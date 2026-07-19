"""Platform-neutral minimal-pan planning for semantic Home/Base facilities.

The planner consumes a fresh localization plus adapter-supplied safe-region and
gesture contracts.  It never captures frames, dispatches input, or treats a
projected coordinate as semantic success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from .home_atlas import (
    AmbiguityState,
    Box,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    Matrix3,
    Point,
    SemanticBuilding,
    ZoomIdentity,
    point_in_coverage,
    polygon_bounds,
)


class PlanDisposition(str, Enum):
    ALREADY_SAFE = "already_safe"
    PAN = "pan"
    BIND = "bind"
    COMPLETE = "complete"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SafeInteractionRegion:
    region_id: str
    screen_box: Box
    placement_anchor: tuple[int, int]
    fixed_hud_masks: tuple[Box, ...] = ()

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.screen_box
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError("safe interaction region is invalid")
        if not (x0 <= self.placement_anchor[0] <= x1 and y0 <= self.placement_anchor[1] <= y1):
            raise ValueError("placement anchor must be inside the safe region")


@dataclass(frozen=True)
class GestureCalibration:
    platform: str
    profile_id: str
    drag_origin: tuple[int, int]
    drag_bounds: Box
    camera_px_per_drag_x: float
    camera_px_per_drag_y: float
    minimum_drag_px: float
    maximum_drag_x: float
    maximum_drag_y: float
    minimum_progress_px: float = 8.0
    wrong_direction_tolerance_px: float = 4.0

    def __post_init__(self) -> None:
        if self.camera_px_per_drag_x <= 0 or self.camera_px_per_drag_y <= 0:
            raise ValueError("gesture conversion is uncalibrated")
        if self.minimum_drag_px <= 0 or self.maximum_drag_x < self.minimum_drag_px or self.maximum_drag_y < self.minimum_drag_px:
            raise ValueError("gesture length bounds are invalid")


@dataclass(frozen=True)
class BuildingViewportPlan:
    disposition: PlanDisposition
    reason: str
    building_id: str
    current_camera_origin: Point | None
    desired_camera_origin: Point | None
    unclamped_camera_origin: Point | None
    target_screen_anchor: Point | None
    residual_atlas: Point
    clamped_axes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DirectPanPlan:
    disposition: PlanDisposition
    reason: str
    viewport: BuildingViewportPlan
    requested_camera_displacement: Point = (0.0, 0.0)
    predicted_camera_displacement: Point = (0.0, 0.0)
    drag_start: tuple[int, int] | None = None
    drag_end: tuple[int, int] | None = None
    predicted_remaining_displacement: Point = (0.0, 0.0)


@dataclass(frozen=True)
class PanProgress:
    accepted: bool
    reason: str
    measured_camera_displacement: Point
    requested_camera_displacement: Point
    remaining_displacement: Point
    progress_px: float


@dataclass(frozen=True)
class NavigationResult:
    status: str
    reason: str
    building_id: str
    pan_count: int
    localization: LocalizationResult | None
    binding: BuildingBinding | None
    last_plan: DirectPanPlan | None


def _apply(matrix: Matrix3, point: Point) -> Point:
    x, y = point
    w = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(w) < 1e-9:
        raise ValueError("singular screen-to-atlas transform")
    return (
        (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / w,
        (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / w,
    )


def _inverse_affine(matrix: Matrix3, point: Point) -> Point:
    a, b, tx = matrix[0]
    c, d, ty = matrix[1]
    det = a * d - b * c
    if abs(det) < 1e-9:
        raise ValueError("singular screen-to-atlas transform")
    x, y = point[0] - tx, point[1] - ty
    return ((d * x - b * y) / det, (-c * x + a * y) / det)


def camera_origin(localization: LocalizationResult) -> Point:
    if localization.screen_to_atlas is None:
        raise ValueError("localization has no screen-to-atlas transform")
    return _apply(localization.screen_to_atlas, (0.0, 0.0))


def _localization_rejection(atlas: HomeAtlas, localization: LocalizationResult) -> str | None:
    if not localization.recognized or localization.screen_to_atlas is None:
        return f"localization_failed:{localization.ambiguity_state.value}"
    if localization.stale or localization.ambiguity_state is AmbiguityState.STALE_FRAME:
        return "stale_frame"
    if localization.overlay or localization.zoom_identity is ZoomIdentity.OVERLAY:
        return "overlay"
    if localization.platform != atlas.profile.platform or localization.profile_id != atlas.profile.profile_id:
        return "wrong_profile"
    if localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        return "canonical_zoom_required"
    if localization.confidence <= 0 or not localization.supporting_landmarks or localization.residual_px is None:
        return "insufficient_landmark_support"
    return None


def _building_inside_safe_region(localization: LocalizationResult, building: SemanticBuilding, safe: SafeInteractionRegion) -> bool:
    assert localization.screen_to_atlas is not None
    x0, y0, x1, y1 = safe.screen_box
    return all(x0 <= sx <= x1 and y0 <= sy <= y1 for sx, sy in (_inverse_affine(localization.screen_to_atlas, p) for p in building.polygon))


def plan_building_viewport(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
) -> BuildingViewportPlan:
    """Choose the nearest reachable camera origin that safely places a building."""

    building = atlas.lookup_building(building_id)
    rejected = _localization_rejection(atlas, localization)
    if rejected:
        return BuildingViewportPlan(PlanDisposition.REJECTED, rejected, building_id, None, None, None, None, (0.0, 0.0))
    current = camera_origin(localization)
    if not building.interaction_eligible:
        return BuildingViewportPlan(PlanDisposition.REJECTED, "non_actionable_building", building_id, current, None, None, None, (0.0, 0.0))
    platform_key = "bluestacks" if "bluestacks" in localization.platform.lower() else localization.platform.lower()
    policy = building.platform_binding_policy.get(platform_key, {})
    allow_subregion = isinstance(policy, dict) and bool(policy.get("allow_safe_subregion_at_camera_edge"))
    fully_covered = all(point_in_coverage(point, atlas.coverage_polygons) for point in building.polygon)
    if not fully_covered and not (allow_subregion and point_in_coverage(building.navigation_anchor, atlas.coverage_polygons)):
        return BuildingViewportPlan(PlanDisposition.REJECTED, "target_outside_verified_coverage", building_id, current, None, None, None, (0.0, 0.0))
    if _building_inside_safe_region(localization, building, safe_region):
        anchor = _inverse_affine(localization.screen_to_atlas, building.navigation_anchor)
        return BuildingViewportPlan(PlanDisposition.ALREADY_SAFE, "target_already_safely_visible", building_id, current, current, current, anchor, (0.0, 0.0))
    if atlas.camera_origin_bounds is None:
        return BuildingViewportPlan(PlanDisposition.REJECTED, "camera_origin_bounds_unverified", building_id, current, None, None, None, (0.0, 0.0))

    ax, ay = building.navigation_anchor
    sx, sy = safe_region.placement_anchor
    unclamped = (ax - sx, ay - sy)
    min_x, min_y, max_x, max_y = atlas.camera_origin_bounds
    desired = (max(min_x, min(max_x, unclamped[0])), max(min_y, min(max_y, unclamped[1])))
    clamped = tuple(axis for axis, before, after in (("x", unclamped[0], desired[0]), ("y", unclamped[1], desired[1])) if abs(before - after) > 1e-6)
    target_screen = (ax - desired[0], ay - desired[1])
    safe_x0, safe_y0, safe_x1, safe_y1 = safe_region.screen_box
    if not (safe_x0 <= target_screen[0] <= safe_x1 and safe_y0 <= target_screen[1] <= safe_y1):
        return BuildingViewportPlan(PlanDisposition.REJECTED, "map_edge_clamp_before_target", building_id, current, desired, unclamped, target_screen, (desired[0] - current[0], desired[1] - current[1]), clamped)
    # Reject a clamped viewport unless the whole polygon is predicted to fit.
    bx0, by0, bx1, by1 = polygon_bounds(building.polygon)
    fully_fits = safe_x0 <= bx0 - desired[0] and bx1 - desired[0] <= safe_x1 and safe_y0 <= by0 - desired[1] and by1 - desired[1] <= safe_y1
    if not fully_fits:
        minimum = policy.get("minimum_safe_subregion", (55, 55)) if isinstance(policy, dict) else (55, 55)
        visible_width = min(bx1 - desired[0], safe_x1) - max(bx0 - desired[0], safe_x0)
        visible_height = min(by1 - desired[1], safe_y1) - max(by0 - desired[1], safe_y0)
        if not allow_subregion or visible_width < float(minimum[0]) or visible_height < float(minimum[1]):
            return BuildingViewportPlan(PlanDisposition.REJECTED, "map_edge_clamp_before_target", building_id, current, desired, unclamped, target_screen, (desired[0] - current[0], desired[1] - current[1]), clamped)
    if atlas.registration_coverage_polygons and not point_in_coverage(
        (desired[0] + safe_region.placement_anchor[0], desired[1] + safe_region.placement_anchor[1]),
        atlas.registration_coverage_polygons,
    ):
        return BuildingViewportPlan(PlanDisposition.REJECTED, "insufficient_predicted_registration_overlap", building_id, current, desired, unclamped, target_screen, (desired[0] - current[0], desired[1] - current[1]), clamped)
    residual = (desired[0] - current[0], desired[1] - current[1])
    return BuildingViewportPlan(PlanDisposition.PAN, "calculated_target_viewport", building_id, current, desired, unclamped, target_screen, residual, clamped)


def plan_direct_pan(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
    calibration: GestureCalibration,
) -> DirectPanPlan:
    viewport = plan_building_viewport(atlas, localization, building_id, safe_region)
    if viewport.disposition is not PlanDisposition.PAN:
        disposition = PlanDisposition.BIND if viewport.disposition is PlanDisposition.ALREADY_SAFE else viewport.disposition
        return DirectPanPlan(disposition, viewport.reason, viewport)
    if calibration.platform != localization.platform or calibration.profile_id != localization.profile_id:
        return DirectPanPlan(PlanDisposition.REJECTED, "gesture_calibration_profile_mismatch", viewport)
    dx, dy = viewport.residual_atlas
    raw_drag = (-dx / calibration.camera_px_per_drag_x, -dy / calibration.camera_px_per_drag_y)
    scale = min(1.0, calibration.maximum_drag_x / max(abs(raw_drag[0]), 1e-9), calibration.maximum_drag_y / max(abs(raw_drag[1]), 1e-9))
    drag = (raw_drag[0] * scale, raw_drag[1] * scale)
    length = math.hypot(*drag)
    if length < calibration.minimum_drag_px:
        return DirectPanPlan(PlanDisposition.BIND, "residual_below_minimum_gesture", viewport, (dx, dy), (0.0, 0.0), predicted_remaining_displacement=(dx, dy))
    start = calibration.drag_origin
    end = (int(round(start[0] + drag[0])), int(round(start[1] + drag[1])))
    x0, y0, x1, y1 = calibration.drag_bounds
    if not (x0 <= start[0] <= x1 and y0 <= start[1] <= y1 and x0 <= end[0] <= x1 and y0 <= end[1] <= y1):
        return DirectPanPlan(PlanDisposition.REJECTED, "gesture_outside_native_bounds", viewport, (dx, dy))
    predicted = (-(end[0] - start[0]) * calibration.camera_px_per_drag_x, -(end[1] - start[1]) * calibration.camera_px_per_drag_y)
    remaining = (dx - predicted[0], dy - predicted[1])
    return DirectPanPlan(PlanDisposition.PAN, "calculated_direct_pan", viewport, (dx, dy), predicted, start, end, remaining)


def measure_pan_progress(before: LocalizationResult, after: LocalizationResult, plan: DirectPanPlan, calibration: GestureCalibration) -> PanProgress:
    rejected = _localization_rejection_for_progress(before, after)
    if rejected:
        return PanProgress(False, rejected, (0.0, 0.0), plan.requested_camera_displacement, plan.requested_camera_displacement, 0.0)
    bx, by = camera_origin(before)
    ax, ay = camera_origin(after)
    measured = (ax - bx, ay - by)
    requested = plan.requested_camera_displacement
    progress = math.hypot(*measured)
    dot = measured[0] * requested[0] + measured[1] * requested[1]
    requested_length = max(math.hypot(*requested), 1.0)
    forward_progress = dot / requested_length
    if progress < calibration.minimum_progress_px or abs(forward_progress) < calibration.minimum_progress_px:
        reason = "no_measured_progress"
        accepted = False
    elif forward_progress < -calibration.wrong_direction_tolerance_px:
        reason = "movement_wrong_direction"
        accepted = False
    else:
        reason = "measured_progress"
        accepted = True
    return PanProgress(accepted, reason, measured, requested, (requested[0] - measured[0], requested[1] - measured[1]), progress)


def _localization_rejection_for_progress(before: LocalizationResult, after: LocalizationResult) -> str | None:
    if not after.recognized or after.screen_to_atlas is None:
        return "post_pan_localization_failed"
    if after.stale or after.overlay or after.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        return "post_pan_localization_invalid"
    if before.frame_sha256 == after.frame_sha256:
        return "repeated_viewport"
    return None


class DirectPanNavigator:
    """Stateful guards around pure plans; callers recapture/relocalize every turn."""

    def __init__(self, atlas: HomeAtlas, building_id: str, safe_region: SafeInteractionRegion, calibration: GestureCalibration, *, maximum_pans: int = 4) -> None:
        if maximum_pans < 1:
            raise ValueError("maximum_pans must be positive")
        self.atlas = atlas
        self.building_id = building_id
        self.safe_region = safe_region
        self.calibration = calibration
        self.maximum_pans = maximum_pans
        self.pan_count = 0
        self.seen_viewports: set[tuple[int, int]] = set()
        self.last_plan: DirectPanPlan | None = None

    def plan(self, localization: LocalizationResult, binding: BuildingBinding | None = None) -> DirectPanPlan:
        if localization.screen_to_atlas is not None:
            origin = camera_origin(localization)
            signature = (round(origin[0]), round(origin[1]))
            if signature in self.seen_viewports:
                viewport = BuildingViewportPlan(PlanDisposition.REJECTED, "repeated_viewport", self.building_id, origin, None, None, None, (0.0, 0.0))
                return DirectPanPlan(PlanDisposition.REJECTED, "repeated_viewport", viewport)
            self.seen_viewports.add(signature)
        plan = plan_direct_pan(self.atlas, localization, self.building_id, self.safe_region, self.calibration)
        if plan.disposition is PlanDisposition.BIND:
            if binding is None:
                self.last_plan = plan
                return plan
            if (binding.building_id != self.building_id or binding.frame_sha256 != localization.frame_sha256 or binding.confidence < 0.80 or not binding.semantic_evidence or binding.overlay_intersects or binding.ambiguous_overlap):
                return DirectPanPlan(PlanDisposition.REJECTED, "current_frame_building_binding_rejected", plan.viewport)
            return DirectPanPlan(PlanDisposition.COMPLETE, "current_frame_semantic_building_bound", plan.viewport)
        if plan.disposition is PlanDisposition.PAN:
            if self.pan_count >= self.maximum_pans:
                return DirectPanPlan(PlanDisposition.REJECTED, "maximum_pan_count", plan.viewport)
            self.pan_count += 1
        self.last_plan = plan
        return plan

    def record_progress(self, before: LocalizationResult, after: LocalizationResult) -> PanProgress:
        if self.last_plan is None or self.last_plan.disposition is not PlanDisposition.PAN:
            raise ValueError("no pan plan awaits progress measurement")
        return measure_pan_progress(before, after, self.last_plan, self.calibration)


def navigate_building_into_view(
    navigator: DirectPanNavigator,
    localization: LocalizationResult,
    binding: BuildingBinding | None = None,
) -> NavigationResult:
    """Return the next navigation-only result without capturing or dispatching input."""

    plan = navigator.plan(localization, binding)
    if plan.disposition is PlanDisposition.COMPLETE:
        status = "completed"
    elif plan.disposition is PlanDisposition.REJECTED:
        status = "blocked"
    elif plan.disposition is PlanDisposition.PAN:
        status = "pan_required"
    else:
        status = "binding_required"
    return NavigationResult(status, plan.reason, navigator.building_id, navigator.pan_count, localization, binding, plan)
