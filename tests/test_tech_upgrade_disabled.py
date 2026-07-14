from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.tech_upgrade_disabled import (
    TechUpgradeObservation,
    tech_upgrade_authorizeable,
    tech_upgrade_disabled_dispatch,
    tech_upgrade_postcondition_verified,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_tech_upgrade_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> TechUpgradeObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return TechUpgradeObservation(**payload)


class DisabledTechUpgradeContractTests(unittest.TestCase):
    def test_prerequisites_and_tech_identity_are_required(self):
        observation = load_fixture("valid")
        self.assertTrue(tech_upgrade_authorizeable(observation))
        for changes in (
            {"tech_identity": ""},
            {"prerequisites_met": False},
            {"target_identity": "tech-other"},
            {"research_queue_empty": False},
            {"cost_known": False},
        ):
            self.assertFalse(tech_upgrade_authorizeable(replace(observation, **changes)))

    def test_main_and_ambiguous_source_states_fail_closed(self):
        observation = load_fixture("valid")
        self.assertFalse(tech_upgrade_authorizeable(load_fixture("main_negative")))
        for changes in (
            {"selected_daily_row": False},
            {"screen_state": "MAIN_QUEST"},
            {"target_provenance": "gnbots-reference"},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"resource_balance": 999},
        ):
            self.assertFalse(tech_upgrade_authorizeable(replace(observation, **changes)))

    def test_level_successor_is_offline_arithmetic_only(self):
        before = load_fixture("valid")
        after = replace(
            before,
            current_level=5,
            target_level=6,
            current_level_after=5,
            daily_progress_after=1,
            successor_state="TECH_LEVEL_RECONCILED",
        )
        self.assertTrue(tech_upgrade_postcondition_verified(before, after))
        self.assertFalse(
            tech_upgrade_postcondition_verified(
                before, replace(after, current_level=6)
            )
        )
        self.assertFalse(
            tech_upgrade_postcondition_verified(
                before, replace(after, tech_identity="other-tech")
            )
        )
        self.assertFalse(
            tech_upgrade_postcondition_verified(
                before, replace(after, game_day_id="synthetic-day-2")
            )
        )

    def test_disabled_policy_blocks_dispatch_and_keeps_claim_separate(self):
        result = tech_upgrade_disabled_dispatch(load_fixture("valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "TECH_UPGRADE_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_matrix_keeps_tech_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "upgrade_tech"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
