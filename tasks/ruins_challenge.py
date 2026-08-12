"""Deterministic Ruins Challenge contract.

The contract models live observations and safe decisions without owning transport.  It is
deliberately separate from the older disabled Daily-Quest replay contract and from every other
gameplay workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


class RuinsChallengeId(str, Enum):
    HERO = "Hero Challenge"
    WEAPON = "Weapon Trial"
    TECH = "Tech Challenge"
    GEAR = "Gear Challenge"
    CORE = "Core Challenge"
    NOVA = "Nova Challenge"
    MODULE = "Module Challenge"
    GLORY = "Glory Challenge"
    BIOENHANCER = "Bioenhancer Challenge"
    ULTIMATE = "Ultimate Challenge"
    CHIP = "Chip Challenge"
    CUBE = "Cube Challenge"


class RuinsAvailability(str, Enum):
    AVAILABLE = "available"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"
    PREMIUM = "premium"
    UNKNOWN = "unknown"


class RuinsControlState(str, Enum):
    VISIBLE_ENABLED = "visible_enabled"
    VISIBLE_DISABLED = "visible_disabled"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class RuinsChestState(str, Enum):
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available_to_claim"
    CLAIMED = "already_claimed"
    UNKNOWN = "unknown"


class RuinsDispatchState(str, Enum):
    NEVER = "never"
    PREPARED = "prepared"
    INPUT_SENT = "input_sent"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


class RuinsResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    AMBIGUOUS = "ambiguous"
    NOT_OBSERVED = "not_observed"


KNOWN_CHALLENGE_IDENTITIES = tuple(item.value for item in RuinsChallengeId)
WEEKDAYS = frozenset({"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
FORBIDDEN_CONTROL_WORDS = frozenset({"exchange", "mall", "buy", "purchase", "upgrade", "ticket"})


def frame_hash(frame: bytes) -> str:
    return hashlib.sha256(frame).hexdigest()


@dataclass(frozen=True)
class RuinsChallengeRow:
    identity: str
    day_label: Optional[str]
    availability: RuinsAvailability
    progress_current: int
    progress_maximum: int
    last_successful_level: Optional[int]
    challenge_control: RuinsControlState
    chest_state: RuinsChestState
    target_roi: Optional[ROI] = None
    hq_restriction: Optional[int] = None
    premium: bool = False
    paid: bool = False
    ticketed: bool = False
    currency_cost: Optional[int] = None
    next_eligible_state: Optional[str] = None
    last_dispatch_state: RuinsDispatchState = RuinsDispatchState.NEVER
    last_postcondition_state: Optional[str] = None
    source_frame_sha256: str = ""
    reset_identity: Optional[str] = None
    recognized: bool = True

    def __post_init__(self) -> None:
        if self.identity not in KNOWN_CHALLENGE_IDENTITIES:
            raise ValueError(f"unknown Ruins challenge identity: {self.identity}")
        if self.progress_current < 0 or self.progress_maximum <= 0:
            raise ValueError("Ruins progress must be non-negative with a positive maximum")
        if self.progress_current > self.progress_maximum:
            raise ValueError("Ruins progress cannot exceed its maximum")
        if self.day_label is not None and self.day_label not in WEEKDAYS:
            raise ValueError("Ruins day label must be a weekday or None")
        if self.target_roi is not None:
            x0, y0, x1, y1 = self.target_roi
            if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
                raise ValueError("Ruins target ROI must be native 800x1280 bounds")


@dataclass(frozen=True)
class RuinsScreenObservation:
    recognized: bool
    screen_identity: str
    title_visible: bool
    points_balance: Optional[int]
    exchange_control: RuinsControlState
    progress_control: RuinsControlState
    total_rank_control: RuinsControlState
    rows: tuple[RuinsChallengeRow, ...]
    overlay_state: str
    source_frame_sha256: str
    reset_identity: Optional[str]
    home_base_recognized: bool = False
    ruins_building_recognized: bool = False
    safe_back_control: RuinsControlState = RuinsControlState.UNKNOWN
    forbidden_controls_seen: tuple[str, ...] = ()
    runtime_profile_id: str = PROFILE_ID

    def row(self, identity: str) -> Optional[RuinsChallengeRow]:
        return next((item for item in self.rows if item.identity == identity), None)


@dataclass(frozen=True)
class RuinsDetailObservation:
    identity: str
    recognized: bool
    floor_current: int
    floor_maximum: int
    attack_control: RuinsControlState
    dispatch_control: RuinsControlState = RuinsControlState.HIDDEN
    npc_troops_provided: bool = False
    npc_troops_current: Optional[int] = None
    npc_troops_maximum: Optional[int] = None
    skip_battle_enabled: bool = False
    resource_cost: Optional[int] = None
    premium: bool = False
    paid: bool = False
    ticketed: bool = False
    overlay_state: str = "none"
    source_frame_sha256: str = ""
    reset_identity: Optional[str] = None


@dataclass(frozen=True)
class RuinsResultObservation:
    identity: str
    result: RuinsResult
    progress_after: Optional[int]
    maximum_after: Optional[int]
    level_after: Optional[int]
    source_frame_sha256: str
    reset_identity: Optional[str]
    explicit_success_text: bool = False
    explicit_failure_text: bool = False
    tap_to_continue_visible: bool = False


@dataclass
class RuinsDailyState:
    required_challenges: int = 1
    challenge_initiations_completed: int = 0
    successful_challenges_completed: int = 0
    ready_to_claim: bool = False
    claim_dormant: bool = True

    @property
    def initiation_complete(self) -> bool:
        return self.challenge_initiations_completed >= self.required_challenges

    @property
    def successful_progress_complete(self) -> bool:
        return self.successful_challenges_completed >= self.required_challenges


@dataclass(frozen=True)
class RuinsChestClaim:
    identity: str
    day_reset_identity: str
    action_key: str
    before_frame_hash: str
    postcondition_state: str
    claimed: bool


def _native_source(source_frame_sha256: str, reset_identity: Optional[str]) -> bool:
    return (
        len(source_frame_sha256) == 64
        and all(char in "0123456789abcdef" for char in source_frame_sha256)
        and bool(reset_identity)
    )


def current_day_allowed(row: RuinsChallengeRow, current_day: str) -> bool:
    """Filter rows by the live reset-day label; timer-bound active rows use None."""

    if current_day not in WEEKDAYS:
        return False
    return row.day_label is None or row.day_label == current_day


def challenge_action_authorized(
    screen: RuinsScreenObservation,
    row: RuinsChallengeRow,
    *,
    current_day: str,
    action_key: str,
    seen_action_keys: set[str] | None = None,
    seen_frame_hashes: set[str] | None = None,
) -> bool:
    """Return true only for a zero-cost, current-day, native, enabled challenge row."""

    seen_action_keys = seen_action_keys or set()
    seen_frame_hashes = seen_frame_hashes or set()
    if not (
        screen.recognized
        and screen.screen_identity == "RUINS_CHALLENGE"
        and screen.title_visible
        and screen.points_balance is not None
        and row.identity in KNOWN_CHALLENGE_IDENTITIES
        and row.availability == RuinsAvailability.AVAILABLE
        and current_day_allowed(row, current_day)
        and row.challenge_control == RuinsControlState.VISIBLE_ENABLED
        and not row.premium
        and not row.paid
        and not row.ticketed
        and row.currency_cost in (None, 0)
        and screen.overlay_state == "none"
        and screen.reset_identity == row.reset_identity
        and _native_source(screen.source_frame_sha256, screen.reset_identity)
        and _native_source(row.source_frame_sha256, row.reset_identity)
        and action_key
        and action_key not in seen_action_keys
        and row.source_frame_sha256 not in seen_frame_hashes
    ):
        return False
    return not (set(screen.forbidden_controls_seen) & FORBIDDEN_CONTROL_WORDS)


def detail_attack_authorized(detail: RuinsDetailObservation) -> bool:
    return bool(
        detail.recognized
        and detail.identity in KNOWN_CHALLENGE_IDENTITIES
        and detail.floor_current >= 0
        and detail.floor_maximum > 0
        and detail.attack_control == RuinsControlState.VISIBLE_ENABLED
        and detail.resource_cost in (None, 0)
        and not detail.premium
        and not detail.paid
        and not detail.ticketed
        and detail.overlay_state == "none"
    )


def dispatch_authorized(detail: RuinsDetailObservation) -> bool:
    return bool(
        detail_attack_authorized(detail)
        and detail.dispatch_control == RuinsControlState.VISIBLE_ENABLED
        and detail.npc_troops_provided
        and detail.npc_troops_current is not None
        and detail.npc_troops_maximum is not None
        and detail.npc_troops_current == detail.npc_troops_maximum
        and detail.skip_battle_enabled
    )


def result_verified(before: RuinsChallengeRow, result: RuinsResultObservation) -> bool:
    if result.identity != before.identity or result.reset_identity != before.reset_identity:
        return False
    if result.result == RuinsResult.SUCCESS:
        return bool(
            result.explicit_success_text
            and result.progress_after is not None
            and result.progress_after > before.progress_current
            and result.maximum_after == before.progress_maximum
            and result.level_after is not None
            and result.source_frame_sha256
        )
    if result.result == RuinsResult.FAILURE:
        return bool(result.explicit_failure_text and result.tap_to_continue_visible)
    return False


def chest_claim_authorized(
    screen: RuinsScreenObservation,
    row: RuinsChallengeRow,
    *,
    action_key: str,
    seen_action_keys: set[str] | None = None,
) -> bool:
    seen_action_keys = seen_action_keys or set()
    return bool(
        screen.recognized
        and screen.screen_identity == "RUINS_CHALLENGE"
        and screen.overlay_state == "none"
        and row.chest_state == RuinsChestState.AVAILABLE
        and row.identity in KNOWN_CHALLENGE_IDENTITIES
        and row.source_frame_sha256 == screen.source_frame_sha256
        and action_key not in seen_action_keys
        and action_key
    )


def chest_claim_postcondition_verified(before: RuinsChallengeRow, after: RuinsChallengeRow) -> bool:
    return bool(
        before.chest_state == RuinsChestState.AVAILABLE
        and after.identity == before.identity
        and after.chest_state == RuinsChestState.CLAIMED
        and after.reset_identity == before.reset_identity
        and after.source_frame_sha256
        and after.source_frame_sha256 != before.source_frame_sha256
    )


def blocked_ruins_result(reason: str, *, state: str = "RUINS_CHALLENGE") -> TaskResult:
    return TaskResult(TaskOutcome.BLOCKED, reason, verified=True, state=state)
