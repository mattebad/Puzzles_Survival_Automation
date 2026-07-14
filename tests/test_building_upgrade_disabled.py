from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.building_upgrade_disabled import (
    BuildingUpgradeObservation,
    building_upgrade_authorizeable,
    building_upgrade_disabled_dispatch,
    building_upgrade_postcondition_verified,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_disabled_building_upgrade_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_fixture(name: str) -> BuildingUpgradeObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return BuildingUpgradeObservation(**payload)


class DisabledBuildingUpgradeContractTests(unittest.TestCase):
    def test_generic_identity_is_valid_and_vehicle_depot_is_main_only(self):
        observation = load_fixture("generic_valid")
        self.assertTrue(building_upgrade_authorizeable(observation))
        self.assertFalse(
            building_upgrade_authorizeable(load_fixture("vehicle_depot_main_negative"))
        )
        for identity in ("Vehicle Depot", "vehicle depot", "vehicle_depot"):
            self.assertFalse(
                building_upgrade_authorizeable(
                    replace(observation, building_identity=identity)
                )
            )

    def test_disabled_policy_blocks_valid_generic_upgrade(self):
        result = building_upgrade_disabled_dispatch(load_fixture("generic_valid"))
        self.assertEqual(result.outcome, TaskOutcome.BLOCKED)
        self.assertEqual(result.reason, "BUILDING_UPGRADE_DISABLED_POLICY")
        self.assertEqual(result.details["dispatch_count"], 0)
        self.assertIsNone(result.completion_key)

    def test_level_successor_is_offline_arithmetic_only(self):
        before = load_fixture("generic_valid")
        after = replace(
            before,
            current_level=11,
            target_level=12,
            current_level_after=11,
            daily_progress_after=1,
            successor_state="LEVEL_RECONCILED",
        )
        self.assertTrue(building_upgrade_postcondition_verified(before, after))
        self.assertFalse(
            building_upgrade_postcondition_verified(
                before, replace(after, current_level=12)
            )
        )
        self.assertFalse(
            building_upgrade_postcondition_verified(
                before, replace(after, building_identity="warehouse-beta")
            )
        )
        self.assertFalse(
            building_upgrade_postcondition_verified(
                before, replace(after, game_day_id="synthetic-day-2")
            )
        )

    def test_identity_cost_queue_and_source_guards_fail_closed(self):
        observation = load_fixture("generic_valid")
        changes = (
            {"selected_daily_row": False},
            {"objective_key": "upgrade_tech"},
            {"building_identity": ""},
            {"current_level": None},
            {"target_level": 12},
            {"target_identity": "upgrade-tech"},
            {"control_class": "BUILD"},
            {"upgrade_control_visible": False},
            {"queue_empty": False},
            {"cost_known": False},
            {"cost_resource": ""},
            {"cost_amount": 0},
            {"resource_balance": 100},
            {"daily_progress_before": 1},
            {"overlay_state": "unknown"},
            {"reset_guard_active": True},
            {"target_provenance": "gnbots-reference"},
        )
        for change in changes:
            self.assertFalse(building_upgrade_authorizeable(replace(observation, **change)))

    def test_matrix_keeps_generic_building_upgrade_disabled_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "upgrade_building"
        )
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
