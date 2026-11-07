"""Semantic contracts and deterministic state for the four Daily troop queues.

This module is transport-free.  It accepts only positively recognized observations from the
native BlueStacks adapter and keeps fighter, shooter, rider, and vehicle state independent.
Daily Quest Claim, production registration, and scheduler promotion are intentionally outside
this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
from typing import Iterable, Mapping


TROOP_TYPES = ("fighter", "shooter", "rider", "vehicle")
FACILITY_BY_TYPE = {
    "fighter": "Fighter Camp",
    "shooter": "Shooter Camp",
    "rider": "Rider Camp",
    "vehicle": "Vehicle Depot",
}
TRAINING_POLICIES = ("once_daily", "continuous", "disabled")
QUANTITY_MODES = ("fixed", "current_max")
RESOURCE_NAMES = ("food", "wood", "steel", "gas")
MAX_TIER = 13
MAX_QUANTITY = 1000
DAILY_TRAINING_QUANTITY = 250


class TrainingContractError(ValueError):
    """Raised when configuration or a live semantic observation is unsafe."""


@dataclass(frozen=True)
class TrainingConfig:
    enabled: bool = True
    target_tier: int | None = None
    quantity: int | None = None
    quantity_mode: str = "fixed"
    training_policy: str = "once_daily"
    allow_resource_boxes: bool = False

    def __post_init__(self) -> None:
        # Preserve the legacy fixed-quantity constructor while making an explicit
        # current_max mode unambiguous (there is no hidden fixed fallback).
        if self.quantity is None and self.quantity_mode == "fixed":
            object.__setattr__(self, "quantity", DAILY_TRAINING_QUANTITY)

    def validate(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(self.allow_resource_boxes, bool):
            raise TrainingContractError("enabled and allow_resource_boxes must be booleans")
        if self.training_policy not in TRAINING_POLICIES:
            raise TrainingContractError(f"unknown training policy: {self.training_policy!r}")
        if self.quantity_mode not in QUANTITY_MODES:
            raise TrainingContractError(f"unknown quantity mode: {self.quantity_mode!r}")
        if self.quantity is not None and (not isinstance(self.quantity, int) or not 1 <= self.quantity <= MAX_QUANTITY):
            raise TrainingContractError("quantity must be an integer from 1 through 1000 when supplied")
        if self.quantity_mode == "fixed" and self.quantity is None:
            raise TrainingContractError("fixed quantity mode requires an explicit quantity")
        if self.quantity_mode == "current_max" and self.quantity is not None:
            raise TrainingContractError("current_max quantity mode cannot include a fixed quantity")
        if self.enabled and self.training_policy != "disabled" and self.target_tier is None:
            raise TrainingContractError("enabled training requires an explicit target tier")
        if self.target_tier is not None and not 1 <= self.target_tier <= MAX_TIER:
            raise TrainingContractError("target tier must be T1 through T13")


@dataclass(frozen=True)
class TroopTrainingConfig:
    fighter: TrainingConfig = field(default_factory=TrainingConfig)
    shooter: TrainingConfig = field(default_factory=TrainingConfig)
    rider: TrainingConfig = field(default_factory=TrainingConfig)
    vehicle: TrainingConfig = field(default_factory=TrainingConfig)

    def validate(self) -> None:
        for troop_type in TROOP_TYPES:
            item = getattr(self, troop_type)
            item.validate()
            if troop_type in {"shooter", "rider"} and item.allow_resource_boxes:
                raise TrainingContractError(f"resource boxes are structurally forbidden for {troop_type}")

    def for_type(self, troop_type: str) -> TrainingConfig:
        if troop_type not in TROOP_TYPES:
            raise TrainingContractError(f"unknown troop type: {troop_type!r}")
        return getattr(self, troop_type)

    def resolved_profile(self) -> dict[str, dict[str, object]]:
        """Return the exact user contract, without resolving screen-dependent maxima."""

        return {
            troop_type: {
                "enabled": self.for_type(troop_type).enabled,
                "target_tier": self.for_type(troop_type).target_tier,
                "quantity": self.for_type(troop_type).quantity,
                "quantity_mode": self.for_type(troop_type).quantity_mode,
                "training_policy": self.for_type(troop_type).training_policy,
                "allow_resource_boxes": self.for_type(troop_type).allow_resource_boxes,
            }
            for troop_type in TROOP_TYPES
        }


def default_troop_training_config() -> TroopTrainingConfig:
    """Return the approved fixed service profile for all four troop variants."""

    return TroopTrainingConfig(
        fighter=TrainingConfig(target_tier=8, quantity=None, quantity_mode="current_max", training_policy="continuous", allow_resource_boxes=True),
        shooter=TrainingConfig(target_tier=8, quantity=DAILY_TRAINING_QUANTITY, quantity_mode="fixed", training_policy="once_daily", allow_resource_boxes=False),
        rider=TrainingConfig(target_tier=1, quantity=DAILY_TRAINING_QUANTITY, quantity_mode="fixed", training_policy="once_daily", allow_resource_boxes=False),
        vehicle=TrainingConfig(target_tier=1, quantity=None, quantity_mode="current_max", training_policy="continuous", allow_resource_boxes=True),
    )


@dataclass(frozen=True)
class ResourceReading:
    name: str
    held: int | None
    required: int | None
    source: str = "base"

    @property
    def status(self) -> str:
        if self.held is None or self.required is None:
            return "unknown"
        return "sufficient" if self.held >= self.required else "insufficient"


@dataclass(frozen=True)
class TierObservation:
    tier: int
    visible: bool = True
    unlocked: bool = False
    selected: bool = False
    question_mark: bool = False
    lock_reason: str = ""
    target_roi: tuple[int, int, int, int] | None = None

    @property
    def locked(self) -> bool:
        return self.question_mark or not self.unlocked


@dataclass(frozen=True)
class HomeObservation:
    recognized: bool
    facilities: Mapping[str, tuple[int, int, int, int]] = field(default_factory=dict)
    completed_ready: Mapping[str, bool] = field(default_factory=dict)
    completed_batch_ids: Mapping[str, str] = field(default_factory=dict)
    overlay_state: str = "none"
    reset_identity: str | None = None
    frame_sha256: str = ""
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def facility_target(self, troop_type: str) -> tuple[int, int, int, int] | None:
        return self.facilities.get(troop_type)


@dataclass(frozen=True)
class RadialMenuObservation:
    recognized: bool
    facility_identity: str
    train_target: tuple[int, int, int, int] | None = None
    completed_banner: str = ""
    overlay_state: str = "none"
    frame_sha256: str = ""


@dataclass(frozen=True)
class TrainingScreenObservation:
    recognized: bool
    troop_type: str | None
    facility_identity: str | None
    selected_tier: int | None
    visible_tiers: tuple[TierObservation, ...] = ()
    selected_quantity: int | None = None
    quantity_maximum: int | None = None
    resources: tuple[ResourceReading, ...] = ()
    normal_train_target: tuple[int, int, int, int] | None = None
    train_now_target: tuple[int, int, int, int] | None = None
    training_duration_seconds: int | None = None
    queue_active: bool = False
    queue_label: str | None = None
    queue_troop_type: str | None = None
    queue_tier: int | None = None
    queue_quantity: int | None = None
    completion_ready: bool = False
    completion_batch_id: str | None = None
    completion_banner: str = ""
    warehouse_popup: bool = False
    warehouse_confirm_target: tuple[int, int, int, int] | None = None
    resource_shortage: tuple[str, ...] = ()
    premium_popup: bool = False
    forbidden_controls: tuple[str, ...] = ()
    overlay_state: str = "none"
    frame_sha256: str = ""
    captured_at: datetime | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def tier(self, number: int) -> TierObservation | None:
        return next((item for item in self.visible_tiers if item.tier == number), None)

    def resources_by_name(self) -> dict[str, ResourceReading]:
        return {resource.name: resource for resource in self.resources}


@dataclass(frozen=True)
class AutoUseResourcePopupObservation:
    """Exact inventory-resource continuation shown after a normal Train shortage."""

    recognized: bool
    resource_boxes_selected: bool = False
    warehouse_only: bool = False
    cancel_target: tuple[int, int, int, int] | None = None
    confirm_target: tuple[int, int, int, int] | None = None
    resources_after_use: tuple[ResourceReading, ...] = ()
    frame_sha256: str = ""
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyTrainingProgress:
    troop_type: str
    current: int | None
    maximum: int = DAILY_TRAINING_QUANTITY
    recognized: bool = False
    source_frame_sha256: str = ""


@dataclass(frozen=True)
class TrainingSchedulerState:
    troop_type: str
    state: str
    next_eligible_timestamp: datetime | None
    scheduler_eligibility: bool = False
    production_registration: bool = False


@dataclass(frozen=True)
class TroopWorkflowState:
    troop_type: str
    facility_identity: str
    reset_identity: str
    enabled: bool
    target_tier: int | None
    tier_unlock_state: str = "unknown"
    configured_quantity: int | None = DAILY_TRAINING_QUANTITY
    quantity_mode: str = "fixed"
    resolved_quantity: int | None = None
    allow_resource_boxes: bool = False
    selected_quantity: int | None = None
    base_resource_state: tuple[ResourceReading, ...] = ()
    warehouse_resource_state: tuple[ResourceReading, ...] = ()
    queue_state: str = "empty"
    queue_generation: int = 0
    last_confirmed_start_action_key: str | None = None
    training_duration_seconds: int | None = None
    expected_completion_timestamp: datetime | None = None
    completion_claim_state: str = "not_ready"
    training_policy: str = "once_daily"
    daily_initiation_state: str = "not_started"
    last_successful_training: datetime | None = None
    last_claim_state: str = "none"
    last_dispatch_state: str = "none"
    last_postcondition_state: str = "none"
    next_eligible_timestamp: datetime | None = None
    duplicate_action_keys: tuple[str, ...] = ()
    frame_hashes: tuple[str, ...] = ()


def parse_duration_seconds(text: str) -> int | None:
    """Parse a positively observed HH:MM:SS or multi-day timer."""

    normalized = str(text).strip().lower().replace(" ", "")
    day_match = re.fullmatch(r"(?:(\d+)d)?(\d{1,3}):(\d{2}):(\d{2})", normalized)
    if day_match:
        days = int(day_match.group(1) or 0)
        hours = int(day_match.group(2))
        minutes = int(day_match.group(3))
        seconds = int(day_match.group(4))
        if minutes >= 60 or seconds >= 60:
            return None
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    return None


def parse_quantity(text: str) -> int | None:
    match = re.fullmatch(r"\s*([0-9][0-9,]*)\s*(?:/\s*([0-9][0-9,]*))?\s*", str(text))
    if not match:
        return None
    try:
        quantity = int(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return quantity if quantity >= 0 else None


def resource_readings_exact(resources: Iterable[ResourceReading], *, source: str = "base") -> bool:
    values = tuple(resources)
    return (
        len(values) == len(RESOURCE_NAMES)
        and tuple(resource.name for resource in values) == RESOURCE_NAMES
        and all(
            resource.source == source
            and type(resource.held) is int
            and resource.held >= 0
            and type(resource.required) is int
            and resource.required >= 0
            for resource in values
        )
    )


def all_base_resources_sufficient(resources: Iterable[ResourceReading]) -> bool:
    values = tuple(resources)
    return resource_readings_exact(values) and all(resource.held >= resource.required for resource in values)

def expected_completion_timestamp(dispatched_at: datetime, duration_seconds: int) -> datetime:
    if dispatched_at.tzinfo is None:
        dispatched_at = dispatched_at.replace(tzinfo=timezone.utc)
    if duration_seconds <= 0:
        raise TrainingContractError("training duration must be positive")
    return dispatched_at + __import__("datetime").timedelta(seconds=duration_seconds)


def make_action_key(troop_type: str, reset_identity: str, frame_sha256: str, suffix: str = "train") -> str:
    if troop_type not in TROOP_TYPES or not reset_identity.strip() or not re.fullmatch(r"[0-9a-f]{64}", frame_sha256):
        raise TrainingContractError("action key requires a troop type, reset identity, and frame hash")
    return f"training:{troop_type}:{reset_identity}:{frame_sha256}:{suffix}"


class TrainingController:
    """Pure per-run authorization with durable quota state injected by the caller."""

    def __init__(
        self,
        config: TroopTrainingConfig,
        *,
        reset_identity: str,
        prior_daily_initiations: Iterable[str] = (),
        queue_generations: Mapping[str, int] | None = None,
        pending_start_action_keys: Mapping[str, str] | None = None,
    ) -> None:
        config.validate()
        if not isinstance(reset_identity, str) or not reset_identity.strip():
            raise TrainingContractError("reset identity is required")
        initiated = frozenset(prior_daily_initiations)
        if any(type(item) is not str or item not in TROOP_TYPES for item in initiated):
            raise TrainingContractError("prior daily initiation has an unknown troop type")
        generations = dict(queue_generations or {})
        if set(generations) - set(TROOP_TYPES) or any(
            type(value) is not int or value < 0 for value in generations.values()
        ):
            raise TrainingContractError("queue generations must be nonnegative per-variant integers")
        pending_starts = dict(pending_start_action_keys or {})
        if set(pending_starts) - set(TROOP_TYPES) or any(
            type(value) is not str or not value.strip() or any(character.isspace() for character in value)
            for value in pending_starts.values()
        ):
            raise TrainingContractError("pending start keys must be non-empty per-variant action keys")
        self.config = config
        self.reset_identity = reset_identity
        self.pending_start_action_keys = pending_starts
        self.states = {
            troop_type: TroopWorkflowState(
                troop_type=troop_type,
                facility_identity=FACILITY_BY_TYPE[troop_type],
                reset_identity=reset_identity,
                enabled=config.for_type(troop_type).enabled,
                target_tier=config.for_type(troop_type).target_tier,
                configured_quantity=config.for_type(troop_type).quantity,
                quantity_mode=config.for_type(troop_type).quantity_mode,
                resolved_quantity=None,
                allow_resource_boxes=config.for_type(troop_type).allow_resource_boxes,
                training_policy=config.for_type(troop_type).training_policy,
                daily_initiation_state="initiated" if troop_type in initiated else "not_started",
                queue_generation=generations.get(troop_type, 0),
            )
            for troop_type in TROOP_TYPES
        }
        self._used_action_keys: set[str] = set()
        self._claimed_batches: set[tuple[str, str, str]] = set()

    def _mark_daily_satisfied(self, troop_type: str) -> bool:
        if self.config.for_type(troop_type).training_policy != "once_daily":
            return True
        state = self.states[troop_type]
        self.states[troop_type] = replace(state, daily_initiation_state="initiated")
        return True

    def plan_tier(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if (
            not observation.recognized
            or observation.troop_type != troop_type
            or observation.facility_identity != FACILITY_BY_TYPE[troop_type]
        ):
            return "reject_unknown_training_screen"
        if observation.overlay_state != "none":
            return "reject_overlay"
        if config.target_tier is None:
            return "reject_unconfigured_tier"
        candidate = observation.tier(config.target_tier)
        if candidate is None:
            # A target outside the currently visible carousel may be reached
            # by one bounded horizontal rebind, but only when the current
            # frame proves a contiguous unlocked tier window.  Locked cards
            # beyond the direction of travel are exclusions; gaps, unbound
            # cards, or locked cards between the window and target remain
            # fail-closed ambiguity.
            visible = sorted(
                (item for item in observation.visible_tiers if item.visible),
                key=lambda item: item.tier,
            )
            unlocked = [
                item
                for item in visible
                if not item.locked and not item.question_mark and item.target_roi is not None
            ]
            lower_target = bool(unlocked and config.target_tier < unlocked[0].tier)
            upper_target = bool(unlocked and config.target_tier > unlocked[-1].tier)
            # Locked/question-marked cards outside the direction of travel are
            # exclusions, not ambiguity.  A locked card between the unlocked
            # window and the configured target would make a swipe unsafe.
            blocking_locked = bool(
                unlocked
                and (
                    any(item.locked and item.tier < unlocked[0].tier for item in visible)
                    if lower_target
                    else any(item.locked and item.tier > unlocked[-1].tier for item in visible)
                    if upper_target
                    else False
                )
            )
            if (
                len(unlocked) >= 2
                and all(right.tier - left.tier == 1 for left, right in zip(unlocked, unlocked[1:]))
                and (lower_target or upper_target)
                and not blocking_locked
            ):
                return "select_tier"
            return "reject_ambiguous_tier"
        if candidate.locked:
            return "reject_locked_tier"
        if observation.selected_tier == config.target_tier:
            return "tier_selected"
        return "select_tier"

    def plan_quantity(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if self.plan_tier(observation, troop_type) != "tier_selected":
            return "reject_tier_not_selected"
        maximum = observation.quantity_maximum
        if type(maximum) is not int or maximum <= 0:
            return "reject_numeric_capacity_unresolved"
        if config.quantity_mode == "current_max":
            if type(observation.selected_quantity) is not int or observation.selected_quantity != maximum:
                return "enter_current_max"
            return "quantity_verified"
        if observation.selected_quantity != config.quantity:
            return "enter_exact_quantity"
        if config.quantity is None or config.quantity > maximum:
            return "reject_quantity_above_maximum"
        return "quantity_verified"

    def resolved_quantity(self, observation: TrainingScreenObservation, troop_type: str) -> int | None:
        config = self.config.for_type(troop_type)
        if config.quantity_mode == "current_max":
            maximum = observation.quantity_maximum
            return maximum if type(maximum) is int and maximum > 0 else None
        return config.quantity

    def plan_training(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if not config.enabled or config.training_policy == "disabled":
            return "disabled"
        if self.plan_quantity(observation, troop_type) != "quantity_verified":
            return "reject_quantity_or_tier"
        if observation.queue_active:
            return "reject_active_queue"
        if observation.completion_ready:
            return "reject_completed_queue_requires_claim"
        if (
            observation.queue_label is not None
            or observation.queue_troop_type is not None
            or observation.queue_tier is not None
            or observation.queue_quantity is not None
            or observation.diagnostics.get("duration_source") in {"queue_band", "queue_timer_band"}
        ):
            return "reject_ambiguous_queue_state"
        if config.training_policy == "once_daily" and self.states[troop_type].daily_initiation_state == "initiated":
            return "reject_once_daily_already_initiated"
        if observation.normal_train_target is None or observation.training_duration_seconds is None or observation.training_duration_seconds <= 0:
            return "reject_normal_train_or_duration"
        if observation.train_now_target is not None and observation.normal_train_target == observation.train_now_target:
            return "reject_train_now_target"
        if observation.train_now_target is not None and "train now" not in observation.forbidden_controls:
            # Train Now is expected to be visible, but it is never an allowed target.
            pass
        if observation.premium_popup or any(item in observation.forbidden_controls for item in ("premium", "purchase", "speedup", "resource_item")):
            return "reject_forbidden_control"
        if not resource_readings_exact(observation.resources):
            return "reject_unknown_resources"
        if not all_base_resources_sufficient(observation.resources):
            if observation.warehouse_popup and observation.warehouse_confirm_target is not None and not observation.resource_shortage:
                return "defer_warehouse_confirmation_authority_unavailable"
            if troop_type in {"fighter", "vehicle"} and config.allow_resource_boxes:
                return "defer_resource_shortage_effect_authority_unavailable"
            return "defer_resource_shortage_resource_boxes_disabled"
        return "authorize_normal_train"

    def reconcile_active_queue(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        """Read-only reconciliation for a queue that was already active on entry."""

        if not observation.recognized or observation.troop_type != troop_type:
            return "reject_active_queue_identity"
        config = self.config.for_type(troop_type)
        if observation.facility_identity != FACILITY_BY_TYPE[troop_type] or not observation.queue_active:
            return "reject_active_queue_identity"
        if (
            observation.queue_label is None
            or observation.queue_troop_type is None
            or observation.queue_tier is None
            or observation.queue_quantity is None
        ):
            return "reject_active_queue_label_unresolved"
        if (
            observation.queue_troop_type != troop_type
            or observation.queue_tier != config.target_tier
        ):
            return "reject_active_queue_label_mismatch"
        if config.quantity_mode == "current_max":
            maximum = observation.quantity_maximum
            expected = observation.queue_quantity
            if (
                type(maximum) is not int
                or maximum <= 0
                or expected != maximum
                or observation.selected_quantity != maximum
            ):
                return "reject_active_queue_quantity"
        else:
            expected = self.resolved_quantity(observation, troop_type)
            maximum = observation.quantity_maximum
            if (
                expected is None
                or type(maximum) is not int
                or maximum < expected
                or observation.selected_quantity != expected
                or observation.queue_quantity != expected
            ):
                return "reject_active_queue_quantity"
        if observation.training_duration_seconds is None or observation.training_duration_seconds <= 0:
            return "reject_active_queue_timer_or_tier"
        completion_at = expected_completion_timestamp(datetime.now(timezone.utc), observation.training_duration_seconds)
        previous = self.states[troop_type]
        self.states[troop_type] = replace(
            previous,
            selected_quantity=expected,
            resolved_quantity=expected,
            queue_state="active",
            last_confirmed_start_action_key=self.pending_start_action_keys.get(troop_type),
            training_duration_seconds=observation.training_duration_seconds,
            expected_completion_timestamp=completion_at,
            next_eligible_timestamp=completion_at,
            daily_initiation_state=("initiated" if config.training_policy == "once_daily" else previous.daily_initiation_state),
            last_dispatch_state="reconciled_existing",
            last_postcondition_state="active_queue_read_only_reconciled",
        )
        if config.training_policy == "once_daily" and not self._mark_daily_satisfied(troop_type):
            return "reject_daily_persistence_unresolved"
        return "active_queue_reconciled"

    def plan_resource_box_continuation(
        self,
        before: TrainingScreenObservation,
        popup: AutoUseResourcePopupObservation,
        troop_type: str,
    ) -> str:
        config = self.config.for_type(troop_type)
        if troop_type not in {"fighter", "vehicle"} and not config.allow_resource_boxes:
            return "reject_resource_boxes_disabled"
        if troop_type not in {"fighter", "vehicle"}:
            return "reject_resource_boxes_type_forbidden"
        if not popup.recognized or not popup.resource_boxes_selected or popup.warehouse_only:
            return "reject_unknown_resource_box_popup"
        if popup.cancel_target is None or popup.confirm_target is None:
            return "reject_ambiguous_resource_box_targets"
        resolved_before_quantity = self.resolved_quantity(before, troop_type)
        if before.troop_type != troop_type or before.selected_tier != config.target_tier or resolved_before_quantity is None or before.selected_quantity != resolved_before_quantity:
            return "reject_resource_box_transaction_mismatch"
        # Disabled is a terminal deny based on the exact popup identity and exact configured
        # transaction alone. It must never become unresolved merely because shortage OCR is
        # incomplete; only the non-consequential Cancel target is available in this branch.
        if not config.allow_resource_boxes:
            return "reject_resource_boxes_disabled"
        if self.plan_training(before, troop_type) != "defer_resource_shortage_effect_authority_unavailable":
            return "reject_resource_box_continuation_not_expected"
        before_resources = before.resources_by_name()
        after_resources = {resource.name: resource for resource in popup.resources_after_use}
        if set(before_resources) != set(RESOURCE_NAMES) or set(after_resources) != set(RESOURCE_NAMES):
            return "reject_resource_box_resource_identity"
        if not any(resource.status == "insufficient" for resource in before_resources.values()):
            return "reject_resource_box_without_shortage"
        for name in RESOURCE_NAMES:
            before_required = before_resources[name].required
            after = after_resources[name]
            if before_required is None or after.required != before_required or after.status != "sufficient":
                return "reject_resource_box_amount_mismatch"
        # The recognized popup and projected resource totals do not identify
        # the consumed box count or authorize its effect.
        return "defer_resource_box_effect_authority_unavailable"

    def plan_claim(self, observation: TrainingScreenObservation, *, action_key: str) -> str:
        if (
            not observation.recognized
            or observation.troop_type not in TROOP_TYPES
            or not observation.completion_ready
        ):
            return "reject_claim_not_ready"
        troop_type = observation.troop_type
        config = self.config.for_type(troop_type)
        state = self.states[troop_type]
        start_action_key = self.pending_start_action_keys.get(troop_type)
        if (
            not start_action_key
            or observation.completion_batch_id != start_action_key
            or state.queue_generation <= 0
        ):
            return "reject_claim_identity_unknown"
        if (
            observation.facility_identity != FACILITY_BY_TYPE[troop_type]
            or observation.selected_tier != config.target_tier
            or type(observation.quantity_maximum) is not int
            or observation.quantity_maximum <= 0
        ):
            return "reject_claim_configuration_mismatch"
        if config.quantity_mode == "current_max":
            quantity_matches = observation.selected_quantity == observation.quantity_maximum
        else:
            quantity_matches = (
                observation.selected_quantity == config.quantity
                and config.quantity is not None
                and config.quantity <= observation.quantity_maximum
            )
        if type(observation.selected_quantity) is not int or observation.selected_quantity <= 0 or not quantity_matches:
            return "reject_claim_quantity_mismatch"
        identity = (troop_type, self.reset_identity, start_action_key)
        if identity in self._claimed_batches or action_key in self._used_action_keys:
            return "reject_duplicate_claim"
        self._used_action_keys.add(action_key)
        return "authorize_claim"

    def reconcile_claim(self, before: TrainingScreenObservation, after: TrainingScreenObservation, *, action_key: str) -> bool:
        if action_key not in self._used_action_keys or not before.completion_ready:
            return False
        if not after.recognized or after.completion_ready or after.troop_type != before.troop_type:
            return False
        batch_id = before.completion_batch_id
        if not batch_id:
            return False
        self._claimed_batches.add((before.troop_type or "", self.reset_identity, batch_id))
        state = self.states[before.troop_type or ""]
        self.states[before.troop_type or ""] = replace(state, last_claim_state="confirmed", completion_claim_state="claimed")
        return True

    def commit_training(
        self,
        troop_type: str,
        observation: TrainingScreenObservation,
        *,
        action_key: str,
        dispatched_at: datetime,
        post: TrainingScreenObservation,
    ) -> TroopWorkflowState:
        if action_key in self._used_action_keys:
            raise TrainingContractError("duplicate training action key")
        if self.plan_training(observation, troop_type) != "authorize_normal_train":
            raise TrainingContractError("training preconditions are not authorizeable")
        resolved_quantity = self.resolved_quantity(observation, troop_type)
        if not post.recognized or not post.queue_active or post.training_duration_seconds is None or post.training_duration_seconds <= 0:
            raise TrainingContractError("positive active queue postcondition is required")
        if (
            not isinstance(post.queue_label, str)
            or not post.queue_label.strip()
            or post.queue_troop_type is None
            or post.queue_tier is None
            or post.queue_quantity is None
        ):
            raise TrainingContractError("exact active queue label postcondition is required")
        if post.troop_type != troop_type or post.facility_identity != FACILITY_BY_TYPE[troop_type]:
            raise TrainingContractError("active queue postcondition has mismatched troop or facility")
        if (
            post.queue_troop_type != troop_type
            or post.queue_tier != self.config.for_type(troop_type).target_tier
            or post.queue_quantity != resolved_quantity
        ):
            raise TrainingContractError("active queue label postcondition has mismatched identity")
        if post.selected_tier != observation.selected_tier or post.selected_tier != self.config.for_type(troop_type).target_tier:
            raise TrainingContractError("active queue postcondition has mismatched tier")
        if resolved_quantity is None or post.selected_quantity != resolved_quantity:
            raise TrainingContractError("active queue postcondition has mismatched quantity")
        maximum = post.quantity_maximum
        if type(maximum) is not int or maximum <= 0:
            raise TrainingContractError("numeric post-training capacity is required")
        if (
            self.config.for_type(troop_type).quantity_mode == "current_max"
            and maximum != resolved_quantity
        ) or (
            self.config.for_type(troop_type).quantity_mode == "fixed"
            and resolved_quantity is not None
            and maximum < resolved_quantity
        ):
            raise TrainingContractError("post-training capacity does not match the configured quantity")
        if not resource_readings_exact(post.resources):
            raise TrainingContractError("exact post-training resource readings are required")
        if tuple(item.required for item in post.resources) != tuple(item.required for item in observation.resources):
            raise TrainingContractError("post-training ordinary resource cost changed")
        done_at = expected_completion_timestamp(dispatched_at, post.training_duration_seconds)
        config = self.config.for_type(troop_type)
        previous = self.states[troop_type]
        updated = replace(
            previous,
            tier_unlock_state="unlocked",
            selected_quantity=resolved_quantity,
            resolved_quantity=resolved_quantity,
            base_resource_state=post.resources,
            queue_state="active",
            queue_generation=previous.queue_generation + 1,
            last_confirmed_start_action_key=action_key,
            training_duration_seconds=post.training_duration_seconds,
            expected_completion_timestamp=done_at,
            training_policy=config.training_policy,
            daily_initiation_state="initiated" if config.training_policy == "once_daily" else previous.daily_initiation_state,
            last_successful_training=dispatched_at,
            last_dispatch_state="confirmed",
            last_postcondition_state="active_queue_confirmed",
            next_eligible_timestamp=done_at,
            duplicate_action_keys=previous.duplicate_action_keys + (action_key,),
            frame_hashes=previous.frame_hashes + tuple(item for item in (observation.frame_sha256, post.frame_sha256) if item),
        )
        self.states[troop_type] = updated
        return updated

    def scheduler_state(self, troop_type: str, *, now: datetime | None = None) -> TrainingSchedulerState:
        state = self.states[troop_type]
        now = now or datetime.now(timezone.utc)
        if state.queue_state == "active" and state.expected_completion_timestamp is not None:
            return TrainingSchedulerState(troop_type, "WAIT_UNTIL_COMPLETION", state.expected_completion_timestamp)
        if state.queue_state == "completed_unverified":
            return TrainingSchedulerState(troop_type, "VERIFICATION_PENDING", None)
        if state.training_policy == "once_daily" and state.daily_initiation_state == "initiated":
            return TrainingSchedulerState(troop_type, "WAIT_DAILY_RECONCILIATION", state.next_eligible_timestamp)
        if state.training_policy == "continuous" and state.last_claim_state != "confirmed":
            return TrainingSchedulerState(troop_type, "WAIT_CLAIM_RECONCILIATION", state.next_eligible_timestamp)
        return TrainingSchedulerState(troop_type, "READY", now)



def daily_progress_from_text(text: str, *, frame_sha256: str = "") -> tuple[DailyTrainingProgress, ...]:
    normalized = re.sub(r"\s+", " ", str(text).casefold())
    result: list[DailyTrainingProgress] = []
    for troop_type in TROOP_TYPES:
        match = re.search(rf"{troop_type}.{{0,80}}?(\d{{1,4}})\s*/\s*(250|2[5o0])", normalized)
        if match:
            result.append(DailyTrainingProgress(troop_type, int(match.group(1)), DAILY_TRAINING_QUANTITY, True, frame_sha256))
        else:
            result.append(DailyTrainingProgress(troop_type, None, DAILY_TRAINING_QUANTITY, False, frame_sha256))
    return tuple(result)
