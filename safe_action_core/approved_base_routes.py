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

from .models import ActionClass, PolicyDecision, PolicyRequest

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

RUINS_FLOW = "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"

RUINS_PRODUCT = "ruins_challenge"

RUINS_TASK = RUINS_PRODUCT

RUINS_REVISION = "ruins_challenge-v1"

MAX_EXACT_ROUTE_INTEGER = 2_147_483_647

MAX_ROUTE_QUANTITY = 1_000_000

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

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

_APPROVED_ROUTE_TASKS = frozenset({DONATION_TASK, ALLIANCE_SHOP_TASK, DAILY_SHOPS_TASK, ALLIANCE_HELP_TASK, RUINS_TASK})

_APPROVED_ROUTE_ACTION_TASKS = {'DONATE_ALLIANCE_TECH': DONATION_TASK, 'PURCHASE_ALLIANCE_SHOP_OFFER': ALLIANCE_SHOP_TASK, 'PURCHASE_DAILY_SHOP_MATERIAL': DAILY_SHOPS_TASK, 'HELP_ALLIANCE_REQUEST': ALLIANCE_HELP_TASK, 'ruins_zero_cost_npc_challenge_dispatch': RUINS_TASK, 'ruins_green_ready_stage_chest_claim': RUINS_TASK}

def decide_approved_base_route(request: PolicyRequest) -> Optional[Tuple[PolicyDecision, str, str]]:
    """Return a route-specific decision, or ``None`` for unrelated legacy policy."""
    if request.action_class is ActionClass.NAVIGATION_ONLY:
        return None
    known_task = request.task_id in _APPROVED_ROUTE_TASKS
    expected_task = _APPROVED_ROUTE_ACTION_TASKS.get(request.semantic_action)
    if not known_task and expected_task is None:
        return None
    if expected_task is not None and request.task_id != expected_task:
        return _deny('APPROVED_BASE_ROUTE_TASK_MISMATCH', 'route semantic action is bound to a different task')
    if request.task_id == DONATION_TASK:
        return _donation(request)
    if request.task_id == ALLIANCE_SHOP_TASK:
        return _alliance_shop(request)
    if request.task_id == DAILY_SHOPS_TASK:
        return _daily_shops(request)
    if request.task_id == ALLIANCE_HELP_TASK:
        return _alliance_help(request)
    if request.task_id == RUINS_TASK:
        return _ruins(request)
    return _deny('APPROVED_BASE_ROUTE_ACTION_NOT_EXACT', 'action is not in the route-specific policy set')
