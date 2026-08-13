from __future__ import annotations

from dataclasses import replace
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
from unittest.mock import patch
import unittest

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, IntegratedRouteResult, LocalBlueStacksRuntime
from scripts.navigation_development_boundary import NavigationBoundaryError
from scripts.noahs_tavern_recruit_bluestacks import NoahTavernIntegratedRoute
from scripts.nova_praise_bluestacks import NovaPraiseIntegratedRoute
from scripts.ruins_challenge_bluestacks import RuinsIntegratedRoute
from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_FREE_TARGET,
    NOAHS_TAVERN_SCREEN,
    NoahTavernObservation,
    NoahTierObservation,
    RecruitTier,
    TIER_ATTEMPT_MAXIMUMS,
    parse_cooldown_seconds,
)
from tasks.nova_praise import NOVA_HOME, NOVA_LAB_MENU, NOVA_PRAISE_TARGET, NOVA_SCREEN, NovaPraiseObservation
from tasks.nova_praise_vision import NOVA_MENU_ROI, NOVA_PRAISE_ROI, RESEARCH_LAB_ROI, NovaFrameRecognition
from tasks.ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsDetailObservation,
    RuinsResult,
    RuinsResultObservation,
    RuinsScreenObservation,
)
from tasks.ruins_challenge_vision import RuinsDetailRecognition, RuinsFrameRecognition, RuinsResultRecognition, RuinsRewardRecognition


RESET = "integration-reset"


class FakeRuntime:
    def __init__(self, count: int = 20):
        self.execute = True
        self.in_flight_action = None
        self.session = Path("fake-session")
        self.frames = []
        for ordinal in range(count):
            frame = np.full((1280, 800, 3), ordinal, dtype=np.uint8)
            self.frames.append(CapturedNativeFrame(frame, b"png", f"{ordinal:064x}", time.monotonic(), Path(f"{ordinal}.png")))
        self.index = 0
        self.taps = []
        self.swipes = []
        self.backs = []
        self.reconciliations = []

    def capture(self, label):
        frame = self.frames[self.index]
        self.index += 1
        return frame

    def tap(self, source, **kwargs):
        if kwargs.get("consequential"):
            self.in_flight_action = kwargs["action_key"]
        continuation = kwargs.get("continuation_of")
        if continuation is not None:
            self.assert_in_flight(continuation)
        self.taps.append((source.sha256, kwargs))

    def back(self, source, **kwargs):
        continuation = kwargs.get("continuation_of")
        if continuation is not None:
            self.assert_in_flight(continuation)
        self.backs.append((source.sha256, kwargs))

    def swipe(self, source, **kwargs):
        self.swipes.append((source.sha256, kwargs))

    def assert_in_flight(self, action_key):
        if self.in_flight_action != action_key:
            raise RuntimeError("continuation mismatch")

    def measure_device_state(self):
        return "device"

    def measure_foreground_package(self):
        return "com.global.ztmslg"

    def reconcile(self, action_key, status, post, reason):
        self.assert_in_flight(action_key)
        self.reconciliations.append((action_key, status, post.sha256, reason))
        if status != "unresolved":
            self.in_flight_action = None


class FakeADBRunner:
    def __init__(self):
        ok, encoded = cv2.imencode(".png", np.zeros((1280, 800, 3), dtype=np.uint8))
        if not ok:
            raise RuntimeError("test PNG encoding failed")
        self.png = encoded.tobytes()
        self.taps = []
        self.swipes = []
        self.backs = 0

    def capture_png(self):
        return self.png

    def dispatch_tap(self, point):
        self.taps.append(point)

    def dispatch_swipe(self, start, end, *, duration_ms=400):
        self.swipes.append((start, end, duration_ms))

    def dispatch_back(self):
        self.backs += 1


def noah_tier(tier, remaining, *, enabled=False, cooldown=False):
    cooldown_text = "Free in 00:09:52" if cooldown else ""
    return NoahTierObservation(
        tier=tier,
        daily_attempt_maximum=TIER_ATTEMPT_MAXIMUMS[tier],
        attempts_remaining=remaining,
        cooldown_text=cooldown_text,
        cooldown_duration_seconds=parse_cooldown_seconds(cooldown_text),
        cooldown_active=cooldown,
        next_eligible_timestamp=700.0 if cooldown else None,
        free_control_visible=True,
        free_control_enabled=enabled,
        target_roi=(90, 925, 385, 1055),
        panel_roi=(40, 840, 760, 1070),
        target_identity=NOAHS_TAVERN_FREE_TARGET,
        control_class=NOAHS_TAVERN_FREE_TARGET,
        cost_type="none",
        cost_amount=0,
        quantity=1,
        recognized=True,
    )


def noah_observation(state, digest, *, remaining=5, cooldown=False):
    tiers = tuple(
        noah_tier(tier, remaining if tier == RecruitTier.BASIC else 0, enabled=tier == RecruitTier.BASIC and not cooldown, cooldown=tier == RecruitTier.BASIC and cooldown)
        for tier in RecruitTier
    )
    return NoahTavernObservation(
        state,
        RecruitTier.BASIC if state == NOAHS_TAVERN_SCREEN else None,
        tiers,
        digest,
        captured_monotonic=1.0,
        recognized=True,
        home_tavern_target_roi=(20, 700, 200, 900) if state == HOME_BASE_SCREEN else None,
    )


class IntegratedRouteTests(unittest.TestCase):
    def test_ruins_chest_claim_is_ordinary_gameplay_not_consequential(self):
        runtime = FakeRuntime()
        runtime.reconcile = lambda *args: runtime.reconciliations.append(args)
        row = RuinsChallengeRow(
            "Hero Challenge", "Mon", RuinsAvailability.AVAILABLE, 60, 120, 60,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.AVAILABLE,
            (600, 250, 770, 390), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 14951,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(
            listed, "a" * 64, (("chest:Hero Challenge", (600, 250, 770, 390)),), {},
        )
        claimed = replace(
            listed,
            rows=(replace(row, chest_state=RuinsChestState.CLAIMED, source_frame_sha256="b" * 64),),
            source_frame_sha256="b" * 64,
        )
        post_recognition = RuinsFrameRecognition(claimed, "b" * 64, (), {})
        reward = RuinsRewardRecognition(
            True, "Hero Challenge", 100, "c" * 64, RESET,
            (("ruins-reward-claim", (250, 900, 550, 1040)),), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Mon", post_input_delay=0)
        route.controller.observe_list(listed)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_reward_frame", return_value=reward), patch.object(
            route, "_observe_list", return_value=(runtime.frames[1], post_recognition),
        ):
            status, _reason, _captured, _recognition = route._claim_one_chest(runtime.frames[0], recognition)
        self.assertEqual(status, "claimed")
        self.assertEqual(
            [item[1]["target_identity"] for item in runtime.taps],
            ["chest:Hero Challenge", "ruins-reward-claim"],
        )
        self.assertFalse(any(item[1].get("consequential") for item in runtime.taps))
        self.assertIsNone(runtime.in_flight_action)

        overlap = RuinsFrameRecognition(
            replace(listed, source_frame_sha256="d" * 64),
            "d" * 64,
            (("chest:Hero Challenge", (600, 250, 770, 390)),),
            {},
        )
        status, reason, _captured, _recognition = route._claim_one_chest(runtime.frames[3], overlap)
        self.assertEqual((status, reason), ("none", "no_available_chest"))
        self.assertEqual(len(runtime.taps), 2)

    def test_ruins_chest_missing_medal_delta_reconciles_unresolved_only(self):
        runtime = FakeRuntime()
        runtime.reconcile = lambda *args: runtime.reconciliations.append(args)
        row = RuinsChallengeRow(
            "Hero Challenge", "Mon", RuinsAvailability.AVAILABLE, 60, 120, 60,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.AVAILABLE,
            (600, 250, 770, 390), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(listed, "a" * 64, (("chest:Hero Challenge", (600, 250, 770, 390)),), {})
        after = replace(
            listed,
            rows=(replace(row, chest_state=RuinsChestState.UNKNOWN, source_frame_sha256="b" * 64),),
            source_frame_sha256="b" * 64,
        )
        post = RuinsFrameRecognition(after, "b" * 64, (), {})
        reward = RuinsRewardRecognition(True, "Hero Challenge", 432, "c" * 64, RESET, (("ruins-reward-claim", (250, 900, 550, 1040)),), {})
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Mon", post_input_delay=0)
        route.controller.observe_list(listed)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_reward_frame", return_value=reward), patch.object(
            route, "_observe_list", return_value=(runtime.frames[1], post),
        ):
            status, reason, _captured, _recognition = route._claim_one_chest(runtime.frames[0], recognition)
        self.assertEqual((status, reason), ("unresolved", "chest_medal_delta_not_proven"))
        self.assertEqual([item[1] for item in runtime.reconciliations], ["unresolved"])

    def test_ruins_chest_row_ocr_miss_reconciles_from_target_absence_and_medal_delta(self):
        runtime = FakeRuntime()
        runtime.reconcile = lambda *args: runtime.reconciliations.append(args)
        row = RuinsChallengeRow(
            "Glory Challenge", "Fri", RuinsAvailability.AVAILABLE, 57, 130, 57,
            RuinsControlState.HIDDEN, RuinsChestState.AVAILABLE,
            (18, 505, 780, 695), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 14958,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(
            listed, "a" * 64, (("chest:Glory Challenge", (600, 510, 780, 655)),), {},
        )
        post_observation = replace(
            listed,
            points_balance=15366,
            rows=(),
            source_frame_sha256="b" * 64,
        )
        post = RuinsFrameRecognition(post_observation, "b" * 64, (), {})
        reward = RuinsRewardRecognition(
            True, "Glory Challenge", 408, "c" * 64, RESET,
            (("ruins-reward-claim", (255, 681, 545, 786)),), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Fri", post_input_delay=0)
        route.controller.observe_list(listed)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_reward_frame", return_value=reward), patch.object(
            route, "_observe_list", return_value=(runtime.frames[1], post),
        ):
            status, reason, _captured, _recognition = route._claim_one_chest(runtime.frames[0], recognition)
        self.assertEqual((status, reason), ("claimed", "Glory Challenge"))
        self.assertEqual([item[1] for item in runtime.reconciliations], ["confirmed"])
        self.assertEqual(route.resource_delta, 408)
        self.assertEqual(route.chest_coverage["Glory Challenge"], "newly claimed")
        self.assertEqual(route.newly_claimed_chests, [{"identity": "Glory Challenge", "ruins_medals": 408}])

    def test_ruins_chest_row_ocr_miss_requires_matching_positive_modal_delta(self):
        row = RuinsChallengeRow(
            "Glory Challenge", "Fri", RuinsAvailability.AVAILABLE, 57, 130, 57,
            RuinsControlState.HIDDEN, RuinsChestState.AVAILABLE,
            (18, 505, 780, 695), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 14958,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(
            listed, "a" * 64, (("chest:Glory Challenge", (600, 510, 780, 655)),), {},
        )
        for points_after, modal_amount in ((14958, 408), (15366, 400)):
            with self.subTest(points_after=points_after, modal_amount=modal_amount):
                runtime = FakeRuntime()
                runtime.reconcile = lambda *args: runtime.reconciliations.append(args)
                post_observation = replace(
                    listed, points_balance=points_after, rows=(), source_frame_sha256="b" * 64,
                )
                post = RuinsFrameRecognition(post_observation, "b" * 64, (), {})
                reward = RuinsRewardRecognition(
                    True, "Glory Challenge", modal_amount, "c" * 64, RESET,
                    (("ruins-reward-claim", (255, 681, 545, 786)),), {},
                )
                route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Fri", post_input_delay=0)
                route.controller.observe_list(listed)
                with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_reward_frame", return_value=reward), patch.object(
                    route, "_observe_list", return_value=(runtime.frames[1], post),
                ):
                    status, reason, _captured, _recognition = route._claim_one_chest(
                        runtime.frames[0], recognition,
                    )
                self.assertEqual((status, reason), ("unresolved", "chest_reward_delta_mismatch"))
                self.assertEqual([item[1] for item in runtime.reconciliations], ["unresolved"])
                self.assertEqual(route.chest_coverage["Glory Challenge"], "unresolved")

    def test_ruins_chests_only_returns_home_without_selecting_challenge(self):
        runtime = FakeRuntime()
        hero = RuinsChallengeRow(
            "Hero Challenge", "Mon", RuinsAvailability.UNAVAILABLE, 60, 120, 60,
            RuinsControlState.HIDDEN, RuinsChestState.UNKNOWN,
            (18, 230, 780, 420), source_frame_sha256="0" * 64, reset_identity=RESET,
        )
        row = RuinsChallengeRow(
            "Gear Challenge", "Tue", RuinsAvailability.AVAILABLE, 67, 190, 67,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (18, 830, 780, 1020), source_frame_sha256="0" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 14951,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (hero, row), "none", "0" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(listed, "0" * 64, (), {})
        expected = IntegratedRouteResult("completed", "verified_safe_exit_to_home", 0, "fake-session")
        route = RuinsIntegratedRoute(
            runtime, reset_identity=RESET, current_day="Tue", chests_only=True, post_input_delay=0,
        )
        route.chest_coverage = {identity: "already claimed" for identity in KNOWN_CHALLENGE_IDENTITIES}
        with patch.object(route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame", return_value=recognition,
        ), patch.object(route, "_claim_one_chest", return_value=("none", "no_available_chest", runtime.frames[0], recognition)), patch.object(
            route, "_choose_challenge", side_effect=AssertionError("chests-only must not select combat"),
        ), patch.object(route, "_return_home", return_value=expected) as return_home:
            outcome = route.run()
        self.assertEqual(outcome, expected)
        return_home.assert_called_once()

    def test_ruins_chests_only_continues_open_reward_without_combat(self):
        runtime = FakeRuntime()
        hero = RuinsChallengeRow(
            "Hero Challenge", "Mon", RuinsAvailability.UNAVAILABLE, 60, 120, 60,
            RuinsControlState.HIDDEN, RuinsChestState.UNKNOWN,
            (18, 230, 780, 420), source_frame_sha256="1" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 15451,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (hero,), "none", "1" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        recognition = RuinsFrameRecognition(listed, "1" * 64, (), {})
        reward = RuinsRewardRecognition(
            True, "Hero Challenge", 432, "0" * 64, RESET,
            (("ruins-reward-claim", (255, 681, 545, 794)),), {},
        )
        expected = IntegratedRouteResult("completed", "verified_safe_exit_to_home", 1, "fake-session")
        route = RuinsIntegratedRoute(
            runtime, reset_identity=RESET, current_day="Tue", chests_only=True, post_input_delay=0,
        )
        route.chest_coverage = {identity: "already claimed" for identity in KNOWN_CHALLENGE_IDENTITIES}
        with patch("scripts.ruins_challenge_bluestacks.recognize_any_ruins_reward_frame", return_value=reward), patch.object(
            route, "_observe_list", return_value=(runtime.frames[1], recognition),
        ), patch.object(route, "_recover_known_chat_to_home", side_effect=lambda source: (source, None, 0)), patch.object(
            route, "_dismiss_known_vip_popup", side_effect=lambda source: (source, None, 0),
        ), patch.object(route, "_claim_one_chest", return_value=("none", "no_available_chest", runtime.frames[1], recognition)), patch.object(
            route, "_choose_challenge", side_effect=AssertionError("reward continuation must not select combat"),
        ), patch.object(route, "_return_home", return_value=expected):
            outcome = route.run()
        self.assertEqual(outcome, expected)
        self.assertEqual([item[1]["target_identity"] for item in runtime.taps], ["ruins-reward-claim"])
        self.assertFalse(runtime.taps[0][1].get("consequential"))
        self.assertEqual(route.resource_delta, 432)
        self.assertEqual(route.chest_coverage["Hero Challenge"], "newly claimed")
        self.assertEqual(route.newly_claimed_chests, [{"identity": "Hero Challenge", "ruins_medals": 432}])

    def test_ruins_chests_only_scrolls_until_every_canonical_identity_is_audited(self):
        runtime = FakeRuntime()

        def row(identity, top, *, locked=False, challenge=False):
            return RuinsChallengeRow(
                identity,
                None,
                RuinsAvailability.LOCKED if locked else RuinsAvailability.AVAILABLE if challenge else RuinsAvailability.UNAVAILABLE,
                1,
                100,
                None,
                RuinsControlState.VISIBLE_ENABLED if challenge else RuinsControlState.HIDDEN,
                RuinsChestState.UNKNOWN,
                (18, top, 780, top + 190),
                source_frame_sha256="a" * 64,
                reset_identity=RESET,
            )

        identities = [
            "Hero Challenge",
            "Weapon Trial",
            "Tech Challenge",
            "Gear Challenge",
            "Core Challenge",
            "Nova Challenge",
            "Module Challenge",
            "Glory Challenge",
            "Bioenhancer Challenge",
            "Ultimate Challenge",
            "Chip Challenge",
            "Cube Challenge",
        ]
        pages = []
        for ordinal, page_ids in enumerate((identities[:5], identities[4:9], identities[8:])):
            rows = tuple(
                row(identity, 230 + index * 190, locked=identity == "Core Challenge", challenge=identity == "Gear Challenge")
                for index, identity in enumerate(page_ids)
            )
            observation = RuinsScreenObservation(
                True,
                "RUINS_CHALLENGE",
                True,
                15712,
                RuinsControlState.VISIBLE_ENABLED,
                RuinsControlState.VISIBLE_ENABLED,
                RuinsControlState.VISIBLE_ENABLED,
                rows,
                "none",
                f"{ordinal + 1:064x}",
                RESET,
                safe_back_control=RuinsControlState.VISIBLE_ENABLED,
            )
            pages.append(RuinsFrameRecognition(observation, observation.source_frame_sha256, (), {}))

        expected = IntegratedRouteResult("completed", "verified_safe_exit_to_home", 2, "fake-session")
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Thu", chests_only=True, post_input_delay=0)
        scrolled_pages = iter((pages[1], pages[2]))

        def scroll(captured, recognition, *, ordinal):
            page = next(scrolled_pages)
            return "scrolled", "ruins_list_scroll_progress", runtime.frames[ordinal], page

        with patch.object(route, "_recover_known_chat_to_home", side_effect=lambda source: (source, None, 0)), patch.object(
            route, "_dismiss_known_vip_popup", side_effect=lambda source: (source, None, 0),
        ), patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", return_value=pages[0]), patch.object(
            route, "_scroll_chest_list", side_effect=scroll,
        ), patch.object(route, "_choose_challenge", side_effect=AssertionError("chests-only must not select combat")), patch.object(
            route, "_return_home", return_value=expected,
        ):
            outcome = route.run()

        self.assertEqual(outcome, expected)
        self.assertEqual(set(route.chest_coverage), set(identities))
        self.assertNotIn("unresolved", route.chest_coverage.values())
        self.assertEqual(route.chest_coverage["Core Challenge"], "locked")
        self.assertEqual(route.chest_coverage["Gear Challenge"], "unavailable/no reward")
        self.assertEqual(route.chest_coverage["Hero Challenge"], "already claimed")

    def test_ruins_chest_scroll_uses_current_list_frame_and_requires_semantic_progress(self):
        runtime = FakeRuntime()
        first = RuinsChallengeRow(
            "Hero Challenge", None, RuinsAvailability.UNAVAILABLE, 60, 120, None,
            RuinsControlState.HIDDEN, RuinsChestState.UNKNOWN, (18, 230, 780, 420),
            source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        second = replace(first, identity="Nova Challenge", target_roi=(18, 300, 780, 490), source_frame_sha256="b" * 64)
        before = RuinsFrameRecognition(
            RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 15712, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (first,), "none", "a" * 64, RESET, safe_back_control=RuinsControlState.VISIBLE_ENABLED),
            "a" * 64, (), {},
        )
        after = RuinsFrameRecognition(
            replace(before.observation, rows=(second,), source_frame_sha256="b" * 64),
            "b" * 64, (), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Thu", chests_only=True, post_input_delay=0)
        with patch.object(route, "_observe_list", return_value=(runtime.frames[1], after)):
            status, reason, _captured, _recognition = route._scroll_chest_list(runtime.frames[0], before, ordinal=1)
        self.assertEqual((status, reason), ("scrolled", "ruins_list_scroll_progress"))
        self.assertEqual(runtime.swipes[0][1]["target_identity"], "ruins-list-scroll")
        self.assertEqual(runtime.swipes[0][1]["start"][0], 400)
        self.assertLess(runtime.swipes[0][1]["end"][1], runtime.swipes[0][1]["start"][1])

        stalled_runtime = FakeRuntime()
        stalled_route = RuinsIntegratedRoute(stalled_runtime, reset_identity=RESET, current_day="Thu", chests_only=True, post_input_delay=0)
        with patch.object(stalled_route, "_observe_list", return_value=(stalled_runtime.frames[1], before)):
            status, reason, _captured, _recognition = stalled_route._scroll_chest_list(
                stalled_runtime.frames[0], before, ordinal=1,
            )
        self.assertEqual((status, reason), ("blocked", "ruins_list_scroll_no_semantic_progress"))

    def test_ruins_chest_mid_list_continuation_restores_canonical_top(self):
        runtime = FakeRuntime()
        glory = RuinsChallengeRow(
            "Glory Challenge", "Fri", RuinsAvailability.UNAVAILABLE, 57, 130, 57,
            RuinsControlState.HIDDEN, RuinsChestState.UNKNOWN, (18, 505, 780, 695),
            source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        hero = replace(
            glory,
            identity="Hero Challenge",
            day_label="Mon",
            target_roi=(18, 230, 780, 420),
            source_frame_sha256="c" * 64,
        )
        nova = replace(
            glory,
            identity="Nova Challenge",
            day_label="Thu",
            availability=RuinsAvailability.AVAILABLE,
            challenge_control=RuinsControlState.VISIBLE_ENABLED,
            target_roi=(18, 938, 780, 1128),
            source_frame_sha256="b" * 64,
        )
        before = RuinsFrameRecognition(
            RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 15366, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (glory,), "none", "a" * 64, RESET, safe_back_control=RuinsControlState.VISIBLE_ENABLED),
            "a" * 64, (), {},
        )
        intermediate = RuinsFrameRecognition(
            replace(before.observation, rows=(nova,), source_frame_sha256="b" * 64),
            "b" * 64, (), {},
        )
        after = RuinsFrameRecognition(
            replace(before.observation, rows=(hero,), source_frame_sha256="c" * 64),
            "c" * 64, (), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Fri", chests_only=True, post_input_delay=0)
        with patch.object(route, "_observe_list", side_effect=((runtime.frames[1], intermediate), (runtime.frames[2], after))):
            status, reason, _captured, recognition, actions = route._restore_chest_list_top(
                runtime.frames[0], before,
            )
        self.assertEqual((status, reason, actions), ("restored", "ruins_chest_list_top_restored", 2))
        self.assertIsNotNone(recognition.observation.row("Hero Challenge"))
        self.assertEqual(route.chest_coverage["Nova Challenge"], "unavailable/no reward")
        self.assertEqual(len(runtime.swipes), 2)
        self.assertEqual(runtime.swipes[0][1]["start"], (400, 400))
        self.assertEqual(runtime.swipes[0][1]["end"], (400, 1100))

    def test_ruins_known_vip_popup_closes_once_and_requires_absent_successor(self):
        runtime = FakeRuntime()
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Tue", post_input_delay=0)
        detail = {"recognized": True, "target": (260, 760, 540, 870)}
        with patch("scripts.ruins_challenge_bluestacks.recognize_reset_popup", side_effect=(detail, {"recognized": False})):
            settled, reason, actions = route._dismiss_known_vip_popup(runtime.frames[0])
        self.assertIsNotNone(settled)
        self.assertIsNone(reason)
        self.assertEqual(actions, 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0][1]["target_identity"], "reset-popup-close")

    def test_ruins_unknown_popup_is_not_dismissed_and_gameplay_allowlist_rejects_controls(self):
        runtime = FakeRuntime()
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Tue", post_input_delay=0)
        with patch("scripts.ruins_challenge_bluestacks.recognize_reset_popup", return_value={"recognized": False}):
            _settled, reason, actions = route._dismiss_known_vip_popup(runtime.frames[0])
        self.assertIsNone(reason)
        self.assertEqual(actions, 0)
        self.assertEqual(runtime.taps, [])
        for target in ("exchange", "purchase", "unknown-control"):
            with self.assertRaisesRegex(NavigationBoundaryError, "undeclared Ruins gameplay target"):
                route._ordinary_tap(runtime.frames[0], target_identity=target, target_roi=(10, 10, 20, 20), action_key=f"reject:{target}")

    def test_native_runtime_allows_multiple_ordinary_actions_without_reconcile(self):
        with TemporaryDirectory() as directory:
            runner = FakeADBRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "session", execute=True)
            source = runtime.capture("source")
            runtime.tap(
                source,
                target_identity="free-action",
                target_roi=(100, 100, 200, 200),
                action_key="action-1",
                consequential=True,
            )
            runtime.back(source, action_key="back-without-reconcile")
            post = runtime.capture("post")
            runtime.reconcile("action-1", "confirmed", post, "verified")
            self.assertEqual(runner.taps, [(150, 150)])
            self.assertEqual(runner.backs, 1)

    def test_native_runtime_rejects_stale_and_dry_run_input(self):
        with TemporaryDirectory() as directory:
            runner = FakeADBRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "session", execute=True)
            stale = replace(runtime.capture("stale"), captured_monotonic=-1.0)
            with self.assertRaisesRegex(RuntimeError, "stale"):
                runtime.tap(stale, target_identity="target", target_roi=(1, 1, 2, 2), action_key="stale")
        with TemporaryDirectory() as directory:
            runner = FakeADBRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "session", execute=False)
            source = runtime.capture("dry")
            with self.assertRaisesRegex(RuntimeError, "dry-run"):
                runtime.tap(source, target_identity="target", target_roi=(1, 1, 2, 2), action_key="dry")
            self.assertEqual(runner.taps, [])

    def test_native_runtime_long_press_is_one_bounded_zero_distance_swipe(self):
        with TemporaryDirectory() as directory:
            runner = FakeADBRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "session", execute=True)
            source = runtime.capture("hold-source")
            runtime.long_press(
                source,
                target_identity="supply-depot-free-food",
                target_roi=(100, 100, 200, 200),
                duration_ms=4000,
                action_key="hold-action-1",
                consequential=True,
            )
            self.assertEqual(runner.swipes, [((150, 150), (150, 150), 4000)])
            runtime.back(source, action_key="back-before-hold-reconcile")
            post = runtime.capture("hold-post")
            runtime.reconcile("hold-action-1", "confirmed", post, "hold verified")
            self.assertEqual(runner.backs, 1)

    def test_noah_route_uses_controller_transport_result_and_home_postcondition(self):
        runtime = FakeRuntime()
        home = noah_observation(HOME_BASE_SCREEN, "a" * 64)
        before = noah_observation(NOAHS_TAVERN_SCREEN, "b" * 64, remaining=5)
        result = replace(
            noah_observation(HERO_RECRUIT_RESULT_SCREEN, "c" * 64),
            result_tier=RecruitTier.BASIC,
            result_identity="hero frag",
            safe_close_visible=True,
            safe_close_roi=(90, 975, 350, 1100),
        )
        # The live Tavern hides Daily free attempts while the cooldown is active.
        after = noah_observation(NOAHS_TAVERN_SCREEN, "d" * 64, remaining=None, cooldown=True)
        # Safe exit performs a fresh Tavern immediate-before revalidation.
        observations = iter((home, before, result, result, after, after, home))

        def recognize(_frame, **_kwargs):
            return next(observations)

        bound_rois = []
        route = NoahTavernIntegratedRoute(
            runtime,
            max_recruits=1,
            recognizer=recognize,
            post_input_delay=0,
            result_timeout=1,
            atlas_binding=lambda captured: (bound_rois.append(captured.sha256) or (10, 10, 20, 20)),
        )
        outcome = route.run()
        self.assertEqual(outcome.status, "completed", outcome.reason)
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(runtime.reconciliations, [])
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 0)
        self.assertEqual(runtime.taps[0][1]["target_roi"], (10, 10, 20, 20))
        self.assertEqual(bound_rois, [runtime.frames[0].sha256])
        self.assertTrue(runtime.backs)

    def test_nova_route_cannot_bypass_centralized_action_boundary(self):
        runtime = FakeRuntime()
        base = dict(
            research_lab_identity=True,
            praise_target_roi=NOVA_PRAISE_ROI,
            frame_sha256="a" * 64,
            captured_monotonic=1.0,
            recognized=True,
        )
        home_obs = NovaPraiseObservation(NOVA_HOME, **base, nova_control_visible=False, selected_nova=False, praise_enabled=False, praise_target_identity="", attempts_remaining=None)
        lab_obs = replace(home_obs, screen_state=NOVA_LAB_MENU, nova_control_visible=True)
        before = replace(home_obs, screen_state=NOVA_SCREEN, selected_nova=True, praise_enabled=True, praise_target_identity=NOVA_PRAISE_TARGET, attempts_remaining=7)
        after = replace(before, praise_enabled=False, attempts_remaining=6, cooldown_active=True, cooldown_seconds=30, next_eligible_at=34.0, frame_sha256="b" * 64, captured_monotonic=4.0)
        recognitions = iter((
            NovaFrameRecognition(home_obs, "a" * 64, (("research-lab-building", RESEARCH_LAB_ROI),), {}),
            NovaFrameRecognition(lab_obs, "b" * 64, (("research-lab-nova", NOVA_MENU_ROI),), {}),
            NovaFrameRecognition(before, "c" * 64, ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),), {}),
            NovaFrameRecognition(after, "d" * 64, (), {}),
            NovaFrameRecognition(lab_obs, "e" * 64, (("research-lab-nova", NOVA_MENU_ROI),), {}),
            NovaFrameRecognition(home_obs, "f" * 64, (("research-lab-building", RESEARCH_LAB_ROI),), {}),
        ))
        route = NovaPraiseIntegratedRoute(runtime, recognizer=lambda *_args, **_kwargs: next(recognitions), post_input_delay=0, postcondition_timeout=1)
        outcome = route.run()
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(outcome.reason, "centralized_action_boundary_required")
        self.assertEqual(outcome.actions_completed, 0)
        self.assertEqual(runtime.reconciliations, [])
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 0)

    def test_ruins_route_executes_controller_chain_and_reconciles_failure(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1080), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        home_obs = RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, (), "none", "a" * 64, RESET, True, True)
        list_obs = RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 100, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (row,), "none", "b" * 64, RESET, safe_back_control=RuinsControlState.VISIBLE_ENABLED)
        home_rec = RuinsFrameRecognition(home_obs, "a" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        list_rec = RuinsFrameRecognition(list_obs, "b" * 64, (("challenge:Nova Challenge", (560, 900, 780, 1080)),), {})
        post_list_rec = RuinsFrameRecognition(replace(list_obs, source_frame_sha256="f" * 64), "f" * 64, (), {})
        safe_before = RuinsFrameRecognition(replace(list_obs, source_frame_sha256="g" * 64), "g" * 64, (), {})
        final_home = RuinsFrameRecognition(replace(home_obs, source_frame_sha256="1" * 64), "1" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        detail_obs = RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="c" * 64, reset_identity=RESET)
        dispatch_obs = RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="d" * 64, reset_identity=RESET)
        result_obs = RuinsResultObservation("Nova Challenge", RuinsResult.FAILURE, None, None, None, "e" * 64, RESET, False, True, True)
        list_queue = iter((home_rec, home_rec, list_rec, post_list_rec, safe_before, final_home))
        detail_queue = iter((
            RuinsDetailRecognition(detail_obs, "c" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {}),
            RuinsDetailRecognition(dispatch_obs, "d" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {}),
        ))
        result_rec = RuinsResultRecognition(result_obs, "e" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {})
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", side_effect=lambda *_args, **_kwargs: next(list_queue)), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets", side_effect=lambda *_args, **_kwargs: next(detail_queue)
        ), patch("scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets", return_value=result_rec):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            with patch.object(route, "_recover_home_zoom_before_ruins_binding", return_value=(runtime.frames[0], None)), patch.object(
                route, "_current_frame_ruins_binding", return_value=(50, 800, 220, 1030)
            ):
                outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(runtime.reconciliations[0][1], "failed_confirmed")
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 1)
        self.assertTrue(runtime.backs)

    def test_ruins_success_detail_successor_advances_same_identity_then_backs_to_list(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1080), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "b" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        list_rec = RuinsFrameRecognition(listed, "b" * 64, (("challenge:Nova Challenge", row.target_roi),), {})
        advanced_list = RuinsFrameRecognition(
            replace(listed, rows=(replace(row, progress_current=19, source_frame_sha256="3" * 64),), source_frame_sha256="3" * 64),
            "3" * 64, (), {},
        )
        post_detail_rec = RuinsFrameRecognition(
            RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN,
                                   RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "d" * 64, RESET),
            "d" * 64, (), {},
        )
        attack = RuinsDetailRecognition(
            RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED,
                                   source_frame_sha256="e" * 64, reset_identity=RESET),
            "e" * 64, (("ruins-attack", (255, 1146, 545, 1251)),), {},
        )
        dispatch = RuinsDetailRecognition(
            RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN,
                                   RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0,
                                   source_frame_sha256="f" * 64, reset_identity=RESET),
            "f" * 64, (("ruins-dispatch", (255, 1140, 545, 1245)),), {},
        )
        successor = RuinsDetailRecognition(
            RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED,
                                   source_frame_sha256="1" * 64, reset_identity=RESET),
            "1" * 64, (), {},
        )
        unknown_detail = RuinsDetailRecognition(
            RuinsDetailObservation("unknown", False, 0, 0, RuinsControlState.HIDDEN,
                                   source_frame_sha256="0" * 64, reset_identity=RESET),
            "0" * 64, (), {},
        )
        details = iter((attack, dispatch, successor, successor, successor))
        result_rec = RuinsResultRecognition(
            RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, None, None, None,
                                   "2" * 64, RESET, True, False, True),
            "2" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {},
        )
        with patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
            side_effect=lambda _frame, identity, **_kwargs: next(details) if identity == "Nova Challenge" else unknown_detail,
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets",
            return_value=result_rec,
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
            side_effect=(post_detail_rec, advanced_list),
        ):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            route.controller.observe_list(list_rec.observation)
            outcome = route._run_challenge(runtime.frames[0], list_rec, row)
        self.assertIsInstance(outcome, tuple)
        _captured, _recognition, result = outcome
        self.assertEqual(result, RuinsResult.SUCCESS)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual(len(runtime.backs), 1)
        self.assertEqual(runtime.backs[0][1]["action_key"].split(":")[1], "detail-safe-exit")

    def test_ruins_success_detail_successor_rejects_same_decreased_wrong_and_ambiguous(self):
        variants = (
            ("same", RuinsDetailObservation("Nova Challenge", True, 18, 100, RuinsControlState.VISIBLE_ENABLED, reset_identity=RESET)),
            ("decreased", RuinsDetailObservation("Nova Challenge", True, 17, 100, RuinsControlState.VISIBLE_ENABLED, reset_identity=RESET)),
            ("wrong_identity", RuinsDetailObservation("Gear Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, reset_identity=RESET)),
            ("ambiguous", RuinsDetailObservation("Nova Challenge", False, 19, 100, RuinsControlState.HIDDEN, reset_identity=RESET)),
        )
        for label, successor_observation in variants:
            with self.subTest(label=label):
                runtime = FakeRuntime()
                row = RuinsChallengeRow(
                    "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
                    RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
                    (560, 900, 780, 1080), source_frame_sha256="b" * 64, reset_identity=RESET,
                )
                listed = RuinsScreenObservation(
                    True, "RUINS_CHALLENGE", True, 100,
                    RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
                    RuinsControlState.VISIBLE_ENABLED, (row,), "none", "b" * 64, RESET,
                    safe_back_control=RuinsControlState.VISIBLE_ENABLED,
                )
                list_rec = RuinsFrameRecognition(listed, "b" * 64, (("challenge:Nova Challenge", row.target_roi),), {})
                post_detail_rec = RuinsFrameRecognition(
                    RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN,
                                           RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "d" * 64, RESET),
                    "d" * 64, (), {},
                )
                attack = RuinsDetailRecognition(
                    RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, reset_identity=RESET),
                    "e" * 64, (("ruins-attack", (255, 1146, 545, 1251)),), {},
                )
                dispatch = RuinsDetailRecognition(
                    RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN,
                                           RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, reset_identity=RESET),
                    "f" * 64, (("ruins-dispatch", (255, 1140, 545, 1245)),), {},
                )
                successor = RuinsDetailRecognition(successor_observation, "1" * 64, (), {})
                details = iter((attack, dispatch, successor))
                unknown_detail = RuinsDetailRecognition(
                    RuinsDetailObservation("unknown", False, 0, 0, RuinsControlState.HIDDEN, reset_identity=RESET),
                    "0" * 64, (), {},
                )
                result_rec = RuinsResultRecognition(
                    RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, None, None, None,
                                           "2" * 64, RESET, True, False, True),
                    "2" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {},
                )
                with patch(
                    "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
                    side_effect=lambda _frame, identity, **_kwargs: next(details) if identity == "Nova Challenge" else unknown_detail,
                ), patch(
                    "scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets",
                    return_value=result_rec,
                ), patch(
                    "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
                    return_value=post_detail_rec,
                ):
                    route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
                    route.controller.observe_list(list_rec.observation)
                    outcome = route._run_challenge(runtime.frames[0], list_rec, row)
                self.assertEqual(outcome.status, "unresolved")
                self.assertEqual(outcome.reason, "successful_progress_not_visible")
                self.assertEqual(len(runtime.backs), 0)
                self.assertEqual(runtime.reconciliations[0][1], "unresolved")

    def test_ruins_evidence_bound_recovery_closes_detail_without_repeating_combat(self):
        runtime = FakeRuntime()
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0)
        row = RuinsChallengeRow(
            "Gear Challenge", None, RuinsAvailability.AVAILABLE, 68, 190, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1080), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "b" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        list_rec = RuinsFrameRecognition(listed, "b" * 64, (), {})
        safe_rec = RuinsFrameRecognition(replace(listed, source_frame_sha256="c" * 64), "c" * 64, (), {})
        home_rec = RuinsFrameRecognition(
            RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN,
                                   RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, (), "none", "d" * 64, RESET,
                                   home_base_recognized=True, ruins_building_recognized=True),
            "d" * 64, (), {},
        )
        successor = RuinsDetailRecognition(
            RuinsDetailObservation("Gear Challenge", True, 68, 190, RuinsControlState.VISIBLE_ENABLED, reset_identity=RESET),
            "e" * 64, (), {},
        )
        evidence_root = Path(".local-captures/flow-delivery/RUINS-CHALLENGE-HOME-ATLAS-MIGRATION")
        evidence_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=evidence_root) as directory:
            evidence = Path(directory)
            frames = evidence / "frames"
            frames.mkdir()
            detail_path = frames / "detail.png"
            successor_path = frames / "successor.png"
            self.assertTrue(cv2.imwrite(str(detail_path), np.full((1280, 800, 3), 1, dtype=np.uint8)))
            self.assertTrue(cv2.imwrite(str(successor_path), np.zeros((1280, 800, 3), dtype=np.uint8)))
            detail_sha = hashlib.sha256(detail_path.read_bytes()).hexdigest()
            successor_sha = hashlib.sha256(successor_path.read_bytes()).hexdigest()
            action_key = "ruins:challenge:reset:Gear Challenge:action"
            (evidence / "flow-delivery-result.json").write_text(json.dumps({
                "status": "failed", "ruins_result": {"reason": "successful_progress_not_visible"},
            }), encoding="utf-8")
            (evidence / "events.jsonl").write_text("\n".join((
                json.dumps({"type": "capture", "label": "challenge-detail-immediate-post", "path": str(detail_path), "sha256": detail_sha}),
                json.dumps({"type": "dispatch", "action_key": action_key, "target_identity": "ruins-dispatch", "target_roi": [255, 1140, 545, 1245], "source_sha256": detail_sha, "consequential": True}),
                json.dumps({"type": "dispatch", "action_key": action_key + ":continue", "target_identity": "ruins-result-continue", "target_roi": [249, 1033, 643, 1154], "source_sha256": detail_sha, "consequential": False}),
                json.dumps({"type": "capture", "label": "challenge-list-postcondition", "path": str(successor_path), "sha256": successor_sha}),
                json.dumps({"type": "reconcile", "action_key": action_key, "post_path": str(successor_path), "post_sha256": successor_sha, "status": "unresolved", "reason": "successful row progress not visible"}),
            )) + "\n", encoding="utf-8")
            with patch(
                "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
                side_effect=lambda frame, identity, **_kwargs: (replace(successor, observation=replace(successor.observation, floor_current=67)) if int(frame[0, 0, 0]) == 1 else successor) if identity == "Gear Challenge" else RuinsDetailRecognition(
                    RuinsDetailObservation("unknown", False, 0, 0, RuinsControlState.HIDDEN, reset_identity=RESET),
                    "0" * 64, (), {},
                ),
            ), patch(
                "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
                side_effect=(safe_rec, home_rec),
            ), patch.object(route, "_recover_known_detail_to_list", return_value=(runtime.frames[1], list_rec, 1, None, True)), patch.object(
                route, "_home_atlas_recognized", return_value=False,
            ):
                outcome = route.recover_only(evidence)
        self.assertEqual(outcome.status, "completed", outcome.reason)
        self.assertEqual(outcome.reason, "verified_safe_exit_to_home")
        self.assertEqual(runtime.taps, [])
        self.assertEqual(len(runtime.backs), 1)
        self.assertIn("Gear Challenge", route.controller.challenge_identities_attempted)

    def test_ruins_recovery_rejects_path_escape_wrong_hash_and_wrong_key(self):
        route = RuinsIntegratedRoute(FakeRuntime(), reset_identity=RESET, current_day="Wed", post_input_delay=0)
        artifact_root = Path(".local-captures/flow-delivery/RUINS-CHALLENGE-HOME-ATLAS-MIGRATION")
        artifact_root.mkdir(parents=True, exist_ok=True)
        for tamper, expected in (("path", "recovery_evidence_path_escape"), ("hash", "recovery_evidence_successor_hash_mismatch"), ("key", "recovery_evidence_reconcile_link_invalid")):
            with self.subTest(tamper=tamper), TemporaryDirectory(dir=artifact_root) as directory:
                evidence = Path(directory)
                frames = evidence / "frames"
                frames.mkdir()
                frame_path = frames / "frame.png"
                self.assertTrue(cv2.imwrite(str(frame_path), np.zeros((1280, 800, 3), dtype=np.uint8)))
                frame_sha = hashlib.sha256(frame_path.read_bytes()).hexdigest()
                action_key = "ruins:challenge:reset:Gear Challenge:action"
                successor_path = frame_path if tamper != "path" else evidence / "outside.png"
                successor_sha = "0" * 64 if tamper == "hash" else frame_sha
                reconcile_key = action_key + ":wrong" if tamper == "key" else action_key
                (evidence / "flow-delivery-result.json").write_text(json.dumps({"status": "failed", "ruins_result": {"reason": "successful_progress_not_visible"}}), encoding="utf-8")
                (evidence / "events.jsonl").write_text("\n".join((
                    json.dumps({"type": "capture", "label": "challenge-detail-immediate-post", "path": str(frame_path), "sha256": frame_sha}),
                    json.dumps({"type": "dispatch", "action_key": action_key, "target_identity": "ruins-dispatch", "target_roi": [255, 1140, 545, 1245], "source_sha256": frame_sha, "consequential": True}),
                    json.dumps({"type": "dispatch", "action_key": action_key + ":continue", "target_identity": "ruins-result-continue"}),
                    json.dumps({"type": "capture", "label": "challenge-list-postcondition", "path": str(successor_path), "sha256": successor_sha}),
                    json.dumps({"type": "reconcile", "action_key": reconcile_key, "post_path": str(successor_path), "post_sha256": successor_sha, "status": "unresolved", "reason": "successful row progress not visible"}),
                )) + "\n", encoding="utf-8")
                outcome = route.recover_only(evidence)
                self.assertEqual(outcome.status, "blocked")
                self.assertEqual(outcome.reason, expected)

    def test_ruins_route_continues_from_current_ruins_list_without_home_entry(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1000), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        source_rec = RuinsFrameRecognition(listed, "a" * 64, (("challenge:Nova Challenge", row.target_roi),), {})
        after = replace(
            listed,
            rows=(replace(row, progress_current=19, source_frame_sha256="d" * 64),),
            source_frame_sha256="d" * 64,
        )
        after_rec = RuinsFrameRecognition(after, "d" * 64, (), {})
        safe_rec = RuinsFrameRecognition(replace(listed, source_frame_sha256="e" * 64), "e" * 64, (), {})
        home = RuinsScreenObservation(
            True, "HOME_BASE", False, None,
            RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN,
            (), "none", "f" * 64, RESET, True, True,
        )
        home_rec = RuinsFrameRecognition(home, "f" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        detail_queue = iter((
            RuinsDetailRecognition(
                RuinsDetailObservation(
                    "Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED,
                    source_frame_sha256="b" * 64, reset_identity=RESET,
                ),
                "b" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {},
            ),
            RuinsDetailRecognition(
                RuinsDetailObservation(
                    "Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN,
                    RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0,
                    source_frame_sha256="c" * 64, reset_identity=RESET,
                ),
                "c" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {},
            ),
        ))
        with patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
            side_effect=(source_rec, after_rec, safe_rec, home_rec),
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
            side_effect=lambda *_args, **_kwargs: next(detail_queue),
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets",
            return_value=RuinsResultRecognition(
                RuinsResultObservation(
                    "Nova Challenge", RuinsResult.SUCCESS, None, None, None,
                    "x" * 64, RESET, True, False, True,
                ),
                "x" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {},
            ),
        ):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            with patch.object(route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)), patch.object(
                route, "_recover_home_zoom_before_ruins_binding", side_effect=AssertionError("Home zoom must be skipped")
            ), patch.object(
                route, "_current_frame_ruins_binding", side_effect=AssertionError("Home atlas binding must be skipped")
            ), patch.object(route, "_home_atlas_recognized", return_value=False):
                outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.reason, "verified_safe_exit_to_home")
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual(
            [item[1]["target_identity"] for item in runtime.taps],
            ["challenge:Nova Challenge", "ruins-attack", "ruins-dispatch", "ruins-result-continue"],
        )
        self.assertTrue(runtime.backs)

    def test_ruins_unknown_source_still_requires_home_recovery(self):
        runtime = FakeRuntime()
        unknown = RuinsScreenObservation(
            False, "UNKNOWN", False, None,
            RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN,
            (), "unknown", "a" * 64, RESET,
        )
        unknown_rec = RuinsFrameRecognition(unknown, "a" * 64, (), {})
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", return_value=unknown_rec), patch.object(
            route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)
        ), patch.object(
            route, "_recover_home_zoom_before_ruins_binding", return_value=(None, "home_zoom_recovery_blocked:unknown")
        ) as recover:
            outcome = route.run()
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(outcome.reason, "home_zoom_recovery_blocked:unknown")
        recover.assert_called_once()
        self.assertEqual(runtime.taps, [])
        self.assertEqual(runtime.backs, [])

    def test_ruins_detail_source_backs_to_list_then_runs_full_controller_chain(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1000), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        list_rec = RuinsFrameRecognition(listed, "a" * 64, (("challenge:Nova Challenge", row.target_roi),), {})
        after = replace(listed, rows=(replace(row, progress_current=19, source_frame_sha256="d" * 64),), source_frame_sha256="d" * 64)
        after_rec = RuinsFrameRecognition(after, "d" * 64, (), {})
        safe_rec = RuinsFrameRecognition(replace(listed, source_frame_sha256="e" * 64), "e" * 64, (), {})
        home = RuinsScreenObservation(
            True, "HOME_BASE", False, None,
            RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN,
            (), "none", "f" * 64, RESET, True, True,
        )
        home_rec = RuinsFrameRecognition(home, "f" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        detail_source = RuinsDetailRecognition(
            RuinsDetailObservation(
                "Gear Challenge", True, 67, 190, RuinsControlState.VISIBLE_ENABLED,
                source_frame_sha256="0" * 64, reset_identity=RESET,
            ),
            "0" * 64, (("ruins-attack", (255, 1146, 545, 1251)),), {},
        )
        unknown_detail = RuinsDetailRecognition(
            RuinsDetailObservation(
                "unknown", False, 0, 0, RuinsControlState.HIDDEN,
                source_frame_sha256="0" * 64, reset_identity=RESET,
            ),
            "0" * 64, (), {},
        )
        challenge_details = iter((
            RuinsDetailRecognition(
                RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="b" * 64, reset_identity=RESET),
                "b" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {},
            ),
            RuinsDetailRecognition(
                RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="c" * 64, reset_identity=RESET),
                "c" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {},
            ),
        ))

        def detail_recognizer(_frame, identity, **_kwargs):
            if identity == "Gear Challenge":
                return detail_source
            if identity == "Nova Challenge" and int(_frame[0, 0, 0]) >= 3:
                return next(challenge_details)
            return unknown_detail

        result_rec = RuinsResultRecognition(
            RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, None, None, None, "x" * 64, RESET, True, False, True),
            "x" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {},
        )
        with patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
            side_effect=(RuinsFrameRecognition(RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "0" * 64, RESET), "0" * 64, (), {}), list_rec, after_rec, safe_rec, home_rec),
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
            side_effect=detail_recognizer,
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets",
            return_value=result_rec,
        ):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            with patch.object(route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)), patch.object(
                route, "_recover_home_zoom_before_ruins_binding", side_effect=AssertionError("detail source must not enter Home recovery")
            ), patch.object(route, "_current_frame_ruins_binding", side_effect=AssertionError("detail source must not bind Home atlas")), patch.object(
                route, "_home_atlas_recognized", return_value=False
            ):
                outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.reason, "verified_safe_exit_to_home")
        self.assertEqual(outcome.actions_completed, 2)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual([item[1]["target_identity"] for item in runtime.taps], ["challenge:Nova Challenge", "ruins-attack", "ruins-dispatch", "ruins-result-continue"])
        self.assertEqual(len(runtime.backs), 2)
        self.assertEqual(runtime.backs[0][1]["action_key"].split(":")[1], "detail-safe-exit")

    def test_ruins_ambiguous_detail_source_blocks_without_input(self):
        runtime = FakeRuntime()
        unknown = RuinsFrameRecognition(
            RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "0" * 64, RESET),
            "0" * 64, (), {},
        )
        ambiguous = RuinsDetailRecognition(
            RuinsDetailObservation("unknown", False, 67, 190, RuinsControlState.HIDDEN, source_frame_sha256="0" * 64, reset_identity=RESET),
            "0" * 64, (), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", return_value=unknown), patch.object(
            route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets", return_value=ambiguous
        ), patch.object(route, "_recover_home_zoom_before_ruins_binding", side_effect=AssertionError("ambiguous detail must not recover Home")):
            outcome = route.run()
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(outcome.reason, "ruins_detail_context_ambiguous")
        self.assertEqual(runtime.taps, [])
        self.assertEqual(runtime.backs, [])

    def test_ruins_dispatch_source_backs_to_detail_then_list_and_runs_full_chain(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1000), source_frame_sha256="a" * 64, reset_identity=RESET,
        )
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED, (row,), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        list_rec = RuinsFrameRecognition(listed, "a" * 64, (("challenge:Nova Challenge", row.target_roi),), {})
        after = replace(listed, rows=(replace(row, progress_current=19, source_frame_sha256="d" * 64),), source_frame_sha256="d" * 64)
        after_rec = RuinsFrameRecognition(after, "d" * 64, (), {})
        safe_rec = RuinsFrameRecognition(replace(listed, source_frame_sha256="e" * 64), "e" * 64, (), {})
        home = RuinsScreenObservation(
            True, "HOME_BASE", False, None,
            RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN,
            (), "none", "f" * 64, RESET, True, True,
        )
        home_rec = RuinsFrameRecognition(home, "f" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        dispatch_source = RuinsDetailRecognition(
            RuinsDetailObservation(
                "", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED,
                True, 200200, 200200, True, 0, source_frame_sha256="0" * 64, reset_identity=RESET,
            ),
            "0" * 64, (("ruins-dispatch", (255, 1140, 545, 1245)),), {},
        )
        gear_detail = RuinsDetailRecognition(
            RuinsDetailObservation(
                "Gear Challenge", True, 67, 190, RuinsControlState.VISIBLE_ENABLED,
                source_frame_sha256="0" * 64, reset_identity=RESET,
            ),
            "0" * 64, (("ruins-attack", (255, 1146, 545, 1251)),), {},
        )
        unknown_detail = RuinsDetailRecognition(
            RuinsDetailObservation("unknown", False, 0, 0, RuinsControlState.HIDDEN, source_frame_sha256="0" * 64, reset_identity=RESET),
            "0" * 64, (), {},
        )
        challenge_details = iter((
            RuinsDetailRecognition(
                RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="b" * 64, reset_identity=RESET),
                "b" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {},
            ),
            RuinsDetailRecognition(
                RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="c" * 64, reset_identity=RESET),
                "c" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {},
            ),
        ))

        def detail_recognizer(frame, identity, **_kwargs):
            ordinal = int(frame[0, 0, 0])
            if identity == "" and ordinal < 2:
                return dispatch_source
            if ordinal in (2, 3) and identity == "Gear Challenge":
                return gear_detail
            if ordinal >= 5 and identity == "Nova Challenge":
                return next(challenge_details)
            return unknown_detail

        result_rec = RuinsResultRecognition(
            RuinsResultObservation("Nova Challenge", RuinsResult.SUCCESS, None, None, None, "x" * 64, RESET, True, False, True),
            "x" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {},
        )
        unknown_list = RuinsFrameRecognition(
            RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "0" * 64, RESET),
            "0" * 64, (), {},
        )
        with patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
            side_effect=(unknown_list, list_rec, after_rec, safe_rec, home_rec),
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets",
            side_effect=detail_recognizer,
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets",
            return_value=result_rec,
        ):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            with patch.object(route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)), patch.object(
                route, "_recover_home_zoom_before_ruins_binding", side_effect=AssertionError("Dispatch source must not enter Home recovery")
            ), patch.object(route, "_current_frame_ruins_binding", side_effect=AssertionError("Dispatch source must not bind Home atlas")), patch.object(
                route, "_home_atlas_recognized", return_value=False
            ):
                outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.reason, "verified_safe_exit_to_home")
        self.assertEqual(outcome.actions_completed, 3)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual([item[1]["target_identity"] for item in runtime.taps], ["challenge:Nova Challenge", "ruins-attack", "ruins-dispatch", "ruins-result-continue"])
        self.assertEqual(len(runtime.backs), 3)

    def test_ruins_invalid_dispatch_source_blocks_without_input(self):
        runtime = FakeRuntime()
        unknown = RuinsFrameRecognition(
            RuinsScreenObservation(False, "UNKNOWN", False, None, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, RuinsControlState.UNKNOWN, (), "unknown", "0" * 64, RESET),
            "0" * 64, (), {},
        )
        invalid_dispatch = RuinsDetailRecognition(
            RuinsDetailObservation("", False, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, True, 199999, 200200, False, 0, source_frame_sha256="0" * 64, reset_identity=RESET),
            "0" * 64, (), {},
        )
        route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0)
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", return_value=unknown), patch.object(
            route, "_dismiss_known_vip_popup", return_value=(runtime.frames[0], None, 0)
        ), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets", return_value=invalid_dispatch
        ), patch.object(route, "_recover_home_zoom_before_ruins_binding", side_effect=AssertionError("invalid Dispatch must not recover Home")):
            outcome = route.run()
        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(outcome.reason, "ruins_dispatch_context_ambiguous")
        self.assertEqual(runtime.taps, [])
        self.assertEqual(runtime.backs, [])

    def test_ruins_safe_exit_accepts_atlas_home_when_legacy_ocr_is_truncated(self):
        runtime = FakeRuntime()
        listed = RuinsScreenObservation(
            True, "RUINS_CHALLENGE", True, 100,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            RuinsControlState.VISIBLE_ENABLED,
            (), "none", "a" * 64, RESET,
            safe_back_control=RuinsControlState.VISIBLE_ENABLED,
        )
        unknown = RuinsScreenObservation(
            False, "UNKNOWN", False, None,
            RuinsControlState.UNKNOWN,
            RuinsControlState.UNKNOWN,
            RuinsControlState.UNKNOWN,
            (), "unknown", "b" * 64, RESET,
        )
        listed_recognition = RuinsFrameRecognition(listed, "a" * 64, (), {})
        unknown_recognition = RuinsFrameRecognition(unknown, "b" * 64, (), {})
        route = RuinsIntegratedRoute(
            runtime,
            reset_identity=RESET,
            current_day="Wed",
            navigation_only=True,
            post_input_delay=0,
            recognition_timeout=1,
        )
        with patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_frame",
            side_effect=(listed_recognition, unknown_recognition),
        ), patch.object(
            route, "_home_atlas_recognized", side_effect=(False, True)
        ), patch.object(route.runtime, "back") as back:
            outcome = route._return_home(runtime.frames[0], listed_recognition, 1)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.reason, "verified_safe_exit_to_home")
        self.assertEqual(outcome.actions_completed, 2)
        back.assert_called_once()

    def test_ruins_route_optionally_tries_distinct_second_stage_after_failure(self):
        runtime = FakeRuntime()
        first = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 700, 780, 850), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        second = replace(first, identity="Module Challenge", progress_current=12, target_roi=(560, 900, 780, 1080))
        home = RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, (), "none", "a" * 64, RESET, True, True)
        listed = RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 100, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (first, second), "none", "b" * 64, RESET, safe_back_control=RuinsControlState.VISIBLE_ENABLED)
        after_first_rows = (replace(first, source_frame_sha256="f" * 64), replace(second, source_frame_sha256="f" * 64))
        after_first = replace(listed, rows=after_first_rows, source_frame_sha256="f" * 64)
        after_second_rows = (
            replace(first, source_frame_sha256="1" * 64),
            replace(second, progress_current=13, source_frame_sha256="1" * 64),
        )
        after_second = replace(listed, rows=after_second_rows, source_frame_sha256="1" * 64)
        safe_before = replace(listed, source_frame_sha256="2" * 64)
        list_queue = iter((
            RuinsFrameRecognition(home, "a" * 64, (("ruins-building", (50, 800, 220, 1030)),), {}),
            RuinsFrameRecognition(home, "a" * 64, (("ruins-building", (50, 800, 220, 1030)),), {}),
            RuinsFrameRecognition(listed, "b" * 64, (("challenge:Nova Challenge", first.target_roi), ("challenge:Module Challenge", second.target_roi)), {}),
            RuinsFrameRecognition(after_first, "f" * 64, (("challenge:Module Challenge", second.target_roi),), {}),
            RuinsFrameRecognition(after_second, "1" * 64, (), {}),
            RuinsFrameRecognition(safe_before, "2" * 64, (), {}),
            RuinsFrameRecognition(replace(home, source_frame_sha256="3" * 64), "3" * 64, (("ruins-building", (50, 800, 220, 1030)),), {}),
        ))
        detail_queue = iter((
            RuinsDetailRecognition(RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="c" * 64, reset_identity=RESET), "c" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {}),
            RuinsDetailRecognition(RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="d" * 64, reset_identity=RESET), "d" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {}),
            RuinsDetailRecognition(RuinsDetailObservation("Module Challenge", True, 13, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="3" * 64, reset_identity=RESET), "3" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {}),
            RuinsDetailRecognition(RuinsDetailObservation("Module Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="4" * 64, reset_identity=RESET), "4" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {}),
        ))
        result_queue = iter((
            RuinsResultRecognition(RuinsResultObservation("Nova Challenge", RuinsResult.FAILURE, None, None, None, "e" * 64, RESET, False, True, True), "e" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {}),
            RuinsResultRecognition(RuinsResultObservation("Module Challenge", RuinsResult.SUCCESS, None, None, None, "5" * 64, RESET, True, False, True), "5" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {}),
        ))
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", side_effect=lambda *_args, **_kwargs: next(list_queue)), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets", side_effect=lambda *_args, **_kwargs: next(detail_queue)
        ), patch("scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets", side_effect=lambda *_args, **_kwargs: next(result_queue)):
            route = RuinsIntegratedRoute(
                runtime,
                reset_identity=RESET,
                current_day="Wed",
                allow_optional_second=True,
                post_input_delay=0,
                recognition_timeout=1,
            )
            with patch.object(route, "_recover_home_zoom_before_ruins_binding", return_value=(runtime.frames[0], None)), patch.object(
                route, "_current_frame_ruins_binding", return_value=(50, 800, 220, 1030)
            ):
                outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.actions_completed, 2)
        self.assertEqual([item[1] for item in runtime.reconciliations], ["failed_confirmed", "confirmed"])
        consequential = [item for item in runtime.taps if item[1].get("consequential")]
        self.assertEqual(len(consequential), 2)
        self.assertNotEqual(consequential[0][1]["action_key"], consequential[1][1]["action_key"])

    def test_all_routes_are_dry_run_by_default_at_adapter_boundary(self):
        from scripts.noahs_tavern_recruit_bluestacks import NoahAdapterConfig
        from scripts.nova_praise_bluestacks import NovaAdapterConfig

        self.assertTrue(NoahAdapterConfig().dry_run)
        self.assertTrue(NovaAdapterConfig().dry_run)


if __name__ == "__main__":
    unittest.main()
