#!/usr/bin/env python3
"""Fail-closed Cursor IDE-native Task routing for an active PnS delivery lease.

preToolUse(Task) is the authorization gate. subagentStart is audit-only and never the
enforcement boundary that prevents child creation.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flow_delivery_routing_policy as routing_policy

LOCAL_ROOT = ROOT / ".local-orchestrator"
LEASE = LOCAL_ROOT / "flow-delivery-lease.json"
WRITABLE_MARKER = LOCAL_ROOT / "writable-subagent.json"
ROUTING_EVENTS = LOCAL_ROOT / "model-routing-events.jsonl"
AUTHORIZATION_EVENTS = LOCAL_ROOT / "task-authorization-events.jsonl"
STATE_LOCK = LOCAL_ROOT / "subagent-guard.lock"
HOOK_CANARY_DIR = LOCAL_ROOT / "hook-canary"
AUDIT_ONLY_FLAG = HOOK_CANARY_DIR / "AUDIT_ONLY"
CAPTURED_PAYLOAD_PATH = HOOK_CANARY_DIR / "latest-pretooluse-task-payload.json"
BUILTIN_DENY_DEFAULT = {
    "generalPurpose",
    "explore",
    "shell",
    "best-of-n-runner",
    "ci-investigator",
    "cursor-guide",
    "bugbot",
    "security-review",
}


class GuardError(RuntimeError):
    """Raised when routing state cannot be bound safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def emit(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError(f"invalid local routing state: {path.name}") from exc
    if not isinstance(payload, dict):
        raise GuardError(f"invalid local routing object: {path.name}")
    return payload


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@contextmanager
def state_lock(timeout_seconds: float = 2.0) -> Iterator[None]:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(STATE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise GuardError("subagent routing state lock is unavailable")
            time.sleep(0.025)
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        STATE_LOCK.unlink(missing_ok=True)


def delivery_lease_active() -> bool:
    lease = _read_object(LEASE)
    return bool(lease and lease.get("workflow") == "pns-flow-delivery")


def audit_only_mode() -> bool:
    return AUDIT_ONLY_FLAG.exists() or os.environ.get("PNS_PRETOOLUSE_AUDIT_ONLY") == "1"


def _load_policy() -> dict[str, Any]:
    try:
        return routing_policy.load_subagent_routing_policy()
    except routing_policy.RoutingPolicyError as exc:
        raise GuardError(str(exc)) from exc


def _policy_digest(policy: Mapping[str, Any]) -> str:
    return routing_policy.routing_policy_digest(policy)


def _require_active_lease() -> dict[str, Any]:
    lease = _read_object(LEASE)
    if not lease or lease.get("workflow") != "pns-flow-delivery":
        raise GuardError("active PnS development lease is unavailable")
    for field in ("owner", "process_or_session_identity", "active_flow", "active_stage"):
        if not isinstance(lease.get(field), str) or not lease[field].strip():
            raise GuardError(f"active development lease does not bind {field}")
    return lease


def _bind_parent(lease: dict[str, Any], parent: str | None) -> str | None:
    if parent is None:
        return None
    if not isinstance(parent, str) or not parent.strip():
        raise GuardError("native subagent event has an invalid parent conversation identity")
    bound = lease.get("bound_parent_conversation_id")
    if bound is None:
        lease["bound_parent_conversation_id"] = parent
        _atomic_write(LEASE, lease)
    elif bound != parent:
        raise GuardError("native subagent belongs to another parent conversation")
    return parent


def _append_jsonl(path: Path, event: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _event_digest(event: Mapping[str, Any]) -> str:
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parent_from_payload(payload: Mapping[str, object]) -> str | None:
    for key in ("conversation_id", "parent_conversation_id"):
        value = payload.get(key)
        if value is not None:
            return value if isinstance(value, str) else ""
    return None


def _tool_input(payload: Mapping[str, object]) -> dict[str, Any]:
    raw = payload.get("tool_input")
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GuardError("Task tool_input is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise GuardError("Task tool_input JSON must be an object")
        return parsed
    if isinstance(raw, dict):
        return raw
    raise GuardError("Task tool_input has an unsupported type")


def _first_string(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    seen: list[str] = []
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise GuardError(f"Task field {key} is invalid")
        seen.append(value.strip())
    if not seen:
        return None
    if len(set(seen)) > 1:
        raise GuardError("conflicting Task routing fields")
    return seen[0]


def extract_task_routing(payload: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GuardError("invalid preToolUse payload")
    tool_name = payload.get("tool_name")
    if tool_name != "Task":
        raise GuardError("preToolUse Task handler received a non-Task tool")
    tool_input = _tool_input(payload)
    agent = _first_string(
        tool_input,
        (
            "subagent_type",
            "subagentType",
            "custom_agent",
            "agent",
            "name",
        ),
    )
    model = _first_string(
        tool_input,
        (
            "model",
            "model_id",
            "requested_model",
            "subagent_model",
        ),
    )
    background = tool_input.get("is_background")
    if background is None:
        background = tool_input.get("run_in_background")
    if background is not None and type(background) is not bool:
        raise GuardError("Task background flag is invalid")
    parent = _parent_from_payload(payload)
    tool_use_id = payload.get("tool_use_id") or payload.get("tool_call_id")
    if tool_use_id is not None and (
        not isinstance(tool_use_id, str) or not tool_use_id.strip()
    ):
        raise GuardError("Task tool-call identity is invalid")
    return {
        "tool_name": "Task",
        "requested_agent": agent,
        "requested_model": model,
        "is_background": background,
        "parent_conversation_id": parent,
        "tool_use_id": tool_use_id.strip() if isinstance(tool_use_id, str) else None,
        "description": tool_input.get("description")
        if isinstance(tool_input.get("description"), str)
        else None,
    }


def _redact_for_capture(payload: Mapping[str, Any]) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input_obj = json.loads(tool_input)
        except json.JSONDecodeError:
            tool_input_obj = {"_unparsed": True}
    elif isinstance(tool_input, dict):
        tool_input_obj = dict(tool_input)
    else:
        tool_input_obj = {}
    safe_input = {
        key: tool_input_obj.get(key)
        for key in (
            "subagent_type",
            "subagentType",
            "custom_agent",
            "agent",
            "name",
            "model",
            "model_id",
            "requested_model",
            "subagent_model",
            "is_background",
            "run_in_background",
            "description",
            "readonly",
            "resume",
            "environment",
        )
        if key in tool_input_obj
    }
    if isinstance(safe_input.get("description"), str):
        safe_input["description"] = safe_input["description"][:120]
    return {
        "hook_event_name": payload.get("hook_event_name"),
        "tool_name": payload.get("tool_name"),
        "tool_use_id": payload.get("tool_use_id") or payload.get("tool_call_id"),
        "conversation_id": payload.get("conversation_id"),
        "parent_conversation_id": payload.get("parent_conversation_id"),
        "generation_id": payload.get("generation_id"),
        "cwd": payload.get("cwd"),
        "model": payload.get("model"),
        "cursor_version": payload.get("cursor_version"),
        "tool_input": safe_input,
        "captured_at": utc_now(),
    }


def _capture_canary_payload(payload: Mapping[str, Any]) -> None:
    HOOK_CANARY_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(CAPTURED_PAYLOAD_PATH, _redact_for_capture(payload))


def _authorization_event(
    *,
    lease: Mapping[str, Any] | None,
    routing: Mapping[str, Any],
    verdict: str,
    reason: str,
    policy: Mapping[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    event = {
        "schema_version": 1,
        "event_kind": "preToolUse_task_authorization",
        "timestamp": utc_now(),
        "mode": mode,
        "tool_name": "Task",
        "tool_use_id": routing.get("tool_use_id"),
        "parent_conversation_id": routing.get("parent_conversation_id"),
        "requested_agent": routing.get("requested_agent"),
        "requested_model": routing.get("requested_model"),
        "is_background": routing.get("is_background"),
        "authorization_verdict": verdict,
        "authorization_reason": reason,
        "policy_digest": _policy_digest(policy) if policy is not None else None,
        "lease_owner": None if lease is None else lease.get("owner"),
        "lease_session": None
        if lease is None
        else lease.get("process_or_session_identity"),
        "active_flow": None if lease is None else lease.get("active_flow"),
        "active_stage": None if lease is None else lease.get("active_stage"),
        "foreground_ide_native": True,
        "duplicate_replay": False,
    }
    event["event_digest"] = _event_digest(event)
    return event


def _append_authorization_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if AUTHORIZATION_EVENTS.exists():
        try:
            for line in AUTHORIZATION_EVENTS.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                existing = json.loads(line)
                if (
                    isinstance(existing, dict)
                    and existing.get("event_digest") == event.get("event_digest")
                ):
                    return {**existing, "duplicate_replay": True}
                if (
                    isinstance(existing, dict)
                    and existing.get("tool_use_id")
                    and existing.get("tool_use_id") == event.get("tool_use_id")
                    and existing.get("authorization_verdict") == event.get("authorization_verdict")
                    and existing.get("requested_agent") == event.get("requested_agent")
                    and existing.get("requested_model") == event.get("requested_model")
                ):
                    return {**existing, "duplicate_replay": True}
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    _append_jsonl(AUTHORIZATION_EVENTS, event)
    return dict(event)


def authorize_task_call(
    payload: Mapping[str, object],
    *,
    lease: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or _load_policy()
    active_lease = lease
    if active_lease is None and delivery_lease_active():
        active_lease = _require_active_lease()
    try:
        routing = extract_task_routing(payload)
    except GuardError as exc:
        reason = str(exc)
        event = _authorization_event(
            lease=active_lease,
            routing={
                "tool_use_id": payload.get("tool_use_id") or payload.get("tool_call_id"),
                "parent_conversation_id": _parent_from_payload(payload),
                "requested_agent": None,
                "requested_model": None,
                "is_background": None,
            },
            verdict="deny",
            reason=reason,
            policy=policy,
            mode="enforce" if active_lease is not None else "passthrough",
        )
        if active_lease is None:
            return {
                "permission": "allow",
                "authorization": {
                    "authorization_verdict": "allow",
                    "authorization_reason": "no_active_delivery_lease",
                    "mode": "passthrough",
                },
                "routing": {},
            }
        stored = _append_authorization_event(event)
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
            "authorization": stored,
            "routing": {},
        }
    if active_lease is None:
        return {
            "permission": "allow",
            "authorization": {
                "authorization_verdict": "allow",
                "authorization_reason": "no_active_delivery_lease",
                "mode": "passthrough",
            },
            "routing": routing,
        }

    reason = "authorized"
    try:
        agent = routing["requested_agent"]
        model = routing["requested_model"]
        if agent is None:
            raise GuardError("Task agent identity is missing")
        if model is None:
            raise GuardError("Task model is missing")
        prefix = policy["agent_namespace_prefix"]
        allowed = set(policy["allowed_agents"])
        denied_models = set(policy["denied_models"])
        denied_builtin = set(policy["denied_builtin_agents"]) | BUILTIN_DENY_DEFAULT
        if agent in denied_builtin:
            raise GuardError("built-in subagent is denied during PnS delivery")
        if not str(agent).startswith(prefix):
            raise GuardError("Task agent escapes the project namespace")
        if agent not in allowed:
            raise GuardError("unknown custom agent is denied")
        if model in denied_models:
            raise GuardError("unapproved model is denied")
        if model != policy["approved_model"]:
            raise GuardError("Task model is not the approved Grok 4.5 High identity")
        expected_agent = policy["stage_agents"].get(str(active_lease["active_stage"]))
        if expected_agent != agent:
            raise GuardError("Task agent does not match the active delivery stage")
        if routing["is_background"] is True:
            raise GuardError("background Task execution is denied")
        parent = routing["parent_conversation_id"]
        if parent == "":
            raise GuardError("native Task event has an invalid parent conversation identity")
        _bind_parent(dict(active_lease), parent if isinstance(parent, str) else None)
        if agent == "pns-flow-implementer":
            # Writable marker is still acquired at subagentStart audit time once a child ID exists.
            pass
    except GuardError as exc:
        reason = str(exc)
        event = _authorization_event(
            lease=active_lease,
            routing=routing,
            verdict="deny",
            reason=reason,
            policy=policy,
            mode="enforce",
        )
        stored = _append_authorization_event(event)
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
            "authorization": stored,
            "routing": routing,
        }

    event = _authorization_event(
        lease=active_lease,
        routing=routing,
        verdict="allow",
        reason=reason,
        policy=policy,
        mode="enforce",
    )
    stored = _append_authorization_event(event)
    return {
        "permission": "allow",
        "authorization": stored,
        "routing": routing,
    }


def _marker_for(
    lease: Mapping[str, Any],
    payload: Mapping[str, object],
    parent: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "lease_owner": lease["owner"],
        "lease_session": lease["process_or_session_identity"],
        "parent_conversation_id": parent,
        "active_flow": lease["active_flow"],
        "active_stage": lease["active_stage"],
        "subagent_id": payload.get("subagent_id"),
        "subagent_type": "pns-flow-implementer",
        "created_at": utc_now(),
    }


def _acquire_writable_marker(
    lease: Mapping[str, Any],
    payload: Mapping[str, object],
    parent: str | None,
) -> None:
    if WRITABLE_MARKER.exists():
        raise GuardError("a writable PnS flow implementer marker remains unresolved")
    _atomic_write(WRITABLE_MARKER, _marker_for(lease, payload, parent))


def _release_writable_marker(lease: Mapping[str, Any], payload: Mapping[str, object]) -> None:
    subagent_type = payload.get("subagent_type")
    if subagent_type != "pns-flow-implementer":
        return
    marker = _read_object(WRITABLE_MARKER)
    if marker is None:
        return
    expected = {
        "lease_owner": lease.get("owner"),
        "lease_session": lease.get("process_or_session_identity"),
        "active_flow": lease.get("active_flow"),
    }
    if any(marker.get(field) != value for field, value in expected.items()):
        return
    subagent_id = payload.get("subagent_id")
    if subagent_id and marker.get("subagent_id") != subagent_id:
        return
    WRITABLE_MARKER.unlink(missing_ok=True)


def _latest_matching_authorization(
    *,
    lease: Mapping[str, Any],
    subagent_type: str,
    parent: str | None,
) -> dict[str, Any] | None:
    if not AUTHORIZATION_EVENTS.exists():
        return None
    try:
        lines = AUTHORIZATION_EVENTS.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    matches: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("authorization_verdict") != "allow":
            continue
        if event.get("requested_agent") != subagent_type:
            continue
        if event.get("lease_session") != lease.get("process_or_session_identity"):
            continue
        if event.get("active_flow") != lease.get("active_flow"):
            continue
        if event.get("active_stage") != lease.get("active_stage"):
            continue
        if parent is not None and event.get("parent_conversation_id") not in {None, parent}:
            continue
        matches.append(event)
    return matches[-1] if matches else None


def _handle_subagent_start_audit(payload: Mapping[str, object]) -> dict[str, object]:
    """Audit-only: never deny. Record resolved identity and requested-versus-resolved match."""
    lease = _require_active_lease()
    policy = _load_policy()
    subagent_type = payload.get("subagent_type")
    observed_model = payload.get("subagent_model") or payload.get("model")
    subagent_id = payload.get("subagent_id")
    parent = _parent_from_payload(payload)
    if parent == "":
        parent = None
    else:
        parent = _bind_parent(lease, parent if isinstance(parent, str) else None)
    auth = _latest_matching_authorization(
        lease=lease,
        subagent_type=str(subagent_type) if subagent_type is not None else "",
        parent=parent,
    )
    requested_agent = None if auth is None else auth.get("requested_agent")
    requested_model = None if auth is None else auth.get("requested_model")
    match = (
        auth is not None
        and subagent_type == requested_agent
        and (
            observed_model is None
            or observed_model == requested_model
            or observed_model == policy["approved_model"]
        )
    )
    if (
        subagent_type == "pns-flow-implementer"
        and match
        and isinstance(subagent_id, str)
        and subagent_id.strip()
    ):
        try:
            _acquire_writable_marker(lease, payload, parent)
        except GuardError:
            match = False
    event = {
        "schema_version": 3,
        "event_kind": "subagentStart_audit",
        "timestamp": utc_now(),
        "lease_acquisition_timestamp": lease["acquisition_timestamp"],
        "lease_owner": lease["owner"],
        "lease_session": lease["process_or_session_identity"],
        "parent_conversation_id": parent,
        "active_flow": lease["active_flow"],
        "active_stage": lease["active_stage"],
        "subagent_id": subagent_id,
        "subagent_type": subagent_type,
        "subagent_model": observed_model,
        "requested_agent": requested_agent,
        "requested_model": requested_model,
        "authorization_event_digest": None if auth is None else auth.get("event_digest"),
        "requested_versus_resolved_match": match,
        "policy_digest": _policy_digest(policy),
        "audit_only": True,
    }
    _append_jsonl(ROUTING_EVENTS, event)
    return {"permission": "allow"}


def reconcile_writable_marker(
    *,
    owner: str,
    session_id: str,
    terminal_state: str,
) -> dict[str, object]:
    with state_lock():
        marker = _read_object(WRITABLE_MARKER)
        if marker is None:
            return {"reconciled": False, "reason": "no_marker"}
        lease = _read_object(LEASE)
        if lease is None:
            WRITABLE_MARKER.unlink(missing_ok=True)
            return {"reconciled": True, "reason": "no_delivery_lease"}
        if terminal_state not in {"completed", "blocked"}:
            raise GuardError("marker reconciliation requires a terminal delivery state")
        if (
            lease.get("owner") != owner
            or lease.get("process_or_session_identity") != session_id
            or marker.get("lease_owner") != owner
            or marker.get("lease_session") != session_id
            or marker.get("active_flow") != lease.get("active_flow")
        ):
            raise GuardError("writable marker belongs to another lease or session")
        if lease.get("active_stage") != terminal_state:
            raise GuardError("owning delivery lease is not terminal")
        if lease.get("runtime_ownership_state") not in {"none", "released"}:
            raise GuardError("runtime ownership is not terminal")
        if lease.get("unresolved_action_state") != "clear":
            raise GuardError("unresolved-action gate is not clear")
        WRITABLE_MARKER.unlink(missing_ok=True)
        return {"reconciled": True, "reason": "owning_lease_terminal"}


def _handle_pretooluse(payload: Mapping[str, object]) -> dict[str, object]:
    tool_name = payload.get("tool_name")
    if tool_name != "Task":
        return {"permission": "allow"}
    if audit_only_mode():
        try:
            _capture_canary_payload(dict(payload))
            result = authorize_task_call(payload)
            # Audit-only canary captures and evaluates, but does not deny.
            return {
                "permission": "allow",
                "agent_message": (
                    "preToolUse audit-only canary mode; enforcement deferred. "
                    f"evaluated_verdict={result['permission']}"
                ),
            }
        except Exception as exc:  # noqa: BLE001 - fail closed when enforcement is later enabled
            _capture_canary_payload(dict(payload))
            return {
                "permission": "allow",
                "agent_message": f"preToolUse audit-only capture with evaluation error: {exc}",
            }
    try:
        result = authorize_task_call(payload)
    except (GuardError, OSError, UnicodeError, json.JSONDecodeError, routing_policy.RoutingPolicyError) as exc:
        reason = str(exc)
        event = _authorization_event(
            lease=_read_object(LEASE),
            routing={
                "tool_use_id": payload.get("tool_use_id"),
                "parent_conversation_id": _parent_from_payload(payload),
                "requested_agent": None,
                "requested_model": None,
                "is_background": None,
            },
            verdict="deny",
            reason=reason,
            policy=None,
            mode="enforce",
        )
        _append_authorization_event(event)
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
        }
    if result["permission"] == "deny":
        return {
            "permission": "deny",
            "user_message": result.get("user_message"),
            "agent_message": result.get("agent_message"),
        }
    return {"permission": "allow"}


def _hook_main() -> int:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        # Cursor sometimes invokes the script with an empty stdin on Windows.
        # Never treat that as a successful deny boundary for subagent creation.
        emit(
            {
                "permission": "allow",
                "user_message": "hook_stdin_empty_audit_only",
            }
        )
        return 0
    try:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeError:
            payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        emit(
            {
                "permission": "allow",
                "user_message": f"audit_error:invalid_hook_json:{exc}",
            }
        )
        return 0
    if not isinstance(payload, dict):
        emit(
            {
                "permission": "allow",
                "user_message": "audit_error:invalid_hook_object",
            }
        )
        return 0
    event_name = payload.get("hook_event_name")
    if event_name == "preToolUse":
        try:
            with state_lock():
                emit(_handle_pretooluse(payload))
            return 0
        except Exception as exc:  # noqa: BLE001 - fail closed for enforcement
            emit(
                {
                    "permission": "deny",
                    "user_message": f"preToolUse handler failure: {exc}",
                    "agent_message": f"preToolUse handler failure: {exc}",
                }
            )
            return 0
    try:
        lease = _read_object(LEASE)
        if not lease or lease.get("workflow") != "pns-flow-delivery":
            emit({"permission": "allow"})
            return 0
        with state_lock():
            if event_name == "subagentStop":
                _release_writable_marker(_require_active_lease(), payload)
                emit({})
                return 0
            emit(_handle_subagent_start_audit(payload))
            return 0
    except Exception as exc:  # noqa: BLE001 - audit-only must not deny
        emit(
            {
                "permission": "allow",
                "user_message": f"audit_error:{exc}",
            }
        )
        return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command")
    reconcile = sub.add_parser("reconcile-marker")
    reconcile.add_argument("--owner", required=True)
    reconcile.add_argument("--session-id", required=True)
    reconcile.add_argument("--terminal-state", required=True, choices=("completed", "blocked"))
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command != "reconcile-marker":
        return _hook_main()
    try:
        result = reconcile_writable_marker(
            owner=args.owner,
            session_id=args.session_id,
            terminal_state=args.terminal_state,
        )
    except GuardError as exc:
        emit({"ok": False, "error": str(exc)})
        return 2
    emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
