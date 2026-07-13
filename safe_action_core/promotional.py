"""Bounded state tracking for verified promotional-page escape actions."""

from __future__ import annotations

from dataclasses import dataclass

MAX_PROMOTIONAL_BACKS = 3
PROMOTIONAL_STATE = "UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK"
SAFE_PROMOTIONAL_BACK = "SAFE_PROMOTIONAL_BACK"
PROMOTIONAL_BACK_GEOMETRY = "standard_game_back_arrow"
PROMOTIONAL_BACK_TARGET_ROI = (45, 5, 130, 60)
KNOWN_SUCCESSOR_STATES = frozenset({"CASH_MALL", "HOME_BASE", "QUEST", "DAILY_QUEST"})


class PromotionalSequenceError(RuntimeError):
    """Raised when a promotional escape successor cannot be safely reconciled."""


@dataclass
class PromotionalBackSequence:
    """Bound the number of independently validated promotional Back actions."""

    confirmed_count: int = 0
    max_actions: int = MAX_PROMOTIONAL_BACKS

    def can_attempt(self) -> bool:
        return 0 <= self.confirmed_count < self.max_actions

    def record_confirmed(self, successor_state: str) -> str:
        if not self.can_attempt():
            raise PromotionalSequenceError("promotional Back limit reached")
        normalized = successor_state.upper().replace("-", "_")
        self.confirmed_count += 1
        if normalized in KNOWN_SUCCESSOR_STATES:
            return "known_safe_state"
        if normalized == PROMOTIONAL_STATE:
            return "promotional_continuation"
        raise PromotionalSequenceError("unexpected promotional Back successor")
