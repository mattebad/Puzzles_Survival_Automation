from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.daily_enhancement import (
    DailyEnhancementObservation,
    daily_enhancement_authorizeable,
    daily_enhancement_postcondition_verified,
    daily_enhancement_replay,
    daily_enhancement_transaction_spec,
)
from tasks.enhancement import EnhancementObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_enhancement_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_enhancement(name: str) -> EnhancementObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return EnhancementObservation(**payload)


def load_pair() -> tuple[DailyEnhancementObservation, DailyEnhancementObservation]:
    before = DailyEnhancementObservation(
        selected_daily_row=True,
        objective_key="enhance_gear",
        daily_progress_before=0,
        enhancement=load_enhancement("gear_synthetic"),
    )
    after = DailyEnhancementObservation(
        selected_daily_row=True,
        objective_key="enhance_gear",
        daily_progress_before=0,
        daily_progress_after=1,
        successor_state="DAILY_GEAR_ENHANCEMENT_COMPLETE",
        enhancement=replace(before.enhancement, item_level=5),
    )
    return before, after


class DailyEnhancementContractTests(unittest.TestCase):
    def test_selected_daily_gear_row_and_shared_guards_are_required(self):
        before, _ = load_pair()
        self.assertTrue(daily_enhancement_authorizeable(before, variant="gear"))
        spec = daily_enhancement_transaction_spec(before, variant="gear")
        self.assertEqual(spec.action_kind, "ENHANCE_GEAR")
        self.assertEqual(spec.subject, "commander-gear-1")
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "enhance_chip"},
            {"daily_progress_before": 1},
            {
                "enhancement": replace(
                    before.enhancement,
                    selected_item_kind="CHIP",
                    selected_tab="CHIP",
                )
            },
        ):
            self.assertFalse(
                daily_enhancement_authorizeable(before, variant="gear")
                if changes == {}
                else daily_enhancement_authorizeable(
                    replace(before, **changes), variant="gear"
                )
            )

    def test_one_enhancement_successor_proves_daily_completion(self):
        before, after = load_pair()
        self.assertTrue(
            daily_enhancement_postcondition_verified(before, after, variant="gear")
        )
        self.assertFalse(
            daily_enhancement_postcondition_verified(
                before, replace(after, daily_progress_after=2), variant="gear"
            )
        )
        self.assertFalse(
            daily_enhancement_postcondition_verified(
                before,
                replace(
                    after,
                    enhancement=replace(
                        after.enhancement,
                        selected_item_identity="other-gear",
                    ),
                ),
                variant="gear",
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, after = load_pair()
        pending = daily_enhancement_replay(before, variant="gear")
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        done = daily_enhancement_replay(before, after, variant="gear")
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-enhancement:gear:completed")

    def test_main_static_and_wrong_variant_inputs_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_enhancement_authorizeable(
                replace(
                    before,
                    selected_daily_row=False,
                    enhancement=load_enhancement("main_negative"),
                ),
                variant="gear",
            )
        )
        self.assertFalse(
            daily_enhancement_authorizeable(
                replace(
                    before,
                    enhancement=load_enhancement("chip_variant_negative"),
                ),
                variant="gear",
            )
        )
        self.assertFalse(
            daily_enhancement_authorizeable(before, variant="chip")
        )

    def test_matrix_keeps_gear_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "enhance_gear"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
