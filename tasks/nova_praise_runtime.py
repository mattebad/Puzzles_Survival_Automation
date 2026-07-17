"""Dormant deterministic state machine for Nova Praise."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .nova_praise import (
    NOVA_HOME,
    NOVA_INTERACTION_TARGET,
    NOVA_LAB_MENU,
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
    next_eligible_timestamp,
    nova_authorizeable,
    nova_postcondition_verified,
)
from .nova_praise_vision import NOVA_MENU_ROI, NOVA_PRAISE_ROI, RESEARCH_LAB_ROI


class NovaAction(str, Enum):
    OPEN_LAB = "OPEN_LAB"
    OPEN_NOVA = "OPEN_NOVA"
    PRAISE = "PRAISE"
    WAIT_COOLDOWN = "WAIT_COOLDOWN"
    RETURN_HOME = "RETURN_HOME"
    STOP = "STOP"


@dataclass(frozen=True)
class NovaCommand:
    action: NovaAction
    target_identity: Optional[str] = None
    target_roi: Optional[tuple[int, int, int, int]] = None
    terminal: bool = False
    reason: str = ""
    next_eligible_at: Optional[float] = None


@dataclass
class NovaProgress:
    dispatches: int = 0
    completed_attempts: int = 0
    attempts_remaining: Optional[int] = None
    next_eligible_at: Optional[float] = None
    awaiting_postcondition: bool = False
    last_dispatch_frame: Optional[str] = None


class NovaPraiseRuntimeController:
    """Produce at most one consequential Praise command for each fresh precondition."""

    def __init__(self, *, now: float = 0.0) -> None:
        self.progress = NovaProgress()
        self.now = now

    def next_command(self, recognition) -> NovaCommand:
        obs: NovaPraiseObservation = recognition.observation
        if not obs.recognized or obs.screen_state == "UNKNOWN" or obs.stale:
            return NovaCommand(NovaAction.STOP, terminal=True, reason="unknown_or_stale_nova_state")
        if self.progress.awaiting_postcondition:
            return NovaCommand(NovaAction.STOP, terminal=True, reason="awaiting_fresh_praise_postcondition")
        if obs.screen_state == NOVA_HOME:
            return NovaCommand(NovaAction.OPEN_LAB, "research-lab-building", RESEARCH_LAB_ROI)
        if obs.screen_state == NOVA_LAB_MENU and obs.nova_control_visible:
            return NovaCommand(NovaAction.OPEN_NOVA, NOVA_INTERACTION_TARGET, NOVA_MENU_ROI)
        if obs.screen_state != NOVA_SCREEN or not obs.selected_nova:
            return NovaCommand(NovaAction.STOP, terminal=True, reason="unknown_nova_screen")
        self.progress.attempts_remaining = obs.attempts_remaining
        if obs.attempts_remaining == 0:
            return NovaCommand(NovaAction.RETURN_HOME, terminal=False, reason="all_attempts_consumed")
        eligible = next_eligible_timestamp(obs, now=self.now)
        if eligible is not None and eligible > self.now:
            self.progress.next_eligible_at = eligible
            return NovaCommand(NovaAction.WAIT_COOLDOWN, terminal=False, reason="cooldown_active", next_eligible_at=eligible)
        if not nova_authorizeable(obs, now=self.now):
            return NovaCommand(NovaAction.STOP, terminal=True, reason="praise_disabled_or_ambiguous")
        if recognition.frame_sha256 == self.progress.last_dispatch_frame:
            return NovaCommand(NovaAction.STOP, terminal=True, reason="duplicate_frame_dispatch_guard")
        self.progress.awaiting_postcondition = True
        self.progress.last_dispatch_frame = recognition.frame_sha256
        return NovaCommand(NovaAction.PRAISE, NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI, reason="one_zero_cost_attempt")

    def accept_postcondition(self, before: NovaPraiseObservation, after: NovaPraiseObservation) -> bool:
        if not self.progress.awaiting_postcondition:
            return False
        if not nova_postcondition_verified(before, after, now=self.now):
            return False
        self.progress.awaiting_postcondition = False
        self.progress.dispatches += 1
        self.progress.completed_attempts += 1
        self.progress.attempts_remaining = after.attempts_remaining
        self.progress.next_eligible_at = next_eligible_timestamp(after, now=self.now)
        return True
