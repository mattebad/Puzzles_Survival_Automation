from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.daily_zombie_lair import (
    DailyZombieLairObservation,
    daily_zombie_lair_authorizeable,
    daily_zombie_lair_postcondition_verified,
    daily_zombie_lair_replay,
    daily_zombie_lair_transaction_spec,
)
from tasks.zombie_lair import ZombieLairObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_zombie_lair_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_lair(name: str) -> ZombieLairObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return ZombieLairObservation(**payload)


def load_pair() -> tuple[DailyZombieLairObservation, DailyZombieLairObservation]:
    before = DailyZombieLairObservation(
        selected_daily_row=True,
        objective_key="defeat_zombie_lair",
        daily_progress_before=0,
        lair=load_lair("lair_synthetic"),
    )
    after = DailyZombieLairObservation(
        selected_daily_row=True,
        objective_key="defeat_zombie_lair",
        daily_progress_before=0,
        daily_progress_after=1,
        successor_state="DAILY_ZOMBIE_LAIR_COMPLETE",
        lair=replace(
            before.lair,
            stamina_before=60,
            defeat_confirmed=True,
        ),
    )
    return before, after


class DailyZombieLairContractTests(unittest.TestCase):
    def test_selected_daily_lair_identity_and_stamina_are_required(self):
        before, _ = load_pair()
        self.assertTrue(daily_zombie_lair_authorizeable(before))
        spec = daily_zombie_lair_transaction_spec(before)
        self.assertEqual(spec.action_kind, "JOIN_ZOMBIE_LAIR")
        self.assertEqual(spec.subject, "lair-level-1")
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "consume_stamina"},
            {"daily_progress_before": 1},
            {"lair": replace(before.lair, lair_level=60)},
            {"lair": replace(before.lair, stamina_budget=19)},
        ):
            self.assertFalse(daily_zombie_lair_authorizeable(replace(before, **changes)))

    def test_exact_lair_successor_proves_daily_completion(self):
        before, after = load_pair()
        self.assertTrue(daily_zombie_lair_postcondition_verified(before, after))
        self.assertFalse(
            daily_zombie_lair_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )
        self.assertFalse(
            daily_zombie_lair_postcondition_verified(
                before,
                replace(after, lair=replace(after.lair, stamina_before=59)),
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, after = load_pair()
        pending = daily_zombie_lair_replay(before)
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        done = daily_zombie_lair_replay(before, after)
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-zombie-lair:completed")

    def test_main_static_and_combat_inputs_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_zombie_lair_authorizeable(
                replace(
                    before,
                    selected_daily_row=False,
                    lair=load_lair("main_negative"),
                )
            )
        )
        self.assertFalse(
            daily_zombie_lair_authorizeable(
                replace(
                    before,
                    lair=load_lair("static_reference_negative"),
                )
            )
        )
        self.assertFalse(
            daily_zombie_lair_authorizeable(
                replace(
                    before,
                    lair=replace(before.lair, combat_mode_visible=True),
                )
            )
        )

    def test_matrix_keeps_lair_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "defeat_zombie_lair"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
