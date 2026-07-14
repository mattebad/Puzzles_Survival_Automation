"""Offline adapter for selected-Daily enhancement objectives."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .enhancement import (
    ENHANCEMENT_SCREEN,
    EnhancementObservation,
    enhancement_authorizeable,
    enhancement_postcondition_verified,
    enhancement_transaction_spec,
)


DAILY_ENHANCEMENT_OBJECTIVES = {
    "gear": "enhance_gear",
    "chip": "enhance_chip",
}


@dataclass(frozen=True)
class DailyEnhancementObservation:
    """Selected-Daily row plus one current-frame enhancement observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    enhancement: EnhancementObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_enhancement_authorizeable(
    observation: DailyEnhancementObservation,
    *,
    variant: str = "gear",
) -> bool:
    """Require exact Daily objective ownership and shared-family guards."""

    expected_objective = DAILY_ENHANCEMENT_OBJECTIVES.get(str(variant).lower())
    return bool(
        expected_objective
        and observation.selected_daily_row
        and observation.objective_key == expected_objective
        and observation.daily_progress_before == 0
        and enhancement_authorizeable(observation.enhancement, variant=variant)
    )


def daily_enhancement_transaction_spec(
    observation: DailyEnhancementObservation,
    *,
    variant: str = "gear",
) -> ActionTransactionSpec:
    if not daily_enhancement_authorizeable(observation, variant=variant):
        raise ValueError("Daily enhancement preconditions are not positively recognized")
    return enhancement_transaction_spec(observation.enhancement, variant=variant)


def daily_enhancement_postcondition_verified(
    before: DailyEnhancementObservation,
    after: DailyEnhancementObservation | None,
    *,
    variant: str = "gear",
) -> bool:
    """Require one same-day positive item/material result and Daily 0/1 transition."""

    return bool(
        daily_enhancement_authorizeable(before, variant=variant)
        and after is not None
        and after.selected_daily_row
        and after.objective_key == DAILY_ENHANCEMENT_OBJECTIVES.get(str(variant).lower())
        and after.daily_progress_after == 1
        and after.successor_state == f"DAILY_{str(variant).upper()}_ENHANCEMENT_COMPLETE"
        and enhancement_authorizeable(after.enhancement, variant=variant)
        and after.enhancement.game_day_id == before.enhancement.game_day_id
        and enhancement_postcondition_verified(
            before.enhancement,
            after.enhancement,
            variant=variant,
        )
    )


def daily_enhancement_replay(
    before: DailyEnhancementObservation,
    after: DailyEnhancementObservation | None = None,
    *,
    variant: str = "gear",
) -> TaskResult:
    """Replay pure evidence; enhancement transport remains evidence-gated."""

    if not daily_enhancement_authorizeable(before, variant=variant):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_ENHANCEMENT",
            verified=True,
            state=ENHANCEMENT_SCREEN,
            details={"dispatch_count": 0},
        )
    if after is None:
        return TaskResult.progress(
            f"Daily {str(variant).lower()} enhancement is recognized; dispatch remains evidence-gated",
            ENHANCEMENT_SCREEN,
            dispatch_count=0,
        )
    if not daily_enhancement_postcondition_verified(before, after, variant=variant):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_ENHANCEMENT_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=ENHANCEMENT_SCREEN,
            details={"dispatch_count": 0},
        )
    variant_name = str(variant).lower()
    return TaskResult.done(
        f"Daily {variant_name} enhancement postcondition verified",
        f"daily-enhancement:{variant_name}:completed",
        ENHANCEMENT_SCREEN,
        dispatch_count=0,
    )
