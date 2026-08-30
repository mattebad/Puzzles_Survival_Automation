"""BlueStacks flow-delivery binding for all current free Supply Depot attempts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


FLOW_ID = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
RUNNER_ID = "supply_depot_bluestacks_runner"
VALIDATOR_ID = "supply_depot_bluestacks_evidence"
RECOVERY_ID = "supply_depot_bluestacks_recovery"
MAX_INPUTS = 10
MAX_HOLD_TRANSPORT_CALLS = 1


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
            "Supply Depot max_inputs must be an integer"
        ) from exc
    if not 1 <= value <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Supply Depot max_inputs must be between 1 and {MAX_INPUTS}"
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
            "Supply Depot requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Supply Depot initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Supply Depot initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Supply Depot initial observation hash or invocation binding is invalid"
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


def _hold_calls(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch"
            and row.get("execute") is not False
            and str(row.get("action_key") or "").startswith(
                "supply-depot-free-hold:"
            )
        for row in _read_events(session)
    )


def _write_read_only_causal_trace(
    session: Path,
    *,
    result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
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
            "inspect_current_frame",
            "supply_depot_navigation",
            "current_frame_free_target_binding",
            "bounded_free_hold",
            "free_disappeared_successor",
            "terminal_home",
        ],
        "transport_count": _retained_transport_count(session),
        "hold_transport_calls": _hold_calls(session),
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


def _payload(
    result: Mapping[str, Any],
    *,
    session_directory: Path | str,
    input_count: int,
    hold_calls: int,
    maximum: int,
) -> dict[str, Any]:
    completed = bool(
        result.get("status") == "completed"
        and result.get("terminal_home_verified") is True
        and result.get("free_attempts_after") == 0
        and hold_calls <= MAX_HOLD_TRANSPORT_CALLS
    )
    reconciliation_required = bool(hold_calls and not completed)
    return {
        **dict(result),
        "status": "completed"
        if completed
        else "effect_reconciliation_required"
        if reconciliation_required
        else "blocked",
        "flow_id": FLOW_ID,
        "session_directory": str(session_directory),
        "input_count": input_count,
        "max_inputs": maximum,
        "hold_transport_calls": hold_calls,
        "dispatch": input_count > 0,
        "effect_reconciliation_required": reconciliation_required,
        "identical_retry_denied": reconciliation_required,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def _write_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
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
                "action_class": "ordinary_free_collection",
                "path": "home_to_supply_depot_free_collection_to_home",
                "outcome": result.get("status"),
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "causal_trace_path": "causal-trace.json",
        **dict(result),
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run_supply_depot(
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
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    outer = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer)
    outer_directory = Path(outer.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_directory = outer_directory
    try:
        pnsctl = _pnsctl()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow=f"supply-depot-{_stamp()}",
            execute=True,
        )
        runtime_directory = runtime.session
        from scripts import supply_depot_free_canary

        result = supply_depot_free_canary.run(
            session=outer,
            runtime=runtime,
            session_directory=runtime_directory,
            settle_seconds=float(lease.get("settle_seconds", 1.5)),
        )
        hold_calls = _hold_calls(runtime_directory)
        input_count = _retained_transport_count(runtime_directory)
        if int(getattr(outer, "input_count", 0)) != input_count:
            raise pnsctl.OperatorError(
                "Supply Depot session input count does not match retained transports"
            )
        if input_count > maximum:
            raise pnsctl.OperatorError("Supply Depot exceeded max_inputs")
        if hold_calls > MAX_HOLD_TRANSPORT_CALLS:
            raise pnsctl.OperatorError("Supply Depot exceeded one hold")
        payload = _payload(
            result,
            session_directory=runtime_directory,
            input_count=input_count,
            hold_calls=hold_calls,
            maximum=maximum,
        )
    except Exception as exc:
        hold_calls = _hold_calls(runtime_directory)
        input_count = _retained_transport_count(runtime_directory)
        payload = _payload(
            {
                "status": "unresolved" if hold_calls else "blocked",
                "reason": f"{type(exc).__name__}: {exc}",
                "terminal_home_verified": False,
                "free_attempts_after": None,
            },
            session_directory=runtime_directory,
            input_count=input_count,
            hold_calls=hold_calls,
            maximum=maximum,
        )
    source_path = outer_directory / "source.png"
    if source_path.is_file():
        retained_initial = runtime_directory / "frames" / "0000-initial-observation.png"
        retained_initial.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, retained_initial)
        initial_observation["frame_path"] = "frames/0000-initial-observation.png"
    payload["proof_topology"] = "continuous"
    payload["initial_observation"] = initial_observation
    payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
    trace = _write_read_only_causal_trace(
        runtime_directory,
        result=payload,
        initial_observation=initial_observation,
    )
    payload["causal_trace_count"] = 1
    payload["causal_trace"] = trace
    outer.set_causal_trace(trace)
    _write_delivery_result(runtime_directory, payload, lease=lease)
    return json.dumps(payload, sort_keys=True, default=str)


def verify_supply_depot(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Supply Depot delivery result is missing")
    session = Path(str(structure.get("session_directory") or ""))
    initial = result.get("initial_observation")
    trace = result.get("causal_trace")
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
    retained_holds = _hold_calls(session)
    trace_file_ok = False
    trace_path = session / str(result.get("causal_trace_path") or "")
    try:
        trace_path.resolve().relative_to(session.resolve())
        trace_file_ok = (
            trace_path.is_file()
            and not trace_path.is_symlink()
            and json.loads(trace_path.read_text(encoding="utf-8")) == trace
        )
    except (OSError, ValueError, json.JSONDecodeError):
        trace_file_ok = False
    trace_ok = (
        isinstance(trace, Mapping)
        and trace_file_ok
        and result.get("causal_trace_count") == 1
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("proof_topology") == "continuous"
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == retained_transport
        and trace.get("hold_transport_calls") == retained_holds
    )
    verified = bool(
        result.get("status") == "completed"
        and result.get("proof_topology") == "continuous"
        and initial_ok
        and trace_ok
        and retained_transport == result.get("input_count")
        and type(result.get("max_inputs")) is int
        and retained_transport <= result.get("max_inputs")
        and result.get("free_attempts_after") == 0
        and result.get("terminal_home_verified") is True
        and retained_holds == result.get("hold_transport_calls")
        and retained_holds <= MAX_HOLD_TRANSPORT_CALLS
        and result.get("effect_reconciliation_required") is False
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
        "hold_transport_calls": retained_holds,
        "reason": None if verified else "Supply Depot continuous route proof is incomplete",
    }


def recover_supply_depot(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    return json.dumps(
        {
            "status": "blocked",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "reason": "safe no-op recovery; use a fresh recognized conduct session",
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
    runners[RUNNER_ID] = run_supply_depot
    validators[VALIDATOR_ID] = verify_supply_depot
    handlers[RECOVERY_ID] = recover_supply_depot
