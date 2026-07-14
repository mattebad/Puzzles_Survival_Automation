"""Offline adapter for the Daily Craft Nanoweapon objective."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .nanoweapon import (
    NANOWEAPON_SCREEN,
    NanoweaponObservation,
    nanoweapon_authorizeable,
    nanoweapon_postcondition_verified,
    nanoweapon_transaction_spec,
)


DAILY_NANOWEAPON_OBJECTIVE = "craft_nanoweapon"
DAILY_NANOWEAPON_COMPLETION = "daily-nanoweapon:completed"


@dataclass(frozen=True)
class DailyNanoweaponObservation:
    """Selected-Daily row plus one current-frame Craft Weapon observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    nanoweapon: NanoweaponObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_nanoweapon_authorizeable(
    observation: DailyNanoweaponObservation,
) -> bool:
    """Require exact selected-Daily identity and one free known craft."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_NANOWEAPON_OBJECTIVE
        and observation.daily_progress_before == 0
        and nanoweapon_authorizeable(observation.nanoweapon)
    )


def daily_nanoweapon_transaction_spec(
    observation: DailyNanoweaponObservation,
) -> ActionTransactionSpec:
    if not daily_nanoweapon_authorizeable(observation):
        raise ValueError("Daily nanoweapon preconditions are not positively recognized")
    return nanoweapon_transaction_spec(observation.nanoweapon)


def daily_nanoweapon_postcondition_verified(
    before: DailyNanoweaponObservation,
    after: DailyNanoweaponObservation | None,
) -> bool:
    """Require one same-day craft result and Daily progress 0/1 transition."""

    return bool(
        daily_nanoweapon_authorizeable(before)
        and after is not None
        and after.selected_daily_row
        and after.objective_key == DAILY_NANOWEAPON_OBJECTIVE
        and after.daily_progress_after == 1
        and after.successor_state == "DAILY_NANOWEAPON_COMPLETE"
        and after.nanoweapon.game_day_id == before.nanoweapon.game_day_id
        and nanoweapon_postcondition_verified(before.nanoweapon, after.nanoweapon)
    )


def daily_nanoweapon_replay(
    before: DailyNanoweaponObservation,
    after: DailyNanoweaponObservation | None = None,
) -> TaskResult:
    """Replay pure evidence; craft transport remains outside this adapter."""

    if not daily_nanoweapon_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_NANOWEAPON",
            verified=True,
            state=NANOWEAPON_SCREEN,
            details={"dispatch_count": 0},
        )
    if after is None:
        return TaskResult.progress(
            "Nanoweapon craft is recognized; dispatch remains evidence-gated",
            NANOWEAPON_SCREEN,
            dispatch_count=0,
        )
    if not daily_nanoweapon_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_NANOWEAPON_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=NANOWEAPON_SCREEN,
            details={"dispatch_count": 0},
        )
    return TaskResult.done(
        "Daily nanoweapon craft postcondition verified",
        DAILY_NANOWEAPON_COMPLETION,
        NANOWEAPON_SCREEN,
        dispatch_count=0,
    )
