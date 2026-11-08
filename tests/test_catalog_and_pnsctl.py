from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import pnsctl
from automation_service.registry import TROOP_TRAINING_FLOW_ID
from tasks.catalog import CATALOG_PATH, catalog_summary, load_catalog, objective_for_text
from tasks.gameplay_flow_contracts import CONTRACTS_DIR
MILESTONE_FLOW_ID = "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION"
MATRIX_PATH = Path(__file__).resolve().parents[1] / "tasks" / "daily_quest_execution_matrix.json"


def _flow_id_choices(parser: argparse.ArgumentParser, command: list[str]):
    """Return the ``flow_id`` choices of the (nested) subcommand named by ``command``."""

    for name in command:
        action = next(
            item
            for item in parser._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        parser = action.choices[name]
    flow_action = next(item for item in parser._actions if item.dest == "flow_id")
    return flow_action.choices


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

    def test_box_purchase_decision_remains_blocked_without_authorization(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        row = next(item for item in matrix["objectives"] if item["objective_key"] == "buy_box")
        self.assertEqual(row["implementation_status"], "DISABLED_POLICY")
        self.assertEqual(row["promotion_state"], "DISABLED_POLICY")
        self.assertIn("no product authorization", row["resource_policy"])
        self.assertIn("no purchase dispatch", row["action_transaction_boundary"])
        self.assertIn("explicit product authorization remains absent", row["required_product_or_policy_decisions"])
    def test_every_catalog_objective_has_one_durable_disposition(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        reconciliation = matrix["portfolio_reconciliation"]
        owners = {
            item["objective_key"]: item["owner_task_id"]
            for item in reconciliation["catalog_objective_ownership"]
        }
        dispositions = reconciliation["catalog_disposition"]
        self.assertEqual(set(dispositions), set(owners))
        allowed = {
            "defer_not_current_portfolio",
            "defer_explicit",
            "retain_existing_owner",
            "retain_owner_blocked",
            "retain_observation_only",
        }
        for key, owner in owners.items():
            with self.subTest(objective=key):
                self.assertEqual(dispositions[key]["owner_task_id"], owner)
                self.assertIn(dispositions[key]["disposition"], allowed)
                self.assertIsNone(dispositions[key]["dispatch_authority"])
    def test_legacy_retirement_keeps_replacements_non_authorizing(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        retirement = matrix["portfolio_reconciliation"]["legacy_retirement"]
        self.assertEqual(retirement["status"], "accepted_offline")
        self.assertEqual(retirement["registration_state"], "NOT_REGISTERED")
        self.assertFalse(retirement["scheduler_eligibility"])
        entries = {item["legacy_id"]: item for item in retirement["entries"]}
        self.assertEqual(
            set(entries),
            {
                "PERSONAL-MIGHT-PRAISE-BLISS-PILOT",
                "personal_might_daily_claim",
                "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
            },
        )
        for entry in entries.values():
            self.assertFalse(entry["runtime_authority"])
            self.assertTrue(entry["replacement"])

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

    def test_catalog_bioenhancer_references_direct_record_without_selected_daily_prerequisite(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        objective = next(
            item
            for item in raw["objectives"]
            if item["objective_key"] == "bioenhancer_research"
        )
        self.assertEqual(objective["product_record_id"], "bioenhancer_research")
        self.assertFalse(objective["selected_daily_prerequisite"])

    def test_catalog_recruitment_maps_only_basic_five_objective_to_direct_record(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        objective = next(
            item
            for item in raw["objectives"]
            if item["objective_key"] == "recruit_noahs_tavern"
        )
        self.assertEqual(objective["product_record_id"], "noahs_tavern_recruitment")
        self.assertFalse(objective["selected_daily_prerequisite"])
        self.assertEqual(objective["progress_format"], "current/5")
        self.assertEqual(objective["claim_support"], "ordinary_row_only")

    def test_catalog_campaign_ap_references_direct_record_without_selected_daily_prerequisite(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        objective = next(
            item for item in raw["objectives"] if item["objective_key"] == "consume_ap"
        )
        self.assertEqual(objective["product_record_id"], "campaign_ap")
        self.assertFalse(objective["selected_daily_prerequisite"])
        self.assertEqual(objective["progress_format"], "current/20")
        self.assertEqual(objective["claim_support"], "ordinary_row_only")
    def test_catalog_maps_all_troop_training_rows_without_selected_daily_prerequisite(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        objectives = {
            item["objective_key"]: item
            for item in raw["objectives"]
            if item["objective_key"] in {"train_fighter", "train_vehicle", "train_shooter", "train_rider"}
        }
        self.assertEqual(
            set(objectives),
            {"train_fighter", "train_vehicle", "train_shooter", "train_rider"},
        )
        for objective in objectives.values():
            with self.subTest(objective=objective["objective_key"]):
                self.assertEqual(objective["product_record_id"], "troop_training")
                self.assertFalse(objective["selected_daily_prerequisite"])
                self.assertEqual(objective["claim_support"], "ordinary_row_only")

    def test_catalog_separates_milestone_claim_from_ordinary_row_claim(self):
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        ordinary = raw["claim_ownership"]["ordinary_claim"]
        milestone = raw["claim_ownership"]["milestone_claim"]
        self.assertEqual(milestone["product_record_id"], "activity_milestone_claim")
        self.assertEqual(
            milestone["execution_flow_id"],
            "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
        )
        self.assertTrue(milestone["sole_owner"])
        self.assertEqual(milestone["ordinary_claim_owner"], ordinary["product_record_id"])
        self.assertEqual(milestone["registration_state"], "NOT_REGISTERED")
        self.assertFalse(milestone["scheduler_eligibility"])


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


    def test_command_surface_is_exactly_the_documented_set(self):
        # Adding or removing a command must be deliberate: update this set and
        # the command reference in docs/pns-operations-runbook.md together.
        def choices(parser):
            action = next(
                item
                for item in parser._actions
                if isinstance(item, argparse._SubParsersAction)
            )
            return action.choices

        top = choices(pnsctl.parser())
        actual = {}
        for name, sub in top.items():
            try:
                actual[name] = frozenset(choices(sub))
            except StopIteration:
                actual[name] = frozenset()
        self.assertEqual(
            actual,
            {
                "reconcile": frozenset(),
                "development-session": frozenset(
                    {
                        "observe",
                        "launch-game",
                        "recover-resource-home",
                        "recover-network",
                        "delegated-dry-run",
                        "run-flow",
                    }
                ),
                "bluestacks": frozenset(
                    {
                        "verify-flow",
                        "recover-home",
                        "reconcile-campaign-atlas-survey-action",
                    }
                ),
                "automation-service": frozenset(
                    {
                        "serve",
                        "inspect-rearm",
                        "status",
                        "health",
                        "enable",
                        "disable",
                        "run",
                        "service-enable",
                        "service-disable",
                        "emergency-stop",
                        "pulse",
                    }
                ),
            },
        )

    def test_retired_commands_are_rejected(self):
        for argv in (
            ["conduct"],
            ["nova-praise-pulse"],
            ["nova-praise-supervised-guard", "reconcile-proven-no-effect"],
            ["noahs-tavern-nav"],
            ["noahs-tavern-recruit"],
            ["bluestacks", "reload-game"],
            ["bluestacks", "preflight"],
            ["bluestacks", "dismiss-reload-overlay"],
            ["bluestacks", "run-flow"],
            ["automation-service", "campaign-plan"],
        ):
            with self.subTest(argv=argv), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit):
                pnsctl.parser().parse_args(argv)

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

    def test_every_selectable_flow_id_has_a_registered_runner(self):
        registry = pnsctl._load_bluestacks_flow_registry()
        self.assertTrue(pnsctl.BLUESTACKS_FLOW_IDS)
        # A registry route without code-bound handlers must fail here rather
        # than be silently dropped from the selectable set.
        self.assertEqual(set(pnsctl.BLUESTACKS_FLOW_IDS), set(registry))
        for flow_id in pnsctl.BLUESTACKS_FLOW_IDS:
            with self.subTest(flow_id=flow_id):
                route = registry.get(flow_id)
                self.assertIsNotNone(route, "no registry route")
                self.assertIn(route["runner"], pnsctl._BLUESTACKS_FLOW_RUNNERS)
                self.assertIn(
                    route["evidence_validator"], pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS
                )

    def test_canonical_ruins_is_not_a_legacy_development_operator(self):
        registry = pnsctl._load_bluestacks_flow_registry()
        self.assertEqual(len(pnsctl.BLUESTACKS_FLOW_IDS), 11)
        self.assertNotIn(pnsctl.RUINS_FLOW_ID, pnsctl.BLUESTACKS_FLOW_IDS)
        self.assertNotIn(pnsctl.RUINS_FLOW_ID, registry)
        self.assertFalse(
            any(
                name.startswith("ruins_challenge_home_atlas_")
                for name in pnsctl._BLUESTACKS_FLOW_RUNNERS
            )
        )

        root = pnsctl.parser()
        root_commands = next(
            action
            for action in root._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        development = root_commands.choices["development-session"]
        development_commands = next(
            action
            for action in development._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        run_flow = development_commands.choices["run-flow"]
        argument_destinations = {action.dest for action in run_flow._actions}
        self.assertNotIn("chests_only", argument_destinations)
        self.assertNotIn("chest_continuation", argument_destinations)


    def test_troop_training_is_service_only_with_manual_recovery_preserved(self):
        registry = pnsctl._load_bluestacks_flow_registry()
        self.assertNotIn(TROOP_TRAINING_FLOW_ID, registry)
        self.assertNotIn(TROOP_TRAINING_FLOW_ID, pnsctl.BLUESTACKS_FLOW_IDS)
        self.assertNotIn(
            "troop_training_consolidation_runner",
            pnsctl._BLUESTACKS_FLOW_RUNNERS,
        )
        self.assertNotIn(
            "troop_training_consolidation_evidence",
            pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS,
        )
        choices = _flow_id_choices(
            pnsctl.parser(),
            ["development-session", "run-flow"],
        )
        self.assertNotIn(TROOP_TRAINING_FLOW_ID, choices)
        self.assertTrue(
            callable(pnsctl.bluestacks_recover_home),
            "manual Home recovery remains a supported pnsctl route",
        )

    def test_flow_commands_offer_exactly_the_selectable_flow_ids(self):
        selectable = set(pnsctl.BLUESTACKS_FLOW_IDS)
        for argv in (["development-session", "run-flow"],):
            with self.subTest(command=argv):
                self.assertEqual(set(_flow_id_choices(pnsctl.parser(), argv)), selectable)

    def test_contract_only_flows_are_not_selectable(self):
        contract_only = set()
        for path in CONTRACTS_DIR.glob("*.json"):
            if path.name == "schema.json":
                continue
            contract = json.loads(path.read_text(encoding="utf-8"))
            if contract.get("implementation_status") == "contract_only":
                contract_only.add(contract["flow_id"])
        self.assertIn(MILESTONE_FLOW_ID, contract_only)
        self.assertFalse(contract_only & set(pnsctl.BLUESTACKS_FLOW_IDS))

    def test_contract_only_milestone_flow_is_rejected_before_runtime_work(self):
        self.assertNotIn(MILESTONE_FLOW_ID, pnsctl.BLUESTACKS_FLOW_IDS)
        for argv in (
            ["development-session", "run-flow", MILESTONE_FLOW_ID],
        ):
            with self.subTest(command=argv), patch.object(
                pnsctl, "_run_fixed_bluestacks_adb"
            ) as adb, contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit):
                    pnsctl.parser().parse_args(argv)
                self.assertIn("invalid choice", stderr.getvalue())
                adb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
