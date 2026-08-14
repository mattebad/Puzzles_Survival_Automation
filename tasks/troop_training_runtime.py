"""Deterministic, transport-free controller for a bounded troop-training run."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from .troop_training import (
    TROOP_TYPES,
    TrainingController,
    TrainingScreenObservation,
    TroopTrainingConfig,
    TroopWorkflowState,
    make_action_key,
)


class TrainingPhase(str, Enum):
    HOME = "home"
    FACILITY_MENU = "facility_menu"
    TRAINING_SCREEN = "training_screen"
    TIER_SELECTION = "tier_selection"
    QUANTITY_ENTRY = "quantity_entry"
    READY_TO_TRAIN = "ready_to_train"
    TRAINING_ACTIVE = "training_active"
    CLAIM_READY = "claim_ready"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TrainingDecision:
    phase: TrainingPhase
    action: str
    reason: str
    troop_type: str
    action_key: str | None = None


class TroopTrainingRuntimeController:
    """State machine that never supplies transport or chooses a fallback tier."""

    def __init__(self, config: TroopTrainingConfig, *, reset_identity: str, persistence_path: Path | None = None):
        self.semantic = TrainingController(config, reset_identity=reset_identity, persistence_path=persistence_path)
        self.phase = TrainingPhase.HOME
        self.unresolved_action: str | None = None

    @property
    def states(self) -> dict[str, TroopWorkflowState]:
        return self.semantic.states

    def begin_facility(self, troop_type: str, frame_sha256: str) -> TrainingDecision:
        if troop_type not in TROOP_TYPES:
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", "unknown troop type", troop_type)
        if not self.semantic.config.for_type(troop_type).enabled:
            self.phase = TrainingPhase.COMPLETE
            return TrainingDecision(self.phase, "skip", "troop workflow disabled", troop_type)
        self.phase = TrainingPhase.TRAINING_SCREEN
        return TrainingDecision(self.phase, "open_training", "facility identity bound", troop_type, make_action_key(troop_type, self.semantic.reset_identity, frame_sha256, "open"))

    def observe_training(self, observation: TrainingScreenObservation, troop_type: str) -> TrainingDecision:
        if self.unresolved_action is not None:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", "prior consequential action unresolved", troop_type, self.unresolved_action)
        if observation.queue_active:
            queue_plan = self.semantic.reconcile_active_queue(observation, troop_type)
            if queue_plan == "active_queue_reconciled":
                self.phase = TrainingPhase.TRAINING_ACTIVE
                return TrainingDecision(self.phase, "reconcile_queue", "matching active queue reconciled read-only; no dispatch", troop_type)
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", queue_plan, troop_type)
        tier_plan = self.semantic.plan_tier(observation, troop_type)
        if tier_plan == "reject_locked_tier":
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", tier_plan, troop_type)
        if tier_plan not in {"tier_selected", "select_tier"}:
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", tier_plan, troop_type)
        if tier_plan == "select_tier":
            self.phase = TrainingPhase.TIER_SELECTION
            return TrainingDecision(self.phase, "select_tier", "configured tier is not selected", troop_type)
        quantity_plan = self.semantic.plan_quantity(observation, troop_type)
        if quantity_plan in {"enter_exact_quantity", "enter_current_max"}:
            self.phase = TrainingPhase.QUANTITY_ENTRY
            reason = "current numeric maximum is not displayed exactly" if quantity_plan == "enter_current_max" else "configured quantity is not displayed exactly"
            return TrainingDecision(self.phase, "enter_quantity", reason, troop_type)
        if quantity_plan != "quantity_verified":
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", quantity_plan, troop_type)
        start_plan = self.semantic.plan_training(observation, troop_type)
        if start_plan in {"authorize_normal_train", "authorize_normal_train_expected_warehouse"}:
            self.phase = TrainingPhase.READY_TO_TRAIN
            return TrainingDecision(self.phase, "start_training", "normal timed Train is authorized", troop_type)
        self.phase = TrainingPhase.BLOCKED
        return TrainingDecision(self.phase, "stop", start_plan, troop_type)

    def dispatch_started(self, troop_type: str, action_key: str) -> TrainingDecision:
        if self.phase != TrainingPhase.READY_TO_TRAIN:
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", "training dispatch was not pre-authorized", troop_type, action_key)
        self.unresolved_action = action_key
        self.phase = TrainingPhase.UNRESOLVED
        return TrainingDecision(self.phase, "await_postcondition", "one training initiation is unresolved", troop_type, action_key)

    def reconcile_started(self, troop_type: str, before: TrainingScreenObservation, post: TrainingScreenObservation, *, action_key: str, dispatched_at):
        if self.unresolved_action != action_key:
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", "action key does not match unresolved training", troop_type, action_key)
        try:
            self.semantic.commit_training(troop_type, before, action_key=action_key, dispatched_at=dispatched_at, post=post)
        except Exception as exc:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", f"training postcondition unresolved: {exc}", troop_type, action_key)
        self.unresolved_action = None
        self.phase = TrainingPhase.TRAINING_ACTIVE
        return TrainingDecision(self.phase, "yield", "active queue and timer positively reconciled", troop_type, action_key)

    def reconcile_failed_started(
        self,
        troop_type: str,
        post: TrainingScreenObservation,
        *,
        action_key: str,
        reason: str,
    ) -> TrainingDecision:
        """Terminally reconcile a dispatched Train that positively produced no queue."""

        if self.unresolved_action != action_key:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", "action key does not match unresolved training", troop_type, action_key)
        if not post.recognized or post.troop_type != troop_type or post.queue_active:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", "failed Train successor is not positively queue-empty", troop_type, action_key)
        previous = self.semantic.states[troop_type]
        self.semantic.states[troop_type] = replace(
            previous,
            selected_quantity=post.selected_quantity,
            base_resource_state=post.resources,
            last_dispatch_state="failed_confirmed",
            last_postcondition_state=reason,
            duplicate_action_keys=previous.duplicate_action_keys + (action_key,),
            frame_hashes=previous.frame_hashes + ((post.frame_sha256,) if post.frame_sha256 else ()),
        )
        self.unresolved_action = None
        self.phase = TrainingPhase.BLOCKED
        return TrainingDecision(self.phase, "stop", reason, troop_type, action_key)

    def mark_claim_ready(self, troop_type: str, observation: TrainingScreenObservation) -> TrainingDecision:
        if self.unresolved_action is not None:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", "prior action unresolved", troop_type)
        if not observation.completion_ready:
            self.phase = TrainingPhase.BLOCKED
            return TrainingDecision(self.phase, "stop", "completion not positively recognized", troop_type)
        self.phase = TrainingPhase.CLAIM_READY
        return TrainingDecision(self.phase, "claim", "completed batch positively recognized", troop_type)

    def final_home(self) -> TrainingDecision:
        if self.unresolved_action is not None:
            self.phase = TrainingPhase.UNRESOLVED
            return TrainingDecision(self.phase, "stop", "cannot leave unresolved action", "aggregate")
        self.phase = TrainingPhase.COMPLETE
        return TrainingDecision(self.phase, "return_home", "all bounded authorized work reconciled", "aggregate")
