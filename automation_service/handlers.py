"""Capability-specific handler protocol for the service composition layer."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
)


class FlowHandler(Protocol):
    """Handlers own action semantics; shared context and scheduling stay outside."""

    def describe(self) -> FlowDescriptor:
        ...

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        ...

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> SemanticActionIntent | Any:
        ...

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
    ) -> NormalizedResult:
        ...

    def recover(self, reason_code: str) -> NormalizedResult:
        ...

    def summarize(self) -> Mapping[str, Any]:
        ...


class DisabledHandler:
    """Explicit placeholder for flows that are not production-registered."""

    def revalidate(self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None) -> bool:
        return False

    def __init__(self, descriptor: FlowDescriptor) -> None:
        self._descriptor = descriptor

    def describe(self) -> FlowDescriptor:
        return self._descriptor

    def eligibility(self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None) -> bool:
        return False

    def plan(self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None) -> None:
        return None

    def reconcile(self, plan: Any, perception: PerceptionEnvelope | None = None) -> NormalizedResult:
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

