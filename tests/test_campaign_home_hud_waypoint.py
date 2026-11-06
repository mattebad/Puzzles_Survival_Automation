"""Actual HUD-edge Campaign Home frame requires one checked camera correction."""

from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2

from scripts import home_atlas_bluestacks as home
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks import home_atlas_vision as vision
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition, camera_origin
from tests.support.home_atlas import _ready
from tests.support.environment import requires_tesseract


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURES = ROOT / "tests/fixtures/campaign_home_entry"
FRAME = FIXTURES / "campaign-home-hud-edge-20261030.png"


class CampaignHomeHudWaypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = home.load_home_atlas(ATLAS)
        cls.localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)
        cls.building = cls.atlas.lookup_building(home.CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        cls.frame = cv2.imread(str(FRAME))
        cls.localization = cls.localizer.localize(cls.frame)
        cls.safe, cls.calibration = home.bluestacks_direct_pan_contract()
        cls.safe = home._campaign_home_entry_safe_region(cls.safe)

    def navigator(self, *, atlas=None, safe=None, calibration=None):
        return DirectPanNavigator(atlas or self.atlas, self.building.semantic_id,
                                  safe or self.safe, calibration or self.calibration)

    @requires_tesseract
    def test_actual_home_is_localized_but_anchor_cannot_clear_hud(self):
        self.assertTrue(home.is_clean_home_frame(self.frame))
        self.assertTrue(self.localization.recognized)
        self.assertGreater(self.localization.confidence, .98)
        self.assertLess(self.localization.residual_px, .2)
        diagnostics = {}
        binding = vision.bind_visible_building(self.frame, self.localization, self.building,
            home_is_clean=home.is_clean_home_frame, diagnostics=diagnostics)
        self.assertIsNone(binding)
        self.assertEqual(diagnostics["predicate"], "interaction_anchor_has_no_safe_hit_region")
        self.assertAlmostEqual(diagnostics["screen_anchor"][0], 551.43991, delta=.01)
        self.assertAlmostEqual(diagnostics["screen_anchor"][1], 418.25464, delta=.01)
        ordinary = self.navigator().plan(self.localization)
        self.assertEqual(ordinary.disposition, PlanDisposition.BIND)

    def test_actual_source_gets_one_bounded_effective_camera_plan_without_binding(self):
        navigator = self.navigator()
        plan = home._plan_mapped_home_entry(navigator, self.localization, None)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertEqual(plan.reason, "calculated_campaign_camera_waypoint")
        self.assertEqual(plan.drag_start, (450, 500))
        self.assertEqual(plan.drag_end, (417, 444))
        self.assertGreaterEqual(math.dist(plan.drag_start, plan.drag_end), self.calibration.minimum_drag_px)
        self.assertEqual(self.calibration.minimum_drag_px, 65)
        self.assertEqual(navigator.pan_count, 1)
        self.assertEqual(len(navigator.seen_viewports), 1)
        self.assertIs(navigator.last_plan, plan)
        self.assertEqual(navigator.safe_region, self.safe)
        forecast = home._campaign_entry_pan_forecast(navigator, self.localization, plan)
        self.assertIsNotNone(forecast["desired_hit_roi"])
        self.assertIsNotNone(forecast["predicted_hit_roi"])
        self.assertIs(forecast["input_authority"], False)
        for origin in (plan.viewport.desired_camera_origin, forecast["predicted_camera_origin"]):
            self.assertTrue(all(self.atlas.camera_origin_bounds[axis] <= origin[axis]
                                <= self.atlas.camera_origin_bounds[axis + 2] for axis in (0, 1)))
        # The placement deliberately allows the building's top above the safe
        # box; the binder's actual anchored hit region still fits unchanged.
        self.assertLess(self.building.polygon[0][1] - plan.viewport.desired_camera_origin[1], self.safe.screen_box[1])
        repeated = home._plan_mapped_home_entry(navigator, self.localization, None, campaign_waypoint_used=True)
        self.assertEqual(repeated.reason, "repeated_viewport")
        self.assertEqual(navigator.pan_count, 1)

    @requires_tesseract
    def test_driver_does_not_open_until_a_fresh_real_frame_binds(self):
        driver = home.BlueStacksLocalizeFirstHomeDriver(self.atlas, ATLAS, _ready(),
            self.building.semantic_id, localizer=self.localizer)
        first = driver.observe(self.frame)
        self.assertEqual(first.disposition, home.HomeDriverDisposition.PAN)
        self.assertIsNone(first.binding)
        self.assertTrue(driver.campaign_waypoint_used)
        successor = cv2.imread(str(FIXTURES / "canonical-home-20261029.png"))
        fresh = driver.observe(successor)
        self.assertEqual(fresh.disposition, home.HomeDriverDisposition.COMPLETE)
        self.assertIsNotNone(fresh.binding)
        self.assertEqual(fresh.binding.frame_sha256, vision.frame_digest(successor))
        self.assertEqual(driver.navigator.pan_count, 1)

    def test_ordinary_admission_and_single_waypoint_budget_remain_authoritative(self):
        for changes in ({"stale": True}, {"overlay": True}, {"confidence": .5}, {"profile_id": "wrong"}):
            with self.subTest(changes=changes):
                navigator = self.navigator()
                plan = home._plan_mapped_home_entry(navigator, replace(self.localization, **changes), None)
                self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
                self.assertEqual(navigator.pan_count, 0)
        for used, count, reason in ((True, 0, "campaign_camera_waypoint_already_used"),
                                    (False, 4, "maximum_pan_count")):
            with self.subTest(used=used, count=count):
                navigator = self.navigator()
                navigator.pan_count = count
                plan = home._plan_mapped_home_entry(navigator, self.localization, None, campaign_waypoint_used=used)
                self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
                self.assertEqual(plan.reason, reason)
                self.assertEqual(navigator.pan_count, count)
        navigator = self.navigator()
        candidate = home._campaign_camera_waypoint(navigator, self.localization)
        navigator.seen_viewports.add(tuple(round(value) for value in candidate.viewport.desired_camera_origin))
        plan = home._plan_mapped_home_entry(navigator, self.localization, None)
        self.assertEqual(plan.reason, "destination_already_visited")
        self.assertEqual(navigator.pan_count, 0)

    def test_missing_coverage_masks_bounds_and_ineffective_geometry_fail_closed(self):
        for kwargs in (
            {"atlas": replace(self.atlas, coverage_polygons=())},
            {"atlas": replace(self.atlas, camera_origin_bounds=None)},
            {"safe": replace(self.safe, fixed_hud_masks=((145, 180, 650, 1010),))},
            {"calibration": replace(self.calibration, drag_bounds=(400, 490, 500, 510))},
            {"calibration": replace(self.calibration, profile_id="wrong")},
        ):
            with self.subTest(kwargs=kwargs):
                navigator = self.navigator(**kwargs)
                plan = home._plan_mapped_home_entry(navigator, self.localization, None)
                self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
                self.assertEqual(navigator.pan_count, 0)

    def test_absent_binding_for_non_geometric_reason_does_not_grant_waypoint(self):
        frame = cv2.imread(str(FIXTURES / "canonical-home-20261029.png"))
        localization = self.localizer.localize(frame)
        navigator = self.navigator()
        plan = home._plan_mapped_home_entry(navigator, localization, None)
        self.assertEqual(plan.disposition, PlanDisposition.BIND)
        self.assertEqual(navigator.pan_count, 0)

    def test_fixture_is_byte_exact_with_immutable_source_provenance(self):
        record = json.loads(FRAME.with_suffix(".provenance.json").read_text())["frames"][0]
        self.assertEqual(record["fixture"], FRAME.name)
        self.assertEqual(hashlib.sha256(FRAME.read_bytes()).hexdigest(), record["transport_sha256"])
        self.assertEqual(self.frame.shape, (record["height"], record["width"], 3))

    def test_pan_reconciliation_is_persisted_before_next_plan_or_rejection_return(self):
        source = cv2.imread(str(FIXTURES / "nova-return-home-20261029.png"))
        owner = self

        class ReplayRuntime:
            def __init__(self, directory, accepted):
                self.session = directory
                self.ordinal = 0
                self.accepted = accepted
                self.after_pan = False

            def capture(self, label):
                self.ordinal += 1
                frame = owner.frame if self.accepted and self.after_pan else source
                ok, payload = cv2.imencode(".png", frame)
                png = payload.tobytes()
                path = self.session / f"{self.ordinal:04d}-{label}.png"
                path.write_bytes(png)
                return CapturedNativeFrame(frame.copy(), png, hashlib.sha256(png).hexdigest(), time.monotonic(), path)

        for accepted in (True, False):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                runtime = ReplayRuntime(Path(directory), accepted)
                snapshots = []
                original_plan = home._plan_mapped_home_entry

                def observe_next_plan(*args, **kwargs):
                    path = runtime.session / "navigate-session.json"
                    if path.exists():
                        snapshots.append(json.loads(path.read_text()))
                    return original_plan(*args, **kwargs)

                def dispatch(**kwargs):
                    kwargs["on_pre_dispatch_admitted"]()
                    runtime.after_pan = True
                    kwargs["post_pan_observer"]()
                    return None, SimpleNamespace(transport_calls=1, status=home.ActionStatus.CONFIRMED, reason="confirmed"), None, {}

                stack.enter_context(patch(
                    "scripts.atlas_runtime_startup.normalize_runtime_home_atlas_startup",
                    return_value=(self.localizer, []),
                ))
                stack.enter_context(patch.object(home, "is_clean_home_frame", return_value=True))
                stack.enter_context(patch.object(home, "dispatch_verified_navigate_pan", side_effect=dispatch))
                stack.enter_context(patch.object(home, "_plan_mapped_home_entry", side_effect=observe_next_plan))
                result = home.run_verified_campaign_home_atlas_entry(runtime, atlas_path=ATLAS,
                    execute=True, maximum_pans=1, settle_seconds=0)
                snapshot = json.loads((runtime.session / "navigate-session.json").read_text())
                ledger = snapshot["action_ledger"][-1]
                self.assertEqual(snapshot["latest_observation"]["frame"]["label"], "campaign-entry-00-settled")
                self.assertEqual(result["status"], "blocked_fail_closed")
                if accepted:
                    self.assertEqual(ledger["status"], "reconciled")
                    self.assertEqual(snapshot["displacement_history"][-1]["pan_ordinal"], 1)
                    self.assertTrue(snapshots)
                    self.assertEqual(snapshots[0]["action_ledger"][-1]["status"], "reconciled")
                    self.assertGreater(snapshot["displacement_history"][-1]["progress_px"], 8)
                else:
                    self.assertFalse(snapshots)
                    # Rejected movement retains the conservative dispatched
                    # ledger status while persisting its blocked observation.
                    self.assertEqual(ledger["status"], "dispatched")
                    self.assertEqual(snapshot["outcome"], "blocked")
                    self.assertEqual(snapshot["terminal_reason"], "repeated_viewport")
                    self.assertFalse(snapshot["latest_observation"]["localization_recognized"])


if __name__ == "__main__":
    unittest.main()
