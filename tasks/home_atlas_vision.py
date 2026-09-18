"""BlueStacks-specific Home atlas registration, zoom recognition, and localization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from .home_atlas import (
    AmbiguityState,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    Matrix3,
    Point,
    Polygon,
    SemanticBuilding,
    ZoomIdentity,
    point_in_polygon,
    polygon_is_valid,
)


BLUESTACKS_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
BLUESTACKS_PLATFORM = "BlueStacks 5 / Android"
PROFILE_SIZE = (800, 1280)

# Registration ignores all fixed HUD, chat, banner, bottom-navigation, and edge controls.
HUD_MASK_RECTS: tuple[tuple[int, int, int, int], ...] = (
    # The resource bar ends near y=82, but its centered curved-arrow control
    # extends below it and otherwise creates a strong false zero-motion peak.
    (0, 0, 800, 150),
    (0, 150, 138, 760),
    # BlueStacks' rotating event stack reaches well into the scene.  Mask the
    # whole stack rather than allowing its fixed screen geometry to dominate
    # registration when the world camera moves underneath it.
    (560, 150, 800, 640),
    (675, 640, 800, 1020),
    (0, 1020, 800, 1280),
)
SCENE_ROI = (138, 150, 560, 1020)
BLUESTACKS_SAFE_INTERACTION_BOX = (145, 180, 650, 1010)
BLUESTACKS_INTERACTION_ANCHOR = (400, 600)


@dataclass(frozen=True)
class RegistrationResult:
    accepted: bool
    model: str
    transform_candidate_to_reference: np.ndarray | None
    confidence: float
    residual_px: float
    inliers: int
    matches: int
    overlap_ratio: float
    reason: str


@dataclass(frozen=True)
class ZoomClassification:
    identity: ZoomIdentity
    confidence: float
    scale: float | None
    residual_px: float | None
    supporting_landmarks: tuple[str, ...]
    reason: str


def native_frame_guard(frame: np.ndarray) -> bool:
    return bool(
        getattr(frame, "shape", None) == (1280, 800, 3)
        and getattr(frame, "dtype", None) == np.uint8
    )


def frame_digest(frame: np.ndarray) -> str:
    ok, payload = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("cannot encode frame for hashing")
    return hashlib.sha256(payload.tobytes()).hexdigest()


def _record_binding_diagnostic(
    diagnostics: dict[str, object] | None,
    *,
    reason: str,
    **details: object,
) -> None:
    if diagnostics is None:
        return
    diagnostics.clear()
    diagnostics.update({"reason": reason, **details})


_MINIMUM_TARGET_SIZE = (33, 33)
_MINIMUM_LOCALIZATION_CONFIDENCE = 0.80
_MAXIMUM_LOCALIZATION_RESIDUAL_PX = 4.5


def _matrix_inverse(matrix: Matrix3) -> np.ndarray:
    candidate = np.asarray(matrix, dtype=np.float64)
    if candidate.shape != (3, 3) or not np.all(np.isfinite(candidate)):
        raise ValueError("localization transform is not finite 3x3")
    determinant = float(np.linalg.det(candidate))
    if not math.isfinite(determinant) or abs(determinant) < 1e-9:
        raise ValueError("localization transform is singular")
    inverse = np.linalg.inv(candidate)
    if not np.all(np.isfinite(inverse)):
        raise ValueError("localization inverse transform is not finite")
    return inverse


def _project_points(inverse: np.ndarray, points: Iterable[Point]) -> np.ndarray:
    source = np.asarray(tuple(points), dtype=np.float64)
    if source.ndim != 2 or source.shape[1] != 2 or not len(source):
        raise ValueError("projection points are invalid")
    homogeneous = np.column_stack((source, np.ones(len(source), dtype=np.float64)))
    projected = homogeneous @ inverse.T
    weights = projected[:, 2]
    if np.any(~np.isfinite(projected)) or np.any(np.abs(weights) < 1e-9):
        raise ValueError("projection contains invalid homogeneous coordinates")
    result = projected[:, :2] / weights[:, None]
    if not np.all(np.isfinite(result)):
        raise ValueError("projection contains non-finite coordinates")
    return result


def _box_inside(
    box: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> bool:
    return (
        outer[0] <= box[0]
        and box[2] <= outer[2]
        and outer[1] <= box[1]
        and box[3] <= outer[3]
    )


def _centered_box(center: Point, width: int, height: int) -> tuple[int, int, int, int]:
    x0 = int(round(center[0] - width / 2.0))
    y0 = int(round(center[1] - height / 2.0))
    return (x0, y0, x0 + width, y0 + height)


def _box_inside_polygon(box: tuple[int, int, int, int], polygon: Polygon) -> bool:
    x0, y0, x1, y1 = box
    if not all(
        point_in_polygon(point, polygon)
        for point in (
            (float(x0), float(y0)),
            (float(x1), float(y0)),
            (float(x1), float(y1)),
            (float(x0), float(y1)),
        )
    ):
        return False
    # Corners alone miss a concave notch entering between them. Clip each
    # footprint edge against the open rectangle; boundary contact is allowed.
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        entry, exit = 0.0, 1.0
        for coordinate, delta, lower, upper in (
            (start[0], end[0] - start[0], x0, x1),
            (start[1], end[1] - start[1], y0, y1),
        ):
            if delta == 0:
                if not lower < coordinate < upper:
                    break
            else:
                first = (lower - coordinate) / delta
                last = (upper - coordinate) / delta
                entry = max(entry, min(first, last))
                exit = min(exit, max(first, last))
        else:
            if entry < exit:
                return False
    return True


def _target_roi(
    projected: np.ndarray,
    screen_anchor: Point,
    policy: dict[str, object],
) -> tuple[tuple[int, int, int, int] | None, str | None, dict[str, object]]:
    polygon = tuple((float(x), float(y)) for x, y in projected)
    body = (
        float(np.min(projected[:, 0])),
        float(np.min(projected[:, 1])),
        float(np.max(projected[:, 0])),
        float(np.max(projected[:, 1])),
    )
    safe = tuple(float(value) for value in BLUESTACKS_SAFE_INTERACTION_BOX)
    visible = (
        max(body[0], safe[0]),
        max(body[1], safe[1]),
        min(body[2], safe[2]),
        min(body[3], safe[3]),
    )
    minimum = policy.get("minimum_safe_subregion", (45, 45))
    if not isinstance(minimum, (list, tuple)) or len(minimum) != 2:
        return None, "invalid_safe_region_policy", {"body_bounds": body, "visible_bounds": visible}
    try:
        minimum_width, minimum_height = float(minimum[0]), float(minimum[1])
    except (TypeError, ValueError):
        return None, "invalid_safe_region_policy", {"body_bounds": body, "visible_bounds": visible}
    if not all(math.isfinite(value) and value > 0 for value in (minimum_width, minimum_height)):
        return None, "invalid_safe_region_policy", {"body_bounds": body, "visible_bounds": visible}
    if visible[2] <= visible[0] or visible[3] <= visible[1]:
        return None, "target_coverage_outside_safe_region", {"body_bounds": body, "visible_bounds": visible}
    # Only the anchored hit region must be HUD-free, not the entire building.
    # Keep its centre fixed even when the footprint extends beyond the safe scene.
    if visible[2] - visible[0] < minimum_width or visible[3] - visible[1] < minimum_height:
        return None, "target_coverage_outside_safe_region", {"body_bounds": body, "visible_bounds": visible}
    if not (
        visible[0] <= screen_anchor[0] <= visible[2]
        and visible[1] <= screen_anchor[1] <= visible[3]
    ):
        return None, "interaction_anchor_outside_safe_region", {"body_bounds": body, "visible_bounds": visible}
    inset_x = min(18.0, max(6.0, (visible[2] - visible[0]) / 8.0))
    inset_y = min(18.0, max(6.0, (visible[3] - visible[1]) / 8.0))
    width = int(math.floor(visible[2] - visible[0] - 2.0 * inset_x))
    height = int(math.floor(visible[3] - visible[1] - 2.0 * inset_y))
    details = {
        "body_bounds": body,
        "visible_bounds": visible,
        "inset": (inset_x, inset_y),
        "minimum_safe_subregion": (minimum_width, minimum_height),
    }
    minimum_target_width, minimum_target_height = _MINIMUM_TARGET_SIZE
    while width >= minimum_target_width and height >= minimum_target_height:
        target = _centered_box(screen_anchor, width, height)
        if _box_inside(tuple(float(value) for value in target), safe) and _box_inside_polygon(target, polygon):
            return target, None, details
        if width >= height:
            width -= 1
        else:
            height -= 1
    return None, "interaction_anchor_has_no_safe_hit_region", details


def bind_visible_building(
    frame: np.ndarray,
    localization: LocalizationResult,
    building: SemanticBuilding,
    *,
    diagnostics: dict[str, object] | None = None,
) -> BuildingBinding | None:
    """Bind a mapped building from fresh frame geometry, never label OCR."""

    def reject(reason: str, predicate: str, **details: object) -> None:
        _record_binding_diagnostic(diagnostics, reason=reason, predicate=predicate, **details)

    if not native_frame_guard(frame):
        reject("localization_failed", "native_frame_guard")
        return None
    if localization.platform != BLUESTACKS_PLATFORM or localization.profile_id != BLUESTACKS_PROFILE_ID:
        reject(
            "localization_failed",
            "platform_profile",
            expected_platform=BLUESTACKS_PLATFORM,
            actual_platform=localization.platform,
            expected_profile_id=BLUESTACKS_PROFILE_ID,
            actual_profile_id=localization.profile_id,
        )
        return None
    try:
        current_digest = frame_digest(frame)
    except (RuntimeError, ValueError):
        reject("localization_failed", "frame_digest")
        return None
    if localization.frame_sha256 != current_digest:
        reject(
            "localization_failed",
            "current_frame_digest",
            localization_frame_sha256=localization.frame_sha256,
            current_frame_sha256=current_digest,
        )
        return None
    if (
        not localization.recognized
        or localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT
        or localization.ambiguity_state is not AmbiguityState.NONE
        or localization.stale
        or localization.overlay
    ):
        reject(
            "localization_failed",
            "canonical_localization_state",
            recognized=localization.recognized,
            zoom_identity=getattr(localization.zoom_identity, "value", localization.zoom_identity),
            ambiguity_state=getattr(localization.ambiguity_state, "value", localization.ambiguity_state),
            stale=localization.stale,
            overlay=localization.overlay,
        )
        return None
    if (
        not math.isfinite(float(localization.confidence))
        or localization.confidence < _MINIMUM_LOCALIZATION_CONFIDENCE
        or not localization.supporting_landmarks
        or localization.residual_px is None
        or not math.isfinite(float(localization.residual_px))
        or localization.residual_px > _MAXIMUM_LOCALIZATION_RESIDUAL_PX
    ):
        reject(
            "localization_failed",
            "localization_quality",
            confidence=localization.confidence,
            supporting_landmarks=localization.supporting_landmarks,
            residual_px=localization.residual_px,
        )
        return None
    try:
        viewport_valid = len(localization.viewport_polygon) >= 3 and all(
            len(point) == 2
            and all(math.isfinite(float(coordinate)) for coordinate in point)
            for point in localization.viewport_polygon
        )
    except (TypeError, ValueError):
        viewport_valid = False
    if not viewport_valid:
        reject("localization_failed", "viewport_polygon")
        return None
    if not building.interaction_eligible:
        reject("target_unsafe", "interaction_eligible", building_id=building.semantic_id)
        return None
    if not math.isfinite(float(building.confidence)) or building.confidence < _MINIMUM_LOCALIZATION_CONFIDENCE:
        reject("target_unsafe", "building_confidence", building_id=building.semantic_id, confidence=building.confidence)
        return None
    if building.safe_interaction_region_id != "home-default":
        reject(
            "target_unsafe",
            "safe_interaction_region",
            building_id=building.semantic_id,
            safe_interaction_region_id=building.safe_interaction_region_id,
        )
        return None
    policies = building.platform_binding_policy if isinstance(building.platform_binding_policy, dict) else {}
    recognition = building.recognition if isinstance(building.recognition, dict) else {}
    policy = policies.get("bluestacks", recognition.get("bluestacks", {}))
    if not isinstance(policy, dict) or policy.get("actionable", True) is False:
        reject("target_unsafe", "platform_actionability", building_id=building.semantic_id)
        return None
    if not polygon_is_valid(building.polygon):
        reject("target_unsafe", "building_polygon", building_id=building.semantic_id)
        return None
    try:
        atlas_anchor = building.interaction_anchor
        if not all(math.isfinite(float(coordinate)) for coordinate in atlas_anchor):
            raise ValueError("interaction anchor is not finite")
        if not point_in_polygon(atlas_anchor, building.polygon):
            reject(
                "target_unsafe",
                "interaction_anchor_inside_footprint",
                building_id=building.semantic_id,
                atlas_anchor=atlas_anchor,
            )
            return None
        geometry = _project_points(
            _matrix_inverse(localization.screen_to_atlas),
            (*building.polygon, atlas_anchor),
        )
        projected = geometry[:-1]
        screen_anchor = (float(geometry[-1, 0]), float(geometry[-1, 1]))
    except (TypeError, ValueError, np.linalg.LinAlgError) as exc:
        reject(
            "localization_failed" if "transform" in str(exc) or "projection" in str(exc) else "target_unsafe",
            "geometry_projection",
            error=f"{type(exc).__name__}: {exc}",
        )
        return None
    target, target_reason, target_details = _target_roi(projected, screen_anchor, policy)
    details = {
        "building_id": building.semantic_id,
        "anchor_source": "explicit_override" if building.interaction_anchor_override is not None else "polygon_centroid",
        "atlas_anchor": atlas_anchor,
        "screen_anchor": screen_anchor,
        "projected_polygon": projected.tolist(),
        "target_roi": target,
        **target_details,
    }
    if target is None:
        reject("target_unsafe", target_reason or "target_geometry", **details)
        return None
    _record_binding_diagnostic(
        diagnostics,
        reason="accepted",
        **details,
        decisive_predicate={
            "geometry_valid": True,
            "anchor_inside_footprint": True,
            "target_center_error_px": (
                abs(((target[0] + target[2]) / 2.0) - screen_anchor[0]),
                abs(((target[1] + target[3]) / 2.0) - screen_anchor[1]),
            ),
        },
    )
    return BuildingBinding(
        building_id=building.semantic_id,
        target_roi=target,
        frame_sha256=localization.frame_sha256,
        confidence=min(localization.confidence, building.confidence, 0.98),
        semantic_evidence=(
            "current-frame Atlas projection",
            "interaction anchor inside mapped footprint",
            "BlueStacks canonical localization",
        ),
        anchor_source=details["anchor_source"],
        atlas_anchor=atlas_anchor,
        screen_anchor=screen_anchor,
    )


def hud_mask(shape: tuple[int, ...] = (1280, 800, 3)) -> np.ndarray:
    if shape[:2] != (1280, 800):
        raise ValueError("HUD mask requires native 800x1280 portrait geometry")
    mask = np.full((1280, 800), 255, dtype=np.uint8)
    for x0, y0, x1, y1 in HUD_MASK_RECTS:
        mask[y0:y1, x0:x1] = 0
    return mask


def mask_home_hud(frame: np.ndarray) -> np.ndarray:
    if not native_frame_guard(frame):
        raise ValueError("Home HUD masking requires native 800x1280 BGR frame")
    result = frame.copy()
    result[hud_mask(frame.shape) == 0] = 0
    return result


def _feature_input(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # CLAHE improves night/day and illumination tolerance without pooling platform thresholds.
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return gray, hud_mask(frame.shape)


def _features(frame: np.ndarray):
    gray, mask = _feature_input(frame)
    detector = cv2.SIFT_create(nfeatures=3500, contrastThreshold=0.025, edgeThreshold=14)
    return detector.detectAndCompute(gray, mask)


def _matched_points(candidate: np.ndarray, reference: np.ndarray):
    key_candidate, desc_candidate = _features(candidate)
    key_reference, desc_reference = _features(reference)
    if desc_candidate is None or desc_reference is None:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32), 0
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc_candidate, desc_reference, k=2)
    good = [first for first, second in pairs if first.distance < 0.70 * second.distance]
    if len(good) < 4:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32), len(good)
    candidate_points = np.float32([key_candidate[item.queryIdx].pt for item in good])
    reference_points = np.float32([key_reference[item.trainIdx].pt for item in good])
    return candidate_points, reference_points, len(good)


def _project(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(points.reshape(-1, 1, 2), matrix).reshape(-1, 2)


def _residual(matrix: np.ndarray, source: np.ndarray, destination: np.ndarray, inliers: np.ndarray | None = None) -> float:
    if inliers is not None:
        keep = inliers.reshape(-1).astype(bool)
        source, destination = source[keep], destination[keep]
    if not len(source):
        return math.inf
    errors = np.linalg.norm(_project(matrix, source) - destination, axis=1)
    return float(np.median(errors))


def _overlap_ratio(matrix: np.ndarray) -> float:
    corners = np.float32([[0, 0], [800, 0], [800, 1280], [0, 1280]])
    projected = _project(matrix, corners)
    x0, y0 = np.maximum(projected.min(axis=0), (0, 0))
    x1, y1 = np.minimum(projected.max(axis=0), (800, 1280))
    return float(max(0, x1 - x0) * max(0, y1 - y0) / (800 * 1280))


def register_home_frame(
    candidate: np.ndarray,
    reference: np.ndarray,
    *,
    maximum_residual_px: float = 4.5,
    minimum_inliers: int = 18,
    minimum_overlap: float = 0.22,
) -> RegistrationResult:
    """Select the simplest transform supported by measured feature residuals."""

    if not native_frame_guard(candidate) or not native_frame_guard(reference):
        return RegistrationResult(False, "none", None, 0.0, math.inf, 0, 0, 0.0, "non_native_frame")
    source, destination, matches = _matched_points(candidate, reference)
    if matches < minimum_inliers:
        return RegistrationResult(False, "none", None, 0.0, math.inf, 0, matches, 0.0, "insufficient_landmarks")

    delta = destination - source
    translation = np.eye(3, dtype=np.float64)
    translation[0, 2], translation[1, 2] = np.median(delta, axis=0)
    translation_residual = _residual(translation, source, destination)
    candidates: list[tuple[str, np.ndarray, float, np.ndarray | None]] = [
        ("translation", translation, translation_residual, np.ones((matches, 1), np.uint8))
    ]

    similarity, similarity_inliers = cv2.estimateAffinePartial2D(
        source, destination, method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=3000, confidence=0.995
    )
    if similarity is not None:
        matrix = np.vstack((similarity, (0.0, 0.0, 1.0)))
        candidates.append(("similarity", matrix, _residual(matrix, source, destination, similarity_inliers), similarity_inliers))
    affine, affine_inliers = cv2.estimateAffine2D(
        source, destination, method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=3000, confidence=0.995
    )
    if affine is not None:
        matrix = np.vstack((affine, (0.0, 0.0, 1.0)))
        candidates.append(("affine", matrix, _residual(matrix, source, destination, affine_inliers), affine_inliers))
    homography, homography_inliers = cv2.findHomography(source, destination, cv2.RANSAC, 4.0, maxIters=3000, confidence=0.995)
    if homography is not None:
        candidates.append(("homography", homography, _residual(homography, source, destination, homography_inliers), homography_inliers))

    # Complexity is admitted only when it materially improves residual.
    selected = candidates[0]
    for item in candidates[1:]:
        if item[2] <= maximum_residual_px and item[2] < selected[2] * 0.72:
            selected = item
    model, matrix, residual, inlier_mask = selected
    inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    overlap = _overlap_ratio(matrix)
    accepted = inliers >= minimum_inliers and residual <= maximum_residual_px and overlap >= minimum_overlap
    confidence = min(1.0, (inliers / max(40, matches)) * max(0.0, 1.0 - residual / 12.0) * min(1.0, overlap / 0.45))
    reason = "accepted" if accepted else "residual_overlap_or_inliers_rejected"
    return RegistrationResult(accepted, model, matrix if accepted else None, confidence, residual, inliers, matches, overlap, reason)


def _matrix_scale(matrix: np.ndarray) -> float:
    return float((np.linalg.norm(matrix[:2, 0]) + np.linalg.norm(matrix[:2, 1])) / 2.0)


_FULLY_ZOOMED_OUT_SCALE_MINIMUM = 0.94
_FULLY_ZOOMED_OUT_SCALE_MAXIMUM = 1.035
_ZOOMED_IN_SCALE_MAXIMUM = 0.91


def _zoom_identity_from_scale(scale: float) -> ZoomIdentity:
    """Classify live BlueStacks scale against the retained fully-out atlas.

    The game clamps a real two-pointer zoom-out at about 0.95 relative to the
    retained atlas captures. Repeated gestures leave that scale unchanged, so
    the fully-out band must include the measured clamp while remaining
    separated from the next observed zoom step.
    """

    if _FULLY_ZOOMED_OUT_SCALE_MINIMUM <= scale <= _FULLY_ZOOMED_OUT_SCALE_MAXIMUM:
        return ZoomIdentity.FULLY_ZOOMED_OUT
    if scale < _ZOOMED_IN_SCALE_MAXIMUM:
        # A larger candidate scene object maps down into the canonical fully-out reference.
        return ZoomIdentity.ZOOMED_IN
    if _ZOOMED_IN_SCALE_MAXIMUM <= scale < _FULLY_ZOOMED_OUT_SCALE_MINIMUM:
        return ZoomIdentity.INTERMEDIATE
    return ZoomIdentity.UNKNOWN


def classify_zoom(
    frame: np.ndarray,
    canonical_reference: np.ndarray,
    *,
    overlay: bool = False,
    loading_or_animation: bool = False,
    clipped_or_translated: bool = False,
) -> ZoomClassification:
    if not native_frame_guard(frame):
        return ZoomClassification(ZoomIdentity.CLIPPED_OR_TRANSLATED, 1.0, None, None, (), "non_native_dimensions")
    if clipped_or_translated:
        return ZoomClassification(ZoomIdentity.CLIPPED_OR_TRANSLATED, 1.0, None, None, (), "clipped_or_translated")
    if overlay:
        return ZoomClassification(ZoomIdentity.OVERLAY, 1.0, None, None, (), "overlay")
    if loading_or_animation:
        return ZoomClassification(ZoomIdentity.LOADING_OR_ANIMATION, 1.0, None, None, (), "loading_or_animation")
    result = register_home_frame(frame, canonical_reference, minimum_overlap=0.12)
    if not result.accepted or result.transform_candidate_to_reference is None:
        return ZoomClassification(ZoomIdentity.UNKNOWN, result.confidence, None, result.residual_px, (), result.reason)
    scale = _matrix_scale(result.transform_candidate_to_reference)
    identity = _zoom_identity_from_scale(scale)
    landmarks = tuple(f"sift-inlier-{index + 1}" for index in range(min(result.inliers, 12)))
    return ZoomClassification(identity, result.confidence, scale, result.residual_px, landmarks, "feature_geometry")


def _as_matrix(matrix: Matrix3) -> np.ndarray:
    return np.asarray(matrix, dtype=np.float64)


def _as_tuple(matrix: np.ndarray) -> Matrix3:
    return tuple(tuple(float(cell) for cell in row) for row in matrix)


def _polygon_from_matrix(matrix: np.ndarray) -> Polygon:
    corners = np.float32([[0, 0], [800, 0], [800, 1280], [0, 1280]])
    return tuple((float(x), float(y)) for x, y in _project(matrix, corners))


class BlueStacksHomeLocalizer:
    def __init__(self, atlas: HomeAtlas, atlas_manifest_path: Path) -> None:
        if atlas.profile.profile_id != BLUESTACKS_PROFILE_ID or atlas.profile.platform != BLUESTACKS_PLATFORM:
            raise ValueError("BlueStacks localizer refuses a non-BlueStacks atlas profile")
        self.atlas = atlas
        self.root = atlas_manifest_path.resolve().parent
        self.references: list[tuple[str, np.ndarray, np.ndarray]] = []
        for viewport in atlas.viewports:
            if not viewport.accepted:
                continue
            image = cv2.imread(str((self.root / viewport.image_path).resolve()), cv2.IMREAD_COLOR)
            if not native_frame_guard(image):
                raise ValueError(f"atlas viewport is missing or non-native: {viewport.image_path}")
            self.references.append((viewport.viewport_id, image, _as_matrix(viewport.transform_to_atlas)))
        if not self.references:
            raise ValueError("atlas contains no accepted BlueStacks viewports")
        self.canonical_reference = self.references[0][1]

    def localize(
        self,
        frame: np.ndarray,
        *,
        timestamp: str | None = None,
        stale: bool = False,
        overlay: bool = False,
        home_recognized: bool = True,
    ) -> LocalizationResult:
        stamp = timestamp or datetime.now(timezone.utc).isoformat()
        digest = frame_digest(frame) if native_frame_guard(frame) else ""
        if not native_frame_guard(frame):
            return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.CLIPPED_OR_TRANSLATED, None, (), 0.0, (), None, AmbiguityState.WRONG_PROFILE, "unknown", digest, stamp)
        if stale:
            return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.UNKNOWN, None, (), 0.0, (), None, AmbiguityState.STALE_FRAME, "unknown", digest, stamp, stale=True)
        if overlay or not home_recognized:
            ambiguity = AmbiguityState.WRONG_SCREEN if not home_recognized else AmbiguityState.NONE
            return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.OVERLAY if overlay else ZoomIdentity.UNKNOWN, None, (), 0.0, (), None, ambiguity, "unknown", digest, stamp, overlay=overlay)

        candidates: list[tuple[float, float, str, np.ndarray, RegistrationResult]] = []
        wrong_zoom_matches: list[tuple[float, float, ZoomIdentity]] = []
        for viewport_id, reference, reference_to_atlas in self.references:
            result = register_home_frame(frame, reference)
            if result.accepted and result.transform_candidate_to_reference is not None:
                scale = _matrix_scale(result.transform_candidate_to_reference)
                zoom_identity = _zoom_identity_from_scale(scale)
                if zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
                    wrong_zoom_matches.append((result.confidence, result.residual_px, zoom_identity))
                    continue
                transform = reference_to_atlas @ result.transform_candidate_to_reference
                candidates.append((result.confidence, result.residual_px, viewport_id, transform, result))
        if not candidates:
            if wrong_zoom_matches:
                wrong_zoom_matches.sort(key=lambda item: (-item[0], item[1]))
                confidence, residual, zoom_identity = wrong_zoom_matches[0]
                return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, zoom_identity, None, (), confidence, (), residual, AmbiguityState.NONE, "unknown", digest, stamp)
            return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.UNKNOWN, None, (), 0.0, (), None, AmbiguityState.INSUFFICIENT_LANDMARKS, "unknown", digest, stamp)
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best = candidates[0]
        if len(candidates) > 1 and candidates[1][0] >= best[0] - 0.04:
            delta = np.linalg.norm(best[3][:2, 2] - candidates[1][3][:2, 2])
            if delta > 28:
                return LocalizationResult(False, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.FULLY_ZOOMED_OUT, None, (), best[0], (best[2], candidates[1][2]), best[1], AmbiguityState.CONFLICTING_TRANSFORMS, "unknown", digest, stamp)
        polygon = _polygon_from_matrix(best[3])
        x0, y0 = min(point[0] for point in polygon), min(point[1] for point in polygon)
        x1, y1 = max(point[0] for point in polygon), max(point[1] for point in polygon)
        edge_parts = []
        if x0 <= 4:
            edge_parts.append("left")
        if y0 <= 4:
            edge_parts.append("top")
        if x1 >= self.atlas.width - 4:
            edge_parts.append("right")
        if y1 >= self.atlas.height - 4:
            edge_parts.append("bottom")
        return LocalizationResult(
            True,
            BLUESTACKS_PLATFORM,
            BLUESTACKS_PROFILE_ID,
            ZoomIdentity.FULLY_ZOOMED_OUT,
            _as_tuple(best[3]),
            polygon,
            best[0],
            tuple(item[2] for item in candidates[:3]),
            best[1],
            AmbiguityState.NONE,
            "+".join(edge_parts) if edge_parts else "interior",
            digest,
            stamp,
        )


def validate_loop_closure(transforms: Iterable[np.ndarray], *, maximum_error_px: float = 12.0) -> tuple[bool, float]:
    matrices = list(transforms)
    if len(matrices) < 2:
        return False, math.inf
    origin = np.float32([[[400.0, 640.0]]])
    points = [cv2.perspectiveTransform(origin, matrix)[0, 0] for matrix in matrices]
    residual = float(max(np.linalg.norm(point - points[0]) for point in points[1:]))
    return residual <= maximum_error_px, residual


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
