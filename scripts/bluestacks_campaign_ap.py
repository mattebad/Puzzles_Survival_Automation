#!/usr/bin/env python3
"""Run one bounded Campaign AP route against an explicitly selected local BlueStacks serial.

Dry-run is the default.  ``--execute`` is required for input, and every fresh frame plus command
is retained under ``.local-captures``.  This adapter never connects ADB and rejects non-local
BlueStacks serials.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bluestacks_flow_collector import ADBRunner, is_permitted_local_bluestacks_serial
from tasks.campaign_auto_battle import (
    CampaignAutoBattleConfig,
    CampaignScreen,
    parse_supported_campaign_story_destination,
)
from tasks.campaign_auto_battle_runtime import CampaignRuntimeController
from tasks.campaign_auto_battle_vision import recognize_campaign_frame


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def append_event(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def capture(runner: ADBRunner, path: Path) -> np.ndarray:
    payload = runner.capture_png()
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1280, 800):
        raise RuntimeError("BlueStacks screenshot is not a native 800x1280 PNG")
    path.write_bytes(payload)
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="BlueStacks HD-Adb.exe path")
    parser.add_argument("--serial", required=True, help="exact local BlueStacks serial")
    parser.add_argument(
        "--stage",
        required=True,
        help="supported Story destination difficulty-stage-chapter, for example 1-20-9",
    )
    parser.add_argument("--ap-cost", required=True, type=int)
    parser.add_argument("--ap-budget", required=True, type=int)
    parser.add_argument("--max-runs", required=True, type=int)
    parser.add_argument("--initial-ap", type=int, help="resume-only verified AP before an in-flight battle")
    parser.add_argument("--battle-timeout", type=float, default=180)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--post-input-delay", type=float, default=1)
    parser.add_argument("--recognition-timeout", type=float, default=25)
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument("--execute", action="store_true", help="allow bounded tap/swipe dispatch")
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/campaign-ap-live"))
    args = parser.parse_args(argv)

    if not is_permitted_local_bluestacks_serial(args.serial):
        parser.error("serial is not a permitted local BlueStacks endpoint")
    stage = parse_supported_campaign_story_destination(args.stage)
    config = CampaignAutoBattleConfig(
        target_stage=stage,
        ap_cost=args.ap_cost,
        ap_budget=args.ap_budget,
        max_runs=args.max_runs,
        battle_poll_seconds=args.poll_seconds,
        battle_timeout_seconds=args.battle_timeout,
    )
    if not args.execute:
        print(json.dumps({"status": "dry-run", "stage": stage.identity, "dispatch": False}, sort_keys=True))
        return 0

    answer = input(f"Confirm exact BlueStacks serial '{args.serial}' for Campaign {stage.identity}? [y/N]: ")
    if answer.strip().casefold() not in {"y", "yes"}:
        print("Campaign AP run cancelled", file=sys.stderr)
        return 2

    runner = ADBRunner(args.adb, args.serial)
    devices = {device.serial: device.state for device in runner.list_devices()}
    if devices.get(args.serial) != "device" or runner.get_state() != "device":
        raise RuntimeError("exact BlueStacks serial is not in device state")

    session = args.output_directory / f"{stage.identity}-{utc_stamp()}"
    frames = session / "frames"
    frames.mkdir(parents=True, exist_ok=False)
    events = session / "events.jsonl"
    controller = CampaignRuntimeController(config, initial_ap=args.initial_ap)
    battle_started: float | None = None
    ordinal = 0

    for step in range(1, args.max_steps + 1):
        deadline = time.monotonic() + args.recognition_timeout
        recognition = None
        while time.monotonic() < deadline:
            ordinal += 1
            frame_path = frames / f"frame-{ordinal:04d}.png"
            frame = capture(runner, frame_path)
            elapsed = 0 if battle_started is None else time.monotonic() - battle_started
            candidate = recognize_campaign_frame(frame, stage, battle_elapsed_seconds=elapsed)
            append_event(
                events,
                {
                    "type": "observation",
                    "step": step,
                    "frame": str(frame_path),
                    "frame_sha256": candidate.frame_sha256,
                    "screen": candidate.observation.screen.value,
                    "recognized": candidate.observation.recognized,
                    "targets": dict(candidate.targets),
                    "diagnostics": candidate.diagnostics,
                },
            )
            if candidate.observation.recognized:
                recognition = candidate
                break
            time.sleep(min(0.5, args.poll_seconds))
        if recognition is None:
            raise RuntimeError("no recognized Campaign state before recognition timeout")

        if recognition.observation.screen == CampaignScreen.BATTLE and battle_started is None:
            battle_started = time.monotonic()
            recognition = recognize_campaign_frame(frame, stage, battle_elapsed_seconds=0)
        elif recognition.observation.screen != CampaignScreen.BATTLE:
            battle_started = None

        command = controller.next_command(recognition)
        append_event(
            events,
            {
                "type": "command",
                "step": step,
                "action": command.action.value,
                "kind": command.kind,
                "reason": command.reason,
                "target_identity": command.target_identity,
                "target_roi": command.target_roi,
                "tap_point": command.tap_point,
                "swipe": command.swipe,
                "progress": controller.progress,
            },
        )
        print(f"{step:03d} {recognition.observation.screen.value} -> {command.action.value}: {command.reason}")
        if command.terminal:
            result = {
                "status": "completed" if command.action.value == "COMPLETE" else "blocked",
                "reason": command.reason,
                "session": str(session),
                "progress": controller.progress,
            }
            (session / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(result, sort_keys=True, default=str))
            return 0 if result["status"] == "completed" else 3
        if command.kind == "wait":
            time.sleep(command.wait_seconds or args.poll_seconds)
            continue
        if command.kind == "tap":
            assert command.tap_point is not None
            runner.dispatch_tap(command.tap_point)
        elif command.kind == "swipe":
            assert command.swipe is not None
            x0, y0, x1, y1, duration = command.swipe
            runner.dispatch_swipe((x0, y0), (x1, y1), duration)
        else:
            raise RuntimeError(f"unsupported Campaign command kind: {command.kind}")
        controller.accept_dispatched(command)
        time.sleep(args.post_input_delay)

    raise RuntimeError("Campaign AP maximum controller steps exceeded")


if __name__ == "__main__":
    raise SystemExit(main())
