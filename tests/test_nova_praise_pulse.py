"""Focused tests for pulseable Nova Praise and replay capsule."""

from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.home_atlas import (
    AmbiguityState,
    AtlasViewport,
    HomeAtlas,
    LocalizationResult,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
)
from tasks.home_context import HomeReadyObservation
from tasks.nova_praise import NOVA_PRAISE_TARGET, NovaPraiseObservation, nova_postcondition_verified
from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController, NovaPulseView
from tasks.nova_praise_replay import assert_contract_fixtures_aligned, load_replay_manifest, run_replay_case
from tasks.nova_praise_vision import NOVA_PRAISE_ROI
from tasks.scheduler_task_result import SchedulerIdentity, SchedulerTaskOutcome


def _atlas() -> HomeAtlas:
    profile = PlatformProfile("BlueStacks 5 / Android", "pns-bluestacks-5-p64-800x1280-v1", (800, 1280), "com.global.ztmslg")
    viewport = AtlasViewport(
        "v1",
        "tile.png",
        "a" * 64,
        "now",
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        1.0,
        0.0,
        "origin",
    )
    lab = SemanticBuilding(
        "home.building.research_lab",
        "Research Lab",
        ((350, 500), (450, 500), (450, 620), (350, 620)),
        0.95,
        ("v1",),
        semantic_proof=("test",),
    )
    return HomeAtlas(
        2,
        "test",
        "1",
        profile,
        "fully_zoomed_out",
        "atlas pixels",
        (0, 0),
        1600,
        1800,
        "atlas.png",
        "test",
        "test",
        (((0, 0), (1600, 0), (1600, 1800), (0, 1800)),),
        (),
        (viewport,),
        (lab,),
    )


def _ready() -> HomeReadyObservation:
    return HomeReadyObservation(True, True, True, False, False)


def _loc() -> LocalizationResult:
    return LocalizationResult(
        True,
        "BlueStacks 5 / Android",
        "pns-bluestacks-5-p64-800x1280-v1",
        ZoomIdentity.FULLY_ZOOMED_OUT,
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0), (800, 0), (800, 1280), (0, 1280)),
        0.95,
        ("v1",),
        0.4,
        AmbiguityState.NONE,
        "interior",
        "a" * 64,
        "now",
    )


def _obs(**changes) -> NovaPraiseObservation:
    base = NovaPraiseObservation(
        screen_state="NOVA",
        research_lab_identity=True,
        nova_control_visible=False,
        selected_nova=True,
        praise_enabled=True,
        praise_target_identity=NOVA_PRAISE_TARGET,
        praise_target_roi=NOVA_PRAISE_ROI,
        attempts_remaining=7,
        frame_sha256="a" * 64,
        captured_monotonic=100.0,
    )
    return replace(base, **changes)


def _controller(*, replay: bool = True) -> NovaPulseController:
    return NovaPulseController(
        SchedulerIdentity("acct", "srv", "reset-1", NOVA_TASK_ID),
        _atlas(),
        now=100.0,
        replay_mode=replay,
    )


class NovaPraisePulseTests(unittest.TestCase):
    def test_at_most_one_praise_per_invocation(self):
        controller = _controller()
        first = controller.pulse(NovaPulseView(_ready(), _loc(), praise=_obs()))
        self.assertEqual(first.outcome, SchedulerTaskOutcome.ACTION_PERFORMED)
        self.assertEqual(first.action_count, 1)
        second = controller.pulse(NovaPulseView(_ready(), _loc(), praise=_obs(frame_sha256="c" * 64)))
        self.assertEqual(second.outcome, SchedulerTaskOutcome.BLOCKED)
        self.assertEqual(second.reason_code, "ONE_PRAISE_PER_INVOCATION")

    def test_attempts_decrement_verified(self):
        controller = _controller(replay=False)
        before = _obs()
        after = _obs(
            attempts_remaining=6,
            praise_enabled=False,
            cooldown_active=True,
            cooldown_seconds=30,
            next_eligible_at=130.0,
            frame_sha256="b" * 64,
            captured_monotonic=101.0,
        )
        self.assertTrue(nova_postcondition_verified(before, after, now=101.0))
        result = controller.accept_praise_postcondition(before, after)
        self.assertEqual(result.outcome, SchedulerTaskOutcome.ACTION_PERFORMED)
        self.assertEqual(result.observed_progress["attempts_remaining"], 6)

    def test_cooldown_produces_deferred(self):
        controller = _controller()
        result = controller.pulse(
            NovaPulseView(
                _ready(),
                _loc(),
                praise=_obs(praise_enabled=False, cooldown_active=True, cooldown_seconds=90, next_eligible_at=190.0),
            )
        )
        self.assertEqual(result.outcome, SchedulerTaskOutcome.DEFERRED)
        self.assertEqual(result.next_eligible_at, 190.0)
        self.assertEqual(result.action_count, 0)

    def test_zero_attempts_complete_for_reset(self):
        controller = _controller()
        result = controller.pulse(
            NovaPulseView(_ready(), _loc(), praise=_obs(attempts_remaining=0, praise_enabled=False))
        )
        self.assertEqual(result.outcome, SchedulerTaskOutcome.COMPLETE_FOR_RESET)

    def test_replay_emits_intended_actions_but_dispatches_none(self):
        controller = _controller(replay=True)
        result = controller.pulse(NovaPulseView(_ready(), _loc(), praise=_obs()))
        self.assertEqual(result.outcome, SchedulerTaskOutcome.ACTION_PERFORMED)
        self.assertIn("dispatch_free_praise", result.intended_actions)
        self.assertEqual(result.dispatched_actions, ())


class NovaPraiseReplayCapsuleTests(unittest.TestCase):
    def test_manifest_aligned_with_contract_and_cases_run(self):
        assert_contract_fixtures_aligned()
        manifest = load_replay_manifest()
        expected = {
            "canonical_home": "blocked",
            "localized_noncanonical_home": "blocked",
            "zoomed_in_home": "blocked",
            "research_lab_visible": "blocked",
            "research_lab_offscreen": "blocked",
            "research_lab_radial_menu": "blocked",
            "nova_lab": "blocked",
            "praise_attempts_available": "action_performed",
            "praise_on_cooldown": "deferred",
            "zero_attempts_remaining": "complete_for_reset",
            "unknown_or_negative_control": "manual_required",
        }
        for case in manifest["cases"]:
            result = run_replay_case(case["fixture_id"])
            self.assertEqual(result.dispatched_actions, ())
            self.assertEqual(result.outcome, expected[case["fixture_id"]], case["fixture_id"])
            if case["fixture_id"] == "research_lab_visible":
                self.assertEqual(result.permitted_action, "tap_building")
            if case["fixture_id"] == "research_lab_offscreen":
                self.assertEqual(result.permitted_action, "pan")
            if case["fixture_id"] == "zoomed_in_home":
                self.assertIn("ensure_canonical_home", result.intended_actions)


if __name__ == "__main__":
    unittest.main()
