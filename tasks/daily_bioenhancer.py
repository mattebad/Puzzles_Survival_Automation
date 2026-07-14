"""Offline adapter for the Daily Bioenhancer research objective."""

from __future__ import annotations

from dataclasses import dataclass

from .bioenhancer import (
    BIOENHANCER_SCREEN,
    BioenhancerObservation,
    bioenhancer_authorizeable,
    bioenhancer_postcondition_verified,
    bioenhancer_transaction_spec,
)
from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult


DAILY_BIOENHANCER_OBJECTIVE = "bioenhancer_research"
DAILY_BIOENHANCER_COMPLETION = "daily-bioenhancer:completed"


@dataclass(frozen=True)
class DailyBioenhancerObservation:
    """Selected-Daily row plus one current-frame Bioenhancer observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    bioenhancer: BioenhancerObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_bioenhancer_authorizeable(
    observation: DailyBioenhancerObservation,
) -> bool:
    """Require exact selected-Daily identity and one free research action."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_BIOENHANCER_OBJECTIVE
        and observation.daily_progress_before == 0
        and bioenhancer_authorizeable(observation.bioenhancer)
    )


def daily_bioenhancer_transaction_spec(
    observation: DailyBioenhancerObservation,
) -> ActionTransactionSpec:
    if not daily_bioenhancer_authorizeable(observation):
        raise ValueError("Daily Bioenhancer preconditions are not positively recognized")
    return bioenhancer_transaction_spec(observation.bioenhancer)


def daily_bioenhancer_postcondition_verified(
    before: DailyBioenhancerObservation,
    after: DailyBioenhancerObservation | None,
) -> bool:
    """Require one same-day research result and Daily progress 0/1 transition."""

    return bool(
        daily_bioenhancer_authorizeable(before)
        and after is not None
        and after.selected_daily_row
        and after.objective_key == DAILY_BIOENHANCER_OBJECTIVE
        and after.daily_progress_after == 1
        and after.successor_state == "DAILY_BIOENHANCER_COMPLETE"
        and bioenhancer_postcondition_verified(
            before.bioenhancer,
            after.bioenhancer,
        )
    )


def daily_bioenhancer_replay(
    before: DailyBioenhancerObservation,
    after: DailyBioenhancerObservation | None = None,
) -> TaskResult:
    """Replay pure evidence; research transport remains evidence-gated."""

    if not daily_bioenhancer_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_BIOENHANCER",
            verified=True,
            state=BIOENHANCER_SCREEN,
            details={"dispatch_count": 0},
        )
    if after is None:
        return TaskResult.progress(
            "Daily Bioenhancer research is recognized; dispatch remains evidence-gated",
            BIOENHANCER_SCREEN,
            dispatch_count=0,
        )
    if not daily_bioenhancer_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_BIOENHANCER_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=BIOENHANCER_SCREEN,
            details={"dispatch_count": 0},
        )
    return TaskResult.done(
        "Daily Bioenhancer research postcondition verified",
        DAILY_BIOENHANCER_COMPLETION,
        BIOENHANCER_SCREEN,
        dispatch_count=0,
    )
