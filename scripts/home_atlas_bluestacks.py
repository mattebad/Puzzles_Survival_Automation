#!/usr/bin/env python3
"""Build, localize, and navigate a BlueStacks Home/Base atlas.

The CLI is unregistered and dry-run by default.  It never connects ADB implicitly and
accepts only the repository's explicit local BlueStacks serial policy.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time
import re
from typing import Any, Callable, Mapping, Optional

import cv2
import numpy as np
import pytesseract

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from tasks.home_atlas import BuildingBinding, LocalizationResult, ZoomIdentity, load_home_atlas
from tasks.home_atlas_planner import (
    DirectPanNavigator,
    GestureCalibration,
    PlanDisposition,
    SafeInteractionRegion,
    ViewportPlanningPolicy,
    camera_origin,
)
from tasks.home_atlas_vision import (
    BLUESTACKS_INTERACTION_ANCHOR,
    BLUESTACKS_PLATFORM,
    BLUESTACKS_PROFILE_ID,
    BLUESTACKS_SAFE_INTERACTION_BOX,
    HUD_MASK_RECTS,
    BlueStacksHomeLocalizer,
    bind_visible_building,
    classify_zoom,
    frame_digest,
    hud_mask,
    native_frame_guard,
    register_home_frame,
)
from tasks.navigation_observability import (
    navigation_observability_snapshot,
    report_navigation_session,
    serialize_navigation_observability_report,
)
from tasks.navigation_session import (
    AuthorizationScope,
    LatestObservation,
    NavigationCheckpoint,
    NavigationSession,
    complete_route_at_target_bound,
    compute_pan_gesture_fingerprint,
    create_session,
    complete_route_at_radial_successor,
    make_pan_action_key,
    mark_blocked,
    mark_dry_run,
    mark_uncertain,
    record_pan_dispatched,
    record_pan_prepared,
    record_plan,
    record_navigation_action_dispatched,
    record_navigation_action_prepared,
    record_home_recovered,
    record_radial_verified,
    record_safe_exit,
    reconcile_navigation_action,
    record_source_home_verified,
    record_target_bound,
    reconcile_pan,
    save_session,
)
from tasks.navigation_session_calibration import (
    SessionCalibrationMeasurement,
    SessionCalibrationState,
    consider_measurement,
    report_session_calibration,
)
from tasks.perception_bundle import (
    FramePerceptionBundle,
    FrameValidityState,
    ImmutableFrameValidationObservation,
    ImmutableRadialObservation,
    ImmutableRecognizedScreenObservation,
    NativeFrameIdentity,
    PerceptionBundleError,
    binding_from_result,
    bundle_evidence_snapshot,
    bundle_from_identity,
    classify_and_attach,
    localization_from_result,
)
from tasks.radial_semantics import (
    ActionabilityState,
    ControlRole,
    HomeRadialSemantics,
    OwningFacilityObservation,
    RadialAmbiguityState,
    RadialControlObservation,
    RecognitionState,
    radial_semantics_evidence_snapshot,
)
from tasks.bluestacks_home_safe_exit import (
    CategoryCoverageProof,
    ExclusionCategory,
    ExclusionRegion,
    ExclusionInventory,
    SafeExitCandidateProposal,
    SafeExitBindingResult,
    bind_bluestacks_home_safe_exit,
    safe_exit_evidence_snapshot,
)
from tasks.supply_depot_vision import (
    bind_supply_depot_building,
    bind_supply_depot_claim_supply,
    recognize_supply_depot_screen,
)

# Navigate-building pan inputs must cross CentralPolicy + SafeActionExecutor.
# Direct runtime.swipe/tap from the PAN disposition path is forbidden.
NAVIGATE_BUILDING_SEMANTIC_ACTION = "HOME_ATLAS_CAMERA_PAN"
NAVIGATE_BUILDING_TARGET_IDENTITY = "home-camera-click-drag"
NAVIGATE_BUILDING_POSTCONDITION = "HOME_BASE_VIEWPORT_PROGRESS"
_VERIFIED_PAN_TRANSPORT_SEAL = object()
CONFIRMED_NOT_DISPATCHED_STATUS = "NON_DISPATCH_AUTHORITY_UNAVAILABLE"

SUPPLY_DEPOT_RADIAL_SEMANTIC_ACTION = "SUPPLY_DEPOT_RADIAL_NAVIGATION"
SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY = "supply-depot-claim-supply-navigation"
SUPPLY_DEPOT_RADIAL_POSTCONDITION = "SUPPLY_DEPOT_SCREEN"
SUPPLY_DEPOT_BUILDING_SEMANTIC_ACTION = "SUPPLY_DEPOT_BUILDING_NAVIGATION"
SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY = "home.building.supply_depot"
SUPPLY_DEPOT_BUILDING_POSTCONDITION = "SUPPLY_DEPOT_RADIAL"
SUPPLY_DEPOT_EXIT_SEMANTIC_ACTION = "SUPPLY_DEPOT_SAFE_EXIT"
SUPPLY_DEPOT_EXIT_TARGET_IDENTITY = "supply-depot-back-arrow"
SUPPLY_DEPOT_EXIT_POSTCONDITION = "HOME_BASE"
SUPPLY_DEPOT_EXIT_TARGET_ROI = (0, 0, 150, 105)
SUPPLY_DEPOT_SAFE_EXIT_CANDIDATE_ROI = (
    int(BLUESTACKS_INTERACTION_ANCHOR[0] - 20),
    int(BLUESTACKS_INTERACTION_ANCHOR[1] - 20),
    int(BLUESTACKS_INTERACTION_ANCHOR[0] + 20),
    int(BLUESTACKS_INTERACTION_ANCHOR[1] + 20),
)
SUPPLY_DEPOT_ROUTE_TASK_ID = "SUPPLY-DEPOT-VERIFIED-ROUTE-INTEGRATION"
_VERIFIED_SUPPLY_DEPOT_RADIAL_TRANSPORT_SEAL = object()
_VERIFIED_SUPPLY_DEPOT_NAVIGATION_TRANSPORT_SEAL = object()


def identity_from_captured(
    captured: CapturedNativeFrame,
    *,
    session_id: str,
    ordinal: int,
    profile_id: str = BLUESTACKS_PROFILE_ID,
    label: str = "",
) -> NativeFrameIdentity:
    """Build a live capture-event identity. semantic_sha256 always comes from frame_digest."""

    height, width = captured.frame.shape[:2]
    return NativeFrameIdentity(
        capture_kind="live",
        runtime_session_id=session_id,
        capture_ordinal=ordinal,
        capture_completed_monotonic=captured.captured_monotonic,
        transport_sha256=captured.sha256,
        semantic_sha256=frame_digest(captured.frame),
        runtime_profile_id=profile_id,
        width=width,
        height=height,
        label=label,
        evidence_path=str(captured.path),
    )


def bluestacks_frame_validation(
    identity: NativeFrameIdentity,
    *,
    package_ok: bool = True,
    orientation_ok: bool = True,
) -> ImmutableFrameValidationObservation:
    """Adapter-owned BlueStacks native validation against the fixed local profile/geometry."""

    validity = FrameValidityState.VALID_NATIVE
    evidence: list[str] = []
    if identity.width != 800 or identity.height != 1280:
        validity = FrameValidityState.WRONG_GEOMETRY
        evidence.append(f"geometry:{identity.width}x{identity.height}")
    elif identity.runtime_profile_id != BLUESTACKS_PROFILE_ID:
        validity = FrameValidityState.WRONG_PROFILE
        evidence.append(f"profile:{identity.runtime_profile_id}")
    elif not package_ok:
        validity = FrameValidityState.WRONG_PACKAGE
        evidence.append("package")
    elif not orientation_ok:
        validity = FrameValidityState.WRONG_ORIENTATION
        evidence.append("orientation")
    else:
        evidence.append("native_800x1280")
    return ImmutableFrameValidationObservation(
        source_frame=identity,
        validity=validity,
        expected_profile_id=BLUESTACKS_PROFILE_ID,
        expected_width=800,
        expected_height=1280,
        expected_platform=BLUESTACKS_PLATFORM,
        package_ok=package_ok,
        orientation_ok=orientation_ok,
        supporting_evidence=tuple(evidence),
    )


def build_navigate_perception_bundle(
    identity: NativeFrameIdentity,
    localization: LocalizationResult,
    binding: BuildingBinding | None,
) -> FramePerceptionBundle:
    """Compose and classify a navigate-building bundle without capturing."""

    bundle = (
        bundle_from_identity(identity)
        .with_frame_validation(bluestacks_frame_validation(identity))
        .with_localization(localization_from_result(identity, localization))
    )
    if binding is not None:
        bundle = bundle.with_building_binding(binding_from_result(identity, binding))
    return classify_and_attach(bundle)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def read_frame(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if not native_frame_guard(frame):
        raise ValueError(f"frame is not native BlueStacks 800x1280: {path}")
    return frame


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _HardwareInput(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput), ("ki", _KeyboardInput), ("hi", _HardwareInput))


class _Input(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (("type", wintypes.DWORD), ("union", _InputUnion))


class BlueStacksHostZoomTransport:
    """Exact-window Ctrl+wheel transport for the positively observed BlueStacks zoom control."""

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _MOUSEEVENTF_WHEEL = 0x0800
    _VK_LCONTROL = 0xA2

    def __init__(
        self,
        window_title: str = "BlueStacks App Player 4",
        *,
        cursor_x: int = 420,
        cursor_y: int = 540,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError("BlueStacks host zoom is Windows-only")
        self.user32 = ctypes.windll.user32
        self.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user32.GetClientRect.restype = wintypes.BOOL
        self.user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        self.user32.ClientToScreen.restype = wintypes.BOOL
        self.user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
        self.user32.SendInput.restype = wintypes.UINT
        self.window_title = window_title
        self.cursor_x = cursor_x
        self.cursor_y = cursor_y

    def _unique_window(self) -> int:
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd, _lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if buffer.value == self.window_title:
                found.append(int(hwnd))
            return True

        self.user32.EnumWindows(callback, 0)
        if len(found) != 1:
            raise RuntimeError(f"expected exactly one {self.window_title!r} window; found {len(found)}")
        return found[0]

    def zoom_out_once(self) -> None:
        hwnd = self._unique_window()
        if not self.user32.SetForegroundWindow(hwnd):
            raise RuntimeError("could not foreground the exact BlueStacks window")
        time.sleep(0.1)
        if int(self.user32.GetForegroundWindow()) != hwnd:
            raise RuntimeError("BlueStacks window is not foreground immediately before zoom")
        rect = wintypes.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("could not read BlueStacks client bounds")
        if not (0 <= self.cursor_x < rect.right - rect.left and 0 <= self.cursor_y < rect.bottom - rect.top):
            raise RuntimeError("configured zoom cursor is outside the BlueStacks client")
        point = wintypes.POINT(self.cursor_x, self.cursor_y)
        if not self.user32.ClientToScreen(hwnd, ctypes.byref(point)):
            raise RuntimeError("could not bind a BlueStacks client point")
        if not self.user32.SetCursorPos(point.x, point.y):
            raise RuntimeError("could not position the zoom gesture inside BlueStacks")
        down = _Input(type=self._INPUT_KEYBOARD, ki=_KeyboardInput(wVk=self._VK_LCONTROL))
        wheel = _Input(
            type=self._INPUT_MOUSE,
            mi=_MouseInput(mouseData=ctypes.c_ulong(-120).value, dwFlags=self._MOUSEEVENTF_WHEEL),
        )
        up = _Input(
            type=self._INPUT_KEYBOARD,
            ki=_KeyboardInput(wVk=self._VK_LCONTROL, dwFlags=self._KEYEVENTF_KEYUP),
        )
        sent = self.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_Input))
        if sent != 1:
            raise RuntimeError("BlueStacks left-Ctrl key-down was incomplete")
        try:
            time.sleep(0.18)
            if not (self.user32.GetAsyncKeyState(self._VK_LCONTROL) & 0x8000):
                raise RuntimeError("left Ctrl is not held immediately before BlueStacks wheel input")
            sent = self.user32.SendInput(1, ctypes.byref(wheel), ctypes.sizeof(_Input))
            if sent != 1:
                raise RuntimeError("BlueStacks wheel-down input was incomplete")
            time.sleep(0.18)
        finally:
            sent = self.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_Input))
            if sent != 1:
                raise RuntimeError("BlueStacks left-Ctrl key-up was incomplete")


class AtlasBuilder:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.paths: list[Path] = []
        self.transforms: list[np.ndarray] = []
        self.metrics: list[dict[str, object]] = []
        self.rejected: list[dict[str, object]] = []

    def add(self, path: Path) -> bool:
        frame = read_frame(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not self.frames:
            self.frames.append(frame)
            self.paths.append(path)
            self.transforms.append(np.eye(3, dtype=np.float64))
            self.metrics.append({"model": "origin", "confidence": 1.0, "residual_px": 0.0, "overlap_ratio": 1.0})
            return True
        candidates = []
        for index, reference in enumerate(self.frames):
            result = register_home_frame(frame, reference)
            if result.accepted and result.transform_candidate_to_reference is not None:
                transform = self.transforms[index] @ result.transform_candidate_to_reference
                candidates.append((result.confidence, -result.residual_px, index, transform, result))
        if not candidates:
            self.rejected.append({"path": str(path), "sha256": digest, "reason": "insufficient_overlap_or_ambiguous_transform"})
            return False
        _, _, reference_index, transform, result = max(candidates)
        selected_center = cv2.perspectiveTransform(np.float32([[[400.0, 640.0]]]), transform)[0, 0]
        closure_errors = []
        for confidence, _negative_residual, _index, alternative, _registration in candidates:
            if confidence < 0.55:
                continue
            alternative_center = cv2.perspectiveTransform(np.float32([[[400.0, 640.0]]]), alternative)[0, 0]
            closure_errors.append(float(np.linalg.norm(selected_center - alternative_center)))
        loop_closure_residual = max(closure_errors, default=0.0)
        if loop_closure_residual > 8.0:
            self.rejected.append(
                {
                    "path": str(path),
                    "sha256": digest,
                    "reason": "conflicting_loop_closure",
                    "loop_closure_residual_px": loop_closure_residual,
                }
            )
            return False
        center = cv2.perspectiveTransform(np.float32([[[400.0, 640.0]]]), transform)[0, 0]
        for existing in self.transforms:
            prior = cv2.perspectiveTransform(np.float32([[[400.0, 640.0]]]), existing)[0, 0]
            if np.linalg.norm(center - prior) < 32:
                self.rejected.append({"path": str(path), "sha256": digest, "reason": "duplicate_viewport"})
                return False
        self.frames.append(frame)
        self.paths.append(path)
        self.transforms.append(transform)
        self.metrics.append(
            {
                "model": result.model,
                "confidence": result.confidence,
                "residual_px": result.residual_px,
                "overlap_ratio": result.overlap_ratio,
                "reference_index": reference_index,
                "inliers": result.inliers,
                "matches": result.matches,
                "loop_closure_residual_px": loop_closure_residual,
            }
        )
        return True

    def write(self, output: Path, *, atlas_id: str, account_layout: str, game_build: str) -> Path:
        if not self.frames:
            raise RuntimeError("atlas has no accepted viewports")
        corners = np.float32([[0, 0], [800, 0], [800, 1280], [0, 1280]])
        projected = [cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2) for matrix in self.transforms]
        all_points = np.vstack(projected)
        minimum = np.floor(all_points.min(axis=0)).astype(int)
        maximum = np.ceil(all_points.max(axis=0)).astype(int)
        shift = np.array([[1.0, 0.0, -minimum[0]], [0.0, 1.0, -minimum[1]], [0.0, 0.0, 1.0]])
        width, height = int(maximum[0] - minimum[0]), int(maximum[1] - minimum[1])
        if width <= 0 or height <= 0 or width * height > 80_000_000:
            raise RuntimeError("atlas bounds are invalid or unexpectedly large")
        weighted = np.zeros((height, width, 3), np.float64)
        weights = np.zeros((height, width), np.float64)
        source_mask = hud_mask().astype(np.float32) / 255.0
        tiles = output / "tiles"
        tiles.mkdir(parents=True, exist_ok=True)
        viewports = []
        for index, (frame, source, transform, metric) in enumerate(zip(self.frames, self.paths, self.transforms, self.metrics), start=1):
            final_transform = shift @ transform
            warped = cv2.warpPerspective(frame, final_transform, (width, height), flags=cv2.INTER_LINEAR)
            warped_mask = cv2.warpPerspective(source_mask, final_transform, (width, height), flags=cv2.INTER_NEAREST)
            weighted += warped.astype(np.float64) * warped_mask[..., None]
            weights += warped_mask
            tile_name = f"viewport-{index:03d}.png"
            shutil.copy2(source, tiles / tile_name)
            polygon = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), final_transform).reshape(-1, 2)
            viewports.append(
                {
                    "viewport_id": f"viewport-{index:03d}",
                    "image_path": f"tiles/{tile_name}",
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "timestamp": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
                    "transform_to_atlas": final_transform.tolist(),
                    "polygon": polygon.tolist(),
                    "overlap_confidence": metric["confidence"],
                    "residual_px": metric["residual_px"],
                    "registration_model": metric["model"],
                    "loop_closure_residual_px": metric.get("loop_closure_residual_px", 0.0),
                    "accepted": True,
                    "rejection_reason": None,
                }
            )
        mosaic = np.zeros((height, width, 3), np.uint8)
        covered = weights > 0
        mosaic[covered] = np.clip(weighted[covered] / weights[covered, None], 0, 255).astype(np.uint8)
        if not cv2.imwrite(str(output / "atlas.png"), mosaic):
            raise RuntimeError("could not write atlas mosaic")
        def contour_polygons(binary: np.ndarray) -> tuple[list[list[list[int]]], list[list[list[int]]]]:
            contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            outside: list[list[list[int]]] = []
            holes: list[list[list[int]]] = []
            hierarchy_rows = hierarchy[0] if hierarchy is not None else []
            for contour_index, contour in enumerate(contours):
                if cv2.contourArea(contour) < 5000:
                    continue
                epsilon = max(2.0, 0.003 * cv2.arcLength(contour, True))
                polygon = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2).tolist()
                if len(hierarchy_rows) and hierarchy_rows[contour_index][3] >= 0:
                    holes.append(polygon)
                else:
                    outside.append(polygon)
            return outside, holes

        registration_coverage, registration_gaps = contour_polygons(covered.astype(np.uint8) * 255)
        actionable_mask = np.zeros((height, width), np.uint8)
        actionable_scene = np.asarray(((138, 150), (650, 150), (650, 1010), (138, 1010)), np.float32).reshape(-1, 1, 2)
        for transform in self.transforms:
            polygon = cv2.perspectiveTransform(actionable_scene, shift @ transform).round().astype(np.int32)
            cv2.fillPoly(actionable_mask, (polygon,), 255)
        coverage, gaps = contour_polygons(actionable_mask)
        payload = {
            "schema_version": 2,
            "atlas_id": atlas_id,
            "atlas_version": utc_stamp(),
            "profile": {
                "platform": BLUESTACKS_PLATFORM,
                "profile_id": BLUESTACKS_PROFILE_ID,
                "viewport": [800, 1280],
                "package": "com.global.ztmslg",
                "dpi": None,
                "renderer": "BlueStacks local renderer; calibration isolated from Bliss",
            },
            "canonical_zoom_identity": "fully_zoomed_out",
            "coordinate_units": "canonical BlueStacks atlas pixels",
            "origin": [0, 0],
            "width": width,
            "height": height,
            "image_path": "atlas.png",
            "game_build_provenance": game_build,
            "account_layout_provenance": account_layout,
            "coverage_polygons": coverage,
            "coverage_gaps": gaps,
            "registration_coverage_polygons": registration_coverage,
            "registration_coverage_gaps": registration_gaps,
            "viewports": viewports,
            "rejected_viewports": self.rejected,
            "buildings": [],
            "production_registration": "NOT_REGISTERED",
            "scheduler_eligibility": False,
        }
        manifest = output / "atlas.json"
        _json(manifest, payload)
        return manifest


def connect_runtime(args, workflow: str) -> LocalBlueStacksRuntime:
    return LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow=workflow,
        execute=bool(getattr(args, "execute", False)),
    )


def command_capture(args) -> int:
    runtime = connect_runtime(args, "home-atlas-capture")
    frame = runtime.capture(args.label)
    print(json.dumps({"status": "captured", "path": str(frame.path), "sha256": frame.sha256, "session": str(runtime.session)}, sort_keys=True))
    return 0


def command_pan(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("pan requires both --execute and --yes")
    runtime = connect_runtime(args, "home-atlas-pan")
    canonical = read_frame(args.canonical_reference)
    source = runtime.capture("pan-source")
    source_zoom = classify_zoom(source.frame, canonical)
    if source_zoom.identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        print(json.dumps({"status": "blocked", "reason": "source_not_canonical_zoom", "zoom": source_zoom.__dict__}, sort_keys=True, default=str))
        return 3
    immediate_before = runtime.capture("pan-immediate-before")
    before_zoom = classify_zoom(immediate_before.frame, canonical)
    if before_zoom.identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        print(json.dumps({"status": "blocked", "reason": "immediate_before_not_canonical_zoom", "zoom": before_zoom.__dict__}, sort_keys=True, default=str))
        return 3
    action_key = f"home-camera-pan-{int(time.time() * 1000)}"
    runtime.swipe(
        immediate_before,
        start=(args.start_x, args.start_y),
        end=(args.end_x, args.end_y),
        action_key=action_key,
        target_identity="home-camera-pan",
    )
    immediate_post = runtime.capture("pan-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("pan-settled")
    registration = register_home_frame(settled.frame, immediate_before.frame)
    settled_zoom = classify_zoom(settled.frame, canonical)
    distance = None
    if registration.accepted and registration.transform_candidate_to_reference is not None:
        distance = float(np.linalg.norm(registration.transform_candidate_to_reference[:2, 2]))
    result = {
        "status": "completed" if distance is not None and distance >= args.minimum_progress else "blocked",
        "reason": "measured_progress" if distance is not None and distance >= args.minimum_progress else "no_or_ambiguous_progress",
        "action_key": action_key,
        "start": [args.start_x, args.start_y],
        "end": [args.end_x, args.end_y],
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "registration": registration.__dict__,
        "settled_zoom": {**settled_zoom.__dict__, "identity": settled_zoom.identity.value},
        "measured_progress_px": distance,
        "session": str(runtime.session),
    }
    _json(runtime.session / "pan-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result["status"] == "completed" else 3


_GRID_GESTURES = {
    # Direction names describe camera/world viewport movement.  The map itself is
    # dragged in the opposite direction with the ordinary in-game click-drag.
    "up": ((450, 260), (450, 440)),
    "down": ((450, 440), (450, 260)),
    # The 150 px horizontal drag yields about 315 world pixels on this profile,
    # retaining roughly 60% full-frame overlap even in feature-sparse rows.
    "left": ((320, 500), (470, 500)),
    "right": ((480, 500), (330, 500)),
}


def _registration_geometry(registration) -> tuple[float | None, float | None]:
    matrix = registration.transform_candidate_to_reference
    if not registration.accepted or matrix is None:
        return None, None
    matrix = np.asarray(matrix, dtype=np.float64)
    scale = float((np.linalg.norm(matrix[:2, 0]) + np.linalg.norm(matrix[:2, 1])) / 2.0)
    movement = float(np.linalg.norm(matrix[:2, 2]))
    return scale, movement


def _canonical_pan_gesture(displacement: np.ndarray) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Choose one proven grid gesture toward an atlas target projection."""

    if abs(float(displacement[0])) >= abs(float(displacement[1])):
        direction = "left" if displacement[0] < 0 else "right"
        axis = "horizontal"
        delta = abs(float(displacement[0]))
    else:
        direction = "up" if displacement[1] < 0 else "down"
        axis = "vertical"
        delta = abs(float(displacement[1]))
    start, end = _GRID_GESTURES[direction]
    base_length = abs(end[0] - start[0]) + abs(end[1] - start[1])
    # Live boundary acquisition measured approximately 2.1 atlas pixels of
    # camera travel per screen pixel dragged.  Shorten only the final approach
    # so recovery cannot oscillate around the canonical center.
    length = min(base_length, max(35, int(round(delta / 2.1))))
    unit_x = 0 if end[0] == start[0] else (1 if end[0] > start[0] else -1)
    unit_y = 0 if end[1] == start[1] else (1 if end[1] > start[1] else -1)
    bounded_end = (start[0] + unit_x * length, start[1] + unit_y * length)
    return axis, start, bounded_end


def bluestacks_home_safe_exit_adapter_profile() -> dict[str, object]:
    """Adapter-owned BlueStacks profile constants for Home safe-exit binding.

    Profile magnitudes remain adapter-owned and are not shared radial semantics.
    Bliss geometry/profile reuse is forbidden. This helper grants no dispatch
    authority and does not connect runtime transport.
    """

    from tasks.bluestacks_home_safe_exit import (
        CONSERVATIVE_GEOMETRY_POLICY,
        bluestacks_safe_exit_profile,
    )

    profile = bluestacks_safe_exit_profile()
    return {
        "platform": profile.platform,
        "profile_id": profile.profile_id,
        "width": profile.width,
        "height": profile.height,
        "default_permitted_safe_space": BLUESTACKS_SAFE_INTERACTION_BOX,
        "geometry_policy": CONSERVATIVE_GEOMETRY_POLICY,
        "authorize_dispatch": False,
        "executable_recovery_coordinate": None,
    }


def bluestacks_session_calibration_adapter_profile() -> dict[str, object]:
    """Adapter-owned BlueStacks original calibration binding for session-local adaptation.

    Extends the existing BlueStacks gesture calibration contract only. Does not create
    a second calibration framework, persist learned scales, grant dispatch authority,
    or connect runtime transport. Bliss calibration remains forbidden.
    """

    from tasks.navigation_session_calibration import (
        assert_no_persistence_api,
        calibration_identity_for,
    )

    assert_no_persistence_api()
    _, calibration = bluestacks_direct_pan_contract()
    return {
        "platform": calibration.platform,
        "profile_id": calibration.profile_id,
        "calibration_id": calibration_identity_for(calibration),
        "camera_px_per_drag_x": calibration.camera_px_per_drag_x,
        "camera_px_per_drag_y": calibration.camera_px_per_drag_y,
        "drag_origin": calibration.drag_origin,
        "drag_bounds": calibration.drag_bounds,
        "authorize_dispatch": False,
        "persistence_authorized": False,
        "capability_grant": None,
    }


def create_bluestacks_session_calibration(navigation_session_id: str):
    """Create a session-local BlueStacks calibration state over the adapter original.

    The returned state preserves the original calibration snapshot and never writes
    learned adjustments to disk or profile storage.
    """

    from tasks.navigation_session_calibration import create_session_calibration

    _, calibration = bluestacks_direct_pan_contract()
    return create_session_calibration(
        navigation_session_id=navigation_session_id,
        original_calibration=calibration,
    )


def gesture_geometry_roi(
    start: tuple[int, int], end: tuple[int, int]
) -> tuple[int, int, int, int]:
    """Encode exact pan gesture geometry as a policy-valid axis-aligned ROI."""

    x0 = min(int(start[0]), int(end[0]))
    y0 = min(int(start[1]), int(end[1]))
    x1 = max(int(start[0]), int(end[0]))
    y1 = max(int(start[1]), int(end[1]))
    if x1 <= x0:
        x1 = min(800, x0 + 1)
    if y1 <= y0:
        y1 = min(1280, y0 + 1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("gesture geometry cannot form a valid in-frame ROI")
    if x0 < 0 or y0 < 0 or x1 > 800 or y1 > 1280:
        raise ValueError("gesture geometry is outside BlueStacks native bounds")
    return (x0, y0, x1, y1)


def reject_direct_navigate_building_transport(*, authorized_token: object | None = None) -> None:
    """Fail closed when navigate-building pan transport bypasses SafeActionExecutor."""

    if authorized_token is not _VERIFIED_PAN_TRANSPORT_SEAL:
        raise RuntimeError("DIRECT_TRANSPORT_BYPASS_REJECTED")


def build_navigate_pan_observation(
    *,
    identity: NativeFrameIdentity,
    drag_start: tuple[int, int],
    drag_end: tuple[int, int],
    capture_completed_monotonic: float | None = None,
) -> Observation:
    """Build a navigation-only Observation for Home Atlas camera pan capability binding."""

    roi = gesture_geometry_roi(drag_start, drag_end)
    mono = (
        float(identity.capture_completed_monotonic)
        if capture_completed_monotonic is None
        else float(capture_completed_monotonic)
    )
    return Observation(
        frame_sha256=str(identity.semantic_sha256),
        capture_completed_monotonic=mono,
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        width=int(identity.width),
        height=int(identity.height),
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity=NAVIGATE_BUILDING_TARGET_IDENTITY,
        target_roi=roi,
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=NAVIGATE_BUILDING_POSTCONDITION,
        evidence_refs=(f"navigate-building:{identity.label or identity.capture_ordinal}",),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )


def build_navigate_pan_policy_request(
    *,
    observation: Observation,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    monotonic_now: float,
    lease_valid: bool = True,
    unresolved_action: bool = False,
    duplicate_action_key: bool = False,
    policy_phase: str = "proposal",
) -> PolicyRequest:
    """Construct an exact PolicyRequest for navigate-building pan capability issuance."""

    return PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        task_mode="supervised_validation",
        semantic_action=NAVIGATE_BUILDING_SEMANTIC_ACTION,
        expected_runtime_profile_id=BLUESTACKS_PROFILE_ID,
        observation=observation,
        monotonic_now=float(monotonic_now),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=15.0,
        lease_owner=lease_owner,
        lease_valid=lease_valid,
        unresolved_action=unresolved_action,
        duplicate_action_key=duplicate_action_key,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=navigation_session_id,
        policy_phase=policy_phase,
    )


def attach_navigate_terminal_reports(
    result: dict[str, object],
    nav_session: NavigationSession,
    *,
    session_calibration: SessionCalibrationState | None = None,
) -> dict[str, object]:
    """Attach read-only observability (and optional calibration) without mutating the ledger."""

    report = report_navigation_session(nav_session)
    result = dict(result)
    result["navigation_observability"] = navigation_observability_snapshot(report)
    result["navigation_observability_json"] = serialize_navigation_observability_report(report)
    result["confirmed_not_dispatched_authority"] = CONFIRMED_NOT_DISPATCHED_STATUS
    if session_calibration is not None:
        result["session_calibration"] = dict(
            report_session_calibration(
                session_calibration,
                navigation_session=nav_session,
                observability_report=report,
            )
        )
    return result


def consider_navigate_pan_calibration(
    session_calibration: SessionCalibrationState,
    *,
    nav_session: NavigationSession,
    plan,
    measured: tuple[float, float],
    progress_px: float,
    progress_reason: str,
    accepted: bool,
    source_identity: NativeFrameIdentity,
    settled_identity: NativeFrameIdentity,
    drag_start: tuple[int, int],
    drag_end: tuple[int, int],
    maximum_pans: int,
) -> SessionCalibrationState:
    """Apply one session-local calibration consideration after a reconciled pan."""

    measurement = SessionCalibrationMeasurement(
        navigation_session_id=nav_session.navigation_session_id,
        platform=BLUESTACKS_PLATFORM,
        profile_id=BLUESTACKS_PROFILE_ID,
        calibration_id=session_calibration.calibration_id,
        calibration_revision=session_calibration.effective.revision,
        source_checkpoint=NavigationCheckpoint.PLAN_CREATED.value,
        destination_checkpoint=NavigationCheckpoint.PAN_RELOCALIZED.value,
        pan_ordinal=int(nav_session.pan_ordinal),
        event_ordinal=int(nav_session.pan_ordinal),
        chronology_ordinal=int(session_calibration.expected_chronology_ordinal),
        requested=tuple(plan.requested_camera_displacement),
        predicted=tuple(plan.predicted_camera_displacement),
        measured=tuple(measured),
        progress_px=float(progress_px),
        progress_reason=str(progress_reason),
        localization_recognized=accepted or progress_reason == "measured_progress",
        localization_ambiguous=progress_reason in {
            "post_pan_localization_failed",
            "post_pan_localization_invalid",
        },
        stale=progress_reason in {"stale_frame", "PERCEPTION_STALE_FRAME"},
        repeated_viewport=progress_reason == "repeated_viewport",
        camera_map_clamp="clamp" in progress_reason or "map_edge" in progress_reason,
        pan_limit_reached=progress_reason == "maximum_pan_count",
        source_capture_ordinal=int(source_identity.capture_ordinal),
        destination_capture_ordinal=int(settled_identity.capture_ordinal),
        drag_vector=(float(drag_end[0] - drag_start[0]), float(drag_end[1] - drag_start[1])),
        maximum_pans=int(maximum_pans),
    )
    return consider_measurement(session_calibration, measurement)


def dispatch_verified_navigate_pan(
    *,
    runtime,
    immediate_before: CapturedNativeFrame,
    identity: NativeFrameIdentity,
    drag_start: tuple[int, int],
    drag_end: tuple[int, int],
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    policy: CentralPolicy,
    store: SafetyStore,
    dry_run: bool = False,
    monotonic_clock: Callable[[], float] | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> tuple[object, object | None, Observation]:
    """Issue one-shot capability and consume it through SafeActionExecutor for a pan.

    Adapter-level runtime.swipe remains reachable only from the executor transport
    callback after capability consumption authorizes dispatch. Direct bypass is rejected.
    """

    pre_observation = build_navigate_pan_observation(
        identity=identity,
        drag_start=drag_start,
        drag_end=drag_end,
    )
    # Keep a distinct prior proposal for executor freshness while preserving the
    # real capture digest used by capability binding and the action journal.
    proposal_observation = replace(
        pre_observation,
        capture_completed_monotonic=pre_observation.capture_completed_monotonic - 0.05,
    )

    # Live captures use the process monotonic clock; offline callers inject a
    # capture-relative clock when their capture timestamps are synthetic.
    mono_clock = monotonic_clock or time.monotonic
    wall = wall_clock or time.time
    now = float(mono_clock())
    issue_request = build_navigate_pan_policy_request(
        observation=pre_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=now,
    )
    issued = policy.issue_capability(issue_request)
    if not issued.authorized or issued.capability is None:
        return issued, None, pre_observation

    def transport(_intent) -> TransportResult:
        reject_direct_navigate_building_transport(authorized_token=_VERIFIED_PAN_TRANSPORT_SEAL)
        if dry_run:
            raise RuntimeError("DRY_RUN_TRANSPORT_MUST_NOT_RUN")
        runtime.swipe(
            immediate_before,
            start=drag_start,
            end=drag_end,
            action_key=action_key,
            target_identity=NAVIGATE_BUILDING_TARGET_IDENTITY,
        )
        return TransportResult(True, "HOME_ATLAS_PAN_DISPATCHED")

    def recapture() -> Observation:
        return pre_observation

    def post_observe():
        return (
            replace(
                pre_observation,
                frame_sha256=("f" if pre_observation.frame_sha256[0] != "f" else "e") * 64,
                capture_completed_monotonic=pre_observation.capture_completed_monotonic + 0.1,
                target_identity=None,
                target_roi=None,
            ),
        )

    def reconcile(_intent, observation: Observation) -> bool:
        # Transport-layer confirmation only; semantic pan progress is reconcile_pan.
        return observation.source_state == "HOME_BASE"

    executor = SafeActionExecutor(
        store,
        policy,
        lease_owner,
        mono_clock,
        transport,
        recapture,
        post_observe,
        reconcile,
        wall_clock=wall,
        max_pre_dispatch_attempts=1,
    )
    execute_request = build_navigate_pan_policy_request(
        observation=proposal_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    result = executor.execute(execute_request, issued.capability, dry_run=dry_run)
    return issued, result, pre_observation


def build_supply_depot_radial_semantics(
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
) -> HomeRadialSemantics:
    """Build exact same-capture Supply Depot radial semantics.

    The visual label remains Claim Supply, while the typed semantic contract
    explicitly limits the control to opening the zero-cost facility screen.
    """

    if binding.building_id != "home.building.supply_depot":
        raise PerceptionBundleError("RADIAL_OWNER_IDENTITY_MISMATCH")
    if binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    owner = OwningFacilityObservation(
        source_frame=identity,
        facility_semantic_id="home.building.supply_depot",
        recognition_state=RecognitionState.RECOGNIZED,
        recognition_confidence=float(binding.confidence),
        ambiguity_state=RadialAmbiguityState.NONE,
        supporting_evidence=(
            "current-frame Supply Depot radial owner",
            "navigation-only facility entry",
        ),
    )
    control = RadialControlObservation(
        source_frame=identity,
        control_id=SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
        label="Claim Supply",
        role=ControlRole.CLAIM,
        recognition_state=RecognitionState.RECOGNIZED,
        recognition_confidence=float(binding.confidence),
        actionability_state=ActionabilityState.ACTIONABLE,
        actionability_reason="navigation_only_facility_entry",
        expected_successors=("facility.screen",),
        forbidden_successors=("facility.claim_supply",),
        owner_facility_semantic_id="home.building.supply_depot",
        ambiguity_state=RadialAmbiguityState.NONE,
        supporting_evidence=tuple(binding.semantic_evidence),
        metadata={
            "historical_control_identity": SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
            "cost": "none",
            "consequence": "navigation_only",
        },
    )
    return HomeRadialSemantics(
        source_frame=identity,
        radial_identity="home.radial.supply_depot",
        recognition_state=RecognitionState.RECOGNIZED,
        recognition_confidence=float(binding.confidence),
        owning_facility=owner,
        controls=(control,),
        ambiguity_state=RadialAmbiguityState.NONE,
        supporting_evidence=(
            "same-capture Supply Depot radial",
            "Claim Supply label is navigation-only",
        ),
        metadata={"route": "supply-depot-radial"},
    )


def build_supply_depot_radial_perception_bundle(
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
) -> FramePerceptionBundle:
    """Compose immutable native validation and typed radial semantics."""

    semantics = build_supply_depot_radial_semantics(identity, binding)
    bundle = (
        bundle_from_identity(identity)
        .with_frame_validation(bluestacks_frame_validation(identity))
        .with_radial(
            ImmutableRadialObservation(
                source_frame=identity,
                facility_identity="home.building.supply_depot",
                confidence=semantics.recognition_confidence,
                supporting_evidence=semantics.supporting_evidence,
                semantics=semantics,
            )
        )
    )
    return classify_and_attach(bundle)


def build_supply_depot_screen_perception_bundle(
    identity: NativeFrameIdentity,
    successor,
) -> FramePerceptionBundle:
    """Compose the semantic Supply Depot successor on its own capture event."""

    if successor.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    return classify_and_attach(
        bundle_from_identity(identity)
        .with_frame_validation(bluestacks_frame_validation(identity))
        .with_recognized_screen(
            ImmutableRecognizedScreenObservation(
                source_frame=identity,
                screen_identity="facility.supply_depot",
                confidence=0.99 if successor.recognized else 0.0,
                supporting_evidence=(
                    "Supply Depot title recognition"
                    if successor.recognized
                    else successor.ambiguity,
                ),
            )
        )
    )


def build_supply_depot_safe_exit_probe(
    identity: NativeFrameIdentity,
    *,
    building_binding: BuildingBinding | None = None,
    radial_binding: BuildingBinding | None = None,
) -> SafeExitBindingResult:
    """Evaluate a real same-capture exterior-close candidate without authority.

    The candidate is a known map-space close target around the existing
    BlueStacks interaction anchor. Every exclusion category is populated from
    fixed HUD geometry or the route's positively recognized current-frame
    bindings. A category is marked empty only when the corresponding recognizer
    explicitly found no such control on this frame.
    """

    if building_binding is not None and building_binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    if radial_binding is not None and radial_binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    bound = radial_binding or building_binding
    if bound is None:
        raise PerceptionBundleError("SAFE_EXIT_SOURCE_BINDING_REQUIRED")

    def region(
        category: ExclusionCategory,
        region_id: str,
        box: tuple[int, int, int, int],
        *evidence: str,
    ) -> ExclusionRegion:
        return ExclusionRegion(
            source_frame=identity,
            category=category,
            region_id=region_id,
            box=box,
            supporting_evidence=tuple(evidence),
        )

    hud_regions = tuple(
        region(
            ExclusionCategory.HUD,
            f"fixed-hud-{index}",
            tuple(rect),
            "Home Atlas fixed HUD exclusion",
        )
        for index, rect in enumerate(HUD_MASK_RECTS)
    )
    building_regions = (
        (
            region(
                ExclusionCategory.BUILDINGS,
                "supply-depot-building-bound",
                tuple(building_binding.target_roi),
                "same-capture Supply Depot building binding",
            ),
        )
        if building_binding is not None
        else ()
    )
    radial_regions = (
        (
            region(
                ExclusionCategory.RADIAL_CONTROLS,
                "supply-depot-radial-control-bound",
                tuple(radial_binding.target_roi),
                "same-capture Supply Depot radial binding",
            ),
        )
        if radial_binding is not None
        else ()
    )
    semantic_regions = (
        region(
            ExclusionCategory.SEMANTIC_TARGETS,
            "supply-depot-semantic-target-bound",
            tuple(bound.target_roi),
            "same-capture Supply Depot route target",
        ),
    )
    interactive_regions = (
        region(
            ExclusionCategory.KNOWN_INTERACTIVE_REGIONS,
            "supply-depot-known-interactive-target",
            tuple(bound.target_roi),
            "same-capture route interaction target",
        ),
    )
    coverage_data = {
        ExclusionCategory.HUD: (hud_regions, False),
        ExclusionCategory.BUILDINGS: (
            building_regions,
            building_binding is None,
        ),
        ExclusionCategory.RADIAL_CONTROLS: (
            radial_regions,
            radial_binding is None,
        ),
        ExclusionCategory.SEMANTIC_TARGETS: (semantic_regions, False),
        ExclusionCategory.KNOWN_INTERACTIVE_REGIONS: (interactive_regions, False),
    }
    coverage = tuple(
        CategoryCoverageProof(
            source_frame=identity,
            category=category,
            regions=regions,
            observed_empty=observed_empty,
        )
        for category, (regions, observed_empty) in sorted(
            coverage_data.items(), key=lambda item: item[0].value
        )
    )
    inventory = ExclusionInventory(source_frame=identity, coverage=coverage)
    return bind_bluestacks_home_safe_exit(
        source_frame=identity,
        permitted_safe_space=BLUESTACKS_SAFE_INTERACTION_BOX,
        exclusion_inventory=inventory,
        proposed_candidates=(
            SafeExitCandidateProposal(
                source_frame=identity,
                candidate_id="supply-depot-exterior-close-anchor",
                box=SUPPLY_DEPOT_SAFE_EXIT_CANDIDATE_ROI,
            ),
        ),
        metadata={
            "route": "supply-depot-radial",
            "dispatch_authority": "none",
            "candidate_proposals": "known_map_space_exterior_close_anchor",
            "building_binding": "bound" if building_binding is not None else "unavailable",
            "radial_binding": "bound" if radial_binding is not None else "unavailable",
        },
    )


def reject_direct_supply_depot_radial_transport(
    *,
    authorized_token: object | None = None,
) -> None:
    """Fail closed when radial transport bypasses the sealed executor callback."""

    if authorized_token is not _VERIFIED_SUPPLY_DEPOT_RADIAL_TRANSPORT_SEAL:
        raise RuntimeError("DIRECT_TRANSPORT_BYPASS_REJECTED")


def reject_direct_supply_depot_navigation_transport(
    *,
    authorized_token: object | None = None,
) -> None:
    """Fail closed for every non-radial Supply Depot navigation transport."""

    if authorized_token is not _VERIFIED_SUPPLY_DEPOT_NAVIGATION_TRANSPORT_SEAL:
        raise RuntimeError("DIRECT_TRANSPORT_BYPASS_REJECTED")


def bind_supply_depot_home_building(
    frame: np.ndarray,
    *,
    atlas_path: Path | None,
    source_frame: NativeFrameIdentity,
) -> BuildingBinding | None:
    """Bind the Supply Depot building only from a positively recognized Home frame."""

    if atlas_path is None:
        return None
    try:
        atlas = load_home_atlas(atlas_path)
        localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
        localization = localizer.localize(frame)
        if (
            not localization.recognized
            or localization.frame_sha256 != source_frame.semantic_sha256
        ):
            return None
        building = atlas.lookup_building("home.building.supply_depot")
        return bind_supply_depot_building(
            frame,
            localization,
            building,
            source_frame=source_frame,
        )
    except (KeyError, OSError, ValueError):
        return None


def recognize_supply_depot_home_successor(
    frame: np.ndarray,
    *,
    atlas_path: Path | None,
    source_frame: NativeFrameIdentity,
):
    """Return a fresh Home localization associated with one settled capture.

    Safe-exit may leave Home at non-canonical zoom. Atlas localization requires
    fully_zoomed_out for recognized=True, but a high-confidence ZOOMED_IN Home
    scene that is no longer the Supply Depot facility still verifies HOME_BASE.
    """

    if atlas_path is None:
        return None
    try:
        facility = recognize_supply_depot_screen(
            frame,
            source_frame=source_frame,
        )
    except (OSError, ValueError, TypeError):
        facility = None
    if facility is not None and bool(getattr(facility, "recognized", False)):
        return None
    try:
        atlas = load_home_atlas(atlas_path)
        localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
        localization = localizer.localize(frame)
    except (OSError, ValueError):
        return None
    if localization.frame_sha256 != source_frame.semantic_sha256:
        return None
    if localization.recognized:
        return localization
    if (
        localization.zoom_identity is ZoomIdentity.ZOOMED_IN
        and float(localization.confidence) >= 0.85
        and not localization.overlay
        and not localization.stale
    ):
        return replace(localization, recognized=True)
    return None


def build_supply_depot_radial_observation(
    *,
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
) -> Observation:
    """Build the navigation-only policy observation from the current bundle."""

    if binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    return Observation(
        frame_sha256=str(identity.semantic_sha256),
        capture_completed_monotonic=float(identity.capture_completed_monotonic),
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        width=int(identity.width),
        height=int(identity.height),
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity=SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
        target_roi=tuple(binding.target_roi),
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=SUPPLY_DEPOT_RADIAL_POSTCONDITION,
        evidence_refs=(
            "supply-depot-radial:same-capture",
            SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
        ),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
        control_class="CLAIM",
    )


def build_supply_depot_building_observation(
    *,
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
) -> Observation:
    """Build the navigation-only Home building-entry observation."""

    if binding.building_id != SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY:
        raise PerceptionBundleError("BUILDING_OWNER_IDENTITY_MISMATCH")
    if binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
    return Observation(
        frame_sha256=str(identity.semantic_sha256),
        capture_completed_monotonic=float(identity.capture_completed_monotonic),
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        width=int(identity.width),
        height=int(identity.height),
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity=SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY,
        target_roi=tuple(binding.target_roi),
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=SUPPLY_DEPOT_BUILDING_POSTCONDITION,
        evidence_refs=(
            "supply-depot-building:same-capture",
            SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY,
        ),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
        control_class="GO",
    )


def build_supply_depot_exit_observation(
    *,
    identity: NativeFrameIdentity,
    recognized_screen: bool,
) -> Observation:
    """Build the navigation-only facility Back-arrow observation."""

    return Observation(
        frame_sha256=str(identity.semantic_sha256),
        capture_completed_monotonic=float(identity.capture_completed_monotonic),
        runtime_profile_id=BLUESTACKS_PROFILE_ID,
        width=int(identity.width),
        height=int(identity.height),
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="SUPPLY_DEPOT_SCREEN",
        overlay_state="none_observed",
        target_identity=SUPPLY_DEPOT_EXIT_TARGET_IDENTITY,
        target_roi=SUPPLY_DEPOT_EXIT_TARGET_ROI,
        recognized=bool(recognized_screen),
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=SUPPLY_DEPOT_EXIT_POSTCONDITION,
        evidence_refs=(
            "supply-depot-exit:same-capture",
            SUPPLY_DEPOT_EXIT_TARGET_IDENTITY,
        ),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
        control_class="CLOSE",
    )


def build_supply_depot_radial_policy_request(
    *,
    observation: Observation,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    monotonic_now: float,
    lease_valid: bool = True,
    unresolved_action: bool = False,
    duplicate_action_key: bool = False,
    policy_phase: str = "proposal",
) -> PolicyRequest:
    """Construct the exact navigation-only Supply Depot radial request."""

    return PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        task_mode="supervised_validation",
        semantic_action=SUPPLY_DEPOT_RADIAL_SEMANTIC_ACTION,
        expected_runtime_profile_id=BLUESTACKS_PROFILE_ID,
        observation=observation,
        monotonic_now=float(monotonic_now),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=15.0,
        lease_owner=lease_owner,
        lease_valid=lease_valid,
        unresolved_action=unresolved_action,
        duplicate_action_key=duplicate_action_key,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=navigation_session_id,
        policy_phase=policy_phase,
    )


def build_supply_depot_building_policy_request(
    *,
    observation: Observation,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    monotonic_now: float,
    lease_valid: bool = True,
    unresolved_action: bool = False,
    duplicate_action_key: bool = False,
    policy_phase: str = "proposal",
) -> PolicyRequest:
    return PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        task_mode="supervised_validation",
        semantic_action=SUPPLY_DEPOT_BUILDING_SEMANTIC_ACTION,
        expected_runtime_profile_id=BLUESTACKS_PROFILE_ID,
        observation=observation,
        monotonic_now=float(monotonic_now),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=15.0,
        lease_owner=lease_owner,
        lease_valid=lease_valid,
        unresolved_action=unresolved_action,
        duplicate_action_key=duplicate_action_key,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=navigation_session_id,
        policy_phase=policy_phase,
    )


def build_supply_depot_exit_policy_request(
    *,
    observation: Observation,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    monotonic_now: float,
    lease_valid: bool = True,
    unresolved_action: bool = False,
    duplicate_action_key: bool = False,
    policy_phase: str = "proposal",
) -> PolicyRequest:
    return PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        task_mode="supervised_validation",
        semantic_action=SUPPLY_DEPOT_EXIT_SEMANTIC_ACTION,
        expected_runtime_profile_id=BLUESTACKS_PROFILE_ID,
        observation=observation,
        monotonic_now=float(monotonic_now),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=15.0,
        lease_owner=lease_owner,
        lease_valid=lease_valid,
        unresolved_action=unresolved_action,
        duplicate_action_key=duplicate_action_key,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=navigation_session_id,
        policy_phase=policy_phase,
    )


def dispatch_verified_supply_depot_radial_tap(
    *,
    runtime,
    immediate_before: CapturedNativeFrame,
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    policy: CentralPolicy,
    store: SafetyStore,
    settle_seconds: float = 0.0,
    dry_run: bool = False,
    monotonic_clock: Callable[[], float] | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> tuple[object, object | None, Observation, dict[str, object]]:
    """Issue and consume one capability for the navigation-only radial tap.

    The transport callback is the only place that can reach ``runtime.tap``.
    The executor recaptures/revalidates through the same issuance-frame
    observation, while the proposal intentionally uses the same digest with an
    earlier monotonic value.
    """

    pre_observation = build_supply_depot_radial_observation(
        identity=identity,
        binding=binding,
    )
    proposal_observation = replace(
        pre_observation,
        capture_completed_monotonic=(
            pre_observation.capture_completed_monotonic - 0.05
        ),
    )
    mono_clock = monotonic_clock or time.monotonic
    wall = wall_clock or time.time
    now = float(mono_clock())
    issue_request = build_supply_depot_radial_policy_request(
        observation=pre_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=now,
    )
    issued = policy.issue_capability(issue_request)
    telemetry: dict[str, object] = {
        "requested": True,
        "authorized": bool(issued.authorized and issued.capability is not None),
        "dispatched": False,
        "transport_observed": False,
        "verified": False,
        "completed": False,
    }
    if not issued.authorized or issued.capability is None:
        return issued, None, pre_observation, telemetry

    def transport(_intent) -> TransportResult:
        reject_direct_supply_depot_radial_transport(
            authorized_token=_VERIFIED_SUPPLY_DEPOT_RADIAL_TRANSPORT_SEAL
        )
        if dry_run:
            raise RuntimeError("DRY_RUN_TRANSPORT_MUST_NOT_RUN")
        runtime.tap(
            immediate_before,
            target_identity=SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
            target_roi=tuple(binding.target_roi),
            action_key=action_key,
            consequential=False,
        )
        telemetry["dispatched"] = True
        return TransportResult(True, "SUPPLY_DEPOT_RADIAL_DISPATCHED")

    def recapture() -> Observation:
        # The executor's immediate recapture is the issuance-frame observation.
        # Its monotonic clock and exact capability binding still run at the
        # final pre_dispatch boundary.
        return pre_observation

    def post_observe():
        immediate_post = runtime.capture("radial-immediate-post")
        immediate_post_ordinal = getattr(runtime, "ordinal", None)
        if immediate_post_ordinal is None:
            immediate_post_ordinal = identity.capture_ordinal + 1
        immediate_post_identity = identity_from_captured(
            immediate_post,
            session_id=str(runtime.session),
            ordinal=int(immediate_post_ordinal),
            label="radial-immediate-post",
        )
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        settled = runtime.capture("radial-settled")
        settled_ordinal = getattr(runtime, "ordinal", None)
        if settled_ordinal is None:
            settled_ordinal = int(immediate_post_ordinal) + 1
        settled_identity = identity_from_captured(
            settled,
            session_id=str(runtime.session),
            ordinal=int(settled_ordinal),
            label="radial-settled",
        )
        successor = recognize_supply_depot_screen(
            settled.frame,
            source_frame=settled_identity,
        )
        settled_bundle = build_supply_depot_screen_perception_bundle(
            settled_identity,
            successor,
        )
        telemetry.update(
            {
                "immediate_post": immediate_post,
                "immediate_post_identity": immediate_post_identity,
                "settled": settled,
                "settled_identity": settled_identity,
                "successor": successor,
                "settled_perception_bundle": settled_bundle,
                "verified": bool(successor.recognized),
            }
        )
        return (
            replace(
                pre_observation,
                frame_sha256=settled_identity.semantic_sha256,
                capture_completed_monotonic=(
                    settled_identity.capture_completed_monotonic
                ),
                source_state=(
                    "SUPPLY_DEPOT_SCREEN"
                    if successor.recognized
                    else "UNKNOWN"
                ),
                target_identity=None,
                target_roi=None,
                recognized=bool(successor.recognized),
                expected_postcondition=SUPPLY_DEPOT_RADIAL_POSTCONDITION,
                evidence_refs=("supply-depot-screen-successor",),
            ),
        )

    def reconcile(_intent, observation: Observation) -> bool:
        successor = telemetry.get("successor")
        return bool(
            successor is not None
            and getattr(successor, "recognized", False)
            and observation.frame_sha256
            == getattr(telemetry.get("settled_identity"), "semantic_sha256", "")
        )

    executor = SafeActionExecutor(
        store,
        policy,
        lease_owner,
        mono_clock,
        transport,
        recapture,
        post_observe,
        reconcile,
        wall_clock=wall,
        max_pre_dispatch_attempts=1,
    )
    execute_request = build_supply_depot_radial_policy_request(
        observation=proposal_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    execution = executor.execute(
        execute_request,
        issued.capability,
        dry_run=dry_run,
    )
    telemetry["transport_observed"] = bool(execution.transport_calls > 0)
    telemetry["completed"] = bool(
        execution.status is ActionStatus.CONFIRMED
        and telemetry.get("verified") is True
    )
    return issued, execution, pre_observation, telemetry


def dispatch_verified_supply_depot_building_tap(
    *,
    runtime,
    immediate_before: CapturedNativeFrame,
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    policy: CentralPolicy,
    store: SafetyStore,
    settle_seconds: float = 0.0,
    dry_run: bool = False,
    monotonic_clock: Callable[[], float] | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> tuple[object, object | None, Observation, dict[str, object]]:
    """Open the Supply Depot radial through the verified executor path."""

    pre_observation = build_supply_depot_building_observation(
        identity=identity,
        binding=binding,
    )
    proposal_observation = replace(
        pre_observation,
        capture_completed_monotonic=(
            pre_observation.capture_completed_monotonic - 0.05
        ),
    )
    mono_clock = monotonic_clock or time.monotonic
    wall = wall_clock or time.time
    issue_request = build_supply_depot_building_policy_request(
        observation=pre_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    issued = policy.issue_capability(issue_request)
    telemetry: dict[str, object] = {
        "requested": True,
        "authorized": bool(issued.authorized and issued.capability is not None),
        "dispatched": False,
        "transport_observed": False,
        "verified": False,
        "completed": False,
    }
    if not issued.authorized or issued.capability is None:
        return issued, None, pre_observation, telemetry

    def transport(_intent) -> TransportResult:
        reject_direct_supply_depot_navigation_transport(
            authorized_token=_VERIFIED_SUPPLY_DEPOT_NAVIGATION_TRANSPORT_SEAL
        )
        if dry_run:
            raise RuntimeError("DRY_RUN_TRANSPORT_MUST_NOT_RUN")
        runtime.tap(
            immediate_before,
            target_identity=SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY,
            target_roi=tuple(binding.target_roi),
            action_key=action_key,
            consequential=False,
        )
        telemetry["dispatched"] = True
        return TransportResult(True, "SUPPLY_DEPOT_BUILDING_DISPATCHED")

    def recapture() -> Observation:
        return pre_observation

    def post_observe():
        immediate_post = runtime.capture("supply-depot-building-immediate-post")
        immediate_post_ordinal = getattr(runtime, "ordinal", None)
        if immediate_post_ordinal is None:
            immediate_post_ordinal = identity.capture_ordinal + 1
        immediate_post_identity = identity_from_captured(
            immediate_post,
            session_id=str(runtime.session),
            ordinal=int(immediate_post_ordinal),
            label="supply-depot-building-immediate-post",
        )
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        settled = runtime.capture("supply-depot-radial-settled")
        settled_ordinal = getattr(runtime, "ordinal", None)
        if settled_ordinal is None:
            settled_ordinal = int(immediate_post_ordinal) + 1
        settled_identity = identity_from_captured(
            settled,
            session_id=str(runtime.session),
            ordinal=int(settled_ordinal),
            label="supply-depot-radial-settled",
        )
        radial_binding = bind_supply_depot_claim_supply(
            settled.frame,
            source_frame=settled_identity,
        )
        radial_bundle = None
        if (
            radial_binding is not None
            and radial_binding.frame_sha256 == settled_identity.semantic_sha256
        ):
            radial_bundle = build_supply_depot_radial_perception_bundle(
                settled_identity,
                radial_binding,
            )
        telemetry.update(
            {
                "immediate_post": immediate_post,
                "immediate_post_identity": immediate_post_identity,
                "settled": settled,
                "settled_identity": settled_identity,
                "radial_binding": radial_binding,
                "settled_perception_bundle": radial_bundle,
                "verified": radial_bundle is not None,
            }
        )
        return (
            replace(
                pre_observation,
                frame_sha256=settled_identity.semantic_sha256,
                capture_completed_monotonic=settled_identity.capture_completed_monotonic,
                source_state="HOME_BASE",
                target_identity=None,
                target_roi=None,
                recognized=radial_bundle is not None,
                expected_postcondition=SUPPLY_DEPOT_BUILDING_POSTCONDITION,
                evidence_refs=("supply-depot-radial-successor",),
            ),
        )

    def reconcile(_intent, observation: Observation) -> bool:
        radial_binding = telemetry.get("radial_binding")
        return bool(
            telemetry.get("verified") is True
            and radial_binding is not None
            and observation.frame_sha256
            == getattr(telemetry.get("settled_identity"), "semantic_sha256", "")
        )

    executor = SafeActionExecutor(
        store,
        policy,
        lease_owner,
        mono_clock,
        transport,
        recapture,
        post_observe,
        reconcile,
        wall_clock=wall,
        max_pre_dispatch_attempts=1,
    )
    execute_request = build_supply_depot_building_policy_request(
        observation=proposal_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    execution = executor.execute(
        execute_request,
        issued.capability,
        dry_run=dry_run,
    )
    telemetry["transport_observed"] = bool(execution.transport_calls > 0)
    telemetry["completed"] = bool(
        execution.status is ActionStatus.CONFIRMED
        and telemetry.get("verified") is True
    )
    return issued, execution, pre_observation, telemetry


def dispatch_verified_supply_depot_exit_tap(
    *,
    runtime,
    immediate_before: CapturedNativeFrame,
    identity: NativeFrameIdentity,
    action_id: str,
    action_key: str,
    task_id: str,
    navigation_session_id: str,
    lease_owner: str,
    policy: CentralPolicy,
    store: SafetyStore,
    home_successor_recognizer: Callable[..., object | None],
    settle_seconds: float = 0.0,
    dry_run: bool = False,
    monotonic_clock: Callable[[], float] | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> tuple[object, object | None, Observation, dict[str, object]]:
    """Return from the facility through a capability-bound Back-arrow tap."""

    pre_observation = build_supply_depot_exit_observation(
        identity=identity,
        recognized_screen=True,
    )
    proposal_observation = replace(
        pre_observation,
        capture_completed_monotonic=(
            pre_observation.capture_completed_monotonic - 0.05
        ),
    )
    mono_clock = monotonic_clock or time.monotonic
    wall = wall_clock or time.time
    issue_request = build_supply_depot_exit_policy_request(
        observation=pre_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    issued = policy.issue_capability(issue_request)
    telemetry: dict[str, object] = {
        "requested": True,
        "authorized": bool(issued.authorized and issued.capability is not None),
        "dispatched": False,
        "transport_observed": False,
        "verified": False,
        "completed": False,
    }
    if not issued.authorized or issued.capability is None:
        return issued, None, pre_observation, telemetry

    def transport(_intent) -> TransportResult:
        reject_direct_supply_depot_navigation_transport(
            authorized_token=_VERIFIED_SUPPLY_DEPOT_NAVIGATION_TRANSPORT_SEAL
        )
        if dry_run:
            raise RuntimeError("DRY_RUN_TRANSPORT_MUST_NOT_RUN")
        runtime.tap(
            immediate_before,
            target_identity=SUPPLY_DEPOT_EXIT_TARGET_IDENTITY,
            target_roi=SUPPLY_DEPOT_EXIT_TARGET_ROI,
            action_key=action_key,
            consequential=False,
        )
        telemetry["dispatched"] = True
        return TransportResult(True, "SUPPLY_DEPOT_EXIT_DISPATCHED")

    def recapture() -> Observation:
        return pre_observation

    def post_observe():
        immediate_post = runtime.capture("supply-depot-exit-immediate-post")
        immediate_post_ordinal = getattr(runtime, "ordinal", None)
        if immediate_post_ordinal is None:
            immediate_post_ordinal = identity.capture_ordinal + 1
        immediate_post_identity = identity_from_captured(
            immediate_post,
            session_id=str(runtime.session),
            ordinal=int(immediate_post_ordinal),
            label="supply-depot-exit-immediate-post",
        )
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        settled = runtime.capture("supply-depot-home-settled")
        settled_ordinal = getattr(runtime, "ordinal", None)
        if settled_ordinal is None:
            settled_ordinal = int(immediate_post_ordinal) + 1
        settled_identity = identity_from_captured(
            settled,
            session_id=str(runtime.session),
            ordinal=int(settled_ordinal),
            label="supply-depot-home-settled",
        )
        home_localization = home_successor_recognizer(
            settled.frame,
            source_frame=settled_identity,
        )
        home_bundle = None
        if home_localization is not None and getattr(
            home_localization, "recognized", False
        ):
            try:
                home_bundle = classify_and_attach(
                    bundle_from_identity(settled_identity)
                    .with_frame_validation(
                        bluestacks_frame_validation(settled_identity)
                    )
                    .with_localization(
                        localization_from_result(
                            settled_identity, home_localization
                        )
                    )
                )
            except (PerceptionBundleError, ValueError, AttributeError):
                home_bundle = None
        telemetry.update(
            {
                "immediate_post": immediate_post,
                "immediate_post_identity": immediate_post_identity,
                "settled": settled,
                "settled_identity": settled_identity,
                "home_localization": home_localization,
                "settled_perception_bundle": home_bundle,
                "verified": bool(
                    home_localization is not None
                    and getattr(home_localization, "recognized", False)
                ),
            }
        )
        return (
            replace(
                pre_observation,
                frame_sha256=settled_identity.semantic_sha256,
                capture_completed_monotonic=settled_identity.capture_completed_monotonic,
                source_state="HOME_BASE",
                target_identity=None,
                target_roi=None,
                recognized=bool(
                    home_localization is not None
                    and getattr(home_localization, "recognized", False)
                ),
                expected_postcondition=SUPPLY_DEPOT_EXIT_POSTCONDITION,
                evidence_refs=("home-semantic-successor",),
            ),
        )

    def reconcile(_intent, observation: Observation) -> bool:
        return bool(
            telemetry.get("verified") is True
            and observation.frame_sha256
            == getattr(telemetry.get("settled_identity"), "semantic_sha256", "")
        )

    executor = SafeActionExecutor(
        store,
        policy,
        lease_owner,
        mono_clock,
        transport,
        recapture,
        post_observe,
        reconcile,
        wall_clock=wall,
        max_pre_dispatch_attempts=1,
    )
    execute_request = build_supply_depot_exit_policy_request(
        observation=proposal_observation,
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
        navigation_session_id=navigation_session_id,
        lease_owner=lease_owner,
        monotonic_now=float(mono_clock()),
    )
    execution = executor.execute(
        execute_request,
        issued.capability,
        dry_run=dry_run,
    )
    telemetry["transport_observed"] = bool(execution.transport_calls > 0)
    telemetry["completed"] = bool(
        execution.status is ActionStatus.CONFIRMED
        and telemetry.get("verified") is True
    )
    return issued, execution, pre_observation, telemetry


def bluestacks_direct_pan_contract() -> tuple[SafeInteractionRegion, GestureCalibration]:
    """Return only the empirically measured local BlueStacks geometry.

    ViewportPlanningPolicy magnitudes are justified from the accepted safe region
    (145,180)-(650,1010) and radial-exterior-close contract (25 px building clearance,
    scan band above radial controls / away from HUD). They are heuristics derived from
    those contracts, not freshly remeasured in this offline task.
    """

    planning_policy = ViewportPlanningPolicy(
        # Asymmetric: radial menus open mostly downward/sideways from facility labels.
        radial_margin_up_px=40.0,
        radial_margin_down_px=120.0,
        radial_margin_left_px=70.0,
        radial_margin_right_px=70.0,
        recovery_clearance_px=25.0,
        recovery_zone_half_size_px=10.0,
        recovery_scan_step_px=25.0,
        # Exterior-close scan band: x in [max(sx0+70,220), min(sx1-70,575)],
        # y in [max(sy0+70,250), min(sy1,650)] inside safe (145,180)-(650,1010).
        recovery_search_inset_left_px=75.0,
        recovery_search_inset_top_px=70.0,
        recovery_search_inset_right_px=75.0,
        recovery_search_inset_bottom_px=360.0,
        action_body_margin_px=8.0,
        label_inset_px=12.0,
        candidate_step_px=50.0,
        max_candidates=48,
        map_edge_soft_margin_px=40.0,
    )
    safe = SafeInteractionRegion(
        "home-default",
        BLUESTACKS_SAFE_INTERACTION_BOX,
        BLUESTACKS_INTERACTION_ANCHOR,
        fixed_hud_masks=((0, 0, 800, 150), (0, 150, 138, 1020), (650, 150, 800, 1020), (0, 1020, 800, 1280)),
        planning_policy=planning_policy,
    )
    calibration = GestureCalibration(
        platform=BLUESTACKS_PLATFORM,
        profile_id=BLUESTACKS_PROFILE_ID,
        drag_origin=(450, 500),
        drag_bounds=(250, 250, 650, 950),
        camera_px_per_drag_x=2.1,
        camera_px_per_drag_y=2.1,
        minimum_drag_px=35.0,
        maximum_drag_x=150.0,
        maximum_drag_y=180.0,
        minimum_progress_px=8.0,
    )
    return safe, calibration


def command_scan_grid(args) -> int:
    """Acquire four measured edge clamps and overlapping interior scan rows."""

    if not args.execute or not args.yes:
        raise SystemExit("scan-base-grid requires both --execute and --yes")
    atlas = load_home_atlas(args.atlas)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    runtime = connect_runtime(args, "home-atlas-four-corner-grid")
    source = runtime.capture("grid-00-source")
    source_localization = localizer.localize(source.frame)
    if (
        not source_localization.recognized
        or source_localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT
    ):
        result = {
            "status": "blocked",
            "reason": "source_not_localized_canonical_home",
            "localization": source_localization.__dict__,
            "session": str(runtime.session),
        }
        _json(runtime.session / "grid-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    records: list[dict[str, object]] = []
    accepted_frames: list[str] = [str(source.path)]
    clamps: dict[str, dict[str, object]] = {}
    row_endpoints: list[dict[str, object]] = []
    ordinal = 0

    def dispatch(direction: str, phase: str, row: int) -> tuple[str, dict[str, object]]:
        nonlocal ordinal
        ordinal += 1
        start, end = _GRID_GESTURES[direction]
        immediate_before = runtime.capture(f"grid-{ordinal:02d}-{phase}-{direction}-immediate-before")
        action_key = f"home-grid-{phase}-{direction}-{row}-{ordinal}-{int(time.time() * 1000)}"
        runtime.swipe(
            immediate_before,
            start=start,
            end=end,
            action_key=action_key,
            target_identity="home-camera-click-drag",
        )
        immediate_post = runtime.capture(f"grid-{ordinal:02d}-{phase}-{direction}-immediate-post")
        time.sleep(args.settle_seconds)
        settled = runtime.capture(f"grid-{ordinal:02d}-{phase}-{direction}-settled")
        registration = register_home_frame(settled.frame, immediate_before.frame, minimum_overlap=0.12)
        scale, movement = _registration_geometry(registration)
        record = {
            "ordinal": ordinal,
            "row": row,
            "phase": phase,
            "direction": direction,
            "action_key": action_key,
            "start": list(start),
            "end": list(end),
            "immediate_before_path": str(immediate_before.path),
            "immediate_before_sha256": immediate_before.sha256,
            "immediate_post_path": str(immediate_post.path),
            "immediate_post_sha256": immediate_post.sha256,
            "settled_path": str(settled.path),
            "settled_sha256": settled.sha256,
            "registration": registration.__dict__,
            "measured_scale": scale,
            "measured_movement_px": movement,
        }
        if scale is None or movement is None:
            status = "ambiguous"
        elif not (args.minimum_scale <= scale <= args.maximum_scale):
            status = "unexpected_scale"
        elif registration.residual_px > args.maximum_residual:
            status = "excessive_residual"
        elif movement < args.minimum_progress:
            status = "edge_clamp"
        else:
            status = "progress"
            accepted_frames.append(str(settled.path))
        record["status"] = status
        records.append(record)
        _json(runtime.session / f"grid-step-{ordinal:02d}.json", record)
        return status, record

    def travel_to_clamp(direction: str, phase: str, row: int) -> tuple[bool, dict[str, object] | None]:
        for _ in range(args.max_edge_inputs):
            status, record = dispatch(direction, phase, row)
            if status == "edge_clamp":
                clamps[f"{phase}:{direction}:row-{row}"] = record
                return True, record
            if status != "progress":
                return False, record
        return False, None

    # Establish the first exact corner, regardless of the arbitrary localized
    # starting camera position: top clamp, then right clamp.
    ok, failure = travel_to_clamp("up", "corner", 0)
    if ok:
        ok, failure = travel_to_clamp("right", "corner", 0)
    if not ok:
        result = {
            "status": "blocked",
            "reason": "corner_clamp_not_established",
            "failure": failure,
            "records": records,
            "session": str(runtime.session),
        }
        _json(runtime.session / "grid-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    row_endpoints.append({"row": 0, "edge": "right", "corner": "top_right", "frame": failure["immediate_before_path"]})

    # Sweep the top row to the opposite edge, then descend one overlapping row
    # at a time and alternate direction.  A downward no-progress step proves the
    # bottom edge; the just-completed row already contains both bottom corners.
    ok, failure = travel_to_clamp("left", "row-sweep", 0)
    if not ok:
        result = {"status": "blocked", "reason": "horizontal_clamp_not_established", "failure": failure, "records": records, "session": str(runtime.session)}
        _json(runtime.session / "grid-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    row_endpoints.append({"row": 0, "edge": "left", "corner": "top_left", "frame": failure["immediate_before_path"]})

    horizontal_direction = "right"
    bottom_reached = False
    for row in range(1, args.max_rows + 1):
        status, vertical = dispatch("down", "row-descent", row)
        if status == "edge_clamp":
            clamps[f"row-descent:down:row-{row}"] = vertical
            bottom_reached = True
            break
        if status != "progress":
            result = {"status": "blocked", "reason": "row_descent_failed", "failure": vertical, "records": records, "session": str(runtime.session)}
            _json(runtime.session / "grid-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        ok, failure = travel_to_clamp(horizontal_direction, "row-sweep", row)
        if not ok:
            result = {"status": "blocked", "reason": "horizontal_clamp_not_established", "failure": failure, "records": records, "session": str(runtime.session)}
            _json(runtime.session / "grid-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        row_endpoints.append({"row": row, "edge": horizontal_direction, "frame": failure["immediate_before_path"]})
        horizontal_direction = "left" if horizontal_direction == "right" else "right"

    if not bottom_reached:
        result = {"status": "blocked", "reason": "maximum_rows_without_bottom_clamp", "records": records, "session": str(runtime.session)}
        _json(runtime.session / "grid-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    bottom_row = max(item["row"] for item in row_endpoints)
    bottom_edges = {item["edge"] for item in row_endpoints if item["row"] == bottom_row}
    # The row starts at the opposite edge from its recorded terminal endpoint.
    terminal = next(item for item in reversed(row_endpoints) if item["row"] == bottom_row)
    start_edge = "left" if terminal["edge"] == "right" else "right"
    bottom_edges.add(start_edge)
    corners = {
        "top_right": row_endpoints[0],
        "top_left": row_endpoints[1],
        f"bottom_{terminal['edge']}": terminal,
        f"bottom_{start_edge}": {"row": bottom_row, "edge": start_edge, "proof": "start of the completed bottom-row sweep"},
    }
    result = {
        "status": "completed",
        "reason": "four_edge_clamps_and_overlapping_rows_acquired",
        "source_path": str(source.path),
        "source_sha256": source.sha256,
        "source_localization": source_localization.__dict__,
        "inputs": ordinal,
        "rows": bottom_row + 1,
        "clamps": clamps,
        "corners": corners,
        "bottom_edges": sorted(bottom_edges),
        "accepted_frame_paths": accepted_frames,
        "records": records,
        "session": str(runtime.session),
    }
    _json(runtime.session / "grid-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def command_zoom(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("zoom-out requires both --execute and --yes")
    runtime = connect_runtime(args, "home-canonical-zoom")
    canonical = read_frame(args.canonical_reference)
    transport = BlueStacksHostZoomTransport(
        args.window_title,
        cursor_x=args.cursor_x,
        cursor_y=args.cursor_y,
    )
    source = runtime.capture("zoom-00-source")
    for ordinal in range(1, args.max_inputs + 1):
        immediate_before = runtime.capture(f"zoom-{ordinal:02d}-immediate-before")
        transport.zoom_out_once()
        immediate_post = runtime.capture(f"zoom-{ordinal:02d}-immediate-post")
        time.sleep(args.settle_seconds)
        settled = runtime.capture(f"zoom-{ordinal:02d}-settled")
        immediate_step = register_home_frame(immediate_post.frame, immediate_before.frame, minimum_overlap=0.12)
        step = register_home_frame(settled.frame, immediate_before.frame, minimum_overlap=0.12)
        scale = None
        translation = None
        if step.accepted and step.transform_candidate_to_reference is not None:
            matrix = step.transform_candidate_to_reference
            scale = float((np.linalg.norm(matrix[:2, 0]) + np.linalg.norm(matrix[:2, 1])) / 2.0)
            translation = float(np.linalg.norm(matrix[:2, 2]))
        record = {
            "ordinal": ordinal,
            "source_sha256": source.sha256,
            "immediate_before_sha256": immediate_before.sha256,
            "immediate_post_sha256": immediate_post.sha256,
            "settled_sha256": settled.sha256,
            "immediate_step_registration": immediate_step.__dict__,
            "step_registration": step.__dict__,
            "step_scale": scale,
            "step_translation_px": translation,
        }
        _json(runtime.session / f"zoom-{ordinal:02d}.json", record)
        if not step.accepted or scale is None or translation is None:
            print(json.dumps({"status": "blocked", "reason": "ambiguous_zoom_step", "record": record, "session": str(runtime.session)}, sort_keys=True, default=str))
            return 3
        if 0.985 <= scale <= 1.015 and translation <= 3.0:
            canonical_class = classify_zoom(settled.frame, canonical)
            result = {
                "status": "completed",
                "reason": "verified_zoom_out_clamp",
                "inputs": ordinal,
                "record": record,
                "canonical_reference_classification": {**canonical_class.__dict__, "identity": canonical_class.identity.value},
                "session": str(runtime.session),
            }
            _json(runtime.session / "zoom-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 0
        if not (1.035 < scale <= 1.60):
            print(json.dumps({"status": "blocked", "reason": "unexpected_zoom_geometry", "record": record, "session": str(runtime.session)}, sort_keys=True, default=str))
            return 3
    print(json.dumps({"status": "blocked", "reason": "maximum_zoom_inputs_without_clamp", "session": str(runtime.session)}, sort_keys=True))
    return 3


def command_build(args) -> int:
    builder = AtlasBuilder()
    accepted = sum(1 for path in args.frames if builder.add(path))
    manifest = builder.write(args.output, atlas_id=args.atlas_id, account_layout=args.account_layout, game_build=args.game_build)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if args.registry_from:
        buildings: dict[str, dict[str, object]] = {}
        for registry_path in args.registry_from:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entries = registry.get("buildings", registry) if isinstance(registry, dict) else registry
            if not isinstance(entries, list):
                raise ValueError(f"building registry is not a list: {registry_path}")
            for entry in entries:
                semantic_id = str(entry["semantic_id"])
                if semantic_id in buildings:
                    raise ValueError(f"duplicate semantic building id: {semantic_id}")
                buildings[semantic_id] = dict(entry)
        source_mask = hud_mask()
        for building in buildings.values():
            polygon = np.asarray(building["polygon"], dtype=np.float64)
            center = polygon.mean(axis=0)
            supporting: list[str] = []
            for viewport in payload["viewports"]:
                inverse = np.linalg.inv(np.asarray(viewport["transform_to_atlas"], dtype=np.float64))
                projected = inverse @ np.asarray([center[0], center[1], 1.0])
                if abs(projected[2]) < 1e-9:
                    continue
                x, y = projected[:2] / projected[2]
                ix, iy = int(round(x)), int(round(y))
                if 0 <= ix < 800 and 0 <= iy < 1280 and source_mask[iy, ix] != 0:
                    supporting.append(viewport["viewport_id"])
            if not supporting:
                building["visibility_constraints"] = list(building.get("visibility_constraints", ())) + [
                    "no accepted HUD-free viewport contains the polygon center; identity is label-supported but not actionable"
                ]
            building["supporting_source_frames"] = supporting[:4]
        payload["buildings"] = list(buildings.values())
    if args.scan_result:
        scan = json.loads(args.scan_result.read_text(encoding="utf-8"))
        tx = [float(item["transform_to_atlas"][0][2]) for item in payload["viewports"]]
        ty = [float(item["transform_to_atlas"][1][2]) for item in payload["viewports"]]
        payload["boundary_evidence"] = {
            "method": "measured four-edge click-drag clamps plus overlapping boustrophedon rows",
            "scan_session": scan.get("session"),
            "navigation_inputs": scan.get("inputs"),
            "rows": scan.get("rows"),
            "clamp_keys": sorted(scan.get("clamps", {}).keys()),
            "corners": scan.get("corners", {}),
            "camera_origin_bounds": {
                "minimum_x": min(tx),
                "maximum_x": max(tx),
                "minimum_y": min(ty),
                "maximum_y": max(ty),
            },
        }
        payload["coverage_assessment"] = {
            "status": "full_reachable_base_coverage",
            "verified_interior_coverage_gaps": len(payload.get("coverage_gaps", ())),
            "verified_registration_coverage_gaps": len(payload.get("registration_coverage_gaps", ())),
            "outside_reachable_envelope": "unverified, rendered black, and never interpolated",
        }
    _json(manifest, payload)
    print(json.dumps({"status": "built", "accepted": accepted, "rejected": len(builder.rejected), "manifest": str(manifest)}, sort_keys=True))
    return 0


def command_localize(args) -> int:
    atlas = load_home_atlas(args.atlas)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    if args.frame is not None:
        frame = read_frame(args.frame)
    else:
        runtime = connect_runtime(args, "home-atlas-localize")
        frame = runtime.capture("localize-source").frame
    result = localizer.localize(frame)
    print(json.dumps(result.__dict__, sort_keys=True, default=lambda value: value.value if hasattr(value, "value") else str(value)))
    return 0 if result.recognized else 3


def command_open_building(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("open-building requires both --execute and --yes")
    atlas = load_home_atlas(args.atlas)
    building = atlas.lookup_building(args.building_id)
    runtime = connect_runtime(args, "home-atlas-open-building")
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    source = runtime.capture("open-building-source")
    source_localization = localizer.localize(source.frame)
    if not source_localization.recognized:
        print(json.dumps({"status": "blocked", "reason": "source_localization_failed", "localization": source_localization.__dict__}, sort_keys=True, default=str))
        return 3
    source_binding = bind_supply_depot_building(source.frame, source_localization, building)
    if source_binding is None:
        print(json.dumps({"status": "blocked", "reason": "source_building_binding_failed", "localization": source_localization.__dict__}, sort_keys=True, default=str))
        return 3
    immediate_before = runtime.capture("open-building-immediate-before")
    before_localization = localizer.localize(immediate_before.frame)
    before_binding = bind_supply_depot_building(immediate_before.frame, before_localization, building)
    if before_binding is None or before_binding.overlay_intersects or before_binding.ambiguous_overlap:
        print(json.dumps({"status": "blocked", "reason": "immediate_before_binding_failed"}, sort_keys=True))
        return 3
    action_key = f"open-{args.building_id}-{int(time.time() * 1000)}"
    runtime.tap(
        immediate_before,
        target_identity=args.building_id,
        target_roi=before_binding.target_roi,
        action_key=action_key,
        consequential=False,
    )
    immediate_post = runtime.capture("open-building-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("open-building-settled")
    if args.building_id != "home.building.supply_depot":
        print(json.dumps({"status": "blocked", "reason": "successor_policy_unimplemented", "session": str(runtime.session)}, sort_keys=True))
        return 3
    successor = recognize_supply_depot_screen(settled.frame)
    radial_action_key = None
    radial_binding = None
    radial_before = None
    radial_post = None
    radial_settled = None
    if not successor.recognized:
        radial_binding = bind_supply_depot_claim_supply(settled.frame)
        if radial_binding is not None:
            radial_before = runtime.capture("open-building-radial-immediate-before")
            radial_binding = bind_supply_depot_claim_supply(radial_before.frame)
            if radial_binding is not None and radial_binding.frame_sha256 == frame_digest(radial_before.frame):
                radial_action_key = f"supply-depot-claim-supply-{int(time.time() * 1000)}"
                runtime.tap(
                    radial_before,
                    target_identity="supply-depot-claim-supply-navigation",
                    target_roi=radial_binding.target_roi,
                    action_key=radial_action_key,
                    consequential=False,
                )
                radial_post = runtime.capture("open-building-radial-immediate-post")
                time.sleep(args.settle_seconds)
                radial_settled = runtime.capture("open-building-radial-settled")
                successor = recognize_supply_depot_screen(radial_settled.frame)
    result = {
        "status": "completed" if successor.recognized else "blocked",
        "reason": "exact_supply_depot_successor" if successor.recognized else "building_successor_not_recognized",
        "action_key": action_key,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "binding": before_binding.__dict__,
        "localization": before_localization.__dict__,
        "successor": successor.__dict__,
        "radial_action_key": radial_action_key,
        "radial_binding": radial_binding.__dict__ if radial_binding is not None else None,
        "radial_immediate_before_sha256": radial_before.sha256 if radial_before is not None else None,
        "radial_immediate_post_sha256": radial_post.sha256 if radial_post is not None else None,
        "radial_settled_sha256": radial_settled.sha256 if radial_settled is not None else None,
        "session": str(runtime.session),
    }
    _json(runtime.session / "open-building-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if successor.recognized else 3


def _navigate_authorization(building_id: str) -> AuthorizationScope:
    return AuthorizationScope(
        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
        owner_operator="home-atlas-navigate-building",
        action_class="navigation_only",
        platform=BLUESTACKS_PLATFORM,
        profile=BLUESTACKS_PROFILE_ID,
        environment="local_bluestacks",
        target_building_id=building_id,
    )


def _persist_navigate_session(nav_session, session_dir: Path) -> Path:
    path = session_dir / "navigate-session.json"
    save_session(nav_session, path)
    return path


def command_navigate_building(args) -> int:
    if args.execute and not args.yes:
        raise SystemExit("live navigate-building requires both --execute and --yes")
    atlas = load_home_atlas(args.atlas)
    building = atlas.lookup_building(args.building_id)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    safe_region, _original_calibration = bluestacks_direct_pan_contract()
    runtime = connect_runtime(args, "home-atlas-navigate-building")
    records: list[dict[str, object]] = []
    nav_session = create_session(
        _navigate_authorization(args.building_id),
        runtime_capture_session_id=str(runtime.session),
        maximum_pans=args.maximum_pans,
    )
    session_calibration = create_bluestacks_session_calibration(nav_session.navigation_session_id)
    controller = DirectPanNavigator(
        atlas,
        args.building_id,
        safe_region,
        session_calibration.effective_gesture_calibration(),
        maximum_pans=args.maximum_pans,
    )
    session_path = _persist_navigate_session(nav_session, runtime.session)
    lease_owner = nav_session.authorization.owner_operator
    # Route-local policy allowlist only; does not register the task for production/scheduler.
    policy = CentralPolicy(
        supervised_tasks=frozenset(
            {
                "MVP-QUEST-TO-CLAIM",
                nav_session.authorization.task_id,
            }
        )
    )
    store: SafetyStore | None = None

    def _ensure_store() -> SafetyStore:
        nonlocal store
        if store is None:
            store = SafetyStore(runtime.session / "navigate-safety.sqlite3")
            store.acquire_lease(lease_owner, time.time(), 3600.0)
        return store

    def _close_store() -> None:
        nonlocal store
        if store is not None:
            store.close()
            store = None

    def _emit(result: dict[str, object], code: int) -> int:
        enriched = attach_navigate_terminal_reports(
            result,
            nav_session,
            session_calibration=session_calibration,
        )
        enriched["production_registration"] = "NOT_REGISTERED"
        enriched["scheduler_eligibility"] = False
        _json(runtime.session / "navigate-building-result.json", enriched)
        print(json.dumps(enriched, sort_keys=True, default=str))
        return code

    try:
        return _command_navigate_building_body(
            args=args,
            atlas=atlas,
            building=building,
            localizer=localizer,
            safe_region=safe_region,
            runtime=runtime,
            records=records,
            nav_session=nav_session,
            session_calibration=session_calibration,
            controller=controller,
            session_path=session_path,
            lease_owner=lease_owner,
            policy=policy,
            ensure_store=_ensure_store,
            emit=_emit,
        )
    finally:
        _close_store()


def _command_navigate_building_body(
    *,
    args,
    atlas,
    building,
    localizer,
    safe_region,
    runtime,
    records: list[dict[str, object]],
    nav_session: NavigationSession,
    session_calibration: SessionCalibrationState,
    controller: DirectPanNavigator,
    session_path: Path,
    lease_owner: str,
    policy: CentralPolicy,
    ensure_store,
    emit,
) -> int:
    source = runtime.capture("navigate-source")
    source_localization = localizer.localize(source.frame)
    if not source_localization.recognized:
        mark_blocked(
            nav_session,
            reason="source_localization_failed",
            observation=LatestObservation(None, localization_recognized=False, summary="source_localization_failed"),
        )
        _persist_navigate_session(nav_session, runtime.session)
        return emit(
            {
                "status": "blocked",
                "reason": "source_localization_failed",
                "localization": source_localization.__dict__,
                "records": records,
                "session": str(runtime.session),
                "navigation_session": str(session_path),
                "route_id": nav_session.route_id,
            },
            3,
        )

    source_home_recorded = False
    for ordinal in range(args.maximum_pans + 1):
        immediate_before = runtime.capture(f"navigate-{ordinal:02d}-immediate-before")
        derived_localization = localizer.localize(immediate_before.frame)
        derived_binding = (
            bind_visible_building(immediate_before.frame, derived_localization, building)
            if derived_localization.recognized
            else None
        )
        try:
            capture_ordinal = getattr(runtime, "ordinal", None)
            if capture_ordinal is None:
                capture_ordinal = ordinal + 1
            identity = identity_from_captured(
                immediate_before,
                session_id=str(runtime.session),
                ordinal=int(capture_ordinal),
                label=f"navigate-{ordinal:02d}-immediate-before",
            )
            perception = build_navigate_perception_bundle(identity, derived_localization, derived_binding)
            localization, binding = perception.checked_navigation_inputs()
        except PerceptionBundleError as exc:
            mark_blocked(nav_session, reason=exc.reason_code)
            _persist_navigate_session(nav_session, runtime.session)
            return emit(
                {
                    "status": "blocked",
                    "reason": exc.reason_code,
                    "building_id": args.building_id,
                    "records": records,
                    "session": str(runtime.session),
                    "navigation_session": str(session_path),
                    "route_id": nav_session.route_id,
                },
                3,
            )

        if not source_home_recorded:
            record_source_home_verified(
                nav_session,
                frame=identity,
                localization_confidence=localization.confidence,
                localization_residual_px=localization.residual_px,
                contextual_class=perception.context.contextual_class.value if perception.context else "",
            )
            _persist_navigate_session(nav_session, runtime.session)
            source_home_recorded = True

        # Keep planner on the session-local effective calibration for this turn.
        controller.calibration = session_calibration.effective_gesture_calibration()
        plan = controller.plan(localization, binding)
        origin = (
            camera_origin(localization)
            if localization.recognized and localization.screen_to_atlas is not None
            else None
        )
        record_plan(
            nav_session,
            requested=plan.requested_camera_displacement,
            predicted=plan.predicted_camera_displacement,
            remaining=plan.predicted_remaining_displacement,
            reason=plan.reason,
            seen_viewport=(int(round(origin[0])), int(round(origin[1]))) if origin is not None else None,
        )
        _persist_navigate_session(nav_session, runtime.session)
        plan_record = {
            "ordinal": ordinal,
            "building_id": args.building_id,
            "localization": localization.__dict__,
            "camera_origin": origin,
            "plan": asdict(plan),
            "binding": binding.__dict__ if binding is not None else None,
            "perception_bundle": bundle_evidence_snapshot(perception),
            "route_id": nav_session.route_id,
            "navigation_checkpoint": nav_session.checkpoint.value,
        }
        _json(runtime.session / f"navigate-plan-{ordinal:02d}.json", plan_record)
        if plan.disposition is PlanDisposition.PAN:
            assert plan.drag_start is not None and plan.drag_end is not None
            if not args.execute:
                mark_dry_run(nav_session)
                _persist_navigate_session(nav_session, runtime.session)
                return emit(
                    {
                        "status": "dry_run",
                        "reason": "calculated_pan_not_dispatched",
                        "building_id": args.building_id,
                        "input_count": 0,
                        "source_localization": source_localization.__dict__,
                        "plan": asdict(plan),
                        "records": records,
                        "perception_bundle": bundle_evidence_snapshot(perception),
                        "session": str(runtime.session),
                        "navigation_session": str(session_path),
                        "route_id": nav_session.route_id,
                    },
                    0,
                )
            next_pan = nav_session.pan_ordinal + 1
            gesture_fingerprint = compute_pan_gesture_fingerprint(
                nav_session,
                pan_ordinal=next_pan,
                requested=plan.requested_camera_displacement,
                predicted=plan.predicted_camera_displacement,
                source_frame=identity,
                target_identity=NAVIGATE_BUILDING_TARGET_IDENTITY,
            )
            action_key = make_pan_action_key(nav_session, gesture_fingerprint, next_pan)
            action_id = f"{nav_session.navigation_session_id}:pan:{next_pan}"
            record_pan_prepared(
                nav_session,
                action_key=action_key,
                source_frame=identity,
                target_identity=NAVIGATE_BUILDING_TARGET_IDENTITY,
                requested=plan.requested_camera_displacement,
                predicted=plan.predicted_camera_displacement,
                gesture_fingerprint=gesture_fingerprint,
            )
            _persist_navigate_session(nav_session, runtime.session)
            issued, execution, _pre_obs = dispatch_verified_navigate_pan(
                runtime=runtime,
                immediate_before=immediate_before,
                identity=identity,
                drag_start=plan.drag_start,
                drag_end=plan.drag_end,
                action_id=action_id,
                action_key=action_key,
                task_id=nav_session.authorization.task_id,
                navigation_session_id=nav_session.navigation_session_id,
                lease_owner=lease_owner,
                policy=policy,
                store=ensure_store(),
                dry_run=False,
            )
            if execution is None:
                mark_blocked(nav_session, reason=str(issued.reason_code))
                _persist_navigate_session(nav_session, runtime.session)
                return emit(
                    {
                        "status": "blocked",
                        "reason": "capability_issuance_denied",
                        "capability_reason": issued.reason_code,
                        "building_id": args.building_id,
                        "records": records,
                        "session": str(runtime.session),
                        "navigation_session": str(session_path),
                        "route_id": nav_session.route_id,
                    },
                    3,
                )
            if execution.status not in {ActionStatus.CONFIRMED, ActionStatus.UNRESOLVED} or execution.transport_calls < 1:
                mark_blocked(nav_session, reason=str(execution.reason))
                _persist_navigate_session(nav_session, runtime.session)
                return emit(
                    {
                        "status": "blocked",
                        "reason": "capability_consumption_denied",
                        "executor_status": execution.status.value,
                        "executor_reason": execution.reason,
                        "building_id": args.building_id,
                        "records": records,
                        "session": str(runtime.session),
                        "navigation_session": str(session_path),
                        "route_id": nav_session.route_id,
                    },
                    3,
                )
            record_pan_dispatched(nav_session, action_key)
            _persist_navigate_session(nav_session, runtime.session)
            pre_input_bundle = perception.invalidate_after_input()
            immediate_post = runtime.capture(f"navigate-{ordinal:02d}-immediate-post")
            time.sleep(args.settle_seconds)
            settled = runtime.capture(f"navigate-{ordinal:02d}-settled")
            settled_localization = localizer.localize(settled.frame)
            settled_ordinal = getattr(runtime, "ordinal", None)
            if settled_ordinal is None:
                settled_ordinal = ordinal + 3
            settled_identity = identity_from_captured(
                settled,
                session_id=str(runtime.session),
                ordinal=int(settled_ordinal),
                label=f"navigate-{ordinal:02d}-settled",
            )
            settled_bundle = classify_and_attach(
                bundle_from_identity(settled_identity)
                .with_frame_validation(bluestacks_frame_validation(settled_identity))
                .with_localization(localization_from_result(settled_identity, settled_localization))
            )
            try:
                settled_localization_checked = settled_bundle.checked_navigation_inputs()[0]
                progress = controller.record_progress(localization, settled_localization_checked)
                accepted = progress.accepted
                progress_reason = progress.reason
                measured = progress.measured_camera_displacement
                residual = progress.remaining_displacement
                progress_px = progress.progress_px
            except (PerceptionBundleError, ValueError) as exc:
                accepted = False
                progress_reason = getattr(exc, "reason_code", None) or str(exc) or "post_pan_localization_failed"
                measured = (0.0, 0.0)
                residual = (0.0, 0.0)
                progress_px = 0.0
                progress = None
            reconcile_pan(
                nav_session,
                action_key,
                post_frame=settled_identity,
                measured=measured,
                residual=residual,
                progress_px=progress_px,
                accepted=accepted,
                reason=progress_reason,
                localization_confidence=settled_localization.confidence if settled_localization.recognized else None,
            )
            _persist_navigate_session(nav_session, runtime.session)
            try:
                session_calibration = consider_navigate_pan_calibration(
                    session_calibration,
                    nav_session=nav_session,
                    plan=plan,
                    measured=measured,
                    progress_px=progress_px,
                    progress_reason=progress_reason,
                    accepted=accepted,
                    source_identity=identity,
                    settled_identity=settled_identity,
                    drag_start=plan.drag_start,
                    drag_end=plan.drag_end,
                    maximum_pans=args.maximum_pans,
                )
            except Exception:
                # Invalid measurements fail closed for adaptation only; route outcome stays semantic.
                pass
            record = {
                "ordinal": ordinal + 1,
                "action": "pan",
                "action_key": action_key,
                "start": plan.drag_start,
                "end": plan.drag_end,
                "plan": asdict(plan),
                "immediate_before_sha256": immediate_before.sha256,
                "immediate_post_sha256": immediate_post.sha256,
                "settled_sha256": settled.sha256,
                "settled_localization": settled_localization.__dict__,
                "progress": asdict(progress) if progress is not None else {"accepted": False, "reason": progress_reason},
                "pre_input_bundle_invalidated": pre_input_bundle.invalidated_after_input,
                "settled_perception_bundle": bundle_evidence_snapshot(settled_bundle),
                "route_id": nav_session.route_id,
                "navigation_checkpoint": nav_session.checkpoint.value,
                "navigation_outcome": nav_session.outcome.value,
                "executor_status": execution.status.value,
                "transport_observed": execution.transport_calls > 0,
                "semantic_verified": bool(accepted),
            }
            records.append(record)
            _json(runtime.session / f"navigate-pan-{ordinal + 1:02d}.json", record)
            if not accepted:
                return emit(
                    {
                        "status": "blocked",
                        "reason": progress_reason,
                        "building_id": args.building_id,
                        "records": records,
                        "session": str(runtime.session),
                        "navigation_session": str(session_path),
                        "route_id": nav_session.route_id,
                        "transport_observed": True,
                        "semantic_verified": False,
                    },
                    3,
                )
            continue
        if plan.disposition is PlanDisposition.COMPLETE and binding is not None:
            record_target_bound(nav_session, binding=binding, frame=identity, historical_roi=binding.target_roi)
            complete_route_at_target_bound(nav_session)
            _persist_navigate_session(nav_session, runtime.session)
            return emit(
                {
                    "status": "completed",
                    "reason": "current_frame_semantic_building_bound",
                    "building_id": args.building_id,
                    "source_sha256": source.sha256,
                    "source_localization": source_localization.__dict__,
                    "navigation_pans": len(records),
                    "records": records,
                    "building_binding": binding.__dict__,
                    "building_immediate_before_sha256": immediate_before.sha256,
                    "input_count": len(records),
                    "building_opened": False,
                    "perception_bundle": bundle_evidence_snapshot(perception),
                    "session": str(runtime.session),
                    "navigation_session": str(session_path),
                    "route_id": nav_session.route_id,
                },
                0,
            )
        reason = "current_frame_building_recognition_failed" if plan.disposition is PlanDisposition.BIND else plan.reason
        mark_blocked(nav_session, reason=reason)
        _persist_navigate_session(nav_session, runtime.session)
        return emit(
            {
                "status": "blocked",
                "reason": reason,
                "building_id": args.building_id,
                "plan": asdict(plan),
                "records": records,
                "perception_bundle": bundle_evidence_snapshot(perception),
                "session": str(runtime.session),
                "navigation_session": str(session_path),
                "route_id": nav_session.route_id,
            },
            3,
        )
    raise AssertionError("unreachable")


def command_supply_depot_radial(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("supply-depot-radial requires both --execute and --yes")
    runtime = connect_runtime(args, "supply-depot-radial")
    nav_session = create_session(
        AuthorizationScope(
            task_id=SUPPLY_DEPOT_ROUTE_TASK_ID,
            owner_operator="supply-depot-radial",
            action_class="navigation_only",
            platform=BLUESTACKS_PLATFORM,
            profile=BLUESTACKS_PROFILE_ID,
            environment="local_bluestacks",
            target_building_id="home.building.supply_depot",
        ),
        runtime_capture_session_id=str(runtime.session),
        maximum_pans=1,
    )
    session_path = runtime.session / "radial-navigation-session.json"
    save_session(nav_session, session_path)
    lease_owner = nav_session.authorization.owner_operator
    policy = CentralPolicy(
        supervised_tasks=frozenset({"MVP-QUEST-TO-CLAIM", SUPPLY_DEPOT_ROUTE_TASK_ID})
    )
    store: SafetyStore | None = None
    radial_semantics = None
    radial_perception = None
    safe_exit_result = None
    action_results: dict[str, dict[str, object]] = {}

    def _ensure_store() -> SafetyStore:
        nonlocal store
        if store is None:
            store = SafetyStore(runtime.session / "radial-safety.sqlite3")
            store.acquire_lease(lease_owner, time.time(), 3600.0)
        return store

    def _emit(result: dict[str, object], code: int) -> int:
        enriched = attach_navigate_terminal_reports(result, nav_session)
        if radial_semantics is not None:
            enriched["radial_semantics"] = radial_semantics_evidence_snapshot(
                radial_semantics
            )
        if radial_perception is not None:
            enriched["radial_perception_bundle"] = bundle_evidence_snapshot(
                radial_perception
            )
        if safe_exit_result is not None:
            enriched["safe_exit_binding"] = safe_exit_evidence_snapshot(
                safe_exit_result
            )
        enriched["production_registration"] = "NOT_REGISTERED"
        enriched["scheduler_eligibility"] = False
        enriched["navigation_session"] = str(session_path)
        enriched["route_id"] = nav_session.route_id
        _json(runtime.session / "radial-result.json", enriched)
        print(json.dumps(enriched, sort_keys=True, default=str))
        return code

    def _execution_payload(
        issued,
        execution,
        telemetry: dict[str, object],
    ) -> dict[str, object]:
        return {
            "requested": bool(telemetry.get("requested")),
            "authorized": bool(telemetry.get("authorized")),
            "dispatched": bool(telemetry.get("dispatched")),
            "transport_observed": bool(telemetry.get("transport_observed")),
            "verified": bool(telemetry.get("verified")),
            "completed": bool(telemetry.get("completed")),
            "capability_reason": getattr(issued, "reason_code", None),
            "executor_status": (
                execution.status.value if execution is not None else None
            ),
            "executor_reason": (
                execution.reason if execution is not None else None
            ),
            "input_count": (
                execution.transport_calls if execution is not None else 0
            ),
        }

    def _blocked(
        reason: str,
        *,
        source: CapturedNativeFrame,
        immediate_before: CapturedNativeFrame | None = None,
        extra: Mapping[str, object] | None = None,
    ) -> int:
        mark_blocked(nav_session, reason=reason)
        save_session(nav_session, session_path)
        result: dict[str, object] = {
            "status": "blocked",
            "reason": reason,
            "source_sha256": source.sha256,
            "requested": True,
            "authorized": False,
            "dispatched": False,
            "transport_observed": False,
            "verified": False,
            "completed": False,
            "session": str(runtime.session),
        }
        if immediate_before is not None:
            result["immediate_before_sha256"] = immediate_before.sha256
        if extra:
            result.update(extra)
        return _emit(result, 3)

    try:
        source = runtime.capture("radial-source")
        source_ordinal = getattr(runtime, "ordinal", None) or 1
        source_identity = identity_from_captured(
            source,
            session_id=str(runtime.session),
            ordinal=int(source_ordinal),
            label="radial-source",
        )
        source_radial_binding = bind_supply_depot_claim_supply(
            source.frame,
            source_frame=source_identity,
        )
        source_building_binding = None
        if source_radial_binding is None:
            source_building_binding = bind_supply_depot_home_building(
                source.frame,
                atlas_path=getattr(args, "atlas", None),
                source_frame=source_identity,
            )
            if source_building_binding is None:
                return _blocked(
                    "source_radial_or_building_not_recognized",
                    source=source,
                )

        immediate_before = runtime.capture(
            "supply-depot-building-immediate-before"
            if source_radial_binding is None
            else "radial-immediate-before"
        )
        before_ordinal = getattr(runtime, "ordinal", None) or int(source_ordinal) + 1
        identity = identity_from_captured(
            immediate_before,
            session_id=str(runtime.session),
            ordinal=int(before_ordinal),
            label=(
                "supply-depot-building-immediate-before"
                if source_radial_binding is None
                else "radial-immediate-before"
            ),
        )
        if source_radial_binding is None:
            building_binding = bind_supply_depot_home_building(
                immediate_before.frame,
                atlas_path=getattr(args, "atlas", None),
                source_frame=identity,
            )
            radial_binding = None
        else:
            building_binding = (
                bind_supply_depot_home_building(
                    immediate_before.frame,
                    atlas_path=getattr(args, "atlas", None),
                    source_frame=identity,
                )
                if getattr(args, "atlas", None) is not None
                else None
            )
            radial_binding = bind_supply_depot_claim_supply(
                immediate_before.frame,
                source_frame=identity,
            )
        if (
            (radial_binding is None and building_binding is None)
            or (
                radial_binding is not None
                and radial_binding.frame_sha256 != identity.semantic_sha256
            )
            or (
                building_binding is not None
                and building_binding.frame_sha256 != identity.semantic_sha256
            )
        ):
            return _blocked(
                "immediate_before_radial_or_building_not_recognized",
                source=source,
                immediate_before=immediate_before,
            )

        safe_exit_result = build_supply_depot_safe_exit_probe(
            identity,
            building_binding=building_binding,
            radial_binding=radial_binding,
        )
        record_source_home_verified(
            nav_session,
            frame=identity,
            contextual_class=(
                "home_with_known_radial"
                if radial_binding is not None
                else "home_with_supply_depot_building"
            ),
        )
        record_plan(
            nav_session,
            requested=(0.0, 0.0),
            predicted=(0.0, 0.0),
            remaining=(0.0, 0.0),
            reason=(
                "current_frame_radial"
                if radial_binding is not None
                else "current_frame_supply_depot_building"
            ),
        )
        record_target_bound(
            nav_session,
            binding=radial_binding or building_binding,
            frame=identity,
            historical_roi=(radial_binding or building_binding).target_roi,
        )
        save_session(nav_session, session_path)

        if building_binding is not None:
            building_action_key = (
                f"supply-depot-building-navigation:"
                f"{nav_session.navigation_session_id}:{int(time.time() * 1000)}"
            )
            building_action_id = (
                f"{nav_session.navigation_session_id}:building:1"
            )
            record_navigation_action_prepared(
                nav_session,
                action_key=building_action_key,
                source_frame=identity,
                target_identity=SUPPLY_DEPOT_BUILDING_TARGET_IDENTITY,
                kind="building_tap",
            )
            issued, execution, _pre_observation, building_telemetry = (
                dispatch_verified_supply_depot_building_tap(
                    runtime=runtime,
                    immediate_before=immediate_before,
                    identity=identity,
                    binding=building_binding,
                    action_id=building_action_id,
                    action_key=building_action_key,
                    task_id=nav_session.authorization.task_id,
                    navigation_session_id=nav_session.navigation_session_id,
                    lease_owner=lease_owner,
                    policy=policy,
                    store=_ensure_store(),
                    settle_seconds=args.settle_seconds,
                )
            )
            action_results["building_entry"] = _execution_payload(
                issued, execution, building_telemetry
            )
            if execution is None:
                return _blocked(
                    "building_capability_issuance_denied",
                    source=source,
                    immediate_before=immediate_before,
                    extra={"actions": action_results},
                )
            building_transport = execution.transport_calls > 0
            if building_transport:
                record_navigation_action_dispatched(
                    nav_session, building_action_key
                )
            settled_building_identity = building_telemetry.get(
                "settled_identity"
            )
            building_verified = bool(
                execution.status is ActionStatus.CONFIRMED
                and building_telemetry.get("verified") is True
                and isinstance(settled_building_identity, NativeFrameIdentity)
            )
            if building_verified:
                assert isinstance(settled_building_identity, NativeFrameIdentity)
                reconcile_navigation_action(
                    nav_session,
                    building_action_key,
                    post_frame=settled_building_identity,
                    verified=True,
                    reason="exact_supply_depot_radial_successor",
                )
                record_radial_verified(
                    nav_session,
                    frame=settled_building_identity,
                )
                save_session(nav_session, session_path)
                immediate_before = runtime.capture(
                    "radial-after-building-immediate-before"
                )
                before_ordinal = (
                    getattr(runtime, "ordinal", None)
                    or settled_building_identity.capture_ordinal + 1
                )
                identity = identity_from_captured(
                    immediate_before,
                    session_id=str(runtime.session),
                    ordinal=int(before_ordinal),
                    label="radial-after-building-immediate-before",
                )
                radial_binding = bind_supply_depot_claim_supply(
                    immediate_before.frame,
                    source_frame=identity,
                )
                if (
                    radial_binding is None
                    or radial_binding.frame_sha256 != identity.semantic_sha256
                ):
                    return _blocked(
                        "radial_not_recognized_after_building_entry",
                        source=source,
                        immediate_before=immediate_before,
                        extra={"actions": action_results},
                    )
            elif execution.status is ActionStatus.UNRESOLVED and building_transport:
                mark_uncertain(
                    nav_session,
                    reason=execution.reason,
                    suppress_action_keys=(building_action_key,),
                )
                save_session(nav_session, session_path)
                return _emit(
                    {
                        "status": "blocked",
                        "reason": execution.reason,
                        "actions": action_results,
                        "requested": True,
                        "authorized": bool(issued.authorized),
                        "dispatched": bool(building_transport),
                        "transport_observed": bool(building_transport),
                        "verified": False,
                        "completed": False,
                    },
                    3,
                )
            else:
                return _blocked(
                    "building_successor_not_recognized",
                    source=source,
                    immediate_before=immediate_before,
                    extra={"actions": action_results},
                )

        assert radial_binding is not None
        radial_perception = build_supply_depot_radial_perception_bundle(
            identity,
            radial_binding,
        )
        radial_semantics = radial_perception.radial.semantics
        if nav_session.checkpoint is NavigationCheckpoint.TARGET_BOUND:
            record_radial_verified(nav_session, frame=identity)
        save_session(nav_session, session_path)

        action_key = (
            f"supply-depot-claim-supply-navigation:"
            f"{nav_session.navigation_session_id}:{int(time.time() * 1000)}"
        )
        action_id = f"{nav_session.navigation_session_id}:radial:1"
        record_navigation_action_prepared(
            nav_session,
            action_key=action_key,
            source_frame=identity,
            target_identity=SUPPLY_DEPOT_RADIAL_TARGET_IDENTITY,
            kind="radial_tap",
        )
        save_session(nav_session, session_path)
        issued, execution, _pre_observation, telemetry = (
            dispatch_verified_supply_depot_radial_tap(
                runtime=runtime,
                immediate_before=immediate_before,
                identity=identity,
                binding=radial_binding,
                action_id=action_id,
                action_key=action_key,
                task_id=nav_session.authorization.task_id,
                navigation_session_id=nav_session.navigation_session_id,
                lease_owner=lease_owner,
                policy=policy,
                store=_ensure_store(),
                settle_seconds=args.settle_seconds,
            )
        )
        if execution is None:
            return _blocked(
                "radial_capability_issuance_denied",
                source=source,
                immediate_before=immediate_before,
                extra={
                    "action_key": action_key,
                    "actions": action_results,
                },
            )

        transport_observed = execution.transport_calls > 0
        if transport_observed:
            record_navigation_action_dispatched(nav_session, action_key)
            save_session(nav_session, session_path)

        action_results["radial_entry"] = _execution_payload(
            issued, execution, telemetry
        )
        settled_identity = telemetry.get("settled_identity")
        successor = telemetry.get("successor")
        radial_verified = bool(
            execution.status is ActionStatus.CONFIRMED
            and telemetry.get("verified") is True
            and settled_identity is not None
            and successor is not None
        )
        if radial_verified:
            assert isinstance(settled_identity, NativeFrameIdentity)
            reconcile_navigation_action(
                nav_session,
                action_key,
                post_frame=settled_identity,
                verified=True,
                reason="exact_supply_depot_successor",
            )
        elif execution.status is ActionStatus.UNRESOLVED and transport_observed:
            mark_uncertain(
                nav_session,
                reason=execution.reason,
                suppress_action_keys=(action_key,),
            )
            save_session(nav_session, session_path)
            return _emit(
                {
                    "status": "blocked",
                    "reason": execution.reason,
                    "action_key": action_key,
                    "actions": action_results,
                    "radial_verified": False,
                    "requested": True,
                    "authorized": bool(issued.authorized),
                    "dispatched": True,
                    "transport_observed": True,
                    "verified": False,
                    "completed": False,
                },
                3,
            )
        elif transport_observed and isinstance(settled_identity, NativeFrameIdentity):
            reconcile_navigation_action(
                nav_session,
                action_key,
                post_frame=settled_identity,
                verified=False,
                reason="supply_depot_successor_not_recognized",
            )
            save_session(nav_session, session_path)
            return _emit(
                {
                    "status": "blocked",
                    "reason": "supply_depot_successor_not_recognized",
                    "action_key": action_key,
                    "actions": action_results,
                    "radial_verified": False,
                    "requested": True,
                    "authorized": bool(issued.authorized),
                    "dispatched": True,
                    "transport_observed": True,
                    "verified": False,
                    "completed": False,
                },
                3,
            )
        else:
            return _blocked(
                "radial_transport_not_observed",
                source=source,
                immediate_before=immediate_before,
                extra={"action_key": action_key, "actions": action_results},
            )

        assert radial_verified
        assert isinstance(settled_identity, NativeFrameIdentity)
        exit_before = runtime.capture("supply-depot-exit-immediate-before")
        exit_ordinal = getattr(runtime, "ordinal", None) or (
            settled_identity.capture_ordinal + 1
        )
        exit_identity = identity_from_captured(
            exit_before,
            session_id=str(runtime.session),
            ordinal=int(exit_ordinal),
            label="supply-depot-exit-immediate-before",
        )
        exit_screen = recognize_supply_depot_screen(
            exit_before.frame,
            source_frame=exit_identity,
        )
        if not exit_screen.recognized:
            return _blocked(
                "facility_screen_not_recognized_before_exit",
                source=source,
                immediate_before=exit_before,
                extra={
                    "action_key": action_key,
                    "actions": action_results,
                    "radial_verified": True,
                },
            )
        exit_action_key = (
            f"supply-depot-safe-exit:{nav_session.navigation_session_id}:"
            f"{int(time.time() * 1000)}"
        )
        exit_action_id = f"{nav_session.navigation_session_id}:exit:1"
        record_navigation_action_prepared(
            nav_session,
            action_key=exit_action_key,
            source_frame=exit_identity,
            target_identity=SUPPLY_DEPOT_EXIT_TARGET_IDENTITY,
            kind="safe_exit_tap",
        )
        exit_issued, exit_execution, _exit_observation, exit_telemetry = (
            dispatch_verified_supply_depot_exit_tap(
                runtime=runtime,
                immediate_before=exit_before,
                identity=exit_identity,
                action_id=exit_action_id,
                action_key=exit_action_key,
                task_id=nav_session.authorization.task_id,
                navigation_session_id=nav_session.navigation_session_id,
                lease_owner=lease_owner,
                policy=policy,
                store=_ensure_store(),
                home_successor_recognizer=lambda frame, *, source_frame: (
                    recognize_supply_depot_home_successor(
                        frame,
                        atlas_path=getattr(args, "atlas", None),
                        source_frame=source_frame,
                    )
                ),
                settle_seconds=args.settle_seconds,
            )
        )
        action_results["safe_exit"] = _execution_payload(
            exit_issued, exit_execution, exit_telemetry
        )
        if exit_execution is None:
            return _blocked(
                "safe_exit_capability_issuance_denied",
                source=source,
                immediate_before=exit_before,
                extra={"action_key": action_key, "actions": action_results},
            )
        exit_transport_observed = exit_execution.transport_calls > 0
        if exit_transport_observed:
            record_navigation_action_dispatched(nav_session, exit_action_key)
        home_identity = exit_telemetry.get("settled_identity")
        home_verified = bool(
            exit_execution.status is ActionStatus.CONFIRMED
            and exit_telemetry.get("verified") is True
            and isinstance(home_identity, NativeFrameIdentity)
        )
        if home_verified:
            assert isinstance(home_identity, NativeFrameIdentity)
            reconcile_navigation_action(
                nav_session,
                exit_action_key,
                post_frame=home_identity,
                verified=True,
                reason="fresh_home_semantic_successor",
            )
            record_safe_exit(nav_session, frame=home_identity)
            record_home_recovered(nav_session, frame=home_identity)
        elif exit_execution.status is ActionStatus.UNRESOLVED and exit_transport_observed:
            mark_uncertain(
                nav_session,
                reason=exit_execution.reason,
                suppress_action_keys=(exit_action_key,),
            )
        elif exit_transport_observed and isinstance(home_identity, NativeFrameIdentity):
            reconcile_navigation_action(
                nav_session,
                exit_action_key,
                post_frame=home_identity,
                verified=False,
                reason="home_successor_not_recognized",
            )
        else:
            mark_blocked(nav_session, reason=exit_execution.reason)
        save_session(nav_session, session_path)
        successor_payload = (
            successor.__dict__ if successor is not None else None
        )
        result = {
            "status": "completed" if home_verified else "blocked",
            "reason": (
                "supply_depot_radial_and_home_recovered"
                if home_verified
                else exit_execution.reason
            ),
            "action_key": action_key,
            "action_id": action_id,
            "source_sha256": source.sha256,
            "immediate_before_sha256": immediate_before.sha256,
            "binding": radial_binding.__dict__,
            "successor": successor_payload,
            "executor_status": execution.status.value,
            "executor_reason": execution.reason,
            "input_count": execution.transport_calls,
            "actions": action_results,
            "radial_verified": True,
            "home_recovered": bool(home_verified),
            "requested": all(
                item["requested"] for item in action_results.values()
            ),
            "authorized": all(
                item["authorized"] for item in action_results.values()
            ),
            "dispatched": all(
                item["dispatched"] for item in action_results.values()
            ),
            "transport_observed": all(
                item["transport_observed"] for item in action_results.values()
            ),
            "verified": bool(home_verified),
            "completed": bool(home_verified),
            "session": str(runtime.session),
        }
        if "immediate_post" in telemetry:
            result["immediate_post_sha256"] = telemetry["immediate_post"].sha256
        if "settled" in telemetry:
            result["settled_sha256"] = telemetry["settled"].sha256
        if "immediate_post_identity" in telemetry:
            result["immediate_post_identity"] = asdict(
                telemetry["immediate_post_identity"]
            )
        if "settled_identity" in telemetry:
            result["settled_identity"] = asdict(telemetry["settled_identity"])
        if "settled_perception_bundle" in telemetry:
            result["settled_perception_bundle"] = bundle_evidence_snapshot(
                telemetry["settled_perception_bundle"]
            )
        if "home_localization" in exit_telemetry:
            localization = exit_telemetry["home_localization"]
            result["home_localization"] = (
                localization.__dict__
                if hasattr(localization, "__dict__")
                else localization
            )
        if "settled_identity" in exit_telemetry:
            result["home_settled_identity"] = asdict(
                exit_telemetry["settled_identity"]
            )
        if exit_telemetry.get("settled_perception_bundle") is not None:
            result["home_perception_bundle"] = bundle_evidence_snapshot(
                exit_telemetry["settled_perception_bundle"]
            )
        result["exit_action_key"] = exit_action_key
        result["exit_action_id"] = exit_action_id
        return _emit(result, 0 if home_verified else 3)
    finally:
        if store is not None:
            store.close()


def _recognize_exact_title(frame: np.ndarray, expected: str) -> tuple[bool, str]:
    title = cv2.cvtColor(frame[0:110, 100:700], cv2.COLOR_BGR2GRAY)
    title = cv2.resize(title, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    text = f"{pytesseract.image_to_string(title, config='--psm 6')} {pytesseract.image_to_string(title, config='--psm 11')}"
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return expected in normalized, text


def command_recover_home(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("recover-home requires both --execute and --yes")
    expected = args.expected_title.replace("-", " ").lower()
    atlas = load_home_atlas(args.atlas)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    runtime = connect_runtime(args, "home-atlas-recover-home")
    source = runtime.capture("recover-home-source")
    source_recognized, source_text = _recognize_exact_title(source.frame, expected)
    if not source_recognized:
        print(json.dumps({"status": "blocked", "reason": "expected_source_title_not_recognized", "title_text": source_text, "session": str(runtime.session)}, sort_keys=True))
        return 3
    immediate_before = runtime.capture("recover-home-immediate-before")
    before_recognized, before_text = _recognize_exact_title(immediate_before.frame, expected)
    if not before_recognized:
        print(json.dumps({"status": "blocked", "reason": "immediate_before_title_not_recognized", "title_text": before_text, "session": str(runtime.session)}, sort_keys=True))
        return 3
    action_key = f"recover-{args.expected_title}-to-home-{int(time.time() * 1000)}"
    runtime.tap(
        immediate_before,
        target_identity=f"{args.expected_title}-back-arrow",
        target_roi=(0, 0, 150, 105),
        action_key=action_key,
        consequential=False,
    )
    immediate_post = runtime.capture("recover-home-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("recover-home-settled")
    localization = localizer.localize(settled.frame)
    result = {
        "status": "completed" if localization.recognized else "blocked",
        "reason": "fresh_home_localized" if localization.recognized else "home_successor_not_localized",
        "action_key": action_key,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "localization": localization.__dict__,
        "session": str(runtime.session),
    }
    _json(runtime.session / "recover-home-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if localization.recognized else 3


def _atlas_point(matrix, screen_point: tuple[float, float]) -> np.ndarray:
    value = np.asarray(matrix, dtype=np.float64) @ np.asarray([screen_point[0], screen_point[1], 1.0])
    return value[:2] / value[2]


def command_return_canonical(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("return-canonical requires both --execute and --yes")
    atlas = load_home_atlas(args.atlas)
    matches = [item for item in atlas.viewports if item.viewport_id == args.canonical_viewport]
    if len(matches) != 1:
        raise RuntimeError("canonical viewport is not uniquely present in the atlas")
    canonical_viewport = matches[0]
    anchor = (400.0, 640.0)
    target_center = _atlas_point(canonical_viewport.transform_to_atlas, anchor)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    runtime = connect_runtime(args, "home-atlas-return-canonical")
    records: list[dict[str, object]] = []
    seen_transforms: set[tuple[int, int]] = set()

    for ordinal in range(args.maximum_pans + 1):
        source = runtime.capture(f"canonical-{ordinal:02d}-source")
        source_localization = localizer.localize(source.frame)
        if not source_localization.recognized or source_localization.screen_to_atlas is None:
            result = {"status": "blocked", "reason": "source_localization_failed", "records": records, "localization": source_localization.__dict__, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        current_center = _atlas_point(source_localization.screen_to_atlas, anchor)
        distance = float(np.linalg.norm(target_center - current_center))
        if distance <= args.tolerance:
            result = {
                "status": "completed",
                "reason": "canonical_viewport_center_reached",
                "canonical_viewport": args.canonical_viewport,
                "target_center_atlas": target_center.tolist(),
                "final_center_atlas": current_center.tolist(),
                "final_distance_px": distance,
                "pans": len(records),
                "records": records,
                "localization": source_localization.__dict__,
                "session": str(runtime.session),
            }
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 0
        signature = (int(round(current_center[0] / 3.0)), int(round(current_center[1] / 3.0)))
        if signature in seen_transforms:
            result = {"status": "blocked", "reason": "repeated_viewport", "distance_px": distance, "records": records, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        seen_transforms.add(signature)
        if ordinal >= args.maximum_pans:
            result = {"status": "blocked", "reason": "maximum_pan_count", "distance_px": distance, "records": records, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3

        immediate_before = runtime.capture(f"canonical-{ordinal:02d}-immediate-before")
        before_localization = localizer.localize(immediate_before.frame)
        if not before_localization.recognized or before_localization.screen_to_atlas is None:
            result = {"status": "blocked", "reason": "immediate_before_localization_failed", "records": records, "localization": before_localization.__dict__, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        before_center = _atlas_point(before_localization.screen_to_atlas, anchor)
        before_distance = float(np.linalg.norm(target_center - before_center))
        inverse = np.linalg.inv(np.asarray(before_localization.screen_to_atlas, dtype=np.float64))
        projected = inverse @ np.asarray([target_center[0], target_center[1], 1.0])
        projected = projected[:2] / projected[2]
        displacement = projected - np.asarray(anchor)
        axis, start, end = _canonical_pan_gesture(displacement)
        if end == start:
            result = {"status": "blocked", "reason": "pan_geometry_ambiguous", "records": records, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3
        action_key = f"home-canonical-{axis}-drag-{ordinal}-{int(time.time() * 1000)}"
        runtime.swipe(
            immediate_before,
            start=start,
            end=end,
            action_key=action_key,
            target_identity="home-camera-click-drag",
        )
        immediate_post = runtime.capture(f"canonical-{ordinal:02d}-immediate-post")
        time.sleep(args.settle_seconds)
        settled = runtime.capture(f"canonical-{ordinal:02d}-settled")
        settled_localization = localizer.localize(settled.frame)
        after_center = _atlas_point(settled_localization.screen_to_atlas, anchor) if settled_localization.recognized and settled_localization.screen_to_atlas is not None else None
        after_distance = float(np.linalg.norm(target_center - after_center)) if after_center is not None else None
        record = {
            "ordinal": ordinal + 1,
            "axis": axis,
            "action_key": action_key,
            "start": start,
            "end": end,
            "source_sha256": source.sha256,
            "immediate_before_sha256": immediate_before.sha256,
            "immediate_post_sha256": immediate_post.sha256,
            "settled_sha256": settled.sha256,
            "before_center_atlas": before_center.tolist(),
            "after_center_atlas": after_center.tolist() if after_center is not None else None,
            "before_distance_px": before_distance,
            "after_distance_px": after_distance,
            "localization": settled_localization.__dict__,
        }
        records.append(record)
        _json(runtime.session / f"canonical-pan-{ordinal + 1:02d}.json", record)
        if after_distance is None or after_distance >= before_distance - args.minimum_progress:
            result = {"status": "blocked", "reason": "no_measured_progress", "records": records, "session": str(runtime.session)}
            _json(runtime.session / "return-canonical-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 3

    raise AssertionError("unreachable")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("capture", "pan", "scan-base-grid", "zoom-out", "localize", "open-building", "navigate-building", "supply-depot-radial", "recover-home", "return-canonical"):
        item = sub.add_parser(name)
        item.add_argument("--adb", required=name != "localize")
        item.add_argument("--serial", required=name != "localize")
        item.add_argument("--output-directory", type=Path, default=Path(".local-captures/home-atlas"))
        if name == "capture":
            item.add_argument("--label", default="home-source")
        elif name == "pan":
            item.add_argument("--canonical-reference", type=Path, required=True)
            item.add_argument("--start-x", type=int, required=True)
            item.add_argument("--start-y", type=int, required=True)
            item.add_argument("--end-x", type=int, required=True)
            item.add_argument("--end-y", type=int, required=True)
            item.add_argument("--settle-seconds", type=float, default=1.2)
            item.add_argument("--minimum-progress", type=float, default=8.0)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "zoom-out":
            item.add_argument("--canonical-reference", type=Path, required=True)
            item.add_argument("--window-title", default="BlueStacks App Player 4")
            item.add_argument("--cursor-x", type=int, default=420)
            item.add_argument("--cursor-y", type=int, default=540)
            item.add_argument("--max-inputs", type=int, default=6)
            item.add_argument("--settle-seconds", type=float, default=1.2)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "scan-base-grid":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--max-edge-inputs", type=int, default=6)
            item.add_argument("--max-rows", type=int, default=7)
            item.add_argument("--settle-seconds", type=float, default=1.2)
            item.add_argument("--minimum-progress", type=float, default=8.0)
            item.add_argument("--minimum-scale", type=float, default=0.985)
            item.add_argument("--maximum-scale", type=float, default=1.015)
            item.add_argument("--maximum-residual", type=float, default=4.0)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "open-building":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--building-id", required=True)
            item.add_argument("--settle-seconds", type=float, default=2.0)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "navigate-building":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--building-id", required=True)
            item.add_argument("--maximum-pans", type=int, default=8)
            item.add_argument("--pan-distance", type=int, default=260)
            item.add_argument("--settle-seconds", type=float, default=1.2)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "supply-depot-radial":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--settle-seconds", type=float, default=2.0)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "recover-home":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--expected-title", choices=("cultivation-center",), required=True)
            item.add_argument("--settle-seconds", type=float, default=2.0)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        elif name == "return-canonical":
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--canonical-viewport", default="viewport-001")
            item.add_argument("--maximum-pans", type=int, default=8)
            item.add_argument("--pan-distance", type=int, default=235)
            item.add_argument("--minimum-progress", type=float, default=8.0)
            item.add_argument("--tolerance", type=float, default=18.0)
            item.add_argument("--settle-seconds", type=float, default=1.2)
            item.add_argument("--execute", action="store_true")
            item.add_argument("--yes", action="store_true")
        else:
            item.add_argument("--atlas", type=Path, required=True)
            item.add_argument("--frame", type=Path)
    build = sub.add_parser("build")
    build.add_argument("--frames", type=Path, nargs="+", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--atlas-id", default="pns-home-base-bluestacks")
    build.add_argument("--account-layout", default="local account layout; BlueStacks-only")
    build.add_argument("--game-build", default="observable build unavailable")
    build.add_argument("--registry-from", type=Path, nargs="+")
    build.add_argument("--scan-result", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return {
        "capture": command_capture,
        "pan": command_pan,
        "scan-base-grid": command_scan_grid,
        "zoom-out": command_zoom,
        "build": command_build,
        "localize": command_localize,
        "open-building": command_open_building,
        "navigate-building": command_navigate_building,
        "supply-depot-radial": command_supply_depot_radial,
        "recover-home": command_recover_home,
        "return-canonical": command_return_canonical,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
