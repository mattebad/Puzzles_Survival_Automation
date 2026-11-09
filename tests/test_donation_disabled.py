from __future__ import annotations

from dataclasses import replace
import json
import unittest

from tasks.donation_disabled import (
    ALLIANCE_TECH_SCREEN, DONATION_ACTION, DONATION_CONSEQUENCE, DONATION_POSTCONDITION,
    DONATION_RESOURCE, DONATION_TARGET, MAX_DONATIONS_PER_RESET, MAX_AVAILABLE_ATTEMPTS,
    DonationActionReconciliationError, DonationDisposition, DonationObservation,
    confirmed_donation_count, donation_action_key, donation_authorizeable,
    donation_disposition, donation_postcondition_verified,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


def observation(**changes) -> DonationObservation:
    values = {
        "screen_state": ALLIANCE_TECH_SCREEN, "auto_hot_marker": True,
        "tech_identity": "II", "target_identity": DONATION_TARGET,
        "target_roi": (400, 700, 620, 790), "panel_bounds": (40, 300, 760, 850),
        "control_class": "DONATE", "donate_control_visible": True, "control_enabled": True,
        "quantity": 1, "donation_amount": 1000, "cost_affordable": True,
        "available_attempts": 20, "attempt_capacity": MAX_AVAILABLE_ATTEMPTS,
        "game_day_id": "synthetic-day-1", "target_provenance": BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        "source_frame_sha256": "a" * 64, "evidence_refs": ("synthetic:alliance-donation",),
        "overlay_state": "none", "runtime_profile_id": ACTIVE_RUNTIME_PROFILE_ID, "recognized": True,
    }
    values.update(changes)
    return DonationObservation(**values)


def canonical_action(*, flow_id="alliance-donation-flow", status="confirmed", ordinal=1,
                     game_day_id="synthetic-day-1", resource=DONATION_RESOURCE, **changes):
    action = {
        "task_id": flow_id,
        "action_key": donation_action_key(account_id="account", server_id="server",
                                          game_day_id=game_day_id, ordinal=ordinal),
        "semantic_action": DONATION_ACTION, "source_state": ALLIANCE_TECH_SCREEN,
        "target_identity": DONATION_TARGET, "consequence": DONATION_CONSEQUENCE,
        "expected_postcondition": DONATION_POSTCONDITION, "game_day_id": game_day_id,
        "quantity": 1, "cost_type": "ordinary_resource", "cost_amount": 1000, "final_status": status,
    }
    request = {key: action[key] for key in ("task_id", "action_key", "semantic_action", "game_day_id")}
    request.update(
        action_class="spend_or_strategic", resource_or_currency=resource, maximum_cost=1000,
        observation={key: action[key] for key in (
            "source_state", "target_identity", "expected_postcondition", "consequence",
            "cost_type", "cost_amount", "quantity")},
        semantic_preconditions=[f"alliance_donation_game_day={game_day_id}",
                                f"alliance_donation_resource={resource}",
                                "alliance_donation_cost=1000", "alliance_donation_quantity=1"],
    )
    action["policy_request_json"] = json.dumps(request)
    action.update(changes)
    return action


def count(actions):
    return confirmed_donation_count(actions, flow_id="alliance-donation-flow", account_id="account",
                                    server_id="server", game_day_id="synthetic-day-1")


class AllianceDonationSemanticsTests(unittest.TestCase):
    def test_current_hot_short_numeric_names_and_stored_attempts_need_no_wallet_or_wait(self):
        for name in ("II", "A", "Tech 2"):
            self.assertTrue(donation_authorizeable(observation(
                tech_identity=name, available_attempts=3, next_attempt_available_in_seconds=1799), 0))

    def test_unknown_target_cost_or_nonordinary_control_fails_closed(self):
        for changes in (
            {"auto_hot_marker": False}, {"tech_identity": ""}, {"screen_state": "ALLIANCE_TECH_TREE"},
            {"target_identity": "alliance-tech:diamond-donate"}, {"donation_amount": None},
            {"cost_affordable": None}, {"available_attempts": None}, {"control_enabled": False},
            {"quantity": 2}, {"overlay_state": "unknown"}, {"available_attempts": 21},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(donation_disposition(observation(**changes), 0), DonationDisposition.BLOCKED)

    def test_attempt_exhaustion_and_red_cost_defer_without_credit(self):
        self.assertEqual(donation_disposition(observation(available_attempts=0), 2), DonationDisposition.NO_ATTEMPTS)
        self.assertEqual(donation_disposition(observation(cost_affordable=False), 4), DonationDisposition.INSUFFICIENT_RESOURCE)
        self.assertTrue(donation_authorizeable(observation(), 9))
        self.assertEqual(donation_disposition(observation(), 10), DonationDisposition.DAILY_TARGET_REACHED)
        self.assertEqual(donation_disposition(observation(), 11), DonationDisposition.BLOCKED)

    def test_attempt_counter_alone_proves_one_action_not_bonus_or_wallet_arithmetic(self):
        before = observation()
        self.assertTrue(donation_postcondition_verified(before, observation(available_attempts=19), elapsed_seconds=1.0))
        self.assertFalse(donation_postcondition_verified(before, observation(available_attempts=18), elapsed_seconds=1.0))
        self.assertFalse(donation_postcondition_verified(before, before, elapsed_seconds=1.0))
        self.assertTrue(donation_postcondition_verified(before, observation(
            available_attempts=19, tech_identity="new HOT 2", cost_affordable=False), elapsed_seconds=1.0))
        # The observed Bonus x2 animation can cover the title, but the HOT panel and
        # attempt decrement still prove the sent action. Missing title cannot authorize another.
        obscured = observation(available_attempts=19, tech_identity="")
        self.assertTrue(donation_postcondition_verified(before, obscured, elapsed_seconds=1.0))
        self.assertFalse(donation_authorizeable(obscured))

    def test_positive_regeneration_rollover_reconciles_unchanged_counter_without_waiting(self):
        before = observation(available_attempts=10, next_attempt_available_in_seconds=1)
        after = observation(available_attempts=10, next_attempt_available_in_seconds=1799)
        self.assertTrue(donation_postcondition_verified(before, after, elapsed_seconds=2.0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, available_attempts=9), elapsed_seconds=2.0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, available_attempts=11), elapsed_seconds=2.0))
        self.assertFalse(donation_postcondition_verified(replace(before, next_attempt_available_in_seconds=1000),
                                                        after, elapsed_seconds=2.0))
        self.assertFalse(donation_postcondition_verified(before, after, elapsed_seconds=None))
        self.assertFalse(donation_postcondition_verified(before, after, elapsed_seconds=1800.0))

    def test_countdown_ticks_and_new_timer_after_cap_do_not_imply_a_refill(self):
        before = observation(available_attempts=3, next_attempt_available_in_seconds=100)
        after = observation(available_attempts=2, next_attempt_available_in_seconds=99)
        self.assertTrue(donation_postcondition_verified(before, after, elapsed_seconds=1.0))
        self.assertFalse(donation_postcondition_verified(before, replace(after, available_attempts=3), elapsed_seconds=1.0))
        self.assertTrue(donation_postcondition_verified(observation(), observation(
            available_attempts=19, next_attempt_available_in_seconds=1800), elapsed_seconds=1.0))

    def test_action_keys_are_stable_unique_reset_scoped_ordinals(self):
        first = donation_action_key(account_id="account", server_id="server", game_day_id="day", ordinal=1)
        self.assertEqual(first, donation_action_key(account_id="account", server_id="server", game_day_id="day", ordinal=1))
        self.assertNotEqual(first, donation_action_key(account_id="account", server_id="server", game_day_id="day", ordinal=2))
        with self.assertRaises(ValueError):
            donation_action_key(account_id="account", server_id="server", game_day_id="day", ordinal=11)

    def test_confirmed_prefix_survives_restart_and_old_journal_resource_contract(self):
        self.assertEqual(count([canonical_action(ordinal=1, resource="STEEL"), canonical_action(ordinal=2),
                                canonical_action(ordinal=1, game_day_id="synthetic-day-0")]), 2)
        self.assertEqual(count([canonical_action(status="cancelled")]), 0)
        self.assertEqual(count([canonical_action(ordinal=n) for n in range(1, 11)]), MAX_DONATIONS_PER_RESET)

    def test_unknown_duplicate_or_gapped_history_cannot_credit_or_retry(self):
        for actions in ([canonical_action(status="input_sent")], [canonical_action(status="unresolved")],
                        [canonical_action(ordinal=2)], [canonical_action(), canonical_action()],
                        [canonical_action(resource="DIAMOND")]):
            with self.subTest(actions=actions), self.assertRaises(DonationActionReconciliationError):
                count(actions)


if __name__ == "__main__":
    unittest.main()
