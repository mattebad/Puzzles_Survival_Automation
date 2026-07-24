"""Native 800x1280 vision bindings for the local Campaign Auto Battle route.

The recognizer combines constrained OCR, fixed-profile geometry, color checks, and small
project-owned templates.  It never dispatches input.  Dynamic hero portraits and lineup contents
are deliberately ignored; only the bottom lineup Challenge control is recognized.
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
STAGE_AP_ROI: Box = (330, 795, 478, 850)
STAGE_COST_ROI: Box = (215, 862, 278, 912)
STAGE_CHALLENGE_ROI: Box = (87, 863, 364, 956)
STAGE_CHALLENGE_TEXT_ROI: Box = (140, 900, 315, 952)
STAGE_CLOSE_ROI: Box = (675, 228, 764, 289)
LINEUP_CHALLENGE_ROI: Box = (262, 1156, 538, 1249)
WAVE_ROI: Box = (366, 13, 437, 54)
AUTO_ROI: Box = (630, 16, 692, 74)
BATTLE_EXIT_ROI: Box = (690, 9, 760, 85)
CAMPAIGN_EXIT_ROI: Box = (690, 920, 800, 1060)
WINNER_ROI: Box = (75, 101, 727, 230)
LOOT_ROI: Box = (342, 435, 458, 490)
CONTINUE_ROI: Box = (271, 1101, 530, 1161)
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
MAP_AP_ROI: Box = (3, 190, 129, 232)
HOME_AP_ROI: Box = (3, 225, 129, 261)

_STAGE_DIALOG_RE = re.compile(
    r"(?:\[(\d+)\s*[-–]\s*(\d+)\]|(\d+)\s*[-–]\s*(\d+)\])"
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
) -> str:
    gray = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
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


def _template_score(frame: np.ndarray, box: Box, asset_name: str) -> float:
    expected = cv2.imread(str(ASSET_ROOT / asset_name), cv2.IMREAD_GRAYSCALE)
    current = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    if expected is None or current.shape != expected.shape:
        return 0.0
    return float(cv2.matchTemplate(current, expected, cv2.TM_CCOEFF_NORMED)[0, 0])


def _edge_template_score(frame: np.ndarray, box: Box, asset_name: str) -> float:
    expected = cv2.imread(str(ASSET_ROOT / asset_name), cv2.IMREAD_GRAYSCALE)
    current = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2GRAY)
    if expected is None or current.shape != expected.shape:
        return 0.0
    return float(
        cv2.matchTemplate(
            cv2.Canny(current, 60, 160),
            cv2.Canny(expected, 60, 160),
            cv2.TM_CCOEFF_NORMED,
        )[0, 0]
    )


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


def _selected_tier(frame: np.ndarray) -> tuple[int | None, dict[str, float]]:
    ratios = {"tier_1_gold": _gold_ratio(frame, TIER_ONE_ROI), "tier_2_gold": _gold_ratio(frame, TIER_TWO_ROI)}
    difference = ratios["tier_1_gold"] - ratios["tier_2_gold"]
    selected = 1 if difference > 0.05 else (2 if difference < -0.05 else None)
    return selected, ratios


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

    loot_text = _ocr(frame, LOOT_ROI)
    continue_text = _ocr(frame, CONTINUE_ROI)
    winner_score = _template_score(frame, WINNER_ROI, "winner_word.png")
    diagnostics.update(loot_text=loot_text, continue_text=continue_text, winner_score=winner_score)
    winner = winner_score >= 0.72
    loot = "loot" in loot_text
    tap_continue = "tap to continue" in continue_text
    if winner and loot and tap_continue:
        targets.append(("campaign-victory-continue", CONTINUE_ROI))
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

    lineup_text = _ocr(frame, LINEUP_CHALLENGE_ROI)
    lineup_score = _template_score(frame, LINEUP_CHALLENGE_ROI, "lineup_challenge.png")
    lineup_gold = _gold_ratio(frame, LINEUP_CHALLENGE_ROI)
    diagnostics.update(lineup_text=lineup_text, lineup_score=lineup_score, lineup_gold=lineup_gold)
    if _challenge_text(lineup_text) and lineup_gold >= 0.20 and lineup_score >= 0.72:
        targets.append(("campaign-lineup-challenge", LINEUP_CHALLENGE_ROI))
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.HERO_LINEUP,
                lineup_challenge_ready=True,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
        )

    stage_header = _ocr(frame, STAGE_HEADER_ROI)
    stage_match = _STAGE_DIALOG_RE.search(stage_header)
    challenge_text = _ocr(frame, STAGE_CHALLENGE_TEXT_ROI)
    challenge_gold = _gold_ratio(frame, STAGE_CHALLENGE_ROI)
    diagnostics.update(
        stage_header=stage_header,
        stage_challenge_text=challenge_text,
        stage_challenge_gold=challenge_gold,
    )
    if stage_match and _challenge_text(challenge_text):
        balance_text = _threshold_ocr(frame, STAGE_AP_ROI, threshold=150, whitelist="0123456789/")
        cost_text = _threshold_ocr(frame, STAGE_COST_ROI, threshold=150, whitelist="0123456789")
        balance = _fraction(balance_text)
        cost_digits = re.sub(r"\D", "", cost_text)
        chapter = int(stage_match.group(1) or stage_match.group(3))
        stage_number = int(stage_match.group(2) or stage_match.group(4))
        stage = CampaignStage(target_stage.tier, chapter, stage_number)
        challenge_ready = challenge_gold >= 0.18
        targets.extend(
            [
                ("campaign-stage-dialog-close", STAGE_CLOSE_ROI),
                (f"campaign-challenge-{stage.identity}", STAGE_CHALLENGE_ROI),
            ]
        )
        diagnostics.update(stage_ap_text=balance_text, stage_cost_text=cost_text)
        return CampaignFrameRecognition(
            CampaignRouteObservation(
                screen=CampaignScreen.STAGE_DIALOG,
                stage_dialog=stage,
                ap_current=balance[0] if balance else None,
                ap_cost=int(cost_digits) if cost_digits else None,
                challenge_ready=challenge_ready,
                refill_visible=False,
            ),
            frame_hash,
            tuple(targets),
            diagnostics,
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
        targets.append(("campaign-chapter-back", (670, 960, 800, 1095)))
        ap_text = _threshold_ocr(frame, MAP_AP_ROI, threshold=150, whitelist="0123456789/")
        ap = _fraction(ap_text)
        diagnostics.update(chapter_header=chapter_header, visible_stage_numbers=sorted(stage_targets), map_ap_text=ap_text)
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

    selected_tier, tier_diagnostics = _selected_tier(frame)
    diagnostics.update(tier_diagnostics)
    tier_controls_score = _edge_template_score(frame, TIER_CONTROLS_ROI, "tier_controls.png")
    diagnostics["tier_controls_score"] = tier_controls_score
    tier_text = _ocr(frame, (400, 55, 635, 140), psm=6)
    map_numbers = _numeric_targets(frame, MAP_SEARCH_ROI)
    diagnostics.update(tier_text=tier_text, visible_chapter_numbers=sorted(map_numbers))
    if selected_tier is not None and tier_controls_score >= 0.45:
        tier_ap = _ap_fraction(frame, MAP_AP_ROI)
        campaign_exit_score = _template_score(frame, CAMPAIGN_EXIT_ROI, "campaign_exit.png")
        diagnostics["campaign_exit_score"] = campaign_exit_score
        targets.extend(
            [
                ("campaign-tier-1", TIER_ONE_ROI),
                ("campaign-tier-2", TIER_TWO_ROI),
                ("campaign-base-request", (0, 1170, 132, 1280)),
            ]
        )
        if campaign_exit_score >= 0.60:
            targets.append(("campaign-exit-base", CAMPAIGN_EXIT_ROI))
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
    home_ap = _ap_fraction(frame, HOME_AP_ROI)
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
