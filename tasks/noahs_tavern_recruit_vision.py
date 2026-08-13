"""Native 800x1280 BlueStacks vision adapter for Noah's Tavern."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import re
import unicodedata
from typing import Callable

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_TIER_TARGET_PREFIX,
    NOAHS_TAVERN_SCREEN,
    UNKNOWN_SCREEN,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
    parse_cooldown_seconds,
)


PROFILE_SIZE = (800, 1280)
Box = tuple[int, int, int, int]

TAVERN_HEADER_ROI: Box = (180, 15, 620, 105)
TAVERN_TITLE_ROI: Box = (150, 105, 650, 220)
TAVERN_ATTEMPTS_ROI: Box = (45, 865, 450, 955)
TAVERN_FREE_ROI: Box = (90, 925, 385, 1055)
TAVERN_PAID_ROI: Box = (410, 925, 720, 1055)
TAVERN_CARDS_ROI: Box = (0, 1070, 800, 1235)
TAVERN_OVERLAY_ROI: Box = (0, 0, 800, 1280)
RESULT_REWARD_ROI: Box = (250, 450, 560, 790)
RESULT_CLOSE_ROI: Box = (90, 975, 350, 1100)
RESULT_PAID_ROI: Box = (420, 975, 720, 1100)

_ATTEMPTS_RE = re.compile(r"daily\s+free\s+atte\w{0,6}\s*[:.]?\s*(\d+)", re.IGNORECASE)
_ATTEMPTS_FALLBACK_RE = re.compile(r"atte\w{0,6}\s*[:.]?\s*(\d+)", re.IGNORECASE)
_FREE_RE = re.compile(r"free\s+recruit\s*1x", re.IGNORECASE)
_PAID_RE = re.compile(r"recruit\s*10x|recruit\s*1x", re.IGNORECASE)
_CARD_ROIS = {
    RecruitTier.BASIC: (0, 1070, 252, 1235),
    RecruitTier.INT: (267, 1070, 503, 1235),
    RecruitTier.ADV: (520, 1070, 756, 1235),
}


def _crop(frame: np.ndarray, box: Box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return frame[y0:y1, x0:x1]


def _normalize_cooldown_ocr(text: str) -> str:
    normalized = text.casefold()
    # On the native gold timer, Tesseract can merge "in 1d" into "i@id".
    return re.sub(r"\bi@id\b", "in 1d", normalized)


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def _text(frame: np.ndarray, box: Box, *, psm: int = 6, ocr: Callable[[np.ndarray, int], str] | None = None) -> str:
    crop = cv2.resize(_crop(frame, box), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    raw = ocr(crop, psm) if ocr else pytesseract.image_to_string(crop, config=f"--psm {psm}")
    return _normalize(raw)


def _ocr_boxes(frame: np.ndarray) -> list[tuple[str, Box]]:
    enlarged = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box]] = []
    for index, raw in enumerate(data["text"]):
        text = _normalize(raw)
        if not text:
            continue
        x = int(data["left"][index]) // 3
        y = int(data["top"][index]) // 3
        width = max(1, int(data["width"][index]) // 3)
        height = max(1, int(data["height"][index]) // 3)
        found.append((text, (x, y, min(800, x + width), min(1280, y + height))))
    return found


def _purple_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([125, 55, 55], dtype=np.uint8), np.array([165, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(mask)) / float(mask.size)


def _red_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array([0, 70, 50], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
    high = cv2.inRange(hsv, np.array([165, 70, 50], dtype=np.uint8), np.array([179, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(cv2.bitwise_or(low, high))) / float(low.size)


def _tier_from_text(text: str) -> RecruitTier | None:
    # The native Tavern title occasionally OCRs ``Adv.`` as ``AQV.``.  This
    # correction is intentionally scoped to the title classifier and is only
    # called after the Noah's Tavern header has been positively recognized.
    normalized = text.replace("aqv", "adv")
    if "basic" in normalized:
        return RecruitTier.BASIC
    if "int" in normalized:
        return RecruitTier.INT
    if "adv" in normalized:
        return RecruitTier.ADV
    return None


def recognize_noahs_tavern_frame(
    frame: np.ndarray,
    *,
    captured_monotonic: float | None = None,
    stale: bool = False,
    ocr: Callable[[np.ndarray, int], str] | None = None,
) -> NoahTavernObservation:
    """Recognize only positively identified native Tavern/result frames."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Noah's Tavern frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    header = _text(frame, TAVERN_HEADER_ROI, ocr=ocr)
    title = _text(frame, TAVERN_TITLE_ROI, ocr=ocr)
    full = _text(frame, TAVERN_OVERLAY_ROI, psm=11, ocr=ocr)
    diagnostics = {"header_text": header, "title_text": title, "full_text": full}
    if "noah" in header and "taver" in header and _tier_from_text(title) is not None:
        selected = _tier_from_text(title)
        cards = _text(frame, TAVERN_CARDS_ROI, psm=11, ocr=ocr)
        visible_tiers = tuple(tier for tier in RecruitTier if tier.value.casefold().replace(".", "")[:4] in cards.replace(".", ""))
        if not visible_tiers:
            visible_tiers = tuple(RecruitTier)
        attempts_text = _text(frame, TAVERN_ATTEMPTS_ROI, ocr=ocr)
        attempts_match = _ATTEMPTS_RE.search(attempts_text) or _ATTEMPTS_FALLBACK_RE.search(attempts_text)
        attempts = int(attempts_match.group(1)) if attempts_match else None
        cooldown_text = attempts_text if parse_cooldown_seconds(attempts_text) else _text(frame, TAVERN_FREE_ROI, ocr=ocr)
        if parse_cooldown_seconds(cooldown_text) is None:
            alternate_timer = _normalize_cooldown_ocr(_text(frame, TAVERN_ATTEMPTS_ROI, psm=11, ocr=ocr))
            if parse_cooldown_seconds(alternate_timer) is not None:
                cooldown_text = alternate_timer
        cooldown = parse_cooldown_seconds(cooldown_text)
        free_text = _text(frame, TAVERN_FREE_ROI, ocr=ocr)
        paid_text = _text(frame, TAVERN_PAID_ROI, ocr=ocr)
        free_visible = bool(_FREE_RE.search(free_text)) or ("free" in free_text and "recruit 1x" in free_text)
        # The native 800x1280 counter occasionally OCRs its lone digit as ``|``.
        # For the one-attempt tiers only, the independently recognized enabled
        # Free Recruit 1x control is sufficient to establish that one remains.
        if attempts is None and free_visible and TIER_ATTEMPT_MAXIMUMS[selected or RecruitTier.BASIC] == 1:
            attempts = 1
        cooldown_active = not free_visible and bool(cooldown and cooldown > 0)
        # A cooldown frame shows the same Daily Free slot as disabled "Recruit 1x".
        free_slot_visible = free_visible or cooldown_active
        target = TAVERN_FREE_ROI
        panel = (40, 840, 760, 1070)
        selected_obs = NoahTierObservation(
            tier=selected or RecruitTier.BASIC,
            daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[selected or RecruitTier.BASIC],
            attempts_remaining=attempts,
            cooldown_text=cooldown_text,
            cooldown_duration_seconds=cooldown,
            cooldown_active=cooldown_active,
            next_eligible_timestamp=(captured_monotonic + cooldown if captured_monotonic is not None and cooldown_active else None),
            free_control_visible=free_slot_visible,
            free_control_enabled=free_visible and not cooldown_active and _purple_ratio(frame, TAVERN_FREE_ROI) >= 0.04,
            target_roi=target,
            panel_roi=panel,
            target_identity=NOAHS_TAVERN_FREE_TARGET if free_slot_visible else "",
            control_class=NOAHS_TAVERN_FREE_TARGET if free_slot_visible else "",
            cost_type="none" if free_slot_visible else "unknown",
            cost_amount=0 if free_slot_visible else None,
            quantity=1 if free_slot_visible else None,
            premium_control_visible=bool(_PAID_RE.search(paid_text)),
            recognized=selected is not None and (attempts is not None or cooldown_active),
        )
        tiers = []
        for tier in RecruitTier:
            if tier == selected_obs.tier:
                tiers.append(selected_obs)
            else:
                tiers.append(
                    NoahTierObservation(
                        tier=tier,
                        daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
                        attempts_remaining=None,
                        target_roi=_CARD_ROIS[tier],
                        panel_roi=TAVERN_CARDS_ROI,
                        target_identity=NOAHS_TAVERN_TIER_TARGET_PREFIX + tier.name,
                        recognized=tier in visible_tiers,
                    )
                )
        return NoahTavernObservation(
            screen_state=NOAHS_TAVERN_SCREEN,
            selected_tier=selected,
            tiers=tuple(tiers),
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
            stale=stale,
            overlay_state="none",
            recognized=selected is not None and bool(visible_tiers),
        )
    result_identity = _text(frame, RESULT_REWARD_ROI, psm=11, ocr=ocr)
    close_visible = _red_ratio(frame, RESULT_CLOSE_ROI) >= 0.08
    explicit_reward = "frag" in result_identity or "antiserum" in result_identity
    if close_visible and explicit_reward:
        result_tier = None
        return NoahTavernObservation(
            screen_state=HERO_RECRUIT_RESULT_SCREEN,
            selected_tier=None,
            tiers=tuple(
                NoahTierObservation(tier=tier, daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier], attempts_remaining=None)
                for tier in RecruitTier
            ),
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
            stale=stale,
            overlay_state="none",
            recognized=bool(result_identity),
            result_tier=result_tier,
            result_identity=result_identity,
            safe_close_visible=close_visible,
            safe_close_roi=RESULT_CLOSE_ROI,
            premium_result_control_visible=bool(_PAID_RE.search(_text(frame, RESULT_PAID_ROI, ocr=ocr))),
        )
    home_text = _text(frame, TAVERN_OVERLAY_ROI, psm=11, ocr=ocr)
    home_boxes = _ocr_boxes(frame) if ocr is None else []
    tavern_box = next((box for text, box in home_boxes if text.startswith("taver")), None)
    is_home = "headquarters" in home_text and "taver" in home_text and tavern_box is not None
    if is_home:
        x0, y0, x1, y1 = tavern_box
        target = (max(0, x0 - 90), max(0, y0 - 160), min(800, x1 + 25), min(1280, y1 + 10))
        return NoahTavernObservation(
            screen_state=HOME_BASE_SCREEN,
            selected_tier=None,
            tiers=tuple(
                NoahTierObservation(tier=tier, daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier], attempts_remaining=None)
                for tier in RecruitTier
            ),
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
            stale=stale,
            recognized=True,
            home_tavern_target_roi=target,
        )
    return NoahTavernObservation(
        screen_state=UNKNOWN_SCREEN,
        selected_tier=None,
        tiers=tuple(
            NoahTierObservation(tier=tier, daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier], attempts_remaining=None)
            for tier in RecruitTier
        ),
        frame_sha256=digest,
        captured_monotonic=captured_monotonic,
        stale=stale,
        recognized=False,
    )
