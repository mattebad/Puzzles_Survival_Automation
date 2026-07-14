from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tasks" / "daily_quest_catalog.json"
MATRIX_PATH = ROOT / "tasks" / "daily_quest_execution_matrix.json"
PROMPT_INDEX_PATH = ROOT / "docs" / "prompts" / "daily-quest" / "index.json"
BACKLOG_PATH = ROOT / "BACKLOG.md"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class DailyQuestPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG_PATH)
        cls.matrix = load_json(MATRIX_PATH)
        cls.prompt_index = load_json(PROMPT_INDEX_PATH)
        cls.catalog_by_key = {row["objective_key"]: row for row in cls.catalog["objectives"]}
        cls.matrix_by_key = {row["objective_key"]: row for row in cls.matrix["objectives"]}
        cls.index_by_id = {row["task_id"]: row for row in cls.prompt_index["prompts"]}
        cls.backlog_ids = set(
            re.findall(
                r"^### (DQ-[A-Z0-9-]+)$",
                BACKLOG_PATH.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
        )

    def test_catalog_reconciliation_derives_count_and_covers_every_key(self):
        self.assertEqual(self.catalog["catalog_version"], 2)
        self.assertTrue(self.catalog["authority"]["legacy_status_fields_are_non_authoritative"])
        records = self.catalog["reconciliation_records"]
        self.assertEqual(
            {record["objective_key"] for record in records},
            set(self.catalog_by_key),
        )
        self.assertEqual(len(self.catalog_by_key), 36)
        self.assertEqual(
            self.catalog["observation_metadata"].keys(),
            self.catalog_by_key.keys(),
        )
        self.assertEqual(
            self.catalog_by_key["gather_food"]["aliases"],
            ["Gather Food", "Gathered Food"],
        )
        self.assertEqual(
            self.catalog["observation_metadata"]["gather_food"]["completion_quantity"],
            30000,
        )

    def test_matrix_has_one_entry_per_catalog_key_and_separate_support_flows(self):
        self.assertEqual(set(self.matrix_by_key), set(self.catalog_by_key))
        self.assertEqual(len(self.matrix_by_key), len(self.catalog_by_key))
        self.assertEqual(len(self.matrix["support_flows"]), 7)
        self.assertTrue(
            all(flow["flow_type"] == "support" for flow in self.matrix["support_flows"])
        )
        self.assertTrue(
            set(self.matrix_by_key["gather_food"]["aliases"])
            == {"Gather Food", "Gathered Food"}
        )

    def test_matrix_fields_and_closed_enums_are_complete(self):
        promotions = set(self.matrix["promotion_enum"])
        registrations = set(self.matrix["registration_status_enum"])
        required = {
            "objective_key",
            "aliases",
            "handler_family",
            "handler_variant",
            "route",
            "consequence_class",
            "resource_policy",
            "completion_target",
            "progress_format",
            "source_recognizer",
            "target_recognizer",
            "successor_recognizer",
            "action_transaction_boundary",
            "semantic_postcondition",
            "recovery_semantics",
            "daily_quest_reconciliation",
            "claim_behavior",
            "persistence_behavior",
            "implementation_status",
            "live_validation_status",
            "promotion_state",
            "current_runtime_registration_status",
            "scheduler_eligibility",
            "existing_implementation",
            "existing_tests",
            "bliss_native_evidence",
            "gnbots_provenance",
            "missing_work",
            "missing_evidence",
            "required_product_or_policy_decisions",
            "dependencies",
            "backlog_task_id",
            "prompt_path",
        }
        for row in self.matrix["objectives"]:
            self.assertEqual(required - set(row), set())
            self.assertIn(row["promotion_state"], promotions)
            self.assertIn(row["current_runtime_registration_status"], registrations)
            self.assertFalse(row["scheduler_eligibility"])
            self.assertTrue(row["route"])
            self.assertTrue(row["claim_behavior"])
            self.assertTrue(row["persistence_behavior"])
            self.assertTrue(row["prompt_path"])
        for row in self.matrix["objectives"]:
            self.assertTrue(row["resource_policy"])
            self.assertTrue(row["semantic_postcondition"])
            self.assertEqual(
                row["completion_target"],
                self.catalog["observation_metadata"][row["objective_key"]][
                    "completion_quantity"
                ],
            )
        for row in self.matrix["support_flows"]:
            self.assertTrue(
                {
                    "route",
                    "implementation_status",
                    "live_validation_status",
                    "promotion_state",
                    "current_runtime_registration_status",
                    "scheduler_eligibility",
                    "claim_behavior",
                    "persistence_behavior",
                    "backlog_task_id",
                    "prompt_path",
                }
                <= set(row)
            )
            self.assertIn(row["promotion_state"], promotions)
            self.assertIn(row["current_runtime_registration_status"], registrations)
            self.assertFalse(row["scheduler_eligibility"])
            self.assertTrue(row["route"])
            self.assertTrue(row["claim_behavior"])
            self.assertTrue(row["persistence_behavior"])
            self.assertTrue(row["prompt_path"])

    def test_backlog_and_prompt_index_are_bijective(self):
        indexed_ids = set(self.index_by_id)
        self.assertEqual(indexed_ids, self.backlog_ids)
        matrix_task_ids = {
            row["backlog_task_id"]
            for row in self.matrix["objectives"] + self.matrix["support_flows"]
        }
        self.assertTrue(matrix_task_ids <= indexed_ids)
        for prompt in self.prompt_index["prompts"]:
            path = ROOT / prompt["prompt_path"]
            self.assertTrue(path.is_file(), prompt["task_id"])
            text = path.read_text(encoding="utf-8")
            normalized_text = " ".join(text.casefold().split())
            self.assertIn(prompt["task_id"], text)
            for marker in (
                "Repository authority",
                "Scope",
                "Route",
                "Source",
                "target",
                "successor",
                "Policy",
                "Postcondition",
                "Recovery",
                "Daily",
                "Claim",
                "Persistence",
                "Tests",
                "Bliss",
                "Commit:",
            ):
                self.assertIn(marker.casefold(), text.casefold(), prompt["task_id"])
            self.assertIn("registration", normalized_text, prompt["task_id"])
            self.assertIn("scheduler", normalized_text, prompt["task_id"])
            self.assertIn("eligibility", text.casefold(), prompt["task_id"])
            self.assertTrue(
                "live input" in normalized_text
                or "gameplay input" in normalized_text
                or "consequential input" in normalized_text
                or (
                    "consequential" in normalized_text
                    and "input" in normalized_text
                ),
                prompt["task_id"],
            )
            self.assertTrue(
                "fail closed" in text.casefold()
                or "stop" in text.casefold()
                or "unresolved" in text.casefold(),
                prompt["task_id"],
            )

    def test_every_objective_has_single_declared_owner_and_prompt(self):
        owners = {}
        for row in self.matrix["objectives"]:
            owner = row["backlog_task_id"]
            self.assertIn(owner, self.index_by_id)
            self.assertIn(row["objective_key"], self.index_by_id[owner]["objective_keys"])
            owners.setdefault(row["objective_key"], []).append(owner)
        self.assertTrue(all(len(values) == 1 for values in owners.values()))

    def test_live_and_registered_states_match_checked_in_operator_surface(self):
        expected_registered = {
            "help_allies",
            "personal_might_praise",
        }
        actual_registered = {
            key
            for key, row in self.matrix_by_key.items()
            if row["current_runtime_registration_status"] != "NOT_REGISTERED"
        }
        self.assertEqual(actual_registered, expected_registered)
        self.assertIn("alliance-help", (ROOT / "scripts" / "pnsctl.py").read_text())
        pnsctl = (ROOT / "scripts" / "pnsctl.py").read_text()
        self.assertIn('"praise"', pnsctl)
        self.assertIn('"personal-might-claim"', pnsctl)
        self.assertNotIn("REGISTERED_RUNTIME", {
            row["current_runtime_registration_status"]
            for row in self.matrix["objectives"] + self.matrix["support_flows"]
        })
        self.assertEqual(
            self.matrix_by_key["help_allies"]["promotion_state"],
            "LIVE_VALIDATED",
        )
        self.assertEqual(
            self.matrix_by_key["personal_might_praise"]["promotion_state"],
            "LIVE_VALIDATED",
        )

    def test_disabled_flows_are_unregistered_and_ineligible(self):
        for row in self.matrix["objectives"]:
            if row["promotion_state"] == "DISABLED_POLICY":
                self.assertEqual(
                    row["current_runtime_registration_status"],
                    "NOT_REGISTERED",
                )
                self.assertFalse(row["scheduler_eligibility"])
        self.assertNotIn(
            "Main Quest Claim",
            (ROOT / "tasks" / "daily_quest_execution_matrix.json").read_text(),
        )

    def test_claim_milestone_and_objective_execution_remain_separate(self):
        for row in self.matrix["objectives"]:
            self.assertIn("Claim", row["claim_behavior"])
            self.assertNotIn("ready", row["claim_behavior"].casefold())
        milestone = next(
            flow
            for flow in self.matrix["support_flows"]
            if flow["flow_key"] == "activity_milestone_claim"
        )
        daily_claim = next(
            flow
            for flow in self.matrix["support_flows"]
            if flow["flow_key"] == "generalized_daily_row_claim"
        )
        self.assertIn("separate", milestone["claim_behavior"])
        self.assertNotEqual(milestone["route"], daily_claim["route"])
        self.assertTrue(self.matrix["authority"]["objective_completion_does_not_imply_claim_readiness"])

    def test_main_quest_implementation_and_active_artifacts_are_absent(self):
        self.assertFalse((ROOT / "tasks" / "main_quest.py").exists())
        self.assertFalse((ROOT / "tests" / "test_main_quest_claim.py").exists())
        self.assertFalse(
            (ROOT / "tests" / "fixtures" / "phase_e_main_claim_observations.json").exists()
        )
        active_paths = (
            BACKLOG_PATH,
            ROOT / "CURRENT_HANDOFF.md",
            ROOT / "docs" / "daily-quest-handler-status.md",
            ROOT / "tasks" / "daily_quest_execution_matrix.json",
        )
        for path in active_paths:
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "main quest claim" in line.casefold():
                    self.assertRegex(
                        line.casefold(),
                        r"exclude|excluded|exclusion|out of scope|not .*claim|never|negative|historical",
                        str(path),
                    )


if __name__ == "__main__":
    unittest.main()
