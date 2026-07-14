"""Offline adapter for the five-count Daily Noah's Tavern objective."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .free_recruitment import (
    FreeRecruitmentObservation,
    free_recruitment_authorizeable,
    free_recruitment_postcondition_verified,
    free_recruitment_transaction_spec,
)


DAILY_RECRUITMENT_OBJECTIVE = "recruit_noahs_tavern"
DAILY_RECRUITMENT_TARGET = 5
DAILY_RECRUITMENT_SCREEN = "RECRUITMENT"
DAILY_RECRUITMENT_COMPLETION = "daily-recruitment:completed"


@dataclass(frozen=True)
class DailyRecruitmentObservation:
    """Selected-Daily row plus one current-frame Tavern observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    tavern: FreeRecruitmentObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_recruitment_authorizeable(observation: DailyRecruitmentObservation) -> bool:
    """Require exact selected-Daily identity and a resumable five-count objective."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_RECRUITMENT_OBJECTIVE
        and 0 <= observation.daily_progress_before < DAILY_RECRUITMENT_TARGET
        and free_recruitment_authorizeable(observation.tavern)
    )


def daily_recruitment_transaction_spec(
    observation: DailyRecruitmentObservation,
) -> ActionTransactionSpec:
    """Return one free-single spec; caller must request one per pulse."""

    if not daily_recruitment_authorizeable(observation):
        raise ValueError("Daily recruitment preconditions are not positively recognized")
    return free_recruitment_transaction_spec(observation.tavern)


def daily_recruitment_postcondition_verified(
    before: DailyRecruitmentObservation,
    successors: tuple[DailyRecruitmentObservation, ...] | None,
) -> bool:
    """Require exactly enough +1 free singles to reach Daily progress 5."""

    if not daily_recruitment_authorizeable(before) or successors is None:
        return False
    remaining = DAILY_RECRUITMENT_TARGET - before.daily_progress_before
    if len(successors) != remaining:
        return False

    current = before
    for index, successor in enumerate(successors, start=1):
        if (
            not successor.selected_daily_row
            or successor.objective_key != DAILY_RECRUITMENT_OBJECTIVE
            or successor.daily_progress_after != before.daily_progress_before + index
            or successor.tavern.game_day_id != before.tavern.game_day_id
            or successor.tavern.recruitment_count is None
            or current.tavern.recruitment_count is None
            or successor.tavern.recruitment_count != current.tavern.recruitment_count + 1
        ):
            return False
        if not free_recruitment_postcondition_verified(current.tavern, successor.tavern):
            return False
        current = successor

    return bool(
        current.daily_progress_after == DAILY_RECRUITMENT_TARGET
        and current.successor_state == "DAILY_RECRUITMENT_COMPLETE"
    )


def daily_recruitment_replay(
    before: DailyRecruitmentObservation,
    successors: tuple[DailyRecruitmentObservation, ...] | None = None,
) -> TaskResult:
    """Replay pure evidence; no recruitment transport or runtime registration occurs."""

    if not daily_recruitment_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_RECRUITMENT",
            verified=True,
            state=DAILY_RECRUITMENT_SCREEN,
            details={"dispatch_count": 0},
        )
    if successors is None:
        return TaskResult.progress(
            "free recruitment is recognized; dispatch remains evidence-gated",
            DAILY_RECRUITMENT_SCREEN,
            dispatch_count=0,
            required_pulses=DAILY_RECRUITMENT_TARGET - before.daily_progress_before,
        )
    if not daily_recruitment_postcondition_verified(before, successors):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_RECRUITMENT_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=DAILY_RECRUITMENT_SCREEN,
            details={"dispatch_count": 0},
        )
    return TaskResult.done(
        "Daily five-count recruitment postcondition verified",
        DAILY_RECRUITMENT_COMPLETION,
        DAILY_RECRUITMENT_SCREEN,
        dispatch_count=0,
    )
