#!/usr/bin/env python3
"""Atomic controller for the serial development-flow delivery queue.

This controller selects development work only. It never issues runtime input, mutates the gameplay
scheduler, or changes SafetyStore action results.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE_PATH = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
DEFAULT_POLICY_PATH = REPO_ROOT / "tasks" / "flow_delivery_product_policy.json"
DEFAULT_LEASE_PATH = REPO_ROOT / ".local-orchestrator" / "flow-delivery-lease.json"

QUEUE_STATUSES = {
    "ready",
    "active",
    "blocked",
    "completed",
    "needs_product_decision",
}
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
LIVE_POLICY_STATUSES = {
    "navigation_only_validation",
    "supervised_consequential_validation",
}
RUNTIME_OWNERSHIP_STATES = {"none", "released", "held", "unknown"}
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
    "owner",
    "host",
    "process_or_session_identity",
    "acquisition_timestamp",
    "heartbeat_timestamp",
    "repository_head",
    "active_flow",
    "active_stage",
    "runtime_ownership_state",
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
    """Raised when queue, stage, or lease policy fails closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
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
        _require_nonempty_string(policy.get("scope"), "policy.scope")
        _require_nonempty_string(policy.get("decision"), "policy.decision")
        _require_nonempty_string(policy.get("source"), "policy.source")
        if policy.get("status") not in POLICY_STATUSES:
            raise FlowDeliveryError(f"unknown product-policy status: {policy.get('status')}")


def validate_queue(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != 1:
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
        if (
            not flow["requires_bluestacks_live"]
            and flow["maximum_live_attempts"] != 0
        ):
            raise FlowDeliveryError(f"{identity} forbids live attempts but has a nonzero limit")
        if flow["product_policy_status"] not in POLICY_STATUSES:
            raise FlowDeliveryError(
                f"unknown flow product-policy status: {flow['product_policy_status']}"
            )
        if flow["status"] == "ready" and flow["product_policy_status"] in {
            "unresolved_user_decision",
            "prohibited",
        }:
            raise FlowDeliveryError(f"{identity} cannot be ready under unresolved/prohibited policy")
        if (
            flow["status"] == "needs_product_decision"
            and flow["product_policy_status"] != "unresolved_user_decision"
        ):
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
    expected_active = active[0] if active else None
    if active_flow_id != expected_active:
        raise FlowDeliveryError("active_flow_id does not match active flow status")
    for identity, flow in by_id.items():
        for dependency in flow["dependencies"]:
            if dependency not in by_id:
                raise FlowDeliveryError(f"{identity} has unknown dependency: {dependency}")
            if dependency == identity:
                raise FlowDeliveryError(f"{identity} cannot depend on itself")

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
    for field in (
        "owner",
        "host",
        "process_or_session_identity",
        "acquisition_timestamp",
        "heartbeat_timestamp",
        "repository_head",
    ):
        _require_nonempty_string(payload[field], f"lease.{field}")
    if not isinstance(payload["active_flow"], str):
        raise FlowDeliveryError("lease.active_flow must be a string")
    if payload["active_stage"] is not None and payload["active_stage"] not in STAGES:
        raise FlowDeliveryError("lease has unknown active_stage")
    if payload["runtime_ownership_state"] not in RUNTIME_OWNERSHIP_STATES:
        raise FlowDeliveryError("lease has unknown runtime ownership state")
    gates = payload.get("gates", {})
    if not isinstance(gates, dict) or any(type(value) is not bool for value in gates.values()):
        raise FlowDeliveryError("lease.gates must be a boolean object")


class FlowDeliveryController:
    def __init__(
        self,
        queue_path: Path = DEFAULT_QUEUE_PATH,
        policy_path: Path = DEFAULT_POLICY_PATH,
        lease_path: Path = DEFAULT_LEASE_PATH,
    ) -> None:
        self.queue_path = queue_path
        self.policy_path = policy_path
        self.lease_path = lease_path

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

    def select_next(self, queue: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        if queue is None:
            queue, _ = self.load()
        by_id = self._flows(queue)
        active = [flow for flow in by_id.values() if flow["status"] == "active"]
        if active:
            return deepcopy(active[0])
        ready = [
            flow
            for flow in by_id.values()
            if flow["status"] == "ready"
            and flow["product_policy_status"] not in {
                "unresolved_user_decision",
                "prohibited",
            }
            and all(by_id[dependency]["status"] == "completed" for dependency in flow["dependencies"])
        ]
        if not ready:
            return None
        return deepcopy(min(ready, key=lambda flow: (flow["priority"], flow["flow_id"])))

    def _require_lease(self, owner: str) -> dict[str, Any]:
        lease = self.lease()
        if lease is None:
            raise FlowDeliveryError("development lease is not held")
        if lease["owner"] != owner:
            raise FlowDeliveryError("development lease is held by another owner")
        return lease

    @staticmethod
    def _repo_head() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode or not result.stdout.strip():
            raise FlowDeliveryError("repository HEAD is unavailable")
        return result.stdout.strip()

    def acquire(
        self,
        *,
        owner: str,
        session_identity: str,
        runtime_ownership_state: str,
    ) -> dict[str, Any]:
        _require_nonempty_string(owner, "owner")
        _require_nonempty_string(session_identity, "session_identity")
        if runtime_ownership_state not in RUNTIME_OWNERSHIP_STATES:
            raise FlowDeliveryError("unknown runtime ownership state")
        if self.lease_path.exists():
            existing = self.lease()
            raise FlowDeliveryError(f"development lease conflict: {existing['owner']}")
        queue, _ = self.load()
        now = utc_now()
        payload = {
            "schema_version": 1,
            "workflow": "pns-flow-delivery",
            "owner": owner,
            "host": socket.gethostname(),
            "process_or_session_identity": session_identity,
            "process_id": os.getpid(),
            "acquisition_timestamp": now,
            "heartbeat_timestamp": now,
            "repository_head": self._repo_head(),
            "active_flow": queue.get("active_flow_id") or "",
            "active_stage": (
                self._flows(queue)[queue["active_flow_id"]]["last_completed_stage"]
                if queue.get("active_flow_id")
                else None
            ),
            "runtime_ownership_state": runtime_ownership_state,
            "gates": {
                "implementation_parent_reviewed": False,
                "focused_tests_passed": False,
                "architecture_tests_passed": False,
                "full_tests_passed": False,
                "no_unresolved_action": False,
            },
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
    ) -> dict[str, Any]:
        lease = self._require_lease(owner)
        if session_identity is not None and lease["process_or_session_identity"] != session_identity:
            raise FlowDeliveryError("lease session identity mismatch")
        if runtime_ownership_state is not None:
            if runtime_ownership_state not in RUNTIME_OWNERSHIP_STATES:
                raise FlowDeliveryError("unknown runtime ownership state")
            lease["runtime_ownership_state"] = runtime_ownership_state
        lease["repository_head"] = self._repo_head()
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return lease

    def activate(self, *, owner: str, flow_id: str | None = None) -> dict[str, Any]:
        lease = self._require_lease(owner)
        queue, _ = self.load()
        selected = self.select_next(queue)
        if selected is None:
            raise FlowDeliveryError("no ready development flow")
        if flow_id is not None and selected["flow_id"] != flow_id:
            raise FlowDeliveryError("requested flow is not the deterministic next flow")
        by_id = self._flows(queue)
        flow = by_id[selected["flow_id"]]
        if flow["status"] == "ready":
            flow["status"] = "active"
            flow["last_completed_stage"] = "selected"
            queue["active_flow_id"] = flow["flow_id"]
            validate_queue(queue)
            _atomic_write_json(self.queue_path, queue)
        lease["active_flow"] = flow["flow_id"]
        lease["active_stage"] = flow["last_completed_stage"]
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def record_stage(
        self,
        *,
        owner: str,
        stage: str,
        parent_reviewed: bool = False,
        focused_tests_passed: bool = False,
        architecture_tests_passed: bool = False,
        full_tests_passed: bool = False,
        no_unresolved_action: bool = False,
    ) -> dict[str, Any]:
        if stage not in STAGES:
            raise FlowDeliveryError(f"unknown delivery stage: {stage}")
        lease = self._require_lease(owner)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("queue and lease do not identify the same active flow")
        flow = self._flows(queue)[active_id]
        current = flow["last_completed_stage"]
        if current not in STAGES or stage not in TRANSITIONS[current]:
            raise FlowDeliveryError(f"invalid stage transition: {current} -> {stage}")
        if (
            current == "full_validation"
            and flow["requires_bluestacks_live"]
            and stage != "live_preflight"
        ):
            raise FlowDeliveryError("live-required flow cannot bypass live preflight")
        gates = lease.setdefault("gates", {})
        if parent_reviewed:
            gates["implementation_parent_reviewed"] = True
        if focused_tests_passed:
            gates["focused_tests_passed"] = True
        if architecture_tests_passed:
            gates["architecture_tests_passed"] = True
        if full_tests_passed:
            gates["full_tests_passed"] = True
        if no_unresolved_action:
            gates["no_unresolved_action"] = True
        if stage == "implementation_review" and not gates.get("implementation_parent_reviewed"):
            raise FlowDeliveryError("implementation review requires parent acceptance")
        if stage == "focused_validation" and not (
            gates.get("focused_tests_passed") and gates.get("architecture_tests_passed")
        ):
            raise FlowDeliveryError("focused validation requires focused and architecture tests")
        if stage == "full_validation" and not gates.get("full_tests_passed"):
            raise FlowDeliveryError("full validation requires the full-suite gate")
        if stage == "live_preflight":
            if not flow["requires_bluestacks_live"]:
                raise FlowDeliveryError("flow does not require BlueStacks live validation")
            if flow["maximum_live_attempts"] <= 0:
                raise FlowDeliveryError("flow has no live-attempt budget")
        if stage == "live_execution":
            required = (
                "implementation_parent_reviewed",
                "focused_tests_passed",
                "architecture_tests_passed",
                "full_tests_passed",
                "no_unresolved_action",
            )
            if any(not gates.get(gate) for gate in required):
                raise FlowDeliveryError("live execution gates are incomplete")
            if lease["runtime_ownership_state"] != "held":
                raise FlowDeliveryError("live execution requires parent-held runtime ownership")
            if flow["product_policy_status"] not in LIVE_POLICY_STATUSES:
                raise FlowDeliveryError("live policy is not explicit")
            _require_nonempty_string(flow["evidence_validator"], "evidence_validator")
        flow["last_completed_stage"] = stage
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        lease["active_stage"] = stage
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def complete(self, *, owner: str, commit: str) -> dict[str, Any]:
        _require_nonempty_string(commit, "commit")
        lease = self._require_lease(owner)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("no matching active flow to complete")
        flow = self._flows(queue)[active_id]
        if flow["last_completed_stage"] != "commit":
            raise FlowDeliveryError("flow must complete the commit stage first")
        if lease["runtime_ownership_state"] not in {"none", "released"}:
            raise FlowDeliveryError("runtime ownership must be released before completion")
        flow["status"] = "completed"
        flow["last_completed_stage"] = "completed"
        flow["last_commit"] = commit
        flow["blocked_reason"] = ""
        queue["active_flow_id"] = None
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        lease["active_flow"] = ""
        lease["active_stage"] = "completed"
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def block(self, *, owner: str, reason: str) -> dict[str, Any]:
        _require_nonempty_string(reason, "reason")
        lease = self._require_lease(owner)
        queue, _ = self.load()
        active_id = queue.get("active_flow_id")
        if not active_id or lease["active_flow"] != active_id:
            raise FlowDeliveryError("no matching active flow to block")
        flow = self._flows(queue)[active_id]
        flow["status"] = "blocked"
        flow["last_completed_stage"] = "blocked"
        flow["blocked_reason"] = reason
        queue["active_flow_id"] = None
        validate_queue(queue)
        _atomic_write_json(self.queue_path, queue)
        lease["active_flow"] = ""
        lease["active_stage"] = "blocked"
        lease["heartbeat_timestamp"] = utc_now()
        _atomic_write_json(self.lease_path, lease)
        return deepcopy(flow)

    def release(self, *, owner: str) -> dict[str, Any]:
        lease = self._require_lease(owner)
        queue, _ = self.load()
        if queue.get("active_flow_id") or lease["active_flow"]:
            raise FlowDeliveryError("cannot release the development lease with an active flow")
        if lease["runtime_ownership_state"] not in {"none", "released"}:
            raise FlowDeliveryError("cannot release while runtime ownership is held or unknown")
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
        if runtime_state != "released":
            raise FlowDeliveryError("stale lease cannot clear while runtime ownership is unknown/held")
        if journal_state != "resolved":
            raise FlowDeliveryError("stale lease cannot clear while journal state is unresolved")
        if consequential_state != "terminal":
            raise FlowDeliveryError("stale lease cannot clear with a possibly nonterminal action")
        if lease["active_stage"] in {"live_preflight", "live_execution", "evidence_review"} and not terminal_evidence:
            raise FlowDeliveryError("live-stage stale lease requires terminal evidence")
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
            "schema_version": 1,
            "queue": queue_name,
            "counts": counts,
            "active_flow": queue.get("active_flow_id"),
            "selected_flow": selected["flow_id"] if selected else None,
            "lease": (
                {
                    "owner": lease["owner"],
                    "active_flow": lease["active_flow"],
                    "active_stage": lease["active_stage"],
                    "runtime_ownership_state": lease["runtime_ownership_state"],
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
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("status", "validate", "select-next"):
        sub.add_parser(command)
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--owner", required=True)
    acquire.add_argument("--session-id", required=True)
    acquire.add_argument(
        "--runtime-ownership-state",
        choices=sorted(RUNTIME_OWNERSHIP_STATES),
        default="none",
    )
    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--owner", required=True)
    heartbeat.add_argument("--session-id")
    heartbeat.add_argument(
        "--runtime-ownership-state",
        choices=sorted(RUNTIME_OWNERSHIP_STATES),
    )
    activate = sub.add_parser("activate")
    activate.add_argument("--owner", required=True)
    activate.add_argument("--flow-id")
    stage = sub.add_parser("record-stage")
    stage.add_argument("--owner", required=True)
    stage.add_argument("--stage", required=True, choices=STAGES)
    stage.add_argument("--parent-reviewed", action="store_true")
    stage.add_argument("--focused-tests-passed", action="store_true")
    stage.add_argument("--architecture-tests-passed", action="store_true")
    stage.add_argument("--full-tests-passed", action="store_true")
    stage.add_argument("--no-unresolved-action", action="store_true")
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
    reconcile.add_argument(
        "--consequential-state",
        required=True,
        choices=("terminal", "nonterminal", "unknown"),
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    controller = FlowDeliveryController(args.queue, args.policy, args.lease)
    try:
        if args.command == "status":
            result = controller.status()
        elif args.command == "validate":
            controller.load()
            controller.lease()
            result = {"valid": True}
        elif args.command == "select-next":
            selected = controller.select_next()
            result = {"flow": selected}
        elif args.command == "acquire":
            result = controller.acquire(
                owner=args.owner,
                session_identity=args.session_id,
                runtime_ownership_state=args.runtime_ownership_state,
            )
        elif args.command == "heartbeat":
            result = controller.heartbeat(
                owner=args.owner,
                session_identity=args.session_id,
                runtime_ownership_state=args.runtime_ownership_state,
            )
        elif args.command == "activate":
            result = controller.activate(owner=args.owner, flow_id=args.flow_id)
        elif args.command == "record-stage":
            result = controller.record_stage(
                owner=args.owner,
                stage=args.stage,
                parent_reviewed=args.parent_reviewed,
                focused_tests_passed=args.focused_tests_passed,
                architecture_tests_passed=args.architecture_tests_passed,
                full_tests_passed=args.full_tests_passed,
                no_unresolved_action=args.no_unresolved_action,
            )
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
