"""Zero-resource Nano Material Production transitions, independent of Daily Craft."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Optional

from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult
from .profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE


NANOWEAPON_SCREEN = "NANOWEAPON"
MATERIAL_PRODUCTION_TAB = "MATERIAL_PRODUCTION"
NANO_MATERIAL_PRODUCTION_TARGET = "nano-material-production"
NANO_MATERIAL_PRODUCTION_DURATION_SECONDS = 21600
NANO_MATERIAL_PRODUCTION_COMPLETION = "nano-material-production:maintenance-pulse-complete"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MaterialProductionObservation:
    """One current native observation of the Material Production slot."""

    screen_state: str
    selected_nanoweapon: bool
    selected_tab: str
    production_state: str
    active_production_count: Optional[int]
    production_duration_seconds: Optional[int]
    timer_seconds_remaining: Optional[int]
    cost_known: bool
    cost_type: str
    cost_amount: Optional[int]
    other_costs_known: bool
    nonzero_other_costs: bool
    target_identity: str
    target_roi: tuple[int, int, int, int]
    panel_bounds: tuple[int, int, int, int]
    completed_batch_count: Optional[int]
    start_enabled: bool = False
    claim_visible: bool = False
    overlay_state: str = "none_observed"
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    occurrence_key: str = ""
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: MaterialProductionObservation) -> bool:
    try:
        bounds = (*observation.panel_bounds, *observation.target_roi)
        if len(bounds) != 8 or any(type(value) is not int for value in bounds):
            return False
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1


def _has_native_source(observation: MaterialProductionObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == ACTIVE_RUNTIME_PROFILE_ID
    )


def material_production_authorizeable(
    observation: MaterialProductionObservation,
) -> bool:
    """Require an exact known one-slot state, exact timer and zero visible cost."""

    common = bool(
        observation.screen_state == NANOWEAPON_SCREEN
        and type(observation.selected_nanoweapon) is bool
        and observation.selected_nanoweapon
        and observation.selected_tab == MATERIAL_PRODUCTION_TAB
        and observation.production_state in {"complete", "idle", "active"}
        and type(observation.production_duration_seconds) is int
        and observation.production_duration_seconds == NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        and type(observation.active_production_count) is int
        and type(observation.completed_batch_count) is int
        and type(observation.cost_known) is bool
        and observation.cost_known
        and observation.cost_type == "none"
        and type(observation.cost_amount) is int
        and observation.cost_amount == 0
        and type(observation.other_costs_known) is bool
        and observation.other_costs_known
        and type(observation.nonzero_other_costs) is bool
        and not observation.nonzero_other_costs
        and type(observation.start_enabled) is bool
        and type(observation.claim_visible) is bool
        and observation.target_identity == NANO_MATERIAL_PRODUCTION_TARGET
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and type(observation.recognized) is bool
        and observation.recognized
        and type(observation.occurrence_key) is str
        and bool(observation.occurrence_key.strip())
        and _has_native_source(observation)
    )
    if not common:
        return False
    if observation.production_state == "complete":
        return bool(
            observation.active_production_count == 0
            and observation.completed_batch_count == 1
            and type(observation.timer_seconds_remaining) is int
            and observation.timer_seconds_remaining == 0
            and observation.claim_visible
            and not observation.start_enabled
        )
    if observation.production_state == "idle":
        return bool(
            observation.active_production_count == 0
            and observation.completed_batch_count == 0
            and type(observation.timer_seconds_remaining) is int
            and observation.timer_seconds_remaining == 0
            and observation.start_enabled
            and not observation.claim_visible
        )
    return bool(
        observation.active_production_count == 1
        and observation.completed_batch_count == 0
        and type(observation.timer_seconds_remaining) is int
        and 0 < observation.timer_seconds_remaining <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        and not observation.claim_visible
        and not observation.start_enabled
    )

def material_production_claim_spec(
    observation: MaterialProductionObservation,
) -> ActionTransactionSpec:
    if not material_production_authorizeable(observation) or observation.production_state != "complete":
        raise ValueError("completed Material Production is not positively recognized")
    return ActionTransactionSpec(
        action_kind="CLAIM_NANO_MATERIAL_PRODUCTION",
        expected_source_screen=NANOWEAPON_SCREEN,
        subject="nano-material-production-claim",
        quantity=1,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(
            "product_id=nano_material_production",
            "product_revision=nano_material_production-v1",
            "effect_ordinal=1",
            f"native_occurrence_key={observation.occurrence_key}",
            "native_action_key_binds_occurrence=true",
            "material_production_tab",
            "production_state=complete",
            "active_production_count=0",
            "completed_batch_count=1",
            "cost=none:0",
            "zero_resource_claim",
        ),
        semantic_postconditions=("NANO_MATERIAL_PRODUCTION_CLAIMED",),
    )


def material_production_start_spec(
    observation: MaterialProductionObservation,
) -> ActionTransactionSpec:
    if not material_production_authorizeable(observation) or observation.production_state != "idle":
        raise ValueError("Material Production is not positively idle and startable")
    return ActionTransactionSpec(
        action_kind="START_NANO_MATERIAL_PRODUCTION",
        expected_source_screen=NANOWEAPON_SCREEN,
        subject="nano-material-production-start",
        quantity=1,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(
            "product_id=nano_material_production",
            "product_revision=nano_material_production-v1",
            "effect_ordinal=1",
            f"native_occurrence_key={observation.occurrence_key}",
            "native_action_key_binds_occurrence=true",
            "material_production_tab",
            "production_state=idle",
            "active_production_count=0",
            "duration_seconds=21600",
            "cost=none:0",
            "production_start_ordinal=1",
        ),
        semantic_postconditions=("NANO_MATERIAL_PRODUCTION_ACTIVE_21600",),
    )


def material_production_claim_postcondition_verified(
    before: MaterialProductionObservation,
    after: MaterialProductionObservation | None,
) -> bool:
    """A claim is confirmed only by its current complete-to-idle successor."""

    return bool(
        after is not None
        and material_production_authorizeable(before)
        and before.production_state == "complete"
        and material_production_authorizeable(after)
        and after.production_state == "idle"
        and after.active_production_count == 0
        and after.completed_batch_count == 0
        and not after.claim_visible
        and after.source_frame_sha256 != before.source_frame_sha256
    )


def material_production_start_postcondition_verified(
    before: MaterialProductionObservation,
    after: MaterialProductionObservation | None,
) -> bool:
    """Require a positive one-slot active timer after an exact zero-cost start."""

    return bool(
        after is not None
        and material_production_authorizeable(before)
        and before.production_state == "idle"
        and material_production_authorizeable(after)
        and after.production_state == "active"
        and after.active_production_count == 1
        and after.completed_batch_count == 0
        and after.production_duration_seconds == NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        and type(after.timer_seconds_remaining) is int
        and 0 < after.timer_seconds_remaining <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        and after.source_frame_sha256 != before.source_frame_sha256
    )


def material_production_due_at(now_utc: float, timer_seconds_remaining: int) -> float:
    if (
        type(now_utc) not in (int, float)
        or not math.isfinite(float(now_utc))
        or now_utc < 0
    ):
        raise ValueError("Material Production observation time must be a finite UTC epoch")
    if (
        type(timer_seconds_remaining) is not int
        or not 0 < timer_seconds_remaining <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
    ):
        raise ValueError("Material Production timer must be a positive bounded integer")
    return float(now_utc) + timer_seconds_remaining


def material_production_transition(
    observation: MaterialProductionObservation,
) -> TaskResult:
    """Select claim/start/defer without performing transport."""

    if not material_production_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "MATERIAL_PRODUCTION_STATE_NOT_POSITIVELY_RECOGNIZED",
            verified=True,
            state=NANOWEAPON_SCREEN,
        )
    if observation.production_state == "complete":
        return TaskResult.progress(
            "Completed Material Production requires one verified claim before restart",
            "production_complete",
            next_action="claim_then_observe_idle",
        )
    if observation.production_state == "idle":
        return TaskResult.progress(
            "One zero-resource six-hour Material Production start is eligible",
            "production_idle",
            next_action="start_one_production",
        )
    return TaskResult(
        TaskOutcome.RETRY,
        "MATERIAL_PRODUCTION_ACTIVE_DEFERRED",
        verified=True,
        state="production_active",
        details={
            "next_action": "refresh_due_time_only",
            "timer_seconds_remaining": observation.timer_seconds_remaining,
            "duration_seconds": NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
            "production_transport_calls": 0,
        },
    )


def material_production_replay(
    before: MaterialProductionObservation,
    *,
    claim_successor: MaterialProductionObservation | None = None,
    start_successor: MaterialProductionObservation | None = None,
) -> TaskResult:
    """Replay the state transitions while keeping claim and start distinct."""

    transition = material_production_transition(before)
    if transition.outcome is TaskOutcome.BLOCKED:
        return transition
    if before.production_state == "active":
        return transition
    idle = before
    claim_calls = 0
    if before.production_state == "complete":
        if claim_successor is None:
            return TaskResult.progress(
                "Claim is recognized; its successor remains unproven",
                "production_complete",
                production_transport_calls=0,
            )
        if not material_production_claim_postcondition_verified(before, claim_successor):
            return TaskResult(
                TaskOutcome.FAILED_SAFE,
                "MATERIAL_PRODUCTION_CLAIM_SUCCESSOR_NOT_PROVEN",
                verified=True,
                state="production_complete",
                details={
                    "production_transport_calls": 1,
                    "effect_reconciliation_required": True,
                    "identical_retry_denied": True,
                },
            )
        idle, claim_calls = claim_successor, 1
    if start_successor is None:
        return TaskResult.progress(
            "Idle Material Production is recognized; start successor remains unproven",
            "production_idle",
            production_transport_calls=claim_calls,
        )
    if not material_production_start_postcondition_verified(idle, start_successor):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "MATERIAL_PRODUCTION_START_SUCCESSOR_NOT_PROVEN",
            verified=True,
            state="production_idle",
            details={
                "production_transport_calls": claim_calls + 1,
                "effect_reconciliation_required": True,
                "identical_retry_denied": True,
            },
        )
    return TaskResult.done(
        "One zero-resource six-hour Material Production batch is active",
        NANO_MATERIAL_PRODUCTION_COMPLETION,
        "production_active",
        production_transport_calls=claim_calls + 1,
        production_duration_seconds=NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
        active_production_count=1,
    )
