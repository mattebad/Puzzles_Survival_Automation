"""Small typed contracts for the offline automation-service composition layer."""

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
    RECONCILIATION_REQUIRED = "reconciliation_required"


class RecurrenceClass(str, Enum):
    """Closed recurrence vocabulary understood by the offline scheduler."""

    DAILY_ONCE_PER_RESET = "daily_once_per_reset"
    RESET_BOUNDED = "reset_bounded"
    COOLDOWN = "cooldown"
    TIMER = "timer"
    AP_REGENERATION = "ap_regeneration"
    STAMINA_REGENERATION = "stamina_regeneration"
    QUEUE_GENERATION = "queue_generation"
    MARCH_GENERATION = "march_generation"
    BOUNDED_REPEAT = "bounded_repeat"
    EVENT_WINDOW = "event_window"


@dataclass(frozen=True)
class RecurrenceProjection:
    """Persistable, product-observation-bound recurrence projection."""

    recurrence_class: RecurrenceClass
    next_eligible_at: float | None = None
    observed_at_utc: float | None = None
    generation: str | None = None
    observed_balance: float | None = None
    repeat_ordinal: int = 0
    repeat_limit: int | None = None
    window_open_at: float | None = None
    window_close_at: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.next_eligible_at,
            self.observed_at_utc,
            self.observed_balance,
            self.window_open_at,
            self.window_close_at,
        )
        if any(
            value is not None
            and (isinstance(value, bool) or not math.isfinite(float(value)))
            for value in values
        ):
            raise ValueError("recurrence projection values must be finite numbers")
        if any(value is not None and float(value) < 0 for value in values):
            raise ValueError("recurrence projection values cannot be negative")
        if type(self.repeat_ordinal) is not int or self.repeat_ordinal < 0:
            raise ValueError("repeat ordinal must be a non-negative integer")
        if self.repeat_limit is not None and (
            type(self.repeat_limit) is not int or self.repeat_limit < 1
        ):
            raise ValueError("repeat limit must be a positive integer")
        if self.repeat_limit is not None and self.repeat_ordinal >= self.repeat_limit:
            raise ValueError("repeat ordinal must remain below repeat limit")
        if self.recurrence_class in {RecurrenceClass.COOLDOWN, RecurrenceClass.TIMER} and (
            self.observed_at_utc is None
        ):
            raise ValueError("cooldown and timer projections require an explicit observation timestamp")
        if (
            self.window_open_at is not None
            and self.window_close_at is not None
            and self.window_close_at <= self.window_open_at
        ):
            raise ValueError("event window must have a positive UTC duration")
        if self.recurrence_class in {
            RecurrenceClass.QUEUE_GENERATION,
            RecurrenceClass.MARCH_GENERATION,
        } and not self.generation:
            raise ValueError("availability generations require a generation identity")
        if self.recurrence_class in {
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        } and (self.observed_balance is None or self.observed_at_utc is None):
            raise ValueError("resource regeneration requires a fresh timestamped observed balance")

    @property
    def is_time_projection(self) -> bool:
        return self.recurrence_class in {
            RecurrenceClass.COOLDOWN,
            RecurrenceClass.TIMER,
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        }


@dataclass(frozen=True)
class ProductAuthority:
    """Accepted product and registration facts for one scheduler descriptor."""

    product_id: str
    product_revision: str
    registration_status: str = "NOT_REGISTERED"
    scheduler_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.product_id.strip() or not self.product_revision.strip():
            raise ValueError("product authority requires product identity and revision")
        if self.registration_status not in {"REGISTERED", "NOT_REGISTERED"}:
            raise ValueError("unsupported registration status")


@dataclass(frozen=True)
class RuntimeOwnerFact:
    """An observed availability fact, never an owner lease or capability."""

    available: bool = False
    owner_id: str | None = None
    observed_at_utc: float | None = None

    def __post_init__(self) -> None:
        if self.available and not self.owner_id:
            raise ValueError("available runtime owner requires an owner identity")
        if self.observed_at_utc is not None and (
            isinstance(self.observed_at_utc, bool)
            or not math.isfinite(float(self.observed_at_utc))
            or self.observed_at_utc < 0
        ):
            raise ValueError("runtime owner observation must be a UTC epoch")


@dataclass(frozen=True)
class FlowDescriptor:
    """Identity, authority, and cadence metadata; no gameplay semantics."""

    flow_id: str
    owner: str
    family: str
    variant: str
    cadence: str
    priority: int = 100
    reset_scoped: bool = True
    scheduler_eligible: bool = False
    accepted_product: bool | str = False
    product_revision: str | None = None
    registration_status: str = "NOT_REGISTERED"
    recurrence: RecurrenceProjection | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.flow_id, self.owner, self.family, self.variant, self.cadence)
        ):
            raise ValueError("flow descriptor requires non-empty identity fields")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("flow priority must be a non-negative integer")
        if self.registration_status not in {"REGISTERED", "NOT_REGISTERED"}:
            raise ValueError("unsupported flow registration status")
        if self.product_revision is not None and not self.product_revision.strip():
            raise ValueError("product revision cannot be blank")
        if isinstance(self.accepted_product, str) and not self.accepted_product.strip():
            raise ValueError("accepted product identity cannot be blank")

    @property
    def product_admitted(self) -> bool:
        return bool(self.accepted_product)

    @property
    def recurrence_class(self) -> RecurrenceClass | None:
        if self.recurrence is not None:
            return self.recurrence.recurrence_class
        return {
            "daily_once": RecurrenceClass.DAILY_ONCE_PER_RESET,
            "daily_once_per_reset": RecurrenceClass.DAILY_ONCE_PER_RESET,
            "reset_pulse": RecurrenceClass.DAILY_ONCE_PER_RESET,
            "cooldown_pulse": RecurrenceClass.COOLDOWN,
            "timer": RecurrenceClass.TIMER,
        }.get(self.cadence)


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
    """Fail-closed UTC boundary facts supplied by external authorities."""

    account_id: str
    server_id: str
    reset_id: str
    now_utc_epoch: float
    health_ok: bool = False
    unresolved_action: bool = False
    breakers: tuple[str, ...] = ()
    last_frame_age_seconds: float | None = None
    accepted_product: bool | str = False
    product_revision: str | None = None
    registration_status: str = "NOT_REGISTERED"
    scheduler_eligible: bool = False
    owner_available: bool = False
    runtime_owner: RuntimeOwnerFact | None = None
    clock_ok: bool = False
    clock_rollback: bool = False
    reset_agreement: bool = False
    observed_reset_id: str | None = None
    projections: Mapping[str, RecurrenceProjection] = field(default_factory=dict)

    projection_freshness_seconds: float = 300.0
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
        if self.registration_status not in {"REGISTERED", "NOT_REGISTERED"}:
            raise ValueError("unsupported scheduler registration status")
        if self.product_revision is not None and not self.product_revision.strip():
            raise ValueError("scheduler product revision cannot be blank")
        if isinstance(self.accepted_product, str) and not self.accepted_product.strip():
            raise ValueError("scheduler accepted product identity cannot be blank")
        if self.observed_reset_id is not None and not self.observed_reset_id.strip():
            raise ValueError("observed reset identity cannot be blank")
        if self.runtime_owner is not None and self.runtime_owner.available != self.owner_available:
            raise ValueError("runtime owner fact disagrees with owner_available")
        if (
            not math.isfinite(self.projection_freshness_seconds)
            or self.projection_freshness_seconds < 0
        ):
            raise ValueError("projection freshness must be finite and non-negative")

    def gate_failures(self, descriptor: FlowDescriptor) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.health_ok:
            failures.append("GLOBAL_HEALTH_BREAKER")
        if self.unresolved_action:
            failures.append("GLOBAL_UNRESOLVED_ACTION")
        if self.breakers:
            failures.append("TASK_BREAKER:" + self.breakers[0])
        if not descriptor.scheduler_eligible or not self.scheduler_eligible:
            failures.append("SCHEDULER_INELIGIBLE")
        if descriptor.registration_status != "REGISTERED" or self.registration_status != "REGISTERED":
            failures.append("REGISTRATION_DISABLED")
        if not descriptor.product_admitted or not self.accepted_product:
            failures.append("ACCEPTED_PRODUCT_REQUIRED")
        if (
            isinstance(descriptor.accepted_product, str)
            and isinstance(self.accepted_product, str)
            and descriptor.accepted_product != self.accepted_product
        ):
            failures.append("ACCEPTED_PRODUCT_MISMATCH")
        if (
            descriptor.product_revision
            and self.product_revision
            and descriptor.product_revision != self.product_revision
        ):
            failures.append("PRODUCT_REVISION_MISMATCH")
        if not self.owner_available:
            failures.append("SINGLETON_OWNER_UNAVAILABLE")
        if not self.clock_ok or self.clock_rollback:
            failures.append("UTC_CLOCK_INVALID")
        if not self.reset_agreement or (
            self.observed_reset_id is not None and self.observed_reset_id != self.reset_id
        ):
            failures.append("RESET_DISAGREEMENT")
        return tuple(failures)


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
        if self.outcome in {NormalizedOutcome.UNRESOLVED, NormalizedOutcome.RECONCILIATION_REQUIRED}:
            object.__setattr__(self, "unresolved_action", True)


@dataclass(frozen=True)
class FlowSpec:
    """Static route facts used only when a flow row is first initialized.

    Runtime enablement, blocking, scheduling, and retry state belong to the
    SQLite state manager.  ``default_enabled`` intentionally defaults to
    ``False`` and is never allowed to override an existing persisted row.
    """

    flow_id: str
    default_enabled: bool = False
    priority: int = 100
    cadence: str = "manual"
    max_wait_seconds: float | None = None
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.flow_id, str) or not self.flow_id.strip():
            raise ValueError("flow spec requires a flow id")
        if type(self.default_enabled) is not bool:
            raise ValueError("flow spec default_enabled must be a bool")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("flow spec priority must be a non-negative integer")
        if not isinstance(self.cadence, str) or not self.cadence.strip():
            raise ValueError("flow spec cadence must be named")
        if self.max_wait_seconds is not None and (
            isinstance(self.max_wait_seconds, bool)
            or not math.isfinite(float(self.max_wait_seconds))
            or self.max_wait_seconds < 0
        ):
            raise ValueError("flow spec max wait must be a non-negative finite number")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("flow spec max attempts must be positive")
