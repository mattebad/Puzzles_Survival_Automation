#!/usr/bin/env python3
"""Fail-closed controller for the serial gameplay-flow development queue.

The controller never invokes an agent, executes gameplay input, mutates the gameplay scheduler, or
changes SafetyStore action results.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE_PATH = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
DEFAULT_POLICY_PATH = REPO_ROOT / "tasks" / "flow_delivery_product_policy.json"
DEFAULT_LEASE_PATH = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"
DEFAULT_WRITABLE_MARKER_PATH = REPO_ROOT / ".local-orchestrator" / "writable-subagent.json"
DEFAULT_ROUTING_EVENTS_PATH = REPO_ROOT / ".local-orchestrator" / "model-routing-events.jsonl"
CANARY_FLOW_ID = "IDE-NATIVE-SUBAGENT-CANARY"

QUEUE_STATUSES = {"ready", "active", "blocked", "completed", "needs_product_decision"}
STAGES = (
    "selected",
    "reconnaissance",
    "implementation",
    "implementation_review",
    "correction",
    "focused_validation",
    "full_validation",
    "live_preflight",
    "live_execution",
    "evidence_review",
    "commit",
    "completed",
    "blocked",
)
POLICY_STATUSES = {
    "explicitly_approved",
    "navigation_only_validation",
    "supervised_consequential_validation",
    "unresolved_user_decision",
    "prohibited",
}
LIVE_POLICY_STATUSES = {"navigation_only_validation", "supervised_consequential_validation"}
RUNTIME_OWNERSHIP_STATES = {"none", "released", "held", "unknown"}
UNRESOLVED_ACTION_STATES = {"clear", "unresolved", "unknown"}
ATTEMPT_OUTCOMES = {"completed", "blocked", "failed", "unresolved"}
TERMINAL_ATTEMPT_OUTCOMES = {"completed", "blocked", "failed"}
VALIDATION_PROFILES = {"focused_tests", "architecture_tests", "full_suite"}
EXPECTED_SUBAGENT_MODEL = "cursor-grok-4.5-high"
SUBAGENT_TERMINAL_OUTCOMES = {"completed", "blocked", "failed"}
STAGE_AGENTS = {
    "reconnaissance": "pns-flow-recon",
    "implementation": "pns-flow-implementer",
    "correction": "pns-flow-implementer",
    "implementation_review": "pns-flow-reviewer",
    "evidence_review": "pns-evidence-reviewer",
}
ALLOWED_SUBAGENTS = set(STAGE_AGENTS.values())
REQUIRED_RECEIPTS_BY_STAGE = {
    "focused_validation": {"focused_tests", "architecture_tests"},
    "full_validation": {"full_suite"},
}
REQUIRED_FLOW_FIELDS = {
    "flow_id",
    "title",
    "kind",
    "priority",
    "status",
    "backlog_task_id",
    "dependencies",
    "implementation_entrypoints",
    "navigation_model",
    "requires_bluestacks_live",
    "live_validation_scope",
    "consequence_policy",
    "product_policy_status",
    "maximum_live_attempts",
    "live_attempt_count",
    "live_attempts",
    "focused_tests",
    "evidence_validator",
    "performance_metrics_required",
    "blocked_reason",
    "next_concrete_action",
    "last_completed_stage",
    "last_commit",
    "artifact_root",
}
REQUIRED_LEASE_FIELDS = {
    "schema_version",
    "workflow",
    "lease_mode",
    "owner",
    "host",
    "process_or_session_identity",
    "bound_parent_conversation_id",
    "acquisition_timestamp",
    "heartbeat_timestamp",
    "acquired_repository_head",
    "expected_repository_head",
    "observed_repository_head",
    "acquired_working_tree_fingerprint",
    "expected_working_tree_fingerprint",
    "acquired_working_tree_snapshot",
    "expected_working_tree_snapshot",
    "reviewed_attributable_paths",
    "active_flow",
    "active_stage",
    "active_stage_entered_at",
    "runtime_ownership_state",
    "unresolved_action_state",
    "live_terminal_evidence",
    "safety_blocked_flow",
    "validation_receipts",
    "subagent_invocation_receipts",
    "reviewed_flow_commit",
    "gates",
}
TRANSITIONS = {
    "selected": {"reconnaissance", "blocked"},
    "reconnaissance": {"implementation", "blocked"},
    "implementation": {"implementation_review", "blocked"},
    "implementation_review": {"correction", "focused_validation", "blocked"},
    "correction": {"implementation_review", "blocked"},
    "focused_validation": {"full_validation", "blocked"},
    "full_validation": {"live_preflight", "evidence_review", "commit", "blocked"},
    "live_preflight": {"live_execution", "blocked"},
    "live_execution": {"evidence_review", "blocked"},
    "evidence_review": {"commit", "blocked"},
    "commit": {"completed", "blocked"},
    "completed": set(),
    "blocked": set(),
}


class FlowDeliveryError(RuntimeError):
    """Raised when queue, repository, validation, attempt, or lease policy fails closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FlowDeliveryError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FlowDeliveryError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise FlowDeliveryError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowDeliveryError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FlowDeliveryError(f"JSON root must be an object: {path}")
    return payload


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


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FlowDeliveryError(f"{field} must be a non-empty string")
    return value


def _validate_string_list(value: Any, field: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise FlowDeliveryError(f"{field} must be a list of non-empty strings")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_policy(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise FlowDeliveryError("unsupported product-policy schema")
    if payload.get("registry_kind") != "flow_delivery_product_policy":
        raise FlowDeliveryError("wrong product-policy registry kind")
    if set(payload.get("status_vocabulary", [])) != POLICY_STATUSES:
        raise FlowDeliveryError("product-policy vocabulary mismatch")
    policies = payload.get("policies")
    if not isinstance(policies, list) or not policies:
        raise FlowDeliveryError("product-policy registry requires policies")
    identities: set[str] = set()
    for policy in policies:
        if not isinstance(policy, dict):
            raise FlowDeliveryError("product-policy entry must be an object")
        identity = _require_nonempty_string(policy.get("policy_id"), "policy_id")
        if identity in identities:
            raise FlowDeliveryError(f"duplicate policy_id: {identity}")
        identities.add(identity)
        for field in ("scope", "decision", "source"):
            _require_nonempty_string(policy.get(field), f"policy.{field}")
        if policy.get("status") not in POLICY_STATUSES:
            raise FlowDeliveryError(f"unknown product-policy status: {policy.get('status')}")


def _validate_attempt(attempt: Mapping[str, Any], flow: Mapping[str, Any]) -> None:
    required = {
        "ordinal",
        "active_flow",
        "lease_owner",
        "lease_session",
        "repository_head",
        "started_at",
        "finished_at",
        "session_directory",
        "terminal_outcome",
        "diagnosis",
    }
    if set(attempt) != required:
        raise FlowDeliveryError(f"{flow['flow_id']} live attempt schema mismatch")
    if type(attempt["ordinal"]) is not int or attempt["ordinal"] <= 0:
        raise FlowDeliveryError("live attempt ordinal must be a positive integer")
    for field in ("active_flow", "lease_owner", "lease_session", "repository_head", "started_at"):
        _require_nonempty_string(attempt[field], f"attempt.{field}")
    _parse_timestamp(attempt["started_at"], "attempt.started_at")
    if attempt["active_flow"] != flow["flow_id"]:
        raise FlowDeliveryError("live attempt is bound to another flow")
    if attempt["finished_at"] is None:
        if attempt["terminal_outcome"] is not None:
            raise FlowDeliveryError("unfinished live attempt cannot have an outcome")
    else:
        _parse_timestamp(attempt["finished_at"], "attempt.finished_at")
        if attempt["terminal_outcome"] not in ATTEMPT_OUTCOMES:
            raise FlowDeliveryError("live attempt has an unknown outcome")
    if attempt["session_directory"] is not None and (
        not isinstance(attempt["session_directory"], str)
        or not attempt["session_directory"].strip()
    ):
        raise FlowDeliveryError("attempt session_directory must be null or non-empty")
    if not isinstance(attempt["diagnosis"], str):
        raise FlowDeliveryError("attempt diagnosis must be a string")
    if attempt["terminal_outcome"] in {"blocked", "failed", "unresolved"} and not attempt[
        "diagnosis"
    ].strip():
        raise FlowDeliveryError("non-successful live attempt requires a diagnosis")


def validate_queue(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != 2:
        raise FlowDeliveryError("unsupported delivery-queue schema")
    if payload.get("queue_kind") != "development_flow_delivery":
        raise FlowDeliveryError("queue is not a development-flow queue")
    if payload.get("gameplay_scheduler") is not False:
        raise FlowDeliveryError("development queue must declare gameplay_scheduler=false")
    if set(payload.get("status_vocabulary", [])) != QUEUE_STATUSES:
        raise FlowDeliveryError("queue status vocabulary mismatch")
    if tuple(payload.get("stage_vocabulary", [])) != STAGES:
        raise FlowDeliveryError("queue stage vocabulary mismatch")
    flows = payload.get("flows")
    if not isinstance(flows, list) or not flows:
        raise FlowDeliveryError("delivery queue requires flows")
    identities: set[str] = set()
    active: list[str] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for flow in flows:
        if not isinstance(flow, dict):
            raise FlowDeliveryError("flow entry must be an object")
        missing = REQUIRED_FLOW_FIELDS - set(flow)
        if missing:
            raise FlowDeliveryError(f"flow entry missing fields: {sorted(missing)}")
        identity = _require_nonempty_string(flow["flow_id"], "flow_id")
        if identity in identities:
            raise FlowDeliveryError(f"duplicate flow_id: {identity}")
        identities.add(identity)
        by_id[identity] = flow
        for field in (
            "title",
            "kind",
            "backlog_task_id",
            "navigation_model",
            "live_validation_scope",
            "consequence_policy",
            "evidence_validator",
            "next_concrete_action",
            "artifact_root",
        ):
            _require_nonempty_string(flow[field], f"{identity}.{field}")
        if type(flow["priority"]) is not int or flow["priority"] < 0:
            raise FlowDeliveryError(f"{identity}.priority must be a nonnegative integer")
        if flow["status"] not in QUEUE_STATUSES:
            raise FlowDeliveryError(f"unknown queue status: {flow['status']}")
        if flow["status"] == "active":
            active.append(identity)
        for field in (
            "dependencies",
            "implementation_entrypoints",
            "focused_tests",
            "performance_metrics_required",
        ):
            _validate_string_list(flow[field], f"{identity}.{field}")
        if type(flow["requires_bluestacks_live"]) is not bool:
            raise FlowDeliveryError(f"{identity}.requires_bluestacks_live must be boolean")
        if type(flow["maximum_live_attempts"]) is not int or flow["maximum_live_attempts"] < 0:
            raise FlowDeliveryError(f"{identity}.maximum_live_attempts must be nonnegative")
        if not flow["requires_bluestacks_live"] and flow["maximum_live_attempts"] != 0:
            raise FlowDeliveryError(f"{identity} forbids live attempts but has a nonzero limit")
        if type(flow["live_attempt_count"]) is not int or flow["live_attempt_count"] < 0:
            raise FlowDeliveryError(f"{identity}.live_attempt_count must be nonnegative")
        if not isinstance(flow["live_attempts"], list):
            raise FlowDeliveryError(f"{identity}.live_attempts must be a list")
        if flow["live_attempt_count"] != len(flow["live_attempts"]):
            raise FlowDeliveryError(f"{identity}.live_attempt_count does not match attempts")
        if flow["live_attempt_count"] > flow["maximum_live_attempts"]:
            raise FlowDeliveryError(f"{identity} exceeds its live-attempt budget")
        for ordinal, attempt in enumerate(flow["live_attempts"], start=1):
            if not isinstance(attempt, dict):
                raise FlowDeliveryError(f"{identity} live attempt must be an object")
            _validate_attempt(attempt, flow)
            if attempt["ordinal"] != ordinal:
                raise FlowDeliveryError(f"{identity} live attempt ordinals are not contiguous")
        if flow["product_policy_status"] not in POLICY_STATUSES:
            raise FlowDeliveryError(f"unknown flow product-policy status: {flow['product_policy_status']}")
        if flow["status"] == "ready" and flow["product_policy_status"] in {
            "unresolved_user_decision",
            "prohibited",
        }:
            raise FlowDeliveryError(f"{identity} cannot be ready under unresolved/prohibited policy")
        if flow["status"] == "needs_product_decision" and flow[
            "product_policy_status"
        ] != "unresolved_user_decision":
            raise FlowDeliveryError(f"{identity} needs_product_decision status is inconsistent")
        if not isinstance(flow["blocked_reason"], str):
            raise FlowDeliveryError(f"{identity}.blocked_reason must be a string")
        if flow["status"] in {"blocked", "needs_product_decision"} and not flow[
            "blocked_reason"
        ].strip():
            raise FlowDeliveryError(f"{identity} requires blocked_reason")
        if flow["last_completed_stage"] is not None and flow["last_completed_stage"] not in STAGES:
            raise FlowDeliveryError(f"{identity} has unknown last_completed_stage")
        if flow["last_commit"] is not None:
            _require_nonempty_string(flow["last_commit"], f"{identity}.last_commit")
    if len(active) > 1:
        raise FlowDeliveryError("exactly one or zero active development flows is allowed")
    active_flow_id = payload.get("active_flow_id")
    if active_flow_id is not None and active_flow_id not in identities:
        raise FlowDeliveryError("active_flow_id names an unknown flow")
    if active_flow_id != (active[0] if active else None):
        raise FlowDeliveryError("active_flow_id does not match active flow status")
    for identity, flow in by_id.items():
        for dependency in flow["dependencies"]:
            if dependency not in by_id or dependency == identity:
                raise FlowDeliveryError(f"{identity} has an invalid dependency: {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identity: str) -> None:
        if identity in visiting:
            raise FlowDeliveryError("delivery queue contains a dependency cycle")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in by_id[identity]["dependencies"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in by_id:
        visit(identity)


def validate_lease(payload: Mapping[str, Any]) -> None:
    missing = REQUIRED_LEASE_FIELDS - set(payload)
    if missing:
        raise FlowDeliveryError(f"lease missing fields: {sorted(missing)}")
    if payload.get("schema_version") != 2 or payload.get("workflow") != "pns-flow-delivery":
        raise FlowDeliveryError("unsupported development lease")
    if payload.get("lease_mode") not in {"delivery", "ide_native_canary"}:
        raise FlowDeliveryError("unknown development lease mode")
    for field in (
        "owner",
        "host",
        "process_or_session_identity",
        "acquisition_timestamp",
        "heartbeat_timestamp",
        "acquired_repository_head",
        "expected_repository_head",
        "observed_repository_head",
        "acquired_working_tree_fingerprint",
        "expected_working_tree_fingerprint",
    ):
        _require_nonempty_string(payload[field], f"lease.{field}")
    _parse_timestamp(payload["acquisition_timestamp"], "lease.acquisition_timestamp")
    _parse_timestamp(payload["heartbeat_timestamp"], "lease.heartbeat_timestamp")
    if payload["bound_parent_conversation_id"] is not None and (
        not isinstance(payload["bound_parent_conversation_id"], str)
        or not payload["bound_parent_conversation_id"].strip()
    ):
        raise FlowDeliveryError("lease.bound_parent_conversation_id must be null or non-empty")
    for field in ("active_flow", "safety_blocked_flow"):
        if not isinstance(payload[field], str):
            raise FlowDeliveryError(f"lease.{field} must be a string")
    if payload["active_stage"] is not None and payload["active_stage"] not in STAGES:
        raise FlowDeliveryError("lease has unknown active_stage")
    _parse_timestamp(payload["active_stage_entered_at"], "lease.active_stage_entered_at")
    if payload["runtime_ownership_state"] not in RUNTIME_OWNERSHIP_STATES:
        raise FlowDeliveryError("lease has unknown runtime ownership state")
    if payload["unresolved_action_state"] not in UNRESOLVED_ACTION_STATES:
        raise FlowDeliveryError("lease has unknown unresolved-action state")
    if type(payload["live_terminal_evidence"]) is not bool:
        raise FlowDeliveryError("lease.live_terminal_evidence must be boolean")
    for field in ("acquired_working_tree_snapshot", "expected_working_tree_snapshot"):
        if not isinstance(payload[field], dict):
            raise FlowDeliveryError(f"lease.{field} must be an object")
    _validate_string_list(payload["reviewed_attributable_paths"], "lease.reviewed_attributable_paths")
    if not isinstance(payload["validation_receipts"], list):
        raise FlowDeliveryError("lease.validation_receipts must be a list")
    if not isinstance(payload["subagent_invocation_receipts"], list):
        raise FlowDeliveryError("lease.subagent_invocation_receipts must be a list")
    if payload["reviewed_flow_commit"] is not None:
        _require_nonempty_string(payload["reviewed_flow_commit"], "lease.reviewed_flow_commit")
    gates = payload["gates"]
    if not isinstance(gates, dict) or set(gates) != {"implementation_parent_reviewed"}:
        raise FlowDeliveryError("lease.gates schema mismatch")
    if type(gates["implementation_parent_reviewed"]) is not bool:
        raise FlowDeliveryError("lease.gates values must be boolean")
    if payload["lease_mode"] == "ide_native_canary" and (
        payload["active_flow"] != CANARY_FLOW_ID or payload["active_stage"] != "reconnaissance"
    ):
        raise FlowDeliveryError("IDE-native canary lease binding is invalid")


class FlowDeliveryController:
    def __init__(
        self,
        queue_path: Path = DEFAULT_QUEUE_PATH,
        policy_path: Path = DEFAULT_POLICY_PATH,
        lease_path: Path = DEFAULT_LEASE_PATH,
        writable_marker_path: Path = DEFAULT_WRITABLE_MARKER_PATH,
        routing_events_path: Path = DEFAULT_ROUTING_EVENTS_PATH,
    ) -> None:
        self.queue_path = queue_path
        self.policy_path = policy_path
        self.lease_path = lease_path
        self.writable_marker_path = writable_marker_path
        self.routing_events_path = routing_events_path

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        queue = _read_json(self.queue_path)
        policy = _read_json(self.policy_path)
        validate_queue(queue)
        validate_policy(policy)
        return queue, policy

    def lease(self) -> dict[str, Any] | None:
        if not self.lease_path.exists():
            return None
        payload = _read_json(self.lease_path)
        validate_lease(payload)
        return payload

    @staticmethod
    def _flows(queue: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {flow["flow_id"]: flow for flow in queue["flows"]}

    @staticmethod
    def _git(arguments: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode:
            raise FlowDeliveryError(f"Git operation failed: {' '.join(arguments)}")
        return result

    @classmethod
    def _repo_head(cls) -> str:
        result = cls._git(["rev-parse", "HEAD"])
        return _require_nonempty_string(result.stdout.strip(), "repository HEAD")

    @classmethod
    def _working_tree_snapshot(cls) -> dict[str, dict[str, Any]]:
        result = cls._git(["status", "--porcelain=v1", "--untracked-files=all"])
        snapshot: dict[str, dict[str, Any]] = {}
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            status = line[:2]
            raw_path = line[3:]
            paths = raw_path.split(" -> ") if " -> " in raw_path else [raw_path]
            for raw in paths:
                path = raw.strip('"')
                candidate = REPO_ROOT / path
                try:
                    stat = candidate.stat()
                    size = stat.st_size if candidate.is_file() else None
                    modified_ns = stat.st_mtime_ns
                except OSError:
                    size = None
                    modified_ns = None
                snapshot[path.replace("\\", "/")] = {
                    "status": status,
                    "size": size,
                    "modified_ns": modified_ns,
                }
        return snapshot

    @staticmethod
    def _snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
        return _canonical_digest(snapshot)

    @classmethod
    def _working_tree_state(cls) -> tuple[dict[str, dict[str, Any]], str]:
        snapshot = cls._working_tree_snapshot()
        return snapshot, cls._snapshot_fingerprint(snapshot)

    @classmethod
    def _resolve_commit(cls, commit: str) -> str:
        _require_nonempty_string(commit, "commit")
        result = cls._git(["rev-parse", "--verify", f"{commit}^{{commit}}"], check=False)
        if result.returncode or not result.stdout.strip():
            raise FlowDeliveryError("commit is not a real Git commit")
        return result.stdout.strip()

    @classmethod
    def _commit_reachable(cls, commit: str) -> bool:
        return cls._git(["merge-base", "--is-ancestor", commit, "HEAD"], check=False).returncode == 0

    @classmethod
    def _commit_paths(cls, commit: str) -> set[str]:
        result = cls._git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
        return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}

    def _require_lease(self, owner: str) -> dict[str, Any]:
        lease = self.lease()
        if lease is None:
            raise FlowDeliveryError("development lease is not held")
        if lease["owner"] != owner:
            raise FlowDeliveryError("development lease is held by another owner")
        return lease

    def _assert_repository_state(self, lease: Mapping[str, Any]) -> None:
        observed_head = self._repo_head()
        if observed_head != lease["expected_repository_head"]:
            raise FlowDeliveryError("unexpected repository HEAD movement")
        _, fingerprint = self._working_tree_state()
        if fingerprint != lease["expected_working_tree_fingerprint"]:
            raise FlowDeliveryError("working tree differs from the reviewed attributable state")

    def _refresh_expected_worktree(self, lease: dict[str, Any]) -> None:
        snapshot, fingerprint = self._working_tree_state()
        lease["expected_working_tree_snapshot"] = snapshot
        lease["expected_working_tree_fingerprint"] = fingerprint

    @staticmethod
    def _attempts_terminal(queue: Mapping[str, Any]) -> bool:
        for flow in queue["flows"]:
            for attempt in flow["live_attempts"]:
                if attempt["finished_at"] is None or attempt["terminal_outcome"] not in TERMINAL_ATTEMPT_OUTCOMES:
                    return False
        return True

    def _assert_global_safety_clear(
        self,
        queue: Mapping[str, Any],
        lease: Mapping[str, Any],
    ) -> None:
        if lease["runtime_ownership_state"] not in {"none", "released"}:
            raise FlowDeliveryError("runtime ownership held/unknown blocks flow activation")
        if lease["unresolved_action_state"] != "clear":
            raise FlowDeliveryError("global unresolved-action gate is not clear")
        if lease["safety_blocked_flow"]:
            raise FlowDeliveryError("previous live work remains safety-blocked")
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("writable subagent marker remains unresolved")
        if not self._attempts_terminal(queue):
            raise FlowDeliveryError("a prior live attempt lacks terminal evidence")

    def _selection_blocked(
        self,
        queue: Mapping[str, Any],
        lease: Mapping[str, Any] | None,
    ) -> bool:
        if not self._attempts_terminal(queue):
            return True
        if lease is None:
            return False
        return (
            lease["runtime_ownership_state"] in {"held", "unknown"}
            or lease["unresolved_action_state"] != "clear"
            or bool(lease["safety_blocked_flow"])
            or self.writable_marker_path.exists()
        )

    def select_next(self, queue: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        if queue is None:
            queue, _ = self.load()
        by_id = self._flows(queue)
        active = [flow for flow in by_id.values() if flow["status"] == "active"]
        if active:
            return deepcopy(active[0])
        lease = self.lease()
        if self._selection_blocked(queue, lease):
            return None
        ready = [
            flow
            for flow in by_id.values()
            if flow["status"] == "ready"
            and flow["product_policy_status"] not in {"unresolved_user_decision", "prohibited"}
            and all(by_id[dependency]["status"] == "completed" for dependency in flow["dependencies"])
        ]
        return deepcopy(min(ready, key=lambda flow: (flow["priority"], flow["flow_id"]))) if ready else None

    def acquire(
        self,
        *,
        owner: str,
        session_identity: str,
        runtime_ownership_state: str,
        unresolved_action_state: str = "unknown",
        ide_native_canary: bool = False,
    ) -> dict[str, Any]:
        _require_nonempty_string(owner, "owner")
        _require_nonempty_string(session_identity, "session_identity")
        if runtime_ownership_state not in RUNTIME_OWNERSHIP_STATES:
            raise FlowDeliveryError("unknown runtime ownership state")
        if unresolved_action_state not in UNRESOLVED_ACTION_STATES:
            raise FlowDeliveryError("unknown unresolved-action state")
        if self.lease_path.exists():
            raise FlowDeliveryError(f"development lease conflict: {self.lease()['owner']}")
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("writable subagent marker remains unresolved")
        queue, _ = self.load()
        if ide_native_canary:
            if queue.get("active_flow_id"):
                raise FlowDeliveryError("IDE-native canary requires an inactive queue")
            if runtime_ownership_state not in {"none", "released"} or unresolved_action_state != "clear":
                raise FlowDeliveryError("IDE-native canary requires released runtime and clear actions")
        now = utc_now()
        head = self._repo_head()
        snapshot, fingerprint = self._working_tree_state()
        active_flow = CANARY_FLOW_ID if ide_native_canary else (queue.get("active_flow_id") or "")
        active_stage = (
            "reconnaissance"
            if ide_native_canary
            else (
                self._flows(queue)[queue["active_flow_id"]]["last_completed_stage"]
                if queue.get("active_flow_id")
                else None
            )
        )
        payload = {
            "schema_version": 2,
            "workflow": "pns-flow-delivery",
            "lease_mode": "ide_native_canary" if ide_native_canary else "delivery",
            "owner": owner,
            "host": socket.gethostname(),
            "process_or_session_identity": session_identity,
            "process_id": os.getpid(),
            "bound_parent_conversation_id": None,
            "acquisition_timestamp": now,
            "heartbeat_timestamp": now,
            "acquired_repository_head": head,
            "expected_repository_head": head,
            "observed_repository_head": head,
            "acquired_working_tree_fingerprint": fingerprint,
            "expected_working_tree_fingerprint": fingerprint,
            "acquired_working_tree_snapshot": snapshot,
            "expected_working_tree_snapshot": snapshot,
            "reviewed_attributable_paths": [],
            "active_flow": active_flow,
            "active_stage": active_stage,
            "active_stage_entered_at": now,
            "runtime_ownership_state": runtime_ownership_state,
            "unresolved_action_state": unresolved_action_state,
            "live_terminal_evidence": False,
            "safety_blocked_flow": "",
            "validation_receipts": [],
            "subagent_invocation_receipts": [],
            "reviewed_flow_commit": None,
            "gates": {"implementation_parent_reviewed": False},
        }
        validate_lease(payload)
        _atomic_write_json(self.lease_path, payload)
        return payload

    def heartbeat(
        self,
        *,
        owner: str,
        session_identity: str | None = None,
        runtime_ownership_state: str | None = None,
        unresolved_action_state: str | None = None,
    ) -> dict[str, Any]:
        lease = self._require_lease(owner)
        if session_identity is not None and lease["process_or_session_identity"] != session_identity:
            raise FlowDeliveryError("lease session identity mismatch")
        self._assert_repository_state(lease)
        if runtime_ownership_state is not None:
            if runtime_ownership_state not in RUNTIME_OWNERSHIP_STATES:
                raise FlowDeliveryError("unknown runtime ownership state")
            lease["runtime_ownership_state"] = runtime_ownership_state
        if unresolved_action_state is not None:
            if unresolved_action_state not in UNRESOLVED_ACTION_STATES:
                raise FlowDeliveryError("unknown unresolved-action state")
            lease["unresolved_action_state"] = unresolved_action_state
        lease["observed_repository_head"] = self._repo_head()
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return lease

    def activate(self, *, owner: str, flow_id: str | None = None) -> dict[str, Any]:
        lease = self._require_lease(owner)
        if lease["lease_mode"] != "delivery":
            raise FlowDeliveryError("IDE-native canary lease cannot activate a flow")
        self._assert_repository_state(lease)
        queue, _ = self.load()
        self._assert_global_safety_clear(queue, lease)
        selected = self.select_next(queue)
        if selected is None:
            raise FlowDeliveryError("no ready development flow")
        if flow_id is not None and selected["flow_id"] != flow_id:
            raise FlowDeliveryError("requested flow is not the deterministic next flow")
        flow = self._flows(queue)[selected["flow_id"]]
        if flow["status"] == "ready":
            flow["status"] = "active"
            flow["last_completed_stage"] = "selected"
            queue["active_flow_id"] = flow["flow_id"]
            validate_queue(queue)
            _atomic_write_json(self.queue_path, queue)
        lease["active_flow"] = flow["flow_id"]
        lease["active_stage"] = flow["last_completed_stage"]
        now = utc_now()
        lease["active_stage_entered_at"] = now
        lease["heartbeat_timestamp"] = now
        self._refresh_expected_worktree(lease)
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def review_worktree(self, *, owner: str, paths: Sequence[str]) -> dict[str, Any]:
        lease = self._require_lease(owner)
        if lease["lease_mode"] != "delivery" or not lease["active_flow"]:
            raise FlowDeliveryError("reviewed worktree requires an active delivery flow")
        if self._repo_head() != lease["expected_repository_head"]:
            raise FlowDeliveryError("unexpected repository HEAD movement")
        queue, _ = self.load()
        flow = self._flows(queue).get(lease["active_flow"])
        if not flow:
            raise FlowDeliveryError("active flow is unavailable")
        allowed = {
            *(path.replace("\\", "/") for path in flow["implementation_entrypoints"]),
            *(path.replace("\\", "/") for path in flow["focused_tests"]),
            "tasks/flow_delivery_queue.json",
        }
        reviewed = {path.replace("\\", "/") for path in paths}
        if not reviewed or not reviewed <= allowed:
            raise FlowDeliveryError("reviewed worktree contains paths outside the flow allowlist")
        current_snapshot, fingerprint = self._working_tree_state()
        acquired_snapshot = lease["acquired_working_tree_snapshot"]
        changed_since_acquisition = {
            path
            for path in set(acquired_snapshot) | set(current_snapshot)
            if acquired_snapshot.get(path) != current_snapshot.get(path)
        }
        if not changed_since_acquisition <= reviewed:
            raise FlowDeliveryError("unrelated working-tree mutation is not attributable")
        lease["reviewed_attributable_paths"] = sorted(reviewed)
        lease["expected_working_tree_snapshot"] = current_snapshot
        lease["expected_working_tree_fingerprint"] = fingerprint
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return {
            "reviewed_attributable_paths": lease["reviewed_attributable_paths"],
            "working_tree_fingerprint": fingerprint,
        }

    def _optional_hook_cross_check(
        self,
        *,
        lease: Mapping[str, Any],
        subagent_id: str,
        expected: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            lines = self.routing_events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return {
                "required": False,
                "status": "not_emitted",
                "source": "optional_subagent_start_hook",
            }
        except (OSError, UnicodeError) as exc:
            raise FlowDeliveryError("optional hook routing evidence is unreadable") from exc
        acquired_at = _parse_timestamp(
            lease["acquisition_timestamp"],
            "lease.acquisition_timestamp",
        )
        current: list[tuple[datetime, dict[str, Any]]] = []
        for ordinal, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FlowDeliveryError(
                    f"optional hook routing event line {ordinal} is invalid"
                ) from exc
            if not isinstance(event, dict):
                raise FlowDeliveryError(
                    f"optional hook routing event line {ordinal} must be an object"
                )
            event_at = _parse_timestamp(event.get("timestamp"), "hook event timestamp")
            if event_at > datetime.now(timezone.utc):
                raise FlowDeliveryError("optional hook routing event is from the future")
            if event_at >= acquired_at:
                current.append((event_at, event))
        if not current:
            return {
                "required": False,
                "status": "not_emitted",
                "source": "optional_subagent_start_hook",
            }
        matching = [item for item in current if item[1].get("subagent_id") == subagent_id]
        if not matching:
            raise FlowDeliveryError(
                "current optional hook event does not match the returned native subagent"
            )
        _, event = max(matching, key=lambda item: item[0])
        bindings = {
            "lease_owner": lease["owner"],
            "lease_session": lease["process_or_session_identity"],
            "lease_acquisition_timestamp": lease["acquisition_timestamp"],
            "parent_conversation_id": expected["parent_conversation_id"],
            "active_flow": expected["active_flow"],
            "active_stage": expected["active_stage"],
            "subagent_type": expected["custom_agent"],
        }
        for field, value in bindings.items():
            observed = event.get(field)
            if observed is not None and observed != value:
                raise FlowDeliveryError(f"optional hook event {field} mismatch")
        observed_model = event.get("subagent_model") or event.get("model")
        if observed_model is not None and observed_model != expected["requested_model"]:
            raise FlowDeliveryError("optional hook event model mismatch")
        return {
            "required": False,
            "status": "matched",
            "source": "optional_subagent_start_hook",
            "event_digest": _canonical_digest(event),
        }

    def record_subagent_invocation(
        self,
        *,
        owner: str,
        active_flow: str,
        active_stage: str,
        lease_session: str,
        parent_conversation_id: str,
        custom_agent: str,
        requested_model: str,
        subagent_id: str,
        is_background: bool,
        terminal_outcome: str,
        timestamp: str,
        repository_head: str,
    ) -> dict[str, Any]:
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        for value, field in (
            (active_flow, "active_flow"),
            (active_stage, "active_stage"),
            (lease_session, "lease_session"),
            (parent_conversation_id, "parent_conversation_id"),
            (custom_agent, "custom_agent"),
            (requested_model, "requested_model"),
            (subagent_id, "subagent_id"),
            (terminal_outcome, "terminal_outcome"),
            (repository_head, "repository_head"),
        ):
            _require_nonempty_string(value, f"invocation.{field}")
        if custom_agent not in ALLOWED_SUBAGENTS:
            raise FlowDeliveryError("native invocation did not use an allowed custom agent")
        if STAGE_AGENTS.get(active_stage) != custom_agent:
            raise FlowDeliveryError("native invocation agent does not match the active stage")
        if requested_model != EXPECTED_SUBAGENT_MODEL:
            raise FlowDeliveryError("native invocation did not request Grok 4.5 High")
        if type(is_background) is not bool or is_background:
            raise FlowDeliveryError("native invocation must be foreground")
        if terminal_outcome not in SUBAGENT_TERMINAL_OUTCOMES:
            raise FlowDeliveryError("native invocation outcome is not terminal")
        if lease["process_or_session_identity"] != lease_session:
            raise FlowDeliveryError("native invocation belongs to another lease session")
        if lease["active_flow"] != active_flow:
            raise FlowDeliveryError("native invocation belongs to another flow")
        if lease["active_stage"] != active_stage:
            raise FlowDeliveryError("native invocation belongs to another stage")
        if lease["expected_repository_head"] != repository_head:
            raise FlowDeliveryError("native invocation belongs to another HEAD")
        receipt_at = _parse_timestamp(timestamp, "invocation.timestamp")
        earliest = max(
            _parse_timestamp(
                lease["acquisition_timestamp"],
                "lease.acquisition_timestamp",
            ),
            _parse_timestamp(
                lease["active_stage_entered_at"],
                "lease.active_stage_entered_at",
            ),
        )
        if receipt_at < earliest or receipt_at > datetime.now(timezone.utc):
            raise FlowDeliveryError("native invocation timestamp is outside the active stage")
        bound_parent = lease["bound_parent_conversation_id"]
        if bound_parent is not None and bound_parent != parent_conversation_id:
            raise FlowDeliveryError("native invocation belongs to another parent conversation")
        if any(
            item.get("subagent_id") == subagent_id
            for item in lease["subagent_invocation_receipts"]
        ):
            raise FlowDeliveryError("duplicate native invocation receipt")
        unsigned: dict[str, Any] = {
            "schema_version": 1,
            "active_flow": active_flow,
            "active_stage": active_stage,
            "lease_owner": lease["owner"],
            "lease_session": lease_session,
            "parent_conversation_id": parent_conversation_id,
            "custom_agent": custom_agent,
            "requested_model": requested_model,
            "subagent_id": subagent_id,
            "is_background": is_background,
            "terminal_outcome": terminal_outcome,
            "timestamp": timestamp,
            "repository_head": repository_head,
        }
        unsigned["hook_cross_check"] = self._optional_hook_cross_check(
            lease=lease,
            subagent_id=subagent_id,
            expected=unsigned,
        )
        receipt = {**unsigned, "receipt_digest": _canonical_digest(unsigned)}
        lease["bound_parent_conversation_id"] = parent_conversation_id
        lease["subagent_invocation_receipts"].append(receipt)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(receipt)

    @staticmethod
    def _require_subagent_invocation(lease: Mapping[str, Any], stage: str) -> None:
        expected_agent = STAGE_AGENTS.get(stage)
        if expected_agent is None:
            return
        entered_at = _parse_timestamp(
            lease["active_stage_entered_at"],
            "lease.active_stage_entered_at",
        )
        valid = [
            receipt
            for receipt in lease["subagent_invocation_receipts"]
            if receipt.get("active_flow") == lease["active_flow"]
            and receipt.get("active_stage") == stage
            and receipt.get("lease_owner") == lease["owner"]
            and receipt.get("lease_session") == lease["process_or_session_identity"]
            and receipt.get("parent_conversation_id") == lease["bound_parent_conversation_id"]
            and receipt.get("custom_agent") == expected_agent
            and receipt.get("requested_model") == EXPECTED_SUBAGENT_MODEL
            and receipt.get("is_background") is False
            and receipt.get("terminal_outcome") == "completed"
            and receipt.get("repository_head") == lease["expected_repository_head"]
            and receipt.get("receipt_digest")
            == _canonical_digest(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_digest"
                }
            )
            and isinstance(receipt.get("hook_cross_check"), dict)
            and receipt["hook_cross_check"].get("status") in {"matched", "not_emitted"}
            and receipt["hook_cross_check"].get("required") is False
            and _parse_timestamp(
                receipt.get("timestamp"),
                "invocation receipt timestamp",
            )
            >= entered_at
        ]
        if not valid:
            raise FlowDeliveryError(
                f"{stage} lacks a valid native subagent invocation receipt"
            )

    def record_validation_receipt(self, *, owner: str, receipt_path: Path) -> dict[str, Any]:
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        receipt = _read_json(receipt_path)
        required = {
            "schema_version",
            "active_flow",
            "repository_head",
            "working_tree_fingerprint",
            "delivery_stage",
            "validation_profile",
            "command_or_profile",
            "exit_code",
            "timestamp",
            "test_count",
            "artifact_paths",
            "receipt_digest",
        }
        if set(receipt) != required or receipt.get("schema_version") != 1:
            raise FlowDeliveryError("validation receipt schema mismatch")
        if receipt["active_flow"] != lease["active_flow"]:
            raise FlowDeliveryError("validation receipt belongs to another flow")
        if receipt["repository_head"] != lease["expected_repository_head"]:
            raise FlowDeliveryError("validation receipt belongs to another HEAD")
        if receipt["working_tree_fingerprint"] != lease["expected_working_tree_fingerprint"]:
            raise FlowDeliveryError("validation receipt belongs to another working tree")
        if receipt["delivery_stage"] not in REQUIRED_RECEIPTS_BY_STAGE:
            raise FlowDeliveryError("validation receipt has an unsupported delivery stage")
        if receipt["validation_profile"] not in VALIDATION_PROFILES:
            raise FlowDeliveryError("validation receipt has an unsupported profile")
        _require_nonempty_string(receipt["command_or_profile"], "receipt.command_or_profile")
        if type(receipt["exit_code"]) is not int or receipt["exit_code"] != 0:
            raise FlowDeliveryError("validation receipt does not prove success")
        receipt_at = _parse_timestamp(receipt["timestamp"], "receipt.timestamp")
        if receipt_at < _parse_timestamp(
            lease["acquisition_timestamp"],
            "lease.acquisition_timestamp",
        ) or receipt_at > datetime.now(timezone.utc):
            raise FlowDeliveryError("validation receipt timestamp is outside the active lease")
        if receipt["test_count"] is not None and (
            type(receipt["test_count"]) is not int or receipt["test_count"] < 0
        ):
            raise FlowDeliveryError("validation receipt test_count is invalid")
        _validate_string_list(receipt["artifact_paths"], "receipt.artifact_paths")
        unsigned = dict(receipt)
        digest = unsigned.pop("receipt_digest")
        if digest != _canonical_digest(unsigned):
            raise FlowDeliveryError("validation receipt digest mismatch")
        if digest not in {item["receipt_digest"] for item in lease["validation_receipts"]}:
            lease["validation_receipts"].append(receipt)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(receipt)

    @staticmethod
    def _require_receipts(lease: Mapping[str, Any], stage: str) -> None:
        required = REQUIRED_RECEIPTS_BY_STAGE.get(stage, set())
        present = {
            receipt["validation_profile"]
            for receipt in lease["validation_receipts"]
            if receipt["delivery_stage"] == stage
            and receipt["active_flow"] == lease["active_flow"]
            and receipt["repository_head"] == lease["expected_repository_head"]
            and receipt["working_tree_fingerprint"] == lease["expected_working_tree_fingerprint"]
        }
        if not required <= present:
            raise FlowDeliveryError(f"{stage} lacks bound validation receipts")

    def record_stage(
        self,
        *,
        owner: str,
        stage: str,
        parent_reviewed: bool = False,
    ) -> dict[str, Any]:
        if stage not in STAGES:
            raise FlowDeliveryError(f"unknown delivery stage: {stage}")
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("queue and lease do not identify the same active flow")
        flow = self._flows(queue)[active_id]
        current = flow["last_completed_stage"]
        if lease["active_stage"] != current:
            raise FlowDeliveryError("queue and lease stages do not match")
        if current not in STAGES or stage not in TRANSITIONS[current]:
            raise FlowDeliveryError(f"invalid stage transition: {current} -> {stage}")
        self._require_subagent_invocation(lease, current)
        if current == "full_validation" and flow["requires_bluestacks_live"] and stage != "live_preflight":
            raise FlowDeliveryError("live-required flow cannot bypass live preflight")
        if parent_reviewed:
            lease["gates"]["implementation_parent_reviewed"] = True
        if stage == "implementation_review" and not lease["gates"]["implementation_parent_reviewed"]:
            raise FlowDeliveryError("implementation review requires parent acceptance")
        self._require_receipts(lease, stage)
        if stage in {"live_preflight", "live_execution"}:
            if not flow["requires_bluestacks_live"] or flow["maximum_live_attempts"] <= 0:
                raise FlowDeliveryError("flow has no live validation authority")
            if lease["runtime_ownership_state"] != "held":
                raise FlowDeliveryError("live stages require parent-held runtime ownership")
            if lease["unresolved_action_state"] != "clear":
                raise FlowDeliveryError("global unresolved-action gate is not clear")
            if self.writable_marker_path.exists():
                raise FlowDeliveryError("writable subagent marker remains unresolved")
            if flow["product_policy_status"] not in LIVE_POLICY_STATUSES:
                raise FlowDeliveryError("live policy is not explicit")
            _require_nonempty_string(flow["evidence_validator"], "evidence_validator")
        flow["last_completed_stage"] = stage
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        lease["active_stage"] = stage
        now = utc_now()
        lease["active_stage_entered_at"] = now
        lease["heartbeat_timestamp"] = now
        self._refresh_expected_worktree(lease)
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def begin_live_attempt(self, *, owner: str, diagnosis: str = "") -> dict[str, Any]:
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if (
            not active_id
            or lease["active_flow"] != active_id
            or lease["active_stage"] != "live_execution"
        ):
            raise FlowDeliveryError("live attempt requires the active live_execution flow")
        if lease["runtime_ownership_state"] != "held":
            raise FlowDeliveryError("live attempt requires parent-held runtime ownership")
        if lease["unresolved_action_state"] != "clear":
            raise FlowDeliveryError("global unresolved-action gate is not clear")
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("writable subagent marker remains unresolved")
        flow = self._flows(queue)[active_id]
        attempts = flow["live_attempts"]
        if flow["live_attempt_count"] >= flow["maximum_live_attempts"]:
            raise FlowDeliveryError("maximum live attempts exhausted")
        if attempts:
            previous = attempts[-1]
            if previous["finished_at"] is None or previous["terminal_outcome"] not in TERMINAL_ATTEMPT_OUTCOMES:
                raise FlowDeliveryError("previous live attempt is not terminal")
            if not diagnosis.strip():
                raise FlowDeliveryError("live retry requires a concrete diagnosis")
        attempt = {
            "ordinal": len(attempts) + 1,
            "active_flow": active_id,
            "lease_owner": lease["owner"],
            "lease_session": lease["process_or_session_identity"],
            "repository_head": lease["expected_repository_head"],
            "started_at": utc_now(),
            "finished_at": None,
            "session_directory": None,
            "terminal_outcome": None,
            "diagnosis": diagnosis or "initial authorized attempt",
        }
        attempts.append(attempt)
        flow["live_attempt_count"] = len(attempts)
        lease["live_terminal_evidence"] = False
        _atomic_write_json(self.queue_path, queue)
        self._refresh_expected_worktree(lease)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(attempt)

    def finish_live_attempt(
        self,
        *,
        owner: str,
        outcome: str,
        diagnosis: str = "",
        session_directory: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in ATTEMPT_OUTCOMES:
            raise FlowDeliveryError("unknown live-attempt outcome")
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("no active flow owns the live attempt")
        flow = self._flows(queue)[active_id]
        if not flow["live_attempts"] or flow["live_attempts"][-1]["finished_at"] is not None:
            raise FlowDeliveryError("no unfinished live attempt exists")
        if outcome != "completed" and not diagnosis.strip():
            raise FlowDeliveryError("non-successful live attempt requires a diagnosis")
        attempt = flow["live_attempts"][-1]
        attempt["finished_at"] = utc_now()
        attempt["terminal_outcome"] = outcome
        attempt["diagnosis"] = diagnosis or attempt["diagnosis"]
        attempt["session_directory"] = session_directory
        lease["live_terminal_evidence"] = outcome in TERMINAL_ATTEMPT_OUTCOMES
        if outcome == "unresolved":
            lease["unresolved_action_state"] = "unresolved"
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        self._refresh_expected_worktree(lease)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(attempt)

    def record_commit(self, *, owner: str, commit: str) -> dict[str, Any]:
        lease = self._require_lease(owner)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id or lease["active_stage"] != "commit":
            raise FlowDeliveryError("reviewed commit transition requires the active commit stage")
        resolved = self._resolve_commit(commit)
        current_head = self._repo_head()
        if current_head != resolved:
            raise FlowDeliveryError("reviewed flow commit must be current HEAD")
        parent = self._git(["rev-parse", f"{resolved}^"]).stdout.strip()
        if parent != lease["expected_repository_head"]:
            raise FlowDeliveryError("reviewed flow commit does not descend from the expected HEAD")
        if not self._commit_reachable(resolved):
            raise FlowDeliveryError("reviewed flow commit is not reachable from the current branch")
        allowed = set(lease["reviewed_attributable_paths"]) | {"tasks/flow_delivery_queue.json"}
        paths = self._commit_paths(resolved)
        if not paths or not paths <= allowed:
            raise FlowDeliveryError("reviewed flow commit contains unrelated paths")
        flow = self._flows(queue)[active_id]
        if not paths.intersection(set(flow["implementation_entrypoints"]) | set(flow["focused_tests"])):
            raise FlowDeliveryError("commit does not contain the reviewed flow implementation")
        lease["reviewed_flow_commit"] = resolved
        lease["expected_repository_head"] = resolved
        lease["observed_repository_head"] = resolved
        self._refresh_expected_worktree(lease)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return {"commit": resolved, "paths": sorted(paths)}

    def complete(self, *, owner: str, commit: str) -> dict[str, Any]:
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("no matching active flow to complete")
        flow = self._flows(queue)[active_id]
        resolved = self._resolve_commit(commit)
        if flow["last_completed_stage"] != "commit" or lease["active_stage"] != "commit":
            raise FlowDeliveryError("flow must reach the commit stage first")
        if lease["reviewed_flow_commit"] != resolved or self._repo_head() != resolved:
            raise FlowDeliveryError("commit is not the dedicated reviewed flow commit")
        if not self._commit_reachable(resolved):
            raise FlowDeliveryError("reviewed flow commit is not reachable from the current branch")
        if lease["runtime_ownership_state"] not in {"none", "released"}:
            raise FlowDeliveryError("runtime ownership must be released before completion")
        if lease["unresolved_action_state"] != "clear":
            raise FlowDeliveryError("unresolved-action gate must be clear before completion")
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("writable subagent marker remains unresolved")
        if flow["live_attempts"]:
            last = flow["live_attempts"][-1]
            if last["finished_at"] is None or last["terminal_outcome"] not in TERMINAL_ATTEMPT_OUTCOMES:
                raise FlowDeliveryError("live attempt is not terminal")
        flow["status"] = "completed"
        flow["last_completed_stage"] = "completed"
        flow["last_commit"] = resolved
        flow["blocked_reason"] = ""
        queue["active_flow_id"] = None
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        lease["active_flow"] = ""
        lease["active_stage"] = "completed"
        now = utc_now()
        lease["active_stage_entered_at"] = now
        lease["heartbeat_timestamp"] = now
        self._refresh_expected_worktree(lease)
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def block(self, *, owner: str, reason: str) -> dict[str, Any]:
        _require_nonempty_string(reason, "reason")
        lease = self._require_lease(owner)
        self._assert_repository_state(lease)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("no matching active flow to block")
        flow = self._flows(queue)[active_id]
        live_touched = lease["active_stage"] in {
            "live_preflight",
            "live_execution",
            "evidence_review",
        } or bool(flow["live_attempts"])
        flow["status"] = "blocked"
        flow["last_completed_stage"] = "blocked"
        flow["blocked_reason"] = reason
        queue["active_flow_id"] = None
        _atomic_write_json(self.queue_path, queue)
        lease["active_stage"] = "blocked"
        lease["active_stage_entered_at"] = utc_now()
        safe_terminal = (
            lease["runtime_ownership_state"] in {"none", "released"}
            and lease["unresolved_action_state"] == "clear"
            and lease["live_terminal_evidence"]
            and self._attempts_terminal(queue)
            and not self.writable_marker_path.exists()
        )
        if live_touched and not safe_terminal:
            lease["safety_blocked_flow"] = active_id
        else:
            lease["active_flow"] = ""
            lease["safety_blocked_flow"] = ""
        self._refresh_expected_worktree(lease)
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def release(self, *, owner: str) -> dict[str, Any]:
        lease = self._require_lease(owner)
        queue, _ = self.load()
        self._assert_repository_state(lease)
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("cannot release with an unresolved writable marker")
        if lease["runtime_ownership_state"] not in {"none", "released"}:
            raise FlowDeliveryError("cannot release while runtime ownership is held or unknown")
        if lease["unresolved_action_state"] != "clear":
            raise FlowDeliveryError("cannot release while unresolved-action state is not clear")
        if lease["lease_mode"] == "delivery" and (
            queue.get("active_flow_id")
            or lease["active_flow"]
            or lease["safety_blocked_flow"]
        ):
            raise FlowDeliveryError("cannot release the development lease with active/blocked work")
        self.lease_path.unlink()
        return {"released": True, "owner": owner}

    def reconcile(
        self,
        *,
        terminal_evidence: bool,
        runtime_state: str,
        journal_state: str,
        consequential_state: str,
    ) -> dict[str, Any]:
        lease = self.lease()
        if lease is None:
            return {"reconciled": False, "reason": "no_lease"}
        if self.writable_marker_path.exists():
            raise FlowDeliveryError("stale lease cannot clear with an unresolved writable marker")
        if runtime_state != "released":
            raise FlowDeliveryError("stale lease cannot clear while runtime ownership is unknown/held")
        if journal_state != "resolved":
            raise FlowDeliveryError("stale lease cannot clear while journal state is unresolved")
        if consequential_state != "terminal":
            raise FlowDeliveryError("stale lease cannot clear with a possibly nonterminal action")
        if not terminal_evidence:
            raise FlowDeliveryError("stale lease reconciliation requires terminal evidence")
        self.lease_path.unlink()
        return {"reconciled": True, "prior_owner": lease["owner"]}

    def status(self) -> dict[str, Any]:
        queue, _ = self.load()
        counts = {status: 0 for status in sorted(QUEUE_STATUSES)}
        for flow in queue["flows"]:
            counts[flow["status"]] += 1
        selected = self.select_next(queue)
        lease = self.lease()
        try:
            queue_name = str(self.queue_path.relative_to(REPO_ROOT))
        except ValueError:
            queue_name = str(self.queue_path)
        return {
            "schema_version": 2,
            "queue": queue_name,
            "counts": counts,
            "active_flow": queue.get("active_flow_id"),
            "selected_flow": selected["flow_id"] if selected else None,
            "lease": (
                {
                    "owner": lease["owner"],
                    "lease_mode": lease["lease_mode"],
                    "active_flow": lease["active_flow"],
                    "active_stage": lease["active_stage"],
                    "runtime_ownership_state": lease["runtime_ownership_state"],
                    "unresolved_action_state": lease["unresolved_action_state"],
                    "safety_blocked_flow": lease["safety_blocked_flow"],
                }
                if lease
                else None
            ),
        }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH)
    root.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    root.add_argument("--lease", type=Path, default=DEFAULT_LEASE_PATH)
    root.add_argument("--writable-marker", type=Path, default=DEFAULT_WRITABLE_MARKER_PATH)
    root.add_argument("--routing-events", type=Path, default=DEFAULT_ROUTING_EVENTS_PATH)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("status", "validate", "select-next"):
        sub.add_parser(command)
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--owner", required=True)
    acquire.add_argument("--session-id", required=True)
    acquire.add_argument("--runtime-ownership-state", choices=sorted(RUNTIME_OWNERSHIP_STATES), default="none")
    acquire.add_argument("--unresolved-action-state", choices=sorted(UNRESOLVED_ACTION_STATES), default="unknown")
    acquire.add_argument("--ide-native-canary", action="store_true")
    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--owner", required=True)
    heartbeat.add_argument("--session-id")
    heartbeat.add_argument("--runtime-ownership-state", choices=sorted(RUNTIME_OWNERSHIP_STATES))
    heartbeat.add_argument("--unresolved-action-state", choices=sorted(UNRESOLVED_ACTION_STATES))
    activate = sub.add_parser("activate")
    activate.add_argument("--owner", required=True)
    activate.add_argument("--flow-id")
    worktree = sub.add_parser("review-worktree")
    worktree.add_argument("--owner", required=True)
    worktree.add_argument("--path", action="append", required=True)
    invocation = sub.add_parser("record-subagent-invocation")
    invocation.add_argument("--owner", required=True)
    invocation.add_argument("--active-flow", required=True)
    invocation.add_argument("--active-stage", required=True, choices=STAGES)
    invocation.add_argument("--lease-session-id", required=True)
    invocation.add_argument("--parent-conversation-id", required=True)
    invocation.add_argument("--custom-agent", required=True)
    invocation.add_argument("--requested-model", required=True)
    invocation.add_argument("--subagent-id", required=True)
    invocation.add_argument("--is-background", required=True, choices=("false", "true"))
    invocation.add_argument("--terminal-outcome", required=True)
    invocation.add_argument("--timestamp", required=True)
    invocation.add_argument("--repository-head", required=True)
    receipt = sub.add_parser("record-validation")
    receipt.add_argument("--owner", required=True)
    receipt.add_argument("--receipt", type=Path, required=True)
    stage = sub.add_parser("record-stage")
    stage.add_argument("--owner", required=True)
    stage.add_argument("--stage", required=True, choices=STAGES)
    stage.add_argument("--parent-reviewed", action="store_true")
    begin = sub.add_parser("begin-live-attempt")
    begin.add_argument("--owner", required=True)
    begin.add_argument("--diagnosis", default="")
    finish = sub.add_parser("finish-live-attempt")
    finish.add_argument("--owner", required=True)
    finish.add_argument("--outcome", required=True, choices=sorted(ATTEMPT_OUTCOMES))
    finish.add_argument("--diagnosis", default="")
    finish.add_argument("--session-directory")
    commit = sub.add_parser("record-commit")
    commit.add_argument("--owner", required=True)
    commit.add_argument("--commit", required=True)
    complete = sub.add_parser("complete")
    complete.add_argument("--owner", required=True)
    complete.add_argument("--commit", required=True)
    block = sub.add_parser("block")
    block.add_argument("--owner", required=True)
    block.add_argument("--reason", required=True)
    release = sub.add_parser("release")
    release.add_argument("--owner", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--terminal-evidence", action="store_true")
    reconcile.add_argument("--runtime-state", required=True, choices=sorted(RUNTIME_OWNERSHIP_STATES))
    reconcile.add_argument("--journal-state", required=True, choices=("resolved", "unresolved", "unknown"))
    reconcile.add_argument("--consequential-state", required=True, choices=("terminal", "nonterminal", "unknown"))
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    controller = FlowDeliveryController(
        args.queue,
        args.policy,
        args.lease,
        args.writable_marker,
        args.routing_events,
    )
    try:
        if args.command == "status":
            result = controller.status()
        elif args.command == "validate":
            controller.load()
            controller.lease()
            result = {"valid": True}
        elif args.command == "select-next":
            result = {"flow": controller.select_next()}
        elif args.command == "acquire":
            result = controller.acquire(
                owner=args.owner,
                session_identity=args.session_id,
                runtime_ownership_state=args.runtime_ownership_state,
                unresolved_action_state=args.unresolved_action_state,
                ide_native_canary=args.ide_native_canary,
            )
        elif args.command == "heartbeat":
            result = controller.heartbeat(
                owner=args.owner,
                session_identity=args.session_id,
                runtime_ownership_state=args.runtime_ownership_state,
                unresolved_action_state=args.unresolved_action_state,
            )
        elif args.command == "activate":
            result = controller.activate(owner=args.owner, flow_id=args.flow_id)
        elif args.command == "review-worktree":
            result = controller.review_worktree(owner=args.owner, paths=args.path)
        elif args.command == "record-subagent-invocation":
            result = controller.record_subagent_invocation(
                owner=args.owner,
                active_flow=args.active_flow,
                active_stage=args.active_stage,
                lease_session=args.lease_session_id,
                parent_conversation_id=args.parent_conversation_id,
                custom_agent=args.custom_agent,
                requested_model=args.requested_model,
                subagent_id=args.subagent_id,
                is_background=args.is_background == "true",
                terminal_outcome=args.terminal_outcome,
                timestamp=args.timestamp,
                repository_head=args.repository_head,
            )
        elif args.command == "record-validation":
            result = controller.record_validation_receipt(owner=args.owner, receipt_path=args.receipt)
        elif args.command == "record-stage":
            result = controller.record_stage(
                owner=args.owner,
                stage=args.stage,
                parent_reviewed=args.parent_reviewed,
            )
        elif args.command == "begin-live-attempt":
            result = controller.begin_live_attempt(owner=args.owner, diagnosis=args.diagnosis)
        elif args.command == "finish-live-attempt":
            result = controller.finish_live_attempt(
                owner=args.owner,
                outcome=args.outcome,
                diagnosis=args.diagnosis,
                session_directory=args.session_directory,
            )
        elif args.command == "record-commit":
            result = controller.record_commit(owner=args.owner, commit=args.commit)
        elif args.command == "complete":
            result = controller.complete(owner=args.owner, commit=args.commit)
        elif args.command == "block":
            result = controller.block(owner=args.owner, reason=args.reason)
        elif args.command == "release":
            result = controller.release(owner=args.owner)
        elif args.command == "reconcile":
            result = controller.reconcile(
                terminal_evidence=args.terminal_evidence,
                runtime_state=args.runtime_state,
                journal_state=args.journal_state,
                consequential_state=args.consequential_state,
            )
        else:
            raise FlowDeliveryError("unknown command")
    except FlowDeliveryError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
