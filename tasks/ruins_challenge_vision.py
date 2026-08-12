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
# The retained native Gear row is consistently OCR'd as "bear challenge" by
# the stylized G.  Keep this as a narrow, identity-specific alias rather than
# loosening row recognition globally.
_IDENTITY_OCR_ALIASES = {"gear challenge": ("bear challenge", "ear challenge", "ear chatenge")}


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


_RUINS_ROW_HEIGHT = 190
_RUINS_ROW_ANCHOR_TOP_OFFSET = 24


def _row_box_from_identity_anchor(anchor: Box) -> Box:
    """Bind one native list row from its current-frame identity text anchor."""

    top = max(210, anchor[1] - _RUINS_ROW_ANCHOR_TOP_OFFSET)
    return (18, top, 780, min(1280, top + _RUINS_ROW_HEIGHT))


def _available_chest_target(frame: np.ndarray, row_box: Box) -> Box | None:
    """Bind a fully visible native green-and-gold Ruins chest in one exact row."""

    if row_box[3] - row_box[1] < _RUINS_ROW_HEIGHT:
        return None
    candidate = (600, row_box[1] + 5, 780, row_box[1] + 150)
    crop = frame[candidate[1]:candidate[3], candidate[0]:candidate[2]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    total = float(crop.shape[0] * crop.shape[1])
    green = float(cv2.countNonZero(cv2.inRange(
        hsv, np.array([35, 80, 80], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8),
    ))) / total
    warm = float(cv2.countNonZero(cv2.inRange(
        hsv, np.array([5, 35, 80], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8),
    ))) / total
    bright = float(cv2.countNonZero(cv2.inRange(
        hsv, np.array([0, 0, 145], dtype=np.uint8), np.array([179, 255, 255], dtype=np.uint8),
    ))) / total
    if green < 0.15 or warm < 0.25 or bright < 0.25:
        return None
    return candidate


def _orange_button_present(frame: np.ndarray, box: Box) -> bool:
    """Detect the native orange Challenge button when stylized OCR drops its label."""
    return _orange_button_target(frame, box) is not None


def _orange_button_target(frame: np.ndarray, box: Box) -> Box | None:
    crop = frame[box[1]:box[3], box[0]:box[2]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 70, 80], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if cv2.contourArea(contour) >= 3000 and 100 <= width <= 220 and 40 <= height <= 90:
            candidates.append(contour)
    if not candidates:
        return None
    x, y, width, height = cv2.boundingRect(max(candidates, key=cv2.contourArea))
    return (
        max(0, box[0] + x - 8),
        max(0, box[1] + y - 8),
        min(800, box[0] + x + width + 8),
        min(1280, box[1] + y + height + 8),
    )


_DETAIL_ATTACK_REGION: Box = (180, 1080, 620, 1270)


def _orange_detail_attack_target(frame: np.ndarray) -> Box | None:
    """Bind only the native bottom Attack button, never generic orange controls."""
    x0, y0, x1, y1 = _DETAIL_ATTACK_REGION
    crop = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 70, 80], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if (
            area >= 2000
            and 180 <= width <= 420
            and 45 <= height <= 130
            and x > 2
            and y > 2
            and x + width < crop.shape[1] - 2
            and y + height < crop.shape[0] - 2
        ):
            candidates.append((area, x, y, width, height))
    if not candidates:
        return None
    _area, x, y, width, height = max(candidates)
    return (
        max(0, x0 + x - 8),
        max(0, y0 + y - 8),
        min(800, x0 + x + width + 8),
        min(1280, y0 + y + height + 8),
    )


def _orange_detail_dispatch_target(frame: np.ndarray) -> Box | None:
    """Dispatch uses the same bounded bottom button geometry as Attack."""
    return _orange_detail_attack_target(frame)


def _expanded(box: Box, *, x_pad: int, y_pad: int) -> Box:
    return (
        max(0, box[0] - x_pad),
        max(0, box[1] - y_pad),
        min(800, box[2] + x_pad),
        min(1280, box[3] + y_pad),
    )


def _identity_matches(identity: str, text: str) -> bool:
    needle = _normalized(identity)
    return needle in text or any(alias in text for alias in _IDENTITY_OCR_ALIASES.get(needle, ()))


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

    points = parse_points(_ocr(frame, (40, 120, 175, 180), psm=7))
    control_text = _ocr(frame, (150, 100, 800, 210), psm=6)
    for label, identity in (("exchange", "exchange"), ("progress", "progress"), ("total rank", "total-rank")):
        if label in control_text:
            targets.append((identity, (150, 100, 800, 210)))
    boxes = _ocr_boxes(frame)
    rows: list[RuinsChallengeRow] = []
    lower_text = full_text
    for identity in KNOWN_CHALLENGE_IDENTITIES:
        needle = _normalized(identity)
        aliases = (needle, *_IDENTITY_OCR_ALIASES.get(needle, ()))
        matches = [
            (text, box)
            for text, box in boxes
            if any(alias.split()[0] in text or alias in text for alias in aliases)
        ]
        if not matches and not _identity_matches(identity, lower_text):
            continue
        _, anchor = matches[0] if matches else (identity, (18, 220, 780, 420))
        row_box = _row_box_from_identity_anchor(anchor)
        row_text = _ocr(frame, row_box, psm=6)
        progress = parse_progress(row_text) or (0, 1)
        day_match = _DAY_RE.search(row_text)
        day = day_match.group(1).title() if day_match else None
        locked = "requires lv" in row_text or "headquarters" in row_text and "requires" in row_text
        button_box = (560, max(0, row_box[3] - 120), 780, min(1280, row_box[3]))
        button_text = _ocr(frame, button_box, psm=7)
        challenge_visible = ("challenge" in button_text or _orange_button_present(frame, button_box)) and not locked
        if locked:
            availability, control = RuinsAvailability.LOCKED, RuinsControlState.HIDDEN
        elif challenge_visible:
            availability, control = RuinsAvailability.AVAILABLE, RuinsControlState.VISIBLE_ENABLED
            challenge_target = _orange_button_target(frame, button_box) or button_box
            targets.append((f"challenge:{identity}", challenge_target))
        else:
            availability, control = RuinsAvailability.UNAVAILABLE, RuinsControlState.HIDDEN
        chest_target = None if locked or challenge_visible else _available_chest_target(frame, row_box)
        chest = RuinsChestState.AVAILABLE if chest_target is not None else RuinsChestState.UNKNOWN
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
    detail_context = normalized_identity in text and floor_match is not None and "challenge" in text
    orange_button = _orange_detail_attack_target(frame)
    npc_match = re.search(r"(\d{3,})\s*/\s*(\d{3,})", text)
    npc_current, npc_maximum = ((int(npc_match.group(1)), int(npc_match.group(2))) if npc_match else (None, None))
    dispatch_context = bool(
        orange_button is not None
        and "npc troops" in text
        and npc_current is not None
        and npc_maximum is not None
        and npc_current == npc_maximum
        and "skip battle" in text
        and not forbidden
    )
    attack = ("attack" in text or (orange_button is not None and detail_context and not dispatch_context)) and not forbidden
    dispatch = dispatch_context and not forbidden
    return RuinsDetailObservation(
        identity=identity,
        recognized=bool(
            detail_context or dispatch_context
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
    orange_attack_target = _orange_detail_attack_target(frame) if observation.attack_control == RuinsControlState.VISIBLE_ENABLED else None
    if orange_attack_target is not None:
        targets.append(("ruins-attack", orange_attack_target))
    orange_dispatch_target = _orange_detail_dispatch_target(frame) if observation.dispatch_control == RuinsControlState.VISIBLE_ENABLED else None
    if orange_dispatch_target is not None:
        targets.append(("ruins-dispatch", orange_dispatch_target))
    for text, box in boxes:
        normalized = _normalized(text)
        if normalized == "attack" and observation.attack_control == RuinsControlState.VISIBLE_ENABLED and orange_attack_target is None:
            targets.append(("ruins-attack", _expanded(box, x_pad=90, y_pad=35)))
        if normalized == "dispatch" and observation.dispatch_control == RuinsControlState.VISIBLE_ENABLED and orange_dispatch_target is None:
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
    claim_box = next((box for item, box in boxes if _normalized(item) == "claim" and box[1] >= 680), None)
    if claim_box is None:
        region = (180, 650, 620, 820)
        crop = frame[region[1]:region[3], region[0]:region[2]]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 70, 80], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if cv2.contourArea(contour) >= 10000 and 200 <= width <= 360 and 55 <= height <= 120:
                candidates.append((cv2.contourArea(contour), x, y, width, height))
        if candidates:
            _area, x, y, width, height = max(candidates)
            claim_box = (
                max(0, region[0] + x - 8), max(0, region[1] + y - 8),
                min(800, region[0] + x + width + 8), min(1280, region[1] + y + height + 8),
            )
    recognized = bool(
        _normalized(identity) in text
        and "reward available" in text
        and "can claim once a week" in text
        and claim_box is not None
        and not any(word in text for word in ("exchange", "mall", "purchase", "ticket", "premium"))
    )
    targets = (("ruins-reward-claim", claim_box),) if recognized and claim_box else ()
    return RuinsRewardRecognition(
        recognized,
        identity,
        parse_points(text),
        digest,
        reset_identity,
        targets,
        {"text": text, "ocr_boxes": boxes},
    )


def recognize_any_ruins_reward_frame(
    frame: np.ndarray,
    *,
    reset_identity: str | None = None,
) -> RuinsRewardRecognition:
    """Recognize exactly one current Ruins reward identity without repeated OCR scans."""

    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Ruins reward frame must be a native 800x1280 image")
    text = _normalized(_ocr(frame))
    identities = [identity for identity in KNOWN_CHALLENGE_IDENTITIES if _normalized(identity) in text]
    if len(identities) != 1:
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        return RuinsRewardRecognition(False, "unknown", None, digest, reset_identity, (), {"text": text})
    return recognize_ruins_reward_frame(frame, identities[0], reset_identity=reset_identity)
