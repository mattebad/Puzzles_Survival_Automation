from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import supply_depot_bluestacks


class SupplyDepotBlueStacksRouteTests(unittest.TestCase):
    def test_collect_one_is_dry_run_and_issues_no_input_by_default(self):
        output = StringIO()
        with patch.object(supply_depot_bluestacks.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must not connect")):
            with redirect_stdout(output):
                code = supply_depot_bluestacks.main(["collect-one"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["config"]["maximum_free_collections_per_run"], 1)
        self.assertFalse(payload["config"]["quest_go_fallback_enabled"])
        self.assertFalse(payload["config"]["production_registration_enabled"])
        self.assertFalse(payload["config"]["scheduler_eligible"])

    def test_action_ledger_blocks_duplicate_semantic_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = {}
            supply_depot_bluestacks._record_ledger(path, ledger, "attempts-9-food", status="unresolved")
            loaded = supply_depot_bluestacks._load_ledger(path)
            self.assertIn("attempts-9-food", loaded)
            self.assertEqual(loaded["attempts-9-food"]["status"], "unresolved")

    def test_collect_free_hold_is_dry_run_and_issues_no_input_by_default(self):
        output = StringIO()
        with patch.object(supply_depot_bluestacks.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must not connect")):
            with redirect_stdout(output):
                code = supply_depot_bluestacks.main(["collect-free-hold"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["config"]["reward_kind"], "food")
        self.assertEqual(payload["config"]["maximum_free_collections_per_hold"], 10)
        self.assertFalse(payload["config"]["quest_go_fallback_enabled"])
        self.assertFalse(payload["config"]["production_registration_enabled"])
        self.assertFalse(payload["config"]["scheduler_eligible"])

    def test_primary_collect_free_command_uses_hold_workflow(self):
        output = StringIO()
        with patch.object(supply_depot_bluestacks.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must not connect")):
            with redirect_stdout(output):
                code = supply_depot_bluestacks.main(["collect-free"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["config"]["reward_kind"], "food")
        self.assertEqual(payload["config"]["maximum_free_collections_per_hold"], 10)

    def test_reconcile_free_hold_is_dry_run_and_issues_no_input_by_default(self):
        output = StringIO()
        with patch.object(supply_depot_bluestacks.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must not connect")):
            with redirect_stdout(output):
                code = supply_depot_bluestacks.main(["reconcile-free-hold"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry_run")

    def test_return_home_is_dry_run_and_issues_no_input_by_default(self):
        output = StringIO()
        with patch.object(supply_depot_bluestacks.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must not connect")):
            with redirect_stdout(output):
                code = supply_depot_bluestacks.main(["return-home", "--atlas", "unused.json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry_run")


if __name__ == "__main__":
    unittest.main()
