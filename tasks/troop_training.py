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
    quantity: int = DAILY_TRAINING_QUANTITY
    training_policy: str = "once_daily"
    allow_resource_boxes: bool = False

    def validate(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(self.allow_resource_boxes, bool):
            raise TrainingContractError("enabled and allow_resource_boxes must be booleans")
        if self.training_policy not in TRAINING_POLICIES:
            raise TrainingContractError(f"unknown training policy: {self.training_policy!r}")
        if not isinstance(self.quantity, int) or not 1 <= self.quantity <= MAX_QUANTITY:
            raise TrainingContractError("quantity must be an integer from 1 through 1000")
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
            getattr(self, troop_type).validate()

    def for_type(self, troop_type: str) -> TrainingConfig:
        if troop_type not in TROOP_TYPES:
            raise TrainingContractError(f"unknown troop type: {troop_type!r}")
        return getattr(self, troop_type)


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
    configured_quantity: int = DAILY_TRAINING_QUANTITY
    allow_resource_boxes: bool = False
    selected_quantity: int | None = None
    base_resource_state: tuple[ResourceReading, ...] = ()
    warehouse_resource_state: tuple[ResourceReading, ...] = ()
    queue_state: str = "empty"
    training_duration_seconds: int | None = None
    expected_completion_timestamp: datetime | None = None
    completion_claim_state: str = "not_ready"
    training_policy: str = "once_daily"
    daily_initiation_state: str = "not_started"
    daily_progress_state: str = "unknown"
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


def all_base_resources_sufficient(resources: Iterable[ResourceReading]) -> bool:
    values = tuple(resources)
    return bool(values) and all(resource.source == "base" and resource.status == "sufficient" for resource in values)


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
    """Pure deterministic authorization and reconciliation for one reset cycle."""

    def __init__(self, config: TroopTrainingConfig, *, reset_identity: str):
        config.validate()
        if not reset_identity.strip():
            raise TrainingContractError("reset identity is required")
        self.config = config
        self.reset_identity = reset_identity
        self.states = {
            troop_type: TroopWorkflowState(
                troop_type=troop_type,
                facility_identity=FACILITY_BY_TYPE[troop_type],
                reset_identity=reset_identity,
                enabled=config.for_type(troop_type).enabled,
                target_tier=config.for_type(troop_type).target_tier,
                configured_quantity=config.for_type(troop_type).quantity,
                allow_resource_boxes=config.for_type(troop_type).allow_resource_boxes,
                training_policy=config.for_type(troop_type).training_policy,
            )
            for troop_type in TROOP_TYPES
        }
        self._used_action_keys: set[str] = set()
        self._claimed_batches: set[tuple[str, str, str]] = set()

    def plan_tier(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if not observation.recognized or observation.troop_type != troop_type:
            return "reject_unknown_training_screen"
        if observation.overlay_state != "none":
            return "reject_overlay"
        if config.target_tier is None:
            return "reject_unconfigured_tier"
        candidate = observation.tier(config.target_tier)
        if candidate is not None and candidate.locked:
            return "reject_locked_tier"
        if observation.selected_tier == config.target_tier:
            return "tier_selected"
        return "select_tier"

    def plan_quantity(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if self.plan_tier(observation, troop_type) != "tier_selected":
            return "reject_tier_not_selected"
        if observation.selected_quantity != config.quantity:
            return "enter_exact_quantity"
        if observation.quantity_maximum is not None and config.quantity > observation.quantity_maximum:
            return "reject_quantity_above_maximum"
        return "quantity_verified"

    def plan_training(self, observation: TrainingScreenObservation, troop_type: str) -> str:
        config = self.config.for_type(troop_type)
        if not config.enabled or config.training_policy == "disabled":
            return "disabled"
        if self.plan_quantity(observation, troop_type) != "quantity_verified":
            return "reject_quantity_or_tier"
        if observation.queue_active:
            return "reject_active_queue"
        if observation.normal_train_target is None or observation.training_duration_seconds is None:
            return "reject_normal_train_or_duration"
        if observation.train_now_target is not None and "train now" not in observation.forbidden_controls:
            # Train Now is expected to be visible, but it is never an allowed target.
            pass
        if observation.premium_popup or any(item in observation.forbidden_controls for item in ("premium", "purchase", "speedup", "resource_item")):
            return "reject_forbidden_control"
        if not observation.resources:
            return "reject_unknown_resources"
        if not all_base_resources_sufficient(observation.resources):
            if observation.warehouse_popup and observation.warehouse_confirm_target is not None and not observation.resource_shortage:
                return "warehouse_confirmation_required"
            # A known base shortage may proceed once to the normal Train control.  The live
            # successor must then prove an exact warehouse-only confirmation before any second
            # input.  Unknown resources and any forbidden source remain blocked above.
            if all(resource.held is not None and resource.required is not None for resource in observation.resources):
                return "authorize_normal_train_expected_warehouse"
            return "reject_resource_sufficiency"
        return "authorize_normal_train"

    def plan_resource_box_continuation(
        self,
        before: TrainingScreenObservation,
        popup: AutoUseResourcePopupObservation,
        troop_type: str,
    ) -> str:
        config = self.config.for_type(troop_type)
        if not popup.recognized or not popup.resource_boxes_selected or popup.warehouse_only:
            return "reject_unknown_resource_box_popup"
        if popup.cancel_target is None or popup.confirm_target is None:
            return "reject_ambiguous_resource_box_targets"
        if before.troop_type != troop_type or before.selected_tier != config.target_tier or before.selected_quantity != config.quantity:
            return "reject_resource_box_transaction_mismatch"
        # Disabled is a terminal deny based on the exact popup identity and exact configured
        # transaction alone. It must never become unresolved merely because shortage OCR is
        # incomplete; only the non-consequential Cancel target is available in this branch.
        if not config.allow_resource_boxes:
            return "reject_resource_boxes_disabled"
        if self.plan_training(before, troop_type) != "authorize_normal_train_expected_warehouse":
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
        return "authorize_resource_box_confirmation"

    def prove_resource_boxes_applied(
        self,
        before: TrainingScreenObservation,
        popup: AutoUseResourcePopupObservation,
        after: TrainingScreenObservation,
        troop_type: str,
    ) -> bool:
        """Prove resource acquisition when Auto Use returns queue-empty instead of training."""

        if self.plan_resource_box_continuation(before, popup, troop_type) != "authorize_resource_box_confirmation":
            return False
        if (
            not after.recognized
            or after.troop_type != troop_type
            or after.selected_tier != before.selected_tier
            or after.queue_active
        ):
            return False
        before_resources = before.resources_by_name()
        popup_resources = {resource.name: resource for resource in popup.resources_after_use}
        after_resources = after.resources_by_name()
        if set(before_resources) != set(RESOURCE_NAMES) or set(after_resources) != set(RESOURCE_NAMES):
            return False
        increase_seen = False
        for name in RESOURCE_NAMES:
            before_held = before_resources[name].held
            popup_held = popup_resources[name].held
            after_held = after_resources[name].held
            if before_held is None or popup_held is None or after_held != popup_held or after_held < before_held:
                return False
            increase_seen = increase_seen or after_held > before_held
        return increase_seen

    def plan_claim(self, observation: TrainingScreenObservation, *, action_key: str) -> str:
        if not observation.recognized or not observation.troop_type or not observation.completion_ready:
            return "reject_claim_not_ready"
        batch_id = observation.completion_batch_id
        if not batch_id:
            return "reject_claim_identity_unknown"
        identity = (observation.troop_type, self.reset_identity, batch_id)
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
        if self.plan_training(observation, troop_type) not in {
            "authorize_normal_train",
            "authorize_normal_train_expected_warehouse",
        }:
            raise TrainingContractError("training preconditions are not authorizeable")
        if not post.recognized or not post.queue_active or post.training_duration_seconds is None:
            raise TrainingContractError("positive active queue postcondition is required")
        self._used_action_keys.add(action_key)
        done_at = expected_completion_timestamp(dispatched_at, post.training_duration_seconds)
        config = self.config.for_type(troop_type)
        previous = self.states[troop_type]
        updated = replace(
            previous,
            tier_unlock_state="unlocked",
            selected_quantity=config.quantity,
            base_resource_state=post.resources,
            queue_state="active",
            training_duration_seconds=post.training_duration_seconds,
            expected_completion_timestamp=done_at,
            training_policy=config.training_policy,
            daily_initiation_state="initiated" if config.training_policy == "once_daily" else previous.daily_initiation_state,
            daily_progress_state="initiated",
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

    def aggregate_daily(self) -> dict[str, object]:
        return {
            "fighter": self.states["fighter"].daily_progress_state,
            "shooter": self.states["shooter"].daily_progress_state,
            "rider": self.states["rider"].daily_progress_state,
            "vehicle": self.states["vehicle"].daily_progress_state,
            "total_training_initiations_completed": sum(
                state.last_dispatch_state == "confirmed" for state in self.states.values()
            ),
            "claim_separate_and_dormant": True,
        }


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
