from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.troop_training_bluestacks import RadialExteriorCloseBinding, TroopTrainingIntegratedRoute, bind_radial_exterior_close
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
from tasks.home_atlas_planner import GestureCalibration, PlanDisposition, SafeInteractionRegion
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
from tasks.troop_training import FACILITY_BY_TYPE, RadialMenuObservation, TrainingConfig, TroopTrainingConfig
from tasks.troop_training_entry import (
    ATLAS_BUILDING_BY_TROOP_TYPE,
    TroopTrainingAtlasEntryPlanner,
    first_enabled_entry_target,
)
from tasks.troop_training_vision import forbidden_atlas_entry_surface


PROFILE = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
SAFE = SafeInteractionRegion("home-default", (145, 180, 650, 1010), (400, 600))
CALIBRATION = GestureCalibration(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (450, 500), (250, 250, 650, 950), 2.1, 2.1, 35, 150, 180)


def config(first: str = "fighter") -> TroopTrainingConfig:
    values = {}
    enabled_seen = False
    for troop_type in ATLAS_BUILDING_BY_TROOP_TYPE:
        enabled = troop_type == first
        enabled_seen = enabled_seen or enabled
        values[troop_type] = TrainingConfig(
            enabled=enabled,
            target_tier=8 if enabled else None,
            training_policy="once_daily" if enabled else "disabled",
        )
    if not enabled_seen:
        raise ValueError(first)
    return TroopTrainingConfig(**values)


def world(troop_type: str = "fighter", *, polygon=((300, 400), (440, 400), (440, 540), (300, 540))) -> HomeAtlas:
    building = SemanticBuilding(
        ATLAS_BUILDING_BY_TROOP_TYPE[troop_type],
        FACILITY_BY_TYPE[troop_type],
        polygon,
        0.98,
        ("v1",),
        recognition={"bluestacks": {"label": FACILITY_BY_TYPE[troop_type]}},
        semantic_proof=(f"visible {FACILITY_BY_TYPE[troop_type]} label",),
        platform_binding_policy={"bluestacks": {"label": FACILITY_BY_TYPE[troop_type]}},
    )
    viewport = AtlasViewport("v1", "unused.png", "a" * 64, "now", ((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((0, 0), (800, 0), (800, 1280), (0, 1280)), 1, 0, "translation")
    coverage = (((0, 0), (1500, 0), (1500, 2800), (0, 2800)),)
    return HomeAtlas(3, "test", "1", PROFILE, "fully_zoomed_out", "atlas pixels", (0, 0), 1500, 2800, "atlas.png", "test", "test", coverage, (), (viewport,), (building,), coverage, (0.0, 0.0, 700.0, 1500.0))


def loc(x: float = 0, y: float = 0, digest: str = "a" * 64, *, recognized: bool = True) -> LocalizationResult:
    return LocalizationResult(
        recognized,
        BLUESTACKS_PLATFORM,
        BLUESTACKS_PROFILE_ID,
        ZoomIdentity.FULLY_ZOOMED_OUT if recognized else ZoomIdentity.UNKNOWN,
        ((1, 0, x), (0, 1, y), (0, 0, 1)) if recognized else None,
        ((x, y), (x + 800, y), (x + 800, y + 1280), (x, y + 1280)) if recognized else (),
        0.96 if recognized else 0.0,
        ("v1",) if recognized else (),
        0.2 if recognized else None,
        AmbiguityState.NONE if recognized else AmbiguityState.INSUFFICIENT_LANDMARKS,
        "interior" if recognized else "unknown",
        digest,
        "now",
    )


def semantic_binding(target, localization: LocalizationResult) -> BuildingBinding:
    return BuildingBinding(target.building_id, (300, 400, 440, 540), localization.frame_sha256, 0.95, (f"current-frame OCR: {target.facility_identity}",))


class Runtime:
    def __init__(self, *, execute: bool = True, count: int = 30):
        self.execute = execute
        self.in_flight_action = None
        self.session = Path("fake-entry-session")
        self.frames = [CapturedNativeFrame(np.full((1280, 800, 3), index, np.uint8), b"png", f"{index:064x}", float(index + 1), Path(f"{index}.png")) for index in range(count)]
        self.index = 0
        self.taps = []
        self.swipes = []
        self.backs = []

    def capture(self, _label):
        frame = self.frames[self.index]
        self.index += 1
        return frame

    def tap(self, source, **kwargs):
        self.taps.append((source.sha256, kwargs))

    def swipe(self, source, **kwargs):
        self.swipes.append((source.sha256, kwargs))

    def back(self, source, **kwargs):
        self.backs.append((source.sha256, kwargs))


class TroopTrainingEntryContractTests(unittest.TestCase):
    def test_troop_type_to_semantic_building_mapping(self):
        self.assertEqual(
            ATLAS_BUILDING_BY_TROOP_TYPE,
            {
                "fighter": "home.building.fighter_camp",
                "shooter": "home.building.shooter_camp",
                "rider": "home.building.rider_camp",
                "vehicle": "home.building.vehicle_depot",
            },
        )
        for troop_type, building_id in ATLAS_BUILDING_BY_TROOP_TYPE.items():
            target = first_enabled_entry_target(config(troop_type))
            self.assertEqual((target.troop_type, target.building_id), (troop_type, building_id))

    def test_zero_pan_requires_exact_current_frame_semantic_binding(self):
        target = first_enabled_entry_target(config())
        planner = TroopTrainingAtlasEntryPlanner(world(), target, SAFE, CALIBRATION)
        localization = loc()
        self.assertEqual(planner.plan(localization).disposition, PlanDisposition.BIND)
        coordinate_only = replace(semantic_binding(target, localization), semantic_evidence=())
        planner = TroopTrainingAtlasEntryPlanner(world(), target, SAFE, CALIBRATION)
        self.assertEqual(planner.plan(localization, coordinate_only).reason, "current_frame_building_binding_rejected")
        planner = TroopTrainingAtlasEntryPlanner(world(), target, SAFE, CALIBRATION)
        self.assertEqual(planner.plan(localization, semantic_binding(target, localization)).disposition, PlanDisposition.COMPLETE)
        self.assertEqual(planner.pan_count, 0)

    def test_outside_view_one_pan_corrective_pan_and_progress_failures(self):
        target = first_enabled_entry_target(config())
        atlas = world(polygon=((650, 500), (750, 500), (750, 600), (650, 600)))
        planner = TroopTrainingAtlasEntryPlanner(atlas, target, SAFE, CALIBRATION, maximum_pans=2)
        first = planner.plan(loc())
        self.assertEqual(first.disposition, PlanDisposition.PAN)
        progress = planner.record_progress(loc(), loc(50, 0, "b" * 64))
        self.assertTrue(progress.accepted)
        corrective = planner.plan(loc(50, 0, "c" * 64))
        self.assertEqual(corrective.disposition, PlanDisposition.PAN)
        self.assertLess(abs(corrective.requested_camera_displacement[0]), abs(first.requested_camera_displacement[0]))
        no_progress = TroopTrainingAtlasEntryPlanner(atlas, target, SAFE, CALIBRATION)
        plan = no_progress.plan(loc())
        self.assertEqual(no_progress.record_progress(loc(), loc(0, 0, "d" * 64)).reason, "no_measured_progress")
        wrong = TroopTrainingAtlasEntryPlanner(atlas, target, SAFE, CALIBRATION)
        wrong.plan(loc())
        self.assertEqual(wrong.record_progress(loc(), loc(-100, 0, "e" * 64)).reason, "movement_wrong_direction")
        failed = TroopTrainingAtlasEntryPlanner(atlas, target, SAFE, CALIBRATION)
        failed.plan(loc())
        self.assertEqual(failed.record_progress(loc(), loc(digest="f" * 64, recognized=False)).reason, "post_pan_localization_failed")

    def test_maximum_pan_and_wrong_facility_radial_rejected(self):
        target = first_enabled_entry_target(config())
        atlas = world(polygon=((900, 700), (1040, 700), (1040, 840), (900, 840)))
        planner = TroopTrainingAtlasEntryPlanner(atlas, target, SAFE, CALIBRATION, maximum_pans=1)
        self.assertEqual(planner.plan(loc()).disposition, PlanDisposition.PAN)
        self.assertEqual(planner.plan(loc(100, 50, "b" * 64)).reason, "maximum_pan_count")
        wrong = RadialMenuObservation(True, FACILITY_BY_TYPE["shooter"], (300, 760, 430, 890), frame_sha256="c" * 64)
        self.assertFalse(planner.radial_is_exact(wrong))
        self.assertFalse(planner.radial_is_exact(replace(wrong, facility_identity=FACILITY_BY_TYPE["fighter"], train_target=None)))

    def test_home_warehouse_label_is_safe_but_modal_and_resource_surfaces_reject(self):
        frame = np.zeros((1280, 800, 3), np.uint8)
        with patch("tasks.troop_training_vision._ocr", return_value="headquarters warehouse fighter camp"):
            self.assertIsNone(forbidden_atlas_entry_surface(frame))
        with patch("tasks.troop_training_vision._ocr", return_value="warehouse insufficient use resources confirm cancel"):
            self.assertEqual(forbidden_atlas_entry_surface(frame), "unexpected_warehouse_surface")
        with patch("tasks.troop_training_vision._ocr", return_value="auto use resource boxes"):
            self.assertEqual(forbidden_atlas_entry_surface(frame), "unexpected_resource_box_surface")

    def test_bluestacks_radial_exterior_binding_rejects_wrong_facility_and_bliss(self):
        frame = np.zeros((1280, 800, 3), np.uint8)
        localization = loc(digest=frame_digest(frame))
        radial = RadialMenuObservation(True, FACILITY_BY_TYPE["fighter"], (300, 800, 430, 900), frame_sha256="r" * 64)
        binding = bind_radial_exterior_close(frame, localization, world(), radial, troop_type="fighter")
        self.assertIsNotNone(binding)
        self.assertGreaterEqual(binding.minimum_building_clearance_px, 25.0)
        self.assertIsNone(bind_radial_exterior_close(frame, localization, world(), radial, troop_type="vehicle"))
        bliss = replace(localization, platform="Bliss OS", profile_id="pns-800x1280-v1")
        self.assertIsNone(bind_radial_exterior_close(frame, bliss, world(), radial, troop_type="fighter"))


class TroopTrainingEntryIntegratedRouteTests(unittest.TestCase):
    def _route(self, runtime: Runtime, *, entry_only=False, atlas=None):
        return TroopTrainingIntegratedRoute(
            runtime,
            config=config(),
            reset_identity="entry-test",
            post_input_delay=0,
            entry_only=entry_only,
            atlas_path=Path("atlas.json"),
            maximum_home_pans=2,
            home_pan_settle_seconds=0,
        )

    def test_project_route_zero_pan_and_one_calculated_pan_relocalize(self):
        target = first_enabled_entry_target(config())
        zero_runtime = Runtime()
        zero_loc = loc()
        zero_localizer = SimpleNamespace(localize=lambda _frame: zero_loc)
        with patch("scripts.troop_training_bluestacks.load_home_atlas", return_value=world()), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=zero_localizer
        ), patch("scripts.troop_training_bluestacks.bind_visible_building", side_effect=lambda _frame, localization, _building: semantic_binding(target, localization)):
            captured, binding, planner, error = self._route(zero_runtime)._navigate_selected_facility(target)
        self.assertIsNone(error)
        self.assertIsNotNone(captured)
        self.assertIsNotNone(binding)
        self.assertEqual(planner.pan_count, 0)
        self.assertEqual(zero_runtime.swipes, [])

        pan_runtime = Runtime()
        locations = iter((loc(), loc(), loc(300, 0, "b" * 64), loc(300, 0, "c" * 64)))
        pan_localizer = SimpleNamespace(localize=lambda _frame: next(locations))
        bind_calls = []

        def bind(_frame, localization, _building):
            bind_calls.append(localization.frame_sha256)
            return semantic_binding(target, localization) if localization.screen_to_atlas[0][2] == 300 else None

        atlas = world(polygon=((650, 500), (750, 500), (750, 600), (650, 600)))
        with patch("scripts.troop_training_bluestacks.load_home_atlas", return_value=atlas), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=pan_localizer
        ), patch("scripts.troop_training_bluestacks.bind_visible_building", side_effect=bind):
            captured, binding, planner, error = self._route(pan_runtime)._navigate_selected_facility(target)
        self.assertIsNone(error)
        self.assertEqual(len(pan_runtime.swipes), 1)
        self.assertEqual(planner.pan_count, 1)
        self.assertEqual(len(bind_calls), 2)
        self.assertEqual(binding.frame_sha256, "c" * 64)

    def test_route_rejects_no_progress_and_dry_run_issues_no_input(self):
        target = first_enabled_entry_target(config())
        atlas = world(polygon=((650, 500), (750, 500), (750, 600), (650, 600)))
        no_progress_runtime = Runtime()
        locations = iter((loc(), loc(), loc(0, 0, "b" * 64)))
        with patch("scripts.troop_training_bluestacks.load_home_atlas", return_value=atlas), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=SimpleNamespace(localize=lambda _frame: next(locations))
        ), patch("scripts.troop_training_bluestacks.bind_visible_building", return_value=None):
            _, _, _, error = self._route(no_progress_runtime)._navigate_selected_facility(target)
        self.assertEqual(error, "no_measured_progress")

        dry_runtime = Runtime(execute=False)
        dry_locations = iter((loc(), loc()))
        with patch("scripts.troop_training_bluestacks.load_home_atlas", return_value=atlas), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=SimpleNamespace(localize=lambda _frame: next(dry_locations))
        ), patch("scripts.troop_training_bluestacks.bind_visible_building", return_value=None):
            _, _, _, error = self._route(dry_runtime)._navigate_selected_facility(target)
        self.assertEqual(error, "dry-run-calculated-pan-not-dispatched")
        self.assertEqual(dry_runtime.swipes, [])
        self.assertEqual(dry_runtime.taps, [])

    def test_entry_only_opens_facility_but_never_taps_train_and_recovers_home(self):
        runtime = Runtime()
        route = self._route(runtime, entry_only=True)
        target = first_enabled_entry_target(config())
        facility_capture = runtime.capture("bound")
        binding = semantic_binding(target, loc())
        planner = SimpleNamespace(radial_is_exact=lambda item: item.recognized and item.facility_identity == target.facility_identity and item.train_target is not None)
        radial = RadialMenuObservation(True, target.facility_identity, (300, 760, 430, 890), frame_sha256="b" * 64)
        route.entry_navigation = {"train_dispatched": False}
        with patch.object(route, "_navigate_selected_facility", return_value=(facility_capture, binding, planner, None)), patch.object(
            route, "_capture_radial", side_effect=((runtime.capture("radial"), radial), (runtime.capture("fresh-radial"), radial))
        ), patch("scripts.troop_training_bluestacks.recognize_auto_use_resource_popup", return_value=SimpleNamespace(recognized=False)), patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=SimpleNamespace(recognized=False)
        ), patch("scripts.troop_training_bluestacks.load_home_atlas", return_value=world()), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=SimpleNamespace(localize=lambda _frame: loc(digest="f" * 64))
        ), patch(
            "scripts.troop_training_bluestacks.bind_radial_exterior_close",
            return_value=RadialExteriorCloseBinding((220, 240, 240, 260), "f" * 64, 100.0, ("safe terrain",)),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_radial_menu", return_value=RadialMenuObservation(False, "")
        ):
            result = route.run()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.final_home_recognized)
        self.assertEqual([item[1]["target_identity"] for item in runtime.taps], ["facility:fighter", "radial-exterior-close:fighter"])
        self.assertEqual(len(runtime.backs), 0)
        self.assertEqual(result.training, ())
        self.assertFalse(result.entry_navigation["train_dispatched"])

    def test_normal_route_hands_the_same_training_observation_to_downstream_controller(self):
        runtime = Runtime()
        route = self._route(runtime)
        target = first_enabled_entry_target(config())
        facility_capture = runtime.capture("bound")
        binding = semantic_binding(target, loc())
        planner = SimpleNamespace(radial_is_exact=lambda item: True)
        radial_capture = runtime.capture("radial")
        radial = RadialMenuObservation(True, target.facility_identity, (300, 760, 430, 890), frame_sha256="b" * 64)
        training_capture = runtime.capture("training")
        training = SimpleNamespace(recognized=True, troop_type="fighter")
        sentinel = route._result("completed", "downstream-sentinel")
        with patch.object(route, "_navigate_selected_facility", return_value=(facility_capture, binding, planner, None)), patch.object(
            route, "_capture_radial", return_value=(radial_capture, radial)
        ), patch.object(route, "_capture_training", return_value=(training_capture, training)), patch.object(
            route, "_run_training_tabs", return_value=sentinel
        ) as downstream, patch("scripts.troop_training_bluestacks.recognize_auto_use_resource_popup", return_value=SimpleNamespace(recognized=False)), patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=SimpleNamespace(recognized=False)
        ):
            result = route.run()
        self.assertIs(result, sentinel)
        downstream.assert_called_once_with(training_capture, training, ["fighter"], "fighter")
        self.assertEqual([item[1]["target_identity"] for item in runtime.taps], ["facility:fighter", "train-menu:fighter"])


if __name__ == "__main__":
    unittest.main()
