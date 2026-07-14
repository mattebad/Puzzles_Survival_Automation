"""Offline free Supply Depot collection contract for Phase E.

This contract does not authorize a collection or inspect a live screen.  It requires explicit
zero-cost and known non-premium reward semantics before a future handler could be promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


SUPPLY_DEPOT_SCREEN = "SUPPLY_DEPOT"
SUPPLY_DEPOT_FREE_TARGET = "supply-depot-free"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SupplyDepotObservation:
    """Semantic evidence for one known free Supply Depot collection."""

    screen_state: str
    selected_supply_depot: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    collection_ready: bool
    reward_kind: str
    known_reward: bool
    premium_reward: bool
    unknown_reward: bool
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: SupplyDepotObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: SupplyDepotObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def supply_depot_authorizeable(observation: SupplyDepotObservation) -> bool:
    """Require an exact free collection with a known, non-premium reward."""

    return bool(
        observation.screen_state == SUPPLY_DEPOT_SCREEN
        and observation.selected_supply_depot
        and observation.target_identity == SUPPLY_DEPOT_FREE_TARGET
        and observation.control_class == "COLLECT"
        and observation.collection_ready
        and observation.known_reward
        and not observation.premium_reward
        and not observation.unknown_reward
        and bool(observation.reward_kind.strip())
        and observation.cost_type == "none"
        and observation.cost_amount == 0
        and observation.quantity == 1
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def supply_depot_transaction_spec(observation: SupplyDepotObservation) -> ActionTransactionSpec:
    if not supply_depot_authorizeable(observation):
        raise ValueError("Supply Depot free collection preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="COLLECT_SUPPLY_DEPOT_FREE",
        expected_source_screen=SUPPLY_DEPOT_SCREEN,
        subject=observation.reward_kind,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "supply_depot_screen",
            "selected_supply_depot",
            "exact_free_collect_target",
            "known_non_premium_reward",
            "bliss_native_target_evidence",
            "explicit_zero_cost",
        ),
        semantic_postconditions=("collection_confirmed_or_target_disappears",),
    )


def supply_depot_postcondition_verified(
    before: SupplyDepotObservation,
    after: SupplyDepotObservation | None,
    *,
    collection_confirmed: bool = False,
) -> bool:
    """Require the same free target to disappear/change or an explicit collection confirmation."""

    if not supply_depot_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != SUPPLY_DEPOT_SCREEN
        or not after.selected_supply_depot
        or after.game_day_id != before.game_day_id
    ):
        return False
    return bool(
        collection_confirmed
        or not after.collection_ready
        or after.target_identity != SUPPLY_DEPOT_FREE_TARGET
        or after.control_class != "COLLECT"
    )


def supply_depot_perform_one_pulse(
    before: SupplyDepotObservation,
    after: SupplyDepotObservation | None = None,
    *,
    collection_confirmed: bool = False,
) -> TaskResult:
    """Return a pure result; no Supply Depot transport is wired here."""

    if not supply_depot_authorizeable(before):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_SUPPLY_DEPOT_FREE_TARGET", verified=True, state=SUPPLY_DEPOT_SCREEN)
    if after is None:
        return TaskResult.progress("COLLECT_SUPPLY_DEPOT_FREE is authorized by the offline contract; dispatch remains evidence-gated", SUPPLY_DEPOT_SCREEN)
    if not supply_depot_postcondition_verified(before, after, collection_confirmed=collection_confirmed):
        return TaskResult(TaskOutcome.FAILED_SAFE, "SUPPLY_DEPOT_POSTCONDITION_NOT_PROVEN", state=SUPPLY_DEPOT_SCREEN)
    return TaskResult.done(
        "Supply Depot free collection postcondition verified",
        f"supply-depot:{before.reward_kind}:collected",
        SUPPLY_DEPOT_SCREEN,
    )
