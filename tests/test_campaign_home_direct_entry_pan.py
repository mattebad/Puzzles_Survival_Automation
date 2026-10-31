"""Native Campaign camera entry plans a safe hit region before any building tap."""

from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import home_atlas_bluestacks as home
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition, _bounded_drag_delta, camera_origin
from tasks import home_atlas_vision as vision
from tests.test_home_atlas_verified_route import _ready


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURES = ROOT / "tests/fixtures/campaign_home_entry"
FRAME = FIXTURES / "nova-return-home-20261029.png"


class CampaignHomeDirectEntryPanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = home.load_home_atlas(ATLAS)
        cls.localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)
        cls.building = cls.atlas.lookup_building(home.CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        cls.frame = cv2.imread(str(FRAME))
        cls.localization = cls.localizer.localize(cls.frame)
        cls.canonical = cv2.imread(str(FIXTURES / "canonical-home-20261029.png"))
        cls.after_noah = cv2.imread(str(FIXTURES / "after-noah-home-20261029.png"))
        cls.after_noah_localization = cls.localizer.localize(cls.after_noah)
        cls.short_pan = cv2.imread(str(FIXTURES / "campaign-home-short-pan-20261029.png"))
        cls.short_pan_localization = cls.localizer.localize(cls.short_pan)

    def driver(self, *, atlas=None, building_id=home.CAMPAIGN_HOME_ATLAS_BUILDING_ID, maximum_pans=8):
        return home.BlueStacksLocalizeFirstHomeDriver(
            atlas or self.atlas, ATLAS, _ready(), building_id, localizer=self.localizer,
            maximum_pans=maximum_pans,
        )

    def test_native_current_campaign_is_unbound_and_generic_radial_planning_rejects(self):
        self.assertTrue(home.is_clean_home_frame(self.frame))
        self.assertTrue(self.localization.recognized)
        self.assertAlmostEqual(self.localization.residual_px, 0.127933, delta=0.01)
        diagnostic = {}
        binding = vision.bind_visible_building(
            self.frame, self.localization, self.building,
            home_is_clean=home.is_clean_home_frame, diagnostics=diagnostic,
        )
        self.assertIsNone(binding)
        self.assertEqual(diagnostic["predicate"], "target_coverage_outside_safe_region")
        self.assertGreater(diagnostic["screen_anchor"][0], 800)
        safe, calibration = home.bluestacks_direct_pan_contract()
        plan = DirectPanNavigator(self.atlas, self.building.semantic_id, safe, calibration).plan(self.localization)
        self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertEqual(plan.reason, "no_recoverable_actionable_viewport")
        rejections = dict(plan.viewport.rejection_counts)
        self.assertEqual(sum(rejections.values()), 48)
        self.assertGreater(rejections.get("insufficient_action_body_visibility", 0), 0)

    def test_native_campaign_driver_plans_bounded_pan_without_fabricating_building_binding(self):
        driver = self.driver()
        step = driver.observe(self.frame)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.PAN)
        self.assertIsNone(step.binding)
        self.assertEqual(step.source_frame_sha256, vision.frame_digest(self.frame))
        self.assertEqual(step.plan.drag_start, (450, 500))
        self.assertEqual(step.plan.drag_end, (300, 564))
        self.assertEqual(driver.navigator.pan_count, 1)
        xmin, ymin, xmax, ymax = driver.calibration.drag_bounds
        for x, y in (step.plan.drag_start, step.plan.drag_end):
            self.assertTrue(xmin <= x <= xmax and ymin <= y <= ymax)
        displacement = step.plan.predicted_camera_displacement
        self.assertTrue(all(math.isfinite(value) for value in displacement))
        origin = camera_origin(step.localization)
        predicted = tuple(origin[index] + displacement[index] for index in (0, 1))
        bounds = self.atlas.camera_origin_bounds
        self.assertTrue(bounds[0] <= predicted[0] <= bounds[2])
        self.assertTrue(bounds[1] <= predicted[1] <= bounds[3])
        # This is geometry-only forecasting. No future frame, localization,
        # identity or BuildingBinding is manufactured to authorize an input.
        inverse = np.linalg.inv(np.asarray(step.localization.screen_to_atlas)[:2, :2])
        projected = (np.asarray(self.building.polygon) - predicted) @ inverse.T
        anchor = tuple((np.asarray(self.building.interaction_anchor) - predicted) @ inverse.T)
        target, reason, _ = vision._target_roi(projected, anchor, self.building.platform_binding_policy["bluestacks"])
        self.assertIsNone(reason)
        self.assertEqual(target, (419, 376, 560, 518))
        self.assertAlmostEqual(anchor[0], 489.9134, delta=0.1)
        self.assertAlmostEqual(anchor[1], 446.7401, delta=0.1)
        forecast = home._campaign_entry_pan_forecast(driver.navigator, step.localization, step.plan)
        self.assertEqual(forecast["predicted_hit_roi"], target)
        self.assertEqual(forecast["predicted_camera_origin"], predicted)
        self.assertIs(forecast["input_authority"], False)

    def test_existing_current_native_campaign_binding_still_completes_without_pan(self):
        step = self.driver().observe(self.canonical)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.COMPLETE)
        self.assertIsNotNone(step.binding)
        self.assertEqual(step.binding.target_roi, (411, 356, 560, 506))
        self.assertEqual(step.binding.frame_sha256, vision.frame_digest(self.canonical))
        self.assertIsNone(step.plan.drag_start)

    def test_actual_after_noah_pan_rounds_inside_verified_camera_bounds(self):
        driver = self.driver()
        localization = self.after_noah_localization
        self.assertTrue(home.is_clean_home_frame(self.after_noah))
        self.assertTrue(localization.recognized)
        self.assertAlmostEqual(localization.residual_px, 0.062158, delta=0.001)
        original = home.plan_direct_pan(self.atlas, localization, self.building.semantic_id,
                                        driver.safe_region, driver.calibration)
        self.assertEqual(original.drag_end, (309, 520))
        self.assertIsNone(home._campaign_entry_pan_forecast(driver.navigator, localization, original))
        origin = camera_origin(localization)
        self.assertGreater(origin[0] + original.predicted_camera_displacement[0],
                           self.atlas.camera_origin_bounds[2])

        step = driver.observe(self.after_noah, localization=localization)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.PAN)
        self.assertIsNone(step.binding)
        self.assertEqual(step.plan.drag_start, (450, 500))
        self.assertEqual(step.plan.drag_end, (310, 520))
        self.assertEqual(step.plan.predicted_camera_displacement, (294.0, -42.0))
        self.assertIs(driver.navigator.last_plan, step.plan)
        self.assertEqual(driver.navigator.pan_count, 1)
        forecast = home._campaign_entry_pan_forecast(driver.navigator, localization, step.plan)
        self.assertIs(forecast["input_authority"], False)
        for axis in (0, 1):
            predicted = forecast["predicted_camera_origin"][axis]
            self.assertLessEqual(self.atlas.camera_origin_bounds[axis], predicted)
            self.assertLessEqual(predicted, self.atlas.camera_origin_bounds[axis + 2])
            self.assertEqual(step.plan.predicted_remaining_displacement[axis],
                             step.plan.requested_camera_displacement[axis]
                             - step.plan.predicted_camera_displacement[axis])

    def test_rounding_does_not_repair_large_overshoot_wrong_direction_or_no_progress(self):
        driver = self.driver()
        localization = self.after_noah_localization
        original = home.plan_direct_pan(self.atlas, localization, self.building.semantic_id,
                                        driver.safe_region, driver.calibration)
        for end, displacement in (
            ((308, 520), (298.2, -42.0)),
            ((591, 480), (-296.1, 42.0)),
            ((450, 500), (0.0, 0.0)),
            ((309, 520), (296.2, -42.0)),
        ):
            with self.subTest(end=end, displacement=displacement):
                invalid = replace(original, drag_end=end, predicted_camera_displacement=displacement)
                self.assertIs(home.inward_rounded_camera_pan(driver.navigator, localization, invalid), invalid)
                self.assertIsNone(home._campaign_entry_pan_forecast(driver.navigator, localization, invalid))
        self.assertEqual(driver.navigator.pan_count, 0)
        self.assertFalse(driver.navigator.seen_viewports)

    def test_actual_short_final_approach_uses_one_measured_camera_waypoint(self):
        driver = self.driver()
        current = self.short_pan_localization
        self.assertTrue(home.is_clean_home_frame(self.short_pan))
        self.assertAlmostEqual(camera_origin(current)[0], 569.786842, delta=0.001)
        normal = home.plan_direct_pan(self.atlas, current, self.building.semantic_id,
                                      driver.safe_region, driver.calibration)
        self.assertEqual(normal.reason, "gesture_below_effective_minimum")
        self.assertAlmostEqual(normal.requested_camera_displacement[0], 77.000618, delta=0.001)
        step = driver.observe(self.short_pan, localization=current)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.PAN)
        self.assertEqual(step.reason, "calculated_campaign_camera_waypoint")
        self.assertIsNone(step.binding)
        self.assertEqual(step.plan.drag_start, (450, 500))
        self.assertEqual(step.plan.drag_end, (414, 441))
        self.assertGreaterEqual(math.dist(step.plan.drag_start, step.plan.drag_end),
                                driver.calibration.minimum_drag_px)
        self.assertEqual(driver.calibration.minimum_drag_px, 65.0)
        self.assertEqual(driver.navigator.safe_region, driver.safe_region)
        self.assertIs(driver.navigator.last_plan, step.plan)
        self.assertEqual(driver.navigator.pan_count, 1)
        self.assertTrue(driver.campaign_waypoint_used)
        forecast = home._campaign_entry_pan_forecast(driver.navigator, current, step.plan)
        self.assertIs(forecast["input_authority"], False)
        self.assertIsNotNone(forecast["desired_hit_roi"])
        self.assertIsNotNone(forecast["predicted_hit_roi"])
        for axis, coordinate in enumerate(forecast["predicted_camera_origin"]):
            self.assertLessEqual(self.atlas.camera_origin_bounds[axis], coordinate)
            self.assertLessEqual(coordinate, self.atlas.camera_origin_bounds[axis + 2])

    def test_short_approach_cannot_repeat_waypoint_or_exceed_existing_pan_budget(self):
        for used, count in ((True, 0), (False, 4)):
            with self.subTest(used=used, count=count):
                driver = self.driver(maximum_pans=4)
                driver.campaign_waypoint_used = used
                driver.navigator.pan_count = count
                step = driver.observe(self.short_pan, localization=self.short_pan_localization)
                self.assertEqual(step.disposition, home.HomeDriverDisposition.BLOCKED)
                self.assertEqual(driver.navigator.pan_count, count)
                self.assertIsNone(step.binding)

    def test_short_pan_fixture_matches_its_immutable_native_source_provenance(self):
        fixture = FIXTURES / "campaign-home-short-pan-20261029.png"
        record = json.loads(fixture.with_suffix(".provenance.json").read_text())["frames"][0]
        self.assertEqual(record["transport_sha256"], hashlib.sha256(fixture.read_bytes()).hexdigest())
        self.assertEqual(record["source"], ".local-captures/automation-service-authorized/soak-20261029T171434658731Z-7900d159/campaign/campaign-ap-1-15-9-20261029T171444996777Z/frames/0010-campaign-entry-02-immediate-before.png")

    def test_rounded_plan_preserves_repeat_destination_and_maximum_pan_guards(self):
        localization = self.after_noah_localization
        driver = self.driver()
        first = driver.observe(self.after_noah, localization=localization)
        repeated = driver.observe(self.after_noah, localization=localization)
        self.assertEqual(first.disposition, home.HomeDriverDisposition.PAN)
        self.assertEqual(repeated.disposition, home.HomeDriverDisposition.BLOCKED)
        self.assertEqual(repeated.reason, "repeated_viewport")
        self.assertEqual(driver.navigator.pan_count, 1)

        limited = self.driver()
        limited.navigator.pan_count = limited.navigator.maximum_pans
        blocked = limited.observe(self.after_noah, localization=localization)
        self.assertEqual(blocked.disposition, home.HomeDriverDisposition.BLOCKED)
        self.assertEqual(blocked.reason, "maximum_pan_count")

        visited = self.driver()
        proposal = home.plan_direct_pan(self.atlas, localization, self.building.semantic_id,
                                        visited.safe_region, visited.calibration)
        visited.navigator.seen_viewports.add(tuple(round(value) for value in proposal.viewport.desired_camera_origin))
        blocked = visited.observe(self.after_noah, localization=localization)
        self.assertEqual(blocked.disposition, home.HomeDriverDisposition.BLOCKED)
        self.assertEqual(blocked.reason, "destination_already_visited")
        self.assertEqual(visited.navigator.pan_count, 0)

    def test_rounding_does_not_change_other_facility_plans_or_calibration(self):
        driver = self.driver(building_id="home.building.research_lab")
        original = home.plan_direct_pan(self.atlas, self.after_noah_localization, self.building.semantic_id,
                                        self.driver().safe_region, driver.calibration)
        with patch.object(home, "inward_rounded_camera_pan", side_effect=AssertionError("no implicit route opt-in")):
            step = driver.observe(self.after_noah, localization=self.after_noah_localization)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.COMPLETE)
        self.assertIsNotNone(step.binding)
        self.assertEqual(driver.navigator.pan_count, 0)

        last_plan = driver.navigator.last_plan
        rounded = home.inward_rounded_camera_pan(driver.navigator, self.after_noah_localization, original)
        self.assertEqual(rounded.drag_end, (310, 520))
        self.assertEqual(driver.navigator.pan_count, 0)
        self.assertFalse(driver.navigator.seen_viewports)
        self.assertIs(driver.navigator.last_plan, last_plan)
        calibration = replace(self.driver().calibration, minimum_drag_px=142.0)
        campaign = self.driver()
        campaign.navigator.calibration = calibration
        self.assertIs(home.inward_rounded_camera_pan(campaign.navigator, self.after_noah_localization, original), original)

    def test_full_campaign_entry_consumer_calculates_native_pan_in_zero_input_dry_run(self):
        fixture_png = FRAME.read_bytes()
        owner = self

        class NativeReplayRuntime:
            def __init__(self, directory):
                self.session = directory
                self.ordinal = self.swipe_count = self.tap_count = 0
                self.captures = []

            def capture(self, label):
                self.ordinal += 1
                path = self.session / f"{self.ordinal:04d}-{label}.png"
                path.write_bytes(fixture_png)
                captured = CapturedNativeFrame(owner.frame.copy(), fixture_png,
                                               hashlib.sha256(fixture_png).hexdigest(), time.monotonic(), path)
                self.captures.append(captured)
                return captured

            def swipe(self, *_args, **_kwargs):
                self.swipe_count += 1
                raise AssertionError("dry-run must not swipe")

            def tap(self, *_args, **_kwargs):
                self.tap_count += 1
                raise AssertionError("an unbound dry-run must not tap")

        bindings = []

        def bind_current(*args, **kwargs):
            binding = vision.bind_visible_building(*args, **kwargs)
            bindings.append(binding)
            return binding

        with tempfile.TemporaryDirectory() as directory:
            runtime = NativeReplayRuntime(Path(directory))
            with patch("scripts.atlas_runtime_startup.normalize_runtime_home_atlas_startup",
                       return_value=(self.localizer, [])), \
                    patch.object(home, "bind_visible_building", side_effect=bind_current):
                result = home.run_verified_campaign_home_atlas_entry(
                    runtime, atlas_path=ATLAS, execute=False, settle_seconds=0,
                )
        self.assertEqual(result["status"], "dry-run", result)
        self.assertEqual(result["records"][0]["disposition"], PlanDisposition.PAN.value)
        self.assertEqual(result["records"][0]["reason"], "calculated_direct_pan")
        self.assertEqual(bindings, [None])
        self.assertEqual(len(runtime.captures), 1)
        self.assertEqual((runtime.swipe_count, runtime.tap_count), (0, 0))
        self.assertEqual(runtime.captures[0].png, fixture_png)

    def test_actual_left_edge_forecast_allows_intermediate_offscreen_target_without_tap_authority(self):
        native = cv2.imread(str(ATLAS.parent / "tiles/viewport-015.png"))
        localization = self.localizer.localize(native)
        self.assertTrue(localization.recognized)
        self.assertEqual(localization.frame_sha256, vision.frame_digest(native))
        origin = camera_origin(localization)
        self.assertAlmostEqual(origin[0], 0.967773, delta=0.01)
        driver = self.driver()
        # This historical night UI supplies actual Atlas geometry. Its current
        # Home classification still fails, so it grants no live source authority.
        current = driver.observe(native, localization=localization)
        self.assertEqual(current.disposition, home.HomeDriverDisposition.BLOCKED)
        self.assertIsNone(current.binding)
        self.assertEqual(driver.navigator.pan_count, 0)
        navigator = DirectPanNavigator(self.atlas, self.building.semantic_id,
                                       driver.safe_region, driver.calibration)
        first_plan = home._plan_mapped_home_entry(navigator, localization, None)
        self.assertEqual(first_plan.disposition, PlanDisposition.PAN)
        forecast = home._campaign_entry_pan_forecast(navigator, localization, first_plan)
        self.assertIsNotNone(forecast["desired_hit_roi"])
        self.assertIsNone(forecast["predicted_hit_roi"])
        self.assertIs(forecast["input_authority"], False)
        first_predicted = forecast["predicted_camera_origin"]
        self.assertGreater(self.building.interaction_anchor[0] - first_predicted[0], 800)

        # SIMULATED second-step geometry only: this does not create a future
        # CurrentFrame, LocalizationResult, Observation, identity or binding.
        desired = first_plan.viewport.desired_camera_origin
        residual = tuple(desired[index] - first_predicted[index] for index in (0, 1))
        second_drag = _bounded_drag_delta(residual, driver.calibration)
        simulated_second_origin = (
            first_predicted[0] - second_drag[0] * driver.calibration.camera_px_per_drag_x,
            first_predicted[1] - second_drag[1] * driver.calibration.camera_px_per_drag_y,
        )
        bounds = self.atlas.camera_origin_bounds
        for predicted in (first_predicted, simulated_second_origin):
            self.assertTrue(all(math.isfinite(value) for value in predicted))
            self.assertTrue(bounds[0] <= predicted[0] <= bounds[2])
            self.assertTrue(bounds[1] <= predicted[1] <= bounds[3])
        self.assertLess(math.dist(first_predicted, desired), math.dist(origin, desired))
        self.assertLess(math.dist(simulated_second_origin, desired), math.dist(first_predicted, desired))
        first_drag = tuple(first_plan.drag_end[index] - first_plan.drag_start[index] for index in (0, 1))
        for drag in (first_drag, second_drag):
            self.assertGreaterEqual(math.hypot(*drag), driver.calibration.minimum_drag_px)
            self.assertLessEqual(abs(drag[0]), driver.calibration.maximum_drag_x)
            self.assertLessEqual(abs(drag[1]), driver.calibration.maximum_drag_y)
        inverse = np.linalg.inv(np.asarray(localization.screen_to_atlas)[:2, :2])
        projected = (np.asarray(self.building.polygon) - simulated_second_origin) @ inverse.T
        anchor = tuple((np.asarray(self.building.interaction_anchor) - simulated_second_origin) @ inverse.T)
        roi, reason, _ = vision._target_roi(projected, anchor, self.building.platform_binding_policy["bluestacks"])
        self.assertIsNone(reason)
        self.assertIsNotNone(roi)
        x0, y0, x1, y1 = roi
        self.assertFalse(any(x0 < hx1 and x1 > hx0 and y0 < hy1 and y1 > hy0
                             for hx0, hy0, hx1, hy1 in driver.safe_region.fixed_hud_masks))

    def test_intermediate_forecast_rejects_wrong_direction_nonfinite_or_out_of_bounds_motion(self):
        driver = self.driver()
        proposed = home.plan_direct_pan(self.atlas, self.localization, self.building.semantic_id,
                                       driver.safe_region, driver.calibration)
        for displacement in ((-10.0, 0.0), (0.0, 0.0), (10000.0, 0.0), (float("nan"), 0.0)):
            with self.subTest(displacement=displacement):
                invalid = replace(proposed, predicted_camera_displacement=displacement)
                self.assertIsNone(home._campaign_entry_pan_forecast(driver.navigator, self.localization, invalid))
        self.assertEqual(driver.navigator.pan_count, 0)
        self.assertFalse(driver.navigator.seen_viewports)

    def test_invalid_current_localization_never_becomes_campaign_pan_or_entry(self):
        for invalid in (
            {"stale": True}, {"overlay": True}, {"profile_id": "wrong-profile"},
            {"confidence": 0.5}, {"residual_px": 10.0}, {"screen_to_atlas": None},
            {"frame_sha256": "f" * 64},
        ):
            with self.subTest(invalid=invalid):
                step = self.driver().observe(self.frame, localization=replace(self.localization, **invalid))
                self.assertNotIn(step.disposition, (home.HomeDriverDisposition.PAN,
                                                     home.HomeDriverDisposition.COMPLETE,
                                                     home.HomeDriverDisposition.BIND))

    def test_unsafe_mapped_geometry_or_missing_coverage_cannot_use_direct_pan(self):
        invalid_buildings = (
            replace(self.building, interaction_anchor_override=(1020.0, 470.0)),  # outside polygon
            replace(self.building, interaction_anchor_override=(1215.0, 470.0)),  # forecast under HUD
        )
        invalid_atlases = [replace(self.atlas, coverage_polygons=()),
                           replace(self.atlas, camera_origin_bounds=None)]
        for building in invalid_buildings:
            invalid_atlases.append(replace(self.atlas, buildings=tuple(
                building if value.semantic_id == building.semantic_id else value for value in self.atlas.buildings
            )))
        for atlas in invalid_atlases:
            with self.subTest(atlas=atlas):
                step = self.driver(atlas=atlas).observe(self.frame, localization=self.localization)
                self.assertEqual(step.disposition, home.HomeDriverDisposition.BLOCKED)
                self.assertIsNone(step.binding)

    def test_campaign_configuration_preserves_hud_bounds_and_other_facility_planning(self):
        default, calibration = home.bluestacks_direct_pan_contract()
        campaign = self.driver()
        research = self.driver(building_id="home.building.research_lab")
        self.assertEqual(campaign.safe_region.screen_box, default.screen_box)
        self.assertEqual(campaign.safe_region.fixed_hud_masks, default.fixed_hud_masks)
        self.assertEqual(campaign.calibration, calibration)
        self.assertEqual(research.safe_region, default)
        self.assertIsNotNone(research.safe_region.planning_policy)

    def test_unsafe_forecast_rejects_before_consuming_navigator_pan_budget_or_history(self):
        building = replace(self.building, interaction_anchor_override=(1215.0, 470.0))
        atlas = replace(self.atlas, buildings=tuple(
            building if value.semantic_id == building.semantic_id else value for value in self.atlas.buildings
        ))
        driver = self.driver(atlas=atlas)
        proposed = home.plan_direct_pan(atlas, self.localization, building.semantic_id,
                                        driver.safe_region, driver.calibration)
        self.assertEqual(proposed.disposition, PlanDisposition.PAN)
        self.assertIsNone(home._campaign_entry_pan_forecast(driver.navigator, self.localization, proposed))
        self.assertEqual(driver.navigator.pan_count, 0)
        self.assertFalse(driver.navigator.seen_viewports)
        step = driver.observe(self.frame, localization=self.localization)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.BLOCKED)
        self.assertEqual(step.reason, "campaign_hit_region_forecast_unsafe")
        self.assertIsNone(step.binding)
        self.assertEqual(driver.navigator.pan_count, 0)
        self.assertFalse(driver.navigator.seen_viewports)

    def test_new_fixture_is_exact_native_copy_with_source_provenance(self):
        record = json.loads((FIXTURES / "nova-return-home-20261029.provenance.json").read_text(encoding="utf-8"))["frames"][0]
        self.assertEqual(record["fixture"], FRAME.name)
        self.assertEqual(hashlib.sha256(FRAME.read_bytes()).hexdigest(), record["transport_sha256"])
        self.assertEqual(record["source"], ".local-captures/automation-service-authorized/campaign-20261029T104211889782Z/campaign-ap-1-15-9-20261029T104221432026Z/frames/0004-campaign-entry-00-immediate-before.png")
        self.assertEqual(self.frame.shape, (record["height"], record["width"], 3))

    def test_after_noah_fixture_is_exact_native_copy_with_source_provenance(self):
        fixture = FIXTURES / "after-noah-home-20261029.png"
        record = json.loads(fixture.with_suffix(".provenance.json").read_text(encoding="utf-8"))["frames"][0]
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), record["transport_sha256"])
        self.assertEqual(record["source"], ".local-captures/automation-service-authorized/soak-20261029T141236151646Z-62a228ca/campaign/campaign-ap-1-15-9-20261029T141511108737Z/frames/0007-campaign-entry-01-immediate-before.png")
        self.assertEqual(self.after_noah.shape, (record["height"], record["width"], 3))


if __name__ == "__main__":
    unittest.main()
