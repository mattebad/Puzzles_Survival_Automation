#!/usr/bin/env python3
"""Evidence-gated native BlueStacks Commander enhancement route.

The route is deliberately direct: canonical Home profile portrait -> Commander
Info -> one requested category -> one equipped item -> Enhance -> one exact
one-star material -> quantity one -> Use -> same-item successor -> Home.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from collections import Counter
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime, NativeBox, captured_native_frame_from_png
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)
from scripts.startup_normalization import is_clean_home_frame
from scripts.bounded_tesseract import (
    DEADLINE as _OCR_DEADLINE, CHECKPOINT as _OCR_CHECKPOINT,
    OcrDeadline as _OcrDeadline, check_budget as _check_ocr_budget,
    call_ocr, tesseract_data as _tesseract_data,
)


FLOW_ID = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
ORDERED_VARIANTS = ("gear", "chip", "module")
NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
NATIVE_PROFILE_ID = BLUESTACKS_RUNTIME_PROFILE_ID
FULL_FRAME: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

# These are semantic search bounds only.  Dispatch boxes come from current-frame
# recognition and never from the reference images or these constants.
HOME_PROFILE_SEARCH_ROI: NativeBox = (0, 0, 300, 380)
HOME_PROFILE_PORTRAIT_ROI: NativeBox = (4, 40, 84, 123)
COMMANDER_HEADER_ROI: NativeBox = (0, 0, 800, 220)
CATEGORY_SEARCH_ROI: NativeBox = (0, 80, 800, 360)
ITEM_SEARCH_ROI: NativeBox = (0, 210, 800, 820)
MATERIAL_SEARCH_ROI: NativeBox = (0, 620, 800, 1140)
CONTROL_SEARCH_ROI: NativeBox = (0, 760, 800, 1260)
GEAR_DETAIL_TITLE_ROI: NativeBox = (290, 345, 510, 385)
GEAR_DETAIL_LEVEL_ROI: NativeBox = (342, 428, 405, 465)
GEAR_DETAIL_STATS_ROI: NativeBox = (90, 590, 710, 780)
GEAR_DETAIL_FOOTER_ROIS: Mapping[str, NativeBox] = {
    "enhance": (150, 915, 260, 950),
    "promote": (280, 920, 390, 950),
    "replace": (410, 915, 520, 950),
    "unequip": (540, 915, 650, 950),
}
CHIP_DETAIL_TITLE_ROI: NativeBox = (280, 365, 520, 404)
CHIP_DETAIL_LEVEL_ROI: NativeBox = (343, 449, 391, 477)
CHIP_DETAIL_STATS_ROI: NativeBox = (90, 630, 710, 752)
CHIP_DETAIL_FOOTER_ROIS: Mapping[str, NativeBox] = {
    "enhance": (85, 900, 195, 935),
    "promote": (215, 900, 325, 935),
    "modify": (350, 900, 450, 935),
    "replace": (475, 900, 585, 935),
    "unequip": (605, 900, 715, 935),
}
MODULE_DETAIL_TITLE_ROI: NativeBox = (250, 365, 550, 404)
MODULE_DETAIL_LEVEL_ROI: NativeBox = (345, 449, 389, 477)
MODULE_DETAIL_FOOTER_ROIS: Mapping[str, NativeBox] = {
    "enhance": (150, 900, 260, 935),
    "promote": (280, 900, 390, 935),
    "replace": (410, 900, 520, 935),
    "unequip": (540, 900, 650, 935),
}
COMMANDER_TAB_CONTEXT_ROI: NativeBox = (34, 58, 760, 120)
CATEGORY_TAB_BOXES: Mapping[str, NativeBox] = {
    "gear": (34, 58, 148, 112),
    "chip": (148, 58, 263, 112),
    "module": (263, 58, 377, 112),
}
CATEGORY_VISUAL_TAB_BOXES: Mapping[str, NativeBox] = {
    "gear": (42, 72, 185, 140),
    "chip": (185, 72, 329, 140),
    "module": (329, 72, 471, 140),
}
COMMANDER_CONTEXT_TAB_LABELS = frozenset(
    {"gear", "chip", "module", "cube", "bioenhancer"}
)
COMMANDER_CONTEXT_MIN_TAB_LABELS = 3
CATEGORY_TAB_MIN_RED_DOMINANCE = 12.0
CATEGORY_TAB_WINNER_MARGIN = 8.0
GEAR_RED_STAR_ARMOR_ROI: NativeBox = (50, 510, 133, 625)
CHIP_BLUE_TWO_STAR_ROI: NativeBox = (99, 590, 202, 696)
MODULE_GRAY_ONE_STAR_ROI: NativeBox = (214, 662, 314, 798)
GEAR_ONE_STAR_ENHANCER_REGION: NativeBox = (168, 675, 270, 790)
GEAR_ONE_STAR_ENHANCER_ROI: NativeBox = (208, 755, 224, 775)
CHIP_ONE_STAR_ENHANCER_ROI: NativeBox = (220, 744, 249, 778)
MODULE_ONE_STAR_ENHANCER_ROI: NativeBox = (80, 735, 115, 780)
QUANTITY_USE_ROI: NativeBox = (264, 780, 536, 875)
QUANTITY_MATERIAL_ROI: NativeBox = (220, 435, 700, 497)
QUANTITY_TOTAL_ROI: NativeBox = (220, 498, 460, 535)
QUANTITY_DENOMINATOR_ROI: NativeBox = (625, 670, 730, 712)
ENHANCEMENT_PANEL_TITLE_ROI: NativeBox = (220, 88, 590, 128)
ENHANCEMENT_PANEL_LEVEL_ROI: NativeBox = (343, 145, 391, 173)
GEAR_CONFIRM_ROI: NativeBox = (452, 1160, 725, 1250)
MAX_SETTLE_POLLS = 3
SETTLED_SUCCESSOR_DELAY_SECONDS = 1.0
OCR_CALL_TIMEOUT_SECONDS = 5.0
RECOGNITION_TIMEOUT_SECONDS = 15.0
FORBIDDEN_ACTIONS = frozenset({"promote", "modify", "replace", "unequip", "auto select"})
PREMIUM_MARKERS = frozenset({"gem", "gems", "diamond", "cash", "premium", "gold"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _normalize(value: object) -> str:
    return " ".join(str(value or "").lower().replace("★", " star ").split())


def _box(value: object) -> NativeBox | None:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        candidate = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = candidate
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        return None
    return candidate  # type: ignore[return-value]


def _expand(value: NativeBox, x_pad: int = 30, y_pad: int = 20) -> NativeBox:
    x0, y0, x1, y1 = value
    return (
        max(0, x0 - x_pad),
        max(0, y0 - y_pad),
        min(NATIVE_WIDTH, x1 + x_pad),
        min(NATIVE_HEIGHT, y1 + y_pad),
    )


@dataclass(frozen=True)
class OcrHit:
    text: str
    bounds: NativeBox
    confidence: float = 0.0


OcrEngine = Callable[[np.ndarray, NativeBox], Sequence[Any]]


def _bounded_recognition(*, home: bool = False):
    """Nested witness recognition shares one budget; each new observation gets its own."""
    def decorate(function):
        @wraps(function)
        def recognize(*args, **kwargs):
            token = (_OCR_DEADLINE.set(time.monotonic() + RECOGNITION_TIMEOUT_SECONDS)
                     if _OCR_DEADLINE.get() is None else None)
            try:
                _check_ocr_budget()
                result = function(*args, **kwargs)
                _check_ocr_budget()
                return result
            except _OcrDeadline:
                if token is None:
                    raise
                source = args[0] if args else kwargs.get("frame", kwargs.get("current"))
                frame = source.frame if isinstance(source, CapturedNativeFrame) else source
                digest = _digest(frame, kwargs.get("source_frame_sha256") or getattr(source, "sha256", None))
                if home:
                    return HomeRecognition(False, "UNKNOWN", "OCR_DEADLINE", digest)
                return StageRecognition(kwargs.get("stage", "material"), False, "OCR_DEADLINE", digest)
            finally:
                if token is not None:
                    _OCR_DEADLINE.reset(token)
        return recognize
    return decorate


def _call_ocr(reader, image: np.ndarray, **options):
    return call_ocr(reader, image, call_timeout=OCR_CALL_TIMEOUT_SECONDS, **options)


def _region_ocr(frame: np.ndarray, roi: NativeBox, *, psm: int) -> list[OcrHit]:
    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    scale = 3
    # Preserve the denominator's thin slash; cubic ringing can turn it into
    # a second digit and leave the complete stock value unreadable.
    scaled = cv2.resize(crop, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_LINEAR if roi == QUANTITY_DENOMINATOR_ROI else cv2.INTER_CUBIC)
    if roi == QUANTITY_DENOMINATOR_ROI:
        # Explicit luminance avoids platform-dependent color thresholding in
        # Tesseract: identical color pixels can become a spurious leading "1".
        scaled = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
    data = _call_ocr(_tesseract_data,
        scaled,
        config=f"--psm {psm}",
    )
    hits: list[OcrHit] = []
    for index, raw in enumerate(data.get("text", ())):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError, IndexError):
            confidence = -1.0
        if confidence < 20:
            continue
        left = x0 + int(data["left"][index] / scale)
        top = y0 + int(data["top"][index] / scale)
        right = left + max(1, int(data["width"][index] / scale))
        bottom = top + max(1, int(data["height"][index] / scale))
        bounds = _box((left, top, right, bottom))
        if bounds is not None:
            hits.append(OcrHit(text, bounds, confidence))
    return hits


def _default_ocr(frame: np.ndarray, roi: NativeBox) -> list[OcrHit]:
    # These modal fields have known text structure. Sparse mode can omit the
    # level or merge Basic Stats with the decorative power icon above it.
    psm = 11
    if roi in (GEAR_DETAIL_LEVEL_ROI, GEAR_DETAIL_FOOTER_ROIS["promote"], QUANTITY_DENOMINATOR_ROI):
        psm = 7
    elif roi == GEAR_DETAIL_STATS_ROI:
        psm = 6
    return _region_ocr(frame, roi, psm=psm)


def _quantity_material_ocr(frame: np.ndarray, roi: NativeBox) -> list[OcrHit]:
    # The material caption is one text block and can wrap. Sparse-text mode can
    # merge the two lines and omit a word; retain all words from block mode.
    return _region_ocr(frame, roi, psm=6)


def _coerce_hits(raw: Sequence[Any] | None) -> list[OcrHit]:
    hits: list[OcrHit] = []
    for value in raw or ():
        if isinstance(value, OcrHit):
            hits.append(value)
        elif isinstance(value, Mapping):
            text = str(value.get("text") or "").strip()
            bounds = _box(value.get("bounds") or value.get("roi"))
            if text and bounds is not None:
                hits.append(OcrHit(text, bounds, float(value.get("confidence", 1.0))))
    return hits


def _hits(frame: np.ndarray, roi: NativeBox, engine: OcrEngine | None) -> list[OcrHit]:
    raw = _coerce_hits((engine or _default_ocr)(frame, roi))
    x0, y0, x1, y1 = roi
    return [
        hit
        for hit in raw
        if x0 <= hit.bounds[0] < hit.bounds[2] <= x1
        and y0 <= hit.bounds[1] < hit.bounds[3] <= y1
    ]


def _text(hits: Sequence[OcrHit]) -> str:
    return " ".join(_normalize(hit.text) for hit in hits)


def _center(bounds: NativeBox) -> tuple[int, int]:
    return (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2


def _associated(
    marker: OcrHit, target: OcrHit, *, y_slack: int = 90, x_slack: int = 260
) -> bool:
    mx, my = _center(marker.bounds)
    tx, ty = _center(target.bounds)
    return abs(my - ty) <= y_slack and abs(mx - tx) <= x_slack


def _red_dominance(frame: np.ndarray, bounds: NativeBox) -> float | None:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] < 3:
        return None
    x0, y0, x1, y1 = bounds
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    red = crop[:, :, 2].astype(np.float32)
    green = crop[:, :, 1].astype(np.float32)
    return float(np.mean(red - green))


def _profile_portrait_visual_present(frame: np.ndarray) -> bool:
    x0, y0, x1, y1 = HOME_PROFILE_PORTRAIT_ROI
    crop = frame[y0:y1, x0:x1]
    if crop.shape[:2] != (y1 - y0, x1 - x0):
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edge_density = float(np.mean(cv2.Canny(gray, 60, 140) > 0))
    return bool(float(gray.std()) >= 40.0 and edge_density >= 0.12)


def _classify_selected_category_visual(frame: np.ndarray) -> str | None:
    """Classify a selected tab only from the fixed native tab boxes."""
    candidates: list[tuple[float, str]] = []
    for boxes in (CATEGORY_VISUAL_TAB_BOXES, CATEGORY_TAB_BOXES):
        scores = {
            variant: _red_dominance(frame, bounds)
            for variant, bounds in boxes.items()
        }
        if any(score is None for score in scores.values()):
            continue
        ordered = sorted(
            ((float(score), variant) for variant, score in scores.items()),
            reverse=True,
        )
        winner_score, winner = ordered[0]
        runner_score = ordered[1][0]
        if (
            winner_score >= CATEGORY_TAB_MIN_RED_DOMINANCE
            and winner_score - runner_score >= CATEGORY_TAB_WINNER_MARGIN
        ):
            candidates.append((winner_score - runner_score, winner))
    return max(candidates)[1] if candidates else None


def _commander_tab_context_sufficient(categories: Sequence[OcrHit]) -> bool:
    context_labels = {
        _normalize(hit.text)
        for hit in categories
        if (
            COMMANDER_TAB_CONTEXT_ROI[0] <= hit.bounds[0]
            and hit.bounds[2] <= COMMANDER_TAB_CONTEXT_ROI[2]
            and COMMANDER_TAB_CONTEXT_ROI[1] <= hit.bounds[1]
            and hit.bounds[3] <= COMMANDER_TAB_CONTEXT_ROI[3]
            and _normalize(hit.text) in COMMANDER_CONTEXT_TAB_LABELS
        )
    }
    return (
        len(context_labels) >= COMMANDER_CONTEXT_MIN_TAB_LABELS
        and bool(context_labels & set(CATEGORY_TAB_BOXES))
    )


def _commander_header_recognized(
    header: Sequence[OcrHit],
    categories: Sequence[OcrHit],
    visual_selected: str | None,
) -> bool:
    header_text = _text(header)
    if "commander info" in header_text or "commanderinfo" in header_text:
        return True
    info_hits = [
        hit
        for hit in header
        if _normalize(hit.text) == "info" and hit.bounds[3] <= 80
    ]
    if len(info_hits) == 1 and _commander_tab_context_sufficient(categories):
        return True
    context_labels = {
        _normalize(hit.text)
        for hit in categories
        if _normalize(hit.text) in COMMANDER_CONTEXT_TAB_LABELS
    }
    return bool(
        context_labels == COMMANDER_CONTEXT_TAB_LABELS
        or (
            visual_selected in CATEGORY_TAB_BOXES
            and len(context_labels) >= 4
            and context_labels | {visual_selected} == COMMANDER_CONTEXT_TAB_LABELS
        )
    )


def _unique_hits(hits: Sequence[OcrHit]) -> list[OcrHit]:
    unique: list[OcrHit] = []
    seen: set[tuple[str, NativeBox]] = set()
    for hit in hits:
        key = (_normalize(hit.text), hit.bounds)
        if key not in seen:
            seen.add(key)
            unique.append(hit)
    return unique


def _icon_overview_binding(
    hits: Sequence[OcrHit], variant: str, frame: np.ndarray
) -> tuple[str, int, NativeBox] | None:
    del hits
    target = {
        "gear": GEAR_RED_STAR_ARMOR_ROI,
        "chip": CHIP_BLUE_TWO_STAR_ROI,
        "module": MODULE_GRAY_ONE_STAR_ROI,
    }.get(variant)
    if target is None:
        return None
    x0, y0, x1, y1 = target
    crop = frame[y0:y1, x0:x1]
    if crop.shape[:2] != (y1 - y0, x1 - x0):
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = (
        ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170))
        & (hsv[:, :, 1] > 100)
        & (hsv[:, :, 2] > 80)
    )
    if variant == "chip":
        blue = (
            (hsv[:, :, 0] >= 85)
            & (hsv[:, :, 0] <= 125)
            & (hsv[:, :, 1] > 100)
            & (hsv[:, :, 2] > 80)
        )
        if (
            float(gray.std()) < 15.0
            or float(np.mean(red)) < 0.02
            or float(np.mean(blue)) < 0.04
        ):
            return None
        return "chip-blue-triangular-two-star", 20, CHIP_BLUE_TWO_STAR_ROI
    if variant == "module":
        if float(gray.std()) < 15.0 or float(np.mean(red)) < 0.01:
            return None
        return "module-gray-shield-one-star", 18, MODULE_GRAY_ONE_STAR_ROI
    if float(gray.std()) < 15.0 or float(np.mean(red)) < 0.04:
        return None
    return "gear-red-star-chest-armor", 0, GEAR_RED_STAR_ARMOR_ROI


def _is_marker(hit: OcrHit) -> bool:
    text = _normalize(hit.text)
    return text in {"selected", "active", "checked", "check", "current"} or (
        "selected" in text
    )


def _target(hits: Sequence[OcrHit], names: set[str]) -> NativeBox | None:
    matches = [hit for hit in hits if _normalize(hit.text) in names]
    return _expand(matches[0].bounds) if len(matches) == 1 else None


def _frame_hash(frame: np.ndarray) -> str:
    if frame is None or not isinstance(frame, np.ndarray):
        return ""
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("native frame could not be encoded")
    return hashlib.sha256(encoded.tobytes()).hexdigest()


def _digest(frame: np.ndarray, supplied: str | None) -> str:
    return supplied if _SHA256_RE.fullmatch(str(supplied or "")) else _frame_hash(frame)


@dataclass(frozen=True)
class HomeRecognition:
    recognized: bool
    state: str
    reason: str
    frame_sha256: str
    portrait_identity: str = ""
    portrait_target: NativeBox | None = None


def _home_profile_ocr_hits(hits: Sequence[OcrHit]) -> tuple[list[OcrHit], bool]:
    """Consolidate repeated reads of one header glyph, never distinct badges."""
    def area(hit: OcrHit) -> int:
        x0, y0, x1, y1 = hit.bounds
        return (x1 - x0) * (y1 - y0)
    def same_glyph(first: OcrHit, second: OcrHit) -> bool:
        ax0, ay0, ax1, ay1 = first.bounds
        bx0, by0, bx1, by1 = second.bounds
        overlap = max(0, min(ax1, bx1) - max(ax0, bx0)) * max(0, min(ay1, by1) - max(ay0, by0))
        acx, acy = _center(first.bounds)
        bcx, bcy = _center(second.bounds)
        return (overlap >= .9 * min(area(first), area(second))
            and ax0 <= bcx <= ax1 and ay0 <= bcy <= ay1
            and bx0 <= acx <= bx1 and by0 <= acy <= by1)
    def header_witness(hit: OcrHit) -> bool:
        text = _normalize(hit.text)
        return bool((re.fullmatch(r"[1-9][0-9]{0,2}", text) and hit.bounds[2] <= 80 and hit.bounds[3] <= 130)
            or (re.fullmatch(r"vip[0-9o]{1,3}", text) and hit.bounds[0] < 280 and hit.bounds[3] <= 150)
            or "portrait" in text or text in {"profile", "commander"})
    contradictory = any(_normalize(first.text) != _normalize(second.text) and same_glyph(first, second)
        and (header_witness(first) or header_witness(second))
        for index, first in enumerate(hits) for second in hits[index + 1:])
    groups: list[list[OcrHit]] = []
    for hit in sorted(hits, key=lambda value: (-value.confidence, area(value))):
        duplicate = next((group for group in groups if _normalize(group[0].text) == _normalize(hit.text)
            and header_witness(group[0]) == header_witness(hit)
            and all(same_glyph(member, hit) for member in group)), None)
        if duplicate is None:
            groups.append([hit])
        else:
            # Complete overlap with the group prevents a large, low-resolution
            # OCR box from bridging two physically separate badge readings.
            duplicate.append(hit)
    return [group[0] for group in groups], contradictory


@_bounded_recognition(home=True)
def recognize_home_frame(
    frame: np.ndarray,
    *,
    source_frame_sha256: str | None = None,
    ocr_engine: OcrEngine | None = None,
) -> HomeRecognition:
    """Require shared clean Home proof and a unique current-frame profile portrait."""

    if isinstance(frame, CapturedNativeFrame):
        frame = frame.frame
    digest = _digest(frame, source_frame_sha256)
    if frame is None or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return HomeRecognition(False, "UNKNOWN", "NON_NATIVE_FRAME", digest)
    try:
        clean_home = is_clean_home_frame(frame)
    except (_OcrDeadline, _FlowBlocked):
        raise
    except Exception as exc:
        return HomeRecognition(False, "UNKNOWN", f"HOME_RECOGNITION_ERROR:{type(exc).__name__}", digest)
    if not clean_home:
        return HomeRecognition(False, "UNKNOWN", "CANONICAL_HOME_NOT_RECOGNIZED", digest)
    profile_hits, contradictory = _home_profile_ocr_hits(_hits(frame, HOME_PROFILE_SEARCH_ROI, ocr_engine))
    if contradictory:
        return HomeRecognition(False, "HOME_CANONICAL", "PROFILE_PORTRAIT_NOT_UNIQUE", digest)
    candidates = [
        hit
        for hit in profile_hits
        if "portrait" in _normalize(hit.text)
        or _normalize(hit.text) in {"profile", "commander"}
    ]
    if len(candidates) == 1:
        portrait = candidates[0]
        identity = _normalize(portrait.text).replace(" ", "-")
        target = _expand(portrait.bounds)
    else:
        level_markers = [
            hit for hit in profile_hits
            if re.fullmatch(r"[1-9][0-9]{0,2}", _normalize(hit.text))
            and hit.bounds[2] <= 80
            and hit.bounds[3] <= 130
        ]
        vip_markers = [
            hit for hit in profile_hits
            if re.fullmatch(r"vip[0-9o]{1,3}", _normalize(hit.text))
            and hit.bounds[0] < 280
            and hit.bounds[3] <= 150
        ]
        visual_portrait = _profile_portrait_visual_present(frame)
        if (
            candidates
            or len(level_markers) > 1
            or len(vip_markers) > 1
            or (
                not visual_portrait
                and (len(level_markers) != 1 or len(vip_markers) != 1)
            )
        ):
            return HomeRecognition(
                False, "HOME_CANONICAL", "PROFILE_PORTRAIT_NOT_UNIQUE", digest
            )
        level = level_markers[0] if level_markers else None
        identity = (
            f"profile-level-{_normalize(level.text)}"
            if level is not None
            else "profile-visual-fixed"
        )
        target = HOME_PROFILE_PORTRAIT_ROI if visual_portrait else _expand(
            level.bounds, x_pad=25, y_pad=25
        )
        if not (
            target[0] < target[2] <= 105
            and 35 <= target[1] < target[3] <= 145
        ):
            return HomeRecognition(
                False, "HOME_CANONICAL", "PROFILE_PORTRAIT_NOT_UNIQUE", digest
            )
    return HomeRecognition(
        True,
        "HOME_CANONICAL",
        "CANONICAL_HOME_AND_PROFILE_RECOGNIZED",
        digest,
        identity,
        target,
    )


@dataclass(frozen=True)
class StageRecognition:
    stage: str
    recognized: bool
    reason: str
    frame_sha256: str
    item_identity: str = ""
    category_selected: bool = False
    category_target: NativeBox | None = None
    item_target: NativeBox | None = None
    open_target: NativeBox | None = None
    material_identity: str = ""
    material_selected: bool = False
    material_target: NativeBox | None = None
    quantity: int | None = None
    quantity_target: NativeBox | None = None
    observation: EnhancementObservation | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    item_level: int = 0
    detail_state: str | None = None
    close_target: NativeBox | None = None
    back_target: NativeBox | None = None


@dataclass(frozen=True)
class EnhancementFrameRecognition:
    recognized: bool
    state: str
    reason: str
    observation: EnhancementObservation | None
    targets: tuple[tuple[str, NativeBox], ...] = ()

    @property
    def target_roi(self) -> NativeBox | None:
        for identity, target in self.targets:
            if identity == "enhancement-use":
                return target
        return None


def _level(text: str) -> int | None:
    match = re.search(r"\b(?:level|lvl)\s*[:#-]?\s*(\d{1,3})\b", text)
    return int(match.group(1)) if match else None


def _star(text: str) -> int | None:
    values = [int(value) for value in re.findall(r"\b([1-9])\s*[- ]?star\b", text)]
    for word, number in (("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5)):
        if f"{word} star" in text:
            values.append(number)
    return values[0] if values and len(set(values)) == 1 else None


def _quantity(text: str) -> int | None:
    values = [
        int(value)
        for pattern in (
            r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*(\d+)\b",
            r"\bx\s*(\d+)\b",
        )
        for value in re.findall(pattern, text)
    ]
    return values[0] if values and len(set(values)) == 1 else None


def _item_identity(
    hits: Sequence[OcrHit], variant: str
) -> tuple[str, OcrHit | None, str | None]:
    explicit: list[tuple[str, OcrHit]] = []
    for hit in hits:
        text = _normalize(hit.text)
        match = re.search(r"(?:item|identity)\s*[:#-]\s*(.+)", text)
        if match:
            explicit.append((match.group(1).replace(" ", "-"), hit))
    if len(explicit) != 1:
        return "", None, "ITEM_IDENTITY_NOT_UNIQUE"
    identity, hit = explicit[0]
    other_variants = [
        name for name in SUPPORTED_VARIANTS if name != variant and re.search(
            rf"\b{re.escape(name)}\b", _normalize(hit.text)
        )
    ]
    if other_variants:
        return "", None, "ITEM_VARIANT_CONFLICT"
    if variant not in _normalize(hit.text) and not identity.startswith("commander-"):
        return "", None, "ITEM_VARIANT_NOT_PROVEN"
    return identity, hit, None


def _identity_syntax_present(hits: Sequence[OcrHit]) -> bool:
    return any(
        re.search(r"\b(?:item|identity)\b", _normalize(hit.text))
        for hit in hits
    )


def _make_observation(
    *,
    variant: str,
    identity: str,
    item_equipped: bool,
    item_level: int,
    target: NativeBox | None,
    material_identity: str,
    material_known: bool,
    material_available: bool,
    material_star: int | None,
    material_quantity: int | None,
    quantity: int | None,
    result_visible: bool,
    result_identity: str,
    result_associated: bool,
    source_frame_sha256: str,
    evidence_ref: str | Path | None,
    game_day_id: str,
    material_inventory_count: int | None = None,
    item_exp_current: int | None = None,
    item_exp_required: int | None = None,
    material_slot_facts: tuple[tuple[int, int, int, int], ...] = (),
) -> EnhancementObservation:
    return EnhancementObservation(
        screen_state=ENHANCEMENT_SCREEN,
        selected_tab=variant.upper(),
        selected_item_kind=variant.upper(),
        selected_item_identity=identity,
        item_equipped=item_equipped,
        item_level=item_level,
        target_identity="enhancement-confirm",
        target_roi=target or (1, 1, 2, 2),
        panel_bounds=FULL_FRAME,
        control_class="ENHANCE",
        enhance_control_visible=target is not None,
        action_mode="ENHANCE",
        material_identity=material_identity,
        material_known=material_known,
        material_available=material_available,
        material_star=material_star,
        material_quantity=material_quantity,
        quantity=quantity,
        enhancement_result_visible=result_visible,
        result_identity=result_identity,
        game_day_id=game_day_id,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=source_frame_sha256,
        evidence_refs=(str(evidence_ref),) if evidence_ref is not None else (),
        overlay_state="none",
        runtime_profile_id=NATIVE_PROFILE_ID,
        recognized=True,
        result_spatially_associated=result_associated,
        material_inventory_count=material_inventory_count,
        item_exp_current=item_exp_current, item_exp_required=item_exp_required,
        material_slot_facts=material_slot_facts,
    )


def _visible_item_modal_close(frame: np.ndarray, roi: NativeBox = (640, 330, 735, 400)) -> NativeBox | None:
    """Use the existing Stage-X glyph shape on this measured modal corner."""
    x0, y0, x1, y1 = roi
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 0, 180), np.uint8), np.array((179, 80, 255), np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(mask)
    reference = np.zeros((40, 40), np.uint8)
    cv2.line(reference, (3, 3), (36, 36), 255, 9)
    cv2.line(reference, (3, 36), (36, 3), 255, 9)
    found = []
    for x, y, width, height, _area in components[1:]:
        if not (30 <= width <= 44 and 30 <= height <= 44 and .85 <= width / height <= 1.15):
            continue
        sample = cv2.resize(mask[y:y + height, x:x + width], (40, 40))
        if float(cv2.matchTemplate(sample, reference, cv2.TM_CCOEFF_NORMED)[0, 0]) >= .60:
            found.append(_expand((int(x + x0), int(y + y0), int(x + width + x0), int(y + height + y0)), 8, 8))
    return found[0] if len(found) == 1 else None


def _visible_back(frame: np.ndarray) -> NativeBox | None:
    from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual
    return _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)


def _gear_item_modal(
    frame: np.ndarray, digest: str, engine: OcrEngine | None,
) -> StageRecognition | None:
    """Bind the native Suit modal itself while its Commander tabs are blurred."""
    title = _hits(frame, GEAR_DETAIL_TITLE_ROI, engine)
    title_text = _text(sorted(title, key=lambda hit: hit.bounds[0]))
    # OCR can omit the decorative star or render it as x. The rarity digit,
    # equipped icon, level, stat rows and unique footer controls remain required.
    named = re.fullmatch(r"6\s*(?:\*|star|x)?\s+(s\.o\.f\s+suit)", title_text)
    if named is None:
        return None
    diagnostics: dict[str, Any] = {"binding_mode": "native_item_modal", "title_text": title_text}

    def rejected(reason):
        return StageRecognition("item", False, reason, digest, diagnostics=diagnostics)

    levels = _hits(frame, GEAR_DETAIL_LEVEL_ROI, engine)
    diagnostics["level_text"] = _text(levels)
    level = re.fullmatch(r"\+\s*(\d{1,3})[^\w\d]*", _text(levels)) if len(levels) == 1 else None
    if level is None:
        return rejected("GEAR_ITEM_MODAL_LEVEL_NOT_RECOGNIZED")
    icon = frame[428:543, 343:457]
    star = cv2.cvtColor(frame[501:540, 379:422], cv2.COLOR_BGR2HSV)
    red_star = (((star[:, :, 0] < 12) | (star[:, :, 0] > 170))
                & (star[:, :, 1] > 100) & (star[:, :, 2] > 80))
    if float(cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY).std()) < 20 or float(np.mean(red_star)) < 0.12:
        return rejected("GEAR_ITEM_MODAL_ICON_NOT_PROVEN")
    stats = _hits(frame, GEAR_DETAIL_STATS_ROI, engine)
    if re.search(r"\bbasic stats\b", _text(stats)) is None:
        return rejected("GEAR_ITEM_MODAL_STATS_NOT_RECOGNIZED")
    rows = []
    diagnostics["stat_rows"] = rows
    for top, bottom, label in ((645, 690, "fighter atk"), (690, 730, "shooter def"), (730, 775, "shooter hp")):
        row = sorted((hit for hit in stats if top <= _center(hit.bounds)[1] < bottom), key=lambda hit: hit.bounds[0])
        # The diamond at x98 is decorative and sometimes OCRs as a copyright
        # symbol. Bind the label and percentage columns independently of it.
        label_text = _text([hit for hit in row if 125 <= _center(hit.bounds)[0] <= 300])
        values = [hit for hit in row if 600 <= _center(hit.bounds)[0] <= 705]
        value_text = _text(values)
        rows.append({"label": label_text, "value": value_text, "raw_text": _text(row)})
        if label_text != label or len(values) != 1 or re.fullmatch(r"\d+(?:\.\d+)?%", value_text) is None:
            return rejected("GEAR_ITEM_MODAL_STAT_ROW_NOT_RECOGNIZED")
    footer = {}
    for label, roi in GEAR_DETAIL_FOOTER_ROIS.items():
        hits = _hits(frame, roi, engine)
        controls = [hit for hit in hits if _normalize(hit.text) == label]
        if len(controls) != 1 or any(_normalize(hit.text) in GEAR_DETAIL_FOOTER_ROIS and _normalize(hit.text) != label for hit in hits):
            diagnostics["unbound_footer"] = {"label": label, "text": _text(hits)}
            return rejected("GEAR_ITEM_MODAL_FOOTER_NOT_UNIQUE")
        footer[label] = controls[0].bounds
    return StageRecognition(
        "item", True, "GEAR_ITEM_DETAIL_MODAL_RECOGNIZED", digest,
        item_identity=named.group(1), category_selected=True,
        open_target=_expand(footer["enhance"], x_pad=8, y_pad=8), item_level=int(level.group(1)),
        detail_state="item_modal", close_target=_visible_item_modal_close(frame),
        diagnostics={**diagnostics, "footer_controls": footer},
    )


def _stat_item_modal(
    frame: np.ndarray, digest: str, engine: OcrEngine | None, *, variant: str,
) -> StageRecognition | None:
    """Bind the measured Chip/Module modal, equipment, stats and visible exits."""
    title_roi = CHIP_DETAIL_TITLE_ROI if variant == "chip" else MODULE_DETAIL_TITLE_ROI
    level_roi = CHIP_DETAIL_LEVEL_ROI if variant == "chip" else MODULE_DETAIL_LEVEL_ROI
    footer_rois = CHIP_DETAIL_FOOTER_ROIS if variant == "chip" else MODULE_DETAIL_FOOTER_ROIS
    prefix = variant.upper()
    title = _text(sorted(_hits(frame, title_roi, engine), key=lambda hit: hit.bounds[0]))
    named = re.fullmatch(rf"([1-9])\s*(?:\*|star|x)?\s+(fighter\s+{variant})", title)
    if named is None:
        return None
    diagnostics: dict[str, Any] = {"binding_mode": "native_item_modal", "title_text": title,
        "item_star": int(named.group(1))}
    def rejected(reason: str) -> StageRecognition:
        return StageRecognition("item", False, reason, digest, diagnostics=diagnostics)
    levels = _hits(frame, level_roi, engine)
    level_text = _text(levels)
    diagnostics["level_text"] = level_text
    level = re.fullmatch(r"\+\s*(\d{1,3})", level_text) if len(levels) == 1 else None
    if level is None:
        return rejected(f"{prefix}_ITEM_MODAL_LEVEL_NOT_RECOGNIZED")
    icon = frame[447:561, 343:457]
    hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
    hue_min, hue_max = (80, 115) if variant == "chip" else (15, 40)
    colored = (hsv[:, :, 0] >= hue_min) & (hsv[:, :, 0] <= hue_max) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)
    star = cv2.cvtColor(frame[516:558, 377:425], cv2.COLOR_BGR2HSV)
    red = ((star[:, :, 0] < 12) | (star[:, :, 0] > 170)) & (star[:, :, 1] > 100) & (star[:, :, 2] > 80)
    if float(cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY).std()) < 20 or np.mean(colored) < .08 or np.mean(red) < .12:
        return rejected(f"{prefix}_ITEM_MODAL_ICON_NOT_PROVEN")
    stats = _hits(frame, CHIP_DETAIL_STATS_ROI, engine)
    rows = []
    diagnostics["stat_rows"] = rows
    for top, bottom, label in ((630, 672, "fighter hp"), (672, 712, "fighter def"), (712, 752, "fighter atk")):
        row = [hit for hit in stats if top <= _center(hit.bounds)[1] < bottom]
        labels = sorted((hit for hit in row if 125 <= _center(hit.bounds)[0] <= 300), key=lambda hit: hit.bounds[0])
        values = [hit for hit in row if 600 <= _center(hit.bounds)[0] <= 705]
        label_text, value_text = _text(labels), _text(values)
        rows.append({"label": label_text, "value": value_text})
        if label_text != label or len(values) != 1 or re.fullmatch(r"\d+(?:\.\d+)?%", value_text) is None:
            return rejected(f"{prefix}_ITEM_MODAL_STAT_ROW_NOT_RECOGNIZED")
    footer = {}
    for label, roi in footer_rois.items():
        hits = _hits(frame, roi, engine)
        controls = [hit for hit in hits if _normalize(hit.text) == label]
        if len(controls) != 1 or any(_normalize(hit.text) in footer_rois and _normalize(hit.text) != label for hit in hits):
            diagnostics["unbound_footer"] = {"label": label, "text": _text(hits)}
            return rejected(f"{prefix}_ITEM_MODAL_FOOTER_NOT_UNIQUE")
        footer[label] = controls[0].bounds
    close = _visible_item_modal_close(frame, (640, 345, 735, 420))
    if close is None:
        return rejected(f"{prefix}_ITEM_MODAL_CLOSE_NOT_UNIQUE")
    return StageRecognition("item", True, f"{prefix}_ITEM_DETAIL_MODAL_RECOGNIZED", digest,
        item_identity=named.group(2), category_selected=True, item_level=int(level.group(1)),
        open_target=_expand(footer["enhance"], 8, 8), detail_state="item_modal", close_target=close,
        diagnostics={**diagnostics, "footer_controls": footer})


def _native_enhancement_panel(
    frame: np.ndarray, *, variant: str, stage: str, digest: str, engine: OcrEngine | None,
) -> StageRecognition | None:
    """Recognize panel context without inventing a material selection or effect."""
    heading = _text(_hits(frame, (270, 10, 550, 60), engine))
    if heading != f"enhance {variant}":
        return None
    title_text = _text(_hits(frame, ENHANCEMENT_PANEL_TITLE_ROI, engine))
    names = {"gear": r"s\.o\.f\s+suit", "chip": r"fighter\s+chip", "module": r"fighter\s+module"}
    titles = list(re.finditer(rf"\b({names[variant]})\s*\+\s*(\d{{1,3}})\b", title_text))
    title = titles[0] if len(titles) == 1 else None
    conflicting_name = any(name != variant and re.search(rf"\b{pattern}\b", title_text) for name, pattern in names.items())
    level_hits = _hits(frame, ENHANCEMENT_PANEL_LEVEL_ROI, engine)
    level_text = _text(level_hits)
    level = re.fullmatch(r"\+\s*(\d{1,3})[^\w\d]*", level_text) if len(level_hits) == 1 else None
    exp_text = _text(_hits(frame, (300, 330, 505, 366), engine)).replace(" ", "")
    exp = re.fullmatch(r"(\d+)/(\d+)", exp_text)
    details = {"heading": heading, "title_text": title_text, "level_text": level_text,
        "exp_text": exp_text, "material_facts_verified": False}
    if title is None or conflicting_name or level is None or exp is None or title.group(2) != level.group(1):
        return StageRecognition(stage, False, "ENHANCEMENT_PANEL_ITEM_OR_EXP_UNKNOWN", digest, diagnostics=details)
    current, required = map(int, exp.groups())
    if not 0 <= current < required:
        return StageRecognition(stage, False, "ENHANCEMENT_PANEL_EXP_INVALID", digest, diagnostics=details)
    green = cv2.inRange(cv2.cvtColor(frame[330:366, 300:505], cv2.COLOR_BGR2HSV),
        np.array((45, 100, 50), np.uint8), np.array((85, 255, 255), np.uint8))
    details.update(displayed_exp_current=current, displayed_exp_required=required,
        exp_display_state="preview" if cv2.countNonZero(green) >= 10 else "committed")
    return StageRecognition(stage, True, "ENHANCEMENT_PANEL_NAVIGATION_ONLY", digest,
        item_identity=title.group(1), item_level=int(title.group(2)), category_selected=True,
        detail_state="enhancement_panel", back_target=_visible_back(frame), diagnostics=details)


def _quantity_count(frame: np.ndarray) -> int | None:
    import pytesseract
    # Isolate the displayed gold digits from their dark input field. No default
    # quantity is supplied when the glyph is missing or the two reads disagree.
    digits = cv2.inRange(cv2.cvtColor(frame[670:710, 508:623], cv2.COLOR_BGR2HSV),
        np.array((10, 80, 90), np.uint8), np.array((45, 255, 255), np.uint8))
    current = cv2.resize(255 - digits, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    current = cv2.copyMakeBorder(current, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    readings = [re.sub(r"\s+", "", _call_ocr(pytesseract.image_to_string, current,
        config=f"--psm {mode} -c tessedit_char_whitelist=0123456789")) for mode in (7, 10)]
    return int(readings[0]) if readings[0] == readings[1] and re.fullmatch(r"\d+", readings[0]) else None


def _quantity_material_text(frame: np.ndarray, engine: OcrEngine | None) -> str:
    hits = _hits(frame, QUANTITY_MATERIAL_ROI, engine or _quantity_material_ocr)
    lines: list[list[OcrHit]] = []
    for hit in sorted(hits, key=lambda word: (word.bounds[1], word.bounds[0])):
        line = next((row for row in lines if any(
            min(hit.bounds[3], word.bounds[3]) - max(hit.bounds[1], word.bounds[1])
                >= .5 * min(hit.bounds[3] - hit.bounds[1], word.bounds[3] - word.bounds[1])
            for word in row)), None)
        if line is None:
            lines.append([hit])
        else:
            line.append(hit)
    ordered = [hit for row in sorted(lines, key=lambda row: min(word.bounds[1] for word in row))
        for hit in sorted(row, key=lambda word: word.bounds[0])]
    return _text(ordered)


def _native_quantity_one(frame, *, variant, stage, digest, engine):
    heading_hits = _hits(frame, (250, 375, 565, 420), engine)
    heading = _text(sorted((hit for hit in heading_hits if re.search(r"[a-z0-9]", _normalize(hit.text))
        and hit.bounds[2] - hit.bounds[0] >= 20 and hit.bounds[3] - hit.bounds[1] >= 15), key=lambda hit: hit.bounds[0]))
    if heading.replace(" ", "") != "selectquantity":
        return None
    material = _quantity_material_text(frame, engine)
    total_text = _text(_hits(frame, QUANTITY_TOTAL_ROI, engine))
    denominator_text = _text(_hits(frame, QUANTITY_DENOMINATOR_ROI, engine)).replace(" ", "")
    total = re.fullmatch(r"total:\s*(\d{1,3}(?:,\d{3})+|\d+)", total_text)
    denominator = re.fullmatch(r"/(\d+)", denominator_text)
    quantity = _quantity_count(frame)
    details = {"heading": heading, "material_text": material, "total_text": total_text,
        "denominator_text": denominator_text, "observed_quantity": quantity, "resource_authority": False}
    if (re.fullmatch(rf"1\s*(?:\*|star)\s+{variant}\s+enhance\s+material", material) is None
            or total is None or denominator is None or type(quantity) is not int or quantity != 1
            or int(total.group(1).replace(",", "")) != int(denominator.group(1))
            or int(denominator.group(1)) < 1 or _material_stars(frame, (95, 441, 209, 557)) != 1):
        return StageRecognition(stage, False, "QUANTITY_ONE_MATERIAL_FACTS_NOT_PROVEN", digest, diagnostics=details)
    use = [hit for hit in _hits(frame, (330, 785, 470, 835), engine) if _normalize(hit.text) == "use"]
    gold = cv2.inRange(cv2.cvtColor(frame[740:870, 240:560], cv2.COLOR_BGR2HSV),
        np.array((8, 70, 90), np.uint8), np.array((40, 255, 255), np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(gold)
    buttons = [(int(x + 240), int(y + 740), int(x + width + 240), int(y + height + 740))
        for x, y, width, height, area in components[1:]
        if 230 <= width <= 270 and 65 <= height <= 95 and area >= .7 * width * height]
    if (len(use) != 1 or len(buttons) != 1
            or not (buttons[0][0] <= _center(use[0].bounds)[0] < buttons[0][2]
                    and buttons[0][1] <= _center(use[0].bounds)[1] < buttons[0][3])):
        return StageRecognition(stage, False, "QUANTITY_USE_CONTROL_NOT_UNIQUE", digest, diagnostics=details)
    details.update(material_owned=int(denominator.group(1)), use_caption_bounds=use[0].bounds)
    return StageRecognition(stage, True, "QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED", digest,
        material_identity=f"{variant}-material-one-star", quantity=quantity,
        detail_state="quantity_modal", quantity_target=buttons[0],
        close_target=_visible_item_modal_close(frame, (640, 365, 735, 435)), diagnostics=details)


def _material_slash_fragments(labels: np.ndarray, components, *, top: int, left: int, right: int):
    """Keep a real fragmented diagonal glyph; never insert a text separator."""
    pending = [(index, tuple(map(int, value))) for index, value in enumerate(components[1:], 1)
        if 1 <= value[2] <= 3 and 1 <= value[3] <= 7
        and top <= value[1] and value[1] + value[3] <= top + 13
        and left <= value[0] and value[0] + value[2] <= right]
    retained = []
    def adjacent(first, second) -> bool:
        ax, ay, aw, ah, _ = first
        bx, by, bw, bh, _ = second
        return (max(0, max(ax, bx) - min(ax + aw, bx + bw)) <= 1
            and max(0, max(ay, by) - min(ay + ah, by + bh)) <= 1)
    while pending:
        group = [pending.pop(0)]
        while True:
            joined = [fragment for fragment in pending if any(adjacent(fragment[1], member[1]) for member in group)]
            if not joined:
                break
            group.extend(joined)
            pending = [fragment for fragment in pending if fragment not in joined]
        if len(group) < 2:
            continue
        ys, xs = np.nonzero(np.isin(labels, [index for index, _ in group]))
        width, height = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if not (2 <= width <= 6 and 8 <= height <= 13 and abs(int(ys.min()) - top) <= 1):
            continue
        top_x = np.median(xs[ys <= ys.min() + height // 3])
        bottom_x = np.median(xs[ys >= ys.max() - height // 3])
        if 2 <= top_x - bottom_x <= 6:
            retained.extend(group)
    return retained


def _material_label(frame: np.ndarray, cell: NativeBox):
    """Read only the common-baseline white glyph labels, excluding book pixels."""
    import pytesseract
    x0, y0, x1, _y1 = cell
    crop = frame[y0:y0 + 34, x0:x1]
    # Keep neutral antialiased text edges, including the slash, while excluding
    # the brown book artwork that can otherwise join the digit components.
    white = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
        np.array((0, 0, 140), np.uint8), np.array((179, 60, 255), np.uint8))
    _, labels, components, _ = cv2.connectedComponentsWithStats(white)
    candidates = [(index, tuple(map(int, values))) for index, values in enumerate(components[1:], 1)
        if 1 <= values[2] <= 12 and 8 <= values[3] <= 15]
    if len(candidates) < 3:
        return None
    tops = Counter(values[1] for _, values in candidates)
    largest = max(tops.values())
    modes = [top for top, count in tops.items() if count == largest]
    if max(modes) - min(modes) > 1:
        return None
    top = min(modes)
    chosen = [(index, values) for index, values in candidates if abs(values[1] - top) <= 1]
    left = min(values[0] for _, values in chosen)
    right = max(values[0] + values[2] for _, values in chosen)
    chosen.extend(_material_slash_fragments(labels, components, top=top, left=left, right=right))
    mask = np.isin(labels, [index for index, _ in chosen]).astype(np.uint8) * 255
    bottom = max(values[1] + values[3] for _, values in chosen)
    glyph_top = min(values[1] for _, values in chosen)
    glyphs = 255 - mask[glyph_top:bottom, left:right]
    # Preserve the complete glyphs and give both edges the same measured
    # whitespace. An arbitrary trailing scanline can turn a native 9 into 3.
    padding = max(1, round((bottom - glyph_top) * .15))
    glyphs = cv2.copyMakeBorder(glyphs, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=255)
    glyphs = cv2.resize(glyphs, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    glyphs = cv2.copyMakeBorder(glyphs, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    readings = [re.sub(r"\s+", "", _call_ocr(pytesseract.image_to_string, glyphs,
        config=f"--psm {mode} -c tessedit_char_whitelist=0123456789/")) for mode in (8, 13)]
    if readings[0] != readings[1]:
        return None
    match = re.fullmatch(r"(\d+)/(\d+)", readings[0])
    if match is None:
        return None
    selected, owned = map(int, match.groups())
    return ((selected, owned), (x0 + left, y0 + glyph_top, x0 + right, y0 + bottom)) if selected <= owned else None


def _material_fraction(frame: np.ndarray, cell: NativeBox) -> tuple[int, int] | None:
    read = _material_label(frame, cell)
    return read[0] if read is not None else None


def _selected_material_fraction(frame: np.ndarray, label: NativeBox) -> tuple[int, int] | None:
    """Read dim selection text inside its actual zero-selection label bounds.

    The selected card dims both its text and star. The linked baseline supplies
    only the text search bounds; no digit or inventory value is substituted.
    """
    import pytesseract
    x0, y0, x1, y1 = label
    crop = frame[y0 - 2:y1 + 2, x0 - 5:x1 + 3]
    neutral = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
        np.array((0, 0, 90), np.uint8), np.array((179, 30, 150), np.uint8))
    ys, xs = np.nonzero(neutral)
    if not len(xs):
        return None
    neutral = neutral[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
    # The baseline supplies search bounds, not OCR whitespace.
    padding = max(1, round(neutral.shape[0] * .15))
    neutral = cv2.copyMakeBorder(neutral, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=0)
    glyphs = cv2.resize(255 - neutral, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    glyphs = cv2.copyMakeBorder(glyphs, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    readings = [re.sub(r"\s+", "", _call_ocr(pytesseract.image_to_string, glyphs,
        config=f"--psm {mode} -c tessedit_char_whitelist=0123456789/")) for mode in (7, 8, 13)]
    match = re.fullmatch(r"(\d+)/(\d+)", readings[0])
    if match is None:
        return None
    if len(set(readings)) != 1:
        # Preserve agreement and reject any competing valid fraction. Word
        # modes can mistake the slash for a "4" at zero confidence; require a
        # confident complete line before disregarding those non-fractions.
        if any(text != readings[0] and re.fullmatch(r"\d+/\d+", text) for text in readings[1:]):
            return None
        data = _call_ocr(_tesseract_data, glyphs,
            config="--psm 7 -c tessedit_char_whitelist=0123456789/")
        words = []
        confident = True
        for index, raw in enumerate(data.get("text", ())):
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (KeyError, TypeError, ValueError, IndexError):
                return None
            if not math.isfinite(confidence):
                return None
            confident = confident and confidence >= 20
            words.append(text)
        if re.sub(r"\s+", "", "".join(words)) != readings[0]:
            return None
        if not confident:
            # A binary mask can change dim antialiased strokes. Independently
            # retain their original luminance and normalize contrast. All three
            # modes must now agree with the original complete line; a competing
            # valid fraction above still denies, and no baseline digit is used.
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = gray[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            alternate = cv2.copyMakeBorder(255 - gray, padding, padding, padding, padding,
                cv2.BORDER_CONSTANT, value=255)
            alternate = cv2.resize(alternate, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            alternate = cv2.copyMakeBorder(alternate, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
            corroboration = [re.sub(r"\s+", "", _call_ocr(pytesseract.image_to_string, alternate,
                config=f"--psm {mode} -c tessedit_char_whitelist=0123456789/")) for mode in (7, 8, 13)]
            if any(text != readings[0] for text in corroboration):
                return None
    selected, owned = map(int, match.groups())
    return (selected, owned) if selected <= owned else None


def _material_card_translation(before: NativeBox, current: NativeBox) -> tuple[float, float] | None:
    ax0, ay0, ax1, ay1 = before
    bx0, by0, bx1, by1 = current
    if not (0 <= ax0 < ax1 <= NATIVE_WIDTH and 0 <= ay0 < ay1 <= NATIVE_HEIGHT
            and 0 <= bx0 < bx1 <= NATIVE_WIDTH and 0 <= by0 < by1 <= NATIVE_HEIGHT):
        return None
    aw, ah, bw, bh = ax1 - ax0, ay1 - ay0, bx1 - bx0, by1 - by0
    if min(aw, ah, bw, bh) <= 0:
        return None
    dx, dy = (bx0 + bx1 - ax0 - ax1) / 2, (by0 + by1 - ay0 - ay1) / 2
    intersection = max(0, min(ax1, bx1) - max(ax0, bx0)) * max(0, min(ay1, by1) - max(ay0, by0))
    union = aw * ah + bw * bh - intersection
    if (abs(aw - bw) > .1 * aw or abs(ah - bh) > .1 * ah
            or abs(dx) > .1 * min(aw, bw) or abs(dy) > .1 * min(ah, bh)
            or intersection / union < .8):
        return None
    return dx, dy


def _selection_card_translations(before: Sequence[NativeBox], current: Sequence[NativeBox]):
    if not before or len(before) != len(current):
        return None
    translations = []
    for slot, old in enumerate(before):
        matches = [(index, offset) for index, box in enumerate(current)
            if (offset := _material_card_translation(old, box)) is not None]
        if len(matches) != 1 or matches[0][0] != slot:
            return None
        translations.append(matches[0][1])
    return translations


def _material_stars(frame: np.ndarray, cell: NativeBox) -> int | None:
    x0, y0, x1, y1 = cell
    band = frame[y0 + 59:y1, x0:x1]
    gold = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV),
        np.array((15, 110, 160), np.uint8), np.array((40, 255, 255), np.uint8))
    _, labels, components, _ = cv2.connectedComponentsWithStats(gold)
    # Detached pin highlights are much smaller than a star glyph. Keep the
    # actual star components and the existing shape checks; never count glints.
    tiny = [index for index, (_x, _y, width, height, _area) in enumerate(components[1:], 1)
        if width <= 4 and height <= 4]
    if tiny:
        gold[np.isin(labels, tiny)] = 0
    ys, xs = np.nonzero(gold)
    if not len(xs):
        return 0
    left, right, top, bottom = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    width, height = right - left, bottom - top
    if not 15 <= width <= 90 or not 15 <= height <= 30:
        return None
    tips = np.any(gold[top:top + max(2, height // 4), left:right] > 0, axis=0)
    starts = np.flatnonzero(np.diff(np.r_[False, tips, False].astype(np.int8)) == 1)
    ends = np.flatnonzero(np.diff(np.r_[False, tips, False].astype(np.int8)) == -1)
    return len(starts) if 1 <= len(starts) <= 9 and all(1 <= end - start <= 10 for start, end in zip(starts, ends)) else None


def _material_cell_boxes(frame: np.ndarray) -> list[NativeBox]:
    contours, _ = cv2.findContours(cv2.Canny(cv2.cvtColor(frame[590:1060, 45:755], cv2.COLOR_BGR2GRAY), 45, 120),
        cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = sorted({(x + 45, y + 590, x + width + 45, y + height + 590)
        for contour in contours for x, y, width, height in (cv2.boundingRect(contour),)
        if 80 <= width <= 105 and 80 <= height <= 105 and abs(width - height) <= 8},
        key=lambda box: -(box[2] - box[0]) * (box[3] - box[1]))
    cells = []
    for box in candidates:
        if any(max(0, min(box[2], prior[2]) - max(box[0], prior[0])) * max(0, min(box[3], prior[3]) - max(box[1], prior[1]))
                >= .75 * min((box[2] - box[0]) * (box[3] - box[1]), (prior[2] - prior[0]) * (prior[3] - prior[1])) for prior in cells):
            continue
        cells.append(box)
    # A selected border grows by a few pixels. Group by row before sorting x,
    # otherwise the earlier top of that border changes the material slot ID.
    rows: list[list[NativeBox]] = []
    for box in sorted(cells, key=lambda item: (_center(item)[1], item[0])):
        if rows and abs(_center(box)[1] - _center(rows[-1][0])[1]) <= 12:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [box for row in rows for box in sorted(row, key=lambda item: item[0])]


def _material_cells(frame: np.ndarray):
    facts = []
    ordered = _material_cell_boxes(frame)
    for slot, box in enumerate(ordered):
        fraction, stars = _material_fraction(frame, box), _material_stars(frame, box)
        if fraction is None or stars is None:
            return None
        facts.append((slot, stars, *fraction))
    return (tuple(facts), ordered) if facts else None


def _native_material_panel(frame, *, panel, variant, digest, evidence_ref, game_day_id, engine):
    read = _material_cells(frame)
    if read is None:
        return replace(panel, reason="ENHANCEMENT_PANEL_MATERIAL_FACTS_UNKNOWN")
    facts, boxes = read
    one_star = [cell for cell in facts if cell[1] == 1]
    if len(one_star) != 1:
        return replace(panel, reason="ONE_STAR_MATERIAL_NOT_UNIQUE")
    slot, _stars, selected, owned = one_star[0]
    controls = _hits(frame, (440, 1170, 715, 1250), engine)
    confirm = _target(controls, {"confirm"})
    details = dict(panel.diagnostics, material_slot_facts=facts, material_facts_verified=True,
        material_inventory_count=owned, selected_material_quantity=selected)
    if any(cell[2] for cell in facts) or details["exp_display_state"] != "committed":
        return replace(panel, recognized=False, reason="ENHANCEMENT_SELECTED_EXP_PREVIEW_UNVERIFIED",
            material_identity=f"{variant}-material-one-star", material_selected=selected > 0,
            quantity=selected, diagnostics=details)
    details.update(item_exp_current=details["displayed_exp_current"], item_exp_required=details["displayed_exp_required"])
    if confirm is None:
        return replace(panel, reason="ENHANCEMENT_CONFIRM_CONTROL_UNKNOWN", diagnostics=details)
    # A material page alone cannot prove that this item is equipped. A normal
    # consuming route must additionally bind its fresh Unequip-modal entry.
    observation = _make_observation(variant=variant, identity=panel.item_identity,
        item_equipped=False, item_level=panel.item_level, target=confirm,
        material_identity=f"{variant}-material-one-star", material_known=True,
        material_available=owned > 0, material_star=1, material_quantity=selected,
        quantity=selected, result_visible=False, result_identity="", result_associated=False,
        source_frame_sha256=digest, evidence_ref=evidence_ref, game_day_id=game_day_id,
        material_inventory_count=owned, item_exp_current=details["item_exp_current"],
        item_exp_required=details["item_exp_required"], material_slot_facts=facts)
    other_selected = any(cell[2] for cell in facts if cell[0] != slot)
    return replace(panel, reason="ENHANCEMENT_MATERIAL_FACTS_OBSERVED", material_identity=f"{variant}-material-one-star",
        material_selected=selected > 0, material_target=boxes[slot] if not other_selected and owned > 0 else None,
        quantity=selected, observation=observation, diagnostics=details)


def _selected_card_checked(frame: np.ndarray, box: NativeBox) -> bool:
    x0, y0, x1, y1 = box
    crop = frame[y0 + 23:y1 - 30, x0 + 8:x1 - 8]
    gold = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
        np.array((15, 100, 160), np.uint8), np.array((40, 255, 255), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(gold)
    return sum(30 <= width <= 55 and 20 <= height <= 36 and area >= 180
        for _x, _y, width, height, area in stats[1:]) == 1


@_bounded_recognition()
def recognize_selection_context(
    current: CapturedNativeFrame, *, modal: CapturedNativeFrame,
    baseline: CapturedNativeFrame, quantity: CapturedNativeFrame,
    variant: str, game_day_id: str, ocr_engine: OcrEngine | None = None,
) -> StageRecognition:
    """Replay four current-run witnesses; this function never dispatches input.

    The caller also binds the source/target/order of the three navigation
    dispatches. A page, caller flag, or historical item name is not equipment or
    selection authority. Selected green EXP is retained only as a preview.
    """
    digest = getattr(current, "sha256", "")
    def rejected(reason: str) -> StageRecognition:
        return StageRecognition("material", False, reason, digest)
    if variant not in SUPPORTED_VARIANTS or not game_day_id:
        return rejected("SELECTION_CONTEXT_IDENTITY_UNKNOWN")
    frames = (modal, baseline, quantity, current)
    for capture in frames:
        if (not isinstance(capture, CapturedNativeFrame)
                or not isinstance(capture.png, bytes) or not isinstance(capture.frame, np.ndarray)
                or not isinstance(capture.path, Path)
                or hashlib.sha256(capture.png).hexdigest() != capture.sha256
                or capture.frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH)
                or type(capture.captured_monotonic) not in (int, float)
                or not math.isfinite(capture.captured_monotonic)
                or not np.array_equal(cv2.imdecode(np.frombuffer(capture.png, np.uint8), cv2.IMREAD_COLOR), capture.frame)):
            return rejected("SELECTION_CONTEXT_NATIVE_SOURCE_INVALID")
    if (len({str(frame.path) for frame in frames}) != 4
            or any(frame.path.parent != current.path.parent for frame in frames)
            or any(first.captured_monotonic >= second.captured_monotonic for first, second in zip(frames, frames[1:]))):
        return rejected("SELECTION_CONTEXT_SESSION_OR_ORDER_INVALID")
    item = recognize_commander_stage(modal.frame, variant=variant, stage="item",
        source_frame_sha256=modal.sha256, evidence_ref=modal.path, game_day_id=game_day_id, ocr_engine=ocr_engine)
    if (not item.recognized or item.detail_state != "item_modal" or item.open_target is None
            or not item.diagnostics.get("footer_controls", {}).get("unequip")):
        return rejected("SELECTION_CONTEXT_EQUIPPED_MODAL_UNPROVEN")
    zero = recognize_commander_stage(baseline.frame, variant=variant, stage="material",
        source_frame_sha256=baseline.sha256, evidence_ref=baseline.path, game_day_id=game_day_id, ocr_engine=ocr_engine)
    before = zero.observation
    if (not zero.recognized or before is None or zero.quantity != 0 or zero.material_selected
            or before.item_equipped or zero.diagnostics.get("exp_display_state") != "committed"
            or any(cell[2] for cell in before.material_slot_facts)
            or (item.item_identity, item.item_level) != (zero.item_identity, zero.item_level)):
        return rejected("SELECTION_CONTEXT_ZERO_BASELINE_UNPROVEN")
    choice = recognize_commander_stage(quantity.frame, variant=variant, stage="material",
        source_frame_sha256=quantity.sha256, evidence_ref=quantity.path, game_day_id=game_day_id, ocr_engine=ocr_engine)
    if (not choice.recognized or choice.reason != "QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED"
            or choice.quantity != 1 or choice.quantity_target is None
            or choice.material_identity != before.material_identity
            or choice.diagnostics.get("material_owned") != before.material_inventory_count):
        return rejected("SELECTION_CONTEXT_QUANTITY_UNPROVEN")
    panel = _native_enhancement_panel(current.frame, variant=variant, stage="material", digest=digest, engine=ocr_engine)
    if (panel is None or not panel.recognized
            or (panel.item_identity, panel.item_level) != (zero.item_identity, zero.item_level)
            or panel.diagnostics.get("exp_display_state") != "preview"
            or panel.diagnostics["displayed_exp_required"] != before.item_exp_required
            or panel.diagnostics["displayed_exp_current"] <= before.item_exp_current):
        return rejected("SELECTION_CONTEXT_PREVIEW_UNPROVEN")
    old_boxes, boxes = _material_cell_boxes(baseline.frame), _material_cell_boxes(current.frame)
    translations = _selection_card_translations(old_boxes, boxes)
    if translations is None or len(old_boxes) != len(before.material_slot_facts):
        return rejected("SELECTION_CONTEXT_CARD_LAYOUT_CHANGED")
    facts = []
    for (slot, stars, _selected, owned), old_box, box, (dx, dy) in zip(before.material_slot_facts, old_boxes, boxes, translations):
        if stars == 1:
            label = _material_label(baseline.frame, old_box)
            shifted = tuple(value + int(round(dx if index % 2 == 0 else dy)) for index, value in enumerate(label[1])) if label is not None else None
            if (shifted is None or not (box[0] <= shifted[0] - 5 < shifted[2] + 3 <= box[2]
                    and box[1] <= shifted[1] - 2 < shifted[3] + 2 <= box[3]
                    and 0 <= shifted[0] - 5 and shifted[2] + 3 <= NATIVE_WIDTH
                    and 0 <= shifted[1] - 2 and shifted[3] + 2 <= NATIVE_HEIGHT)):
                return rejected("SELECTION_CONTEXT_LABEL_OUTSIDE_CARD")
            fraction = _selected_material_fraction(current.frame, shifted)
            # The selected glyph is dimmed/overlaid. Its one-star identity comes
            # from this exact baseline card and the strict quantity witness.
            if fraction != (1, owned) or not _selected_card_checked(current.frame, box):
                return rejected("SELECTION_CONTEXT_SELECTED_CARD_UNPROVEN")
        else:
            fraction = _material_fraction(current.frame, box)
            if fraction != (0, owned) or _material_stars(current.frame, box) != stars:
                return rejected("SELECTION_CONTEXT_OTHER_MATERIAL_CHANGED")
        facts.append((slot, stars, *fraction))
    confirm = _target(_hits(current.frame, (440, 1170, 715, 1250), ocr_engine), {"confirm"})
    if confirm is None:
        return rejected("SELECTION_CONTEXT_CONFIRM_NOT_UNIQUE")
    observation = replace(before, item_equipped=True, target_roi=confirm, quantity=1, material_quantity=1,
        source_frame_sha256=digest, evidence_refs=tuple(str(frame.path) for frame in (current, modal, baseline, quantity)),
        material_slot_facts=tuple(facts), item_exp_preview=panel.diagnostics["displayed_exp_current"],
        selection_baseline_frame_sha256=baseline.sha256, selection_baseline_evidence_ref=str(baseline.path))
    return replace(panel, reason="ENHANCEMENT_SELECTION_CONTEXT_VERIFIED", material_identity=before.material_identity,
        material_selected=True, quantity=1, observation=observation,
        diagnostics={**panel.diagnostics, "material_slot_facts": tuple(facts),
            "equipped_modal_frame_sha256": modal.sha256, "selection_baseline_frame_sha256": baseline.sha256,
            "quantity_frame_sha256": quantity.sha256, "item_exp_current": before.item_exp_current,
            "item_exp_preview": observation.item_exp_preview, "resource_authority": False,
            "card_translations": tuple(translations),
            "selection_context_targets": {"modal_enhance": item.open_target,
                "baseline_card": zero.material_target, "quantity_use": choice.quantity_target}})


@_bounded_recognition()
def recognize_commander_stage(
    frame: np.ndarray,
    *,
    variant: str,
    stage: str,
    source_frame_sha256: str | None = None,
    evidence_ref: str | Path | None = None,
    ocr_engine: OcrEngine | None = None,
    game_day_id: str = "",
) -> StageRecognition:
    if isinstance(frame, CapturedNativeFrame):
        frame = frame.frame
    digest = _digest(frame, source_frame_sha256)
    if frame is None or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return StageRecognition(stage, False, "NON_NATIVE_FRAME", digest)
    variant = str(variant).strip().lower()
    if variant not in SUPPORTED_VARIANTS:
        return StageRecognition(stage, False, "UNSUPPORTED_VARIANT", digest)
    if stage not in {"tab", "item", "material", "post"}:
        return StageRecognition(stage, False, "UNSUPPORTED_STAGE", digest)
    if stage == "item" and variant == "gear":
        modal = _gear_item_modal(frame, digest, ocr_engine)
        if modal is not None:
            return modal
    if stage == "item" and variant in {"chip", "module"}:
        modal = _stat_item_modal(frame, digest, ocr_engine, variant=variant)
        if modal is not None:
            return modal
    if stage in {"material", "post"}:
        quantity = _native_quantity_one(frame, variant=variant, stage=stage, digest=digest, engine=ocr_engine)
        if quantity is not None:
            return replace(quantity, recognized=False) if stage == "post" else quantity
        panel = _native_enhancement_panel(frame, variant=variant, stage=stage, digest=digest, engine=ocr_engine)
        if panel is not None:
            if not panel.recognized:
                return panel
            result = _native_material_panel(frame, panel=panel, variant=variant, digest=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id, engine=ocr_engine)
            return replace(result, recognized=False) if stage == "post" and result.observation is None else result

    header = _hits(frame, COMMANDER_HEADER_ROI, ocr_engine)
    categories = _hits(frame, CATEGORY_SEARCH_ROI, ocr_engine)
    tab_context = _hits(frame, COMMANDER_TAB_CONTEXT_ROI, ocr_engine)
    categories = _unique_hits([*categories, *tab_context])
    items = _hits(frame, ITEM_SEARCH_ROI, ocr_engine)
    materials = _hits(frame, MATERIAL_SEARCH_ROI, ocr_engine)
    controls = _hits(frame, CONTROL_SEARCH_ROI, ocr_engine)
    visual_selected = _classify_selected_category_visual(frame)
    if not _commander_header_recognized(header, categories, visual_selected):
        return StageRecognition(stage, False, "COMMANDER_INFO_NOT_RECOGNIZED", digest)

    category_hits = [
        hit for hit in categories
        if _center(hit.bounds)[1] < 260
        if any(re.search(rf"\b{re.escape(name)}\b", _normalize(hit.text)) for name in SUPPORTED_VARIANTS)
    ]
    requested = [
        hit for hit in category_hits
        if re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    if visual_selected is not None and requested:
        requested = [requested[0]]
    elif visual_selected is not None:
        requested = [OcrHit(variant, CATEGORY_TAB_BOXES[variant], 1.0)]
    if len(requested) != 1:
        return StageRecognition(stage, False, "CATEGORY_LABEL_NOT_UNIQUE", digest)
    requested_hit = requested[0]
    wrong_selected = [
        hit for hit in categories
        if _is_marker(hit)
        and hit is not requested_hit
        and any(re.search(rf"\b{re.escape(name)}\b", _normalize(hit.text)) for name in SUPPORTED_VARIANTS)
        and not re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    if stage != "tab" and wrong_selected:
        return StageRecognition(stage, False, "CATEGORY_CONFLICT", digest)
    category_markers = [
        hit for hit in categories
        if _is_marker(hit) and _associated(hit, requested_hit, y_slack=55, x_slack=65)
    ]
    if stage == "tab":
        marker_bindings = [
            [
                category for category in categories
                if not _is_marker(category)
                and _associated(marker, category, y_slack=55, x_slack=65)
            ]
            for marker in categories if _is_marker(marker)
        ]
        if any(len(binding) != 1 for binding in marker_bindings):
            return StageRecognition(stage, False, "CATEGORY_SELECTION_AMBIGUOUS", digest)
        return StageRecognition(
            stage,
            True,
            "REQUESTED_TAB_RECOGNIZED",
            digest,
            category_selected=(
                len(category_markers) == 1 or visual_selected == variant
            ),
            category_target=_expand(requested_hit.bounds),
            diagnostics={"visual_selected_tab": visual_selected or ""},
            detail_state="commander_overview", back_target=_visible_back(frame),
        )
    if len(category_markers) > 1:
        return StageRecognition(stage, False, "CATEGORY_SELECTION_AMBIGUOUS", digest)
    category_selected = len(category_markers) == 1 or visual_selected == variant
    category_target = _expand(requested_hit.bounds)

    if (
        stage == "item"
        and variant in {"chip", "module"}
        and category_selected
        and _commander_tab_context_sufficient(categories)
    ):
        overview = _icon_overview_binding(items, variant, frame)
        if overview is not None:
            overview_identity, overview_level, overview_target = overview
            return StageRecognition(
                stage,
                True,
                "ICON_OVERVIEW_ITEM_RECOGNIZED",
                digest,
                item_identity=overview_identity,
                category_selected=True,
                category_target=category_target,
                item_target=overview_target,
                item_level=overview_level,
                diagnostics={
                    "binding_mode": "icon_overview",
                    "level_marker": overview_level,
                    "visual_selected_tab": visual_selected or "",
                },
            )

    item_text = _text(items)
    all_text = " ".join((_text(header), _text(categories), item_text, _text(materials), _text(controls)))
    forbidden = sorted(action for action in FORBIDDEN_ACTIONS if action in all_text)
    if forbidden:
        return StageRecognition(stage, False, "FORBIDDEN_ACTION_MODE", digest, diagnostics={"actions": forbidden})
    if any(marker in all_text for marker in PREMIUM_MARKERS):
        return StageRecognition(stage, False, "PREMIUM_CURRENCY_FORBIDDEN", digest)

    identity, item_hit, item_error = _item_identity(items, variant)
    equipped_hits = [
        hit for hit in items
        if _normalize(hit.text) == "equipped" and _associated(hit, item_hit, y_slack=500)
    ] if item_hit is not None else []
    if (
        stage == "item"
        and category_selected
        and _commander_tab_context_sufficient(categories)
        and item_hit is None
        and not equipped_hits
        and not _identity_syntax_present(items)
    ):
        overview = _icon_overview_binding(items, variant, frame)
        if overview is not None:
            overview_identity, overview_level, overview_target = overview
            return StageRecognition(
                stage=stage,
                recognized=True,
                reason="COMMANDER_INFO_ICON_OVERVIEW_RECOGNIZED",
                frame_sha256=digest,
                item_identity=overview_identity,
                category_selected=True,
                category_target=category_target,
                item_target=overview_target,
                item_level=overview_level,
                diagnostics={
                    "binding_mode": "icon_overview",
                    "level_marker": overview_level,
                    "visual_selected_tab": visual_selected or "",
                },
            )
    if item_error or item_hit is None:
        return StageRecognition(stage, False, item_error or "ITEM_IDENTITY_UNKNOWN", digest)
    if any(
        name != variant and re.search(rf"\b{re.escape(name)}\b", item_text)
        for name in SUPPORTED_VARIANTS
    ):
        return StageRecognition(stage, False, "ITEM_CATEGORY_CONFLICT", digest)
    if len(equipped_hits) != 1:
        return StageRecognition(stage, False, "EQUIPPED_ITEM_NOT_PROVEN", digest)
    item_target = _expand(item_hit.bounds)
    item_level = _level(item_text) or 0

    open_target = _target(controls, {"enhance"})
    use_target = _target(controls, {"use"})

    if stage == "item":
        if open_target is None:
            return StageRecognition(
                stage, False, "OPEN_ENHANCE_NOT_RECOGNIZED", digest,
                identity, category_selected, category_target, item_target,
            )
        observation = _make_observation(
            variant=variant, identity=identity, item_equipped=True, item_level=item_level,
            target=None, material_identity="", material_known=False, material_available=False,
            material_star=None, material_quantity=None, quantity=None, result_visible=False,
            result_identity="", result_associated=False, source_frame_sha256=digest,
            evidence_ref=evidence_ref, game_day_id=game_day_id,
        )
        return StageRecognition(
            stage, True, "COMMANDER_INFO_ITEM_RECOGNIZED", digest, identity,
            category_selected, category_target, item_target, open_target,
            observation=observation,
        )

    expected_material = f"{variant}-material-one-star"
    material_hits = [
        hit for hit in materials
        if expected_material in _normalize(hit.text).replace(" ", "-")
    ]
    if len(material_hits) > 1:
        return StageRecognition(
            stage, False, "CATEGORY_MATERIAL_NOT_UNIQUE", digest, identity,
            category_selected, category_target, item_target,
        )
    material_hit = material_hits[0] if material_hits else None
    material_identity = expected_material if material_hit else ""
    material_text = _text(materials)
    material_star = _star(material_text) if material_hit else None
    quantity = _quantity(material_text)
    quantity_hits = [
        hit for hit in materials
        if re.search(r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*1\b|\bx\s*1\b", _normalize(hit.text))
    ]
    quantity_target = _expand(quantity_hits[0].bounds) if len(quantity_hits) == 1 else None
    material_target = _expand(material_hit.bounds) if material_hit else None
    material_markers = [hit for hit in materials if _is_marker(hit)]
    material_selected = bool(
        material_hit and any(_associated(marker, material_hit) for marker in material_markers)
    )
    result_hits = [
        hit for hit in items
        if any(word in _normalize(hit.text) for word in ("result", "enhanced", "success"))
    ]
    result_identities: list[str] = []
    result_identity_hits: list[OcrHit] = []
    for hit in result_hits:
        match = re.search(r"(?:result|item)\s*[:#-]\s*(.+)", _normalize(hit.text))
        if match:
            result_identities.append(match.group(1).replace(" ", "-"))
            result_identity_hits.append(hit)
    unique_result_identities = set(result_identities)
    if len(unique_result_identities) > 1:
        return StageRecognition(stage, False, "RESULT_IDENTITY_CONFLICT", digest)
    if result_hits and not result_identities:
        return StageRecognition(stage, False, "RESULT_IDENTITY_UNKNOWN", digest)
    if unique_result_identities and next(iter(unique_result_identities)) != identity:
        return StageRecognition(stage, False, "RESULT_IDENTITY_CONFLICT", digest)
    if stage == "post" and len(result_identity_hits) > 1:
        return StageRecognition(stage, False, "RESULT_IDENTITY_NOT_UNIQUE", digest)
    result_identity = next(iter(unique_result_identities), "")
    result_associated = bool(
        any(_associated(result_hit, item_hit) for result_hit in result_hits)
    )
    if stage == "post" and result_identity and not result_associated:
        return StageRecognition(stage, False, "RESULT_IDENTITY_NOT_ASSOCIATED", digest)

    if stage != "post":
        if material_hit is None:
            return StageRecognition(
                stage, False, "MATERIAL_IDENTITY_UNKNOWN", digest, identity,
                category_selected, category_target, item_target,
            )
        if material_star != 1:
            return StageRecognition(
                stage, False, "MATERIAL_MUST_BE_EXACTLY_ONE_STAR", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity,
            )
        if quantity != 1 or quantity_target is None:
            return StageRecognition(
                stage, False, "MATERIAL_QUANTITY_MUST_BE_EXACTLY_ONE", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity, material_target=material_target,
                quantity=quantity,
            )
        if not material_selected:
            observation = _make_observation(
                variant=variant, identity=identity, item_equipped=True, item_level=item_level,
                target=None, material_identity=material_identity, material_known=True,
                material_available=True, material_star=material_star,
                material_quantity=quantity, quantity=quantity, result_visible=False,
                result_identity="", result_associated=False, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "MATERIAL_NOT_SELECTED", digest, identity, category_selected,
                category_target, item_target, material_identity=material_identity,
                material_selected=False, material_target=material_target, quantity=quantity,
                quantity_target=quantity_target, observation=observation,
            )
        if use_target is None:
            return StageRecognition(
                stage, False, "USE_CONTROL_NOT_RECOGNIZED", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity, material_selected=True,
                material_target=material_target, quantity=quantity,
                quantity_target=quantity_target,
            )

    observation = _make_observation(
        variant=variant, identity=identity, item_equipped=True, item_level=item_level,
        target=use_target, material_identity=material_identity, material_known=material_hit is not None,
        material_available=material_hit is not None, material_star=material_star,
        material_quantity=quantity, quantity=quantity, result_visible=bool(result_hits),
        result_identity=result_identity, result_associated=result_associated,
        source_frame_sha256=digest, evidence_ref=evidence_ref, game_day_id=game_day_id,
    )
    return StageRecognition(
        stage, True, "SUCCESSOR_RECOGNIZED" if stage == "post" else "FINAL_USE_RECOGNIZED",
        digest, identity, category_selected, category_target, item_target,
        material_identity=material_identity, material_selected=material_selected,
        material_target=material_target, quantity=quantity, quantity_target=quantity_target,
        observation=observation,
        diagnostics={"result_spatially_associated": result_associated},
    )


def _as_observation(value: EnhancementObservation | None) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _stage_record(stage: str, capture: CapturedNativeFrame, recognition: Any) -> dict[str, Any]:
    return {
        "kind": "recognition",
        "stage": stage,
        "frame_sha256": capture.sha256,
        "recognized": bool(getattr(recognition, "recognized", False)),
        "reason": getattr(recognition, "reason", "unknown"),
        "target_roi": getattr(recognition, "portrait_target", None)
        or getattr(recognition, "open_target", None)
        or getattr(recognition, "material_target", None),
        "category_target": getattr(recognition, "category_target", None),
        "item_target": getattr(recognition, "item_target", None),
        "material_target": getattr(recognition, "material_target", None),
        "quantity_target": getattr(recognition, "quantity_target", None),
        "item_identity": getattr(recognition, "item_identity", ""),
        "item_level": getattr(recognition, "item_level", 0),
        "detail_state": getattr(recognition, "detail_state", None),
        "close_target": getattr(recognition, "close_target", None),
        "back_target": getattr(recognition, "back_target", None),
        "diagnostics": dict(getattr(recognition, "diagnostics", {}) or {}),
    }


class _SessionNativeDispatch:
    """Marker keeping native runtime authorization inside DevelopmentSession."""

    def __init__(self, callback: Callable[[CapturedNativeFrame], None]) -> None:
        self._callback = callback

    def _authorize_dispatch(self) -> None:
        return None

    def dispatch(self, source: CapturedNativeFrame) -> None:
        self._callback(source)


class _FlowBlocked(RuntimeError):
    pass


class EnhancementIntegratedRoute:
    def __init__(
        self,
        runtime: Any,
        *,
        variant: str,
        reset_identity: str,
        session: Any | None = None,
        ocr_engine: OcrEngine | None = None,
        variants: Sequence[str] | None = None,
        completed_categories: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.variant = str(variant).strip().lower()
        self.reset_identity = str(reset_identity).strip()
        self.session = session
        self.ocr_engine = ocr_engine
        self.variants = tuple(variants) if variants is not None else (self.variant,)
        self.completed_categories = {
            str(key): dict(value) for key, value in (completed_categories or {}).items()
        }
        self.stages: list[dict[str, Any]] = []
        self.final_dispatch_key: str | None = None
        self.resource_dispatch_keys: list[str] = [
            str(value["resource_affecting_action_key"])
            for value in self.completed_categories.values()
            if value.get("resource_affecting_action_key")
        ]
        self.final_dispatch_key = self.resource_dispatch_keys[-1] if self.resource_dispatch_keys else None
        self.category_results: list[dict[str, Any]] = []
        self._last_before: tuple[CapturedNativeFrame, Any] | None = None
        self._last_after: tuple[CapturedNativeFrame, Any] | None = None
        self._selection_witnesses: dict[str, CapturedNativeFrame] = {}

    def _observe(self, label: str) -> CapturedNativeFrame:
        if self.session is None or not callable(getattr(self.session, "observe", None)):
            raise RuntimeError("enhancement route requires DevelopmentSession.observe")
        return self.session.observe(self.runtime.capture, label=label)

    def _record(self, label: str, capture: CapturedNativeFrame, recognition: Any) -> None:
        record = _stage_record(label, capture, recognition)
        record["variant"] = self.variant
        self.stages.append(record)

    def _action(
        self,
        *,
        label: str,
        identity: str,
        before_recognizer: Callable[[CapturedNativeFrame], Any],
        post_recognizer: Callable[[CapturedNativeFrame], Any],
        target_getter: Callable[[Any], NativeBox | None] | None = None,
        before_guard: Callable[[Any], bool] | None = None,
        resource_affecting: bool = False,
        settle_polls: int = 1,
    ) -> tuple[CapturedNativeFrame, Any]:
        if type(settle_polls) is not int or not 1 <= settle_polls <= MAX_SETTLE_POLLS:
            raise ValueError("enhancement successor polls must be bounded")
        if self.session is None or not callable(getattr(self.session, "run_action", None)):
            raise RuntimeError("enhancement route requires the pnsctl-owned DevelopmentSession")
        before_state: dict[str, Any] = {}
        after_state: dict[str, Any] = {}
        dispatch_state: dict[str, Any] = {}
        action_key = f"enhancement:{self.variant}:{identity}:{_stamp()}"

        def capture(capture_label: str) -> CapturedNativeFrame:
            return self.runtime.capture(capture_label)

        def authorize(before: CapturedNativeFrame) -> None:
            recognition = before_recognizer(before)
            before_state.update(frame=before, recognition=recognition)
            self._record(f"{label}-immediate-before", before, recognition)
            if not getattr(recognition, "recognized", False):
                raise _FlowBlocked(
                    f"{identity} immediate-before recognition failed: {getattr(recognition, 'reason', 'unknown')}"
                )
            if before_guard is not None and not before_guard(recognition):
                raise _FlowBlocked(f"{identity} immediate-before authorization failed")
            target = target_getter(recognition) if target_getter else None
            if target is None:
                raise _FlowBlocked(f"{identity} immediate-before target is missing")
            dispatch_state["target"] = target

        def dispatch(before: CapturedNativeFrame) -> None:
            target = dispatch_state.get("target")
            self.runtime.tap(before, target_identity=identity, target_roi=target,
                action_key=action_key, action_class="navigation", consequential=False)
            self.stages.append(
                {
                    "kind": "dispatch",
                    "stage": f"dispatch:{identity}",
                    "frame_sha256": before.sha256,
                    "target_identity": identity,
                    "target_roi": target,
                    "resource_affecting": resource_affecting,
                    "consequential": False,
                    "action_key": action_key,
                }
            )
            if resource_affecting:
                self.final_dispatch_key = action_key
                self.resource_dispatch_keys.append(action_key)
                event = getattr(self.runtime, "_event", None)
                if callable(event):
                    event(
                        "dispatch_classification",
                        {
                            "action_key": action_key,
                            "action_class": "resource_affecting_confirmation",
                            "resource_affecting": True,
                            "consequential": False,
                        },
                    )

        after_phase = "immediate-post"

        def recognize(after: CapturedNativeFrame) -> str:
            recognition = post_recognizer(after)
            after_state.update(frame=after, recognition=recognition)
            self._record(f"{label}-{after_phase}", after, recognition)
            return "recognized" if getattr(recognition, "recognized", False) else "unknown"

        def settled_successor() -> CapturedNativeFrame:
            nonlocal after_phase
            for poll in range(1, settle_polls + 1):
                time.sleep(SETTLED_SUCCESSOR_DELAY_SECONDS)
                after_phase = "settled" if settle_polls == 1 else f"settled-{poll}"
                candidate = self._observe(f"{label}-{after_phase}")
                if poll == settle_polls:
                    return candidate
                recognition = post_recognizer(candidate)
                if getattr(recognition, "recognized", False):
                    return candidate
                self._record(f"{label}-{after_phase}", candidate, recognition)
            raise AssertionError("bounded enhancement successor did not observe")

        self.session.run_action(
            action_class="navigation",
            label=label,
            capture=capture,
            authorize=authorize,
            dispatch=_SessionNativeDispatch(dispatch).dispatch,
            recognize=recognize,
            target_roi=None,
            consequence_class="ordinary_development" if resource_affecting else "navigation_only",
            settled_successor=None if resource_affecting else settled_successor,
        )
        self._last_before = (before_state["frame"], before_state["recognition"])
        self._last_after = (after_state["frame"], after_state["recognition"])
        if not resource_affecting and callable(getattr(self.runtime, "reconcile", None)):
            self.runtime.reconcile(action_key,
                "confirmed" if getattr(after_state["recognition"], "recognized", False) else "unresolved",
                after_state["frame"], getattr(after_state["recognition"], "reason", "unknown"))
        if not getattr(after_state["recognition"], "recognized", False):
            if resource_affecting:
                return after_state["frame"], after_state["recognition"]
            raise _FlowBlocked(
                f"{identity} successor recognition failed: {getattr(after_state['recognition'], 'reason', 'unknown')}"
            )
        return after_state["frame"], after_state["recognition"]

    def _selected_item_detail(self, frame: CapturedNativeFrame) -> StageRecognition:
        result = recognize_commander_stage(
            frame, variant=self.variant, stage="item", source_frame_sha256=frame.sha256,
            evidence_ref=frame.path, ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
        )
        if result.recognized and (not result.category_selected or result.open_target is None):
            return replace(result, recognized=False, reason="SELECTED_ITEM_DETAIL_NOT_OPEN")
        return result

    def _selected_category_item(self, frame: CapturedNativeFrame) -> StageRecognition:
        result = recognize_commander_stage(frame, variant=self.variant, stage="item",
            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity)
        if result.recognized and not result.category_selected:
            return replace(result, recognized=False, reason="REQUESTED_CATEGORY_SUCCESSOR_NOT_PROVEN")
        return result

    def _selection_source(self, frame: CapturedNativeFrame, kind: str) -> StageRecognition:
        result = recognize_commander_stage(frame.frame, variant=self.variant,
            stage="item" if kind == "modal" else "material", source_frame_sha256=frame.sha256,
            evidence_ref=frame.path, ocr_engine=self.ocr_engine, game_day_id=self.reset_identity)
        if kind == "modal":
            valid = (result.detail_state == "item_modal" and result.open_target is not None
                and bool(result.diagnostics.get("footer_controls", {}).get("unequip")))
        elif kind == "baseline":
            valid = (result.observation is not None and result.quantity == 0 and not result.material_selected
                and result.diagnostics.get("exp_display_state") == "committed")
        elif kind == "quantity":
            valid = result.reason == "QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED" and result.quantity_target is not None
        else:
            raise ValueError("unsupported enhancement selection witness")
        valid = result.recognized and valid
        if not valid:
            return replace(result, recognized=False, reason=f"CURRENT_RUN_{kind.upper()}_WITNESS_UNPROVEN")
        self._selection_witnesses[kind] = frame
        return result

    def _selected_material(self, frame: CapturedNativeFrame) -> StageRecognition:
        if set(self._selection_witnesses) != {"modal", "baseline", "quantity"}:
            return StageRecognition("material", False, "CURRENT_RUN_SELECTION_CONTEXT_REQUIRED", frame.sha256)
        frames_parent = Path(self.runtime.session) / "frames"
        if any(capture.path.parent != frames_parent for capture in (frame, *self._selection_witnesses.values())):
            return StageRecognition("material", False, "CURRENT_RUN_SELECTION_SESSION_MISMATCH", frame.sha256)
        result = recognize_selection_context(frame, variant=self.variant, game_day_id=self.reset_identity,
            modal=self._selection_witnesses["modal"], baseline=self._selection_witnesses["baseline"],
            quantity=self._selection_witnesses["quantity"], ocr_engine=self.ocr_engine)
        if not result.recognized:
            return result
        targets = result.diagnostics["selection_context_targets"]
        expected = ((f"open-enhance:{self.variant}", "modal", "modal_enhance"),
            (f"material-select:{self.variant}", "baseline", "baseline_card"),
            ("quantity-use", "quantity", "quantity_use"))
        dispatches = [row for row in self.stages if row.get("kind") == "dispatch"][-3:]
        if len(dispatches) != 3 or any(
                row.get("target_identity") != identity
                or row.get("frame_sha256") != self._selection_witnesses[kind].sha256
                or row.get("target_roi") != targets[target]
                or row.get("resource_affecting") is not False
                for row, (identity, kind, target) in zip(dispatches, expected)):
            return replace(result, recognized=False, observation=None, reason="CURRENT_RUN_SELECTION_DISPATCH_CHAIN_UNPROVEN")
        return result

    def _navigation_state(self, frame: CapturedNativeFrame, *, allow_post: bool) -> StageRecognition:
        home = recognize_home_frame(frame.frame, source_frame_sha256=frame.sha256, ocr_engine=self.ocr_engine)
        if home.recognized:
            return StageRecognition("navigation", True, home.reason, frame.sha256, detail_state="home")
        item = recognize_commander_stage(frame.frame, variant=self.variant, stage="item",
            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity)
        if item.recognized and item.detail_state == "item_modal":
            return item
        quantity = _native_quantity_one(frame.frame, variant=self.variant, stage="navigation",
            digest=frame.sha256, engine=self.ocr_engine)
        if quantity is not None:
            if quantity.recognized and quantity.close_target is None:
                return replace(quantity, recognized=False, reason="QUANTITY_EXIT_CONTROL_NOT_BOUND")
            return quantity
        panel = _native_enhancement_panel(frame.frame, variant=self.variant, stage="navigation",
            digest=frame.sha256, engine=self.ocr_engine)
        if panel is not None:
            return panel
        if allow_post:
            post = recognize_commander_stage(frame.frame, variant=self.variant, stage="post",
                source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity)
            if post.recognized:
                return replace(post, detail_state="enhancement_post", back_target=_visible_back(frame.frame))
        commander = recognize_commander_stage(frame.frame, variant=self.variant, stage="tab",
            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity)
        if commander.recognized:
            return commander
        return StageRecognition("navigation", False, "ENHANCEMENT_EXIT_SOURCE_UNKNOWN", frame.sha256)

    def _navigate_to(
        self, destination: str, *, allow_post: bool = False,
        source_frame: CapturedNativeFrame | None = None,
    ) -> tuple[CapturedNativeFrame, StageRecognition]:
        """Only measured exits, with progress after each input and no repeated tap."""
        if destination not in {"commander_overview", "home"}:
            raise ValueError("enhancement navigation destination is unsupported")
        label = "return-home" if destination == "home" else "commander-return"
        current = source_frame or self._observe(f"{label}-source")
        limit = 3 if destination == "home" else 2
        transitions = {"item_modal": {"commander_overview"}, "quantity_modal": {"enhancement_panel"},
            "enhancement_post": {"item_modal", "commander_overview"},
            "enhancement_panel": {"item_modal", "commander_overview"}, "commander_overview": {"home"}}
        for step in range(limit + 1):
            observed = self._navigation_state(current, allow_post=allow_post)
            self._record(f"{label}-source-{step}", current, observed)
            if observed.recognized and observed.detail_state == destination:
                return current, observed
            state = observed.detail_state
            modal = state in {"item_modal", "quantity_modal"}
            target = observed.close_target if modal else observed.back_target
            if step == limit or not observed.recognized or target is None or state not in transitions:
                raise _FlowBlocked("ENHANCEMENT_VISIBLE_EXIT_NOT_BOUND")

            def before(frame):
                bound = self._navigation_state(frame, allow_post=allow_post)
                return bound if bound.detail_state == state else replace(bound, recognized=False, reason="ENHANCEMENT_EXIT_SOURCE_CHANGED")

            def after(frame):
                bound = self._navigation_state(frame, allow_post=allow_post)
                return bound if bound.detail_state in transitions[state] else replace(bound, recognized=False, reason="ENHANCEMENT_EXIT_SUCCESSOR_UNKNOWN")

            current, _ = self._action(label=f"{label}-{step + 1}",
                identity="quantity-modal-close" if state == "quantity_modal" else "item-detail-close" if state == "item_modal" else "commander-visible-back" if state == "commander_overview" else "enhancement-visible-back",
                before_recognizer=before, post_recognizer=after,
                target_getter=lambda recognition: recognition.close_target if modal else recognition.back_target,
                settle_polls=MAX_SETTLE_POLLS)
        raise _FlowBlocked("ENHANCEMENT_VISIBLE_EXIT_LIMIT_REACHED")

    def _result(
        self,
        *,
        status: str,
        reason: str,
        source: CapturedNativeFrame,
        before: StageRecognition | None = None,
        post: StageRecognition | None = None,
        terminal: CapturedNativeFrame | None = None,
        terminal_recognized: bool = False,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "flow_id": FLOW_ID,
            "status": status,
            "reason": reason,
            "variant": self.variant,
            "reset_identity": self.reset_identity,
            "stages": self.stages,
            "dispatch_count": sum(stage.get("kind") == "dispatch" for stage in self.stages),
            "resource_affecting_dispatch_count": len(self.resource_dispatch_keys),
            "resource_affecting_action_key": self.final_dispatch_key,
            "resource_affecting_action_keys": list(self.resource_dispatch_keys),
            "variants": list(self.variants),
            "category_results": list(self.category_results),
            "source_frame_sha256": source.sha256,
            "final_before_observation": _as_observation(
                getattr(before, "observation", None) if before else None
            ),
            "immediate_post_observation": _as_observation(
                getattr(post, "observation", None) if post else None
            ),
            "terminal_frame_sha256": terminal.sha256 if terminal and terminal_recognized else "",
            "terminal_recognized": terminal_recognized,
            "terminal_state": "recognized_safe_terminal" if terminal_recognized else "evidence_required",
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }

    def _run_single(
        self,
        *,
        start_at_commander: bool = False,
        return_home: bool = True,
        source_frame: CapturedNativeFrame | None = None,
        initial_recognition: Any | None = None,
    ) -> dict[str, Any]:
        if self.variant not in SUPPORTED_VARIANTS or not self.reset_identity:
            raise ValueError("enhancement variant and reset identity are required")
        if self.session is None:
            raise RuntimeError("enhancement route requires DevelopmentSession")
        self._selection_witnesses.clear()
        source = source_frame or self._observe(
            "commander-source" if start_at_commander else "home-source"
        )
        if start_at_commander:
            home = initial_recognition or recognize_commander_stage(
                source.frame, variant=self.variant, stage="tab",
                source_frame_sha256=source.sha256, evidence_ref=source.path,
                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
            )
            self._record("commander-source", source, home)
            if not home.recognized:
                return self._result(status="blocked", reason=home.reason, source=source)
            if getattr(home, "stage", "") == "material":
                return self._result(status="blocked", reason="CURRENT_RUN_SELECTION_CONTEXT_REQUIRED", source=source)
        else:
            home = initial_recognition or recognize_home_frame(
                source.frame,
                source_frame_sha256=source.sha256,
                ocr_engine=self.ocr_engine,
            )
            self._record("home-source", source, home)
            if not home.recognized or home.portrait_target is None:
                return self._result(status="blocked", reason=home.reason, source=source)

        try:
            if start_at_commander:
                current = source
                item = initial_recognition or recognize_commander_stage(
                    current.frame, variant=self.variant, stage="tab",
                    source_frame_sha256=current.sha256, evidence_ref=current.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                )
            else:
                current, item = self._action(
                    label="home-to-commander",
                    identity="commander-profile-portrait",
                    before_recognizer=lambda frame: recognize_home_frame(
                        frame, source_frame_sha256=frame.sha256, ocr_engine=self.ocr_engine
                    ),
                    post_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="tab",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    target_getter=lambda recognition: recognition.portrait_target,
                    settle_polls=MAX_SETTLE_POLLS,
                )
            if not item.category_selected:
                current, item = self._action(
                    label="select-enhancement-category",
                    identity=f"category-select:{self.variant}",
                    before_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="tab",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    post_recognizer=self._selected_category_item,
                    target_getter=lambda recognition: recognition.category_target,
                    before_guard=lambda recognition: bool(
                        recognition.recognized and not recognition.category_selected
                    ),
                    settle_polls=MAX_SETTLE_POLLS,
                )
                if not item.category_selected:
                    raise _FlowBlocked("CATEGORY_SELECTION_NOT_PROVEN")
            if not (start_at_commander and item.open_target is not None):
                current, item = self._action(
                    label="select-equipped-enhancement-item",
                    identity=f"item-select:{self.variant}",
                    before_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    post_recognizer=self._selected_item_detail,
                    target_getter=lambda recognition: recognition.item_target,
                    before_guard=lambda recognition: bool(
                        recognition.recognized and recognition.category_selected
                    ),
                    settle_polls=MAX_SETTLE_POLLS,
                )
            current, material = self._action(
                label="open-enhance-panel", identity=f"open-enhance:{self.variant}",
                before_recognizer=lambda frame: self._selection_source(frame, "modal"),
                post_recognizer=lambda frame: self._selection_source(frame, "baseline"),
                target_getter=lambda recognition: recognition.open_target,
                settle_polls=MAX_SETTLE_POLLS,
            )
            current, choice = self._action(
                label="select-exact-one-star-material", identity=f"material-select:{self.variant}",
                before_recognizer=lambda frame: self._selection_source(frame, "baseline"),
                post_recognizer=lambda frame: self._selection_source(frame, "quantity"),
                target_getter=lambda recognition: recognition.material_target,
                before_guard=lambda recognition: recognition.quantity == 0 and not recognition.material_selected,
                settle_polls=MAX_SETTLE_POLLS,
            )
            if choice.reason != "QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED":
                raise _FlowBlocked("QUANTITY_ONE_MODAL_NOT_PROVEN")
            current, material = self._action(
                label="apply-quantity-selection", identity="quantity-use",
                before_recognizer=lambda frame: self._selection_source(frame, "quantity"),
                post_recognizer=self._selected_material,
                target_getter=lambda recognition: recognition.quantity_target,
                settle_polls=MAX_SETTLE_POLLS,
            )
            final_before = self._selected_material(current)
            if (
                not final_before.recognized
                or not final_before.material_selected
                or final_before.quantity != 1
                or final_before.observation is None
                or not enhancement_bluestacks_authorizeable(
                    final_before.observation, variant=self.variant
                )
            ):
                raise _FlowBlocked("FINAL_USE_REVALIDATION_FAILED")
            current, post = self._action(
                label="use-one-star-enhancer",
                identity="enhancement-use",
                before_recognizer=self._selected_material,
                post_recognizer=lambda frame: recognize_commander_stage(
                    frame, variant=self.variant, stage="post",
                    source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                ),
                target_getter=lambda recognition: (
                    recognition.observation.target_roi
                    if recognition.observation is not None else None
                ),
                before_guard=lambda recognition: bool(
                    recognition.recognized
                    and recognition.material_selected
                    and recognition.quantity == 1
                    and recognition.observation is not None
                    and enhancement_bluestacks_authorizeable(
                        recognition.observation, variant=self.variant
                    )
                ),
                resource_affecting=True,
            )
            final_before = self._last_before[1]
            post = self._last_after[1]
            post_capture = current
            settled = None
            for ordinal in range(0 if post.reason == "OCR_DEADLINE" else MAX_SETTLE_POLLS):
                candidate_capture = self._observe(f"enhancement-settle-{ordinal}")
                candidate = recognize_commander_stage(
                    candidate_capture.frame, variant=self.variant, stage="post",
                    source_frame_sha256=candidate_capture.sha256,
                    evidence_ref=candidate_capture.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                )
                self._record(f"enhancement-settle-{ordinal}", candidate_capture, candidate)
                if candidate.reason == "OCR_DEADLINE":
                    break
                if (
                    candidate.recognized
                    and candidate.observation is not None
                    and final_before.observation is not None
                    and enhancement_bluestacks_postcondition_verified(
                        final_before.observation, candidate.observation, variant=self.variant
                    )
                ):
                    settled = (candidate_capture, candidate)
                    break
            if settled is None:
                self._category_result = {
                    "variant": self.variant,
                    "status": "dispatch_bearing_unresolved",
                    "resource_affecting_dispatch_count": 1,
                    "resource_affecting_action_key": self.final_dispatch_key,
                    "source_frame_sha256": final_before.frame_sha256,
                    "before_observation": _as_observation(final_before.observation),
                    "successor_observation": None,
                    "runtime_session": str(getattr(self.runtime, "session", "")),
                }
                self.category_results.append(dict(self._category_result))
                self.runtime.reconcile(
                    self.final_dispatch_key or "", "unresolved", post_capture,
                    "same-item successor not proven by bounded native polling",
                )
                return self._result(
                    status="evidence_required", reason="SETTLED_SUCCESSOR_NOT_PROVEN",
                    source=source, before=final_before, post=post,
                )
            post_capture, post = settled
            self.runtime.reconcile(
                self.final_dispatch_key or "", "confirmed", post_capture,
                "same-item successor proven after bounded native polling",
            )
            self._category_result = {
                "variant": self.variant,
                "status": "completed",
                "resource_affecting_dispatch_count": 1,
                "resource_affecting_action_key": self.final_dispatch_key,
                "source_frame_sha256": final_before.frame_sha256,
                "before_observation": _as_observation(final_before.observation),
                "successor_observation": _as_observation(post.observation),
                "runtime_session": str(getattr(self.runtime, "session", "")),
            }
            self.category_results.append(dict(self._category_result))
            terminal_capture, terminal = self._navigate_to(
                "home" if return_home else "commander_overview", allow_post=True)
            result = self._result(status="completed", reason="CATEGORY_AND_HOME_VERIFIED" if return_home else "CATEGORY_AND_COMMANDER_VERIFIED",
                source=source, before=final_before, post=post,
                terminal=terminal_capture, terminal_recognized=return_home and terminal.detail_state == "home")
            result["postcondition_verified"] = True
            return result
        except _FlowBlocked as exc:
            return self._result(
                status="blocked", reason=str(exc), source=source,
                before=self._last_before[1] if self._last_before else None,
                post=self._last_after[1] if self._last_after else None,
            )

    def _run_family(self) -> dict[str, Any]:
        if tuple(self.variants) != ORDERED_VARIANTS:
            raise ValueError("enhancement family order must be gear, chip, module")
        self.category_results.extend(
            dict(self.completed_categories[variant])
            for variant in ORDERED_VARIANTS
            if variant in self.completed_categories
        )
        result: dict[str, Any] = {}
        started = False
        pending_variants = tuple(
            variant for variant in self.variants if variant not in self.completed_categories
        )
        startup_source: CapturedNativeFrame | None = None
        startup_recognition: Any | None = None
        startup_at_commander = False
        if pending_variants:
            self.variant = pending_variants[0]
            startup_source = self._observe("family-startup")
            commander = recognize_commander_stage(
                startup_source.frame,
                variant=self.variant,
                stage="item",
                source_frame_sha256=startup_source.sha256,
                evidence_ref=startup_source.path,
                ocr_engine=self.ocr_engine,
                game_day_id=self.reset_identity,
            )
            if commander.recognized:
                self._record("family-startup-commander", startup_source, commander)
                startup_recognition = commander
                startup_at_commander = True
            else:
                material = recognize_commander_stage(
                    startup_source.frame,
                    variant=self.variant,
                    stage="material",
                    source_frame_sha256=startup_source.sha256,
                    evidence_ref=startup_source.path,
                    ocr_engine=self.ocr_engine,
                    game_day_id=self.reset_identity,
                )
                if material.recognized:
                    self._record("family-startup-material", startup_source, material)
                    startup_recognition = material
                    startup_at_commander = True
                    commander = material
                else:
                    tab = recognize_commander_stage(
                        startup_source.frame,
                        variant=self.variant,
                        stage="tab",
                        source_frame_sha256=startup_source.sha256,
                        evidence_ref=startup_source.path,
                        ocr_engine=self.ocr_engine,
                        game_day_id=self.reset_identity,
                    )
                    if tab.recognized:
                        self._record("family-startup-tab", startup_source, tab)
                        startup_recognition = tab
                        startup_at_commander = True
                        commander = tab
            if not commander.recognized or commander.stage == "material":
                navigation = self._navigation_state(startup_source, allow_post=False)
                if navigation.recognized and navigation.detail_state in {"enhancement_panel", "quantity_modal"}:
                    # A selected page from an interrupted attempt cannot carry
                    # consuming authority into this run. Unwind known exits and
                    # rebuild the equipped-item and quantity witnesses.
                    try:
                        startup_source, commander = self._navigate_to(
                            "commander_overview", source_frame=startup_source,
                        )
                    except _FlowBlocked as exc:
                        result = self._result(status="blocked", reason=str(exc), source=startup_source)
                        result.update(variant="family", variants=list(self.variants))
                        return result
                    startup_recognition = commander
                    startup_at_commander = True
            if not commander.recognized:
                pending_variant = self.variant
                index = ORDERED_VARIANTS.index(pending_variant)
                prior_variant = ORDERED_VARIANTS[index - 1] if index else None
                if prior_variant in self.completed_categories:
                    prior = recognize_commander_stage(startup_source.frame,
                        variant=prior_variant, stage="post", source_frame_sha256=startup_source.sha256,
                        evidence_ref=startup_source.path, ocr_engine=self.ocr_engine,
                        game_day_id=self.reset_identity)
                    if prior.recognized:
                        self.variant = prior_variant
                        try:
                            startup_source, _ = self._navigate_to("commander_overview", allow_post=True,
                                source_frame=startup_source)
                        except _FlowBlocked as exc:
                            self.variant = pending_variant
                            result = self._result(status="blocked", reason=str(exc), source=startup_source)
                            result["variant"] = "family"
                            return result
                        self.variant = pending_variant
                        startup_recognition = recognize_commander_stage(startup_source.frame,
                            variant=pending_variant, stage="tab", source_frame_sha256=startup_source.sha256,
                            evidence_ref=startup_source.path, ocr_engine=self.ocr_engine,
                            game_day_id=self.reset_identity)
                        startup_at_commander = startup_recognition.recognized
                        commander = startup_recognition
            if not commander.recognized:
                home = recognize_home_frame(
                    startup_source.frame,
                    source_frame_sha256=startup_source.sha256,
                    ocr_engine=self.ocr_engine,
                )
                self._record("family-startup-home", startup_source, home)
                if home.recognized:
                    startup_recognition = home
                else:
                    result = self._result(
                        status="blocked",
                        reason="STARTUP_STATE_NOT_RECOGNIZED",
                        source=startup_source,
                    )
                    result["variant"] = "family"
                    result["variants"] = list(self.variants)
                    result["category_results"] = list(self.category_results)
                    result["resource_affecting_dispatch_count"] = len(
                        self.resource_dispatch_keys
                    )
                    result["resource_affecting_action_keys"] = list(
                        self.resource_dispatch_keys
                    )
                    return result
        for variant in self.variants:
            if variant in self.completed_categories:
                continue
            self.variant = variant
            result = self._run_single(
                start_at_commander=startup_at_commander if not started else True,
                return_home=variant == next(
                    pending for pending in reversed(self.variants)
                    if pending not in self.completed_categories
                ),
                source_frame=startup_source if not started else None,
                initial_recognition=startup_recognition if not started else None,
            )
            started = True
            if result.get("status") != "completed":
                result["variant"] = "family"
                result["variants"] = list(self.variants)
                result["category_results"] = list(self.category_results)
                return result
        if not started:
            self.variant = ORDERED_VARIANTS[-1]
            source = self._observe("family-home-terminal")
            try:
                terminal, _ = self._navigate_to("home", allow_post=True, source_frame=source)
            except _FlowBlocked as exc:
                result = self._result(status="evidence_required", reason=str(exc), source=source)
                result["variant"] = "family"
                return result
            result = self._result(status="completed", reason="RETAINED_FAMILY_HOME_VERIFIED",
                source=source, terminal=terminal, terminal_recognized=True)
            result["postcondition_verified"] = True
        result["variant"] = "family"
        result["variants"] = list(self.variants)
        result["category_results"] = list(self.category_results)
        result["resource_affecting_dispatch_count"] = len(self.resource_dispatch_keys)
        result["resource_affecting_action_keys"] = list(self.resource_dispatch_keys)
        result["reason"] = "ORDERED_GEAR_CHIP_MODULE_AND_HOME_VERIFIED"
        result["state_transition"] = [
            "HOME_CANONICAL", "COMMANDER_INFO_RECOGNIZED",
            "GEAR_SUCCESSOR_RECONCILED", "CHIP_SUCCESSOR_RECONCILED",
            "MODULE_SUCCESSOR_RECONCILED", "SAFE_TERMINAL_RECOGNIZED",
        ]
        return result

    def run(self) -> dict[str, Any]:
        token = _OCR_CHECKPOINT.set(getattr(self.runtime, "checkpoint", None))
        try:
            if len(self.variants) > 1:
                return self._run_family()
            return self._run_single()
        finally:
            _OCR_CHECKPOINT.reset(token)


EnhancementRoute = EnhancementIntegratedRoute
recognize_enhancement = recognize_commander_stage


def recognize_enhancement_frame(
    frame: np.ndarray,
    *,
    variant: str = "gear",
    source_frame_sha256: str | None = None,
    evidence_ref: str | Path | None = None,
    game_day_id: str = "",
    ocr_engine: OcrEngine | None = None,
    postcondition: bool = False,
) -> EnhancementFrameRecognition:
    stage = "post" if postcondition else "material"
    result = recognize_commander_stage(
        frame, variant=variant, stage=stage, source_frame_sha256=source_frame_sha256,
        evidence_ref=evidence_ref, ocr_engine=ocr_engine, game_day_id=game_day_id,
    )
    target = (
        result.observation.target_roi
        if result.observation is not None and result.observation.enhance_control_visible
        else None
    )
    return EnhancementFrameRecognition(
        result.recognized,
        "ENHANCEMENT_RESULT" if postcondition else ENHANCEMENT_SCREEN,
        result.reason,
        result.observation,
        (("enhancement-use", target),) if target is not None else (),
    )


def run_recovery(
    runtime: Any,
    *,
    variant: str,
    reset_identity: str,
    session: Any,
    navigation_only: bool = False,
    pending_attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if navigation_only and pending_attempt is not None:
        raise ValueError("Enhancement navigation and pending-effect proof are separate operations")
    capture = session.observe(runtime.capture, label=f"enhancement-{variant}-recovery-source")
    if pending_attempt is not None:
        try:
            try:
                payload = dict(pending_attempt["before_observation"])
                for name in ("target_roi", "panel_bounds", "evidence_refs"):
                    if name in payload:
                        payload[name] = tuple(payload[name])
                if "material_slot_facts" in payload:
                    payload["material_slot_facts"] = tuple(tuple(cell) for cell in payload["material_slot_facts"])
                before = EnhancementObservation(**payload)
            except (KeyError, TypeError, ValueError):
                before = None
            if before is not None and enhancement_bluestacks_authorizeable(before, variant=variant):
                receipt = _pending_settled_successor(runtime, session, capture, variant,
                    reset_identity, pending_attempt, before)
                # This receipt crosses the persisted delivery boundary before
                # independent replay; its in-memory form must match JSON reload.
                receipt = json.loads(json.dumps(receipt))
                return {"schema_version": 1, "flow_id": FLOW_ID, "variant": variant,
                    "reset_identity": reset_identity, "status": "recovered_successor",
                    "reason": "retained_settled_successor_and_two_fresh_observations_agree",
                    "proof_kind": "settled_successor", "read_only": True, "input_authority": False,
                    "dispatch": False, "dispatch_count": 0, "input_count": 0,
                    "resource_affecting_dispatch_count": 0, "recovery_only": True,
                    "terminal_recognized": False, "semantic_successor_proven": True,
                    "successor_receipt": receipt,
                    "successor_observation": receipt["successor_observation"],
                    "successor_evidence_ref": receipt["successor_evidence_ref"]}
            receipt = _pending_no_effect(runtime, session, capture, variant, reset_identity, pending_attempt)
            return {"schema_version": 1, "flow_id": FLOW_ID, "variant": variant,
                "reset_identity": reset_identity, "status": "recovered_no_effect",
                "reason": "zero_selected_confirm_had_no_material_or_exp_effect",
                "dispatch": False, "dispatch_count": 0, "input_count": 0,
                "resource_affecting_dispatch_count": 0, "recovery_only": True,
                "terminal_recognized": False, "semantic_successor_proven": False,
                "proof_kind": receipt["proof_kind"], "no_effect_receipt": receipt}
        except (OSError, KeyError, TypeError, ValueError) as exc:
            return {"schema_version": 1, "flow_id": FLOW_ID, "variant": variant,
                "reset_identity": reset_identity, "status": "evidence_required", "reason": str(exc),
                "dispatch": False, "dispatch_count": 0, "input_count": 0,
                "resource_affecting_dispatch_count": 0, "recovery_only": True,
                "terminal_recognized": False, "semantic_successor_proven": False}
    if navigation_only:
        route = EnhancementIntegratedRoute(runtime, variant=variant, reset_identity=reset_identity, session=session)
        try:
            terminal, _ = route._navigate_to("home", source_frame=capture)
            result = route._result(status="recovered_safe", reason="ZERO_USE_VISIBLE_HOME_RETURN_VERIFIED",
                source=capture, terminal=terminal, terminal_recognized=True)
        except _FlowBlocked as exc:
            result = route._result(status="evidence_required", reason=str(exc), source=capture)
        result.update(recovery_only=True, navigation_only=True,
            terminal_home_verified=result["terminal_recognized"], dispatch=bool(result["dispatch_count"]),
            successor_observation=None, successor_evidence_ref="")
        return result
    home = recognize_home_frame(capture.frame, source_frame_sha256=capture.sha256)
    commander = recognize_commander_stage(
        capture.frame, variant=variant, stage="post",
        source_frame_sha256=capture.sha256, evidence_ref=capture.path,
        game_day_id=reset_identity,
    )
    observed_material = commander.recognized and commander.observation is not None
    safe = home.recognized
    result = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": (
            "recovered_safe" if home.recognized
            else "evidence_required"
        ),
        "reason": home.reason if home.recognized else commander.reason,
        "variant": variant,
        "reset_identity": reset_identity,
        "dispatch": False,
        "dispatch_count": 0,
        "resource_affecting_dispatch_count": 0,
        "resource_affecting_action_key": None,
        "recovery_only": True,
        "terminal_recognized": safe,
        "terminal_frame_sha256": capture.sha256 if safe else "",
        "terminal_state": "recognized_safe_terminal" if safe else "evidence_required",
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    result["successor_observation"] = (
        _as_observation(commander.observation) if observed_material else None
    )
    result["successor_evidence_ref"] = capture.path if observed_material else ""
    result["semantic_successor_proven"] = False
    return result


def _pending_settled_successor(runtime, session, current, variant, reset_identity, pending, before):
    """Prove an original settled effect and two agreeing current read-only frames."""
    def checkpoint():
        callback = getattr(runtime, "checkpoint", None)
        if callback is not None:
            callback()
        if any(type(getattr(owner, "input_count", None)) is not int or owner.input_count != 0
                for owner in (runtime, session)):
            raise ValueError("Enhancement successor recovery requires exact zero inputs")

    checkpoint()
    if (pending.get("variant") != variant or pending.get("status") != "dispatch_bearing_unresolved"
            or type(pending.get("resource_affecting_dispatch_count")) is not int
            or pending["resource_affecting_dispatch_count"] != 1 or before.game_day_id != reset_identity):
        raise ValueError("Enhancement pending successor identity differs")
    original = Path(pending["runtime_session"])
    if original.is_symlink() or not original.is_dir():
        raise ValueError("Enhancement original successor session is not a regular directory")
    original = original.resolve(strict=True)

    def regular(path, root):
        path = Path(path)
        path = path if path.is_absolute() else root / path
        resolved = path.resolve(strict=True)
        relative = path.absolute().relative_to(root)
        if not resolved.is_file() or any(root.joinpath(*relative.parts[:index]).is_symlink()
                for index in range(1, len(relative.parts) + 1)):
            raise ValueError("Enhancement successor evidence is not a confined regular file")
        return resolved

    delivery_path = regular(original / "flow-delivery-result.json", original)
    delivery_raw = delivery_path.read_bytes()
    delivery = json.loads(delivery_raw)
    key = pending["resource_affecting_action_key"]
    if not isinstance(delivery, Mapping) or not isinstance(delivery.get("enhancement_result"), Mapping):
        raise ValueError("Enhancement original delivery is malformed")
    retained = [entry for entry in delivery["enhancement_result"].get("category_results", ())
        if isinstance(entry, Mapping) and entry.get("variant") == variant
        and entry.get("resource_affecting_action_key") == key]
    if (not isinstance(key, str) or not key or len(retained) != 1
            or retained[0].get("status") != "dispatch_bearing_unresolved"
            or retained[0].get("source_frame_sha256") != pending.get("source_frame_sha256")
            or retained[0].get("before_observation") != pending.get("before_observation")):
        raise ValueError("Enhancement original delivery does not bind the pending effect")
    rows = [json.loads(line) for line in regular(original / "events.jsonl", original).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("Enhancement original successor journal is malformed")
    confirms = [(index, row) for index, row in enumerate(rows)
        if row.get("type") == "dispatch" and (row.get("action_key") == key
            or (row.get("target_identity") == "enhancement-use"
                and str(row.get("action_key", "")).startswith(f"enhancement:{variant}:")))]
    if len(confirms) != 1:
        raise ValueError("Enhancement original Confirm is not unique")
    dispatch_index, dispatch = confirms[0]
    if (dispatch.get("action_key") != key or dispatch.get("target_identity") != "enhancement-use"
            or dispatch.get("execute") is not True or dispatch.get("source_sha256") != before.source_frame_sha256
            or before.source_frame_sha256 != pending.get("source_frame_sha256")
            or tuple(dispatch.get("target_roi") or ()) != tuple(before.target_roi)):
        raise ValueError("Enhancement original Confirm source or target differs")
    classifications = [row for row in rows if row.get("type") == "dispatch_classification"
        and row.get("action_key") == key]
    if (len(classifications) != 1 or classifications[0].get("resource_affecting") is not True
            or classifications[0].get("action_class") != "resource_affecting_confirmation"):
        raise ValueError("Enhancement original Confirm classification differs")

    def retained_capture(row):
        checkpoint()
        path = regular(row["path"], original)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Enhancement original successor capture changed")
        return captured_native_frame_from_png(raw, path=path,
            captured_monotonic=row["captured_monotonic"])

    witnesses = []
    witness_indices = []
    for reference in before.evidence_refs:
        path = regular(reference, original)
        matches = [(index, row) for index, row in enumerate(rows[:dispatch_index])
            if row.get("type") == "capture" and regular(row["path"], original) == path]
        if len(matches) != 1:
            raise ValueError("Enhancement original selection capture is not unique")
        witness_indices.append(matches[0][0])
        witnesses.append(retained_capture(matches[0][1]))
    if len(witnesses) != 4:
        raise ValueError("Enhancement original four selection witnesses are required")
    source, modal, baseline, quantity = witnesses
    if (source.sha256 != before.source_frame_sha256 or witness_indices[0] >= dispatch_index
            or any(row.get("type") == "dispatch" for row in rows[witness_indices[0] + 1:dispatch_index])):
        raise ValueError("Enhancement original Confirm lacks its immediate source")
    parsed = recognize_selection_context(source, modal=modal, baseline=baseline, quantity=quantity,
        variant=variant, game_day_id=reset_identity)
    if (not parsed.recognized or parsed.observation is None
            or json.dumps(_as_observation(parsed.observation), sort_keys=True) != json.dumps(_as_observation(before), sort_keys=True)):
        raise ValueError("Enhancement original selected-one source is not replayable")
    for position, identity, target in ((1, f"open-enhance:{variant}", "modal_enhance"),
            (2, f"material-select:{variant}", "baseline_card"), (3, "quantity-use", "quantity_use")):
        start = witness_indices[position]
        stop = witness_indices[position + 1] if position < 3 else witness_indices[0]
        actions = [row for row in rows[start + 1:stop] if row.get("type") == "dispatch"]
        if (len(actions) != 1 or actions[0].get("target_identity") != identity
                or actions[0].get("source_sha256") != witnesses[position].sha256
                or actions[0].get("execute") is not True
                or tuple(actions[0].get("target_roi") or ()) != tuple(parsed.diagnostics["selection_context_targets"][target])):
            raise ValueError("Enhancement original selection dispatch chain differs")
    successor = None
    for row in rows[dispatch_index + 1:]:
        if row.get("type") == "dispatch":
            break
        if row.get("type") != "capture":
            continue
        frame = retained_capture(row)
        if frame.captured_monotonic <= source.captured_monotonic:
            raise ValueError("Enhancement original successor capture is not fresh")
        found = recognize_commander_stage(frame.frame, variant=variant, stage="post",
            source_frame_sha256=frame.sha256, evidence_ref=frame.path, game_day_id=reset_identity)
        if found.recognized and enhancement_bluestacks_postcondition_verified(before, found.observation, variant=variant):
            successor = found.observation
            successor_monotonic = frame.captured_monotonic
            break
    if successor is None:
        raise ValueError("Enhancement original settled positive successor is not proven")
    checkpoint()
    time.sleep(SETTLED_SUCCESSOR_DELAY_SECONDS)
    later = session.observe(runtime.capture, label=f"enhancement-{variant}-successor-later")
    checkpoint()
    if (not successor_monotonic < current.captured_monotonic < later.captured_monotonic
            or later.path == current.path):
        raise ValueError("Enhancement successor recovery observations are not fresh")
    observations = []
    recovery_root = Path(runtime.session).resolve(strict=True)
    recovery_rows = [json.loads(line) for line in regular(runtime.events, recovery_root).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, Mapping) or row.get("type") == "dispatch" for row in recovery_rows):
        raise ValueError("Enhancement successor recovery journal contains input")
    for frame in (current, later):
        path = regular(frame.path, recovery_root)
        if path.read_bytes() != frame.png or hashlib.sha256(frame.png).hexdigest() != frame.sha256:
            raise ValueError("Enhancement current successor capture changed")
        matches = [row for row in recovery_rows if row.get("type") == "capture"
            and Path(row.get("path", "")).resolve() == path
            and row.get("sha256") == frame.sha256
            and row.get("captured_monotonic") == frame.captured_monotonic]
        if len(matches) != 1:
            raise ValueError("Enhancement successor recovery capture is not journal-bound")
        decoded = captured_native_frame_from_png(frame.png, path=path, captured_monotonic=frame.captured_monotonic)
        found = recognize_commander_stage(decoded.frame, variant=variant, stage="post",
            source_frame_sha256=decoded.sha256, evidence_ref=decoded.path, game_day_id=reset_identity)
        observation = found.observation
        fields = ("selected_item_identity", "item_level", "item_exp_current", "item_exp_required", "material_slot_facts")
        if (not found.recognized or not enhancement_bluestacks_postcondition_verified(before, observation, variant=variant)
                or any(getattr(observation, name) != getattr(successor, name) for name in fields)):
            raise ValueError("Enhancement current observations differ from original settled successor")
        observations.append(observation)
    checkpoint()
    return {"proof_kind": "settled_successor", "read_only": True, "input_authority": False,
        "original_action_key": key, "original_runtime_session": str(original), "reset_identity": reset_identity,
        "original_delivery_sha256": hashlib.sha256(delivery_raw).hexdigest(),
        "original_source_frame_sha256": source.sha256, "successor_observation": _as_observation(successor),
        "successor_evidence_ref": successor.evidence_refs[0], "recovery_session_directory": str(recovery_root),
        "immediate_recovery_observation": _as_observation(observations[0]),
        "later_recovery_observation": _as_observation(observations[1]),
        "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0}


def _pending_no_effect(runtime, session, current, variant, reset_identity, pending):
    """Read four actual zero-selection frames; this proof grants no input."""
    if (pending.get("variant") != variant or pending.get("status") != "dispatch_bearing_unresolved"
            or pending.get("resource_affecting_dispatch_count") != 1
            or getattr(runtime, "input_count", 0) != 0 or getattr(session, "input_count", 0) != 0):
        raise ValueError("Enhancement pending no-effect identity or zero-input scope differs")
    original = Path(pending["runtime_session"])
    if original.is_symlink() or not original.is_dir():
        raise ValueError("Enhancement original runtime must be a retained directory")
    original = original.resolve(strict=True)
    before = pending["before_observation"]
    if not isinstance(before, Mapping) or before.get("game_day_id") != reset_identity:
        raise ValueError("Enhancement original reset does not match no-effect recovery")
    key = pending["resource_affecting_action_key"]
    rows = [json.loads(line) for line in (original / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    dispatches = [(index, row) for index, row in enumerate(rows) if row.get("type") == "dispatch" and row.get("action_key") == key]
    if len(dispatches) != 1 or dispatches[0][1].get("target_identity") != "enhancement-use":
        raise ValueError("Enhancement original Confirm dispatch is not unique")
    index, dispatch = dispatches[0]
    sources = [row for row in rows[:index] if row.get("type") == "capture" and row.get("sha256") == dispatch.get("source_sha256")]
    posts = [row for row in rows[index + 1:] if row.get("type") == "capture"]
    if not sources or not posts or dispatch.get("execute") is not True:
        raise ValueError("Enhancement original immediate capture chain is incomplete")

    def retained(row):
        path = Path(row["path"])
        path = path if path.is_absolute() else original / path
        if path.is_symlink():
            raise ValueError("Enhancement no-effect capture cannot be a link")
        path.resolve(strict=True).relative_to(original)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Enhancement no-effect original capture changed")
        return captured_native_frame_from_png(raw, path=path, captured_monotonic=row["captured_monotonic"])

    source, immediate = retained(sources[-1]), retained(posts[0])
    if (source.sha256 != pending.get("source_frame_sha256")
            or source.sha256 != before.get("source_frame_sha256")
            or source.path.resolve() not in [Path(value).resolve() for value in before.get("evidence_refs", ())]
            or source.captured_monotonic >= immediate.captured_monotonic):
        raise ValueError("Enhancement original source does not match the pending attempt")
    time.sleep(SETTLED_SUCCESSOR_DELAY_SECONDS)
    later = session.observe(runtime.capture, label=f"enhancement-{variant}-no-effect-later")
    if (later.captured_monotonic <= current.captured_monotonic
            or later.path == current.path or getattr(runtime, "input_count", 0) != 0
            or getattr(session, "input_count", 0) != 0):
        raise ValueError("Enhancement no-effect recovery was not two fresh zero-input observations")
    observations = []
    for frame in (source, immediate, current, later):
        parsed = recognize_commander_stage(frame.frame, variant=variant, stage="material",
            source_frame_sha256=frame.sha256, evidence_ref=frame.path, game_day_id=reset_identity)
        observation = parsed.observation
        if (observation is None or not observation.material_slot_facts
                or any(cell[2] for cell in observation.material_slot_facts)
                or observation.quantity != 0 or observation.material_quantity != 0
                or observation.item_equipped or enhancement_bluestacks_authorizeable(observation, variant=variant)):
            raise ValueError("Enhancement no-effect requires complete actual zero-selection facts")
        observations.append(observation)
    names = ("selected_item_identity", "item_level", "item_exp_current", "item_exp_required", "material_slot_facts")
    if any(any(getattr(item, name) != getattr(observations[0], name) for name in names) for item in observations[1:]):
        raise ValueError("Enhancement material or EXP facts changed; no-effect is not proven")
    return {"proof_kind": "zero_selected_confirm", "semantic_replay_reason": "legacy_static_selected_quantity_shortcut_rejected",
        "read_only": True, "input_authority": False,
        "original_action_key": key, "original_runtime_session": str(original),
        "recovery_session_directory": str(runtime.session), "reset_identity": reset_identity,
        "original_source_frame_sha256": source.sha256, "original_immediate_post_frame_sha256": immediate.sha256,
        "immediate_recovery_frame_sha256": current.sha256, "later_recovery_frame_sha256": later.sha256,
        "original_before_observation": _as_observation(observations[0]),
        "original_immediate_post_observation": _as_observation(observations[1]),
        "immediate_recovery_observation": _as_observation(observations[2]),
        "later_recovery_observation": _as_observation(observations[3]),
        "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0}


def _write_result(session: Path, result: Mapping[str, Any]) -> None:
    session.mkdir(parents=True, exist_ok=True)
    (session / "result.json").write_text(
        json.dumps(dict(result), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dict(result), sort_keys=True, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--variant", choices=tuple(sorted(SUPPORTED_VARIANTS)), default="gear")
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--recovery-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        _write_result(
            args.output_directory,
            {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "dry-run",
                "variant": args.variant,
                "dispatch": False,
                "dispatch_count": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
        )
        return 0
    raise SystemExit(
        "live enhancement execution must be admitted through the pnsctl-owned DevelopmentSession"
    )


if __name__ == "__main__":
    raise SystemExit(main())
