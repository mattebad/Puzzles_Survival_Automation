#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Ultimate Challenge Daily delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
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
TERMINAL_RECONCILIATION_TOPOLOGY = "continuous"
RETAINED_FLEE_PROOF_TOPOLOGY = "composite"
RETAINED_EFFECT_EVIDENCE_REFS = (
    "tasks/flow_delivery_queue.json#ultimate-attempt-13",
    "tasks/flow_delivery_queue.json#ultimate-attempt-14",
)


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
    _legacy_flow, maximum = _ultimate_runtime_context(queue, lease)
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
        "--max-total-inputs",
        str(maximum),
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
        raise _pnsctl().OperatorError(
            "legacy flow-delivery queue flows are required"
        )
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


def _ultimate_runtime_context(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, int]:
    """Validate the current session contract before creating or launching a child."""

    development_session = lease.get("development_session")
    live_development_session = development_session is True or isinstance(
        getattr(development_session, "session_directory", None), Path
    )
    marker_present = (
        "development_session" in queue
        or "development_session" in lease
    )
    if marker_present:
        if queue.get("development_session") is not True or not live_development_session:
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
        if type(maximum) is not int or maximum != MAX_TOTAL_INPUTS:
            raise _pnsctl().OperatorError(
                "Ultimate Challenge development session max_inputs must be exactly 16"
            )
        route_maximum = lease.get("route_max_inputs", maximum)
        if (
            type(route_maximum) is not int
            or route_maximum < 0
            or route_maximum > maximum
        ):
            raise _pnsctl().OperatorError(
                "Ultimate Challenge route_max_inputs must be within the shared 16-input ceiling"
            )
        return None, route_maximum

    if lease.get("runtime_ownership_state") != "held":
        raise _pnsctl().OperatorError(
            "Ultimate Challenge runner requires held runtime ownership"
        )
    owner = lease.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise _pnsctl().OperatorError("Ultimate Challenge runner owner is required")
    flow = _legacy_daily_flow(queue)
    maximum = lease.get("max_inputs")
    if "max_inputs" not in lease:
        raise _pnsctl().OperatorError(
            "Ultimate Challenge legacy context max_inputs must be explicitly set to 16"
        )
    if type(maximum) is not int or maximum != MAX_TOTAL_INPUTS:
        raise _pnsctl().OperatorError(
            "Ultimate Challenge max_inputs must be exactly 16"
        )
    return flow, MAX_TOTAL_INPUTS


def _terminal_development_session(lease: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Require the exact active session and its identity-bound initial frame."""

    from scripts.navigation_development_boundary import (
        DevelopmentInitialObservation,
        DevelopmentSession,
    )

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{FLOW_ID}"
        or not callable(getattr(session, "run_action", None))
    ):
        raise _pnsctl().OperatorError(
            "Ultimate terminal reconciliation requires the active pnsctl-owned DevelopmentSession"
        )
    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Ultimate terminal initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Ultimate terminal initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Ultimate terminal initial observation hash or invocation binding is invalid"
        )
    return session, value.to_mapping()


def _read_events(session: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in (session / "events.jsonl", session / "runtime" / "events.jsonl"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if isinstance(row, dict) and row:
                rows.append(row)
    return rows


def _retained_transport_count(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch" and row.get("execute") is not False
        for row in _read_events(session)
    )


def _retained_flee_transport_count(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch"
        and row.get("execute") is not False
        and (
            row.get("target_identity") == "tap_flee"
            or str(row.get("action_key") or "").startswith("tap_flee")
        )
        for row in _read_events(session)
    )


def _write_terminal_causal_trace(
    session: Path,
    *,
    initial_observation: Mapping[str, Any],
    transport_count: int,
    terminal: str,
    home_verified: bool,
) -> dict[str, Any]:
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "stages": [
            "typed_initial_observation",
            "retained_flee_effect_state",
            "ultimate_main_recognition",
            "ultimate_to_campaign_successor",
            "measured_campaign_exit",
            "canonical_home_terminal",
        ],
        "proof_topology": RETAINED_FLEE_PROOF_TOPOLOGY,
        "terminal_reconciliation_topology": TERMINAL_RECONCILIATION_TOPOLOGY,
        "transport_count": transport_count,
        "new_flee_transport_count": 0,
        "semantic_effect_state": "retained_flee_confirmed",
        "retained_effect_evidence_refs": list(RETAINED_EFFECT_EVIDENCE_REFS),
        "terminal": terminal,
        "canonical_home_verified": home_verified,
    }
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return trace


def run_ultimate_challenge_daily(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    """Run the approved zero-resource Flee route through the production operator."""

    pnsctl = _pnsctl()
    flow, maximum = _ultimate_runtime_context(queue, lease)
    migrated_session = queue.get("development_session") is True
    outer_session = None
    initial_observation: dict[str, Any] | None = None
    if migrated_session:
        outer_session, initial_observation = _terminal_development_session(lease)
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"daily-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    reset_identity = _current_reset_identity()
    reset_state_path = _reset_window_state_path()
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--post-flee-home-only" if migrated_session else "--daily",
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
    permitted_terminals = (
        {TERMINAL_COMPLETE_FOR_RESET}
        if migrated_session
        else {TERMINAL_COMPLETE_FOR_RESET, "already_completed"}
    )
    ok = (
        completed.returncode == 0
        and terminal in permitted_terminals
        and home_verified
        and type(input_count) is int
        and 0 <= input_count <= maximum
    )
    retained_transport = _retained_transport_count(uc_session)
    retained_flee = _retained_flee_transport_count(uc_session)
    if migrated_session and retained_flee != 0:
        raise pnsctl.OperatorError(
            "Ultimate terminal reconciliation attempted a forbidden new Flee"
        )
    if migrated_session and retained_transport != input_count:
        raise pnsctl.OperatorError(
            "Ultimate terminal retained transports do not match route accounting"
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
    trace = None
    if migrated_session and initial_observation is not None and outer_session is not None:
        source = Path(outer_session.session_directory) / "source.png"
        retained_initial = uc_session / "frames" / "0000-initial-observation.png"
        if not source.is_file():
            raise pnsctl.OperatorError(
                "Ultimate terminal session initial frame is not retained"
            )
        retained_initial.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, retained_initial)
        initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        trace = _write_terminal_causal_trace(
            uc_session,
            initial_observation=initial_observation,
            transport_count=retained_transport,
            terminal=str(terminal or "blocked"),
            home_verified=home_verified,
        )
        outer_session.set_causal_trace(trace)
        outer_session.remember_control("ultimate_semantic_effect_state", "retained_flee_confirmed")
        outer_session.remember_control(
            "ultimate_terminal_reconciliation",
            "canonical_home_verified" if ok else "evidence_required",
        )
    reconciliation_required = bool(migrated_session and retained_transport and not ok)
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
        "actions": [
            {
                "action_class": (
                    "terminal_reconciliation"
                    if migrated_session
                    else "zero_resource_flee"
                ),
                "path": (
                    "retained_flee_ultimate_to_campaign_measured_exit_home"
                    if migrated_session
                    else "home_to_ultimate_challenge_flee_home"
                ),
                "outcome": terminal,
            }
        ],
        "events_path": "events.jsonl",
        "transport_events_path": "runtime/events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": completed.returncode,
        "input_count": input_count,
        "dispatch_count": retained_transport,
        "new_flee_transport_count": retained_flee,
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
        "semantic_effect_state": "retained_flee_confirmed" if migrated_session else None,
        "semantic_effect_verified": migrated_session,
        "retained_effect_evidence_refs": (
            list(RETAINED_EFFECT_EVIDENCE_REFS) if migrated_session else []
        ),
        "terminal_completion_verified": ok,
        "proof_topology": RETAINED_FLEE_PROOF_TOPOLOGY if migrated_session else "composite",
        "terminal_reconciliation_topology": (
            TERMINAL_RECONCILIATION_TOPOLOGY if migrated_session else None
        ),
        "initial_observation": initial_observation,
        "initial_frame_sha256": (
            str(initial_observation.get("frame_sha256") or "")
            if initial_observation is not None
            else ""
        ),
        "causal_trace_count": 1 if trace is not None else 0,
        "causal_trace": trace,
        "effect_reconciliation_required": reconciliation_required,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    if reconciliation_required:
        delivery["status"] = "effect_reconciliation_required"
    (uc_session / "flow-delivery-result.json").write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not ok and not reconciliation_required:
        raise pnsctl.OperatorError("Ultimate Challenge Daily failed: " + str(uc_result.get("reason") or completed.stderr or completed.stdout or "unknown"))
    return json.dumps(
        {
            "status": delivery["status"],
            "flow_id": FLOW_ID,
            "terminal": terminal,
            "session_directory": str(uc_session),
            "dispatch": retained_transport > 0,
            "proof_topology": delivery["proof_topology"],
            "terminal_reconciliation_topology": delivery[
                "terminal_reconciliation_topology"
            ],
            "causal_trace_count": delivery["causal_trace_count"],
            "effect_reconciliation_required": reconciliation_required,
            "retained_transport_count": retained_transport,
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
    initial = result.get("initial_observation")
    trace = result.get("causal_trace")
    initial_ok = False
    if isinstance(initial, Mapping):
        digest = str(initial.get("frame_sha256") or "")
        try:
            retained = pnsctl._session_relative_path(
                session_directory,
                str(initial.get("frame_path") or ""),
                "initial_observation.frame_path",
            )
            initial_ok = bool(
                len(digest) == 64
                and retained.is_file()
                and hashlib.sha256(retained.read_bytes()).hexdigest() == digest
                and digest == str(result.get("initial_frame_sha256") or "")
                and str(initial.get("invocation_id") or "")
            )
        except Exception:
            initial_ok = False
    retained_transport = _retained_transport_count(session_directory)
    retained_flee = _retained_flee_transport_count(session_directory)
    transport_ok = bool(
        retained_transport == result.get("input_count")
        and retained_transport == result.get("dispatch_count")
        and 2 <= retained_transport <= MAX_TOTAL_INPUTS
        and retained_flee == result.get("new_flee_transport_count") == 0
    )
    trace_ok = bool(
        result.get("proof_topology") == RETAINED_FLEE_PROOF_TOPOLOGY
        and result.get("terminal_reconciliation_topology")
        == TERMINAL_RECONCILIATION_TOPOLOGY
        and result.get("causal_trace_count") == 1
        and isinstance(trace, Mapping)
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("proof_topology") == RETAINED_FLEE_PROOF_TOPOLOGY
        and trace.get("terminal_reconciliation_topology")
        == TERMINAL_RECONCILIATION_TOPOLOGY
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("new_flee_transport_count") == 0
    )
    semantic_effect_ok = bool(
        result.get("semantic_effect_state") == "retained_flee_confirmed"
        and result.get("semantic_effect_verified") is True
        and result.get("retained_effect_evidence_refs")
        == list(RETAINED_EFFECT_EVIDENCE_REFS)
        and result.get("terminal_completion_verified") is True
    )
    verified = bool(
        result.get("status") == "completed"
        and result.get("effect_reconciliation_required") is False
        and initial_ok
        and transport_ok
        and trace_ok
        and semantic_effect_ok
        and result.get("production_registration") == "NOT_REGISTERED"
        and result.get("scheduler_enabled") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "terminal": uc.get("terminal"),
        "session_directory": structure["session_directory"],
        "actions": result.get("actions", []),
        "terminal_runtime_state": result["terminal_runtime_state"],
        "verified_home_path": str(home_path.relative_to(session_directory.resolve())).replace("\\", "/"),
        "initial_observation_verified": initial_ok,
        "transport_accounting_verified": transport_ok,
        "zero_new_flee_verified": retained_flee == 0,
        "causal_trace_verified": trace_ok,
        "semantic_effect_verified": semantic_effect_ok,
        "retained_effect_evidence_refs": list(RETAINED_EFFECT_EVIDENCE_REFS),
        "terminal_completion_verified": result.get("terminal_completion_verified") is True,
        "proof_topology": RETAINED_FLEE_PROOF_TOPOLOGY,
        "terminal_reconciliation_topology": TERMINAL_RECONCILIATION_TOPOLOGY,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


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
