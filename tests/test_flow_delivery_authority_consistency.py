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
    def test_approved_reconciliation_closes_only_named_product_decisions(self) -> None:
        policy = _read(POLICY)
        entries = {item["policy_id"]: item for item in policy["policies"]}
        for policy_id in (
            "campaign-ap-budget",
            "ultimate-challenge-unresolved-execution-details",
            "recruitment-quantity-and-resource-policy",
            "nanoweapon-material-policy",
            "nano-material-production-maintenance",
            "zombie-lair-level-stamina-march",
            "gathering-resource-node-march-policy",
            "troop-training-resource-policy",
        ):
            self.assertEqual(entries[policy_id]["status"], "explicitly_approved")
        gathering = entries["gathering-resource-node-march-policy"]
        self.assertIn("exact level 5", gathering["decision"])
        self.assertIn("one free march slot", gathering["decision"])
        self.assertIn("default formation", gathering["decision"])
        self.assertEqual(gathering["registration_status"], "NOT_REGISTERED")
        self.assertFalse(gathering["scheduler_eligibility"])
        self.assertIn("proving slice only", gathering["daily_catalog_boundary"])

    def test_affected_queue_flows_are_evidence_gated_and_not_live_authorized(self) -> None:
        queue = _read(QUEUE)
        affected = {
            "NANOWEAPON-BLUESTACKS-INTEGRATION",
            "NANO-MATERIAL-PRODUCTION-MAINTENANCE",
            "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
            "ZOMBIE-LAIR-HOME-MAINTENANCE",
        }
        by_id = {item["flow_id"]: item for item in queue["flows"]}
        for flow_id in affected:
            self.assertEqual(by_id[flow_id]["status"], "blocked")
            self.assertEqual(by_id[flow_id]["maximum_live_attempts"], 0)
            self.assertEqual(by_id[flow_id]["live_attempt_count"], 0)
        for flow_id in (
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        ):
            self.assertEqual(by_id[flow_id]["status"], "completed")
        for flow_id in (
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
        ):
            self.assertEqual(by_id[flow_id]["live_attempt_count"], 5)
            self.assertFalse(queue["gameplay_scheduler"])
        campaign = by_id[CAMPAIGN_FLOW_ID]
        self.assertEqual(campaign["status"], "completed")
        self.assertEqual(campaign["additional_live_attempts_authorized"], 14)
        self.assertEqual(campaign["maximum_live_attempts"], 14)
        self.assertEqual(campaign["live_attempt_count"], 14)
        self.assertEqual(campaign["historical_live_attempt_count"], 3)
        self.assertEqual(len(campaign["historical_live_attempts"]), 3)

    def test_recruitment_registry_consequence_matches_queue_validation_profile(self) -> None:
        queue = _read(QUEUE)
        registry = _read(REGISTRY)
        flow_id = "RECRUITMENT-BLUESTACKS-INTEGRATION"
        flow = {item["flow_id"]: item for item in queue["flows"]}[flow_id]
        registry_entry = registry["flows"][flow_id]
        self.assertEqual(registry_entry["consequence_class"], "consequential")
        self.assertEqual(
            flow["product_policy_status"],
            "supervised_consequential_validation",
        )
        self.assertEqual(flow["status"], "completed")
        self.assertEqual(flow["live_attempt_count"], 5)
        self.assertEqual(
            queue["portfolio_staging"]["registration_state"],
            "all newly scoped handlers NOT_REGISTERED",
        )
        self.assertIn("NOT_REGISTERED", flow["next_concrete_action"])
        self.assertFalse(queue["gameplay_scheduler"])

    def test_bioenhancer_registry_flow_has_blocked_non_scheduler_queue_owner(self) -> None:
        queue = _read(QUEUE)
        registry = _read(REGISTRY)
        by_id = {item["flow_id"]: item for item in queue["flows"]}
        flow_id = "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION"
        flow = by_id[flow_id]
        registry_entry = registry["flows"][flow_id]
        self.assertEqual(flow["status"], "blocked")
        self.assertEqual(flow["product_policy_status"], "supervised_consequential_validation")
        self.assertEqual(flow["registration_state"], "NOT_REGISTERED")
        self.assertFalse(flow["production_eligible"])
        self.assertFalse(flow["scheduler_eligibility"])
        self.assertEqual(flow["maximum_live_attempts"], 0)
        self.assertEqual(flow["live_attempt_count"], 0)
        self.assertEqual(
            registry_entry["runner"],
            "bioenhancer_free_research_bluestacks_runner",
        )
        self.assertEqual(
            registry_entry["evidence_validator"],
            "bioenhancer_free_research_bluestacks_evidence",
        )
        self.assertEqual(
            registry_entry["recovery_handler"],
            "bioenhancer_free_research_bluestacks_recovery",
        )
        self.assertIn("Free Research 1x", flow["consequence_policy"])
        self.assertIn("Aggregate Claim remains the sole Claim owner", flow["consequence_policy"])
        self.assertIn("existing Bioenhancer development runner", flow["next_concrete_action"])

    def test_supply_registry_flow_has_blocked_non_scheduler_queue_owner(self) -> None:
        queue = _read(QUEUE)
        registry = _read(REGISTRY)
        by_id = {item["flow_id"]: item for item in queue["flows"]}
        flow_id = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        self.assertIn(flow_id, by_id)
        self.assertIn(flow_id, registry["flows"])
        flow = by_id[flow_id]
        registry_entry = registry["flows"][flow_id]
        self.assertEqual(flow["status"], "blocked")
        self.assertEqual(
            flow["product_policy_status"],
            "supervised_consequential_validation",
        )
        self.assertEqual(flow["registration_state"], "NOT_REGISTERED")
        self.assertFalse(flow["production_eligible"])
        self.assertFalse(flow["scheduler_eligibility"])
        self.assertEqual(flow["maximum_live_attempts"], 0)
        self.assertEqual(flow["live_attempt_count"], 0)
        self.assertEqual(flow["live_attempts"], [])
        self.assertTrue(flow["requires_bluestacks_live"])
        self.assertIn(
            "scripts/flow_delivery_supply_depot_bluestacks.py",
            flow["implementation_entrypoints"],
        )
        self.assertEqual(
            registry_entry["runner"],
            "supply_depot_bluestacks_runner",
        )
        self.assertEqual(
            registry_entry["evidence_validator"],
            "supply_depot_bluestacks_evidence",
        )
        self.assertEqual(
            registry_entry["recovery_handler"],
            "supply_depot_bluestacks_recovery",
        )
        self.assertIn("evidence_required", flow["blocked_reason"])
        self.assertIn("evidence_required", flow["next_concrete_action"])
        self.assertIn("No live attempt is authorized", flow["live_validation_scope"])
        policy_text = flow["consequence_policy"].casefold()
        for prohibited in (
            "paid",
            "diamond",
            "ambiguous",
            "stale",
            "unknown",
            "identical-retry",
        ):
            self.assertIn(prohibited, policy_text)
        self.assertIn("transport or a hold alone", policy_text)
        self.assertIn("daily 5/5", policy_text)
        self.assertEqual(
            flow["focused_validation_receipt_digest"],
            "21d2184ba75969cdd7e1f75101eddde3f1edf69d1344255eb9564a236b0ca036",
        )
        self.assertEqual(
            flow["architecture_validation_receipt_digest"],
            "ff47b92baf60b59dcc859bf0fca1232ad0047717aab8fb25fb6f501ea4f06a0d",
        )

    def test_campaign_atlas_dependency_chain_authorizes_one_bounded_survey(self) -> None:
        queue = _read(QUEUE)
        by_id = {item["flow_id"]: item for item in queue["flows"]}
        prep = by_id["CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP"]
        survey = by_id["CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"]
        integration = by_id["CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY"]
        self.assertEqual(prep["status"], "completed")
        self.assertFalse(prep["requires_bluestacks_live"])
        self.assertEqual(survey["dependencies"], [prep["flow_id"]])
        self.assertEqual(integration["dependencies"], [survey["flow_id"]])
        for flow in (prep, integration):
            self.assertEqual(flow["maximum_live_attempts"], 0)
            self.assertEqual(flow["live_attempt_count"], 0)
            self.assertEqual(flow["additional_live_attempts_authorized"], 0)
        self.assertEqual(survey["live_attempt_count"], 1)
        self.assertEqual(survey["additional_live_attempts_authorized"], 1)
        self.assertEqual(survey["maximum_navigation_inputs"], 272)
        self.assertEqual(survey["navigation_inputs_used"], 93)
        self.assertEqual(
            survey["live_validation_scenarios"][0]["navigation_inputs_used"],
            93,
        )
        self.assertEqual(
            survey["navigation_budget_disposition"],
            "authorized_navigation_only_survey",
        )
        self.assertEqual(survey["maximum_live_attempts"], 1)
        self.assertEqual(survey["live_attempts"][0]["finished_at"], "2026-07-24T02:52:20.001438Z")
        self.assertEqual(survey["live_attempts"][0]["terminal_outcome"], "completed")
        self.assertIn(
            "survey-20260724T023336884972Z",
            str(survey["live_attempts"][0]["session_directory"]),
        )
        self.assertEqual(
            survey.get("survey_continuation_prior_session_ids"),
            [
                "survey-20260723T232154448911Z",
                "survey-20260724T000253173324Z",
                "survey-20260724T004227747200Z",
                "survey-20260724T012057293610Z",
                "survey-20260724T021222146973Z",
                "survey-20260724T023336884972Z",
            ],
        )
        diagnosis = str(survey["live_attempts"][0].get("diagnosis") or "")
        self.assertIn("survey-20260723T232154448911Z", diagnosis)
        self.assertIn("survey-20260724T000253173324Z", diagnosis)
        self.assertIn("survey-20260724T004227747200Z", diagnosis)
        self.assertIn("survey-20260724T012057293610Z", diagnosis)
        self.assertIn("survey-20260724T021222146973Z", diagnosis)
        self.assertIn("survey-20260724T023336884972Z", diagnosis)
        self.assertIn("93/272", diagnosis)
        self.assertEqual(survey["status"], "completed")
        self.assertEqual(survey["last_completed_stage"], "completed")
        self.assertIn(
            "tasks/assets/campaign_auto_battle/800x1280/campaign_exit_unhighlighted.png",
            survey["implementation_allowlist_seed"],
        )
        self.assertIn(
            "tasks/assets/campaign_auto_battle/800x1280/tier1_selected.png",
            survey["implementation_allowlist_seed"],
        )
        self.assertIn(
            "safe_action_core/policy.py",
            survey["implementation_allowlist_seed"],
        )
        self.assertEqual(survey["blocked_reason"], "")
        self.assertEqual(
            survey["focused_tests"],
            [
                "tests/test_campaign_atlas.py",
                "tests/test_campaign_atlas_vision.py",
                "tests/test_campaign_atlas_collector.py",
                "tests/test_flow_delivery_authority_consistency.py",
                "tests/test_flow_delivery_orchestrator.py",
                "tests/test_home_atlas_verified_route.py",
                "tests/test_personal_might_praise.py",
            ],
        )
        self.assertEqual(
            survey["completion_tests"],
            [
                "tests/test_campaign_atlas.py",
                "tests/test_campaign_atlas_vision.py",
                "tests/test_campaign_atlas_collector.py",
                "tests/test_flow_delivery_authority_consistency.py",
                "tests/test_flow_delivery_orchestrator.py",
                "tests/test_home_atlas_verified_route.py",
            ],
        )
        self.assertEqual(integration["maximum_live_attempts"], 0)
        self.assertEqual(integration["live_attempt_count"], 0)
        self.assertIn("tests/test_campaign_atlas_navigation.py", integration["focused_tests"])
        self.assertIn(
            "tests/test_campaign_atlas_navigation.py",
            integration["completion_tests"],
        )
        self.assertIn("scripts/flow_delivery_campaign_atlas_bluestacks.py", survey["implementation_entrypoints"])
        self.assertIn(
            "scripts/home_atlas_bluestacks.py",
            survey["implementation_entrypoints"],
        )
        self.assertIn(
            "scripts/flow_delivery_campaign_atlas_bluestacks.py",
            survey["implementation_allowlist_seed"],
        )
        self.assertIn(
            "scripts/home_atlas_bluestacks.py",
            survey["implementation_allowlist_seed"],
        )
        self.assertIn(
            "tests/test_flow_delivery_orchestrator.py",
            survey["implementation_allowlist_seed"],
        )
        self.assertIn(
            "tests/test_home_atlas_verified_route.py",
            survey["implementation_allowlist_seed"],
        )
        self.assertNotIn(
            "tests/test_navigation_session.py",
            survey["implementation_allowlist_seed"],
        )
        registry = _read(REGISTRY)
        survey_registry = registry["flows"]["CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"]
        self.assertEqual(survey_registry["runner"], "campaign_atlas_native_survey_runner")
        self.assertEqual(
            survey_registry["evidence_validator"],
            "campaign_atlas_native_survey_evidence",
        )
        self.assertEqual(
            survey_registry["recovery_handler"],
            "campaign_atlas_native_survey_recovery",
        )
        self.assertEqual(survey_registry["consequence_class"], "navigation_only")
        for consumer_id in (
            CAMPAIGN_FLOW_ID,
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        ):
            self.assertEqual(by_id[consumer_id]["dependencies"], [integration["flow_id"]])
        survey_text = json.dumps(survey).casefold()
        self.assertIn("without using difficulty switching as recentering", survey_text)
        prep_text = json.dumps(prep).casefold()
        for prohibited in (
            "no final atlas tiles or atlas geometry",
            "no semantic chapter, stage, or ultimate challenge anchors",
            "no recognition thresholds or threshold tuning",
            "no campaign localizer or navigator",
            "no production replay",
        ):
            self.assertIn(prohibited, prep_text)
        self.assertEqual(
            prep["focused_tests"],
            [
                "tests/test_campaign_atlas.py",
                "tests/test_campaign_atlas_vision.py",
                "tests/test_campaign_atlas_collector.py",
            ],
        )
        self.assertEqual(prep["completion_tests"], prep["focused_tests"])
        self.assertNotIn("future_required_tests", prep)
        self.assertEqual(prep["last_completed_stage"], "completed")
        self.assertFalse(queue["gameplay_scheduler"])
        self.assertEqual(by_id[CAMPAIGN_FLOW_ID]["status"], "completed")
        self.assertEqual(
            by_id["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]["status"],
            "completed",
        )

    def test_recruitment_native_evidence_is_complete_without_registration_promotion(self) -> None:
        coverage = _read(COVERAGE)["flows"]
        for flow_id in (
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
        ):
            payload = json.dumps(coverage[flow_id]).casefold()
            self.assertIn("gameplay", payload)
            self.assertIn("noahs-tavern-unified-recruitment-20260812t205031174713z", payload)
            self.assertIn("proven_through_retained_native_production_path", payload)
            self.assertIn("evidence_satisfied", payload)
            self.assertNotIn("evidence_required", payload)
            self.assertEqual(coverage[flow_id]["maximum_live_attempts"], 6)
            self.assertFalse(coverage[flow_id]["registered"])
            self.assertFalse(coverage[flow_id]["scheduler_eligible"])

    def test_real_repo_authority_is_consistent(self) -> None:
        control.load_and_validate_authority_consistency()

        # Independent anchor: product policy owns destination arrays; queue/coverage only ref.
        policy = _read(POLICY)
        queue = _read(QUEUE)
        coverage = _read(COVERAGE)
        campaign_policy = _campaign_policy_entry(policy)
        self.assertIsInstance(campaign_policy["supported_story_destinations"], list)
        self.assertIsInstance(campaign_policy["rejected_destinations"], list)
        self.assertTrue(campaign_policy["supported_story_destinations"])
        self.assertTrue(campaign_policy["rejected_destinations"])
        queue_campaign = _campaign_queue_flow(queue)
        coverage_campaign = _campaign_coverage_entry(coverage)
        self.assertEqual(queue_campaign["destination_policy_id"], CAMPAIGN_POLICY_ID)
        self.assertEqual(coverage_campaign["destination_policy_id"], CAMPAIGN_POLICY_ID)
        self.assertNotIn("supported_story_destinations", queue_campaign)
        self.assertNotIn("rejected_destinations", queue_campaign)
        self.assertNotIn("supported_story_destinations", coverage_campaign)
        self.assertNotIn("rejected_destinations", coverage_campaign)

    def test_malformed_policy_destination_raises(self) -> None:
        queue = _read(QUEUE)
        policy = deepcopy(_read(POLICY))
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_policy_entry(policy)
        campaign["supported_story_destinations"] = ["1-20-9", 99]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_missing_policy_destination_list_raises(self) -> None:
        queue = _read(QUEUE)
        policy = deepcopy(_read(POLICY))
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_policy_entry(policy)
        del campaign["supported_story_destinations"]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_missing_queue_destination_ref_raises(self) -> None:
        queue = deepcopy(_read(QUEUE))
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_queue_flow(queue)
        del campaign["destination_policy_id"]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_missing_coverage_destination_ref_raises(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = deepcopy(_read(COVERAGE))
        registry = _read(REGISTRY)
        campaign = _campaign_coverage_entry(coverage)
        del campaign["destination_policy_id"]
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_wrong_destination_ref_raises(self) -> None:
        queue = deepcopy(_read(QUEUE))
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_queue_flow(queue)
        campaign["destination_policy_id"] = "not-campaign-supported-destinations"
        with self.assertRaises(control.FlowDeliveryError):
            control.validate_authority_consistency(queue, policy, coverage, registry)

    def test_residual_queue_destination_arrays_raise(self) -> None:
        queue = deepcopy(_read(QUEUE))
        policy = _read(POLICY)
        coverage = _read(COVERAGE)
        registry = _read(REGISTRY)
        campaign = _campaign_queue_flow(queue)
        campaign["supported_story_destinations"] = list(
            _campaign_policy_entry(policy)["supported_story_destinations"]
        )
        with self.assertRaises(control.FlowDeliveryError) as raised:
            control.validate_authority_consistency(queue, policy, coverage, registry)
        self.assertIn("duplicate authority", str(raised.exception))
        self.assertIn("queue", str(raised.exception))

    def test_residual_coverage_destination_arrays_raise(self) -> None:
        queue = _read(QUEUE)
        policy = _read(POLICY)
        coverage = deepcopy(_read(COVERAGE))
        registry = _read(REGISTRY)
        campaign = _campaign_coverage_entry(coverage)
        campaign["rejected_destinations"] = list(
            _campaign_policy_entry(policy)["rejected_destinations"]
        )
        with self.assertRaises(control.FlowDeliveryError) as raised:
            control.validate_authority_consistency(queue, policy, coverage, registry)
        self.assertIn("duplicate authority", str(raised.exception))
        self.assertIn("coverage", str(raised.exception))

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
        self.assertFalse(queue.get("gameplay_scheduler"))
        for flow, prior in zip(queue["flows"], before["queue"]["flows"]):
            self.assertEqual(flow.get("maximum_live_attempts"), prior.get("maximum_live_attempts"))
            self.assertEqual(flow.get("live_attempt_count"), prior.get("live_attempt_count"))
            self.assertEqual(flow.get("live_attempts"), prior.get("live_attempts"))
            self.assertEqual(flow.get("named_scenarios"), prior.get("named_scenarios"))
            self.assertEqual(
                flow.get("product_policy_status"), prior.get("product_policy_status")
            )

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

    def test_real_repo_product_authority_bindings_resolve(self) -> None:
        policy = _read(POLICY)
        contracts = {}
        for flow_id in (
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
        ):
            contracts[flow_id] = _read(
                ROOT / "tasks" / "gameplay_flow_contracts" / f"{flow_id}.json"
            )
        control.validate_contract_policy_refs(
            {
                entry["policy_id"]
                for entry in policy["policies"]
                if "policy_id" in entry
            },
            contracts,
            authority=policy,
        )

    def test_stale_product_authority_binding_fails_closed(self) -> None:
        policy = _read(POLICY)
        contract = _read(
            ROOT
            / "tasks"
            / "gameplay_flow_contracts"
            / "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json"
        )
        contract["product_authority_binding"]["product_record_digest"] = "0" * 64
        with self.assertRaisesRegex(control.FlowDeliveryError, "stale product record digest"):
            control.validate_contract_policy_refs(
                {
                    entry["policy_id"]
                    for entry in policy["policies"]
                    if "policy_id" in entry
                },
                {"resource": contract},
                authority=policy,
            )

    def test_v2_policy_digest_is_required_by_control(self) -> None:
        policy = deepcopy(_read(POLICY))
        policy["authority_digest"] = "0" * 64
        with self.assertRaisesRegex(control.FlowDeliveryError, "product authority validation failed"):
            control.validate_policy(policy)

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
