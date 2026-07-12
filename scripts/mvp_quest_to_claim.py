#!/usr/bin/env python3
"""Task-scoped live adapter for one supervised quest-to-claim trial.

All game input is dispatched only by SafeActionExecutor through the injected ADBTransport.
There are no retries, generic input service, scheduler, or unattended loop.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import cv2

from safe_action_core import (
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
from startup_normalization import classify_cash_mall, load_frame

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
        with path.open("wb") as handle:
            result = self._run(["exec-out", "screencap", "-p"], stdout=handle)
        if result.returncode != 0:
            raise RuntimeError("ADB capture failed without retry: " + result.stderr.decode("utf-8", "replace"))
        return valid_png_frame(path)

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
        return recognize_home(frame, args.cash_reference, args.policy_file)
    if mode == "quest":
        return recognize_quest(frame)
    if mode == "daily":
        return recognize_daily_quest(frame)
    raise ValueError("unsupported classifier: " + mode)


def observation_for(
    mode: str,
    frame: Path,
    captured_at: float,
    args: argparse.Namespace,
) -> Observation:
    metadata = valid_png_frame(frame)
    result = classify(mode, frame, args)
    roi = tuple(args.roi) if args.roi else None
    return Observation(
        frame_sha256=metadata["sha256"],
        captured_at=captured_at,
        runtime_profile_id=PROFILE_ID,
        width=metadata["width"],
        height=metadata["height"],
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=result["state"],
        overlay_state="none_observed" if result["recognized"] else "unknown",
        target_identity=args.target if result["recognized"] else None,
        target_roi=roi if result["recognized"] else None,
        recognized=bool(result["recognized"]),
        clipped=args.clipped,
        ambiguous=args.ambiguous,
        control_class=args.control_class,
        consequence=args.consequence,
        cost_type="none",
        cost_amount=0,
        quantity=args.quantity,
        expected_postcondition=args.expected_state,
        evidence_refs=(str(frame),),
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def observe(args: argparse.Namespace) -> int:
    transport = ADBTransport(args.adb, args.serial)
    captured_at = time.time()
    metadata = transport.capture(args.output)
    result = classify(args.mode, args.output, args)
    write_json(args.result, {"captured_at": captured_at, "metadata": metadata, "classification": result})
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result["recognized"] else 2


def annotate(args: argparse.Namespace) -> int:
    valid_png_frame(args.frame)
    image = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
    x0, y0, x1, y1 = args.roi
    cv2.rectangle(image, (x0, y0), (x1, y1), (0, 255, 0), 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), image):
        raise RuntimeError("failed to write annotation")
    print(json.dumps({"frame": str(args.frame), "output": str(args.output), "roi": args.roi}))
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
    initial_at = time.time()
    transport.capture(initial_path)
    initial = observation_for(args.source_mode, initial_path, initial_at, args)

    capture_counter = {"value": 0}

    def recapture() -> Observation:
        capture_counter["value"] += 1
        path = evidence / (args.action_id + "-immediate-before.png")
        captured_at = time.time()
        transport.capture(path)
        return observation_for(args.source_mode, path, captured_at, args)

    post_paths: List[Path] = []

    def post_observe() -> Iterable[Observation]:
        observations = []
        for index, delay in enumerate((1.0, 3.0, 6.0), start=1):
            time.sleep(delay)
            path = evidence / (args.action_id + "-post-%d.png" % index)
            captured_at = time.time()
            transport.capture(path)
            post_paths.append(path)
            result = classify(args.expected_mode, path, args)
            metadata = valid_png_frame(path)
            observations.append(
                Observation(
                    frame_sha256=metadata["sha256"], captured_at=captured_at,
                    runtime_profile_id=PROFILE_ID, width=800, height=1280,
                    valid_png=True, corrupt=False, black=False,
                    source_state=result["state"], overlay_state="none_observed" if result["recognized"] else "unknown",
                    target_identity=None, target_roi=None, recognized=bool(result["recognized"]),
                    expected_postcondition=args.expected_state, evidence_refs=(str(path),),
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
        store, CentralPolicy(), args.owner, time.time, dispatch, recapture, post_observe,
        lambda _intent, item: item.recognized and item.source_state == args.expected_state,
    )
    request = PolicyRequest(
        action_id=args.action_id, action_key=args.action_key, task_id=TASK_ID,
        task_mode="supervised_validation", semantic_action=args.semantic_action,
        expected_runtime_profile_id=PROFILE_ID, observation=initial, now=time.time(),
        max_frame_age_seconds=args.max_frame_age, lease_owner=args.owner, lease_valid=True,
        unresolved_action=False, duplicate_action_key=False, game_day_id=args.game_day,
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
    root.add_argument("--policy-file", type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    obs = sub.add_parser("observe")
    obs.add_argument("--mode", choices=("cash", "home", "quest", "daily"), required=True)
    obs.add_argument("--output", type=Path, required=True)
    obs.add_argument("--result", type=Path, required=True)
    obs.set_defaults(handler=observe)
    ann = sub.add_parser("annotate")
    ann.add_argument("--frame", type=Path, required=True)
    ann.add_argument("--output", type=Path, required=True)
    ann.add_argument("--roi", type=int, nargs=4, required=True)
    ann.set_defaults(handler=annotate)
    act = sub.add_parser("execute")
    act.add_argument("--database", type=Path, required=True)
    act.add_argument("--evidence", type=Path, required=True)
    act.add_argument("--owner", required=True)
    act.add_argument("--lease-ttl", type=float, default=600.0)
    act.add_argument("--action-id", required=True)
    act.add_argument("--action-key", required=True)
    act.add_argument("--game-day")
    act.add_argument("--source-mode", choices=("cash", "home", "quest", "daily"), required=True)
    act.add_argument("--expected-mode", choices=("cash", "home", "quest", "daily"), required=True)
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
    act.add_argument("--max-frame-age", type=float, default=3.0)
    act.set_defaults(handler=execute)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
