"""Pure Daily Quest row-state and ordering semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class DailyObjectiveState(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    READY_TO_CLAIM = "READY_TO_CLAIM"
    CLAIMED = "CLAIMED"
    GATED = "GATED"


@dataclass(frozen=True)
class DailyObjectiveRow:
    """Read-only row observation; it never authorizes an input."""

    objective_key: str
    progress: int
    target: int
    control: str | None = None
    gated: bool = False


def classify_daily_objective(row: DailyObjectiveRow) -> DailyObjectiveState:
    """Classify state from progress and the exact row-local control."""

    if row.target < 0 or row.progress < 0:
        raise ValueError("Daily progress must be non-negative")
    if row.control == "Claimed":
        if row.progress < row.target:
            raise ValueError("a Claimed row must be complete")
        return DailyObjectiveState.CLAIMED
    if row.gated:
        if row.progress >= row.target:
            raise ValueError("a completed row cannot remain gated")
        return DailyObjectiveState.GATED
    if row.control == "Claim":
        if row.progress < row.target:
            raise ValueError("a Claim row must be complete")
        return DailyObjectiveState.READY_TO_CLAIM
    if row.progress >= row.target:
        raise ValueError("a completed row must show Claim or Claimed")
    return DailyObjectiveState.INCOMPLETE


def validate_daily_row_order(rows: Sequence[DailyObjectiveRow]) -> bool:
    """Validate the observed client ordering without using viewport absence as evidence."""

    order = {
        DailyObjectiveState.READY_TO_CLAIM: 0,
        DailyObjectiveState.INCOMPLETE: 1,
        DailyObjectiveState.GATED: 2,
        DailyObjectiveState.CLAIMED: 3,
    }
    states = [classify_daily_objective(row) for row in rows]
    return states == sorted(states, key=order.__getitem__)


def claim_requires_separate_transaction(
    before: DailyObjectiveRow,
    after: DailyObjectiveRow,
) -> bool:
    """Completion and Claim are independent transitions."""

    return (
        classify_daily_objective(before) != DailyObjectiveState.CLAIMED
        and after.progress >= after.target
        and classify_daily_objective(after) == DailyObjectiveState.CLAIMED
    )
