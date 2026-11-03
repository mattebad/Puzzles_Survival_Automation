#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Campaign delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

from tasks.campaign_auto_battle import CAMPAIGN_MAX_INPUTS, CAMPAIGN_STAGE_COSTS

from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    require_operator_evidence,
)
from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    RegisteredDispatchSnapshot,
)
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_PACKAGE, BLUESTACKS_SERIAL


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


def _ensure_home_surface_before_prep(
    session: Path,
    *,
    task_id: str = FLOW_ID,
    recovery_scope: str | None = None,
    startup_recovery: Mapping[str, object] | None = None,
    max_inputs: int = 6,
    runtime=None,
    probe_stage=None,
) -> dict[str, object]:
    """Leave Campaign Story surfaces via bound Base/Exit controls before Home Atlas prep.

    Navigation-only canaries may end on the tier map. Zoom-out requires Home, so one
    authorized Base request plus optional highlighted Exit is required before prep.
    """

    import time

    from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
    from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
    from tasks.campaign_auto_battle_vision import recognize_campaign_frame

    pnsctl = _pnsctl()
    if type(max_inputs) is not int or max_inputs < 0:
        raise pnsctl.OperatorError("Campaign Home prep input budget is invalid")
    provided_runtime = runtime is not None
    runtime = runtime or LocalBlueStacksRuntime.connect(
        adb=str(BLUESTACKS_ADB),
        serial=BLUESTACKS_SERIAL,
        output_directory=session / "campaign-exit-to-home",
        workflow="campaign-exit-to-home",
        execute=True,
    )
    probe_stage = probe_stage or CampaignStage(1, 20, 9)
    # Startup overlays are recovered once by pnsctl before the typed route
    # observation. This route-owned helper only normalizes Campaign surfaces.
    startup_recovery = dict(
        startup_recovery
        or {
            "status": "shared_pre_flow_startup_recovery",
            "flow_id": task_id,
            "recovery_scope": recovery_scope,
            "input_count": 0,
        }
    )
    records: list[dict[str, object]] = []
    base_request_sent = False
    lineup_back_sent = False
    lineup_parent_pending = False
    input_count = 0

    def tap_navigation(before, **kwargs):
        nonlocal input_count
        if input_count >= max_inputs:
            raise pnsctl.OperatorError("Campaign Home prep input budget exhausted before dispatch")
        input_count += 1
        runtime.tap(before, **kwargs)

    for ordinal in range(6):
        immediate_before = runtime.capture(f"exit-{ordinal:02d}-immediate-before")
        recognition = recognize_campaign_frame(immediate_before.frame, probe_stage)
        screen = recognition.observation.screen
        if (provided_runtime and (recognition.observation.recognized is not True
                or recognition.observation.overlay_state not in {"none", "none_observed"})):
            raise pnsctl.OperatorError("Campaign Home prep requires a clear recognized surface")
        records.append(
            {
                "ordinal": ordinal,
                "screen": getattr(screen, "name", str(screen)),
                "frame_sha256": recognition.frame_sha256,
                "targets": [name for name, _box in recognition.targets],
            }
        )
        if lineup_parent_pending:
            if (recognition.observation.recognized is not True
                    or screen not in {CampaignScreen.STAGE_DIALOG, CampaignScreen.CHAPTER_MAP}):
                raise pnsctl.OperatorError("Campaign Lineup Back did not reach a recognized Story parent")
            lineup_parent_pending = False
        if screen == CampaignScreen.HOME_BASE and recognition.observation.recognized is True:
            (session / "campaign-exit-to-home-accepted.json").write_text(
                json.dumps(
                    {
                        "status": "accepted",
                        "reason": "home_base_recognized",
                        "records": records,
                        "session": str(runtime.session),
                        "startup_recovery": startup_recovery,
                        "input_count": input_count,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return startup_recovery

        if screen == CampaignScreen.HERO_LINEUP:
            back = _target_roi(recognition, "campaign-lineup-back")
            if lineup_back_sent or recognition.observation.recognized is not True or back is None:
                raise pnsctl.OperatorError("Campaign Hero Lineup lacks one unused bound game Back control")
            tap_navigation(
                immediate_before,
                target_identity="campaign-lineup-back",
                target_roi=back,
                action_key=f"campaign-lineup-back-{ordinal}-{int(time.time() * 1000)}",
                consequential=False,
            )
            lineup_back_sent = lineup_parent_pending = True
            time.sleep(1.2)
            continue

        if screen == CampaignScreen.STAGE_DIALOG:
            close = _target_roi(recognition, "campaign-stage-dialog-close")
            if close is None:
                raise pnsctl.OperatorError(
                    "Campaign stage dialog is open but dialog-close is not bound for Home prep"
                )
            tap_navigation(
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
            tap_navigation(
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
            if exit_roi is not None:
                tap_navigation(
                    immediate_before,
                    target_identity="campaign-exit-base",
                    target_roi=exit_roi,
                    action_key=f"campaign-exit-base-{ordinal}-{int(time.time() * 1000)}",
                    consequential=False,
                )
                time.sleep(1.5)
                continue
            if request_roi is not None:
                if base_request_sent:
                    raise pnsctl.OperatorError(
                        "Campaign exit did not appear after one Base request"
                    )
                tap_navigation(
                    immediate_before,
                    target_identity="campaign-base-request",
                    target_roi=request_roi,
                    action_key=f"campaign-base-request-{ordinal}-{int(time.time() * 1000)}",
                    consequential=False,
                )
                base_request_sent = True
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


def _prepare_canonical_home(
    session: Path,
    *,
    startup_recovery: Mapping[str, object] | None = None,
) -> None:
    pnsctl = _pnsctl()
    _ensure_home_surface_before_prep(session, startup_recovery=startup_recovery)
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
        str(BLUESTACKS_ADB),
        "--serial",
        BLUESTACKS_SERIAL,
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
        str(BLUESTACKS_ADB),
        "--serial",
        BLUESTACKS_SERIAL,
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
    try:
        route_maximum = int(lease.get("route_max_inputs", lease.get("max_inputs", MAX_INPUTS)))
    except (TypeError, ValueError) as exc:
        raise pnsctl.OperatorError("Campaign navigation route_max_inputs must be an integer") from exc
    if not 1 <= route_maximum <= MAX_INPUTS:
        raise pnsctl.OperatorError("Campaign navigation route_max_inputs is outside the session ceiling")
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / flow_id / f"nav-{destination}-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    _prepare_canonical_home(
        session,
        startup_recovery=lease.get("startup_recovery_result"),
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_campaign_ap.py"),
        "--adb",
        str(BLUESTACKS_ADB),
        "--serial",
        BLUESTACKS_SERIAL,
        "--stage",
        destination,
        "--ap-cost",
        "16",
        "--ap-budget",
        "16",
        "--max-runs",
        "1",
        "--max-inputs",
        str(route_maximum),
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
        "serial": BLUESTACKS_SERIAL,
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
    if package != BLUESTACKS_PACKAGE:
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


MAX_INPUTS = CAMPAIGN_MAX_INPUTS


def _campaign_maximum(lease: Mapping[str, Any]) -> int:
    try:
        maximum = int(lease.get("max_inputs", MAX_INPUTS))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Campaign AP development-session max_inputs must be an integer"
        ) from exc
    if not 1 <= maximum <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Campaign AP input ceiling must be between 1 and {MAX_INPUTS}"
        )
    route_maximum = lease.get("route_max_inputs")
    if route_maximum is not None:
        try:
            route_maximum = int(route_maximum)
        except (TypeError, ValueError) as exc:
            raise _pnsctl().OperatorError(
                "Campaign AP route_max_inputs must be an integer"
            ) from exc
        if not 1 <= route_maximum <= maximum:
            raise _pnsctl().OperatorError(
                "Campaign AP route_max_inputs is outside the shared session reserve"
            )
        maximum = route_maximum
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
        # In-process callers may already have native captures in events.jsonl.
        # Their semantic Campaign steps use a separate stream.
        campaign_steps = events_path.with_name("campaign-events.jsonl")
        if campaign_steps.is_file():
            events_path = campaign_steps
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
    total = 0
    directories = {path.parent for pattern in ("events.jsonl", "native-events.jsonl")
                   for path in session.rglob(pattern) if path.is_file() and not path.is_symlink()}
    for directory in directories:
        native = directory / "native-events.jsonl"
        native_stream = native.is_file() or (directory / "campaign-events.jsonl").is_file()
        path = native if native.is_file() else directory / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        count = sum(isinstance(row, dict) and (
            (row.get("type") == "dispatch" and row.get("execute") is not False)
            or (not native_stream and row.get("type") == "command" and row.get("kind") in {"tap", "swipe"})
        ) for row in rows)
        if native_stream and (directory / "result.json").is_file():
            result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            observed = result.get("total_input_count") if isinstance(result, dict) else None
            # Native input reservations can precede a checkpoint/ledger failure.
            # Retain those attempted inputs; never count the semantic command twice.
            if (type(observed) is int and count <= observed <= MAX_INPUTS
                    and result.get("input_count") == observed
                    and result.get("native_events_path") == str(path)):
                count = observed
        total += count
    return total


def _campaign_action_count(campaign_result: Mapping[str, Any]) -> int:
    progress = campaign_result.get("progress")
    if not isinstance(progress, Mapping):
        return 0
    count = progress.get("completed_runs")
    return count if type(count) is int and count >= 0 else 0


def _campaign_progress_valid(progress: Any) -> bool:
    if not isinstance(progress, Mapping):
        return False
    integer_fields = ("initial_ap", "current_ap", "ap_spent", "completed_runs", "ap_regenerated")
    if any(type(progress.get(key)) is not int or progress[key] < 0 for key in integer_fields):
        return False
    return (
        progress["current_ap"] == progress["initial_ap"] - progress["ap_spent"] + progress["ap_regenerated"]
        and type(progress.get("loss_seen")) is bool
    )


def _campaign_unconsumed_progress(progress: Any) -> bool:
    return (
        _campaign_progress_valid(progress) and progress["ap_spent"] == 0
        and progress["completed_runs"] == 0 and progress["loss_seen"] is False
    )


def _campaign_navigation_only_trace(rows: Sequence[Mapping[str, Any]], input_count: int) -> bool:
    """Prove every counted input was pre-battle navigation, or stay uncertain."""
    counted = []
    for row in rows:
        progress = row.get("progress")
        if "progress" in row and not _campaign_unconsumed_progress(progress):
            return False
        if row.get("type") == "dispatch":
            if row.get("execute") is False:
                continue
            if row.get("execute") is not True or row.get("consequential") is not False or row.get("target_identity") not in {
                "home-zoom-out", "home.building.campaign", "home-camera-click-drag",
                "campaign-stage-dialog-close", "campaign-chapter-back",
                "campaign-base-request", "campaign-exit-base",
            }:
                return False
            if re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256") or "")) is None:
                return False
            counted.append(row)
        elif row.get("type") == "command":
            if not isinstance(progress, Mapping):
                return False
            action = row.get("action")
            target = str(row.get("target_identity") or "")
            kind = row.get("kind")
            if kind == "home_atlas_entry" and action == "OPEN_CAMPAIGN" and target == "home.building.campaign":
                continue
            if kind == "terminal" and action == "BLOCKED":
                continue
            if action == "SELECT_TIER":
                known = kind == "tap" and target in {"campaign-tier-1", "campaign-tier-2"}
            elif action == "NAVIGATE_CHAPTER":
                known = (
                    kind == "swipe" and row.get("target_identity") is None
                ) or (kind == "tap" and re.fullmatch(r"campaign-chapter-\d+", target) is not None)
            elif action == "SELECT_STAGE":
                known = kind == "tap" and re.fullmatch(r"campaign-stage-\d+-\d+-\d+", target) is not None
            else:
                known = False
            if not known:
                return False
            counted.append(row)
        elif row.get("type") not in {
            "observation", "capture", "home_atlas_entry_verified", "home_atlas_entry_result",
        }:
            return False
    return input_count > 0 and len(counted) == input_count


def _campaign_victory_recovery_inputs(rows: Sequence[Mapping[str, Any]]) -> bool:
    allowed = {
        "CONTINUE_VICTORY": {"campaign-victory-continue"},
        "LEAVE_CHAPTER_MAP": {"campaign-chapter-back"},
        "RETURN_HOME": {"campaign-exit-base", "campaign-base-request"},
        "CLOSE_STAGE_DIALOG": {"campaign-stage-dialog-close"},
    }
    continuations = 0
    for row in rows:
        if row.get("type") == "observation":
            continue
        if row.get("type") != "command":
            return False
        kind, action = row.get("kind"), row.get("action")
        if kind == "wait" and action == "WAIT_FOR_BATTLE_RESULT":
            continue
        if kind == "terminal" and action in {"COMPLETE", "BLOCKED"}:
            continue
        if kind != "tap" or row.get("target_identity") not in allowed.get(str(action), set()):
            return False
        continuations += action == "CONTINUE_VICTORY"
    return continuations == 1


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
    cost_match = type(campaign.get("ap_cost")) is int and campaign["ap_cost"] == ap_cost
    ledger_match = bool(
        _campaign_progress_valid(progress) and progress["ap_spent"] == ap_cost
        and progress["initial_ap"] == ap_before and progress["current_ap"] == ap_after
    )
    ap_cost_reconciled = bool(
        ledger_match and type(ap_before) is int and type(ap_after) is int
        and ap_before - ap_after + progress["ap_regenerated"] == ap_cost
    )
    event_rows = _campaign_event_rows(session_directory)
    victory_home_only = route_result.get("victory_home_only") is True
    recovery_inputs_safe = _campaign_victory_recovery_inputs(event_rows)
    forbidden_action_seen = any(
        any(
            marker in str(row.get("action") or "").casefold()
            or marker in str(row.get("target_identity") or "").casefold()
            for marker in ("sweep", "blitz", "auto_complete", "refill")
        )
        for row in event_rows
        if row.get("type") == "command"
    )
    refill_action_seen = any(
        "refill" in str(row.get("action") or "").casefold()
        or "refill" in str(row.get("target_identity") or "").casefold()
        for row in event_rows
        if row.get("type") == "command"
    )
    refill_forbidden_verified = not refill_action_seen
    safe_action_policy = not forbidden_action_seen and (not victory_home_only or recovery_inputs_safe)
    route_status = str(route_result.get("status") or "blocked")
    terminal_home = route_result.get("terminal_runtime_state") == "recognized_home"
    outcome = campaign.get("battle_outcome")
    result_successor = outcome in {"victory", "defeat"}
    action_count = _campaign_action_count(campaign)
    proof = route_result.get("recovery_proof")
    recovery_contract = not victory_home_only or bool(
        isinstance(proof, Mapping)
        and proof.get("baseline_ap") == ap_before
        and proof.get("destination") == destination
        and proof.get("ap_cost") == ap_cost
        and proof.get("registration_snapshot") == registration_snapshot
        and type(proof.get("new_battle_count")) is int and proof["new_battle_count"] == 0
        and campaign.get("victory_home_only") is True
        and type(campaign.get("new_battle_count")) is int and campaign["new_battle_count"] == 0
        and outcome == "victory" and progress.get("loss_seen") is False
        and recovery_inputs_safe
    )
    completed = bool(
        route_status == "completed"
        and route_result.get("terminal") == "completed"
        and route_result.get("navigation_only") is False
        and terminal_home
        and ap_cost_reconciled
        and result_successor
        and destination_match
        and cost_match
        and ledger_match
        and safe_action_policy
        and refill_forbidden_verified
        and action_count == 1
        and recovery_contract
    )
    navigation_only_trace = bool(
        not victory_home_only and _campaign_navigation_only_trace(event_rows, input_count)
        and ("progress" not in campaign or _campaign_unconsumed_progress(campaign["progress"]))
        and not action_count
        and not progress.get("ap_spent")
        and (
            ap_before is None and ap_after is None
            or type(ap_before) is int and type(ap_after) is int and ap_before == ap_after
        )
        and outcome is None
        and safe_action_policy
    )
    reconciliation_required = bool((input_count or victory_home_only) and not completed and not navigation_only_trace)
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
            "observed_ap_delta": ap_before - ap_after if type(ap_before) is int and type(ap_after) is int else None,
            "ap_regenerated": progress.get("ap_regenerated"),
            "ap_cost_reconciled": ap_cost_reconciled,
            "destination_match": destination_match,
            "cost_match": cost_match,
            "ledger_match": ledger_match,
            "result_successor_verified": result_successor,
            "terminal_home_verified": terminal_home,
            "forbidden_action_seen": forbidden_action_seen,
            "safe_action_policy": safe_action_policy,
            "refill_forbidden_verified": refill_forbidden_verified,
            "proof_topology": "composite" if victory_home_only else "continuous",
            "victory_home_only": victory_home_only,
            "recovery_inputs_verified": recovery_inputs_safe if victory_home_only else None,
            "recovery_contract_verified": recovery_contract if victory_home_only else None,
            "new_battle_count": 0 if victory_home_only and recovery_inputs_safe else action_count,
            "effect_reconciliation_required": reconciliation_required,
            "navigation_only_trace_verified": navigation_only_trace,
            "identical_retry_denied": reconciliation_required,
            "registration_snapshot": dict(registration_snapshot),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    )
    if not payload.get("reason"):
        if not ap_cost_reconciled or not ledger_match:
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
        "proof_topology": result.get("proof_topology", "continuous"),
        "recovery_proof": result.get("recovery_proof"),
        "new_battle_count": result.get("new_battle_count"),
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
        "route_input_count": int(result.get("route_input_count") or 0),
        "recovery_input_count": int(result.get("recovery_input_count") or 0),
        "total_input_count": int(result.get("total_input_count") or result.get("input_count") or 0),
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
        "serial": BLUESTACKS_SERIAL,
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


def _run_campaign_victory_home_recovery(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    if lease.get("recovery_only") is not True:
        raise _pnsctl().OperatorError(
            "Ordinary Campaign AP execution uses pnsctl automation-service serve; "
            "the legacy runner supports only verified Victory-home recovery"
        )
    del queue
    from tasks.campaign_victory_recovery import load_victory_recovery_proof

    recovery_proof = load_victory_recovery_proof(Path(str(lease.get("recovery_session") or "")))
    # Retained registration identifies the original battle. Current user
    # authorization and the active session fence permit navigation only.
    registration = RegisteredDispatchSnapshot.from_mapping(recovery_proof["registration_snapshot"])
    registration_snapshot = registration.to_mapping()
    maximum = _campaign_maximum(lease)
    outer_session = _campaign_outer_session(lease)
    initial_observation = _campaign_initial_observation(lease, outer_session)
    outer_directory = Path(outer_session.session_directory)
    runtime_directory = outer_directory / "runtime"
    runtime_directory.mkdir(parents=True, exist_ok=True)
    destination = str(recovery_proof["destination"])
    if destination not in CAMPAIGN_STAGE_COSTS:
        raise _pnsctl().OperatorError(
            f"Campaign AP destination is unsupported: {destination}"
        )
    ap_cost = CAMPAIGN_STAGE_COSTS[destination]
    child = runtime_directory
    startup_recovery: dict[str, object] | None = None
    try:
        pnsctl = _pnsctl()
        preparation_input_count = _campaign_transport_count(runtime_directory)
        remaining_inputs = maximum - preparation_input_count
        if remaining_inputs < 1:
            raise pnsctl.OperatorError(
                "Campaign AP has no input budget remaining after startup preparation"
            )
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bluestacks_campaign_ap.py"),
            "--adb",
            str(BLUESTACKS_ADB),
            "--serial",
            BLUESTACKS_SERIAL,
            "--stage",
            destination,
            "--ap-cost",
            str(ap_cost),
            "--ap-budget",
            str(ap_cost),
            "--max-runs",
            "1",
            "--victory-home-only",
            "--initial-ap",
            str(recovery_proof["baseline_ap"]),
            "--max-inputs",
            str(remaining_inputs),
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
            "startup_recovery": startup_recovery,
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
    route_input_count = _campaign_transport_count(runtime_directory)
    route_result.update({
        "victory_home_only": True,
        "recovery_proof": recovery_proof,
        "proof_topology": "composite",
    })
    recovery_input_count = int(lease.get("startup_recovery_input_count") or 0)
    input_count = recovery_input_count + route_input_count
    if input_count > int(lease.get("max_inputs", MAX_INPUTS)):
        raise _pnsctl().OperatorError("Campaign AP exceeded max_inputs")
    payload = _campaign_result_payload(
        route_result,
        session_directory=child,
        input_count=input_count,
        maximum=int(lease.get("max_inputs", MAX_INPUTS)),
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
    payload["campaign_transport_count"] = route_input_count
    payload["recovery_input_count"] = recovery_input_count
    payload["route_input_count"] = route_input_count
    payload["total_input_count"] = input_count
    trace = _campaign_causal_trace(
        child,
        result=payload,
        initial_observation=initial_observation,
        registration_snapshot=registration_snapshot,
    )
    payload["initial_observation"] = initial_observation
    payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
    payload["campaign_transport_count"] = route_input_count
    payload["recovery_input_count"] = recovery_input_count
    payload["route_input_count"] = route_input_count
    payload["total_input_count"] = input_count
    payload["causal_trace_count"] = 1
    payload["causal_trace"] = trace
    outer_session.adopt_retained_transport_count(
        input_count,
        source="runtime_session/events.jsonl",
    )
    outer_session.remember_control("campaign_transport_count", route_input_count)
    outer_session.remember_control("recovery_input_count", recovery_input_count)
    outer_session.remember_control("route_input_count", route_input_count)
    outer_session.remember_control("total_input_count", input_count)
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
    if lease.get("recovery_only") is not True:
        raise _pnsctl().OperatorError(
            "Ordinary Campaign AP execution uses pnsctl automation-service serve; "
            "the legacy runner supports only verified Victory-home recovery"
        )
    if "development_session" not in lease:
        raise _pnsctl().OperatorError(
            "Campaign AP requires the active pnsctl-owned DevelopmentSession"
        )
    return _run_campaign_victory_home_recovery(queue, lease)


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
        and type(ap_cost) is int
        and type(campaign.get("ap_cost")) is int and campaign["ap_cost"] == ap_cost
        and _campaign_progress_valid(progress)
        and progress.get("ap_spent") == ap_cost
        and progress.get("initial_ap") == campaign.get("ap_before")
        and progress.get("current_ap") == campaign.get("ap_after")
        and type(campaign.get("ap_before")) is int and type(campaign.get("ap_after")) is int
        and campaign["ap_before"] - campaign["ap_after"] + progress["ap_regenerated"] == ap_cost
        and result.get("ap_cost_reconciled") is True
        and result.get("ap_regenerated") == progress["ap_regenerated"]
        and result.get("exact_ap_delta") is (campaign["ap_before"] - campaign["ap_after"] == ap_cost)
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
    recovery_raw = result.get("recovery_input_count", 0)
    route_raw = result.get("route_input_count", result.get("campaign_transport_count"))
    total_raw = result.get("total_input_count", result.get("input_count"))
    recovery_input_count = recovery_raw if type(recovery_raw) is int else -1
    route_input_count = route_raw if type(route_raw) is int else -1
    total_input_count = total_raw if type(total_raw) is int else -1
    accounting_ok = bool(
        type(recovery_raw) is int
        and type(route_raw) is int
        and type(total_raw) is int
        and type(result.get("input_count")) is int
        and type(result.get("campaign_transport_count")) is int
        and recovery_input_count >= 0
        and route_input_count >= 0
        and total_input_count >= 0
        and route_input_count == retained_transport
        and total_input_count == recovery_input_count + route_input_count
        and total_input_count == result.get("input_count")
        and route_input_count == result.get("campaign_transport_count")
    )
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
        and trace.get("proof_topology") == result.get("proof_topology")
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("route_input_count", route_input_count) == route_input_count
        and trace.get("recovery_input_count", recovery_input_count) == recovery_input_count
        and trace.get("total_input_count", total_input_count) == total_input_count
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
    topology_ok = result.get("proof_topology") == "continuous" and result.get("victory_home_only") is not True
    if result.get("proof_topology") == "composite":
        proof = result.get("recovery_proof")
        try:
            from tasks.campaign_victory_recovery import load_victory_recovery_proof

            stamp = str(initial.get("invocation_id") or "").rsplit("-", 1)[-1] if isinstance(initial, Mapping) else ""
            observed_at = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
            retained_proof = load_victory_recovery_proof(Path(proof["source_session"]), now=observed_at)
            topology_ok = bool(
                isinstance(trace, Mapping)
                and result.get("victory_home_only") is True
                and campaign.get("victory_home_only") is True
                and type(result.get("new_battle_count")) is int and result["new_battle_count"] == 0
                and type(campaign.get("new_battle_count")) is int and campaign["new_battle_count"] == 0
                and campaign.get("battle_outcome") == "victory" and progress.get("loss_seen") is False
                and proof == retained_proof
                and proof["baseline_ap"] == campaign.get("ap_before")
                and proof["destination"] == destination and proof["ap_cost"] == ap_cost
                and proof["registration_snapshot"] == result.get("registration_snapshot")
                and trace.get("recovery_proof") == proof
                and trace.get("new_battle_count") == 0
                and result.get("recovery_inputs_verified") is True
                and _campaign_victory_recovery_inputs(_campaign_event_rows(session))
            )
        except (OSError, ValueError, TypeError, KeyError):
            topology_ok = False
    verified = bool(
        result.get("status") == "completed"
        and topology_ok
        and initial_ok
        and trace_ok
        and accounting_ok
        and type(result.get("max_inputs")) is int
        and total_input_count <= result.get("max_inputs")
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
        "proof_topology_verified": topology_ok,
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
