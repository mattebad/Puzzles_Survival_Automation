#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Ultimate Challenge Daily delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

import cv2
import numpy as np

from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    require_operator_evidence,
)
from tasks.ultimate_challenge_daily import (
    TERMINAL_COMPLETE_FOR_RESET,
    load_reset_window_state,
    record_verified_home_success,
    save_reset_window_state,
)
from tasks.home_nav_recognition import recognize_home_nav

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
MAX_TOTAL_INPUTS = 16
UC_RUNNER_ID = "ultimate_challenge_navigation_only_runner"
UC_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_navigation_only_evidence"
UC_RECOVERY_HANDLER_ID = "ultimate_challenge_navigation_only_recovery"
UC_DAILY_RUNNER_ID = "ultimate_challenge_daily_runner"
UC_DAILY_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_daily_evidence"
UC_DAILY_RECOVERY_HANDLER_ID = "ultimate_challenge_daily_recovery"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _current_reset_identity() -> str:
    return f"game-day-{datetime.now(timezone.utc).date().isoformat()}"


def _reset_window_state_path() -> Path:
    """Return the stable, untracked per-flow reset state location."""

    return REPO_ROOT / ".local-captures" / "ultimate-challenge-daily-reset-window.json"


def _verified_home_evidence(
    session_directory: Path,
    result: Mapping[str, Any],
) -> tuple[bool, Path | None]:
    """Safely reload the child-retained Home PNG and independently verify it."""

    if result.get("home_nav_recognized") is not True:
        return False, None
    relative = result.get("home_frame")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return False, None
    session = session_directory.resolve()
    candidate = (session / relative).resolve()
    if session not in candidate.parents or not candidate.is_file():
        return False, None
    payload = candidate.read_bytes()
    expected_hash = str(result.get("home_frame_sha256") or result.get("home_sha256") or "")
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        return False, None
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or not recognize_home_nav(frame).is_home:
        return False, None
    return True, candidate


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def run_ultimate_challenge_navigation_only(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    pnsctl = _pnsctl()
    del queue
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"nav-ultimate-challenge-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--adb",
        str(pnsctl.BLUESTACKS_ADB),
        "--serial",
        pnsctl.BLUESTACKS_SERIAL,
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
    child_sessions = sorted(path for path in session.iterdir() if path.is_dir())
    uc_session = child_sessions[-1] if child_sessions else session
    try:
        uc_result, frame_names = require_operator_evidence(uc_session)
    except FlowEvidenceIntegrityError as exc:
        raise pnsctl.OperatorError(
            f"Ultimate Challenge executable/evidence-integrity failure: {exc}"
        ) from exc
    terminal = uc_result.get("terminal")
    home_verified = False
    if terminal == "navigation_only_complete":
        ok = (
            completed.returncode == 0
            and uc_result.get("terminal_runtime_state")
            == "ultimate_challenge_entry_recognized"
        )
    elif terminal == "already_completed":
        home_verified, _home_path = _verified_home_evidence(uc_session, uc_result)
        ok = completed.returncode == 0 and home_verified
    else:
        ok = False
    events_rel = "events.jsonl"
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": (
            "recognized_home"
            if terminal == "already_completed" and home_verified
            else (
                "ultimate_challenge_entry_recognized"
                if terminal == "navigation_only_complete" and ok
                else "safe_blocked_terminal"
            )
        ),
        "ultimate_challenge_result": uc_result,
        "actions": [
            {
                "action_class": "navigation_only",
                "path": "home_atlas_to_campaign_to_ultimate_challenge",
                "outcome": uc_result.get("status") or "failed",
            }
        ],
        "events_path": events_rel,
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
    }
    (uc_session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not ok:
        raise pnsctl.OperatorError(
            "Ultimate Challenge navigation-only failed: "
            f"{uc_result.get('reason') or completed.stderr or completed.stdout or 'unknown'}"
        )
    return json.dumps(
        {
            "status": "completed",
            "flow_id": FLOW_ID,
            "terminal": terminal,
            "session_directory": str(uc_session),
            "dispatch": True,
        },
        sort_keys=True,
    )


def _legacy_daily_flow(queue: Mapping[str, Any]) -> Mapping[str, Any] | None:
    flows = queue.get("flows")
    if flows is None:
        return None
    if not isinstance(flows, list):
        raise _pnsctl().OperatorError("legacy flow-delivery queue flows must be a list")
    matches = [
        item
        for item in flows
        if isinstance(item, Mapping) and item.get("flow_id") == FLOW_ID
    ]
    if len(matches) != 1:
        raise _pnsctl().OperatorError(
            "legacy flow-delivery queue does not identify exactly one Ultimate Challenge flow"
        )
    return matches[0]


def _daily_runtime_context(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, int]:
    """Validate the current session contract before creating or launching a child."""

    marker_present = (
        "development_session" in queue or "development_session" in lease
    )
    if marker_present:
        if queue.get("development_session") is not True or lease.get(
            "development_session"
        ) is not True:
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development-session markers are required"
            )
        if queue.get("active_flow_id") != FLOW_ID:
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development session has the wrong active flow"
            )
        if lease.get("runtime_ownership_state") != "held":
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development session requires held runtime ownership"
            )
        owner = lease.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development session owner is required"
            )
        maximum = lease.get("max_inputs")
        if type(maximum) is not int or not 1 <= maximum <= MAX_TOTAL_INPUTS:
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development session max_inputs must be an integer "
                "between 1 and 16"
            )
        return None, maximum

    if "runtime_ownership_state" in lease and lease.get(
        "runtime_ownership_state"
    ) != "held":
        raise _pnsctl().OperatorError(
            "Ultimate Challenge runner requires held runtime ownership"
        )
    flow = _legacy_daily_flow(queue)
    maximum = lease.get("max_inputs", MAX_TOTAL_INPUTS)
    if type(maximum) is not int or not 1 <= maximum <= MAX_TOTAL_INPUTS:
        raise _pnsctl().OperatorError(
            "Ultimate Challenge max_inputs must be an integer between 1 and 16"
        )
    return flow, maximum


def run_ultimate_challenge_daily(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    """Run the approved zero-resource Flee route through the production operator."""

    pnsctl = _pnsctl()
    flow, maximum = _daily_runtime_context(queue, lease)
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"daily-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    reset_identity = _current_reset_identity()
    reset_state_path = _reset_window_state_path()
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--daily",
        "--adb", str(pnsctl.BLUESTACKS_ADB),
        "--serial", pnsctl.BLUESTACKS_SERIAL,
        "--execute", "--yes",
        "--reset-identity", reset_identity,
        "--reset-state-path", str(reset_state_path),
        "--max-total-inputs", str(maximum),
        "--output-directory", str(session),
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    (session / "operator-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (session / "operator-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    child_sessions = sorted(path for path in session.iterdir() if path.is_dir())
    uc_session = child_sessions[-1] if child_sessions else session
    try:
        uc_result, frame_names = require_operator_evidence(uc_session)
    except FlowEvidenceIntegrityError as exc:
        raise pnsctl.OperatorError(f"Ultimate Challenge executable/evidence-integrity failure: {exc}") from exc
    terminal = uc_result.get("terminal")
    home_verified, home_path = _verified_home_evidence(uc_session, uc_result)
    input_count = uc_result.get("input_count")
    ok = (
        completed.returncode == 0
        and terminal in {"complete_for_reset", "already_completed"}
        and home_verified
        and type(input_count) is int
        and 0 <= input_count <= maximum
    )
    if terminal == TERMINAL_COMPLETE_FOR_RESET and ok:
        if not home_verified:
            raise pnsctl.OperatorError(
                "Ultimate Challenge completion lacks verified template Home evidence"
            )
        try:
            state = load_reset_window_state(reset_state_path)
            updated = record_verified_home_success(
                state,
                reset_identity=reset_identity,
            )
            save_reset_window_state(reset_state_path, updated)
        except (OSError, TypeError, ValueError) as exc:
            raise pnsctl.OperatorError(
                f"Ultimate Challenge reset-window persistence failed: {exc}"
            ) from exc
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if home_verified else "safe_blocked_terminal",
        "ultimate_challenge_result": uc_result,
        "actions": [{"action_class": "zero_resource_flee", "path": "home_to_ultimate_challenge_flee_home", "outcome": terminal}],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
        "input_count": input_count,
        "attempt_budget": (
            flow.get("maximum_live_attempts") if flow is not None else None
        ),
        "legacy_attempt_budget": (
            flow.get("maximum_live_attempts") if flow is not None else None
        ),
        "max_inputs": maximum,
        "session_max_inputs": maximum,
        "reset_identity": reset_identity,
        "reset_state_path": str(reset_state_path),
        "verified_home_path": str(home_path.relative_to(uc_session)).replace("\\", "/")
        if home_path is not None
        else None,
    }
    (uc_session / "flow-delivery-result.json").write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not ok:
        raise pnsctl.OperatorError("Ultimate Challenge Daily failed: " + str(uc_result.get("reason") or completed.stderr or completed.stdout or "unknown"))
    return json.dumps({"status": "completed", "flow_id": FLOW_ID, "terminal": terminal, "session_directory": str(uc_session), "dispatch": True}, sort_keys=True)


def verify_ultimate_challenge_navigation_only(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    del lease
    result = structure["result"]
    if result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Ultimate Challenge evidence belongs to another flow")
    uc = result.get("ultimate_challenge_result") or {}
    terminal = uc.get("terminal")
    if terminal not in {"navigation_only_complete", "already_completed"}:
        raise pnsctl.OperatorError(
            "Ultimate Challenge evidence terminal is not navigation_only_complete/already_completed"
        )
    if terminal == "navigation_only_complete":
        if (
            result.get("terminal_runtime_state")
            != "ultimate_challenge_entry_recognized"
            or uc.get("terminal_runtime_state")
            != "ultimate_challenge_entry_recognized"
        ):
            raise pnsctl.OperatorError("Ultimate Challenge entry evidence state is unsafe")
    else:
        home_verified, _home_path = _verified_home_evidence(
            Path(str(structure["session_directory"])),
            uc,
        )
        if not home_verified or result.get("terminal_runtime_state") != "recognized_home":
            raise pnsctl.OperatorError("Ultimate Challenge already_completed Home evidence is unsafe")
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    if "already_completed" not in flow.get("required_terminal_states", []):
        raise pnsctl.OperatorError("Ultimate Challenge flow contract missing already_completed")
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "terminal": terminal,
        "session_directory": structure["session_directory"],
        "actions": structure["actions"],
        "terminal_runtime_state": result["terminal_runtime_state"],
    }


def recover_ultimate_challenge_navigation_only(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    pnsctl = _pnsctl()
    del queue, lease
    state = str(pnsctl._run_fixed_bluestacks_adb("get-state")).strip()
    if state != "device":
        raise pnsctl.OperatorError("approved BlueStacks serial is not in device state")
    focus = str(pnsctl._run_fixed_bluestacks_adb("shell", "dumpsys", "window"))
    package = pnsctl._focused_package(focus)
    if package != pnsctl.PACKAGE:
        raise pnsctl.OperatorError(
            "Puzzles & Survival is not the foreground package during recovery"
        )
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


def verify_ultimate_challenge_daily(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    del lease
    result = structure["result"]
    if result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Ultimate Challenge evidence belongs to another flow")
    uc = result.get("ultimate_challenge_result") or {}
    if uc.get("terminal") not in {"complete_for_reset", "already_completed"}:
        raise pnsctl.OperatorError("Ultimate Challenge Daily did not prove the reset terminal")
    session_directory = Path(str(structure["session_directory"]))
    home_verified, home_path = _verified_home_evidence(session_directory, uc)
    if not home_verified:
        raise pnsctl.OperatorError("Ultimate Challenge terminal lacks independently verified Home evidence")
    if type(uc.get("input_count")) is not int or not 0 <= uc["input_count"] <= MAX_TOTAL_INPUTS:
        raise pnsctl.OperatorError("Ultimate Challenge aggregate input count exceeds 16 or is missing")
    if result.get("terminal_runtime_state") != "recognized_home":
        raise pnsctl.OperatorError("Ultimate Challenge terminal runtime state is unsafe")
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    maximum = int(flow.get("maximum_live_attempts") or 0)
    used = int(flow.get("live_attempt_count") or 0)
    if maximum <= 0 or used > maximum:
        raise pnsctl.OperatorError("Ultimate Challenge attempt accounting exceeds its configured ceiling")
    return {"status": "verified", "flow_id": FLOW_ID, "terminal": uc.get("terminal"), "session_directory": structure["session_directory"], "actions": result.get("actions", []), "terminal_runtime_state": result["terminal_runtime_state"], "verified_home_path": str(home_path.relative_to(session_directory.resolve())).replace("\\", "/")}


def recover_ultimate_challenge_daily(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    return recover_ultimate_challenge_navigation_only(queue, lease)


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[UC_RUNNER_ID] = run_ultimate_challenge_navigation_only
    validators[UC_EVIDENCE_VALIDATOR_ID] = verify_ultimate_challenge_navigation_only
    handlers[UC_RECOVERY_HANDLER_ID] = recover_ultimate_challenge_navigation_only
    runners[UC_DAILY_RUNNER_ID] = run_ultimate_challenge_daily
    validators[UC_DAILY_EVIDENCE_VALIDATOR_ID] = verify_ultimate_challenge_daily
    handlers[UC_DAILY_RECOVERY_HANDLER_ID] = recover_ultimate_challenge_daily
