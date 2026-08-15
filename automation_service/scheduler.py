"""UTC, restart-safe pulse coordination over the existing invocation repository."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Mapping, Protocol, Sequence

from safe_action_core import SQLiteSchedulerInvocationRepository
from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerTaskOutcome,
)

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
)
from .handlers import FlowHandler
from .registry import load_disabled_registry


class ActivationAuthority(Protocol):
    def permits(self, descriptor: FlowDescriptor, facts: SchedulerFacts) -> bool:
        ...


class DisabledProductionAuthority:
    """Production authority that fail-closes every registry entry."""

    def __init__(self) -> None:
        self._entries = {entry.flow_id: entry for entry in load_disabled_registry()}

    def permits(self, descriptor: FlowDescriptor, facts: SchedulerFacts) -> bool:
        entry = self._entries.get(descriptor.flow_id)
        return bool(
            entry
            and entry.registration_status == "REGISTERED"
            and entry.mode != "disabled"
            and entry.scheduler_eligible
        )


@dataclass(frozen=True)
class PulseCandidate:
    descriptor: FlowDescriptor
    identity: SchedulerIdentity


@dataclass(frozen=True)
class PulseReport:
    candidate: PulseCandidate | None
    result: SchedulerAwareTaskResult | None
    next_wake_utc_epoch: float | None
    reason_code: str


class UtcPulseCoordinator:
    """Select and execute at most one eligible handler per UTC pulse.

    The coordinator intentionally does not instantiate or consult ``tasks.scheduler``.  The
    existing SQLite scheduler-invocation repository is the sole restart-safe task lifecycle.
    """

    def __init__(
        self,
        repository: SQLiteSchedulerInvocationRepository,
        descriptors: Sequence[FlowDescriptor],
        handlers: Mapping[str, FlowHandler],
        *,
        activation_authority: ActivationAuthority,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repository = repository
        self.descriptors = tuple(sorted(descriptors, key=lambda item: (item.priority, item.flow_id)))
        self.handlers = dict(handlers)
        self.activation_authority = activation_authority
        self.clock = clock
        descriptor_ids = [item.flow_id for item in self.descriptors]
        if len(descriptor_ids) != len(set(descriptor_ids)):
            raise ValueError("scheduler descriptors must have unique flow IDs")
        missing = [item.flow_id for item in self.descriptors if item.flow_id not in self.handlers]
        if missing:
            raise ValueError("scheduler handler missing for: " + ", ".join(missing))

    def _now(self, facts: SchedulerFacts | None) -> float:
        now = self.clock() if facts is None else facts.now_utc_epoch
        if not math.isfinite(now) or now < 0:
            raise ValueError("UTC scheduler time must be finite and non-negative")
        return now

    @staticmethod
    def _identity(facts: SchedulerFacts, descriptor: FlowDescriptor) -> SchedulerIdentity:
        return SchedulerIdentity(
            facts.account_id,
            facts.server_id,
            facts.reset_id,
            descriptor.flow_id,
        )

    def _next_wake(self, now: float, facts: SchedulerFacts) -> float | None:
        wakes = [
            state.next_eligible_at
            for descriptor in self.descriptors
            if (
                (state := self.repository.get(self._identity(facts, descriptor))) is not None
                and state.next_eligible_at is not None
                and state.next_eligible_at > now
            )
        ]
        return min(wakes) if wakes else None

    @staticmethod
    def _to_scheduler_result(
        identity: SchedulerIdentity,
        result: NormalizedResult,
    ) -> SchedulerAwareTaskResult:
        kwargs = {
            "verified": result.verified,
            "observed_progress": result.observed_progress,
            "action_count": result.action_count,
            "consequence": result.consequence,
            "evidence_refs": result.evidence_refs,
            "unresolved_action": result.unresolved_action,
        }
        if result.outcome is NormalizedOutcome.ACTION_PERFORMED:
            return SchedulerAwareTaskResult.action_performed(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.DEFERRED:
            return SchedulerAwareTaskResult.deferred(
                identity,
                result.reason_code,
                float(result.next_eligible_at),
                **kwargs,
            )
        if result.outcome is NormalizedOutcome.COMPLETE_FOR_RESET:
            return SchedulerAwareTaskResult.complete_for_reset(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.ALREADY_COMPLETE:
            return SchedulerAwareTaskResult.already_complete(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.MANUAL_REQUIRED:
            return SchedulerAwareTaskResult.manual_required(identity, result.reason_code, **kwargs)
        # The existing scheduler vocabulary has no unresolved outcome. Preserve it as a
        # blocked result and force the global unresolved-action lock.
        kwargs["unresolved_action"] = True
        return SchedulerAwareTaskResult.blocked(identity, result.reason_code, **kwargs)

    def pulse(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
    ) -> PulseReport:
        now = self._now(facts)
        if not facts.health_ok:
            return PulseReport(None, None, self._next_wake(now, facts), "GLOBAL_HEALTH_BREAKER")
        if facts.unresolved_action:
            return PulseReport(None, None, self._next_wake(now, facts), "GLOBAL_UNRESOLVED_ACTION")
        if facts.breakers:
            return PulseReport(None, None, self._next_wake(now, facts), "TASK_BREAKER:" + facts.breakers[0])

        selected: PulseCandidate | None = None
        for descriptor in self.descriptors:
            if not descriptor.scheduler_eligible:
                continue
            if not self.activation_authority.permits(descriptor, facts):
                continue
            identity = self._identity(facts, descriptor)
            if not self.repository.is_eligible(identity, now):
                continue
            handler = self.handlers[descriptor.flow_id]
            if not handler.eligibility(facts, perception):
                continue
            selected = PulseCandidate(descriptor, identity)
            break
        if selected is None:
            return PulseReport(None, None, self._next_wake(now, facts), "NO_ELIGIBLE_TASK")

        handler = self.handlers[selected.descriptor.flow_id]
        plan = handler.plan(facts, perception)
        normalized = (
            plan
            if isinstance(plan, NormalizedResult)
            else handler.reconcile(plan, perception)
        )
        scheduler_result = self._to_scheduler_result(selected.identity, normalized)
        self.repository.apply_result(scheduler_result, now)
        return PulseReport(
            selected,
            scheduler_result,
            self._next_wake(now, facts),
            scheduler_result.reason_code,
        )

    def run(self, facts: SchedulerFacts, *, perception: PerceptionEnvelope | None = None) -> PulseReport:
        return self.pulse(facts, perception=perception)


PulseCoordinator = UtcPulseCoordinator

