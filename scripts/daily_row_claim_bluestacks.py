"""Bounded Home -> Quest -> Daily reconnaissance for local BlueStacks.

This module owns the selected-Daily aggregate Claim flow and its optional exact
VIP popup dismissal.  It never spends resources, performs recovery, or talks
to ADB directly.  Runtime capture and transport are supplied by
``LocalBlueStacksRuntime``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeBox
from tasks.available_daily_claim import (
    AvailableDailyClaimObservation,
    available_daily_claim_authorizeable,
)
from scripts.world_map_navigation_bluestacks import (
    _visual_popup_panel_candidates as _accepted_visual_popup_panel_candidates,
)


NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
EXPECTED_PACKAGE = "com.global.ztmslg"
HOME_SEARCH_ROI: NativeBox = (0, 1000, NATIVE_WIDTH, NATIVE_HEIGHT)
QUEST_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
DAILY_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
FULL_FRAME_SEARCH_ROI: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

HOME_STATE = "HOME"
QUEST_STATE = "QUEST"
DAILY_SELECTED_STATE = "DAILY_SELECTED"
UNKNOWN_STATE = "UNKNOWN"
DAILY_CLAIM_STATE = "DAILY_CLAIM_READY"
DAILY_CLAIM_ACTION_IDENTITY = "daily-claim:aggregate"
DAILY_CLAIM_TARGET_IDENTITY = "daily-quest-claim"
BLUESTACKS_TARGET_PROVENANCE = "bluestacks-native"
BLUESTACKS_RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
DAILY_CLAIM_CONSEQUENCE_CLASS = "ordinary_development"
DAILY_CLAIM_ACTION_CLASS = "reward_claim"
DAILY_CLAIM_SUCCESS_POLL_TIMEOUT_SECONDS = 5.0
DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS = 0.25
DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS = 20
VIP_POPUP_SUCCESS_POLL_TIMEOUT_SECONDS = 5.0
VIP_POPUP_SUCCESS_POLL_INTERVAL_SECONDS = 0.25
VIP_POPUP_SUCCESS_POLL_MAX_ATTEMPTS = 20
RESET_DEADLINE_TOLERANCE_SECONDS = 2

HOME_QUEST_IDENTITY = "home-quest-entry"
QUEST_DAILY_IDENTITY = "quest-daily-tab"
NAVIGATION_ACTION_CLASS = "navigation"
NAVIGATION_CONSEQUENCE_CLASS = "navigation_only"
VIP_POINTS_POPUP_IDENTITY = "VIP_POINTS_GET_PTS"
VIP_POINTS_POPUP_CLOSE_IDENTITY = "reset-popup-close"
SUCCESSOR_POLL_TIMEOUT_SECONDS = 5.0
SUCCESSOR_POLL_INTERVAL_SECONDS = 0.25
SUCCESSOR_POLL_MAX_ATTEMPTS = 20

_HOME_WORDS = frozenset({"quest", "world", "hero", "bag", "mail", "alliance", "more"})
_OVERLAY_MARKERS = frozenset(
    {"loading", "retry", "cancel", "confirm", "purchase", "payment", "popup", "captcha"}
)
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


class _NativeSwipeDispatch:
    """Keep receipt reservation ownership with the native runtime swipe."""

    def __init__(self, callback: Callable[[CapturedNativeFrame], None]) -> None:
        self._callback = callback

    def _authorize_dispatch(self) -> None:
        # DevelopmentSession uses this marker to avoid a second generic
        # delegated reservation.  LocalBlueStacksRuntime.swipe performs the
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
    import pytesseract

    return pytesseract.image_to_data(
        image,
        config="--psm 11",
        output_type=pytesseract.Output.DICT,
    )


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
    """Derive the current Quest lane and icon band from adjacent labels."""

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
    if not left or not right:
        return None

    left.sort(key=lambda candidate: (candidate.roi[0] + candidate.roi[2]) // 2, reverse=True)
    right.sort(key=lambda candidate: (candidate.roi[0] + candidate.roi[2]) // 2)
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
        "left_label_center": (left_center_x, (left_label.roi[1] + left_label.roi[3]) // 2),
        "right_label_center": (right_center_x, (right_label.roi[1] + right_label.roi[3]) // 2),
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
            "left_label_roi": geometry["left_label"].roi,
            "right_label_roi": geometry["right_label"].roi,
            "left_label_center": geometry["left_label_center"],
            "right_label_center": geometry["right_label_center"],
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


def _parse_progress(text: str) -> tuple[int, int] | None:
    match = re.search(r"\(?\s*(\d{1,6})\s*/\s*(\d{1,6})\s*\)?", text)
    if match is not None:
        return int(match.group(1)), int(match.group(2))
    numbers = re.findall(r"\b\d{1,6}\b", text)
    if len(numbers) >= 2:
        return int(numbers[-2]), int(numbers[-1])
    return None


def _parse_points(text: str) -> int | None:
    match = re.search(r"(?:daily\s+quest\s+)?pts?[^0-9]{0,12}(\d{1,6})", text)
    return int(match.group(1)) if match else None


def _parse_reward_points(text: str) -> int | None:
    match = re.search(r"reward[^0-9+-]*pts?[^0-9+-]*\+?\s*(\d{1,6})", text)
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
    main_token = max(main, key=lambda token: token.roi[2]) if main else None
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
            center_score >= max(left_score, right_score) + 0.02
        )
        details.update(
            {
                "daily_center": (round(center_x, 3), round((cy0 + cy1) / 2.0, 3)),
                "daily_tab_probe": center_roi,
                "daily_tab_score": round(center_score, 6),
                "main_tab_score": round(left_score, 6),
                "alliance_tab_score": round(right_score, 6),
            }
        )
    details["recognized"] = selected_by_geometry
    if not selected_by_geometry:
        details["reason"] = "center-daily-tab-selection-not-proven"
    return selected_by_geometry, details


def _visual_claim_button_candidates(
    frame: np.ndarray,
    *,
    row_y: float,
    minimum_x: int,
) -> tuple[NativeBox, ...]:
    """Find current-frame orange Claim button bodies in a measured row panel."""

    y0 = max(0, int(row_y) - 180)
    y1 = min(NATIVE_HEIGHT, int(row_y) + 180)
    x0 = max(0, int(minimum_x))
    patch = frame[y0:y1, x0:NATIVE_WIDTH]
    if patch.size == 0:
        return ()
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 50, 80), (40, 255, 255))
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    candidates: list[NativeBox] = []
    for component in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[component])
        if width < 80 or height < 28 or area < 1000:
            continue
        candidates.append((x0 + left, y0 + top, x0 + left + width, y0 + top + height))
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
    evidence_tokens: Sequence[OCRToken],
) -> dict[str, Any] | None:
    """Measure one row panel from current pixels, never from Claim proximity."""

    if not evidence_tokens:
        return None
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
        y0 = max(320, min(token.roi[1] for token in evidence_tokens) - 24)
        y1 = min(NATIVE_HEIGHT, max(token.roi[3] for token in evidence_tokens) + 24)
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
    token_x0 = max(0, min(token.roi[0] for token in evidence_tokens) - 18)
    token_x1 = min(NATIVE_WIDTH, max(token.roi[2] for token in evidence_tokens) + 18)
    if token_x0 >= token_x1:
        return None
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
    milestone_markers = tuple(sorted(words & _MILESTONE_MARKERS))
    selected, selected_visual = _selected_daily_visual_context(frame, tokens)
    full_text = _reading_text(tokens)
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
    body = tuple(token for token in tokens if _token_center(token)[1] >= 340)

    visual: dict[str, Any] = {
        "full_frame_overlay": {
            "recognized": bool(overlay_markers),
            "markers": overlay_markers,
        },
        "milestone_markers": milestone_markers,
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
                _token_rows(tokens),
            ),
            None,
        )

    if overlay_markers:
        return failure("full-frame overlay/modal detected")
    if milestone_markers:
        return failure("milestone reward is not row-local")
    if not selected:
        return failure(selected_visual.get("reason", "selected Daily was not proven"))
    if points is None:
        return failure("Daily Quest points were not proven")
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
    visual["recognized_claim_controls"] = len(claim_tokens)
    visual["available_claim_controls"] = 0
    visual["available_ordinary_claim_controls"] = 0
    if not claim_tokens:
        # A selected-Daily successor remains recognized after the aggregate
        # Claim is consumed, but it never authorizes a second input.
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
                _token_rows(tokens),
            ),
            None,
        )

    candidates: list[dict[str, Any]] = []
    for ordinal, claim_token in enumerate(claim_tokens, start=1):
        row_y = _token_center(claim_token)[1]
        candidate: dict[str, Any] = {
            "ordinal": ordinal,
            "claim_ocr_roi": claim_token.roi,
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
            evidence_tokens=(claim_token,),
        )
        candidate["row_panel_geometry"] = panel_geometry
        if panel_geometry is None or not panel_geometry["proven"]:
            candidate["rejection_reasons"].append("row_panel_not_proven")
            candidates.append(candidate)
            continue

        row_bounds = tuple(panel_geometry["bounds"])
        candidate["row_bounds"] = row_bounds
        if row_bounds[1] <= 340 or row_bounds[3] >= NATIVE_HEIGHT:
            candidate["rejection_reasons"].append("claim_clipped_or_milestone_region")
        if not (
            row_bounds[0] <= claim_token.roi[0]
            and claim_token.roi[2] <= row_bounds[2]
            and row_bounds[1] <= claim_token.roi[1]
            and claim_token.roi[3] <= row_bounds[3]
        ):
            candidate["rejection_reasons"].append("claim_outside_measured_panel")

        tx0, ty0, tx1, ty1 = claim_token.roi
        claim_roi = _clamp_roi((tx0 - 45, ty0 - 25, tx1 + 45, ty1 + 25))
        candidate["claim_roi"] = claim_roi
        if claim_roi is None:
            candidate["rejection_reasons"].append("claim_geometry_out_of_bounds")
            candidates.append(candidate)
            continue
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
    visual["available_ordinary_claim_controls"] = len(eligible)
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
    claim_token = claim_tokens[int(selected_candidate["ordinal"]) - 1]
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
            "available_ordinary_claim_controls": len(eligible),
            "row_bounds": row_bounds,
            "row_panel_bounds": row_bounds,
            "claim_roi": target_roi,
            "claim_ocr_roi": claim_token.roi,
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
            _token_rows(tokens),
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


def _box_contains(box: NativeBox, point: tuple[float, float]) -> bool:
    x0, y0, x1, y1 = box
    return bool(x0 <= point[0] <= x1 and y0 <= point[1] <= y1)


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
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, HOME_SEARCH_ROI, self._ocr)
        quest_tokens = [token for token in tokens if token.text == "quest"]
        quest = quest_tokens[0] if len(quest_tokens) == 1 else None
        navigation_geometry = (
            _home_navigation_geometry(tokens, quest) if quest is not None else None
        )
        target = None
        visual: dict[str, Any] = {
            "bottom_navigation": navigation_geometry is not None,
            "known_navigation_labels": sorted(
                {word for token in tokens for word in token.text.split()} & _HOME_WORDS
            ),
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        if quest is not None:
            target, binding = _bind_home_quest_target(frame, quest, tokens)
            visual["quest_binding"] = binding
        recognized = bool(
            len(quest_tokens) == 1
            and navigation_geometry is not None
            and target is not None
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else "home-quest-target-not-proven"
        )
        return FrameRecognition(
            HOME_STATE if recognized else UNKNOWN_STATE,
            recognized,
            HOME_QUEST_IDENTITY if recognized else None,
            target if recognized else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
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

    def recognize_main_quest(self, frame: np.ndarray) -> FrameRecognition:
        """Reuse the complete Main-selection proof from ``recognize_quest``."""

        return self.recognize_quest(frame)

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
        daily = next((token for token in tokens if token.text == "daily"), None)
        main = next(
            (token for token in tokens if token.text in {"main", "main quest", "quest"}),
            None,
        )
        daily_score = _tab_visual_score(frame, daily) if daily else 0.0
        main_score = _tab_visual_score(frame, main) if main else 0.0
        visual: dict[str, Any] = {
            "daily_tab_score": daily_score,
            "main_tab_score": main_score,
            "selected_margin": round(daily_score - main_score, 6),
            "main_tab_present": main is not None,
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        recognized = bool(
            daily is not None
            and main is not None
            and daily_score >= 0.12
            and daily_score >= main_score + 0.015
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
            daily.roi if recognized and daily else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
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
        clipped=not bool(evidence.get("row_fully_visible")),
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
    )


def daily_claim_postcondition_verified(
    before: FrameRecognition,
    after: FrameRecognition | None,
    *,
    game_day_id: str,
) -> bool:
    """Require selected Daily/reset continuity, points increase, and Claim exhaustion."""

    before_evidence = dict(before.visual_evidence or {})
    after_evidence = dict((after.visual_evidence if after is not None else {}) or {})
    if (
        not before.recognized
        or before.state != DAILY_SELECTED_STATE
        or before.target_identity != DAILY_CLAIM_TARGET_IDENTITY
        or before_evidence.get("selected_daily") is not True
        or after is None
        or not after.recognized
        or after.state != DAILY_SELECTED_STATE
        or after_evidence.get("selected_daily") is not True
        or before_evidence.get("game_day_id") != game_day_id
        or after_evidence.get("game_day_id") != game_day_id
        or after_evidence.get("reset_timer") is None
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
    if after_evidence.get("available_ordinary_claim_controls") != 0:
        return False
    before_points = before_evidence.get("points")
    after_points = after_evidence.get("points")
    if (
        not isinstance(before_points, int)
        or isinstance(before_points, bool)
        or not isinstance(after_points, int)
        or isinstance(after_points, bool)
    ):
        return False
    return after_points > before_points


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


def _recognize_main_quest(
    recognizer: DailyRowClaimRecognizer | Any,
    frame: np.ndarray,
) -> FrameRecognition:
    method = getattr(recognizer, "recognize_main_quest", None)
    if callable(method):
        return method(frame)
    return FrameRecognition(
        QUEST_STATE,
        False,
        reason="Main Quest recognition is unavailable",
    )


def _settle_successor(
    *,
    session: SessionLike,
    capture: Callable[[str], CapturedNativeFrame],
    immediate_post: CapturedNativeFrame,
    recognize: Callable[[np.ndarray], FrameRecognition],
    expected_state: str,
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
    if current_recognition.recognized and current_recognition.state == expected_state:
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
        if current_recognition.recognized and current_recognition.state == expected_state:
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
    """Run exactly Home -> Quest -> selected Daily, without recovery."""

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

        def recognize_quest_successor(after: CapturedNativeFrame) -> str:
            nonlocal first_post_recognition
            first_post_recognition = _settle_successor(
                session=session,
                capture=capture,
                immediate_post=after,
                recognize=recognizer.recognize_quest,
                expected_state=QUEST_STATE,
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
                expected_state=DAILY_SELECTED_STATE,
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

        session.terminal_status = "observed"
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


def run_quest_daily_continuation(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    recognizer: DailyRowClaimRecognizer | Any | None = None,
) -> dict[str, Any]:
    """Continue from a positively recognized Main Quest screen to Daily."""

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
                "quest-source": "source",
                "quest-daily-tab-immediate-before": "daily_immediate_before",
                "quest-daily-tab-immediate-post": "daily_terminal",
            }
            name = frame_names.get(label)
            if name is None and label.startswith(f"{QUEST_DAILY_IDENTITY}-poll-"):
                name = f"daily_terminal_poll_{label.rsplit('-', 1)[-1]}"
            if name is not None:
                frames[name] = captured
            return captured

        source = session.observe(capture, label="quest-source")
        frames["source"] = source
        source_recognition = _recognize_main_quest(recognizer, source.frame)
        recognitions["source"] = source_recognition
        _require_recognition(
            source_recognition,
            state=QUEST_STATE,
            target_identity=QUEST_DAILY_IDENTITY,
        )

        terminal_recognition: FrameRecognition | None = None

        def dispatch_daily(before: CapturedNativeFrame) -> None:
            rebound = _recognize_main_quest(recognizer, before.frame)
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
            nonlocal terminal_recognition
            terminal_recognition = _settle_successor(
                session=session,
                capture=capture,
                immediate_post=after,
                recognize=recognizer.recognize_daily_selected,
                expected_state=DAILY_SELECTED_STATE,
                action_identity=QUEST_DAILY_IDENTITY,
                frame_key="daily_terminal",
                recognition_key="daily_terminal",
                frames=frames,
                recognitions=recognitions,
                polls=polls,
            )
            return terminal_recognition.state if terminal_recognition.recognized else UNKNOWN_STATE

        daily_dispatch = _NativeTapDispatch(dispatch_daily)
        action = session.run_action(
            action_class=NAVIGATION_ACTION_CLASS,
            label=QUEST_DAILY_IDENTITY,
            capture=capture,
            dispatch=daily_dispatch.dispatch,
            recognize=recognize_daily_successor,
            consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
        )
        if (
            action.status != "completed"
            or terminal_recognition is None
            or not terminal_recognition.recognized
        ):
            return _failure(
                session,
                reason="selected Daily terminal was not positively recognized",
                frames=frames,
                recognitions=recognitions,
                polls=polls,
            )

        session.terminal_status = "observed"
        return {
            "status": "observed",
            "reason": "selected Daily positively recognized from Main Quest",
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


def _claim_frame_label_map(label: str) -> str | None:
    if label == "daily-row-claim-source":
        return "source"
    if label in {
        "daily-row-claim-immediate-before",
        f"{DAILY_CLAIM_ACTION_IDENTITY}-immediate-before",
    }:
        return "immediate_before"
    if label in {
        "daily-row-claim-immediate-post",
        f"{DAILY_CLAIM_ACTION_IDENTITY}-immediate-post",
    }:
        return "immediate_post"
    if label.startswith("daily-row-claim-poll-"):
        return f"poll_{label.rsplit('-', 1)[-1]}"
    return None


def _annotate_daily_claim_frame(
    frame: CapturedNativeFrame,
    *,
    row_bounds: NativeBox,
    target_roi: NativeBox,
    output: Any,
) -> None:
    image = frame.frame.copy()
    rx0, ry0, rx1, ry1 = row_bounds
    tx0, ty0, tx1, ty1 = target_roi
    cv2.rectangle(image, (rx0, ry0), (rx1 - 1, ry1 - 1), (255, 180, 0), 3)
    cv2.rectangle(image, (tx0, ty0), (tx1 - 1, ty1 - 1), (0, 255, 0), 3)
    cv2.putText(
        image,
        "aggregate daily claim",
        (max(4, rx0), max(22, ry0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise DailyRowClaimRecognitionError("annotated target overlay encoding failed")
    output.write_bytes(encoded.tobytes())


def _claim_result(
    *,
    status: str,
    reason: str,
    session: SessionLike,
    frames: Mapping[str, CapturedNativeFrame],
    recognitions: Mapping[str, FrameRecognition],
    polls: Sequence[Mapping[str, Any]],
    game_day_id: str,
    mode: str,
    claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "mode": mode,
        "reason": reason,
        "input_count": int(session.input_count),
        "resource_affecting_inputs": 0,
        "combat_confirmations": 0,
        "game_day_id": game_day_id,
        "frames": {
            name: _frame_ref(frame, session.session_directory)
            for name, frame in frames.items()
        },
        "recognitions": {
            name: recognition.as_dict()
            for name, recognition in recognitions.items()
        },
        "polls": [dict(item) for item in polls],
        "actions": [dict(item) for item in session.actions],
    }
    if claim is not None:
        payload["claim"] = dict(claim)
    return payload


def run_daily_row_claim_prepare(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    game_day_id: str | None = None,
    recognizer: DailyRowClaimRecognizer | Any | None = None,
    wall_utc: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Capture and annotate one zero-input native BlueStacks Claim target."""

    recognizer = recognizer or DailyRowClaimRecognizer()
    if game_day_id is None and not hasattr(recognizer, "_ocr"):
        # Test doubles predating reset-deadline evidence cannot derive pixels;
        # keep their deterministic contract explicit without using host date.
        game_day_id = "test-reset-deadline-bound"
    frames: dict[str, CapturedNativeFrame] = {}
    recognitions: dict[str, FrameRecognition] = {}
    if not bool(getattr(runtime, "execute", False)):
        return _claim_result(
            status="evidence_required",
            reason="runtime execution is required for Daily Claim preparation",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=(),
            game_day_id=game_day_id,
            mode="prepare",
        )
    try:
        source = session.observe(runtime.capture, label="daily-row-claim-source")
        frames["source"] = source
        recognition = _recognize_daily_claim(
            recognizer,
            source.frame,
            game_day_id=game_day_id,
            wall_utc=wall_utc,
        )
        recognitions["source"] = recognition
        if game_day_id is None:
            game_day_id = str(
                (recognition.visual_evidence or {}).get("game_day_id") or ""
            )
        if not game_day_id:
            raise DailyRowClaimRecognitionError(
                "reset deadline identity was not bound at Daily Claim source"
            )
        observation = daily_claim_observation_from_recognition(
            recognition,
            source_frame_sha256=source.sha256,
            evidence_ref=str(source.path),
            game_day_id=game_day_id,
        )
        if (
            observation is None
            or recognition.target_identity != DAILY_CLAIM_TARGET_IDENTITY
            or not available_daily_claim_authorizeable(observation)
        ):
            raise DailyRowClaimRecognitionError(
                recognition.reason or "aggregate Daily Claim target was not authorized"
            )
        annotated = Path(runtime.session) / "annotated-daily-row-claim-source.png"
        _annotate_daily_claim_frame(
            source,
            row_bounds=observation.row_bounds,
            target_roi=observation.target_roi,
            output=annotated,
        )
        claim = {
            "points": observation.points,
            "reset_timer": observation.reset_timer,
            "reset_timer_seconds": observation.reset_timer_seconds,
            "reset_observed_utc": observation.reset_observed_utc,
            "reset_deadline_utc": observation.reset_deadline_utc,
            "reset_deadline_identity": observation.reset_deadline_identity,
            "reset_deadline_tolerance_seconds": observation.reset_deadline_tolerance_seconds,
            "game_day_id": observation.game_day_id,
            "row_bounds": observation.row_bounds,
            "claim_roi": observation.target_roi,
            "target_provenance": observation.target_provenance,
            "runtime_profile_id": observation.runtime_profile_id,
            "source_frame_sha256": source.sha256,
            "annotated_source": str(annotated.relative_to(session.session_directory)).replace("\\", "/"),
            "selected_daily": observation.selected_daily_quest,
            "ordinary_reward_claim": observation.ordinary_reward_claim,
            "free_control_proven": observation.free_control_proven,
            "milestone_reward": observation.milestone_reward,
            "available_claim_controls": observation.available_claim_controls,
        }
        session.terminal_status = "observed"
        return _claim_result(
            status="observed",
            reason="aggregate Daily Claim target prepared without input",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=(),
            game_day_id=game_day_id,
            mode="prepare",
            claim=claim,
        )
    except BaseException as exc:
        session.terminal_status = "evidence_required"
        session.blocker = str(exc)
        return _claim_result(
            status="evidence_required",
            reason=f"{type(exc).__name__}: {exc}",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=(),
            game_day_id=game_day_id,
            mode="prepare",
        )


def _settle_daily_claim_successor(
    *,
    session: SessionLike,
    runtime: RuntimeLike,
    recognizer: DailyRowClaimRecognizer | Any,
    immediate_post: CapturedNativeFrame,
    before: FrameRecognition,
    game_day_id: str,
    wall_utc: Callable[[], datetime] | None,
    frames: dict[str, CapturedNativeFrame],
    recognitions: dict[str, FrameRecognition],
    polls: list[dict[str, Any]],
) -> FrameRecognition | None:
    def inspect(frame: CapturedNativeFrame, label: str, attempt: int) -> FrameRecognition:
        recognition = _recognize_daily_claim(
            recognizer,
            frame.frame,
            game_day_id=game_day_id,
            wall_utc=wall_utc,
        )
        frame_name = _claim_frame_label_map(label)
        if frame_name is not None:
            frames[frame_name] = frame
            recognitions[frame_name] = recognition
        polls.append(
            {
                "action_identity": DAILY_CLAIM_ACTION_IDENTITY,
                "attempt": attempt,
                "label": label,
                "frame_name": frame_name,
                "frame": _frame_ref(frame, session.session_directory),
                "recognition": recognition.as_dict(),
            }
        )
        return recognition

    current = inspect(immediate_post, "daily-row-claim-immediate-post", 0)
    if daily_claim_postcondition_verified(before, current, game_day_id=game_day_id):
        return current
    deadline = time.monotonic() + DAILY_CLAIM_SUCCESS_POLL_TIMEOUT_SECONDS
    attempts = 0
    while attempts < DAILY_CLAIM_SUCCESS_POLL_MAX_ATTEMPTS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        interval = max(0.0, min(DAILY_CLAIM_SUCCESS_POLL_INTERVAL_SECONDS, remaining))
        if interval:
            time.sleep(interval)
        if time.monotonic() >= deadline:
            break
        attempts += 1
        label = f"daily-row-claim-poll-{attempts:02d}"
        current_frame = session.observe(runtime.capture, label=label)
        current = inspect(current_frame, label, attempts)
        if daily_claim_postcondition_verified(before, current, game_day_id=game_day_id):
            return current
    return None


def run_daily_row_claim_canary(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    game_day_id: str | None = None,
    recognizer: DailyRowClaimRecognizer | Any | None = None,
    wall_utc: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Dispatch exactly one receipt-bound free Claim and prove its successor."""

    recognizer = recognizer or DailyRowClaimRecognizer()
    if game_day_id is None and not hasattr(recognizer, "_ocr"):
        game_day_id = "test-reset-deadline-bound"
    frames: dict[str, CapturedNativeFrame] = {}
    recognitions: dict[str, FrameRecognition] = {}
    polls: list[dict[str, Any]] = []
    before_recognition: FrameRecognition | None = None
    terminal_recognition: FrameRecognition | None = None
    annotated_immediate_before: str | None = None
    if not bool(getattr(runtime, "execute", False)):
        return _claim_result(
            status="evidence_required",
            reason="runtime execution is required for Daily Claim canary",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=polls,
            game_day_id=game_day_id,
            mode="canary",
        )
    try:
        source = session.observe(runtime.capture, label="daily-row-claim-source")
        frames["source"] = source
        before_recognition = _recognize_daily_claim(
            recognizer,
            source.frame,
            game_day_id=game_day_id,
            wall_utc=wall_utc,
        )
        recognitions["source"] = before_recognition
        if game_day_id is None:
            game_day_id = str(
                (before_recognition.visual_evidence or {}).get("game_day_id") or ""
            )
        if not game_day_id:
            raise DailyRowClaimRecognitionError(
                "reset deadline identity was not bound at Daily Claim source"
            )
        before_observation = daily_claim_observation_from_recognition(
            before_recognition,
            source_frame_sha256=source.sha256,
            evidence_ref=str(source.path),
            game_day_id=game_day_id,
        )
        if (
            before_observation is None
            or before_recognition.target_identity != DAILY_CLAIM_TARGET_IDENTITY
            or not available_daily_claim_authorizeable(before_observation)
        ):
            raise DailyRowClaimRecognitionError(
                before_recognition.reason
                or "aggregate Daily Claim target was not authorized"
            )

        def capture(label: str) -> CapturedNativeFrame:
            frame = runtime.capture(label)
            frame_name = _claim_frame_label_map(label)
            if frame_name is not None:
                frames[frame_name] = frame
            return frame

        def dispatch(before_frame: CapturedNativeFrame) -> None:
            nonlocal annotated_immediate_before
            rebound = _recognize_daily_claim(
                recognizer,
                before_frame.frame,
                game_day_id=game_day_id,
                wall_utc=wall_utc,
            )
            recognitions["immediate_before"] = rebound
            rebound_observation = daily_claim_observation_from_recognition(
                rebound,
                source_frame_sha256=before_frame.sha256,
                evidence_ref=str(before_frame.path),
                game_day_id=game_day_id,
            )
            if (
                rebound_observation is None
                or rebound.target_identity != DAILY_CLAIM_TARGET_IDENTITY
                or not available_daily_claim_authorizeable(rebound_observation)
            ):
                raise DailyRowClaimRecognitionError(
                    rebound.reason or "immediate-before Claim revalidation failed"
                )
            _ensure_fresh(before_frame, runtime)
            _ensure_runtime_ready(runtime)
            annotated = Path(runtime.session) / "annotated-daily-row-claim-immediate-before.png"
            _annotate_daily_claim_frame(
                before_frame,
                row_bounds=tuple(rebound.visual_evidence["row_bounds"]),  # type: ignore[index]
                target_roi=rebound.target_roi,  # type: ignore[arg-type]
                output=annotated,
            )
            try:
                annotated_immediate_before = str(
                    annotated.resolve()
                    .relative_to(session.session_directory.resolve())
                ).replace("\\", "/")
            except (OSError, ValueError):
                annotated_immediate_before = str(annotated)
            runtime.tap(
                before_frame,
                target_identity=DAILY_CLAIM_ACTION_IDENTITY,
                target_roi=rebound.target_roi,  # type: ignore[arg-type]
                action_key=DAILY_CLAIM_ACTION_IDENTITY,
                action_class=DAILY_CLAIM_ACTION_CLASS,
                consequential=False,
            )

        def recognize_successor(after: CapturedNativeFrame) -> str:
            nonlocal terminal_recognition
            terminal_recognition = _settle_daily_claim_successor(
                session=session,
                runtime=runtime,
                recognizer=recognizer,
                immediate_post=after,
                before=before_recognition,  # type: ignore[arg-type]
                game_day_id=game_day_id,
                wall_utc=wall_utc,
                frames=frames,
                recognitions=recognitions,
                polls=polls,
            )
            return (
                DAILY_SELECTED_STATE
                if terminal_recognition is not None
                else UNKNOWN_STATE
            )

        action = session.run_action(
            action_class=DAILY_CLAIM_ACTION_CLASS,
            label=DAILY_CLAIM_ACTION_IDENTITY,
            capture=capture,
            dispatch=_NativeTapDispatch(dispatch).dispatch,
            recognize=recognize_successor,
            consequence_class=DAILY_CLAIM_CONSEQUENCE_CLASS,
        )
        if action.status != "completed" or terminal_recognition is None:
            raise DailyRowClaimRecognitionError(
                "Daily Claim semantic postcondition was not proven"
            )
        session.terminal_status = "completed"
        before_visual = dict(before_recognition.visual_evidence or {})
        return _claim_result(
            status="completed",
            reason="aggregate Daily Claim postcondition proven",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=polls,
            game_day_id=game_day_id,
            mode="canary",
            claim={
                "points_before": before_visual.get("points"),
                "points_after": dict(terminal_recognition.visual_evidence or {}).get("points"),
                "reset_timer": before_visual.get("reset_timer"),
                "reset_timer_seconds": before_visual.get("reset_timer_seconds"),
                "reset_observed_utc": before_visual.get("reset_observed_utc"),
                "reset_deadline_utc": before_visual.get("reset_deadline_utc"),
                "reset_deadline_identity": before_visual.get(
                    "reset_deadline_identity"
                ),
                "reset_deadline_tolerance_seconds": before_visual.get(
                    "reset_deadline_tolerance_seconds"
                ),
                "action_class": DAILY_CLAIM_ACTION_CLASS,
                "consequence_class": DAILY_CLAIM_CONSEQUENCE_CLASS,
                "annotated_immediate_before": annotated_immediate_before,
            },
        )
    except BaseException as exc:
        session.terminal_status = "evidence_required"
        session.blocker = str(exc)
        return _claim_result(
            status="evidence_required",
            reason=f"{type(exc).__name__}: {exc}",
            session=session,
            frames=frames,
            recognitions=recognitions,
            polls=polls,
            game_day_id=game_day_id,
            mode="canary",
        )


def _popup_value(recognition: Any, key: str, default: Any = None) -> Any:
    if isinstance(recognition, Mapping):
        return recognition.get(key, default)
    return getattr(recognition, key, default)


def _popup_record(recognition: Any) -> dict[str, Any]:
    target_roi = _popup_value(recognition, "target_roi")
    if isinstance(target_roi, list):
        target_roi = tuple(target_roi)
    return {
        "status": _popup_value(recognition, "status"),
        "recognized": bool(
            _popup_value(
                recognition,
                "recognized",
                _popup_value(recognition, "status") == "allowed",
            )
        ),
        "popup_identity": _popup_value(recognition, "popup_identity"),
        "target_identity": _popup_value(recognition, "target_identity"),
        "target_roi": target_roi,
        "source_frame_sha256": _popup_value(recognition, "source_frame_sha256", ""),
        "semantic_evidence": tuple(
            _popup_value(recognition, "semantic_evidence", ()) or ()
        ),
        "reason": _popup_value(recognition, "reason", ""),
    }


def _popup_recognizer_call(
    recognizer: Any,
    frame: np.ndarray,
    *,
    source_frame_sha256: str,
) -> Any:
    if recognizer is None:
        from scripts.world_map_navigation_bluestacks import recognize_allowlisted_popup

        return recognize_allowlisted_popup(
            frame,
            source_frame_sha256=source_frame_sha256,
        )
    if callable(recognizer):
        return recognizer(frame, source_frame_sha256=source_frame_sha256)
    method = getattr(recognizer, "recognize_allowlisted_popup", None)
    if callable(method):
        return method(frame, source_frame_sha256=source_frame_sha256)
    method = getattr(recognizer, "recognize_popup", None)
    if callable(method):
        return method(frame, source_frame_sha256=source_frame_sha256)
    raise DailyRowClaimRecognitionError("VIP popup recognizer is not callable")


def _require_exact_vip_popup(
    recognition: Any,
    frame: CapturedNativeFrame,
    *,
    phase: str,
) -> dict[str, Any]:
    record = _popup_record(recognition)
    target_roi = record["target_roi"]
    semantics = {
        _normalize_text(value)
        for value in record["semantic_evidence"]
    }
    required_semantics = {
        "get pts",
        "log in every day to get vip pts",
        "close",
        "spatially associated close control",
    }
    if (
        record["status"] != "allowed"
        or record["popup_identity"] != VIP_POINTS_POPUP_IDENTITY
        or record["target_identity"] != VIP_POINTS_POPUP_CLOSE_IDENTITY
        or record["source_frame_sha256"] != frame.sha256
        or not isinstance(target_roi, (tuple, list))
        or len(target_roi) != 4
        or not all(isinstance(value, (int, np.integer)) for value in target_roi)
        or not (
            0 <= int(target_roi[0]) < int(target_roi[2]) <= NATIVE_WIDTH
            and 0 <= int(target_roi[1]) < int(target_roi[3]) <= NATIVE_HEIGHT
        )
        or not required_semantics.issubset(semantics)
    ):
        raise DailyRowClaimRecognitionError(
            f"{phase} is not the exact VIP_POINTS_GET_PTS popup contract"
        )
    record["target_roi"] = tuple(int(value) for value in target_roi)
    return record


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


def _daily_selected_successor(
    recognizer: Any,
    frame: CapturedNativeFrame,
) -> tuple[FrameRecognition | Mapping[str, Any] | None, dict[str, Any] | None]:
    method = getattr(recognizer, "recognize_daily_selected", None)
    if not callable(method):
        raise DailyRowClaimRecognitionError(
            "selected-Daily successor recognizer is not available"
        )
    result = method(frame.frame)
    if isinstance(result, Mapping):
        record = dict(result)
    elif hasattr(result, "as_dict"):
        record = dict(result.as_dict())
    else:
        record = dict(asdict(result))
    visual = record.get("visual_evidence")
    visual = visual if isinstance(visual, Mapping) else {}
    overlay = visual.get("full_frame_overlay")
    overlay = overlay if isinstance(overlay, Mapping) else {}
    generic_overlay = _generic_modal_overlay_evidence(frame.frame)
    record = dict(record)
    visual = dict(visual)
    visual["generic_modal_overlay"] = generic_overlay
    record["visual_evidence"] = visual
    positive = bool(
        record.get("recognized")
        and record.get("state") == DAILY_SELECTED_STATE
        and not bool(overlay.get("recognized"))
        and visual.get("blurred") is not True
        and visual.get("unblurred") is not False
        and visual.get("overlay_state") not in {"blurred", "modal"}
        and not generic_overlay["recognized"]
    )
    record["successor_proven"] = positive
    return result, record


def _popup_dismiss_result(
    *,
    status: str,
    reason: str,
    session: SessionLike,
    frames: Mapping[str, CapturedNativeFrame],
    popup_recognitions: Mapping[str, Mapping[str, Any]],
    recognitions: Mapping[str, FrameRecognition | Mapping[str, Any]],
    polls: Sequence[Mapping[str, Any]],
    successor: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": "dismiss-vip-popup",
        "reason": reason,
        "input_count": int(session.input_count),
        "resource_affecting_inputs": 0,
        "combat_confirmations": 0,
        "action_identity": VIP_POINTS_POPUP_CLOSE_IDENTITY,
        "action_class": NAVIGATION_ACTION_CLASS,
        "consequence_class": NAVIGATION_CONSEQUENCE_CLASS,
        "popup_identity": VIP_POINTS_POPUP_IDENTITY,
        "frames": {
            name: _frame_ref(frame, session.session_directory)
            for name, frame in frames.items()
        },
        "popup_recognitions": {
            name: dict(recognition)
            for name, recognition in popup_recognitions.items()
        },
        "recognitions": {
            name: (
                dict(recognition)
                if isinstance(recognition, Mapping)
                else recognition.as_dict()
            )
            for name, recognition in recognitions.items()
        },
        "polls": [dict(item) for item in polls],
        "successor": dict(successor) if successor is not None else None,
        "actions": [dict(item) for item in session.actions],
    }


def run_daily_row_claim_vip_popup_dismissal(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    recognizer: Any | None = None,
    popup_recognizer: Any | None = None,
    daily_recognizer: Any | None = None,
) -> dict[str, Any]:
    """Dismiss only the exact VIP Points popup, then observe selected Daily."""

    if popup_recognizer is None and recognizer is not None:
        popup_recognizer = (
            getattr(recognizer, "recognize_allowlisted_popup", None)
            or getattr(recognizer, "recognize_popup", None)
            or recognizer
        )
    if daily_recognizer is None and recognizer is not None:
        candidate = getattr(recognizer, "recognize_daily_selected", None)
        if callable(candidate):
            daily_recognizer = recognizer
    daily_recognizer = daily_recognizer or DailyRowClaimRecognizer()
    frames: dict[str, CapturedNativeFrame] = {}
    popup_recognitions: dict[str, dict[str, Any]] = {}
    recognitions: dict[str, FrameRecognition | Mapping[str, Any]] = {}
    polls: list[dict[str, Any]] = []
    successor: dict[str, Any] | None = None
    terminal_recognition: FrameRecognition | Mapping[str, Any] | None = None

    def result(status: str, reason: str) -> dict[str, Any]:
        return _popup_dismiss_result(
            status=status,
            reason=reason,
            session=session,
            frames=frames,
            popup_recognitions=popup_recognitions,
            recognitions=recognitions,
            polls=polls,
            successor=successor,
        )

    if not bool(getattr(runtime, "execute", False)):
        session.terminal_status = "evidence_required"
        session.blocker = "runtime execution is required for VIP popup dismissal"
        return result("evidence_required", session.blocker)

    try:
        source = session.observe(runtime.capture, label="daily-row-claim-source")
        frames["source"] = source
        source_popup = _popup_recognizer_call(
            popup_recognizer,
            source.frame,
            source_frame_sha256=source.sha256,
        )
        popup_recognitions["source"] = _popup_record(source_popup)
        _require_exact_vip_popup(source_popup, source, phase="source")

        def capture(label: str) -> CapturedNativeFrame:
            frame = runtime.capture(label)
            if label == f"{VIP_POINTS_POPUP_CLOSE_IDENTITY}-immediate-before":
                frames["immediate_before"] = frame
            elif label == f"{VIP_POINTS_POPUP_CLOSE_IDENTITY}-immediate-post":
                frames["immediate_post"] = frame
            elif label.startswith(f"{VIP_POINTS_POPUP_CLOSE_IDENTITY}-poll-"):
                frames[f"poll_{label.rsplit('-', 1)[-1]}"] = frame
            return frame

        def dispatch(before_frame: CapturedNativeFrame) -> None:
            before_popup = _popup_recognizer_call(
                popup_recognizer,
                before_frame.frame,
                source_frame_sha256=before_frame.sha256,
            )
            popup_recognitions["immediate_before"] = _popup_record(before_popup)
            exact = _require_exact_vip_popup(
                before_popup,
                before_frame,
                phase="immediate-before",
            )
            _ensure_fresh(before_frame, runtime)
            _ensure_runtime_ready(runtime)
            runtime.tap(
                before_frame,
                target_identity=VIP_POINTS_POPUP_CLOSE_IDENTITY,
                target_roi=exact["target_roi"],
                action_key=VIP_POINTS_POPUP_CLOSE_IDENTITY,
                action_class=NAVIGATION_ACTION_CLASS,
                consequential=False,
            )

        def inspect_successor(
            frame: CapturedNativeFrame,
            label: str,
            attempt: int,
        ) -> FrameRecognition | Mapping[str, Any] | None:
            nonlocal successor
            popup = _popup_recognizer_call(
                popup_recognizer,
                frame.frame,
                source_frame_sha256=frame.sha256,
            )
            popup_record = _popup_record(popup)
            popup_recognitions[label] = popup_record
            daily_result: FrameRecognition | Mapping[str, Any] | None = None
            daily_record: dict[str, Any] | None = None
            if popup_record["status"] == "absent":
                daily_result, daily_record = _daily_selected_successor(
                    daily_recognizer,
                    frame,
                )
                if daily_record is not None and daily_record.get("successor_proven"):
                    successor = {
                        "state": DAILY_SELECTED_STATE,
                        "popup_absent": True,
                        "unblurred": True,
                        "frame_name": (
                            "immediate_post"
                            if label == "immediate_post"
                            else f"poll_{attempt:02d}"
                        ),
                        "frame_sha256": frame.sha256,
                        "recognition": daily_record,
                    }
            poll = {
                "action_identity": VIP_POINTS_POPUP_CLOSE_IDENTITY,
                "attempt": attempt,
                "label": label,
                "frame_name": (
                    "immediate_post"
                    if label == "immediate_post"
                    else f"poll_{attempt:02d}"
                ),
                "frame": _frame_ref(frame, session.session_directory),
                "popup": popup_record,
                "recognition": daily_record,
            }
            polls.append(poll)
            if daily_result is not None:
                recognitions[label] = daily_result
            return (
                daily_result
                if daily_record is not None
                and bool(daily_record.get("successor_proven"))
                else None
            )

        def recognize_successor(
            immediate_post: CapturedNativeFrame,
        ) -> str:
            nonlocal terminal_recognition
            terminal_recognition = inspect_successor(
                immediate_post,
                "immediate_post",
                0,
            )
            if terminal_recognition is not None:
                return DAILY_SELECTED_STATE
            deadline = time.monotonic() + VIP_POPUP_SUCCESS_POLL_TIMEOUT_SECONDS
            attempts = 0
            while attempts < VIP_POPUP_SUCCESS_POLL_MAX_ATTEMPTS:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                interval = max(
                    0.0,
                    min(VIP_POPUP_SUCCESS_POLL_INTERVAL_SECONDS, remaining),
                )
                if interval:
                    time.sleep(interval)
                if time.monotonic() >= deadline:
                    break
                attempts += 1
                label = f"{VIP_POINTS_POPUP_CLOSE_IDENTITY}-poll-{attempts:02d}"
                current = session.observe(runtime.capture, label=label)
                terminal_recognition = inspect_successor(
                    current,
                    f"poll_{attempts:02d}",
                    attempts,
                )
                if terminal_recognition is not None:
                    return DAILY_SELECTED_STATE
            return UNKNOWN_STATE

        action = session.run_action(
            action_class=NAVIGATION_ACTION_CLASS,
            label=VIP_POINTS_POPUP_CLOSE_IDENTITY,
            capture=capture,
            dispatch=_NativeTapDispatch(dispatch).dispatch,
            recognize=recognize_successor,
            consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
        )
        if action.status != "completed" or terminal_recognition is None:
            raise DailyRowClaimRecognitionError(
                "VIP popup dismissal selected-Daily successor was not proven"
            )
        session.terminal_status = "observed"
        return result(
            "observed",
            "VIP_POINTS_GET_PTS popup dismissed; selected Daily successor observed",
        )
    except BaseException as exc:
        session.terminal_status = "evidence_required"
        session.blocker = str(exc)
        return result("evidence_required", f"{type(exc).__name__}: {exc}")
