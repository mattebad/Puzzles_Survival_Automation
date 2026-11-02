"""Actual retained Campaign HeroLineup pixels and fail-closed control guards."""
import hashlib
import json
from pathlib import Path
import unittest

import cv2

from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import read_campaign_frame, recognize_campaign_frame


FIXTURES = Path(__file__).resolve().parent / "fixtures/campaign_lineup_current"
SOURCE = FIXTURES / "hero-lineup-20261030.png"
STAGE = CampaignStage(1, 15, 9)
CONTROL = (276, 1168, 524, 1252)


class CurrentCampaignLineupTests(unittest.TestCase):
    def frame(self):
        image = cv2.imread(str(SOURCE))
        self.assertIsNotNone(image)
        self.assertEqual(image.shape, (1280, 800, 3))
        return image

    def recognize(self, frame):
        return recognize_campaign_frame(frame, STAGE)

    def assert_closed(self, frame):
        recognition = self.recognize(frame)
        self.assertFalse(recognition.observation.lineup_challenge_ready)
        self.assertNotEqual(recognition.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertIsNone(recognition.target("campaign-lineup-challenge"))
        self.assertIsNone(recognition.target("campaign-lineup-back"))

    def test_actual_png_reader_binds_current_challenge_and_source_pixels(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))[SOURCE.name]
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), manifest["sha256"])
        recognition = read_campaign_frame(SOURCE, STAGE)
        self.assertEqual(recognition.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertTrue(recognition.observation.lineup_challenge_ready)
        self.assertEqual(recognition.target("campaign-lineup-challenge"), CONTROL)
        self.assertEqual(recognition.frame_sha256, hashlib.sha256(self.frame().tobytes()).hexdigest())

    def test_missing_or_wrong_header_cannot_authorize_challenge(self):
        for caption in ("", "Hero Upgrade", "Buy Hero Lineup"):
            with self.subTest(caption=caption):
                frame = self.frame()
                frame[5:70, 200:620] = (25, 25, 35)
                if caption:
                    cv2.putText(frame, caption, (280, 43), cv2.FONT_HERSHEY_SIMPLEX,
                                0.65, (255, 255, 255), 2, cv2.LINE_AA)
                self.assert_closed(frame)

    def test_wrong_or_premium_caption_cannot_replace_challenge(self):
        for caption in ("Enhance", "Refill", "Buy Challenge"):
            with self.subTest(caption=caption):
                frame = self.frame()
                frame[1184:1238, 284:516] = (35, 150, 210)
                cv2.putText(frame, caption, (290, 1221), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2, cv2.LINE_AA)
                self.assert_closed(frame)

    def test_duplicate_or_displaced_control_remains_ambiguous(self):
        for duplicate in (True, False):
            with self.subTest(duplicate=duplicate):
                frame = self.frame()
                button = frame[1168:1252, 276:524].copy()
                if not duplicate:
                    frame[1168:1252, 276:524] = (24, 28, 36)
                frame[1168:1252, 20:268] = button
                self.assert_closed(frame)

    def test_non_gold_or_occluded_challenge_cannot_dispatch(self):
        for variant in ("non_gold", "overlay"):
            with self.subTest(variant=variant):
                frame = self.frame()
                if variant == "non_gold":
                    gray = cv2.cvtColor(frame[1168:1252, 276:524], cv2.COLOR_BGR2GRAY)
                    frame[1168:1252, 276:524] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                else:
                    frame[1194:1227, 290:510] = (40, 40, 45)
                    cv2.putText(frame, "Confirm", (315, 1220), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (255, 255, 255), 2, cv2.LINE_AA)
                self.assert_closed(frame)

    def test_current_control_is_measured_after_a_small_displacement(self):
        frame = self.frame()
        button = frame[1168:1252, 276:524].copy()
        frame[1168:1252, 276:524] = (24, 28, 36)
        frame[1165:1249, 280:528] = button
        recognition = self.recognize(frame)
        self.assertEqual(recognition.observation.screen, CampaignScreen.HERO_LINEUP)
        self.assertEqual(recognition.target("campaign-lineup-challenge"), (280, 1165, 528, 1249))


if __name__ == "__main__":
    unittest.main()
