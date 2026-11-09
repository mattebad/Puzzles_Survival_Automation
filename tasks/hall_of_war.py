"""Pure Hall of War → Zombie Zero action semantics; never owns transport or state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re

from automation_service.registry import (
    HALL_OF_WAR_FLOW_ID as FLOW_ID,
    HALL_OF_WAR_PRODUCT_ID as PRODUCT_ID,
    HALL_OF_WAR_PRODUCT_REVISION as PRODUCT_REVISION,
)
DISPATCH_ACTION = "HALL_OF_WAR_ZOMBIE_ZERO_DISPATCH"
DISPATCH_SOURCE = "HALL_OF_WAR_ZOMBIE_ZERO_DISPATCH"
DISPATCH_TARGET = "hall-of-war:zombie-zero:dispatch"
DISPATCH_CONSEQUENCE = "hall_of_war_zombie_zero_attempt"
DISPATCH_POSTCONDITION = "HALL_OF_WAR_ZOMBIE_ZERO_HISTORY_HIGH_RESULT"
REWARD_ACTION = "HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_CLAIM"
REWARD_SOURCE = "HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_READY"
REWARD_TARGET = "hall-of-war:zombie-zero:daily-reward-row"
REWARD_CONSEQUENCE = "hall_of_war_daily_reward_claim"
REWARD_POSTCONDITION = "HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_CLAIMED_CHECKMARKS"


class AttemptState(str, Enum):
    READY = "ready"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RewardState(str, Enum):
    READY = "ready"
    CLAIMED = "claimed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Action(str, Enum):
    DISPATCH = "dispatch"
    CLAIM_REWARD = "claim_reward"
    NO_WORK = "no_work"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ChallengeObservation:
    """Current challenge state joined to exact page and Dispatch-screen evidence."""

    page_identity: str
    page_exact: bool
    attempt: AttemptState
    saved_military_verified: bool
    troop_set_one_selected: bool
    troop_set_one_applied: bool
    five_heroes_populated: bool
    current_troops: int | None
    troop_capacity: int | None
    today_highest_damage: int | None
    attempt_source_frame_sha256: str
    dispatch_page_identity: str
    dispatch_page_exact: bool
    attempt_ordinal: int
    source_frame_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, AttemptState):
            raise TypeError("attempt must be a typed Hall of War observation")
        for name in (
            "page_exact", "saved_military_verified", "troop_set_one_selected",
            "troop_set_one_applied", "five_heroes_populated",
            "dispatch_page_exact",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean observation")
        if self.page_identity != "ZOMBIE_ZERO" or self.page_exact is not True:
            raise ValueError("challenge facts require the exact Zombie Zero page")
        if self.dispatch_page_identity != "ZOMBIE_ZERO_DISPATCH" or self.dispatch_page_exact is not True:
            raise ValueError("formation facts require the exact Zombie Zero Dispatch page")
        if type(self.attempt_ordinal) is not int or self.attempt_ordinal != 1:
            raise ValueError("only the first route dispatch attempt is permitted")
        for name in ("attempt_source_frame_sha256", "source_frame_sha256"):
            digest = getattr(self, name)
            if not isinstance(digest, str) or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError(f"{name} must be a current source frame digest")
        for name in ("current_troops", "troop_capacity", "today_highest_damage"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or unknown")


@dataclass(frozen=True)
class RewardObservation:
    """The Zombie Zero daily reward row, not a Daily objectives surface."""

    page_identity: str
    page_exact: bool
    reward: RewardState
    glowing: bool
    checkmarks_verified: bool
    source_frame_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.reward, RewardState):
            raise TypeError("reward must be a typed Hall of War observation")
        if self.page_identity != "ZOMBIE_ZERO" or self.page_exact is not True:
            raise ValueError("reward facts require the exact Zombie Zero page")
        if len(self.source_frame_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_frame_sha256
        ):
            raise ValueError("current source frame digest is required")
        if self.reward is RewardState.CLAIMED and not self.checkmarks_verified:
            raise ValueError("claimed reward requires explicit row/checkmark evidence")


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


def action_key(*, category: str, runtime_scope: str, account_id: str, server_id: str, reset_id: str) -> str:
    """Bind category, ordinal, account and exact current reset to one canonical key."""

    if category not in {"dispatch", "reward"}:
        raise ValueError("Hall of War action category must be dispatch or reward")
    identity = {
        "runtime_scope": runtime_scope,
        "account_id": account_id,
        "server_id": server_id,
        "reset_id": reset_id,
        "flow_id": FLOW_ID,
        "category": category,
        "action_ordinal": 1,
    }
    for name in ("runtime_scope", "account_id", "server_id", "reset_id", "flow_id", "category"):
        value = identity[name]
        if type(value) is not str or not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError(f"{name} must be a non-empty normalized identity")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ordinal_name = "attempt" if category == "dispatch" else "claim"
    digest = hashlib.sha256(encoded).hexdigest()
    return f"hall-of-war:{category}:daily:{reset_id}:{ordinal_name}-1:{digest}"

def _action_reset(value: str) -> str:
    if type(value) is not str or not value.startswith("game-day-") or value != value.strip() or any(c.isspace() for c in value):
        raise ValueError("Hall of War action requires its exact scheduler game-day reset id")
    return value


def _current_action_key(value: str, *, category: str, reset_id: str, ordinal: str) -> None:
    prefix = f"hall-of-war:{category}:daily:{reset_id}:{ordinal}-1:"
    if type(value) is not str or not value.startswith(prefix) or re.fullmatch(r"[0-9a-f]{64}", value[len(prefix):]) is None:
        raise ValueError("Hall of War action key does not bind the current reset, ordinal and digest")


def _source_digest(value: str, name: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def dispatch_policy_preconditions(
    *,
    reset_id: str,
    action_key: str,
    source_frame_sha256: str,
    formation_roi_sha256: str,
    dispatch_roi_sha256: str,
) -> tuple[str, ...]:
    """Build exact current-frame dispatch proof tokens after every route gate passed."""
    reset_id = _action_reset(reset_id)
    _current_action_key(action_key, category="dispatch", reset_id=reset_id, ordinal="attempt")
    source = _source_digest(source_frame_sha256, "dispatch source frame")
    formation = _source_digest(formation_roi_sha256, "saved formation ROI")
    dispatch = _source_digest(dispatch_roi_sha256, "dispatch control ROI")
    return (
        f"hall_of_war_product={PRODUCT_ID}",
        f"hall_of_war_product_revision={PRODUCT_REVISION}",
        f"hall_of_war_reset={reset_id}",
        "current_reset_id_bound_to_game_day_id",
        "challenge_action_ordinal=1",
        "challenge_action_key_binds_attempt_ordinal_one_for_current_reset",
        "exact_zombie_zero_page_and_current_reset_action_key_checked",
        "challenge_attempt_ready_and_not_busy_or_cooling_down",
        "saved_military_preset_verified",
        "troop_set_1_saved_identity_selected_not_edit_or_quick_select",
        "troop_set_1_application_toast_verified",
        "five_hero_slots_populated",
        "current_troop_count_positive",
        f"dispatch_source_frame={source}",
        f"hall_of_war_saved_formation={formation}",
        f"hall_of_war_dispatch_control={dispatch}",
        "fixed_zero_resource_zero_loss_zombie_zero_mechanic",
        "one_dispatch_transport_remaining",
    )


def reward_policy_preconditions(*, reset_id: str, action_key: str) -> tuple[str, ...]:
    """Build the independent same-reset glowing-row claim proof tokens."""
    reset_id = _action_reset(reset_id)
    _current_action_key(action_key, category="reward", reset_id=reset_id, ordinal="claim")
    return (
        f"hall_of_war_product={PRODUCT_ID}",
        f"hall_of_war_product_revision={PRODUCT_REVISION}",
        f"hall_of_war_reset={reset_id}",
        "current_reset_id_bound_to_game_day_id",
        "daily_reward_claim_ordinal=1",
        "reward_action_key_independent_from_challenge_key_and_binds_current_reset",
        "same_reset_zombie_zero_participation_proven_by_confirmed_dispatch_or_exact_positive_today_highest_damage",
        "exact_zombie_zero_daily_reward_row_identity",
        "current_reward_row_explicitly_glowing_and_enabled",
        "claimed_label_and_green_checkmarks_absent",
        "one_reward_claim_transport_remaining",
    )


def plan_dispatch(observation: ChallengeObservation, *, saved_military_verified: bool) -> Decision:
    """Authorize the fixed free mechanic using the observed saved populated formation."""

    if observation.page_identity != "ZOMBIE_ZERO" or observation.page_exact is not True:
        return Decision(Action.BLOCKED, "exact_zombie_zero_page_not_recognized")
    if (observation.dispatch_page_identity != "ZOMBIE_ZERO_DISPATCH"
            or observation.dispatch_page_exact is not True):
        return Decision(Action.BLOCKED, "exact_zombie_zero_dispatch_page_not_recognized")
    if observation.attempt_ordinal != 1:
        return Decision(Action.BLOCKED, "challenge_attempt_ordinal_not_one")
    if not saved_military_verified or not observation.saved_military_verified:
        return Decision(Action.BLOCKED, "saved_military_preset_not_verified")
    if type(observation.today_highest_damage) is int and observation.today_highest_damage > 0:
        return Decision(Action.NO_WORK, "same_reset_participation_already_observed")
    if observation.attempt is AttemptState.BUSY:
        return Decision(Action.NO_WORK, "challenge_attempt_busy_or_cooling_down")
    if observation.attempt is AttemptState.UNAVAILABLE:
        return Decision(Action.NO_WORK, "challenge_unavailable")
    if observation.attempt is not AttemptState.READY:
        return Decision(Action.BLOCKED, "challenge_attempt_state_unknown")
    if not observation.troop_set_one_selected or not observation.troop_set_one_applied:
        return Decision(Action.BLOCKED, "saved_troop_set_one_not_applied")
    if not observation.five_heroes_populated:
        return Decision(Action.BLOCKED, "five_hero_formation_not_verified")
    if type(observation.current_troops) is not int or observation.current_troops <= 0:
        return Decision(Action.BLOCKED, "current_troops_empty_or_unknown")
    return Decision(Action.DISPATCH, "exact_current_dispatch_preconditions_verified")


def plan_reward(observation: RewardObservation, *, same_reset_participation_proven: bool) -> Decision:
    """Claim one glowing Zombie Zero reward row only after same-reset participation."""

    if observation.page_identity != "ZOMBIE_ZERO" or observation.page_exact is not True:
        return Decision(Action.BLOCKED, "exact_zombie_zero_reward_page_not_recognized")
    if observation.reward is RewardState.CLAIMED:
        return Decision(Action.NO_WORK, "daily_reward_already_claimed")
    if observation.reward is RewardState.UNAVAILABLE:
        return Decision(Action.NO_WORK, "daily_reward_unavailable")
    if observation.reward is not RewardState.READY:
        return Decision(Action.BLOCKED, "daily_reward_state_unknown")
    if not observation.glowing:
        return Decision(Action.BLOCKED, "daily_reward_ready_glow_not_verified")
    if not same_reset_participation_proven:
        return Decision(Action.BLOCKED, "same_reset_zombie_zero_participation_not_proven")
    return Decision(Action.CLAIM_REWARD, "exact_glowing_daily_reward_row_verified")


def aggregate_action_count(
    *,
    dispatch_transport_calls: int,
    reward_claim_transport_calls: int,
    talent_switch_transport_calls: int = 0,
) -> int:
    """Count every consequential Hall of War transport, including a preset switch."""

    values = (dispatch_transport_calls, reward_claim_transport_calls, talent_switch_transport_calls)
    if any(type(value) is not int or value not in (0, 1) for value in values):
        raise ValueError("Hall of War consequential transport counts must each be zero or one")
    return sum(values)
