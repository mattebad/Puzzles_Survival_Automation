"""Offline free Bioenhancer research contract.

This module models one explicit free research action without owning transport, runtime
registration, or live evidence capture.  Paid, multi-use, ambiguous, and stale states fail
closed until a future promotion supplies fresh Bliss-native evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


BIOENHANCER_SCREEN = "BIOENHANCER"
BIOENHANCER_FREE_TARGET = "bioenhancer-free-research"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BioenhancerObservation:
    """Semantic evidence for one free, single Bioenhancer research action."""

    screen_state: str
    selected_bioenhancer: bool
    research_mode: str
    free_available: bool
    free_banner_visible: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    research_ready: bool = True
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    research_count: Optional[int] = None
    research_result_visible: bool = False
    result_identity: str = ""
    cooldown_active: bool = False
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: BioenhancerObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: BioenhancerObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def bioenhancer_authorizeable(observation: BioenhancerObservation) -> bool:
    """Require exact selected-screen, free-single, zero-cost research evidence."""

    return bool(
        observation.screen_state == BIOENHANCER_SCREEN
        and observation.selected_bioenhancer
        and observation.research_mode == "FREE_SINGLE"
        and observation.free_available
        and observation.free_banner_visible
        and observation.research_ready
        and observation.target_identity == BIOENHANCER_FREE_TARGET
        and observation.control_class == "RESEARCH_FREE"
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


def bioenhancer_transaction_spec(observation: BioenhancerObservation) -> ActionTransactionSpec:
    if not bioenhancer_authorizeable(observation):
        raise ValueError("Bioenhancer free research preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="RESEARCH_BIOENHANCER_FREE",
        expected_source_screen=BIOENHANCER_SCREEN,
        subject="free Bioenhancer research",
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "bioenhancer_screen",
            "selected_bioenhancer",
            "explicit_free_single_research",
            "free_banner",
            "bliss_native_target_evidence",
            "explicit_zero_cost",
        ),
        semantic_postconditions=("research_result_or_cooldown_change",),
    )


def bioenhancer_postcondition_verified(
    before: BioenhancerObservation,
    after: BioenhancerObservation | None,
) -> bool:
    """Require a same-day positive result, count increase, or cooldown transition."""

    if not bioenhancer_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != BIOENHANCER_SCREEN
        or not after.selected_bioenhancer
        or after.game_day_id != before.game_day_id
        or not after.recognized
    ):
        return False
    count_increased = (
        before.research_count is not None
        and after.research_count is not None
        and after.research_count > before.research_count
    )
    result_confirmed = after.research_result_visible and bool(after.result_identity.strip())
    cooldown_started = not before.cooldown_active and after.cooldown_active
    return bool(count_increased or result_confirmed or cooldown_started)


def bioenhancer_perform_one_pulse(
    before: BioenhancerObservation,
    after: BioenhancerObservation | None = None,
) -> TaskResult:
    """Return a pure result; transport remains outside this evidence-gated module."""

    if not bioenhancer_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_BIOENHANCER_FREE_RESEARCH",
            verified=True,
            state=BIOENHANCER_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "RESEARCH_BIOENHANCER_FREE is authorized by the offline contract; dispatch remains evidence-gated",
            BIOENHANCER_SCREEN,
        )
    if not bioenhancer_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "BIOENHANCER_POSTCONDITION_NOT_PROVEN",
            state=BIOENHANCER_SCREEN,
        )
    return TaskResult.done(
        "Bioenhancer research postcondition verified",
        "bioenhancer:free:completed",
        BIOENHANCER_SCREEN,
    )
