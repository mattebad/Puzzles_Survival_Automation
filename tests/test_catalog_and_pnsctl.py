from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import pnsctl
from tasks.catalog import CATALOG_PATH, catalog_summary, load_catalog, objective_for_text
from tasks.daily_quest import AllianceHelpHandler, AllianceHelpObservation


class CatalogTests(unittest.TestCase):
    def test_retained_inventory_is_durable_and_complete(self):
        catalog = load_catalog()
        self.assertEqual(catalog_summary()["count"], len(catalog))
        self.assertEqual(objective_for_text("  Help   allies ").objective_key, "help_allies")
        self.assertEqual(objective_for_text("Gather Gas").progress_format, "current/1500")
        self.assertIsNone(objective_for_text("Gathered Food"))

    def test_disabled_consequences_are_explicit(self):
        by_key = {item.objective_key: item for item in load_catalog()}
        self.assertEqual(by_key["help_allies"].policy_mode, "supervised_zero_cost")
        self.assertEqual(by_key["help_allies"].implementation_status, "LIVE_VALIDATED")
        self.assertEqual(by_key["buy_box"].implementation_status, "DISABLED_POLICY")
        self.assertEqual(by_key["gather_wood"].consequence_class, "spend_or_strategic")

    def test_loader_rejects_row_without_selected_daily_provenance(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        raw["objectives"][0]["evidence_provenance"] = "planning-document.md"
        with patch("tasks.catalog._load_raw", return_value=raw):
            with self.assertRaisesRegex(ValueError, "selected-Daily provenance"):
                load_catalog()

    def test_catalog_names_aggregate_claim_as_sole_ordinary_owner(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        owner = raw["claim_ownership"]["ordinary_claim"]
        self.assertEqual(owner["product_record_id"], "aggregate_daily_claim")
        self.assertEqual(
            owner["execution_flow_id"],
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
        )
        self.assertTrue(owner["sole_owner"])
        self.assertEqual(owner["registration_state"], "NOT_REGISTERED")
        self.assertFalse(owner["scheduler_eligibility"])

    def test_catalog_praise_references_nova_without_selected_daily_prerequisite(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        objective = next(
            item for item in raw["objectives"] if item["objective_key"] == "personal_might_praise"
        )
        self.assertEqual(objective["product_record_id"], "nova_praise")
        self.assertFalse(objective["selected_daily_prerequisite"])


class OperatorCliTests(unittest.TestCase):
    def test_promoted_navigation_asset_manifest_hashes_match(self):
        root = Path(__file__).resolve().parents[1]
        asset_root = root / pnsctl.NAVIGATION_ASSET_ROOT
        manifest = json.loads((asset_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["width"], manifest["height"]), (800, 1280))
        self.assertEqual(len(manifest["assets"]), 14)
        for asset in manifest["assets"]:
            payload = (asset_root / asset["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), asset["sha256"])

    def test_local_operator_surface_remains_available(self):
        parser = pnsctl.parser()
        for command in (
            "development-session",
            "reconcile",
            "nova-praise-pulse",
            "noahs-tavern-nav",
            "noahs-tavern-recruit",
            "nova-praise-supervised-guard",
            "bluestacks",
            "automation-service",
        ):
            with self.subTest(command=command):
                self.assertIn(command, parser._subparsers._group_actions[0].choices)

    def test_removed_remote_commands_are_rejected(self):
        parser = pnsctl.parser()
        for command in (
            "preflight",
            "worker-start",
            "worker-status",
            "worker-stop",
            "adb-start",
            "launch",
            "capture",
            "observe",
            "navigate",
            "run-task",
            "test-focused",
            "test-full",
            "validate",
            "preserve-evidence",
            "evidence-status",
            "cleanup",
        ):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                parser.parse_args([command])

    def test_pnsctl_has_no_legacy_remote_transport_or_task_literals(self):
        source = Path(pnsctl.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "nas.local",
            "192.168.122.79",
            "PnS-BlissOS-PoC",
            "UNRAID_TEMP_",
            "plink",
            "pscp",
            "docker",
            "mvp_quest_to_claim",
            "MVP-QUEST-TO-CLAIM",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_removed_remote_implementation_symbols_are_absent(self):
        for symbol in (
            "OperatorConfig",
            "load_credentials",
            "run_remote",
            "run_pscp",
            "worker_start",
            "worker_status",
            "worker_stop",
            "adb_start",
            "navigate",
            "run_task",
            "test_command",
            "validate",
            "preserve_evidence",
            "evidence_status",
            "cleanup",
        ):
            with self.subTest(symbol=symbol):
                self.assertFalse(hasattr(pnsctl, symbol))


class HelpCompletionAttributionTests(unittest.TestCase):
    def _observation(self, **changes):
        values = dict(
            screen_state="DAILY_QUEST",
            objective_name="Help allies",
            current_progress=0,
            required_progress=10,
        )
        values.update(changes)
        return AllianceHelpObservation(**values)

    def test_help_provider_attributes_completion_only(self):
        before = self._observation()
        after = self._observation(current_progress=10)
        self.assertEqual(AllianceHelpHandler.remaining(before), 10)
        self.assertTrue(AllianceHelpHandler.completion_check(after))
        self.assertFalse(
            AllianceHelpHandler.completion_check(
                self._observation(current_progress=11)
            )
        )
        for name in (
            "authorizeable",
            "transaction_spec",
            "perform_one_pulse",
            "postcondition_verified",
        ):
            self.assertFalse(hasattr(AllianceHelpHandler, name))


if __name__ == "__main__":
    unittest.main()
