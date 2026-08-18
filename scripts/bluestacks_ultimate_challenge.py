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
import os
from pathlib import Path
import re
import shutil
import sys
import time

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bluestacks_flow_collector import (
    ADBRunner,
    EXPECTED_PACKAGE,
    is_permitted_local_bluestacks_serial,
)
from bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
    NATIVE_WIDTH,
    NATIVE_RUNTIME_PROFILE_ID,
)
from home_atlas_bluestacks import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID,
    BlueStacksHomeLocalizer,
    BlueStacksLocalizeFirstHomeDriver,
    HomeDriverDisposition,
    ScrcpyMotionEventZoomTransport,
    load_home_atlas,
    require_campaign_home_atlas_building,
    run_verified_ultimate_challenge_campaign_door,
)
from navigation_development_boundary import (
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from scripts.bluestacks_popup_recognition import recognize_reset_popup
from scripts.flow_delivery_evidence import require_operator_evidence
from world_map_navigation_bluestacks import _visual_popup_panel_candidates
from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks.home_atlas import ZoomIdentity
from tasks.home_context import HomeReadyObservation
from tasks.home_atlas_vision import classify_zoom
from tasks.home_nav_recognition import recognize_home_nav
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
from tasks.ultimate_challenge_daily import (
    FLOW_ID,
    TERMINAL_ALREADY_COMPLETED,
    TERMINAL_BLOCKED,
    TERMINAL_COMPLETE_FOR_RESET,
    TERMINAL_NAVIGATION_ONLY_COMPLETE,
    ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
    UltimateChallengeEntryObservation,
    empty_reset_window_state,
    evaluate_already_completed,
    evaluate_navigation_only,
    load_reset_window_state,
    ultimate_challenge_already_completed_from_ocr_hits,
)

MAX_TOTAL_INPUTS = 16
MAX_HOME_ZOOM_INPUTS = 4
_ULTIMATE_HOME_ZOOM_SOURCE_STATE = "ULTIMATE_HOME_TEMPLATE"
_ULTIMATE_HOME_ZOOM_TARGET_IDENTITY = "home-zoom-out"

_UC_PORTAL_SEARCH_ROI = (400, 700, 700, 970)
_UC_ENTRY_SEMANTIC_ROI = (400, 850, 700, 1030)
_UC_TITLE_ROI = (120, 0, 680, 90)
_HERO_LINEUP_SELECTED_CARD_ROIS = (
    (29, 621, 168, 808),
    (180, 620, 323, 810),
    (332, 620, 475, 810),
    (485, 620, 628, 810),
    (639, 621, 778, 808),
)
_HERO_LINEUP_CARD_GRID_BOXES = frozenset(
    {
        (84, 373, 750, 1050),
        (84, 373, 729, 1050),
        (84, 373, 715, 1050),
        (85, 435, 750, 1050),
        (101, 435, 750, 1050),
        (85, 435, 729, 1050),
        (106, 435, 750, 1050),
        (85, 435, 715, 1050),
        (101, 435, 729, 1050),
        (106, 435, 729, 1050),
        (101, 435, 715, 1050),
        (106, 435, 715, 1050),
        (84, 373, 750, 891),
        (84, 373, 748, 891),
        (85, 435, 750, 891),
        (85, 435, 748, 891),
        (101, 435, 750, 891),
        (101, 435, 748, 891),
        (106, 435, 750, 891),
        (106, 435, 748, 891),
    }
)
_HERO_LINEUP_SELECTED_COLOR_MINIMUM = 400
_FLEE_MODAL_ROI = (65, 365, 735, 745)
_FLEE_MODAL_TEXT_ROI = (120, 450, 680, 590)
_FLEE_FIGHT_SEARCH_ROI = (80, 590, 390, 740)
_FLEE_FLEE_SEARCH_ROI = (390, 590, 720, 740)
# Keep contour boxes touching the native horizontal edge margins classified as scenery.
_CENTRAL_POPUP_HORIZONTAL_MARGIN = int(NATIVE_WIDTH * 0.05)

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


def _ocr_region_hits(
    frame: np.ndarray,
    region: tuple[int, int, int, int],
) -> dict[str, tuple[int, int, int, int]]:
    """OCR boxes inside one state-specific semantic ROI."""

    x0, y0, x1, y1 = region
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


def _ocr_ordered_tokens(
    frame: np.ndarray,
    region: tuple[int, int, int, int],
    expected: tuple[str, ...],
) -> bool:
    """Require high-confidence OCR tokens in their native reading order."""

    if frame is None or frame.shape[:2] != (1280, 800):
        return False
    x0, y0, x1, y1 = region
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    enlarged = cv2.resize(
        crop,
        None,
        fx=3,
        fy=3,
        interpolation=cv2.INTER_CUBIC,
    )
    try:
        data = pytesseract.image_to_data(
            enlarged,
            config="--psm 7",
            output_type=Output.DICT,
        )
        texts = data["text"]
        confidences = data["conf"]
        if not expected or len(texts) != len(confidences):
            return False
    except Exception:
        return False

    recognized_tokens: list[str] = []
    for raw_text, raw_confidence in zip(texts, confidences):
        token = re.sub(r"[^a-z]", "", str(raw_text).casefold())
        if not token:
            continue
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence >= 80.0 and token in expected:
            recognized_tokens.append(token)
    return tuple(recognized_tokens) == expected


def _visual_popup_candidates(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Reuse the checked-in visual panel primitive without broad OCR."""

    return _visual_popup_panel_candidates(frame)


def _roi_area(roi: tuple[int, int, int, int]) -> int:
    return max(0, roi[2] - roi[0]) * max(0, roi[3] - roi[1])


def _roi_intersection_area(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> int:
    return max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0, min(left[3], right[3]) - max(left[1], right[1])
    )


def _flee_modal_popup_iou(
    popup: tuple[int, int, int, int],
) -> float:
    intersection = _roi_intersection_area(popup, _FLEE_MODAL_ROI)
    union = _roi_area(popup) + _roi_area(_FLEE_MODAL_ROI) - intersection
    return intersection / union if intersection > 0 and union > 0 else 0.0


def _flee_popup_is_materially_overbroad(
    popup: tuple[int, int, int, int],
) -> bool:
    """Keep a frame-anchored candidate too large for the bounded modal separate."""

    # The shared Hough primitive emits many nested interior rectangles from
    # one modal.  Preserve those for duplicate collapse, but keep a genuinely
    # broad panel that is anchored to the native frame independently visible.
    x0, y0, x1, y1 = popup
    modal_area = _roi_area(_FLEE_MODAL_ROI)
    materially_large = _roi_area(popup) >= modal_area * 2.0
    frame_anchored = x0 <= 10 or y0 <= 10 or x1 >= 790 or y1 >= 1270
    return materially_large and frame_anchored


def _flee_popup_panel_candidates(
    frame: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Collapse modal duplicates while preserving independent panel evidence."""

    raw = _visual_popup_candidates(frame)
    clusters: list[list[tuple[int, int, int, int]]] = []
    for candidate in raw:
        area = _roi_area(candidate)
        joined = False
        for cluster in clusters:
            for existing in cluster:
                if (
                    _flee_popup_is_materially_overbroad(candidate)
                    or _flee_popup_is_materially_overbroad(existing)
                ):
                    continue
                overlap = _roi_intersection_area(candidate, existing)
                if overlap and (
                    overlap / max(1, min(area, _roi_area(existing))) >= 0.60
                    or overlap / max(1, area + _roi_area(existing) - overlap) >= 0.35
                ):
                    cluster.append(candidate)
                    joined = True
                    break
            if joined:
                break
        if not joined:
            clusters.append([candidate])
    return [
        max(cluster, key=_flee_modal_popup_iou)
        for cluster in clusters
    ]


def _central_popup_candidates(
    frame: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Keep only bounded, central popup geometry from the shared detector."""

    candidates = []
    for x0, y0, x1, y1 in _visual_popup_candidates(frame):
        if (
            x0 > _CENTRAL_POPUP_HORIZONTAL_MARGIN
            and x1 < NATIVE_WIDTH - _CENTRAL_POPUP_HORIZONTAL_MARGIN
            and 350 <= y0 <= 800
            and 450 <= y1 <= 1100
            and 400 <= x1 - x0 <= 780
            and 220 <= y1 - y0 <= 700
        ):
            candidates.append((x0, y0, x1, y1))
    return candidates


def _unexpected_visual_popup(frame: np.ndarray) -> bool:
    """Reject bounded unexpected panels, including resource/purchase prompts."""

    panels = _central_popup_candidates(frame)
    if not panels:
        return False
    # An unexpected panel is denied by geometry alone.  Resource/purchase/refill
    # semantics, when present, are corroboration rather than authorization.
    return True


def _home_nav_terminal(frame: np.ndarray) -> bool:
    """Recognize template Home only when no unexpected popup is visible."""

    return not _unexpected_visual_popup(frame) and recognize_home_nav(frame).is_home


def _ultimate_home_zoom_route_declaration() -> NavigationRouteDeclaration:
    """Declare only the supervised, navigation-only Ultimate Home zoom route."""

    return NavigationRouteDeclaration(
        allowed_source_states=frozenset({_ULTIMATE_HOME_ZOOM_SOURCE_STATE}),
        allowed_target_identities=frozenset({_ULTIMATE_HOME_ZOOM_TARGET_IDENTITY}),
        allowed_gesture_classes=frozenset({"zoom_out"}),
        consequence_class="navigation_only",
    )


def _ultimate_home_ready_observation(
    runtime: LocalBlueStacksRuntime,
    source: CapturedNativeFrame,
) -> HomeReadyObservation:
    """Build the supervised-local Home precondition without production identity claims."""

    foreground = runtime.measure_foreground_package()
    device_state = runtime.measure_device_state()
    native = source.frame.shape == (1280, 800, 3)
    identity = VerifiedRuntimeIdentity(
        runtime_scope="ultimate-challenge-supervised-local",
        account_id="supervised-local-account",
        server_id="supervised-local-server",
        reset_id=None,
        assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        evidence_refs=(
            "operator:supervised-local",
            f"source-frame:{source.sha256}",
        ),
    )
    return HomeReadyObservation(
        game_foregrounded=foreground == EXPECTED_PACKAGE and device_state == "device",
        expected_native_profile=native,
        identity=identity,
        manual_only_state=False,
        blocking_unknown_modal=False,
    )


def _ultimate_home_zoom_safety_facts(
    runtime: LocalBlueStacksRuntime,
    source: CapturedNativeFrame,
) -> object:
    """Describe the exact current Home source consumed by the navigation firewall."""

    return make_source_safety_facts(
        recognized=True,
        source_state=_ULTIMATE_HOME_ZOOM_SOURCE_STATE,
        overlay_state="none_observed",
        manual_required=False,
        hard_stop=False,
        unknown_state=False,
        frame_width=int(source.frame.shape[1]),
        frame_height=int(source.frame.shape[0]),
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        foreground_package=str(runtime.measure_foreground_package()),
        device_state=str(runtime.measure_device_state()),
        frame_sha256=source.sha256,
        captured_monotonic=source.captured_monotonic,
        now_monotonic=time.monotonic(),
    )


def _ultimate_home_zoom_step_detail(
    ordinal: int,
    step,
    *,
    source: CapturedNativeFrame | None = None,
) -> dict[str, object]:
    localization = getattr(step, "localization", None)
    return {
        "ordinal": ordinal,
        "disposition": getattr(getattr(step, "disposition", None), "value", str(getattr(step, "disposition", ""))),
        "reason": str(getattr(step, "reason", "")),
        "source_frame_sha256": str(getattr(step, "source_frame_sha256", "")),
        "runtime_source_sha256": source.sha256 if source is not None else None,
        "zoom_identity": getattr(
            getattr(localization, "zoom_identity", None),
            "value",
            str(getattr(localization, "zoom_identity", "")),
        ),
        "localization_recognized": bool(getattr(localization, "recognized", False)),
        "localization_confidence": getattr(localization, "confidence", None),
        "localization_residual_px": getattr(localization, "residual_px", None),
        "overlay": bool(getattr(localization, "overlay", False)),
        "ambiguity_state": getattr(
            getattr(localization, "ambiguity_state", None),
            "value",
            str(getattr(localization, "ambiguity_state", "")),
        ),
    }


def _ultimate_home_zoom_is_fully_out(step) -> bool:
    localization = getattr(step, "localization", None)
    return bool(
        getattr(localization, "recognized", False)
        and getattr(localization, "screen_to_atlas", None) is not None
        and getattr(localization, "zoom_identity", None) is ZoomIdentity.FULLY_ZOOMED_OUT
        and not getattr(localization, "overlay", False)
        and not getattr(localization, "stale", False)
        and getattr(
            getattr(localization, "ambiguity_state", None),
            "value",
            "",
        )
        == "none"
    )


def _ultimate_home_zoom_progressed(
    before: CapturedNativeFrame,
    settled: CapturedNativeFrame,
    *,
    canonical_reference: np.ndarray,
) -> tuple[bool, str]:
    """Require measurable zoom progress when the driver still requests recovery."""

    before_digest = frame_sha256(before.frame)
    settled_digest = frame_sha256(settled.frame)
    if before_digest == settled_digest:
        return False, "no_progress_repeated_settled_frame"
    before_zoom = classify_zoom(before.frame, canonical_reference)
    settled_zoom = classify_zoom(settled.frame, canonical_reference)
    if before_zoom.scale is None or settled_zoom.scale is None:
        return False, "unknown_zoom_progress_geometry"
    if settled_zoom.scale <= before_zoom.scale + 0.005:
        return False, "no_progress_zoom_scale"
    return True, "measurable_zoom_progress"


def _runtime_input_count(runtime: object) -> int | None:
    value = getattr(runtime, "input_count", None)
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _runtime_action_keys(runtime: object) -> frozenset[str] | None:
    value = getattr(runtime, "action_keys", None)
    if value is None:
        return None
    try:
        return frozenset(str(key) for key in value)
    except TypeError:
        return None


def _valid_native_roi(value: object) -> bool:
    if not isinstance(value, tuple) or len(value) != 4:
        return False
    if not all(isinstance(coordinate, int) for coordinate in value):
        return False
    x0, y0, x1, y1 = value
    return 0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= 1280


def _exact_vip_reset_popup(observation: object) -> bool:
    return bool(
        isinstance(observation, dict)
        and observation.get("recognized") is True
        and observation.get("popup_identity") == "VIP_POINTS_GET_PTS"
        and observation.get("target_identity") == "reset-popup-close"
        and _valid_native_roi(observation.get("target"))
    )


def _runtime_tap_dispatch_was_accounted(
    runtime: object,
    *,
    action_key: str,
    input_count_before: int | None,
    action_keys_before: frozenset[str] | None,
) -> bool:
    """Prove that the exact popup-close tap occupied one runtime slot."""

    input_count_after = _runtime_input_count(runtime)
    if (
        input_count_before is None
        or input_count_after is None
        or input_count_after - input_count_before != 1
    ):
        return False
    action_keys_after = _runtime_action_keys(runtime)
    if action_keys_after is not None:
        return (
            action_key in action_keys_after
            and action_key not in (action_keys_before or frozenset())
        )
    return True


def _zoom_runtime_dispatch_was_accounted(
    runtime: object,
    *,
    action_key: str,
    input_count_before: int | None,
    action_keys_before: frozenset[str] | None,
    dispatched_key_before: object,
) -> bool:
    """Prove one exact runtime-accounted slot before reconciling it."""

    input_count_after = _runtime_input_count(runtime)
    if (
        input_count_before is None
        or input_count_after is None
        or input_count_after - input_count_before != 1
    ):
        return False
    action_keys_after = _runtime_action_keys(runtime)
    if action_keys_after is not None:
        return (
            action_key in action_keys_after
            and action_key not in (action_keys_before or frozenset())
        )
    dispatched_key_after = getattr(runtime, "dispatched_external_zoom_key", None)
    return (
        dispatched_key_after == action_key
        and dispatched_key_after != dispatched_key_before
    )


def _normalize_ultimate_home_before_campaign(
    *,
    runtime: LocalBlueStacksRuntime,
    session: Path,
    events: Path,
    atlas_path: Path,
    adb: Path,
    serial: str,
    source: CapturedNativeFrame,
    maximum_pans: int,
    post_input_delay: float,
) -> tuple[bool, dict[str, object]]:
    """Normalize a fresh template Home in-session before Campaign Atlas binding."""

    records: list[dict[str, object]] = []
    detail: dict[str, object] = {
        "status": "blocked_fail_closed",
        "zoom_input_count": 0,
        "max_zoom_inputs": MAX_HOME_ZOOM_INPUTS,
        "records": records,
        "zoom_records": records,
    }
    home_nav = recognize_home_nav(source.frame)
    if not home_nav.is_home or _unexpected_visual_popup(source.frame):
        detail["reason"] = "fresh template Home was not positively recognized"
        return False, detail

    try:
        ready = _ultimate_home_ready_observation(runtime, source)
        atlas = load_home_atlas(atlas_path)
        localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
        driver = BlueStacksLocalizeFirstHomeDriver(
            atlas,
            atlas_path,
            ready,
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            localizer=localizer,
            maximum_pans=maximum_pans,
            maximum_zoom_inputs=MAX_HOME_ZOOM_INPUTS,
        )
        guarded = NavigationGuardedRuntime(
            runtime,
            _ultimate_home_zoom_route_declaration(),
        )
    except Exception as exc:
        detail["reason"] = f"Home normalization precondition failed: {type(exc).__name__}: {exc}"
        return False, detail

    current = source
    transport = None
    try:
        step = driver.observe(current.frame)
    except Exception as exc:
        detail["reason"] = f"Home normalization observation failed: {type(exc).__name__}: {exc}"
        return False, detail
    for ordinal in range(1, MAX_HOME_ZOOM_INPUTS + 1):
        plan_detail = _ultimate_home_zoom_step_detail(ordinal, step, source=current)
        if _ultimate_home_zoom_is_fully_out(step) and getattr(
            step, "disposition", None
        ) is not HomeDriverDisposition.BLOCKED:
            detail.update(
                {
                    "status": "completed",
                    "reason": "fresh Home already fully localized for Campaign Atlas",
                    "zoom_input_count": driver.zoom_inputs,
                    "terminal_source_sha256": current.sha256,
                    "terminal_semantic_frame_sha256": frame_sha256(current.frame),
                    "terminal_zoom_identity": ZoomIdentity.FULLY_ZOOMED_OUT.value,
                }
            )
            append_event(
                events,
                {
                    "type": "ultimate_home_normalization_complete",
                    "flow_id": FLOW_ID,
                    **detail,
                },
            )
            return True, detail
        if getattr(step, "disposition", None) is HomeDriverDisposition.BLOCKED:
            detail["reason"] = str(getattr(step, "reason", "Home normalization blocked"))
            records.append(plan_detail)
            append_event(
                events,
                {
                    "type": "ultimate_home_normalization_blocked",
                    "flow_id": FLOW_ID,
                    **detail,
                },
            )
            return False, detail
        if getattr(step, "disposition", None) is not HomeDriverDisposition.RECOVER_ZOOM:
            detail["reason"] = (
                "Home normalization produced an unsupported non-zoom disposition: "
                f"{getattr(step, 'reason', 'unknown')}"
            )
            records.append(plan_detail)
            return False, detail

        planned_source = str(getattr(step, "source_frame_sha256", ""))
        planned_disposition = getattr(step, "disposition", None)
        immediate_before = runtime.capture(
            f"ultimate-home-zoom-{ordinal:02d}-immediate-before"
        )
        immediate_semantic = frame_sha256(immediate_before.frame)
        plan_detail.update(
            {
                "action_key": f"home-zoom-out:{immediate_before.sha256}",
                "immediate_before_sha256": immediate_before.sha256,
                "immediate_before_semantic_frame_sha256": immediate_semantic,
                "planned_source_frame_sha256": planned_source,
                "planned_disposition": getattr(
                    planned_disposition, "value", str(planned_disposition)
                ),
            }
        )
        if not _home_nav_terminal(immediate_before.frame):
            plan_detail["status"] = "blocked"
            plan_detail["failure"] = "immediate_before_home_revalidation_failed"
            records.append(plan_detail)
            detail["reason"] = "Home zoom immediate-before revalidation failed"
            return False, detail
        # The first observation is only a provisional plan.  Re-observing an
        # unchanged frame must replace that plan rather than trip the driver's
        # post-dispatch repeated-frame guard before any input was sent.
        if immediate_semantic == planned_source:
            seen_recovery_frames = getattr(driver, "_seen_recovery_frames", None)
            if isinstance(seen_recovery_frames, set):
                seen_recovery_frames.discard(immediate_semantic)
        try:
            step = driver.observe(immediate_before.frame)
        except Exception as exc:
            plan_detail["status"] = "blocked"
            plan_detail["failure"] = (
                f"immediate_before_reobservation_failed:{type(exc).__name__}:{exc}"
            )
            records.append(plan_detail)
            detail["reason"] = "Home zoom immediate-before re-observation failed"
            return False, detail
        refreshed_source = str(getattr(step, "source_frame_sha256", ""))
        plan_detail.update(
            _ultimate_home_zoom_step_detail(
                ordinal,
                step,
                source=immediate_before,
            )
        )
        plan_detail.update(
            {
                "planned_source_frame_sha256": planned_source,
                "planned_disposition": getattr(
                    planned_disposition, "value", str(planned_disposition)
                ),
                "refreshed_source_frame_sha256": refreshed_source,
            }
        )
        if getattr(step, "disposition", None) is not HomeDriverDisposition.RECOVER_ZOOM:
            plan_detail["status"] = "blocked"
            plan_detail["failure"] = "immediate_before_disposition_changed"
            records.append(plan_detail)
            detail["reason"] = (
                "Home zoom immediate-before disposition changed: "
                f"{getattr(getattr(step, 'disposition', None), 'value', 'unknown')}"
            )
            return False, detail
        if refreshed_source != immediate_semantic:
            plan_detail["status"] = "blocked"
            plan_detail["failure"] = "immediate_before_source_digest_mismatch"
            records.append(plan_detail)
            detail["reason"] = (
                "Home zoom immediate-before source digest did not match "
                "the refreshed driver source"
            )
            return False, detail
        try:
            immediate_localization = localizer.localize(immediate_before.frame)
            if (
                immediate_localization.frame_sha256 != immediate_semantic
                or immediate_localization.overlay
                or immediate_localization.stale
            ):
                raise RuntimeError("immediate-before localization was stale or mismatched")
            facts = _ultimate_home_zoom_safety_facts(runtime, immediate_before)
        except Exception as exc:
            plan_detail["status"] = "blocked"
            plan_detail["failure"] = f"source_safety_facts_failed:{type(exc).__name__}:{exc}"
            records.append(plan_detail)
            detail["reason"] = "Home zoom source safety facts were not established"
            return False, detail

        action_key = str(plan_detail["action_key"])
        input_count_before = _runtime_input_count(runtime)
        action_keys_before = _runtime_action_keys(runtime)
        dispatched_key_before = getattr(
            runtime, "dispatched_external_zoom_key", None
        )
        if transport is None:
            try:
                transport = ScrcpyMotionEventZoomTransport(
                    adb=adb,
                    serial=serial,
                    evidence_directory=session / "home-normalization",
                )
            except Exception as exc:
                plan_detail["status"] = "blocked"
                plan_detail["failure"] = f"zoom_transport_unavailable:{type(exc).__name__}:{exc}"
                records.append(plan_detail)
                detail["reason"] = "Home zoom transport was unavailable"
                return False, detail

        transport_error: BaseException | None = None
        try:
            guarded.dispatch_zoom_out(
                immediate_before,
                facts,
                transport=transport.zoom_out_once,
                target_identity=_ULTIMATE_HOME_ZOOM_TARGET_IDENTITY,
            )
        except BaseException as exc:
            transport_error = exc

        immediate_post = runtime.capture(
            f"ultimate-home-zoom-{ordinal:02d}-immediate-post"
        )
        if post_input_delay > 0:
            time.sleep(post_input_delay)
        settled = runtime.capture(f"ultimate-home-zoom-{ordinal:02d}-settled")
        plan_detail.update(
            {
                "immediate_post_sha256": immediate_post.sha256,
                "settled_sha256": settled.sha256,
                "runtime_input_count_before": input_count_before,
                "runtime_input_count_after": _runtime_input_count(runtime),
            }
        )
        runtime_accounted = _zoom_runtime_dispatch_was_accounted(
            runtime,
            action_key=action_key,
            input_count_before=input_count_before,
            action_keys_before=action_keys_before,
            dispatched_key_before=dispatched_key_before,
        )
        plan_detail["runtime_accounted"] = runtime_accounted

        if transport_error is not None:
            plan_detail["status"] = "transport_failed"
            plan_detail["failure"] = (
                f"{type(transport_error).__name__}:{transport_error}"
            )
            plan_detail["home_successor_recognized"] = bool(
                _home_nav_terminal(immediate_post.frame)
                and _home_nav_terminal(settled.frame)
            )
            if runtime_accounted:
                runtime.reconcile(
                    action_key,
                    "unresolved",
                    settled,
                    "Home zoom transport failed after runtime accounting; outcome remains unresolved",
                )
            else:
                plan_detail["status"] = "blocked"
                plan_detail["failure"] = (
                    "zoom transport failed before runtime accounting: "
                    f"{type(transport_error).__name__}:{transport_error}"
                )
                records.append(plan_detail)
                detail["reason"] = (
                    "Home zoom transport was denied before runtime accounting; "
                    "route blocked fail-closed"
                )
                detail["zoom_input_count"] = _runtime_input_count(runtime) or 0
                return False, detail
            records.append(plan_detail)
            try:
                failed_step = driver.observe(settled.frame)
                failed_reobservation = _ultimate_home_zoom_step_detail(
                    ordinal,
                    failed_step,
                    source=settled,
                )
                failed_reobservation["phase"] = "driver_reobservation_after_transport_failure"
                records.append(failed_reobservation)
            except Exception as exc:
                plan_detail["reobservation_error"] = f"{type(exc).__name__}:{exc}"
            detail["reason"] = "Home zoom transport failed; route blocked fail-closed"
            detail["zoom_input_count"] = getattr(runtime, "input_count", 0)
            return False, detail

        try:
            driver.record_zoom_input_dispatched(immediate_semantic)
        except Exception as exc:
            plan_detail["status"] = "unresolved" if runtime_accounted else "blocked"
            plan_detail["failure"] = f"zoom_accounting_failed:{type(exc).__name__}:{exc}"
            if runtime_accounted:
                runtime.reconcile(
                    action_key,
                    "unresolved",
                    settled,
                    "Home zoom driver accounting failed after runtime-accounted transport",
                )
            records.append(plan_detail)
            detail["reason"] = (
                "Home zoom driver accounting rejected the dispatched source"
                if runtime_accounted
                else "Home zoom transport succeeded without runtime accounting"
            )
            detail["zoom_input_count"] = _runtime_input_count(runtime) or 0
            return False, detail

        immediate_post_home_recognized = _home_nav_terminal(immediate_post.frame)
        settled_home_recognized = _home_nav_terminal(settled.frame)
        home_successor_recognized = bool(
            immediate_post_home_recognized and settled_home_recognized
        )
        plan_detail["immediate_post_home_recognized"] = immediate_post_home_recognized
        plan_detail["settled_home_recognized"] = settled_home_recognized
        plan_detail["home_successor_recognized"] = home_successor_recognized
        try:
            step = driver.observe(settled.frame)
        except Exception as exc:
            plan_detail["status"] = "unresolved"
            plan_detail["failure"] = (
                f"home_reobservation_failed:{type(exc).__name__}:{exc}"
            )
            runtime.reconcile(
                action_key,
                "unresolved",
                settled,
                "Home zoom outcome remained unknown after driver re-observation failure",
            )
            records.append(plan_detail)
            detail["reason"] = (
                f"Home re-observation failed: {type(exc).__name__}: {exc}"
            )
            detail["zoom_input_count"] = driver.zoom_inputs
            return False, detail
        reobserved = _ultimate_home_zoom_step_detail(
            ordinal,
            step,
            source=settled,
        )
        reobserved["phase"] = "driver_reobservation"

        def finalize_reconciliation(status: str, reason: str) -> bool:
            runtime.reconcile(action_key, status, settled, reason)
            plan_detail["status"] = status
            records.extend((plan_detail, reobserved))
            return True

        settled_terminal_dispositions = {
            HomeDriverDisposition.PAN,
            HomeDriverDisposition.BIND,
            HomeDriverDisposition.COMPLETE,
        }
        if (
            settled_home_recognized
            and _ultimate_home_zoom_is_fully_out(step)
            and getattr(step, "disposition", None) in settled_terminal_dispositions
        ):
            if not finalize_reconciliation(
                "confirmed",
                "template Home successor and canonical zoom outcome recognized after guarded zoom",
            ):
                return False, detail
            detail.update(
                {
                    "status": "completed",
                    "reason": "Home fully localized after guarded zoom recovery",
                    "zoom_input_count": driver.zoom_inputs,
                    "terminal_source_sha256": settled.sha256,
                    "terminal_semantic_frame_sha256": frame_sha256(settled.frame),
                    "terminal_zoom_identity": ZoomIdentity.FULLY_ZOOMED_OUT.value,
                }
            )
            append_event(
                events,
                {
                    "type": "ultimate_home_normalization_complete",
                    "flow_id": FLOW_ID,
                    **detail,
                },
            )
            return True, detail
        if getattr(step, "disposition", None) is HomeDriverDisposition.BLOCKED:
            step_reason = str(getattr(step, "reason", "Home normalization blocked"))
            no_progress_confirmed = (
                home_successor_recognized
                and step_reason == "repeated_zoom_recovery_frame"
            )
            reconciliation_status = (
                "failed_confirmed" if no_progress_confirmed else "unresolved"
            )
            if not finalize_reconciliation(reconciliation_status, step_reason):
                return False, detail
            detail["reason"] = step_reason
            detail["zoom_input_count"] = driver.zoom_inputs
            return False, detail
        if getattr(step, "disposition", None) is not HomeDriverDisposition.RECOVER_ZOOM:
            unsupported_reason = (
                "Home re-observation produced an unsupported disposition: "
                f"{getattr(step, 'reason', 'unknown')}"
            )
            if not finalize_reconciliation("unresolved", unsupported_reason):
                return False, detail
            detail["reason"] = unsupported_reason
            detail["zoom_input_count"] = driver.zoom_inputs
            return False, detail
        progressed, progress_reason = _ultimate_home_zoom_progressed(
            immediate_before,
            settled,
            canonical_reference=localizer.canonical_reference,
        )
        plan_detail["progress_reason"] = progress_reason
        if progressed and home_successor_recognized:
            if not finalize_reconciliation(
                "confirmed",
                "template Home successor recognized after measurable guarded zoom progress",
            ):
                return False, detail
            current = settled
            continue
        no_progress_confirmed = (
            home_successor_recognized
            and not progressed
            and progress_reason
            in {"no_progress_repeated_settled_frame", "no_progress_zoom_scale"}
        )
        reconciliation_status = (
            "failed_confirmed" if no_progress_confirmed else "unresolved"
        )
        if not finalize_reconciliation(reconciliation_status, progress_reason):
            return False, detail
        if not progressed:
            detail["reason"] = progress_reason
        else:
            detail["reason"] = "Home successor recognition remained unknown after zoom"
        detail["zoom_input_count"] = driver.zoom_inputs
        return False, detail

    detail["reason"] = "maximum_zoom_recovery_inputs"
    detail["zoom_input_count"] = getattr(driver, "zoom_inputs", 0)
    return False, detail


def _campaign_context_recognized(frame: np.ndarray) -> bool:
    """Recognize only a Campaign context; never infer it from generic OCR."""

    if _unexpected_visual_popup(frame):
        return False
    recognition = _classify_campaign_ui_open(frame)
    return bool(
        recognition.observation.recognized
        and recognition.observation.screen in _CAMPAIGN_ENTRY_OPEN_SCREENS
    )


def _blue_vortex_candidates(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find fresh, bounded blue-vortex geometry on the Campaign map."""

    if frame is None or frame.shape[:2] != (1280, 800):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([90, 110, 90]), np.array([135, 255, 255]))
    x0, y0, x1, y1 = _UC_PORTAL_SEARCH_ROI
    bounded = np.zeros_like(blue)
    bounded[y0:y1, x0:x1] = blue[y0:y1, x0:x1]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
    candidates: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[index]
        if (
            area >= 15000
            and width >= 150
            and height >= 150
            and 480 <= cx <= 640
            and 760 <= cy <= 920
        ):
            candidates.append((x, y, x + width, y + height))
    return candidates


def _bind_ultimate_challenge_entry(
    frame: np.ndarray,
    *,
    reset_identity: str | None,
) -> UltimateChallengeEntryObservation:
    """Bind the blue vortex only after Campaign context and uniqueness checks."""

    if _unexpected_visual_popup(frame):
        return UltimateChallengeEntryObservation(
            campaign_screen_recognized=False,
            entry_control_visible=False,
            entry_control_identity="",
            entry_roi=None,
            already_completed_marker=False,
            reset_identity=reset_identity,
            source_frame_sha256=frame_sha256(frame),
        )
    campaign_open = _campaign_context_recognized(frame)
    candidates = _blue_vortex_candidates(frame) if campaign_open else []
    entry_roi = candidates[0] if len(candidates) == 1 else None
    semantic_hits = _ocr_region_hits(frame, _UC_ENTRY_SEMANTIC_ROI) if entry_roi else {}
    marker = (
        ultimate_challenge_already_completed_from_ocr_hits(
            semantic_hits,
            entry_control_visible=entry_roi is not None,
        )
        if entry_roi is not None
        else False
    )
    return UltimateChallengeEntryObservation(
        campaign_screen_recognized=campaign_open,
        entry_control_visible=entry_roi is not None,
        entry_control_identity=ULTIMATE_CHALLENGE_ENTRY_IDENTITY if entry_roi else "",
        entry_roi=entry_roi,
        already_completed_marker=marker,
        reset_identity=reset_identity,
        source_frame_sha256=frame_sha256(frame),
    )


def _write_result(session: Path, result: dict[str, object]) -> None:
    terminal = result.get("terminal")
    if not isinstance(terminal, str) or not terminal.strip():
        raise ValueError("operator result requires a terminal identity")
    _write_operator_artifacts(session, terminal)
    (session / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    require_operator_evidence(session)
    print(json.dumps(result, sort_keys=True, default=str))


def _retain_top_level_frame(
    session: Path,
    source_frame: CapturedNativeFrame,
    filename: str,
) -> tuple[str, str]:
    """Copy an exact native runtime capture into operator top-level evidence."""

    target = session / "frames" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_frame.path, target)
    payload = target.read_bytes()
    return (
        str(target.relative_to(session)).replace("\\", "/"),
        hashlib.sha256(payload).hexdigest(),
    )


def _capture_and_retain_terminal_source(
    runtime: LocalBlueStacksRuntime,
    *,
    session: Path,
    events: Path,
    capture_label: str,
    frame_filename: str,
    event_type: str,
    event_payload: dict[str, object] | None = None,
) -> tuple[CapturedNativeFrame, str, str]:
    """Retain truthful source evidence before a terminal result is written."""

    source = runtime.capture(capture_label)
    frame_path, frame_hash = _retain_top_level_frame(session, source, frame_filename)
    event = {
        "type": event_type,
        "flow_id": FLOW_ID,
        "capture_label": capture_label,
        "frame": frame_path,
        "source_frame_sha256": source.sha256,
    }
    if event_payload:
        event.update(event_payload)
    append_event(events, event)
    return source, frame_path, frame_hash


def _ocr_region_text(
    frame: np.ndarray,
    region: tuple[int, int, int, int],
    *,
    psm: int = 7,
) -> str:
    """Read semantic corroboration from one narrow state ROI."""

    x0, y0, x1, y1 = region
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return ""
    enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return " ".join(
        str(pytesseract.image_to_string(enlarged, config=f"--psm {psm}")).casefold().split()
    )


def _recognize_ultimate_main(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Require the lower red Challenge control and narrow title corroboration."""

    if _unexpected_visual_popup(frame):
        return None
    challenge_roi = _bind_red_challenge_button(frame)
    title = _ocr_region_text(frame, _UC_TITLE_ROI, psm=7)
    compact_title = "".join(character for character in title if character.isalpha())
    if challenge_roi is None or "ultimatechallenge" not in compact_title:
        return None
    return challenge_roi


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
        if (
            area >= 8000
            and width >= 150
            and height >= 45
            and 1180 <= cy <= 1260
            and x >= 200
            and y >= 1160
        ):
            candidates.append(index)
    if len(candidates) != 1:
        return None
    return (320, 1195, 480, 1245)


def _lineup_selected_card_color_counts(hsv: np.ndarray) -> tuple[int, ...]:
    """Count the existing selected-color signature in each fixed card ROI."""

    selected = cv2.inRange(hsv, np.array([15, 120, 140]), np.array([40, 255, 255]))
    return tuple(
        int(np.count_nonzero(selected[y0:y1, x0:x1]))
        for x0, y0, x1, y1 in _HERO_LINEUP_SELECTED_CARD_ROIS
    )


def _lineup_selected_card_union_area() -> int:
    """Return the area of the independently bound five-card union."""

    return sum(_roi_area(roi) for roi in _HERO_LINEUP_SELECTED_CARD_ROIS)


def _lineup_card_grid_candidate_matches(
    candidate: tuple[int, int, int, int],
) -> bool:
    """Recognize only the measured nested card-grid contour artifact."""

    if candidate not in _HERO_LINEUP_CARD_GRID_BOXES:
        return False
    selected_union_area = _lineup_selected_card_union_area()
    if selected_union_area <= 0:
        return False
    intersection = sum(
        _roi_intersection_area(candidate, roi)
        for roi in _HERO_LINEUP_SELECTED_CARD_ROIS
    )
    return intersection / selected_union_area >= 0.78


def _bind_lineup_challenge_button(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind the gold Hero Lineup Challenge control from current native geometry."""

    if frame is None or frame.shape[:2] != (1280, 800):
        return None
    if not _ocr_ordered_tokens(frame, _UC_TITLE_ROI, ("hero", "lineup")):
        return None
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
    selected_counts = _lineup_selected_card_color_counts(hsv)
    if len(candidates) != 1 or any(
        count < _HERO_LINEUP_SELECTED_COLOR_MINIMUM
        for count in selected_counts
    ):
        return None
    try:
        popup_candidates = _central_popup_candidates(frame)
    except Exception:
        return None
    for popup in popup_candidates:
        if not _lineup_card_grid_candidate_matches(popup):
            return None
    if len(selected_counts) != 5:
        return None
    return (300, 1175, 500, 1230)


def _continue_from_vip_reset_popup(
    *,
    runtime: LocalBlueStacksRuntime,
    initial: CapturedNativeFrame,
    initial_observation: dict[str, object],
    session: Path,
    events: Path,
    post_input_delay: float,
) -> tuple[CapturedNativeFrame | None, str | None, dict[str, object]]:
    """Close one exact VIP reset popup and admit only Hero Lineup."""

    detail: dict[str, object] = {
        "initial_source_sha256": initial.sha256,
        "initial_source": str(initial.path),
        "status": "blocked_fail_closed",
    }
    try:
        immediate_before = runtime.capture("vip-reset-close-immediate-before")
        immediate_path, _immediate_hash = _retain_top_level_frame(
            session,
            immediate_before,
            "vip-reset-close-immediate-before.png",
        )
        detail.update(
            {
                "immediate_before": immediate_path,
                "immediate_before_sha256": immediate_before.sha256,
            }
        )
        fresh = recognize_reset_popup(immediate_before.frame)
        detail["fresh_observation"] = fresh
        if not _exact_vip_reset_popup(initial_observation):
            detail["reason"] = "initial VIP reset popup recognition was not exact"
            return None, None, detail
        initial_target = initial_observation["target"]
        if (
            not _exact_vip_reset_popup(fresh)
            or fresh.get("target") != initial_target
            or fresh.get("target_center") != initial_observation.get("target_center")
        ):
            detail["reason"] = "VIP reset popup or Close target drifted before dispatch"
            detail["initial_target_roi"] = initial_target
            detail["fresh_target_roi"] = (
                fresh.get("target") if isinstance(fresh, dict) else None
            )
            return None, None, detail

        action_key = f"reset-popup-close:{immediate_before.sha256}"
        detail["action_key"] = action_key
        input_count_before = _runtime_input_count(runtime)
        action_keys_before = _runtime_action_keys(runtime)
        try:
            runtime.tap(
                immediate_before,
                target_identity="reset-popup-close",
                target_roi=fresh["target"],
                action_key=action_key,
                consequential=False,
            )
        except BaseException as exc:
            runtime_accounted = _runtime_tap_dispatch_was_accounted(
                runtime,
                action_key=action_key,
                input_count_before=input_count_before,
                action_keys_before=action_keys_before,
            )
            detail.update(
                {
                    "runtime_accounted": runtime_accounted,
                    "tap_error": f"{type(exc).__name__}: {exc}",
                }
            )
            if runtime_accounted:
                runtime.reconcile(
                    action_key,
                    "unresolved",
                    immediate_before,
                    "VIP reset-popup Close transport failed after runtime accounting",
                )
            detail["reason"] = "VIP reset-popup Close transport failed"
            return None, None, detail

        runtime_accounted = _runtime_tap_dispatch_was_accounted(
            runtime,
            action_key=action_key,
            input_count_before=input_count_before,
            action_keys_before=action_keys_before,
        )
        detail["runtime_accounted"] = runtime_accounted
        if not runtime_accounted:
            detail["reason"] = "VIP reset-popup Close was not runtime-accounted"
            return None, None, detail

        try:
            time.sleep(post_input_delay)
        except BaseException as exc:
            runtime.reconcile(
                action_key,
                "unresolved",
                immediate_before,
                "VIP reset-popup Close post delay failed after runtime accounting",
            )
            detail.update(
                {
                    "reason": "VIP reset-popup Close post delay failed",
                    "delay_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None, None, detail
        try:
            settled = runtime.capture("vip-reset-close-settled")
        except BaseException as exc:
            runtime.reconcile(
                action_key,
                "unresolved",
                immediate_before,
                "VIP reset-popup Close settled capture failed after runtime accounting",
            )
            detail.update(
                {
                    "reason": "VIP reset-popup Close settled capture failed",
                    "capture_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None, None, detail

        try:
            settled_path, _settled_hash = _retain_top_level_frame(
                session,
                settled,
                "campaign-resume-source.png",
            )
        except BaseException as exc:
            runtime.reconcile(
                action_key,
                "unresolved",
                settled,
                "VIP reset-popup Close settled evidence retention failed after runtime accounting",
            )
            detail.update(
                {
                    "reason": "VIP reset-popup Close settled evidence retention failed",
                    "retention_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None, None, detail
        detail.update(
            {
                "settled": settled_path,
                "settled_sha256": settled.sha256,
            }
        )
        try:
            settled_popup = recognize_reset_popup(settled.frame)
            lineup_roi = _bind_lineup_challenge_button(settled.frame)
            other_resume_states = {
                "ultimate_challenge": _recognize_ultimate_main(settled.frame),
                "active_battle": _recognize_active_battle(settled.frame),
                "flee_warning": _bind_flee_warning_button(settled.frame),
            }
        except BaseException as exc:
            runtime.reconcile(
                action_key,
                "unresolved",
                settled,
                "VIP reset-popup Close successor recognition failed after runtime accounting",
            )
            detail.update(
                {
                    "reason": "VIP reset-popup Close successor recognition failed",
                    "recognizer_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None, None, detail

        detail.update(
            {
                "settled_popup": settled_popup,
                "lineup_roi": lineup_roi,
                "other_resume_states": other_resume_states,
            }
        )
        if (
            not isinstance(settled_popup, dict)
            or settled_popup.get("recognized") is not False
            or not _valid_native_roi(lineup_roi)
            or any(value is not None for value in other_resume_states.values())
        ):
            runtime.reconcile(
                action_key,
                "unresolved",
                settled,
                "VIP reset-popup Close successor was not uniquely Hero Lineup",
            )
            detail["reason"] = "VIP reset-popup Close successor was not uniquely Hero Lineup"
            return None, None, detail

        runtime.reconcile(
            action_key,
            "confirmed",
            settled,
            "VIP reset-popup Close produced a unique Hero Lineup successor",
        )
        detail["status"] = "confirmed"
        return settled, settled_path, detail
    except BaseException as exc:
        detail.update(
            {
                "reason": "VIP reset-popup continuation failed before dispatch",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return None, None, detail


def _bind_active_battle_exit(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind the icon-only upper-right Exit after proving the native puzzle board."""

    if _unexpected_visual_popup(frame):
        return None
    if _has_warning_modal_geometry(frame):
        return None
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


def _has_warning_modal_geometry(frame: np.ndarray) -> bool:
    """Recognize the bounded warning panel before considering its controls."""

    x0, y0, x1, y1 = _FLEE_MODAL_ROI
    if frame is None or frame.shape[:2] != (1280, 800):
        return False
    modal = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(modal, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    header = modal[:70]
    header_hsv = cv2.cvtColor(header, cv2.COLOR_BGR2HSV)
    red_header = cv2.inRange(
        header_hsv, np.array([0, 35, 35]), np.array([15, 255, 220])
    )
    dark_center = gray[75:-45, 45:-45]
    panel_shape = bool(
        np.count_nonzero(edges) >= 1800
        and np.count_nonzero(red_header) >= 900
        and float(np.mean(dark_center)) <= 115.0
    )
    if not panel_shape:
        return False
    fight = _visual_control_candidates(
        frame,
        search_roi=_FLEE_FIGHT_SEARCH_ROI,
        hsv_lower=(0, 60, 60),
        hsv_upper=(15, 255, 255),
        min_area=8000,
        min_width=170,
        min_height=45,
    )
    flee = _visual_control_candidates(
        frame,
        search_roi=_FLEE_FLEE_SEARCH_ROI,
        hsv_lower=(10, 80, 80),
        hsv_upper=(35, 255, 255),
        min_area=12000,
        min_width=190,
        min_height=55,
    )
    return len(fight) == 1 and len(flee) == 1


def _visual_control_candidates(
    frame: np.ndarray,
    *,
    search_roi: tuple[int, int, int, int],
    hsv_lower: tuple[int, int, int],
    hsv_upper: tuple[int, int, int],
    min_area: int,
    min_width: int,
    min_height: int,
) -> list[tuple[int, int, int, int]]:
    """Return all color/geometry candidates inside one bounded control ROI."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_lower), np.array(hsv_upper))
    bounded = np.zeros_like(mask)
    x0, y0, x1, y1 = search_roi
    bounded[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(bounded)
    candidates: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx, cy = centroids[index]
        if area >= min_area and width >= min_width and height >= min_height:
            candidates.append((x, y, x + width, y + height))
    return candidates


def _flee_modal_popup_matches(
    popup: tuple[int, int, int, int],
) -> bool:
    """Require a bounded two-way spatial match to the expected Flee modal."""

    intersection = _roi_intersection_area(popup, _FLEE_MODAL_ROI)
    popup_area = _roi_area(popup)
    modal_area = _roi_area(_FLEE_MODAL_ROI)
    if intersection <= 0 or popup_area <= 0 or modal_area <= 0:
        return False
    return (
        intersection / popup_area >= 0.75
        and intersection / modal_area >= 0.75
        and _flee_modal_popup_iou(popup) >= 0.60
    )


def _recognize_flee_warning(
    frame: np.ndarray,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    """Require modal geometry, both controls, and narrow warning text."""

    popup_panels = _flee_popup_panel_candidates(frame)
    if len(popup_panels) != 1:
        return None
    popup = popup_panels[0]
    if not _flee_modal_popup_matches(popup):
        return None
    if not _has_warning_modal_geometry(frame):
        return None
    fight = _visual_control_candidates(
        frame,
        search_roi=_FLEE_FIGHT_SEARCH_ROI,
        hsv_lower=(0, 60, 60),
        hsv_upper=(15, 255, 255),
        min_area=8000,
        min_width=170,
        min_height=45,
    )
    flee = _visual_control_candidates(
        frame,
        search_roi=_FLEE_FLEE_SEARCH_ROI,
        hsv_lower=(10, 80, 80),
        hsv_upper=(35, 255, 255),
        min_area=12000,
        min_width=190,
        min_height=55,
    )
    text = _ocr_region_text(frame, _FLEE_MODAL_TEXT_ROI, psm=6)
    if len(fight) != 1 or len(flee) != 1:
        return None
    if "flee now" not in text or "failure" not in text:
        return None
    return fight[0], flee[0]


def _bind_flee_warning_button(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind only the gold Flee button on the exact failure-warning modal."""

    controls = _recognize_flee_warning(frame)
    if controls is None:
        return None
    _fight_roi, flee_roi = controls
    return flee_roi


def _recognize_active_battle(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bind Exit only on an active puzzle board, never under the warning modal."""

    if _has_warning_modal_geometry(frame):
        return None
    return _bind_active_battle_exit(frame)


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


def _capture_lineup_successor_after_challenge(
    runtime: LocalBlueStacksRuntime,
    *,
    label: str,
    attempts: int = 6,
    settle_seconds: float = 0.8,
) -> tuple[
    CapturedNativeFrame | None,
    tuple[int, int, int, int] | None,
    str | None,
    Exception | None,
]:
    """Poll Hero Lineup while retaining the exact latest post capture.

    The returned capture is the frame used by the successful binder result, or
    the latest retained post frame when polling fails.  A capture or binder
    exception is returned instead of escaping so the caller can reconcile the
    Challenge action against truthful evidence.
    """

    latest: CapturedNativeFrame | None = None
    for ordinal in range(attempts):
        time.sleep(settle_seconds)
        try:
            latest = runtime.capture(f"{label}-{ordinal + 1:02d}")
        except Exception as exc:
            return latest, None, "capture", exc
        try:
            lineup_roi = _bind_lineup_challenge_button(latest.frame)
        except Exception as exc:
            return latest, None, "predicate", exc
        if lineup_roi is not None:
            return latest, lineup_roi, None, None
    return latest, None, None, None


def _write_operator_artifacts(session: Path, terminal: str) -> None:
    """Ensure substantive artifacts carry the current terminal identity."""

    if not isinstance(terminal, str) or not terminal.strip():
        raise ValueError("operator artifacts require a terminal identity")
    rows = {
        "ledger.jsonl": {
            "flow_id": FLOW_ID,
            "record_type": "operator_terminal",
            "terminal": terminal,
            "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
        },
        "capability-audit.jsonl": {
            "flow_id": FLOW_ID,
            "record_type": "operator_terminal",
            "terminal": terminal,
            "action_class": "ultimate_challenge_zero_resource_flee",
            "dispatch_policy": "SafeAction/NativeRuntime",
        },
        "journal.jsonl": {
            "flow_id": FLOW_ID,
            "record_type": "operator_terminal",
            "terminal": terminal,
            "unresolved_action": False,
        },
    }
    for name, payload in rows.items():
        path = session / name
        if not path.exists() or path.stat().st_size == 0:
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            continue
        try:
            existing_rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing_rows = []
        last = existing_rows[-1] if existing_rows else None
        if not (
            isinstance(last, dict)
            and last.get("record_type") == "operator_terminal"
            and last.get("terminal") == terminal
        ):
            append_event(path, payload)


def _run_post_flee_home_route(
    *,
    runner: ADBRunner,
    session: Path,
    events: Path,
    reset_identity: str,
    post_input_delay: float,
    runtime: LocalBlueStacksRuntime | None = None,
    completed_actions: list[dict[str, object]] | None = None,
) -> tuple[str, dict[str, object]]:
    """Return UC main → Campaign tier map → canonical Home with verified transitions."""

    runtime = runtime or LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    completed_actions = list(completed_actions or [])
    uc, uc_frame, uc_frame_sha256 = _capture_and_retain_terminal_source(
        runtime,
        session=session,
        events=events,
        capture_label="post-flee-ultimate-immediate-before",
        frame_filename="post-flee-ultimate-immediate-before.png",
        event_type="post_flee_home_source",
        event_payload={"state": "ultimate_challenge_main"},
    )
    if _recognize_ultimate_main(uc.frame) is None:
        return TERMINAL_BLOCKED, {
            "reason": "post-Flee Ultimate Challenge main not positively recognized",
            "completed_actions": completed_actions,
            "source_frame": uc_frame,
            "source_frame_sha256": uc_frame_sha256,
        }
    uc_back_key = f"uc-back-{utc_stamp()}"
    runtime.back(
        uc,
        target_identity="ultimate-challenge-back",
        action_key=uc_back_key,
    )
    campaign = _capture_until(
        runtime,
        label="campaign-tier-map-successor",
        predicate=_campaign_context_recognized,
        attempts=6,
        settle_seconds=max(0.8, post_input_delay),
    )
    if campaign is None:
        return TERMINAL_BLOCKED, {
            "reason": "Campaign successor not captured after Ultimate Challenge back",
            "completed_actions": completed_actions,
        }
    if not _campaign_context_recognized(campaign.frame):
        return TERMINAL_BLOCKED, {
            "reason": "Campaign successor not positively recognized after Ultimate Challenge back",
            "campaign_sha256": campaign.sha256,
            "completed_actions": completed_actions,
        }
    runtime.reconcile(
        uc_back_key,
        "confirmed",
        campaign,
        "Campaign context recognized after Ultimate Challenge back",
    )
    completed_actions.append(
        {
            "action": "back_uc_to_campaign",
            "before_sha256": uc.sha256,
            "post_sha256": campaign.sha256,
        }
    )
    campaign_back_key = f"campaign-back-{utc_stamp()}"
    runtime.back(
        campaign,
        target_identity="campaign-back-to-home",
        action_key=campaign_back_key,
    )
    home = _capture_until(
        runtime,
        label="canonical-home-successor",
        predicate=_home_nav_terminal,
        attempts=8,
        settle_seconds=max(0.8, post_input_delay),
    )
    if home is None or not _home_nav_terminal(home.frame):
        return TERMINAL_BLOCKED, {
            "reason": "canonical Home terminal not positively recognized after Campaign back",
            "campaign_sha256": campaign.sha256,
            "completed_actions": completed_actions,
        }
    runtime.reconcile(
        campaign_back_key,
        "confirmed",
        home,
        "template Home recognized after Campaign back",
    )
    completed_actions.append(
        {
            "action": "back_campaign_to_home",
            "before_sha256": campaign.sha256,
            "post_sha256": home.sha256,
        }
    )
    append_event(
        events,
        {
            "type": "post_flee_home_route",
            "ultimate_sha256": uc.sha256,
            "campaign_sha256": campaign.sha256,
            "home_sha256": home.sha256,
            "home_nav_recognized": True,
        },
    )
    home_frame, home_frame_sha256 = _retain_top_level_frame(
        session, home, "canonical-home-terminal.png"
    )
    return TERMINAL_COMPLETE_FOR_RESET, {
        "reason": "Flee completion retained and canonical Home recognized through verified back transitions",
        "completed_actions": completed_actions,
        "home_sha256": home.sha256,
        "home_frame": home_frame,
        "home_frame_sha256": home_frame_sha256,
        "home_nav_recognized": True,
        "reset_identity": reset_identity,
        "input_count": runtime.input_count,
        "navigation_input_count": runtime.input_count,
        "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
    }


def _run_daily_route(
    *,
    runtime: LocalBlueStacksRuntime,
    session: Path,
    frames: Path,
    events: Path,
    atlas_path: Path,
    reset_identity: str,
    maximum_pans: int,
    post_input_delay: float,
    entry_observation,
    starting_state: str = "campaign_entry",
    resume_capture: CapturedNativeFrame | None = None,
    resume_lineup_roi: tuple[int, int, int, int] | None = None,
) -> tuple[str, dict[str, object]]:
    """Execute the exact bounded Challenge → Exit → Flee → Home route."""

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
        exit_roi = _recognize_active_battle(active.frame)
        if exit_roi is None:
            return TERMINAL_BLOCKED, {"reason": "fresh active-battle resume source or icon-only Exit not positively bound", "completed_actions": completed_actions}
        exit_bound = ("icon-only Exit", exit_roi)
        append_event(events, {"type": "active_battle_resume_accepted", "source_sha256": active.sha256, "target_roi": exit_roi})
    elif starting_state == "hero_lineup":
        lineup = resume_capture or runtime.capture("hero-lineup-resume-source")
        lineup_roi = resume_lineup_roi or _bind_lineup_challenge_button(lineup.frame)
        if lineup_roi is None:
            return TERMINAL_BLOCKED, {"reason": "fresh Hero Lineup resume source or gold Challenge button not positively bound", "completed_actions": completed_actions}
        append_event(events, {"type": "hero_lineup_resume_accepted", "source_sha256": lineup.sha256, "target_roi": lineup_roi})
    elif starting_state == "ultimate_challenge":
        current = runtime.capture("ultimate-challenge-resume-source")
        append_event(events, {"type": "ultimate_challenge_resume_accepted", "source_sha256": current.sha256})
    else:
        source = runtime.capture("uc-entry-immediate-before")
        fresh_entry = _bind_ultimate_challenge_entry(
            source.frame,
            reset_identity=reset_identity,
        )
        if (
            not fresh_entry.entry_control_visible
            or fresh_entry.entry_roi is None
        ):
            return TERMINAL_BLOCKED, {
                "reason": "Ultimate Challenge entry was not positively rebound on immediate-before frame",
                "completed_actions": completed_actions,
            }
        runtime.tap(
            source,
            target_identity="ultimate-challenge-entry",
            target_roi=fresh_entry.entry_roi,
            action_key=f"ultimate-entry-{utc_stamp()}",
            consequential=False,
        )
        time.sleep(post_input_delay)
        current = runtime.capture("ultimate-challenge-post-entry")
        append_event(events, {"type": "ultimate_challenge_opened", "source_sha256": source.sha256, "post_sha256": current.sha256})

    if starting_state not in {"hero_lineup", "active_battle", "flee_warning"}:
        before = runtime.capture("tap_challenge-immediate-before")
        challenge_roi = _recognize_ultimate_main(before.frame)
        if challenge_roi is None:
            return TERMINAL_BLOCKED, {"reason": "actual red Challenge button not bound on Ultimate Challenge main", "completed_actions": completed_actions}
        challenge_key = f"tap_challenge-1-{utc_stamp()}"
        runtime.tap(before, target_identity="tap_challenge", target_roi=challenge_roi, action_key=challenge_key, consequential=True)
        lineup, lineup_roi, polling_phase, polling_error = (
            _capture_lineup_successor_after_challenge(
                runtime,
                label="hero-lineup-successor",
                attempts=6,
                settle_seconds=max(0.8, post_input_delay),
            )
        )
        if polling_error is not None:
            evidence = lineup or before
            if lineup is None:
                reason = (
                    "Hero Lineup successor "
                    f"{polling_phase} failed after Challenge; no post capture was "
                    "retained, so semantic post evidence is unavailable: "
                    f"{type(polling_error).__name__}: {polling_error}"
                )
            else:
                reason = (
                    "Hero Lineup successor "
                    f"{polling_phase} failed after Challenge; latest retained post "
                    "capture is unresolved and semantic post evidence is "
                    f"unavailable: {type(polling_error).__name__}: {polling_error}"
                )
            runtime.reconcile(challenge_key, "unresolved", evidence, reason)
            return TERMINAL_BLOCKED, {
                "reason": reason,
                "completed_actions": completed_actions,
                "challenge_action_key": challenge_key,
                "latest_capture_sha256": evidence.sha256,
                "capture_error": f"{type(polling_error).__name__}: {polling_error}",
            }
        if lineup is None:
            reason = "Hero Lineup successor was not captured after Challenge"
            return TERMINAL_BLOCKED, {
                "reason": reason,
                "completed_actions": completed_actions,
                "challenge_action_key": challenge_key,
            }
        if lineup_roi is None:
            reason = "Hero Lineup successor not positively recognized after Challenge"
            runtime.reconcile(challenge_key, "unresolved", lineup, reason)
            return TERMINAL_BLOCKED, {
                "reason": reason,
                "completed_actions": completed_actions,
                "challenge_action_key": challenge_key,
                "lineup_sha256": lineup.sha256,
                "latest_capture_sha256": lineup.sha256,
            }
        runtime.reconcile(challenge_key, "confirmed", lineup, "Hero Lineup recognized after Challenge")
        completed_actions.append({"action": "tap_challenge", "target_text": "red Challenge button", "target_roi": challenge_roi, "before_sha256": before.sha256, "post_sha256": lineup.sha256})
        append_event(events, {"type": "consequential_step", "action": "tap_challenge", "target_text": "red Challenge button", "target_roi": challenge_roi, "before_sha256": before.sha256, "post_sha256": lineup.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})
    if starting_state not in {"active_battle", "flee_warning"}:
        lineup_key = f"tap_lineup_challenge-2-{utc_stamp()}"
        runtime.tap(lineup, target_identity="tap_lineup_challenge", target_roi=lineup_roi, action_key=lineup_key, consequential=True)
        active = _capture_until(
            runtime,
            label="active-challenge-successor",
            predicate=lambda frame: _recognize_active_battle(frame) is not None,
            attempts=10,
            settle_seconds=max(0.8, post_input_delay),
        )
        if active is None:
            return TERMINAL_BLOCKED, {"reason": "active challenge successor not captured", "completed_actions": completed_actions, "lineup_action_key": lineup_key}
        exit_roi = _recognize_active_battle(active.frame)
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
        predicate=lambda frame: _recognize_ultimate_main(frame) is not None,
        attempts=6,
        settle_seconds=max(0.8, post_input_delay),
    )
    if fled is None or _recognize_ultimate_main(fled.frame) is None:
        return TERMINAL_BLOCKED, {"reason": "Flee completion not positively recognized", "completed_actions": completed_actions, "flee_action_key": flee_key}
    runtime.reconcile(flee_key, "confirmed", fled, "Ultimate Challenge main recognized after Flee")
    completed_actions.append({"action": "tap_flee", "target_text": flee_text, "target_roi": flee_roi, "before_sha256": warning.sha256, "post_sha256": fled.sha256})
    append_event(events, {"type": "consequential_step", "action": "tap_flee", "target_text": flee_text, "target_roi": flee_roi, "before_sha256": warning.sha256, "post_sha256": fled.sha256, "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}})

    return _run_post_flee_home_route(
        runner=runtime.runner,
        session=session,
        events=events,
        reset_identity=reset_identity,
        post_input_delay=post_input_delay,
        runtime=runtime,
        completed_actions=completed_actions,
    )


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
    parser.add_argument("--max-total-inputs", type=int, default=MAX_TOTAL_INPUTS)
    args = parser.parse_args(argv)

    if sum(bool(value) for value in (args.navigation_only, args.daily, args.post_flee_home_only)) != 1:
        parser.error("select exactly one of --navigation-only, --daily, or --post-flee-home-only")
    if args.max_total_inputs != MAX_TOTAL_INPUTS:
        parser.error("Ultimate Challenge aggregate input ceiling is exactly 16")
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
        frames = session / "frames"
        frames.mkdir(parents=True, exist_ok=False)
        runner = ADBRunner(args.adb, args.serial)
        devices = {device.serial: device.state for device in runner.list_devices()}
        if devices.get(args.serial) != "device" or runner.get_state() != "device":
            raise RuntimeError("exact BlueStacks serial is not in device state")
        runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=args.execute)
        source, home_frame, home_frame_sha256 = _capture_and_retain_terminal_source(
            runtime,
            session=session,
            events=session / "events.jsonl",
            capture_label="already-completed-home-source",
            frame_filename="canonical-home-terminal.png",
            event_type="already_completed_home_source",
            event_payload={
                "reset_identity": args.reset_identity,
                "input_count": runtime.input_count,
            },
        )
        home_nav_recognized = _home_nav_terminal(source.frame)
        append_event(
            session / "events.jsonl",
            {
                "type": "already_completed_home_recognition",
                "home_nav_recognized": home_nav_recognized,
                "home_frame": home_frame,
                "home_frame_sha256": home_frame_sha256,
                "source_sha256": source.sha256,
                "input_count": runtime.input_count,
            },
        )
        terminal = TERMINAL_ALREADY_COMPLETED if home_nav_recognized else TERMINAL_BLOCKED
        result = {
            "status": terminal,
            "terminal": terminal,
            "reason": (
                precheck.reason
                if home_nav_recognized
                else "already_completed state requires a current template Home source"
            ),
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": not args.daily,
            "dispatch": False,
            "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            "reset_identity": args.reset_identity,
            "navigation_input_count": 0,
            "input_count": 0,
            "home_nav_recognized": home_nav_recognized,
            "home_frame": home_frame,
            "home_frame_sha256": home_frame_sha256,
            "terminal_runtime_state": (
                "recognized_home"
                if terminal == TERMINAL_ALREADY_COMPLETED and home_nav_recognized
                else "safe_blocked_terminal"
            ),
        }
        _write_result(session, result)
        return 0 if terminal == TERMINAL_ALREADY_COMPLETED else 3
    if precheck.terminal == TERMINAL_BLOCKED and precheck.reason != "not already_completed":
        session = args.output_directory / f"blocked-{utc_stamp()}"
        session.mkdir(parents=True, exist_ok=False)
        (session / "frames").mkdir(parents=True, exist_ok=False)
        runner = ADBRunner(args.adb, args.serial)
        devices = {device.serial: device.state for device in runner.list_devices()}
        if devices.get(args.serial) != "device" or runner.get_state() != "device":
            raise RuntimeError("exact BlueStacks serial is not in device state")
        runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=args.execute)
        _source, source_frame, source_frame_sha256 = _capture_and_retain_terminal_source(
            runtime,
            session=session,
            events=session / "events.jsonl",
            capture_label="reset-precheck-blocked-source",
            frame_filename="reset-precheck-blocked-source.png",
            event_type="reset_precheck_blocked",
            event_payload={
                "blocked_reason": precheck.reason,
                "reset_identity": args.reset_identity,
                "input_count": runtime.input_count,
            },
        )
        result = {
            "status": TERMINAL_BLOCKED,
            "terminal": TERMINAL_BLOCKED,
            "reason": precheck.reason,
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": True,
            "dispatch": False,
            "reset_identity": args.reset_identity,
            "source_frame": source_frame,
            "source_frame_sha256": source_frame_sha256,
            "input_count": runtime.input_count,
            "navigation_input_count": runtime.input_count,
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

    os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(args.max_total_inputs)

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
    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)

    if args.post_flee_home_only:
        terminal, detail = _run_post_flee_home_route(
            runner=runner,
            session=session,
            events=events,
            reset_identity=args.reset_identity or "",
            post_input_delay=args.post_input_delay,
            runtime=runtime,
        )
        if runtime.input_count > args.max_total_inputs:
            terminal = TERMINAL_BLOCKED
            detail["reason"] = "aggregate runtime input count exceeded 16"
        result = {"status": terminal, "terminal": terminal, "flow_id": FLOW_ID, "session": str(session), "navigation_only": False, "dispatch": terminal == TERMINAL_COMPLETE_FOR_RESET, **detail, "input_count": runtime.input_count, "navigation_input_count": runtime.input_count}
        _write_result(session, result)
        return 0 if terminal == TERMINAL_COMPLETE_FOR_RESET else 3

    resume_capture = runtime.capture("campaign-resume-source")
    resume_frame = resume_capture.frame
    resume_path, _resume_hash = _retain_top_level_frame(
        session, resume_capture, "campaign-resume-source.png"
    )
    vip_resume_capture: CapturedNativeFrame | None = None
    vip_resume_lineup_roi: tuple[int, int, int, int] | None = None
    try:
        vip_initial_observation = recognize_reset_popup(resume_frame)
    except BaseException as exc:
        result = {
            "status": TERMINAL_BLOCKED,
            "terminal": TERMINAL_BLOCKED,
            "reason": "initial VIP reset-popup recognition failed",
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": False,
            "dispatch": False,
            "recognizer_error": f"{type(exc).__name__}: {exc}",
            "resume_source": str(resume_path),
            "resume_source_sha256": resume_capture.sha256,
            "input_count": runtime.input_count,
            "navigation_input_count": runtime.input_count,
            "home_recovery_latency_seconds": time.monotonic() - started,
        }
        _write_result(session, result)
        return 3
    if isinstance(vip_initial_observation, dict) and vip_initial_observation.get(
        "recognized"
    ):
        (
            vip_resume_capture,
            vip_resume_path,
            vip_detail,
        ) = _continue_from_vip_reset_popup(
            runtime=runtime,
            initial=resume_capture,
            initial_observation=vip_initial_observation,
            session=session,
            events=events,
            post_input_delay=args.post_input_delay,
        )
        if vip_resume_capture is None or vip_resume_path is None:
            result = {
                "status": TERMINAL_BLOCKED,
                "terminal": TERMINAL_BLOCKED,
                "reason": vip_detail.get(
                    "reason",
                    "VIP reset-popup continuation failed closed",
                ),
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "vip_reset_popup": vip_detail,
                "input_count": runtime.input_count,
                "navigation_input_count": runtime.input_count,
                "home_recovery_latency_seconds": time.monotonic() - started,
            }
            _write_result(session, result)
            return 3
        resume_capture = vip_resume_capture
        resume_frame = resume_capture.frame
        resume_path = vip_resume_path
        vip_resume_lineup_roi = vip_detail.get("lineup_roi")
        if not _valid_native_roi(vip_resume_lineup_roi):
            result = {
                "status": TERMINAL_BLOCKED,
                "terminal": TERMINAL_BLOCKED,
                "reason": "VIP reset-popup continuation did not retain a valid Hero Lineup target",
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "vip_reset_popup": vip_detail,
                "input_count": runtime.input_count,
                "navigation_input_count": runtime.input_count,
                "home_recovery_latency_seconds": time.monotonic() - started,
            }
            _write_result(session, result)
            return 3
        append_event(
            events,
            {
                "type": "vip_reset_popup_resume_accepted",
                "flow_id": FLOW_ID,
                "source_frame_sha256": resume_capture.sha256,
                "frame": str(resume_path),
                "target_roi": vip_resume_lineup_roi,
                "popup_close_action_key": vip_detail.get("action_key"),
            },
        )
    ultimate_already_open = _recognize_ultimate_main(resume_frame) is not None
    hero_lineup_already_open = (
        _valid_native_roi(vip_resume_lineup_roi)
        if vip_resume_capture is not None
        else _bind_lineup_challenge_button(resume_frame) is not None
    )
    active_battle_already_open = _recognize_active_battle(resume_frame) is not None
    flee_warning_already_open = _bind_flee_warning_button(resume_frame) is not None
    resume_observation = _bind_ultimate_challenge_entry(
        resume_frame, reset_identity=args.reset_identity
    )
    home_normalization_detail: dict[str, object] | None = None
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
    elif _home_nav_terminal(resume_frame):
        resumed_campaign = False
        entry_session = session / f"home-atlas-entry-{utc_stamp()}"
        normalized, home_normalization_detail = _normalize_ultimate_home_before_campaign(
            runtime=runtime,
            session=session,
            events=events,
            atlas_path=args.atlas,
            adb=args.adb,
            serial=args.serial,
            source=resume_capture,
            maximum_pans=args.maximum_pans,
            post_input_delay=args.post_input_delay,
        )
        if not normalized:
            entry = {
                "status": "blocked_fail_closed",
                "reason": home_normalization_detail.get(
                    "reason",
                    "Ultimate Home normalization failed closed",
                ),
                "records": [],
                "home_normalization": home_normalization_detail,
            }
        else:
            entry = run_verified_ultimate_challenge_campaign_door(
                runtime,
                atlas_path=args.atlas,
                maximum_pans=args.maximum_pans,
                execute=True,
                settle_seconds=args.post_input_delay,
                semantic_opened_check=_campaign_entry_semantically_opened,
            )
            entry["home_normalization"] = home_normalization_detail
    else:
        resumed_campaign = False
        entry_session = session
        entry = {
            "status": "blocked_fail_closed",
            "reason": "canonical Daily start requires current template Home or a recognized resume state",
            "records": [],
        }
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
            "home_normalization": home_normalization_detail,
            "input_count": runtime.input_count,
            "navigation_input_count": runtime.input_count,
            "home_recovery_latency_seconds": time.monotonic() - started,
        }
        _write_result(session, result)
        return 3

    if (flee_warning_already_open or active_battle_already_open or hero_lineup_already_open or ultimate_already_open) and args.daily:
        terminal, detail = _run_daily_route(
            runtime=runtime,
            session=session,
            frames=frames,
            events=events,
            atlas_path=args.atlas,
            reset_identity=args.reset_identity or "",
            maximum_pans=args.maximum_pans,
            post_input_delay=args.post_input_delay,
            entry_observation=resume_observation,
            starting_state="flee_warning" if flee_warning_already_open else ("active_battle" if active_battle_already_open else ("hero_lineup" if hero_lineup_already_open else "ultimate_challenge")),
            resume_capture=vip_resume_capture,
            resume_lineup_roi=(
                vip_resume_lineup_roi
                if _valid_native_roi(vip_resume_lineup_roi)
                else None
            ),
        )
        if runtime.input_count > args.max_total_inputs:
            terminal = TERMINAL_BLOCKED
            detail["reason"] = "aggregate runtime input count exceeded 16"
        result = {
            "status": terminal,
            "terminal": terminal,
            "reason": detail.get("reason", ""),
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": False,
            "dispatch": terminal == TERMINAL_COMPLETE_FOR_RESET,
            "reset_identity": args.reset_identity,
            "home_normalization": home_normalization_detail,
            **detail,
            "input_count": runtime.input_count,
            "navigation_input_count": runtime.input_count,
        }
        _write_result(session, result)
        return 0 if terminal in {TERMINAL_COMPLETE_FOR_RESET, TERMINAL_ALREADY_COMPLETED} else 3

    entry_capture = runtime.capture("uc-entry-bind")
    frame_path, _entry_bind_hash = _retain_top_level_frame(
        session, entry_capture, "uc-entry-bind.png"
    )
    observation = _bind_ultimate_challenge_entry(
        entry_capture.frame,
        reset_identity=args.reset_identity,
    )
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
            result = {
                "status": TERMINAL_BLOCKED,
                "terminal": TERMINAL_BLOCKED,
                "reason": "already_completed marker requires a current template Home source",
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "reset_identity": args.reset_identity,
                "input_count": runtime.input_count,
                "navigation_input_count": runtime.input_count,
                "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
            }
            _write_result(session, result)
            return 3
        if decision.terminal == TERMINAL_BLOCKED:
            result = {
                "status": TERMINAL_BLOCKED,
                "terminal": TERMINAL_BLOCKED,
                "reason": decision.reason,
                "session": str(session),
                "flow_id": FLOW_ID,
                "navigation_only": False,
                "dispatch": False,
                "reset_identity": args.reset_identity,
                "input_count": runtime.input_count,
                "navigation_input_count": runtime.input_count,
            }
            _write_result(session, result)
            return 3
        terminal, detail = _run_daily_route(
            runtime=runtime,
            session=session,
            frames=frames,
            events=events,
            atlas_path=args.atlas,
            reset_identity=args.reset_identity or "",
            maximum_pans=args.maximum_pans,
            post_input_delay=args.post_input_delay,
            entry_observation=observation,
        )
        if runtime.input_count > args.max_total_inputs:
            terminal = TERMINAL_BLOCKED
            detail["reason"] = "aggregate runtime input count exceeded 16"
        result = {
            "status": terminal,
            "terminal": terminal,
            "reason": detail.get("reason", ""),
            "session": str(session),
            "flow_id": FLOW_ID,
            "navigation_only": False,
            "dispatch": terminal == TERMINAL_COMPLETE_FOR_RESET,
            "reset_identity": args.reset_identity,
            "home_normalization": home_normalization_detail,
            **detail,
            "input_count": runtime.input_count,
            "navigation_input_count": runtime.input_count,
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
        "terminal_runtime_state": "ultimate_challenge_entry_recognized"
        if decision.terminal == TERMINAL_NAVIGATION_ONLY_COMPLETE
        else "safe_blocked_terminal",
        "entry_roi": decision.entry_roi,
        "reset_identity": decision.reset_identity,
        "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
        "home_atlas_entry": {k: v for k, v in entry.items() if k != "tap_telemetry"},
        "home_normalization": home_normalization_detail,
        "input_count": runtime.input_count,
        "navigation_input_count": runtime.input_count,
        "home_recovery_latency_seconds": time.monotonic() - started,
    }
    _write_result(session, result)
    if decision.terminal in {TERMINAL_NAVIGATION_ONLY_COMPLETE, TERMINAL_ALREADY_COMPLETED}:
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
