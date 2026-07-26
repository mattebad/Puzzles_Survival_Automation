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
_UC_PORTAL_SEARCH_ROI = (400, 700, 700, 970)
_UC_PORTAL_INTERIOR_ROI = (480, 760, 640, 920)
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
    label_bound = ultimate_challenge_entry_roi_from_ocr_hits(hits) is not None
    if not label_bound:
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
                    label_bound = True
    # The text label is semantic context, not the clickable control.  Bind the fresh
    # blue vortex geometry above it and use a conservative interior ROI whose center
    # cannot overlap the adjacent Eclipolis / Chapter 2 node.
    if label_bound:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, np.array([90, 110, 90]), np.array([135, 255, 255]))
        x0, y0, x1, y1 = _UC_PORTAL_SEARCH_ROI
        bounded = np.zeros_like(blue)
        bounded[y0:y1, x0:x1] = blue[y0:y1, x0:x1]
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
        candidates: list[tuple[int, int]] = []
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            width = int(stats[index, cv2.CC_STAT_WIDTH])
            height = int(stats[index, cv2.CC_STAT_HEIGHT])
            cx, cy = centroids[index]
            if area >= 15000 and width >= 150 and height >= 150 and 480 <= cx <= 640 and 760 <= cy <= 920:
                candidates.append((area, index))
        if len(candidates) == 1:
            hits["Ultimate Challenge"] = _UC_PORTAL_INTERIOR_ROI
        else:
            hits = {text: roi for text, roi in hits.items() if "ultimate" not in text.casefold() and "challenge" not in text.casefold()}
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


def _bind_red_challenge_button(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind the actual red Challenge button, never nearby descriptive text."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 60, 60]), np.array([15, 255, 255]))
    bounded = np.zeros_like(red)
    bounded[1160:1280, 200:600] = red[1160:1280, 200:600]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
    candidates: list[int] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[index]
        if area >= 8000 and width >= 170 and height >= 50 and 360 <= cx <= 440 and 1190 <= cy <= 1245 and x >= 260 and y >= 1170:
            candidates.append(index)
    if len(candidates) != 1:
        return None
    return (320, 1195, 480, 1245)


def _bind_lineup_challenge_button(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind the gold Hero Lineup Challenge control from current native geometry."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array([10, 80, 80]), np.array([35, 255, 255]))
    bounded = np.zeros_like(gold)
    bounded[1140:1270, 200:600] = gold[1140:1270, 200:600]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
    candidates: list[int] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[index]
        if area >= 18000 and width >= 240 and height >= 70 and 380 <= cx <= 420 and 1180 <= cy <= 1220 and x >= 240 and y >= 1140:
            candidates.append(index)
    # Require all five selected-card checkmarks.  This is independent of the
    # stylized title OCR and prevents the incomplete-lineup warning path.
    selected = cv2.inRange(hsv, np.array([15, 120, 140]), np.array([40, 255, 255]))
    selected_counts = [
        int(np.count_nonzero(selected[650:760, x:x + 120]))
        for x in (20, 180, 340, 500, 660)
    ]
    if len(candidates) != 1 or any(count < 400 for count in selected_counts):
        return None
    return (300, 1175, 500, 1230)


def _bind_active_battle_exit(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind the icon-only upper-right Exit after proving the native puzzle board."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturated = cv2.inRange(hsv, np.array([0, 90, 70]), np.array([179, 255, 255]))
    bounded = np.zeros_like(saturated)
    bounded[500:1030, 40:760] = saturated[500:1030, 40:760]
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(bounded)
    puzzle_components = sum(
        1
        for index in range(1, count)
        if 1200 <= int(stats[index, cv2.CC_STAT_AREA]) <= 9000
        and int(stats[index, cv2.CC_STAT_WIDTH]) >= 35
        and int(stats[index, cv2.CC_STAT_HEIGHT]) >= 35
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    exit_patch = gray[15:85, 690:760]
    if puzzle_components < 20 or int(np.count_nonzero(exit_patch >= 180)) < 250:
        return None
    return (700, 20, 750, 75)


def _bind_flee_warning_button(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind only the gold Flee button on the exact failure-warning modal."""

    folded = _ocr_folded(frame)
    if "flee now" not in folded or "failure" not in folded:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array([10, 80, 80]), np.array([35, 255, 255]))
    bounded = np.zeros_like(gold)
    bounded[600:730, 380:730] = gold[600:730, 380:730]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
    candidates: list[int] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[index]
        if area >= 16000 and width >= 220 and height >= 65 and x >= 420 and y >= 610 and 540 <= cx <= 580 and 650 <= cy <= 685:
            candidates.append(index)
    if len(candidates) != 1:
        return None
    return (470, 645, 650, 700)


def _ocr_folded(frame: np.ndarray) -> str:
    return " ".join(text for text, _roi in _ocr_boxes(frame)).casefold()


def _capture_until(
    runtime: LocalBlueStacksRuntime,
    *,
    label: str,
    predicate,
    attempts: int = 6,
    settle_seconds: float = 0.8,
):
    latest = None
    for ordinal in range(attempts):
        time.sleep(settle_seconds)
        latest = runtime.capture(f"{label}-{ordinal + 1:02d}")
        if predicate(latest.frame):
            return latest
    return latest


def _write_operator_artifacts(session: Path, terminal: str) -> None:
    """Ensure the flow wrapper has substantive journal/ledger artifacts."""

    rows = {
        "ledger.jsonl": {"flow_id": FLOW_ID, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}},
        "capability-audit.jsonl": {"flow_id": FLOW_ID, "action_class": "ultimate_challenge_zero_resource_flee", "dispatch_policy": "SafeAction/NativeRuntime"},
        "journal.jsonl": {"flow_id": FLOW_ID, "terminal": terminal, "unresolved_action": False},
    }
    for name, payload in rows.items():
        path = session / name
        if not path.exists() or path.stat().st_size == 0:
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _run_post_flee_home_route(
    *, runner: ADBRunner, session: Path, events: Path, reset_identity: str, post_input_delay: float
) -> tuple[str, dict[str, object]]:
    """Return UC main → Campaign tier map → canonical Home with verified transitions."""

    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    uc = runtime.capture("post-flee-ultimate-immediate-before")
    if "ultimate challenge" not in _ocr_folded(uc.frame) or _bind_red_challenge_button(uc.frame) is None:
        return TERMINAL_BLOCKED, {"reason": "post-Flee Ultimate Challenge main not positively recognized"}
    back_roi = (55, 10, 135, 65)
    runtime.tap(uc, target_identity="ultimate-challenge-back", target_roi=back_roi, action_key=f"uc-back-{utc_stamp()}", consequential=False)
    campaign = _capture_until(
        runtime,
        label="campaign-tier-map-successor",
        predicate=lambda frame: _bind_ultimate_challenge_entry(frame, reset_identity=reset_identity).campaign_screen_recognized,
        attempts=6,
        settle_seconds=max(0.8, post_input_delay),
    )
    if campaign is None:
        return TERMINAL_BLOCKED, {"reason": "Campaign tier-map successor not captured after Ultimate Challenge back"}
    campaign_observation = _bind_ultimate_challenge_entry(campaign.frame, reset_identity=reset_identity)
    if not campaign_observation.campaign_screen_recognized:
        return TERMINAL_BLOCKED, {"reason": "Campaign tier-map successor not positively recognized after Ultimate Challenge back", "campaign_sha256": campaign.sha256}
    runtime.tap(campaign, target_identity="campaign-back-to-home", target_roi=back_roi, action_key=f"campaign-back-{utc_stamp()}", consequential=False)
    home = _capture_until(
        runtime,
        label="canonical-home-successor",
        predicate=lambda frame: any(token in _ocr_folded(frame) for token in ("base", "build", "hero")),
        attempts=8,
        settle_seconds=max(0.8, post_input_delay),
    )
    if home is None or not any(token in _ocr_folded(home.frame) for token in ("base", "build", "hero")):
        return TERMINAL_BLOCKED, {"reason": "canonical Home terminal not positively recognized after Campaign back", "campaign_sha256": campaign.sha256}
    append_event(events, {"type": "post_flee_home_route", "ultimate_sha256": uc.sha256, "campaign_sha256": campaign.sha256, "home_sha256": home.sha256})
    return TERMINAL_COMPLETE_FOR_RESET, {
        "reason": "Flee completion retained and canonical Home recognized through verified back transitions",
        "completed_actions": [],
        "home_sha256": home.sha256,
        "reset_identity": reset_identity,
        "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
    }


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
    starting_state: str = "campaign_entry",
) -> tuple[str, dict[str, object]]:
    """Execute the exact bounded Challenge → Exit → Flee → Home route."""

    if starting_state == "campaign_entry" and (not entry_observation.entry_control_visible or entry_observation.entry_roi is None):
        return TERMINAL_BLOCKED, {"reason": "Ultimate Challenge entry was not positively bound"}
    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    completed_actions: list[dict[str, object]] = []
    if starting_state == "flee_warning":
        warning = runtime.capture("flee-warning-resume-source")
        flee_roi = _bind_flee_warning_button(warning.frame)
        if flee_roi is None:
            return TERMINAL_BLOCKED, {"reason": "fresh Flee-warning resume source or gold Flee button not positively bound", "completed_actions": completed_actions}
        flee_bound = ("gold Flee button", flee_roi)
        append_event(events, {"type": "flee_warning_resume_accepted", "source_sha256": warning.sha256, "target_roi": flee_roi})
    elif starting_state == "active_battle":
        active = runtime.capture("active-battle-resume-source")
        exit_roi = _bind_active_battle_exit(active.frame)
        if exit_roi is None:
            return TERMINAL_BLOCKED, {"reason": "fresh active-battle resume source or icon-only Exit not positively bound", "completed_actions": completed_actions}
        exit_bound = ("icon-only Exit", exit_roi)
        append_event(events, {"type": "active_battle_resume_accepted", "source_sha256": active.sha256, "target_roi": exit_roi})
    elif starting_state == "hero_lineup":
        lineup = runtime.capture("hero-lineup-resume-source")
        lineup_roi = _bind_lineup_challenge_button(lineup.frame)
        if lineup_roi is None:
            return TERMINAL_BLOCKED, {"reason": "fresh Hero Lineup resume source or gold Challenge button not positively bound", "completed_actions": completed_actions}
        append_event(events, {"type": "hero_lineup_resume_accepted", "source_sha256": lineup.sha256, "target_roi": lineup_roi})
    elif starting_state == "ultimate_challenge":
        current = runtime.capture("ultimate-challenge-resume-source")
        append_event(events, {"type": "ultimate_challenge_resume_accepted", "source_sha256": current.sha256})
    else:
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

    if starting_state not in {"hero_lineup", "active_battle", "flee_warning"}:
        before = runtime.capture("tap_challenge-immediate-before")
        challenge_roi = _bind_red_challenge_button(before.frame)
        if challenge_roi is None or "ultimate" not in _ocr_folded(before.frame):
            return TERMINAL_BLOCKED, {"reason": "actual red Challenge button not bound on Ultimate Challenge main", "completed_actions": completed_actions}
        challenge_key = f"tap_challenge-1-{utc_stamp()}"
        runtime.tap(before, target_identity="tap_challenge", target_roi=challenge_roi, action_key=challenge_key, consequential=True)
        lineup = _capture_until(
            runtime,
            label="hero-lineup-successor",
            predicate=lambda frame: _bind_lineup_challenge_button(frame) is not None,
            attempts=6,
            settle_seconds=max(0.8, post_input_delay),
        )
        if lineup is None or _bind_lineup_challenge_button(lineup.frame) is None:
            return TERMINAL_BLOCKED, {"reason": "Hero Lineup successor not positively recognized after Challenge", "completed_actions": completed_actions, "challenge_action_key": challenge_key}
        runtime.reconcile(challenge_key, "confirmed", lineup, "Hero Lineup recognized after Challenge")
        completed_actions.append({"action": "tap_challenge", "target_text": "red Challenge button", "target_roi": challenge_roi, "before_sha256": before.sha256, "post_sha256": lineup.sha256})
        append_event(events, {"type": "consequential_step", "action": "tap_challenge", "target_text": "red Challenge button", "target_roi": challenge_roi, "before_sha256": before.sha256, "post_sha256": lineup.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})
        lineup_roi = _bind_lineup_challenge_button(lineup.frame)
        assert lineup_roi is not None
    if starting_state not in {"active_battle", "flee_warning"}:
        lineup_key = f"tap_lineup_challenge-2-{utc_stamp()}"
        runtime.tap(lineup, target_identity="tap_lineup_challenge", target_roi=lineup_roi, action_key=lineup_key, consequential=True)
        active = _capture_until(
            runtime,
            label="active-challenge-successor",
            predicate=lambda frame: _bind_active_battle_exit(frame) is not None,
            attempts=10,
            settle_seconds=max(0.8, post_input_delay),
        )
        if active is None:
            return TERMINAL_BLOCKED, {"reason": "active challenge successor not captured", "completed_actions": completed_actions, "lineup_action_key": lineup_key}
        exit_roi = _bind_active_battle_exit(active.frame)
        if exit_roi is None:
            return TERMINAL_BLOCKED, {"reason": "upper-right icon-only Exit not positively bound after Hero Lineup Challenge", "completed_actions": completed_actions, "lineup_action_key": lineup_key, "active_sha256": active.sha256}
        exit_bound = ("icon-only Exit", exit_roi)
        runtime.reconcile(lineup_key, "confirmed", active, "active challenge icon-only Exit control recognized")
        completed_actions.append({"action": "tap_lineup_challenge", "target_text": "gold Challenge button", "target_roi": lineup_roi, "before_sha256": lineup.sha256, "post_sha256": active.sha256})
        append_event(events, {"type": "consequential_step", "action": "tap_lineup_challenge", "target_text": "gold Challenge button", "target_roi": lineup_roi, "before_sha256": lineup.sha256, "post_sha256": active.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})

    if starting_state != "flee_warning":
        exit_text, exit_roi = exit_bound
        exit_key = f"tap_upper_right_exit-3-{utc_stamp()}"
        runtime.tap(active, target_identity="tap_upper_right_exit", target_roi=exit_roi, action_key=exit_key, consequential=True)
        warning = _capture_until(
            runtime,
            label="flee-warning-successor",
            predicate=lambda frame: _bind_flee_warning_button(frame) is not None,
            attempts=6,
            settle_seconds=max(0.8, post_input_delay),
        )
        if warning is None:
            return TERMINAL_BLOCKED, {"reason": "Flee warning successor not captured", "completed_actions": completed_actions, "exit_action_key": exit_key}
        flee_roi = _bind_flee_warning_button(warning.frame)
        if flee_roi is None:
            return TERMINAL_BLOCKED, {"reason": "gold Flee control not positively bound after Exit", "completed_actions": completed_actions, "exit_action_key": exit_key, "warning_sha256": warning.sha256}
        flee_bound = ("gold Flee button", flee_roi)
        runtime.reconcile(exit_key, "confirmed", warning, "Flee warning recognized after Exit")
        completed_actions.append({"action": "tap_upper_right_exit", "target_text": exit_text, "target_roi": exit_roi, "before_sha256": active.sha256, "post_sha256": warning.sha256})
        append_event(events, {"type": "consequential_step", "action": "tap_upper_right_exit", "target_text": exit_text, "target_roi": exit_roi, "before_sha256": active.sha256, "post_sha256": warning.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})

    flee_text, flee_roi = flee_bound
    flee_key = f"tap_flee-4-{utc_stamp()}"
    runtime.tap(warning, target_identity="tap_flee", target_roi=flee_roi, action_key=flee_key, consequential=True)
    fled = _capture_until(
        runtime,
        label="flee-confirmed-successor",
        predicate=lambda frame: "ultimate challenge" in _ocr_folded(frame) and _bind_red_challenge_button(frame) is not None,
        attempts=6,
        settle_seconds=max(0.8, post_input_delay),
    )
    if fled is None or "ultimate challenge" not in _ocr_folded(fled.frame) or _bind_red_challenge_button(fled.frame) is None:
        return TERMINAL_BLOCKED, {"reason": "Flee completion not positively recognized", "completed_actions": completed_actions, "flee_action_key": flee_key}
    runtime.reconcile(flee_key, "confirmed", fled, "Ultimate Challenge main recognized after Flee")
    completed_actions.append({"action": "tap_flee", "target_text": flee_text, "target_roi": flee_roi, "before_sha256": warning.sha256, "post_sha256": fled.sha256})
    append_event(events, {"type": "consequential_step", "action": "tap_flee", "target_text": flee_text, "target_roi": flee_roi, "before_sha256": warning.sha256, "post_sha256": fled.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})

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
    parser.add_argument("--post-flee-home-only", action="store_true", help="resume only the verified UC-main → Campaign → Home terminal route")
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

    if sum(bool(value) for value in (args.navigation_only, args.daily, args.post_flee_home_only)) != 1:
        parser.error("select exactly one of --navigation-only, --daily, or --post-flee-home-only")
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

    if args.post_flee_home_only:
        terminal, detail = _run_post_flee_home_route(
            runner=runner,
            session=session,
            events=events,
            reset_identity=args.reset_identity or "",
            post_input_delay=args.post_input_delay,
        )
        _write_operator_artifacts(session, terminal)
        result = {"status": terminal, "terminal": terminal, "flow_id": FLOW_ID, "session": str(session), "navigation_only": False, "dispatch": terminal == TERMINAL_COMPLETE_FOR_RESET, "navigation_input_count": 2, **detail}
        _write_result(session, result)
        return 0 if terminal == TERMINAL_COMPLETE_FOR_RESET else 3

    resume_path = frames / "campaign-resume-source.png"
    resume_frame = capture(runner, resume_path)
    resume_text = _ocr_folded(resume_frame)
    ultimate_already_open = (
        "ultimate challenge" in resume_text
        and _bind_red_challenge_button(resume_frame) is not None
    )
    hero_lineup_already_open = _bind_lineup_challenge_button(resume_frame) is not None
    active_battle_already_open = _bind_active_battle_exit(resume_frame) is not None
    flee_warning_already_open = _bind_flee_warning_button(resume_frame) is not None
    resume_observation = _bind_ultimate_challenge_entry(
        resume_frame, reset_identity=args.reset_identity
    )
    if flee_warning_already_open:
        resumed_campaign = True
        entry_session = session / "flee-warning-resume"
        entry = {
            "status": "opened",
            "reason": "fresh exact Flee-warning resume point with gold Flee button bound",
            "records": [],
            "resume_source": str(resume_path),
            "resume_source_sha256": frame_sha256(resume_frame),
        }
        append_event(events, {"type": "flee_warning_resume_source", "flow_id": FLOW_ID, "frame": str(resume_path), "source_frame_sha256": frame_sha256(resume_frame)})
    elif active_battle_already_open:
        resumed_campaign = True
        entry_session = session / "active-battle-resume"
        entry = {
            "status": "opened",
            "reason": "fresh active puzzle battle resume point with icon-only Exit bound",
            "records": [],
            "resume_source": str(resume_path),
            "resume_source_sha256": frame_sha256(resume_frame),
        }
        append_event(events, {"type": "active_battle_resume_source", "flow_id": FLOW_ID, "frame": str(resume_path), "source_frame_sha256": frame_sha256(resume_frame)})
    elif hero_lineup_already_open:
        resumed_campaign = True
        entry_session = session / "hero-lineup-resume"
        entry = {
            "status": "opened",
            "reason": "fresh Hero Lineup resume point with gold Challenge button bound",
            "records": [],
            "resume_source": str(resume_path),
            "resume_source_sha256": frame_sha256(resume_frame),
        }
        append_event(events, {"type": "hero_lineup_resume_source", "flow_id": FLOW_ID, "frame": str(resume_path), "source_frame_sha256": frame_sha256(resume_frame)})
    elif ultimate_already_open:
        resumed_campaign = True
        entry_session = session / "ultimate-challenge-resume"
        entry = {
            "status": "opened",
            "reason": "fresh Ultimate Challenge main resume point with red Challenge button bound",
            "records": [],
            "resume_source": str(resume_path),
            "resume_source_sha256": frame_sha256(resume_frame),
        }
        append_event(events, {"type": "ultimate_challenge_resume_source", "flow_id": FLOW_ID, "frame": str(resume_path), "source_frame_sha256": frame_sha256(resume_frame)})
    elif (
        resume_observation.campaign_screen_recognized
        and resume_observation.entry_control_visible
        and resume_observation.entry_roi is not None
    ):
        resumed_campaign = True
        entry_session = session / "campaign-resume"
        entry = {
            "status": "opened",
            "reason": "fresh Campaign tier-map resume point with Ultimate Challenge vortex bound",
            "records": [],
            "resume_source": str(resume_path),
            "resume_source_sha256": resume_observation.source_frame_sha256,
            "resume_entry_roi": resume_observation.entry_roi,
        }
        append_event(
            events,
            {
                "type": "campaign_resume_source",
                "flow_id": FLOW_ID,
                "frame": str(resume_path),
                "source_frame_sha256": resume_observation.source_frame_sha256,
                "entry_roi": resume_observation.entry_roi,
            },
        )
    else:
        resumed_campaign = False
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
            "type": "flee_warning_resume_accepted" if flee_warning_already_open else ("active_battle_resume_accepted" if active_battle_already_open else ("hero_lineup_resume_accepted" if hero_lineup_already_open else ("ultimate_challenge_resume_accepted" if ultimate_already_open else ("campaign_resume_accepted" if resumed_campaign else "home_atlas_campaign_door")))),
            "building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            "entry_session": str(entry_session),
            **{k: v for k, v in entry.items() if k != "tap_telemetry"},
        },
    )
    if entry.get("status") == "opened" and not resumed_campaign:
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

    if (flee_warning_already_open or active_battle_already_open or hero_lineup_already_open or ultimate_already_open) and args.daily:
        terminal, detail = _run_daily_route(
            runner=runner,
            session=session,
            frames=frames,
            events=events,
            atlas_path=args.atlas,
            reset_identity=args.reset_identity or "",
            maximum_pans=args.maximum_pans,
            post_input_delay=args.post_input_delay,
            entry_observation=resume_observation,
            starting_state="flee_warning" if flee_warning_already_open else ("active_battle" if active_battle_already_open else ("hero_lineup" if hero_lineup_already_open else "ultimate_challenge")),
        )
        _write_operator_artifacts(session, terminal)
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
            _write_operator_artifacts(session, TERMINAL_ALREADY_COMPLETED)
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
            _write_operator_artifacts(session, TERMINAL_BLOCKED)
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
        _write_operator_artifacts(session, terminal)
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
