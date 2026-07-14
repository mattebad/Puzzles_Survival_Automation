"""Offline adapter for the five-count Daily Supply Depot objective."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .supply_depot import (
    SUPPLY_DEPOT_SCREEN,
    SupplyDepotObservation,
    supply_depot_authorizeable,
    supply_depot_postcondition_verified,
    supply_depot_transaction_spec,
)


DAILY_SUPPLY_DEPOT_OBJECTIVE = "supply_depot"
DAILY_SUPPLY_DEPOT_TARGET = 5
DAILY_SUPPLY_DEPOT_COMPLETION = "daily-supply-depot:completed"


@dataclass(frozen=True)
class DailySupplyDepotObservation:
    """Selected-Daily row plus one current-frame Supply Depot observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    supply_depot: SupplyDepotObservation
    daily_progress_after: int | None = None
    successor_state: str = ""
    collection_confirmed: bool = False


def daily_supply_depot_authorizeable(
    observation: DailySupplyDepotObservation,
) -> bool:
    """Require exact selected-Daily identity and a resumable five-count objective."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_SUPPLY_DEPOT_OBJECTIVE
        and 0 <= observation.daily_progress_before < DAILY_SUPPLY_DEPOT_TARGET
        and supply_depot_authorizeable(observation.supply_depot)
    )


def daily_supply_depot_transaction_spec(
    observation: DailySupplyDepotObservation,
) -> ActionTransactionSpec:
    """Return one free collection spec; caller must request one per pulse."""

    if not daily_supply_depot_authorizeable(observation):
        raise ValueError("Daily Supply Depot preconditions are not positively recognized")
    return supply_depot_transaction_spec(observation.supply_depot)


def daily_supply_depot_postcondition_verified(
    before: DailySupplyDepotObservation,
    successors: tuple[DailySupplyDepotObservation, ...] | None,
) -> bool:
    """Require exactly enough one-pulse collections to reach Daily progress 5."""

    if not daily_supply_depot_authorizeable(before) or successors is None:
        return False
    remaining = DAILY_SUPPLY_DEPOT_TARGET - before.daily_progress_before
    if len(successors) != remaining:
        return False

    current = before
    for index, successor in enumerate(successors, start=1):
        if (
            not successor.selected_daily_row
            or successor.objective_key != DAILY_SUPPLY_DEPOT_OBJECTIVE
            or successor.daily_progress_after != before.daily_progress_before + index
            or successor.supply_depot.game_day_id != before.supply_depot.game_day_id
        ):
            return False
        if not supply_depot_postcondition_verified(
            current.supply_depot,
            successor.supply_depot,
            collection_confirmed=successor.collection_confirmed,
        ):
            return False
        current = successor

    return bool(
        current.daily_progress_after == DAILY_SUPPLY_DEPOT_TARGET
        and current.successor_state == "DAILY_SUPPLY_DEPOT_COMPLETE"
    )


def daily_supply_depot_replay(
    before: DailySupplyDepotObservation,
    successors: tuple[DailySupplyDepotObservation, ...] | None = None,
) -> TaskResult:
    """Replay pure evidence; collection transport remains evidence-gated."""

    if not daily_supply_depot_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_SUPPLY_DEPOT",
            verified=True,
            state=SUPPLY_DEPOT_SCREEN,
            details={"dispatch_count": 0},
        )
    if successors is None:
        return TaskResult.progress(
            "free Supply Depot collection is recognized; dispatch remains evidence-gated",
            SUPPLY_DEPOT_SCREEN,
            dispatch_count=0,
            required_pulses=DAILY_SUPPLY_DEPOT_TARGET - before.daily_progress_before,
        )
    if not daily_supply_depot_postcondition_verified(before, successors):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_SUPPLY_DEPOT_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=SUPPLY_DEPOT_SCREEN,
            details={"dispatch_count": 0},
        )
    return TaskResult.done(
        "Daily Supply Depot collection postcondition verified",
        DAILY_SUPPLY_DEPOT_COMPLETION,
        SUPPLY_DEPOT_SCREEN,
        dispatch_count=0,
    )
