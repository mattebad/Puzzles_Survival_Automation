"""Offline model for disabled generic Daily building upgrades.

Generic building identity and level arithmetic are replayable.  Vehicle Depot is Main-Quest-only
and explicitly rejected.  Current policy blocks all material spend and upgrade dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


BUILDING_SCREEN = "BUILDING"
BUILDING_TARGET = "upgrade-building"
DISABLED_POLICY_REASON = "BUILDING_UPGRADE_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAIN_ONLY_TOKENS = ("vehicle depot", "vehicle_depot")


@dataclass(frozen=True)
class BuildingUpgradeObservation:
    """Semantic generic building evidence with no executable upgrade target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    building_identity: str
    current_level: Optional[int]
    target_level: Optional[int]
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    upgrade_control_visible: bool
    queue_empty: bool
    cost_known: bool
    cost_resource: str
    cost_amount: Optional[int]
    resource_balance: Optional[int]
    daily_progress_before: int
    current_level_after: Optional[int] = None
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


def _target_inside_panel(observation: BuildingUpgradeObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: BuildingUpgradeObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def _is_main_only_building(identity: str) -> bool:
    normalized = str(identity).strip().lower()
    return any(token in normalized for token in _MAIN_ONLY_TOKENS)


def building_upgrade_authorizeable(
    observation: BuildingUpgradeObservation,
) -> bool:
    """Recognize generic building upgrade evidence; this does not authorize an upgrade."""

    return bool(
        observation.screen_state == BUILDING_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "upgrade_building"
        and bool(observation.building_identity.strip())
        and not _is_main_only_building(observation.building_identity)
        and observation.current_level is not None
        and observation.current_level >= 0
        and observation.target_level == observation.current_level + 1
        and observation.target_identity == BUILDING_TARGET
        and observation.control_class == "UPGRADE"
        and observation.upgrade_control_visible
        and observation.queue_empty
        and _target_inside_panel(observation)
        and observation.cost_known
        and bool(observation.cost_resource.strip())
        and observation.cost_amount is not None
        and observation.cost_amount > 0
        and observation.resource_balance is not None
        and observation.resource_balance >= observation.cost_amount
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def building_upgrade_postcondition_verified(
    before: BuildingUpgradeObservation,
    after: BuildingUpgradeObservation | None,
) -> bool:
    """Verify offline level arithmetic without implying permission to spend."""

    if not building_upgrade_authorizeable(before) or after is None:
        return False
    return bool(
        building_upgrade_authorizeable(after)
        and after.building_identity == before.building_identity
        and after.game_day_id == before.game_day_id
        and after.current_level == before.target_level
        and after.current_level_after == after.current_level
        and after.daily_progress_after == 1
        and after.successor_state == "LEVEL_RECONCILED"
    )


def building_upgrade_disabled_dispatch(
    observation: BuildingUpgradeObservation,
) -> TaskResult:
    """Always block generic building upgrade dispatch under current policy."""

    if not building_upgrade_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_BUILDING_UPGRADE_OBSERVATION",
            verified=True,
            state=BUILDING_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=BUILDING_SCREEN,
        details={"dispatch_count": 0},
    )
