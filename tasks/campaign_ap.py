"""Offline Campaign AP consumption contract.

This module models one bounded, allowlisted AP-consuming Campaign action.  It owns no transport,
runtime registration, persistence, or live evidence capture.  Refill, battle, unknown-cost, and
static-reference states fail closed until a future promotion supplies fresh Bliss-native evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


CAMPAIGN_SCREEN = "CAMPAIGN"
CAMPAIGN_AP_TARGET = "campaign-ap-action"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
ALLOWED_ACTION_MODES = frozenset({"SWEEP", "AUTO_COMPLETE"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CampaignAPObservation:
    """Semantic evidence for one bounded AP-consuming Campaign action."""

    screen_state: str
    selected_campaign: bool
    stage_identity: str
    stage_known: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    action_mode: str
    action_ready: bool
    ap_before: int
    ap_cost: Optional[int]
    ap_budget: int
    ap_refill_visible: bool = False
    battle_mode_visible: bool = False
    stage_result_visible: bool = False
    result_identity: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: CampaignAPObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: CampaignAPObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def campaign_ap_authorizeable(observation: CampaignAPObservation) -> bool:
    """Require one known allowlisted AP action within an explicit budget."""

    return bool(
        observation.screen_state == CAMPAIGN_SCREEN
        and observation.selected_campaign
        and bool(observation.stage_identity.strip())
        and observation.stage_known
        and observation.target_identity == CAMPAIGN_AP_TARGET
        and observation.control_class in ALLOWED_ACTION_MODES
        and observation.action_mode == observation.control_class
        and observation.action_ready
        and observation.ap_before >= 0
        and observation.ap_cost is not None
        and observation.ap_cost > 0
        and observation.ap_budget > 0
        and observation.ap_cost <= observation.ap_budget
        and observation.ap_cost <= observation.ap_before
        and not observation.ap_refill_visible
        and not observation.battle_mode_visible
        and _target_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def campaign_ap_transaction_spec(observation: CampaignAPObservation) -> ActionTransactionSpec:
    if not campaign_ap_authorizeable(observation):
        raise ValueError("Campaign AP preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind=f"CONSUME_AP_{observation.action_mode}",
        expected_source_screen=CAMPAIGN_SCREEN,
        subject=observation.stage_identity,
        quantity=1,
        resource_or_currency="AP",
        maximum_cost=observation.ap_budget,
        free_only=False,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "campaign_screen",
            "known_allowlisted_stage",
            "exact_ap_action",
            "explicit_ap_budget",
            "ap_cost_within_budget",
            "no_refill_or_battle",
            "bliss_native_target_evidence",
        ),
        semantic_postconditions=("campaign_result_and_exact_ap_delta",),
    )


def campaign_ap_postcondition_verified(
    before: CampaignAPObservation,
    after: CampaignAPObservation | None,
) -> bool:
    """Require same-day same-stage result and exact AP consumption."""

    if not campaign_ap_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != CAMPAIGN_SCREEN
        or not after.selected_campaign
        or after.stage_identity != before.stage_identity
        or after.game_day_id != before.game_day_id
        or not after.recognized
        or after.ap_refill_visible
        or after.battle_mode_visible
        or after.ap_before != before.ap_before - before.ap_cost
    ):
        return False
    return bool(
        after.stage_result_visible
        and bool(after.result_identity.strip())
    )


def campaign_ap_perform_one_pulse(
    before: CampaignAPObservation,
    after: CampaignAPObservation | None = None,
) -> TaskResult:
    """Return a pure result; Campaign transport remains evidence-gated."""

    if not campaign_ap_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_CAMPAIGN_AP_ACTION",
            verified=True,
            state=CAMPAIGN_SCREEN,
        )
    if after is None:
        return TaskResult.progress(
            "Campaign AP action is authorized by the offline contract; dispatch remains evidence-gated",
            CAMPAIGN_SCREEN,
        )
    if not campaign_ap_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "CAMPAIGN_AP_POSTCONDITION_NOT_PROVEN",
            state=CAMPAIGN_SCREEN,
        )
    return TaskResult.done(
        "Campaign AP postcondition verified",
        f"campaign-ap:{before.stage_identity}:completed",
        CAMPAIGN_SCREEN,
    )
