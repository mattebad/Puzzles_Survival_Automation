"""Capability-specific handler protocol for the service composition layer."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    RecurrenceClass,
    RecurrenceProjection,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
)
from .registry import (
    CAMPAIGN_FLOW_ID,
    CAMPAIGN_HANDLER_ID,
    CAMPAIGN_PHASE_MODE,
    CAMPAIGN_PRODUCT_ID,
    CAMPAIGN_PRODUCT_REVISION,
    CAMPAIGN_PROFILE_ID,
    RegisteredDispatchSnapshot,
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RECRUITMENT_FLOW_ID,
    RECRUITMENT_HANDLER_ID,
    RECRUITMENT_PHASE_MODE,
    RECRUITMENT_PRODUCT_ID,
    RECRUITMENT_PRODUCT_REVISION,
    RECRUITMENT_PROFILE_ID,
    WORLD_FLOW_ID,
    WORLD_HANDLER_ID,
    WORLD_PHASE_MODE,
    WORLD_PRODUCT_ID,
    WORLD_PRODUCT_REVISION,
    WORLD_PROFILE_ID,
)


class FlowHandler(Protocol):
    """Handlers own action semantics; shared context and scheduling stay outside."""

    def describe(self) -> FlowDescriptor: ...

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool: ...

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> SemanticActionIntent | Any: ...

    def revalidate(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        """Re-enter the accepted product boundary after an atomic claim."""
        ...

    def reconcile(
        self,
        plan: SemanticActionIntent | Any,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult: ...

    def recover(self, reason_code: str) -> NormalizedResult: ...

    def summarize(self) -> Mapping[str, Any]: ...


class DisabledHandler:
    """Explicit placeholder for flows that are not production-registered."""

    def revalidate(
        self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None
    ) -> bool:
        return False

    def __init__(self, descriptor: FlowDescriptor) -> None:
        self._descriptor = descriptor

    def describe(self) -> FlowDescriptor:
        return self._descriptor

    def eligibility(
        self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None
    ) -> bool:
        return False

    def plan(
        self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None
    ) -> None:
        return None

    def reconcile(
        self, plan: Any, perception: PerceptionEnvelope | None = None
    ) -> NormalizedResult:
        return NormalizedResult(
            outcome=NormalizedOutcome.BLOCKED,
            reason_code="HANDLER_DISABLED",
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            outcome=NormalizedOutcome.BLOCKED,
            reason_code=reason_code or "HANDLER_DISABLED",
        )

    def summarize(self) -> Mapping[str, Any]:
        return {"flow_id": self._descriptor.flow_id, "mode": "disabled"}


class WorldNavigationSelectionHandler:
    """Zero-transport selector for the one registered World phase canary.

    This handler exists only to hand a parent a terminal scheduler selection.
    It has no runtime, target, route, or transport capability.
    """

    handler_id = WORLD_HANDLER_ID

    def __init__(self, snapshot: RegisteredDispatchSnapshot | None = None) -> None:
        if snapshot is None:
            snapshot = RegisteredDispatchSnapshot(
                flow_id=WORLD_FLOW_ID,
                product_id=WORLD_PRODUCT_ID,
                product_revision=WORLD_PRODUCT_REVISION,
                production_handler=WORLD_HANDLER_ID,
                profile=WORLD_PROFILE_ID,
                mode=WORLD_PHASE_MODE,
                registration_status="REGISTERED",
                scheduler_eligible=True,
            )
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("World selection requires a typed registration snapshot")
        self._snapshot = snapshot
        self.plan_calls = 0

    @property
    def snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=WORLD_FLOW_ID,
            owner="automation_service",
            family="world_map_navigation",
            variant="navigation_only",
            cadence="daily_once_per_reset",
            priority=1,
            scheduler_eligible=True,
            accepted_product=WORLD_PRODUCT_ID,
            product_revision=WORLD_PRODUCT_REVISION,
            registration_status="REGISTERED",
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        descriptor = self.describe()
        if facts.gate_failures(descriptor):
            return False
        if (
            facts.accepted_product != WORLD_PRODUCT_ID
            or facts.product_revision != WORLD_PRODUCT_REVISION
            or facts.registration_status != "REGISTERED"
            or facts.scheduler_eligible is not True
            or facts.owner_available is not True
            or facts.clock_ok is not True
            or facts.clock_rollback is True
            or facts.reset_agreement is not True
        ):
            return False
        if perception is not None and perception.profile_id != WORLD_PROFILE_ID:
            return False
        return True

    def revalidate(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        return self.eligibility(facts, perception)

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        self.plan_calls += 1
        if not self.eligibility(facts, perception):
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "WORLD_NAVIGATION_SELECTION_GATES_FAILED",
                verified=False,
                observed_progress={"transport_count": 0},
            )
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "WORLD_NAVIGATION_PARENT_CANARY_REQUIRED",
            verified=True,
            observed_progress={
                "transport_count": 0,
                "accepted_product": WORLD_PRODUCT_ID,
                "product_revision": WORLD_PRODUCT_REVISION,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "runtime_owner_available": facts.owner_available,
                "clock_ok": facts.clock_ok,
                "clock_rollback": facts.clock_rollback,
                "reset_agreement": facts.reset_agreement,
                "unresolved_occurrence": False,
                "registration_snapshot": self._snapshot.to_mapping(),
            },
        )

    def reconcile(
        self,
        plan: SemanticActionIntent | Any,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "WORLD_NAVIGATION_SELECTION_UNKNOWN_PLAN",
            verified=False,
            observed_progress={"transport_count": 0},
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "WORLD_NAVIGATION_SELECTION_RECOVERY_UNAVAILABLE",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": WORLD_FLOW_ID,
            "handler_id": WORLD_HANDLER_ID,
            "mode": WORLD_PHASE_MODE,
            "product_id": WORLD_PRODUCT_ID,
            "product_revision": WORLD_PRODUCT_REVISION,
            "profile": WORLD_PROFILE_ID,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "transport_count": 0,
            "plan_calls": self.plan_calls,
        }


class NovaPraiseSelectionHandler:
    """Zero-transport selector for the registered Nova Praise promotion."""

    handler_id = NOVA_HANDLER_ID

    def __init__(self, snapshot: RegisteredDispatchSnapshot | None = None) -> None:
        if snapshot is None:
            snapshot = RegisteredDispatchSnapshot(
                flow_id=NOVA_FLOW_ID,
                product_id=NOVA_PRODUCT_ID,
                product_revision=NOVA_PRODUCT_REVISION,
                production_handler=NOVA_HANDLER_ID,
                profile=NOVA_PROFILE_ID,
                mode=NOVA_PHASE_MODE,
                registration_status="REGISTERED",
                scheduler_eligible=True,
            )
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Nova selection requires a typed registration snapshot")
        self._snapshot = snapshot
        self.plan_calls = 0

    @property
    def snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=NOVA_FLOW_ID,
            owner="automation_service",
            family="nova_praise",
            variant="supervised_one_free_pulse",
            cadence="daily_once_per_reset",
            priority=1,
            scheduler_eligible=True,
            accepted_product=NOVA_PRODUCT_ID,
            product_revision=NOVA_PRODUCT_REVISION,
            registration_status="REGISTERED",
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        descriptor = self.describe()
        if facts.gate_failures(descriptor):
            return False
        if (
            facts.accepted_product != NOVA_PRODUCT_ID
            or facts.product_revision != NOVA_PRODUCT_REVISION
            or facts.registration_status != "REGISTERED"
            or facts.scheduler_eligible is not True
            or facts.owner_available is not True
            or facts.clock_ok is not True
            or facts.clock_rollback is True
            or facts.reset_agreement is not True
        ):
            return False
        if perception is not None and perception.profile_id != NOVA_PROFILE_ID:
            return False
        return True

    def revalidate(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        return self.eligibility(facts, perception)

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        self.plan_calls += 1
        if not self.eligibility(facts, perception):
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "NOVA_PRAISE_SELECTION_GATES_FAILED",
                verified=False,
                observed_progress={"transport_count": 0},
            )
        snapshot = self._snapshot.to_mapping()
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "NOVA_PRAISE_PARENT_CANARY_REQUIRED",
            verified=True,
            observed_progress={
                "transport_count": 0,
                "accepted_product": NOVA_PRODUCT_ID,
                "product_revision": NOVA_PRODUCT_REVISION,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "runtime_owner_available": facts.owner_available,
                "clock_ok": facts.clock_ok,
                "clock_rollback": facts.clock_rollback,
                "reset_agreement": facts.reset_agreement,
                "unresolved_occurrence": False,
                "registration_snapshot": snapshot,
                "dispatch_registration": dict(snapshot),
            },
        )

    def reconcile(
        self,
        plan: SemanticActionIntent | Any,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "NOVA_PRAISE_SELECTION_UNKNOWN_PLAN",
            verified=False,
            observed_progress={"transport_count": 0},
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "NOVA_PRAISE_SELECTION_RECOVERY_UNAVAILABLE",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": NOVA_FLOW_ID,
            "handler_id": NOVA_HANDLER_ID,
            "mode": NOVA_PHASE_MODE,
            "product_id": NOVA_PRODUCT_ID,
            "product_revision": NOVA_PRODUCT_REVISION,
            "profile": NOVA_PROFILE_ID,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "transport_count": 0,
            "plan_calls": self.plan_calls,
            "registration_snapshot": self._snapshot.to_mapping(),
        }


class RecruitmentMaintenanceSelectionHandler:
    """Zero-transport selector for the Recruitment cooldown canary."""

    handler_id = RECRUITMENT_HANDLER_ID

    def __init__(self, snapshot: RegisteredDispatchSnapshot | None = None) -> None:
        if snapshot is None:
            snapshot = RegisteredDispatchSnapshot(
                flow_id=RECRUITMENT_FLOW_ID,
                product_id=RECRUITMENT_PRODUCT_ID,
                product_revision=RECRUITMENT_PRODUCT_REVISION,
                production_handler=RECRUITMENT_HANDLER_ID,
                profile=RECRUITMENT_PROFILE_ID,
                mode=RECRUITMENT_PHASE_MODE,
                registration_status="REGISTERED",
                scheduler_eligible=True,
            )
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError(
                "Recruitment selection requires a typed registration snapshot"
            )
        if snapshot.flow_id != RECRUITMENT_FLOW_ID:
            raise ValueError(
                "Recruitment selection snapshot has the wrong flow identity"
            )
        self._snapshot = snapshot
        self.plan_calls = 0

    @property
    def snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=RECRUITMENT_FLOW_ID,
            owner="automation_service",
            family="recruitment",
            variant="free_attempt_maintenance",
            cadence="cooldown_pulse",
            priority=1,
            reset_scoped=False,
            scheduler_eligible=True,
            accepted_product=RECRUITMENT_PRODUCT_ID,
            product_revision=RECRUITMENT_PRODUCT_REVISION,
            registration_status="REGISTERED",
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        descriptor = self.describe()
        if facts.gate_failures(descriptor):
            return False
        if (
            facts.accepted_product != RECRUITMENT_PRODUCT_ID
            or facts.product_revision != RECRUITMENT_PRODUCT_REVISION
            or facts.registration_status != "REGISTERED"
            or facts.scheduler_eligible is not True
            or facts.owner_available is not True
            or facts.clock_ok is not True
            or facts.clock_rollback is True
            or facts.reset_agreement is not True
        ):
            return False
        projection = facts.projections.get(RECRUITMENT_FLOW_ID)
        if (
            projection is None
            or projection.recurrence_class is not RecurrenceClass.COOLDOWN
            or projection.observed_at_utc is None
            or projection.observed_at_utc > facts.now_utc_epoch
            or facts.now_utc_epoch - projection.observed_at_utc
            > facts.projection_freshness_seconds
            or (
                projection.next_eligible_at is not None
                and projection.next_eligible_at > facts.now_utc_epoch
            )
        ):
            return False
        if perception is not None and perception.profile_id != RECRUITMENT_PROFILE_ID:
            return False
        return True

    def revalidate(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        return self.eligibility(facts, perception)

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        self.plan_calls += 1
        if not self.eligibility(facts, perception):
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "RECRUITMENT_MAINTENANCE_SELECTION_GATES_FAILED",
                verified=False,
                observed_progress={"transport_count": 0},
            )
        projection = facts.projections[RECRUITMENT_FLOW_ID]
        snapshot = self._snapshot.to_mapping()
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "RECRUITMENT_MAINTENANCE_PARENT_CANARY_REQUIRED",
            verified=True,
            observed_progress={
                "transport_count": 0,
                "accepted_product": RECRUITMENT_PRODUCT_ID,
                "product_revision": RECRUITMENT_PRODUCT_REVISION,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "projection_observed_at_utc": projection.observed_at_utc,
                "projection_next_eligible_at": projection.next_eligible_at,
                "registration_snapshot": snapshot,
                "dispatch_registration": dict(snapshot),
            },
        )

    def reconcile(
        self,
        plan: SemanticActionIntent | Any,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "RECRUITMENT_MAINTENANCE_SELECTION_UNKNOWN_PLAN",
            verified=False,
            observed_progress={"transport_count": 0},
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "RECRUITMENT_MAINTENANCE_SELECTION_RECOVERY_UNAVAILABLE",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": RECRUITMENT_FLOW_ID,
            "handler_id": RECRUITMENT_HANDLER_ID,
            "mode": RECRUITMENT_PHASE_MODE,
            "product_id": RECRUITMENT_PRODUCT_ID,
            "product_revision": RECRUITMENT_PRODUCT_REVISION,
            "profile": RECRUITMENT_PROFILE_ID,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "transport_count": 0,
            "plan_calls": self.plan_calls,
            "registration_snapshot": self._snapshot.to_mapping(),
        }


class CampaignApSelectionHandler:
    """Zero-transport selector for the Campaign AP canary."""

    handler_id = CAMPAIGN_HANDLER_ID
    minimum_observed_ap = 14.0

    def __init__(self, snapshot: RegisteredDispatchSnapshot | None = None) -> None:
        if snapshot is None:
            snapshot = RegisteredDispatchSnapshot(
                flow_id=CAMPAIGN_FLOW_ID,
                product_id=CAMPAIGN_PRODUCT_ID,
                product_revision=CAMPAIGN_PRODUCT_REVISION,
                production_handler=CAMPAIGN_HANDLER_ID,
                profile=CAMPAIGN_PROFILE_ID,
                mode=CAMPAIGN_PHASE_MODE,
                registration_status="REGISTERED",
                scheduler_eligible=True,
            )
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Campaign AP selection requires a typed registration snapshot")
        if snapshot.flow_id != CAMPAIGN_FLOW_ID:
            raise ValueError("Campaign AP selection snapshot has the wrong flow identity")
        self._snapshot = snapshot
        self.plan_calls = 0

    @property
    def snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=CAMPAIGN_FLOW_ID,
            owner="automation_service",
            family="campaign_ap",
            variant="one_auto_battle",
            cadence="ap_regeneration_pulse",
            priority=1,
            reset_scoped=False,
            scheduler_eligible=True,
            accepted_product=CAMPAIGN_PRODUCT_ID,
            product_revision=CAMPAIGN_PRODUCT_REVISION,
            registration_status="REGISTERED",
            recurrence=RecurrenceProjection(
                RecurrenceClass.AP_REGENERATION,
                observed_at_utc=0.0,
                observed_balance=0.0,
            ),
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        descriptor = self.describe()
        if facts.gate_failures(descriptor):
            return False
        if (
            facts.accepted_product != CAMPAIGN_PRODUCT_ID
            or facts.product_revision != CAMPAIGN_PRODUCT_REVISION
            or facts.registration_status != "REGISTERED"
            or facts.scheduler_eligible is not True
            or facts.owner_available is not True
            or facts.clock_ok is not True
            or facts.clock_rollback is True
            or facts.reset_agreement is not True
        ):
            return False
        projection = facts.projections.get(CAMPAIGN_FLOW_ID)
        if (
            projection is None
            or projection.recurrence_class is not RecurrenceClass.AP_REGENERATION
            or projection.observed_at_utc is None
            or projection.observed_balance is None
            or projection.observed_balance < self.minimum_observed_ap
            or projection.observed_at_utc > facts.now_utc_epoch
            or facts.now_utc_epoch - projection.observed_at_utc
            > facts.projection_freshness_seconds
            or (
                projection.next_eligible_at is not None
                and projection.next_eligible_at > facts.now_utc_epoch
            )
        ):
            return False
        if perception is not None and perception.profile_id != CAMPAIGN_PROFILE_ID:
            return False
        return True

    def revalidate(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        return self.eligibility(facts, perception)

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        self.plan_calls += 1
        if not self.eligibility(facts, perception):
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_AP_SELECTION_GATES_FAILED",
                verified=False,
                observed_progress={"transport_count": 0},
            )
        projection = facts.projections[CAMPAIGN_FLOW_ID]
        snapshot = self._snapshot.to_mapping()
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "CAMPAIGN_AP_PARENT_CANARY_REQUIRED",
            verified=True,
            observed_progress={
                "transport_count": 0,
                "accepted_product": CAMPAIGN_PRODUCT_ID,
                "product_revision": CAMPAIGN_PRODUCT_REVISION,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "projection_observed_at_utc": projection.observed_at_utc,
                "projection_observed_balance": projection.observed_balance,
                "projection_next_eligible_at": projection.next_eligible_at,
                "registration_snapshot": snapshot,
                "dispatch_registration": dict(snapshot),
            },
        )

    def reconcile(
        self,
        plan: SemanticActionIntent | Any,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_AP_SELECTION_UNKNOWN_PLAN",
            verified=False,
            observed_progress={"transport_count": 0},
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_AP_SELECTION_RECOVERY_UNAVAILABLE",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": CAMPAIGN_FLOW_ID,
            "handler_id": CAMPAIGN_HANDLER_ID,
            "mode": CAMPAIGN_PHASE_MODE,
            "product_id": CAMPAIGN_PRODUCT_ID,
            "product_revision": CAMPAIGN_PRODUCT_REVISION,
            "profile": CAMPAIGN_PROFILE_ID,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "transport_count": 0,
            "plan_calls": self.plan_calls,
            "registration_snapshot": self._snapshot.to_mapping(),
        }


# Stable concise aliases for callers that use either terminology.
WorldSelectionHandler = WorldNavigationSelectionHandler
WorldNavigationHandler = WorldNavigationSelectionHandler
NovaSelectionHandler = NovaPraiseSelectionHandler
NovaPraiseHandler = NovaPraiseSelectionHandler
RecruitmentSelectionHandler = RecruitmentMaintenanceSelectionHandler
CampaignSelectionHandler = CampaignApSelectionHandler
