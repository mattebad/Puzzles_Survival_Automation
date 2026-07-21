"""Scheduler-aware deterministic task results for pulseable gameplay flows.

Extends the existing TaskResult vocabulary without replacing the Phase-F scheduler or
action journal. Persistence uses the SafetyStore SQLite boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class SchedulerTaskOutcome(str, Enum):
    ACTION_PERFORMED = "action_performed"
    DEFERRED = "deferred"
    COMPLETE_FOR_RESET = "complete_for_reset"
    ALREADY_COMPLETE = "already_complete"
    BLOCKED = "blocked"
    MANUAL_REQUIRED = "manual_required"


@dataclass(frozen=True)
class SchedulerIdentity:
    account_id: str
    server_id: str
    reset_id: str
    task_id: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.account_id, self.server_id, self.reset_id, self.task_id)
        ):
            raise ValueError("scheduler identity requires account, server, reset, and task ids")

    @property
    def composite_key(self) -> str:
        return f"{self.account_id}|{self.server_id}|{self.reset_id}|{self.task_id}"


@dataclass(frozen=True)
class SchedulerAwareTaskResult:
    outcome: SchedulerTaskOutcome
    reason_code: str
    identity: SchedulerIdentity
    verified: bool = True
    observed_progress: Mapping[str, Any] = field(default_factory=dict)
    action_count: int = 0
    consequence: Mapping[str, Any] = field(default_factory=dict)
    next_eligible_at: Optional[float] = None
    evidence_refs: tuple[str, ...] = ()
    unresolved_action: bool = False
    intended_actions: tuple[str, ...] = ()
    dispatched_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.action_count < 0:
            raise ValueError("action_count cannot be negative")
        if self.outcome is SchedulerTaskOutcome.ACTION_PERFORMED and self.action_count < 1:
            raise ValueError("action_performed requires action_count >= 1")
        if self.outcome is SchedulerTaskOutcome.DEFERRED and self.next_eligible_at is None:
            raise ValueError("deferred requires next_eligible_at")
        if self.dispatched_actions and not self.intended_actions:
            raise ValueError("dispatched actions require intended actions")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "identity": asdict(self.identity),
            "composite_key": self.identity.composite_key,
            "verified": self.verified,
            "observed_progress": dict(self.observed_progress),
            "action_count": self.action_count,
            "consequence": dict(self.consequence),
            "next_eligible_at": self.next_eligible_at,
            "evidence_refs": list(self.evidence_refs),
            "unresolved_action": self.unresolved_action,
            "intended_actions": list(self.intended_actions),
            "dispatched_actions": list(self.dispatched_actions),
        }

    @classmethod
    def action_performed(cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any) -> "SchedulerAwareTaskResult":
        kwargs.setdefault("action_count", 1)
        return cls(SchedulerTaskOutcome.ACTION_PERFORMED, reason_code, identity, **kwargs)

    @classmethod
    def deferred(cls, identity: SchedulerIdentity, reason_code: str, next_eligible_at: float, **kwargs: Any) -> "SchedulerAwareTaskResult":
        return cls(SchedulerTaskOutcome.DEFERRED, reason_code, identity, next_eligible_at=next_eligible_at, **kwargs)

    @classmethod
    def complete_for_reset(cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any) -> "SchedulerAwareTaskResult":
        return cls(SchedulerTaskOutcome.COMPLETE_FOR_RESET, reason_code, identity, **kwargs)

    @classmethod
    def already_complete(cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any) -> "SchedulerAwareTaskResult":
        return cls(SchedulerTaskOutcome.ALREADY_COMPLETE, reason_code, identity, **kwargs)

    @classmethod
    def blocked(cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any) -> "SchedulerAwareTaskResult":
        return cls(SchedulerTaskOutcome.BLOCKED, reason_code, identity, **kwargs)

    @classmethod
    def manual_required(cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any) -> "SchedulerAwareTaskResult":
        return cls(SchedulerTaskOutcome.MANUAL_REQUIRED, reason_code, identity, **kwargs)


@dataclass(frozen=True)
class SchedulerInvocationState:
    identity: SchedulerIdentity
    status: str
    revision: int = 0
    next_eligible_at: Optional[float] = None
    last_reason_code: str = ""
    observed_progress_json: str = "{}"
    action_count_total: int = 0
    unresolved_action: bool = False
    evidence_refs_json: str = "[]"

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        if self.status not in {
            "pending",
            "deferred",
            "complete_for_reset",
            "already_complete",
            "blocked",
            "manual_required",
            "unresolved",
        }:
            raise ValueError("invalid scheduler invocation status")
