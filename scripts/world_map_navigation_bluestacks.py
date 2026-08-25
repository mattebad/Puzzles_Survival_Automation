#!/usr/bin/env python3
"""Bounded, navigation-only Home -> World -> Search -> Home route.

The route is intentionally small.  It recognizes every successor from a fresh
native frame, binds controls locally from that frame, and stops on any unknown
modal, unsupported zoom, stale binding, or transport result without semantic
proof.  World nodes are only planned/bound for later flows; this module never
selects or dispatches to a node.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import os
import re
import time
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    NATIVE_HEIGHT,
    NATIVE_RUNTIME_PROFILE_ID,
    NATIVE_WIDTH,
)
from tasks.world_stamina import (
    WORLD_ZOOM_SUPPORTED,
    WorldNavigationObservation,
    world_navigation_observation_authorizeable,
)


FLOW_ID = "WORLD-MAP-NAVIGATION-FOUNDATION"
RUNNER_ID = "world_map_navigation_foundation_runner"
VALIDATOR_ID = "world_map_navigation_foundation_evidence"
RECOVERY_ID = "world_map_navigation_foundation_recovery"
PACKAGE_ID = "com.global.ztmslg"
MAX_ROUTE_INPUTS = 20
MAX_SAFE_POPUP_INPUTS = 4
MAX_SAFE_POPUP_POST_FRAMES = 3
SAFE_POPUP_SETTLE_DELAY_SECONDS = 0.25
MAX_NAVIGATION_POST_FRAMES = 3
NAVIGATION_SETTLE_DELAY_SECONDS = 0.25
POPUP_CONTRACT_VERSION = "vip-points-get-pts-close-v1"
FULL_ROUTE_PATH = "home_ready_to_world_to_search_to_home_ready"
RECOVERY_PATH = "world_ready_to_home_recovery"
SEARCH_ENTRY_ONLY_PATH = "world_ready_to_search_entry_only"

HOME_READY = "HOME_READY"
HOME_CANONICAL = "HOME_CANONICAL"
WORLD_READY = "WORLD_READY"
WORLD_SEARCH_OPEN = "WORLD_SEARCH_OPEN"
NAVIGATION_ONLY_COMPLETE = "navigation_only_complete"
BLOCKED_FAIL_CLOSED = "blocked_fail_closed"

HOME_TO_WORLD = "home-to-world"
WORLD_SEARCH_ENTRY = "world-search-entry"
WORLD_SEARCH_CLOSE = "world-search-close"
WORLD_TO_HOME = "world-to-home"
POPUP_CLOSE = "reset-popup-close"
ANDROID_BACK = "android-back"
WORLD_PAN_PLAN = "world-camera-pan-plan"

ALLOWED_CONTROL_IDENTITIES = frozenset(
    {
        HOME_TO_WORLD,
        WORLD_SEARCH_ENTRY,
        WORLD_SEARCH_CLOSE,
        WORLD_TO_HOME,
        POPUP_CLOSE,
        ANDROID_BACK,
    }
)
FORBIDDEN_IDENTITY_MARKERS = (
    "gather",
    "resource",
    "node",
    "march",
    "combat",
    "attack",
    "stamina",
    "ap",
    "troop",
    "formation",
    "dispatch",
    "cash-mall",
    "purchase",
    "payment",
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_OCR_TEXT_RE = re.compile(r"[^a-z0-9]+")
_CONTROL_LABELS: Mapping[str, tuple[str, ...]] = {
    HOME_TO_WORLD: ("world map", "world"),
    WORLD_SEARCH_ENTRY: ("search", "find"),
    WORLD_SEARCH_CLOSE: ("close",),
    WORLD_TO_HOME: ("home", "base"),
}
_POPUP_TITLE_MARKERS = ("get pts", "get points", "getpts")
_POPUP_BODY_MARKERS = (
    "log in every day to get vip pts",
    "obtained vip pts",
    "obtained vip pt",
)
WORLD_SEARCH_ENTRY_ROI = (100, 1030, 152, 1086)
WORLD_SEARCH_ENTRY_CENTER = (126, 1058)
_SEARCH_ICON_CENTER_TOLERANCE = 8
_WORLD_COORDINATE_HUD_REGION = (240, 80, 600, 220)
_FOOTER_NAVIGATION_REGION = (0, 1160, 150, 1280)
_FOOTER_OCR_SCALE = 3.0
_FOOTER_MIN_TEXT_CANDIDATE_OVERLAP = 0.50
_FOOTER_EFFECTIVE_CANDIDATE_MIN_OVERLAP = 0.70
_FOOTER_EFFECTIVE_CANDIDATE_MIN_IOU = 0.65
_FOOTER_CONTROL_LABELS: Mapping[str, tuple[str, ...]] = {
    HOME_TO_WORLD: ("world",),
    WORLD_TO_HOME: ("home", "base"),
}
_WORLD_SEARCH_CATEGORY_MARKERS = (
    ("zombie", "zombie"),
    ("zombie lair", "zombielair"),
    ("food", "food"),
    ("wood", "wood"),
    ("steel", "steel"),
)


class WorldNavigationBlocked(RuntimeError):
    """A route decision failed closed and must not be retried identically."""


@dataclass(frozen=True)
class PopupContract:
    popup_identity: str
    title_markers: tuple[str, ...]
    body_markers: tuple[str, ...]
    close_identity: str
    close_label: str
    cost_type: str
    consequence_class: str


POPUP_CONTRACT_REGISTRY: Mapping[str, PopupContract] = {
    "VIP_POINTS_GET_PTS": PopupContract(
        popup_identity="VIP_POINTS_GET_PTS",
        title_markers=("get pts", "get points", "getpts"),
        body_markers=("log in every day to get vip pts", "obtained vip pt"),
        close_identity=POPUP_CLOSE,
        close_label="Close",
        cost_type="none",
        consequence_class="navigation_only",
    )
}


@dataclass(frozen=True)
class PopupRecognition:
    status: str
    popup_identity: str | None = None
    target_identity: str | None = None
    target_roi: tuple[int, int, int, int] | None = None
    source_frame_sha256: str = ""
    semantic_evidence: tuple[str, ...] = ()
    reason: str = ""

    @property
    def recognized(self) -> bool:
        return self.status == "allowed"


@dataclass(frozen=True)
class Checkpoint:
    frame: CapturedNativeFrame
    observation: WorldNavigationObservation
    popup_handled: bool = False


def _capture_identity(source: CapturedNativeFrame) -> tuple[str, str, str]:
    """Identify a fresh capture by session, ordinal/path, and digest."""

    return (
        str(source.path.parent.parent),
        source.path.name.split("-", 1)[0],
        source.sha256,
    )


def _capture_metadata(source: CapturedNativeFrame) -> dict[str, str]:
    session, ordinal, digest = _capture_identity(source)
    return {
        "capture_session": session,
        "capture_ordinal": ordinal,
        "capture_frame_sha256": digest,
    }

def _frame_digest(frame: np.ndarray) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def _valid_roi(value: object) -> bool:
    try:
        x0, y0, x1, y1 = tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return bool(
        all(type(item) is int for item in (x0, y0, x1, y1))
        and 0 <= x0 < x1 <= NATIVE_WIDTH
        and 0 <= y0 < y1 <= NATIVE_HEIGHT
    )


def _roi_contains(
    outer: object,
    inner: object,
) -> bool:
    if not (_valid_roi(outer) and _valid_roi(inner)):
        return False
    ox0, oy0, ox1, oy1 = tuple(outer)  # type: ignore[arg-type]
    ix0, iy0, ix1, iy1 = tuple(inner)  # type: ignore[arg-type]
    return ox0 <= ix0 < ix1 <= ox1 and oy0 <= iy0 < iy1 <= oy1


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _compact(value: object) -> str:
    return _OCR_TEXT_RE.sub("", _normalized(value))


def _ocr_hits(frame: np.ndarray) -> list[tuple[str, tuple[int, int, int, int]]]:
    if frame is None or getattr(frame, "shape", ())[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return []
    try:
        import pytesseract

        data = pytesseract.image_to_data(
            cv2.resize(frame, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC),
            config="--psm 11",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return []
    hits: list[tuple[str, tuple[int, int, int, int]]] = []
    for index, raw in enumerate(data.get("text", ())):
        text = _normalized(raw)
        if not text:
            continue
        try:
            left = int(data["left"][index] / 2)
            top = int(data["top"][index] / 2)
            width = int(data["width"][index] / 2)
            height = int(data["height"][index] / 2)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        roi = (
            max(0, left - 12),
            max(0, top - 10),
            min(NATIVE_WIDTH, left + width + 12),
            min(NATIVE_HEIGHT, top + height + 10),
        )
        if _valid_roi(roi):
            hits.append((text, roi))
    return hits


def _footer_navigation_ocr_hits(
    frame: np.ndarray,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Run fallback OCR only over the current bottom-left footer controls."""

    if frame is None or getattr(frame, "shape", ())[:2] != (
        NATIVE_HEIGHT,
        NATIVE_WIDTH,
    ):
        return []
    x0, y0, x1, y1 = _FOOTER_NAVIGATION_REGION
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    try:
        import pytesseract

        data = pytesseract.image_to_data(
            cv2.resize(
                crop,
                None,
                fx=_FOOTER_OCR_SCALE,
                fy=_FOOTER_OCR_SCALE,
                interpolation=cv2.INTER_CUBIC,
            ),
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return []
    hits: list[tuple[str, tuple[int, int, int, int]]] = []
    for index, raw in enumerate(data.get("text", ())):
        text = _normalized(raw)
        if not text:
            continue
        try:
            left = int(data["left"][index] / _FOOTER_OCR_SCALE)
            top = int(data["top"][index] / _FOOTER_OCR_SCALE)
            width = int(data["width"][index] / _FOOTER_OCR_SCALE)
            height = int(data["height"][index] / _FOOTER_OCR_SCALE)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        roi = (
            x0 + left,
            y0 + top,
            x0 + left + width,
            y0 + top + height,
        )
        if _valid_roi(roi) and _roi_contains(_FOOTER_NAVIGATION_REGION, roi):
            hits.append((text, roi))
    return hits


def _group_spatial_ocr_hits(
    hits: list[tuple[str, tuple[int, int, int, int]]],
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Group OCR words into deterministic spatial lines.

    Tesseract's data output is word-oriented for this frame.  A word is never
    treated as a phrase object: only words on the same measured line are
    combined, in x order, and the resulting ROI is the union of those words.
    """

    words = [
        (text, roi)
        for text, roi in hits
        if _normalized(text) and _valid_roi(roi)
    ]
    lines: list[list[tuple[str, tuple[int, int, int, int]]]] = []
    for text, roi in sorted(
        words,
        key=lambda item: (
            (item[1][1] + item[1][3]) / 2,
            item[1][0],
        ),
    ):
        x0, y0, x1, y1 = roi
        center_y = (y0 + y1) / 2
        height = y1 - y0
        matching: list[tuple[float, int]] = []
        for line_index, line in enumerate(lines):
            line_top = min(item[1][1] for item in line)
            line_bottom = max(item[1][3] for item in line)
            line_center = (line_top + line_bottom) / 2
            line_height = line_bottom - line_top
            tolerance = max(8.0, min(height, line_height) * 0.62)
            if abs(center_y - line_center) <= tolerance:
                matching.append((abs(center_y - line_center), line_index))
        if matching:
            lines[min(matching)[1]].append((text, roi))
        else:
            lines.append([(text, roi)])

    grouped: list[tuple[str, tuple[int, int, int, int]]] = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item[1][0])
        text = " ".join(_normalized(item[0]) for item in ordered)
        x0 = min(item[1][0] for item in ordered)
        y0 = min(item[1][1] for item in ordered)
        x1 = max(item[1][2] for item in ordered)
        y1 = max(item[1][3] for item in ordered)
        roi = (x0, y0, x1, y1)
        if text and _valid_roi(roi):
            grouped.append((text, roi))
    return grouped


def _ocr_text_in_roi(
    frame: np.ndarray,
    roi: tuple[int, int, int, int],
    *,
    psm: int,
) -> str:
    """Run grayscale OCR on one current-frame ROI."""

    if frame is None or not _valid_roi(roi):
        return ""
    x0, y0, x1, y1 = roi
    crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if crop.size == 0:
        return ""
    try:
        import pytesseract

        return pytesseract.image_to_string(
            cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC),
            config=f"--psm {psm}",
        )
    except Exception:
        return ""


def _ocr_phrase_present(text: str, marker: str) -> bool:
    """Match an exact OCR token sequence, never an individual token."""

    actual = re.findall(r"[a-z0-9]+", str(text).casefold())
    wanted = re.findall(r"[a-z0-9]+", marker.casefold())
    if not actual or not wanted or len(wanted) > len(actual):
        return False
    return any(
        actual[index : index + len(wanted)] == wanted
        for index in range(len(actual) - len(wanted) + 1)
    )


def _visual_popup_panel_candidates(
    frame: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Detect large rectangular popup panels from current-frame edges."""

    if frame is None or getattr(frame, "shape", ())[:2] != (
        NATIVE_HEIGHT,
        NATIVE_WIDTH,
    ):
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 140)
    minimum_line = max(80, int(NATIVE_WIDTH * 0.12))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(35, int(NATIVE_HEIGHT * 0.06)),
        minLineLength=minimum_line,
        maxLineGap=max(20, int(NATIVE_WIDTH * 0.04)),
    )
    if lines is None:
        return []
    horizontal: list[tuple[int, int, int]] = []
    vertical: list[tuple[int, int, int]] = []
    for raw_line in lines[:, 0]:
        x0, y0, x1, y1 = (int(value) for value in raw_line)
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        if dx >= minimum_line and dx >= dy * 5:
            horizontal.append((min(y0, y1), min(x0, x1), max(x0, x1)))
        elif dy >= minimum_line and dy >= dx * 5:
            vertical.append((min(x0, x1), min(y0, y1), max(y0, y1)))

    def cluster(
        segments: list[tuple[int, int, int]],
    ) -> list[tuple[int, int, int]]:
        clusters: list[list[tuple[int, int, int]]] = []
        for segment in sorted(segments):
            if not clusters or segment[0] - int(
                sum(item[0] for item in clusters[-1]) / len(clusters[-1])
            ) > 12:
                clusters.append([segment])
            else:
                clusters[-1].append(segment)
        return [
            (
                int(sum(item[0] for item in group) / len(group)),
                min(item[1] for item in group),
                max(item[2] for item in group),
            )
            for group in clusters
        ]

    horizontal = cluster(horizontal)
    vertical = cluster(vertical)
    panels: set[tuple[int, int, int, int]] = set()
    for top, top_x0, top_x1 in horizontal:
        for bottom, bottom_x0, bottom_x1 in horizontal:
            if bottom - top < int(NATIVE_HEIGHT * 0.20):
                continue
            if bottom - top > int(NATIVE_HEIGHT * 0.95):
                continue
            horizontal_overlap = min(top_x1, bottom_x1) - max(top_x0, bottom_x0)
            if horizontal_overlap < int(NATIVE_WIDTH * 0.40):
                continue
            for left, left_y0, left_y1 in vertical:
                for right, right_y0, right_y1 in vertical:
                    if right - left < int(NATIVE_WIDTH * 0.45):
                        continue
                    if right - left > int(NATIVE_WIDTH * 0.98):
                        continue
                    vertical_overlap = min(left_y1, right_y1) - max(left_y0, right_y0)
                    if vertical_overlap < int(NATIVE_HEIGHT * 0.30):
                        continue
                    x0 = max(0, min(top_x0, bottom_x0, left))
                    y0 = max(0, top)
                    x1 = min(NATIVE_WIDTH, max(top_x1, bottom_x1, right))
                    y1 = min(NATIVE_HEIGHT, bottom)
                    roi = (x0, y0, x1, y1)
                    if (
                        _valid_roi(roi)
                        and x1 - x0 >= int(NATIVE_WIDTH * 0.50)
                        and y1 - y0 >= int(NATIVE_HEIGHT * 0.30)
                    ):
                        panels.add(roi)
    return sorted(
        panels,
        key=lambda roi: (-(roi[2] - roi[0]) * (roi[3] - roi[1]), roi),
    )


def _visual_popup_button_candidates(
    frame: np.ndarray,
    panel: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    """Find and merge lower-panel button geometry independently of OCR."""

    if not _valid_roi(panel):
        return []
    px0, py0, px1, py1 = panel
    panel_width = px1 - px0
    panel_height = py1 - py0
    candidates = []
    for candidate in _visual_candidate_boxes(frame):
        x0, y0, x1, y1 = candidate
        width = x1 - x0
        height = y1 - y0
        if not _roi_contains(panel, candidate):
            continue
        if not (
            panel_width * 0.15 <= width <= panel_width * 0.75
            and panel_height * 0.04 <= height <= panel_height * 0.25
            and y0 >= py0 + panel_height * 0.55
        ):
            continue
        candidates.append(candidate)

    merged: list[tuple[int, int, int, int]] = []
    for candidate in sorted(candidates, key=lambda roi: (roi[1], roi[0])):
        x0, y0, x1, y1 = candidate
        for index, existing in enumerate(merged):
            ex0, ey0, ex1, ey1 = existing
            overlap_x = max(0, min(x1, ex1) - max(x0, ex0))
            gap_y = max(0, max(y0, ey0) - min(y1, ey1))
            if overlap_x >= min(x1 - x0, ex1 - ex0) * 0.60 and gap_y <= max(
                8, int(max(y1 - y0, ey1 - ey0) * 0.25)
            ):
                merged[index] = (
                    min(x0, ex0),
                    min(y0, ey0),
                    max(x1, ex1),
                    max(y1, ey1),
                )
                break
        else:
            merged.append(candidate)
    return sorted(
        merged,
        key=lambda roi: (-(roi[2] - roi[0]) * (roi[3] - roi[1]), roi),
    )


def _find_hit(
    hits: list[tuple[str, tuple[int, int, int, int]]],
    *markers: str,
) -> tuple[int, int, int, int] | None:
    wanted = tuple(_compact(marker) for marker in markers)
    for text, roi in hits:
        compact = _compact(text)
        if any(marker and (marker == compact or marker in compact) for marker in wanted):
            return roi
    return None


def _hit_for_labels(
    hits: list[tuple[str, tuple[int, int, int, int]]],
    labels: tuple[str, ...],
) -> tuple[str, tuple[int, int, int, int]] | None:
    wanted = tuple(_compact(label) for label in labels)
    for text, roi in hits:
        compact = _compact(text)
        if any(marker and marker == compact for marker in wanted):
            return text, roi
    return None


def _visual_candidate_boxes(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find control/panel geometry without using OCR text or fixed tap points."""

    if frame is None or getattr(frame, "shape", ())[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 180)
    contours, _hierarchy = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 24 or height < 18 or width > 760 or height > 1160:
            continue
        area = width * height
        if area < 700:
            continue
        boxes.append((x, y, x + width, y + height))
    return boxes


def _candidate_associated_with(
    frame: np.ndarray,
    text_roi: tuple[int, int, int, int],
    *,
    minimum_overlap: float = 0.10,
    candidates: list[tuple[int, int, int, int]] | None = None,
) -> tuple[int, int, int, int] | None:
    """Bind text to a separately detected visual candidate."""

    tx0, ty0, tx1, ty1 = text_roi
    text_area = max(1, (tx1 - tx0) * (ty1 - ty0))
    best: tuple[float, tuple[int, int, int, int]] | None = None
    for candidate in (
        _visual_candidate_boxes(frame) if candidates is None else candidates
    ):
        x0, y0, x1, y1 = candidate
        overlap = max(0, min(tx1, x1) - max(tx0, x0)) * max(
            0, min(ty1, y1) - max(ty0, y0)
        )
        ratio = overlap / text_area
        if ratio >= minimum_overlap and (best is None or ratio > best[0]):
            best = (ratio, candidate)
    return best[1] if best else None


def _control_binding(
    frame: np.ndarray,
    hits: list[tuple[str, tuple[int, int, int, int]]],
    identity: str,
    *,
    candidates: list[tuple[int, int, int, int]] | None = None,
) -> tuple[tuple[int, int, int, int], tuple[str, ...], str] | None:
    labels = _CONTROL_LABELS[identity]
    hit = _hit_for_labels(hits, labels)
    if hit is None:
        return None
    text, text_roi = hit
    candidate = _candidate_associated_with(
        frame,
        text_roi,
        candidates=candidates,
    )
    if candidate is None:
        return None
    if (
        identity in _FOOTER_CONTROL_LABELS
        and _roi_contains(_FOOTER_NAVIGATION_REGION, text_roi)
    ):
        candidate = (
            max(candidate[0], _FOOTER_NAVIGATION_REGION[0]),
            max(candidate[1], _FOOTER_NAVIGATION_REGION[1]),
            min(candidate[2], _FOOTER_NAVIGATION_REGION[2]),
            min(candidate[3], _FOOTER_NAVIGATION_REGION[3]),
        )
        if not _valid_roi(candidate):
            return None
    return candidate, (text,), "current-frame-bounded-candidate"


def _footer_control_binding(
    frame: np.ndarray,
    identity: str,
    *,
    footer_hits: list[tuple[str, tuple[int, int, int, int]]],
    candidates: list[tuple[int, int, int, int]] | None = None,
) -> tuple[tuple[int, int, int, int], tuple[str, ...], str] | None:
    """Bind one exact footer label to an independently measured candidate."""

    wanted = set(_FOOTER_CONTROL_LABELS[identity])
    matching = [
        (text, roi)
        for text, roi in footer_hits
        if _compact(text) in wanted
        and _roi_contains(_FOOTER_NAVIGATION_REGION, roi)
    ]
    observed = {
        _compact(text)
        for text, roi in footer_hits
        if _compact(text) in {"world", "home", "base"}
        and _roi_contains(_FOOTER_NAVIGATION_REGION, roi)
    }
    if (
        len(matching) != 1
        or ("world" in observed and bool(observed & {"home", "base"}))
    ):
        return None
    text, text_roi = matching[0]
    associated: list[tuple[int, int, int, int]] = []
    tx0, ty0, tx1, ty1 = text_roi
    text_area = max(1, (tx1 - tx0) * (ty1 - ty0))
    for candidate in (
        _visual_candidate_boxes(frame) if candidates is None else candidates
    ):
        if not _valid_roi(candidate):
            continue
        x0, y0, x1, y1 = candidate
        overlap = max(0, min(tx1, x1) - max(tx0, x0)) * max(
            0, min(ty1, y1) - max(ty0, y0)
        )
        if overlap / text_area >= _FOOTER_MIN_TEXT_CANDIDATE_OVERLAP:
            associated.append(candidate)

    distinct = sorted(
        set(associated),
        key=lambda candidate: (
            (candidate[2] - candidate[0]) * (candidate[3] - candidate[1]),
            candidate,
        ),
    )
    if not distinct:
        return None
    smallest_area = (
        (distinct[0][2] - distinct[0][0])
        * (distinct[0][3] - distinct[0][1])
    )
    smallest = [
        candidate
        for candidate in distinct
        if (candidate[2] - candidate[0]) * (candidate[3] - candidate[1])
        == smallest_area
    ]
    if len(smallest) != 1:
        return None
    selected = smallest[0]
    if not _roi_contains(_FOOTER_NAVIGATION_REGION, selected):
        return None
    if any(
        candidate != selected
        and not _roi_contains(candidate, selected)
        for candidate in distinct
    ):
        return None
    return selected, (text,), "current-frame-bounded-candidate"


def _footer_fallback_identity(
    footer_hits: list[tuple[str, tuple[int, int, int, int]]],
) -> str | None:
    """Select one screen-specific identity from one fallback OCR result."""

    labels = {
        _compact(text)
        for text, roi in footer_hits
        if _roi_contains(_FOOTER_NAVIGATION_REGION, roi)
        and _compact(text) in {"world", "home", "base"}
    }
    if len(labels) != 1:
        return None
    label = next(iter(labels))
    if label == "world":
        return HOME_TO_WORLD
    return WORLD_TO_HOME


def _merge_overlapping_candidates(
    candidates: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge nested contour boxes while preserving measured current-frame bounds."""

    merged: list[tuple[int, int, int, int]] = []
    for candidate in sorted(candidates, key=lambda roi: (roi[1], roi[0], roi[2], roi[3])):
        if not _valid_roi(candidate):
            continue
        x0, y0, x1, y1 = candidate
        area = max(1, (x1 - x0) * (y1 - y0))
        for index, existing in enumerate(merged):
            ex0, ey0, ex1, ey1 = existing
            overlap = max(0, min(x1, ex1) - max(x0, ex0)) * max(
                0, min(y1, ey1) - max(y0, ey0)
            )
            existing_area = max(1, (ex1 - ex0) * (ey1 - ey0))
            if overlap / min(area, existing_area) < 0.45:
                continue
            merged[index] = (
                min(x0, ex0),
                min(y0, ey0),
                max(x1, ex1),
                max(y1, ey1),
            )
            break
        else:
            merged.append(candidate)
    return sorted(merged, key=lambda roi: (roi[1], roi[0], roi[2], roi[3]))


def _magnifier_has_lens_and_handle(
    frame: np.ndarray,
    candidate: tuple[int, int, int, int],
) -> bool:
    """Require a current-frame circular lens and its lower-right handle."""

    if not _valid_roi(candidate):
        return False
    x0, y0, x1, y1 = candidate
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=12,
        param1=60,
        param2=16,
        minRadius=9,
        maxRadius=max(10, min(gray.shape) // 2),
    )
    if circles is None:
        return False
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=8,
        minLineLength=8,
        maxLineGap=4,
    )
    if lines is None:
        return False
    for raw_circle in circles[0]:
        center_x, center_y, radius = (float(value) for value in raw_circle)
        if (
            radius < 12
            or radius > min(gray.shape) * 0.45
            or center_x > (x1 - x0) * 0.40
        ):
            continue
        for raw_line in lines[:, 0]:
            first = np.array(raw_line[:2], dtype=float)
            second = np.array(raw_line[2:], dtype=float)
            first_distance = float(
                np.linalg.norm(first - np.array((center_x, center_y)))
            )
            second_distance = float(
                np.linalg.norm(second - np.array((center_x, center_y)))
            )
            near, far = (
                (first, second)
                if first_distance <= second_distance
                else (second, first)
            )
            near_distance = min(first_distance, second_distance)
            far_distance = max(first_distance, second_distance)
            dx = float(far[0] - near[0])
            dy = float(far[1] - near[1])
            angle = math.degrees(math.atan2(dy, dx)) if dx > 0 else -180.0
            if not (
                near_distance <= radius * 1.35
                and far_distance >= radius * 1.45
                and dx >= radius * 0.45
                and dy >= radius * 0.30
                and 20.0 <= angle <= 70.0
                and far[0] >= center_x + radius * 0.45
                and far[1] >= center_y + radius * 0.35
            ):
                continue
            return True
    return False


def _visual_search_entry_binding(
    frame: np.ndarray,
    *,
    candidates: list[tuple[int, int, int, int]] | None = None,
) -> tuple[tuple[int, int, int, int], tuple[str, ...], str] | None:
    """Confirm one magnifier in the fixed native Search HUD slot.

    The fixed ROI is the only dispatch geometry.  ``candidates`` is accepted
    for compatibility with older callers but is intentionally ignored: neither
    contours, toolbar boxes, nor OCR may move or authorize this target.
    """

    del candidates
    rx0, ry0, rx1, ry1 = WORLD_SEARCH_ENTRY_ROI
    if frame is None or getattr(frame, "shape", ())[:2] != (
        NATIVE_HEIGHT,
        NATIVE_WIDTH,
    ):
        return None
    crop = frame[ry0:ry1, rx0:rx1]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        cv2.medianBlur(gray, 5),
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=12,
        param1=60,
        param2=14,
        minRadius=10,
        maxRadius=22,
    )
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=8,
        minLineLength=8,
        maxLineGap=4,
    )
    if circles is None or lines is None:
        return None

    expected_x = WORLD_SEARCH_ENTRY_CENTER[0] - rx0
    expected_y = WORLD_SEARCH_ENTRY_CENTER[1] - ry0
    grid_y, grid_x = np.ogrid[: gray.shape[0], : gray.shape[1]]
    matches: list[tuple[float, float, float]] = []
    for raw_circle in circles[0]:
        center_x, center_y, radius = (float(value) for value in raw_circle)
        if not (
            10 <= radius <= 22
            and abs(center_x - expected_x) <= _SEARCH_ICON_CENTER_TOLERANCE
            and abs(center_y - expected_y) <= _SEARCH_ICON_CENTER_TOLERANCE
            and center_x - radius >= 0
            and center_x + radius <= gray.shape[1]
            and center_y - radius >= 0
            and center_y + radius <= gray.shape[0]
        ):
            continue
        distance = np.sqrt(
            (grid_x - center_x) ** 2 + (grid_y - center_y) ** 2
        )
        ring = gray[(distance >= radius - 2) & (distance <= radius + 2)]
        inside = gray[distance <= radius * 0.55]
        if (
            not len(ring)
            or not len(inside)
            or float(ring.mean() - inside.mean()) < 30
            or float(inside.std()) > 30
        ):
            continue

        handle_found = False
        for raw_line in lines[:, 0]:
            first = np.array(raw_line[:2], dtype=float)
            second = np.array(raw_line[2:], dtype=float)
            first_distance = float(
                np.linalg.norm(first - np.array((center_x, center_y)))
            )
            second_distance = float(
                np.linalg.norm(second - np.array((center_x, center_y)))
            )
            near, far = (
                (first, second)
                if first_distance <= second_distance
                else (second, first)
            )
            near_distance = min(first_distance, second_distance)
            far_distance = max(first_distance, second_distance)
            dx = float(far[0] - near[0])
            dy = float(far[1] - near[1])
            angle = math.degrees(math.atan2(dy, dx)) if dx > 0 else -180.0
            if not (
                near_distance <= radius * 1.70
                and far_distance >= radius * 1.35
                and dx >= radius * 0.45
                and dy >= radius * 0.30
                and 20.0 <= angle <= 70.0
                and far[0] >= center_x + radius * 0.45
                and far[1] >= center_y + radius * 0.35
            ):
                continue
            handle_found = True
            break
        if handle_found:
            matches.append((center_x, center_y, radius))

    distinct_matches: list[tuple[float, float, float]] = []
    for match in matches:
        if not any(
            math.hypot(match[0] - other[0], match[1] - other[1]) <= 6
            and abs(match[2] - other[2]) <= 4
            for other in distinct_matches
        ):
            distinct_matches.append(match)
    if len(distinct_matches) != 1:
        return None
    return (
        WORLD_SEARCH_ENTRY_ROI,
        (
            "Search",
            "magnifying-glass lens",
            "magnifying-glass handle",
            "fixed native Search HUD slot",
            "current-frame visual structure",
        ),
        "current-frame-bounded-candidate",
    )


def _coordinate_hud_evidence(
    frame: np.ndarray,
    hits: list[tuple[str, tuple[int, int, int, int]]],
) -> tuple[str, ...]:
    """Recognize only the spatially bounded top coordinate HUD."""

    hx0, hy0, hx1, hy1 = _WORLD_COORDINATE_HUD_REGION
    bounded = [
        (_compact(text), roi)
        for text, roi in hits
        if _valid_roi(roi)
        and hx0 <= roi[0] < roi[2] <= hx1
        and hy0 <= roi[1] < roi[3] <= hy1
    ]
    if not bounded:
        return ()
    direct_x = any(re.fullmatch(r"x\d{2,4}", text) for text, _roi in bounded)
    direct_y = any(re.fullmatch(r"y\d{2,4}", text) for text, _roi in bounded)
    if direct_x and direct_y:
        return ("spatially-bounded-top-coordinate-hud",)
    x_marker = any(
        text in {"x", "xk"} or text.startswith("x")
        for text, _roi in bounded
    )
    numeric = [
        roi
        for text, roi in bounded
        if re.fullmatch(r"\d{2,4}", text)
        and roi[1] >= hy0 + 10
    ]
    direct_x_rois = [
        roi
        for text, roi in bounded
        if re.fullmatch(r"x\d{2,4}", text)
    ]
    y_value_rois = [
        roi
        for text, roi in bounded
        if re.fullmatch(r"\d{3,4}", text)
    ]
    for x_roi in direct_x_rois:
        x0, y0, x1, y1 = x_roi
        x_center = (x0 + x1) / 2
        x_y_center = (y0 + y1) / 2
        for y_roi in y_value_rois:
            yx0, yy0, yx1, yy1 = y_roi
            y_center = (yx0 + yx1) / 2
            y_y_center = (yy0 + yy1) / 2
            if (
                yx1 < x0
                or yx0 > x1 + 24
                or y_center < x_center - 12
                or abs(y_y_center - x_y_center) > 32
            ):
                continue
            return ("spatially-bounded-top-coordinate-hud",)
    if not x_marker or len(numeric) < 2:
        x_rois = [
            roi
            for text, roi in bounded
            if text in {"x", "xk"}
        ]
        y_rois = [
            roi
            for text, roi in bounded
            if re.fullmatch(r"y\d{2,4}", text)
        ]
        if x_rois and y_rois and any(
            y_roi[0] >= x_roi[0]
            and abs(
                (y_roi[1] + y_roi[3]) / 2
                - (x_roi[1] + x_roi[3]) / 2
            )
            <= 32
            for x_roi in x_rois
            for y_roi in y_rois
        ):
            return ("spatially-bounded-top-coordinate-hud",)
        return ()
    numeric = sorted(numeric, key=lambda roi: roi[0])
    first_center = (numeric[0][0] + numeric[0][2]) / 2
    second_center = (numeric[1][0] + numeric[1][2]) / 2
    if not (
        30 <= second_center - first_center <= 240
        and abs(
            (numeric[0][1] + numeric[0][3]) / 2
            - (numeric[1][1] + numeric[1][3]) / 2
        )
        <= 80
    ):
        return ()
    return ("spatially-bounded-top-coordinate-hud",)


def _world_search_menu_evidence(
    hits: list[tuple[str, tuple[int, int, int, int]]],
) -> tuple[str, ...]:
    """Recognize visible Search categories without binding any category control."""

    category_hits: set[str] = set()
    category_rois: set[tuple[int, int, int, int]] = set()
    markers = sorted(
        _WORLD_SEARCH_CATEGORY_MARKERS,
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for text, roi in hits:
        if not _valid_roi(roi) or roi[1] < 180:
            continue
        compact = _compact(text)
        match = next(
            (
                (label, marker)
                for label, marker in markers
                if compact == marker
            ),
            None,
        )
        if match is not None:
            category_hits.add(match[0])
            category_rois.add(roi)
    if "zombie" not in category_hits and "zombie lair" not in category_hits:
        return ()
    if len(category_hits) < 2:
        return ()
    if not any(
        abs(
            (first[0] + first[2]) / 2
            - (second[0] + second[2]) / 2
        )
        <= 360
        and abs(
            (first[1] + first[3]) / 2
            - (second[1] + second[3]) / 2
        )
        <= 180
        for index, first in enumerate(sorted(category_rois))
        for second in sorted(category_rois)[index + 1 :]
    ):
        return ()
    return (
        "visible Search category semantics",
        *(f"Search category: {label}" for label in sorted(category_hits)),
    )


def recognize_allowlisted_popup(
    frame: np.ndarray,
    *,
    source_frame_sha256: str = "",
) -> PopupRecognition:
    """Recognize only the explicit VIP Points/Get Pts/Close popup contract.

    A partially matching panel is ``unknown`` rather than ``absent`` so a
    lookalike cannot fall through to a generic close/back action.
    """

    if frame is None or getattr(frame, "shape", ())[:2] != (
        NATIVE_HEIGHT,
        NATIVE_WIDTH,
    ):
        return PopupRecognition(
            "unknown",
            source_frame_sha256=source_frame_sha256,
            reason="profile_dimensions_mismatch",
        )
    if _HASH_RE.fullmatch(str(source_frame_sha256)) is None:
        return PopupRecognition(
            "unknown",
            source_frame_sha256=source_frame_sha256,
            reason="current_frame_hash_missing_or_invalid",
        )

    hits = _ocr_hits(frame)
    grouped_hits = _group_spatial_ocr_hits(hits)
    global_title = _find_hit(grouped_hits, *_POPUP_TITLE_MARKERS)
    global_body = _find_hit(grouped_hits, *_POPUP_BODY_MARKERS)
    global_close = _hit_for_labels(grouped_hits, ("close",))
    panel_boxes = _visual_popup_panel_candidates(frame)
    semantic_partial = any(
        evidence is not None for evidence in (global_title, global_body, global_close)
    )
    for panel in panel_boxes:
        panel_text = _ocr_text_in_roi(frame, panel, psm=11)
        title_marker = next(
            (
                marker
                for marker in _POPUP_TITLE_MARKERS
                if _ocr_phrase_present(panel_text, marker)
            ),
            None,
        )
        body_marker = next(
            (
                marker
                for marker in _POPUP_BODY_MARKERS
                if _ocr_phrase_present(panel_text, marker)
            ),
            None,
        )
        if title_marker is None and body_marker is None:
            continue
        semantic_partial = True
        if title_marker is None or body_marker is None:
            continue
        for button in _visual_popup_button_candidates(frame, panel):
            x0, y0, x1, y1 = button
            width = x1 - x0
            height = y1 - y0
            pad_x = max(4, int(width * 0.08))
            pad_y = max(8, int(height * 0.20))
            control_roi = (
                max(panel[0], x0 - pad_x),
                max(panel[1], y0 - pad_y),
                min(panel[2], x1 + pad_x),
                min(panel[3], y1 + pad_y),
            )
            if not _roi_contains(panel, button) or not _valid_roi(control_roi):
                continue
            close_text = _ocr_text_in_roi(frame, control_roi, psm=7)
            if not _ocr_phrase_present(close_text, "close"):
                continue
            contract = POPUP_CONTRACT_REGISTRY["VIP_POINTS_GET_PTS"]
            return PopupRecognition(
                "allowed",
                popup_identity=contract.popup_identity,
                target_identity=contract.close_identity,
                target_roi=button,
                source_frame_sha256=source_frame_sha256,
                semantic_evidence=(
                    "Get Pts",
                    "Log in every day to get VIP pts",
                    "Close",
                    "spatially_associated_close_control",
                    "independently_bounded_popup_panel",
                ),
            )

    if not semantic_partial:
        return PopupRecognition(
            "absent",
            source_frame_sha256=source_frame_sha256,
            reason="allowlisted_popup_absent",
        )
    return PopupRecognition(
        "unknown",
        source_frame_sha256=source_frame_sha256,
        reason="popup_semantics_incomplete",
    )


def recognize_world_frame(
    frame: np.ndarray,
    *,
    source_frame_sha256: str = "",
    evidence_ref: str = "",
) -> WorldNavigationObservation:
    """Recognize only explicit controls with independent current-frame geometry."""

    if frame is None or getattr(frame, "shape", ())[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return WorldNavigationObservation(
            state="UNKNOWN",
            source_frame_sha256=source_frame_sha256,
            evidence_ref=evidence_ref or "invalid-native-frame",
            recognized=False,
            overlay_state="unknown",
            zoom_identity="WORLD_ZOOM_UNKNOWN",
        )
    hits = _ocr_hits(frame)
    visual_candidates = _visual_candidate_boxes(frame)
    words = " ".join(text for text, _roi in hits)
    compact = _compact(words)
    unknown_modal = any(
        marker in compact
        for marker in (
            "captcha",
            "login",
            "tutorial",
            "accountselection",
            "switchaccount",
            "payment",
            "checkout",
            "serverselection",
        )
    )
    controls: dict[str, tuple[int, int, int, int]] = {}
    control_semantics: dict[str, tuple[str, ...]] = {}
    control_geometry_source: dict[str, str] = {}
    footer_fallback_identities: set[str] = set()
    footer_hits: list[tuple[str, tuple[int, int, int, int]]] | None = None
    for identity in (
        HOME_TO_WORLD,
        WORLD_SEARCH_CLOSE,
        WORLD_TO_HOME,
    ):
        binding = _control_binding(
            frame,
            hits,
            identity,
            candidates=visual_candidates,
        )
        if binding is not None:
            roi, semantics, geometry_source = binding
            controls[identity] = roi
            control_semantics[identity] = semantics
            control_geometry_source[identity] = geometry_source
    if not (
        HOME_TO_WORLD in controls
        or WORLD_TO_HOME in controls
    ):
        footer_hits = _footer_navigation_ocr_hits(frame)
        fallback_identity = _footer_fallback_identity(footer_hits)
        if fallback_identity is not None:
            binding = _footer_control_binding(
                frame,
                fallback_identity,
                footer_hits=footer_hits,
                candidates=visual_candidates,
            )
            if binding is not None:
                roi, semantics, geometry_source = binding
                controls[fallback_identity] = roi
                control_semantics[fallback_identity] = semantics
                control_geometry_source[fallback_identity] = geometry_source
                footer_fallback_identities.add(fallback_identity)
    search_binding = _visual_search_entry_binding(
        frame,
        candidates=visual_candidates,
    )
    if search_binding is not None:
        roi, semantics, geometry_source = search_binding
        controls[WORLD_SEARCH_ENTRY] = roi
        control_semantics[WORLD_SEARCH_ENTRY] = semantics
        control_geometry_source[WORLD_SEARCH_ENTRY] = geometry_source
    # A confirmed magnifier in the fixed native Search HUD slot is sufficient
    # for World/Search-entry recognition.  Coordinate OCR is intentionally not
    # consulted and grants no zoom or localization authority.
    coordinate_evidence: tuple[str, ...] = ()
    menu_evidence = _world_search_menu_evidence(hits)
    has_home = HOME_TO_WORLD in controls
    has_world_context = WORLD_TO_HOME in controls
    has_world = WORLD_SEARCH_ENTRY in controls
    has_search_panel = bool(menu_evidence)
    has_canonical_home = has_home and any(
        marker in compact for marker in ("canonical home", "home base", "command center")
    )
    if unknown_modal:
        state = "UNKNOWN"
    elif has_canonical_home:
        state = HOME_CANONICAL
    elif has_home:
        state = HOME_READY
    elif has_search_panel:
        state = WORLD_SEARCH_OPEN
    elif has_world:
        state = WORLD_READY
    else:
        state = "UNKNOWN"
    zoom = "WORLD_ZOOM_UNKNOWN" if state in {WORLD_READY, WORLD_SEARCH_OPEN} else "HOME"
    footer_evidence = tuple(
        text
        for identity in footer_fallback_identities
        for text in control_semantics.get(identity, ())
        if any(_compact(text) == label for label in _FOOTER_CONTROL_LABELS[identity])
    )
    evidence = (
        tuple(text for text, _roi in hits)
        + footer_evidence
        + coordinate_evidence
        + menu_evidence
    )
    if search_binding is not None:
        evidence += (
            "magnifying-glass lens",
            "magnifying-glass handle",
            "fixed native Search HUD slot",
            "current-frame Search visual structure",
        )
    return WorldNavigationObservation(
        state=state,
        source_frame_sha256=source_frame_sha256 or _frame_digest(frame),
        evidence_ref=evidence_ref or "current-native-frame",
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        frame_width=NATIVE_WIDTH,
        frame_height=NATIVE_HEIGHT,
        recognized=state != "UNKNOWN",
        overlay_state="unknown" if unknown_modal else "none_observed",
        unknown_modal=unknown_modal,
        zoom_identity=zoom,
        controls=controls,
        control_semantics=control_semantics,
        control_geometry_source=control_geometry_source,
        semantic_evidence=evidence,
        zoom_evidence=(),
        localization_evidence=(),
    )


def recognize_world_home_recovery(
    frame: np.ndarray,
    *,
    source_frame_sha256: str = "",
    evidence_ref: str = "",
) -> WorldNavigationObservation:
    """Bind only the World HUD Home control without granting atlas authority."""

    observation = recognize_world_frame(
        frame,
        source_frame_sha256=source_frame_sha256,
        evidence_ref=evidence_ref,
    )
    if observation.state == WORLD_READY:
        return observation
    coordinate_hud = any(
        re.fullmatch(r"x\d+", _compact(text)) is not None
        and 0 <= roi[1] < roi[3] <= 220
        for text, roi in _ocr_hits(frame)
    )
    if (
        observation.state == "UNKNOWN"
        and not observation.unknown_modal
        and observation.overlay_state in {"none", "none_observed", ""}
        and coordinate_hud
        and _valid_roi(observation.control_roi(WORLD_TO_HOME))
    ):
        return replace(
            observation,
            state=WORLD_READY,
            recognized=True,
            semantic_evidence=(
                *observation.semantic_evidence,
                "spatially_bound_world_coordinate_hud",
                "current-frame Home control",
            ),
        )
    return observation


def _coerce_observation(
    value: Any,
    captured: CapturedNativeFrame,
) -> WorldNavigationObservation:
    if isinstance(value, WorldNavigationObservation):
        return replace(
            value,
            source_frame_sha256=value.source_frame_sha256 or captured.sha256,
            evidence_ref=value.evidence_ref or str(captured.path),
        )
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.setdefault("source_frame_sha256", captured.sha256)
        payload.setdefault("evidence_ref", str(captured.path))
        from tasks.world_stamina import world_navigation_observation_from_mapping

        return world_navigation_observation_from_mapping(payload)
    raise WorldNavigationBlocked("recognizer returned no current-frame observation")


def _hud_contract_state(state: str) -> str:
    """Report the HUD route's Home expectation without granting atlas authority."""

    return HOME_READY if state == HOME_CANONICAL else state


def _contradictory_zoom_claim(observation: WorldNavigationObservation) -> bool:
    """Reject explicit unsupported-zoom evidence without requiring zoom authority."""

    return bool(
        observation.state in {WORLD_READY, WORLD_SEARCH_OPEN}
        and observation.zoom_identity != WORLD_ZOOM_SUPPORTED
        and (observation.zoom_evidence or observation.localization_evidence)
    )


def _recognize(
    recognizer: Callable[..., Any],
    captured: CapturedNativeFrame,
) -> WorldNavigationObservation:
    try:
        value = recognizer(
            captured.frame,
            source_frame_sha256=captured.sha256,
            evidence_ref=str(captured.path),
        )
    except TypeError:
        value = recognizer(captured.frame)
    return _coerce_observation(value, captured)


def _record(runtime: Any, route_events: list[dict[str, Any]], event: dict[str, Any]) -> None:
    route_events.append(dict(event))
    writer = getattr(runtime, "_event", None)
    if callable(writer):
        writer("semantic", dict(event))


class SafePopupHandler:
    """Reusable allowlisted popup checkpoint handler."""

    def __init__(self, *, maximum_inputs: int = MAX_SAFE_POPUP_INPUTS) -> None:
        if type(maximum_inputs) is not int or not 0 <= maximum_inputs <= MAX_ROUTE_INPUTS:
            raise ValueError("safe popup maximum_inputs is outside the bounded route range")
        self.maximum_inputs = maximum_inputs
        self.input_count = 0
        self._handled_captures: set[tuple[str, str, str]] = set()
        self._ambiguous_captures: set[tuple[str, str, str]] = set()

    @property
    def handled_source_frames(self) -> frozenset[str]:
        return frozenset(identity[2] for identity in self._handled_captures)

    def recognize(
        self,
        frame: np.ndarray,
        *,
        source_frame_sha256: str = "",
    ) -> PopupRecognition:
        if isinstance(frame, Mapping):
            payload = frame
            popup = payload.get("popup")
            if popup in (None, {}, False):
                return PopupRecognition(
                    "absent",
                    source_frame_sha256=source_frame_sha256,
                    reason="allowlisted_popup_absent",
                )
            if not isinstance(popup, Mapping):
                return PopupRecognition(
                    "unknown",
                    source_frame_sha256=source_frame_sha256,
                    reason="popup_payload_malformed",
                )
            identity = str(popup.get("popup_identity") or "")
            contract = POPUP_CONTRACT_REGISTRY.get(identity)
            target = popup.get("target_roi")
            panel = popup.get("panel_roi")
            popup_evidence = popup.get("semantic_evidence") or ()
            if isinstance(popup_evidence, str):
                popup_evidence = (popup_evidence,)
            if contract is None:
                return PopupRecognition(
                    "unknown",
                    source_frame_sha256=source_frame_sha256,
                    reason="unknown_popup_identity",
                )
            if (
                popup.get("title_identity") is not True
                or popup.get("body_identity") is not True
                or popup.get("close_identity") != contract.close_identity
                or popup.get("literal_close") is not True
                or not _valid_roi(target)
                or not _valid_roi(panel)
                or not _roi_contains(panel, target)
                or popup.get("target_geometry_source")
                != "current-frame-bounded-candidate"
                or not popup_evidence
                or not all(
                    any(marker.casefold() in str(item).casefold() for item in popup_evidence)
                    for marker in ("Get Pts", "VIP pts", "Close")
                )
            ):
                return PopupRecognition(
                    "unknown",
                    popup_identity=identity,
                    source_frame_sha256=source_frame_sha256,
                    reason="popup_semantics_not_spatially_associated",
                )
            return PopupRecognition(
                "allowed",
                popup_identity=identity,
                target_identity=contract.close_identity,
                target_roi=tuple(target),
                source_frame_sha256=source_frame_sha256,
                semantic_evidence=(
                    *(str(item) for item in popup_evidence),
                    "spatially_associated_close_control",
                ),
            )
        return recognize_allowlisted_popup(
            frame,
            source_frame_sha256=source_frame_sha256,
        )

    def handle(
        self,
        runtime: Any,
        source: CapturedNativeFrame,
        *,
        expected_state: str,
        recognizer: Callable[..., Any],
        route_input_count: int,
        route_input_limit: int,
        route_events: list[dict[str, Any]],
    ) -> Checkpoint | None:
        popup = self.recognize(
            source.frame,
            source_frame_sha256=source.sha256,
        )
        if popup.status == "absent":
            return None
        if popup.status != "allowed":
            raise WorldNavigationBlocked(f"unknown_popup:{popup.reason}")
        capture_identity = _capture_identity(source)
        if capture_identity in self._handled_captures:
            raise WorldNavigationBlocked(
                "same_capture_popup_close_repeated:same_frame"
            )
        if capture_identity in self._ambiguous_captures:
            raise WorldNavigationBlocked("ambiguous_capture_popup_close_repeated")
        if isinstance(source.frame, Mapping):
            popup_payload = source.frame.get("popup")
            popup_context = (
                popup_payload.get("context_state")
                if isinstance(popup_payload, Mapping)
                else expected_state
            )
            if (
                source.frame.get("state") != expected_state
                or popup_context != expected_state
            ):
                raise WorldNavigationBlocked("popup_context_not_current_checkpoint")
        if self.input_count >= self.maximum_inputs:
            raise WorldNavigationBlocked("safe_popup_input_budget_exhausted")
        if route_input_count + self.input_count >= route_input_limit:
            raise WorldNavigationBlocked("route_input_budget_exhausted_before_popup")
        if popup.target_identity != POPUP_CLOSE or not _valid_roi(popup.target_roi):
            raise WorldNavigationBlocked("popup_close_target_not_allowlisted")
        self._handled_captures.add(capture_identity)
        self.input_count += 1
        action_key = (
            f"safe-popup-close:{capture_identity[1]}:{source.sha256[:24]}"
        )
        _record(
            runtime,
            route_events,
            {
                "event": "safe_popup_planned",
                "action_key": action_key,
                "popup_identity": popup.popup_identity,
                "target_identity": popup.target_identity,
                "source_frame_sha256": source.sha256,
                "target_roi": popup.target_roi,
                "expected_successor_state": expected_state,
                **_capture_metadata(source),
            },
        )
        _record(
            runtime,
            route_events,
            {
                "event": "safe_popup_prepared",
                "popup_identity": popup.popup_identity,
                "target_identity": popup.target_identity,
                "source_frame_sha256": source.sha256,
                "target_roi": popup.target_roi,
                "expected_successor_state": expected_state,
                "popup_contract_version": POPUP_CONTRACT_VERSION,
                "popup_semantic_evidence": popup.semantic_evidence,
                "target_geometry_source": "current-frame-bounded-candidate",
                "popup_context_state": expected_state,
                **_capture_metadata(source),
            },
        )
        try:
            runtime.tap(
                source,
                target_identity=POPUP_CLOSE,
                target_roi=popup.target_roi,
                action_key=action_key,
                consequential=False,
            )
        except Exception as exc:
            self._ambiguous_captures.add(capture_identity)
            raise WorldNavigationBlocked(
                f"safe_popup_transport_ambiguous:{type(exc).__name__}"
            ) from exc
        immediate_post = runtime.capture("safe-popup-close-immediate-post")
        post = immediate_post
        post_popup = self.recognize(post.frame, source_frame_sha256=post.sha256)
        post_observation_count = 1
        _record(
            runtime,
            route_events,
            {
                "event": "safe_popup_post_observed",
                "action_key": action_key,
                "post_phase": "immediate",
                "popup_status": post_popup.status,
                "post_frame_sha256": post.sha256,
                **_capture_metadata(post),
            },
        )
        while (
            post_popup.status == "allowed"
            and post_observation_count < MAX_SAFE_POPUP_POST_FRAMES
        ):
            if SAFE_POPUP_SETTLE_DELAY_SECONDS > 0:
                time.sleep(SAFE_POPUP_SETTLE_DELAY_SECONDS)
            post = runtime.capture(
                f"safe-popup-close-settle-{post_observation_count:02d}"
            )
            post_observation_count += 1
            post_popup = self.recognize(post.frame, source_frame_sha256=post.sha256)
            _record(
                runtime,
                route_events,
                {
                    "event": "safe_popup_post_observed",
                    "action_key": action_key,
                    "post_phase": "settle",
                    "post_observation_number": post_observation_count,
                    "popup_status": post_popup.status,
                    "post_frame_sha256": post.sha256,
                    **_capture_metadata(post),
                },
            )
        if post_popup.status == "unknown":
            raise WorldNavigationBlocked("popup_successor_unknown_or_lookalike")
        if post_popup.status != "absent":
            raise WorldNavigationBlocked("popup_transport_without_verified_dismissal")
        observation = _recognize(recognizer, post)
        accepted_state = observation.state == expected_state
        if observation.source_frame_sha256 != post.sha256:
            raise WorldNavigationBlocked("popup_successor_stale_or_cross_frame")
        if not accepted_state or not world_navigation_observation_authorizeable(
            observation,
            expected_state=expected_state,
            require_supported_zoom=False,
        ):
            raise WorldNavigationBlocked("popup_successor_not_recognized")
        if _contradictory_zoom_claim(observation):
            raise WorldNavigationBlocked("world_zoom_unsupported_or_ambiguous")
        reconcile = getattr(runtime, "reconcile", None)
        if callable(reconcile):
            reconcile(action_key, "confirmed", post, "allowlisted_popup_absent_and_successor_recognized")
        _record(
            runtime,
            route_events,
            {
                "event": "safe_popup_reconciled",
                "popup_identity": popup.popup_identity,
                "action_key": action_key,
                "source_frame_sha256": source.sha256,
                "immediate_post_frame_sha256": immediate_post.sha256,
                "post_frame_sha256": post.sha256,
                "popup_absent_verified": True,
                "successor_state": observation.state,
                "post_observation_count": post_observation_count,
                "popup_contract_version": POPUP_CONTRACT_VERSION,
                "popup_semantic_evidence": popup.semantic_evidence,
                **_capture_metadata(post),
            },
        )
        return Checkpoint(post, observation, popup_handled=True)


class WorldMapNavigationController:
    """Closed-loop navigation controller with no node/action policy."""

    def __init__(
        self,
        runtime: Any,
        *,
        recognizer: Callable[..., Any] | None = None,
        maximum_inputs: int = MAX_ROUTE_INPUTS,
        maximum_popup_inputs: int = MAX_SAFE_POPUP_INPUTS,
        popup_handler: SafePopupHandler | None = None,
    ) -> None:
        if type(maximum_inputs) is not int or not 1 <= maximum_inputs <= MAX_ROUTE_INPUTS:
            raise ValueError("maximum_inputs must be between 1 and 20")
        self.runtime = runtime
        self.recognizer = recognizer or recognize_world_frame
        self.maximum_inputs = maximum_inputs
        self.navigation_input_count = 0
        self.route_events: list[dict[str, Any]] = []
        self.popup_handler = popup_handler or SafePopupHandler(
            maximum_inputs=maximum_popup_inputs
        )
        self.started = time.monotonic()

    @property
    def safe_popup_input_count(self) -> int:
        return self.popup_handler.input_count

    @property
    def total_input_count(self) -> int:
        return self.navigation_input_count + self.safe_popup_input_count

    def _checkpoint(self, source: CapturedNativeFrame, expected_state: str) -> Checkpoint:
        observation = _recognize(self.recognizer, source)
        if observation.source_frame_sha256 != source.sha256:
            raise WorldNavigationBlocked("stale_or_cross_frame_observation")
        accepted_state = (
            observation.state == expected_state
            or expected_state == HOME_READY
            and observation.state == HOME_CANONICAL
        )
        if accepted_state and world_navigation_observation_authorizeable(
            observation,
            expected_state=(
                HOME_CANONICAL if observation.state == HOME_CANONICAL else expected_state
            ),
            require_supported_zoom=False,
        ):
            if _contradictory_zoom_claim(observation):
                raise WorldNavigationBlocked("world_zoom_unsupported_or_ambiguous")
            return Checkpoint(source, observation)

        # Normal route frames already expose the exact allowlisted HUD control,
        # so do not spend a second full-frame OCR pass looking for a reset popup.
        # An obscuring popup makes normal state recognition fail closed; only
        # then run the slower explicit popup recognizer.
        if observation.state == "UNKNOWN":
            handled = self.popup_handler.handle(
                self.runtime,
                source,
                expected_state=expected_state,
                recognizer=self.recognizer,
                route_input_count=self.navigation_input_count,
                route_input_limit=self.maximum_inputs,
                route_events=self.route_events,
            )
            if handled is not None:
                return handled
            raise WorldNavigationBlocked("unknown_state_or_modal")
        if not accepted_state:
            raise WorldNavigationBlocked(
                f"unexpected_successor:{observation.state}:{expected_state}"
            )
        raise WorldNavigationBlocked("current_frame_state_not_authorizeable")

    def _fresh_checkpoint(self, expected_state: str, label: str) -> Checkpoint:
        source = self.runtime.capture(label)
        checkpoint = self._checkpoint(source, expected_state)
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "state_recognized",
                "state": checkpoint.observation.state,
                "frame_sha256": checkpoint.frame.sha256,
                "checkpoint": label,
                **_capture_metadata(checkpoint.frame),
            },
        )
        return checkpoint

    def _settle_successor(
        self,
        immediate_post: CapturedNativeFrame,
        expected_state: str,
        label: str,
    ) -> Checkpoint:
        post = immediate_post
        for observation_index in range(MAX_NAVIGATION_POST_FRAMES):
            try:
                return self._checkpoint(post, expected_state)
            except WorldNavigationBlocked as exc:
                reason = str(exc)
                retryable_observation = reason == "unknown_state_or_modal" or reason.startswith(
                    "unexpected_successor:"
                )
                if (
                    not retryable_observation
                    or observation_index + 1 >= MAX_NAVIGATION_POST_FRAMES
                ):
                    raise
                if NAVIGATION_SETTLE_DELAY_SECONDS > 0:
                    time.sleep(NAVIGATION_SETTLE_DELAY_SECONDS)
                post = self.runtime.capture(
                    f"{label}-settle-{observation_index + 1:02d}"
                )
        raise WorldNavigationBlocked("navigation_successor_settle_exhausted")

    def _tap(
        self,
        checkpoint: Checkpoint,
        *,
        target_identity: str,
        successor_state: str,
        label: str,
    ) -> Checkpoint:
        if target_identity not in ALLOWED_CONTROL_IDENTITIES:
            raise WorldNavigationBlocked("target_identity_not_allowlisted")
        if any(marker in target_identity.casefold() for marker in FORBIDDEN_IDENTITY_MARKERS):
            raise WorldNavigationBlocked("forbidden_resource_or_combat_identity")
        if (
            checkpoint.observation.state in {HOME_READY, HOME_CANONICAL}
            and target_identity != HOME_TO_WORLD
        ):
            raise WorldNavigationBlocked("home_ready_target_not_home_to_world")
        roi = checkpoint.observation.control_roi(target_identity)
        if not _valid_roi(roi):
            raise WorldNavigationBlocked("missing_current_frame_target_roi")
        if checkpoint.observation.source_frame_sha256 != checkpoint.frame.sha256:
            raise WorldNavigationBlocked("stale_or_cross_frame_roi")
        if not world_navigation_observation_authorizeable(
            checkpoint.observation,
            expected_state=checkpoint.observation.state,
            required_target_identity=target_identity,
            require_supported_zoom=False,
        ):
            raise WorldNavigationBlocked("control_semantics_not_current_frame_bound")
        if self.total_input_count >= self.maximum_inputs:
            raise WorldNavigationBlocked("route_input_budget_exhausted")
        action_key = f"world-navigation:{label}:{checkpoint.frame.sha256[:24]}"
        self.navigation_input_count += 1
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_planned",
                "action_key": action_key,
                "target_identity": target_identity,
                "source_state": _hud_contract_state(checkpoint.observation.state),
                "source_frame_sha256": checkpoint.frame.sha256,
                "target_roi": roi,
                "expected_successor_state": successor_state,
                **_capture_metadata(checkpoint.frame),
            },
        )
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_prepared",
                "action_key": action_key,
                "target_identity": target_identity,
                "source_state": _hud_contract_state(checkpoint.observation.state),
                "source_frame_sha256": checkpoint.frame.sha256,
                "target_roi": roi,
                "expected_successor_state": successor_state,
                **_capture_metadata(checkpoint.frame),
            },
        )
        try:
            self.runtime.tap(
                checkpoint.frame,
                target_identity=target_identity,
                target_roi=roi,
                action_key=action_key,
                consequential=False,
            )
        except Exception as exc:
            raise WorldNavigationBlocked(
                f"navigation_transport_ambiguous:{target_identity}:{type(exc).__name__}"
            ) from exc
        immediate_post = self.runtime.capture(f"{label}-immediate-post")
        # A popup may appear over a valid successor.  Handle it at this exact
        # fresh frame before declaring the route transition reconciled.
        settled = self._settle_successor(immediate_post, successor_state, label)
        reconcile = getattr(self.runtime, "reconcile", None)
        if callable(reconcile):
            reconcile(action_key, "confirmed", settled.frame, "recognized_exact_successor")
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_reconciled",
                "action_key": action_key,
                "target_identity": target_identity,
                "source_frame_sha256": checkpoint.frame.sha256,
                "immediate_post_frame_sha256": immediate_post.sha256,
                "successor_frame_sha256": settled.frame.sha256,
                "source_state": _hud_contract_state(checkpoint.observation.state),
                "expected_successor_state": successor_state,
                "successor_state": successor_state,
                "successor_overlay_state": settled.observation.overlay_state,
                **_capture_metadata(immediate_post),
                "successor_capture_ordinal": _capture_identity(settled.frame)[1],
            },
        )
        return settled

    def _back(
        self,
        checkpoint: Checkpoint,
        *,
        successor_state: str,
    ) -> Checkpoint:
        if self.total_input_count >= self.maximum_inputs:
            raise WorldNavigationBlocked("route_input_budget_exhausted")
        if checkpoint.observation.source_frame_sha256 != checkpoint.frame.sha256:
            raise WorldNavigationBlocked("stale_or_cross_frame_search_roi")
        if not world_navigation_observation_authorizeable(
            checkpoint.observation,
            expected_state=WORLD_SEARCH_OPEN,
            require_supported_zoom=False,
        ):
            raise WorldNavigationBlocked("search_source_not_current_frame_bound")
        action_key = f"world-navigation:search-back:{checkpoint.frame.sha256[:24]}"
        self.navigation_input_count += 1
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_planned",
                "action_key": action_key,
                "target_identity": ANDROID_BACK,
                "source_state": checkpoint.observation.state,
                "source_frame_sha256": checkpoint.frame.sha256,
                "expected_successor_state": successor_state,
                **_capture_metadata(checkpoint.frame),
            },
        )
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_prepared",
                "action_key": action_key,
                "target_identity": ANDROID_BACK,
                "source_state": checkpoint.observation.state,
                "source_frame_sha256": checkpoint.frame.sha256,
                "expected_successor_state": successor_state,
                **_capture_metadata(checkpoint.frame),
            },
        )
        try:
            self.runtime.back(
                checkpoint.frame,
                action_key=action_key,
                continuation_of=None,
            )
        except Exception as exc:
            raise WorldNavigationBlocked(
                f"navigation_transport_ambiguous:{ANDROID_BACK}:{type(exc).__name__}"
            ) from exc
        immediate_post = self.runtime.capture("world-search-back-immediate-post")
        settled = self._settle_successor(
            immediate_post,
            successor_state,
            "world-search-back",
        )
        reconcile = getattr(self.runtime, "reconcile", None)
        if callable(reconcile):
            reconcile(action_key, "confirmed", settled.frame, "recognized_exact_successor")
        _record(
            self.runtime,
            self.route_events,
            {
                "event": "navigation_reconciled",
                "action_key": action_key,
                "target_identity": ANDROID_BACK,
                "source_frame_sha256": checkpoint.frame.sha256,
                "immediate_post_frame_sha256": immediate_post.sha256,
                "successor_frame_sha256": settled.frame.sha256,
                "source_state": checkpoint.observation.state,
                "expected_successor_state": successor_state,
                "successor_state": settled.observation.state,
                "successor_overlay_state": settled.observation.overlay_state,
                **_capture_metadata(immediate_post),
                "successor_capture_ordinal": _capture_identity(settled.frame)[1],
            },
        )
        return settled

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        home_recovery_started: float | None = None
        current = self.runtime.capture("world-navigation-source")
        try:
            home = self._checkpoint(current, HOME_READY)
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "state_recognized",
                    "state": _hud_contract_state(home.observation.state),
                    "frame_sha256": home.frame.sha256,
                    "checkpoint": "world-navigation-source",
                    **_capture_metadata(home.frame),
                },
            )
            world = self._tap(
                home,
                target_identity=HOME_TO_WORLD,
                successor_state=WORLD_READY,
                label="home-to-world",
            )
            world = self._fresh_checkpoint(WORLD_READY, "world-search-source")
            search = self._tap(
                world,
                target_identity=WORLD_SEARCH_ENTRY,
                successor_state=WORLD_SEARCH_OPEN,
                label="world-search-entry",
            )
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "world_search_open",
                    "state": WORLD_SEARCH_OPEN,
                    "frame_sha256": search.frame.sha256,
                },
            )
            search = self._fresh_checkpoint(
                WORLD_SEARCH_OPEN, "world-search-close-source"
            )
            world_again = self._back(search, successor_state=WORLD_READY)
            world_again = self._fresh_checkpoint(
                WORLD_READY, "world-to-home-source"
            )
            home_recovery_started = time.monotonic()
            home_again = self._tap(
                world_again,
                target_identity=WORLD_TO_HOME,
                successor_state=HOME_READY,
                label="world-to-home",
            )
            final = self._checkpoint(home_again.frame, HOME_READY)
            latency = time.monotonic() - (home_recovery_started or started)
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "route_terminal",
                    "state": HOME_READY,
                    "overlay_state": final.observation.overlay_state,
                    "frame_sha256": final.frame.sha256,
                    **_capture_metadata(final.frame),
                },
            )
            return self._result(
                status=NAVIGATION_ONLY_COMPLETE,
                reason="verified_hud_home_round_trip",
                terminal_runtime_state=HOME_READY,
                final=final,
                home_recovery_latency_seconds=latency,
                started=started,
                path=FULL_ROUTE_PATH,
            )
        except WorldNavigationBlocked as exc:
            return self._result(
                status=BLOCKED_FAIL_CLOSED,
                reason=str(exc),
                terminal_runtime_state="safe_blocked_terminal",
                final=None,
                home_recovery_latency_seconds=(
                    time.monotonic() - home_recovery_started
                    if home_recovery_started is not None
                    else None
                ),
                started=started,
                path=FULL_ROUTE_PATH,
            )

    def run_search_entry_only(self) -> dict[str, Any]:
        """Tap Search once from a fresh World checkpoint and stop open."""

        started = time.monotonic()
        current = self.runtime.capture("world-search-entry-only-source")
        try:
            world = self._checkpoint(current, WORLD_READY)
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "state_recognized",
                    "state": world.observation.state,
                    "frame_sha256": world.frame.sha256,
                    "checkpoint": "world-search-entry-only-source",
                    **_capture_metadata(world.frame),
                },
            )
            search = self._tap(
                world,
                target_identity=WORLD_SEARCH_ENTRY,
                successor_state=WORLD_SEARCH_OPEN,
                label="world-search-entry",
            )
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "world_search_open",
                    "state": WORLD_SEARCH_OPEN,
                    "frame_sha256": search.frame.sha256,
                },
            )
            final = self._checkpoint(search.frame, WORLD_SEARCH_OPEN)
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "route_terminal",
                    "state": WORLD_SEARCH_OPEN,
                    "overlay_state": final.observation.overlay_state,
                    "frame_sha256": final.frame.sha256,
                    **_capture_metadata(final.frame),
                },
            )
            return self._result(
                status=NAVIGATION_ONLY_COMPLETE,
                reason="verified_world_ready_to_search_open",
                terminal_runtime_state=WORLD_SEARCH_OPEN,
                final=final,
                home_recovery_latency_seconds=None,
                started=started,
                path=SEARCH_ENTRY_ONLY_PATH,
            )
        except WorldNavigationBlocked as exc:
            return self._result(
                status=BLOCKED_FAIL_CLOSED,
                reason=str(exc),
                terminal_runtime_state="safe_blocked_terminal",
                final=None,
                home_recovery_latency_seconds=None,
                started=started,
                path=SEARCH_ENTRY_ONLY_PATH,
            )

    def recover_home(self) -> dict[str, Any]:
        """Return an open World map or Search menu to Home with bounded inputs."""

        started = time.monotonic()
        current = self.runtime.capture("world-home-recovery-source")
        try:
            initial = _recognize(self.recognizer, current)
            if initial.source_frame_sha256 != current.sha256:
                raise WorldNavigationBlocked("stale_or_cross_frame_observation")
            if initial.state == WORLD_SEARCH_OPEN:
                if not world_navigation_observation_authorizeable(
                    initial,
                    expected_state=WORLD_SEARCH_OPEN,
                    require_supported_zoom=False,
                ):
                    raise WorldNavigationBlocked("world_search_menu_not_authorizeable")
                world = Checkpoint(current, initial)
                world = self._back(world, successor_state=WORLD_READY)
                world = self._fresh_checkpoint(
                    WORLD_READY,
                    "world-to-home-source",
                )
            elif self.recognizer is recognize_world_frame:
                world_observation = recognize_world_home_recovery(
                    current.frame,
                    source_frame_sha256=current.sha256,
                    evidence_ref=str(current.path),
                )
                if world_observation.source_frame_sha256 != current.sha256:
                    raise WorldNavigationBlocked("stale_or_cross_frame_observation")
                if not world_navigation_observation_authorizeable(
                    world_observation,
                    expected_state=WORLD_READY,
                    required_target_identity=WORLD_TO_HOME,
                    require_supported_zoom=False,
                ):
                    raise WorldNavigationBlocked(
                        "world_home_control_not_authorizeable:"
                        f"state={world_observation.state}:"
                        f"controls={','.join(sorted(world_observation.controls))}:"
                        f"home_geometry={world_observation.control_geometry_source.get(WORLD_TO_HOME)}:"
                        f"overlay={world_observation.overlay_state}"
                    )
                world = Checkpoint(current, world_observation)
            else:
                world = self._checkpoint(current, WORLD_READY)
            home = self._tap(
                world,
                target_identity=WORLD_TO_HOME,
                successor_state=HOME_READY,
                label="world-home-recovery",
            )
            final = self._checkpoint(home.frame, HOME_READY)
            _record(
                self.runtime,
                self.route_events,
                {
                    "event": "route_terminal",
                    "state": HOME_READY,
                    "overlay_state": final.observation.overlay_state,
                    "frame_sha256": final.frame.sha256,
                    **_capture_metadata(final.frame),
                },
            )
            return self._result(
                status=NAVIGATION_ONLY_COMPLETE,
                reason="verified_world_to_home_recovery",
                terminal_runtime_state=HOME_READY,
                final=final,
                home_recovery_latency_seconds=time.monotonic() - started,
                started=started,
                path=RECOVERY_PATH,
            )
        except WorldNavigationBlocked as exc:
            return self._result(
                status=BLOCKED_FAIL_CLOSED,
                reason=str(exc),
                terminal_runtime_state="safe_blocked_terminal",
                final=None,
                home_recovery_latency_seconds=None,
                started=started,
                path=RECOVERY_PATH,
            )

    def _result(
        self,
        *,
        status: str,
        reason: str,
        terminal_runtime_state: str,
        final: Checkpoint | None,
        home_recovery_latency_seconds: float | None,
        started: float,
        path: str,
    ) -> dict[str, Any]:
        result = {
            "schema_version": 1,
            "flow_id": FLOW_ID,
            "status": status,
            "reason": reason,
            "terminal_runtime_state": terminal_runtime_state,
            "path": path,
            "navigation_input_count": self.navigation_input_count,
            "safe_popup_input_count": self.safe_popup_input_count,
            "input_count": self.total_input_count,
            "max_inputs": self.maximum_inputs,
            "home_recovery_latency_seconds": home_recovery_latency_seconds,
            "elapsed_seconds": time.monotonic() - started,
            "popup_contract_version": POPUP_CONTRACT_VERSION,
            "popup_contract_registry": sorted(POPUP_CONTRACT_REGISTRY),
            "route_transitions": [
                event
                for event in self.route_events
                if event.get("event") in {"navigation_reconciled", "safe_popup_reconciled"}
            ],
            "route_events": list(self.route_events),
            "final_state": (
                _hud_contract_state(final.observation.state) if final else None
            ),
            "final_overlay_state": final.observation.overlay_state if final else None,
            "final_frame_sha256": final.frame.sha256 if final else None,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "resource_actions": 0,
            "combat_actions": 0,
            "node_inputs": 0,
            "resource_node_selection_inputs": 0,
            "march_inputs": 0,
            "formation_inputs": 0,
            "occupancy_override_inputs": 0,
            "stamina_inputs": 0,
            "ap_inputs": 0,
            "currency_inputs": 0,
            "forbidden_input_classes": [],
        }
        return result


def run_world_map_navigation(
    runtime: Any,
    *,
    maximum_inputs: int = MAX_ROUTE_INPUTS,
    maximum_popup_inputs: int = MAX_SAFE_POPUP_INPUTS,
    recognizer: Callable[..., Any] | None = None,
    search_entry_only: bool = False,
) -> dict[str, Any]:
    """Run the route against an injected runtime; useful for deterministic tests."""

    if search_entry_only:
        return run_world_map_search_entry_only(
            runtime,
            maximum_inputs=1,
            recognizer=recognizer,
        )
    return WorldMapNavigationController(
        runtime,
        recognizer=recognizer,
        maximum_inputs=maximum_inputs,
        maximum_popup_inputs=maximum_popup_inputs,
    ).run()


def run_world_map_search_entry_only(
    runtime: Any,
    *,
    maximum_inputs: int = 1,
    recognizer: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run only the one-input World -> Search-entry canary."""

    if type(maximum_inputs) is not int or maximum_inputs != 1:
        raise ValueError("search-entry-only maximum_inputs must be exactly 1")
    return WorldMapNavigationController(
        runtime,
        recognizer=recognizer,
        maximum_inputs=1,
        maximum_popup_inputs=0,
    ).run_search_entry_only()


def recover_world_map_home(
    runtime: Any,
    *,
    maximum_inputs: int = 1,
    recognizer: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run only the explicit World-to-Home recovery transition."""

    return WorldMapNavigationController(
        runtime,
        recognizer=recognizer,
        maximum_inputs=maximum_inputs,
        maximum_popup_inputs=0,
    ).recover_home()


def default_maximum_inputs() -> int:
    try:
        value = int(os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", str(MAX_ROUTE_INPUTS)))
    except ValueError:
        return MAX_ROUTE_INPUTS
    return max(1, min(MAX_ROUTE_INPUTS, value))


def route_declaration() -> dict[str, Any]:
    """Static audit view of the navigation-only capability boundary."""

    return {
        "flow_id": FLOW_ID,
        "package": PACKAGE_ID,
        "native_profile": NATIVE_RUNTIME_PROFILE_ID,
        "allowed_source_states": [HOME_READY, HOME_CANONICAL, WORLD_READY, WORLD_SEARCH_OPEN],
        "required_start_state": HOME_READY,
        "allowed_target_identities": sorted(ALLOWED_CONTROL_IDENTITIES),
        "allowed_gesture_classes": ["tap", "back"],
        "consequence_class": "navigation_only",
        "resource_actions": False,
        "combat_actions": False,
        "node_inputs": False,
        "forbidden_input_classes": [
            "resource_node_selection",
            "march",
            "formation",
            "occupancy_override",
            "stamina",
            "ap",
            "resource",
            "currency",
            "combat",
        ],
        "scheduler_enabled": False,
        "production_registration": "NOT_REGISTERED",
    }