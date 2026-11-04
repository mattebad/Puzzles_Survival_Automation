from pathlib import Path
import unittest

import cv2
import numpy as np

from tasks.campaign_auto_battle import CampaignAction, CampaignAutoBattleConfig, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_runtime import CampaignRuntimeController
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_tesseract


def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()


FIXTURES = Path(__file__).resolve().parent / "fixtures/campaign_victory"
STAGE = CampaignStage(1, 15, 9)


class NativeCampaignVictoryTests(unittest.TestCase):
    def frame(self, name="current-winner-45.png"):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1280, 800, 3))
        return frame

    def recognize(self, frame):
        return recognize_campaign_frame(frame, STAGE)

    def assert_no_victory_dispatch(self, frame):
        result = self.recognize(frame)
        self.assertFalse(result.observation.winner_visible)
        self.assertIsNone(result.target("campaign-victory-continue"))

    @requires_tesseract
    def test_three_native_glow_phases_and_retained_layout_bind_measured_caption(self):
        for name, caption_surface in (
            ("current-winner-44.png", (300, 1133, 500, 1158)),
            ("current-winner-45.png", (300, 1133, 500, 1158)),
            ("current-winner-46.png", (300, 1133, 500, 1158)),
            ("retained-winner.png", (289, 1117, 505, 1146)),
        ):
            with self.subTest(name=name):
                frame = self.frame(name)
                result = self.recognize(frame)
                self.assertEqual(result.observation.screen, CampaignScreen.RESULT)
                self.assertTrue(result.observation.winner_visible)
                self.assertTrue(result.observation.loot_visible)
                self.assertTrue(result.observation.tap_to_continue_visible)
                self.assertIsNotNone(result.target("campaign-victory-continue"))
                controller = CampaignRuntimeController(
                    CampaignAutoBattleConfig(target_stage=STAGE, ap_cost=14, ap_budget=14, max_runs=1), initial_ap=120)
                command = controller.next_command(result, frame)
                self.assertEqual(command.action, CampaignAction.CONTINUE_VICTORY)
                self.assertIsNotNone(command.target_roi)
                x0, y0, x1, y1 = command.target_roi
                self.assertTrue(200 <= x0 < x1 <= 610 and 1090 <= y0 < y1 <= 1190)
                # OCR engines may group nearby glow particles with a word.
                # The actual input must still land on the visible caption.
                point = ((x0 + x1) // 2, (y0 + y1) // 2)
                left, top, right, bottom = caption_surface
                self.assertTrue(left <= point[0] < right and top <= point[1] < bottom,
                                f"{name}: dispatch point {point} misses caption {caption_surface}")

    @requires_tesseract
    def test_reward_art_and_particles_outside_captions_do_not_gate_victory(self):
        original = self.frame()
        changed = original.copy()
        changed[520:1060, 70:740] = 255 - changed[520:1060, 70:740]
        before, after = self.recognize(original), self.recognize(changed)
        self.assertNotEqual(before.frame_sha256, after.frame_sha256)
        self.assertGreater(np.count_nonzero(original != changed), 500_000)
        self.assertEqual(after.observation, before.observation)
        self.assertEqual(after.targets, before.targets)

    @requires_tesseract
    def test_wrong_or_incomplete_title_cannot_authorize_continue(self):
        for caption in ("WINER", "LOSER"):
            with self.subTest(caption=caption):
                frame = self.frame()
                frame[100:280, 75:730] = 0
                cv2.putText(frame, caption, (140, 245), cv2.FONT_HERSHEY_COMPLEX,
                            2.5, (120, 210, 255), 4, cv2.LINE_AA)
                self.assert_no_victory_dispatch(frame)

    @requires_tesseract
    def test_missing_loot_or_continue_and_unknown_popup_block_continue(self):
        for kind in ("loot", "continue", "popup"):
            with self.subTest(kind=kind):
                frame = self.frame()
                if kind == "loot":
                    frame[425:515, 300:500] = 0
                elif kind == "continue":
                    frame[1090:1190, 200:610] = 0
                    cv2.putText(frame, "Tap to replay", (275, 1155), cv2.FONT_HERSHEY_SIMPLEX,
                                0.8, (120, 210, 255), 2, cv2.LINE_AA)
                else:
                    cv2.rectangle(frame, (190, 400), (610, 820), (40, 40, 40), -1)
                    cv2.putText(frame, "Connection lost", (225, 500), cv2.FONT_HERSHEY_SIMPLEX,
                                0.9, (255, 255, 255), 2, cv2.LINE_AA)
                self.assert_no_victory_dispatch(frame)

    @requires_tesseract
    def test_duplicate_or_split_row_continue_caption_is_ambiguous(self):
        for kind in ("duplicate", "split"):
            with self.subTest(kind=kind):
                frame = self.frame()
                if kind == "duplicate":
                    frame[1098:1123, 300:500] = frame[1133:1158, 300:500].copy()
                else:
                    frame[1098:1123, 389:500] = frame[1133:1158, 389:500].copy()
                    frame[1133:1158, 389:500] = 0
                self.assert_no_victory_dispatch(frame)

    @requires_tesseract
    def test_native_defeat_retains_only_its_separate_return_control(self):
        result = self.recognize(self.frame("retained-defeat.png"))
        self.assertEqual(result.observation.screen, CampaignScreen.RESULT)
        self.assertTrue(result.observation.defeat_visible)
        self.assertFalse(result.observation.winner_visible)
        self.assertIsNotNone(result.target("campaign-defeat-return"))
        self.assertIsNone(result.target("campaign-victory-continue"))


if __name__ == "__main__":
    unittest.main()
