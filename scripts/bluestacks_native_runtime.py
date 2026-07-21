"""Shared native BlueStacks runtime boundary for local workflow integration.

The workflow controllers own semantic decisions.  This module owns only exact local-device
selection, fresh native capture, evidence retention, duplicate-input guards, and transport.
It never connects ADB, never registers a production task, and never enables a scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Protocol

import cv2
import numpy as np

from scripts.bluestacks_flow_collector import (
    ADBRunner,
    EXPECTED_PACKAGE,
    is_permitted_local_bluestacks_serial,
    parse_foreground_package,
)


NativeBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class CapturedNativeFrame:
    frame: np.ndarray
    png: bytes
    sha256: str
    captured_monotonic: float
    path: Path


def captured_native_frame_from_png(
    payload: bytes,
    *,
    captured_monotonic: float,
    path: Path,
) -> CapturedNativeFrame:
    """Apply the production native PNG validation used by live capture and replay."""

    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1280, 800):
        raise RuntimeError("BlueStacks capture is not a native 800x1280 frame")
    return CapturedNativeFrame(
        frame,
        payload,
        hashlib.sha256(payload).hexdigest(),
        captured_monotonic,
        path,
    )


@dataclass(frozen=True)
class IntegratedRouteResult:
    status: str
    reason: str
    actions_completed: int
    session: str


class NativeRuntimePort(Protocol):
    execute: bool
    in_flight_action: str | None
    session: Path

    def capture(self, label: str) -> CapturedNativeFrame: ...

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None: ...

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
    ) -> None: ...

    def long_press(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        duration_ms: int,
        action_key: str,
        consequential: bool = True,
    ) -> None: ...

    def type_text(
        self,
        source: CapturedNativeFrame,
        *,
        text: str,
        action_key: str,
    ) -> None: ...

    def clear_numeric_text(
        self,
        source: CapturedNativeFrame,
        *,
        max_digits: int,
        action_key: str,
    ) -> None: ...

    def press_key(
        self,
        source: CapturedNativeFrame,
        *,
        key: str,
        action_key: str,
    ) -> None: ...

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        continuation_of: str | None = None,
    ) -> None: ...

    def reconcile(self, action_key: str, status: str, post: CapturedNativeFrame, reason: str) -> None: ...

    def record_recovery(
        self,
        *,
        action_key: str,
        previous_session: str,
        previous_source_sha256: str,
        previous_post_sha256: str,
        current: CapturedNativeFrame,
        expected_completion_timestamp: str,
        reason: str,
    ) -> None: ...


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def box_center(box: NativeBox) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        raise RuntimeError("target is outside native 800x1280 bounds")
    return ((x0 + x1) // 2, (y0 + y1) // 2)


class LocalBlueStacksRuntime:
    """Evidence-retaining local runtime with one unresolved consequential action maximum."""

    def __init__(
        self,
        runner: ADBRunner,
        session: Path,
        *,
        execute: bool,
        frame_max_age_seconds: float = 30.0,
    ) -> None:
        self.runner = runner
        self.session = session
        self.execute = execute
        self.frame_max_age_seconds = frame_max_age_seconds
        self.frames = session / "frames"
        self.frames.mkdir(parents=True, exist_ok=False)
        self.events = session / "events.jsonl"
        self.ordinal = 0
        self.action_keys: set[str] = set()
        self.frame_actions: set[tuple[str, str, NativeBox | None]] = set()
        self.in_flight_action: str | None = None

    @classmethod
    def connect(
        cls,
        *,
        adb: str,
        serial: str,
        output_directory: Path,
        workflow: str,
        execute: bool,
    ) -> "LocalBlueStacksRuntime":
        if not is_permitted_local_bluestacks_serial(serial):
            raise RuntimeError("serial is not a permitted local BlueStacks endpoint")
        runner = ADBRunner(adb, serial)
        devices = {device.serial: device.state for device in runner.list_devices()}
        if devices.get(serial) != "device" or runner.get_state() != "device":
            raise RuntimeError("exact local BlueStacks serial is not in device state")
        foreground = parse_foreground_package(runner.shell_text("dumpsys", "window", "windows"))
        if foreground != EXPECTED_PACKAGE:
            raise RuntimeError(f"unexpected foreground package: {foreground!r}")
        session = output_directory / f"{workflow}-{utc_stamp()}"
        return cls(runner, session, execute=execute)

    def _event(self, kind: str, payload: dict[str, object]) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": kind, **payload}
        with self.events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def capture(self, label: str) -> CapturedNativeFrame:
        payload = self.runner.capture_png()
        captured = time.monotonic()
        self.ordinal += 1
        path = self.frames / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        result = captured_native_frame_from_png(
            payload,
            captured_monotonic=captured,
            path=path,
        )
        self._event("capture", {"label": label, "path": str(path), "sha256": result.sha256})
        return result

    def _authorize_dispatch(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        target_identity: str,
        target_roi: NativeBox | None,
        consequential: bool,
        continuation_of: str | None,
    ) -> None:
        age = time.monotonic() - source.captured_monotonic
        if age < 0 or age > self.frame_max_age_seconds:
            raise RuntimeError("dispatch source frame is stale")
        if self.in_flight_action is not None and continuation_of != self.in_flight_action:
            raise RuntimeError("prior consequential action is unresolved")
        if continuation_of is not None and continuation_of != self.in_flight_action:
            raise RuntimeError("continuation does not match the in-flight action")
        if not action_key or action_key in self.action_keys:
            raise RuntimeError("duplicate or missing action key")
        fingerprint = (source.sha256, target_identity, target_roi)
        if fingerprint in self.frame_actions:
            raise RuntimeError("identical source/target input is forbidden")
        if consequential and self.in_flight_action is not None:
            raise RuntimeError("cannot start a second consequential action")
        self.action_keys.add(action_key)
        self.frame_actions.add(fingerprint)

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        point = box_center(target_roi)
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=target_roi,
            consequential=consequential,
            continuation_of=continuation_of,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "target_roi": target_roi,
                "point": point,
                "source_sha256": source.sha256,
                "consequential": consequential,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        if consequential:
            self.in_flight_action = action_key
        self.runner.dispatch_tap(point)

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
    ) -> None:
        if not all(0 <= point[0] < 800 and 0 <= point[1] < 1280 for point in (start, end)):
            raise RuntimeError("swipe must remain inside native 800x1280 bounds")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=(
                min(start[0], end[0]),
                min(start[1], end[1]),
                min(800, max(start[0], end[0]) + 1),
                min(1280, max(start[1], end[1]) + 1),
            ),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "start": start,
                "end": end,
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self.runner.dispatch_swipe(start, end)

    def long_press(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        duration_ms: int,
        action_key: str,
        consequential: bool = True,
    ) -> None:
        if not 500 <= duration_ms <= 12_000:
            raise RuntimeError("long press duration must be between 500 and 12000 ms")
        point = box_center(target_roi)
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=target_roi,
            consequential=consequential,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "target_roi": target_roi,
                "point": point,
                "duration_ms": duration_ms,
                "gesture": "zero-distance-long-press",
                "source_sha256": source.sha256,
                "consequential": consequential,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        if consequential:
            self.in_flight_action = action_key
        self.runner.dispatch_swipe(point, point, duration_ms=duration_ms)

    def type_text(
        self,
        source: CapturedNativeFrame,
        *,
        text: str,
        action_key: str,
    ) -> None:
        if not text or not text.isdigit():
            raise RuntimeError("native route text input is restricted to decimal quantities")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="quantity-editor",
            target_roi=(560, 1030, 760, 1160),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "quantity-editor",
                "text": text,
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self.runner.dispatch_text(text)

    def clear_numeric_text(
        self,
        source: CapturedNativeFrame,
        *,
        max_digits: int,
        action_key: str,
    ) -> None:
        if not 1 <= max_digits <= 4:
            raise RuntimeError("numeric editor clear is restricted to one through four digits")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="quantity-editor-clear",
            target_roi=(560, 1030, 760, 1160),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "quantity-editor-clear",
                "max_digits": max_digits,
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self.runner.dispatch_clear_numeric_text(max_digits)

    def press_key(
        self,
        source: CapturedNativeFrame,
        *,
        key: str,
        action_key: str,
    ) -> None:
        normalized = key.strip().upper()
        if normalized not in {"ENTER", "BACK"}:
            raise RuntimeError("native route key input is restricted to ENTER or BACK; numeric clearing has a dedicated route")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=f"key:{normalized}",
            target_roi=None,
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": f"key:{normalized}",
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self.runner.dispatch_keyevent("ENTER" if normalized == "ENTER" else "4")

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        continuation_of: str | None = None,
    ) -> None:
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="android-back",
            target_roi=None,
            consequential=False,
            continuation_of=continuation_of,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "android-back",
                "source_sha256": source.sha256,
                "consequential": False,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self.runner.dispatch_back()

    def reconcile(self, action_key: str, status: str, post: CapturedNativeFrame, reason: str) -> None:
        if self.in_flight_action != action_key:
            raise RuntimeError("reconciliation does not match the in-flight action")
        if status not in {"confirmed", "failed_confirmed", "unresolved"}:
            raise ValueError("invalid reconciliation status")
        self._event(
            "reconcile",
            {
                "action_key": action_key,
                "status": status,
                "post_sha256": post.sha256,
                "post_path": str(post.path),
                "reason": reason,
            },
        )
        if status != "unresolved":
            self.in_flight_action = None

    def record_recovery(
        self,
        *,
        action_key: str,
        previous_session: str,
        previous_source_sha256: str,
        previous_post_sha256: str,
        current: CapturedNativeFrame,
        expected_completion_timestamp: str,
        reason: str,
    ) -> None:
        """Record a fresh live reconciliation without recreating a dispatch."""

        if not action_key or not previous_session or not previous_source_sha256 or not previous_post_sha256:
            raise ValueError("recovery requires the prior action and evidence identities")
        self._event(
            "recovery_reconcile",
            {
                "action_key": action_key,
                "previous_session": previous_session,
                "previous_source_sha256": previous_source_sha256,
                "previous_post_sha256": previous_post_sha256,
                "current_sha256": current.sha256,
                "current_path": str(current.path),
                "expected_completion_timestamp": expected_completion_timestamp,
                "reason": reason,
                "execute": self.execute,
            },
        )
