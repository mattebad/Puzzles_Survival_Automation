"""Offline contract for proven Wood, Steel, and Gas gathering variants.

The family recognizes one current-frame resource node and one bounded march specification.  It
produces replay results only; transport, runtime registration, persistence, and scheduler
eligibility remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID
from .world_stamina import WorldStaminaObservation, world_route_authorizeable


GATHERING_SCREEN = "WORLD"
GATHERING_DESTINATION = "RESOURCE_NODE"
GATHERING_TARGET = "gather-resource"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
SUPPORTED_VARIANTS = {
    "wood": ("WOOD", "gather_wood", 30000),
    "steel": ("STEEL", "gather_steel", 6000),
    "gas": ("GAS", "gather_gas", 1500),
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GatheringObservation:
    """Semantic evidence for one exact resource node and available march slot."""

    screen_state: str
    selected_world: bool
    route_identity: str
    resource_variant: str
    resource_name: str
    selected_daily_row: bool
    daily_objective_key: str
    daily_target_quantity: int
    daily_progress_before: int
    node_identity: str
    node_level: Optional[int]
    node_resource_quantity: int
    target_roi: ROI
    panel_bounds: ROI
    action_target_identity: str
    control_class: str
    gather_control_visible: bool
    action_ready: bool
    node_unoccupied: bool
    node_not_targeted: bool
    node_not_already_marched: bool
    march_slot_available: bool
    active_march_count: int
    march_capacity: int
    formation_identity: str
    march_duration_seconds: Optional[int]
    march_duration_budget_seconds: int
    inventory_quantity_before: int = 0
    daily_progress_after: Optional[int] = None
    inventory_quantity_after: Optional[int] = None
    outbound_march_identity: str = ""
    gather_result_identity: str = ""
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _variant_identity(variant: str) -> tuple[str, str, int]:
    normalized = str(variant).strip().lower()
    try:
        return SUPPORTED_VARIANTS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported gathering variant: {variant!r}") from exc


def _target_inside_panel(observation: GatheringObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: GatheringObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def _world_observation(observation: GatheringObservation) -> WorldStaminaObservation:
    return WorldStaminaObservation(
        screen_state=observation.screen_state,
        selected_world=observation.selected_world,
        route_identity=observation.route_identity,
        destination_kind=GATHERING_DESTINATION,
        target_identity=observation.node_identity,
        target_roi=observation.target_roi,
        panel_bounds=observation.panel_bounds,
        resource_name="STAMINA",
        current_resource=0,
        resource_budget=0,
        game_day_id=observation.game_day_id,
        target_provenance=observation.target_provenance,
        source_frame_sha256=observation.source_frame_sha256,
        evidence_refs=observation.evidence_refs,
        overlay_state=observation.overlay_state,
        reset_guard_active=observation.reset_guard_active,
        runtime_profile_id=observation.runtime_profile_id,
        recognized=observation.recognized,
    )


def gathering_authorizeable(
    observation: GatheringObservation,
    *,
    variant: str = "wood",
) -> bool:
    """Require exact resource ownership, unoccupied node, and one free march slot."""

    expected_resource, expected_objective, expected_target = _variant_identity(variant)
    return bool(
        world_route_authorizeable(
            _world_observation(observation),
            destination_kind=GATHERING_DESTINATION,
        )
        and observation.resource_variant == str(variant).strip().lower()
        and observation.resource_name == expected_resource
        and observation.selected_daily_row
        and observation.daily_objective_key == expected_objective
        and observation.daily_target_quantity == expected_target
        and 0 <= observation.daily_progress_before < expected_target
        and bool(observation.node_identity.strip())
        and observation.node_level is not None
        and observation.node_level > 0
        and observation.node_resource_quantity > 0
        and observation.action_target_identity == f"{GATHERING_TARGET}:{expected_resource.lower()}"
        and observation.control_class == "GATHER"
        and observation.gather_control_visible
        and observation.action_ready
        and observation.node_unoccupied
        and observation.node_not_targeted
        and observation.node_not_already_marched
        and observation.march_slot_available
        and observation.active_march_count >= 0
        and observation.march_capacity > 0
        and observation.active_march_count < observation.march_capacity
        and bool(observation.formation_identity.strip())
        and observation.march_duration_seconds is not None
        and observation.march_duration_seconds > 0
        and observation.march_duration_seconds
        <= observation.march_duration_budget_seconds
        and _target_inside_panel(observation)
    )


def gathering_transaction_spec(
    observation: GatheringObservation,
    *,
    variant: str = "wood",
) -> ActionTransactionSpec:
    if not gathering_authorizeable(observation, variant=variant):
        raise ValueError("gathering preconditions are not positively recognized")
    expected_resource, _, _ = _variant_identity(variant)
    return ActionTransactionSpec(
        action_kind="GATHER_RESOURCE",
        expected_source_screen=GATHERING_SCREEN,
        subject=observation.node_identity,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=None,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "selected_daily_resource_row",
            f"exact_{expected_resource.lower()}_node",
            "positive_node_level",
            "node_unoccupied_and_not_targeted",
            "available_march_slot",
            "known_formation_and_duration",
            "current_frame_target_binding",
            "bliss_native_target_evidence",
        ),
        semantic_postconditions=(
            "outbound_march_or_positive_gather_result",
            "daily_progress_or_inventory_increase",
        ),
    )


def gathering_postcondition_verified(
    before: GatheringObservation,
    after: GatheringObservation | None,
    *,
    variant: str = "wood",
) -> bool:
    """Require same-day node binding and positive outbound/result evidence."""

    if not gathering_authorizeable(before, variant=variant) or after is None:
        return False
    expected_resource, expected_objective, expected_target = _variant_identity(variant)
    if (
        after.resource_variant != str(variant).strip().lower()
        or after.resource_name != expected_resource
        or after.daily_objective_key != expected_objective
        or after.node_identity != before.node_identity
        or after.game_day_id != before.game_day_id
        or after.runtime_profile_id != before.runtime_profile_id
        or not _has_bliss_native_source(after)
        or after.successor_state not in {"MARCHES", "GATHERING_RESULT", "DAILY_RECONCILED"}
    ):
        return False
    progress_increased = (
        after.daily_progress_after is not None
        and after.daily_progress_after > before.daily_progress_before
        and after.daily_progress_after <= expected_target
    )
    inventory_increased = (
        after.inventory_quantity_after is not None
        and after.inventory_quantity_after > before.inventory_quantity_before
    )
    outbound_confirmed = (
        after.successor_state == "MARCHES"
        and after.outbound_march_identity == before.node_identity
    )
    result_confirmed = (
        after.successor_state == "GATHERING_RESULT"
        and bool(after.gather_result_identity.strip())
    )
    return bool(
        (progress_increased or inventory_increased)
        and (outbound_confirmed or result_confirmed)
    )


def gathering_perform_one_pulse(
    before: GatheringObservation,
    after: GatheringObservation | None = None,
    *,
    variant: str = "wood",
) -> TaskResult:
    """Return pure replay output; gathering transport remains evidence-gated."""

    if not gathering_authorizeable(before, variant=variant):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_GATHERING_TARGET",
            verified=True,
            state=GATHERING_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "Gathering target recognized; march dispatch remains evidence-gated",
            GATHERING_SCREEN,
        )
    if not gathering_postcondition_verified(before, after, variant=variant):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "GATHERING_POSTCONDITION_NOT_PROVEN",
            state=GATHERING_SCREEN,
        )
    normalized_variant = str(variant).strip().lower()
    return TaskResult.done(
        f"{normalized_variant} gathering postcondition verified",
        f"gathering:{normalized_variant}:{before.node_identity}:completed",
        GATHERING_SCREEN,
    )
