from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.supply_depot import (
    SupplyDepotObservation,
    supply_depot_authorizeable,
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

    def test_postcondition_requires_same_day_and_collection_change(self):
        before = load_fixture("free_synthetic")
        self.assertFalse(supply_depot_postcondition_verified(before, before))
        collected = replace(before, collection_ready=False, control_class="")
        self.assertTrue(supply_depot_postcondition_verified(before, collected))
        self.assertTrue(supply_depot_postcondition_verified(before, before, collection_confirmed=True))
        self.assertFalse(supply_depot_postcondition_verified(before, replace(collected, game_day_id="next-day")))

    def test_perform_one_pulse_is_pure_and_fail_safe(self):
        before = load_fixture("free_synthetic")
        prepared = supply_depot_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = supply_depot_perform_one_pulse(before, replace(before, collection_ready=False))
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "supply-depot:known-basic-supplies:collected")


if __name__ == "__main__":
    unittest.main()
