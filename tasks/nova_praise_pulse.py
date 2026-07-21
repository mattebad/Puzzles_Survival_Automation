"""Pulseable Nova Praise reference flow over shared Home primitives.

One invocation performs at most one free Praise when eligible, otherwise returns
deferred / complete_for_reset / blocked / manual_required. Never busy-waits cooldown.
Replay mode emits intended actions and dispatches none.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .home_context import (
    HOME_NAVIGATION_PRIMITIVES_DIGEST,
    HomeContextDecision,
    HomePrimitiveAction,
    HomeReadyObservation,
    ensure_home_ready,
    localize_home,
    navigate_home_building,
)
from .home_atlas import BuildingBinding, ClosedLoopBuildingNavigator, HomeAtlas, LocalizationResult
from .nova_praise import (
    NOVA_PRAISE_TARGET,
    NovaPraiseObservation,
    next_eligible_timestamp,
    nova_authorizeable,
    nova_postcondition_verified,
    nova_remaining,
)
from .scheduler_task_result import SchedulerAwareTaskResult, SchedulerIdentity

NOVA_TASK_ID = "nova_praise"
RESEARCH_LAB_BUILDING_ID = "home.building.research_lab"
# Checked-in product-policy cooldown from retained 2026-07-16 Nova Praise evidence.
DEFAULT_POLICY_COOLDOWN_SECONDS = 300.0


class NovaPulsePhase(str, Enum):
    ENSURE_HOME_READY = "ensure_home_ready"
    LOCALIZE_HOME = "localize_home"
    NAVIGATE_RESEARCH_LAB = "navigate_research_lab"
    TAP_RESEARCH_LAB = "tap_research_lab"
    VERIFY_RADIAL = "verify_radial"
    TAP_NOVA = "tap_nova"
    VERIFY_NOVA_LAB = "verify_nova_lab"
    OPEN_PRAISE = "open_praise"
    READ_ATTEMPTS = "read_attempts"
    DISPATCH_FREE_PRAISE = "dispatch_free_praise"
    VERIFY_POSTCONDITION = "verify_postcondition"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class NovaPulseView:
    """Caller-supplied current-frame facts; no transport ownership here."""

    ready: HomeReadyObservation
    localization: Optional[LocalizationResult] = None
    building_binding: Optional[BuildingBinding] = None
    research_lab_radial_recognized: bool = False
    nova_lab_recognized: bool = False
    praise: Optional[NovaPraiseObservation] = None
    manual_only: bool = False
    reset_id_known: bool = True


@dataclass
class NovaPulseController:
    identity: SchedulerIdentity
    atlas: HomeAtlas
    now: float = 0.0
    replay_mode: bool = True
    policy_cooldown_seconds: float = DEFAULT_POLICY_COOLDOWN_SECONDS
    navigator: ClosedLoopBuildingNavigator | None = None

    def __post_init__(self) -> None:
        if self.identity.task_id != NOVA_TASK_ID:
            raise ValueError("Nova pulse identity task_id must be nova_praise")
        self.intended_actions: list[str] = []
        self.dispatched_actions: list[str] = []
        self.consequential_dispatches = 0
        self._navigator = self.navigator or ClosedLoopBuildingNavigator(self.atlas, RESEARCH_LAB_BUILDING_ID)

    def _emit(self, action: str, *, dispatch: bool = False) -> None:
        self.intended_actions.append(action)
        if dispatch and not self.replay_mode:
            self.dispatched_actions.append(action)

    def pulse(self, view: NovaPulseView) -> SchedulerAwareTaskResult:
        """Run one pulse; at most one consequential free Praise."""

        if view.manual_only or view.ready.manual_only_state:
            return SchedulerAwareTaskResult.manual_required(
                self.identity,
                "MANUAL_ONLY_STATE",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        if not view.reset_id_known or not self.identity.reset_id.strip():
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "RESET_IDENTITY_UNKNOWN",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        ready = ensure_home_ready(view.ready)
        self._emit("ensure_home_ready")
        if ready.level is None:
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                ready.reason.upper(),
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        if view.localization is None:
            self._emit("localize_home")
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "LOCALIZATION_REQUIRED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
                observed_progress={"home_primitives_digest": HOME_NAVIGATION_PRIMITIVES_DIGEST},
            )

        localized = localize_home(view.ready, view.localization)
        self._emit("localize_home")
        if localized.requires_canonical_recovery or localized.level is None:
            self._emit("ensure_canonical_home")
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "CANONICAL_HOME_RECOVERY_REQUIRED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
                observed_progress={"home_primitives_digest": HOME_NAVIGATION_PRIMITIVES_DIGEST},
            )

        # If Praise observation is already available, prefer pulse decision without re-entering.
        if view.praise is not None:
            return self._praise_decision(view.praise)

        # Navigate Research Lab from current localized viewport.
        nav = navigate_home_building(
            self.atlas,
            RESEARCH_LAB_BUILDING_ID,
            view.ready,
            view.localization,
            view.building_binding,
            navigator=self._navigator,
        )
        self._emit("navigate_home_building:home.building.research_lab")
        if nav.requires_canonical_recovery:
            self._emit("ensure_canonical_home")
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "CANONICAL_HOME_RECOVERY_REQUIRED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        if nav.action is HomePrimitiveAction.PAN:
            self._emit("pan", dispatch=True)
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "NAVIGATION_PAN_PENDING_FRESH_FRAME",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
                observed_progress={"nav_reason": nav.reason},
            )
        if nav.action is HomePrimitiveAction.BIND_BUILDING:
            self._emit("bind_research_lab")
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "RESEARCH_LAB_BINDING_REQUIRED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        if nav.action is HomePrimitiveAction.TAP_BUILDING:
            self._emit("tap_research_lab", dispatch=True)
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "RESEARCH_LAB_TAP_PENDING_RADIAL",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        if not view.research_lab_radial_recognized:
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "RESEARCH_LAB_RADIAL_NOT_RECOGNIZED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        self._emit("tap_nova", dispatch=True)
        if not view.nova_lab_recognized:
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "NOVA_LAB_NOT_RECOGNIZED",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        self._emit("open_praise")
        return SchedulerAwareTaskResult.blocked(
            self.identity,
            "PRAISE_OBSERVATION_REQUIRED",
            intended_actions=tuple(self.intended_actions),
            dispatched_actions=tuple(self.dispatched_actions),
        )

    def _praise_decision(self, observation: NovaPraiseObservation) -> SchedulerAwareTaskResult:
        self._emit("read_interaction_attempts")
        remaining = nova_remaining(observation)
        if remaining is None:
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "ATTEMPTS_UNKNOWN",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        if remaining == 0:
            return SchedulerAwareTaskResult.complete_for_reset(
                self.identity,
                "NOVA_PRAISE_ATTEMPTS_CONSUMED",
                observed_progress={"attempts_remaining": 0},
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        eligible = next_eligible_timestamp(observation, now=self.now)
        cooling = (
            observation.cooldown_active
            or (observation.cooldown_seconds is not None and observation.cooldown_seconds > 0)
            or (eligible is not None and eligible > self.now)
            or not observation.praise_enabled
        )
        if cooling and not nova_authorizeable(observation, now=self.now):
            next_at = eligible if eligible is not None and eligible > self.now else self.now + self.policy_cooldown_seconds
            return SchedulerAwareTaskResult.deferred(
                self.identity,
                "NOVA_PRAISE_COOLDOWN",
                next_at,
                observed_progress={"attempts_remaining": remaining},
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        if not nova_authorizeable(observation, now=self.now):
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "NO_AUTHORIZED_FREE_PRAISE",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        if self.consequential_dispatches >= 1:
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "ONE_PRAISE_PER_INVOCATION",
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )

        self._emit("prepare_free_praise")
        self._emit("dispatch_free_praise", dispatch=True)
        self.consequential_dispatches += 1
        # Replay/dry path: emit intended dispatch without transport and without claiming verified postcondition.
        if self.replay_mode:
            return SchedulerAwareTaskResult.action_performed(
                self.identity,
                "FREE_PRAISE_INTENDED_REPLAY_NO_DISPATCH",
                action_count=1,
                observed_progress={"attempts_remaining_before": remaining},
                consequence={"free_only": True, "maximum_cost": 0, "quantity": 1, "target": NOVA_PRAISE_TARGET},
                next_eligible_at=self.now + self.policy_cooldown_seconds,
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        return SchedulerAwareTaskResult.blocked(
            self.identity,
            "AWAITING_PRAISE_POSTCONDITION",
            action_count=1,
            unresolved_action=True,
            observed_progress={"attempts_remaining_before": remaining},
            consequence={"free_only": True, "maximum_cost": 0, "quantity": 1, "target": NOVA_PRAISE_TARGET},
            intended_actions=tuple(self.intended_actions),
            dispatched_actions=tuple(self.dispatched_actions),
        )

    def accept_praise_postcondition(
        self,
        before: NovaPraiseObservation,
        after: NovaPraiseObservation,
    ) -> SchedulerAwareTaskResult:
        if not nova_postcondition_verified(before, after, now=self.now):
            return SchedulerAwareTaskResult.blocked(
                self.identity,
                "NOVA_PRAISE_POSTCONDITION_NOT_PROVEN",
                unresolved_action=True,
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        remaining = after.attempts_remaining
        if remaining == 0:
            return SchedulerAwareTaskResult.complete_for_reset(
                self.identity,
                "NOVA_PRAISE_ATTEMPTS_CONSUMED",
                action_count=1,
                observed_progress={"attempts_remaining": 0},
                consequence={"free_only": True, "maximum_cost": 0, "quantity": 1},
                intended_actions=tuple(self.intended_actions),
                dispatched_actions=tuple(self.dispatched_actions),
            )
        next_at = next_eligible_timestamp(after, now=self.now)
        if next_at is None:
            next_at = self.now + self.policy_cooldown_seconds
        return SchedulerAwareTaskResult.action_performed(
            self.identity,
            "FREE_PRAISE_VERIFIED",
            action_count=1,
            observed_progress={"attempts_remaining": remaining},
            consequence={"free_only": True, "maximum_cost": 0, "quantity": 1},
            next_eligible_at=next_at,
            intended_actions=tuple(self.intended_actions),
            dispatched_actions=tuple(self.dispatched_actions),
        )


def describe_home_nav_decision(decision: HomeContextDecision) -> str:
    return f"{decision.level.value if decision.level else 'none'}:{decision.action.value}:{decision.reason}"
