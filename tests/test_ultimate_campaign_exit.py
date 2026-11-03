"""Ultimate terminal navigation requests Base once before measuring Exit."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate
from tasks.campaign_auto_battle import CampaignScreen
from tests.support.ultimate import CampaignExitRuntime, captured_native_frame


ROOT = Path(__file__).resolve().parents[1]


class UltimateCampaignExitTests(unittest.TestCase):
    BASE = (0, 1170, 132, 1280)
    EXIT = (650, 965, 785, 1090)

    @staticmethod
    def frame(marker):
        return np.full((1280, 800, 3), marker, np.uint8)

    def run_terminal(self, markers, *, post_flee=False, transport_error=False, exit_dialog=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        runtime = CampaignExitRuntime(root, [self.frame(x) for x in markers])
        if transport_error:
            actual_tap = runtime.tap

            def failing_tap(*args, **kwargs):
                actual_tap(*args, **kwargs)
                raise RuntimeError("unknown transport result")

            runtime.tap = failing_tap

        def measure(frame, _identity):
            if frame[0, 0, 0] == 3:
                return self.EXIT, 0.98
            raise RuntimeError("highlighted Exit is absent")

        recognition = SimpleNamespace(
            observation=SimpleNamespace(screen=CampaignScreen.TIER_MAP, recognized=True),
            targets=(("campaign-base-request", self.BASE),),
        )
        with patch.object(ultimate, "_campaign_context_recognized", side_effect=lambda f: int(f[0, 0, 0]) in (1, 3)), patch.object(
            ultimate, "_home_nav_terminal", side_effect=lambda f: int(f[0, 0, 0]) == 4
        ), patch.object(ultimate, "_classify_campaign_ui_open", return_value=recognition), patch.object(
            ultimate.campaign_atlas_vision, "measured_survey_target", side_effect=measure
        ), patch.object(ultimate, "_recognize_ultimate_main", return_value=None), patch.object(
            ultimate.time, "sleep", return_value=None
        ), patch.object(
            ultimate.troop_training_vision, "recognize_exit_dialog", return_value=(True, (60, 650, 380, 780))
        ):
            kwargs = dict(runtime=runtime, session=root, events=root / "events.jsonl",
                          reset_identity="game-day-test", post_input_delay=0)
            if exit_dialog:
                initial = captured_native_frame(root, self.frame(0), "dialog-source", 91)
                result = ultimate._continue_from_exit_dialog(
                    initial=initial, initial_observation=(True, (60, 650, 380, 780)), **kwargs
                )
            elif post_flee:
                result = ultimate._run_post_flee_home_route(runner=runtime.runner, **kwargs)
            else:
                result = ultimate._run_measured_campaign_exit_home_route(**kwargs)
        return runtime, result

    def test_native_current_tier_map_binds_base_and_visible_city_exit(self):
        frame = cv2.imread(str(ROOT / "tests/fixtures/ultimate_campaign_exit/campaign-before-base-20261029.png"))
        recognition = ultimate._classify_campaign_ui_open(frame)
        self.assertIs(recognition.observation.screen, CampaignScreen.TIER_MAP)
        self.assertIn(("campaign-base-request", self.BASE), recognition.targets)
        roi, score = ultimate.campaign_atlas_vision.measured_survey_target(frame, "campaign-exit-base")
        self.assertEqual(roi, (723, 1000, 771, 1050))
        self.assertGreaterEqual(score, 0.72)

    def test_base_then_transient_then_measured_exit_then_home(self):
        runtime, (terminal, detail) = self.run_terminal([1, 2, 3, 4])
        self.assertEqual(terminal, "complete_for_reset")
        self.assertEqual([t["target_identity"] for t in runtime.taps], ["campaign-base-request", "campaign-exit-base"])
        self.assertEqual(runtime.taps[1]["source"].frame[0, 0, 0], 3)
        self.assertEqual([r[1] for r in runtime.reconciliations], ["confirmed", "confirmed"])
        self.assertEqual(runtime.backs, [])
        self.assertEqual(detail["input_count"], 2)

    def test_unknown_after_one_base_stops_without_repeating_request(self):
        runtime, (terminal, _detail) = self.run_terminal([1, 2])
        self.assertEqual(terminal, "blocked_fail_closed")
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.reconciliations[-1][1], "unresolved")

    def test_accounted_base_transport_error_is_unresolved_without_retry(self):
        runtime, (terminal, _detail) = self.run_terminal([1], transport_error=True)
        self.assertEqual(terminal, "blocked_fail_closed")
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.reconciliations[-1][1], "unresolved")

    def test_terminal_only_campaign_resume_never_reenters_challenge(self):
        runtime, (terminal, _detail) = self.run_terminal([1, 1, 3, 4], post_flee=True)
        self.assertEqual(terminal, "complete_for_reset")
        self.assertEqual([t["target_identity"] for t in runtime.taps], ["campaign-base-request", "campaign-exit-base"])
        self.assertEqual(runtime.backs, [])

    def test_cancel_then_base_then_exit_accounts_all_three_inputs(self):
        runtime, (terminal, detail) = self.run_terminal([0, 1, 1, 3, 4], exit_dialog=True)
        self.assertEqual(terminal, "complete_for_reset")
        self.assertEqual([t["target_identity"] for t in runtime.taps],
                         ["exit-dialog-cancel", "campaign-base-request", "campaign-exit-base"])
        self.assertEqual(detail["recovery_input_count"], 3)

    def test_terminal_only_home_and_unknown_source_dispatch_nothing(self):
        for marker, expected in ((4, "complete_for_reset"), (2, "blocked_fail_closed")):
            with self.subTest(marker=marker):
                runtime, (terminal, _detail) = self.run_terminal([marker], post_flee=True)
                self.assertEqual(terminal, expected)
                self.assertEqual(runtime.input_count, 0)
                self.assertEqual(runtime.backs, [])
