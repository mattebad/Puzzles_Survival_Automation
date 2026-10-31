"""Native 800x1280 vision bindings for the local Campaign Auto Battle route.

The recognizer combines constrained OCR, fixed-profile geometry, color checks, and small
project-owned templates.  It never dispatches input.  Dynamic hero portraits and lineup contents
are ignored; Hero Lineup binds its Challenge and optional measured game Back controls.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Mapping
import unicodedata

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .campaign_auto_battle import CampaignRouteObservation, CampaignScreen, CampaignStage


Box = tuple[int, int, int, int]
Target = tuple[str, Box]

PROFILE_SIZE = (800, 1280)
ASSET_ROOT = Path(__file__).resolve().parent / "assets" / "campaign_auto_battle" / "800x1280"

STAGE_HEADER_ROI: Box = (246, 232, 559, 280)
STAGE_AP_ROI: Box = (338, 795, 478, 850)
STAGE_COST_ROI: Box = (215, 862, 278, 912)
STAGE_CHALLENGE_ROI: Box = (87, 863, 364, 956)
STAGE_CHALLENGE_TEXT_ROI: Box = (140, 900, 315, 952)
STAGE_CLOSE_ROI: Box = (675, 228, 764, 289)
LINEUP_CHALLENGE_ROI: Box = (262, 1156, 538, 1249)
LINEUP_HEADER_ROI: Box = (275, 5, 545, 70)
LINEUP_CONTROL_STRIP: Box = (0, 1135, 800, 1265)
WAVE_ROI: Box = (366, 13, 437, 54)
AUTO_ROI: Box = (630, 16, 692, 74)
BATTLE_EXIT_ROI: Box = (690, 9, 760, 85)
CAMPAIGN_EXIT_ROI: Box = (690, 920, 800, 1060)
WINNER_CAPTION_ROIS: tuple[Box, ...] = ((118, 174, 685, 270), (90, 120, 710, 230))
LOOT_CAPTION_ROI: Box = (300, 425, 500, 515)
VICTORY_CONTINUE_CAPTION_ROI: Box = (200, 1090, 610, 1190)
LOSE_ROI: Box = (145, 15, 655, 190)
DEFEAT_HINT_ROI: Box = (270, 250, 530, 302)
DEFEAT_CONTINUE_ROI: Box = (270, 1212, 530, 1270)
BUY_NOW_FORBIDDEN_ROI: Box = (278, 658, 470, 725)
CHAPTER_HEADER_ROI: Box = (390, 58, 800, 155)
HOME_CAMPAIGN_SEARCH_ROI: Box = (250, 250, 680, 760)
HOME_BOTTOM_NAV_ROI: Box = (0, 1160, 800, 1280)
MAP_SEARCH_ROI: Box = (40, 145, 690, 1010)
TIER_ONE_ROI: Box = (415, 65, 515, 132)
TIER_TWO_ROI: Box = (525, 65, 625, 132)
TIER_CONTROLS_ROI: Box = (410, 65, 625, 133)
TIER_CONTROLS_SEARCH_ROI: Box = (375, 45, 650, 145)
MAP_AP_ROI: Box = (3, 190, 129, 232)
HOME_AP_ROI: Box = (3, 225, 129, 261)
MAP_AP_CURRENT_ROI: Box = (3, 173, 115, 202)
HOME_AP_CURRENT_ROI: Box = (3, 205, 122, 234)

_STAGE_DIALOG_RE = re.compile(
    r"\[(\d+)\s*[-–]\s*(\d+)\]"
)
_CHAPTER_RE = re.compile(r"\bch\.?\s*(\d+)\b", re.IGNORECASE)
_FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass(frozen=True)
class CampaignFrameRecognition:
    observation: CampaignRouteObservation
    frame_sha256: str
    targets: tuple[Target, ...]
    diagnostics: Mapping[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


def _crop(frame: np.ndarray, box: Box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return frame[y0:y1, x0:x1]


def _normalized(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def _challenge_text(text: str) -> bool:
    return "challenge" in text or "hallenge" in text


def _ocr(frame: np.ndarray, box: Box, *, psm: int = 7, whitelist: str | None = None) -> str:
    image = cv2.resize(_crop(frame, box), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    return _normalized(pytesseract.image_to_string(image, config=config))


def _threshold_ocr(
    frame: np.ndarray,
    box: Box,
    *,
    threshold: int,
    whitelist: str,
    upscale: int = 5,
) -> str:
    gray = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    return _normalized(
        pytesseract.image_to_string(
            binary,
            config=f"--psm 7 -c tessedit_char_whitelist={whitelist}",
        )
    )


def _ap_fraction(frame: np.ndarray, box: Box) -> tuple[int, int] | None:
    text = _threshold_ocr(frame, box, threshold=150, whitelist="0123456789/")
    return _fraction(text)


def _hud_ap_text(frame: np.ndarray, box: Box) -> str:
    # HUD glyphs are smaller than Stage dialog text. At 5x the thresholded
    # antialiased Home 5 can read as 9; 3x preserves this row's digit strokes.
    gray = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    # Give Tesseract a blank line margin; a tightly cropped full AP bar can
    # otherwise segment as empty despite independently verified icon identity.
    binary = cv2.copyMakeBorder(binary, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=0)
    return _normalized(pytesseract.image_to_string(
        binary, config="--psm 7 -c tessedit_char_whitelist=0123456789/",
    ))


def _hud_ap_fraction(frame: np.ndarray, candidates: tuple[Box, ...]) -> tuple[int, int] | None:
    """Read one independently icon-bound AP row, never a neighboring stamina row."""
    template = cv2.imread(str(ASSET_ROOT / "stage_ap_icon.png"), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None
    # Isolate the lightning/badge identity from the stage crop's padding.
    glyph = template[6:48, 10:46]
    readings = []
    for _, y0, x1, y1 in candidates:
        icon = cv2.cvtColor(_crop(frame, (0, y0, 34, y1)), cv2.COLOR_BGR2GRAY)
        score = 0.0
        icon_right = None
        for percent in range(40, 76, 2):
            scaled = cv2.resize(glyph, None, fx=percent / 100.0, fy=percent / 100.0, interpolation=cv2.INTER_AREA)
            if scaled.shape[0] > icon.shape[0] or scaled.shape[1] > icon.shape[1]:
                continue
            _, matched, _, location = cv2.minMaxLoc(cv2.matchTemplate(icon, scaled, cv2.TM_CCOEFF_NORMED))
            if float(matched) > score:
                score = float(matched)
                icon_right = location[0] + scaled.shape[1]
        if score < 0.75 or icon_right is None:
            continue
        # The matched box's right edge is exclusive, as are NumPy crop bounds.
        number_left = max(23, icon_right)
        if number_left >= x1:
            continue
        text = _hud_ap_text(frame, (number_left, y0, x1, y1))
        if _FRACTION_RE.fullmatch(text) is None:
            continue
        value = _fraction(text)
        if value is not None:
            readings.append(value)
    # Multiple matching rows remain ambiguous even when their numbers agree.
    return readings[0] if len(readings) == 1 else None


def _template_score(frame: np.ndarray, box: Box, asset_name: str) -> float:
    expected = cv2.imread(str(ASSET_ROOT / asset_name), cv2.IMREAD_GRAYSCALE)
    current = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    if expected is None or current.shape != expected.shape:
        return 0.0
    return float(cv2.matchTemplate(current, expected, cv2.TM_CCOEFF_NORMED)[0, 0])


def _stage_close_x(frame: np.ndarray) -> Box | None:
    """Find the visible white X in the bounded Stage dialog corner."""
    hsv = cv2.cvtColor(_crop(frame, (630, 220, 775, 330)), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([179, 80, 255]))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    reference = np.zeros((40, 40), dtype=np.uint8)
    cv2.line(reference, (3, 3), (36, 36), 255, 9)
    cv2.line(reference, (3, 36), (36, 3), 255, 9)
    found = []
    for x, y, width, height, area in stats[1:]:
        if not (30 <= width <= 44 and 30 <= height <= 44 and 0.85 <= width / height <= 1.15):
            continue
        sample = cv2.resize(mask[y:y + height, x:x + width], (40, 40))
        if float(cv2.matchTemplate(sample, reference, cv2.TM_CCOEFF_NORMED)[0, 0]) >= 0.60:
            found.append((int(x + 630), int(y + 220), int(x + width + 630), int(y + height + 220)))
    return found[0] if len(found) == 1 else None


def _stage_ap_icon(frame: np.ndarray, box: Box) -> bool:
    asset = cv2.imread(str(ASSET_ROOT / "stage_ap_icon.png"), cv2.IMREAD_GRAYSCALE)
    if asset is None:
        return False
    glyph = asset[6:48, 10:46]
    search = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    for percent in range(65, 111):
        scaled = cv2.resize(glyph, None, fx=percent / 100.0, fy=percent / 100.0, interpolation=cv2.INTER_AREA)
        if scaled.shape[0] > search.shape[0] or scaled.shape[1] > search.shape[1]:
            continue
        _, score, _, _ = cv2.minMaxLoc(cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED))
        if score >= 0.75:
            return True
    return False


def _bind_stage_dialog(frame: np.ndarray, target_stage: CampaignStage):
    close = _stage_close_x(frame)
    if close is None:
        return None
    # The fresh X sets only search geometry. Each action target is measured
    # again from its own visible component; projected boxes never authorize taps.
    scale = (close[2] - close[0]) / 40.0
    dx = (close[0] + close[2]) / 2 - 720 * scale
    dy = (close[1] + close[3]) / 2 - 256 * scale

    def region(reference: Box) -> Box:
        result = tuple(round(value * scale + (dx if index % 2 == 0 else dy)) for index, value in enumerate(reference))
        if not (0 <= result[0] < result[2] <= 800 and 0 <= result[1] < result[3] <= 1280):
            raise ValueError("Stage dialog search geometry is outside the native frame")
        return result

    try:
        header = _ocr(frame, region((210, 232, 625, 280)))
        identities = list(_STAGE_DIALOG_RE.finditer(header))
        enemy_title = _ocr(frame, region((180, 295, 620, 355)))
        if len(identities) != 1 or re.search(r"\benemy\s+lineup\b", enemy_title) is None:
            return None
        identity = identities[0]
        stage = CampaignStage(target_stage.tier, int(identity.group(1)), int(identity.group(2)))
        balance_box = region(STAGE_AP_ROI)
        balance_text = _threshold_ocr(frame, balance_box, threshold=150, whitelist="0123456789/", upscale=3)
        balance_corroboration = _ocr(frame, balance_box, whitelist="0123456789/")
        balance_icon = _stage_ap_icon(frame, region((275, 795, 333, 852)))
        balance = _fraction(balance_text) if _FRACTION_RE.fullmatch(balance_text) and balance_icon else None
        corroborated = _fraction(balance_corroboration) if _FRACTION_RE.fullmatch(balance_corroboration) else None
        if balance != corroborated:
            balance = None
        cost_text = _threshold_ocr(frame, region((226, 863, 280, 914)), threshold=150, whitelist="0123456789")
        cost = int(cost_text) if cost_text.isdigit() and _stage_ap_icon(frame, region((180, 865, 228, 913))) else None
        x0, y0, x1, y1 = region((60, 840, 390, 975))
    except ValueError:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array([8, 70, 100]), np.array([38, 255, 255]))
    _, _, stats, _ = cv2.connectedComponentsWithStats(gold)
    controls = []
    for x, y, width, height, area in stats[1:]:
        if 200 * scale <= width <= 310 * scale and 60 * scale <= height <= 110 * scale and 2.5 <= width / height <= 4.2 and area / (width * height) >= 0.55:
            controls.append((int(x0 + x), int(y0 + y), int(x0 + x + width), int(y0 + y + height)))
    control = controls[0] if len(controls) == 1 else None
    caption = ""
    if control is not None:
        left, top, right, bottom = control
        caption = _ocr(frame, (left, top + (bottom - top) // 2, right, bottom))
    refill = re.search(r"\b(?:refill|buy|use)\b", caption + " " + header) is not None
    forbidden = refill or re.search(r"\bblitz\b", caption) is not None
    ready = bool(control and re.search(r"\bchallenge\b", caption) and not forbidden and balance is not None and cost is not None)
    targets = [("campaign-stage-dialog-close", close)]
    if ready:
        targets.append((f"campaign-challenge-{stage.identity}", control))
    return (
        CampaignRouteObservation(screen=CampaignScreen.STAGE_DIALOG, stage_dialog=stage,
                                 ap_current=balance[0] if balance else None, ap_cost=cost,
                                 challenge_ready=ready, refill_visible=refill),
        targets,
        {"stage_header": header, "stage_challenge_text": caption, "stage_ap_text": balance_text,
         "stage_ap_corroboration": balance_corroboration, "stage_ap_icon_verified": balance_icon,
         "stage_cost_text": cost_text, "stage_challenge_gold": _gold_ratio(frame, control) if control else 0.0},
    )


def _bind_chapter_back(frame: np.ndarray) -> Box | None:
    hsv = cv2.cvtColor(_crop(frame, (660, 930, 800, 1120)), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 80, 140]), np.array([40, 255, 255]))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    found = []
    for index, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if not (40 <= width <= 95 and 40 <= height <= 95 and 0.8 <= width / height <= 1.5 and 0.25 <= area / (width * height) <= 0.60):
            continue
        component = labels[y:y + height, x:x + width] == index
        cells = [[float(cell.mean()) for cell in np.array_split(row, 3, axis=1)] for row in np.array_split(component, 3)]
        if cells[0][0] < 0.10 and cells[0][2] > 0.35 and cells[1][2] > 0.60 and cells[2][0] > 0.20:
            found.append((int(x + 660), int(y + 930), int(x + width + 660), int(y + height + 930)))
    return found[0] if len(found) == 1 else None


def _bind_lineup_challenge(frame: np.ndarray) -> tuple[float, Box | None]:
    """Locate one unambiguous existing Challenge control in the bottom strip."""
    expected = cv2.imread(str(ASSET_ROOT / "lineup_challenge.png"), cv2.IMREAD_GRAYSCALE)
    if expected is None:
        return 0.0, None
    search = cv2.cvtColor(_crop(frame, LINEUP_CONTROL_STRIP), cv2.COLOR_BGR2GRAY)
    candidates: list[tuple[float, Box]] = []
    for percent in range(80, 111):
        scale = percent / 100.0
        resized = cv2.resize(expected, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        height, width = resized.shape
        scores = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        # A second spatially separate match is ambiguity, not another target.
        for _ in range(2):
            _, score, _, (left, top) = cv2.minMaxLoc(scores)
            if score < 0.72:
                break
            y = top + LINEUP_CONTROL_STRIP[1]
            candidates.append((float(score), (left, y, left + width, y + height)))
            scores[max(0, top - height // 2):top + height // 2 + 1,
                   max(0, left - width // 2):left + width // 2 + 1] = -1
    if not candidates:
        return 0.0, None
    score, target = max(candidates)
    x0, y0, x1, y1 = target
    if x0 < 240 or x1 > 560:
        return score, None
    if any(abs((box[0] + box[2]) - (x0 + x1)) > 80
           or abs((box[1] + box[3]) - (y0 + y1)) > 40
           for _, box in candidates):
        return score, None
    return score, target


def _bind_tier_controls(frame: np.ndarray) -> tuple[float, tuple[Box, Box] | None]:
    """Match only opaque 1/2 button faces; the gap, pointers and map are excluded."""
    search = cv2.cvtColor(_crop(frame, TIER_CONTROLS_SEARCH_ROI), cv2.COLOR_BGR2GRAY)
    controls = []
    for digit, interior in ((1, (12, 10, 89, 55)), (2, (16, 10, 90, 55))):
        candidates = []
        for state in ("selected", "unselected"):
            asset = cv2.imread(str(ASSET_ROOT / f"tier{digit}_{state}.png"), cv2.IMREAD_GRAYSCALE)
            if asset is None:
                return 0.0, None
            x0, y0, x1, y1 = interior
            face = asset[y0:y1, x0:x1]
            for percent in range(80, 111):
                scale = percent / 100.0
                resized = cv2.resize(face, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                height, width = resized.shape
                scores = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
                for _ in range(2):
                    _, score, _, (left, top) = cv2.minMaxLoc(scores)
                    if score < 0.90:
                        break
                    box = (left + TIER_CONTROLS_SEARCH_ROI[0], top + TIER_CONTROLS_SEARCH_ROI[1],
                           left + width + TIER_CONTROLS_SEARCH_ROI[0], top + height + TIER_CONTROLS_SEARCH_ROI[1])
                    candidates.append((float(score), scale, box))
                    scores[max(0, top - height // 2):top + height // 2 + 1,
                           max(0, left - width // 2):left + width // 2 + 1] = -1
        if not candidates:
            return 0.0, None
        best = max(candidates)
        _, _, box = best
        # Neighboring scale samples describe one face. A separate occurrence of
        # the same digit is ambiguity, including a duplicate overlaid pair.
        if any(abs((candidate[0] + candidate[2]) - (box[0] + box[2])) > 40
               or abs((candidate[1] + candidate[3]) - (box[1] + box[3])) > 20
               for _, _, candidate in candidates):
            return best[0], None
        controls.append(best)
    (score_one, scale_one, one), (score_two, scale_two, two) = controls
    score = min(score_one, score_two)
    separation = ((two[0] + two[2]) - (one[0] + one[2])) / 2
    expected_separation = 110 * (scale_one + scale_two) / 2
    if (abs(scale_one - scale_two) > 0.03
            or abs((one[1] + one[3]) - (two[1] + two[3])) > 8
            or not 0.85 * expected_separation <= separation <= 1.15 * expected_separation
            or _selected_tier(frame, one, two)[0] is None):
        return score, None
    return score, (one, two)


def _gold_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([8, 70, 100], dtype=np.uint8),
        np.array([38, 255, 255], dtype=np.uint8),
    )
    return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])


def _green_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([35, 80, 80], dtype=np.uint8),
        np.array([90, 255, 255], dtype=np.uint8),
    )
    return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])


def _fraction(text: str) -> tuple[int, int] | None:
    match = _FRACTION_RE.search(text)
    if not match:
        return None
    current = int(match.group(1))
    maximum = int(match.group(2))
    # Reject OCR garbage such as BGR "720/120" for a real "120/120" HUD.
    if maximum <= 0 or current < 0 or current > maximum:
        return None
    return (current, maximum)


def _ocr_boxes(frame: np.ndarray, box: Box) -> list[tuple[str, Box, float]]:
    x0, y0, _, _ = box
    scale = 3
    enlarged = cv2.resize(_crop(frame, box), None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box, float]] = []
    for index, raw in enumerate(data["text"]):
        text = raw.strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < 30:
            continue
        left = x0 + int(data["left"][index]) // scale
        top = y0 + int(data["top"][index]) // scale
        width = max(1, int(data["width"][index]) // scale)
        height = max(1, int(data["height"][index]) // scale)
        found.append((text, (left, top, left + width, top + height), confidence))
    return found


def _find_word_target(
    frame: np.ndarray,
    box: Box,
    expected: str,
) -> Box | None:
    expected = expected.casefold()
    for text, bounds, _ in _ocr_boxes(frame, box):
        if expected in text.casefold():
            x0, y0, x1, y1 = bounds
            return (max(0, x0 - 12), max(0, y0 - 12), min(800, x1 + 12), min(1280, y1 + 12))
    return None


def _caption_phrase_target(frame: np.ndarray, box: Box, words: tuple[str, ...]) -> Box | None:
    """Measure one literal caption, rejecting missing, duplicate, or split-row words."""
    matches = sorted(
        ((_normalized(text), bounds) for text, bounds, _ in _ocr_boxes(frame, box)
         if _normalized(text) in words),
        key=lambda match: match[1][0],
    )
    if tuple(text for text, _ in matches) != words:
        return None
    bounds = [bounds for _, bounds in matches]
    heights = [bottom - top for _, top, _, bottom in bounds]
    centers = [(top + bottom) / 2 for _, top, _, bottom in bounds]
    if max(centers) - min(centers) > max(8, max(heights) / 2):
        return None
    if any(left[2] >= right[0] for left, right in zip(bounds, bounds[1:])):
        return None
    return (min(bound[0] for bound in bounds), min(bound[1] for bound in bounds),
            max(bound[2] for bound in bounds), max(bound[3] for bound in bounds))


def _bind_victory_continue(frame: np.ndarray) -> tuple[Box | None, dict[str, object]]:
    continue_roi = _caption_phrase_target(frame, VICTORY_CONTINUE_CAPTION_ROI, ("tap", "to", "continue"))
    diagnostics: dict[str, object] = {"victory_continue_roi": continue_roi}
    if continue_roi is None:
        return None, diagnostics
    loot_roi = _caption_phrase_target(frame, LOOT_CAPTION_ROI, ("loot",))
    diagnostics["loot_caption_roi"] = loot_roi
    if loot_roi is None:
        return None, diagnostics

    captions = []
    for box in WINNER_CAPTION_ROIS:
        gray = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
        # The word is stable while the crest and flare behind it animate. Remove
        # only low-frequency illumination before reading the complete caption.
        letters = cv2.addWeighted(gray, 1.0, cv2.GaussianBlur(gray, (0, 0), 15), -1.0, 128)
        captions.append(_normalized(pytesseract.image_to_string(letters, config="--psm 8")))
    diagnostics["winner_captions"] = captions
    return (continue_roi if captions.count("winner") == 1 else None), diagnostics


def _numeric_targets(frame: np.ndarray, box: Box) -> dict[int, Box]:
    targets: dict[int, Box] = {}
    for text, bounds, confidence in _ocr_boxes(frame, box):
        cleaned = re.sub(r"\D", "", text)
        if cleaned and len(cleaned) <= 2 and confidence >= 45:
            value = int(cleaned)
            if 1 <= value <= 99:
                x0, y0, x1, y1 = bounds
                targets.setdefault(
                    value,
                    (max(0, x0 - 20), max(0, y0 - 20), min(800, x1 + 20), min(1280, y1 + 20)),
                )
    return targets


def _chapter_medallion_targets(frame: np.ndarray, box: Box) -> dict[int, Box]:
    """OCR chapter digits inside their circular map medallions.

    Full-map OCR can merge a chapter number with text or counters beside it.  Circle
    localization makes the OCR spatially local to the current-frame chapter control
    without encoding any destination-specific coordinates or values.
    """

    x0, y0, x1, y1 = box
    gray = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(gray, (5, 5), 1.2),
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=50,
        param1=100,
        param2=35,
        minRadius=20,
        maxRadius=38,
    )
    if circles is None:
        return {}

    targets: dict[int, Box] = {}
    for local_x, local_y, radius in circles[0]:
        cx = int(round(local_x)) + x0
        cy = int(round(local_y)) + y0
        radius = int(round(radius))
        inset = max(12, int(round(radius * 0.75)))
        digit_roi = (
            max(0, cx - inset),
            max(0, cy - inset),
            min(PROFILE_SIZE[0], cx + inset),
            min(PROFILE_SIZE[1], cy + inset),
        )
        digit = cv2.cvtColor(_crop(frame, digit_roi), cv2.COLOR_BGR2GRAY)
        enlarged = cv2.resize(digit, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
        token = pytesseract.image_to_string(
            enlarged,
            config="--psm 8 -c tessedit_char_whitelist=0123456789",
        ).strip()
        if not token.isdigit() or len(token) > 2:
            continue
        value = int(token)
        if not 1 <= value <= 99:
            continue
        control_roi = (
            max(0, cx - radius),
            max(0, cy - radius),
            min(PROFILE_SIZE[0], cx + radius),
            min(PROFILE_SIZE[1], cy + radius),
        )
        targets.setdefault(value, control_roi)
    return targets


def _stage_node_targets(frame: np.ndarray) -> dict[int, Box]:
    """Locate red Campaign stage nodes and OCR only their high-contrast white center glyphs."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    low_red = cv2.inRange(hsv, np.array([0, 100, 60]), np.array([12, 255, 255]))
    high_red = cv2.inRange(hsv, np.array([170, 100, 60]), np.array([179, 255, 255]))
    mask = cv2.bitwise_or(low_red, high_red)
    mask[: MAP_SEARCH_ROI[1], :] = 0
    mask[MAP_SEARCH_ROI[3] :, :] = 0
    mask[:, : MAP_SEARCH_ROI[0]] = 0
    mask[:, MAP_SEARCH_ROI[2] :] = 0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    targets: dict[int, Box] = {}
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if not (40 <= width <= 80 and 40 <= height <= 80 and 1200 <= area <= 4500):
            continue
        inset = max(7, min(width, height) // 7)
        center = frame[y + inset : y + height - inset, x + inset : x + width - inset]
        center = cv2.resize(center, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
        center_hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        white = cv2.inRange(center_hsv, np.array([0, 0, 130]), np.array([179, 100, 255]))
        text = pytesseract.image_to_string(
            white,
            config="--psm 8 -c tessedit_char_whitelist=0123456789",
        ).strip()
        if text.isdigit() and 1 <= int(text) <= 99:
            targets.setdefault(int(text), (x, y, x + width, y + height))
    return targets


def _selected_tier(
    frame: np.ndarray, tier_one: Box | None = None, tier_two: Box | None = None,
) -> tuple[int | None, dict[str, float]]:
    if tier_one is None or tier_two is None:
        _, boxes = _bind_tier_controls(frame)
        if boxes is None:
            return None, {}
        tier_one, tier_two = boxes
    ratios = {}
    states = []
    for digit, box in ((1, tier_one), (2, tier_two)):
        hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
        gold = cv2.inRange(hsv, np.array([8, 70, 150]), np.array([38, 255, 255]))
        brown = cv2.inRange(hsv, np.array([5, 50, 45]), np.array([38, 255, 149]))
        gold_ratio, brown_ratio = float(np.mean(gold > 0)), float(np.mean(brown > 0))
        ratios.update({f"tier_{digit}_gold": gold_ratio, f"tier_{digit}_brown": brown_ratio})
        states.append("gold" if gold_ratio >= 0.60 and brown_ratio <= 0.15
                      else "brown" if brown_ratio >= 0.60 and gold_ratio <= 0.15 else "unknown")
    return (1 if states == ["gold", "brown"] else 2 if states == ["brown", "gold"] else None), ratios


def recognize_campaign_frame(
    frame: np.ndarray,
    target_stage: CampaignStage,
    *,
    battle_elapsed_seconds: float = 0.0,
) -> CampaignFrameRecognition:
    """Classify one fresh native frame and bind only positively recognized controls."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Campaign frame must be a native 800x1280 image")

    frame_hash = hashlib.sha256(frame.tobytes()).hexdigest()
    targets: list[Target] = []
    diagnostics: dict[str, object] = {}

    victory_continue_roi, victory_diagnostics = _bind_victory_continue(frame)
    diagnostics.update(victory_diagnostics)
    if victory_continue_roi is not None:
        targets.append(("campaign-victory-continue", victory_continue_roi))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.RESULT,
                winner_visible=True,
                loot_visible=True,
                tap_to_continue_visible=True,
                battle_elapsed_seconds=battle_elapsed_seconds,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    lose_score = _template_score(frame, LOSE_ROI, "lose_word.png")
    defeat_hint_score = _template_score(frame, DEFEAT_HINT_ROI, "defeat_improve_might.png")
    defeat_continue_score = _template_score(
        frame,
        DEFEAT_CONTINUE_ROI,
        "defeat_tap_to_continue.png",
    )
    defeat_hint_text = _ocr(frame, DEFEAT_HINT_ROI)
    defeat_continue_text = _ocr(frame, DEFEAT_CONTINUE_ROI)
    diagnostics.update(
        lose_score=lose_score,
        defeat_hint_score=defeat_hint_score,
        defeat_continue_score=defeat_continue_score,
        defeat_hint_text=defeat_hint_text,
        defeat_continue_text=defeat_continue_text,
    )
    defeat = bool(
        lose_score >= 0.72
        and defeat_hint_score >= 0.72
        and "improve might" in defeat_hint_text
        and defeat_continue_score >= 0.72
        and "tap to continue" in defeat_continue_text
    )
    if defeat:
        targets.append(("campaign-defeat-return", DEFEAT_CONTINUE_ROI))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.RESULT,
                defeat_visible=True,
                tap_to_continue_visible=True,
                return_control_visible=True,
                battle_elapsed_seconds=battle_elapsed_seconds,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    lineup_header = _ocr(frame, LINEUP_HEADER_ROI)
    header_is_lineup = lineup_header == "hero lineup"
    lineup_score, lineup_roi = _bind_lineup_challenge(frame) if header_is_lineup else (0.0, None)
    lineup_caption_roi = None
    if lineup_roi is not None:
        left, top, right, bottom = lineup_roi
        width, height = right - left, bottom - top
        # Read the caption inside the freshly matched face. The gold frame and
        # its shadow can cause whole-button OCR to discard a clear caption.
        lineup_caption_roi = (left + width // 30, top + height // 5,
                              right - width // 30, bottom - height // 6)
    lineup_text = _ocr(frame, lineup_caption_roi) if lineup_caption_roi is not None else ""
    lineup_gold = _gold_ratio(frame, lineup_roi or LINEUP_CHALLENGE_ROI)
    diagnostics.update(lineup_header=lineup_header, lineup_text=lineup_text, lineup_score=lineup_score,
                       lineup_gold=lineup_gold, lineup_caption_roi=lineup_caption_roi)
    if lineup_roi is not None and lineup_text == "challenge" and lineup_gold >= 0.20:
        targets.append(("campaign-lineup-challenge", lineup_roi))
        from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual

        lineup_back = _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)
        if lineup_back is not None:
            targets.append(("campaign-lineup-back", lineup_back))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.HERO_LINEUP,
                lineup_challenge_ready=True,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    stage_dialog = _bind_stage_dialog(frame, target_stage)
    if stage_dialog is not None:
        observation, stage_targets, stage_diagnostics = stage_dialog
        return CampaignFrameRecognition(
            observation,
            frame_hash,
            tuple(stage_targets),
            diagnostics | stage_diagnostics,
        )

    wave_text = _threshold_ocr(frame, WAVE_ROI, threshold=180, whitelist="0123456789/")
    enabled_score = _template_score(frame, AUTO_ROI, "auto_enabled.png")
    disabled_score = _template_score(frame, AUTO_ROI, "auto_disabled.png")
    auto_green = _green_ratio(frame, AUTO_ROI)
    wave = _fraction(wave_text)
    diagnostics.update(
        wave_text=wave_text,
        auto_enabled_score=enabled_score,
        auto_disabled_score=disabled_score,
        auto_green_ratio=auto_green,
    )
    if wave and wave[1] == 3 and 1 <= wave[0] <= 3:
        auto_enabled = bool(auto_green >= 0.08 and enabled_score >= disabled_score + 0.04)
        if not auto_enabled:
            targets.append(("campaign-auto", AUTO_ROI))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.BATTLE,
                auto_enabled=auto_enabled,
                battle_elapsed_seconds=battle_elapsed_seconds,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    chapter_header = _ocr(frame, CHAPTER_HEADER_ROI, psm=6)
    chapter_match = _CHAPTER_RE.search(chapter_header)
    if chapter_match:
        chapter = int(chapter_match.group(1))
        stage_targets = _stage_node_targets(frame)
        for number, bounds in stage_targets.items():
            targets.append((f"campaign-stage-{target_stage.tier}-{chapter}-{number}", bounds))
        chapter_back = _bind_chapter_back(frame)
        if chapter_back is not None:
            targets.append(("campaign-chapter-back", chapter_back))
        ap = _hud_ap_fraction(frame, (MAP_AP_CURRENT_ROI, MAP_AP_ROI))
        diagnostics.update(chapter_header=chapter_header, visible_stage_numbers=sorted(stage_targets), map_ap=ap)
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=target_stage.tier,
                chapter_number=chapter,
                visible_stage_numbers=tuple(sorted(stage_targets)),
                stage_navigation_available=True,
                ap_current=ap[0] if ap else None,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    tier_controls_score, tier_rois = _bind_tier_controls(frame)
    selected_tier, tier_diagnostics = _selected_tier(frame, *tier_rois) if tier_rois else (None, {})
    diagnostics.update(tier_diagnostics)
    diagnostics["tier_controls_score"] = tier_controls_score
    tier_text = _ocr(frame, (400, 55, 635, 140), psm=6)
    map_numbers = _numeric_targets(frame, MAP_SEARCH_ROI)
    map_numbers.update(
        {
            number: bounds
            for number, bounds in _chapter_medallion_targets(frame, MAP_SEARCH_ROI).items()
            if number not in map_numbers
        }
    )
    diagnostics.update(tier_text=tier_text, visible_chapter_numbers=sorted(map_numbers))
    if selected_tier is not None and tier_rois is not None:
        tier_ap = _hud_ap_fraction(frame, (MAP_AP_CURRENT_ROI, MAP_AP_ROI))
        # Atlas vision imports this recognizer's shared constants, so defer the
        # measured-control seam until current Tier Map recognition is complete.
        from .campaign_atlas_vision import measured_survey_target

        try:
            campaign_exit_roi, campaign_exit_score = measured_survey_target(frame, "campaign-exit-base")
        except RuntimeError:
            campaign_exit_roi, campaign_exit_score = None, 0.0
        diagnostics["campaign_exit_score"] = campaign_exit_score
        targets.extend(
            [
                ("campaign-tier-1", tier_rois[0]),
                ("campaign-tier-2", tier_rois[1]),
                ("campaign-base-request", (0, 1170, 132, 1280)),
            ]
        )
        if campaign_exit_roi is not None:
            targets.append(("campaign-exit-base", campaign_exit_roi))
        for number, bounds in map_numbers.items():
            targets.append((f"campaign-chapter-{number}", bounds))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=selected_tier,
                chapter_number=target_stage.chapter if target_stage.chapter in map_numbers else None,
                visible_chapter_numbers=tuple(sorted(map_numbers)),
                chapter_navigation_available=True,
                ap_current=tier_ap[0] if tier_ap else None,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    campaign_target = _find_word_target(frame, HOME_CAMPAIGN_SEARCH_ROI, "campaign")
    bottom_nav = _ocr(frame, HOME_BOTTOM_NAV_ROI, psm=6)
    home_ap = _hud_ap_fraction(frame, (HOME_AP_CURRENT_ROI, HOME_AP_ROI))
    if home_ap and any(word in bottom_nav for word in ("hero", "quest", "alliance", "more")):
        if campaign_target:
            targets.append(("campaign-entry", campaign_target))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.HOME_BASE,
                ap_current=home_ap[0] if home_ap else None,
            ),
            frame_hash,
            tuple(targets),
            diagnostics | {"bottom_nav_text": bottom_nav},
        )

    return CampaignFrameRecognition(
        CampaignRouteObservation(screen=CampaignScreen.UNKNOWN, recognized=False),
        frame_hash,
        (),
        diagnostics,
    )


def read_campaign_frame(
    path: Path,
    target_stage: CampaignStage,
    *,
    battle_elapsed_seconds: float = 0.0,
) -> CampaignFrameRecognition:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot read Campaign frame: {path}")
    return recognize_campaign_frame(frame, target_stage, battle_elapsed_seconds=battle_elapsed_seconds)
