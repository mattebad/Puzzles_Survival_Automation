"""Exact Campaign Story AP entry and result contract.

This module is deliberately separate from the legacy ``tasks.campaign_ap``
Sweep/Auto Complete contract.  It describes the current native route only:
Each Stage Dialog ``Challenge`` enters Hero Lineup with its own one-shot entry.
Verified Victory -> Chapter Map AP debits survive later route failures; normal
whole-route completion additionally requires a fresh drained Home balance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from safe_action_core.models import ActionClass, PolicyRequest, ROI
from safe_action_core.policy import (
    CAMPAIGN_AP_COSTS,
    CAMPAIGN_AP_ENTRY_CONSEQUENCE,
    CAMPAIGN_AP_ENTRY_POSTCONDITION,
    CAMPAIGN_AP_FLOW_ID,
    CAMPAIGN_AP_MAXIMUM_BALANCE,
    CAMPAIGN_AP_PRODUCT_ID,
    CAMPAIGN_AP_PRODUCT_REVISION,
    CAMPAIGN_AP_SEMANTIC_ACTION,
    CAMPAIGN_AP_SOURCE_STATE,
    CAMPAIGN_AP_TARGET_PREFIX,
)
from tasks.campaign_auto_battle import CAMPAIGN_DRAIN_MAX_RUNS, CampaignRouteProgress


CAMPAIGN_AP_CONTROL_CLASS = "CHALLENGE"
CAMPAIGN_AP_CURRENCY = "AP"
CAMPAIGN_AP_RESULT_SUCCESSOR = "CAMPAIGN_CHAPTER_MAP"
CAMPAIGN_AP_TERMINAL_HOME = "HOME_BASE"


def campaign_ap_challenge_preconditions(current_ap: int) -> tuple[str, ...]:
    """Return the closed route-owned precondition tuple for one AP entry."""

    if type(current_ap) is not int or current_ap < 0 or current_ap > CAMPAIGN_AP_MAXIMUM_BALANCE:
        raise ValueError("current_ap must be an integer within the Campaign AP balance limit")
    return (
        f"campaign_ap_product={CAMPAIGN_AP_PRODUCT_ID}",
        f"campaign_ap_current_ap={current_ap}",
        "campaign_ap_no_refill",
        "campaign_ap_effect_ordinal=1",
    )


def campaign_ap_challenge_policy_request(
    base_request: PolicyRequest,
    *,
    stage_identity: str,
    current_ap: int,
    target_roi: ROI,
) -> PolicyRequest:
    """Bind a fresh Stage Dialog observation to the Campaign AP policy class.

    ``base_request`` supplies the live lease, timing, session, and action
    identity.  The native recognizer supplies the current frame and isolated
    target ROI; this helper intentionally does not manufacture recognition.
    """

    if stage_identity not in CAMPAIGN_AP_COSTS:
        raise ValueError("stage_identity is not an approved Campaign AP destination")
    expected_cost = CAMPAIGN_AP_COSTS[stage_identity]
    if (
        type(current_ap) is not int
        or current_ap < 0
        or current_ap > CAMPAIGN_AP_MAXIMUM_BALANCE
    ):
        raise ValueError("current_ap must be within the Campaign AP balance limit")
    if (
        type(target_roi) is not tuple
        or len(target_roi) != 4
        or any(type(item) is not int for item in target_roi)
    ):
        raise ValueError("target_roi must be a native four-coordinate ROI")
    observation = base_request.observation
    expected_target = f"{CAMPAIGN_AP_TARGET_PREFIX}{stage_identity}"
    if observation.recognized is not True:
        raise ValueError("Campaign AP request requires a positively recognized source frame")
    if observation.target_roi != target_roi:
        raise ValueError("target_roi does not match the recognized Campaign Challenge target")
    if (
        observation.source_state != CAMPAIGN_AP_SOURCE_STATE
        or observation.target_identity != expected_target
        or observation.control_class != CAMPAIGN_AP_CONTROL_CLASS
        or observation.consequence != CAMPAIGN_AP_ENTRY_CONSEQUENCE
        or observation.cost_type != CAMPAIGN_AP_CURRENCY
        or observation.cost_amount != expected_cost
        or observation.quantity != 1
        or observation.expected_postcondition != CAMPAIGN_AP_ENTRY_POSTCONDITION
    ):
        raise ValueError("base observation is not the exact Campaign AP Challenge entry")
    return replace(
        base_request,
        task_id=CAMPAIGN_AP_FLOW_ID,
        semantic_action=CAMPAIGN_AP_SEMANTIC_ACTION,
        action_class=ActionClass.CAMPAIGN_AP_CHALLENGE,
        action_kind=CAMPAIGN_AP_PRODUCT_REVISION,
        subject=stage_identity,
        resource_or_currency=CAMPAIGN_AP_CURRENCY,
        maximum_cost=expected_cost,
        free_only=False,
        semantic_preconditions=campaign_ap_challenge_preconditions(current_ap),
        semantic_postconditions=(CAMPAIGN_AP_ENTRY_POSTCONDITION,),
        observation=observation,
    )


@dataclass(frozen=True)
class CampaignApRouteResult:
    """The route-level facts required before committing one AP effect."""

    stage_identity: str
    ap_before: int
    ap_after: int
    ap_regenerated: int
    battle_outcome: str
    result_successor: str
    terminal_home: str
    effect_ordinal: int
    refill_seen: bool


def campaign_ap_effect_verified(result: CampaignApRouteResult) -> bool:
    """Commit only after exact AP delta, victory result, and canonical Home."""

    if result.stage_identity not in CAMPAIGN_AP_COSTS:
        return False
    if any(
        type(value) is not int
        for value in (
            result.ap_before,
            result.ap_after,
            result.ap_regenerated,
            result.effect_ordinal,
        )
    ):
        return False
    cost = CAMPAIGN_AP_COSTS[result.stage_identity]
    return bool(
        0 <= result.ap_before <= CAMPAIGN_AP_MAXIMUM_BALANCE
        and 0 <= result.ap_after <= CAMPAIGN_AP_MAXIMUM_BALANCE
        and result.ap_regenerated >= 0
        and result.effect_ordinal == 1
        and result.battle_outcome == "victory"
        and result.result_successor == CAMPAIGN_AP_RESULT_SUCCESSOR
        and result.terminal_home == CAMPAIGN_AP_TERMINAL_HOME
        and result.refill_seen is False
        and result.ap_after == result.ap_before - cost + result.ap_regenerated
    )


def campaign_ap_drain_verified(
    stage_identity: str, progress: CampaignRouteProgress, *, battle_outcome: str,
    result_successor_verified: bool, terminal_home_verified: bool, refill_seen: bool = False,
) -> bool:
    """Accept a whole AP drain only after every debit and the terminal Home."""
    if (type(stage_identity) is not str or stage_identity not in CAMPAIGN_AP_COSTS
            or type(progress) is not CampaignRouteProgress):
        return False
    integers = (progress.initial_ap, progress.current_ap, progress.completed_runs,
                progress.ap_spent, progress.ap_regenerated)
    if any(type(value) is not int or value < 0 for value in integers):
        return False
    cost = CAMPAIGN_AP_COSTS[stage_identity]
    return bool(0 <= progress.initial_ap <= CAMPAIGN_AP_MAXIMUM_BALANCE
                and 0 <= progress.current_ap < cost
                and 1 <= progress.completed_runs <= CAMPAIGN_DRAIN_MAX_RUNS
                and progress.ap_spent == progress.completed_runs * cost
                and progress.current_ap == progress.initial_ap - progress.ap_spent + progress.ap_regenerated
                and progress.loss_seen is False and refill_seen is False
                and battle_outcome == "victory" and result_successor_verified is True
                and terminal_home_verified is True)


__all__ = [
    "CAMPAIGN_AP_COSTS",
    "CAMPAIGN_AP_CONTROL_CLASS",
    "CAMPAIGN_AP_CURRENCY",
    "CAMPAIGN_AP_ENTRY_CONSEQUENCE",
    "CAMPAIGN_AP_ENTRY_POSTCONDITION",
    "CAMPAIGN_AP_FLOW_ID",
    "CAMPAIGN_AP_MAXIMUM_BALANCE",
    "CAMPAIGN_AP_PRODUCT_ID",
    "CAMPAIGN_AP_PRODUCT_REVISION",
    "CAMPAIGN_AP_RESULT_SUCCESSOR",
    "CAMPAIGN_AP_SEMANTIC_ACTION",
    "CAMPAIGN_AP_SOURCE_STATE",
    "CAMPAIGN_AP_TARGET_PREFIX",
    "CAMPAIGN_AP_TERMINAL_HOME",
    "CampaignApRouteResult",
    "campaign_ap_challenge_policy_request",
    "campaign_ap_challenge_preconditions",
    "campaign_ap_effect_verified",
    "campaign_ap_drain_verified",
]
