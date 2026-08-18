"""Focused tests for zoom-independent Base-surface recognition."""

from __future__ import annotations

from pathlib import Path
import unittest

import cv2
import numpy as np

from tasks.home_base_vision import recognize_base_surface


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nova_praise_preflight"


class HomeBaseVisionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
