"""Focused tests for gameplay flow contracts and dependency regression marking."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from tasks.gameplay_flow_contracts import (
    CONTRACTS_DIR,
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
        self.assertEqual(queue_ids, contract_ids)
        contracts = load_all_flow_contracts()
        self.assertEqual(len(contracts), len(queue_ids))
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
