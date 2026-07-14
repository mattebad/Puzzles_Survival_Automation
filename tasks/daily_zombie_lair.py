"""Offline adapter for the selected-Daily Zombie Lair objective."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .zombie_lair import (
    ZOMBIE_LAIR_SCREEN,
    ZombieLairObservation,
    zombie_lair_authorizeable,
    zombie_lair_postcondition_verified,
    zombie_lair_transaction_spec,
)


DAILY_ZOMBIE_LAIR_OBJECTIVE = "defeat_zombie_lair"
DAILY_ZOMBIE_LAIR_COMPLETION = "daily-zombie-lair:completed"


@dataclass(frozen=True)
class DailyZombieLairObservation:
    """Selected-Daily row plus one current-frame Zombie Lair observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    lair: ZombieLairObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_zombie_lair_authorizeable(
    observation: DailyZombieLairObservation,
) -> bool:
    """Require exact selected-Daily identity and bounded Lair participation."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_ZOMBIE_LAIR_OBJECTIVE
        and observation.daily_progress_before == 0
        and zombie_lair_authorizeable(observation.lair)
    )


def daily_zombie_lair_transaction_spec(
    observation: DailyZombieLairObservation,
) -> ActionTransactionSpec:
    if not daily_zombie_lair_authorizeable(observation):
        raise ValueError("Daily Zombie Lair preconditions are not positively recognized")
    return zombie_lair_transaction_spec(observation.lair)


def daily_zombie_lair_postcondition_verified(
    before: DailyZombieLairObservation,
    after: DailyZombieLairObservation | None,
) -> bool:
    """Require one same-day Lair result and Daily 0/1 transition."""

    return bool(
        daily_zombie_lair_authorizeable(before)
        and after is not None
        and after.selected_daily_row
        and after.objective_key == DAILY_ZOMBIE_LAIR_OBJECTIVE
        and after.daily_progress_after == 1
        and after.successor_state == "DAILY_ZOMBIE_LAIR_COMPLETE"
        and zombie_lair_postcondition_verified(before.lair, after.lair)
    )


def daily_zombie_lair_replay(
    before: DailyZombieLairObservation,
    after: DailyZombieLairObservation | None = None,
) -> TaskResult:
    """Replay pure Lair evidence; join/combat transport remains evidence-gated."""

    if not daily_zombie_lair_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_ZOMBIE_LAIR",
            verified=True,
            state=ZOMBIE_LAIR_SCREEN,
            details={"dispatch_count": 0},
        )
    if after is None:
        return TaskResult.progress(
            "Daily Zombie Lair is recognized; dispatch remains evidence-gated",
            ZOMBIE_LAIR_SCREEN,
            dispatch_count=0,
        )
    if not daily_zombie_lair_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_ZOMBIE_LAIR_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=ZOMBIE_LAIR_SCREEN,
            details={"dispatch_count": 0},
        )
    return TaskResult.done(
        "Daily Zombie Lair postcondition verified",
        DAILY_ZOMBIE_LAIR_COMPLETION,
        ZOMBIE_LAIR_SCREEN,
        dispatch_count=0,
    )
