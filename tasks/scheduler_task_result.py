"""Scheduler-aware deterministic task results for pulseable gameplay flows.

Extends the existing TaskResult vocabulary without replacing the Phase-F scheduler or
action journal. Persistence uses the SafetyStore SQLite boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Optional

class SchedulerTaskOutcome(str, Enum):
    ACTION_PERFORMED = "action_performed"
    DEFERRED = "deferred"
    COMPLETE_FOR_RESET = "complete_for_reset"
    ALREADY_COMPLETE = "already_complete"
    BLOCKED = "blocked"
    MANUAL_REQUIRED = "manual_required"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"

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
class SchedulerOccurrence:
    """One reset/recurrence occurrence persisted by the scheduler repository."""

    identity: SchedulerIdentity
    occurrence_key: str
    recurrence_class: str
    repeat_ordinal: int = 0
    status: str = "ELIGIBLE"
    revision: int = 0
    next_eligible_at: float | None = None
    projection_json: str = "{}"
    claim_id: str | None = None
    claim_token: str | None = None
    last_reason_code: str = ""
    pulse_token: str | None = None
    action_count_total: int = 0
    unresolved_action: bool = False
    evidence_refs_json: str = "[]"

    def __post_init__(self) -> None:
        if not self.occurrence_key.strip() or not self.recurrence_class.strip():
            raise ValueError("scheduler occurrence requires key and recurrence class")
        if self.repeat_ordinal < 0 or self.revision < 0 or self.action_count_total < 0:
            raise ValueError("scheduler occurrence counters cannot be negative")
        if self.status not in {
            "ELIGIBLE",
            "CLAIMED",
            "DEFERRED",
            "COMPLETED",
            "BLOCKED",
            "MANUAL_REQUIRED",
            "RECONCILIATION_REQUIRED",
        }:
            raise ValueError("invalid scheduler occurrence status")

    @property
    def occurrence_id(self) -> str:
        """Stable opaque occurrence identifier exposed without a second authority."""
        return self.occurrence_key


@dataclass(frozen=True)
class SchedulerOccurrenceClaim:
    occurrence: SchedulerOccurrence
    claim_id: str
    claim_token: str
    claimed_at: float

    @property
    def identity(self) -> SchedulerIdentity:
        return self.occurrence.identity

    @property
    def occurrence_key(self) -> str:
        return self.occurrence.occurrence_key


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
        if not self.reason_code.strip():
            raise ValueError("scheduler result requires a reason code")
        if type(self.action_count) is not int or self.action_count < 0:
            raise ValueError("action_count cannot be negative")
        if self.outcome is SchedulerTaskOutcome.ACTION_PERFORMED and self.action_count < 1:
            raise ValueError("action_performed requires action_count >= 1")
        if self.outcome is SchedulerTaskOutcome.DEFERRED and (
            self.next_eligible_at is None
            or not isinstance(self.next_eligible_at, (int, float))
            or not math.isfinite(float(self.next_eligible_at))
            or self.next_eligible_at < 0
        ):
            raise ValueError("deferred requires a finite non-negative UTC deadline")
        if self.next_eligible_at is not None and (
            not isinstance(self.next_eligible_at, (int, float))
            or not math.isfinite(float(self.next_eligible_at))
            or self.next_eligible_at < 0
        ):
            raise ValueError("next_eligible_at must be a finite non-negative UTC epoch")
        if self.dispatched_actions and not self.intended_actions:
            raise ValueError("dispatched actions require intended actions")
        if self.outcome in {
            SchedulerTaskOutcome.RECONCILIATION_REQUIRED,
            SchedulerTaskOutcome.UNRESOLVED,
            SchedulerTaskOutcome.UNKNOWN,
        }:
            object.__setattr__(self, "unresolved_action", True)


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

    @classmethod
    def reconciliation_required(
        cls, identity: SchedulerIdentity, reason_code: str, **kwargs: Any
    ) -> "SchedulerAwareTaskResult":
        kwargs["unresolved_action"] = True
        return cls(
            SchedulerTaskOutcome.RECONCILIATION_REQUIRED,
            reason_code,
            identity,
            **kwargs,
        )
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
        if self.revision < 0 or self.action_count_total < 0:
            raise ValueError("scheduler invocation counters cannot be negative")
        if self.status not in {
            "pending",
            "deferred",
            "complete_for_reset",
            "already_complete",
            "blocked",
            "manual_required",
            "unresolved",
            "reconciliation_required",
        }:
            raise ValueError("invalid scheduler invocation status")
        if self.next_eligible_at is not None and (
            not isinstance(self.next_eligible_at, (int, float))
            or not math.isfinite(float(self.next_eligible_at))
            or self.next_eligible_at < 0
        ):
            raise ValueError("scheduler invocation deadline must be a UTC epoch")
