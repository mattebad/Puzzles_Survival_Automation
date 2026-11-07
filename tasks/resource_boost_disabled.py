"""Offline model for disabled Daily resource-building output boosts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


RESOURCE_BUILDING_SCREEN = "RESOURCE_BUILDING"
BOOST_TARGET = "resource-boost-control"
DISABLED_POLICY_REASON = "RESOURCE_BOOST_DISABLED_POLICY"
_RESOURCE_TYPES = {"WOOD", "STEEL", "GAS", "FOOD"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResourceBoostObservation:
    """Semantic resource-building boost evidence with no executable action."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    building_identity: str
    resource_identity: str
    resource_type: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    boost_control_visible: bool
    boost_duration_minutes: Optional[int]
    cost_known: bool
    cost_resource: str
    cost_amount: Optional[int]
    resource_balance_before: Optional[int]
    boost_active_before: bool
    daily_progress_before: int
    boost_active_after: Optional[bool] = None
    boost_duration_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    boost_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: ResourceBoostObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bluestacks_native_source(observation: ResourceBoostObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )


def resource_boost_authorizeable(observation: ResourceBoostObservation) -> bool:
    """Recognize exact building/resource boost evidence; this does not authorize a boost."""

    return bool(
        observation.screen_state == RESOURCE_BUILDING_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "boost_resource_building_output"
        and bool(observation.building_identity.strip())
        and bool(observation.resource_identity.strip())
        and observation.resource_type in _RESOURCE_TYPES
        and observation.target_identity == BOOST_TARGET
        and observation.control_class == "BOOST"
        and observation.boost_control_visible
        and _target_inside_panel(observation)
        and observation.boost_duration_minutes is not None
        and observation.boost_duration_minutes > 0
        and observation.cost_known
        and bool(observation.cost_resource.strip())
        and observation.cost_amount is not None
        and observation.cost_amount > 0
        and observation.resource_balance_before is not None
        and observation.resource_balance_before >= observation.cost_amount
        and not observation.boost_active_before
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bluestacks_native_source(observation)
    )


def resource_boost_postcondition_verified(
    before: ResourceBoostObservation,
    after: ResourceBoostObservation | None,
) -> bool:
    """Verify offline boost-state arithmetic without implying permission to spend."""

    if not resource_boost_authorizeable(before) or after is None:
        return False
    return bool(
        resource_boost_authorizeable(after)
        and after.building_identity == before.building_identity
        and after.resource_identity == before.resource_identity
        and after.resource_type == before.resource_type
        and after.game_day_id == before.game_day_id
        and after.boost_confirmed
        and after.boost_active_after
        and after.boost_duration_after == before.boost_duration_minutes
        and after.daily_progress_after == 1
        and after.successor_state == "BOOST_RECONCILED"
    )


def resource_boost_disabled_dispatch(observation: ResourceBoostObservation) -> TaskResult:
    """Always block resource-building boost dispatch under current policy."""

    if not resource_boost_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_RESOURCE_BOOST_OBSERVATION",
            verified=True,
            state=RESOURCE_BUILDING_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=RESOURCE_BUILDING_SCREEN,
        details={"dispatch_count": 0},
    )


FOOD_FARM_BOOST_SCREEN = "FOOD_FARM_BOOST_PANEL"
FOOD_FARM_ACTIVE_SCREEN = "FOOD_FARM_ACTIVE_BOOST"
FOOD_FARM_RESOURCE_TYPES = frozenset({"FOOD", "WOOD", "STEEL", "GAS"})
_FARM_ID_RE = re.compile(r"^home\.building\.farm\.\d{2}$")


class FoodFarmBoostChoice(str, Enum):
    OWNED_ITEM = "owned_item"
    DIAMONDS = "diamonds"
    ALREADY_ACTIVE = "already_active"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class FoodFarmBoostObservation:
    """Current-frame Food Farm boost facts; no fact is inferred from panel art."""

    screen_state: str
    farm_identity: str
    resource_type: str
    boost_active: bool
    active_remaining_seconds: Optional[int]
    option_duration_seconds: Optional[int]
    option_item_name: Optional[str]
    option_item_cost: Optional[int]
    option_item_visible: bool
    inventory_item_name: Optional[str]
    inventory_item_count: Optional[int]
    inventory_observed: bool
    diamond_option_visible: bool
    diamond_item_name: Optional[str]
    diamond_duration_seconds: Optional[int]
    diamond_cost: Optional[int]
    diamond_balance: Optional[int]
    diamond_offer_actionable: bool
    purchase_prompt_visible: bool = False
    prompt_item_name: Optional[str] = None
    prompt_duration_seconds: Optional[int] = None
    prompt_cost: Optional[int] = None
    prompt_balance: Optional[int] = None
    confirmation_required: bool = False
    confirmation_control_identity: Optional[str] = None
    confirmation_control_visible: bool = False
    confirmation_binding_current: bool = False
    overlay_state: str = "none"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True
    boost_options_visible: bool = True


@dataclass(frozen=True)
class FoodFarmBoostDecision:
    choice: FoodFarmBoostChoice
    reason: str
    item_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    cost: Optional[int] = None
    currency: Optional[str] = None


def _food_farm_source_valid(observation: FoodFarmBoostObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.recognized
        and _FARM_ID_RE.fullmatch(observation.farm_identity or "")
        and observation.resource_type == "FOOD"
        and observation.overlay_state in {"none", "none_observed"}
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
    )


def _exact_name(value: Optional[str]) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _positive_int(value: Optional[int]) -> bool:
    return type(value) is int and value > 0


def food_farm_boost_decision(
    observation: FoodFarmBoostObservation,
) -> FoodFarmBoostDecision:
    """Choose one fresh owned item first, else one exact current diamond offer."""

    if not _food_farm_source_valid(observation):
        return FoodFarmBoostDecision(FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_SOURCE_UNKNOWN")
    if observation.boost_active:
        if _positive_int(observation.active_remaining_seconds):
            return FoodFarmBoostDecision(
                FoodFarmBoostChoice.ALREADY_ACTIVE,
                "FOOD_FARM_BOOST_ALREADY_ACTIVE",
                duration_seconds=observation.active_remaining_seconds,
            )
        return FoodFarmBoostDecision(
            FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_ACTIVE_TIMER_UNKNOWN"
        )
    if observation.screen_state != FOOD_FARM_BOOST_SCREEN or not observation.boost_options_visible:
        return FoodFarmBoostDecision(FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_BOOST_OPTIONS_UNKNOWN")

    option_name = _exact_name(observation.option_item_name)
    inventory_name = _exact_name(observation.inventory_item_name)
    exact_item_identity = bool(option_name and option_name == inventory_name)
    exact_item_duration = _positive_int(observation.option_duration_seconds)
    exact_item_action_cost = type(observation.option_item_cost) is int and observation.option_item_cost == 1
    if observation.inventory_observed:
        if (
            observation.option_item_visible
            and exact_item_identity
            and exact_item_duration
            and exact_item_action_cost
            and type(observation.inventory_item_count) is int
            and observation.inventory_item_count >= 0
        ):
            if observation.inventory_item_count >= 1:
                return FoodFarmBoostDecision(
                    FoodFarmBoostChoice.OWNED_ITEM,
                    "EXACT_OWNED_FOOD_FARM_ITEM_PREFERRED",
                    item_name=observation.inventory_item_name,
                    duration_seconds=observation.option_duration_seconds,
                    cost=1,
                    currency="owned_item",
                )
        else:
            return FoodFarmBoostDecision(
                FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_ITEM_IDENTITY_OR_COUNT_UNKNOWN"
            )
    else:
        return FoodFarmBoostDecision(
            FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_INVENTORY_NOT_OBSERVED"
        )

    # A known zero count is the only state that permits considering diamonds.
    # The displayed item-option ×1 is per-action cost, never an inventory count.
    if observation.inventory_item_count != 0:
        return FoodFarmBoostDecision(FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_ITEM_COUNT_UNKNOWN")
    exact_offer = bool(
        observation.diamond_option_visible
        and observation.diamond_offer_actionable
        and _exact_name(observation.diamond_item_name)
        and _positive_int(observation.diamond_duration_seconds)
        and _positive_int(observation.diamond_cost)
        and type(observation.diamond_balance) is int
        and observation.diamond_balance >= observation.diamond_cost
    )
    if not exact_offer:
        return FoodFarmBoostDecision(FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_DIAMOND_OFFER_UNKNOWN")
    if observation.purchase_prompt_visible:
        if (
            _exact_name(observation.prompt_item_name) != _exact_name(observation.diamond_item_name)
            or observation.prompt_duration_seconds != observation.diamond_duration_seconds
            or observation.prompt_cost != observation.diamond_cost
            or observation.prompt_balance != observation.diamond_balance
        ):
            return FoodFarmBoostDecision(
                FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_DIAMOND_PROMPT_CHANGED"
            )
        return FoodFarmBoostDecision(
            FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_DIAMOND_CONFIRMATION_NOT_AUTHORIZED"
        )
    if observation.confirmation_required:
        return FoodFarmBoostDecision(
            FoodFarmBoostChoice.BLOCKED, "FOOD_FARM_CONFIRMATION_CONTROL_UNKNOWN"
        )
    return FoodFarmBoostDecision(
        FoodFarmBoostChoice.DIAMONDS,
        "EXACT_CURRENT_DIAMOND_OPTION",
        item_name=observation.diamond_item_name,
        duration_seconds=observation.diamond_duration_seconds,
        cost=observation.diamond_cost,
        currency="diamonds",
    )


def food_farm_boost_postcondition_verified(
    before: FoodFarmBoostObservation,
    after: FoodFarmBoostObservation | None,
) -> bool:
    """Require the same mapped Farm's observed positive active timer successor."""

    return bool(
        after is not None
        and _food_farm_source_valid(before)
        and _food_farm_source_valid(after)
        and before.farm_identity == after.farm_identity
        and before.resource_type == after.resource_type == "FOOD"
        and not before.boost_active
        and after.boost_active
        and _positive_int(after.active_remaining_seconds)
        and after.screen_state in {FOOD_FARM_ACTIVE_SCREEN, FOOD_FARM_BOOST_SCREEN}
        and not after.boost_options_visible
    )


def food_farm_collection_effect(
    balances_before: Mapping[str, object],
    balances_after: Mapping[str, object],
    *,
    home_successor_verified: bool,
) -> tuple[bool, dict[str, int], str]:
    """Account for the broad Farm tap only from exact resource balances + Home."""

    if type(home_successor_verified) is not bool or not home_successor_verified:
        return False, {}, "FOOD_FARM_COLLECTION_SUCCESSOR_UNKNOWN"
    if set(balances_before) != FOOD_FARM_RESOURCE_TYPES or set(balances_after) != FOOD_FARM_RESOURCE_TYPES:
        return False, {}, "FOOD_FARM_COLLECTION_BALANCES_INCOMPLETE"
    deltas: dict[str, int] = {}
    for resource in FOOD_FARM_RESOURCE_TYPES:
        before = balances_before[resource]
        after = balances_after[resource]
        if type(before) is not int or type(after) is not int or before < 0 or after < before:
            return False, {}, "FOOD_FARM_COLLECTION_BALANCE_UNKNOWN_OR_CHANGED"
        deltas[resource] = after - before
    if sum(delta > 0 for delta in deltas.values()) < 2:
        return False, deltas, "FOOD_FARM_COLLECTION_EFFECT_NOT_BROADLY_RECONCILED"
    return True, deltas, "FOOD_FARM_COLLECTION_ACCOUNTED"


def food_farm_boost_daily_action_key(
    *,
    runtime_scope: str,
    account_id: str,
    server_id: str,
    reset_id: str,
    phase: str,
    collection_occurrence_id: Optional[str] = None,
) -> str:
    """Build the boost's reset key or a separate ready-collection occurrence key."""

    if phase not in {"collection", "boost"}:
        raise ValueError("Food Farm action phase must be collection or boost")
    if phase == "collection" and (
        type(collection_occurrence_id) is not str
        or not collection_occurrence_id
        or collection_occurrence_id != collection_occurrence_id.strip()
    ):
        raise ValueError("a concrete collection occurrence identity is required")
    if phase == "boost" and collection_occurrence_id is not None:
        raise ValueError("the reset-scoped boost key cannot include a collection occurrence")
    identity = {
        "runtime_scope": runtime_scope,
        "account_id": account_id,
        "server_id": server_id,
        "reset_id": reset_id,
        "task_id": "food_farm_output_boost",
        "phase": phase,
        "collection_occurrence_id": collection_occurrence_id,
    }
    for name, value in identity.items():
        if value is None and name == "collection_occurrence_id":
            continue
        if (
            type(value) is not str
            or not value
            or value != value.strip()
            or any(character.isspace() for character in value)
        ):
            raise ValueError(f"{name} must be a non-empty normalized identity")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    scope = "occurrence" if phase == "collection" else "daily"
    return f"food-farm-output-boost:{scope}:{phase}:{hashlib.sha256(encoded).hexdigest()}"


def food_farm_canonical_action_state(action: Mapping[str, object] | None) -> str:
    """Interpret an existing canonical action row without a parallel persistence layer."""

    if action is None:
        return "ready"
    status = action.get("final_status")
    if status == "confirmed":
        return "complete"
    if status == "cancelled":
        return "ready"
    if status in {"prepared", "input_sent", "unresolved"}:
        return "reconciliation_required"
    return "unknown"
