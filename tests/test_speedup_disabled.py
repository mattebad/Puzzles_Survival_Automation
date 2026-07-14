from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.speedup_disabled import (
    SpeedupObservation,
    speedup_authorizeable,
    speedup_disabled_dispatch,
    speedup_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_speedup_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> SpeedupObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return SpeedupObservation(**payload)


class DisabledSpeedupContractTests(unittest.TestCase):
    def test_timer_item_and_180_minute_quantity_model_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(speedup_authorizeable(observation))
        for changes in (
            {"timer_identity": ""},
            {"timer_active": False},
            {"timer_seconds_before": 10799},
            {"item_identity": ""},
            {"item_known": False},
            {"item_quantity_before": 0},
            {"speedup_minutes": 60},
            {"premium_item": True},
        ):
            self.assertFalse(speedup_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_source_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(speedup_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(speedup_authorizeable(replace(observation, **changes)))

    def test_speedup_successor_is_offline_timer_and_item_arithmetic_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            timer_seconds_after=9200,
            item_quantity_after=1,
            daily_progress_after=1,
            speedup_confirmed=True,
            successor_state="SPEEDUP_RECONCILED",
        )
        self.assertTrue(speedup_postcondition_verified(before, after))
        self.assertFalse(
            speedup_postcondition_verified(
                before, replace(after, timer_seconds_after=9199)
            )
        )
        self.assertFalse(
            speedup_postcondition_verified(
                before, replace(after, item_identity="other-speedup")
            )
        )
        self.assertFalse(
            speedup_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = speedup_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "SPEEDUP_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_speedup_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "speedup_using_items"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
