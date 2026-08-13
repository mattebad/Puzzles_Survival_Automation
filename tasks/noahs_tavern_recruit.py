"""Separate semantic contract for Noah's Tavern Daily Free Hero Recruit.

This module is intentionally independent from the legacy recruitment contracts.  It models
each Tavern tier separately and never exposes a Claim action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI
from .profile import PROFILE_ID


HOME_BASE_SCREEN = "HOME_BASE"
NOAHS_TAVERN_SCREEN = "NOAHS_TAVERN"
HERO_RECRUIT_RESULT_SCREEN = "HERO_RECRUIT_RESULT"
UNKNOWN_SCREEN = "UNKNOWN"
NOAHS_TAVERN_FREE_TARGET = "NOAHS_TAVERN_DAILY_FREE"
NOAHS_TAVERN_TIER_TARGET_PREFIX = "NOAHS_TAVERN_TIER_"
NOAHS_TAVERN_REQUIRED_RECRUITS = 5


class RecruitTier(str, Enum):
    BASIC = "Basic Recruit"
    INT = "Int. Recruit"
    ADV = "Adv. Recruit"


TIER_ATTEMPT_MAXIMUMS = {
    RecruitTier.BASIC: 5,
    RecruitTier.INT: 1,
    RecruitTier.ADV: 1,
}


@dataclass(frozen=True)
class TierState:
    tier: RecruitTier
    daily_attempt_maximum: int
    attempts_remaining: Optional[int]
    cooldown_duration_seconds: Optional[int] = None
    cooldown_active: bool = False
    next_eligible_timestamp: Optional[float] = None
    last_dispatch_state: str = "never_dispatched"
    last_postcondition_state: str = "not_observed"

    def __post_init__(self) -> None:
        expected = TIER_ATTEMPT_MAXIMUMS[self.tier]
        if self.daily_attempt_maximum != expected:
            raise ValueError(f"{self.tier.value} maximum must be {expected}")
        if self.attempts_remaining is not None and not 0 <= self.attempts_remaining <= expected:
            raise ValueError("attempts_remaining is outside the tier maximum")
        if self.cooldown_duration_seconds is not None and self.cooldown_duration_seconds <= 0:
            raise ValueError("cooldown duration must be positive")


@dataclass(frozen=True)
class NoahTierObservation:
    tier: RecruitTier
    daily_attempt_maximum: int
    attempts_remaining: Optional[int]
    cooldown_text: str = ""
    cooldown_duration_seconds: Optional[int] = None
    cooldown_active: bool = False
    next_eligible_timestamp: Optional[float] = None
    free_control_visible: bool = False
    free_control_enabled: bool = False
    target_roi: ROI = (0, 0, 0, 0)
    panel_roi: ROI = (0, 0, 0, 0)
    target_identity: str = ""
    control_class: str = ""
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    premium_control_visible: bool = False
    overlay_state: str = "none"
    overlapping_target: bool = False
    recognized: bool = False

    def __post_init__(self) -> None:
        if self.daily_attempt_maximum != TIER_ATTEMPT_MAXIMUMS[self.tier]:
            raise ValueError("tier maximum does not match the canonical tier")


@dataclass(frozen=True)
class NoahTavernObservation:
    screen_state: str
    selected_tier: Optional[RecruitTier]
    tiers: tuple[NoahTierObservation, ...]
    frame_sha256: str
    captured_monotonic: Optional[float] = None
    stale: bool = False
    overlay_state: str = "none"
    recognized: bool = False
    result_tier: Optional[RecruitTier] = None
    result_identity: str = ""
    safe_close_visible: bool = False
    safe_close_roi: ROI = (0, 0, 0, 0)
    premium_result_control_visible: bool = False
    daily_quest_completed: int = 0
    daily_quest_required: int = NOAHS_TAVERN_REQUIRED_RECRUITS
    claim_visible: bool = False
    home_tavern_target_roi: Optional[ROI] = None

    def tier(self, identity: RecruitTier) -> NoahTierObservation:
        for item in self.tiers:
            if item.tier == identity:
                return item
        raise KeyError(identity)


@dataclass
class DailyQuestProgress:
    recruits_completed: int = 0
    required_recruits: int = NOAHS_TAVERN_REQUIRED_RECRUITS
    claim_dormant: bool = True

    @property
    def ready_to_claim(self) -> bool:
        return self.recruits_completed >= self.required_recruits


_TIME_RE = re.compile(r"(?:(\d+)\s*d\s*)?(\d{1,3}):(\d{2})(?::(\d{2}))?", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*(?:minutes?|mins?)", re.IGNORECASE)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_cooldown_seconds(text: str | None) -> Optional[int]:
    """Parse Tavern timer text such as ``00:09:52`` or ``1d23:59:52``."""

    normalized = " ".join((text or "").casefold().split())
    match = _TIME_RE.search(normalized)
    if match:
        days = int(match.group(1) or 0)
        first = int(match.group(2))
        minutes = int(match.group(3))
        seconds = int(match.group(4) or 0)
        if match.group(4) is None:
            return first * 60 + minutes
        return days * 86400 + first * 3600 + minutes * 60 + seconds
    minutes_match = _MINUTES_RE.search(normalized)
    return int(minutes_match.group(1)) * 60 if minutes_match else None


def _roi_inside(inner: ROI, outer: ROI) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    return ox0 <= ix0 < ix1 <= ox1 and oy0 <= iy0 < iy1 <= oy1


def _valid_source(observation: NoahTavernObservation) -> bool:
    return bool(
        observation.recognized
        and not observation.stale
        and _HASH_RE.fullmatch(observation.frame_sha256 or "")
    )


def noah_recruit_authorizeable(
    observation: NoahTavernObservation,
    tier: RecruitTier,
) -> bool:
    """Authorize exactly one visible, enabled, zero-cost Daily Free single."""

    if (
        observation.screen_state != NOAHS_TAVERN_SCREEN
        or observation.selected_tier != tier
        or observation.overlay_state not in {"none", "none_observed"}
        or not _valid_source(observation)
    ):
        return False
    try:
        selected = observation.tier(tier)
    except KeyError:
        return False
    return bool(
        selected.recognized
        and selected.attempts_remaining is not None
        and 0 < selected.attempts_remaining <= selected.daily_attempt_maximum
        and selected.free_control_visible
        and selected.free_control_enabled
        and selected.target_identity == NOAHS_TAVERN_FREE_TARGET
        and selected.control_class == NOAHS_TAVERN_FREE_TARGET
        and selected.cost_type == "none"
        and selected.cost_amount == 0
        and selected.quantity == 1
        and not selected.cooldown_active
        and selected.cooldown_duration_seconds in (None, 0)
        and not selected.overlapping_target
        and _roi_inside(selected.target_roi, selected.panel_roi)
        and not observation.claim_visible
    )


def noah_recruit_transaction_spec(observation: NoahTavernObservation, tier: RecruitTier) -> ActionTransactionSpec:
    if not noah_recruit_authorizeable(observation, tier):
        raise ValueError("Noah's Tavern Daily Free preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="NOAHS_TAVERN_DAILY_FREE",
        expected_source_screen=NOAHS_TAVERN_SCREEN,
        subject=f"single free {tier.value}",
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(
            "home_to_noahs_tavern_route",
            "exact_tier_identity",
            "daily_free_control_enabled",
            "no_premium_or_ticket_cost",
            "fresh_native_frame",
        ),
        semantic_postconditions=(
            "hero_recruit_result_screen",
            "exactly_one_tier_attempt_decrement",
            "tier_cooldown_active",
        ),
    )


def noah_result_postcondition_verified(
    before: NoahTavernObservation,
    result: NoahTavernObservation | None,
    after_close: NoahTavernObservation | None,
    tier: RecruitTier,
    *,
    require_daily_progress: bool = True,
    require_attempt_decrement: bool = True,
    cooldown_tolerance_seconds: int = 0,
) -> bool:
    """Require positive result, safe close, exact decrement, and cooldown."""

    if not (_valid_source(before) and result and after_close):
        return False
    if (
        result.screen_state != HERO_RECRUIT_RESULT_SCREEN
        or not result.recognized
        or result.result_tier != tier
        or not result.result_identity.strip()
        or not result.safe_close_visible
        or result.stale
        or result.overlay_state not in {"none", "none_observed"}
    ):
        return False
    if (
        after_close.screen_state != NOAHS_TAVERN_SCREEN
        or after_close.selected_tier != tier
        or not _valid_source(after_close)
        or after_close.overlay_state not in {"none", "none_observed"}
    ):
        return False
    before_tier = before.tier(tier)
    after_tier = after_close.tier(tier)
    parsed = parse_cooldown_seconds(after_tier.cooldown_text)
    daily_progress_valid = (
        after_close.daily_quest_completed == before.daily_quest_completed + 1
        if require_daily_progress
        else True
    )
    attempt_decrement_valid = (
        before_tier.attempts_remaining is not None
        and after_tier.attempts_remaining is not None
        and before_tier.attempts_remaining - after_tier.attempts_remaining == 1
        and after_tier.attempts_remaining >= 0
    )
    if not require_attempt_decrement and after_tier.attempts_remaining is None:
        attempt_decrement_valid = before_tier.attempts_remaining is not None
    return bool(
        attempt_decrement_valid
        and after_tier.cooldown_active
        and parsed is not None
        and after_tier.cooldown_duration_seconds is not None
        and parsed is not None
        and abs(after_tier.cooldown_duration_seconds - parsed) <= cooldown_tolerance_seconds
        and after_tier.next_eligible_timestamp is not None
        and daily_progress_valid
    )


def update_progress(progress: DailyQuestProgress, observation: NoahTavernObservation) -> None:
    """Update aggregate state from a verified postcondition; never mutate Claim state."""

    if not 0 <= observation.daily_quest_completed <= progress.required_recruits:
        raise ValueError("invalid Daily Quest progress")
    progress.recruits_completed = observation.daily_quest_completed
    progress.claim_dormant = True
