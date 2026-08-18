"""BlueStacks flow-delivery binding for all current free Supply Depot attempts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
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
    session = lease.get("development_session")
    if session is None or not callable(getattr(session, "run_action", None)):
        raise _pnsctl().OperatorError(
            "Supply Depot requires the pnsctl-owned DevelopmentSession"
        )
    return session


def _hold_calls(session: Path) -> int:
    events = session / "events.jsonl"
    if not events.is_file():
        return 0
    count = 0
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            isinstance(row, Mapping)
            and row.get("type") == "dispatch"
            and row.get("execute") is not False
            and str(row.get("action_key") or "").startswith(
                "supply-depot-free-hold:"
            )
        ):
            count += 1
    return count


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
    return {
        **dict(result),
        "status": "completed"
        if completed
        else "unresolved"
        if hold_calls
        else "blocked",
        "flow_id": FLOW_ID,
        "session_directory": str(session_directory),
        "input_count": input_count,
        "max_inputs": maximum,
        "hold_transport_calls": hold_calls,
        "dispatch": input_count > 0,
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
        "frames": frames,
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
        input_count = int(getattr(outer, "input_count", 0))
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
        input_count = int(getattr(outer, "input_count", 0))
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
    verified = bool(
        result.get("status") == "completed"
        and result.get("free_attempts_after") == 0
        and result.get("terminal_home_verified") is True
        and int(result.get("hold_transport_calls") or 0) <= 1
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
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
