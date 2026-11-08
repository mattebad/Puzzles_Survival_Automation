from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import atlas_runtime_startup as startup
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from tasks.home_atlas import AmbiguityState, ZoomIdentity
from tasks.home_atlas_vision import frame_digest


class _Runtime:
    execute = True
    in_flight_action = None
    session = Path("synthetic-runtime-atlas-startup")
    runner = SimpleNamespace(executable="adb", serial="emulator-5554")

    def __init__(self, frames):
        self.frames = list(frames)
        self.input_count = 0

    def capture(self, _label):
        return self.frames.pop(0)

    def measure_device_state(self):
        return "device"

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def dispatch_external_zoom(self, _source, *, action_key, transport):
        self.input_count += 1
        transport()


class _Transport:
    def __init__(self, **_kwargs):
        self.calls = 0

    def zoom_out_once(self):
        self.calls += 1


def _captured(frame, marker: str):
    return CapturedNativeFrame(
        frame,
        marker.encode(),
        hashlib.sha256(marker.encode()).hexdigest(),
        __import__("time").monotonic(),
        Path(f"{marker}.png"),
    )


def _localizer(states):
    class Localizer:
        canonical_reference = np.full((1280, 800, 3), 7, dtype=np.uint8)

        def localize(self, frame):
            state = states[id(frame)]
            return SimpleNamespace(
                recognized=state[0],
                zoom_identity=state[1],
                confidence=state[2],
                residual_px=1.0,
                frame_sha256=frame_digest(frame),
                ambiguity_state=AmbiguityState.NONE,
                stale=False,
                overlay=False,
            )

    return Localizer()


class AtlasRuntimeStartupTests(unittest.TestCase):
    def _run(self, frames, states, *, execute=True, home=True):
        runtime = _Runtime(frames)
        with (
            patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
                return_value=_localizer(states),
            ),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
            patch.object(startup, "is_clean_home_frame", return_value=True),
            patch.object(
                startup,
                "classify_home_base_live",
                return_value={"state": "HOME_BASE", "recognized": home},
            ),
        ):
            localizer, records = startup.normalize_runtime_home_atlas_startup(
                runtime=runtime,
                atlas=object(),
                atlas_path=Path("atlas.json"),
                execute=execute,
                settle_seconds=0.0,
            )
        return localizer, records, runtime

    def test_canonical_home_is_ready_without_input(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        _localizer_value, records, runtime = self._run(
            [_captured(frame, "canonical")],
            {id(frame): (True, ZoomIdentity.FULLY_ZOOMED_OUT, 0.9)},
        )
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(records[-1]["disposition"], "ready")

    def test_unknown_home_blocks_without_input(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with self.assertRaisesRegex(RuntimeError, "startup blocked"):
            self._run(
                [_captured(frame, "unknown")],
                {id(frame): (False, ZoomIdentity.UNKNOWN, 0.0)},
            )

    def test_supported_noncanonical_home_recovers_to_canonical(self):
        source = np.zeros((1280, 800, 3), dtype=np.uint8)
        immediate = np.full((1280, 800, 3), 1, dtype=np.uint8)
        settled = np.full((1280, 800, 3), 2, dtype=np.uint8)
        _localizer_value, records, runtime = self._run(
            [
                _captured(source, "source"),
                _captured(immediate, "immediate"),
                _captured(settled, "settled"),
            ],
            {
                id(source): (False, ZoomIdentity.ZOOMED_IN, 0.92),
                id(settled): (True, ZoomIdentity.FULLY_ZOOMED_OUT, 0.9),
            },
        )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(
            [row["disposition"] for row in records], ["recover_zoom", "ready"]
        )

    def test_unrecognized_home_cannot_authorize_supported_zoom(self):
        source = np.zeros((1280, 800, 3), dtype=np.uint8)
        with self.assertRaisesRegex(
            RuntimeError, "not positively recognized clean Home"
        ):
            self._run(
                [_captured(source, "source")],
                {id(source): (False, ZoomIdentity.ZOOMED_IN, 0.92)},
                home=False,
            )


def _solid(value: int) -> np.ndarray:
    return np.full((1280, 800, 3), value, dtype=np.uint8)


class _ZoomDevice:
    """Device-free ADB surface: pixels change only through accounted transport."""

    executable = "fake-adb-not-executed"
    serial = "emulator-5554"

    def __init__(self, frames, *, state, zoom_successors, tap_successor=None):
        self.frames = frames
        self.state = state
        self.zoom_successors = zoom_successors
        self.tap_successor = tap_successor
        self.zooms = 0
        self.taps = []

    def capture_png(self):
        ok, payload = cv2.imencode(".png", self.frames[self.state])
        assert ok
        return payload.tobytes()

    def get_state(self):
        return "device"

    def shell_text(self, *arguments):
        assert arguments == ("dumpsys", "window", "windows")
        return "mCurrentFocus=Window{1 u0 com.global.ztmslg/.MainActivity}\n"

    def dispatch_tap(self, point):
        self.taps.append(point)
        self.state = self.tap_successor

    def zoom(self):
        self.zooms += 1
        self.state = self.zoom_successors[self.state]


class SessionOwnedAtlasStartupTests(unittest.TestCase):
    """Real DevelopmentSession and native runtime; only ADB pixels/transport are replayed."""

    FRAMES = {
        "zoomed-a": _solid(10),
        "canonical-a": _solid(20),
        "zoomed-b": _solid(30),
        "canonical-b": _solid(40),
        "unknown": _solid(50),
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        lock = patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3")
        lock.start()
        self.addCleanup(lock.stop)
        states = {}
        for name, frame in self.FRAMES.items():
            if name.startswith("zoomed"):
                states[frame_digest(frame)] = (False, ZoomIdentity.ZOOMED_IN, 0.92)
            elif name.startswith("canonical"):
                states[frame_digest(frame)] = (True, ZoomIdentity.FULLY_ZOOMED_OUT, 0.9)
            else:
                states[frame_digest(frame)] = (False, ZoomIdentity.UNKNOWN, 0.0)
        self.states = states

    def _session(self):
        return boundary.DevelopmentSession(
            owner="atlas-startup-session-test",
            invocation_id="atlas-startup-session-test-1",
            session_directory=self.root / "session",
            max_inputs=4,
        )

    def _runtime(self, device):
        runtime = LocalBlueStacksRuntime(device, self.root / "runtime", execute=True)
        runtime.max_inputs = 4
        return runtime

    def _normalize(self, runtime, session, device):
        states = self.states

        class Localizer:
            canonical_reference = _solid(7)

            def localize(self, frame):
                digest = frame_digest(frame)
                recognized, zoom_identity, confidence = states[digest]
                return SimpleNamespace(
                    recognized=recognized, zoom_identity=zoom_identity, confidence=confidence,
                    residual_px=1.0, frame_sha256=digest, ambiguity_state=AmbiguityState.NONE,
                    stale=False, overlay=False,
                )

        class Transport:
            def __init__(self, **_kwargs):
                pass

            def zoom_out_once(self):
                device.zoom()

        unknown = frame_digest(self.FRAMES["unknown"])
        with (
            patch("scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=Localizer()),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", Transport),
            patch.object(startup, "is_clean_home_frame", side_effect=lambda frame: frame_digest(frame) != unknown),
            patch.object(startup, "classify_home_base_live",
                         return_value={"state": "HOME_BASE", "recognized": True}),
        ):
            return startup.normalize_runtime_home_atlas_startup(
                runtime=runtime, atlas=object(), atlas_path=Path("atlas.json"),
                execute=True, settle_seconds=0.0, session=session,
            )

    @staticmethod
    def _dispatch_rows(runtime):
        rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines()]
        return [row for row in rows if row.get("type") == "dispatch"]

    def test_route_inputs_interleave_between_two_session_owned_zoom_normalizations(self):
        device = _ZoomDevice(
            self.FRAMES, state="zoomed-a",
            zoom_successors={"zoomed-a": "canonical-a", "zoomed-b": "canonical-b"},
            tap_successor="zoomed-b",
        )
        with self._session() as session:
            runtime = self._runtime(device)
            _localizer, first = self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
            result = session.run_action(
                action_class="navigation",
                label="route-owned-tap",
                capture=runtime.capture,
                dispatch=lambda before: runtime.tap(
                    before, target_identity="route-target", target_roi=(390, 630, 410, 650),
                    action_key="route-owned-tap-1",
                ),
                recognize=lambda _frame: "home_base",
                consequence_class="navigation_only",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual((runtime.input_count, session.input_count), (2, 2))
            _localizer, second = self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (3, 3))
            labels = [row["label"] for row in session.actions]
            statuses = [row["status"] for row in session.actions]
        self.assertEqual([row["disposition"] for row in first], ["recover_zoom", "ready"])
        self.assertEqual([row["disposition"] for row in second], ["recover_zoom", "ready"])
        self.assertEqual((device.zooms, len(device.taps)), (2, 1))
        self.assertEqual(
            [row["target_identity"] for row in self._dispatch_rows(runtime)],
            ["home-zoom-out", "route-target", "home-zoom-out"],
        )
        self.assertEqual(statuses, ["completed", "completed", "completed"])
        self.assertTrue(labels[0].startswith("home-atlas-startup-zoom-01-"))
        self.assertEqual(labels[1], "route-owned-tap")
        self.assertTrue(labels[2].startswith("home-atlas-startup-zoom-01-"))
        self.assertNotEqual(labels[0], labels[2])

    def test_unknown_zoom_successor_denies_any_later_normalization_input(self):
        device = _ZoomDevice(self.FRAMES, state="zoomed-a", zoom_successors={"zoomed-a": "unknown"})
        with self._session() as session:
            runtime = self._runtime(device)
            with self.assertRaisesRegex(RuntimeError, "startup blocked"):
                self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
            self.assertEqual(session.actions[-1]["status"], "unknown")
            device.state = "zoomed-b"
            with self.assertRaisesRegex(RuntimeError, "unresolved session action"):
                self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
        self.assertEqual(device.zooms, 1)
        self.assertEqual(len(self._dispatch_rows(runtime)), 1)

    def test_unmoved_camera_never_receives_identical_zoom_input(self):
        device = _ZoomDevice(self.FRAMES, state="zoomed-a", zoom_successors={"zoomed-a": "zoomed-a"})
        with self._session() as session:
            runtime = self._runtime(device)
            with self.assertRaisesRegex(RuntimeError, "no frame progress"):
                self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
            with self.assertRaises(startup.AtlasRuntimeStartupError) as denied:
                self._normalize(runtime, session, device)
            self.assertEqual(denied.exception.records[-1]["reason"], "identical_zoom_source_already_dispatched")
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
        self.assertEqual(device.zooms, 1)
        self.assertEqual(len(self._dispatch_rows(runtime)), 1)

    def test_exhausted_session_budget_dispatches_no_zoom(self):
        device = _ZoomDevice(
            self.FRAMES, state="zoomed-a", zoom_successors={"zoomed-a": "canonical-a"},
            tap_successor="zoomed-b",
        )
        with boundary.DevelopmentSession(
            owner="atlas-startup-session-test", invocation_id="atlas-startup-session-test-1",
            session_directory=self.root / "session", max_inputs=1,
        ) as session:
            runtime = self._runtime(device)
            session.run_action(
                action_class="navigation", label="route-owned-tap", capture=runtime.capture,
                dispatch=lambda before: runtime.tap(
                    before, target_identity="route-target", target_roi=(390, 630, 410, 650),
                    action_key="route-owned-tap-1",
                ),
                recognize=lambda _frame: "home_base", consequence_class="navigation_only",
            )
            with self.assertRaisesRegex(boundary.DevelopmentSessionError, "input limit"):
                self._normalize(runtime, session, device)
            self.assertEqual((runtime.input_count, session.input_count), (1, 1))
        self.assertEqual(device.zooms, 0)


if __name__ == "__main__":
    unittest.main()
