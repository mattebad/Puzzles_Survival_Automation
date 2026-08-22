"""Focused tests for gameplay flow contracts and dependency regression marking."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scripts import pnsctl
from tasks.gameplay_flow_contracts import (
    CONTRACTS_DIR,
    FlowContractError,
    load_all_flow_contracts,
    load_flow_contract,
    list_flow_contract_ids,
    mark_regression_required_for_dependency,
    validate_flow_contract,
)
from tasks.home_context import HOME_NAVIGATION_PRIMITIVES_DIGEST


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
MATRIX_PATH = ROOT / "tasks" / "daily_quest_execution_matrix.json"
CATALOG_PATH = ROOT / "tasks" / "daily_quest_catalog.json"


class GameplayFlowContractTests(unittest.TestCase):
    def test_all_queue_flows_have_schema_valid_contracts(self):
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        queue_ids = {item["flow_id"] for item in queue["flows"]}
        contract_ids = set(list_flow_contract_ids())
        conduct_ids = set(pnsctl._CONDUCT_DEFAULT_MAX_INPUTS)
        self.assertTrue(queue_ids <= contract_ids)
        self.assertEqual(
            contract_ids - queue_ids,
            {"PERSONAL-MIGHT-PRAISE-BLISS-PILOT"} | (conduct_ids - queue_ids),
        )
        contracts = load_all_flow_contracts()
        self.assertEqual(
            len(contracts),
            len(queue_ids | conduct_ids | {"PERSONAL-MIGHT-PRAISE-BLISS-PILOT"}),
        )
        for flow_id, contract in contracts.items():
            validate_flow_contract(contract)
            self.assertEqual(contract["flow_id"], flow_id)
            if contract["implementation_status"] == "contract_only":
                self.assertTrue(
                    contract["evidence_requirements"] or contract["proof_state"] == "evidence_required"
                )
            if contract["implementation_status"] == "live_validated":
                self.assertEqual(contract["proof_state"], "current")
            self.assertNotEqual(contract["implementation_status"], "scheduler_eligible")

    def test_ultimate_challenge_is_blocked_by_evidence_not_policy(self):
        contract = load_flow_contract("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")
        scenario = next(
            item
            for item in contract["scenarios"]
            if item["scenario_id"] == "ultimate_flee_production"
        )
        self.assertEqual(scenario["mode"], "blocked_until_evidence")
        self.assertEqual(scenario["permitted_inputs"], [])
        proof_notes = " ".join(contract["evidence_requirements"]).casefold()
        self.assertIn("composite", proof_notes)
        self.assertIn("continuous terminal-reconciliation", proof_notes)

    def test_bioenhancer_contract_is_free_only_and_historical_evidence_non_accepting(self):
        contract = load_flow_contract(
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION"
        )
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["product_authority_binding"]["product_record_id"],
            "bioenhancer_research",
        )
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        dispatch = next(
            item
            for item in contract["transition_contracts"]
            if item["transition_id"] == "dispatch-free-research"
        )
        self.assertIn("cooldown successor", " ".join(dispatch["postconditions"]).casefold())
        self.assertIn("count text alone", " ".join(dispatch["postconditions"]).casefold())
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["replay_fixture_proof_state"], "evidence_required")
        scenario = contract["scenarios"][0]
        self.assertEqual(scenario["mode"], "blocked_until_evidence")
        self.assertEqual(scenario["permitted_inputs"], [])
        evidence = " ".join(contract["evidence_requirements"]).casefold()
        self.assertIn("historical bliss", evidence)
        self.assertIn("non-accepting", evidence)
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")

    def test_nova_contract_separates_live_proof_from_production_eligibility(self):
        nova = load_flow_contract("NOVA-PRAISE-HOME-ATLAS-MIGRATION")
        self.assertEqual(nova["schema_version"], 2)
        self.assertEqual(nova["implementation_status"], "reference_implemented")
        self.assertNotEqual(nova["implementation_status"], "live_validated")
        self.assertEqual(nova["supervised_live_proof_state"], "current")
        self.assertEqual(nova["offline_proof_state"], "current")
        self.assertEqual(nova["replay_fixture_proof_state"], "evidence_required")
        self.assertFalse(nova["production_eligible"])
        fixtures = {item["fixture_id"]: item for item in nova["replay_fixture_requirements"]}
        self.assertEqual(
            [fixture_id for fixture_id, item in fixtures.items() if item["status"] == "required_evidence"],
            ["zero_attempts_remaining"],
        )
        for item in fixtures.values():
            if item["status"] == "available":
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
        deps = nova["shared_primitive_dependencies"]
        self.assertTrue(any(dep["version_digest_field"] == "HOME_NAVIGATION_PRIMITIVES_DIGEST" for dep in deps))
        self.assertEqual(len(HOME_NAVIGATION_PRIMITIVES_DIGEST), 64)
        scenario = next(
            item
            for item in nova["scenarios"]
            if item["scenario_id"] == "nova_navigation_round_trip_no_praise"
        )
        self.assertEqual(scenario["mode"], "navigation_only")
        self.assertIn("open_praise", scenario["forbidden_inputs"])
        self.assertIn("exactly_one_free_praise_when_authorized", scenario["forbidden_inputs"])
        self.assertNotIn("open_praise", scenario["permitted_inputs"])
        self.assertEqual(nova["registration_state"], "disabled")

    def test_personal_might_pilot_is_v2_and_registration_disabled(self):
        pilot = load_flow_contract("PERSONAL-MIGHT-PRAISE-BLISS-PILOT")
        self.assertEqual(pilot["schema_version"], 2)
        self.assertEqual(pilot["registration_state"], "disabled")
        self.assertFalse(pilot["production_eligible"])
        self.assertEqual(pilot["proof_state"], "evidence_required")
        scenario = pilot["scenarios"][0]
        self.assertEqual(scenario["mode"], "blocked_until_policy")
        self.assertEqual(scenario["permitted_inputs"], [])
        self.assertIn("praise_personal_might", scenario["forbidden_inputs"])
        self.assertNotIn("claim", " ".join(pilot["permitted_inputs"]).casefold())

    def test_v2_unknown_behavior_requires_no_input_evidence_gate(self):
        nova = load_flow_contract("NOVA-PRAISE-HOME-ATLAS-MIGRATION")
        broken = deepcopy(nova)
        gate = next(
            item for item in broken["evidence_gates"] if item["status"] == "evidence_required"
        )
        gate["permitted_inputs"] = ["open_praise"]
        with self.assertRaisesRegex(FlowContractError, "permit no input"):
            validate_flow_contract(broken)

    def test_v2_rejects_unknown_transition_and_scenario_references(self):
        nova = load_flow_contract("NOVA-PRAISE-HOME-ATLAS-MIGRATION")
        broken_transition = deepcopy(nova)
        broken_transition["transition_contracts"][0]["to"] = "invented_success"
        with self.assertRaisesRegex(FlowContractError, "unknown state"):
            validate_flow_contract(broken_transition)
        broken_scenario = deepcopy(nova)
        broken_scenario["scenarios"][0]["required_transitions"].append("invented_transition")
        with self.assertRaisesRegex(FlowContractError, "unknown transition"):
            validate_flow_contract(broken_scenario)

    def test_campaign_contract_is_v2_auto_battle_and_registration_disabled(self):
        campaign = load_flow_contract(
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
        )
        self.assertEqual(campaign["schema_version"], 2)
        self.assertEqual(campaign["registration_state"], "disabled")
        self.assertFalse(campaign["production_eligible"])
        joined = json.dumps(campaign).casefold()
        self.assertIn("auto_battle", joined)
        self.assertIn("one ap per 360 seconds", joined)
        self.assertIn("maximum ap 120", joined)

    def test_daily_and_maintenance_contract_identities_are_separate(self):
        pairs = (
            ("NANOWEAPON-BLUESTACKS-INTEGRATION", "NANO-MATERIAL-PRODUCTION-MAINTENANCE"),
            ("RECRUITMENT-BLUESTACKS-INTEGRATION", "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"),
            ("ZOMBIE-LAIR-BLUESTACKS-INTEGRATION", "ZOMBIE-LAIR-HOME-MAINTENANCE"),
        )
        for daily_id, maintenance_id in pairs:
            daily = load_flow_contract(daily_id)
            maintenance = load_flow_contract(maintenance_id)
            self.assertNotEqual(daily["completion_identity"], maintenance["completion_identity"])
            self.assertEqual(daily["registration_state"], "disabled")
            self.assertEqual(maintenance["registration_state"], "disabled")
            self.assertFalse(daily["production_eligible"])
            self.assertFalse(maintenance["production_eligible"])

    def test_exact_policy_quantities_cooldowns_and_home_terminals(self):
        nano_daily = json.dumps(load_flow_contract("NANOWEAPON-BLUESTACKS-INTEGRATION"))
        nano_maintenance = json.dumps(load_flow_contract("NANO-MATERIAL-PRODUCTION-MAINTENANCE"))
        recruitment_daily = json.dumps(load_flow_contract("RECRUITMENT-BLUESTACKS-INTEGRATION"))
        recruitment_maintenance = json.dumps(load_flow_contract("RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"))
        zombie_maintenance = json.dumps(load_flow_contract("ZOMBIE-LAIR-HOME-MAINTENANCE"))
        self.assertIn("43200", nano_daily)
        self.assertIn("100", nano_daily)
        self.assertIn("21600", nano_maintenance)
        self.assertIn("600", recruitment_daily)
        for seconds in ("600", "86400", "172800"):
            self.assertIn(seconds, recruitment_maintenance)
        self.assertIn("28", zombie_maintenance)
        for payload in (
            nano_daily,
            nano_maintenance,
            recruitment_daily,
            recruitment_maintenance,
            zombie_maintenance,
        ):
            self.assertIn("home", payload.casefold())
            self.assertIn("deferred", payload.casefold())

    def test_shared_home_dependency_change_marks_nova_regression_required(self):
        contracts = load_all_flow_contracts()
        self.assertEqual(contracts["NOVA-PRAISE-HOME-ATLAS-MIGRATION"]["proof_state"], "evidence_required")
        updated = mark_regression_required_for_dependency(
            contracts,
            primitive_id="home_navigation_primitives",
        )
        self.assertEqual(updated["NOVA-PRAISE-HOME-ATLAS-MIGRATION"]["proof_state"], "evidence_required")
        # Non-dependent quest-screen contracts preserve their current proof state.
        self.assertEqual(
            updated["DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"]["proof_state"],
            "current",
        )

    def test_schema_file_exists(self):
        self.assertTrue((CONTRACTS_DIR / "schema.json").is_file())

    def test_published_schema_accepts_all_representative_contracts(self):
        schema = json.loads(
            (CONTRACTS_DIR / "schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        representative_ids = (
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
            "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
        )
        for flow_id in representative_ids:
            contract = load_flow_contract(flow_id)
            with self.subTest(flow_id=flow_id):
                self.assertEqual(list(validator.iter_errors(contract)), [])

    def test_nova_praise_contract_is_bound_free_only_and_registration_disabled(self):
        contract = load_flow_contract("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE")
        self.assertEqual(contract["product_authority_binding"]["product_record_id"], "nova_praise")
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        route = contract["transition_contracts"]
        praise = next(item for item in route if item["transition_id"] == "dispatch_one_free_praise")
        self.assertEqual(praise["permitted_input"], "exactly_one_free_praise_when_authorized")
        self.assertIn("attempts_remaining_decremented_by_one", praise["postconditions"])
        self.assertIn("cooldown_consistent_with_fixed_300_second_policy_after_capture_delay", praise["postconditions"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])

    def test_daily_claim_contract_is_aggregate_row_local_and_fail_closed(self):
        contract = load_flow_contract("DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION")
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["trigger_cadence_type"], "daily_once")
        self.assertEqual(contract["reset_scope"], "daily_reset")
        self.assertEqual(
            contract["product_authority_binding"]["product_record_id"],
            "aggregate_daily_claim",
        )
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        self.assertEqual(
            contract["transition_contracts"][2]["permitted_input"],
            "current-frame-bound ordinary free non-milestone Claim tap",
        )
        self.assertIn(
            "reconcile-unknown-claim-effect",
            {item["transition_id"] for item in contract["transition_contracts"]},
        )
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertTrue(
            any(
                item["scenario_id"] == "selected-daily-aggregate-claim-unknown-successor"
                and "current-frame-bound ordinary free non-milestone Claim tap"
                in item["forbidden_inputs"]
                for item in contract["scenarios"]
            )
        )
        self.assertIn("non-claimable Claim row", contract["unsupported_or_manual_only_states"])
        self.assertIn("non-claimable", contract["cooldown_deferred_behavior"])

    def test_enhancement_family_sequence_reaches_each_ordered_category(self):
        contract = load_flow_contract(
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
        )
        transitions = {
            item["transition_id"]: item
            for item in contract["transition_contracts"]
        }
        advance = transitions["advance-to-next-category"]
        self.assertEqual(
            (advance["from"], advance["to"], advance["permitted_input"]),
            ("SETTLED_SUCCESSOR_RECONCILED", "COMMANDER_INFO_RECOGNIZED", None),
        )
        required = contract["scenarios"][0]["required_transitions"]
        self.assertEqual(required.count("advance-to-next-category"), 2)
        settled_positions = [
            index
            for index, transition_id in enumerate(required)
            if transition_id == "settle-same-item-successor"
        ]
        self.assertEqual(len(settled_positions), 3)
        self.assertEqual(
            [required[index + 1] for index in settled_positions[:2]],
            ["advance-to-next-category", "advance-to-next-category"],
        )
        self.assertEqual(required[settled_positions[-1] + 1], "return-canonical-home")
        self.assertEqual(
            transitions["quantity-selection-use"]["permitted_input"],
            "one_quantity_selection_use",
        )
        self.assertEqual(
            transitions["use-one-enhancer"]["permitted_input"],
            "one_consuming_confirm",
        )

    def test_daily_resource_item_contract_is_exact_and_not_eligible(self):
        contract = load_flow_contract(
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
        )
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["required_starting_context"], ["home_ready"])
        self.assertEqual(contract["navigation_input_authorization"]["maximum_inputs"], 10)
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_resource_list_swipes"],
            6,
        )
        self.assertEqual(
            contract["navigation_input_authorization"]["maximum_item_use_dispatches"],
            1,
        )
        self.assertEqual(
            [transition["from"] for transition in contract["transition_contracts"]],
            [
                "home_ready",
                "bag",
                "resources",
                "resource_list_progress",
                "1k_food_ready",
                "1k_food_used",
                "resource_delta_verified",
            ],
        )
        route_text = json.dumps(contract).casefold()
        self.assertNotIn("quest_screen", route_text)
        self.assertNotIn("selected_daily", route_text)
        self.assertNotIn("daily_progress", route_text)
        self.assertNotIn("catalog_admission", route_text)
        self.assertEqual(
            contract["cost_quantity_requirements"]["quantity"],
            1,
        )
        self.assertFalse(contract["cost_quantity_requirements"]["free_only"])
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 1)
        self.assertIn(
            "1K Food",
            contract["cost_quantity_requirements"]["resource_or_currency"],
        )
        self.assertIn("second confirmation", " ".join(contract["unsupported_or_manual_only_states"]))
        self.assertIn("In bulk", " ".join(contract["unsupported_or_manual_only_states"]))
        self.assertIn(
            "daily-resource-item:use-1k-food",
            contract["completion_identity"],
        )
        self.assertEqual(
            contract["product_authority_binding"]["binding_type"],
            "typed_product_record",
        )
        self.assertEqual(
            contract["product_authority_binding"]["home_authority"],
            "HOME_READY",
        )
        self.assertEqual(
            contract["product_authority_binding"]["terminal_home_authority"],
            "HOME_CANONICAL",
        )
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertIn(
            "optional current-frame-bound Resource & Speedup category tab when another Bag tab is selected",
            contract["permitted_inputs"],
        )

    def test_daily_resource_item_has_no_selected_daily_dependency(self):
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        queue_record = next(
            item
            for item in queue["flows"]
            if item["flow_id"] == "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
        )
        self.assertEqual(queue_record["dependencies"], [])
        self.assertEqual(queue_record["direct_dependencies"], [])
        self.assertEqual(queue_record["maximum_inputs"], 10)
        self.assertEqual(queue_record["maximum_resource_list_swipes"], 6)
        self.assertEqual(queue_record["production_registration"], "NOT_REGISTERED")
        self.assertFalse(queue_record["scheduler_enabled"])
        matrix_task = next(
            item
            for item in matrix["portfolio_reconciliation"]["ordered_atomic_tasks"]
            if item["task_id"] == "use-resource-item"
        )
        self.assertEqual(matrix_task["depends_on"], [])
        identity = next(
            item
            for item in matrix["portfolio_reconciliation"]["non_catalog_portfolio_ownership"]
            if item["identity"] == "use_resource_item"
        )
        self.assertNotIn("catalog_admission_state", identity)
        catalog_identity = catalog["implementation_reconciliation"]["use_resource_item"]
        self.assertNotIn("catalog_admitted", catalog_identity)
        self.assertNotIn("admission_state", catalog_identity)
        self.assertNotIn(
            "current_selected_daily_catalog_admission",
            json.dumps((queue_record, matrix_task, identity, catalog_identity)),
        )
        self.assertEqual(matrix_task["maximum_inputs"], 10)
        self.assertEqual(matrix_task["maximum_resource_list_swipes"], 6)
        self.assertEqual(catalog_identity["maximum_inputs"], 10)
        self.assertEqual(catalog_identity["maximum_resource_list_swipes"], 6)


if __name__ == "__main__":
    unittest.main()
