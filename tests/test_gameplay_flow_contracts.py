"""Focused tests for gameplay flow contracts and dependency regression marking."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

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


class GameplayFlowContractTests(unittest.TestCase):
    def test_all_queue_flows_have_schema_valid_contracts(self):
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        queue_ids = {item["flow_id"] for item in queue["flows"]}
        contract_ids = set(list_flow_contract_ids())
        self.assertTrue(queue_ids <= contract_ids)
        self.assertEqual(contract_ids - queue_ids, {"PERSONAL-MIGHT-PRAISE-BLISS-PILOT"})
        contracts = load_all_flow_contracts()
        self.assertEqual(len(contracts), len(queue_ids) + 1)
        for flow_id, contract in contracts.items():
            validate_flow_contract(contract)
            self.assertEqual(contract["flow_id"], flow_id)
            if contract["implementation_status"] == "contract_only":
                self.assertTrue(
                    contract["evidence_requirements"] or contract["proof_state"] == "evidence_required"
                )
            if contract["implementation_status"] != "reference_implemented":
                self.assertNotEqual(contract["implementation_status"], "live_validated")
                self.assertNotEqual(contract["implementation_status"], "scheduler_eligible")

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

    def test_schema_v1_contracts_remain_readable(self):
        campaign = load_flow_contract(
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
        )
        self.assertEqual(campaign["schema_version"], 1)

    def test_shared_home_dependency_change_marks_nova_regression_required(self):
        contracts = load_all_flow_contracts()
        self.assertEqual(contracts["NOVA-PRAISE-HOME-ATLAS-MIGRATION"]["proof_state"], "evidence_required")
        updated = mark_regression_required_for_dependency(
            contracts,
            primitive_id="home_navigation_primitives",
        )
        self.assertEqual(updated["NOVA-PRAISE-HOME-ATLAS-MIGRATION"]["proof_state"], "evidence_required")
        # Non-dependent quest-screen contracts remain evidence_required / unchanged currentness.
        self.assertEqual(updated["DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"]["proof_state"], "evidence_required")

    def test_schema_file_exists(self):
        self.assertTrue((CONTRACTS_DIR / "schema.json").is_file())


if __name__ == "__main__":
    unittest.main()
