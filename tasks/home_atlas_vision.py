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


def _contains_label(text: str, label: str) -> bool:
    """Match a normalized label on token boundaries, including multiword labels."""

    return bool(label) and f" {label} " in f" {text} "


def _project_building(localization: LocalizationResult, building: SemanticBuilding) -> np.ndarray:
    if not localization.recognized or localization.screen_to_atlas is None:
        raise ValueError("building binding requires a recognized current localization")
    inverse = np.linalg.inv(np.asarray(localization.screen_to_atlas, dtype=np.float64))
    points = np.asarray(building.polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, inverse).reshape(-1, 2)


_BINDING_MAX_OCR_CALLS = 2
_BINDING_OCR_TIMEOUT_SECONDS = 15
_LABEL_COMPONENT_THRESHOLDS = (128, 140)
_LABEL_COMPONENT_HORIZONTAL_GAP = 24
_LABEL_COMPONENT_Y_TOLERANCE = 3


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


def _label_line_candidate(
    frame: np.ndarray,
    projected: np.ndarray,
    search: tuple[int, int, int, int],
) -> tuple[
    tuple[int, int, int, int],
    tuple[int, int, int, int],
    tuple[int, int, int, int] | None,
]:
    """Find one complete renderer label line within the projected search area.

    Retained frames place labels at materially different heights relative to a
    building, so segmentation covers the whole projected search rectangle. Two
    fixed, renderer-calibrated luminance
    thresholds make antialiased glyph extents stable without widening the OCR
    search or making spelling part of candidate selection.
    """

    search_x0, search_y0, search_x1, search_y1 = search
    if search_x0 >= search_x1 or search_y0 >= search_y1:
        return search, search, None

    gray = cv2.cvtColor(
        frame[search_y0:search_y1, search_x0:search_x1],
        cv2.COLOR_BGR2GRAY,
    )
    candidates: list[tuple[int, int, int, int, int, int, int]] = []
    for threshold in _LABEL_COMPONENT_THRESHOLDS:
        ink = np.uint8(gray >= threshold) * 255
        ink = cv2.morphologyEx(
            ink,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)),
        )
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            ink,
            8,
        )
        components: list[tuple[int, int, int, int, int]] = []
        for index in range(1, count):
            component_x, component_y, width, height, area = (
                int(value) for value in stats[index]
            )
            if 5 <= height <= 14 and 2 <= width <= 80 and area >= 10:
                components.append(
                    (
                        component_x + search_x0,
                        component_y + search_y0,
                        width,
                        height,
                        area,
                    )
                )
        components.sort(key=lambda item: (item[1], item[0]))
        rows: list[list[tuple[int, int, int, int, int]]] = []
        for component in components:
            center_y = component[1] + component[3] / 2
            row = next(
                (
                    candidate
                    for candidate in rows
                    if abs(
                        center_y
                        - float(
                            np.median(
                                [
                                    item[1] + item[3] / 2
                                    for item in candidate
                                ]
                            )
                        )
                    )
                    <= _LABEL_COMPONENT_Y_TOLERANCE
                ),
                None,
            )
            if row is None:
                rows.append([component])
            else:
                row.append(component)
        for row in rows:
            row.sort(key=lambda item: item[0])
            groups: list[list[tuple[int, int, int, int, int]]] = []
            for component in row:
                if (
                    not groups
                    or component[0]
                    - (groups[-1][-1][0] + groups[-1][-1][2])
                    > _LABEL_COMPONENT_HORIZONTAL_GAP
                ):
                    groups.append([component])
                else:
                    groups[-1].append(component)
            for group in groups:
                text_x0 = min(item[0] for item in group)
                text_y0 = min(item[1] for item in group)
                text_x1 = max(item[0] + item[2] for item in group)
                text_y1 = max(item[1] + item[3] for item in group)
                width = text_x1 - text_x0
                height = text_y1 - text_y0
                if width < 20 or height < 5 or height > 16:
                    continue
                candidates.append(
                    (
                        text_x0,
                        text_y0,
                        text_x1,
                        text_y1,
                        len(group),
                        sum(item[4] for item in group),
                        threshold,
                    )
                )

    if not candidates:
        return search, search, None

    # The same line appears at both thresholds.  Retain the wider, denser
    # extent before ranking, so weak antialiased trailing glyphs are not clipped.
    candidates.sort(
        key=lambda item: (
            item[1],
            item[0],
            -(item[2] - item[0]),
            -item[5],
        )
    )
    unique: list[tuple[int, int, int, int, int, int, int]] = []
    for candidate in candidates:
        if any(
            abs(candidate[1] - prior[1]) <= _LABEL_COMPONENT_Y_TOLERANCE
            and abs(candidate[0] - prior[0]) <= 4
            and abs(candidate[2] - prior[2]) <= 4
            and abs(candidate[3] - prior[3]) <= 4
            for prior in unique
        ):
            continue
        unique.append(candidate)

    px0, _py0 = np.floor(projected.min(axis=0)).astype(int)
    px1, py1 = np.ceil(projected.max(axis=0)).astype(int)
    projected_center_x = (float(px0) + float(px1)) / 2.0

    def candidate_score(
        candidate: tuple[int, int, int, int, int, int, int],
    ) -> tuple[float, float, float, float, float]:
        text_x0, text_y0, text_x1, text_y1, _count, area, _threshold = candidate
        width = text_x1 - text_x0
        height = text_y1 - text_y0
        density = area / float(width * height)
        center_x = (float(text_x0) + float(text_x1)) / 2.0
        return (
            abs(center_x - projected_center_x),
            abs(float(text_y1) - float(py1)),
            -float(min(width, 120)),
            abs(float(height) - 9.0),
            -min(density, 1.0),
        )

    text_x0, text_y0, text_x1, text_y1, _count, _area, _threshold = min(
        unique,
        key=candidate_score,
    )
    text_bounds = (text_x0, text_y0, text_x1, text_y1)
    padded = (
        max(search_x0, text_x0 - 14),
        max(search_y0, text_y0 - 4),
        min(search_x1, text_x1 + 14),
        min(search_y1, text_y1 + 7),
    )
    return text_bounds, padded, text_bounds


def bind_visible_building(
    frame: np.ndarray,
    localization: LocalizationResult,
    building: SemanticBuilding,
    *,
    ocr=None,
    diagnostics: dict[str, object] | None = None,
) -> BuildingBinding | None:
    """Bind an atlas building only after current-frame renderer label proof.

    Projection narrows the current-frame search only. A present renderer-local
    semantic label is still required and the returned interaction ROI must lie
    wholly inside the fixed-HUD-free region.
    """

    if not native_frame_guard(frame):
        _record_binding_diagnostic(
            diagnostics,
            reason="localization_failed",
            predicate="native_frame_guard",
        )
        return None
    if localization.profile_id != BLUESTACKS_PROFILE_ID:
        _record_binding_diagnostic(
            diagnostics,
            reason="localization_failed",
            predicate="profile_id",
            expected_profile_id=BLUESTACKS_PROFILE_ID,
            actual_profile_id=localization.profile_id,
        )
        return None
    current_digest = frame_digest(frame)
    zoom_identity = getattr(localization, "zoom_identity", None)
    if (
        not localization.recognized
        or zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT
        or bool(getattr(localization, "stale", False))
        or bool(getattr(localization, "overlay", False))
    ):
        _record_binding_diagnostic(
            diagnostics,
            reason="localization_failed",
            predicate="canonical_localization_state",
            recognized=bool(localization.recognized),
            zoom_identity=getattr(zoom_identity, "value", zoom_identity),
            stale=bool(getattr(localization, "stale", False)),
            overlay=bool(getattr(localization, "overlay", False)),
        )
        return None
    if localization.frame_sha256 != current_digest:
        _record_binding_diagnostic(
            diagnostics,
            reason="localization_failed",
            predicate="current_frame_digest",
            localization_frame_sha256=localization.frame_sha256,
            current_frame_sha256=current_digest,
        )
        return None
    if not building.interaction_eligible:
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            predicate="interaction_eligible",
            building_id=building.semantic_id,
        )
        return None
    policy = building.platform_binding_policy.get(
        "bluestacks", building.recognition.get("bluestacks", {})
    )
    if not isinstance(policy, dict) or not policy.get("label"):
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            predicate="renderer_label_policy",
            building_id=building.semantic_id,
        )
        return None
    expected = _normalized_label(str(policy["label"]))
    declared_aliases = policy.get("label_aliases", ())
    if not isinstance(declared_aliases, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in declared_aliases
    ):
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            predicate="renderer_label_alias_policy",
            building_id=building.semantic_id,
        )
        return None
    accepted_labels = (expected, *(_normalized_label(item) for item in declared_aliases))
    try:
        projected = _project_building(localization, building)
    except (ValueError, np.linalg.LinAlgError) as exc:
        _record_binding_diagnostic(
            diagnostics,
            reason="localization_failed",
            predicate="project_building",
            error=f"{type(exc).__name__}: {exc}",
        )
        return None
    px0, py0 = np.floor(projected.min(axis=0)).astype(int)
    px1, py1 = np.ceil(projected.max(axis=0)).astype(int)
    search = (
        max(0, px0 - 18),
        max(0, py1 - 75),
        min(800, px1 + 18),
        min(1280, py1 + 45),
    )
    if search[0] >= search[2] or search[1] >= search[3]:
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            predicate="projected_search_bounds",
            projected_polygon=np.asarray(projected, dtype=float).tolist(),
            search_bounds=tuple(int(value) for value in search),
        )
        return None
    line_band, text_crop_bounds, glyph_bounds = _label_line_candidate(
        frame,
        projected,
        tuple(int(value) for value in search),
    )
    if glyph_bounds is None and ocr is None:
        _record_binding_diagnostic(
            diagnostics,
            reason="label_not_read",
            building_id=building.semantic_id,
            expected_label=expected,
            accepted_labels=accepted_labels,
            projected_polygon=np.asarray(projected, dtype=float).tolist(),
            search_bounds=tuple(int(value) for value in search),
            label_band_bounds=tuple(int(value) for value in line_band),
            text_bounds=None,
            glyph_bounds=None,
            ocr_calls=[],
            decisive_predicate={
                "label_band_valid": False,
                "expected_label_present": False,
            },
        )
        return None
    if (
        text_crop_bounds[0] >= text_crop_bounds[2]
        or text_crop_bounds[1] >= text_crop_bounds[3]
    ):
        _record_binding_diagnostic(
            diagnostics,
            reason="label_not_read",
            building_id=building.semantic_id,
            expected_label=expected,
            accepted_labels=accepted_labels,
            projected_polygon=np.asarray(projected, dtype=float).tolist(),
            search_bounds=tuple(int(value) for value in search),
            label_band_bounds=tuple(int(value) for value in line_band),
            text_bounds=tuple(int(value) for value in text_crop_bounds),
            glyph_bounds=None,
            ocr_calls=[],
            decisive_predicate={
                "label_band_valid": False,
                "expected_label_present": False,
            },
        )
        return None
    reader = ocr or (
        lambda image, psm: pytesseract.image_to_string(
            image,
            config=f"--psm {psm}",
            timeout=_BINDING_OCR_TIMEOUT_SECONDS,
        )
    )
    readings: list[dict[str, object]] = []
    matched_label: str | None = None
    image = frame[
        text_crop_bounds[1]:text_crop_bounds[3],
        text_crop_bounds[0]:text_crop_bounds[2],
    ]
    enlarged = cv2.resize(image, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    for psm in (13, 11):
        if len(readings) >= _BINDING_MAX_OCR_CALLS:
            break
        try:
            raw = str(reader(enlarged, psm))
            error = None
        except (OSError, RuntimeError, TimeoutError) as exc:
            raw = ""
            error = f"{type(exc).__name__}: {exc}"
        normalized = _normalized_label(raw)
        matches = tuple(label for label in accepted_labels if _contains_label(normalized, label))
        reading = {
            "psm": psm,
            "variant": "renderer_label_line_bgr",
            "shape": tuple(int(value) for value in enlarged.shape),
            "raw_text": raw,
            "normalized_text": normalized,
            "matched_labels": matches,
        }
        if error is not None:
            reading["error"] = error
        readings.append(reading)
        if matches:
            matched_label = matches[0]
            break
    common_diagnostics = {
        "building_id": building.semantic_id,
        "expected_label": expected,
        "accepted_labels": accepted_labels,
        "projected_polygon": np.asarray(projected, dtype=float).tolist(),
        "search_bounds": tuple(int(value) for value in search),
        "label_band_bounds": tuple(int(value) for value in line_band),
        "text_bounds": tuple(int(value) for value in text_crop_bounds),
        "glyph_bounds": (
            tuple(int(value) for value in glyph_bounds)
            if glyph_bounds is not None
            else None
        ),
        "ocr_calls": readings,
    }
    if matched_label is None:
        _record_binding_diagnostic(
            diagnostics,
            reason="label_not_read",
            **common_diagnostics,
            decisive_predicate={
                "expected_label_present": False,
                "matched_label": None,
            },
        )
        return None
    sx0, sy0, sx1, sy1 = BLUESTACKS_SAFE_INTERACTION_BOX
    ax0, ay0, ax1, ay1 = (
        max(px0, sx0), max(py0, sy0), min(px1, sx1), min(py1, sy1)
    )
    if ax1 - ax0 < 45 or ay1 - ay0 < 45:
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            **common_diagnostics,
            decisive_predicate={
                "expected_label_present": True,
                "matched_label": matched_label,
                "safe_interaction_size": (int(ax1 - ax0), int(ay1 - ay0)),
            },
        )
        return None
    inset_x = min(18, max(6, (ax1 - ax0) // 8))
    inset_y = min(18, max(6, (ay1 - ay0) // 8))
    target = (ax0 + inset_x, ay0 + inset_y, ax1 - inset_x, ay1 - inset_y)
    if target[0] >= target[2] or target[1] >= target[3]:
        _record_binding_diagnostic(
            diagnostics,
            reason="target_unsafe",
            **common_diagnostics,
            decisive_predicate={
                "expected_label_present": True,
                "matched_label": matched_label,
                "target_valid": False,
            },
        )
        return None
    _record_binding_diagnostic(
        diagnostics,
        reason="accepted",
        **common_diagnostics,
        decisive_predicate={
            "expected_label_present": True,
            "matched_label": matched_label,
            "target_valid": True,
            "target_roi": tuple(int(value) for value in target),
        },
    )
    return BuildingBinding(
        building_id=building.semantic_id,
        target_roi=tuple(int(value) for value in target),
        frame_sha256=localization.frame_sha256,
        confidence=min(localization.confidence, building.confidence, 0.98),
        semantic_evidence=(
            f"current-frame OCR: {policy['label']}",
            "atlas-predicted building region",
            "BlueStacks renderer policy",
        ),
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
