from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.supply_depot import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_PROFILE_ID,
    SupplyDepotConfig,
    SupplyDepotHoldConfig,
    SupplyDepotObservation,
    supply_depot_authorizeable,
    supply_depot_hold_postcondition_verified,
    supply_depot_perform_one_pulse,
    supply_depot_postcondition_verified,
    supply_depot_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_supply_depot_observations.json"


def load_fixture(name: str) -> SupplyDepotObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return SupplyDepotObservation(**payload)


class SupplyDepotContractTests(unittest.TestCase):
    def test_free_known_non_premium_collection_is_exact(self):
        observation = load_fixture("free_synthetic")
        self.assertTrue(supply_depot_authorizeable(observation))
        spec = supply_depot_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "COLLECT_SUPPLY_DEPOT_FREE")
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)

    def test_bluestacks_profile_is_native_but_not_pooled_with_bliss(self):
        observation = replace(
            load_fixture("free_synthetic"),
            game_day_id=None,
            reset_identity_required=False,
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            runtime_profile_id=BLUESTACKS_PROFILE_ID,
            evidence_refs=(".local-captures/supply-depot/frame.png",),
        )
        self.assertTrue(supply_depot_authorizeable(observation))
        self.assertFalse(supply_depot_authorizeable(replace(observation, runtime_profile_id="pns-800x1280-v1")))

    def test_default_config_is_one_direct_collection_and_never_promoted(self):
        config = SupplyDepotConfig()
        self.assertTrue(config.enabled)
        self.assertEqual(config.maximum_free_collections_per_run, 1)
        self.assertTrue(config.direct_building_route_enabled)
        self.assertFalse(config.quest_go_fallback_enabled)
        self.assertFalse(config.daily_progress_verification)
        self.assertFalse(config.production_registration_enabled)
        self.assertFalse(config.scheduler_eligible)

    def test_hold_config_is_bounded_food_only_and_never_promoted(self):
        config = SupplyDepotHoldConfig()
        self.assertTrue(config.enabled)
        self.assertEqual(config.reward_kind, "food")
        self.assertEqual(config.maximum_free_collections_per_hold, 10)
        self.assertEqual(config.duration_ms(8), 11100)
        self.assertTrue(config.direct_building_route_enabled)
        self.assertFalse(config.quest_go_fallback_enabled)
        self.assertFalse(config.production_registration_enabled)
        self.assertFalse(config.scheduler_eligible)
        with self.assertRaises(ValueError):
            config.duration_ms(0)
        with self.assertRaises(ValueError):
            config.duration_ms(11)

    def test_premium_and_static_reference_cases_fail_closed(self):
        self.assertFalse(supply_depot_authorizeable(load_fixture("premium_negative")))
        self.assertFalse(supply_depot_authorizeable(load_fixture("static_reference_negative")))

    def test_target_reward_cost_and_safety_guards_are_required(self):
        observation = load_fixture("free_synthetic")
        for changes in (
            {"target_identity": "generic-collect"},
            {"target_roi": (10, 10, 100, 80)},
            {"known_reward": False},
            {"unknown_reward": True},
            {"cost_type": "gems"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"collection_ready": False},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
        ):
            self.assertFalse(supply_depot_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_day_and_positive_semantic_change(self):
        before = load_fixture("free_synthetic")
        self.assertFalse(supply_depot_postcondition_verified(before, before))
        collected = replace(before, collection_ready=False, control_class="")
        self.assertFalse(supply_depot_postcondition_verified(before, collected))
        reward_increased = replace(collected, reward_balance=101)
        before_with_balance = replace(before, reward_balance=100)
        self.assertTrue(supply_depot_postcondition_verified(before_with_balance, reward_increased))
        before_with_attempts = replace(before, daily_free_attempts=9)
        attempts_decreased = replace(collected, daily_free_attempts=8)
        self.assertTrue(supply_depot_postcondition_verified(before_with_attempts, attempts_decreased))
        self.assertFalse(supply_depot_postcondition_verified(before_with_attempts, replace(collected, daily_free_attempts=7)))
        self.assertTrue(supply_depot_postcondition_verified(before, before, collection_confirmed=True))
        self.assertFalse(supply_depot_postcondition_verified(before, replace(collected, game_day_id="next-day")))

    def test_hold_postcondition_requires_exact_exhaustion_of_observed_attempts(self):
        before = replace(
            load_fixture("free_synthetic"),
            reward_kind="food",
            daily_free_attempts=8,
            game_day_id=None,
            reset_identity_required=False,
            target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            runtime_profile_id=BLUESTACKS_PROFILE_ID,
            evidence_refs=(".local-captures/supply-depot/food-before.png",),
        )
        exhausted = replace(before, collection_ready=False, control_class="", daily_free_attempts=0)
        self.assertTrue(supply_depot_hold_postcondition_verified(before, exhausted, maximum_attempts=10))
        self.assertFalse(
            supply_depot_hold_postcondition_verified(
                before,
                replace(exhausted, daily_free_attempts=1),
                maximum_attempts=10,
            )
        )
        self.assertFalse(
            supply_depot_hold_postcondition_verified(
                replace(before, reward_kind="wood"),
                exhausted,
                maximum_attempts=10,
            )
        )

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("free_synthetic")
        prepared = supply_depot_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = supply_depot_perform_one_pulse(
            replace(before, daily_free_attempts=9),
            replace(before, collection_ready=False, daily_free_attempts=8),
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "supply-depot:known-basic-supplies:collected")


if __name__ == "__main__":
    unittest.main()
