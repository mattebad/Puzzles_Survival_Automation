"""Focused tests for Campaign atlas-backed chapter navigation."""

from __future__ import annotations

import unittest
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from tasks.campaign_atlas import LandmarkKind, load_campaign_atlas
from tasks.campaign_atlas_chapter_nav import (
    CHAPTER_SAFE_VIEWPORT,
    chapter_roi_is_safely_framed,
    default_campaign_atlas_path,
    localization_from_single_near_anchor,
    pan_direction_toward_screen_point,
    projected_landmark_screen_center,
    projection_is_safely_framed,
    resolve_atlas_chapter_navigation,
)
from tasks.campaign_atlas_vision import hud_safe_pan_gesture


ROOT = Path(__file__).resolve().parents[1]
LIVE_NEAR_CH20 = (
    ROOT
    / ".local-captures/flow-delivery/CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
    / "nav-1-20-9-20260724T201307847363Z"
    / "1-20-9-20260724T201448015456Z"
    / "frames"
    / "frame-0004.png"
)
LIVE_CH2_FALSE_BADGE = (
    ROOT
    / ".local-captures/flow-delivery/CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
    / "auto-2-2-9-20260726T190122399712Z"
    / "2-2-9-20260726T190128367763Z"
    / "frames"
    / "frame-0002.png"
)
LIVE_CH15_EDGE_CLIPPED = (
    ROOT
    / ".local-captures/flow-delivery/CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
    / "auto-1-15-9-20260726T191300995213Z"
    / "1-15-9-20260726T191306611467Z"
    / "frames"
    / "frame-0005.png"
)
LIVE_CH2_ECLIPOLIS = (
    ROOT
    / ".local-captures/development-sessions"
    / "observe-20260815T005959023610Z"
    / "observe.png"
)


class CampaignAtlasChapterNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.atlas_path = default_campaign_atlas_path()
        if not cls.atlas_path.is_file():
            raise unittest.SkipTest("accepted Campaign atlas artifact is absent")
        cls.atlas = load_campaign_atlas(cls.atlas_path)

    def test_accepted_atlas_has_supported_chapter_landmarks(self) -> None:
        for chapter in (2, 15, 20):
            landmark = self.atlas.lookup_landmark(
                kind=LandmarkKind.CHAPTER, label=f"Chapter {chapter}"
            )
            self.assertIsNotNone(landmark)
            assert landmark is not None
            self.assertTrue(landmark.spatially_associated)

    def test_single_near_anchor_projects_chapter_20_from_chapter_15(self) -> None:
        localization, count = localization_from_single_near_anchor(
            atlas=self.atlas,
            visible_chapter_rois={15: (532, 249, 599, 308)},
            frame_sha256="test",
            target_chapter=20,
        )
        self.assertEqual(count, 1)
        self.assertIsNotNone(localization)
        assert localization is not None
        landmark = self.atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label="Chapter 20")
        assert landmark is not None
        projected = projected_landmark_screen_center(localization, landmark.atlas_roi)
        self.assertIsNotNone(projected)
        assert projected is not None
        direction = pan_direction_toward_screen_point(projected[0], projected[1])
        self.assertIn(direction, {"top", "right", "bottom", "left"})

    def test_safe_framing_requires_projection_and_complete_roi_clear_of_hud(self) -> None:
        x0, y0, x1, y1 = CHAPTER_SAFE_VIEWPORT
        self.assertTrue(projection_is_safely_framed((x0 + x1) / 2, (y0 + y1) / 2))
        self.assertFalse(projection_is_safely_framed(x0 - 1, (y0 + y1) / 2))
        self.assertTrue(chapter_roi_is_safely_framed((240, 300, 360, 360)))
        self.assertFalse(chapter_roi_is_safely_framed((120, 300, 360, 360)))
        self.assertFalse(chapter_roi_is_safely_framed((580, 940, 680, 1010)))

    def test_live_frame_near_chapter_20_reframes_before_tap(self) -> None:
        if not LIVE_NEAR_CH20.is_file():
            raise unittest.SkipTest("retained live frame near Chapter 20 is absent")
        frame = np.asarray(Image.open(LIVE_NEAR_CH20).convert("RGB"))
        # Weak OCR set that previously overrode ORB with a single Ch.21 anchor.
        decision = resolve_atlas_chapter_navigation(
            frame,
            destination_id="1-20-9",
            visible_chapter_rois={
                3: (581, 229, 648, 291),
                21: (539, 766, 604, 825),
                24: (298, 313, 378, 373),
            },
        )
        self.assertEqual(decision.kind, "swipe")
        self.assertIsNotNone(decision.swipe)
        self.assertIn("safely frame", decision.reason)
        self.assertTrue(
            any(item.startswith("viewport-") for item in decision.localization_support)
            or "orb" in decision.reason.casefold()
        )

    def test_retained_chapter_2_false_badge_is_ignored_when_eclipolis_binds(self) -> None:
        if not LIVE_CH2_FALSE_BADGE.is_file():
            raise unittest.SkipTest("retained Chapter 2 false-badge frame is absent")
        frame = np.asarray(Image.open(LIVE_CH2_FALSE_BADGE).convert("RGB"))
        decision = resolve_atlas_chapter_navigation(
            frame,
            destination_id="2-2-9",
            visible_chapter_rois={4: (259, 384, 302, 428), 6: (68, 333, 117, 387)},
        )
        self.assertEqual(decision.kind, "tap")
        self.assertEqual(decision.target_identity, "campaign-chapter-2")
        self.assertIsNotNone(decision.target_roi)
        assert decision.target_roi is not None
        # The false 2x3 event badge is in the fixed upper-right event stack.
        self.assertLess(decision.target_roi[2], 560)
        self.assertGreater(decision.target_roi[1], 700)

    def test_retained_chapter_2_eclipolis_frame_binds_medallion_not_label(self) -> None:
        if not LIVE_CH2_ECLIPOLIS.is_file():
            raise unittest.SkipTest("retained Chapter 2 Eclipolis frame is absent")
        frame = np.asarray(Image.open(LIVE_CH2_ECLIPOLIS).convert("RGB"))
        decision = resolve_atlas_chapter_navigation(
            frame,
            destination_id="2-2-9",
        )
        self.assertEqual(decision.kind, "tap")
        self.assertEqual(decision.target_identity, "campaign-chapter-2")
        self.assertIsNotNone(decision.target_roi)
        assert decision.target_roi is not None
        # Retained Eclipolis text starts to the right of x=348; target the medallion.
        self.assertLessEqual(decision.target_roi[2], 348)

    def test_retained_edge_clipped_chapter_15_frame_never_taps(self) -> None:
        if not LIVE_CH15_EDGE_CLIPPED.is_file():
            raise unittest.SkipTest("retained edge-clipped Chapter 15 frame is absent")
        frame = np.asarray(Image.open(LIVE_CH15_EDGE_CLIPPED).convert("RGB"))
        decision = resolve_atlas_chapter_navigation(
            frame,
            destination_id="1-15-9",
            visible_chapter_rois={17: (590, 752, 656, 811), 23: (248, 462, 316, 521)},
        )
        self.assertNotEqual(decision.kind, "tap")


class PortableCampaignAtlasReframeTests(unittest.TestCase):
    """Replay native geometry without depending on the local full atlas bundle."""

    def setUp(self) -> None:
        metadata_path = ROOT / "tests/fixtures/campaign_atlas_chapter_nav/chapter15-atlas-geometry.json"
        geometry = json.loads(metadata_path.read_text(encoding="utf-8"))["landmarks"]

        class GeometryAtlas:
            def lookup_landmark(self, *, kind, label):
                roi = geometry.get(label) if kind is LandmarkKind.CHAPTER else None
                return SimpleNamespace(atlas_roi=tuple(roi), spatially_associated=True) if roi else None

        self.atlas = GeometryAtlas()
        localizer = SimpleNamespace(localize=lambda *_args, **_kwargs: SimpleNamespace(
            recognized=False, residual_px=None, ambiguity_state="INSUFFICIENT_LANDMARKS"))
        self.enterContext(patch("tasks.campaign_atlas_chapter_nav._cached_atlas_and_localizer",
                                return_value=(self.atlas, localizer, metadata_path)))
        self.enterContext(patch("tasks.campaign_atlas_chapter_nav.bind_campaign_destination_from_current_frame",
                                return_value=SimpleNamespace(bound=False, current_frame_roi=None,
                                                             reason="retained template miss: 0.197")))

    def test_native_chapter_15_hud_occlusion_reframes_without_tapping(self) -> None:
        path = ROOT / "tests/fixtures/campaign_atlas_chapter_nav/chapter15-right-hud-20261101.png"
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         "283cbb8f026c5fc3103ef80589f49db1891ec89a626324113d31045ec5fb294c")
        # Exact retained route OCR targets from the same frame.
        rois = {12: (219, 257, 273, 311), 15: (638, 446, 705, 506),
                17: (622, 955, 666, 999), 2: (449, 863, 493, 917),
                22: (245, 945, 327, 1026), 23: (277, 659, 333, 715),
                24: (23, 747, 75, 799), 4: (340, 875, 414, 949),
                43: (475, 120, 533, 178)}
        decision = resolve_atlas_chapter_navigation(frame, destination_id="1-15-9",
                                                    visible_chapter_rois=rois)
        self.assertEqual(decision.kind, "swipe", decision)
        self.assertEqual(decision.pan_direction, "right")
        self.assertEqual(decision.swipe, hud_safe_pan_gesture("right").as_swipe())
        self.assertIsNone(decision.target_roi)
        self.assertFalse(decision.binding_bound)
        self.assertAlmostEqual(decision.projected_screen_center[0], 700.0)
        self.assertGreaterEqual(decision.anchor_count, 2)
        self.assertEqual(decision.localization_support, ("chapter-15", "chapter-24"))

    def test_unbound_reframe_requires_supported_localization_near_edge(self) -> None:
        landmark = self.atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label="Chapter 15")
        assert landmark is not None
        ax = (landmark.atlas_roi[0] + landmark.atlas_roi[2]) / 2
        ay = (landmark.atlas_roi[1] + landmark.atlas_roi[3]) / 2
        def localization(*, recognized=True, x=690, residual=25, support=("chapter-15", "chapter-24")):
            return SimpleNamespace(recognized=recognized, screen_to_atlas=((1, 0, ax-x), (0, 1, ay-480), (0, 0, 1)),
                                   residual_px=residual, supporting_viewports=support)
        cases = ((localization(recognized=False), 2), (localization(), 1),
                 (localization(residual=121), 2), (localization(x=400), 2))
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        for loc, count in cases:
            with self.subTest(localization=loc, count=count), \
                 patch("tasks.campaign_atlas_chapter_nav._pick_localization", return_value=(loc, count, "test")), \
                 patch("tasks.campaign_atlas_chapter_nav.bind_campaign_destination_from_current_frame",
                       return_value=SimpleNamespace(bound=False, reason="no binding", current_frame_roi=None)), \
                 patch("tasks.campaign_atlas_chapter_nav.ocr_chapter_roi_near_projection", return_value=None):
                decision = resolve_atlas_chapter_navigation(frame, destination_id="1-15-9")
            self.assertEqual(decision.kind, "blocked", decision)
            self.assertIsNone(decision.target_roi)


if __name__ == "__main__":
    unittest.main()
