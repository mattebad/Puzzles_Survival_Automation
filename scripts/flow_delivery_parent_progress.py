#!/usr/bin/env python3
"""Parent-conversation completed-gameplay-flow progress for the delivery loop.

Local operational state only. Grants no gameplay authorization.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOOP_POLICY_PATH = REPO_ROOT / "tasks" / "flow_delivery_loop_policy.json"
DEFAULT_PROGRESS_PATH = REPO_ROOT / ".local-orchestrator" / "parent-conversation-progress.json"

PARENT_CONVERSATION_ROLLOVER_REQUIRED = "PARENT_CONVERSATION_ROLLOVER_REQUIRED"
RESUME_INVOCATION_LINES = (
    "/loop Load and follow `.cursor/commands/pns-flow-delivery-loop.md` exactly.",
    "Continue the authoritative queue until a checked-in hard stop condition occurs.",
    "IDE-native custom subagents only; no CLI fallback.",
)
RESUME_INVOCATION = "\n".join(RESUME_INVOCATION_LINES)

PROGRESS_SCHEMA_VERSION = 1
REQUIRED_POLICY_FIELDS = {
    "schema_version",
    "registry_kind",
    "max_completed_flows_per_parent_conversation",
}
REQUIRED_PROGRESS_ROOT_FIELDS = {"schema_version", "parents"}
REQUIRED_PARENT_ENTRY_FIELDS = {
    "parent_conversation_id",
    "completed_gameplay_flow_count",
    "counted_flow_ids",
    "counted_completions",
    "latest_counted_completion_timestamp",
    "latest_counted_commit",
    "rollover_required",
    "configured_maximum",
    "policy_digest",
}
REQUIRED_COUNTED_COMPLETION_FIELDS = {
    "flow_id",
    "commit",
    "recorded_at",
    "full_suite_receipt_digest",
}


class ParentProgressError(RuntimeError):
    """Raised when loop policy or parent progress state fails closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParentProgressError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ParentProgressError(f"JSON root must be an object: {path}")
    return payload


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParentProgressError(f"{field} must be a non-empty string")
    return value


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ParentProgressError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParentProgressError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ParentProgressError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_loop_policy(payload: Mapping[str, Any]) -> None:
    if set(payload) != REQUIRED_POLICY_FIELDS:
        missing = REQUIRED_POLICY_FIELDS - set(payload)
        extra = set(payload) - REQUIRED_POLICY_FIELDS
        if missing:
            raise ParentProgressError(
                f"loop policy missing required fields: {sorted(missing)}"
            )
        raise ParentProgressError(f"loop policy has unknown fields: {sorted(extra)}")
    if payload.get("schema_version") != 1:
        raise ParentProgressError("unsupported loop-policy schema")
    if payload.get("registry_kind") != "flow_delivery_loop_policy":
        raise ParentProgressError("wrong loop-policy registry kind")
    maximum = payload.get("max_completed_flows_per_parent_conversation")
    if type(maximum) is not int:
        raise ParentProgressError(
            "max_completed_flows_per_parent_conversation must be an integer"
        )
    if maximum < 0:
        raise ParentProgressError(
            "max_completed_flows_per_parent_conversation must be nonnegative"
        )


def load_loop_policy(path: Path = DEFAULT_LOOP_POLICY_PATH) -> dict[str, Any]:
    payload = _read_json(path)
    validate_loop_policy(payload)
    return payload


def loop_policy_digest(payload: Mapping[str, Any]) -> str:
    validate_loop_policy(payload)
    return _canonical_digest(dict(payload))


def empty_parent_entry(
    *,
    parent_conversation_id: str,
    configured_maximum: int,
    policy_digest: str,
) -> dict[str, Any]:
    _require_nonempty_string(parent_conversation_id, "parent_conversation_id")
    if type(configured_maximum) is not int or configured_maximum < 0:
        raise ParentProgressError("configured_maximum must be a nonnegative integer")
    _require_nonempty_string(policy_digest, "policy_digest")
    return {
        "parent_conversation_id": parent_conversation_id,
        "completed_gameplay_flow_count": 0,
        "counted_flow_ids": [],
        "counted_completions": [],
        "latest_counted_completion_timestamp": None,
        "latest_counted_commit": None,
        "rollover_required": False,
        "configured_maximum": configured_maximum,
        "policy_digest": policy_digest,
    }


def validate_counted_completion(item: Mapping[str, Any]) -> None:
    if set(item) != REQUIRED_COUNTED_COMPLETION_FIELDS:
        raise ParentProgressError("counted completion schema mismatch")
    for field in ("flow_id", "commit", "recorded_at"):
        _require_nonempty_string(item[field], f"counted_completion.{field}")
    _parse_timestamp(item["recorded_at"], "counted_completion.recorded_at")
    digest = item["full_suite_receipt_digest"]
    if digest is not None and (
        not isinstance(digest, str) or not digest.strip()
    ):
        raise ParentProgressError(
            "counted_completion.full_suite_receipt_digest must be null or non-empty"
        )


def validate_parent_entry(entry: Mapping[str, Any]) -> None:
    if set(entry) != REQUIRED_PARENT_ENTRY_FIELDS:
        raise ParentProgressError("parent progress entry schema mismatch")
    _require_nonempty_string(entry["parent_conversation_id"], "parent_conversation_id")
    count = entry["completed_gameplay_flow_count"]
    if type(count) is not int or count < 0:
        raise ParentProgressError("completed_gameplay_flow_count must be nonnegative")
    if not isinstance(entry["counted_flow_ids"], list) or any(
        not isinstance(item, str) or not item.strip() for item in entry["counted_flow_ids"]
    ):
        raise ParentProgressError("counted_flow_ids must be a list of non-empty strings")
    if not isinstance(entry["counted_completions"], list):
        raise ParentProgressError("counted_completions must be a list")
    if len(entry["counted_flow_ids"]) != count or len(entry["counted_completions"]) != count:
        raise ParentProgressError("completed gameplay count does not match counted records")
    seen_pairs: set[tuple[str, str]] = set()
    for ordinal, item in enumerate(entry["counted_completions"]):
        if not isinstance(item, dict):
            raise ParentProgressError("counted completion must be an object")
        validate_counted_completion(item)
        if entry["counted_flow_ids"][ordinal] != item["flow_id"]:
            raise ParentProgressError("counted_flow_ids order does not match completions")
        pair = (item["flow_id"], item["commit"])
        if pair in seen_pairs:
            raise ParentProgressError("duplicate counted completion records")
        seen_pairs.add(pair)
    if count == 0:
        if entry["latest_counted_completion_timestamp"] is not None:
            raise ParentProgressError("empty progress cannot have a latest timestamp")
        if entry["latest_counted_commit"] is not None:
            raise ParentProgressError("empty progress cannot have a latest commit")
    else:
        _parse_timestamp(
            entry["latest_counted_completion_timestamp"],
            "latest_counted_completion_timestamp",
        )
        _require_nonempty_string(entry["latest_counted_commit"], "latest_counted_commit")
        last = entry["counted_completions"][-1]
        if entry["latest_counted_commit"] != last["commit"]:
            raise ParentProgressError("latest_counted_commit mismatch")
        if entry["latest_counted_completion_timestamp"] != last["recorded_at"]:
            raise ParentProgressError("latest_counted_completion_timestamp mismatch")
    if type(entry["rollover_required"]) is not bool:
        raise ParentProgressError("rollover_required must be boolean")
    if type(entry["configured_maximum"]) is not int or entry["configured_maximum"] < 0:
        raise ParentProgressError("configured_maximum must be a nonnegative integer")
    _require_nonempty_string(entry["policy_digest"], "policy_digest")
    maximum = entry["configured_maximum"]
    if maximum == 0:
        if entry["rollover_required"]:
            raise ParentProgressError("unbounded policy cannot require rollover")
    elif count > maximum:
        raise ParentProgressError("completed gameplay count exceeds configured maximum")
    elif entry["rollover_required"] and count < maximum:
        raise ParentProgressError("rollover_required set before reaching the maximum")


def validate_progress_document(payload: Mapping[str, Any]) -> None:
    if set(payload) != REQUIRED_PROGRESS_ROOT_FIELDS:
        raise ParentProgressError("parent progress root schema mismatch")
    if payload.get("schema_version") != PROGRESS_SCHEMA_VERSION:
        raise ParentProgressError("unsupported parent progress schema")
    parents = payload.get("parents")
    if not isinstance(parents, dict):
        raise ParentProgressError("parents must be an object")
    for key, entry in parents.items():
        if not isinstance(key, str) or not key.strip():
            raise ParentProgressError("parent progress keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise ParentProgressError("parent progress entry must be an object")
        validate_parent_entry(entry)
        if entry["parent_conversation_id"] != key:
            raise ParentProgressError("parent progress key does not match entry identity")


def empty_progress_document() -> dict[str, Any]:
    return {"schema_version": PROGRESS_SCHEMA_VERSION, "parents": {}}


def load_progress(path: Path = DEFAULT_PROGRESS_PATH) -> dict[str, Any]:
    if not path.exists():
        return empty_progress_document()
    payload = _read_json(path)
    validate_progress_document(payload)
    return payload


def save_progress(path: Path, payload: Mapping[str, Any]) -> None:
    validate_progress_document(payload)
    _atomic_write_json(path, payload)


def get_parent_entry(
    payload: Mapping[str, Any],
    parent_conversation_id: str,
    *,
    configured_maximum: int,
    policy_digest: str,
) -> dict[str, Any]:
    validate_progress_document(payload)
    _require_nonempty_string(parent_conversation_id, "parent_conversation_id")
    existing = payload.get("parents", {}).get(parent_conversation_id)
    if existing is None:
        return empty_parent_entry(
            parent_conversation_id=parent_conversation_id,
            configured_maximum=configured_maximum,
            policy_digest=policy_digest,
        )
    entry = deepcopy(existing)
    if entry["policy_digest"] != policy_digest:
        raise ParentProgressError("parent progress policy digest mismatch")
    if entry["configured_maximum"] != configured_maximum:
        raise ParentProgressError("parent progress configured maximum mismatch")
    return entry


def prune_stale_parents(
    payload: dict[str, Any],
    *,
    keep_parent_ids: Sequence[str],
) -> dict[str, Any]:
    validate_progress_document(payload)
    keep = {item for item in keep_parent_ids if isinstance(item, str) and item.strip()}
    pruned = empty_progress_document()
    for identity, entry in payload["parents"].items():
        if identity in keep:
            pruned["parents"][identity] = deepcopy(entry)
    validate_progress_document(pruned)
    return pruned


def completion_already_counted(entry: Mapping[str, Any], flow_id: str, commit: str) -> bool:
    validate_parent_entry(entry)
    return any(
        item["flow_id"] == flow_id and item["commit"] == commit
        for item in entry["counted_completions"]
    )


def append_counted_completion(
    entry: dict[str, Any],
    *,
    flow_id: str,
    commit: str,
    recorded_at: str | None = None,
    full_suite_receipt_digest: str | None = None,
) -> dict[str, Any]:
    validate_parent_entry(entry)
    _require_nonempty_string(flow_id, "flow_id")
    _require_nonempty_string(commit, "commit")
    if completion_already_counted(entry, flow_id, commit):
        raise ParentProgressError("duplicate counted gameplay completion")
    timestamp = recorded_at or utc_now()
    _parse_timestamp(timestamp, "recorded_at")
    item = {
        "flow_id": flow_id,
        "commit": commit,
        "recorded_at": timestamp,
        "full_suite_receipt_digest": full_suite_receipt_digest,
    }
    validate_counted_completion(item)
    entry["counted_completions"].append(item)
    entry["counted_flow_ids"].append(flow_id)
    entry["completed_gameplay_flow_count"] = len(entry["counted_completions"])
    entry["latest_counted_completion_timestamp"] = timestamp
    entry["latest_counted_commit"] = commit
    maximum = entry["configured_maximum"]
    if maximum > 0 and entry["completed_gameplay_flow_count"] >= maximum:
        entry["rollover_required"] = True
    validate_parent_entry(entry)
    return entry


def rollover_reached(entry: Mapping[str, Any]) -> bool:
    validate_parent_entry(entry)
    maximum = entry["configured_maximum"]
    if maximum == 0:
        return False
    return entry["completed_gameplay_flow_count"] >= maximum


def assert_texts_do_not_hardcode_maximum(
    texts: Mapping[str, str],
    *,
    maximum: int,
) -> None:
    if maximum <= 0:
        return
    needle = str(maximum)
    for name, text in texts.items():
        # Allow semantic references, but forbid an authoritative numeric assignment.
        for pattern in (
            f"max_completed_flows_per_parent_conversation\": {needle}",
            f"max_completed_flows_per_parent_conversation = {needle}",
            f"maximum is {needle}",
            f"maximum of {needle}",
            f"at most {needle} fully completed",
            f"at most {needle} completed gameplay",
        ):
            if pattern in text:
                raise ParentProgressError(
                    f"{name} hardcodes competing maximum {maximum}"
                )
