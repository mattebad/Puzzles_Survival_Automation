from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.resource_boost_disabled import (
    ResourceBoostObservation,
    resource_boost_authorizeable,
    resource_boost_disabled_dispatch,
    resource_boost_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_resource_boost_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> ResourceBoostObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return ResourceBoostObservation(**payload)


class DisabledResourceBoostContractTests(unittest.TestCase):
    def test_resource_building_identity_and_duration_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(resource_boost_authorizeable(observation))
        for changes in (
            {"building_identity": ""},
            {"resource_identity": ""},
            {"resource_type": "UNKNOWN"},
            {"target_identity": "generic-boost"},
            {"boost_duration_minutes": 0},
            {"cost_known": False},
            {"resource_balance_before": 0},
            {"boost_active_before": True},
        ):
            self.assertFalse(resource_boost_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_source_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(resource_boost_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"recognized": False},
        ):
            self.assertFalse(resource_boost_authorizeable(replace(observation, **changes)))

    def test_boost_successor_is_offline_state_and_progress_replay_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            boost_active_after=True,
            boost_duration_after=60,
            daily_progress_after=1,
            boost_confirmed=True,
            successor_state="BOOST_RECONCILED",
        )
        self.assertTrue(resource_boost_postcondition_verified(before, after))
        self.assertFalse(
            resource_boost_postcondition_verified(
                before, replace(after, boost_duration_after=59)
            )
        )
        self.assertFalse(
            resource_boost_postcondition_verified(
                before, replace(after, building_identity="other-building")
            )
        )
        self.assertFalse(
            resource_boost_postcondition_verified(
                before, replace(after, daily_progress_after=2)
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = resource_boost_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "RESOURCE_BOOST_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_resource_boost_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "boost_resource_building_output"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
