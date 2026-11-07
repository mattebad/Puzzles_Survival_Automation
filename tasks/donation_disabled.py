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
MAX_DONATIONS_PER_RESET = 10
MAX_AVAILABLE_ATTEMPTS = 20
ORDINARY_RESOURCES = frozenset({"FOOD", "WOOD", "STEEL", "GAS"})
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
    """Fresh current-HOT donation evidence; ranking points are deliberately absent."""

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
    resource_identity: str
    resource_known: bool
    donation_amount: int | None
    resource_balance: int | None
    available_attempts: int | None
    attempt_capacity: int | None
    active_recharge_timer: bool | None = None
    next_attempt_available_in_seconds: int | None = None
    tech_points: int | None = None
    reward_signature: tuple[int, ...] | None = None
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


def _current_hot_panel(observation: DonationObservation | None) -> bool:
    return bool(
        type(observation) is DonationObservation
        and observation.screen_state == ALLIANCE_TECH_SCREEN
        and observation.auto_hot_marker is True
        and isinstance(observation.tech_identity, str)
        and bool(observation.tech_identity.strip())
        and observation.target_identity == DONATION_TARGET
        and _target_inside_panel(observation)
        and isinstance(observation.game_day_id, str)
        and bool(observation.game_day_id.strip())
        and _native_observation(observation)
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
    if not _current_hot_panel(observation):
        return DonationDisposition.BLOCKED
    if (
        type(observation.available_attempts) is not int
        or type(observation.attempt_capacity) is not int
        or observation.attempt_capacity != MAX_AVAILABLE_ATTEMPTS
        or not 0 <= observation.available_attempts <= MAX_AVAILABLE_ATTEMPTS
    ):
        return DonationDisposition.BLOCKED
    if observation.available_attempts == 0:
        return DonationDisposition.NO_ATTEMPTS
    resource = observation.resource_identity
    if (
        observation.resource_known is not True
        or not isinstance(resource, str)
        or resource.upper() not in ORDINARY_RESOURCES
        or type(observation.donation_amount) is not int
        or observation.donation_amount <= 0
        or type(observation.resource_balance) is not int
        or observation.resource_balance < 0
        or observation.control_class != "DONATE"
        or observation.donate_control_visible is not True
        or type(observation.quantity) is not int
        or observation.quantity != 1
    ):
        return DonationDisposition.BLOCKED
    if observation.resource_balance < observation.donation_amount:
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


def donation_postcondition_verified(
    before: DonationObservation,
    after: DonationObservation | None,
    committed_action_count_before: int = 0,
) -> bool:
    """Require one attempt, exact resource spend and a variable-valued tech/reward successor."""

    if (
        not donation_authorizeable(before, committed_action_count_before)
        or not _current_hot_panel(after)
        or after.game_day_id != before.game_day_id
        or after.resource_identity.upper() != before.resource_identity.upper()
        or after.available_attempts != before.available_attempts - 1
        or after.resource_balance != before.resource_balance - before.donation_amount
    ):
        return False
    tech_successor = (
        after.tech_identity != before.tech_identity
        or (
            after.tech_identity == before.tech_identity
            and type(before.tech_points) is int
            and type(after.tech_points) is int
            and after.tech_points > before.tech_points
        )
    )
    reward_successor = (
        isinstance(before.reward_signature, tuple)
        and isinstance(after.reward_signature, tuple)
        and bool(before.reward_signature)
        and len(before.reward_signature) == len(after.reward_signature)
        and after.reward_signature != before.reward_signature
    )
    return tech_successor or reward_successor


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


def _action_resource_identity(action: Mapping[str, Any], *, flow_id: str, game_day_id: str) -> str | None:
    resource = action.get("resource_or_currency")
    if isinstance(resource, str) and resource in ORDINARY_RESOURCES:
        return resource
    if resource not in (None, "ordinary_resource"):
        return None
    try:
        request = json.loads(action.get("policy_request_json"))
    except (TypeError, ValueError):
        return None
    if not isinstance(request, Mapping):
        return None
    observation = request.get("observation")
    preconditions = request.get("semantic_preconditions")
    if not isinstance(observation, Mapping) or not isinstance(preconditions, list):
        return None
    identity = request.get("resource_or_currency")
    amount = observation.get("cost_amount")
    required = {
        f"alliance_donation_game_day={game_day_id}",
        f"alliance_donation_resource={identity}",
        f"alliance_donation_cost={amount}",
        "alliance_donation_quantity=1",
    }
    if (
        not isinstance(identity, str) or identity not in ORDINARY_RESOURCES
        or request.get("task_id") != flow_id or request.get("action_key") != action.get("action_key")
        or request.get("semantic_action") != DONATION_ACTION
        or request.get("action_class") != "spend_or_strategic"
        or request.get("game_day_id") != game_day_id
        or request.get("maximum_cost") != action.get("cost_amount")
        or observation.get("source_state") != ALLIANCE_TECH_SCREEN
        or observation.get("target_identity") != DONATION_TARGET
        or observation.get("expected_postcondition") != DONATION_POSTCONDITION
        or observation.get("consequence") != DONATION_CONSEQUENCE
        or observation.get("cost_type") != "ordinary_resource"
        or amount != action.get("cost_amount") or observation.get("quantity") != 1
        or not required.issubset(set(preconditions))
    ):
        return None
    return identity


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
        resource_identity = _action_resource_identity(
            action, flow_id=flow_id, game_day_id=game_day_id,
        )
        if (
            action.get("semantic_action") != DONATION_ACTION
            or action.get("source_state") != ALLIANCE_TECH_SCREEN
            or action.get("target_identity") != DONATION_TARGET
            or action.get("consequence") != DONATION_CONSEQUENCE
            or action.get("expected_postcondition") != DONATION_POSTCONDITION
            or action.get("game_day_id") != game_day_id
            or action.get("quantity") != 1
            or action.get("cost_type") != "ordinary_resource"
            or resource_identity is None
            or type(action.get("cost_amount")) not in (int, float)
            or type(action.get("cost_amount")) is bool
            or not math.isfinite(float(action["cost_amount"]))
            or action["cost_amount"] <= 0
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


