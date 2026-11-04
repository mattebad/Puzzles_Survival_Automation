from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import atlas_flow_startup as startup
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.atlas_startup_normalizer import AtlasStartupDisposition
from tasks.home_atlas import AmbiguityState, ZoomIdentity
from tasks.home_atlas_vision import frame_digest
from tests.support.environment import requires_tesseract


REPO_ROOT = Path(__file__).resolve().parents[1]
HOME_BIO_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "home_base"
    / "native-home-bio-zoomed-20261029.png"
)
HOME_CANONICAL_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "home_base"
    / "native-home-zoom-settled-20261029.png"
)
RADIAL_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "nova_praise_preflight"
    / "research-lab-radial-07f3d826.png"
)
POPUP_FIXTURE = (
    REPO_ROOT
    / "tasks"
    / "assets"
    / "navigation"
    / "800x1280"
    / "reset_popup_source.png"
)


class _Runtime:
    execute = True
    in_flight_action = None
    session = Path("synthetic-atlas-startup")

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


class _Session:
    def __init__(self):
        self.input_count = 0
        self.terminal_status = None

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(
        self,
        *,
        capture,
        dispatch,
        recognize,
        authorize=None,
        settled_successor=None,
        **_kwargs,
    ):
        before = capture("immediate-before")
        if authorize is not None:
            authorize(before)
        self.input_count += 1
        dispatch(before)
        immediate = capture("immediate-post")
        state = recognize(immediate)
        if state == "unknown" and settled_successor is not None:
            state = recognize(settled_successor())
        return SimpleNamespace(status="completed" if state != "unknown" else "unknown")


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


def _captured_png(path: Path, marker: str) -> CapturedNativeFrame:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise AssertionError(f"fixture did not decode: {path}")
    png = path.read_bytes()
    return CapturedNativeFrame(
        frame,
        png,
        hashlib.sha256(png).hexdigest(),
        time.monotonic(),
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


class AtlasFlowStartupTests(unittest.TestCase):
    def _run(self, frames, states):
        runtime = _Runtime(frames)
        session = _Session()
        records = []
        contract = (object(), object())
        with (
            patch.object(
                startup, "BlueStacksHomeLocalizer", return_value=_localizer(states)
            ),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
            patch.object(startup, "is_clean_home_frame", return_value=True),
            patch.object(
                startup, "bluestacks_direct_pan_contract", return_value=contract
            ),
        ):
            result = startup.normalize_home_atlas_startup(
                session=session,
                runtime=runtime,
                capture=runtime.capture,
                atlas=object(),
                atlas_path=Path("atlas.json"),
                settle_seconds=0.0,
                evidence_records=records,
                adb="adb",
                serial="emulator-5554",
            )
        return result, runtime, session, records

    def test_canonical_home_is_ready_without_zoom(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        result, runtime, session, records = self._run(
            [_captured(frame, "canonical")],
            {id(frame): (True, ZoomIdentity.FULLY_ZOOMED_OUT, 0.9)},
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(
            records[-1]["disposition"], AtlasStartupDisposition.READY.value
        )

    def test_unknown_home_blocks_without_transport(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        runtime = _Runtime([_captured(frame, "unknown")])
        session = _Session()
        records = []
        with (
            patch.object(
                startup,
                "BlueStacksHomeLocalizer",
                return_value=_localizer(
                    {id(frame): (False, ZoomIdentity.UNKNOWN, 0.0)}
                ),
            ),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
            patch.object(startup, "is_clean_home_frame", return_value=True),
        ):
            with self.assertRaises(startup.AtlasStartupNormalizationError):
                startup.normalize_home_atlas_startup(
                    session=session,
                    runtime=runtime,
                    capture=runtime.capture,
                    atlas=object(),
                    atlas_path=Path("atlas.json"),
                    settle_seconds=0.0,
                    evidence_records=records,
                    adb="adb",
                    serial="emulator-5554",
                )
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(
            records[-1]["disposition"], AtlasStartupDisposition.BLOCKED.value
        )

    def test_supported_noncanonical_home_recovers_then_requires_canonical(self):
        source = np.zeros((1280, 800, 3), dtype=np.uint8)
        immediate = np.full((1280, 800, 3), 1, dtype=np.uint8)
        settled = np.full((1280, 800, 3), 2, dtype=np.uint8)
        _result, runtime, session, records = self._run(
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
        self.assertEqual(session.input_count, 1)
        self.assertEqual(
            records[0]["disposition"], AtlasStartupDisposition.RECOVER_ZOOM.value
        )
        self.assertEqual(
            records[-1]["disposition"], AtlasStartupDisposition.READY.value
        )

    @requires_tesseract
    def test_native_zoomed_home_uses_canonical_clean_home_for_one_bounded_zoom(self):
        source = _captured_png(HOME_BIO_FIXTURE, "native-bio-source")
        immediate = _captured_png(HOME_BIO_FIXTURE, "native-bio-immediate")
        settled = _captured_png(HOME_CANONICAL_FIXTURE, "native-bio-settled")
        states = {
            id(source.frame): (True, ZoomIdentity.ZOOMED_IN, 0.92),
            id(settled.frame): (True, ZoomIdentity.FULLY_ZOOMED_OUT, 0.9),
        }
        runtime = _Runtime([source, immediate, settled])
        session = _Session()
        records = []
        with (
            patch.object(startup, "BlueStacksHomeLocalizer", return_value=_localizer(states)),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
            patch.object(startup, "bluestacks_direct_pan_contract", return_value=(object(), object())),
        ):
            startup.normalize_home_atlas_startup(
                session=session,
                runtime=runtime,
                capture=runtime.capture,
                atlas=object(),
                atlas_path=Path("atlas.json"),
                settle_seconds=0.0,
                evidence_records=records,
                adb="adb",
                serial="emulator-5554",
            )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(session.input_count, 1)
        self.assertEqual(records[0]["disposition"], AtlasStartupDisposition.RECOVER_ZOOM.value)
        self.assertEqual(records[-1]["disposition"], AtlasStartupDisposition.READY.value)

    @requires_tesseract
    def test_popup_and_radial_home_sources_block_before_zoom_transport(self):
        for fixture in (POPUP_FIXTURE, RADIAL_FIXTURE):
            with self.subTest(fixture=fixture.name):
                source = _captured_png(fixture, f"blocked-{fixture.stem}")
                states = {
                    id(source.frame): (True, ZoomIdentity.ZOOMED_IN, 0.92),
                }
                runtime = _Runtime([source])
                session = _Session()
                records = []
                with (
                    patch.object(startup, "BlueStacksHomeLocalizer", return_value=_localizer(states)),
                    patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
                ):
                    with self.assertRaises(startup.AtlasStartupNormalizationError):
                        startup.normalize_home_atlas_startup(
                            session=session,
                            runtime=runtime,
                            capture=runtime.capture,
                            atlas=object(),
                            atlas_path=Path("atlas.json"),
                            settle_seconds=0.0,
                            evidence_records=records,
                            adb="adb",
                            serial="emulator-5554",
                        )
                self.assertEqual(runtime.input_count, 0)
                self.assertEqual(session.input_count, 0)
                self.assertEqual(records[-1]["disposition"], AtlasStartupDisposition.BLOCKED.value)

    def test_changed_zoom_source_is_denied_before_transport(self):
        source = _captured_png(HOME_BIO_FIXTURE, "source-bound")
        replacement = _captured_png(HOME_CANONICAL_FIXTURE, "changed-source")
        states = {
            id(source.frame): (True, ZoomIdentity.ZOOMED_IN, 0.92),
        }

        class ChangingSession(_Session):
            def run_action(self, *, capture, authorize=None, **kwargs):
                del kwargs
                capture("immediate-before")
                if authorize is not None:
                    authorize(replacement)
                raise AssertionError("changed source should be denied before dispatch")

        runtime = _Runtime([source])
        session = ChangingSession()
        records = []
        with (
            patch.object(startup, "BlueStacksHomeLocalizer", return_value=_localizer(states)),
            patch.object(startup, "ScrcpyMotionEventZoomTransport", _Transport),
            patch.object(startup, "is_clean_home_frame", return_value=True),
        ):
            with self.assertRaises(startup.AtlasStartupNormalizationError):
                startup.normalize_home_atlas_startup(
                    session=session,
                    runtime=runtime,
                    capture=runtime.capture,
                    atlas=object(),
                    atlas_path=Path("atlas.json"),
                    settle_seconds=0.0,
                    evidence_records=records,
                    adb="adb",
                    serial="emulator-5554",
                )
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(session.input_count, 0)


if __name__ == "__main__":
    unittest.main()
