"""Fail-closed controller for recognized local Campaign Auto Battle frames.

Transport is intentionally injected.  The controller emits one bounded tap, swipe, or wait at a
time and advances its AP ledger only after the caller confirms the corresponding dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .campaign_auto_battle import (
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignRouteProgress,
    CampaignScreen,
    campaign_next_decision,
    reconcile_observed_ap,
    record_verified_victory,
)
from .campaign_auto_battle_vision import Box, CampaignFrameRecognition


# Retained for orchestrator/governance symbol presence. Campaign entry must not cycle these;
# unbound OPEN_CAMPAIGN fails closed toward Home Atlas home.building.campaign instead.
HOME_PAN_GESTURES = (
    (427, 703, 107, 836, 600),
    (107, 836, 427, 703, 600),
    (560, 720, 220, 420, 600),
    (220, 420, 560, 720, 600),
)

# Feedback-controlled residual pans (not open-loop round-robin).
# Drag left reveals content toward higher map numbers; drag right reveals lower.
CHAPTER_PAN_TOWARD_HIGHER = (620, 620, 180, 620, 550)
CHAPTER_PAN_TOWARD_LOWER = (180, 620, 620, 620, 550)
CHAPTER_PAN_TOWARD_HIGHER_STRONG = (720, 580, 80, 580, 700)
CHAPTER_PAN_TOWARD_LOWER_STRONG = (80, 580, 720, 580, 700)
STAGE_PAN_TOWARD_HIGHER = (620, 700, 220, 700, 500)
STAGE_PAN_TOWARD_LOWER = (220, 700, 620, 700, 500)
STAGE_PAN_TOWARD_HIGHER_STRONG = (720, 700, 100, 700, 650)
STAGE_PAN_TOWARD_LOWER_STRONG = (100, 700, 720, 700, 650)

# Legacy gesture tables retained as non-authoritative references only.
CHAPTER_PAN_GESTURES = (
    CHAPTER_PAN_TOWARD_HIGHER,
    (400, 840, 400, 300, 550),
    CHAPTER_PAN_TOWARD_LOWER,
    (400, 300, 400, 840, 550),
    (600, 780, 220, 360, 600),
    (220, 360, 600, 780, 600),
)
STAGE_PAN_GESTURES = (
    STAGE_PAN_TOWARD_HIGHER,
    (400, 850, 400, 330, 500),
    STAGE_PAN_TOWARD_LOWER,
    (400, 330, 400, 850, 500),
)

CAMPAIGN_HOME_ATLAS_BUILDING_ID = "home.building.campaign"


def home_pan_gestures_for_campaign_entry() -> None:
    """Fail-closed guard: open-loop HOME_PAN_GESTURES must not open Campaign."""

    raise RuntimeError(
        "HOME_PAN_GESTURES is fail-closed for Campaign entry; "
        f"use Home Atlas {CAMPAIGN_HOME_ATLAS_BUILDING_ID}"
    )


def residual_pan_swipe(
    target: int,
    visible: tuple[int, ...],
    *,
    toward_higher: tuple[int, int, int, int, int],
    toward_lower: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int]:
    """Choose one pan from remembered visible numbers versus the target residual.

    Empty visible sets are not a residual baseline; callers must fail closed before pan.
    """

    if not visible:
        raise ValueError(
            "residual pan requires a non-empty visible set; empty baseline is not a residual"
        )
    low = min(visible)
    high = max(visible)
    center = (low + high) / 2.0
    if target > center:
        return toward_higher
    if target < center:
        return toward_lower
    if abs(target - high) <= abs(target - low):
        return toward_higher
    return toward_lower


def stronger_residual_pan_swipe(
    swipe: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int]:
    """Return a materially longer pan in the same residual direction.

    Used when a prior residual pan made progress but the default geometry would be an
    identical retry. This is a corrected longer gesture, not a blind duplicate.
    """

    mapping = {
        CHAPTER_PAN_TOWARD_HIGHER: CHAPTER_PAN_TOWARD_HIGHER_STRONG,
        CHAPTER_PAN_TOWARD_LOWER: CHAPTER_PAN_TOWARD_LOWER_STRONG,
        STAGE_PAN_TOWARD_HIGHER: STAGE_PAN_TOWARD_HIGHER_STRONG,
        STAGE_PAN_TOWARD_LOWER: STAGE_PAN_TOWARD_LOWER_STRONG,
        CHAPTER_PAN_TOWARD_HIGHER_STRONG: CHAPTER_PAN_TOWARD_HIGHER_STRONG,
        CHAPTER_PAN_TOWARD_LOWER_STRONG: CHAPTER_PAN_TOWARD_LOWER_STRONG,
        STAGE_PAN_TOWARD_HIGHER_STRONG: STAGE_PAN_TOWARD_HIGHER_STRONG,
        STAGE_PAN_TOWARD_LOWER_STRONG: STAGE_PAN_TOWARD_LOWER_STRONG,
    }
    if swipe not in mapping:
        raise ValueError("stronger residual pan requires a known residual swipe geometry")
    return mapping[swipe]


def visible_set_moved_toward_target(
    target: int,
    before: tuple[int, ...],
    after: tuple[int, ...],
) -> bool:
    """True only when a non-empty after set is strictly closer to the target than before."""

    if not after or not before:
        return False
    if after == before:
        return False
    before_dist = min(abs(value - target) for value in before)
    after_dist = min(abs(value - target) for value in after)
    if after_dist < before_dist:
        return True
    before_center = (min(before) + max(before)) / 2.0
    after_center = (min(after) + max(after)) / 2.0
    return abs(target - after_center) < abs(target - before_center)


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
        self._awaiting_victory_ap = False
        self._return_request_sent = False
        self._last_frame_hash: str | None = None
        self._last_dispatched_signature: tuple[object, ...] | None = None
        self._remembered_chapter_visible: tuple[int, ...] | None = None
        self._remembered_stage_visible: tuple[int, ...] | None = None
        self._awaiting_chapter_progress = False
        self._awaiting_stage_progress = False
        self._destination_verified = False
        self._awaiting_atlas_chapter_progress = False
        self._remembered_atlas_chapter_distance: float | None = None
        self._remembered_atlas_localization_support: tuple[str, ...] | None = None
        self._remembered_atlas_pan_direction: str | None = None
        self._atlas_lost_localization_continuation_sent = False
        self._auto_confirmed_for_current_battle = False

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
        if command.kind in {"tap", "swipe", "home_atlas_entry"} and signature == self._last_dispatched_signature:
            return self._terminal(CampaignAction.BLOCKED, "identical input retry is forbidden")
        return command

    def _visible_chapter_rois(
        self, recognition: CampaignFrameRecognition
    ) -> dict[int, tuple[int, int, int, int]]:
        rois: dict[int, tuple[int, int, int, int]] = {}
        for identity, box in recognition.targets:
            if not identity.startswith("campaign-chapter-"):
                continue
            suffix = identity.split("campaign-chapter-", 1)[-1]
            if not suffix.isdigit():
                continue
            rois[int(suffix)] = tuple(int(value) for value in box)
        return rois

    def _atlas_chapter_command(
        self,
        recognition: CampaignFrameRecognition,
        frame: object,
    ) -> CampaignRuntimeCommand:
        from tasks.campaign_atlas_chapter_nav import resolve_atlas_chapter_navigation

        decision = resolve_atlas_chapter_navigation(
            frame,  # type: ignore[arg-type]
            destination_id=self.config.target_stage.identity,
            visible_chapter_rois=self._visible_chapter_rois(recognition),
        )
        if self._awaiting_atlas_chapter_progress:
            if decision.kind == "tap":
                self._awaiting_atlas_chapter_progress = False
                self._remembered_atlas_chapter_distance = None
                self._remembered_atlas_localization_support = None
                self._remembered_atlas_pan_direction = None
                self._atlas_lost_localization_continuation_sent = False
            elif (
                self._remembered_atlas_localization_support is not None
                and decision.localization_support
                != self._remembered_atlas_localization_support
            ):
                # Anchor/ORB support identity changed; projected distances are not comparable.
                self._awaiting_atlas_chapter_progress = False
                self._remembered_atlas_chapter_distance = None
                self._remembered_atlas_localization_support = None
            elif (
                decision.distance_to_screen_center_px is not None
                and self._remembered_atlas_chapter_distance is not None
                and decision.distance_to_screen_center_px
                < self._remembered_atlas_chapter_distance - 8.0
            ):
                self._awaiting_atlas_chapter_progress = False
            else:
                return self._terminal(
                    CampaignAction.BLOCKED,
                    "Campaign atlas chapter pan produced no progress toward the configured landmark",
                )

        if decision.kind == "tap":
            assert decision.target_roi is not None
            return self._checked(
                CampaignRuntimeCommand(
                    CampaignAction.NAVIGATE_CHAPTER,
                    "tap",
                    decision.reason,
                    target_identity=decision.target_identity,
                    target_roi=decision.target_roi,
                )
            )
        if decision.kind == "swipe":
            assert decision.swipe is not None
            swipe = decision.swipe
            reason = decision.reason
            signature = (
                CampaignAction.NAVIGATE_CHAPTER,
                "swipe",
                None,
                None,
                swipe,
            )
            if signature == self._last_dispatched_signature:
                from tasks.campaign_atlas_vision import (
                    HUD_SAFE_PAN_HALF_TRAVEL_STRONG_PX,
                    hud_safe_pan_gesture,
                )

                direction = decision.pan_direction
                if direction is None:
                    return self._terminal(
                        CampaignAction.BLOCKED,
                        "Campaign atlas chapter pan would repeat without a stronger direction",
                    )
                swipe = hud_safe_pan_gesture(
                    direction,
                    travel_px=HUD_SAFE_PAN_HALF_TRAVEL_STRONG_PX,
                ).as_swipe()
                reason = (
                    f"{decision.reason}; stronger atlas-directed pan after measured progress"
                )
            command = self._checked(
                CampaignRuntimeCommand(
                    CampaignAction.NAVIGATE_CHAPTER,
                    "swipe",
                    reason,
                    swipe=swipe,
                )
            )
            if not command.terminal:
                self._remembered_atlas_chapter_distance = decision.distance_to_screen_center_px
                self._remembered_atlas_localization_support = decision.localization_support
                self._remembered_atlas_pan_direction = decision.pan_direction
            return command
        if (
            decision.kind == "blocked"
            and self._remembered_atlas_pan_direction is not None
            and not self._atlas_lost_localization_continuation_sent
        ):
            from tasks.campaign_atlas_vision import (
                HUD_SAFE_PAN_HALF_TRAVEL_STRONG_PX,
                hud_safe_pan_gesture,
            )

            self._atlas_lost_localization_continuation_sent = True
            return self._checked(
                CampaignRuntimeCommand(
                    CampaignAction.NAVIGATE_CHAPTER,
                    "swipe",
                    "one bounded continuation of the last atlas-directed pan after localization support dropped",
                    swipe=hud_safe_pan_gesture(
                        self._remembered_atlas_pan_direction,
                        travel_px=HUD_SAFE_PAN_HALF_TRAVEL_STRONG_PX,
                    ).as_swipe(),
                )
            )
        return self._terminal(CampaignAction.BLOCKED, decision.reason)

    def _initialize_or_reconcile(self, recognition: CampaignFrameRecognition) -> str | None:
        observation = recognition.observation
        if observation.screen == CampaignScreen.BATTLE and observation.auto_enabled:
            self._auto_confirmed_for_current_battle = True
        elif observation.screen not in {CampaignScreen.BATTLE, CampaignScreen.UNKNOWN}:
            self._auto_confirmed_for_current_battle = False
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

    def _feedback_blocked_if_no_progress(
        self,
        *,
        awaiting: bool,
        remembered: tuple[int, ...] | None,
        visible: tuple[int, ...],
        target: int,
        label: str,
    ) -> CampaignRuntimeCommand | None:
        if not awaiting:
            return None
        # Empty / OCR-failed visible sets are never progress.
        if not visible:
            return self._terminal(
                CampaignAction.BLOCKED,
                f"{label} pan produced empty/OCR-failed visible set; not progress toward target",
            )
        if remembered is None:
            return self._terminal(
                CampaignAction.BLOCKED,
                f"{label} pan progress gate missing remembered visible set",
            )
        if not visible_set_moved_toward_target(target, remembered, visible):
            return self._terminal(
                CampaignAction.BLOCKED,
                f"{label} pan produced no progress toward the configured target",
            )
        return None

    def next_command(
        self,
        recognition: CampaignFrameRecognition,
        frame: object | None = None,
    ) -> CampaignRuntimeCommand:
        if self._last_frame_hash == recognition.frame_sha256 and recognition.observation.screen == CampaignScreen.UNKNOWN:
            return self._terminal(CampaignAction.BLOCKED, "unchanged unknown frame")
        self._last_frame_hash = recognition.frame_sha256

        error = self._initialize_or_reconcile(recognition)
        if error:
            return self._terminal(CampaignAction.BLOCKED, error)
        assert self.progress is not None

        observation = recognition.observation
        if self._destination_verified and self.config.navigation_only:
            return self._terminal(
                CampaignAction.NAVIGATION_ONLY_COMPLETE,
                "destination already verified; navigation-only complete",
            )

        no_chapter_progress = self._feedback_blocked_if_no_progress(
            awaiting=self._awaiting_chapter_progress,
            remembered=self._remembered_chapter_visible,
            visible=observation.visible_chapter_numbers,
            target=self.config.target_stage.chapter,
            label="chapter",
        )
        if no_chapter_progress is not None:
            return no_chapter_progress
        self._awaiting_chapter_progress = False

        no_stage_progress = self._feedback_blocked_if_no_progress(
            awaiting=self._awaiting_stage_progress,
            remembered=self._remembered_stage_visible,
            visible=observation.visible_stage_numbers,
            target=self.config.target_stage.stage,
            label="stage",
        )
        if no_stage_progress is not None:
            return no_stage_progress
        self._awaiting_stage_progress = False

        decision = campaign_next_decision(self.config, self.progress, observation)
        if decision.terminal:
            if decision.action == CampaignAction.DESTINATION_VERIFIED:
                self._destination_verified = True
            return self._terminal(decision.action, decision.reason)
        if decision.action == CampaignAction.WAIT_FOR_BATTLE_RESULT:
            return CampaignRuntimeCommand(
                decision.action,
                "wait",
                decision.reason,
                wait_seconds=self.config.battle_poll_seconds,
            )
        if decision.action == CampaignAction.ENABLE_AUTO and self._auto_confirmed_for_current_battle:
            return CampaignRuntimeCommand(
                CampaignAction.WAIT_FOR_BATTLE_RESULT,
                "wait",
                "Auto was positively confirmed for this battle; ignore transient disabled-state recognition",
                wait_seconds=self.config.battle_poll_seconds,
            )

        target = recognition.target(decision.target_identity) if decision.target_identity else None
        if decision.action == CampaignAction.OPEN_CAMPAIGN:
            # Always use the accepted Home Atlas seam. A legacy direct Campaign ROI may be
            # visible at some Home camera positions but is not an authorized entry target.
            return self._checked(
                CampaignRuntimeCommand(
                    decision.action,
                    "home_atlas_entry",
                    (
                        "open Campaign via Home Atlas "
                        f"{CAMPAIGN_HOME_ATLAS_BUILDING_ID}; HOME_PAN_GESTURES is fail-closed"
                    ),
                    target_identity=CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                )
            )
        if decision.action == CampaignAction.NAVIGATE_CHAPTER:
            if target is not None:
                from tasks.campaign_atlas_chapter_nav import chapter_roi_is_safely_framed

                if chapter_roi_is_safely_framed(target):
                    return self._checked(
                        CampaignRuntimeCommand(
                            decision.action,
                            "tap",
                            f"{decision.reason}; complete chapter ROI is safely framed",
                            target_identity=decision.target_identity,
                            target_roi=target,
                        )
                    )
                if frame is None:
                    return self._terminal(
                        CampaignAction.BLOCKED,
                        "recognized chapter target is edge/HUD clipped and atlas reframing requires the current native frame",
                    )
            if frame is None:
                return self._terminal(
                    CampaignAction.BLOCKED,
                    "Campaign atlas chapter navigation requires the current native frame",
                )
            return self._atlas_chapter_command(recognition, frame)
        if decision.action == CampaignAction.NAVIGATE_STAGE and target is None:
            visible = observation.visible_stage_numbers
            if not visible:
                return self._terminal(
                    CampaignAction.BLOCKED,
                    "stage residual pan requires non-empty visible stage set before pan",
                )
            swipe = residual_pan_swipe(
                self.config.target_stage.stage,
                visible,
                toward_higher=STAGE_PAN_TOWARD_HIGHER,
                toward_lower=STAGE_PAN_TOWARD_LOWER,
            )
            reason = decision.reason
            signature = (
                decision.action,
                "swipe",
                None,
                None,
                swipe,
            )
            if signature == self._last_dispatched_signature:
                swipe = stronger_residual_pan_swipe(swipe)
                reason = f"{decision.reason}; stronger residual stage pan after measured progress"
            command = self._checked(
                CampaignRuntimeCommand(
                    decision.action,
                    "swipe",
                    reason,
                    swipe=swipe,
                )
            )
            if not command.terminal:
                # Never remember empty () as a residual baseline.
                self._remembered_stage_visible = visible
            return command
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
        if command.kind not in {"tap", "swipe", "home_atlas_entry"}:
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
        elif command.kind == "swipe" and command.action == CampaignAction.NAVIGATE_CHAPTER:
            if "atlas" in command.reason.casefold():
                self._awaiting_atlas_chapter_progress = True
            else:
                self._awaiting_chapter_progress = True
        elif command.kind == "swipe" and command.action == CampaignAction.NAVIGATE_STAGE:
            self._awaiting_stage_progress = True
