"""Current city structure binds Exit independently of its animated highlight."""

from pathlib import Path
import unittest

import cv2
import numpy as np

from tasks.campaign_atlas_vision import measured_survey_target
from tasks.home_atlas_vision import frame_digest


ROOT = Path(__file__).resolve().parents[1]


class CampaignExitCityNativeTests(unittest.TestCase):
    @staticmethod
    def frame(variant="a"):
        return cv2.imread(str(ROOT / f"tests/fixtures/ultimate_campaign_exit/campaign-highlighted-exit-20261029-{variant}.png"))

    def test_native_different_captures_bind_city_at_current_scale(self):
        first, second = self.frame("a"), self.frame("b")
        self.assertNotEqual(frame_digest(first), frame_digest(second))
        for frame in (first, second):
            roi, score = measured_survey_target(frame, "campaign-exit-base")
            x0, y0, x1, y1 = roi
            self.assertTrue(720 <= x0 < x1 <= 775 and 995 <= y0 < y1 <= 1055)
            self.assertAlmostEqual((x0 + x1) / 2, 746.5, delta=2)
            self.assertAlmostEqual((y0 + y1) / 2, 1025.5, delta=2)
            self.assertGreaterEqual(score, 0.72)

    def test_halo_arrow_and_background_have_no_selector_authority(self):
        frame = self.frame()
        roi, _ = measured_survey_target(frame, "campaign-exit-base")
        x0, y0, x1, y1 = roi
        changed = np.zeros_like(frame)
        changed[y0:y1, x0:x1] = frame[y0:y1, x0:x1]
        self.assertNotEqual(frame_digest(frame), frame_digest(changed))
        self.assertEqual(measured_survey_target(changed, "campaign-exit-base")[0], roi)

    def test_changed_static_city_or_missing_target_fails_closed(self):
        frame = self.frame()
        x0, y0, x1, y1 = measured_survey_target(frame, "campaign-exit-base")[0]
        frame[y0:y1, x0:x1] = 80
        for image in (frame, np.zeros_like(frame)):
            with self.assertRaises(RuntimeError):
                measured_survey_target(image, "campaign-exit-base")

    def test_city_position_is_measured_within_search_band(self):
        frame = self.frame()
        x0, y0, x1, y1 = measured_survey_target(frame, "campaign-exit-base")[0]
        moved = np.zeros_like(frame)
        moved[900:900 + y1 - y0, 620:620 + x1 - x0] = frame[y0:y1, x0:x1]
        self.assertEqual(measured_survey_target(moved, "campaign-exit-base")[0],
                         (620, 900, 620 + x1 - x0, 900 + y1 - y0))
