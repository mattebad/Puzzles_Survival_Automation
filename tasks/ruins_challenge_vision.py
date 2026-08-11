"""Native 800x1280 Ruins Challenge vision adapter.

This adapter only recognizes and binds targets.  It never dispatches input.  OCR is constrained to
the Ruins header/list and explicit forbidden controls are treated as blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Mapping

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsScreenObservation,
    RuinsDetailObservation,
    RuinsResult,
    RuinsResultObservation,
)


PROFILE_SIZE = (800, 1280)
Box = tuple[int, int, int, int]
Target = tuple[str, Box]
_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_POINTS_RE = re.compile(r"\b(\d{2,7})\b")
_DAY_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", re.IGNORECASE)


def _normalized(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def parse_progress(text: str) -> tuple[int, int] | None:
    match = _PROGRESS_RE.search(text.replace("O", "0"))
    if not match:
        return None
    current, maximum = int(match.group(1)), int(match.group(2))
    return (current, maximum) if maximum > 0 and current <= maximum else None


def parse_points(text: str) -> int | None:
    candidates = [int(item) for item in _POINTS_RE.findall(text.replace(",", ""))]
    return max(candidates) if candidates else None


def _ocr(frame: np.ndarray, box: Box | None = None, *, psm: int = 11) -> str:
    image = frame if box is None else frame[box[1]:box[3], box[0]:box[2]]
    enlarged = cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return _normalized(pytesseract.image_to_string(enlarged, config=f"--psm {psm}"))


def _ocr_boxes(frame: np.ndarray) -> list[tuple[str, Box]]:
    enlarged = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box]] = []
    for index, raw in enumerate(data["text"]):
        text = _normalized(raw)
        if not text:
            continue
        x = int(data["left"][index]) // 3
        y = int(data["top"][index]) // 3
        w = max(1, int(data["width"][index]) // 3)
        h = max(1, int(data["height"][index]) // 3)
        found.append((text, (x, y, min(800, x + w), min(1280, y + h))))
    return found


def recognize_navigation_chat_screen(frame: np.ndarray) -> bool:
    """Recognize the exact full-screen Chat surface used for one safe Back recovery."""

    if frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins recognition requires native 800x1280 frame")
    header = _ocr(frame, (0, 0, 800, 245), psm=11).lower()
    return (
        "chat" in header
        and "alliance" in header
        and ("whisper" in header or "state" in header)
        and "alliance bulletin" in header
    )


def _green_ratio(frame: np.ndarray, box: Box) -> float:
    crop = frame[box[1]:box[3], box[0]:box[2]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 80, 80], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])


def _green_target(frame: np.ndarray, box: Box) -> Box | None:
    crop = frame[box[1]:box[3], box[0]:box[2]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 80, 80], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 120:
        return None
    x, y, width, height = cv2.boundingRect(contour)
    return (
        max(0, box[0] + x - 20),
        max(0, box[1] + y - 20),
        min(800, box[0] + x + width + 20),
        min(1280, box[1] + y + height + 20),
    )


def _expanded(box: Box, *, x_pad: int, y_pad: int) -> Box:
    return (
        max(0, box[0] - x_pad),
        max(0, box[1] - y_pad),
        min(800, box[2] + x_pad),
        min(1280, box[3] + y_pad),
    )


def recognize_ruins_frame(frame: np.ndarray, *, reset_identity: str | None = None) -> "RuinsFrameRecognition":
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    full_text = _ocr(frame)
    header = _ocr(frame, (0, 0, 800, 120), psm=7)
    is_ruins = "uins challenge" in header or "uins challenge" in full_text
    is_home = not is_ruins and "headquarters" in full_text and "uins" in full_text
    targets: list[Target] = []
    diagnostics: dict[str, object] = {"full_text": full_text, "header_text": header}
    if is_home:
        home_boxes = _ocr_boxes(frame)
        ruins_box = next((box for text, box in home_boxes if text.endswith("uins")), None)
        if ruins_box is None:
            return RuinsFrameRecognition(
                RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN,
                                       RuinsControlState.UNKNOWN, (), "unknown", digest, reset_identity), digest, (), diagnostics)
        x0, y0, x1, y1 = ruins_box
        targets.append(("ruins-building", (max(0, x0 - 90), max(0, y0 - 160), min(800, x1 + 90), min(1280, y1 + 10))))
        return RuinsFrameRecognition(
            RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN,
                                   RuinsControlState.HIDDEN, (), "none", digest, reset_identity,
                                   home_base_recognized=True, ruins_building_recognized=True,
                                   safe_back_control=RuinsControlState.HIDDEN), digest, tuple(targets), diagnostics)
    if not is_ruins:
        return RuinsFrameRecognition(
            RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN,
                                   RuinsControlState.UNKNOWN, (), "unknown", digest, reset_identity), digest, (), diagnostics)

    points = parse_points(_ocr(frame, (0, 100, 180, 210), psm=7))
    control_text = _ocr(frame, (150, 100, 800, 210), psm=6)
    for label, identity in (("exchange", "exchange"), ("progress", "progress"), ("total rank", "total-rank")):
        if label in control_text:
            targets.append((identity, (150, 100, 800, 210)))
    boxes = _ocr_boxes(frame)
    rows: list[RuinsChallengeRow] = []
    lower_text = full_text
    for identity in KNOWN_CHALLENGE_IDENTITIES:
        needle = _normalized(identity)
        matches = [(text, box) for text, box in boxes if needle.split()[0] in text or needle in text]
        if not matches and needle not in lower_text:
            continue
        _, anchor = matches[0] if matches else (identity, (18, 220, 780, 420))
        y = anchor[1]
        row_box = (18, max(210, y - 60), 780, min(1280, y + 180))
        row_text = _ocr(frame, row_box, psm=6)
        progress = parse_progress(row_text) or (0, 1)
        day_match = _DAY_RE.search(row_text)
        day = day_match.group(1).title() if day_match else None
        locked = "requires lv" in row_text or "headquarters" in row_text and "requires" in row_text
        button_box = (560, max(0, row_box[1]), 780, min(1280, row_box[3]))
        button_text = _ocr(frame, button_box, psm=7)
        challenge_visible = "challenge" in button_text and not locked
        if locked:
            availability, control = RuinsAvailability.LOCKED, RuinsControlState.HIDDEN
        elif challenge_visible:
            availability, control = RuinsAvailability.AVAILABLE, RuinsControlState.VISIBLE_ENABLED
            targets.append((f"challenge:{identity}", (560, max(0, row_box[1]), 780, min(1280, row_box[3]))))
        else:
            availability, control = RuinsAvailability.UNAVAILABLE, RuinsControlState.HIDDEN
        green = _green_ratio(frame, (580, row_box[1], 780, row_box[3]))
        chest = RuinsChestState.AVAILABLE if green >= 0.08 and not locked and not challenge_visible else RuinsChestState.UNKNOWN
        if chest == RuinsChestState.AVAILABLE:
            chest_target = _green_target(frame, (580, row_box[1], 780, row_box[3]))
            if chest_target is not None:
                targets.append((f"chest:{identity}", chest_target))
        rows.append(RuinsChallengeRow(identity, day, availability, progress[0], progress[1], None, control, chest,
                                      row_box, None, False, False, False, None, None, None, None, digest,
                                      reset_identity, True))
    diagnostics["known_rows"] = [row.identity for row in rows]
    forbidden = tuple(word for word in ("exchange", "mall", "buy", "purchase", "ticket") if word in full_text)
    return RuinsFrameRecognition(
        RuinsScreenObservation(True, "RUINS_CHALLENGE", True, points,
                               RuinsControlState.VISIBLE_ENABLED if "exchange" in control_text else RuinsControlState.UNKNOWN,
                               RuinsControlState.VISIBLE_ENABLED if "progress" in control_text else RuinsControlState.UNKNOWN,
                               RuinsControlState.VISIBLE_ENABLED if "total rank" in control_text else RuinsControlState.UNKNOWN,
                               tuple(rows), "none", digest, reset_identity,
                               safe_back_control=RuinsControlState.VISIBLE_ENABLED,
                               forbidden_controls_seen=forbidden),
        digest, tuple(targets), diagnostics)


@dataclass(frozen=True)
class RuinsFrameRecognition:
    observation: RuinsScreenObservation
    frame_sha256: str
    targets: tuple[Target, ...]
    diagnostics: Mapping[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


@dataclass(frozen=True)
class RuinsDetailRecognition:
    observation: RuinsDetailObservation
    frame_sha256: str
    targets: tuple[Target, ...]
    diagnostics: Mapping[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


@dataclass(frozen=True)
class RuinsResultRecognition:
    observation: RuinsResultObservation
    frame_sha256: str
    targets: tuple[Target, ...]
    diagnostics: Mapping[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


@dataclass(frozen=True)
class RuinsRewardRecognition:
    recognized: bool
    identity: str
    medal_amount: int | None
    frame_sha256: str
    reset_identity: str | None
    targets: tuple[Target, ...]
    diagnostics: Mapping[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


def recognize_ruins_detail_frame(
    frame: np.ndarray,
    identity: str,
    *,
    reset_identity: str | None = None,
) -> RuinsDetailObservation:
    """Recognize a single challenge detail screen and its zero-cost controls."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins detail frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    text = _normalized(_ocr(frame))
    normalized_identity = _normalized(identity)
    floor_match = re.search(r"floor\s*(\d+)\s*/\s*(\d+)", text)
    floor_current, floor_maximum = (int(floor_match.group(1)), int(floor_match.group(2))) if floor_match else (0, 0)
    forbidden = any(word in text for word in ("exchange", "mall", "buy", "purchase", "ticket", "premium"))
    attack = "attack" in text and not forbidden
    dispatch = "dispatch" in text and not forbidden
    npc_match = re.search(r"(\d{3,})\s*/\s*(\d{3,})", text)
    npc_current, npc_maximum = ((int(npc_match.group(1)), int(npc_match.group(2))) if npc_match else (None, None))
    return RuinsDetailObservation(
        identity=identity,
        recognized=bool(
            (normalized_identity in text and floor_match is not None and "challenge" in text)
            or (dispatch and "npc troops" in text and npc_match is not None)
        ),
        floor_current=floor_current,
        floor_maximum=floor_maximum,
        attack_control=RuinsControlState.VISIBLE_ENABLED if attack else RuinsControlState.HIDDEN,
        dispatch_control=RuinsControlState.VISIBLE_ENABLED if dispatch else RuinsControlState.HIDDEN,
        npc_troops_provided="npc troops" in text,
        npc_troops_current=npc_current,
        npc_troops_maximum=npc_maximum,
        skip_battle_enabled="skip battle" in text,
        resource_cost=0 if "resource cost" not in text else parse_points(text),
        overlay_state="unknown" if "loading" in text or "confirm" in text else "none",
        source_frame_sha256=digest,
        reset_identity=reset_identity,
    )


def recognize_ruins_detail_with_targets(
    frame: np.ndarray,
    identity: str,
    *,
    reset_identity: str | None = None,
) -> RuinsDetailRecognition:
    observation = recognize_ruins_detail_frame(frame, identity, reset_identity=reset_identity)
    boxes = _ocr_boxes(frame)
    targets: list[Target] = []
    for text, box in boxes:
        normalized = _normalized(text)
        if normalized == "attack" and observation.attack_control == RuinsControlState.VISIBLE_ENABLED:
            targets.append(("ruins-attack", _expanded(box, x_pad=90, y_pad=35)))
        if normalized == "dispatch" and observation.dispatch_control == RuinsControlState.VISIBLE_ENABLED:
            targets.append(("ruins-dispatch", _expanded(box, x_pad=90, y_pad=35)))
    return RuinsDetailRecognition(
        observation,
        observation.source_frame_sha256,
        tuple(targets),
        {"ocr_boxes": boxes},
    )


def recognize_ruins_result_frame(
    frame: np.ndarray,
    identity: str,
    *,
    before_progress: int | None = None,
    reset_identity: str | None = None,
) -> RuinsResultObservation:
    """Recognize explicit success/failure terminals; unknown results remain ambiguous."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins result frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    text = _normalized(_ocr(frame))
    success = any(token in text for token in ("winner", "victory", "loot", "successful"))
    failure = "lose" in text or "defeated" in text or "defeat" in text
    progress = parse_progress(text)
    result = RuinsResult.SUCCESS if success and not failure else RuinsResult.FAILURE if failure and not success else RuinsResult.AMBIGUOUS
    if result == RuinsResult.SUCCESS and before_progress is not None and progress and progress[0] <= before_progress:
        result = RuinsResult.AMBIGUOUS
    return RuinsResultObservation(
        identity=identity,
        result=result,
        progress_after=progress[0] if progress else None,
        maximum_after=progress[1] if progress else None,
        level_after=progress[0] if progress else None,
        source_frame_sha256=digest,
        reset_identity=reset_identity,
        explicit_success_text=success and not failure,
        explicit_failure_text=failure and not success,
        tap_to_continue_visible="tap to continue" in text or "tap continue" in text,
    )


def recognize_ruins_result_with_targets(
    frame: np.ndarray,
    identity: str,
    *,
    before_progress: int | None = None,
    reset_identity: str | None = None,
) -> RuinsResultRecognition:
    observation = recognize_ruins_result_frame(
        frame,
        identity,
        before_progress=before_progress,
        reset_identity=reset_identity,
    )
    boxes = _ocr_boxes(frame)
    targets: list[Target] = []
    if observation.tap_to_continue_visible:
        continue_box = next((box for text, box in boxes if "continue" in _normalized(text)), None)
        if continue_box is not None:
            targets.append(("ruins-result-continue", _expanded(continue_box, x_pad=140, y_pad=50)))
    return RuinsResultRecognition(
        observation,
        observation.source_frame_sha256,
        tuple(targets),
        {"ocr_boxes": boxes},
    )


def recognize_ruins_reward_frame(
    frame: np.ndarray,
    identity: str,
    *,
    reset_identity: str | None = None,
) -> RuinsRewardRecognition:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins reward frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    text = _normalized(_ocr(frame))
    boxes = _ocr_boxes(frame)
    claim_box = next((box for item, box in boxes if _normalized(item) == "claim"), None)
    recognized = bool(
        "ruins reward" in text
        and _normalized(identity) in text
        and "reward available" in text
        and claim_box is not None
        and not any(word in text for word in ("exchange", "mall", "purchase", "ticket", "premium"))
    )
    targets = (("ruins-reward-claim", _expanded(claim_box, x_pad=100, y_pad=35)),) if recognized and claim_box else ()
    return RuinsRewardRecognition(
        recognized,
        identity,
        parse_points(text),
        digest,
        reset_identity,
        targets,
        {"text": text, "ocr_boxes": boxes},
    )
