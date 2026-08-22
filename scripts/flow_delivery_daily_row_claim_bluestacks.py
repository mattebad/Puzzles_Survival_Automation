"""BlueStacks flow-delivery binding for one Daily Row reward claim."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
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
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or str(session.owner) != f"pnsctl-development-session:{FLOW_ID}"
        or not callable(getattr(session, "run_action", None))
    ):
        raise _pnsctl().OperatorError(
            "Daily Row flow requires the active pnsctl-owned DevelopmentSession"
        )
    return session


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Daily Row initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Daily Row initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        len(digest) != 64
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Daily Row initial observation hash or invocation binding is invalid"
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


def _write_read_only_causal_trace(
    session: Path,
    *,
    flow_result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
) -> dict[str, Any]:
    events = _read_events(session)
    transport_count = sum(
        row.get("type") == "dispatch" and row.get("execute") is not False
        for row in events
    )
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "stages": [
            "observation",
            "claim_intent",
            "row_binding",
            "transport",
            "points_control_successor",
            "terminal_home",
        ],
        "proof_topology": "continuous",
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "transport_count": transport_count,
        "claim_transport_calls": int(flow_result.get("claim_transport_calls") or 0),
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


def _daily_claim_transport_calls(session: Path) -> int:
    calls = 0
    for row in _read_events(session):
        if (
            row.get("type") == "dispatch"
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
        status = "effect_reconciliation_required"
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
        "proof_topology": "continuous",
        "causal_trace_count": 1,
        "effect_reconciliation_required": bool(
            claim_calls and status != "completed"
        ),
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
        "proof_topology": str(result.get("proof_topology") or "continuous"),
        "initial_observation": result.get("initial_observation"),
        "initial_frame_sha256": str(result.get("initial_frame_sha256") or ""),
        "causal_trace_count": int(result.get("causal_trace_count") or 1),
        "causal_trace": result.get("causal_trace"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
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
                "proof_topology": "composite",
                "causal_trace_count": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )

    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
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
        source_path = outer_directory / "source.png"
        if source_path.is_file():
            retained_initial = runtime_session / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, retained_initial)
            initial_observation["frame_path"] = "frames/0000-initial-observation.png"
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
        payload["initial_observation"] = initial_observation
        payload["initial_frame_sha256"] = initial_observation["frame_sha256"]
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
            payload["status"] = "effect_reconciliation_required"
            payload["effect_reconciliation_required"] = True
        else:
            payload["status"] = "blocked"
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
    outer_session.remember_control("daily_claim_route_status", payload.get("status"))
    outer_session.remember_control(
        "target_history",
        [str(row.get("label") or row.get("action_key") or "") for row in outer_session.actions],
    )
    outer_session.remember_control(
        "recovery_result",
        payload.get("reason") if payload.get("status") != "completed" else "verified_home",
    )
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
    session = Path(str(structure.get("session_directory") or ""))
    initial = result.get("initial_observation")
    trace = result.get("causal_trace")
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
    claim = canary.get("claim") if isinstance(canary, Mapping) else None
    points_before = claim.get("points_before") if isinstance(claim, Mapping) else None
    points_after = claim.get("points_after") if isinstance(claim, Mapping) else None
    recognitions = (
        canary.get("recognitions") if isinstance(canary, Mapping) else None
    )
    control_successor = False
    if isinstance(recognitions, Mapping):
        for recognition in recognitions.values():
            visual = (
                recognition.get("visual_evidence")
                if isinstance(recognition, Mapping)
                else None
            )
            if (
                isinstance(visual, Mapping)
                and visual.get("selected_daily") is True
                and visual.get("available_ordinary_claim_controls") == 0
                and visual.get("points") == points_after
            ):
                control_successor = True
                break
    semantic_successor = bool(
        type(points_before) is int
        and type(points_after) is int
        and points_after > points_before
        and control_successor
    )
    retained_events = _read_events(session)
    retained_transport_count = sum(
        row.get("type") == "dispatch" and row.get("execute") is not False
        for row in retained_events
    )
    retained_claim_calls = sum(
        row.get("type") == "dispatch"
        and row.get("execute") is not False
        and row.get("action_key") == "daily-claim:aggregate"
        for row in retained_events
    )
    transport_ok = bool(
        retained_transport_count == result.get("input_count")
        and retained_claim_calls == MAX_DAILY_CLAIM_TRANSPORT_CALLS
        and result.get("claim_transport_calls") == retained_claim_calls
    )
    trace_ok = bool(
        result.get("causal_trace_count") == 1
        and isinstance(trace, Mapping)
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("proof_topology") == "continuous"
        and trace.get("flow_id") == FLOW_ID
        and trace.get("initial_frame_sha256")
        == str(result.get("initial_frame_sha256") or "")
        and trace.get("claim_transport_calls")
        == retained_claim_calls
        and trace.get("transport_count") == retained_transport_count
    )
    verified = (
        result.get("status") == "completed"
        and result.get("claim_transport_calls") == MAX_DAILY_CLAIM_TRANSPORT_CALLS
        and result.get("proof_topology") == "continuous"
        and result.get("effect_reconciliation_required") is False
        and initial_ok
        and trace_ok
        and transport_ok
        and semantic_successor
        and _terminal_home_verified(canary)
        and result.get("production_registration") == "NOT_REGISTERED"
        and result.get("scheduler_enabled") is False
    )
    return {
        "status": "verified" if verified else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "proof_topology": result.get("proof_topology"),
        "initial_observation_verified": initial_ok,
        "causal_trace_verified": trace_ok,
        "transport_accounting_verified": transport_ok,
        "semantic_successor_verified": semantic_successor,
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
