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

    def test_authority_is_v2_and_has_exactly_twenty_two_typed_records(self) -> None:
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
                "rare_earth_shop_purchase",
                "alliance_shop_purchase",
                "hero_upgrade",
                "hero_duel",
                "nanoweapon_normal_craft",
                "nano_material_production",
                "vip_points_popup_dismissal",
                "world_map_navigation",
            },
        )
        validate_product_authority(self.authority)

    def test_aggregate_daily_claim_is_the_only_selected_daily_owner(self) -> None:
        record = self.records["aggregate_daily_claim"]
        self.assertEqual(record["record_type"], "aggregate_daily_claim")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(record["semantic_entry_route"]["target"], "DAILY")
        self.assertTrue(record["target"]["selected_daily"])
        self.assertTrue(record["target"]["row_local"])
        self.assertFalse(record["target"]["milestone"])
        self.assertEqual(record["target"]["control"], "Claim")
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        self.assertTrue(record["semantic_effect"]["positive_points_delta_required"])
        self.assertTrue(record["semantic_effect"]["ordinary_claim_controls_cleared_required"])
        self.assertTrue(record["semantic_effect"]["dispatch_is_not_success_proof"])
        self.assertEqual(record["daily_ownership"]["daily_owner"], "aggregate_daily_claim")
        self.assertTrue(record["daily_ownership"]["selected_daily_prerequisite"])
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
            "rare_earth_shop_purchase",
            "alliance_shop_purchase",
            "hero_upgrade",
            "hero_duel",
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

    def test_alliance_shop_candidate_keeps_unknown_offer_fail_closed(self) -> None:
        record = self.records["alliance_shop_purchase"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "alliance-shop-purchase-policy"
        )
        self.assertEqual(policy["status"], "unresolved_user_decision")
        self.assertFalse(policy["purchase_dispatch_allowed"])
        self.assertEqual(record["record_type"], "alliance_shop_purchase")
        self.assertEqual(record["semantic_entry_route"]["route"], ["ALLIANCE_SHOP"])
        target = record["target"]
        self.assertEqual(target["candidate_item"], "unknown_current_alliance_shop_item")
        self.assertEqual(
            target["candidate_currency"],
            "unknown_current_joy_coin_or_alliance_coin",
        )
        self.assertIsNone(target["candidate_cost"])
        self.assertEqual(target["quantity"], 1)
        self.assertEqual(target["policy_status"], "unresolved_user_decision")
        self.assertFalse(target["purchase_dispatch_allowed"])
        cost = record["quantity_cost"]["cost"]
        self.assertIsNone(cost["amount"])
        self.assertEqual(cost["unit"], "UNKNOWN_CURRENT_JOY_COIN_OR_ALLIANCE_COIN")
        self.assertFalse(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_item_evidence_required"])
        self.assertTrue(effect["exact_currency_evidence_required"])
        self.assertTrue(effect["exact_cost_evidence_required"])
        self.assertTrue(effect["balance_evidence_required"])
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
            "currency spend",
            "insufficient balance",
        ):
            self.assertIn(marker, forbidden)

    def test_hero_upgrade_candidate_keeps_unknown_material_fail_closed(self) -> None:
        record = self.records["hero_upgrade"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "hero-upgrade-policy"
        )
        self.assertEqual(policy["status"], "prohibited")
        self.assertFalse(policy["upgrade_dispatch_allowed"])
        self.assertEqual(record["record_type"], "hero_upgrade")
        self.assertEqual(record["semantic_entry_route"]["route"], ["HERO"])
        target = record["target"]
        self.assertEqual(target["hero_identity"], "unknown_current_wally")
        self.assertIsNone(target["current_level"])
        self.assertIsNone(target["target_level"])
        self.assertEqual(target["candidate_material"], "unknown_current_hero_material")
        self.assertIsNone(target["candidate_amount"])
        self.assertIsNone(target["candidate_balance"])
        self.assertEqual(target["daily_completion_target"], 3)
        self.assertFalse(target["upgrade_dispatch_allowed"])
        cost = record["quantity_cost"]["cost"]
        self.assertIsNone(cost["amount"])
        self.assertEqual(cost["unit"], "UNKNOWN_HERO_MATERIAL")
        self.assertFalse(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_hero_evidence_required"])
        self.assertTrue(effect["exact_level_evidence_required"])
        self.assertTrue(effect["exact_material_evidence_required"])
        self.assertTrue(effect["level_successor_required"])
        self.assertTrue(effect["daily_progress_successor_required"])
        self.assertFalse(effect["upgrade_dispatch_allowed"])
        self.assertTrue(effect["canonical_home_successor_required"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "upgrade",
            "material spend",
            "unknown hero",
            "unknown material",
            "unknown cost",
            "insufficient material balance",
        ):
            self.assertIn(marker, forbidden)

    def test_hero_duel_candidate_keeps_pvp_fail_closed(self) -> None:
        record = self.records["hero_duel"]
        policy = next(
            item
            for item in self.authority["policies"]
            if item["policy_id"] == "hero-duel-policy"
        )
        self.assertEqual(policy["status"], "prohibited")
        self.assertFalse(policy["pvp_entry_allowed"])
        self.assertEqual(record["record_type"], "hero_duel")
        self.assertEqual(record["semantic_entry_route"]["route"], ["HERO_DUEL"])
        target = record["target"]
        self.assertEqual(target["event_identity"], "unknown_current_hero_duel_event")
        self.assertIsNone(target["event_active"])
        self.assertEqual(target["target_identity"], "HERO_DUEL_JOIN")
        self.assertIsNone(target["candidate_attempts_remaining"])
        self.assertEqual(target["daily_completion_target"], 3)
        self.assertFalse(target["pvp_entry_allowed"])
        cost = record["quantity_cost"]["cost"]
        self.assertIsNone(cost["amount"])
        self.assertEqual(cost["unit"], "NO_PVP_RESOURCE_SPEND")
        self.assertFalse(cost["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_event_evidence_required"])
        self.assertTrue(effect["free_opponent_evidence_required"])
        self.assertTrue(effect["join_control_evidence_required"])
        self.assertTrue(effect["participation_successor_required"])
        self.assertFalse(effect["pvp_entry_allowed"])
        self.assertFalse(effect["combat_dispatch_allowed"])
        self.assertFalse(effect["lineup_change_allowed"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in (
            "join",
            "pvp entry",
            "combat dispatch",
            "lineup change",
            "unknown event",
            "unknown opponent",
            "insufficient attempts",
        ):
            self.assertIn(marker, forbidden)

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
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("normal craft", "exclusive craft", "resource box", "multiple active"):
            self.assertIn(marker, forbidden)
    def test_nanoweapon_product_is_one_exact_normal_craft_per_reset(self) -> None:
        record = self.records["nanoweapon_normal_craft"]
        self.assertEqual(record["record_type"], "nanoweapon_normal_craft")
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
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 100)
        self.assertEqual(record["quantity_cost"]["cost"]["unit"], "NANO_PARTS")
        self.assertFalse(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["exact_parts_consumption_required"])
        self.assertTrue(effect["single_start_per_reset_required"])
        self.assertTrue(effect["exact_duration_required"])
        self.assertTrue(effect["daily_objective_successor_required"])
        self.assertFalse(effect["identical_retry"])
        self.assertIsNone(record["daily_ownership"]["daily_owner"])
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("material production", "exclusive craft", "second craft", "currency"):
            self.assertIn(marker, forbidden)


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
        self.assertEqual(record["record_revision"], "gathering_resources-v1")
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
        self.assertTrue(target["source_daily_row_required"])
        self.assertEqual(target["food_authority"], "forbidden")
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        self.assertEqual(record["semantic_effect"]["resource_progress_successor_required"], True)
        self.assertFalse(record["semantic_effect"]["identical_retry"])
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
        self.assertEqual(record["record_revision"], "troop_training-v1")
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

    def test_aggregate_claim_requires_non_claimable_negative(self) -> None:
        record = self.records["aggregate_daily_claim"]
        forbidden = {str(item).casefold() for item in record["forbidden_actions"]}
        self.assertIn("non-claimable claim row", forbidden)

        changed = deepcopy(self.authority)
        daily = next(
            item
            for item in changed["product_records"]
            if item["record_id"] == "aggregate_daily_claim"
        )
        daily["forbidden_actions"].remove("non-claimable Claim row")
        daily["record_digest"] = record_digest(daily)
        changed["authority_digest"] = authority_digest(changed)
        with self.assertRaisesRegex(ProductAuthorityError, "must forbid non-claimable"):
            validate_product_authority(changed)

    def test_activity_milestone_product_is_one_free_ready_chest_and_not_ordinary_claim_owned(self) -> None:
        record = self.records["activity_milestone_claim"]
        self.assertEqual(record["record_type"], "activity_milestone_claim")
        self.assertEqual(record["recurrence"], "daily_reset_scoped")
        self.assertEqual(record["semantic_entry_route"]["target"], "QUEST")
        self.assertEqual(
            record["semantic_entry_route"]["route"],
            ["QUEST", "ACTIVITY_MILESTONES"],
        )
        target = record["target"]
        self.assertEqual(target["kind"], "activity_milestone_chest")
        self.assertEqual(target["control"], "MILESTONE_CHEST")
        self.assertTrue(target["fully_visible"])
        self.assertTrue(target["reset_bound"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        effect = record["semantic_effect"]
        self.assertTrue(effect["same_milestone_successor_required"])
        self.assertTrue(effect["positive_bound_points_successor_allowed"])
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
        ):
            self.assertIn(marker, forbidden)
        self.assertEqual(record["terminal_requirement"]["home_authority"], "HOME_CANONICAL")

    def test_activity_milestone_safety_fields_fail_closed_with_fresh_digests(self) -> None:
        mutations = (
            ("ready", lambda record: record["target"].__setitem__("eligibility", "already_claimed")),
            ("free_only", lambda record: record["quantity_cost"]["cost"].__setitem__("free_only", False)),
            ("successor", lambda record: record["semantic_effect"].__setitem__("same_milestone_successor_required", False)),
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

    def test_resource_semantics_are_direct_owned_one_item(self) -> None:
        record = self.records["use_resource_item"]
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
        self.assertFalse(record["quantity_cost"]["cost"]["free_only"])
        self.assertEqual(record["semantic_effect"]["effect_ordinal"], 1)
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

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

    def test_daily_claim_contract_binds_aggregate_record_and_preserves_disabled_state(self) -> None:
        contract = self.contracts["DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "aggregate_daily_claim")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_revision"], "aggregate_daily_claim-v1")
        self.assertEqual(binding["home_authority"], "HOME_READY")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")
        self.assertEqual(contract["product_policy_refs"][0]["policy_id"], "aggregate-daily-claim")
        self.assertEqual(contract["replay_fixture_proof_state"], "evidence_required")
        self.assertIn(
            "composite",
            " ".join(contract["evidence_requirements"]).casefold(),
        )

    def test_nova_praise_contract_binds_direct_record_and_preserves_disabled_state(self) -> None:
        contract = self.contracts["NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "nova_praise")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_revision"], "nova_praise-v1")
        self.assertEqual(binding["home_authority"], "HOME_LOCALIZED")
        self.assertEqual(binding["terminal_home_authority"], "HOME_CANONICAL")
        self.assertFalse(contract["production_eligible"])
        self.assertEqual(contract["registration_state"], "disabled")

    def test_ultimate_contract_binds_direct_record_and_retains_composite_proof(self) -> None:
        contract = self.contracts["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]
        binding = contract["product_authority_binding"]
        self.assertEqual(binding["product_record_id"], "ultimate_challenge")
        self.assertEqual(binding["product_authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(binding["product_record_revision"], "ultimate_challenge-v1")
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
