"""Bounded native Hero Duel–Survival participation over the existing runtime owner."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping

import cv2
import numpy as np

from safe_action_core import ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
from scripts.atlas_flow_startup import normalize_home_atlas_startup
from scripts.bounded_tesseract import CHECKPOINT as OCR_CHECKPOINT, call_ocr, tesseract_data
from scripts.home_atlas_bluestacks import BlueStacksHomeLocalizer, DirectPanNavigator, bind_visible_building
from tasks.home_atlas_vision import frame_digest
from scripts.navigation_development_boundary import DevelopmentSession
from tasks.hero_duel_disabled import (
    HERO_DUEL_SURVIVAL, MAX_HERO_DUEL_CYCLES, HeroDuelObservation,
    hero_duel_action_key, hero_duel_attack_fill, hero_duel_attack_lineup_valid,
    hero_duel_current_survival, hero_duel_entry_authorizeable, hero_duel_first_five_eligible,
    hero_duel_flee_authorizeable, hero_duel_policy_preconditions,
)
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import PlanDisposition
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL, FIXED_RUNTIME_SCOPE
from automation_service.registry import (
    HERO_DUEL_FLOW_ID,
    HERO_DUEL_MAX_INPUTS,
    HERO_DUEL_PRODUCT_ID,
    HERO_DUEL_PRODUCT_REVISION,
    HERO_DUEL_PROFILE_ID,
)


ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = HERO_DUEL_FLOW_ID
PRODUCT_ID = HERO_DUEL_PRODUCT_ID
PRODUCT_REVISION = HERO_DUEL_PRODUCT_REVISION
PROFILE_ID = HERO_DUEL_PROFILE_ID
MAX_INPUTS = HERO_DUEL_MAX_INPUTS
MAX_ACTIONS = MAX_HERO_DUEL_CYCLES
ATLAS_PATH = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
ARENA_BUILDING_ID = "home.building.arena"
WORKFLOW = "hero-duel-survival"
OWNER = "automation-service:hero-duel"
TIMER_RE = re.compile(r"(?:(\d+)\s*d\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?", re.I)
FREE_RE = re.compile(r"\bfree\s*[:=]?\s*(\d+)\s*/\s*(\d+)\b", re.I)
PASS_RE = re.compile(r"\b(?:hero\s+duel\s+)?pass(?:es)?\s*[:=]?\s*([0-9][0-9,]*)\b", re.I)
UI_WORDS = frozenset("hero heroes duel survival glory arena emergency details excluded exclude cannot use defense defence attack formation save form saved success challenge now activate opponent opponents free pass passes none rank ranking legend dueling wave exit flee fight warning lose loss defeat victory continue tap battle matches back confirm cancel close home enter select selected available power level team points score time remaining event rewards record defeated start rules".split())


class HeroDuelRecognitionError(RuntimeError):
    """A current frame cannot prove a unique route state or target."""


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _roi_hash(frame, roi):
    x0, y0, x1, y1 = roi
    return hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()


class HeroDuelVision:
    """Native timed OCR, current-frame target binding, and event-local observations."""

    def __init__(self, *, checkpoint, reset_id: str, utc_clock):
        self.checkpoint = checkpoint
        self.reset_id = reset_id
        self.utc_clock = utc_clock
        self.current_event_valid = False
        self.event_identity: str | None = None
        self.excluded: tuple[str, ...] | None = None
        self.free_opponent_selected = False
        self.defense_saved = False
        self.battle_loaded = False
        self.exit_confirmed = False
        self.route_pass_balance = None

    def _lines(self, frame):
        data = call_ocr(tesseract_data, frame, call_timeout=4.0, config="--psm 11")
        words = []
        for i, text in enumerate(data.get("text", ())):
            try:
                text = str(text).strip()
                conf = float(data["conf"][i])
                x, y = int(data["left"][i]), int(data["top"][i])
                w, h = int(data["width"][i]), int(data["height"][i])
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if text and conf >= 28 and w > 0 and h > 0 and 0 <= x < x + w <= frame.shape[1] and 0 <= y < y + h <= frame.shape[0]:
                words.append({"text": text, "box": (x, y, x + w, y + h), "center": (x + w // 2, y + h // 2)})
        words.sort(key=lambda row: (row["center"][1], row["center"][0]))
        groups = []
        for word in words:
            group = next((candidate for candidate in reversed(groups)
                          if abs(word["center"][1] - sum(item["center"][1] for item in candidate) / len(candidate)) <= 16), None)
            if group is None:
                groups.append([word])
            else:
                group.append(word)
        lines = []
        for group in groups:
            group.sort(key=lambda row: row["box"][0])
            x0 = min(row["box"][0] for row in group)
            y0 = min(row["box"][1] for row in group)
            x1 = max(row["box"][2] for row in group)
            y1 = max(row["box"][3] for row in group)
            text = " ".join(row["text"] for row in group)
            lines.append({
                "text": text, "norm": _norm(text), "box": (x0, y0, x1, y1),
                "center": ((x0 + x1) // 2, (y0 + y1) // 2),
                "word_boxes": tuple((row["text"], row["box"]) for row in group),
            })
        return tuple(lines)

    @staticmethod
    def has(line, *phrases):
        return any(_norm(phrase) in line["norm"] for phrase in phrases)

    @staticmethod
    def bind_phrase(lines, phrase):
        wanted = _norm(phrase)
        exact = [row for row in lines if row["norm"] == wanted]
        matches = exact or [row for row in lines if wanted and wanted in row["norm"]]
        if len(matches) != 1:
            return None
        x0, y0, x1, y1 = matches[0]["box"]
        return max(0, x0 - 3), max(0, y0 - 3), min(800, x1 + 3), min(1280, y1 + 3)

    @staticmethod
    def hero_name(line):
        words = [word for word in _norm(line["text"]).split() if re.fullmatch(r"[a-z][a-z'-]*", word)]
        if not 1 <= len(words) <= 3 or any(word in UI_WORDS for word in words):
            return None
        name = " ".join(words)
        return name.title() if 3 <= len(name) <= 24 else None

    def _hero_candidates(self, lines):
        candidates = []
        for line in lines:
            word_boxes = line.get("word_boxes")
            tokens = []
            if isinstance(word_boxes, (tuple, list)):
                for item in word_boxes:
                    if (isinstance(item, (tuple, list)) and len(item) == 2
                            and isinstance(item[0], str) and isinstance(item[1], (tuple, list))
                            and len(item[1]) == 4):
                        tokens.append((item[0], tuple(item[1])))
            if not tokens:
                name = self.hero_name(line)
                if name:
                    x0, y0, x1, y1 = line["box"]
                    candidates.append({
                        "name": name, "center": line["center"],
                        "roi": (max(0, x0 - 3), max(0, y0 - 3), min(800, x1 + 3), min(1280, y1 + 3)),
                    })
                continue
            tokens.sort(key=lambda item: (item[1][0], item[1][1]))
            groups = []
            for text, box in tokens:
                if groups and box[0] - groups[-1][-1][1][2] <= 24:
                    groups[-1].append((text, box))
                else:
                    groups.append([(text, box)])
            for group in groups:
                text = " ".join(token for token, _box in group)
                name = self.hero_name({"text": text})
                if not name:
                    continue
                x0 = min(box[0] for _token, box in group)
                y0 = min(box[1] for _token, box in group)
                x1 = max(box[2] for _token, box in group)
                y1 = max(box[3] for _token, box in group)
                candidates.append({
                    "name": name, "center": ((x0 + x1) // 2, (y0 + y1) // 2),
                    "roi": (max(0, x0 - 3), max(0, y0 - 3), min(800, x1 + 3), min(1280, y1 + 3)),
                })
        return tuple(candidates)

    def hero_rows(self, lines):
        groups = []
        for candidate in self._hero_candidates(lines):
            group = next((row for row in reversed(groups)
                          if abs(candidate["center"][1] - sum(item["center"][1] for item in row) / len(row)) <= 30), None)
            if group is None:
                groups.append([candidate])
            else:
                group.append(candidate)
        return tuple(tuple(item["name"] for item in sorted(row, key=lambda item: item["center"][0])) for row in groups)

    def _heading_row_candidates(self, lines, headings):
        anchors = [line for line in lines if any(self.has(line, word) for word in headings)]
        if len(anchors) != 1:
            return ()
        y = anchors[0]["center"][1]
        candidates = [candidate for candidate in self._hero_candidates(lines)
                      if y < candidate["center"][1] <= y + 450]
        if not candidates:
            return ()
        first_y = min(candidate["center"][1] for candidate in candidates)
        return tuple(sorted(
            (candidate for candidate in candidates if abs(candidate["center"][1] - first_y) <= 30),
            key=lambda candidate: candidate["center"][0],
        ))

    def heading_row(self, lines, headings):
        candidates = self._heading_row_candidates(lines, headings)
        row = tuple(candidate["name"] for candidate in candidates)
        return row if row and len(row) <= 5 and len(set(row)) == len(row) else ()

    def hero_selection_roi(self, lines, name, state, *, add):
        headings = (
            ("defense formation", "defence formation", "defense lineup", "defence lineup", "hero lineup")
            if state == "defense_formation" else ("attack formation", "attack lineup", "your formation")
        )
        formation = self._heading_row_candidates(lines, headings)
        if not formation:
            return None
        if add:
            formation_bottom = max(candidate["center"][1] for candidate in formation)
            matches = [
                candidate for candidate in self._hero_candidates(lines)
                if candidate["name"] == name and candidate["center"][1] > formation_bottom + 30
            ]
        else:
            matches = [candidate for candidate in formation if candidate["name"] == name]
        return matches[0]["roi"] if len(matches) == 1 else None

    @staticmethod
    def free_counter(lines):
        values = []
        for line in lines:
            match = FREE_RE.search(line["text"])
            if match:
                value, cap = int(match.group(1)), int(match.group(2))
                if 0 <= value <= 3 and 1 <= cap <= 3:
                    values.append(value)
        return values[0] if len(values) == 1 else None

    @staticmethod
    def first_free_opponent_row(lines):
        """Choose the topmost uniquely bound Free opponent row from the current list."""
        rows = []
        for line in lines:
            if not HeroDuelVision.has(line, "free") or FREE_RE.search(line["text"]) is not None:
                continue
            free_boxes = [
                box for text, box in line.get("word_boxes", ())
                if _norm(text) == "free"
            ]
            if len(free_boxes) == 1:
                rows.append({**line, "free_button_roi": free_boxes[0]})
        if not rows:
            return None
        top = min(line["center"][1] for line in rows)
        first = [line for line in rows if line["center"][1] == top]
        return first[0] if len(first) == 1 else None

    @staticmethod
    def emergency_close_x_roi(lines):
        headers = [line for line in lines if HeroDuelVision.has(line, "emergency details")]
        x_boxes = [
            box for line in lines for text, box in line.get("word_boxes", ())
            if text.strip().casefold() in {"x", "×"}
        ]
        if len(headers) != 1 or len(x_boxes) != 1:
            return None
        header, box = headers[0], x_boxes[0]
        center_x = (box[0] + box[2]) / 2
        center_y = (box[1] + box[3]) / 2
        if center_x <= header["center"][0] or abs(center_y - header["center"][1]) > 48:
            return None
        return max(0, box[0] - 3), max(0, box[1] - 3), min(800, box[2] + 3), min(1280, box[3] + 3)

    @staticmethod
    def panel_close_x_roi(lines, heading):
        """Bind the single X beside the current route-owned panel heading."""
        adapted = [
            {**line, "norm": "emergency details"} if line["norm"] == _norm(heading) else line
            for line in lines
        ]
        return HeroDuelVision.emergency_close_x_roi(adapted)

    @staticmethod
    def battle_exit_arrow_roi(frame):
        """Find a fresh pale right-arrow inside a circular battle toolbar control."""
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array((0, 0, 165)), np.array((45, 120, 255)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        template = np.array(((0, 3), (6, 3), (6, 0), (12, 6), (6, 12), (6, 9), (0, 9)), dtype=np.int32)
        matches = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, w * .04,
            param1=100, param2=25, minRadius=int(w * .025), maxRadius=int(w * .05))
        toolbar = [] if circles is None else [
            circle for circle in circles[0] if w * .6 < circle[0] < w * .98 and circle[1] < h * .14
        ]
        if len(toolbar) != 3:
            return None
        cx, cy, radius = max(toolbar, key=lambda circle: circle[0])
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            if not (w * .65 < x < w * .98 and 0 < y < h * .14
                    and w * .015 <= cw <= w * .07 and .65 <= cw / ch <= 1.8):
                continue
            hull_area = cv2.contourArea(cv2.convexHull(contour))
            if hull_area <= 0 or not .45 <= cv2.contourArea(contour) / hull_area <= .9:
                continue
            right_tip = contour[:, 0, :][contour[:, 0, 0] >= x + cw - 2]
            if not len(right_tip) or np.ptp(right_tip[:, 1]) > ch * .4:
                continue
            if cv2.matchShapes(contour, template, cv2.CONTOURS_MATCH_I1, 0) > .22:
                continue
            if (abs(cx - (x + cw / 2)) < radius * .5
                    and abs(cy - (y + ch / 2)) < radius * .5):
                matches.append((x, y, x + cw, y + ch))
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def pass_balance(lines):
        values = [int(match.group(1).replace(",", "")) for line in lines if (match := PASS_RE.search(line["text"]))]
        return values[0] if len(values) == 1 else None

    @staticmethod
    def board_visible(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        h, w = gray.shape[:2]
        crop = gray[int(h * .24):int(h * .84), int(w * .08):int(w * .92)]
        edges = cv2.Canny(cv2.GaussianBlur(crop, (3, 3), 0), 45, 120)
        segments = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=65,
            minLineLength=max(45, int(min(crop.shape) * .12)), maxLineGap=9)
        if segments is None:
            return False
        vertical, horizontal = set(), set()
        for x0, y0, x1, y1 in segments[:, 0, :]:
            dx, dy = abs(int(x1) - int(x0)), abs(int(y1) - int(y0))
            if dx <= 5 and dy >= max(45, int(crop.shape[0] * .12)):
                vertical.add(round((int(x0) + int(x1)) / 16))
            if dy <= 5 and dx >= max(45, int(crop.shape[1] * .12)):
                horizontal.add(round((int(y0) + int(y1)) / 16))
        return len(vertical) >= 5 and len(horizontal) >= 5

    def recognize(self, captured, *, clean_home=False, target_hint=None):
        self.checkpoint()
        lines = self._lines(captured.frame)
        text = "\n".join(line["text"] for line in lines)
        norm = _norm(text)
        state = "unknown"
        if clean_home:
            state = "home"
        elif "emergency details" in norm or all(marker in norm for marker in (
                "hero duel survival", "formation first", "some support heroes cannot be deployed")):
            state = "emergency_details"
        elif "challenge now" in norm and any(self.has(line, "activate") for line in lines):
            state = "challenge_upsell"
        elif "tap to continue" in norm and (
                any(self.has(line, "defeat", "defeated", "loss") for line in lines)
                or ("reward list" in norm and "rank" in norm)):
            state = "loss_result"
        elif any(self.has(line, "warning") for line in lines) and any(self.has(line, "flee") for line in lines):
            state = "flee_warning"
        elif "wave 1 1" in norm and self.board_visible(captured.frame):
            state = "active_battle"
        # A page can be identified before its action control is readable/ready.
        # Target binding and cycle credit still require their own current proof.
        elif ("hero lineup" in norm and "opponent formation" not in norm) or (
                "save form" in norm and any(self.has(line, "defense", "defence") for line in lines)):
            state = "defense_formation"
        elif ("opponent formation" in norm and "your formation" in norm) or (
                "attack" in norm and any(self.has(line, "challenge") for line in lines)):
            state = "attack_formation"
        elif ("challenge opponent" in norm and "hero duel pass" in norm) or (
                any(self.has(line, "opponent", "opponents") for line in lines)
                and any(self.has(line, "free") for line in lines)):
            state = "opponent_list"
        elif "arena" in norm and "hero duel" in norm and "survival" in norm:
            state = "arena"
        elif "hero duel" in norm and "survival" in norm and any(self.has(line, "challenge", "free", "rank") for line in lines):
            state = "hero_duel_overview"
        elif "hero duel" in norm and "survival" in norm:
            state = "event_select"

        overlay = "none"
        if state != "loss_result" and any(self.has(line, "cash mall", "purchase", "buy now", "recharge") for line in lines):
            overlay = "premium_prompt"
        event_identity = self.event_identity
        event_active = None
        timers = []
        for line in lines:
            match = TIMER_RE.search(line["text"])
            if match:
                days = int(match.group(1) or 0)
                hours, minutes, seconds = int(match.group(2)), int(match.group(3)), int(match.group(4) or 0)
                total = days * 86400 + hours * 3600 + minutes * 60 + seconds
                if total > 0:
                    timers.append(total)
        event_states = {"arena", "event_select", "emergency_details", "defense_formation", "hero_duel_overview", "challenge_upsell", "opponent_list", "attack_formation"}
        event_timer_visible = len(timers) == 1
        if state in event_states:
            if event_timer_visible:
                remaining = timers[0]
                deadline_minute = int((float(self.utc_clock()) + remaining + 30) // 60)
                derived = f"survival_{self.reset_id}_ends_{deadline_minute}"
                if self.event_identity and state not in {"arena", "event_select"} and derived != self.event_identity:
                    overlay = "event_identity_changed"
                    self.current_event_valid = False
                else:
                    self.event_identity = derived
                    event_identity = derived
                    self.current_event_valid = True
                event_active = remaining > 0
            elif self.event_identity and self.current_event_valid:
                event_active = True
        if state in {"active_battle", "flee_warning", "loss_result"}:
            event_active = self.event_identity is not None and self.current_event_valid
        excluded = self.excluded
        if state == "emergency_details":
            anchors = [line for line in lines if self.has(line, "excluded", "cannot use")]
            if len(anchors) == 1:
                anchor = anchors[0]
                if self.has(anchor, "no excluded", "no heroes excluded", "excluded none", "excluded heroes none"):
                    excluded = ()
                else:
                    y = anchor["center"][1]
                    excluded = tuple(dict.fromkeys(name for line in lines
                        if y < line["center"][1] < y + 180 and (name := self.hero_name(line)))) or None
                self.excluded = excluded
            else:
                excluded = None
                self.excluded = None
        rows = self.hero_rows(lines)
        displayed = tuple(dict.fromkeys(name for row in rows for name in row))
        defense = self.heading_row(lines, ("defense formation", "defence formation", "defense lineup", "defence lineup", "hero lineup")) if state == "defense_formation" else ()
        attack = self.heading_row(lines, ("attack formation", "attack lineup", "your formation")) if state == "attack_formation" else ()
        if state in {"defense_formation", "attack_formation"}:
            headings = ("hero lineup", "defense formation", "defence formation", "defense lineup", "defence lineup") if state == "defense_formation" else ("attack formation", "attack lineup", "your formation")
            selected_row = self._heading_row_candidates(lines, headings)
            if selected_row:
                bottom = max(candidate["center"][1] for candidate in selected_row)
                # Selected names do not prove the displayed portrait roster order.
                displayed = tuple(dict.fromkeys(
                    candidate["name"] for candidate in self._hero_candidates(lines)
                    if candidate["center"][1] > bottom + 30))
            else:
                displayed = ()
        target_roi = None
        if target_hint and state != "unknown" and overlay == "none":
            if target_hint == ("hero-duel-emergency-close-x", "emergency close x"):
                target_roi = self.emergency_close_x_roi(lines)
            elif target_hint == ("hero-duel-opponents-close", "close"):
                target_roi = self.panel_close_x_roi(lines, "challenge opponent")
            elif target_hint == ("hero-duel-battle-exit", "exit") and state == "active_battle":
                target_roi = self.battle_exit_arrow_roi(captured.frame)
            elif ((state != "loss_result" or target_hint == ("hero-duel-loss-continue", "tap to continue"))
                    and (state != "flee_warning" or target_hint == ("hero-duel-warning-flee", "flee"))):
                target_roi = self.bind_phrase(lines, target_hint[1])
        target = target_hint[0] if target_roi is not None else None
        observed_pass = self.pass_balance(lines)
        if (state == "opponent_list" and event_active is True and overlay == "none"
                and observed_pass is not None):
            self.route_pass_balance = observed_pass
        return {
            "screen_state": state, "lines": lines, "text": text, "event_identity": event_identity,
            "event_timer_visible": event_timer_visible,
            "event_active": event_active, "free_entries_remaining": self.free_counter(lines),
            "pass_balance": observed_pass, "excluded_hero_ids": excluded,
            "displayed_hero_ids": displayed, "defense_hero_ids": defense,
            "defense_save_acknowledged": self.defense_saved, "attack_hero_ids": attack,
            "attack_slots_populated": len(attack) if state == "attack_formation" else None,
            "listed_opponent_free": (state == "opponent_list" and sum(self.has(line, "free") for line in lines) == 1)
                or (state == "attack_formation" and self.free_opponent_selected),
            "free_opponent_selected": self.free_opponent_selected,
            "target_identity": target, "target_roi": target_roi,
            "battle_board_visible": state == "active_battle", "overlay_state": overlay,
        }


class HeroDuelNativeFlow:
    """Three reset-bounded cycles using fresh screens and canonical action effects."""

    def __init__(self, context, arguments: Mapping[str, object]):
        self.context = context
        self.session: DevelopmentSession = context.session
        self.runtime = context.runtime
        self.store = context.action_store
        self.identity = context.identity
        self.reset_id = str(getattr(self.identity, "reset_id", ""))
        self.runtime_scope = FIXED_RUNTIME_SCOPE
        if not self.reset_id or (context.flow_id, context.product_id, context.product_revision, context.runtime_profile_id) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Hero Duel fixed product/runtime identity is not exact")
        self.settle = float(context.settle_seconds)
        self.atlas_path = Path(arguments.get("atlas_path", ATLAS_PATH))
        if str(arguments.get("arena_building_id", ARENA_BUILDING_ID)) != ARENA_BUILDING_ID:
            raise ValueError("Hero Duel permits only the Atlas-mapped Arena building")
        self.vision = HeroDuelVision(checkpoint=context.checkpoint, reset_id=self.reset_id, utc_clock=context.utc_clock)
        self.event_identity = None
        self.result: dict[str, Any] = {
            "preset_id": PRODUCT_ID, "runtime_profile_id": PROFILE_ID,
            "status": "blocked", "reason": "hero_duel_route_not_started",
            "duel_dispatch_count": 0, "entry_transport_calls": 0,
            "flee_transport_calls": 0, "defense_save_transport_calls": 0,
            "defense_selection_transport_calls": 0, "flee_confirmed_count": 0,
            "effect_reconciliation_required": False, "identical_retry_denied": False,
            "terminal_home_verified": False, "no_work": False,
            "cycle_proofs": [], "evidence": [], "navigation_input_count": 0,
            "selected_listed_opponents": [],
        }
        self.return_back_count = 0
        self.overview_balances = None

    def capture(self, label):
        self.context.checkpoint()
        captured = self.session.observe(self.runtime.capture, label=label)
        _, reference = self.context.capture_reference(captured.path, captured.sha256)
        self.result["evidence"].append(asdict(reference))
        return captured

    def observe(self, captured, target_hint=None):
        return self.vision.recognize(captured, clean_home=self.context.is_clean_home(captured.frame), target_hint=target_hint)

    def action_key(self, ordinal, kind):
        return hero_duel_action_key(runtime_scope=self.runtime_scope,
            account_id=self.identity.account_id, server_id=self.identity.server_id,
            game_day_id=self.reset_id, ordinal=ordinal, action_kind=kind)

    @staticmethod
    def confirmed(record):
        return bool(record and record.get("final_status") == ActionStatus.CONFIRMED.value)

    @staticmethod
    def _record_preconditions(record):
        if not record:
            return ()
        try:
            request = json.loads(record.get("policy_request_json") or "null")
        except (TypeError, json.JSONDecodeError):
            return ()
        facts = request.get("semantic_preconditions", ()) if isinstance(request, dict) else ()
        return tuple(item for item in facts if isinstance(item, str)) if isinstance(facts, (list, tuple)) else ()

    def stored_event_identity(self):
        found = set()
        for ordinal in range(1, 4):
            for kind in ("hero_duel_free_entry", "hero_duel_flee", "hero_duel_save_defense"):
                record = self.store.get_action_by_key(self.action_key(ordinal, kind))
                for value in self._record_preconditions(record):
                    if value.startswith("hero_duel_event_identity="):
                        found.add(value.split("=", 1)[1])
        return next(iter(found)) if len(found) == 1 else None

    def _navigation_tap(self, label, phrase, expected, target_id):
        before = self.capture(f"hero-duel-{label}-source")
        page = self.observe(before, (target_id, phrase))
        roi = page["target_roi"]
        if roi is None or page["overlay_state"] != "none":
            self.result["reason"] = f"{label}_target_not_uniquely_bound"
            return None
        source_state = page["screen_state"]
        after = {}
        def authorize(current):
            rebound = self.observe(current, (target_id, phrase))
            if rebound["screen_state"] != source_state or rebound["target_roi"] != roi or rebound["overlay_state"] != "none":
                raise HeroDuelRecognitionError(f"{label}_pre_dispatch_rebind_failed")
        def dispatch(current):
            self.runtime.tap(current, target_identity=target_id, target_roi=roi,
                action_key=f"hero-duel:navigation:{label}:{current.sha256}")
        def recognize(current):
            page_after = self.observe(current)
            after.update(captured=current, page=page_after)
            return page_after["screen_state"] if page_after["screen_state"] in expected else "unknown"
        action = self.session.run_action(action_class="navigation", label=f"hero-duel-{label}",
            capture=self.runtime.capture, authorize=authorize, dispatch=dispatch, recognize=recognize,
            settled_successor=lambda: self.capture(f"hero-duel-{label}-settled"),
            consequence_class="navigation_only")
        if action.status != "completed" or not after:
            self.result["reason"] = f"{label}_successor_unverified"
            return None
        self.result["navigation_input_count"] += 1
        return after

    def _atlas_arena(self):
        atlas = load_home_atlas(self.atlas_path)
        safe, calibration = normalize_home_atlas_startup(session=self.session, runtime=self.runtime,
            capture=self.runtime.capture, atlas=atlas, atlas_path=self.atlas_path,
            settle_seconds=self.settle, evidence_records=self.result["evidence"],
            adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL, maximum_zoom_inputs=2)
        localizer = BlueStacksHomeLocalizer(atlas, self.atlas_path)
        navigator = DirectPanNavigator(atlas, ARENA_BUILDING_ID, safe, calibration, maximum_pans=6)
        building = atlas.lookup_building(ARENA_BUILDING_ID)
        for ordinal in range(7):
            before = self.capture(f"hero-duel-arena-atlas-{ordinal}")
            if not self.context.is_clean_home(before.frame):
                self.result["reason"] = "arena_atlas_source_not_clean_home"
                return None
            local = localizer.localize(before.frame)
            binding = bind_visible_building(before.frame, local, building, home_is_clean=self.context.is_clean_home) if local.recognized else None
            plan = navigator.plan(local, binding)
            if plan.disposition is PlanDisposition.PAN and plan.drag_start and plan.drag_end:
                accepted = {}
                key = f"hero-duel:arena-pan:{ordinal}:{before.sha256}"
                def recognize(_after, before_local=local):
                    settled = self.capture(f"hero-duel-arena-pan-{ordinal}-settled")
                    progress = navigator.record_progress(before_local, localizer.localize(settled.frame))
                    accepted["value"] = progress.accepted
                    return "home_panned" if progress.accepted else "unknown"
                action = self.session.run_action(action_class="navigation", label=f"hero-duel-arena-pan-{ordinal}",
                    capture=lambda _label: before,
                    authorize=lambda current: self._authorize_clean_home(current, before.sha256),
                    dispatch=lambda current: self.runtime.swipe(current, start=plan.drag_start, end=plan.drag_end,
                        action_key=key, target_identity="home-camera-click-drag"),
                    recognize=recognize, consequence_class="navigation_only")
                if action.status != "completed" or not accepted.get("value"):
                    self.result["reason"] = "arena_pan_progress_unverified"
                    return None
                self.result["navigation_input_count"] += 1
                continue
            if plan.disposition is not PlanDisposition.COMPLETE or binding is None:
                self.result["reason"] = f"arena_atlas_binding_unavailable:{plan.reason}"
                return None
            fresh = self.capture("hero-duel-arena-building-immediate")
            local = localizer.localize(fresh.frame)
            rebound = bind_visible_building(fresh.frame, local, building, home_is_clean=self.context.is_clean_home) if local.recognized else None
            if rebound is None or rebound.frame_sha256 != frame_digest(fresh.frame):
                self.result["reason"] = "arena_atlas_immediate_binding_failed"
                return None
            successor = {}
            action = self.session.run_action(action_class="navigation", label="hero-duel-arena-building",
                capture=lambda _label: fresh,
                authorize=lambda current: self._authorize_arena(current, localizer, building, rebound),
                dispatch=lambda current: self.runtime.tap(current, target_identity=ARENA_BUILDING_ID,
                    target_roi=rebound.target_roi, action_key=f"hero-duel:arena-building:{current.sha256}"),
                recognize=lambda current: self._recognize_arena(current, successor),
                settled_successor=lambda: self.capture("hero-duel-arena-building-settled"),
                consequence_class="navigation_only")
            if action.status != "completed":
                self.result["reason"] = "arena_building_successor_unverified"
                return None
            self.result["navigation_input_count"] += 1
            page = successor.get("page")
            if page and page["screen_state"] == "arena":
                return successor
            radial = self.capture("hero-duel-arena-radial-source")
            radial_page = self.observe(radial, ("hero-duel-arena-enter", "enter arena"))
            phrase = "enter arena"
            if radial_page["target_roi"] is None:
                radial_page = self.observe(radial, ("hero-duel-arena-enter", "arena"))
                phrase = "arena"
            if radial_page["target_roi"] is None:
                self.result["reason"] = "arena_radial_enter_target_unbound"
                return None
            return self._navigation_tap("arena-enter", phrase, {"arena", "event_select"}, "hero-duel-arena-enter")
        self.result["reason"] = "arena_pan_budget_exhausted"
        return None

    def _authorize_clean_home(self, current, sha):
        if current.sha256 != sha or not self.context.is_clean_home(current.frame):
            raise HeroDuelRecognitionError("Atlas pan source changed")

    def _authorize_arena(self, current, localizer, building, expected):
        localization = localizer.localize(current.frame)
        rebound = bind_visible_building(current.frame, localization, building,
            home_is_clean=self.context.is_clean_home) if localization.recognized else None
        if rebound is None or rebound.frame_sha256 != frame_digest(current.frame) or rebound.target_roi != expected.target_roi:
            raise HeroDuelRecognitionError("Arena Atlas target changed before dispatch")

    def _recognize_arena(self, captured, output):
        page = self.observe(captured)
        output.update(captured=captured, page=page)
        norm = _norm(page["text"])
        return "arena" if page["screen_state"] == "arena" or ("arena" in norm and "hero duel" not in norm) else "unknown"

    def _observation(self, captured, page, ordinal):
        roi = page.get("target_roi") or (0, 0, 1, 1)
        lines = page["lines"]
        balances = None
        if page["screen_state"] == "attack_formation" and self.vision.free_opponent_selected:
            balances = self.overview_balances
        elif page["screen_state"] == "flee_warning":
            record = self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_free_entry"))
            facts = self._record_preconditions(record)
            prior = self._prior_free_pass_proof(ordinal)
            if (self.confirmed(record) and prior is not None
                    and self._fact_value(facts, "hero_duel_event_identity") == self.event_identity):
                balances = (prior[0] - 1, prior[1])
        # Omitted counters retain proven facts; visible contradictions win.
        free = page.get("free_entries_remaining")
        passes = page.get("pass_balance")
        if (passes is None and page["screen_state"] in {"hero_duel_overview", "attack_formation"}
                and page.get("event_identity") == self.event_identity and page.get("event_active") is True):
            passes = self.vision.route_pass_balance
        if balances is not None:
            free = balances[0] if free is None else free
            passes = balances[1] if passes is None else passes
        return HeroDuelObservation(
            screen_state=page["screen_state"], source_frame_sha256=captured.sha256,
            evidence_refs=(f"native:{captured.path}",), overlay_state=page["overlay_state"],
            event_identity=page.get("event_identity") or "",
            event_variant=HERO_DUEL_SURVIVAL if page.get("event_identity") else "",
            event_active=page.get("event_active"), free_entries_remaining=free,
            entry_cost=0 if page.get("free_opponent_selected") else None,
            entry_cost_known=page.get("free_opponent_selected") is True,
            pass_balance=passes, excluded_hero_ids=page.get("excluded_hero_ids"),
            displayed_hero_ids=page.get("displayed_hero_ids", ()),
            defense_hero_ids=page.get("defense_hero_ids") or (
                tuple(self.result.get("expected_defense_hero_ids", ())) if self.vision.defense_saved else ()),
            defense_save_acknowledged=page.get("defense_save_acknowledged") is True,
            saved_defense_expected_hero_ids=tuple(self.result.get("expected_defense_hero_ids", ())) if self.vision.defense_saved else (),
            attack_hero_ids=page.get("attack_hero_ids", ()), attack_slots_populated=page.get("attack_slots_populated"),
            listed_opponent_free=page.get("listed_opponent_free") is True,
            free_opponent_selected=page.get("free_opponent_selected") is True,
            challenge_now_visible=any("challenge now" in row["norm"] for row in lines),
            activate_visible=any("activate" in row["norm"] for row in lines),
            premium_prompt_visible=page["overlay_state"] != "none",
            battle_board_visible=page["battle_board_visible"], wave_text="Wave 1/1" if page["battle_board_visible"] else "",
            battle_exit_visible=page["screen_state"] == "active_battle" and any(self.vision.has(row, "exit") for row in lines),
            flee_warning_visible=page["screen_state"] == "flee_warning",
            flee_control_visible=page["screen_state"] == "flee_warning" and page.get("target_identity") == "hero-duel-warning-flee",
            fight_control_visible=page["screen_state"] == "flee_warning" and any(self.vision.has(row, "fight") for row in lines),
            loss_result_visible=page["screen_state"] == "loss_result",
            tap_to_continue_visible=page["screen_state"] == "loss_result" and page.get("target_identity") == "hero-duel-loss-continue",
            cycle_battle_loaded=self.vision.battle_loaded,
            cycle_exit_confirmed=self.vision.exit_confirmed,
            cycle_flee_confirmed=page["screen_state"] == "loss_result",
            cycle_loss_result_seen=page["screen_state"] == "loss_result",
            cycle_continue_confirmed=page["screen_state"] == "hero_duel_overview",
            target_identity=page.get("target_identity") or "hero-duel-current-page", target_roi=roi,
            game_day_id=self.reset_id, entry_ordinal=ordinal,
        )

    def _effect(self, *, kind, ordinal, source_state, target_id, phrase, consequence, postcondition, expected_state,
                expected_free=None, expected_pass=None):
        key = self.action_key(ordinal, kind)
        record = self.store.get_action_by_key(key)
        if record is not None:
            if self.confirmed(record):
                return {"status": "confirmed", "reason": "canonical_action_already_confirmed", "transport_calls": 0}
            return {"status": "blocked", "reason": f"canonical_action_{record.get('final_status')}", "transport_calls": 0, "effect_reconciliation_required": True}
        if self.store.has_action_block():
            return {"status": "blocked", "reason": "canonical_unresolved_action", "transport_calls": 0, "effect_reconciliation_required": True}
        proposal = self.capture(f"hero-duel-{kind}-proposal")
        proposal_page = self.observe(proposal, (target_id, phrase))
        immediate = self.capture(f"hero-duel-{kind}-immediate")
        page = self.observe(immediate, (target_id, phrase))
        if (proposal_page["screen_state"] != source_state or page["screen_state"] != source_state
                or page["target_roi"] is None or page["overlay_state"] != "none"
                or proposal_page["target_roi"] != page["target_roi"]
                or proposal_page["overlay_state"] != "none"
                or proposal_page.get("event_identity") != self.event_identity
                or page.get("event_identity") != self.event_identity):
            return {"status": "blocked", "reason": f"{kind}_source_not_bound", "transport_calls": 0}
        game = self._observation(immediate, page, ordinal)
        dynamic_facts = {}
        if kind == "hero_duel_free_entry":
            permitted = hero_duel_entry_authorizeable(game, ordinal=ordinal, game_day_id=self.reset_id)
            dynamic_facts = {
                "free_allowance_before": game.free_entries_remaining,
                "pass_balance_before": game.pass_balance,
            }
            current_free = game.free_entries_remaining
        elif kind == "hero_duel_flee":
            permitted = hero_duel_flee_authorizeable(game, ordinal=ordinal, game_day_id=self.reset_id)
            dynamic_facts = {
                "free_allowance_at_flee": game.free_entries_remaining,
                "pass_balance_before": game.pass_balance,
            }
            current_free = game.free_entries_remaining
        else:
            permitted = (hero_duel_current_survival(game) and game.screen_state == "defense_formation"
                         and game.target_identity == target_id
                         and game.defense_hero_ids == tuple(self.result.get("expected_defense_hero_ids", ())))
            current_free = None
        if (not permitted or (expected_free is not None and current_free != expected_free)
                or (expected_pass is not None and game.pass_balance != expected_pass)):
            return {"status": "blocked", "reason": f"{kind}_semantic_guard_denied_or_balance_changed", "transport_calls": 0}
        try:
            preconditions = hero_duel_policy_preconditions(
                kind,
                event_identity=self.event_identity,
                ordinal=1 if kind == "hero_duel_save_defense" else ordinal,
                game_day_id=self.reset_id,
                **dynamic_facts,
            )
        except ValueError as exc:
            return {"status": "blocked", "reason": f"{kind}_numeric_policy_facts_unproven:{exc}", "transport_calls": 0}
        policy_source_state = {
            "attack_formation": "hero_duel_attack_formation",
            "flee_warning": "hero_duel_flee_warning",
            "defense_formation": "hero_duel_defense_formation",
        }[source_state]
        def observation(captured, observed_page):
            roi = observed_page["target_roi"]
            return Observation(frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=PROFILE_ID, width=800, height=1280, valid_png=True, corrupt=False, black=False,
                source_state=policy_source_state, overlay_state="none_observed", target_identity=target_id, target_roi=roi,
                recognized=True, control_class={"hero_duel_free_entry": "FREE_CHALLENGE",
                    "hero_duel_flee": "FLEE", "hero_duel_save_defense": "SAVE_FORM"}[kind],
                consequence=consequence, cost_type="none", cost_amount=0, quantity=1,
                expected_postcondition=postcondition, evidence_refs=(str(captured.path),),
                critical_roi_hashes=((kind, _roi_hash(captured.frame, roi)),),
                ocr_result_frame_sha256=captured.sha256,
                ocr_result_capture_completed_monotonic=captured.captured_monotonic,
                source_family="hero_duel_survival", target_isolated=True,
                package_foreground=self.runtime.measure_foreground_package() == "com.global.ztmslg")
        proposal_observation, immediate_observation = observation(proposal, proposal_page), observation(immediate, page)
        action_id = f"hero-duel-{kind}-{ordinal}-{hashlib.sha256(key.encode()).hexdigest()[:16]}"
        policy = CentralPolicy({FLOW_ID})
        def request(obs):
            return PolicyRequest(action_id=action_id, action_key=key, task_id=FLOW_ID,
                task_mode="supervised_validation", semantic_action=kind, expected_runtime_profile_id=PROFILE_ID,
                observation=obs, monotonic_now=self.context.monotonic_clock(), observation_max_age_seconds=30.0,
                dispatch_max_age_seconds=30.0, lease_owner=self.session.owner,
                lease_valid=self.store.lease_valid_for(self.session.owner, self.context.utc_clock()),
                unresolved_action=self.store.has_action_block(), duplicate_action_key=self.store.action_key_exists(key),
                game_day_id=self.reset_id, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                action_kind=kind, subject=None, maximum_cost=0, free_only=True,
                semantic_preconditions=preconditions, semantic_postconditions=(postcondition,),
                runtime_session_id=str(self.runtime.session))
        self.context.validate_identity()
        issued = policy.issue_capability(request(immediate_observation))
        self.store.audit(FLOW_ID, "capability_issued", self.context.utc_clock(), issued.audit, action_id)
        if not issued.authorized or issued.capability is None:
            return {"status": "blocked", "reason": issued.reason_code, "transport_calls": 0}
        post_frames, post_pages, first_capture = [], {}, [immediate]
        def verified(post):
            return (post["screen_state"] == expected_state and post["overlay_state"] == "none"
                and (kind != "hero_duel_save_defense"
                     or any(self.vision.has(line, "lineup saved", "formation saved") for line in post["lines"])))
        def action_capture(label):
            return first_capture.pop() if first_capture else self.capture(label)
        def transport(_intent):
            self.context.validate_identity()
            def recognize(after):
                post = self.observe(after)
                post_frames.append(after)
                post_pages[str(after.path)] = post
                return postcondition if verified(post) else "unknown"
            def settled():
                if self.settle:
                    time.sleep(self.settle)
                return self.capture(f"hero-duel-{kind}-{ordinal}-settled")
            self.session.run_action(action_class="zero_cost_consequential", label=f"hero-duel-{kind}-{ordinal}",
                capture=action_capture,
                dispatch=lambda current: self.runtime.tap(current, target_identity=target_id,
                    target_roi=page["target_roi"], action_key=key,
                    action_class="zero_cost_consequential", consequential=True),
                recognize=recognize, settled_successor=settled, consequence_class=consequence)
            return TransportResult(True, f"HERO_DUEL_{kind.upper()}_DISPATCHED")
        def post_observations():
            for current in post_frames:
                post = post_pages[str(current.path)]
                yield Observation(frame_sha256=current.sha256, capture_completed_monotonic=current.captured_monotonic,
                    runtime_profile_id=PROFILE_ID, width=800, height=1280, valid_png=True, corrupt=False, black=False,
                    source_state=post["screen_state"], overlay_state="none_observed" if post["overlay_state"] == "none" else "unknown",
                    target_identity=None, target_roi=None,
                    recognized=verified(post), evidence_refs=(str(current.path),))
        execution = SafeActionExecutor(self.store, policy, self.session.owner, self.context.monotonic_clock,
            transport, lambda: immediate_observation, post_observations,
            lambda _intent, obs: bool(post_frames and obs.frame_sha256 == post_frames[-1].sha256
                and verified(post_pages[str(post_frames[-1].path)])),
            wall_clock=self.context.utc_clock, max_pre_dispatch_attempts=1).execute(request(proposal_observation), issued.capability)
        if kind == "hero_duel_free_entry" and execution.transport_calls:
            # Reconciliation needs a fresh returned opponent-list pass reading.
            self.vision.route_pass_balance = None
        successor = post_frames[-1] if post_frames else None
        record = self.store.get_action_by_key(key)
        if successor is not None and callable(getattr(self.runtime, "reconcile", None)):
            self.runtime.reconcile(key, "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved", successor, execution.reason)
        return {"status": "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved" if execution.status is ActionStatus.UNRESOLVED else "blocked",
            "reason": execution.reason, "transport_calls": execution.transport_calls,
            "journal_status": record.get("final_status") if record else None,
            "effect_reconciliation_required": execution.status is ActionStatus.UNRESOLVED, "successor": successor}

    def _authorize_return_back(self, captured, screen):
        page = self.observe(captured)
        if page["screen_state"] != screen or page["overlay_state"] != "none":
            raise HeroDuelRecognitionError("route-owned Back source changed")

    def _return_home(self, page):
        current = page
        for ordinal in range(3):
            if current["screen_state"] == "home":
                break
            if current["screen_state"] not in {"hero_duel_overview", "defense_formation", "emergency_details", "event_select", "arena"} or current["overlay_state"] != "none":
                self.result["reason"] = "return_home_source_not_route_owned"
                return False
            source = self.capture(f"hero-duel-return-back-{ordinal}")
            if self.observe(source)["screen_state"] != current["screen_state"]:
                self.result["reason"] = "return_home_source_changed"
                return False
            post = {}
            def dispatch(before, step=ordinal):
                self.context.checkpoint()
                self.context.validate_identity()
                self.runtime.back(before, action_key=f"hero-duel:return-back:{step}:{before.sha256}",
                    target_identity="hero-duel-route-back")
            action = self.session.run_action(action_class="navigation", label=f"hero-duel-return-back-{ordinal}",
                capture=lambda _label: source,
                authorize=lambda before, screen=current["screen_state"]: self._authorize_return_back(before, screen),
                dispatch=dispatch,
                recognize=lambda after, previous=current["screen_state"]: self._recognize_return_transition(after, previous, post),
                settled_successor=lambda: self.capture(f"hero-duel-return-back-{ordinal}-settled"),
                consequence_class="navigation_only")
            if action.status != "completed" or not post.get("page"):
                self.result["reason"] = "route_owned_back_successor_unverified"
                return False
            self.return_back_count += 1
            current = post["page"]
        terminal = self.capture("hero-duel-terminal-home")
        if self.observe(terminal)["screen_state"] != "home" or not self.context.is_clean_home(terminal.frame):
            self.result["reason"] = "terminal_clean_home_not_verified"
            return False
        self.result.update(terminal_home_verified=True,
            terminal_home_frame={"frame_path": str(terminal.path), "frame_sha256": terminal.sha256},
            return_home_inputs=self.return_back_count)
        return True

    def _recognize_transition(self, captured, expected, output):
        page = self.observe(captured)
        output.update(captured=captured, page=page)
        return page["screen_state"] if page["screen_state"] in expected else "unknown"
    def _recognize_return_transition(self, captured, previous_state, output):
        page = self.observe(captured)
        output.update(captured=captured, page=page)
        allowed = {"home", "arena", "event_select", "emergency_details", "hero_duel_overview", "defense_formation"}
        if page["screen_state"] == previous_state or page["screen_state"] not in allowed:
            return "unknown"
        return page["screen_state"]

    def _inspect_exclusions(self, page):
        if page["screen_state"] == "emergency_details":
            if page["excluded_hero_ids"] is None:
                self.result["reason"] = "evidence_required:emergency_details_portrait_exclusions_unresolved"
                return None
            self.vision.excluded = tuple(page["excluded_hero_ids"])
            self.result["excluded_hero_ids"] = list(self.vision.excluded)
            exact_controls = [
                phrase for phrase in ("confirm", "close", "got it", "understood", "ok")
                if sum(_norm(line["text"]) == _norm(phrase) for line in page["lines"]) == 1
            ]
            if len(exact_controls) == 1:
                target_id, phrase = "hero-duel-emergency-dismiss", exact_controls[0]
            elif exact_controls:
                self.result["reason"] = "emergency_details_dismissal_ambiguous"
                return None
            elif self.vision.emergency_close_x_roi(page["lines"]) is not None:
                target_id, phrase = "hero-duel-emergency-close-x", "emergency close x"
            else:
                self.result["reason"] = "emergency_details_dismissal_unbound"
                return None
            step = self._navigation_tap("dismiss-emergency-details", phrase,
                {"defense_formation", "hero_duel_overview"}, target_id)
            return step["page"] if step else None
        if page["screen_state"] == "hero_duel_overview" and self.vision.excluded is None:
            step = self._navigation_tap("open-emergency-details", "emergency details",
                {"emergency_details"}, "hero-duel-event-details")
            if step is None:
                return None
            return self._inspect_exclusions(step["page"])
        return page if self.vision.excluded is not None else None

    def _prepare_defense(self, page):
        if page["screen_state"] == "hero_duel_overview":
            step = self._navigation_tap("open-defense", "defense", {"defense_formation"}, "hero-duel-defense-open")
            if step is None:
                return None
            page = step["page"]
        if page["screen_state"] != "defense_formation" or self.vision.excluded is None:
            self.result["reason"] = "defense_formation_or_exclusions_unknown"
            return None
        captured = self.capture("hero-duel-defense-source")
        page = self.observe(captured)
        expected = hero_duel_first_five_eligible(self._observation(captured, page, 1))
        if expected is None:
            self.result["reason"] = "evidence_required:first_five_eligible_defense_roster_identities_unbound"
            return None
        self.result["expected_defense_hero_ids"] = list(expected)
        prior = self.store.get_action_by_key(self.action_key(1, "hero_duel_save_defense"))
        if self.confirmed(prior):
            if page["defense_hero_ids"] != expected:
                self.result.update(status="reconciliation_required", reason="confirmed_defense_save_disagrees_with_current_lineup",
                    effect_reconciliation_required=True, identical_retry_denied=True)
                return None
            self.vision.defense_saved = True
            self.result["defense_save_confirmed"] = True
            step = self._defense_back("return-from-defense")
            return step["page"] if step else None
        if page["defense_hero_ids"] != expected:
            removable = tuple(name for name in page["defense_hero_ids"] if name not in expected)
            if not self._select_heroes(page, expected, "defense", remove=removable):
                return None
            captured = self.capture("hero-duel-defense-verify")
            page = self.observe(captured)
            if page["defense_hero_ids"] != expected:
                self.result["reason"] = "defense_first_five_not_verified"
                return None
        action = self._effect(kind="hero_duel_save_defense", ordinal=1, source_state="defense_formation",
            target_id="hero-duel-defense-save-form", phrase="save form", consequence="set_hero_duel_defense",
            postcondition="hero_duel_lineup_saved", expected_state="hero_duel_overview")
        self.result["defense_save_transport_calls"] += action["transport_calls"]
        if action["status"] != "confirmed" or action.get("successor") is None:
            dispatched = action["transport_calls"] > 0 or action.get("effect_reconciliation_required", False)
            self.result.update(status="reconciliation_required" if dispatched else "blocked",
                reason=action.get("reason", "defense_save_unconfirmed"),
                effect_reconciliation_required=action.get("effect_reconciliation_required", False),
                identical_retry_denied=dispatched)
            return None
        self.vision.defense_saved = True
        self.result["defense_save_confirmed"] = True
        return self.observe(action["successor"])

    def _select_heroes(self, page, names, mode, *, remove=()):
        state = "defense_formation" if mode == "defense" else "attack_formation"
        current = tuple(page["defense_hero_ids"] if mode == "defense" else page["attack_hero_ids"])
        selected = [(name, False) for name in remove if name in current]
        selected.extend((name, True) for name in names if name not in current or name in remove)
        for name, add in selected:
            source = self.capture(f"hero-duel-{mode}-selection-source")
            observed = self.observe(source)
            roi = self.vision.hero_selection_roi(observed["lines"], name, state, add=add)
            if roi is None:
                self.result["reason"] = f"{mode}_hero_target_not_uniquely_bound"
                return False
            output = {}
            before_input_count = self.session.input_count
            try:
                action = self.session.run_action(action_class="navigation", label=f"hero-duel-{mode}-select", capture=lambda _label: source,
                    authorize=lambda before, hero=name, box=roi, add_target=add:
                        self._authorize_hero(before, state, hero, box, add=add_target),
                    dispatch=lambda before, hero=name, box=roi: self.runtime.tap(before,
                        target_identity=f"hero-duel-{mode}-hero:{hashlib.sha256(hero.encode()).hexdigest()[:16]}", target_roi=box,
                        action_key=f"hero-duel:{mode}:{'add' if add else 'remove'}:{hashlib.sha256(hero.encode()).hexdigest()}:{before.sha256}"),
                    recognize=lambda after: self._recognize_transition(after, {state}, output),
                    settled_successor=lambda: self.capture(f"hero-duel-{mode}-select-settled"), consequence_class="navigation_only")
            finally:
                if mode == "defense":
                    self.result["defense_selection_transport_calls"] += max(
                        0, self.session.input_count - before_input_count)
            if action.status != "completed":
                self.result["reason"] = f"{mode}_hero_selection_successor_unverified"
                return False
            if add:
                current = (*current, name)
            else:
                current = tuple(hero for hero in current if hero != name)
        return True

    def _authorize_hero(self, captured, state, name, roi, *, add):
        page = self.observe(captured)
        if (page["screen_state"] != state
                or self.vision.hero_selection_roi(page["lines"], name, state, add=add) != roi
                or page["overlay_state"] != "none"):
            raise HeroDuelRecognitionError("Hero Duel hero selection target changed")

    def _cycle(self, ordinal, overview):
        self.overview_balances = (overview.free_entries_remaining, overview.pass_balance)
        page = self.observe(self.capture(f"hero-duel-cycle-{ordinal}-source"))
        if page["screen_state"] == "hero_duel_overview":
            step = self._navigation_tap(f"challenge-now-{ordinal}", "challenge",
                {"challenge_upsell", "opponent_list", "attack_formation"}, "hero-duel-overview-challenge")
            if step is None:
                return False
            page = step["page"]
        if page["screen_state"] == "challenge_upsell":
            step = self._navigation_tap(f"free-challenge-path-{ordinal}", "challenge now",
                {"opponent_list", "attack_formation"}, "hero-duel-challenge-now")
            if step is None:
                return False
            page = step["page"]
        selected_opponent_display = None
        if page["screen_state"] == "opponent_list":
            source = self.capture(f"hero-duel-free-opponent-source-{ordinal}")
            current = self.observe(source)
            row = self.vision.first_free_opponent_row(current["lines"])
            if (current["screen_state"] != "opponent_list" or current["overlay_state"] != "none"
                    or current.get("event_identity") != self.event_identity or row is None):
                self.result["reason"] = "listed_free_opponent_not_uniquely_bound"
                return False
            roi = row["free_button_roi"]
            selected_opponent_display = row["text"]
            after = {}
            action = self.session.run_action(action_class="navigation", label=f"hero-duel-select-free-opponent-{ordinal}",
                capture=lambda _label: source,
                authorize=lambda before: self._authorize_free_opponent(before, roi),
                dispatch=lambda before: self.runtime.tap(before, target_identity="hero-duel-free-opponent", target_roi=roi,
                    action_key=f"hero-duel:free-opponent:{ordinal}:{before.sha256}"),
                recognize=lambda captured: self._recognize_transition(captured, {"attack_formation"}, after),
                settled_successor=lambda: self.capture(f"hero-duel-free-opponent-settled-{ordinal}"), consequence_class="navigation_only")
            if action.status != "completed" or not after:
                self.result["reason"] = "free_opponent_selection_unverified"
                return False
            self.vision.free_opponent_selected = True
            self.result["selected_listed_opponents"].append(selected_opponent_display)
            page = after["page"]
        if page["screen_state"] != "attack_formation" or not self.vision.free_opponent_selected or page["overlay_state"] != "none":
            self.result["reason"] = "attack_formation_or_free_opponent_unknown"
            return False
        captured = self.capture(f"hero-duel-attack-source-{ordinal}")
        page = self.observe(captured)
        semantic = self._observation(captured, page, ordinal)
        fill = hero_duel_attack_fill(semantic)
        remove_attack = ()
        if fill is None:
            eligible = hero_duel_first_five_eligible(semantic)
            selected = tuple(semantic.attack_hero_ids)
            if (eligible is None or len(set(selected)) != len(selected)
                    or semantic.attack_slots_populated != len(selected) or not 0 <= len(selected) <= 5
                    or any(hero not in semantic.displayed_hero_ids for hero in selected)):
                self.result["reason"] = "attack_lineup_or_exclusions_unreadable"
                return False
            remove_attack = tuple(hero for hero in selected if hero not in eligible)
            remaining = tuple(hero for hero in selected if hero not in remove_attack)
            missing = 5 - len(remaining)
            fill = tuple(hero for hero in eligible if hero not in remaining)[:missing]
            if not remove_attack or len(fill) != missing:
                self.result["reason"] = "attack_lineup_cannot_be_completed_without_ambiguous_removal"
                return False
        if fill or remove_attack:
            if not self._select_heroes(page, fill, "attack", remove=remove_attack):
                return False
            captured = self.capture(f"hero-duel-attack-verify-{ordinal}")
            page = self.observe(captured)
            semantic = self._observation(captured, page, ordinal)
        if (not hero_duel_attack_lineup_valid(semantic) or semantic.free_entries_remaining is None
                or semantic.free_entries_remaining <= 0 or semantic.pass_balance is None
                or semantic.entry_cost_known is not True or semantic.entry_cost != 0):
            self.result["reason"] = "free_cost_pass_or_five_attack_slots_not_proven"
            return False
        entry = self._effect(kind="hero_duel_free_entry", ordinal=ordinal, source_state="attack_formation",
            target_id="hero-duel-attack-challenge", phrase="challenge",
            consequence="bounded_hero_duel_participation", postcondition="hero_duel_battle_loaded", expected_state="active_battle",
            expected_free=semantic.free_entries_remaining, expected_pass=semantic.pass_balance)
        self.result["entry_transport_calls"] += entry["transport_calls"]
        self.result["duel_dispatch_count"] += entry["transport_calls"]
        if entry["status"] != "confirmed" or entry.get("successor") is None:
            dispatched = entry["transport_calls"] > 0 or entry.get("effect_reconciliation_required", False)
            self.result.update(status="reconciliation_required" if dispatched else "blocked",
                reason=entry.get("reason", "battle_load_unconfirmed"),
                effect_reconciliation_required=entry.get("effect_reconciliation_required", False),
                identical_retry_denied=dispatched)
            return False
        battle = self.observe(entry["successor"])
        if battle["screen_state"] != "active_battle" or not battle["battle_board_visible"]:
            self.result.update(status="reconciliation_required", reason="match3_battle_wave_1_1_not_verified",
                effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        self.vision.battle_loaded = True
        exit_step = self._navigation_tap("battle-exit", "exit", {"flee_warning"}, "hero-duel-battle-exit")
        if exit_step is None:
            self.result.update(status="reconciliation_required", effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        self.vision.exit_confirmed = True
        warning_capture = self.capture(f"hero-duel-flee-warning-{ordinal}")
        warning_page = self.observe(warning_capture, ("hero-duel-warning-flee", "flee"))
        warning = self._observation(warning_capture, warning_page, ordinal)
        if (not hero_duel_flee_authorizeable(warning, ordinal=ordinal, game_day_id=self.reset_id)
                or warning.free_entries_remaining != overview.free_entries_remaining - 1
                or warning.pass_balance != overview.pass_balance):
            self.result.update(status="reconciliation_required", reason="flee_warning_or_current_free_pass_not_verified",
                effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        flee = self._effect(kind="hero_duel_flee", ordinal=ordinal, source_state="flee_warning",
            target_id="hero-duel-warning-flee", phrase="flee", consequence="accept_hero_duel_loss",
            postcondition="hero_duel_loss_result", expected_state="loss_result",
            expected_free=warning.free_entries_remaining, expected_pass=overview.pass_balance)
        self.result["flee_transport_calls"] += flee["transport_calls"]
        if flee["status"] != "confirmed" or flee.get("successor") is None:
            dispatched = flee["transport_calls"] > 0 or flee.get("effect_reconciliation_required", False)
            self.result.update(status="reconciliation_required" if dispatched else "blocked",
                reason=flee.get("reason", "loss_result_unconfirmed"),
                effect_reconciliation_required=flee.get("effect_reconciliation_required", False),
                identical_retry_denied=True)
            return False
        self.result["flee_confirmed_count"] += 1
        result_page = self.observe(flee["successor"], ("hero-duel-loss-continue", "tap to continue"))
        if result_page["screen_state"] != "loss_result" or result_page["target_roi"] is None:
            self.result.update(status="reconciliation_required", reason="loss_result_or_continue_target_unbound",
                effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        step = self._continue_to_overview("loss-continue")
        if step is None:
            self.result.update(status="reconciliation_required", effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        after_capture = self.capture(f"hero-duel-cycle-{ordinal}-after")
        after_page = self.observe(after_capture)
        after = self._observation(after_capture, after_page, ordinal)
        if (not hero_duel_current_survival(after) or after.event_identity != self.event_identity
                or after.free_entries_remaining != overview.free_entries_remaining - 1
                or after.pass_balance != overview.pass_balance):
            self.result.update(status="reconciliation_required", reason="cycle_event_free_delta_or_pass_balance_not_verified",
                effect_reconciliation_required=True, identical_retry_denied=True)
            return False
        self.result["cycle_proofs"].append({
            "ordinal": ordinal, "reset_id": self.reset_id, "event_identity": self.event_identity,
            "listed_opponent_display": selected_opponent_display,
            "entry_action_key": self.action_key(ordinal, "hero_duel_free_entry"),
            "flee_action_key": self.action_key(ordinal, "hero_duel_flee"),
            "free_before": overview.free_entries_remaining, "free_after": after.free_entries_remaining,
            "pass_before": overview.pass_balance, "pass_after": after.pass_balance,
            "wave_text": "Wave 1/1", "battle_board_verified": True,
            "exit_confirmed": True, "flee_confirmed": True, "loss_result_seen": True,
            "tap_to_continue_confirmed": True, "result_frame_sha256": after_capture.sha256,
        })
        self.vision.free_opponent_selected = False
        self.vision.battle_loaded = False
        self.vision.exit_confirmed = False
        return True

    def _authorize_free_opponent(self, current, expected_roi):
        page = self.observe(current)
        row = self.vision.first_free_opponent_row(page["lines"])
        if (page["screen_state"] != "opponent_list" or page["overlay_state"] != "none"
                or page.get("event_identity") != self.event_identity
                or row is None or row["free_button_roi"] != expected_roi):
            raise HeroDuelRecognitionError("first listed Free opponent changed")

    def _defense_back(self, label):
        source = self.capture(f"hero-duel-{label}-source")
        if self.observe(source)["screen_state"] != "defense_formation":
            self.result["reason"] = "defense_back_source_not_route_owned"
            return None
        after = {}
        action = self.session.run_action(
            action_class="navigation", label=f"hero-duel-{label}",
            capture=lambda _label: source,
            authorize=lambda current: self._authorize_return_back(current, "defense_formation"),
            dispatch=lambda current: self.runtime.back(current,
                action_key=f"hero-duel:{label}:{current.sha256}", target_identity="hero-duel-defense-back"),
            recognize=lambda current: self._recognize_transition(current, {"hero_duel_overview"}, after),
            settled_successor=lambda: self.capture(f"hero-duel-{label}-settled"),
            consequence_class="navigation_only")
        if action.status != "completed" or not after:
            self.result["reason"] = "defense_back_successor_unverified"
            return None
        self.result["navigation_input_count"] += 1
        return after

    def _continue_to_overview(self, label, *, page=None):
        if page is None or page["screen_state"] == "loss_result":
            step = self._navigation_tap(label, "tap to continue",
                {"opponent_list", "hero_duel_overview"}, "hero-duel-loss-continue")
            if step is None:
                return None
            page = step["page"]
        if page["screen_state"] == "opponent_list":
            return self._navigation_tap(label + "-opponents-close", "close",
                {"hero_duel_overview"}, "hero-duel-opponents-close")
        return {"page": page} if page["screen_state"] == "hero_duel_overview" else None

    def _resume_active_cycle(self, page, ordinal):
        entry_ok, flee_ok = self.cycle_receipts(ordinal)
        proof = self._prior_free_pass_proof(ordinal)
        entry_record = self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_free_entry"))
        event_facts = self._record_preconditions(entry_record)
        entry_event = next((item.split("=", 1)[1] for item in event_facts
                            if item.startswith("hero_duel_event_identity=")), None)
        if (not entry_ok or not self.event_identity or entry_event != self.event_identity
                or proof is None or proof[0] != 4 - ordinal or type(proof[1]) is not int):
            self.result.update(status="reconciliation_required", reason="active_cycle_has_no_exact_confirmed_entry_event_or_balance_proof", effect_reconciliation_required=True)
            return self._finish(page)
        self.vision.current_event_valid = True
        if page["screen_state"] == "active_battle":
            if not HeroDuelVision.board_visible(self.context.initial_frame.frame) or "wave 1 1" not in _norm(page["text"]):
                self.result.update(status="reconciliation_required", reason="restart_battle_wave_not_exact", effect_reconciliation_required=True)
                return self._finish(page)
            self.vision.battle_loaded = True
            step = self._navigation_tap("restart-battle-exit", "exit", {"flee_warning"}, "hero-duel-battle-exit")
            if step is None:
                return self._finalize()
            page = step["page"]
        if page["screen_state"] == "flee_warning" and not flee_ok:
            self.vision.battle_loaded = True
            self.vision.exit_confirmed = True
            warning_capture = self.capture("hero-duel-restart-flee-warning")
            warning_page = self.observe(warning_capture, ("hero-duel-warning-flee", "flee"))
            warning = self._observation(warning_capture, warning_page, ordinal)
            if (not hero_duel_flee_authorizeable(warning, ordinal=ordinal, game_day_id=self.reset_id)
                    or warning.free_entries_remaining != proof[0] - 1
                    or warning.pass_balance != proof[1]):
                self.result.update(status="reconciliation_required", reason="restart_flee_warning_or_balance_not_authorizeable", effect_reconciliation_required=True)
                return self._finish(page)
            flee = self._effect(kind="hero_duel_flee", ordinal=ordinal, source_state="flee_warning",
                target_id="hero-duel-warning-flee", phrase="flee", consequence="accept_hero_duel_loss",
                postcondition="hero_duel_loss_result", expected_state="loss_result",
                expected_free=warning.free_entries_remaining, expected_pass=proof[1])
            self.result["flee_transport_calls"] += flee["transport_calls"]
            if flee["status"] != "confirmed" or flee.get("successor") is None:
                self.result.update(status="reconciliation_required", reason=flee.get("reason", "restart_flee_unconfirmed"), effect_reconciliation_required=True,
                    identical_retry_denied=flee["transport_calls"] > 0 or flee.get("effect_reconciliation_required", False))
                return self._finalize()
            self.result["flee_confirmed_count"] += 1
            page = self.observe(flee["successor"], ("hero-duel-loss-continue", "tap to continue"))
        if page["screen_state"] in {"loss_result", "opponent_list"} and (flee_ok or self.confirmed(self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_flee")))):
            self.result["flee_confirmed_count"] = 1
            step = self._continue_to_overview("restart-loss-continue", page=page)
            if step is None:
                return self._finalize()
            overview_capture = self.capture("hero-duel-restart-overview")
            overview_page = self.observe(overview_capture)
            overview = self._observation(overview_capture, overview_page, ordinal)
            timer_fresh = overview_page.get("event_timer_visible") and overview_page.get("event_active") is True
            canonical = [item for item in range(1, 4) if all(self.cycle_receipts(item))]
            if (not timer_fresh or overview.event_identity != self.event_identity
                    or overview.free_entries_remaining != proof[0] - 1 or overview.pass_balance != proof[1]
                    or canonical != list(range(1, ordinal + 1))
                    or not self._canonical_proofs_match(canonical, overview.pass_balance)):
                self.result.update(status="reconciliation_required", reason="restart_cycle_missing_fresh_exact_event_free_pass_proof", effect_reconciliation_required=True)
                return self._finish(overview_page)
            self.result["cycle_proofs"].append({
                "ordinal": ordinal, "reset_id": self.reset_id, "event_identity": self.event_identity,
                "entry_action_key": self.action_key(ordinal, "hero_duel_free_entry"),
                "flee_action_key": self.action_key(ordinal, "hero_duel_flee"),
                "free_before": proof[0], "free_after": overview.free_entries_remaining,
                "pass_before": proof[1], "pass_after": overview.pass_balance,
                "wave_text": "Wave 1/1", "restart_reconciled": True, "battle_board_verified": True,
                "exit_confirmed": True, "flee_confirmed": True, "loss_result_seen": True,
                "tap_to_continue_confirmed": True,
            })
            self._retain_canonical_cycle_proofs(canonical, overview.pass_balance)
            disposition = "deferred" if overview.free_entries_remaining > 0 else (
                "complete_for_reset" if canonical == [1, 2, 3] else "reconciliation_required")
            self.result.update(status=disposition, reason="partial_cycle_reconciled_from_canonical_effects",
                canonical_confirmed_cycle_ordinals=canonical, final_free_entries_remaining=overview.free_entries_remaining,
                final_pass_balance=overview.pass_balance, hero_duel_event_identity=self.event_identity,
                current_event_active=True)
            self.result["availability_observed_at_utc"] = self.context.utc_clock()
            if disposition == "reconciliation_required":
                self.result["effect_reconciliation_required"] = True
            return self._finish(overview_page)
        self.result.update(status="reconciliation_required", reason="restart_cycle_screen_or_canonical_stage_conflict", effect_reconciliation_required=True)
        return self._finish(page)

    def _prior_free_pass_proof(self, ordinal):
        record = self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_free_entry"))
        if not record:
            return None
        try:
            request = json.loads(record.get("policy_request_json") or "null")
            facts = request.get("semantic_preconditions", ()) if isinstance(request, dict) else ()
            free = next((int(item.split("=", 1)[1]) for item in facts if isinstance(item, str) and item.startswith("hero_duel_free_allowance_before=")), None)
            passes = next((int(item.split("=", 1)[1]) for item in facts if isinstance(item, str) and item.startswith("hero_duel_pass_balance_before=")), None)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return (free, passes) if type(free) is int and type(passes) is int else None

    @staticmethod
    def _fact_value(facts, key):
        prefix = key + "="
        values = [item[len(prefix):] for item in facts if item.startswith(prefix)]
        return values[0] if len(values) == 1 else None

    @classmethod
    def _fact_int(cls, facts, key):
        value = cls._fact_value(facts, key)
        return int(value) if isinstance(value, str) and value.isdigit() else None

    def _canonical_proofs_match(self, ordinals, current_pass):
        if type(current_pass) is not int or current_pass < 0:
            return False
        for ordinal in ordinals:
            entry = self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_free_entry"))
            flee = self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_flee"))
            if not self.confirmed(entry) or not self.confirmed(flee):
                return False
            entry_facts, flee_facts = self._record_preconditions(entry), self._record_preconditions(flee)
            if (self._fact_value(entry_facts, "hero_duel_event_identity") != self.event_identity
                    or self._fact_value(flee_facts, "hero_duel_event_identity") != self.event_identity
                    or self._fact_value(entry_facts, "hero_duel_entry_reset") != self.reset_id
                    or self._fact_value(flee_facts, "hero_duel_entry_reset") != self.reset_id
                    or self._fact_int(entry_facts, "hero_duel_entry_ordinal") != ordinal
                    or self._fact_int(flee_facts, "hero_duel_entry_ordinal") != ordinal
                    or self._fact_int(entry_facts, "hero_duel_free_allowance_before") != 4 - ordinal
                    or self._fact_int(flee_facts, "hero_duel_free_allowance_at_flee") != 3 - ordinal
                    or self._fact_int(entry_facts, "hero_duel_pass_balance_before") != current_pass
                    or self._fact_int(flee_facts, "hero_duel_pass_balance_before") != current_pass):
                return False
        return True

    def cycle_receipts(self, ordinal):
        return (self.confirmed(self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_free_entry"))),
                self.confirmed(self.store.get_action_by_key(self.action_key(ordinal, "hero_duel_flee"))))

    def _retain_canonical_cycle_proofs(self, ordinals, current_pass):
        """Reopen a prefix only against exact receipts and reconciled counters."""
        if not self._canonical_proofs_match(ordinals, current_pass):
            return
        existing = {proof["ordinal"] for proof in self.result["cycle_proofs"]}
        for ordinal in ordinals:
            if ordinal in existing:
                continue
            self.result["cycle_proofs"].append({
                "ordinal": ordinal, "reset_id": self.reset_id, "event_identity": self.event_identity,
                "entry_action_key": self.action_key(ordinal, "hero_duel_free_entry"),
                "flee_action_key": self.action_key(ordinal, "hero_duel_flee"),
                "free_before": 4 - ordinal, "free_after": 3 - ordinal,
                "pass_before": current_pass, "pass_after": current_pass,
                "wave_text": "Wave 1/1", "battle_board_verified": True,
                "exit_confirmed": True, "flee_confirmed": True, "loss_result_seen": True,
                "tap_to_continue_confirmed": True, "canonical_receipts_reconciled": True,
            })
        self.result["cycle_proofs"].sort(key=lambda proof: proof["ordinal"])

    def _finish(self, page):
        if page["screen_state"] in {"home", "hero_duel_overview", "defense_formation", "emergency_details", "event_select", "arena"}:
            self._return_home(page)
        return self._finalize()

    def run(self):
        self.context.checkpoint()
        first = self.context.initial_frame
        self.event_identity = self.stored_event_identity()
        self.vision.event_identity = self.event_identity
        page = self.observe(first)
        self.context.bind_initial_observation(first, extra={"hero_duel_start_screen": page["screen_state"]})
        if self.store.has_action_block():
            self.result.update(status="reconciliation_required", reason="canonical_unresolved_action",
                effect_reconciliation_required=True, identical_retry_denied=True)
            return self._finalize()
        if page["screen_state"] in {"active_battle", "flee_warning", "loss_result", "opponent_list"}:
            pending = [ordinal for ordinal in range(1, 4)
                       if self.cycle_receipts(ordinal)[0] and not self.cycle_receipts(ordinal)[1]]
            finished = [ordinal for ordinal in range(1, 4)
                        if self.cycle_receipts(ordinal)[0] and self.cycle_receipts(ordinal)[1]]
            ordinal = pending[0] if len(pending) == 1 else (finished[-1] if page["screen_state"] in {"loss_result", "opponent_list"} and finished else 0)
            if not ordinal:
                self.result.update(status="reconciliation_required", reason="active_cycle_canonical_ordinal_ambiguous", effect_reconciliation_required=True)
                return self._finalize()
            return self._resume_active_cycle(page, ordinal)
        if page["screen_state"] == "home":
            entered = self._atlas_arena()
            if entered is None:
                self._return_home(page)
                return self._finalize()
            page = entered["page"]
        elif page["screen_state"] not in {"arena", "event_select", "emergency_details", "defense_formation", "hero_duel_overview"}:
            self.result["reason"] = "fresh_home_or_known_route_state_required"
            return self._finalize()
        if page["screen_state"] in {"arena", "event_select"}:
            source = self.capture("hero-duel-current-survival-event")
            page = self.observe(source)
            if (not page.get("event_timer_visible") or not page["event_identity"]
                    or page["event_active"] is not True or page["overlay_state"] == "event_identity_changed"):
                self.result["reason"] = "current_survival_event_identity_or_timer_unproven"
                return self._finish(page)
            if self.event_identity and page["event_identity"] != self.event_identity:
                self.result.update(status="reconciliation_required", reason="canonical_same_reset_event_identity_changed", effect_reconciliation_required=True)
                return self._finish(page)
            self.event_identity = page["event_identity"]
            self.vision.event_identity = self.event_identity
            self.vision.current_event_valid = True
            self.result["hero_duel_event_identity"] = self.event_identity
            selected = self._navigation_tap("select-current-survival", "hero duel survival",
                {"event_select", "emergency_details", "defense_formation", "hero_duel_overview"}, "hero-duel-current-survival-event")
            if selected is None:
                return self._finish(page)
            page = selected["page"]
        else:
            if (not page.get("event_timer_visible") or page.get("event_active") is not True
                    or not page.get("event_identity") or page["overlay_state"] == "event_identity_changed"):
                self.result["reason"] = "restart_requires_fresh_current_survival_event_timer"
                return self._finish(page)
            if self.event_identity and page["event_identity"] != self.event_identity:
                self.result.update(status="reconciliation_required", reason="canonical_same_reset_event_identity_changed", effect_reconciliation_required=True)
                return self._finish(page)
            self.event_identity = page["event_identity"]
            self.vision.event_identity = self.event_identity
            self.vision.current_event_valid = True
            self.result["hero_duel_event_identity"] = self.event_identity
        if page["screen_state"] == "defense_formation" and self.vision.excluded is None:
            step = self._defense_back("defense-return-overview")
            if step is None:
                return self._finish(page)
            page = step["page"]
        if page["screen_state"] == "emergency_details" or (page["screen_state"] == "hero_duel_overview" and self.vision.excluded is None):
            page = self._inspect_exclusions(page)
            if page is None:
                return self._finish(page or self.observe(self.capture("hero-duel-exclusions-blocked")))
        if page["screen_state"] in {"defense_formation", "hero_duel_overview"}:
            page = self._prepare_defense(page)
            if page is None:
                return self._finish(self.observe(self.capture("hero-duel-defense-blocked")))
        if page["screen_state"] != "hero_duel_overview" or not self.event_identity or self.vision.excluded is None:
            self.result["reason"] = "survival_overview_event_or_exclusions_unverified"
            return self._finish(page)
        overview_capture = self.capture("hero-duel-free-and-pass-source")
        page = self.observe(overview_capture)
        if page.get("pass_balance") is None and self.vision.route_pass_balance is None:
            step = self._navigation_tap("allowance-pass-opponents", "challenge",
                {"challenge_upsell", "opponent_list"}, "hero-duel-overview-challenge")
            if step and step["page"]["screen_state"] == "challenge_upsell":
                step = self._navigation_tap("allowance-pass-free-path", "challenge now",
                    {"opponent_list"}, "hero-duel-challenge-now")
            if not step or self.vision.route_pass_balance is None:
                self.result["reason"] = "current_pass_balance_unobserved"
                return self._finish(step["page"] if step else page)
            closed = self._navigation_tap("allowance-pass-close", "close",
                {"hero_duel_overview"}, "hero-duel-opponents-close")
            if closed is None:
                return self._finalize()
            overview_capture = self.capture("hero-duel-free-and-pass-rebound")
            page = self.observe(overview_capture)
        overview = self._observation(overview_capture, page, 1)
        free = overview.free_entries_remaining
        if type(free) is not int or not 0 <= free <= 3:
            self.result["reason"] = "current_free_allowance_unknown_or_out_of_range"
            return self._finish(page)
        if type(overview.pass_balance) is not int or overview.pass_balance < 0:
            self.result["reason"] = "current_pass_balance_unobserved"
            return self._finish(page)
        used = 3 - free
        canonical = [ordinal for ordinal in range(1, 4) if all(self.cycle_receipts(ordinal))]
        partial = [ordinal for ordinal in range(1, 4) if any(self.cycle_receipts(ordinal)) and not all(self.cycle_receipts(ordinal))]
        self.result.update(initial_free_entries_remaining=free, ui_inferred_prior_uses=used,
                           initial_pass_balance=overview.pass_balance, canonical_confirmed_cycle_ordinals=canonical,
                           hero_duel_event_identity=self.event_identity, current_event_active=True)
        if (partial or used != len(canonical) or canonical != list(range(1, used + 1))
                or not self._canonical_proofs_match(canonical, overview.pass_balance)):
            self.result.update(status="reconciliation_required", reason="current_reset_usage_lacks_matching_complete_canonical_event_free_pass_proofs", effect_reconciliation_required=True)
            return self._finish(page)
        self._retain_canonical_cycle_proofs(canonical, overview.pass_balance)
        self.result.update(final_free_entries_remaining=free, final_pass_balance=overview.pass_balance)
        self.result["availability_observed_at_utc"] = self.context.utc_clock()
        if free == 0:
            if canonical == [1, 2, 3]:
                self.result.update(status="already_complete", reason="three_current_reset_cycles_canonically_confirmed", no_work=True)
            else:
                self.result.update(status="reconciliation_required", reason="allowance_exhausted_without_three_confirmed_cycles", effect_reconciliation_required=True, no_work=True)
            return self._finish(page)
        entries_available = free
        for ordinal in range(len(canonical) + 1, len(canonical) + entries_available + 1):
            before_capture = self.capture(f"hero-duel-cycle-{ordinal}-overview-before")
            before_page = self.observe(before_capture)
            before = self._observation(before_capture, before_page, ordinal)
            if (not hero_duel_current_survival(before) or before.event_identity != self.event_identity
                    or before.free_entries_remaining != 4 - ordinal or before.free_entries_remaining != free
                    or before.pass_balance != overview.pass_balance):
                self.result.update(status="reconciliation_required", reason="event_allowance_or_pass_changed_before_entry", effect_reconciliation_required=True)
                break
            if not self._cycle(ordinal, before):
                break
            free -= 1
        terminal_capture = self.capture("hero-duel-terminal-route-source")
        terminal_page = self.observe(terminal_capture)
        if terminal_page["screen_state"] in {"hero_duel_overview", "defense_formation", "emergency_details", "event_select", "arena"}:
            home = self._return_home(terminal_page)
        else:
            home = False
            self.result["reason"] = self.result.get("reason") or "terminal_route_state_unknown"
        final_free = terminal_page.get("free_entries_remaining")
        final_pass = self._observation(terminal_capture, terminal_page, 3).pass_balance
        self.result.update(final_free_entries_remaining=final_free, final_pass_balance=final_pass)
        if (not home or type(final_free) is not int or not 0 <= final_free <= 3
                or type(final_pass) is not int or final_pass != overview.pass_balance
                or terminal_page.get("event_identity") != self.event_identity
                or terminal_page.get("overlay_state") == "event_identity_changed"):
            if self.result.get("status") not in {"reconciliation_required", "unresolved"}:
                self.result.update(status="blocked", reason=self.result.get("reason") or "terminal_home_free_pass_or_event_not_verified")
            return self._finalize()
        canonical = [ordinal for ordinal in range(1, 4) if all(self.cycle_receipts(ordinal))]
        self.result["canonical_confirmed_cycle_ordinals"] = canonical
        self.result["availability_observed_at_utc"] = self.context.utc_clock()
        if canonical == [1, 2, 3] and final_free == 0 and self._canonical_proofs_match(canonical, final_pass):
            self.result.update(status="complete_for_reset", reason="three_canonical_free_loss_cycles_and_home_verified", no_work=False)
        elif final_free == 0:
            self.result.update(status="reconciliation_required", reason="free_allowance_exhausted_before_three_canonical_cycles", effect_reconciliation_required=True)
        elif self.result.get("status") not in {"reconciliation_required", "unresolved", "blocked"}:
            self.result.update(status="blocked", reason="current_reset_route_did_not_complete_or_verify_all_free_cycles")
        return self._finalize()

    def _finalize(self):
        if self.result.get("status") == "blocked":
            self.session.blocker = str(self.result["reason"])
        accounting = self.context.accounting()
        self.result.update(flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            reset_id=self.reset_id,
            total_input_count=accounting.input_count, input_accounting_verified=accounting.verified,
            accounting_verified=accounting.verified,
            committed_action_count=max(len(self.result["cycle_proofs"]), self.result["entry_transport_calls"], self.result["flee_transport_calls"]),
            effect_reconciliation_required=bool(self.result.get("effect_reconciliation_required")),
            identical_retry_denied=bool(self.result.get("identical_retry_denied")))
        return self.result


def driver(context, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    token = OCR_CHECKPOINT.set(context.checkpoint)
    try:
        return HeroDuelNativeFlow(context, arguments).run()
    finally:
        OCR_CHECKPOINT.reset(token)


def create_service_binding(make_native_route_binding):
    if not callable(make_native_route_binding):
        raise TypeError("Hero Duel requires the shared native route binding factory")
    return make_native_route_binding(flow_id=FLOW_ID, product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION, runtime_profile_id=PROFILE_ID,
        owner="automation-service:hero-duel", workflow="hero-duel-survival",
        max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS, driver=driver,
        validator=_validate_native_request, lease_seconds=3600.0)


def _validate_native_request(request) -> None:
    if (request.flow_id, request.product_id, request.product_revision, request.runtime_profile_id) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
        raise ValueError("Hero Duel native request product/profile identity is not exact")
    identity = request.identity
    if getattr(identity, "task_id", None) != PRODUCT_ID or not getattr(identity, "reset_id", None):
        raise ValueError("Hero Duel requires its current canonical scheduler identity")
    if not isinstance(request.occurrence_key, str) or not request.occurrence_key.strip():
        raise ValueError("Hero Duel requires the actual service occurrence key")
    if request.max_inputs != MAX_INPUTS or request.max_actions != MAX_ACTIONS:
        raise ValueError("Hero Duel native input/action budgets differ from the fixed route")
    lock = request.runtime_input_lock
    if not getattr(lock, "held", False) or getattr(lock, "owner", None) != "automation-service":
        raise ValueError("Hero Duel requires the actual held AutomationService input lock")
