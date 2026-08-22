"""BlueStacks flow-delivery binding for one free Bioenhancer research."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION"
RUNNER_ID = "bioenhancer_free_research_bluestacks_runner"
VALIDATOR_ID = "bioenhancer_free_research_bluestacks_evidence"
RECOVERY_ID = "bioenhancer_free_research_bluestacks_recovery"
MAX_INPUTS = 8
MAX_FREE_RESEARCH_TRANSPORT_CALLS = 1


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _max_inputs(lease: Mapping[str, Any]) -> int:
    try:
        maximum = int(lease.get("max_inputs", MAX_INPUTS))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "Bioenhancer development-session max_inputs must be an integer"
        ) from exc
    if not 1 <= maximum <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Bioenhancer development-session max_inputs must be between 1 and {MAX_INPUTS}"
        )
    return maximum


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
            "Bioenhancer flow requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Bioenhancer initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Bioenhancer initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Bioenhancer initial observation hash or invocation binding is invalid"
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


def _free_research_transport_calls(session: Path) -> int:
    return sum(
        row.get("type") == "dispatch"
            and row.get("execute") is not False
            and str(row.get("action_key") or "").startswith("free-research-1x:")
        for row in _read_events(session)
    )


def _write_read_only_causal_trace(
    session: Path,
    *,
    flow_result: Mapping[str, Any],
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
            "inspect_current_home_frame",
            "research_lab_navigation",
            "current_frame_free_research_binding",
            "free_research_transport",
            "cooldown_successor",
            "terminal_home",
        ],
        "transport_count": _retained_transport_count(session),
        "free_research_transport_calls": _free_research_transport_calls(session),
        "event_count": len(events),
        "status": str(flow_result.get("status") or "unknown"),
        "effect_reconciliation_required": bool(
            flow_result.get("effect_reconciliation_required")
        ),
    }
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return trace


def _write_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
    maximum: int,
) -> None:
    session.mkdir(parents=True, exist_ok=True)
    free_calls = int(result.get("free_research_transport_calls") or 0)
    input_count = int(result.get("input_count") or 0)
    frames = sorted(
        path.relative_to(session).as_posix()
        for path in (session / "frames").glob("*.png")
        if path.is_file() and not path.is_symlink()
    ) if (session / "frames").is_dir() else []
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
                "action_class": "one_free_bioenhancer_research",
                "path": "home_to_research_lab_to_bioenhancer_to_home",
                "outcome": result.get("status"),
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "causal_trace_path": "causal-trace.json",
        "dispatch": free_calls > 0,
        "dispatch_count": input_count,
        "input_count": input_count,
        "max_inputs": maximum,
        "free_research_transport_calls": free_calls,
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "semantic_postcondition": result.get("semantic_postcondition"),
        "proof_topology": result.get("proof_topology"),
        "initial_observation": result.get("initial_observation"),
        "initial_frame_sha256": result.get("initial_frame_sha256"),
        "causal_trace_count": result.get("causal_trace_count"),
        "causal_trace": result.get("causal_trace"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
        "identical_retry_denied": bool(result.get("identical_retry_denied")),
        "reason": result.get("reason"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _result_payload(
    result: Mapping[str, Any],
    *,
    session_directory: Path | str,
    input_count: int,
    free_calls: int,
    maximum: int,
) -> dict[str, Any]:
    raw_status = str(result.get("status") or "blocked")
    postcondition = result.get("semantic_postcondition")
    return_home = result.get("return_home")
    cooldown_proven = (
        isinstance(postcondition, Mapping) and postcondition.get("proven") is True
    )
    terminal_home_verified = (
        isinstance(return_home, Mapping)
        and return_home.get("status") == "home_returned"
    ) or result.get("terminal_home_verified") is True
    semantic_success = (
        raw_status == "completed"
        and free_calls == 1
        and cooldown_proven
        and terminal_home_verified
    )
    if semantic_success:
        status = "completed"
    elif free_calls:
        status = "effect_reconciliation_required"
    else:
        status = "blocked"
    payload = dict(result)
    payload.update(
        {
            "status": status,
            "flow_id": FLOW_ID,
            "input_count": input_count,
            "max_inputs": maximum,
            "free_research_transport_calls": free_calls,
            "dispatch": free_calls > 0,
            "terminal_home_verified": terminal_home_verified,
            "effect_reconciliation_required": bool(free_calls and not semantic_success),
            "identical_retry_denied": bool(free_calls and not semantic_success),
            "session_directory": str(session_directory),
            "reason": str(
                result.get("reason")
                or (
                    "free_research_postcondition_verified"
                    if status == "completed"
                    else "bioenhancer_free_research_blocked"
                )
            ),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    )
    return payload


def run_bioenhancer_free_research(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    """Run the existing canary inside pnsctl's already-owned session."""

    del queue
    maximum = _max_inputs(lease)
    if not live:
        session_directory = str(lease.get("session_directory") or "")
        payload = _result_payload(
            {"status": "dry_run", "dispatch": False},
            session_directory=session_directory,
            input_count=0,
            free_calls=0,
            maximum=maximum,
        )
        payload["status"] = "dry_run"
        return json.dumps(payload, sort_keys=True, default=str)

    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
    outer_directory = Path(outer_session.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_session = outer_directory
    try:
        pnsctl = _pnsctl()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow=f"bioenhancer-free-research-{_stamp()}",
            execute=True,
        )
        runtime_session = runtime.session
        from scripts import bioenhancer_free_research_canary as route_module

        route_result = route_module.run(
            max_inputs=maximum,
            settle_seconds=float(lease.get("settle_seconds", 1.5)),
            session=outer_session,
            runtime=runtime,
            session_directory=runtime_session,
        )
        free_calls = _free_research_transport_calls(runtime_session)
        input_count = _retained_transport_count(runtime_session)
        if int(getattr(outer_session, "input_count", 0)) != input_count:
            raise pnsctl.OperatorError(
                "Bioenhancer session input count does not match retained transports"
            )
        if input_count > maximum:
            raise pnsctl.OperatorError(
                "Bioenhancer development-session exceeded its max_inputs ceiling"
            )
        if free_calls > MAX_FREE_RESEARCH_TRANSPORT_CALLS:
            raise pnsctl.OperatorError(
                "Bioenhancer development-session exceeded its one-research ceiling"
            )
        payload = _result_payload(
            route_result,
            session_directory=runtime_session,
            input_count=input_count,
            free_calls=free_calls,
            maximum=maximum,
        )
    except Exception as exc:
        free_calls = _free_research_transport_calls(runtime_session)
        input_count = _retained_transport_count(runtime_session)
        payload = _result_payload(
            {
                "status": "unresolved" if free_calls else "blocked",
                "reason": f"{type(exc).__name__}: {exc}",
            },
            session_directory=runtime_session,
            input_count=input_count,
            free_calls=free_calls,
            maximum=maximum,
        )
    source_path = outer_directory / "source.png"
    if source_path.is_file():
        retained_initial = runtime_session / "frames" / "0000-initial-observation.png"
        retained_initial.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, retained_initial)
        initial_observation["frame_path"] = "frames/0000-initial-observation.png"
    payload["proof_topology"] = "continuous"
    payload["initial_observation"] = initial_observation
    payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
    trace = _write_read_only_causal_trace(
        runtime_session,
        flow_result=payload,
        initial_observation=initial_observation,
    )
    payload["causal_trace_count"] = 1
    payload["causal_trace"] = trace
    outer_session.set_causal_trace(trace)
    _write_delivery_result(
        runtime_session,
        payload,
        lease=lease,
        maximum=maximum,
    )
    return json.dumps(payload, sort_keys=True, default=str)


def verify_bioenhancer_free_research(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Bioenhancer delivery result is missing")
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
    retained_free = _free_research_transport_calls(session)
    postcondition = result.get("semantic_postcondition")
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
        and trace.get("free_research_transport_calls") == retained_free
    )
    verified = (
        result.get("status") == "completed"
        and result.get("proof_topology") == "continuous"
        and initial_ok
        and trace_ok
        and retained_transport == result.get("input_count")
        and type(result.get("max_inputs")) is int
        and retained_transport <= result.get("max_inputs")
        and retained_free == result.get("free_research_transport_calls") == 1
        and isinstance(postcondition, Mapping)
        and postcondition.get("proven") is True
        and postcondition.get("timer_proven") is True
        and result.get("terminal_home_verified") is True
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
        "free_research_transport_calls": retained_free,
        "reason": None if verified else "Bioenhancer continuous route proof is incomplete",
    }


def recover_bioenhancer_free_research(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    return json.dumps(
        {
            "status": "blocked",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "reason": "Bioenhancer recovery is safe no-op; use a fresh canonical conduct session",
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
    runners[RUNNER_ID] = run_bioenhancer_free_research
    validators[VALIDATOR_ID] = verify_bioenhancer_free_research
    handlers[RECOVERY_ID] = recover_bioenhancer_free_research
