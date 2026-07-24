"""Focused tests for Campaign atlas-backed chapter navigation."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tasks.campaign_atlas import LandmarkKind, load_campaign_atlas
from tasks.campaign_atlas_chapter_nav import (
    default_campaign_atlas_path,
    localization_from_single_near_anchor,
    pan_direction_toward_screen_point,
    projected_landmark_screen_center,
    resolve_atlas_chapter_navigation,
)


ROOT = Path(__file__).resolve().parents[1]
LIVE_NEAR_CH20 = (
    ROOT
    / ".local-captures/flow-delivery/CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
    / "nav-1-20-9-20260724T201307847363Z"
    / "1-20-9-20260724T201448015456Z"
    / "frames"
    / "frame-0004.png"
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

    def test_live_frame_near_chapter_20_prefers_orb_and_local_ocr_tap(self) -> None:
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
        self.assertEqual(decision.kind, "tap")
        self.assertEqual(decision.target_identity, "campaign-chapter-20")
        self.assertIsNotNone(decision.target_roi)
        self.assertTrue(
            any(item.startswith("viewport-") for item in decision.localization_support)
            or "orb" in decision.reason.casefold()
        )


if __name__ == "__main__":
    unittest.main()
