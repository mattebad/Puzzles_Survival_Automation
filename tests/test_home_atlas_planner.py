from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract, command_navigate_building
from tasks.home_atlas import (
    AmbiguityState,
    AtlasViewport,
    BuildingBinding,
    HomeAtlas,
    LocalizationResult,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
)
from tasks.home_atlas_planner import (
    DirectPanNavigator,
    GestureCalibration,
    PlanDisposition,
    SafeInteractionRegion,
    measure_pan_progress,
    plan_building_viewport,
    plan_direct_pan,
)
from tasks.home_atlas_vision import (
    BLUESTACKS_PLATFORM,
    BLUESTACKS_PROFILE_ID,
    bind_visible_building,
    frame_digest,
)


PROFILE = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
SAFE = SafeInteractionRegion("home-default", (145, 180, 650, 1010), (400, 600))
CALIBRATION = GestureCalibration(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (450, 500), (250, 250, 650, 950), 2.1, 2.1, 35, 150, 180)


def building(*, semantic_id: str = "home.building.bank", polygon=((900, 700), (1040, 700), (1040, 840), (900, 840)), eligible: bool = True) -> SemanticBuilding:
    return SemanticBuilding(
        semantic_id,
        "Bank",
        polygon,
        0.98,
        ("v1",),
        recognition={"bluestacks": {"label": "Bank"}},
        semantic_proof=("visible Bank label",),
        interaction_eligible=eligible,
        platform_binding_policy={"bluestacks": {"label": "Bank"}},
    )


def atlas(target: SemanticBuilding | None = None, *, coverage=True, bounds=(0.0, 0.0, 700.0, 1500.0)) -> HomeAtlas:
    target = target or building()
    viewport = AtlasViewport("v1", "unused.png", "a" * 64, "now", ((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((0, 0), (800, 0), (800, 1280), (0, 1280)), 1, 0, "translation")
    polygons = (((0, 0), (1500, 0), (1500, 2800), (0, 2800)),) if coverage else (((0, 0), (500, 0), (500, 500), (0, 500)),)
    return HomeAtlas(3, "test", "1", PROFILE, "fully_zoomed_out", "atlas pixels", (0, 0), 1500, 2800, "atlas.png", "test", "test", polygons, (), (viewport,), (target,), polygons, bounds)


def localization(x: float = 0, y: float = 0, digest: str = "a" * 64) -> LocalizationResult:
    return LocalizationResult(True, BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, ZoomIdentity.FULLY_ZOOMED_OUT, ((1, 0, x), (0, 1, y), (0, 0, 1)), ((x, y), (x + 800, y), (x + 800, y + 1280), (x, y + 1280)), 0.95, ("v1",), 0.4, AmbiguityState.NONE, "interior", digest, "now")


class MinimalPanPlannerTests(unittest.TestCase):
    def test_target_already_safe_is_zero_pan_and_requires_binding(self):
        target = building(polygon=((300, 400), (440, 400), (440, 540), (300, 540)))
        plan = plan_direct_pan(atlas(target), localization(), target.semantic_id, SAFE, CALIBRATION)
        self.assertEqual(plan.disposition, PlanDisposition.BIND)
        self.assertIsNone(plan.drag_start)

    def test_visible_but_hud_occluded_plans_pan(self):
        target = building(polygon=((460, 400), (600, 400), (600, 540), (460, 540)))
        plan = plan_building_viewport(atlas(target), localization(400, 0), target.semantic_id, SAFE)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertLess(plan.residual_atlas[0], 0)

    def test_desired_viewport_and_exact_inverse_drag_direction(self):
        plan = plan_direct_pan(atlas(), localization(), "home.building.bank", SAFE, CALIBRATION)
        self.assertEqual(plan.viewport.desired_camera_origin, (570.0, 170.0))
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertLess(plan.drag_end[0], plan.drag_start[0])
        self.assertLess(plan.drag_end[1], plan.drag_start[1])
        self.assertLessEqual(abs(plan.drag_end[0] - plan.drag_start[0]), 150)
        self.assertLessEqual(abs(plan.drag_end[1] - plan.drag_start[1]), 180)

    def test_camera_clamp_and_map_edge_failure(self):
        target = building(polygon=((10, 500), (110, 500), (110, 620), (10, 620)))
        plan = plan_building_viewport(atlas(target, bounds=(0, 0, 700, 1500)), localization(400, 0), target.semantic_id, SAFE)
        self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertEqual(plan.reason, "map_edge_clamp_before_target")
        self.assertIn("x", plan.clamped_axes)

    def test_coverage_and_non_actionable_rejections(self):
        self.assertEqual(plan_building_viewport(atlas(coverage=False), localization(), "home.building.bank", SAFE).reason, "target_outside_verified_coverage")
        blocked = building(eligible=False)
        self.assertEqual(plan_building_viewport(atlas(blocked), localization(), blocked.semantic_id, SAFE).reason, "non_actionable_building")

    def test_progress_corrective_plan_wrong_direction_and_no_progress(self):
        first = plan_direct_pan(atlas(), localization(), "home.building.bank", SAFE, CALIBRATION)
        progressed = localization(300, 90, "b" * 64)
        progress = measure_pan_progress(localization(), progressed, first, CALIBRATION)
        self.assertTrue(progress.accepted)
        corrective = plan_direct_pan(atlas(), progressed, "home.building.bank", SAFE, CALIBRATION)
        self.assertEqual(corrective.disposition, PlanDisposition.PAN)
        self.assertLess(np.hypot(*corrective.requested_camera_displacement), np.hypot(*first.requested_camera_displacement))
        self.assertEqual(measure_pan_progress(localization(), localization(0, 0, "c" * 64), first, CALIBRATION).reason, "no_measured_progress")
        self.assertEqual(measure_pan_progress(localization(), localization(-100, -40, "d" * 64), first, CALIBRATION).reason, "movement_wrong_direction")

    def test_repeated_viewport_maximum_pan_and_post_pan_localization_failure(self):
        controller = DirectPanNavigator(atlas(), "home.building.bank", SAFE, CALIBRATION, maximum_pans=1)
        self.assertEqual(controller.plan(localization()).disposition, PlanDisposition.PAN)
        self.assertEqual(controller.plan(localization(100, 50, "b" * 64)).reason, "maximum_pan_count")
        controller = DirectPanNavigator(atlas(), "home.building.bank", SAFE, CALIBRATION)
        controller.plan(localization())
        self.assertEqual(controller.plan(localization(digest="c" * 64)).reason, "repeated_viewport")
        failed = replace(localization(digest="d" * 64), recognized=False, screen_to_atlas=None, ambiguity_state=AmbiguityState.INSUFFICIENT_LANDMARKS)
        self.assertEqual(measure_pan_progress(localization(), failed, plan_direct_pan(atlas(), localization(), "home.building.bank", SAFE, CALIBRATION), CALIBRATION).reason, "post_pan_localization_failed")

    def test_coordinate_only_success_rejected_and_semantic_binding_completes(self):
        target = building(polygon=((300, 400), (440, 400), (440, 540), (300, 540)))
        world = atlas(target)
        loc = localization()
        controller = DirectPanNavigator(world, target.semantic_id, SAFE, CALIBRATION)
        self.assertEqual(controller.plan(loc).disposition, PlanDisposition.BIND)
        controller = DirectPanNavigator(world, target.semantic_id, SAFE, CALIBRATION)
        coordinate_only = BuildingBinding(target.semantic_id, (320, 420, 420, 520), loc.frame_sha256, 0.9, ())
        self.assertEqual(controller.plan(loc, coordinate_only).reason, "current_frame_building_binding_rejected")
        controller = DirectPanNavigator(world, target.semantic_id, SAFE, CALIBRATION)
        semantic = replace(coordinate_only, semantic_evidence=("current-frame OCR: Bank",))
        self.assertEqual(controller.plan(loc, semantic).disposition, PlanDisposition.COMPLETE)

    def test_bluestacks_and_bliss_calibration_are_separate(self):
        safe, blue = bluestacks_direct_pan_contract()
        self.assertEqual(safe.region_id, "home-default")
        bliss = replace(blue, platform="Bliss OS", profile_id="pns-800x1280-v1")
        plan = plan_direct_pan(atlas(), localization(), "home.building.bank", SAFE, bliss)
        self.assertEqual(plan.reason, "gesture_calibration_profile_mismatch")
        self.assertNotEqual(blue.profile_id, bliss.profile_id)

    def test_generic_binder_requires_current_frame_semantics(self):
        frame = np.zeros((1280, 800, 3), np.uint8)
        loc = replace(localization(), frame_sha256=frame_digest(frame))
        target = building(polygon=((300, 400), (440, 400), (440, 540), (300, 540)))
        self.assertIsNone(bind_visible_building(frame, loc, target, ocr=lambda image, psm: "unknown"))
        binding = bind_visible_building(frame, loc, target, ocr=lambda image, psm: "Bank")
        self.assertIsNotNone(binding)
        self.assertIn("current-frame OCR", binding.semantic_evidence[0])

    def test_project_owned_route_dry_run_issues_no_input(self):
        class Runtime:
            execute = False
            in_flight_action = None

            def __init__(self, session: Path):
                self.session = session
                self.swipes = 0

            def capture(self, label):
                frame = np.zeros((1280, 800, 3), np.uint8)
                return CapturedNativeFrame(frame, b"png", "f" * 64, 1.0, self.session / f"{label}.png")

            def swipe(self, *args, **kwargs):
                self.swipes += 1

        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            loc = localization()
            args = SimpleNamespace(
                execute=False,
                yes=False,
                atlas=Path(directory) / "atlas.json",
                building_id="home.building.bank",
                maximum_pans=4,
                settle_seconds=0,
                adb="unused",
                serial="emulator-5554",
                output_directory=Path(directory),
            )
            fake_localizer = SimpleNamespace(localize=lambda frame: loc)
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=atlas()), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ):
                self.assertEqual(command_navigate_building(args), 0)
            self.assertEqual(runtime.swipes, 0)

    def test_project_owned_route_completes_only_with_semantic_binding(self):
        target = building(polygon=((300, 400), (440, 400), (440, 540), (300, 540)))
        world = atlas(target)

        class Runtime:
            execute = True
            in_flight_action = None

            def __init__(self, session: Path):
                self.session = session

            def capture(self, label):
                frame = np.zeros((1280, 800, 3), np.uint8)
                return CapturedNativeFrame(frame, b"png", "f" * 64, 1.0, self.session / f"{label}.png")

            def swipe(self, *args, **kwargs):
                raise AssertionError("already-visible route must not swipe")

        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            loc = localization()
            binding = BuildingBinding(target.semantic_id, (320, 420, 420, 520), loc.frame_sha256, 0.95, ("current-frame OCR: Bank",))
            args = SimpleNamespace(execute=True, yes=True, atlas=Path(directory) / "atlas.json", building_id=target.semantic_id, maximum_pans=4, settle_seconds=0, adb="unused", serial="emulator-5554", output_directory=Path(directory))
            fake_localizer = SimpleNamespace(localize=lambda frame: loc)
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=binding
            ):
                self.assertEqual(command_navigate_building(args), 0)


if __name__ == "__main__":
    unittest.main()
