#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Campaign navigation-only delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    require_operator_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
PROVING_FLOW_ID = "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE"
AUTO_BATTLE_FLOW_ID = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
DESTINATIONS = ("1-20-9", "1-15-9", "2-2-9")
MAX_PROVING_ATTEMPTS = 25
REQUIRED_CONSECUTIVE_PROVING_CYCLES = 10
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


def run_campaign_auto_battle_live(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    """Run the explicitly authorized consequential Campaign AP canary through the checked-in adapter."""

    pnsctl = _pnsctl()
    flow = next(item for item in queue["flows"] if item["flow_id"] == AUTO_BATTLE_FLOW_ID)
    destination = "1-15-9"
    costs = {"1-20-9": 16, "1-15-9": 14, "2-2-9": 20}
    maximum_ap = 120
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / AUTO_BATTLE_FLOW_ID / f"auto-{destination}-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    # The accepted Home Atlas entry localizes and pans from the fresh native Home frame.
    # Avoid redundant host zoom preparation here; it can surface Android recents before
    # the operator captures its authoritative starting frame.
    _ensure_home_surface_before_prep(session)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_campaign_ap.py"),
        "--adb", str(pnsctl.BLUESTACKS_ADB),
        "--serial", pnsctl.BLUESTACKS_SERIAL,
        "--stage", destination,
        "--ap-cost", str(costs[destination]),
        "--ap-budget", str(costs[destination]),
        "--max-runs", "1",
        "--execute", "--yes",
        "--output-directory", str(session),
    ]
    completed_process = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    (session / "operator-stdout.log").write_text(completed_process.stdout or "", encoding="utf-8")
    (session / "operator-stderr.log").write_text(completed_process.stderr or "", encoding="utf-8")
    campaign_session = _resolve_campaign_operator_session(session, destination)
    result_path = campaign_session / "result.json"
    if not result_path.is_file():
        raise pnsctl.OperatorError("Campaign Auto Battle result.json is missing")
    campaign_result = json.loads(result_path.read_text(encoding="utf-8"))
    ok = (
        completed_process.returncode == 0
        and campaign_result.get("status") == "completed"
        and campaign_result.get("terminal") == "completed"
        and campaign_result.get("navigation_only") is False
        and campaign_result.get("battle_outcome") == "victory"
    )
    delivery = {
        "schema_version": 1,
        "flow_id": AUTO_BATTLE_FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if ok else "safe_blocked_terminal",
        "destination": destination,
        "campaign_result": campaign_result,
        "actions": [{"action_class": "campaign_ap_auto_battle", "destination": destination, "outcome": campaign_result.get("battle_outcome")}],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "journal_path": "journal.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "frames_directory": "frames",
        "operator_returncode": completed_process.returncode,
    }
    (campaign_session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not ok:
        raise pnsctl.OperatorError(
            f"Campaign Auto Battle failed for {destination}: "
            f"{campaign_result.get('reason') or completed_process.stderr or completed_process.stdout or 'unknown'}"
        )
    return json.dumps(
        {"status": "completed", "flow_id": AUTO_BATTLE_FLOW_ID, "destination": destination, "session_directory": str(campaign_session), "dispatch": True, "ap_before": campaign_result.get("ap_before"), "ap_after": campaign_result.get("ap_after"), "battle_outcome": campaign_result.get("battle_outcome")},
        sort_keys=True,
    )


def verify_campaign_auto_battle_live(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    del queue, lease
    result = structure["result"]
    if result.get("flow_id") != AUTO_BATTLE_FLOW_ID:
        raise _pnsctl().OperatorError("Campaign Auto Battle evidence belongs to another flow")
    campaign = result.get("campaign_result") or {}
    if campaign.get("status") != "completed" or campaign.get("terminal") != "completed":
        raise _pnsctl().OperatorError("Campaign Auto Battle evidence is not a completed terminal")
    if campaign.get("navigation_only") is not False or campaign.get("battle_outcome") not in {"victory", "defeat"}:
        raise _pnsctl().OperatorError("Campaign Auto Battle consequence/result contract failed")
    progress = campaign.get("progress") or {}
    if progress.get("ap_spent") != campaign.get("ap_cost"):
        raise _pnsctl().OperatorError("Campaign AP ledger does not equal configured cost")
    if result.get("terminal_runtime_state") != "recognized_home":
        raise _pnsctl().OperatorError("Campaign Auto Battle did not return to recognized Home")
    return {"status": "verified", "flow_id": AUTO_BATTLE_FLOW_ID, "destination": result.get("destination"), "session_directory": structure["session_directory"], "ap_before": campaign.get("ap_before"), "ap_after": campaign.get("ap_after"), "battle_outcome": campaign.get("battle_outcome"), "terminal_runtime_state": result["terminal_runtime_state"]}


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
