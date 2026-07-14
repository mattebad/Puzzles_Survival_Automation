from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.available_daily_claim import (
    AvailableDailyClaimObservation,
    available_daily_claim_authorizeable,
    available_daily_claim_perform_one_pulse,
    available_daily_claim_postcondition_verified,
    available_daily_claim_transaction_spec,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_daily_claim_observations.json"


def load_fixture(name: str) -> AvailableDailyClaimObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["row_bounds"] = tuple(payload["row_bounds"])
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return AvailableDailyClaimObservation(**payload)


class AvailableDailyClaimContractTests(unittest.TestCase):
    def test_generalized_contract_does_not_require_personal_might_catalog_alias(self):
        observation = load_fixture("generalized_contract_positive")
        self.assertEqual(observation.objective_key, "gather_food")
        self.assertTrue(available_daily_claim_authorizeable(observation))
        spec = available_daily_claim_transaction_spec(observation)
        self.assertEqual(spec.action_kind, "CLAIM_DAILY_QUEST")
        self.assertEqual(spec.subject, "Gather Food")
        self.assertTrue(spec.free_only)

    def test_go_and_static_reference_cases_fail_closed(self):
        self.assertFalse(available_daily_claim_authorizeable(load_fixture("go_negative")))
        self.assertFalse(available_daily_claim_authorizeable(load_fixture("static_reference_negative")))

    def test_exact_target_cost_and_visibility_guards_are_required(self):
        observation = load_fixture("generalized_contract_positive")
        for changes in (
            {"selected_daily_quest": False},
            {"target_identity": "generic-claim"},
            {"target_roi": (10, 10, 100, 80)},
            {"cost_type": "gems"},
            {"cost_amount": 1},
            {"quantity": 10},
            {"milestone_reward": True},
            {"clipped": True},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"game_day_id": None},
        ):
            self.assertFalse(available_daily_claim_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_same_objective_and_positive_change(self):
        before = load_fixture("generalized_contract_positive")
        self.assertFalse(available_daily_claim_postcondition_verified(before, before))
        disappeared = replace(before, target_identity="", control_class="", claim_fully_visible=False)
        self.assertTrue(available_daily_claim_postcondition_verified(before, disappeared, row_disappeared=True))
        self.assertTrue(available_daily_claim_postcondition_verified(before, before, points_before=5, points_after=6))
        self.assertFalse(available_daily_claim_postcondition_verified(before, replace(disappeared, objective_key="other"), row_disappeared=True))

    def test_perform_one_pulse_is_pure_and_does_not_dispatch(self):
        before = load_fixture("generalized_contract_positive")
        prepared = available_daily_claim_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        result = available_daily_claim_perform_one_pulse(
            before,
            replace(before, target_identity="", control_class="", claim_fully_visible=False),
            row_disappeared=True,
        )
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.completion_key, "daily-quest:gather_food:claimed")


if __name__ == "__main__":
    unittest.main()
