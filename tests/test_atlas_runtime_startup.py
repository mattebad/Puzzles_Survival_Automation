from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import unittest
from unittest.mock import patch

import numpy as np

from scripts import atlas_runtime_startup as startup
from scripts.bluestacks_native_runtime import CapturedNativeFrame
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


if __name__ == "__main__":
    unittest.main()
