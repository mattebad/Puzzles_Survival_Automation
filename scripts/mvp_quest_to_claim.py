#!/usr/bin/env python3
"""Task-scoped live adapter for one supervised quest-to-claim trial.

All game input is dispatched only by SafeActionExecutor through the injected ADBTransport.
There are no retries, generic input service, scheduler, or unattended loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import cv2

from safe_action_core import (
    ActionClass,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from daily_quest_bootstrap import recognize_daily_quest, recognize_home, recognize_quest, valid_png_frame
from navigation_recognition import recognize_home_quest
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
            return {"state": local.state, "recognized": local.recognized, "detail": local.as_dict()}
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
        return recognize_quest(frame)
    if mode == "daily":
        return recognize_daily_quest(frame)
    if mode == "promo":
        decision = classify_promotional_back(load_frame(frame), load_frame(args.cash_reference))
        return {"state": decision.state, "recognized": decision.recognized, "detail": decision.as_dict()}
    raise ValueError("unsupported classifier: " + mode)


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
    roi = tuple(detail.get("target_roi")) if is_promo and detail.get("target_roi") else (tuple(args.roi) if args.roi else None)
    target_identity = detail.get("target_identity") if is_promo else (args.target if recognized else None)
    overlay_state = detail.get("overlay_state", "unknown") if is_promo else ("none_observed" if recognized else "unknown")
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
        control_class=detail.get("control_class") if is_promo else args.control_class,
        consequence=detail.get("consequence") if is_promo else args.consequence,
        cost_type=detail.get("cost_type", "none") if is_promo else "none",
        cost_amount=detail.get("cost_amount", 0) if is_promo else 0,
        quantity=detail.get("quantity", 1) if is_promo else args.quantity,
        expected_postcondition=(
            "RECOGNIZED_NAVIGATION_STATE" if is_promo
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
            "target_daily_tab": (260, 80, 540, 300),
        }
    elif mode == "promo":
        rois = {
            "arrow_target": PROMOTIONAL_BACK_TARGET_ROI,
            **{name: roi for name, roi in PROMOTIONAL_FORBIDDEN_REGIONS},
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
                        "RECOGNIZED_NAVIGATION_STATE" if args.source_mode == "promo" else args.expected_state
                    ), evidence_refs=(str(path),),
                )
            )
            if result["recognized"]:
                break
        return observations

    def dispatch(_intent) -> TransportResult:
        if args.input_kind == "tap":
            x0, y0, x1, y1 = args.roi
            return transport.tap((x0 + x1) // 2, (y0 + y1) // 2)
        return transport.swipe(*args.swipe)

    executor = SafeActionExecutor(
        store, CentralPolicy(), args.owner, time.monotonic, dispatch, recapture, post_observe,
        lambda _intent, item: (
            item.recognized and item.source_state in KNOWN_PROMOTIONAL_SUCCESSORS
            if args.source_mode == "promo"
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
    write_json(
        evidence / (args.action_id + "-result.json"),
        {"result": result.__dict__, "action": store.get_action(args.action_id), "audit": store.audit_events(args.action_id)},
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
    root.add_argument("--home-reference", type=Path)
    root.add_argument("--policy-file", type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    obs = sub.add_parser("observe")
    obs.add_argument("--mode", choices=("cash", "home", "quest", "daily", "promo"), required=True)
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
    act.add_argument("--source-mode", choices=("cash", "home", "quest", "daily", "promo"), required=True)
    act.add_argument("--expected-mode", choices=("cash", "home", "quest", "daily", "promo"), required=True)
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
