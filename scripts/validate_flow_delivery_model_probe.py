#!/usr/bin/env python3
"""Passively validate one lease-bound Cursor IDE-native Task invocation receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / ".local-orchestrator"
DEFAULT_LEASE = LOCAL_ROOT / "flow-delivery-lease.json"
DEFAULT_EVENTS = LOCAL_ROOT / "model-routing-events.jsonl"
DEFAULT_REPORT = LOCAL_ROOT / "model-routing-probe-report.json"
EXPECTED_MODEL = "cursor-grok-4.5-high"
STAGE_AGENTS = {
    "reconnaissance": "pns-flow-recon",
    "implementation": "pns-flow-implementer",
    "correction": "pns-flow-implementer",
    "implementation_review": "pns-flow-reviewer",
    "evidence_review": "pns-evidence-reviewer",
}


class RoutingValidationError(RuntimeError):
    """Raised when IDE-native routing evidence is absent, stale, or mismatched."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoutingValidationError(f"{label} is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise RoutingValidationError(f"{label} must be an object")
    return payload


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RoutingValidationError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoutingValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RoutingValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _frontmatter_model(agent: str) -> str | None:
    path = ROOT / ".cursor" / "agents" / f"{agent}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r"(?m)^model:\s*(\S+)\s*$", text)
    return match.group(1) if match else None


def _read_events(path: Path, *, required: bool = False) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if not required:
            return []
        raise RoutingValidationError("IDE-native subagentStart events are unavailable")
    except (OSError, UnicodeError) as exc:
        raise RoutingValidationError("IDE-native subagentStart events are unavailable") from exc
    events: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RoutingValidationError(f"routing event line {ordinal} is invalid") from exc
        if not isinstance(event, dict):
            raise RoutingValidationError(f"routing event line {ordinal} must be an object")
        events.append(event)
    return events


def _atomic_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def validate_event(
    *,
    expected_agent: str,
    expected_stage: str,
    lease_session_id: str,
    lease_path: Path = DEFAULT_LEASE,
    events_path: Path = DEFAULT_EVENTS,
) -> dict[str, Any]:
    if STAGE_AGENTS.get(expected_stage) != expected_agent:
        raise RoutingValidationError("expected agent does not match the delivery stage")
    lease = _read_object(lease_path, "active development lease")
    if lease.get("workflow") != "pns-flow-delivery":
        raise RoutingValidationError("active development lease has the wrong workflow")
    if lease.get("process_or_session_identity") != lease_session_id:
        raise RoutingValidationError("lease session identity mismatch")
    if lease.get("active_stage") != expected_stage:
        raise RoutingValidationError("active delivery stage mismatch")
    active_flow = lease.get("active_flow")
    if not isinstance(active_flow, str) or not active_flow.strip():
        raise RoutingValidationError("active lease does not bind a flow or IDE canary")
    parent_conversation_id = lease.get("bound_parent_conversation_id")
    if not isinstance(parent_conversation_id, str) or not parent_conversation_id.strip():
        raise RoutingValidationError("lease is not bound to the current IDE parent conversation")
    acquired_at = _parse_timestamp(lease.get("acquisition_timestamp"), "lease acquisition")
    receipts = lease.get("subagent_invocation_receipts")
    if not isinstance(receipts, list):
        raise RoutingValidationError("lease does not contain native invocation receipts")
    current_receipts: list[tuple[datetime, dict[str, Any]]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise RoutingValidationError("native invocation receipt must be an object")
        receipt_at = _parse_timestamp(receipt.get("timestamp"), "receipt timestamp")
        if receipt_at >= acquired_at:
            current_receipts.append((receipt_at, receipt))
    if not current_receipts:
        raise RoutingValidationError("no native invocation receipt exists for the current lease")
    receipt_at, receipt = max(current_receipts, key=lambda item: item[0])
    expected_bindings = {
        "lease_owner": lease.get("owner"),
        "lease_session": lease_session_id,
        "parent_conversation_id": parent_conversation_id,
        "active_flow": active_flow,
        "active_stage": expected_stage,
        "custom_agent": expected_agent,
        "requested_model": EXPECTED_MODEL,
        "repository_head": lease.get("expected_repository_head"),
    }
    for field, expected in expected_bindings.items():
        if receipt.get(field) != expected:
            raise RoutingValidationError(f"native invocation receipt {field} mismatch")
    if receipt.get("is_background") is not False:
        raise RoutingValidationError("native invocation receipt is not foreground")
    if receipt.get("terminal_outcome") != "completed":
        raise RoutingValidationError("native invocation receipt is not completed")
    subagent_id = receipt.get("subagent_id")
    if not isinstance(subagent_id, str) or not subagent_id.strip():
        raise RoutingValidationError("native invocation receipt lacks a subagent ID")
    if _frontmatter_model(expected_agent) != EXPECTED_MODEL:
        raise RoutingValidationError("custom-agent frontmatter model does not match")
    if receipt_at > datetime.now(timezone.utc):
        raise RoutingValidationError("native invocation receipt is from the future")
    unsigned = dict(receipt)
    digest = unsigned.pop("receipt_digest", None)
    expected_digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != expected_digest:
        raise RoutingValidationError("native invocation receipt digest mismatch")
    hook = receipt.get("hook_cross_check")
    if not isinstance(hook, dict) or hook.get("required") is not False:
        raise RoutingValidationError("optional hook cross-check status is invalid")
    hook_status = hook.get("status")
    if hook_status not in {"matched", "not_emitted"}:
        raise RoutingValidationError("optional hook mode is not reported honestly")
    if hook_status == "matched":
        matching = [
            event
            for event in _read_events(events_path, required=True)
            if event.get("subagent_id") == subagent_id
        ]
        if not matching or hook.get("event_digest") not in {
            hashlib.sha256(
                json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for event in matching
        }:
            raise RoutingValidationError("optional hook cross-check evidence mismatch")
    return {
        "schema_version": 3,
        "status": "passed",
        "source": "cursor_ide_native_task_receipt",
        "lease_owner": lease["owner"],
        "lease_session": lease_session_id,
        "parent_conversation_id": parent_conversation_id,
        "active_flow": active_flow,
        "active_stage": expected_stage,
        "subagent_type": expected_agent,
        "subagent_id": subagent_id,
        "resolved_model": EXPECTED_MODEL,
        "receipt_timestamp": receipt.get("timestamp"),
        "receipt_digest": digest,
        "hook_cross_check": hook,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--expected-agent", required=True, choices=sorted(set(STAGE_AGENTS.values())))
    root.add_argument("--expected-stage", required=True, choices=sorted(STAGE_AGENTS))
    root.add_argument("--lease-session-id", required=True)
    root.add_argument("--lease", type=Path, default=DEFAULT_LEASE)
    root.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    root.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = validate_event(
            expected_agent=args.expected_agent,
            expected_stage=args.expected_stage,
            lease_session_id=args.lease_session_id,
            lease_path=args.lease,
            events_path=args.events,
        )
    except RoutingValidationError as exc:
        result = {"schema_version": 3, "status": "failed", "error": str(exc)}
        _atomic_report(args.report, result)
        print(json.dumps(result, sort_keys=True))
        return 2
    _atomic_report(args.report, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
