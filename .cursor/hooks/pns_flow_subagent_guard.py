#!/usr/bin/env python3
"""Fail-closed Cursor IDE-native subagent routing for an active PnS delivery lease."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = ROOT / ".local-orchestrator"
LEASE = LOCAL_ROOT / "flow-delivery-lease.json"
WRITABLE_MARKER = LOCAL_ROOT / "writable-subagent.json"
ROUTING_EVENTS = LOCAL_ROOT / "model-routing-events.jsonl"
STATE_LOCK = LOCAL_ROOT / "subagent-guard.lock"
ALLOWED = {
    "pns-flow-recon",
    "pns-flow-implementer",
    "pns-flow-reviewer",
    "pns-evidence-reviewer",
}
STAGE_AGENTS = {
    "reconnaissance": "pns-flow-recon",
    "implementation": "pns-flow-implementer",
    "correction": "pns-flow-implementer",
    "implementation_review": "pns-flow-reviewer",
    "evidence_review": "pns-evidence-reviewer",
}
EXPECTED_MODEL = "cursor-grok-4.5-high"


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


def _require_active_lease() -> dict[str, Any]:
    lease = _read_object(LEASE)
    if not lease or lease.get("workflow") != "pns-flow-delivery":
        raise GuardError("active PnS development lease is unavailable")
    for field in ("owner", "process_or_session_identity", "active_flow", "active_stage"):
        if not isinstance(lease.get(field), str) or not lease[field].strip():
            raise GuardError(f"active development lease does not bind {field}")
    return lease


def _bind_parent(lease: dict[str, Any], payload: Mapping[str, object]) -> str | None:
    parent = payload.get("conversation_id") or payload.get("parent_conversation_id")
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


def _append_event(event: Mapping[str, object]) -> None:
    with ROUTING_EVENTS.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


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
    if payload.get("subagent_type") != "pns-flow-implementer":
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


def _handle_start(payload: Mapping[str, object]) -> dict[str, object]:
    lease = _require_active_lease()
    subagent_type = payload.get("subagent_type")
    if subagent_type not in ALLOWED:
        raise GuardError("active PnS delivery lease permits only four named custom subagents")
    observed_model = payload.get("subagent_model") or payload.get("model")
    if observed_model is not None and observed_model != EXPECTED_MODEL:
        raise GuardError("PnS delivery subagent did not resolve to Grok 4.5 High")
    expected_agent = STAGE_AGENTS.get(str(lease["active_stage"]))
    if expected_agent != subagent_type:
        raise GuardError("custom subagent type does not match the active delivery stage")
    subagent_id = payload.get("subagent_id")
    if subagent_id is not None and (
        not isinstance(subagent_id, str) or not subagent_id.strip()
    ):
        raise GuardError("native subagent event has an invalid subagent ID")
    parent = _bind_parent(lease, payload)
    if subagent_type == "pns-flow-implementer":
        _acquire_writable_marker(lease, payload, parent)
    event = {
        "schema_version": 2,
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
    }
    _append_event(event)
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


def _hook_main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise GuardError("invalid subagent hook input")
        lease = _read_object(LEASE)
        if not lease or lease.get("workflow") != "pns-flow-delivery":
            emit({"permission": "allow"})
            return 0
        with state_lock():
            if payload.get("hook_event_name") == "subagentStop":
                _release_writable_marker(_require_active_lease(), payload)
                emit({})
                return 0
            emit(_handle_start(payload))
            return 0
    except (GuardError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        emit({"permission": "deny", "user_message": str(exc)})
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
