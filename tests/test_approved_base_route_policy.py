from __future__ import annotations

import hashlib

import json

import unittest

from dataclasses import replace

from automation_service.registry import ALLIANCE_DONATION_FLOW_ID as DONATION, ALLIANCE_DONATION_PRODUCT_ID as DONATION_PRODUCT, ALLIANCE_DONATION_PRODUCT_REVISION as DONATION_REVISION, ALLIANCE_HELP_FLOW_ID as HELP, ALLIANCE_HELP_PRODUCT_ID as HELP_PRODUCT, ALLIANCE_HELP_PRODUCT_REVISION as HELP_REVISION, ALLIANCE_SHOP_FLOW_ID as ALLIANCE_SHOP, ALLIANCE_SHOP_PRODUCT_REVISION as ALLIANCE_SHOP_REVISION, DAILY_SHOPS_FLOW_ID as DAILY_SHOPS, DAILY_SHOPS_PRODUCT_REVISION as DAILY_SHOPS_REVISION, RUINS_FLOW_ID as RUINS, RUINS_PRODUCT_ID as RUINS_PRODUCT, RUINS_PRODUCT_REVISION as RUINS_REVISION

from safe_action_core.models import ActionClass, PolicyDecision

from safe_action_core.policy import CentralPolicy

from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

from tests.support.safe_action import TEST_TASK_ID, observation, request as base_request

DAY = "game-day-2026-07-15"

FRAME = "a" * 64

OTHER_TASK = "OTHER-SUPERVISED-TASK"

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

POLICY = CentralPolicy({DONATION, ALLIANCE_SHOP, DAILY_SHOPS, HELP, RUINS_PRODUCT, TEST_TASK_ID, OTHER_TASK})

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

if __name__ == "__main__":
    unittest.main()
