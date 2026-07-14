"""Offline activity-milestone chest contract for Phase E.

No runtime detector or transport is registered here.  A ready chest remains non-authorizing until
fresh Bliss-native target, explicit free semantics, and a positive postcondition are promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


ACTIVITY_MILESTONES_SCREEN = "ACTIVITY_MILESTONES"
ACTIVITY_MILESTONE_TARGET = "activity-milestone-chest"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ActivityMilestoneObservation:
    """Semantic evidence for one ready, free activity milestone chest."""

    screen_state: str
    selected_activity_milestones: bool
    milestone_key: str
    milestone_name: str
    milestone_ready: bool
    panel_bounds: ROI
    target_identity: str
    target_roi: ROI
    control_class: str
    chest_fully_visible: bool
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


def _target_inside_panel(observation: ActivityMilestoneObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: ActivityMilestoneObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def activity_milestone_authorizeable(observation: ActivityMilestoneObservation) -> bool:
    """Require an exact ready activity chest with explicit zero-cost semantics."""

    return bool(
        observation.screen_state == ACTIVITY_MILESTONES_SCREEN
        and observation.selected_activity_milestones
        and bool(observation.milestone_key.strip())
        and bool(observation.milestone_name.strip())
        and observation.milestone_ready
        and observation.chest_fully_visible
        and observation.target_identity == ACTIVITY_MILESTONE_TARGET
        and observation.control_class == "MILESTONE_CHEST"
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


def activity_milestone_transaction_spec(observation: ActivityMilestoneObservation) -> ActionTransactionSpec:
    if not activity_milestone_authorizeable(observation):
        raise ValueError("activity milestone chest preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="CLAIM_ACTIVITY_MILESTONE",
        expected_source_screen=ACTIVITY_MILESTONES_SCREEN,
        subject=observation.milestone_name,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "activity_milestones_screen",
            "selected_activity_milestones",
            "exact_ready_milestone_chest",
            "bliss_native_target_evidence",
            "explicit_zero_cost",
        ),
        semantic_postconditions=("same_milestone_opens_or_points_increase",),
    )


def activity_milestone_postcondition_verified(
    before: ActivityMilestoneObservation,
    after: ActivityMilestoneObservation | None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    chest_opened: bool = False,
) -> bool:
    """Require the same milestone to open/change or an explicitly positive points delta."""

    if not activity_milestone_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != ACTIVITY_MILESTONES_SCREEN
        or not after.selected_activity_milestones
        or after.milestone_key != before.milestone_key
        or after.game_day_id != before.game_day_id
    ):
        return False
    chest_changed = bool(
        chest_opened
        or not after.milestone_ready
        or after.target_identity != ACTIVITY_MILESTONE_TARGET
        or after.control_class != "MILESTONE_CHEST"
        or not after.chest_fully_visible
    )
    points_changed = (
        points_before is not None
        and points_after is not None
        and points_after > points_before
    )
    return bool(chest_changed or points_changed)


def activity_milestone_perform_one_pulse(
    before: ActivityMilestoneObservation,
    after: ActivityMilestoneObservation | None = None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    chest_opened: bool = False,
) -> TaskResult:
    """Return a pure result; transport remains outside this evidence-gated module."""

    if not activity_milestone_authorizeable(before):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_ACTIVITY_MILESTONE", verified=True, state=ACTIVITY_MILESTONES_SCREEN)
    if after is None:
        return TaskResult.progress("CLAIM_ACTIVITY_MILESTONE is authorized by the offline contract; dispatch remains evidence-gated", ACTIVITY_MILESTONES_SCREEN)
    if not activity_milestone_postcondition_verified(
        before,
        after,
        points_before=points_before,
        points_after=points_after,
        chest_opened=chest_opened,
    ):
        return TaskResult(TaskOutcome.FAILED_SAFE, "ACTIVITY_MILESTONE_POSTCONDITION_NOT_PROVEN", state=ACTIVITY_MILESTONES_SCREEN)
    return TaskResult.done(
        "activity milestone chest postcondition verified",
        f"activity-milestone:{before.milestone_key}:claimed",
        ACTIVITY_MILESTONES_SCREEN,
    )
