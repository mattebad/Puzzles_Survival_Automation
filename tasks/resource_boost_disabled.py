"""Offline model for disabled Daily resource-building output boosts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


RESOURCE_BUILDING_SCREEN = "RESOURCE_BUILDING"
BOOST_TARGET = "resource-boost-control"
DISABLED_POLICY_REASON = "RESOURCE_BOOST_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_RESOURCE_TYPES = {"WOOD", "STEEL", "GAS", "FOOD"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResourceBoostObservation:
    """Semantic resource-building boost evidence with no executable action."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    building_identity: str
    resource_identity: str
    resource_type: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    boost_control_visible: bool
    boost_duration_minutes: Optional[int]
    cost_known: bool
    cost_resource: str
    cost_amount: Optional[int]
    resource_balance_before: Optional[int]
    boost_active_before: bool
    daily_progress_before: int
    boost_active_after: Optional[bool] = None
    boost_duration_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    boost_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: ResourceBoostObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: ResourceBoostObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def resource_boost_authorizeable(observation: ResourceBoostObservation) -> bool:
    """Recognize exact building/resource boost evidence; this does not authorize a boost."""

    return bool(
        observation.screen_state == RESOURCE_BUILDING_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "boost_resource_building_output"
        and bool(observation.building_identity.strip())
        and bool(observation.resource_identity.strip())
        and observation.resource_type in _RESOURCE_TYPES
        and observation.target_identity == BOOST_TARGET
        and observation.control_class == "BOOST"
        and observation.boost_control_visible
        and _target_inside_panel(observation)
        and observation.boost_duration_minutes is not None
        and observation.boost_duration_minutes > 0
        and observation.cost_known
        and bool(observation.cost_resource.strip())
        and observation.cost_amount is not None
        and observation.cost_amount > 0
        and observation.resource_balance_before is not None
        and observation.resource_balance_before >= observation.cost_amount
        and not observation.boost_active_before
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def resource_boost_postcondition_verified(
    before: ResourceBoostObservation,
    after: ResourceBoostObservation | None,
) -> bool:
    """Verify offline boost-state arithmetic without implying permission to spend."""

    if not resource_boost_authorizeable(before) or after is None:
        return False
    return bool(
        resource_boost_authorizeable(after)
        and after.building_identity == before.building_identity
        and after.resource_identity == before.resource_identity
        and after.resource_type == before.resource_type
        and after.game_day_id == before.game_day_id
        and after.boost_confirmed
        and after.boost_active_after
        and after.boost_duration_after == before.boost_duration_minutes
        and after.daily_progress_after == 1
        and after.successor_state == "BOOST_RECONCILED"
    )


def resource_boost_disabled_dispatch(observation: ResourceBoostObservation) -> TaskResult:
    """Always block resource-building boost dispatch under current policy."""

    if not resource_boost_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_RESOURCE_BOOST_OBSERVATION",
            verified=True,
            state=RESOURCE_BUILDING_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=RESOURCE_BUILDING_SCREEN,
        details={"dispatch_count": 0},
    )
