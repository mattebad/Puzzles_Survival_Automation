"""Offline identity model for disabled Daily Hero Duel participation.

The contract recognizes event/Join/progress observations and proves successor arithmetic in replay
fixtures.  PvP entry, lineup changes, resource use, registration, and scheduler eligibility remain
blocked by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


HERO_DUEL_SCREEN = "HERO_DUEL"
HERO_DUEL_TARGET = "hero-duel-join"
DISABLED_POLICY_REASON = "HERO_DUEL_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HeroDuelObservation:
    """Semantic event and participation evidence with no executable PvP action."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    event_identity: str
    event_active: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    join_control_visible: bool
    attempts_remaining: Optional[int]
    daily_progress_before: int
    participation_confirmed: bool = False
    daily_progress_after: Optional[int] = None
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: HeroDuelObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: HeroDuelObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def hero_duel_authorizeable(observation: HeroDuelObservation) -> bool:
    """Recognize exact Hero Duel entry evidence; this does not authorize PvP."""

    return bool(
        observation.screen_state == HERO_DUEL_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "join_hero_duel"
        and bool(observation.event_identity.strip())
        and observation.event_active
        and observation.target_identity == HERO_DUEL_TARGET
        and observation.control_class == "JOIN"
        and observation.join_control_visible
        and _target_inside_panel(observation)
        and observation.attempts_remaining is not None
        and observation.attempts_remaining > 0
        and 0 <= observation.daily_progress_before < 3
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def hero_duel_postcondition_verified(
    before: HeroDuelObservation,
    after: HeroDuelObservation | None,
) -> bool:
    """Verify offline participation arithmetic without implying PvP entry permission."""

    if not hero_duel_authorizeable(before) or after is None:
        return False
    return bool(
        hero_duel_authorizeable(after)
        and after.event_identity == before.event_identity
        and after.game_day_id == before.game_day_id
        and after.successor_state == "PARTICIPATION_RECONCILED"
        and after.participation_confirmed
        and after.daily_progress_after == before.daily_progress_before + 1
        and after.daily_progress_after <= 3
    )


def hero_duel_disabled_dispatch(observation: HeroDuelObservation) -> TaskResult:
    """Always block Hero Duel entry under PvP policy."""

    if not hero_duel_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_HERO_DUEL_OBSERVATION",
            verified=True,
            state=HERO_DUEL_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=HERO_DUEL_SCREEN,
        details={"dispatch_count": 0},
    )
