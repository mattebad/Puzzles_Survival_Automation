from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.daily_recruitment import (
    DailyRecruitmentObservation,
    daily_recruitment_authorizeable,
    daily_recruitment_postcondition_verified,
    daily_recruitment_replay,
    daily_recruitment_transaction_spec,
)
from tasks.free_recruitment import FreeRecruitmentObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_daily_recruitment_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_free(payload: dict) -> FreeRecruitmentObservation:
    payload = dict(payload)
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return FreeRecruitmentObservation(**payload)


def load_observations() -> tuple[
    DailyRecruitmentObservation, tuple[DailyRecruitmentObservation, ...]
]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    before_payload = payload["before"]
    before = DailyRecruitmentObservation(
        selected_daily_row=before_payload["selected_daily_row"],
        objective_key=before_payload["objective_key"],
        daily_progress_before=before_payload["daily_progress_before"],
        tavern=load_free(before_payload["tavern"]),
    )
    successors = tuple(
        DailyRecruitmentObservation(
            selected_daily_row=item["selected_daily_row"],
            objective_key=item["objective_key"],
            daily_progress_before=item["daily_progress_after"] - 1,
            daily_progress_after=item["daily_progress_after"],
            successor_state=item["successor_state"],
            tavern=load_free(item["tavern"]),
        )
        for item in payload["successors"]
    )
    return before, successors


class DailyRecruitmentContractTests(unittest.TestCase):
    def test_selected_daily_row_and_free_tavern_identity_are_required(self):
        before, _ = load_observations()
        self.assertTrue(daily_recruitment_authorizeable(before))
        spec = daily_recruitment_transaction_spec(before)
        self.assertEqual(spec.action_kind, "RECRUIT_FREE")
        self.assertTrue(spec.free_only)
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "personal_might_praise"},
            {"daily_progress_before": 5},
            {"tavern": replace(before.tavern, recruitment_mode="TEN_X")},
        ):
            self.assertFalse(
                daily_recruitment_authorizeable(replace(before, **changes))
            )

    def test_five_count_requires_exact_one_pulse_successors(self):
        before, successors = load_observations()
        self.assertTrue(daily_recruitment_postcondition_verified(before, successors))
        self.assertFalse(daily_recruitment_postcondition_verified(before, successors[:-1]))
        self.assertFalse(
            daily_recruitment_postcondition_verified(
                before,
                successors[:2] + (replace(successors[2], daily_progress_after=5),) + successors[3:],
            )
        )
        self.assertFalse(
            daily_recruitment_postcondition_verified(
                before,
                successors[:2]
                + (replace(
                    successors[2],
                    tavern=replace(successors[2].tavern, recruitment_count=9),
                ),)
                + successors[3:],
            )
        )

    def test_dispatch_cardinality_and_claim_separation(self):
        before, successors = load_observations()
        result = daily_recruitment_replay(before)
        self.assertEqual(result.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertEqual(result.details["required_pulses"], 5)
        result = daily_recruitment_replay(before, successors)
        self.assertEqual(result.outcome, TaskOutcome.DONE)
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertEqual(result.completion_key, "daily-recruitment:completed")

    def test_main_negative_and_ambiguous_successor_fail_closed(self):
        before, successors = load_observations()
        self.assertFalse(
            daily_recruitment_authorizeable(
                replace(before, selected_daily_row=False)
            )
        )
        self.assertFalse(
            daily_recruitment_postcondition_verified(
                before,
                successors[:1]
                + (replace(successors[1], tavern=replace(successors[1].tavern, unknown_confirmation=True)),)
                + successors[2:],
            )
        )

    def test_matrix_keeps_recruitment_unregistered_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "recruit_noahs_tavern"
        )
        self.assertEqual(row["implementation_status"], "DORMANT_REFERENCE_IMPLEMENTATION")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
