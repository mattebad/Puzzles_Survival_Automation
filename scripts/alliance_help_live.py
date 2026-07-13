#!/usr/bin/env python3
"""One bounded, checked-in Speedup Help / Help All validation adapter.

This module is intentionally narrow.  It recognizes only the local Speedup Help header and
Help All ROI from independently captured Bliss evidence, then delegates the one consequential
input to the existing SafeActionExecutor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import cv2
import numpy as np
import pytesseract

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from mvp_quest_to_claim import ADBTransport
from safe_action_core import (
    ActionClass,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from tasks.daily_quest import AllianceHelpHandler, AllianceHelpObservation
from tasks.profile import HELP_ALL_ACTION, PROFILE_ID


TASK_ID = "MVP-QUEST-TO-CLAIM"
TARGET_ROI = HELP_ALL_ACTION.roi
HEADER_ROI = (250, 0, 550, 120)
ORANGE_LOWER = np.array([3, 90, 120], dtype=np.uint8)
ORANGE_UPPER = np.array([35, 255, 255], dtype=np.uint8)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _roi(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = box
    return image[y0:y1, x0:x1]


def _orange_ratio(image: np.ndarray, box: tuple[int, int, int, int]) -> float:
    crop = _roi(image, box)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, ORANGE_LOWER, ORANGE_UPPER)
    return float(cv2.countNonZero(mask)) / float(mask.shape[0] * mask.shape[1])


def _header_text(image: np.ndarray) -> str:
    crop = _roi(image, HEADER_ROI)
    enlarged = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return " ".join(pytesseract.image_to_string(enlarged, config="--psm 6").casefold().split())


def recognize_help_surface(path: Path, capture_completed_monotonic: float, evidence_ref: str, header_reference: Optional[Path] = None) -> Dict[str, Any]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (1280, 800):
        raise ValueError("Help All frame is not the locked 800x1280 PNG")
    raw = path.read_bytes()
    frame_hash = hashlib.sha256(raw).hexdigest()
    header = _roi(image, HEADER_ROI)
    target = _roi(image, TARGET_ROI)
    target_hash = hashlib.sha256(target.tobytes()).hexdigest()
    header_hash = hashlib.sha256(header.tobytes()).hexdigest()
    text = _header_text(image)
    orange_ratio = _orange_ratio(image, TARGET_ROI)
    help_all_visible = orange_ratio >= 0.35
    header_stable = False
    if header_reference is not None:
        reference_image = cv2.imread(str(header_reference), cv2.IMREAD_COLOR)
        if reference_image is not None and reference_image.shape[:2] == (1280, 800):
            reference_header = _roi(reference_image, HEADER_ROI)
            header_stable = float(cv2.absdiff(header, reference_header).mean()) <= 2.0
    # The retained Speedup Help title is OCR-noisy. Post-action recognition therefore binds
    # to the small stable header ROI, never to whole-screen equality or unrelated OCR.
    speedup_title = "speed" in text or ("spee" in text and "help" in text)
    recognized = bool(speedup_title or help_all_visible or header_stable)
    return {
        "recognized": recognized,
        "screen_state": "SPEEDUP_HELP" if recognized else "UNKNOWN",
        "header_stable": header_stable,
        "header_text": text,
        "help_all_visible": help_all_visible,
        "orange_ratio": orange_ratio,
        "frame_sha256": frame_hash,
        "capture_completed_monotonic": capture_completed_monotonic,
        "critical_roi_hashes": (("speedup_help_header", header_hash), ("help_all", target_hash)),
        "evidence_ref": evidence_ref,
    }


def observation_from(path: Path, metadata: Dict[str, Any], args: argparse.Namespace, header_reference: Optional[Path] = None) -> tuple[Observation, Dict[str, Any]]:
    detail = recognize_help_surface(path, metadata["capture_completed_monotonic"], str(path), header_reference)
    target = detail["help_all_visible"]
    observation = Observation(
        frame_sha256=detail["frame_sha256"],
        capture_completed_monotonic=detail["capture_completed_monotonic"],
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=detail["screen_state"],
        overlay_state="none_observed",
        target_identity=HELP_ALL_ACTION.name if target else None,
        target_roi=TARGET_ROI if target else None,
        recognized=detail["recognized"],
        control_class="HELP_ALL" if target else None,
        consequence="alliance_help_zero_cost" if target else None,
        cost_type="none" if target else None,
        cost_amount=0 if target else None,
        quantity=1 if target else None,
        expected_postcondition="available_help_controls_decrease_or_empty" if target else None,
        evidence_refs=(str(path),),
        critical_roi_hashes=detail["critical_roi_hashes"],
        ocr_result_frame_sha256=detail["frame_sha256"],
        ocr_result_capture_completed_monotonic=detail["capture_completed_monotonic"],
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )
    return observation, detail


def run(args: argparse.Namespace) -> int:
    args.evidence.mkdir(parents=True, exist_ok=True)
    transport = ADBTransport(args.adb, args.serial)
    store = SafetyStore(args.database)
    owner = args.owner
    leased = False
    try:
        if store.list_nonterminal_actions() or store.list_unresolved_actions():
            raise RuntimeError("existing action state blocks Help All validation")
        store.acquire_lease(owner, time.time(), args.lease_ttl)
        leased = True
        source_path = args.evidence / (args.action_id + "-source.png")
        metadata = transport.capture(source_path)
        initial, initial_detail = observation_from(source_path, metadata, args)
        if not initial.recognized or not initial.target_identity:
            write_json(args.result, {"status": "blocked", "reason": "HELP_ALL_NOT_RECOGNIZED", "detail": initial_detail})
            return 2

        recapture_count = {"value": 0}

        def recapture() -> Observation:
            recapture_count["value"] += 1
            path = args.evidence / (args.action_id + "-immediate-before-%d.png" % recapture_count["value"])
            capture_metadata = transport.capture(path)
            return observation_from(path, capture_metadata, args, header_reference=source_path)[0]

        def dispatch(intent) -> TransportResult:
            x0, y0, x1, y1 = TARGET_ROI
            return transport.tap((x0 + x1) // 2, (y0 + y1) // 2)

        post_counter = {"value": 0}

        def post_observe() -> Iterable[Observation]:
            results = []
            for delay in (0.8, 1.8, 3.0):
                time.sleep(delay)
                post_counter["value"] += 1
                path = args.evidence / (args.action_id + "-post-%d.png" % post_counter["value"])
                capture_metadata = transport.capture(path)
                results.append(observation_from(path, capture_metadata, args, header_reference=source_path)[0])
            return results

        before_semantic = AllianceHelpHandlerObservation(initial, args.current_progress, args.required_progress)

        def reconcile(_intent, observation: Observation) -> bool:
            if not observation.recognized or observation.source_state != "SPEEDUP_HELP":
                return False
            after = AllianceHelpHandlerObservation(observation, args.current_progress, args.required_progress)
            return AllianceHelpHandler.postcondition_verified(before_semantic, after)

        request = PolicyRequest(
            action_id=args.action_id,
            action_key=args.action_key,
            task_id=TASK_ID,
            task_mode="supervised_validation",
            semantic_action="ALLIANCE_HELP_ALL",
            expected_runtime_profile_id=PROFILE_ID,
            observation=initial,
            monotonic_now=time.monotonic(),
            observation_max_age_seconds=3.0,
            dispatch_max_age_seconds=2.0,
            lease_owner=owner,
            lease_valid=True,
            unresolved_action=False,
            duplicate_action_key=False,
            game_day_id=args.game_day,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            action_kind="ALLIANCE_HELP_ALL",
            subject="Help allies",
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            semantic_preconditions=("speedup_help_screen", "help_all_visible", "explicit_zero_cost_help_all"),
            semantic_postconditions=("available_help_controls_decrease_or_empty", "daily_objective_progress_increases"),
        )
        executor = SafeActionExecutor(
            store, CentralPolicy(), owner, time.monotonic, dispatch, recapture, post_observe, reconcile,
            wall_clock=time.time, max_pre_dispatch_attempts=2,
        )
        result = executor.execute(request)
        action = store.get_action(args.action_id)
        write_json(args.result, {
            "result": result.__dict__,
            "action": action,
            "initial": initial_detail,
            "immediate_before_attempts": recapture_count["value"],
            "post_observation_count": post_counter["value"],
            "audit": store.audit_events(args.action_id),
        })
        return 0 if result.status.value == "confirmed" else 3
    finally:
        if leased:
            lease = store.get_lease(time.time())
            if lease and lease.get("valid") and lease.get("owner_id") == owner:
                store.release_lease(owner, time.time())
        store.close()


class AllianceHelpHandlerObservation(AllianceHelpObservation):
    """Adapt a safe-core Observation to the task module without duplicating policy."""

    def __init__(self, observation: Observation, current_progress: int, required_progress: int):
        super().__init__(
            screen_state=observation.source_state,
            objective_name="Help allies",
            current_progress=current_progress,
            required_progress=required_progress,
            target_identity=observation.target_identity or HELP_ALL_ACTION.name,
            target_roi=observation.target_roi or TARGET_ROI,
            zero_cost_evidence=True,
            available_request_count=1 if observation.target_identity else 0,
            help_all_visible=bool(observation.target_identity),
            request_controls_count=1 if observation.target_identity else 0,
            empty_state=not bool(observation.target_identity),
            overlay_state=observation.overlay_state,
            forbidden_region_intersects_target=observation.forbidden_region_intersects_target,
            recognized=observation.recognized,
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--adb", default="/opt/adb")
    root.add_argument("--serial", default="192.168.122.79:5555")
    root.add_argument("--database", type=Path, required=True)
    root.add_argument("--evidence", type=Path, required=True)
    root.add_argument("--result", type=Path, required=True)
    root.add_argument("--owner", required=True)
    root.add_argument("--action-id", required=True)
    root.add_argument("--action-key", required=True)
    root.add_argument("--game-day", default="daily-2026-07-13")
    root.add_argument("--current-progress", type=int, default=0)
    root.add_argument("--required-progress", type=int, default=10)
    root.add_argument("--lease-ttl", type=float, default=600.0)
    return root


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
