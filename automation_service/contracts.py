"""Small typed contracts for the offline automation-service composition layer.

The service composes existing policy, action, perception, and scheduler primitives.  It
does not define a second action journal, coordinate language, or monotonic scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Optional

from safe_action_core.models import ActionIntent as CoreActionIntent


class ServiceMode(str, Enum):
    DISABLED = "disabled"
    OBSERVE_ONLY = "observe_only"
    DRY_RUN = "dry_run"
    SUPERVISED = "supervised"


class NormalizedOutcome(str, Enum):
    ACTION_PERFORMED = "action_performed"
    DEFERRED = "deferred"
    COMPLETE_FOR_RESET = "complete_for_reset"
    ALREADY_COMPLETE = "already_complete"
    BLOCKED = "blocked"
    MANUAL_REQUIRED = "manual_required"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class FlowDescriptor:
    """Identity and cadence metadata; it contains no gameplay action semantics."""

    flow_id: str
    owner: str
    family: str
    variant: str
    cadence: str
    priority: int = 100
    reset_scoped: bool = True
    scheduler_eligible: bool = False

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.flow_id, self.owner, self.family, self.variant, self.cadence)
        ):
            raise ValueError("flow descriptor requires non-empty identity fields")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("flow priority must be a non-negative integer")


@dataclass(frozen=True)
class FamilyFacts:
    family: str
    recognized: bool
    values: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise ValueError("family facts require a family")


@dataclass(frozen=True)
class PerceptionEnvelope:
    """Read-only family observations passed to handlers."""

    capture_id: str
    context: str
    profile_id: str
    freshness: str
    runtime_state: str = "unknown"
    family_facts: tuple[FamilyFacts, ...] = ()
    candidate: str | None = None
    runner_up: str | None = None
    negative_evidence: tuple[str, ...] = ()
    invalidated_after_input: bool = False

    def __post_init__(self) -> None:
        if not self.capture_id.strip() or not self.profile_id.strip():
            raise ValueError("perception envelope requires capture and profile identity")

    def facts_for(self, family: str) -> FamilyFacts | None:
        return next((facts for facts in self.family_facts if facts.family == family), None)


@dataclass(frozen=True)
class SchedulerFacts:
    """UTC boundary facts.  No monotonic deadline belongs in this contract."""

    account_id: str
    server_id: str
    reset_id: str
    now_utc_epoch: float
    health_ok: bool = False
    unresolved_action: bool = False
    breakers: tuple[str, ...] = ()
    last_frame_age_seconds: float | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.account_id, self.server_id, self.reset_id)
        ):
            raise ValueError("scheduler facts require account, server, and reset identity")
        if not math.isfinite(self.now_utc_epoch) or self.now_utc_epoch < 0:
            raise ValueError("scheduler time must be a finite UTC epoch")
        if self.last_frame_age_seconds is not None and (
            not math.isfinite(self.last_frame_age_seconds) or self.last_frame_age_seconds < 0
        ):
            raise ValueError("last-frame age must be finite and non-negative")


@dataclass(frozen=True)
class CostEffectVector:
    """Explicit cost/effect dimensions used by eligibility and summaries."""

    resource: Mapping[str, float] = field(default_factory=dict)
    currency: Mapping[str, float] = field(default_factory=dict)
    material: Mapping[str, float] = field(default_factory=dict)
    ap: float = 0.0
    stamina: float = 0.0
    item: Mapping[str, float] = field(default_factory=dict)
    queue_time_seconds: float = 0.0
    march_slot: int = 0
    reserve: Mapping[str, float] = field(default_factory=dict)
    cap: Mapping[str, float] = field(default_factory=dict)
    deltas: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scalar_values = (self.ap, self.stamina, self.queue_time_seconds, self.march_slot)
        if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in scalar_values):
            raise ValueError("cost/effect scalar values must be finite numbers")
        if self.queue_time_seconds < 0 or self.march_slot < 0:
            raise ValueError("queue time and march slot values cannot be negative")
        for mapping in (
            self.resource,
            self.currency,
            self.material,
            self.item,
            self.reserve,
            self.cap,
            self.deltas,
        ):
            for key, value in mapping.items():
                if not str(key).strip() or isinstance(value, bool) or not math.isfinite(float(value)):
                    raise ValueError("cost/effect maps require finite values and named keys")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "resource": dict(self.resource),
            "currency": dict(self.currency),
            "material": dict(self.material),
            "ap": self.ap,
            "stamina": self.stamina,
            "item": dict(self.item),
            "queue_time_seconds": self.queue_time_seconds,
            "march_slot": self.march_slot,
            "reserve": dict(self.reserve),
            "cap": dict(self.cap),
            "deltas": dict(self.deltas),
        }


@dataclass(frozen=True)
class SemanticActionIntent:
    """Semantic service intent that can reference the existing core intent."""

    semantic_action: str
    task_id: str
    source_state: str
    expected_postcondition: str
    cost_effect: CostEffectVector = field(default_factory=CostEffectVector)
    core_intent: Optional[CoreActionIntent] = None
    target_identity: str | None = None
    evidence_refs: tuple[str, ...] = ()
    flow_id: str | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.semantic_action,
                self.task_id,
                self.source_state,
                self.expected_postcondition,
            )
        ):
            raise ValueError("semantic action intent requires named lifecycle fields")

    @property
    def action_key(self) -> str:
        if self.core_intent is not None:
            return self.core_intent.action_key
        return f"{self.task_id}:{self.semantic_action}"


@dataclass(frozen=True)
class NormalizedResult:
    outcome: NormalizedOutcome
    reason_code: str
    action_count: int = 0
    verified: bool = True
    next_eligible_at: float | None = None
    observed_progress: Mapping[str, Any] = field(default_factory=dict)
    consequence: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    unresolved_action: bool = False

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("normalized results require a reason code")
        if type(self.action_count) is not int or self.action_count < 0:
            raise ValueError("action_count must be a non-negative integer")
        if self.outcome is NormalizedOutcome.ACTION_PERFORMED and self.action_count < 1:
            raise ValueError("action_performed requires an action")
        if self.outcome is NormalizedOutcome.DEFERRED:
            if self.next_eligible_at is None or not math.isfinite(self.next_eligible_at):
                raise ValueError("deferred requires a finite UTC next_eligible_at")
        if self.next_eligible_at is not None and (
            not math.isfinite(self.next_eligible_at) or self.next_eligible_at < 0
        ):
            raise ValueError("next_eligible_at must be a non-negative UTC epoch")
        if self.outcome is NormalizedOutcome.UNRESOLVED:
            object.__setattr__(self, "unresolved_action", True)

