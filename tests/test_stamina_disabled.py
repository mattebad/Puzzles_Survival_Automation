from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.stamina_disabled import (
    DisabledStaminaObservation,
    stamina_counter_authorizeable,
    stamina_counter_postcondition_verified,
    stamina_disabled_dispatch,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_stamina_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> DisabledStaminaObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return DisabledStaminaObservation(**payload)


class DisabledStaminaContractTests(unittest.TestCase):
    def test_daily_counter_replay_is_valid_but_not_action_authorization(self):
        observation = load_fixture("daily_counter_synthetic")
        self.assertTrue(stamina_counter_authorizeable(observation))
        result = stamina_disabled_dispatch(observation, requested_cost=20)
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "STAMINA_SPEND_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_counter_postcondition_is_arithmetic_only(self):
        before = load_fixture("daily_counter_synthetic")
        after = replace(before, current_stamina=60)
        self.assertTrue(
            stamina_counter_postcondition_verified(
                before, after, expected_delta=20
            )
        )
        self.assertFalse(
            stamina_counter_postcondition_verified(
                before, replace(after, current_stamina=59), expected_delta=20
            )
        )
        self.assertFalse(
            stamina_counter_postcondition_verified(
                before, replace(after, game_day_id="next-day"), expected_delta=20
            )
        )

    def test_main_static_and_uncertain_observations_fail_closed(self):
        self.assertFalse(
            stamina_counter_authorizeable(load_fixture("main_negative"))
        )
        self.assertFalse(
            stamina_counter_authorizeable(load_fixture("static_reference_negative"))
        )
        observation = load_fixture("daily_counter_synthetic")
        for changes in (
            {"objective_key": "defeat_zombie_lair"},
            {"current_stamina": -1},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
            {"target_roi": (10, 10, 100, 80)},
        ):
            self.assertFalse(stamina_counter_authorizeable(replace(observation, **changes)))

    def test_disabled_policy_blocks_every_positive_dispatch_request(self):
        observation = load_fixture("daily_counter_synthetic")
        for requested_cost in (1, 20, 80):
            result = stamina_disabled_dispatch(
                observation, requested_cost=requested_cost
            )
            self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
            self.assertEqual(result.reason, "STAMINA_SPEND_DISABLED_POLICY")
            self.assertEqual(result.details["dispatch_count"], 0)

    def test_matrix_keeps_stamina_unregistered_and_scheduler_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "consume_stamina"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
