from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from scripts.bluestacks_flow_collector import ADBRunner

from tasks.ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsDetailObservation,
    RuinsDispatchState,
    RuinsResult,
    RuinsResultObservation,
    RuinsScreenObservation,
    challenge_action_authorized,
    chest_claim_authorized,
    chest_claim_postcondition_verified,
    current_day_allowed,
    detail_attack_authorized,
    dispatch_authorized,
    result_verified,
)
from tasks.ruins_challenge_runtime import RuinsRuntimeController, RuinsRuntimeState
from tasks.ruins_challenge_vision import (
    recognize_ruins_detail_frame,
    recognize_ruins_detail_with_targets,
    recognize_ruins_frame,
    recognize_ruins_result_frame,
    recognize_any_ruins_reward_frame,
    recognize_ruins_reward_frame,
    recognize_navigation_chat_screen,
    parse_points,
    parse_progress,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ruins_challenge_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"
RESET = "local-2026-07-16-ruins"


def load_row(name: str) -> RuinsChallengeRow:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    raw["target_roi"] = tuple(raw["target_roi"])
    return RuinsChallengeRow(**raw)


def screen(*rows: RuinsChallengeRow, source: str = "e" * 64) -> RuinsScreenObservation:
    return RuinsScreenObservation(
        recognized=True,
        screen_identity="RUINS_CHALLENGE",
        title_visible=True,
        points_balance=13426,
        exchange_control=RuinsControlState.VISIBLE_ENABLED,
        progress_control=RuinsControlState.VISIBLE_ENABLED,
        total_rank_control=RuinsControlState.VISIBLE_ENABLED,
        rows=tuple(rows),
        overlay_state="none",
        source_frame_sha256=source,
        reset_identity=RESET,
        safe_back_control=RuinsControlState.VISIBLE_ENABLED,
    )


class RuinsContractTests(unittest.TestCase):
    def test_reward_modal_uses_identity_text_and_native_orange_claim_geometry(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[689:778, 263:537] = (0, 128, 255)
        text = (
            "you cleared 60 floors in mon hero challenge reward available "
            "can claim once a week please claim before the challenge restarts next week"
        )
        with patch("tasks.ruins_challenge_vision._ocr", return_value=text), patch(
            "tasks.ruins_challenge_vision._ocr_boxes", return_value=[],
        ):
            reward = recognize_ruins_reward_frame(frame, "Hero Challenge", reset_identity=RESET)
            any_reward = recognize_any_ruins_reward_frame(frame, reset_identity=RESET)
            wrong = recognize_ruins_reward_frame(frame, "Weapon Trial", reset_identity=RESET)
        self.assertTrue(reward.recognized)
        self.assertEqual(reward.target("ruins-reward-claim"), (255, 681, 545, 786))
        self.assertTrue(any_reward.recognized)
        self.assertEqual(any_reward.identity, "Hero Challenge")
        self.assertFalse(wrong.recognized)

    def test_native_list_binds_only_fully_visible_row_local_chests(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        for top in (230, 430, 630):
            frame[top + 5:top + 75, 600:780] = (0, 200, 0)
            for x in range(600, 780, 20):
                frame[top + 75:top + 150, x:x + 10] = (80, 180, 230)
        # Nova is deliberately clipped at the native frame edge and cannot bind.
        frame[1235:1280, 600:780] = (0, 200, 0)

        row_text = {
            230: "hero challenge mon progress 60/120",
            430: "weapon trial mon progress 2/200",
            630: "tech challenge tue progress 33/120",
            1232: "nova challenge thu progress 18/100",
        }

        def fake_ocr(_frame, box=None, psm=11):
            if box is None:
                return "ruins challenge hero challenge weapon trial tech challenge nova challenge"
            if box == (0, 0, 800, 120):
                return "ruins challenge"
            if box == (40, 120, 175, 180):
                return "ruins medals 14951"
            if box == (150, 100, 800, 210):
                return "exchange progress total rank"
            if box[0] == 18:
                return row_text.get(box[1], "")
            return ""

        ocr_boxes = [
            ("hero", (227, 254, 297, 278)),
            ("weapon", (227, 454, 360, 491)),
            ("tech", (225, 654, 294, 678)),
            ("nova", (227, 1256, 285, 1277)),
        ]
        with patch("tasks.ruins_challenge_vision._ocr", side_effect=fake_ocr), patch(
            "tasks.ruins_challenge_vision._ocr_boxes", return_value=ocr_boxes,
        ):
            recognition = recognize_ruins_frame(frame, reset_identity=RESET)

        self.assertEqual(
            {identity: roi for identity, roi in recognition.targets if identity.startswith("chest:")},
            {
                "chest:Hero Challenge": (600, 235, 780, 380),
                "chest:Weapon Trial": (600, 435, 780, 580),
                "chest:Tech Challenge": (600, 635, 780, 780),
            },
        )
        self.assertEqual(recognition.observation.row("Hero Challenge").progress_current, 60)
        self.assertEqual(recognition.observation.row("Weapon Trial").progress_maximum, 200)
        self.assertEqual(recognition.observation.row("Tech Challenge").day_label, "Tue")
        self.assertEqual(recognition.observation.row("Nova Challenge").chest_state, RuinsChestState.UNKNOWN)

    def test_gear_alias_binds_only_current_day_free_challenge_with_narrow_button_roi(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        # Synthetic native orange Challenge control in the Gear row only.
        frame[410:470, 600:720] = (0, 128, 255)

        def fake_ocr(_frame, box=None, psm=11):
            if box is None:
                return "ruins challenge ear chatenge core challenge exchange mall"
            if box == (0, 0, 800, 120):
                return "ruins challenge"
            if box == (40, 120, 175, 180):
                return "ruins medals 0"
            if box == (150, 100, 800, 210):
                return "exchange mall progress total rank"
            if box[0] == 18:
                return "ear chatenge 12/100 tue" if box[1] < 500 else "core challenge requires lv 20 thu"
            return ""

        ocr_boxes = [
            ("ear chatenge", (40, 320, 200, 350)),
            ("core challenge", (40, 600, 220, 630)),
        ]
        with patch("tasks.ruins_challenge_vision._ocr", side_effect=fake_ocr), patch(
            "tasks.ruins_challenge_vision._ocr_boxes", return_value=ocr_boxes
        ):
            recognition = recognize_ruins_frame(frame, reset_identity=RESET)

        gear = recognition.observation.row("Gear Challenge")
        core = recognition.observation.row("Core Challenge")
        self.assertIsNotNone(gear)
        self.assertEqual(gear.availability, RuinsAvailability.AVAILABLE)
        self.assertEqual(gear.challenge_control, RuinsControlState.VISIBLE_ENABLED)
        self.assertTrue(current_day_allowed(gear, "Tue"))
        self.assertFalse(current_day_allowed(gear, "Wed"))
        self.assertIsNotNone(core)
        self.assertEqual(core.availability, RuinsAvailability.LOCKED)
        challenge_targets = {
            identity: roi for identity, roi in recognition.targets if identity.startswith("challenge:")
        }
        self.assertEqual(set(challenge_targets), {"challenge:Gear Challenge"})
        x0, y0, x1, y1 = challenge_targets["challenge:Gear Challenge"]
        self.assertLessEqual(x1 - x0, 150)
        self.assertLessEqual(y1 - y0, 100)
        self.assertGreater(y0, 350)
        self.assertNotIn("mall", {identity for identity, _roi in recognition.targets})
        self.assertNotEqual(recognition.target("exchange"), challenge_targets["challenge:Gear Challenge"])

    def test_navigation_chat_recognition_requires_exact_header_context(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with patch(
            "tasks.ruins_challenge_vision._ocr",
            return_value="Chat State Alliance Whisper Alliance Bulletin",
        ):
            self.assertTrue(recognize_navigation_chat_screen(frame))
        with patch(
            "tasks.ruins_challenge_vision._ocr",
            return_value="Alliance message content without navigation header",
        ):
            self.assertFalse(recognize_navigation_chat_screen(frame))

    def test_android_zoom_transport_uses_discovered_multitouch_device(self):
        capabilities = """add device 4: /dev/input/event4
  name:     \"BlueStacks Virtual Touch\"
  events:
    ABS (0003): ABS_MT_POSITION_X     : value 0, min 0, max 32767
                ABS_MT_POSITION_Y     : value 0, min 0, max 32767
                ABS_MT_TRACKING_ID    : value 0, min 0, max 65535
"""
        runner = ADBRunner("adb", "emulator-5554")
        with patch.object(runner, "shell_text", return_value=capabilities) as shell, patch.object(
            runner,
            "run",
            return_value=SimpleNamespace(returncode=0, stderr=b""),
        ) as run:
            runner.dispatch_zoom_out()
        self.assertEqual(shell.call_args_list[0].args, ("getevent", "-pl"))
        self.assertEqual(run.call_args.args, ("shell", "sh"))
        script = run.call_args.kwargs["input_payload"].decode("ascii")
        self.assertIn("sendevent /dev/input/event4 3 53", script)
        self.assertNotIn(" 3 57 ", script)
        self.assertIn("sleep 0.30", script)
        self.assertEqual(script.count("sleep 0.05"), 20)
        self.assertEqual(script.count("sendevent /dev/input/event4 0 2 0"), 42)
        self.assertTrue(script.endswith("sendevent /dev/input/event4 0 0 0\n"))

    def test_all_known_challenge_identities_are_explicit(self):
        self.assertEqual(len(KNOWN_CHALLENGE_IDENTITIES), 12)
        self.assertIn("Hero Challenge", KNOWN_CHALLENGE_IDENTITIES)
        self.assertIn("Cube Challenge", KNOWN_CHALLENGE_IDENTITIES)

    def test_current_day_filtering_and_one_or_two_available_rows(self):
        nova, module = load_row("available_nova"), load_row("available_module")
        self.assertTrue(current_day_allowed(nova, "Wed"))
        self.assertTrue(current_day_allowed(module, "Wed"))
        self.assertEqual([row.identity for row in (nova, module)], ["Nova Challenge", "Module Challenge"])
        self.assertFalse(current_day_allowed(load_row("locked_core"), "Thu"))

    def test_locked_wrong_day_and_ambiguous_rows_fail_closed(self):
        locked = load_row("locked_core")
        self.assertFalse(challenge_action_authorized(screen(locked), locked, current_day="Wed", action_key="core-1"))
        unavailable = replace(load_row("available_nova"), availability=RuinsAvailability.UNAVAILABLE)
        self.assertFalse(challenge_action_authorized(screen(unavailable), unavailable, current_day="Wed", action_key="nova-1"))
        wrong_day = replace(load_row("available_nova"), day_label="Mon")
        self.assertFalse(challenge_action_authorized(screen(wrong_day), wrong_day, current_day="Wed", action_key="nova-2"))

    def test_progress_and_points_parsing(self):
        self.assertEqual(parse_progress("Floor 47/200"), (47, 200))
        self.assertEqual(parse_progress("60 / 120"), (60, 120))
        self.assertIsNone(parse_progress("200/47"))
        self.assertEqual(parse_points("Ruins medals 16,350"), 16350)

    def test_authorization_rejects_forbidden_and_spending_controls(self):
        row = load_row("available_nova")
        valid = screen(row)
        self.assertTrue(challenge_action_authorized(valid, row, current_day="Wed", action_key="nova-1"))
        for changes in (
            {"premium": True},
            {"paid": True},
            {"ticketed": True},
            {"currency_cost": 1},
            {"forbidden_controls_seen": ("exchange",)},
            {"overlay_state": "popup"},
            {"source_frame_sha256": ""},
        ):
            candidate = replace(row, **{key: value for key, value in changes.items() if key in row.__dataclass_fields__})
            candidate_screen = replace(valid, **{key: value for key, value in changes.items() if key in valid.__dataclass_fields__})
            self.assertFalse(challenge_action_authorized(candidate_screen, candidate, current_day="Wed", action_key="nova-x"))

    def test_detail_dispatch_and_result_guards(self):
        detail = RuinsDetailObservation(
            "Nova Challenge", True, 19, 100,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            npc_troops_provided=True, npc_troops_current=200200, npc_troops_maximum=200200,
            skip_battle_enabled=True, resource_cost=0,
        )
        self.assertTrue(detail_attack_authorized(detail))
        self.assertTrue(dispatch_authorized(detail))
        self.assertFalse(dispatch_authorized(replace(detail, resource_cost=1)))
        before = load_row("available_nova")
        success = RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, 20, 100, 20, "f" * 64, RESET, True, False, False)
        failure = RuinsResultObservation("Nova Challenge", RuinsResult.FAILURE, 18, 100, None, "f" * 64, RESET, False, True, True)
        ambiguous = replace(failure, result=RuinsResult.AMBIGUOUS, explicit_failure_text=False)
        self.assertTrue(result_verified(before, success))
        self.assertTrue(result_verified(before, failure))
        self.assertFalse(result_verified(before, ambiguous))

    def test_native_vision_rejects_non_native_and_recognizes_detail_result(self):
        with self.assertRaises(ValueError):
            recognize_ruins_frame(np.zeros((1279, 800, 3), dtype=np.uint8), reset_identity=RESET)
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with patch("tasks.ruins_challenge_vision._ocr", return_value="nova challenge floor 19/100 attack dispatch npc troops 200200/200200 skip battle"):
            detail = recognize_ruins_detail_frame(frame, "Nova Challenge", reset_identity=RESET)
        self.assertTrue(detail.recognized)
        self.assertTrue(detail_attack_authorized(detail))
        with patch("tasks.ruins_challenge_vision._ocr", return_value="Nova Challenge LOSE You were defeated Tap to continue"):
            result = recognize_ruins_result_frame(frame, "Nova Challenge", before_progress=18, reset_identity=RESET)
        self.assertEqual(result.result, RuinsResult.FAILURE)
        self.assertTrue(result.tap_to_continue_visible)
        with patch("tasks.ruins_challenge_vision._ocr", return_value="unknown modal"):
            unknown = recognize_ruins_result_frame(frame, "Nova Challenge", reset_identity=RESET)
        self.assertEqual(unknown.result, RuinsResult.AMBIGUOUS)

    def test_detail_gear_context_binds_narrow_bottom_orange_attack(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[1154:1243, 263:537] = (0, 128, 255)
        with patch(
            "tasks.ruins_challenge_vision._ocr",
            return_value="gear challenge floor 67/190 z-chef",
        ), patch("tasks.ruins_challenge_vision._ocr_boxes", return_value=[]):
            recognition = recognize_ruins_detail_with_targets(frame, "Gear Challenge", reset_identity=RESET)
        self.assertTrue(recognition.observation.recognized)
        self.assertEqual(recognition.observation.attack_control, RuinsControlState.VISIBLE_ENABLED)
        target = recognition.target("ruins-attack")
        self.assertIsNotNone(target)
        x0, y0, x1, y1 = target
        self.assertTrue(240 <= x0 < x1 <= 560)
        self.assertTrue(1130 <= y0 < y1 <= 1270)
        self.assertLessEqual(x1 - x0, 300)
        self.assertLessEqual(y1 - y0, 110)

    def test_detail_orange_attack_fallback_rejects_forbidden_unknown_and_clipped_controls(self):
        def recognize(frame, text):
            with patch("tasks.ruins_challenge_vision._ocr", return_value=text), patch(
                "tasks.ruins_challenge_vision._ocr_boxes", return_value=[]
            ):
                return recognize_ruins_detail_with_targets(frame, "Gear Challenge", reset_identity=RESET)

        forbidden = np.zeros((1280, 800, 3), dtype=np.uint8)
        forbidden[1154:1243, 263:537] = (0, 128, 255)
        forbidden_recognition = recognize(forbidden, "gear challenge floor 67/190 exchange mall")
        self.assertEqual(forbidden_recognition.observation.attack_control, RuinsControlState.HIDDEN)
        self.assertIsNone(forbidden_recognition.target("ruins-attack"))

        unknown = np.zeros((1280, 800, 3), dtype=np.uint8)
        unknown[1154:1243, 263:537] = (0, 128, 255)
        unknown_recognition = recognize(unknown, "loading unknown modal")
        self.assertFalse(unknown_recognition.observation.recognized)
        self.assertIsNone(unknown_recognition.target("ruins-attack"))

        clipped = np.zeros((1280, 800, 3), dtype=np.uint8)
        clipped[1245:1280, 263:537] = (0, 128, 255)
        clipped_recognition = recognize(clipped, "gear challenge floor 67/190 z-chef")
        self.assertEqual(clipped_recognition.observation.attack_control, RuinsControlState.HIDDEN)
        self.assertIsNone(clipped_recognition.target("ruins-attack"))

    def test_dispatch_context_binds_narrow_button_and_rejects_incomplete_surfaces(self):
        def recognize(frame, text):
            with patch("tasks.ruins_challenge_vision._ocr", return_value=text), patch(
                "tasks.ruins_challenge_vision._ocr_boxes", return_value=[]
            ):
                return recognize_ruins_detail_with_targets(frame, "", reset_identity=RESET)

        def dispatch_frame():
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            frame[1149:1237, 263:537] = (0, 128, 255)
            return frame

        valid = recognize(
            dispatch_frame(),
            "dispatch npc troops 200200/200200 skip battle",
        )
        self.assertTrue(valid.observation.recognized)
        self.assertEqual(valid.observation.dispatch_control, RuinsControlState.VISIBLE_ENABLED)
        target = valid.target("ruins-dispatch")
        self.assertIsNotNone(target)
        x0, y0, x1, y1 = target
        self.assertTrue(240 <= x0 < x1 <= 560)
        self.assertTrue(1125 <= y0 < y1 <= 1260)
        self.assertLessEqual(x1 - x0, 300)
        self.assertLessEqual(y1 - y0, 110)

        generic_orange = np.zeros((1280, 800, 3), dtype=np.uint8)
        generic_orange[700:788, 263:537] = (0, 128, 255)
        generic = recognize(generic_orange, "dispatch npc troops 200200/200200 skip battle")
        self.assertEqual(generic.observation.dispatch_control, RuinsControlState.HIDDEN)
        self.assertIsNone(generic.target("ruins-dispatch"))

        for text in (
            "dispatch npc troops 200200/200200",
            "dispatch npc troops 199999/200200 skip battle",
            "dispatch npc troops 200200/200200 skip battle purchase",
        ):
            negative = recognize(dispatch_frame(), text)
            self.assertEqual(negative.observation.dispatch_control, RuinsControlState.HIDDEN)
            self.assertIsNone(negative.target("ruins-dispatch"))

        clipped = np.zeros((1280, 800, 3), dtype=np.uint8)
        clipped[1250:1280, 263:537] = (0, 128, 255)
        clipped_recognition = recognize(clipped, "dispatch npc troops 200200/200200 skip battle")
        self.assertEqual(clipped_recognition.observation.dispatch_control, RuinsControlState.HIDDEN)
        self.assertIsNone(clipped_recognition.target("ruins-dispatch"))

    def test_home_and_ruins_list_vision_bind_fresh_native_targets(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)

        def home_ocr(_frame, box=None, psm=11):
            return "headquarters ruins" if box is None else "home"

        with patch("tasks.ruins_challenge_vision._ocr", side_effect=home_ocr), patch(
            "tasks.ruins_challenge_vision._ocr_boxes", return_value=[("ruins", (84, 900, 152, 932))]
        ):
            home = recognize_ruins_frame(frame, reset_identity=RESET)
        self.assertTrue(home.observation.home_base_recognized)
        self.assertTrue(home.observation.ruins_building_recognized)
        self.assertIsNotNone(home.target("ruins-building"))
        x0, y0, x1, y1 = home.target("ruins-building")
        self.assertTrue(0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280)

        def list_ocr(_frame, box=None, psm=11):
            if box is None:
                return "nova challenge"
            if box == (0, 0, 800, 120):
                return "ruins challenge"
            if box == (40, 120, 175, 180):
                return "16350"
            if box == (150, 100, 800, 210):
                return "Exchange Progress Total Rank"
            if box[0] == 18:
                return "Nova Challenge 18/100 Wed"
            return "challenge"

        with patch("tasks.ruins_challenge_vision._ocr", side_effect=list_ocr), patch(
            "tasks.ruins_challenge_vision._ocr_boxes", return_value=[("nova", (40, 320, 140, 350))]
        ):
            ruins = recognize_ruins_frame(frame, reset_identity=RESET)
        self.assertTrue(ruins.observation.recognized)
        self.assertEqual(ruins.observation.screen_identity, "RUINS_CHALLENGE")
        self.assertEqual(ruins.observation.points_balance, 16350)
        self.assertEqual(ruins.observation.row("Nova Challenge").progress_current, 18)
        self.assertIsNotNone(ruins.target("challenge:Nova Challenge"))

    def test_chest_claim_is_independent_and_exactly_once(self):
        before = load_row("available_chest")
        observation = screen(before, source=before.source_frame_sha256)
        self.assertTrue(chest_claim_authorized(observation, before, action_key="chest-hero-1"))
        claimed = replace(before, chest_state=RuinsChestState.CLAIMED, source_frame_sha256="f" * 64)
        self.assertTrue(chest_claim_postcondition_verified(before, claimed))
        self.assertTrue(chest_claim_postcondition_verified(before, replace(claimed, progress_current=61)))
        self.assertFalse(chest_claim_postcondition_verified(before, replace(claimed, source_frame_sha256=before.source_frame_sha256)))
        controller = RuinsRuntimeController(reset_identity=RESET)
        controller.observe_list(observation)
        command = controller.plan_chest_claim(observation, before, action_key="chest-hero-1")
        self.assertEqual(command.kind, "claim_chest")
        self.assertEqual(controller.daily.challenge_initiations_completed, 0)
        self.assertEqual(controller.reconcile_chest(before, claimed, action_key="chest-hero-1").kind, "chest_reconciled")
        self.assertEqual(controller.plan_chest_claim(replace(observation, rows=(claimed,), source_frame_sha256=claimed.source_frame_sha256), claimed, action_key="chest-hero-1").kind, "blocked")

    def test_one_success_completes_daily_and_default_controller_does_not_do_second(self):
        nova = load_row("available_nova")
        controller = RuinsRuntimeController(reset_identity=RESET)
        observation = screen(nova)
        controller.observe_list(observation)
        self.assertEqual(controller.plan_challenge(observation, nova, current_day="Wed", action_key="nova-1").kind, "open_detail")
        detail = RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0)
        self.assertEqual(controller.plan_attack(detail, action_key="nova-1").kind, "attack")
        self.assertEqual(controller.plan_dispatch(detail, action_key="nova-1").kind, "dispatch")
        result = RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, 20, 100, 20, "f" * 64, RESET, True, False, False)
        self.assertEqual(controller.reconcile_result(nova, result).kind, "reconciled")
        self.assertTrue(controller.daily.initiation_complete)
        self.assertTrue(controller.daily.successful_progress_complete)
        self.assertEqual(controller.plan_challenge(observation, nova, current_day="Wed", action_key="nova-2").kind, "blocked")

    def test_failed_first_challenge_can_optionally_be_followed_by_distinct_second(self):
        nova, module = load_row("available_nova"), load_row("available_module")
        controller = RuinsRuntimeController(reset_identity=RESET, allow_optional_second=True)
        first = screen(nova)
        controller.observe_list(first)
        self.assertEqual(controller.plan_challenge(first, nova, current_day="Wed", action_key="nova-1").kind, "open_detail")
        failure = RuinsResultObservation("Nova Challenge", RuinsResult.FAILURE, 18, 100, None, "f" * 64, RESET, False, True, True)
        self.assertEqual(controller.reconcile_result(nova, failure).kind, "reconciled")
        second = replace(screen(module), source_frame_sha256="1" * 64)
        controller.observe_list(second)
        self.assertEqual(controller.plan_challenge(second, module, current_day="Wed", action_key="module-1").kind, "open_detail")
        self.assertEqual(controller.plan_challenge(second, module, current_day="Wed", action_key="module-duplicate").kind, "blocked")

    def test_ambiguous_result_stops_without_retry(self):
        nova = load_row("available_nova")
        controller = RuinsRuntimeController(reset_identity=RESET, allow_optional_second=True)
        observation = screen(nova)
        controller.observe_list(observation)
        controller.plan_challenge(observation, nova, current_day="Wed", action_key="nova-1")
        ambiguous = RuinsResultObservation("Nova Challenge", RuinsResult.AMBIGUOUS, None, None, None, "f" * 64, RESET)
        self.assertEqual(controller.reconcile_result(nova, ambiguous).kind, "blocked")
        self.assertEqual(controller.plan_challenge(observation, nova, current_day="Wed", action_key="nova-retry").kind, "blocked")
        self.assertEqual(controller.finish().kind, "blocked")

    def test_registration_and_scheduler_remain_disabled(self):
        row = next(item for item in json.loads(MATRIX.read_text(encoding="utf-8"))["objectives"] if item["objective_key"] == "ruins_challenge")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
