#!/usr/bin/env python3
"""Run one bounded Ultimate Challenge navigation-only route on local BlueStacks.

Dry-run is the default. ``--execute`` is required for input. This adapter never
connects remote ADB and rejects non-local BlueStacks serials.

``--navigation-only`` prepares Home (zoom-out + return-canonical), opens Campaign
via verified Home Atlas ``home.building.campaign``, binds/verifies the Ultimate
Challenge entry control on the Campaign screen, and stops at
``navigation_only_complete`` (or offline ``already_completed`` without action).

Ultimate Challenge is never routed through Campaign story destination parsing
(``1-20-9`` / ``1-15-9`` / ``2-2-9`` or ``ultimate-challenge`` as a destination).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
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
    require_campaign_home_atlas_building,
    run_verified_ultimate_challenge_campaign_door,
)
from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks.ultimate_challenge_daily import (
    FLOW_ID,
    TERMINAL_ALREADY_COMPLETED,
    TERMINAL_BLOCKED,
    TERMINAL_NAVIGATION_ONLY_COMPLETE,
    ULTIMATE_CHALLENGE_ENTRY_SEARCH_ROI,
    empty_reset_window_state,
    evaluate_already_completed,
    evaluate_navigation_only,
    load_reset_window_state,
    recognize_ultimate_challenge_entry_from_texts,
)
import pytesseract
from pytesseract import Output

DEFAULT_HOME_ATLAS = (
    REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
)


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


def frame_sha256(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("failed to encode frame for sha256")
    return hashlib.sha256(encoded.tobytes()).hexdigest()


_CAMPAIGN_ENTRY_OPEN_SCREENS = frozenset(
    {
        CampaignScreen.TIER_MAP,
        CampaignScreen.CHAPTER_MAP,
        CampaignScreen.STAGE_DIALOG,
        CampaignScreen.HERO_LINEUP,
    }
)

# Destination-free classification stub for recognize_campaign_frame incidental labels only.
# Not a selected Campaign AP story destination and never routed through the AP parser.
_UC_CAMPAIGN_OPEN_CLASSIFIER_STAGE = CampaignStage(1, 1, 1)


def _classify_campaign_ui_open(frame: np.ndarray):
    """Classify Campaign-open screens without parsing supported story destinations."""

    return recognize_campaign_frame(frame, _UC_CAMPAIGN_OPEN_CLASSIFIER_STAGE)


def _campaign_entry_semantically_opened(frame: np.ndarray) -> bool:
    """True only when post-entry vision binds Campaign/TIER_MAP (or equivalent)."""

    recognition = _classify_campaign_ui_open(frame)
    return (
        recognition.observation.recognized
        and recognition.observation.screen in _CAMPAIGN_ENTRY_OPEN_SCREENS
    )


def _prepare_canonical_home(
    *,
    adb: Path,
    serial: str,
    session: Path,
    atlas_path: Path,
) -> None:
    canonical_reference = atlas_path.parent / "tiles" / "viewport-001.png"
    if not canonical_reference.is_file():
        raise RuntimeError("Home Atlas viewport-001.png reference is missing for zoom-out")
    zoom = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
        "zoom-out",
        "--adb",
        str(adb),
        "--serial",
        serial,
        "--canonical-reference",
        str(canonical_reference),
        "--output-directory",
        str(session / "zoom-out"),
        "--execute",
        "--yes",
    ]
    zoomed = subprocess.run(zoom, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    (session / "zoom-out-stdout.log").write_text(zoomed.stdout or "", encoding="utf-8")
    (session / "zoom-out-stderr.log").write_text(zoomed.stderr or "", encoding="utf-8")
    if zoomed.returncode != 0:
        raise RuntimeError(
            "Ultimate Challenge pre-entry zoom-out failed: "
            f"{zoomed.stderr or zoomed.stdout or 'unknown'}"
        )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
        "return-canonical",
        "--adb",
        str(adb),
        "--serial",
        serial,
        "--atlas",
        str(atlas_path),
        "--output-directory",
        str(session / "return-canonical"),
        "--execute",
        "--yes",
    ]
    completed = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    (session / "return-canonical-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (session / "return-canonical-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            "Ultimate Challenge pre-entry return-canonical failed: "
            f"{completed.stderr or completed.stdout or 'unknown'}"
        )


def _ocr_entry_hits(frame: np.ndarray) -> dict[str, tuple[int, int, int, int]]:
    """OCR word boxes inside the Ultimate Challenge entry search ROI."""

    x0, y0, x1, y1 = ULTIMATE_CHALLENGE_ENTRY_SEARCH_ROI
    crop = frame[y0:y1, x0:x1]
    scale = 3
    enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    hits: dict[str, tuple[int, int, int, int]] = {}
    for index, raw in enumerate(data["text"]):
        text = str(raw).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if not text or confidence < 30:
            continue
        left = x0 + int(data["left"][index]) // scale
        top = y0 + int(data["top"][index]) // scale
        width = max(1, int(data["width"][index]) // scale)
        height = max(1, int(data["height"][index]) // scale)
        hits[text] = (left, top, left + width, top + height)
    return hits


def _bind_ultimate_challenge_entry(frame: np.ndarray, *, reset_identity: str | None):
    # Destination-free Campaign-open classification; never selects a Campaign AP story destination.
    recognition = _classify_campaign_ui_open(frame)
    campaign_open = (
        recognition.observation.recognized
        and recognition.observation.screen in _CAMPAIGN_ENTRY_OPEN_SCREENS
    )
    hits = _ocr_entry_hits(frame)
    digest = recognition.frame_sha256 or frame_sha256(frame)
    # Marker auto-derived inside recognize: generic claimed/already-complet require UC entry bind.
    return recognize_ultimate_challenge_entry_from_texts(
        campaign_screen_recognized=campaign_open,
        ocr_hits=hits,
        source_frame_sha256=digest,
        reset_identity=reset_identity,
    )


def _write_result(session: Path, result: dict[str, object]) -> None:
    (session / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="BlueStacks HD-Adb.exe path")
    parser.add_argument("--serial", required=True, help="exact local BlueStacks serial")
    parser.add_argument(
        "--navigation-only",
        action="store_true",
        help="verify Ultimate Challenge entry only; stop before challenge action",
    )
    parser.add_argument("--atlas", type=Path, default=DEFAULT_HOME_ATLAS)
    parser.add_argument("--execute", action="store_true", help="allow bounded tap/swipe dispatch")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive serial confirmation (required for operator-driven live delivery)",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path(".local-captures/ultimate-challenge-live"),
    )
    parser.add_argument(
        "--reset-identity",
        default=None,
        help="positively established game-day / reset identity for already_completed checks",
    )
    parser.add_argument(
        "--reset-state-path",
        type=Path,
        default=None,
        help="optional persistent last-success/reset-window JSON path",
    )
    parser.add_argument("--maximum-pans", type=int, default=4)
    parser.add_argument("--post-input-delay", type=float, default=1.0)
    args = parser.parse_args(argv)

    if not args.navigation_only:
        parser.error("Ultimate Challenge operator currently supports --navigation-only only")
    if not is_permitted_local_bluestacks_serial(args.serial):
        parser.error("serial is not a permitted local BlueStacks endpoint")
    require_campaign_home_atlas_building(args.atlas)

    state = (
        load_reset_window_state(args.reset_state_path)
        if args.reset_state_path is not None
        else empty_reset_window_state()
    )
    precheck = evaluate_already_completed(state, current_reset_identity=args.reset_identity)
    if precheck.terminal == TERMINAL_ALREADY_COMPLETED:
        session = args.output_directory / f"already-completed-{utc_stamp()}"
        session.mkdir(parents=True, exist_ok=False)
        result = {
            "status": TERMINAL_ALREADY_COMPLETED,
            "terminal": TERMINAL_ALREADY_COMPLETED,
            "reason": precheck.reason,
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": True,
            "dispatch": False,
            "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            "reset_identity": args.reset_identity,
            "navigation_input_count": 0,
        }
        _write_result(session, result)
        return 0
    if precheck.terminal == TERMINAL_BLOCKED and precheck.reason != "not already_completed":
        session = args.output_directory / f"blocked-{utc_stamp()}"
        session.mkdir(parents=True, exist_ok=False)
        result = {
            "status": TERMINAL_BLOCKED,
            "terminal": TERMINAL_BLOCKED,
            "reason": precheck.reason,
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": True,
            "dispatch": False,
            "reset_identity": args.reset_identity,
            "navigation_input_count": 0,
        }
        _write_result(session, result)
        return 3

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "dispatch": False,
                    "navigation_only": True,
                    "flow_id": FLOW_ID,
                    "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                    "reset_identity": args.reset_identity,
                },
                sort_keys=True,
            )
        )
        return 0

    if not args.yes:
        answer = input(
            f"Confirm exact BlueStacks serial '{args.serial}' for Ultimate Challenge navigation-only? [y/N]: "
        )
        if answer.strip().casefold() not in {"y", "yes"}:
            print("Ultimate Challenge run cancelled", file=sys.stderr)
            return 2

    runner = ADBRunner(args.adb, args.serial)
    devices = {device.serial: device.state for device in runner.list_devices()}
    if devices.get(args.serial) != "device" or runner.get_state() != "device":
        raise RuntimeError("exact BlueStacks serial is not in device state")

    session = args.output_directory / f"nav-{utc_stamp()}"
    frames = session / "frames"
    frames.mkdir(parents=True, exist_ok=False)
    events = session / "events.jsonl"
    started = time.monotonic()
    navigation_inputs = 0

    _prepare_canonical_home(
        adb=Path(args.adb),
        serial=args.serial,
        session=session,
        atlas_path=args.atlas,
    )
    append_event(events, {"type": "home_prepared", "flow_id": FLOW_ID})

    entry_session = session / f"home-atlas-entry-{utc_stamp()}"
    runtime = LocalBlueStacksRuntime(runner, entry_session, execute=True)
    entry = run_verified_ultimate_challenge_campaign_door(
        runtime,
        atlas_path=args.atlas,
        maximum_pans=args.maximum_pans,
        execute=True,
        settle_seconds=args.post_input_delay,
        semantic_opened_check=_campaign_entry_semantically_opened,
    )
    append_event(
        events,
        {
            "type": "home_atlas_campaign_door",
            "building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            "entry_session": str(entry_session),
            **{k: v for k, v in entry.items() if k != "tap_telemetry"},
        },
    )
    if entry.get("status") == "opened":
        navigation_inputs += 1
    if entry.get("status") != "opened":
        result = {
            "status": TERMINAL_BLOCKED,
            "terminal": TERMINAL_BLOCKED,
            "reason": entry.get("reason", "Home Atlas Campaign door failed for Ultimate Challenge"),
            "session": str(session),
            "flow_id": FLOW_ID,
            "home_atlas_entry": entry,
            "navigation_input_count": navigation_inputs,
            "home_recovery_latency_seconds": time.monotonic() - started,
        }
        _write_result(session, result)
        return 3

    frame_path = frames / "uc-entry-bind.png"
    frame = capture(runner, frame_path)
    observation = _bind_ultimate_challenge_entry(frame, reset_identity=args.reset_identity)
    append_event(
        events,
        {
            "type": "ultimate_challenge_entry_observation",
            "frame": str(frame_path),
            "campaign_screen_recognized": observation.campaign_screen_recognized,
            "entry_control_visible": observation.entry_control_visible,
            "entry_control_identity": observation.entry_control_identity,
            "entry_roi": observation.entry_roi,
            "already_completed_marker": observation.already_completed_marker,
            "source_frame_sha256": observation.source_frame_sha256,
            "reset_identity": observation.reset_identity,
        },
    )
    decision = evaluate_navigation_only(
        state,
        observation,
        current_reset_identity=args.reset_identity,
    )
    result = {
        "status": decision.terminal,
        "terminal": decision.terminal,
        "reason": decision.reason,
        "session": str(session),
        "flow_id": FLOW_ID,
        "navigation_only": True,
        "dispatch": False,
        "entry_roi": decision.entry_roi,
        "reset_identity": decision.reset_identity,
        "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
        "home_atlas_entry": {k: v for k, v in entry.items() if k != "tap_telemetry"},
        "navigation_input_count": navigation_inputs,
        "home_recovery_latency_seconds": time.monotonic() - started,
    }
    _write_result(session, result)
    if decision.terminal in {TERMINAL_NAVIGATION_ONLY_COMPLETE, TERMINAL_ALREADY_COMPLETED}:
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
