"""Fail-closed BlueStacks route for one direct 1K Food resource-item use.

The route starts at a verified canonical Home, opens Bag, selects the
Resource & Speedup category when another Bag tab is current, binds the exact
measured 1K Food card and quantity-one Use control, proves a positive
item/resource delta, and returns Home through a recognized visible control.
It never visits Quest or Daily and never uses Android Back.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
    NativeBox,
    NATIVE_HEIGHT,
    NATIVE_WIDTH,
)
from scripts.daily_row_claim_bluestacks import (
    _generic_modal_overlay_evidence,
)
from tasks.home_nav_recognition import (
    NAV_STRIP_BOX,
    _load_template as _load_home_nav_template,
    recognize_home_nav,
)


FLOW_ID = "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
EXPECTED_PACKAGE = "com.global.ztmslg"
RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
MAX_RESOURCE_LIST_SWIPES = 6
MAX_ROUTE_INPUTS = 10
RESOURCE_LIST_SCROLL_PX = 180
RESOURCE_LIST_LOWER_MARKERS = frozenset(
    {
        "gas",
        "wood",
        "steel",
        "antiserum",
        "gathering",
        "omni",
        "march",
    }
)
RESOURCE_LIST_LARGER_FOOD_MARKERS = frozenset({"2k", "5k", "10k", "50k"})
ITEM_USE_ACTION_KEY = "daily-resource-item:use-1k-food"
ITEM_TARGET_IDENTITY = "daily-resource-item:1k-food"
USE_TARGET_IDENTITY = "daily-resource-item:use-1k-food"
BAG_TARGET_IDENTITY = "daily-resource-item:bag"
RESOURCES_TARGET_IDENTITY = "daily-resource-item:resources-tab"
RESOURCE_LIST_SWIPE_TARGET_IDENTITY = "daily-resource-item:resource-list-upward-swipe"
HOME_TARGET_IDENTITY = "daily-resource-item:home"
RESOURCE_ITEM_STATE = "RESOURCES_1K_FOOD_READY"
RESOURCE_SUCCESSOR_STATE = "RESOURCES_1K_FOOD_USED"
HOME_SUCCESSOR_STATE = "HOME_VERIFIED"
RESOURCE_LIST_LANE_WIDTH = 72
RESOURCE_LIST_TOP_MARGIN = 12
RESOURCE_LIST_BOTTOM_MARGIN = 80
BAG_CATEGORY_TAB_BAND = (170, 240)
BAG_CATEGORY_CONTEXT_LABELS = frozenset({"military", "gadget", "other", "recent"})
BAG_CATEGORY_TAB_MIN_RED_DOMINANCE = 12.0
BAG_CATEGORY_TAB_WINNER_MARGIN = 8.0
BAG_CATEGORY_TAB_PAD_LEFT = 6
BAG_CATEGORY_TAB_PAD_TOP = 45
BAG_CATEGORY_TAB_PAD_RIGHT = 6
BAG_CATEGORY_TAB_PAD_BOTTOM = 8
BAG_CATEGORY_TAB_VISUAL_Y0 = 90
BAG_CATEGORY_TAB_VISUAL_Y1 = 250

# Measured from the checked-in native Home navigation strip: the Bag icon
# occupies this half-open ROI, while the OCR label-only area extends below it.
# This route-local geometry deliberately does not reuse the shared label-center
# tap point at (431, 1247).
HOME_BAG_ICON_ROI: NativeBox = (396, 1213, 462, 1247)
HOME_BAG_TEMPLATE_CORRELATION_THRESHOLD = 0.95

_OVERLAY_MARKERS = frozenset(
    {
        "cancel",
        "close",
        "captcha",
        "confirm",
        "dialog",
        "modal",
        "payment",
        "popup",
        "purchase",
        "checkout",
        "loading",
        "retry",
        "unknown",
    }
)
_FORBIDDEN_ITEM_MARKERS = frozenset(
    {
        "ap",
        "stamina",
        "premium",
        "diamond",
        "paid",
        "cash",
        "unidentified",
    }
)


class DailyResourceItemRecognitionError(RuntimeError):
    """Raised when the route cannot prove a safe current-frame decision."""


class RuntimeLike(Protocol):
    execute: bool
    frame_max_age_seconds: float
    input_count: int

    def capture(self, label: str) -> CapturedNativeFrame: ...

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        action_class: str = "navigation",
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None: ...

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str,
    ) -> None: ...


class SessionLike(Protocol):
    input_count: int
    actions: list[dict[str, Any]]
    session_directory: Any
    terminal_status: str | None
    blocker: str | None
    next_action: str | None

    def observe(
        self,
        capture: Callable[[str], CapturedNativeFrame],
        *,
        label: str,
    ) -> CapturedNativeFrame: ...

    def run_action(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class OCRToken:
    text: str
    roi: NativeBox


@dataclass(frozen=True)
class ResourceItemRecognition:
    state: str
    recognized: bool
    target_identity: str | None = None
    target_roi: NativeBox | None = None
    item_name: str = ""
    owned_quantity: int | None = None
    quantity: int | None = None
    use_roi: NativeBox | None = None
    bulk_visible: bool = False
    bulk_disjoint_from_use: bool = False
    premium_or_forbidden_visible: bool = False
    unidentified: bool = False
    fresh_frame: bool = True
    inventory_quantity: int | None = None
    food_resource: int | None = None
    home_verified: bool = False
    visual_evidence: Mapping[str, Any] | None = None
    reason: str | None = None
    quantity_source: str = ""
    single_use_semantics_proven: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceListSwipeBinding:
    """One content-aware list swipe measured from one current Resources frame."""

    lane: NativeBox
    start: tuple[int, int]
    end: tuple[int, int]
    content_roi: NativeBox
    use_rois: tuple[NativeBox, ...]
    bulk_rois: tuple[NativeBox, ...]
    signature: tuple[tuple[object, ...], ...]
    direction: str = "forward"
    source: str = "current-frame-resources-content"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _record(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    method = getattr(value, "as_dict", None)
    if callable(method):
        return dict(method())
    return dict(asdict(value)) if hasattr(value, "__dataclass_fields__") else {}


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _valid_roi(value: object) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 4
        and all(isinstance(item, (int, np.integer)) for item in value)
        and 0 <= int(value[0]) < int(value[2]) <= NATIVE_WIDTH
        and 0 <= int(value[1]) < int(value[3]) <= NATIVE_HEIGHT
    )


def _roi(value: Sequence[int]) -> NativeBox | None:
    if len(value) != 4:
        return None
    candidate = tuple(int(item) for item in value)
    return candidate if _valid_roi(candidate) else None


def _default_ocr(image: np.ndarray) -> Mapping[str, Sequence[object]]:
    import pytesseract

    return pytesseract.image_to_data(
        image,
        config="--oem 3 --psm 11",
        output_type=pytesseract.Output.DICT,
    )


def _ocr_tokens(
    frame: np.ndarray,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[OCRToken, ...]:
    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return ()
    data = ocr(frame)
    tokens: list[OCRToken] = []
    for text, left, top, width, height in zip(
        data.get("text", ()),
        data.get("left", ()),
        data.get("top", ()),
        data.get("width", ()),
        data.get("height", ()),
    ):
        normalized = _normalize_text(text)
        if not normalized:
            continue
        try:
            box = _roi((int(left), int(top), int(left) + int(width), int(top) + int(height)))
        except (TypeError, ValueError):
            box = None
        if box is not None:
            tokens.append(OCRToken(normalized, box))
    return tuple(tokens)


def _token_center(token: OCRToken) -> tuple[float, float]:
    return ((token.roi[0] + token.roi[2]) / 2.0, (token.roi[1] + token.roi[3]) / 2.0)


def _line_tokens(
    tokens: Sequence[OCRToken],
    *,
    tolerance: int = 24,
) -> tuple[tuple[OCRToken, ...], ...]:
    lines: list[list[OCRToken]] = []
    for token in sorted(tokens, key=lambda item: (_token_center(item)[1], item.roi[0])):
        center_y = _token_center(token)[1]
        line = next(
            (
                candidate
                for candidate in lines
                if abs(_token_center(candidate[0])[1] - center_y) <= tolerance
            ),
            None,
        )
        if line is None:
            lines.append([token])
        else:
            line.append(token)
    return tuple(
        tuple(sorted(line, key=lambda item: item.roi[0]))
        for line in lines
    )


def _line_text(line: Sequence[OCRToken]) -> str:
    return " ".join(token.text for token in line)


def _line_words(line: Sequence[OCRToken]) -> tuple[str, ...]:
    return tuple(word for token in line for word in token.text.split())


def _ocr_overlay_markers(tokens: Sequence[OCRToken]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                word
                for token in tokens
                for word in token.text.split()
                if word in _OVERLAY_MARKERS
            }
        )
    )


def _overlay_free_current_frame(frame: np.ndarray) -> tuple[bool, Mapping[str, Any]]:
    """Require the shared modal detector to positively prove a clear frame."""

    try:
        evidence = _generic_modal_overlay_evidence(frame)
    except Exception as exc:
        return (
            False,
            {
                "recognized": True,
                "state": "unknown",
                "panel_candidates": (),
                "reason": f"visual-panel-detector-failed:{type(exc).__name__}",
            },
        )
    if not isinstance(evidence, Mapping):
        return (
            False,
            {
                "recognized": True,
                "state": "unknown",
                "panel_candidates": (),
                "reason": "visual-panel-detector-returned-invalid-evidence",
            },
        )
    panel_candidates = evidence.get("panel_candidates")
    clear = (
        evidence.get("recognized") is False
        and evidence.get("state") == "none_observed"
        and isinstance(panel_candidates, (tuple, list))
        and not panel_candidates
    )
    return clear, evidence


def _positive_integer(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", value)) and int(value) > 0


def _food_name_line(line: Sequence[OCRToken]) -> bool:
    """Recognize only the exact item-name anchor, with optional OCR suffixes."""

    words = _line_words(line)
    # Icon OCR can inject junk tokens before the real title. Accept the first
    # exact ``1k food`` pair and ignore a bounded prefix.
    start = None
    for index in range(len(words) - 1):
        if words[index : index + 2] == ("1k", "food"):
            start = index
            break
    if start is None:
        return False
    if start > 3:
        return False
    suffix = words[start + 2 :]
    if not suffix:
        return True
    # A name such as ``1K Food Pack`` must not be accepted as the target.
    return suffix[0] in {
        "owned",
        "have",
        "count",
        "quantity",
        "qty",
        "x",
        "use",
        "in",
        "bulk",
        "inbulk",
    } or _positive_integer(suffix[0])


def _selected_resource_words(words: Sequence[str]) -> bool:
    """Accept the observed ``Resource & Speedup`` selected tab spelling."""

    compact = tuple(word for word in words if word not in {"&", "and"})
    return any(
        compact[index : index + 2] == ("resource", "speedup")
        for index in range(max(0, len(compact) - 1))
    )


def _union_roi(rois: Sequence[NativeBox]) -> NativeBox | None:
    if not rois or not all(_valid_roi(roi) for roi in rois):
        return None
    return (
        min(roi[0] for roi in rois),
        min(roi[1] for roi in rois),
        max(roi[2] for roi in rois),
        max(roi[3] for roi in rois),
    )


def _selected_resource_tab(tokens: Sequence[OCRToken]) -> NativeBox | None:
    """Locate the Resource & Speedup category label ROI (selected or not)."""

    matches: list[NativeBox] = []
    for line in _line_tokens(
        token
        for token in tokens
        if BAG_CATEGORY_TAB_BAND[0] <= _token_center(token)[1] <= BAG_CATEGORY_TAB_BAND[1]
    ):
        words = _line_words(line)
        if _selected_resource_words(words):
            direct_start = next(
                (
                    index
                    for index, token in enumerate(line)
                    if token.text == "resource"
                    and any(
                        candidate.text == "speedup"
                        for candidate in line[index + 1 : index + 4]
                    )
                ),
                None,
            )
            if direct_start is None:
                selected_tokens = [
                    token
                    for token in line
                    if "resource" in token.text and "speedup" in token.text
                ]
            else:
                end = next(
                    index
                    for index in range(direct_start + 1, min(len(line), direct_start + 4))
                    if line[index].text == "speedup"
                )
                selected_tokens = list(line[direct_start : end + 1])
            union = _union_roi(tuple(token.roi for token in selected_tokens))
            if union is not None:
                matches.append(union)
    return matches[0] if len(matches) == 1 else None


def _bag_category_tab_rois(tokens: Sequence[OCRToken]) -> dict[str, NativeBox]:
    """Bind every visible Bag category label from the current tab strip."""

    rois: dict[str, NativeBox] = {}
    resource = _selected_resource_tab(tokens)
    if resource is not None:
        rois["resource_speedup"] = resource
    band_tokens = tuple(
        token
        for token in tokens
        if BAG_CATEGORY_TAB_BAND[0] <= _token_center(token)[1] <= BAG_CATEGORY_TAB_BAND[1]
    )
    for label in sorted(BAG_CATEGORY_CONTEXT_LABELS):
        matches = [token for token in band_tokens if token.text == label]
        if len(matches) == 1 and _valid_roi(matches[0].roi):
            rois[label] = matches[0].roi
    return rois


def _expand_tab_visual_roi(label_roi: NativeBox) -> NativeBox | None:
    if not _valid_roi(label_roi):
        return None
    x0, y0, x1, y1 = label_roi
    return (
        max(0, x0 - BAG_CATEGORY_TAB_PAD_LEFT),
        max(BAG_CATEGORY_TAB_VISUAL_Y0, y0 - BAG_CATEGORY_TAB_PAD_TOP),
        min(NATIVE_WIDTH, x1 + BAG_CATEGORY_TAB_PAD_RIGHT),
        min(BAG_CATEGORY_TAB_VISUAL_Y1, y1 + BAG_CATEGORY_TAB_PAD_BOTTOM),
    )


def _red_dominance(frame: np.ndarray, bounds: NativeBox) -> float | None:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] < 3:
        return None
    if not _valid_roi(bounds):
        return None
    x0, y0, x1, y1 = bounds
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    red = crop[:, :, 2].astype(np.float32)
    green = crop[:, :, 1].astype(np.float32)
    return float(np.mean(red - green))


def classify_selected_bag_category(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
    tokens: Sequence[OCRToken] | None = None,
) -> str | None:
    """Return the visually selected Bag category id, or None when ambiguous."""

    resolved = tuple(tokens) if tokens is not None else _ocr_tokens(frame, ocr or _default_ocr)
    rois = _bag_category_tab_rois(resolved)
    if "resource_speedup" not in rois:
        return None
    if len(BAG_CATEGORY_CONTEXT_LABELS & set(rois)) < 3:
        return None
    scores: dict[str, float] = {}
    for name, label_roi in rois.items():
        visual = _expand_tab_visual_roi(label_roi)
        if visual is None:
            return None
        score = _red_dominance(frame, visual)
        if score is None:
            return None
        scores[name] = score
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner, winner_score = ordered[0]
    runner_score = ordered[1][1] if len(ordered) > 1 else 0.0
    if (
        winner_score < BAG_CATEGORY_TAB_MIN_RED_DOMINANCE
        or winner_score - runner_score < BAG_CATEGORY_TAB_WINNER_MARGIN
    ):
        return None
    return winner


def bind_resources_category_tab(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> NativeBox | None:
    """Bind Resource & Speedup for one tap when another Bag category is selected."""

    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    rois = _bag_category_tab_rois(tokens)
    label = rois.get("resource_speedup")
    if label is None:
        return None
    selected = classify_selected_bag_category(frame, tokens=tokens)
    if selected is None or selected == "resource_speedup":
        return None
    return label


def _control_line_rois(
    tokens: Sequence[OCRToken],
    *,
    label: str,
) -> tuple[NativeBox, ...]:
    """Group one visible control label with its same-line words."""

    rois: list[NativeBox] = []
    for line in _line_tokens(tokens):
        words = _line_words(line)
        if label == "use":
            matching = [token for token in line if token.text == "use"]
        else:
            matching = [
                token
                for token in line
                if token.text == label
                or (label == "bulk" and token.text in {"in", "bulk", "inbulk"})
            ]
        if not matching:
            continue
        if label == "bulk" and not (
            "bulk" in words
            or "inbulk" in words
            or "in" in words and "bulk" in words
        ):
            continue
        if label == "use":
            union = _union_roi(tuple(token.roi for token in matching))
        else:
            union = _union_roi(
                tuple(
                    token.roi
                    for token in line
                    if token.text in {"in", "bulk", "inbulk"}
                )
            )
        if union is not None:
            rois.append(union)
    return tuple(rois)


def _visual_action_control_rois(
    frame: np.ndarray,
    content: NativeBox,
) -> tuple[NativeBox, ...]:
    """Find conservative red action-button exclusions from current pixels."""

    x0, y0, x1, y1 = content
    crop_x0 = max(430, x0)
    crop = frame[y0:y1, crop_x0:x1]
    if crop.size == 0:
        return ()
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(
        hsv,
        np.array((0, 80, 70), dtype=np.uint8),
        np.array((20, 255, 255), dtype=np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(red)
    candidates: list[NativeBox] = []
    for index in range(1, count):
        x, y, width, height, area = (
            int(value) for value in stats[index]
        )
        if not (80 <= width <= 240 and 25 <= height <= 100 and area >= 1000):
            continue
        target = _roi(
            (x + crop_x0, y + y0, x + width + crop_x0, y + height + y0)
        )
        if target is not None:
            candidates.append(target)
    return tuple(candidates)


def _boxes_overlap(left: NativeBox, right: NativeBox) -> bool:
    return not (
        left[2] <= right[0]
        or right[2] <= left[0]
        or left[3] <= right[1]
        or right[3] <= left[1]
    )


def _box_inside(inner: object, outer: object) -> bool:
    return bool(
        _valid_roi(inner)
        and _valid_roi(outer)
        and int(outer[0]) <= int(inner[0])
        and int(inner[2]) <= int(outer[2])
        and int(outer[1]) <= int(inner[1])
        and int(inner[3]) <= int(outer[3])
    )


def _resource_from_lines(lines: Sequence[Sequence[OCRToken]]) -> int | None:
    candidates: list[int] = []
    for line in lines:
        text = _line_text(line)
        if "food" not in text or _food_name_line(line):
            continue
        numbers = [
            int(value.replace(",", ""))
            for value in re.findall(r"\b\d[\d,]*\b", text)
            if value.replace(",", "").isdigit()
        ]
        if numbers:
            candidates.append(numbers[-1])
    return candidates[0] if len(candidates) == 1 else None


def _resource_panel_separator_rows(frame: np.ndarray) -> tuple[int, ...]:
    if frame.size == 0:
        return ()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 140)
    counts = np.count_nonzero(edges, axis=1)
    rows = np.flatnonzero(counts >= max(160, int(round(frame.shape[1] * 0.42))))
    if rows.size == 0:
        return ()
    groups: list[list[int]] = [[int(rows[0])]]
    for row in rows[1:]:
        if int(row) <= groups[-1][-1] + 4:
            groups[-1].append(int(row))
        else:
            groups.append([int(row)])
    return tuple(int(round(sum(group) / len(group))) for group in groups)


def _measure_resource_item_panel(
    frame: np.ndarray,
    *,
    anchor_y: float,
    evidence_tokens: Sequence[OCRToken] = (),
) -> dict[str, Any] | None:
    """Measure one resource card from native pixels and independent separators."""

    separators = _resource_panel_separator_rows(frame)
    anchor = int(round(anchor_y))
    above = [row for row in separators if 320 < row < anchor - 18]
    below = [
        row
        for row in separators
        if anchor + 18 < row < min(NATIVE_HEIGHT, anchor + 240)
    ]
    if above and below:
        top = max(above) + 2
        bottom = min(below) - 2
        source = "visual-horizontal-separators"
        proven = True
    else:
        y0 = max(320, anchor - 120)
        y1 = min(NATIVE_HEIGHT, anchor + 120)
        support = np.count_nonzero(np.any(frame[y0:y1] != 0, axis=2), axis=1)
        broad = support >= int(round(frame.shape[1] * 0.45))
        if not broad.size or not bool(np.any(broad)):
            return None
        indexes = np.flatnonzero(broad)
        containing = indexes[
            (indexes >= max(0, anchor - y0 - 24))
            & (indexes <= min(broad.size - 1, anchor - y0 + 24))
        ]
        if not containing.size:
            return None
        start, end = int(containing[0]), int(containing[-1])
        while start > 0 and broad[start - 1]:
            start -= 1
        while end + 1 < broad.size and broad[end + 1]:
            end += 1
        top, bottom = y0 + start, y0 + end + 1
        source = "visual-background-support"
        proven = True
    if not (0 <= top < bottom <= NATIVE_HEIGHT):
        return None
    panel_x0, panel_x1 = 0, NATIVE_WIDTH
    if source == "visual-horizontal-separators":
        panel_edges = cv2.Canny(frame[top:bottom], 50, 140)
        columns = np.flatnonzero(
            np.count_nonzero(panel_edges, axis=0)
            >= max(24, int(round((bottom - top) * 0.35)))
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
    if not (0 <= panel_x0 < panel_x1 <= NATIVE_WIDTH):
        return None
    return {
        "bounds": (panel_x0, top, panel_x1, bottom),
        "source": source,
        "proven": proven,
        "horizontal_separators": separators,
    }


def _measure_resource_item_card(
    frame: np.ndarray,
    *,
    anchor_y: float,
    anchor_tokens: Sequence[OCRToken],
    tokens: Sequence[OCRToken],
) -> dict[str, Any] | None:
    """Measure the current resource card before using OCR controls."""

    measured = _measure_resource_item_panel(
        frame,
        anchor_y=anchor_y,
        evidence_tokens=anchor_tokens,
    )
    if measured is None or measured.get("proven") is not True:
        return None
    separators = tuple(measured.get("horizontal_separators") or ())
    if not (
        any(row < anchor_y - 18 for row in separators)
        and any(row > anchor_y + 18 for row in separators)
    ):
        return None
    bounds = measured.get("bounds")
    if not _valid_roi(bounds):
        return None
    bounds = tuple(int(value) for value in bounds)
    if bounds[1] <= 0 or bounds[3] >= NATIVE_HEIGHT:
        return None
    band_tokens = tuple(
        token
        for token in tokens
        if bounds[1] <= token.roi[1] and token.roi[3] <= bounds[3]
    )
    refined = _measure_resource_item_panel(
        frame,
        anchor_y=anchor_y,
        evidence_tokens=band_tokens or anchor_tokens,
    )
    if refined is None or refined.get("proven") is not True:
        return None
    refined_separators = tuple(refined.get("horizontal_separators") or ())
    if not (
        any(row < anchor_y - 18 for row in refined_separators)
        and any(row > anchor_y + 18 for row in refined_separators)
    ):
        return None
    refined_bounds = refined.get("bounds")
    if not _valid_roi(refined_bounds):
        return None
    refined["bounds"] = tuple(int(value) for value in refined_bounds)
    if refined["bounds"][1] <= 0 or refined["bounds"][3] >= NATIVE_HEIGHT:
        return None
    return refined


def _food_line(line: Sequence[OCRToken]) -> bool:
    """Accept only the exact item-name field before metadata/control text."""

    return _food_name_line(line)


def recognize_resources_screen(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> ResourceItemRecognition:
    """Bind the visually selected ``Resource & Speedup`` context from one fresh frame."""

    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    overlay_markers = _ocr_overlay_markers(tokens)
    overlay = bool(overlay_markers)
    overlay_free, modal_evidence = _overlay_free_current_frame(frame)
    selected = _selected_resource_tab(tokens)
    selected_category = classify_selected_bag_category(frame, tokens=tokens)
    content = _resource_content_roi(selected) if selected is not None else None
    visual_controls = (
        _visual_action_control_rois(frame, content)
        if content is not None
        else ()
    )
    words = {word for token in tokens for word in token.text.split()}
    panel_candidates = modal_evidence.get("panel_candidates", ())
    stacked_list_surface = bool(
        selected is not None
        and selected_category == "resource_speedup"
        and {"diamond", "shop"} <= words
        and len({"military", "gadget", "other", "recent"} & words) >= 3
        and len(visual_controls) >= 3
        and isinstance(panel_candidates, (tuple, list))
        and len(panel_candidates) >= 6
    )
    overlay_free = overlay_free or stacked_list_surface
    if (
        selected is None
        or selected_category != "resource_speedup"
        or overlay
        or not overlay_free
    ):
        return ResourceItemRecognition(
            "UNKNOWN",
            False,
            reason="resources-tab-is-missing-or-ambiguous",
            visual_evidence={
                "tokens": tuple(token.text for token in tokens),
                "selected_resource_tab": selected,
                "selected_bag_category": selected_category,
                "overlay": overlay,
                "overlay_markers": overlay_markers,
                "generic_modal_overlay": dict(modal_evidence),
                "overlay_free": overlay_free,
                "stacked_list_surface": stacked_list_surface,
                "visual_action_control_count": len(visual_controls),
            },
        )
    return ResourceItemRecognition(
        "RESOURCES",
        True,
        target_identity=RESOURCES_TARGET_IDENTITY,
        target_roi=selected,
        visual_evidence={
            "resources_tab": selected,
            "selected_category": "Resource & Speedup",
            "selected_bag_category": selected_category,
            "overlay": overlay,
            "overlay_markers": overlay_markers,
            "generic_modal_overlay": dict(modal_evidence),
            "overlay_free": overlay_free,
            "stacked_list_surface": stacked_list_surface,
            "visual_action_control_count": len(visual_controls),
        },
    )


def _resource_content_roi(selected_tab: NativeBox) -> NativeBox | None:
    top = int(selected_tab[3]) + RESOURCE_LIST_TOP_MARGIN
    bottom = NATIVE_HEIGHT - RESOURCE_LIST_BOTTOM_MARGIN
    if not (0 <= top < bottom <= NATIVE_HEIGHT):
        return None
    return (0, top, NATIVE_WIDTH, bottom)


def _resource_list_tokens(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[tuple[OCRToken, ...], NativeBox] | None:
    tokens = _ocr_tokens(frame, ocr)
    selected = _selected_resource_tab(tokens)
    content = _resource_content_roi(selected) if selected is not None else None
    if content is None:
        return None
    content_tokens = tuple(
        token
        for token in tokens
        if _box_inside(token.roi, content)
        and token.text not in {"resource", "speedup"}
    )
    return content_tokens, content


def resource_list_content_signature(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> tuple[tuple[object, ...], ...] | None:
    """Return a stable, current-frame OCR signature for the visible list."""

    engine = ocr or _default_ocr
    resources = recognize_resources_screen(frame, ocr=engine)
    if not resources.recognized:
        return None
    listed = _resource_list_tokens(frame, ocr=engine)
    if listed is None:
        return None
    tokens, _content = listed
    if not tokens:
        return None
    return tuple(
        sorted(
            (
                token.text,
                token.roi[0] // 8,
                token.roi[1] // 8,
                token.roi[2] // 8,
                token.roi[3] // 8,
            )
            for token in tokens
        )
    )


def resource_list_progressed(
    before: Sequence[Sequence[object]] | None,
    after: Sequence[Sequence[object]] | None,
) -> bool:
    """Require a materially different visible list, not a transport receipt."""

    if not before or not after:
        return False
    left = tuple(tuple(row) for row in before)
    right = tuple(tuple(row) for row in after)
    if left == right:
        return False
    left_words = tuple(row[0] for row in left if row)
    right_words = tuple(row[0] for row in right if row)
    if left_words != right_words:
        return True
    changed = len(set(left) ^ set(right))
    return changed >= max(1, min(len(left), len(right)) // 5)


def _list_scroll_direction(words: set[str]) -> str:
    """Choose a short reverse/forward scroll from the current list context.

    ``reverse`` reveals upper rows (finger moves down). ``forward`` reveals
    lower rows (finger moves up). Food packs sit above Gas/Wood/Antiserum and
    below the opening percentage-boost rows.
    """

    if words & RESOURCE_LIST_LOWER_MARKERS:
        return "reverse"
    if "food" in words and (words & RESOURCE_LIST_LARGER_FOOD_MARKERS):
        return "reverse"
    return "forward"


def bind_resource_list_swipe(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> ResourceListSwipeBinding | None:
    """Bind one short central list swipe from the current frame."""

    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return None
    engine = ocr or _default_ocr
    resources = recognize_resources_screen(frame, ocr=engine)
    if not resources.recognized or not _valid_roi(resources.target_roi):
        return None
    listed = _resource_list_tokens(frame, ocr=engine)
    if listed is None:
        return None
    tokens, content = listed
    signature = resource_list_content_signature(frame, ocr=engine)
    if signature is None:
        return None
    visual_action_rois = _visual_action_control_rois(frame, content)
    ocr_use_rois = _control_line_rois(tokens, label="use")
    use_rois = (
        tuple(roi for roi in ocr_use_rois if roi[0] >= NATIVE_WIDTH // 2)
        if visual_action_rois
        else ocr_use_rois
    )
    use_rois = tuple(dict.fromkeys((*use_rois, *visual_action_rois)))
    ocr_bulk_rois = _control_line_rois(tokens, label="bulk")
    bulk_rois = (
        tuple(roi for roi in ocr_bulk_rois if roi[0] >= NATIVE_WIDTH // 2)
        if visual_action_rois
        else ocr_bulk_rois
    )
    visible_use_left = min((roi[0] for roi in use_rois), default=464)
    lane_right = min(440, visible_use_left - 24)
    lane_left = lane_right - RESOURCE_LIST_LANE_WIDTH
    if lane_left < 180 or lane_right <= lane_left:
        return None
    words = {word for token in tokens for word in token.text.split()}
    direction = _list_scroll_direction(words)
    if direction == "reverse":
        start_y = content[1] + 220
        end_y = min(content[3] - 24, start_y + RESOURCE_LIST_SCROLL_PX)
    else:
        start_y = content[3] - 24
        end_y = max(content[1] + 180, start_y - RESOURCE_LIST_SCROLL_PX)
    if not (
        content[1] < start_y < content[3]
        and content[1] < end_y < content[3]
        and start_y != end_y
    ):
        return None
    lane = (
        lane_left,
        min(start_y, end_y),
        lane_right,
        max(start_y, end_y) + 1,
    )
    if any(_boxes_overlap(lane, roi) for roi in (*use_rois, *bulk_rois)):
        return None
    return ResourceListSwipeBinding(
        lane=lane,
        start=((lane_left + lane_right) // 2, start_y),
        end=((lane_left + lane_right) // 2, end_y),
        content_roi=content,
        use_rois=use_rois,
        bulk_rois=bulk_rois,
        signature=signature,
        direction=direction,
    )


def recognize_food_item(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> ResourceItemRecognition:
    """Bind one visually measured Resources card and its single Use control."""

    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    lines = _line_tokens(tokens)
    food_lines = [line for line in lines if _food_line(line)]
    food_resource = _resource_from_lines(lines)
    full_text = " ".join(token.text for token in tokens)
    overlay = any(marker in full_text.split() for marker in _OVERLAY_MARKERS)
    if len(food_lines) != 1 or overlay:
        return ResourceItemRecognition(
            RESOURCE_ITEM_STATE,
            False,
            item_name="1K Food",
            premium_or_forbidden_visible=overlay,
            food_resource=food_resource,
            reason="unsafe-overlay-at-resource-item" if overlay else "exact-1k-food-row-not-proven",
        )
    line = food_lines[0]
    line_y = sum(_token_center(token)[1] for token in line) / len(line)
    panel = _measure_resource_item_card(
        frame,
        anchor_y=line_y,
        anchor_tokens=line,
        tokens=tokens,
    )
    if panel is None:
        return ResourceItemRecognition(
            RESOURCE_ITEM_STATE,
            False,
            item_name="1K Food",
            food_resource=food_resource,
            reason="current-resource-item-card-not-visually-proven",
        )
    panel_bounds = tuple(panel["bounds"])
    card_tokens = tuple(
        sorted(
            (
                token
                for token in tokens
                if _box_inside(token.roi, panel_bounds)
            ),
            key=lambda token: (_token_center(token)[1], token.roi[0]),
        )
    )
    if not all(_box_inside(token.roi, panel_bounds) for token in line):
        return ResourceItemRecognition(
            RESOURCE_ITEM_STATE,
            False,
            target_identity=ITEM_TARGET_IDENTITY,
            item_name="1K Food",
            food_resource=food_resource,
            reason="1k-food-anchor-escapes-measured-card",
            visual_evidence={"item_card": panel},
        )
    card_text = _line_text(card_tokens)
    card_words = _line_words(card_tokens)
    card_forbidden = any(
        marker in card_words for marker in _FORBIDDEN_ITEM_MARKERS
    )
    name_bottom = max(token.roi[3] for token in line)
    owned = None
    for owned_line in _line_tokens(card_tokens):
        if min(token.roi[1] for token in owned_line) < name_bottom - 4:
            continue
        owned_text = _line_text(owned_line)
        owned_match = re.search(
            r"\b(?:owned|have|count)[:\s]*(\d[\d,]*)\b",
            owned_text,
        )
        if owned_match is not None:
            owned = int(owned_match.group(1).replace(",", ""))
            break
        owned_words = _line_words(owned_line)
        if (
            owned_words
            and owned_words[0] in {"owned", "owned:"}
            and len(owned_words) >= 2
            and owned_words[1].replace(",", "").isdigit()
        ):
            owned = int(owned_words[1].replace(",", ""))
            break
    owned_matches = [] if owned is None else [str(owned)]
    explicit_quantity_matches = re.findall(
        r"\b(?:quantity|qty)[:\s]*(?:is\s*)?(\d+)\b",
        card_text,
    )
    pair_quantity_matches = re.findall(r"\bx[:\s]*(\d+)\b", card_text)
    quantity_matches = [*explicit_quantity_matches, *pair_quantity_matches]
    explicit_quantity = (
        int(quantity_matches[0]) if len(quantity_matches) == 1 else None
    )
    use_tokens = tuple(token for token in card_tokens if token.text == "use")
    ocr_bulk_boxes = _control_line_rois(card_tokens, label="bulk")
    use_boxes = _control_line_rois(card_tokens, label="use")
    use = use_tokens[0] if len(use_tokens) == 1 else None
    visual_controls = tuple(
        sorted(
            _visual_action_control_rois(frame, panel_bounds),
            key=lambda box: box[1],
        )
    )
    if use is None and not use_boxes and len(visual_controls) == 2:
        # Resource cards use a fixed vertical pair: red single-use control over
        # orange bulk control. The measured card owns both controls.
        use = OCRToken("use", visual_controls[0])
        use_tokens = (use,)
        use_boxes = (use.roi,)
    if owned is None and use is not None:
        # An enabled, card-owned single-use control proves at least one item is
        # available even when OCR misses the small Owned count.
        owned = 1
        owned_matches = ["enabled-use-implies-positive-owned"]
    visual_bulk_boxes = tuple(
        candidate
        for candidate in visual_controls
        if not _boxes_overlap(use.roi, candidate)
    )
    bulk_boxes = tuple(dict.fromkeys((*ocr_bulk_boxes, *visual_bulk_boxes)))
    bulk_overlaps_use = bool(
        use is not None
        and any(_boxes_overlap(use.roi, candidate) for candidate in bulk_boxes)
    )
    ordinary_use_implies_one = (
        len(use_tokens) == 1
        and len(use_boxes) == 1
        and explicit_quantity is None
        and not bulk_overlaps_use
    )
    quantity = (
        explicit_quantity
        if explicit_quantity is not None
        else 1
        if ordinary_use_implies_one
        else None
    )
    if (
        len(use_tokens) != 1
        or len(use_boxes) != 1
        or bulk_overlaps_use
        or card_forbidden
        or len(owned_matches) != 1
        or len(quantity_matches) > 1
        or owned is None
        or quantity is None
    ):
        return ResourceItemRecognition(
            RESOURCE_ITEM_STATE,
            False,
            target_identity=ITEM_TARGET_IDENTITY,
            item_name="1K Food",
            owned_quantity=owned,
            quantity=quantity,
            inventory_quantity=owned,
            food_resource=food_resource,
            bulk_visible=bool(bulk_boxes),
            bulk_disjoint_from_use=not bulk_overlaps_use,
            premium_or_forbidden_visible=card_forbidden,
            reason=(
                "1k-food-use-overlaps-bulk-control"
                if bulk_overlaps_use
                else "1k-food-card-evidence-is-ambiguous"
            ),
            visual_evidence={
                "item_card": panel,
                "item_card_bounds": panel_bounds,
                "item_anchor_tokens": tuple(token.roi for token in line),
                "card_tokens": tuple(token.roi for token in card_tokens),
                "use_count": len(use_tokens),
                "bulk_candidates": bulk_boxes,
                "quantity_source": (
                    "explicit"
                    if explicit_quantity is not None
                    else "ordinary-use-implied-one"
                    if ordinary_use_implies_one
                    else "unknown"
                ),
            },
            quantity_source=(
                "explicit"
                if explicit_quantity is not None
                else "ordinary-use-implied-one"
                if ordinary_use_implies_one
                else ""
            ),
            single_use_semantics_proven=ordinary_use_implies_one
            or explicit_quantity == 1,
        )
    recognized = owned >= 1 and quantity == 1
    return ResourceItemRecognition(
        RESOURCE_ITEM_STATE if recognized else "UNKNOWN",
        recognized,
        target_identity=ITEM_TARGET_IDENTITY if recognized else None,
        target_roi=panel_bounds,
        item_name="1K Food",
        owned_quantity=owned,
        quantity=quantity,
        use_roi=use.roi if use is not None else None,
        inventory_quantity=owned,
        food_resource=food_resource,
        bulk_visible=bool(bulk_boxes),
        bulk_disjoint_from_use=not bulk_overlaps_use,
        visual_evidence={
            "item_line": _line_text(line),
            "item_card": panel,
            "item_card_bounds": panel_bounds,
            "item_anchor_tokens": tuple(token.roi for token in line),
            "use_roi": use.roi if use is not None else None,
            "use_count": len(use_tokens),
            "bulk_candidates": bulk_boxes,
            "bulk_disjoint_from_use": not bulk_overlaps_use,
            "card_ownership_proven": True,
            "quantity_source": (
                "explicit"
                if explicit_quantity is not None
                else "ordinary-use-implied-one"
                if ordinary_use_implies_one
                else "unknown"
            ),
        },
        reason=None if recognized else "1k-food-quantity-must-be-exactly-one",
        quantity_source=(
            "explicit"
            if explicit_quantity is not None
            else "ordinary-use-implied-one"
            if ordinary_use_implies_one
            else ""
        ),
        single_use_semantics_proven=ordinary_use_implies_one
        or explicit_quantity == 1,
    )


def recognize_food_item_in_resources(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> ResourceItemRecognition:
    """Require both the Resources context and exact item-card binding."""

    resources = recognize_resources_screen(frame, ocr=ocr)
    item = recognize_food_item(frame, ocr=ocr)
    if not resources.recognized:
        return ResourceItemRecognition(
            RESOURCE_ITEM_STATE,
            False,
            item_name=item.item_name or "1K Food",
            owned_quantity=item.owned_quantity,
            quantity=item.quantity,
            inventory_quantity=item.inventory_quantity,
            food_resource=item.food_resource,
            reason="current-resources-context-not-proven",
            visual_evidence={"resources": resources.as_dict(), "item": item.as_dict()},
        )
    return ResourceItemRecognition(
        **{
            **item.as_dict(),
            "visual_evidence": {
                **dict(item.visual_evidence or {}),
                "resources_context": resources.target_roi,
            },
        }
    )


def resource_item_authorizeable(
    value: Mapping[str, Any] | ResourceItemRecognition,
) -> bool:
    """Return true only for exact current-frame 1K Food quantity-one evidence."""

    record = _record(value)
    target = record.get("target_roi") or record.get("item_roi")
    use_roi = record.get("use_roi") or record.get("use_target_roi")
    visual = record.get("visual_evidence")
    item_card = visual.get("item_card") if isinstance(visual, Mapping) else None
    card_proven = (
        isinstance(item_card, Mapping)
        and item_card.get("proven") is True
        and item_card.get("source")
        in {"visual-horizontal-separators", "visual-background-support"}
        and tuple(item_card.get("bounds") or ()) == tuple(target or ())
        and visual.get("card_ownership_proven") is True
        and visual.get("use_count") == 1
    )
    return bool(
        record.get("recognized") is True
        and record.get("target_identity") == ITEM_TARGET_IDENTITY
        and record.get("item_name") == "1K Food"
        and type(record.get("owned_quantity")) is int
        and record["owned_quantity"] >= 1
        and record.get("quantity") == 1
        and _valid_roi(target)
        and _valid_roi(use_roi)
        and _box_inside(use_roi, target)
        and card_proven
        and record.get("single_use_semantics_proven") is True
        and record.get("quantity_source")
        in {"explicit", "ordinary-use-implied-one"}
        and (
            record.get("bulk_visible") is not True
            or record.get("bulk_disjoint_from_use") is True
        )
        and record.get("premium_or_forbidden_visible") is not True
        and record.get("unidentified") is not True
        and record.get("fresh_frame", True) is True
    )


def _number(value: object) -> int | None:
    return value if type(value) is int else None


def _owned_count(record: Mapping[str, Any]) -> int | None:
    for key in ("inventory_quantity", "owned_quantity"):
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def _resource_delta_verified(
    before: ResourceItemRecognition | Mapping[str, Any],
    after: ResourceItemRecognition | Mapping[str, Any],
) -> bool:
    """Prove exactly one owned 1K Food consumption from retained successors.

    Live BlueStacks evidence established an exact owned decrement of one
    (``129680 → 129679``). Food-resource totals were not reliably recognized,
    so an arbitrary Food increase is not accepted as proof.
    """

    left = _record(before)
    right = _record(after)
    owned_before = _owned_count(left)
    owned_after = _owned_count(right)
    food_before = _number(left.get("food_resource"))
    food_after = _number(right.get("food_resource"))

    if owned_before is None or owned_after is None:
        return False
    if owned_after != owned_before - 1:
        return False
    if food_before is not None and food_after is not None and food_after < food_before:
        return False
    return True


def resource_item_postcondition_verified(
    before: Mapping[str, Any] | ResourceItemRecognition,
    after: Mapping[str, Any] | ResourceItemRecognition,
) -> bool:
    """Require an exact one-item owned delta and verified Home."""

    right = _record(after)
    home = right.get("home_verified") is True or right.get("terminal_home_verified") is True
    home_payload = right.get("home")
    if isinstance(home_payload, Mapping):
        home = home or home_payload.get("verified") is True
    return _resource_delta_verified(before, after) and home


def _frame_ref(frame: CapturedNativeFrame, session_directory: Any) -> dict[str, Any]:
    try:
        path = frame.path.resolve().relative_to(session_directory.resolve())
        path_value = str(path).replace("\\", "/")
    except (AttributeError, OSError, ValueError):
        path_value = str(frame.path)
    return {
        "path": path_value,
        "sha256": frame.sha256,
        "captured_monotonic": frame.captured_monotonic,
    }


def _fresh(frame: CapturedNativeFrame, runtime: RuntimeLike) -> None:
    age = time.monotonic() - frame.captured_monotonic
    if age < 0 or age > float(getattr(runtime, "frame_max_age_seconds", 30.0)):
        raise DailyResourceItemRecognitionError("dispatch source frame is stale")


def _home_bag_target(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> NativeBox | None:
    """Bind the measured Bag icon from the current verified Home frame."""

    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return None
    recognition = recognize_home_nav(frame)
    if not recognition.is_home or not recognition.native_ok:
        return None
    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    if _ocr_overlay_markers(tokens):
        return None
    try:
        template = _load_home_nav_template()
    except Exception:
        return None
    nav_x0, nav_y0, nav_x1, nav_y1 = NAV_STRIP_BOX
    bag_x0, bag_y0, bag_x1, bag_y1 = HOME_BAG_ICON_ROI
    if not (
        nav_x0 <= bag_x0 < bag_x1 <= nav_x1
        and nav_y0 <= bag_y0 < bag_y1 <= nav_y1
        and template.shape[:2] == (nav_y1 - nav_y0, nav_x1 - nav_x0)
    ):
        return None
    template_patch = template[
        bag_y0 - nav_y0 : bag_y1 - nav_y0,
        bag_x0 - nav_x0 : bag_x1 - nav_x0,
    ]
    nav_strip = frame[nav_y0:nav_y1, nav_x0:nav_x1]
    if (
        template_patch.shape != nav_strip[
            bag_y0 - nav_y0 : bag_y1 - nav_y0,
            bag_x0 - nav_x0 : bag_x1 - nav_x0,
        ].shape
        or template_patch.size == 0
        or float(np.std(template_patch)) <= 1e-6
    ):
        return None
    matches = cv2.matchTemplate(
        nav_strip,
        template_patch,
        cv2.TM_CCOEFF_NORMED,
    )
    match_points = np.argwhere(matches >= HOME_BAG_TEMPLATE_CORRELATION_THRESHOLD)
    expected_x = bag_x0 - nav_x0
    expected_y = bag_y0 - nav_y0
    if (
        len(match_points) != 1
        or int(match_points[0][0]) != expected_y
        or int(match_points[0][1]) != expected_x
    ):
        return None
    return HOME_BAG_ICON_ROI


def _bag_back_arrow_visual(frame: np.ndarray) -> NativeBox | None:
    """Bind the top-left Bag back arrow from current-frame pixels only."""

    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return None

    # Native evidence shows one bright neutral arrow component inside the
    # top-left Bag chrome. Require its measured pixels rather than authorizing
    # the enclosing profile region or an OCR label.
    crop = frame[0:90, 0:140]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    neutral = cv2.inRange(
        hsv,
        np.array((0, 0, 150), dtype=np.uint8),
        np.array((179, 90, 255), dtype=np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(neutral)
    candidates: list[NativeBox] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if (
            700 <= area <= 2000
            and 10 <= x <= 35
            and 5 <= y <= 25
            and 50 <= width <= 90
            and 30 <= height <= 55
        ):
            target = _roi((max(0, x - 10), max(0, y - 10), x + width + 10, y + height + 10))
            if target is not None:
                candidates.append(target)
    return candidates[0] if len(candidates) == 1 else None


def _return_home_target(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> NativeBox | None:
    """Bind the Bag back arrow only after Resource & Speedup is selected."""

    resources = recognize_resources_screen(frame, ocr=ocr)
    if not resources.recognized:
        return None
    return _bag_back_arrow_visual(frame)


def _visible_label_target(
    frame: np.ndarray,
    labels: frozenset[str],
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> NativeBox | None:
    tokens = [token for token in _ocr_tokens(frame, ocr or _default_ocr) if token.text in labels]
    if len(tokens) != 1:
        return None
    return tokens[0].roi


def _recognize_home(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> dict[str, Any]:
    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "home_verified": False,
            "reason": "profile_dimensions_mismatch",
        }
    nav = recognize_home_nav(frame)
    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    markers = tuple(sorted(set(token.text for token in tokens) & _OVERLAY_MARKERS))
    recognized = bool(nav.is_home and nav.native_ok and not markers)
    return {
        "state": "HOME" if recognized else "UNKNOWN",
        "recognized": recognized,
        "home_verified": recognized,
        "target_identity": HOME_TARGET_IDENTITY if recognized else None,
        "target_roi": (0, 1213, NATIVE_WIDTH, NATIVE_HEIGHT) if recognized else None,
        "visual_evidence": {
            "home_navigation": {
                "recognized": bool(nav.is_home),
                "native_ok": bool(nav.native_ok),
                "correlation": nav.correlation,
                "reason": nav.reason,
            },
            "overlay_markers": markers,
        },
        "reason": None if recognized else "verified-home-not-proven",
    }


def _recognize_bag(
    frame: np.ndarray,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> dict[str, Any]:
    tokens = _ocr_tokens(frame, ocr or _default_ocr)
    resources = recognize_resources_screen(frame, ocr=ocr)
    overlay = any(marker in {token.text for token in tokens} for marker in _OVERLAY_MARKERS)
    header_tokens = tuple(
        token
        for token in tokens
        if token.text == "bag" and _token_center(token)[1] < 80
    )
    back_arrow = _bag_back_arrow_visual(frame)
    category_rois = _bag_category_tab_rois(tokens)
    selected_category = classify_selected_bag_category(frame, tokens=tokens)
    words = {token.text for token in tokens}
    bag_surface = (
        back_arrow is not None
        and not overlay
        and "resource_speedup" in category_rois
        and len(BAG_CATEGORY_CONTEXT_LABELS & set(category_rois)) >= 3
        and (
            bool(header_tokens)
            or {"diamond", "shop"} <= words
        )
    )
    recognized = bag_surface
    return {
        "state": "BAG" if recognized else "UNKNOWN",
        "recognized": recognized,
        "target_identity": BAG_TARGET_IDENTITY if recognized else None,
        "target_roi": category_rois.get("resource_speedup") if recognized else None,
        "visual_evidence": {
            "bag_header": header_tokens[0].roi if header_tokens else None,
            "back_arrow": back_arrow,
            "resources_tab": category_rois.get("resource_speedup"),
            "selected_bag_category": selected_category,
            "selected_category": "Resource & Speedup"
            if selected_category == "resource_speedup"
            else None,
            "direct_selected_successor": resources.recognized,
            "category_tabs": {
                name: list(roi) for name, roi in category_rois.items()
            },
            "overlay": overlay,
        },
        "reason": None
        if recognized
        else "bag-surface-or-category-strip-not-proven",
    }


def _semantic_evidence(
    frames: Mapping[str, CapturedNativeFrame],
    recognitions: Mapping[str, Any],
    *,
    session_directory: Any,
    resource_delta_verified: bool,
    terminal_home_verified: bool,
) -> dict[str, Any]:
    before = _record(recognitions.get("item-before") or recognitions.get("item-ready") or {})
    after = _record(recognitions.get("item-after") or {})
    home = _record(recognitions.get("home") or {})
    before_frame = frames.get("item-before")
    after_frame = frames.get("item-after")
    home_frame = frames.get("home") or frames.get("return-home-immediate-post")
    return {
        "before_owned_quantity": _owned_count(before),
        "after_owned_quantity": _owned_count(after),
        "before_food_resource": _number(before.get("food_resource")),
        "after_food_resource": _number(after.get("food_resource")),
        "resource_delta_verified": resource_delta_verified,
        "terminal_home_verified": terminal_home_verified,
        "home_verified": home.get("home_verified") is True,
        "item_before_frame": (
            _frame_ref(before_frame, session_directory) if before_frame is not None else None
        ),
        "item_after_frame": (
            _frame_ref(after_frame, session_directory) if after_frame is not None else None
        ),
        "terminal_home_frame": (
            _frame_ref(home_frame, session_directory) if home_frame is not None else None
        ),
    }


def _result(
    session: SessionLike,
    *,
    status: str,
    reason: str,
    frames: Mapping[str, CapturedNativeFrame],
    recognitions: Mapping[str, Any],
    item_use_calls: int = 0,
    resource_delta_verified: bool = False,
    terminal_home_verified: bool = False,
) -> dict[str, Any]:
    session.terminal_status = "completed" if status == "completed" else "evidence_required"
    if status != "completed":
        session.blocker = reason
        session.next_action = "retain evidence_required; require a materially changed hypothesis"
    return {
        "status": status,
        "flow_id": FLOW_ID,
        "reason": reason,
        "input_count": int(getattr(session, "input_count", 0)),
        "max_inputs": MAX_ROUTE_INPUTS,
        "max_resource_list_swipes": MAX_RESOURCE_LIST_SWIPES,
        "item_use_transport_calls": item_use_calls,
        "dispatch": item_use_calls > 0,
        "resource_delta_verified": resource_delta_verified,
        "terminal_home_verified": terminal_home_verified,
        "semantic_evidence": _semantic_evidence(
            frames,
            recognitions,
            session_directory=session.session_directory,
            resource_delta_verified=resource_delta_verified,
            terminal_home_verified=terminal_home_verified,
        ),
        "frames": {
            name: _frame_ref(frame, session.session_directory)
            for name, frame in frames.items()
        },
        "recognitions": {
            name: _record(recognition)
            for name, recognition in recognitions.items()
        },
        "actions": [dict(row) for row in getattr(session, "actions", ())],
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def _tap_action(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    label: str,
    target_identity: str,
    action_key: str,
    bind: Callable[[np.ndarray], NativeBox | None],
    recognize: Callable[[np.ndarray], Any],
    action_class: str = "navigation",
    consequential: bool = False,
    settled_successor: Callable[[], CapturedNativeFrame] | None = None,
) -> tuple[
    Any,
    CapturedNativeFrame | None,
    CapturedNativeFrame | None,
    Any | None,
]:
    if int(getattr(session, "input_count", 0)) >= MAX_ROUTE_INPUTS:
        raise DailyResourceItemRecognitionError("Daily Resource Item route input ceiling reached")

    before_frame: CapturedNativeFrame | None = None
    terminal_frame: CapturedNativeFrame | None = None
    terminal_recognition: Any | None = None

    def capture(action_label: str) -> CapturedNativeFrame:
        return runtime.capture(action_label)

    def dispatch(before: CapturedNativeFrame) -> None:
        nonlocal before_frame
        before_frame = before
        target = bind(before.frame)
        if target is None:
            raise DailyResourceItemRecognitionError(
                f"{target_identity} was not bound from the immediate-before frame"
            )
        _fresh(before, runtime)
        runtime.tap(
            before,
            target_identity=target_identity,
            target_roi=target,
            action_key=action_key,
            action_class=action_class,
            consequential=consequential,
        )

    def successor(after: CapturedNativeFrame) -> str:
        nonlocal terminal_frame, terminal_recognition
        terminal_frame = after
        terminal_recognition = recognize(after.frame)
        record = _record(terminal_recognition)
        return str(record.get("state") or "UNKNOWN") if record.get("recognized") else "UNKNOWN"

    action = session.run_action(
        action_class=action_class,
        label=label,
        capture=capture,
        dispatch=dispatch,
        recognize=successor,
        consequence_class="consequential" if consequential else "navigation_only",
        settled_successor=settled_successor,
    )
    return action, before_frame, terminal_frame, terminal_recognition


def _settled_observe(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    label: str,
    recognize: Callable[[np.ndarray], Any],
) -> tuple[CapturedNativeFrame, Any]:
    time.sleep(1.0)
    frame = session.observe(runtime.capture, label=label)
    return frame, recognize(frame.frame)


def _swipe_list_action(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    ordinal: int,
    before_signature: tuple[tuple[object, ...], ...],
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None,
) -> tuple[Any, CapturedNativeFrame | None, CapturedNativeFrame | None, Any, dict[str, Any]]:
    holder: dict[str, Any] = {}
    before_frame: CapturedNativeFrame | None = None
    after_frame: CapturedNativeFrame | None = None
    after_recognition: Any = None

    def capture(label: str) -> CapturedNativeFrame:
        return runtime.capture(label)

    def dispatch(before: CapturedNativeFrame) -> None:
        nonlocal before_frame
        before_frame = before
        ready = recognize_food_item_in_resources(before.frame, ocr=ocr)
        holder["item"] = ready
        if resource_item_authorizeable(ready):
            # Exact card already visible: do not overshoot with another scroll.
            signature = resource_list_content_signature(before.frame, ocr=ocr)
            holder["already_ready"] = True
            holder["before_signature"] = signature
            holder["signature"] = signature
            holder["progressed"] = True
            return
        binding = bind_resource_list_swipe(before.frame, ocr=ocr)
        if binding is None:
            raise DailyResourceItemRecognitionError(
                "resource-list swipe source is not current-frame bound"
            )
        holder["before_signature"] = binding.signature
        _fresh(before, runtime)
        runtime.swipe(
            before,
            start=binding.start,
            end=binding.end,
            target_identity=RESOURCE_LIST_SWIPE_TARGET_IDENTITY,
            action_key=f"daily-resource-item:scroll:{ordinal}:{before.sha256}",
        )

    def recognize(after: CapturedNativeFrame) -> str:
        nonlocal after_frame, after_recognition
        after_frame = after
        if holder.get("already_ready") is True:
            after_recognition = holder.get("item")
            return "RESOURCES_LIST_PROGRESS"
        resources = recognize_resources_screen(after.frame, ocr=ocr)
        signature = resource_list_content_signature(after.frame, ocr=ocr)
        item = recognize_food_item_in_resources(after.frame, ocr=ocr)
        holder.update(
            {
                "resources": resources,
                "signature": signature,
                "item": item,
            }
        )
        effective_before = holder.get("before_signature", before_signature)
        progressed = resource_list_progressed(effective_before, signature)
        holder["progressed"] = progressed
        after_recognition = item
        if not resources.recognized or not progressed:
            return "UNKNOWN"
        return "RESOURCES_LIST_PROGRESS"

    action = session.run_action(
        action_class="navigation",
        label=f"daily-resource-item-scroll-{ordinal:02d}",
        capture=capture,
        dispatch=dispatch,
        recognize=recognize,
        consequence_class="navigation_only",
        settled_successor=lambda: (
            time.sleep(1.0)
            or runtime.capture(f"daily-resource-item-scroll-{ordinal:02d}-settled")
        ),
    )
    return action, before_frame, after_frame, after_recognition, holder


def _run_route(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> dict[str, Any]:
    frames: dict[str, CapturedNativeFrame] = {}
    recognitions: dict[str, Any] = {}

    source = session.observe(runtime.capture, label="daily-resource-item-source")
    frames["source"] = source
    source_home = _recognize_home(source.frame, ocr=ocr)
    recognitions["home-source"] = source_home
    resources_frame: CapturedNativeFrame | None = None
    if not source_home.get("recognized"):
        source_resources = recognize_resources_screen(source.frame, ocr=ocr)
        recognitions["resources-source"] = source_resources
        if source_resources.recognized:
            # Already on the selected Resources list: continue the same find/use
            # path instead of scrolling once and abandoning the transaction.
            resources_frame = source
            frames["resources"] = resources_frame
            frames["bag"] = source
            recognitions["resources"] = source_resources
            recognitions["bag"] = {
                "state": "BAG",
                "recognized": True,
                "target_identity": BAG_TARGET_IDENTITY,
                "target_roi": source_resources.target_roi,
                "visual_evidence": {
                    "direct_selected_successor": True,
                    "resources_tab": source_resources.target_roi,
                },
            }
            max_inputs = int(getattr(session, "max_inputs", MAX_ROUTE_INPUTS) or MAX_ROUTE_INPUTS)
            if max_inputs <= 1 and _return_home_target(source.frame, ocr=ocr) is not None:
                _, home_before, home_post, home_successor = _tap_action(
                    runtime,
                    session,
                    label="daily-resource-item-return-home",
                    target_identity=HOME_TARGET_IDENTITY,
                    action_key="daily-resource-item:return-home",
                    bind=lambda frame: _return_home_target(frame, ocr=ocr),
                    recognize=lambda frame: _recognize_home(frame, ocr=ocr),
                    settled_successor=lambda: (
                        time.sleep(1.0)
                        or runtime.capture("daily-resource-item-return-home-settled")
                    ),
                )
                if home_before is not None:
                    frames["return-home-immediate-before"] = home_before
                if home_post is not None:
                    frames["return-home-immediate-post"] = home_post
                    frames["home"] = home_post
                terminal_home = bool(
                    home_post is not None
                    and _record(home_successor).get("home_verified") is True
                )
                recognitions["home"] = home_successor
                return _result(
                    session,
                    status="completed" if terminal_home else "evidence_required",
                    reason=(
                        "Resources source returned to verified Home"
                        if terminal_home
                        else "Resources source return did not prove verified Home"
                    ),
                    frames=frames,
                    recognitions=recognitions,
                    terminal_home_verified=terminal_home,
                )
        else:
            return _result(
                session,
                status="evidence_required",
                reason="source is not verified Home",
                frames=frames,
                recognitions=recognitions,
            )

    if resources_frame is None:
        _, bag_before, bag_post, bag_successor = _tap_action(
            runtime,
            session,
            label="daily-resource-item-open-bag",
            target_identity=BAG_TARGET_IDENTITY,
            action_key="daily-resource-item:open-bag",
            bind=lambda frame: _home_bag_target(frame, ocr=ocr),
            recognize=lambda frame: _recognize_bag(frame, ocr=ocr),
            settled_successor=lambda: (
                time.sleep(1.0) or runtime.capture("daily-resource-item-open-bag-settled")
            ),
        )
        if bag_before is not None:
            frames["bag-immediate-before"] = bag_before
        if bag_post is not None:
            frames["bag-immediate-post"] = bag_post
        if bag_post is None or not _record(bag_successor).get("recognized"):
            return _result(
                session,
                status="evidence_required",
                reason="Bag successor was not positively recognized",
                frames=frames,
                recognitions={**recognitions, "bag": bag_successor},
            )
        frames["bag"] = bag_post
        recognitions["bag"] = bag_successor

        resources_frame, resources_successor = _settled_observe(
            runtime,
            session,
            label="daily-resource-item-selected-resource-settled",
            recognize=lambda frame: recognize_resources_screen(frame, ocr=ocr),
        )
        if not resources_successor.recognized:
            if bind_resources_category_tab(resources_frame.frame, ocr=ocr) is None:
                return _result(
                    session,
                    status="evidence_required",
                    reason=(
                        "Bag opened without a selected Resource & Speedup "
                        "context and the category tab was not bindable"
                    ),
                    frames={**frames, "resources-settled": resources_frame},
                    recognitions={**recognitions, "resources": resources_successor},
                )
            _, tab_before, tab_post, resources_successor = _tap_action(
                runtime,
                session,
                label="daily-resource-item-select-resources",
                target_identity=RESOURCES_TARGET_IDENTITY,
                action_key="daily-resource-item:select-resources-tab",
                bind=lambda frame: bind_resources_category_tab(frame, ocr=ocr),
                recognize=lambda frame: recognize_resources_screen(frame, ocr=ocr),
                settled_successor=lambda: (
                    time.sleep(1.0)
                    or runtime.capture("daily-resource-item-select-resources-settled")
                ),
            )
            if tab_before is not None:
                frames["select-resources-immediate-before"] = tab_before
            if tab_post is not None:
                frames["select-resources-immediate-post"] = tab_post
                resources_frame = tab_post
            recognitions["select-resources"] = resources_successor
        if not _record(resources_successor).get("recognized"):
            return _result(
                session,
                status="evidence_required",
                reason="settled Resource & Speedup successor was not positively recognized",
                frames={**frames, "resources-settled": resources_frame},
                recognitions={**recognitions, "resources": resources_successor},
            )
        frames["resources"] = resources_frame
        recognitions["resources"] = resources_successor

    current_frame = resources_frame
    current_item = recognize_food_item_in_resources(current_frame.frame, ocr=ocr)
    current_signature = resource_list_content_signature(current_frame.frame, ocr=ocr)
    recognitions["item-current"] = current_item
    if not resource_item_authorizeable(current_item):
        if current_signature is None:
            return _result(
                session,
                status="evidence_required",
                reason="current Resources list signature is unknown before scrolling",
                frames=frames,
                recognitions=recognitions,
            )
        seen_signatures: set[tuple[tuple[object, ...], ...]] = {current_signature}
        for ordinal in range(1, MAX_RESOURCE_LIST_SWIPES + 1):
            binding = bind_resource_list_swipe(current_frame.frame, ocr=ocr)
            if binding is None or binding.signature != current_signature:
                return _result(
                    session,
                    status="evidence_required",
                    reason=f"resource-list swipe {ordinal} was not safely bound",
                    frames=frames,
                    recognitions=recognitions,
                )
            action, before, after, item_after, holder = _swipe_list_action(
                runtime,
                session,
                ordinal=ordinal,
                before_signature=current_signature,
                ocr=ocr,
            )
            if before is not None:
                frames[f"scroll-{ordinal:02d}-immediate-before"] = before
            if after is not None:
                frames[f"scroll-{ordinal:02d}-immediate-post"] = after
            after_signature = holder.get("signature")
            effective_before_signature = holder.get("before_signature")
            recognitions[f"scroll-{ordinal:02d}"] = {
                "state": "RESOURCES_LIST_PROGRESS"
                if holder.get("progressed") is True
                else "UNKNOWN",
                "recognized": holder.get("progressed") is True,
                "before_signature": effective_before_signature,
                "after_signature": after_signature,
                "lane": binding.lane,
                "content_roi": binding.content_roi,
                "use_rois": binding.use_rois,
                "bulk_rois": binding.bulk_rois,
                "item": _record(item_after),
                "already_ready": holder.get("already_ready") is True,
            }
            if holder.get("already_ready") is True:
                current_frame = before if before is not None else after
                current_item = holder.get("item") or item_after
                recognitions[f"item-after-scroll-{ordinal:02d}"] = current_item
                break
            if (
                action.status != "completed"
                or not holder.get("progressed")
                or not isinstance(effective_before_signature, tuple)
                or not isinstance(after_signature, tuple)
                or after_signature in seen_signatures
                or after is None
            ):
                return _result(
                    session,
                    status="evidence_required",
                    reason=(
                        f"resource-list swipe {ordinal} stalled, repeated, "
                        "or produced an unknown successor"
                    ),
                    frames=frames,
                    recognitions=recognitions,
                )
            seen_signatures.add(effective_before_signature)
            seen_signatures.add(after_signature)
            current_frame = after
            current_signature = after_signature
            current_item = item_after
            recognitions[f"item-after-scroll-{ordinal:02d}"] = current_item
            if resource_item_authorizeable(current_item):
                break
        else:
            return _result(
                session,
                status="evidence_required",
                reason="exact 1K Food was not exposed within the bounded list scroll",
                frames=frames,
                recognitions=recognitions,
            )
    if not resource_item_authorizeable(current_item):
        return _result(
            session,
            status="evidence_required",
            reason="exact measured-card 1K Food single Use was not proven",
            frames=frames,
            recognitions=recognitions,
        )
    ready_frame, ready_item = _settled_observe(
        runtime,
        session,
        label="daily-resource-item-item-ready-settled",
        recognize=lambda frame: recognize_food_item_in_resources(frame, ocr=ocr),
    )
    frames["item-ready-settled"] = ready_frame
    recognitions["item-ready-settled"] = ready_item
    if not resource_item_authorizeable(ready_item):
        return _result(
            session,
            status="evidence_required",
            reason="settled exact 1K Food Use was not proven before dispatch",
            frames=frames,
            recognitions=recognitions,
        )
    current_frame = ready_frame
    current_item = ready_item
    recognitions["item-ready"] = current_item

    use_before_holder: dict[str, Any] = {"item": current_item}

    def bind_use(frame: np.ndarray) -> NativeBox | None:
        item = recognize_food_item_in_resources(frame, ocr=ocr)
        use_before_holder["item"] = item
        return item.use_roi if resource_item_authorizeable(item) else None

    def recognize_use_successor(frame: np.ndarray) -> Any:
        item_after = recognize_food_item_in_resources(frame, ocr=ocr)
        use_before_holder["after"] = item_after
        before = use_before_holder.get("item")
        return ResourceItemRecognition(
            RESOURCE_SUCCESSOR_STATE,
            isinstance(before, ResourceItemRecognition)
            and _resource_delta_verified(before, item_after),
            item_name="1K Food",
            owned_quantity=item_after.owned_quantity,
            quantity=item_after.quantity,
            inventory_quantity=item_after.inventory_quantity,
            food_resource=item_after.food_resource,
            reason="resource_delta_not_proven",
        )

    _, use_before, use_post, use_successor = _tap_action(
        runtime,
        session,
        label=ITEM_USE_ACTION_KEY,
        target_identity=USE_TARGET_IDENTITY,
        action_key=ITEM_USE_ACTION_KEY,
        bind=bind_use,
        recognize=recognize_use_successor,
        action_class="resource_item_use",
        consequential=True,
        settled_successor=lambda: (
            time.sleep(1.0) or runtime.capture("daily-resource-item-use-settled")
        ),
    )
    item_before = use_before_holder.get("item")
    item_after = use_before_holder.get("after")
    item_use_calls = sum(
        1
        for row in getattr(session, "actions", ())
        if row.get("label") == ITEM_USE_ACTION_KEY
        or row.get("action_key") == ITEM_USE_ACTION_KEY
    )
    resource_delta = (
        isinstance(item_before, ResourceItemRecognition)
        and isinstance(item_after, ResourceItemRecognition)
        and _resource_delta_verified(item_before, item_after)
    )
    if use_before is not None:
        frames["item-before"] = use_before
    if use_post is not None:
        frames["item-after"] = use_post
    if use_post is None or not resource_delta:
        return _result(
            session,
            status="unresolved" if item_use_calls else "evidence_required",
            reason="1K Food Use did not prove an exact owned decrement of one",
            frames=frames,
            recognitions={
                **recognitions,
                "item-before": item_before,
                "item-after": item_after,
            },
            item_use_calls=item_use_calls,
            resource_delta_verified=resource_delta,
        )
    recognitions["item-before"] = item_before
    recognitions["item-after"] = use_successor

    _, home_before, home_post, home_successor = _tap_action(
        runtime,
        session,
        label="daily-resource-item-return-home",
        target_identity=HOME_TARGET_IDENTITY,
        action_key="daily-resource-item:return-home",
        bind=lambda frame: _return_home_target(frame, ocr=ocr),
        recognize=lambda frame: _recognize_home(frame, ocr=ocr),
        settled_successor=lambda: (
            time.sleep(1.0) or runtime.capture("daily-resource-item-return-home-settled")
        ),
    )
    if home_before is not None:
        frames["return-home-immediate-before"] = home_before
    if home_post is not None:
        frames["return-home-immediate-post"] = home_post
    if home_post is None or not _record(home_successor).get("home_verified"):
        return _result(
            session,
            status="evidence_required",
            reason="verified Home successor was not proven",
            frames=frames,
            recognitions={**recognitions, "home": home_successor},
            item_use_calls=item_use_calls,
            resource_delta_verified=resource_delta,
        )
    final_home, final_home_recognition = _settled_observe(
        runtime,
        session,
        label="daily-resource-item-return-home-settled-final",
        recognize=lambda frame: _recognize_home(frame, ocr=ocr),
    )
    terminal_home = bool(
        final_home_recognition.get("recognized") is True
        and final_home_recognition.get("home_verified") is True
    )
    frames["home"] = final_home
    recognitions["home"] = final_home_recognition
    if not terminal_home:
        return _result(
            session,
            status="evidence_required",
            reason="settled verified Home successor was not proven",
            frames=frames,
            recognitions=recognitions,
            item_use_calls=item_use_calls,
            resource_delta_verified=resource_delta,
        )
    return _result(
        session,
        status="completed",
        reason="1K Food use, resource delta, and settled Home verified",
        frames=frames,
        recognitions=recognitions,
        item_use_calls=item_use_calls,
        resource_delta_verified=resource_delta,
        terminal_home_verified=terminal_home,
    )


def run_daily_resource_item(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
) -> dict[str, Any]:
    """Execute the bounded direct route inside an owned development session."""

    if not bool(getattr(runtime, "execute", False)):
        session.terminal_status = "evidence_required"
        session.blocker = "runtime execution is required for resource-item delivery"
        return _result(
            session,
            status="evidence_required",
            reason=session.blocker,
            frames={},
            recognitions={},
        )
    try:
        return _run_route(runtime, session, ocr=ocr)
    except BaseException as exc:
        return _result(
            session,
            status=(
                "unresolved"
                if any(
                    row.get("label") == ITEM_USE_ACTION_KEY
                    or row.get("action_key") == ITEM_USE_ACTION_KEY
                    for row in getattr(session, "actions", ())
                )
                else "evidence_required"
            ),
            reason=f"{type(exc).__name__}: {exc}",
            frames={},
            recognitions={},
            item_use_calls=sum(
                1
                for row in getattr(session, "actions", ())
                if row.get("label") == ITEM_USE_ACTION_KEY
                or row.get("action_key") == ITEM_USE_ACTION_KEY
            ),
        )


__all__ = [
    "FLOW_ID",
    "ITEM_USE_ACTION_KEY",
    "MAX_RESOURCE_LIST_SWIPES",
    "MAX_ROUTE_INPUTS",
    "ResourceListSwipeBinding",
    "ResourceItemRecognition",
    "bind_resource_list_swipe",
    "recognize_resources_screen",
    "recognize_food_item",
    "recognize_food_item_in_resources",
    "resource_list_content_signature",
    "resource_list_progressed",
    "resource_item_authorizeable",
    "resource_item_postcondition_verified",
    "run_daily_resource_item",
]
