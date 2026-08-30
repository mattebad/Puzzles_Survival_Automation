"""Fixed development-session binding for the supervised Nova Praise pulse."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any, Mapping
from automation_service.registry import (
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RegisteredDispatchSnapshot,
)


_REGISTRATION_FIELDS = frozenset(
    {
        "flow_id",
        "product_id",
        "product_revision",
        "production_handler",
        "profile",
        "mode",
        "registration_status",
        "scheduler_eligible",
    }
)


def _validated_registration_snapshot(
    value: object,
    *,
    require_typed: bool = False,
) -> dict[str, Any]:
    """Rehydrate only the exact consumed Nova registration snapshot."""

    if require_typed and not isinstance(value, RegisteredDispatchSnapshot):
        raise _pnsctl().OperatorError(
            "Nova live execution requires the atomically consumed registration snapshot"
        )
    try:
        snapshot = (
            value
            if isinstance(value, RegisteredDispatchSnapshot)
            else RegisteredDispatchSnapshot.from_mapping(value)  # type: ignore[arg-type]
        )
        mapping = snapshot.to_mapping()
    except (TypeError, ValueError, KeyError) as exc:
        raise _pnsctl().OperatorError(
            "Nova dispatch registration snapshot is incomplete or invalid"
        ) from exc
    if set(mapping) != _REGISTRATION_FIELDS or mapping != {
        "flow_id": NOVA_FLOW_ID,
        "product_id": NOVA_PRODUCT_ID,
        "product_revision": NOVA_PRODUCT_REVISION,
        "production_handler": NOVA_HANDLER_ID,
        "profile": NOVA_PROFILE_ID,
        "mode": NOVA_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    }:
        raise _pnsctl().OperatorError(
            "Nova dispatch registration snapshot is not the fixed Nova binding"
        )
    return mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
SCENARIO_ID = "nova_praise_one_free_pulse"
RUNNER_ID = "nova_praise_supervised_one_free_pulse_runner"
VALIDATOR_ID = "nova_praise_supervised_one_free_pulse_evidence"
RECOVERY_ID = "nova_praise_supervised_one_free_pulse_recovery"
MAX_INPUTS = 8
MAX_PRAISE = 1


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _max_inputs(lease: Mapping[str, Any]) -> int:
    value = lease.get("max_inputs")
    try:
        maximum = int(value)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Nova development-session max_inputs is required"
        ) from exc
    if not 1 <= maximum <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Nova development-session max_inputs must be between 1 and {MAX_INPUTS}"
        )
    return maximum


def _identity(lease: Mapping[str, Any]) -> Any:
    identity = lease.get("nova_identity")
    required = ("runtime_scope", "account_id", "server_id", "reset_id")
    if identity is None or any(
        not isinstance(getattr(identity, field, None), str)
        or not str(getattr(identity, field)).strip()
        for field in required
    ):
        raise _pnsctl().OperatorError(
            "Nova development-session requires verified account/server/reset identity"
        )
    reset_id = _pnsctl()._validate_nova_reset_id(identity.reset_id)
    if lease.get("nova_reset_id") != reset_id:
        raise _pnsctl().OperatorError(
            "Nova development-session reset_id does not match verified identity"
        )
    return identity


def _outer_session(lease: Mapping[str, Any]) -> Any:
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{FLOW_ID}"
        or not callable(getattr(session, "run_action", None))
    ):
        raise _pnsctl().OperatorError(
            "Nova Praise requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Nova Praise initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Nova Praise initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Nova Praise initial observation hash or invocation binding is invalid"
        )
    return value.to_mapping()


def _read_events(session: Path) -> list[dict[str, Any]]:
    events = session / "events.jsonl"
    if not events.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in events.read_text(encoding="utf-8").splitlines():
        row = json.loads(line) if line.strip() else {}
        if isinstance(row, dict) and row:
            rows.append(row)
    return rows


def _retained_transport_count(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch" and row.get("execute") is not False
        for row in _read_events(session)
    )


def _retained_praise_count(session: Path, action_key: str) -> int:
    return sum(
        row.get("type") == "dispatch"
        and row.get("execute") is not False
        and row.get("consequential") is True
        and row.get("action_key") == action_key
        for row in _read_events(session)
    )


def _write_read_only_causal_trace(
    session: Path,
    *,
    flow_result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
    registration_snapshot: object | None = None,
) -> dict[str, Any]:
    events = _read_events(session)
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "stages": [
            "observation",
            "home_atlas_navigation",
            "praise_intent",
            "current_frame_target_binding",
            "transport",
            "attempts_cooldown_successor",
            "terminal_home",
        ],
        "proof_topology": "continuous",
        "flow_id": FLOW_ID,
        "scheduler_enabled": False,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "transport_count": _retained_transport_count(session),
        "praise_transport_calls": int(flow_result.get("praise_transport_calls") or 0),
        "event_count": len(events),
        "status": str(flow_result.get("status") or "unknown"),
        "effect_reconciliation_required": bool(
            flow_result.get("effect_reconciliation_required")
        ),
    }
    if registration_snapshot is not None:
        snapshot = _validated_registration_snapshot(registration_snapshot)
        trace["registration_snapshot"] = snapshot
        trace["dispatch_registration"] = dict(snapshot)
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return trace


def _candidate_commit() -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _pnsctl().OperatorError(
            "Nova development-session candidate commit is unavailable"
        ) from exc
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise _pnsctl().OperatorError(
            "Nova development-session candidate commit is invalid"
        )
    return value


def _scenario_record(
    result: Mapping[str, Any],
    *,
    candidate_commit: str,
    session: str,
) -> dict[str, Any]:
    status = str(result.get("status") or "blocked")
    navigation = int(result.get("navigation_input_count") or 0)
    praise = int(result.get("praise_transport_calls") or 0)
    if status == "completed" and praise == 1:
        outcome = "completed"
        consumes = True
        reason = "confirmed_praise_and_verified_safe_return_home"
    elif praise:
        outcome = "unresolved"
        consumes = True
        reason = str(result.get("reason") or "praise_unresolved")
    else:
        outcome = "blocked"
        consumes = navigation > 0
        reason = str(result.get("reason") or "supervised_pulse_blocked")
    return {
        "scenario_id": SCENARIO_ID,
        "phase": "execution" if consumes else "pre_input",
        "outcome": outcome,
        "candidate_commit": candidate_commit,
        "navigation_input_count": navigation,
        "praise_transport_calls": praise,
        "input_class": (
            "mixed_navigation_and_one_consequential"
            if praise
            else "navigation_only"
            if navigation
            else "none"
        ),
        "consumes_execution_budget": consumes,
        "reason": reason,
        "failure_class": None if outcome == "completed" else "postcondition",
        "terminal_ownership_state": "released",
        "unresolved_action": outcome == "unresolved",
        "evidence_refs": [session] if session else [],
        "input_count": navigation + praise,
    }


def _write_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
    maximum: int,
    candidate_commit: str,
) -> None:
    frames = sorted(
        path.relative_to(session).as_posix()
        for path in (session / "frames").glob("*.png")
        if path.is_file() and not path.is_symlink()
    )
    if not frames:
        raise _pnsctl().OperatorError(
            "Nova Praise development-session produced no native frame evidence"
        )
    snapshot = None
    if result.get("production_registration") == "REGISTERED":
        snapshot = _validated_registration_snapshot(result.get("registration_snapshot"))
    payload = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
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
                "action_class": "mixed_navigation_and_one_consequential",
                "path": "home_to_nova_one_free_praise_to_home",
                "outcome": result.get("status"),
            }
        ],
        "required_artifacts": [
            "events_path",
            "ledger_path",
            "capability_audit_path",
            "journal_path",
        ],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frames,
        "dispatch": int(result.get("navigation_input_count") or 0)
        + int(result.get("praise_transport_calls") or 0)
        > 0,
        "dispatch_count": int(result.get("navigation_input_count") or 0)
        + int(result.get("praise_transport_calls") or 0),
        "input_count": int(result.get("navigation_input_count") or 0)
        + int(result.get("praise_transport_calls") or 0),
        "max_inputs": maximum,
        "praise_transport_calls": int(result.get("praise_transport_calls") or 0),
        "attempts_before": result.get("attempts_before"),
        "attempts_after": result.get("attempts_after"),
        "cooldown_seconds": result.get("cooldown_seconds"),
        "action_id": result.get("action_id"),
        "action_key": result.get("action_key"),
        "journal_status": result.get("journal_status"),
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "proof_topology": str(result.get("proof_topology") or "continuous"),
        "initial_observation": result.get("initial_observation"),
        "initial_frame_sha256": str(result.get("initial_frame_sha256") or ""),
        "causal_trace_count": int(result.get("causal_trace_count") or 1),
        "causal_trace": result.get("causal_trace"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
        "candidate_commit": candidate_commit,
        "production_registration": result.get(
            "production_registration", "NOT_REGISTERED"
        ),
        "scheduler_enabled": False,
    }
    if snapshot is not None:
        payload["registration_snapshot"] = dict(snapshot)
        payload["dispatch_registration"] = dict(snapshot)
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run_nova_praise_supervised_one_free_pulse(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    """Run Nova inside the already-owned outer DevelopmentSession."""

    del queue
    pnsctl = _pnsctl()
    maximum = _max_inputs(lease)
    identity = _identity(lease)
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "scenario_id": SCENARIO_ID,
                "dispatch": False,
                "input_count": 0,
                "max_inputs": maximum,
                "reset_id": identity.reset_id,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    registration_snapshot = _validated_registration_snapshot(
        lease.get("registration_snapshot"), require_typed=True
    )
    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
    candidate_commit = _candidate_commit()
    reset_id = pnsctl._validate_nova_reset_id(identity.reset_id)
    pnsctl._create_nova_supervised_invocation_guard(
        candidate_commit=candidate_commit,
        reset_id=reset_id,
    )
    session = ""
    terminal_status = "failed"
    result_status: str | None = None
    try:
        from scripts import nova_praise_bluestacks as route_module

        args = SimpleNamespace(
            adb=pnsctl.BLUESTACKS_ADB,
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=pnsctl.NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT,
            action_database=pnsctl.NOVA_SUPERVISED_ACTION_DATABASE,
            owner=str(lease.get("owner") or "pnsctl-development-session"),
            invocation_id=str(
                lease.get("invocation_id")
                or f"{FLOW_ID}-{_stamp()}"
            ),
            lease_ttl=3600.0,
            settle_seconds=float(lease.get("settle_seconds", 1.0)),
        )
        result = json.loads(
            route_module.run_nova_praise_one_free_pulse(args, identity)
        )
        result_status = str(result.get("status") or "blocked")
        session = str(result.get("session_directory") or "")
        if session:
            pnsctl._bind_nova_supervised_invocation_guard_session(
                session,
                reset_id=reset_id,
            )
        navigation = int(result.get("navigation_input_count") or 0)
        praise = int(result.get("praise_transport_calls") or 0)
        runtime_session = Path(session) if session else Path(outer_session.session_directory)
        source_path = Path(outer_session.session_directory) / "source.png"
        if session and source_path.is_file():
            retained_initial = runtime_session / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, retained_initial)
            initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        if navigation + praise > maximum:
            raise pnsctl.OperatorError(
                "Nova development-session exceeded its max_inputs ceiling"
            )
        if praise > MAX_PRAISE:
            raise pnsctl.OperatorError(
                "Nova development-session exceeded its one-Praise ceiling"
            )
        retained_transport = _retained_transport_count(runtime_session)
        action_key = str(result.get("action_key") or "")
        retained_praise = _retained_praise_count(runtime_session, action_key)
        if retained_transport != navigation + praise:
            raise pnsctl.OperatorError(
                "Nova retained transport count does not match route accounting"
            )
        if retained_praise != praise:
            raise pnsctl.OperatorError(
                "Nova retained Praise dispatch count does not match route accounting"
            )
        semantic_success = bool(
            result.get("status") == "completed"
            and praise == MAX_PRAISE
            and pnsctl._supervised_pulse_completed_facts_ok(result)
        )
        if praise and not semantic_success:
            result["status"] = "effect_reconciliation_required"
            result["effect_reconciliation_required"] = True
            result["reason"] = str(
                result.get("reason") or "praise_effect_requires_reconciliation"
            )
        else:
            result["effect_reconciliation_required"] = False
        result["flow_id"] = FLOW_ID
        result["scenario_id"] = SCENARIO_ID
        result["reset_id"] = reset_id
        result["candidate_commit"] = candidate_commit
        result["max_inputs"] = maximum
        result["production_registration"] = "REGISTERED"
        result["scheduler_enabled"] = False
        result["registration_snapshot"] = dict(registration_snapshot)
        result["dispatch_registration"] = dict(registration_snapshot)
        result["proof_topology"] = "continuous"
        result["initial_observation"] = initial_observation
        result["initial_frame_sha256"] = initial_observation["frame_sha256"]
        if session:
            result["scenario_record"] = _scenario_record(
                result,
                candidate_commit=candidate_commit,
                session=session,
            )
            trace = _write_read_only_causal_trace(
                runtime_session,
                flow_result=result,
                initial_observation=initial_observation,
                registration_snapshot=registration_snapshot,
            )
            result["causal_trace_count"] = 1
            result["causal_trace"] = trace
            outer_session.set_causal_trace(trace)
            outer_session.remember_control("nova_praise_route_status", result.get("status"))
            outer_session.remember_control(
                "target_history",
                [
                    str(row.get("label") or row.get("action_key") or "")
                    for row in outer_session.actions
                ],
            )
            outer_session.remember_control(
                "recovery_result",
                "verified_home"
                if result.get("status") == "completed"
                else result.get("reason"),
            )
            persisted = pnsctl._persist_nova_session_result(
                session,
                result,
                candidate_commit=candidate_commit,
            )
            result.update(persisted)
            _write_delivery_result(
                Path(session),
                result,
                lease=lease,
                maximum=maximum,
                candidate_commit=candidate_commit,
            )
        result_status = str(result.get("status") or "blocked")
        if semantic_success:
            terminal_status = "completed"
        elif int(result.get("praise_transport_calls") or 0) > 0:
            terminal_status = "unresolved"
        else:
            terminal_status = "blocked"
        return json.dumps(result, sort_keys=True, default=str)
    except BaseException:
        if result_status == "completed" or session:
            terminal_status = "unresolved"
        raise
    finally:
        pnsctl._finalize_nova_supervised_invocation_guard(
            terminal_status=terminal_status,
            result_status=result_status,
            session_directory=session or None,
            reset_id=reset_id,
        )


def _registration_evidence_valid(
    result: Mapping[str, Any], trace: object
) -> tuple[bool, dict[str, Any] | None]:
    if result.get("production_registration") != "REGISTERED":
        return False, None
    if (
        result.get("scheduler_enabled") is not False
        or not isinstance(trace, Mapping)
        or trace.get("scheduler_enabled") is not False
    ):
        return False, None
    aliases = (
        result.get("registration_snapshot"),
        result.get("dispatch_registration"),
        trace.get("registration_snapshot"),
        trace.get("dispatch_registration"),
    )
    if any(value is None for value in aliases):
        return False, None
    try:
        snapshots = [_validated_registration_snapshot(value) for value in aliases]
    except (_pnsctl().OperatorError, TypeError, ValueError, KeyError):
        return False, None
    first = snapshots[0]
    if any(snapshot != first for snapshot in snapshots[1:]):
        return False, None
    return True, first


def verify_nova_praise_supervised_one_free_pulse(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Nova delivery result is missing")
    session = Path(str(structure.get("session_directory") or ""))
    initial = result.get("initial_observation")
    trace = result.get("causal_trace")
    registration_ok, registration_snapshot = _registration_evidence_valid(
        result, trace
    )
    initial_ok = False
    if isinstance(initial, Mapping):
        digest = str(initial.get("frame_sha256") or "")
        frame_path = str(initial.get("frame_path") or "")
        try:
            retained = _pnsctl()._session_relative_path(
                session, frame_path, "initial_observation.frame_path"
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
    retained_transport = _retained_transport_count(session)
    action_key = str(result.get("action_key") or "")
    retained_praise = _retained_praise_count(session, action_key)
    before = result.get("attempts_before")
    after = result.get("attempts_after")
    cooldown = result.get("cooldown_seconds")
    from tasks.nova_praise import (
        NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS,
        NOVA_POLICY_COOLDOWN_SECONDS,
    )

    semantic_successor = bool(
        type(before) is int
        and type(after) is int
        and before > 0
        and after == before - 1
        and type(cooldown) is int
        and NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS
        <= cooldown
        <= NOVA_POLICY_COOLDOWN_SECONDS
        and result.get("journal_status") == "confirmed"
        and result.get("terminal_home_verified") is True
    )
    trace_ok = bool(
        result.get("proof_topology") == "continuous"
        and result.get("causal_trace_count") == 1
        and isinstance(trace, Mapping)
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("scheduler_enabled") is False
        and trace.get("proof_topology") == "continuous"
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("praise_transport_calls") == retained_praise
        and registration_ok
    )
    transport_ok = bool(
        retained_transport == result.get("input_count")
        and retained_transport == result.get("dispatch_count")
        and retained_praise == result.get("praise_transport_calls") == MAX_PRAISE
        and retained_transport <= int(result.get("max_inputs") or 0)
    )
    verified = bool(
        result.get("status") == "completed"
        and result.get("effect_reconciliation_required") is False
        and initial_ok
        and trace_ok
        and transport_ok
        and semantic_successor
        and registration_ok
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "initial_observation_verified": initial_ok,
        "transport_accounting_verified": transport_ok,
        "causal_trace_verified": trace_ok,
        "semantic_successor_verified": semantic_successor,
        "registration_verified": registration_ok,
        "registration_snapshot": registration_snapshot,
        "production_registration": (
            "REGISTERED" if registration_ok else result.get("production_registration")
        ),
        "scheduler_enabled": result.get("scheduler_enabled"),
    }


def recover_nova_praise_supervised_one_free_pulse(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    raise _pnsctl().OperatorError(
        "Nova supervised Praise has no generic recovery handler"
    )


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[RUNNER_ID] = run_nova_praise_supervised_one_free_pulse
    validators[VALIDATOR_ID] = verify_nova_praise_supervised_one_free_pulse
    handlers[RECOVERY_ID] = recover_nova_praise_supervised_one_free_pulse
