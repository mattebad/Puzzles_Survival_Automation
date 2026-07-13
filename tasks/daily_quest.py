"""Deterministic Daily Quest task contracts and route dispatch.

This module owns task semantics, not ADB.  Device access remains injected through the existing
safe_action_core executor and navigation runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import ALLIANCE_HELP_ACTION


ALLIANCE_HELP_ROUTE = "daily_go_to_alliance_help"


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
        if state == "ALLIANCE":
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
    """Semantic evidence for one independently recognized Alliance Help request."""

    screen_state: str
    objective_name: str
    current_progress: int
    required_progress: int
    target_identity: str
    target_roi: ROI
    zero_cost_evidence: bool
    overlay_state: str = "none_observed"
    forbidden_region_intersects_target: bool = False
    recognized: bool = True


class AllianceHelpHandler:
    """The first narrow zero-cost Daily Quest handler; transport remains injected."""

    objective_name = "Help allies"
    action_kind = "ALLIANCE_HELP"
    consequence = "alliance_help_zero_cost"

    @classmethod
    def matches_objective(cls, name: str) -> bool:
        return " ".join(name.lower().split()) == cls.objective_name.lower()

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
            observation.screen_state == RouteType.ALLIANCE.value
            and cls.matches_objective(observation.objective_name)
            and remaining is not None and remaining > 0
            and observation.target_identity == ALLIANCE_HELP_ACTION.name
            and observation.target_roi == ALLIANCE_HELP_ACTION.roi
            and observation.zero_cost_evidence
            and observation.overlay_state == "none_observed"
            and not observation.forbidden_region_intersects_target
        )

    @classmethod
    def transaction_spec(cls, observation: AllianceHelpObservation) -> ActionTransactionSpec:
        if not cls.authorizeable(observation):
            raise ValueError("Alliance Help preconditions are not positively recognized")
        return ActionTransactionSpec(
            action_kind=cls.action_kind,
            expected_source_screen=RouteType.ALLIANCE.value,
            subject=cls.objective_name,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            allowed_confirmation_dialogs=(),
            semantic_preconditions=("exact_alliance_help_request", "explicit_zero_cost_help", "remaining_count_positive"),
            semantic_postconditions=("help_request_or_count_changes", "daily_objective_progress_increases"),
        )

    @classmethod
    def postcondition_verified(cls, before: AllianceHelpObservation, after: AllianceHelpObservation) -> bool:
        before_remaining = cls.remaining(before)
        after_remaining = cls.remaining(after)
        if before_remaining is None or after_remaining is None:
            return False
        if not cls.matches_objective(after.objective_name) or after.screen_state != RouteType.ALLIANCE.value:
            return False
        return after.current_progress == before.current_progress + 1 and after_remaining < before_remaining


@dataclass(frozen=True)
class QuestHandlerSpec:
    objective_name: str
    route_name: str
    route_type: RouteType
    handler: type[AllianceHelpHandler]


ALLIANCE_HELP_HANDLER = QuestHandlerSpec(
    objective_name=AllianceHelpHandler.objective_name,
    route_name=ALLIANCE_HELP_ROUTE,
    route_type=RouteType.ALLIANCE,
    handler=AllianceHelpHandler,
)

QUEST_HANDLERS = (ALLIANCE_HELP_HANDLER,)


def handler_for_objective(name: str) -> Optional[QuestHandlerSpec]:
    normalized = " ".join(name.lower().split())
    return next((spec for spec in QUEST_HANDLERS if spec.objective_name.lower() == normalized), None)


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
