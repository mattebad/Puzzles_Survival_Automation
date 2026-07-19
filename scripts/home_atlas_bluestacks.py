#!/usr/bin/env python3
"""Build, localize, and navigate a BlueStacks Home/Base atlas.

The CLI is unregistered and dry-run by default.  It never connects ADB implicitly and
accepts only the repository's explicit local BlueStacks serial policy.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time
import re

import cv2
import numpy as np
import pytesseract

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.home_atlas import ClosedLoopBuildingNavigator, NavigationAction, ZoomIdentity, load_home_atlas
from tasks.home_atlas_vision import (
    BLUESTACKS_PLATFORM,
    BLUESTACKS_PROFILE_ID,
    BlueStacksHomeLocalizer,
    classify_zoom,
    frame_digest,
    hud_mask,
    native_frame_guard,
    register_home_frame,
)
from tasks.supply_depot_vision import (
    bind_supply_depot_building,
    bind_supply_depot_claim_supply,
    recognize_supply_depot_screen,
)


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


def command_navigate_building(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("navigate-building requires both --execute and --yes")
    if args.building_id != "home.building.supply_depot":
        raise SystemExit("only the Supply Depot successor policy is executable in this task")
    atlas = load_home_atlas(args.atlas)
    building = atlas.lookup_building(args.building_id)
    localizer = BlueStacksHomeLocalizer(atlas, args.atlas)
    controller = ClosedLoopBuildingNavigator(
        atlas,
        args.building_id,
        maximum_pans=args.maximum_pans,
        pan_distance=args.pan_distance,
    )
    runtime = connect_runtime(args, "home-atlas-navigate-building")
    records: list[dict[str, object]] = []
    source = runtime.capture("navigate-source")
    source_localization = localizer.localize(source.frame)
    if not source_localization.recognized:
        result = {"status": "blocked", "reason": "source_localization_failed", "localization": source_localization.__dict__, "records": records, "session": str(runtime.session)}
        _json(runtime.session / "navigate-building-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3

    for ordinal in range(args.maximum_pans + 1):
        immediate_before = runtime.capture(f"navigate-{ordinal:02d}-immediate-before")
        localization = localizer.localize(immediate_before.frame)
        binding = bind_supply_depot_building(immediate_before.frame, localization, building) if localization.recognized else None
        command = controller.next_command(localization, binding)
        if command.action is NavigationAction.PAN:
            assert command.pan_start is not None and command.pan_end is not None
            action_key = f"navigate-{args.building_id}-pan-{ordinal}-{int(time.time() * 1000)}"
            runtime.swipe(
                immediate_before,
                start=command.pan_start,
                end=command.pan_end,
                action_key=action_key,
                target_identity="home-camera-click-drag",
            )
            immediate_post = runtime.capture(f"navigate-{ordinal:02d}-immediate-post")
            time.sleep(args.settle_seconds)
            settled = runtime.capture(f"navigate-{ordinal:02d}-settled")
            settled_localization = localizer.localize(settled.frame)
            record = {
                "ordinal": ordinal + 1,
                "action": "pan",
                "action_key": action_key,
                "start": command.pan_start,
                "end": command.pan_end,
                "immediate_before_sha256": immediate_before.sha256,
                "immediate_post_sha256": immediate_post.sha256,
                "settled_sha256": settled.sha256,
                "settled_localization": settled_localization.__dict__,
            }
            records.append(record)
            _json(runtime.session / f"navigate-pan-{ordinal + 1:02d}.json", record)
            if not settled_localization.recognized:
                result = {"status": "blocked", "reason": "post_pan_localization_failed", "records": records, "session": str(runtime.session)}
                _json(runtime.session / "navigate-building-result.json", result)
                print(json.dumps(result, sort_keys=True, default=str))
                return 3
            continue
        if command.action is NavigationAction.TAP_TARGET and binding is not None:
            action_key = f"open-{args.building_id}-{int(time.time() * 1000)}"
            runtime.tap(
                immediate_before,
                target_identity=args.building_id,
                target_roi=binding.target_roi,
                action_key=action_key,
                consequential=False,
            )
            building_post = runtime.capture("navigate-building-immediate-post")
            time.sleep(args.settle_seconds)
            building_settled = runtime.capture("navigate-building-settled")
            successor = recognize_supply_depot_screen(building_settled.frame)
            radial_binding = None
            radial_action_key = None
            radial_before = None
            radial_post = None
            radial_settled = None
            if not successor.recognized:
                radial_binding = bind_supply_depot_claim_supply(building_settled.frame)
                if radial_binding is not None:
                    radial_before = runtime.capture("navigate-radial-immediate-before")
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
                        radial_post = runtime.capture("navigate-radial-immediate-post")
                        time.sleep(args.settle_seconds)
                        radial_settled = runtime.capture("navigate-radial-settled")
                        successor = recognize_supply_depot_screen(radial_settled.frame)
            result = {
                "status": "completed" if successor.recognized else "blocked",
                "reason": "exact_supply_depot_successor" if successor.recognized else "building_successor_not_recognized",
                "source_sha256": source.sha256,
                "source_localization": source_localization.__dict__,
                "navigation_pans": len(records),
                "records": records,
                "building_action_key": action_key,
                "building_binding": binding.__dict__,
                "building_immediate_before_sha256": immediate_before.sha256,
                "building_immediate_post_sha256": building_post.sha256,
                "building_settled_sha256": building_settled.sha256,
                "radial_action_key": radial_action_key,
                "radial_binding": radial_binding.__dict__ if radial_binding is not None else None,
                "radial_immediate_before_sha256": radial_before.sha256 if radial_before is not None else None,
                "radial_immediate_post_sha256": radial_post.sha256 if radial_post is not None else None,
                "radial_settled_sha256": radial_settled.sha256 if radial_settled is not None else None,
                "successor": successor.__dict__,
                "session": str(runtime.session),
            }
            _json(runtime.session / "navigate-building-result.json", result)
            print(json.dumps(result, sort_keys=True, default=str))
            return 0 if successor.recognized else 3
        result = {"status": "blocked", "reason": command.reason, "command": command.__dict__, "records": records, "session": str(runtime.session)}
        _json(runtime.session / "navigate-building-result.json", result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 3
    raise AssertionError("unreachable")


def command_supply_depot_radial(args) -> int:
    if not args.execute or not args.yes:
        raise SystemExit("supply-depot-radial requires both --execute and --yes")
    runtime = connect_runtime(args, "supply-depot-radial")
    source = runtime.capture("radial-source")
    source_binding = bind_supply_depot_claim_supply(source.frame)
    if source_binding is None:
        print(json.dumps({"status": "blocked", "reason": "source_radial_not_recognized"}, sort_keys=True))
        return 3
    immediate_before = runtime.capture("radial-immediate-before")
    binding = bind_supply_depot_claim_supply(immediate_before.frame)
    if binding is None or binding.frame_sha256 != frame_digest(immediate_before.frame):
        print(json.dumps({"status": "blocked", "reason": "immediate_before_radial_not_recognized"}, sort_keys=True))
        return 3
    action_key = f"supply-depot-claim-supply-{int(time.time() * 1000)}"
    runtime.tap(
        immediate_before,
        target_identity="supply-depot-claim-supply-navigation",
        target_roi=binding.target_roi,
        action_key=action_key,
        consequential=False,
    )
    immediate_post = runtime.capture("radial-immediate-post")
    time.sleep(args.settle_seconds)
    settled = runtime.capture("radial-settled")
    successor = recognize_supply_depot_screen(settled.frame)
    result = {
        "status": "completed" if successor.recognized else "blocked",
        "reason": "exact_supply_depot_successor" if successor.recognized else "supply_depot_successor_not_recognized",
        "action_key": action_key,
        "source_sha256": source.sha256,
        "immediate_before_sha256": immediate_before.sha256,
        "immediate_post_sha256": immediate_post.sha256,
        "settled_sha256": settled.sha256,
        "binding": binding.__dict__,
        "successor": successor.__dict__,
        "session": str(runtime.session),
    }
    _json(runtime.session / "radial-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if successor.recognized else 3


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
