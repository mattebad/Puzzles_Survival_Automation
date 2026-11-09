"""Native, source-bound Hall of War → Zombie Zero route."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from safe_action_core import ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, NATIVE_HEIGHT, NATIVE_WIDTH
from scripts.bounded_tesseract import call_ocr, tesseract_data, tesseract_string
from scripts.home_atlas_bluestacks import (
    BlueStacksHomeLocalizer,
    BlueStacksLocalizeFirstHomeDriver,
    HomeDriverDisposition,
    ScrcpyMotionEventZoomTransport,
    bind_visible_building,
    identity_from_captured,
    load_home_atlas,
)
from scripts.navigation_development_boundary import (
    NavigationRouteDeclaration,
    NavigationGuardedRuntime,
    make_source_safety_facts,
)
from scripts.startup_normalization import is_clean_home_frame
from tasks.hall_of_war import (
    Action,
    AttemptState,
    ChallengeObservation,
    FLOW_ID,
    PRODUCT_ID,
    PRODUCT_REVISION,
    REWARD_ACTION,
    REWARD_CONSEQUENCE,
    REWARD_POSTCONDITION,
    REWARD_SOURCE,
    REWARD_TARGET,
    RewardObservation,
    RewardState,
    DISPATCH_ACTION,
    DISPATCH_CONSEQUENCE,
    DISPATCH_POSTCONDITION,
    DISPATCH_SOURCE,
    DISPATCH_TARGET,
    action_key,
    aggregate_action_count,
    plan_dispatch,
    plan_reward,
    dispatch_policy_preconditions,
    reward_policy_preconditions,
)
from tasks.home_atlas import BuildingBinding
from tasks.home_context import HomeReadyObservation
from tasks.radial_semantics import (
    ActionabilityState,
    ControlRole,
    HomeRadialSemantics,
    OwningFacilityObservation,
    RadialAmbiguityState,
    RadialControlObservation,
    RecognitionState,
)
from tasks.runtime_identity import (
    VerifiedRuntimeIdentity,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity
from automation_service.registry import HALL_OF_WAR_MAX_INPUTS, HALL_OF_WAR_PROFILE_ID


HALL_OF_WAR_ATLAS_BUILDING_ID = "home.building.hall_of_war"
HALL_OF_WAR_RADIAL_ID = "home.radial.hall_of_war"
HALL_OF_WAR_RADIAL_TARGET = "hall-of-war-radial-zombie-zero"
ATTACK_TARGET = "hall-of-war-zombie-zero-attack"
FORMATION_ARROW_TARGET = "hall-of-war-troop-set-selector"
TROOP_SET_ONE_TARGET = "hall-of-war-troop-set-1"
RESULT_CONFIRM_TARGET = "hall-of-war-zombie-zero-result-confirm"
HOME_ATLAS_PAN_TARGET = "hall-of-war-home-atlas-pan"
HOME_ZOOM_TARGET = "home-zoom-out"
HOME_BACK_TARGET = "system-back"
MAX_INPUTS = HALL_OF_WAR_MAX_INPUTS
MAX_ACTIONS = 3
PROFILE_ID = HALL_OF_WAR_PROFILE_ID


class HallOfWarRouteError(RuntimeError):
    """A current Hall of War observation failed a route-specific evidence gate."""


@dataclass(frozen=True)
class OCRToken:
    text: str
    roi: tuple[int, int, int, int]
    confidence: float | None


@dataclass(frozen=True)
class BoundTarget:
    target_identity: str
    target_roi: tuple[int, int, int, int]


@dataclass(frozen=True)
class ZombieZeroMenu:
    """Exact current Zombie Zero menu labels read from one native frame."""

    title_roi: tuple[int, int, int, int]
    damage_roi: tuple[int, int, int, int]
    today_highest_damage: int | None
    reward_header: str
    reward_header_roi: tuple[int, int, int, int]
    footer_text: tuple[str, ...]
    attack: BoundTarget | None


class HallOfWarVision:
    """OCR/geometry recognizers for the exact observed Hall of War UI surfaces."""

    # Measured outer borders of the five Dispatch hero cards (native saved
    # Troop Set 1 capture; empty "+" slots share the same frames).
    _HERO_RECTS = (
        (56, 157, 170, 271), (201, 118, 315, 233), (343, 118, 457, 233),
        (483, 118, 598, 233), (629, 157, 743, 271),
    )

    @staticmethod
    def _normal(value: object) -> str:
        folded = unicodedata.normalize("NFKD", str(value).casefold())
        return " ".join("".join(ch for ch in folded if not unicodedata.combining(ch)).split())

    @staticmethod
    def _native(frame: np.ndarray) -> bool:
        return isinstance(frame, np.ndarray) and frame.shape == (NATIVE_HEIGHT, NATIVE_WIDTH, 3)

    def tokens(self, frame: np.ndarray, roi: tuple[int, int, int, int] | None = None) -> tuple[OCRToken, ...]:
        if not self._native(frame):
            return ()
        x0, y0, x1, y1 = roi or (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)
        if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
            return ()
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return ()
        scale = 2.0
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            data = call_ocr(tesseract_data, enlarged, config="--psm 11")
        except (RuntimeError, OSError, ValueError):
            return ()
        texts = data.get("text", ())
        lefts, tops = data.get("left", ()), data.get("top", ())
        widths, heights = data.get("width", ()), data.get("height", ())
        confidences = data.get("conf", ())
        count = min(len(texts), len(lefts), len(tops), len(widths), len(heights))
        found: list[OCRToken] = []
        for index in range(count):
            text = self._normal(texts[index])
            if not text:
                continue
            try:
                left = round(float(lefts[index]) / scale) + x0
                top = round(float(tops[index]) / scale) + y0
                width = round(float(widths[index]) / scale)
                height = round(float(heights[index]) / scale)
                confidence = float(confidences[index]) if index < len(confidences) and str(confidences[index]).strip() else None
            except (TypeError, ValueError):
                continue
            box = (max(0, left), max(0, top), min(NATIVE_WIDTH, left + width), min(NATIVE_HEIGHT, top + height))
            if box[0] < box[2] and box[1] < box[3]:
                found.append(OCRToken(text, box, confidence))
        return tuple(found)

    def text(self, frame: np.ndarray, roi: tuple[int, int, int, int] | None = None) -> str:
        return " ".join(token.text for token in self.tokens(frame, roi))

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        return f" {HallOfWarVision._normal(text)} ".find(f" {HallOfWarVision._normal(phrase)} ") >= 0

    def _phrase_boxes(self, frame: np.ndarray, phrase: str) -> tuple[tuple[int, int, int, int], ...]:
        wanted = self._normal(phrase).split()
        tokens = self.tokens(frame)
        words: list[tuple[str, tuple[int, int, int, int]]] = []
        for token in tokens:
            for word in token.text.split():
                words.append((word, token.roi))
        matches: list[tuple[int, int, int, int]] = []
        for start in range(max(0, len(words) - len(wanted) + 1)):
            selected = words[start:start + len(wanted)]
            if [item[0] for item in selected] != wanted:
                continue
            centers = [((box[1] + box[3]) // 2) for _, box in selected]
            if max(centers) - min(centers) > 55:
                continue
            boxes = [box for _, box in selected]
            matches.append((min(box[0] for box in boxes), min(box[1] for box in boxes),
                            max(box[2] for box in boxes), max(box[3] for box in boxes)))
        # Deduplicate OCR word grouping that emits the same geometry more than once.
        return tuple(dict.fromkeys(matches))

    @staticmethod
    def _visual_button(frame: np.ndarray, roi: tuple[int, int, int, int]) -> bool:
        x0, y0, x1, y1 = roi
        patch = frame[y0:y1, x0:x1]
        if patch.size == 0:
            return False
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        edges = cv2.Canny(gray, 60, 160)
        orange = cv2.inRange(hsv, (5, 70, 90), (38, 255, 255))
        return float(np.count_nonzero(edges)) / edges.size >= 0.003 or float(np.count_nonzero(orange)) / orange.size >= 0.035

    def _padded_target(self, frame: np.ndarray, box: tuple[int, int, int, int], identity: str,
                       padding: tuple[int, int] = (22, 18)) -> BoundTarget | None:
        x0, y0, x1, y1 = box
        px, py = padding
        roi = (max(0, x0 - px), max(0, y0 - py), min(NATIVE_WIDTH, x1 + px), min(NATIVE_HEIGHT, y1 + py))
        if not self._visual_button(frame, roi):
            return None
        return BoundTarget(identity, roi)

    def bind_text_target(self, frame: np.ndarray, phrase: str, identity: str, *, padding: tuple[int, int] = (22, 18)) -> BoundTarget | None:
        boxes = self._phrase_boxes(frame, phrase)
        if len(boxes) != 1:
            return None
        return self._padded_target(frame, boxes[0], identity, padding)

    # Hall surfaces draw their labels over busy, animated art (Home radial
    # captions, the Zombie Zero boss portrait), where sparse full-frame OCR
    # interleaves or drops them. Labels are therefore read as isolated text
    # lines of one known colour inside a bounded band.
    _WHITE_TEXT = ((0, 0, 200), (180, 50, 255))
    _GOLD_TEXT = ((10, 90, 150), (30, 200, 255))
    _MAX_TEXT_LINES = 24
    _RADIAL_ENVELOPE = (300, 60, 230)  # |dx|, pixels above, pixels below the bound anchor

    def _text_lines(self, frame: np.ndarray, band: tuple[int, int, int, int],
                    colour: tuple[tuple[int, int, int], tuple[int, int, int]]) -> tuple[OCRToken, ...] | None:
        if not self._native(frame):
            return None
        x0, y0, x1, y1 = band
        if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
            return None
        low, high = colour
        mask = cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), low, high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        boxes = [
            (x0 + int(left), y0 + int(top), x0 + int(left + width), y0 + int(top + height))
            for left, top, width, height, area in stats[1:count]
            if 12 <= height <= 34 and width >= 20 and area >= 120
        ]
        if len(boxes) > self._MAX_TEXT_LINES:
            return None
        lines: list[OCRToken] = []
        for box in boxes:
            text = self._read_isolated(frame, (max(0, box[0] - 4), max(0, box[1] - 4),
                                               min(NATIVE_WIDTH, box[2] + 4), min(NATIVE_HEIGHT, box[3] + 4)), colour)
            if text is None:
                return None
            if text:
                lines.append(OCRToken(text, box, None))
        return tuple(lines)

    def _read_isolated(self, frame: np.ndarray, box: tuple[int, int, int, int],
                       colour: tuple[tuple[int, int, int], tuple[int, int, int]]) -> str | None:
        # Read only the box's own strokes of one colour (plus their
        # anti-aliased edge): animated art inside the box (bobbing quest
        # markers) otherwise makes Tesseract drop an unchanged label.
        x0, y0, x1, y1 = box
        strokes = cv2.dilate(
            cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), *colour),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        )
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        isolated = (255 - np.where(strokes > 0, gray, 0)).astype(np.uint8)
        enlarged = cv2.resize(isolated, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        try:
            return self._normal(call_ocr(tesseract_string, enlarged, config="--psm 7"))
        except (RuntimeError, OSError, ValueError):
            return None

    def _radial_caption_lines(self, frame: np.ndarray, anchor: tuple[float, float]) -> tuple[OCRToken, ...] | None:
        # The opened radial covers the Hall's own title; its captions are read
        # around the freshly Atlas-bound Hall interaction anchor.
        ax, ay = int(round(anchor[0])), int(round(anchor[1]))
        reach, above, below = self._RADIAL_ENVELOPE
        band = (max(0, ax - reach), max(0, ay - above), min(NATIVE_WIDTH, ax + reach), min(NATIVE_HEIGHT, ay + below))
        return self._text_lines(frame, band, self._WHITE_TEXT)

    def radial_captions(self, frame: np.ndarray, anchor: tuple[float, float]) -> dict[str, tuple[int, int, int, int]] | None:
        """Exact, unique Hall radial captions arranged around the bound Hall anchor."""
        lines = self._radial_caption_lines(frame, anchor)
        if lines is None:
            return None
        found: dict[str, list[tuple[int, int, int, int]]] = {}
        for line in lines:
            found.setdefault(line.text, []).append(line.roi)

        def single(word: str) -> tuple[int, int, int, int] | None:
            boxes = found.get(word, [])
            return boxes[0] if len(boxes) == 1 else None

        def stacked(first: str, second: str) -> tuple[int, int, int, int] | None:
            upper, lower = single(first), single(second)
            if upper is None or lower is None:
                return None
            gap = lower[1] - upper[3]
            height = max(upper[3] - upper[1], lower[3] - lower[1])
            if not 0 <= gap <= height or abs((upper[0] + upper[2]) - (lower[0] + lower[2])) > 24:
                return None
            return (min(upper[0], lower[0]), upper[1], max(upper[2], lower[2]), lower[3])

        details = single("details")
        upgrade = single("upgrade")
        military = stacked("military", "operation")
        zombie = stacked("zombie", "zero")
        if details is None or upgrade is None or military is None or zombie is None:
            return None
        captions = {
            "Details": details, "Upgrade": upgrade,
            "Military Operation": military, "Zombie Zero": zombie,
        }
        centers = [(box[0] + box[2]) / 2 for box in captions.values()]
        if not min(centers) < anchor[0] < max(centers):
            return None
        return captions

    def radial_target(self, frame: np.ndarray, captions: Mapping[str, tuple[int, int, int, int]] | None) -> BoundTarget | None:
        if not captions or "Zombie Zero" not in captions:
            return None
        return self._padded_target(frame, captions["Zombie Zero"], HALL_OF_WAR_RADIAL_TARGET)

    @staticmethod
    def same_hall_anchor(entry: BuildingBinding | None, current: BuildingBinding | None) -> bool:
        return bool(
            entry is not None and current is not None
            and entry.building_id == current.building_id == HALL_OF_WAR_ATLAS_BUILDING_ID
            and entry.screen_anchor is not None and current.screen_anchor is not None
            and abs(entry.screen_anchor[0] - current.screen_anchor[0]) <= 3.0
            and abs(entry.screen_anchor[1] - current.screen_anchor[1]) <= 3.0
        )

    def is_clean_home(self, frame: np.ndarray) -> bool:
        return self._native(frame) and is_clean_home_frame(frame)

    def radial_semantics(self, frame: np.ndarray, runtime, captured, *, entry: BuildingBinding | None,
                         current: BuildingBinding | None) -> HomeRadialSemantics | None:
        """Hall radial owned by the immediate-before Atlas Hall binding.

        The radial covers the Hall title, so ownership is the canonical Atlas
        Hall binding of the tapped entry, re-proved at the same anchor on this
        exact capture, plus the Hall-only caption set arranged around it.
        """
        if entry is None or current is None or not self.same_hall_anchor(entry, current):
            return None
        ordinal = getattr(runtime, "ordinal", None)
        if type(ordinal) is not int or ordinal < 1:
            return None
        identity = identity_from_captured(captured, session_id=str(runtime.session), ordinal=ordinal, label="hall-of-war-radial")
        if current.frame_sha256 != identity.semantic_sha256 or current.overlay_intersects or current.ambiguous_overlap:
            return None
        if current.screen_anchor is None:
            return None
        captions = self.radial_captions(frame, current.screen_anchor)
        target = self.radial_target(frame, captions)
        if target is None:
            return None
        confidence = float(current.confidence)
        owner = OwningFacilityObservation(
            identity, HALL_OF_WAR_ATLAS_BUILDING_ID, RecognitionState.RECOGNIZED, confidence,
            RadialAmbiguityState.NONE,
            ("immediate-before Atlas Hall of War entry binding",
             "same-capture Atlas Hall of War binding at the entry anchor",
             "Hall-only radial captions anchored to the bound Hall of War"),
        )
        control = RadialControlObservation(
            identity, "hall_of_war_zombie_zero", "Zombie Zero", ControlRole.PRIMARY_ACTION,
            RecognitionState.RECOGNIZED, confidence, ActionabilityState.ACTIONABLE,
            "exact route-owned Hall of War radial label and bound current target",
            ("facility.screen",), ("facility.upgrade", "facility.train_queue"),
            HALL_OF_WAR_ATLAS_BUILDING_ID, RadialAmbiguityState.NONE, ("exact stacked Zombie Zero caption",),
            {"target_roi": ",".join(str(value) for value in target.target_roi)},
        )
        return HomeRadialSemantics(
            identity, HALL_OF_WAR_RADIAL_ID, RecognitionState.RECOGNIZED, confidence,
            owner, (control,), RadialAmbiguityState.NONE,
            ("Hall of War owner binding, radial captions and target share one capture",),
            {"entry_frame_sha256": str(entry.frame_sha256)},
        )

    # Fixed native Zombie Zero menu bands. The large gold total above the
    # damage line is not white text and never matches the damage label.
    _MENU_TITLE_BAND = (0, 0, NATIVE_WIDTH, 80)
    _MENU_DAMAGE_BAND = (75, 730, 675, 875)
    _MENU_REWARD_BAND = (60, 860, 740, 960)
    _MENU_FOOTER_BAND = (40, 1080, 760, NATIVE_HEIGHT)
    _MENU_DAMAGE_LINE = re.compile(r"today[’']?s highest dmg(.*)")
    _MENU_DAMAGE_VALUE = re.compile(r"\s*:?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
    _MENU_REWARD_HEADERS = ("daily reward", "daily reward (claimed)")

    def zombie_zero_menu(self, frame: np.ndarray) -> ZombieZeroMenu | None:
        # Bands are read in order and stop at the first missing exact label,
        # so non-menu frames do not pay for every band's line OCR.
        title = self._text_lines(frame, self._MENU_TITLE_BAND, self._WHITE_TEXT)
        titles = [line.roi for line in title or () if line.text == "zombie zero"]
        if len(titles) != 1:
            return None
        damage = self._text_lines(frame, self._MENU_DAMAGE_BAND, self._WHITE_TEXT)
        damages = [(line.roi, match) for line in damage or () if (match := self._MENU_DAMAGE_LINE.fullmatch(line.text))]
        if len(damages) != 1:
            return None
        reward = self._text_lines(frame, self._MENU_REWARD_BAND, self._GOLD_TEXT)
        headers = [line for line in reward or () if line.text in self._MENU_REWARD_HEADERS]
        if len(headers) != 1:
            return None
        footer = self._text_lines(frame, self._MENU_FOOTER_BAND, self._WHITE_TEXT)
        if footer is None:
            return None
        damage_roi, label = damages[0]
        value = self._MENU_DAMAGE_VALUE.fullmatch(label.group(1))
        return ZombieZeroMenu(
            titles[0], damage_roi,
            int(value.group(1).replace(",", "")) if value is not None else None,
            headers[0].text, headers[0].roi,
            tuple(line.text for line in footer),
            self._attack_button(frame, footer),
        )

    def _gold_button(self, frame: np.ndarray, band: tuple[int, int, int, int], lines: tuple[OCRToken, ...],
                     label: str) -> tuple[int, int, int, int] | None:
        # The measured gold button that contains the one exact label line,
        # not a fixed coordinate.
        labels = [line.roi for line in lines if line.text == label]
        if len(labels) != 1:
            return None
        lx0, ly0, lx1, ly1 = labels[0]
        x0, y0, x1, y1 = band
        gold = cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), (8, 120, 120), (30, 255, 255))
        count, _, stats, _ = cv2.connectedComponentsWithStats(gold)
        buttons = [
            (x0 + int(left), y0 + int(top), x0 + int(left + width), y0 + int(top + height))
            for left, top, width, height, area in stats[1:count]
            if area >= 2000
        ]
        containing = [box for box in buttons if box[0] <= lx0 and box[1] <= ly0 and lx1 <= box[2] and ly1 <= box[3]]
        return containing[0] if len(containing) == 1 else None

    def _attack_button(self, frame: np.ndarray, footer: tuple[OCRToken, ...]) -> BoundTarget | None:
        button = self._gold_button(frame, self._MENU_FOOTER_BAND, footer, "attack")
        return None if button is None else BoundTarget(ATTACK_TARGET, button)

    def zombie_zero_page(self, frame: np.ndarray) -> bool:
        return self.zombie_zero_menu(frame) is not None

    def today_highest_damage(self, frame: np.ndarray) -> int | None:
        menu = self.zombie_zero_menu(frame)
        return None if menu is None else menu.today_highest_damage

    @staticmethod
    def _ready_attack(menu: ZombieZeroMenu) -> BoundTarget | None:
        # Any other footer text (timer, limit notice) withholds READY.
        return menu.attack if menu.footer_text == ("attack",) else None

    def attempt_state(self, frame: np.ndarray) -> AttemptState:
        menu = self.zombie_zero_menu(frame)
        if menu is None:
            return AttemptState.UNKNOWN
        text = " ".join((self._normal(self.text(frame)),) + menu.footer_text)
        if re.search(r"\b(?:cooldown|cooling down|in\s+\d)\b", text):
            return AttemptState.BUSY
        if self._ready_attack(menu) is not None:
            return AttemptState.READY
        if self._contains(text, "unavailable") or self._contains(text, "daily limit"):
            return AttemptState.UNAVAILABLE
        return AttemptState.UNKNOWN

    _DISPATCH_FOOTER_BAND = (40, 1140, 760, NATIVE_HEIGHT)

    def _dispatch_footer(self, frame: np.ndarray) -> tuple[str, tuple[int, int, int, int]] | None:
        # Formation page: exact "Dispatch" header plus exactly one measured
        # gold footer button holding "Quick Select" (empty) or "Dispatch"
        # (populated formation).
        title = self._text_lines(frame, self._MENU_TITLE_BAND, self._WHITE_TEXT)
        if len([line for line in title or () if line.text == "dispatch"]) != 1:
            return None
        footer = self._text_lines(frame, self._DISPATCH_FOOTER_BAND, self._WHITE_TEXT)
        if footer is None:
            return None
        found = [(label, button) for label in ("quick select", "dispatch")
                 if (button := self._gold_button(frame, self._DISPATCH_FOOTER_BAND, footer, label)) is not None]
        return found[0] if len(found) == 1 else None

    def _quick_select_button(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        footer = self._dispatch_footer(frame)
        return footer[1] if footer is not None and footer[0] == "quick select" else None

    def bind_dispatch(self, frame: np.ndarray) -> BoundTarget | None:
        # The measured gold footer button with the exact "Dispatch" label,
        # never the identical page title.
        footer = self._dispatch_footer(frame)
        return BoundTarget(DISPATCH_TARGET, footer[1]) if footer is not None and footer[0] == "dispatch" else None

    def dispatch_page(self, frame: np.ndarray) -> bool:
        return self._dispatch_footer(frame) is not None

    def bind_attack(self, frame: np.ndarray) -> BoundTarget | None:
        menu = self.zombie_zero_menu(frame)
        return None if menu is None else self._ready_attack(menu)

    def bind_formation_arrow(self, frame: np.ndarray) -> BoundTarget | None:
        # The selector is the one measured round chevron button immediately
        # left of the current Quick Select button, on the same row.
        button = self._quick_select_button(frame)
        if button is None:
            return None
        bx0, by0, _bx1, by1 = button
        x0, y0, x1, y1 = max(0, bx0 - 130), by0, bx0, by1
        if x1 - x0 < 40:
            return None
        gray = cv2.medianBlur(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), 3)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1.2, 30, param1=120, param2=25, minRadius=15, maxRadius=35)
        if circles is None or len(circles[0]) != 1:
            return None
        cx, cy, radius = (int(round(float(value))) for value in circles[0][0])
        roi = (x0 + cx - radius, y0 + cy - radius, x0 + cx + radius + 1, y0 + cy + radius + 1)
        if not (x0 <= roi[0] < roi[2] <= x1 and y0 <= roi[1] < roi[3] <= y1):
            return None
        disc = np.zeros(gray.shape, dtype=np.uint8)
        cv2.circle(disc, (cx, cy), max(1, radius - 4), 255, -1)
        chevron = cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), (10, 90, 140), (30, 220, 255))
        if np.count_nonzero(cv2.bitwise_and(chevron, disc)) < 60:
            return None
        return BoundTarget(FORMATION_ARROW_TARGET, roi)

    _SELECTOR_BAND = (40, 300, 760, 1160)
    _SELECTOR_ROW = ((0, 80, 70), (12, 255, 200))

    def _troop_set_rows(self, frame: np.ndarray) -> dict[int, tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] | None:
        """Bind the exact Set 1 row body separately from its excluded Edit control."""
        if not self._native(frame):
            return None
        x0, y0, x1, y1 = self._SELECTOR_BAND
        panel_mask = cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), *self._SELECTOR_ROW)
        count, _, stats, _ = cv2.connectedComponentsWithStats(panel_mask)
        panels = [
            (x0 + int(left), y0 + int(top), x0 + int(left + width), y0 + int(top + height))
            for left, top, width, height, area in stats[1:count]
            if 300 <= width <= 420 and 50 <= height <= 75 and area >= 0.75 * width * height
        ]
        # Other saved sets may be locked or unreadable; only Set 1 is required.
        if not panels or self.dispatch_page(frame):
            return None
        white = self._text_lines(frame, self._SELECTOR_BAND, self._WHITE_TEXT)
        gold = self._text_lines(frame, self._SELECTOR_BAND, self._GOLD_TEXT)
        if white is None or gold is None:
            return None

        def inside(roi: tuple[int, int, int, int], panel: tuple[int, int, int, int]) -> bool:
            return panel[0] <= roi[0] and roi[2] <= panel[2] and panel[1] <= roi[1] and roi[3] <= panel[3]

        rows: dict[int, tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = {}
        for panel in panels:
            edits = [line.roi for line in gold if line.text == "edit" and inside(line.roi, panel)]
            labels = [line.roi for line in white if line.text.startswith("troop set") and inside(line.roi, panel)]
            if not edits and not labels:
                continue  # locked VIP rows carry no Troop Set label or Edit control
            if len(edits) != 1 or len(labels) != 1 or labels[0][2] >= edits[0][0]:
                continue
            # The narrow set digit can sit apart from "Troop Set"; read the
            # label once from its measured start to the Edit control.
            text = self._read_isolated(frame, (labels[0][0] - 4, panel[1] + 6, edits[0][0] - 4, panel[3] - 6), self._WHITE_TEXT)
            match = re.fullmatch(r"troop set ([123])", text or "")
            if match is None:
                continue
            number = int(match.group(1))
            if number in rows:
                return None
            rows[number] = (panel, edits[0])
        return rows if 1 in rows else None

    def troop_set_selector(self, frame: np.ndarray) -> bool:
        return self._troop_set_rows(frame) is not None

    def bind_troop_set_one(self, frame: np.ndarray) -> BoundTarget | None:
        rows = self._troop_set_rows(frame)
        if rows is None:
            return None
        panel, edit = rows[1]
        # The row body up to, and excluding, its separate Edit control.
        roi = (panel[0], panel[1], edit[0] - 8, panel[3])
        return BoundTarget(TROOP_SET_ONE_TARGET, roi) if roi[2] - roi[0] >= 100 else None

    _HERO_BAND = (0, 100, NATIVE_WIDTH, 300)

    def _empty_hero_slot_centres(self, frame: np.ndarray) -> tuple[tuple[int, int], ...]:
        # Empty Dispatch hero slots show one glowing yellow "+" placeholder.
        x0, y0, x1, y1 = self._HERO_BAND
        yellow = cv2.inRange(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), (18, 90, 170), (40, 255, 255))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(yellow)
        centres: list[tuple[int, int]] = []
        for index in range(1, count):
            left, top, width, height, area = (int(value) for value in stats[index])
            if not (30 <= width <= 55 and 30 <= height <= 55 and abs(width - height) <= 8):
                continue
            if not 0.25 <= area / float(width * height) <= 0.55:
                continue
            shape = labels[top:top + height, left:left + width] == index
            corner = max(4, min(width, height) // 4)
            corners = (shape[:corner, :corner], shape[:corner, -corner:], shape[-corner:, :corner], shape[-corner:, -corner:])
            if not shape[height // 2, width // 2] or any(float(part.mean()) > 0.15 for part in corners):
                continue
            centres.append((x0 + left + width // 2, y0 + top + height // 2))
        return tuple(centres)

    def hero_count(self, frame: np.ndarray) -> int:
        if not self._native(frame):
            return 0
        empty = self._empty_hero_slot_centres(frame)
        count = 0
        for x0, y0, x1, y1 in self._HERO_RECTS:
            patch = frame[y0:y1, x0:x1]
            if patch.shape[:2] != (y1 - y0, x1 - x0):
                continue
            if any(x0 <= cx < x1 and y0 <= cy < y1 for cx, cy in empty):
                continue
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            edge_ratio = float(np.count_nonzero(cv2.Canny(gray, 60, 160))) / gray.size
            if float(np.std(gray)) >= 22.0 and edge_ratio >= 0.025:
                count += 1
        return count

    # Green footer fraction "current/capacity", below the troop rows.
    _TROOP_FOOTER_BAND = (40, 1080, 760, 1145)
    _GREEN_TEXT = ((40, 120, 150), (85, 255, 255))
    _TROOP_FRACTION = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})*)/([0-9]{1,3}(?:,[0-9]{3})*)")

    def troop_counts(self, frame: np.ndarray) -> tuple[int | None, int | None]:
        lines = self._text_lines(frame, self._TROOP_FOOTER_BAND, self._GREEN_TEXT)
        matches = [match for line in lines or () if (match := self._TROOP_FRACTION.fullmatch(line.text))]
        if len(matches) != 1:
            return None, None
        return int(matches[0].group(1).replace(",", "")), int(matches[0].group(2).replace(",", ""))


    @staticmethod
    def roi_sha256(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> str | None:
        if roi is None:
            return None
        x0, y0, x1, y1 = roi
        if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
            return None
        return hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()


    # White toast just below Clear Hero on the owned Dispatch page (native
    # saved Troop Set 1 capture: label at y367-394).
    _APPLIED_TOAST_BAND = (40, 330, 760, 470)

    def troop_set_one_applied(self, frame: np.ndarray) -> bool:
        if not self.dispatch_page(frame):
            return False
        toast = self._text_lines(frame, self._APPLIED_TOAST_BAND, self._WHITE_TEXT)
        anchors = [line.roi for line in toast or () if line.text.startswith("troop set")]
        if len(anchors) != 1:
            return False
        # The narrow set digit drops out as its own component; join the
        # anchor's same-row line components and read their envelope once.
        x0, y0, x1, y1 = anchors[0]
        centre = (y0 + y1) // 2
        for roi in sorted((line.roi for line in toast or ()), key=lambda roi: roi[0]):
            if roi[0] > x1 and roi[0] - x1 <= 60 and abs((roi[1] + roi[3]) // 2 - centre) <= 8:
                x1, y0, y1 = roi[2], min(y0, roi[1]), max(y1, roi[3])
        text = self._read_isolated(frame, (max(0, x0 - 4), max(0, y0 - 4), min(NATIVE_WIDTH, x1 + 4), min(NATIVE_HEIGHT, y1 + 4)),
                                   self._WHITE_TEXT)
        return text == "troop set 1 formation applied"

    def formation_signature(self, frame: np.ndarray) -> tuple[str, ...]:
        if not self._native(frame):
            return ()
        return tuple(hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
                     for x0, y0, x1, y1 in self._HERO_RECTS)

    def challenge_reward(self, frame: np.ndarray) -> RewardObservation | None:
        located = self._challenge_reward(frame)
        return None if located is None else located[0]

    def _challenge_reward(self, frame: np.ndarray) -> tuple[RewardObservation, tuple[int, int, int, int]] | None:
        menu = self.zombie_zero_menu(frame)
        if menu is None:
            return None
        # Historically observed claimed header: "Daily Reward (Claimed)".
        claimed = menu.reward_header == "daily reward (claimed)"
        header = menu.reward_header_roi
        y = (header[1] + header[3]) // 2
        x0, x1 = 205, 545
        row = frame[max(0, y + 20):min(NATIVE_HEIGHT, y + 145), x0:x1]
        if row.size == 0:
            return None
        hsv = cv2.cvtColor(row, cv2.COLOR_BGR2HSV)
        glow_mask = cv2.inRange(hsv, (8, 75, 155), (45, 255, 255))
        green_mask = cv2.inRange(hsv, (35, 75, 100), (95, 255, 255))
        glow_ratio = float(np.count_nonzero(glow_mask)) / glow_mask.size
        green_ratio = float(np.count_nonzero(green_mask)) / green_mask.size
        glow = glow_ratio >= 0.10
        checkmarks = green_ratio >= 0.045
        if claimed and checkmarks:
            state = RewardState.CLAIMED
        elif not claimed and glow:
            state = RewardState.READY
        elif not claimed and not glow:
            state = RewardState.UNAVAILABLE
        else:
            state = RewardState.UNKNOWN
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        return RewardObservation("ZOMBIE_ZERO", True, state, glow, checkmarks, digest), header

    def bind_reward_row(self, frame: np.ndarray) -> BoundTarget | None:
        located = self._challenge_reward(frame)
        if located is None:
            return None
        observation, header = located
        if observation.reward is not RewardState.READY or not observation.glowing:
            return None
        y0, y1 = header[1], min(NATIVE_HEIGHT, header[3] + 155)
        return BoundTarget(REWARD_TARGET, (190, y0, 560, y1))

    def result_modal(self, frame: np.ndarray) -> tuple[bool, int | None]:
        text = self._normal(self.text(frame))
        if self._contains(text, "LOSE"):
            damage = re.findall(r"\bdmg this time\s*:\s*([0-9][0-9,]*)\b", text)
            continuation = self._phrase_boxes(frame, "Tap to continue")
            if (len(damage) == 1 and len(continuation) == 1
                    and continuation[0][1] >= NATIVE_HEIGHT * 0.8):
                return True, int(damage[0].replace(",", ""))
            return False, None
        if not self._contains(text, "History High"):
            return False, None
        numeric = self.text(frame, (90, 520, 710, 680))
        values = [int(item.replace(",", "")) for item in re.findall(r"[0-9][0-9,]{3,}", numeric)]
        target = self.bind_text_target(frame, "Confirm", RESULT_CONFIRM_TARGET)
        if target is None or len(values) != 1:
            return False, None
        return True, values[0]

    def bind_result_confirm(self, frame: np.ndarray) -> BoundTarget | None:
        recognized, damage = self.result_modal(frame)
        if not recognized or damage is None:
            return None
        continuation = self._phrase_boxes(frame, "Tap to continue")
        if len(continuation) == 1 and continuation[0][1] >= NATIVE_HEIGHT * 0.8:
            return BoundTarget(RESULT_CONFIRM_TARGET, continuation[0])
        return self.bind_text_target(frame, "Confirm", RESULT_CONFIRM_TARGET)


class HallOfWarBoundary:
    """One bounded challenge and one separate reward-row action under the caller's owner."""

    def __init__(
        self, *, session, runtime: LocalBlueStacksRuntime, action_store, backend_identity,
        scheduler_identity: SchedulerIdentity, validate_identity: Callable[[], None],
        settle_seconds: float = 0.65, monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time, vision: HallOfWarVision | None = None,
    ) -> None:
        if not callable(validate_identity):
            raise TypeError("Hall of War requires the caller's current identity checkpoint")
        if not isinstance(backend_identity, VerifiedRuntimeIdentity):
            raise TypeError("Hall of War needs its verified fixed-slot runtime identity")
        if not isinstance(scheduler_identity, SchedulerIdentity) or scheduler_identity.task_id != PRODUCT_ID:
            raise TypeError("Hall of War needs its exact scheduler game-day identity")
        self.session, self.runtime, self.store = session, runtime, action_store
        self.identity, self.scheduler_identity = backend_identity, scheduler_identity
        self.game_day_id = scheduler_identity.reset_id
        self.validate_identity = validate_identity
        self.settle_seconds, self.monotonic_clock, self.wall_clock = settle_seconds, monotonic_clock, wall_clock
        self.vision = vision or HallOfWarVision()
        self.atlas_path = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
        self.atlas = load_home_atlas(self.atlas_path)
        self.localizer = BlueStacksHomeLocalizer(self.atlas, self.atlas_path)
        ready = HomeReadyObservation(True, True, backend_identity, False, False)
        self.home_driver = BlueStacksLocalizeFirstHomeDriver(
            self.atlas, self.atlas_path, ready, HALL_OF_WAR_ATLAS_BUILDING_ID,
            localizer=self.localizer, maximum_pans=2, maximum_zoom_inputs=1,
        )
        self.navigation = NavigationGuardedRuntime(self.runtime, NavigationRouteDeclaration(
            allowed_source_states=frozenset({
                "HOME_BASE", "HOME_WITH_KNOWN_RADIAL", "ZOMBIE_ZERO",
                "ZOMBIE_ZERO_DISPATCH", "ZOMBIE_ZERO_RESULT",
                "COMMANDER_TALENT_MEMORY", "COMMANDER_TALENT", "COMMANDER_INFO",
            }),
            allowed_target_identities=frozenset({
                HALL_OF_WAR_ATLAS_BUILDING_ID, HALL_OF_WAR_RADIAL_TARGET, ATTACK_TARGET,
                FORMATION_ARROW_TARGET, TROOP_SET_ONE_TARGET, RESULT_CONFIRM_TARGET,
                HOME_ATLAS_PAN_TARGET, HOME_ZOOM_TARGET, HOME_BACK_TARGET,
            }),
            allowed_gesture_classes=frozenset({"tap", "swipe", "back", "zoom_out"}),
        ))
        self.dispatch_key = action_key(category="dispatch", runtime_scope=backend_identity.runtime_scope,
            account_id=backend_identity.account_id, server_id=backend_identity.server_id, reset_id=self.game_day_id)
        self.reward_key = action_key(category="reward", runtime_scope=backend_identity.runtime_scope,
            account_id=backend_identity.account_id, server_id=backend_identity.server_id, reset_id=self.game_day_id)
        self.result: dict[str, Any] = {
            "status": "blocked", "reason": "hall_of_war_source_not_bound",
            "challenge_status": "unknown", "reward_status": "unknown",
            "dispatch_transport_calls": 0, "reward_claim_transport_calls": 0,
            "talent_switch_transport_calls": 0,
            "committed_action_count": 0, "hall_of_war_dispatch_count": 0,
            "scheduler_reset_id": self.game_day_id,
            "backend_reset_id": backend_identity.reset_id,
            "terminal_home_verified": False, "effect_reconciliation_required": False,
            "identical_retry_denied": False, "verified_navigation": [],
        }
        self.formation_proof: dict[str, Any] | None = None
        self.radial_semantics: HomeRadialSemantics | None = None
        self._last_successor_capture = None
        self._hall_entry_binding: BuildingBinding | None = None

    def _checkpoint(self, *, active_action_id: str | None = None) -> None:
        self.session.runtime_input_lock.assert_held(
            self.session.runtime_input_lock.owner, self.session.runtime_input_lock.invocation_id
        )
        self.validate_identity()
        if self.store.has_action_block(exclude_action_id=active_action_id):
            raise HallOfWarRouteError("canonical unresolved action requires inspection")

    def _capture(self, label: str, *, active_action_id: str | None = None):
        self._checkpoint(active_action_id=active_action_id)
        return self.session.observe(self.runtime.capture, label=label)

    def _safety(self, captured, source_state: str, roi=None):
        return make_source_safety_facts(
            recognized=True, source_state=source_state, frame_sha256=captured.sha256,
            captured_monotonic=captured.captured_monotonic, target_roi=roi,
        )

    def _navigation_tap(
        self, *, label: str, source_state: str, target_identity: str,
        binder: Callable[[np.ndarray], BoundTarget | None], successor: Callable[[np.ndarray], str],
    ):
        selected: dict[str, BoundTarget] = {}
        def authorize(before):
            target = binder(before.frame)
            if target is None or target.target_identity != target_identity:
                raise HallOfWarRouteError(f"{label}_target_not_bound_from_current_frame")
            selected["target"] = target
        def dispatch(before):
            target = selected["target"]
            self.navigation.prepare_source_safety(self._safety(before, source_state, target.target_roi))
            self.navigation.tap(before, target_identity=target.target_identity, target_roi=target.target_roi,
                action_key=f"hall-of-war:{label}:{before.sha256}")
        def recognize(after):
            self._last_successor_capture = after
            return successor(after.frame)
        action = self.session.run_action(
            action_class="navigation", label=f"hall-of-war-{label}", capture=self.runtime.capture,
            authorize=authorize, dispatch=dispatch, recognize=recognize,
            settled_successor=lambda: self._settled(f"hall-of-war-{label}-settled"),
            consequence_class="navigation_only",
        )
        if action.status != "completed":
            raise HallOfWarRouteError(f"{label}_successor_unknown")
        self.result["verified_navigation"].append(label)
        return action

    def _settled(self, label: str, *, active_action_id: str | None = None):
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)
        return self._capture(label, active_action_id=active_action_id)

    def _home_binding(self):
        pans = zooms = 0
        zoom_transport = None
        if getattr(self.runtime, "execute", False) and getattr(self.runtime, "runner", None) is not None:
            zoom_transport = ScrcpyMotionEventZoomTransport(
                adb=self.runtime.runner.executable, serial=self.runtime.runner.serial,
                evidence_directory=self.runtime.session,
            )
        for ordinal in range(1, 7):
            captured = self._capture(f"hall-of-war-home-atlas-{ordinal:02d}")
            step = self.home_driver.observe(captured.frame)
            if step.disposition in {HomeDriverDisposition.COMPLETE, HomeDriverDisposition.BIND}:
                binding = step.binding
                if (binding is None or binding.building_id != HALL_OF_WAR_ATLAS_BUILDING_ID
                        or binding.frame_sha256 != step.source_frame_sha256 or binding.overlay_intersects or binding.ambiguous_overlap):
                    raise HallOfWarRouteError("hall_of_war_home_atlas_binding_not_current_or_unambiguous")
                return captured, binding
            if step.disposition is HomeDriverDisposition.BLOCKED:
                raise HallOfWarRouteError(f"hall_of_war_home_atlas_blocked:{step.reason}")
            if step.disposition is HomeDriverDisposition.RECOVER_ZOOM:
                if zooms >= 1:
                    raise HallOfWarRouteError("hall_of_war_home_zoom_input_limit")
                self.navigation.prepare_source_safety(self._safety(captured, "HOME_BASE"))
                self.session.run_action(
                    action_class="navigation", label=f"hall-of-war-home-zoom-{zooms + 1}",
                    capture=self.runtime.capture,
                    dispatch=lambda before: self.navigation.dispatch_zoom_out(
                        before, self._safety(before, "HOME_BASE"),
                        transport=zoom_transport.zoom_out_once if zoom_transport is not None else None,
                    ),
                    recognize=lambda after: "home" if self.vision.is_clean_home(after.frame) else "unknown",
                    settled_successor=lambda: self._settled("hall-of-war-home-zoom-settled"),
                    consequence_class="navigation_only",
                )
                self.home_driver.record_zoom_input_dispatched(step.source_frame_sha256)
                zooms += 1
                continue
            if step.disposition is HomeDriverDisposition.PAN:
                if pans >= 2 or step.plan is None or not step.plan.drag_start or not step.plan.drag_end:
                    raise HallOfWarRouteError("hall_of_war_home_atlas_pan_unavailable_or_over_budget")
                before_localization = step.localization
                pan_roi = (min(step.plan.drag_start[0], step.plan.drag_end[0]),
                           min(step.plan.drag_start[1], step.plan.drag_end[1]),
                           max(step.plan.drag_start[0], step.plan.drag_end[0]) + 1,
                           max(step.plan.drag_start[1], step.plan.drag_end[1]) + 1)
                def authorize_pan(before):
                    nonlocal before_localization
                    localized_before = self.localizer.localize(before.frame)
                    if (not self.vision.is_clean_home(before.frame)
                            or not localized_before.recognized
                            or localized_before.stale or localized_before.overlay):
                        raise HallOfWarRouteError("hall_of_war_home_pan_source_not_current")
                    before_localization = localized_before
                    self.navigation.prepare_source_safety(self._safety(before, "HOME_BASE", pan_roi))

                self.session.run_action(
                    action_class="navigation", label=f"hall-of-war-home-pan-{pans + 1}",
                    capture=self.runtime.capture,
                    authorize=authorize_pan,
                    dispatch=lambda before, plan=step.plan: self.navigation.swipe(
                        before, start=plan.drag_start, end=plan.drag_end,
                        action_key=f"hall-of-war-home-pan:{before.sha256}",
                        target_identity=HOME_ATLAS_PAN_TARGET,
                    ),
                    recognize=lambda after: "home" if self.vision.is_clean_home(after.frame) else "unknown",
                    settled_successor=lambda: self._settled("hall-of-war-home-pan-settled"),
                    consequence_class="navigation_only",
                )
                after = self.runtime.capture("hall-of-war-home-pan-localization")
                localized = self.localizer.localize(after.frame)
                if not localized.recognized or localized.stale or localized.overlay:
                    raise HallOfWarRouteError("hall_of_war_home_pan_successor_not_localized")
                self.home_driver.record_pan_progress(before_localization, localized)
                pans += 1
                continue
            raise HallOfWarRouteError(f"hall_of_war_home_atlas_unhandled:{step.disposition.value}")
        raise HallOfWarRouteError("hall_of_war_home_atlas_entry_limit")

    def _page_observation(self, captured) -> tuple[AttemptState, int | None]:
        if not self.vision.zombie_zero_page(captured.frame):
            return AttemptState.UNKNOWN, None
        return self.vision.attempt_state(captured.frame), self.vision.today_highest_damage(captured.frame)

    def _make_challenge_observation(self, *, dispatch_capture, attempt_capture, attempt, today_damage) -> ChallengeObservation:
        exact_dispatch = self.vision.dispatch_page(dispatch_capture.frame)
        current, capacity = self.vision.troop_counts(dispatch_capture.frame)
        applied = bool(self.formation_proof and self.formation_proof.get("applied"))
        selected = bool(applied and self.formation_proof.get("selector_row") == "Troop Set 1")
        signature = self.vision.formation_signature(dispatch_capture.frame)
        if self.formation_proof and self.formation_proof.get("formation_signature") != signature:
            selected = False
        return ChallengeObservation(
            page_identity="ZOMBIE_ZERO",
            page_exact=self.vision.zombie_zero_page(attempt_capture.frame),
            attempt=attempt,
            saved_military_verified=bool(self.result.get("saved_military_verified")),
            troop_set_one_selected=selected,
            troop_set_one_applied=applied,
            five_heroes_populated=self.vision.hero_count(dispatch_capture.frame) == 5,
            current_troops=current,
            troop_capacity=capacity,
            today_highest_damage=today_damage,
            attempt_source_frame_sha256=attempt_capture.sha256,
            dispatch_page_identity="ZOMBIE_ZERO_DISPATCH",
            dispatch_page_exact=exact_dispatch,
            attempt_ordinal=1,
            source_frame_sha256=dispatch_capture.sha256,
        )

    def _action_observation(self, captured, *, source_state: str, target: BoundTarget,
                            consequence: str, postcondition: str,
                            critical_roi_hashes: tuple[tuple[str, str], ...] = ()) -> Observation:
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=PROFILE_ID,
            width=NATIVE_WIDTH, height=NATIVE_HEIGHT, valid_png=True,
            corrupt=False, black=False, source_state=source_state,
            overlay_state="none_observed", target_identity=target.target_identity,
            target_roi=target.target_roi, recognized=True,
            control_class="DISPATCH" if target.target_identity == DISPATCH_TARGET else "CLAIM",
            consequence=consequence, cost_type="none", cost_amount=0, quantity=1,
            expected_postcondition=postcondition, evidence_refs=(str(captured.path),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="hall_of_war_zombie_zero", target_isolated=True,
            package_foreground=self.runtime.measure_foreground_package() == "com.global.ztmslg",
            critical_roi_hashes=critical_roi_hashes,
        )

    def _action_critical_rois(self, frame: np.ndarray, category: str, target: BoundTarget):
        if category == "dispatch":
            signature = self.vision.formation_signature(frame)
            if len(signature) != 5:
                raise HallOfWarRouteError("dispatch_current_saved_formation_unproven")
            formation = hashlib.sha256("|".join(signature).encode("ascii")).hexdigest()
            control = self.vision.roi_sha256(frame, target.target_roi)
            if not control:
                raise HallOfWarRouteError("dispatch_current_control_roi_not_hashable")
            return (
                ("hall_of_war_saved_formation", formation),
                ("hall_of_war_dispatch_control", control),
            )
        digest = self.vision.roi_sha256(frame, target.target_roi)
        if not digest:
            raise HallOfWarRouteError("reward_current_row_roi_not_hashable")
        return (("hall_of_war_glowing_daily_reward", digest),)

    def _perform_canonical_action(
        self, *, category: str, action_id: str, key: str, semantic_action: str,
        source_state: str, target_identity: str, consequence: str, postcondition: str,
        binder: Callable[[np.ndarray], BoundTarget | None],
        postcondition_checker: Callable[[np.ndarray], bool], action_class: str,
    ) -> tuple[str, int, dict[str, Any]]:
        # The first capture plans the action. A second genuine capture is the
        # capability source and the only frame eligible for the dispatched tap.
        proposal_capture = self._capture(f"hall-of-war-{category}-proposal")
        target = binder(proposal_capture.frame)
        if target is None or target.target_identity != target_identity:
            return "blocked", 0, {"reason": f"{category}_target_not_bound"}

        try:
            proposal_rois = self._action_critical_rois(proposal_capture.frame, category, target)
            pre_dispatch_capture = self._capture(f"hall-of-war-{category}-pre-dispatch")
            pre_dispatch_target = binder(pre_dispatch_capture.frame)
            if (
                pre_dispatch_target is None
                or pre_dispatch_target.target_identity != target_identity
                or pre_dispatch_target.target_roi != target.target_roi
            ):
                return "blocked", 0, {"reason": f"{category}_pre_dispatch_target_changed"}
            pre_dispatch_rois = self._action_critical_rois(
                pre_dispatch_capture.frame, category, pre_dispatch_target
            )
            if proposal_rois != pre_dispatch_rois:
                return "blocked", 0, {"reason": f"{category}_critical_proof_changed"}
        except HallOfWarRouteError as exc:
            return "blocked", 0, {"reason": str(exc)}
        pre_dispatch_observation = self._action_observation(
            pre_dispatch_capture, source_state=source_state, target=pre_dispatch_target,
            consequence=consequence, postcondition=postcondition,
            critical_roi_hashes=pre_dispatch_rois,
        )
        proposal_observation = self._action_observation(
            proposal_capture, source_state=source_state, target=target,
            consequence=consequence, postcondition=postcondition,
            critical_roi_hashes=proposal_rois,
        )
        if category == "dispatch":
            roi_digests = dict(pre_dispatch_rois)
            route_preconditions = dispatch_policy_preconditions(
                reset_id=self.game_day_id, action_key=key,
                source_frame_sha256=proposal_capture.sha256,
                formation_roi_sha256=roi_digests["hall_of_war_saved_formation"],
                dispatch_roi_sha256=roi_digests["hall_of_war_dispatch_control"],
            )
            action_id = "hall-of-war:dispatch:" + hashlib.sha256(json.dumps(
                [key, list(route_preconditions)], ensure_ascii=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
        else:
            route_preconditions = reward_policy_preconditions(reset_id=self.game_day_id, action_key=key)
        self._checkpoint()
        request = PolicyRequest(
            action_id=action_id, action_key=key, task_id=FLOW_ID,
            task_mode="supervised_validation", semantic_action=semantic_action,
            expected_runtime_profile_id=PROFILE_ID,
            observation=proposal_observation, monotonic_now=self.monotonic_clock(),
            observation_max_age_seconds=15.0, dispatch_max_age_seconds=5.0,
            lease_owner=self.session.owner,
            lease_valid=self.store.lease_valid_for(self.session.owner, self.wall_clock()),
            unresolved_action=self.store.has_action_block(),
            duplicate_action_key=self.store.action_key_exists(key),
            game_day_id=self.game_day_id,
            action_kind=semantic_action, subject=None,
            maximum_cost=0, free_only=True,
            semantic_preconditions=tuple(route_preconditions),
            semantic_postconditions=(postcondition,),
            runtime_session_id=str(self.runtime.session),
        )
        policy = CentralPolicy({FLOW_ID})
        issue_request = replace(
            request,
            observation=pre_dispatch_observation,
            monotonic_now=self.monotonic_clock(),
            policy_phase="pre_dispatch",
        )
        issued = policy.issue_capability(issue_request)
        self.store.audit(FLOW_ID, "capability_issued", self.wall_clock(), issued.audit, action_id)
        if not issued.authorized or issued.capability is None:
            return "blocked", 0, {"reason": issued.reason_code, "action_key": key}
        latest: dict[str, Any] = {"captured": pre_dispatch_capture, "target": pre_dispatch_target}
        post_captures: list[Any] = []
        post_seen: dict[str, bool] = {}
        pre_dispatch_observation_supplied = False
        action_capture_supplied = False

        def recapture():
            nonlocal pre_dispatch_observation_supplied
            self._checkpoint(active_action_id=action_id)
            if pre_dispatch_observation_supplied:
                raise HallOfWarRouteError(f"{category}_pre_dispatch_capture_reused")
            pre_dispatch_observation_supplied = True
            return pre_dispatch_observation

        def transport(_intent):
            def action_capture(label: str):
                nonlocal action_capture_supplied
                self._checkpoint(active_action_id=action_id)
                if not action_capture_supplied:
                    action_capture_supplied = True
                    return pre_dispatch_capture
                captured = self.runtime.capture(label)
                self._checkpoint(active_action_id=action_id)
                return captured

            def authorize(before):
                self._checkpoint(active_action_id=action_id)
                fresh_target = binder(before.frame)
                if (
                    before.sha256 != pre_dispatch_capture.sha256
                    or before.captured_monotonic != pre_dispatch_capture.captured_monotonic
                    or fresh_target is None
                    or fresh_target.target_identity != target_identity
                    or fresh_target.target_roi != pre_dispatch_target.target_roi
                ):
                    raise HallOfWarRouteError(f"{category}_current_target_changed")
                fresh_rois = self._action_critical_rois(before.frame, category, fresh_target)
                if fresh_rois != pre_dispatch_rois:
                    raise HallOfWarRouteError(f"{category}_current_critical_proof_changed")
                latest.update(captured=before, target=fresh_target)

            def dispatch(before):
                self._checkpoint(active_action_id=action_id)
                current = latest["target"]
                self.runtime.tap(
                    before, target_identity=target_identity,
                    target_roi=current.target_roi, action_key=key,
                    action_class="combat" if category == "dispatch" else "reward",
                    consequential=True,
                )

            def recognize(after):
                self._checkpoint(active_action_id=action_id)
                positive = bool(postcondition_checker(after.frame))
                post_captures.append(after)
                post_seen[str(after.path)] = positive
                return postcondition if positive else "unknown"

            input_result = self.session.run_action(
                action_class="combat" if category == "dispatch" else "reward",
                label=f"hall-of-war-{category}", capture=action_capture,
                authorize=authorize, dispatch=dispatch, recognize=recognize,
                settled_successor=lambda: self._settled(
                    f"hall-of-war-{category}-settled", active_action_id=action_id
                ),
                consequence_class=f"hall_of_war_{category}_effect",
            )
            return TransportResult(
                True, f"HALL_OF_WAR_{category.upper()}_DISPATCHED", input_result.status
            )


        def post_observe():
            captured = self._capture(
                f"hall-of-war-{category}-postcondition", active_action_id=action_id
            )
            positive = bool(postcondition_checker(captured.frame))
            post_captures.append(captured)
            post_seen[str(captured.path)] = positive
            yield Observation(
                frame_sha256=captured.sha256,
                capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=PROFILE_ID,
                width=NATIVE_WIDTH, height=NATIVE_HEIGHT, valid_png=True,
                corrupt=False, black=False,
                source_state=postcondition if positive else "UNKNOWN",
                overlay_state="none_observed" if positive else "unknown",
                target_identity=None, target_roi=None, recognized=positive,
                evidence_refs=(str(captured.path),),
            )

        def reconcile(_intent, observed):
            positive = bool(post_captures and post_seen.get(str(post_captures[-1].path)))
            return bool(positive and observed.recognized and observed.source_state == postcondition)

        execution = SafeActionExecutor(
            self.store, policy, self.session.owner, self.monotonic_clock,
            transport, recapture, post_observe, reconcile,
            wall_clock=self.wall_clock, max_pre_dispatch_attempts=1,
        ).execute(request, issued.capability)
        transport_field = (
            "dispatch_transport_calls" if category == "dispatch" else "reward_claim_transport_calls"
        )
        self.result[transport_field] = execution.transport_calls
        action = self.store.get_action_by_key(key)
        payload = {
            "action_id": action_id, "action_key": key,
            "journal_status": action["final_status"] if action is not None else None,
            "executor_status": execution.status.value,
            "executor_reason": execution.reason,
            "transport_calls": execution.transport_calls,
            "result_frame": str(post_captures[-1].path) if post_captures else None,
            "result_sha256": post_captures[-1].sha256 if post_captures else None,
        }

        if execution.status is ActionStatus.CONFIRMED:
            exact = {
                "action_id": action_id, "task_id": FLOW_ID,
                "semantic_action": semantic_action, "source_state": source_state,
                "target_identity": target_identity, "game_day_id": self.game_day_id,
                "consequence": consequence, "expected_postcondition": postcondition,
                "cost_type": "none", "cost_amount": 0.0, "quantity": 1,
                "consequential": 1, "final_status": ActionStatus.CONFIRMED.value,
            }
            if action is None or any(action.get(field) != value for field, value in exact.items()):
                return "unresolved", execution.transport_calls, {**payload, "reason": "canonical_confirmation_mismatch"}
            return "confirmed", execution.transport_calls, payload
        if execution.status is ActionStatus.UNRESOLVED:
            return "unresolved", execution.transport_calls, payload
        return "blocked", execution.transport_calls, payload
    def _confirmed_dispatch_action(self, action) -> bool:
        if action is None:
            return False
        exact = {
            "action_id": f"hall-of-war-dispatch:{self.game_day_id}",
            "task_id": FLOW_ID,
            "semantic_action": DISPATCH_ACTION,
            "source_state": DISPATCH_SOURCE,
            "target_identity": DISPATCH_TARGET,
            "game_day_id": self.game_day_id,
            "consequence": DISPATCH_CONSEQUENCE,
            "expected_postcondition": DISPATCH_POSTCONDITION,
            "cost_type": "none",
            "cost_amount": 0.0,
            "quantity": 1,
            "consequential": 1,
            "final_status": ActionStatus.CONFIRMED.value,
        }
        return all(action.get(field) == value for field, value in exact.items())

    def _result_modal(self, frame: np.ndarray) -> bool:
        recognized, damage = self.vision.result_modal(frame)
        return recognized and type(damage) is int and damage >= 0

    def _reward_claimed(self, frame: np.ndarray) -> bool:
        observation = self.vision.challenge_reward(frame)
        return observation is not None and observation.reward is RewardState.CLAIMED and observation.checkmarks_verified

    def _return_home(self, *, maximum_backs: int = 2) -> bool:
        for ordinal in range(maximum_backs + 1):
            captured = self._capture(f"hall-of-war-terminal-check-{ordinal}")
            localization = self.localizer.localize(captured.frame)
            if (self.vision.is_clean_home(captured.frame) and localization.recognized
                    and not localization.stale and not localization.overlay):
                self.result.update(terminal_home_verified=True,
                    terminal_home_frame={"frame_path": captured.path.relative_to(self.runtime.session).as_posix(),
                                         "frame_sha256": captured.sha256})
                return True
            if ordinal >= maximum_backs:
                return False
            # Only known Zombie Zero or its exact Dispatch page may use system Back.
            state = "ZOMBIE_ZERO_DISPATCH" if self.vision.dispatch_page(captured.frame) else "ZOMBIE_ZERO" if self.vision.zombie_zero_page(captured.frame) else None
            if state is None:
                return False
            self.navigation.prepare_source_safety(self._safety(captured, state))
            action = self.session.run_action(
                action_class="navigation", label=f"hall-of-war-return-home-{ordinal + 1}",
                capture=self.runtime.capture,
                authorize=lambda before, expected=state: self._require_back_source(before, expected),
                dispatch=lambda before, idx=ordinal: self.navigation.back(
                    before, action_key=f"hall-of-war-home-back:{idx}:{before.sha256}",
                    target_identity=HOME_BACK_TARGET,
                ),
                recognize=lambda after: "home" if self.vision.is_clean_home(after.frame) else "zombie_zero" if self.vision.zombie_zero_page(after.frame) else "unknown",
                settled_successor=lambda: self._settled("hall-of-war-return-home-settled"),
                consequence_class="navigation_only",
            )
            if action.status != "completed":
                return False
        return False

    def _require_back_source(self, captured, expected: str) -> None:
        if expected == "ZOMBIE_ZERO_DISPATCH" and not self.vision.dispatch_page(captured.frame):
            raise HallOfWarRouteError("return_home_dispatch_source_changed")
        if expected == "ZOMBIE_ZERO" and not self.vision.zombie_zero_page(captured.frame):
            raise HallOfWarRouteError("return_home_zombie_zero_source_changed")

    def _radial_successor(self, frame: np.ndarray) -> str:
        captured = self._last_successor_capture
        if captured is None or not np.array_equal(frame, captured.frame):
            return "unknown"
        semantics = self._hall_radial(captured)
        return "home_radial" if semantics is not None and semantics.recognized else "unknown"

    def _hall_radial(self, captured) -> HomeRadialSemantics | None:
        return self.vision.radial_semantics(
            captured.frame, self.runtime, captured,
            entry=self._hall_entry_binding, current=self._hall_binding(captured.frame),
        )

    def _bind_zombie_zero(self, frame: np.ndarray) -> BoundTarget | None:
        # Rebind on the immediate-before frame: same Hall anchor as the tapped
        # entry, the full exact caption set, and the recognized radial target.
        recognized = self.radial_semantics
        current = self._hall_binding(frame)
        if (recognized is None or not recognized.recognized
                or current is None or current.screen_anchor is None
                or not self.vision.same_hall_anchor(self._hall_entry_binding, current)):
            return None
        target = self.vision.radial_target(frame, self.vision.radial_captions(frame, current.screen_anchor))
        try:
            expected = tuple(int(value) for value in recognized.controls[0].metadata["target_roi"].split(","))
        except (IndexError, KeyError, ValueError):
            return None
        if target is None or len(expected) != 4:
            return None
        if any(abs(a - b) > 6 for a, b in zip(target.target_roi, expected)):
            return None
        return target

    def _return_home_from_preset_memory(self, recognize_page: Callable[..., Any]) -> bool:
        def page(captured) -> str:
            observation = recognize_page(captured, required_preset="Military")
            return observation.page if observation.recognized else "unknown"

        current = self._capture("hall-of-war-preset-memory-source")
        if page(current) != "talent_memory":
            return False
        transitions = (
            ("talent_memory", "commander_talent", "COMMANDER_TALENT_MEMORY", "COMMANDER_TALENT"),
            ("commander_talent", "commander_info", "COMMANDER_TALENT", "COMMANDER_INFO"),
            ("commander_info", "home", "COMMANDER_INFO", "HOME_BASE"),
        )
        for index, (source_page, destination_page, source_state, destination_state) in enumerate(transitions, 1):
            def authorize(before, expected=source_page):
                if page(before) != expected:
                    raise HallOfWarRouteError("preset_return_back_source_not_exact")

            def dispatch(before, source=source_state, step=index):
                self.navigation.prepare_source_safety(self._safety(before, source))
                self.navigation.back(
                    before, action_key=f"hall-of-war-preset-back:{step}:{before.sha256}",
                    target_identity=HOME_BACK_TARGET,
                )

            action = self.session.run_action(
                action_class="navigation", label=f"hall-of-war-preset-back-{index}",
                capture=self.runtime.capture, authorize=authorize, dispatch=dispatch,
                recognize=lambda after, expected=destination_page: expected if page(after) == expected else "unknown",
                settled_successor=lambda: self._settled(f"hall-of-war-preset-back-{index}-settled"),
                consequence_class="navigation_only",
            )
            if action.status != "completed":
                return False
            current = self._capture(f"hall-of-war-preset-back-{index}-verified")
            if page(current) != destination_page:
                return False
            self.result["verified_navigation"].append(f"preset-return-{source_page}-to-{destination_page}")
        localization = self.localizer.localize(current.frame)
        if not (self.vision.is_clean_home(current.frame) and localization.recognized
                and not localization.stale and not localization.overlay):
            return False
        self.result["preset_return_home_verified"] = {
            "frame_path": current.path.relative_to(self.runtime.session).as_posix(),
            "frame_sha256": current.sha256,
        }
        return True
    def execute(self) -> dict[str, Any]:
        dispatch_calls = reward_calls = 0
        committed = int(self.result.get("talent_switch_transport_calls", 0))
        try:
            self._checkpoint()
            source = self._capture("hall-of-war-source-home")
            if not self.vision.is_clean_home(source.frame) or self.runtime.measure_foreground_package() != "com.global.ztmslg":
                raise HallOfWarRouteError("fresh_clean_home_required")
            self.result["source_frame"] = {"frame_path": source.path.relative_to(self.runtime.session).as_posix(), "frame_sha256": source.sha256}
            building_capture, binding = self._home_binding()
            self._navigation_tap(
                label="open-building", source_state="HOME_BASE", target_identity=HALL_OF_WAR_ATLAS_BUILDING_ID,
                binder=lambda frame: self._bind_hall_of_war(frame),
                successor=self._radial_successor,
            )
            radial_capture = self._capture("hall-of-war-radial-current")
            self.radial_semantics = self._hall_radial(radial_capture)
            if self.radial_semantics is None or not self.radial_semantics.recognized:
                raise HallOfWarRouteError("hall_of_war_radial_successor_not_recognized")
            self.result["radial_semantics"] = {
                "radial_identity": self.radial_semantics.radial_identity,
                "facility_identity": self.radial_semantics.owning_facility.facility_semantic_id,
                "target_label": "Zombie Zero",
                "source_frame_sha256": self.radial_semantics.source_frame.semantic_sha256,
                "entry_frame_sha256": self.radial_semantics.metadata["entry_frame_sha256"],
            }
            control = self.radial_semantics.controls[0]
            if control.control_id != "hall_of_war_zombie_zero" or control.label != "Zombie Zero":
                raise HallOfWarRouteError("hall_of_war_radial_target_identity_mismatch")
            self._navigation_tap(
                label="open-zombie-zero", source_state="HOME_WITH_KNOWN_RADIAL",
                target_identity=HALL_OF_WAR_RADIAL_TARGET,
                binder=self._bind_zombie_zero,
                successor=lambda frame: "zombie_zero" if self.vision.zombie_zero_page(frame) else "unknown",
            )
            page = self._capture("hall-of-war-zombie-zero-page")
            if not self.vision.zombie_zero_page(page.frame):
                raise HallOfWarRouteError("exact_zombie_zero_page_not_recognized")
            attempt, today_damage = self._page_observation(page)
            self.result.update(challenge_page_frame={"frame_path": page.path.relative_to(self.runtime.session).as_posix(),
                "frame_sha256": page.sha256}, today_highest_damage=today_damage,
                challenge_attempt_state=attempt.value)
            key = self.dispatch_key
            existing = self.store.get_action_by_key(self.dispatch_key)
            if self._confirmed_dispatch_action(existing):
                self.result.update(challenge_status="confirmed_prior_canonical_action",
                    challenge_participation_proven=True, challenge_transport_calls=0)
            elif existing is not None:
                self.result.update(challenge_status="unknown",
                    reason=f"existing_challenge_action_{existing.get('final_status')}",
                    effect_reconciliation_required=existing.get("final_status") in {"prepared", "input_sent", "unresolved"},
                    identical_retry_denied=True)
                if self.result.get("effect_reconciliation_required"):
                    self.result.update(status="unresolved")
                    return self._account(dispatch_calls, reward_calls, committed)
            elif type(today_damage) is int and today_damage > 0:
                # Manual use proves participation, not a new canonical effect.
                self.result.update(challenge_status="deferred_unexplained_prior_same_reset_use",
                    challenge_participation_proven=True, challenge_participation_source="positive_current_reset_today_highest_damage",
                    challenge_transport_calls=0, reason="prior_same_reset_use_has_no_canonical_dispatch_record")
            elif attempt is AttemptState.BUSY:
                self.result.update(challenge_status="busy", reason="challenge_attempt_busy_or_cooling_down")
            elif attempt is AttemptState.UNAVAILABLE:
                self.result.update(challenge_status="unavailable", reason="challenge_unavailable")
            elif attempt is not AttemptState.READY:
                self.result.update(challenge_status="blocked_unknown", reason="challenge_attempt_state_unknown")
            elif self.vision.challenge_reward(page.frame) is not None and self.vision.challenge_reward(page.frame).reward is RewardState.CLAIMED:
                self.result.update(challenge_status="blocked_inconsistent_claimed_reward",
                    reason="reward_claimed_without_current_participation")
            else:
                    self._navigation_tap(
                        label="open-dispatch", source_state="ZOMBIE_ZERO", target_identity=ATTACK_TARGET,
                        binder=self.vision.bind_attack,
                        successor=lambda frame: "dispatch" if self.vision.dispatch_page(frame) else "unknown",
                    )
                    dispatch_page = self._capture("hall-of-war-dispatch-page")
                    if not self.vision.dispatch_page(dispatch_page.frame):
                        raise HallOfWarRouteError("zombie_zero_dispatch_page_not_recognized")
                    arrow = self.vision.bind_formation_arrow(dispatch_page.frame)
                    if arrow is None or arrow.target_identity != FORMATION_ARROW_TARGET:
                        raise HallOfWarRouteError("troop_set_selector_arrow_not_bound")
                    self._navigation_tap(
                        label="open-troop-set-selector", source_state="ZOMBIE_ZERO_DISPATCH",
                        target_identity=FORMATION_ARROW_TARGET, binder=self.vision.bind_formation_arrow,
                        successor=lambda frame: "troop_set_selector" if self.vision.troop_set_selector(frame) else "unknown",
                    )
                    selector = self._capture("hall-of-war-troop-set-selector")
                    selected_target = self.vision.bind_troop_set_one(selector.frame)
                    if selected_target is None or selected_target.target_identity != TROOP_SET_ONE_TARGET:
                        raise HallOfWarRouteError("exact_troop_set_one_row_not_bound_or_edit_ambiguous")
                    self._navigation_tap(
                        label="select-troop-set-one", source_state="ZOMBIE_ZERO_DISPATCH",
                        target_identity=TROOP_SET_ONE_TARGET, binder=self.vision.bind_troop_set_one,
                        successor=lambda frame: "troop_set_one_applied" if self.vision.troop_set_one_applied(frame)
                            and self.vision.hero_count(frame) == 5 else "unknown",
                    )
                    applied = self._capture("hall-of-war-troop-set-one-applied")
                    counts = self.vision.troop_counts(applied.frame)
                    signature = self.vision.formation_signature(applied.frame)
                    if (not self.vision.troop_set_one_applied(applied.frame)
                            or self.vision.hero_count(applied.frame) != 5
                            or type(counts[0]) is not int or counts[0] <= 0
                            or len(signature) != 5):
                        raise HallOfWarRouteError("troop_set_one_formation_or_current_troops_not_verified")
                    self.formation_proof = {
                        "applied": True, "selector_row": "Troop Set 1",
                        "source_frame_sha256": applied.sha256,
                        "current_troops": counts[0], "troop_capacity": counts[1],
                        "formation_signature": signature,
                    }
                    self.result["troop_set_one"] = {
                        "selected": True, "applied_toast_verified": True,
                        "hero_count": 5, "current_troops": counts[0],
                        "troop_capacity": counts[1], "source_frame_sha256": applied.sha256,
                    }
                    # Bind the actual saved formation for the fixed free mechanic.
                    dispatch_before = self._capture("hall-of-war-dispatch-preflight")
                    composite = self._make_challenge_observation(
                        dispatch_capture=dispatch_before, attempt_capture=page,
                        attempt=attempt, today_damage=today_damage,
                    )
                    self.challenge_observation = composite
                    self.result["dispatch_preflight"] = asdict(composite)
                    decision = plan_dispatch(composite, saved_military_verified=bool(self.result.get("saved_military_verified")))
                    if decision.action is not Action.DISPATCH:
                        self.result.update(challenge_status="blocked_pre_dispatch", reason=decision.reason,
                            challenge_participation_proven=False)
                    else:
                        state, dispatch_calls, action_result = self._perform_canonical_action(
                            category="dispatch", action_id=f"hall-of-war-dispatch:{self.game_day_id}",
                            key=key, semantic_action=DISPATCH_ACTION, source_state=DISPATCH_SOURCE,
                            target_identity=DISPATCH_TARGET, consequence=DISPATCH_CONSEQUENCE,
                            postcondition=DISPATCH_POSTCONDITION,
                            binder=lambda frame: self._bind_dispatch_target(frame, composite),
                            postcondition_checker=self._result_modal, action_class="combat",
                        )
                        self.result.update(dispatch_transport_calls=dispatch_calls,
                            challenge_transport_calls=dispatch_calls, dispatch_action=action_result)
                        if state == "confirmed" and dispatch_calls == 1:
                            self.result.update(challenge_status="confirmed", challenge_participation_proven=True)
                            committed += 1
                            self._navigation_tap(
                                label="confirm-result", source_state="ZOMBIE_ZERO_RESULT",
                                target_identity=RESULT_CONFIRM_TARGET, binder=self.vision.bind_result_confirm,
                                successor=lambda frame: "zombie_zero" if self.vision.zombie_zero_page(frame) else "unknown",
                            )
                        elif state == "unresolved":
                            self.result.update(status="unresolved", challenge_status="unknown",
                                reason="dispatch_effect_unresolved",
                                effect_reconciliation_required=True, identical_retry_denied=True)
                            return self._account(dispatch_calls, reward_calls, committed)
                        else:
                            self.result.update(challenge_status="blocked", reason=action_result.get("reason", "dispatch_not_confirmed"))
            current = self._capture("hall-of-war-reward-current")
            page_reward = self.vision.challenge_reward(current.frame)
            participation = bool(self.result.get("challenge_participation_proven"))
            if page_reward is None:
                self.result.update(reward_status="blocked_unknown", reason="daily_reward_row_not_recognized")
            elif page_reward.reward is RewardState.CLAIMED:
                self.result.update(reward_status="already_claimed", reward_claim_transport_calls=0,
                    reward_action_key=self.reward_key, reward_result_frame={
                        "frame_path": current.path.relative_to(self.runtime.session).as_posix(),
                        "frame_sha256": current.sha256,
                    })
            elif page_reward.reward is RewardState.UNAVAILABLE:
                self.result.update(reward_status="unavailable", reward_claim_transport_calls=0)
            elif page_reward.reward is RewardState.READY:
                decision = plan_reward(page_reward, same_reset_participation_proven=participation)
                if decision.action is not Action.CLAIM_REWARD:
                    self.result.update(reward_status="blocked", reason=decision.reason)
                else:
                    state, reward_calls, action_result = self._perform_canonical_action(
                        category="reward", action_id=f"hall-of-war-reward:{self.game_day_id}",
                        key=self.reward_key, semantic_action=REWARD_ACTION,
                        source_state=REWARD_SOURCE, target_identity=REWARD_TARGET,
                        consequence=REWARD_CONSEQUENCE, postcondition=REWARD_POSTCONDITION,
                        binder=self.vision.bind_reward_row,
                        postcondition_checker=self._reward_claimed, action_class="reward",
                    )
                    self.result.update(reward_claim_transport_calls=reward_calls,
                        reward_action=action_result, reward_action_key=self.reward_key)
                    if state == "confirmed" and reward_calls == 1:
                        self.result.update(reward_status="claimed")
                        committed += 1
                    elif state == "unresolved":
                        self.result.update(reward_status="unknown", reason="reward_claim_effect_unresolved",
                            effect_reconciliation_required=True, identical_retry_denied=True)
                    else:
                        self.result.update(reward_status="blocked", reason=action_result.get("reason", "reward_not_confirmed"))
            else:
                self.result.update(reward_status="blocked_unknown", reason="daily_reward_state_unknown")
            dispatch_calls = int(self.result.get("dispatch_transport_calls", dispatch_calls))
            reward_calls = int(self.result.get("reward_claim_transport_calls", reward_calls))
            if self.result.get("effect_reconciliation_required"):
                self.result.update(status="unresolved", identical_retry_denied=True)
                return self._account(dispatch_calls, reward_calls, committed)
            if not self.result.get("terminal_home_verified"):
                # Do not leave a known safe page without attempting its verified Home back.
                if not self._return_home(maximum_backs=2):
                    self.result.update(status="blocked", reason=self.result.get("reason") or "terminal_home_not_verified")
            if self.result.get("terminal_home_verified"):
                challenge = self.result.get("challenge_status")
                reward = self.result.get("reward_status")
                complete = challenge in {"confirmed", "confirmed_prior_canonical_action"} and reward in {"claimed", "already_claimed"}
                if complete:
                    self.result.update(status="complete_for_reset", reason="hall_of_war_challenge_and_reward_reconciled")
                elif challenge in {"busy", "unavailable", "deferred_unexplained_prior_same_reset_use"} or reward == "unavailable":
                    self.result.update(status="deferred", reason=self.result.get("reason") or "hall_of_war_action_not_available")
                else:
                    self.result.update(status="blocked", reason=self.result.get("reason") or "hall_of_war_partial_or_unknown_state")
            return self._account(dispatch_calls, reward_calls, committed)
        except Exception as exc:
            sent = sum(int(self.result.get(name, 0)) for name in (
                "dispatch_transport_calls", "reward_claim_transport_calls", "talent_switch_transport_calls",
            ))
            unknown = bool(self.result.get("effect_reconciliation_required")) or sent > committed
            self.result.update(status="unresolved" if unknown else "blocked",
                reason=f"{type(exc).__name__}: {exc}")
            if unknown:
                self.result.update(effect_reconciliation_required=True, identical_retry_denied=True)
            return self._account(int(self.result.get("dispatch_transport_calls", 0)),
                int(self.result.get("reward_claim_transport_calls", 0)), committed)

    def _account(self, dispatch_calls: int, reward_calls: int, committed: int) -> dict[str, Any]:
        talent_calls = int(self.result.get("talent_switch_transport_calls", 0))
        action_count = aggregate_action_count(
            dispatch_transport_calls=dispatch_calls,
            reward_claim_transport_calls=reward_calls,
            talent_switch_transport_calls=talent_calls,
        )
        valid_committed = type(committed) is int and 0 <= committed <= action_count
        valid_transport_counts = all(
            type(value) is int and value in (0, 1)
            for value in (dispatch_calls, reward_calls, talent_calls)
        )
        effect_unknown = (
            bool(self.result.get("effect_reconciliation_required"))
            or action_count > 0 and (not valid_transport_counts or not valid_committed)
            or valid_committed and committed < action_count
            or action_count > MAX_ACTIONS
        )
        self.result.update(
            dispatch_transport_calls=dispatch_calls,
            reward_claim_transport_calls=reward_calls,
            committed_action_count=committed if valid_committed else None,
            hall_of_war_dispatch_count=action_count,
            total_input_count=int(self.runtime.input_count),
            input_count=int(self.runtime.input_count),
            accounting_verified=(
                self.runtime.input_count == self.session.input_count
                and 0 <= self.runtime.input_count <= MAX_INPUTS
                and valid_transport_counts
                and action_count <= MAX_ACTIONS
                and valid_committed
            ),
            effect_reconciliation_required=effect_unknown,
        )
        if effect_unknown:
            self.result.update(status="unresolved", identical_retry_denied=True)
        return self.result

    def _hall_binding(self, frame: np.ndarray) -> BuildingBinding | None:
        localization = self.localizer.localize(frame)
        if not localization.recognized or localization.stale or localization.overlay:
            return None
        binding = bind_visible_building(frame, localization,
            self.atlas.lookup_building(HALL_OF_WAR_ATLAS_BUILDING_ID), home_is_clean=is_clean_home_frame)
        if (binding is None or binding.building_id != HALL_OF_WAR_ATLAS_BUILDING_ID
                or binding.frame_sha256 != localization.frame_sha256
                or binding.overlay_intersects or binding.ambiguous_overlap):
            return None
        return binding

    def _bind_hall_of_war(self, frame: np.ndarray) -> BoundTarget | None:
        # Called only from open-building authorization on its immediate-before
        # frame; that exact binding is the radial's carried owner entry.
        binding = self._hall_binding(frame)
        self._hall_entry_binding = binding
        return None if binding is None else BoundTarget(HALL_OF_WAR_ATLAS_BUILDING_ID, tuple(binding.target_roi))

    def _bind_dispatch_target(self, frame: np.ndarray, composite: ChallengeObservation) -> BoundTarget | None:
        if not self.vision.dispatch_page(frame):
            return None
        if plan_dispatch(composite, saved_military_verified=bool(self.result.get("saved_military_verified"))).action is not Action.DISPATCH:
            return None
        current, _capacity = self.vision.troop_counts(frame)
        if current != composite.current_troops or type(current) is not int or current <= 0:
            return None
        if self.vision.hero_count(frame) != 5:
            return None
        if not self.formation_proof or self.vision.formation_signature(frame) != self.formation_proof.get("formation_signature"):
            return None
        return self.vision.bind_dispatch(frame)


def run_hall_of_war(
    *, session, runtime: LocalBlueStacksRuntime, action_store, backend_identity,
    scheduler_identity: SchedulerIdentity, validate_identity: Callable[[], None],
    preset_result, recognize_talent_page: Callable[..., Any], settle_seconds: float = 0.65,
) -> dict[str, Any]:
    """Run under the held native owner after independent saved-Military verification."""
    route = HallOfWarBoundary(
        session=session, runtime=runtime, action_store=action_store,
        backend_identity=backend_identity, scheduler_identity=scheduler_identity,
        validate_identity=validate_identity, settle_seconds=settle_seconds,
    )
    switch_calls = int(bool(getattr(preset_result, "switch_transport_attempted", False)))
    route.result["talent_switch_transport_calls"] = switch_calls
    route.result["military_preset_verification"] = asdict(preset_result)
    route.result["saved_military_verified"] = bool(
        getattr(preset_result, "status", None) in {"already_applied", "switched"}
        and getattr(preset_result, "verified", None) is True
        and getattr(preset_result, "preset_name", None) == "Military"
        and (switch_calls == 0 or bool(getattr(preset_result, "switch_action_key", None)))
    )
    if switch_calls and not route.result["saved_military_verified"]:
        route.result.update(status="unresolved", reason="talent_switch_effect_not_verified",
            effect_reconciliation_required=True, identical_retry_denied=True)
        return route._account(0, 0, 0)
    if not route._return_home_from_preset_memory(recognize_talent_page):
        route.result.update(status="blocked", reason="verified_talent_memory_to_home_path_not_confirmed")
        return route._account(0, 0, switch_calls if route.result["saved_military_verified"] else 0)
    if not route.result["saved_military_verified"]:
        route.result.update(
            status="deferred" if getattr(preset_result, "status", None) == "deferred" else "blocked",
            reason=f"saved_military_preset_not_verified:{getattr(preset_result, 'reason', 'unknown')}",
            terminal_home_verified=True,
            terminal_home_frame=route.result["preset_return_home_verified"],
        )
        return route._account(0, 0, 0)
    return route.execute()


def _fixed_backend_identity(context) -> VerifiedRuntimeIdentity:
    from automation_service.recruitment import recruitment_reset

    identity = context.identity
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise HallOfWarRouteError("hall_of_war_scheduler_identity_not_exact")
    sampled_utc = context.utc_clock()
    if not isinstance(sampled_utc, (int, float)) or isinstance(sampled_utc, bool):
        raise HallOfWarRouteError("hall_of_war_utc_clock_sample_invalid")
    window = derive_static_utc_reset(datetime.fromtimestamp(float(sampled_utc), timezone.utc))
    if identity.reset_id != recruitment_reset(float(sampled_utc)):
        raise HallOfWarRouteError("hall_of_war_scheduler_reset_not_current")
    backend = derive_resource_runtime_identity(resource_fixed_runtime_binding(), window.evaluated_utc)
    if (backend.account_id != identity.account_id or backend.server_id != identity.server_id
            or backend.reset_start_utc != window.reset_start_text
            or backend.reset_deadline_utc != window.reset_deadline_text
            or context.runtime_profile_id != PROFILE_ID):
        raise HallOfWarRouteError("hall_of_war_scheduler_and_verified_backend_window_mismatch")
    return backend


def run_hall_of_war_native(context, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    """Fixed static driver; shares the boundary's session, store, owner and native runtime."""
    from automation_service.commander_talents import ensure_commander_talent_preset
    from scripts.commander_talents_bluestacks import (
        recognize_commander_talent_page,
        run_commander_talent_preset,
    )

    if arguments:
        raise ValueError("Hall of War does not accept caller-supplied route arguments")
    if (context.flow_id != FLOW_ID or context.product_id != PRODUCT_ID
            or context.product_revision != PRODUCT_REVISION):
        raise ValueError("Hall of War native context binding does not match this route")
    context.checkpoint()
    context.validate_identity()
    backend_identity = _fixed_backend_identity(context)
    identity = context.identity
    if context.runtime_profile_id != PROFILE_ID:
        raise HallOfWarRouteError("hall_of_war_runtime_profile_mismatch")
    if context.is_clean_home(context.initial_frame.frame):
        context.bind_initial_observation(context.initial_frame)
    else:
        context.prepare_startup(
            source_context="hall_of_war_canonical_startup",
            recognize_successor=lambda captured: context.is_clean_home(captured.frame),
            action_key=f"hall-of-war-startup:{context.invocation_id}",
            settle_seconds=context.settle_seconds,
        )
    context.validate_identity()
    preset_context = {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "required_preset": "Military",
        "scheduler_reset_id": identity.reset_id,
    }
    preset_result = ensure_commander_talent_preset(
        context.session, context.runtime, "Military",
        checkpoint=context.checkpoint,
        runtime_input_lock=context.runtime_input_lock,
        action_store=context.action_store,
        source_generation=context.invocation_id,
        context=preset_context,
        native_port=run_commander_talent_preset,
        switch_approval=None,
    )
    context.validate_identity()
    result = run_hall_of_war(
        session=context.session, runtime=context.runtime, action_store=context.action_store,
        backend_identity=backend_identity, scheduler_identity=identity,
        validate_identity=context.validate_identity, preset_result=preset_result,
        recognize_talent_page=recognize_commander_talent_page,
        settle_seconds=context.settle_seconds,
    )
    result.update(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        scheduler_reset_id=identity.reset_id,
        backend_identity_proof={
            "runtime_scope": backend_identity.runtime_scope,
            "account_id": backend_identity.account_id,
            "server_id": backend_identity.server_id,
            "reset_id": backend_identity.reset_id,
            "reset_start_utc": backend_identity.reset_start_utc,
            "reset_deadline_utc": backend_identity.reset_deadline_utc,
            "assurance": backend_identity.assurance.value,
            "runtime_binding_digest": backend_identity.runtime_binding_digest,
        },
        source_generation=context.invocation_id,
    )
    context.validate_identity()
    return result


def create_service_binding(make_native_route_binding):
    """Create the fixed native lifecycle binding without opening a device at import."""
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:hall-of-war",
        workflow="hall-of-war-zombie-zero",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_hall_of_war_native,
    )
