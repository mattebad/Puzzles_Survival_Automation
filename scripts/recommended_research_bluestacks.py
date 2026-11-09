"""Bounded BlueStacks route for the first displayed Research recommendation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from automation_service.registry import (
    RECOMMENDED_RESEARCH_FLOW_ID as FLOW_ID,
    RECOMMENDED_RESEARCH_MAX_INPUTS as MAX_INPUTS,
    RECOMMENDED_RESEARCH_PROFILE_ID as PROFILE_ID,
    RECOMMENDED_RESEARCH_PRODUCT_ID as PRODUCT_ID,
    RECOMMENDED_RESEARCH_PRODUCT_REVISION as PRODUCT_REVISION,
)
import cv2

from safe_action_core import (
    ActionClass,
    ActionIntent,
    CentralPolicy,
    Observation,
    PolicyRequest,
    TransportResult,
)
from tasks.home_atlas import BuildingBinding, HomeAtlas, load_home_atlas
from tasks.home_atlas_vision import (
    HUD_MASK_RECTS,
    BlueStacksHomeLocalizer,
    bind_visible_building,
    native_frame_guard,
)
from scripts.home_atlas_bluestacks import bind_or_pan_mapped_home_building
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE
from tasks.tech_upgrade_disabled import (
    ACTIVE_SCREEN,
    DETAIL_SCREEN,
    LIST_SCREEN,
    RESEARCH_RESOURCES,
    ResearchActiveObservation,
    ResearchResourceRow,
    RecommendedResearchListObservation,
    TechUpgradeObservation,
    research_identity,
    research_list_navigation_authorizeable,
    research_list_navigation_verified,
    tech_upgrade_authorizeable,
    tech_upgrade_postcondition_verified,
    tech_upgrade_shortages,
)


MAX_ACTIONS = 1
MAX_RESEARCH_TRANSPORT_CALLS = 1
OBSERVATION_INTERVAL_SECONDS = 300
ATLAS_PATH = Path(__file__).resolve().parents[1] / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
RESEARCH_CENTER_ID = "home.building.research_center"
_RESEARCH_PANEL_RE = re.compile(r"([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)")
_LEVEL_RE = re.compile(r"(?:\(\s*)?([0-9]{1,3})\s*/\s*([0-9]{1,3})(?:\s*\))?")
_CLOCK_RE = re.compile(r"(?<![0-9])([0-9]{1,2}):([0-9]{2}):([0-9]{2})(?![0-9])")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
# Owned intermediate between a detail sheet and the Research Center: one
# category's technology tree under its white header (actual Research Center
# categories: Development, Economy, Military, Fortification, Unit Tactics).
TREE_SCREEN = "RESEARCH_TREE"
_RESEARCH_TREE_CATEGORIES = frozenset({"development", "economy", "military", "fortification", "unittactics"})
_UNSAFE_OVERLAY_MARKERS = (
    "insufficientresource",
    "notenoughresource",
    "purchase",
    "buy",
    "refill",
    "openbox",
    "box",
    "activatequeue",
    "premium",
    "confirm",
)
_ACCOUNTING_UNSET = object()


@dataclass(frozen=True)
class ResearchWord:
    text: str
    normalized: str
    roi: tuple[int, int, int, int]
    confidence: float
    line_id: tuple[int, int, int]

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.roi
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


@dataclass(frozen=True)
class ResearchScreenObservation:
    screen_state: str
    frame_sha256: str
    evidence_refs: tuple[str, ...]
    text: str
    words: tuple[ResearchWord, ...]
    overlay_state: str = "none_observed"
    owner_building_id: str | None = None
    owner_screen_anchor: tuple[float, float] | None = None
    first_recommendation_title: str | None = None
    first_recommendation_identity: str | None = None
    recommendation_position: int | None = None
    list_research_target_roi: tuple[int, int, int, int] | None = None
    detail_research_target_roi: tuple[int, int, int, int] | None = None
    research_now_target_roi: tuple[int, int, int, int] | None = None
    panel_bounds: tuple[int, int, int, int] | None = None
    scroll_roi: tuple[int, int, int, int] | None = None
    current_level: int | None = None
    target_level: int | None = None
    selected_technology_title: str | None = None
    selected_technology_identity: str | None = None
    prerequisite_lines: tuple[str, ...] = ()
    prerequisite_level: int | None = None
    prerequisite_evidence: tuple[str, ...] = ()
    prerequisites_known: bool = False
    prerequisites_met: bool = False
    resource_ink_conflict: bool = False
    resource_pairs: tuple[tuple[int, int], ...] = ()
    resource_rows: tuple[ResearchResourceRow, ...] = ()
    requirements_scrolled: bool = False
    duration_seconds: int | None = None
    queue1_state: str = "unknown"
    queue1_remaining_seconds: int | None = None
    active_title: str | None = None
    active_identity: str | None = None
    active_remaining_seconds: int | None = None
    active_resource_rows: tuple[ResearchResourceRow, ...] = ()
    research_category: str | None = None
    recognized: bool = False


@dataclass(frozen=True)
class _ActionPlan:
    target_identity: str
    target_roi: tuple[int, int, int, int]
    source_state: str
    control_class: str
    expected_postcondition: str
    semantic_action: str
    target_isolated: bool = True
    gesture: str = "tap"
    scroll_direction: str | None = None


class RecommendedResearchRouteFailure(RuntimeError):
    def __init__(self, message: str, *, partial_result: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.partial_result = dict(partial_result)


def _normalize(value: object) -> str:
    text = str(value).replace("’", "'").replace("‘", "'").casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _line_text(words: Sequence[ResearchWord]) -> str:
    return " ".join(word.text for word in words if word.text.strip()).strip()


def _line_groups(words: Sequence[ResearchWord]) -> tuple[tuple[ResearchWord, ...], ...]:
    groups: dict[tuple[int, int, int], list[ResearchWord]] = {}
    for word in words:
        groups.setdefault(word.line_id, []).append(word)
    ordered = sorted(groups.values(), key=lambda row: (min(word.roi[1] for word in row), min(word.roi[0] for word in row)))
    return tuple(tuple(sorted(row, key=lambda word: word.roi[0])) for row in ordered)


def _ocr_words(data: Mapping[str, object]) -> tuple[ResearchWord, ...]:
    text = data.get("text")
    if not isinstance(text, Sequence) or isinstance(text, (str, bytes)):
        return ()
    columns = {name: data.get(name) for name in ("left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")}
    if any(not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != len(text) for value in columns.values()):
        return ()
    output = []
    for index, value in enumerate(text):
        word = str(value).strip()
        if not word:
            continue
        try:
            x, y, width, height = (int(columns[name][index]) for name in ("left", "top", "width", "height"))
            confidence = float(columns["conf"][index])
            block, paragraph, line = (int(columns[name][index]) for name in ("block_num", "par_num", "line_num"))
        except (TypeError, ValueError, OverflowError):
            continue
        if confidence < 30 or x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 800 or y + height > 1280:
            continue
        output.append(ResearchWord(word, _normalize(word), (x, y, x + width, y + height), confidence, (block, paragraph, line)))
    return tuple(output)


def _read_words(frame: Any, ocr_data: Mapping[str, object] | None = None) -> tuple[ResearchWord, ...]:
    if ocr_data is None:
        from scripts.bounded_tesseract import call_ocr, tesseract_data

        ocr_data = call_ocr(tesseract_data, frame, config="--psm 6", call_timeout=5.0)
    if not isinstance(ocr_data, Mapping):
        return ()
    return _ocr_words(ocr_data)


def _translated_words(data: object, x0: int, y0: int) -> tuple[ResearchWord, ...]:
    if not isinstance(data, Mapping):
        return ()
    try:
        data = {
            **data,
            "left": [x0 + int(value) // 3 for value in data["left"]],
            "top": [y0 + int(value) // 3 for value in data["top"]],
            "width": [-(-int(value) // 3) for value in data["width"]],
            "height": [-(-int(value) // 3) for value in data["height"]],
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return ()
    return _ocr_words(data)


def _scaled_crop_words(frame: Any, roi: tuple[int, int, int, int], config: str) -> tuple[ResearchWord, ...]:
    from scripts.bounded_tesseract import call_ocr, tesseract_data

    x0, y0, x1, y1 = roi
    crop = cv2.resize(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), None, fx=3, fy=3)
    return _translated_words(call_ocr(tesseract_data, crop, config=config, call_timeout=5.0), x0, y0)


def _white_ink(crop: Any) -> Any:
    """Keep only white UI strokes, darkened onto a blank page."""

    white = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), (0, 0, 180), (179, 80, 255))
    strokes = cv2.dilate(white, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.bitwise_not(cv2.bitwise_and(gray, gray, mask=strokes))


def _gray(crop: Any) -> Any:
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _prepared_crop_words(
    frame: Any, roi: tuple[int, int, int, int], prepare: Callable[[Any], Any], config: str,
) -> tuple[ResearchWord, ...]:
    from scripts.bounded_tesseract import call_ocr, tesseract_data

    x0, y0, x1, y1 = roi
    scaled = cv2.resize(prepare(frame[y0:y1, x0:x1]), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return _translated_words(call_ocr(tesseract_data, scaled, config=config, call_timeout=5.0), x0, y0)


def _radial_caption_words(frame: Any, anchor: tuple[float, float]) -> tuple[ResearchWord, ...]:
    """Read the white radial captions beneath a freshly bound owner anchor.

    Full-frame OCR merges the small outlined captions with the city art, so
    only white strokes in the owner's caption band are read sparse at 3x.
    """

    height, width = frame.shape[:2]
    ax, ay = (int(round(value)) for value in anchor)
    x0, y0 = max(0, ax - 240), max(0, ay + 40)
    x1, y1 = min(width, ax + 240), min(height, ay + 210)
    if x1 - x0 < 24 or y1 - y0 < 24:
        return ()
    return _prepared_crop_words(frame, (x0, y0, x1, y1), _white_ink, "--psm 11")


# Actual Research Center page rereads measured 95-96 for the title and both
# Research buttons, and 95-96 for the row title words they anchor.
_RESEARCH_PAGE_MIN_CONFIDENCE = 80.0
_ROMAN_TAIL_RE = re.compile(r"(.*\S)\s+([IVXl|]{1,4})")


def _canonical_title(title: str) -> str:
    """Tesseract reads this font's roman-numeral I as l or |; titles end in I/V/X tiers."""

    match = _ROMAN_TAIL_RE.fullmatch(title)
    if match is None:
        return title
    return f"{match.group(1)} {match.group(2).replace('l', 'I').replace('|', 'I')}"


def _reread_line_words(
    reread: Sequence[ResearchWord], block: int, *, gap: int = 40,
) -> tuple[list[ResearchWord], int]:
    """Give each horizontally separated reread cluster its own line identity."""

    grouped: list[ResearchWord] = []
    previous_right: int | None = None
    previous_y: float | None = None
    for word in sorted(reread, key=lambda item: (item.roi[1] // 40, item.roi[0])):
        if (
            previous_right is not None
            and previous_y is not None
            and (word.roi[0] - previous_right > gap or abs(word.center[1] - previous_y) > 20)
        ):
            block += 1
        grouped.append(ResearchWord(word.text, word.normalized, word.roi, word.confidence, (block, 0, 0)))
        previous_right, previous_y = word.roi[2], word.center[1]
    return grouped, block + 1


def _reread_list_rows(
    frame: Any, words: tuple[ResearchWord, ...], header_bottom: int, block: int,
    added: list[ResearchWord], replaced: list[tuple[int, int, int, int]],
) -> int:
    height, width = frame.shape[:2]
    buttons = sorted(
        (
            word for word in _prepared_crop_words(frame, (330, header_bottom, width, height), _white_ink, "--psm 6")
            if word.normalized == "research" and word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE
        ),
        key=lambda word: (word.roi[1], word.roi[0]),
    )
    for button in buttons:
        bx0, by0, _bx1, by1 = button.roi
        added.append(ResearchWord(button.text, button.normalized, button.roi, button.confidence, (block, 0, 0)))
        replaced.append(button.roi)
        block += 1
        anchors = [
            word for word in words
            if word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE
            and word.roi[1] > header_bottom
            and word.roi[2] <= bx0 - 8
            and by0 - 40 <= word.center[1] <= by1
        ]
        if not anchors:
            continue
        band = (
            max(0, min(word.roi[0] for word in anchors) - 8),
            max(header_bottom, min(word.roi[1] for word in anchors) - 6),
            bx0 - 8,
            min(height, max(word.roi[3] for word in anchors) + 6),
        )
        row = [word for word in _prepared_crop_words(frame, band, _gray, "--psm 11") if word.normalized]
        if not row or any(word.confidence < 60 for word in row):
            continue
        added.extend(ResearchWord(word.text, word.normalized, word.roi, word.confidence, (block, 0, 0)) for word in row)
        replaced.append((0, band[1], band[2], band[3]))
        block += 1
    return block


def _detail_title_lines(lines: Sequence[tuple[ResearchWord, ...]]) -> list[tuple[ResearchWord, ...]]:
    """Sheet title rows: one "(n/m)" level token right of confident title words."""

    labels = (*_phrase_lines(lines, "Original Time"), *_phrase_lines(lines, "Actual Time"))
    labels_top = min((_line_bounds(line)[1] for line in labels), default=None)
    titles = []
    for line in lines:
        x0, y0, x1, y1 = _line_bounds(line)
        levels = [word for word in line if _LEVEL_RE.fullmatch(word.text.strip())]
        if y0 <= 500 or (labels_top is not None and y1 >= labels_top) or len(levels) != 1:
            continue
        if any(
            word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE and word.normalized.isalpha() and word.roi[2] <= levels[0].roi[0]
            for word in line
        ):
            titles.append(line)
    return titles


def _reread_detail_controls(
    frame: Any, words: tuple[ResearchWord, ...], lines: Sequence[tuple[ResearchWord, ...]], block: int,
    added: list[ResearchWord], replaced: list[tuple[int, int, int, int]],
) -> int:
    """Reread the actual detail sheet's title row and its bottom control pair.

    Measured on the actual Troop Load II sheet: the full-frame pass merged the
    title with its icon/close glyphs ('@ Troop Load 11 (8/10) x') and dropped
    both bottom controls; white-ink rereads gave 'Troop Load II (8/10)'
    (96/96/73-78/93-96) and 'Research Now' 96/96 left of ordinary 'Research' 96.
    """

    height, width = frame.shape[:2]
    title_lines = _detail_title_lines(lines)
    if len(title_lines) == 1:
        line = title_lines[0]
        level = next(word for word in line if _LEVEL_RE.fullmatch(word.text.strip()))
        anchors = [
            word for word in line
            if word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE
            and word.normalized.isalpha()
            and word.roi[2] <= level.roi[0]
        ]
        if anchors:
            band = (
                max(0, min(word.roi[0] for word in anchors) - 8),
                max(0, min(word.roi[1] for word in (*anchors, level)) - 6),
                min(width, level.roi[2] + 8),
                min(height, max(word.roi[3] for word in (*anchors, level)) + 6),
            )
            row = [word for word in _prepared_crop_words(frame, band, _white_ink, "--psm 7") if word.normalized]
            if (
                row
                and all(word.confidence >= 60 for word in row)
                and sum(bool(_LEVEL_RE.fullmatch(word.text.strip())) for word in row) == 1
                and any(word.normalized.isalpha() for word in row)
            ):
                added.extend(ResearchWord(word.text, word.normalized, word.roi, word.confidence, (block, 0, 0)) for word in row)
                replaced.append(band)
                block += 1
    controls_top = max(_line_bounds(line)[3] for line in lines)
    if controls_top < height - 24:
        controls = [
            word for word in _prepared_crop_words(frame, (0, controls_top, width, height), _white_ink, "--psm 6")
            if word.normalized in {"research", "now"} and word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE
        ]
        grouped, block = _reread_line_words(controls, block)
        added.extend(grouped)
        replaced.extend(word.roi for word in grouped)
    return block




def _research_page_words(frame: Any, words: tuple[ResearchWord, ...]) -> tuple[ResearchWord, ...]:
    """Reread the Research page text the full-frame pass drops.

    The white header band is always reread when no title was found there.
    With exactly one recommendation header the Research buttons and their
    anchored row titles are reread; with exactly one Original/Actual Time pair
    the detail title row and bottom controls are. Nothing is added without a
    confident current read.
    """

    lines = _line_groups(words)
    height, width = frame.shape[:2]
    block = max((word.line_id[0] for word in words), default=0) + 1
    added: list[ResearchWord] = []
    replaced: list[tuple[int, int, int, int]] = []
    if not any(_line_bounds(line)[1] < 180 for line in _phrase_lines(lines, "Research Center")):
        for word in _prepared_crop_words(frame, (0, 0, width, 180), _white_ink, "--psm 6"):
            if word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE:
                added.append(ResearchWord(word.text, word.normalized, word.roi, word.confidence, (block, word.line_id[1], word.line_id[2])))
        block += 1
    headers = [line for line in lines if "recomd" in _normalize(_line_text(line)) or "recommended" in _normalize(_line_text(line))]
    if len(headers) == 1:
        block = _reread_list_rows(frame, words, _line_bounds(headers[0])[3], block, added, replaced)
    elif (
        len(_phrase_lines(lines, "Original Time")) == 1 and len(_phrase_lines(lines, "Actual Time")) == 1
    ) or len(_detail_title_lines(lines)) == 1:
        block = _reread_detail_controls(frame, words, lines, block, added, replaced)
    if not added:
        return words
    retained = tuple(
        word for word in words
        if not any(x0 <= word.center[0] <= x1 and y0 <= word.center[1] <= y1 for x0, y0, x1, y1 in replaced)
    )
    return (*retained, *added)


def _home_research_hud_words(frame: Any, words: tuple[ResearchWord, ...]) -> tuple[ResearchWord, ...]:
    """Reread the fraction beneath the fresh, measured left-HUD Research label.

    Full-frame OCR can drop the small HUD label entirely, so the label is
    measured from the shared fixed left-HUD column and must be unique there.
    """
    hud = HUD_MASK_RECTS[1]
    anchors = [word for word in _scaled_crop_words(frame, hud, "--psm 11") if word.normalized == "research"]
    if len(anchors) != 1:
        return words
    anchor = anchors[0]
    left, top = max(hud[0], anchor.roi[0] - 14), max(hud[1], anchor.roi[1] - 10)
    right, bottom = min(hud[2], anchor.roi[2] + 18), min(hud[3], anchor.roi[3] + 24)
    block = max((word.line_id[0] for word in words), default=0) + 1
    retained = tuple(word for word in words
                     if not (left <= word.center[0] <= right and top <= word.center[1] <= bottom))
    clocks = tuple(
        ResearchWord(word.text, word.normalized, word.roi, word.confidence, (block, word.line_id[1], word.line_id[2]))
        for word in _scaled_crop_words(frame, (left, top, right, bottom), "--psm 6")
        if _CLOCK_RE.fullmatch(word.text)
    )
    label = ResearchWord(anchor.text, anchor.normalized, anchor.roi, anchor.confidence, (block, 0, 0))
    fraction_band = (left, anchor.roi[3] + 3, right, min(hud[3], anchor.roi[3] + _HUD_FRACTION_BAND_BELOW_LABEL))
    fraction = _hud_queue_fraction_word(frame, fraction_band, (block + 1, 0, 0))
    return (*retained, label, *((fraction,) if fraction is not None else ()), *clocks)


# Actual Homes (prerequisite-native 0001/0002, parent-chain 0008): the HUD
# "(0/1)" strokes are dim neutral white (V 150..180) over changing map art.
# Whole-crop OCR dropped it on 0002 and a white-ink cut misread it as (3/7);
# the isolated neutral glyphs at 6x read (0/1) identically in psm 7/8/13 on
# all three frames. The label OCR bottom varies 406..410 while the fraction
# spans y 416..431, so the band reaches 28 px below the label bottom and a
# glyph touching the band edge is treated as clipped.
_HUD_FRACTION_INK_MIN_VALUE = 150
_HUD_FRACTION_INK_MAX_SATURATION = 50
_HUD_FRACTION_BAND_BELOW_LABEL = 28


def _hud_queue_fraction_word(
    frame: Any, band: tuple[int, int, int, int], line_id: tuple[int, int, int],
) -> ResearchWord | None:
    """Read the queue fraction glyphs below the HUD label; every mode must agree.

    Agreement of the three string reads selects the text; the returned word
    keeps the actual TSV confidence of a psm 7 data read of the same crop,
    which must report exactly that text at the page confidence floor.
    """

    from scripts.bounded_tesseract import call_ocr, tesseract_data, tesseract_string

    x0, y0, x1, y1 = band
    if x1 - x0 < 12 or y1 - y0 < 8:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    ink = ((hsv[:, :, 2] >= _HUD_FRACTION_INK_MIN_VALUE) & (hsv[:, :, 1] <= _HUD_FRACTION_INK_MAX_SATURATION)).astype("uint8") * 255
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
    glyph_mask = ((labels > 0) & (stats[labels, cv2.CC_STAT_HEIGHT] >= 6)).astype("uint8") * 255 if count > 1 else ink * 0
    rows, columns = glyph_mask.nonzero()
    if not len(rows):
        return None
    gx0, gy0, gx1, gy1 = int(columns.min()), int(rows.min()), int(columns.max()), int(rows.max())
    if gy0 == 0 or gy1 == y1 - y0 - 1 or gx0 == 0 or gx1 == x1 - x0 - 1:
        return None
    glyphs = 255 - glyph_mask[gy0:gy1 + 1, gx0:gx1 + 1]
    padding = max(1, round((gy1 - gy0 + 1) * .15))
    glyphs = cv2.copyMakeBorder(glyphs, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255)
    glyphs = cv2.resize(glyphs, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    glyphs = cv2.copyMakeBorder(glyphs, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    whitelist = "-c tessedit_char_whitelist=0123456789/()"
    readings = {
        re.sub(r"\s+", "", str(call_ocr(tesseract_string, glyphs, config=f"--psm {mode} {whitelist}", call_timeout=5.0)))
        for mode in (7, 8, 13)
    }
    if len(readings) != 1:
        return None
    text = readings.pop()
    if not re.fullmatch(r"\([0-9]/[0-9]\)", text):
        return None
    data = call_ocr(tesseract_data, glyphs, config=f"--psm 7 {whitelist}", call_timeout=5.0)
    read = _ocr_words(data) if isinstance(data, Mapping) else ()
    if len(read) != 1 or read[0].text != text or read[0].confidence < _RESEARCH_PAGE_MIN_CONFIDENCE:
        return None
    return ResearchWord(text, _normalize(text), (x0 + gx0, y0 + gy0, x0 + gx1 + 1, y0 + gy1 + 1), read[0].confidence, line_id)


def _phrase_lines(lines: Sequence[tuple[ResearchWord, ...]], phrase: str) -> tuple[tuple[ResearchWord, ...], ...]:
    sought = _normalize(phrase)
    return tuple(line for line in lines if sought and sought in _normalize(_line_text(line)))


def _line_bounds(line: Sequence[ResearchWord]) -> tuple[int, int, int, int]:
    return (
        min(word.roi[0] for word in line),
        min(word.roi[1] for word in line),
        max(word.roi[2] for word in line),
        max(word.roi[3] for word in line),
    )


def _padded_roi(roi: tuple[int, int, int, int], *, pad_x: int = 22, pad_y: int = 17) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi
    return (max(0, x0 - pad_x), max(0, y0 - pad_y), min(800, x1 + pad_x), min(1280, y1 + pad_y))


def _inside(bounds: tuple[int, int, int, int], roi: tuple[int, int, int, int]) -> bool:
    return bounds[0] <= roi[0] < roi[2] <= bounds[2] and bounds[1] <= roi[1] < roi[3] <= bounds[3]


def _exact_word_lines(lines: Sequence[tuple[ResearchWord, ...]], normalized: str) -> tuple[tuple[ResearchWord, ...], ...]:
    return tuple(line for line in lines if _normalize(_line_text(line)) == normalized)


def _integer(value: str) -> int | None:
    text = value.replace(",", "")
    if not text.isascii() or not text.isdecimal():
        return None
    number = int(text)
    return number if str(number) == text.lstrip("0") or number == 0 else None


def _clock_seconds(value: str) -> int | None:
    match = _CLOCK_RE.search(value)
    if match is None:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    if minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _paired_amounts(line: str) -> tuple[int, int] | None:
    match = _RESEARCH_PANEL_RE.search(line)
    if match is None:
        return None
    balance, cost = (_integer(value) for value in match.groups())
    if balance is None or cost is None:
        return None
    return balance, cost


def _panel_bounds(lines: Sequence[tuple[ResearchWord, ...]], *, top: int, bottom: int) -> tuple[int, int, int, int] | None:
    selected = [word for line in lines for word in line if word.roi[3] >= top and word.roi[1] <= bottom]
    if not selected:
        return None
    return (
        max(0, min(word.roi[0] for word in selected) - 24),
        max(0, top - 24),
        min(800, max(word.roi[2] for word in selected) + 24),
        min(1280, max(bottom, max(word.roi[3] for word in selected)) + 24),
    )


def _queue1_from_lines(lines: Sequence[tuple[ResearchWord, ...]]) -> tuple[str, int | None]:
    research_lines = [line for line in lines if _normalize(
        _CLOCK_RE.sub("", _LEVEL_RE.sub("", _line_text(line)))) == "research"]
    if len(research_lines) != 1:
        return "unknown", None
    line = research_lines[0]
    value = _line_text(line)
    matches = list(_LEVEL_RE.finditer(value))
    count_bounds = _line_bounds(line)
    if not matches:
        # Global OCR order can interleave unrelated right-side HUD lines.
        # Associate one numeric fraction geometrically with this Research label.
        candidates = []
        for candidate in lines:
            candidate_value = _line_text(candidate)
            candidate_bounds = _line_bounds(candidate)
            fractions = list(_LEVEL_RE.finditer(candidate_value))
            if (len(fractions) == 1 and not _normalize(_LEVEL_RE.sub("", candidate_value))
                    and 0 <= candidate_bounds[1] - count_bounds[3] <= 60
                    and candidate_bounds[0] <= count_bounds[2] + 35
                    and count_bounds[0] <= candidate_bounds[2] + 35):
                candidates.append((fractions[0], candidate_bounds))
        if len(candidates) != 1:
            return "unknown", None
        match, count_bounds = candidates[0]
    elif len(matches) == 1:
        match = matches[0]
    else:
        return "unknown", None
    current, maximum = (int(part) for part in match.groups())
    if (current, maximum) == (0, 1):
        return "idle", None
    if (current, maximum) == (1, 1):
        times = [_clock_seconds(value)]
        for candidate in lines:
            x0, y0, x1, _y1 = _line_bounds(candidate)
            if 0 <= y0 - count_bounds[3] <= 90 and x0 <= 180 and x1 <= 180:
                times.append(_clock_seconds(_line_text(candidate)))
        remaining = [item for item in times if item is not None and item > 0]
        return ("busy", remaining[0]) if len(remaining) == 1 else ("busy", None)
    return "unknown", None


def _resource_pairs_from_lines(
    lines: Sequence[tuple[ResearchWord, ...]], *, after_y: int
) -> tuple[tuple[int, int], ...]:
    pairs: list[tuple[int, int]] = []
    for line in lines:
        if _line_bounds(line)[1] <= after_y:
            continue
        amount_words = [
            word for word in line
            if word.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE
            and re.fullmatch(r"(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)/(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*|[1-9][0-9]*)", word.text)
        ]
        pair = _paired_amounts(amount_words[0].text) if len(amount_words) == 1 else None
        if pair is not None:
            pairs.append(pair)
    return tuple(pairs)


def _resource_rows_from_pairs(pairs: Sequence[tuple[int, int]]) -> tuple[ResearchResourceRow, ...]:
    if len(pairs) != len(RESEARCH_RESOURCES):
        return ()
    return tuple(
        ResearchResourceRow(resource, cost, balance)
        for resource, (balance, cost) in zip(RESEARCH_RESOURCES, pairs)
    )


def _merge_top_and_scrolled_resource_rows(
    top_pairs: Sequence[tuple[int, int]],
    scrolled_pairs: Sequence[tuple[int, int]],
) -> tuple[ResearchResourceRow, ...]:
    if len(scrolled_pairs) == len(RESEARCH_RESOURCES):
        return _resource_rows_from_pairs(scrolled_pairs)
    if len(top_pairs) == len(RESEARCH_RESOURCES):
        return _resource_rows_from_pairs(top_pairs)
    if (
        len(top_pairs) == 2
        and len(scrolled_pairs) == 3
        and top_pairs[1] == scrolled_pairs[0]
        and sum(pair == top_pairs[1] for pair in (*top_pairs, *scrolled_pairs)) == 2
    ):
        return _resource_rows_from_pairs((top_pairs[0], top_pairs[1], scrolled_pairs[1], scrolled_pairs[2]))
    return ()

def _red_text(frame: Any, line: Sequence[ResearchWord]) -> bool | None:
    """Inspect text ROIs only: beige requirement text is not red shortage ink."""
    red_pixels = bright_pixels = 0
    for word in line:
        if word.confidence < _RESEARCH_PAGE_MIN_CONFIDENCE:
            continue
        x0, y0, x1, y1 = word.roi
        hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        bright_pixels += int((value >= 150).sum())
        red_pixels += int((((hue <= 8) | (hue >= 170)) & (saturation >= 120) & (value >= 150)).sum())
    if bright_pixels < 12:
        return None
    return red_pixels >= 12 and red_pixels >= bright_pixels * 0.25


def recognize_research_screen(
    frame: Any,
    *,
    source_frame_sha256: str,
    evidence_refs: Sequence[str],
    home_recognized: bool = False,
    ocr_data: Mapping[str, object] | None = None,
    expected_detail_identity: str | None = None,
) -> ResearchScreenObservation:
    """Recognize a recommendation list/detail only from their complete current UI markers."""

    refs = tuple(str(item) for item in evidence_refs)
    if not native_frame_guard(frame) or not _DIGEST_RE.fullmatch(source_frame_sha256 or ""):
        return ResearchScreenObservation("UNKNOWN", source_frame_sha256 or "", refs, "", (), recognized=False)
    words = _read_words(frame, ocr_data)
    if home_recognized and ocr_data is None:
        words = _home_research_hud_words(frame, words)
    elif ocr_data is None:
        words = _research_page_words(frame, words)
    lines = _line_groups(words)
    text = "\n".join(_line_text(line) for line in lines)
    normalized_text = _normalize(text)
    if any(marker in normalized_text for marker in _UNSAFE_OVERLAY_MARKERS):
        return ResearchScreenObservation(
            "UNKNOWN",
            source_frame_sha256,
            refs,
            text,
            words,
            overlay_state="unknown",
            recognized=False,
        )
    title_lines = tuple(
        line for line in _phrase_lines(lines, "Research Center")
        if _line_bounds(line)[1] < 180
    )
    categories = [
        line for line in lines
        if _line_bounds(line)[3] < 90 and _normalize(_line_text(line)) in _RESEARCH_TREE_CATEGORIES
    ]
    recommendation_lines = tuple(
        line for line in lines
        if "recomd" in _normalize(_line_text(line)) or "recommended" in _normalize(_line_text(line))
    )
    time_actual_lines = _phrase_lines(lines, "Actual Time")
    time_original_lines = _phrase_lines(lines, "Original Time")
    research_now_lines = _phrase_lines(lines, "Research Now")

    if title_lines and recommendation_lines:
        header = min(recommendation_lines, key=lambda line: _line_bounds(line)[1])
        header_bottom = _line_bounds(header)[3]
        buttons = [
            line for line in _exact_word_lines(lines, "research")
            if _line_bounds(line)[1] > header_bottom and _line_bounds(line)[0] > 330
        ]
        buttons.sort(key=lambda line: (_line_bounds(line)[1], _line_bounds(line)[0]))
        if len(buttons) >= 2:
            first_button = buttons[0]
            bx0, by0, bx1, by1 = _line_bounds(first_button)
            candidates = []
            for line in lines:
                x0, y0, x1, y1 = _line_bounds(line)
                if y1 <= header_bottom or y0 > by1 + 14 or x0 >= bx0 - 8:
                    continue
                words_left = [word for word in line if word.roi[2] <= bx0 - 8 and word.normalized not in {"research", "recomd", "recommended"}]
                if words_left:
                    candidates.append((abs(((y0 + y1) / 2) - ((by0 + by1) / 2)), y0, words_left))
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                title = _canonical_title(" ".join(word.text for word in sorted(candidates[0][2], key=lambda item: item.roi[0])).strip())
                identity = research_identity(title)
                page_bounds = _panel_bounds(lines, top=header_bottom - 20, bottom=max(_line_bounds(line)[3] for line in buttons) + 24)
                button_roi = _padded_roi((bx0, by0, bx1, by1))
                if identity and page_bounds and _inside(page_bounds, button_roi):
                    return ResearchScreenObservation(
                        screen_state=LIST_SCREEN,
                        frame_sha256=source_frame_sha256,
                        evidence_refs=refs,
                        text=text,
                        words=words,
                        first_recommendation_title=title,
                        first_recommendation_identity=identity,
                        recommendation_position=1,
                        list_research_target_roi=button_roi,
                        panel_bounds=page_bounds,
                        queue1_state="unknown",
                        recognized=True,
                    )

    detail_title_line = None
    selected_title = None
    selected_identity = None
    current_level = target_level = None
    for line in lines:
        if _line_bounds(line)[1] <= 500:
            continue
        value = _line_text(line)
        match = _LEVEL_RE.search(value)
        title = _canonical_title(value[:match.start()].strip(" ():-") if match else value)
        identity = research_identity(title)
        if identity is None or (expected_detail_identity is not None and identity != expected_detail_identity):
            continue
        if match is None and expected_detail_identity is None:
            continue
        detail_title_line = line
        selected_title = title
        selected_identity = identity
        if match is not None:
            current_level, target_level = (int(part) for part in match.groups())
        break

    if detail_title_line is not None:
        detail_title_bounds = _line_bounds(detail_title_line)
        has_time_pair = bool(time_actual_lines and time_original_lines)
        # Completeness is bounded by the visible time section and first cost
        # row; do not replace the displayed requirements with a Center schema.
        time_bottom = max(
            (_line_bounds(line)[3] for line in lines
             if _line_bounds(line)[1] >= detail_title_bounds[3]
             and _CLOCK_RE.search(_line_text(line))),
            default=detail_title_bounds[3],
        )
        cost_top = min(
            (_line_bounds(line)[1] for line in lines
             if _line_bounds(line)[1] > time_bottom and _paired_amounts(_line_text(line)) is not None),
            default=time_bottom,
        )
        prereq_lines = tuple(
            line for line in lines
            if has_time_pair and time_bottom < _line_bounds(line)[1] < cost_top
            and any(word.normalized.isalpha() or "lv" in word.normalized for word in line)
        )
        prerequisite_text = tuple(_line_text(line) for line in prereq_lines)
        prerequisite_evidence = tuple(
            slug for line in prerequisite_text if (slug := research_identity(line)) is not None
        )
        prereq_known = bool(
            has_time_pair and cost_top > time_bottom
            and len(prerequisite_evidence) == len(prereq_lines)
            and all(re.search(r"\b(?:lv\.?|level)\s*[0-9]{1,3}\b", line, re.IGNORECASE) for line in prerequisite_text)
        )
        prerequisite_tones = tuple(_red_text(frame, line) for line in prereq_lines)
        prereq_known = prereq_known and all(tone is not None for tone in prerequisite_tones)
        prereq_met = prereq_known and not any(prerequisite_tones)
        if prereq_known and not prerequisite_evidence:
            prerequisite_evidence = ("no-displayed-prerequisites",)
        prerequisite_level = None
        for line in prerequisite_text:
            match = re.search(r"Research Center:\s*Lv\.?\s*([0-9]+)", line, re.IGNORECASE)
            if match:
                prerequisite_level = int(match.group(1))
        pairs = _resource_pairs_from_lines(
            lines,
            after_y=max([detail_title_bounds[3], *(_line_bounds(line)[3] for line in prereq_lines)]),
        )
        resource_rows = _resource_rows_from_pairs(pairs)
        button_lines = [
            line for line in _exact_word_lines(lines, "research")
            if _line_bounds(line)[1] > detail_title_bounds[1] and _line_bounds(line)[0] > 320
        ]
        button_lines.sort(key=lambda line: (_line_bounds(line)[1], _line_bounds(line)[0]))
        detail_button_roi = _padded_roi(_line_bounds(button_lines[-1])) if button_lines else None
        now_line = min(research_now_lines, key=lambda line: _line_bounds(line)[1]) if research_now_lines else None
        now_bounds = _line_bounds(now_line) if now_line is not None else None
        actual_time = _clock_seconds(" ".join(_line_text(line) for line in time_actual_lines))
        if actual_time is None:
            # Actual sheet prints both clocks on the row below their labels:
            # take the one clock directly under the single "Actual" label.
            labels = [word for line in time_actual_lines for word in line if word.normalized == "actual"]
            if len(labels) == 1:
                lx0, _ly0, _lx1, ly1 = labels[0].roi
                clocks = [
                    word for word in words
                    if _CLOCK_RE.fullmatch(word.text.strip())
                    and 0 <= word.roi[1] - ly1 <= 40
                    and abs(word.roi[0] - lx0) <= 30
                ]
                if len(clocks) == 1:
                    actual_time = _clock_seconds(clocks[0].text)
        if now_bounds is not None and detail_button_roi is not None and detail_button_roi[0] <= now_bounds[2]:
            # The ordinary control must be the one right of Research Now.
            detail_button_roi = None
        panel_top = detail_title_bounds[1] - 24
        panel_bottom = max(_line_bounds(line)[3] for line in lines if _line_bounds(line)[1] >= panel_top)
        panel = _panel_bounds(lines, top=panel_top, bottom=panel_bottom)
        if panel is not None and detail_button_roi is not None and not _inside(panel, detail_button_roi):
            detail_button_roi = None
        scroll_roi = None
        if panel is not None:
            scroll_roi = (
                max(0, panel[0] + 12),
                max(panel[1], detail_title_bounds[3] + 10),
                min(800, panel[2] - 12),
                min(1280, panel[3] - 76),
            )
        top_detail = bool(
            has_time_pair
            and actual_time is not None
            and current_level is not None
            and target_level is not None
            and detail_button_roi is not None
        )
        scrolled_detail = bool(
            selected_identity is not None
            and (
                selected_identity == expected_detail_identity
                if expected_detail_identity is not None
                else len(categories) == 1 and len(pairs) == len(RESEARCH_RESOURCES)
            )
            and now_bounds is not None
            and detail_button_roi is not None
            and len(pairs) >= 2
            and not title_lines
            and not recommendation_lines
        )
        if top_detail or scrolled_detail:
            return ResearchScreenObservation(
                screen_state=DETAIL_SCREEN,
                frame_sha256=source_frame_sha256,
                evidence_refs=refs,
                text=text,
                words=words,
                selected_technology_title=selected_title,
                selected_technology_identity=selected_identity,
                recommendation_position=1,
                detail_research_target_roi=detail_button_roi,
                research_now_target_roi=_padded_roi(now_bounds) if now_bounds is not None else None,
                panel_bounds=panel,
                scroll_roi=scroll_roi,
                current_level=current_level,
                target_level=target_level,
                prerequisite_lines=prerequisite_text,
                prerequisite_level=prerequisite_level,
                prerequisite_evidence=prerequisite_evidence,
                prerequisites_known=prereq_known,
                prerequisites_met=prereq_met,
                resource_ink_conflict=any(
                    _red_text(frame, tuple(word for word in line if "/" in word.text))
                    and (pair := _paired_amounts(_line_text(line))) is not None
                    and pair[0] >= pair[1]
                    for line in lines if _line_bounds(line)[1] > detail_title_bounds[3]
                ),
                resource_pairs=pairs,
                resource_rows=resource_rows,
                requirements_scrolled=len(pairs) >= 3,
                duration_seconds=actual_time,
                recognized=True,
            )

    # The live countdown must identify this technology, not either static
    # Original/Actual Time quote. A still-visible ordinary start is not active.
    active_markers = [
        line for line in lines
        if any(marker in _normalize(_line_text(line)) for marker in ("researching", "researchinprogress"))
    ]
    active_titles = []
    for line in lines:
        raw_title = _line_text(line)
        for marker in ("Researching", "Research in Progress"):
            raw_title = re.sub(marker, "", raw_title, flags=re.IGNORECASE).strip(" :-")
        raw_title = _LEVEL_RE.sub("", raw_title).strip()
        identity = research_identity(_canonical_title(raw_title))
        if identity and (
            identity == expected_detail_identity if expected_detail_identity is not None else line in active_markers
        ):
            active_titles.append((_canonical_title(raw_title), line))
    static_labels = (*time_original_lines, *time_actual_lines)
    timers = [
        word for word in words if _CLOCK_RE.fullmatch(word.text.strip())
        and not any(-20 <= word.roi[1] - _line_bounds(label)[3] <= 50 for label in static_labels)
    ]
    ordinary_start = any(
        _line_bounds(line)[0] > 320 and _line_bounds(line)[1] > 500
        for line in _exact_word_lines(lines, "research")
    )
    # The observed post-start detail retains both static time quotes and
    # repeats its live countdown in "No idle queue" and the bottom progress
    # bar. Help replaces Research; neither duplicate clocks nor the distant
    # detail heading makes this same-technology successor ambiguous.
    if detail_title_line is not None and selected_identity is not None:
        detail_bottom = _line_bounds(detail_title_line)[3]
        no_idle_queue = any(
            "noidlequeue" in _normalize(_line_text(line))
            and _line_bounds(line)[1] > detail_bottom
            for line in lines
        )
        help_visible = any(
            word.normalized == "help"
            and word.roi[0] > 320 and word.roi[1] > detail_bottom
            for word in words
        )
        detail_timers = [
            word for word in timers if word.roi[1] > detail_bottom
        ]
        countdowns = {_clock_seconds(word.text) for word in detail_timers}
        if (
            no_idle_queue and help_visible and not ordinary_start
            and not research_now_lines and len(countdowns) == 1
            and (remaining := next(iter(countdowns))) is not None
            and remaining > 0
        ):
            return ResearchScreenObservation(
                screen_state=ACTIVE_SCREEN, frame_sha256=source_frame_sha256,
                evidence_refs=refs, text=text, words=words,
                active_title=selected_title, active_identity=selected_identity,
                active_remaining_seconds=remaining, recognized=True,
            )
    if active_titles and len(timers) == 1 and not ordinary_start and not research_now_lines:
        title, title_line = min(active_titles, key=lambda item: abs(_line_bounds(item[1])[1] - timers[0].roi[1]))
        if abs(_line_bounds(title_line)[1] - timers[0].roi[1]) <= 160:
            return ResearchScreenObservation(
                screen_state=ACTIVE_SCREEN, frame_sha256=source_frame_sha256,
                evidence_refs=refs, text=text, words=words, active_title=title,
                active_identity=research_identity(title),
                active_remaining_seconds=_clock_seconds(timers[0].text),
                recognized=True,
            )

    if (
        not home_recognized
        and not title_lines
        and not recommendation_lines
        and not time_actual_lines
        and not time_original_lines
        and not research_now_lines
    ):
        if len(categories) == 1:
            return ResearchScreenObservation(
                screen_state=TREE_SCREEN,
                frame_sha256=source_frame_sha256,
                evidence_refs=refs,
                text=text,
                words=words,
                research_category=_line_text(categories[0]),
                recognized=True,
            )
    queue_state, queue_remaining = _queue1_from_lines(lines)
    if home_recognized:
        return ResearchScreenObservation(
            screen_state="HOME_BASE",
            frame_sha256=source_frame_sha256,
            evidence_refs=refs,
            text=text,
            words=words,
            queue1_state=queue_state,
            queue1_remaining_seconds=queue_remaining,
            recognized=True,
        )
    return ResearchScreenObservation("UNKNOWN", source_frame_sha256, refs, text, words, recognized=False)


# Measured actual Details/Research captions read 96 on both real radial frames;
# lower reads are not owner evidence. Upgrade sits under its white arrow icon
# and the mask can merge them (actual '“Upgrade' conf 41), so it is not required.
_RADIAL_CAPTION_MIN_CONFIDENCE = 80.0
_RADIAL_REQUIRED_CAPTIONS = ("details", "research")


def recognize_research_radial(
    frame: Any,
    *,
    source_frame_sha256: str,
    evidence_refs: Sequence[str],
    building_binding: BuildingBinding,
    home_recognized: bool,
    ocr_data: Mapping[str, object] | None = None,
) -> ResearchScreenObservation | None:
    """Bind radial Research near a freshly localized owner, not the Home HUD label."""

    if (
        not native_frame_guard(frame)
        or not _DIGEST_RE.fullmatch(source_frame_sha256 or "")
        or not home_recognized
        or building_binding.building_id != RESEARCH_CENTER_ID
        or building_binding.screen_anchor is None
    ):
        return None
    ax, ay = building_binding.screen_anchor
    captions: list[ResearchWord] = []
    if ocr_data is None:
        # Native frames: exactly one owner Details and one Research caption.
        captions = [
            word for word in _radial_caption_words(frame, (ax, ay))
            if word.confidence >= _RADIAL_CAPTION_MIN_CONFIDENCE
        ]
        if any(sum(word.normalized == name for word in captions) != 1 for name in _RADIAL_REQUIRED_CAPTIONS):
            return None
        details = next(word for word in captions if word.normalized == "details")
        if not 35 <= math.hypot(details.center[0] - ax, details.center[1] - ay) <= 240:
            return None
    page = recognize_research_screen(
        frame,
        source_frame_sha256=source_frame_sha256,
        evidence_refs=evidence_refs,
        home_recognized=False,
        ocr_data=ocr_data,
    )
    if page.screen_state in {LIST_SCREEN, DETAIL_SCREEN, ACTIVE_SCREEN}:
        return None
    if ocr_data is None:
        research_words = (word for word in captions if word.normalized == "research")
    else:
        research_words = (
            word
            for line in _line_groups(page.words)
            if _normalize(_line_text(line)) == "research"
            for word in line
        )
    choices = [
        word for word in research_words
        if word.normalized == "research"
        and math.hypot(word.center[0] - ax, word.center[1] - ay) <= 240
        and math.hypot(word.center[0] - ax, word.center[1] - ay) >= 35
    ]
    if len(choices) != 1:
        return None
    target = _padded_roi(choices[0].roi)
    if not (0 <= target[0] < target[2] <= 800 and 0 <= target[1] < target[3] <= 1280):
        return None
    return ResearchScreenObservation(
        screen_state="RESEARCH_RADIAL",
        frame_sha256=source_frame_sha256,
        evidence_refs=tuple(evidence_refs),
        text=page.text,
        words=page.words,
        owner_building_id=RESEARCH_CENTER_ID,
        owner_screen_anchor=building_binding.screen_anchor,
        list_research_target_roi=target,
        panel_bounds=(max(0, int(ax - 240)), max(0, int(ay - 240)), min(800, int(ax + 240)), min(1280, int(ay + 240))),
        recognized=True,
    )


def research_center_successor_verified(
    source: ResearchScreenObservation,
    successor: ResearchScreenObservation | None,
) -> bool:
    """Require a route-owned Research radial successor plus the actual Research Center page."""

    return bool(
        source.screen_state == "RESEARCH_RADIAL"
        and source.owner_building_id == RESEARCH_CENTER_ID
        and source.owner_screen_anchor is not None
        and successor is not None
        and successor.screen_state == LIST_SCREEN
        and successor.recognized is True
        and successor.frame_sha256 != source.frame_sha256
        and successor.first_recommendation_identity
        and successor.recommendation_position == 1
        and successor.list_research_target_roi is not None
    )


def _capture_ref(context: Any, captured: Any) -> str:
    try:
        path = Path(captured.path).resolve().relative_to(Path(context.runtime.session).resolve()).as_posix()
    except (OSError, ValueError, TypeError):
        path = ""
    if not path or not _DIGEST_RE.fullmatch(str(captured.sha256 or "")):
        return ""
    return f"native:{path}:{captured.sha256}"


def _source_screen(
    context: Any,
    captured: Any,
    *,
    expected_detail_identity: str | None = None,
) -> ResearchScreenObservation:
    ref = _capture_ref(context, captured)
    if not native_frame_guard(captured.frame) or not _DIGEST_RE.fullmatch(str(captured.sha256)):
        return ResearchScreenObservation("UNKNOWN", str(captured.sha256), (ref,) if ref else (), "", (), recognized=False)
    # Decode immutable captured pixels once per invocation, never re-date them.
    # The pixel digest prevents mutated frames or a reused source identity from
    # turning this OCR memo into cached current-screen authority.
    key = (str(captured.sha256), float(captured.captured_monotonic),
           expected_detail_identity, ref, hashlib.sha256(captured.frame.tobytes()).hexdigest())
    cache = getattr(context, "_recommended_research_screen_cache", None)
    if cache is None:
        cache = {}
        context._recommended_research_screen_cache = cache
    if key not in cache:
        cache[key] = recognize_research_screen(
            captured.frame,
            source_frame_sha256=str(captured.sha256),
            evidence_refs=(ref,) if ref else (),
            home_recognized=context.is_clean_home(captured.frame),
            expected_detail_identity=expected_detail_identity,
        )
    return cache[key]


def _binding_for_home(context: Any, frame: Any, localizer: BlueStacksHomeLocalizer, building: Any) -> BuildingBinding | None:
    pixels = hashlib.sha256(frame.tobytes()).hexdigest()
    if not context.is_clean_home(frame):
        return None
    localization = localizer.localize(frame, home_recognized=True)
    # Binding re-asks for clean Home on the same frame. This exact unchanged
    # array was just classified; any other or mutated frame is classified anew.
    # A repeated ~1.5 s classification here pushed the SDK immediate-before
    # source past the 5 s dispatch age (retained research76 221908 run).
    return bind_visible_building(
        frame,
        localization,
        building,
        home_is_clean=lambda candidate: (
            candidate is frame and hashlib.sha256(candidate.tobytes()).hexdigest() == pixels
        ) or context.is_clean_home(candidate),
    )


def _research_center_level(frame: Any, binding: BuildingBinding | None) -> int | None:
    """Read the owned Research Center's level badge through its own caption.

    Actual Home (0008, binding roi (320,230,462,394)): the caption "Research
    Center" sits on the binding's lower edge and every building's level badge
    is one dark plate up-right of its caption (measured caption-right to
    plate-left 18..32 px, plate bottom 19..23 px above the caption top on
    Research Center, Warehouse and Hall of War). A nearest Home number is not
    owner evidence; only the plate bound to this caption is read.

    The plate's 8-px digits are read like the existing material labels: the
    neutral white glyphs only, 15% padding, 6x cubic, and every reading must
    agree. Measured on actual Homes 0008/0027 (16 plates), this gave Research
    Center 24, Warehouse 24, Gear Factory 24 and Pit 22 exactly; Rider Camp,
    Hall of War and one Supply Depot read disagreed and stayed unknown, and no
    plate produced an agreed wrong value. Tesseract confidence was not usable
    (Research Center '24' at 19..65).
    """

    if binding is None or binding.ambiguous_overlap or binding.overlay_intersects:
        return None
    from scripts.bounded_tesseract import call_ocr, tesseract_string

    height, width = frame.shape[:2]
    tx0, _ty0, tx1, ty1 = (int(round(value)) for value in binding.target_roi)
    band = (max(0, tx0 - 60), max(0, ty1 - 24), min(width, tx1 + 60), min(height, ty1 + 40))
    if band[2] - band[0] < 24 or band[3] - band[1] < 12:
        return None
    words = [word for word in _prepared_crop_words(frame, band, _gray, "--psm 6") if word.normalized]
    captions = [
        (first, second) for first in words for second in words
        if first.normalized == "research" and second.normalized == "center"
        and first.confidence >= _RESEARCH_PAGE_MIN_CONFIDENCE and second.confidence >= 60
        and 0 <= second.roi[0] - first.roi[2] <= 12
        and abs(first.center[1] - second.center[1]) <= 6
    ]
    if len(captions) != 1:
        return None
    first, second = captions[0]
    cx0, cy0, cx1 = first.roi[0], min(first.roi[1], second.roi[1]), second.roi[2]
    if not tx0 <= (cx0 + cx1) / 2 <= tx1:
        return None
    wx0, wy0, wx1, wy1 = cx1, max(0, cy0 - 50), min(width, cx1 + 80), cy0
    if wx1 - wx0 < 30 or wy1 - wy0 < 20:
        return None
    window = frame[wy0:wy1, wx0:wx1]
    dark = (cv2.cvtColor(window, cv2.COLOR_BGR2HSV)[:, :, 2] < 70).astype("uint8")
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    plates = [
        tuple(int(value) for value in stats[index][:4]) for index in range(1, count)
        if 18 <= stats[index][2] <= 44 and 10 <= stats[index][3] <= 20
        and stats[index][4] >= 0.6 * stats[index][2] * stats[index][3]
        and 10 <= stats[index][0] <= 40
        and 15 <= wy1 - wy0 - (stats[index][1] + stats[index][3]) <= 30
    ]
    plate_inset = 1
    if not plates:
        # Actual night Home200932 frames0002/0024: the <70 terrain merges
        # into the plate, so darkness alone has no isolated component.
        # Its closed rim remains unique in this same caption-owned window:
        # 29x15, inset2 excludes the rim while retaining the complete digits.
        # This is plate segmentation only; the two ink cuts and all six OCR
        # readings below are unchanged. Ambiguous dark plates never recover.
        edges = cv2.Canny(cv2.cvtColor(window, cv2.COLOR_BGR2GRAY), 60, 160)
        contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            px, py, pw, ph = cv2.boundingRect(contour)
            if (
                18 <= pw <= 44 and 10 <= ph <= 20
                and cv2.contourArea(contour) >= .6 * pw * ph
                and 10 <= px <= 40
                and 15 <= wy1 - wy0 - (py + ph) <= 30
            ):
                interior = window[py + 2:py + ph - 2, px + 2:px + pw - 2]
                interior_dark = cv2.cvtColor(interior, cv2.COLOR_BGR2HSV)[:, :, 2] < 70
                if int(interior_dark.sum()) >= .6 * interior_dark.size:
                    plates.append((px, py, pw, ph))
        plate_inset = 2
    if len(plates) != 1:
        return None
    px, py, pw, ph = plates[0]
    plate = cv2.cvtColor(window[py + plate_inset:py + ph - plate_inset, px + plate_inset:px + pw - plate_inset], cv2.COLOR_BGR2HSV)
    readings = []
    for minimum_value in _RESEARCH_CENTER_PLATE_INK_VALUES:
        ink = ((plate[:, :, 2] >= minimum_value) & (plate[:, :, 1] <= 60)).astype("uint8") * 255
        # Actual panned Home0007: both glyphs are 8px tall inside this
        # caption-owned plate; its slanted right edge leaves 1..5px fragments
        # in the outer four columns (largest 3x4). At cut140 a single border
        # pixel x23 of25 enlarged the OCR crop and produced a spurious "0".
        # Remove only those small peripheral fragments, never interior ink or
        # a glyph-height component. Both cuts/all three modes must still agree.
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
        for index in range(1, count):
            ix, _iy, iw, ih, area = (int(value) for value in stats[index])
            peripheral = ix + iw <= 4 or ix >= ink.shape[1] - 4
            if peripheral and iw <= 3 and ih <= 4 and area <= 5:
                ink[labels == index] = 0
        rows, columns = ink.nonzero()
        if not len(rows):
            return None
        glyphs = 255 - ink[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
        padding = max(1, round((rows.max() - rows.min() + 1) * .15))
        glyphs = cv2.copyMakeBorder(glyphs, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255)
        glyphs = cv2.resize(glyphs, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        glyphs = cv2.copyMakeBorder(glyphs, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        readings.extend(
            re.sub(r"\s+", "", str(call_ocr(
                tesseract_string, glyphs,
                config=f"--psm {mode} -c tessedit_char_whitelist=0123456789", call_timeout=5.0,
            )))
            for mode in (7, 8, 13)
        )
    if len(set(readings)) != 1 or not re.fullmatch(r"[1-9][0-9]?", readings[0]):
        return None
    return int(readings[0])


# Two neutral-ink cuts of the same plate; all six readings must agree.
_RESEARCH_CENTER_PLATE_INK_VALUES = (110, 140)


def _list_observation(screen: ResearchScreenObservation, context: Any) -> RecommendedResearchListObservation | None:
    if (
        screen.screen_state != LIST_SCREEN
        or not screen.recognized
        or not screen.first_recommendation_title
        or not screen.first_recommendation_identity
        or screen.list_research_target_roi is None
        or screen.panel_bounds is None
    ):
        return None
    return RecommendedResearchListObservation(
        screen_state=LIST_SCREEN,
        recomd_section_visible=True,
        first_recommendation_title=screen.first_recommendation_title,
        first_recommendation_identity=screen.first_recommendation_identity,
        recommendation_position=1,
        target_identity=f"recommended-research:{screen.first_recommendation_identity}:list-research-button",
        target_roi=screen.list_research_target_roi,
        panel_bounds=screen.panel_bounds,
        control_class="RESEARCH_NAVIGATE",
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=screen.frame_sha256,
        evidence_refs=screen.evidence_refs,
        overlay_state=screen.overlay_state,
        runtime_profile_id=PROFILE_ID,
        recognized=True,
    )


def _detail_observation(
    screen: ResearchScreenObservation,
    listing: RecommendedResearchListObservation,
    context: Any,
    *,
    costs: tuple[ResearchResourceRow, ...],
    scrolled_refs: Sequence[str],
    top_screen: ResearchScreenObservation | None = None,
) -> TechUpgradeObservation | None:
    top = top_screen if top_screen is not None else screen
    if (
        screen.screen_state != DETAIL_SCREEN
        or not screen.recognized
        or screen.selected_technology_title is None
        or screen.selected_technology_identity is None
        or screen.selected_technology_identity != listing.first_recommendation_identity
        or research_identity(screen.selected_technology_title) != listing.first_recommendation_identity
        or screen.detail_research_target_roi is None
        or screen.panel_bounds is None
        or screen.research_now_target_roi is None
        or len(costs) != len(RESEARCH_RESOURCES)
    ):
        return None
    if (
        top.selected_technology_identity != screen.selected_technology_identity
        or top.current_level is None or top.target_level is None
        or top.duration_seconds is None or screen.resource_ink_conflict
    ):
        return None
    selected_title = screen.selected_technology_title
    selected_identity = screen.selected_technology_identity
    prereq_known = top.prerequisites_known
    prereq_met = top.prerequisites_met
    current_center_level = getattr(context, "_recommended_research_center_level", None)
    if type(current_center_level) is int and top.prerequisite_level is not None:
        prereq_met = prereq_met and current_center_level >= top.prerequisite_level
    evidence = tuple(top.prerequisite_evidence)
    if prereq_known and not prereq_met:
        evidence = tuple(f"{item}-unmet" for item in evidence)
    return TechUpgradeObservation(
        screen_state=DETAIL_SCREEN,
        recommendation_frame_sha256=listing.source_frame_sha256,
        first_recommendation_title=listing.first_recommendation_title,
        first_recommendation_identity=listing.first_recommendation_identity,
        recommendation_position=1,
        selected_technology_title=selected_title,
        selected_technology_identity=selected_identity,
        current_level=top.current_level,
        target_level=top.target_level,
        prerequisites_known=prereq_known,
        prerequisites_met=prereq_met,
        prerequisite_evidence=evidence,
        queue1_state=getattr(context, "_recommended_research_queue1_state", "unknown"),
        queue1_remaining_seconds=getattr(context, "_recommended_research_queue1_remaining", None),
        queue2_activate_tapped=False,
        requirements_scrolled=True,
        resource_rows=tuple(costs),
        duration_seconds=top.duration_seconds,
        target_identity=f"recommended-research:{selected_identity}:detail-research-button",
        target_roi=screen.detail_research_target_roi,
        panel_bounds=screen.panel_bounds,
        control_class="RESEARCH_START",
        research_start_visible=True,
        research_now_target_identity="research-now-diamonds",
        research_now_tapped=False,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=screen.frame_sha256,
        evidence_refs=tuple(dict.fromkeys((*listing.evidence_refs, *top.evidence_refs, *screen.evidence_refs, *scrolled_refs))),
        overlay_state=screen.overlay_state,
        runtime_profile_id=PROFILE_ID,
        recognized=True,
    )

def _research_visit_identity(context: Any) -> tuple[Any, ...]:
    return (
        id(context), context.invocation_id, context.occurrence_key, context.owner,
        context.session.owner, str(context.runtime.session), repr(context.identity),
    )


def _research_visit_valid(context: Any) -> bool:
    proof = getattr(context, "_recommended_research_visit", None)
    accounting = context.accounting()
    return bool(
        isinstance(proof, dict) and proof.get("valid") is True
        and proof.get("identity") == _research_visit_identity(context)
        and proof.get("action_keys") == tuple(context.runtime.action_keys)
        and proof.get("input_count") == context.runtime.input_count
        and accounting.verified is True
        and accounting.input_count == accounting.session_input_count
        == accounting.runtime_input_count == proof.get("input_count")
        and context.action_store.lease_valid_for(context.owner, context.utc_clock())
        and not context.action_store.has_action_block()
    )



def _fresh_start_detail(
    context: Any, *, captured: Any, screen: ResearchScreenObservation,
    home: Any, home_binding: BuildingBinding, listing_capture: Any,
    listing: RecommendedResearchListObservation, quote_capture: Any,
    quote_screen: ResearchScreenObservation, expected: TechUpgradeObservation,
) -> TechUpgradeObservation | None:
    """Retain phase-fresh entry/selection only across verified exclusive navigation.

    Original source timestamps and phase-use times remain unchanged. Detail and
    resource affordability are still fresh at consuming use, not inherited from
    entry or a previous visit.
    """
    context.checkpoint()
    context.validate_identity()
    proof = getattr(context, "_recommended_research_visit", None)
    now = context.monotonic_clock()
    if not _research_visit_valid(context):
        return None
    sources = (quote_capture, captured)
    if any(not 0 <= now - source.captured_monotonic <= 10.0 for source in sources):
        return None
    if proof.get("home_source") != (home.sha256, home.captured_monotonic):
        return None
    if proof.get("home_binding") != home_binding or home_binding.building_id != RESEARCH_CENTER_ID:
        return None
    if proof.get("list_source") != (listing_capture.sha256, listing_capture.captured_monotonic):
        return None
    if (
        not native_frame_guard(home.frame) or not native_frame_guard(listing_capture.frame)
        or proof["home_pixels"] != hashlib.sha256(home.frame.tobytes()).hexdigest()
        or proof["list_pixels"] != hashlib.sha256(listing_capture.frame.tobytes()).hexdigest()
    ):
        return None
    top_capture = proof.get("detail_capture")
    top_screen = proof.get("detail_screen")
    if top_capture is None or top_screen is None:
        return None
    if (
        proof.get("detail_pixels") != hashlib.sha256(top_capture.frame.tobytes()).hexdigest()
        or not native_frame_guard(top_capture.frame)
        or not 0 <= proof.get("detail_used_at", -1) - top_capture.captured_monotonic <= 10.0
        or not listing_capture.captured_monotonic <= top_capture.captured_monotonic <= quote_capture.captured_monotonic
    ):
        return None
    if not (
        0 <= proof["home_used_at"] - home.captured_monotonic <= 10.0
        and 0 <= proof["list_used_at"] - listing_capture.captured_monotonic <= 10.0
        and home.captured_monotonic <= listing_capture.captured_monotonic
        <= quote_capture.captured_monotonic <= captured.captured_monotonic
        and proof.get("transitions")
    ):
        return None
    home_screen = proof["home_screen"]
    fresh_listing = proof["listing"]
    queue_state, queue_remaining = _queue1_from_lines(_line_groups(screen.words))
    if (
        home_screen.queue1_state != "idle" or queue_state not in {"unknown", "idle"}
        or fresh_listing.first_recommendation_identity != listing.first_recommendation_identity
        or screen.selected_technology_identity != fresh_listing.first_recommendation_identity
    ):
        return None
    context._recommended_research_center_level = proof["center_level"]
    context._recommended_research_queue1_state = home_screen.queue1_state
    context._recommended_research_queue1_remaining = queue_remaining
    fresh_quote = _source_screen(context, quote_capture, expected_detail_identity=fresh_listing.first_recommendation_identity)
    if fresh_quote != quote_screen:
        return None
    # The consuming frame must itself expose the whole quote. Static top
    # prerequisites may survive the exclusive scroll; affordability may not.
    costs = screen.resource_rows
    detail = _detail_observation(
        screen, fresh_listing, context, costs=costs, scrolled_refs=fresh_quote.evidence_refs, top_screen=top_screen,
    )
    if detail is None or not tech_upgrade_authorizeable(detail, fresh_listing):
        return None
    # A different affordable quote is still a changed authorization, not consent.
    fields = (
        "first_recommendation_identity", "selected_technology_identity",
        "current_level", "target_level", "prerequisites_known", "prerequisites_met",
        "prerequisite_evidence", "queue1_state", "resource_rows", "duration_seconds",
        "target_identity", "target_roi", "panel_bounds",
    )
    if any(getattr(detail, field) != getattr(expected, field) for field in fields):
        return None
    if any(not 0 <= context.monotonic_clock() - source.captured_monotonic <= 10.0 for source in sources):
        return None
    return detail


def _policy_observation(
    captured: Any,
    plan: _ActionPlan,
    *,
    consequence: str,
    cost_type: str,
    cost_amount: int,
    quantity: int,
    evidence_refs: Sequence[str],
    expected_postcondition: str,
) -> Observation:
    frame = captured.frame
    height, width = frame.shape[:2]
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=PROFILE_ID,
        width=int(width),
        height=int(height),
        valid_png=True,
        corrupt=False,
        black=bool(cv2.countNonZero(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)) == 0),
        source_state=plan.source_state,
        overlay_state="none_observed",
        target_identity=plan.target_identity,
        target_roi=plan.target_roi,
        recognized=True,
        clipped=False,
        ambiguous=False,
        control_class=plan.control_class,
        consequence=consequence,
        cost_type=cost_type,
        cost_amount=cost_amount,
        quantity=quantity,
        expected_postcondition=expected_postcondition,
        evidence_refs=tuple(evidence_refs),
        critical_roi_hashes=(),
        ocr_result_frame_sha256=str(captured.sha256),
        ocr_result_capture_completed_monotonic=float(captured.captured_monotonic),
        ocr_reused=False,
        source_family="recommended_research",
        target_isolated=plan.target_isolated,
        forbidden_region_intersects_target=False,
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )


def _action_intent(request: PolicyRequest) -> ActionIntent:
    obs = request.observation
    return ActionIntent(
        action_id=request.action_id,
        action_key=request.action_key,
        task_id=request.task_id,
        semantic_action=request.semantic_action,
        source_state=obs.source_state,
        target_identity=obs.target_identity,
        target_roi=obs.target_roi,
        source_frame_sha256=obs.frame_sha256,
        source_frame_captured_at=obs.capture_completed_monotonic,
        runtime_profile_id=obs.runtime_profile_id,
        game_day_id=request.game_day_id,
        expected_postcondition=obs.expected_postcondition,
        consequence=obs.consequence,
        cost_type=obs.cost_type,
        cost_amount=obs.cost_amount,
        quantity=obs.quantity,
        evidence_refs=obs.evidence_refs,
        consequential=request.action_class is not ActionClass.NAVIGATION_ONLY,
        source_family=obs.source_family,
        target_isolated=obs.target_isolated,
        forbidden_region_intersects_target=obs.forbidden_region_intersects_target,
        action_class=request.action_class,
        action_kind=request.action_kind,
        subject=request.subject,
        resource_or_currency=request.resource_or_currency,
        maximum_cost=request.maximum_cost,
        free_only=request.free_only,
        allowed_confirmation_dialogs=request.allowed_confirmation_dialogs,
        semantic_preconditions=request.semantic_preconditions,
        semantic_postconditions=request.semantic_postconditions,
    )


def _guarded_action(
    context: Any,
    policy: CentralPolicy,
    *,
    captured: Any,
    game_day_id: str,
    occurrence_key: str,
    action_key: str,
    plan_builder: Callable[[Any], _ActionPlan | None],
    recognizes_successor: Callable[[Any], bool],
    semantic_preconditions: tuple[str, ...] | Callable[[Any], tuple[str, ...]] = (),
    action_class: ActionClass = ActionClass.NAVIGATION_ONLY,
    action_kind: str | None = None,
    subject: str | None = None,
    resource_or_currency: str | None = None,
    maximum_cost: int | None = None,
    free_only: bool = False,
    cost_type: str = "none",
    cost_amount: int = 0,
    consequence_class: str = "navigation_only",
    initial_plan: _ActionPlan | None = None,
) -> tuple[Any, Any | None, bool]:
    """Execute one fresh-bound input through CentralPolicy, the canonical store, and the held session."""

    visit = getattr(context, "_recommended_research_visit", None)
    if visit is not None and not _research_visit_valid(context):
        raise RuntimeError("RECOMMENDED_RESEARCH_VISIT_CONTINUITY_LOST")
    # A caller may already have decoded this immutable planning source.
    # Authorization below always rebuilds on the SDK immediate-before capture.
    if initial_plan is None:
        initial_plan = plan_builder(captured)
    if initial_plan is None:
        raise RuntimeError("RECOMMENDED_RESEARCH_TARGET_NOT_FRESHLY_BOUND")
    action_id = f"{action_key}:{uuid4().hex}"
    action_state: dict[str, Any] = {"plan": None, "request": None, "intent": None, "post": None, "post_ok": False}
    store = context.action_store
    consequence = "navigate_zero_cost" if action_class is ActionClass.NAVIGATION_ONLY else "start_ordinary_recommended_research"
    postcondition = initial_plan.expected_postcondition

    def authorize(before: Any) -> None:
        context.checkpoint()
        context.validate_identity()
        if visit is not None and not _research_visit_valid(context):
            raise RuntimeError("RECOMMENDED_RESEARCH_VISIT_CONTINUITY_LOST")
        plan = plan_builder(before)
        if plan is None or plan.target_identity != initial_plan.target_identity or plan.source_state != initial_plan.source_state:
            raise RuntimeError("RECOMMENDED_RESEARCH_PREINPUT_TARGET_CHANGED")
        references = (_capture_ref(context, before),)
        if action_class is ActionClass.SPEND_OR_STRATEGIC and visit is not None:
            references = tuple(dict.fromkeys((
                *references, visit["home_ref"], visit["list_ref"], visit["detail_ref"], visit["quote_ref"],
            )))
        observation = _policy_observation(
            before,
            plan,
            consequence=consequence,
            cost_type=cost_type,
            cost_amount=cost_amount,
            quantity=1,
            evidence_refs=references,
            expected_postcondition=postcondition,
        )
        now = context.utc_clock()
        request = PolicyRequest(
            action_id=action_id,
            action_key=action_key,
            task_id=FLOW_ID,
            task_mode="supervised_validation",
            semantic_action=plan.semantic_action,
            expected_runtime_profile_id=PROFILE_ID,
            observation=observation,
            monotonic_now=context.monotonic_clock(),
            observation_max_age_seconds=10.0,
            dispatch_max_age_seconds=5.0,
            lease_owner=context.owner,
            lease_valid=store.lease_valid_for(context.owner, now),
            unresolved_action=store.has_action_block(),
            duplicate_action_key=store.action_key_exists(action_key),
            game_day_id=game_day_id,
            policy_phase="pre_dispatch",
            action_class=action_class,
            action_kind=action_kind,
            subject=subject,
            resource_or_currency=resource_or_currency,
            maximum_cost=maximum_cost,
            free_only=free_only,
            semantic_preconditions=semantic_preconditions(before) if callable(semantic_preconditions) else semantic_preconditions,
            semantic_postconditions=(postcondition,),
            runtime_session_id=str(context.runtime.session),
        )
        issued = policy.issue_capability(request)
        store.audit(FLOW_ID, "policy_evaluated", now, issued.policy_result, action_id)
        if not issued.authorized or issued.capability is None:
            raise RuntimeError(f"RECOMMENDED_RESEARCH_POLICY_DENIED:{issued.reason_code}")
        intent = _action_intent(request)
        store.prepare_action(intent, issued.policy_result, now)
        consumed = policy.consume_capability(issued.capability, request)
        store.audit(FLOW_ID, "capability_consume", now, consumed.audit, action_id)
        if not consumed.allow_dispatch:
            store.mark_cancelled(action_id, context.utc_clock(), "capability:" + consumed.reason_code)
            raise RuntimeError(f"RECOMMENDED_RESEARCH_CAPABILITY_DENIED:{consumed.reason_code}")
        action_state.update(plan=plan, request=request, intent=intent, before=before)

    def dispatch(before: Any) -> None:
        context.checkpoint()
        plan = action_state.get("plan")
        intent = action_state.get("intent")
        if not isinstance(plan, _ActionPlan) or intent is None:
            raise RuntimeError("RECOMMENDED_RESEARCH_ACTION_NOT_PREPARED")
        runtime = context.runtime
        if plan.gesture == "swipe":
            x0, y0, x1, y1 = plan.target_roi
            center_x = (x0 + x1) // 2
            top = y0 + max(14, (y1 - y0) // 6)
            bottom = y1 - max(14, (y1 - y0) // 6)
            if top >= bottom:
                raise RuntimeError("RECOMMENDED_RESEARCH_SCROLL_REGION_INVALID")
            start_y, end_y = (bottom, top) if plan.scroll_direction == "down" else (top, bottom)
            runtime.swipe(
                before,
                start=(center_x, start_y),
                end=(center_x, end_y),
                target_identity=plan.target_identity,
                action_key=action_key,
                duration_ms=500,
            )
        else:
            runtime.tap(
                before,
                target_identity=plan.target_identity,
                target_roi=plan.target_roi,
                action_key=action_key,
                action_class="research_start" if action_class is ActionClass.SPEND_OR_STRATEGIC else "navigation",
                consequential=action_class is ActionClass.SPEND_OR_STRATEGIC,
            )
        store.mark_input_sent(action_id, context.utc_clock(), TransportResult(True, "DISPATCHED"))

    def recognize(captured_after: Any) -> str:
        context.checkpoint()
        action_state["post"] = captured_after
        verified = bool(recognizes_successor(captured_after))
        action_state["post_ok"] = verified
        return postcondition if verified else "unknown"

    try:
        result = context.session.run_action(
            action_class="research_start" if action_class is ActionClass.SPEND_OR_STRATEGIC else "navigation",
            label=action_key,
            capture=context.runtime.capture,
            dispatch=dispatch,
            recognize=recognize,
            authorize=authorize,
            target_roi=initial_plan.target_roi,
            consequence_class=consequence_class,
            settled_successor=(
                (lambda: time.sleep(context.settle_seconds) or context.session.observe(
                    context.runtime.capture, label=f"{action_key}-settled-successor"
                ))
                if context.settle_seconds > 0 else None
            ),
        )
    except BaseException:
        if visit is not None:
            visit["valid"] = False
        if action_state.get("intent") is not None:
            try:
                row = store.get_action(action_id)
                if row.get("final_status") in {"prepared", "input_sent", "unresolved"}:
                    store.mark_unresolved(action_id, context.utc_clock(), "route_exception_after_preparation")
            except Exception:
                pass
        raise
    intent = action_state.get("intent")
    if intent is not None:
        try:
            if result.status == "completed" and action_state.get("post_ok") is True:
                after = action_state.get("post")
                store.mark_confirmed(
                    action_id,
                    context.utc_clock(),
                    {"confirmed": True, "state": result.state, "frame_sha256": getattr(after, "sha256", "")},
                )
            else:
                row = store.get_action(action_id)
                if row.get("final_status") in {"prepared", "input_sent", "unresolved"}:
                    store.mark_unresolved(action_id, context.utc_clock(), "route_successor_not_proven")
        except Exception as exc:
            raise RuntimeError("RECOMMENDED_RESEARCH_CANONICAL_RECONCILIATION_FAILED") from exc
    if visit is not None and action_class is ActionClass.NAVIGATION_ONLY:
        keys = tuple(context.runtime.action_keys)
        verified_chain = (
            result.status == "completed" and action_state.get("post_ok") is True
            and context.runtime.input_count == visit["input_count"] + 1
            and keys == visit["action_keys"] + (action_key,)
            and visit["identity"] == _research_visit_identity(context)
        )
        visit["valid"] = verified_chain
        if verified_chain:
            before, after = action_state["before"], action_state["post"]
            visit["transitions"].append({
                "action_key": action_key, "postcondition": postcondition,
                "source_sha256": before.sha256, "source_captured_at": before.captured_monotonic,
                "successor_sha256": after.sha256, "successor_captured_at": after.captured_monotonic,
            })
            visit.update(action_keys=keys, input_count=context.runtime.input_count)
    return result, action_state.get("post"), bool(action_state.get("post_ok"))


def _research_selection_facts(detail: TechUpgradeObservation) -> dict[str, object]:
    return {
        "first_recommendation_identity": detail.first_recommendation_identity,
        "recommendation_position": detail.recommendation_position,
        "target_identity": detail.target_identity,
        "queue1_state": detail.queue1_state,
        "queue1_remaining_seconds": detail.queue1_remaining_seconds,
        "queue2_activate_tapped": detail.queue2_activate_tapped,
        "prerequisites_known": detail.prerequisites_known,
        "prerequisites_met": detail.prerequisites_met,
        "prerequisite_evidence": list(detail.prerequisite_evidence),
        "requirements_scrolled": detail.requirements_scrolled,
        "research_start_visible": detail.research_start_visible,
        "control_class": detail.control_class,
        "research_now_target_identity": detail.research_now_target_identity,
        "research_now_tapped": detail.research_now_tapped,
        "overlay_state": detail.overlay_state,
        "research_duration_seconds": detail.duration_seconds,
        "current_level": detail.current_level,
        "target_level": detail.target_level,
    }


def _research_start_preconditions(
    detail: TechUpgradeObservation,
    game_day_id: str,
) -> tuple[str, ...]:
    if not re.fullmatch(r"game-day-[0-9]{4}-[0-9]{2}-[0-9]{2}", game_day_id, flags=re.ASCII):
        raise ValueError("scheduler game-day reset identity is unavailable")
    slug = detail.first_recommendation_identity
    prerequisite = "_".join(detail.prerequisite_evidence)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", prerequisite, flags=re.ASCII):
        raise ValueError("exact prerequisite evidence is unavailable")
    rows = {row.resource: row for row in detail.resource_rows}
    if set(rows) != set(RESEARCH_RESOURCES):
        raise ValueError("all four ordinary research resource rows are required")
    return (
        f"product_id={PRODUCT_ID}",
        f"product_revision={PRODUCT_REVISION}",
        f"recommended_research_reset={game_day_id}",
        "recommended_research_start_ordinal=1",
        "recommended_research_start_count_before=0",
        f"first_displayed_recommendation_identity={slug}",
        "recommendation_position=1",
        "queue1_state=idle",
        "queue2_activate_tapped=false",
        "prerequisites_known=true",
        "prerequisites_met=true",
        f"prerequisite_evidence={prerequisite}",
        *(token for resource in RESEARCH_RESOURCES for token in (
            f"{resource}_cost={rows[resource].cost}",
            f"{resource}_balance={rows[resource].balance}",
        )),
        "cost_source=detail_panel_scrolled_complete",
        "affordable=true",
        "premium_cost_excluded=true",
        "research_now_diamonds_excluded=true",
    )


def _page_plan(screen: ResearchScreenObservation, *, state: str, target: str, control: str, postcondition: str, semantic_action: str) -> _ActionPlan | None:
    if screen.screen_state != state or screen.panel_bounds is None:
        return None
    roi = screen.list_research_target_roi if target.endswith(":list-research-button") else screen.detail_research_target_roi
    if roi is None or not _inside(screen.panel_bounds, roi):
        return None
    return _ActionPlan(target, roi, state, control, postcondition, semantic_action)


# The Back arrow walks detail -> tree -> Research Center -> Home. Each hop must
# land on a recognized page strictly nearer Home, or on verified clean Home.
_RETURN_PARENT_STATES: dict[str, frozenset[str]] = {
    DETAIL_SCREEN: frozenset({TREE_SCREEN, LIST_SCREEN}),
    TREE_SCREEN: frozenset({LIST_SCREEN}),
    LIST_SCREEN: frozenset(),
    ACTIVE_SCREEN: frozenset({TREE_SCREEN, LIST_SCREEN}),
}
_RETURN_HOME_MAX_BACKS = 3


def _return_plan(frame: Any, screen: ResearchScreenObservation) -> _ActionPlan | None:
    if screen.screen_state not in _RETURN_PARENT_STATES:
        return None
    from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual

    target = _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)
    if target is None:
        return None
    roi = (int(target[0]), int(target[1]), int(target[2]), int(target[3]))
    if _RETURN_PARENT_STATES[screen.screen_state]:
        return _ActionPlan(
            "recommended-research:back-parent",
            roi,
            screen.screen_state,
            "CLOSE",
            "RECOMMENDED_RESEARCH_PARENT_OR_HOME",
            "RECOMMENDED_RESEARCH_RETURN_HOME",
        )
    return _ActionPlan(
        "recommended-research:back-home",
        roi,
        screen.screen_state,
        "CLOSE",
        "HOME_BASE",
        "RECOMMENDED_RESEARCH_RETURN_HOME",
    )


def _reference(context: Any, captured: Any) -> str:
    value = _capture_ref(context, captured)
    if not value:
        raise RuntimeError("RECOMMENDED_RESEARCH_CAPTURE_REFERENCE_INVALID")
    return value


def _build_active_observation(screen: ResearchScreenObservation) -> ResearchActiveObservation | None:
    if (
        screen.screen_state != ACTIVE_SCREEN
        or screen.active_title is None
        or screen.active_identity is None
        or type(screen.active_remaining_seconds) is not int
        or screen.active_remaining_seconds <= 0
        or not _DIGEST_RE.fullmatch(screen.frame_sha256 or "")
    ):
        return None
    return ResearchActiveObservation(
        screen_state=ACTIVE_SCREEN,
        active_technology_title=screen.active_title,
        active_technology_identity=screen.active_identity,
        queue1_state="active",
        remaining_seconds=screen.active_remaining_seconds,
        resource_rows=screen.active_resource_rows,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=screen.frame_sha256,
        evidence_refs=screen.evidence_refs,
        overlay_state=screen.overlay_state,
        runtime_profile_id=PROFILE_ID,
        recognized=True,
    )


def _normal_result(
    context: Any,
    *,
    status: str,
    reason: str,
    start_calls: int = 0,
    committed_action_count: int = 0,
    terminal_home_verified: bool = False,
    accounting: Any = _ACCOUNTING_UNSET,
    **facts: object,
) -> dict[str, Any]:
    if accounting is _ACCOUNTING_UNSET:
        accounting = context.accounting()
    terminal_home_frame = None
    if terminal_home_verified:
        try:
            captured_home = context.session.observe(
                context.runtime.capture,
                label="recommended-research-terminal-home",
            )
            if context.is_clean_home(captured_home.frame):
                reference = _capture_ref(context, captured_home)
                if reference:
                    _, frame_path, frame_sha256 = reference.split(":", 2)
                    terminal_home_frame = {
                        "frame_path": frame_path,
                        "frame_sha256": frame_sha256,
                    }
                else:
                    terminal_home_verified = False
            else:
                terminal_home_verified = False
        except Exception:
            terminal_home_verified = False
    completed_at = context.utc_clock()
    next_due = None
    if status == "completed" and type(facts.get("remaining_seconds")) is int:
        next_due = completed_at + facts["remaining_seconds"]
    elif status == "deferred":
        if facts.get("queue1_state") == "busy" and type(facts.get("queue1_remaining_seconds")) is int:
            next_due = completed_at + facts["queue1_remaining_seconds"]
        elif facts.get("observation_interval_seconds") == OBSERVATION_INTERVAL_SECONDS:
            next_due = completed_at + OBSERVATION_INTERVAL_SECONDS
    input_count = accounting.input_count if accounting is not None else None
    session_input_count = accounting.session_input_count if accounting is not None else None
    runtime_input_count = accounting.runtime_input_count if accounting is not None else None
    accounting_verified = bool(accounting is not None and accounting.verified)
    return {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "status": status,
        "reason": reason,
        "terminal_home_verified": terminal_home_verified,
        "terminal_home_frame": terminal_home_frame,
        "terminal_home_frame_sha256": terminal_home_frame["frame_sha256"] if terminal_home_frame else None,
        "research_transport_calls": start_calls,
        "committed_action_count": committed_action_count,
        "total_action_count": start_calls,
        "total_input_count": input_count,
        "input_count": input_count,
        "session_input_count": session_input_count,
        "runtime_input_count": runtime_input_count,
        "accounting_verified": accounting_verified,
        "effect_reconciliation_required": status == "unresolved",
        "identical_retry_denied": bool(start_calls or status in {"unresolved", "already_complete"}),
        "time_basis": "utc",
        "completed_at_utc": completed_at,
        "next_due_utc": next_due,
        "session_directory": str(context.runtime.session),
        "start_semantically_verified": facts.get("start_semantically_verified") is True,
        **facts,
    }


def _game_day_id(identity: Any) -> str:
    value = getattr(identity, "reset_id", None)
    if not isinstance(value, str) or re.fullmatch(r"game-day-[0-9]{4}-[0-9]{2}-[0-9]{2}", value, flags=re.ASCII) is None:
        raise ValueError("scheduler identity must carry its exact game-day reset id")
    return value


def _action_key(identity: Any, game_day_id: str) -> str:
    account = getattr(identity, "account_id", None)
    server = getattr(identity, "server_id", None)
    if not all(type(value) is str and re.fullmatch(r"[A-Za-z0-9:._-]+", value, flags=re.ASCII) for value in (account, server)):
        raise ValueError("account and server identities must be canonical tokens")
    scope = json.dumps((account, server, game_day_id), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return f"recommended-research:v1:{hashlib.sha256(scope).hexdigest()}"


def _navigation_key(context: Any, occurrence_key: str, name: str) -> str:
    """Non-consuming navigation identity: unique per native invocation, never per retry.

    The durable reset-scoped start key stays ``_action_key``; navigation from a
    later invocation's fresh source must not collide with retained earlier rows.
    """

    invocation = getattr(context, "invocation_id", None)
    if not isinstance(invocation, str) or not invocation.strip():
        raise RuntimeError("RECOMMENDED_RESEARCH_INVOCATION_ID_REQUIRED")
    return f"{occurrence_key}:{invocation}:recommended-research:{name}"



def _home_from_current(
    context: Any,
    policy: CentralPolicy,
    *,
    current: Any,
    game_day_id: str,
    occurrence_key: str,
    step: int,
    key_name: str | None = None,
) -> tuple[Any, bool, int]:
    """Bounded guarded Back chain; every hop needs a recognized nearer successor."""
    # Home return ends the exclusive forward proof chain; it can never be
    # resumed as retained entry/selection authority afterwards.
    context._recommended_research_visit = None
    if context.action_store.has_action_block():
        return current, False, step

    def return_screen(captured: Any) -> ResearchScreenObservation:
        screen = _source_screen(context, captured)
        active_identity = getattr(context, "_recommended_research_active_identity", None)
        if not screen.recognized and active_identity is not None:
            return _source_screen(context, captured, expected_detail_identity=active_identity)
        return screen

    for hop in range(_RETURN_HOME_MAX_BACKS):
        if context.is_clean_home(current.frame):
            return current, True, step
        screen = return_screen(current)
        plan = _return_plan(current.frame, screen)
        if plan is None:
            return current, False, step
        parents = _RETURN_PARENT_STATES[plan.source_state]

        def nearer_home(captured: Any, parents: frozenset[str] = parents) -> bool:
            if context.is_clean_home(captured.frame):
                return True
            if not parents:
                return False
            successor = _source_screen(context, captured)
            return bool(
                successor.recognized
                and successor.screen_state in parents
                and _return_plan(captured.frame, successor) is not None
            )

        name = f"{key_name}:{hop}" if key_name else f"return-home:{step}"
        result, after, verified = _guarded_action(
            context,
            policy,
            captured=current,
            game_day_id=game_day_id,
            occurrence_key=occurrence_key,
            action_key=_navigation_key(context, occurrence_key, name),
            plan_builder=lambda fresh_capture: _return_plan(fresh_capture.frame, return_screen(fresh_capture)),
            recognizes_successor=nearer_home,
        )
        del result
        step += 1
        if not verified or after is None:
            return current, False, step
        current = after
    return current, context.is_clean_home(current.frame), step




def _startup(context: Any, policy: CentralPolicy, game_day_id: str, occurrence_key: str) -> Any:
    initial = context.initial_frame
    if context.is_clean_home(initial.frame):
        if context.session.initial_observation is None:
            context.bind_initial_observation(initial, extra={"route_source": "recommended-research-clean-home"})
        return initial
    screen = _source_screen(context, initial)
    if screen.recognized and _return_plan(initial.frame, screen) is not None:
        # A positively identified Research page (e.g. left open by an earlier
        # unverified successor): bind that exact source, then the bounded
        # guarded Back chain (detail -> tree -> list -> Home) to verified Home.
        if context.session.initial_observation is None:
            context.bind_initial_observation(initial, extra={
                "route_source": "recommended-research-existing-page",
                "research_page_state": screen.screen_state,
            })
        home, home_verified, _step = _home_from_current(
            context, policy, current=initial, game_day_id=game_day_id,
            occurrence_key=occurrence_key, step=0, key_name="startup-return-home",
        )
        if not home_verified:
            raise RuntimeError("RECOMMENDED_RESEARCH_STARTUP_HOME_NOT_PROVEN")
        return home
    recovery = context.prepare_startup(
        source_context="recommended_research_clean_home",
        recognize_successor=lambda captured: context.is_clean_home(captured.frame),
        action_key=f"recommended-research-startup:{game_day_id}:{occurrence_key}",
        settle_seconds=context.settle_seconds,
    )
    if not recovery.resume_ready or recovery.settled_frame is None or not context.is_clean_home(recovery.settled_frame.frame):
        raise RuntimeError("RECOMMENDED_RESEARCH_STARTUP_HOME_NOT_PROVEN")
    return recovery.settled_frame


def run_native_route(context: Any, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    """Use fresh Atlas/UI evidence and one durable reset-scoped Research start at most."""

    if (context.flow_id, context.product_id, context.product_revision, context.runtime_profile_id) != (
        FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID,
    ):
        raise RuntimeError("RECOMMENDED_RESEARCH_NATIVE_BINDING_IDENTITY_MISMATCH")
    context.checkpoint()
    context.validate_identity()
    game_day_id = _game_day_id(context.identity)
    occurrence_key = context.occurrence_key
    if not isinstance(occurrence_key, str) or not occurrence_key.strip():
        raise RuntimeError("RECOMMENDED_RESEARCH_OCCURRENCE_KEY_REQUIRED")
    start_action_key = _action_key(context.identity, game_day_id)
    policy = CentralPolicy(supervised_tasks=frozenset({FLOW_ID}))
    prior = context.action_store.get_action_by_key(start_action_key)
    if prior is not None:
        status = prior.get("final_status")
        if status == "confirmed":
            _startup(context, policy, game_day_id, occurrence_key)
            home = context.session.observe(
                context.runtime.capture,
                label="recommended-research-reset-action-home",
            )
            return _normal_result(
                context,
                status="already_complete",
                reason="reset_scoped_research_start_already_confirmed",
                already_confirmed=True,
                game_day_id=game_day_id,
                terminal_home_verified=context.is_clean_home(home.frame),
            )
        pending = status in {"prepared", "input_sent", "unresolved"}
        raise RecommendedResearchRouteFailure(
            "RECOMMENDED_RESEARCH_RESET_ACTION_ALREADY_EXISTS_REQUIRES_INSPECTION",
            partial_result={
                "status": "unresolved" if pending else "blocked",
                "reason": "reset_scoped_research_action_not_confirmed",
                "game_day_id": game_day_id,
                "research_transport_calls": 0,
                "committed_action_count": 0,
                "total_action_count": 0,
                "effect_reconciliation_required": pending,
                "identical_retry_denied": pending,
            },
        )
    semantic_progress: dict[str, Any] = {}
    context._recommended_research_screen_cache = {}
    context._recommended_research_visit = None
    context._recommended_research_active_identity = None
    try:
        initial = _startup(context, policy, game_day_id, occurrence_key)
        home = context.session.observe(context.runtime.capture, label="recommended-research-home-source")
        if not context.is_clean_home(home.frame):
            return _normal_result(context, status="blocked", reason="fresh_clean_home_not_proven", game_day_id=game_day_id)
        home_screen = _source_screen(context, home)
        queue_state = home_screen.queue1_state
        queue_remaining = home_screen.queue1_remaining_seconds
        if queue_state == "busy":
            return _normal_result(
                context,
                status="deferred",
                reason="research_queue1_busy",
                game_day_id=game_day_id,
                queue1_state="busy",
                queue1_remaining_seconds=queue_remaining,
                observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
                terminal_home_verified=True,
            )
        if queue_state != "idle":
            return _normal_result(
                context, status="blocked", reason="research_queue1_state_unknown_or_timer_unproven",
                game_day_id=game_day_id, queue1_state=queue_state,
                queue1_remaining_seconds=queue_remaining, terminal_home_verified=True,
            )
        atlas: HomeAtlas = load_home_atlas(ATLAS_PATH)
        localizer = BlueStacksHomeLocalizer(atlas, ATLAS_PATH)
        building = atlas.lookup_building(RESEARCH_CENTER_ID)
        entry_home, binding, binding_error = bind_or_pan_mapped_home_building(
            context, current=home, atlas=atlas, localizer=localizer,
            building_id=RESEARCH_CENTER_ID, product_id=PRODUCT_ID,
            binding_for_frame=lambda frame: _binding_for_home(context, frame, localizer, building),
        )
        if entry_home is None or binding is None:
            return _normal_result(
                context, status="blocked",
                reason=binding_error or "fresh_research_center_binding_unavailable",
                game_day_id=game_day_id,
            )
        if entry_home is not home:
            home_screen = _source_screen(context, entry_home)
            queue_state = home_screen.queue1_state
            queue_remaining = home_screen.queue1_remaining_seconds
            if queue_state == "busy":
                return _normal_result(
                    context, status="deferred", reason="research_queue1_busy",
                    game_day_id=game_day_id, queue1_state="busy",
                    queue1_remaining_seconds=queue_remaining, terminal_home_verified=True,
                    observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
                )
            if queue_state != "idle":
                return _normal_result(
                    context, status="blocked", reason="research_queue1_state_unknown_or_timer_unproven",
                    game_day_id=game_day_id, queue1_state=queue_state,
                    queue1_remaining_seconds=queue_remaining,
                    terminal_home_verified=home_screen.screen_state == "HOME_BASE" and home_screen.recognized,
                )
        home = entry_home
        visit = {
            "identity": _research_visit_identity(context), "valid": True,
            "action_keys": tuple(context.runtime.action_keys),
            "input_count": context.runtime.input_count, "transitions": [],
        }
        context._recommended_research_visit = visit
        owner_binding: dict[str, BuildingBinding | None] = {"value": binding}
        occurrence = occurrence_key
        step = 0

        def building_plan(captured: Any) -> _ActionPlan | None:
            nonlocal home, binding, home_screen
            current_binding = _binding_for_home(context, captured.frame, localizer, building)
            if current_binding is None:
                return None
            # This fresh binding already proved clean Home on these exact
            # pixels. Do not run the same Home classifier again during the
            # dispatch-age window; the canonical reader still guards frame
            # shape/digest and reads the actual current queue.
            current_home = recognize_research_screen(
                captured.frame, source_frame_sha256=str(captured.sha256),
                evidence_refs=(_capture_ref(context, captured),),
                home_recognized=True,
            )
            home_screen = current_home
            pixels = hashlib.sha256(captured.frame.tobytes()).hexdigest()
            current_level = _research_center_level(captured.frame, current_binding)
            used_at = context.monotonic_clock()
            if (
                not 0 <= used_at - captured.captured_monotonic <= 10.0
                or current_home.queue1_state != "idle"
                or not _research_visit_valid(context)
            ):
                return None
            home, binding = captured, current_binding
            context._recommended_research_center_level = current_level
            context._recommended_research_queue1_state = current_home.queue1_state
            context._recommended_research_queue1_remaining = current_home.queue1_remaining_seconds
            visit.update(
                home_source=(captured.sha256, captured.captured_monotonic),
                home_used_at=used_at, home_screen=current_home, center_level=current_level,
                home_ref=_capture_ref(context, captured),
                home_pixels=pixels,
                home_binding=current_binding,
            )
            owner_binding["value"] = current_binding
            return _ActionPlan(
                RESEARCH_CENTER_ID,
                tuple(current_binding.target_roi),
                "HOME_BASE",
                "GO",
                "RESEARCH_RADIAL",
                "RECOMMENDED_RESEARCH_OPEN_CENTER",
            )

        def entry_dispatch_plan(captured: Any) -> _ActionPlan | None:
            # SDK immediate-before revalidation on its own actual capture:
            # clean Home plus the Atlas-bound Research Center target, nothing
            # cached. The queue/level phase proof stays bound to the entry-phase
            # capture with its original timestamps and is not re-dated onto
            # this frame. Re-running that OCR here measured 5.8 s offline on
            # the retained 221908 frames, past the 5 s dispatch age (STALE_FRAME).
            proof = getattr(context, "_recommended_research_visit", None)
            if proof is not visit or visit.get("home_source") != (home.sha256, home.captured_monotonic):
                return None
            current_binding = _binding_for_home(context, captured.frame, localizer, building)
            used_at = context.monotonic_clock()
            if (
                current_binding is None
                or current_binding.building_id != RESEARCH_CENTER_ID
                or not 0 <= used_at - captured.captured_monotonic <= 10.0
                or not _research_visit_valid(context)
            ):
                return None
            owner_binding["value"] = current_binding
            x0, y0, x1, y1 = current_binding.target_roi
            return _ActionPlan(
                RESEARCH_CENTER_ID,
                (x0, y0, x1, y1),
                "HOME_BASE",
                "GO",
                "RESEARCH_RADIAL",
                "RECOMMENDED_RESEARCH_OPEN_CENTER",
            )

        # A real new capture after Atlas planning, not a re-dated source. The
        # full phase proof (binding, queue idle, center level) is decoded once
        # here; the SDK immediate-before capture then rebinds only the target.
        home = context.session.observe(context.runtime.capture, label="recommended-research-entry-phase-source")
        entry_plan = building_plan(home)
        if entry_plan is None:
            context._recommended_research_visit = None
            if home_screen.queue1_state == "busy":
                return _normal_result(
                    context, status="deferred", reason="research_queue1_busy",
                    game_day_id=game_day_id, queue1_state="busy",
                    queue1_remaining_seconds=home_screen.queue1_remaining_seconds,
                    observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
                    terminal_home_verified=context.is_clean_home(home.frame),
                )
            return _normal_result(
                context, status="blocked", reason="research_entry_phase_proof_unknown_or_expired",
                game_day_id=game_day_id, terminal_home_verified=context.is_clean_home(home.frame),
            )
        radial_state: dict[str, ResearchScreenObservation | None] = {"value": None}

        def radial_successor(captured: Any) -> bool:
            current_binding = owner_binding["value"]
            if current_binding is None:
                return False
            screen = recognize_research_radial(
                captured.frame,
                source_frame_sha256=captured.sha256,
                evidence_refs=(_reference(context, captured),),
                building_binding=current_binding,
                home_recognized=context.is_clean_home(captured.frame),
            )
            radial_state["value"] = screen
            return screen is not None

        if radial_successor(home):
            # Restart on this owner's already-open radial: resume from the same
            # fresh capture that bound the Atlas owner instead of re-tapping it.
            after = home
        else:
            result, after, verified = _guarded_action(
                context,
                policy,
                captured=home,
                game_day_id=game_day_id,
                occurrence_key=occurrence,
                action_key=_navigation_key(context, occurrence, "open-center"),
                plan_builder=entry_dispatch_plan,
                recognizes_successor=radial_successor,
                initial_plan=entry_plan,
            )
            step += 1
            if not verified or after is None or radial_state["value"] is None:
                return _normal_result(context, status="blocked", reason="research_center_radial_successor_unverified", game_day_id=game_day_id, route_steps=step)
        radial = radial_state["value"]
        if radial is None:
            return _normal_result(context, status="blocked", reason="research_center_radial_successor_unverified", game_day_id=game_day_id, route_steps=step)
        radial_target = radial.list_research_target_roi
        if radial_target is None:
            return _normal_result(context, status="blocked", reason="radial_research_control_unavailable", game_day_id=game_day_id, route_steps=step)

        def radial_plan(captured: Any) -> _ActionPlan | None:
            frame = captured.frame
            current_binding = owner_binding["value"]
            if current_binding is None or not context.is_clean_home(frame):
                return None
            fresh = recognize_research_radial(
                frame,
                source_frame_sha256=captured.sha256,
                evidence_refs=(_reference(context, captured),),
                building_binding=current_binding,
                home_recognized=True,
            )
            if fresh is None or fresh.list_research_target_roi is None:
                return None
            return _ActionPlan(
                "recommended-research:radial-research",
                fresh.list_research_target_roi,
                "RESEARCH_RADIAL",
                "GO",
                "RECOMMENDED_LIST",
                "RECOMMENDED_RESEARCH_RADIAL_NAVIGATE",
            )

        list_state: dict[str, ResearchScreenObservation | None] = {"value": None}

        def list_successor(captured: Any) -> bool:
            screen = _source_screen(context, captured)
            list_state["value"] = screen
            return research_center_successor_verified(radial, screen)

        result, after, verified = _guarded_action(
            context,
            policy,
            captured=after,
            game_day_id=game_day_id,
            occurrence_key=occurrence,
            action_key=_navigation_key(context, occurrence, "radial-research"),
            plan_builder=radial_plan,
            recognizes_successor=list_successor,
        )
        step += 1
        if not verified or after is None or list_state["value"] is None:
            current = after if after is not None else home
            current, home_verified, step = _home_from_current(context, policy, current=current, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="research_center_page_successor_unverified", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
        list_screen = list_state["value"]
        listing_capture = after
        listing = _list_observation(list_screen, context)
        if listing is None or not research_list_navigation_authorizeable(listing):
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="first_recommendation_list_control_unavailable", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)

        def list_button_plan(captured: Any) -> _ActionPlan | None:
            nonlocal listing_capture, listing
            fresh_screen = _source_screen(context, captured)
            fresh_listing = _list_observation(fresh_screen, context)
            if fresh_listing is None or fresh_listing.first_recommendation_identity != listing.first_recommendation_identity:
                return None
            if not research_list_navigation_authorizeable(fresh_listing):
                return None
            used_at = context.monotonic_clock()
            if not 0 <= used_at - captured.captured_monotonic <= 10.0 or not _research_visit_valid(context):
                return None
            listing_capture, listing = captured, fresh_listing
            visit.update(
                list_source=(captured.sha256, captured.captured_monotonic),
                list_used_at=used_at, listing=fresh_listing,
                list_ref=_capture_ref(context, captured),
                list_pixels=hashlib.sha256(captured.frame.tobytes()).hexdigest(),
            )
            return _ActionPlan(
                fresh_listing.target_identity,
                tuple(fresh_listing.target_roi),
                LIST_SCREEN,
                "GO",
                DETAIL_SCREEN,
                "RECOMMENDED_RESEARCH_LIST_NAVIGATE",
            )

        detail_screen_state: dict[str, ResearchScreenObservation | None] = {"value": None}

        def detail_successor(captured: Any) -> bool:
            screen = _source_screen(
                context,
                captured,
                expected_detail_identity=listing.first_recommendation_identity,
            )
            detail_screen_state["value"] = screen
            if (
                screen.screen_state != DETAIL_SCREEN
                or screen.selected_technology_identity != listing.first_recommendation_identity
                or screen.detail_research_target_roi is None
                or screen.panel_bounds is None
            ):
                return False
            provisional = _detail_observation(
                screen,
                listing,
                context,
                costs=screen.resource_rows,
                scrolled_refs=(),
            ) if len(screen.resource_rows) == len(RESEARCH_RESOURCES) else None
            if provisional is None:
                provisional = TechUpgradeObservation(
                    screen_state=DETAIL_SCREEN,
                    recommendation_frame_sha256=listing.source_frame_sha256,
                    first_recommendation_title=listing.first_recommendation_title,
                    first_recommendation_identity=listing.first_recommendation_identity,
                    recommendation_position=1,
                    selected_technology_title=screen.selected_technology_title,
                    selected_technology_identity=screen.selected_technology_identity,
                    current_level=screen.current_level,
                    target_level=screen.target_level,
                    # Navigation proof only: row text is not prerequisite proof.
                    prerequisites_known=False,
                    prerequisites_met=False,
                    prerequisite_evidence=screen.prerequisite_evidence,
                    queue1_state=getattr(context, "_recommended_research_queue1_state", "unknown"),
                    queue1_remaining_seconds=getattr(context, "_recommended_research_queue1_remaining", None),
                    queue2_activate_tapped=False,
                    requirements_scrolled=False,
                    resource_rows=(),
                    duration_seconds=screen.duration_seconds,
                    target_identity=f"recommended-research:{listing.first_recommendation_identity}:detail-research-button",
                    target_roi=screen.detail_research_target_roi,
                    panel_bounds=screen.panel_bounds,
                    control_class="RESEARCH_START",
                    research_start_visible=True,
                    research_now_target_identity="research-now-diamonds",
                    research_now_tapped=False,
                    target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
                    source_frame_sha256=screen.frame_sha256,
                    evidence_refs=screen.evidence_refs,
                )
            return research_list_navigation_verified(listing, provisional)

        result, after, verified = _guarded_action(
            context,
            policy,
            captured=after,
            game_day_id=game_day_id,
            occurrence_key=occurrence,
            action_key=_navigation_key(context, occurrence, "list-research"),
            plan_builder=list_button_plan,
            recognizes_successor=detail_successor,
        )
        step += 1
        if not verified or after is None or detail_screen_state["value"] is None:
            current = after if after is not None else home
            current, home_verified, step = _home_from_current(context, policy, current=current, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="first_recommendation_detail_successor_unverified", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)

        detail_screen = detail_screen_state["value"]
        visit.update(
            detail_capture=after, detail_screen=detail_screen,
            detail_pixels=hashlib.sha256(after.frame.tobytes()).hexdigest(),
            detail_used_at=context.monotonic_clock(), detail_ref=_capture_ref(context, after),
        )
        scrolled_refs: list[str] = []
        quote_capture = after
        quote_screen = detail_screen
        if len(detail_screen.resource_rows) != len(RESEARCH_RESOURCES):
            if detail_screen.scroll_roi is None:
                current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
                return _normal_result(context, status="blocked", reason="detail_resource_scroll_region_unknown", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)

            def scroll_down_plan(captured: Any) -> _ActionPlan | None:
                screen = _source_screen(
                    context,
                    captured,
                    expected_detail_identity=listing.first_recommendation_identity,
                )
                if screen.screen_state != DETAIL_SCREEN or screen.scroll_roi is None:
                    return None
                return _ActionPlan(
                    f"recommended-research:{listing.first_recommendation_identity}:requirements-scroll",
                    screen.scroll_roi,
                    DETAIL_SCREEN,
                    "GO",
                    "RESEARCH_DETAIL_REQUIREMENTS_SCROLLED",
                    "RECOMMENDED_RESEARCH_SCROLL_REQUIREMENTS",
                    gesture="swipe",
                    scroll_direction="down",
                )

            scrolled_screen_state: dict[str, ResearchScreenObservation | None] = {"value": None}
            scrolled_costs: dict[str, tuple[ResearchResourceRow, ...]] = {"value": ()}

            def scrolled_successor(captured: Any) -> bool:
                screen = _source_screen(
                    context,
                    captured,
                    expected_detail_identity=listing.first_recommendation_identity,
                )
                costs_from_both_views = _merge_top_and_scrolled_resource_rows(
                    detail_screen.resource_pairs,
                    screen.resource_pairs,
                )
                scrolled_screen_state["value"] = screen
                scrolled_costs["value"] = costs_from_both_views
                return (
                    screen.screen_state == DETAIL_SCREEN
                    and screen.recognized
                    and screen.requirements_scrolled
                    and len(costs_from_both_views) == len(RESEARCH_RESOURCES)
                )

            result, after_scroll, verified = _guarded_action(
                context,
                policy,
                captured=after,
                game_day_id=game_day_id,
                occurrence_key=occurrence,
                action_key=_navigation_key(context, occurrence, "requirements-scroll-down"),
                plan_builder=scroll_down_plan,
                recognizes_successor=scrolled_successor,
            )
            step += 1
            if not verified or after_scroll is None or scrolled_screen_state["value"] is None:
                current = after_scroll if after_scroll is not None else after
                current, home_verified, step = _home_from_current(context, policy, current=current, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
                return _normal_result(context, status="blocked", reason="all_four_scrolled_resource_rows_unverified", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
            scrolled_screen = scrolled_screen_state["value"]
            quote_capture = after_scroll
            quote_screen = scrolled_screen
            costs = scrolled_costs["value"]
            scrolled_refs.append(_reference(context, after_scroll))

            # Research remains fixed beside Research Now in both retained
            # views. Avoid hiding/expiring the quote with an unnecessary return.
            after = after_scroll
        else:
            costs = detail_screen.resource_rows
            scrolled_refs.append(_reference(context, after))

        detail = _detail_observation(quote_screen, listing, context, costs=costs, scrolled_refs=scrolled_refs, top_screen=detail_screen)
        if detail is None:
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="detail_prerequisites_duration_or_target_unknown", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
        selection_facts = _research_selection_facts(detail)
        semantic_progress.update(selection_facts)
        if not detail.prerequisites_known:
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="research_prerequisite_unknown", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
        if not detail.prerequisites_met:
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(
                context, status="deferred" if home_verified else "blocked",
                reason="research_prerequisite_unmet", game_day_id=game_day_id,
                terminal_home_verified=home_verified, route_steps=step,
                observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
                unmet_prerequisites=list(detail.prerequisite_evidence), **selection_facts,
            )
        shortages = tech_upgrade_shortages(detail, listing)
        if shortages is None:
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="research_cost_or_balance_unknown", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
        if shortages:
            shortage_rows = [{"resource": resource, "shortage": amount} for resource, amount in shortages]
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            if not home_verified:
                return _normal_result(
                    context,
                    status="blocked",
                    reason="research_shortage_observed_but_home_unverified",
                    game_day_id=game_day_id,
                    shortages=shortage_rows,
                    terminal_home_verified=False,
                    route_steps=step,
                )
            return _normal_result(
                context,
                status="deferred",
                reason="research_ordinary_resource_shortage",
                game_day_id=game_day_id,
                shortages=shortage_rows,
                exact_resource_costs={row.resource: row.cost for row in detail.resource_rows},
                exact_resource_balances={row.resource: row.balance for row in detail.resource_rows},
                terminal_home_verified=True,
                observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
                normal_defer=True,
                route_steps=step,
                **selection_facts,
            )
        if not tech_upgrade_authorizeable(detail, listing):
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="recommended_research_exact_start_guard_failed", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)
        start_plan = _page_plan(
            quote_screen,
            state=DETAIL_SCREEN,
            target=detail.target_identity,
            control="RESEARCH_START",
            postcondition="RESEARCH_ACTIVE_WITH_TIMER",
            semantic_action="START_RECOMMENDED_RESEARCH",
        )
        if start_plan is None or detail.research_now_tapped or detail.research_now_target_identity == detail.target_identity:
            current, home_verified, step = _home_from_current(context, policy, current=after, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
            return _normal_result(context, status="blocked", reason="research_start_or_premium_target_not_isolated", game_day_id=game_day_id, terminal_home_verified=home_verified, route_steps=step)

        # Entry/selection retain their phase-use provenance only through this
        # verified exclusive navigation chain. Affordability/detail do not:
        # both still have to be fresh at the consuming fence.
        start_source_ages = {
            name: context.monotonic_clock() - source.captured_monotonic
            for name, source in (
                ("resource_quote", quote_capture), ("detail", after),
            )
        }
        if not _research_visit_valid(context) or any(not 0 <= age <= 10.0 for age in start_source_ages.values()):
            current, home_verified, step = _home_from_current(
                context, policy, current=after, game_day_id=game_day_id,
                occurrence_key=occurrence, step=step,
            )
            return _normal_result(
                context, status="blocked", reason="research_cross_page_source_expired",
                game_day_id=game_day_id, terminal_home_verified=home_verified,
                route_steps=step, source_ages_seconds=start_source_ages,
                **selection_facts,
            )
        visit["quote_ref"] = _capture_ref(context, quote_capture)
        semantic_progress["phase_proof"] = {
            "invocation_id": context.invocation_id,
            "home": {"frame_sha256": home.sha256, "captured_at": home.captured_monotonic, "used_at": visit["home_used_at"]},
            "recommendation": {"frame_sha256": listing_capture.sha256, "captured_at": listing_capture.captured_monotonic, "used_at": visit["list_used_at"]},
            "resource_quote": {"frame_sha256": quote_capture.sha256, "captured_at": quote_capture.captured_monotonic},
            "transitions": list(visit["transitions"]),
        }

        active_state: dict[str, ResearchActiveObservation | None] = {"value": None}

        def start_plan_builder(captured: Any) -> _ActionPlan | None:
            nonlocal detail
            context.checkpoint()
            context.validate_identity()
            screen = _source_screen(
                context, captured,
                expected_detail_identity=listing.first_recommendation_identity,
            )
            fresh_detail = _fresh_start_detail(
                context, captured=captured, screen=screen, home=home,
                home_binding=binding, listing_capture=listing_capture,
                listing=listing, quote_capture=quote_capture,
                quote_screen=quote_screen,
                expected=detail,
            )
            if fresh_detail is None:
                return None
            detail = fresh_detail
            current_identity = detail.first_recommendation_identity
            now_bounds = screen.research_now_target_roi
            target_roi = screen.detail_research_target_roi
            if now_bounds is None or not (target_roi[2] <= now_bounds[0] or now_bounds[2] <= target_roi[0] or target_roi[3] <= now_bounds[1] or now_bounds[3] <= target_roi[1]):
                return None
            return _ActionPlan(
                f"recommended-research:{current_identity}:detail-research-button",
                target_roi,
                DETAIL_SCREEN,
                "RESEARCH_START",
                "RESEARCH_ACTIVE_WITH_TIMER",
                "START_RECOMMENDED_RESEARCH",
            )

        def active_successor(captured: Any) -> bool:
            screen = _source_screen(context, captured, expected_detail_identity=listing.first_recommendation_identity)
            active = _build_active_observation(screen)
            active_state["value"] = active
            verified = active is not None and tech_upgrade_postcondition_verified(detail, active, listing)
            if verified and active is not None:
                context._recommended_research_active_identity = active.active_technology_identity
                semantic_progress.update(
                    start_semantically_verified=True,
                    active_technology=active.active_technology_identity,
                    first_recommendation_identity=detail.first_recommendation_identity,
                    target_identity=detail.target_identity,
                    remaining_seconds=active.remaining_seconds,
                    research_duration_seconds=detail.duration_seconds,
                    exact_resource_costs={row.resource: row.cost for row in detail.resource_rows},
                    exact_resource_prebalances={row.resource: row.balance for row in detail.resource_rows},
                    prerequisite_evidence=list(detail.prerequisite_evidence),
                )
                semantic_progress["start_action"] = {
                    "target_identity": detail.target_identity,
                    "source_frame": _capture_ref(context, after) or None,
                    "successor_frame": _capture_ref(context, captured) or None,
                }
            return verified

        start_result, active_capture, start_verified = _guarded_action(
            context,
            policy,
            captured=after,
            game_day_id=game_day_id,
            occurrence_key=occurrence,
            action_key=start_action_key,
            plan_builder=start_plan_builder,
            recognizes_successor=active_successor,
            semantic_preconditions=lambda captured: _research_start_preconditions(detail, game_day_id),
            action_class=ActionClass.SPEND_OR_STRATEGIC,
            action_kind="research_start",
            subject=detail.first_recommendation_identity,
            resource_or_currency="food+wood+steel+gas",
            maximum_cost=None,
            free_only=False,
            cost_type="ordinary_resource_bundle",
            cost_amount=1,
            consequence_class="research_effect",
        )
        step += 1
        start_calls = max(
            sum(1 for key in context.runtime.action_keys if key == start_action_key),
            int(semantic_progress.get("start_semantically_verified") is True),
        )
        if start_calls > MAX_RESEARCH_TRANSPORT_CALLS:
            raise RuntimeError("RECOMMENDED_RESEARCH_TRANSPORT_LIMIT_EXCEEDED")
        start_source_ref = _capture_ref(context, after)
        start_successor_ref = _capture_ref(context, active_capture) if active_capture is not None else ""
        start_action_facts = {
            "target_identity": detail.target_identity,
            "source_frame": start_source_ref or None,
            "successor_frame": start_successor_ref or None,
        }
        progress_facts = dict(semantic_progress)
        progress_facts["start_action"] = start_action_facts
        if not start_verified or active_state["value"] is None or start_result.status != "completed":
            return _normal_result(
                context,
                status="unresolved",
                reason="research_start_successor_unknown",
                game_day_id=game_day_id,
                start_calls=start_calls,
                committed_action_count=int(semantic_progress.get("start_semantically_verified") is True),
                effect_reconciliation_required=True,
                identical_retry_denied=True,
                route_steps=step,
                partial_target=detail.first_recommendation_identity,
                **progress_facts,
            )
        active = active_state["value"]
        current = active_capture
        current, home_verified, step = _home_from_current(context, policy, current=current, game_day_id=game_day_id, occurrence_key=occurrence, step=step)
        if not home_verified:
            return _normal_result(
                context,
                status="unresolved",
                reason="research_confirmed_but_home_successor_unverified",
                game_day_id=game_day_id,
                start_calls=start_calls,
                committed_action_count=1,
                effect_reconciliation_required=True,
                identical_retry_denied=True,
                terminal_home_verified=False,
                route_steps=step,
                **semantic_progress,
            )
        return _normal_result(
            context,
            status="completed",
            reason="recommended_research_started_and_active_timer_verified",
            game_day_id=game_day_id,
            start_calls=start_calls,
            committed_action_count=1,
            terminal_home_verified=True,
            route_steps=step,
            completed=True,
            **semantic_progress,
        )
    except Exception as exc:
        try:
            calls = sum(1 for key in context.runtime.action_keys if key == start_action_key)
        except Exception:
            calls = 0
        if semantic_progress.get("start_semantically_verified") is True:
            calls = max(calls, 1)
        try:
            row = context.action_store.get_action_by_key(start_action_key)
            row_lookup_failed = False
        except Exception:
            row = None
            row_lookup_failed = True
        row_status = row.get("final_status") if isinstance(row, Mapping) else None
        possible_effect = bool(
            calls
            or row_status in {"prepared", "input_sent", "unresolved"}
            or row_lookup_failed
        )
        if (
            not possible_effect and not context.action_store.has_action_block()
            and isinstance(exc, RuntimeError) and str(exc).startswith((
                "RECOMMENDED_RESEARCH_TARGET_NOT_FRESHLY_BOUND",
                "RECOMMENDED_RESEARCH_PREINPUT_TARGET_CHANGED",
                "RECOMMENDED_RESEARCH_VISIT_CONTINUITY_LOST",
            ))
        ):
            # Only known pre-START/no-dispatch refusal can navigate out.
            # Revalidate ownership and inspect a real current capture first;
            # unknown/sent effects never enter this recovery branch.
            try:
                context.checkpoint()
                context.validate_identity()
                recovery_source = context.session.observe(
                    context.runtime.capture, label="recommended-research-prestart-refusal-source",
                )
                recovery_screen = _source_screen(context, recovery_source)
                if context.is_clean_home(recovery_source.frame) or (
                    recovery_screen.recognized and _return_plan(recovery_source.frame, recovery_screen) is not None
                ):
                    _, recovered, recovery_step = _home_from_current(
                        context, policy, current=recovery_source, game_day_id=game_day_id,
                        occurrence_key=occurrence_key, step=locals().get("step", 0),
                        key_name="prestart-refusal-return-home",
                    )
                    if recovered:
                        return _normal_result(
                            context, status="blocked", reason="research_prestart_proof_refused",
                            refusal=str(exc), game_day_id=game_day_id,
                            terminal_home_verified=True, route_steps=recovery_step,
                            **semantic_progress,
                        )
            except Exception:
                # Existing failure reporting retains all journals/evidence.
                pass
            possible_effect = possible_effect or context.action_store.has_action_block()
        if isinstance(row, Mapping) and row_status in {"prepared", "input_sent", "unresolved"}:
            try:
                context.action_store.mark_unresolved(
                    row["action_id"],
                    context.utc_clock(),
                    "research_route_exception_after_possible_dispatch",
                )
            except Exception:
                possible_effect = True
        try:
            accounting = context.accounting()
        except Exception:
            accounting = None
        progress_facts = dict(semantic_progress)
        action_facts = locals().get("start_action_facts")
        if isinstance(action_facts, Mapping):
            progress_facts["start_action"] = dict(action_facts)
        committed = int(
            calls == 1 and semantic_progress.get("start_semantically_verified") is True
        )
        try:
            partial = _normal_result(
                context,
                status="unresolved" if possible_effect else "blocked",
                reason=f"research_route_failed:{type(exc).__name__}",
                start_calls=calls,
                committed_action_count=committed,
                terminal_home_verified=False,
                accounting=accounting,
                game_day_id=game_day_id,
                effect_reconciliation_required=possible_effect,
                identical_retry_denied=possible_effect,
                **progress_facts,
            )
        except Exception:
            partial = {
                "flow_id": FLOW_ID,
                "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION,
                "status": "unresolved" if possible_effect else "blocked",
                "reason": f"research_route_failed:{type(exc).__name__}",
                "terminal_home_verified": False,
                "terminal_home_frame": None,
                "terminal_home_frame_sha256": None,
                "research_transport_calls": calls,
                "committed_action_count": committed,
                "total_action_count": calls,
                "total_input_count": accounting.input_count if accounting is not None else None,
                "input_count": accounting.input_count if accounting is not None else None,
                "session_input_count": accounting.session_input_count if accounting is not None else None,
                "runtime_input_count": accounting.runtime_input_count if accounting is not None else None,
                "accounting_verified": bool(accounting is not None and accounting.verified),
                "effect_reconciliation_required": possible_effect,
                "identical_retry_denied": possible_effect,
                **progress_facts,
            }
        input_count = accounting.input_count if accounting is not None else "unknown"
        raise RecommendedResearchRouteFailure(
            f"RECOMMENDED_RESEARCH_ROUTE_FAILED:{type(exc).__name__}:{exc};"
            f"inputs={input_count};research_transport_calls={calls}",
            partial_result=partial,
        ) from exc


def create_service_binding(make_native_route_binding: Callable[..., Any]) -> Any:
    """Bind the fixed service flow to this route driver without opening a device."""

    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:recommended-research",
        workflow="recommended-research-native",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_native_route,
        lease_seconds=3600.0,
    )
