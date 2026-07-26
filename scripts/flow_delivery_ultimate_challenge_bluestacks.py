#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Ultimate Challenge Daily delivery."""

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
FLOW_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
UC_RUNNER_ID = "ultimate_challenge_navigation_only_runner"
UC_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_navigation_only_evidence"
UC_RECOVERY_HANDLER_ID = "ultimate_challenge_navigation_only_recovery"
UC_DAILY_RUNNER_ID = "ultimate_challenge_daily_runner"
UC_DAILY_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_daily_evidence"
UC_DAILY_RECOVERY_HANDLER_ID = "ultimate_challenge_daily_recovery"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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
    ok = completed.returncode == 0 and terminal in {
        "navigation_only_complete",
        "already_completed",
    }
    events_rel = "events.jsonl"
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if ok else "safe_blocked_terminal",
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


def run_ultimate_challenge_daily(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    """Run the approved zero-resource Flee route through the production operator."""

    pnsctl = _pnsctl()
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"daily-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--daily",
        "--adb", str(pnsctl.BLUESTACKS_ADB),
        "--serial", pnsctl.BLUESTACKS_SERIAL,
        "--execute", "--yes",
        "--reset-identity", "local-2026-07-26-ultimate",
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
    ok = completed.returncode == 0 and terminal in {"complete_for_reset", "already_completed"}
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if ok else "safe_blocked_terminal",
        "ultimate_challenge_result": uc_result,
        "actions": [{"action_class": "zero_resource_flee", "path": "home_to_ultimate_challenge_flee_home", "outcome": terminal}],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
        "attempt_budget": int(flow.get("maximum_live_attempts") or 0),
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
    if result.get("terminal_runtime_state") != "recognized_home":
        raise pnsctl.OperatorError("Ultimate Challenge evidence terminal runtime state is unsafe")
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
    if result.get("terminal_runtime_state") != "recognized_home":
        raise pnsctl.OperatorError("Ultimate Challenge terminal runtime state is unsafe")
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    if int(flow.get("maximum_live_attempts") or 0) != 6:
        raise pnsctl.OperatorError("Ultimate Challenge attempt ceiling must remain six")
    return {"status": "verified", "flow_id": FLOW_ID, "terminal": uc.get("terminal"), "session_directory": structure["session_directory"], "actions": result.get("actions", []), "terminal_runtime_state": result["terminal_runtime_state"]}


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
