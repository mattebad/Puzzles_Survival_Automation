"""Hero Lineup authority is header, enabled action and five selection glyphs."""

import unittest
from pathlib import Path

import cv2

from scripts import bluestacks_ultimate_challenge as ultimate
from tests.support.environment import requires_tesseract


ROOT = Path(__file__).resolve().parents[1]


class UltimateLineupNativeTests(unittest.TestCase):
    @staticmethod
    def frame():
        return cv2.imread(str(ROOT / "tests/fixtures/ultimate_lineup/hero-lineup-20261029-a.png"))

    @requires_tesseract
    def test_native_variants_bind_same_enabled_challenge(self):
        first = self.frame()
        self.assertEqual(ultimate._bind_lineup_challenge_button(first), (287, 1178, 513, 1241))
        # Hero artwork and stars outside the check glyphs carry no authority.
        changed = first.copy()
        changed[110:465] = 0
        changed[735:1115] = 0
        self.assertNotEqual(ultimate.frame_sha256(first), ultimate.frame_sha256(changed))
        self.assertEqual(ultimate._bind_lineup_challenge_button(changed), (287, 1178, 513, 1241))

    @requires_tesseract
    def test_missing_any_selected_glyph_fails_closed(self):
        for index, (x0, y0, x1, y1) in enumerate(ultimate._HERO_LINEUP_SELECTED_CARD_ROIS):
            with self.subTest(slot=index):
                frame = self.frame()
                frame[y0:y1, x0:x1] = 0
                self.assertIsNone(ultimate._bind_lineup_challenge_button(frame))

    @requires_tesseract
    def test_changed_header_disabled_or_wrong_action_fails_closed(self):
        for part in ("header", "disabled", "wrong_action"):
            with self.subTest(part=part):
                frame = self.frame()
                if part == "header":
                    frame[0:70, 200:620] = 0
                elif part == "disabled":
                    frame[1170:1250, 277:523] = 70
                else:
                    frame[1182:1235, 295:507] = (0, 180, 220)
                    cv2.putText(frame, "Upgrade", (300, 1220), cv2.FONT_HERSHEY_SIMPLEX,
                                1, (255, 255, 255), 2, cv2.LINE_AA)
                self.assertIsNone(ultimate._bind_lineup_challenge_button(frame))

    @requires_tesseract
    def test_real_vip_and_unknown_modal_fail_closed(self):
        vip = cv2.imread(str(ROOT / "tasks/assets/navigation/800x1280/reset_popup_source.png"))
        frame = self.frame()
        frame[320:900, 40:760] = vip[320:900, 40:760]
        self.assertIsNone(ultimate._bind_lineup_challenge_button(frame))
        frame = self.frame()
        cv2.rectangle(frame, (170, 420), (630, 860), (35, 35, 35), -1)
        cv2.rectangle(frame, (170, 420), (630, 860), (220, 220, 220), 5)
        cv2.putText(frame, "Unexpected", (210, 500), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1, (255, 255, 255), 2, cv2.LINE_AA)
        self.assertIsNone(ultimate._bind_lineup_challenge_button(frame))
