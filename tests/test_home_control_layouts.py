"""Regression coverage for the two native Home quick-control layouts."""

from pathlib import Path
import unittest
from unittest.mock import patch

import cv2

from scripts.startup_normalization import classify_home_base_live


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nova_praise_preflight"


class HomeControlLayoutTests(unittest.TestCase):
    def frame(self, name: str = "zoomed-home-a.png"):
        frame = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        return frame

    def classify(self, frame, **kwargs):
        return classify_home_base_live(frame, cash_mall_rejected=True, **kwargs)

    def test_spaced_native_home_frames_and_missing_labels(self):
        for name in ("zoomed-home-a.png", "zoomed-home-b.png"):
            with self.subTest(name=name):
                frame = self.frame(name)
                result = self.classify(frame)
                self.assertTrue(result["recognized"], result)
                self.assertGreaterEqual(len(result["scene_ocr_hits"]), 2)
                frame[290:583, :115] = 0
                result = self.classify(frame)
                self.assertFalse(result["recognized"], result)

    def test_partial_words_and_cross_layout_singletons_do_not_authorize_home(self):
        frame = self.frame()
        with patch("pytesseract.image_to_string", side_effect=["Quest Bag Mail"] +
                   ["Buildable Researching Pits Idleness"] * 10):
            self.assertFalse(self.classify(frame)["recognized"])
        # Compact Build and spaced Idle are not two labels from one layout.
        texts = ["Quest Bag Mail", "Build", "", "", "", "", "", "", "", "", "Idle"]
        with patch("pytesseract.image_to_string", side_effect=texts):
            self.assertFalse(self.classify(frame)["recognized"])

    def test_os_gate_and_fallback_timeout_fail_closed(self):
        frame = self.frame()
        self.assertFalse(self.classify(frame, safe_os_surface=False)["recognized"])
        texts = ["Quest Bag Mail"] + [""] * 6 + [RuntimeError("OCR timeout")]
        with patch("pytesseract.image_to_string", side_effect=texts):
            self.assertFalse(self.classify(frame)["recognized"])


if __name__ == "__main__":
    unittest.main()
