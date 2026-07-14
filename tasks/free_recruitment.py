"""Offline free recruitment contract for Phase E.

The free recruitment control is not registered with pnsctl.  This module only proves the semantic
guards required before a future one-dispatch transaction could be promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


RECRUITMENT_SCREEN = "RECRUITMENT"
FREE_RECRUITMENT_TARGET = "recruit-free"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FreeRecruitmentObservation:
    """Semantic evidence for one free single recruitment."""

    screen_state: str
    selected_recruitment: bool
    recruitment_mode: str
    free_available: bool
    free_banner_visible: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    recruitment_count: Optional[int] = None
    unknown_confirmation: bool = False
    recruitment_result_visible: bool = False
    result_identity: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: FreeRecruitmentObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: FreeRecruitmentObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def free_recruitment_authorizeable(observation: FreeRecruitmentObservation) -> bool:
    """Require explicit free single-recruit mode and no ambiguous confirmation."""

    return bool(
        observation.screen_state == RECRUITMENT_SCREEN
        and observation.selected_recruitment
        and observation.recruitment_mode == "FREE"
        and observation.free_available
        and observation.free_banner_visible
        and observation.target_identity == FREE_RECRUITMENT_TARGET
        and observation.control_class == "RECRUIT_FREE"
        and observation.cost_type == "none"
        and observation.cost_amount == 0
        and observation.quantity == 1
        and not observation.unknown_confirmation
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def free_recruitment_transaction_spec(observation: FreeRecruitmentObservation) -> ActionTransactionSpec:
    if not free_recruitment_authorizeable(observation):
        raise ValueError("free recruitment preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="RECRUIT_FREE",
        expected_source_screen=RECRUITMENT_SCREEN,
        subject="single free recruitment",
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "recruitment_screen",
            "selected_recruitment",
            "explicit_free_single_mode",
            "free_banner",
            "bliss_native_target_evidence",
            "no_unknown_confirmation",
        ),
        semantic_postconditions=("recruitment_result_or_count_increase",),
    )


def free_recruitment_postcondition_verified(
    before: FreeRecruitmentObservation,
    after: FreeRecruitmentObservation | None,
) -> bool:
    """Require a confirmed result identity or a positive recruitment-count increase."""

    if not free_recruitment_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != RECRUITMENT_SCREEN
        or not after.selected_recruitment
        or after.game_day_id != before.game_day_id
        or after.unknown_confirmation
    ):
        return False
    count_increased = (
        before.recruitment_count is not None
        and after.recruitment_count is not None
        and after.recruitment_count > before.recruitment_count
    )
    result_confirmed = after.recruitment_result_visible and bool(after.result_identity.strip())
    return bool(count_increased or result_confirmed)


def free_recruitment_perform_one_pulse(
    before: FreeRecruitmentObservation,
    after: FreeRecruitmentObservation | None = None,
) -> TaskResult:
    """Return a pure result; recruitment transport remains outside this evidence-gated module."""

    if not free_recruitment_authorizeable(before):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_FREE_RECRUITMENT", verified=True, state=RECRUITMENT_SCREEN)
    if after is None:
        return TaskResult.progress("RECRUIT_FREE is authorized by the offline contract; dispatch remains evidence-gated", RECRUITMENT_SCREEN)
    if not free_recruitment_postcondition_verified(before, after):
        return TaskResult(TaskOutcome.FAILED_SAFE, "FREE_RECRUITMENT_POSTCONDITION_NOT_PROVEN", state=RECRUITMENT_SCREEN)
    return TaskResult.done(
        "free recruitment postcondition verified",
        "recruitment:free:completed",
        RECRUITMENT_SCREEN,
    )
