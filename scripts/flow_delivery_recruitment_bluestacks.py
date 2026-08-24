"""BlueStacks flow-delivery binding for Noah's Tavern continuous recruitment."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


FLOW_ID = "RECRUITMENT-BLUESTACKS-INTEGRATION"
RUNNER_ID = "recruitment_bluestacks_runner"
VALIDATOR_ID = "recruitment_bluestacks_evidence"
RECOVERY_ID = "recruitment_bluestacks_recovery"
MAX_INPUTS = 12
MAX_CONTINUATION_INPUTS = 4
MAX_RECRUITMENT_ACTIONS = 3
RECRUIT_TARGET_IDENTITY = "noahs-tavern-daily-free"


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _maximum(lease: Mapping[str, Any]) -> int:
    try:
        value = int(lease.get("max_inputs", MAX_INPUTS))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Recruitment development-session max_inputs must be an integer"
        ) from exc
    if value != MAX_INPUTS:
        raise _pnsctl().OperatorError(
            "Recruitment full pass requires exact 12-input cap; "
            "continuation uses the separate exact 4-input route"
        )
    return value


def _outer_session(lease: Mapping[str, Any]):
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{FLOW_ID}"
        or not callable(getattr(session, "run_action", None))
    ):
        raise _pnsctl().OperatorError(
            "Recruitment requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Recruitment initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Recruitment initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Recruitment initial observation hash or invocation binding is invalid"
        )
    return value.to_mapping()


def _read_events(session: Path) -> list[dict[str, Any]]:
    events = session / "events.jsonl"
    if not events.is_file() or events.is_symlink():
        return []
    rows: list[dict[str, Any]] = []
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _retained_transport_count(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch" and row.get("execute") is not False
        for row in _read_events(session)
    )


def _recruitment_transport_count(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch"
        and row.get("execute") is not False
        and row.get("target_identity") == RECRUIT_TARGET_IDENTITY
        for row in _read_events(session)
    )


def _write_read_only_causal_trace(
    session: Path,
    *,
    result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
    transport_count: int,
    recruitment_transport_count: int,
) -> dict[str, Any]:
    events = _read_events(session)
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "proof_topology": "continuous",
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "stages": [
            "typed_initial_observation",
            "canonical_home_atlas_binding",
            "noahs_tavern_navigation",
            "current_frame_tier_binding",
            "current_frame_free_control_binding",
            "recruit_result_successor",
            "free_attempt_cooldown_successor",
            "independent_tier_persistence",
            "canonical_home_terminal",
        ],
        "transport_count": transport_count,
        "recruitment_transport_count": recruitment_transport_count,
        "recruitment_action_count": int(result.get("recruitment_action_count") or 0),
        "event_count": len(events),
        "status": str(result.get("status") or "unknown"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
    }
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return trace


def _result_payload(
    route_result: Mapping[str, Any],
    *,
    session_directory: Path | str,
    input_count: int,
    recruitment_transport_count: int,
    maximum: int,
) -> dict[str, Any]:
    route_status = str(route_result.get("status") or "blocked")
    action_count = int(
        route_result.get("recruitment_dispatch_count")
        or route_result.get("actions_completed")
        or 0
    )
    terminal_home = bool(route_result.get("terminal_home_verified") is True)
    counts_match = action_count == recruitment_transport_count
    completed = bool(
        route_status == "completed"
        and terminal_home
        and counts_match
        and action_count <= MAX_RECRUITMENT_ACTIONS
    )
    reconciliation_required = bool(
        recruitment_transport_count and not completed
    )
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
            "flow_id": FLOW_ID,
            "session_directory": str(session_directory),
            "input_count": input_count,
            "max_inputs": maximum,
            "dispatch": input_count > 0,
            "recruitment_transport_count": recruitment_transport_count,
            "recruitment_action_count": action_count,
            "recruitment_dispatch_count": action_count,
            "terminal_home_verified": terminal_home,
            "proof_topology": "continuous",
            "effect_reconciliation_required": reconciliation_required,
            "identical_retry_denied": reconciliation_required,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    )
    if not counts_match:
        payload["reason"] = "recruitment transport/action counts do not match"
    return payload


def _write_delivery_result(
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
            for path in (session / "frames").glob("*.png")
            if path.is_file() and not path.is_symlink()
        )
        if (session / "frames").is_dir()
        else []
    )
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
                "action_class": "ordinary_free_recruitment",
                "path": "home_to_noahs_tavern_tier_free_recruit_to_home",
                "outcome": result.get("status"),
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


def _identity(lease: Mapping[str, Any]):
    from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID
    from tasks.scheduler_task_result import SchedulerIdentity

    return SchedulerIdentity(
        str(lease.get("account_id") or "local-bluestacks-account"),
        str(lease.get("server_id") or "local-bluestacks-server"),
        str(lease.get("reset_id") or "local-bluestacks-reset"),
        MAINTENANCE_TASK_ID,
    )


def run_recruitment(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    del queue
    maximum = _maximum(lease)
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "dispatch": False,
                "input_count": 0,
                "max_inputs": maximum,
                "recruitment_transport_count": 0,
                "recruitment_action_count": 0,
                "proof_topology": "continuous",
                "causal_trace_count": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
    outer_directory = Path(outer_session.session_directory)
    runtime_directory = outer_directory / "runtime"
    runtime: LocalBlueStacksRuntime | None = None
    try:
        pnsctl = _pnsctl()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=runtime_directory,
            workflow=f"recruitment-{_stamp()}",
            execute=True,
        )
        from scripts import noahs_tavern_recruit_bluestacks as route_module

        route_args = SimpleNamespace(
            adb=pnsctl.BLUESTACKS_ADB,
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=runtime_directory,
            max_inputs=maximum,
            settle_seconds=float(lease.get("settle_seconds", 1.0)),
            state_session=None,
        )
        route_result = json.loads(
            route_module.run_noahs_tavern_unified_recruitment(
                route_args,
                _identity(lease),
            )
        )
        child_text = str(route_result.get("session_directory") or runtime.session)
        child = Path(child_text)
        input_count = _retained_transport_count(child)
        recruitment_count = _recruitment_transport_count(child)
        route_count = int(route_result.get("input_count") or 0)
        source_path = outer_directory / "source.png"
        if source_path.is_file():
            retained_initial = child / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            retained_initial.write_bytes(source_path.read_bytes())
            initial_observation = dict(initial_observation)
            initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        if route_count != input_count:
            raise pnsctl.OperatorError(
                "Recruitment route count does not match retained native transports"
            )
        if input_count > maximum:
            raise pnsctl.OperatorError("Recruitment exceeded max_inputs")
        if recruitment_count > MAX_RECRUITMENT_ACTIONS:
            raise pnsctl.OperatorError(
                "Recruitment exceeded the full-pass recruit-action ceiling"
            )
        payload = _result_payload(
            route_result,
            session_directory=child,
            input_count=input_count,
            recruitment_transport_count=recruitment_count,
            maximum=maximum,
        )
    except Exception as exc:
        child = runtime.session if runtime is not None else runtime_directory
        input_count = _retained_transport_count(child)
        recruitment_count = _recruitment_transport_count(child)
        payload = _result_payload(
            {
                "status": "unresolved" if recruitment_count else "blocked",
                "reason": f"{type(exc).__name__}: {exc}",
                "terminal_home_verified": False,
            },
            session_directory=child,
            input_count=input_count,
            recruitment_transport_count=recruitment_count,
            maximum=maximum,
        )

    trace = _write_read_only_causal_trace(
        child,
        result=payload,
        initial_observation=initial_observation,
        transport_count=input_count,
        recruitment_transport_count=recruitment_count,
    )
    payload["initial_observation"] = initial_observation
    payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
    payload["causal_trace_count"] = 1
    payload["causal_trace"] = trace
    if hasattr(outer_session, "adopt_retained_transport_count"):
        outer_session.adopt_retained_transport_count(
            input_count,
            source="runtime_session/events.jsonl",
        )
        outer_session.remember_control(
            "recruitment_transport_count", recruitment_count
        )
        outer_session.remember_control(
            "recruitment_action_count", payload["recruitment_action_count"]
        )
    elif int(getattr(outer_session, "input_count", 0)) != input_count:
        raise _pnsctl().OperatorError(
            "Recruitment input count does not match retained transports"
        )
    outer_session.set_causal_trace(trace)
    _write_delivery_result(
        child,
        payload,
        lease=lease,
        initial_observation=initial_observation,
        causal_trace=trace,
    )
    return json.dumps(payload, sort_keys=True, default=str)


def verify_recruitment(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Recruitment delivery result is missing")
    session = Path(str(structure.get("session_directory") or ""))
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
    retained_transport = _retained_transport_count(session)
    retained_recruitment = _recruitment_transport_count(session)
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
        and trace.get("proof_topology") == "continuous"
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("recruitment_transport_count") == retained_recruitment
        and trace.get("recruitment_action_count")
        == result.get("recruitment_action_count")
    )
    verified = bool(
        result.get("status") == "completed"
        and result.get("proof_topology") == "continuous"
        and initial_ok
        and trace_ok
        and retained_transport == result.get("input_count")
        and type(result.get("max_inputs")) is int
        and retained_transport <= result.get("max_inputs")
        and retained_recruitment == result.get("recruitment_transport_count")
        and retained_recruitment == result.get("recruitment_action_count")
        and retained_recruitment <= MAX_RECRUITMENT_ACTIONS
        and result.get("terminal_home_verified") is True
        and result.get("effect_reconciliation_required") is False
        and result.get("identical_retry_denied") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
        "initial_observation_verified": initial_ok,
        "causal_trace_verified": trace_ok,
        "retained_transport_count": retained_transport,
        "recruitment_transport_count": retained_recruitment,
        "reason": None if verified else "Recruitment continuous route proof is incomplete",
    }


def recover_recruitment(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    return json.dumps(
        {
            "status": "blocked",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "reason": "Recruitment recovery is a safe no-op; use a fresh conduct session",
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[RUNNER_ID] = run_recruitment
    validators[VALIDATOR_ID] = verify_recruitment
    handlers[RECOVERY_ID] = recover_recruitment
