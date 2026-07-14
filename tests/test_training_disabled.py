from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.training_disabled import (
    SUPPORTED_VARIANTS,
    TrainingObservation,
    training_disabled_dispatch,
    training_queue_authorizeable,
    training_queue_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_training_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> TrainingObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return TrainingObservation(**payload)


class DisabledTrainingContractTests(unittest.TestCase):
    def test_exact_four_variants_keep_ownership_separate(self):
        self.assertEqual(
            set(SUPPORTED_VARIANTS), {"fighter", "rider", "shooter", "vehicle"}
        )
        for variant in SUPPORTED_VARIANTS:
            observation = load_fixture(f"{variant}_valid")
            self.assertTrue(training_queue_authorizeable(observation, variant=variant))
            for other_variant in SUPPORTED_VARIANTS:
                if other_variant != variant:
                    self.assertFalse(
                        training_queue_authorizeable(observation, variant=other_variant)
                    )

    def test_disabled_policy_blocks_valid_queue_observation(self):
        observation = load_fixture("fighter_valid")
        self.assertTrue(training_queue_authorizeable(observation, variant="fighter"))
        result = training_disabled_dispatch(observation, variant="fighter")
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "TRAINING_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_queue_postcondition_is_offline_arithmetic_only(self):
        before = load_fixture("fighter_valid")
        after = replace(
            before,
            queue_quantity_after=250,
            daily_progress_after=250,
            successor_state="QUEUE_RECONCILED",
        )
        self.assertTrue(training_queue_postcondition_verified(before, after, variant="fighter"))
        self.assertFalse(
            training_queue_postcondition_verified(
                before, replace(after, queue_quantity_after=249), variant="fighter"
            )
        )
        self.assertFalse(
            training_queue_postcondition_verified(
                before, replace(after, daily_progress_after=0), variant="fighter"
            )
        )
        self.assertFalse(
            training_queue_postcondition_verified(
                before, replace(after, game_day_id="synthetic-day-2"), variant="fighter"
            )
        )

    def test_unit_cost_queue_and_source_guards_fail_closed(self):
        observation = load_fixture("fighter_valid")
        changes = (
            {"selected_daily_row": False},
            {"unit_identity": "RIDER"},
            {"selected_facility": False},
            {"target_identity": "training-start:rider"},
            {"control_class": "UPGRADE"},
            {"training_control_visible": False},
            {"queue_quantity_before": 1001},
            {"requested_quantity": 10},
            {"queue_capacity": 100},
            {"queue_slot_available": False},
            {"unit_tier": None},
            {"cost_known": False},
            {"cost_resource": ""},
            {"cost_amount": 0},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"target_provenance": "gnbots-reference"},
        )
        for change in changes:
            self.assertFalse(
                training_queue_authorizeable(replace(observation, **change), variant="fighter")
            )

    def test_main_and_unsupported_variants_fail_closed(self):
        observation = load_fixture("fighter_valid")
        self.assertFalse(
            training_queue_authorizeable(
                replace(observation, screen_state="MAIN_QUEST", selected_daily_row=False),
                variant="fighter",
            )
        )
        with self.assertRaises(ValueError):
            training_queue_authorizeable(observation, variant="hero")

    def test_matrix_keeps_all_training_rows_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        expected = {"train_fighter", "train_rider", "train_shooter", "train_vehicle"}
        rows = {
            row["objective_key"]: row
            for row in matrix["objectives"]
            if row["objective_key"] in expected
        }
        self.assertEqual(set(rows), expected)
        for row in rows.values():
            self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
            self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
            self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
            self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
