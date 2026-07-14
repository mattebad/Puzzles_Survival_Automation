"""Offline model for disabled Daily Alliance Technology donations."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


ALLIANCE_TECH_SCREEN = "ALLIANCE_TECH"
DONATION_TARGET = "donate-control"
DISABLED_POLICY_REASON = "DONATION_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DonationObservation:
    """Semantic Alliance Technology donation evidence with no executable action."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    tech_identity: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    donate_control_visible: bool
    resource_identity: str
    resource_known: bool
    donation_amount: Optional[int]
    resource_balance_before: Optional[int]
    donation_count_before: Optional[int]
    daily_progress_before: int
    resource_balance_after: Optional[int] = None
    donation_count_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    donation_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: DonationObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: DonationObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def donation_authorizeable(observation: DonationObservation) -> bool:
    """Recognize exact tech/resource donation evidence; this does not authorize a donation."""

    return bool(
        observation.screen_state == ALLIANCE_TECH_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "donate_alliance_tech"
        and bool(observation.tech_identity.strip())
        and observation.target_identity == DONATION_TARGET
        and observation.control_class == "DONATE"
        and observation.donate_control_visible
        and _target_inside_panel(observation)
        and bool(observation.resource_identity.strip())
        and observation.resource_known
        and observation.donation_amount is not None
        and observation.donation_amount > 0
        and observation.resource_balance_before is not None
        and observation.resource_balance_before >= observation.donation_amount
        and observation.donation_count_before is not None
        and 0 <= observation.donation_count_before < 10
        and observation.daily_progress_before == observation.donation_count_before
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def donation_postcondition_verified(
    before: DonationObservation,
    after: DonationObservation | None,
) -> bool:
    """Verify offline donation/resource arithmetic without implying permission to spend."""

    if not donation_authorizeable(before) or after is None:
        return False
    return bool(
        donation_authorizeable(after)
        and after.tech_identity == before.tech_identity
        and after.resource_identity == before.resource_identity
        and after.game_day_id == before.game_day_id
        and after.donation_confirmed
        and after.resource_balance_after
        == before.resource_balance_before - before.donation_amount
        and after.donation_count_after == before.donation_count_before + 1
        and after.daily_progress_after == before.daily_progress_before + 1
        and after.successor_state == "DONATION_RECONCILED"
    )


def donation_disabled_dispatch(observation: DonationObservation) -> TaskResult:
    """Always block Alliance Technology donation dispatch under current policy."""

    if not donation_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_DONATION_OBSERVATION",
            verified=True,
            state=ALLIANCE_TECH_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=ALLIANCE_TECH_SCREEN,
        details={"dispatch_count": 0},
    )
