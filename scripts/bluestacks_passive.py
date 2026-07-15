"""Windows passive input observation for the BlueStacks flow collector.

This module is loaded only for ``--passive`` sessions.  It uses the Windows low-level
mouse and keyboard hooks through ``ctypes`` so normal BlueStacks input is observed and
passed through unchanged.  No ADB input command is available from this module.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
GA_ROOT = 2

MOUSE_BUTTONS = {
    WM_LBUTTONDOWN: ("left", WM_LBUTTONUP),
    WM_RBUTTONDOWN: ("right", WM_RBUTTONUP),
    WM_MBUTTONDOWN: ("middle", WM_MBUTTONUP),
}
MOUSE_UP_TO_BUTTON = {value[1]: key for key, value in MOUSE_BUTTONS.items()}
VK_NAMES = {
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "PAUSE": 0x13,
}


def _collector_module() -> Any:
    import sys

    return sys.modules.get("__main__") or sys.modules["bluestacks_flow_collector"]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process_id: int


@dataclass
class MouseState:
    button: str
    start_screen: tuple[int, int]
    start_client: tuple[float, float]
    end_screen: tuple[int, int]
    end_client: tuple[float, float]
    started_monotonic: float
    started_at_utc: str
    rendered_bounds: tuple[float, float, float, float]
    client_size: tuple[int, int]


@dataclass(frozen=True)
class FrameSnapshot:
    captured_monotonic: float
    captured_at_utc: str
    payload: bytes


class Win32:
    def __init__(self) -> None:
        if os.name != "nt":
            raise _collector_module().CollectorError("passive recording requires Windows")
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.hook_proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self.enum_proc_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        self.user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, self.hook_proc_type, ctypes.c_void_p, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self.user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        self.user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self.user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self.user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self.user32.PostQuitMessage.argtypes = [ctypes.c_int]

    def window_info(self, hwnd: int) -> WindowInfo:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return WindowInfo(int(hwnd), buffer.value, int(process_id.value))

    def visible_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        @self.enum_proc_type
        def callback(hwnd: int, _lparam: int) -> bool:
            if self.user32.IsWindowVisible(hwnd):
                info = self.window_info(hwnd)
                if info.title.strip():
                    windows.append(info)
            return True

        if not self.user32.EnumWindows(callback, 0):
            raise _collector_module().CollectorError("EnumWindows failed")
        return windows

    def is_window_usable(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindow(hwnd) and self.user32.IsWindowVisible(hwnd))

    def is_active(self, hwnd: int) -> bool:
        foreground = self.user32.GetForegroundWindow()
        if not foreground:
            return False
        root = self.user32.GetAncestor(foreground, GA_ROOT)
        return int(root or foreground) == int(hwnd)

    def client_point(self, hwnd: int, screen: tuple[int, int]) -> tuple[float, float]:
        point = POINT(screen[0], screen[1])
        if not self.user32.ScreenToClient(hwnd, ctypes.byref(point)):
            raise _collector_module().CollectorError("ScreenToClient failed")
        return float(point.x), float(point.y)

    def client_size(self, hwnd: int) -> tuple[int, int]:
        rect = RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise _collector_module().CollectorError("GetClientRect failed")
        return max(0, int(rect.right - rect.left)), max(0, int(rect.bottom - rect.top))

    def install_hook(self, hook_type: int, callback: Any) -> Any:
        handle = self.user32.SetWindowsHookExW(hook_type, callback, self.kernel32.GetModuleHandleW(None), 0)
        if not handle:
            raise _collector_module().CollectorError(f"SetWindowsHookEx failed for hook {hook_type}")
        return handle


def parse_hotkey(value: str) -> int:
    text = value.strip().upper()
    if text in VK_NAMES:
        return VK_NAMES[text]
    if text.startswith("F") and text[1:].isdigit() and 1 <= int(text[1:]) <= 24:
        return 0x70 + int(text[1:]) - 1
    if len(text) == 1:
        return ord(text)
    try:
        return int(text, 0)
    except ValueError as exc:
        raise _collector_module().CollectorError(f"unsupported hotkey: {value}") from exc


def select_window(win32: Win32, args: Any) -> WindowInfo:
    windows = win32.visible_windows()
    if args.window_handle:
        try:
            hwnd = int(str(args.window_handle), 0)
        except ValueError as exc:
            raise _collector_module().CollectorError("--window-handle must be decimal or 0x-prefixed hexadecimal") from exc
        if not win32.is_window_usable(hwnd):
            raise _collector_module().CollectorError(f"selected window handle is not visible: {args.window_handle}")
        return win32.window_info(hwnd)

    if args.process_id:
        try:
            process_id = int(args.process_id)
        except ValueError as exc:
            raise _collector_module().CollectorError("--process-id must be an integer") from exc
        matches = [item for item in windows if item.process_id == process_id]
    elif args.window_title:
        requested = args.window_title.casefold()
        matches = [item for item in windows if item.title.casefold() == requested]
        if not matches:
            matches = [item for item in windows if requested in item.title.casefold()]
    else:
        matches = []

    if len(matches) != 1:
        if matches:
            print("Window selection is ambiguous; choose one exact handle:")
        else:
            print("Visible windows (select the exact BlueStacks window handle):")
            matches = windows
        for item in matches:
            print(f"  0x{item.hwnd:x}\tpid={item.process_id}\t{item.title}")
        try:
            answer = input("Enter the exact window handle: ").strip()
        except EOFError as exc:
            raise _collector_module().CollectorError("an explicit BlueStacks window selection is required") from exc
        try:
            hwnd = int(answer, 0)
        except ValueError as exc:
            raise _collector_module().CollectorError("window handle must be decimal or 0x-prefixed hexadecimal") from exc
        selected = next((item for item in windows if item.hwnd == hwnd), None)
        if selected is None:
            raise _collector_module().CollectorError("selected window handle is not in the current visible window list")
        return selected
    return matches[0]


class RollingFrameBuffer:
    def __init__(self, session: Any, interval: float, max_frames: int = 12) -> None:
        self.session = session
        self.collector = _collector_module()
        self.interval = max(0.05, interval)
        self.frames: deque[FrameSnapshot] = deque(maxlen=max_frames)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.logged_capture_error = False

    def capture_once(self) -> FrameSnapshot:
        if self.session.source is None:
            raise self.collector.CollectorError("no screenshot source is available")
        payload = self.session.source.capture()
        if self.collector.png_dimensions(payload) != self.collector.RAW_SIZE:
            raise self.collector.CollectorError("rolling frame is not exactly 800x1280")
        snapshot = FrameSnapshot(time.monotonic(), self.collector.utc_now(), bytes(payload))
        with self.lock:
            self.frames.append(snapshot)
        return snapshot

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.capture_once()
            except Exception as exc:
                if not self.logged_capture_error:
                    self.logged_capture_error = True
                    self.session._record_error("PASSIVE_BUFFER_CAPTURE_FAILED", str(exc), phase="passive-buffer", exception=type(exc).__name__)
            self.stop_event.wait(self.interval)

    def start(self) -> None:
        self.capture_once()
        self.thread = threading.Thread(target=self._run, name="bluestacks-passive-frame-buffer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(2.0, self.interval * 4))

    def before(self, observed_monotonic: float) -> tuple[FrameSnapshot, bool]:
        with self.lock:
            eligible = [item for item in self.frames if item.captured_monotonic <= observed_monotonic]
            if eligible:
                return max(eligible, key=lambda item: item.captured_monotonic), True
            if self.frames:
                return self.frames[0], False
        raise self.collector.CollectorError("no rolling clean screenshot predates the observed input")


class PassiveRecorder:
    """Observe selected-window input without dispatching or replaying it."""

    def __init__(self, session: Any) -> None:
        self.collector = _collector_module()
        self.session = session
        self.win32 = Win32()
        self.target = select_window(self.win32, session.args)
        self.start_vk = parse_hotkey(session.args.start_hotkey)
        self.stop_vk = parse_hotkey(session.args.stop_hotkey)
        self.back_vk = parse_hotkey(session.args.back_hotkey)
        if len({self.start_vk, self.stop_vk, self.back_vk}) != 3:
            raise self.collector.CollectorError("start, stop, and Back hotkeys must differ")
        self.buffer = RollingFrameBuffer(session, session.args.buffer_interval)
        self.events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.recording = False
        self.started = False
        self.stop_requested = False
        self.mouse_state: MouseState | None = None
        self.sequence = 0
        self.mouse_callback: Any = None
        self.keyboard_callback: Any = None
        self.mouse_hook: Any = None
        self.keyboard_hook: Any = None
        self.session.manifest["passive_recording"] = {
            "selected_window": {"handle": f"0x{self.target.hwnd:x}", "title": self.target.title, "process_id": self.target.process_id},
            "start_hotkey": session.args.start_hotkey,
            "stop_hotkey": session.args.stop_hotkey,
            "back_hotkey": session.args.back_hotkey,
            "buffer_interval_seconds": session.args.buffer_interval,
            "swipe_distance_threshold": session.args.swipe_distance_threshold,
            "swipe_duration_threshold": session.args.swipe_duration_threshold,
            "input_dispatch": False,
            "state": "waiting",
        }
        session._append_log("passive_window_selected", self.session.manifest["passive_recording"]["selected_window"])
        session._persist_manifest()

    def _rendered_bounds(self) -> tuple[tuple[float, float, float, float], tuple[int, int]]:
        width, height = self.win32.client_size(self.target.hwnd)
        if width <= 0 or height <= 0:
            raise self.collector.CollectorError("selected BlueStacks window has no usable client area")
        scale = min(width / self.collector.RAW_WIDTH, height / self.collector.RAW_HEIGHT)
        rendered = (self.collector.RAW_WIDTH * scale, self.collector.RAW_HEIGHT * scale)
        return ((width - rendered[0]) / 2.0, (height - rendered[1]) / 2.0, rendered[0], rendered[1]), (width, height)

    def _screen_and_client(self, data: MSLLHOOKSTRUCT) -> tuple[tuple[int, int], tuple[float, float], tuple[float, float, float, float], tuple[int, int]]:
        screen = (int(data.pt.x), int(data.pt.y))
        client = self.win32.client_point(self.target.hwnd, screen)
        bounds, client_size = self._rendered_bounds()
        return screen, client, bounds, client_size

    def _active_and_inside(self, client: tuple[float, float], bounds: tuple[float, float, float, float]) -> bool:
        return self.win32.is_active(self.target.hwnd) and self.collector.point_inside_rendered_image(*client, bounds)

    def _handle_mouse(self, message: int, data: MSLLHOOKSTRUCT) -> None:
        now = time.monotonic()
        if message in MOUSE_BUTTONS:
            if not self.recording or not self.win32.is_active(self.target.hwnd):
                return
            screen, client, bounds, client_size = self._screen_and_client(data)
            if not self._active_and_inside(client, bounds):
                return
            button, _ = MOUSE_BUTTONS[message]
            started_at = self.collector.utc_now()
            self.mouse_state = MouseState(button, screen, client, screen, client, now, started_at, bounds, client_size)
            return
        if message == WM_MOUSEMOVE and self.mouse_state is not None:
            if not self.recording or not self.win32.is_active(self.target.hwnd):
                self.mouse_state = None
                return
            screen, client, _bounds, _client_size = self._screen_and_client(data)
            self.mouse_state.end_screen = screen
            self.mouse_state.end_client = client
            return
        if message in MOUSE_UP_TO_BUTTON and self.mouse_state is not None:
            state = self.mouse_state
            self.mouse_state = None
            if not self.recording or not self.win32.is_active(self.target.hwnd):
                return
            screen, client, bounds, client_size = self._screen_and_client(data)
            if not self._active_and_inside(client, bounds):
                return
            state.end_screen = screen
            state.end_client = client
            duration = max(0.0, now - state.started_monotonic)
            distance = ((client[0] - state.start_client[0]) ** 2 + (client[1] - state.start_client[1]) ** 2) ** 0.5
            is_swipe = distance >= self.session.args.swipe_distance_threshold and duration >= self.session.args.swipe_duration_threshold
            try:
                raw_start = self.collector.translate_display_point(*state.start_client, state.rendered_bounds)
                raw_end = self.collector.translate_display_point(*state.end_client, bounds)
            except ValueError:
                return
            self.sequence += 1
            self.events.put({
                "sequence": self.sequence,
                "action_type": "swipe" if is_swipe else "tap",
                "button": state.button,
                "started_at_utc": state.started_at_utc,
                "observed_at_utc": self.collector.utc_now(),
                "observed_monotonic": now,
                "duration_seconds": duration,
                "movement_pixels": distance,
                "screen_start": state.start_screen,
                "screen_end": state.end_screen,
                "client_start": state.start_client,
                "client_end": state.end_client,
                "rendered_bounds": bounds,
                "client_size": client_size,
                "raw_start": raw_start,
                "raw_end": raw_end,
            })

    def _handle_keyboard(self, message: int, data: KBDLLHOOKSTRUCT) -> None:
        if message not in {WM_KEYDOWN, WM_SYSKEYDOWN}:
            return
        key = int(data.vkCode)
        if key == self.start_vk and not self.recording:
            self.recording = True
            self.started = True
            self.session.manifest["passive_recording"]["state"] = "recording"
            self.session.manifest["passive_recording"]["started_at_utc"] = self.collector.utc_now()
            self.session._append_log("passive_recording_started")
            self.session._persist_manifest()
            print(f"Passive recording started for 0x{self.target.hwnd:x}; actions are observed only.")
        elif key == self.stop_vk and self.started:
            self.recording = False
            self.stop_requested = True
            self.stop_event.set()
            self.session.manifest["passive_recording"]["state"] = "stopping"
            self.session._append_log("passive_recording_stop_requested")
            self.session._persist_manifest()
            self.win32.user32.PostQuitMessage(0)
        elif key == self.back_vk and self.recording and self.win32.is_active(self.target.hwnd):
            self.sequence += 1
            now = time.monotonic()
            self.events.put({
                "sequence": self.sequence,
                "action_type": "android_back",
                "button": "keyboard",
                "started_at_utc": self.collector.utc_now(),
                "observed_at_utc": self.collector.utc_now(),
                "observed_monotonic": now,
                "duration_seconds": 0.0,
                "movement_pixels": 0.0,
            })

    def _mouse_proc(self, code: int, message: int, pointer: int) -> int:
        if code >= 0:
            try:
                self._handle_mouse(message, ctypes.cast(pointer, ctypes.POINTER(MSLLHOOKSTRUCT)).contents)
            except Exception as exc:
                self.session._record_error("PASSIVE_MOUSE_HOOK_FAILED", str(exc), phase="passive-input", exception=type(exc).__name__)
        return int(self.win32.user32.CallNextHookEx(0, code, message, pointer))

    def _keyboard_proc(self, code: int, message: int, pointer: int) -> int:
        if code >= 0:
            try:
                self._handle_keyboard(message, ctypes.cast(pointer, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents)
            except Exception as exc:
                self.session._record_error("PASSIVE_KEYBOARD_HOOK_FAILED", str(exc), phase="passive-input", exception=type(exc).__name__)
        return int(self.win32.user32.CallNextHookEx(0, code, message, pointer))

    def _record_event(self, event: dict[str, Any]) -> None:
        c = self.collector
        step_id = f"step-{self.session.step_count + 1:03d}"
        before_snapshot, predates = self.buffer.before(event["observed_monotonic"])
        action_type = event["action_type"]
        if action_type == "android_back":
            display_coordinates = None
            raw_coordinates = None
            annotation = {"border": True}
        elif action_type == "tap":
            display_coordinates = {
                "coordinate_space": "selected_window_client",
                "point": {"x": event["client_end"][0], "y": event["client_end"][1]},
                "screen_point": {"x": event["screen_end"][0], "y": event["screen_end"][1]},
                "rendered_bounds": event["rendered_bounds"],
                "client_size": event["client_size"],
            }
            raw_coordinates = {"point": {"x": event["raw_end"][0], "y": event["raw_end"][1]}}
            annotation = {"raw_point": event["raw_end"]}
        else:
            display_coordinates = {
                "coordinate_space": "selected_window_client",
                "start": {"x": event["client_start"][0], "y": event["client_start"][1]},
                "end": {"x": event["client_end"][0], "y": event["client_end"][1]},
                "screen_start": {"x": event["screen_start"][0], "y": event["screen_start"][1]},
                "screen_end": {"x": event["screen_end"][0], "y": event["screen_end"][1]},
                "rendered_bounds": event["rendered_bounds"],
                "client_size": event["client_size"],
            }
            raw_coordinates = {
                "start": {"x": event["raw_start"][0], "y": event["raw_start"][1]},
                "end": {"x": event["raw_end"][0], "y": event["raw_end"][1]},
            }
            annotation = {"raw_start": event["raw_start"], "raw_end": event["raw_end"]}
        step: dict[str, Any] = {
            "step_id": step_id,
            "ordinal": self.session.step_count + 1,
            "action_type": action_type,
            **self.session._context_step_fields(),
            "display_coordinates": display_coordinates,
            "raw_coordinates": raw_coordinates,
            "before_frame_path": None,
            "after_frame_path": None,
            "annotated_frame_path": None,
            "annotation_implementation": None,
            "ui_dump_path": None,
            "dispatch_status": "passive_observed",
            "dispatch_transport": "none",
            "semantic_result": {"status": "unlabeled", "notes": ["passive observation; add semantic annotations separately"]},
            "started_at_utc": event["started_at_utc"],
            "observed_at_utc": event["observed_at_utc"],
            "completed_at_utc": None,
            "observed_sequence": event["sequence"],
            "input_observation": {
                "button": event["button"],
                "duration_seconds": event["duration_seconds"],
                "movement_pixels": event["movement_pixels"],
                "key_or_button": event["button"],
                "window_handle": f"0x{self.target.hwnd:x}",
                "window_title": self.target.title,
                "process_id": self.target.process_id,
                "before_frame_captured_at_utc": before_snapshot.captured_at_utc,
                "before_frame_predates_observed_input": predates,
            },
        }
        before_path = self.session.frames_dir / f"{step_id}-before.png"
        annotated_path = self.session.frames_dir / f"{step_id}-annotated.png"
        try:
            c.atomic_write_bytes(before_path, before_snapshot.payload)
            step["before_frame_path"] = self.session._rel(before_path)
            step["annotation_implementation"] = c.annotate_png(before_path, annotated_path, annotation)
            step["annotated_frame_path"] = self.session._rel(annotated_path)
        except Exception as exc:
            step["dispatch_status"] = "failed_before_observation"
            step["semantic_result"] = {"status": "error", "notes": [str(exc)]}
            self.session.manifest["structured_errors"].append({"timestamp_utc": c.utc_now(), "code": "PASSIVE_BEFORE_CAPTURE_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
        self.session.manifest["steps"].append(step)
        self.session.step_count += 1
        self.session._persist_manifest()
        if step["dispatch_status"] != "passive_observed":
            return
        try:
            time.sleep(max(0.0, self.session.args.post_action_delay))
            if self.session.source is None:
                raise c.CollectorError("no screenshot source is available")
            after_payload = self.session.source.capture()
            if c.png_dimensions(after_payload) != c.RAW_SIZE:
                raise c.CollectorError("passive after frame is not exactly 800x1280")
            after_path = self.session.frames_dir / f"{step_id}-after.png"
            c.atomic_write_bytes(after_path, after_payload)
            step["after_frame_path"] = self.session._rel(after_path)
        except Exception as exc:
            step["dispatch_status"] = "failed_after_observation"
            step["semantic_result"] = {"status": "unresolved", "notes": [str(exc), "passive after frame unavailable; no replay or retry"]}
            self.session.manifest["structured_errors"].append({"timestamp_utc": c.utc_now(), "code": "PASSIVE_AFTER_CAPTURE_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
        step["completed_at_utc"] = c.utc_now()
        self.session._append_log("passive_step_recorded", {"step_id": step_id, "dispatch_status": step["dispatch_status"]})
        self.session._persist_manifest()

    def _worker_loop(self) -> None:
        while True:
            event = self.events.get()
            try:
                if event is None:
                    return
                self._record_event(event)
            except Exception as exc:
                self.session._record_error("PASSIVE_STEP_FAILED", str(exc), phase="passive-step", exception=type(exc).__name__)
            finally:
                self.events.task_done()

    def _message_loop(self) -> None:
        self.mouse_callback = self.win32.hook_proc_type(self._mouse_proc)
        self.keyboard_callback = self.win32.hook_proc_type(self._keyboard_proc)
        self.mouse_hook = self.win32.install_hook(WH_MOUSE_LL, self.mouse_callback)
        try:
            self.keyboard_hook = self.win32.install_hook(WH_KEYBOARD_LL, self.keyboard_callback)
            message = wintypes.MSG()
            while not self.stop_event.is_set():
                result = self.win32.user32.GetMessageW(ctypes.byref(message), 0, 0, 0)
                if result <= 0:
                    break
                self.win32.user32.TranslateMessage(ctypes.byref(message))
                self.win32.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self.keyboard_hook:
                self.win32.user32.UnhookWindowsHookEx(self.keyboard_hook)
            if self.mouse_hook:
                self.win32.user32.UnhookWindowsHookEx(self.mouse_hook)

    def run(self) -> int:
        c = self.collector
        self.buffer.start()
        self.worker = threading.Thread(target=self._worker_loop, name="bluestacks-passive-action-writer", daemon=True)
        self.worker.start()
        print(f"Passive target: 0x{self.target.hwnd:x} pid={self.target.process_id} {self.target.title}")
        print(f"Press {self.session.args.start_hotkey} to start, {self.session.args.stop_hotkey} to stop; {self.session.args.back_hotkey} records an observation-only Back step. Inputs are never blocked or replayed.")
        try:
            if self.session.args.start_immediately:
                self.recording = True
                self.started = True
                self.session.manifest["passive_recording"]["state"] = "recording"
                self.session.manifest["passive_recording"]["started_at_utc"] = c.utc_now()
                self.session._persist_manifest()
            self._message_loop()
        except KeyboardInterrupt:
            self.stop_requested = False
            self.session.interrupt()
        finally:
            self.recording = False
            self.buffer.stop()
            self.events.put(None)
            self.events.join()
            if self.session.manifest["session_status"] == "active":
                if self.stop_requested and self.started:
                    self.session.manifest["passive_recording"]["state"] = "stopped"
                    self.session.mark_complete()
                else:
                    self.session.interrupt()
            if self.session.manifest["session_status"] != "failed":
                try:
                    result = self.session.export_zip()
                    print(json.dumps({"session_directory": str(self.session.session_dir), "manifest": str(self.session.manifest_path), "zip": result, "status": self.session.manifest["session_status"]}, sort_keys=True))
                except Exception as exc:
                    self.session._record_error("PASSIVE_ZIP_EXPORT_FAILED", str(exc), phase="passive-zip", exception=type(exc).__name__)
                    print(f"Passive session preserved without verified ZIP: {self.session.session_dir}: {exc}")
        return 0
