"""Deterministic Daily Quest task contracts and route dispatch.

This module owns task semantics, not ADB.  Device access remains injected through the existing
safe_action_core executor and navigation runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from .contracts import TaskOutcome, TaskResult


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
