import hashlib
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from tasks.campaign_auto_battle import CampaignAction, CampaignAutoBattleConfig, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_runtime import CampaignRuntimeController
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks import campaign_auto_battle_vision as vision
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_tesseract


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/campaign_stage_dialog"
STAGE = CampaignStage(1, 15, 9)


class NativeStageDialogTests(unittest.TestCase):
    def frame(self, name="current-stage15.png"):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1280, 800, 3))
        return frame

    def recognize(self, frame, stage=STAGE):
        return recognize_campaign_frame(frame, stage)

    def controller(self, *, stage=STAGE, cost=14, initial_ap=120):
        return CampaignRuntimeController(CampaignAutoBattleConfig(target_stage=stage, ap_cost=cost, ap_budget=cost, max_runs=1), initial_ap=initial_ap)

    @requires_tesseract
    def test_actual_ap64_after_four_wins_excludes_the_ap_icon_from_digits(self):
        path = FIXTURES / "current-stage15-ap64.png"
        provenance = json.loads(path.with_suffix(".provenance.json").read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), provenance["sha256"])
        frame = self.frame(path.name)
        result = self.recognize(frame)
        self.assertEqual(result.observation.ap_current, 64)
        self.assertEqual(result.observation.ap_cost, 14)
        self.assertTrue(result.observation.challenge_ready)
        self.assertEqual(self.controller(initial_ap=64).next_command(result, frame).action,
                         CampaignAction.CHALLENGE_STAGE)

    @requires_tesseract
    def test_impossible_ap_fraction_never_binds_a_challenge(self):
        original = vision._threshold_ocr
        for text in ("664/120", "64/0"):
            with self.subTest(text=text):
                def ocr(frame, box, *, threshold, whitelist, **kwargs):
                    return text if "/" in whitelist else original(frame, box, threshold=threshold, whitelist=whitelist, **kwargs)

                with patch.object(vision, "_threshold_ocr", side_effect=ocr):
                    result = self.recognize(self.frame())
                self.assertEqual(result.observation.screen, CampaignScreen.STAGE_DIALOG)
                self.assertIsNone(result.observation.ap_current)
                self.assertFalse(result.observation.challenge_ready)
                self.assertIsNone(result.target("campaign-challenge-1-15-9"))

    @requires_tesseract
    def test_actual_stage53_agrees_with_the_preceding_map_and_is_actionable(self):
        controller = self.controller(initial_ap=53)
        parent = self.recognize(self.frame("current-chapter15-ap53.png"))
        self.assertEqual(parent.observation.ap_current, 53)
        self.assertEqual(controller.next_command(parent).action, CampaignAction.SELECT_STAGE)
        frame = self.frame("current-stage15-ap53.png")
        result = self.recognize(frame)
        self.assertEqual(result.observation.ap_current, 53)
        self.assertEqual(controller.next_command(result, frame).action, CampaignAction.CHALLENGE_STAGE)
        self.assertEqual(controller.progress.ap_regenerated, 0)

    @requires_tesseract
    def test_implausible_stage_gain_cannot_invent_regeneration_before_entry(self):
        controller = self.controller(initial_ap=53)
        controller.next_command(self.recognize(self.frame("current-chapter15-ap53.png")))
        result = self.recognize(self.frame("current-stage15-ap53.png"))
        corrupted = replace(result, observation=replace(result.observation, ap_current=93))
        self.assertEqual(controller.next_command(corrupted).action, CampaignAction.BLOCKED)
        self.assertEqual((controller.progress.current_ap, controller.progress.ap_regenerated), (53, 0))

    @requires_tesseract
    def test_disagreeing_ap_views_wait_without_input_then_stop_or_recover(self):
        frame = self.frame("current-stage15-ap53.png")
        good = self.recognize(frame)
        original = vision._threshold_ocr

        def wrong_threshold(current, box, *, threshold, whitelist, **kwargs):
            return "93/120" if "/" in whitelist else original(current, box, threshold=threshold, whitelist=whitelist, **kwargs)

        with patch.object(vision, "_threshold_ocr", side_effect=wrong_threshold):
            uncertain = self.recognize(frame)
        self.assertIsNone(uncertain.observation.ap_current)
        self.assertIsNone(uncertain.target("campaign-challenge-1-15-9"))
        controller = self.controller(initial_ap=53)
        for _ in range(2):
            command = controller.next_command(uncertain)
            self.assertEqual((command.action, command.kind), (CampaignAction.WAIT_FOR_AP_READ, "wait"))
        self.assertEqual(controller.next_command(uncertain).action, CampaignAction.BLOCKED)
        self.assertEqual((controller.progress.current_ap, controller.progress.ap_regenerated), (53, 0))
        recovering = self.controller(initial_ap=53)
        self.assertEqual(recovering.next_command(uncertain).kind, "wait")
        self.assertEqual(recovering.next_command(good).action, CampaignAction.CHALLENGE_STAGE)

        def spaced_threshold(current, box, *, threshold, whitelist, **kwargs):
            return "53 / 120" if "/" in whitelist else original(current, box, threshold=threshold, whitelist=whitelist, **kwargs)

        with patch.object(vision, "_threshold_ocr", side_effect=spaced_threshold):
            self.assertEqual(self.recognize(frame).observation.ap_current, 53)

    @requires_tesseract
    def test_current_and_retained_dialogs_bind_all_controls_before_challenge(self):
        for name in ("current-stage15.png", "retained-stage15.png"):
            with self.subTest(name=name):
                frame = self.frame(name)
                result = self.recognize(frame)
                self.assertEqual(result.observation.screen, CampaignScreen.STAGE_DIALOG)
                self.assertEqual(result.observation.stage_dialog, STAGE)
                self.assertEqual(result.observation.ap_current, 120)
                self.assertEqual(result.observation.ap_cost, 14)
                self.assertTrue(result.observation.challenge_ready)
                self.assertIsNotNone(result.target("campaign-stage-dialog-close"))
                target = result.target("campaign-challenge-1-15-9")
                self.assertIsNotNone(target)
                self.assertLess(target[2], 400)  # Blitz and AP refill remain outside this target.
                command = self.controller().next_command(result, frame)
                self.assertEqual(command.action, CampaignAction.CHALLENGE_STAGE)
                self.assertEqual(command.target_roi, target)

    @requires_tesseract
    def test_wrong_stage_or_cost_blocks_resource_dispatch(self):
        frame = self.frame()
        wrong_stage = CampaignStage(1, 20, 9)
        result = self.recognize(frame, wrong_stage)
        self.assertEqual(self.controller(stage=wrong_stage, cost=16).next_command(result, frame).action, CampaignAction.BLOCKED)
        result = self.recognize(frame)
        self.assertEqual(self.controller(cost=16).next_command(result, frame).action, CampaignAction.BLOCKED)

    @requires_tesseract
    def test_missing_x_or_ap_icons_never_emits_challenge_target(self):
        for roi in ((665, 270, 710, 315), (288, 779, 340, 830), (204, 845, 243, 883)):
            with self.subTest(roi=roi):
                frame = self.frame()
                x0, y0, x1, y1 = roi
                frame[y0:y1, x0:x1] = (35, 35, 45)
                result = self.recognize(frame)
                self.assertIsNone(result.target("campaign-challenge-1-15-9"))
                self.assertNotEqual(self.controller().next_command(result, frame).action, CampaignAction.CHALLENGE_STAGE)

    @requires_tesseract
    def test_blitz_refill_and_disabled_button_cannot_replace_challenge(self):
        for caption in ("Blitz", "Refill", "disabled"):
            with self.subTest(caption=caption):
                frame = self.frame()
                if caption == "disabled":
                    gray = cv2.cvtColor(frame[842:921, 119:365], cv2.COLOR_BGR2GRAY)
                    frame[842:921, 119:365] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                else:
                    frame[881:920, 120:365] = (40, 115, 170)
                    cv2.putText(frame, caption, (174, 910), cv2.FONT_HERSHEY_SIMPLEX,
                                1.0, (255, 255, 255), 2, cv2.LINE_AA)
                result = self.recognize(frame)
                self.assertEqual(result.observation.screen, CampaignScreen.STAGE_DIALOG)
                self.assertIsNone(result.target("campaign-challenge-1-15-9"))
                self.assertEqual(self.controller().next_command(result, frame).action, CampaignAction.BLOCKED)

    @requires_tesseract
    def test_enemy_art_and_rewards_are_outside_selector_authority(self):
        original = self.frame()
        changed = original.copy()
        changed[385:690, 80:700] = 255 - changed[385:690, 80:700]
        self.assertNotEqual(hashlib.sha256(original.tobytes()).digest(), hashlib.sha256(changed.tobytes()).digest())
        self.assertGreater(np.count_nonzero(original != changed), 400_000)
        before, after = self.recognize(original), self.recognize(changed)
        self.assertEqual(after.observation, before.observation)
        self.assertEqual(after.targets, before.targets)

    @requires_tesseract
    def test_current_chapter_back_is_measured_and_missing_arrow_blocks(self):
        frame = self.frame("current-chapter15.png")
        result = self.recognize(frame)
        self.assertEqual(result.observation.screen, CampaignScreen.CHAPTER_MAP)
        self.assertEqual(result.observation.chapter_number, 15)
        self.assertEqual(result.target("campaign-chapter-back"), (705, 1028, 767, 1084))
        frame[995:1095, 690:780] = (20, 20, 20)
        missing = self.recognize(frame)
        self.assertEqual(missing.observation.screen, CampaignScreen.CHAPTER_MAP)
        self.assertIsNone(missing.target("campaign-chapter-back"))


if __name__ == "__main__":
    unittest.main()
