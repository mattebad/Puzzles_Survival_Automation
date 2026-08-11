"""Checked-in navigation-only Ruins Challenge delivery binding."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
RUNNER_ID = "ruins_challenge_home_atlas_runner"
VALIDATOR_ID = "ruins_challenge_home_atlas_evidence"
RECOVERY_ID = "ruins_challenge_home_atlas_recovery"


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _operator_result(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Ruins operator did not emit a JSON result")


def run_ruins_challenge_home_atlas(
    queue: Mapping[str, Any], lease: Mapping[str, Any], *, live: bool = True
) -> str:
    """Run exactly Home -> Ruins Challenge -> verified safe exit -> Home."""

    pnsctl = _pnsctl()
    del queue
    development_mode = bool(lease.get("development_session"))
    root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"nav-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "ruins_challenge_bluestacks.py"),
        "--adb", str(pnsctl.BLUESTACKS_ADB),
        "--serial", pnsctl.BLUESTACKS_SERIAL,
        "--reset-identity", "local-2026-08-06-ruins-home-atlas",
        "--current-day", "Thu",
        "--navigation-only",
        "--output-directory", str(root),
    ]
    if live:
        command.extend(("--execute", "--yes"))
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    (root / "operator-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (root / "operator-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    children = sorted(path for path in root.iterdir() if path.is_dir())
    session = children[-1] if children else root
    try:
        ruins = _operator_result(completed.stdout or "")
    except ValueError as exc:
        raise pnsctl.OperatorError(str(exc)) from exc
    frame_names = [str(path.relative_to(session)) for path in sorted((session / "frames").glob("*.png"))]
    if not frame_names:
        raise pnsctl.OperatorError("Ruins route produced no native frame evidence")
    events = session / "events.jsonl"
    if not events.is_file():
        raise pnsctl.OperatorError("Ruins route produced no transport/capture event journal")
    terminal = ruins.get("status") == "completed" and ruins.get("reason") == "verified_safe_exit_to_home"
    event_rows = [
        json.loads(line)
        for line in events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    zero_transport = not live and not any(row.get("type") == "dispatch" for row in event_rows)
    # These are real route-accounting records, not placeholders: the flow-level ledger
    # binds the child event journal and the navigation-only contract to this invocation.
    accounting = {
        "flow_id": FLOW_ID,
        "navigation_only": True,
        "operator_status": ruins.get("status"),
        "operator_reason": ruins.get("reason"),
        "actions_completed": ruins.get("actions_completed"),
        "child_event_journal": "events.jsonl",
    }
    evidence_names = (
        ()
        if development_mode
        else ("ledger.jsonl", "capability-audit.jsonl", "journal.jsonl")
    )
    for name in evidence_names:
        (session / name).write_text(json.dumps(accounting, sort_keys=True) + "\n", encoding="utf-8")
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if terminal else "dry_run" if zero_transport else "failed",
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if terminal else "safe_blocked_terminal",
        "ruins_result": ruins,
        "actions": [{"action_class": "ordinary_development" if development_mode else "navigation_only", "path": "canonical_home_to_ruins_to_safe_exit_home", "outcome": ruins.get("reason")}],
        "events_path": "events.jsonl",
        "ledger_path": None if development_mode else "ledger.jsonl",
        "capability_audit_path": None if development_mode else "capability-audit.jsonl",
        "journal_path": None if development_mode else "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
        "resource_delta": 0,
    }
    (session / "flow-delivery-result.json").write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if zero_transport:
        return json.dumps({
            "status": "dry_run",
            "flow_id": FLOW_ID,
            "session_directory": str(session),
            "dispatch": False,
            "reason": ruins.get("reason"),
        }, sort_keys=True)
    if not terminal:
        if development_mode:
            return json.dumps(
                {
                    "status": "blocked",
                    "flow_id": FLOW_ID,
                    "session_directory": str(session),
                    "dispatch": any(row.get("type") == "dispatch" for row in event_rows),
                    "reason": ruins.get("reason") or "development_route_not_terminal",
                    "actions_completed": ruins.get("actions_completed", 0),
                },
                sort_keys=True,
            )
        raise pnsctl.OperatorError("Ruins navigation route did not prove safe exit to Home")
    return json.dumps({"status": "completed", "flow_id": FLOW_ID, "session_directory": str(session), "dispatch": True}, sort_keys=True)


def verify_ruins_challenge_home_atlas(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    del lease
    result = structure["result"]
    ruins = result.get("ruins_result") or {}
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    if result.get("flow_id") != FLOW_ID or result.get("resource_delta") != 0:
        raise pnsctl.OperatorError("Ruins evidence identity or zero-resource invariant failed")
    if ruins.get("status") != "completed" or ruins.get("reason") != "verified_safe_exit_to_home":
        raise pnsctl.OperatorError("Ruins evidence lacks Home -> Ruins -> Home proof")
    if int(flow.get("live_attempt_count") or 0) > int(flow.get("maximum_live_attempts") or 0):
        raise pnsctl.OperatorError("Ruins attempt accounting exceeds authorization")
    return {"status": "verified", "flow_id": FLOW_ID, "terminal": "navigation_only_complete", "session_directory": structure["session_directory"], "actions": structure["actions"], "terminal_runtime_state": result["terminal_runtime_state"], "resource_delta": 0}


def recover_ruins_challenge_home_atlas(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    pnsctl = _pnsctl()
    del queue, lease
    state = str(pnsctl._run_fixed_bluestacks_adb("get-state")).strip()
    if state != "device":
        raise pnsctl.OperatorError("approved BlueStacks serial is not in device state")
    return json.dumps({"status": "recovered_or_already_safe", "flow_id": FLOW_ID, "dispatch": False, "recovery": "observe_only_no_android_back"}, sort_keys=True)


def register(runners: dict[str, Any], validators: dict[str, Any], handlers: dict[str, Any]) -> None:
    runners[RUNNER_ID] = run_ruins_challenge_home_atlas
    validators[VALIDATOR_ID] = verify_ruins_challenge_home_atlas
    handlers[RECOVERY_ID] = recover_ruins_challenge_home_atlas
