from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tasks" / "daily_quest_catalog.json"
MATRIX_PATH = ROOT / "tasks" / "daily_quest_execution_matrix.json"
AUDIT_PATH = ROOT / "tasks" / "daily_quest_provenance_audit.json"
PROMPT_INDEX_PATH = ROOT / "docs" / "prompts" / "daily-quest" / "index.json"
BACKLOG_PATH = ROOT / "docs" / "archive" / "backlog-legacy.md"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class DailyQuestPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_json(CATALOG_PATH)
        cls.matrix = load_json(MATRIX_PATH)
        cls.audit = load_json(AUDIT_PATH)
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
        cls.inventory = load_json(
            ROOT / cls.audit["proven_daily_inventory"]["inventory_path"]
        )

    def test_catalog_reconciliation_derives_count_and_covers_every_key(self):
        self.assertEqual(self.catalog["catalog_version"], 3)
        self.assertTrue(self.catalog["authority"]["legacy_status_fields_are_non_authoritative"])
        records = self.catalog["reconciliation_records"]
        self.assertEqual(
            {record["objective_key"] for record in records},
            set(self.catalog_by_key),
        )
        self.assertEqual(len(self.catalog_by_key), len(self.inventory["rows"]))
        self.assertEqual(
            self.catalog["observation_metadata"].keys(),
            self.catalog_by_key.keys(),
        )
        self.assertTrue(self.catalog["admission_rule"]["requires_selected_daily_provenance"])
        self.assertTrue(self.catalog["admission_rule"]["requires_objective_list_region"])

    def test_catalog_admission_requires_selected_daily_provenance(self):
        inventory_proof = self.audit["proven_daily_inventory"]
        accepted_source_types = set(self.audit["admission_rule"]["accepted_source_types"])
        self.assertEqual(inventory_proof["classification"], "PROVEN_DAILY_OBJECTIVE")
        self.assertIn(inventory_proof["source_type"], accepted_source_types)
        self.assertTrue(inventory_proof["quest_screen_positive"])
        self.assertTrue(inventory_proof["daily_tab_positive"])
        self.assertTrue(inventory_proof["main_negative"])
        self.assertEqual(inventory_proof["non_main_classification"], "NON_MAIN")
        self.assertTrue(inventory_proof["raw_frame_paths"])
        self.assertTrue(inventory_proof["objective_list_region"])
        for objective in self.catalog["objectives"]:
            self.assertIn(
                "inventory-20260713.json",
                objective["evidence_provenance"],
            )
        for candidate in self.audit["records"]:
            self.assertFalse(candidate["catalog_admitted"], candidate["candidate_key"])
            self.assertIn(
                candidate["classification"],
                self.audit["allowed_classifications"],
            )
            self.assertTrue(candidate["missing_evidence"], candidate["candidate_key"])

    def test_provenance_audit_rejects_non_daily_sources(self):
        rejected_sources = set(self.audit["admission_rule"]["rejected_as_independent_proof"])
        self.assertIn("synthetic_fixture", rejected_sources)
        self.assertIn("planning_document", rejected_sources)
        self.assertIn("unclassified_ocr_capture", rejected_sources)
        audit_by_key = {record["candidate_key"]: record for record in self.audit["records"]}
        self.assertEqual(audit_by_key["gather_food"]["classification"], "SYNTHETIC_ONLY")
        self.assertEqual(
            audit_by_key["upgrade_building.vehicle_depot"]["classification"],
            "PROVEN_MAIN_OBJECTIVE",
        )
        self.assertEqual(
            audit_by_key["attack_headquarters_and_win"]["classification"],
            "DOCUMENTATION_ONLY",
        )
        self.assertFalse(any(
            key in self.catalog_by_key
            for key in (
                "gather_food",
                "ultimate_challenge",
                "hunt_zombie",
                "own_hero",
                "attack_headquarters_and_win",
            )
        ))

    def test_matrix_has_one_entry_per_catalog_key_and_separate_support_flows(self):
        self.assertEqual(set(self.matrix_by_key), set(self.catalog_by_key))
        self.assertEqual(len(self.matrix_by_key), len(self.catalog_by_key))
        self.assertEqual(len(self.matrix["support_flows"]), 8)
        self.assertTrue(
            all(flow["flow_type"] == "support" for flow in self.matrix["support_flows"])
        )
        support_by_task = {
            flow["backlog_task_id"]: flow for flow in self.matrix["support_flows"]
        }
        self.assertEqual(
            support_by_task["DQ-FLOW-WORLD-STAMINA-ENGINE"]["implementation_status"],
            "OFFLINE_IMPLEMENTED",
        )
        self.assertEqual(
            self.matrix_by_key["upgrade_building"]["aliases"],
            ["Upgrade building"],
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

    def test_retired_help_and_praise_are_completion_attribution_only(self):
        actual_registered = {
            key
            for key, row in self.matrix_by_key.items()
            if row["current_runtime_registration_status"] != "NOT_REGISTERED"
        }
        self.assertEqual(actual_registered, set())
        self.assertNotIn("REGISTERED_RUNTIME", {
            row["current_runtime_registration_status"]
            for row in self.matrix["objectives"] + self.matrix["support_flows"]
        })
        for key in ("help_allies", "personal_might_praise"):
            row = self.matrix_by_key[key]
            self.assertEqual(row["handler_variant"], "completion_attribution")
            self.assertEqual(row["route"], "completion_attribution_only")
            self.assertEqual(row["consequence_class"], "observation_only")
            self.assertEqual(row["promotion_state"], "OFFLINE_ONLY")
            self.assertEqual(
                row["current_runtime_registration_status"],
                "NOT_REGISTERED",
            )
            self.assertFalse(row["scheduler_eligibility"])
            self.assertIn("no gameplay dispatch", row["action_transaction_boundary"])

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
            if flow["flow_key"] == "aggregate_daily_claim"
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

    def test_rec_d01_exact_recovery_owner_map_preserves_prior_dispositions(self):
        expected = {
            "upgrade_building": "REC-P06",
            "join_hero_duel": "REC-P05",
            "upgrade_tech": "REC-P07",
            "train_fighter": "REC-R06",
            "train_rider": "REC-R07",
            "train_shooter": "REC-R08",
            "train_vehicle": "REC-R09",
            "recruit_noahs_tavern": "REC-D07",
            "upgrade_hero": "REC-P04",
            "defeat_zombie_lair": "REC-R19",
            "consume_stamina": "REC-R19",
            "consume_ap": "REC-R11",
            "help_allies": "REC-D08",
            "buy_box": "REC-P12",
            "gather_wood": "REC-R17",
            "gather_steel": "REC-R17",
            "gather_gas": "REC-R18",
            "boost_resource_building_output": "REC-P10",
            "ruins_shop_purchase": "REC-P01",
            "rare_earth_shop_purchase": "REC-P02",
            "alliance_shop_purchase": "REC-P03",
            "speedup_using_items": "REC-P09",
            "bioenhancer_research": "REC-D06",
            "craft_nanoweapon": "REC-R15",
            "personal_might_praise": "REC-D09",
            "enhance_chip": "REC-R04",
            "enhance_module": "REC-R05",
            "enhance_gear": "REC-R03",
            "donate_alliance_tech": "REC-P08",
            "supply_depot": "REC-D10",
            "ruins_challenge": "REC-R12",
        }
        ownership = self.matrix["portfolio_reconciliation"]["catalog_objective_ownership"]
        self.assertEqual(len(ownership), 31)
        self.assertEqual({row["objective_key"]: row["owner_task_id"] for row in ownership}, expected)
        self.assertEqual(len({row["objective_key"] for row in ownership}), 31)
        for row in ownership:
            with self.subTest(objective=row["objective_key"]):
                self.assertEqual(row["recovery_owner_task_id"], expected[row["objective_key"]])
                self.assertEqual(row["dispatch_authority"], None)
                self.assertEqual(row["dispatch_owner"], None)
                self.assertTrue(row["historical_owner_task_id"])
                self.assertTrue(row["historical_state"])
                self.assertTrue(row["historical_missing_proof"])
        for key, disposition in self.matrix["portfolio_reconciliation"]["catalog_disposition"].items():
            self.assertEqual(disposition["owner_task_id"], expected[key])
            self.assertEqual(disposition["dispatch_authority"], None)
            self.assertTrue(disposition["historical_missing_proof"])

    def test_rec_d01_non_catalog_identity_boundaries_are_explicit(self):
        rows = {row["identity"]: row for row in self.matrix["portfolio_reconciliation"]["non_catalog_portfolio_ownership"]}
        ultimate = rows["ultimate_daily_join"]
        self.assertEqual(ultimate["owner_task_id"], "REC-D05")
        self.assertFalse(ultimate["catalog_admitted"])
        self.assertEqual(ultimate["daily_control"], "Join")
        self.assertEqual(ultimate["main_control"], "Clear")
        self.assertTrue(ultimate["not_main_clear"])
        self.assertTrue(ultimate["not_campaign_ap"])
        self.assertEqual(ultimate["campaign_ap_owner"], "REC-R11")
        resource = rows["use_resource_item"]
        self.assertEqual(resource["owner_task_id"], "REC-R02")
        self.assertFalse(resource["catalog_admitted"])
        self.assertTrue(resource["direct_resource_evidence_required"])
        self.assertTrue(resource["selected_daily_evidence_required"])
        self.assertTrue(resource["ownership_requires_both_evidence"])
        food = rows["gathering_food_march_proving_slice"]
        self.assertEqual(food["owner_task_id"], "REC-R16")
        self.assertFalse(food["catalog_admitted"])
        self.assertTrue(food["proving_slice"])
        self.assertEqual(food["daily_ownership"], "EXCLUDED_FROM_DAILY")

    def test_rec_d01_policy_consumers_keep_negative_and_non_authorizing_facts(self):
        from copy import deepcopy

        from tasks.product_authority import (
            ProductAuthorityError,
            authority_digest,
            load_product_authority,
            validate_product_authority,
        )

        authority = load_product_authority()
        policies = {row["policy_id"]: row for row in authority["policies"]}
        costs = policies["daily-control-cost-boundary"]
        for field in (
            "premium_allowed", "cash_allowed", "paid_allowed", "ambiguous_allowed",
            "refill_allowed", "ten_x_allowed", "item_backed_substitute_allowed",
            "unknown_cost_allowed",
        ):
            with self.subTest(control=field):
                self.assertFalse(costs[field])
        self.assertFalse(costs["route_owned_effects_globally_forbidden"])
        unknown = policies["unknown-consequence"]
        self.assertEqual(unknown["status"], "prohibited")
        completion = policies["current-positive-completion-postcondition"]
        self.assertTrue(completion["current_positive_postcondition_required"])
        for field in (
            "queue_projection_is_completion", "timer_projection_is_completion",
            "outbound_projection_is_completion", "return_projection_is_completion",
            "dispatch_is_completion",
        ):
            with self.subTest(projection=field):
                self.assertFalse(completion[field])
        supply = policies["supply-depot-free-only"]
        self.assertTrue(supply["free_only"])
        self.assertTrue(supply["stop_when_free_disappears"])
        self.assertFalse(supply["permissions_infer_daily_completion"])
        for key in (
            "train_fighter", "train_rider", "train_shooter", "train_vehicle",
            "gather_wood", "gather_steel", "gather_gas",
        ):
            row = self.matrix_by_key[key]
            self.assertTrue(row["completion_requires_current_positive_postcondition"])
            self.assertFalse(row.get("queue_projection_is_completion", False))
            self.assertFalse(row.get("timer_projection_is_completion", False))
            self.assertFalse(row.get("return_projection_is_completion", False))
        ultimate = policies["ultimate-daily-join-identity"]
        self.assertFalse(ultimate["main_clear_is_daily"])
        self.assertFalse(ultimate["campaign_ap_is_daily"])

        rejected_policy_mutations = (
            ("Main Clear identity", "ultimate-daily-join-identity", "main_clear_is_daily", True),
            ("Nova and Personal Might transfer", "nova-personal-might-identity", "distinct_identities", False),
            ("BuyBox and ResourceBuildingBoost merge", "buy-box-resource-boost-separation", "same_identity", True),
            ("premium control", "daily-control-cost-boundary", "premium_allowed", True),
            ("paid control", "daily-control-cost-boundary", "paid_allowed", True),
            ("projected completion", "current-positive-completion-postcondition", "queue_projection_is_completion", True),
            ("Free disappearance", "supply-depot-free-only", "stop_when_free_disappears", False),
            ("unknown cost", "daily-control-cost-boundary", "unknown_cost_allowed", True),
        )
        for label, policy_id, field, invalid in rejected_policy_mutations:
            with self.subTest(rejected=label):
                changed = deepcopy(authority)
                changed_policy = next(
                    row for row in changed["policies"] if row["policy_id"] == policy_id
                )
                changed_policy[field] = invalid
                changed["authority_digest"] = authority_digest(changed)
                with self.assertRaises(ProductAuthorityError):
                    validate_product_authority(changed)

        changed = deepcopy(authority)
        changed["static_facts_are_non_authorizing"]["can_claim"] = True
        changed["authority_digest"] = authority_digest(changed)
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(changed)

        for facts in (
            self.catalog["authority"]["static_facts_are_non_authorizing"],
            authority["static_facts_are_non_authorizing"],
            self.matrix["authority"]["non_authorizing_static_facts"],
        ):
            self.assertFalse(facts["can_claim"])
            self.assertFalse(facts["can_reserve"])
            self.assertFalse(facts["can_enable"])
            self.assertFalse(facts["can_dispatch"])
            self.assertFalse(facts["runtime_authority"])


if __name__ == "__main__":
    unittest.main()
