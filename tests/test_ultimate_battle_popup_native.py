"""Native Ultimate battle regression: gem lines are not popup borders."""
from pathlib import Path
import unittest

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate


class UltimateBattlePopupNativeTests(unittest.TestCase):
    def frame(self):
        path = Path(__file__).parent / "fixtures/ultimate_active_battle/native-grid-20261101.png"
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        return frame

    def test_native_grid_allows_current_exit(self):
        self.assertEqual(ultimate._recognize_active_battle(self.frame()), (700, 20, 750, 75))

    def test_board_brightness_variation_does_not_become_a_popup(self):
        for factor in (0.8, 1.1):
            with self.subTest(factor=factor):
                frame = self.frame()
                frame[500:1030, 40:760] = np.clip(
                    frame[500:1030, 40:760].astype(float) * factor, 0, 255,
                ).astype(np.uint8)
                self.assertEqual(ultimate._recognize_active_battle(frame), (700, 20, 750, 75))

    def test_unknown_panels_still_block_exit_with_the_board_underneath(self):
        for box in ((180, 350, 650, 580), (150, 400, 650, 700),
                    (180, 550, 650, 780), (60, 400, 740, 800)):
            with self.subTest(panel=box):
                frame = self.frame()
                x0, y0, x1, y1 = box
                cv2.rectangle(frame, (x0, y0), (x1, y1), (45, 45, 45), -1)
                cv2.rectangle(frame, (x0, y0), (x1, y1), (210, 210, 210), 5)
                self.assertIsNone(ultimate._recognize_active_battle(frame))

    def test_missing_board_or_exit_never_supplies_a_target(self):
        for box in ((40, 500, 760, 1030), (690, 15, 760, 85)):
            with self.subTest(erased=box):
                frame = self.frame()
                x0, y0, x1, y1 = box
                frame[y0:y1, x0:x1] = 0
                self.assertIsNone(ultimate._recognize_active_battle(frame))


if __name__ == "__main__":
    unittest.main()
