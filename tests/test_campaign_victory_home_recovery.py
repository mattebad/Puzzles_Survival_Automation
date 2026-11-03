"""Victory recovery reconciles one existing AP battle without new battle input."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from safe_action_core import SafetyStore

import cv2
import numpy as np

from scripts import bluestacks_campaign_ap as live
from tasks.campaign_auto_battle import CampaignAction, CampaignRouteObservation, CampaignScreen
from tasks.campaign_auto_battle_runtime import CampaignRuntimeCommand
from tests.support.campaign import recognized


def victory(*, frame_hash="winner", roi=(271, 1101, 530, 1161)):
    return recognized(
        CampaignRouteObservation(screen=CampaignScreen.RESULT, winner_visible=True,
                                 loot_visible=True, tap_to_continue_visible=True),
        ("campaign-victory-continue", roi), frame_hash=frame_hash,
    )


class CampaignVictoryHomeRecoveryTests(unittest.TestCase):
    def run_cli(self, observations, *, initial_ap=120, extra=(), command=None, timeout=25):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name)
        runners = []

        class Runner:
            def __init__(self, *_args):
                self.taps = []
                self.swipes = []
                runners.append(self)

            def list_devices(self):
                return [type("Device", (), {"serial": "emulator-5554", "state": "device"})()]

            def get_state(self):
                return "device"

            def dispatch_tap(self, point):
                self.taps.append(point)

            def dispatch_swipe(self, *args):
                self.swipes.append(args)

            def capture_png(self):
                return cv2.imencode(".png", np.full((1280, 800, 3), 127, np.uint8))[1].tobytes()

        def connect(**kwargs):
            return live.LocalBlueStacksRuntime(
                Runner(), kwargs["output_directory"] / f"{kwargs['workflow']}-test", execute=True)

        class Clock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = Clock()
        queue = iter(observations)
        last = observations[-1]

        def recognize(*_args, **_kwargs):
            nonlocal last
            last = next(queue, last)
            return last

        argv = ["--adb", "unused-adb", "--serial", "emulator-5554", "--stage", "1-15-9",
                "--ap-cost", "14", "--ap-budget", "14", "--max-runs", "1", "--max-inputs", "16",
                "--initial-ap", str(initial_ap), "--victory-home-only", "--execute", "--yes",
                "--output-directory", str(output), "--post-input-delay", "0", "--poll-seconds", "0.1",
                "--recognition-timeout", str(timeout), *extra]
        with patch.object(live.LocalBlueStacksRuntime, "connect", side_effect=connect), patch.object(
            live, "open_canonical_action_store", side_effect=lambda: SafetyStore(output / "actions.sqlite3")
        ), patch.object(
            live, "recognize_campaign_frame", side_effect=recognize
        ), patch.object(live, "is_permitted_local_bluestacks_serial", return_value=True), patch.object(
            live, "require_campaign_home_atlas_building"
        ), patch.object(live.time, "monotonic", side_effect=clock.monotonic), patch.object(
            live.time, "sleep", side_effect=clock.sleep
        ):
            if command is not None:
                with patch.object(live.CampaignRuntimeController, "next_command", return_value=command):
                    code = live.main(argv)
            else:
                code = live.main(argv)
        result = json.loads(next(output.glob("*/result.json")).read_text())
        return code, result, runners[0], clock

    def test_wrong_first_recognized_source_dispatches_zero_input(self):
        for screen in (CampaignScreen.CHAPTER_MAP, CampaignScreen.HOME_BASE, CampaignScreen.BATTLE):
            with self.subTest(screen=screen):
                code, result, runner, _clock = self.run_cli([
                    recognized(CampaignRouteObservation(screen=screen, ap_current=106, auto_enabled=True))
                ])
                self.assertEqual(code, 3)
                self.assertTrue(result["victory_home_only"])
                self.assertEqual(result["new_battle_count"], 0)
                self.assertEqual(runner.taps, [])
                self.assertEqual(runner.swipes, [])

    def test_forbidden_new_battle_command_is_blocked_before_transport(self):
        for action, kind in ((CampaignAction.CONFIRM_LINEUP, "tap"),
                             (CampaignAction.ENABLE_AUTO, "tap"),
                             (CampaignAction.OPEN_CAMPAIGN, "home_atlas_entry"),
                             (CampaignAction.SELECT_TIER, "tap"),
                             (CampaignAction.CHALLENGE_STAGE, "tap"),
                             (CampaignAction.SELECT_STAGE, "tap"),
                             (CampaignAction.RETURN_HOME, "tap"),
                             (CampaignAction.NAVIGATE_CHAPTER, "swipe"),
                             (CampaignAction.NAVIGATE_STAGE, "swipe")):
            with self.subTest(action=action):
                command = CampaignRuntimeCommand(action, kind, "forbidden", target_roi=(200, 300, 400, 500),
                                                 target_identity="campaign-lineup-challenge")
                code, _result, runner, _clock = self.run_cli([victory()], command=command)
                self.assertEqual(code, 3)
                self.assertEqual(runner.taps, [])
                self.assertEqual(runner.swipes, [])

    def test_one_continue_despite_new_winner_hash_and_roi_then_ap_ledger_and_home(self):
        for ap_after in (106, 107):
            with self.subTest(ap_after=ap_after):
                observations = [victory(), victory(frame_hash="animation-1"),
                                victory(frame_hash="animation-2", roi=(270, 1100, 529, 1160)),
                                recognized(CampaignRouteObservation(screen=CampaignScreen.CHAPTER_MAP,
                                           ap_current=ap_after), ("campaign-chapter-back", (670, 960, 800, 1095)), frame_hash="chapter"),
                                recognized(CampaignRouteObservation(screen=CampaignScreen.TIER_MAP, selected_tier=1),
                                           ("campaign-exit-base", (723, 1001, 770, 1050)), frame_hash="tier"),
                                recognized(CampaignRouteObservation(screen=CampaignScreen.HOME_BASE,
                                           ap_current=ap_after), frame_hash="home")]
                code, result, runner, _clock = self.run_cli(observations)
                self.assertEqual(code, 0)
                self.assertEqual(len(runner.taps), 3)
                self.assertEqual(runner.taps.count((400, 1131)), 1)
                self.assertEqual(result["progress"]["completed_runs"], 1)
                self.assertEqual(result["progress"]["ap_spent"], 14)
                self.assertEqual(result["progress"]["ap_regenerated"], ap_after - 106)
                self.assertEqual(result["ap_after"], ap_after)
                self.assertEqual(result["new_battle_count"], 0)

    def test_continue_successor_deadline_bounds_readonly_waits(self):
        code, result, runner, clock = self.run_cli([victory()], timeout=0.05)
        self.assertEqual(code, 3)
        self.assertEqual(len(runner.taps), 1)
        self.assertIn("timed out", result["reason"])
        self.assertLess(clock.now, 1)

    def test_recovery_config_cannot_authorize_multiple_runs_or_navigation(self):
        for extra in (("--max-runs", "2"), ("--ap-budget", "28"), ("--navigation-only",)):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                self.run_cli([victory()], extra=extra)
        with self.assertRaises(SystemExit):
            self.run_cli([victory()], initial_ap=13)
