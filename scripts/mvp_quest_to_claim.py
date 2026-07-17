#!/usr/bin/env python3
"""Task-scoped live adapter for one supervised quest-to-claim trial.

All game input is dispatched only by SafeActionExecutor through the injected ADBTransport.
There are no retries, generic input service, scheduler, or unattended loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import cv2
import pytesseract

from safe_action_core import (
    ALLIANCE_FORT_WAVE_ALERT,
    ActionClass,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
    alliance_fort_dismissal_allowed,
    classify_popup_semantics,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from daily_quest_bootstrap import (
    recognize_bioenhancer,
    recognize_daily_quest,
    recognize_home,
    recognize_quest,
    recognize_supply_depot,
    valid_png_frame,
)
from navigation_recognition import (
    QUEST_TAB_ROI,
    recognize_daily_selected,
    recognize_home_quest,
    recognize_local_state,
)
from startup_normalization import classify_cash_mall, load_frame
from promotional_escape import (
    PROMOTIONAL_BACK_TARGET_ROI,
    PROMOTIONAL_FORBIDDEN_REGIONS,
    PROMOTIONAL_STATE,
    classify_promotional_back,
)

KNOWN_PROMOTIONAL_SUCCESSORS = frozenset({
    "CASH_MALL", "HOME_BASE", "QUEST", "DAILY_QUEST", PROMOTIONAL_STATE,
})

PROFILE_ID = "pns-blissos-poc-virgl-800x1280-v1"
TASK_ID = "MVP-QUEST-TO-CLAIM"
ALLIANCE_FORT_POPUP_REGION = (60, 300, 740, 760)
ALLIANCE_FORT_X_REGION = (620, 360, 735, 455)
ALLIANCE_FORT_X_TARGET = "alliance-fort-wave-dismiss-x"
ALLIANCE_FORT_SUCCESSOR = "ALLIANCE_FORT_DISMISSED"
DAILY_BIOENHANCER_GO_TARGET = "daily-bioenhancer-go"
DAILY_CLAIM_TARGET = "daily-quest-claim"


def recognize_alliance_fort_wave(frame: Any) -> Dict[str, Any]:
    """Recognize exact Alliance Fort wave semantics and bind its X control."""
    if getattr(frame, "shape", ()) != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}
    x0, y0, x1, y1 = ALLIANCE_FORT_POPUP_REGION
    body = cv2.resize(frame[y0:y1, x0:x1], None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    body_text = " ".join(pytesseract.image_to_string(body, config="--psm 6").lower().split())
    popup_identity = classify_popup_semantics("", body_text)
    x0, y0, x1, y1 = ALLIANCE_FORT_X_REGION
    x_crop = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(x_crop, cv2.COLOR_BGR2GRAY)
    white = cv2.inRange(gray, 210, 255)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(white)
    candidates = [
        tuple(int(value) for value in stats[index])
        for index in range(1, count)
        if stats[index, 4] >= 250
        and 20 <= stats[index, 2] <= 60
        and 20 <= stats[index, 3] <= 60
    ]
    component = max(candidates, key=lambda item: item[4], default=None)
    x_bounds = None
    if component:
        left, top, width, height, _area = component
        x_bounds = (x0 + left - 10, y0 + top - 10, x0 + left + width + 10, y0 + top + height + 10)
    semantic_match = popup_identity == ALLIANCE_FORT_WAVE_ALERT
    geometry_valid = bool(
        x_bounds
        and x_bounds[0] >= 0
        and x_bounds[1] >= 0
        and x_bounds[2] <= 800
        and x_bounds[3] <= 1280
        and x_bounds[0] < x_bounds[2]
        and x_bounds[1] < x_bounds[3]
    )
    recognized = bool(
        semantic_match
        and geometry_valid
        and alliance_fort_dismissal_allowed(ALLIANCE_FORT_WAVE_ALERT, "x")
    )
    return {
        "recognized": recognized,
        "popup_identity": popup_identity if semantic_match else None,
        "body_text": body_text,
        "body_identity": semantic_match,
        "target": x_bounds if recognized else None,
        "target_center": (
            ((x_bounds[0] + x_bounds[2]) // 2, (x_bounds[1] + x_bounds[3]) // 2)
            if recognized else None
        ),
        "target_identity": ALLIANCE_FORT_X_TARGET if recognized else None,
        "control_class": "POPUP_DISMISS_X" if recognized else None,
        "overlay_state": "alliance_fort_wave_alert" if recognized else "unknown",
        "consequence": "navigate_zero_cost" if recognized else None,
        "cost_type": "none" if recognized else None,
        "cost_amount": 0 if recognized else None,
        "quantity": 1 if recognized else None,
        "expected_postcondition": ALLIANCE_FORT_SUCCESSOR if recognized else None,
        "popup_bounds": ALLIANCE_FORT_POPUP_REGION,
        "x_region": ALLIANCE_FORT_X_REGION,
        "x_geometry_valid": geometry_valid,
    }


def recognize_home_semantic(frame: Any) -> Dict[str, Any]:
    """Fallback Home identity for animated base frames rejected by template similarity."""
    if getattr(frame, "shape", ()) != (1280, 800, 3):
        return {"state": "UNKNOWN", "recognized": False}
    nav = " ".join(
        pytesseract.image_to_string(
            cv2.resize(frame[1120:1280, 0:800], None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC),
            config="--psm 6",
        ).lower().split()
    )
    content = " ".join(
        pytesseract.image_to_string(
            cv2.resize(frame[0:1120, 0:800], None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC),
            config="--psm 6",
        ).lower().split()
    )
    nav_compact = re.sub(r"[^a-z]", "", nav)
    content_compact = re.sub(r"[^a-z]", "", content)
    nav_labels = ("world", "hero", "quest", "bag", "mail", "allian", "more")
    building_labels = ("researchlab", "warehouse", "arena")
    recognized = bool(
        sum(label in nav_compact for label in nav_labels) >= 6
        and any(label in content_compact for label in building_labels)
    )
    return {
        "state": "HOME_BASE" if recognized else "UNKNOWN",
        "recognized": recognized,
        "nav_text": nav,
        "content_text": content,
        "quest_entry_target": (250, 1130, 410, 1280),
        "method": "semantic_home_nav_and_buildings",
    }


class ADBTransport:
    """One-call ADB actuator with an injected command runner for tests."""

    def __init__(self, adb: str, serial: str, runner=subprocess.run) -> None:
        self.adb = adb
        self.serial = serial
        self.runner = runner

    def _run(self, args: Sequence[str], *, stdout=None) -> subprocess.CompletedProcess:
        return self.runner(
            [self.adb, "-s", self.serial, *args],
            check=False,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def capture(self, path: Path) -> Dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        command_started_monotonic = time.monotonic()
        with path.open("wb") as handle:
            result = self._run(["exec-out", "screencap", "-p"], stdout=handle)
        if result.returncode != 0:
            raise RuntimeError("ADB capture failed without retry: " + result.stderr.decode("utf-8", "replace"))
        capture_completed_monotonic = time.monotonic()
        metadata = valid_png_frame(path)
        metadata.update(
            {
                "command_started_monotonic": command_started_monotonic,
                "capture_completed_monotonic": capture_completed_monotonic,
                "decode_completed_monotonic": time.monotonic(),
            }
        )
        return metadata

    def tap(self, x: int, y: int) -> TransportResult:
        result = self._run(["shell", "input", "tap", str(x), str(y)])
        if result.returncode != 0:
            raise RuntimeError("ambiguous ADB tap result: " + result.stderr.decode("utf-8", "replace"))
        return TransportResult(True, "ADB_DISPATCHED", "input tap %d %d" % (x, y))

    def swipe(self, x0: int, y0: int, x1: int, y1: int, duration_ms: int) -> TransportResult:
        result = self._run(
            ["shell", "input", "swipe", str(x0), str(y0), str(x1), str(y1), str(duration_ms)]
        )
        if result.returncode != 0:
            raise RuntimeError("ambiguous ADB swipe result: " + result.stderr.decode("utf-8", "replace"))
        return TransportResult(
            True, "ADB_DISPATCHED", "input swipe %d %d %d %d %d" % (x0, y0, x1, y1, duration_ms)
        )


def classify(mode: str, frame: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if mode == "cash":
        decision = classify_cash_mall(
            load_frame(frame),
            load_frame(args.cash_reference),
            load_frame(args.cash_overlay_reference) if args.cash_overlay_reference else None,
        )
        return {"state": decision.state, "recognized": decision.recognized, "detail": decision.__dict__}
    if mode == "home":
        if getattr(args, "home_reference", None):
            local = recognize_home_quest(load_frame(frame), load_frame(args.home_reference))
            if local.recognized:
                return {"state": local.state, "recognized": True, "detail": local.as_dict()}
            fallback = recognize_home_semantic(load_frame(frame))
            if fallback["recognized"]:
                return fallback
            return {"state": local.state, "recognized": False, "detail": local.as_dict()}
        return recognize_home(frame, args.cash_reference, args.policy_file)
    if mode == "quest":
        if getattr(args, "quest_reference", None):
            candidate = valid_png_frame(frame)
            reference = valid_png_frame(args.quest_reference)
            if candidate["sha256"] == reference["sha256"]:
                return {
                    "state": "QUEST",
                    "recognized": True,
                    "detail": {
                        "method": "exact_promoted_quest_reference_hash",
                        "frame_sha256": candidate["sha256"],
                        "daily_quest_target_recognized": True,
                    },
                }
            local = recognize_local_state(
                load_frame(frame),
                load_frame(args.quest_reference),
                "QUEST",
                QUEST_TAB_ROI,
                "daily-quest-target",
            )
            if local.recognized:
                return {"state": local.state, "recognized": True, "detail": local.as_dict()}
        return recognize_quest(frame)
    if mode == "daily":
        if getattr(args, "daily_reference", None) and getattr(args, "main_quest_reference", None):
            local = recognize_daily_selected(
                load_frame(frame),
                load_frame(args.daily_reference),
                load_frame(args.main_quest_reference),
            )
            return {"state": local.state, "recognized": local.recognized, "detail": local.as_dict()}
        return {
            "state": "UNKNOWN",
            "recognized": False,
            "detail": {"reason": "selected Daily Quest reference pair is required"},
        }
    if mode == "daily_claim":
        detail = recognize_daily_claim(load_frame(frame), frame, args, claimed=False)
        return {
            "state": "DAILY_QUEST" if detail["recognized"] else "UNKNOWN",
            "recognized": detail["recognized"],
            "detail": detail,
        }
    if mode == "daily_claimed":
        detail = recognize_daily_claim(load_frame(frame), frame, args, claimed=True)
        return {
            "state": "DAILY_QUEST_CLAIMED" if detail["recognized"] else "UNKNOWN",
            "recognized": detail["recognized"],
            "detail": detail,
        }
    if mode == "daily_bioenhancer":
        detail = recognize_daily_bioenhancer_go(load_frame(frame), frame, args)
        return {
            "state": "DAILY_QUEST" if detail["recognized"] else "UNKNOWN",
            "recognized": detail["recognized"],
            "detail": detail,
        }
    if mode == "bioenhancer":
        return recognize_bioenhancer(frame)
    if mode == "bioenhancer_free":
        detail = recognize_bioenhancer_free_research(
            load_frame(frame),
            frame,
            require_free=True,
        )
        return {
            "state": "BIOENHANCER" if detail["recognized"] else "UNKNOWN",
            "recognized": detail["recognized"],
            "detail": detail,
        }
    if mode == "supply_depot":
        return recognize_supply_depot(frame)
    if mode == "alliance_fort":
        detail = recognize_alliance_fort_wave(load_frame(frame))
        return {
            "state": ALLIANCE_FORT_WAVE_ALERT if detail["recognized"] else "UNKNOWN",
            "recognized": detail["recognized"],
            "detail": detail,
        }
    if mode == "promo":
        decision = classify_promotional_back(load_frame(frame), load_frame(args.cash_reference))
        return {"state": decision.state, "recognized": decision.recognized, "detail": decision.as_dict()}
    raise ValueError("unsupported classifier: " + mode)


def recognize_daily_bioenhancer_go(
    frame: Any,
    frame_path: Path,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Bind visible selected-Daily Bioenhancer row and its local Go control."""
    if getattr(frame, "shape", ()) != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}
    selected = classify("daily", frame_path, args)
    data = pytesseract.image_to_data(
        frame,
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    bio_y = None
    for index, raw in enumerate(data.get("text", ())):
        if " ".join(str(raw).lower().split()) == "bioenhancer":
            bio_y = int(data["top"][index])
            break
    orange = cv2.inRange(
        cv2.cvtColor(frame, cv2.COLOR_BGR2HSV),
        (0, 60, 80),
        (25, 255, 240),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(orange)
    candidates = []
    for index in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[index])
        center_y = top + height // 2
        if (
            area > 1000
            and left >= 500
            and width >= 120
            and 35 <= height <= 80
            and bio_y is not None
            and abs(center_y - (bio_y + 45)) <= 85
        ):
            candidates.append((left, top, width, height, area))
    button = max(candidates, key=lambda item: item[4], default=None)
    target = (
        (button[0], button[1], button[0] + button[2], button[1] + button[3])
        if button else None
    )
    recognized = bool(selected.get("recognized") and bio_y is not None and target)
    return {
        "recognized": recognized,
        "selected_daily": selected,
        "bioenhancer_row_y": bio_y,
        "target": target if recognized else None,
        "target_identity": DAILY_BIOENHANCER_GO_TARGET if recognized else None,
        "control_class": "GO" if recognized else None,
        "overlay_state": "none_observed" if recognized else "unknown",
        "consequence": "navigate_zero_cost" if recognized else None,
        "cost_type": "none" if recognized else None,
        "cost_amount": 0 if recognized else None,
        "quantity": 1 if recognized else None,
        "expected_postcondition": "BIOENHANCER" if recognized else None,
    }


def recognize_daily_claim(
    frame: Any,
    frame_path: Path,
    args: argparse.Namespace,
    *,
    claimed: bool,
) -> Dict[str, Any]:
    """Bind the current Bioenhancer Research row's Claim/Claimed control."""
    if getattr(frame, "shape", ()) != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}
    selected = classify("daily", frame_path, args)
    data = pytesseract.image_to_data(
        frame,
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    objective_y = None
    for index, raw in enumerate(data.get("text", ())):
        text = " ".join(str(raw).lower().split())
        if "bioenhancer" in text:
            objective_y = int(data["top"][index])
            break
    if objective_y is None:
        return {
            "recognized": False,
            "selected_daily": selected,
            "reason": "Bioenhancer Research row is not positively recognized",
        }
    row_top = max(300, objective_y - 55)
    row_bottom = min(1120, objective_y + 135)
    row = frame[row_top:row_bottom, 35:780]
    row_text = " ".join(pytesseract.image_to_string(row, config="--psm 6").lower().split())
    compact_row_text = re.sub(r"\s+", "", row_text)
    objective_present = "bioenhancer" in row_text and "research" in row_text
    completed = "1/1" in compact_row_text
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    button_mask = cv2.inRange(hsv, (0, 45, 70), (45, 255, 255))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(button_mask)
    candidates = []
    for index in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[index])
        center_y = top + height // 2
        if (
            area > 1000
            and left >= 500
            and width >= 120
            and 35 <= height <= 95
            and abs(center_y - (objective_y + 45)) <= 90
        ):
            candidates.append((left, top, width, height, area))
    button = max(candidates, key=lambda item: item[4], default=None)
    target = (
        (button[0], button[1], button[0] + button[2], button[1] + button[3])
        if button else None
    )
    button_text = ""
    if target:
        x0, y0, x1, y1 = target
        button_crop = frame[
            max(0, y0 - 10):min(1280, y1 + 10),
            max(0, x0 - 10):min(800, x1 + 10),
        ]
        button_text = " ".join(
            pytesseract.image_to_string(
                cv2.resize(button_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC),
                config="--psm 7",
            ).lower().split()
        )
    claim_label = "claim" in button_text and "claimed" not in button_text
    claimed_label = "claimed" in button_text or "claimed" in row_text
    recognized = bool(
        selected.get("recognized")
        and objective_present
        and (claimed_label if claimed else completed and claim_label)
    )
    return {
        "recognized": recognized,
        "selected_daily": selected,
        "objective_name": "Bioenhancer Research",
        "objective_y": objective_y,
        "row_text": row_text,
        "completed": completed,
        "button_text": button_text,
        "target": target if recognized and not claimed else None,
        "target_identity": DAILY_CLAIM_TARGET if recognized and not claimed else None,
        "control_class": "CLAIM" if recognized and not claimed else "CLAIMED" if recognized else None,
        "overlay_state": "none_observed" if recognized else "unknown",
        "consequence": "claim_zero_cost_reward" if recognized and not claimed else None,
        "cost_type": "none" if recognized else None,
        "cost_amount": 0 if recognized else None,
        "quantity": 1 if recognized else None,
        "expected_postcondition": "DAILY_QUEST_CLAIMED" if recognized else None,
        "claimed": claimed,
    }


def recognize_bioenhancer_free_research(
    frame: Any,
    frame_path: Path,
    *,
    require_free: bool,
) -> Dict[str, Any]:
    """Bind Free Research 1x and reject the distinct Research 10x control."""
    if getattr(frame, "shape", ()) != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}
    source = recognize_bioenhancer(frame_path)
    left_crop = cv2.resize(
        frame[1125:1225, 80:360],
        None,
        fx=5.0,
        fy=5.0,
        interpolation=cv2.INTER_CUBIC,
    )
    right_crop = cv2.resize(
        frame[1125:1225, 440:720],
        None,
        fx=5.0,
        fy=5.0,
        interpolation=cv2.INTER_CUBIC,
    )
    left_text = " ".join(pytesseract.image_to_string(left_crop, config="--psm 6").lower().split())
    right_text = " ".join(pytesseract.image_to_string(right_crop, config="--psm 6").lower().split())
    free_label = "free" in left_text and "research" in left_text and "1x" in left_text
    ten_label = "research" in right_text and "10x" in right_text
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {
        "free": cv2.inRange(hsv, (125, 40, 40), (170, 255, 255)),
        "ten": cv2.inRange(hsv, (0, 60, 80), (35, 255, 240)),
    }
    bounds = {}
    for name, mask in masks.items():
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
        candidates = [
            tuple(int(value) for value in stats[index])
            for index in range(1, count)
            if stats[index, 4] > 5000
            and stats[index, 0] >= (50 if name == "free" else 400)
            and stats[index, 1] >= 1100
            and stats[index, 2] >= 180
            and stats[index, 3] >= 60
        ]
        if candidates:
            left, top, width, height, _area = max(candidates, key=lambda item: item[4])
            bounds[name] = (left, top, left + width, top + height)
    source_recognized = bool(source.get("recognized"))
    free_cost_proof = bool(
        free_label
        and not any(token in left_text for token in ("token", "gem", "premium", "cost"))
    )
    free_available = bool(source_recognized and free_label and "free" in bounds)
    ten_distinct = bool(ten_label and "ten" in bounds)
    recognized = bool(
        source_recognized
        and free_available
        and free_cost_proof
        and ten_distinct
        and bounds["free"][2] <= bounds["ten"][0]
    )
    if require_free:
        state = "BIOENHANCER" if recognized else "UNKNOWN"
    else:
        state = (
            "BIOENHANCER_RESEARCH_SUCCESS"
            if source_recognized and not free_available
            else ("BIOENHANCER" if recognized else "UNKNOWN")
        )
    return {
        "recognized": recognized if require_free else state == "BIOENHANCER_RESEARCH_SUCCESS",
        "source_recognized": source_recognized,
        "source": source,
        "left_text": left_text,
        "right_text": right_text,
        "free_label": free_label,
        "ten_label": ten_label,
        "free_available": free_available,
        "free_cost_proof": free_cost_proof,
        "quantity": 1,
        "cost_type": "none",
        "cost_amount": 0,
        "ten_distinct": ten_distinct,
        "free_bounds": bounds.get("free"),
        "ten_bounds": bounds.get("ten"),
        "target": bounds.get("free") if recognized else None,
        "target_identity": "bioenhancer-free-research" if recognized else None,
        "control_class": "RESEARCH_FREE" if recognized else None,
        "overlay_state": "none_observed" if source_recognized else "unknown",
        "consequence": "bioenhancer_research_free" if recognized else None,
        "expected_postcondition": "BIOENHANCER_RESEARCH_SUCCESS" if recognized else None,
    }


def observation_for(
    mode: str,
    frame: Path,
    capture_completed_monotonic: float,
    args: argparse.Namespace,
    prior: Observation | None = None,
) -> Observation:
    metadata = valid_png_frame(frame)
    bindings = critical_roi_hashes(mode, frame, args)
    reuse = bool(prior and dict(prior.critical_roi_hashes) == dict(bindings))
    if reuse and prior is not None:
        result = {
            "state": prior.source_state,
            "recognized": prior.recognized,
            "detail": {
                "target_roi": prior.target_roi,
                "target_identity": prior.target_identity,
                "control_class": prior.control_class,
                "source_family": prior.source_family,
                "overlay_state": prior.overlay_state,
                "consequence": prior.consequence,
                "cost_type": prior.cost_type,
                "cost_amount": prior.cost_amount,
                "quantity": prior.quantity,
                "expected_postcondition": prior.expected_postcondition,
                "arrow_geometry": prior.arrow_geometry,
                "target_isolated": prior.target_isolated,
                "forbidden_region_intersects_target": prior.forbidden_region_intersects_target,
                "forbidden_regions": prior.forbidden_regions,
                "package_foreground": prior.package_foreground,
                "os_surface": prior.os_surface,
                "hard_stop_detected": prior.hard_stop_detected,
            },
        }
    else:
        result = classify(mode, frame, args)
    detail = result.get("detail", {})
    recognized = bool(result["recognized"])
    is_promo = mode == "promo"
    is_alliance_fort = mode == "alliance_fort"
    is_daily_bio = mode == "daily_bioenhancer"
    is_daily_claim = mode == "daily_claim"
    is_daily_claimed = mode == "daily_claimed"
    is_bio_free = mode == "bioenhancer_free"
    roi = (
        tuple(detail.get("target"))
        if (is_alliance_fort or is_daily_bio or is_daily_claim or is_bio_free) and detail.get("target")
        else (
            tuple(detail.get("target_roi"))
            if is_promo and detail.get("target_roi")
            else (tuple(args.roi) if args.roi else None)
        )
    )
    target_identity = (
        detail.get("target_identity")
        if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_bio_free)
        else (args.target if recognized else None)
    )
    overlay_state = (
        detail.get("overlay_state", "unknown")
        if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free)
        else ("none_observed" if recognized else "unknown")
    )
    ocr_frame = None if is_promo else (prior.frame_sha256 if reuse and prior else metadata["sha256"])
    ocr_time = None if is_promo else (prior.capture_completed_monotonic if reuse and prior else capture_completed_monotonic)
    return Observation(
        frame_sha256=metadata["sha256"],
        capture_completed_monotonic=capture_completed_monotonic,
        runtime_profile_id=PROFILE_ID,
        width=metadata["width"],
        height=metadata["height"],
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=result["state"],
        overlay_state=overlay_state,
        target_identity=target_identity if recognized else None,
        target_roi=roi if recognized else None,
        recognized=recognized,
        clipped=args.clipped,
        ambiguous=args.ambiguous,
        control_class=detail.get("control_class") if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free) else args.control_class,
        consequence=detail.get("consequence") if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free) else args.consequence,
        cost_type=detail.get("cost_type", "none") if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free) else "none",
        cost_amount=detail.get("cost_amount", 0) if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free) else 0,
        quantity=detail.get("quantity", 1) if (is_promo or is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free) else args.quantity,
        expected_postcondition=(
            "RECOGNIZED_NAVIGATION_STATE" if is_promo
            else detail.get("expected_postcondition") if (is_alliance_fort or is_daily_bio or is_daily_claim or is_daily_claimed or is_bio_free)
            else args.expected_state
        ),
        evidence_refs=(str(frame),),
        critical_roi_hashes=bindings,
        ocr_result_frame_sha256=ocr_frame,
        ocr_result_capture_completed_monotonic=ocr_time,
        ocr_reused=(reuse and not is_promo),
        source_family=detail.get("source_family") if is_promo else None,
        target_isolated=bool(detail.get("target_isolated", False)) if is_promo else False,
        forbidden_region_intersects_target=bool(detail.get("forbidden_region_intersects_target", False)) if is_promo else False,
        arrow_geometry=detail.get("arrow_geometry") if is_promo else None,
        forbidden_regions=tuple(tuple(item) for item in detail.get("forbidden_regions", ())) if is_promo else (),
        package_foreground=bool(detail.get("package_foreground", True)) if is_promo else True,
        os_surface=bool(detail.get("os_surface", False)) if is_promo else False,
        hard_stop_detected=bool(detail.get("hard_stop_detected", False)) if is_promo else False,
    )


def critical_rois(mode: str, args: argparse.Namespace) -> Dict[str, tuple[int, int, int, int]]:
    target = tuple(args.roi) if getattr(args, "roi", None) else None
    if mode == "cash":
        rois = {
            "source_title": (220, 0, 580, 70),
            "source_back": (35, 0, 180, 65),
            "overlay_guard": (0, 70, 800, 1000),
        }
    elif mode == "home":
        rois = {
            "source_nav_left_anchor": (0, 1130, 250, 1280),
            "target_quest": (250, 1130, 410, 1280),
            "source_nav_right_anchor": (410, 1130, 800, 1280),
        }
    elif mode == "quest":
        rois = {
            "source_title": (0, 0, 800, 180),
            "target_daily_tab": QUEST_TAB_ROI,
        }
    elif mode == "promo":
        rois = {
            "arrow_target": PROMOTIONAL_BACK_TARGET_ROI,
            **{name: roi for name, roi in PROMOTIONAL_FORBIDDEN_REGIONS},
        }
    elif mode == "bioenhancer":
        rois = {
            "source_title": (0, 0, 800, 180),
            "source_content": (0, 150, 800, 1120),
        }
    elif mode == "supply_depot":
        rois = {
            "source_title": (0, 0, 800, 180),
            "source_content": (0, 150, 800, 1120),
        }
    elif mode == "alliance_fort":
        rois = {
            "popup_body": ALLIANCE_FORT_POPUP_REGION,
            "dismiss_x": ALLIANCE_FORT_X_REGION,
        }
    elif mode in {"daily_claim", "daily_claimed"}:
        rois = {
            "daily_rows": (35, 300, 780, 1120),
            "daily_claim_target_band": (500, 300, 780, 1120),
        }
    elif mode == "daily_bioenhancer":
        rois = {
            "daily_rows": (0, 300, 800, 1120),
            "daily_bioenhancer_target_band": (500, 850, 780, 1120),
        }
    elif mode == "bioenhancer_free":
        rois = {
            "source_title": (0, 0, 800, 180),
            "free_control": (50, 1100, 380, 1240),
            "ten_control": (420, 1100, 760, 1240),
        }
    else:
        rois = {"source_header": (0, 0, 800, 450), "source_rows": (0, 400, 800, 1120)}
    if target is not None:
        rois["semantic_target"] = target
    return rois


def critical_roi_hashes(
    mode: str, frame_path: Path, args: argparse.Namespace
) -> tuple[tuple[str, str], ...]:
    image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if image is None or image.shape != (1280, 800, 3):
        raise ValueError("critical ROI frame is not the locked profile")
    values = []
    for name, (x0, y0, x1, y1) in critical_rois(mode, args).items():
        values.append((name, hashlib.sha256(image[y0:y1, x0:x1].tobytes()).hexdigest()))
    return tuple(sorted(values))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def observe(args: argparse.Namespace) -> int:
    transport = ADBTransport(args.adb, args.serial)
    metadata = transport.capture(args.output)
    result = classify(args.mode, args.output, args)
    write_json(args.result, {"metadata": metadata, "classification": result})
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result["recognized"] else 2


def annotate(args: argparse.Namespace) -> int:
    valid_png_frame(args.frame)
    image = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
    if args.mode == "promo":
        decision = classify_promotional_back(image, load_frame(args.cash_reference))
        from promotional_escape import annotate_promotional_back
        image = annotate_promotional_back(image, decision)
        detail = decision.as_dict()
    else:
        if args.roi is None:
            raise ValueError("--roi is required for non-promotional annotations")
        x0, y0, x1, y1 = args.roi
        cv2.rectangle(image, (x0, y0), (x1, y1), (0, 255, 0), 3)
        detail = {"roi": args.roi}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), image):
        raise RuntimeError("failed to write annotation")
    print(json.dumps({"frame": str(args.frame), "output": str(args.output), "detail": detail}, default=str))
    return 0


def execute(args: argparse.Namespace) -> int:
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    transport = ADBTransport(args.adb, args.serial)
    store = SafetyStore(args.database)
    now = time.time()
    if store.list_nonterminal_actions() or store.list_unresolved_actions():
        raise RuntimeError("existing nonterminal or unresolved action blocks execution")
    if not store.lease_valid_for(args.owner, now):
        store.acquire_lease(args.owner, now, args.lease_ttl)

    initial_path = evidence / (args.action_id + "-source.png")
    initial_metadata = transport.capture(initial_path)
    initial = observation_for(
        args.source_mode,
        initial_path,
        initial_metadata["capture_completed_monotonic"],
        args,
    )

    capture_counter = {"value": 0}

    def recapture() -> Observation:
        capture_counter["value"] += 1
        path = evidence / (args.action_id + "-immediate-before-%d.png" % capture_counter["value"])
        metadata = transport.capture(path)
        return observation_for(
            args.source_mode,
            path,
            metadata["capture_completed_monotonic"],
            args,
            prior=initial,
        )

    post_paths: List[Path] = []

    def classify_promotional_successor(path: Path) -> Dict[str, Any]:
        """Classify a bounded known successor without assuming the prior page's state or ROI."""
        for mode in ("cash", "home", "quest", "daily", "promo"):
            try:
                candidate = classify(mode, path, args)
            except (ValueError, RuntimeError):
                continue
            if candidate.get("recognized") and candidate.get("state") in KNOWN_PROMOTIONAL_SUCCESSORS:
                return candidate
        return {"state": "UNKNOWN", "recognized": False, "detail": {}}

    def classify_alliance_fort_successor(path: Path) -> Dict[str, Any]:
        """Require popup disappearance plus a recognized non-strategic game screen."""
        popup = classify("alliance_fort", path, args)
        if popup.get("recognized"):
            return {"state": ALLIANCE_FORT_WAVE_ALERT, "recognized": False, "detail": popup.get("detail", {})}
        for mode in ("home", "quest", "daily", "bioenhancer", "supply_depot"):
            try:
                candidate = classify(mode, path, args)
            except (ValueError, RuntimeError):
                continue
            if candidate.get("recognized"):
                return {
                    "state": ALLIANCE_FORT_SUCCESSOR,
                    "recognized": True,
                    "detail": {
                        "underlying_mode": mode,
                        "underlying_state": candidate.get("state"),
                    },
                }
        return {"state": "UNKNOWN", "recognized": False, "detail": {}}

    def classify_bioenhancer_successor(path: Path) -> Dict[str, Any]:
        detail = recognize_bioenhancer_free_research(
            load_frame(path),
            path,
            require_free=False,
        )
        if detail.get("source_recognized") and not detail.get("free_available"):
            return {
                "state": "BIOENHANCER_RESEARCH_SUCCESS",
                "recognized": True,
                "detail": detail,
            }
        return {
            "state": "BIOENHANCER",
            "recognized": False,
            "detail": detail,
        }

    def post_observe() -> Iterable[Observation]:
        observations = []
        for index, delay in enumerate((1.0, 3.0, 6.0), start=1):
            time.sleep(delay)
            path = evidence / (args.action_id + "-post-%d.png" % index)
            capture_metadata = transport.capture(path)
            post_paths.append(path)
            result = (
                classify_promotional_successor(path)
                if args.source_mode == "promo"
                else classify_alliance_fort_successor(path)
                if args.source_mode == "alliance_fort"
                else classify_bioenhancer_successor(path)
                if args.source_mode == "bioenhancer_free"
                else classify(args.expected_mode, path, args)
            )
            metadata = valid_png_frame(path)
            observations.append(
                Observation(
                    frame_sha256=metadata["sha256"],
                    capture_completed_monotonic=capture_metadata["capture_completed_monotonic"],
                    runtime_profile_id=PROFILE_ID, width=800, height=1280,
                    valid_png=True, corrupt=False, black=False,
                    source_state=result["state"], overlay_state="none_observed" if result["recognized"] else "unknown",
                    target_identity=None, target_roi=None, recognized=bool(result["recognized"]),
                    expected_postcondition=(
                        "RECOGNIZED_NAVIGATION_STATE"
                        if args.source_mode == "promo"
                        else args.expected_state
                    ), evidence_refs=(str(path),),
                )
            )
            if result["recognized"]:
                break
        return observations

    def dispatch(_intent) -> TransportResult:
        if args.input_kind == "tap":
            x0, y0, x1, y1 = _intent.target_roi
            return transport.tap((x0 + x1) // 2, (y0 + y1) // 2)
        return transport.swipe(*args.swipe)

    executor = SafeActionExecutor(
        store, CentralPolicy(), args.owner, time.monotonic, dispatch, recapture, post_observe,
        lambda _intent, item: (
            item.recognized and item.source_state in KNOWN_PROMOTIONAL_SUCCESSORS
            if args.source_mode == "promo"
            else item.recognized and item.source_state == args.expected_state
            if args.source_mode == "alliance_fort"
            else item.recognized and item.source_state == args.expected_state
        ),
        wall_clock=time.time,
        max_pre_dispatch_attempts=args.max_pre_dispatch_attempts,
    )
    request = PolicyRequest(
        action_id=args.action_id, action_key=args.action_key, task_id=TASK_ID,
        task_mode="supervised_validation", semantic_action=args.semantic_action,
        expected_runtime_profile_id=PROFILE_ID, observation=initial, monotonic_now=time.monotonic(),
        observation_max_age_seconds=args.observation_max_age,
        dispatch_max_age_seconds=args.dispatch_max_age,
        lease_owner=args.owner, lease_valid=True,
        unresolved_action=False, duplicate_action_key=False, game_day_id=args.game_day,
        promotional_back_count=args.promotional_back_count,
        action_class=(ActionClass.NAVIGATION_ONLY if args.consequence == "navigate_zero_cost" else ActionClass.ZERO_COST_CONSEQUENTIAL),
    )
    result = executor.execute(request)
    audit = store.audit_events(args.action_id)
    try:
        action_record = store.get_action(args.action_id)
    except Exception:
        # Policy can deny before preparation.  Preserve a safe cancellation without
        # fabricating a journal record or implying that transport was attempted.
        action_record = None
    write_json(
        evidence / (args.action_id + "-result.json"),
        {"result": result.__dict__, "action": action_record, "audit": audit},
    )
    print(json.dumps(result.__dict__, sort_keys=True, default=str))
    store.close()
    return 0 if result.status.value == "confirmed" else 3


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--adb", default="/opt/adb")
    root.add_argument("--serial", default="192.168.122.79:5555")
    root.add_argument("--cash-reference", type=Path, required=True)
    root.add_argument("--cash-overlay-reference", type=Path)
    root.add_argument("--quest-reference", type=Path)
    root.add_argument("--daily-reference", type=Path)
    root.add_argument("--main-quest-reference", type=Path)
    root.add_argument("--home-reference", type=Path)
    root.add_argument("--policy-file", type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    obs = sub.add_parser("observe")
    obs.add_argument("--mode", choices=("cash", "home", "quest", "daily", "daily_claim", "daily_claimed", "daily_bioenhancer", "bioenhancer", "bioenhancer_free", "supply_depot", "alliance_fort", "promo"), required=True)
    obs.add_argument("--output", type=Path, required=True)
    obs.add_argument("--result", type=Path, required=True)
    obs.set_defaults(handler=observe)
    ann = sub.add_parser("annotate")
    ann.add_argument("--frame", type=Path, required=True)
    ann.add_argument("--output", type=Path, required=True)
    ann.add_argument("--mode", choices=("generic", "promo"), default="generic")
    ann.add_argument("--roi", type=int, nargs=4)
    ann.set_defaults(handler=annotate)
    act = sub.add_parser("execute")
    act.add_argument("--database", type=Path, required=True)
    act.add_argument("--evidence", type=Path, required=True)
    act.add_argument("--owner", required=True)
    act.add_argument("--lease-ttl", type=float, default=600.0)
    act.add_argument("--action-id", required=True)
    act.add_argument("--action-key", required=True)
    act.add_argument("--game-day")
    act.add_argument("--source-mode", choices=("cash", "home", "quest", "daily", "daily_claim", "daily_claimed", "daily_bioenhancer", "bioenhancer", "bioenhancer_free", "supply_depot", "alliance_fort", "promo"), required=True)
    act.add_argument("--expected-mode", choices=("cash", "home", "quest", "daily", "daily_claim", "daily_claimed", "daily_bioenhancer", "bioenhancer", "bioenhancer_free", "supply_depot", "alliance_fort", "promo"), required=True)
    act.add_argument("--expected-state", required=True)
    act.add_argument("--target", required=True)
    act.add_argument("--roi", type=int, nargs=4, required=True)
    act.add_argument("--semantic-action", required=True)
    act.add_argument("--consequence", default="navigate_zero_cost")
    act.add_argument("--quantity", type=int, default=1)
    act.add_argument("--control-class")
    act.add_argument("--clipped", action="store_true")
    act.add_argument("--ambiguous", action="store_true")
    act.add_argument("--input-kind", choices=("tap", "swipe"), default="tap")
    act.add_argument("--swipe", type=int, nargs=5)
    act.add_argument("--observation-max-age", type=float, default=3.0)
    act.add_argument("--dispatch-max-age", type=float, default=2.0)
    act.add_argument("--max-pre-dispatch-attempts", type=int, choices=(1, 2, 3), default=2)
    act.add_argument("--promotional-back-count", type=int, choices=(0, 1, 2, 3), default=0)
    act.set_defaults(handler=execute)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
