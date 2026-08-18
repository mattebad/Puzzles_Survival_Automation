"""BlueStacks flow-delivery binding for one Daily Row reward claim."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
RUNNER_ID = "daily_row_claim_bluestacks_runner"
VALIDATOR_ID = "daily_row_claim_bluestacks_evidence"
RECOVERY_ID = "daily_row_claim_bluestacks_recovery"
MAX_INPUTS = 4
MAX_DAILY_CLAIM_TRANSPORT_CALLS = 1


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
            "Daily Row development-session max_inputs must be an integer"
        ) from exc
    if not 1 <= maximum <= MAX_INPUTS:
        raise _pnsctl().OperatorError(
            f"Daily Row development-session max_inputs must be between 1 and {MAX_INPUTS}"
        )
    return maximum


def _outer_session(lease: Mapping[str, Any]) -> Any:
    session = lease.get("development_session")
    if session is None or not callable(getattr(session, "run_action", None)):
        raise _pnsctl().OperatorError(
            "Daily Row flow requires the pnsctl-owned DevelopmentSession"
        )
    return session


def _daily_claim_transport_calls(session: Path) -> int:
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
            and row.get("action_key") == "daily-claim:aggregate"
        ):
            calls += 1
    return calls


def _game_day_id(result: Mapping[str, Any] | None) -> str | None:
    if not isinstance(result, Mapping):
        return None
    direct = result.get("game_day_id")
    if isinstance(direct, str) and direct.strip():
        return direct
    recognitions = result.get("recognitions")
    if not isinstance(recognitions, Mapping):
        return None
    for name in ("daily_terminal", "source"):
        recognition = recognitions.get(name)
        if not isinstance(recognition, Mapping):
            continue
        visual = recognition.get("visual_evidence")
        if not isinstance(visual, Mapping):
            continue
        value = visual.get("game_day_id")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _terminal_home_verified(result: Mapping[str, Any] | None) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "completed":
        return False
    home = result.get("home")
    return isinstance(home, Mapping) and home.get("verified") is True


def _result_payload(
    *,
    reconnaissance: Mapping[str, Any] | None,
    canary: Mapping[str, Any] | None,
    session_directory: Path | str,
    input_count: int,
    claim_calls: int,
    maximum: int,
) -> dict[str, Any]:
    recon_status = (
        str(reconnaissance.get("status") or "blocked")
        if isinstance(reconnaissance, Mapping)
        else "blocked"
    )
    canary_status = (
        str(canary.get("status") or "blocked")
        if isinstance(canary, Mapping)
        else "blocked"
    )
    home_verified = _terminal_home_verified(canary)
    if (
        recon_status == "observed"
        and canary_status == "completed"
        and claim_calls == MAX_DAILY_CLAIM_TRANSPORT_CALLS
        and home_verified
    ):
        status = "completed"
        reason = "daily_claim_and_template_home_postconditions_verified"
    elif claim_calls:
        status = "unresolved"
        reason = str(
            (canary or {}).get("reason") if isinstance(canary, Mapping) else None
            or "daily_claim_postcondition_unresolved"
        )
    else:
        status = "blocked"
        reason = str(
            (canary or {}).get("reason")
            if isinstance(canary, Mapping)
            else (reconnaissance or {}).get("reason")
            if isinstance(reconnaissance, Mapping)
            else None
            or "daily_claim_not_authorized"
        )
    payload: dict[str, Any] = {
        "status": status,
        "flow_id": FLOW_ID,
        "input_count": input_count,
        "max_inputs": maximum,
        "claim_transport_calls": claim_calls,
        "dispatch": claim_calls > 0,
        "terminal_home_verified": home_verified,
        "game_day_id": _game_day_id(canary) or _game_day_id(reconnaissance),
        "reconnaissance": dict(reconnaissance) if reconnaissance is not None else None,
        "canary": dict(canary) if canary is not None else None,
        "session_directory": str(session_directory),
        "reason": reason,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    return payload


def _write_delivery_result(
    session: Path,
    result: Mapping[str, Any],
    *,
    lease: Mapping[str, Any],
    maximum: int,
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
                "action_class": "ordinary_reward_claim",
                "path": "home_to_daily_row_claim_to_home",
                "outcome": result.get("status"),
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "dispatch": bool(result.get("dispatch")),
        "dispatch_count": int(result.get("input_count") or 0),
        "input_count": int(result.get("input_count") or 0),
        "max_inputs": maximum,
        "claim_transport_calls": int(result.get("claim_transport_calls") or 0),
        "terminal_home_verified": result.get("terminal_home_verified") is True,
        "game_day_id": result.get("game_day_id"),
        "reconnaissance": result.get("reconnaissance"),
        "canary": result.get("canary"),
        "reason": result.get("reason"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run_daily_row_claim(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    live: bool = True,
) -> str:
    """Run Daily reconnaissance and claim inside pnsctl's owned session."""

    del queue
    maximum = _max_inputs(lease)
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

    outer_session = _outer_session(lease)
    outer_directory = Path(outer_session.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_session = outer_directory
    reconnaissance: Mapping[str, Any] | None = None
    canary: Mapping[str, Any] | None = None
    try:
        pnsctl = _pnsctl()
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow=f"daily-row-claim-{_stamp()}",
            execute=True,
        )
        runtime_session = runtime.session
        from scripts import daily_row_claim_bluestacks as route_module

        reconnaissance = route_module.run_daily_row_reconnaissance(runtime, outer_session)
        input_count = int(getattr(outer_session, "input_count", 0))
        if input_count > maximum:
            raise pnsctl.OperatorError(
                "Daily Row development-session exceeded its max_inputs ceiling"
            )
        if reconnaissance.get("status") != "observed":
            payload = _result_payload(
                reconnaissance=reconnaissance,
                canary=None,
                session_directory=runtime_session,
                input_count=input_count,
                claim_calls=0,
                maximum=maximum,
            )
        else:
            canary = route_module.run_daily_row_claim_canary(
                runtime,
                outer_session,
                game_day_id=_game_day_id(reconnaissance),
            )
            input_count = int(getattr(outer_session, "input_count", 0))
            claim_calls = _daily_claim_transport_calls(runtime_session)
            if input_count > maximum:
                raise pnsctl.OperatorError(
                    "Daily Row development-session exceeded its max_inputs ceiling"
                )
            if claim_calls > MAX_DAILY_CLAIM_TRANSPORT_CALLS:
                raise pnsctl.OperatorError(
                    "Daily Row development-session exceeded its one-Claim ceiling"
                )
            payload = _result_payload(
                reconnaissance=reconnaissance,
                canary=canary,
                session_directory=runtime_session,
                input_count=input_count,
                claim_calls=claim_calls,
                maximum=maximum,
            )
    except Exception as exc:
        input_count = int(getattr(outer_session, "input_count", 0))
        claim_calls = _daily_claim_transport_calls(runtime_session)
        payload = _result_payload(
            reconnaissance=reconnaissance,
            canary=canary,
            session_directory=runtime_session,
            input_count=input_count,
            claim_calls=claim_calls,
            maximum=maximum,
        )
        payload["reason"] = f"{type(exc).__name__}: {exc}"
        if claim_calls:
            payload["status"] = "unresolved"
        else:
            payload["status"] = "blocked"
    _write_delivery_result(
        runtime_session,
        payload,
        lease=lease,
        maximum=maximum,
    )
    return json.dumps(payload, sort_keys=True, default=str)


def verify_daily_row_claim(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Daily Row delivery result is missing")
    canary = result.get("canary")
    verified = (
        result.get("status") == "completed"
        and result.get("claim_transport_calls") == MAX_DAILY_CLAIM_TRANSPORT_CALLS
        and _terminal_home_verified(canary)
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def recover_daily_row_claim(
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> str:
    del queue, lease
    return json.dumps(
        {
            "status": "blocked",
            "flow_id": FLOW_ID,
            "dispatch": False,
            "reason": "Daily Row recovery is safe no-op; use a fresh canonical conduct session",
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
    runners[RUNNER_ID] = run_daily_row_claim
    validators[VALIDATOR_ID] = verify_daily_row_claim
    handlers[RECOVERY_ID] = recover_daily_row_claim
