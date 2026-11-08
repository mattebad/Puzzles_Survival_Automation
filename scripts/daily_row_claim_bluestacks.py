"""Native BlueStacks binding for the canonical Daily rewards service route.

The route visits Home -> Quest -> Daily, performs at most one aggregate
Claim for an identified ready batch, then individually claims glowing chests.
An explicit same-slot Claimed label proves chest success. Runtime capture
and transport are supplied by the fixed service binding.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeBox
from scripts.bounded_tesseract import call_ocr, tesseract_data
from tasks.available_daily_claim import (
    AvailableDailyClaimObservation,
    available_daily_claim_authorizeable,
)
from tasks.activity_milestones import ACTIVITY_MILESTONE_TARGET
from tasks.home_nav_recognition import recognize_home_nav
from scripts.world_map_navigation_bluestacks import (
    _visual_popup_panel_candidates as _accepted_visual_popup_panel_candidates,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
EXPECTED_PACKAGE = "com.global.ztmslg"
QUEST_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
DAILY_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
FULL_FRAME_SEARCH_ROI: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

HOME_STATE = "HOME"
QUEST_STATE = "QUEST"
DAILY_SELECTED_STATE = "DAILY_SELECTED"
UNKNOWN_STATE = "UNKNOWN"
DAILY_CLAIM_TARGET_IDENTITY = "daily-quest-claim"
BLUESTACKS_TARGET_PROVENANCE = "bluestacks-native"
BLUESTACKS_RUNTIME_PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
DAILY_CLAIM_CONSEQUENCE_CLASS = "ordinary_development"
DAILY_CLAIM_ACTION_CLASS = "reward_claim"
DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS = 0.25
DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS = 20
RESET_DEADLINE_TOLERANCE_SECONDS = 2

# The Daily action column is stable on the native BlueStacks profile.  Gold
# Claim bodies are separated from red Go controls by hue; no stylized Claim
# OCR is needed for the actionable binding.
CLAIM_BUTTON_COLUMN = (560, 780)
CLAIM_SCAN_TOP_Y = 440
CLAIM_HUE_RANGE = (10, 22)
CLAIM_MIN_SAT = 120
CLAIM_MIN_VAL = 140
CLAIM_MIN_WIDTH = 60
CLAIM_MIN_HEIGHT = 25

HOME_QUEST_IDENTITY = "home-quest-entry"
QUEST_DAILY_IDENTITY = "quest-daily-tab"
NAVIGATION_ACTION_CLASS = "navigation"
NAVIGATION_CONSEQUENCE_CLASS = "navigation_only"
SUCCESSOR_POLL_TIMEOUT_SECONDS = 5.0
SUCCESSOR_POLL_INTERVAL_SECONDS = 0.25
SUCCESSOR_POLL_MAX_ATTEMPTS = 20

_HOME_WORDS = frozenset({"quest", "world", "hero", "bag", "mail", "alliance", "more"})
_OVERLAY_MARKERS = frozenset(
    {"loading", "retry", "cancel", "confirm", "purchase", "payment", "popup", "captcha"}
)
DAILY_MILESTONE_CHEST_TARGET_IDENTITY = ACTIVITY_MILESTONE_TARGET
DAILY_MILESTONE_SLOT_COUNT = 5
DAILY_MILESTONE_GLOW_HUE_RANGE = (12, 48)
DAILY_MILESTONE_GLOW_MIN_SAT = 120
DAILY_MILESTONE_GLOW_MIN_VAL = 190
DAILY_MILESTONE_GLOW_READY_PIXELS = 600
DAILY_MILESTONE_GLOW_READY_COMPONENT = 250
DAILY_MILESTONE_GLOW_ABSENT_PIXELS = 300
DAILY_MILESTONE_GLOW_ABSENT_COMPONENT = 80


def _daily_milestone_unknown_scan(
    *,
    reason: str,
    source_frame_sha256: str | None,
    points: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason": reason,
        "source_frame_sha256": source_frame_sha256,
        "slot_count": DAILY_MILESTONE_SLOT_COUNT,
        "observed_chest_count": 0,
        "ready_chest_count": 0,
        "unclaimed_ready_chest_count": 0,
        "points": points,
        "milestones": tuple(
            {
                "slot_index": slot,
                "milestone_key": f"daily-milestone-slot-{slot}",
                "target_identity": DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                "target_roi": None,
                "milestone_state": "unknown",
                "milestone_ready": None,
                "glow_pixel_count": None,
                "largest_glow_component": None,
            }
            for slot in range(1, DAILY_MILESTONE_SLOT_COUNT + 1)
        ),
    }

_MILESTONE_MARKERS = frozenset({"milestone", "chest"})


class DailyRowClaimRecognitionError(RuntimeError):
    """Raised when a bounded route cannot prove a required recognition."""


class RuntimeLike(Protocol):
    execute: bool
    session: Any

    def capture(self, label: str) -> CapturedNativeFrame: ...

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        action_class: str = NAVIGATION_ACTION_CLASS,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None: ...



class SessionLike(Protocol):
    input_count: int
    actions: list[dict[str, Any]]
    terminal_status: str | None
    blocker: str | None
    next_action: str | None
    session_directory: Any

    def observe(
        self,
        capture: Callable[[str], CapturedNativeFrame],
        *,
        label: str,
    ) -> CapturedNativeFrame: ...

    def run_action(self, **kwargs: Any) -> Any: ...


class _NativeTapDispatch:
    """Keep receipt reservation ownership with the native runtime tap."""

    def __init__(self, callback: Callable[[CapturedNativeFrame], None]) -> None:
        self._callback = callback

    def _authorize_dispatch(self) -> None:
        # DevelopmentSession uses this marker to avoid a second generic
        # delegated reservation.  LocalBlueStacksRuntime.tap performs the
        # actual current-frame and receipt-bound authorization.
        return None

    def dispatch(self, source: CapturedNativeFrame) -> None:
        self._callback(source)


@dataclass(frozen=True)
class OCRToken:
    text: str
    roi: NativeBox
    confidence: float | None = None


@dataclass(frozen=True)
class FrameRecognition:
    state: str
    recognized: bool
    target_identity: str | None = None
    target_roi: NativeBox | None = None
    ocr_text: str = ""
    visual_evidence: Mapping[str, Any] | None = None
    reason: str | None = None
    tokens: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _clamp_roi(roi: Sequence[int]) -> NativeBox | None:
    if len(roi) != 4:
        return None
    x0, y0, x1, y1 = (int(value) for value in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(NATIVE_WIDTH, x1), min(NATIVE_HEIGHT, y1)
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        return None
    return (x0, y0, x1, y1)


def _default_ocr(image: np.ndarray) -> Mapping[str, Sequence[object]]:
    return call_ocr(tesseract_data, image, config="--psm 11")


def _ocr_tokens(
    frame: np.ndarray,
    roi: NativeBox,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[OCRToken, ...]:
    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return ()
    scale = 2.0
    enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    data = ocr(enlarged)
    texts = data.get("text", ())
    lefts = data.get("left", ())
    tops = data.get("top", ())
    widths = data.get("width", ())
    heights = data.get("height", ())
    confidences = data.get("conf", ())
    count = min(len(texts), len(lefts), len(tops), len(widths), len(heights))
    tokens: list[OCRToken] = []
    for index in range(count):
        text = _normalize_text(texts[index])
        if not text:
            continue
        try:
            left = round(float(lefts[index]) / scale) + x0
            top = round(float(tops[index]) / scale) + y0
            width = round(float(widths[index]) / scale)
            height = round(float(heights[index]) / scale)
            confidence = (
                float(confidences[index])
                if index < len(confidences) and str(confidences[index]).strip()
                else None
            )
        except (TypeError, ValueError):
            continue
        token_roi = _clamp_roi((left, top, left + width, top + height))
        if token_roi is None:
            continue
        tokens.append(OCRToken(text=text, roi=token_roi, confidence=confidence))
    return tuple(tokens)


def _token_rows(tokens: Sequence[OCRToken]) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "text": token.text,
            "roi": token.roi,
            "confidence": token.confidence,
        }
        for token in tokens
    )


def _frame_shape_ok(frame: np.ndarray) -> bool:
    return frame.shape == (NATIVE_HEIGHT, NATIVE_WIDTH, 3)


def _visual_button_evidence(frame: np.ndarray, target: NativeBox) -> dict[str, Any]:
    x0, y0, x1, y1 = target
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return {"recognized": False, "edge_ratio": 0.0, "accent_ratio": 0.0}
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    accent = cv2.inRange(hsv, (0, 45, 70), (179, 255, 255))
    edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
    accent_ratio = float(np.count_nonzero(accent)) / float(accent.size)
    # Text plus a bounded button/icon patch is the minimum independent
    # structural evidence.  The target is always derived from this frame's
    # OCR box; these are not retained coordinates.
    recognized = bool(edge_ratio >= 0.004 or accent_ratio >= 0.025)
    return {
        "recognized": recognized,
        "edge_ratio": round(edge_ratio, 6),
        "accent_ratio": round(accent_ratio, 6),
    }


def _bind_text_target(
    frame: np.ndarray,
    token: OCRToken,
    *,
    identity: str,
    min_y: int,
    max_y: int,
) -> tuple[NativeBox | None, dict[str, Any]]:
    tx0, ty0, tx1, ty1 = token.roi
    center_y = (ty0 + ty1) // 2
    if not (min_y <= center_y <= max_y):
        return None, {"recognized": False, "reason": "token_outside_structural_region"}
    padding_x = max(18, min(80, (tx1 - tx0) * 2))
    padding_y = max(16, min(48, (ty1 - ty0) * 2))
    target = _clamp_roi((tx0 - padding_x, ty0 - padding_y, tx1 + padding_x, ty1 + padding_y))
    if target is None:
        return None, {"recognized": False, "reason": "target_out_of_bounds"}
    visual = _visual_button_evidence(frame, target)
    details = {
        "recognized": bool(visual["recognized"]),
        "target_identity": identity,
        "target_roi": target,
        "ocr_roi": token.roi,
        "visual": visual,
    }
    return (target if visual["recognized"] else None), details


def _home_navigation_geometry(
    tokens: Sequence[OCRToken],
    quest: OCRToken,
) -> dict[str, Any] | None:
    """Derive the current Quest lane and icon band from navigation labels."""

    quest_x0, quest_y0, quest_x1, quest_y1 = quest.roi
    quest_center_x = (quest_x0 + quest_x1) // 2
    quest_center_y = (quest_y0 + quest_y1) // 2
    quest_height = quest_y1 - quest_y0
    if quest_x0 >= quest_x1 or quest_y0 >= quest_y1 or quest_height <= 0:
        return None

    labels: list[OCRToken] = []
    row_tolerance = max(12, min(36, quest_height * 2))
    for candidate in tokens:
        if (
            candidate is quest
            or candidate.roi == quest.roi
            or candidate.text not in (_HOME_WORDS - {"quest"})
        ):
            continue
        cx0, cy0, cx1, cy1 = candidate.roi
        center_x = (cx0 + cx1) // 2
        center_y = (cy0 + cy1) // 2
        if (
            cx0 >= cx1
            or cy0 >= cy1
            or abs(center_y - quest_center_y) > row_tolerance
            or center_x == quest_center_x
        ):
            continue
        labels.append(candidate)

    left = [candidate for candidate in labels if (candidate.roi[0] + candidate.roi[2]) // 2 < quest_center_x]
    right = [candidate for candidate in labels if (candidate.roi[0] + candidate.roi[2]) // 2 > quest_center_x]

    left.sort(key=lambda candidate: (candidate.roi[0] + candidate.roi[2]) // 2, reverse=True)
    right.sort(key=lambda candidate: (candidate.roi[0] + candidate.roi[2]) // 2)
    left_label: OCRToken | None = None
    right_label: OCRToken | None = None
    navigation_evidence = "two_sided_adjacent_labels"
    if left and right:
        if (
            len(left) > 1
            and (left[0].roi[0] + left[0].roi[2]) // 2
            == (left[1].roi[0] + left[1].roi[2]) // 2
        ) or (
            len(right) > 1
            and (right[0].roi[0] + right[0].roi[2]) // 2
            == (right[1].roi[0] + right[1].roi[2]) // 2
        ):
            return None
        left_label, right_label = left[0], right[0]
        left_center_x = (left_label.roi[0] + left_label.roi[2]) // 2
        right_center_x = (right_label.roi[0] + right_label.roi[2]) // 2
        if not (left_center_x < quest_center_x < right_center_x):
            return None
        lane_left = (left_center_x + quest_center_x) // 2
        lane_right = (quest_center_x + right_center_x + 1) // 2
    elif not left and len(right) >= 3:
        # The fresh Home frame missed Hero but retained the exact ordered
        # Bag -> Mail -> More chain.  Do not generalize this to arbitrary
        # recognized navigation words or an extra-label chain.
        right_chain = tuple(
            candidate
            for candidate in right
            if candidate.text in {"bag", "mail", "more"}
        )
        if (
            len(right) != 3
            or len(right_chain) != 3
            or tuple(candidate.text for candidate in right_chain)
            != ("bag", "mail", "more")
        ):
            return None
        right_centers = tuple(
            (candidate.roi[0] + candidate.roi[2]) // 2 for candidate in right_chain
        )
        if len(set(right_centers)) != len(right_centers):
            return None
        adjacent_gap_limit = max(192, quest_height * 6)
        gaps = (
            right_centers[0] - quest_center_x,
            right_centers[1] - right_centers[0],
            right_centers[2] - right_centers[1],
        )
        if any(gap <= 0 or gap > adjacent_gap_limit for gap in gaps):
            return None
        right_label = right_chain[0]
        navigation_evidence = "right_side_label_chain"
        # Reflect the measured Quest-to-Bag gap to retain a Quest-local lane
        # without inventing a fixed coordinate or accepting Quest text alone.
        lane_left = (quest_center_x * 3 - right_centers[0]) // 2
        lane_right = (quest_center_x + right_centers[0] + 1) // 2
    else:
        return None

    if lane_right - lane_left < 12:
        return None

    band_height = max(48, quest_height * 4)
    icon_band = _clamp_roi(
        (
            lane_left,
            max(0, quest_y0 - band_height),
            lane_right,
            quest_y0,
        )
    )
    if icon_band is None:
        return None
    return {
        "quest_ocr_roi": quest.roi,
        "quest_center": (quest_center_x, quest_center_y),
        "left_label": left_label,
        "right_label": right_label,
        "left_label_center": (
            (left_label.roi[0] + left_label.roi[2]) // 2,
            (left_label.roi[1] + left_label.roi[3]) // 2,
        )
        if left_label is not None
        else None,
        "right_label_center": (
            (right_label.roi[0] + right_label.roi[2]) // 2,
            (right_label.roi[1] + right_label.roi[3]) // 2,
        )
        if right_label is not None
        else None,
        "navigation_evidence": navigation_evidence,
        "ownership_lane": (lane_left, lane_right),
        "icon_band": icon_band,
    }


def _home_support_mask(frame: np.ndarray, roi: NativeBox) -> np.ndarray:
    """Build the raw color/brightness support mask for one current-frame ROI."""

    x0, y0, x1, y1 = roi
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return np.zeros((0, 0), dtype=np.uint8)
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    saturated = cv2.inRange(hsv, (0, 60, 45), (179, 255, 255))
    # The retained Home frame has a low-value, moderately saturated
    # navigation-bar background that joins neighboring controls.  Exclude
    # only that band; brighter muted icon pixels and neutral details remain
    # accepted by the original thresholds.
    low_value_navigation = cv2.inRange(hsv, (0, 60, 45), (179, 119, 154))
    saturated = cv2.bitwise_and(saturated, cv2.bitwise_not(low_value_navigation))
    bright_neutral = cv2.inRange(hsv, (0, 0, 155), (179, 85, 255))
    # This mask is intentionally never closed, opened, dilated, or otherwise
    # changed.  Only pixels present in this raw mask may authorize a target.
    return cv2.bitwise_or(saturated, bright_neutral)


def _home_component_records_for_mask(
    frame: np.ndarray,
    geometry: Mapping[str, Any],
    candidate_mask: np.ndarray,
    support_mask: np.ndarray,
) -> tuple[dict[str, Any], ...]:
    """Return candidate-mask components with raw support-point gates."""

    icon_band = geometry["icon_band"]
    lane_left, lane_right = geometry["ownership_lane"]
    quest_center_x = geometry["quest_center"][0]
    quest_width = geometry["quest_ocr_roi"][2] - geometry["quest_ocr_roi"][0]
    quest_height = geometry["quest_ocr_roi"][3] - geometry["quest_ocr_roi"][1]
    if candidate_mask.size == 0:
        return ()

    count, component_labels, stats, _ = cv2.connectedComponentsWithStats(candidate_mask, 8)
    band_height, band_width = candidate_mask.shape
    minimum_dimension = max(10, quest_height // 2)
    records: list[dict[str, Any]] = []
    for component_id in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[component_id])
        reason: str | None = None
        if x <= 0 or y <= 0 or x + width >= band_width or y + height >= band_height:
            reason = "component_touches_icon_band_boundary"
        elif width < minimum_dimension or height < minimum_dimension or area < 80:
            reason = "component_too_small"
        elif width >= max(12, int(round(band_width * 0.85))) or height >= max(
            12, int(round(band_height * 0.95))
        ):
            reason = "broad_or_background_like_component"

        component_roi = (
            icon_band[0] + x,
            icon_band[1] + y,
            icon_band[0] + x + width,
            icon_band[1] + y + height,
        )
        component_center_x = icon_band[0] + x + (width - 1) / 2.0
        association_limit = max(12.0, quest_width * 0.75, band_width * 0.35)
        if reason is None and abs(component_center_x - quest_center_x) > association_limit:
            reason = "component_lacks_quest_horizontal_association"
        if reason is None and not (
            lane_left <= component_center_x < lane_right
            and icon_band[0] <= component_roi[0] < component_roi[2] <= icon_band[2]
        ):
            reason = "component_outside_quest_lane_or_icon_band"
        if reason is not None:
            continue

        component_mask = np.where(component_labels == component_id, 255, 0).astype(np.uint8)
        clearance_map = cv2.distanceTransform(component_mask, cv2.DIST_L2, 5)
        maximum_clearance = float(clearance_map.max())
        if maximum_clearance <= 0.0:
            continue
        max_points = np.argwhere(
            np.isclose(clearance_map, maximum_clearance, rtol=0.0, atol=1e-6)
        )
        selected_point: tuple[int, int] | None = None
        for point_y, point_x in max_points:
            if point_y <= 0 or point_x <= 0 or point_y >= band_height - 1 or point_x >= band_width - 1:
                continue
            neighborhood = support_mask[point_y - 1 : point_y + 2, point_x - 1 : point_x + 2]
            if neighborhood.shape == (3, 3) and bool(np.all(neighborhood != 0)):
                selected_point = (
                    icon_band[0] + int(point_x),
                    icon_band[1] + int(point_y),
                )
                break
        if selected_point is None:
            continue

        records.append(
            {
                "component_roi": component_roi,
                "component_area": area,
                "selected_point": selected_point,
                "clearance": round(maximum_clearance, 6),
                "raw_support_result": {
                    "supported_pixel": True,
                    "complete_3x3": True,
                    "neighborhood_pixels": 9,
                },
            }
        )
    return tuple(records)


def _home_component_records(
    frame: np.ndarray,
    geometry: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return one supported component from the current-frame icon band."""

    support_mask = _home_support_mask(frame, geometry["icon_band"])
    records = _home_component_records_for_mask(frame, geometry, support_mask, support_mask)
    if records:
        return records

    # A low-value navigation background can still connect the retained
    # support pixels.  Re-evaluate only with a raw, high-saturation icon mask;
    # the selected point must still be present in the original support mask.
    hsv = cv2.cvtColor(
        frame[geometry["icon_band"][1] : geometry["icon_band"][3],
              geometry["icon_band"][0] : geometry["icon_band"][2]],
        cv2.COLOR_BGR2HSV,
    )
    icon_core = cv2.inRange(hsv, (0, 120, 60), (179, 255, 255))
    return _home_component_records_for_mask(frame, geometry, icon_core, support_mask)


def _home_visual_components(
    frame: np.ndarray,
    token: OCRToken,
    navigation_tokens: Sequence[OCRToken] | None = None,
) -> tuple[NativeBox, ...]:
    """Find current-frame components in the Quest-relative icon band."""

    geometry = _home_navigation_geometry(navigation_tokens or (), token)
    if geometry is None:
        return ()
    return tuple(record["component_roi"] for record in _home_component_records(frame, geometry))


def _bind_home_quest_target(
    frame: np.ndarray,
    token: OCRToken,
    navigation_tokens: Sequence[OCRToken] | None = None,
) -> tuple[NativeBox | None, dict[str, Any]]:
    """Bind Home Quest to one maximum-clearance raw-supported point."""

    geometry = _home_navigation_geometry(navigation_tokens or (), token)
    records = _home_component_records(frame, geometry) if geometry is not None else ()
    components = tuple(record["component_roi"] for record in records)
    details: dict[str, Any] = {
        "recognized": False,
        "target_identity": HOME_QUEST_IDENTITY,
        "ocr_roi": token.roi,
        "component_count": len(components),
        "components": components,
    }
    if geometry is None:
        details["reason"] = "quest_and_adjacent_navigation_labels_not_proven"
        return None, details
    details.update(
        {
            "quest_ocr_roi": geometry["quest_ocr_roi"],
            "ownership_lane": geometry["ownership_lane"],
            "icon_band": geometry["icon_band"],
            "left_label_roi": (
                geometry["left_label"].roi if geometry["left_label"] is not None else None
            ),
            "right_label_roi": (
                geometry["right_label"].roi if geometry["right_label"] is not None else None
            ),
            "left_label_center": geometry["left_label_center"],
            "right_label_center": geometry["right_label_center"],
            "navigation_evidence": geometry["navigation_evidence"],
        }
    )
    if len(components) == 0:
        details["reason"] = "no_unique_home_quest_visual_component"
        return None, details
    if len(components) != 1:
        details["reason"] = "ambiguous_home_quest_visual_components"
        return None, details

    record = records[0]
    selected_x, selected_y = record["selected_point"]
    target = _clamp_roi((selected_x - 1, selected_y - 1, selected_x + 2, selected_y + 2))
    if target is None or target[2] - target[0] != 3 or target[3] - target[1] != 3:
        details["reason"] = "home_quest_supported_point_out_of_bounds"
        return None, details
    details.update(
        {
            "recognized": True,
            "target_roi": target,
            "component_roi": record["component_roi"],
            "selected_point": record["selected_point"],
            "clearance": record["clearance"],
            "raw_support_result": record["raw_support_result"],
        }
    )
    return target, details


def _contains_overlay_marker(tokens: Sequence[OCRToken]) -> bool:
    words = {word for token in tokens for word in token.text.split()}
    return bool(words & _OVERLAY_MARKERS)


def _full_frame_overlay_markers(
    frame: np.ndarray,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[str, ...]:
    """Reject explicit modal markers found anywhere in the current frame."""

    tokens = _ocr_tokens(frame, FULL_FRAME_SEARCH_ROI, ocr)
    words = {word for token in tokens for word in token.text.split()}
    return tuple(sorted(words & _OVERLAY_MARKERS))


def _tab_visual_score(frame: np.ndarray, token: OCRToken) -> float:
    x0, y0, x1, y1 = token.roi
    roi = _clamp_roi((x0 - 20, y0 - 12, x1 + 20, y1 + 28))
    if roi is None:
        return 0.0
    rx0, ry0, rx1, ry1 = roi
    patch = frame[ry0:ry1, rx0:rx1]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1])) / 255.0
    value = float(np.mean(hsv[:, :, 2])) / 255.0
    edges = cv2.Canny(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 60, 160)
    edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
    return round(0.55 * saturation + 0.30 * value + 0.15 * min(edge_ratio * 8.0, 1.0), 6)


def _quest_page_semantics(
    tokens: Sequence[OCRToken],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Prove the current Quest page from spatially related tab/list labels."""

    daily_candidates = [token for token in tokens if token.text == "daily"]
    quest_candidates = [token for token in tokens if token.text == "quest"]
    alliance_candidates = [token for token in tokens if token.text == "alliance"]
    activity_candidates = [token for token in tokens if token.text == "activity"]
    context_candidates = [
        token
        for token in tokens
        if token.text in {"recom d", "recommend"}
    ]
    details: dict[str, Any] = {
        "daily_candidates": tuple(token.roi for token in daily_candidates),
        "quest_candidates": tuple(token.roi for token in quest_candidates),
        "alliance_candidates": tuple(token.roi for token in alliance_candidates),
        "activity_candidates": tuple(token.roi for token in activity_candidates),
        "context_candidates": tuple(token.roi for token in context_candidates),
    }

    def fail(reason: str) -> tuple[None, dict[str, Any]]:
        details["recognized"] = False
        details["reason"] = reason
        return None, details

    if len(daily_candidates) != 1:
        return fail("daily-target-is-missing-or-ambiguous")
    if len(alliance_candidates) != 1 or len(activity_candidates) != 1:
        return fail("alliance-activity-context-is-missing-or-ambiguous")
    if len(context_candidates) != 1:
        return fail("recommendation-context-is-missing-or-ambiguous")

    daily = daily_candidates[0]
    alliance = alliance_candidates[0]
    activity = activity_candidates[0]
    context = context_candidates[0]
    daily_x0, daily_y0, daily_x1, daily_y1 = daily.roi
    daily_center_y = (daily_y0 + daily_y1) / 2.0
    daily_height = daily_y1 - daily_y0

    adjacent_quests: list[OCRToken] = []
    for quest in quest_candidates:
        quest_x0, quest_y0, quest_x1, quest_y1 = quest.roi
        quest_center_y = (quest_y0 + quest_y1) / 2.0
        quest_height = quest_y1 - quest_y0
        row_tolerance = max(16.0, 1.25 * max(daily_height, quest_height))
        horizontal_gap = quest_x0 - daily_x1
        max_horizontal_gap = max(48.0, 2.5 * max(daily_height, quest_height))
        if (
            horizontal_gap >= 0
            and horizontal_gap <= max_horizontal_gap
            and abs(quest_center_y - daily_center_y) <= row_tolerance
        ):
            adjacent_quests.append(quest)
    if len(adjacent_quests) != 1:
        return fail("daily-quest-tab-phrase-is-missing-or-ambiguous")
    quest = adjacent_quests[0]

    quest_x0, quest_y0, quest_x1, quest_y1 = quest.roi
    quest_center_x = (quest_x0 + quest_x1) / 2.0
    quest_center_y = (quest_y0 + quest_y1) / 2.0
    quest_height = quest_y1 - quest_y0
    alliance_x0, alliance_y0, alliance_x1, alliance_y1 = alliance.roi
    activity_x0, activity_y0, activity_x1, activity_y1 = activity.roi
    alliance_center_x = (alliance_x0 + alliance_x1) / 2.0
    alliance_center_y = (alliance_y0 + alliance_y1) / 2.0
    activity_center_x = (activity_x0 + activity_x1) / 2.0
    activity_center_y = (activity_y0 + activity_y1) / 2.0
    tab_height = max(
        daily_height,
        quest_height,
        alliance_y1 - alliance_y0,
        activity_y1 - activity_y0,
    )
    if (
        alliance_x0 <= quest_x1
        or activity_x0 <= quest_x1
        or abs(alliance_center_x - activity_center_x) > max(36.0, tab_height)
        or activity_y0 < alliance_y1
        or activity_y0 - alliance_y1 > max(64.0, 3.0 * tab_height)
        or activity_center_y <= alliance_center_y
    ):
        return fail("alliance-activity-tab-phrase-is-spatially-disassociated")

    context_x0, context_y0, context_x1, context_y1 = context.roi
    context_center_x = (context_x0 + context_x1) / 2.0
    context_center_y = (context_y0 + context_y1) / 2.0
    lower_tab_edge = max(daily_y1, quest_y1, alliance_y1, activity_y1)
    context_gap = context_center_y - lower_tab_edge
    if (
        context_gap < max(10.0, (context_y1 - context_y0) / 2.0)
        or context_gap > max(80.0, 4.0 * tab_height)
    ):
        return fail("recommendation-context-is-outside-tab-layout")
    group_left = daily_x0
    group_right = quest_x1
    context_margin = max(16.0, (context_x1 - context_x0) / 2.0)
    if not (group_left - context_margin <= context_center_x <= group_right + context_margin):
        return fail("recommendation-context-is-not-associated-with-daily-quest")

    details.update(
        {
            "recognized": True,
            "daily": daily.roi,
            "quest": quest.roi,
            "alliance": alliance.roi,
            "activity": activity.roi,
            "recommendation_context": context.roi,
            "daily_quest_group": (group_left, min(daily_y0, quest_y0), group_right, max(daily_y1, quest_y1)),
            "alliance_activity_centers": (
                (round(alliance_center_x, 3), round(alliance_center_y, 3)),
                (round(activity_center_x, 3), round(activity_center_y, 3)),
            ),
            "recommendation_context_gap": round(context_gap, 3),
            "quest_center": (round(quest_center_x, 3), round(quest_center_y, 3)),
        }
    )
    return (
        {
            "daily": daily,
            "quest": quest,
            "alliance": alliance,
            "activity": activity,
            "context": context,
            "group_center_x": (group_left + group_right) / 2.0,
            "group_width": group_right - group_left,
            "tab_height": tab_height,
            "alliance_center_x": alliance_center_x,
        },
        details,
    )


def _tab_probe_token(
    *,
    center_x: float,
    group_width: float,
    y0: int,
    y1: int,
) -> OCRToken | None:
    width = max(1, int(round(group_width)))
    left = int(round(center_x - width / 2.0))
    roi = _clamp_roi((left, y0, left + width, y1))
    if roi is None:
        return None
    return OCRToken(text="tab-probe", roi=roi)


def _token_center(token: OCRToken) -> tuple[float, float]:
    x0, y0, x1, y1 = token.roi
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _line_tokens(tokens: Sequence[OCRToken], *, y: float, tolerance: float = 24.0) -> tuple[OCRToken, ...]:
    return tuple(
        sorted(
            (
                token
                for token in tokens
                if abs(_token_center(token)[1] - y) <= tolerance
            ),
            key=lambda token: token.roi[0],
        )
    )


def _line_text(tokens: Sequence[OCRToken]) -> str:
    return " ".join(token.text for token in sorted(tokens, key=lambda item: item.roi[0])).strip()


def _reading_text(tokens: Sequence[OCRToken]) -> str:
    return " ".join(
        token.text
        for token in sorted(tokens, key=lambda item: (item.roi[1], item.roi[0]))
    ).strip()




def _parse_points(text: str) -> int | None:
    match = re.search(r"(?:daily\s+quest\s+)?pts?[^0-9]{0,12}(\d{1,6})", text)
    return int(match.group(1)) if match else None




def _parse_reset_timer(text: str) -> str | None:
    match = re.search(
        r"reset\s*(?:time\s*)?[^0-9]*(\d{1,2}:\d{2}:\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        spaced = re.search(
            r"reset\s*(?:time\s*)?[^0-9]*(\d{1,2})\s+(\d{2})\s+(\d{2})",
            text,
            flags=re.IGNORECASE,
        )
        if spaced is not None:
            value = ":".join(spaced.groups())
            hours, minutes, seconds = (int(part) for part in value.split(":"))
            if minutes <= 59 and seconds <= 59 and hours + minutes + seconds > 0:
                return value
        return None
    value = match.group(1)
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if minutes > 59 or seconds > 59 or hours + minutes + seconds <= 0:
        return None
    return value


def _reset_timer_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (AttributeError, TypeError, ValueError):
        return None
    if minutes > 59 or seconds > 59 or hours < 0:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def _coerce_wall_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def reset_deadline_evidence(
    reset_timer: str,
    *,
    observed_utc: datetime | str | None = None,
    tolerance_seconds: int = RESET_DEADLINE_TOLERANCE_SECONDS,
) -> dict[str, Any] | None:
    """Resolve a displayed countdown to a stable, evidence-bound deadline."""

    seconds = _reset_timer_seconds(reset_timer)
    if seconds is None or tolerance_seconds < 0:
        return None
    observed = _coerce_wall_utc(observed_utc)
    # The game display is second-granular.  Flooring the observed wall time
    # makes consecutive frames with a decrementing timer resolve identically.
    normalized = (observed + timedelta(seconds=seconds)).replace(microsecond=0)
    deadline = normalized.isoformat().replace("+00:00", "Z")
    identity = f"reset-deadline:{deadline}"
    return {
        "displayed_timer": reset_timer,
        "reset_timer_seconds": seconds,
        "observed_utc": observed.isoformat().replace("+00:00", "Z"),
        "normalized_deadline_utc": deadline,
        "deadline_identity": identity,
        "tolerance_seconds": int(tolerance_seconds),
    }


def _reset_deadline_identities_match(
    expected: object,
    actual: object,
    *,
    tolerance_seconds: int,
) -> bool:
    if expected == actual:
        return True
    if not (
        isinstance(expected, str)
        and isinstance(actual, str)
        and expected.startswith("reset-deadline:")
        and actual.startswith("reset-deadline:")
    ):
        return False
    try:
        expected_utc = _coerce_wall_utc(expected.split(":", 1)[1])
        actual_utc = _coerce_wall_utc(actual.split(":", 1)[1])
    except (TypeError, ValueError):
        return False
    return abs((expected_utc - actual_utc).total_seconds()) <= max(0, tolerance_seconds)


def _selected_daily_visual_context(
    frame: np.ndarray,
    tokens: Sequence[OCRToken],
) -> tuple[bool, dict[str, Any]]:
    """Prove the center Daily tab from current geometry and neighboring labels."""

    top_tokens = tuple(
        token for token in tokens if _token_center(token)[1] <= 230
    )
    daily = [
        token for token in top_tokens if token.text in {"daily", "daily quest"}
    ]
    main = [
        token
        for token in top_tokens
        if token.text in {"main", "main quest", "quest"}
    ]
    alliance = [
        token
        for token in top_tokens
        if token.text in {"alliance", "alliance activity"}
    ]
    activity = [token for token in top_tokens if token.text == "activity"]
    details: dict[str, Any] = {
        "daily_candidates": tuple(token.roi for token in daily),
        "main_candidates": tuple(token.roi for token in main),
        "alliance_candidates": tuple(token.roi for token in alliance),
        "activity_candidates": tuple(token.roi for token in activity),
        "title_ocr_present": bool(daily),
    }
    explicit_main = [token for token in main if token.text in {"main", "main quest"}]
    main_token = (
        max(explicit_main or main, key=lambda token: token.roi[2])
        if main
        else None
    )
    alliance_token = min(alliance, key=lambda token: token.roi[0]) if alliance else None
    if alliance_token is None and activity:
        alliance_token = min(activity, key=lambda token: token.roi[0])

    daily_token = daily[0] if len(daily) == 1 else None
    if main_token is None or alliance_token is None:
        details["reason"] = "main-alliance-daily-context-is-missing"
        return False, details
    main_center = _token_center(main_token)
    alliance_center = _token_center(alliance_token)
    if not main_center[0] < alliance_center[0]:
        details["reason"] = "main-alliance-context-order-is-invalid"
        return False, details

    if daily_token is not None:
        daily_center = _token_center(daily_token)
        geometry_proven = bool(
            main_center[0] < daily_center[0] < alliance_center[0]
            and abs(daily_center[1] - main_center[1]) <= 75
            and abs(daily_center[1] - alliance_center[1]) <= 75
        )
        daily_score = _tab_visual_score(frame, daily_token)
        main_score = _tab_visual_score(frame, main_token)
        selected_by_geometry = bool(
            geometry_proven
            and daily_score >= 0.12
            and daily_score >= main_score + 0.015
        )
        details["daily_center"] = (round(daily_center[0], 3), round(daily_center[1], 3))
        details.update(
            {
                "daily_tab_score": daily_score,
                "main_tab_score": main_score,
                "selected_margin": round(daily_score - main_score, 6),
            }
        )
    else:
        # If the stylized Daily title is missed, use the current frame's center
        # tab between the positively associated Main and Alliance labels.
        tab_row_vertical_delta = abs(main_center[1] - alliance_center[1])
        tab_row_compatible = tab_row_vertical_delta <= 75
        center_x = (main_token.roi[2] + alliance_token.roi[0]) / 2.0
        y0 = max(45, min(main_token.roi[1], alliance_token.roi[1]) - 18)
        y1 = min(150, max(main_token.roi[3], alliance_token.roi[3]) + 32)
        center_roi = _clamp_roi((int(main_token.roi[2]), y0, int(alliance_token.roi[0]), y1))
        if center_roi is None:
            details["reason"] = "center-daily-tab-geometry-is-invalid"
            return False, details
        cx0, cy0, cx1, cy1 = center_roi
        left_roi = _clamp_roi((max(0, cx0 - max(20, cx1 - cx0)), cy0, cx0, cy1))
        right_roi = _clamp_roi((cx1, cy0, min(NATIVE_WIDTH, cx1 + max(20, cx1 - cx0)), cy1))

        def score(roi: NativeBox | None) -> float:
            if roi is None:
                return 0.0
            x0, y0, x1, y1 = roi
            patch = frame[y0:y1, x0:x1]
            if patch.size == 0:
                return 0.0
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            red = np.asarray(patch[:, :, 2], dtype=np.float32)
            blue = np.asarray(patch[:, :, 0], dtype=np.float32)
            return float(np.mean(hsv[:, :, 1]) / 255.0 + np.mean(red - blue) / 255.0)

        center_score = score(center_roi)
        left_score = score(left_roi)
        right_score = score(right_roi)
        selected_by_geometry = bool(
            tab_row_compatible
            and center_score >= max(left_score, right_score) + 0.02
        )
        details.update(
            {
                "daily_center": (round(center_x, 3), round((cy0 + cy1) / 2.0, 3)),
                "daily_tab_probe": center_roi,
                "daily_tab_score": round(center_score, 6),
                "main_tab_score": round(left_score, 6),
                "alliance_tab_score": round(right_score, 6),
                "selected_margin": round(
                    center_score - max(left_score, right_score),
                    6,
                ),
                "tab_row_vertical_delta": round(tab_row_vertical_delta, 3),
                "tab_row_compatible": tab_row_compatible,
            }
        )
    details["recognized"] = selected_by_geometry
    if not selected_by_geometry:
        details["reason"] = (
            "main-alliance-tab-row-is-vertically-incompatible"
            if daily_token is None
            and not details.get("tab_row_compatible", True)
            else "center-daily-tab-selection-not-proven"
        )
    return selected_by_geometry, details


def _visual_claim_button_candidates(
    frame: np.ndarray,
    *,
    row_y: float,
    minimum_x: int,
    scan_details: dict[str, Any] | None = None,
) -> tuple[NativeBox, ...]:
    """Find current-frame gold Claim bodies and reject red Go controls."""

    if not _frame_shape_ok(frame):
        return ()
    x0, x1 = CLAIM_BUTTON_COLUMN
    x0 = max(x0, int(minimum_x))
    if x0 >= x1:
        return ()
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    region = hsv[CLAIM_SCAN_TOP_Y:NATIVE_HEIGHT, x0:x1]
    if region.size == 0:
        return ()
    hue, saturation, value = (
        region[:, :, 0],
        region[:, :, 1],
        region[:, :, 2],
    )
    gold = (
        (hue >= CLAIM_HUE_RANGE[0])
        & (hue <= CLAIM_HUE_RANGE[1])
        & (saturation >= CLAIM_MIN_SAT)
        & (value >= CLAIM_MIN_VAL)
    ).astype(np.uint8) * 255
    if scan_details is not None:
        scan_details.update(
            {
                "claim_scan_roi": (x0, CLAIM_SCAN_TOP_Y, x1, NATIVE_HEIGHT),
                "claim_scan_raw_gold_pixel_count": int(cv2.countNonZero(gold)),
            }
        )
    full = np.zeros((NATIVE_HEIGHT, NATIVE_WIDTH), dtype=np.uint8)
    full[CLAIM_SCAN_TOP_Y:NATIVE_HEIGHT, x0:x1] = gold
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 15))
    closed = cv2.morphologyEx(full, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        closed,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    candidates: list[NativeBox] = []
    for contour in contours:
        left, top, width, height = cv2.boundingRect(contour)
        if width < CLAIM_MIN_WIDTH or height < CLAIM_MIN_HEIGHT:
            continue
        candidates.append((left, top, left + width, top + height))
    candidates.sort(key=lambda box: (box[1], box[0], box[2], box[3]))
    if scan_details is not None:
        scan_details["claim_scan_complete"] = True
    return tuple(candidates)


def _horizontal_separator_rows(frame: np.ndarray) -> tuple[int, ...]:
    """Return long current-frame horizontal panel edges."""

    if frame.size == 0:
        return ()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 140)
    counts = np.count_nonzero(edges, axis=1)
    threshold = max(160, int(round(frame.shape[1] * 0.42)))
    rows = np.flatnonzero(counts >= threshold)
    if rows.size == 0:
        return ()
    groups: list[list[int]] = [[int(rows[0])]]
    for row in rows[1:]:
        if int(row) <= groups[-1][-1] + 4:
            groups[-1].append(int(row))
        else:
            groups.append([int(row)])
    return tuple(int(round(sum(group) / len(group))) for group in groups)


def _measure_daily_row_panel(
    frame: np.ndarray,
    *,
    anchor_y: float,
    evidence_tokens: Sequence[OCRToken] = (),
) -> dict[str, Any] | None:
    """Measure one row panel from current pixels, never from Claim proximity."""

    separators = _horizontal_separator_rows(frame)
    anchor = int(round(anchor_y))
    above = [row for row in separators if 320 < row < anchor - 18]
    below = [row for row in separators if anchor + 18 < row < min(NATIVE_HEIGHT, anchor + 240)]
    if above and below:
        if (
            len(above) > 1
            and above[-1] - above[-2] < 30
            or len(below) > 1
            and below[1] - below[0] < 30
        ):
            return None
        top = max(above) + 2
        bottom = min(below) - 2
        source = "visual-horizontal-separators"
        proven = True
    else:
        # A panel may have a filled background without a crisp edge.  Require
        # broad support across the frame and measure its contiguous vertical
        # run around the objective evidence.
        if evidence_tokens:
            y0 = max(320, min(token.roi[1] for token in evidence_tokens) - 24)
            y1 = min(NATIVE_HEIGHT, max(token.roi[3] for token in evidence_tokens) + 24)
        else:
            # Color binding intentionally does not depend on stylized Claim
            # OCR.  Use a bounded native band around the color control only
            # to locate independently visible panel support.
            y0 = max(320, anchor - 120)
            y1 = min(NATIVE_HEIGHT, anchor + 120)
        support = np.count_nonzero(np.any(frame[y0:y1] != 0, axis=2), axis=1)
        broad = support >= int(round(frame.shape[1] * 0.45))
        if broad.size and bool(np.any(broad)):
            indexes = np.flatnonzero(broad)
            containing = indexes[
                (indexes >= max(0, anchor - y0 - 24))
                & (indexes <= min(broad.size - 1, anchor - y0 + 24))
            ]
            if containing.size:
                start = int(containing[0])
                end = int(containing[-1])
                while start > 0 and broad[start - 1]:
                    start -= 1
                while end + 1 < broad.size and broad[end + 1]:
                    end += 1
                top, bottom = y0 + start, y0 + end + 1
                source = "visual-background-support"
                proven = True
            else:
                top = bottom = 0
                source = "unproven"
                proven = False
        else:
            top = bottom = 0
            source = "unproven"
            proven = False

    if not (0 <= top < bottom <= NATIVE_HEIGHT):
        return None
    if evidence_tokens:
        token_x0 = max(0, min(token.roi[0] for token in evidence_tokens) - 18)
        token_x1 = min(NATIVE_WIDTH, max(token.roi[2] for token in evidence_tokens) + 18)
        if token_x0 >= token_x1:
            return None
    else:
        token_x0, token_x1 = 0, NATIVE_WIDTH
    # If only a long horizontal separator proves the panel, its horizontal
    # extent is the native content frame.  A filled background is narrowed
    # below only when broad current pixels independently expose its edges.
    panel_x0, panel_x1 = token_x0, token_x1
    if source == "visual-horizontal-separators":
        panel_edges = cv2.Canny(
            cv2.cvtColor(frame[top:bottom], cv2.COLOR_BGR2GRAY),
            50,
            140,
        )
        column_counts = np.count_nonzero(panel_edges, axis=0)
        columns = np.flatnonzero(
            column_counts >= max(24, int(round((bottom - top) * 0.35)))
        )
        if columns.size:
            groups: list[list[int]] = [[int(columns[0])]]
            for column in columns[1:]:
                if int(column) <= groups[-1][-1] + 2:
                    groups[-1].append(int(column))
                else:
                    groups.append([int(column)])
            if len(groups) >= 2:
                panel_x0 = max(0, groups[0][-1] + 2)
                panel_x1 = min(NATIVE_WIDTH, groups[-1][0] - 1)
            else:
                panel_x0, panel_x1 = 0, NATIVE_WIDTH
    # Current visual panel evidence proves the vertical ownership.  Horizontal
    # bounds remain a conservative measured content span, and every selected
    # control must fit fully within it.
    return {
        "bounds": (panel_x0, top, panel_x1, bottom),
        "source": source,
        "proven": proven,
        "horizontal_separators": separators,
    }


def _visual_claim_button_evidence(
    frame: np.ndarray,
    target: NativeBox,
) -> dict[str, Any]:
    """Prove an ordinary rectangular Claim button, not an icon or amount."""

    tx0, ty0, tx1, ty1 = target
    candidates = _visual_claim_button_candidates(
        frame,
        row_y=(ty0 + ty1) / 2.0,
        minimum_x=max(0, tx0 - 80),
    )
    matching = tuple(
        box
        for box in candidates
        if box[0] < tx1 and tx0 < box[2] and box[1] < ty1 and ty0 < box[3]
    )
    if len(matching) != 1:
        return {
            "recognized": False,
            "button_class": "unknown",
            "candidates": matching,
        }
    bx0, by0, bx1, by1 = matching[0]
    width, height = bx1 - bx0, by1 - by0
    ordinary = bool(width >= 50 and height >= 20 and width / max(1, height) >= 1.2)
    return {
        "recognized": ordinary,
        "button_class": "ordinary_claim_button" if ordinary else "unknown",
        "button_roi": matching[0],
        "candidates": matching,
        "aspect_ratio": round(width / max(1, height), 4),
    }


def _scan_claim_cost_region(
    frame: np.ndarray,
    *,
    panel: NativeBox,
    target: NativeBox,
    tokens: Sequence[OCRToken],
    excluded_tokens: Sequence[OCRToken],
) -> dict[str, Any]:
    """Scan only the region attached to the Claim control for cost evidence."""

    px0, py0, px1, py1 = panel
    tx0, ty0, _tx1, ty1 = target
    region = _clamp_roi(
        (
            max(px0, tx0 - 140),
            max(py0, ty0 - 24),
            min(px1, tx0),
            min(py1, ty1 + 24),
        )
    )
    if region is None:
        return {
            "roi": None,
            "currency_words": (),
            "numeric_tokens": (),
            "currency_icon": False,
            "attached_cost": True,
            "numeric_only_cost": False,
            "icon_only_cost": False,
        }
    excluded = {token.roi for token in excluded_tokens}
    currency_words = {
        "gem",
        "gems",
        "diamond",
        "diamonds",
        "cost",
        "purchase",
        "buy",
        "usd",
        "dollar",
        "price",
    }
    rx0, ry0, rx1, ry1 = region
    attached = [
        token
        for token in tokens
        if token.roi not in excluded
        and rx0 <= _token_center(token)[0] <= rx1
        and ry0 <= _token_center(token)[1] <= ry1
    ]
    words = tuple(
        sorted(
            {
                word
                for token in attached
                for word in token.text.split()
                if word in currency_words
            }
        )
    )
    numeric = tuple(
        sorted(
            token.text
            for token in attached
            if re.fullmatch(r"\d+(?:\.\d+)?", token.text)
        )
    )
    crop = frame[ry0:ry1, rx0:rx1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV) if crop.size else np.zeros((0, 0, 3), dtype=np.uint8)
    saturated = cv2.inRange(hsv, (0, 80, 70), (179, 255, 255)) if crop.size else np.zeros((0, 0), dtype=np.uint8)
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(saturated, 8)
    icon_components = []
    for component in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[component])
        if (
            8 <= width <= 60
            and 8 <= height <= 60
            and area >= 30
            and left > 0
            and top > 0
            and left + width < saturated.shape[1]
            and top + height < saturated.shape[0]
        ):
            icon_components.append((rx0 + left, ry0 + top, rx0 + left + width, ry0 + top + height))
    currency_icon = bool(icon_components)
    return {
        "roi": region,
        "currency_words": words,
        "numeric_tokens": numeric,
        "currency_icon": currency_icon,
        "icon_components": tuple(icon_components),
        "attached_cost": bool(words or numeric or currency_icon),
        "numeric_only_cost": bool(numeric and not words),
        "icon_only_cost": bool(currency_icon and not words and not numeric),
    }


def _free_claim_control_proven(cost_scan: Mapping[str, Any]) -> bool:
    """Require the Claim-adjacent region to prove a free ordinary control."""

    return bool(
        not cost_scan.get("attached_cost")
        and not cost_scan.get("currency_icon")
        and not cost_scan.get("numeric_tokens")
    )


def _daily_aggregate_claim_semantics(
    frame: np.ndarray,
    tokens: Sequence[OCRToken],
    *,
    game_day_id: str | None,
    observed_utc: datetime | str | None = None,
) -> tuple[FrameRecognition, AvailableDailyClaimObservation | None]:
    """Select one safe target from aggregate Claim controls on selected Daily."""

    words = {word for token in tokens for word in token.text.split()}
    overlay_markers = tuple(sorted(words & _OVERLAY_MARKERS))
    header_tokens = tuple(token for token in tokens if _token_center(token)[1] < 440)
    selected, selected_visual = _selected_daily_visual_context(frame, header_tokens)
    full_text = _reading_text(header_tokens)
    points = _parse_points(full_text)
    reset_timer = _parse_reset_timer(full_text)
    reset_evidence = (
        reset_deadline_evidence(reset_timer, observed_utc=observed_utc)
        if reset_timer is not None
        else None
    )
    deadline_identity = (
        str(reset_evidence["deadline_identity"])
        if reset_evidence is not None
        else None
    )
    bound_game_day_id = game_day_id or deadline_identity
    deadline_bound_to_game_day = bool(
        deadline_identity is not None
        and (
            game_day_id is None
            or _reset_deadline_identities_match(
                game_day_id,
                deadline_identity,
                tolerance_seconds=(
                    reset_evidence["tolerance_seconds"] if reset_evidence else 0
                ),
            )
        )
    )
    body = tuple(token for token in tokens if token.text == "claim")
    visual: dict[str, Any] = {
        "full_frame_overlay": {
            "recognized": bool(overlay_markers),
            "markers": overlay_markers,
        },
        "selected_daily_semantics": selected_visual,
        "selected_daily": selected,
        "points": points,
        "reset_timer": reset_timer,
        "game_day_id": bound_game_day_id,
        "reset_timer_seconds": (
            reset_evidence["reset_timer_seconds"]
            if reset_evidence and deadline_bound_to_game_day
            else None
        ),
        "reset_observed_utc": (
            reset_evidence["observed_utc"]
            if reset_evidence and deadline_bound_to_game_day
            else None
        ),
        "reset_deadline_utc": (
            reset_evidence["normalized_deadline_utc"]
            if reset_evidence and deadline_bound_to_game_day
            else None
        ),
        "reset_deadline_identity": (
            deadline_identity if deadline_bound_to_game_day else None
        ),
        "reset_deadline_tolerance_seconds": (
            reset_evidence["tolerance_seconds"]
            if reset_evidence and deadline_bound_to_game_day
            else None
        ),
        "runtime_profile_id": BLUESTACKS_RUNTIME_PROFILE_ID,
        "target_provenance": BLUESTACKS_TARGET_PROVENANCE,
    }

    def failure(reason: str) -> tuple[FrameRecognition, None]:
        visual["reason"] = reason
        return (
            FrameRecognition(
                UNKNOWN_STATE,
                False,
                None,
                None,
                full_text,
                visual,
                reason,
                _token_rows((*header_tokens, *body)),
            ),
            None,
        )

    if overlay_markers:
        return failure("full-frame overlay/modal detected")
    if not selected:
        return failure(selected_visual.get("reason", "selected Daily was not proven"))
    if reset_timer is None:
        return failure("positive Daily reset timer was not proven")
    if reset_evidence is None:
        return failure("Daily reset deadline identity was not proven")
    if (
        isinstance(game_day_id, str)
        and game_day_id.startswith("reset-deadline:")
        and not _reset_deadline_identities_match(
            game_day_id,
            deadline_identity,
            tolerance_seconds=(
                reset_evidence["tolerance_seconds"] if reset_evidence else 0
            ),
        )
    ):
        return failure("Daily reset deadline identity changed")
    claim_tokens = tuple(
        sorted(
            (token for token in body if token.text == "claim"),
            key=lambda token: (
                _token_center(token)[1],
                _token_center(token)[0],
                token.roi,
            ),
        )
    )
    all_claim_controls = _visual_claim_button_candidates(
        frame,
        row_y=NATIVE_HEIGHT / 2.0,
        minimum_x=CLAIM_BUTTON_COLUMN[0],
        scan_details=visual,
    )
    claim_controls = all_claim_controls[:1]
    visual["recognized_claim_controls"] = len(all_claim_controls)
    visual["available_claim_controls"] = 0
    visual["available_ordinary_claim_controls"] = 0
    visual["zero_claim_scan_proven"] = False
    if not all_claim_controls:
        if (
            visual.get("claim_scan_complete") is not True
            or visual.get("claim_scan_raw_gold_pixel_count") != 0
        ):
            return failure(
                "Claim control absence is ambiguous; residual or clipped Claim pixels remain"
            )
        visual["zero_claim_scan_proven"] = True
        visual["claim_ready"] = False
        return (
            FrameRecognition(
                DAILY_SELECTED_STATE,
                True,
                None,
                None,
                full_text,
                visual,
                None,
                _token_rows((*header_tokens, *body)),
            ),
            None,
        )

    candidates: list[dict[str, Any]] = []
    for ordinal, claim_roi in enumerate(claim_controls, start=1):
        row_y = (claim_roi[1] + claim_roi[3]) / 2.0
        claim_token = next(
            (
                token
                for token in claim_tokens
                if token.roi[0] < claim_roi[2]
                and claim_roi[0] < token.roi[2]
                and token.roi[1] < claim_roi[3]
                and claim_roi[1] < token.roi[3]
            ),
            None,
        )
        candidate: dict[str, Any] = {
            "ordinal": ordinal,
            "claim_ocr_roi": claim_token.roi if claim_token is not None else None,
            "status": "rejected",
            "eligible": False,
            "rejection_reasons": [],
            "row_bounds": None,
            "claim_roi": None,
            "button_evidence": None,
            "cost_scan": None,
        }
        panel_geometry = _measure_daily_row_panel(
            frame,
            anchor_y=row_y,
        )
        candidate["row_panel_geometry"] = panel_geometry
        if panel_geometry is None or not panel_geometry["proven"]:
            candidate["rejection_reasons"].append("row_panel_not_proven")
            candidates.append(candidate)
            continue

        row_bounds = tuple(panel_geometry["bounds"])
        candidate["row_bounds"] = row_bounds
        if (
            row_bounds[1] <= 340
            or row_bounds[3] >= NATIVE_HEIGHT - 20
            or claim_roi[3] >= NATIVE_HEIGHT - 20
        ):
            candidate["rejection_reasons"].append("claim_clipped_or_milestone_region")
        if not (
            row_bounds[0] <= claim_roi[0]
            and claim_roi[2] <= row_bounds[2]
            and row_bounds[1] <= claim_roi[1]
            and claim_roi[3] <= row_bounds[3]
        ):
            candidate["rejection_reasons"].append("claim_outside_measured_panel")

        candidate["claim_roi"] = claim_roi
        if not (
            row_bounds[0] <= claim_roi[0]
            and claim_roi[2] <= row_bounds[2]
            and row_bounds[1] <= claim_roi[1]
            and claim_roi[3] <= row_bounds[3]
        ):
            candidate["rejection_reasons"].append("claim_outside_or_straddles_panel")

        button_evidence = _visual_claim_button_evidence(frame, claim_roi)
        cost_scan = _scan_claim_cost_region(
            frame,
            panel=row_bounds,
            target=claim_roi,
            tokens=tokens,
            excluded_tokens=claim_tokens,
        )
        candidate["button_evidence"] = button_evidence
        candidate["cost_scan"] = cost_scan
        candidate["ordinary_reward_claim"] = bool(
            selected
            and button_evidence["button_class"] == "ordinary_claim_button"
        )
        candidate["free_control_proven"] = _free_claim_control_proven(cost_scan)
        candidate["quantity_one_proven"] = True
        if not button_evidence["recognized"]:
            candidate["rejection_reasons"].append("ordinary_claim_button_not_proven")
        if cost_scan["attached_cost"]:
            candidate["rejection_reasons"].append("claim_attached_cost")
        if not candidate["ordinary_reward_claim"]:
            candidate["rejection_reasons"].append("ordinary_claim_semantics_not_proven")
        if not candidate["free_control_proven"]:
            candidate["rejection_reasons"].append("free_claim_semantics_not_proven")
        candidate["eligible"] = not candidate["rejection_reasons"]
        if candidate["eligible"]:
            candidate["status"] = "eligible"
        candidates.append(candidate)

    # Two OCR tokens that bind to one current visual button are ambiguous and
    # cannot be treated as two eligible controls or selected opportunistically.
    physical_groups: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not candidate.get("eligible"):
            continue
        button = candidate.get("button_evidence") or {}
        physical = button.get("button_roi") or candidate.get("claim_roi")
        if isinstance(physical, (tuple, list)) and len(physical) == 4:
            physical_groups.setdefault(tuple(int(value) for value in physical), []).append(candidate)
    for grouped in physical_groups.values():
        if len(grouped) <= 1:
            continue
        for candidate in grouped:
            candidate["eligible"] = False
            candidate["status"] = "rejected"
            candidate["rejection_reasons"].append("ambiguous_duplicate_claim_control")

    eligible = [candidate for candidate in candidates if candidate.get("eligible")]
    visual["claim_candidates"] = tuple(candidates)
    visual["available_claim_controls"] = len(eligible)
    if not eligible:
        rejection_reasons = {
            reason
            for candidate in candidates
            for reason in candidate["rejection_reasons"]
        }
        if (
            "claim_outside_measured_panel" in rejection_reasons
            or "claim_outside_or_straddles_panel" in rejection_reasons
        ):
            return failure("Claim control escaped the measured panel")
        if "claim_attached_cost" in rejection_reasons:
            return failure(
                "Claim control has an attached currency, amount, or purchase surface"
            )
        if "ambiguous_duplicate_claim_control" in rejection_reasons:
            return failure("Claim control is missing or ambiguous")
        return failure("no independently safe ordinary free Claim control was proven")

    selected_candidate = eligible[0]
    row_bounds = tuple(selected_candidate["row_bounds"])
    target_roi = tuple(selected_candidate["claim_roi"])
    panel_geometry = selected_candidate["row_panel_geometry"]
    button_evidence = dict(selected_candidate["button_evidence"])
    cost_scan = dict(selected_candidate["cost_scan"])
    ordinary_reward_claim = True
    free_control_proven = True
    quantity_one_proven = True

    observation = AvailableDailyClaimObservation(
        screen_state="DAILY_QUEST",
        selected_daily_quest=True,
        objective_key="",
        objective_name="",
        current_progress=0,
        required_progress=0,
        row_bounds=row_bounds,
        target_identity=DAILY_CLAIM_TARGET_IDENTITY,
        target_roi=target_roi,
        control_class="CLAIM",
        row_fully_visible=True,
        claim_fully_visible=True,
        cost_type="none",
        cost_amount=0,
        quantity=1,
        game_day_id=bound_game_day_id,
        target_provenance=BLUESTACKS_TARGET_PROVENANCE,
        source_frame_sha256="",
        evidence_refs=(),
        milestone_reward=False,
        clipped=False,
        overlay_state="none",
        reset_guard_active=False,
        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        recognized=True,
        points=points,
        reward_points=None,
        reset_timer=reset_timer,
        catalog_reconciled=False,
        ordinary_reward_claim=ordinary_reward_claim,
        free_control_proven=free_control_proven,
        quantity_one_proven=quantity_one_proven,
        cost_region_scan=cost_scan,
        cost_icon_scan={
            "currency_icon": bool(cost_scan.get("currency_icon")),
            "icon_components": cost_scan.get("icon_components", ()),
        },
        row_panel_proven=True,
        row_panel_source=str(panel_geometry["source"]),
        reset_timer_seconds=visual.get("reset_timer_seconds"),
        reset_observed_utc=visual.get("reset_observed_utc"),
        reset_deadline_utc=visual.get("reset_deadline_utc"),
        reset_deadline_identity=visual.get("reset_deadline_identity"),
        reset_deadline_tolerance_seconds=visual.get(
            "reset_deadline_tolerance_seconds"
        ),
        available_claim_controls=len(eligible),
    )
    visual.update(
        {
            "claim_ready": True,
            "row_bounds": row_bounds,
            "row_panel_bounds": row_bounds,
            "claim_roi": target_roi,
            "claim_ocr_roi": selected_candidate.get("claim_ocr_roi"),
            "row_panel_geometry": panel_geometry,
            "panel_geometry_proven": bool(panel_geometry["proven"]),
            "row_fully_visible": True,
            "claim_fully_visible": True,
            "cost_type": "none",
            "cost_amount": 0,
            "quantity": 1,
            "ordinary_reward_claim": ordinary_reward_claim,
            "free_control_proven": free_control_proven,
            "quantity_one_proven": quantity_one_proven,
            "cost_region_scan": cost_scan,
            "cost_icon_scan": {
                "currency_icon": bool(cost_scan.get("currency_icon")),
                "icon_components": cost_scan.get("icon_components", ()),
            },
            "button_evidence": button_evidence,
            "milestone_reward": False,
            "available_claim_controls": len(eligible),
        }
    )
    return (
        FrameRecognition(
            DAILY_SELECTED_STATE,
            True,
            DAILY_CLAIM_TARGET_IDENTITY,
            target_roi,
            full_text,
            visual,
            None,
            _token_rows((*header_tokens, *body)),
        ),
        observation,
    )


def _daily_claim_semantics(
    frame: np.ndarray,
    tokens: Sequence[OCRToken],
    *,
    game_day_id: str | None,
    observed_utc: datetime | str | None = None,
) -> tuple[FrameRecognition, AvailableDailyClaimObservation | None]:
    return _daily_aggregate_claim_semantics(
        frame,
        tokens,
        game_day_id=game_day_id,
        observed_utc=observed_utc,
    )




class DailyRowClaimRecognizer:
    """Recognize only the three states needed by the frozen route."""

    def __init__(
        self,
        *,
        ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
    ) -> None:
        self._ocr = ocr or _default_ocr

    def recognize_home(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(HOME_STATE, False, reason="profile_dimensions_mismatch")
        template = recognize_home_nav(frame)
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        quest_point = template.quest_tap_point()
        target = (
            _clamp_roi(
                (
                    quest_point[0] - 30,
                    quest_point[1] - 24,
                    quest_point[0] + 30,
                    quest_point[1] + 24,
                )
            )
            if quest_point is not None
            else None
        )
        visual: dict[str, Any] = {
            "bottom_navigation": bool(template.is_home),
            "template_home": {
                "recognized": bool(template.is_home),
                "native_ok": bool(template.native_ok),
                "correlation": template.correlation,
                "reason": template.reason,
                "quest_tap_point": quest_point,
            },
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        recognized = bool(
            template.is_home
            and template.native_ok
            and target is not None
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else template.reason
            if not template.is_home
            else "home-quest-target-not-proven"
        )
        return FrameRecognition(
            HOME_STATE if recognized else UNKNOWN_STATE,
            recognized,
            HOME_QUEST_IDENTITY if recognized else None,
            target if recognized else None,
            "",
            visual,
            reason,
            (),
        )

    def recognize_quest(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(QUEST_STATE, False, reason="profile_dimensions_mismatch")
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, QUEST_TAB_SEARCH_ROI, self._ocr)
        quest_header = next(
            (token for token in tokens if "quest" in token.text and token.roi[1] < 90),
            None,
        )
        semantics, semantics_visual = _quest_page_semantics(tokens)
        daily_candidates = [token for token in tokens if token.text == "daily"]
        daily = daily_candidates[0] if len(daily_candidates) == 1 else None
        target = None
        visual: dict[str, Any] = {
            "quest_header": quest_header.roi if quest_header else None,
            "tab_structure": semantics is not None,
            "quest_page_semantics": semantics_visual,
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        if daily is not None:
            target, binding = _bind_text_target(
                frame,
                daily,
                identity=QUEST_DAILY_IDENTITY,
                min_y=35,
                max_y=220,
            )
            visual["daily_binding"] = binding

        selection_proven = False
        if semantics is not None:
            group_left, group_y0, group_right, group_y1 = semantics_visual["daily_quest_group"]
            daily_probe = _tab_probe_token(
                center_x=semantics["group_center_x"],
                group_width=semantics["group_width"],
                y0=group_y0,
                y1=group_y1,
            )
            tab_pitch = semantics["alliance_center_x"] - semantics["group_center_x"]
            main_probe = (
                _tab_probe_token(
                    center_x=semantics["group_center_x"] - tab_pitch,
                    group_width=semantics["group_width"],
                    y0=group_y0,
                    y1=group_y1,
                )
                if tab_pitch > semantics["group_width"]
                else None
            )
            main_candidates = [
                token
                for token in tokens
                if token.text in {"main", "main quest"}
            ]
            main_row_candidates = [
                token
                for token in main_candidates
                if token.roi[2] <= group_left
                and abs(
                    (token.roi[1] + token.roi[3]) / 2.0
                    - (group_y0 + group_y1) / 2.0
                )
                <= max(16.0, 1.25 * semantics["tab_height"])
            ]
            main_token = main_row_candidates[0] if len(main_row_candidates) == 1 else None
            if main_candidates and len(main_row_candidates) != 1:
                main_probe = None
            daily_score = _tab_visual_score(frame, daily_probe) if daily_probe else 0.0
            main_score = (
                _tab_visual_score(frame, main_token)
                if main_token is not None
                else _tab_visual_score(frame, main_probe)
                if main_probe is not None
                else 0.0
            )
            selection_proven = bool(
                main_probe is not None
                and main_score >= 0.12
                and main_score >= daily_score + 0.015
            )
            visual.update(
                {
                    "daily_tab_score": daily_score,
                    "main_tab_score": main_score,
                    "main_selected_margin": round(main_score - daily_score, 6),
                    "main_tab_present": main_token is not None,
                    "main_tab_probe": main_probe.roi if main_probe else None,
                    "selection_proven": selection_proven,
                }
            )
        recognized = bool(
            semantics is not None
            and daily is not None
            and target is not None
            and selection_proven
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else semantics_visual.get("reason")
            if semantics is None
            else "main-quest-selection-not-proven"
            if not selection_proven
            else None
            if recognized
            else "quest-daily-target-not-proven"
        )
        return FrameRecognition(
            QUEST_STATE if recognized else UNKNOWN_STATE,
            recognized,
            QUEST_DAILY_IDENTITY if recognized else None,
            target if recognized else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
        )


    def recognize_daily_claim(
        self,
        frame: np.ndarray,
        *,
        game_day_id: str | None = None,
        observed_utc: datetime | str | None = None,
        wall_utc: datetime | str | None = None,
    ) -> FrameRecognition:
        """Recognize the current-frame aggregate Daily Claim control."""

        if not _frame_shape_ok(frame):
            return FrameRecognition(
                DAILY_SELECTED_STATE,
                False,
                reason="profile_dimensions_mismatch",
            )
        tokens = _ocr_tokens(frame, FULL_FRAME_SEARCH_ROI, self._ocr)
        identity = game_day_id
        recognition, _observation = _daily_claim_semantics(
            frame,
            tokens,
            game_day_id=identity,
            observed_utc=observed_utc if observed_utc is not None else wall_utc,
        )
        return recognition

    def recognize_daily_row(
        self,
        frame: np.ndarray,
        *,
        game_day_id: str | None = None,
        observed_utc: datetime | str | None = None,
        wall_utc: datetime | str | None = None,
    ) -> FrameRecognition:
        """Compatibility alias for the exact Daily row recognizer."""

        return self.recognize_daily_claim(
            frame,
            game_day_id=game_day_id,
            observed_utc=observed_utc,
            wall_utc=wall_utc,
        )

    def recognize_daily_selected(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(DAILY_SELECTED_STATE, False, reason="profile_dimensions_mismatch")
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, DAILY_TAB_SEARCH_ROI, self._ocr)
        selected, selected_visual = _selected_daily_visual_context(frame, tokens)
        visual: dict[str, Any] = dict(selected_visual)
        visual.update(
            {
                "selected_daily": selected,
                "main_tab_present": bool(selected_visual.get("main_candidates")),
                "full_frame_overlay": {
                    "recognized": bool(overlay_markers),
                    "markers": overlay_markers,
                },
            }
        )
        daily_candidates = selected_visual.get("daily_candidates", ())
        daily = daily_candidates[0] if len(daily_candidates) == 1 else None
        recognized = bool(
            selected
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else "selected-daily-semantics-not-proven"
        )
        return FrameRecognition(
            DAILY_SELECTED_STATE if recognized else UNKNOWN_STATE,
            recognized,
            "daily-quest-selected" if recognized else None,
            daily if recognized else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
        )



def recognize_daily_milestone_chests(
    frame: np.ndarray,
    daily_recognition: FrameRecognition,
    *,
    source_frame_sha256: str | None,
) -> dict[str, Any]:
    """Observe the five current milestone chests without inferring from points."""
    visual = dict(daily_recognition.visual_evidence or {})
    points = visual.get("points")
    points = points if type(points) is int else None
    if not _frame_shape_ok(frame):
        return _daily_milestone_unknown_scan(
            reason="native frame dimensions do not match the BlueStacks profile",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    if not isinstance(source_frame_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source_frame_sha256
    ):
        return _daily_milestone_unknown_scan(
            reason="native source frame identity is missing or malformed",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    overlay = visual.get("full_frame_overlay")
    if (
        not daily_recognition.recognized
        or daily_recognition.state != DAILY_SELECTED_STATE
        or visual.get("selected_daily") is not True
        or (isinstance(overlay, Mapping) and overlay.get("recognized"))
    ):
        return _daily_milestone_unknown_scan(
            reason="selected Daily context or overlay-free screen was not proven",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    if not (
        isinstance(visual.get("reset_deadline_identity"), str)
        and visual["reset_deadline_identity"].strip()
        and isinstance(visual.get("reset_deadline_utc"), str)
        and visual["reset_deadline_utc"].strip()
    ):
        return _daily_milestone_unknown_scan(
            reason="current Daily reset identity was not positively recognized",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )

    selected_geometry = visual.get("selected_daily_semantics")
    if not isinstance(selected_geometry, Mapping):
        return _daily_milestone_unknown_scan(
            reason="selected Daily header geometry is unavailable",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    daily_headers = tuple(selected_geometry.get("daily_candidates", ()))
    main_headers = tuple(selected_geometry.get("main_candidates", ()))
    alliance_headers = tuple(selected_geometry.get("alliance_candidates", ()))
    activity_headers = tuple(selected_geometry.get("activity_candidates", ()))
    if len(daily_headers) > 1 or not main_headers or not (
        alliance_headers or activity_headers
    ):
        return _daily_milestone_unknown_scan(
            reason="Daily header geometry is missing or ambiguous",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    daily_roi = _clamp_roi(
        daily_headers[0]
        if daily_headers
        else selected_geometry.get("daily_tab_probe", ())
    )
    header_boxes = tuple(
        roi
        for candidates in (
            daily_headers,
            main_headers,
            alliance_headers,
            activity_headers,
        )
        for candidate in candidates
        if (roi := _clamp_roi(candidate)) is not None
        and 35 <= roi[1] < roi[3] <= 200
    )
    if daily_roi is not None and not daily_headers:
        header_boxes = (*header_boxes, daily_roi)
    if (
        daily_roi is None
        or not 35 <= daily_roi[1] < daily_roi[3] <= 200
        or len(header_boxes) < 3
    ):
        return _daily_milestone_unknown_scan(
            reason="Daily header geometry is outside the native screen",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )
    header_bottom = max(roi[3] for roi in header_boxes)
    if not 80 <= header_bottom <= 180:
        return _daily_milestone_unknown_scan(
            reason="Daily header/chest row spacing is unsupported",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )

    raw_daily_center = selected_geometry.get("daily_center")
    daily_split_x = (
        float(raw_daily_center[0])
        if isinstance(raw_daily_center, (tuple, list))
        and len(raw_daily_center) == 2
        and isinstance(raw_daily_center[0], (int, float))
        else (daily_roi[0] + daily_roi[2]) / 2.0
    )
    left_header_boxes = tuple(
        roi
        for candidate in main_headers
        if (roi := _clamp_roi(candidate)) is not None
        and 35 <= roi[1] < roi[3] <= 200
        and roi[2] <= daily_split_x
    )
    right_header_boxes = tuple(
        roi
        for candidates in (alliance_headers, activity_headers)
        for candidate in candidates
        if (roi := _clamp_roi(candidate)) is not None
        and 35 <= roi[1] < roi[3] <= 200
        and (roi[0] + roi[2]) / 2.0 > daily_split_x
    )
    if not left_header_boxes or not right_header_boxes:
        return _daily_milestone_unknown_scan(
            reason="Daily chest row cannot be bound to both neighboring tab headers",
            source_frame_sha256=source_frame_sha256,
            points=points,
        )

    slot_pitch = frame.shape[1] * 0.175
    chest_row_center_x = (
        max(roi[2] for roi in left_header_boxes)
        + min(roi[0] for roi in right_header_boxes)
    ) / 2.0
    chest_y0 = header_bottom + 34
    chest_y1 = header_bottom + 131
    core_y0 = header_bottom + 58
    core_y1 = header_bottom + 115
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    observations: list[dict[str, Any]] = []
    claimed_tokens = tuple(
        token
        for token in daily_recognition.tokens
        if isinstance(token, Mapping)
        and token.get("text") == "claimed"
        and _clamp_roi(token.get("roi", ())) is not None
    )
    for slot in range(1, DAILY_MILESTONE_SLOT_COUNT + 1):
        center_x = int(round(chest_row_center_x + (slot - 3) * slot_pitch))
        target_roi = (
            center_x - 50,
            chest_y0,
            center_x + 50,
            chest_y1,
        )
        core_roi = (
            center_x - 38,
            core_y0,
            center_x + 39,
            core_y1,
        )
        x0, y0, x1, y1 = core_roi
        core = hsv[y0:y1, x0:x1]
        gold_body = cv2.inRange(
            core,
            np.asarray((8, 50, 35), dtype=np.uint8),
            np.asarray((48, 255, 255), dtype=np.uint8),
        )
        red_body = cv2.bitwise_or(
            cv2.inRange(
                core,
                np.asarray((0, 45, 35), dtype=np.uint8),
                np.asarray((7, 255, 255), dtype=np.uint8),
            ),
            cv2.inRange(
                core,
                np.asarray((170, 45, 35), dtype=np.uint8),
                np.asarray((179, 255, 255), dtype=np.uint8),
            ),
        )
        gold_pixels = int(cv2.countNonZero(gold_body))
        red_pixels = int(cv2.countNonZero(red_body))
        supported_skin = (
            "gold"
            if gold_pixels >= 500 and red_pixels < 500
            else "red"
            if red_pixels >= 500 and gold_pixels < 500
            else None
        )

        x0, y0, x1, y1 = target_roi
        hot_glow = cv2.inRange(
            hsv[y0:y1, x0:x1],
            np.asarray(
                (
                    DAILY_MILESTONE_GLOW_HUE_RANGE[0],
                    DAILY_MILESTONE_GLOW_MIN_SAT,
                    DAILY_MILESTONE_GLOW_MIN_VAL,
                ),
                dtype=np.uint8,
            ),
            np.asarray(
                (DAILY_MILESTONE_GLOW_HUE_RANGE[1], 255, 255),
                dtype=np.uint8,
            ),
        )
        glow_pixels = int(cv2.countNonZero(hot_glow))
        component_count, _labels, component_stats, _centroids = (
            cv2.connectedComponentsWithStats(hot_glow, connectivity=8)
        )
        largest_glow_component = max(
            (
                int(component_stats[index, cv2.CC_STAT_AREA])
                for index in range(1, component_count)
            ),
            default=0,
        )
        slot_claimed_tokens = tuple(
            token
            for token in claimed_tokens
            if center_x - slot_pitch / 2 < (token["roi"][0] + token["roi"][2]) / 2
            < center_x + slot_pitch / 2
            and header_bottom + 168 <= token["roi"][1]
            < token["roi"][3] <= header_bottom + 215
        )
        claimed_label = (
            slot_claimed_tokens[0]
            if len(slot_claimed_tokens) == 1
            and isinstance(slot_claimed_tokens[0].get("confidence"), (int, float))
            and slot_claimed_tokens[0]["confidence"] >= 60
            else None
        )
        if supported_skin is None:
            state = "unknown"
            reason = "chest appearance is unsupported or ambiguous"
        elif slot_claimed_tokens:
            if (
                claimed_label is not None
                and not (
                    glow_pixels >= DAILY_MILESTONE_GLOW_READY_PIXELS
                    and largest_glow_component >= DAILY_MILESTONE_GLOW_READY_COMPONENT
                )
            ):
                state = "claimed"
                reason = None
            else:
                state = "unknown"
                reason = "Claimed label is ambiguous or contradicts a glowing ready chest"
        elif (
            glow_pixels >= DAILY_MILESTONE_GLOW_READY_PIXELS
            and largest_glow_component >= DAILY_MILESTONE_GLOW_READY_COMPONENT
        ):
            state = "ready"
            reason = None
        elif (
            glow_pixels <= DAILY_MILESTONE_GLOW_ABSENT_PIXELS
            and largest_glow_component <= DAILY_MILESTONE_GLOW_ABSENT_COMPONENT
        ):
            state = "not_ready"
            reason = None
        else:
            state = "unknown"
            reason = "glow pixels are ambiguous for the supported chest skin"
        observations.append(
            {
                "slot_index": slot,
                "milestone_key": f"daily-milestone-slot-{slot}",
                "target_identity": DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                "target_roi": target_roi,
                "milestone_state": state,
                "milestone_ready": (
                    state == "ready" if state != "unknown" else None
                ),
                "glow_pixel_count": glow_pixels,
                "largest_glow_component": largest_glow_component,
                "supported_chest_skin": supported_skin,
                "claimed_label_roi": tuple(claimed_label["roi"]) if state == "claimed" else None,
                "claimed_label_proven": state == "claimed",
                "reason": reason,
            }
        )
    ready_count = sum(
        chest["milestone_state"] == "ready" for chest in observations
    )
    observed_count = sum(
        chest["milestone_state"] != "unknown" for chest in observations
    )
    uncertain = observed_count != DAILY_MILESTONE_SLOT_COUNT
    return {
        "status": "partial_unknown" if uncertain else "observed",
        "reason": (
            "one or more chest slots have ambiguous or unsupported appearance"
            if uncertain
            else None
        ),
        "source_frame_sha256": source_frame_sha256,
        "game_day_id": visual.get("game_day_id"),
        "header_bounds": (
            min(roi[0] for roi in header_boxes),
            min(roi[1] for roi in header_boxes),
            max(roi[2] for roi in header_boxes),
            header_bottom,
        ),
        "slot_count": DAILY_MILESTONE_SLOT_COUNT,
        "observed_chest_count": observed_count,
        "ready_chest_count": ready_count,
        "unclaimed_ready_chest_count": ready_count,
        "points": points,
        "milestones": tuple(observations),
    }


def daily_milestone_postcondition_verified(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    milestone_key: str,
) -> bool:
    """Require the bound ready chest's explicit current native Claimed label."""
    if (
        before.get("status") not in {"observed", "partial_unknown"}
        or after.get("status") not in {"observed", "partial_unknown"}
        or not before.get("game_day_id")
        or before.get("game_day_id") != after.get("game_day_id")
        or before.get("source_frame_sha256") == after.get("source_frame_sha256")
    ):
        return False
    source = [
        row for row in before.get("milestones", ())
        if isinstance(row, Mapping) and row.get("milestone_key") == milestone_key
    ]
    successor = [
        row for row in after.get("milestones", ())
        if isinstance(row, Mapping) and row.get("milestone_key") == milestone_key
    ]
    return bool(
        len(source) == len(successor) == 1
        and source[0].get("milestone_state") == "ready"
        and source[0].get("milestone_ready") is True
        and source[0].get("target_identity") == DAILY_MILESTONE_CHEST_TARGET_IDENTITY
        and source[0].get("target_roi") is not None
        and successor[0].get("slot_index") == source[0].get("slot_index")
        and isinstance(successor[0].get("target_roi"), (list, tuple))
        and len(successor[0]["target_roi"]) == len(source[0]["target_roi"]) == 4
        and max(
            abs(a - b)
            for a, b in zip(source[0]["target_roi"], successor[0]["target_roi"])
        ) <= 2
        and successor[0].get("milestone_state") == "claimed"
        and successor[0].get("claimed_label_proven") is True
        and successor[0].get("claimed_label_roi") is not None
    )


def _ensure_fresh(frame: CapturedNativeFrame, runtime: RuntimeLike) -> None:
    age = time.monotonic() - frame.captured_monotonic
    maximum = float(getattr(runtime, "frame_max_age_seconds", 30.0))
    if age < 0 or age > maximum:
        raise DailyRowClaimRecognitionError("dispatch source frame is stale")


def _ensure_runtime_ready(runtime: RuntimeLike) -> None:
    device_state = getattr(runtime, "measure_device_state", None)
    if callable(device_state) and device_state() != "device":
        raise DailyRowClaimRecognitionError("local BlueStacks device state is not ready")
    foreground = getattr(runtime, "measure_foreground_package", None)
    if callable(foreground) and foreground() != EXPECTED_PACKAGE:
        raise DailyRowClaimRecognitionError("Puzzles & Survival is not the foreground package")


def _recognize_daily_claim(
    recognizer: DailyRowClaimRecognizer | Any,
    frame: np.ndarray,
    *,
    game_day_id: str | None,
    wall_utc: Callable[[], datetime] | None = None,
) -> FrameRecognition:
    kwargs: dict[str, Any] = {"game_day_id": game_day_id}
    if wall_utc is not None and hasattr(recognizer, "_ocr"):
        kwargs["observed_utc"] = wall_utc() if wall_utc is not None else None
    return recognizer.recognize_daily_claim(frame, **kwargs)


def _require_recognition(
    recognition: FrameRecognition,
    *,
    state: str,
    target_identity: str | None = None,
) -> None:
    if not recognition.recognized or recognition.state != state:
        raise DailyRowClaimRecognitionError(recognition.reason or f"{state.lower()} recognition failed")
    if target_identity is not None and recognition.target_identity != target_identity:
        raise DailyRowClaimRecognitionError("recognized target identity is not manifest-bound")
    if target_identity is not None and recognition.target_roi is None:
        raise DailyRowClaimRecognitionError("recognized target geometry is missing")


def _frame_ref(frame: CapturedNativeFrame, session_directory: Any) -> dict[str, Any]:
    path = frame.path
    try:
        relative = path.resolve().relative_to(session_directory.resolve())
        path_value = str(relative).replace("\\", "/")
    except (AttributeError, OSError, ValueError):
        path_value = str(path)
    return {
        "path": path_value,
        "sha256": frame.sha256,
        "captured_monotonic": frame.captured_monotonic,
    }


def daily_claim_observation_from_recognition(
    recognition: FrameRecognition,
    *,
    source_frame_sha256: str,
    evidence_ref: str,
    game_day_id: str | None,
    aggregate_batch_identity: str,
) -> AvailableDailyClaimObservation | None:
    """Project one current-frame recognition into the offline claim contract."""

    evidence = dict(recognition.visual_evidence or {})
    if not evidence.get("selected_daily"):
        return None
    row_bounds = evidence.get("row_bounds") or (0, 0, 1, 1)
    target_roi = evidence.get("claim_roi") or (0, 0, 1, 1)
    if not (
        isinstance(row_bounds, (tuple, list))
        and len(row_bounds) == 4
        and isinstance(target_roi, (tuple, list))
        and len(target_roi) == 4
    ):
        return None
    bound_game_day_id = str(game_day_id or evidence.get("game_day_id") or "")
    return AvailableDailyClaimObservation(
        screen_state="DAILY_QUEST",
        selected_daily_quest=True,
        objective_key=str(evidence.get("objective_key") or ""),
        objective_name=str(evidence.get("objective_name") or ""),
        current_progress=int(evidence.get("current_progress") or 0),
        required_progress=int(evidence.get("required_progress") or 0),
        row_bounds=tuple(int(value) for value in row_bounds),
        target_identity="daily-quest-claim" if evidence.get("claim_ready") else "",
        target_roi=tuple(int(value) for value in target_roi),
        control_class="CLAIM" if evidence.get("claim_ready") else "",
        row_fully_visible=bool(evidence.get("row_fully_visible")),
        claim_fully_visible=bool(evidence.get("claim_fully_visible")),
        cost_type=str(evidence.get("cost_type") or "unknown"),
        cost_amount=evidence.get("cost_amount"),
        quantity=int(evidence.get("quantity") or 0) if evidence.get("quantity") is not None else None,
        game_day_id=bound_game_day_id,
        target_provenance=BLUESTACKS_TARGET_PROVENANCE,
        source_frame_sha256=source_frame_sha256,
        evidence_refs=(evidence_ref,),
        milestone_reward=bool(evidence.get("milestone_reward")),
        clipped=not bool(evidence.get("claim_fully_visible")),
        overlay_state="none" if not evidence.get("full_frame_overlay", {}).get("recognized") else "unknown",
        reset_guard_active=False,
        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        recognized=bool(recognition.recognized),
        points=evidence.get("points"),
        reward_points=evidence.get("reward_points"),
        reset_timer=evidence.get("reset_timer"),
        catalog_reconciled=False,
        ordinary_reward_claim=evidence.get("ordinary_reward_claim"),
        free_control_proven=evidence.get("free_control_proven"),
        quantity_one_proven=evidence.get("quantity_one_proven"),
        cost_region_scan=evidence.get("cost_region_scan"),
        cost_icon_scan=evidence.get("cost_icon_scan"),
        row_panel_proven=evidence.get("row_panel_geometry", {}).get("proven")
        if isinstance(evidence.get("row_panel_geometry"), Mapping)
        else None,
        row_panel_source=str(
            evidence.get("row_panel_geometry", {}).get("source") or ""
        )
        if isinstance(evidence.get("row_panel_geometry"), Mapping)
        else "",
        reset_timer_seconds=evidence.get("reset_timer_seconds"),
        reset_observed_utc=evidence.get("reset_observed_utc"),
        reset_deadline_utc=evidence.get("reset_deadline_utc"),
        reset_deadline_identity=evidence.get("reset_deadline_identity"),
        reset_deadline_tolerance_seconds=evidence.get(
            "reset_deadline_tolerance_seconds"
        ),
        available_claim_controls=(
            int(evidence["available_claim_controls"])
            if isinstance(evidence.get("available_claim_controls"), int)
            and not isinstance(evidence.get("available_claim_controls"), bool)
            else None
        ),
        aggregate_batch_identity=aggregate_batch_identity,
    )


def daily_claim_postcondition_verified(
    before: FrameRecognition,
    after: FrameRecognition | None,
    *,
    game_day_id: str,
) -> bool:
    """Require selected Daily/reset continuity and exhaustion of Claim controls."""

    before_evidence = dict(before.visual_evidence or {})
    after_evidence = dict((after.visual_evidence if after is not None else {}) or {})
    if (
        not before.recognized
        or before.state != DAILY_SELECTED_STATE
        or before_evidence.get("claim_scan_complete") is not True
        or before_evidence.get("recognized_claim_controls", 0) < 1
        or before_evidence.get("claim_ready") is not True
        or after is None
        or not after.recognized
        or after.target_identity is not None
        or after.target_roi is not None
        or after.state != DAILY_SELECTED_STATE
        or after_evidence.get("selected_daily") is not True
        or before_evidence.get("game_day_id") != game_day_id
        or after_evidence.get("game_day_id") != game_day_id
        or after_evidence.get("reset_timer") is None
        or after_evidence.get("claim_ready") is not False
        or bool(after_evidence.get("full_frame_overlay", {}).get("recognized"))
    ):
        return False
    before_deadline = before_evidence.get("reset_deadline_identity")
    after_deadline = after_evidence.get("reset_deadline_identity")
    if (
        not isinstance(before_deadline, str)
        or not isinstance(after_deadline, str)
        or not _reset_deadline_identities_match(
            before_deadline,
            after_deadline,
            tolerance_seconds=RESET_DEADLINE_TOLERANCE_SECONDS,
        )
        or not _reset_deadline_identities_match(
            before_deadline,
            game_day_id,
            tolerance_seconds=RESET_DEADLINE_TOLERANCE_SECONDS,
        )
    ):
        return False
    before_seconds = before_evidence.get("reset_timer_seconds")
    after_seconds = after_evidence.get("reset_timer_seconds")
    if not isinstance(before_seconds, int) or not isinstance(after_seconds, int):
        return False
    tolerance = max(
        0,
        int(
            after_evidence.get("reset_deadline_tolerance_seconds")
            or before_evidence.get("reset_deadline_tolerance_seconds")
            or RESET_DEADLINE_TOLERANCE_SECONDS
        ),
    )
    # A countdown may stay on the same displayed second briefly, but it
    # must never jump forward.  This explicitly rejects 00:00:02 ->
    # 23:59:58 at rollover even when the successor remains otherwise
    # plausible.
    if after_seconds - before_seconds > tolerance:
        return False
    before_observed = before_evidence.get("reset_observed_utc")
    after_observed = after_evidence.get("reset_observed_utc")
    if not isinstance(before_observed, str) or not isinstance(after_observed, str):
        return False
    try:
        before_utc = _coerce_wall_utc(before_observed)
        after_utc = _coerce_wall_utc(after_observed)
        elapsed = max(0.0, (after_utc - before_utc).total_seconds())
    except (TypeError, ValueError):
        return False
    if abs((before_seconds - after_seconds) - elapsed) > tolerance + 1.0:
        return False
    if (
        after_evidence.get("claim_scan_complete") is not True
        or after_evidence.get("zero_claim_scan_proven") is not True
        or after_evidence.get("recognized_claim_controls") != 0
        or after_evidence.get("available_claim_controls") != 0
    ):
        return False
    return True


def _failure(
    session: SessionLike,
    *,
    reason: str,
    frames: Mapping[str, CapturedNativeFrame],
    recognitions: Mapping[str, FrameRecognition],
    polls: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    session.terminal_status = "evidence_required"
    session.blocker = reason
    session.next_action = "retain evidence_required and repair recognition or transport"
    return {
        "status": "evidence_required",
        "reason": reason,
        "input_count": int(session.input_count),
        "resource_affecting_inputs": 0,
        "combat_confirmations": 0,
        "frames": {
            name: _frame_ref(frame, session.session_directory)
            for name, frame in frames.items()
        },
        "recognitions": {
            name: recognition.as_dict() for name, recognition in recognitions.items()
        },
        "polls": [dict(poll) for poll in polls],
        "actions": [dict(row) for row in session.actions],
    }



def _settle_successor(
    *,
    session: SessionLike,
    capture: Callable[[str], CapturedNativeFrame],
    immediate_post: CapturedNativeFrame,
    recognize: Callable[[np.ndarray], FrameRecognition],
    expected_states: tuple[str, ...],
    action_identity: str,
    frame_key: str,
    recognition_key: str,
    frames: dict[str, CapturedNativeFrame],
    recognitions: dict[str, FrameRecognition],
    polls: list[dict[str, Any]],
) -> FrameRecognition:
    """Poll fresh frames after one input without dispatching another input."""

    def record(
        frame: CapturedNativeFrame,
        recognition: FrameRecognition,
        *,
        attempt: int,
        label: str,
    ) -> None:
        frame_name = frame_key if attempt == 0 else f"{recognition_key}_poll_{attempt}"
        frames[frame_name] = frame
        recognitions[frame_name] = recognition
        polls.append(
            {
                "action_identity": action_identity,
                "attempt": attempt,
                "label": label,
                "frame_name": frame_name,
                "frame": _frame_ref(frame, session.session_directory),
                "recognition": recognition.as_dict(),
            }
        )

    current = immediate_post
    current_recognition = recognize(current.frame)
    record(
        current,
        current_recognition,
        attempt=0,
        label=f"{action_identity}-immediate-post",
    )
    if current_recognition.recognized and current_recognition.state in expected_states:
        recognitions[recognition_key] = current_recognition
        return current_recognition

    deadline = time.monotonic() + SUCCESSOR_POLL_TIMEOUT_SECONDS
    attempts = 0
    while attempts < SUCCESSOR_POLL_MAX_ATTEMPTS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        interval = max(0.0, min(SUCCESSOR_POLL_INTERVAL_SECONDS, remaining))
        if interval:
            time.sleep(interval)
        if time.monotonic() >= deadline:
            break
        attempts += 1
        label = f"{action_identity}-poll-{attempts:02d}"
        current = session.observe(capture, label=label)
        current_recognition = recognize(current.frame)
        record(current, current_recognition, attempt=attempts, label=label)
        if current_recognition.recognized and current_recognition.state in expected_states:
            recognitions[recognition_key] = current_recognition
            frames[frame_key] = current
            return current_recognition

    recognitions[recognition_key] = current_recognition
    return current_recognition


def run_daily_row_reconnaissance(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    recognizer: DailyRowClaimRecognizer | Any | None = None,
) -> dict[str, Any]:
    """Reach selected Daily from Home, accepting a directly resumed Daily tab."""

    if not bool(getattr(runtime, "execute", False)):
        return _failure(
            session,
            reason="runtime execution is required for reconnaissance",
            frames={},
            recognitions={},
        )
    recognizer = recognizer or DailyRowClaimRecognizer()
    frames: dict[str, CapturedNativeFrame] = {}
    recognitions: dict[str, FrameRecognition] = {}
    polls: list[dict[str, Any]] = []

    try:
        def capture(label: str) -> CapturedNativeFrame:
            captured = runtime.capture(label)
            frame_names = {
                "home-source": "source",
                "home-quest-entry-immediate-before": "home_immediate_before",
                "home-quest-entry-immediate-post": "quest_successor",
                "quest-daily-tab-immediate-before": "daily_immediate_before",
                "quest-daily-tab-immediate-post": "daily_terminal",
            }
            name = frame_names.get(label)
            if name is None and label.startswith(f"{HOME_QUEST_IDENTITY}-poll-"):
                name = f"quest_successor_poll_{label.rsplit('-', 1)[-1]}"
            if name is None and label.startswith(f"{QUEST_DAILY_IDENTITY}-poll-"):
                name = f"daily_terminal_poll_{label.rsplit('-', 1)[-1]}"
            if name is not None:
                frames[name] = captured
            return captured

        source = session.observe(capture, label="home-source")
        frames["source"] = source
        source_recognition = recognizer.recognize_home(source.frame)
        recognitions["source"] = source_recognition
        _require_recognition(
            source_recognition,
            state=HOME_STATE,
            target_identity=HOME_QUEST_IDENTITY,
        )

        first_post_recognition: FrameRecognition | None = None

        def dispatch_quest(before: CapturedNativeFrame) -> None:
            rebound = recognizer.recognize_home(before.frame)
            recognitions["home_immediate_before"] = rebound
            _require_recognition(
                rebound,
                state=HOME_STATE,
                target_identity=HOME_QUEST_IDENTITY,
            )
            _ensure_fresh(before, runtime)
            _ensure_runtime_ready(runtime)
            runtime.tap(
                before,
                target_identity=HOME_QUEST_IDENTITY,
                target_roi=rebound.target_roi,  # type: ignore[arg-type]
                action_key=HOME_QUEST_IDENTITY,
            )

        def recognize_quest_or_daily(frame: np.ndarray) -> FrameRecognition:
            quest = recognizer.recognize_quest(frame)
            if quest.recognized and quest.state == QUEST_STATE:
                return quest
            return recognizer.recognize_daily_selected(frame)

        def recognize_quest_successor(after: CapturedNativeFrame) -> str:
            nonlocal first_post_recognition
            first_post_recognition = _settle_successor(
                session=session,
                capture=capture,
                immediate_post=after,
                recognize=recognize_quest_or_daily,
                expected_states=(QUEST_STATE, DAILY_SELECTED_STATE),
                action_identity=HOME_QUEST_IDENTITY,
                frame_key="quest_successor",
                recognition_key="quest_successor",
                frames=frames,
                recognitions=recognitions,
                polls=polls,
            )
            return first_post_recognition.state if first_post_recognition.recognized else UNKNOWN_STATE

        quest_dispatch = _NativeTapDispatch(dispatch_quest)
        first_action = session.run_action(
            action_class=NAVIGATION_ACTION_CLASS,
            label=HOME_QUEST_IDENTITY,
            capture=capture,
            dispatch=quest_dispatch.dispatch,
            recognize=recognize_quest_successor,
            consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
        )
        if (
            first_action.status != "completed"
            or first_post_recognition is None
            or not first_post_recognition.recognized
        ):
            return _failure(
                session,
                reason="Quest successor was not positively recognized",
                frames=frames,
                recognitions=recognitions,
                polls=polls,
            )

        if first_post_recognition.state == DAILY_SELECTED_STATE:
            frames["daily_terminal"] = frames["quest_successor"]
            recognitions["daily_terminal"] = first_post_recognition
        else:
            second_post_recognition: FrameRecognition | None = None

            def dispatch_daily(before: CapturedNativeFrame) -> None:
                rebound = recognizer.recognize_quest(before.frame)
                recognitions["daily_immediate_before"] = rebound
                _require_recognition(
                    rebound,
                    state=QUEST_STATE,
                    target_identity=QUEST_DAILY_IDENTITY,
                )
                _ensure_fresh(before, runtime)
                _ensure_runtime_ready(runtime)
                runtime.tap(
                    before,
                    target_identity=QUEST_DAILY_IDENTITY,
                    target_roi=rebound.target_roi,  # type: ignore[arg-type]
                    action_key=QUEST_DAILY_IDENTITY,
                )

            def recognize_daily_successor(after: CapturedNativeFrame) -> str:
                nonlocal second_post_recognition
                second_post_recognition = _settle_successor(
                    session=session,
                    capture=capture,
                    immediate_post=after,
                    recognize=recognizer.recognize_daily_selected,
                    expected_states=(DAILY_SELECTED_STATE,),
                    action_identity=QUEST_DAILY_IDENTITY,
                    frame_key="daily_terminal",
                    recognition_key="daily_terminal",
                    frames=frames,
                    recognitions=recognitions,
                    polls=polls,
                )
                return second_post_recognition.state if second_post_recognition.recognized else UNKNOWN_STATE

            daily_dispatch = _NativeTapDispatch(dispatch_daily)
            second_action = session.run_action(
                action_class=NAVIGATION_ACTION_CLASS,
                label=QUEST_DAILY_IDENTITY,
                capture=capture,
                dispatch=daily_dispatch.dispatch,
                recognize=recognize_daily_successor,
                consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
            )
            if (
                second_action.status != "completed"
                or second_post_recognition is None
                or not second_post_recognition.recognized
            ):
                return _failure(
                    session,
                    reason="selected Daily terminal was not positively recognized",
                    frames=frames,
                    recognitions=recognitions,
                    polls=polls,
                )

        return {
            "status": "observed",
            "reason": "selected Daily positively recognized",
            "input_count": int(session.input_count),
            "resource_affecting_inputs": 0,
            "combat_confirmations": 0,
            "frames": {
                name: _frame_ref(frame, session.session_directory)
                for name, frame in frames.items()
            },
            "recognitions": {
                name: recognition.as_dict() for name, recognition in recognitions.items()
            },
            "polls": [dict(poll) for poll in polls],
            "actions": [dict(row) for row in session.actions],
        }
    except BaseException as exc:
        return _failure(
            session,
            reason=f"{type(exc).__name__}: {exc}",
            frames=frames,
            recognitions=recognitions,
            polls=polls,
        )







def _generic_modal_overlay_evidence(frame: np.ndarray) -> dict[str, Any]:
    """Prove that no large current-frame modal panel remains after close."""

    if not _frame_shape_ok(frame):
        return {
            "recognized": True,
            "state": "unknown",
            "panel_candidates": (),
            "reason": "profile_dimensions_mismatch",
        }
    try:
        panel_candidates = tuple(_accepted_visual_popup_panel_candidates(frame))
    except Exception as exc:
        return {
            "recognized": True,
            "state": "unknown",
            "panel_candidates": (),
            "reason": f"visual-panel-detector-failed:{type(exc).__name__}",
        }
    if panel_candidates:
        return {
            "recognized": True,
            "state": "modal",
            "panel_candidates": panel_candidates,
            "reason": "current-frame-visual-popup-panel-detected",
        }
    return {
        "recognized": False,
        "state": "none_observed",
        "panel_candidates": (),
        "reason": "no-current-frame-visual-popup-panel-detected",
    }


def _daily_aggregate_action_key(
    account_id: str,
    server_id: str,
    reset_id: str,
    game_day_id: str,
    batch_identity: str,
) -> str:
    identity = (account_id, server_id, reset_id, game_day_id, batch_identity)
    if any(not isinstance(value, str) or not value.strip() for value in identity):
        raise ValueError("Daily aggregate action key requires exact account/reset/batch identity")
    material = "".join(f"{len(value)}:{value}" for value in identity)
    return "daily-rewards:aggregate:" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def run_daily_rewards_from_home(context: Any, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    """Maintain the current free Daily reward batch through the canonical journal."""
    from safe_action_core import (
        ActionClass,
        ActionStatus,
        CentralPolicy,
        Observation,
        PolicyRequest,
        SafeActionExecutor,
        TransportResult,
    )
    from dataclasses import replace
    from tasks.runtime_identity import BLUESTACKS_PACKAGE

    if (
        not isinstance(arguments, Mapping)
        or type(arguments.get("observation_interval_seconds")) is not int
        or not 1 <= arguments["observation_interval_seconds"] <= 86400
    ):
        return {
            "status": "blocked",
            "reason": "invalid observation cadence",
            "total_input_count": None,
            "total_action_count": 0,
            "reward_claim_transport_calls": 0,
            "committed_action_count": 0,
            "accounting_verified": False,
            "terminal_home_verified": False,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "aggregate_claim": {
                "status": "none",
                "dispatch_count": 0,
                "confirmed": False,
            },
            "chests_collected": [],
            "observed_points": {"before": None, "after": None},
            "milestone_scan": {
                "status": "unproven",
                "reason": "invalid observation cadence",
            },
            "unclaimed_ready_chest_count": None,
            "no_work": False,
        }
    context.validate_identity()
    start_accounting = context.accounting()
    runtime, session, store = context.runtime, context.session, context.action_store
    recognizer = DailyRowClaimRecognizer()
    initial = context.initial_frame
    home = recognizer.recognize_home(initial.frame)
    if not context.is_clean_home(initial.frame) or not home.recognized:
        return {
            "status": "blocked",
            "reason": "fresh clean recognized Home is required before Daily rewards",
            "total_input_count": start_accounting.input_count,
            "total_action_count": 0,
            "reward_claim_transport_calls": 0,
            "committed_action_count": 0,
            "accounting_verified": start_accounting.verified,
            "terminal_home_verified": False,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "aggregate_claim": {
                "status": "none",
                "dispatch_count": 0,
                "confirmed": False,
            },
            "chests_collected": [],
            "observed_points": {"before": None, "after": None},
            "milestone_scan": {
                "status": "unproven",
                "reason": "Daily surface was not reached from Home",
            },
            "unclaimed_ready_chest_count": None,
            "no_work": False,
        }
    context.bind_initial_observation(
        initial,
        extra={"daily_rewards_start_state": HOME_STATE},
    )
    reconnaissance = run_daily_row_reconnaissance(runtime, session, recognizer=recognizer)
    context.validate_identity()
    if reconnaissance.get("status") != "observed":
        accounting = context.accounting()
        return {
            "status": "blocked",
            "reason": "Home-to-Quest-to-Daily reconnaissance was not verified",
            "reconnaissance": reconnaissance,
            "total_input_count": accounting.input_count,
            "total_action_count": 0,
            "reward_claim_transport_calls": 0,
            "committed_action_count": 0,
            "accounting_verified": accounting.verified,
            "terminal_home_verified": False,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "aggregate_claim": {
                "status": "none",
                "dispatch_count": 0,
                "confirmed": False,
            },
            "chests_collected": [],
            "observed_points": {"before": None, "after": None},
            "milestone_scan": {
                "status": "unproven",
                "reason": "selected Daily was not verified",
            },
            "unclaimed_ready_chest_count": None,
            "no_work": False,
        }

    utc_now = lambda: datetime.fromtimestamp(context.utc_clock(), timezone.utc)

    def recognize(captured: CapturedNativeFrame, game_day_id: str | None = None):
        return _recognize_daily_claim(
            recognizer,
            captured.frame,
            game_day_id=game_day_id,
            wall_utc=utc_now,
        )

    proposal_capture = session.observe(
        runtime.capture,
        label="daily-rewards-aggregate-proposal",
    )
    proposal_recognition = recognize(proposal_capture)
    proposal_visual = dict(proposal_recognition.visual_evidence or {})
    proposal_game_day = str(proposal_visual.get("game_day_id") or "")
    proposal = daily_claim_observation_from_recognition(
        proposal_recognition,
        source_frame_sha256=proposal_capture.sha256,
        evidence_ref=str(proposal_capture.path),
        game_day_id=proposal_game_day,
        aggregate_batch_identity=context.occurrence_key,
    )
    milestone_scan = recognize_daily_milestone_chests(
        proposal_capture.frame,
        proposal_recognition,
        source_frame_sha256=proposal_capture.sha256,
    )
    scan_is_observed = milestone_scan.get("status") in {
        "observed",
        "partial_unknown",
    }
    ready_chest_count = (
        milestone_scan.get("ready_chest_count", 0)
        if scan_is_observed
        else None
    )
    ready_chest_count = (
        ready_chest_count if type(ready_chest_count) is int else None
    )

    def has_complete_zero_control_scan(recognition: FrameRecognition) -> bool:
        visual = dict(recognition.visual_evidence or {})
        return bool(
            recognition.recognized
            and recognition.state == DAILY_SELECTED_STATE
            and recognition.target_identity is None
            and recognition.target_roi is None
            and visual.get("selected_daily") is True
            and visual.get("claim_scan_complete") is True
            and visual.get("claim_scan_raw_gold_pixel_count") == 0
            and visual.get("zero_claim_scan_proven") is True
            and visual.get("recognized_claim_controls") == 0
            and visual.get("available_claim_controls") == 0
            and isinstance(visual.get("game_day_id"), str)
            and visual["game_day_id"].strip()
            and isinstance(visual.get("reset_deadline_identity"), str)
            and visual["reset_deadline_identity"].strip()
        )

    def has_five_static_chests(scan: Mapping[str, Any]) -> bool:
        chests = scan.get("milestones")
        keys = [
            chest.get("milestone_key")
            for chest in chests
            if isinstance(chest, Mapping)
        ] if isinstance(chests, (tuple, list)) else []
        return bool(
            scan.get("status") == "observed"
            and scan.get("slot_count") == DAILY_MILESTONE_SLOT_COUNT
            and scan.get("observed_chest_count") == DAILY_MILESTONE_SLOT_COUNT
            and scan.get("ready_chest_count") == 0
            and isinstance(chests, (tuple, list))
            and len(chests) == DAILY_MILESTONE_SLOT_COUNT
            and len(keys) == DAILY_MILESTONE_SLOT_COUNT
            and all(isinstance(key, str) and key.strip() for key in keys)
            and len(set(keys)) == DAILY_MILESTONE_SLOT_COUNT
            and all(
                isinstance(chest, Mapping)
                and chest.get("milestone_state") in {"not_ready", "claimed"}
                and chest.get("milestone_ready") is False
                and chest.get("target_roi") is not None
                for chest in chests
            )
        )

    def verified_static_scan(
        scan: Mapping[str, Any],
        collected: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not has_five_static_chests(scan):
            raise DailyRowClaimRecognitionError(
                "all five current milestone chests were not positively observed static"
            )
        ready_keys = [str(chest["milestone_key"]) for chest in collected]
        static_keys = [
            str(chest["milestone_key"])
            for chest in scan["milestones"]
            if chest["milestone_key"] not in ready_keys
        ]
        if len(set(ready_keys)) != len(ready_keys) or any(
            chest.get("milestone_state") != "claimed"
            for chest in scan["milestones"]
            if chest["milestone_key"] in ready_keys
        ):
            raise DailyRowClaimRecognitionError("collected chest successor is no longer proven")
        return {
            **dict(scan),
            "status": "verified",
            "selected_daily": True,
            "reset_id": context.identity.reset_id,
            # These keys describe the pass's positively admitted ready sources;
            # the retained terminal rows below show their current Claimed state.
            "ready_chest_count": len(ready_keys),
            "ready_chest_keys": ready_keys,
            "remaining_ready_chest_count": 0,
            "static_or_locked_chest_keys": static_keys,
        }

    def same_daily_reset(
        before: FrameRecognition,
        current: FrameRecognition,
    ) -> bool:
        before_visual = dict(before.visual_evidence or {})
        current_visual = dict(current.visual_evidence or {})
        before_deadline = before_visual.get("reset_deadline_identity")
        current_deadline = current_visual.get("reset_deadline_identity")
        return bool(
            before_visual.get("game_day_id")
            and before_visual.get("game_day_id") == current_visual.get("game_day_id")
            and isinstance(before_deadline, str)
            and isinstance(current_deadline, str)
            and _reset_deadline_identities_match(
                before_deadline,
                current_deadline,
                tolerance_seconds=RESET_DEADLINE_TOLERANCE_SECONDS,
            )
        )

    def return_home_from_static_daily(
        reference_recognition: FrameRecognition,
    ) -> tuple[
        CapturedNativeFrame | None,
        Mapping[str, Any] | None,
        FrameRecognition | None,
        str | None,
    ]:
        """Back out only from a fresh, unchanged, complete zero-ready Daily scan."""
        source: dict[str, Any] = {}
        terminal: dict[str, CapturedNativeFrame] = {}
        reference_day = str(
            dict(reference_recognition.visual_evidence or {}).get("game_day_id")
            or ""
        )

        for ordinal in range(1, 3):
            successor_state = {"value": UNKNOWN_STATE}
            label = f"daily-rewards:return-home-back-{ordinal}"

            def authorize(before: CapturedNativeFrame) -> None:
                context.validate_identity()
                _ensure_fresh(before, runtime)
                _ensure_runtime_ready(runtime)
                if ordinal == 1:
                    current = recognize(before, reference_day)
                    current_scan = recognize_daily_milestone_chests(
                        before.frame,
                        current,
                        source_frame_sha256=before.sha256,
                    )
                    source.update(
                        capture=before,
                        recognition=current,
                        scan=current_scan,
                    )
                    if not has_complete_zero_control_scan(current):
                        raise DailyRowClaimRecognitionError(
                            "fresh selected Daily has no complete positive zero-Claim scan"
                        )
                    if not same_daily_reset(reference_recognition, current):
                        raise DailyRowClaimRecognitionError(
                            "fresh selected Daily reset identity changed before Home return"
                        )
                    if not has_five_static_chests(current_scan):
                        raise DailyRowClaimRecognitionError(
                            "fresh Daily chest scan is ready, unknown, or incomplete"
                        )
                else:
                    quest = recognizer.recognize_quest(before.frame)
                    if not quest.recognized or quest.state != QUEST_STATE:
                        raise DailyRowClaimRecognitionError(
                            "fresh intermediate Quest surface was not positively recognized"
                        )

            def dispatch(before: CapturedNativeFrame) -> None:
                context.validate_identity()
                _ensure_fresh(before, runtime)
                _ensure_runtime_ready(runtime)
                runtime.back(
                    before,
                    action_key=f"{label}:{before.sha256}",
                    target_identity="android-back",
                )

            def recognize_return(after: CapturedNativeFrame) -> str:
                if context.is_clean_home(after.frame):
                    home_recognition = recognizer.recognize_home(after.frame)
                    if home_recognition.recognized and home_recognition.state == HOME_STATE:
                        terminal["capture"] = after
                        successor_state["value"] = HOME_STATE
                        return HOME_STATE
                quest = recognizer.recognize_quest(after.frame)
                if quest.recognized and quest.state == QUEST_STATE:
                    successor_state["value"] = QUEST_STATE
                    return QUEST_STATE
                successor_state["value"] = UNKNOWN_STATE
                return UNKNOWN_STATE

            def settled_successor() -> CapturedNativeFrame:
                delay = float(getattr(context, "settle_seconds", 0.0))
                if delay > 0:
                    time.sleep(delay)
                return session.observe(
                    runtime.capture,
                    label=f"{label}-settled-successor",
                )

            try:
                outcome = session.run_action(
                    action_class=NAVIGATION_ACTION_CLASS,
                    label=label,
                    capture=runtime.capture,
                    authorize=authorize,
                    dispatch=dispatch,
                    recognize=recognize_return,
                    settled_successor=settled_successor,
                    consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
                )
            except Exception as exc:
                return (
                    None,
                    source.get("scan"),
                    source.get("recognition"),
                    f"{type(exc).__name__}: {exc}",
                )
            if outcome.status != "completed":
                return (
                    None,
                    source.get("scan"),
                    source.get("recognition"),
                    "system Back did not produce a positively recognized successor",
                )
            if successor_state["value"] == HOME_STATE:
                try:
                    context.validate_identity()
                except Exception as exc:
                    return (
                        None,
                        source.get("scan"),
                        source.get("recognition"),
                        f"identity validation failed after Home return: {exc}",
                    )
                return (
                    terminal.get("capture"),
                    source.get("scan"),
                    source.get("recognition"),
                    None,
                )
            if successor_state["value"] != QUEST_STATE:
                return (
                    None,
                    source.get("scan"),
                    source.get("recognition"),
                    "system Back successor was neither verified Home nor verified Quest",
                )

        return (
            None,
            source.get("scan"),
            source.get("recognition"),
            "two bounded system Back actions did not reach verified Home",
        )

    def close_static_daily(
        result: dict[str, Any],
        reference_recognition: FrameRecognition,
        *,
        no_work: bool,
    ) -> dict[str, Any]:
        home_capture, source_scan, source_recognition, return_error = (
            return_home_from_static_daily(reference_recognition)
        )
        if source_scan is not None:
            result["milestone_scan"] = source_scan
            source_ready_count = source_scan.get("ready_chest_count")
            result["unclaimed_ready_chest_count"] = (
                source_ready_count if type(source_ready_count) is int else None
            )
        if source_scan is not None and not has_five_static_chests(source_scan):
            accounting_now = context.accounting()
            if (
                source_recognition is not None
                and has_complete_zero_control_scan(source_recognition)
            ):
                source_ready_count = source_scan.get("ready_chest_count")
                if type(source_ready_count) is int and source_ready_count > 0:
                    reason = (
                        f"{source_ready_count} ready Daily milestone chest(es) remain "
                        "at the fresh Home-return boundary; completion is deferred."
                    )
                else:
                    reason = (
                        "Fresh Daily chest scan contains unknown or unsupported slots; "
                        "no chest input was sent and unsupported appearance is not "
                        "treated as locked or opened."
                    )
                status = "evidence_required"
            else:
                reason = (
                    "Fresh Daily zero-Claim and complete chest-state evidence changed "
                    "before Home return."
                )
                status = "blocked" if no_work else "evidence_required"
            result.update(
                status=status,
                reason=reason,
                total_input_count=accounting_now.input_count,
                accounting_verified=accounting_now.verified,
                terminal_home_verified=False,
                no_work=False,
            )
            return result
        if home_capture is None or source_scan is None:
            accounting_now = context.accounting()
            result.update(
                status="blocked" if no_work else "evidence_required",
                reason=(
                    "Complete zero-ready Daily evidence was not sufficient to prove "
                    f"a clean Home return: {return_error or 'required evidence is missing'}"
                ),
                total_input_count=accounting_now.input_count,
                accounting_verified=accounting_now.verified,
                terminal_home_verified=False,
                no_work=False,
            )
            return result

        try:
            scan_projection = verified_static_scan(source_scan, result["chests_collected"])
            accounting_now = context.accounting()
            terminal_ref = _frame_ref(home_capture, runtime.session)
            terminal_path = terminal_ref["path"]
            if not isinstance(terminal_path, str) or not terminal_path:
                raise DailyRowClaimRecognitionError(
                    "retained verified Home frame reference is unavailable"
                )
        except Exception as exc:
            accounting_now = context.accounting()
            result.update(
                status="blocked" if no_work else "evidence_required",
                reason=f"verified Home result evidence is incomplete: {exc}",
                total_input_count=accounting_now.input_count,
                accounting_verified=accounting_now.verified,
                terminal_home_verified=False,
                no_work=False,
            )
            return result
        if (
            not accounting_now.verified
            or source_recognition is None
            or not has_complete_zero_control_scan(source_recognition)
        ):
            result.update(
                status="blocked" if no_work else "evidence_required",
                reason=(
                    "Clean Home was recognized but native accounting or the complete "
                    "zero-Claim source proof is unavailable."
                ),
                total_input_count=accounting_now.input_count,
                accounting_verified=accounting_now.verified,
                terminal_home_verified=True,
                terminal_home_frame={
                    "frame_path": terminal_ref["path"],
                    "frame_sha256": terminal_ref["sha256"],
                },
                native_session_directory=str(runtime.session),
                milestone_scan=scan_projection,
                no_work=False,
            )
            return result
        source_visual = dict(source_recognition.visual_evidence or {})
        static_keys = scan_projection["static_or_locked_chest_keys"]
        result.update(
            status="completed",
            reason=(
                "No aggregate Claim was available; all five current Daily milestone "
                "chests were positively observed static/not ready, and clean Home was "
                "verified."
                if no_work
                else (
                    "Current free Daily rewards were confirmed; all five milestone "
                    "chests are now claimed or not ready, and clean Home was verified."
                )
            ),
            total_input_count=accounting_now.input_count,
            accounting_verified=True,
            terminal_home_verified=True,
            terminal_home_frame={
                "frame_path": terminal_ref["path"],
                "frame_sha256": terminal_ref["sha256"],
            },
            native_session_directory=str(runtime.session),
            milestone_scan=scan_projection,
            unclaimed_ready_chest_count=0,
            no_work=no_work,
        )
        if no_work:
            result["no_work_evidence"] = {
                "selected_daily": True,
                "reset_id": context.identity.reset_id,
                "source_frame_sha256": source_scan.get("source_frame_sha256"),
                "ordinary_claim_controls": source_visual.get(
                    "available_claim_controls"
                ),
                "ready_chest_count": 0,
                "static_or_locked_chest_keys": list(static_keys),
            }
        else:
            result["no_work_evidence"] = None
        return result

    accounting = context.accounting()
    empty_aggregate = {
        "status": "none",
        "dispatch_count": 0,
        "confirmed": False,
    }
    base: dict[str, Any] = {
        "status": "blocked",
        "total_input_count": accounting.input_count,
        "total_action_count": 0,
        "reward_claim_transport_calls": 0,
        "committed_action_count": 0,
        "accounting_verified": accounting.verified,
        "terminal_home_verified": False,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "aggregate_claim": empty_aggregate,
        "chests_collected": [],
        "observed_points": {"before": proposal_visual.get("points"), "after": None},
        "reconnaissance": reconnaissance,
        "milestone_scan": milestone_scan,
        "unclaimed_ready_chest_count": ready_chest_count,
        "no_work": False,
    }
    def claim_ready_chests(
        result: dict[str, Any],
        captured: CapturedNativeFrame,
        recognition: FrameRecognition,
        scan: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Claim each freshly bound ready slot once; UNKNOWN never retries input."""
        def refresh_accounting() -> None:
            accounting_now = context.accounting()
            result.update(
                total_input_count=accounting_now.input_count,
                accounting_verified=accounting_now.verified,
            )

        for _ in range(DAILY_MILESTONE_SLOT_COUNT):
            context.checkpoint()
            context.validate_identity()
            if not has_complete_zero_control_scan(recognition):
                result.update(
                    status="evidence_required",
                    reason="Current ordinary Claim batch is not positively clear; chest phase deferred.",
                )
                return result
            ready = [
                row for row in scan.get("milestones", ())
                if row.get("milestone_state") == "ready"
                and row.get("milestone_ready") is True
                and row.get("target_identity") == DAILY_MILESTONE_CHEST_TARGET_IDENTITY
            ]
            if not ready:
                break
            if result["total_action_count"] >= min(
                context.max_actions if context.max_actions is not None else 6, 6,
            ):
                result.update(status="blocked", reason="Finite Daily reward action budget exhausted.")
                return result
            chest = ready[0]
            key = str(chest["milestone_key"])
            game_day = str(scan["game_day_id"])
            identity = (
                context.identity.account_id, context.identity.server_id,
                context.identity.reset_id, key,
            )
            material = "".join(f"{len(value)}:{value}" for value in identity)
            action_key = "daily-rewards:milestone:" + hashlib.sha256(
                material.encode("utf-8")
            ).hexdigest()
            prior = store.get_action_by_key(action_key)
            if store.has_action_block() or prior is not None:
                result.update(
                    status="unresolved",
                    reason="Canonical action history requires reconciliation; no chest retry.",
                    effect_reconciliation_required=store.has_action_block(),
                    identical_retry_denied=True,
                )
                return result
            before = session.observe(runtime.capture, label=f"{key}-immediate-before")
            before_recognition = recognize(before, game_day)
            before_scan = recognize_daily_milestone_chests(
                before.frame, before_recognition, source_frame_sha256=before.sha256,
            )
            bound = [
                row for row in before_scan.get("milestones", ())
                if row.get("milestone_key") == key
                and row.get("milestone_state") == "ready"
                and row.get("milestone_ready") is True
            ]
            if (
                len(bound) != 1
                or not has_complete_zero_control_scan(before_recognition)
                or not same_daily_reset(recognition, before_recognition)
                or before.captured_monotonic <= captured.captured_monotonic
                or max(abs(a - b) for a, b in zip(
                    chest["target_roi"], bound[0]["target_roi"]
                )) > 2
            ):
                result.update(status="blocked", reason="Fresh same-slot ready chest binding changed.")
                refresh_accounting()
                return result
            target_roi = tuple(bound[0]["target_roi"])
            action_id = "daily-milestone-" + hashlib.sha256(
                f"{action_key}:{context.invocation_id}".encode("utf-8")
            ).hexdigest()
            expected_postcondition = "same_milestone_claimed_opened_or_removed"
            consequence = "claim_zero_cost_reward"
            policy = CentralPolicy({context.flow_id})

            def source_observation(frame):
                return Observation(
                    frame_sha256=frame.sha256,
                    capture_completed_monotonic=frame.captured_monotonic,
                    runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
                    width=NATIVE_WIDTH, height=NATIVE_HEIGHT, valid_png=True,
                    corrupt=False, black=False, source_state=DAILY_SELECTED_STATE,
                    overlay_state="none_observed",
                    target_identity=DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                    target_roi=target_roi, recognized=True, control_class="MILESTONE_CHEST",
                    consequence=consequence, cost_type="none", cost_amount=0, quantity=1,
                    expected_postcondition=expected_postcondition,
                    evidence_refs=(str(frame.path),), ocr_result_frame_sha256=frame.sha256,
                    ocr_result_capture_completed_monotonic=frame.captured_monotonic,
                    source_family="daily_rewards_milestone", target_isolated=True,
                    package_foreground=runtime.measure_foreground_package() == BLUESTACKS_PACKAGE,
                )

            immediate_observation = source_observation(before)
            request = PolicyRequest(
                action_id=action_id, action_key=action_key, task_id=context.flow_id,
                task_mode="supervised_validation", semantic_action="CLAIM_ACTIVITY_MILESTONE",
                expected_runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
                observation=immediate_observation, monotonic_now=context.monotonic_clock(),
                observation_max_age_seconds=30.0, dispatch_max_age_seconds=30.0,
                lease_owner=context.owner,
                lease_valid=store.lease_valid_for(context.owner, context.utc_clock()),
                unresolved_action=store.has_action_block(),
                duplicate_action_key=store.action_key_exists(action_key),
                game_day_id=game_day, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                action_kind="CLAIM_ACTIVITY_MILESTONE",
                subject=DAILY_MILESTONE_CHEST_TARGET_IDENTITY, maximum_cost=0, free_only=True,
                semantic_preconditions=(
                    "daily_quest_screen", "selected_activity_milestones",
                    f"exact_milestone:{key}", "exact_ready_chest",
                    "bluestacks_native_evidence", "zero_cost_reward",
                ),
                semantic_postconditions=(expected_postcondition,),
                runtime_session_id=str(runtime.session),
            )
            issued = policy.issue_capability(request)
            store.audit(context.flow_id, "capability_issued", context.utc_clock(), issued.audit, action_id)
            if not issued.authorized or issued.capability is None:
                result.update(status="blocked", reason=f"Chest policy denied: {issued.reason_code}")
                refresh_accounting()
                return result
            post_frames: list[CapturedNativeFrame] = []
            post_scans: list[Mapping[str, Any]] = []
            post_recognitions: list[FrameRecognition] = []
            verified: list[bool] = []
            transport_calls = 0
            before_used = False
            recapture_used = False

            def single_before(label):
                nonlocal before_used
                if before_used:
                    return runtime.capture(label)
                before_used = True
                return before

            def recapture():
                nonlocal recapture_used
                if recapture_used:
                    raise DailyRowClaimRecognitionError("Chest source observation is single-use")
                recapture_used = True
                return immediate_observation

            def observe_successor(frame):
                current = recognize(frame, game_day)
                current_scan = recognize_daily_milestone_chests(
                    frame.frame, current, source_frame_sha256=frame.sha256,
                )
                positive = daily_milestone_postcondition_verified(before_scan, current_scan, key)
                post_frames.append(frame)
                post_scans.append(current_scan)
                post_recognitions.append(current)
                verified.append(positive)
                return expected_postcondition if positive else "unknown"

            def settle_successor():
                last = None
                for ordinal in range(1, DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS + 1):
                    context.checkpoint()
                    context.validate_identity()
                    time.sleep(DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS)
                    last = runtime.capture(f"{key}-settled-{ordinal:02d}")
                    if observe_successor(last) == expected_postcondition:
                        break
                return last

            def dispatch(frame):
                nonlocal transport_calls
                context.validate_identity()
                transport_calls += 1
                runtime.tap(
                    frame, target_identity=DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                    target_roi=target_roi, action_key=action_key,
                    action_class="free_action", consequential=False,
                )

            def transport(_intent):
                action = session.run_action(
                    action_class=DAILY_CLAIM_ACTION_CLASS, label=action_key,
                    capture=single_before, dispatch=dispatch, recognize=observe_successor,
                    settled_successor=settle_successor,
                    consequence_class=DAILY_CLAIM_CONSEQUENCE_CLASS,
                )
                return TransportResult(
                    action.status == "completed",
                    "BLUESTACKS_DAILY_MILESTONE_CLAIM_DISPATCHED"
                    if action.status == "completed" else "BLUESTACKS_DAILY_MILESTONE_UNRESOLVED",
                )

            def post_observe():
                for frame, positive in zip(post_frames, verified):
                    yield Observation(
                        frame_sha256=frame.sha256,
                        capture_completed_monotonic=frame.captured_monotonic,
                        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
                        width=NATIVE_WIDTH, height=NATIVE_HEIGHT, valid_png=True,
                        corrupt=False, black=False,
                        source_state=expected_postcondition if positive else UNKNOWN_STATE,
                        overlay_state="none_observed" if positive else "unknown",
                        target_identity=None, target_roi=None, recognized=positive,
                        evidence_refs=(str(frame.path),),
                    )

            def reconcile(_intent, observed):
                return bool(
                    verified and verified[-1]
                    and observed.frame_sha256 == post_frames[-1].sha256
                    and observed.capture_completed_monotonic == post_frames[-1].captured_monotonic
                )

            error = None
            execution = None
            try:
                execution = SafeActionExecutor(
                    store, policy, context.owner, context.monotonic_clock, transport,
                    recapture, post_observe, reconcile, wall_clock=context.utc_clock,
                    max_pre_dispatch_attempts=1,
                ).execute(
                    replace(request, observation=source_observation(captured),
                            monotonic_now=context.monotonic_clock()),
                    issued.capability,
                )
            except Exception as exc:
                error = str(exc)
            journal = store.get_action_by_key(action_key)
            expected_journal = {
                "action_id": action_id, "task_id": context.flow_id,
                "semantic_action": "CLAIM_ACTIVITY_MILESTONE",
                "source_state": DAILY_SELECTED_STATE,
                "target_identity": DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                "game_day_id": game_day, "consequence": consequence,
                "expected_postcondition": expected_postcondition, "cost_type": "none",
                "cost_amount": 0, "quantity": 1, "consequential": 1,
                "final_status": ActionStatus.CONFIRMED.value,
            }
            confirmed = bool(
                execution is not None and execution.status is ActionStatus.CONFIRMED
                and transport_calls == 1 and verified and verified[-1]
                and journal is not None
                and all(journal.get(field) == value for field, value in expected_journal.items())
            )
            result["total_action_count"] += transport_calls
            result["reward_claim_transport_calls"] += transport_calls
            result["identical_retry_denied"] = bool(journal is not None or transport_calls)
            if not confirmed:
                result.update(
                    status="unresolved" if journal is not None or transport_calls else "blocked",
                    reason=error or (execution.reason if execution is not None else "Chest outcome unknown"),
                    effect_reconciliation_required=bool(journal is not None or transport_calls),
                )
                refresh_accounting()
                return result
            result["committed_action_count"] += 1
            result["chests_collected"].append({
                "status": "confirmed", "milestone_key": key,
                "reset_id": context.identity.reset_id,
                "target_identity": DAILY_MILESTONE_CHEST_TARGET_IDENTITY,
                "control_class": "MILESTONE_CHEST", "ready_state_proven": True,
                "free_only": True, "cost_type": "none", "dispatch_count": 1,
                "action_key": action_key, "successor_milestone_key": key,
                "successor_state": "claimed",
                "source_frame_sha256": before.sha256,
                "successor_frame_sha256": post_frames[-1].sha256,
            })
            refresh_accounting()
            captured, recognition, scan = post_frames[-1], post_recognitions[-1], post_scans[-1]
            result.update(
                milestone_scan=scan,
                unclaimed_ready_chest_count=scan.get("ready_chest_count"),
            )
            result["observed_points"]["after"] = dict(recognition.visual_evidence or {}).get("points")
        if has_complete_zero_control_scan(recognition) and has_five_static_chests(scan):
            return close_static_daily(
                result, recognition, no_work=result["committed_action_count"] == 0,
            )
        result.update(
            status="evidence_required",
            reason="Current five-slot chest scan is incomplete or still ready; no identical retry.",
        )
        return result

    if proposal is None or not available_daily_claim_authorizeable(proposal):
        if has_complete_zero_control_scan(proposal_recognition):
            return claim_ready_chests(base, proposal_capture, proposal_recognition, milestone_scan)
        base["reason"] = proposal_recognition.reason or "Current free Daily claim context is ambiguous."
        return base

    batch_identity = proposal.aggregate_batch_identity
    if not isinstance(batch_identity, str) or not batch_identity:
        base["reason"] = "current aggregate ready-batch identity is missing"
        return base
    action_key = _daily_aggregate_action_key(
        context.identity.account_id,
        context.identity.server_id,
        context.identity.reset_id,
        proposal.game_day_id,
        batch_identity,
    )
    if store.has_action_block():
        base.update(
            status="unresolved",
            reason="canonical unresolved action requires inspection",
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        return base
    prior = store.get_action_by_key(action_key)
    if prior is not None:
        base["reason"] = (
            "same current aggregate batch already has a canonical journal entry; no retry"
        )
        base["identical_retry_denied"] = True
        base["prior_journal_status"] = prior.get("final_status")
        return base

    immediate_capture = session.observe(
        runtime.capture,
        label="daily-rewards-aggregate-immediate-before",
    )
    immediate_recognition = recognize(immediate_capture, proposal.game_day_id)
    immediate_visual = dict(immediate_recognition.visual_evidence or {})
    immediate = daily_claim_observation_from_recognition(
        immediate_recognition,
        source_frame_sha256=immediate_capture.sha256,
        evidence_ref=str(immediate_capture.path),
        game_day_id=proposal.game_day_id,
        aggregate_batch_identity=batch_identity,
    )
    if (
        immediate is None
        or not available_daily_claim_authorizeable(immediate)
        or immediate.aggregate_batch_identity != batch_identity
        or immediate.target_roi != proposal.target_roi
        or immediate.row_bounds != proposal.row_bounds
        or immediate_capture.captured_monotonic <= proposal_capture.captured_monotonic
    ):
        base["reason"] = "immediate-before aggregate batch changed or became ambiguous"
        return base

    action_id = "daily-rewards-aggregate-" + hashlib.sha256(
        f"{action_key}:{context.invocation_id}".encode("utf-8")
    ).hexdigest()
    action_semantic = "CLAIM_DAILY_QUEST"
    expected_postcondition = "all_ordinary_claim_controls_cleared"
    consequence = "claim_zero_cost_reward"

    def action_observation(captured, recognition, observed):
        package = runtime.measure_foreground_package()
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
            width=NATIVE_WIDTH,
            height=NATIVE_HEIGHT,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state=DAILY_SELECTED_STATE,
            overlay_state="none_observed",
            target_identity=DAILY_CLAIM_TARGET_IDENTITY,
            target_roi=recognition.target_roi,
            recognized=bool(recognition.recognized),
            control_class="CLAIM",
            consequence=consequence,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition=expected_postcondition,
            evidence_refs=(str(captured.path),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="daily_rewards_aggregate",
            target_isolated=True,
            package_foreground=package == BLUESTACKS_PACKAGE,
        )

    immediate_policy_observation = action_observation(
        immediate_capture, immediate_recognition, immediate
    )
    proposal_policy_observation = action_observation(
        proposal_capture, proposal_recognition, proposal
    )
    policy = CentralPolicy({context.flow_id})

    def policy_request(observed):
        return PolicyRequest(
            action_id=action_id,
            action_key=action_key,
            task_id=context.flow_id,
            task_mode="supervised_validation",
            semantic_action=action_semantic,
            expected_runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
            observation=observed,
            monotonic_now=context.monotonic_clock(),
            observation_max_age_seconds=30.0,
            dispatch_max_age_seconds=30.0,
            lease_owner=context.owner,
            lease_valid=store.lease_valid_for(context.owner, context.utc_clock()),
            unresolved_action=store.has_action_block(),
            duplicate_action_key=store.action_key_exists(action_key),
            game_day_id=proposal.game_day_id,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            action_kind=action_semantic,
            subject=DAILY_CLAIM_TARGET_IDENTITY,
            maximum_cost=0,
            free_only=True,
            semantic_preconditions=(
                "daily_quest_screen",
                "current_aggregate_ready_batch",
                "exact_current_free_claim_control",
                "aggregate_batch_bound_to_reset",
            ),
            semantic_postconditions=(expected_postcondition,),
            runtime_session_id=str(runtime.session),
        )

    issue_request = policy_request(immediate_policy_observation)
    issued = policy.issue_capability(issue_request)
    store.audit(context.flow_id, "capability_issued", context.utc_clock(), issued.audit, action_id)
    if not issued.authorized or issued.capability is None:
        base["reason"] = f"aggregate Claim policy denied: {issued.reason_code}"
        return base

    post_captures: list[CapturedNativeFrame] = []
    post_recognitions: list[FrameRecognition] = []
    post_verified: list[bool] = []
    immediate_returned = False
    recapture_returned = False

    def single_immediate(label):
        nonlocal immediate_returned
        if not immediate_returned:
            immediate_returned = True
            return immediate_capture
        return runtime.capture(label)

    def recapture():
        nonlocal recapture_returned
        if recapture_returned:
            raise ValueError("aggregate Claim immediate observation is single-use")
        recapture_returned = True
        return immediate_policy_observation

    def observe_successor(captured):
        recognition = recognize(captured, proposal.game_day_id)
        verified = daily_claim_postcondition_verified(
            immediate_recognition,
            recognition,
            game_day_id=proposal.game_day_id,
        )
        post_captures.append(captured)
        post_recognitions.append(recognition)
        post_verified.append(verified)
        return expected_postcondition if verified else "unknown"

    def settle_successor():
        last = None
        for ordinal in range(1, DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS + 1):
            time.sleep(DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS)
            last = runtime.capture(f"daily-rewards-aggregate-settled-{ordinal:02d}")
            if observe_successor(last) == expected_postcondition:
                break
        if last is None:
            raise DailyRowClaimRecognitionError("aggregate Claim successor capture is unavailable")
        return last

    def transport(_intent):
        context.validate_identity()
        action = session.run_action(
            action_class=DAILY_CLAIM_ACTION_CLASS,
            label=action_key,
            capture=single_immediate,
            dispatch=lambda before: runtime.tap(
                before,
                target_identity=DAILY_CLAIM_TARGET_IDENTITY,
                target_roi=immediate_recognition.target_roi,
                action_key=action_key,
                action_class="free_action",
                consequential=False,
            ),
            recognize=observe_successor,
            settled_successor=settle_successor,
            consequence_class=DAILY_CLAIM_CONSEQUENCE_CLASS,
        )
        if action.status != "completed":
            return TransportResult(False, "BLUESTACKS_DAILY_AGGREGATE_ACTION_UNRESOLVED")
        return TransportResult(True, "BLUESTACKS_DAILY_AGGREGATE_CLAIM_DISPATCHED")

    def post_observe():
        for captured, recognition, positive in zip(
            post_captures, post_recognitions, post_verified
        ):
            visual = dict(recognition.visual_evidence or {})
            yield Observation(
                frame_sha256=captured.sha256,
                capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
                width=NATIVE_WIDTH,
                height=NATIVE_HEIGHT,
                valid_png=True,
                corrupt=False,
                black=False,
                source_state=(
                    expected_postcondition if positive else "UNKNOWN"
                ),
                overlay_state=(
                    "none_observed"
                    if not visual.get("full_frame_overlay", {}).get("recognized")
                    else "unknown"
                ),
                target_identity=None,
                target_roi=None,
                recognized=positive,
                evidence_refs=(str(captured.path),),
            )

    def reconcile(_intent, observed):
        return bool(
            post_captures
            and observed.frame_sha256 == post_captures[-1].sha256
            and observed.capture_completed_monotonic
            == post_captures[-1].captured_monotonic
            and post_verified[-1]
        )

    def aggregate_action_count() -> int:
        return sum(
            1
            for item in runtime.frame_actions
            if isinstance(item, tuple)
            and len(item) == 3
            and item[1] == DAILY_CLAIM_TARGET_IDENTITY
        )

    def interrupted_result(reason: str) -> Mapping[str, Any]:
        calls = aggregate_action_count()
        try:
            current_accounting = context.accounting()
            input_count = current_accounting.input_count
            accounting_verified = current_accounting.verified is True
        except Exception:
            input_count = None
            accounting_verified = False
        return {
            "status": "unresolved" if calls else "blocked",
            "reason": reason,
            "total_input_count": input_count,
            "total_action_count": calls,
            "reward_claim_transport_calls": calls,
            "committed_action_count": 0,
            "accounting_verified": accounting_verified,
            "terminal_home_verified": False,
            "effect_reconciliation_required": bool(calls),
            "identical_retry_denied": bool(calls),
            "aggregate_claim": {
                "status": "unresolved" if calls else "none",
                "dispatch_count": calls,
                "confirmed": False,
                "batch_identity": batch_identity,
                "reset_id": context.identity.reset_id,
                "ready_batch_proven": True,
                "free_only": True,
                "control_identity": DAILY_CLAIM_TARGET_IDENTITY,
                "ordinary_claim_controls_cleared": False,
                "source_frame_sha256": immediate_capture.sha256,
            },
            "chests_collected": [],
            "observed_points": {"before": immediate.points, "after": None},
            "milestone_scan": milestone_scan,
            "unclaimed_ready_chest_count": ready_chest_count,
            "no_work": False,
        }
    try:
        execution = SafeActionExecutor(
            store,
            policy,
            context.owner,
            context.monotonic_clock,
            transport,
            recapture,
            post_observe,
            reconcile,
            wall_clock=context.utc_clock,
            max_pre_dispatch_attempts=1,
        ).execute(
            replace(
                issue_request,
                observation=proposal_policy_observation,
                monotonic_now=context.monotonic_clock(),
            ),
            issued.capability,
        )
    except Exception as exc:
        return interrupted_result(f"aggregate Claim execution outcome is unknown: {exc}")
    action_calls = aggregate_action_count()
    committed = 0
    journal = store.get_action_by_key(action_key)
    if (
        execution.status is ActionStatus.CONFIRMED
        and journal is not None
        and journal.get("final_status") == ActionStatus.CONFIRMED.value
        and post_verified
        and post_verified[-1]
    ):
        expected = {
            "action_id": action_id,
            "task_id": context.flow_id,
            "semantic_action": action_semantic,
            "source_state": DAILY_SELECTED_STATE,
            "target_identity": DAILY_CLAIM_TARGET_IDENTITY,
            "game_day_id": proposal.game_day_id,
            "consequence": consequence,
            "expected_postcondition": expected_postcondition,
            "cost_type": "none",
            "cost_amount": 0,
            "quantity": 1,
            "consequential": 1,
            "final_status": ActionStatus.CONFIRMED.value,
        }
        if any(journal.get(field) != value for field, value in expected.items()):
            return interrupted_result(
                "aggregate Claim canonical journal does not match the dispatched batch"
            )
        committed = 1
    try:
        context.validate_identity()
        accounting = context.accounting()
    except Exception as exc:
        return interrupted_result(f"aggregate Claim identity/accounting became unknown: {exc}")
    effect_unknown = bool(action_calls and not committed)
    aggregate_result: dict[str, Any] = {
        "status": "confirmed" if committed else "unresolved" if effect_unknown else "none",
        "dispatch_count": action_calls,
        "confirmed": bool(committed),
        "batch_identity": batch_identity,
        "reset_id": context.identity.reset_id,
        "ready_batch_proven": True,
        "free_only": True,
        "control_identity": DAILY_CLAIM_TARGET_IDENTITY,
        "ordinary_claim_controls_cleared": bool(committed),
        "source_frame_sha256": immediate_capture.sha256,
    }
    if committed and post_captures:
        aggregate_result["successor_frame_sha256"] = post_captures[-1].sha256
    post_milestone_scan = (
        recognize_daily_milestone_chests(
            post_captures[-1].frame,
            post_recognitions[-1],
            source_frame_sha256=post_captures[-1].sha256,
        )
        if post_captures
        else None
    )
    latest_milestone_scan = post_milestone_scan or milestone_scan
    latest_scan_observed = latest_milestone_scan.get("status") in {
        "observed",
        "partial_unknown",
    }
    latest_ready_chest_count = (
        latest_milestone_scan.get("ready_chest_count")
        if latest_scan_observed
        else None
    )
    latest_ready_chest_count = (
        latest_ready_chest_count
        if type(latest_ready_chest_count) is int
        else None
    )
    partial = {
        "status": (
            "unresolved"
            if effect_unknown
            else "evidence_required"
            if committed
            else "blocked"
        ),
        "reason": execution.reason,
        "total_input_count": accounting.input_count,
        "total_action_count": action_calls,
        "reward_claim_transport_calls": action_calls,
        "committed_action_count": committed,
        "accounting_verified": accounting.verified,
        "terminal_home_verified": False,
        "effect_reconciliation_required": effect_unknown,
        "identical_retry_denied": bool(action_calls),
        "aggregate_claim": aggregate_result,
        "chests_collected": [],
        "observed_points": {
            "before": immediate.points,
            "after": (
                (post_recognitions[-1].visual_evidence or {}).get("points")
                if post_recognitions
                else None
            ),
        },
        "milestone_scan": latest_milestone_scan,
        "milestone_scan_before_aggregate": (
            milestone_scan if post_milestone_scan is not None else None
        ),
        "unclaimed_ready_chest_count": latest_ready_chest_count,
        "no_work": False,
    }
    if committed and post_recognitions:
        return claim_ready_chests(
            partial, post_captures[-1], post_recognitions[-1], latest_milestone_scan,
        )
    return partial


def create_service_binding(make_native_route_binding):
    """Construct the fixed native binding used by the canonical Daily rewards adapter."""
    from automation_service.registry import (
        DAILY_REWARDS_FLOW_ID,
        DAILY_REWARDS_MAX_INPUTS,
        DAILY_REWARDS_PRODUCT_ID,
        DAILY_REWARDS_PRODUCT_REVISION,
    )

    return make_native_route_binding(
        flow_id=DAILY_REWARDS_FLOW_ID,
        product_id=DAILY_REWARDS_PRODUCT_ID,
        product_revision=DAILY_REWARDS_PRODUCT_REVISION,
        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        owner="automation-service:daily-rewards",
        workflow="daily-rewards-native",
        max_inputs=DAILY_REWARDS_MAX_INPUTS,
        max_actions=6,
        driver=run_daily_rewards_from_home,
        lease_seconds=3600.0,
    )
