import hashlib
from pathlib import Path
import unittest

import cv2
import numpy as np

from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/ultimate_lineup/hero-lineup-20261029-a.png"


class CampaignLineupTests(unittest.TestCase):
    def frame(self):
        frame = cv2.imread(str(SOURCE))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1280, 800, 3))
        return frame

    def recognize(self, frame):
        return recognize_campaign_frame(frame, CampaignStage(1, 20, 9))

    def test_native_scaled_lineup_binds_the_current_challenge_control(self):
        recognition = self.recognize(self.frame())
        self.assertEqual(recognition.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertTrue(recognition.observation.lineup_challenge_ready)
        target = recognition.target("campaign-lineup-challenge")
        self.assertEqual(target, (276, 1168, 524, 1252))
        self.assertEqual(recognition.target("campaign-lineup-back"), (47, 2, 128, 61))
        self.assertGreaterEqual(recognition.diagnostics["lineup_score"], 0.72)

    def test_missing_game_arrow_preserves_lineup_identity_without_a_back_target(self):
        frame = self.frame()
        frame[0:90, 0:180] = 0
        recognition = self.recognize(frame)
        self.assertEqual(recognition.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertTrue(recognition.observation.lineup_challenge_ready)
        self.assertIsNotNone(recognition.target("campaign-lineup-challenge"))
        self.assertIsNone(recognition.target("campaign-lineup-back"))

    def test_hero_art_and_selection_contents_do_not_authorize_the_control(self):
        original = self.frame()
        changed = original.copy()
        changed[80:1120] = 255 - changed[80:1120]
        self.assertNotEqual(hashlib.sha256(original.tobytes()).digest(), hashlib.sha256(changed.tobytes()).digest())
        self.assertGreater(np.count_nonzero(changed != original), 1_000_000)
        before, after = self.recognize(original), self.recognize(changed)
        self.assertEqual(after.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertEqual(after.target("campaign-lineup-challenge"), before.target("campaign-lineup-challenge"))

    def test_changed_header_gold_or_caption_rejects_dispatch_target(self):
        for variant in ("header", "gold", "caption"):
            with self.subTest(variant=variant):
                frame = self.frame()
                if variant == "header":
                    frame[5:70, 200:620] = 0
                elif variant == "gold":
                    gray = cv2.cvtColor(frame[1168:1252, 276:524], cv2.COLOR_BGR2GRAY)
                    frame[1168:1252, 276:524] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                else:
                    frame[1184:1238, 296:507] = (35, 150, 210)
                    cv2.putText(frame, "Enhance", (319, 1222), cv2.FONT_HERSHEY_SIMPLEX,
                                0.9, (255, 255, 255), 2, cv2.LINE_AA)
                result = self.recognize(frame)
                self.assertNotEqual(result.observation.screen, CampaignScreen.HERO_LINEUP)
                self.assertIsNone(result.target("campaign-lineup-challenge"))
                self.assertIsNone(result.target("campaign-lineup-back"))

    def test_duplicate_or_displaced_challenge_controls_fail_closed(self):
        for duplicate in (True, False):
            with self.subTest(duplicate=duplicate):
                frame = self.frame()
                control = frame[1168:1252, 276:524].copy()
                if not duplicate:
                    frame[1168:1252, 276:524] = (24, 28, 36)
                frame[1168:1252, 20:268] = control
                result = self.recognize(frame)
                self.assertNotEqual(result.observation.screen, CampaignScreen.HERO_LINEUP)
                self.assertIsNone(result.target("campaign-lineup-challenge"))


if __name__ == "__main__":
    unittest.main()
