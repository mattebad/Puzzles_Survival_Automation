from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.daily_nanoweapon import (
    DailyNanoweaponObservation,
    daily_nanoweapon_authorizeable,
    daily_nanoweapon_postcondition_verified,
    daily_nanoweapon_replay,
    daily_nanoweapon_transaction_spec,
)
from tasks.nanoweapon import NanoweaponObservation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_nanoweapon_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_nanoweapon(name: str) -> NanoweaponObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return NanoweaponObservation(**payload)


def load_pair() -> tuple[DailyNanoweaponObservation, DailyNanoweaponObservation]:
    before = DailyNanoweaponObservation(
        selected_daily_row=True,
        objective_key="craft_nanoweapon",
        daily_progress_before=0,
        nanoweapon=load_nanoweapon("normal_craft_synthetic"),
    )
    after = DailyNanoweaponObservation(
        selected_daily_row=True,
        objective_key="craft_nanoweapon",
        daily_progress_before=0,
        daily_progress_after=1,
        successor_state="DAILY_NANOWEAPON_COMPLETE",
        nanoweapon=replace(
            before.nanoweapon,
            nano_parts=0,
            craft_count=1,
            craft_result_visible=True,
            result_identity="Nano Spear",
        ),
    )
    return before, after


class DailyNanoweaponContractTests(unittest.TestCase):
    def test_selected_daily_row_and_exact_craft_are_required(self):
        before, _ = load_pair()
        self.assertTrue(daily_nanoweapon_authorizeable(before))
        spec = daily_nanoweapon_transaction_spec(before)
        self.assertEqual(spec.action_kind, "CRAFT_NANOWEAPON_NORMAL")
        self.assertFalse(spec.free_only)
        self.assertEqual(spec.maximum_cost, 100)
        self.assertEqual(spec.resource_or_currency, "NANO_PARTS")
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "upgrade_building"},
            {"daily_progress_before": 1},
            {
                "nanoweapon": replace(
                    before.nanoweapon, selected_tab="MATERIAL_PRODUCTION"
                )
            },
        ):
            self.assertFalse(daily_nanoweapon_authorizeable(replace(before, **changes)))

    def test_one_craft_successor_proves_daily_completion(self):
        before, after = load_pair()
        self.assertTrue(daily_nanoweapon_postcondition_verified(before, after))
        self.assertFalse(
            daily_nanoweapon_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )
        self.assertFalse(
            daily_nanoweapon_postcondition_verified(
                before,
                replace(
                    after,
                    nanoweapon=replace(after.nanoweapon, game_day_id="next-day"),
                ),
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, after = load_pair()
        pending = daily_nanoweapon_replay(before)
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        done = daily_nanoweapon_replay(before, after)
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-nanoweapon:completed")

    def test_main_and_static_inputs_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_nanoweapon_authorizeable(replace(before, selected_daily_row=False))
        )
        self.assertFalse(
            daily_nanoweapon_authorizeable(
                replace(
                    before,
                    nanoweapon=load_nanoweapon("static_reference_negative"),
                )
            )
        )

    def test_matrix_keeps_nanoweapon_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "craft_nanoweapon"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
