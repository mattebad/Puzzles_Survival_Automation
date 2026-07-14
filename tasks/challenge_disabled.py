"""Offline model for disabled Daily Ruins Challenge entry."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


CHALLENGE_SCREEN = "CHALLENGE"
RUINS_CHALLENGE = "RUINS_CHALLENGE"
CHALLENGE_TARGET = "challenge-entry"
DISABLED_POLICY_REASON = "CHALLENGE_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ChallengeObservation:
    """Semantic Ruins Challenge evidence with no executable entry target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    challenge_identity: str
    challenge_available: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    entry_control_visible: bool
    entry_cost_known: bool
    entry_cost_ap: Optional[int]
    ap_balance_before: Optional[int]
    premium_entry: bool
    daily_progress_before: int
    challenge_result_after: str = ""
    daily_progress_after: Optional[int] = None
    entry_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: ChallengeObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: ChallengeObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def challenge_authorizeable(observation: ChallengeObservation) -> bool:
    """Recognize exact Ruins Challenge entry evidence; this does not authorize entry."""

    return bool(
        observation.screen_state == CHALLENGE_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "ruins_challenge"
        and observation.challenge_identity == RUINS_CHALLENGE
        and observation.challenge_available
        and observation.target_identity == CHALLENGE_TARGET
        and observation.control_class == "ENTER"
        and observation.entry_control_visible
        and _target_inside_panel(observation)
        and observation.entry_cost_known
        and observation.entry_cost_ap is not None
        and observation.entry_cost_ap > 0
        and observation.ap_balance_before is not None
        and observation.ap_balance_before >= observation.entry_cost_ap
        and not observation.premium_entry
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def challenge_postcondition_verified(
    before: ChallengeObservation,
    after: ChallengeObservation | None,
) -> bool:
    """Verify offline challenge-entry/result replay without implying permission to enter."""

    if not challenge_authorizeable(before) or after is None:
        return False
    return bool(
        challenge_authorizeable(after)
        and after.challenge_identity == before.challenge_identity
        and after.game_day_id == before.game_day_id
        and after.entry_confirmed
        and after.challenge_result_after in {"ENTERED", "RESULT_RECONCILED"}
        and after.daily_progress_after == 1
        and after.successor_state == "CHALLENGE_RECONCILED"
    )


def challenge_disabled_dispatch(observation: ChallengeObservation) -> TaskResult:
    """Always block Ruins Challenge entry under current policy."""

    if not challenge_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_CHALLENGE_OBSERVATION",
            verified=True,
            state=CHALLENGE_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=CHALLENGE_SCREEN,
        details={"dispatch_count": 0},
    )
