"""Bounded Home -> Quest -> Daily reconnaissance for local BlueStacks.

This module owns only two receipt-authorized navigation taps.  It never claims a
row, spends resources, performs recovery, or talks to ADB directly.  Runtime
capture and transport are supplied by ``LocalBlueStacksRuntime``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeBox


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
    bright_neutral = cv2.inRange(hsv, (0, 0, 155), (179, 85, 255))
    # This mask is intentionally never closed, opened, dilated, or otherwise
    # changed.  Only pixels present in this raw mask may authorize a target.
    return cv2.bitwise_or(saturated, bright_neutral)


def _home_component_records(
    frame: np.ndarray,
    geometry: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return raw-mask components that satisfy the supported-point gates."""

    icon_band = geometry["icon_band"]
    lane_left, lane_right = geometry["ownership_lane"]
    quest_center_x = geometry["quest_center"][0]
    quest_width = geometry["quest_ocr_roi"][2] - geometry["quest_ocr_roi"][0]
    quest_height = geometry["quest_ocr_roi"][3] - geometry["quest_ocr_roi"][1]
    raw_mask = _home_support_mask(frame, icon_band)
    if raw_mask.size == 0:
        return ()

    count, component_labels, stats, _ = cv2.connectedComponentsWithStats(raw_mask, 8)
    band_height, band_width = raw_mask.shape
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
            neighborhood = raw_mask[point_y - 1 : point_y + 2, point_x - 1 : point_x + 2]
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
    daily_center_x = (daily_x0 + daily_x1) / 2.0
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

