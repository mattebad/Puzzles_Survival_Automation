from pathlib import Path
import unittest

import cv2

from tasks.campaign_atlas_vision import measured_survey_target
from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import CAMPAIGN_EXIT_ROI, recognize_campaign_frame
from tests.support.environment import requires_tesseract


FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/ultimate_campaign_exit"


class CampaignExitBindingTests(unittest.TestCase):
    @requires_tesseract
    def test_native_exit_variants_reuse_the_current_city_binding(self):
        for name in (
            "campaign-before-base-20261029.png",
            "campaign-highlighted-exit-20261029-a.png",
            "campaign-highlighted-exit-20261029-b.png",
        ):
            with self.subTest(name=name):
                frame = cv2.imread(str(FIXTURES / name))
                expected, _ = measured_survey_target(frame, "campaign-exit-base")
                recognition = recognize_campaign_frame(frame, CampaignStage(1, 20, 9))
                self.assertEqual(recognition.observation.screen, CampaignScreen.TIER_MAP)
                self.assertEqual(recognition.observation.ap_current, 120)
                self.assertEqual(recognition.target("campaign-exit-base"), expected)
                self.assertNotEqual(expected, CAMPAIGN_EXIT_ROI)

    @requires_tesseract
    def test_another_city_sprite_does_not_bind_the_exit_control(self):
        frame = cv2.imread(str(FIXTURES / "campaign-highlighted-exit-20261029-a.png"))
        wrong_city = frame[610:700, 370:460].copy()
        frame[780:1140, 560:800] = 0
        frame[990:1050, 710:770] = cv2.resize(wrong_city, (60, 60))
        recognition = recognize_campaign_frame(frame, CampaignStage(1, 20, 9))
        self.assertEqual(recognition.observation.screen, CampaignScreen.TIER_MAP)
        self.assertEqual(recognition.observation.ap_current, 120)
        self.assertIsNone(recognition.target("campaign-exit-base"))


if __name__ == "__main__":
    unittest.main()
