"""Offline adapter for the selected-Daily 20 AP Campaign objective."""

from __future__ import annotations

from dataclasses import dataclass

from .campaign_ap import (
    CAMPAIGN_SCREEN,
    CampaignAPObservation,
    campaign_ap_authorizeable,
    campaign_ap_postcondition_verified,
    campaign_ap_transaction_spec,
)
from .contracts import ActionTransactionSpec, TaskOutcome, TaskResult


DAILY_CAMPAIGN_AP_OBJECTIVE = "consume_ap"
DAILY_CAMPAIGN_AP_TARGET = 20
DAILY_CAMPAIGN_AP_COMPLETION = "daily-campaign-ap:completed"


@dataclass(frozen=True)
class DailyCampaignAPObservation:
    """Selected-Daily row plus one current-frame Campaign AP observation."""

    selected_daily_row: bool
    objective_key: str
    daily_progress_before: int
    campaign: CampaignAPObservation
    daily_progress_after: int | None = None
    successor_state: str = ""


def daily_campaign_ap_authorizeable(
    observation: DailyCampaignAPObservation,
) -> bool:
    """Require exact Daily identity and an explicit bounded AP action."""

    return bool(
        observation.selected_daily_row
        and observation.objective_key == DAILY_CAMPAIGN_AP_OBJECTIVE
        and 0 <= observation.daily_progress_before < DAILY_CAMPAIGN_AP_TARGET
        and campaign_ap_authorizeable(observation.campaign)
        and observation.daily_progress_before + observation.campaign.ap_cost
        <= DAILY_CAMPAIGN_AP_TARGET
    )


def daily_campaign_ap_transaction_spec(
    observation: DailyCampaignAPObservation,
) -> ActionTransactionSpec:
    if not daily_campaign_ap_authorizeable(observation):
        raise ValueError("Daily Campaign AP preconditions are not positively recognized")
    return campaign_ap_transaction_spec(observation.campaign)


def daily_campaign_ap_postcondition_verified(
    before: DailyCampaignAPObservation,
    after: DailyCampaignAPObservation | None,
) -> bool:
    """Require exact AP and Daily progress deltas for one bounded action."""

    if not daily_campaign_ap_authorizeable(before) or after is None:
        return False
    return bool(
        after.selected_daily_row
        and after.objective_key == DAILY_CAMPAIGN_AP_OBJECTIVE
        and after.daily_progress_after
        == before.daily_progress_before + before.campaign.ap_cost
        and after.successor_state
        == (
            "DAILY_CAMPAIGN_AP_COMPLETE"
            if after.daily_progress_after == DAILY_CAMPAIGN_AP_TARGET
            else "DAILY_CAMPAIGN_AP_PROGRESS"
        )
        and after.campaign.game_day_id == before.campaign.game_day_id
        and campaign_ap_postcondition_verified(before.campaign, after.campaign)
    )


def daily_campaign_ap_replay(
    before: DailyCampaignAPObservation,
    after: DailyCampaignAPObservation | None = None,
) -> TaskResult:
    """Replay pure Campaign evidence; AP transport remains evidence-gated."""

    if not daily_campaign_ap_authorizeable(before):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_AUTHORIZED_DAILY_CAMPAIGN_AP",
            verified=True,
            state=CAMPAIGN_SCREEN,
            details={"dispatch_count": 0},
        )
    if after is None:
        return TaskResult.progress(
            "Daily Campaign AP action is recognized; dispatch remains evidence-gated",
            CAMPAIGN_SCREEN,
            dispatch_count=0,
        )
    if not daily_campaign_ap_postcondition_verified(before, after):
        return TaskResult(
            TaskOutcome.FAILED_SAFE,
            "DAILY_CAMPAIGN_AP_POSTCONDITION_NOT_PROVEN",
            verified=True,
            state=CAMPAIGN_SCREEN,
            details={"dispatch_count": 0},
        )
    if after.daily_progress_after != DAILY_CAMPAIGN_AP_TARGET:
        return TaskResult.progress(
            "Daily Campaign AP progress replay verified",
            CAMPAIGN_SCREEN,
            dispatch_count=0,
            daily_progress=after.daily_progress_after,
        )
    return TaskResult.done(
        "Daily Campaign AP postcondition verified",
        DAILY_CAMPAIGN_AP_COMPLETION,
        CAMPAIGN_SCREEN,
        dispatch_count=0,
    )
