from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.daily_supply_depot import (
    DailySupplyDepotObservation,
    daily_supply_depot_authorizeable,
    daily_supply_depot_postcondition_verified,
    daily_supply_depot_replay,
    daily_supply_depot_transaction_spec,
)
from tasks.supply_depot import SupplyDepotObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_supply_depot_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_supply(name: str) -> SupplyDepotObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return SupplyDepotObservation(**payload)


def load_observations() -> tuple[
    DailySupplyDepotObservation, tuple[DailySupplyDepotObservation, ...]
]:
    before = DailySupplyDepotObservation(
        selected_daily_row=True,
        objective_key="supply_depot",
        daily_progress_before=0,
        supply_depot=load_supply("free_synthetic"),
    )
    successors = tuple(
        DailySupplyDepotObservation(
            selected_daily_row=True,
            objective_key="supply_depot",
            daily_progress_before=index,
            daily_progress_after=index + 1,
            successor_state=(
                "DAILY_SUPPLY_DEPOT_COMPLETE"
                if index == 4
                else "DAILY_SUPPLY_DEPOT_PROGRESS"
            ),
            collection_confirmed=True,
            supply_depot=before.supply_depot,
        )
        for index in range(5)
    )
    return before, successors


class DailySupplyDepotContractTests(unittest.TestCase):
    def test_selected_daily_row_and_free_depot_identity_are_required(self):
        before, _ = load_observations()
        self.assertTrue(daily_supply_depot_authorizeable(before))
        spec = daily_supply_depot_transaction_spec(before)
        self.assertEqual(spec.action_kind, "COLLECT_SUPPLY_DEPOT_FREE")
        self.assertTrue(spec.free_only)
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "personal_might_praise"},
            {"daily_progress_before": 5},
            {"supply_depot": load_supply("premium_negative")},
        ):
            self.assertFalse(daily_supply_depot_authorizeable(replace(before, **changes)))

    def test_five_count_requires_exact_one_pulse_successors(self):
        before, successors = load_observations()
        self.assertTrue(daily_supply_depot_postcondition_verified(before, successors))
        self.assertFalse(daily_supply_depot_postcondition_verified(before, successors[:-1]))
        self.assertFalse(
            daily_supply_depot_postcondition_verified(
                before,
                successors[:2]
                + (replace(successors[2], daily_progress_after=5),)
                + successors[3:],
            )
        )
        self.assertFalse(
            daily_supply_depot_postcondition_verified(
                before,
                successors[:1]
                + (replace(successors[1], collection_confirmed=False),)
                + successors[2:],
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, successors = load_observations()
        pending = daily_supply_depot_replay(before)
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        self.assertEqual(pending.details["required_pulses"], 5)
        done = daily_supply_depot_replay(before, successors)
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-supply-depot:completed")

    def test_main_and_static_inputs_fail_closed(self):
        before, _ = load_observations()
        self.assertFalse(
            daily_supply_depot_authorizeable(replace(before, selected_daily_row=False))
        )
        self.assertFalse(
            daily_supply_depot_authorizeable(
                replace(
                    before,
                    supply_depot=load_supply("static_reference_negative"),
                )
            )
        )

    def test_matrix_keeps_supply_depot_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "supply_depot"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
