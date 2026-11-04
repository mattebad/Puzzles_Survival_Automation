from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from tasks.campaign_auto_battle import (
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignRouteObservation,
    CampaignScreen,
    CampaignStage,
)
from tasks.campaign_auto_battle_runtime import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID,
    CHAPTER_PAN_TOWARD_HIGHER,
    CHAPTER_PAN_TOWARD_LOWER,
    HOME_PAN_GESTURES,
    STAGE_PAN_TOWARD_HIGHER,
    STAGE_PAN_TOWARD_LOWER,
    CampaignRuntimeController,
    home_pan_gestures_for_campaign_entry,
    residual_pan_swipe,
)
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition, read_campaign_frame
from tasks.campaign_auto_battle_vision import BUY_NOW_FORBIDDEN_ROI, DEFEAT_CONTINUE_ROI
from tasks.campaign_auto_battle_vision import _fraction
from tests.support.campaign import recognized
from tests.support.local_captures import require_capture, requires_local_captures
from tests.support.environment import requires_tesseract


class CampaignRuntimeControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stage = CampaignStage.parse("1-20-9")
        self.config = CampaignAutoBattleConfig(
            target_stage=self.stage,
            ap_cost=16,
            ap_budget=96,
            max_runs=6,
            battle_poll_seconds=0.1,
            battle_timeout_seconds=180,
        )
        self.controller = CampaignRuntimeController(self.config)

    def test_lost_atlas_support_reframes_once_after_strong_pan_then_requires_new_binding(self):
        from tasks.campaign_atlas_chapter_nav import AtlasChapterNavDecision
        from tasks.campaign_atlas_vision import hud_safe_pan_gesture
        source = recognized(CampaignRouteObservation(screen=CampaignScreen.TIER_MAP, selected_tier=1,
                            chapter_navigation_available=True, ap_current=99))
        def plan(distance):
            return AtlasChapterNavDecision("swipe", "atlas-directed pan", swipe=hud_safe_pan_gesture("right").as_swipe(),
                pan_direction="right", localization_recognized=True, distance_to_screen_center_px=distance,
                localization_support=("viewport-062",))
        lost = AtlasChapterNavDecision("blocked", "no current atlas localization")
        with patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation",
                   side_effect=[plan(900), plan(700), lost, lost]):
            first = self.controller._atlas_chapter_command(source, object())
            self.controller.accept_dispatched(first)
            stronger = self.controller._atlas_chapter_command(source, object())
            self.controller.accept_dispatched(stronger)
            reframe = self.controller._atlas_chapter_command(source, object())
            self.assertEqual(reframe.kind, "swipe")
            self.assertNotEqual(reframe.swipe, stronger.swipe)
            self.assertIsNone(reframe.target_identity)
            self.controller.accept_dispatched(reframe)
            stopped = self.controller._atlas_chapter_command(source, object())
            self.assertTrue(stopped.terminal)
            self.assertEqual(stopped.action, CampaignAction.BLOCKED)

    def test_localized_unbound_destination_does_not_receive_lost_support_reframe(self):
        from tasks.campaign_atlas_chapter_nav import AtlasChapterNavDecision
        from tasks.campaign_atlas_vision import hud_safe_pan_gesture
        source = recognized(CampaignRouteObservation(screen=CampaignScreen.TIER_MAP, selected_tier=1,
                            chapter_navigation_available=True, ap_current=99))
        initial = AtlasChapterNavDecision("swipe", "atlas-directed pan", swipe=hud_safe_pan_gesture("right").as_swipe(),
            pan_direction="right", localization_recognized=True, distance_to_screen_center_px=900,
            localization_support=("viewport-062",))
        unbound = AtlasChapterNavDecision("blocked", "current projected destination cannot be bound",
            localization_recognized=True, distance_to_screen_center_px=500, localization_support=("viewport-062",))
        with patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation", side_effect=[initial, unbound]):
            self.controller.accept_dispatched(self.controller._atlas_chapter_command(source, object()))
            stopped = self.controller._atlas_chapter_command(source, object())
            self.assertTrue(stopped.terminal)
            self.assertEqual(stopped.reason, unbound.reason)

    def test_unbound_edge_reframe_needs_progress_and_fresh_binding(self):
        from tasks.campaign_atlas_chapter_nav import AtlasChapterNavDecision
        from tasks.campaign_atlas_vision import hud_safe_pan_gesture
        source = recognized(CampaignRouteObservation(screen=CampaignScreen.TIER_MAP, selected_tier=1,
                            chapter_navigation_available=True, ap_current=99))
        initial = AtlasChapterNavDecision("swipe", "Campaign atlas-directed reframe unbound chapter",
            swipe=hud_safe_pan_gesture("right").as_swipe(), pan_direction="right",
            localization_recognized=True, distance_to_screen_center_px=340,
            localization_support=("chapter-15", "chapter-24"))
        bound = AtlasChapterNavDecision("tap", "fresh binding", target_identity="campaign-chapter-20",
            target_roi=(400, 440, 460, 500), localization_recognized=True, binding_bound=True)
        with patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation", side_effect=(initial, initial)):
            self.controller.accept_dispatched(self.controller._atlas_chapter_command(source, object()))
            stopped = self.controller._atlas_chapter_command(source, object())
            self.assertTrue(stopped.terminal)
            self.assertEqual(stopped.action, CampaignAction.BLOCKED)
        controller = CampaignRuntimeController(self.config)
        with patch("tasks.campaign_atlas_chapter_nav.resolve_atlas_chapter_navigation", side_effect=(initial, bound)):
            controller.accept_dispatched(controller._atlas_chapter_command(source, object()))
            command = controller._atlas_chapter_command(source, object())
            self.assertEqual(command.kind, "tap")
            self.assertEqual(command.target_roi, bound.target_roi)

    def test_route_uses_bound_targets_and_only_lineup_challenge(self):
        home = recognized(
            CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
            ("campaign-entry", (400, 500, 520, 610)),
            frame_hash="home",
        )
        command = self.controller.next_command(home)
        self.assertEqual(command.action, CampaignAction.OPEN_CAMPAIGN)
        self.assertEqual(command.kind, "home_atlas_entry")
        self.assertEqual(command.target_identity, CAMPAIGN_HOME_ATLAS_BUILDING_ID)

        tier = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=20,
                chapter_navigation_available=True,
                ap_current=99,
            ),
            ("campaign-chapter-20", (300, 400, 420, 480)),
            frame_hash="tier",
        )
        self.assertEqual(self.controller.next_command(tier).tap_point, (360, 440))

        unsafe_tier = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=20,
                chapter_navigation_available=True,
                ap_current=99,
            ),
            ("campaign-chapter-20", (620, 930, 700, 1010)),
            frame_hash="unsafe-tier",
        )
        unsafe_command = CampaignRuntimeController(self.config).next_command(unsafe_tier)
        self.assertEqual(unsafe_command.action, CampaignAction.BLOCKED)
        self.assertIn("edge/HUD clipped", unsafe_command.reason)

        chapter = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(9,),
                stage_navigation_available=True,
                ap_current=99,
            ),
            ("campaign-stage-1-20-9", (500, 600, 560, 660)),
            frame_hash="chapter",
        )
        self.assertEqual(self.controller.next_command(chapter).action, CampaignAction.SELECT_STAGE)

        dialog = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.STAGE_DIALOG,
                stage_dialog=self.stage,
                ap_current=99,
                ap_cost=16,
                challenge_ready=True,
            ),
            ("campaign-challenge-1-20-9", (87, 863, 364, 956)),
            frame_hash="dialog",
        )
        self.assertEqual(self.controller.next_command(dialog).action, CampaignAction.CHALLENGE_STAGE)

        lineup = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.HERO_LINEUP,
                lineup_challenge_ready=True,
            ),
            ("campaign-lineup-challenge", (262, 1156, 538, 1249)),
            frame_hash="lineup",
        )
        lineup_command = self.controller.next_command(lineup)
        self.assertEqual(lineup_command.action, CampaignAction.CONFIRM_LINEUP)
        self.assertEqual(lineup_command.target_identity, "campaign-lineup-challenge")

    def test_auto_poll_victory_and_exact_ap_ledger(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home",
            )
        )
        disabled = recognized(
            CampaignRouteObservation(screen=CampaignScreen.BATTLE, auto_enabled=False),
            ("campaign-auto", (630, 16, 692, 74)),
            frame_hash="disabled",
        )
        self.assertEqual(self.controller.next_command(disabled).action, CampaignAction.ENABLE_AUTO)
        enabled = recognized(
            CampaignRouteObservation(screen=CampaignScreen.BATTLE, auto_enabled=True),
            frame_hash="enabled",
        )
        self.assertEqual(self.controller.next_command(enabled).kind, "wait")

        victory = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.RESULT,
                winner_visible=True,
                loot_visible=True,
                tap_to_continue_visible=True,
            ),
            ("campaign-victory-continue", (271, 1101, 530, 1161)),
            frame_hash="victory",
        )
        command = self.controller.next_command(victory)
        self.assertEqual(command.action, CampaignAction.CONTINUE_VICTORY)
        self.controller.accept_dispatched(command)

        chapter = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(9,),
                stage_navigation_available=True,
                ap_current=84,
            ),
            ("campaign-stage-1-20-9", (1, 1, 2, 2)),
            frame_hash="post",
        )
        self.assertEqual(self.controller.next_command(chapter).action, CampaignAction.SELECT_STAGE)
        self.assertEqual(self.controller.progress.completed_runs, 1)
        self.assertEqual(self.controller.progress.ap_spent, 16)
        self.assertEqual(self.controller.progress.ap_regenerated, 1)

    def test_missing_map_target_uses_campaign_atlas_not_ocr_residual_pan(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home",
            )
        )
        tier = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=None,
                visible_chapter_numbers=(3, 4, 5),
                chapter_navigation_available=True,
            ),
            ("campaign-chapter-3", (100, 100, 200, 200)),
            frame_hash="tier",
        )
        command = self.controller.next_command(tier)
        self.assertEqual(command.action, CampaignAction.BLOCKED)
        self.assertIn("Campaign atlas chapter navigation requires the current native frame", command.reason)
        self.assertIsNone(command.swipe)

    def test_return_home_requires_one_request_then_highlighted_exit(self):
        controller = CampaignRuntimeController(self.config, initial_ap=8)
        tier = CampaignRouteObservation(
            screen=CampaignScreen.TIER_MAP,
            selected_tier=1,
            chapter_navigation_available=True,
            ap_current=8,
        )
        request = controller.next_command(
            recognized(
                tier,
                ("campaign-base-request", (0, 1170, 132, 1280)),
                frame_hash="tier-request",
            )
        )
        self.assertEqual(request.target_identity, "campaign-base-request")
        controller.accept_dispatched(request)

        repeated = controller.next_command(
            recognized(
                tier,
                ("campaign-base-request", (0, 1170, 132, 1280)),
                frame_hash="tier-request-animated",
            )
        )
        self.assertTrue(repeated.terminal)
        self.assertIn("did not appear", repeated.reason)

        controller = CampaignRuntimeController(self.config, initial_ap=8)
        request = controller.next_command(
            recognized(tier, ("campaign-base-request", (0, 1170, 132, 1280)), frame_hash="a")
        )
        controller.accept_dispatched(request)
        exit_command = controller.next_command(
            recognized(
                tier,
                ("campaign-base-request", (0, 1170, 132, 1280)),
                ("campaign-exit-base", (690, 920, 800, 1060)),
                frame_hash="b",
            )
        )
        self.assertEqual(exit_command.target_identity, "campaign-exit-base")
        self.assertEqual(exit_command.tap_point, (745, 990))

    def test_defeat_continue_unwinds_without_selecting_stage_again(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home",
            )
        )
        defeat = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.RESULT,
                defeat_visible=True,
                tap_to_continue_visible=True,
                return_control_visible=True,
            ),
            ("campaign-defeat-return", DEFEAT_CONTINUE_ROI),
            frame_hash="defeat",
        )
        continue_command = self.controller.next_command(defeat)
        self.assertEqual(continue_command.action, CampaignAction.RETURN_HOME_AFTER_DEFEAT)
        self.assertEqual(continue_command.target_roi, DEFEAT_CONTINUE_ROI)
        self.controller.accept_dispatched(continue_command)

        chapter = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(9,),
                stage_navigation_available=True,
                ap_current=99,
            ),
            ("campaign-stage-1-20-9", (500, 600, 560, 660)),
            ("campaign-chapter-back", (670, 960, 800, 1095)),
            frame_hash="chapter-after-defeat",
        )
        unwind = self.controller.next_command(chapter)
        self.assertEqual(unwind.action, CampaignAction.LEAVE_CHAPTER_MAP)
        self.assertNotEqual(unwind.target_identity, "campaign-stage-1-20-9")

        dx0, dy0, dx1, dy1 = DEFEAT_CONTINUE_ROI
        bx0, by0, bx1, by1 = BUY_NOW_FORBIDDEN_ROI
        self.assertTrue(dx1 <= bx0 or bx1 <= dx0 or dy1 <= by0 or by1 <= dy0)

    def test_unbound_campaign_entry_requests_home_atlas_not_home_pan(self):
        self.assertTrue(HOME_PAN_GESTURES)
        with self.assertRaises(RuntimeError):
            home_pan_gestures_for_campaign_entry()
        home = recognized(
            CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
            frame_hash="home-unbound",
        )
        command = self.controller.next_command(home)
        self.assertEqual(command.action, CampaignAction.OPEN_CAMPAIGN)
        self.assertEqual(command.kind, "home_atlas_entry")
        self.assertEqual(command.target_identity, CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        self.assertIsNone(command.swipe)
        self.assertIn("HOME_PAN_GESTURES is fail-closed", command.reason)

    def test_unbound_chapter_requires_native_frame_for_atlas_navigation(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home",
            )
        )
        for frame_hash, visible in (
            ("tier-unbound", (3, 4, 5)),
            ("tier-empty", ()),
        ):
            blocked = self.controller.next_command(
                recognized(
                    CampaignRouteObservation(
                        screen=CampaignScreen.TIER_MAP,
                        selected_tier=1,
                        chapter_number=None,
                        visible_chapter_numbers=visible,
                        chapter_navigation_available=True,
                    ),
                    frame_hash=frame_hash,
                )
            )
            self.assertTrue(blocked.terminal)
            self.assertEqual(blocked.action, CampaignAction.BLOCKED)
            self.assertIn(
                "Campaign atlas chapter navigation requires the current native frame",
                blocked.reason,
            )

    def test_stage_pan_empty_visible_before_pan_fails_closed(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home-stage-empty-before",
            )
        )
        empty_before = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(),
                stage_navigation_available=True,
            ),
            frame_hash="chapter-empty-stages-before",
        )
        blocked = self.controller.next_command(empty_before)
        self.assertTrue(blocked.terminal)
        self.assertEqual(blocked.action, CampaignAction.BLOCKED)
        self.assertIsNone(blocked.swipe)
        self.assertIn("non-empty visible stage set before pan", blocked.reason)
        self.assertIsNone(self.controller._remembered_stage_visible)

    def test_residual_pan_swipe_rejects_empty_visible(self):
        with self.assertRaises(ValueError) as raised:
            residual_pan_swipe(
                20,
                (),
                toward_higher=CHAPTER_PAN_TOWARD_HIGHER,
                toward_lower=CHAPTER_PAN_TOWARD_LOWER,
            )
        self.assertIn("non-empty visible set", str(raised.exception))

    def test_stronger_residual_pan_helper_maps_known_geometries(self):
        from tasks.campaign_auto_battle_runtime import (
            CHAPTER_PAN_TOWARD_HIGHER_STRONG,
            stronger_residual_pan_swipe,
        )

        self.assertEqual(
            stronger_residual_pan_swipe(CHAPTER_PAN_TOWARD_HIGHER),
            CHAPTER_PAN_TOWARD_HIGHER_STRONG,
        )

    def test_stage_pan_uses_remembered_residual_and_fails_closed_on_no_progress(self):
        self.controller.next_command(
            recognized(
                CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, ap_current=99),
                ("campaign-entry", (1, 1, 2, 2)),
                frame_hash="home-stage",
            )
        )
        chapter = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(3, 4, 5),
                stage_navigation_available=True,
            ),
            ("campaign-stage-other", (100, 100, 200, 200)),
            frame_hash="chapter-low-stages",
        )
        first = self.controller.next_command(chapter)
        self.assertEqual(first.action, CampaignAction.NAVIGATE_STAGE)
        self.assertEqual(first.kind, "swipe")
        self.assertEqual(first.swipe, STAGE_PAN_TOWARD_HIGHER)
        self.controller.accept_dispatched(first)

        stalled = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(3, 4, 5),
                stage_navigation_available=True,
            ),
            frame_hash="chapter-stalled-stages",
        )
        blocked = self.controller.next_command(stalled)
        self.assertTrue(blocked.terminal)
        self.assertIn("no progress", blocked.reason)

        toward_lower = residual_pan_swipe(
            2,
            (15, 16, 17),
            toward_higher=STAGE_PAN_TOWARD_HIGHER,
            toward_lower=STAGE_PAN_TOWARD_LOWER,
        )
        self.assertEqual(toward_lower, STAGE_PAN_TOWARD_LOWER)

    def test_relocalization_residual_pixels_prefers_localization_then_displacement(self):
        from scripts.bluestacks_campaign_ap import relocalization_residual_pixels

        self.assertEqual(relocalization_residual_pixels(1.25, (30.0, 40.0)), 1.25)
        self.assertEqual(relocalization_residual_pixels(None, (30.0, 40.0)), 50.0)
        self.assertIsNone(relocalization_residual_pixels(None, None))

    def test_home_atlas_entry_delegates_to_verified_route_without_raw_transport(self):
        import json
        import tempfile

        from scripts import bluestacks_campaign_ap as campaign_ap

        class Runtime:
            input_count = 0

            def tap(self, *_args, **_kwargs):
                raise AssertionError("entry wrapper must not tap directly")

            def swipe(self, *_args, **_kwargs):
                raise AssertionError("entry wrapper must not swipe directly")

        calls = []

        def verified(runtime, **kwargs):
            calls.append((runtime, kwargs))
            runtime.input_count += 2
            return {"status": "opened", "tap_telemetry": {"dispatched": True}}

        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime()
            runtime.session = Path(directory)
            events = Path(directory) / "events.jsonl"
            with patch.object(campaign_ap, "run_verified_campaign_home_atlas_entry", side_effect=verified):
                result = campaign_ap._dispatch_home_atlas_campaign_entry(
                    runtime=runtime, events=events, maximum_pans=3, post_input_delay=0.0,
                )
            logged = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], runtime)
        self.assertIs(calls[0][1]["execute"], True)
        self.assertEqual(calls[0][1]["maximum_pans"], 3)
        self.assertIs(calls[0][1]["semantic_opened_check"], campaign_ap._campaign_entry_semantically_opened)
        self.assertEqual(result["status"], "opened")
        self.assertEqual(result["navigation_input_count"], 2)
        self.assertEqual([row["type"] for row in logged], ["home_atlas_entry_verified"])
        self.assertNotIn("tap_telemetry", logged[0])

    def test_campaign_entry_semantic_open_rejects_home_and_unknown(self):
        from unittest.mock import patch

        from scripts.bluestacks_campaign_ap import (
            _campaign_entry_semantically_opened,
            _CAMPAIGN_ENTRY_OPEN_SCREENS,
        )

        self.assertIn(CampaignScreen.TIER_MAP, _CAMPAIGN_ENTRY_OPEN_SCREENS)
        self.assertNotIn(CampaignScreen.HOME_BASE, _CAMPAIGN_ENTRY_OPEN_SCREENS)
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        unknown = CampaignFrameRecognition(
            CampaignRouteObservation(screen=CampaignScreen.UNKNOWN, recognized=False),
            "unknown",
            (),
            {},
        )
        with patch(
            "scripts.bluestacks_campaign_ap.recognize_campaign_frame",
            return_value=unknown,
        ):
            self.assertFalse(_campaign_entry_semantically_opened(blank))

        home_false_positive = CampaignFrameRecognition(
            CampaignRouteObservation(screen=CampaignScreen.HOME_BASE, recognized=True),
            "home-false-positive",
            (),
            {},
        )
        with patch(
            "scripts.bluestacks_campaign_ap.recognize_campaign_frame",
            return_value=home_false_positive,
        ):
            self.assertFalse(_campaign_entry_semantically_opened(blank))

        with patch(
            "scripts.bluestacks_campaign_ap.recognize_campaign_frame",
            return_value=unknown,
        ):
            self.assertFalse(_campaign_entry_semantically_opened(blank))

    def test_navigation_only_runtime_stops_before_challenge(self):
        controller = CampaignRuntimeController(
            CampaignAutoBattleConfig(
                target_stage=self.stage,
                ap_cost=16,
                ap_budget=16,
                max_runs=1,
                battle_poll_seconds=0.1,
                battle_timeout_seconds=180,
                navigation_only=True,
            ),
            initial_ap=99,
        )
        dialog = recognized(
            CampaignRouteObservation(
                screen=CampaignScreen.STAGE_DIALOG,
                stage_dialog=self.stage,
                ap_current=99,
                ap_cost=16,
                challenge_ready=True,
            ),
            ("campaign-challenge-1-20-9", (87, 863, 364, 956)),
            frame_hash="dialog-nav-only",
        )
        command = controller.next_command(dialog)
        self.assertEqual(command.action, CampaignAction.DESTINATION_VERIFIED)
        self.assertTrue(command.terminal)
        self.assertNotEqual(command.action, CampaignAction.CHALLENGE_STAGE)

        again = controller.next_command(
            recognized(
                CampaignRouteObservation(
                    screen=CampaignScreen.STAGE_DIALOG,
                    stage_dialog=self.stage,
                    ap_cost=16,
                ),
                frame_hash="dialog-nav-only-2",
            )
        )
        self.assertEqual(again.action, CampaignAction.NAVIGATION_ONLY_COMPLETE)


class CampaignVisionReplayTests(unittest.TestCase):
    capture = Path(
        ".local-captures/bluestacks/consume-ap-campaign/"
        "20260716T014118395232Z/frames"
    )

    def test_ap_fraction_rejects_current_above_maximum(self):
        self.assertEqual(_fraction("120/120"), (120, 120))
        self.assertIsNone(_fraction("720/120"))
        self.assertIsNone(_fraction("0/0"))

    def test_project_templates_exist_and_have_expected_shapes(self):
        assets = Path("tasks/assets/campaign_auto_battle/800x1280")
        expected = {
            "auto_disabled.png": (58, 62),
            "auto_enabled.png": (58, 62),
            "defeat_improve_might.png": (52, 260),
            "defeat_tap_to_continue.png": (58, 260),
            "lineup_challenge.png": (93, 276),
            "lose_word.png": (175, 510),
            "winner_word.png": (129, 652),
        }
        for name, shape in expected.items():
            image = cv2.imread(str(assets / name), cv2.IMREAD_COLOR)
            self.assertIsNotNone(image)
            self.assertEqual(image.shape[:2], shape)

    @requires_tesseract
    def test_committed_frames_recognize_tier_map_and_result(self):
        # Committed copies of consume-ap-campaign step-002-after / step-008-before
        # (provenance and sha256 in tests/fixtures/*/manifest.json).
        stage = CampaignStage.parse("1-3-1")
        fixtures = Path("tests/fixtures")
        cases = {
            fixtures / "campaign_tier_controls/retained-tier2-map.png": CampaignScreen.TIER_MAP,
            fixtures / "campaign_victory/retained-winner.png": CampaignScreen.RESULT,
        }
        for path, screen in cases.items():
            with self.subTest(name=path.name):
                self.assertEqual(read_campaign_frame(path, stage).observation.screen, screen)

    @requires_local_captures
    @requires_tesseract
    def test_retained_frames_recognize_full_battle_sequence(self):
        stage = CampaignStage.parse("1-3-1")
        cases = {
            "step-002-before.png": CampaignScreen.HOME_BASE,
            "step-002-after.png": CampaignScreen.TIER_MAP,
            "step-003-after.png": CampaignScreen.CHAPTER_MAP,
            "step-004-after.png": CampaignScreen.STAGE_DIALOG,
            "step-005-after.png": CampaignScreen.HERO_LINEUP,
            "step-006-after.png": CampaignScreen.BATTLE,
            "step-007-after.png": CampaignScreen.BATTLE,
            "step-008-before.png": CampaignScreen.RESULT,
        }
        for name, screen in cases.items():
            with self.subTest(name=name):
                path = require_capture(self.capture / name)
                self.assertEqual(read_campaign_frame(path, stage).observation.screen, screen)

        self.assertFalse(
            read_campaign_frame(
                require_capture(self.capture / "step-006-after.png"), stage
            ).observation.auto_enabled
        )
        self.assertTrue(
            read_campaign_frame(
                require_capture(self.capture / "step-007-after.png"), stage
            ).observation.auto_enabled
        )

    @requires_tesseract
    def test_user_defeat_frame_binds_only_bottom_continue(self):
        # Committed copy of the user-supplied 2026-07-16 defeat screenshot
        # (tests/fixtures/campaign_victory/manifest.json records its sha256).
        recognition = read_campaign_frame(
            Path("tests/fixtures/campaign_victory/retained-defeat.png"),
            CampaignStage.parse("1-20-9"),
        )
        self.assertEqual(recognition.observation.screen, CampaignScreen.RESULT)
        self.assertTrue(recognition.observation.defeat_visible)
        self.assertEqual(recognition.target("campaign-defeat-return"), DEFEAT_CONTINUE_ROI)


if __name__ == "__main__":
    unittest.main()
