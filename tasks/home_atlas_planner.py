"""Platform-neutral minimal-pan planning for semantic Home/Base facilities.

The planner consumes a fresh localization plus adapter-supplied safe-region and
gesture contracts.  It never captures frames, dispatches input, or treats a
projected coordinate as semantic success.

When SafeInteractionRegion.planning_policy is None, plan_building_viewport
preserves the exact legacy single-candidate path.  When a ViewportPlanningPolicy
is present, candidates are scored for actionable entry plus predicted recovery
search-zone availability without emitting executable recovery coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Iterable

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


# Soft-score weights for recovery-aware planning. Each component is normalized to [0, 1]
# before weighting. Documented for determinism; not runtime-tuned.
VIEWPORT_SCORE_WEIGHTS: dict[str, float] = {
    "target_semantic_coverage": 0.18,
    "hud_border_clearance": 0.12,
    "label_readability": 0.10,
    "action_body_visibility": 0.12,
    "radial_footprint_clearance": 0.14,
    "predicted_recovery_search_zone": 0.16,
    "registration_support": 0.10,
    "map_edge_proximity": 0.04,
    "pan_distance": 0.04,
}

_MAX_EXTRA_REJECTED_ALTERNATIVES = 5
_RECOVERY_HONESTY = (
    "predicted_recovery_search_zone_available_is_not_a_live_tap_proof",
    "current_frame_recovery_binding_still_required",
    "projection_does_not_authorize_entry_or_exit_input",
)


class PlanDisposition(str, Enum):
    ALREADY_SAFE = "already_safe"
    PAN = "pan"
    BIND = "bind"
    COMPLETE = "complete"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ViewportPlanningPolicy:
    """Adapter-injected abstract envelopes for recovery-aware viewport selection.

    Magnitudes are screen-space pixels relative to the safe interaction region.
    They must not encode BlueStacks gesture calibration or executable tap points.
    recovery_search_* insets define the adapter-owned predicted recovery-search
    envelope inside the safe region; they are not executable tap coordinates.
    """

    radial_margin_up_px: float
    radial_margin_down_px: float
    radial_margin_left_px: float
    radial_margin_right_px: float
    recovery_clearance_px: float
    recovery_zone_half_size_px: float
    recovery_scan_step_px: float
    recovery_search_inset_left_px: float
    recovery_search_inset_top_px: float
    recovery_search_inset_right_px: float
    recovery_search_inset_bottom_px: float
    action_body_margin_px: float
    label_inset_px: float
    candidate_step_px: float
    max_candidates: int
    map_edge_soft_margin_px: float = 40.0

    def __post_init__(self) -> None:
        for name in (
            "radial_margin_up_px",
            "radial_margin_down_px",
            "radial_margin_left_px",
            "radial_margin_right_px",
            "recovery_clearance_px",
            "recovery_zone_half_size_px",
            "recovery_scan_step_px",
            "recovery_search_inset_left_px",
            "recovery_search_inset_top_px",
            "recovery_search_inset_right_px",
            "recovery_search_inset_bottom_px",
            "action_body_margin_px",
            "label_inset_px",
            "candidate_step_px",
            "map_edge_soft_margin_px",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        if self.candidate_step_px <= 0 or self.recovery_scan_step_px <= 0:
            raise ValueError("scan steps must be positive")


@dataclass(frozen=True)
class SafeInteractionRegion:
    region_id: str
    screen_box: Box
    placement_anchor: tuple[int, int]
    fixed_hud_masks: tuple[Box, ...] = ()
    planning_policy: ViewportPlanningPolicy | None = None

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
class ViewportCandidateRejection:
    reason: str
    desired_camera_origin: Point | None
    score: float | None = None
    note: str = ""


@dataclass(frozen=True)
class PredictedRecoverySearchZone:
    """Predicted atlas-free search availability only; never an executable tap."""

    available: bool
    clearance_px: float
    zone_box: Box | None
    executable_recovery_coordinate: None = None


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
    selection_score: float | None = None
    score_breakdown: tuple[tuple[str, float], ...] = ()
    rejection_counts: tuple[tuple[str, int], ...] = ()
    best_rejected_by_reason: tuple[ViewportCandidateRejection, ...] = ()
    rejected_alternatives: tuple[ViewportCandidateRejection, ...] = ()
    predicted_recovery_search_zone: PredictedRecoverySearchZone | None = None
    recovery_honesty: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class _AffineLinear:
    a: float
    b: float
    c: float
    d: float

    @property
    def det(self) -> float:
        return self.a * self.d - self.b * self.c

    def apply(self, point: Point) -> Point:
        x, y = point
        return (self.a * x + self.b * y, self.c * x + self.d * y)

    def inverse_apply(self, point: Point) -> Point:
        det = self.det
        if abs(det) < 1e-9:
            raise ValueError("singular screen-to-atlas linear component")
        x, y = point
        return ((self.d * x - self.b * y) / det, (-self.c * x + self.a * y) / det)


@dataclass(frozen=True)
class _ScoredCandidate:
    desired: Point
    unclamped: Point
    target_screen: Point
    clamped_axes: tuple[str, ...]
    pan_distance: float
    score: float
    breakdown: tuple[tuple[str, float], ...]
    recovery_zone: PredictedRecoverySearchZone
    hard_fail: str | None = None


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


def _linear_from_matrix(matrix: Matrix3) -> _AffineLinear:
    return _AffineLinear(matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1])


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


def _platform_key(localization: LocalizationResult) -> str:
    return "bluestacks" if "bluestacks" in localization.platform.lower() else localization.platform.lower()


def _building_binding_policy(building: SemanticBuilding, localization: LocalizationResult) -> dict:
    policy = building.platform_binding_policy.get(_platform_key(localization), {})
    return policy if isinstance(policy, dict) else {}


def _building_inside_safe_region(localization: LocalizationResult, building: SemanticBuilding, safe: SafeInteractionRegion) -> bool:
    assert localization.screen_to_atlas is not None
    x0, y0, x1, y1 = safe.screen_box
    return all(x0 <= sx <= x1 and y0 <= sy <= y1 for sx, sy in (_inverse_affine(localization.screen_to_atlas, p) for p in building.polygon))


def _point_in_box(point: Point, box: Box) -> bool:
    x0, y0, x1, y1 = box
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1


def _box_inside_box(inner: Box, outer: Box) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    return ox0 <= ix0 and ix1 <= ox1 and oy0 <= iy0 and iy1 <= oy1


def _boxes_intersect(a: Box, b: Box) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _boxes_overlap_area(a: Box, b: Box) -> bool:
    """True only when boxes share positive area (shared edges do not count)."""

    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return (x1 - x0) > 1e-6 and (y1 - y0) > 1e-6


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _round_evidence(value: float) -> float:
    return round(value, 6)


def _origin_signature(origin: Point) -> tuple[int, int]:
    return (round(origin[0]), round(origin[1]))


def _project_atlas_point(linear: _AffineLinear, translation: Point, atlas_point: Point) -> Point:
    return linear.inverse_apply((atlas_point[0] - translation[0], atlas_point[1] - translation[1]))


def _project_polygon(linear: _AffineLinear, translation: Point, polygon: tuple[Point, ...]) -> tuple[Point, ...]:
    return tuple(_project_atlas_point(linear, translation, point) for point in polygon)


def _screen_bounds(points: Iterable[Point]) -> Box:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _expand_box(box: Box, left: float, top: float, right: float, bottom: float) -> Box:
    x0, y0, x1, y1 = box
    return (x0 - left, y0 - top, x1 + right, y1 + bottom)


def _min_distance_to_masks(box: Box, masks: tuple[Box, ...], safe: Box) -> float:
    x0, y0, x1, y1 = box
    sx0, sy0, sx1, sy1 = safe
    border = min(x0 - sx0, y0 - sy0, sx1 - x1, sy1 - y1)
    if not masks:
        return border
    mask_gap = min(
        min(abs(x0 - mx1), abs(x1 - mx0), abs(y0 - my1), abs(y1 - my0))
        if not _boxes_intersect(box, mask)
        else 0.0
        for mask in masks
        for mx0, my0, mx1, my1 in (mask,)
    )
    return min(border, mask_gap)


def _point_to_polygon_signed_distance(point: Point, polygon: tuple[Point, ...]) -> float:
    """Positive outside, negative/zero inside. Approximate via edges + winding."""

    if len(polygon) < 3:
        return 0.0
    x, y = point
    inside = False
    min_dist = float("inf")
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1):
            inside = not inside
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        if length2 <= 1e-12:
            dist = math.hypot(x - x1, y - y1)
        else:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length2))
            dist = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
        min_dist = min(min_dist, dist)
    return -min_dist if inside else min_dist


def _legacy_plan_building_viewport(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
) -> BuildingViewportPlan:
    """Exact pre-recovery-aware single-candidate planner."""

    building = atlas.lookup_building(building_id)
    rejected = _localization_rejection(atlas, localization)
    if rejected:
        return BuildingViewportPlan(PlanDisposition.REJECTED, rejected, building_id, None, None, None, None, (0.0, 0.0))
    current = camera_origin(localization)
    if not building.interaction_eligible:
        return BuildingViewportPlan(PlanDisposition.REJECTED, "non_actionable_building", building_id, current, None, None, None, (0.0, 0.0))
    policy = _building_binding_policy(building, localization)
    allow_subregion = bool(policy.get("allow_safe_subregion_at_camera_edge"))
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
    bx0, by0, bx1, by1 = polygon_bounds(building.polygon)
    fully_fits = safe_x0 <= bx0 - desired[0] and bx1 - desired[0] <= safe_x1 and safe_y0 <= by0 - desired[1] and by1 - desired[1] <= safe_y1
    if not fully_fits:
        minimum = policy.get("minimum_safe_subregion", (55, 55))
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


def _authoritative_label_box(building: SemanticBuilding, localization: LocalizationResult, body: Box) -> Box | None:
    policy = _building_binding_policy(building, localization)
    label = policy.get("label_screen_box") or policy.get("label_geometry")
    if isinstance(label, (list, tuple)) and len(label) == 4:
        return (float(label[0]), float(label[1]), float(label[2]), float(label[3]))
    return None


def _intersect_boxes(a: Box, b: Box) -> Box | None:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _safe_dims(safe: SafeInteractionRegion) -> tuple[float, float]:
    x0, y0, x1, y1 = safe.screen_box
    return (x1 - x0, y1 - y0)


def _actionable_interaction_region(
    atlas: HomeAtlas,
    building: SemanticBuilding,
    localization: LocalizationResult,
    linear: _AffineLinear,
    translation: Point,
    safe: SafeInteractionRegion,
) -> tuple[Box | None, str | None]:
    """Return the predicted actionable screen region for radial/recovery gates.

    Full polygon fit uses the building body. When allow_safe_subregion_at_camera_edge
    is authorized, the intersection of the projected body with the safe box is used
    once it meets minimum_safe_subregion.
    """

    policy = _building_binding_policy(building, localization)
    allow_subregion = bool(policy.get("allow_safe_subregion_at_camera_edge"))
    projected = _project_polygon(linear, translation, building.polygon)
    body = _screen_bounds(projected)
    safe_box = safe.screen_box
    if _box_inside_box(body, safe_box):
        return body, None
    if not allow_subregion:
        return None, "target_coverage_outside_safe_region"
    intersection = _intersect_boxes(body, safe_box)
    if intersection is None:
        return None, "target_coverage_outside_safe_region"
    minimum = policy.get("minimum_safe_subregion", (55, 55))
    width = intersection[2] - intersection[0]
    height = intersection[3] - intersection[1]
    if width < float(minimum[0]) or height < float(minimum[1]):
        return None, "target_coverage_outside_safe_region"
    return intersection, None


def _radial_footprint(region: Box, policy: ViewportPlanningPolicy) -> Box:
    return _expand_box(region, policy.radial_margin_left_px, policy.radial_margin_up_px, policy.radial_margin_right_px, policy.radial_margin_down_px)


def _radial_ok(footprint: Box, safe: SafeInteractionRegion) -> bool:
    if not _box_inside_box(footprint, safe.screen_box):
        return False
    return not any(_boxes_overlap_area(footprint, mask) for mask in safe.fixed_hud_masks)


def _recovery_search_box(safe: SafeInteractionRegion, policy: ViewportPlanningPolicy) -> Box | None:
    sx0, sy0, sx1, sy1 = safe.screen_box
    box = (
        sx0 + policy.recovery_search_inset_left_px,
        sy0 + policy.recovery_search_inset_top_px,
        sx1 - policy.recovery_search_inset_right_px,
        sy1 - policy.recovery_search_inset_bottom_px,
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _registration_probe_score(
    atlas: HomeAtlas,
    translation: Point,
    safe: SafeInteractionRegion,
    linear: _AffineLinear,
) -> float:
    """Normalized predicted registration support in [0, 1] from safe-region probes."""

    if not atlas.registration_coverage_polygons:
        return 1.0
    sx0, sy0, sx1, sy1 = safe.screen_box
    # Platform-neutral 3x3 probe lattice across the safe region.
    xs = (sx0, (sx0 + sx1) / 2.0, sx1)
    ys = (sy0, (sy0 + sy1) / 2.0, sy1)
    hits = 0
    total = 0
    for y in ys:
        for x in xs:
            atlas_probe = (translation[0] + linear.apply((x, y))[0], translation[1] + linear.apply((x, y))[1])
            total += 1
            if point_in_coverage(atlas_probe, atlas.registration_coverage_polygons):
                hits += 1
    return hits / float(total)


def _registration_ok(atlas: HomeAtlas, translation: Point, safe: SafeInteractionRegion, linear: _AffineLinear) -> bool:
    return _registration_probe_score(atlas, translation, safe, linear) > 0.0


def _predict_recovery_search_zone(
    atlas: HomeAtlas,
    linear: _AffineLinear,
    translation: Point,
    safe: SafeInteractionRegion,
    policy: ViewportPlanningPolicy,
) -> PredictedRecoverySearchZone:
    """Predict whether a clearance search zone exists. Never returns an executable tap."""

    search = _recovery_search_box(safe, policy)
    if search is None:
        return PredictedRecoverySearchZone(False, 0.0, None, None)
    sx0, sy0, sx1, sy1 = search
    half = policy.recovery_zone_half_size_px
    step = policy.recovery_scan_step_px
    # Include all atlas buildings. Transient live units/controls remain adapter-bound.
    projected = [_project_polygon(linear, translation, building.polygon) for building in atlas.buildings]
    best_clearance = -1.0
    best_zone: Box | None = None
    y = sy0 + half
    while y <= sy1 - half + 1e-9:
        x = sx0 + half
        while x <= sx1 - half + 1e-9:
            zone = (x - half, y - half, x + half, y + half)
            if not _box_inside_box(zone, search):
                x += step
                continue
            if any(_boxes_overlap_area(zone, mask) for mask in safe.fixed_hud_masks):
                x += step
                continue
            clearances = [_point_to_polygon_signed_distance((x, y), polygon) for polygon in projected]
            if clearances and min(clearances) >= policy.recovery_clearance_px:
                clearance = min(clearances)
                if clearance > best_clearance:
                    best_clearance = clearance
                    best_zone = zone
            x += step
        y += step
    if best_zone is None:
        return PredictedRecoverySearchZone(False, 0.0, None, None)
    return PredictedRecoverySearchZone(True, best_clearance, best_zone, None)


def _hard_evaluate_candidate(
    atlas: HomeAtlas,
    building: SemanticBuilding,
    localization: LocalizationResult,
    safe: SafeInteractionRegion,
    policy: ViewportPlanningPolicy,
    linear: _AffineLinear,
    unclamped: Point,
    current: Point,
) -> _ScoredCandidate:
    if atlas.camera_origin_bounds is None:
        return _ScoredCandidate(unclamped, unclamped, (0.0, 0.0), (), 0.0, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), "camera_origin_bounds_unverified")
    min_x, min_y, max_x, max_y = atlas.camera_origin_bounds
    desired = (max(min_x, min(max_x, unclamped[0])), max(min_y, min(max_y, unclamped[1])))
    clamped = tuple(axis for axis, before, after in (("x", unclamped[0], desired[0]), ("y", unclamped[1], desired[1])) if abs(before - after) > 1e-6)
    target_screen = _project_atlas_point(linear, desired, building.navigation_anchor)
    pan_distance = math.hypot(desired[0] - current[0], desired[1] - current[1])
    actionable, coverage_reason = _actionable_interaction_region(atlas, building, localization, linear, desired, safe)
    if actionable is None:
        return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), coverage_reason or "target_coverage_outside_safe_region")
    binding_policy = _building_binding_policy(building, localization)
    allow_subregion = bool(binding_policy.get("allow_safe_subregion_at_camera_edge"))
    action_body = _expand_box(actionable, policy.action_body_margin_px, policy.action_body_margin_px, policy.action_body_margin_px, policy.action_body_margin_px)
    if allow_subregion:
        # Camera-edge subregions may already touch the safe boundary; keep the in-safe slice.
        action_body = _intersect_boxes(action_body, safe.screen_box) or actionable
    if not _box_inside_box(action_body, safe.screen_box) or any(_boxes_overlap_area(action_body, mask) for mask in safe.fixed_hud_masks):
        return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), "insufficient_action_body_visibility")
    footprint = _radial_footprint(actionable, policy)
    if allow_subregion:
        footprint = _intersect_boxes(footprint, safe.screen_box) or actionable
        if not _box_inside_box(actionable, footprint) or any(_boxes_overlap_area(footprint, mask) for mask in safe.fixed_hud_masks):
            return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), "insufficient_radial_footprint")
    elif not _radial_ok(footprint, safe):
        return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), "insufficient_radial_footprint")
    registration = _registration_probe_score(atlas, desired, safe, linear)
    if registration <= 0.0:
        return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), PredictedRecoverySearchZone(False, 0.0, None), "insufficient_predicted_registration_overlap")
    recovery = _predict_recovery_search_zone(atlas, linear, desired, safe, policy)
    if not recovery.available:
        return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, 0.0, (), recovery, "predicted_recovery_search_zone_unavailable")
    safe_w, safe_h = _safe_dims(safe)
    clearance_norm = max(min(safe_w, safe_h) * 0.1, 1.0)
    cam_span = max(math.hypot(max_x - min_x, max_y - min_y), 1.0)
    label_box = _authoritative_label_box(building, localization, actionable) or actionable
    inset = policy.label_inset_px
    label_clearance = _min_distance_to_masks(label_box, safe.fixed_hud_masks, safe.screen_box)
    components = {
        "target_semantic_coverage": _clamp01(min(actionable[2] - actionable[0], actionable[3] - actionable[1]) / max(min(safe_w, safe_h) * 0.25, 1.0)),
        "hud_border_clearance": _clamp01(_min_distance_to_masks(actionable, safe.fixed_hud_masks, safe.screen_box) / clearance_norm),
        "label_readability": _clamp01(max(0.0, label_clearance - inset) / clearance_norm),
        "action_body_visibility": _clamp01(_min_distance_to_masks(action_body, safe.fixed_hud_masks, safe.screen_box) / clearance_norm),
        "radial_footprint_clearance": _clamp01(_min_distance_to_masks(footprint, safe.fixed_hud_masks, safe.screen_box) / clearance_norm),
        "predicted_recovery_search_zone": _clamp01(recovery.clearance_px / max(policy.recovery_clearance_px * 2.0, 1.0)),
        "registration_support": _clamp01(registration),
        "map_edge_proximity": _clamp01(
            min(
                desired[0] - min_x,
                max_x - desired[0],
                desired[1] - min_y,
                max_y - desired[1],
            )
            / max(policy.map_edge_soft_margin_px, 1.0)
        ),
        "pan_distance": _clamp01(1.0 - pan_distance / cam_span),
    }
    breakdown = tuple((name, _round_evidence(components[name])) for name in VIEWPORT_SCORE_WEIGHTS)
    score = sum(VIEWPORT_SCORE_WEIGHTS[name] * components[name] for name in VIEWPORT_SCORE_WEIGHTS)
    return _ScoredCandidate(desired, unclamped, target_screen, clamped, pan_distance, score, breakdown, recovery, None)


def _candidate_screen_placements(safe: SafeInteractionRegion, policy: ViewportPlanningPolicy) -> list[tuple[float, float]]:
    """Deterministic spatially distributed placements covering the full feasible region."""

    sx0, sy0, sx1, sy1 = safe.screen_box
    inset = max(policy.label_inset_px, policy.action_body_margin_px)
    x0, y0 = sx0 + inset, sy0 + inset
    x1, y1 = sx1 - inset, sy1 - inset
    if x1 <= x0 or y1 <= y0:
        return [safe.placement_anchor]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    seeds = [
        safe.placement_anchor,
        (cx, cy),
        (cx, y0),
        (cx, y1),
        (x0, cy),
        (x1, cy),
        (x0, y0),
        (x1, y0),
        (x0, y1),
        (x1, y1),
    ]
    span_x = x1 - x0
    span_y = y1 - y0
    step = policy.candidate_step_px
    cols = max(2, int(math.floor(span_x / step)) + 1)
    rows = max(2, int(math.floor(span_y / step)) + 1)
    lattice: list[tuple[float, float]] = []
    for row in range(rows):
        y = y0 if rows == 1 else y0 + (span_y * row / (rows - 1))
        for col in range(cols):
            x = x0 if cols == 1 else x0 + (span_x * col / (cols - 1))
            lattice.append((x, y))
    unique: dict[tuple[int, int], tuple[float, float]] = {}
    for point in seeds + lattice:
        if x0 - 1e-6 <= point[0] <= x1 + 1e-6 and y0 - 1e-6 <= point[1] <= y1 + 1e-6:
            unique[(round(point[0]), round(point[1]))] = point
    ordered = sorted(unique.values(), key=lambda item: (item[1], item[0]))
    priority = []
    seen: set[tuple[int, int]] = set()
    for point in seeds + [
        min(ordered, key=lambda p: (p[0], p[1])),
        max(ordered, key=lambda p: (p[0], p[1])),
        min(ordered, key=lambda p: (p[1], p[0])),
        max(ordered, key=lambda p: (p[1], p[0])),
    ]:
        key = (round(point[0]), round(point[1]))
        if key in unique and key not in seen:
            priority.append(unique[key])
            seen.add(key)
    selected = priority[: policy.max_candidates]
    if len(selected) >= policy.max_candidates:
        return sorted(selected[: policy.max_candidates], key=lambda item: (item[1], item[0]))
    remaining = [p for p in ordered if (round(p[0]), round(p[1])) not in {(round(s[0]), round(s[1])) for s in selected}]
    while len(selected) < policy.max_candidates and remaining:
        def min_dist2(candidate: tuple[float, float]) -> tuple[float, float, float]:
            best = min((candidate[0] - s[0]) ** 2 + (candidate[1] - s[1]) ** 2 for s in selected)
            return (-best, candidate[1], candidate[0])
        pick = min(remaining, key=min_dist2)
        selected.append(pick)
        remaining.remove(pick)
    return sorted(selected, key=lambda item: (item[1], item[0]))


def _build_rejection_evidence(rejected: list[_ScoredCandidate]) -> tuple[
    tuple[tuple[str, int], ...],
    tuple[ViewportCandidateRejection, ...],
    tuple[ViewportCandidateRejection, ...],
]:
    counts: dict[str, int] = {}
    best_by_reason: dict[str, ViewportCandidateRejection] = {}
    ranked: list[ViewportCandidateRejection] = []
    for item in rejected:
        reason = item.hard_fail or "unscored"
        counts[reason] = counts.get(reason, 0) + 1
        record = ViewportCandidateRejection(
            reason,
            None if item.desired is None else (_round_evidence(item.desired[0]), _round_evidence(item.desired[1])),
            None if item.hard_fail else _round_evidence(item.score),
            note="rejected_candidate",
        )
        ranked.append(record)
        previous = best_by_reason.get(reason)
        if previous is None or (record.score or -1.0) > (previous.score or -1.0):
            best_by_reason[reason] = record
    # Prefer lower pan distance among hard rejects with equal score for extras.
    extras = sorted(
        ranked,
        key=lambda item: (
            -(item.score or -1.0),
            0.0 if item.desired_camera_origin is None else math.hypot(item.desired_camera_origin[0], item.desired_camera_origin[1]),
            0.0 if item.desired_camera_origin is None else item.desired_camera_origin[0],
            0.0 if item.desired_camera_origin is None else item.desired_camera_origin[1],
        ),
    )[:_MAX_EXTRA_REJECTED_ALTERNATIVES]
    count_items = tuple(sorted(counts.items()))
    best_items = tuple(best_by_reason[reason] for reason in sorted(best_by_reason))
    return count_items, best_items, tuple(extras)


def _plan_with_policy(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
    *,
    seen_destinations: Iterable[tuple[int, int]] | None = None,
) -> BuildingViewportPlan:
    policy = safe_region.planning_policy
    assert policy is not None
    assert localization.screen_to_atlas is not None
    building = atlas.lookup_building(building_id)
    rejected = _localization_rejection(atlas, localization)
    if rejected:
        return BuildingViewportPlan(PlanDisposition.REJECTED, rejected, building_id, None, None, None, None, (0.0, 0.0), recovery_honesty=_RECOVERY_HONESTY)
    current = camera_origin(localization)
    if not building.interaction_eligible:
        return BuildingViewportPlan(PlanDisposition.REJECTED, "non_actionable_building", building_id, current, None, None, None, (0.0, 0.0), recovery_honesty=_RECOVERY_HONESTY)
    binding_policy = _building_binding_policy(building, localization)
    allow_subregion = bool(binding_policy.get("allow_safe_subregion_at_camera_edge"))
    fully_covered = all(point_in_coverage(point, atlas.coverage_polygons) for point in building.polygon)
    if not fully_covered and not (allow_subregion and point_in_coverage(building.navigation_anchor, atlas.coverage_polygons)):
        return BuildingViewportPlan(PlanDisposition.REJECTED, "target_outside_verified_coverage", building_id, current, None, None, None, (0.0, 0.0), recovery_honesty=_RECOVERY_HONESTY)
    if atlas.camera_origin_bounds is None:
        return BuildingViewportPlan(PlanDisposition.REJECTED, "camera_origin_bounds_unverified", building_id, current, None, None, None, (0.0, 0.0), recovery_honesty=_RECOVERY_HONESTY)

    linear = _linear_from_matrix(localization.screen_to_atlas)
    seen = set(seen_destinations or ())
    # Evaluate current viewport first for ALREADY_SAFE.
    current_eval = _hard_evaluate_candidate(atlas, building, localization, safe_region, policy, linear, current, current)
    if current_eval.hard_fail is None:
        anchor = _project_atlas_point(linear, current, building.navigation_anchor)
        return BuildingViewportPlan(
            PlanDisposition.ALREADY_SAFE,
            "target_already_safely_visible",
            building_id,
            current,
            current,
            current,
            anchor,
            (0.0, 0.0),
            selection_score=_round_evidence(current_eval.score),
            score_breakdown=current_eval.breakdown,
            predicted_recovery_search_zone=replace(current_eval.recovery_zone, clearance_px=_round_evidence(current_eval.recovery_zone.clearance_px)),
            recovery_honesty=_RECOVERY_HONESTY,
        )

    passed: list[_ScoredCandidate] = []
    failed: list[_ScoredCandidate] = []
    for sx, sy in _candidate_screen_placements(safe_region, policy):
        unclamped = (
            building.navigation_anchor[0] - linear.apply((sx, sy))[0],
            building.navigation_anchor[1] - linear.apply((sx, sy))[1],
        )
        evaluated = _hard_evaluate_candidate(atlas, building, localization, safe_region, policy, linear, unclamped, current)
        if _origin_signature(evaluated.desired) in seen:
            failed.append(
                _ScoredCandidate(
                    evaluated.desired,
                    evaluated.unclamped,
                    evaluated.target_screen,
                    evaluated.clamped_axes,
                    evaluated.pan_distance,
                    evaluated.score,
                    evaluated.breakdown,
                    evaluated.recovery_zone,
                    "destination_already_visited",
                )
            )
            continue
        if evaluated.hard_fail is not None:
            failed.append(evaluated)
            continue
        passed.append(evaluated)

    counts, best_by_reason, extras = _build_rejection_evidence(failed)
    if not passed:
        return BuildingViewportPlan(
            PlanDisposition.REJECTED,
            "no_recoverable_actionable_viewport",
            building_id,
            current,
            None,
            None,
            None,
            (0.0, 0.0),
            rejection_counts=counts,
            best_rejected_by_reason=best_by_reason,
            rejected_alternatives=extras,
            recovery_honesty=_RECOVERY_HONESTY,
        )

    passed.sort(
        key=lambda item: (
            -item.score,
            item.pan_distance,
            item.desired[0],
            item.desired[1],
        )
    )
    winner = passed[0]
    residual = (winner.desired[0] - current[0], winner.desired[1] - current[1])
    return BuildingViewportPlan(
        PlanDisposition.PAN,
        "recovery_aware_target_viewport",
        building_id,
        current,
        winner.desired,
        winner.unclamped,
        winner.target_screen,
        residual,
        winner.clamped_axes,
        selection_score=_round_evidence(winner.score),
        score_breakdown=winner.breakdown,
        rejection_counts=counts,
        best_rejected_by_reason=best_by_reason,
        rejected_alternatives=extras,
        predicted_recovery_search_zone=replace(winner.recovery_zone, clearance_px=_round_evidence(winner.recovery_zone.clearance_px)),
        recovery_honesty=_RECOVERY_HONESTY,
    )


def _plan_building_viewport_impl(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
    *,
    seen_destinations: Iterable[tuple[int, int]] | None = None,
) -> BuildingViewportPlan:
    """Private planner that can reject already-visited destination origins."""

    if safe_region.planning_policy is None:
        return _legacy_plan_building_viewport(atlas, localization, building_id, safe_region)
    return _plan_with_policy(atlas, localization, building_id, safe_region, seen_destinations=seen_destinations)


def plan_building_viewport(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
) -> BuildingViewportPlan:
    """Choose a reachable camera origin that safely places a building."""

    return _plan_building_viewport_impl(atlas, localization, building_id, safe_region)


def plan_direct_pan(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
    calibration: GestureCalibration,
) -> DirectPanPlan:
    """Public direct-pan planner; destination history is navigator-private."""

    return _plan_direct_pan_impl(atlas, localization, building_id, safe_region, calibration)


def _plan_direct_pan_impl(
    atlas: HomeAtlas,
    localization: LocalizationResult,
    building_id: str,
    safe_region: SafeInteractionRegion,
    calibration: GestureCalibration,
    *,
    seen_destinations: Iterable[tuple[int, int]] | None = None,
) -> DirectPanPlan:
    viewport = _plan_building_viewport_impl(
        atlas,
        localization,
        building_id,
        safe_region,
        seen_destinations=seen_destinations,
    )
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
    # Reject destination already in navigator history before dispatch.
    if seen_destinations is not None and viewport.desired_camera_origin is not None:
        if _origin_signature(viewport.desired_camera_origin) in set(seen_destinations):
            blocked = replace(viewport, disposition=PlanDisposition.REJECTED, reason="destination_already_visited")
            return DirectPanPlan(PlanDisposition.REJECTED, "destination_already_visited", blocked, (dx, dy))
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
            signature = _origin_signature(origin)
            if signature in self.seen_viewports:
                viewport = BuildingViewportPlan(PlanDisposition.REJECTED, "repeated_viewport", self.building_id, origin, None, None, None, (0.0, 0.0), recovery_honesty=_RECOVERY_HONESTY)
                return DirectPanPlan(PlanDisposition.REJECTED, "repeated_viewport", viewport)
            self.seen_viewports.add(signature)
        plan = _plan_direct_pan_impl(
            self.atlas,
            localization,
            self.building_id,
            self.safe_region,
            self.calibration,
            seen_destinations=self.seen_viewports,
        )
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
            if plan.viewport.desired_camera_origin is not None:
                destination = _origin_signature(plan.viewport.desired_camera_origin)
                if destination in self.seen_viewports:
                    blocked = replace(plan.viewport, disposition=PlanDisposition.REJECTED, reason="destination_already_visited")
                    return DirectPanPlan(PlanDisposition.REJECTED, "destination_already_visited", blocked)
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
