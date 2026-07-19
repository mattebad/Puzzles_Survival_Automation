"""Platform-neutral Home/Base atlas and closed-loop navigation contracts.

Pixel atlases, feature descriptors, zoom signatures, and gesture geometry live in a
platform adapter.  This module owns semantic world coordinates and deterministic
navigation policy only; it dispatches no input and has no registration/scheduler path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Iterable


Point = tuple[float, float]
Polygon = tuple[Point, ...]
Box = tuple[int, int, int, int]
Matrix3 = tuple[tuple[float, float, float], ...]


class ZoomIdentity(str, Enum):
    FULLY_ZOOMED_OUT = "fully_zoomed_out"
    ZOOMED_IN = "zoomed_in"
    INTERMEDIATE = "intermediate"
    UNKNOWN = "unknown"
    LOADING_OR_ANIMATION = "loading_or_animation"
    OVERLAY = "overlay"
    CLIPPED_OR_TRANSLATED = "clipped_or_translated"


class AmbiguityState(str, Enum):
    NONE = "none"
    INSUFFICIENT_LANDMARKS = "insufficient_landmarks"
    CONFLICTING_TRANSFORMS = "conflicting_transforms"
    EXCESSIVE_RESIDUAL = "excessive_residual"
    REPEATED_TERRAIN = "repeated_terrain"
    STALE_FRAME = "stale_frame"
    WRONG_PROFILE = "wrong_profile"
    WRONG_SCREEN = "wrong_screen"


@dataclass(frozen=True)
class PlatformProfile:
    platform: str
    profile_id: str
    viewport: tuple[int, int]
    package: str
    dpi: int | None = None
    renderer: str | None = None


@dataclass(frozen=True)
class AtlasViewport:
    viewport_id: str
    image_path: str
    source_sha256: str
    timestamp: str
    transform_to_atlas: Matrix3
    polygon: Polygon
    overlap_confidence: float
    residual_px: float
    registration_model: str
    loop_closure_residual_px: float = 0.0
    accepted: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True)
class SemanticBuilding:
    semantic_id: str
    display_identity: str
    polygon: Polygon
    confidence: float
    supporting_source_frames: tuple[str, ...]
    expected_visual_variants: tuple[str, ...] = ()
    recognition: dict[str, object] = field(default_factory=dict)
    visibility_constraints: tuple[str, ...] = ()
    semantic_proof: tuple[str, ...] = ()
    navigation_anchor_override: Point | None = None
    interaction_eligible: bool = True
    safe_interaction_region_id: str = "home-default"
    platform_binding_policy: dict[str, object] = field(default_factory=dict)

    @property
    def center(self) -> Point:
        return polygon_centroid(self.polygon)

    @property
    def navigation_anchor(self) -> Point:
        return self.navigation_anchor_override or self.center


@dataclass(frozen=True)
class HomeAtlas:
    schema_version: int
    atlas_id: str
    atlas_version: str
    profile: PlatformProfile
    canonical_zoom_identity: str
    coordinate_units: str
    origin: Point
    width: int
    height: int
    image_path: str
    game_build_provenance: str
    account_layout_provenance: str
    coverage_polygons: tuple[Polygon, ...]
    coverage_gaps: tuple[Polygon, ...]
    viewports: tuple[AtlasViewport, ...]
    buildings: tuple[SemanticBuilding, ...]
    registration_coverage_polygons: tuple[Polygon, ...] = ()
    camera_origin_bounds: tuple[float, float, float, float] | None = None

    def lookup_building(self, building_id: str) -> SemanticBuilding:
        matches = [item for item in self.buildings if item.semantic_id == building_id]
        if len(matches) != 1:
            raise KeyError(f"semantic building is not uniquely mapped: {building_id}")
        return matches[0]


@dataclass(frozen=True)
class LocalizationResult:
    recognized: bool
    platform: str
    profile_id: str
    zoom_identity: ZoomIdentity
    screen_to_atlas: Matrix3 | None
    viewport_polygon: Polygon
    confidence: float
    supporting_landmarks: tuple[str, ...]
    residual_px: float | None
    ambiguity_state: AmbiguityState
    map_edge_state: str
    frame_sha256: str
    timestamp: str
    stale: bool = False
    overlay: bool = False


class NavigationAction(str, Enum):
    PAN = "pan"
    BIND_TARGET = "bind_target"
    TAP_TARGET = "tap_target"
    COMPLETE = "complete"
    STOP = "stop"


@dataclass(frozen=True)
class BuildingBinding:
    building_id: str
    target_roi: Box
    frame_sha256: str
    confidence: float
    semantic_evidence: tuple[str, ...]
    overlay_intersects: bool = False
    ambiguous_overlap: bool = False


@dataclass(frozen=True)
class NavigationCommand:
    action: NavigationAction
    reason: str
    pan_start: tuple[int, int] | None = None
    pan_end: tuple[int, int] | None = None
    target_roi: Box | None = None
    target_identity: str | None = None
    terminal: bool = False


def polygon_centroid(polygon: Polygon) -> Point:
    if not polygon:
        raise ValueError("polygon is empty")
    return (
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )


def polygon_bounds(polygon: Polygon) -> tuple[float, float, float, float]:
    if not polygon:
        raise ValueError("polygon is empty")
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def polygons_intersect(left: Polygon, right: Polygon) -> bool:
    lx0, ly0, lx1, ly1 = polygon_bounds(left)
    rx0, ry0, rx1, ry1 = polygon_bounds(right)
    return lx0 <= rx1 and rx0 <= lx1 and ly0 <= ry1 and ry0 <= ly1


def point_in_coverage(point: Point, polygons: Iterable[Polygon]) -> bool:
    x, y = point
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        inside = False
        previous = polygon[-1]
        for current in polygon:
            x1, y1 = previous
            x2, y2 = current
            if min(y1, y2) <= y <= max(y1, y2):
                cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
                if abs(cross) <= 1e-9 and min(x1, x2) <= x <= max(x1, x2):
                    return True
            if (y1 > y) != (y2 > y):
                crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < crossing_x:
                    inside = not inside
            previous = current
        if inside:
            return True
    return False


def frame_sha256(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


class ClosedLoopBuildingNavigator:
    """Pure policy controller; callers must recapture and relocalize after every pan."""

    def __init__(
        self,
        atlas: HomeAtlas,
        building_id: str,
        *,
        maximum_pans: int = 8,
        safe_screen_box: Box = (145, 265, 665, 1010),
        pan_distance: int = 260,
    ) -> None:
        if maximum_pans < 1:
            raise ValueError("maximum_pans must be positive")
        self.atlas = atlas
        self.building = atlas.lookup_building(building_id)
        self.maximum_pans = maximum_pans
        self.safe_screen_box = safe_screen_box
        self.pan_distance = pan_distance
        self.pan_count = 0
        self.seen_frame_hashes: set[str] = set()
        self.previous_distance: float | None = None

    @staticmethod
    def _apply(matrix: Matrix3, point: Point) -> Point:
        x, y = point
        w = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
        if abs(w) < 1e-9:
            raise ValueError("singular screen-to-atlas transform")
        return (
            (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / w,
            (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / w,
        )

    @staticmethod
    def _inverse_affine(matrix: Matrix3, point: Point) -> Point:
        a, b, tx = matrix[0]
        c, d, ty = matrix[1]
        det = a * d - b * c
        if abs(det) < 1e-9:
            raise ValueError("singular atlas transform")
        x, y = point[0] - tx, point[1] - ty
        return ((d * x - b * y) / det, (-c * x + a * y) / det)

    def _safe_viewport_polygon(self, result: LocalizationResult) -> Polygon:
        assert result.screen_to_atlas is not None
        x0, y0, x1, y1 = self.safe_screen_box
        return tuple(
            self._apply(result.screen_to_atlas, point)
            for point in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        )

    def _building_fully_inside_safe_screen(self, result: LocalizationResult) -> bool:
        assert result.screen_to_atlas is not None
        x0, y0, x1, y1 = self.safe_screen_box
        for point in self.building.polygon:
            x, y = self._inverse_affine(result.screen_to_atlas, point)
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                return False
        return True

    def next_command(
        self,
        localization: LocalizationResult,
        binding: BuildingBinding | None = None,
    ) -> NavigationCommand:
        if localization.frame_sha256 in self.seen_frame_hashes:
            return NavigationCommand(NavigationAction.STOP, "repeated_viewport", terminal=True)
        self.seen_frame_hashes.add(localization.frame_sha256)
        if not localization.recognized or localization.screen_to_atlas is None:
            return NavigationCommand(NavigationAction.STOP, f"localization_failed:{localization.ambiguity_state.value}", terminal=True)
        if localization.stale or localization.overlay:
            return NavigationCommand(NavigationAction.STOP, "stale_or_overlay", terminal=True)
        if localization.zoom_identity != ZoomIdentity.FULLY_ZOOMED_OUT:
            return NavigationCommand(NavigationAction.STOP, "canonical_zoom_required", terminal=True)
        if not point_in_coverage(self.building.center, self.atlas.coverage_polygons):
            return NavigationCommand(NavigationAction.STOP, "target_outside_verified_coverage", terminal=True)

        if binding is not None:
            safe_x0, safe_y0, safe_x1, safe_y1 = self.safe_screen_box
            roi_x0, roi_y0, roi_x1, roi_y1 = binding.target_roi
            if (
                binding.building_id != self.building.semantic_id
                or binding.frame_sha256 != localization.frame_sha256
                or binding.confidence < 0.80
                or binding.overlay_intersects
                or binding.ambiguous_overlap
                or not binding.semantic_evidence
                or roi_x0 < safe_x0
                or roi_y0 < safe_y0
                or roi_x1 > safe_x1
                or roi_y1 > safe_y1
            ):
                return NavigationCommand(NavigationAction.STOP, "current_frame_building_binding_rejected", terminal=True)
            return NavigationCommand(
                NavigationAction.TAP_TARGET,
                "current_frame_semantic_building_bound",
                target_roi=binding.target_roi,
                target_identity=self.building.semantic_id,
            )

        # Intersection is insufficient: a building at a HUD edge may have its
        # label visible while the actionable geometry is clipped or occluded.
        # A narrower exact current-frame binding can still authorize a tap when
        # its own ROI is fully safe, as at a clamped map edge.
        visible = self._building_fully_inside_safe_screen(localization)
        if visible:
            return NavigationCommand(NavigationAction.BIND_TARGET, "semantic_current_frame_binding_required")

        if self.pan_count >= self.maximum_pans:
            return NavigationCommand(NavigationAction.STOP, "maximum_pan_count", terminal=True)
        screen_center = self._inverse_affine(localization.screen_to_atlas, self.building.center)
        safe_x0, safe_y0, safe_x1, safe_y1 = self.safe_screen_box
        cx, cy = (safe_x0 + safe_x1) // 2, (safe_y0 + safe_y1) // 2
        dx, dy = screen_center[0] - cx, screen_center[1] - cy
        distance = (dx * dx + dy * dy) ** 0.5
        if self.previous_distance is not None and distance >= self.previous_distance - 8:
            return NavigationCommand(NavigationAction.STOP, "no_measured_progress", terminal=True)
        self.previous_distance = distance
        if distance < 1:
            return NavigationCommand(NavigationAction.STOP, "target_projection_ambiguous", terminal=True)
        scale = min(1.0, self.pan_distance / distance)
        # Dragging the map opposite the target displacement moves the viewport toward it.
        end = (int(round(cx - dx * scale)), int(round(cy - dy * scale)))
        end = (max(165, min(635, end[0])), max(315, min(945, end[1])))
        self.pan_count += 1
        return NavigationCommand(
            NavigationAction.PAN,
            "bounded_pan_toward_target",
            pan_start=(cx, cy),
            pan_end=end,
        )


def _polygon(value: object) -> Polygon:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError("atlas polygon must contain at least three points")
    return tuple((float(item[0]), float(item[1])) for item in value)


def _matrix(value: object) -> Matrix3:
    if not isinstance(value, list) or len(value) != 3 or any(len(row) != 3 for row in value):
        raise ValueError("atlas transform must be a 3x3 matrix")
    return tuple(tuple(float(cell) for cell in row) for row in value)


def load_home_atlas(path: Path) -> HomeAtlas:
    payload = json.loads(path.read_text(encoding="utf-8"))
    profile = PlatformProfile(**payload["profile"])
    viewports = tuple(
        AtlasViewport(
            **{
                **item,
                "transform_to_atlas": _matrix(item["transform_to_atlas"]),
                "polygon": _polygon(item["polygon"]),
            }
        )
        for item in payload.get("viewports", [])
    )
    buildings = tuple(
        SemanticBuilding(
            **{
                **{key: value for key, value in item.items() if key != "navigation_anchor"},
                "polygon": _polygon(item["polygon"]),
                "supporting_source_frames": tuple(item["supporting_source_frames"]),
                "expected_visual_variants": tuple(item.get("expected_visual_variants", ())),
                "visibility_constraints": tuple(item.get("visibility_constraints", ())),
                "semantic_proof": tuple(item.get("semantic_proof", ())),
                "navigation_anchor_override": (
                    (float(item["navigation_anchor"][0]), float(item["navigation_anchor"][1]))
                    if item.get("navigation_anchor") is not None else None
                ),
                "interaction_eligible": bool(item.get(
                    "interaction_eligible",
                    bool(item.get("supporting_source_frames")) and item.get("semantic_id") != "home.landmark.wall",
                )),
                "safe_interaction_region_id": str(item.get("safe_interaction_region_id", "home-default")),
                "platform_binding_policy": dict(item.get("platform_binding_policy", item.get("recognition", {}))),
            }
        )
        for item in payload.get("buildings", [])
    )
    return HomeAtlas(
        schema_version=int(payload["schema_version"]),
        atlas_id=str(payload["atlas_id"]),
        atlas_version=str(payload["atlas_version"]),
        profile=profile,
        canonical_zoom_identity=str(payload["canonical_zoom_identity"]),
        coordinate_units=str(payload["coordinate_units"]),
        origin=(float(payload["origin"][0]), float(payload["origin"][1])),
        width=int(payload["width"]),
        height=int(payload["height"]),
        image_path=str(payload["image_path"]),
        game_build_provenance=str(payload.get("game_build_provenance", "unknown")),
        account_layout_provenance=str(payload.get("account_layout_provenance", "unknown")),
        coverage_polygons=tuple(_polygon(item) for item in payload.get("coverage_polygons", [])),
        coverage_gaps=tuple(_polygon(item) for item in payload.get("coverage_gaps", [])),
        viewports=viewports,
        buildings=buildings,
        registration_coverage_polygons=tuple(
            _polygon(item) for item in payload.get("registration_coverage_polygons", [])
        ),
        camera_origin_bounds=(
            float(payload["boundary_evidence"]["camera_origin_bounds"]["minimum_x"]),
            float(payload["boundary_evidence"]["camera_origin_bounds"]["minimum_y"]),
            float(payload["boundary_evidence"]["camera_origin_bounds"]["maximum_x"]),
            float(payload["boundary_evidence"]["camera_origin_bounds"]["maximum_y"]),
        ) if payload.get("boundary_evidence", {}).get("camera_origin_bounds") else None,
    )
