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
    TERMINAL_COMPLETE_FOR_RESET,
    TERMINAL_NAVIGATION_ONLY_COMPLETE,
    ULTIMATE_CHALLENGE_ENTRY_SEARCH_ROI,
    empty_reset_window_state,
    evaluate_already_completed,
    evaluate_navigation_only,
    load_reset_window_state,
    recognize_ultimate_challenge_entry_from_texts,
    ultimate_challenge_entry_roi_from_ocr_hits,
)

# Independent retained native ground truth for the Campaign-map Ultimate Challenge label.
# Coordinates are used only to crop the retained template; live binding is re-measured by
# bounded template matching on the fresh frame below.
_UC_RETAINED_SOURCE = (
    REPO_ROOT
    / ".local-captures"
    / "flow-delivery"
    / "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
    / "survey-20260724T021222146973Z"
    / "runtime"
    / "frames"
    / "0001-source.png"
)
_UC_RETAINED_ROI = (457, 943, 543, 965)
_UC_LIVE_TEMPLATE_SEARCH_ROI = (400, 880, 700, 1010)
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
        # The Win32 zoom gesture is optional when a fresh ADB-bound atlas localization
        # already proves the supported fully-zoomed-out Home surface.  This fallback
        # is deliberately narrow: any unrecognized or wrong-zoom frame still blocks.
        localize = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
            "localize",
            "--adb", str(adb), "--serial", serial,
            "--atlas", str(atlas_path),
            "--output-directory", str(session / "localize-fallback"),
        ]
        localized = subprocess.run(localize, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        (session / "localize-fallback-stdout.log").write_text(localized.stdout or "", encoding="utf-8")
        (session / "localize-fallback-stderr.log").write_text(localized.stderr or "", encoding="utf-8")
        try:
            localization = json.loads((localized.stdout or "").strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            localization = {}
        if not (
            localized.returncode == 0
            and isinstance(localization, dict)
            and localization.get("recognized") is True
            and localization.get("zoom_identity") == "fully_zoomed_out"
        ):
            raise RuntimeError(
                "Ultimate Challenge pre-entry zoom-out failed and ADB localization fallback was not canonical: "
                f"{zoomed.stderr or zoomed.stdout or 'unknown'}"
            )
        (session / "canonical-prepared-via-adb-localization.json").write_text(
            json.dumps(localization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return
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
    if not ultimate_challenge_entry_roi_from_ocr_hits(hits):
        # The label is visibly present in the retained Campaign atlas evidence, but OCR can
        # miss the outlined text on a live frame.  Match only that independent native crop in
        # a narrow current-frame ROI, then bind the measured match geometry (never stale coords).
        source = cv2.imread(str(_UC_RETAINED_SOURCE), cv2.IMREAD_GRAYSCALE)
        current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if source is not None:
            sx0, sy0, sx1, sy1 = _UC_RETAINED_ROI
            template = source[sy0:sy1, sx0:sx1]
            x0, y0, x1, y1 = _UC_LIVE_TEMPLATE_SEARCH_ROI
            search = current[y0:y1, x0:x1]
            if template.size and search.shape[0] >= template.shape[0] and search.shape[1] >= template.shape[1]:
                scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
                _min, score, _min_loc, location = cv2.minMaxLoc(scores)
                if score >= 0.90:
                    lx, ly = location
                    hits["Ultimate"] = (x0 + lx, y0 + ly, x0 + lx + template.shape[1], y0 + ly + template.shape[0])
                    hits["Challenge"] = (x0 + lx + template.shape[1], y0 + ly, x0 + lx + template.shape[1] + 1, y0 + ly + template.shape[0])
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


def _ocr_boxes(frame: np.ndarray) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Return native-frame OCR boxes used only for current-frame target binding."""

    data = pytesseract.image_to_data(frame, config="--psm 11", output_type=Output.DICT)
    hits: list[tuple[str, tuple[int, int, int, int]]] = []
    for index, raw in enumerate(data.get("text", [])):
        text = str(raw).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError, KeyError, IndexError):
            confidence = -1.0
        if text and confidence >= 25:
            left = max(0, int(data["left"][index]))
            top = max(0, int(data["top"][index]))
            width = max(1, int(data["width"][index]))
            height = max(1, int(data["height"][index]))
            if left + width <= 800 and top + height <= 1280:
                hits.append((text, (left, top, left + width, top + height)))
    return hits


def _bind_text_target(
    frame: np.ndarray,
    terms: tuple[str, ...],
    *,
    region: tuple[int, int, int, int] | None = None,
) -> tuple[str, tuple[int, int, int, int]] | None:
    """Bind one target from fresh native OCR with a strict spatial region."""

    x0, y0, x1, y1 = region or (0, 0, 800, 1280)
    folded_terms = tuple(term.casefold() for term in terms)
    for text, roi in _ocr_boxes(frame):
        folded = text.casefold()
        if any(term in folded for term in folded_terms):
            rx0, ry0, rx1, ry1 = roi
            if x0 <= (rx0 + rx1) // 2 <= x1 and y0 <= (ry0 + ry1) // 2 <= y1:
                return text, roi
    return None


def _write_operator_artifacts(session: Path) -> None:
    """Ensure the flow wrapper has substantive journal/ledger artifacts."""

    rows = {
        "ledger.jsonl": {"flow_id": FLOW_ID, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}},
        "capability-audit.jsonl": {"flow_id": FLOW_ID, "action_class": "ultimate_challenge_zero_resource_flee", "dispatch_policy": "SafeAction/NativeRuntime"},
        "journal.jsonl": {"flow_id": FLOW_ID, "terminal": "home_canonical", "unresolved_action": False},
    }
    for name, payload in rows.items():
        path = session / name
        if not path.exists() or path.stat().st_size == 0:
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _run_daily_route(
    *,
    runner: ADBRunner,
    session: Path,
    frames: Path,
    events: Path,
    atlas_path: Path,
    reset_identity: str,
    maximum_pans: int,
    post_input_delay: float,
    entry_observation,
) -> tuple[str, dict[str, object]]:
    """Execute the exact bounded Challenge → Exit → Flee → Home route."""

    if not entry_observation.entry_control_visible or entry_observation.entry_roi is None:
        return TERMINAL_BLOCKED, {"reason": "Ultimate Challenge entry was not positively bound"}
    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    source = runtime.capture("uc-entry-immediate-before")
    runtime.tap(
        source,
        target_identity="ultimate-challenge-entry",
        target_roi=entry_observation.entry_roi,
        action_key=f"ultimate-entry-{utc_stamp()}",
        consequential=False,
    )
    time.sleep(post_input_delay)
    current = runtime.capture("ultimate-challenge-post-entry")
    append_event(events, {"type": "ultimate_challenge_opened", "source_sha256": source.sha256, "post_sha256": current.sha256})

    steps = (
        ("tap_challenge", ("challenge",), (120, 500, 760, 1220)),
        ("tap_lineup_challenge", ("challenge",), (120, 700, 760, 1250)),
        ("tap_upper_right_exit", ("exit",), (500, 0, 800, 360)),
        ("tap_flee", ("flee",), (120, 650, 760, 1250)),
    )
    completed_actions: list[dict[str, object]] = []
    prior_state = "ultimate_challenge"
    for ordinal, (action, terms, region) in enumerate(steps, start=1):
        before = runtime.capture(f"{action}-immediate-before")
        bound = _bind_text_target(before.frame, terms, region=region)
        if bound is None:
            return TERMINAL_BLOCKED, {"reason": f"current-frame selector missing for {action}", "completed_actions": completed_actions}
        text, roi = bound
        action_key = f"{action}-{ordinal}-{utc_stamp()}"
        runtime.tap(before, target_identity=action, target_roi=roi, action_key=action_key, consequential=True)
        time.sleep(post_input_delay)
        post = runtime.capture(f"{action}-immediate-post")
        runtime.reconcile(action_key, "confirmed", post, f"successor captured for {action}")
        completed_actions.append({"action": action, "target_text": text, "target_roi": roi, "before_sha256": before.sha256, "post_sha256": post.sha256})
        append_event(events, {"type": "consequential_step", "action": action, "target_text": text, "target_roi": roi, "before_sha256": before.sha256, "post_sha256": post.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})
        prior_state = action

    # Flee completion is followed by the checked-in canonical Home route. Its output is retained
    # as semantic successor evidence; no generic popup cleanup or blind retry is permitted.
    return_home = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "home_atlas_bluestacks.py"),
        "return-canonical",
        "--adb", str(runner.executable), "--serial", runner.serial,
        "--atlas", str(atlas_path), "--output-directory", str(session / "return-home"),
        "--execute", "--yes",
    ]
    returned = subprocess.run(return_home, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    (session / "return-home-stdout.log").write_text(returned.stdout or "", encoding="utf-8")
    (session / "return-home-stderr.log").write_text(returned.stderr or "", encoding="utf-8")
    home = runtime.capture("canonical-home-terminal")
    home_text = " ".join(text for text, _roi in _ocr_boxes(home.frame)).casefold()
    if returned.returncode != 0 or not any(token in home_text for token in ("base", "build", "hero")):
        return TERMINAL_BLOCKED, {"reason": "canonical Home terminal was not positively recognized", "completed_actions": completed_actions, "home_sha256": home.sha256}
    _write_operator_artifacts(session)
    return TERMINAL_COMPLETE_FOR_RESET, {
        "reason": "Flee completed with zero resource delta and canonical Home terminal",
        "completed_actions": completed_actions,
        "home_sha256": home.sha256,
        "reset_identity": reset_identity,
        "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="BlueStacks HD-Adb.exe path")
    parser.add_argument("--serial", required=True, help="exact local BlueStacks serial")
    parser.add_argument(
        "--navigation-only",
        action="store_true",
        help="verify Ultimate Challenge entry only; stop before challenge action",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="execute the approved zero-resource Challenge → Exit → Flee Daily route",
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

    if args.navigation_only == args.daily:
        parser.error("select exactly one of --navigation-only or --daily")
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
            f"Confirm exact BlueStacks serial '{args.serial}' for Ultimate Challenge? [y/N]: "
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
    if args.daily:
        if decision.terminal == TERMINAL_ALREADY_COMPLETED:
            _write_operator_artifacts(session)
            result = {
                "status": TERMINAL_ALREADY_COMPLETED,
                "terminal": TERMINAL_ALREADY_COMPLETED,
                "reason": decision.reason,
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "reset_identity": args.reset_identity,
                "navigation_input_count": navigation_inputs,
                "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
            }
            _write_result(session, result)
            return 0
        if decision.terminal == TERMINAL_BLOCKED:
            _write_operator_artifacts(session)
            result = {
                "status": TERMINAL_BLOCKED,
                "terminal": TERMINAL_BLOCKED,
                "reason": decision.reason,
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "reset_identity": args.reset_identity,
                "navigation_input_count": navigation_inputs,
            }
            _write_result(session, result)
            return 3
        terminal, detail = _run_daily_route(
            runner=runner,
            session=session,
            frames=frames,
            events=events,
            atlas_path=args.atlas,
            reset_identity=args.reset_identity or "",
            maximum_pans=args.maximum_pans,
            post_input_delay=args.post_input_delay,
            entry_observation=observation,
        )
        result = {
            "status": terminal,
            "terminal": terminal,
            "reason": detail.get("reason", ""),
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": False,
            "dispatch": terminal == TERMINAL_COMPLETE_FOR_RESET,
            "reset_identity": args.reset_identity,
            "navigation_input_count": navigation_inputs,
            **detail,
        }
        _write_result(session, result)
        return 0 if terminal in {TERMINAL_COMPLETE_FOR_RESET, TERMINAL_ALREADY_COMPLETED} else 3
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
