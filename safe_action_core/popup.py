"""Explicit popup handling policy for navigation and action transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from tasks.contracts import PopupMode, PopupOutcome


ALLIANCE_FORT_WAVE_ALERT = "ALLIANCE_FORT_WAVE_ALERT"
UPDATE_RESTART_ALERT = "UPDATE_RESTART_ALERT"


def _popup_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def classify_popup_semantics(title: str, body: str) -> Optional[str]:
    """Classify only explicitly known popup semantics; button text is insufficient."""
    text = _popup_text(f"{title} {body}")
    update_terms = (
        "update available",
        "new version",
        "client update",
        "patch",
        "download update",
        "restart required",
        "restarting the game",
    )
    if any(term in text for term in update_terms):
        return UPDATE_RESTART_ALERT
    alliance_terms = (
        "next wave",
        "mutant zombie",
        "alliance fort",
        "send your army",
        "defend it",
    )
    if all(term in text for term in alliance_terms):
        return ALLIANCE_FORT_WAVE_ALERT
    return None


def alliance_fort_dismissal_allowed(popup_identity: str, control: str) -> bool:
    """Permit only X/Confirm on the exact Alliance Fort wave alert."""
    return bool(
        popup_identity == ALLIANCE_FORT_WAVE_ALERT
        and _popup_text(control) in {"x", "confirm"}
    )


def popup_dismissal_verified(
    popup_identity: str,
    before_present: bool,
    after_present: bool,
    successor_recognized: bool,
) -> bool:
    """Require exact known popup disappearance and a recognized successor."""
    return bool(
        popup_identity == ALLIANCE_FORT_WAVE_ALERT
        and before_present
        and not after_present
        and successor_recognized
    )


@dataclass(frozen=True)
class PopupObservation:
    name: Optional[str]
    benign: bool = False
    hard_stop: bool = False
    purchase_or_cost: bool = False
    resource_or_premium: bool = False
    frame_sha256: Optional[str] = None


class PopupController:
    def __init__(
        self,
        mode: PopupMode,
        allowed_dialogs: Tuple[str, ...] = (),
        max_rounds: int = 3,
        known_navigation_popups: Tuple[str, ...] = (
            "vip-points-reset",
            "help-webview",
            ALLIANCE_FORT_WAVE_ALERT,
        ),
    ):
        if max_rounds < 1:
            raise ValueError("popup round cap must be positive")
        self.mode = mode
        self.allowed_dialogs = frozenset(allowed_dialogs)
        self.known_navigation_popups = frozenset(known_navigation_popups)
        self.max_rounds = max_rounds
        self.rounds = 0
        self.last_handled_frame: Optional[str] = None

    def inspect(self, popup: Optional[PopupObservation]) -> PopupOutcome:
        if popup is None or popup.name is None:
            return PopupOutcome.NOT_PRESENT
        if popup.hard_stop:
            return PopupOutcome.FATAL
        if popup.purchase_or_cost or popup.resource_or_premium:
            return PopupOutcome.BLOCKING
        if self.mode == PopupMode.NAVIGATION and popup.name not in self.known_navigation_popups:
            return PopupOutcome.UNKNOWN
        if popup.frame_sha256 and popup.frame_sha256 == self.last_handled_frame:
            return PopupOutcome.BLOCKING
        if self.rounds >= self.max_rounds:
            return PopupOutcome.BLOCKING
        if self.mode == PopupMode.NAVIGATION and popup.benign:
            self.rounds += 1
            self.last_handled_frame = popup.frame_sha256
            return PopupOutcome.HANDLED
        if self.mode == PopupMode.ACTION_TRANSACTION and popup.name in self.allowed_dialogs:
            self.rounds += 1
            self.last_handled_frame = popup.frame_sha256
            return PopupOutcome.HANDLED
        return PopupOutcome.UNKNOWN
