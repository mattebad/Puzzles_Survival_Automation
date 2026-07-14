"""Offline generalized Daily Quest Claim contract for Phase E.

The passed Personal Might Claim path remains unchanged.  This separate contract models any
available ordinary Daily Quest Claim and is deliberately not registered for transport until a
fresh Bliss-native target and positive postcondition pair is promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


DAILY_QUEST_SCREEN = "DAILY_QUEST"
DAILY_QUEST_CLAIM_TARGET = "daily-quest-claim"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AvailableDailyClaimObservation:
    """Semantic evidence for one ordinary completed Daily Quest row."""

    screen_state: str
    selected_daily_quest: bool
    objective_key: str
    objective_name: str
    current_progress: int
    required_progress: int
    row_bounds: ROI
    target_identity: str
    target_roi: ROI
    control_class: str
    row_fully_visible: bool
    claim_fully_visible: bool
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    milestone_reward: bool = False
    clipped: bool = False
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_row(observation: AvailableDailyClaimObservation) -> bool:
    try:
        rx0, ry0, rx1, ry1 = observation.row_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(rx0 <= tx0 < tx1 <= rx1 and ry0 <= ty0 < ty1 <= ry1)


def _has_bliss_native_source(observation: AvailableDailyClaimObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def available_daily_claim_authorizeable(observation: AvailableDailyClaimObservation) -> bool:
    """Require a generalized, ordinary, free Daily Quest Claim target."""

    return bool(
        observation.screen_state == DAILY_QUEST_SCREEN
        and observation.selected_daily_quest
        and bool(observation.objective_key.strip())
        and bool(observation.objective_name.strip())
        and observation.required_progress >= 1
        and observation.current_progress == observation.required_progress
        and observation.row_fully_visible
        and observation.claim_fully_visible
        and observation.target_identity == DAILY_QUEST_CLAIM_TARGET
        and observation.control_class == "CLAIM"
        and observation.cost_type == "none"
        and observation.cost_amount == 0
        and observation.quantity == 1
        and _target_inside_row(observation)
        and not observation.milestone_reward
        and not observation.clipped
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def available_daily_claim_transaction_spec(observation: AvailableDailyClaimObservation) -> ActionTransactionSpec:
    if not available_daily_claim_authorizeable(observation):
        raise ValueError("generalized Daily Quest Claim preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="CLAIM_DAILY_QUEST",
        expected_source_screen=DAILY_QUEST_SCREEN,
        subject=observation.objective_name,
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "daily_quest_screen",
            "selected_daily_quest",
            "exact_completed_row_local_claim",
            "bliss_native_target_evidence",
            "explicit_zero_cost",
            "not_milestone",
        ),
        semantic_postconditions=("same_objective_row_disappears_or_points_increase",),
    )


def available_daily_claim_postcondition_verified(
    before: AvailableDailyClaimObservation,
    after: AvailableDailyClaimObservation | None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    row_disappeared: bool = False,
) -> bool:
    """Require the same generalized Daily row to change or an explicitly positive points delta."""

    if not available_daily_claim_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != DAILY_QUEST_SCREEN
        or not after.selected_daily_quest
        or after.objective_key != before.objective_key
        or after.game_day_id != before.game_day_id
    ):
        return False
    row_changed = bool(
        row_disappeared
        or after.target_identity != DAILY_QUEST_CLAIM_TARGET
        or after.control_class != "CLAIM"
        or not after.claim_fully_visible
    )
    points_changed = (
        points_before is not None
        and points_after is not None
        and points_after > points_before
    )
    return bool(row_changed or points_changed)


def available_daily_claim_perform_one_pulse(
    before: AvailableDailyClaimObservation,
    after: AvailableDailyClaimObservation | None = None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    row_disappeared: bool = False,
) -> TaskResult:
    """Return a pure result; transport remains outside this evidence-gated module."""

    if not available_daily_claim_authorizeable(before):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_DAILY_CLAIM_TARGET", verified=True, state=DAILY_QUEST_SCREEN)
    if after is None:
        return TaskResult.progress("CLAIM_DAILY_QUEST is authorized by the offline contract; dispatch remains evidence-gated", DAILY_QUEST_SCREEN)
    if not available_daily_claim_postcondition_verified(
        before,
        after,
        points_before=points_before,
        points_after=points_after,
        row_disappeared=row_disappeared,
    ):
        return TaskResult(TaskOutcome.FAILED_SAFE, "DAILY_CLAIM_POSTCONDITION_NOT_PROVEN", state=DAILY_QUEST_SCREEN)
    return TaskResult.done(
        "generalized Daily Quest Claim postcondition verified",
        f"daily-quest:{before.objective_key}:claimed",
        DAILY_QUEST_SCREEN,
    )
