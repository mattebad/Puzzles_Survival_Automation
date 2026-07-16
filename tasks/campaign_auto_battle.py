"""Dormant Campaign Auto Battle route contract.

This module converts positively recognized screenshot state into one semantic next action.  It
does not capture frames, select coordinates, dispatch input, register a runtime task, or assume
that a battle completed after a fixed delay.  A future Bliss adapter must bind every non-wait
decision to fresh 800x1280 evidence and the central safety executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re


_STAGE_RE = re.compile(r"^(?:campaign-stage-)?([1-9]\d*)-([1-9]\d*)-([1-9]\d*)$")


class CampaignScreen(str, Enum):
    HOME_BASE = "HOME_BASE"
    TIER_MAP = "CAMPAIGN_TIER_MAP"
    CHAPTER_MAP = "CAMPAIGN_CHAPTER_MAP"
    STAGE_DIALOG = "CAMPAIGN_STAGE_DIALOG"
    HERO_LINEUP = "CAMPAIGN_HERO_LINEUP"
    BATTLE = "CAMPAIGN_BATTLE"
    RESULT = "CAMPAIGN_RESULT"
    UNKNOWN = "UNKNOWN"


class BattleResult(str, Enum):
    ACTIVE = "ACTIVE"
    VICTORY = "VICTORY"
    DEFEAT = "DEFEAT"
    UNKNOWN = "UNKNOWN"


class CampaignAction(str, Enum):
    OPEN_CAMPAIGN = "OPEN_CAMPAIGN"
    SELECT_TIER = "SELECT_TIER"
    NAVIGATE_CHAPTER = "NAVIGATE_CHAPTER"
    NAVIGATE_STAGE = "NAVIGATE_STAGE"
    SELECT_STAGE = "SELECT_STAGE"
    CHALLENGE_STAGE = "CHALLENGE_STAGE"
    CONFIRM_LINEUP = "CONFIRM_LINEUP"
    ENABLE_AUTO = "ENABLE_AUTO"
    WAIT_FOR_BATTLE_RESULT = "WAIT_FOR_BATTLE_RESULT"
    CONTINUE_VICTORY = "CONTINUE_VICTORY"
    RETURN_HOME_AFTER_DEFEAT = "RETURN_HOME_AFTER_DEFEAT"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, order=True)
class CampaignStage:
    tier: int
    chapter: int
    stage: int

    def __post_init__(self) -> None:
        if min(self.tier, self.chapter, self.stage) <= 0:
            raise ValueError("Campaign tier, chapter, and stage must be positive")

    @classmethod
    def parse(cls, value: str) -> "CampaignStage":
        match = _STAGE_RE.fullmatch(value.strip())
        if not match:
            raise ValueError("stage must use positive tier-chapter-stage form, for example 1-20-9")
        return cls(*(int(part) for part in match.groups()))

    @property
    def identity(self) -> str:
        return f"{self.tier}-{self.chapter}-{self.stage}"

    @property
    def dialog_identity(self) -> str:
        return f"[{self.chapter}-{self.stage}]"


@dataclass(frozen=True)
class CampaignAutoBattleConfig:
    target_stage: CampaignStage
    ap_cost: int
    ap_budget: int
    max_runs: int
    battle_poll_seconds: float = 1.0
    battle_timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.ap_cost <= 0:
            raise ValueError("ap_cost must be positive")
        if self.ap_budget <= 0:
            raise ValueError("ap_budget must be positive")
        if self.max_runs <= 0:
            raise ValueError("max_runs must be positive")
        if self.battle_poll_seconds <= 0:
            raise ValueError("battle_poll_seconds must be positive")
        if self.battle_timeout_seconds <= self.battle_poll_seconds:
            raise ValueError("battle_timeout_seconds must exceed battle_poll_seconds")


@dataclass(frozen=True)
class CampaignRouteProgress:
    initial_ap: int
    current_ap: int
    completed_runs: int = 0
    ap_spent: int = 0
    loss_seen: bool = False

    def __post_init__(self) -> None:
        if min(self.initial_ap, self.current_ap, self.completed_runs, self.ap_spent) < 0:
            raise ValueError("Campaign progress values cannot be negative")


@dataclass(frozen=True)
class CampaignRouteObservation:
    screen: CampaignScreen
    recognized: bool = True
    overlay_state: str = "none_observed"
    selected_tier: int | None = None
    chapter_number: int | None = None
    visible_stage_numbers: tuple[int, ...] = ()
    stage_dialog: CampaignStage | None = None
    chapter_navigation_available: bool = False
    stage_navigation_available: bool = False
    ap_current: int | None = None
    ap_cost: int | None = None
    refill_visible: bool = False
    challenge_ready: bool = False
    lineup_challenge_ready: bool = False
    auto_enabled: bool = False
    winner_visible: bool = False
    loot_visible: bool = False
    tap_to_continue_visible: bool = False
    defeat_visible: bool = False
    return_control_visible: bool = False
    battle_elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class CampaignDecision:
    action: CampaignAction
    reason: str
    expected_successor: CampaignScreen | None = None
    target_identity: str | None = None
    terminal: bool = False
    dispatch_authorized: bool = False


def planned_run_count(
    *, ap_available: int, ap_cost: int, ap_budget: int, max_runs: int
) -> int:
    """Return the bounded number of whole stage runs; never imply a refill."""

    if min(ap_available, ap_budget) < 0 or ap_cost <= 0 or max_runs <= 0:
        raise ValueError("invalid AP planning values")
    return min(ap_available // ap_cost, ap_budget // ap_cost, max_runs)


def classify_battle_result(observation: CampaignRouteObservation) -> BattleResult:
    """Recognize only explicit active, victory, or defeat states."""

    victory = bool(
        observation.winner_visible
        and observation.loot_visible
        and observation.tap_to_continue_visible
    )
    defeat = bool(
        observation.defeat_visible
        and (observation.tap_to_continue_visible or observation.return_control_visible)
    )
    if victory and defeat:
        return BattleResult.UNKNOWN
    if victory:
        return BattleResult.VICTORY
    if defeat:
        return BattleResult.DEFEAT
    if observation.screen == CampaignScreen.BATTLE:
        return BattleResult.ACTIVE
    return BattleResult.UNKNOWN


def record_verified_victory(
    progress: CampaignRouteProgress,
    *,
    ap_cost: int,
    ap_after: int,
) -> CampaignRouteProgress:
    """Advance one run only when the exact AP delta is independently observed."""

    if ap_cost <= 0 or ap_after != progress.current_ap - ap_cost:
        raise ValueError("victory AP delta is not exact")
    return replace(
        progress,
        current_ap=ap_after,
        completed_runs=progress.completed_runs + 1,
        ap_spent=progress.ap_spent + ap_cost,
    )


def _decision(
    action: CampaignAction,
    reason: str,
    *,
    successor: CampaignScreen | None = None,
    target: str | None = None,
    terminal: bool = False,
) -> CampaignDecision:
    return CampaignDecision(
        action=action,
        reason=reason,
        expected_successor=successor,
        target_identity=target,
        terminal=terminal,
        dispatch_authorized=False,
    )


def campaign_next_decision(
    config: CampaignAutoBattleConfig,
    progress: CampaignRouteProgress,
    observation: CampaignRouteObservation,
) -> CampaignDecision:
    """Plan one semantic next action from fresh recognized state.

    Decisions are intentionally coordinate-free and dormant.  Unknown state, overlays, stale AP,
    stage mismatch, missing navigation targets, loss, or battle timeout fail closed.
    """

    if not observation.recognized or observation.overlay_state not in {"none", "none_observed"}:
        return _decision(CampaignAction.BLOCKED, "screen or overlay is not positively recognized", terminal=True)

    total_runs = planned_run_count(
        ap_available=progress.initial_ap,
        ap_cost=config.ap_cost,
        ap_budget=config.ap_budget,
        max_runs=config.max_runs,
    )
    if progress.ap_spent != progress.completed_runs * config.ap_cost:
        return _decision(CampaignAction.BLOCKED, "recorded AP spend does not match completed runs", terminal=True)
    if progress.current_ap != progress.initial_ap - progress.ap_spent:
        return _decision(CampaignAction.BLOCKED, "current AP does not match the verified run ledger", terminal=True)

    if observation.screen == CampaignScreen.HOME_BASE:
        if progress.loss_seen:
            return _decision(CampaignAction.COMPLETE, "returned home after a loss; repeats are disabled", terminal=True)
        if progress.completed_runs >= total_runs:
            return _decision(CampaignAction.COMPLETE, "bounded AP plan is complete at Home/Base", terminal=True)
        return _decision(
            CampaignAction.OPEN_CAMPAIGN,
            "more bounded AP runs remain",
            successor=CampaignScreen.TIER_MAP,
            target="campaign-entry",
        )

    if observation.screen == CampaignScreen.TIER_MAP:
        if observation.selected_tier != config.target_stage.tier:
            return _decision(
                CampaignAction.SELECT_TIER,
                "configured Campaign tier is not selected",
                successor=CampaignScreen.TIER_MAP,
                target=f"campaign-tier-{config.target_stage.tier}",
            )
        if not observation.chapter_navigation_available:
            return _decision(CampaignAction.BLOCKED, "exact target chapter navigation is not bound", terminal=True)
        if observation.chapter_number != config.target_stage.chapter:
            return _decision(
                CampaignAction.NAVIGATE_CHAPTER,
                "navigate to the configured chapter",
                successor=CampaignScreen.CHAPTER_MAP,
                target=f"campaign-chapter-{config.target_stage.chapter}",
            )
        return _decision(
            CampaignAction.NAVIGATE_CHAPTER,
            "enter the recognized configured chapter",
            successor=CampaignScreen.CHAPTER_MAP,
            target=f"campaign-chapter-{config.target_stage.chapter}",
        )

    if observation.screen == CampaignScreen.CHAPTER_MAP:
        if (
            observation.selected_tier != config.target_stage.tier
            or observation.chapter_number != config.target_stage.chapter
        ):
            return _decision(CampaignAction.BLOCKED, "chapter map identity does not match configured stage", terminal=True)
        if config.target_stage.stage not in observation.visible_stage_numbers:
            if not observation.stage_navigation_available:
                return _decision(CampaignAction.BLOCKED, "exact target stage is not visible or navigable", terminal=True)
            return _decision(
                CampaignAction.NAVIGATE_STAGE,
                "move the chapter map until the exact stage target is visible",
                successor=CampaignScreen.CHAPTER_MAP,
                target=f"campaign-stage-{config.target_stage.identity}",
            )
        return _decision(
            CampaignAction.SELECT_STAGE,
            "select the exact visible configured stage",
            successor=CampaignScreen.STAGE_DIALOG,
            target=f"campaign-stage-{config.target_stage.identity}",
        )

    if observation.screen == CampaignScreen.STAGE_DIALOG:
        if observation.stage_dialog != config.target_stage:
            return _decision(CampaignAction.BLOCKED, "stage dialog identity mismatch", terminal=True)
        if observation.refill_visible:
            return _decision(CampaignAction.BLOCKED, "AP refill is forbidden", terminal=True)
        if observation.ap_current != progress.current_ap or observation.ap_cost != config.ap_cost:
            return _decision(CampaignAction.BLOCKED, "fresh AP or stage cost does not match the bounded plan", terminal=True)
        if progress.completed_runs >= total_runs or observation.ap_current < config.ap_cost:
            return _decision(CampaignAction.BLOCKED, "no additional bounded stage run is affordable", terminal=True)
        if not observation.challenge_ready:
            return _decision(CampaignAction.BLOCKED, "exact Challenge control is not ready", terminal=True)
        return _decision(
            CampaignAction.CHALLENGE_STAGE,
            "exact stage, AP cost, and budget are recognized",
            successor=CampaignScreen.HERO_LINEUP,
            target=f"campaign-challenge-{config.target_stage.identity}",
        )

    if observation.screen == CampaignScreen.HERO_LINEUP:
        if not observation.lineup_challenge_ready:
            return _decision(CampaignAction.BLOCKED, "Hero Lineup Challenge control is not ready", terminal=True)
        return _decision(
            CampaignAction.CONFIRM_LINEUP,
            "confirm the recognized Hero Lineup",
            successor=CampaignScreen.BATTLE,
            target="campaign-lineup-challenge",
        )

    battle_result = classify_battle_result(observation)
    if battle_result == BattleResult.VICTORY:
        return _decision(
            CampaignAction.CONTINUE_VICTORY,
            "WINNER, Loot, and Tap to continue are all visible",
            successor=CampaignScreen.HOME_BASE,
            target="campaign-victory-continue",
        )
    if battle_result == BattleResult.DEFEAT:
        return _decision(
            CampaignAction.RETURN_HOME_AFTER_DEFEAT,
            "explicit defeat terminal recognized; do not repeat",
            successor=CampaignScreen.HOME_BASE,
            target="campaign-defeat-return",
        )
    if observation.screen == CampaignScreen.BATTLE:
        if observation.battle_elapsed_seconds >= config.battle_timeout_seconds:
            return _decision(CampaignAction.BLOCKED, "battle terminal was not recognized before timeout", terminal=True)
        if not observation.auto_enabled:
            return _decision(
                CampaignAction.ENABLE_AUTO,
                "battle is active and Auto is not positively enabled",
                successor=CampaignScreen.BATTLE,
                target="campaign-auto",
            )
        return _decision(
            CampaignAction.WAIT_FOR_BATTLE_RESULT,
            "battle remains active; capture and classify another frame",
            successor=CampaignScreen.BATTLE,
        )

    return _decision(CampaignAction.BLOCKED, "unsupported or ambiguous Campaign state", terminal=True)
