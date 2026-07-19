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
import pytesseract

from .home_atlas import (
    AmbiguityState,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    Matrix3,
    Polygon,
    SemanticBuilding,
    ZoomIdentity,
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
    return bool(frame is not None and frame.shape == (1280, 800, 3))


def frame_digest(frame: np.ndarray) -> str:
    ok, payload = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("cannot encode frame for hashing")
    return hashlib.sha256(payload.tobytes()).hexdigest()


def _normalized_label(value: str) -> str:
    return " ".join("".join(character if character.isalnum() else " " for character in value.lower()).split())


def _project_building(localization: LocalizationResult, building: SemanticBuilding) -> np.ndarray:
    if not localization.recognized or localization.screen_to_atlas is None:
        raise ValueError("building binding requires a recognized current localization")
    inverse = np.linalg.inv(np.asarray(localization.screen_to_atlas, dtype=np.float64))
    points = np.asarray(building.polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, inverse).reshape(-1, 2)


def bind_visible_building(
    frame: np.ndarray,
    localization: LocalizationResult,
    building: SemanticBuilding,
    *,
    ocr=None,
) -> BuildingBinding | None:
    """BlueStacks renderer binding for an atlas-predicted building label.

    Projection narrows the current-frame search only.  A present renderer-local
    semantic label is still required and the returned interaction ROI must lie
    wholly inside the fixed-HUD-free region.
    """

    if (
        not native_frame_guard(frame)
        or localization.profile_id != BLUESTACKS_PROFILE_ID
        or localization.frame_sha256 != frame_digest(frame)
        or not building.interaction_eligible
    ):
        return None
    policy = building.platform_binding_policy.get("bluestacks", building.recognition.get("bluestacks", {}))
    if not isinstance(policy, dict) or not policy.get("label"):
        return None
    expected = _normalized_label(str(policy["label"]))
    declared_aliases = policy.get("label_aliases", ())
    if not isinstance(declared_aliases, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in declared_aliases):
        return None
    accepted_labels = (expected, *(_normalized_label(item) for item in declared_aliases))
    projected = _project_building(localization, building)
    px0, py0 = np.floor(projected.min(axis=0)).astype(int)
    px1, py1 = np.ceil(projected.max(axis=0)).astype(int)
    search = (max(0, px0 - 18), max(0, py1 - 75), min(800, px1 + 18), min(1280, py1 + 45))
    if search[0] >= search[2] or search[1] >= search[3]:
        return None
    crop = cv2.cvtColor(frame[search[1]:search[3], search[0]:search[2]], cv2.COLOR_BGR2GRAY)
    threshold = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    reader = ocr or (lambda image, psm: pytesseract.image_to_string(image, config=f"--psm {psm}"))
    readings = []
    for variant in (crop, threshold):
        enlarged = cv2.resize(variant, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        readings.extend(reader(enlarged, psm) for psm in (6, 7, 11, 12))
    text = _normalized_label(" ".join(readings))
    if not any(label in text for label in accepted_labels):
        return None
    sx0, sy0, sx1, sy1 = BLUESTACKS_SAFE_INTERACTION_BOX
    ax0, ay0, ax1, ay1 = max(px0, sx0), max(py0, sy0), min(px1, sx1), min(py1, sy1)
    if ax1 - ax0 < 45 or ay1 - ay0 < 45:
        return None
    inset_x = min(18, max(6, (ax1 - ax0) // 8))
    inset_y = min(18, max(6, (ay1 - ay0) // 8))
    target = (ax0 + inset_x, ay0 + inset_y, ax1 - inset_x, ay1 - inset_y)
    if target[0] >= target[2] or target[1] >= target[3]:
        return None
    return BuildingBinding(
        building_id=building.semantic_id,
        target_roi=tuple(int(value) for value in target),
        frame_sha256=localization.frame_sha256,
        confidence=min(localization.confidence, building.confidence, 0.98),
        semantic_evidence=(f"current-frame OCR: {policy['label']}", "atlas-predicted building region", "BlueStacks renderer policy"),
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
    if 0.965 <= scale <= 1.035:
        identity = ZoomIdentity.FULLY_ZOOMED_OUT
    elif scale < 0.91:
        # A larger candidate scene object maps down into the canonical fully-out reference.
        identity = ZoomIdentity.ZOOMED_IN
    elif 0.91 <= scale < 0.965:
        identity = ZoomIdentity.INTERMEDIATE
    else:
        identity = ZoomIdentity.UNKNOWN
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
                if 0.965 <= scale <= 1.035:
                    zoom_identity = ZoomIdentity.FULLY_ZOOMED_OUT
                elif scale < 0.91:
                    zoom_identity = ZoomIdentity.ZOOMED_IN
                elif scale < 0.965:
                    zoom_identity = ZoomIdentity.INTERMEDIATE
                else:
                    zoom_identity = ZoomIdentity.UNKNOWN
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
