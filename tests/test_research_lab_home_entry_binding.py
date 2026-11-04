"""Native Research Lab hit regions complete before hypothetical radial planning."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import cv2

from scripts import home_atlas_bluestacks as home
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition
from tasks.home_atlas_vision import bind_visible_building
from tests.support.home_atlas import _ready
from tests.support.environment import requires_tesseract


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FIXTURES = ROOT / "tests/fixtures/research_lab_home_entry"


class ResearchLabHomeEntryBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = home.load_home_atlas(ATLAS)
        cls.building = cls.atlas.lookup_building("home.building.research_lab")
        localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)
        cls.frames = {}
        for name in ("initial-safe-subregion.png", "fully-visible-after-pan.png"):
            frame = cv2.imread(str(FIXTURES / name))
            localization = localizer.localize(frame)
            binding = bind_visible_building(
                frame, localization, cls.building, home_is_clean=lambda _frame: True
            )
            cls.frames[name] = frame, localization, binding

    def navigator(self, atlas=None):
        safe, calibration = home.bluestacks_direct_pan_contract()
        return DirectPanNavigator(atlas or self.atlas, self.building.semantic_id, safe, calibration)

    @requires_tesseract
    def test_native_current_lab_and_initial_safe_subregion_complete_without_pan(self):
        for name, (frame, localization, _synthetic_binding) in self.frames.items():
            with self.subTest(frame=name):
                binding = bind_visible_building(
                    frame, localization, self.building, home_is_clean=is_clean_home_frame
                )
                self.assertIsNotNone(binding)
                self.assertEqual(binding.atlas_anchor, (835, 520))
                driver = home.BlueStacksLocalizeFirstHomeDriver(
                    self.atlas, ATLAS, _ready(), self.building.semantic_id,
                    localizer=SimpleNamespace(localize=lambda _f: localization, canonical_reference=frame),
                )
                step = driver.observe(frame)
                self.assertEqual(step.disposition, home.HomeDriverDisposition.COMPLETE)
                self.assertEqual(step.binding.target_roi, binding.target_roi)
                self.assertEqual(driver.navigator.pan_count, 0)
                self.assertIsNone(step.plan.drag_start)

    def test_current_safe_binding_is_not_vetoed_by_unexecutable_forecast_fine_pan(self):
        _frame, localization, binding = self.frames["fully-visible-after-pan.png"]
        navigator = self.navigator()
        forecast = home.plan_direct_pan(
            self.atlas, localization, self.building.semantic_id,
            navigator.safe_region, navigator.calibration,
        )
        self.assertEqual(forecast.reason, "no_recoverable_actionable_viewport")
        self.assertGreater(dict(forecast.viewport.rejection_counts).get("gesture_below_effective_minimum", 0), 0)
        self.assertEqual(binding.target_roi, (216, 310, 380, 534))
        self.assertEqual(home._plan_mapped_home_entry(navigator, localization, binding).disposition,
                         PlanDisposition.COMPLETE)

    def test_invalid_or_absent_binding_and_source_never_complete(self):
        _frame, localization, binding = self.frames["fully-visible-after-pan.png"]
        for name, source, target in (
            ("absent", localization, None),
            ("stale_binding", localization, replace(binding, frame_sha256="f" * 64)),
            ("wrong_building", localization, replace(binding, building_id="home.building.campaign")),
            ("outside_safe", localization, replace(binding, target_roi=(700, 700, 760, 760), screen_anchor=(730, 730))),
            ("masked", localization, replace(binding, target_roi=(580, 350, 620, 390), screen_anchor=(600, 370))),
            ("binding_overlay", localization, replace(binding, overlay_intersects=True)),
            ("binding_ambiguous", localization, replace(binding, ambiguous_overlap=True)),
            ("wrong_anchor", localization, replace(binding, atlas_anchor=(836, 520))),
            ("source_stale", replace(localization, stale=True), binding),
            ("source_overlay", replace(localization, overlay=True), binding),
            ("source_profile", replace(localization, profile_id="wrong-profile"), binding),
        ):
            with self.subTest(case=name):
                self.assertEqual(home._plan_mapped_home_entry(self.navigator(), source, target).disposition,
                                 PlanDisposition.REJECTED)
        self.assertEqual(home._plan_mapped_home_entry(
            self.navigator(atlas=replace(self.atlas, coverage_polygons=())), localization, binding,
        ).disposition, PlanDisposition.REJECTED)

    def test_core_binder_still_requires_current_source_home_and_mapped_polygon(self):
        frame, localization, _binding = self.frames["fully-visible-after-pan.png"]
        self.assertIsNone(bind_visible_building(
            frame, replace(localization, frame_sha256="f" * 64), self.building,
            home_is_clean=lambda _frame: True,
        ))
        self.assertIsNone(bind_visible_building(
            frame, localization, self.building, home_is_clean=lambda _frame: False,
        ))
        outside_anchor = replace(self.building, interaction_anchor_override=(500, 500))
        self.assertIsNone(bind_visible_building(
            frame, localization, outside_anchor, home_is_clean=lambda _frame: True,
        ))

    def test_fixture_bytes_match_retained_source_provenance(self):
        provenance = json.loads((FIXTURES / "provenance.json").read_text())
        for record in provenance["frames"]:
            payload = (FIXTURES / record["fixture"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), record["transport_sha256"])
            self.assertEqual(cv2.imread(str(FIXTURES / record["fixture"])).shape, (1280, 800, 3))
