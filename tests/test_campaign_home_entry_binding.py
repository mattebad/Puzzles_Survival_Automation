"""Native Campaign entry regression: bind the safe anchor before planning pans."""

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2

from scripts import home_atlas_bluestacks as home
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_planner import DirectPanNavigator, PlanDisposition
from tasks.home_atlas_vision import bind_visible_building
from tests.test_home_atlas_verified_route import _ready


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "tasks/assets/home_atlas/bluestacks/800x1280/atlas.json"
FRAME = ROOT / "tests/fixtures/campaign_home_entry/canonical-home-20261029.png"


class CampaignHomeEntryBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(FRAME), cv2.IMREAD_COLOR)
        cls.payload = FRAME.read_bytes()
        cls.atlas = home.load_home_atlas(ATLAS)
        localizer = home.BlueStacksHomeLocalizer(cls.atlas, ATLAS)
        cls.localization = localizer.localize(cls.frame)
        cls.building = cls.atlas.lookup_building(home.CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        cls.binding = bind_visible_building(
            cls.frame, cls.localization, cls.building, home_is_clean=is_clean_home_frame
        )

    def navigator(self, *, atlas=None):
        safe, calibration = home.bluestacks_direct_pan_contract()
        return DirectPanNavigator(
            atlas or self.atlas, self.building.semantic_id, safe, calibration
        )

    def test_native_safe_anchor_completes_without_requiring_full_artwork_visibility(self):
        self.assertIsNotNone(self.binding)
        self.assertEqual(self.binding.target_roi, (411, 356, 560, 506))
        navigator = self.navigator()
        # The wide aircraft wing overlaps the event stack. The mapped central
        # hit region is completely clear; Campaign opens directly with no radial.
        self.assertEqual(
            home.plan_direct_pan(
                self.atlas, self.localization, self.building.semantic_id,
                navigator.safe_region, navigator.calibration,
            ).reason,
            "no_recoverable_actionable_viewport",
        )
        plan = home._plan_mapped_home_entry(navigator, self.localization, self.binding)
        self.assertEqual(plan.disposition, PlanDisposition.COMPLETE)
        self.assertIsNone(plan.drag_start)
        self.assertEqual(navigator.pan_count, 0)

        driver = home.BlueStacksLocalizeFirstHomeDriver(
            self.atlas, ATLAS, _ready(), self.building.semantic_id,
            localizer=SimpleNamespace(
                localize=lambda _frame: self.localization,
                canonical_reference=self.frame,
            ),
        )
        step = driver.observe(self.frame)
        self.assertEqual(step.disposition, home.HomeDriverDisposition.COMPLETE)
        self.assertEqual(step.binding.target_roi, self.binding.target_roi)
        self.assertEqual(driver.navigator.pan_count, 0)

    def test_invalid_binding_or_source_never_completes(self):
        self.assertIsNotNone(self.binding)
        for name, localization, binding in (
            ("stale_binding", self.localization, replace(self.binding, frame_sha256="f" * 64)),
            ("wrong_building", self.localization, replace(self.binding, building_id="home.building.bank")),
            ("overlay_binding", self.localization, replace(self.binding, overlay_intersects=True)),
            ("hud_roi", self.localization, replace(self.binding, target_roi=(580, 350, 620, 390), screen_anchor=(600, 370))),
            ("outside_bounds", self.localization, replace(self.binding, target_roi=(700, 700, 740, 740), screen_anchor=(720, 720))),
            ("wrong_anchor", self.localization, replace(self.binding, atlas_anchor=(1100, 470))),
            ("stale_source", replace(self.localization, stale=True), self.binding),
            ("overlay_source", replace(self.localization, overlay=True), self.binding),
        ):
            with self.subTest(case=name):
                self.assertEqual(
                    home._plan_mapped_home_entry(self.navigator(), localization, binding).disposition,
                    PlanDisposition.REJECTED,
                )
        self.assertEqual(
            home._plan_mapped_home_entry(
                self.navigator(atlas=replace(self.atlas, coverage_polygons=())),
                self.localization, self.binding,
            ).disposition,
            PlanDisposition.REJECTED,
        )

    def test_shared_campaign_entry_reaches_bound_dry_run_without_pan(self):
        owner = self

        class NativeReplayRuntime:
            ordinal = 0

            def capture(self, label):
                self.ordinal += 1
                return CapturedNativeFrame(
                    owner.frame.copy(), owner.payload,
                    hashlib.sha256(owner.payload).hexdigest(), time.monotonic(), FRAME,
                )

            def swipe(self, *_args, **_kwargs):
                raise AssertionError("already bound Campaign must not pan")

            def tap(self, *_args, **_kwargs):
                raise AssertionError("dry-run must not tap")

        with tempfile.TemporaryDirectory() as directory:
            runtime = NativeReplayRuntime()
            runtime.session = Path(directory)
            localizer = SimpleNamespace(localize=lambda _frame: self.localization)
            with patch(
                "scripts.atlas_runtime_startup.normalize_runtime_home_atlas_startup",
                return_value=(localizer, []),
            ):
                result = home.run_verified_campaign_home_atlas_entry(runtime, atlas_path=ATLAS)
        self.assertEqual(result["status"], "dry-run", result)
        self.assertEqual(result["records"][0]["disposition"], "complete")
        self.assertIn("binding ready", result["reason"])
