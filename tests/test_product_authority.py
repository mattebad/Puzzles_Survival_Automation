"""Focused tests for schema-v2 product authority and representative bindings."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_flow_authority_views import (
    AuthorityViewError,
    build_authority_view,
    check_authority_view,
    write_authority_view,
)
from tasks.gameplay_flow_contracts import load_all_flow_contracts
from tasks.product_authority import (
    AUTHORITY_REVISION,
    DAILY_RESET_POLICY_ID,
    DAILY_RESET_POLICY_INTERVAL_SECONDS,
    DAILY_RESET_POLICY_RESET_TIME,
    DAILY_RESET_POLICY_SOURCE,
    DAILY_RESET_POLICY_STATUS,
    DAILY_RESET_POLICY_TIMEZONE,
    ProductAuthorityError,
    authority_digest,
    canonical_digest,
    get_daily_reset_policy,
    load_product_authority,
    record_digest,
    validate_contract_product_authority_bindings,
    validate_daily_reset_policy,
    validate_product_authority,
    validate_product_record,
)
from tasks.purchases_disabled import (
    ALLIANCE_CURRENCY,
    ALLIANCE_FALLBACK_ITEM,
    ALLIANCE_OTHER_SHOP,
    ALLIANCE_WEEKLY_ITEMS,
    ALLIANCE_WEEKLY_SHOP,
    RARE_EARTH_CURRENCY,
    RARE_EARTH_MODULE_ITEM,
    RARE_EARTH_SHOP,
    RUINS_CHIP_ITEM,
    RUINS_CURRENCY,
    RUINS_SHOP,
    ShopOffer,
    alliance_shop_choice,
    daily_shop_quantity,
    purchase_dialog_matches,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"


class ProductAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = load_product_authority()
        self.contracts = load_all_flow_contracts()
        self.records = {
            record["record_id"]: record
            for record in self.authority["product_records"]
        }

    def test_authority_is_v2_and_has_exact_product_record_set(self) -> None:
        self.assertEqual(self.authority["schema_version"], 2)
        self.assertEqual(self.authority["authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(
            set(self.records),
            {
                "use_resource_item",
                "enhancement_family",
                "supply_depot",
                "aggregate_daily_claim",
                "activity_milestone_claim",
                "nova_praise",
                "ultimate_challenge",
                "bioenhancer_research",
                "noahs_tavern_recruitment",
                "campaign_ap",
                "troop_training",
                "gathering_resources",
                "zombie_lair",
                "ruins_shop_purchase",
                "ruins_challenge",
                "alliance_help",
                "rare_earth_shop_purchase",
                "alliance_shop_purchase",
                "alliance_donation",
                "daily_shops_purchase",
                "hero_upgrade",
                "hero_duel",
                "recommended_research",
                "food_farm_output_boost",
                "hall_of_war_zombie_zero",
                "nanoweapon_normal_craft",
                "nano_material_production",
                "vip_points_popup_dismissal",
                "world_map_navigation",
            },
        )
        validate_product_authority(self.authority)

    def test_record_type_discriminator_is_bound_to_record_identity(self) -> None:
        for record_id, wrong_type in (
            ("use_resource_item", "supply_depot"),
            ("recommended_research", "food_farm_output_boost"),
            ("food_farm_output_boost", "recommended_research"),
        ):
            changed = deepcopy(self.records[record_id])
            changed["record_type"] = wrong_type
            changed["record_digest"] = record_digest(changed)
            with self.subTest(record_id=record_id), self.assertRaisesRegex(
                ProductAuthorityError, "id/type discriminator mismatch"
            ):
                validate_product_record(changed)


    def test_aggregate_daily_claim_is_batch_scoped_and_the_only_selected_daily_owner(self) -> None:
        record = self.records["aggregate_daily_claim"]
        self.assertEqual(record["record_type"], "aggregate_daily_claim")
        self.assertEqual(record["record_revision"], "aggregate_daily_claim-v3")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(record["semantic_entry_route"]["target"], "DAILY")
        self.assertTrue(record["target"]["selected_daily"])
        self.assertFalse(record["target"]["row_local"])
        self.assertFalse(record["target"]["milestone"])
        self.assertTrue(record["target"]["current_ready_batch_required"])
        self.assertTrue(record["target"]["batch_identity_required"])
        self.assertEqual(record["target"]["control"], "Claim")
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["at_most_once_per_current_ready_batch_per_pass"])
        self.assertTrue(effect["distinct_later_ready_batch_allowed_same_reset"])
        self.assertTrue(effect["points_observation_optional"])
        self.assertTrue(effect["points_are_diagnostic_or_corroborative_only"])
        self.assertTrue(effect["points_are_not_a_success_gate_or_ownership_grant"])
        self.assertNotIn("positive_points_delta_required", effect)
        self.assertTrue(effect["ready_chests_independent_of_aggregate_claim_and_residual_ordinary_controls"])
        self.assertFalse(effect["complete_zero_claim_control_scan_required"])
        self.assertFalse(effect["all_chests_static_closure_required"])
        self.assertFalse(effect["points_threshold_required"])
        self.assertTrue(effect["sent_unknown_aggregate_claim_retains_runtime_stop"])
        self.assertEqual(
            record["aggregate_success_trigger"],
            {
                "action": "exact_free_aggregate_claim",
                "successor": "all_ordinary_claim_controls_cleared",
                "source_bounds": [
                    "current_frame",
                    "current_ready_batch_identity",
                    "daily_reset_identity",
                ],
            },
        )
        self.assertEqual(record["daily_ownership"]["daily_owner"], "aggregate_daily_claim")
        self.assertNotIn("point_credit_trigger", record["daily_ownership"])
        self.assertTrue(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        self.assertIn("150-point threshold prerequisite", forbidden)
        self.assertIn("daily objective-row inventory", forbidden)
        self.assertIn("per-objective daily attribution", forbidden)
        for record_id in (
            "use_resource_item",
            "enhancement_family",
            "supply_depot",
            "activity_milestone_claim",
            "nova_praise",
            "ultimate_challenge",
            "bioenhancer_research",
            "troop_training",
            "gathering_resources",
            "zombie_lair",
            "ruins_shop_purchase",
            "ruins_challenge",
            "alliance_help",
            "rare_earth_shop_purchase",
            "alliance_shop_purchase",
            "alliance_donation",
            "daily_shops_purchase",
            "hero_upgrade",
            "hero_duel",
            "recommended_research",
            "food_farm_output_boost",
            "hall_of_war_zombie_zero",
            "nanoweapon_normal_craft",
            "nano_material_production",
            "world_map_navigation",
        ):
            self.assertFalse(self.records[record_id]["daily_ownership"]["selected_daily_prerequisite"])
    def test_rare_earth_shop_candidate_keeps_unknown_cost_fail_closed(self) -> None:
        record = self.records["rare_earth_shop_purchase"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "rare-earth-shop-purchase-policy"
        )
        self.assertEqual(policy["status"], "unresolved_user_decision")
        self.assertFalse(policy["purchase_dispatch_allowed"])
        self.assertEqual(record["record_type"], "rare_earth_shop_purchase")
        self.assertEqual(record["semantic_entry_route"]["route"], ["RARE_EARTH_SHOP"])
        target = record["target"]
        self.assertEqual(target["candidate_item"], "unknown_current_three_star_item")
        self.assertEqual(target["candidate_rarity"], "3_STAR")
        self.assertEqual(target["candidate_currency"], "unknown_current_currency")
        self.assertIsNone(target["candidate_cost"])
        self.assertEqual(target["quantity"], 1)
        self.assertEqual(target["policy_status"], "unresolved_user_decision")
        self.assertFalse(target["purchase_dispatch_allowed"])
        cost = record["quantity_cost"]["cost"]
        self.assertIsNone(cost["amount"])
        self.assertEqual(cost["unit"], "UNKNOWN_CURRENT_CURRENCY")
        self.assertFalse(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_item_evidence_required"])
        self.assertTrue(effect["exact_cost_evidence_required"])
        self.assertTrue(effect["quantity_one_required"])
        self.assertFalse(effect["purchase_dispatch_allowed"])
        self.assertTrue(effect["canonical_home_successor_required"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "unknown item",
            "unknown cost",
            "unknown currency",
            "purchase dispatch",
            "insufficient balance",
        ):
            self.assertIn(marker, forbidden)

    def test_alliance_shop_approval_binds_exact_allowlist_and_one_item_fallback(self) -> None:
        record = self.records["alliance_shop_purchase"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "alliance-shop-purchase-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertFalse(policy["purchase_dispatch_allowed"])
        self.assertEqual(record["record_revision"], "alliance_shop_purchase-v4")
        target = record["target"]
        self.assertEqual(target["preferred_items"], list(ALLIANCE_WEEKLY_ITEMS))
        self.assertEqual(target["preferred_shop"], ALLIANCE_WEEKLY_SHOP)
        self.assertEqual(target["preferred_currency"], ALLIANCE_CURRENCY)
        self.assertEqual(target["approved_item_currency_pairs"], [
            ["joy_coin", "ALLIANCE_COINS"],
            ["timed_recruit_coin", "ALLIANCE_COINS"],
            ["bioenhance_scheme", "ALLIANCE_COINS"],
            ["one_star_gear_enhance_material", "ALLIANCE_COINS"],
            ["timed_recruit_coin", "DIAMONDS"],
        ])
        self.assertEqual(target["fallback_shop"], ALLIANCE_OTHER_SHOP)
        self.assertEqual(target["fallback_item"], ALLIANCE_FALLBACK_ITEM)
        self.assertEqual(target["fallback_rarity"], 1)
        self.assertEqual(target["maximum_quantity_total"], 1)
        self.assertTrue(target["unaffordable_preferred_permits_fallback"])
        self.assertFalse(target["purchase_dispatch_allowed"])
        self.assertFalse(target["premium_allowed"])
        self.assertFalse(target["cash_purchase_allowed"])
        self.assertFalse(target["alternative_currency_allowed"])
        self.assertIsNone(record["quantity_cost"]["cost"]["amount"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_item_quantity_one_purchase_acknowledgement_required"])
        self.assertTrue(effect["purchase_effect_independent_of_home_return"])
        self.assertTrue(effect["historical_home_digest_receipts_remain_valid"])
        self.assertTrue(effect["red_price_shortage_permits_fallback_without_owned_balance_or_stock"])
        self.assertFalse(effect["owned_baseline_required"])
        self.assertTrue(effect["timed_recruit_coin_diamonds_pair_allowed"])
        self.assertTrue(effect["premium_requires_finite_explicit_operator_approval"])
        self.assertFalse(effect["current_quote_maximum_cost_is_operator_budget"])

    def test_alliance_shop_typed_fallback_and_quantity_guards_fail_closed(self) -> None:
        mutations = (
            ("preferred_allowlist", lambda changed: changed["target"]["preferred_items"].__setitem__(1, "Int. Recruit Coin")),
            ("multiple_items", lambda changed: changed["target"].__setitem__("maximum_quantity_total", 2)),
            ("fallback_gate", lambda changed: changed["target"].__setitem__("unaffordable_preferred_permits_fallback", False)),
            ("fallback_affordability", lambda changed: changed["semantic_effect"].__setitem__("fallback_offer_must_be_current_and_affordable", False)),
            ("unaffordable_fallback", lambda changed: changed["semantic_effect"].__setitem__("no_affordable_fallback_yields_no_purchase", False)),
            ("premium", lambda changed: changed["target"].__setitem__("premium_allowed", True)),
            ("premium_pair", lambda changed: changed["target"]["approved_item_currency_pairs"].append(["joy_coin", "DIAMONDS"])),
            ("premium_approval", lambda changed: changed["semantic_effect"].__setitem__("premium_requires_finite_explicit_operator_approval", False)),
            ("quote_as_budget", lambda changed: changed["semantic_effect"].__setitem__("current_quote_maximum_cost_is_operator_budget", True)),
            ("daily_gate", lambda changed: changed["semantic_effect"].__setitem__("daily_screen_or_points_inspection_required", True)),
            ("acknowledgement", lambda changed: changed["semantic_effect"].__setitem__("exact_item_quantity_one_purchase_acknowledgement_required", False)),
            ("home_effect_gate", lambda changed: changed["semantic_effect"].__setitem__("purchase_effect_independent_of_home_return", False)),
            ("historical_receipt", lambda changed: changed["semantic_effect"].__setitem__("historical_home_digest_receipts_remain_valid", False)),
            ("red_shortage", lambda changed: changed["semantic_effect"].__setitem__("red_price_shortage_permits_fallback_without_owned_balance_or_stock", False)),
            ("owned_gate", lambda changed: changed["semantic_effect"].__setitem__("owned_baseline_required", True)),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.records["alliance_shop_purchase"])
            mutate(changed)
            changed["record_digest"] = record_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)

    def test_alliance_red_shortage_without_owned_allows_one_exact_fallback(self) -> None:
        weekly = ShopOffer(
            ALLIANCE_WEEKLY_SHOP,
            "Bioenhance Scheme",
            ALLIANCE_CURRENCY,
            None,
            None,
            None,
            None,
            available=None,
            price_shortage=True,
        )
        fallback = ShopOffer(
            ALLIANCE_OTHER_SHOP,
            ALLIANCE_FALLBACK_ITEM,
            ALLIANCE_CURRENCY,
            3,
            100,
            10,
            None,
            rarity=1,
            available=True,
        )
        choice = alliance_shop_choice(
            (weekly,),
            fallback,
            weekly_inventory_complete=True,
            fallback_inventory_complete=True,
        )
        self.assertEqual(choice.status, "selected")
        self.assertEqual(choice.reason, "AFFORDABLE_EXACT_FALLBACK")
        self.assertEqual(choice.offer, fallback)
        self.assertEqual(choice.quantity, 1)
        self.assertTrue(
            purchase_dialog_matches(
                fallback,
                quantity=1,
                selected_quantity=1,
                displayed_total=3,
            )
        )
        self.assertFalse(
            purchase_dialog_matches(
                fallback,
                quantity=2,
                selected_quantity=2,
                displayed_total=6,
            )
        )
        unaffordable_fallback = ShopOffer(
            ALLIANCE_OTHER_SHOP,
            ALLIANCE_FALLBACK_ITEM,
            ALLIANCE_CURRENCY,
            3,
            2,
            10,
            11,
            rarity=1,
            available=True,
        )
        deferred = alliance_shop_choice(
            (weekly,),
            unaffordable_fallback,
            weekly_inventory_complete=True,
            fallback_inventory_complete=True,
        )
        self.assertEqual(deferred.status, "deferred")
        self.assertIsNone(deferred.offer)

    def test_alliance_donation_limits_and_success_transitions_are_typed(self) -> None:
        record = self.records["alliance_donation"]
        target = record["target"]
        effect = record["semantic_effect"]
        self.assertEqual(record["record_type"], "alliance_donation")
        self.assertEqual(record["record_revision"], "alliance_donation-v2")
        self.assertEqual(target["technology_selection"], "game_automatically_selected_hot_tech")
        self.assertEqual(target["daily_action_limit"], 10)
        self.assertEqual(target["attempts_regenerate"], 1)
        self.assertEqual(target["attempt_regeneration_seconds"], 1_800)
        self.assertEqual(target["stored_attempt_cap"], 20)
        self.assertTrue(target["consecutive_available_attempts_allowed"])
        self.assertFalse(target["unbounded_hold_allowed"])
        self.assertEqual(effect["daily_success_limit"], 10)
        self.assertTrue(effect["one_confirmed_action_requires_one_consumed_attempt"])
        self.assertTrue(effect["attempt_consumption_accounts_for_positively_observed_regeneration"])
        self.assertTrue(effect["unchanged_attempt_count_requires_observed_timer_rollover"])
        self.assertFalse(effect["hud_resource_census_required"])
        self.assertFalse(effect["resource_wallet_debit_required"])
        self.assertFalse(effect["tech_progress_required"])
        self.assertFalse(effect["wait_required_while_attempts_remain"])
        self.assertFalse(effect["ranking_or_reward_point_counters_are_success_gates"])
        self.assertFalse(effect["daily_screen_or_points_inspection_required"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        mutations = (
            ("affordability", lambda changed: changed["semantic_effect"].__setitem__("current_hot_target_numeric_ordinary_cost_and_affordability_required", False)),
            ("regen_count", lambda changed: changed["semantic_effect"].__setitem__("attempt_consumption_accounts_for_positively_observed_regeneration", False)),
            ("unproved_rollover", lambda changed: changed["semantic_effect"].__setitem__("unchanged_attempt_count_requires_observed_timer_rollover", False)),
            ("resource_census", lambda changed: changed["semantic_effect"].__setitem__("hud_resource_census_required", True)),
            ("wallet_gate", lambda changed: changed["semantic_effect"].__setitem__("resource_wallet_debit_required", True)),
            ("progress_gate", lambda changed: changed["semantic_effect"].__setitem__("tech_progress_required", True)),
            ("quota", lambda changed: changed["target"].__setitem__("daily_action_limit", 11)),
            ("regen", lambda changed: changed["target"].__setitem__("attempt_regeneration_seconds", 900)),
            ("attempt_cap", lambda changed: changed["target"].__setitem__("stored_attempt_cap", 21)),
            ("no_consecutive", lambda changed: changed["target"].__setitem__("consecutive_available_attempts_allowed", False)),
            ("unbounded_hold", lambda changed: changed["target"].__setitem__("unbounded_hold_allowed", True)),
            ("count_transport", lambda changed: changed["semantic_effect"].__setitem__("count_only_distinct_effect_confirmed_actions", False)),
            ("rank_gate", lambda changed: changed["semantic_effect"].__setitem__("ranking_or_reward_point_counters_are_success_gates", True)),
            ("daily_gate", lambda changed: changed["semantic_effect"].__setitem__("daily_screen_or_points_inspection_required", True)),
        )
        for field, mutate in mutations:
            changed = deepcopy(record)
            mutate(changed)
            changed["record_digest"] = record_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)

    def test_daily_shops_bound_both_tabs_and_live_numeric_affordability(self) -> None:
        record = self.records["daily_shops_purchase"]
        shops = record["target"]["shops"]
        self.assertEqual(record["record_type"], "daily_shops_purchase")
        self.assertEqual(record["record_revision"], "daily_shops_purchase-v3")
        self.assertEqual(record["semantic_entry_route"]["route"],
                         ["HOME_ATLAS_MYSTERY_SHOP", "SHARED_SHOP", "RUINS_SHOP", "RARE_EARTH_SHOP"])
        self.assertEqual(
            [(shop["shop"], shop["item"], shop["rarity"], shop["currency"]) for shop in shops],
            [
                ("RUINS_SHOP", RUINS_CHIP_ITEM, 3, RUINS_CURRENCY),
                ("RARE_EARTH_SHOP", RARE_EARTH_MODULE_ITEM, 3, RARE_EARTH_CURRENCY),
            ],
        )
        self.assertTrue(record["target"]["one_visit_for_both_tabs"])
        self.assertTrue(record["target"]["per_tab_result_independent"])
        self.assertTrue(record["target"]["maximum_quantity_is_current_stock_and_affordability_min"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["both_tabs_evaluated_in_one_visit"])
        self.assertTrue(effect["per_tab_result_is_independent"])
        self.assertTrue(effect["quantity_must_equal_current_affordable_stock_cap"])
        self.assertFalse(effect["daily_screen_or_points_inspection_required"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertTrue(effect["exact_item_and_quantity_purchase_acknowledgement_required_per_tab"])
        self.assertTrue(effect["decreased_stock_required_per_purchased_tab"])
        self.assertTrue(effect["confirmed_or_already_confirmed_tab_with_blocked_sibling_is_partial_deferred"])
        self.assertFalse(effect["owned_baseline_required"])
        self.assertFalse(effect["wallet_debit_required"])
        ruins = ShopOffer(
            RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY,
            7, 100, 4, 0, rarity=3, available=True,
        )
        rare_earth = ShopOffer(
            RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY,
            9, 22, 20, 0, rarity=3, available=True,
        )
        self.assertEqual(daily_shop_quantity(ruins, shop_identity=RUINS_SHOP), 4)
        self.assertEqual(daily_shop_quantity(rare_earth, shop_identity=RARE_EARTH_SHOP), 2)
        self.assertTrue(
            purchase_dialog_matches(
                rare_earth,
                quantity=2,
                selected_quantity=2,
                displayed_total=18,
                shop_identity=RARE_EARTH_SHOP,
            )
        )
        self.assertFalse(
            purchase_dialog_matches(
                rare_earth,
                quantity=3,
                selected_quantity=3,
                displayed_total=27,
            )
        )
        mutations = (
            ("wrong_item", lambda changed: changed["target"]["shops"][1].__setitem__("item", "Module Promoter")),
            ("obsolete_ruins_exchange", lambda changed: changed["semantic_entry_route"].__setitem__("route", ["RUINS", "EXCHANGE", "RUINS_SHOP", "RARE_EARTH_SHOP"])),
            ("wrong_rarity", lambda changed: changed["target"]["shops"][0].__setitem__("rarity", 1)),
            ("stock_only_cap", lambda changed: changed["target"]["shops"][1].__setitem__("quantity_formula", "current_stock")),
            ("shared_tab_result", lambda changed: changed["target"].__setitem__("per_tab_result_independent", False)),
            ("skip_buy_without_numeric", lambda changed: changed["semantic_effect"].__setitem__("numeric_quantity_and_total_must_match_before_inner_buy", False)),
            ("daily_attribution", lambda changed: changed["daily_ownership"].__setitem__("daily_owner", "daily_shops_purchase")),
            ("less_than_current_cap", lambda changed: changed["semantic_effect"].__setitem__("quantity_must_equal_current_affordable_stock_cap", False)),
            ("premium", lambda changed: changed["target"].__setitem__("premium_allowed", True)),
            ("changed_offer", lambda changed: changed["semantic_effect"].__setitem__("changed_or_ambiguous_tab_blocks_without_substitution", False)),
            ("missing_acknowledgement", lambda changed: changed["semantic_effect"].__setitem__("exact_item_and_quantity_purchase_acknowledgement_required_per_tab", False)),
            ("missing_stock_successor", lambda changed: changed["semantic_effect"].__setitem__("decreased_stock_required_per_purchased_tab", False)),
            ("lost_partial", lambda changed: changed["semantic_effect"].__setitem__("confirmed_or_already_confirmed_tab_with_blocked_sibling_is_partial_deferred", False)),
        )
        for field, mutate in mutations:
            changed = deepcopy(record)
            mutate(changed)
            changed["record_digest"] = record_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)

    def test_hero_upgrade_policy_allows_three_normal_levels_with_evidence_gated_evolution(self) -> None:
        record = self.records["hero_upgrade"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "hero-upgrade-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertTrue(policy["upgrade_dispatch_allowed"])
        self.assertEqual(
            policy["approved_action_kinds"],
            ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        )
        self.assertEqual(
            policy["runtime_admission"],
            "canonical_supervised_claim_and_current_explicit_authorization_required",
        )
        self.assertTrue(policy["current_explicit_authorization_required"])
        self.assertTrue(policy["canonical_supervised_claim_required"])
        self.assertEqual(policy["registration_status"], "NOT_REGISTERED")
        self.assertFalse(policy["scheduler_eligibility"])
        self.assertEqual(policy["candidate_hero"], "Wali")
        self.assertEqual(policy["normal_upgrade_count_per_reset"], 3)
        self.assertEqual(policy["normal_upgrade_kind"], "single_level")
        self.assertEqual(policy["normal_upgrade_material"], "ANTISERUM")
        self.assertTrue(policy["evolution_only_at_displayed_cap"])
        self.assertFalse(policy["evolution_counts_toward_normal_upgrade_count"])
        self.assertEqual(policy["evidence_state"], "evidence_required")
        self.assertFalse(policy["scheduler_eligibility"])
        reset_path = policy["reset_campaign_diamond_path"]
        self.assertEqual(reset_path["status"], "evidence_required")
        self.assertTrue(reset_path["operationally_blocked"])
        self.assertFalse(reset_path["campaign_block_proven"])
        self.assertFalse(reset_path["final_150_diamond_confirmation_proven"])
        self.assertFalse(reset_path["dispatch_allowed"])

        self.assertEqual(record["record_type"], "hero_upgrade")
        self.assertEqual(record["semantic_entry_route"]["route"], ["HERO"])
        target = record["target"]
        self.assertEqual(target["hero_identity"], "Wali")
        self.assertIsNone(target["current_level"])
        self.assertIsNone(target["evolution_cap"])
        self.assertIsNone(target["next_evolution_cap"])
        self.assertEqual(target["normal_upgrade_material"], "ANTISERUM")
        self.assertEqual(target["normal_upgrade_count_per_reset"], 3)
        self.assertTrue(target["normal_single_upgrade"])
        self.assertTrue(target["evolution_only_at_displayed_cap"])
        self.assertFalse(target["evolution_level_change_counts_as_normal_upgrade"])
        self.assertEqual(target["policy_status"], "explicitly_approved")
        self.assertTrue(target["upgrade_dispatch_allowed"])
        self.assertEqual(
            target["approved_action_kinds"],
            ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        )
        self.assertEqual(
            target["standard_evolution_materials"],
            [
                "ANTISERUM",
                "COMBAT_MANUAL_I",
                "COMBAT_MANUAL_II",
                "COMBAT_MANUAL_III",
                "COMBAT_MANUAL_IV",
                "COMBAT_MANUAL_V",
            ],
        )
        cost = record["quantity_cost"]
        self.assertEqual(cost["quantity"], 1)
        self.assertIsNone(cost["normal_upgrade"]["amount"])
        self.assertTrue(cost["normal_upgrade"]["current_observation_required"])
        self.assertEqual(cost["normal_upgrade"]["material"], "ANTISERUM")
        self.assertFalse(cost["normal_upgrade"]["free_only"])
        self.assertTrue(cost["standard_evolution"]["exact_current_vector_required"])
        self.assertFalse(cost["standard_evolution"]["free_only"])
        self.assertTrue(cost["reset_campaign_diamond_path"]["operationally_blocked"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_selected_wali_evidence_required"])
        self.assertTrue(effect["exact_current_material_vector_and_balance_required"])
        self.assertTrue(effect["exact_antiserum_debit_required"])
        self.assertTrue(effect["evolution_automatic_level_not_counted"])
        self.assertTrue(effect["evolution_manual_decrement_numeric_receipt_or_named_usage_toast_required"])
        self.assertTrue(effect["confirmed_normal_count_persists_through_evolution_and_restart"])
        self.assertFalse(effect["daily_progress_successor_required"])
        self.assertFalse(effect["points_credit_required"])
        self.assertTrue(effect["upgrade_dispatch_allowed"])
        self.assertEqual(
            effect["approved_action_kinds"],
            ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        )
        self.assertTrue(effect["current_explicit_authorization_required"])
        self.assertTrue(effect["canonical_supervised_claim_required"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "bulk upgrade",
            "premium material",
            "premium currency",
            "unknown or ambiguous hero",
            "unknown or ambiguous material",
            "unknown or ambiguous cost",
            "reset/campaign path without exact evidence",
            "150-diamond path before exact campaign block and final confirmation evidence",
            "daily prerequisite",
            "d02 prerequisite",
            "points prerequisite",
            "identical retry",
        ):
            self.assertIn(marker, forbidden)

        mutations = (
            lambda changed: changed["target"].__setitem__("normal_upgrade_count_per_reset", 2),
            lambda changed: changed["quantity_cost"]["normal_upgrade"].__setitem__("maximum_inputs_per_batch", 4),
            lambda changed: changed["quantity_cost"]["normal_upgrade"].__setitem__("current_quote_before_each_input", False),
            lambda changed: changed["semantic_effect"].__setitem__("normal_batch_cumulative_level_and_debit_required", False),
            lambda changed: changed["semantic_effect"].__setitem__("per_input_settled_successor_required", True),
            lambda changed: changed["semantic_effect"].__setitem__("partial_batch_requires_exact_known_prefix", False),
            lambda changed: changed["target"]["approved_action_kinds"].append("HERO_UPGRADE_BULK"),
            lambda changed: changed["target"].__setitem__("evolution_level_change_counts_as_normal_upgrade", True),
            lambda changed: changed["quantity_cost"]["reset_campaign_diamond_path"].__setitem__(
                "dispatch_allowed", True
            ),
            lambda changed: changed["semantic_effect"].__setitem__(
                "confirmed_normal_count_persists_through_evolution_and_restart", False
            ),
            lambda changed: changed["semantic_effect"].__setitem__(
                "current_explicit_authorization_required", False
            ),
            lambda changed: changed["daily_ownership"].__setitem__(
                "selected_daily_prerequisite", True
            ),
        )
        for mutate in mutations:
            changed = deepcopy(record)
            mutate(changed)
            changed["record_digest"] = record_digest(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)

        changed_authority = deepcopy(self.authority)
        changed_policy = next(
            item
            for item in changed_authority["policies"]
            if item["policy_id"] == "hero-upgrade-policy"
        )
        changed_policy["reset_campaign_diamond_path"]["final_150_diamond_confirmation_proven"] = True
        changed_authority["authority_digest"] = authority_digest(changed_authority)
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(changed_authority)

    def test_gathering_validator_rejects_validation_recurrence_or_daily_coupling(self) -> None:
        record = self.records["gathering_resources"]
        invalid_recurrence = deepcopy(record)
        invalid_recurrence["recurrence"] = "evidence_gated_variant_canary"
        with self.assertRaises(ProductAuthorityError):
            validate_product_record(invalid_recurrence)
        invalid_daily = deepcopy(record)
        invalid_daily["target"]["source_daily_row_required"] = True
        with self.assertRaises(ProductAuthorityError):
            validate_product_record(invalid_daily)

    def test_hero_duel_approves_bounded_free_survival_cycles_only(self) -> None:
        record = self.records["hero_duel"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "hero-duel-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertTrue(policy["pvp_entry_allowed"])
        self.assertEqual(policy["maximum_confirmed_cycles_per_reset"], 3)
        self.assertEqual(record["record_revision"], "hero_duel-v3")
        self.assertEqual(
            record["semantic_entry_route"]["route"], ["ARENA", "HERO_DUEL_SURVIVAL"]
        )
        target = record["target"]
        self.assertEqual(target["event_identity"], "hero_duel_survival")
        self.assertTrue(target["event_active_required"])
        self.assertEqual(target["maximum_cycles_per_reset"], 3)
        self.assertEqual(target["maximum_hero_slots"], 5)
        self.assertEqual(target["hero_selection"], "first_five_eligible_displayed")
        self.assertEqual(
            target["attack_selection"], "first_five_eligible_displayed"
        )
        self.assertTrue(target["excluded_heroes_skipped"])
        self.assertTrue(target["attack_lineup_independent"])
        self.assertTrue(target["attack_lineup_fill_missing_only"])
        cost = record["quantity_cost"]["cost"]
        self.assertEqual(cost["amount"], 0)
        self.assertTrue(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["defense_formation_save_required"])
        self.assertTrue(effect["preserve_complete_valid_attack_formation"])
        self.assertEqual(
            effect["attack_selection"], "first_five_eligible_displayed"
        )
        self.assertTrue(effect["loss_result_acceptable"])
        self.assertTrue(effect["positive_participation_successor_required"])
        self.assertNotIn("pass_balance_decrease_allowed", effect)
        self.assertFalse(effect["daily_inspection_required"])
        self.assertFalse(effect["points_attribution_required"])
        self.assertEqual(record["daily_ownership"]["daily_owner"], None)

        for mutate in (
            lambda invalid: invalid["target"].__setitem__("maximum_cycles_per_reset", 4),
            lambda invalid: invalid["target"].__setitem__("maximum_hero_slots", 6),
            lambda invalid: invalid["target"].__setitem__("attack_selection", "keep_current"),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "fill_missing_attack_slots_only", False
            ),
            lambda invalid: invalid["quantity_cost"]["cost"].__setitem__("amount", 1),
        ):
            invalid = deepcopy(record)
            mutate(invalid)
            invalid["record_digest"] = record_digest(invalid)
            with self.assertRaises(ProductAuthorityError):
                validate_product_record(invalid)

    def test_recommended_research_is_first_row_idle_and_ordinary_only(self) -> None:
        record = self.records["recommended_research"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "recommended-research-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertEqual(policy["maximum_starts_per_reset"], 1)
        self.assertFalse(policy["queue2_activation_allowed"])
        self.assertEqual(
            policy["shortage_behavior"], "record_exact_shortages_and_defer"
        )
        self.assertEqual(record["record_revision"], "recommended_research-v2")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["RESEARCH_CENTER", "RECOMMENDED_RESEARCH"],
        )
        target = record["target"]
        self.assertEqual(target["recommendation_position"], 1)
        self.assertEqual(
            target["recommendation_row_control"], "ROW_RESEARCH_NAVIGATION"
        )
        self.assertEqual(target["detail_start_control"], "DETAIL_RESEARCH_START")
        self.assertTrue(target["row_research_only_navigates"])
        self.assertEqual(
            target["ordinary_resources"], ["food", "wood", "steel", "gas"]
        )
        self.assertEqual(target["maximum_starts_per_reset"], 1)
        self.assertEqual(
            target["shortage_behavior"], "record_exact_shortages_and_defer"
        )
        effect = record["semantic_effect"]
        self.assertTrue(effect["queue1_idle_before_start"])
        self.assertTrue(effect["all_four_ordinary_costs_and_balances_required"])
        self.assertTrue(effect["shortages_recorded_and_deferred"])
        self.assertTrue(effect["recommendation_row_research_navigates_only"])
        self.assertTrue(effect["detail_research_control_starts_action"])
        self.assertTrue(effect["active_queue_successor_for_same_identity_required"])
        self.assertTrue(effect["positive_remaining_timer_required"])
        self.assertNotIn("all_four_resource_debits_required", effect)
        self.assertFalse(effect["queue2_activation_allowed"])
        self.assertFalse(effect["research_now_diamonds_allowed"])
        self.assertFalse(effect["alternate_technology_allowed"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("research now", "queue 2", "box", "alternate technology", "gathering"):
            self.assertIn(marker, forbidden)
        for mutate in (
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "active_queue_successor_for_same_identity_required", False
            ),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "positive_remaining_timer_required", False
            ),
            lambda invalid: invalid["target"].__setitem__("recommendation_position", 2),
            lambda invalid: invalid["target"].__setitem__("queue2_activation_allowed", True),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "all_four_ordinary_costs_and_balances_required", False
            ),
            lambda invalid: invalid["target"].__setitem__(
                "shortage_behavior", "switch_to_another_technology"
            ),
        ):
            invalid = deepcopy(record)
            mutate(invalid)
            invalid["record_digest"] = record_digest(invalid)
            with self.assertRaises(ProductAuthorityError):
                validate_product_record(invalid)

    def test_food_farm_boost_requires_item_usability_not_inventory_or_collection_gate(self) -> None:
        record = self.records["food_farm_output_boost"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "food-farm-output-boost-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertEqual(policy["maximum_boosts_per_reset"], 1)
        self.assertTrue(policy["owned_item_preferred"])
        self.assertEqual(
            policy["diamond_fallback_offer"],
            {
                "control": "Boost output (1-day)",
                "duration": "1-day",
                "currency": "DIAMONDS",
                "maximum_authorized_price_diamonds": 48,
                "current_numeric_price_must_be_observed": True,
                "current_numeric_price_must_not_exceed_authorized_cap": True,
                "current_balance_must_cover_exact_observed_price": True,
                "price_and_balance_rechecked_if_confirmation_appears": True,
            },
        )
        self.assertTrue(policy["collection_credit_requires_positive_food_hud_tick"])
        self.assertFalse(policy["positive_collection_required_before_boost"])
        self.assertTrue(policy["diamond_price_cap_not_assumed_current_price"])
        self.assertEqual(record["record_revision"], "food_farm_output_boost-v2")
        self.assertEqual(record["semantic_entry_route"]["target"], "FOOD_FARM")
        target = record["target"]
        self.assertEqual(target["resource_type"], "FOOD")
        self.assertEqual(target["maximum_boosts_per_reset"], 1)
        self.assertTrue(target["owned_item_preferred"])
        self.assertTrue(target["owned_item_usable_must_be_positively_observed"])
        self.assertEqual(target["item_action_cost"], 1)
        self.assertTrue(target["item_action_cost_is_not_inventory_count"])
        self.assertTrue(target["diamond_fallback_only_when_owned_item_unavailable"])
        self.assertEqual(
            target["diamond_fallback_offer"],
            {
                "control": "Boost output (1-day)",
                "duration": "1-day",
                "currency": "DIAMONDS",
                "maximum_authorized_price_diamonds": 48,
                "current_numeric_price_must_be_observed": True,
                "current_numeric_price_must_not_exceed_authorized_cap": True,
                "current_balance_must_cover_exact_observed_price": True,
                "price_and_balance_rechecked_if_confirmation_appears": True,
            },
        )
        self.assertTrue(target["diamond_price_cap_not_assumed_current_price"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["first_tap_bound_home_or_same_farm_radial_required"])
        self.assertTrue(effect["collection_credit_requires_positive_food_hud_tick"])
        self.assertFalse(effect["positive_collection_required_before_boost"])
        self.assertNotIn("collection_balance_resources", effect)
        self.assertNotIn("collection_exact_balance_delta_for_each_resource_required", effect)
        self.assertTrue(effect["collection_is_not_boost_success"])
        self.assertTrue(effect["same_farm_active_boost_successor_required"])
        self.assertFalse(effect["global_food_output_boost_item_allowed"])
        self.assertTrue(effect["current_price_must_not_exceed_authorized_cap"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "buy box",
            "resource building boost",
            "inventory count inferred from action cost",
            "changed prompt",
            "second boost",
        ):
            self.assertIn(marker, forbidden)
        for mutate in (
            lambda invalid: invalid["target"].__setitem__("maximum_boosts_per_reset", 2),
            lambda invalid: invalid["target"].__setitem__(
                "item_action_cost_is_not_inventory_count", False
            ),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "positive_collection_required_before_boost", True
            ),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "same_farm_active_boost_successor_required", False
            ),
            lambda invalid: invalid["target"]["diamond_fallback_offer"].__setitem__(
                "maximum_authorized_price_diamonds", 49
            ),
            lambda invalid: invalid["target"]["diamond_fallback_offer"].__setitem__(
                "current_numeric_price_must_be_observed", False
            ),
            lambda invalid: invalid["target"]["diamond_fallback_offer"].__setitem__(
                "current_numeric_price_must_not_exceed_authorized_cap", False
            ),
            lambda invalid: invalid["target"].__setitem__(
                "diamond_price_cap_not_assumed_current_price", False
            ),
        ):
            invalid = deepcopy(record)
            mutate(invalid)
            invalid["record_digest"] = record_digest(invalid)
            with self.assertRaises(ProductAuthorityError):
                validate_product_record(invalid)

    def test_e_and_f_product_policy_statuses_are_enforced_and_non_authorizing(self) -> None:
        for policy_id in (
            "hero-duel-policy",
            "recommended-research-policy",
            "food-farm-output-boost-policy",
            "commander-talent-preset-helper",
            "hall-of-war-zombie-zero-policy",
            "troop-training-resource-policy",
        ):
            with self.subTest(policy_id=policy_id):
                changed = deepcopy(self.authority)
                policy = next(
                    item
                    for item in changed["policies"]
                    if item["policy_id"] == policy_id
                )
                policy["status"] = "prohibited"
                changed["authority_digest"] = authority_digest(changed)
                with self.assertRaises(ProductAuthorityError):
                    validate_product_authority(changed)
        changed = deepcopy(self.authority)
        farm_policy = next(
            item
            for item in changed["policies"]
            if item["policy_id"] == "food-farm-output-boost-policy"
        )
        farm_policy["diamond_fallback_offer"]["maximum_authorized_price_diamonds"] = 49
        changed["authority_digest"] = authority_digest(changed)
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(changed)

    def test_f_policy_guards_saved_preset_costs_hall_quota_and_box_scope(self) -> None:
        preset_policy = next(
            policy for policy in self.authority["policies"]
            if policy["policy_id"] == "commander-talent-preset-helper"
        )
        self.assertIsNone(preset_policy["switch_cooldown_seconds"])
        self.assertIsNone(preset_policy["default_switch_approval"])
        self.assertEqual(preset_policy["unknown_switch_cost"], "blocked_under_current_authority_schema")
        self.assertFalse(preset_policy["standing_reset_permission"])
        self.assertEqual(preset_policy["allocated_points_reset_confirmation_preset"], "Training")
        self.assertTrue(preset_policy["allocated_points_reset_requires_explicit_scoped_approval"])
        mutations = (
            ("commander-talent-preset-helper", lambda policy: policy.__setitem__("generic_free_strategic_action_allowed", True)),
            ("commander-talent-preset-helper", lambda policy: policy.__setitem__("optional_actual_confirmation_only", False)),
            ("commander-talent-preset-helper", lambda policy: policy.__setitem__("standing_reset_permission", True)),
            ("commander-talent-preset-helper", lambda policy: policy.__setitem__("unknown_switch_cost", "assumed_free")),
            ("commander-talent-preset-helper", lambda policy: policy.__setitem__("switch_cooldown_seconds", 0)),
            ("hall-of-war-zombie-zero-policy", lambda policy: policy.__setitem__("maximum_consequential_actions_per_visit", 4)),
            ("troop-training-resource-policy", lambda policy: policy["resource_box_continuation"].__setitem__("consumption_allowed_without_exact_box_evidence", True)),
            ("troop-training-resource-policy", lambda policy: policy.__setitem__("existing_batch_retains_start_quantity", False)),
            (
                "commander-talent-preset-helper",
                lambda policy: policy.__setitem__(
                    "switch_cost_allowance", "observed_zero_or_paid"
                ),
            ),
            (
                "commander-talent-preset-helper",
                lambda policy: policy.__setitem__("route_approval_required", False),
            ),
            (
                "hall-of-war-zombie-zero-policy",
                lambda policy: policy.__setitem__("maximum_dispatches_per_reset", 2),
            ),
            (
                "troop-training-resource-policy",
                lambda policy: policy["resource_box_continuation"].__setitem__(
                    "allowed_types", ["fighter", "vehicle", "shooter"]
                ),
            ),
        )
        for policy_id, mutate in mutations:
            with self.subTest(policy_id=policy_id):
                changed = deepcopy(self.authority)
                policy = next(
                    item
                    for item in changed["policies"]
                    if item["policy_id"] == policy_id
                )
                mutate(policy)
                changed["authority_digest"] = authority_digest(changed)
                with self.assertRaises(ProductAuthorityError):
                    validate_product_authority(changed)


    def test_hall_of_war_zombie_zero_record_is_one_current_free_attempt_and_separate_reward(self) -> None:
        record = self.records["hall_of_war_zombie_zero"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "hall-of-war-zombie-zero-policy"
        )
        self.assertEqual(policy["status"], "explicitly_approved")
        self.assertEqual(policy["maximum_dispatches_per_reset"], 1)
        self.assertEqual(
            policy["dispatch_cost_allowance"], "owner_fixed_zero_resource"
        )
        self.assertFalse(policy["premium_or_refill_allowed"])
        self.assertTrue(policy["owner_fixed_zero_loss_mechanic"])
        self.assertEqual(record["record_revision"], "hall_of_war_zombie_zero-v3")
        self.assertEqual(
            record["semantic_entry_route"]["route"], ["HALL_OF_WAR", "ZOMBIE_ZERO"]
        )
        target = record["target"]
        self.assertEqual(target["maximum_dispatches_per_reset"], 1)
        self.assertTrue(target["attempt_state_must_be_current"])
        self.assertTrue(target["attempt_availability_or_cooldown_is_not_hardcoded"])
        self.assertFalse(target["literal_cost_or_loss_disclosure_required"])
        self.assertEqual(target["commander_talent_requirement"]["required_preset"], "Military")
        self.assertTrue(
            target["commander_talent_requirement"]["route_approval_required"]
        )
        self.assertEqual(target["saved_troop_set_identity"], "Troop Set 1")
        self.assertTrue(target["saved_troop_set_must_be_selected_and_applied"])
        self.assertTrue(target["five_heroes_must_be_populated"])
        self.assertFalse(target["full_capacity_or_sets_two_and_three_labels_required"])
        self.assertFalse(target["quick_select_allowed"])
        self.assertFalse(target["formation_edit_allowed"])
        self.assertIsNone(target["minimum_damage_threshold"])
        self.assertTrue(target["reward_claim_requires_current_glowing_ready_row"])
        self.assertTrue(target["reward_claim_is_one_daily_row_tap"])
        self.assertTrue(target["claimed_reward_successor_requires_current_row_checkmarks"])
        cost = record["quantity_cost"]["cost"]
        self.assertEqual(cost["kind"], "owner_fixed_zero_resource")
        self.assertEqual(cost["amount"], 0)
        self.assertTrue(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["history_high_result_successor_required"])
        self.assertTrue(effect["reward_claim_requires_same_reset_positive_participation"])
        self.assertTrue(effect["one_row_tap_and_current_claimed_checkmark_successor_required"])
        self.assertFalse(effect["daily_inspection_required"])
        self.assertFalse(effect["d02_prerequisite"])
        self.assertFalse(effect["points_attribution_required"])
        self.assertEqual(effect["maximum_consequential_actions_per_visit"], 3)
        self.assertEqual(effect["visit_budget_includes"], ["optional_preset_switch", "dispatch", "reward_claim"])
        self.assertFalse(effect["visit_budget_changes_reset_quotas"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        for mutate in (
            lambda invalid: invalid["target"].__setitem__(
                "maximum_dispatches_per_reset", 2
            ),
            lambda invalid: invalid["target"].__setitem__(
                "saved_troop_set_identity", "Troop Set 2"
            ),
            lambda invalid: invalid["target"].__setitem__(
                "owner_fixed_zero_loss_mechanic", False
            ),
            lambda invalid: invalid["target"].__setitem__(
                "minimum_damage_threshold", 1
            ),
            lambda invalid: invalid["quantity_cost"]["cost"].__setitem__(
                "kind", "unknown_cost"
            ),
            lambda invalid: invalid["semantic_effect"].__setitem__(
                "one_row_tap_and_current_claimed_checkmark_successor_required", False
            ),
        ):
            invalid = deepcopy(record)
            mutate(invalid)
            invalid["record_digest"] = record_digest(invalid)
            with self.assertRaises(ProductAuthorityError):
                validate_product_record(invalid)

    def test_ruins_shop_candidate_is_unresolved_and_non_dispatching(self) -> None:
        record = self.records["ruins_shop_purchase"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "ruins-shop-purchase-policy"
        )
        self.assertEqual(policy["status"], "unresolved_user_decision")
        self.assertFalse(policy["purchase_dispatch_allowed"])
        self.assertEqual(record["record_type"], "ruins_shop_purchase")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["RUINS_SHOP"],
        )
        target = record["target"]
        self.assertEqual(target["candidate_item"], "three_star_chip_material")
        self.assertEqual(target["candidate_currency"], "RUINS_COINS")
        self.assertEqual(target["candidate_cost"], 15)
        self.assertEqual(target["quantity"], 1)
        self.assertEqual(target["policy_status"], "unresolved_user_decision")
        self.assertFalse(target["purchase_dispatch_allowed"])
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 15)
        self.assertEqual(record["quantity_cost"]["cost"]["unit"], "RUINS_COINS")
        self.assertFalse(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["offer_observation_successor_required"])
        self.assertTrue(effect["exact_cost_evidence_required"])
        self.assertTrue(effect["balance_evidence_required"])
        self.assertFalse(effect["purchase_dispatch_allowed"])
        self.assertTrue(effect["canonical_home_successor_required"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "buy",
            "purchase dispatch",
            "currency spend",
            "unknown",
            "ambiguous",
            "insufficient balance",
        ):
            self.assertIn(marker, forbidden)


    def test_nano_material_production_is_one_zero_resource_six_hour_batch(self) -> None:
        record = self.records["nano_material_production"]
        self.assertEqual(record["record_revision"], "nano_material_production-v2")
        self.assertEqual(record["record_type"], "nano_material_production")
        self.assertEqual(record["recurrence"], "cooldown_pulse")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["NANOWEAPON", "MATERIAL_PRODUCTION"],
        )
        target = record["target"]
        self.assertEqual(target["maximum_active_productions"], 1)
        self.assertEqual(target["production_duration_seconds"], 21600)
        self.assertTrue(target["completed_claim_allowed"])
        self.assertTrue(target["idle_start_allowed"])
        self.assertTrue(target["active_due_time_refresh_allowed"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["completed_claim_successor_allowed"])
        self.assertTrue(effect["idle_start_successor_allowed"])
        self.assertTrue(effect["active_due_time_successor_required"])
        self.assertTrue(effect["zero_resource_cost_required"])
        for field in ("dynamic_start_quote_required", "literal_free_cost_or_duration_disclosure_required", "info_visit_required"):
            self.assertFalse(effect[field])
        self.assertTrue(effect["confirmed_claim_preserved_after_unsent_restart_failure"])
        self.assertTrue(effect["confirmed_effect_independent_of_home_return"])
        self.assertTrue(effect["claim_and_start_proofs_separate"])
        self.assertEqual(effect["active_due_time_source"], "observed_remaining_timer")
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
    def test_nanoweapon_product_is_one_exact_normal_craft_per_reset(self) -> None:
        record = self.records["nanoweapon_normal_craft"]
        self.assertEqual(record["record_type"], "nanoweapon_normal_craft")
        self.assertEqual(record["record_revision"], "nanoweapon_normal_craft-v3")
        self.assertEqual(record["objective"], "nanoweapon_normal_craft")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["GEAR_FACTORY", "NANOWEAPON", "NORMAL_CRAFT"],
        )
        target = record["target"]
        self.assertTrue(target["completed_claim_on_entry"])
        self.assertEqual(target["parts_required"], 100)
        self.assertEqual(target["parts_unit"], "NANO_PARTS")
        self.assertEqual(target["maximum_active_crafts"], 1)
        self.assertEqual(target["maximum_starts_per_reset"], 1)
        self.assertEqual(target["craft_duration_seconds"], 43200)
        self.assertFalse(target["exclusive_craft_allowed"])
        self.assertFalse(target["rotating_display_selection_allowed"])
        self.assertTrue(target["insufficient_parts_defer"])
        self.assertTrue(target["disabled_craft_defer"])
        self.assertEqual(
            target["prior_material_production"],
            {
                "product_record_id": "nano_material_production",
                "product_record_revision": "nano_material_production-v2",
                "required_same_visit": True,
                "separate_authorization_required": True,
                "positive_effect_must_be_reconciled_before_craft": True,
                "verified_active_zero_effects_satisfies_maintenance": True,
                "claim_without_restart_satisfies_maintenance": False,
                "normal_craft_substitution_allowed": False,
                "normal_craft_reset_allowance_consumed": False,
            },
        )
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 100)
        self.assertEqual(record["quantity_cost"]["cost"]["unit"], "NANO_PARTS")
        self.assertFalse(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["completed_claim_successor_required"])
        self.assertTrue(effect["no_currency_box_or_item_input"])
        self.assertFalse(effect["exact_parts_consumption_required"])
        self.assertTrue(effect["completed_claim_free"])
        for field in ("completed_claim_requires_original_start", "completed_claim_requires_new_start_quote",
                      "completed_claim_requires_current_affordability", "active_craft_requires_new_start_quote",
                      "literal_quantity_one_caption_required", "navigation_failure_makes_confirmed_effect_unknown"):
            self.assertFalse(effect[field])
        self.assertTrue(effect["claim_and_start_proofs_separate"])
        self.assertTrue(effect["confirmed_effect_preserved_after_unsent_failure"])
        self.assertEqual(effect["affordability_source"], "normal_or_red_material_cost_display")
        self.assertTrue(effect["single_active_craft_required"])
        self.assertTrue(effect["single_start_per_reset_required"])
        self.assertTrue(effect["exact_duration_required"])
        self.assertTrue(effect["own_normal_craft_start_successor_required"])
        self.assertTrue(effect["prior_material_production_reconciled_before_craft"])
        self.assertTrue(effect["maintenance_does_not_satisfy_normal_craft"])
        self.assertTrue(effect["maintenance_does_not_consume_normal_craft_reset_allowance"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

    def test_nanoweapon_v3_rejects_daily_and_composition_regressions(self) -> None:
        mutations = (
            ("stale_revision", lambda changed: changed.__setitem__("record_revision", "nanoweapon_normal_craft-v1")),
            ("wrong_parts", lambda changed: changed["target"].__setitem__("parts_required", 101)),
            ("wrong_cost", lambda changed: changed["quantity_cost"]["cost"].__setitem__("amount", 101)),
            ("occupied", lambda changed: changed["target"].__setitem__("maximum_active_crafts", 2)),
            ("second_start", lambda changed: changed["target"].__setitem__("maximum_starts_per_reset", 2)),
            ("wrong_duration", lambda changed: changed["target"].__setitem__("craft_duration_seconds", 21600)),
            ("exclusive", lambda changed: changed["target"].__setitem__("exclusive_craft_allowed", True)),
            ("maintenance_record", lambda changed: changed["target"]["prior_material_production"].__setitem__("product_record_id", "nanoweapon_normal_craft")),
            ("maintenance_revision", lambda changed: changed["target"]["prior_material_production"].__setitem__("product_record_revision", "nano_material_production-v1")),
            ("not_same_visit", lambda changed: changed["target"]["prior_material_production"].__setitem__("required_same_visit", False)),
            ("not_separately_authorized", lambda changed: changed["target"]["prior_material_production"].__setitem__("separate_authorization_required", False)),
            ("maintenance_substitution", lambda changed: changed["target"]["prior_material_production"].__setitem__("normal_craft_substitution_allowed", True)),
            ("maintenance_consumes_quota", lambda changed: changed["target"]["prior_material_production"].__setitem__("normal_craft_reset_allowance_consumed", True)),
            ("unreconciled_maintenance", lambda changed: changed["target"]["prior_material_production"].__setitem__("positive_effect_must_be_reconciled_before_craft", False)),
            ("maintenance_not_reconciled", lambda changed: changed["semantic_effect"].__setitem__("prior_material_production_reconciled_before_craft", False)),
            ("maintenance_satisfies_craft", lambda changed: changed["semantic_effect"].__setitem__("maintenance_does_not_satisfy_normal_craft", False)),
            ("maintenance_quota", lambda changed: changed["semantic_effect"].__setitem__("maintenance_does_not_consume_normal_craft_reset_allowance", False)),
            ("daily_objective_requirement", lambda changed: changed["semantic_effect"].__setitem__("daily_objective_successor_required", False)),
            ("daily_provider_requirement", lambda changed: changed["semantic_effect"].__setitem__("daily_provider_required", True)),
            ("points_requirement", lambda changed: changed["semantic_effect"].__setitem__("points_delta_required", True)),
            ("missing_own_successor", lambda changed: changed["semantic_effect"].__setitem__("own_normal_craft_start_successor_required", False)),
            ("identical_retry", lambda changed: changed["semantic_effect"].__setitem__("identical_retry", True)),
            ("original_start_claim_gate", lambda changed: changed["semantic_effect"].__setitem__("completed_claim_requires_original_start", True)),
            ("quote_claim_gate", lambda changed: changed["semantic_effect"].__setitem__("completed_claim_requires_new_start_quote", True)),
            ("affordability_claim_gate", lambda changed: changed["semantic_effect"].__setitem__("completed_claim_requires_current_affordability", True)),
            ("quote_active_gate", lambda changed: changed["semantic_effect"].__setitem__("active_craft_requires_new_start_quote", True)),
            ("merged_proofs", lambda changed: changed["semantic_effect"].__setitem__("claim_and_start_proofs_separate", False)),
            ("lost_partial", lambda changed: changed["semantic_effect"].__setitem__("confirmed_effect_preserved_after_unsent_failure", False)),
            ("active_maintenance_gate", lambda changed: changed["target"]["prior_material_production"].__setitem__("verified_active_zero_effects_satisfies_maintenance", False)),
            ("claim_without_restart", lambda changed: changed["target"]["prior_material_production"].__setitem__("claim_without_restart_satisfies_maintenance", True)),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.records["nanoweapon_normal_craft"])
            mutate(changed)
            changed["record_digest"] = record_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)

    def test_material_v2_rejects_disclosures_and_lost_confirmed_claim(self) -> None:
        for field in ("dynamic_start_quote_required", "literal_free_cost_or_duration_disclosure_required",
                      "info_visit_required", "confirmed_claim_preserved_after_unsent_restart_failure",
                      "confirmed_effect_independent_of_home_return", "claim_and_start_proofs_separate"):
            changed = deepcopy(self.records["nano_material_production"])
            changed["semantic_effect"][field] = not changed["semantic_effect"][field]
            changed["record_digest"] = record_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_record(changed)


    def test_world_navigation_record_is_zero_cost_and_non_gameplay(self) -> None:
        record = self.records["world_map_navigation"]
        self.assertEqual(record["record_type"], "world_map_navigation")
        self.assertEqual(record["record_revision"], "world_map_navigation-v1")
        self.assertEqual(record["semantic_entry_route"]["source_home_authorities"], ["HOME_READY"])
        self.assertEqual(record["semantic_entry_route"]["target"], "WORLD")
        self.assertEqual(record["target"]["search_control"], "WORLD_SEARCH")
        self.assertEqual(record["target"]["atlas_authority"], "out_of_scope")
        self.assertEqual(record["quantity_cost"]["quantity"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["navigation_only"])
        self.assertTrue(effect["search_successor_required"])
        self.assertTrue(effect["home_successor_required"])
        self.assertFalse(effect["identical_retry"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("march", "attack", "stamina", "ap", "resource", "combat"):
            self.assertIn(marker, forbidden)
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
    def test_vip_points_popup_record_is_bounded_navigation_only_helper(self) -> None:
        record = self.records["vip_points_popup_dismissal"]
        self.assertEqual(record["record_type"], "vip_points_popup_dismissal")
        self.assertEqual(record["record_revision"], "vip_points_popup_dismissal-v1")
        self.assertEqual(
            record["semantic_entry_route"]["source_home_authorities"],
            ["HOME_READY", "HOME_LOCALIZED", "HOME_CANONICAL"],
        )
        self.assertEqual(record["semantic_entry_route"]["target"], "HOME")
        target = record["target"]
        self.assertEqual(target["popup_identity"], "VIP_POINTS_GET_PTS")
        self.assertEqual(target["close_control"], "RESET_POPUP_CLOSE")
        self.assertEqual(target["maximum_inputs"], 1)
        self.assertEqual(record["quantity_cost"]["quantity"], 0)
        effect = record["semantic_effect"]
        self.assertTrue(effect["navigation_only"])
        self.assertTrue(effect["popup_absent_successor_required"])
        self.assertTrue(effect["source_context_successor_required"])
        self.assertTrue(effect["bounded_single_close"])
        self.assertFalse(effect["identical_retry"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("unknown", "ambiguous", "generic close", "resource", "combat"):
            self.assertIn(marker, forbidden)
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])


    def test_gathering_record_binds_supported_variants_and_free_node_guards(self) -> None:
        record = self.records["gathering_resources"]
        self.assertEqual(record["record_type"], "gathering_resources")
        self.assertEqual(record["recurrence"], "pulse_march_slot_timer")
        self.assertEqual(record["record_revision"], "gathering_resources-v3")
        self.assertEqual(record["semantic_entry_route"]["source_home_authorities"], ["HOME_READY"])
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["WORLD", "SEARCH", "RESOURCE_CATEGORY", "LEVEL_5_NODE", "MARCH"],
        )
        target = record["target"]
        self.assertEqual(target["supported_variants"], ["WOOD", "STEEL", "GAS"])
        self.assertEqual(target["level"], 5)
        self.assertEqual(target["occupancy"], "free_only")
        self.assertEqual(target["march_slot"], "one_free_slot")
        self.assertEqual(target["formation"], "default")
        self.assertFalse(target["source_daily_row_required"])
        self.assertEqual(target["food_authority"], "forbidden")
        self.assertNotIn("commander_talent_requirement", target)
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertNotIn("commander_talent_preset_verified_before_dispatch", effect)
        self.assertTrue(effect["free_march_slot_required"])
        self.assertTrue(effect["default_formation_required"])
        self.assertTrue(effect["outbound_timer_successor_required"])
        self.assertTrue(effect["return_timer_successor_required"])
        self.assertTrue(effect["terminal_home_successor_required"])
        self.assertTrue(effect["resource_progress_successor_required"])
        self.assertFalse(effect["identical_retry"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("food", "occupied", "level-5", "existing march", "gas", "identical retry"):
            self.assertIn(marker, forbidden)
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

    def test_zombie_lair_record_binds_daily_and_maintenance_ownership(self) -> None:
        record = self.records["zombie_lair"]
        self.assertEqual(record["record_type"], "zombie_lair")
        self.assertEqual(record["record_revision"], "zombie_lair-v1")
        self.assertEqual(record["semantic_entry_route"]["source_home_authorities"], ["HOME_CANONICAL"])
        target = record["target"]
        self.assertEqual(target["minimum_level"], 30)
        self.assertEqual(target["maximum_level"], 55)
        self.assertEqual(target["join_control"], "QUICK_JOIN")
        self.assertEqual(target["stamina_per_join"], 28)
        self.assertEqual(target["level_60"], "forbidden")
        self.assertEqual(target["stamina_refill"], "forbidden")
        self.assertEqual(
            record["daily_ownership"]["daily_owner"],
            "first_successful_eligible_join_per_reset",
        )
        self.assertEqual(
            record["daily_ownership"]["point_credit_trigger"],
            "first_successful_eligible_join_per_reset",
        )
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("level 60", "stamina refill", "unknown level", "identical retry"):
            self.assertIn(marker, forbidden)

    def test_recruitment_record_separates_basic_daily_from_tier_maintenance(self) -> None:
        record = self.records["noahs_tavern_recruitment"]
        self.assertEqual(record["record_type"], "noahs_tavern_recruitment")
        self.assertEqual(record["record_revision"], "noahs_tavern_recruitment-v1")
        self.assertEqual(record["semantic_entry_route"]["target"], "NOAHS_TAVERN")
        self.assertEqual(record["target"]["quantity"], 1)
        self.assertTrue(record["target"]["tier_selection_required"])
        self.assertEqual(record["target"]["tiers"]["basic"]["free_attempts_per_reset"], 5)
        self.assertEqual(record["target"]["tiers"]["basic"]["cooldown_seconds"], 600)
        self.assertEqual(record["target"]["tiers"]["intermediate"]["cooldown_seconds"], 86400)
        self.assertEqual(record["target"]["tiers"]["advanced"]["cooldown_seconds"], 172800)
        effect = record["semantic_effect"]
        self.assertTrue(effect["reset_bound_basic_progress"])
        self.assertTrue(effect["independent_tier_cooldowns"])
        self.assertTrue(effect["dispatch_is_not_success_proof"])
        self.assertFalse(effect["identical_retry"])
        self.assertEqual(record["daily_ownership"]["daily_owner"], "five_basic_free_singles_per_reset")
        self.assertEqual(record["daily_ownership"]["point_credit_trigger"], "five_basic_recruit_successors")
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")
    def test_campaign_ap_record_binds_budget_and_forbidden_modes(self) -> None:
        record = self.records["campaign_ap"]
        self.assertEqual(record["record_type"], "campaign_ap")
        self.assertEqual(record["record_revision"], "campaign_ap-v1")
        self.assertEqual(record["semantic_entry_route"]["target"], "CAMPAIGN")
        self.assertEqual(
            record["target"]["supported_story_destinations"],
            ["1-20-9", "1-15-9", "2-2-9"],
        )
        self.assertEqual(record["target"]["stage_costs"], {"1-15-9": 14, "1-20-9": 16, "2-2-9": 20})
        self.assertEqual(record["target"]["maximum_ap"], 120)
        self.assertFalse(record["target"]["refill_allowed"])
        self.assertEqual(record["quantity_cost"]["cost"]["unit"], "AP")
        self.assertTrue(record["semantic_effect"]["exact_ap_delta_required"])
        self.assertTrue(record["semantic_effect"]["result_successor_required"])
        self.assertTrue(record["semantic_effect"]["no_refill"])
        self.assertFalse(record["semantic_effect"]["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "sweep",
            "blitz",
            "auto complete",
            "ap refill",
            "ultimate challenge",
            "unknown cost",
        ):
            self.assertIn(marker, forbidden)

    def test_troop_training_record_preserves_four_type_queue_and_daily_policy(self) -> None:
        record = self.records["troop_training"]
        self.assertEqual(record["record_type"], "troop_training")
        self.assertEqual(record["record_revision"], "troop_training-v6")
        self.assertEqual(record["semantic_entry_route"]["target"], "TRAINING_FACILITIES")
        variants = record["target"]["per_type_contract"]
        self.assertEqual(variants["fighter"]["target_tier"], 8)
        self.assertEqual(variants["fighter"]["quantity_mode"], "current_max")
        self.assertEqual(variants["fighter"]["training_policy"], "continuous")
        self.assertTrue(variants["fighter"]["allow_resource_boxes"])
        self.assertEqual(variants["vehicle"]["target_tier"], 1)
        self.assertEqual(variants["vehicle"]["training_policy"], "continuous")
        self.assertEqual(variants["shooter"]["quantity"], 250)
        self.assertEqual(variants["shooter"]["training_policy"], "once_daily")
        self.assertFalse(variants["shooter"]["allow_resource_boxes"])
        self.assertEqual(variants["rider"]["quantity"], 250)
        self.assertEqual(variants["rider"]["training_policy"], "once_daily")
        self.assertFalse(variants["rider"]["allow_resource_boxes"])
        self.assertEqual(
            record["target"]["current_max_quantity_source"],
            "fresh_current_frame_numeric_maximum",
        )
        self.assertIsNone(record["target"]["current_max_fixed_fallback"])
        self.assertEqual(
            record["target"]["commander_talent_requirement"]["required_preset"],
            "Training",
        )
        self.assertTrue(
            record["target"]["commander_talent_requirement"]["route_approval_required"]
        )
        boxes = record["target"]["resource_box_continuation"]
        self.assertNotIn("implementation_status", boxes)
        self.assertEqual(boxes["missing_native_evidence"],
                         ["exact_popup_box_identity", "owned_quantity", "consumption_count"])
        self.assertFalse(boxes["consumption_allowed_without_exact_box_evidence"])
        metadata_record = deepcopy(record)
        metadata_record["target"]["resource_box_continuation"]["implementation_status"] = "evidence_required"
        metadata_record["record_digest"] = record_digest(metadata_record)
        with self.assertRaises(ProductAuthorityError):
            validate_product_record(metadata_record)

        invalid_maximum = deepcopy(record)
        invalid_maximum["target"]["current_max_fixed_fallback"] = 1000
        invalid_maximum["record_digest"] = record_digest(invalid_maximum)
        with self.assertRaises(ProductAuthorityError):
            validate_product_record(invalid_maximum)
        invalid_boxes = deepcopy(record)
        invalid_boxes["target"]["resource_box_continuation"]["allowed_types"] = [
            "fighter",
            "vehicle",
            "shooter",
        ]
        invalid_boxes["record_digest"] = record_digest(invalid_boxes)
        with self.assertRaises(ProductAuthorityError):
            validate_product_record(invalid_boxes)
        self.assertTrue(record["semantic_effect"]["active_queue_successor_required"])
        self.assertTrue(record["semantic_effect"]["positive_timer_spatial_association_required"])
        self.assertTrue(record["semantic_effect"]["once_daily_reset_identity_bound"])
        self.assertFalse(record["semantic_effect"]["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
    def test_direct_records_reject_daily_owner_and_point_credit_even_with_fresh_digests(self) -> None:
        for field, replacement in (
            ("daily_owner", "aggregate_daily_claim"),
            ("point_credit_trigger", "positive_points_delta_and_ordinary_claim_controls_cleared"),
        ):
            changed = deepcopy(self.authority)
            record = changed["product_records"][0]
            record["daily_ownership"][field] = replacement
            record["record_digest"] = record_digest(record)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaisesRegex(
                ProductAuthorityError,
                "direct product record must not own Daily",
            ):
                validate_product_authority(changed)

    def test_aggregate_claim_requires_batch_scoping_and_forbids_row_inventory(self) -> None:
        changed = deepcopy(self.authority)
        daily = next(
            item
            for item in changed["product_records"]
            if item["record_id"] == "aggregate_daily_claim"
        )
        daily["semantic_effect"]["at_most_once_per_current_ready_batch_per_pass"] = False
        daily["record_digest"] = record_digest(daily)
        changed["authority_digest"] = authority_digest(changed)
        with self.assertRaisesRegex(ProductAuthorityError, "batch-scoped dispatch"):
            validate_product_authority(changed)

        changed = deepcopy(self.authority)
        daily = next(
            item
            for item in changed["product_records"]
            if item["record_id"] == "aggregate_daily_claim"
        )
        daily["forbidden_actions"] = [
            action for action in daily["forbidden_actions"]
            if action.casefold() != "daily objective-row inventory"
        ]
        daily["record_digest"] = record_digest(daily)
        changed["authority_digest"] = authority_digest(changed)
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(changed)

    def test_aggregate_success_trigger_binds_sources_and_excludes_point_credit(self) -> None:
        mutations = (
            (
                "exact_free_claim",
                lambda record: record["aggregate_success_trigger"].__setitem__(
                    "action", "claim_any_control"
                ),
            ),
            (
                "all_controls_cleared",
                lambda record: record["aggregate_success_trigger"].__setitem__(
                    "successor", "positive_points_delta"
                ),
            ),
            (
                "source_bounds",
                lambda record: record["aggregate_success_trigger"].__setitem__(
                    "source_bounds", ["current_frame"]
                ),
            ),
            (
                "point_credit_trigger",
                lambda record: record["daily_ownership"].__setitem__(
                    "point_credit_trigger", "positive_points_delta"
                ),
            ),
            (
                "positive_points_gate",
                lambda record: record["semantic_effect"].__setitem__(
                    "positive_points_delta_required", True
                ),
            ),
            (
                "zero_claim_scan_gate",
                lambda record: record["semantic_effect"].__setitem__(
                    "complete_zero_claim_control_scan_required", True
                ),
            ),
            (
                "static_closure_gate",
                lambda record: record["semantic_effect"].__setitem__(
                    "all_chests_static_closure_required", True
                ),
            ),
            (
                "chests_suppressed_by_residual_controls",
                lambda record: record["semantic_effect"].__setitem__(
                    "ready_chests_independent_of_aggregate_claim_and_residual_ordinary_controls", False
                ),
            ),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            daily = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "aggregate_daily_claim"
            )
            mutate(daily)
            daily["record_digest"] = record_digest(daily)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)


    def test_activity_milestone_product_is_per_chest_and_not_ordinary_claim_owned(self) -> None:
        record = self.records["activity_milestone_claim"]
        self.assertEqual(record["record_type"], "activity_milestone_claim")
        self.assertEqual(record["record_revision"], "activity_milestone_claim-v2")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(record["semantic_entry_route"]["target"], "QUEST")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["QUEST", "ACTIVITY_MILESTONES"],
        )
        target = record["target"]
        self.assertEqual(target["kind"], "activity_milestone_chest")
        self.assertEqual(target["control"], "MILESTONE_CHEST")
        self.assertEqual(
            target["eligibility"],
            "one_current_ready_free_milestone_chest_per_action",
        )
        self.assertTrue(target["distinct_chest_identity_required"])
        self.assertTrue(target["one_claim_per_chest_per_reset"])
        self.assertTrue(target["distinct_chests_per_reset_allowed"])
        self.assertTrue(target["fully_visible"])
        self.assertTrue(target["reset_bound"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["same_milestone_successor_required"])
        self.assertTrue(effect["same_chest_identity_and_reset_bound"])
        self.assertFalse(effect["positive_bound_points_successor_allowed"])
        self.assertEqual(
            effect["success_requires"],
            "same_chest_milestone_state_transition_ready_to_claimed_opened_or_removed",
        )
        self.assertTrue(effect["dispatch_is_not_success_proof"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "not-ready",
            "already-claimed",
            "clipped",
            "cost-bearing",
            "ordinary claim",
            "unknown",
            "contradictory",
            "stale",
            "real-money",
            "identical retry",
            "points-only successor",
        ):
            self.assertIn(marker, forbidden)
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")
    def test_activity_milestone_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            ("ready", lambda record: record["target"].__setitem__("eligibility", "already_claimed")),
            ("free_only", lambda record: record["quantity_cost"]["cost"].__setitem__("free_only", False)),
            ("successor", lambda record: record["semantic_effect"].__setitem__("same_milestone_successor_required", False)),
            ("same_chest", lambda record: record["semantic_effect"].__setitem__("same_chest_identity_and_reset_bound", False)),
            ("points_only", lambda record: record["semantic_effect"].__setitem__("positive_bound_points_successor_allowed", True)),
            ("multiple_chests", lambda record: record["target"].__setitem__("distinct_chests_per_reset_allowed", False)),
            ("dispatch_separation", lambda record: record["semantic_effect"].__setitem__("dispatch_is_not_success_proof", False)),
            ("retry_denial", lambda record: record["semantic_effect"].__setitem__("identical_retry", True)),
            ("ordinary_ownership", lambda record: record["daily_ownership"].__setitem__("point_credit_trigger", "points")),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            milestone = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "activity_milestone_claim"
            )
            mutate(milestone)
            milestone["record_digest"] = record_digest(milestone)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)
    def test_digest_excludes_only_its_own_field(self) -> None:
        first = {"a": 1, "digest": "0" * 64}
        second = {"a": 1, "digest": "f" * 64}
        self.assertEqual(canonical_digest(first), canonical_digest(second))
        record = deepcopy(self.records["use_resource_item"])
        self.assertEqual(record_digest(record), record["record_digest"])
        self.assertEqual(authority_digest(self.authority), self.authority["authority_digest"])

    def test_daily_reset_policy_is_exact_and_typed(self) -> None:
        policy = validate_daily_reset_policy(self.authority)
        self.assertEqual(policy["policy_id"], DAILY_RESET_POLICY_ID)
        self.assertEqual(policy["status"], DAILY_RESET_POLICY_STATUS)
        self.assertEqual(policy["timezone"], DAILY_RESET_POLICY_TIMEZONE)
        self.assertEqual(policy["reset_time"], DAILY_RESET_POLICY_RESET_TIME)
        self.assertEqual(policy["interval_seconds"], DAILY_RESET_POLICY_INTERVAL_SECONDS)
        self.assertEqual(policy["source"], DAILY_RESET_POLICY_SOURCE)
        self.assertEqual(get_daily_reset_policy(self.authority), policy)

        for field, replacement in (
            ("timezone", "America/New_York"),
            ("reset_time", "00:00:01"),
            ("interval_seconds", 3600),
            ("status", "prohibited"),
            ("source", "test"),
        ):
            with self.subTest(field=field):
                changed = deepcopy(self.authority)
                reset_policy = next(
                    item
                    for item in changed["policies"]
                    if item["policy_id"] == DAILY_RESET_POLICY_ID
                )
                reset_policy[field] = replacement
                changed["authority_digest"] = authority_digest(changed)
                with self.assertRaises(ProductAuthorityError):
                    validate_product_authority(changed)

    def test_stale_contract_authority_binding_fails_closed(self) -> None:
        contract = self.contracts["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]
        for field, replacement in (
            ("product_authority_revision", "flow-delivery-product-authority-v2-r1"),
            ("product_authority_digest", "0" * 64),
        ):
            with self.subTest(field=field):
                changed = deepcopy(contract)
                changed["product_authority_binding"][field] = replacement
                with self.assertRaises(ProductAuthorityError):
                    validate_contract_product_authority_bindings(
                        self.authority,
                        {"resource": changed},
                    )
    def test_combined_daily_contract_reuses_typed_activity_milestone_record(self) -> None:
        contract = self.contracts["DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"]
        validate_contract_product_authority_bindings(
            self.authority,
            {"daily": contract},
        )
        aggregate = self.records["aggregate_daily_claim"]
        activity_binding = aggregate["additional_product_record_bindings"][0]
        self.assertEqual(
            contract["product_authority_binding"]["product_record_id"],
            "aggregate_daily_claim",
        )
        self.assertEqual(activity_binding["binding_type"], "typed_product_record")
        self.assertEqual(activity_binding["product_record_id"], "activity_milestone_claim")
        self.assertEqual(
            activity_binding["product_record_revision"],
            "activity_milestone_claim-v2",
        )
        self.assertEqual(
            activity_binding["product_record_digest"],
            self.records["activity_milestone_claim"]["record_digest"],
        )

        stale_record = deepcopy(self.authority)
        aggregate = next(
            item
            for item in stale_record["product_records"]
            if item["record_id"] == "aggregate_daily_claim"
        )
        aggregate["additional_product_record_bindings"][0][
            "product_record_digest"
        ] = "0" * 64
        aggregate["record_digest"] = record_digest(aggregate)
        stale_record["authority_digest"] = authority_digest(stale_record)
        with self.assertRaisesRegex(
            ProductAuthorityError,
            "stale Activity Milestone product record",
        ):
            validate_product_authority(stale_record)


    def test_resource_semantics_are_direct_owned_one_item(self) -> None:
        record = self.records["use_resource_item"]
        self.assertEqual(record["record_revision"], "use_resource_item-v3")
        self.assertEqual(record["objective"], "use_resource_item")
        self.assertEqual(
            record["semantic_entry_route"]["source_home_authorities"],
            ["HOME_READY", "HOME_CANONICAL"],
        )
        self.assertEqual(record["semantic_entry_route"]["target"], "BAG")
        self.assertEqual(record["target"]["item_name"], "1K Food")
        self.assertTrue(record["target"]["owned"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 1)
        self.assertEqual(
            record["semantic_effect"]["owned_inventory_delta"],
            -1,
        )
        self.assertFalse(record["semantic_effect"]["food_balance_ocr_required"])
        self.assertTrue(record["semantic_effect"]["last_item_one_to_zero_included"])
        self.assertTrue(record["semantic_effect"]["consumed_item_identity_bound_to_pre_use_observation"])
        self.assertTrue(
            record["semantic_effect"]["zero_after_requires_attributable_last_item_consumption_successor"]
        )
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        invalid_delta = deepcopy(record)
        invalid_delta["semantic_effect"]["owned_inventory_delta"] = 0
        invalid_delta["record_digest"] = record_digest(invalid_delta)
        with self.assertRaisesRegex(ProductAuthorityError, "exact owned-item decrement"):
            validate_product_record(invalid_delta)
        invalid_home = deepcopy(record)
        invalid_home["terminal_requirement"]["return_required"] = False
        invalid_home["record_digest"] = record_digest(invalid_home)
        with self.assertRaisesRegex(ProductAuthorityError, "canonical Home return"):
            validate_product_record(invalid_home)
        invalid_ocr = deepcopy(record)
        invalid_ocr["semantic_effect"]["food_balance_ocr_required"] = True
        invalid_ocr["record_digest"] = record_digest(invalid_ocr)
        with self.assertRaisesRegex(ProductAuthorityError, "Food-balance OCR"):
            validate_product_record(invalid_ocr)
        unattributed_zero = deepcopy(record)
        unattributed_zero["semantic_effect"][
            "zero_after_requires_attributable_last_item_consumption_successor"
        ] = False
        unattributed_zero["record_digest"] = record_digest(unattributed_zero)
        with self.assertRaisesRegex(ProductAuthorityError, "attributable last-item"):
            validate_product_record(unattributed_zero)

    def test_enhancement_semantics_separate_use_and_confirm(self) -> None:
        record = self.records["enhancement_family"]
        self.assertEqual(record["target"]["variants"], ["Gear", "Chip", "Module"])
        self.assertTrue(record["target"]["independent"])
        actions = {item["action_id"]: item for item in record["actions"]}
        self.assertFalse(actions["quantity_selection_use"]["consumes_material"])
        self.assertFalse(actions["quantity_selection_use"]["owns_material_decrement"])
        self.assertTrue(actions["consuming_confirm"]["consumes_material"])
        self.assertTrue(actions["consuming_confirm"]["owns_material_decrement"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("auto select", "higher-star", "premium", "unknown", "real-money"):
            self.assertIn(marker, forbidden)

    def test_supply_semantics_are_free_evidence_only(self) -> None:
        record = self.records["supply_depot"]
        self.assertEqual(record["semantic_entry_route"]["target"], "SUPPLY_DEPOT")
        self.assertEqual(record["target"]["free_control"], "Free")
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        self.assertFalse(record["semantic_effect"]["paid_collection"])
        self.assertEqual(record["daily_ownership"]["daily_owner"], None)
        self.assertNotIn("daily 5/5", json.dumps(record["semantic_effect"]).casefold())

    def test_nova_praise_product_is_one_free_pulse_and_not_daily_owned(self) -> None:
        record = self.records["nova_praise"]
        self.assertEqual(record["record_type"], "nova_praise")
        self.assertEqual(record["recurrence"], "cooldown_pulse")
        self.assertEqual(record["semantic_entry_route"]["target"], "RESEARCH_LAB")
        self.assertEqual(record["target"]["eligibility"], "one_free_attempt_available")
        self.assertEqual(record["target"]["control"], "Praise")
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertEqual((effect["attempts_before"], effect["attempts_after"]), ("X", "X-1"))
        self.assertEqual(effect["cooldown_seconds"], 300)
        self.assertFalse(effect["paid_fallback"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")

    def test_nova_praise_required_action_success_and_terminal_fields_fail_closed(self) -> None:
        mutations = (
            ("action", lambda record: record.__setitem__("action", "safe_return_home")),
            (
                "cooldown_policy",
                lambda record: record["semantic_effect"].__setitem__(
                    "cooldown_policy", "fixed_300_seconds"
                ),
            ),
            (
                "success_requires",
                lambda record: record["semantic_effect"].__setitem__(
                    "success_requires", "attempt_decrement_only"
                ),
            ),
            (
                "terminal_home_authority",
                lambda record: record["terminal_requirement"].__setitem__(
                    "home_authority", "HOME_READY"
                ),
            ),
            (
                "terminal_return_required",
                lambda record: record["terminal_requirement"].__setitem__(
                    "return_required", False
                ),
            ),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            nova = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "nova_praise"
            )
            mutate(nova)
            nova["record_digest"] = record_digest(nova)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)

    def test_ultimate_challenge_product_is_one_free_reset_bound_flee(self) -> None:
        record = self.records["ultimate_challenge"]
        self.assertEqual(record["record_type"], "ultimate_challenge")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(record["semantic_entry_route"]["target"], "CAMPAIGN")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["CAMPAIGN", "ULTIMATE_CHALLENGE"],
        )
        self.assertEqual(record["target"]["control"], "Flee")
        self.assertTrue(record["target"]["reset_bound"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertEqual(effect["flee_ceiling"], 1)
        self.assertEqual(effect["resource_delta"], 0)
        self.assertTrue(effect["resource_delta_is_zero"])
        self.assertTrue(effect["dispatch_is_not_success_proof"])
        self.assertTrue(effect["terminal_home_separate"])
        self.assertFalse(effect["repeated_flee"])
        self.assertFalse(effect["identical_retry"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("auto battle", "second flee", "campaign ap", "ap spend"):
            self.assertIn(marker, forbidden)
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")

    def test_ultimate_challenge_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            ("flee_ceiling", lambda record: record["semantic_effect"].__setitem__("flee_ceiling", 2)),
            ("zero_cost", lambda record: record["quantity_cost"]["cost"].__setitem__("amount", 1)),
            ("repeat_denial", lambda record: record["semantic_effect"].__setitem__("repeated_flee", True)),
            ("terminal_separation", lambda record: record["semantic_effect"].__setitem__("terminal_home_separate", False)),
            ("direct_ownership", lambda record: record["daily_ownership"].__setitem__("daily_owner", "ultimate_challenge")),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            ultimate = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "ultimate_challenge"
            )
            mutate(ultimate)
            ultimate["record_digest"] = record_digest(ultimate)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)

    def test_bioenhancer_product_is_one_free_cooldown_pulse_and_not_daily_owned(self) -> None:
        record = self.records["bioenhancer_research"]
        self.assertEqual(record["record_type"], "bioenhancer_research")
        self.assertEqual(record["recurrence"], "cooldown_pulse")
        self.assertEqual(record["semantic_entry_route"]["target"], "RESEARCH_LAB")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["RESEARCH_LAB", "BIOENHANCER"],
        )
        self.assertEqual(record["target"]["eligibility"], "one_free_attempt_available")
        self.assertEqual(record["target"]["control"], "Free Research 1x")
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["cooldown_successor_required"])
        self.assertTrue(effect["count_text_not_sufficient"])
        self.assertTrue(effect["dispatch_is_not_success_proof"])
        self.assertFalse(effect["paid_fallback"])
        self.assertFalse(effect["ten_x_fallback"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")

    def test_bioenhancer_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            ("action", lambda record: record.__setitem__("action", "research_10x")),
            (
                "free_only",
                lambda record: record["quantity_cost"]["cost"].__setitem__(
                    "free_only", False
                ),
            ),
            (
                "cooldown_successor",
                lambda record: record["semantic_effect"].__setitem__(
                    "cooldown_successor_required", False
                ),
            ),
            (
                "dispatch_separation",
                lambda record: record["semantic_effect"].__setitem__(
                    "dispatch_is_not_success_proof", False
                ),
            ),
            (
                "retry_denial",
                lambda record: record["semantic_effect"].__setitem__(
                    "identical_retry", True
                ),
            ),
            (
                "direct_ownership",
                lambda record: record["daily_ownership"].__setitem__(
                    "daily_owner", "bioenhancer_research"
                ),
            ),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            bio = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "bioenhancer_research"
            )
            mutate(bio)
            bio["record_digest"] = record_digest(bio)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)

    def test_ruins_product_attempts_challenge_first_and_keeps_ready_chests_independent(self) -> None:
        record = self.records["ruins_challenge"]
        self.assertEqual(record["record_type"], "ruins_challenge")
        self.assertEqual(record["record_revision"], "ruins_challenge-v2")
        self.assertEqual(record["recurrence"], "reset_scoped_cooldown_pulse")
        self.assertEqual(record["semantic_entry_route"]["target"], "RUINS")
        self.assertEqual(record["target"]["challenge_identity"], "current_allowlisted_npc")
        self.assertEqual(record["target"]["challenge_control"], "Attack/Dispatch")
        self.assertEqual(record["target"]["challenge_quantity"], 1)
        self.assertEqual(record["target"]["chest_eligibility"], "visible_green_ready")
        self.assertEqual(
            record["target"]["challenge_unavailable_behavior"],
            "continue_to_independently_ready_overview_chests",
        )
        self.assertIsNone(record["quantity_cost"]["quantity"])
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        effect = record["semantic_effect"]
        self.assertTrue(effect["challenge_before_overview"])
        self.assertTrue(effect["challenge_success_not_required_for_ready_chests"])
        self.assertTrue(effect["recognized_loss_counts_as_participation"])
        self.assertEqual(effect["dispatch_limit_per_exact_stage_per_reset"], 1)
        self.assertTrue(effect["verified_win_requires_fresh_next_permitted_stage"])
        self.assertTrue(effect["first_recognized_loss_finishes_challenge_for_reset"])
        self.assertTrue(effect["finite_visit_budget_pause_is_resumable"])
        self.assertTrue(effect["budget_pause_is_not_daily_completion"])
        self.assertNotIn("attempt_limit_per_reset", effect)
        self.assertTrue(effect["challenge_unavailability_does_not_fabricate_a_result"])
        self.assertTrue(effect["per_category_claim_and_unknown_state_persisted"])
        self.assertTrue(effect["unknown_consequential_effects_block_restart_retry"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

    def test_ruins_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            (
                "stage_replay",
                lambda record: record["semantic_effect"].__setitem__(
                    "dispatch_limit_per_exact_stage_per_reset", 2
                ),
            ),
            (
                "loss_not_durable",
                lambda record: record["semantic_effect"].__setitem__(
                    "first_recognized_loss_finishes_challenge_for_reset", False
                ),
            ),
            (
                "budget_marks_daily_complete",
                lambda record: record["semantic_effect"].__setitem__(
                    "budget_pause_is_not_daily_completion", False
                ),
            ),
            (
                "reset_wide_attempt_cap",
                lambda record: record["semantic_effect"].__setitem__(
                    "attempt_limit_per_reset", 1
                ),
            ),
            (
                "challenge_order",
                lambda record: record["semantic_effect"].__setitem__(
                    "challenge_before_overview", False
                ),
            ),
            (
                "unavailable_no_fabricated_result",
                lambda record: record["semantic_effect"].__setitem__(
                    "challenge_unavailability_does_not_fabricate_a_result", False
                ),
            ),
            (
                "non_green_claim",
                lambda record: record["target"].__setitem__(
                    "chest_eligibility", "any_visible"
                ),
            ),
            (
                "unavailable_blocks_chests",
                lambda record: record["target"].__setitem__(
                    "challenge_unavailable_behavior", "stop"
                ),
            ),
            (
                "paid_cost",
                lambda record: record["quantity_cost"]["cost"].__setitem__(
                    "free_only", False
                ),
            ),
            (
                "unknown_retry",
                lambda record: record["semantic_effect"].__setitem__(
                    "identical_retry", True
                ),
            ),
            (
                "daily_owner",
                lambda record: record["daily_ownership"].__setitem__(
                    "daily_owner", "ruins_challenge"
                ),
            ),
            (
                "revision",
                lambda record: record.__setitem__(
                    "record_revision", "ruins_challenge-v1"
                ),
            ),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            ruins = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "ruins_challenge"
            )
            mutate(ruins)
            ruins["record_digest"] = record_digest(ruins)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)

    def test_alliance_help_product_enforces_quota_and_partial_progress(self) -> None:
        record = self.records["alliance_help"]
        self.assertEqual(record["record_type"], "alliance_help")
        self.assertEqual(record["record_revision"], "alliance_help-v2")
        self.assertEqual(record["recurrence"], "reset_scoped_cooldown_pulse")
        self.assertEqual(record["semantic_entry_route"]["target"], "ALLIANCE")
        self.assertEqual(record["target"]["help_all_control"], "Help All")
        self.assertEqual(
            record["target"]["help_all_count_rule"],
            "actual_numeric_result_credit_without_pre_dispatch_census",
        )
        self.assertEqual(record["target"]["individual_control"], "Help")
        self.assertEqual(record["quantity_cost"]["quantity"], 10)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertEqual(effect["successful_request_goal"], 10)
        self.assertEqual(effect["operation_ordinal_minimum"], 1)
        self.assertIsNone(effect["operation_ordinal_ceiling"])
        self.assertTrue(effect["actual_numeric_credit_not_clipped_to_goal"])
        self.assertTrue(effect["positive_unknown_count_batch_confirmed_and_deferred"])
        self.assertTrue(effect["unknown_count_batch_is_not_unknown_effect"])
        self.assertFalse(effect["request_census_required"])
        self.assertFalse(effect["coin_balance_or_delta_required"])
        self.assertEqual(effect["maximum_help_all_batches_per_visit"], 1)
        self.assertTrue(effect["confirmed_partial_quota_persisted_across_restart"])
        self.assertTrue(effect["transport_call_is_not_success"])
        self.assertTrue(effect["static_help_screen_is_not_success"])
        self.assertTrue(effect["unknown_successor_persisted_and_identical_retry_denied"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertIsNone(record["daily_ownership"]["point_credit_trigger"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

    def test_alliance_help_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            (
                "quota",
                lambda record: record["quantity_cost"].__setitem__("quantity", 9),
            ),
            (
                "help_all_census_gate",
                lambda record: record["semantic_effect"].__setitem__(
                    "request_census_required", True
                ),
            ),
            (
                "operation_ordinal_cap",
                lambda record: record["semantic_effect"].__setitem__(
                    "operation_ordinal_ceiling", 10
                ),
            ),
            (
                "clip_actual_credit",
                lambda record: record["semantic_effect"].__setitem__(
                    "actual_numeric_credit_not_clipped_to_goal", False
                ),
            ),
            (
                "uncounted_batch_fabricates_completion",
                lambda record: record["semantic_effect"].__setitem__(
                    "positive_unknown_count_batch_confirmed_and_deferred", False
                ),
            ),
            (
                "transport_success",
                lambda record: record["semantic_effect"].__setitem__(
                    "transport_call_is_not_success", False
                ),
            ),
            (
                "partial_quota",
                lambda record: record["semantic_effect"].__setitem__(
                    "confirmed_partial_quota_persisted_across_restart", False
                ),
            ),
            (
                "free_cost",
                lambda record: record["quantity_cost"]["cost"].__setitem__(
                    "amount", 1
                ),
            ),
            (
                "retry",
                lambda record: record["semantic_effect"].__setitem__(
                    "identical_retry", True
                ),
            ),
            (
                "daily_owner",
                lambda record: record["daily_ownership"].__setitem__(
                    "daily_owner", "alliance_help"
                ),
            ),
            (
                "revision",
                lambda record: record.__setitem__(
                    "record_revision", "alliance_help-v1"
                ),
            ),
        )
        for field, mutate in mutations:
            changed = deepcopy(self.authority)
            help_record = next(
                item
                for item in changed["product_records"]
                if item["record_id"] == "alliance_help"
            )
            mutate(help_record)
            help_record["record_digest"] = record_digest(help_record)
            changed["authority_digest"] = authority_digest(changed)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_product_authority(changed)

    def test_product_records_have_no_forbidden_authority_domains(self) -> None:
        forbidden = {
            "coordinate",
            "coordinates",
            "ocr",
            "profile",
            "profile_id",
            "runtime",
            "runtime_binding",
            "runtime_profile",
            "proof",
            "proof_state",
            "status",
            "queue",
            "registration",
            "scheduler",
            "conductor",
            "plan",
            "backlog",
        }

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).casefold().replace("-", "_")
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        for record in self.records.values():
            self.assertTrue(forbidden.isdisjoint(set(keys(record))))

    def test_all_bound_representative_contracts_bind_exact_authority(self) -> None:
        validate_contract_product_authority_bindings(self.authority, self.contracts)
        bound = {
            contract["product_authority_binding"]["product_record_id"]
            for contract in self.contracts.values()
            if "product_authority_binding" in contract
        }
        self.assertEqual(bound, set(self.records))


    def test_research_farm_and_hall_routes_reject_typed_record_substitution(self) -> None:
        for flow_id, wrong_record_id in (
            (
                "RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION",
                "food_farm_output_boost",
            ),
            (
                "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION",
                "recommended_research",
            ),
            (
                "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION",
                "hero_duel",
            ),
        ):
            contract = deepcopy(self.contracts[flow_id])
            wrong_record = self.records[wrong_record_id]
            binding = contract["product_authority_binding"]
            binding["product_record_id"] = wrong_record_id
            binding["product_record_revision"] = wrong_record["record_revision"]
            binding["product_record_digest"] = wrong_record["record_digest"]
            with self.subTest(flow_id=flow_id), self.assertRaises(ProductAuthorityError):
                validate_contract_product_authority_bindings(
                    self.authority,
                    {flow_id: contract},
                )
    def test_ruins_and_alliance_help_contracts_bind_their_exact_typed_records(self) -> None:
        for flow_id, record_id, revision in (
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
        ):
            contract = self.contracts[flow_id]
            binding = contract["product_authority_binding"]
            record = self.records[record_id]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(binding["product_record_id"], record_id)
                self.assertEqual(binding["product_record_revision"], revision)
                self.assertEqual(binding["product_record_revision"], record["record_revision"])
                self.assertEqual(binding["product_record_digest"], record["record_digest"])
                self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
                self.assertEqual(
                    binding["product_authority_digest"],
                    self.authority["authority_digest"],
                )
                self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
                self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
                self.assertFalse(binding["selected_daily_prerequisite"])
                self.assertEqual(contract["registration_state"], "disabled")
                self.assertFalse(contract["production_eligible"])
                self.assertEqual(contract["proof_state"], "evidence_required")

    def test_ruins_and_alliance_help_records_cannot_bind_each_others_routes(self) -> None:
        for flow_id, wrong_record_id in (
            ("RUINS-CHALLENGE-HOME-ATLAS-MIGRATION", "alliance_help"),
            ("ALLIANCE-HELP-TEN-FREE-REQUESTS", "ruins_challenge"),
        ):
            contract = deepcopy(self.contracts[flow_id])
            wrong_record = self.records[wrong_record_id]
            binding = contract["product_authority_binding"]
            binding["product_record_id"] = wrong_record_id
            binding["product_record_revision"] = wrong_record["record_revision"]
            binding["product_record_digest"] = wrong_record["record_digest"]
            with self.subTest(flow_id=flow_id), self.assertRaises(ProductAuthorityError):
                validate_contract_product_authority_bindings(
                    self.authority,
                    {flow_id: contract},
                )

    def test_nova_praise_contract_binds_direct_record_and_preserves_disabled_state(self) -> None:
        contract = self.contracts["NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "nova_praise")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["home_authority"], "HOME_LOCALIZED")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")

    def test_ultimate_contract_binds_direct_record_and_retains_composite_proof(self) -> None:
        contract = self.contracts["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "ultimate_challenge")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["home_authority"], "HOME_CANONICAL")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["replay_fixture_proof_state"], "current")
        notes = " ".join(contract["evidence_requirements"]).casefold()
        self.assertIn("attempt 13", notes)
        self.assertIn("attempt 14", notes)
        self.assertIn("composite", notes)

    def test_bioenhancer_contract_binds_direct_record_and_preserves_historical_boundary(self) -> None:
        contract = self.contracts["BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "bioenhancer_research")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_revision"], "bioenhancer_research-v1")
        self.assertEqual(binding["home_authority"], "HOME_LOCALIZED")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(binding["selected_daily_prerequisite"])
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["proof_state"], "evidence_required")
        self.assertEqual(contract["replay_fixture_proof_state"], "evidence_required")
        evidence = " ".join(contract["evidence_requirements"]).casefold()
        self.assertIn("historical bliss", evidence)
        self.assertIn("current bluestacks", evidence)
        self.assertIn("non-accepting", evidence)

    def test_stale_revision_or_digest_fails_closed(self) -> None:
        stale_revision = deepcopy(self.authority)
        stale_revision["authority_revision"] = "old-authority-revision"
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(stale_revision)

        stale_payload = deepcopy(self.authority)
        stale_payload["policies"][0]["decision"] += " changed"
        with self.assertRaisesRegex(ProductAuthorityError, "stale product authority digest"):
            validate_product_authority(stale_payload)

        stale_record = deepcopy(self.authority)
        stale_record["product_records"][0]["purpose"] += " changed"
        stale_record["authority_digest"] = authority_digest(stale_record)
        with self.assertRaisesRegex(ProductAuthorityError, "stale record digest"):
            validate_product_authority(stale_record)

    def test_stale_nova_record_binding_fails_closed(self) -> None:
        contract = deepcopy(self.contracts["NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"])
        for field, value in (
            ("product_record_revision", "nova_praise-old"),
            ("product_record_digest", "0" * 64),
        ):
            changed = deepcopy(contract)
            changed["product_authority_binding"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ProductAuthorityError,
                "stale product record",
            ):
                validate_contract_product_authority_bindings(
                    self.authority,
                    {"nova": changed},
                )

    def test_selected_daily_generic_home_and_bliss_mutations_fail(self) -> None:
        contract = self.contracts["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]

        selected_daily = deepcopy(contract)
        selected_daily["scenarios"][0]["permitted_inputs"].append(
            "open selected Daily"
        )
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": selected_daily},
            )

        generic_home = deepcopy(contract)
        generic_home["product_authority_binding"]["home_authority"] = "Home"
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": generic_home},
            )

        generic_home_state = deepcopy(contract)
        generic_home_state["transition_contracts"][0]["from"] = "hOmE"
        with self.assertRaisesRegex(ProductAuthorityError, "generic Home state"):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": generic_home_state},
            )

        bliss = deepcopy(contract)
        bliss["product_authority_binding"]["platform"] = "bliss"
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": bliss},
            )

    def test_binding_requires_exact_native_profile_and_package(self) -> None:
        contract = self.contracts["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]

        extra_binding_id = deepcopy(contract)
        extra_binding_id["product_authority_binding"]["platform_binding_ids"].append(
            "arbitrary-binding-id"
        )
        with self.assertRaisesRegex(ProductAuthorityError, "exact BlueStacks binding set"):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": extra_binding_id},
            )

        for field in ("platform_profile_id", "package_id"):
            omitted = deepcopy(contract)
            omitted["product_authority_binding"].pop(field)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_contract_product_authority_bindings(
                    self.authority,
                    {"resource": omitted},
                )

    def test_generated_view_is_deterministic_and_detects_tamper(self) -> None:
        view = build_authority_view()
        supply = next(
            item
            for item in view["bound_flows"]
            if item["flow_id"] == "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        )
        supply_text = json.dumps(supply).casefold()
        self.assertNotIn("daily 5/5", supply_text)
        self.assertNotIn("collect", supply_text)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "authority-view.json"
            write_authority_view(output)
            first = output.read_text(encoding="utf-8")
            check_authority_view(output)
            write_authority_view(output)
            self.assertEqual(first, output.read_text(encoding="utf-8"))

            payload = json.loads(first)
            payload["bound_flows"][0]["flow_id"] = "tampered"
            output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AuthorityViewError, "stale or hand-edited"):
                check_authority_view(output)


if __name__ == "__main__":
    unittest.main()
