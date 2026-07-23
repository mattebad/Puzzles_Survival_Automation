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
DESTINATIONS = ("1-20-9", "1-15-9", "2-2-9")
CAMPAIGN_RUNNER_ID = "campaign_navigation_only_runner"
CAMPAIGN_EVIDENCE_VALIDATOR_ID = "campaign_navigation_only_evidence"
CAMPAIGN_RECOVERY_HANDLER_ID = "campaign_navigation_only_recovery"


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


def _prepare_canonical_home(session: Path) -> None:
    pnsctl = _pnsctl()
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
    if completed.returncode != 0:
        raise pnsctl.OperatorError(
            "Campaign pre-entry return-canonical failed: "
            f"{completed.stderr or completed.stdout or 'unknown'}"
        )


def run_campaign_navigation_only(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    pnsctl = _pnsctl()
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    destination = _destination_for_attempt(flow)
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"nav-{destination}-{stamp}"
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
    child_sessions = sorted(path for path in session.iterdir() if path.is_dir())
    campaign_session = child_sessions[-1] if child_sessions else session
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
        "flow_id": FLOW_ID,
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
            "flow_id": FLOW_ID,
            "destination": destination,
            "session_directory": str(campaign_session),
            "dispatch": True,
        },
        sort_keys=True,
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


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[CAMPAIGN_RUNNER_ID] = run_campaign_navigation_only
    validators[CAMPAIGN_EVIDENCE_VALIDATOR_ID] = verify_campaign_navigation_only
    handlers[CAMPAIGN_RECOVERY_HANDLER_ID] = recover_campaign_navigation_only
