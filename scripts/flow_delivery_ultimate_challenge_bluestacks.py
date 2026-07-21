#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Ultimate Challenge navigation-only delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
UC_RUNNER_ID = "ultimate_challenge_navigation_only_runner"
UC_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_navigation_only_evidence"
UC_RECOVERY_HANDLER_ID = "ultimate_challenge_navigation_only_recovery"


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
    result_path = uc_session / "result.json"
    uc_result: dict[str, Any] = {}
    if result_path.is_file():
        uc_result = json.loads(result_path.read_text(encoding="utf-8"))
    terminal = uc_result.get("terminal")
    ok = completed.returncode == 0 and terminal in {
        "navigation_only_complete",
        "already_completed",
    }
    frames_dir = uc_session / "frames"
    frame_names = []
    if frames_dir.is_dir():
        frame_names = [
            str(path.relative_to(uc_session)).replace("\\", "/")
            for path in sorted(frames_dir.glob("*.png"))
        ]
    events_rel = "events.jsonl"
    if not (uc_session / events_rel).is_file():
        (uc_session / events_rel).write_text("", encoding="utf-8")
    for name in ("ledger.jsonl", "capability-audit.jsonl", "journal.jsonl"):
        path = uc_session / name
        if not path.is_file():
            path.write_text("", encoding="utf-8")
    if not frame_names:
        png = pnsctl._run_fixed_bluestacks_adb("exec-out", "screencap", "-p", binary=True)
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "operator-terminal.png").write_bytes(png)
        frame_names = ["frames/operator-terminal.png"]
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


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[UC_RUNNER_ID] = run_ultimate_challenge_navigation_only
    validators[UC_EVIDENCE_VALIDATOR_ID] = verify_ultimate_challenge_navigation_only
    handlers[UC_RECOVERY_HANDLER_ID] = recover_ultimate_challenge_navigation_only
