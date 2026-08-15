"""Offline Campaign navigation handler using the existing Campaign/Home seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tasks.campaign_atlas import (
    NAVIGATION_BLOCKED_FAIL_CLOSED,
    NAVIGATION_EVIDENCE_REQUIRED,
    ZERO_TRANSPORT_REPLAY_COMPLETE,
    plan_shared_campaign_destination_navigation,
)
from tasks.campaign_auto_battle import parse_supported_campaign_story_destination

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
)


CAMPAIGN_FLOW_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
FORBIDDEN_CAMPAIGN_INPUTS = frozenset({"sweep", "blitz", "auto_complete", "ap_refill"})
FORBIDDEN_NAVIGATION_ACTIONS = frozenset(
    {"ap", "challenge", "auto_battle", *FORBIDDEN_CAMPAIGN_INPUTS}
)


@dataclass(frozen=True)
class CampaignNavigationPlan:
    destination: str
    decision: Any
    navigation_only: bool = True


class CampaignNavigationHandler:
    """Navigation-only Campaign handler; AP and battle transitions are not exposed."""

    def __init__(self, destination: str = "1-20-9") -> None:
        stage = parse_supported_campaign_story_destination(destination)
        self.destination = stage.identity

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=CAMPAIGN_FLOW_ID,
            owner="automation_service",
            family="campaign",
            variant="navigation_only",
            cadence="evidence_gated",
            priority=25,
            scheduler_eligible=False,
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        if not facts.health_ok or facts.unresolved_action or facts.breakers:
            return False
        if perception is None:
            return True
        return (
            perception.context in {"home", "home_canonical", "canonical_home"}
            and not perception.invalidated_after_input
            and not any(
                item.casefold() in FORBIDDEN_NAVIGATION_ACTIONS
                for item in perception.negative_evidence
            )
        )

    @staticmethod
    def _family_values(perception: PerceptionEnvelope | None) -> Mapping[str, Any]:
        if perception is None:
            return {}
        facts = perception.facts_for("campaign")
        return {} if facts is None else facts.values

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> CampaignNavigationPlan | NormalizedResult:
        if perception is None:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_PERCEPTION_REQUIRED",
                verified=False,
            )
        values = self._family_values(perception)
        decision = plan_shared_campaign_destination_navigation(
            consumer="campaign_stage",
            destination_id=self.destination,
            localization=values.get("localization"),
            binding=values.get("binding"),
            atlas=values.get("atlas"),
        )
        return CampaignNavigationPlan(self.destination, decision)

    def reconcile(
        self,
        plan: CampaignNavigationPlan | NormalizedResult,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        decision = plan.decision
        terminal = getattr(decision, "terminal", "")
        if terminal == ZERO_TRANSPORT_REPLAY_COMPLETE:
            return NormalizedResult(
                NormalizedOutcome.COMPLETE_FOR_RESET,
                "CAMPAIGN_NAVIGATION_ONLY_COMPLETE",
                observed_progress={"destination": plan.destination, "navigation_only": True},
            )
        if terminal == NAVIGATION_EVIDENCE_REQUIRED:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_NAVIGATION_EVIDENCE_REQUIRED",
                verified=False,
                observed_progress={"destination": plan.destination},
            )
        if terminal == NAVIGATION_BLOCKED_FAIL_CLOSED:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_NAVIGATION_BLOCKED_FAIL_CLOSED",
                verified=False,
                observed_progress={"destination": plan.destination},
            )
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_NAVIGATION_UNKNOWN_DECISION",
            verified=False,
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_NAVIGATION_RECOVERY_REQUIRES_RECOGNIZED_SAFE_EXIT",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": CAMPAIGN_FLOW_ID,
            "destination": self.destination,
            "mode": "navigation_only",
            "forbidden_inputs": sorted(FORBIDDEN_CAMPAIGN_INPUTS),
            "transport_count": 0,
            "registration_status": "NOT_REGISTERED",
            "scheduler_eligible": False,
        }

