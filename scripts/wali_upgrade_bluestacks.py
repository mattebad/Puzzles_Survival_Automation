"""Canonical native BlueStacks route for bounded batches of individual single-level Wali upgrades.

Each normal Core intent covers up to the remaining daily quota (capped at the
displayed evolution cap) of individual ordinary Upgrade inputs. Every input is
its own native action with its own fresh source frame, positively identified
single control and current icon-bound Antiserum quote. The cumulative level and
exact Antiserum debit are verified once after the batch; the separate
"Upgrade to Lv.N" row is never a target and is dismissed only at that final
verification boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    TransportResult,
)
from scripts.bounded_tesseract import call_ocr, tesseract_data
from tasks.hero_upgrade_disabled import (
    ANTISERUM,
    EVOLUTION_SCREEN,
    EVOLUTION_TARGET,
    HERO_IDENTITY,
    HERO_SCREEN,
    HERO_TARGET,
    MAX_CONFIRMED_UPGRADES,
    STANDARD_MANUALS,
    HeroUpgradeObservation,
    hero_evolution_authorizeable,
    hero_evolution_postcondition_verified,
    hero_evolution_spec,
    hero_upgrade_authorizeable,
    hero_upgrade_batch_input_authorizeable,
    hero_upgrade_batch_postcondition_verified,
    hero_upgrade_batch_spec,
    normal_upgrade_input_limit,
)
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE
from automation_service.registry import (
    WALI_UPGRADE_FLOW_ID as FLOW_ID,
    WALI_UPGRADE_PRODUCT_ID as PRODUCT_ID,
    WALI_UPGRADE_PRODUCT_REVISION as PRODUCT_REVISION,
    WALI_UPGRADE_PROFILE_ID as PROFILE_ID,
    WALI_UPGRADE_MAX_INPUTS as MAX_INPUTS,
)
from tasks.runtime_identity import FIXED_RUNTIME_SCOPE


MAX_ACTIONS = 6

_NORMAL_POSTCONDITION = "WALI_NORMAL_BATCH_CUMULATIVE_LEVEL_WITH_EXACT_ANTISERUM_DEBIT"
_EVOLUTION_POSTCONDITION = "WALI_STANDARD_EVOLUTION_WITH_EXACT_MATERIAL_USE"
_NORMAL_CONSEQUENCE = "upgrade_wali_individual_single_levels"
_BATCH_INPUT_CONTEXT = "WALI_BATCH_INPUT_CONTEXT_RETAINED_PENDING_FINAL_PROOF"
_EVOLUTION_CONSEQUENCE = "evolve_wali_with_standard_materials"
_EVOLUTION_COST_TYPE = "standard_hero_evolution_material_bundle"
_MAX_STABLE_CAPTURES = 4
_MAX_POST_ACTION_CAPTURES = 8
_MAX_ROSTER_SWIPES = 12
_MIN_SETTLE_SECONDS = 0.25
_DETAIL_PANEL = (35, 90, 765, 1260)
_EVOLUTION_PANEL = (60, 220, 740, 1030)
_PAIR_RE = re.compile(r"(?<![0-9.,])([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)(?![0-9.,])", re.ASCII)
_CURRENT_LEVEL_RE = re.compile(r"\blv\s*\.?\s*([0-9]+)\b", re.IGNORECASE | re.ASCII)
_MAX_LEVEL_RE = re.compile(r"\bmax\s*lv\s*\.?\s*([0-9]+)\b", re.IGNORECASE | re.ASCII)
_PREVIEW_MAX_RE = re.compile(r"\bmax\s*lv\s*\.?\s*([0-9]+)\b", re.IGNORECASE | re.ASCII)
_MANUAL_RECEIPT_RE = re.compile(
    r"(?:\[\s*)?combat\s+manual\s+([iv])(?:\s*\])?\s+used\b",
    re.IGNORECASE | re.ASCII,
)


@dataclass(frozen=True)
class _Word:
    text: str
    confidence: float
    roi: tuple[int, int, int, int]
    line: tuple[int, int, int]


@dataclass(frozen=True)
class _View:
    page: str
    observation: HeroUpgradeObservation | None
    words: tuple[_Word, ...]
    lines: tuple[tuple[str, tuple[_Word, ...]], ...]
    roster_target: tuple[int, int, int, int] | None = None
    home_hero_target: tuple[int, int, int, int] | None = None
    detail_evolve_target: tuple[int, int, int, int] | None = None
    bulk_target: tuple[int, int, int, int] | None = None
    reason: str = "unrecognized"


@dataclass(frozen=True)
class _PostCapture:
    captured: Any
    view: _View
    after: HeroUpgradeObservation | None
    verified: bool
    policy_observation: Observation


@dataclass
class _RouteState:
    evidence_refs: list[str]
    navigation_input_count: int = 0
    normal_transport_calls: int = 0
    evolution_transport_calls: int = 0
    total_action_count: int = 0
    normal_committed: int = 0
    evolution_committed: int = 0
    unknown_action_sent: bool = False
    identical_retry_denied: bool = False
    normal_batches: list[dict[str, object]] | None = None
    evolutions: list[dict[str, object]] | None = None
    terminal_home_verified: bool = False
    terminal_home_frame: dict[str, object] | None = None
    bulk_dismissals_attempted: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.normal_batches is None:
            self.normal_batches = []
        if self.evolutions is None:
            self.evolutions = []

    def add_ref(self, ref: str) -> None:
        if ref and ref not in self.evidence_refs:
            self.evidence_refs.append(ref)


class _HomeEvidence:
    @staticmethod
    def verified(context: Any, captured: Any) -> bool:
        context.checkpoint()
        return bool(context.is_clean_home(captured.frame))

def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold(), re.ASCII))


def _ocr_region(
    frame: np.ndarray, roi: tuple[int, int, int, int], *, field: int,
    psm: int = 7, grayscale: bool = False, minimum_confidence: float = 35,
) -> tuple[_Word, ...]:
    x0, y0, x1, y1 = roi
    scale = 1 if roi == (0, 0, 800, 1280) else 3
    image = frame[y0:y1, x0:x1]
    if grayscale:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if scale != 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    try:
        data = call_ocr(tesseract_data, image, config=f"--psm {psm}", call_timeout=5.0)
    except Exception:
        return ()
    fields = ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")
    if not isinstance(data, Mapping) or any(not isinstance(data.get(name), (tuple, list)) for name in fields):
        return ()
    words: list[_Word] = []
    for index in range(min(len(data[name]) for name in fields)):
        text = str(data["text"][index]).strip()
        if not _normal(text):
            continue
        try:
            confidence = float(data["conf"][index])
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            line_id = (field * 10000 + int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        except (TypeError, ValueError, OverflowError):
            continue
        if confidence < minimum_confidence or width <= 0 or height <= 0:
            continue
        box = (x0 + left // scale, y0 + top // scale,
               min(x1, x0 + (left + width + scale - 1) // scale),
               min(y1, y0 + (top + height + scale - 1) // scale))
        if 0 <= box[0] < box[2] <= 800 and 0 <= box[1] < box[3] <= 1280:
            words.append(_Word(text, confidence, box, line_id))
    return tuple(words)


def _numeric_words(frame: np.ndarray, roi: tuple[int, int, int, int], *, field: int) -> tuple[_Word, ...]:
    # Two readings of the same current pixels must agree. Never repair a missing
    # digit/slash from historical prices or interpret a decimal as a thousands separator.
    readings = [
        _ocr_region(frame, roi, field=field, grayscale=grayscale, minimum_confidence=70)
        for grayscale in (False, True)
    ]
    values = []
    for words in readings:
        text = " ".join(word.text for word in words)
        matches = list(_PAIR_RE.finditer(text))
        if len(matches) != 1:
            return ()
        match = matches[0]
        if re.search(r"[0-9]", text[:match.start()] + text[match.end():]):
            return ()
        values.append(tuple(int(value.replace(",", "")) for value in match.groups()))
    return readings[0] if values[0] == values[1] else ()


def _ocr_words(frame: np.ndarray) -> tuple[_Word, ...]:
    if not isinstance(frame, np.ndarray) or frame.shape != (1280, 800, 3):
        return ()
    # Keep the broad pass for unknown overlays and route-owned Home/roster states.
    # Known detail fields use small current-image ROIs, not past click coordinates.
    words = list(_ocr_region(frame, (0, 0, 800, 1280), field=0, psm=11))
    field = 0

    def replace_region(roi, *, numeric=False, psm=7):
        nonlocal words, field
        field += 1
        current = _numeric_words(frame, roi, field=field) if numeric else _ocr_region(frame, roi, field=field, psm=psm)
        words = [word for word in words if not _overlaps(word.roi, roi)]
        words.extend(current)

    replace_region((300, 10, 500, 65))
    replace_region((310, 75, 520, 125))
    replace_region((180, 210, 620, 270))
    lines = _lines(tuple(words))
    preview = len(_matches(lines, "Evolution Preview", y_min=180, y_max=350)) == 1
    detail = len(_matches(lines, "Hero", y_min=20, y_max=150)) == 1 and bool(_hero_name(lines))
    if preview:
        replace_region((150, 285, 650, 350))
        replace_region((300, 685, 510, 730))
        replace_region((300, 860, 510, 900))
        cards, unambiguous = _manual_cards(frame)
        if unambiguous:
            for _material, (x0, y0, x1, _y1) in cards:
                replace_region((max(0, x0 - 4), y0 - 24, min(800, x1 + 4), y0), numeric=True)
    elif detail:
        replace_region((200, 950, 600, 1080), psm=6)
        replace_region((130, 1175, 330, 1230))
        replace_region((480, 1175, 660, 1230))
        replace_region((100, 1080, 380, 1155))
    if preview or detail:
        for x0, y0, x1, y1 in _antiserum_icons(frame):
            center = (y0 + y1) // 2
            replace_region((x1 + 4, center - 18, min(740, x1 + 325), center + 18), numeric=True)
    return tuple(words)


def _lines(words: tuple[_Word, ...]) -> tuple[tuple[str, tuple[_Word, ...]], ...]:
    groups: dict[tuple[int, int, int], list[_Word]] = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    return tuple(
        (" ".join(word.text for word in ordered), ordered)
        for _key, group in sorted(groups.items())
        for ordered in (tuple(sorted(group, key=lambda word: word.roi[0])),)
    )


def _box(words: tuple[_Word, ...], pad: int = 7) -> tuple[int, int, int, int] | None:
    if not words:
        return None
    return (
        max(0, min(word.roi[0] for word in words) - pad),
        max(0, min(word.roi[1] for word in words) - pad),
        min(800, max(word.roi[2] for word in words) + pad),
        min(1280, max(word.roi[3] for word in words) + pad),
    )


def _matches(lines, phrase: str, *, y_min: int = 0, y_max: int = 1280):
    expected = _normal(phrase)
    return [
        (text, words)
        for text, words in lines
        if _normal(text) == expected
        and y_min <= (min(word.roi[1] for word in words) + max(word.roi[3] for word in words)) // 2 <= y_max
    ]


def _line_center_y(words: tuple[_Word, ...]) -> int:
    return (min(word.roi[1] for word in words) + max(word.roi[3] for word in words)) // 2

def _words_for_span(text: str, words: tuple[_Word, ...], start: int, end: int) -> tuple[_Word, ...]:
    selected: list[_Word] = []
    offset = 0
    for word in sorted(words, key=lambda item: item.roi[0]):
        word_start = offset
        word_end = word_start + len(word.text)
        if word_start < end and word_end > start:
            selected.append(word)
        offset = word_end + 1
    return tuple(selected)


def _load_antiserum_templates() -> tuple[tuple[np.ndarray, float], ...]:
    try:
        root = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "wali_upgrade" / "800x1280"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        templates = []
        for asset_id in ("antiserum-detail", "antiserum-preview", "antiserum-preview-compact"):
            matches = [row for row in manifest["templates"] if row.get("id") == asset_id]
            if len(matches) != 1:
                return ()
            row = matches[0]
            if (row.get("path") != asset_id + ".png" or row.get("material") != ANTISERUM
                    or row.get("runtime_profile") != "native-800x1280" or row.get("recognition_only") is not True):
                return ()
            data = (root / row["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != row.get("file_sha256"):
                return ()
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            width, height = row["template_pixel_size"]
            score = float(row["minimum_score"])
            if image is None or image.shape != (height, width, 3) or not 0.97 <= score <= 1.0:
                return ()
            image.setflags(write=False)
            templates.append((image, score))
        return tuple(templates)
    except (AttributeError, KeyError, OSError, TypeError, ValueError, cv2.error):
        return ()


_ANTISERUM_TEMPLATES = _load_antiserum_templates()


def _antiserum_icons(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    candidates = []
    left, top, right, bottom = 60, 500, 740, 1180
    search = frame[top:bottom, left:right]
    for template, minimum in _ANTISERUM_TEMPLATES:
        scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        while scores.size:
            _low, score, _low_at, at = cv2.minMaxLoc(scores)
            if not np.isfinite(score) or score < minimum:
                break
            width, height = template.shape[1], template.shape[0]
            x, y = at
            candidates.append((score, (left + x, top + y, left + x + width, top + y + height)))
            scores[max(0, y - height):y + height + 1, max(0, x - width):x + width + 1] = -1
    result = []
    for _score, box in sorted(candidates, reverse=True):
        if not any(_overlaps(box, existing) for existing in result):
            result.append(box)
    return result


def _antiserum_icon_matches(frame: np.ndarray, pair_box: tuple[int, int, int, int]) -> bool:
    x0, y0, _x1, y1 = pair_box
    return sum(
        0 <= x0 - box[2] <= 75
        and abs((y0 + y1) - (box[1] + box[3])) <= 40
        for box in _antiserum_icons(frame)
    ) == 1


def _load_manual_templates() -> dict[str, tuple[np.ndarray, np.ndarray, float, float, int, int]] | None:
    try:
        manifest_path = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "wali_upgrade" / "800x1280" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        profile = manifest.get("profile")
        rows = manifest.get("templates")
        if (
            manifest.get("schema_version") != 1
            or not isinstance(profile, dict)
            or profile.get("logical_size") != [800, 1280]
            or profile.get("runtime_profile") != "native-800x1280"
            or not isinstance(rows, list)
        ):
            return None
        expected = {f"combat-manual-{roman.lower()}": f"COMBAT_MANUAL_{roman}" for roman in ("I", "II", "III", "IV", "V")}
        entries = {
            row.get("id"): row
            for row in rows
            if isinstance(row, dict) and row.get("id") in expected
        }
        if len(entries) != sum(isinstance(row, dict) and row.get("id") in expected for row in rows):
            return None
        if set(entries) != set(expected):
            return None
        templates: dict[str, tuple[np.ndarray, np.ndarray, float, float, int, int]] = {}
        for asset_id, material in expected.items():
            entry = entries[asset_id]
            path = f"{asset_id}.png"
            dimensions = entry.get("template_pixel_size")
            tier_roi = entry.get("tier_roi_xyxy")
            if (
                entry.get("path") != path
                or entry.get("runtime_profile") != "native-800x1280"
                or entry.get("recognition_only") is not True
                or not isinstance(dimensions, list)
                or len(dimensions) != 2
                or not isinstance(tier_roi, list)
                or len(tier_roi) != 4
            ):
                return None
            width, height = (int(value) for value in dimensions)
            tx0, ty0, tx1, ty1 = (int(value) for value in tier_roi)
            if not (0 < width <= 800 and 0 < height <= 1280 and 0 <= tx0 < tx1 <= width and 0 <= ty0 < ty1 <= height):
                return None
            data = (manifest_path.parent / path).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry.get("file_sha256"):
                return None
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape != (height, width, 3):
                return None
            minimum_score = float(entry.get("minimum_score", 0))
            minimum_tier_score = float(entry.get("minimum_tier_score", 0))
            if not (0.97 <= minimum_score <= 1.0 and 0.97 <= minimum_tier_score <= 1.0):
                return None
            template = image.copy()
            tier = image[ty0:ty1, tx0:tx1].copy()
            template.setflags(write=False)
            tier.setflags(write=False)
            templates[material] = (template, tier, minimum_score, minimum_tier_score, tx0, ty0)
        return templates
    except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError, cv2.error):
        return None


_MANUAL_TEMPLATES = _load_manual_templates()


def _manual_cards(frame: np.ndarray) -> tuple[list[tuple[str, tuple[int, int, int, int]]], bool]:
    if _MANUAL_TEMPLATES is None or not isinstance(frame, np.ndarray) or frame.shape != (1280, 800, 3):
        return [], False
    left, top, right, bottom = 70, 500, 740, 900
    search = frame[top:bottom, left:right]
    cards: list[tuple[str, tuple[int, int, int, int]]] = []
    for material, (template, tier_template, minimum_score, minimum_tier_score, tx0, ty0) in _MANUAL_TEMPLATES.items():
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            return cards, False
        scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        while scores.size:
            _min_value, max_value, _min_location, max_location = cv2.minMaxLoc(scores)
            if not np.isfinite(max_value) or max_value < minimum_score:
                break
            match_x, match_y = left + max_location[0], top + max_location[1]
            tier_width, tier_height = tier_template.shape[1], tier_template.shape[0]
            tier = frame[match_y + ty0:match_y + ty0 + tier_height, match_x + tx0:match_x + tx0 + tier_width]
            if tier.shape == tier_template.shape:
                tier_score = float(cv2.matchTemplate(tier, tier_template, cv2.TM_CCOEFF_NORMED)[0, 0])
                if np.isfinite(tier_score) and tier_score >= minimum_tier_score:
                    cards.append((
                        material,
                        (match_x, match_y, match_x + template.shape[1], match_y + template.shape[0]),
                    ))
            suppression_x0 = max(0, max_location[0] - template.shape[1])
            suppression_y0 = max(0, max_location[1] - template.shape[0])
            suppression_x1 = min(scores.shape[1], max_location[0] + template.shape[1] + 1)
            suppression_y1 = min(scores.shape[0], max_location[1] + template.shape[0] + 1)
            scores[suppression_y0:suppression_y1, suppression_x0:suppression_x1] = -1
    for index, (_material, first) in enumerate(cards):
        for other_index in range(index + 1, len(cards)):
            if _overlaps(first, cards[other_index][1]):
                return cards, False
    return cards, True


def _manual_card_for_pair(
    pair_box: tuple[int, int, int, int],
    cards: list[tuple[str, tuple[int, int, int, int]]],
) -> tuple[str, tuple[int, int, int, int]] | None:
    x0, _y0, x1, y1 = pair_box
    candidates = [
        (material, icon_box)
        for material, icon_box in cards
        if x0 - 40 <= (icon_box[0] + icon_box[2]) // 2 <= x1 + 40
        and y1 - 3 <= icon_box[1] <= y1 + 120
    ]
    return candidates[0] if len(candidates) == 1 else None


def _manual_card_identity(
    frame: np.ndarray,
    pair_box: tuple[int, int, int, int],
) -> str | None:
    cards, unambiguous = _manual_cards(frame)
    match = _manual_card_for_pair(pair_box, cards) if unambiguous else None
    return match[0] if match is not None else None

def _overlaps(first: tuple[int, int, int, int] | None, second: tuple[int, int, int, int] | None) -> bool:
    if first is None or second is None:
        return False
    ax0, ay0, ax1, ay1 = first
    bx0, by0, bx1, by1 = second
    return bool(ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0)



def _parse_material_rows(
    frame: np.ndarray,
    lines,
    *,
    preview: bool,
) -> tuple[dict[str, int], dict[str, int], bool, bool]:
    y_min, y_max = (480, 850) if preview else (995, 1180)
    pair_rows: list[tuple[int, int, tuple[int, int, int, int]]] = []
    seen_boxes: set[tuple[int, int, int, int]] = set()
    complete = True
    manual_cards, manual_scan_unambiguous = _manual_cards(frame) if preview else ([], True)
    used_manual_cards: set[tuple[int, int, int, int]] = set()
    for text, words in lines:
        if not words or not y_min <= _line_center_y(words) <= y_max:
            continue
        for found in _PAIR_RE.finditer(text):
            try:
                balance, cost = (int(value.replace(",", "")) for value in found.groups())
            except (TypeError, ValueError, OverflowError):
                complete = False
                continue
            pair_words = _words_for_span(text, words, *found.span())
            if not pair_words or not y_min <= _line_center_y(pair_words) <= y_max:
                complete = False
                continue
            pair_box = _box(pair_words, pad=0)
            if pair_box is None or balance < 0 or cost <= 0 or pair_box in seen_boxes:
                complete = False
                continue
            seen_boxes.add(pair_box)
            pair_rows.append((balance, cost, pair_box))
    costs: dict[str, int] = {}
    balances: dict[str, int] = {}
    antiserum_rows = 0
    manual_rows = 0
    manual_identity_unproven = not manual_scan_unambiguous if preview else False
    for balance, cost, line_box in pair_rows:
        matched_manual = _manual_card_for_pair(line_box, manual_cards) if preview and manual_scan_unambiguous else None
        if matched_manual is not None:
            material, icon_box = matched_manual
            if icon_box in used_manual_cards:
                complete = False
                continue
            used_manual_cards.add(icon_box)
            manual_rows += 1
        elif _antiserum_icon_matches(frame, line_box):
            material = ANTISERUM
            antiserum_rows += 1
        else:
            complete = False
            manual_identity_unproven = manual_identity_unproven or bool(preview)
            continue
        if material in costs:
            complete = False
            continue
        costs[material] = cost
        balances[material] = balance
    if preview and len(used_manual_cards) != len(manual_cards):
        complete = False
    if preview:
        complete = bool(
            complete
            and len(pair_rows) >= 2
            and antiserum_rows == 1
            and manual_rows >= 1
            and len(costs) == len(pair_rows)
            and any(material in costs for material in STANDARD_MANUALS)
        )
    else:
        complete = bool(complete and len(pair_rows) == 1 and antiserum_rows == 1 and set(costs) == {ANTISERUM})
    return costs, balances, complete, manual_identity_unproven


def _hero_name(lines) -> str:
    candidates = []
    for text, words in lines:
        if not words:
            continue
        center_y = _line_center_y(words)
        min_x = min(word.roi[0] for word in words)
        max_x = max(word.roi[2] for word in words)
        normalized = _normal(text)
        if 75 <= center_y <= 125 and 310 <= min_x and max_x <= 520 and normalized and not re.search(r"[0-9]", normalized):
            if normalized not in {"hero", "story", "upgrade", "enhance", "troop skill", "hero skill"}:
                candidates.append(text.strip())
    unique = {" ".join(name.split()) for name in candidates}
    return next(iter(unique)) if len(unique) == 1 else ""


def _detail_levels(lines) -> tuple[int | None, int | None]:
    current_values: list[int] = []
    cap_values: list[int] = []
    for text, words in lines:
        if not words:
            continue
        y = _line_center_y(words)
        normalized = _normal(text)
        if 880 <= y <= 1110:
            cap_values.extend(int(match.group(1)) for match in _MAX_LEVEL_RE.finditer(text))
            if not any(token in normalized for token in ("max", "required", "upgrade", "evolve")):
                current_values.extend(int(match.group(1)) for match in _CURRENT_LEVEL_RE.finditer(text))
    current = current_values[0] if len(current_values) == 1 else None
    cap = cap_values[0] if len(cap_values) == 1 else None
    return current, cap


def _preview_caps(lines) -> tuple[int | None, int | None]:
    candidates = []
    for text, words in lines:
        if not words:
            continue
        values = [int(match.group(1)) for match in _PREVIEW_MAX_RE.finditer(text)]
        if len(values) == 2 and 250 <= _line_center_y(words) <= 430:
            candidates.append(tuple(values))
    unique = set(candidates)
    if len(unique) != 1:
        return None, None
    before, after = next(iter(unique))
    if before <= 0 or after <= before:
        return None, None
    return before, after


def _usage_receipts(lines) -> tuple[str, ...]:
    found = set()
    for text, _words in lines:
        for match in _MANUAL_RECEIPT_RE.finditer(text):
            found.add(f"COMBAT_MANUAL_{match.group(1).upper()}")
    return tuple(item for item in STANDARD_MANUALS if item in found)


def _view_signature(view: _View) -> tuple[object, ...]:
    obs = view.observation
    if obs is None:
        return (view.page, view.roster_target, view.home_hero_target)
    return (
        view.page,
        obs.hero_identity,
        obs.hero_selected,
        obs.current_level,
        obs.evolution_cap,
        obs.next_evolution_cap,
        tuple(sorted(obs.material_costs.items())),
        tuple(sorted(obs.material_balances.items())),
        obs.target_identity,
        obs.target_roi,
        obs.control_class,
        obs.normal_upgrade_visible,
        obs.normal_single_upgrade,
        obs.evolution_control_visible,
        obs.material_rows_complete,
        obs.overlay_state,
        obs.reset_guard_active,
        view.bulk_target,
    )



def _overlay_state(lines) -> str:
    for text, _words in lines:
        normalized = _normal(text)
        if (
            normalized in {"confirm", "cancel", "yes", "no", "ok", "close", "continue", "claim", "skip", "tap to continue", "are you sure"}
            or normalized.startswith("confirm ")
            or normalized.startswith("are you sure ")
        ):
            return "unknown"
    return "none_observed"
def _view(
    captured: Any,
    *,
    game_day_id: str,
    confirmed_upgrades: int,
    context: Any,
    previous: _View | None = None,
    seed: HeroUpgradeObservation | None = None,
) -> _View:
    words = _ocr_words(captured.frame)
    lines = _lines(words)
    evidence_ref = _evidence_ref(captured, context.session)
    hero_headers = _matches(lines, "Hero", y_min=20, y_max=150)
    preview_headers = _matches(lines, "Evolution Preview", y_min=180, y_max=350)
    reset_text = any(
        "resetting will return" in _normal(text) or "reset hero" in _normal(text)
        for text, _line_words in lines
    )
    overlay_state = _overlay_state(lines)
    if len(preview_headers) == 1:
        source_cap, next_cap = _preview_caps(lines)
        evolve_buttons = _matches(lines, "Evolve", y_min=600, y_max=1000)
        target = _box(evolve_buttons[0][1], pad=8) if len(evolve_buttons) == 1 else None
        costs, balances, rows_complete, manual_identity_unproven = _parse_material_rows(captured.frame, lines, preview=True)
        name = seed.hero_identity if seed is not None else ""
        selected = bool(seed is not None and seed.hero_selected and seed.hero_identity == HERO_IDENTITY)
        current_level = seed.current_level if seed is not None else None
        if seed is None or source_cap != seed.evolution_cap:
            selected = False
        recognized = bool(
            seed is not None
            and selected
            and source_cap is not None
            and next_cap is not None
            and current_level is not None
            and len(evolve_buttons) == 1
            and target is not None
            and not reset_text
            and overlay_state == "none_observed"
        )
        obs = None
        if recognized:
            obs = HeroUpgradeObservation(
                screen_state=EVOLUTION_SCREEN,
                hero_identity=name,
                hero_selected=selected,
                current_level=current_level,
                evolution_cap=source_cap,
                material_costs=costs,
                material_balances=balances,
                target_identity=EVOLUTION_TARGET,
                target_roi=target,
                panel_bounds=_EVOLUTION_PANEL,
                control_class="EVOLVE",
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                next_evolution_cap=next_cap,
                material_rows_complete=rows_complete,
                stable_selected_state=False,
                normal_upgrade_visible=False,
                normal_single_upgrade=False,
                evolution_control_visible=True,
                target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
                source_frame_sha256=str(captured.sha256),
                evidence_refs=(evidence_ref,) if evidence_ref else (),
                overlay_state=overlay_state,
                reset_guard_active=reset_text,
                runtime_profile_id=PROFILE_ID,
                recognized=True,
            )
        if reset_text:
            reason = "reset_overlay_detected"
        elif overlay_state != "none_observed":
            reason = "unknown_overlay_detected"
        elif manual_identity_unproven:
            reason = "manual_identity_unproven"
        else:
            reason = "recognized" if obs else "preview_missing_exact_wali_seed_or_materials"
        result = _View("evolution_preview", obs, words, lines, reason=reason)
        if previous is not None and previous.observation is not None and result.observation is not None and _view_signature(previous) == _view_signature(result):
            combined = tuple(dict.fromkeys((*previous.observation.evidence_refs, *result.observation.evidence_refs)))
            result = replace(result, observation=replace(result.observation, stable_selected_state=True, evidence_refs=combined))
        return result

    name = _hero_name(lines)
    current_level, evolution_cap = _detail_levels(lines)
    normal_buttons = _matches(lines, "Upgrade", y_min=1100, y_max=1250)
    evolve_buttons = _matches(lines, "Evolve", y_min=1100, y_max=1250)
    bulk_lines = [
        (text, row_words)
        for text, row_words in lines
        if "upgrade to lv" in _normal(text) or "upgrade to level" in _normal(text)
    ]
    bulk_target = _box(bulk_lines[0][1], pad=8) if len(bulk_lines) == 1 else None
    if len(bulk_lines) > 1:
        overlay_state = "unknown"
    normal_target = _box(normal_buttons[0][1], pad=8) if len(normal_buttons) == 1 else None
    detail_evolve = _box(evolve_buttons[0][1], pad=8) if len(evolve_buttons) == 1 else None
    is_detail = bool(
        len(hero_headers) == 1
        and name
        and current_level is not None
        and evolution_cap is not None
        and (normal_target is not None or detail_evolve is not None)
    )
    if is_detail:
        costs, balances, rows_complete, _manual_identity_unproven = _parse_material_rows(captured.frame, lines, preview=False)
        selected = name == HERO_IDENTITY
        use_evolve_target = bool(
            detail_evolve is not None
            and (normal_target is None or current_level == evolution_cap)
        )
        target = detail_evolve if use_evolve_target else normal_target
        target_id = EVOLUTION_TARGET if use_evolve_target else HERO_TARGET
        if target is None:
            return _View("unknown", None, words, lines, reason="detail_control_missing")
        normal_visible = normal_target is not None
        # The separate bulk row never makes the single control ambiguous unless
        # it overlaps it; its quote obstruction is judged by the material row.
        normal_single = bool(
            normal_visible
            and current_level < evolution_cap
            and not _overlaps(bulk_target, normal_target)
        )
        obs = HeroUpgradeObservation(
            screen_state=HERO_SCREEN,
            hero_identity=name,
            hero_selected=selected,
            current_level=current_level,
            evolution_cap=evolution_cap,
            material_costs=costs,
            material_balances=balances,
            target_identity=target_id,
            target_roi=target,
            panel_bounds=_DETAIL_PANEL,
            control_class="EVOLVE" if use_evolve_target else "UPGRADE",
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
            material_rows_complete=rows_complete,
            stable_selected_state=False,
            normal_upgrade_visible=normal_visible,
            normal_single_upgrade=normal_single,
            evolution_control_visible=detail_evolve is not None,
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            source_frame_sha256=str(captured.sha256),
            evidence_refs=(evidence_ref,) if evidence_ref else (),
            overlay_state=(
                "wali_bulk_row"
                if bulk_target is not None and overlay_state == "none_observed"
                else overlay_state
            ),
            bulk_row_roi=bulk_target,
            reset_guard_active=reset_text,
            runtime_profile_id=PROFILE_ID,
            recognized=not reset_text and overlay_state == "none_observed",
        )
        result = _View(
            "hero_detail",
            obs,
            words,
            lines,
            detail_evolve_target=detail_evolve,
            bulk_target=bulk_target,
            reason=(
                "reset_overlay_detected"
                if reset_text
                else "unknown_overlay_detected"
                if overlay_state != "none_observed"
                else "recognized"
            ),
        )
        if previous is not None and previous.observation is not None and _view_signature(previous) == _view_signature(result):
            combined = tuple(dict.fromkeys((*previous.observation.evidence_refs, *result.observation.evidence_refs)))
            result = replace(result, observation=replace(result.observation, stable_selected_state=True, evidence_refs=combined))
        return result

    roster_names = [
        (text, row_words)
        for text, row_words in lines
        if _normal(text) == "wali" and row_words and _line_center_y(row_words) > 180
    ]
    roster_target = _box(roster_names[0][1], pad=8) if len(roster_names) == 1 else None
    if len(hero_headers) == 1:
        result = _View("hero_roster", None, words, lines, roster_target=roster_target, reason="recognized_roster")
        if previous is not None and _view_signature(previous) == _view_signature(result):
            result = replace(result, reason="stable_roster")
        return result

    home_targets = [
        (text, row_words)
        for text, row_words in lines
        if _normal(text) in {"hero", "heroes"} and row_words and _line_center_y(row_words) >= 1080
    ]
    home_target = _box(home_targets[0][1], pad=8) if len(home_targets) == 1 else None
    return _View("unknown", None, words, lines, home_hero_target=home_target, reason="screen_not_recognized")


def _evidence_ref(captured: Any, session: Any) -> str:
    try:
        relative = Path(captured.path).resolve().relative_to(Path(session.session_directory).resolve())
    except (OSError, TypeError, ValueError):
        return ""
    return "evidence/" + relative.as_posix()


def _capture(context: Any, state: _RouteState, label: str) -> Any:
    context.checkpoint()
    captured = context.session.observe(context.runtime.capture, label=label)
    state.add_ref(_evidence_ref(captured, context.session))
    return captured


def _identity_value(context: Any, name: str) -> str:
    value = getattr(context.identity, name, None)
    if type(value) is not str or not value.strip():
        raise ValueError(f"Wali Upgrade requires current {name}")
    return value


def _sleep(context: Any) -> None:
    context.checkpoint()
    time.sleep(max(float(context.settle_seconds), _MIN_SETTLE_SECONDS))
    context.checkpoint()


def _stable_view(
    context: Any,
    state: _RouteState,
    *,
    label: str,
    game_day_id: str,
    confirmed_upgrades: int,
    seed: HeroUpgradeObservation | None = None,
    expected_page: str | None = None,
    home: _HomeEvidence | None = None,
) -> tuple[_View, Any]:
    previous: _View | None = None
    last: tuple[_View, Any] | None = None
    for attempt in range(_MAX_STABLE_CAPTURES):
        if previous is not None:
            _sleep(context)
        captured = _capture(context, state, f"{label}-{attempt + 1}")
        current = (
            _route_page(
                context,
                captured,
                home,
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                seed=seed,
            )
            if home is not None
            else _view(
                captured,
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                context=context,
                previous=previous,
                seed=seed,
            )
        )
        if home is not None and previous is not None and _view_signature(previous) == _view_signature(current):
            if current.observation is not None:
                refs = tuple(dict.fromkeys((*previous.observation.evidence_refs, *current.observation.evidence_refs))) if previous.observation else current.observation.evidence_refs
                current = replace(current, observation=replace(current.observation, stable_selected_state=True, evidence_refs=refs))
        last = (current, captured)
        if expected_page is not None and current.page != expected_page:
            previous = current
            continue
        if previous is not None and _view_signature(previous) == _view_signature(current):
            return current, captured
        previous = current
    if last is None:
        raise RuntimeError("Wali Upgrade could not capture a source frame")
    return last


def _scope_prefix(context: Any, game_day_id: str) -> str:
    account = _identity_value(context, "account_id")
    server = _identity_value(context, "server_id")
    scope = json.dumps(
        [FIXED_RUNTIME_SCOPE, account, server, game_day_id],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"{PRODUCT_ID}|{FLOW_ID}|{scope}|"


def _journaled_batch_inputs(row: Mapping[str, Any]) -> int | None:
    """Actual individual inputs persisted by the batch transport; never the planned limit."""
    try:
        transport = json.loads(str(row.get("transport_result_json") or ""))
        detail = json.loads(str(transport.get("detail") or ""))
        inputs = detail["inputs"]
        quotes = detail["quoted_antiserum"]
        sources = detail["source_frame_sha256"]
        limit = int(row.get("quantity"))
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if (
        transport.get("dispatched") is not True
        or type(inputs) is not int
        or not 1 <= inputs <= min(limit, MAX_CONFIRMED_UPGRADES)
        or not isinstance(quotes, list)
        or len(quotes) != inputs
        or not all(type(cost) is int and cost > 0 for cost in quotes)
        or not isinstance(sources, list)
        or len(sources) != inputs
        or not all(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{64}", source) for source in sources)
        or len(set(sources)) != inputs
    ):
        return None
    return inputs


def _history(context: Any, game_day_id: str) -> tuple[int, int, bool, bool, list[dict[str, Any]]]:
    prefix = _scope_prefix(context, game_day_id)
    rows = [
        row
        for row in context.action_store.list_actions_for_task(FLOW_ID)
        if str(row.get("action_key", "")).startswith(prefix)
    ]
    # First ordinal -> (row, legacy single). Historical confirmed single rows
    # (``normal|k``) remain durable count-one progress.
    normal: dict[int, tuple[dict[str, Any], bool]] = {}
    evolutions: list[dict[str, Any]] = []
    evolution_ordinals: set[int] = set()
    malformed = False
    for row in rows:
        suffix = str(row.get("action_key", ""))[len(prefix):]
        parts = suffix.split("|")
        try:
            if len(parts) == 2 and parts[0] in {"normal", "normal-batch"}:
                ordinal = int(parts[1])
                if ordinal not in {1, 2, 3} or ordinal in normal:
                    malformed = True
                    continue
                normal[ordinal] = (row, parts[0] == "normal")
            elif len(parts) == 4 and parts[0] == "evolution":
                before_cap, next_cap, ordinal = map(int, parts[1:])
                if (
                    before_cap < 1
                    or next_cap <= before_cap
                    or ordinal not in {1, 2, 3}
                    or ordinal in evolution_ordinals
                ):
                    malformed = True
                    continue
                evolution_ordinals.add(ordinal)
                evolutions.append(row)
            else:
                malformed = True
        except (TypeError, ValueError, OverflowError):
            malformed = True
    confirmed = 0
    contiguous = True
    for ordinal in sorted(normal):
        row, legacy = normal[ordinal]
        if row.get("final_status") != ActionStatus.CONFIRMED.value:
            continue
        inputs = 1 if legacy else _journaled_batch_inputs(row)
        if inputs is None:
            malformed = True
            continue
        contiguous = contiguous and ordinal == confirmed + 1
        confirmed += inputs
    contiguous = contiguous and confirmed <= MAX_CONFIRMED_UPGRADES
    evolution_contiguous = sorted(evolution_ordinals) == list(range(1, len(evolution_ordinals) + 1))
    normal_nonterminal = any(
        row.get("final_status") not in {ActionStatus.CONFIRMED.value, ActionStatus.CANCELLED.value}
        for row, _legacy in normal.values()
    )
    evolution_nonterminal = any(
        row.get("final_status") not in {ActionStatus.CONFIRMED.value, ActionStatus.CANCELLED.value}
        for row in evolutions
    )
    confirmed_evolutions = sum(row.get("final_status") == ActionStatus.CONFIRMED.value for row in evolutions)
    key_conflict = any(
        row.get("final_status") == ActionStatus.CANCELLED.value
        for row, _legacy in normal.values()
    ) or any(
        row.get("final_status") == ActionStatus.CANCELLED.value
        for row in evolutions
    )
    return confirmed, confirmed_evolutions, bool(malformed or not contiguous or not evolution_contiguous), bool(normal_nonterminal or evolution_nonterminal or key_conflict), rows


def _action_key(context: Any, game_day_id: str, *, phase: str, ordinal: int, cap: int | None = None, next_cap: int | None = None) -> str:
    prefix = _scope_prefix(context, game_day_id)
    if phase == "normal":
        # ``ordinal`` is the batch's first quota ordinal.
        return f"{prefix}normal-batch|{ordinal}"
    if phase == "evolution" and cap is not None and next_cap is not None:
        return f"{prefix}evolution|{cap}|{next_cap}|{ordinal}"
    raise ValueError("Wali Upgrade action identity is incomplete")


def _action_id(key: str, preconditions: tuple[str, ...]) -> str:
    quote = json.dumps([key, list(preconditions)], ensure_ascii=True, separators=(",", ":"))
    return "wali-upgrade:" + hashlib.sha256(quote.encode("utf-8")).hexdigest()


def _route_observation(
    context: Any,
    captured: Any,
    observation: HeroUpgradeObservation,
    *,
    consequence: str,
    postcondition: str,
    cost_type: str,
    cost_amount: int,
    quantity: int,
) -> Observation:
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=PROFILE_ID,
        width=int(captured.frame.shape[1]),
        height=int(captured.frame.shape[0]),
        valid_png=True,
        corrupt=False,
        black=not bool(captured.frame.any()),
        source_state=observation.screen_state,
        overlay_state=observation.overlay_state,
        target_identity=observation.target_identity,
        target_roi=tuple(observation.target_roi),
        recognized=bool(observation.recognized),
        control_class=observation.control_class,
        consequence=consequence,
        cost_type=cost_type,
        cost_amount=cost_amount,
        quantity=quantity,
        expected_postcondition=postcondition,
        evidence_refs=tuple(observation.evidence_refs),
        ocr_result_frame_sha256=str(captured.sha256),
        ocr_result_capture_completed_monotonic=float(captured.captured_monotonic),
        ocr_reused=False,
        source_family="hero_upgrade",
        target_isolated=True,
        package_foreground=str(context.runtime.measure_foreground_package()) == "com.global.ztmslg",
    )


def _semantic_after(
    before: HeroUpgradeObservation,
    view: _View,
    *,
    inputs: int,
    refs: tuple[str, ...],
    receipts: tuple[str, ...],
) -> HeroUpgradeObservation | None:
    """Bind one settled frame to the journaled normal inputs (zero for evolution)."""
    observed = view.observation
    if observed is None:
        return None
    return replace(
        observed,
        confirmed_upgrades=before.confirmed_upgrades + inputs,
        stable_selected_state=observed.stable_selected_state,
        spent_materials={},
        material_usage_receipts=receipts,
        evidence_refs=refs,
    )


def _post_verified(
    before: HeroUpgradeObservation,
    after: HeroUpgradeObservation | None,
    phase: str,
    *,
    quotes: tuple[int, ...] = (),
) -> bool:
    if after is None:
        return False
    if phase == "normal":
        return hero_upgrade_batch_postcondition_verified(
            before, after, inputs=len(quotes), quoted_costs=quotes,
        )
    return hero_evolution_postcondition_verified(before, after)


def _policy_post_observation(
    context: Any,
    captured: Any,
    view: _View,
    after: HeroUpgradeObservation | None,
    *,
    phase: str,
    cost_amount: int,
    quantity: int,
    verified: bool,
) -> Observation:
    obs = after or view.observation
    consequence = _NORMAL_CONSEQUENCE if phase == "normal" else _EVOLUTION_CONSEQUENCE
    cost_type = ANTISERUM if phase == "normal" else _EVOLUTION_COST_TYPE
    expected = _NORMAL_POSTCONDITION if phase == "normal" else _EVOLUTION_POSTCONDITION
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=PROFILE_ID,
        width=int(captured.frame.shape[1]),
        height=int(captured.frame.shape[0]),
        valid_png=True,
        corrupt=False,
        black=not bool(captured.frame.any()),
        source_state=obs.screen_state if verified and obs is not None else "UNKNOWN",
        overlay_state="none_observed" if verified else "unknown",
        target_identity=obs.target_identity if verified and obs is not None else None,
        target_roi=tuple(obs.target_roi) if verified and obs is not None else None,
        recognized=bool(verified),
        control_class=obs.control_class if verified and obs is not None else None,
        consequence=consequence if verified else None,
        cost_type=cost_type if verified else None,
        cost_amount=cost_amount if verified else None,
        quantity=quantity if verified else None,
        expected_postcondition=expected if verified else None,
        evidence_refs=tuple(obs.evidence_refs) if obs is not None else (),
        ocr_result_frame_sha256=str(captured.sha256),
        ocr_result_capture_completed_monotonic=float(captured.captured_monotonic),
        ocr_reused=False,
        source_family="hero_upgrade" if verified else None,
        target_isolated=bool(verified),
        package_foreground=str(context.runtime.measure_foreground_package()) == "com.global.ztmslg",
    )


def _home_verified(context: Any, captured: Any, home: _HomeEvidence) -> bool:
    try:
        return home.verified(context, captured)
    except Exception:
        return False


def _route_page(
    context: Any,
    captured: Any,
    home: _HomeEvidence,
    *,
    game_day_id: str,
    confirmed_upgrades: int,
    seed: HeroUpgradeObservation | None = None,
) -> _View:
    if _home_verified(context, captured, home):
        words = _ocr_words(captured.frame)
        lines = _lines(words)
        targets = [
            (text, line_words)
            for text, line_words in lines
            if _normal(text) in {"hero", "heroes"} and line_words and _line_center_y(line_words) >= 1080
        ]
        return _View(
            "home",
            None,
            words,
            lines,
            home_hero_target=_box(targets[0][1], pad=8) if len(targets) == 1 else None,
            reason="verified_home",
        )
    return _view(
        captured,
        game_day_id=game_day_id,
        confirmed_upgrades=confirmed_upgrades,
        context=context,
        seed=seed,
    )


def _nav_action(
    context: Any,
    state: _RouteState,
    home: _HomeEvidence,
    *,
    label: str,
    source_view: _View,
    source_capture: Any,
    target_identity: str,
    action: Callable[[Any, str, str], None],
    expected: Callable[[Any], bool],
    game_day_id: str,
    confirmed_upgrades: int,
    seed: HeroUpgradeObservation | None = None,
) -> tuple[bool, _View | None, Any | None, str]:
    if target_identity not in {"navigate_to_hero", "safe_return_home", "dismiss_wali_bulk_row"}:
        return False, None, None, "navigation_action_not_admitted"
    if context.session.input_count >= int(context.max_inputs) - 3:
        return False, None, None, "native_input_budget_reserve"
    action_key = (
        f"{FLOW_ID}|{context.session.invocation_id}|navigation|"
        f"{state.navigation_input_count + 1}|{target_identity}|{label}"
    )
    runtime = context.runtime
    nav_refs_before = int(getattr(runtime, "input_count", 0))
    state.add_ref(_evidence_ref(source_capture, context.session))

    def authorize(current: Any) -> None:
        context.validate_identity()
        current_view = _route_page(
            context,
            current,
            home,
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
            seed=seed,
        )
        if (
            current_view.page != source_view.page
            or _view_signature(current_view) != _view_signature(source_view)
        ):
            raise RuntimeError("Wali navigation source screen or selection changed before input")
        if source_view.page == "home" and not _home_verified(context, current, home):
            raise RuntimeError("Wali navigation source Home lost clean-Home verification")

    def dispatch(current: Any) -> None:
        action(current, action_key, target_identity)

    def recognize(current: Any) -> str:
        page = _route_page(
            context,
            current,
            home,
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
            seed=seed,
        )
        return "recognized" if expected(page) else "unknown"

    def settled() -> Any:
        _sleep(context)
        return _capture(context, state, f"{label}-settled")

    try:
        context.session.run_action(
            action_class="navigation",
            label=f"wali-upgrade-{label}",
            capture=runtime.capture,
            authorize=authorize,
            dispatch=dispatch,
            recognize=recognize,
            target_roi=None,
            consequence_class="navigation_only",
            settled_successor=settled,
        )
    except Exception as exc:
        sent = int(getattr(runtime, "input_count", 0)) - nav_refs_before
        state.navigation_input_count += max(0, sent)
        return False, None, None, f"{type(exc).__name__}:{exc}"
    sent = int(getattr(runtime, "input_count", 0)) - nav_refs_before
    state.navigation_input_count += max(0, sent)
    if sent != 1:
        return False, None, None, "navigation_transport_not_exactly_one"
    result_view, result_capture = _stable_view(
        context,
        state,
        label=f"{label}-verified",
        game_day_id=game_day_id,
        confirmed_upgrades=confirmed_upgrades,
        seed=seed,
        home=home,
    )
    if not expected(result_view):
        return False, result_view, result_capture, "navigation_successor_not_verified"
    return True, result_view, result_capture, "navigation_verified"


def _select_wali_from_roster(
    context: Any, state: _RouteState, home: _HomeEvidence, *,
    view: _View, captured: Any, game_day_id: str, confirmed_upgrades: int,
) -> tuple[bool, _View | None, Any | None, str]:
    for step in range(_MAX_ROSTER_SWIPES + 1):
        if view.page != "hero_roster":
            return False, view, captured, "wali_roster_not_recognized"
        if view.roster_target is not None:
            roi = view.roster_target

            def tap_wali(source: Any, key: str, target: str) -> None:
                context.runtime.tap(source, target_identity=target, target_roi=roi,
                                    action_key=key, action_class="navigation", consequential=False)

            return _nav_action(
                context, state, home, label="select-wali-card", source_view=view, source_capture=captured,
                target_identity="navigate_to_hero", action=tap_wali,
                expected=lambda candidate: candidate.page == "hero_detail"
                and candidate.observation is not None
                and candidate.observation.hero_identity == HERO_IDENTITY
                and candidate.observation.hero_selected and candidate.bulk_target is None,
                game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
            )
        if step == _MAX_ROSTER_SWIPES or context.session.input_count >= int(context.max_inputs) - 6:
            return False, view, captured, "wali_not_visible_within_roster_or_input_budget"

        def swipe_roster(source: Any, key: str, target: str) -> None:
            context.runtime.swipe(source, start=(370, 1030), end=(370, 300),
                                  action_key=key, target_identity=target)

        ok, next_view, next_capture, reason = _nav_action(
            context, state, home, label=f"roster-scroll-{step + 1}", source_view=view, source_capture=captured,
            target_identity="navigate_to_hero", action=swipe_roster,
            expected=lambda candidate: candidate.page == "hero_roster",
            game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
        )
        if not ok or next_view is None or next_capture is None:
            return False, next_view, next_capture, reason
        view, captured = next_view, next_capture
    raise AssertionError("bounded Wali roster selector exhausted unexpectedly")


def _reveal_single_upgrade_successor(
    context: Any, state: _RouteState, *, view: _View, captured: Any,
    game_day_id: str, confirmed_upgrades: int,
) -> tuple[bool, _View | None, Any | None, str]:
    """One non-spending Back; verify its actual successor, never press the bulk row."""
    home = _HomeEvidence()

    def selected_detail(candidate: _View) -> bool:
        obs = candidate.observation
        return bool(candidate.page == "hero_detail" and candidate.bulk_target is None
                    and obs is not None and obs.hero_identity == HERO_IDENTITY and obs.hero_selected)

    def back(source: Any, key: str, target: str) -> None:
        context.runtime.back(source, action_key=key, target_identity=target)

    ok, next_view, next_capture, reason = _nav_action(
        context, state, home, label="dismiss-single-upgrade-bulk-row", source_view=view, source_capture=captured,
        target_identity="dismiss_wali_bulk_row", action=back,
        expected=lambda candidate: selected_detail(candidate) or candidate.page == "hero_roster",
        game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
    )
    if not ok or next_view is None or next_capture is None:
        return False, next_view, next_capture, reason
    if selected_detail(next_view):
        return True, next_view, next_capture, reason
    return _select_wali_from_roster(
        context, state, home, view=next_view, captured=next_capture,
        game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
    )


def _return_home(
    context: Any,
    state: _RouteState,
    home: _HomeEvidence,
    *,
    view: _View,
    captured: Any,
    game_day_id: str,
    confirmed_upgrades: int,
) -> tuple[bool, Any | None, str]:
    current_view, current_capture = view, captured
    for step in range(4):
        if current_view.page == "home" and _home_verified(context, current_capture, home):
            _, reference = context.capture_reference(current_capture.path, current_capture.sha256)
            state.terminal_home_verified = True
            state.terminal_home_frame = reference.to_mapping()
            state.add_ref(_evidence_ref(current_capture, context.session))
            return True, current_capture, "verified_home"
        if current_view.page not in {"hero_detail", "hero_roster", "evolution_preview"}:
            return False, None, "home_return_source_unknown"
        if current_view.page == "evolution_preview":
            expected_page = "hero_detail"
        elif current_view.page == "hero_detail":
            expected_page = "hero_roster"
        else:
            expected_page = "home"

        preview_seed = current_view.observation if current_view.page == "evolution_preview" else None

        def back(source: Any, action_key: str, nav_target: str) -> None:
            context.runtime.back(source, action_key=action_key, target_identity=nav_target)

        def expected(candidate: _View) -> bool:
            return candidate.page == expected_page

        ok, next_view, next_capture, reason = _nav_action(
            context,
            state,
            home,
            label=f"return-home-{step + 1}",
            source_view=current_view,
            source_capture=current_capture,
            target_identity="safe_return_home",
            action=back,
            expected=expected,
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
            seed=preview_seed,
        )
        if not ok or next_view is None or next_capture is None:
            return False, None, reason
        current_view, current_capture = next_view, next_capture
    return False, None, "home_return_navigation_limit"


def _settle_post_action(
    context: Any,
    state: _RouteState,
    *,
    label: str,
    game_day_id: str,
    confirmed_upgrades: int,
    before: HeroUpgradeObservation,
    phase: str,
    seed: HeroUpgradeObservation | None,
    post_captures: list[_PostCapture],
    action_key: str,
    quotes: tuple[int, ...],
    allow_confirmation: bool,
) -> Any:
    previous_view = post_captures[-1].view if post_captures else None
    refs = [
        ref
        for capture in post_captures
        for ref in (_evidence_ref(capture.captured, context.session),)
        if ref
    ]
    receipts: set[str] = set()
    for capture in post_captures:
        receipts.update(_usage_receipts(capture.view.lines))
    last_capture = post_captures[-1].captured if post_captures else None
    for attempt in range(_MAX_POST_ACTION_CAPTURES):
        _sleep(context)
        captured = _capture(context, state, f"{label}-settled-{attempt + 1}")
        view = _view(
            captured,
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
            context=context,
            previous=previous_view,
            seed=seed,
        )
        if (
            allow_confirmation and phase == "normal" and view.page == "hero_detail"
            and view.bulk_target is not None and view.observation is not None
            and view.observation.stable_selected_state and view.observation.hero_selected
            and view.observation.hero_identity == HERO_IDENTITY
            and view.observation.overlay_state in {"none_observed", "wali_bulk_row"}
            and not view.observation.reset_guard_active
            and action_key not in state.bulk_dismissals_attempted
        ):
            # The one non-spending Back of this batch happens only here, at its
            # final verification boundary. Reserve it before input; an unknown
            # dismissal is never repeated by the executor's later read-only
            # reconciliation pass or a restarted route.
            state.bulk_dismissals_attempted.add(action_key)
            ok, revealed, revealed_capture, _reason = _reveal_single_upgrade_successor(
                context, state, view=view, captured=captured,
                game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
            )
            if not ok or revealed is None or revealed_capture is None:
                return captured
            view, captured = revealed, revealed_capture
        receipts.update(_usage_receipts(view.lines))
        ref = _evidence_ref(captured, context.session)
        if ref:
            refs.append(ref)
        after = _semantic_after(
            before,
            view,
            inputs=len(quotes) if phase == "normal" else 0,
            refs=tuple(dict.fromkeys(refs)),
            receipts=tuple(item for item in STANDARD_MANUALS if item in receipts),
        )
        verified = bool(allow_confirmation and _post_verified(before, after, phase, quotes=quotes))
        policy_observation = _policy_post_observation(
            context,
            captured,
            view,
            after,
            phase=phase,
            cost_amount=sum(quotes) if phase == "normal" else 1,
            quantity=len(quotes) if phase == "normal" else 1,
            verified=verified,
        )
        post_captures.append(_PostCapture(captured, view, after, verified, policy_observation))
        previous_view = view
        last_capture = captured
        required_refs = len(receipts) + 1 if receipts else 0
        if verified and len(set(refs)) >= required_refs:
            return captured
    return last_capture


def _dispatch_consequential(
    context: Any,
    state: _RouteState,
    *,
    before_view: _View,
    before_capture: Any,
    phase: str,
    ordinal: int,
    game_day_id: str,
    prior_confirmed: int,
    evolution_count: int,
) -> dict[str, Any]:
    before = before_view.observation
    if before is None or not before.stable_selected_state:
        return {"status": "blocked", "reason": "stable_wali_source_required", "transport_calls": 0}
    if phase == "normal":
        if not hero_upgrade_authorizeable(before):
            return {"status": "blocked", "reason": "normal_upgrade_preconditions_rejected", "transport_calls": 0}
        # Remaining quota, split only at the displayed cap and the route's action budget.
        input_limit = min(normal_upgrade_input_limit(before), MAX_ACTIONS - state.total_action_count)
        if input_limit < 1:
            return {"status": "blocked", "reason": "consequential_action_budget_exhausted", "transport_calls": 0}
        spec = hero_upgrade_batch_spec(before, input_limit)
        semantic_action = spec.action_kind
        target_identity = HERO_TARGET
        postcondition = _NORMAL_POSTCONDITION
        consequence = _NORMAL_CONSEQUENCE
        cost_type = ANTISERUM
        cost_amount = before.material_costs[ANTISERUM]
        action_key = _action_key(context, game_day_id, phase="normal", ordinal=ordinal)
    else:
        if not hero_evolution_authorizeable(before):
            return {"status": "blocked", "reason": "evolution_preconditions_rejected", "transport_calls": 0}
        input_limit = 1
        spec = hero_evolution_spec(before)
        semantic_action = spec.action_kind
        target_identity = EVOLUTION_TARGET
        postcondition = _EVOLUTION_POSTCONDITION
        consequence = _EVOLUTION_CONSEQUENCE
        cost_type = _EVOLUTION_COST_TYPE
        cost_amount = 1
        action_key = _action_key(
            context,
            game_day_id,
            phase="evolution",
            ordinal=evolution_count + 1,
            cap=before.evolution_cap,
            next_cap=before.next_evolution_cap,
        )
    store = context.action_store
    if store.action_key_exists(action_key):
        state.identical_retry_denied = True
        return {"status": "blocked", "reason": "canonical_action_key_already_exists", "action_key": action_key, "transport_calls": 0}
    if state.total_action_count >= MAX_ACTIONS:
        return {"status": "blocked", "reason": "consequential_action_budget_exhausted", "transport_calls": 0}
    if context.session.input_count >= int(context.max_inputs) - 3:
        return {"status": "blocked", "reason": "native_input_budget_reserve", "action_key": action_key, "transport_calls": 0}
    action_id = _action_id(action_key, spec.semantic_preconditions)
    now = float(context.utc_clock())
    request = PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action=semantic_action,
        expected_runtime_profile_id=PROFILE_ID,
        observation=_route_observation(
            context,
            before_capture,
            before,
            consequence=consequence,
            postcondition=postcondition,
            cost_type=cost_type,
            cost_amount=cost_amount,
            quantity=input_limit,
        ),
        monotonic_now=float(context.monotonic_clock()),
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        game_day_id=game_day_id,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        action_kind=spec.action_kind,
        subject=HERO_IDENTITY,
        resource_or_currency=spec.resource_or_currency,
        maximum_cost=spec.maximum_cost,
        free_only=False,
        allowed_confirmation_dialogs=spec.allowed_confirmation_dialogs,
        semantic_preconditions=spec.semantic_preconditions,
        semantic_postconditions=spec.semantic_postconditions,
        runtime_session_id=str(context.runtime.session),
    )
    policy = CentralPolicy(frozenset({FLOW_ID}))
    post_captures: list[_PostCapture] = []
    transport_attempts = 0
    sent_holder = {"count": 0}
    # Journal of individual inputs actually counted by the native runtime:
    # each input's own current quote and source frame. Never the planned limit.
    quotes: list[int] = []
    sources: list[str] = []
    stop_holder = {"reason": ""}
    runtime = context.runtime
    before_box = tuple(before.target_roi)
    action_class_value = ActionClass.SPEND_OR_STRATEGIC.value
    current_before_view = before_view
    current_before_capture = before_capture
    immediate_observation: Observation | None = None
    immediate_observation_supplied = False

    def recapture() -> Observation:
        nonlocal current_before_view, current_before_capture, immediate_observation
        nonlocal immediate_observation_supplied
        if immediate_observation is not None:
            if immediate_observation_supplied:
                raise RuntimeError("Wali pre-dispatch source was already consumed")
            immediate_observation_supplied = True
            return immediate_observation
        context.validate_identity()
        fresh_capture = _capture(context, state, f"wali-{phase}-pre-dispatch")
        fresh_view = _view(
            fresh_capture,
            game_day_id=game_day_id,
            confirmed_upgrades=prior_confirmed,
            context=context,
            previous=current_before_view,
            seed=before_view.observation if phase == "evolution" else None,
        )
        fresh = fresh_view.observation
        same = bool(
            fresh is not None
            and fresh.stable_selected_state
            and _view_signature(fresh_view) == _view_signature(current_before_view)
            and fresh.target_identity == target_identity
            and tuple(fresh.target_roi) == before_box
        )
        authorizeable = hero_upgrade_authorizeable(fresh) if phase == "normal" and fresh is not None else hero_evolution_authorizeable(fresh) if fresh is not None else False
        if not same or not authorizeable:
            raise ValueError("Wali exact source or selector changed before dispatch")
        current_before_view, current_before_capture = fresh_view, fresh_capture
        immediate_observation = _route_observation(
            context,
            fresh_capture,
            fresh,
            consequence=consequence,
            postcondition=postcondition,
            cost_type=cost_type,
            cost_amount=cost_amount,
            quantity=input_limit,
        )
        return immediate_observation

    try:
        capability_observation = recapture()
    except Exception as exc:
        return {"status": "blocked", "reason": f"pre_dispatch:{type(exc).__name__}:{exc}", "action_key": action_key, "transport_calls": 0}
    before = current_before_view.observation
    if before is None:
        return {"status": "blocked", "reason": "fresh_wali_source_missing", "transport_calls": 0}
    policy_now = float(context.utc_clock())
    capability_request = replace(
        request,
        observation=capability_observation,
        monotonic_now=float(context.monotonic_clock()),
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, policy_now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        policy_phase="pre_dispatch",
    )
    issued = policy.issue_capability(capability_request)
    store.audit(FLOW_ID, "capability_issued", policy_now, issued.audit, action_id)
    if not issued.authorized or issued.capability is None:
        return {"status": "blocked", "reason": issued.reason_code, "action_key": action_key, "transport_calls": 0}

    def journaled_quotes() -> tuple[int, ...]:
        return tuple(quotes) if phase == "normal" else ()

    def proof_allowed() -> bool:
        # Final proof only for the inputs the runtime actually counted.
        if phase == "normal":
            return bool(
                quotes and sent_holder["count"] == len(quotes) == len(sources)
                and not stop_holder["reason"].startswith(("transport_exception:", "input_context_unknown"))
            )
        return sent_holder["count"] == 1

    def record_post(captured: Any) -> bool:
        if any(item.captured.sha256 == captured.sha256 for item in post_captures):
            return post_captures[-1].verified
        view = _view(
            captured,
            game_day_id=game_day_id,
            confirmed_upgrades=prior_confirmed,
            context=context,
            seed=before_view.observation if phase == "evolution" else None,
        )
        ref = _evidence_ref(captured, context.session)
        receipts = _usage_receipts(view.lines)
        after = _semantic_after(
            before, view, inputs=len(quotes) if phase == "normal" else 0,
            refs=(ref,) if ref else (), receipts=receipts,
        )
        verified = bool(proof_allowed() and _post_verified(before, after, phase, quotes=journaled_quotes()))
        policy_obs = _policy_post_observation(
            context,
            captured,
            view,
            after,
            phase=phase,
            cost_amount=sum(quotes) if phase == "normal" else 1,
            quantity=len(quotes) if phase == "normal" else 1,
            verified=verified,
        )
        post_captures.append(_PostCapture(captured, view, after, verified, policy_obs))
        return verified

    def batch_input_context(captured: Any) -> str:
        # Context only; the level/debit effect is proven once after the batch.
        view = _view(captured, game_day_id=game_day_id, confirmed_upgrades=prior_confirmed, context=context)
        obs = view.observation
        retained = bool(
            view.page == "hero_detail" and obs is not None
            and obs.hero_identity == HERO_IDENTITY and obs.hero_selected
            and obs.recognized and not obs.reset_guard_active
            and obs.overlay_state in {"none_observed", "wali_bulk_row"}
        )
        if not retained:
            stop_holder["reason"] = "input_context_unknown"
        return _BATCH_INPUT_CONTEXT if retained else "unknown"

    def input_admissible(observed: HeroUpgradeObservation, index: int, previous: HeroUpgradeObservation | None) -> bool:
        if phase == "evolution":
            return hero_evolution_authorizeable(observed)
        if index == 0:
            return hero_upgrade_authorizeable(observed)
        return hero_upgrade_batch_input_authorizeable(
            before, observed, input_limit=input_limit,
            quoted_costs=tuple(quotes), previous_source=previous,
        )

    def stop_reason(view: _View, previous: HeroUpgradeObservation | None) -> str:
        observed = view.observation
        if view.page != "hero_detail" or observed is None:
            return "batch_source_not_recognized"
        if not observed.stable_selected_state:
            return "batch_source_not_settled"
        if not observed.material_rows_complete or ANTISERUM not in observed.material_costs:
            return "current_quote_not_readable"
        if _is_shortage(observed, evolution=False):
            return "current_quote_unaffordable"
        if sum(quotes) + observed.material_costs[ANTISERUM] > before.material_balances[ANTISERUM]:
            return "cumulative_quote_exceeds_baseline_balance"
        if previous is not None and (
            observed.current_level, observed.material_balances.get(ANTISERUM),
            observed.material_costs.get(ANTISERUM),
        ) == (
            previous.current_level, previous.material_balances.get(ANTISERUM),
            previous.material_costs.get(ANTISERUM),
        ):
            return "current_source_not_fresh"
        return "batch_input_guard_rejected"

    def transport(_intent: Any) -> TransportResult:
        nonlocal transport_attempts
        transport_attempts += 1
        starting_runtime_inputs = int(getattr(runtime, "input_count", 0))
        starting_navigation_inputs = state.navigation_input_count

        def counted() -> int:
            return (
                int(getattr(runtime, "input_count", 0)) - starting_runtime_inputs
                - (state.navigation_input_count - starting_navigation_inputs)
            )

        def send_one(index: int, source_view: _View, source_capture: Any, previous: HeroUpgradeObservation | None) -> None:
            observed = source_view.observation
            assert observed is not None
            box = tuple(observed.target_roi)
            input_key = action_key if phase == "evolution" else f"{action_key}#input-{index + 1}"
            supplied = False

            def action_capture(label: str) -> Any:
                nonlocal supplied
                context.checkpoint()
                if not supplied:
                    supplied = True
                    return source_capture
                return runtime.capture(label)

            def authorize(current: Any) -> None:
                context.validate_identity()
                pending = store.get_action_by_key(action_key)
                if (
                    pending is None
                    or pending.get("action_id") != action_id
                    or pending.get("final_status") != ActionStatus.PREPARED.value
                    or not store.lease_valid_for(context.session.owner, float(context.utc_clock()))
                ):
                    raise RuntimeError("Wali batch intent or current owner lease is not active")
                # The SDK receives this input's genuine parsed source capture,
                # not a new, retimestamped or earlier input's frame.
                if (
                    current is not source_capture
                    or current.sha256 != source_capture.sha256
                    or current.captured_monotonic != source_capture.captured_monotonic
                    or not observed.stable_selected_state
                    or observed.source_frame_sha256 != str(source_capture.sha256)
                    or observed.target_identity != target_identity
                    or (index == 0 and box != before_box)
                    or not input_admissible(observed, index, previous)
                ):
                    raise RuntimeError("Wali input source frame or exact single control changed before native dispatch")
                context.checkpoint()
                context.validate_identity()

            def dispatch(current: Any) -> None:
                context.checkpoint()
                age = float(context.monotonic_clock()) - float(current.captured_monotonic)
                if not 0 <= age <= request.dispatch_max_age_seconds:
                    raise RuntimeError("Wali immediate-before capture expired before transport")
                runtime.tap(
                    current,
                    target_identity=target_identity,
                    target_roi=box,
                    action_key=input_key,
                    action_class=action_class_value,
                    consequential=True,
                )
                sent_holder["count"] = max(0, counted())

            def settled_successor() -> Any:
                return _settle_post_action(
                    context,
                    state,
                    label=f"wali-{phase}-successor",
                    action_key=action_key,
                    quotes=(),
                    game_day_id=game_day_id,
                    confirmed_upgrades=prior_confirmed,
                    before=before,
                    phase=phase,
                    seed=before_view.observation,
                    post_captures=post_captures,
                    allow_confirmation=sent_holder["count"] == 1,
                )

            already = counted()
            try:
                if phase == "normal":
                    context.session.run_action(
                        action_class=action_class_value,
                        label=f"wali-normal-batch-{ordinal}-input-{index + 1}",
                        capture=action_capture,
                        authorize=authorize,
                        dispatch=dispatch,
                        recognize=batch_input_context,
                        target_roi=box,
                        consequence_class=consequence,
                    )
                else:
                    context.session.run_action(
                        action_class=action_class_value,
                        label=f"wali-evolution-{ordinal}",
                        capture=action_capture,
                        authorize=authorize,
                        dispatch=dispatch,
                        recognize=lambda captured: postcondition if record_post(captured) else "unknown",
                        target_roi=box,
                        consequence_class=consequence,
                        settled_successor=settled_successor,
                    )
            finally:
                if phase == "normal" and counted() == already + 1:
                    quotes.append(int(observed.material_costs[ANTISERUM]))
                    sources.append(str(source_capture.sha256))

        code = "INPUTS_SENT"
        source_view, source_capture = current_before_view, current_before_capture
        previous: HeroUpgradeObservation | None = None
        try:
            for index in range(input_limit):
                if index:
                    if context.session.input_count >= int(context.max_inputs) - 3:
                        stop_holder["reason"] = "native_input_budget_reserve"
                        break
                    # A fresh current source for the next individual input: no
                    # Back, no intermediate level settlement, own current quote.
                    source_view, source_capture = _stable_view(
                        context, state,
                        label=f"wali-normal-batch-{ordinal}-input-{index + 1}-source",
                        game_day_id=game_day_id, confirmed_upgrades=prior_confirmed,
                        expected_page="hero_detail",
                    )
                    if source_view.observation is None or not input_admissible(source_view.observation, index, previous):
                        stop_holder["reason"] = stop_reason(source_view, previous)
                        break
                send_one(index, source_view, source_capture, previous)
                if stop_holder["reason"] == "input_context_unknown":
                    break
                previous = source_view.observation
            else:
                stop_holder["reason"] = "input_limit_reached"
        except Exception as exc:
            code = f"TRANSPORT_{type(exc).__name__}"
            stop_holder["reason"] = f"transport_exception:{type(exc).__name__}"
        sent = counted()
        sent_holder["count"] = sent
        if sent == 0 and code == "INPUTS_SENT":
            code = "INPUT_NOT_SENT"
        if phase == "evolution":
            return TransportResult(sent > 0, f"WALI_EVOLUTION_{code.replace('INPUTS_SENT', 'INPUT_SENT')}")
        detail = json.dumps(
            {
                "inputs": len(quotes),
                "quoted_antiserum": list(quotes),
                "source_frame_sha256": list(sources),
                "stop_reason": stop_holder["reason"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return TransportResult(sent > 0, f"WALI_NORMAL_BATCH_{code}", detail)

    def post_observe():
        if not post_captures:
            record_post(_capture(context, state, f"wali-{phase}-reconcile-source"))
        if not any(item.verified for item in post_captures):
            _settle_post_action(
                context,
                state,
                label=f"wali-{phase}-reconcile",
                action_key=action_key,
                quotes=journaled_quotes(),
                game_day_id=game_day_id,
                confirmed_upgrades=prior_confirmed,
                before=before,
                phase=phase,
                seed=before_view.observation if phase == "evolution" else None,
                post_captures=post_captures,
                allow_confirmation=proof_allowed(),
            )
        for item in post_captures:
            yield item.policy_observation

    def reconcile(_intent: Any, observed: Observation) -> bool:
        return bool(
            proof_allowed()
            and any(
                item.verified and item.captured.sha256 == observed.frame_sha256
                for item in post_captures
            )
        )

    def account(sent: int) -> int:
        # Physical consequential inputs: individual normal inputs, or evolution attempts.
        physical = max(0, sent) if phase == "normal" else transport_attempts
        if phase == "normal":
            state.normal_transport_calls += physical
        else:
            state.evolution_transport_calls += physical
        state.total_action_count += physical
        return physical

    starting_runtime_inputs = int(getattr(runtime, "input_count", 0))
    starting_navigation_inputs = state.navigation_input_count
    try:
        execution = SafeActionExecutor(
            store,
            policy,
            context.session.owner,
            lambda: float(context.monotonic_clock()),
            transport,
            recapture,
            post_observe,
            reconcile,
            wall_clock=lambda: float(context.utc_clock()),
            max_pre_dispatch_attempts=1,
        ).execute(request, issued.capability)
        row = store.get_action_by_key(action_key)
    except Exception as exc:
        ending_runtime_inputs = int(getattr(runtime, "input_count", starting_runtime_inputs))
        sent = ending_runtime_inputs - starting_runtime_inputs - (state.navigation_input_count - starting_navigation_inputs)
        physical = account(sent)
        try:
            blocked = bool(store.has_action_block())
            duplicate = bool(store.action_key_exists(action_key))
        except Exception:
            blocked, duplicate = True, True
        unresolved = bool(sent or blocked)
        state.unknown_action_sent = state.unknown_action_sent or unresolved
        state.identical_retry_denied = state.identical_retry_denied or unresolved or duplicate
        return {
            "status": "unknown" if unresolved else "blocked",
            "reason": f"executor:{type(exc).__name__}:{exc}",
            "action_key": action_key,
            "transport_calls": physical,
            "sent": sent,
        }

    sent = int(getattr(runtime, "input_count", starting_runtime_inputs)) - starting_runtime_inputs - (state.navigation_input_count - starting_navigation_inputs)
    physical = account(sent)
    candidate = next((item for item in reversed(post_captures) if item.verified), None)
    accounting_consistent = (
        int(execution.transport_calls) == transport_attempts
        and sent == sent_holder["count"]
        and 0 <= sent <= input_limit
        and (phase == "evolution" or sent == len(quotes) == len(sources))
    )
    confirmed = bool(
        accounting_consistent
        and sent >= 1
        and execution.status is ActionStatus.CONFIRMED
        and row is not None
        and row.get("final_status") == ActionStatus.CONFIRMED.value
        and candidate is not None
        and (phase == "evolution" or _journaled_batch_inputs(row) == sent)
    )
    if not confirmed:
        try:
            blocked = bool(store.has_action_block())
            duplicate = bool(store.action_key_exists(action_key))
        except Exception:
            blocked, duplicate = True, True
        unresolved = bool(
            execution.status is ActionStatus.UNRESOLVED
            or sent
            or not accounting_consistent
            or blocked
        )
        state.unknown_action_sent = state.unknown_action_sent or unresolved
        state.identical_retry_denied = state.identical_retry_denied or unresolved or duplicate
        return {
            "status": "unknown" if unresolved else "blocked",
            "reason": execution.reason,
            "action_key": action_key,
            "transport_calls": physical,
            "sent": sent,
        }

    before_mapping = asdict(before)
    after_mapping = asdict(candidate.after)
    if phase == "normal":
        state.normal_committed += sent
        assert state.normal_batches is not None
        state.normal_batches.append({
            "action_key": action_key,
            "first_ordinal": ordinal,
            "input_limit": input_limit,
            "normal_inputs": sent,
            "quoted_antiserum_costs": list(quotes),
            "stop_reason": stop_holder["reason"],
            "before": before_mapping,
            "after": after_mapping,
            "semantic_verified": True,
        })
    else:
        state.evolution_committed += 1
        assert state.evolutions is not None
        state.evolutions.append({
            "action_key": action_key,
            "before": before_mapping,
            "after": after_mapping,
            "semantic_verified": True,
        })
    return {
        "status": "confirmed",
        "reason": execution.reason,
        "action_key": action_key,
        "transport_calls": physical,
        "sent": sent,
        "inputs": sent if phase == "normal" else 0,
        "stop_reason": stop_holder["reason"],
        "before": before,
        "after": candidate.after,
        "successor_capture": candidate.captured,
    }


def _is_shortage(observation: HeroUpgradeObservation, *, evolution: bool) -> bool:
    if not observation.material_rows_complete:
        return False
    costs = observation.material_costs
    balances = observation.material_balances
    if ANTISERUM not in costs or set(costs) - ({ANTISERUM, *STANDARD_MANUALS} if evolution else {ANTISERUM}):
        return False
    if evolution and not (set(costs) & set(STANDARD_MANUALS)):
        return False
    return any(balances.get(material, -1) < cost for material, cost in costs.items())




def _result(
    *,
    status: str,
    reason: str,
    game_day_id: str,
    occurrence_key: Any,
    prior_confirmed: int,
    confirmed: int,
    state: _RouteState,
    input_actions: int,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "game_day_id": game_day_id,
        "hero_identity": HERO_IDENTITY,
        "occurrence_key": occurrence_key,
        "prior_confirmed_upgrades": prior_confirmed,
        "confirmed_upgrades": confirmed,
        "level_upgrade_committed_count": state.normal_committed,
        "evolution_committed_count": state.evolution_committed,
        "committed_action_count": state.normal_committed + state.evolution_committed,
        "upgrade_transport_calls": state.normal_transport_calls,
        "evolution_transport_calls": state.evolution_transport_calls,
        "total_action_count": state.total_action_count,
        "input_actions": input_actions,
        "normal_batches": list(state.normal_batches or ()),
        "evolutions": list(state.evolutions or ()),
        "unknown_action_sent": state.unknown_action_sent,
        "identical_retry_denied": state.identical_retry_denied,
        "terminal_home_verified": state.terminal_home_verified,
        "terminal_home_frame": state.terminal_home_frame,
        "terminal_home_frame_sha256": (
            state.terminal_home_frame["frame_sha256"] if state.terminal_home_frame else None
        ),
        "evidence_refs": list(state.evidence_refs),
        "campaign_reset_evidence_required": True,
        "reset_transport_calls": 0,
        "reset_count_unchanged": True,
    }


def run_wali_upgrade_service_route(
    context: Any, arguments: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Run the remaining normal quota using batches of individual single Upgrade inputs."""

    starting_session_inputs = int(context.session.input_count)
    state = _RouteState(evidence_refs=[])
    game_day_id = ""
    prior_confirmed = 0
    confirmed_upgrades = 0
    status = "ready"
    reason = "route_not_started"
    home: _HomeEvidence | None = None
    current_view: _View | None = None
    current_capture: Any | None = None
    try:
        if arguments:
            raise ValueError("Wali native route accepts no runtime-selected action arguments")
        if (
            context.flow_id != FLOW_ID
            or context.product_id != PRODUCT_ID
            or context.product_revision != PRODUCT_REVISION
            or context.runtime_profile_id != PROFILE_ID
            or int(context.max_inputs) != MAX_INPUTS
            or int(context.max_actions) != MAX_ACTIONS
        ):
            raise ValueError("Wali Upgrade fixed native binding does not match its route contract")
        if context.runtime_input_lock is None or not bool(context.runtime_input_lock.held):
            raise ValueError("Wali Upgrade requires the held native runtime input lock")
        context.runtime_input_lock.assert_held("automation-service", context.runtime_input_lock.invocation_id)
        context.validate_identity()
        context.checkpoint()
        game_day_id = _identity_value(context, "reset_id")
        prior_confirmed, prior_evolutions, malformed, blocked_history, _rows = _history(context, game_day_id)
        confirmed_upgrades = prior_confirmed
        if malformed or prior_confirmed > MAX_CONFIRMED_UPGRADES or prior_evolutions > MAX_CONFIRMED_UPGRADES:
            reason = "canonical_wali_history_invalid"
            context.validate_identity()
            return _result(
                status="blocked", reason=reason, game_day_id=game_day_id,
                occurrence_key=context.occurrence_key, prior_confirmed=prior_confirmed,
                confirmed=confirmed_upgrades, state=state,
                input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
            )
        if blocked_history or context.action_store.has_action_block():
            state.identical_retry_denied = True
            reason = "canonical_wali_action_unresolved_or_nonterminal"
            context.validate_identity()
            return _result(
                status="blocked", reason=reason, game_day_id=game_day_id,
                occurrence_key=context.occurrence_key, prior_confirmed=prior_confirmed,
                confirmed=confirmed_upgrades, state=state,
                input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
            )
        if context.is_clean_home(context.initial_frame.frame):
            context.bind_initial_observation(context.initial_frame)
        else:
            context.prepare_startup(
                source_context="wali_upgrade_canonical_startup",
                recognize_successor=lambda captured: context.is_clean_home(captured.frame),
                action_key=f"wali-upgrade-startup:{context.invocation_id}",
                settle_seconds=context.settle_seconds,
            )
        home = _HomeEvidence()
        current_capture = _capture(context, state, "wali-upgrade-initial")
        current_view = _route_page(
            context,
            current_capture,
            home,
            game_day_id=game_day_id,
            confirmed_upgrades=confirmed_upgrades,
        )
        if current_view.page == "home":
            current_view, current_capture = _stable_view(
                context,
                state,
                label="wali-clean-home-entry",
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                expected_page="home",
                home=home,
            )
            current_view = _route_page(
                context,
                current_capture,
                home,
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
            )
        elif current_view.page == "hero_detail":
            current_view, current_capture = _stable_view(
                context,
                state,
                label="wali-existing-detail",
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                expected_page="hero_detail",
            )
        elif current_view.page == "hero_roster":
            current_view, current_capture = _stable_view(
                context,
                state,
                label="wali-existing-roster",
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
                expected_page="hero_roster",
            )
        else:
            reason = current_view.reason
            status = "blocked"
            context.validate_identity()
            return _result(
                status=status, reason=reason, game_day_id=game_day_id,
                occurrence_key=context.occurrence_key, prior_confirmed=prior_confirmed,
                confirmed=confirmed_upgrades, state=state,
                input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
            )

        if confirmed_upgrades >= MAX_CONFIRMED_UPGRADES:
            if current_view.page == "home":
                _, reference = context.capture_reference(current_capture.path, current_capture.sha256)
                state.terminal_home_verified = True
                state.terminal_home_frame = reference.to_mapping()
                status, reason = "completed", "daily_wali_upgrade_quota_already_confirmed"
            else:
                ok, home_capture, home_reason = _return_home(
                    context, state, home, view=current_view, captured=current_capture,
                    game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
                )
                status = "completed" if ok else "blocked"
                reason = "daily_wali_upgrade_quota_already_confirmed" if ok else home_reason
            context.validate_identity()
            return _result(
                status=status, reason=reason, game_day_id=game_day_id,
                occurrence_key=context.occurrence_key, prior_confirmed=prior_confirmed,
                confirmed=confirmed_upgrades, state=state,
                input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
            )

        if current_view.page == "home":
            if current_view.home_hero_target is None:
                reason = "home_hero_navigation_target_not_uniquely_visible"
                status = "blocked"
            else:
                home_source = current_capture
                nav_state = current_view
                roi = current_view.home_hero_target

                def tap_hero(source: Any, action_key: str, nav_target: str) -> None:
                    context.runtime.tap(
                        source,
                        target_identity=nav_target,
                        target_roi=roi,
                        action_key=action_key,
                        action_class="navigation",
                        consequential=False,
                    )

                ok, next_view, next_capture, reason = _nav_action(
                    context, state, home, label="open-hero-roster",
                    source_view=nav_state, source_capture=home_source,
                    target_identity="navigate_to_hero", action=tap_hero,
                    expected=lambda candidate: candidate.page == "hero_roster",
                    game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
                )
                if not ok:
                    status = "blocked"
                else:
                    current_view, current_capture = next_view, next_capture
        if current_view is not None and current_view.page == "hero_roster" and status != "blocked":
            ok, next_view, next_capture, reason = _select_wali_from_roster(
                context, state, home, view=current_view, captured=current_capture,
                game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
            )
            if not ok or next_view is None or next_capture is None:
                status = "blocked"
            else:
                current_view, current_capture = next_view, next_capture

        while status != "blocked" and current_view is not None and current_capture is not None and confirmed_upgrades < MAX_CONFIRMED_UPGRADES:
            context.validate_identity()
            context.checkpoint()
            if current_view.page == "evolution_preview":
                # A preview that was already open on route entry lacks a fresh selected-Wali seed.
                if current_view.observation is None or not current_view.observation.stable_selected_state:
                    status, reason = "blocked", "evolution_preview_not_bound_to_stable_wali_detail"
                    break
                before = current_view.observation
                if (
                    not before.recognized
                    or before.reset_guard_active
                    or before.overlay_state not in {"none", "none_observed"}
                ):
                    status, reason = "blocked", "evolution_reset_or_unknown_overlay_guard"
                    break
                if _is_shortage(before, evolution=True):
                    status, reason = "deferred", "standard_evolution_material_shortage"
                    break
                if not hero_evolution_authorizeable(before):
                    status, reason = "blocked", "evolution_preconditions_not_proven"
                    break
                result = _dispatch_consequential(
                    context, state, before_view=current_view, before_capture=current_capture,
                    phase="evolution", ordinal=confirmed_upgrades + 1,
                    game_day_id=game_day_id, prior_confirmed=confirmed_upgrades,
                    evolution_count=prior_evolutions + state.evolution_committed,
                )
                if result["status"] != "confirmed":
                    status, reason = str(result["status"]), str(result["reason"])
                    break
                current_view, current_capture = _stable_view(
                    context, state, label="wali-after-evolution",
                    game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
                    expected_page="hero_detail",
                )
                continue

            if current_view.page != "hero_detail" or current_view.observation is None:
                status, reason = "blocked", "selected_wali_detail_not_stably_recognized"
                break
            observation = current_view.observation
            if observation.hero_identity != HERO_IDENTITY or not observation.hero_selected:
                status, reason = "blocked", "selected_hero_is_not_wali"
                break
            if not observation.stable_selected_state:
                status, reason = "blocked", "selected_wali_state_not_settled"
                break
            if (
                not observation.recognized
                or observation.reset_guard_active
                or observation.overlay_state not in {"none", "none_observed"}
            ):
                status, reason = "blocked", "wali_reset_or_unknown_overlay_guard"
                break
            if observation.current_level is None or observation.evolution_cap is None or observation.current_level > observation.evolution_cap:
                status, reason = "blocked", "current_wali_level_or_cap_is_ambiguous"
                break
            if observation.current_level < observation.evolution_cap:
                if _is_shortage(observation, evolution=False):
                    status, reason = "deferred", "antiserum_shortage"
                    break
                if not hero_upgrade_authorizeable(observation):
                    status, reason = "blocked", "single_level_upgrade_preconditions_not_proven"
                    break
                result = _dispatch_consequential(
                    context, state, before_view=current_view, before_capture=current_capture,
                    phase="normal", ordinal=confirmed_upgrades + 1,
                    game_day_id=game_day_id, prior_confirmed=confirmed_upgrades,
                    evolution_count=prior_evolutions + state.evolution_committed,
                )
                if result["status"] != "confirmed":
                    status, reason = str(result["status"]), str(result["reason"])
                    break
                confirmed_upgrades += int(result["inputs"])
                current_view, current_capture = _stable_view(
                    context, state, label="wali-after-normal-batch",
                    game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
                    expected_page="hero_detail",
                )
                if int(result["inputs"]) < normal_upgrade_input_limit(observation):
                    # The next input was not admissible. Settle this prefix and
                    # leave its remaining quota for a later occurrence rather
                    # than re-opening the UI merely to evade the batch guard.
                    status, reason = "deferred", f"normal_batch_prefix:{result['stop_reason']}"
                    break
                continue

            if prior_evolutions + state.evolution_committed >= MAX_CONFIRMED_UPGRADES:
                status, reason = "deferred", "standard_evolution_quota_exhausted"
                break
            if observation.evolution_control_visible is not True or current_view.detail_evolve_target is None:
                status, reason = "blocked", "standard_evolution_control_not_uniquely_visible"
                break
            source_view, source_capture = current_view, current_capture
            roi = current_view.detail_evolve_target

            def open_evolution(source: Any, action_key: str, nav_target: str) -> None:
                context.runtime.tap(
                    source,
                    target_identity=nav_target,
                    target_roi=roi,
                    action_key=action_key,
                    action_class="navigation",
                    consequential=False,
                )

            def preview_expected(candidate: _View) -> bool:
                return bool(
                    candidate.page == "evolution_preview"
                    and candidate.observation is not None
                    and candidate.observation.hero_identity == HERO_IDENTITY
                    and candidate.observation.hero_selected
                )

            ok, next_view, next_capture, reason = _nav_action(
                context, state, home, label=f"open-evolution-preview-{observation.evolution_cap}",
                source_view=source_view, source_capture=source_capture,
                target_identity="navigate_to_hero", action=open_evolution,
                expected=preview_expected, game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades, seed=observation,
            )
            if not ok or next_view is None or next_capture is None:
                status = "blocked"
                break
            current_view, current_capture = _stable_view(
                context, state, label="wali-evolution-preview-stable",
                game_day_id=game_day_id, confirmed_upgrades=confirmed_upgrades,
                seed=observation, expected_page="evolution_preview",
            )
            if current_view.observation is None or not current_view.observation.stable_selected_state:
                status, reason = "blocked", "evolution_preview_state_not_settled"
                break
            if current_view.reason == "manual_identity_unproven":
                status, reason = "deferred", "manual_identity_source_proof_required"
                break
            if _is_shortage(current_view.observation, evolution=True):
                status, reason = "deferred", "standard_evolution_material_shortage"
                break
            if not hero_evolution_authorizeable(current_view.observation):
                status, reason = "blocked", "standard_evolution_costs_or_successor_cap_not_proven"
                break

        if status not in {"blocked", "deferred", "unknown"}:
            status = "completed" if confirmed_upgrades >= MAX_CONFIRMED_UPGRADES else "deferred"
            reason = "three_single_level_wali_upgrades_confirmed" if status == "completed" else "daily_wali_upgrade_quota_not_yet_complete"
        if status == "unknown":
            context.validate_identity()
            return _result(
                status=status, reason=reason, game_day_id=game_day_id,
                occurrence_key=context.occurrence_key, prior_confirmed=prior_confirmed,
                confirmed=confirmed_upgrades, state=state,
                input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
            )
        if current_view is not None and current_capture is not None and current_view.page != "home":
            home_ok, home_capture, home_reason = _return_home(
                context,
                state,
                home,
                view=current_view,
                captured=current_capture,
                game_day_id=game_day_id,
                confirmed_upgrades=confirmed_upgrades,
            )
            if not home_ok:
                status = "blocked"
                reason = f"{reason};home_return:{home_reason}"
        elif current_view is not None and current_view.page == "home" and current_capture is not None:
            if _home_verified(context, current_capture, home):
                state.terminal_home_verified = True
                state.terminal_home_frame = {
                    "frame_path": Path(current_capture.path).resolve().relative_to(Path(context.session.session_directory).resolve()).as_posix(),
                    "frame_sha256": str(current_capture.sha256),
                }
            else:
                status = "blocked"
                reason = f"{reason};terminal_home_not_clean_verified"
        if status == "completed" and (confirmed_upgrades < MAX_CONFIRMED_UPGRADES or not state.terminal_home_verified):
            status = "blocked"
        if not state.terminal_home_verified and status == "deferred":
            status = "blocked"
            reason = f"{reason};terminal_home_not_verified"
        context.validate_identity()
        if _identity_value(context, "reset_id") != game_day_id:
            status = "blocked"
            reason = f"{reason};reset_identity_changed"
    except Exception as exc:
        status = "blocked"
        reason = f"{type(exc).__name__}:{exc}"
        try:
            if game_day_id:
                context.validate_identity()
        except Exception:
            reason = f"{reason};identity_revalidation_failed"

    return _result(
        status=status,
        reason=reason,
        game_day_id=game_day_id,
        occurrence_key=getattr(context, "occurrence_key", None),
        prior_confirmed=prior_confirmed,
        confirmed=confirmed_upgrades,
        state=state,
        input_actions=max(0, int(context.session.input_count) - starting_session_inputs),
    )


def create_service_binding(make_native_route_binding):
    """Compose the fixed canonical driver without opening a device or store."""
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:wali-upgrade",
        workflow="wali-individual-single-upgrade-batches",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_wali_upgrade_service_route,
    )
