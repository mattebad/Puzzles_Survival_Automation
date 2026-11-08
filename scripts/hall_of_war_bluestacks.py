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
    CostState,
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
MAX_ACTIONS = 2
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


class HallOfWarVision:
    """OCR/geometry recognizers for the exact observed Hall of War UI surfaces."""

    _HERO_RECTS = (
        (48, 174, 162, 286), (185, 140, 294, 251), (316, 140, 426, 251),
        (447, 140, 557, 251), (581, 174, 690, 286),
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

    def bind_text_target(self, frame: np.ndarray, phrase: str, identity: str, *, padding: tuple[int, int] = (22, 18)) -> BoundTarget | None:
        boxes = self._phrase_boxes(frame, phrase)
        if len(boxes) != 1:
            return None
        x0, y0, x1, y1 = boxes[0]
        px, py = padding
        roi = (max(0, x0 - px), max(0, y0 - py), min(NATIVE_WIDTH, x1 + px), min(NATIVE_HEIGHT, y1 + py))
        if not self._visual_button(frame, roi):
            return None
        return BoundTarget(identity, roi)

    def is_clean_home(self, frame: np.ndarray) -> bool:
        return self._native(frame) and is_clean_home_frame(frame)

    def radial_semantics(self, frame: np.ndarray, runtime, captured) -> HomeRadialSemantics | None:
        text = self.text(frame)
        if not all(self._contains(text, item) for item in ("Hall of War", "Zombie Zero", "Military Operation", "Upgrade", "Details")):
            return None
        ordinal = getattr(runtime, "ordinal", None)
        if type(ordinal) is not int or ordinal < 1:
            return None
        identity = identity_from_captured(captured, session_id=str(runtime.session), ordinal=ordinal, label="hall-of-war-radial")
        owner = OwningFacilityObservation(
            identity, HALL_OF_WAR_ATLAS_BUILDING_ID, RecognitionState.RECOGNIZED, 0.98,
            RadialAmbiguityState.NONE, ("visible Hall of War label",),
        )
        target = self.bind_text_target(frame, "Zombie Zero", HALL_OF_WAR_RADIAL_TARGET)
        if target is None:
            return None
        control = RadialControlObservation(
            identity, "hall_of_war_zombie_zero", "Zombie Zero", ControlRole.PRIMARY_ACTION,
            RecognitionState.RECOGNIZED, 0.98, ActionabilityState.ACTIONABLE,
            "exact route-owned Hall of War radial label and bound current target",
            ("facility.screen",), ("facility.upgrade", "facility.train_queue"),
            HALL_OF_WAR_ATLAS_BUILDING_ID, RadialAmbiguityState.NONE, ("visible Zombie Zero label",),
        )
        return HomeRadialSemantics(
            identity, HALL_OF_WAR_RADIAL_ID, RecognitionState.RECOGNIZED, 0.98,
            owner, (control,), RadialAmbiguityState.NONE,
            ("Hall of War owner, radial controls and target share one capture",),
        )

    def zombie_zero_page(self, frame: np.ndarray) -> bool:
        text = self.text(frame)
        return (
            self._contains(text, "Zombie Zero")
            and self._contains(text, "Today's Highest Dmg")
            and self._contains(text, "Daily Reward")
        )

    def today_highest_damage(self, frame: np.ndarray) -> int | None:
        text = self.text(frame, (75, 730, 675, 875))
        normalized = self._normal(text)
        match = re.search(r"today s highest dmg\s*[: ]\s*([0-9][0-9,]*)", normalized)
        if match is None:
            match = re.search(r"highest dmg\s*[: ]\s*([0-9][0-9,]*)", normalized)
        if match is None:
            return None
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None

    def attempt_state(self, frame: np.ndarray) -> AttemptState:
        text = self.text(frame)
        if not self.zombie_zero_page(frame):
            return AttemptState.UNKNOWN
        if re.search(r"\b(?:cooldown|cooling down|in\s+\d)\b", text):
            return AttemptState.BUSY
        if self.bind_text_target(frame, "Attack", ATTACK_TARGET) is not None:
            return AttemptState.READY
        if self._contains(text, "unavailable") or self._contains(text, "daily limit"):
            return AttemptState.UNAVAILABLE
        return AttemptState.UNKNOWN

    def dispatch_page(self, frame: np.ndarray) -> bool:
        text = self.text(frame)
        return self._contains(text, "Dispatch") and self._contains(text, "Quick Select")

    def bind_attack(self, frame: np.ndarray) -> BoundTarget | None:
        return self.bind_text_target(frame, "Attack", ATTACK_TARGET)

    def bind_formation_arrow(self, frame: np.ndarray) -> BoundTarget | None:
        if not self.dispatch_page(frame):
            return None
        quick = self._phrase_boxes(frame, "Quick Select")
        if len(quick) != 1:
            return None
        qx0, qy0, qx1, qy1 = quick[0]
        center_x, center_y = (qx0 + qx1) // 2, (qy0 + qy1) // 2
        x = center_x - 170
        roi = (x - 25, center_y - 25, x + 26, center_y + 26)
        if not (0 <= roi[0] < roi[2] <= NATIVE_WIDTH and 0 <= roi[1] < roi[3] <= NATIVE_HEIGHT):
            return None
        patch = frame[roi[1]:roi[3], roi[0]:roi[2]]
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 55, 150)
        if float(np.count_nonzero(edges)) / edges.size < 0.055:
            return None
        # The text anchor is Quick Select; the bound selector is explicitly to its left.
        return BoundTarget(FORMATION_ARROW_TARGET, roi)

    def troop_set_selector(self, frame: np.ndarray) -> bool:
        text = self.text(frame)
        return self._contains(text, "Troop Set 1") and self._contains(text, "Edit") and not self.dispatch_page(frame)

    def bind_troop_set_one(self, frame: np.ndarray) -> BoundTarget | None:
        if not self.troop_set_selector(frame):
            return None
        target = self.bind_text_target(frame, "Troop Set 1", TROOP_SET_ONE_TARGET)
        if target is None:
            return None
        edit_boxes = self._phrase_boxes(frame, "Edit")
        if any(not (target.target_roi[2] <= box[0] or box[2] <= target.target_roi[0])
               and abs((target.target_roi[1] + target.target_roi[3] - box[1] - box[3]) // 2) < 55
               for box in edit_boxes):
            return None
        return target

    def hero_count(self, frame: np.ndarray) -> int:
        if not self._native(frame):
            return 0
        count = 0
        for x0, y0, x1, y1 in self._HERO_RECTS:
            patch = frame[y0:y1, x0:x1]
            if patch.shape[:2] != (y1 - y0, x1 - x0):
                continue
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            edge_ratio = float(np.count_nonzero(cv2.Canny(gray, 60, 160))) / gray.size
            if float(np.std(gray)) >= 22.0 and edge_ratio >= 0.025:
                count += 1
        return count

    def troop_counts(self, frame: np.ndarray) -> tuple[int | None, int | None]:
        text = self.text(frame, (50, 1005, 760, 1165))
        match = re.search(r"([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)", text)
        if not match:
            return None, None
        try:
            return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))
        except ValueError:
            return None, None

    def _ocr_lines(self, frame: np.ndarray) -> tuple[tuple[str, tuple[int, int, int, int]], ...]:
        tokens = sorted(self.tokens(frame), key=lambda token: ((token.roi[1] + token.roi[3]) // 2, token.roi[0]))
        groups: list[list[OCRToken]] = []
        for token in tokens:
            center = (token.roi[1] + token.roi[3]) // 2
            group = next((item for item in groups
                          if abs(center - sum((part.roi[1] + part.roi[3]) // 2 for part in item) / len(item)) <= 28), None)
            if group is None:
                groups.append([token])
            else:
                group.append(token)
        rows = []
        for group in groups:
            group.sort(key=lambda token: token.roi[0])
            text = " ".join(token.text for token in group)
            roi = (min(token.roi[0] for token in group), min(token.roi[1] for token in group),
                   max(token.roi[2] for token in group), max(token.roi[3] for token in group))
            rows.append((self._normal(text), roi))
        return tuple(rows)

    @staticmethod
    def roi_sha256(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> str | None:
        if roi is None:
            return None
        x0, y0, x1, y1 = roi
        if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
            return None
        return hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()

    def cost_proof(self, frame: np.ndarray) -> tuple[CostState, int | None, tuple[int, int, int, int] | None]:
        # Absence of any explicit price/free statement remains UNKNOWN.
        for text, roi in self._ocr_lines(frame):
            if re.search(r"\b(?:cost|price|consume|required)\b", text):
                zero = re.search(r"\b(?:cost|price|consume|required)\b\D{0,16}0(?:\b|\.0)\b", text)
                if zero:
                    return CostState.EXPLICIT_ZERO, 0, roi
                positive = re.search(r"\b(?:cost|price|consume|required)\b\D{0,16}([1-9][0-9,]*)\b", text)
                if positive:
                    try:
                        return CostState.NONZERO, int(positive.group(1).replace(",", "")), roi
                    except ValueError:
                        pass
            if re.search(r"\bfree\s+(?:dispatch|attack|challenge)\b", text):
                return CostState.EXPLICIT_ZERO, 0, roi
        return CostState.UNKNOWN, None, None

    def explicit_cost(self, frame: np.ndarray) -> tuple[CostState, int | None]:
        state, amount, _roi = self.cost_proof(frame)
        return state, amount

    def loss_effect_proof(self, frame: np.ndarray) -> tuple[bool, tuple[int, int, int, int] | None]:
        patterns = (
            r"\bno troop losses\b",
            r"\btroops will not be lost\b",
            r"\btroops cannot be lost\b",
        )
        for text, roi in self._ocr_lines(frame):
            if any(re.search(pattern, text) for pattern in patterns):
                return True, roi
        return False, None

    def loss_effect_approved(self, frame: np.ndarray) -> bool:
        return self.loss_effect_proof(frame)[0]

    def troop_set_one_applied(self, frame: np.ndarray) -> bool:
        text = self._normal(self.text(frame))
        return self.dispatch_page(frame) and self._contains(text, "Troop Set 1 formation applied")

    def formation_signature(self, frame: np.ndarray) -> tuple[str, ...]:
        if not self._native(frame):
            return ()
        return tuple(hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
                     for x0, y0, x1, y1 in self._HERO_RECTS)

    def challenge_reward(self, frame: np.ndarray) -> RewardObservation | None:
        if not self.zombie_zero_page(frame):
            return None
        text = self._normal(self.text(frame))
        claimed = self._contains(text, "Daily Reward Claimed")
        header = self._phrase_boxes(frame, "Daily Reward")
        if len(header) != 1:
            # The claimed title is a separate, exact combined phrase.
            header = self._phrase_boxes(frame, "Daily Reward Claimed")
        if len(header) != 1:
            return None
        y = (header[0][1] + header[0][3]) // 2
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
        return RewardObservation("ZOMBIE_ZERO", True, state, glow, checkmarks, digest)

    def bind_reward_row(self, frame: np.ndarray) -> BoundTarget | None:
        observation = self.challenge_reward(frame)
        if observation is None or observation.reward is not RewardState.READY or not observation.glowing:
            return None
        header = self._phrase_boxes(frame, "Daily Reward")
        if len(header) != 1:
            return None
        y0, y1 = header[0][1], min(NATIVE_HEIGHT, header[0][3] + 155)
        return BoundTarget(REWARD_TARGET, (190, y0, 560, y1))

    def result_modal(self, frame: np.ndarray) -> tuple[bool, int | None]:
        text = self._normal(self.text(frame))
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
        return self.bind_text_target(frame, "Confirm", RESULT_CONFIRM_TARGET) if recognized and damage is not None else None


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
                        or binding.frame_sha256 != captured.sha256 or binding.overlay_intersects or binding.ambiguous_overlap):
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
        cost, amount, cost_roi = self.vision.cost_proof(dispatch_capture.frame)
        current, capacity = self.vision.troop_counts(dispatch_capture.frame)
        loss_approved, loss_roi = self.vision.loss_effect_proof(dispatch_capture.frame)
        applied = bool(self.formation_proof and self.formation_proof.get("applied"))
        selected = bool(applied and self.formation_proof.get("selector_row") == "Troop Set 1")
        signature = self.vision.formation_signature(dispatch_capture.frame)
        if self.formation_proof and self.formation_proof.get("formation_signature") != signature:
            selected = False
        return ChallengeObservation(
            page_identity="ZOMBIE_ZERO",
            page_exact=self.vision.zombie_zero_page(attempt_capture.frame),
            attempt=attempt,
            cost=cost,
            cost_amount=amount,
            saved_military_verified=bool(self.result.get("saved_military_verified")),
            troop_set_one_selected=selected,
            troop_set_one_applied=applied,
            five_heroes_populated=self.vision.hero_count(dispatch_capture.frame) == 5,
            current_troops=current,
            troop_capacity=capacity,
            cost_roi_sha256=self.vision.roi_sha256(dispatch_capture.frame, cost_roi),
            loss_effect_known_and_approved=loss_approved,
            loss_roi_sha256=self.vision.roi_sha256(dispatch_capture.frame, loss_roi),
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
            cost, amount, cost_roi = self.vision.cost_proof(frame)
            loss, loss_roi = self.vision.loss_effect_proof(frame)
            cost_digest = self.vision.roi_sha256(frame, cost_roi)
            loss_digest = self.vision.roi_sha256(frame, loss_roi)
            if cost is not CostState.EXPLICIT_ZERO or amount != 0 or not loss or not cost_digest or not loss_digest:
                raise HallOfWarRouteError("dispatch_current_cost_or_loss_disclosure_unproven")
            return (
                ("hall_of_war_explicit_zero_cost", cost_digest),
                ("hall_of_war_no_loss_rule", loss_digest),
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
            critical_rois = self._action_critical_rois(proposal_capture.frame, category, target)
        except HallOfWarRouteError as exc:
            return "blocked", 0, {"reason": str(exc)}
        proposal_observation = self._action_observation(
            proposal_capture, source_state=source_state, target=target,
            consequence=consequence, postcondition=postcondition,
            critical_roi_hashes=critical_rois,
        )

        try:
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
        except HallOfWarRouteError as exc:
            return "blocked", 0, {"reason": str(exc)}
        if pre_dispatch_rois != critical_rois:
            return "blocked", 0, {"reason": f"{category}_pre_dispatch_critical_proof_changed"}
        if pre_dispatch_capture.sha256 != proposal_capture.sha256:
            return "blocked", 0, {"reason": f"{category}_source_frame_changed_before_capability"}
        pre_dispatch_observation = self._action_observation(
            pre_dispatch_capture, source_state=source_state, target=pre_dispatch_target,
            consequence=consequence, postcondition=postcondition,
            critical_roi_hashes=pre_dispatch_rois,
        )
        if category == "dispatch":
            roi_digests = dict(pre_dispatch_rois)
            route_preconditions = dispatch_policy_preconditions(
                reset_id=self.game_day_id, action_key=key,
                source_frame_sha256=pre_dispatch_capture.sha256,
                cost_roi_sha256=roi_digests["hall_of_war_explicit_zero_cost"],
                loss_roi_sha256=roi_digests["hall_of_war_no_loss_rule"],
            )
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
        semantics = self.vision.radial_semantics(frame, self.runtime, captured)
        return "home_radial" if semantics is not None and semantics.recognized else "unknown"

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
        dispatch_calls = reward_calls = committed = 0
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
            self.radial_semantics = self.vision.radial_semantics(radial_capture.frame, self.runtime, radial_capture)
            if self.radial_semantics is None or not self.radial_semantics.recognized:
                raise HallOfWarRouteError("hall_of_war_radial_successor_not_recognized")
            self.result["radial_semantics"] = {
                "radial_identity": self.radial_semantics.radial_identity,
                "facility_identity": self.radial_semantics.owning_facility.facility_semantic_id,
                "target_label": "Zombie Zero",
                "source_frame_sha256": self.radial_semantics.source_frame.semantic_sha256,
            }
            control = self.radial_semantics.controls[0]
            if control.control_id != "hall_of_war_zombie_zero" or control.label != "Zombie Zero":
                raise HallOfWarRouteError("hall_of_war_radial_target_identity_mismatch")
            self._navigation_tap(
                label="open-zombie-zero", source_state="HOME_WITH_KNOWN_RADIAL",
                target_identity=HALL_OF_WAR_RADIAL_TARGET,
                binder=lambda frame: self.vision.bind_text_target(frame, "Zombie Zero", HALL_OF_WAR_RADIAL_TARGET),
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
            if today_damage is None:
                self.result.update(challenge_status="blocked_unknown", reason="today_highest_damage_not_exactly_read")
            elif today_damage > 0:
                if self._confirmed_dispatch_action(existing):
                    self.result.update(challenge_status="confirmed_prior_canonical_action",
                        challenge_participation_proven=True, challenge_transport_calls=0)
                else:
                    # Preserve independent reward eligibility, but do not convert a
                    # live manual-use observation into a canonical dispatch record.
                    self.result.update(challenge_status="deferred_unexplained_prior_same_reset_use",
                        challenge_participation_proven=True, challenge_participation_source="positive_current_reset_today_highest_damage",
                        challenge_transport_calls=0, reason="prior_same_reset_use_has_no_canonical_dispatch_record")
            elif existing is not None:
                self.result.update(challenge_status="unknown",
                    reason=f"existing_challenge_action_{existing.get('final_status')}",
                    effect_reconciliation_required=existing.get("final_status") in {"prepared", "input_sent", "unresolved"},
                    identical_retry_denied=True)
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
                            or not counts[0] or not counts[1] or counts[0] != counts[1]
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
                    # The native capture of a current cost and loss disclosure is mandatory.
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
                            challenge_participation_proven=False, dispatch_cost_state=composite.cost.value,
                            loss_effect_known_and_approved=composite.loss_effect_known_and_approved)
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
                elif challenge in {"busy", "unavailable"} or reward == "unavailable":
                    self.result.update(status="deferred", reason=self.result.get("reason") or "hall_of_war_action_not_available")
                else:
                    self.result.update(status="blocked", reason=self.result.get("reason") or "hall_of_war_partial_or_unknown_state")
            return self._account(dispatch_calls, reward_calls, committed)
        except Exception as exc:
            self.result.update(status="unresolved" if self.result.get("dispatch_transport_calls") or self.result.get("reward_claim_transport_calls") else "blocked",
                reason=f"{type(exc).__name__}: {exc}")
            if self.result.get("dispatch_transport_calls") or self.result.get("reward_claim_transport_calls"):
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

    def _bind_hall_of_war(self, frame: np.ndarray) -> BoundTarget | None:
        captured = self._current_capture_for(frame)
        localization = self.localizer.localize(frame)
        if not localization.recognized or localization.stale or localization.overlay:
            return None
        binding = bind_visible_building(frame, localization,
            self.atlas.lookup_building(HALL_OF_WAR_ATLAS_BUILDING_ID), home_is_clean=is_clean_home_frame)
        if (binding is None or binding.building_id != HALL_OF_WAR_ATLAS_BUILDING_ID
                or binding.frame_sha256 != localization.frame_sha256
                or binding.overlay_intersects or binding.ambiguous_overlap):
            return None
        return BoundTarget(HALL_OF_WAR_ATLAS_BUILDING_ID, tuple(binding.target_roi))

    def _current_capture_for(self, frame):
        # The current-frame navigation callback supplies its own captured object;
        # this compatibility method deliberately does not reconstruct one.
        return frame

    def _bind_dispatch_target(self, frame: np.ndarray, composite: ChallengeObservation) -> BoundTarget | None:
        if not self.vision.dispatch_page(frame):
            return None
        if not (composite.saved_military_verified and composite.troop_set_one_selected
                and composite.troop_set_one_applied and composite.five_heroes_populated
                and composite.cost is CostState.EXPLICIT_ZERO and composite.cost_amount == 0
                and composite.loss_effect_known_and_approved):
            return None
        current, capacity = self.vision.troop_counts(frame)
        if current != composite.current_troops or capacity != composite.troop_capacity or current != capacity or current is None:
            return None
        if self.vision.hero_count(frame) != 5:
            return None
        if not self.formation_proof or self.vision.formation_signature(frame) != self.formation_proof.get("formation_signature"):
            return None
        cost, amount, cost_roi = self.vision.cost_proof(frame)
        loss, loss_roi = self.vision.loss_effect_proof(frame)
        if (cost is not CostState.EXPLICIT_ZERO or amount != 0 or not loss
                or self.vision.roi_sha256(frame, cost_roi) != composite.cost_roi_sha256
                or self.vision.roi_sha256(frame, loss_roi) != composite.loss_roi_sha256):
            return None
        return self.vision.bind_text_target(frame, "Dispatch", DISPATCH_TARGET)


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
        getattr(preset_result, "status", None) == "already_applied"
        and getattr(preset_result, "verified", None) is True
        and getattr(preset_result, "preset_name", None) == "Military"
        and switch_calls == 0
    )
    if switch_calls:
        route.result.update(status="unresolved", reason="unapproved_talent_switch_transport_was_attempted",
            effect_reconciliation_required=True, identical_retry_denied=True)
        return route._account(0, 0, 0)
    if not route._return_home_from_preset_memory(recognize_talent_page):
        route.result.update(status="blocked", reason="verified_talent_memory_to_home_path_not_confirmed")
        return route._account(0, 0, 0)
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
