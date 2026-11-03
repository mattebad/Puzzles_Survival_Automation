import hashlib
from pathlib import Path
import unittest

import cv2
import numpy as np

from tasks.campaign_auto_battle import CampaignAction, CampaignAutoBattleConfig, CampaignRouteObservation, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_runtime import CampaignRuntimeController
from tasks.campaign_auto_battle_vision import (
    HOME_AP_CURRENT_ROI, HOME_AP_ROI, MAP_AP_CURRENT_ROI, MAP_AP_ROI,
    CampaignFrameRecognition, _ap_fraction, _hud_ap_fraction, recognize_campaign_frame,
)
from tests.ocr_memo import install_module_memo


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


ROOT = Path(__file__).resolve().parents[1]
CURRENT_HOME = "tests/fixtures/campaign_home_entry/canonical-home-20261029.png"
OLDER_HOME = "tests/fixtures/campaign_ap_hud/home-ap100-stamina120.png"
HOME_ROWS = (HOME_AP_CURRENT_ROI, HOME_AP_ROI)
MAP_ROWS = (MAP_AP_CURRENT_ROI, MAP_AP_ROI)
STAGE = CampaignStage(1, 20, 9)


class CampaignNativeAPTests(unittest.TestCase):
    def frame(self, relative):
        image = cv2.imread(str(ROOT / relative))
        self.assertIsNotNone(image)
        self.assertEqual(image.shape, (1280, 800, 3))
        return image

    def test_retained_post_victory_map_reconciles_ap_and_leaves_chapter(self):
        stage = CampaignStage(1, 15, 9)
        frame = self.frame("tests/fixtures/campaign_ap_hud/chapter15-post-victory-ap12.png")
        recognition = recognize_campaign_frame(frame, stage)
        self.assertEqual(recognition.observation.screen, CampaignScreen.CHAPTER_MAP)
        self.assertEqual(recognition.observation.ap_current, 12)
        controller = CampaignRuntimeController(CampaignAutoBattleConfig(
            target_stage=stage, ap_cost=14, ap_budget=28, max_runs=2,
        ), initial_ap=26)
        victory = CampaignFrameRecognition(CampaignRouteObservation(
            screen=CampaignScreen.RESULT, winner_visible=True, loot_visible=True,
            tap_to_continue_visible=True,
        ), "verified-victory", (("campaign-victory-continue", (271, 1101, 530, 1161)),), {})
        command = controller.next_command(victory)
        self.assertEqual(command.action, CampaignAction.CONTINUE_VICTORY)
        controller.accept_dispatched(command)
        command = controller.next_command(recognition, frame)
        self.assertEqual(command.action, CampaignAction.LEAVE_CHAPTER_MAP)
        self.assertEqual(controller.progress.initial_ap, 26)
        self.assertEqual(controller.progress.current_ap, 12)
        self.assertEqual(controller.progress.ap_spent, 14)
        self.assertEqual(controller.progress.completed_runs, 1)

    def test_current_and_retained_home_map_read_the_lightning_row(self):
        for path, screen, balance in (
            (CURRENT_HOME, CampaignScreen.HOME_BASE, 120),
            (OLDER_HOME, CampaignScreen.HOME_BASE, 100),
            ("tests/fixtures/campaign_tier_controls/current-tier-map.png", CampaignScreen.TIER_MAP, 120),
            ("tests/fixtures/campaign_tier_controls/older-tier-map.png", CampaignScreen.TIER_MAP, 21),
        ):
            with self.subTest(path=path):
                recognition = recognize_campaign_frame(self.frame(path), STAGE)
                self.assertEqual(recognition.observation.screen, screen)
                self.assertEqual(recognition.observation.ap_current, balance)
        # The retained Home image has stamina 120 and AP 100: equal counters
        # in the current image cannot substitute for resource identity.
        self.assertEqual(_hud_ap_fraction(self.frame(OLDER_HOME), HOME_ROWS), (100, 120))

    def test_full_ap_headquarters_home_is_not_blocked_by_tight_text_margin(self):
        frame = self.frame("tests/fixtures/campaign_ap_hud/home-ap120-ocr-margin-20261030.png")
        recognition = recognize_campaign_frame(frame, CampaignStage(1, 15, 9))
        self.assertEqual(recognition.observation.screen, CampaignScreen.HOME_BASE)
        self.assertTrue(recognition.observation.recognized)
        self.assertEqual(recognition.observation.ap_current, 120)
        self.assertEqual(_hud_ap_fraction(frame, HOME_ROWS), (120, 120))

    def assert_ap_cannot_dispatch(self, frame):
        recognition = recognize_campaign_frame(frame, STAGE)
        self.assertIsNone(recognition.observation.ap_current)
        controller = CampaignRuntimeController(CampaignAutoBattleConfig(
            target_stage=STAGE, ap_cost=16, ap_budget=16, max_runs=1,
        ))
        command = controller.next_command(recognition, frame)
        self.assertTrue(command.terminal)
        self.assertEqual(command.action, CampaignAction.BLOCKED)

    def test_missing_lightning_or_replaced_stamina_icon_cannot_use_valid_numbers(self):
        original = self.frame(CURRENT_HOME)
        for missing in (True, False):
            with self.subTest(missing=missing):
                changed = original.copy()
                changed[205:234, 0:23] = 0 if missing else original[176:205, 0:23]
                # The numeric AP row remains legible while identity fails.
                self.assertEqual(_ap_fraction(changed, (23, 205, 122, 234)), (120, 120))
                self.assertIsNone(_hud_ap_fraction(changed, HOME_ROWS))
                self.assert_ap_cannot_dispatch(changed)

    def test_two_individually_valid_ap_rows_are_ambiguous(self):
        current = self.frame(CURRENT_HOME)
        ambiguous = self.frame(OLDER_HOME)
        ambiguous[195:234, 0:135] = (20, 20, 20)
        ambiguous[202:231, 0:122] = current[205:234, 0:122]
        self.assertEqual(_hud_ap_fraction(ambiguous, (HOME_AP_CURRENT_ROI,)), (120, 120))
        self.assertEqual(_hud_ap_fraction(ambiguous, (HOME_AP_ROI,)), (100, 120))
        self.assertIsNone(_hud_ap_fraction(ambiguous, HOME_ROWS))
        self.assert_ap_cannot_dispatch(ambiguous)

    def test_outside_hud_animation_does_not_change_resource_identity(self):
        original = self.frame(CURRENT_HOME)
        changed = original.copy()
        changed[300:1000] = 255 - changed[300:1000]
        self.assertNotEqual(hashlib.sha256(original.tobytes()).digest(), hashlib.sha256(changed.tobytes()).digest())
        self.assertGreater(np.count_nonzero(original != changed), 1_000_000)
        self.assertEqual(_hud_ap_fraction(original, HOME_ROWS), (120, 120))
        self.assertEqual(_hud_ap_fraction(changed, HOME_ROWS), (120, 120))
        recognition = recognize_campaign_frame(changed, STAGE)
        self.assertEqual(recognition.observation.screen, CampaignScreen.HOME_BASE)
        self.assertEqual(recognition.observation.ap_current, 120)


if __name__ == "__main__":
    unittest.main()
