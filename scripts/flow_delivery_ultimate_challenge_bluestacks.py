#!/usr/bin/env python3
"""Checked-in BlueStacks operator bindings for Ultimate Challenge Daily delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping

import cv2
import numpy as np

from automation_service.registry import ULTIMATE_FLOW_ID, ULTIMATE_MAX_INPUTS
from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    REQUIRED_OPERATOR_ARTIFACTS,
    require_operator_evidence,
)
from safe_action_core.path_safety import UnsafePathError, require_no_untrusted_symlinks
from tasks.ultimate_challenge_daily import (
    BLUESTACKS_RUNTIME_PROFILE_ID,
    TERMINAL_COMPLETE_FOR_RESET,
    load_reset_window_state,
    record_verified_home_success,
    record_pending_home,
    save_reset_window_state,
)
from scripts.startup_normalization import is_clean_home_frame
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = ULTIMATE_FLOW_ID
MAX_TOTAL_INPUTS = ULTIMATE_MAX_INPUTS
UC_RUNNER_ID = "ultimate_challenge_navigation_only_runner"
UC_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_navigation_only_evidence"
UC_DAILY_RUNNER_ID = "ultimate_challenge_daily_runner"
UC_DAILY_EVIDENCE_VALIDATOR_ID = "ultimate_challenge_daily_evidence"
DAILY_PROOF_TOPOLOGY = "continuous"



def _physical_path(path: Path) -> Path:
    """Validate raw path components before resolving aliases to physical paths."""

    return require_no_untrusted_symlinks(Path(path)).resolve()


def _session_reference(session: Path, reference: str | Path) -> tuple[Path, Path]:
    """Return a physical session root and a contained, validated evidence path."""

    safe_session = require_no_untrusted_symlinks(Path(session))
    root = safe_session.resolve()
    raw_reference = Path(reference)
    candidate = (
        raw_reference
        if raw_reference.is_absolute()
        else safe_session / raw_reference
    )
    path = require_no_untrusted_symlinks(candidate).resolve()
    if root not in path.parents:
        raise ValueError("evidence reference escaped its session")
    return root, path


def _operator_evidence_session(session: Path) -> Path:
    """Validate every path the shared operator-evidence reader may open."""

    root = _physical_path(session)
    for name in ("result.json", *REQUIRED_OPERATOR_ARTIFACTS):
        _session_reference(root, name)
    frames = _session_reference(root, "frames")[1]
    frame_paths = sorted(frames.glob("*.png")) if frames.is_dir() else []
    if not frame_paths:
        frames = _session_reference(root, "runtime/frames")[1]
        frame_paths = sorted(frames.glob("*.png")) if frames.is_dir() else []
    for frame in frame_paths:
        _session_reference(root, frame.relative_to(root))
    return root


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
    try:
        _session, candidate = _session_reference(session_directory, relative)
    except (OSError, ValueError):
        return False, None
    if not candidate.is_file():
        return False, None
    payload = candidate.read_bytes()
    expected_hash = str(result.get("home_frame_sha256") or result.get("home_sha256") or "")
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        return False, None
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or not is_clean_home_frame(frame):
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
    try:
        session = _physical_path(
            pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"nav-ultimate-challenge-{stamp}"
        )
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Ultimate Challenge session path contains a link") from exc
    session.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--adb",
        str(BLUESTACKS_ADB),
        "--serial",
        BLUESTACKS_SERIAL,
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
    _root, stdout_path = _session_reference(session, "operator-stdout.log")
    _root, stderr_path = _session_reference(session, "operator-stderr.log")
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    child_sessions = sorted(path for path in session.iterdir() if path.is_dir())
    uc_session = child_sessions[-1] if child_sessions else session
    try:
        uc_session = _operator_evidence_session(uc_session)
        uc_result, frame_names = require_operator_evidence(uc_session)
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Ultimate Challenge evidence session contains a link") from exc
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
        "serial": BLUESTACKS_SERIAL,
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
    _root, delivery_path = _session_reference(uc_session, "flow-delivery-result.json")
    delivery_path.write_text(
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
    for reference in ("events.jsonl", "runtime/events.jsonl"):
        _root, path = _session_reference(session, reference)
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


def _daily_effect_state(result: Mapping[str, Any], flee_count: int) -> str | None:
    if result.get("terminal") == "already_completed" and flee_count == 0:
        return "already_completed"
    actions = result.get("completed_actions") or []
    if result.get("terminal") != "already_completed" and flee_count == 1:
        for action in actions:
            if not isinstance(action, Mapping) or action.get("action") != "tap_flee":
                continue
            if all(
                isinstance(action.get(key), str)
                and len(action[key]) == 64
                and all(char in "0123456789abcdef" for char in action[key])
                for key in ("before_sha256", "post_sha256")
            ):
                return "flee_confirmed"
    return None


def _defeat_flee_recovery_evidence(session: Path, result: Mapping[str, Any]) -> dict[str, str]:
    """Replay a single Flee-to-defeat transition without changing its failed receipt."""
    from scripts import bluestacks_ultimate_challenge as native

    if (result.get("terminal") != "blocked_fail_closed"
            or result.get("completed_actions") != [] or result.get("input_count") != 1):
        raise ValueError("defeat recovery requires an isolated failed Flee attempt")
    session = _physical_path(session)
    _root, event_path = _session_reference(session, "runtime/events.jsonl")
    rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) or row.get("type") not in {"capture", "dispatch"} for row in rows):
        raise ValueError("defeat recovery journal contains an invalid row")
    dispatches = [(index, row) for index, row in enumerate(rows) if row.get("type") == "dispatch"]
    if len(dispatches) != 1:
        raise ValueError("defeat recovery requires exactly one retained dispatch")
    index, dispatch = dispatches[0]
    if (dispatch.get("target_identity") != "tap_flee" or dispatch.get("execute") is not True
            or dispatch.get("consequential") is not True
            or not dispatch.get("action_key") or dispatch["action_key"] != result.get("flee_action_key")):
        raise ValueError("defeat recovery dispatch is not the original Flee")

    def timestamp(row):
        value = datetime.fromisoformat(row["timestamp"])
        if (value.tzinfo is None or value.utcoffset().total_seconds() != 0
                or value > datetime.now(timezone.utc)):
            raise ValueError("defeat recovery timestamp is missing UTC or in the future")
        return value

    def capture(row):
        raw = Path(row["path"])
        try:
            _root, path = _session_reference(session, raw)
        except (OSError, ValueError) as exc:
            raise ValueError("defeat recovery capture escaped its session") from exc
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError("defeat recovery capture hash changed")
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (1280, 800, 3):
            raise ValueError("defeat recovery capture is not native")
        return frame

    captures = [(i, row) for i, row in enumerate(rows) if row.get("type") == "capture"]
    previous = -1.0
    for _, row in captures:
        value = row.get("captured_monotonic")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= previous:
            raise ValueError("defeat recovery capture chronology is invalid")
        previous = value
        timestamp(row)
    sources = [row for i, row in captures if i < index and row.get("sha256") == dispatch.get("source_sha256")]
    posts = [row for i, row in captures if i > index]
    if not sources or len(posts) < 2:
        raise ValueError("defeat recovery lacks its warning source or persistent successor")
    source = sources[-1]
    target = native._bind_flee_warning_button(capture(source))
    if target is None or list(target) != dispatch.get("target_roi"):
        raise ValueError("defeat recovery Flee source/target is not verified")
    sent = timestamp(dispatch)
    if timestamp(source) > sent:
        raise ValueError("defeat recovery source follows its dispatch")
    for post in posts[-2:]:
        if (timestamp(post) < sent
                or native._bind_ultimate_defeat_continue(capture(post)) is None):
            raise ValueError("defeat recovery lacks a verified post-Flee defeat successor")
    return {"recovery_kind": "defeat_after_flee", "flee_action_key": dispatch["action_key"],
        "flee_before_sha256": source["sha256"], "flee_after_sha256": posts[-1]["sha256"]}


def _validated_flee_recovery(
    session: Path, reset_identity: str, expected_result_sha256: str | None = None,
) -> dict[str, str]:
    """Validate one exact retained Flee effect; this grants no input authority."""
    try:
        session = _physical_path(session)
        session = _operator_evidence_session(session)
        result, _ = require_operator_evidence(session)
        _root, result_path = _session_reference(session, "result.json")
        result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
        _root, delivery_path = _session_reference(session, "flow-delivery-result.json")
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        if (
            result.get("flow_id") != FLOW_ID
            or result.get("reset_identity") != reset_identity
            or delivery.get("flow_id") != FLOW_ID
            or delivery.get("serial") != BLUESTACKS_SERIAL
            or delivery.get("native_width") != 800
            or delivery.get("native_height") != 1280
            or delivery.get("runtime_profile_id", BLUESTACKS_RUNTIME_PROFILE_ID) != BLUESTACKS_RUNTIME_PROFILE_ID
            or delivery.get("ultimate_challenge_result") != result
            or (expected_result_sha256 is not None and result_hash != expected_result_sha256)
            or _retained_transport_count(session) != result.get("input_count")
            or type(result.get("input_count")) is not int
            or not 1 <= result["input_count"] <= MAX_TOTAL_INPUTS
        ):
            raise ValueError("flow/reset/profile/Flee accounting mismatch")
        if _daily_effect_state(result, _retained_flee_transport_count(session)) != "flee_confirmed":
            evidence = _defeat_flee_recovery_evidence(session, result)
            return {"session_directory": str(session), "result_sha256": result_hash,
                "reset_identity": reset_identity, "runtime_profile_id": BLUESTACKS_RUNTIME_PROFILE_ID,
                **evidence}
        actions = [row for row in result["completed_actions"] if isinstance(row, Mapping) and row.get("action") == "tap_flee"]
        if len(actions) != 1:
            raise ValueError("exactly one confirmed Flee action is required")
        effect = actions[0]
        events = _read_events(session)
        dispatch = next(row for row in events if row.get("type") == "dispatch" and row.get("target_identity") == "tap_flee" and row.get("execute") is not False)
        if dispatch.get("source_sha256") != effect["before_sha256"] or not any(
            row.get("type") == "reconcile"
            and row.get("action_key") == dispatch.get("action_key")
            and row.get("status") == "confirmed"
            and row.get("post_sha256") == effect["post_sha256"]
            for row in events
        ):
            raise ValueError("Flee dispatch and confirmed successor do not match")
        for digest in (effect["before_sha256"], effect["post_sha256"]):
            captures = [row for row in events if row.get("type") == "capture" and row.get("sha256") == digest]
            valid = False
            for capture in captures:
                raw_path = Path(str(capture.get("path") or ""))
                try:
                    _root, path = _session_reference(session, raw_path)
                except (OSError, ValueError):
                    continue
                if not path.is_file():
                    continue
                data = path.read_bytes()
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if hashlib.sha256(data).hexdigest() == digest and frame is not None and frame.shape == (1280, 800, 3):
                    valid = True
                    break
            if not valid:
                raise ValueError("Flee source/successor native capture integrity failed")
        return {
            "session_directory": str(session),
            "result_sha256": result_hash,
            "reset_identity": reset_identity,
            "runtime_profile_id": BLUESTACKS_RUNTIME_PROFILE_ID,
        }
    except (OSError, ValueError, TypeError, KeyError, StopIteration, FlowEvidenceIntegrityError) as exc:
        raise _pnsctl().OperatorError(f"Ultimate recovery evidence rejected: {exc}") from exc


def _write_daily_causal_trace(
    session: Path,
    *,
    initial_observation: Mapping[str, Any],
    transport_count: int,
    terminal: str,
    home_verified: bool,
    flee_count: int,
    semantic_effect_state: str | None,
    recovery_evidence: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "stages": ["typed_initial_observation"] + (
            ["challenge_flee_confirmed", "canonical_home_terminal"]
            if semantic_effect_state == "flee_confirmed" and home_verified
            else ["already_completed_reset_check", "canonical_home_terminal"]
            if semantic_effect_state == "already_completed" and home_verified
            else ["route_evidence_required"]
        ),
        "proof_topology": "composite" if recovery_evidence else DAILY_PROOF_TOPOLOGY,
        "terminal_recovery": dict(recovery_evidence) if recovery_evidence else None,
        "transport_count": transport_count,
        "new_flee_transport_count": flee_count,
        "semantic_effect_state": semantic_effect_state,
        "terminal": terminal,
        "canonical_home_verified": home_verified,
    }
    _root, trace_path = _session_reference(session, "causal-trace.json")
    trace_path.write_text(
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
    try:
        session = _physical_path(
            pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"daily-{stamp}"
        )
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Ultimate Challenge session path contains a link") from exc
    session.mkdir(parents=True, exist_ok=False)
    reset_identity = _current_reset_identity()
    reset_state_path = _reset_window_state_path()
    state = load_reset_window_state(reset_state_path)
    if state.pending_home_session and state.reset_identity != reset_identity:
        raise pnsctl.OperatorError("Ultimate pending Home belongs to another reset; no new combat is allowed")
    recovery_path = lease.get("recovery_session") if lease.get("recovery_only") else state.pending_home_session
    if lease.get("recovery_only") and not recovery_path:
        raise pnsctl.OperatorError("Ultimate recovery requires a retained session")
    recovery_evidence = None
    if recovery_path:
        if state.pending_home_session:
            try:
                recovery_root = _physical_path(Path(recovery_path))
                pending_root = _physical_path(Path(state.pending_home_session))
            except UnsafePathError as exc:
                raise pnsctl.OperatorError("Ultimate recovery session path contains a link") from exc
            if recovery_root != pending_root:
                raise pnsctl.OperatorError("Ultimate recovery does not match the pending Flee session")
        recovery_evidence = _validated_flee_recovery(
            Path(recovery_path), reset_identity, state.pending_home_result_sha256,
        )
        if state.last_success_reset_identity == reset_identity:
            raise pnsctl.OperatorError("Ultimate is already completed for this reset")
        state = record_pending_home(
            state, reset_identity=reset_identity,
            session_directory=recovery_evidence["session_directory"],
            result_sha256=recovery_evidence["result_sha256"],
        )
        save_reset_window_state(reset_state_path, state)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "bluestacks_ultimate_challenge.py"),
        "--post-flee-home-only" if recovery_evidence else "--daily",
        "--adb", str(BLUESTACKS_ADB),
        "--serial", BLUESTACKS_SERIAL,
        "--execute", "--yes",
        "--reset-identity", reset_identity,
        "--max-total-inputs", str(maximum),
        "--output-directory", str(session),
    ]
    if recovery_evidence is None:
        command.extend(["--reset-state-path", str(reset_state_path)])
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    _root, stdout_path = _session_reference(session, "operator-stdout.log")
    _root, stderr_path = _session_reference(session, "operator-stderr.log")
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    child_sessions = sorted(path for path in session.iterdir() if path.is_dir())
    uc_session = child_sessions[-1] if child_sessions else session
    try:
        uc_session = _operator_evidence_session(uc_session)
        uc_result, frame_names = require_operator_evidence(uc_session)
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Ultimate Challenge evidence session contains a link") from exc
    except FlowEvidenceIntegrityError as exc:
        raise pnsctl.OperatorError(f"Ultimate Challenge executable/evidence-integrity failure: {exc}") from exc
    terminal = uc_result.get("terminal")
    home_verified, home_path = _verified_home_evidence(uc_session, uc_result)
    input_count = uc_result.get("input_count")
    retained_transport = _retained_transport_count(uc_session)
    retained_flee = _retained_flee_transport_count(uc_session)
    semantic_effect_state = _daily_effect_state(uc_result, retained_flee)
    if recovery_evidence is not None:
        if retained_flee != 0:
            raise pnsctl.OperatorError("Ultimate terminal recovery dispatched a new Flee")
        semantic_effect_state = "flee_confirmed"
    ok = (
        completed.returncode == 0
        and terminal in {TERMINAL_COMPLETE_FOR_RESET, "already_completed"}
        and home_verified
        and type(input_count) is int
        and 0 <= input_count <= maximum
        and retained_transport == input_count
        and semantic_effect_state is not None
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
        _root, source = _session_reference(
            Path(outer_session.session_directory), "source.png"
        )
        _root, retained_initial = _session_reference(
            uc_session, "frames/0000-initial-observation.png"
        )
        if not source.is_file():
            raise pnsctl.OperatorError(
                "Ultimate terminal session initial frame is not retained"
            )
        retained_initial.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, retained_initial)
        initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        trace = _write_daily_causal_trace(
            uc_session,
            initial_observation=initial_observation,
            transport_count=retained_transport,
            terminal=str(terminal or "blocked"),
            home_verified=home_verified,
            flee_count=retained_flee,
            semantic_effect_state=semantic_effect_state,
            recovery_evidence=recovery_evidence,
        )
        outer_session.set_causal_trace(trace)
        outer_session.remember_control("ultimate_semantic_effect_state", semantic_effect_state)
        outer_session.remember_control(
            "ultimate_terminal_reconciliation",
            "canonical_home_verified" if ok else "evidence_required",
        )
    reconciliation_required = bool(migrated_session and retained_transport and not ok)
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed" if ok else "failed",
        "serial": BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": lease["owner"],
        "terminal_runtime_state": "recognized_home" if home_verified else "safe_blocked_terminal",
        "ultimate_challenge_result": uc_result,
        "actions": [
            {
                "action_class": "terminal_recovery" if recovery_evidence else "zero_resource_flee",
                "path": "validated_flee_to_home" if recovery_evidence else "home_to_ultimate_challenge_flee_home",
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
        "semantic_effect_state": semantic_effect_state,
        "semantic_effect_verified": semantic_effect_state is not None,
        "terminal_completion_verified": ok,
        "proof_topology": "composite" if recovery_evidence else DAILY_PROOF_TOPOLOGY,
        "terminal_recovery": recovery_evidence,
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
    _root, delivery_path = _session_reference(uc_session, "flow-delivery-result.json")
    delivery_path.write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not ok and recovery_evidence is None and semantic_effect_state == "flee_confirmed":
        pending = _validated_flee_recovery(uc_session, reset_identity)
        save_reset_window_state(
            reset_state_path,
            record_pending_home(
                state, reset_identity=reset_identity,
                session_directory=pending["session_directory"], result_sha256=pending["result_sha256"],
            ),
        )
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
    try:
        session_directory = _physical_path(Path(str(structure["session_directory"])))
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Ultimate Challenge evidence session contains a link") from exc
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
            frame_reference = str(initial.get("frame_path") or "")
            _session_reference(session_directory, frame_reference)
            retained = pnsctl._session_relative_path(
                session_directory,
                frame_reference,
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
    expected_effect = _daily_effect_state(uc, retained_flee)
    recovery = result.get("terminal_recovery")
    recovery_ok = False
    if isinstance(recovery, Mapping):
        try:
            checked = _validated_flee_recovery(
                Path(str(recovery.get("session_directory") or "")),
                str(result.get("reset_identity") or ""),
                str(recovery.get("result_sha256") or ""),
            )
            recovery_ok = checked == dict(recovery) and retained_flee == 0
        except pnsctl.OperatorError:
            recovery_ok = False
        expected_effect = "flee_confirmed" if recovery_ok else None
    topology = "composite" if recovery is not None else DAILY_PROOF_TOPOLOGY
    transport_ok = bool(
        retained_transport == result.get("input_count")
        and retained_transport == result.get("dispatch_count")
        and 0 <= retained_transport <= MAX_TOTAL_INPUTS
        and retained_flee == result.get("new_flee_transport_count")
        and expected_effect is not None
    )
    trace_ok = bool(
        result.get("proof_topology") == topology
        and result.get("causal_trace_count") == 1
        and isinstance(trace, Mapping)
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("proof_topology") == topology
        and trace.get("terminal_recovery") == recovery
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("new_flee_transport_count") == retained_flee
        and trace.get("semantic_effect_state") == expected_effect
    )
    semantic_effect_ok = bool(
        expected_effect is not None
        and result.get("semantic_effect_state") == expected_effect
        and result.get("semantic_effect_verified") is True
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
        "verified_home_path": str(home_path.relative_to(session_directory)).replace("\\", "/"),
        "initial_observation_verified": initial_ok,
        "transport_accounting_verified": transport_ok,
        "new_flee_transport_count": retained_flee,
        "causal_trace_verified": trace_ok,
        "semantic_effect_verified": semantic_effect_ok,
        "terminal_completion_verified": result.get("terminal_completion_verified") is True,
        "proof_topology": topology,
        "terminal_recovery_verified": recovery_ok,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
) -> None:
    runners[UC_RUNNER_ID] = run_ultimate_challenge_navigation_only
    validators[UC_EVIDENCE_VALIDATOR_ID] = verify_ultimate_challenge_navigation_only
    runners[UC_DAILY_RUNNER_ID] = run_ultimate_challenge_daily
    validators[UC_DAILY_EVIDENCE_VALIDATOR_ID] = verify_ultimate_challenge_daily
