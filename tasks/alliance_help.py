"""Pure Alliance Help request semantics; persistence and input stay in the native boundary."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping, Sequence


DAILY_REQUEST_LIMIT = 10
SOURCE_STATE = "SPEEDUP_HELP"
HELP_ALL_TARGET_IDENTITY = "alliance-help-all"
INDIVIDUAL_TARGET_IDENTITY = "alliance-help-individual-request"
SEMANTIC_ACTION = "HELP_ALLIANCE_REQUEST"
CONSEQUENCE = "alliance_help_zero_cost"
POSTCONDITION = "ALLIANCE_HELP_REQUEST_RESULT"
CONTROL_CLASS = "FREE_HELP"


class HelpAction(str, Enum):
    HELP_ALL = "help_all"
    INDIVIDUAL = "individual"
    NO_REQUESTS = "no_requests"
    FREE_HELP_DISAPPEARED = "free_help_disappeared"
    STOP_QUOTA = "stop_quota"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HelpRequest:
    """One current, stable Alliance request and its current free Help control."""

    request_id: str
    target_roi: tuple[int, int, int, int]
    free_control: bool
    exact_free_label: bool


@dataclass(frozen=True)
class HelpObservation:
    """Fresh screen evidence; a static screen or tap is never a result."""

    screen_state: str
    captured_at: float
    frame_sha256: str
    overlay_clear: bool
    source_fresh: bool
    requests: tuple[HelpRequest, ...]
    help_all_roi: tuple[int, int, int, int] | None = None
    help_all_free: bool = False
    exact_no_requests_message: bool = False
    pending_count: int | None = None
    request_list_complete: bool = False
    cost_marker_seen: bool = False
    daily_alliance_coin_balance: int | None = None
    daily_alliance_coin_limit: int | None = None
    help_success_message: bool = False
    help_all_success_count: int | None = None
    recognizer_reason: str | None = None


@dataclass(frozen=True)
class HelpPlan:
    action: HelpAction
    target_identity: str | None
    target_roi: tuple[int, int, int, int] | None
    request_ids: tuple[str, ...]
    reason: str


def choose_help_action(observation: HelpObservation, remaining: int, *, allow_help_all: bool = False) -> HelpPlan:
    """Choose one safe transaction from exact current evidence.

    Help All is admissible only when the complete current request set is positively
    bounded and no larger than the still-unfilled quota. Incomplete or unknown lists
    fall back to one independently bound free Help control.
    """
    if type(remaining) is not int or not 0 <= remaining <= DAILY_REQUEST_LIMIT:
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "invalid_remaining_quota")
    if remaining == 0:
        return HelpPlan(HelpAction.STOP_QUOTA, None, None, (), "ten_requests_confirmed")
    if (observation.screen_state != SOURCE_STATE or not observation.source_fresh
            or not observation.overlay_clear or not observation.frame_sha256):
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "source_stale_unknown_or_overlay")
    if observation.cost_marker_seen:
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "cost_or_paid_control_seen")
    if observation.exact_no_requests_message:
        if observation.requests:
            return HelpPlan(HelpAction.UNKNOWN, None, None, (), "no_requests_conflicts_with_controls")
        return HelpPlan(HelpAction.NO_REQUESTS, None, None, (), "exact_no_requests_message")

    requests = observation.requests
    if requests:
        balance, limit = observation.daily_alliance_coin_balance, observation.daily_alliance_coin_limit
        if (type(balance) is not int or type(limit) is not int or not 0 <= balance < limit):
            return HelpPlan(HelpAction.UNKNOWN, None, None, (), "result_counter_missing_or_at_limit")
    if len({item.request_id for item in requests}) != len(requests):
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "duplicate_request_identity")
    if any(not item.request_id or not item.free_control or not item.exact_free_label
           or not _valid_roi(item.target_roi) for item in requests):
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "unknown_or_nonfree_individual_control")

    # A visibly present Help All control is not proof of how many requests it covers.
    # Require an independently complete list and exact matching pending count.
    if allow_help_all and observation.help_all_roi is not None:
        if not _valid_roi(observation.help_all_roi) or not observation.help_all_free:
            return HelpPlan(HelpAction.UNKNOWN, None, None, (), "help_all_cost_or_binding_unknown")
        if (observation.request_list_complete and type(observation.pending_count) is int
                and observation.pending_count == len(requests) and 0 < observation.pending_count <= remaining):
            return HelpPlan(HelpAction.HELP_ALL, HELP_ALL_TARGET_IDENTITY,
                            observation.help_all_roi, tuple(item.request_id for item in requests),
                            "complete_request_list_within_remaining_quota")

    if requests:
        first = requests[0]
        return HelpPlan(HelpAction.INDIVIDUAL, INDIVIDUAL_TARGET_IDENTITY,
                        first.target_roi, (first.request_id,),
                        "one_current_free_request_bounded_to_one")
    if not observation.requests or not observation.help_all_free:
        return HelpPlan(HelpAction.FREE_HELP_DISAPPEARED, None, None, (), "no_current_free_request_control")
    return HelpPlan(HelpAction.UNKNOWN, None, None, (), "help_all_count_not_proven_bounded")


def verified_request_delta(
    before: HelpObservation,
    after: HelpObservation,
    *,
    plan: HelpPlan,
    remaining: int,
    transport_calls: int,
) -> int:
    """Return only a transported, positive request/result transition; reject ambiguity."""
    if (type(transport_calls) is not int or transport_calls != 1
            or before.screen_state != SOURCE_STATE or after.screen_state != SOURCE_STATE
            or not before.source_fresh or not after.source_fresh
            or not before.overlay_clear or not after.overlay_clear
            or after.captured_at <= before.captured_at
            or not before.frame_sha256 or not after.frame_sha256
            or type(remaining) is not int or not 1 <= remaining <= DAILY_REQUEST_LIMIT
            or plan.action not in {HelpAction.HELP_ALL, HelpAction.INDIVIDUAL}):
        return 0
    before_by_id = {item.request_id: item for item in before.requests}
    after_by_id = {item.request_id: item for item in after.requests}
    if len(before_by_id) != len(before.requests) or len(after_by_id) != len(after.requests):
        return 0
    if any(not item.request_id for item in (*before.requests, *after.requests)):
        return 0

    removed = set(before_by_id) - set(after_by_id)
    if plan.action is HelpAction.INDIVIDUAL:
        selected = plan.request_ids[0] if len(plan.request_ids) == 1 else None
        coin_delta = _positive_coin_delta(before, after)
        if (selected is None or selected not in before_by_id or selected not in removed
                or not before_by_id[selected].free_control
                or not before_by_id[selected].exact_free_label
                or not after.help_success_message or coin_delta is None):
            return 0
        return 1

    coin_delta = _positive_coin_delta(before, after)
    if (not before.request_list_complete or not after.request_list_complete
            or type(before.pending_count) is not int or type(after.pending_count) is not int
            or before.pending_count != len(before.requests)
            or after.pending_count != len(after.requests)
            or not before.help_all_free or not after.help_all_free
            or plan.request_ids != tuple(item.request_id for item in before.requests)
            or not removed or len(removed) > remaining
            or not after.help_success_message
            or type(after.help_all_success_count) is not int
            or after.help_all_success_count != len(removed)
            or coin_delta is None):
        return 0
    if len(removed) != before.pending_count - after.pending_count + len(set(after_by_id) - set(before_by_id)):
        return 0
    return len(removed)


def _positive_coin_delta(before: HelpObservation, after: HelpObservation) -> int | None:
    old, new = before.daily_alliance_coin_balance, after.daily_alliance_coin_balance
    old_limit, new_limit = before.daily_alliance_coin_limit, after.daily_alliance_coin_limit
    if (type(old) is not int or type(new) is not int or type(old_limit) is not int
            or type(new_limit) is not int or old_limit != new_limit
            or not 0 <= old <= old_limit or not 0 <= new <= new_limit or new <= old):
        return None
    return new - old


def alliance_help_action_key(
    *, runtime_scope: str, account_id: str, server_id: str, reset_id: str, ordinal: int,
) -> str:
    """Canonical, reset-scoped request-occurrence key persisted in SafetyStore."""
    identity = {
        "account_id": account_id,
        "flow_id": "ALLIANCE-HELP-TEN-FREE-REQUESTS",
        "ordinal": ordinal,
        "reset_id": reset_id,
        "runtime_scope": runtime_scope,
        "server_id": server_id,
    }
    for name, value in identity.items():
        if name == "ordinal":
            if type(value) is not int or not 1 <= value <= DAILY_REQUEST_LIMIT:
                raise ValueError("ordinal must name a request in the fixed ten-request quota")
        elif type(value) is not str or not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError(f"{name} must be non-empty normalized identity")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"alliance-help:daily:{hashlib.sha256(encoded).hexdigest()}:{ordinal:02d}"


def confirmed_request_count(actions: Mapping[int, Mapping[str, object]], *, maximum: int = DAILY_REQUEST_LIMIT) -> int:
    """Validate an ordinal prefix of canonical action records and return its durable count."""
    if type(maximum) is not int or maximum != DAILY_REQUEST_LIMIT:
        raise ValueError("Alliance Help occurrence limit is fixed at ten")
    count = 0
    unresolved_seen = False
    for ordinal in range(1, DAILY_REQUEST_LIMIT + 1):
        action = actions.get(ordinal)
        if action is None:
            if any(key > ordinal for key in actions):
                raise ValueError("Alliance Help canonical request ordinals are not contiguous")
            break
        status = action.get("final_status")
        quantity = action.get("quantity")
        if action.get("game_day_id") is None or type(quantity) is not int or quantity != 1:
            raise ValueError("Alliance Help canonical action record has invalid reset or quantity")
        if status == "confirmed" and not unresolved_seen:
            count += 1
            continue
        unresolved_seen = True
        if status not in {"prepared", "input_sent", "unresolved"}:
            raise ValueError("Alliance Help has non-confirmed action in its occurrence prefix")
        if any(key > ordinal for key in actions):
            raise ValueError("Alliance Help cannot continue after an unknown request result")
        break
    if not 0 <= count <= DAILY_REQUEST_LIMIT:
        raise ValueError("Alliance Help durable count is outside its bound")
    return count


def _valid_roi(value: object) -> bool:
    return (type(value) is tuple and len(value) == 4
            and all(type(item) is int for item in value)
            and 0 <= value[0] < value[2] <= 800
            and 0 <= value[1] < value[3] <= 1280)
