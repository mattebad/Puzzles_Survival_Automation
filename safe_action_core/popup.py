"""Explicit popup handling policy for navigation and action transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from tasks.contracts import PopupMode, PopupOutcome


@dataclass(frozen=True)
class PopupObservation:
    name: Optional[str]
    benign: bool = False
    hard_stop: bool = False
    purchase_or_cost: bool = False


class PopupController:
    def __init__(self, mode: PopupMode, allowed_dialogs: Tuple[str, ...] = (), max_rounds: int = 3):
        if max_rounds < 1:
            raise ValueError("popup round cap must be positive")
        self.mode = mode
        self.allowed_dialogs = frozenset(allowed_dialogs)
        self.max_rounds = max_rounds
        self.rounds = 0

    def inspect(self, popup: Optional[PopupObservation]) -> PopupOutcome:
        if popup is None or popup.name is None:
            return PopupOutcome.NOT_PRESENT
        if popup.hard_stop:
            return PopupOutcome.FATAL
        if popup.purchase_or_cost:
            return PopupOutcome.BLOCKING
        if self.rounds >= self.max_rounds:
            return PopupOutcome.BLOCKING
        if self.mode == PopupMode.NAVIGATION and popup.benign:
            self.rounds += 1
            return PopupOutcome.HANDLED
        if self.mode == PopupMode.ACTION_TRANSACTION and popup.name in self.allowed_dialogs:
            self.rounds += 1
            return PopupOutcome.HANDLED
        return PopupOutcome.UNKNOWN
