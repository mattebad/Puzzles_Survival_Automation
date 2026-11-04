"""Focused tests for zoom-independent Base-surface recognition."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from tasks.home_base_vision import recognize_base_surface
from tests.support.environment import requires_tesseract


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nova_praise_preflight"


class HomeBaseVisionTests(unittest.TestCase):
    @requires_tesseract
    def test_zoomed_home_fixtures_are_recognized_as_base(self) -> None:
        for name in ("zoomed-home-a.png", "zoomed-home-b.png"):
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
                self.assertIsNotNone(frame)
                result = recognize_base_surface(frame)
                self.assertTrue(result.recognized, result)
                self.assertEqual(result.reason, "base_surface_recognized")
                self.assertTrue(result.native_ok)
                self.assertGreaterEqual(result.confidence, 0.7)
                evidence = " ".join(result.evidence)
                self.assertIn("left:", evidence)
                self.assertTrue(
                    "headquarters" in evidence or "landmark:" in evidence,
                    result.evidence,
                )

    def test_wrong_geometry_and_overlay_fail_closed(self) -> None:
        bad = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertFalse(recognize_base_surface(bad).recognized)
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        self.assertFalse(recognize_base_surface(frame, overlay=True).recognized)
        self.assertFalse(recognize_base_surface(frame, stale=True).recognized)

    @requires_tesseract
    def test_resource_or_empty_frame_is_not_base(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        # Synthetic resource-looking digits alone must not admit Base.
        cv2.putText(
            frame,
            "2.15M 2.79M 966K +",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        result = recognize_base_surface(frame)
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "insufficient_base_evidence")

    @requires_tesseract
    def test_exit_dialog_tokens_are_rejected(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "Exit the game?",
            (180, 520),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3,
        )
        cv2.putText(
            frame,
            "Build Research",
            (10, 360),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        result = recognize_base_surface(frame)
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "negative_surface")


class CleanHomeLabelTests(unittest.TestCase):
    @requires_tesseract
    def test_latest_native_home_control_ocr_regression_and_native_positives(self) -> None:
        from scripts.startup_normalization import classify_home_base_live

        names = (
            "native-home-bio-zoomed-20261029.png",
            "native-home-control-ocr-failure-20261029.png",
            "native-home-20261029.png",
            "native-home-pan-20261029.png",
            "native-home-return-20261028.png",
            "native-home-zoom-settled-20261029.png",
        )
        for name in names:
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES.parent / "home_base" / name))
                self.assertIsNotNone(frame)
                result = classify_home_base_live(
                    frame, cash_mall_rejected=True, safe_os_surface=True
                )
                self.assertTrue(result["recognized"], result)
                self.assertEqual(
                    result["scene_ocr_hits"], ["build", "idle", "pit", "research"]
                )

    @requires_tesseract
    def test_missing_home_control_source_is_not_home(self) -> None:
        from scripts.startup_normalization import classify_home_base_live, is_clean_home_frame

        path = FIXTURES.parent / "home_base" / "native-home-20261029.png"
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        missing_controls = frame.copy()
        missing_controls[260:535, 0:120] = 0
        result = classify_home_base_live(
            missing_controls, cash_mall_rejected=True, safe_os_surface=True
        )
        self.assertFalse(result["recognized"], result)
        self.assertFalse(is_clean_home_frame(missing_controls))

    def test_ocr_timeout_leaves_home_unrecognized(self) -> None:
        from scripts.startup_normalization import is_clean_home_frame

        frame = cv2.imread(str(FIXTURES.parent / "home_base" / "native-home-20261029.png"))
        with patch("pytesseract.image_to_string", side_effect=RuntimeError("OCR timeout")):
            self.assertFalse(is_clean_home_frame(frame))

    @requires_tesseract
    def test_native_home_with_badges_and_dynamic_artwork(self) -> None:
        from scripts.startup_normalization import is_clean_home_frame

        path = FIXTURES.parent / "home_base" / "native-home-20261029.png"
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        self.assertTrue(is_clean_home_frame(frame))
        pan_frame = cv2.imread(str(path.with_name("native-home-pan-20261029.png")))
        self.assertIsNotNone(pan_frame)
        self.assertFalse(np.array_equal(frame, pan_frame))
        self.assertTrue(is_clean_home_frame(pan_frame))
        returned = cv2.imread(str(path.with_name("native-home-return-20261028.png")))
        self.assertIsNotNone(returned)
        self.assertTrue(is_clean_home_frame(returned))
        bio_zoomed = cv2.imread(str(path.with_name("native-home-bio-zoomed-20261029.png")))
        self.assertIsNotNone(bio_zoomed)
        self.assertTrue(is_clean_home_frame(bio_zoomed))
        zoomed_out = cv2.imread(str(path.with_name("native-home-zoom-settled-20261029.png")))
        self.assertIsNotNone(zoomed_out)
        self.assertTrue(is_clean_home_frame(zoomed_out))
        animated = frame.copy()
        # Event art and footer icons lie outside the source/label OCR authority.
        animated[80:350, 600:800] = 0
        animated[1180:1235, 200:700] = 0
        self.assertFalse(np.array_equal(frame, animated))
        self.assertTrue(is_clean_home_frame(animated))

    @requires_tesseract
    def test_missing_navigation_or_base_scene_is_not_home(self) -> None:
        from scripts.startup_normalization import is_clean_home_frame

        frame = cv2.imread(str(FIXTURES.parent / "home_base" / "native-home-20261029.png"))
        self.assertIsNotNone(frame)
        for box in ((0, 1238, 800, 1280), (0, 180, 800, 1160)):
            with self.subTest(box=box):
                changed = frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                self.assertFalse(is_clean_home_frame(changed))

    @requires_tesseract
    def test_open_research_lab_radial_is_not_clean_home(self) -> None:
        from scripts.startup_normalization import is_clean_home_frame

        for name in ("stale-radial-translated-dff2386b.png", "research-lab-radial-07f3d826.png"):
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES / name))
                self.assertIsNotNone(frame)
                self.assertFalse(is_clean_home_frame(frame))


if __name__ == "__main__":
    unittest.main()
