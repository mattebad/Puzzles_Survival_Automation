"""Fixed development-session binding for the supervised Nova Praise pulse."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any, Mapping


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
        "candidate_commit": candidate_commit,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
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
        if navigation + praise > maximum:
            raise pnsctl.OperatorError(
                "Nova development-session exceeded its max_inputs ceiling"
            )
        if praise > MAX_PRAISE:
            raise pnsctl.OperatorError(
                "Nova development-session exceeded its one-Praise ceiling"
            )
        result["flow_id"] = FLOW_ID
        result["scenario_id"] = SCENARIO_ID
        result["reset_id"] = reset_id
        result["candidate_commit"] = candidate_commit
        result["max_inputs"] = maximum
        result["production_registration"] = "NOT_REGISTERED"
        result["scheduler_enabled"] = False
        if session:
            result["scenario_record"] = _scenario_record(
                result,
                candidate_commit=candidate_commit,
                session=session,
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
        if (
            result.get("status") == "completed"
            and result.get("praise_transport_calls") == MAX_PRAISE
            and pnsctl._supervised_pulse_completed_facts_ok(result)
        ):
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


def verify_nova_praise_supervised_one_free_pulse(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    del queue, lease
    result = structure.get("result")
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Nova delivery result is missing")
    return {
        "status": "verified" if result.get("status") == "completed" else "evidence_required",
        "flow_id": FLOW_ID,
        "session_directory": structure.get("session_directory"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
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
