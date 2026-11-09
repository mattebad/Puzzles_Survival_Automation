"""Offline Normal Craft action semantics.

One affordable Normal Craft start consumes the fixed 100 nano parts and starts
one 43200-second craft. Completed claims and active observations are independent
of a new-start quote. Exclusive Craft and ambiguous states fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


NANOWEAPON_SCREEN = "NANOWEAPON"
CRAFT_WEAPON_TAB = "CRAFT_WEAPON"
NANOWEAPON_NORMAL_TARGET = "nanoweapon-craft-normal"
NANO_PARTS_REQUIRED = 100
NORMAL_CRAFT_DURATION_SECONDS = 43200
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NanoweaponObservation:
    """Semantic evidence for one exact Normal Craft Nanoweapon recipe."""

    screen_state: str
    selected_nanoweapon: bool
    selected_tab: str
    recipe_name: str
    recipe_known: bool
    materials_known: bool
    materials_available: bool
    nano_parts: Optional[int]
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
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True
    active_craft_count: Optional[int] = None
    craft_enabled: bool = False
    starts_this_reset: Optional[int] = None
    claim_visible: bool = False
    recipe_selection_mode: str = "unknown"
    craft_timer_seconds_remaining: Optional[int] = None
    prior_material_production_reconciled: bool = False


def _target_inside_panel(observation: NanoweaponObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_native_source(observation: NanoweaponObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )


def nanoweapon_authorizeable(observation: NanoweaponObservation) -> bool:
    """Require affordable fixed Normal Craft, reset and empty-slot boundaries."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and type(observation.selected_nanoweapon) is bool
        and observation.selected_nanoweapon
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and type(observation.recipe_name) is str
        and bool(observation.recipe_name.strip())
        and type(observation.recipe_known) is bool
        and observation.recipe_known
        and type(observation.materials_known) is bool
        and observation.materials_known
        and type(observation.materials_available) is bool
        and observation.materials_available
        and (observation.nano_parts is None or (type(observation.nano_parts) is int and observation.nano_parts >= NANO_PARTS_REQUIRED))
        and observation.prior_material_production_reconciled is True
        and observation.craft_mode == "CRAFT"
        and observation.recipe_selection_mode == "normal_recipe"
        and observation.target_identity == NANOWEAPON_NORMAL_TARGET
        and observation.control_class == "CRAFT"
        and type(observation.craft_ready) is bool
        and observation.craft_ready
        and type(observation.craft_enabled) is bool
        and observation.craft_enabled
        and (observation.quantity is None or (type(observation.quantity) is int and observation.quantity == 1))
        and (observation.craft_duration_seconds is None or (
            type(observation.craft_duration_seconds) is int and observation.craft_duration_seconds == NORMAL_CRAFT_DURATION_SECONDS
        ))
        and observation.cost_type == "NANO_PARTS"
        and type(observation.cost_amount) is int
        and observation.cost_amount == NANO_PARTS_REQUIRED
        and type(observation.active_craft_count) is int
        and observation.active_craft_count == 0
        and type(observation.starts_this_reset) is int
        and observation.starts_this_reset == 0
        and type(observation.claim_visible) is bool
        and not observation.claim_visible
        and type(observation.craft_timer_active) is bool
        and not observation.craft_timer_active
        and type(observation.craft_timer_seconds_remaining) is int
        and observation.craft_timer_seconds_remaining == 0
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and type(observation.game_day_id) is str
        and bool(observation.game_day_id)
        and type(observation.reset_guard_active) is bool
        and not observation.reset_guard_active
        and type(observation.recognized) is bool
        and observation.recognized
        and _has_native_source(observation)
    )


def nanoweapon_active_craft_authorizeable(observation: NanoweaponObservation) -> bool:
    """Recognize a single existing Normal craft without granting restart authority."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and observation.selected_nanoweapon is True
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and observation.recipe_known is True
        and observation.recipe_selection_mode == "normal_recipe"
        and observation.craft_mode == "CRAFT"
        and observation.target_identity == NANOWEAPON_NORMAL_TARGET
        and observation.prior_material_production_reconciled is True
        and type(observation.active_craft_count) is int
        and observation.active_craft_count == 1
        and type(observation.starts_this_reset) is int
        and observation.starts_this_reset in {0, 1}
        and observation.craft_timer_active is True
        and type(observation.craft_timer_seconds_remaining) is int
        and 0 < observation.craft_timer_seconds_remaining <= NORMAL_CRAFT_DURATION_SECONDS
        and type(observation.game_day_id) is str
        and bool(observation.game_day_id)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.recognized is True
        and _target_inside_panel(observation)
        and _has_native_source(observation)
    )


def nanoweapon_known_material_shortage(observation: NanoweaponObservation) -> bool:
    """Recognize exact Normal Craft semantics and a known sub-100 current balance."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and observation.selected_nanoweapon is True
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and observation.recipe_known is True
        and observation.recipe_selection_mode == "normal_recipe"
        and observation.craft_mode == "CRAFT"
        and observation.target_identity == NANOWEAPON_NORMAL_TARGET
        and observation.prior_material_production_reconciled is True
        and type(observation.materials_known) is bool
        and observation.materials_known
        and observation.materials_available is False
        and observation.craft_ready is False
        and observation.craft_enabled is False
        and (observation.nano_parts is None or (type(observation.nano_parts) is int and 0 <= observation.nano_parts < NANO_PARTS_REQUIRED))
        and type(observation.active_craft_count) is int
        and observation.active_craft_count == 0
        and type(observation.starts_this_reset) is int
        and observation.starts_this_reset == 0
        and observation.cost_type == "NANO_PARTS"
        and type(observation.cost_amount) is int
        and observation.cost_amount == NANO_PARTS_REQUIRED
        and type(observation.craft_timer_seconds_remaining) is int
        and observation.craft_timer_seconds_remaining == 0
        and observation.claim_visible is False
        and type(observation.game_day_id) is str
        and bool(observation.game_day_id)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.recognized is True
        and _target_inside_panel(observation)
        and _has_native_source(observation)
    )


def nanoweapon_current_reset_start_known(observation: NanoweaponObservation) -> bool:
    """Recognize the canonical one-start guard without authorizing another start."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and observation.selected_nanoweapon is True
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and observation.recipe_known is True
        and observation.recipe_selection_mode == "normal_recipe"
        and observation.craft_mode == "CRAFT"
        and observation.prior_material_production_reconciled is True
        and type(observation.active_craft_count) is int
        and observation.active_craft_count == 0
        and type(observation.starts_this_reset) is int
        and observation.starts_this_reset == 1
        and type(observation.game_day_id) is str
        and bool(observation.game_day_id)
        and observation.overlay_state in {"none", "none_observed"}
        and observation.recognized is True
        and _has_native_source(observation)
    )


def nanoweapon_claim_authorizeable(observation: NanoweaponObservation) -> bool:

    """Require one positively recognized completed normal craft and its Claim."""

    return bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and type(observation.selected_nanoweapon) is bool
        and observation.selected_nanoweapon
        and observation.selected_tab == CRAFT_WEAPON_TAB
        and observation.prior_material_production_reconciled is True
        and observation.craft_mode == "CRAFT"
        and observation.recipe_known is True
        and type(observation.recipe_name) is str
        and bool(observation.recipe_name.strip())
        and observation.recipe_selection_mode == "normal_recipe"
        and observation.target_identity == NANOWEAPON_NORMAL_TARGET
        and observation.craft_result_visible is True
        and type(observation.result_identity) is str
        and observation.result_identity.startswith("craft-instance:")
        and bool(observation.result_identity[len("craft-instance:"):].strip())
        and observation.claim_visible is True
        and type(observation.active_craft_count) is int
        and observation.active_craft_count == 0
        and type(observation.craft_count) is int
        and observation.craft_count == 1
        and observation.craft_timer_active is False
        and type(observation.craft_timer_seconds_remaining) is int
        and observation.craft_timer_seconds_remaining == 0
        and type(observation.game_day_id) is str
        and bool(observation.game_day_id)
        and observation.overlay_state in {"none", "none_observed"}
        and type(observation.recognized) is bool
        and observation.recognized
        and _has_native_source(observation)
    )


def nanoweapon_transaction_spec(observation: NanoweaponObservation) -> ActionTransactionSpec:
    if not nanoweapon_authorizeable(observation):
        raise ValueError("Nanoweapon Normal Craft preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="START_NORMAL_NANOWEAPON_CRAFT",
        expected_source_screen=NANOWEAPON_SCREEN,
        subject=NANOWEAPON_NORMAL_TARGET,
        quantity=1,
        resource_or_currency="NANO_PARTS",
        maximum_cost=NANO_PARTS_REQUIRED,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "product_id=nanoweapon_normal_craft",
            "product_revision=nanoweapon_normal_craft-v2",
            "effect_ordinal=1",
            "prior_material_production_reconciled=1",
            "normal_craft_tab",
            "recipe_selection=normal",
            f"game_day_id={observation.game_day_id}",
            "materials_affordable=1",
            "cost=NANO_PARTS:100",
            "duration_seconds=43200",
            "active_craft_count=0",
            "current_reset_start_ordinal=1",
            "exclusive_craft=0",
            "rotating_display=0",
        ),
        semantic_postconditions=("NANOWEAPON_NORMAL_CRAFT_ACTIVE",),
    )


def nanoweapon_claim_transaction_spec(observation: NanoweaponObservation) -> ActionTransactionSpec:
    if not nanoweapon_claim_authorizeable(observation):
        raise ValueError("completed Normal Craft claim is not positively recognized")
    return ActionTransactionSpec(
        action_kind="CLAIM_NANOWEAPON_COMPLETED",
        expected_source_screen=NANOWEAPON_SCREEN,
        subject="nanoweapon-completed-claim",
        quantity=1,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(
            "product_id=nanoweapon_normal_craft",
            "product_revision=nanoweapon_normal_craft-v2",
            "effect_ordinal=1",
            f"game_day_id={observation.game_day_id}",
            "prior_material_production_reconciled=1",
            "normal_craft_tab",
            "completed_normal_craft=1",
            f"craft_instance={observation.result_identity}",
            "active_craft_count=0",
            "claim_visible=1",
            "cost=none:0",
        ),
        semantic_postconditions=("NANOWEAPON_CRAFT_CLAIMED",),
    )

def nanoweapon_claim_postcondition_verified(
    before: NanoweaponObservation,
    after: NanoweaponObservation | None,
) -> bool:

    """Claim succeeds only when the Normal Craft result and exact Claim disappear."""

    return bool(
        after is not None
        and nanoweapon_claim_authorizeable(before)
        and after.screen_state == NANOWEAPON_SCREEN
        and after.prior_material_production_reconciled is True
        and after.selected_nanoweapon is True
        and after.selected_tab == CRAFT_WEAPON_TAB
        and after.recipe_known is True
        and after.recipe_name == before.recipe_name
        and after.recipe_selection_mode == "normal_recipe"
        and after.craft_mode == "CRAFT"
        and after.target_identity == NANOWEAPON_NORMAL_TARGET
        and after.craft_result_visible is False
        and after.result_identity == ""
        and after.claim_visible is False
        and type(after.active_craft_count) is int
        and after.active_craft_count == 0
        and after.craft_timer_active is False
        and type(after.craft_timer_seconds_remaining) is int
        and after.craft_timer_seconds_remaining == 0
        and type(after.starts_this_reset) is int
        and after.starts_this_reset == before.starts_this_reset
        and after.game_day_id == before.game_day_id
        and after.overlay_state in {"none", "none_observed"}
        and after.recognized is True
        and _has_native_source(after)
        and after.source_frame_sha256 != before.source_frame_sha256
    )


def nanoweapon_postcondition_verified(
    before: NanoweaponObservation,
    after: NanoweaponObservation | None,
) -> bool:
    """Require exact parts consumption and a current one-slot craft successor."""

    if not nanoweapon_authorizeable(before) or after is None:
        return False
    return bool(
        after.screen_state == NANOWEAPON_SCREEN
        and after.selected_nanoweapon is True
        and after.selected_tab == CRAFT_WEAPON_TAB
        and after.prior_material_production_reconciled is True
        and after.recipe_known is True
        and after.recipe_name == before.recipe_name
        and after.recipe_selection_mode == "normal_recipe"
        and after.craft_mode == "CRAFT"
        and type(after.active_craft_count) is int
        and type(after.starts_this_reset) is int
        and after.target_identity == NANOWEAPON_NORMAL_TARGET
        and (before.nano_parts is None or after.nano_parts is None or (
            type(after.nano_parts) is int and after.nano_parts == before.nano_parts - NANO_PARTS_REQUIRED
        ))
        and after.active_craft_count == 1
        and after.craft_timer_active is True
        and type(after.craft_timer_seconds_remaining) is int
        and 0 < after.craft_timer_seconds_remaining <= NORMAL_CRAFT_DURATION_SECONDS
        and after.craft_result_visible is False
        and after.claim_visible is False
        and after.starts_this_reset == 1
        and after.game_day_id == before.game_day_id
        and after.overlay_state in {"none", "none_observed"}
        and after.recognized is True
        and _has_native_source(after)
        and after.source_frame_sha256 != before.source_frame_sha256
    )

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
            "CRAFT_NANOWEAPON_NORMAL is authorized by the offline contract; dispatch remains evidence-gated",
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
        "nanoweapon:normal:completed",
        NANOWEAPON_SCREEN,
    )
def nanoweapon_active_craft_due_at(now_utc: float, timer_seconds_remaining: int) -> float:
    if (
        type(now_utc) not in (int, float)
        or not math.isfinite(float(now_utc))
        or now_utc < 0
    ):
        raise ValueError("Nanoweapon timer observation time must be a finite UTC epoch")
    if (
        type(timer_seconds_remaining) is not int
        or not 0 < timer_seconds_remaining <= NORMAL_CRAFT_DURATION_SECONDS
    ):
        raise ValueError("Nanoweapon active timer must be a positive bounded integer")
    return float(now_utc) + timer_seconds_remaining


def nanoweapon_shortage_due_at(
    now_utc: float,
    observation_interval_seconds: int = 300,
) -> float:
    if (
        type(now_utc) not in (int, float)
        or not math.isfinite(float(now_utc))
        or now_utc < 0
        or type(observation_interval_seconds) is not int
        or observation_interval_seconds < 1
    ):
        raise ValueError("Nanoweapon shortage observation cadence is invalid")
    return float(now_utc) + observation_interval_seconds


def nanoweapon_transition(observation: NanoweaponObservation) -> TaskResult:
    """Select claim, exact craft start, or a known non-start state without transport."""

    if nanoweapon_claim_authorizeable(observation):
        return TaskResult.progress(
            "A completed Normal Craft requires one verified claim before any new start",
            NANOWEAPON_SCREEN,
            next_action="claim_completed_normal_craft",
            craft_transport_calls=0,
        )
    if nanoweapon_active_craft_authorizeable(observation):
        return TaskResult(
            TaskOutcome.RETRY,
            "NANOWEAPON_ACTIVE_CRAFT_DEFERRED",
            verified=True,
            state="normal_craft_active",
            details={
                "next_action": "observe_active_timer_only",
                "timer_seconds_remaining": observation.craft_timer_seconds_remaining,
                "duration_seconds": NORMAL_CRAFT_DURATION_SECONDS,
                "craft_transport_calls": 0,
            },
        )
    if nanoweapon_known_material_shortage(observation):
        return TaskResult(
            TaskOutcome.RETRY,
            "NANOWEAPON_KNOWN_MATERIAL_SHORTAGE",
            verified=True,
            state="normal_craft_idle",
            details={
                "next_action": "observe_after_configured_interval",
                "nano_parts_balance": observation.nano_parts,
                "craft_transport_calls": 0,
            },
        )
    if nanoweapon_current_reset_start_known(observation):
        return TaskResult(
            TaskOutcome.RETRY,
            "NANOWEAPON_RESET_START_ALREADY_USED",
            verified=True,
            state="normal_craft_idle",
            details={
                "next_action": "observe_next_reset",
                "craft_transport_calls": 0,
            },
        )
    if nanoweapon_authorizeable(observation):
        return TaskResult.progress(
            "One exact Normal Craft start is eligible",
            NANOWEAPON_SCREEN,
            next_action="start_one_normal_craft",
            craft_transport_calls=0,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        "NANOWEAPON_STATE_NOT_POSITIVELY_RECOGNIZED",
        verified=True,
        state=NANOWEAPON_SCREEN,
    )


def nanoweapon_replay(
    before: NanoweaponObservation,
    *,
    claim_successor: NanoweaponObservation | None = None,
    craft_successor: NanoweaponObservation | None = None,
) -> TaskResult:
    """Replay one claim-first Normal Craft visit and stop after any unknown successor."""

    transition = nanoweapon_transition(before)
    if transition.outcome is TaskOutcome.BLOCKED:
        return transition
    if nanoweapon_active_craft_authorizeable(before):
        return transition
    if nanoweapon_known_material_shortage(before) or nanoweapon_current_reset_start_known(before):
        return transition

    current = before
    claim_calls = 0
    if nanoweapon_claim_authorizeable(before):
        if claim_successor is None:
            return TaskResult.progress(
                "Completed Normal Craft is recognized; claim successor remains unproven",
                NANOWEAPON_SCREEN,
                craft_transport_calls=0,
            )
        if not nanoweapon_claim_postcondition_verified(before, claim_successor):
            return TaskResult(
                TaskOutcome.FAILED_SAFE,
                "NANOWEAPON_CLAIM_SUCCESSOR_NOT_PROVEN",
                verified=True,
                state=NANOWEAPON_SCREEN,
                details={
                    "craft_transport_calls": 1,
                    "craft_claim_transport_calls": 1,
                    "craft_start_transport_calls": 0,
                    "committed_action_count": 0,
                    "effect_reconciliation_required": True,
                    "identical_retry_denied": True,
                },
            )
        current, claim_calls = claim_successor, 1

    if nanoweapon_active_craft_authorizeable(current):
        result = nanoweapon_transition(current)
        return TaskResult(
            result.outcome,
            result.reason,
            result.verified,
            result.state,
            result.completion_key,
            dict(
                result.details,
                craft_transport_calls=claim_calls,
                craft_claim_transport_calls=claim_calls,
                craft_start_transport_calls=0,
                committed_action_count=claim_calls,
            ),
        )
    if nanoweapon_known_material_shortage(current):
        result = nanoweapon_transition(current)
        return TaskResult(
            result.outcome,
            result.reason,
            result.verified,
            result.state,
            result.completion_key,
            dict(
                result.details,
                craft_transport_calls=claim_calls,
                craft_claim_transport_calls=claim_calls,
                craft_start_transport_calls=0,
                committed_action_count=claim_calls,
            ),
        )
    if nanoweapon_current_reset_start_known(current):
        result = nanoweapon_transition(current)
        return TaskResult(
            result.outcome,
            result.reason,
            result.verified,
            result.state,
            result.completion_key,
            dict(
                result.details,
                craft_transport_calls=claim_calls,
                craft_claim_transport_calls=claim_calls,
                craft_start_transport_calls=0,
                committed_action_count=claim_calls,
            ),
        )
    if not nanoweapon_authorizeable(current):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NANOWEAPON_CRAFT_PRECONDITION_NOT_PROVEN",
            verified=True,
            state=NANOWEAPON_SCREEN,
            details={
                "craft_transport_calls": claim_calls,
                "craft_claim_transport_calls": claim_calls,
                "craft_start_transport_calls": 0,
                "committed_action_count": claim_calls,
                "effect_reconciliation_required": False,
                "identical_retry_denied": False,
            },
        )
    if craft_successor is None:
        return TaskResult.progress(
            "Normal Craft is eligible; start successor remains unproven",
            NANOWEAPON_SCREEN,
            craft_transport_calls=claim_calls,
            craft_claim_transport_calls=claim_calls,
            craft_start_transport_calls=0,
            committed_action_count=claim_calls,
        )
    if not nanoweapon_postcondition_verified(current, craft_successor):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "NANOWEAPON_START_SUCCESSOR_NOT_PROVEN",
            verified=True,
            state=NANOWEAPON_SCREEN,
            details={
                "craft_transport_calls": claim_calls + 1,
                "craft_claim_transport_calls": claim_calls,
                "craft_start_transport_calls": 1,
                "committed_action_count": claim_calls,
                "effect_reconciliation_required": True,
                "identical_retry_denied": True,
            },
        )
    return TaskResult.done(
        "One exact Normal Craft successor is positively verified",
        "nanoweapon:normal:completed",
        NANOWEAPON_SCREEN,
        craft_transport_calls=claim_calls + 1,
        craft_claim_transport_calls=claim_calls,
        craft_start_transport_calls=1,
        committed_action_count=claim_calls + 1,
    )
