"""Bioenhancer entry uses the existing checked current Research Lab binding."""

from dataclasses import replace
import hashlib
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2

from scripts import bioenhancer_free_research_route as bio
from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition, plan_direct_pan
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/research_lab_home_entry"


class BioenhancerHomeEntryBindingTests(unittest.TestCase):
    def navigator(self, atlas):
        safe, calibration = bluestacks_direct_pan_contract()
        return DirectPanNavigator(atlas, bio.RESEARCH_LAB_ID, safe, calibration)

    def test_native_safe_hit_region_completes_without_pan(self):
        for name in ("fully-visible-after-pan.png",):
            with self.subTest(frame=name):
                frame = cv2.imread(str(FIXTURES / name))
                atlas = bio.load_home_atlas(bio.ATLAS_PATH)
                navigator = self.navigator(atlas)
                localization, binding, plan = bio.plan_research_lab_pan(frame, navigator)
                self.assertIsNotNone(binding)
                self.assertEqual(binding.frame_sha256, localization.frame_sha256)
                self.assertEqual(binding.atlas_anchor, (835, 520))
                self.assertEqual(plan.disposition, PlanDisposition.COMPLETE)
                self.assertIsNone(plan.drag_start)
                self.assertEqual(navigator.pan_count, 0)

    def test_native_high_lab_needs_pan_before_its_nova_radial_can_be_recognized(self):
        frame = cv2.imread(str(FIXTURES / "initial-safe-subregion.png"))
        atlas = bio.load_home_atlas(bio.ATLAS_PATH)
        navigator = self.navigator(atlas)
        localization, binding, plan = bio.plan_research_lab_pan(frame, navigator)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.frame_sha256, localization.frame_sha256)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertIsNone(bio.bind_research_lab(frame))
        self.assertEqual(navigator.pan_count, 1)

    def test_native_right_lab_needs_pan_before_research_clears_the_event_hud(self):
        frame = cv2.imread(str(ROOT / "tests/fixtures/bioenhancer_radial/home-research-under-event-hud.png"))
        atlas = bio.load_home_atlas(bio.ATLAS_PATH)
        navigator = self.navigator(atlas)
        localization, binding, plan = bio.plan_research_lab_pan(frame, navigator)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.frame_sha256, localization.frame_sha256)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertAlmostEqual(plan.viewport.target_screen_anchor[0], 317.33, delta=1.)
        self.assertIsNone(bio.bind_research_lab(frame))
        self.assertEqual(navigator.pan_count, 1)

    def test_unclean_home_stops_before_binding_or_planning(self):
        frame = cv2.imread(str(FIXTURES / "fully-visible-after-pan.png"))
        atlas, localization = bio._atlas_stack(frame)
        navigator = self.navigator(atlas)
        with patch.object(bio, "_atlas_stack", return_value=(atlas, localization)), patch.object(
            bio, "is_clean_home_frame", return_value=False
        ), patch.object(bio, "bind_visible_building") as bind, patch.object(navigator, "plan") as plan:
            actual_localization, binding, decision = bio.plan_research_lab_pan(frame, navigator)
        self.assertIs(actual_localization, localization)
        self.assertIsNone(binding)
        self.assertIsNone(decision)
        bind.assert_not_called()
        plan.assert_not_called()

    def test_actual_minimum_pan_dead_zone_gets_calibrated_camera_move_only(self):
        path = FIXTURES / "research-right-hud-minimum-pan-20261031.png"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            "c9e2b473da749a58befed3b6aba150eda7ec40a91f8fa71871e41aac36b4017e")
        frame = cv2.imread(str(path))
        atlas, localization = bio._atlas_stack(frame)
        navigator = self.navigator(atlas)
        original_safe = navigator.safe_region
        normal = plan_direct_pan(atlas, localization, bio.RESEARCH_LAB_ID,
                                 original_safe, navigator.calibration)
        self.assertEqual(normal.disposition, PlanDisposition.REJECTED)
        self.assertGreater(dict(normal.viewport.rejection_counts)["gesture_below_effective_minimum"], 0)
        current, binding, plan = bio.plan_research_lab_pan(frame, navigator)
        self.assertEqual(plan.disposition, PlanDisposition.PAN)
        self.assertEqual(binding.frame_sha256, current.frame_sha256)
        self.assertFalse(bio._research_radial_viewport_safe(binding))
        self.assertTrue(bio._research_radial_viewport_safe(replace(
            binding, screen_anchor=plan.viewport.target_screen_anchor)))
        self.assertIs(navigator.safe_region, original_safe)
        self.assertIs(navigator.last_plan, plan)
        self.assertEqual(navigator.pan_count, 1)
        self.assertGreaterEqual(math.dist(plan.drag_start, plan.drag_end), navigator.calibration.minimum_drag_px)
        self.assertIsNone(bio.bind_research_lab(frame))
        self.assertFalse(navigator.record_progress(current, replace(current, frame_sha256="1" * 64)).accepted)
        _, _, repeated = bio.plan_research_lab_pan(frame, navigator)
        self.assertEqual(repeated.reason, "repeated_viewport")
        self.assertEqual(navigator.pan_count, 1)

    def test_dead_zone_camera_move_preserves_existing_pan_cap(self):
        frame = cv2.imread(str(FIXTURES / "research-right-hud-minimum-pan-20261031.png"))
        atlas = bio.load_home_atlas(bio.ATLAS_PATH)
        navigator = self.navigator(atlas)
        navigator.pan_count = navigator.maximum_pans
        _, _, plan = bio.plan_research_lab_pan(frame, navigator)
        self.assertEqual(plan.disposition, PlanDisposition.REJECTED)
        self.assertEqual(plan.reason, "maximum_pan_count")
        self.assertEqual(navigator.pan_count, navigator.maximum_pans)

    def test_stale_localization_cannot_supply_a_binding(self):
        frame = cv2.imread(str(FIXTURES / "fully-visible-after-pan.png"))
        atlas, localization = bio._atlas_stack(frame)
        with patch.object(bio, "_atlas_stack", return_value=(atlas, replace(localization, stale=True))):
            _actual, binding, plan = bio.plan_research_lab_pan(frame, self.navigator(atlas))
        self.assertIsNone(binding)
        self.assertIs(plan.disposition, PlanDisposition.REJECTED)
