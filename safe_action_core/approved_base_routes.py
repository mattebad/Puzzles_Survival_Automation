"""Narrow policy admissions for explicitly approved base-route actions.

This module does not grant authority from product approval alone. Each action
is admitted only when its task, revision, semantic labels, current observation,
quantity/cost fields, reset-bound preconditions, and common runtime guards
match the route-specific contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional, Tuple

# Fixed policy allowlist, independent of runtime composition and registration.
DONATION_TASK = "ALLIANCE-TECH-DONATION-BLUESTACKS-INTEGRATION"
DONATION_PRODUCT = "alliance_donation"
DONATION_REVISION = "alliance_donation-v1"
ALLIANCE_HELP_TASK = "ALLIANCE-HELP-TEN-FREE-REQUESTS"
ALLIANCE_HELP_PRODUCT = "alliance_help"
ALLIANCE_HELP_REVISION = "alliance_help-v1"
ALLIANCE_SHOP_TASK = "ALLIANCE-SHOP-PURCHASE-EVIDENCE-GATE"
ALLIANCE_SHOP_REVISION = "alliance_shop_purchase-v2"
DAILY_SHOPS_TASK = "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE"
DAILY_SHOPS_REVISION = "daily_shops_purchase-v1"
FOOD_FARM_TASK = "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION"
FOOD_FARM_PRODUCT = "food_farm_output_boost"
FOOD_FARM_REVISION = "food_farm_output_boost-v1"
HALL_OF_WAR_TASK = "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION"
HALL_OF_WAR_PRODUCT = "hall_of_war_zombie_zero"
HALL_OF_WAR_REVISION = "hall_of_war_zombie_zero-v1"
HERO_DUEL_TASK = "HERO-DUEL-EVIDENCE-GATE"
HERO_DUEL_PRODUCT = "hero_duel"
HERO_DUEL_REVISION = "hero_duel-v2"
NANO_PRODUCTION_TASK = "NANO-MATERIAL-PRODUCTION-MAINTENANCE"
NANO_PRODUCTION_PRODUCT = "nano_material_production"
NANO_PRODUCTION_REVISION = "nano_material_production-v1"
NANOWEAPON_TASK = "NANOWEAPON-BLUESTACKS-INTEGRATION"
NANOWEAPON_PRODUCT = "nanoweapon_normal_craft"
NANOWEAPON_REVISION = "nanoweapon_normal_craft-v2"
RECOMMENDED_RESEARCH_TASK = "RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION"
RECOMMENDED_RESEARCH_PRODUCT = "recommended_research"
RECOMMENDED_RESEARCH_REVISION = "recommended_research-v1"
RUINS_FLOW = "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
RUINS_PRODUCT = "ruins_challenge"
RUINS_TASK = RUINS_PRODUCT
RUINS_REVISION = "ruins_challenge-v1"
TROOP_TRAINING_TASK = "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
TROOP_TRAINING_PRODUCT = "troop_training"
TROOP_TRAINING_REVISION = "troop_training-v3"

from .models import ActionClass, PolicyDecision, PolicyRequest

MAX_EXACT_ROUTE_INTEGER = 2_147_483_647
MAX_ROUTE_QUANTITY = 1_000_000
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_APPROVED_ROUTE_TASKS = frozenset({
    DONATION_TASK, ALLIANCE_SHOP_TASK, DAILY_SHOPS_TASK, NANO_PRODUCTION_TASK,
    NANOWEAPON_TASK, RECOMMENDED_RESEARCH_TASK, TROOP_TRAINING_TASK, ALLIANCE_HELP_TASK,
    RUINS_TASK, HERO_DUEL_TASK, FOOD_FARM_TASK, HALL_OF_WAR_TASK,
})
_APPROVED_ROUTE_ACTION_TASKS = {
    "DONATE_ALLIANCE_TECH": DONATION_TASK,
    "PURCHASE_ALLIANCE_SHOP_OFFER": ALLIANCE_SHOP_TASK,
    "PURCHASE_DAILY_SHOP_MATERIAL": DAILY_SHOPS_TASK,
    "claim_nano_material_production": NANO_PRODUCTION_TASK,
    "start_nano_material_production": NANO_PRODUCTION_TASK,
    "claim_completed_nanoweapon": NANOWEAPON_TASK,
    "start_one_normal_nanoweapon_craft": NANOWEAPON_TASK,
    "START_RECOMMENDED_RESEARCH": RECOMMENDED_RESEARCH_TASK,
    "TROOP_TRAINING_START": TROOP_TRAINING_TASK,
    "TROOP_TRAINING_COMPLETED_BATCH_CLAIM": TROOP_TRAINING_TASK,
    "TROOP_TRAINING_RESOURCE_BOX_CONTINUATION": TROOP_TRAINING_TASK,
    "HELP_ALLIANCE_REQUEST": ALLIANCE_HELP_TASK,
    "ruins_zero_cost_npc_challenge_dispatch": RUINS_TASK,
    "ruins_green_ready_stage_chest_claim": RUINS_TASK,
    "hero_duel_free_entry": HERO_DUEL_TASK,
    "hero_duel_flee": HERO_DUEL_TASK,
    "hero_duel_save_defense": HERO_DUEL_TASK,
    "collect_food_farm_resources": FOOD_FARM_TASK,
    "apply_food_farm_output_boost_owned_item": FOOD_FARM_TASK,
    "buy_food_farm_output_boost_diamonds": FOOD_FARM_TASK,
    "HALL_OF_WAR_ZOMBIE_ZERO_DISPATCH": HALL_OF_WAR_TASK,
    "HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_CLAIM": HALL_OF_WAR_TASK,
}


def is_approved_base_route_request(request: PolicyRequest) -> bool:
    return request.task_id in _APPROVED_ROUTE_TASKS or request.semantic_action in _APPROVED_ROUTE_ACTION_TASKS


def _deny(code: str, reason: str) -> Tuple[PolicyDecision, str, str]:
    return PolicyDecision.DENY, code, reason


def _lock(code: str, reason: str) -> Tuple[PolicyDecision, str, str]:
    return PolicyDecision.GLOBAL_INPUT_LOCK, code, reason




def _integer_token(value: object, *, minimum: int = 0, maximum: int = MAX_EXACT_ROUTE_INTEGER) -> Optional[int]:
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]*)", value, flags=re.ASCII):
        return None
    number = int(value)
    return number if minimum <= number <= maximum else None


def _slug(value: object) -> bool:
    return type(value) is str and _SLUG.fullmatch(value) is not None


def _hash(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _tokens(request: PolicyRequest, length: int) -> Optional[Tuple[str, ...]]:
    values = request.semantic_preconditions
    if type(values) is not tuple or len(values) != length or any(type(value) is not str for value in values):
        return None
    return values


def _field(token: str, prefix: str) -> Optional[str]:
    if not token.startswith(prefix):
        return None
    value = token[len(prefix) :]
    return value if value else None


def _route_runtime_guard(request: PolicyRequest) -> Optional[Tuple[PolicyDecision, str, str]]:
    observation = request.observation
    if observation.os_surface or observation.hard_stop_detected or not observation.package_foreground:
        return _lock("APPROVED_BASE_ROUTE_HARD_STOP", "OS, manual stop, or package foreground safety is not proven")
    if observation.forbidden_region_intersects_target:
        return _deny("APPROVED_BASE_ROUTE_TARGET_DANGEROUS", "the bound target intersects a forbidden control")
    if observation.overlay_state not in {"none", "none_observed"}:
        return _deny("APPROVED_BASE_ROUTE_OVERLAY", "the exact clear overlay state is not present")
    return None


def _contract_matches(
    request: PolicyRequest,
    *,
    action_class: ActionClass,
    semantic_action: str,
    action_kind: str,
    subject: Optional[str],
    source_state: str,
    target_identity: str,
    control_class: str,
    consequence: str,
    postcondition: str,
    cost_type: str,
    cost_amount: int,
    quantity: int,
    resource_or_currency: Optional[str],
    maximum_cost: Optional[int],
    free_only: bool,
    require_isolated: bool = True,
) -> bool:
    observation = request.observation
    if (
        request.action_class is not action_class
        or request.semantic_action != semantic_action
        or request.action_kind != action_kind
        or request.subject != subject
        or request.task_mode != "supervised_validation"
        or request.game_day_id is None
        or observation.source_state != source_state
        or observation.target_identity != target_identity
        or observation.control_class != control_class
        or observation.consequence != consequence
        or observation.expected_postcondition != postcondition
        or observation.cost_type != cost_type
        or type(observation.cost_amount) is not int
        or observation.cost_amount != cost_amount
        or request.resource_or_currency != resource_or_currency
        or observation.quantity != quantity
        or (
            maximum_cost is None
            and request.maximum_cost is not None
        )
        or (
            maximum_cost is not None
            and (type(request.maximum_cost) is not int or request.maximum_cost != maximum_cost)
        )
        or request.free_only is not free_only
        or request.semantic_postconditions != (postcondition,)
        or (require_isolated and observation.target_isolated is not True)
    ):
        return False
    return True


def _exact_tuple(request: PolicyRequest, expected: Tuple[str, ...]) -> bool:
    values = _tokens(request, len(expected))
    return values == expected


def _donation(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("ALLIANCE_DONATION_ACTION_NOT_EXACT", "only the current exact ordinary Alliance Tech donation is allowed")
    if not _contract_matches(
        request,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        semantic_action="DONATE_ALLIANCE_TECH",
        action_kind=DONATION_REVISION,
        subject=request.subject,
        source_state="ALLIANCE_TECH_DONATION_PANEL",
        target_identity="alliance-tech:ordinary-donate",
        control_class="DONATE",
        consequence="alliance_tech_donation_effect",
        postcondition="ALLIANCE_TECH_DONATION_CONFIRMED",
        cost_type="ordinary_resource",
        cost_amount=request.observation.cost_amount if type(request.observation.cost_amount) is int else -1,
        quantity=1,
        resource_or_currency=request.resource_or_currency,
        maximum_cost=request.observation.cost_amount if type(request.observation.cost_amount) is int else -1,
        free_only=False,
    ):
        return deny
    if request.game_day_id is None or not _slug(request.subject):
        return deny
    tokens = _tokens(request, 15)
    if tokens is None:
        return deny
    prefixes = (
        "alliance_donation_product=",
        "alliance_donation_product_revision=",
        "alliance_donation_game_day=",
        "alliance_donation_hot_marker=",
        "alliance_donation_target=",
        "alliance_donation_attempts=",
        "alliance_donation_balance=",
        "alliance_donation_resource=",
        "alliance_donation_cost=",
        "alliance_donation_quantity=",
        "alliance_donation_single_tap=",
        "alliance_donation_no_premium=",
        "alliance_donation_no_refill=",
        "alliance_donation_no_hold=",
        "alliance_donation_daily_action_count=",
    )
    values = tuple(_field(token, prefix) for token, prefix in zip(tokens, prefixes))
    if any(value is None for value in values):
        return deny
    product, revision, reset, hot, target, attempts_text, balance_text, resource, cost_text, qty_text, tap, premium, refill, hold, count_text = values
    if (
        product != DONATION_PRODUCT
        or revision != DONATION_REVISION
        or reset != request.game_day_id
        or hot != "true"
        or target != request.subject
        or resource not in {"FOOD", "WOOD", "STEEL", "GAS"}
        or resource != request.resource_or_currency
        or qty_text != "1"
        or tap != "true"
        or premium != "true"
        or refill != "true"
        or hold != "true"
    ):
        return deny
    if not re.fullmatch(r"(?:[1-9]|1[0-9]|20)/20", attempts_text or "", flags=re.ASCII):
        return deny
    attempts = int(attempts_text.split("/", 1)[0])
    balance = _integer_token(balance_text)
    cost = _integer_token(cost_text, minimum=1)
    count = _integer_token(count_text, maximum=9)
    if balance is None or cost is None or count is None or balance < cost:
        return deny
    if request.observation.cost_amount != cost or request.maximum_cost != cost:
        return deny
    expected = (
        f"alliance_donation_product={DONATION_PRODUCT}",
        f"alliance_donation_product_revision={DONATION_REVISION}",
        f"alliance_donation_game_day={request.game_day_id}",
        "alliance_donation_hot_marker=true",
        f"alliance_donation_target={request.subject}",
        f"alliance_donation_attempts={attempts}/20",
        f"alliance_donation_balance={balance}",
        f"alliance_donation_resource={resource}",
        f"alliance_donation_cost={cost}",
        "alliance_donation_quantity=1",
        "alliance_donation_single_tap=true",
        "alliance_donation_no_premium=true",
        "alliance_donation_no_refill=true",
        "alliance_donation_no_hold=true",
        f"alliance_donation_daily_action_count={count}",
    )
    if not _exact_tuple(request, expected):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_ALLIANCE_TECH_DONATION", "exact current HOT ordinary-resource donation and daily quota guards passed"


_ALLIANCE_SHOP_ITEMS = frozenset({
    "joy_coin",
    "timed_recruit_coin",
    "bioenhance_scheme",
    "one_star_gear_enhance_material",
})
_DAILY_SHOP_ITEMS = {
    "3_star_chip_enhance_material": ("ruins_shop", "RUINS_COINS", "RUINS_SHOP_QUANTITY_DIALOG", "daily-shops:ruins:inner-buy", "RUINS_SHOP_PURCHASE_RECONCILED"),
    "3_star_module_enhance_material": ("rare_earth_shop", "RARE_EARTH", "RARE_EARTH_SHOP_QUANTITY_DIALOG", "daily-shops:rare-earth:inner-buy", "RARE_EARTH_SHOP_PURCHASE_RECONCILED"),
}


def _alliance_shop(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("ALLIANCE_SHOP_ACTION_NOT_EXACT", "only one exact allowlisted quantity-one Alliance Shop offer may be bought")
    item = request.subject
    if not _slug(item) or item not in _ALLIANCE_SHOP_ITEMS:
        return deny
    tokens = _tokens(request, 12)
    if tokens is None:
        return deny
    shop = _field(tokens[0], "shop=")
    item_token = _field(tokens[1], "item=")
    currency = _field(tokens[2], "currency=")
    price = _integer_token(_field(tokens[3], "unit_price="), minimum=1)
    stock = _integer_token(_field(tokens[4], "stock="))
    balance = _integer_token(_field(tokens[5], "balance="))
    qty = _integer_token(_field(tokens[6], "quantity="), minimum=1, maximum=1)
    total = _integer_token(_field(tokens[7], "total="), minimum=1)
    reset = _field(tokens[8], "alliance_shop_reset_id=")
    ordinal = _integer_token(_field(tokens[9], "alliance_shop_action_ordinal="), minimum=1, maximum=1)
    count_before = _integer_token(_field(tokens[10], "alliance_shop_action_count_before="), maximum=1)
    limit = _integer_token(_field(tokens[11], "alliance_shop_action_limit="), minimum=1, maximum=1)
    source = {"weekly_offers": "ALLIANCE_SHOP_WEEKLY_QUANTITY_DIALOG", "other": "ALLIANCE_SHOP_OTHER_QUANTITY_DIALOG"}.get(shop)
    allowed_shop_item = (
        (shop == "weekly_offers" and item in {"joy_coin", "timed_recruit_coin", "bioenhance_scheme"})
        or (shop == "other" and item == "one_star_gear_enhance_material")
    )
    if (
        source is None
        or item_token != item
        or currency != "ALLIANCE_COINS"
        or not allowed_shop_item
        or stock is None or balance is None or price is None or qty is None or total is None
        or stock < 1 or balance < price or total != price
        or reset != request.game_day_id or ordinal != 1 or count_before != 0 or limit != 1
    ):
        return deny
    if not _contract_matches(
        request,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        semantic_action="PURCHASE_ALLIANCE_SHOP_OFFER",
        action_kind=ALLIANCE_SHOP_REVISION,
        subject=item,
        source_state=source,
        target_identity="alliance-shop:inner-buy",
        control_class="BUY",
        consequence="alliance_shop_purchase",
        postcondition="ALLIANCE_SHOP_PURCHASE_RECONCILED",
        cost_type="ALLIANCE_COINS",
        cost_amount=total,
        quantity=1,
        resource_or_currency="ALLIANCE_COINS",
        maximum_cost=total,
        free_only=False,
    ):
        return deny
    expected = (
        f"shop={shop}", f"item={item}", "currency=ALLIANCE_COINS",
        f"unit_price={price}", f"stock={stock}", f"balance={balance}", "quantity=1", f"total={total}",
        f"alliance_shop_reset_id={request.game_day_id}", "alliance_shop_action_ordinal=1",
        "alliance_shop_action_count_before=0", "alliance_shop_action_limit=1",
    )
    if not _exact_tuple(request, expected):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_ALLIANCE_SHOP_PURCHASE", "exact allowlisted Alliance offer, quantity one, current balance, and total passed"


def _daily_shops(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("DAILY_SHOPS_ACTION_NOT_EXACT", "only the exact current affordable maximum for a listed daily shop material may be bought")
    item = request.subject
    if not _slug(item) or item not in _DAILY_SHOP_ITEMS:
        return deny
    shop, currency, source, target, post = _DAILY_SHOP_ITEMS[item]
    tokens = _tokens(request, 14)
    if tokens is None:
        return deny
    values = tuple(_field(tokens[index], prefix) for index, prefix in enumerate((
        "shop=", "item=", "rarity=", "currency=", "unit_price=", "stock=", "balance=", "quantity=", "total=",
    )))
    if any(value is None for value in values):
        return deny
    shop_value, item_value, rarity, currency_value, price_text, stock_text, balance_text, qty_text, total_text = values
    price = _integer_token(price_text, minimum=1)
    reset = _field(tokens[9], "daily_shops_reset_id=")
    tab = _field(tokens[10], "daily_shops_tab=")
    ordinal = _integer_token(_field(tokens[11], "daily_shops_tab_action_ordinal="), minimum=1, maximum=1)
    count_before = _integer_token(_field(tokens[12], "daily_shops_tab_action_count_before="), maximum=1)
    limit = _integer_token(_field(tokens[13], "daily_shops_tab_action_limit="), minimum=1, maximum=1)
    stock = _integer_token(stock_text)
    balance = _integer_token(balance_text)
    qty = _integer_token(qty_text, minimum=1, maximum=MAX_ROUTE_QUANTITY)
    total = _integer_token(total_text, minimum=1)
    if (
        shop_value != shop or item_value != item or rarity != "3" or currency_value != currency
        or price is None or stock is None or balance is None or qty is None or total is None
        or total != price * qty or total > MAX_EXACT_ROUTE_INTEGER
        or qty != min(stock, balance // price)
        or reset != request.game_day_id or tab != shop
        or ordinal != 1 or count_before != 0 or limit != 1
    ):
        return deny
    if not _contract_matches(
        request,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        semantic_action="PURCHASE_DAILY_SHOP_MATERIAL",
        action_kind=DAILY_SHOPS_REVISION,
        subject=item,
        source_state=source,
        target_identity=target,
        control_class="BUY",
        consequence="daily_shops_purchase",
        postcondition=post,
        cost_type=currency,
        cost_amount=total,
        quantity=qty,
        resource_or_currency=currency,
        maximum_cost=total,
        free_only=False,
    ):
        return deny
    expected = (
        f"shop={shop}", f"item={item}", "rarity=3", f"currency={currency}",
        f"unit_price={price}", f"stock={stock}", f"balance={balance}",
        f"quantity={qty}", f"total={total}",
        f"daily_shops_reset_id={request.game_day_id}", f"daily_shops_tab={shop}",
        "daily_shops_tab_action_ordinal=1", "daily_shops_tab_action_count_before=0",
        "daily_shops_tab_action_limit=1",
    )
    if not _exact_tuple(request, expected):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_DAILY_SHOP_PURCHASE", "exact item/currency pair and displayed affordable stock-bounded maximum passed"


def _nanoweapon(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    action = request.semantic_action
    deny = _deny("NANOWEAPON_ACTION_NOT_EXACT", "only the exact bounded material-production or Normal Craft action is allowed")
    nano_claim = action == "claim_nano_material_production"
    nano_start = action == "start_nano_material_production"
    craft_claim = action == "claim_completed_nanoweapon"
    craft_start = action == "start_one_normal_nanoweapon_craft"
    if not (nano_claim or nano_start or craft_claim or craft_start):
        return deny
    task = NANO_PRODUCTION_TASK if nano_claim or nano_start else NANOWEAPON_TASK
    if request.task_id != task:
        return _deny("NANOWEAPON_TASK_MISMATCH", "Nano Material and Normal Craft actions are bound to their exact task")
    if nano_claim or nano_start:
        tokens = _tokens(request, 11)
        if tokens is None or tokens[:3] != (
            f"product_id={NANO_PRODUCTION_PRODUCT}",
            f"product_revision={NANO_PRODUCTION_REVISION}",
            "effect_ordinal=1",
        ):
            return deny
        occurrence = _field(tokens[3], "native_occurrence_key=")
        phase = "claim" if nano_claim else "start"
        if (
            type(occurrence) is not str or not occurrence
            or tokens[4] != "native_action_key_binds_occurrence=true"
            or request.action_key != f"{NANO_PRODUCTION_PRODUCT}|{occurrence}|{phase}"
        ):
            return deny
        suffix = (
            ("material_production_tab", "production_state=complete", "active_production_count=0",
             "completed_batch_count=1", "cost=none:0", "zero_resource_claim")
            if nano_claim
            else ("material_production_tab", "production_state=idle", "active_production_count=0",
                  "duration_seconds=21600", "cost=none:0", "production_start_ordinal=1")
        )
        if tokens[5:] != suffix:
            return deny
        action_class = ActionClass.ZERO_COST_CONSEQUENTIAL
        action_kind = "CLAIM_NANO_MATERIAL_PRODUCTION" if nano_claim else "START_NANO_MATERIAL_PRODUCTION"
        subject = "nano-material-production-claim" if nano_claim else "nano-material-production-start"
        control = "CLAIM" if nano_claim else "PRODUCE"
        consequence = "nano_material_production_claim" if nano_claim else "nano_material_production_start"
        postcondition = "NANO_MATERIAL_PRODUCTION_CLAIMED" if nano_claim else "NANO_MATERIAL_PRODUCTION_ACTIVE_21600"
        cost_type, cost, currency, maximum, free = "none", 0, None, 0, True
    elif craft_claim:
        tokens = _tokens(request, 10)
        if tokens is None:
            return deny
        expected = (
            f"product_id={NANOWEAPON_PRODUCT}",
            f"product_revision={NANOWEAPON_REVISION}",
            "effect_ordinal=1",
            f"game_day_id={request.game_day_id}",
            "prior_material_production_reconciled=1",
            "normal_craft_tab",
            "completed_normal_craft=1",
            "active_craft_count=0",
            "claim_visible=1",
            "cost=none:0",
        )
        if not request.game_day_id or tokens != expected:
            return deny
        action_class = ActionClass.ZERO_COST_CONSEQUENTIAL
        action_kind = "CLAIM_NANOWEAPON_COMPLETED"
        subject = "nanoweapon-completed-claim"
        control = "CLAIM"
        consequence = "nanoweapon_completed_claim"
        postcondition = "NANOWEAPON_CRAFT_CLAIMED"
        cost_type, cost, currency, maximum, free = "none", 0, None, 0, True
    else:
        tokens = _tokens(request, 14)
        if tokens is None:
            return deny
        balance = _integer_token(_field(tokens[7], "nano_parts_balance="))
        expected = (
            f"product_id={NANOWEAPON_PRODUCT}",
            f"product_revision={NANOWEAPON_REVISION}",
            "effect_ordinal=1",
            "prior_material_production_reconciled=1",
            "normal_craft_tab",
            "recipe_selection=normal",
            f"game_day_id={request.game_day_id}",
            f"nano_parts_balance={balance}" if balance is not None else "",
            "cost=NANO_PARTS:100",
            "duration_seconds=43200",
            "active_craft_count=0",
            "current_reset_start_ordinal=1",
            "exclusive_craft=0",
            "rotating_display=0",
        )
        if not request.game_day_id or balance is None or balance < 100 or tokens != expected:
            return deny
        action_class = ActionClass.SPEND_OR_STRATEGIC
        action_kind = "START_NORMAL_NANOWEAPON_CRAFT"
        subject = "nanoweapon-craft-normal"
        control = "CRAFT"
        consequence = "nanoweapon_normal_craft"
        postcondition = "NANOWEAPON_NORMAL_CRAFT_ACTIVE"
        cost_type, cost, currency, maximum, free = "NANO_PARTS", 100, "NANO_PARTS", 100, False
    if not _contract_matches(
        request,
        action_class=action_class,
        semantic_action=action,
        action_kind=action_kind,
        subject=subject,
        source_state="NANOWEAPON",
        target_identity=subject,
        control_class=control,
        consequence=consequence,
        postcondition=postcondition,
        cost_type=cost_type,
        cost_amount=cost,
        quantity=1,
        resource_or_currency=currency,
        maximum_cost=maximum,
        free_only=free,
    ):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    code = "AUTHORIZED_NANO_MATERIAL_PRODUCTION" if nano_claim or nano_start else "AUTHORIZED_NANOWEAPON_NORMAL_CRAFT"
    return PolicyDecision.AUTHORIZE, code, "exact current Nanoweapon tab, recipe, resource, and bounded action facts passed"


def _recommended_research(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("RECOMMENDED_RESEARCH_ACTION_NOT_EXACT", "only the first current recommended target on idle queue 1 with affordable ordinary costs is allowed")
    target = request.subject
    if not _slug(target):
        return deny
    tokens = _tokens(request, 24)
    if tokens is None:
        return deny
    fixed = (
        f"product_id={RECOMMENDED_RESEARCH_PRODUCT}",
        f"product_revision={RECOMMENDED_RESEARCH_REVISION}",
        f"recommended_research_reset={request.game_day_id}",
        "recommended_research_start_ordinal=1",
        "recommended_research_start_count_before=0",
        f"first_displayed_recommendation_identity={target}",
        "recommendation_position=1",
        "queue1_state=idle",
        "queue2_activate_tapped=false",
        "prerequisites_known=true",
        "prerequisites_met=true",
    )
    if tokens[:11] != fixed:
        return deny
    prerequisite_evidence = _field(tokens[11], "prerequisite_evidence=")
    if not _slug(prerequisite_evidence):
        return deny
    resources = ("food", "wood", "steel", "gas")
    for index, resource in enumerate(resources):
        cost = _integer_token(_field(tokens[12 + index * 2], f"{resource}_cost="))
        balance = _integer_token(_field(tokens[13 + index * 2], f"{resource}_balance="))
        if cost is None or balance is None or balance < cost:
            return deny
    if tokens[20:] != (
        "cost_source=detail_panel_scrolled_complete",
        "affordable=true",
        "premium_cost_excluded=true",
        "research_now_diamonds_excluded=true",
    ):
        return deny
    if not _contract_matches(
        request,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        semantic_action="START_RECOMMENDED_RESEARCH",
        action_kind="research_start",
        subject=target,
        source_state="RESEARCH_DETAIL",
        target_identity=f"recommended-research:{target}:detail-research-button",
        control_class="RESEARCH_START",
        consequence="start_ordinary_recommended_research",
        postcondition="RESEARCH_ACTIVE_WITH_TIMER_AND_MATCHED_RESOURCE_DEBIT",
        cost_type="ordinary_resource_bundle",
        cost_amount=1,
        quantity=1,
        resource_or_currency="food+wood+steel+gas",
        maximum_cost=None,
        free_only=False,
    ):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_RECOMMENDED_RESEARCH", "first displayed recommendation, idle queue 1, and all current ordinary resource rows passed"





_RUINS_CHALLENGE_IDS = frozenset({
    "hero-challenge", "weapon-trial", "tech-challenge", "gear-challenge",
    "core-challenge", "nova-challenge", "module-challenge", "glory-challenge",
    "bioenhancer-challenge", "ultimate-challenge", "chip-challenge", "cube-challenge",
})
_RUINS_WEEKDAYS = frozenset({"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})


def _ruins(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("RUINS_ACTION_NOT_EXACT", "only a current exact zero-cost NPC challenge or independently ready chest is allowed")
    action = request.semantic_action
    if action == "ruins_zero_cost_npc_challenge_dispatch":
        tokens = _tokens(request, 23)
        if tokens is None:
            return deny
        fields = tuple(_field(token, prefix) for token, prefix in zip(tokens, (
            "ruins_product=", "ruins_product_revision=", "ruins_flow=", "ruins_account_id=",
            "ruins_server_id=", "ruins_reset_id=", "ruins_game_day=", "ruins_category=",
            "ruins_challenge_identity=", "ruins_challenge_day=", "ruins_challenge_availability=",
            "ruins_challenge_control=", "ruins_cost_type=", "ruins_cost_amount=", "ruins_premium=",
            "ruins_paid=", "ruins_ticketed=", "ruins_npc_troops=", "ruins_npc_troops_current=",
            "ruins_npc_troops_maximum=", "ruins_skip_battle=", "ruins_dispatch_count_before=",
            "ruins_dispatch_count_limit=",
        )))
        if any(value is None for value in fields):
            return deny
        (product, revision, flow, account, server, reset, game_day, category, identity,
         challenge_day, availability, control, cost_type, cost_text, premium, paid,
         ticketed, npc_troops, current_text, maximum_text, skip, count_text, limit_text) = fields
        current = _integer_token(current_text, minimum=1, maximum=MAX_ROUTE_QUANTITY)
        maximum = _integer_token(maximum_text, minimum=1, maximum=MAX_ROUTE_QUANTITY)
        if (
            product != RUINS_PRODUCT or revision != RUINS_REVISION
            or flow != RUINS_FLOW or not _slug(account) or not _slug(server)
            or current is None or maximum is None or current != maximum
            or reset != request.game_day_id or game_day not in _RUINS_WEEKDAYS
            or category != "challenge" or identity not in _RUINS_CHALLENGE_IDS
            or challenge_day not in _RUINS_WEEKDAYS | {"active_timer"}
            or (challenge_day in _RUINS_WEEKDAYS and challenge_day != game_day)
            or availability != "available" or control != "visible_enabled"
            or cost_type != "none" or cost_text != "0" or premium != "false"
            or paid != "false" or ticketed != "false" or npc_troops != "provided"
            or skip != "true" or count_text != "0" or limit_text != "1"
        ):
            return deny
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=f"ruins_challenge:{identity}",
            source_state="RUINS_CHALLENGE_DETAIL",
            target_identity="ruins-dispatch",
            control_class="DISPATCH",
            consequence="ruins_zero_cost_npc_challenge",
            postcondition="RUINS_CHALLENGE_RESULT_RECOGNIZED",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        if not _slug(request.game_day_id):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_RUINS_ZERO_COST_CHALLENGE", "one current-day, full-capacity NPC challenge with no paid or ticket cost passed"
    if action == "ruins_green_ready_stage_chest_claim":
        tokens = _tokens(request, 21)
        if tokens is None:
            return deny
        fields = tuple(_field(token, prefix) for token, prefix in zip(tokens, (
            "ruins_product=", "ruins_product_revision=", "ruins_flow=", "ruins_account_id=",
            "ruins_server_id=", "ruins_reset_id=", "ruins_game_day=", "ruins_category=",
            "ruins_chest_identity=", "ruins_chest_state=", "ruins_chest_fully_visible=",
            "ruins_claim_control=", "ruins_reward_identity=", "ruins_reward_medals=",
            "ruins_cost_type=", "ruins_cost_amount=", "ruins_premium=", "ruins_exchange=",
            "ruins_shop=", "ruins_claim_count_before=", "ruins_claim_count_limit=",
        )))
        if any(value is None for value in fields):
            return deny
        (product, revision, flow, account, server, reset, game_day, category, identity,
         state, visible, control, reward, medals_text, cost_type, cost_text, premium,
         exchange, shop, count_text, limit_text) = fields
        medals = _integer_token(medals_text, minimum=1)
        if (
            product != RUINS_PRODUCT or revision != RUINS_REVISION
            or flow != RUINS_FLOW or not _slug(account) or not _slug(server)
            or reset != request.game_day_id or game_day not in _RUINS_WEEKDAYS
            or category != "chest" or not _slug(identity) or state != "green_ready"
            or visible != "true" or control != "visible_enabled" or reward != identity
            or medals is None or cost_type != "none" or cost_text != "0"
            or premium != "false" or exchange != "false" or shop != "false"
            or count_text != "0" or limit_text != "1"
        ):
            return deny
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=f"ruins_stage_chest:{identity}",
            source_state="RUINS_REWARD_MODAL",
            target_identity="ruins-reward-claim",
            control_class="CLAIM",
            consequence="ruins_zero_cost_ready_chest_reward",
            postcondition="RUINS_STAGE_CHEST_CLAIMED",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_RUINS_READY_CHEST", "exact same-category green-ready chest and zero-cost claim passed"
    return deny


def _hero_duel(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("HERO_DUEL_ACTION_NOT_EXACT", "only exact free Survival setup, entry, or same-cycle Flee actions are allowed")
    action = request.semantic_action
    prefix = (f"hero_duel_product={HERO_DUEL_PRODUCT}", f"hero_duel_product_revision={HERO_DUEL_REVISION}")
    if action == "hero_duel_free_entry":
        tokens = _tokens(request, 16)
        if tokens is None or tokens[:2] != prefix:
            return deny
        event_id = _field(tokens[2], "hero_duel_event_identity=")
        allowance = _integer_token(_field(tokens[3], "hero_duel_free_allowance_before="), minimum=1, maximum=3)
        pass_balance = _integer_token(_field(tokens[4], "hero_duel_pass_balance_before="))
        ordinal = _integer_token(_field(tokens[5], "hero_duel_entry_ordinal="), minimum=1, maximum=3)
        reset = _field(tokens[6], "hero_duel_entry_reset=")
        if (
            not _slug(event_id) or allowance is None or pass_balance is None or ordinal is None
            or reset != request.game_day_id or allowance != 4 - ordinal
        ):
            return deny
        if tokens[7:] != (
            "current_event_is_hero_duel_survival", "event_active",
            "emergency_details_exclusions_inspected", "defense_first_five_eligible_saved",
            "attack_five_eligible_slots_populated", "listed_opponent_free_selected",
            "entry_cost_exactly_zero", "premium_prompt_absent", "overlay_absent",
        ):
            return deny
        source, target, control, consequence, post = (
            "hero_duel_attack_formation", "hero-duel-attack-challenge",
            "FREE_CHALLENGE", "bounded_hero_duel_participation", "hero_duel_battle_loaded",
        )
    elif action == "hero_duel_flee":
        tokens = _tokens(request, 16)
        if tokens is None or tokens[:2] != prefix:
            return deny
        event_id = _field(tokens[2], "hero_duel_event_identity=")
        allowance = _integer_token(_field(tokens[3], "hero_duel_free_allowance_at_flee="), maximum=3)
        pass_balance = _integer_token(_field(tokens[4], "hero_duel_pass_balance_before="))
        ordinal = _integer_token(_field(tokens[5], "hero_duel_entry_ordinal="), minimum=1, maximum=3)
        reset = _field(tokens[6], "hero_duel_entry_reset=")
        if (
            not _slug(event_id) or allowance is None or pass_balance is None or ordinal is None
            or reset != request.game_day_id or allowance != 3 - ordinal
        ):
            return deny
        if tokens[7:] != (
            "current_event_is_hero_duel_survival", "entry_same_cycle_ordinal_confirmed",
            "current_battle_loaded", "battle_exit_control_bound", "flee_warning_visible",
            "flee_button_bound", "fight_control_excluded", "premium_prompt_absent", "overlay_absent",
        ):
            return deny
        source, target, control, consequence, post = (
            "hero_duel_flee_warning", "hero-duel-warning-flee",
            "FLEE", "accept_hero_duel_loss", "hero_duel_loss_result",
        )
    elif action == "hero_duel_save_defense":
        tokens = _tokens(request, 10)
        if tokens is None or tokens[:2] != prefix:
            return deny
        event_id = _field(tokens[2], "hero_duel_event_identity=")
        if not _slug(event_id) or tokens[3:] != (
            "current_event_is_hero_duel_survival", "event_active",
            "emergency_details_exclusions_inspected", "first_five_eligible_heroes_bound",
            "five_defense_slots_exact", "prohibited_support_absent", "overlay_absent",
        ):
            return deny
        source, target, control, consequence, post = (
            "hero_duel_defense_formation", "hero-duel-defense-save-form",
            "SAVE_FORM", "set_hero_duel_defense", "hero_duel_lineup_saved",
        )
    else:
        return deny
    if not _contract_matches(
        request,
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        semantic_action=action,
        action_kind=action,
        subject=None,
        source_state=source,
        target_identity=target,
        control_class=control,
        consequence=consequence,
        postcondition=post,
        cost_type="none",
        cost_amount=0,
        quantity=1,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
    ):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_HERO_DUEL_FREE_ACTION", "exact Survival event, numeric free/pass balances, bounded entry/Flee, or defense-save guards passed"

def _hall_of_war(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("HALL_OF_WAR_ACTION_NOT_EXACT", "only the bounded Zombie Zero action and its exact own reward claim are in scope")
    action = request.semantic_action
    if action == "HALL_OF_WAR_ZOMBIE_ZERO_DISPATCH":
        tokens = request.semantic_preconditions
        if type(tokens) is not tuple or len(tokens) != 19:
            return _deny("HALL_OF_WAR_LOSS_EFFECT_UNPROVEN", "current exact cost and independent current no-loss ROI proof are required before Dispatch")
        frame_hash = request.observation.frame_sha256
        reset = _field(tokens[2], "hall_of_war_reset=")
        cost_frame = _field(tokens[13], "dispatch_cost_source_frame=")
        cost_roi = _field(tokens[14], "hall_of_war_explicit_zero_cost=")
        loss_frame = _field(tokens[16], "troop_loss_effect_source_frame=")
        loss_roi = _field(tokens[17], "hall_of_war_no_loss_rule=")
        fixed = (
            f"hall_of_war_product={HALL_OF_WAR_PRODUCT}",
            f"hall_of_war_product_revision={HALL_OF_WAR_REVISION}",
            f"hall_of_war_reset={request.game_day_id}",
            "current_reset_id_bound_to_game_day_id",
            "challenge_action_ordinal=1",
            "challenge_action_key_binds_attempt_ordinal_one_for_current_reset",
            "exact_zombie_zero_page_and_today_highest_damage_zero",
            "challenge_attempt_ready_and_not_busy_or_cooling_down",
            "saved_military_preset_verified",
            "troop_set_1_saved_identity_selected_not_edit_or_quick_select",
            "troop_set_1_application_toast_verified",
            "five_hero_slots_populated",
            "current_troop_count_exactly_matches_visible_capacity_and_positive",
            f"dispatch_cost_source_frame={frame_hash}",
            f"hall_of_war_explicit_zero_cost={cost_roi}" if cost_roi is not None else "",
            "troop_loss_effect=explicit_no_loss",
            f"troop_loss_effect_source_frame={frame_hash}",
            f"hall_of_war_no_loss_rule={loss_roi}" if loss_roi is not None else "",
            "one_dispatch_transport_remaining",
        )
        roi_hashes = request.observation.critical_roi_hashes
        action_key_pattern = rf"hall-of-war:dispatch:daily:{re.escape(request.game_day_id or '')}:attempt-1:[0-9a-f]{{64}}"
        if (
            reset != request.game_day_id or not _slug(reset)
            or frame_hash != cost_frame or frame_hash != loss_frame
            or not _hash(cost_roi) or not _hash(loss_roi)
            or sum(name == "hall_of_war_explicit_zero_cost" for name, _digest in roi_hashes) != 1
            or sum(name == "hall_of_war_no_loss_rule" for name, _digest in roi_hashes) != 1
            or not any(name == "hall_of_war_explicit_zero_cost" and digest == cost_roi for name, digest in roi_hashes)
            or not any(name == "hall_of_war_no_loss_rule" and digest == loss_roi for name, digest in roi_hashes)
            or re.fullmatch(action_key_pattern, request.action_key, flags=re.ASCII) is None
            or tokens != fixed
        ):
            return _deny("HALL_OF_WAR_LOSS_EFFECT_UNPROVEN", "current exact zero-cost and frame-bound explicit no-loss proof did not match")
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=None,
            source_state="HALL_OF_WAR_ZOMBIE_ZERO_DISPATCH",
            target_identity="hall-of-war:zombie-zero:dispatch",
            control_class="DISPATCH",
            consequence="hall_of_war_zombie_zero_attempt",
            postcondition="HALL_OF_WAR_ZOMBIE_ZERO_HISTORY_HIGH_RESULT",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_HALL_OF_WAR_ZOMBIE_ZERO", "exact current zero-cost ROI and independently frame-bound explicit no-loss rule passed"
    if action == "HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_CLAIM":
        tokens = _tokens(request, 11)
        expected = (
            f"hall_of_war_product={HALL_OF_WAR_PRODUCT}",
            f"hall_of_war_product_revision={HALL_OF_WAR_REVISION}",
            f"hall_of_war_reset={request.game_day_id}",
            "current_reset_id_bound_to_game_day_id",
            "daily_reward_claim_ordinal=1",
            "reward_action_key_independent_from_challenge_key_and_binds_current_reset",
            "same_reset_zombie_zero_participation_proven_by_confirmed_dispatch_or_exact_positive_today_highest_damage",
            "exact_zombie_zero_daily_reward_row_identity",
            "current_reward_row_explicitly_glowing_and_enabled",
            "claimed_label_and_green_checkmarks_absent",
            "one_reward_claim_transport_remaining",
        )
        reward_key_pattern = rf"hall-of-war:reward:daily:{re.escape(request.game_day_id or '')}:claim-1:[0-9a-f]{{64}}"
        if (
            tokens is None or not request.game_day_id or tokens != expected
            or re.fullmatch(reward_key_pattern, request.action_key, flags=re.ASCII) is None
        ):
            return deny
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=None,
            source_state="HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_READY",
            target_identity="hall-of-war:zombie-zero:daily-reward-row",
            control_class="CLAIM",
            consequence="hall_of_war_daily_reward_claim",
            postcondition="HALL_OF_WAR_ZOMBIE_ZERO_DAILY_REWARD_CLAIMED_CHECKMARKS",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_HALL_OF_WAR_OWN_REWARD", "exact current own-reward readiness and once-per-reset claim guards passed"
    return deny


_TRAINING_VARIANTS = {
    "fighter": ("fighter_camp", 8, "current_max", "current_max", "continuous", True),
    "vehicle": ("vehicle_depot", 1, "current_max", "current_max", "continuous", True),
    "shooter": ("shooter_camp", 8, "fixed", "250", "once_daily", False),
    "rider": ("rider_camp", 1, "fixed", "250", "once_daily", False),
}

_TRAINING_START_KEY = re.compile(
    r"^troop-training:([0-9a-f]{64}):([0-9a-f]{64}):(fighter|vehicle|shooter|rider):g([1-9][0-9]*):start$",
    flags=re.ASCII,
)


def _training_key_parts(value: object) -> Optional[Tuple[str, str, str, int]]:
    if type(value) is not str:
        return None
    match = _TRAINING_START_KEY.fullmatch(value)
    if match is None:
        return None
    generation = _integer_token(match.group(4), minimum=1)
    if generation is None:
        return None
    return match.group(1), match.group(2), match.group(3), generation


def _training(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("TROOP_TRAINING_ACTION_NOT_EXACT", "only an exact configured ordinary-resource training start or confirmed outstanding batch claim is allowed")
    action = request.semantic_action
    if action == "TROOP_TRAINING_RESOURCE_BOX_CONTINUATION":
        return _deny(
            "TROOP_TRAINING_BOX_COST_UNPROVEN",
            "the policy request does not bind exact resource-box identity/count or an authorized inventory-effect record; popup recognition and projected resource changes do not prove the consumed inventory effect",
        )
    if action == "TROOP_TRAINING_COMPLETED_BATCH_CLAIM":
        tokens = _tokens(request, 28)
        if tokens is None:
            return deny
        variant = _field(tokens[7], "variant=")
        if variant not in _TRAINING_VARIANTS:
            return deny
        facility, tier, mode, configured, policy, _allow_boxes = _TRAINING_VARIANTS[variant]
        scope = _field(tokens[3], "runtime_scope=")
        account = _field(tokens[4], "account_id=")
        server = _field(tokens[5], "server_id=")
        runtime_hash = _field(tokens[6], "runtime_identity_sha256=")
        quantity = _integer_token(_field(tokens[13], "selected_quantity="), minimum=1, maximum=MAX_ROUTE_QUANTITY)
        batch_quantity = _integer_token(_field(tokens[20], "completed_batch_quantity="), minimum=1, maximum=MAX_ROUTE_QUANTITY)
        batch_id = _field(tokens[15], "completed_batch_id=")
        confirmed_key = _field(tokens[16], "confirmed_start_action_key=")
        confirmed_reset = _field(tokens[17], "confirmed_start_reset_id=")
        generation = _integer_token(_field(tokens[22], "queue_generation="), minimum=1)
        starts = _integer_token(_field(tokens[23], "per_reset_variant_start_count="), maximum=MAX_ROUTE_QUANTITY)
        claims = _integer_token(_field(tokens[24], "per_reset_variant_claim_count="), maximum=MAX_ROUTE_QUANTITY)
        start_key_parts = _training_key_parts(batch_id)
        if scope is None or account is None or server is None or runtime_hash is None or confirmed_reset is None:
            return deny
        expected_runtime_hash = hashlib.sha256(f"{scope}\0{account}\0{server}".encode("utf-8")).hexdigest()
        expected = (
            f"troop_training_product={TROOP_TRAINING_PRODUCT}",
            f"troop_training_product_revision={TROOP_TRAINING_REVISION}",
            "approved_profile=true",
            f"runtime_scope={scope}",
            f"account_id={account}",
            f"server_id={server}",
            f"runtime_identity_sha256={expected_runtime_hash}",
            f"variant={variant}",
            f"facility_identity={facility}",
            f"troop_type={variant}",
            f"tier={tier}",
            f"quantity_mode={mode}",
            f"configured_quantity={configured}",
            f"selected_quantity={quantity}" if quantity is not None else "",
            "completed_batch_ready=true",
            f"completed_batch_id={batch_id}" if batch_id is not None else "",
            f"confirmed_start_action_key={batch_id}" if batch_id is not None else "",
            f"confirmed_start_reset_id={confirmed_reset}",
            f"completed_batch_troop_type={variant}",
            f"completed_batch_tier={tier}",
            f"completed_batch_quantity={quantity}" if quantity is not None else "",
            "queue_state=positively_completed",
            f"queue_generation={generation}" if generation is not None else "",
            f"per_reset_variant_start_count={starts}" if starts is not None else "",
            f"per_reset_variant_claim_count={claims}" if claims is not None else "",
            f"reset_id={request.game_day_id}",
            "overlay=none",
            "forbidden_controls=none",
        )
        if (
            runtime_hash != expected_runtime_hash or quantity is None or batch_quantity is None
            or quantity != batch_quantity or generation is None or starts is None or claims is None
            or request.game_day_id is None or not _slug(request.game_day_id) or not _slug(confirmed_reset)
            or start_key_parts is None or batch_id != confirmed_key or request.action_key != f"{batch_id}:claim"
            or start_key_parts[0] != runtime_hash
            or start_key_parts[1] != hashlib.sha256(confirmed_reset.encode("utf-8")).hexdigest()
            or start_key_parts[2] != variant or start_key_parts[3] != generation
            or tokens != expected
        ):
            return deny
        post = f"TROOP_TRAINING_BATCH_CLAIMED:{variant}:{batch_id}"
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=action,
            source_state="TROOP_TRAINING_SCREEN",
            target_identity=f"troop_training:completed_batch_claim:{variant}",
            control_class=f"tab:{variant}:claim-completed",
            consequence="claim_zero_cost_reward",
            postcondition=post,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_TROOP_TRAINING_BATCH_CLAIM", "exact outstanding confirmed start key and completed variant batch passed"
    if action != "TROOP_TRAINING_START" or request.task_id != TROOP_TRAINING_TASK:
        return deny
    tokens = _tokens(request, 33)
    if tokens is None:
        return deny
    scope = _field(tokens[2], "runtime_scope=")
    account = _field(tokens[3], "account_id=")
    server = _field(tokens[4], "server_id=")
    runtime_hash = _field(tokens[5], "runtime_identity_sha256=")
    if scope is None or account is None or server is None or runtime_hash is None:
        return deny
    expected_runtime_hash = hashlib.sha256(f"{scope}\0{account}\0{server}".encode("utf-8")).hexdigest()
    variant = _field(tokens[8], "variant=")
    if variant not in _TRAINING_VARIANTS:
        return deny
    facility, tier, mode, configured, policy, allow_boxes = _TRAINING_VARIANTS[variant]
    qty = _integer_token(_field(tokens[14], "selected_quantity="), minimum=1, maximum=MAX_ROUTE_QUANTITY)
    maximum = _integer_token(_field(tokens[15], "quantity_maximum="), minimum=1, maximum=MAX_ROUTE_QUANTITY)
    generation = _integer_token(_field(tokens[19], "queue_generation="), minimum=1)
    count = _integer_token(_field(tokens[20], "per_reset_variant_start_count="), maximum=MAX_ROUTE_QUANTITY)
    if qty is None or maximum is None or generation is None or count is None:
        return deny
    fixed = (
        f"troop_training_product={TROOP_TRAINING_PRODUCT}",
        f"troop_training_product_revision={TROOP_TRAINING_REVISION}",
        f"runtime_scope={scope}",
        f"account_id={account}",
        f"server_id={server}",
        f"runtime_identity_sha256={expected_runtime_hash}",
        f"game_day_id={request.game_day_id}",
        "approved_profile=true",
        f"variant={variant}",
        f"facility_identity={facility}",
        f"troop_type={variant}",
        f"tier={tier}",
        f"quantity_mode={mode}",
        f"configured_quantity={configured}",
        f"selected_quantity={qty}",
        f"quantity_maximum={maximum}",
        f"training_policy={policy}",
        f"allow_resource_boxes={str(allow_boxes).lower()}",
        "queue_state=positively_empty",
        f"queue_generation={generation}",
        f"per_reset_variant_start_count={count}",
        "saved_commander_talent_preset=Training",
        "saved_commander_talent_preset_verified=true",
    )
    key_parts = _training_key_parts(request.action_key)
    if (
        not request.game_day_id or not _slug(request.game_day_id)
        or runtime_hash != expected_runtime_hash or tokens[:23] != fixed
        or key_parts is None or key_parts[0] != runtime_hash
        or key_parts[1] != hashlib.sha256(request.game_day_id.encode("utf-8")).hexdigest()
        or key_parts[2] != variant or key_parts[3] != generation
    ):
        return deny
    resource_costs = []
    for index, resource in enumerate(("food", "wood", "steel", "gas")):
        held = _integer_token(_field(tokens[23 + index * 2], f"resource.{resource}.held="))
        required = _integer_token(_field(tokens[24 + index * 2], f"resource.{resource}.required="))
        if held is None or required is None or held < required:
            return deny
        resource_costs.append(required)
    if tokens[31:] != ("forbidden_controls=none", "overlay=none"):
        return deny
    if (
        (mode == "current_max" and qty != maximum)
        or (mode == "fixed" and (qty != 250 or maximum < 250))
        or (policy == "once_daily" and count != 0)
    ):
        return deny
    total_cost = sum(resource_costs)
    if total_cost > MAX_EXACT_ROUTE_INTEGER:
        return deny
    post = f"active_queue_confirmed:{variant}:{tier}:{qty}:positive_current_timer"
    if not _contract_matches(
        request,
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        semantic_action=action,
        action_kind="troop_training_start",
        subject=variant,
        source_state="TROOP_TRAINING_SCREEN",
        target_identity=f"troop_training:normal_train:{variant}",
        control_class="TRAIN",
        consequence="troop_training_start",
        postcondition=post,
        cost_type="ordinary_game_resources",
        cost_amount=total_cost,
        quantity=qty,
        resource_or_currency="food+wood+steel+gas",
        maximum_cost=total_cost,
        free_only=False,
    ):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_TROOP_TRAINING_START", "fixed variant, global generation key, live queue/quantity, Training preset, and exact affordable resource vector passed"


def _alliance_help(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("ALLIANCE_HELP_ACTION_NOT_EXACT", "only one exact individual free Help or bounded complete Help All action is allowed")
    if request.semantic_action != "HELP_ALLIANCE_REQUEST" or request.action_kind != "HELP_ALLIANCE_REQUEST":
        return deny
    if request.game_day_id is None:
        return deny
    tokens = request.semantic_preconditions
    if type(tokens) is not tuple or not tokens:
        return deny
    if request.observation.target_identity == "alliance-help-individual-request":
        if len(tokens) != 8:
            return deny
        ordinal = _integer_token(_field(tokens[4], "alliance_help_request_ordinal="), minimum=1, maximum=10)
        expected = (
            f"alliance_help_product={ALLIANCE_HELP_PRODUCT}",
            f"alliance_help_product_revision={ALLIANCE_HELP_REVISION}",
            "alliance_help_quota=10",
            f"alliance_help_request_reset={request.game_day_id}",
            f"alliance_help_request_ordinal={ordinal}" if ordinal is not None else "",
            "alliance_help_target_variant=individual",
            "alliance_help_exact_free_label=Help",
            "alliance_help_complete_request_transition_required",
        )
        target, subject, control, quantity = "alliance-help-individual-request", "alliance-help-individual-request", "FREE_HELP", 1
    elif request.observation.target_identity == "alliance-help-all":
        if len(tokens) != 12:
            return deny
        ordinal = _integer_token(_field(tokens[3], "alliance_help_request_ordinal="), minimum=1, maximum=10)
        quantity = _integer_token(_field(tokens[4], "alliance_help_request_count="), minimum=1, maximum=10)
        request_ids_json = _field(tokens[8], "alliance_help_request_ids_json=")
        digest = _field(tokens[10], "alliance_help_request_set_sha256=")
        if request_ids_json is None or len(request_ids_json) > 512 or digest is None or not _hash(digest):
            return deny
        try:
            request_ids = json.loads(request_ids_json)
        except (TypeError, ValueError):
            return deny
        if (
            type(request_ids) is not list or quantity is None or len(request_ids) != quantity
            or any(type(item) is not str or re.fullmatch(r"[0-9a-f]{24}", item, flags=re.ASCII) is None for item in request_ids)
            or len(set(request_ids)) != len(request_ids)
            or json.dumps(request_ids, ensure_ascii=True, separators=(",", ":")) != request_ids_json
            or hashlib.sha256(request_ids_json.encode("utf-8")).hexdigest() != digest
            or ordinal is None or ordinal + quantity - 1 > 10
        ):
            return deny
        expected = (
            f"alliance_help_product={ALLIANCE_HELP_PRODUCT}",
            f"alliance_help_product_revision={ALLIANCE_HELP_REVISION}",
            f"alliance_help_request_reset={request.game_day_id}",
            f"alliance_help_request_ordinal={ordinal}",
            f"alliance_help_request_count={quantity}",
            "alliance_help_quota=10",
            "alliance_help_target_variant=help_all",
            "alliance_help_exact_free_label=Help_All",
            f"alliance_help_request_ids_json={request_ids_json}",
            "alliance_help_request_list_complete=true",
            f"alliance_help_request_set_sha256={digest}",
            "alliance_help_complete_request_transition_required",
        )
        target, subject, control = "alliance-help-all", "alliance-help-all", "FREE_HELP_ALL"
    else:
        return deny
    if ordinal is None or type(quantity) is not int or tokens != expected:
        return deny
    if not _contract_matches(
        request,
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        semantic_action="HELP_ALLIANCE_REQUEST",
        action_kind="HELP_ALLIANCE_REQUEST",
        subject=subject,
        source_state="SPEEDUP_HELP",
        target_identity=target,
        control_class=control,
        consequence="alliance_help_zero_cost",
        postcondition="ALLIANCE_HELP_REQUEST_RESULT",
        cost_type="none",
        cost_amount=0,
        quantity=quantity,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
    ):
        return deny
    guard = _route_runtime_guard(request)
    if guard is not None:
        return guard
    return PolicyDecision.AUTHORIZE, "AUTHORIZED_ALLIANCE_HELP", "exact current free request, reset-bound ordinal, and bounded quota passed"


def _food_farm(request: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
    deny = _deny("FOOD_FARM_ACTION_NOT_EXACT", "only exact current Farm collection is authorizable while boost item identities remain unproven")
    action = request.semantic_action
    farm = request.subject if action == "collect_food_farm_resources" else None
    if action == "collect_food_farm_resources":
        tokens = _tokens(request, 8)
        if tokens is None or type(farm) is not str or re.fullmatch(r"home\.building\.farm\.[0-9]{2}", farm, flags=re.ASCII) is None:
            return deny
        if (
            _field(tokens[0], "product_id:") != FOOD_FARM_PRODUCT
            or _field(tokens[1], "product_revision:") != FOOD_FARM_REVISION
            or _field(tokens[2], "reset_identity:") != request.game_day_id
            or tokens[3] != "effect_ordinal:collection=1"
            or _field(tokens[4], "current_clean_home_atlas_binding:") != farm
            or tokens[6] != f"canonical_collection_action_key_unclaimed:{request.action_key}"
            or type(request.action_key) is not str
            or re.fullmatch(r"food-farm-output-boost:occurrence:collection:[0-9a-f]{64}", request.action_key, flags=re.ASCII) is None
            or tokens[7] != "current_runtime_lease_valid"
        ):
            return deny
        balance = _field(tokens[5], "current_collection_balance_before:")
        if balance is None or not _farm_resource_vector(balance):
            return deny
        if not _contract_matches(
            request,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            semantic_action=action,
            action_kind=action,
            subject=farm,
            source_state="HOME_BASE",
            target_identity=farm,
            control_class="COLLECT",
            consequence="collect_all_base_resource_building_output",
            postcondition="FOOD_FARM_COLLECTION_RECONCILED",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            resource_or_currency="none",
            maximum_cost=0,
            free_only=True,
        ):
            return deny
        guard = _route_runtime_guard(request)
        if guard is not None:
            return guard
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_FOOD_FARM_COLLECTION", "fresh exact Atlas-bound Farm collection and reset-scoped collection key passed"
    if action == "apply_food_farm_output_boost_owned_item":
        return _deny("FOOD_FARM_OWNED_ITEM_IDENTITY_UNPROVEN", "the exact owned boost inventory identity and current count are not proven")
    if action == "buy_food_farm_output_boost_diamonds":
        return _deny("FOOD_FARM_DIAMOND_OFFER_IDENTITY_UNPROVEN", "the exact current diamond offer identity and direct-action semantics are not proven")
    return deny


def _farm_resource_vector(value: str) -> bool:
    parts = value.split(",")
    if len(parts) != 4:
        return False
    for part, resource in zip(parts, ("food", "wood", "steel", "gas")):
        if _integer_token(_field(part, f"{resource}=")) is None:
            return False
    return True


def decide_approved_base_route(request: PolicyRequest) -> Optional[Tuple[PolicyDecision, str, str]]:
    """Return a route-specific decision, or ``None`` for unrelated legacy policy."""
    # Route-owned recipes must not consume navigation-only requests. Let the
    # central navigation policy retain its freshness, binding, and cost gates.
    if request.action_class is ActionClass.NAVIGATION_ONLY:
        return None
    known_task = request.task_id in _APPROVED_ROUTE_TASKS
    expected_task = _APPROVED_ROUTE_ACTION_TASKS.get(request.semantic_action)
    if not known_task and expected_task is None:
        return None
    if expected_task is not None and request.task_id != expected_task:
        return _deny("APPROVED_BASE_ROUTE_TASK_MISMATCH", "route semantic action is bound to a different task")
    if request.task_id == DONATION_TASK:
        return _donation(request)
    if request.task_id == ALLIANCE_SHOP_TASK:
        return _alliance_shop(request)
    if request.task_id == DAILY_SHOPS_TASK:
        return _daily_shops(request)
    if request.task_id in {NANO_PRODUCTION_TASK, NANOWEAPON_TASK}:
        return _nanoweapon(request)
    if request.task_id == RECOMMENDED_RESEARCH_TASK:
        return _recommended_research(request)
    if request.task_id == TROOP_TRAINING_TASK:
        return _training(request)
    if request.task_id == ALLIANCE_HELP_TASK:
        return _alliance_help(request)
    if request.task_id == RUINS_TASK:
        return _ruins(request)
    if request.task_id == HERO_DUEL_TASK:
        return _hero_duel(request)
    if request.task_id == FOOD_FARM_TASK:
        return _food_farm(request)
    if request.task_id == HALL_OF_WAR_TASK:
        return _hall_of_war(request)
    return _deny("APPROVED_BASE_ROUTE_ACTION_NOT_EXACT", "action is not in the route-specific policy set")
