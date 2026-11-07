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

ALLIANCE_HELP_TASK = "ALLIANCE-HELP-TEN-FREE-REQUESTS"

ALLIANCE_HELP_PRODUCT = "alliance_help"

ALLIANCE_HELP_REVISION = "alliance_help-v1"

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

_APPROVED_ROUTE_TASKS = frozenset({ALLIANCE_HELP_TASK, RUINS_TASK})
_APPROVED_ROUTE_ACTION_TASKS = {
    "HELP_ALLIANCE_REQUEST": ALLIANCE_HELP_TASK,
    "ruins_zero_cost_npc_challenge_dispatch": RUINS_TASK,
    "ruins_green_ready_stage_chest_claim": RUINS_TASK,
}


def decide_approved_base_route(request: PolicyRequest) -> Optional[Tuple[PolicyDecision, str, str]]:
    """Admit only this batch's exact route actions; retain central navigation policy."""
    if request.action_class is ActionClass.NAVIGATION_ONLY:
        return None
    expected_task = _APPROVED_ROUTE_ACTION_TASKS.get(request.semantic_action)
    if request.task_id not in _APPROVED_ROUTE_TASKS and expected_task is None:
        return None
    if expected_task is not None and request.task_id != expected_task:
        return _deny("APPROVED_BASE_ROUTE_TASK_MISMATCH", "route semantic action is bound to a different task")
    if request.task_id == ALLIANCE_HELP_TASK:
        return _alliance_help(request)
    if request.task_id == RUINS_TASK:
        return _ruins(request)
    return _deny("APPROVED_BASE_ROUTE_ACTION_NOT_EXACT", "action is not in the route-specific policy set")

