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
    ViewportPlanningPolicy,
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
        focused = bind_visible_building(
            frame,
            loc,
            target,
            ocr=lambda image, psm: "Bank" if psm in (8, 13) else "unknown",
        )
        self.assertIsNotNone(focused)

        pit = replace(
            target,
            semantic_id="home.building.pit",
            display_identity="Pit",
            recognition={"bluestacks": {"label": "Pit"}},
            platform_binding_policy={"bluestacks": {"label": "Pit"}},
        )
        self.assertIsNone(
            bind_visible_building(frame, loc, pit, ocr=lambda image, psm: "Hospital")
        )

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
            sample = runtime.capture("seed")
            loc = replace(localization(), frame_sha256=frame_digest(sample.frame))
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
            fake_localizer = SimpleNamespace(localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame)))
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
            sample = runtime.capture("seed")
            digest = frame_digest(sample.frame)
            loc = replace(localization(), frame_sha256=digest)
            binding = BuildingBinding(target.semantic_id, (320, 420, 420, 520), digest, 0.95, ("current-frame OCR: Bank",))
            args = SimpleNamespace(execute=True, yes=True, atlas=Path(directory) / "atlas.json", building_id=target.semantic_id, maximum_pans=4, settle_seconds=0, adb="unused", serial="emulator-5554", output_directory=Path(directory))
            fake_localizer = SimpleNamespace(localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame)))
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building",
                side_effect=lambda frame, localization_arg, building_arg: replace(
                    binding, frame_sha256=localization_arg.frame_sha256
                ),
            ):
                self.assertEqual(command_navigate_building(args), 0)

    def test_route_rejects_localization_from_another_frame(self):
        class Runtime:
            execute = False
            in_flight_action = None

            def __init__(self, session: Path):
                self.session = session

            def capture(self, label):
                frame = np.zeros((1280, 800, 3), np.uint8)
                return CapturedNativeFrame(frame, b"png", "f" * 64, 1.0, self.session / f"{label}.png")

        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            foreign = replace(localization(), frame_sha256="b" * 64)
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
            fake_localizer = SimpleNamespace(localize=lambda frame: foreign)
            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=atlas()), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ):
                self.assertEqual(command_navigate_building(args), 3)



POLICY = ViewportPlanningPolicy(
    radial_margin_up_px=40.0,
    radial_margin_down_px=120.0,
    radial_margin_left_px=70.0,
    radial_margin_right_px=70.0,
    recovery_clearance_px=25.0,
    recovery_zone_half_size_px=10.0,
    recovery_scan_step_px=25.0,
    recovery_search_inset_left_px=75.0,
    recovery_search_inset_top_px=70.0,
    recovery_search_inset_right_px=75.0,
    recovery_search_inset_bottom_px=360.0,
    action_body_margin_px=8.0,
    label_inset_px=12.0,
    candidate_step_px=80.0,
    max_candidates=36,
    map_edge_soft_margin_px=40.0,
)


def policy_safe(**overrides) -> SafeInteractionRegion:
    policy = POLICY if not overrides else ViewportPlanningPolicy(**{**POLICY.__dict__, **overrides})
    return SafeInteractionRegion("home-default", (145, 180, 650, 1010), (400, 600), fixed_hud_masks=((0, 0, 800, 150), (0, 150, 138, 1020), (650, 150, 800, 1020), (0, 1020, 800, 1280)), planning_policy=policy)


class RecoveryAwareViewportPlannerTests(unittest.TestCase):
    def test_policy_absent_preserves_exact_legacy_output(self):
        target = building()
        world = atlas(target)
        loc = localization()
        legacy_safe = SafeInteractionRegion("home-default", (145, 180, 650, 1010), (400, 600))
        first = plan_building_viewport(world, loc, target.semantic_id, legacy_safe)
        second = plan_building_viewport(world, loc, target.semantic_id, legacy_safe)
        self.assertIsNone(legacy_safe.planning_policy)
        self.assertEqual(first, second)
        self.assertEqual(first.desired_camera_origin, (570.0, 170.0))
        self.assertEqual(first.reason, "calculated_target_viewport")
        self.assertEqual(first.selection_score, None)
        self.assertEqual(first.recovery_honesty, ())

    def test_zero_pan_when_current_passes_hard_gates(self):
        target = building(polygon=((300, 400), (440, 400), (440, 520), (300, 520)))
        plan = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe())
        self.assertEqual(plan.disposition, PlanDisposition.ALREADY_SAFE)
        self.assertIsNotNone(plan.predicted_recovery_search_zone)
        self.assertTrue(plan.predicted_recovery_search_zone.available)
        self.assertIsNone(plan.predicted_recovery_search_zone.executable_recovery_coordinate)
        self.assertIn("current_frame_recovery_binding_still_required", plan.recovery_honesty)

    def test_visible_but_poorly_positioned_requires_reposition(self):
        # Fully inside safe box but radial footprint (down 200) collides with bottom HUD.
        target = building(polygon=((300, 880), (440, 880), (440, 980), (300, 980)))
        plan = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe(radial_margin_down_px=200.0))
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertEqual(plan.reason, "recovery_aware_target_viewport")
        self.assertLess(plan.desired_camera_origin[1], 880 - 180)

    def test_asymmetric_radial_footprint_rejects_downward_overflow(self):
        target = building(polygon=((300, 860), (420, 860), (420, 960), (300, 960)))
        reject = plan_building_viewport(
            atlas(target),
            localization(),
            target.semantic_id,
            policy_safe(
                radial_margin_up_px=10.0,
                radial_margin_down_px=400.0,
                radial_margin_left_px=10.0,
                radial_margin_right_px=10.0,
                max_candidates=4,
                candidate_step_px=500.0,
                recovery_search_inset_bottom_px=360.0,
            ),
        )
        self.assertEqual(reject.disposition, PlanDisposition.REJECTED)
        self.assertEqual(reject.reason, "no_recoverable_actionable_viewport")
        self.assertTrue(any(reason == "insufficient_radial_footprint" for reason, _ in reject.rejection_counts))

    def test_insufficient_recovery_search_zone_fails_closed(self):
        # Demand impossible exterior clearance so predicted recovery search zone cannot exist.
        target = building(polygon=((300, 400), (440, 400), (440, 520), (300, 520)))
        plan = plan_building_viewport(
            atlas(target),
            localization(),
            target.semantic_id,
            policy_safe(recovery_clearance_px=500.0, recovery_zone_half_size_px=20.0, max_candidates=8, candidate_step_px=120.0),
        )
        self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertEqual(plan.reason, "no_recoverable_actionable_viewport")
        self.assertTrue(any(reason == "predicted_recovery_search_zone_unavailable" for reason, _ in plan.rejection_counts))

    def test_affine_non_identity_scale_derives_translation_through_linear(self):
        target = building(polygon=((1900, 1500), (2040, 1500), (2040, 1640), (1900, 1640)))
        loc = replace(localization(), screen_to_atlas=((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)), viewport_polygon=((0, 0), (1600, 0), (1600, 2560), (0, 2560)))
        base = atlas(target, bounds=(0.0, 0.0, 2000.0, 2500.0))
        polygons = (((0, 0), (2500, 0), (2500, 3000), (0, 3000)),)
        world = HomeAtlas(
            base.schema_version,
            base.atlas_id,
            base.atlas_version,
            base.profile,
            base.canonical_zoom_identity,
            base.coordinate_units,
            base.origin,
            2500,
            3000,
            base.image_path,
            base.game_build_provenance,
            base.account_layout_provenance,
            polygons,
            (),
            base.viewports,
            (target,),
            polygons,
            (0.0, 0.0, 2000.0, 2500.0),
        )
        plan = plan_building_viewport(world, loc, target.semantic_id, policy_safe())
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        sx, sy = plan.target_screen_anchor
        ax, ay = target.navigation_anchor
        self.assertAlmostEqual(plan.desired_camera_origin[0], ax - 2.0 * sx, places=5)
        self.assertAlmostEqual(plan.desired_camera_origin[1], ay - 2.0 * sy, places=5)

    def test_predicted_recovery_zone_never_produces_executable_tap(self):
        target = building(polygon=((300, 400), (440, 400), (440, 520), (300, 520)))
        plan = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe())
        zone = plan.predicted_recovery_search_zone
        self.assertIsNotNone(zone)
        self.assertIsNone(zone.executable_recovery_coordinate)
        self.assertFalse(hasattr(zone, "tap_xy"))
        self.assertIn("projection_does_not_authorize_entry_or_exit_input", plan.recovery_honesty)
        self.assertIn("current_frame_recovery_binding_still_required", plan.recovery_honesty)

    def test_foreign_transient_clearance_delegated_via_honesty_fields(self):
        target = building()
        plan = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe())
        self.assertIn("predicted_recovery_search_zone_available_is_not_a_live_tap_proof", plan.recovery_honesty)
        if plan.predicted_recovery_search_zone is not None:
            self.assertIsNone(plan.predicted_recovery_search_zone.executable_recovery_coordinate)

    def test_destination_already_in_navigator_history_rejected_before_dispatch(self):
        target = building()
        world = atlas(target)
        # Restrict candidates so the classic destination is the only viable option.
        safe = policy_safe(max_candidates=1, candidate_step_px=500.0)
        controller = DirectPanNavigator(world, target.semantic_id, safe, CALIBRATION)
        first = controller.plan(localization())
        self.assertEqual(first.disposition, PlanDisposition.PAN)
        destination = (round(first.viewport.desired_camera_origin[0]), round(first.viewport.desired_camera_origin[1]))
        controller.seen_viewports.add(destination)
        blocked = controller.plan(localization(10, 10, "b" * 64))
        self.assertEqual(blocked.disposition, PlanDisposition.REJECTED)
        self.assertEqual(blocked.reason, "no_recoverable_actionable_viewport")
        self.assertTrue(any(reason == "destination_already_visited" for reason, _ in blocked.viewport.rejection_counts))

    def test_deterministic_tie_resolution(self):
        target = building(polygon=((900, 700), (1040, 700), (1040, 840), (900, 840)))
        world = atlas(target)
        a = plan_building_viewport(world, localization(), target.semantic_id, policy_safe())
        b = plan_building_viewport(world, localization(), target.semantic_id, policy_safe())
        self.assertEqual(a.desired_camera_origin, b.desired_camera_origin)
        self.assertEqual(a.selection_score, b.selection_score)
        self.assertEqual(a.score_breakdown, b.score_breakdown)

    def test_bounded_rejection_evidence(self):
        target = building(polygon=((10, 500), (110, 500), (110, 620), (10, 620)))
        plan = plan_building_viewport(atlas(target, bounds=(0, 0, 50, 1500)), localization(400, 0), target.semantic_id, policy_safe(max_candidates=40, candidate_step_px=40.0))
        self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertLessEqual(len(plan.rejected_alternatives), 5)
        self.assertTrue(plan.rejection_counts)
        self.assertTrue(plan.best_rejected_by_reason)
        reasons = {item.reason for item in plan.best_rejected_by_reason}
        self.assertEqual(len(reasons), len(plan.best_rejected_by_reason))


    def test_lower_half_alternate_candidate_selected(self):
        # Classic placement puts a tall body+radial past the safe bottom; a higher placement remains viable.
        target = building(polygon=((350, 820), (490, 820), (490, 1000), (350, 1000)))
        plan = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe(radial_margin_down_px=400.0, candidate_step_px=50.0, max_candidates=48))
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertEqual(plan.reason, "recovery_aware_target_viewport")
        classic = (target.navigation_anchor[0] - 400, target.navigation_anchor[1] - 600)
        self.assertNotEqual(plan.desired_camera_origin, classic)
        self.assertGreater(plan.desired_camera_origin[1], classic[1])

    def test_map_edge_proximity_alone_does_not_hard_reject(self):
        # Interior safe building whose desired origin sits near the camera bound.
        target = building(polygon=((300, 400), (420, 400), (420, 520), (300, 520)))
        plan = plan_building_viewport(atlas(target, bounds=(0.0, 0.0, 20.0, 1500.0)), localization(), target.semantic_id, policy_safe())
        self.assertEqual(plan.disposition, PlanDisposition.ALREADY_SAFE)
        self.assertEqual(plan.reason, "target_already_safely_visible")
        self.assertNotIn("map_edge_proximity", dict(plan.rejection_counts))

    def test_near_hud_target_is_repositioned(self):
        # Building sits near the top of the current viewport; pan to a lower screen placement.
        target = building(polygon=((300, 700), (420, 700), (420, 790), (300, 790)))
        plan = plan_building_viewport(atlas(target), localization(0, 500), target.semantic_id, policy_safe())
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertEqual(plan.reason, "recovery_aware_target_viewport")
        self.assertLess(plan.desired_camera_origin[1], 500.0)

    def test_recovery_search_envelope_bounds_zone_availability(self):
        target = building(polygon=((300, 400), (440, 400), (440, 520), (300, 520)))
        # Envelope excludes the entire safe interior -> recovery unavailable.
        blocked = plan_building_viewport(
            atlas(target),
            localization(),
            target.semantic_id,
            policy_safe(recovery_search_inset_left_px=400.0, recovery_search_inset_right_px=400.0),
        )
        self.assertEqual(blocked.disposition, PlanDisposition.REJECTED)
        self.assertEqual(blocked.reason, "no_recoverable_actionable_viewport")
        self.assertTrue(any(reason == "predicted_recovery_search_zone_unavailable" for reason, _ in blocked.rejection_counts))
        # Matching BlueStacks exterior-close envelope admits a zone without executable taps.
        ok = plan_building_viewport(atlas(target), localization(), target.semantic_id, policy_safe())
        self.assertEqual(ok.disposition, PlanDisposition.ALREADY_SAFE)
        self.assertIsNotNone(ok.predicted_recovery_search_zone)
        self.assertTrue(ok.predicted_recovery_search_zone.available)
        self.assertIsNone(ok.predicted_recovery_search_zone.executable_recovery_coordinate)
        self.assertIn("current_frame_recovery_binding_still_required", ok.recovery_honesty)
        search = (
            145 + 75,
            180 + 70,
            650 - 75,
            1010 - 360,
        )
        zone = ok.predicted_recovery_search_zone.zone_box
        self.assertIsNotNone(zone)
        self.assertGreaterEqual(zone[0], search[0] - 1e-6)
        self.assertGreaterEqual(zone[1], search[1] - 1e-6)
        self.assertLessEqual(zone[2], search[2] + 1e-6)
        self.assertLessEqual(zone[3], search[3] + 1e-6)

    def test_bluestacks_candidate_set_covers_upper_middle_lower(self):
        from tasks.home_atlas_planner import _candidate_screen_placements
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
        safe, _ = bluestacks_direct_pan_contract()
        points = _candidate_screen_placements(safe, safe.planning_policy)
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        self.assertLessEqual(min(ys), 280)
        self.assertGreaterEqual(max(ys), 900)
        self.assertTrue(any(450 <= y <= 700 for y in ys))
        self.assertLessEqual(min(xs), 200)
        self.assertGreaterEqual(max(xs), 600)
        self.assertEqual(points, sorted(points, key=lambda item: (item[1], item[0])))

    def test_plan_direct_pan_public_signature_excludes_seen_destinations(self):
        import inspect
        params = list(inspect.signature(plan_direct_pan).parameters)
        self.assertEqual(params, ["atlas", "localization", "building_id", "safe_region", "calibration"])

    def test_supply_depot_safe_subregion_produces_viable_plan(self):
        from tasks.home_atlas import load_home_atlas
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
        from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID
        atlas_path = Path("tasks/assets/home_atlas/bluestacks/800x1280/atlas.json")
        world = load_home_atlas(atlas_path)
        safe, _ = bluestacks_direct_pan_contract()
        # Representative canonical-ish Home localization near viewport-001 origin.
        loc = LocalizationResult(
            True,
            BLUESTACKS_PLATFORM,
            BLUESTACKS_PROFILE_ID,
            ZoomIdentity.FULLY_ZOOMED_OUT,
            ((1.0, 0.0, 171.0), (0.0, 1.0, 113.0), (0.0, 0.0, 1.0)),
            ((171.0, 113.0), (971.0, 113.0), (971.0, 1393.0), (171.0, 1393.0)),
            0.99,
            ("viewport-001",),
            0.1,
            AmbiguityState.NONE,
            "interior",
            "a" * 64,
            "now",
        )
        plan = plan_building_viewport(world, loc, "home.building.supply_depot", safe)
        self.assertIn(plan.disposition, {PlanDisposition.PAN, PlanDisposition.ALREADY_SAFE})
        self.assertIn(plan.reason, {"recovery_aware_target_viewport", "target_already_safely_visible"})
        self.assertNotEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertIn("projection_does_not_authorize_entry_or_exit_input", plan.recovery_honesty)
        self.assertIn(
            "planner_projected_recovery_search_zone_is_non_authorizing_safe_exit_provenance_only",
            plan.recovery_honesty,
        )
        if plan.predicted_recovery_search_zone is not None:
            self.assertIsNone(plan.predicted_recovery_search_zone.executable_recovery_coordinate)



if __name__ == "__main__":
    unittest.main()
