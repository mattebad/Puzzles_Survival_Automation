#!/usr/bin/env python3
"""Scope subagent routing enforcement to an active PnS flow-delivery lease."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT = Path.cwd()
LOCAL_ROOT = ROOT / ".local-orchestrator"
LEASE = LOCAL_ROOT / "flow-delivery-lease.json"
WRITABLE_MARKER = LOCAL_ROOT / "writable-subagent.json"
ROUTING_EVENTS = LOCAL_ROOT / "model-routing-events.jsonl"
ALLOWED = {
    "pns-flow-recon",
    "pns-flow-implementer",
    "pns-flow-reviewer",
    "pns-evidence-reviewer",
}
EXPECTED_MODEL = "cursor-grok-4.5-high"


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def is_expected_model(payload: dict[str, object]) -> bool:
    return payload.get("subagent_model") == EXPECTED_MODEL


def delivery_lease_active() -> bool:
    try:
        payload = json.loads(LEASE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return payload.get("workflow") == "pns-flow-delivery"


def record_event(payload: dict[str, object]) -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "subagent_id": payload.get("subagent_id"),
        "subagent_type": payload.get("subagent_type"),
        "subagent_model": payload.get("subagent_model"),
        "model_id": payload.get("model_id"),
        "model_params": payload.get("model_params"),
        "cursor_version": payload.get("cursor_version"),
    }
    with ROUTING_EVENTS.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def acquire_writable_marker(payload: dict[str, object]) -> bool:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    marker = {
        "subagent_id": payload.get("subagent_id"),
        "subagent_type": payload.get("subagent_type"),
    }
    try:
        descriptor = os.open(WRITABLE_MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(marker, sort_keys=True) + "\n")
    return True


def release_writable_marker(payload: dict[str, object]) -> None:
    if payload.get("subagent_type") != "pns-flow-implementer":
        return
    try:
        marker = json.loads(WRITABLE_MARKER.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not payload.get("subagent_id") or marker.get("subagent_id") == payload.get("subagent_id"):
        WRITABLE_MARKER.unlink(missing_ok=True)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (UnicodeError, json.JSONDecodeError):
        emit({"permission": "deny", "user_message": "Invalid subagent hook input."})
        return 0
    if not delivery_lease_active():
        emit({"permission": "allow"})
        return 0
    event = payload.get("hook_event_name")
    if event == "subagentStop":
        release_writable_marker(payload)
        emit({})
        return 0
    subagent_type = payload.get("subagent_type")
    if subagent_type not in ALLOWED:
        emit(
            {
                "permission": "deny",
                "user_message": "The active PnS delivery lease permits only its four named custom subagents.",
            }
        )
        return 0
    if not is_expected_model(payload):
        emit(
            {
                "permission": "deny",
                "user_message": "PnS delivery subagent model routing did not resolve to Grok 4.5 High.",
            }
        )
        return 0
    if subagent_type == "pns-flow-implementer" and not acquire_writable_marker(payload):
        emit(
            {
                "permission": "deny",
                "user_message": "A writable PnS flow implementer is already active.",
            }
        )
        return 0
    record_event(payload)
    emit({"permission": "allow"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
