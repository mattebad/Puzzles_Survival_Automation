"""Fail-closed controller for recognized local Campaign Auto Battle frames.

Transport is intentionally injected.  The controller emits one bounded tap, swipe, or wait at a
time and advances its AP ledger only after the caller confirms the corresponding dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .campaign_auto_battle import (
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignDecision,
    CampaignRouteProgress,
    CampaignScreen,
    campaign_next_decision,
    reconcile_observed_ap,
    record_verified_victory,
)
from .campaign_auto_battle_vision import Box, CampaignFrameRecognition


CHAPTER_PAN_GESTURES = (
    (620, 620, 180, 620, 550),
    (400, 840, 400, 300, 550),
    (180, 620, 620, 620, 550),
    (400, 300, 400, 840, 550),
    (600, 780, 220, 360, 600),
    (220, 360, 600, 780, 600),
)
HOME_PAN_GESTURES = (
    (427, 703, 107, 836, 600),
    (107, 836, 427, 703, 600),
    (560, 720, 220, 420, 600),
    (220, 420, 560, 720, 600),
)
STAGE_PAN_GESTURES = (
    (620, 700, 220, 700, 500),
    (400, 850, 400, 330, 500),
    (220, 700, 620, 700, 500),
    (400, 330, 400, 850, 500),
)


@dataclass(frozen=True)
class CampaignRuntimeCommand:
    action: CampaignAction
    kind: str
    reason: str
    target_identity: str | None = None
    target_roi: Box | None = None
    swipe: tuple[int, int, int, int, int] | None = None
    wait_seconds: float | None = None
    terminal: bool = False

    @property
    def tap_point(self) -> tuple[int, int] | None:
        if self.target_roi is None:
            return None
        x0, y0, x1, y1 = self.target_roi
        return ((x0 + x1) // 2, (y0 + y1) // 2)


class CampaignRuntimeController:
    def __init__(self, config: CampaignAutoBattleConfig, *, initial_ap: int | None = None) -> None:
        self.config = config
        self.progress: CampaignRouteProgress | None = (
            CampaignRouteProgress(initial_ap=initial_ap, current_ap=initial_ap)
            if initial_ap is not None
            else None
        )
        self._home_pan_index = 0
        self._chapter_pan_index = 0
        self._stage_pan_index = 0
        self._awaiting_victory_ap = False
        self._return_request_sent = False
        self._last_frame_hash: str | None = None
        self._last_dispatched_signature: tuple[object, ...] | None = None

    def _terminal(self, action: CampaignAction, reason: str) -> CampaignRuntimeCommand:
        return CampaignRuntimeCommand(action, "terminal", reason, terminal=True)

    def _checked(self, command: CampaignRuntimeCommand) -> CampaignRuntimeCommand:
        signature = (
            command.action,
            command.kind,
            command.target_identity,
            command.target_roi,
            command.swipe,
        )
        if command.kind in {"tap", "swipe"} and signature == self._last_dispatched_signature:
            return self._terminal(CampaignAction.BLOCKED, "identical input retry is forbidden")
        return command

    def _initialize_or_reconcile(self, recognition: CampaignFrameRecognition) -> str | None:
        observation = recognition.observation
        if self.progress is None:
            if observation.ap_current is None:
                return "initial AP is not readable"
            self.progress = CampaignRouteProgress(
                initial_ap=observation.ap_current,
                current_ap=observation.ap_current,
            )
            return None

        if self._awaiting_victory_ap and observation.screen == CampaignScreen.CHAPTER_MAP:
            if observation.ap_current is None:
                return "post-victory AP is not readable"
            regeneration = observation.ap_current - (self.progress.current_ap - self.config.ap_cost)
            if regeneration < 0:
                return "post-victory AP decrease exceeds configured stage cost"
            try:
                self.progress = record_verified_victory(
                    self.progress,
                    ap_cost=self.config.ap_cost,
                    ap_after=observation.ap_current,
                    ap_regenerated=regeneration,
                )
            except ValueError as exc:
                return str(exc)
            self._awaiting_victory_ap = False
            return None

        if observation.ap_current is not None and observation.screen in {
            CampaignScreen.HOME_BASE,
            CampaignScreen.CHAPTER_MAP,
            CampaignScreen.STAGE_DIALOG,
        }:
            if observation.ap_current < self.progress.current_ap:
                return "unexplained AP decrease outside a verified victory"
            if observation.ap_current > self.progress.current_ap:
                try:
                    self.progress = reconcile_observed_ap(
                        self.progress,
                        ap_observed=observation.ap_current,
                    )
                except ValueError as exc:
                    return str(exc)
        return None

    def next_command(self, recognition: CampaignFrameRecognition) -> CampaignRuntimeCommand:
        if self._last_frame_hash == recognition.frame_sha256 and recognition.observation.screen == CampaignScreen.UNKNOWN:
            return self._terminal(CampaignAction.BLOCKED, "unchanged unknown frame")
        self._last_frame_hash = recognition.frame_sha256

        error = self._initialize_or_reconcile(recognition)
        if error:
            return self._terminal(CampaignAction.BLOCKED, error)
        assert self.progress is not None

        decision = campaign_next_decision(self.config, self.progress, recognition.observation)
        if decision.terminal:
            return self._terminal(decision.action, decision.reason)
        if decision.action == CampaignAction.WAIT_FOR_BATTLE_RESULT:
            return CampaignRuntimeCommand(
                decision.action,
                "wait",
                decision.reason,
                wait_seconds=self.config.battle_poll_seconds,
            )

        target = recognition.target(decision.target_identity) if decision.target_identity else None
        if decision.action == CampaignAction.OPEN_CAMPAIGN and target is None:
            swipe = HOME_PAN_GESTURES[self._home_pan_index % len(HOME_PAN_GESTURES)]
            self._home_pan_index += 1
            return self._checked(CampaignRuntimeCommand(decision.action, "swipe", "pan Home until Campaign is visible", swipe=swipe))
        if decision.action == CampaignAction.NAVIGATE_CHAPTER and target is None:
            swipe = CHAPTER_PAN_GESTURES[self._chapter_pan_index % len(CHAPTER_PAN_GESTURES)]
            self._chapter_pan_index += 1
            return self._checked(CampaignRuntimeCommand(decision.action, "swipe", decision.reason, swipe=swipe))
        if decision.action == CampaignAction.NAVIGATE_STAGE and target is None:
            swipe = STAGE_PAN_GESTURES[self._stage_pan_index % len(STAGE_PAN_GESTURES)]
            self._stage_pan_index += 1
            return self._checked(CampaignRuntimeCommand(decision.action, "swipe", decision.reason, swipe=swipe))
        if decision.action == CampaignAction.RETURN_HOME and target is None:
            if self._return_request_sent:
                return self._terminal(CampaignAction.BLOCKED, "Campaign exit did not appear after one base request")
            request_target = recognition.target("campaign-base-request")
            if request_target is None:
                return self._terminal(CampaignAction.BLOCKED, "Campaign base request control is not bound")
            return self._checked(CampaignRuntimeCommand(
                decision.action,
                "tap",
                "request the highlighted Campaign exit",
                target_identity="campaign-base-request",
                target_roi=request_target,
            ))
        if target is None:
            return self._terminal(
                CampaignAction.BLOCKED,
                f"recognized action target is not bound: {decision.target_identity}",
            )
        return self._checked(CampaignRuntimeCommand(
            decision.action,
            "tap",
            decision.reason,
            target_identity=decision.target_identity,
            target_roi=target,
        ))

    def accept_dispatched(self, command: CampaignRuntimeCommand) -> None:
        if command.kind not in {"tap", "swipe"}:
            raise ValueError("only dispatched input commands may be accepted")
        self._last_dispatched_signature = (
            command.action,
            command.kind,
            command.target_identity,
            command.target_roi,
            command.swipe,
        )
        if command.action == CampaignAction.CONTINUE_VICTORY:
            self._awaiting_victory_ap = True
        elif command.action == CampaignAction.RETURN_HOME and command.target_identity == "campaign-base-request":
            self._return_request_sent = True
        elif command.action == CampaignAction.RETURN_HOME_AFTER_DEFEAT:
            assert self.progress is not None
            self.progress = replace(self.progress, loss_seen=True)
