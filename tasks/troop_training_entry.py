"""Platform-neutral Home-atlas entry contracts for troop-training facilities.

This module selects semantic atlas identities and delegates camera movement to
the shared direct-pan planner.  Platform adapters inject safe regions and
gesture calibration; no BlueStacks or Bliss geometry belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .home_atlas import BuildingBinding, HomeAtlas, LocalizationResult
from .home_atlas_planner import (
    DirectPanNavigator,
    DirectPanPlan,
    GestureCalibration,
    PanProgress,
    SafeInteractionRegion,
)
from .troop_training import FACILITY_BY_TYPE, TROOP_TYPES, RadialMenuObservation, TroopTrainingConfig


ATLAS_BUILDING_BY_TROOP_TYPE = {
    "fighter": "home.building.fighter_camp",
    "shooter": "home.building.shooter_camp",
    "rider": "home.building.rider_camp",
    "vehicle": "home.building.vehicle_depot",
}


@dataclass(frozen=True)
class TroopFacilityEntryTarget:
    troop_type: str
    building_id: str
    facility_identity: str


def first_enabled_entry_target(config: TroopTrainingConfig) -> TroopFacilityEntryTarget | None:
    """Return the first enabled training type in the route's stable type order."""

    config.validate()
    for troop_type in TROOP_TYPES:
        item = config.for_type(troop_type)
        if item.enabled and item.training_policy != "disabled":
            return TroopFacilityEntryTarget(
                troop_type,
                ATLAS_BUILDING_BY_TROOP_TYPE[troop_type],
                FACILITY_BY_TYPE[troop_type],
            )
    return None


class TroopTrainingAtlasEntryPlanner:
    """Bind one selected troop facility through the shared direct-pan planner."""

    def __init__(
        self,
        atlas: HomeAtlas,
        target: TroopFacilityEntryTarget,
        safe_region: SafeInteractionRegion,
        calibration: GestureCalibration,
        *,
        maximum_pans: int = 4,
    ) -> None:
        if target.troop_type not in TROOP_TYPES:
            raise ValueError("unknown troop facility entry target")
        if ATLAS_BUILDING_BY_TROOP_TYPE[target.troop_type] != target.building_id:
            raise ValueError("troop type and semantic building ID differ")
        if FACILITY_BY_TYPE[target.troop_type] != target.facility_identity:
            raise ValueError("troop type and facility identity differ")
        atlas.lookup_building(target.building_id)
        self.target = target
        self.navigator = DirectPanNavigator(
            atlas,
            target.building_id,
            safe_region,
            calibration,
            maximum_pans=maximum_pans,
        )

    @property
    def pan_count(self) -> int:
        return self.navigator.pan_count

    def plan(
        self,
        localization: LocalizationResult,
        binding: BuildingBinding | None = None,
    ) -> DirectPanPlan:
        return self.navigator.plan(localization, binding)

    def record_progress(
        self,
        before: LocalizationResult,
        after: LocalizationResult,
    ) -> PanProgress:
        return self.navigator.record_progress(before, after)

    def radial_is_exact(self, observation: RadialMenuObservation) -> bool:
        """Require the expected current facility radial and its fresh Train target."""

        return bool(
            observation.recognized
            and observation.facility_identity == self.target.facility_identity
            and observation.train_target is not None
            and observation.overlay_state == "none"
        )
