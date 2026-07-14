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
from tasks.profile import HELP_ALL_ACTION, INDIVIDUAL_HELP_ACTION, PROFILE_ID


TASK_ID = "MVP-QUEST-TO-CLAIM"
TARGET_ROI = HELP_ALL_ACTION.roi
INDIVIDUAL_ROI = INDIVIDUAL_HELP_ACTION.roi
HEADER_ROI = (250, 0, 550, 120)
INDIVIDUAL_REGION = (0, 200, 800, 500)
NO_HELP_MESSAGE_ROI = (80, 500, 720, 1150)
INTERIOR_MARGIN = 8
HELP_ALL_REFERENCE = REPO_ROOT / "evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-validation-20260713/remote/alliance-help-1783981635-source.png"
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


def _ocr_text(image: np.ndarray, box: tuple[int, int, int, int], psm: int = 7) -> str:
    crop = _roi(image, box)
    enlarged = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    return " ".join(pytesseract.image_to_string(enlarged, config=f"--psm {psm}").casefold().split())


def _header_text(image: np.ndarray) -> str:
    return _ocr_text(image, HEADER_ROI, 6)


def _template_score(image: np.ndarray, box: tuple[int, int, int, int]) -> float:
    reference = cv2.imread(str(HELP_ALL_REFERENCE), cv2.IMREAD_COLOR)
    if reference is None or reference.shape[:2] != image.shape[:2]:
        return 0.0
    current = cv2.cvtColor(_roi(image, box), cv2.COLOR_BGR2GRAY)
    expected = cv2.cvtColor(_roi(reference, box), cv2.COLOR_BGR2GRAY)
    return float(cv2.matchTemplate(current, expected, cv2.TM_CCOEFF_NORMED)[0, 0])


def help_all_geometry(box: tuple[int, int, int, int]) -> Dict[str, Any]:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    intersects_individual = not (y1 <= 200 or y0 >= 500)
    tap_inside = x0 + INTERIOR_MARGIN <= cx <= x1 - INTERIOR_MARGIN and y0 + INTERIOR_MARGIN <= cy <= y1 - INTERIOR_MARGIN
    valid = bool(y0 > 1100 and cy > 1150 and cy < 1275 and y1 < 1280 and not intersects_individual and tap_inside)
    return {"bounds": box, "center": (cx, cy), "target_top": y0, "center_y": cy,
            "center_y_gt_1150": cy > 1150, "center_y_lt_1275": cy < 1275,
            "intersects_individual_region": intersects_individual, "tap_inside_with_margin": tap_inside,
            "valid": valid}


def recognize_help_surface(path: Path, capture_completed_monotonic: float, evidence_ref: str, header_reference: Optional[Path] = None) -> Dict[str, Any]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (1280, 800):
        raise ValueError("Help frame is not the locked 800x1280 PNG")
    raw = path.read_bytes()
    frame_hash = hashlib.sha256(raw).hexdigest()
    header = _roi(image, HEADER_ROI)
    help_all_crop = _roi(image, TARGET_ROI)
    individual_crop = _roi(image, INDIVIDUAL_ROI)
    header_text = _header_text(image)
    help_all_ocr = _ocr_text(image, TARGET_ROI)
    individual_ocr = _ocr_text(image, INDIVIDUAL_ROI)
    transient_message_text = _ocr_text(image, NO_HELP_MESSAGE_ROI, 6)
    no_help_request_visible = all(word in transient_message_text for word in ("no", "help", "request", "currently"))
    help_all_orange = _orange_ratio(image, TARGET_ROI)
    individual_orange = _orange_ratio(image, INDIVIDUAL_ROI)
    template_score = _template_score(image, TARGET_ROI)
    geometry = help_all_geometry(TARGET_ROI)
    literal_help_all = "help all" in help_all_ocr
    template_help_all = template_score >= HELP_ALL_ACTION.threshold
    help_all_visible = bool(geometry["valid"] and help_all_orange >= 0.35 and (literal_help_all or template_help_all))
    individual_help_visible = bool(individual_orange >= 0.35 and "help" in individual_ocr and "help all" not in individual_ocr)
    header_stable = False
    if header_reference is not None:
        reference_image = cv2.imread(str(header_reference), cv2.IMREAD_COLOR)
        if reference_image is not None and reference_image.shape[:2] == (1280, 800):
            header_stable = float(cv2.absdiff(header, _roi(reference_image, HEADER_ROI)).mean()) <= 2.0
    speedup_title = "speed" in header_text or ("spee" in header_text and "help" in header_text)
    recognized = bool(speedup_title or header_stable or help_all_visible or individual_help_visible)
    individual_count = 1 if individual_help_visible else 0
    return {
        "recognized": recognized, "screen_state": "SPEEDUP_HELP" if recognized else "UNKNOWN",
        "header_stable": header_stable, "header_text": header_text,
        "help_all_visible": help_all_visible, "individual_help_visible": individual_help_visible,
        "individual_help_count": individual_count, "empty_state": not help_all_visible and individual_count == 0,
        "help_all_ocr": help_all_ocr, "individual_help_ocr": individual_ocr,
        "transient_message_text": transient_message_text,
        "no_help_request_visible": no_help_request_visible,
        "matched_text": "Help All" if help_all_visible else None,
        "identity_basis": "literal_ocr" if literal_help_all else ("retained_template" if template_help_all else None),
        "help_all_orange_ratio": help_all_orange, "individual_orange_ratio": individual_orange,
        "help_all_template_score": template_score, "geometry": geometry,
        "frame_sha256": frame_hash, "capture_completed_monotonic": capture_completed_monotonic,
        "critical_roi_hashes": (("speedup_help_header", hashlib.sha256(header.tobytes()).hexdigest()),
                                ("help_all", hashlib.sha256(help_all_crop.tobytes()).hexdigest()),
                                ("individual_help", hashlib.sha256(individual_crop.tobytes()).hexdigest())),
        "evidence_ref": evidence_ref,
    }


def create_predispatch_artifact(source: Path, detail: Dict[str, Any], json_path: Path, annotated_path: Path) -> Dict[str, Any]:
    geometry = detail["geometry"]
    artifact = {
        "target_action": "ALLIANCE_HELP_ALL", "current_screenshot_path": str(source),
        "recognized_screen": detail["screen_state"], "matched_text": detail["matched_text"],
        "identity_basis": detail["identity_basis"], "matched_button_bounds": list(geometry["bounds"]),
        "proposed_center": list(geometry["center"]), "target_top": geometry["target_top"],
        "target_center_y": geometry["center_y"], "center_y_gt_1150": geometry["center_y_gt_1150"],
        "center_y_lt_1275": geometry["center_y_lt_1275"],
        "intersects_individual_help_region": geometry["intersects_individual_region"],
        "tap_inside_with_margin": geometry["tap_inside_with_margin"],
        "geometry_valid": geometry["valid"], "help_all_visible": detail["help_all_visible"],
    }
    if not (detail["screen_state"] == "SPEEDUP_HELP" and detail["matched_text"] == "Help All"
            and detail["help_all_visible"] and geometry["valid"]):
        raise ValueError("pre-dispatch Help All artifact failed the lower-button semantic gate")
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    x0, y0, x1, y1 = geometry["bounds"]; cx, cy = geometry["center"]
    cv2.rectangle(image, (x0, y0), (x1, y1), (0, 255, 0), 3)
    cv2.circle(image, (cx, cy), 8, (0, 0, 255), -1)
    cv2.putText(image, "ALLIANCE_HELP_ALL", (x0, y0 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
    annotated_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(annotated_path), image):
        raise ValueError("failed to persist annotated Help All artifact")
    artifact["annotated_screenshot_path"] = str(annotated_path)
    write_json(json_path, artifact)
    return artifact


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
            write_json(args.result, {"status": "blocked", "reason": "ACTUAL_LOWER_HELP_ALL_NOT_RECOGNIZED", "detail": initial_detail})
            return 2
        artifact_json = args.evidence / (args.action_id + "-pre-dispatch.json")
        artifact_png = args.evidence / (args.action_id + "-pre-dispatch-annotated.png")
        predispatch_artifact = create_predispatch_artifact(source_path, initial_detail, artifact_json, artifact_png)

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
        detail_by_hash: Dict[str, Dict[str, Any]] = {initial.frame_sha256: initial_detail}
        postcondition_signals: set[str] = set()

        def post_observe() -> Iterable[Observation]:
            results = []
            for delay in (0.8, 1.8, 3.0):
                time.sleep(delay)
                post_counter["value"] += 1
                path = args.evidence / (args.action_id + "-post-%d.png" % post_counter["value"])
                capture_metadata = transport.capture(path)
                observed, detail = observation_from(path, capture_metadata, args, header_reference=source_path)
                detail_by_hash[observed.frame_sha256] = detail
                results.append(observed)
            return results

        before_semantic = AllianceHelpHandlerObservation(initial, args.current_progress, args.required_progress, initial_detail)

        def reconcile(_intent, observation: Observation) -> bool:
            if not observation.recognized or observation.source_state != "SPEEDUP_HELP":
                return False
            detail = detail_by_hash.get(observation.frame_sha256, {})
            after = AllianceHelpHandlerObservation(observation, args.current_progress, args.required_progress, detail)
            signals = set()
            if before_semantic.help_all_visible and not after.help_all_visible:
                signals.add("lower_help_all_disappeared")
            if (before_semantic.request_controls_count is not None and after.request_controls_count is not None
                    and after.request_controls_count < before_semantic.request_controls_count):
                signals.add("individual_help_controls_decreased")
            if after.empty_state:
                signals.add("empty_state")
            if after.no_help_request_visible:
                signals.add("explicit_no_help_request_popup")
            postcondition_signals.update(signals)
            return AllianceHelpHandler.postcondition_verified(before_semantic, after) and (
                "explicit_no_help_request_popup" in signals or len(signals) >= 2
            )

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
            "pre_dispatch_artifact": predispatch_artifact,
            "postcondition_signals": sorted(postcondition_signals),
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
    """Adapt frame-bound detector detail to the task handler."""

    def __init__(self, observation: Observation, current_progress: int, required_progress: int, detail: Optional[Dict[str, Any]] = None):
        detail = detail or {}
        super().__init__(
            screen_state=observation.source_state, objective_name="Help allies",
            current_progress=current_progress, required_progress=required_progress,
            target_identity=observation.target_identity or HELP_ALL_ACTION.name,
            target_roi=observation.target_roi or TARGET_ROI, zero_cost_evidence=True,
            available_request_count=detail.get("individual_help_count"),
            help_all_visible=bool(detail.get("help_all_visible", observation.target_identity == HELP_ALL_ACTION.name)),
            individual_help_visible=bool(detail.get("individual_help_visible", False)),
            request_controls_count=detail.get("individual_help_count"),
            empty_state=bool(detail.get("empty_state", False)),
            no_help_request_visible=bool(detail.get("no_help_request_visible", False)),
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
