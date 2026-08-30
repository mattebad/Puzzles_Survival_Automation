from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.bioenhancer import BioenhancerObservation
from tasks.contracts import TaskOutcome
from tasks.daily_bioenhancer import (
    DailyBioenhancerObservation,
    daily_bioenhancer_authorizeable,
    daily_bioenhancer_postcondition_verified,
    daily_bioenhancer_replay,
    daily_bioenhancer_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_bioenhancer_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_bioenhancer(name: str) -> BioenhancerObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return BioenhancerObservation(**payload)


def load_pair() -> tuple[DailyBioenhancerObservation, DailyBioenhancerObservation]:
    before = DailyBioenhancerObservation(
        selected_daily_row=True,
        objective_key="bioenhancer_research",
        daily_progress_before=0,
        bioenhancer=load_bioenhancer("free_synthetic"),
    )
    after = DailyBioenhancerObservation(
        selected_daily_row=True,
        objective_key="bioenhancer_research",
        daily_progress_before=0,
        daily_progress_after=1,
        successor_state="DAILY_BIOENHANCER_COMPLETE",
        bioenhancer=replace(
            before.bioenhancer,
            research_count=1,
            research_result_visible=True,
            result_identity="Bioenhancer Research",
        ),
    )
    return before, after


class DailyBioenhancerContractTests(unittest.TestCase):
    def test_selected_daily_row_and_free_research_are_required(self):
        before, _ = load_pair()
        self.assertTrue(daily_bioenhancer_authorizeable(before))
        spec = daily_bioenhancer_transaction_spec(before)
        self.assertEqual(spec.action_kind, "RESEARCH_BIOENHANCER_FREE")
        self.assertTrue(spec.free_only)
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "personal_might_praise"},
            {"daily_progress_before": 1},
            {
                "bioenhancer": load_bioenhancer("paid_negative"),
            },
        ):
            self.assertFalse(daily_bioenhancer_authorizeable(replace(before, **changes)))

    def test_one_research_successor_proves_daily_completion(self):
        before, after = load_pair()
        self.assertTrue(daily_bioenhancer_postcondition_verified(before, after))
        self.assertFalse(
            daily_bioenhancer_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )
        self.assertFalse(
            daily_bioenhancer_postcondition_verified(
                before,
                replace(after, successor_state="DAILY_BIOENHANCER_PENDING"),
            )
        )
        self.assertFalse(
            daily_bioenhancer_postcondition_verified(
                before,
                replace(
                    after,
                    bioenhancer=replace(after.bioenhancer, game_day_id="next-day"),
                ),
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, after = load_pair()
        pending = daily_bioenhancer_replay(before)
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        done = daily_bioenhancer_replay(before, after)
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-bioenhancer:completed")

    def test_main_and_static_inputs_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_bioenhancer_authorizeable(replace(before, selected_daily_row=False))
        )
        self.assertFalse(
            daily_bioenhancer_authorizeable(
                replace(
                    before,
                    bioenhancer=load_bioenhancer("static_reference_negative"),
                )
            )
        )

    def test_matrix_keeps_retained_bioenhancer_evidence_non_accepting(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "bioenhancer_research"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["live_validation_status"], "EVIDENCE_MISSING")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["authoritative_status"], "BIOENHANCER_CURRENT_PROOF_REQUIRED")
        self.assertEqual(row["execution_validation_status"], "OFFLINE_CONTRACT_VALIDATED_ONLY")
        self.assertEqual(row["daily_reconciliation_validation_status"], "HISTORICAL_NON_ACCEPTING")
        self.assertEqual(
            row["research_action_status"],
            "HISTORICAL_RESEARCH_RETAINED_NOT_CURRENT_ACCEPTANCE",
        )
        self.assertEqual(
            row["daily_reconciliation_status"],
            "CURRENT_DAILY_RECONCILIATION_EVIDENCE_REQUIRED",
        )
        self.assertEqual(row["daily_reconciliation_outcome"], "NOT_CURRENTLY_PROVEN")
        self.assertEqual(row["consequential_dispatch_count"], 2)
        self.assertEqual(
            row["consequential_dispatch_count_scope"],
            "retained_historical_evidence_only",
        )
        self.assertEqual(row["research_10x_dispatch_count"], 0)
        self.assertEqual(row["lease_release_status"], "EXPIRED_BY_POLICY")
        self.assertEqual(row["claim_execution_status"], "NOT_PERFORMED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])
        self.assertEqual(
            row["non_repeatable_actions"],
            ["bioenhancer-free-1784069057", "bioenhancer-free-1784079616"],
        )
        self.assertEqual(row["next_atomic_backlog_task"], "DQ-CLAIM-DAILY")


if __name__ == "__main__":
    unittest.main()
