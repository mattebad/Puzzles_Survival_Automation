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
from tasks.product_authority import AUTHORITY_REVISION


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"
MATRIX_PATH = ROOT / "tasks" / "daily_quest_execution_matrix.json"
CATALOG_PATH = ROOT / "tasks" / "daily_quest_catalog.json"


class GameplayFlowContractTests(unittest.TestCase):
    def test_all_queue_flows_have_schema_valid_contracts(self):
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        queue_ids = {item["flow_id"] for item in queue["flows"]}
        contract_ids = set(list_flow_contract_ids())
        default_ids = set(pnsctl._DEFAULT_MAX_INPUTS)
        self.assertTrue(queue_ids <= contract_ids)
        self.assertEqual(
            contract_ids - queue_ids,
            {"PERSONAL-MIGHT-PRAISE-BLISS-PILOT"} | (default_ids - queue_ids),
        )
        contracts = load_all_flow_contracts()
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

    def test_ruins_shop_purchase_contract_is_observation_only_and_blocked(self):
        contract = load_flow_contract("RUINS-SHOP-PURCHASE-EVIDENCE-GATE")
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["product_policy_refs"][0]["policy_id"], "ruins-shop-purchase-policy")
        self.assertEqual(contract["permitted_inputs"], [])
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 15)
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "RUINS_COINS",
        )
        self.assertEqual(contract["implementation_status"], "contract_only")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        scenario = contract["scenarios"][0]
        self.assertEqual(scenario["mode"], "blocked_until_evidence")
        self.assertEqual(scenario["permitted_inputs"], [])
        self.assertEqual(contract["product_authority_binding"]["product_record_id"], "ruins_shop_purchase")

    def test_rare_earth_shop_contract_is_observation_only_and_unknown_cost_fails_closed(self):
        contract = load_flow_contract("RARE-EARTH-SHOP-PURCHASE-EVIDENCE-GATE")
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["product_policy_refs"][0]["policy_id"], "rare-earth-shop-purchase-policy")
        self.assertEqual(contract["permitted_inputs"], [])
        self.assertIsNone(contract["cost_quantity_requirements"]["maximum_cost"])
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "UNKNOWN_CURRENT_CURRENCY",
        )
        self.assertEqual(contract["implementation_status"], "contract_only")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        scenario = contract["scenarios"][0]
        self.assertEqual(scenario["mode"], "blocked_until_evidence")
        self.assertEqual(scenario["permitted_inputs"], [])
        self.assertEqual(contract["product_authority_binding"]["product_record_id"], "rare_earth_shop_purchase")
    def test_alliance_shop_contract_binds_approved_one_item_choice_but_stays_disabled(self):
        contract = load_flow_contract("ALLIANCE-SHOP-PURCHASE-EVIDENCE-GATE")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["product_policy_refs"][0]["policy_id"],
            "alliance-shop-purchase-policy",
        )
        self.assertEqual(binding["product_record_id"], "alliance_shop_purchase")
        self.assertEqual(binding["product_record_revision"], "alliance_shop_purchase-v3")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertIsNone(contract["cost_quantity_requirements"]["maximum_cost"])
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "Alliance Coins",
        )
        transitions = {
            item["transition_id"]: item for item in contract["transition_contracts"]
        }
        self.assertEqual(
            transitions["no_affordable_preferred_offer"]["from"],
            "weekly_inventory_current",
        )
        self.assertEqual(
            transitions["no_affordable_preferred_offer"]["to"],
            "preferred_offer_unaffordable_or_absent",
        )
        self.assertEqual(
            transitions["evaluate_exact_fallback"]["from"],
            "preferred_offer_unaffordable_or_absent",
        )
        self.assertEqual(contract["evidence_gates"][0]["status"], "evidence_required")
        self.assertEqual(contract["evidence_gates"][0]["permitted_inputs"], [])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])

        scenarios = {item["scenario_id"]: item for item in contract["scenarios"]}
        self.assertEqual(
            scenarios["alliance_shop_preferred_purchase_production"]["required_transitions"],
            [
                "open_alliance_shop",
                "bind_complete_weekly_inventory",
                "select_affordable_preferred_offer",
                "verify_numeric_purchase_quantity",
                "buy_one_preferred_or_fallback",
                "reconcile_exact_purchase_acknowledgement",
                "return_canonical_home",
            ],
        )
        self.assertEqual(
            scenarios["alliance_shop_fallback_purchase_production"]["required_transitions"],
            [
                "open_alliance_shop",
                "bind_complete_weekly_inventory",
                "no_affordable_preferred_offer",
                "evaluate_exact_fallback",
                "verify_fallback_quantity",
                "buy_one_preferred_or_fallback",
                "reconcile_exact_purchase_acknowledgement",
                "return_canonical_home",
            ],
        )
        self.assertTrue(
            all(item["mode"] == "blocked_until_evidence" for item in scenarios.values())
        )
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])

    def test_alliance_donation_contract_tracks_actual_reset_scoped_actions(self):
        contract = load_flow_contract(
            "ALLIANCE-TECH-DONATION-BLUESTACKS-INTEGRATION"
        )
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "alliance_donation")
        self.assertEqual(binding["product_record_revision"], "alliance_donation-v2")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(contract["trigger_cadence_type"], "cooldown_pulse")
        self.assertEqual(contract["reset_scope"], "daily_reset")
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "ORDINARY_RESOURCE",
        )
        transitions = {
            item["transition_id"]: item for item in contract["transition_contracts"]
        }
        self.assertEqual(
            transitions["dispatch_one_donation"]["to"],
            "donation_effect_pending",
        )
        self.assertEqual(
            transitions["commit_one_positive_donation_effect"]["from"],
            "donation_effect_pending",
        )
        self.assertEqual(
            transitions["stop_at_ten_confirmed_actions"]["to"],
            "quota_reached",
        )
        self.assertIn("no_attempt_available", contract["recognized_states"])
        self.assertIn("quota_partial_persisted", contract["recognized_states"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])

    def test_daily_shops_contract_retains_independent_two_tab_partial_results(self):
        contract = load_flow_contract("DAILY-SHOPS-PURCHASE-EVIDENCE-GATE")
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "daily_shops_purchase")
        self.assertEqual(binding["product_record_revision"], "daily_shops_purchase-v2")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertIsNone(contract["cost_quantity_requirements"]["quantity"])
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "CURRENT_TAB_CURRENCY",
        )
        transitions = {
            item["transition_id"]: item for item in contract["transition_contracts"]
        }
        self.assertEqual(
            transitions["skip_zero_or_unavailable_tab"]["to"],
            "zero_quantity_tab_skipped",
        )
        self.assertEqual(
            transitions["continue_after_ruins_tab_skipped"]["from"],
            "zero_quantity_tab_skipped",
        )
        self.assertEqual(
            transitions["continue_after_ruins_tab_skipped"]["to"],
            "rare_earth_tab_current",
        )
        self.assertEqual(
            transitions["skip_zero_or_unavailable_rare_earth_tab"]["to"],
            "rare_earth_tab_result_recorded",
        )
        self.assertIn("ruins_tab_result_recorded", contract["recognized_states"])
        self.assertIn("rare_earth_tab_result_recorded", contract["recognized_states"])
        partial_transition = transitions["preserve_known_partial_visit"]
        self.assertEqual(partial_transition["to"], "independent_partial_results")
        self.assertEqual(partial_transition["terminal_outcomes"], ["deferred"])
        self.assertIsNone(partial_transition["permitted_input"])
        self.assertEqual(
            transitions["return_canonical_home_after_partial_tabs"]["from"],
            "independent_partial_results",
        )
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])

        partial = next(
            item
            for item in contract["scenarios"]
            if item["scenario_id"] == "daily_shops_partial_two_tab_visit"
        )
        self.assertEqual(
            partial["required_transitions"],
            [
                "open_ruins_from_current_home",
                "open_shared_shop_exchange",
                "bind_ruins_tab_offer_and_quantity",
                "skip_zero_or_unavailable_tab",
                "continue_after_ruins_tab_skipped",
                "bind_rare_earth_offer_and_quantity",
                "verify_rare_earth_numeric_quantity_and_total",
                "buy_rare_earth_verified_quantity",
                "record_rare_earth_tab_result",
                "return_canonical_home_after_both_tabs",
            ],
        )
        self.assertEqual(partial["permitted_inputs"], [])
        self.assertEqual(partial["mode"], "blocked_until_evidence")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])

    def test_hero_duel_contract_binds_approved_cycle_semantics_but_stays_disabled(self):
        contract = load_flow_contract("HERO-DUEL-EVIDENCE-GATE")
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["product_policy_refs"][0]["policy_id"],
            "hero-duel-policy",
        )
        cost = contract["cost_quantity_requirements"]
        self.assertEqual(cost["maximum_cost"], 0)
        self.assertTrue(cost["free_only"])
        self.assertEqual(cost["resource_or_currency"], "NO_RESOURCE_SPEND")
        self.assertEqual(cost["quantity"], 1)
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["offline_proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["product_authority_binding"]["product_record_id"], "hero_duel")
        self.assertEqual(
            contract["product_authority_binding"]["product_record_revision"], "hero_duel-v2"
        )
        self.assertFalse(
            contract["product_authority_binding"]["selected_daily_prerequisite"]
        )
        self.assertEqual(contract["evidence_gates"][0]["status"], "evidence_required")
        self.assertEqual(contract["evidence_gates"][0]["permitted_inputs"], [])
        scenario = contract["scenarios"][0]
        self.assertEqual(scenario["mode"], "blocked_until_evidence")
        self.assertEqual(scenario["permitted_inputs"], [])
        self.assertEqual(scenario["forbidden_inputs"], [])
        transitions = contract["transition_contracts"]
        self.assertIn(
            "dispatch_one_free_entry",
            {transition["transition_id"] for transition in transitions},
        )
        self.assertIn(
            "return_canonical_home",
            {transition["transition_id"] for transition in transitions},
        )

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


    def test_campaign_ap_contract_binds_typed_record_and_preserves_disabled_state(self):
        contract = load_flow_contract("CAMPAIGN-AP-AUTO-BATTLE")
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "campaign_ap")
        self.assertEqual(binding["product_record_revision"], "campaign_ap-v1")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 20)
        self.assertEqual(contract["cost_quantity_requirements"]["resource_or_currency"], "CAMPAIGN_AP")
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")

    def test_troop_training_contract_binds_four_type_product_record_and_stays_disabled(self):
        contract = load_flow_contract("TROOP-TRAINING-END-TO-END-CONSOLIDATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "troop_training")
        self.assertEqual(binding["product_record_revision"], "troop_training-v3")
        self.assertIn(
            "commander-talent-preset-helper",
            [ref["policy_id"] for ref in contract["product_policy_refs"]],
        )
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["proof_state"], "evidence_required")

    def test_world_navigation_contract_binds_typed_record_and_stays_navigation_only(self):
        contract = load_flow_contract("WORLD-MAP-NAVIGATION-FOUNDATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "world_map_navigation")
        self.assertEqual(binding["product_record_revision"], "world_map_navigation-v1")
        self.assertEqual(binding["home_authority"], "HOME_READY")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["consequential_action_class"], "none")
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["proof_state"], "evidence_required")
    def test_vip_points_popup_contract_binds_bounded_helper_and_stays_disabled(self):
        contract = load_flow_contract("VIP-GET-PTS-POPUP-DISMISSAL")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "vip_points_popup_dismissal")
        self.assertEqual(binding["product_record_revision"], "vip_points_popup_dismissal-v1")
        self.assertEqual(binding["home_authority"], "HOME_READY")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["consequential_action_class"], "vip_popup_dismissal_candidate_observation")
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["permitted_inputs"], [])
        self.assertEqual(contract["scenarios"][0]["permitted_inputs"], [])

    def test_gathering_contract_binds_direct_timer_variants_and_stays_evidence_gated(self):
        contract = load_flow_contract("GATHERING-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["trigger_cadence_type"], "evidence_gated")
        self.assertEqual(contract["reset_scope"], "pulse_and_march_slot_timer")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "gathering_resources")
        self.assertEqual(binding["product_record_revision"], "gathering_resources-v3")
        self.assertEqual(binding["home_authority"], "HOME_READY")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["consequential_action_class"], "gathering_march")
        self.assertIsNone(contract["cost_quantity_requirements"]["maximum_cost"])
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertIn("select_food", contract["scenarios"][0]["forbidden_inputs"])
        self.assertIn("dispatch_attack", contract["scenarios"][0]["forbidden_inputs"])
        self.assertIn("retry_identical_dispatch", contract["scenarios"][0]["forbidden_inputs"])

    def test_recommended_research_contract_enforces_first_row_idle_queue_and_exact_costs(self):
        contract = load_flow_contract("RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["trigger_cadence_type"], "daily_once")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "recommended_research")
        self.assertEqual(binding["product_record_revision"], "recommended_research-v1")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(
            set(contract["permitted_inputs"]),
            {
                "navigate_to_research_center",
                "select_first_displayed_recommendation_row_research",
                "tap_detail_research_once",
                "return_to_canonical_home",
            },
        )
        cost = contract["cost_quantity_requirements"]
        self.assertEqual(cost["quantity"], 1)
        self.assertIsNone(cost["maximum_cost"])
        self.assertEqual(cost["resource_or_currency"], "FOOD_WOOD_STEEL_GAS")
        transitions = {item["transition_id"]: item for item in contract["transition_contracts"]}
        self.assertEqual(
            transitions["select_first_recommendation_row"]["to"], "research_detail"
        )
        self.assertEqual(
            transitions["select_first_recommendation_row"]["permitted_input"],
            "select_first_displayed_recommendation_row_research",
        )
        self.assertEqual(
            transitions["start_one_detail_research"]["permitted_input"],
            "tap_detail_research_once",
        )
        self.assertIn(
            "every current prerequisite",
            " ".join(transitions["verify_prerequisites_costs_and_balances"]["postconditions"]).casefold(),
        )
        self.assertIn(
            "all four ordinary resource debits",
            " ".join(transitions["verify_queue1_start_and_timer"]["postconditions"]).casefold(),
        )
        unsupported = " ".join(contract["unsupported_or_manual_only_states"]).casefold()
        for marker in ("research now", "queue 2", "box", "alternate technology", "gathering"):
            self.assertIn(marker, unsupported)
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["evidence_gates"][0]["permitted_inputs"], [])
        self.assertEqual(contract["scenarios"][0]["permitted_inputs"], [])

        invalid = deepcopy(contract)
        next(
            item
            for item in invalid["transition_contracts"]
            if item["transition_id"] == "start_one_detail_research"
        )["permitted_input"] = "research_now_diamonds"
        with self.assertRaises(FlowContractError):
            validate_flow_contract(invalid)

    def test_food_farm_contract_accounts_for_collection_and_caps_exact_diamond_fallback(self):
        contract = load_flow_contract("FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["trigger_cadence_type"], "daily_once")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "food_farm_output_boost")
        self.assertEqual(binding["product_record_revision"], "food_farm_output_boost-v1")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(
            set(contract["permitted_inputs"]),
            {
                "tap_current_mapped_food_farm_once",
                "use_one_owned_matching_food_farm_item",
                "buy_one_current_food_farm_one_day_diamond_option",
                "return_to_canonical_home",
            },
        )
        cost = contract["cost_quantity_requirements"]
        self.assertEqual(cost["quantity"], 1)
        self.assertEqual(cost["maximum_cost"], 48)
        self.assertEqual(cost["resource_or_currency"], "MATCHING_FOOD_FARM_ITEM_OR_DIAMONDS")
        self.assertIn("cap is not the current price", cost["notes"])
        transitions = {item["transition_id"]: item for item in contract["transition_contracts"]}
        self.assertLess(
            [item["transition_id"] for item in contract["transition_contracts"]].index(
                "reconcile_entry_collection"
            ),
            [item["transition_id"] for item in contract["transition_contracts"]].index(
                "apply_one_owned_matching_item"
            ),
        )
        self.assertIn(
            "multiple buildings",
            " ".join(transitions["enter_mapped_food_farm"]["postconditions"]).casefold(),
        )
        self.assertIn(
            "independently observed as zero",
            " ".join(transitions["observe_exact_diamond_offer_when_no_item"]["postconditions"]).casefold(),
        )
        self.assertIn(
            "48-diamond authorization cap",
            " ".join(transitions["apply_one_exact_diamond_boost"]["postconditions"]).casefold(),
        )
        self.assertIn(
            "positive current timer",
            " ".join(transitions["verify_active_boosting_timer"]["postconditions"]).casefold(),
        )
        unsupported = " ".join(contract["unsupported_or_manual_only_states"]).casefold()
        for marker in ("item action cost mistaken for inventory count", "global food output boost", "second boost"):
            self.assertIn(marker, unsupported)
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["evidence_gates"][0]["permitted_inputs"], [])
        self.assertEqual(contract["scenarios"][0]["permitted_inputs"], [])

        invalid = deepcopy(contract)
        next(
            item
            for item in invalid["transition_contracts"]
            if item["transition_id"] == "apply_one_exact_diamond_boost"
        )["permitted_input"] = "buy_global_food_output_boost"
        with self.assertRaises(FlowContractError):
            validate_flow_contract(invalid)

    def test_hall_zombie_zero_contract_separates_dispatch_and_reward_claim(self):
        contract = load_flow_contract("HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["trigger_cadence_type"], "daily_once")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "hall_of_war_zombie_zero")
        self.assertEqual(binding["product_record_revision"], "hall_of_war_zombie_zero-v1")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(
            set(contract["permitted_inputs"]),
            {
                "navigate_to_hall_of_war",
                "open_zombie_zero",
                "select_and_apply_saved_troop_set_one",
                "dispatch_one_zombie_zero",
                "tap_own_glowing_daily_reward_row_once",
                "return_to_canonical_home",
            },
        )
        cost = contract["cost_quantity_requirements"]
        self.assertTrue(cost["free_only"])
        self.assertEqual(cost["maximum_cost"], 0)
        self.assertEqual(cost["quantity"], 1)
        transitions = {item["transition_id"]: item for item in contract["transition_contracts"]}
        self.assertIsNone(transitions["reconcile_prior_attempt_without_redispatch"]["permitted_input"])
        self.assertEqual(
            transitions["claim_own_glowing_reward_row_once"]["permitted_input"],
            "tap_own_glowing_daily_reward_row_once",
        )
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["evidence_gates"][0]["permitted_inputs"], [])
        self.assertEqual(contract["scenarios"][0]["permitted_inputs"], [])

        invalid = deepcopy(contract)
        next(
            item
            for item in invalid["transition_contracts"]
            if item["transition_id"] == "dispatch_one_zombie_zero"
        )["permitted_input"] = "dispatch_second_zombie_zero"
        with self.assertRaises(FlowContractError):
            validate_flow_contract(invalid)

    def test_zombie_lair_contracts_bind_one_record_and_stay_disabled(self):
        for flow_id in (
            "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
            "ZOMBIE-LAIR-HOME-MAINTENANCE",
        ):
            contract = load_flow_contract(flow_id)
            binding = contract["product_authority_binding"]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
                self.assertEqual(binding["product_record_id"], "zombie_lair")
                self.assertEqual(binding["product_record_revision"], "zombie_lair-v1")
                self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
                self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
                self.assertFalse(binding["selected_daily_prerequisite"])
                self.assertEqual(contract["registration_state"], "disabled")
                self.assertFalse(contract["production_eligible"])
                self.assertEqual(contract["proof_state"], "evidence_required")

    def test_nanoweapon_contract_binds_same_visit_maintenance_and_own_craft_success(self):
        contract = load_flow_contract("NANOWEAPON-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "nanoweapon_normal_craft")
        self.assertEqual(binding["product_record_revision"], "nanoweapon_normal_craft-v2")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(
            contract["consequential_action_class"],
            "same_visit_material_maintenance_then_one_normal_craft",
        )
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 100)
        self.assertFalse(contract["cost_quantity_requirements"]["free_only"])
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(
            contract["cost_quantity_requirements"]["resource_or_currency"],
            "NANO_PARTS",
        )
        transitions = {
            item["transition_id"]: item for item in contract["transition_contracts"]
        }
        self.assertEqual(
            transitions["open_material_production"]["from"],
            "craft_status_known",
        )
        self.assertEqual(
            transitions["open_material_production"]["permitted_input"],
            "select_material_production",
        )
        self.assertEqual(
            transitions["claim_completed_production"]["permitted_input"],
            "claim_material_production",
        )
        self.assertEqual(
            transitions["start_one_production"]["permitted_input"],
            "start_material_production",
        )
        self.assertEqual(
            transitions["inspect_normal_craft"]["from"],
            "prior_material_production_reconciled",
        )
        self.assertEqual(
            transitions["authorize_normal_craft"]["postconditions"][-2:],
            [
                "same_visit_record_70_maintenance_effect_is_current_and_reconciled",
                "maintenance_did_not_consume_the_normal_craft_reset_allowance",
            ],
        )
        self.assertIn(
            "own_current_NANOWEAPON_NORMAL_CRAFT_ACTIVE_successor_is_positive",
            transitions["start_one_normal_craft"]["postconditions"],
        )
        transition_inputs = {
            item["permitted_input"]
            for item in contract["transition_contracts"]
            if item["permitted_input"] is not None
        }
        self.assertEqual(transition_inputs, set(contract["permitted_inputs"]))
        scenarios = {item["scenario_id"]: item for item in contract["scenarios"]}
        normal = scenarios["nanoweapon_normal_craft_with_maintenance"]
        self.assertLess(
            normal["required_transitions"].index("reconcile_started_production"),
            normal["required_transitions"].index("start_one_normal_craft"),
        )
        claim_restart = scenarios["nanoweapon_claim_restart_then_craft"][
            "required_transitions"
        ]
        self.assertLess(
            claim_restart.index("claim_completed_craft"),
            claim_restart.index("claim_completed_production"),
        )
        self.assertLess(
            claim_restart.index("reconcile_started_production"),
            claim_restart.index("start_one_normal_craft"),
        )
        insufficient = scenarios["nanoweapon_insufficient_parts_after_maintenance"][
            "required_transitions"
        ]
        self.assertIn("defer_insufficient_parts", insufficient)
        self.assertNotIn("start_one_normal_craft", insufficient)
        revisit = scenarios["nanoweapon_maintenance_revisit_after_reset_quota"][
            "required_transitions"
        ]
        self.assertLess(
            revisit.index("reconcile_started_production"),
            revisit.index("observe_already_started"),
        )
        self.assertNotIn("start_one_normal_craft", revisit)
        self.assertIn(
            "record_active_production_due_time",
            scenarios["nanoweapon_active_maintenance_then_craft"][
                "required_transitions"
            ],
        )
        self.assertIn(
            "defer_active_craft",
            scenarios["nanoweapon_active_craft_after_maintenance"][
                "required_transitions"
            ],
        )
        self.assertTrue(
            all(
                item["mode"] == "blocked_until_evidence"
                and item["permitted_inputs"] == []
                for item in scenarios.values()
            )
        )
        self.assertTrue(
            all(
                item["status"] == "evidence_required"
                and item["permitted_inputs"] == []
                for item in contract["evidence_gates"]
            )
        )
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["proof_state"], "evidence_required")

    def test_nano_material_contract_binds_zero_resource_batch_and_stays_disabled(self):
        contract = load_flow_contract("NANO-MATERIAL-PRODUCTION-MAINTENANCE")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_id"], "nano_material_production")
        self.assertEqual(binding["product_record_revision"], "nano_material_production-v1")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(
            contract["consequential_action_class"],
            "zero_resource_claim_and_timed_maintenance_start",
        )
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["proof_state"], "not_implemented")
        self.assertEqual(contract["scenarios"][0]["mode"], "blocked_until_policy")
        self.assertEqual(contract["scenarios"][0]["permitted_inputs"], [])

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

    def test_recruitment_contracts_bind_one_r8_record_and_remain_evidence_gated(self):
        for flow_id in (
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
        ):
            contract = load_flow_contract(flow_id)
            binding = contract["product_authority_binding"]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
                self.assertEqual(binding["product_record_id"], "noahs_tavern_recruitment")
                self.assertEqual(binding["product_record_revision"], "noahs_tavern_recruitment-v1")
                self.assertEqual(binding["platform"], "bluestacks")
                self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
                self.assertFalse(binding["selected_daily_prerequisite"])
                self.assertEqual(contract["proof_state"], "evidence_required")
                self.assertFalse(contract["production_eligible"])
                self.assertEqual(contract["registration_state"], "disabled")

    def test_ruins_and_alliance_help_contracts_bind_product_semantics_and_stay_disabled(self):
        cases = (
            (
                "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
                "ruins_challenge",
                "ruins_challenge-v2",
            ),
            (
                "ALLIANCE-HELP-TEN-FREE-REQUESTS",
                "alliance_help",
                "alliance_help-v2",
            ),
        )
        for flow_id, record_id, record_revision in cases:
            contract = load_flow_contract(flow_id)
            binding = contract["product_authority_binding"]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(contract["schema_version"], 2)
                self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
                self.assertEqual(binding["product_record_id"], record_id)
                self.assertEqual(binding["product_record_revision"], record_revision)
                self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
                self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
                self.assertFalse(binding["selected_daily_prerequisite"])
                self.assertEqual(contract["trigger_cadence_type"], "cooldown_pulse")
                self.assertEqual(contract["reset_scope"], "daily_reset")
                self.assertEqual(contract["implementation_status"], "reference_implemented")
                self.assertEqual(contract["proof_state"], "evidence_required")
                self.assertEqual(contract["registration_state"], "disabled")
                self.assertFalse(contract["production_eligible"])
                self.assertTrue(
                    all(not gate["permitted_inputs"] for gate in contract["evidence_gates"])
                )
                scenario = contract["scenarios"][0]
                self.assertEqual(scenario["mode"], "blocked_until_evidence")
                self.assertEqual(scenario["permitted_inputs"], [])

        ruins = load_flow_contract("RUINS-CHALLENGE-HOME-ATLAS-MIGRATION")
        ruins_transitions = {
            item["transition_id"]: item for item in ruins["transition_contracts"]
        }
        self.assertIsNone(
            ruins_transitions["preserve-unknown-challenge-effect"]["permitted_input"]
        )
        self.assertIsNone(
            ruins_transitions["preserve-unknown-chest-effect"]["permitted_input"]
        )
        self.assertEqual(
            ruins_transitions["dispatch-allowlisted-zero-cost-challenge"]["permitted_input"],
            "one_current_allowlisted_zero_cost_attack_or_dispatch",
        )
        self.assertIn(
            "independently green-ready Stage Overview chest category",
            ruins["product_purpose"],
        )
        self.assertEqual(
            ruins_transitions["open-overview-after-unavailable-challenge"]["to"],
            "stage_overview",
        )
        self.assertEqual(
            ruins["cost_quantity_requirements"]["maximum_cost"],
            0,
        )
        self.assertIsNone(ruins["cost_quantity_requirements"]["quantity"])
        self.assertEqual(
            ruins_transitions["continue-after-verified-win"]["to"],
            "ruins_challenge_surface",
        )
        self.assertEqual(
            ruins_transitions["pause-challenge-at-finite-budget"]["terminal_outcomes"],
            ["deferred"],
        )
        self.assertIn(
            "first recognized loss durably stops",
            " ".join(ruins_transitions["dispatch-allowlisted-zero-cost-challenge"]["postconditions"]),
        )

        help_contract = load_flow_contract("ALLIANCE-HELP-TEN-FREE-REQUESTS")
        self.assertEqual(help_contract["cost_quantity_requirements"]["quantity"], 10)
        help_transitions = {
            item["transition_id"]: item
            for item in help_contract["transition_contracts"]
        }
        self.assertEqual(
            help_transitions["defer-when-free-help-is-unavailable"][
                "terminal_outcomes"
            ],
            ["deferred"],
        )
        self.assertEqual(
            help_transitions["stop-at-ten-successful-requests"][
                "terminal_outcomes"
            ],
            ["complete_for_reset"],
        )
        self.assertIsNone(
            help_transitions["preserve-unknown-request-effect"]["permitted_input"]
        )
        self.assertIn(
            "no complete request census",
            " ".join(help_transitions["bind-preferred-free-help-all"]["postconditions"]),
        )
        self.assertIn(
            "confirmed partial count survives restart",
            " ".join(help_transitions["resume-partial-reset-quota"]["postconditions"]),
        )
        self.assertEqual(
            help_transitions["preserve-unknown-request-effect"]["to"],
            "effect_reconciliation_required",
        )
        self.assertIn(
            "actual successful numeric credit reaches at least ten",
            help_contract["cooldown_deferred_behavior"],
        )
        self.assertEqual(
            help_transitions["defer-positive-batch-without-count"]["terminal_outcomes"],
            ["deferred"],
        )
        self.assertNotEqual(
            help_transitions["defer-positive-batch-without-count"]["to"],
            "effect_reconciliation_required",
        )
        self.assertIn(
            "without clipping even above ten",
            " ".join(help_transitions["reconcile-positive-request-successors"]["postconditions"]),
        )

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
            "evidence_required",
        )

    def test_published_schema_accepts_all_representative_contracts(self):
        schema = json.loads(
            (CONTRACTS_DIR / "schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        representative_ids = (
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION",
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
            "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION",
            "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
            "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-BLUESTACKS-INTEGRATION",
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
            "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
            "ALLIANCE-HELP-TEN-FREE-REQUESTS",
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

    def test_daily_claim_contract_combines_batch_claim_and_per_chest_collection(self):
        contract = load_flow_contract("DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["trigger_cadence_type"], "cooldown_pulse")
        self.assertEqual(contract["reset_scope"], "daily_reset")
        self.assertEqual(binding["product_record_id"], "aggregate_daily_claim")
        self.assertEqual(
            binding["product_record_revision"],
            "aggregate_daily_claim-v3",
        )
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        transitions = {item["transition_id"]: item for item in contract["transition_contracts"]}
        self.assertIn("dispatch-chest", transitions)
        self.assertIn(
            "unknown_chest_successor",
            contract["unsupported_or_manual_only_states"],
        )
        self.assertEqual(contract["implementation_status"], "reference_implemented")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertFalse(contract["production_eligible"])

    def test_daily_milestone_contract_requires_same_chest_successor_and_is_evidence_gated(self):
        contract = load_flow_contract("DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION")
        binding = contract["product_authority_binding"]
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["required_starting_context"], ["home_canonical"])
        self.assertEqual(binding["product_record_id"], "activity_milestone_claim")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_revision"], "activity_milestone_claim-v2")
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertEqual(contract["cost_quantity_requirements"]["maximum_cost"], 0)
        self.assertEqual(contract["cost_quantity_requirements"]["quantity"], 1)
        self.assertTrue(contract["cost_quantity_requirements"]["free_only"])
        self.assertEqual(contract["implementation_status"], "contract_only")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")
        transitions = {item["transition_id"]: item for item in contract["transition_contracts"]}
        self.assertEqual(
            transitions["dispatch-milestone"]["permitted_input"],
            "exactly_one_zero_cost_ready_milestone_chest_claim",
        )
        self.assertIn(
            "effect_reconciliation_required",
            contract["unsupported_or_manual_only_states"],
        )

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
                "owned_item_decrement_verified",
            ],
        )
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

    def test_contract_policy_refs_into_product_policy_resolve(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        policy_ids = {item["policy_id"] for item in policy["policies"]}
        checked = 0
        for flow_id, contract in load_all_flow_contracts().items():
            for ref in contract.get("product_policy_refs", []):
                if Path(str(ref["source"])).name != POLICY_PATH.name:
                    continue
                checked += 1
                with self.subTest(flow_id=flow_id, policy_id=ref["policy_id"]):
                    self.assertIn(ref["policy_id"], policy_ids)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
