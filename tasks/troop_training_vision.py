"""Native 800x1280 OCR/visual adapter for the four troop-training screens.

The adapter only recognizes current frames and returns fresh, bounded targets.  It never dispatches
input and never treats a reference screenshot or transport result as semantic proof.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re
import unicodedata
from typing import Mapping

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .troop_training import (
    AutoUseResourcePopupObservation,
    FACILITY_BY_TYPE,
    RESOURCE_NAMES,
    TROOP_TYPES,
    DailyTrainingProgress,
    HomeObservation,
    RadialMenuObservation,
    ResourceReading,
    TierObservation,
    TrainingScreenObservation,
    daily_progress_from_text,
    parse_duration_seconds,
    parse_quantity,
)


PROFILE_SIZE = (800, 1280)
Box = tuple[int, int, int, int]
Target = tuple[str, Box]
RADIAL_TRAIN_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "troop_training" / "800x1280" / "radial-train-icon.png"
RADIAL_TRAIN_TEMPLATE_SHA256 = "3e733d4466f295edf9fc552a7462764cc4128a9efb572c4ba5f88846df8003cb"
RADIAL_TRAIN_MATCH_MINIMUM = 0.78
RADIAL_TRAIN_AMBIGUITY_MAXIMUM = 0.80

FACILITY_BY_NORMALIZED = {"fighter camp": "fighter", "shooter camp": "shooter", "rider camp": "rider", "vehicle depot": "vehicle"}
FACILITY_BY_COMPACT = {key.replace(" ", ""): value for key, value in FACILITY_BY_NORMALIZED.items()}
FACILITY_OCR_ALIASES = {
    "fighter": ("fighter", "fig"),
    "shooter": ("shooter",),
    "rider": ("rider",),
    "vehicle": ("vehicle", "ehicle"),
}
TAB_ROIS: Mapping[str, Box] = {
    "fighter": (180, 65, 300, 185),
    "shooter": (285, 65, 405, 185),
    "rider": (390, 65, 510, 185),
    "vehicle": (495, 65, 615, 185),
}
TIER_BAND: Box = (40, 790, 760, 990)
# Canonical native training cards occupy these bounded slots.  The slots are
# used only to recover small T-label OCR that ``image_to_data`` can miss; the
# tier identity still comes from text inside each current-frame slot, never
# from slot ordinal or swipe count.
TIER_CARD_SLOTS: tuple[Box, ...] = (
    (50, 835, 195, 955),
    (185, 835, 330, 955),
    (325, 835, 475, 955),
    (460, 835, 610, 955),
    (595, 835, 755, 955),
)
QUANTITY_BAND: Box = (500, 1010, 780, 1150)
TRAIN_BAND: Box = (80, 1120, 760, 1270)
# Native 800x1280 training screens render the active queue label and countdown
# immediately above the normal Train/Speedup control (roughly y=1050..1150).
# Keep this ROI spatially bound to that row; full-frame OCR is non-authorizing.
QUEUE_BAND: Box = (90, 1040, 710, 1160)
QUEUE_TIMER_BAND: Box = (180, 1095, 520, 1160)


def _normalized(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def _ocr(frame: np.ndarray, box: Box | None = None, *, psm: int = 11) -> str:
    image = frame if box is None else frame[box[1]:box[3], box[0]:box[2]]
    enlarged = cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return _normalized(pytesseract.image_to_string(enlarged, config=f"--psm {psm}"))


def _queue_timer_text(frame: np.ndarray) -> str | None:
    """Read a positive countdown only from the queue label's native timer row."""
    image = frame[QUEUE_TIMER_BAND[1]:QUEUE_TIMER_BAND[3], QUEUE_TIMER_BAND[0]:QUEUE_TIMER_BAND[2]]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    thresholded = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1]
    enlarged = cv2.resize(thresholded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    for psm in (6, 7, 11):
        raw = pytesseract.image_to_string(
            enlarged,
            config=f"--psm {psm} -c tessedit_char_whitelist=0123456789:",
        )
        match = re.search(r"(?<!\d)(?:\d{1,3}):\d{2}:\d{2}(?!\d)", raw)
        if match is None:
            continue
        candidate = match.group(0)
        duration = parse_duration_seconds(candidate)
        if duration is not None and duration > 0:
            return candidate
    return None


def _tier_slot_text(frame: np.ndarray, slot: Box) -> str:
    """Read one tier card's own label with bounded native variants.

    The carousel labels are outlined gold/white text over artwork.  The
    default grayscale OCR can lose the leading ``T`` (or the whole label) on
    the low-contrast leftmost card.  Retry only within that same card using
    color channels and a small y expansion; this keeps tier identity tied to
    the current card rather than its ordinal position or swipe history.
    """

    initial = " ".join((_ocr(frame, slot, psm=6), _ocr(frame, slot, psm=11)))
    # Do not accept an isolated OCR digit embedded in card artwork (for
    # example ``2) gare`` on the T1 card).  An explicit T token is preferred;
    # a pure numeric label remains compatible with stylized ``18`` -> T8
    # fixtures.
    explicit = re.search(r"(?:^|[^0-9])t\s*(1[0-3]|[1-9])(?=\D|$)", initial)
    pure_numeric = re.fullmatch(r"1[0-3]|[1-9]", initial.strip())
    if explicit is not None or pure_numeric is not None:
        return initial
    recovered: list[str] = [initial]
    # Read the lower label strip first.  On a camera-shifted carousel the
    # first card can be offset substantially, but its own T-label remains in
    # this card-local lower band (and is not recoverable from the slot's
    # ordinal).
    center = (slot[0] + slot[2]) // 2
    bands = (
        (slot[0], max(0, slot[1] + 45), slot[2], min(1280, slot[3] + 15)),
        # A centered sub-band avoids neighboring card artwork after a
        # carousel translation while retaining the card-local T-label.
        (max(0, center - 45), max(0, slot[1] + 45), min(800, center + 45), min(1280, slot[3] + 15)),
        (slot[0], max(0, slot[1] + 60), slot[2], slot[3]),
        (_expanded(slot, x_pad=0, y_pad=15)),
    )
    for bounded in bands:
        crop = frame[bounded[1]:bounded[3], bounded[0]:bounded[2]]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Blue/gray retain the bright outlined card labels on the native Rider
        # frame while remaining bounded to this card's ROI.
        variants = (
            (gray, (11, 6)),
            (crop[:, :, 0], (11, 6)),
            (crop[:, :, 2], (11, 6)),
            # Gold/white outlined numerals separate more reliably after a
            # bounded threshold on the native card label band.
            (cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1], (11, 6)),
            (cv2.threshold(crop[:, :, 0], 160, 255, cv2.THRESH_BINARY)[1], (11, 6)),
            (cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)[1], (11,)),
            (cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)[1], (11,)),
            (cv2.threshold(crop[:, :, 0], 80, 255, cv2.THRESH_BINARY)[1], (11,)),
            (cv2.threshold(crop[:, :, 0], 120, 255, cv2.THRESH_BINARY)[1], (11,)),
        )
        for variant, psms in variants:
            enlarged = cv2.resize(variant, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            for psm in psms:
                text = _normalized(pytesseract.image_to_string(enlarged, config=f"--psm {psm}"))
                if text:
                    explicit = re.search(r"(?:^|[^0-9])t\s*(1[0-3]|[1-9])(?=\D|$)", text)
                    pure_numeric = re.fullmatch(r"1[0-3]|[1-9]", text.strip())
                    parsed = int(explicit.group(1)) if explicit is not None else (int(pure_numeric.group(0)) if pure_numeric else None)
                    # Supplemental variants are only needed for the
                    # low-contrast T1 label.  Do not let broad artwork OCR
                    # invent another tier (e.g. T3 on a T6 card).
                    if parsed == 1:
                        recovered.append(text)
                        return " ".join(recovered)
    return " ".join(recovered)


def _ocr_boxes(frame: np.ndarray, box: Box | None = None) -> list[tuple[str, Box]]:
    origin_x, origin_y = (0, 0) if box is None else (box[0], box[1])
    image = frame if box is None else frame[box[1]:box[3], box[0]:box[2]]
    enlarged = cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box]] = []
    for index, raw in enumerate(data["text"]):
        text = _normalized(raw)
        if not text:
            continue
        x = origin_x + int(data["left"][index]) // 3
        y = origin_y + int(data["top"][index]) // 3
        width = max(1, int(data["width"][index]) // 3)
        height = max(1, int(data["height"][index]) // 3)
        found.append((text, (max(0, x), max(0, y), min(800, x + width), min(1280, y + height))))
    return found


def _ocr_variant_boxes(frame: np.ndarray, box: Box, *, psm: int = 6) -> list[tuple[str, Box]]:
    """Read a small current-frame label band with stable grayscale variants."""
    origin_x, origin_y = box[0], box[1]
    image = frame[box[1]:box[3], box[0]:box[2]]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = (
        image,
        gray,
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
    )
    found: list[tuple[str, Box]] = []
    for variant in variants:
        enlarged = cv2.resize(variant, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        data = pytesseract.image_to_data(enlarged, config=f"--psm {psm}", output_type=Output.DICT)
        for index, raw in enumerate(data["text"]):
            text = _normalized(raw)
            if not text:
                continue
            x = origin_x + int(data["left"][index]) // 4
            y = origin_y + int(data["top"][index]) // 4
            width = max(1, int(data["width"][index]) // 4)
            height = max(1, int(data["height"][index]) // 4)
            found.append((text, (max(0, x), max(0, y), min(800, x + width), min(1280, y + height))))
    return found


def _expanded(box: Box, *, x_pad: int, y_pad: int) -> Box:
    return (max(0, box[0] - x_pad), max(0, box[1] - y_pad), min(800, box[2] + x_pad), min(1280, box[3] + y_pad))


def _colored_button_target(frame: np.ndarray, box: Box, *, hue_low: int, hue_high: int) -> Box | None:
    """Bind a large current-frame colored button without relying on button-text OCR."""

    crop = frame[box[1]:box[3], box[0]:box[2]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([hue_low, 60, 40]), np.array([hue_high, 255, 255]))
    components, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates = [stat for stat in stats[1:] if stat[4] >= 1000 and stat[2] >= 120 and stat[3] >= 35]
    if not candidates:
        return None
    x, y, width, height, _ = max(candidates, key=lambda stat: int(stat[4]))
    return _expanded((box[0] + int(x), box[1] + int(y), box[0] + int(x + width), box[1] + int(y + height)), x_pad=20, y_pad=15)


def _digest(frame: np.ndarray) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def _find_label_box(boxes: list[tuple[str, Box]], needle: str) -> Box | None:
    normalized = _normalized(needle)
    direct = next((box for text, box in boxes if normalized in text or text in normalized), None)
    if direct is not None:
        return direct
    words = normalized.split()
    for index, (text, box) in enumerate(boxes):
        if words and words[0] in text:
            nearby = [candidate for candidate_text, candidate in boxes[index + 1:index + 4] if abs(candidate[1] - box[1]) < 80]
            if nearby:
                return (box[0], box[1], max(box[2], nearby[0][2]), max(box[3], nearby[0][3]))
            return box
    return None


def _number_value(raw: str) -> int | None:
    text = raw.replace(",", "").replace(" ", "").upper()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMB]?)", text)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def _parse_resource_cell(frame: np.ndarray, box: Box, name: str) -> ResourceReading:
    text = _ocr(frame, box, psm=7)
    values = re.findall(r"[0-9]+(?:[.,][0-9]+)?\s*[KMB]?", text.upper())
    held = _number_value(values[0]) if values else None
    required = _number_value(values[1]) if len(values) > 1 else None
    return ResourceReading(name, held, required, "base")


def _selected_tier(frame: np.ndarray, full_text: str) -> int | None:
    # The highlighted troop header is separate from the horizontal card band;
    # read its tighter native ROI first so a neighboring T6/T7/T9 label cannot
    # be mistaken for the selected tier.
    for box in ((30, 745, 300, 825), (35, 730, 320, 820), (35, 720, 320, 860)):
        for psm in (7, 6, 11):
            prominent = _ocr(frame, box, psm=psm)
            match = re.search(r"\bt\s*(1[0-3]|[1-9])\b", prominent)
            if match:
                return int(match.group(1))
    matches = re.findall(r"\bt\s*(1[0-3]|[1-9])\b", full_text)
    return int(matches[0]) if matches else None


def _bounded_tier_label(text: str) -> int | None:
    """Parse a tier numeral from one current card's bounded OCR text.

    Stylized card labels are often read as ``17``/``18`` rather than ``T7``/
    ``T8`` because the leading T resembles ``1``.  Accept that narrowly
    bounded OCR artifact while rejecting arbitrary frame numbers.
    """

    direct = re.search(r"\bt\s*(1[0-3]|[1-9])\b", text)
    if direct is not None:
        return int(direct.group(1))
    # Card-local OCR may glue a preceding artwork character to the stylized
    # T (for example ``aT3``).  The bounded slot already proves spatial
    # association, so accept the suffix while still requiring a complete
    # 1..13 tier token.
    glued = re.search(r"t\s*(1[0-3]|[1-9])(?=\D|$)", text)
    if glued is not None:
        return int(glued.group(1))
    malformed = re.search(r"(?<!\d)1(1[0-3]|[1-9])(?:\D|$)", text)
    if malformed is not None:
        return int(malformed.group(1))
    # On the dark unlocked T7 card Tesseract can drop the stylized T and
    # leave only a repeated standalone ``7``.  Accept it only when every
    # bounded numeric token agrees, avoiding arbitrary card-art numbers.
    numerals = re.findall(r"(?<!\d)(1[0-3]|[1-9])(?!\d)", text)
    if numerals and len(set(numerals)) == 1:
        return int(numerals[0])
    return None


def _tier_observations(frame: np.ndarray, full_text: str, selected: int | None) -> tuple[TierObservation, ...]:
    observations: dict[int, TierObservation] = {}
    for raw_text, box in _ocr_boxes(frame, TIER_BAND):
        match = re.fullmatch(r"t\s*(1[0-3]|[1-9])", raw_text)
        if not match:
            continue
        tier = int(match.group(1))
        card = _expanded(box, x_pad=45, y_pad=45)
        card_text = _ocr(frame, card, psm=6)
        card_crop = frame[card[1]:card[3], card[0]:card[2]]
        card_hsv = cv2.cvtColor(card_crop, cv2.COLOR_BGR2HSV) if card_crop.size else None
        # Locked/question-mark cards are rendered as dark, desaturated tiles in
        # the native carousel even when OCR misses the question glyph.  This
        # visual marker is advisory only and is combined with the exact card
        # label; it never infers a tier from position.
        locked_visual = bool(
            card_hsv is not None
            and float(card_hsv[:, :, 1].mean()) < 25.0
            and float(card_hsv[:, :, 2].mean()) < 55.0
            and (selected is None or tier > selected)
        )
        locked_marker = "?" in card_text or "locked" in card_text or "requires" in card_text or locked_visual
        is_selected = tier == selected
        unlocked = is_selected and "train" in _ocr(frame, TRAIN_BAND, psm=6) and "required" not in full_text and not locked_marker
        if not is_selected and not locked_marker:
            # The icon/card itself is a positive non-question-mark state; no tier number is
            # inferred from position.  It is still revalidated after selection.
            unlocked = True
        observations[tier] = TierObservation(
            tier=tier,
            visible=True,
            unlocked=unlocked,
            selected=is_selected,
            question_mark="?" in card_text,
            lock_reason=card_text if locked_marker else "",
            target_roi=card,
        )
    # Recover labels that image_to_data misses on the low-contrast unlocked
    # cards (notably T6/T7 in the Rider screen).  Each candidate is parsed from
    # its own bounded native slot; no tier is inferred from position.
    for slot in TIER_CARD_SLOTS:
        slot_text = _tier_slot_text(frame, slot)
        tier = _bounded_tier_label(slot_text)
        if tier is None or tier in observations:
            continue
        card = _expanded(slot, x_pad=0, y_pad=0)
        card_text = _ocr(frame, card, psm=6)
        card_crop = frame[card[1]:card[3], card[0]:card[2]]
        card_hsv = cv2.cvtColor(card_crop, cv2.COLOR_BGR2HSV) if card_crop.size else None
        locked_visual = bool(
            card_hsv is not None
            and float(card_hsv[:, :, 1].mean()) < 25.0
            and float(card_hsv[:, :, 2].mean()) < 55.0
            and (selected is None or tier > selected)
        )
        locked_marker = "?" in card_text or "locked" in card_text or "requires" in card_text or locked_visual
        observations[tier] = TierObservation(
            tier=tier,
            visible=True,
            unlocked=not locked_marker,
            selected=tier == selected,
            question_mark="?" in card_text,
            lock_reason=card_text if locked_marker else "",
            target_roi=card,
        )
    if selected is not None and selected not in observations:
        # The selected card's numeric label is frequently lost in native OCR because it is
        # ring-highlighted.  Its identity is already positively bound by the prominent T-number
        # and the unlocked normal Train control, so bind the current card ROI for revalidation.
        card_centers = {1: 125, 2: 125, 3: 260, 4: 125, 5: 260, 6: 125, 7: 260, 8: 400, 9: 530, 10: 665, 11: 665, 12: 530, 13: 400}
        center = card_centers.get(selected, 400)
        train_text = _ocr(frame, TRAIN_BAND, psm=6)
        observations[selected] = TierObservation(
            tier=selected,
            visible=True,
            unlocked="train" in train_text and "required" not in full_text,
            selected=True,
            target_roi=(max(0, center - 65), 825, min(800, center + 65), 975),
        )
    return tuple(observations[tier] for tier in sorted(observations))


def _training_title(full_text: str) -> tuple[str | None, str | None]:
    for facility, troop_type in FACILITY_BY_NORMALIZED.items():
        if facility in full_text:
            return troop_type, FACILITY_BY_TYPE[troop_type]
    compact = full_text.replace(" ", "")
    for facility, troop_type in FACILITY_BY_COMPACT.items():
        if facility in compact:
            return troop_type, FACILITY_BY_TYPE[troop_type]
    return None, None


def recognize_home(frame: np.ndarray, *, reset_identity: str | None = None) -> HomeObservation:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Home frame must be a native 800x1280 image")
    digest = _digest(frame)
    full_text = _ocr(frame)
    boxes = _ocr_boxes(frame)
    # Facility labels are small, perspective-rendered text.  Full-frame OCR
    # can intermittently drop Fighter/Rider while the same fresh pixels are
    # readable in their bounded label bands.  Keep those extra observations
    # frame-local and use them only to establish the facility identity/target.
    boxes += _ocr_boxes(frame, (80, 700, 380, 800))
    boxes += _ocr_boxes(frame, (520, 710, 690, 830))
    for label_roi in ((80, 680, 380, 810), (350, 620, 540, 710), (500, 700, 710, 830), (340, 820, 500, 900)):
        boxes += _ocr_variant_boxes(frame, label_roi)
    # This recovery frame is a fully zoomed Home layout whose facility labels
    # sit above the older broad OCR bands.  Keep each read spatially bounded to
    # the expected building-label neighborhood; these are identity evidence,
    # not free-form full-frame text.
    for label_roi in (
        (260, 470, 470, 560),   # Fighter Camp
        (450, 365, 640, 440),   # Shooter Camp
        (620, 440, 800, 530),   # Rider Camp
        (430, 520, 650, 640),   # Vehicle Depot
    ):
        boxes += _ocr_variant_boxes(frame, label_roi)
    home_hud_band = (0, 0, 800, 70)
    home_hud_text = " ".join(
        (_ocr(frame, home_hud_band, psm=6), _ocr(frame, home_hud_band, psm=11))
    )
    home_hud_values = re.findall(r"\b\d+(?:\.\d+)?\s*[kmb]\b", home_hud_text)
    home_hud_signal = len(home_hud_values) >= 3 and "+" in home_hud_text
    headquarters_band = " ".join(
        (
            _ocr(frame, (350, 480, 560, 570), psm=6),
            _ocr(frame, (350, 480, 560, 570), psm=11),
            # The base can be panned far enough left that the Headquarters label moves outside
            # the legacy narrow band. This broader current-frame band remains bounded above all
            # four troop facilities and positively reads the full identity at night.
            _ocr(frame, (250, 400, 520, 550), psm=11),
        )
    )
    facilities: dict[str, Box] = {}
    label_y_hint = {"fighter": 775, "shooter": 675, "rider": 765, "vehicle": 865}
    for troop_type in TROOP_TYPES:
        candidates = [
            (box, abs(box[1] - label_y_hint[troop_type]))
            for text, box in boxes
            if any(alias in text for alias in FACILITY_OCR_ALIASES[troop_type]) and 350 <= box[1] <= 950
        ]
        label_box = min(candidates, key=lambda item: item[1])[0] if candidates else None
        if label_box is None and troop_type == "fighter":
            # Fighter Camp's label is rendered close to the left edge and full-frame OCR can
            # drop the entire word while the bounded current-frame label remains exact.  This
            # fallback is identity-only: it still requires the fresh native pixels to read the
            # complete facility name before binding the adjacent building body.
            fighter_label_band = (20, 720, 190, 790)
            fighter_label_text = " ".join(
                _ocr(frame, fighter_label_band, psm=psm) for psm in (6, 7, 12)
            )
            if "fighter camp" in fighter_label_text:
                label_box = fighter_label_band
        if label_box is None and troop_type == "rider":
            # On a retained Home frame the right-side Rider Camp label can be
            # partially occluded, and OCR may return ``ridengay``/``ridenca``.
            # Accept only that bounded label neighborhood; a free-form
            # full-frame ``rid`` token is not facility evidence.
            rider_label_band = (620, 440, 800, 530)
            rider_candidates = [
                box
                for text, box in boxes
                if 440 <= box[1] <= 530 and (text.startswith("rider") or text.startswith("rid"))
            ]
            if rider_candidates:
                label_box = min(rider_candidates, key=lambda box: abs(box[1] - 490))
        if label_box is not None:
            if troop_type == "fighter":
                # OCR commonly clips the leftmost F in the live label.  Bind the current
                # label and shift the action ROI upward/right onto the building body.
                facilities[troop_type] = (
                    max(0, label_box[0] - 100),
                    max(0, label_box[1] - 170),
                    min(800, label_box[2] + 100),
                    min(1280, label_box[3] + 30),
                )
            elif troop_type == "shooter":
                # Shooter Camp's label sits below the roof; keep the target centered on the
                # current building body rather than the text baseline.
                facilities[troop_type] = (
                    max(0, label_box[0] - 60),
                    max(0, label_box[1] - 125),
                    min(800, label_box[2] + 60),
                    min(1280, label_box[3] + 10),
                )
            elif troop_type == "rider":
                facilities[troop_type] = (
                    max(0, label_box[0] - 60),
                    max(0, label_box[1] - 100),
                    min(800, label_box[2] + 60),
                    min(1280, label_box[3] + 10),
                )
            elif troop_type == "vehicle":
                facilities[troop_type] = (
                    max(0, label_box[0] - 80),
                    max(0, label_box[1] - 100),
                    min(800, label_box[2] + 80),
                    min(1280, label_box[3] + 10),
                )
            else:
                facilities[troop_type] = _expanded(label_box, x_pad=100, y_pad=165)
    recognized = (
        ("headquarters" in full_text
        or "headquarter" in full_text
        or "headquarter" in headquarters_band
        or home_hud_signal)
        and len(facilities) == len(TROOP_TYPES)
    )
    ready_text = "training completed" in full_text or "ready to claim" in full_text
    completed_ready = {troop_type: bool(ready_text and troop_type in full_text) for troop_type in TROOP_TYPES}
    return HomeObservation(
        recognized=recognized,
        facilities=facilities,
        completed_ready=completed_ready,
        completed_batch_ids={troop_type: f"{troop_type}:{digest}" for troop_type, ready in completed_ready.items() if ready},
        overlay_state="unknown" if any(word in full_text for word in ("loading", "confirm", "purchase")) else "none",
        reset_identity=reset_identity,
        frame_sha256=digest,
        diagnostics={
            "full_text": full_text,
            "headquarters_band": headquarters_band,
            "home_hud_band": home_hud_band,
            "home_hud_text": home_hud_text,
            "home_hud_values": home_hud_values,
            # Keep the bounded resource-HUD predicate available to recovery.
            # Facility OCR is intentionally not folded into this signal: a
            # camera pan may clip one or more labels while the native Home HUD
            # remains fully visible.
            "home_hud_signal": home_hud_signal,
            "ocr_boxes": boxes,
        },
    )


def forbidden_atlas_entry_surface(frame: np.ndarray) -> str | None:
    """Reject consequential or modal surfaces before Home-atlas localization.

    This is deliberately a semantic negative gate, not a Home recognizer.  The
    atlas localizer remains the positive Home authority and therefore does not
    inherit the legacy requirement that all four troop facilities be visible.
    """

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        return "non_native_frame"
    text = _ocr(frame)
    phrases = (
        ("train now", "unexpected_training_surface"),
        ("auto use", "unexpected_resource_box_surface"),
        ("resource boxes", "unexpected_resource_box_surface"),
        ("daily free attempts", "unexpected_resource_surface"),
        ("premium", "unexpected_premium_surface"),
        ("purchase", "unexpected_purchase_surface"),
    )
    for phrase, reason in phrases:
        if phrase in text:
            return reason
    if "quantity" in text and ("train now" in text or "select tier" in text):
        return "unexpected_quantity_surface"
    if "warehouse" in text and ("confirm" in text or "use resources" in text or "insufficient" in text):
        return "unexpected_warehouse_surface"
    if "confirm" in text and "cancel" in text:
        return "unexpected_confirmation_overlay"
    return None


def recognize_exit_dialog(frame: np.ndarray) -> tuple[bool, Box | None]:
    """Recognize the in-game exit modal and bind only its Cancel control."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("exit-dialog frame must be a native 800x1280 image")
    modal_text = _ocr(frame, (40, 380, 760, 800), psm=6)
    cancel_text = _ocr(frame, (60, 650, 380, 780), psm=7)
    confirm_text = _ocr(frame, (400, 650, 740, 780), psm=7)
    recognized = "exit" in modal_text and "game" in modal_text and "cancel" in cancel_text and "confirm" in confirm_text
    return recognized, (60, 650, 380, 780) if recognized else None


def recognize_training_speedup(frame: np.ndarray) -> bool:
    """Recognize only Training Speedup; this authorizes Back, never Use."""

    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        return False
    title = " ".join((_ocr(frame, (150, 0, 650, 85), psm=6), _ocr(frame, (150, 0, 650, 85), psm=11)))
    return "training speedup" in title


def recognize_auto_use_resource_popup(frame: np.ndarray) -> AutoUseResourcePopupObservation:
    """Recognize forbidden Auto Use resource boxes and bind Cancel separately from Confirm."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Auto Use popup frame must be a native 800x1280 image")
    digest = _digest(frame)
    title = _ocr(frame, (250, 150, 550, 230), psm=7)
    body = _ocr(frame, (50, 220, 750, 340), psm=6)
    summary = _ocr(frame, (40, 740, 760, 1130), psm=6)
    button_boxes = _ocr_variant_boxes(frame, (70, 930, 730, 1080))
    cancel_box = next((box for label, box in button_boxes if label == "cancel"), None)
    confirm_box = next((box for label, box in button_boxes if label == "confirm"), None)
    resource_boxes = "auto-use resource boxes" in summary
    resource_pairs = re.findall(
        r"([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)\s*/\s*([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)",
        summary.upper(),
    )
    resources_after_use = tuple(
        ResourceReading(name, _number_value(held), _number_value(required), "inventory_resource_box")
        for name, (held, required) in zip(RESOURCE_NAMES, resource_pairs[: len(RESOURCE_NAMES)])
    )
    recognized = bool(
        "auto use" in title
        and "sufficient resources after use" in body
        and "auto use (total)" in summary
        and "resources held (total)" in summary
        and resource_boxes
        and len(resources_after_use) == len(RESOURCE_NAMES)
        and cancel_box is not None
        and confirm_box is not None
    )
    return AutoUseResourcePopupObservation(
        recognized=recognized,
        resource_boxes_selected=recognized and resource_boxes,
        warehouse_only=False,
        cancel_target=_expanded(cancel_box, x_pad=70, y_pad=35) if recognized and cancel_box is not None else None,
        confirm_target=_expanded(confirm_box, x_pad=70, y_pad=35) if recognized and confirm_box is not None else None,
        resources_after_use=resources_after_use if recognized else (),
        frame_sha256=digest,
        diagnostics={"title": title, "body": body, "summary": summary, "button_boxes": button_boxes},
    )


def _radial_train_sector(facility_target: Box) -> Box | None:
    """Return the tight Train sector relative to the freshly tapped facility."""

    x0, y0, x1, y1 = (int(value) for value in facility_target)
    if not (0 <= x0 < x1 <= PROFILE_SIZE[0] and 0 <= y0 < y1 <= PROFILE_SIZE[1]):
        return None
    center_x = (x0 + x1) // 2
    center_y = (y0 + y1) // 2
    sector = (
        max(0, center_x + 50),
        max(0, center_y),
        min(PROFILE_SIZE[0], center_x + 205),
        min(PROFILE_SIZE[1], center_y + 165),
    )
    return sector if sector[2] - sector[0] >= 80 and sector[3] - sector[1] >= 80 else None


def _radial_train_target(frame: np.ndarray, sector: Box) -> Box | None:
    """Match the retained native Train icon template inside one bounded sector."""

    try:
        encoded = RADIAL_TRAIN_TEMPLATE_PATH.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(encoded).hexdigest() != RADIAL_TRAIN_TEMPLATE_SHA256:
        return None
    template = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    search = frame[sector[1]:sector[3], sector[0]:sector[2]]
    if template is None or search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return None
    response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(response)
    if score < RADIAL_TRAIN_MATCH_MINIMUM:
        return None
    suppressed = response.copy()
    tx, ty = location
    height, width = template.shape[:2]
    suppressed[
        max(0, ty - height // 2):min(suppressed.shape[0], ty + height // 2 + 1),
        max(0, tx - width // 2):min(suppressed.shape[1], tx + width // 2 + 1),
    ] = -1.0
    if suppressed.size and cv2.minMaxLoc(suppressed)[1] >= RADIAL_TRAIN_AMBIGUITY_MAXIMUM:
        return None
    x0, y0 = sector[0] + tx, sector[1] + ty
    return (x0, y0, x0 + width, y0 + height)


def recognize_radial_menu(
    frame: np.ndarray,
    *,
    troop_type: str | None = None,
    facility_target: Box | None = None,
) -> RadialMenuObservation:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("radial-menu frame must be a native 800x1280 image")
    digest = _digest(frame)
    text = _ocr(frame)
    detected_type, facility = _training_title(text)
    if troop_type is not None:
        # Several other facility labels remain visible behind the radial.  The
        # menu itself has no facility title, so identity comes only from the
        # exact current-frame facility binding that the caller just tapped.
        detected_type, facility = troop_type, FACILITY_BY_TYPE[troop_type]
    if facility_target is not None:
        train_sector = _radial_train_sector(facility_target)
        train_target = _radial_train_target(frame, train_sector) if train_sector is not None else None
        radial = train_target is not None and facility is not None
    else:
        # Recovery has no retained facility binding, so search the bounded
        # center scene for the same exact template. It can only authorize a
        # radial close; canonical Train entry uses the tighter sector above.
        train_target = _radial_train_target(frame, (200, 250, 650, 650))
        radial = train_target is not None and facility is not None
    return RadialMenuObservation(
        recognized=radial,
        facility_identity=facility or "",
        train_target=train_target,
        completed_banner=next((line for line in ("fighter", "shooter", "rider", "vehicle") if "training completed" in text and line in text), ""),
        overlay_state="unknown" if "confirm" in text else "none",
        frame_sha256=digest,
    )


def recognize_training(frame: np.ndarray) -> TrainingScreenObservation:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("training frame must be a native 800x1280 image")
    digest = _digest(frame)
    full_text = _ocr(frame)
    title_band = " ".join((_ocr(frame, (180, 0, 620, 75), psm=6), _ocr(frame, (180, 0, 620, 75), psm=11)))
    title_context = f"{full_text} {title_band}"
    master_band = " ".join((_ocr(frame, (600, 250, 790, 420), psm=6), _ocr(frame, (600, 250, 790, 420), psm=11)))
    troop_type, facility = _training_title(title_context)
    bottom_text = _ocr(frame, TRAIN_BAND, psm=6)
    queue_text = " ".join((_ocr(frame, QUEUE_BAND, psm=6), _ocr(frame, QUEUE_BAND, psm=11)))
    quantity_text = _ocr(frame, QUANTITY_BAND, psm=7)
    quantity_values = re.findall(r"[0-9][0-9,]*", quantity_text)
    selected_quantity = parse_quantity(quantity_values[0]) if quantity_values else None
    quantity_maximum = parse_quantity(quantity_values[1]) if len(quantity_values) > 1 else None
    selected = _selected_tier(frame, full_text)
    tiers = _tier_observations(frame, full_text, selected)
    resource_row = _ocr(frame, (35, 940, 780, 1040), psm=6)
    resource_pairs = re.findall(
        r"([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)\s*/\s*([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)",
        resource_row.upper(),
    )
    # An insufficient food holding is rendered red beside a green requirement. Grayscale OCR can
    # erase the red number while reading the other three resources correctly; saturation retains
    # both values in the bounded food cell.
    food_cell = frame[950:1045, 35:230]
    food_saturation = cv2.cvtColor(food_cell, cv2.COLOR_BGR2HSV)[:, :, 1]
    food_text = _normalized(
        pytesseract.image_to_string(
            cv2.resize(food_saturation, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
            config="--psm 7",
        )
    )
    food_pair = re.search(
        r"([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)\s*/\s*([0-9][0-9,.]*(?:\.[0-9]+)?\s*[KMB]?)",
        food_text.upper(),
    )
    if food_pair is not None and len(resource_pairs) == len(RESOURCE_NAMES) - 1:
        resource_pairs.insert(0, food_pair.groups())
    resources = tuple(
        ResourceReading(name, _number_value(held), _number_value(required), "base")
        for name, (held, required) in zip(RESOURCE_NAMES, resource_pairs[: len(RESOURCE_NAMES)])
    )
    normal_button_box = (400, 1120, 760, 1270)
    normal_button_text_box = (430, 1135, 700, 1270)
    normal_button_text = " ".join((_ocr(frame, normal_button_text_box, psm=6), _ocr(frame, normal_button_text_box, psm=11)))
    normal_color_target = _colored_button_target(frame, normal_button_box, hue_low=0, hue_high=20)
    train_now_color_target = _colored_button_target(frame, (80, 1120, 400, 1270), hue_low=8, hue_high=40)
    boxes = _ocr_boxes(frame, TRAIN_BAND)
    normal_box = next((box for label, box in boxes if label == "train" and box[0] > 400), None)
    train_now_box = next((box for label, box in boxes if label == "train" and box[0] <= 400), None)
    normal_box = normal_color_target or normal_box
    train_now_box = train_now_color_target or train_now_box
    # An active queue renders its label and countdown above the normal control band.  The
    # bottom-band OCR therefore often misses the timer even though the full native frame contains
    # the positive queue successor (for example: `Train T8 Veteran x250 02:55:32`).
    queue_match = re.search(
        r"\btrain\s+t\s*(1[0-3]|[1-9])\b.*?\bx\s*([0-9][0-9,]*)",
        queue_text,
    )
    queue_quantity = parse_quantity(queue_match.group(2)) if queue_match else None
    duration_match = None
    duration = None
    duration_source = "none"
    duration_ocr_source = "none"
    queue_timer_text = None
    if queue_match is not None:
        duration_match = re.search(r"(?:\d+d)?(?:\d{1,3}:)?\d{1,3}:\d{2}:\d{2}", queue_text)
        duration = parse_duration_seconds(duration_match.group(0)) if duration_match else None
        if duration is not None and duration > 0:
            duration_source = "queue_band"
            duration_ocr_source = "queue_band"
        else:
            queue_timer_text = _queue_timer_text(frame)
            fallback_duration = parse_duration_seconds(queue_timer_text) if queue_timer_text is not None else None
            if fallback_duration is not None and fallback_duration > 0:
                duration = fallback_duration
                duration_source = "queue_band"
                duration_ocr_source = "queue_timer_band"
            else:
                duration = None
    else:
        duration_match = re.search(r"(?:\d+d)?(?:\d{1,3}:)?\d{1,3}:\d{2}:\d{2}", normal_button_text)
        duration = parse_duration_seconds(duration_match.group(0)) if duration_match else None
        if duration is not None and duration > 0:
            duration_source = "normal_train_band"
            duration_ocr_source = "normal_train_band"
    if queue_quantity is not None:
        # Quantity OCR in the hidden/disabled editor is not a reliable queue value.  The live
        # queue label is the exact semantic successor and is bound to the selected troop type.
        selected_quantity = queue_quantity
    completion_banner = "training completed" in full_text
    popup = "popup" in full_text or "shortage" in full_text or "warehouse resources" in full_text
    warehouse = "warehouse" in full_text and ("use" in full_text or "resource" in full_text)
    confirm_box = next((box for label, box in boxes if label in {"confirm", "ok", "yes"}), None)
    forbidden = tuple(
        item
        for item, words in {
            "purchase": ("purchase", "buy", "mall"),
            "speedup": ("speed up", "speedup"),
            "resource_item": ("resource pack", "item"),
            "ticket": ("ticket",),
            "premium": ("diamond", "premium currency"),
        }.items()
        if popup and any(word in full_text for word in words)
    )
    master_trainer_signal = (
        "master" in full_text
        or "master" in master_band
        or ("mast" in master_band and ("train" in master_band or "rainer" in master_band))
        or ("mas" in full_text and "reduce training time" in full_text)
        or "reduce training time" in full_text
        # The Master Trainer artwork/label can be occluded briefly after quantity editing. A
        # current title, selected tier, normal timed-control color, and parsed duration still
        # provide a positive bounded training-screen successor without authorizing any premium UI.
        or (normal_color_target is not None and duration is not None and not queue_match)
    )
    if normal_color_target is not None and not queue_match:
        tiers = tuple(
            replace(tier, unlocked=True)
            if tier.selected and not tier.question_mark
            else tier
            for tier in tiers
        )
    normal_target = normal_box if normal_color_target is not None else (_expanded(normal_box, x_pad=95, y_pad=55) if normal_box is not None else None)
    train_now_target = train_now_box if train_now_color_target is not None else (_expanded(train_now_box, x_pad=95, y_pad=55) if train_now_box is not None else None)
    queue_active = bool(
        not completion_banner
        and duration is not None
        and duration > 0
        and queue_match is not None
    )
    active_queue_companion = bool(
        queue_active
        and troop_type
        and facility
        and selected is not None
        and any(tier.selected and tier.tier == selected for tier in tiers)
    )
    recognized = bool(
        troop_type
        and facility
        and selected is not None
        # The live Master Trainer label is sometimes OCR'd as the clipped
        # `mas ... rainery`; require the companion training-time label too so
        # this remains a positive screen-recognition signal.
        and (master_trainer_signal or active_queue_companion)
    )
    return TrainingScreenObservation(
        recognized=recognized,
        troop_type=troop_type,
        facility_identity=facility,
        selected_tier=selected,
        visible_tiers=tiers,
        selected_quantity=selected_quantity,
        quantity_maximum=quantity_maximum,
        resources=resources,
        normal_train_target=normal_target,
        train_now_target=train_now_target,
        training_duration_seconds=duration,
        queue_active=queue_active,
        queue_label=queue_match.group(0) if queue_match is not None else None,
        queue_troop_type=troop_type if queue_match is not None else None,
        queue_tier=int(queue_match.group(1)) if queue_match is not None else None,
        queue_quantity=queue_quantity,
        completion_ready=completion_banner,
        completion_batch_id=f"{troop_type}:{digest}" if completion_banner and troop_type else None,
        completion_banner=full_text if completion_banner else "",
        warehouse_popup=warehouse,
        warehouse_confirm_target=_expanded(confirm_box, x_pad=95, y_pad=55) if warehouse and confirm_box is not None else None,
        resource_shortage=tuple(name for name in RESOURCE_NAMES if name in full_text and "insufficient" in full_text),
        premium_popup=popup and "diamond" in full_text,
        forbidden_controls=forbidden,
        overlay_state="unknown" if "loading" in full_text else "popup" if popup else "none",
        frame_sha256=digest,
        diagnostics={"full_text": full_text, "title_band": title_band, "master_band": master_band, "bottom_text": bottom_text, "queue_band": QUEUE_BAND, "queue_timer_band": QUEUE_TIMER_BAND, "queue_text": queue_text, "queue_timer_text": queue_timer_text, "normal_button_text": normal_button_text, "duration_source": duration_source, "duration_ocr_source": duration_ocr_source, "quantity_text": quantity_text, "ocr_boxes": boxes, "queue_label": queue_match.group(0) if queue_match is not None else None, "queue_tier": int(queue_match.group(1)) if queue_match is not None else None, "queue_quantity": queue_quantity, "queue_spatially_associated": queue_match is not None and duration_source in {"queue_band", "queue_timer_band"}},
    )


def recognize_training_with_targets(frame: np.ndarray) -> "TrainingFrameRecognition":
    observation = recognize_training(frame)
    targets: list[Target] = [(f"tab:{troop_type}", roi) for troop_type, roi in TAB_ROIS.items()]
    for tier in observation.visible_tiers:
        if tier.target_roi is not None:
            targets.append((f"tier:{tier.tier}", tier.target_roi))
    if observation.normal_train_target is not None:
        targets.append(("train", observation.normal_train_target))
    if observation.train_now_target is not None:
        targets.append(("train-now", observation.train_now_target))
    if observation.warehouse_confirm_target is not None:
        targets.append(("warehouse-confirm", observation.warehouse_confirm_target))
    return TrainingFrameRecognition(observation, observation.frame_sha256, tuple(targets), observation.diagnostics)


def recognize_daily_training_progress(frame: np.ndarray) -> tuple[DailyTrainingProgress, ...]:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Daily frame must be a native 800x1280 image")
    return daily_progress_from_text(_ocr(frame), frame_sha256=_digest(frame))


class TrainingFrameRecognition:
    def __init__(self, observation: TrainingScreenObservation, frame_sha256: str, targets: tuple[Target, ...], diagnostics: Mapping[str, object]):
        self.observation = observation
        self.frame_sha256 = frame_sha256
        self.targets = targets
        self.diagnostics = diagnostics

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)
