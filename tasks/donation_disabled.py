"""Offline semantics for one ordinary Alliance Tech donation at a time."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .contracts import ROI
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


ALLIANCE_TECH_SCREEN = "ALLIANCE_TECH_DONATION_PANEL"
DONATION_TARGET = "alliance-tech:ordinary-donate"
DONATION_ACTION = "DONATE_ALLIANCE_TECH"
DONATION_CONSEQUENCE = "alliance_tech_donation_effect"
DONATION_POSTCONDITION = "ALLIANCE_TECH_DONATION_CONFIRMED"
# The ordinary (non-premium) Donate control's displayed cost; the HOT modal hides the wallet,
# so no individual resource identity or balance is part of the action contract.
DONATION_RESOURCE = "ORDINARY_RESOURCE"
MAX_DONATIONS_PER_RESET = 10
MAX_AVAILABLE_ATTEMPTS = 20
ATTEMPT_REGENERATION_SECONDS = 1800
# Displayed countdowns have one-second resolution and captures are not instantaneous.
_TIMER_TOLERANCE_SECONDS = 2.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DonationDisposition(str, Enum):
    READY = "ready"
    DAILY_TARGET_REACHED = "daily_target_reached"
    NO_ATTEMPTS = "no_attempts"
    INSUFFICIENT_RESOURCE = "insufficient_resource"
    BLOCKED = "blocked"


class DonationActionReconciliationError(ValueError):
    """Canonical donation history is incomplete or contains an unknown effect."""


@dataclass(frozen=True)
class DonationObservation:
    """Fresh current-HOT donation evidence; the attempt counter is the only action count."""

    screen_state: str
    auto_hot_marker: bool
    tech_identity: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    donate_control_visible: bool
    control_enabled: bool
    quantity: int
    donation_amount: int | None
    # False when the game shows the ordinary cost as a red shortage; None when unread.
    cost_affordable: bool | None
    available_attempts: int | None
    attempt_capacity: int | None
    next_attempt_available_in_seconds: int | None = None
    game_day_id: str | None = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def _roi(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 4
        and all(type(item) is int for item in value)
        and 0 <= value[0] < value[2]
        and 0 <= value[1] < value[3]
    )


def _target_inside_panel(observation: DonationObservation) -> bool:
    if not _roi(observation.target_roi) or not _roi(observation.panel_bounds):
        return False
    px0, py0, px1, py1 = observation.panel_bounds
    tx0, ty0, tx1, ty1 = observation.target_roi
    return px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1


def _native_observation(observation: DonationObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "native-frame://", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
        and observation.recognized
        and observation.overlay_state in {"none", "none_observed"}
        and not observation.reset_guard_active
    )


def _current_hot_panel(observation: DonationObservation | None, *, require_title: bool = True) -> bool:
    return bool(
        type(observation) is DonationObservation
        and observation.screen_state == ALLIANCE_TECH_SCREEN
        and observation.auto_hot_marker is True
        and (not require_title or (isinstance(observation.tech_identity, str)
                                   and bool(observation.tech_identity.strip())))
        and observation.target_identity == DONATION_TARGET
        and _target_inside_panel(observation)
        and isinstance(observation.game_day_id, str)
        and bool(observation.game_day_id.strip())
        and _native_observation(observation)
    )


def _attempt_counter(observation: DonationObservation) -> bool:
    return (
        type(observation.available_attempts) is int
        and type(observation.attempt_capacity) is int
        and observation.attempt_capacity == MAX_AVAILABLE_ATTEMPTS
        and 0 <= observation.available_attempts <= MAX_AVAILABLE_ATTEMPTS
    )


def donation_disposition(
    observation: DonationObservation,
    committed_action_count: int,
) -> DonationDisposition:
    """Return the safe next state without treating a timer or points as an action count."""

    if type(committed_action_count) is not int or not 0 <= committed_action_count <= MAX_DONATIONS_PER_RESET:
        return DonationDisposition.BLOCKED
    if committed_action_count == MAX_DONATIONS_PER_RESET:
        return DonationDisposition.DAILY_TARGET_REACHED
    if not _current_hot_panel(observation) or not _attempt_counter(observation):
        return DonationDisposition.BLOCKED
    if observation.available_attempts == 0:
        return DonationDisposition.NO_ATTEMPTS
    if (
        type(observation.donation_amount) is not int
        or observation.donation_amount <= 0
        or type(observation.cost_affordable) is not bool
        or observation.control_class != "DONATE"
        or observation.donate_control_visible is not True
        or type(observation.quantity) is not int
        or observation.quantity != 1
    ):
        return DonationDisposition.BLOCKED
    if observation.cost_affordable is False:
        return DonationDisposition.INSUFFICIENT_RESOURCE
    if observation.control_enabled is not True:
        return DonationDisposition.BLOCKED
    return DonationDisposition.READY


def donation_authorizeable(
    observation: DonationObservation,
    committed_action_count: int = 0,
) -> bool:
    """Whether the current ordinary Donate control is eligible for a one-shot request."""

    return donation_disposition(observation, committed_action_count) is DonationDisposition.READY


def attempt_regeneration_observed(
    before: DonationObservation,
    after: DonationObservation,
    elapsed_seconds: float | None,
) -> bool:
    """Whether one ordinary 30-minute attempt refill positively happened between two captures.

    The before countdown must have expired within the elapsed capture interval and the after
    countdown must show a newer period.  An unread or contradictory timer is never a refill.
    """

    timer = before.next_attempt_available_in_seconds
    after_timer = after.next_attempt_available_in_seconds
    return bool(
        type(timer) is int
        and 0 <= timer <= ATTEMPT_REGENERATION_SECONDS
        and type(elapsed_seconds) in (int, float)
        and math.isfinite(float(elapsed_seconds))
        and 0 <= elapsed_seconds < ATTEMPT_REGENERATION_SECONDS - _TIMER_TOLERANCE_SECONDS
        and timer <= float(elapsed_seconds) + _TIMER_TOLERANCE_SECONDS
        and type(after_timer) is int
        and timer < after_timer <= ATTEMPT_REGENERATION_SECONDS
    )


def donation_postcondition_verified(
    before: DonationObservation,
    after: DonationObservation | None,
    committed_action_count_before: int = 0,
    *,
    elapsed_seconds: float | None,
) -> bool:
    """One ordinary tap consumed exactly one displayed attempt, net of an observed refill."""

    if (
        not donation_authorizeable(before, committed_action_count_before)
        or not _current_hot_panel(after, require_title=False)
        or not _attempt_counter(after)
        or after.game_day_id != before.game_day_id
    ):
        return False
    consumed = before.available_attempts - after.available_attempts
    # A refill landing in the same interval leaves the counter unchanged. It must also be
    # counted when rejecting a two-attempt decrement hidden by that refill.
    regenerated = int(attempt_regeneration_observed(before, after, elapsed_seconds))
    return consumed + regenerated == 1


def donation_action_key(
    *,
    account_id: str,
    server_id: str,
    game_day_id: str,
    ordinal: int,
) -> str:
    """Bind one donation to its stable reset-scoped action ordinal."""

    values = (account_id, server_id, game_day_id)
    if any(type(value) is not str or not value.strip() for value in values):
        raise ValueError("donation action identity fields must be non-empty strings")
    if type(ordinal) is not int or not 1 <= ordinal <= MAX_DONATIONS_PER_RESET:
        raise ValueError("donation action ordinal must be from one through ten")
    identity = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"alliance-donation:v1:{identity}:{ordinal:02d}"


def _donation_key_prefix(*, account_id: str, server_id: str, game_day_id: str) -> str:
    return donation_action_key(
        account_id=account_id,
        server_id=server_id,
        game_day_id=game_day_id,
        ordinal=1,
    ).rsplit(":", 1)[0] + ":"


def _action_request_matches(action: Mapping[str, Any], *, flow_id: str, game_day_id: str) -> bool:
    try:
        request = json.loads(action.get("policy_request_json"))
    except (TypeError, ValueError):
        return False
    if not isinstance(request, Mapping):
        return False
    observation = request.get("observation")
    preconditions = request.get("semantic_preconditions")
    if not isinstance(observation, Mapping) or not isinstance(preconditions, list):
        return False
    amount = observation.get("cost_amount")
    # Retain confirmed/cancelled rows written under the old per-resource contract. This is
    # historical journal interpretation only: new requests always use DONATION_RESOURCE.
    resource = request.get("resource_or_currency")
    if resource not in {DONATION_RESOURCE, "FOOD", "WOOD", "STEEL", "GAS"}:
        return False
    required = {
        f"alliance_donation_game_day={game_day_id}",
        f"alliance_donation_resource={resource}",
        f"alliance_donation_cost={amount}",
        "alliance_donation_quantity=1",
    }
    return bool(
        request.get("resource_or_currency") == resource
        and request.get("task_id") == flow_id and request.get("action_key") == action.get("action_key")
        and request.get("semantic_action") == DONATION_ACTION
        and request.get("action_class") == "spend_or_strategic"
        and request.get("game_day_id") == game_day_id
        and request.get("maximum_cost") == action.get("cost_amount")
        and observation.get("source_state") == ALLIANCE_TECH_SCREEN
        and observation.get("target_identity") == DONATION_TARGET
        and observation.get("expected_postcondition") == DONATION_POSTCONDITION
        and observation.get("consequence") == DONATION_CONSEQUENCE
        and observation.get("cost_type") == "ordinary_resource"
        and amount == action.get("cost_amount") and observation.get("quantity") == 1
        and required.issubset(set(preconditions))
    )


def confirmed_donation_count(
    actions: Sequence[Mapping[str, Any]],
    *,
    flow_id: str,
    account_id: str,
    server_id: str,
    game_day_id: str,
) -> int:
    """Rebuild reset-scoped progress from canonical rows and stable ordinals."""

    prefix = _donation_key_prefix(
        account_id=account_id, server_id=server_id, game_day_id=game_day_id
    )
    matched: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    ordinals: set[int] = set()
    for action in actions:
        if action.get("task_id") != flow_id:
            continue
        key = action.get("action_key")
        if type(key) is not str or not key.startswith(prefix):
            continue
        if key in seen:
            raise DonationActionReconciliationError("duplicate canonical donation action key")
        seen.add(key)
        ordinal_text = key[len(prefix):]
        if not ordinal_text.isdigit():
            raise DonationActionReconciliationError("canonical donation action ordinal is malformed")
        ordinal = int(ordinal_text)
        if not 1 <= ordinal <= MAX_DONATIONS_PER_RESET or ordinal_text != f"{ordinal:02d}":
            raise DonationActionReconciliationError("canonical donation action ordinal is outside its quota")
        if ordinal in ordinals:
            raise DonationActionReconciliationError("duplicate canonical donation ordinal")
        ordinals.add(ordinal)
        if (
            action.get("semantic_action") != DONATION_ACTION
            or action.get("source_state") != ALLIANCE_TECH_SCREEN
            or action.get("target_identity") != DONATION_TARGET
            or action.get("consequence") != DONATION_CONSEQUENCE
            or action.get("expected_postcondition") != DONATION_POSTCONDITION
            or action.get("game_day_id") != game_day_id
            or action.get("quantity") != 1
            or action.get("cost_type") != "ordinary_resource"
            or type(action.get("cost_amount")) not in (int, float)
            or type(action.get("cost_amount")) is bool
            or not math.isfinite(float(action["cost_amount"]))
            or action["cost_amount"] <= 0
            or not _action_request_matches(action, flow_id=flow_id, game_day_id=game_day_id)
        ):
            raise DonationActionReconciliationError("canonical donation action does not match its exact contract")
        if action.get("final_status") in {"prepared", "input_sent", "unresolved"}:
            raise DonationActionReconciliationError("canonical donation effect requires observe-only reconciliation")
        if action.get("final_status") == "confirmed":
            matched.append(action)
        elif action.get("final_status") != "cancelled":
            raise DonationActionReconciliationError("canonical donation action status is unknown")
    confirmed_ordinals = {
        int(action["action_key"][len(prefix):])
        for action in matched
    }
    if confirmed_ordinals != set(range(1, len(matched) + 1)):
        raise DonationActionReconciliationError("canonical confirmed donation ordinals contain a gap")
    if len(matched) > MAX_DONATIONS_PER_RESET:
        raise DonationActionReconciliationError("canonical confirmed donation count exceeds ten")
    return len(matched)
