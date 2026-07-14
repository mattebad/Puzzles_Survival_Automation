"""Offline Craft Weapon contract for Daily nanoweapon objectives.

The contract requires a known free recipe and material state.  Material Production, Inherit,
unknown resources, paid recipes, and long/ambiguous craft states fail closed.  No transport,
runtime registration, or evidence capture is owned here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


NANOWEAPON_SCREEN = "NANOWEAPON"
CRAFT_WEAPON_TAB = "CRAFT_WEAPON"
NANOWEAPON_FREE_TARGET = "nanoweapon-craft-free"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NanoweaponObservation:
    """Semantic evidence for one free, known Craft Weapon recipe."""

    screen_state: str
    selected_nanoweapon: bool
    selected_tab: str
    recipe_name: str
    recipe_known: bool
    materials_known: bool
    materials_available: bool
    craft_mode: str
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    craft_ready: bool = True
    duration_policy_approved: bool = False
    craft_duration_seconds: Optional[int] = None
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    craft_count: Optional[int] = None
    craft_result_visible: bool = False
    result_identity: str = ""
    craft_timer_active: bool = False
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: NanoweaponObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: NanoweaponObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def nanoweapon_authorizeable(observation: NanoweaponObservation) -> bool:
    """Require a known free Craft Weapon recipe with approved duration policy."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and observation.selected_nanoweapon
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and bool(observation.recipe_name.strip())
        and observation.recipe_known
        and observation.materials_known
        and observation.materials_available
        and observation.craft_mode == "CRAFT"
        and observation.target_identity == NANOWEAPON_FREE_TARGET
        and observation.control_class == "CRAFT"
        and observation.craft_ready
        and observation.duration_policy_approved
        and observation.craft_duration_seconds is not None
        and observation.craft_duration_seconds >= 0
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


def nanoweapon_transaction_spec(observation: NanoweaponObservation) -> ActionTransactionSpec:
    if not nanoweapon_authorizeable(observation):
        raise ValueError("Nanoweapon Craft Weapon preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="CRAFT_NANOWEAPON_FREE",
        expected_source_screen=NANOWEAPON_SCREEN,
        subject=observation.recipe_name,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "nanoweapon_screen",
            "craft_weapon_tab",
            "known_recipe_and_materials",
            "approved_craft_duration_policy",
            "bliss_native_target_evidence",
            "explicit_zero_cost",
        ),
        semantic_postconditions=("craft_result_or_timer_change",),
    )


def nanoweapon_postcondition_verified(
    before: NanoweaponObservation,
    after: NanoweaponObservation | None,
) -> bool:
    """Require a same-day positive craft result, count increase, or timer start."""

    if not nanoweapon_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != NANOWEAPON_SCREEN
        or not after.selected_nanoweapon
        or after.selected_tab != CRAFT_WEAPON_TAB
        or after.game_day_id != before.game_day_id
        or not after.recognized
    ):
        return False
    count_increased = (
        before.craft_count is not None
        and after.craft_count is not None
        and after.craft_count > before.craft_count
    )
    result_confirmed = after.craft_result_visible and bool(after.result_identity.strip())
    timer_started = not before.craft_timer_active and after.craft_timer_active
    return bool(count_increased or result_confirmed or timer_started)


def nanoweapon_perform_one_pulse(
    before: NanoweaponObservation,
    after: NanoweaponObservation | None = None,
) -> TaskResult:
    """Return a pure result; Craft Weapon transport remains evidence-gated."""

    if not nanoweapon_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_NANOWEAPON_CRAFT",
            verified=True,
            state=NANOWEAPON_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "CRAFT_NANOWEAPON_FREE is authorized by the offline contract; dispatch remains evidence-gated",
            NANOWEAPON_SCREEN,
        )
    if not nanoweapon_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "NANOWEAPON_POSTCONDITION_NOT_PROVEN",
            state=NANOWEAPON_SCREEN,
        )
    return TaskResult.done(
        "Nanoweapon craft postcondition verified",
        "nanoweapon:free:completed",
        NANOWEAPON_SCREEN,
    )
