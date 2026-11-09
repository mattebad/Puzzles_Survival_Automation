from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
import unittest

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from scripts.startup_recovery import ContextualPopupRecoveryResult
from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahCommand
from scripts.noahs_tavern_recruit_bluestacks import NoahTavernIntegratedRoute
from scripts.nova_praise_bluestacks import NovaPraiseIntegratedRoute
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
from tests.support.home_atlas import _UnusedAtlasLocalizer


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
        self.events = []
        self.taps = []
        self.swipes = []
        self.backs = []
        self.reconciliations = []

    def capture(self, label):
        frame = self.frames[self.index]
        self.events.append(("capture", label, frame.sha256))
        self.index += 1
        return frame

    def tap(self, source, **kwargs):
        if kwargs.get("consequential"):
            self.in_flight_action = kwargs["action_key"]
        continuation = kwargs.get("continuation_of")
        if continuation is not None:
            self.assert_in_flight(continuation)
        self.taps.append((source.sha256, kwargs))
        self.events.append(("tap", source.sha256, kwargs))

    def back(self, source, **kwargs):
        continuation = kwargs.get("continuation_of")
        if continuation is not None:
            self.assert_in_flight(continuation)
        self.backs.append((source.sha256, kwargs))
        self.events.append(("back", source.sha256, kwargs))

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
        # Reconciliation accepts ordinary transitions without an in-flight marker;
        # tap/back still enforce the exact key for explicit continuation_of inputs.
        self.reconciliations.append((action_key, status, post.sha256, reason))
        if status != "unresolved" and self.in_flight_action == action_key:
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

    def dispatch_swipe(self, start, end, duration_ms=400):
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
    def setUp(self):
        # These localizers are unused by the scripted Home paths.
        # The strict sentinel catches accidental localization in route tests.
        localizer = _UnusedAtlasLocalizer()
        self.addCleanup(localizer.assert_unused)
        for target in (
            "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer",
            "scripts.noahs_tavern_recruit_bluestacks.BlueStacksHomeLocalizer",
        ):
            dependency = patch(target, return_value=localizer)
            dependency.start()
            self.addCleanup(dependency.stop)

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
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_startup_overlay",
            side_effect=lambda runtime, captured, **kwargs: __import__(
                "scripts.startup_recovery", fromlist=["ContextualPopupRecoveryResult"]
            ).ContextualPopupRecoveryResult(
                captured, False, True, True, 0, "exact_vip_popup_absent"
            ),
        ):
            outcome = route.run()
        self.assertEqual(outcome.status, "completed", outcome.reason)
        self.assertEqual(outcome.actions_completed, 1)
        self.assertIsInstance(outcome.contextual_popup_recoveries, tuple)
        self.assertTrue(all("source_context" in row for row in outcome.contextual_popup_recoveries))
        self.assertEqual(
            [(key, status, post) for key, status, post, _reason in runtime.reconciliations],
            [
                (runtime.taps[0][1]["action_key"], "confirmed", runtime.frames[1].sha256),
                (runtime.taps[1][1]["action_key"], "confirmed", runtime.frames[4].sha256),
                (runtime.taps[2][1]["action_key"], "confirmed", runtime.frames[4].sha256),
                (runtime.backs[0][1]["action_key"], "confirmed", runtime.frames[runtime.index - 1].sha256),
            ],
        )
        self.assertEqual(len([item for item in runtime.taps if item[1].get("consequential")]), 0)
        self.assertEqual(runtime.taps[0][1]["target_roi"], (10, 10, 20, 20))
        self.assertEqual(bound_rois, [runtime.frames[0].sha256])
        self.assertTrue(runtime.backs)
    def test_safe_return_popup_dismissal_reobserves_before_back(self):
        runtime = FakeRuntime()
        tavern = noah_observation(NOAHS_TAVERN_SCREEN, "0" * 64, remaining=0)
        home = noah_observation(HOME_BASE_SCREEN, "5" * 64)

        def recognize(frame, **_kwargs):
            marker = int(frame[0, 0, 0])
            if marker == 5:
                return home
            return replace(tavern, frame_sha256=f"{marker:064x}")

        recoveries = []

        def contextual_recovery(_runtime, captured, **kwargs):
            recoveries.append((captured.sha256, kwargs["source_context"]))
            if len(recoveries) == 3:
                runtime.tap(
                    captured,
                    target_identity="VIP_POINTS_GET_PTS",
                    target_roi=(10, 10, 20, 20),
                    action_key=kwargs["action_key"],
                    action_class="navigation",
                    consequential=False,
                )
                return ContextualPopupRecoveryResult(
                    runtime.frames[2], True, True, True, 1, "popup_dismissed_resume_ready"
                )
            return ContextualPopupRecoveryResult(
                captured, False, True, True, 0, "exact_vip_popup_absent"
            )

        route = NoahTavernIntegratedRoute(
            runtime,
            max_recruits=1,
            recognizer=recognize,
            post_input_delay=0.0,
        )
        with patch(
            "scripts.noahs_tavern_recruit_bluestacks.recover_contextual_startup_overlay",
            side_effect=contextual_recovery,
        ), patch(
            "scripts.noahs_tavern_recruit_bluestacks.recognize_reset_popup",
            return_value={"recognized": False},
        ), patch.object(
            route.controller,
            "next_command",
            side_effect=lambda *_args, **_kwargs: NoahCommand(NoahAction.RETURN_HOME),
        ):
            outcome = route.run(max_steps=4)

        self.assertEqual(outcome.status, "completed", outcome.reason)
        self.assertEqual(outcome.actions_completed, 0)
        self.assertEqual(len(recoveries), 6)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0][1]["target_identity"], "VIP_POINTS_GET_PTS")
        self.assertTrue(runtime.taps[0][1]["action_key"].startswith("noah:popup-close:tavern-safe-return:"))
        self.assertEqual(len(runtime.backs), 1)
        tap_index = next(index for index, event in enumerate(runtime.events) if event[0] == "tap")
        reobserve_index = next(
            index
            for index, event in enumerate(runtime.events)
            if event[0] == "capture" and event[1] == "step-002-source"
        )
        back_index = next(index for index, event in enumerate(runtime.events) if event[0] == "back")
        self.assertLess(tap_index, reobserve_index)
        self.assertLess(reobserve_index, back_index)
        safe_exit_sources = [
            event[2]
            for event in runtime.events
            if event[0] == "capture" and event[1] == "tavern-safe-exit-immediate-before"
        ]
        self.assertEqual(len(safe_exit_sources), 2)
        self.assertEqual(runtime.backs[0][0], safe_exit_sources[-1])

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

    def test_all_routes_are_dry_run_by_default_at_adapter_boundary(self):
        from scripts.noahs_tavern_recruit_bluestacks import NoahAdapterConfig
        from scripts.nova_praise_bluestacks import NovaAdapterConfig

        self.assertTrue(NoahAdapterConfig().dry_run)
        self.assertTrue(NovaAdapterConfig().dry_run)


if __name__ == "__main__":
    unittest.main()
