"""Native 800x1280 OCR/color recognition for the Research Lab Nova route."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .nova_praise import (
    NOVA_HOME,
    NOVA_INTERACTION_TARGET,
    NOVA_LAB_MENU,
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
    parse_cooldown_seconds,
)


PROFILE_SIZE = (800, 1280)
Box = tuple[int, int, int, int]

RESEARCH_LAB_ROI: Box = (455, 410, 665, 650)
LAB_MENU_ROI: Box = (330, 570, 760, 780)
NOVA_MENU_ROI: Box = (500, 600, 640, 760)
NOVA_HEADER_ROI: Box = (260, 0, 540, 92)
NOVA_BODY_ROI: Box = (80, 80, 730, 930)
NOVA_PRAISE_ROI: Box = (270, 975, 530, 1115)
NOVA_ATTEMPTS_ROI: Box = (150, 1125, 650, 1235)
# The native CD timer is above the interaction buttons; keep it separate from the
# attempts counter so a clipped lower panel cannot masquerade as cooldown evidence.
NOVA_COOLDOWN_ROI: Box = (100, 900, 700, 1000)
NOVA_OVERLAY_ROI: Box = (0, 0, 800, 1280)
_ATTEMPTS_RE = re.compile(r"(?:attempts?|interactions?)[^0-9]{0,20}(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class NovaFrameRecognition:
    observation: NovaPraiseObservation
    frame_sha256: str
    targets: tuple[tuple[str, Box], ...]
    diagnostics: dict[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


def _crop(frame: np.ndarray, box: Box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return frame[y0:y1, x0:x1]


def _text(frame: np.ndarray, box: Box, *, psm: int = 6) -> str:
    crop = cv2.resize(_crop(frame, box), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    value = pytesseract.image_to_string(crop, config=f"--psm {psm}")
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def _ocr_boxes(frame: np.ndarray) -> list[tuple[str, Box]]:
    enlarged = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box]] = []
    for index, raw in enumerate(data["text"]):
        text = " ".join(str(raw).casefold().split())
        if not text:
            continue
        x = int(data["left"][index]) // 3
        y = int(data["top"][index]) // 3
        width = max(1, int(data["width"][index]) // 3)
        height = max(1, int(data["height"][index]) // 3)
        found.append((text, (x, y, min(800, x + width), min(1280, y + height))))
    return found


def _gold_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([8, 70, 100], dtype=np.uint8), np.array([42, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(mask)) / float(mask.size)


def _red_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array([0, 80, 60], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
    high = cv2.inRange(hsv, np.array([165, 80, 60], dtype=np.uint8), np.array([179, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(cv2.bitwise_or(low, high))) / float(low.size)


def _attempts(text: str) -> int | None:
    match = _ATTEMPTS_RE.search(text)
    return int(match.group(1)) if match else None


def recognize_nova_frame(
    frame: np.ndarray,
    *,
    captured_monotonic: float | None = None,
    stale: bool = False,
) -> NovaFrameRecognition:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Nova frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    header = _text(frame, NOVA_HEADER_ROI, psm=11)
    menu_text = _text(frame, LAB_MENU_ROI)
    nova_text = _text(frame, NOVA_BODY_ROI)
    attempts_text = _text(frame, NOVA_ATTEMPTS_ROI)
    cooldown_text = _text(frame, NOVA_COOLDOWN_ROI)
    diagnostics: dict[str, object] = {
        "header_text": header,
        "menu_text": menu_text,
        "nova_text": nova_text,
        "attempts_text": attempts_text,
        "cooldown_text": cooldown_text,
        "lab_gold_ratio": _gold_ratio(frame, RESEARCH_LAB_ROI),
        "praise_red_ratio": _red_ratio(frame, NOVA_PRAISE_ROI),
    }
    is_nova = "nova" in header and ("skill" in nova_text or "praise" in nova_text or "interaction" in attempts_text)
    lab_identity = "research lab" in menu_text or "research lab" in _text(frame, RESEARCH_LAB_ROI)
    if is_nova:
        remaining = _attempts(attempts_text)
        cooldown_seconds = parse_cooldown_seconds(cooldown_text)
        praise_label = "praise" in _text(frame, NOVA_PRAISE_ROI)
        enabled = praise_label and _red_ratio(frame, NOVA_PRAISE_ROI) >= 0.08 and cooldown_seconds in (None, 0)
        targets = ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),) if enabled else ()
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_SCREEN,
                research_lab_identity=True,
                nova_control_visible=False,
                selected_nova=True,
                praise_enabled=enabled,
                praise_target_identity=NOVA_PRAISE_TARGET if praise_label else "",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=remaining,
                cooldown_text=cooldown_text,
                cooldown_active=bool(cooldown_seconds and cooldown_seconds > 0),
                cooldown_seconds=cooldown_seconds,
                next_eligible_at=(
                    captured_monotonic + cooldown_seconds
                    if captured_monotonic is not None and cooldown_seconds and cooldown_seconds > 0
                    else None
                ),
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=remaining is not None and praise_label,
            ),
            digest,
            targets,
            diagnostics,
        )
    menu_boxes = _ocr_boxes(frame)
    nova_box = next((box for text, box in menu_boxes if text.startswith("nova")), None)
    menu_signature = "details" in nova_text and "upgrade" in nova_text and "bioenhancer" in nova_text
    if menu_signature and nova_box is not None:
        x0, y0, x1, y1 = nova_box
        nova_target = (max(0, x0 - 45), max(0, y0 - 100), min(800, x1 + 45), min(1280, y1 + 20))
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_LAB_MENU,
                research_lab_identity=True,
                nova_control_visible=True,
                selected_nova=False,
                praise_enabled=False,
                praise_target_identity="",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=None,
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=True,
            ),
            digest,
            ((NOVA_INTERACTION_TARGET, nova_target),),
            diagnostics,
        )
    home_text = _text(frame, (0, 0, 800, 1280), psm=11)
    if "research lab" in home_text:
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_HOME,
                research_lab_identity=True,
                nova_control_visible=False,
                selected_nova=False,
                praise_enabled=False,
                praise_target_identity="",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=None,
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=True,
            ),
            digest,
            (("research-lab-building", RESEARCH_LAB_ROI),),
            diagnostics,
        )
    return NovaFrameRecognition(
        NovaPraiseObservation(
            screen_state="UNKNOWN",
            research_lab_identity=False,
            nova_control_visible=False,
            selected_nova=False,
            praise_enabled=False,
            praise_target_identity="",
            praise_target_roi=NOVA_PRAISE_ROI,
            attempts_remaining=None,
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
            stale=stale,
            recognized=False,
        ),
        digest,
        (),
        diagnostics,
    )
