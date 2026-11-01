"""Supply's measured camera dead zone keeps its minimum gesture and HUD fences."""
from dataclasses import replace
import hashlib
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2

from scripts import navigation_development_boundary as boundary
from scripts import supply_depot_free_canary as canary
from scripts.atlas_startup_normalizer import AtlasStartupDisposition
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import DevelopmentSession, DevelopmentSessionError
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition, camera_origin, plan_direct_pan
from tasks.home_atlas_vision import BlueStacksHomeLocalizer


FIXTURE = Path(__file__).parent / "fixtures/supply_depot/native-entry-dead-zone-20261029.png"


class SupplyCameraReframeTests(unittest.TestCase):
    def test_drawer_collapse_requires_fresh_home_before_any_input(self):
        path = FIXTURE.parent / "native-drawer-occluded-radial-20261101.png"
        png, image = path.read_bytes(), cv2.imread(str(path))
        captured = CapturedNativeFrame(image, png, hashlib.sha256(png).hexdigest(), 1., path)
        def forbidden(*args, **kwargs):
            self.fail("unknown Home cannot authorize drawer input")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"), \
                    patch.object(canary, "is_clean_home_frame", return_value=False):
                with DevelopmentSession(owner="offline-drawer", invocation_id="drawer", session_directory=root / "session", max_inputs=2) as session:
                    with self.assertRaises(canary.PerceptionBundleError):
                        canary._collapse_home_event_drawer(session, SimpleNamespace(tap=forbidden),
                            lambda label: captured, settle_seconds=0)
                    self.assertEqual(session.input_count, 0)

    def test_drawer_collapse_does_not_repeat_input_when_expanded_state_remains(self):
        path = FIXTURE.parent / "native-drawer-occluded-radial-20261101.png"
        png, image = path.read_bytes(), cv2.imread(str(path))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ordinal, taps = 0, []
            def capture(label):
                nonlocal ordinal
                ordinal += 1
                return CapturedNativeFrame(image, png, hashlib.sha256(png).hexdigest(),
                    float(ordinal), root / f"{ordinal}-{label}.png")
            runtime = SimpleNamespace(tap=lambda source, **kwargs: taps.append(kwargs))
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"), \
                    patch.object(canary, "is_clean_home_frame", return_value=True):
                with DevelopmentSession(owner="offline-drawer", invocation_id="drawer", session_directory=root / "session", max_inputs=2) as session:
                    result = canary._collapse_home_event_drawer(session, runtime, capture, settle_seconds=0)
                    self.assertEqual(result.status, "unknown")
                    self.assertEqual(session.input_count, 1)
            self.assertEqual([tap["target_identity"] for tap in taps], ["home-event-drawer-collapse"])
            self.assertEqual(taps[0]["target_roi"], (729, 1057, 764, 1075))

    @classmethod
    def setUpClass(cls):
        cls.png = FIXTURE.read_bytes()
        cls.frame = cv2.imread(str(FIXTURE))
        cls.atlas = load_home_atlas(canary.ATLAS_PATH)
        cls.localization = BlueStacksHomeLocalizer(cls.atlas, canary.ATLAS_PATH).localize(cls.frame)

    def navigator(self):
        safe, calibration = canary._supply_pan_contract()
        return DirectPanNavigator(self.atlas, canary.SUPPLY_DEPOT_BUILDING_ID,
                                  safe, calibration, maximum_pans=canary.MAX_PANS)

    def test_actual_dead_zone_gets_one_bounded_camera_only_reframe(self):
        navigator = self.navigator()
        self.assertTrue(self.localization.recognized)
        normal = plan_direct_pan(self.atlas, self.localization, navigator.building_id,
                                 navigator.safe_region, navigator.calibration)
        self.assertEqual(normal.disposition, PlanDisposition.REJECTED)
        self.assertGreater(dict(normal.viewport.rejection_counts)["gesture_below_effective_minimum"], 0)
        self.assertFalse(canary._supply_entry_viewport_safe(self.atlas, self.localization))
        plan, active, reframe = canary._plan_supply_entry(navigator, self.localization, reframe_used=False)
        self.assertTrue(reframe)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertIsNot(active, navigator)
        self.assertIs(active.last_plan, plan)
        self.assertEqual(active.maximum_pans, 1)
        self.assertGreaterEqual(math.dist(plan.drag_start, plan.drag_end), navigator.calibration.minimum_drag_px)
        current = camera_origin(self.localization)
        for axis in (0, 1):
            predicted = current[axis] + plan.predicted_camera_displacement[axis]
            self.assertGreaterEqual(predicted, self.atlas.camera_origin_bounds[axis])
            self.assertLessEqual(predicted, self.atlas.camera_origin_bounds[axis + 2])

    def test_reframe_is_not_repeated_and_does_not_bypass_pan_cap(self):
        for used, cap_reached in ((True, False), (False, True)):
            navigator = self.navigator()
            if cap_reached:
                navigator.pan_count = navigator.maximum_pans
            plan, active, reframe = canary._plan_supply_entry(navigator, self.localization, reframe_used=used)
            self.assertFalse(reframe)
            self.assertIs(active, navigator)
            self.assertEqual(plan.disposition, PlanDisposition.REJECTED)

    def test_no_progress_and_wrong_direction_do_not_authorize_continuation(self):
        navigator = self.navigator()
        plan, active, _ = canary._plan_supply_entry(navigator, self.localization, reframe_used=False)
        same = replace(self.localization, frame_sha256="1" * 64)
        self.assertFalse(active.record_progress(self.localization, same).accepted)
        matrix = [list(row) for row in self.localization.screen_to_atlas]
        for axis in (0, 1):
            matrix[axis][2] -= plan.requested_camera_displacement[axis] / 2
        wrong = replace(self.localization, frame_sha256="2" * 64,
                        screen_to_atlas=tuple(tuple(row) for row in matrix))
        progress = active.record_progress(self.localization, wrong)
        self.assertFalse(progress.accepted)
        self.assertEqual(progress.reason, "movement_wrong_direction")

    def test_native_consumer_stops_after_one_no_progress_reframe_and_respects_input_cap(self):
        test = self
        for max_inputs in (0, 10):
            with self.subTest(max_inputs=max_inputs), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)

                class Runtime:
                    session = root / "runtime"
                    ordinal = 0
                    swipes = []

                    def capture(self, label):
                        self.ordinal += 1
                        path = self.session / f"{self.ordinal:04d}-{label}.png"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(test.png)
                        return CapturedNativeFrame(test.frame.copy(), test.png,
                            hashlib.sha256(test.png).hexdigest(), time.monotonic(), path)

                    def swipe(self, before, **kwargs):
                        self.swipes.append((before, kwargs))

                    def tap(self, *_args, **_kwargs):
                        raise AssertionError("A camera waypoint cannot authorize building or Claim input")

                runtime = Runtime()
                startup = SimpleNamespace(disposition=AtlasStartupDisposition.READY,
                    reason="canonical_zoom_ready", source_frame_sha256=self.localization.frame_sha256,
                    recovery_input_ordinal=None)
                with (
                    patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
                    patch.object(canary, "BlueStacksAtlasStartupNormalizer", return_value=SimpleNamespace(observe=lambda frame: startup)),
                    patch.object(canary, "BlueStacksHomeLocalizer", return_value=SimpleNamespace(localize=lambda frame: self.localization)),
                    patch.object(canary, "_bind_home_building", return_value=(self.localization, None)),
                    patch.object(canary, "_recognize", return_value=SimpleNamespace(recognized=False)),
                    patch.object(canary, "bind_supply_depot_claim_supply", return_value=None),
                    patch.object(canary, "recognize_supply_depot_radial", return_value=False),
                    patch.object(canary, "is_clean_home_frame", return_value=True),
                    patch.object(canary, "_arena_exit_target", return_value=None),
                ):
                    with DevelopmentSession(owner="offline-supply-reframe", invocation_id="offline-supply-reframe",
                                            session_directory=root / "session", max_inputs=max(1, max_inputs)) as session:
                        if max_inputs == 0:
                            session.input_count = session.max_inputs
                            with self.assertRaises(DevelopmentSessionError):
                                canary.run(session=session, runtime=runtime, session_directory=root / "session", settle_seconds=0)
                            self.assertEqual(session.input_count, session.max_inputs)
                        else:
                            result = canary.run(session=session, runtime=runtime, session_directory=root / "session", settle_seconds=0)
                            self.assertEqual(result["reason"], "pan_no_progress:0")
                            self.assertEqual(session.input_count, 1)
                self.assertEqual(len(runtime.swipes), int(max_inputs != 0))


if __name__ == "__main__":
    unittest.main()
