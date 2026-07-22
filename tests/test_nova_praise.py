from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.contracts import TaskOutcome
from tasks.nova_praise import (
    NOVA_POLICY_COOLDOWN_SECONDS,
    NOVA_PRAISE_TARGET,
    NovaPraiseObservation,
    next_eligible_timestamp,
    nova_authorizeable,
    nova_cooldown_consistent_with_policy,
    nova_perform_one_pulse,
    nova_postcondition_verified,
    parse_cooldown_seconds,
    with_cooldown,
)
from tasks.nova_praise_runtime import NovaAction, NovaPraiseRuntimeController
from tasks.nova_praise_vision import NovaFrameRecognition, NOVA_PRAISE_ROI


class NovaPraiseContractTests(unittest.TestCase):
    def obs(self, **changes):
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

    def after_decrement(self, *, cooldown_seconds: int, captured_monotonic: float, digest: str = "b" * 64):
        return self.obs(
            attempts_remaining=6,
            praise_enabled=False,
            cooldown_active=True,
            cooldown_seconds=cooldown_seconds,
            next_eligible_at=captured_monotonic + cooldown_seconds,
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
        )

    def test_attempt_counting(self):
        self.assertEqual(self.obs().attempts_remaining, 7)
        self.assertEqual(replace(self.obs(), attempts_remaining=0).attempts_remaining, 0)

    def test_one_attempt_decrement_and_cooldown_postcondition(self):
        before = self.obs()
        after = self.after_decrement(cooldown_seconds=299, captured_monotonic=101.0)
        self.assertTrue(nova_postcondition_verified(before, after, now=101.0))
        result = nova_perform_one_pulse(before, after, now=101.0)
        self.assertEqual(result.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(result.details["attempts_remaining"], 6)

    def test_cooldown_parsing(self):
        self.assertEqual(parse_cooldown_seconds("Next attempt in 01:23"), 83)
        self.assertEqual(parse_cooldown_seconds("Cooldown: 01:02:03"), 3723)
        self.assertEqual(parse_cooldown_seconds("CD: 00:05:00"), 300)
        self.assertEqual(parse_cooldown_seconds("next attempt in 5 minutes"), 300)
        self.assertIsNone(parse_cooldown_seconds("Interaction attempts left: 6"))

    def test_next_eligible_scheduling_yields(self):
        waiting = with_cooldown(self.obs(attempts_remaining=6, cooldown_text="Next attempt in 00:30"), now=200.0)
        self.assertEqual(next_eligible_timestamp(waiting, now=200.0), 230.0)
        self.assertIsNone(next_eligible_timestamp(self.obs(attempts_remaining=0), now=200.0))

    def test_repeat_until_zero(self):
        before = self.obs(attempts_remaining=1)
        after = self.obs(
            attempts_remaining=0,
            praise_enabled=False,
            cooldown_active=True,
            cooldown_seconds=299,
            next_eligible_at=400.0,
            frame_sha256="b" * 64,
            captured_monotonic=101.0,
        )
        self.assertTrue(nova_postcondition_verified(before, after, now=101.0))
        self.assertEqual(nova_perform_one_pulse(before, after, now=101.0).outcome, TaskOutcome.DONE)

    def test_disabled_cooldown_unknown_and_stale_guards(self):
        for changes in (
            {"praise_enabled": False},
            {"cooldown_active": True, "cooldown_seconds": 10},
            {"screen_state": "UNKNOWN", "recognized": False},
            {"stale": True},
        ):
            self.assertFalse(nova_authorizeable(self.obs(**changes), now=101.0))

    def test_policy_cooldown_near_300_minus_elapsed(self):
        before = self.obs(captured_monotonic=100.0)
        after = self.after_decrement(cooldown_seconds=290, captured_monotonic=110.0)
        self.assertTrue(nova_cooldown_consistent_with_policy(before, after))
        self.assertTrue(nova_postcondition_verified(before, after, now=110.0))

    def test_retained_278_second_cooldown_proof(self):
        before = self.obs(captured_monotonic=100.0)
        after = self.after_decrement(cooldown_seconds=278, captured_monotonic=122.0)
        self.assertEqual(NOVA_POLICY_COOLDOWN_SECONDS, 300)
        self.assertTrue(nova_cooldown_consistent_with_policy(before, after))
        self.assertTrue(nova_postcondition_verified(before, after, now=122.0))

    def test_immediate_post_rejects_below_270_while_accepting_policy_window(self):
        before = self.obs(captured_monotonic=100.0)
        self.assertFalse(
            nova_cooldown_consistent_with_policy(
                before,
                self.after_decrement(cooldown_seconds=269, captured_monotonic=101.0),
            )
        )
        self.assertTrue(
            nova_cooldown_consistent_with_policy(
                before,
                self.after_decrement(cooldown_seconds=278, captured_monotonic=101.0),
            )
        )
        self.assertTrue(
            nova_cooldown_consistent_with_policy(
                before,
                self.after_decrement(cooldown_seconds=299, captured_monotonic=101.0),
            )
        )

    def test_cooldown_rejects_over_policy_too_short_missing_and_no_decrement(self):
        before = self.obs(captured_monotonic=100.0)
        self.assertFalse(
            nova_cooldown_consistent_with_policy(
                before,
                self.after_decrement(cooldown_seconds=301, captured_monotonic=101.0),
            )
        )
        self.assertFalse(
            nova_postcondition_verified(
                before,
                self.after_decrement(cooldown_seconds=301, captured_monotonic=101.0),
                now=101.0,
            )
        )
        self.assertFalse(
            nova_postcondition_verified(
                before,
                self.after_decrement(cooldown_seconds=30, captured_monotonic=101.0),
                now=101.0,
            )
        )
        missing = self.obs(
            attempts_remaining=6,
            praise_enabled=False,
            cooldown_active=False,
            cooldown_seconds=None,
            frame_sha256="b" * 64,
            captured_monotonic=101.0,
        )
        self.assertFalse(nova_postcondition_verified(before, missing, now=101.0))
        no_decrement = self.after_decrement(cooldown_seconds=299, captured_monotonic=101.0)
        no_decrement = replace(no_decrement, attempts_remaining=7)
        self.assertFalse(nova_postcondition_verified(before, no_decrement, now=101.0))


class NovaRuntimeTests(unittest.TestCase):
    def recognition(self, observation, digest):
        return NovaFrameRecognition(observation, digest, ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),), {})

    def test_no_duplicate_dispatch(self):
        controller = NovaPraiseRuntimeController(now=100.0)
        obs = NovaPraiseContractTests().obs()
        first = controller.next_command(self.recognition(obs, "a" * 64))
        self.assertEqual(first.action, NovaAction.PRAISE)
        second = controller.next_command(self.recognition(obs, "a" * 64))
        self.assertTrue(second.terminal)
        self.assertIn("postcondition", second.reason)

    def test_repeat_waits_for_cooldown_and_then_allows_fresh_attempt(self):
        controller = NovaPraiseRuntimeController(now=100.0)
        helper = NovaPraiseContractTests()
        before = helper.obs()
        self.assertEqual(controller.next_command(self.recognition(before, "a" * 64)).action, NovaAction.PRAISE)
        after = helper.after_decrement(cooldown_seconds=299, captured_monotonic=101.0)
        self.assertTrue(controller.accept_postcondition(before, after))
        self.assertEqual(controller.next_command(self.recognition(after, "b" * 64)).action, NovaAction.WAIT_COOLDOWN)


if __name__ == "__main__":
    unittest.main()
