"""Pure Alliance Help request semantics; persistence and input stay in the native boundary."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json


DAILY_REQUEST_LIMIT = 10
SOURCE_STATE = "SPEEDUP_HELP"
HELP_ALL_TARGET_IDENTITY = "alliance-help-all"
INDIVIDUAL_TARGET_IDENTITY = "alliance-help-individual-request"
SEMANTIC_ACTION = "HELP_ALLIANCE_REQUEST"
CONSEQUENCE = "alliance_help_zero_cost"
POSTCONDITION = "ALLIANCE_HELP_REQUEST_RESULT"
CONTROL_CLASS = "FREE_HELP"
HELP_ALL_CONTROL_CLASS = "FREE_HELP_ALL"


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
    """Fresh screen evidence; a static screen or tap is never a result.

    ``help_all_success_count`` is an attributable helped-request count shown by the game
    for a Help All result. ``None`` means no such count was recognized; it never means
    zero and is never inferred from rows leaving the list.
    """

    screen_state: str
    captured_at: float
    frame_sha256: str
    overlay_clear: bool
    source_fresh: bool
    requests: tuple[HelpRequest, ...]
    help_all_roi: tuple[int, int, int, int] | None = None
    help_all_free: bool = False
    exact_no_requests_message: bool = False
    cost_marker_seen: bool = False
    help_success_message: bool = False
    help_all_success_count: int | None = None
    recognizer_reason: str | None = None
    ready_request_context: bool = False


@dataclass(frozen=True)
class HelpPlan:
    action: HelpAction
    target_identity: str | None
    target_roi: tuple[int, int, int, int] | None
    request_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class HelpResult:
    """A positively acknowledged Help operation.

    ``proven_request_count`` is the attributable number of successful requests, or
    ``None`` for a known successful Help All batch whose quantity is unproven.
    """

    action: HelpAction
    proven_request_count: int | None


def choose_help_action(observation: HelpObservation, remaining: int) -> HelpPlan:
    """Choose one safe transaction from exact current evidence.

    A bound free Help All control is the native action whenever free requests are
    visible; it may cover several requests and needs no request census. One
    individually bound free Help control is the fallback when Help All is not bound.
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
    # A still-visible earlier result message would make the next result unattributable.
    if observation.help_success_message:
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "prior_result_message_visible")

    if observation.help_all_roi is not None and (
            observation.ready_request_context or observation.requests):
        if not _valid_roi(observation.help_all_roi) or not observation.help_all_free:
            return HelpPlan(HelpAction.UNKNOWN, None, None, (), "help_all_cost_or_binding_unknown")
        return HelpPlan(HelpAction.HELP_ALL, HELP_ALL_TARGET_IDENTITY, observation.help_all_roi,
                        tuple(item.request_id for item in observation.requests),
                        "bound_free_help_all_with_ready_request_context")

    requests = observation.requests
    if len({item.request_id for item in requests}) != len(requests):
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "duplicate_request_identity")
    if any(not item.request_id or not item.free_control or not item.exact_free_label
           or not _valid_roi(item.target_roi) for item in requests):
        return HelpPlan(HelpAction.UNKNOWN, None, None, (), "unknown_or_nonfree_individual_control")
    if not requests:
        return HelpPlan(HelpAction.FREE_HELP_DISAPPEARED, None, None, (), "no_current_free_request_control")
    first = requests[0]
    return HelpPlan(HelpAction.INDIVIDUAL, INDIVIDUAL_TARGET_IDENTITY,
                    first.target_roi, (first.request_id,),
                    "one_current_free_request_bounded_to_one")


def verified_help_result(
    before: HelpObservation,
    after: HelpObservation,
    *,
    plan: HelpPlan,
    transport_calls: int,
) -> HelpResult | None:
    """Return a transported, positively acknowledged result, or ``None`` when unknown.

    The success acknowledgement must appear after the single input and be absent
    immediately before it. Rows leaving the list are corroboration only: other members
    and list motion also remove rows, so they never establish a request count.
    """
    if (type(transport_calls) is not int or transport_calls != 1
            or before.screen_state != SOURCE_STATE or after.screen_state != SOURCE_STATE
            or not before.source_fresh or not after.source_fresh
            or not before.overlay_clear or not after.overlay_clear
            or after.captured_at <= before.captured_at
            or not before.frame_sha256 or not after.frame_sha256
            or before.help_success_message or not after.help_success_message):
        return None
    if plan.action is HelpAction.HELP_ALL:
        selected = choose_help_action(before, DAILY_REQUEST_LIMIT)
        count = after.help_all_success_count
        if (selected.action is not HelpAction.HELP_ALL
                or plan.target_identity != selected.target_identity
                or plan.target_roi != selected.target_roi
                or (count is not None and (type(count) is not int or count < 1))):
            return None
        return HelpResult(HelpAction.HELP_ALL, count)
    before_ids = {item.request_id for item in before.requests}
    if len(before_ids) != len(before.requests) or any(not item for item in before_ids):
        return None
    if plan.action is HelpAction.INDIVIDUAL:
        selected = plan.request_ids[0] if len(plan.request_ids) == 1 else None
        if (selected is None or selected not in before_ids
                or selected in {item.request_id for item in after.requests}):
            return None
        return HelpResult(HelpAction.INDIVIDUAL, 1)
    return None


def alliance_help_action_key(
    *, runtime_scope: str, account_id: str, server_id: str, reset_id: str, ordinal: int,
) -> str:
    """Canonical, reset-scoped Help operation key persisted in SafetyStore.

    ``ordinal`` is the contiguous per-reset operation ordinal shared by individual
    requests and Help All batches. The key never depends on a readable count.
    """
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
            if type(value) is not int or value < 1:
                raise ValueError("ordinal must name a positive per-reset Help operation")
        elif type(value) is not str or not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError(f"{name} must be non-empty normalized identity")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"alliance-help:daily:{hashlib.sha256(encoded).hexdigest()}:{ordinal:02d}"


def _valid_roi(value: object) -> bool:
    return (type(value) is tuple and len(value) == 4
            and all(type(item) is int for item in value)
            and 0 <= value[0] < value[2] <= 800
            and 0 <= value[1] < value[3] <= 1280)
