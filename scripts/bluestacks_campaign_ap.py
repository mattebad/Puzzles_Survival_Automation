#!/usr/bin/env python3
"""Run one bounded Campaign AP route against an explicitly selected local BlueStacks serial.

Dry-run is the default.  ``--execute`` is required for input, and every fresh frame plus command
is retained under ``.local-captures``.  This adapter never connects ADB and rejects non-local
BlueStacks serials.

``--navigation-only`` verifies an exact supported Story destination and stops at
``destination_verified`` / ``navigation_only_complete`` without Challenge or AP consumption.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
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
from bluestacks_native_runtime import LocalBlueStacksRuntime
from home_atlas_bluestacks import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID,
    campaign_home_atlas_building_id,
    require_campaign_home_atlas_building,
    run_verified_campaign_home_atlas_entry,
)
from tasks.campaign_auto_battle import (
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignScreen,
    parse_supported_campaign_story_destination,
)
from tasks.campaign_auto_battle_runtime import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID as RUNTIME_CAMPAIGN_BUILDING_ID,
    CampaignRuntimeController,
)
from tasks.campaign_auto_battle_vision import recognize_campaign_frame


DEFAULT_HOME_ATLAS = (
    REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def append_event(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def write_navigation_only_evidence(session: Path, result: dict[str, object]) -> None:
    """Persist navigation-only ledger/journal/capability-audit required by flow-delivery evidence."""

    status = str(result.get("status") or "unknown")
    reason = str(result.get("reason") or "")
    navigation_only = bool(result.get("navigation_only", True))
    progress = result.get("progress")
    if hasattr(progress, "__dict__"):
        progress = dict(progress.__dict__)
    row = {
        "status": status,
        "reason": reason,
        "navigation_only": navigation_only,
        "session": str(session),
        "destination": result.get("destination"),
        "ap_before": result.get("ap_before"),
        "ap_after": result.get("ap_after"),
        "ap_cost": result.get("ap_cost"),
        "battle_outcome": result.get("battle_outcome"),
        "progress": progress,
    }
    for name in ("ledger.jsonl", "journal.jsonl", "capability-audit.jsonl"):
        path = session / name
        if path.exists() and path.stat().st_size > 0:
            continue
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            if name == "capability-audit.jsonl":
                handle.write(
                    json.dumps(
                        {
                            **row,
                            "authority": "CampaignRuntimeController",
                            "authorized": status
                            in {"destination_verified", "navigation_only_complete", "completed"},
                            "transport_observed": status == "completed" and not navigation_only,
                            "consequence_class": "navigation_only" if navigation_only else "campaign_ap_auto_battle",
                        },
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )
            else:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def relocalization_residual_pixels(
    localization_residual_px: float | None,
    remaining_displacement: tuple[float, float] | None = None,
) -> float | None:
    """Prefer Home Atlas localization residual; else pan remaining displacement magnitude."""

    if localization_residual_px is not None:
        return float(localization_residual_px)
    if remaining_displacement is None:
        return None
    return float(math.hypot(remaining_displacement[0], remaining_displacement[1]))


def capture(runner: ADBRunner, path: Path) -> np.ndarray:
    payload = runner.capture_png()
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1280, 800):
        raise RuntimeError("BlueStacks screenshot is not a native 800x1280 PNG")
    path.write_bytes(payload)
    return frame


_CAMPAIGN_ENTRY_OPEN_SCREENS = frozenset(
    {
        CampaignScreen.TIER_MAP,
        CampaignScreen.CHAPTER_MAP,
        CampaignScreen.STAGE_DIALOG,
        CampaignScreen.HERO_LINEUP,
    }
)


def _campaign_entry_semantically_opened(frame: np.ndarray) -> bool:
    """True only when post-entry vision binds Campaign/TIER_MAP (or equivalent)."""

    # Screen classification only; any supported destination supplies OCR targets.
    stage = parse_supported_campaign_story_destination("1-20-9")
    recognition = recognize_campaign_frame(frame, stage)
    return (
        recognition.observation.recognized
        and recognition.observation.screen in _CAMPAIGN_ENTRY_OPEN_SCREENS
    )


def _dispatch_home_atlas_campaign_entry(
    *,
    runner: ADBRunner,
    frames: Path,
    events: Path,
    execute: bool,
    maximum_pans: int = 4,
    maximum_inputs: int = 12,
    post_input_delay: float = 1.0,
    atlas_path: Path = DEFAULT_HOME_ATLAS,
) -> dict[str, object]:
    """Pan/bind/open Campaign via verified Home Atlas path; never raw ADB or HOME_PAN_GESTURES."""

    building_id = require_campaign_home_atlas_building(atlas_path)
    assert building_id == RUNTIME_CAMPAIGN_BUILDING_ID == campaign_home_atlas_building_id()
    entry_session = frames.parent / f"home-atlas-entry-{utc_stamp()}"
    runtime = LocalBlueStacksRuntime(runner, entry_session, execute=execute)
    runtime.max_inputs = min(runtime.max_inputs, int(maximum_inputs))
    result = run_verified_campaign_home_atlas_entry(
        runtime,
        atlas_path=atlas_path,
        maximum_pans=maximum_pans,
        execute=execute,
        settle_seconds=post_input_delay,
        semantic_opened_check=_campaign_entry_semantically_opened,
    )
    append_event(
        events,
        {
            "type": "home_atlas_entry_verified",
            "building_id": building_id,
            "entry_session": str(entry_session),
            **{k: v for k, v in result.items() if k != "tap_telemetry"},
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="BlueStacks HD-Adb.exe path")
    parser.add_argument("--serial", required=True, help="exact local BlueStacks serial")
    parser.add_argument(
        "--stage",
        required=True,
        help="supported Story destination difficulty-chapter-stage, for example 1-20-9",
    )
    parser.add_argument("--ap-cost", required=True, type=int)
    parser.add_argument("--ap-budget", required=True, type=int)
    parser.add_argument("--max-runs", required=True, type=int)
    parser.add_argument("--max-inputs", type=int, default=12)
    parser.add_argument("--initial-ap", type=int, help="resume-only verified AP before an in-flight battle")
    parser.add_argument("--battle-timeout", type=float, default=180)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--post-input-delay", type=float, default=1)
    parser.add_argument("--recognition-timeout", type=float, default=25)
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument(
        "--navigation-only",
        action="store_true",
        help="verify destination only; stop before Challenge/AP",
    )
    parser.add_argument("--atlas", type=Path, default=DEFAULT_HOME_ATLAS)
    parser.add_argument("--execute", action="store_true", help="allow bounded tap/swipe dispatch")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive serial confirmation (required for operator-driven live delivery)",
    )
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/campaign-ap-live"))
    args = parser.parse_args(argv)
    if not 1 <= args.max_inputs <= 12:
        parser.error("--max-inputs must be between 1 and 12")

    if not is_permitted_local_bluestacks_serial(args.serial):
        parser.error("serial is not a permitted local BlueStacks endpoint")
    stage = parse_supported_campaign_story_destination(args.stage)
    require_campaign_home_atlas_building(args.atlas)
    config = CampaignAutoBattleConfig(
        target_stage=stage,
        ap_cost=args.ap_cost,
        ap_budget=args.ap_budget,
        max_runs=args.max_runs,
        battle_poll_seconds=args.poll_seconds,
        battle_timeout_seconds=args.battle_timeout,
        navigation_only=bool(args.navigation_only),
    )
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "stage": stage.identity,
                    "dispatch": False,
                    "navigation_only": config.navigation_only,
                    "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                },
                sort_keys=True,
            )
        )
        return 0

    mode = "navigation-only" if config.navigation_only else "AP"
    if not args.yes:
        answer = input(
            f"Confirm exact BlueStacks serial '{args.serial}' for Campaign {mode} {stage.identity}? [y/N]: "
        )
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
    started = time.monotonic()
    navigation_inputs = 0
    last_relocalization_residual_pixels: float | None = None

    for step in range(1, args.max_steps + 1):
        recognition_window = (
            max(args.recognition_timeout, args.battle_timeout)
            if battle_started is not None
            else args.recognition_timeout
        )
        deadline = time.monotonic() + recognition_window
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

        command = controller.next_command(recognition, frame=frame)
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
                "progress": controller.progress.__dict__ if controller.progress else None,
            },
        )
        print(f"{step:03d} {recognition.observation.screen.value} -> {command.action.value}: {command.reason}")
        if command.terminal:
            if command.action in {
                CampaignAction.DESTINATION_VERIFIED,
                CampaignAction.NAVIGATION_ONLY_COMPLETE,
            }:
                status = (
                    "destination_verified"
                    if command.action == CampaignAction.DESTINATION_VERIFIED
                    else "navigation_only_complete"
                )
                result = {
                    "status": status,
                    "terminal": "navigation_only_complete",
                    "reason": command.reason,
                    "session": str(session),
                    "navigation_only": True,
                    "progress": controller.progress.__dict__ if controller.progress else None,
                    "destination": stage.identity,
                    "destination_verification_latency_seconds": time.monotonic() - started,
                    "navigation_input_count": navigation_inputs,
                    "relocalization_residual_pixels": last_relocalization_residual_pixels,
                }
                (session / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                )
                write_navigation_only_evidence(session, result)
                print(json.dumps(result, sort_keys=True, default=str))
                return 0
            if command.action == CampaignAction.COMPLETE:
                result = {
                    "status": "completed",
                    "terminal": "completed",
                    "reason": command.reason,
                    "session": str(session),
                    "progress": controller.progress.__dict__ if controller.progress else None,
                    "navigation_only": False,
                    "destination": stage.identity,
                    "ap_before": controller.progress.initial_ap if controller.progress else None,
                    "ap_after": controller.progress.current_ap if controller.progress else None,
                    "ap_cost": config.ap_cost,
                    "battle_outcome": "victory" if controller.progress and controller.progress.completed_runs else "defeat",
                }
            else:
                result = {
                    "status": "blocked_fail_closed",
                    "terminal": "blocked_fail_closed",
                    "reason": command.reason,
                    "session": str(session),
                    "progress": controller.progress.__dict__ if controller.progress else None,
                    "navigation_only": config.navigation_only,
                    "destination": stage.identity,
                }
            (session / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            write_navigation_only_evidence(session, result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 0 if result["status"] == "completed" else 3
        if command.kind == "wait":
            time.sleep(command.wait_seconds or args.poll_seconds)
            continue
        if command.kind == "home_atlas_entry":
            if navigation_inputs >= args.max_inputs:
                raise RuntimeError(
                    "Campaign AP input budget exhausted before Home Atlas entry"
                )
            entry = _dispatch_home_atlas_campaign_entry(
                runner=runner,
                frames=frames,
                events=events,
                execute=True,
                post_input_delay=args.post_input_delay,
                atlas_path=args.atlas,
                maximum_inputs=args.max_inputs - navigation_inputs,
            )
            append_event(events, {"type": "home_atlas_entry_result", **entry})
            residual = entry.get("relocalization_residual_pixels")
            if isinstance(residual, (int, float)):
                last_relocalization_residual_pixels = float(residual)
            if entry["status"] != "opened":
                result = {
                    "status": "blocked_fail_closed",
                    "reason": entry.get("reason", "Home Atlas Campaign entry failed"),
                    "session": str(session),
                    "home_atlas_entry": entry,
                    "relocalization_residual_pixels": last_relocalization_residual_pixels,
                }
                (session / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                )
                write_navigation_only_evidence(session, result)
                print(json.dumps(result, sort_keys=True, default=str))
                return 3
            navigation_inputs += 1 + len(entry.get("records", []))
            if navigation_inputs > args.max_inputs:
                raise RuntimeError("Campaign AP input budget exhausted during Home Atlas entry")
            controller.accept_dispatched(command)
            continue
        if navigation_inputs >= args.max_inputs:
            raise RuntimeError("Campaign AP input budget exhausted before dispatch")
        if command.kind == "tap":
            assert command.tap_point is not None
            runner.dispatch_tap(command.tap_point)
            navigation_inputs += 1
        elif command.kind == "swipe":
            assert command.swipe is not None
            x0, y0, x1, y1, duration = command.swipe
            runner.dispatch_swipe((x0, y0), (x1, y1), duration)
            navigation_inputs += 1
        else:
            raise RuntimeError(f"unsupported Campaign command kind: {command.kind}")
        controller.accept_dispatched(command)
        time.sleep(args.post_input_delay)

    raise RuntimeError("Campaign AP maximum controller steps exceeded")


if __name__ == "__main__":
    raise SystemExit(main())
