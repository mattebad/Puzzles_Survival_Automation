from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID as DONATION,
    ALLIANCE_DONATION_PRODUCT_ID as DONATION_PRODUCT,
    ALLIANCE_DONATION_PRODUCT_REVISION as DONATION_REVISION,
    ALLIANCE_HELP_FLOW_ID as HELP,
    ALLIANCE_HELP_PRODUCT_ID as HELP_PRODUCT,
    ALLIANCE_HELP_PRODUCT_REVISION as HELP_REVISION,
    ALLIANCE_SHOP_FLOW_ID as ALLIANCE_SHOP,
    ALLIANCE_SHOP_PRODUCT_REVISION as ALLIANCE_SHOP_REVISION,
    DAILY_SHOPS_FLOW_ID as DAILY_SHOPS,
    DAILY_SHOPS_PRODUCT_REVISION as DAILY_SHOPS_REVISION,
    FOOD_FARM_BOOST_FLOW_ID as FOOD_FARM,
    FOOD_FARM_BOOST_PRODUCT_ID as FARM_PRODUCT,
    FOOD_FARM_BOOST_PRODUCT_REVISION as FARM_REVISION,
    HERO_DUEL_FLOW_ID as HERO_DUEL,
    HERO_DUEL_PRODUCT_ID as HERO_PRODUCT,
    HERO_DUEL_PRODUCT_REVISION as HERO_REVISION,
    NANO_MATERIAL_PRODUCTION_FLOW_ID as NANO_PRODUCTION,
    NANO_MATERIAL_PRODUCTION_PRODUCT_ID as NANO_PRODUCTION_PRODUCT,
    NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION as NANO_PRODUCTION_REVISION,
    NANOWEAPON_FLOW_ID as NANOWEAPON,
    RECOMMENDED_RESEARCH_FLOW_ID as RESEARCH,
    NANOWEAPON_PRODUCT_ID as NANOWEAPON_PRODUCT,
    NANOWEAPON_PRODUCT_REVISION as NANOWEAPON_REVISION,
    RUINS_FLOW_ID as RUINS,
    RECOMMENDED_RESEARCH_PRODUCT_ID as RESEARCH_PRODUCT,
    RECOMMENDED_RESEARCH_PRODUCT_REVISION as RESEARCH_REVISION,
    RUINS_PRODUCT_ID as RUINS_PRODUCT,
    RUINS_PRODUCT_REVISION as RUINS_REVISION,
)
from safe_action_core.models import ActionClass, PolicyDecision
from safe_action_core.policy import CentralPolicy
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tests.support.safe_action import TEST_TASK_ID, observation, request as base_request


DAY = "game-day-2026-07-15"
FRAME = "a" * 64
OTHER_TASK = "OTHER-SUPERVISED-TASK"

POLICY = CentralPolicy(
    {
        DONATION, ALLIANCE_SHOP, DAILY_SHOPS, NANO_PRODUCTION, NANOWEAPON,
        RESEARCH, HELP, RUINS_PRODUCT, HERO_DUEL, FOOD_FARM,
        TEST_TASK_ID, OTHER_TASK,
    }
)


def route_request(
    *,
    task: str,
    action: str,
    action_class: ActionClass,
    kind: str,
    subject: str | None,
    source: str,
    target: str,
    control: str,
    consequence: str,
    post: str,
    cost_type: str,
    cost: int,
    quantity: int,
    resource: str | None,
    maximum: int | None,
    free: bool,
    preconditions: tuple[str, ...],
    action_key: str | None = None,
    roi_hashes: tuple[tuple[str, str], ...] = (),
    game_day: str = DAY,
):
    obs = observation(
        frame_sha256=FRAME,
        capture_completed_monotonic=999.5,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=source,
        overlay_state="none_observed",
        target_identity=target,
        target_roi=(100, 100, 300, 200),
        recognized=True,
        control_class=control,
        consequence=consequence,
        cost_type=cost_type,
        cost_amount=cost,
        quantity=quantity,
        expected_postcondition=post,
        target_isolated=True,
        critical_roi_hashes=roi_hashes,
    )
    return base_request(
        obs,
        action_id="route-action",
        action_key=action_key or f"route:{action}:1",
        task_id=task,
        task_mode="supervised_validation",
        semantic_action=action,
        expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="policy-test-controller",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        game_day_id=game_day,
        action_class=action_class,
        action_kind=kind,
        subject=subject,
        resource_or_currency=resource,
        maximum_cost=maximum,
        free_only=free,
        semantic_preconditions=preconditions,
        semantic_postconditions=(post,),
    )

def navigation_request():
    return route_request(
        task=TRAINING, action="HOME_ATLAS_CAMERA_PAN", action_class=ActionClass.NAVIGATION_ONLY,
        kind="navigation", subject=None, source="HOME_BASE", target="home.atlas.camera-pan",
        control="GO", consequence="navigate_zero_cost", post="HOME_ATLAS_CAMERA_PAN_PROGRESS",
        cost_type="none", cost=0, quantity=1, resource=None, maximum=0, free=True,
        preconditions=(), action_key="home-atlas-camera-pan:frame-bound-1",
    )


def donation_request():
    cost = 25
    tokens = (
        f"alliance_donation_product={DONATION_PRODUCT}",
        f"alliance_donation_product_revision={DONATION_REVISION}",
        f"alliance_donation_game_day={DAY}",
        "alliance_donation_hot_marker=true",
        "alliance_donation_target=tech_alpha",
        "alliance_donation_attempts=1/20",
        "alliance_donation_balance=100",
        "alliance_donation_resource=FOOD",
        f"alliance_donation_cost={cost}",
        "alliance_donation_quantity=1",
        "alliance_donation_single_tap=true",
        "alliance_donation_no_premium=true",
        "alliance_donation_no_refill=true",
        "alliance_donation_no_hold=true",
        "alliance_donation_daily_action_count=0",
    )
    return route_request(
        task=DONATION, action="DONATE_ALLIANCE_TECH", action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind=DONATION_REVISION, subject="tech_alpha", source="ALLIANCE_TECH_DONATION_PANEL",
        target="alliance-tech:ordinary-donate", control="DONATE", consequence="alliance_tech_donation_effect",
        post="ALLIANCE_TECH_DONATION_CONFIRMED", cost_type="ordinary_resource", cost=cost, quantity=1,
        resource="FOOD", maximum=cost, free=False, preconditions=tokens,
    )


def alliance_shop_request(item="joy_coin", shop="weekly_offers", currency="ALLIANCE_COINS", price=12, balance=80, quantity=1):
    stock = 3
    total = price * quantity
    tokens = (
        f"shop={shop}", f"item={item}", f"currency={currency}", f"unit_price={price}",
        f"stock={stock}", f"balance={balance}", f"quantity={quantity}", f"total={total}",
        f"alliance_shop_reset_id={DAY}", "alliance_shop_action_ordinal=1",
        "alliance_shop_action_count_before=0", "alliance_shop_action_limit=1",
    )
    source = "ALLIANCE_SHOP_WEEKLY_QUANTITY_DIALOG" if shop == "weekly_offers" else "ALLIANCE_SHOP_OTHER_QUANTITY_DIALOG"
    return route_request(
        task=ALLIANCE_SHOP, action="PURCHASE_ALLIANCE_SHOP_OFFER", action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind=ALLIANCE_SHOP_REVISION, subject=item, source=source, target="alliance-shop:inner-buy",
        control="BUY", consequence="alliance_shop_purchase", post="ALLIANCE_SHOP_PURCHASE_RECONCILED",
        cost_type="ALLIANCE_COINS", cost=total, quantity=quantity, resource=currency, maximum=total,
        free=False, preconditions=tokens,
    )


def daily_shop_request(item="3_star_chip_enhance_material", shop="ruins_shop", currency="RUINS_COINS", price=4, stock=8, balance=21, quantity=5):
    total = price * quantity
    rare = item == "3_star_module_enhance_material"
    source = "RARE_EARTH_SHOP_QUANTITY_DIALOG" if rare else "RUINS_SHOP_QUANTITY_DIALOG"
    target = "daily-shops:rare-earth:inner-buy" if rare else "daily-shops:ruins:inner-buy"
    post = "RARE_EARTH_SHOP_PURCHASE_RECONCILED" if rare else "RUINS_SHOP_PURCHASE_RECONCILED"
    tokens = (
        f"shop={shop}", f"item={item}", "rarity=3", f"currency={currency}",
        f"unit_price={price}", f"stock={stock}", f"balance={balance}",
        f"quantity={quantity}", f"total={total}", f"daily_shops_reset_id={DAY}",
        f"daily_shops_tab={shop}", "daily_shops_tab_action_ordinal=1",
        "daily_shops_tab_action_count_before=0", "daily_shops_tab_action_limit=1",
    )
    return route_request(
        task=DAILY_SHOPS, action="PURCHASE_DAILY_SHOP_MATERIAL", action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind=DAILY_SHOPS_REVISION, subject=item, source=source, target=target, control="BUY",
        consequence="daily_shops_purchase", post=post, cost_type=currency, cost=total,
        quantity=quantity, resource=currency, maximum=total, free=False, preconditions=tokens,
    )


def nano_request(action, occurrence=f"{NANO_PRODUCTION}:{DAY}:1"):
    if action == "claim_nano_material_production":
        tokens = (
            f"product_id={NANO_PRODUCTION_PRODUCT}", f"product_revision={NANO_PRODUCTION_REVISION}",
            "effect_ordinal=1", f"native_occurrence_key={occurrence}", "native_action_key_binds_occurrence=true",
            "material_production_tab", "production_state=complete", "active_production_count=0",
            "completed_batch_count=1", "cost=none:0", "zero_resource_claim",
        )
        source, target, control, consequence, post, subject = (
            "NANOWEAPON", "nano-material-production-claim", "CLAIM", "nano_material_production_claim",
            "NANO_MATERIAL_PRODUCTION_CLAIMED", "nano-material-production-claim",
        )
        action_class, kind, cost_type, cost, quantity, resource, maximum, free = (
            ActionClass.ZERO_COST_CONSEQUENTIAL, "CLAIM_NANO_MATERIAL_PRODUCTION", "none", 0, 1, None, 0, True,
        )
        key = f"{NANO_PRODUCTION_PRODUCT}|{occurrence}|claim"
    else:
        tokens = (
            f"product_id={NANO_PRODUCTION_PRODUCT}", f"product_revision={NANO_PRODUCTION_REVISION}",
            "effect_ordinal=1", f"native_occurrence_key={occurrence}", "native_action_key_binds_occurrence=true",
            "material_production_tab", "production_state=idle", "active_production_count=0",
            "duration_seconds=21600", "cost=none:0", "production_start_ordinal=1",
        )
        source, target, control, consequence, post, subject = (
            "NANOWEAPON", "nano-material-production-start", "PRODUCE", "nano_material_production_start",
            "NANO_MATERIAL_PRODUCTION_ACTIVE_21600", "nano-material-production-start",
        )
        action_class, kind, cost_type, cost, quantity, resource, maximum, free = (
            ActionClass.ZERO_COST_CONSEQUENTIAL, "START_NANO_MATERIAL_PRODUCTION", "none", 0, 1, None, 0, True,
        )
        key = f"{NANO_PRODUCTION_PRODUCT}|{occurrence}|start"
    return route_request(
        task=NANO_PRODUCTION, action=action, action_class=action_class, kind=kind, subject=subject,
        source=source, target=target, control=control, consequence=consequence, post=post,
        cost_type=cost_type, cost=cost, quantity=quantity, resource=resource, maximum=maximum,
        free=free, preconditions=tokens, action_key=key,
    )


def craft_claim_request():
    tokens = (
        f"product_id={NANOWEAPON_PRODUCT}", f"product_revision={NANOWEAPON_REVISION}",
        "effect_ordinal=1", f"game_day_id={DAY}", "prior_material_production_reconciled=1",
        "normal_craft_tab", "completed_normal_craft=1", "active_craft_count=0", "claim_visible=1", "cost=none:0",
    )
    return route_request(
        task=NANOWEAPON, action="claim_completed_nanoweapon", action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind="CLAIM_NANOWEAPON_COMPLETED", subject="nanoweapon-completed-claim", source="NANOWEAPON",
        target="nanoweapon-completed-claim", control="CLAIM", consequence="nanoweapon_completed_claim",
        post="NANOWEAPON_CRAFT_CLAIMED", cost_type="none", cost=0, quantity=1, resource=None,
        maximum=0, free=True, preconditions=tokens,
    )


def craft_start_request():
    tokens = (
        f"product_id={NANOWEAPON_PRODUCT}", f"product_revision={NANOWEAPON_REVISION}",
        "effect_ordinal=1", "prior_material_production_reconciled=1", "normal_craft_tab",
        "recipe_selection=normal", f"game_day_id={DAY}", "nano_parts_balance=130",
        "cost=NANO_PARTS:100", "duration_seconds=43200", "active_craft_count=0",
        "current_reset_start_ordinal=1", "exclusive_craft=0", "rotating_display=0",
    )
    return route_request(
        task=NANOWEAPON, action="start_one_normal_nanoweapon_craft", action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind="START_NORMAL_NANOWEAPON_CRAFT", subject="nanoweapon-craft-normal", source="NANOWEAPON",
        target="nanoweapon-craft-normal", control="CRAFT", consequence="nanoweapon_normal_craft",
        post="NANOWEAPON_NORMAL_CRAFT_ACTIVE", cost_type="NANO_PARTS", cost=100, quantity=1,
        resource="NANO_PARTS", maximum=100, free=False, preconditions=tokens,
    )


def research_request():
    tokens = (
        f"product_id={RESEARCH_PRODUCT}", f"product_revision={RESEARCH_REVISION}",
        f"recommended_research_reset={DAY}", "recommended_research_start_ordinal=1",
        "recommended_research_start_count_before=0", "first_displayed_recommendation_identity=research_alpha",
        "recommendation_position=1", "queue1_state=idle", "queue2_activate_tapped=false",
        "prerequisites_known=true", "prerequisites_met=true", "prerequisite_evidence=research_alpha",
        "food_cost=100", "food_balance=500", "wood_cost=0", "wood_balance=200",
        "steel_cost=25", "steel_balance=100", "gas_cost=0", "gas_balance=50",
        "cost_source=detail_panel_scrolled_complete", "affordable=true", "premium_cost_excluded=true",
        "research_now_diamonds_excluded=true",
    )
    return route_request(
        task=RESEARCH, action="START_RECOMMENDED_RESEARCH", action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind="research_start", subject="research_alpha", source="RESEARCH_DETAIL",
        target="recommended-research:research_alpha:detail-research-button", control="RESEARCH_START",
        consequence="start_ordinary_recommended_research", post="RESEARCH_ACTIVE_WITH_TIMER_AND_MATCHED_RESOURCE_DEBIT",
        cost_type="ordinary_resource_bundle", cost=1, quantity=1, resource="food+wood+steel+gas",
        maximum=None, free=False, preconditions=tokens,
    )


def ruins_challenge_request():
    tokens = (
        f"ruins_product={RUINS_PRODUCT}", f"ruins_product_revision={RUINS_REVISION}",
        f"ruins_flow={RUINS}", "ruins_account_id=account_a", "ruins_server_id=server_a",
        f"ruins_reset_id={DAY}", "ruins_game_day=Tue", "ruins_category=challenge",
        "ruins_challenge_identity=hero-challenge", "ruins_challenge_day=Tue",
        "ruins_challenge_availability=available", "ruins_challenge_control=visible_enabled",
        "ruins_cost_type=none", "ruins_cost_amount=0", "ruins_premium=false", "ruins_paid=false",
        "ruins_ticketed=false", "ruins_npc_troops=provided", "ruins_npc_troops_current=100",
        "ruins_npc_troops_maximum=100", "ruins_skip_battle=true", "ruins_dispatch_count_before=0",
        "ruins_dispatch_count_limit=1",
    )
    return route_request(
        task=RUINS_PRODUCT, action="ruins_zero_cost_npc_challenge_dispatch", action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind="ruins_zero_cost_npc_challenge_dispatch", subject="ruins_challenge:hero-challenge",
        source="RUINS_CHALLENGE_DETAIL", target="ruins-dispatch", control="DISPATCH",
        consequence="ruins_zero_cost_npc_challenge", post="RUINS_CHALLENGE_RESULT_RECOGNIZED",
        cost_type="none", cost=0, quantity=1, resource=None, maximum=0, free=True, preconditions=tokens,
    )


def ruins_chest_request():
    tokens = (
        f"ruins_product={RUINS_PRODUCT}", f"ruins_product_revision={RUINS_REVISION}",
        f"ruins_flow={RUINS}", "ruins_account_id=account_a", "ruins_server_id=server_a",
        f"ruins_reset_id={DAY}", "ruins_game_day=Tue", "ruins_category=chest",
        "ruins_chest_identity=hero-challenge", "ruins_chest_state=green_ready",
        "ruins_chest_fully_visible=true", "ruins_claim_control=visible_enabled",
        "ruins_reward_identity=hero-challenge", "ruins_reward_medals=10", "ruins_cost_type=none",
        "ruins_cost_amount=0", "ruins_premium=false", "ruins_exchange=false", "ruins_shop=false",
        "ruins_claim_count_before=0", "ruins_claim_count_limit=1",
    )
    return route_request(
        task=RUINS_PRODUCT, action="ruins_green_ready_stage_chest_claim", action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind="ruins_green_ready_stage_chest_claim", subject="ruins_stage_chest:hero-challenge",
        source="RUINS_REWARD_MODAL", target="ruins-reward-claim", control="CLAIM",
        consequence="ruins_zero_cost_ready_chest_reward", post="RUINS_STAGE_CHEST_CLAIMED",
        cost_type="none", cost=0, quantity=1, resource=None, maximum=0, free=True, preconditions=tokens,
    )


def hero_request(action):
    event = "survival_event_01"
    prefix = (f"hero_duel_product={HERO_PRODUCT}", f"hero_duel_product_revision={HERO_REVISION}", f"hero_duel_event_identity={event}")
    if action == "hero_duel_free_entry":
        tokens = prefix + (
            "hero_duel_free_allowance_before=3", "hero_duel_pass_balance_before=0",
            "hero_duel_entry_ordinal=1", f"hero_duel_entry_reset={DAY}",
            "current_event_is_hero_duel_survival", "event_active", "emergency_details_exclusions_inspected",
            "defense_first_five_eligible_saved", "attack_five_eligible_slots_populated",
            "listed_opponent_free_selected", "entry_cost_exactly_zero", "premium_prompt_absent", "overlay_absent",
        )
        source, target, control, consequence, post = (
            "hero_duel_attack_formation", "hero-duel-attack-challenge", "FREE_CHALLENGE",
            "bounded_hero_duel_participation", "hero_duel_battle_loaded",
        )
    elif action == "hero_duel_flee":
        tokens = prefix + (
            "hero_duel_free_allowance_at_flee=2", "hero_duel_pass_balance_before=0",
            "hero_duel_entry_ordinal=1", f"hero_duel_entry_reset={DAY}",
            "current_event_is_hero_duel_survival", "entry_same_cycle_ordinal_confirmed", "current_battle_loaded",
            "battle_exit_control_bound", "flee_warning_visible", "flee_button_bound", "fight_control_excluded",
            "premium_prompt_absent", "overlay_absent",
        )
        source, target, control, consequence, post = (
            "hero_duel_flee_warning", "hero-duel-warning-flee", "FLEE", "accept_hero_duel_loss", "hero_duel_loss_result",
        )
    else:
        tokens = prefix + (
            "current_event_is_hero_duel_survival", "event_active", "emergency_details_exclusions_inspected",
            "first_five_eligible_heroes_bound", "five_defense_slots_exact", "prohibited_support_absent", "overlay_absent",
        )
        source, target, control, consequence, post = (
            "hero_duel_defense_formation", "hero-duel-defense-save-form", "SAVE_FORM",
            "set_hero_duel_defense", "hero_duel_lineup_saved",
        )
    return route_request(
        task=HERO_DUEL, action=action, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind=action, subject=None, source=source, target=target, control=control, consequence=consequence,
        post=post, cost_type="none", cost=0, quantity=1, resource="none", maximum=0, free=True,
        preconditions=tokens,
    )






def help_request(all=False):
    if all:
        request_ids = ["a" * 24, "b" * 24]
        request_ids_json = json.dumps(request_ids, ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(request_ids_json.encode("utf-8")).hexdigest()
        tokens = (
            f"alliance_help_product={HELP_PRODUCT}", f"alliance_help_product_revision={HELP_REVISION}",
            f"alliance_help_request_reset={DAY}", "alliance_help_request_ordinal=1", "alliance_help_request_count=2",
            "alliance_help_quota=10", "alliance_help_target_variant=help_all", "alliance_help_exact_free_label=Help_All",
            f"alliance_help_request_ids_json={request_ids_json}", "alliance_help_request_list_complete=true",
            f"alliance_help_request_set_sha256={digest}", "alliance_help_complete_request_transition_required",
        )
        target, control, subject, quantity = "alliance-help-all", "FREE_HELP_ALL", "alliance-help-all", 2
    else:
        tokens = (
            f"alliance_help_product={HELP_PRODUCT}", f"alliance_help_product_revision={HELP_REVISION}",
            "alliance_help_quota=10", f"alliance_help_request_reset={DAY}", "alliance_help_request_ordinal=1",
            "alliance_help_target_variant=individual", "alliance_help_exact_free_label=Help",
            "alliance_help_complete_request_transition_required",
        )
        target, control, subject, quantity = "alliance-help-individual-request", "FREE_HELP", "alliance-help-individual-request", 1
    return route_request(
        task=HELP, action="HELP_ALLIANCE_REQUEST", action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind="HELP_ALLIANCE_REQUEST", subject=subject, source="SPEEDUP_HELP", target=target, control=control,
        consequence="alliance_help_zero_cost", post="ALLIANCE_HELP_REQUEST_RESULT", cost_type="none", cost=0,
        quantity=quantity, resource=None, maximum=0, free=True, preconditions=tokens,
    )


def farm_collection_request():
    farm = "home.building.farm.01"
    key = f"food-farm-output-boost:occurrence:collection:{'9' * 64}"
    tokens = (
        f"product_id:{FARM_PRODUCT}", f"product_revision:{FARM_REVISION}",
        f"reset_identity:{DAY}", "effect_ordinal:collection=1", f"current_clean_home_atlas_binding:{farm}",
        "current_collection_balance_before:food=100,wood=200,steel=300,gas=400",
        f"canonical_collection_action_key_unclaimed:{key}", "current_runtime_lease_valid",
    )
    return route_request(
        task=FOOD_FARM, action="collect_food_farm_resources", action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        kind="collect_food_farm_resources", subject=farm, source="HOME_BASE", target=farm, control="COLLECT",
        consequence="collect_all_base_resource_building_output", post="FOOD_FARM_COLLECTION_RECONCILED",
        cost_type="none", cost=0, quantity=1, resource="none", maximum=0, free=True,
        preconditions=tokens, action_key=key,
    )


def farm_boost_request(diamonds=False):
    farm = "home.building.farm.01"
    item = "unproven_boost_product"
    key = f"food-farm-output-boost:daily:boost:{'8' * 64}"
    common = (
        f"product_id:{FARM_PRODUCT}", f"product_revision:{FARM_REVISION}",
        f"reset_identity:{DAY}", "effect_ordinal:boost=1", f"current_clean_home_atlas_binding:{farm}",
        f"same_farm_identity_after_collection:{farm}", "current_food_farm_boost_panel", "boost_inactive",
        f"exact_owned_item_name:{item}",
    )
    if diamonds:
        tokens = common + (
            "owned_inventory_count=0", f"exact_current_diamond_offer_item:{item}",
            "diamond_offer_duration_seconds=86400", "diamond_offer_price=50", "current_diamond_balance=100",
            "current_offer_action_or_confirmation:direct", f"canonical_food_farm_boost_action_key_unclaimed:{key}",
            "current_runtime_lease_valid",
        )
        cost_type, cost, resource, maximum, consequence, action = (
            "diamonds", 50, "diamonds", 50, "spend_exact_diamonds_for_one_food_farm_output_boost",
            "buy_food_farm_output_boost_diamonds",
        )
    else:
        tokens = common + (
            "owned_inventory_count>=1:2", "panel_item_action_cost=1", "boost_duration_seconds=86400",
            f"canonical_food_farm_boost_action_key_unclaimed:{key}", "current_runtime_lease_valid",
        )
        cost_type, cost, resource, maximum, consequence, action = (
            "owned_item", 1, item, 1, "consume_one_exact_named_owned_food_farm_output_boost_item",
            "apply_food_farm_output_boost_owned_item",
        )
    return route_request(
        task=FOOD_FARM, action=action, action_class=ActionClass.SPEND_OR_STRATEGIC,
        kind=action, subject=item, source="FOOD_FARM_BOOST_PANEL", target=farm, control="BOOST",
        consequence=consequence, post="FOOD_FARM_POSITIVE_BOOSTING_TIMER", cost_type=cost_type,
        cost=cost, quantity=1, resource=resource, maximum=maximum, free=False, preconditions=tokens,
        action_key=key,
    )






class ApprovedBaseRoutePolicyTests(unittest.TestCase):
    def assert_authorized(self, req):
        result = POLICY.evaluate(req)
        self.assertEqual(result.decision, PolicyDecision.AUTHORIZE, result.reason_code)

    def assert_denied(self, req):
        self.assertEqual(POLICY.evaluate(req).decision, PolicyDecision.DENY)

    def test_alliance_donation_requires_exact_ordinary_resource_tuple(self):
        req = donation_request()
        self.assert_authorized(req)
        tokens = list(req.semantic_preconditions)
        tokens[1] = "alliance_donation_product_revision=alliance_donation-v2"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        self.assert_denied(replace(req, resource_or_currency="DIAMONDS"))
        self.assert_denied(replace(req, observation=replace(req.observation, cost_amount=26), maximum_cost=26))
        self.assert_denied(replace(req, task_id=OTHER_TASK))
        self.assert_denied(replace(req, semantic_action="PURCHASE_ALLIANCE_SHOP_OFFER"))
        tokens = list(req.semantic_preconditions)
        tokens[11] = "alliance_donation_no_premium=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))

    def test_alliance_shop_allowlist_currency_and_quantity_are_exact(self):
        for item, shop in (
            ("joy_coin", "weekly_offers"), ("timed_recruit_coin", "weekly_offers"),
            ("bioenhance_scheme", "weekly_offers"), ("one_star_gear_enhance_material", "other"),
        ):
            with self.subTest(item=item):
                self.assert_authorized(alliance_shop_request(item=item, shop=shop))
        req = alliance_shop_request()
        self.assert_denied(replace(req, subject="premium_pack"))
        self.assert_denied(replace(req, resource_or_currency="DIAMONDS"))
        self.assert_denied(replace(req, observation=replace(req.observation, cost_amount=13), maximum_cost=13))
        tokens = list(req.semantic_preconditions)
        tokens[2] = "currency=DIAMONDS"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[6] = "quantity=2"
        tokens[7] = "total=24"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[1] = "item=unknown_item"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))

    def test_daily_shop_quantity_is_exact_affordable_stock_maximum(self):
        self.assert_authorized(daily_shop_request())
        self.assert_authorized(daily_shop_request(
            item="3_star_module_enhance_material", shop="rare_earth_shop", currency="RARE_EARTH",
            price=7, stock=4, balance=35, quantity=4,
        ))
        req = daily_shop_request()
        tokens = list(req.semantic_preconditions)
        tokens[7] = "quantity=4"
        tokens[8] = "total=16"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens),
                                  observation=replace(req.observation, quantity=4, cost_amount=16), maximum_cost=16))
        self.assert_denied(replace(req, resource_or_currency="DIAMONDS"))
        tokens = list(req.semantic_preconditions)
        tokens[3] = "currency=DIAMONDS"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        self.assert_denied(replace(req, subject="premium_pack"))

    def test_nanoweapon_claims_and_exact_production_and_craft_effects(self):
        self.assert_authorized(nano_request("claim_nano_material_production"))
        self.assert_authorized(nano_request("start_nano_material_production"))
        self.assert_authorized(craft_claim_request())
        self.assert_authorized(craft_start_request())
        req = nano_request("start_nano_material_production")
        tokens = list(req.semantic_preconditions)
        tokens[8] = "duration_seconds=21601"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        self.assert_denied(replace(req, action_key=f"{NANO_PRODUCTION_PRODUCT}|{NANO_PRODUCTION}:{DAY}:2|start"))
        opaque_occurrence = f"{NANO_PRODUCTION}:{DAY}:1|opaque_basis"
        opaque_req = nano_request("start_nano_material_production", occurrence=opaque_occurrence)
        self.assert_authorized(opaque_req)
        self.assert_denied(replace(
            opaque_req,
            action_key=f"{NANO_PRODUCTION_PRODUCT}|{NANO_PRODUCTION}:{DAY}:1|other_basis|start",
        ))
        req = craft_start_request()
        self.assert_denied(replace(req, resource_or_currency="DIAMONDS"))
        self.assert_denied(replace(req, observation=replace(req.observation, cost_amount=101), maximum_cost=101))
        tokens = list(req.semantic_preconditions)
        tokens[8] = "cost=NANO_PARTS:101"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))

    def test_recommended_research_only_first_idle_queue_ordinary_affordable_case(self):
        req = research_request()
        self.assert_authorized(req)
        tokens = list(req.semantic_preconditions)
        tokens[7] = "queue1_state=active"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[8] = "queue2_activate_tapped=true"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[13] = "food_balance=99"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[22] = "premium_cost_excluded=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        self.assert_denied(replace(req, subject="premium_research"))
        self.assert_denied(replace(req, semantic_action="ACTIVATE_RESEARCH_QUEUE"))

    def test_ruins_zero_cost_challenge_and_same_category_chest(self):
        self.assert_authorized(ruins_challenge_request())
        self.assert_authorized(ruins_chest_request())
        req = ruins_challenge_request()
        tokens = list(req.semantic_preconditions)
        tokens[14] = "ruins_premium=true"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[20] = "ruins_npc_troops_maximum=99"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        req = ruins_chest_request()
        tokens = list(req.semantic_preconditions)
        tokens[12] = "ruins_reward_identity=other-category"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[16] = "ruins_premium=true"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))

    def test_hero_duel_exact_free_entry_flee_and_defense_save(self):
        for action in ("hero_duel_free_entry", "hero_duel_flee", "hero_duel_save_defense"):
            with self.subTest(action=action):
                self.assert_authorized(hero_request(action))
        req = hero_request("hero_duel_free_entry")
        tokens = list(req.semantic_preconditions)
        tokens[7] = "current_event_is_hero_duel_survival=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[3] = "hero_duel_free_allowance_before=2"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[-2] = "premium_prompt_absent=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        req = hero_request("hero_duel_flee")
        tokens = list(req.semantic_preconditions)
        tokens[13] = "fight_control_excluded=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[3] = "hero_duel_free_allowance_at_flee=4"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[3] = "hero_duel_free_allowance_at_flee=1"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[4] = "hero_duel_pass_balance_before=-1"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))


    def test_free_alliance_help_individual_and_complete_help_all(self):
        self.assert_authorized(help_request())
        self.assert_authorized(help_request(all=True))
        req = help_request()
        tokens = list(req.semantic_preconditions)
        tokens[6] = "alliance_help_exact_free_label=Help_All"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        req = help_request(all=True)
        tokens = list(req.semantic_preconditions)
        tokens[9] = "alliance_help_request_list_complete=false"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[10] = f"alliance_help_request_set_sha256={'0' * 64}"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[8] = f"alliance_help_request_ids_json={json.dumps(['a' * 24, 'a' * 24], ensure_ascii=True, separators=(',', ':'))}"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))
        tokens = list(req.semantic_preconditions)
        tokens[4] = "alliance_help_request_count=11"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens),
                                  observation=replace(req.observation, quantity=11)))

    def test_food_farm_collection_and_unproven_boosts(self):
        self.assert_authorized(farm_collection_request())
        self.assert_denied(farm_boost_request())
        self.assert_denied(farm_boost_request(diamonds=True))
        req = farm_collection_request()
        invalid_key = "food-farm-output-boost:daily:collection:unbound"
        invalid_key_tokens = list(req.semantic_preconditions)
        invalid_key_tokens[6] = f"canonical_collection_action_key_unclaimed:{invalid_key}"
        self.assert_denied(replace(
            req, action_key=invalid_key, semantic_preconditions=tuple(invalid_key_tokens),
        ))
        tokens = list(req.semantic_preconditions)
        tokens[5] = "current_collection_balance_before=food=100,wood=200,steel=300"
        self.assert_denied(replace(req, semantic_preconditions=tuple(tokens)))


    def test_navigation_only_route_requests_use_generic_freshness_cost_and_binding_gates(self):
        req = navigation_request()
        result = POLICY.evaluate(req)
        self.assertEqual(result.decision, PolicyDecision.AUTHORIZE, result.reason_code)
        self.assertEqual(result.reason_code, "AUTHORIZED_NAVIGATION_ONLY")

        stale = replace(
            req,
            observation=replace(req.observation, capture_completed_monotonic=994.0),
        )
        self.assertEqual(POLICY.evaluate(stale).reason_code, "STALE_FRAME")

        cost_bearing = replace(
            req,
            observation=replace(req.observation, cost_type="ordinary_game_resources", cost_amount=1),
            resource_or_currency="food",
            maximum_cost=1,
            free_only=False,
        )
        self.assertEqual(POLICY.evaluate(cost_bearing).reason_code, "NAVIGATION_COST_DENIED")
        self.assert_denied(replace(req, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL))

        issue_request = replace(req, runtime_session_id="navigation-policy-session")
        issued = POLICY.issue_capability(issue_request)
        self.assertTrue(issued.authorized, issued.reason_code)
        changed_target = replace(
            issue_request,
            policy_phase="pre_dispatch",
            observation=replace(issue_request.observation, target_identity="home.atlas.changed-target"),
        )
        consumed = POLICY.consume_capability(issued.capability, changed_target)
        self.assertFalse(consumed.allow_dispatch)
        self.assertFalse(consumed.binding_matched)
        self.assertEqual(consumed.reason_code, "CAPABILITY_TARGET_MISMATCH")

    def test_unproved_preset_switch_and_generic_strategic_actions_stay_denied(self):
        req = route_request(
            task=TEST_TASK_ID, action="SWITCH_TALENT_PRESET", action_class=ActionClass.SPEND_OR_STRATEGIC,
            kind="talent_preset_switch", subject="training", source="MILITARY_PRESETS", target="preset:training",
            control="APPLY", consequence="switch_saved_talent_preset", post="TRAINING_PRESET_APPLIED",
            cost_type="unknown", cost=0, quantity=1, resource=None, maximum=None, free=False, preconditions=(),
        )
        self.assert_denied(req)
        generic = replace(req, semantic_action="UNAPPROVED_STRATEGIC_ACTION", action_kind="arbitrary")
        self.assert_denied(generic)
        unknown_route_action = replace(donation_request(), semantic_action="UNAPPROVED_ROUTE_ACTION")
        self.assert_denied(unknown_route_action)


if __name__ == "__main__":
    unittest.main()
