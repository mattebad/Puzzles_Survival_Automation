from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
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
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsDetailObservation,
    RuinsResult,
    RuinsResultObservation,
    RuinsScreenObservation,
)
from tasks.ruins_challenge_vision import RuinsDetailRecognition, RuinsFrameRecognition, RuinsResultRecognition


RESET = "integration-reset"


class FakeRuntime:
    def __init__(self, count: int = 20):
        self.execute = True
        self.in_flight_action = None
        self.session = Path("fake-session")
        self.frames = []
        for ordinal in range(count):
            frame = np.full((1280, 800, 3), ordinal, dtype=np.uint8)
            self.frames.append(CapturedNativeFrame(frame, b"png", f"{ordinal:064x}", float(ordinal + 1), Path(f"{ordinal}.png")))
        self.index = 0
        self.taps = []
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

    def assert_in_flight(self, action_key):
        if self.in_flight_action != action_key:
            raise RuntimeError("continuation mismatch")

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
    def test_native_runtime_enforces_fresh_single_flight_transport(self):
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
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                runtime.back(source, action_key="back-before-reconcile")
            post = runtime.capture("post")
            runtime.reconcile("action-1", "confirmed", post, "verified")
            runtime.back(post, action_key="back-after-reconcile")
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
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                runtime.back(source, action_key="back-before-hold-reconcile")
            post = runtime.capture("hold-post")
            runtime.reconcile("hold-action-1", "confirmed", post, "hold verified")
            runtime.back(post, action_key="back-after-hold-reconcile")
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
        observations = iter((home, before, result, result, after, home))

        def recognize(_frame, **_kwargs):
            return next(observations)

        route = NoahTavernIntegratedRoute(runtime, recognizer=recognize, post_input_delay=0, result_timeout=1)
        outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(len(runtime.reconciliations), 1)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 1)
        self.assertTrue(runtime.backs)

    def test_nova_route_uses_controller_and_verifies_exact_decrement(self):
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
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 1)

    def test_ruins_route_executes_controller_chain_and_reconciles_failure(self):
        runtime = FakeRuntime()
        row = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 900, 780, 1080), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        home_obs = RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, (), "none", "a" * 64, RESET, True, True)
        list_obs = RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 100, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (row,), "none", "b" * 64, RESET)
        home_rec = RuinsFrameRecognition(home_obs, "a" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        list_rec = RuinsFrameRecognition(list_obs, "b" * 64, (("challenge:Nova Challenge", (560, 900, 780, 1080)),), {})
        post_list_rec = RuinsFrameRecognition(replace(list_obs, source_frame_sha256="f" * 64), "f" * 64, (), {})
        final_home = RuinsFrameRecognition(replace(home_obs, source_frame_sha256="1" * 64), "1" * 64, (("ruins-building", (50, 800, 220, 1030)),), {})
        detail_obs = RuinsDetailObservation("Nova Challenge", True, 19, 100, RuinsControlState.VISIBLE_ENABLED, source_frame_sha256="c" * 64, reset_identity=RESET)
        dispatch_obs = RuinsDetailObservation("Nova Challenge", True, 0, 0, RuinsControlState.HIDDEN, RuinsControlState.VISIBLE_ENABLED, True, 200200, 200200, True, 0, source_frame_sha256="d" * 64, reset_identity=RESET)
        result_obs = RuinsResultObservation("Nova Challenge", RuinsResult.FAILURE, None, None, None, "e" * 64, RESET, False, True, True)
        list_queue = iter((home_rec, list_rec, post_list_rec, final_home))
        detail_queue = iter((
            RuinsDetailRecognition(detail_obs, "c" * 64, (("ruins-attack", (250, 950, 550, 1080)),), {}),
            RuinsDetailRecognition(dispatch_obs, "d" * 64, (("ruins-dispatch", (250, 1050, 550, 1180)),), {}),
        ))
        result_rec = RuinsResultRecognition(result_obs, "e" * 64, (("ruins-result-continue", (200, 1080, 600, 1240)),), {})
        with patch("scripts.ruins_challenge_bluestacks.recognize_ruins_frame", side_effect=lambda *_args, **_kwargs: next(list_queue)), patch(
            "scripts.ruins_challenge_bluestacks.recognize_ruins_detail_with_targets", side_effect=lambda *_args, **_kwargs: next(detail_queue)
        ), patch("scripts.ruins_challenge_bluestacks.recognize_ruins_result_with_targets", return_value=result_rec):
            route = RuinsIntegratedRoute(runtime, reset_identity=RESET, current_day="Wed", post_input_delay=0, recognition_timeout=1)
            outcome = route.run()
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.actions_completed, 1)
        self.assertEqual(runtime.reconciliations[0][1], "failed_confirmed")
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 1)
        self.assertTrue(runtime.backs)

    def test_ruins_route_optionally_tries_distinct_second_stage_after_failure(self):
        runtime = FakeRuntime()
        first = RuinsChallengeRow(
            "Nova Challenge", None, RuinsAvailability.AVAILABLE, 18, 100, None,
            RuinsControlState.VISIBLE_ENABLED, RuinsChestState.UNKNOWN,
            (560, 700, 780, 850), source_frame_sha256="b" * 64, reset_identity=RESET,
        )
        second = replace(first, identity="Module Challenge", progress_current=12, target_roi=(560, 900, 780, 1080))
        home = RuinsScreenObservation(True, "HOME_BASE", False, None, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, RuinsControlState.HIDDEN, (), "none", "a" * 64, RESET, True, True)
        listed = RuinsScreenObservation(True, "RUINS_CHALLENGE", True, 100, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, RuinsControlState.VISIBLE_ENABLED, (first, second), "none", "b" * 64, RESET)
        after_first_rows = (replace(first, source_frame_sha256="f" * 64), replace(second, source_frame_sha256="f" * 64))
        after_first = replace(listed, rows=after_first_rows, source_frame_sha256="f" * 64)
        after_second_rows = (
            replace(first, source_frame_sha256="1" * 64),
            replace(second, progress_current=13, source_frame_sha256="1" * 64),
        )
        after_second = replace(listed, rows=after_second_rows, source_frame_sha256="1" * 64)
        list_queue = iter((
            RuinsFrameRecognition(home, "a" * 64, (("ruins-building", (50, 800, 220, 1030)),), {}),
            RuinsFrameRecognition(listed, "b" * 64, (("challenge:Nova Challenge", first.target_roi), ("challenge:Module Challenge", second.target_roi)), {}),
            RuinsFrameRecognition(after_first, "f" * 64, (("challenge:Module Challenge", second.target_roi),), {}),
            RuinsFrameRecognition(after_second, "1" * 64, (), {}),
            RuinsFrameRecognition(replace(home, source_frame_sha256="2" * 64), "2" * 64, (("ruins-building", (50, 800, 220, 1030)),), {}),
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
            outcome = RuinsIntegratedRoute(
                runtime,
                reset_identity=RESET,
                current_day="Wed",
                allow_optional_second=True,
                post_input_delay=0,
                recognition_timeout=1,
            ).run()
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
