from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.gathering import (
    SUPPORTED_VARIANTS,
    GatheringObservation,
    gathering_authorizeable,
    gathering_perform_one_pulse,
    gathering_postcondition_verified,
    gathering_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_gathering_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> GatheringObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return GatheringObservation(**payload)


class GatheringContractTests(unittest.TestCase):
    def test_exact_three_variant_family_and_ownership(self):
        self.assertEqual(set(SUPPORTED_VARIANTS), {"wood", "steel", "gas"})
        for variant in SUPPORTED_VARIANTS:
            observation = load_fixture(f"{variant}_valid")
            self.assertTrue(gathering_authorizeable(observation, variant=variant))
            for other_variant in SUPPORTED_VARIANTS:
                if other_variant != variant:
                    self.assertFalse(
                        gathering_authorizeable(observation, variant=other_variant)
                    )

    def test_transaction_spec_binds_node_resource_and_march(self):
        observation = load_fixture("wood_valid")
        spec = gathering_transaction_spec(observation, variant="wood")
        self.assertEqual(spec.action_kind, "GATHER_RESOURCE")
        self.assertEqual(spec.subject, "wood-node-17")
        self.assertEqual(spec.quantity, 1)
        self.assertIn("exact_wood_node", spec.semantic_preconditions)
        self.assertIn("available_march_slot", spec.semantic_preconditions)
        self.assertIsNone(spec.maximum_cost)
        with self.assertRaises(ValueError):
            gathering_transaction_spec(observation, variant="gas")

    def test_successor_requires_positive_progress_and_bound_node(self):
        before = load_fixture("wood_valid")
        after = replace(
            before,
            successor_state="MARCHES",
            daily_progress_after=1000,
            outbound_march_identity=before.node_identity,
        )
        self.assertTrue(gathering_postcondition_verified(before, after, variant="wood"))
        self.assertEqual(
            gathering_perform_one_pulse(before, after, variant="wood").outcome,
            TaskOutcome.DONE,
        )
        self.assertFalse(
            gathering_postcondition_verified(
                before,
                replace(after, daily_progress_after=before.daily_progress_before),
                variant="wood",
            )
        )
        self.assertFalse(
            gathering_postcondition_verified(
                before, replace(after, node_identity="wood-node-other"), variant="wood"
            )
        )
        self.assertFalse(
            gathering_postcondition_verified(
                before, replace(after, game_day_id="synthetic-day-2"), variant="wood"
            )
        )

    def test_node_march_and_target_guards_fail_closed(self):
        observation = load_fixture("wood_valid")
        changes = (
            {"selected_daily_row": False},
            {"node_unoccupied": False},
            {"node_not_targeted": False},
            {"node_not_already_marched": False},
            {"march_slot_available": False},
            {"active_march_count": 3},
            {"march_capacity": 0},
            {"formation_identity": ""},
            {"march_duration_seconds": None},
            {"march_duration_budget_seconds": 899},
            {"node_level": None},
            {"action_target_identity": "gather-resource:steel"},
            {"control_class": "ATTACK"},
            {"overlay_state": "unknown"},
            {"target_provenance": "gnbots-reference"},
        )
        for change in changes:
            self.assertFalse(gathering_authorizeable(replace(observation, **change), variant="wood"))

    def test_main_food_and_static_provenance_are_not_admitted(self):
        observation = load_fixture("wood_valid")
        self.assertFalse(
            gathering_authorizeable(
                replace(observation, screen_state="MAIN_QUEST", selected_world=False),
                variant="wood",
            )
        )
        with self.assertRaises(ValueError):
            gathering_authorizeable(observation, variant="food")
        self.assertFalse(
            gathering_authorizeable(
                replace(observation, target_provenance="gnbots-reference"),
                variant="wood",
            )
        )

    def test_pulse_is_pure_and_matrix_stays_unregistered(self):
        observation = load_fixture("wood_valid")
        result = gathering_perform_one_pulse(observation, variant="wood")
        self.assertEqual(result.outcome, TaskOutcome.PROGRESS)
        self.assertIsNone(result.completion_key)
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        rows = {
            row["objective_key"]: row
            for row in matrix["objectives"]
            if row["objective_key"] in {"gather_wood", "gather_steel", "gather_gas"}
        }
        self.assertEqual(set(rows), {"gather_wood", "gather_steel", "gather_gas"})
        for row in rows.values():
            self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
            self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
