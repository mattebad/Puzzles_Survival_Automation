"""BlueStacks flow-delivery binding for one free Bioenhancer research."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
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
    session = lease.get("development_session")
    if session is None or not callable(getattr(session, "run_action", None)):
        raise _pnsctl().OperatorError(
            "Bioenhancer flow requires the pnsctl-owned DevelopmentSession"
        )
    return session


def _free_research_transport_calls(session: Path) -> int:
    events = session / "events.jsonl"
    if not events.is_file():
        return 0
    calls = 0
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            isinstance(row, dict)
            and row.get("type") == "dispatch"
            and row.get("execute") is not False
            and str(row.get("action_key") or "").startswith("free-research-1x:")
        ):
            calls += 1
    return calls


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
        "dispatch": free_calls > 0,
        "dispatch_count": input_count,
        "input_count": input_count,
        "max_inputs": maximum,
        "free_research_transport_calls": free_calls,
        "terminal_home_verified": result.get("terminal_home_verified") is True,
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
    if raw_status == "completed" and free_calls == 1:
        status = "completed"
    elif free_calls:
        status = "unresolved"
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
        input_count = int(getattr(outer_session, "input_count", 0))
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
        input_count = int(getattr(outer_session, "input_count", 0))
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
    verified = (
        result.get("status") == "completed"
        and result.get("free_research_transport_calls") == 1
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
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
