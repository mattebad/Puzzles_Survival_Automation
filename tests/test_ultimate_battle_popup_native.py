"""Native Ultimate battle regression: gem lines are not popup borders."""
from pathlib import Path
import unittest

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate


class UltimateBattlePopupNativeTests(unittest.TestCase):
    def frame(self, name="native-grid-20261101.png"):
        path = Path(__file__).parent / "fixtures/ultimate_active_battle" / name
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

    def test_native_warning_binds_flee_without_treating_canvas_edges_as_panels(self):
        for name in ("native-flee-warning-20261101.png", "native-flee-warning-over-defeat-20261101.png"):
            with self.subTest(background=name):
                frame = self.frame(name)
                self.assertEqual(ultimate._bind_flee_warning_button(frame), (436, 628, 682, 708))
                self.assertIsNone(ultimate._recognize_active_battle(frame))

    def test_warning_requires_both_controls_and_failure_text(self):
        for box in ((436, 628, 682, 708), (118, 628, 364, 708), (120, 450, 680, 590)):
            with self.subTest(erased=box):
                frame = self.frame("native-flee-warning-20261101.png")
                x0, y0, x1, y1 = box
                frame[y0:y1, x0:x1] = 0
                self.assertIsNone(ultimate._bind_flee_warning_button(frame))

    def test_unknown_panel_covering_warning_blocks_flee(self):
        frame = self.frame("native-flee-warning-20261101.png")
        cv2.rectangle(frame, (160, 400), (660, 750), (45, 45, 45), -1)
        cv2.rectangle(frame, (160, 400), (660, 750), (180, 180, 180), 6)
        self.assertIsNone(ultimate._bind_flee_warning_button(frame))

    def test_gold_purchase_label_cannot_inherit_flee_authority(self):
        frame = self.frame("native-flee-warning-20261101.png")
        frame[640:700, 460:665] = (0, 165, 210)
        cv2.putText(frame, "Buy", (500, 684), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2, cv2.LINE_AA)
        self.assertIsNone(ultimate._bind_flee_warning_button(frame))


if __name__ == "__main__":
    unittest.main()
