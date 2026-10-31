"""Offline shared enhancement-family contract.

Gear, Chip, and Module share target, material, quantity, and postcondition semantics while keeping
variant ownership explicit.  This module owns no transport, runtime registration, or live evidence
capture.  It fails closed on ambiguous items, unsafe materials, premium actions, and stale state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult


ENHANCEMENT_SCREEN = "COMMANDER_INFO"
ENHANCEMENT_TARGET = "enhancement-confirm"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
BLUESTACKS_NATIVE_TARGET_PROVENANCE = "bluestacks-native"
BLUESTACKS_RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
LEGACY_BLISS_RUNTIME_PROFILE_ID = "pns-blissos-poc-virgl-800x1280-v1"
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
    runtime_profile_id: str = BLUESTACKS_RUNTIME_PROFILE_ID
    recognized: bool = True
    result_spatially_associated: bool = False
    # Committed EXP; a selected material's displayed preview is separate.
    item_exp_current: Optional[int] = None
    item_exp_required: Optional[int] = None
    # Each visible populated cell: (row-major slot, star count, selected, owned).
    material_slot_facts: tuple[tuple[int, int, int, int], ...] = ()
    item_exp_preview: int | None = None
    selection_baseline_frame_sha256: str | None = None
    selection_baseline_evidence_ref: str | None = None


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
        and observation.runtime_profile_id == LEGACY_BLISS_RUNTIME_PROFILE_ID
    )


def _has_bluestacks_native_source(observation: EnhancementObservation) -> bool:
    """Require independently retained native BlueStacks frame provenance.

    Synthetic fixture references intentionally remain valid for the Bliss-only
    contract, but can never authorize the BlueStacks adapter.
    """

    refs = tuple(str(ref).strip() for ref in observation.evidence_refs)
    source_hash = str(observation.source_frame_sha256 or "")
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and observation.runtime_profile_id == BLUESTACKS_RUNTIME_PROFILE_ID
        and _SHA256_RE.fullmatch(source_hash)
        and source_hash != "0" * 64
        and refs
        and all(
            ref
            and "local-reference" not in ref.lower()
            and not ref.lower().startswith("synthetic:")
            and Path(ref).suffix.lower() in {".png", ".jpg", ".jpeg"}
            for ref in refs
        )
    )


def _enhancement_semantics_authorizeable(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> bool:
    """Require exact variant ownership and one-star material semantics."""

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
        and observation.cost_amount in (None, 0, 0.0)
        and observation.quantity == 1
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
    )


def enhancement_authorizeable(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> bool:
    """Authorize the existing Bliss-native offline contract only."""

    return bool(
        _enhancement_semantics_authorizeable(observation, variant=variant)
        and _has_bliss_native_source(observation)
    )


def enhancement_bluestacks_authorizeable(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> bool:
    """Authorize one exact native BlueStacks enhancement target.

    This separate entry point prevents BlueStacks provenance from weakening
    Bliss behavior or making synthetic fixture observations dispatchable.
    """

    expected_kind = _variant_identity(variant)
    material = observation.material_identity.strip().lower()
    return bool(
        _enhancement_semantics_authorizeable(observation, variant=variant)
        and _has_bluestacks_native_source(observation)
        and material == f"{variant.lower()}-material-one-star"
        and observation.selected_tab == expected_kind
        and observation.selected_item_kind == expected_kind
        and _native_exp_valid(observation)
        and _native_selection_baseline_valid(observation)
        and _native_selection_valid(observation, selected=1)
    )


def _native_exp_valid(observation: EnhancementObservation) -> bool:
    return bool(type(observation.item_level) is int and observation.item_level >= 0
        and type(observation.item_exp_current) is int
        and type(observation.item_exp_required) is int
        and 0 <= observation.item_exp_current < observation.item_exp_required)


def _native_selection_baseline_valid(observation: EnhancementObservation) -> bool:
    """Require a distinct baseline and the actual same-level selection preview."""

    refs = observation.evidence_refs
    digest = observation.selection_baseline_frame_sha256
    reference = observation.selection_baseline_evidence_ref
    return bool(
        type(observation.item_exp_preview) is int
        and observation.item_exp_current < observation.item_exp_preview < observation.item_exp_required
        and type(digest) is str and _SHA256_RE.fullmatch(digest)
        and digest != "0" * 64 and digest != observation.source_frame_sha256
        and type(reference) is str and reference and reference == reference.strip()
        and isinstance(refs, tuple) and len(refs) >= 4
        and all(type(ref) is str for ref in refs[:4])
        and len(set(refs[:4])) == 4
        # The adapter retains current, equipped-modal, baseline, quantity proof.
        and refs[2] == reference
    )


def _native_slots(observation: EnhancementObservation) -> dict[int, tuple[int, int, int]] | None:
    cells = observation.material_slot_facts
    if not isinstance(cells, tuple) or not cells or len(cells) > 36:
        return None
    result = {}
    for cell in cells:
        if (not isinstance(cell, tuple) or len(cell) != 4
                or any(type(value) is not int for value in cell)):
            return None
        slot, stars, selected, owned = cell
        if slot < 0 or slot in result or not 0 <= stars <= 9 or not 0 <= selected <= owned:
            return None
        result[slot] = (stars, selected, owned)
    return result


def _native_selection_valid(observation: EnhancementObservation, *, selected: int) -> bool:
    cells = _native_slots(observation)
    if cells is None:
        return False
    one_star = [value for value in cells.values() if value[0] == 1]
    return bool(len(one_star) == 1 and one_star[0][1] == selected
        and one_star[0][2] >= selected
        and type(observation.material_inventory_count) is int
        and type(observation.material_quantity) is int and type(observation.quantity) is int
        and observation.material_inventory_count == one_star[0][2]
        and observation.material_quantity == selected and observation.quantity == selected
        and all(value[1] == 0 for value in cells.values() if value[0] != 1))


def enhancement_transaction_spec(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> ActionTransactionSpec:
    if not enhancement_authorizeable(observation, variant=variant):
        raise ValueError("enhancement preconditions are not positively recognized")
    return _enhancement_transaction_spec(
        observation, variant=variant, provenance="bliss"
    )


def enhancement_bluestacks_transaction_spec(
    observation: EnhancementObservation,
    *,
    variant: str = "gear",
) -> ActionTransactionSpec:
    if not enhancement_bluestacks_authorizeable(observation, variant=variant):
        raise ValueError(
            "native BlueStacks enhancement preconditions are not positively recognized"
        )
    return _enhancement_transaction_spec(
        observation, variant=variant, provenance="bluestacks"
    )


def _enhancement_transaction_spec(
    observation: EnhancementObservation,
    *,
    variant: str,
    provenance: str,
) -> ActionTransactionSpec:
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
            f"{provenance}_native_target_evidence",
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
    return _enhancement_postcondition_verified(before, after, variant=variant)


def _enhancement_postcondition_verified(
    before: EnhancementObservation,
    after: EnhancementObservation,
    *,
    variant: str,
) -> bool:
    """Compare a recognized successor without imposing its pre-dispatch target."""

    if after is None:
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
        after.enhancement_result_visible
        and after.result_identity.strip() == before.selected_item_identity.strip()
        and after.result_spatially_associated
    )
    return bool(level_changed or material_changed or result_confirmed)


def enhancement_bluestacks_postcondition_verified(
    before: EnhancementObservation,
    after: EnhancementObservation | None,
    *,
    variant: str = "gear",
) -> bool:
    """Verify a same-category BlueStacks successor after one dispatch."""

    if (
        not enhancement_bluestacks_authorizeable(before, variant=variant)
        or after is None
        or after.target_provenance != BLUESTACKS_NATIVE_TARGET_PROVENANCE
        or after.runtime_profile_id != BLUESTACKS_RUNTIME_PROFILE_ID
        or not _has_bluestacks_native_source(after)
        or not _native_exp_valid(after)
        or not _native_selection_valid(after, selected=0)
        or after.item_exp_preview is not None
        or after.selection_baseline_frame_sha256 is not None
        or after.selection_baseline_evidence_ref is not None
        or after.material_identity != before.material_identity
        or after.material_known is not True or after.material_star != 1
        or after.overlay_state not in {"none", "none_observed"}
        or after.source_frame_sha256 == before.source_frame_sha256
    ):
        return False
    previous, current = _native_slots(before), _native_slots(after)
    if previous is None or current is None or previous.keys() != current.keys():
        return False
    for slot, (stars, _selected, owned) in previous.items():
        next_stars, _next_selected, next_owned = current[slot]
        if next_stars != stars or next_owned != owned - (1 if stars == 1 else 0):
            return False
    # Only same-level preview semantics have native proof. A level change must
    # not bypass the committed EXP check merely because inventory decreased.
    progress = (after.item_level == before.item_level
        and after.item_exp_required == before.item_exp_required
        and after.item_exp_current == before.item_exp_preview
        and after.item_exp_current > before.item_exp_current)
    return bool(progress and _enhancement_postcondition_verified(before, after, variant=variant))


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
