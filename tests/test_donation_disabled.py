from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.donation_disabled import (
    ALLIANCE_TECH_SCREEN,
    DONATION_ACTION,
    DONATION_CONSEQUENCE,
    DONATION_POSTCONDITION,
    DONATION_TARGET,
    MAX_DONATIONS_PER_RESET,
    MAX_AVAILABLE_ATTEMPTS,
    DonationActionReconciliationError,
    DonationDisposition,
    DonationObservation,
    confirmed_donation_count,
    donation_action_key,
    donation_authorizeable,
    donation_disposition,
    donation_postcondition_verified,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


def observation(**changes) -> DonationObservation:
    values = {
        "screen_state": ALLIANCE_TECH_SCREEN,
        "auto_hot_marker": True,
        "tech_identity": "current auto HOT research label",
        "target_identity": DONATION_TARGET,
        "target_roi": (400, 700, 620, 790),
        "panel_bounds": (40, 300, 760, 850),
        "control_class": "DONATE",
        "donate_control_visible": True,
        "control_enabled": True,
        "quantity": 1,
        "resource_identity": "STEEL",
        "resource_known": True,
        "donation_amount": 1000,
        "resource_balance": 129702,
        "available_attempts": 20,
        "attempt_capacity": MAX_AVAILABLE_ATTEMPTS,
        "active_recharge_timer": False,
        "tech_points": 2138950,
        "reward_signature": (250, 250, 250, 250),
        "game_day_id": "synthetic-day-1",
        "target_provenance": BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        "source_frame_sha256": "a" * 64,
        "evidence_refs": ("synthetic:alliance-donation",),
        "overlay_state": "none",
        "runtime_profile_id": ACTIVE_RUNTIME_PROFILE_ID,
        "recognized": True,
    }
    values.update(changes)
    return DonationObservation(**values)


def canonical_action(*, flow_id="alliance-donation-flow", status="confirmed", ordinal=1,
                     game_day_id="synthetic-day-1", **changes):
    action = {
        "task_id": flow_id,
        "action_key": donation_action_key(
            account_id="account", server_id="server", game_day_id=game_day_id, ordinal=ordinal,
        ),
        "semantic_action": DONATION_ACTION,
        "source_state": ALLIANCE_TECH_SCREEN,
        "target_identity": DONATION_TARGET,
        "consequence": DONATION_CONSEQUENCE,
        "expected_postcondition": DONATION_POSTCONDITION,
        "game_day_id": game_day_id,
        "quantity": 1,
        "cost_type": "ordinary_resource",
        "resource_or_currency": "STEEL",
        "cost_amount": 1000,
        "final_status": status,
    }
    action.update(changes)
    return action


class AllianceDonationSemanticsTests(unittest.TestCase):
    def test_current_automatic_hot_target_and_active_timer_allow_one_ordinary_tap(self):
        current = observation(
            tech_identity="technology not in any route allowlist",
            active_recharge_timer=True,
        )
        self.assertTrue(donation_authorizeable(current, 0))
        self.assertEqual(donation_disposition(current, 0), DonationDisposition.READY)

    def test_unknown_target_cost_balance_or_nonordinary_control_fails_closed(self):
        current = observation()
        for changes in (
            {"auto_hot_marker": False},
            {"tech_identity": ""},
            {"screen_state": "ALLIANCE_TECH_TREE"},
            {"target_identity": "alliance-tech:diamond-donate"},
            {"resource_identity": "DIAMOND"},
            {"resource_known": False},
            {"donation_amount": None},
            {"resource_balance": None},
            {"available_attempts": None},
            {"control_enabled": False},
            {"quantity": 2},
            {"overlay_state": "unknown"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(donation_disposition(replace(current, **changes), 0), DonationDisposition.BLOCKED)

    def test_attempts_exhaustion_defers_but_active_timer_does_not_block_stored_attempts(self):
        current = observation(available_attempts=0, active_recharge_timer=True)
        self.assertEqual(donation_disposition(current, 2), DonationDisposition.NO_ATTEMPTS)
        self.assertEqual(
            donation_disposition(observation(available_attempts=3, active_recharge_timer=True), 2),
            DonationDisposition.READY,
        )
        self.assertEqual(
            donation_disposition(observation(available_attempts=21), 2),
            DonationDisposition.BLOCKED,
        )

    def test_insufficient_resource_defers_without_changing_action_count(self):
        current = observation(resource_balance=999, control_enabled=False)
        self.assertEqual(donation_disposition(current, 4), DonationDisposition.INSUFFICIENT_RESOURCE)
        self.assertFalse(donation_authorizeable(current, 4))

    def test_ten_is_the_action_cap_and_not_a_points_or_bonus_value(self):
        current = observation()
        self.assertTrue(donation_authorizeable(current, 9))
        self.assertEqual(donation_disposition(current, MAX_DONATIONS_PER_RESET), DonationDisposition.DAILY_TARGET_REACHED)
        self.assertFalse(donation_authorizeable(current, MAX_DONATIONS_PER_RESET))
        self.assertEqual(donation_disposition(current, 11), DonationDisposition.BLOCKED)

    def test_bonus_x2_confirms_one_exact_spend_and_one_attempt(self):
        before = observation()
        after = observation(
            resource_balance=128702,
            available_attempts=19,
            tech_points=2139500,
            reward_signature=(550, 550, 550, 550),
        )
        self.assertTrue(donation_postcondition_verified(before, after, 0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, available_attempts=18), 0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, resource_balance=128703), 0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, tech_points=None,
                                                                          reward_signature=before.reward_signature), 0))

    def test_automatic_hot_reselection_is_a_tech_successor_after_exact_spend(self):
        before = observation()
        after = observation(
            tech_identity="next automatic HOT research",
            resource_balance=128702,
            available_attempts=19,
        )
        self.assertTrue(donation_postcondition_verified(before, after, 0))

    def test_action_keys_are_stable_unique_reset_scoped_ordinals(self):
        first = donation_action_key(
            account_id="account", server_id="server", game_day_id="day", ordinal=1,
        )
        self.assertEqual(first, donation_action_key(
            account_id="account", server_id="server", game_day_id="day", ordinal=1,
        ))
        self.assertNotEqual(first, donation_action_key(
            account_id="account", server_id="server", game_day_id="day", ordinal=2,
        ))
        with self.assertRaises(ValueError):
            donation_action_key(
                account_id="account", server_id="server", game_day_id="day", ordinal=11,
            )

    def test_partial_quota_remains_partial_when_attempts_or_resources_run_out(self):
        attempts = observation(available_attempts=0)
        resources = observation(resource_balance=999)
        self.assertEqual(donation_disposition(attempts, 3), DonationDisposition.NO_ATTEMPTS)
        self.assertEqual(donation_disposition(resources, 3), DonationDisposition.INSUFFICIENT_RESOURCE)
        self.assertEqual(donation_disposition(observation(), 3), DonationDisposition.READY)

    def test_confirmed_actions_survive_restart_and_ignore_other_resets(self):
        actions = [
            canonical_action(ordinal=1),
            canonical_action(ordinal=2),
            canonical_action(ordinal=1, game_day_id="synthetic-day-0"),
        ]
        self.assertEqual(
            confirmed_donation_count(
                actions, flow_id="alliance-donation-flow", account_id="account",
                server_id="server", game_day_id="synthetic-day-1",
            ),
            2,
        )

    def test_unknown_persisted_donation_requires_reconciliation_and_is_not_retried(self):
        with self.assertRaises(DonationActionReconciliationError):
            confirmed_donation_count(
                [canonical_action(status="input_sent")], flow_id="alliance-donation-flow",
                account_id="account", server_id="server", game_day_id="synthetic-day-1",
            )
        self.assertFalse(
            donation_postcondition_verified(
                observation(resource_balance=None), observation(), 0,
            )
        )

    def test_cancelled_no_effect_attempt_does_not_increment_durable_quota(self):
        self.assertEqual(
            confirmed_donation_count(
                [canonical_action(status="cancelled")], flow_id="alliance-donation-flow",
                account_id="account", server_id="server", game_day_id="synthetic-day-1",
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
