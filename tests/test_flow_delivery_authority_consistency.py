from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import flow_delivery_control as control


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY = ROOT / "tasks" / "flow_delivery_product_policy.json"
COVERAGE = ROOT / "tasks" / "flow_delivery_coverage.json"
REGISTRY = ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"
CAMPAIGN_FLOW_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
CAMPAIGN_POLICY_ID = "campaign-supported-destinations"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _campaign_policy_entry(policy: dict) -> dict:
    for entry in policy["policies"]:
        if entry.get("policy_id") == CAMPAIGN_POLICY_ID:
            return entry
    raise AssertionError(f"missing {CAMPAIGN_POLICY_ID}")


def _campaign_queue_flow(queue: dict) -> dict:
    for flow in queue["flows"]:
        if flow.get("flow_id") == CAMPAIGN_FLOW_ID:
            return flow
    raise AssertionError(f"missing queue flow {CAMPAIGN_FLOW_ID}")


def _campaign_coverage_entry(coverage: dict) -> dict:
    flows = coverage.get("flows")
    if isinstance(flows, dict):
        entry = flows.get(CAMPAIGN_FLOW_ID)
        if isinstance(entry, dict):
            return entry
    elif isinstance(flows, list):
        for entry in flows:
            if isinstance(entry, dict) and entry.get("flow_id") == CAMPAIGN_FLOW_ID:
                return entry
    raise AssertionError(f"missing coverage flow {CAMPAIGN_FLOW_ID}")


class AuthorityConsistencyTests(unittest.TestCase):
    def test_real_repo_authority_is_consistent(self) -> None:
        control.load_and_validate_authority_consistency()

        # Independent anchor: policy destinations must equal queue + coverage Campaign sets.
        policy = _read(POLICY)
        queue = _read(QUEUE)
        coverage = _read(COVERAGE)
        campaign_policy = _campaign_policy_entry(policy)
        expected_supported = set(campaign_policy["supported_story_destinations"])
        expected_rejected = set(campaign_policy["rejected_destinations"])
        queue_campaign = _campaign_queue_flow(queue)
        coverage_campaign = _campaign_coverage_entry(coverage)
        self.assertEqual(set(queue_campaign["supported_story_destinations"]), expected_supported)
        self.assertEqual(set(queue_campaign["rejected_destinations"]), expected_rejected)
        self.assertEqual(
            set(coverage_campaign["supported_story_destinations"]), expected_supported
        )
        self.assertEqual(set(coverage_campaign["rejected_destinations"]), expected_rejected)

    def test_destination_drift_raises(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        drifted_policy = deepcopy(policy)
        campaign = _campaign_policy_entry(drifted_policy)
        # Derive baseline from policy so the assertion is not circular vs queue/coverage.
        baseline = set(campaign["supported_story_destinations"])
        campaign["supported_story_destinations"] = list(baseline) + ["bogus-9-9-9"]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(
                queue, drifted_policy, coverage, registry
            )

    def test_destination_value_drift_raises(self) -> None:
        queue = deepcopy(_read(QUEUE))
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_queue_flow(queue)
        supported = list(campaign["supported_story_destinations"])
        self.assertTrue(supported, "expected at least one supported destination")
        supported[0] = f"{supported[0]}-drifted"
        campaign["supported_story_destinations"] = supported
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_registry_class_drift_raises(self) -> None:
        queue = deepcopy(_read(QUEUE))
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = next(
            flow for flow in queue["flows"] if flow["flow_id"] == CAMPAIGN_FLOW_ID
        )
        campaign["product_policy_status"] = "supervised_consequential_validation"
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_membership_drift_raises(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = deepcopy(_read(REGISTRY))
        registry["flows"]["NOT-IN-QUEUE-FLOW"] = {
            "runner": "x",
            "evidence_validator": "y",
            "recovery_handler": "z",
            "consequence_class": "navigation_only",
        }
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_missing_policy_entry_raises(self) -> None:
        queue = _read(QUEUE)
        policy = deepcopy(_read(POLICY))
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        policy["policies"] = [
            entry
            for entry in policy["policies"]
            if entry.get("policy_id") != CAMPAIGN_POLICY_ID
        ]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_coverage_id_absent_from_queue_raises(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = deepcopy(_read(COVERAGE))
        registry = _read(REGISTRY)
        flows = coverage["flows"]
        if isinstance(flows, dict):
            flows["BOGUS-COVERAGE-ONLY-FLOW"] = {
                "supported_story_destinations": [],
                "rejected_destinations": [],
            }
        else:
            flows.append(
                {
                    "flow_id": "BOGUS-COVERAGE-ONLY-FLOW",
                    "supported_story_destinations": [],
                    "rejected_destinations": [],
                }
            )
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_unknown_consequence_class_fails_closed(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = deepcopy(_read(REGISTRY))
        registry_flow = next(iter(registry["flows"].values()))
        registry_flow["consequence_class"] = "not_a_real_class"
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_validator_does_not_mutate_inputs(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        before = {
            "queue": deepcopy(queue),
            "policy": deepcopy(policy),
            "coverage": deepcopy(coverage),
            "registry": deepcopy(registry),
        }
        control.validate_authority_consistency(queue, policy, coverage, registry)
        self.assertEqual(queue, before["queue"])
        self.assertEqual(policy, before["policy"])
        self.assertEqual(coverage, before["coverage"])
        self.assertEqual(registry, before["registry"])
        self.assertEqual(queue.get("gameplay_scheduler"), before["queue"].get("gameplay_scheduler"))
        for flow, prior in zip(queue["flows"], before["queue"]["flows"]):
            self.assertEqual(flow.get("live_attempts"), prior.get("live_attempts"))

    def test_validate_cli_invokes_authority_check(self) -> None:
        mock_check = Mock()
        with patch.object(
            control, "load_and_validate_authority_consistency", mock_check
        ):
            # Other validate gates may fail before/after; authority call must still occur
            # once when reached. Patch controller gates so we prove the wiring itself.
            # Also stub O4 contract-ref loader so this slice-1 test stays isolated.
            with patch.object(
                control, "load_and_validate_contract_policy_refs", Mock()
            ):
                with patch.object(control.FlowDeliveryController, "load", return_value=None):
                    with patch.object(
                        control.FlowDeliveryController, "lease", return_value=None
                    ):
                        with patch.object(
                            control.FlowDeliveryController,
                            "load_parent_progress",
                            return_value=None,
                        ):
                            code = control.main(["validate"])
        self.assertEqual(code, 0)
        mock_check.assert_called_once_with(
            queue_path=control.DEFAULT_QUEUE_PATH,
            policy_path=control.DEFAULT_POLICY_PATH,
            coverage_path=control.DEFAULT_COVERAGE_PATH,
            registry_path=control.DEFAULT_REGISTRY_PATH,
        )

    def test_validate_cli_surfaces_authority_failure(self) -> None:
        with patch.object(
            control,
            "load_and_validate_authority_consistency",
            side_effect=control.FlowDeliveryError("boom"),
        ):
            with patch.object(control.FlowDeliveryController, "load", return_value=None):
                with patch.object(
                    control.FlowDeliveryController, "lease", return_value=None
                ):
                    with patch.object(
                        control.FlowDeliveryController,
                        "load_parent_progress",
                        return_value=None,
                    ):
                        code = control.main(["validate"])
        # Existing main() handler maps FlowDeliveryError -> exit 2 (nonzero).
        self.assertNotEqual(code, 0)
        self.assertEqual(code, 2)

    def test_real_repo_contract_policy_refs_resolve(self) -> None:
        control.load_and_validate_contract_policy_refs()

    def test_contract_policy_ref_unknown_policy_id_raises(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "BOGUS-CONTRACT": {
                "flow_id": "BOGUS-CONTRACT",
                "product_policy_refs": [
                    {
                        "policy_id": "does-not-exist",
                        "source": "tasks/flow_delivery_product_policy.json",
                    }
                ],
            }
        }
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_contract_policy_ref_nonpolicy_source_ignored(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "CODE-POLICY-REF": {
                "flow_id": "CODE-POLICY-REF",
                "product_policy_refs": [
                    {
                        "policy_id": "does-not-exist",
                        "source": "safe_action_core.CentralPolicy",
                    }
                ],
            }
        }
        control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_contract_without_policy_refs_is_skipped(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "V1-NO-REFS": {
                "flow_id": "V1-NO-REFS",
            }
        }
        control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_contract_ref_missing_source_raises(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "MISSING-SOURCE": {
                "flow_id": "MISSING-SOURCE",
                "product_policy_refs": [
                    {"policy_id": "nova-navigation-only"},
                ],
            }
        }
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_contract_ref_missing_policy_id_raises(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "MISSING-POLICY-ID": {
                "flow_id": "MISSING-POLICY-ID",
                "product_policy_refs": [
                    {"source": "tasks/flow_delivery_product_policy.json"},
                ],
            }
        }
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_contract_empty_policy_refs_list_ok(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "EMPTY-REFS": {
                "flow_id": "EMPTY-REFS",
                "product_policy_refs": [],
            }
        }
        control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_duplicate_contract_flow_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contracts_dir = Path(tmp)
            shared_flow_id = "DUP-FLOW-ID"
            for name in ("a.json", "b.json"):
                (contracts_dir / name).write_text(
                    json.dumps({"flow_id": shared_flow_id}),
                    encoding="utf-8",
                )
            with self.assertRaises(control.FlowDeliveryError):
                control.load_and_validate_contract_policy_refs(
                    policy_path=POLICY,
                    contracts_dir=contracts_dir,
                )

    def test_spoof_policy_source_name_not_treated_as_registry(self) -> None:
        policy = _read(POLICY)
        real_policy_ids = {
            entry["policy_id"] for entry in policy["policies"] if "policy_id" in entry
        }
        contracts = {
            "SPOOF-SOURCE": {
                "flow_id": "SPOOF-SOURCE",
                "product_policy_refs": [
                    {
                        "policy_id": "does-not-exist",
                        "source": "evil_flow_delivery_product_policy.json",
                    }
                ],
            }
        }
        control.validate_contract_policy_refs(real_policy_ids, contracts)

    def test_validate_cli_invokes_contract_ref_check(self) -> None:
        mock_check = Mock()
        with patch.object(
            control, "load_and_validate_contract_policy_refs", mock_check
        ):
            with patch.object(
                control, "load_and_validate_authority_consistency", return_value=None
            ):
                with patch.object(control.FlowDeliveryController, "load", return_value=None):
                    with patch.object(
                        control.FlowDeliveryController, "lease", return_value=None
                    ):
                        with patch.object(
                            control.FlowDeliveryController,
                            "load_parent_progress",
                            return_value=None,
                        ):
                            code = control.main(["validate"])
        self.assertEqual(code, 0)
        mock_check.assert_called_once_with(
            policy_path=control.DEFAULT_POLICY_PATH,
            contracts_dir=control.DEFAULT_CONTRACTS_DIR,
        )


if __name__ == "__main__":
    unittest.main()
