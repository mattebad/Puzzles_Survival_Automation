#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Campaign delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    require_operator_evidence,
)
from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    RegisteredDispatchSnapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
PROVING_FLOW_ID = "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE"
AUTO_BATTLE_FLOW_ID = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
DESTINATIONS = ("1-20-9", "1-15-9", "2-2-9")
MAX_PROVING_ATTEMPTS = 25
REQUIRED_CONSECUTIVE_PROVING_CYCLES = 3
CAMPAIGN_RUNNER_ID = "campaign_navigation_only_runner"
CAMPAIGN_EVIDENCE_VALIDATOR_ID = "campaign_navigation_only_evidence"
CAMPAIGN_RECOVERY_HANDLER_ID = "campaign_navigation_only_recovery"
PROVING_RUNNER_ID = "automation_service_campaign_navigation_proving_runner"
PROVING_EVIDENCE_VALIDATOR_ID = "automation_service_campaign_navigation_proving_evidence"
PROVING_RECOVERY_HANDLER_ID = "automation_service_campaign_navigation_proving_recovery"
AUTO_BATTLE_RUNNER_ID = "campaign_auto_battle_live_runner"
AUTO_BATTLE_EVIDENCE_VALIDATOR_ID = "campaign_auto_battle_live_evidence"
AUTO_BATTLE_RECOVERY_HANDLER_ID = "campaign_auto_battle_live_recovery"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _destination_for_attempt(flow: Mapping[str, Any]) -> str:
    pnsctl = _pnsctl()
    finished = [item for item in flow.get("live_attempts", []) if item.get("finished_at")]
    completed = sum(1 for item in finished if item.get("terminal_outcome") == "completed")
    if completed >= len(DESTINATIONS):
        raise pnsctl.OperatorError("all Campaign navigation destinations already completed")
    return DESTINATIONS[completed]


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    payload = (text or "").strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _recognized_fully_zoomed_out(localization: Mapping[str, Any] | None) -> bool:
    if not isinstance(localization, Mapping):
        return False
    return bool(localization.get("recognized")) and localization.get("zoom_identity") == "fully_zoomed_out"


def _return_canonical_sufficient_for_campaign_entry(result: Mapping[str, Any]) -> bool:
    """Accept near-canonical stuck states when Home is already atlas-recognized.

    Campaign entry pans to ``home.building.campaign`` from the current recognized
    fully-zoomed-out viewport. Exact viewport-001 centering is preferred but not
    required once zoom-out has restored canonical localization.
    """

    if result.get("status") == "completed":
        return True
    reason = str(result.get("reason") or "")
    if reason not in {"no_measured_progress", "maximum_pan_count", "repeated_viewport"}:
        return False
    localization = result.get("localization")
    if isinstance(localization, Mapping) and _recognized_fully_zoomed_out(localization):
        return True
    records = result.get("records")
    if not isinstance(records, list) or not records:
        return False
    last = records[-1]
    if not isinstance(last, Mapping):
        return False
    return _recognized_fully_zoomed_out(last.get("localization"))


def _target_roi(recognition: object, identity: str) -> tuple[int, int, int, int] | None:
    targets = getattr(recognition, "targets", ())
    for name, box in targets:
        if name == identity:
            return tuple(int(value) for value in box)
    return None


def _ensure_home_surface_before_prep(session: Path) -> None:
    """Leave Campaign Story surfaces via bound Base/Exit controls before Home Atlas prep.

    Navigation-only canaries may end on the tier map. Zoom-out requires Home, so one
    authorized Base request plus optional highlighted Exit is required before prep.
    """

    import time

    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
    from tasks.campaign_auto_battle_vision import recognize_campaign_frame

    pnsctl = _pnsctl()
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(pnsctl.BLUESTACKS_ADB),
        serial=pnsctl.BLUESTACKS_SERIAL,
        output_directory=session / "campaign-exit-to-home",
        workflow="campaign-exit-to-home",
        execute=True,
    )
    probe_stage = CampaignStage(1, 20, 9)
    records: list[dict[str, object]] = []

    for ordinal in range(6):
        immediate_before = runtime.capture(f"exit-{ordinal:02d}-immediate-before")
        recognition = recognize_campaign_frame(immediate_before.frame, probe_stage)
        screen = recognition.observation.screen
        records.append(
            {
                "ordinal": ordinal,
                "screen": getattr(screen, "name", str(screen)),
                "frame_sha256": recognition.frame_sha256,
                "targets": [name for name, _box in recognition.targets],
            }
        )
        if screen == CampaignScreen.HOME_BASE:
            (session / "campaign-exit-to-home-accepted.json").write_text(
                json.dumps(
                    {
                        "status": "accepted",
                        "reason": "home_base_recognized",
                        "records": records,
                        "session": str(runtime.session),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return

        if screen == CampaignScreen.STAGE_DIALOG:
            close = _target_roi(recognition, "campaign-stage-dialog-close")
            if close is None:
                raise pnsctl.OperatorError(
                    "Campaign stage dialog is open but dialog-close is not bound for Home prep"
                )
            runtime.tap(
                immediate_before,
                target_identity="campaign-stage-dialog-close",
                target_roi=close,
                action_key=f"campaign-stage-dialog-close-{ordinal}-{int(time.time() * 1000)}",
                consequential=False,
            )
            time.sleep(1.2)
            continue

        if screen == CampaignScreen.CHAPTER_MAP:
            back = _target_roi(recognition, "campaign-chapter-back")
            if back is None:
                raise pnsctl.OperatorError(
                    "Campaign chapter map is open but chapter-back is not bound for Home prep"
                )
            runtime.tap(
                immediate_before,
                target_identity="campaign-chapter-back",
                target_roi=back,
                action_key=f"campaign-chapter-back-{ordinal}-{int(time.time() * 1000)}",
                consequential=False,
            )
            time.sleep(1.2)
            continue

        if screen == CampaignScreen.TIER_MAP:
            exit_roi = _target_roi(recognition, "campaign-exit-base")
            request_roi = _target_roi(recognition, "campaign-base-request")
            exit_score = float(recognition.diagnostics.get("campaign_exit_score") or 0.0)
            if exit_roi is None and exit_score >= 0.50:
                from tasks.campaign_auto_battle_vision import CAMPAIGN_EXIT_ROI

                exit_roi = CAMPAIGN_EXIT_ROI
            if exit_roi is not None:
                runtime.tap(
                    immediate_before,
                    target_identity="campaign-exit-base",
                    target_roi=exit_roi,
                    action_key=f"campaign-exit-base-{ordinal}-{int(time.time() * 1000)}",
                    consequential=False,
                )
                time.sleep(1.5)
                continue
            if request_roi is not None:
                runtime.tap(
                    immediate_before,
                    target_identity="campaign-base-request",
                    target_roi=request_roi,
                    action_key=f"campaign-base-request-{ordinal}-{int(time.time() * 1000)}",
                    consequential=False,
                )
                time.sleep(1.2)
                continue
            raise pnsctl.OperatorError(
                "Campaign tier map is open but Base request/Exit controls are not bound"
            )

        raise pnsctl.OperatorError(
            f"Campaign Home prep cannot start from unrecognized screen {screen}"
        )

    raise pnsctl.OperatorError(
        "Campaign exit-to-home did not reach HOME_BASE within bounded navigation-only taps: "
        + json.dumps(records, sort_keys=True)
    )


def _prepare_canonical_home(session: Path) -> None:
    pnsctl = _pnsctl()
    _ensure_home_surface_before_prep(session)
    atlas = REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
    # Viewport reference used by checked-in zoom-out / localize tooling.
    canonical_reference = atlas.parent / "tiles" / "viewport-001.png"
    if not canonical_reference.is_file():
        raise pnsctl.OperatorError("Home Atlas viewport-001.png reference is missing for zoom-out")
    zoom = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
        "zoom-out",
        "--adb",
        str(pnsctl.BLUESTACKS_ADB),
        "--serial",
        pnsctl.BLUESTACKS_SERIAL,
        "--canonical-reference",
        str(canonical_reference),
        "--output-directory",
        str(session / "zoom-out"),
        "--execute",
        "--yes",
    ]
    zoomed = subprocess.run(zoom, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    (session / "zoom-out-stdout.log").write_text(zoomed.stdout or "", encoding="utf-8")
    (session / "zoom-out-stderr.log").write_text(zoomed.stderr or "", encoding="utf-8")
    if zoomed.returncode != 0:
        raise pnsctl.OperatorError(
            "Campaign pre-entry zoom-out failed: "
            f"{zoomed.stderr or zoomed.stdout or 'unknown'}"
        )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
        "return-canonical",
        "--adb",
        str(pnsctl.BLUESTACKS_ADB),
        "--serial",
        pnsctl.BLUESTACKS_SERIAL,
        "--atlas",
        str(atlas),
        "--output-directory",
        str(session / "return-canonical"),
        "--execute",
        "--yes",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    (session / "return-canonical-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (session / "return-canonical-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    result = _parse_json_payload(completed.stdout or "")
    if result is None:
        for candidate in sorted((session / "return-canonical").rglob("return-canonical-result.json")):
            result = _parse_json_payload(candidate.read_text(encoding="utf-8"))
            if result is not None:
                break
    if completed.returncode == 0 and result is not None and result.get("status") == "completed":
        (session / "home-prep-accepted.json").write_text(
            json.dumps(
                {
                    "status": "accepted",
                    "mode": "exact_canonical_viewport",
                    "return_canonical": result,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    if result is not None and _return_canonical_sufficient_for_campaign_entry(result):
        (session / "home-prep-accepted.json").write_text(
            json.dumps(
                {
                    "status": "accepted",
                    "mode": "recognized_fully_zoomed_out_near_canonical",
                    "return_canonical": result,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    raise pnsctl.OperatorError(
        "Campaign pre-entry return-canonical failed: "
        f"{completed.stderr or completed.stdout or 'unknown'}"
    )


def _resolve_campaign_operator_session(session: Path, destination: str) -> Path:
    """Prefer the destination operator session over zoom/return-canonical prep dirs."""

    preferred = sorted(
        path
        for path in session.iterdir()
        if path.is_dir() and path.name.startswith(f"{destination}-") and (path / "result.json").is_file()
    )
    if preferred:
        return preferred[-1]
    with_result = sorted(
        path for path in session.iterdir() if path.is_dir() and (path / "result.json").is_file()
    )
    if with_result:
        return with_result[-1]
    return session


def _run_campaign_navigation_execution(
    *,
    flow_id: str,
    destination: str,
    lease: Mapping[str, Any],
) -> str:
    pnsctl = _pnsctl()
    from automation_service.campaign import CampaignNavigationHandler

    handler = CampaignNavigationHandler(destination)
    if handler.describe().flow_id != FLOW_ID:
        raise pnsctl.OperatorError("automation-service Campaign handler identity mismatch")
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / flow_id / f"nav-{destination}-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    _prepare_canonical_home(session)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_campaign_ap.py"),
        "--adb",
        str(pnsctl.BLUESTACKS_ADB),
        "--serial",
        pnsctl.BLUESTACKS_SERIAL,
        "--stage",
        destination,
        "--ap-cost",
        "16",
        "--ap-budget",
        "16",
        "--max-runs",
        "1",
        "--navigation-only",
        "--execute",
        "--yes",
        "--output-directory",
        str(session),
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    (session / "operator-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (session / "operator-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    campaign_session = _resolve_campaign_operator_session(session, destination)
    try:
        campaign_result, frame_names = require_operator_evidence(campaign_session)
    except FlowEvidenceIntegrityError as exc:
        raise pnsctl.OperatorError(
            f"Campaign executable/evidence-integrity failure: {exc}"
        ) from exc
    ok = completed.returncode == 0 and campaign_result.get("terminal") == "navigation_only_complete"
    events_rel = "events.jsonl"
    delivery = {
        "schema_version": 1,
        "flow_id": flow_id,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if ok else "safe_blocked_terminal",
        "destination": destination,
        "campaign_result": campaign_result,
        "actions": [
            {
                "action_class": "navigation_only",
                "destination": destination,
                "outcome": campaign_result.get("status") or "failed",
            }
        ],
        "events_path": events_rel,
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
        "automation_service_handler": handler.summarize(),
    }
    (campaign_session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not ok:
        raise pnsctl.OperatorError(
            f"Campaign navigation-only failed for {destination}: "
            f"{campaign_result.get('reason') or completed.stderr or completed.stdout or 'unknown'}"
        )
    return json.dumps(
        {
            "status": "completed",
            "flow_id": flow_id,
            "destination": destination,
            "session_directory": str(campaign_session),
            "dispatch": True,
        },
        sort_keys=True,
    )


def run_campaign_navigation_only(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    return _run_campaign_navigation_execution(
        flow_id=FLOW_ID,
        destination=_destination_for_attempt(flow),
        lease=lease,
    )


def _proving_result_summary(root: Path) -> tuple[int, int, dict[str, int]]:
    records: list[tuple[str, Mapping[str, Any]]] = []
    attempt_directories = (
        sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and path.name.startswith("nav-")
            ),
            key=lambda path: path.name.rsplit("-", 1)[-1],
        )
        if root.is_dir()
        else ()
    )
    for attempt in attempt_directories:
        result_paths = sorted(attempt.rglob("flow-delivery-result.json"))
        payload: Mapping[str, Any] = {
            "flow_id": PROVING_FLOW_ID,
            "status": "failed",
        }
        for path in reversed(result_paths):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if candidate.get("flow_id") == PROVING_FLOW_ID:
                payload = candidate
                break
        records.append((attempt.name, payload))
    successful_by_destination = {destination: 0 for destination in DESTINATIONS}
    for _path, payload in records:
        if (
            payload.get("status") == "completed"
            and payload.get("destination") in successful_by_destination
        ):
            successful_by_destination[str(payload["destination"])] += 1
    trailing_successes = 0
    for _path, payload in reversed(records):
        if payload.get("status") != "completed":
            break
        trailing_successes += 1
    return len(records), trailing_successes, successful_by_destination


def run_campaign_navigation_proving_slice(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue
    pnsctl = _pnsctl()
    root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / PROVING_FLOW_ID
    attempt_count, trailing_successes, successful_by_destination = _proving_result_summary(root)
    if trailing_successes >= REQUIRED_CONSECUTIVE_PROVING_CYCLES:
        raise pnsctl.OperatorError("Campaign navigation proving-slice is already complete")
    if attempt_count >= MAX_PROVING_ATTEMPTS:
        raise pnsctl.OperatorError("Campaign navigation proving-slice attempt budget is exhausted")
    destination = min(
        DESTINATIONS,
        key=lambda item: (successful_by_destination[item], DESTINATIONS.index(item)),
    )
    return _run_campaign_navigation_execution(
        flow_id=PROVING_FLOW_ID,
        destination=destination,
        lease=lease,
    )


def verify_campaign_navigation_only(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    # Queue destination arrays were removed; allowlist is DESTINATIONS only (no product-policy load).
    del queue, lease
    result = structure["result"]
    if result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Campaign evidence belongs to another flow")
    destination = result.get("destination")
    if destination not in DESTINATIONS:
        raise pnsctl.OperatorError("Campaign evidence destination is not authorized")
    campaign = result.get("campaign_result") or {}
    if campaign.get("terminal") != "navigation_only_complete":
        raise pnsctl.OperatorError("Campaign evidence is not navigation_only_complete")
    if result.get("terminal_runtime_state") != "recognized_home":
        raise pnsctl.OperatorError("Campaign evidence terminal runtime state is unsafe")
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "destination": destination,
        "session_directory": structure["session_directory"],
        "actions": structure["actions"],
        "terminal_runtime_state": result["terminal_runtime_state"],
    }


def verify_campaign_navigation_proving_slice(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    pnsctl = _pnsctl()
    result = structure["result"]
    if result.get("flow_id") != PROVING_FLOW_ID:
        raise pnsctl.OperatorError("Campaign proving evidence belongs to another flow")
    destination = result.get("destination")
    if destination not in DESTINATIONS:
        raise pnsctl.OperatorError("Campaign proving destination is not authorized")
    campaign = result.get("campaign_result") or {}
    if campaign.get("terminal") != "navigation_only_complete":
        raise pnsctl.OperatorError("Campaign proving evidence is not navigation_only_complete")
    handler = result.get("automation_service_handler") or {}
    if (
        handler.get("flow_id") != FLOW_ID
        or handler.get("mode") != "navigation_only"
        or handler.get("transport_count") != 0
    ):
        raise pnsctl.OperatorError("Campaign proving evidence lacks the service handler boundary")
    if result.get("terminal_runtime_state") != "recognized_home":
        raise pnsctl.OperatorError("Campaign proving evidence terminal runtime state is unsafe")
    return {
        "status": "verified",
        "flow_id": PROVING_FLOW_ID,
        "destination": destination,
        "session_directory": structure["session_directory"],
        "actions": structure["actions"],
        "terminal_runtime_state": result["terminal_runtime_state"],
    }


def recover_campaign_navigation_only(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    pnsctl = _pnsctl()
    del queue, lease
    state = str(pnsctl._run_fixed_bluestacks_adb("get-state")).strip()
    if state != "device":
        raise pnsctl.OperatorError("approved BlueStacks serial is not in device state")
    focus = str(pnsctl._run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    package = pnsctl._focused_package(focus)
    if package != pnsctl.PACKAGE:
        raise pnsctl.OperatorError("Puzzles & Survival is not the foreground package during recovery")
    return json.dumps(
        {
            "status": "recovered_or_already_safe",
            "flow_id": FLOW_ID,
            "foreground_package": package,
            "dispatch": False,
            "recovery": "observe_only_no_android_back",
        },
        sort_keys=True,
    )


def recover_campaign_navigation_proving_slice(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    result = json.loads(recover_campaign_navigation_only(queue, lease))
    result["flow_id"] = PROVING_FLOW_ID
    return json.dumps(result, sort_keys=True)


MAX_INPUTS = 12
CAMPAIGN_DEFAULT_DESTINATION = "1-15-9"
CAMPAIGN_STAGE_COSTS = {"1-20-9": 16, "1-15-9": 14, "2-2-9": 20}


def _campaign_registration_snapshot(
    lease: Mapping[str, Any],
) -> RegisteredDispatchSnapshot:
    snapshot = lease.get("registration_snapshot")
    if not isinstance(snapshot, RegisteredDispatchSnapshot):
        raise _pnsctl().OperatorError(
            "Campaign AP requires a typed registration snapshot before observation"
        )
    if snapshot.flow_id != CAMPAIGN_FLOW_ID:
        raise _pnsctl().OperatorError(
            "Campaign AP registration snapshot has the wrong flow identity"
        )
    return snapshot


def _campaign_maximum(lease: Mapping[str, Any]) -> int:
    try:
        maximum = int(lease.get("max_inputs", MAX_INPUTS))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Campaign AP development-session max_inputs must be an integer"
        ) from exc
    if maximum != MAX_INPUTS:
        raise _pnsctl().OperatorError(
            "Campaign AP continuous session requires exact 12-input cap"
        )
    return maximum


def _campaign_outer_session(lease: Mapping[str, Any]):
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{AUTO_BATTLE_FLOW_ID}"
        or not callable(getattr(session, "adopt_retained_transport_count", None))
    ):
        raise _pnsctl().OperatorError(
            "Campaign AP requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _campaign_initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Campaign AP initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Campaign AP initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Campaign AP initial observation hash or invocation binding is invalid"
        )
    return value.to_mapping()


def _campaign_event_rows(session: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for events_path in session.rglob("events.jsonl"):
        if not events_path.is_file() or events_path.is_symlink():
            continue
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _campaign_transport_count(session: Path) -> int:
    return sum(
        (
            row.get("type") == "dispatch"
            and row.get("execute") is not False
        )
        or (
            row.get("type") == "command"
            and row.get("kind") in {"tap", "swipe"}
        )
        for row in _campaign_event_rows(session)
    )


def _campaign_action_count(campaign_result: Mapping[str, Any]) -> int:
    progress = campaign_result.get("progress")
    if not isinstance(progress, Mapping):
        return 0
    try:
        return int(progress.get("completed_runs") or 0)
    except (TypeError, ValueError):
        return 0


def _campaign_result_payload(
    route_result: Mapping[str, Any],
    *,
    session_directory: Path,
    input_count: int,
    maximum: int,
    destination: str,
    ap_cost: int,
    registration_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    campaign = route_result.get("campaign_result")
    campaign = campaign if isinstance(campaign, Mapping) else {}
    ap_before = campaign.get("ap_before")
    ap_after = campaign.get("ap_after")
    try:
        exact_ap_delta = (
            type(ap_before) is int
            and type(ap_after) is int
            and ap_before - ap_after == ap_cost
        )
    except (TypeError, ValueError):
        exact_ap_delta = False
    progress = campaign.get("progress")
    progress = progress if isinstance(progress, Mapping) else {}
    destination_match = campaign.get("destination") == destination
    cost_match = campaign.get("ap_cost") == ap_cost
    ledger_match = progress.get("ap_spent") == ap_cost
    forbidden_action_seen = any(
        any(
            marker in str(row.get("action") or "").casefold()
            or marker in str(row.get("target_identity") or "").casefold()
            for marker in ("sweep", "blitz", "auto_complete", "refill")
        )
        for row in _campaign_event_rows(session_directory)
        if row.get("type") == "command"
    )
    refill_action_seen = any(
        "refill" in str(row.get("action") or "").casefold()
        or "refill" in str(row.get("target_identity") or "").casefold()
        for row in _campaign_event_rows(session_directory)
        if row.get("type") == "command"
    )
    refill_forbidden_verified = not refill_action_seen
    safe_action_policy = not forbidden_action_seen
    route_status = str(route_result.get("status") or "blocked")
    terminal_home = route_result.get("terminal_runtime_state") == "recognized_home"
    outcome = campaign.get("battle_outcome")
    result_successor = outcome in {"victory", "defeat"}
    action_count = _campaign_action_count(campaign)
    completed = bool(
        route_status == "completed"
        and route_result.get("terminal") == "completed"
        and route_result.get("navigation_only") is False
        and terminal_home
        and exact_ap_delta
        and result_successor
        and destination_match
        and cost_match
        and ledger_match
        and safe_action_policy
        and refill_forbidden_verified
        and action_count == 1
    )
    reconciliation_required = bool(input_count and not completed)
    status = (
        "completed"
        if completed
        else "effect_reconciliation_required"
        if reconciliation_required
        else "blocked"
    )
    payload = dict(route_result)
    payload.update(
        {
            "status": status,
            "flow_id": AUTO_BATTLE_FLOW_ID,
            "session_directory": str(session_directory),
            "input_count": input_count,
            "max_inputs": maximum,
            "dispatch": input_count > 0,
            "campaign_transport_count": input_count,
            "campaign_action_count": action_count,
            "destination": destination,
            "ap_cost": ap_cost,
            "ap_before": ap_before,
            "ap_after": ap_after,
            "exact_ap_delta": exact_ap_delta,
            "destination_match": destination_match,
            "cost_match": cost_match,
            "ledger_match": ledger_match,
            "result_successor_verified": result_successor,
            "terminal_home_verified": terminal_home,
            "forbidden_action_seen": forbidden_action_seen,
            "safe_action_policy": safe_action_policy,
            "refill_forbidden_verified": refill_forbidden_verified,
            "proof_topology": "continuous",
            "effect_reconciliation_required": reconciliation_required,
            "identical_retry_denied": reconciliation_required,
            "registration_snapshot": dict(registration_snapshot),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    )
    if not exact_ap_delta or not ledger_match:
        payload["reason"] = "Campaign AP ledger does not equal configured cost"
    elif not destination_match or not cost_match:
        payload["reason"] = "Campaign stage or configured AP cost is not bound"
    elif forbidden_action_seen:
        payload["reason"] = "Campaign route emitted a forbidden action"
    elif not result_successor:
        payload["reason"] = "Campaign result successor is not positively recognized"
    elif not terminal_home:
        payload["reason"] = "Campaign terminal Home is not recognized"
    return payload


def _campaign_causal_trace(
    session: Path,
    *,
    result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
    registration_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _campaign_event_rows(session)
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "proof_topology": "continuous",
        "flow_id": AUTO_BATTLE_FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "registration_snapshot": dict(registration_snapshot),
        "stages": [
            "typed_initial_observation",
            "canonical_home_atlas_binding",
            "campaign_stage_cost_binding",
            "campaign_auto_battle",
            "exact_ap_ledger",
            "battle_result_successor",
            "canonical_home_terminal",
        ],
        "transport_count": int(result.get("campaign_transport_count") or 0),
        "campaign_action_count": int(result.get("campaign_action_count") or 0),
        "event_count": len(rows),
        "status": str(result.get("status") or "unknown"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
    }
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return trace


def _write_campaign_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
    causal_trace: Mapping[str, Any],
) -> None:
    session.mkdir(parents=True, exist_ok=True)
    frames = (
        sorted(
            path.relative_to(session).as_posix()
            for path in session.rglob("*.png")
            if path.is_file() and not path.is_symlink()
        )
        if session.is_dir()
        else []
    )
    payload = {
        "schema_version": 1,
        "flow_id": AUTO_BATTLE_FLOW_ID,
        "status": result.get("status"),
        "serial": _pnsctl().BLUESTACKS_SERIAL,
        "native_width": _pnsctl().BLUESTACKS_NATIVE_WIDTH,
        "native_height": _pnsctl().BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": (
            "recognized_home"
            if result.get("terminal_home_verified") is True
            else "safe_blocked_terminal"
        ),
        "actions": [
            {
                "action_class": "campaign_ap_auto_battle",
                "destination": result.get("destination"),
                "outcome": result.get("battle_outcome"),
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path", "causal_trace_path"],
        "events_path": "events.jsonl",
        "causal_trace_path": "causal-trace.json",
        "initial_observation": dict(initial_observation),
        "initial_frame_sha256": initial_observation.get("frame_sha256"),
        "causal_trace_count": 1,
        "causal_trace": dict(causal_trace),
        **dict(result),
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _run_campaign_auto_battle_continuous(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue
    registration = _campaign_registration_snapshot(lease)
    registration_snapshot = registration.to_mapping()
    maximum = _campaign_maximum(lease)
    outer_session = _campaign_outer_session(lease)
    initial_observation = _campaign_initial_observation(lease, outer_session)
    outer_directory = Path(outer_session.session_directory)
    runtime_directory = outer_directory / "runtime"
    runtime_directory.mkdir(parents=True, exist_ok=True)
    destination = str(
        lease.get("campaign_stage") or CAMPAIGN_DEFAULT_DESTINATION
    )
    if destination not in CAMPAIGN_STAGE_COSTS:
        raise _pnsctl().OperatorError(
            f"Campaign AP destination is unsupported: {destination}"
        )
    ap_cost = CAMPAIGN_STAGE_COSTS[destination]
    child = runtime_directory
    try:
        pnsctl = _pnsctl()
        _ensure_home_surface_before_prep(runtime_directory)
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bluestacks_campaign_ap.py"),
            "--adb",
            str(pnsctl.BLUESTACKS_ADB),
            "--serial",
            pnsctl.BLUESTACKS_SERIAL,
            "--stage",
            destination,
            "--ap-cost",
            str(ap_cost),
            "--ap-budget",
            str(ap_cost),
            "--max-runs",
            "1",
            "--execute",
            "--yes",
            "--output-directory",
            str(runtime_directory),
        ]
        completed_process = subprocess.run(
            command, cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
        (runtime_directory / "operator-stdout.log").write_text(
            completed_process.stdout or "", encoding="utf-8"
        )
        (runtime_directory / "operator-stderr.log").write_text(
            completed_process.stderr or "", encoding="utf-8"
        )
        child = _resolve_campaign_operator_session(runtime_directory, destination)
        result_path = child / "result.json"
        campaign_result = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.is_file()
            else {}
        )
        route_result = {
            "status": "completed"
            if completed_process.returncode == 0
            else "blocked",
            "terminal": campaign_result.get("terminal"),
            "navigation_only": campaign_result.get("navigation_only"),
            "terminal_runtime_state": "recognized_home"
            if completed_process.returncode == 0
            else "safe_blocked_terminal",
            "campaign_result": campaign_result,
            "operator_returncode": completed_process.returncode,
        }
        if not campaign_result:
            route_result["reason"] = (
                completed_process.stderr
                or completed_process.stdout
                or "Campaign Auto Battle result.json is missing"
            )
    except Exception as exc:
        route_result = {
            "status": "unresolved",
            "reason": f"{type(exc).__name__}: {exc}",
            "terminal_runtime_state": "safe_blocked_terminal",
            "campaign_result": {},
        }
    input_count = _campaign_transport_count(runtime_directory)
    if input_count > maximum:
        raise _pnsctl().OperatorError("Campaign AP exceeded max_inputs")
    payload = _campaign_result_payload(
        route_result,
        session_directory=child,
        input_count=input_count,
        maximum=maximum,
        destination=destination,
        ap_cost=ap_cost,
        registration_snapshot=registration_snapshot,
    )
    if child != runtime_directory:
        source_path = outer_directory / "source.png"
        if source_path.is_file():
            retained_initial = child / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            retained_initial.write_bytes(source_path.read_bytes())
            initial_observation = dict(initial_observation)
            initial_observation["frame_path"] = (
                "frames/0000-initial-observation.png"
            )
    trace = _campaign_causal_trace(
        child,
        result=payload,
        initial_observation=initial_observation,
        registration_snapshot=registration_snapshot,
    )
    payload["initial_observation"] = initial_observation
    payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
    payload["causal_trace_count"] = 1
    payload["causal_trace"] = trace
    outer_session.adopt_retained_transport_count(
        input_count,
        source="runtime_session/events.jsonl",
    )
    outer_session.remember_control("campaign_transport_count", input_count)
    outer_session.remember_control(
        "campaign_action_count", payload["campaign_action_count"]
    )
    outer_session.set_causal_trace(trace)
    _write_campaign_delivery_result(
        child,
        payload,
        lease=lease,
        initial_observation=initial_observation,
        causal_trace=trace,
    )
    return json.dumps(payload, sort_keys=True, default=str)


def run_campaign_auto_battle_live(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": AUTO_BATTLE_FLOW_ID,
                "dispatch": False,
                "input_count": 0,
                "max_inputs": MAX_INPUTS,
                "proof_topology": "continuous",
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    if "development_session" not in lease:
        raise _pnsctl().OperatorError(
            "Campaign AP requires the active pnsctl-owned DevelopmentSession"
        )
    return _run_campaign_auto_battle_continuous(queue, lease)


def verify_campaign_auto_battle_live(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Campaign Auto Battle delivery result is missing")
    if result.get("flow_id") != AUTO_BATTLE_FLOW_ID:
        raise _pnsctl().OperatorError("Campaign Auto Battle evidence belongs to another flow")
    session = Path(str(structure.get("session_directory") or ""))
    campaign = result.get("campaign_result")
    if not isinstance(campaign, Mapping):
        raise _pnsctl().OperatorError("Campaign Auto Battle campaign result is missing")
    if (
        campaign.get("status") != "completed"
        or campaign.get("terminal") != "completed"
        or campaign.get("navigation_only") is not False
        or campaign.get("battle_outcome") not in {"victory", "defeat"}
    ):
        raise _pnsctl().OperatorError(
            "Campaign Auto Battle consequence/result contract failed"
        )
    destination = result.get("destination")
    ap_cost = result.get("ap_cost")
    progress = campaign.get("progress")
    progress = progress if isinstance(progress, Mapping) else {}
    ledger_ok = (
        campaign.get("destination") == destination
        and campaign.get("ap_cost") == ap_cost
        and progress.get("ap_spent") == ap_cost
        and result.get("exact_ap_delta") is True
    )
    if not ledger_ok:
        raise _pnsctl().OperatorError(
            "Campaign AP ledger or configured stage does not match authority"
        )
    initial = result.get("initial_observation")
    initial_ok = False
    if isinstance(initial, Mapping):
        frame_path = session / str(initial.get("frame_path") or "")
        try:
            frame_path.resolve().relative_to(session.resolve())
            initial_ok = (
                frame_path.is_file()
                and not frame_path.is_symlink()
                and hashlib.sha256(frame_path.read_bytes()).hexdigest()
                == initial.get("frame_sha256")
                == result.get("initial_frame_sha256")
                and bool(initial.get("invocation_id"))
            )
        except (OSError, ValueError):
            initial_ok = False
    transport_scope = session.parent if session.parent.name == "runtime" else session
    retained_transport = _campaign_transport_count(transport_scope)
    trace = result.get("causal_trace")
    trace_path = session / str(result.get("causal_trace_path") or "causal-trace.json")
    trace_file_ok = False
    try:
        trace_path.resolve().relative_to(session.resolve())
        trace_file_ok = (
            trace_path.is_file()
            and not trace_path.is_symlink()
            and json.loads(trace_path.read_text(encoding="utf-8")) == trace
        )
    except (OSError, ValueError, json.JSONDecodeError):
        trace_file_ok = False
    trace_ok = bool(
        isinstance(trace, Mapping)
        and trace_file_ok
        and result.get("causal_trace_count") == 1
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("proof_topology") == "continuous"
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("campaign_action_count") == result.get("campaign_action_count")
    )
    registration_ok = False
    try:
        registration = RegisteredDispatchSnapshot.from_mapping(
            result.get("registration_snapshot")
        )
        expected_registration = registration.to_mapping()
        registration_ok = bool(
            registration.flow_id == CAMPAIGN_FLOW_ID
            and dict(result.get("registration_snapshot") or {})
            == expected_registration
            and isinstance(trace, Mapping)
            and trace.get("registration_snapshot") == expected_registration
        )
    except (TypeError, ValueError):
        registration_ok = False
    verified = bool(
        result.get("status") == "completed"
        and result.get("proof_topology") == "continuous"
        and initial_ok
        and trace_ok
        and retained_transport == result.get("input_count")
        and retained_transport == result.get("campaign_transport_count")
        and type(result.get("max_inputs")) is int
        and retained_transport <= result.get("max_inputs")
        and result.get("campaign_action_count") == 1
        and result.get("destination_match") is True
        and result.get("cost_match") is True
        and result.get("ledger_match") is True
        and result.get("safe_action_policy") is True
        and result.get("refill_forbidden_verified") is True
        and result.get("production_registration") == "NOT_REGISTERED"
        and result.get("scheduler_enabled") is False
        and registration_ok
        and result.get("terminal_home_verified") is True
        and result.get("effect_reconciliation_required") is False
        and result.get("identical_retry_denied") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": AUTO_BATTLE_FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": result.get("production_registration"),
        "scheduler_enabled": result.get("scheduler_enabled"),
        "registration_verified": registration_ok,
        "initial_observation_verified": initial_ok,
        "causal_trace_verified": trace_ok,
        "retained_transport_count": retained_transport,
        "campaign_transport_count": result.get("campaign_transport_count"),
        "campaign_action_count": result.get("campaign_action_count"),
        "reason": None if verified else "Campaign continuous route proof is incomplete",
    }


def recover_campaign_auto_battle_live(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    del queue, lease
    pnsctl = _pnsctl()
    session = (
        pnsctl.BLUESTACKS_ARTIFACT_ROOT
        / AUTO_BATTLE_FLOW_ID
        / f"recovery-home-{_utc_stamp()}"
    )
    session.mkdir(parents=True, exist_ok=False)
    _prepare_canonical_home(session)
    return json.dumps(
        {
            "status": "recovered",
            "flow_id": AUTO_BATTLE_FLOW_ID,
            "terminal_runtime_state": "recognized_home",
            "session_directory": str(session),
            "dispatch": True,
            "recovery": "campaign_safe_exit_then_canonical_home",
        },
        sort_keys=True,
    )


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[CAMPAIGN_RUNNER_ID] = run_campaign_navigation_only
    validators[CAMPAIGN_EVIDENCE_VALIDATOR_ID] = verify_campaign_navigation_only
    handlers[CAMPAIGN_RECOVERY_HANDLER_ID] = recover_campaign_navigation_only
    runners[PROVING_RUNNER_ID] = run_campaign_navigation_proving_slice
    validators[PROVING_EVIDENCE_VALIDATOR_ID] = verify_campaign_navigation_proving_slice
    handlers[PROVING_RECOVERY_HANDLER_ID] = recover_campaign_navigation_proving_slice
    runners[AUTO_BATTLE_RUNNER_ID] = run_campaign_auto_battle_live
    validators[AUTO_BATTLE_EVIDENCE_VALIDATOR_ID] = verify_campaign_auto_battle_live
    handlers[AUTO_BATTLE_RECOVERY_HANDLER_ID] = recover_campaign_auto_battle_live
