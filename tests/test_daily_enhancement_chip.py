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
        objective_key="enhance_chip",
        daily_progress_before=0,
        enhancement=load_enhancement("chip_variant_negative"),
    )
    after = DailyEnhancementObservation(
        selected_daily_row=True,
        objective_key="enhance_chip",
        daily_progress_before=0,
        daily_progress_after=1,
        successor_state="DAILY_CHIP_ENHANCEMENT_COMPLETE",
        enhancement=replace(before.enhancement, item_level=5),
    )
    return before, after


class DailyChipEnhancementContractTests(unittest.TestCase):
    def test_chip_row_owns_chip_variant_and_rejects_gear(self):
        before, _ = load_pair()
        self.assertTrue(daily_enhancement_authorizeable(before, variant="chip"))
        spec = daily_enhancement_transaction_spec(before, variant="chip")
        self.assertEqual(spec.action_kind, "ENHANCE_CHIP")
        self.assertEqual(spec.subject, "commander-chip-1")
        self.assertFalse(daily_enhancement_authorizeable(before, variant="gear"))
        self.assertFalse(
            daily_enhancement_authorizeable(
                replace(before, objective_key="enhance_gear"), variant="chip"
            )
        )

    def test_chip_material_and_successor_guards_are_required(self):
        before, after = load_pair()
        self.assertTrue(
            daily_enhancement_postcondition_verified(before, after, variant="chip")
        )
        self.assertFalse(
            daily_enhancement_postcondition_verified(
                before,
                replace(
                    after,
                    enhancement=replace(
                        after.enhancement,
                        material_star=2,
                    ),
                ),
                variant="chip",
            )
        )
        self.assertFalse(
            daily_enhancement_postcondition_verified(
                before, replace(after, daily_progress_after=2), variant="chip"
            )
        )

    def test_replay_is_pure_and_dispatch_count_is_zero(self):
        before, after = load_pair()
        pending = daily_enhancement_replay(before, variant="chip")
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        done = daily_enhancement_replay(before, after, variant="chip")
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-enhancement:chip:completed")

    def test_main_and_static_inputs_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_enhancement_authorizeable(
                replace(
                    before,
                    selected_daily_row=False,
                    enhancement=load_enhancement("main_negative"),
                ),
                variant="chip",
            )
        )
        self.assertFalse(
            daily_enhancement_authorizeable(
                replace(
                    before,
                    enhancement=replace(
                        before.enhancement,
                        target_provenance="gnbots-static-reference",
                    ),
                ),
                variant="chip",
            )
        )

    def test_matrix_keeps_chip_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "enhance_chip"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
