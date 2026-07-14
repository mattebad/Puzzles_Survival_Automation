"""Deterministic Daily Quest task contracts and route dispatch.

This module owns task semantics, not ADB.  Device access remains injected through the existing
safe_action_core executor and navigation runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping, Optional

from .catalog import objective_for_text
from .contracts import ActionTransactionSpec, AnchorSpec, NavigationStep, ROI, TaskOutcome, TaskResult
from .profile import (
    HELP_ALL_ACTION,
    HOME_MORE,
    HOME_RIGHT,
    INDIVIDUAL_HELP_ACTION,
    MIGHT_PRAISE_ACTION,
    PERSONAL_MIGHT_BACK,
    PERSONAL_MIGHT_CHECK,
    PERSONAL_MIGHT_LEADERBOARD,
    PERSONAL_MIGHT_ROW,
    RANKINGS_BACK,
    RANKINGS_ENTRY,
    RESET_POPUP_CLOSE,
)


ALLIANCE_HELP_ROUTE = "daily_go_to_alliance_help"
PERSONAL_MIGHT_PRAISE_ROUTE = "daily_go_to_personal_might"
RESET_POPUP_DISMISS_ROUTE = "reset_popup_close_to_home"


class RouteType(str, Enum):
    DAILY_QUEST = "DAILY_QUEST"
    DIRECT_TASK_SCREEN = "DIRECT_TASK_SCREEN"
    HOME_WITH_HIGHLIGHTED_BUILDING = "HOME_WITH_HIGHLIGHTED_BUILDING"
    HOME_SEARCH_REQUIRED = "HOME_SEARCH_REQUIRED"
    ALLIANCE = "ALLIANCE"
    WORLD = "WORLD"
    CASH_MALL = "CASH_MALL"
    UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK = "UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK"
    ACCOUNT_OR_SESSION_HARD_STOP = "ACCOUNT_OR_SESSION_HARD_STOP"
    UNKNOWN_UNSAFE = "UNKNOWN_UNSAFE"


@dataclass(frozen=True)
class RouteObservation:
    state: Optional[str]
    recognized: bool
    source_family: Optional[str] = None
    highlighted_building: bool = False
    search_required: bool = False
    hard_stop: bool = False
    verified_back: bool = False


class RouteDispatcher:
    """Classify a Go destination without assuming one universal route."""

    def classify(self, observation: RouteObservation | Mapping[str, Any]) -> RouteType:
        if isinstance(observation, Mapping):
            observation = RouteObservation(
                state=observation.get("state"),
                recognized=bool(observation.get("recognized")),
                source_family=observation.get("source_family"),
                highlighted_building=bool(observation.get("highlighted_building")),
                search_required=bool(observation.get("search_required")),
                hard_stop=bool(observation.get("hard_stop")),
                verified_back=bool(observation.get("verified_back")),
            )
        if observation.hard_stop:
            return RouteType.ACCOUNT_OR_SESSION_HARD_STOP
        state = (observation.state or "").upper().replace("-", "_")
        if state in {"DAILY_QUEST", "DAILYQUEST"}:
            return RouteType.DAILY_QUEST
        if state in {"HOME_BASE", "HOME/BASE", "HOME"}:
            if observation.highlighted_building:
                return RouteType.HOME_WITH_HIGHLIGHTED_BUILDING
            if observation.search_required:
                return RouteType.HOME_SEARCH_REQUIRED
        if state in {"ALLIANCE", "SPEEDUP_HELP"}:
            return RouteType.ALLIANCE
        if state == "WORLD":
            return RouteType.WORLD
        if state == "CASH_MALL":
            return RouteType.CASH_MALL
        if observation.source_family == "promotional" and observation.verified_back:
            return RouteType.UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK
        if observation.recognized and state:
            return RouteType.DIRECT_TASK_SCREEN
        return RouteType.UNKNOWN_UNSAFE


    def outcome_for(self, route: RouteType) -> TaskResult:
        if route in {RouteType.DAILY_QUEST, RouteType.DIRECT_TASK_SCREEN, RouteType.ALLIANCE,
                     RouteType.HOME_WITH_HIGHLIGHTED_BUILDING, RouteType.HOME_SEARCH_REQUIRED,
                     RouteType.CASH_MALL}:
            return TaskResult.progress("recognized supported route", route.value)
        if route == RouteType.WORLD:
            return TaskResult(TaskOutcome.BLOCKED, "world route is unsupported for the zero-cost MVP", verified=True, state=route.value)
        if route == RouteType.UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK:
            return TaskResult(TaskOutcome.RETRY, "bounded verified promotional Back recovery required", verified=True, state=route.value)
        if route == RouteType.ACCOUNT_OR_SESSION_HARD_STOP:
            return TaskResult(TaskOutcome.FAILED_SAFE, "account or session hard stop", verified=False, state=route.value)
        return TaskResult(TaskOutcome.FAILED_SAFE, "unknown unsafe route", verified=False, state=route.value)


@dataclass(frozen=True)
class AllianceHelpObservation:
    """Semantic evidence for the Speedup Help / Help All transaction."""

    screen_state: str
    objective_name: str
    current_progress: int
    required_progress: int
    target_identity: str
    target_roi: ROI
    zero_cost_evidence: bool
    available_request_count: Optional[int] = None
    help_all_visible: bool = False
    individual_help_visible: bool = False
    request_controls_count: Optional[int] = None
    empty_state: bool = False
    no_help_request_visible: bool = False
    overlay_state: str = "none_observed"
    forbidden_region_intersects_target: bool = False
    recognized: bool = True


class AllianceHelpHandler:
    """Choose one Help All action, or one individual Help fallback, per pulse."""

    objective_name = "Help allies"
    consequence = "alliance_help_zero_cost"
    route_name = "daily_go_to_speedup_help"

    @classmethod
    def matches_objective(cls, name: str) -> bool:
        return " ".join(name.lower().split()) == cls.objective_name.lower()

    @classmethod
    def selected_action_kind(cls, observation: AllianceHelpObservation) -> Optional[str]:
        if observation.help_all_visible:
            return "ALLIANCE_HELP_ALL"
        if observation.individual_help_visible:
            return "ALLIANCE_HELP_ONE"
        return None

    @classmethod
    def expected_anchor(cls, observation: AllianceHelpObservation):
        return HELP_ALL_ACTION if cls.selected_action_kind(observation) == "ALLIANCE_HELP_ALL" else INDIVIDUAL_HELP_ACTION

    @classmethod
    def remaining(cls, observation: AllianceHelpObservation) -> Optional[int]:
        if not observation.recognized or observation.required_progress < 0:
            return None
        if observation.current_progress < 0 or observation.current_progress > observation.required_progress:
            return None
        return observation.required_progress - observation.current_progress

    @classmethod
    def authorizeable(cls, observation: AllianceHelpObservation) -> bool:
        remaining = cls.remaining(observation)
        return bool(
            observation.screen_state in {RouteType.ALLIANCE.value, "SPEEDUP_HELP"}
            and cls.matches_objective(observation.objective_name)
            and remaining is not None and remaining > 0
            and cls.selected_action_kind(observation) is not None
            and observation.target_identity == cls.expected_anchor(observation).name
            and observation.target_roi == cls.expected_anchor(observation).roi
            and observation.zero_cost_evidence
            and observation.overlay_state in {"none", "none_observed"}
            and not observation.forbidden_region_intersects_target
        )

    @classmethod
    def transaction_spec(cls, observation: AllianceHelpObservation) -> ActionTransactionSpec:
        if not cls.authorizeable(observation):
            raise ValueError("Speedup Help action preconditions are not positively recognized")
        action_kind = cls.selected_action_kind(observation)
        return ActionTransactionSpec(
            action_kind=action_kind,
            expected_source_screen="SPEEDUP_HELP",
            subject=cls.objective_name,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            allowed_confirmation_dialogs=(),
            semantic_preconditions=("speedup_help_screen", "exact_help_target", "explicit_zero_cost", "remaining_count_positive"),
            semantic_postconditions=("selected_help_control_or_request_disappears", "daily_objective_progress_increases"),
        )

    @classmethod
    def postcondition_verified(cls, before: AllianceHelpObservation, after: AllianceHelpObservation) -> bool:
        before_remaining = cls.remaining(before)
        after_remaining = cls.remaining(after)
        if before_remaining is None or after_remaining is None:
            return False
        if not cls.matches_objective(after.objective_name):
            return False
        if after.screen_state not in {RouteType.ALLIANCE.value, "SPEEDUP_HELP"}:
            return False
        progress_increased = after.current_progress > before.current_progress
        request_count_decreased = (
            before.available_request_count is not None
            and after.available_request_count is not None
            and after.available_request_count < before.available_request_count
        )
        control_count_decreased = (
            before.request_controls_count is not None
            and after.request_controls_count is not None
            and after.request_controls_count < before.request_controls_count
        )
        empty_state_reached = after.empty_state or (
            after.available_request_count is not None and after.available_request_count == 0
        )
        return (progress_increased or request_count_decreased or control_count_decreased
                or empty_state_reached or after.no_help_request_visible)

    @classmethod
    def perform_one_pulse(cls, before: AllianceHelpObservation, after: Optional[AllianceHelpObservation] = None) -> TaskResult:
        if not cls.authorizeable(before):
            return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_HELP_TARGET", verified=True, state="SPEEDUP_HELP")
        if after is None:
            return TaskResult.progress(cls.selected_action_kind(before) + " is authorized; dispatch one ActionTransaction", "SPEEDUP_HELP")
        if not cls.postcondition_verified(before, after):
            return TaskResult(TaskOutcome.FAILED_SAFE, "HELP_POSTCONDITION_NOT_PROVEN", state="SPEEDUP_HELP")
        if after.no_help_request_visible:
            return TaskResult(TaskOutcome.BLOCKED, "NO_HELP_REQUEST_CURRENTLY", verified=True, state="SPEEDUP_HELP")
        remaining = cls.remaining(after)
        if remaining == 0:
            return TaskResult.done("Help allies objective is complete", "daily:help_allies:complete", "SPEEDUP_HELP")
        return TaskResult.progress("one Help action changed the available request state", "SPEEDUP_HELP")

    @classmethod
    def completion_check(cls, observation: AllianceHelpObservation) -> bool:
        return cls.remaining(observation) == 0

    @classmethod
    def next_eligible_time(cls, observation: AllianceHelpObservation) -> Optional[float]:
        # Availability/cooldown scheduling is supplied by the later service scheduler.
        return None


@dataclass(frozen=True)
class PraiseObservation:
    """Semantic evidence for one Personal Might Praise control."""

    screen_state: str
    objective_name: str
    current_progress: int
    required_progress: int
    target_identity: str
    target_roi: ROI
    leaderboard_identity: bool
    might_region_identity: bool
    target_visible: bool
    zero_cost_evidence: bool
    game_day_id: Optional[str]
    already_praised: bool = False
    cooldown_active: bool = False
    praise_disabled: bool = False
    praise_count: Optional[int] = None
    overlay_state: str = "none_observed"
    forbidden_region_intersects_target: bool = False
    reset_guard_active: bool = False
    recognized: bool = True


@dataclass(frozen=True)
class DailyQuestClaimObservation:
    """Exact row-local evidence required before ordinary Daily Quest Claim."""

    screen_state: str
    selected_daily_quest: bool
    objective_name: str
    current_progress: int
    required_progress: int
    row_bounds: ROI
    target_identity: str
    target_roi: ROI
    control_class: str
    row_fully_visible: bool
    claim_fully_visible: bool
    milestone_reward: bool = False
    clipped: bool = False
    overlay_state: str = "none_observed"
    game_day_id: Optional[str] = None
    reset_guard_active: bool = False
    recognized: bool = True


class PersonalMightPraiseHandler:
    """Bounded Personal Might route and one zero-cost Praise transaction."""

    objective_key = "personal_might_praise"
    objective_aliases = ("Praise 1x in Personal Might rank", "Personal Might praise")
    route_name = PERSONAL_MIGHT_PRAISE_ROUTE
    consequence = "praise_zero_cost"
    action_kind = "PRAISE_PERSONAL_MIGHT"

    @classmethod
    def matches_objective(cls, name: str) -> bool:
        spec = objective_for_text(name)
        return bool(spec and spec.objective_key == cls.objective_key)

    @staticmethod
    def parse_progress(text: str) -> Optional[tuple[int, int]]:
        match = re.search(r"\b(\d+)\s*/\s*(\d+)\b", text)
        if not match:
            return None
        current, required = (int(value) for value in match.groups())
        if required < 1 or current < 0 or current > required:
            return None
        return current, required

    @classmethod
    def remaining(cls, observation: PraiseObservation) -> Optional[int]:
        if not observation.recognized or not cls.matches_objective(observation.objective_name):
            return None
        if observation.current_progress < 0 or observation.required_progress < 1:
            return None
        if observation.current_progress > observation.required_progress:
            return None
        return observation.required_progress - observation.current_progress

    @classmethod
    def authorizeable(cls, observation: PraiseObservation, action_recorded_today: bool = False) -> bool:
        return bool(
            observation.screen_state == "PERSONAL_MIGHT_LEADERBOARD"
            and cls.matches_objective(observation.objective_name)
            and cls.remaining(observation) == 1
            and observation.leaderboard_identity
            and observation.might_region_identity
            and observation.target_visible
            and observation.target_identity == MIGHT_PRAISE_ACTION.name
            and observation.target_roi == MIGHT_PRAISE_ACTION.roi
            and observation.zero_cost_evidence
            and bool(observation.game_day_id)
            and not observation.already_praised
            and not observation.cooldown_active
            and not observation.praise_disabled
            and observation.overlay_state in {"none", "none_observed"}
            and not observation.forbidden_region_intersects_target
            and not observation.reset_guard_active
            and not action_recorded_today
        )

    @classmethod
    def transaction_spec(cls, observation: PraiseObservation) -> ActionTransactionSpec:
        if not cls.authorizeable(observation):
            raise ValueError("Personal Might Praise preconditions are not positively recognized")
        return ActionTransactionSpec(
            action_kind=cls.action_kind,
            expected_source_screen="PERSONAL_MIGHT_LEADERBOARD",
            subject=cls.objective_aliases[0],
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            allowed_confirmation_dialogs=(),
            semantic_preconditions=(
                "personal_might_leaderboard",
                "might_associated_praise",
                "explicit_zero_cost",
                "no_cooldown_or_already_praised",
            ),
            semantic_postconditions=(
                "praise_control_changes_or_disables",
                "praise_confirmation_or_count_change",
                "daily_objective_progress_increases",
            ),
        )

    @classmethod
    def postcondition_verified(cls, before: PraiseObservation, after: PraiseObservation) -> bool:
        if not after.recognized or after.screen_state != "PERSONAL_MIGHT_LEADERBOARD":
            return False
        if not after.leaderboard_identity or not after.might_region_identity:
            return False
        if after.already_praised or after.cooldown_active or after.praise_disabled:
            return True
        if before.praise_count is not None and after.praise_count is not None:
            return after.praise_count != before.praise_count
        return after.target_identity != before.target_identity or after.target_roi != before.target_roi

    @classmethod
    def perform_one_pulse(
        cls, before: PraiseObservation, after: Optional[PraiseObservation] = None,
        action_recorded_today: bool = False,
    ) -> TaskResult:
        if before.already_praised or before.cooldown_active or before.praise_disabled:
            return TaskResult(TaskOutcome.BLOCKED, "ALREADY_PRAISED_OR_COOLDOWN", verified=True, state=before.screen_state)
        if not cls.authorizeable(before, action_recorded_today):
            return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_PERSONAL_MIGHT_PRAISE_TARGET", verified=True, state=before.screen_state)
        if after is None:
            return TaskResult.progress("PRAISE_PERSONAL_MIGHT is authorized; dispatch one ActionTransaction", before.screen_state)
        if not cls.postcondition_verified(before, after):
            return TaskResult(TaskOutcome.FAILED_SAFE, "PRAISE_POSTCONDITION_NOT_PROVEN", state=after.screen_state)
        return TaskResult.progress(
            "Personal Might Praise confirmed; Daily Quest Claim reconciliation required",
            "PERSONAL_MIGHT_LEADERBOARD",
            action_kind=cls.action_kind,
        )

    @classmethod
    def completion_check(cls, observation: PraiseObservation) -> bool:
        return cls.remaining(observation) == 0

    @classmethod
    def next_eligible_time(cls, observation: PraiseObservation) -> Optional[float]:
        return None


def claim_authorizeable(observation: DailyQuestClaimObservation) -> bool:
    """Require selected Daily Quest, exact objective, complete row, and row-local Claim."""
    rx0, ry0, rx1, ry1 = observation.row_bounds
    tx0, ty0, tx1, ty1 = observation.target_roi
    target_inside_row = rx0 <= tx0 < tx1 <= rx1 and ry0 <= ty0 < ty1 <= ry1
    return bool(
        observation.screen_state == "DAILY_QUEST"
        and observation.selected_daily_quest
        and PersonalMightPraiseHandler.matches_objective(observation.objective_name)
        and observation.required_progress >= 1
        and observation.current_progress == observation.required_progress
        and observation.row_fully_visible
        and observation.claim_fully_visible
        and observation.target_identity == "daily-quest-claim"
        and observation.control_class == "CLAIM"
        and target_inside_row
        and not observation.milestone_reward
        and not observation.clipped
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
    )


def claim_postcondition_verified(
    before: DailyQuestClaimObservation,
    after: DailyQuestClaimObservation | None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    row_disappeared: bool = False,
) -> bool:
    if after is None or after.screen_state != "DAILY_QUEST" or not after.selected_daily_quest:
        return False
    if not PersonalMightPraiseHandler.matches_objective(before.objective_name):
        return False
    if after.target_identity != before.target_identity or after.target_roi == before.target_roi:
        row_changed = row_disappeared
    else:
        row_changed = True
    points_changed = points_before is not None and points_after is not None and points_after > points_before
    return bool(row_changed or points_changed)


PRAISE_NAVIGATION_STEPS = (
    NavigationStep("home_to_more", "HOME_BASE", "HOME_TO_MORE", ("MORE",), source_anchor=HOME_RIGHT, target_anchor=HOME_MORE),
    NavigationStep("more_to_rankings", "MORE", "MORE_TO_RANKINGS", ("RANKINGS",), source_anchor=HOME_MORE, target_anchor=RANKINGS_ENTRY),
    NavigationStep("rankings_to_personal_might", "RANKINGS", "RANKINGS_TO_PERSONAL_MIGHT", ("PERSONAL_MIGHT_RANK",), source_anchor=RANKINGS_ENTRY, target_anchor=PERSONAL_MIGHT_ROW),
    NavigationStep("personal_might_check_to_leaderboard", "PERSONAL_MIGHT_RANK", "PERSONAL_MIGHT_CHECK", ("PERSONAL_MIGHT_LEADERBOARD",), source_anchor=PERSONAL_MIGHT_ROW, target_anchor=PERSONAL_MIGHT_CHECK),
    NavigationStep("personal_might_praise", "PERSONAL_MIGHT_LEADERBOARD", "PRAISE_PERSONAL_MIGHT", ("PERSONAL_MIGHT_LEADERBOARD",), source_anchor=PERSONAL_MIGHT_LEADERBOARD, target_anchor=MIGHT_PRAISE_ACTION, allow_one_safe_retry=False),
    NavigationStep("personal_might_back_to_rankings", "PERSONAL_MIGHT_LEADERBOARD", "PERSONAL_MIGHT_BACK", ("RANKINGS",), source_anchor=PERSONAL_MIGHT_BACK, target_anchor=PERSONAL_MIGHT_BACK),
    NavigationStep("rankings_back_to_home", "RANKINGS", "RANKINGS_BACK", ("HOME_BASE", "MORE"), source_anchor=RANKINGS_BACK, target_anchor=RANKINGS_BACK),
)

PRAISE_NAVIGATION_BY_NAME = {step.name: step for step in PRAISE_NAVIGATION_STEPS}
RESET_POPUP_DISMISS_STEP = NavigationStep(
    "reset_popup_close",
    "RESET_POPUP",
    "DISMISS_RESET_POPUP",
    ("HOME_BASE",),
    source_anchor=RESET_POPUP_CLOSE,
    target_anchor=RESET_POPUP_CLOSE,
    allow_one_safe_retry=False,
)


@dataclass(frozen=True)
class QuestHandlerSpec:
    objective_name: str
    route_name: str
    route_type: RouteType
    handler: type


ALLIANCE_HELP_HANDLER = QuestHandlerSpec(
    objective_name=AllianceHelpHandler.objective_name,
    route_name=ALLIANCE_HELP_ROUTE,
    route_type=RouteType.ALLIANCE,
    handler=AllianceHelpHandler,
)

PERSONAL_MIGHT_PRAISE_HANDLER = QuestHandlerSpec(
    objective_name=PersonalMightPraiseHandler.objective_aliases[0],
    route_name=PERSONAL_MIGHT_PRAISE_ROUTE,
    route_type=RouteType.DIRECT_TASK_SCREEN,
    handler=PersonalMightPraiseHandler,
)

QUEST_HANDLERS = (ALLIANCE_HELP_HANDLER, PERSONAL_MIGHT_PRAISE_HANDLER)


def handler_for_objective(name: str) -> Optional[QuestHandlerSpec]:
    return next((spec for spec in QUEST_HANDLERS if spec.handler.matches_objective(name)), None)


class DailyQuestTask:
    """Stateful task shell; completion requires a verified explicit task result."""

    task_id = "MVP-QUEST-TO-CLAIM"

    def __init__(self, completion_key: str):
        self.completion_key = completion_key
        self.completed = False

    def apply(self, result: TaskResult) -> TaskResult:
        if result.outcome == TaskOutcome.DONE and result.verified and result.completion_key == self.completion_key:
            self.completed = True
            return result
        if result.outcome == TaskOutcome.DONE:
            return TaskResult(TaskOutcome.FAILED_SAFE, "DONE_REQUIRES_VERIFIED_COMPLETION", verified=False, state=result.state)
        return result

    def complete_from_postcondition(self, state: str, evidence: Mapping[str, Any]) -> TaskResult:
        if not evidence.get("verified"):
            return TaskResult(TaskOutcome.FAILED_SAFE, "POSTCONDITION_NOT_VERIFIED", state=state)
        return self.apply(TaskResult.done("task completion postcondition verified", self.completion_key, state, evidence=dict(evidence)))
