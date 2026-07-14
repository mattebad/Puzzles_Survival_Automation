"""Offline shared enhancement-family contract.

Gear, Chip, and Module share target, material, quantity, and postcondition semantics while keeping
variant ownership explicit.  This module owns no transport, runtime registration, or live evidence
capture.  It fails closed on ambiguous items, unsafe materials, premium actions, and stale state.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


ENHANCEMENT_SCREEN = "COMMANDER_INFO"
ENHANCEMENT_TARGET = "enhancement-confirm"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
SUPPORTED_VARIANTS = frozenset({"gear", "chip", "module"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EnhancementObservation:
    """Semantic evidence for one exact enhancement variant and material selection."""

    screen_state: str
    selected_tab: str
    selected_item_kind: str
    selected_item_identity: str
    item_equipped: bool
    item_level: int
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    enhance_control_visible: bool
    action_mode: str
    material_identity: str
    material_known: bool
    material_available: bool
    material_star: Optional[int]
    material_quantity: Optional[int]
    auto_select_enabled: bool = False
    cost_type: str = "material"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    material_inventory_count: Optional[int] = None
    enhancement_result_visible: bool = False
    result_identity: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _variant_identity(variant: str) -> str:
    normalized = str(variant).strip().lower()
    if normalized not in SUPPORTED_VARIANTS:
        raise ValueError(f"unsupported enhancement variant: {variant!r}")
    return normalized.upper()


def _target_inside_panel(observation: EnhancementObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: EnhancementObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def enhancement_authorizeable(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> bool:
    """Require exact variant ownership and one-star material enhancement semantics."""

    expected_kind = _variant_identity(variant)
    return bool(
        observation.screen_state == ENHANCEMENT_SCREEN
        and observation.selected_tab == expected_kind
        and observation.selected_item_kind == expected_kind
        and bool(observation.selected_item_identity.strip())
        and observation.item_equipped
        and observation.item_level >= 0
        and observation.target_identity == ENHANCEMENT_TARGET
        and observation.control_class == "ENHANCE"
        and observation.enhance_control_visible
        and observation.action_mode == "ENHANCE"
        and bool(observation.material_identity.strip())
        and observation.material_known
        and observation.material_available
        and observation.material_star == 1
        and observation.material_quantity == 1
        and not observation.auto_select_enabled
        and observation.cost_type == "material"
        and observation.quantity == 1
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def enhancement_transaction_spec(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> ActionTransactionSpec:
    if not enhancement_authorizeable(observation, variant=variant):
        raise ValueError("enhancement preconditions are not positively recognized")
    expected_kind = _variant_identity(variant)
    return ActionTransactionSpec(
        action_kind=f"ENHANCE_{expected_kind}",
        expected_source_screen=ENHANCEMENT_SCREEN,
        subject=observation.selected_item_identity,
        quantity=1,
        resource_or_currency=observation.material_identity,
        maximum_cost=0,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "commander_info_screen",
            f"selected_{variant}_tab",
            "equipped_item",
            "exact_enhance_control",
            "one_star_material_quantity_one",
            "no_auto_select",
            "bliss_native_target_evidence",
        ),
        semantic_postconditions=(f"{variant}_level_or_material_delta",),
    )


def enhancement_postcondition_verified(
    before: EnhancementObservation,
    after: EnhancementObservation | None,
    *,
    variant: str = "gear",
) -> bool:
    """Require a same-day positive change for the same selected enhancement variant."""

    if not enhancement_authorizeable(before, variant=variant) or after is None:
        return False
    expected_kind = _variant_identity(variant)
    if (
        after.screen_state != ENHANCEMENT_SCREEN
        or after.selected_tab != expected_kind
        or after.selected_item_kind != expected_kind
        or after.selected_item_identity != before.selected_item_identity
        or after.game_day_id != before.game_day_id
        or not after.recognized
    ):
        return False
    level_changed = after.item_level > before.item_level
    material_changed = (
        before.material_inventory_count is not None
        and after.material_inventory_count is not None
        and after.material_inventory_count < before.material_inventory_count
    )
    result_confirmed = (
        after.enhancement_result_visible and bool(after.result_identity.strip())
    )
    return bool(level_changed or material_changed or result_confirmed)


def enhancement_perform_one_pulse(
    before: EnhancementObservation,
    after: EnhancementObservation | None = None,
    *,
    variant: str = "gear",
) -> TaskResult:
    """Return a pure result; enhancement transport remains evidence-gated."""

    if not enhancement_authorizeable(before, variant=variant):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_ENHANCEMENT_TARGET",
            verified=True,
            state=ENHANCEMENT_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            f"ENHANCE_{_variant_identity(variant)} is authorized by the offline contract; dispatch remains evidence-gated",
            ENHANCEMENT_SCREEN,
        )
    if not enhancement_postcondition_verified(before, after, variant=variant):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "ENHANCEMENT_POSTCONDITION_NOT_PROVEN",
            state=ENHANCEMENT_SCREEN,
        )
    expected_kind = _variant_identity(variant).lower()
    return TaskResult.done(
        f"{expected_kind} enhancement postcondition verified",
        f"enhancement:{expected_kind}:{before.selected_item_identity}:completed",
        ENHANCEMENT_SCREEN,
    )
