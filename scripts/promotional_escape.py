"""Fail-closed recognition for an isolated game Back arrow on unknown promotions.

This is deliberately an escape-only classifier.  It does not identify the offer, product,
price, reward, or any other control on the page.  Callers must run known-state classifiers
first and use this classifier only as the bounded fallback for a promotional surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

FRAME_WIDTH = 800
FRAME_HEIGHT = 1280
FRAME_SHAPE = (FRAME_HEIGHT, FRAME_WIDTH)
PROMOTIONAL_BACK_TARGET_ROI: Tuple[int, int, int, int] = (45, 5, 130, 60)
PROMOTIONAL_BACK_GEOMETRY = "standard_game_back_arrow"
PROMOTIONAL_STATE = "UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK"
SAFE_PROMOTIONAL_BACK = "SAFE_PROMOTIONAL_BACK"

# These regions are intentionally conservative.  They describe areas that must remain separate
# from the arrow, not areas that are semantically classified or authorized.
PROMOTIONAL_FORBIDDEN_REGIONS: Tuple[Tuple[str, Tuple[int, int, int, int]], ...] = (
    ("offer_tabs", (40, 120, 760, 390)),
    ("reward_tiles", (40, 390, 760, 900)),
    ("confirmation_controls", (0, 880, 800, 1280)),
    ("price_purchase_controls", (40, 950, 760, 1260)),
    ("premium_currency_controls", (500, 0, 800, 120)),
)


@dataclass(frozen=True)
class PromotionalBackDecision:
    state: str
    recognized: bool
    target_roi: Tuple[int, int, int, int]
    target_identity: Optional[str]
    control_class: Optional[str]
    source_family: str
    overlay_state: str
    consequence: str
    cost_type: str
    cost_amount: float
    quantity: int
    expected_postcondition: str
    arrow_geometry: str
    target_isolated: bool
    forbidden_region_intersects_target: bool
    forbidden_regions: Tuple[Tuple[str, Tuple[int, int, int, int]], ...]
    arrow_similarity: float
    arrow_component: Optional[Tuple[int, int, int, int, int]]
    arrow_contrast: float
    denial_rules: Tuple[str, ...]
    reason: str
    package_foreground: bool
    os_surface: bool
    hard_stop_detected: bool

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _valid_frame(frame: np.ndarray) -> bool:
    return isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.shape == (1280, 800, 3)


def _crop(frame: np.ndarray, roi: Tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def _similarity(candidate: np.ndarray, reference: np.ndarray) -> float:
    if candidate.shape != reference.shape:
        return 0.0
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    pixel = 1.0 - float(np.mean(cv2.absdiff(candidate_gray, reference_gray))) / 255.0
    candidate_edge = cv2.Canny(candidate_gray, 80, 180)
    reference_edge = cv2.Canny(reference_gray, 80, 180)
    edge = 1.0 - float(np.mean(cv2.absdiff(candidate_edge, reference_edge))) / 255.0
    return round(max(0.0, min(1.0, 0.70 * pixel + 0.30 * edge)), 6)


def _component_metrics(roi: np.ndarray) -> Tuple[Optional[Tuple[int, int, int, int, int]], float]:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    mask = (gray >= 180).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates = []
    for raw in stats[1:count]:
        x, y, width, height, area = (int(item) for item in raw)
        if 50 <= width <= 70 and 32 <= height <= 45 and 600 <= area <= 1100:
            candidates.append((x, y, width, height, area))
    if not candidates:
        return None, 0.0
    component = max(candidates, key=lambda item: item[4])
    x, y, width, height, _area = component
    component_mask = mask[y : y + height, x : x + width].astype(bool)
    component_pixels = gray[y : y + height, x : x + width]
    foreground = float(component_pixels[component_mask].mean()) if component_mask.any() else 0.0
    background_values = component_pixels[~component_mask]
    background = float(background_values.mean()) if background_values.size else 0.0
    return component, round(foreground - background, 3)


def _intersects(first: Tuple[int, int, int, int], second: Tuple[int, int, int, int]) -> bool:
    return not (first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1] or second[3] <= first[1])


def classify_promotional_back(
    frame: np.ndarray,
    arrow_reference: np.ndarray,
    *,
    package_foreground: bool = True,
    os_surface: bool = False,
    hard_stop_detected: bool = False,
    unknown_overlay_intersects_target: bool = False,
    forbidden_regions: Tuple[Tuple[str, Tuple[int, int, int, int]], ...] = PROMOTIONAL_FORBIDDEN_REGIONS,
    similarity_threshold: float = 0.82,
) -> PromotionalBackDecision:
    """Recognize only a standard, isolated, fully visible game Back arrow."""
    target = PROMOTIONAL_BACK_TARGET_ROI
    reasons = []
    valid = _valid_frame(frame) and _valid_frame(arrow_reference)
    if not valid:
        reasons.append("INVALID_FRAME")
        similarity = 0.0
        component = None
        contrast = 0.0
    else:
        candidate_roi = _crop(frame, target)
        reference_roi = _crop(arrow_reference, target)
        similarity = _similarity(candidate_roi, reference_roi)
        component, contrast = _component_metrics(candidate_roi)
        if similarity < similarity_threshold:
            reasons.append("ARROW_SHAPE_MISMATCH")
        if component is None:
            reasons.append("ARROW_MISSING_OR_GEOMETRY_MISMATCH")
        if contrast < 80.0:
            reasons.append("ARROW_CONTRAST_INSUFFICIENT")

    intersects = any(_intersects(target, roi) for _name, roi in forbidden_regions)
    if intersects:
        reasons.append("FORBIDDEN_REGION_INTERSECTS_TARGET")
    if unknown_overlay_intersects_target:
        reasons.append("UNKNOWN_OVERLAY_INTERSECTS_TARGET")
    if not package_foreground:
        reasons.append("PACKAGE_NOT_FOREGROUND")
    if os_surface:
        reasons.append("OS_SURFACE")
    if hard_stop_detected:
        reasons.append("ACCOUNT_OR_SESSION_HARD_STOP")

    recognized = not reasons
    return PromotionalBackDecision(
        state=PROMOTIONAL_STATE if recognized else "UNKNOWN",
        recognized=recognized,
        target_roi=target,
        target_identity="standard-game-back-arrow" if recognized else None,
        control_class=SAFE_PROMOTIONAL_BACK if recognized else None,
        source_family="promotional",
        overlay_state="promotional_unknown_nonintersecting" if recognized else "unknown",
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="recognized_navigation_state",
        arrow_geometry=PROMOTIONAL_BACK_GEOMETRY if component is not None else "unknown",
        target_isolated=not intersects,
        forbidden_region_intersects_target=intersects,
        forbidden_regions=forbidden_regions,
        arrow_similarity=similarity,
        arrow_component=component,
        arrow_contrast=contrast,
        denial_rules=tuple(reasons),
        reason=("isolated standard game Back arrow recognized; page semantics intentionally remain unknown"
                if recognized else ";".join(reasons)),
        package_foreground=package_foreground,
        os_surface=os_surface,
        hard_stop_detected=hard_stop_detected,
    )


def annotate_promotional_back(
    frame: np.ndarray,
    decision: PromotionalBackDecision,
) -> np.ndarray:
    """Return a review annotation; it does not authorize or dispatch input."""
    result = frame.copy()
    x0, y0, x1, y1 = decision.target_roi
    cv2.rectangle(result, (x0, y0), (x1, y1), (0, 255, 0), 3)
    for name, (fx0, fy0, fx1, fy1) in decision.forbidden_regions:
        cv2.rectangle(result, (fx0, fy0), (fx1, fy1), (0, 0, 255), 2)
        cv2.putText(result, name, (fx0 + 4, max(18, fy0 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    return result
