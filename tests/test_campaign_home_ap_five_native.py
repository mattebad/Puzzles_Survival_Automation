from pathlib import Path
import unittest

import cv2

from tasks.campaign_auto_battle import (
    CampaignAction, CampaignAutoBattleConfig, CampaignScreen, CampaignStage,
)
from tasks.campaign_auto_battle_runtime import CampaignRuntimeController
from tasks.campaign_auto_battle_vision import (
    HOME_AP_CURRENT_ROI, HOME_AP_ROI, _hud_ap_fraction, recognize_campaign_frame,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/campaign_ap_hud/home-ap5-stamina120-20261030.png"
HOME_ROWS = (HOME_AP_CURRENT_ROI, HOME_AP_ROI)
STAGE = CampaignStage(1, 15, 9)


class CampaignHomeAPFiveNativeTests(unittest.TestCase):
    def frame(self):
        frame = cv2.imread(str(SOURCE))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1280, 800, 3))
        return frame

    def controller(self):
        return CampaignRuntimeController(CampaignAutoBattleConfig(
            target_stage=STAGE, ap_cost=14, ap_budget=28, max_runs=2,
        ))

    def test_native_five_is_ap_five_and_cannot_admit_a_battle(self):
        frame = self.frame()
        self.assertEqual(_hud_ap_fraction(frame, HOME_ROWS), (5, 120))
        recognition = recognize_campaign_frame(frame, STAGE)
        self.assertEqual(recognition.observation.screen, CampaignScreen.HOME_BASE)
        self.assertEqual(recognition.observation.ap_current, 5)
        controller = self.controller()
        command = controller.next_command(recognition, frame)
        self.assertTrue(command.terminal)
        self.assertEqual(command.action, CampaignAction.COMPLETE)
        self.assertEqual(controller.progress.current_ap, 5)
        self.assertEqual(controller.progress.ap_spent, 0)
        self.assertEqual(controller.progress.completed_runs, 0)

    def test_unreadable_five_row_cannot_fall_back_to_stamina(self):
        frame = self.frame()
        frame[205:234, 27:122] = 0
        self.assertIsNone(_hud_ap_fraction(frame, HOME_ROWS))
        recognition = recognize_campaign_frame(frame, STAGE)
        self.assertEqual(recognition.observation.screen, CampaignScreen.UNKNOWN)
        self.assertIsNone(recognition.observation.ap_current)
        command = self.controller().next_command(recognition, frame)
        self.assertTrue(command.terminal)
        self.assertEqual(command.action, CampaignAction.BLOCKED)

    def test_five_and_retained_hundred_rows_remain_ambiguous(self):
        frame = cv2.imread(str(ROOT / "tests/fixtures/campaign_ap_hud/home-ap100-stamina120.png"))
        self.assertIsNotNone(frame)
        frame[195:234, 0:135] = (20, 20, 20)
        frame[202:231, 0:122] = self.frame()[205:234, 0:122]
        self.assertEqual(_hud_ap_fraction(frame, (HOME_AP_CURRENT_ROI,)), (5, 120))
        self.assertEqual(_hud_ap_fraction(frame, (HOME_AP_ROI,)), (100, 120))
        self.assertIsNone(_hud_ap_fraction(frame, HOME_ROWS))
        recognition = recognize_campaign_frame(frame, STAGE)
        self.assertIsNone(recognition.observation.ap_current)
        command = self.controller().next_command(recognition, frame)
        self.assertTrue(command.terminal)
        self.assertEqual(command.action, CampaignAction.BLOCKED)


if __name__ == "__main__":
    unittest.main()
