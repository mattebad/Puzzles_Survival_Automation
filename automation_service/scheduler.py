"""UTC, restart-safe pulse coordination over the existing invocation repository."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Mapping, Protocol, Sequence

from safe_action_core import SQLiteSchedulerInvocationRepository
from safe_action_core.scheduler_invocation_state import (
    ProjectionInvalidatedError,
    SchedulerConcurrencyError,
)
from tasks.scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerOccurrenceClaim,
    SchedulerTaskOutcome,
)

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    RecurrenceClass,
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
    occurrence_key: str | None = None
    claim: SchedulerOccurrenceClaim | None = None


@dataclass(frozen=True)
class PulseReport:
    candidate: PulseCandidate | None
    result: SchedulerAwareTaskResult | None
    next_wake_utc_epoch: float | None
    reason_code: str


class UtcPulseCoordinator:
    """Select, atomically claim, and execute at most one handler per UTC pulse.

    Selection never binds targets, creates a session, acquires runtime ownership,
    or grants transport authority.
    """

    def __init__(
        self,
        repository: SQLiteSchedulerInvocationRepository,
        descriptors: Sequence[FlowDescriptor],
        handlers: Mapping[str, FlowHandler],
        *,
        activation_authority: ActivationAuthority | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repository = repository
        self.descriptors = tuple(sorted(descriptors, key=lambda item: (item.priority, item.flow_id)))
        self.handlers = dict(handlers)
        self.activation_authority = activation_authority or DisabledProductionAuthority()
        self.clock = clock
        descriptor_ids = [item.flow_id for item in self.descriptors]
        if len(descriptor_ids) != len(set(descriptor_ids)):
            raise ValueError("scheduler descriptors must have unique flow IDs")
        missing = [item.flow_id for item in self.descriptors if item.flow_id not in self.handlers]
        if missing:
            raise ValueError("scheduler handler missing for: " + ", ".join(missing))
        for descriptor in self.descriptors:
            handler = self.handlers[descriptor.flow_id]
            describe = getattr(handler, "describe", None)
            if not callable(describe) or describe().flow_id != descriptor.flow_id:
                raise ValueError("scheduler handler descriptor identity mismatch")

    def _now(self, facts: SchedulerFacts | None) -> float:
        now = self.clock() if facts is None else facts.now_utc_epoch
        if not math.isfinite(now) or now < 0:
            raise ValueError("UTC scheduler time must be finite and non-negative")
        return now

    @staticmethod
    def _identity(facts: SchedulerFacts, descriptor: FlowDescriptor) -> SchedulerIdentity:
        return SchedulerIdentity(facts.account_id, facts.server_id, facts.reset_id, descriptor.flow_id)

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
    def _to_scheduler_result(identity: SchedulerIdentity, result: NormalizedResult) -> SchedulerAwareTaskResult:
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
            return SchedulerAwareTaskResult.deferred(identity, result.reason_code, float(result.next_eligible_at), **kwargs)
        if result.outcome is NormalizedOutcome.COMPLETE_FOR_RESET:
            return SchedulerAwareTaskResult.complete_for_reset(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.ALREADY_COMPLETE:
            return SchedulerAwareTaskResult.already_complete(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.MANUAL_REQUIRED:
            kwargs["unresolved_action"] = False
            return SchedulerAwareTaskResult.manual_required(identity, result.reason_code, **kwargs)
        if result.outcome is NormalizedOutcome.BLOCKED:
            kwargs["unresolved_action"] = False
            return SchedulerAwareTaskResult.blocked(identity, result.reason_code, **kwargs)
        return SchedulerAwareTaskResult.reconciliation_required(identity, result.reason_code, **kwargs)

    @staticmethod
    def _unknown_result(identity: SchedulerIdentity, reason: str) -> SchedulerAwareTaskResult:
        return SchedulerAwareTaskResult.reconciliation_required(
            identity,
            reason,
            verified=False,
            unresolved_action=True,
        )

    @staticmethod
    def _recurrence_allows(
        descriptor: FlowDescriptor, facts: SchedulerFacts, now: float
    ) -> bool:
        recurrence = descriptor.recurrence
        if recurrence is None:
            return True
        projection = facts.projections.get(descriptor.flow_id) or recurrence
        if projection.observed_at_utc is None:
            return False
        if recurrence.recurrence_class in {
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        }:
            if (
                projection is None
                or projection.observed_balance is None
                or projection.observed_at_utc is None
                or projection.observed_at_utc > now
                or now - projection.observed_at_utc > facts.projection_freshness_seconds
            ):
                return False
        if recurrence.recurrence_class in {
            RecurrenceClass.QUEUE_GENERATION,
            RecurrenceClass.MARCH_GENERATION,
        } and (projection is None or not projection.generation):
            return False
        if recurrence.recurrence_class is RecurrenceClass.BOUNDED_REPEAT and (
            recurrence.repeat_limit is None or recurrence.repeat_ordinal >= recurrence.repeat_limit
        ):
            return False
        if recurrence.recurrence_class is RecurrenceClass.EVENT_WINDOW and (
            projection is None
            or projection.window_open_at is None
            or projection.window_close_at is None
            or not (projection.window_open_at <= now < projection.window_close_at)
        ):
            return False
        return not (
            projection is not None
            and projection.next_eligible_at is not None
            and projection.next_eligible_at > now
        )

    def _post_selection_revalidate(
        self,
        handler: FlowHandler,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None,
    ) -> bool:
        revalidate = getattr(handler, "revalidate", None)
        if callable(revalidate):
            return bool(revalidate(facts, perception))
        eligibility = getattr(handler, "eligibility", None)
        return bool(callable(eligibility) and eligibility(facts, perception))

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
        if not facts.clock_ok or facts.clock_rollback:
            return PulseReport(None, None, self._next_wake(now, facts), "UTC_CLOCK_INVALID")
        if not facts.reset_agreement or (
            facts.observed_reset_id is not None and facts.observed_reset_id != facts.reset_id
        ):
            self.repository.record_reset_disagreement(
                facts.account_id,
                facts.server_id,
                facts.reset_id,
                facts.observed_reset_id,
                now,
            )
            return PulseReport(None, None, self._next_wake(now, facts), "RESET_DISAGREEMENT")

        clock_identity = SchedulerIdentity(facts.account_id, facts.server_id, facts.reset_id, "__clock__")
        if not self.repository.observe_clock(clock_identity, now):
            return PulseReport(None, None, self._next_wake(now, facts), "CLOCK_ROLLBACK")

        selected: PulseCandidate | None = None
        for descriptor in self.descriptors:
            if facts.gate_failures(descriptor):
                continue
            if not self._recurrence_allows(descriptor, facts, now):
                continue
            try:
                if not self.activation_authority.permits(descriptor, facts):
                    continue
            except Exception:
                continue
            identity = self._identity(facts, descriptor)
            recurrence_projection = facts.projections.get(descriptor.flow_id) or descriptor.recurrence
            if recurrence_projection is not None:
                if recurrence_projection.observed_at_utc is None:
                    continue
                projection_key = f"{identity.composite_key}|{descriptor.flow_id}"
                try:
                    self.repository.save_projection(
                        identity,
                        projection_key,
                        recurrence_projection,
                        recurrence_projection.observed_at_utc,
                    )
                except ProjectionInvalidatedError:
                    continue
                if not self.repository.projection_is_valid(
                    projection_key, now, facts.projection_freshness_seconds
                ):
                    continue
            if not self.repository.is_eligible(identity, now):
                continue
            handler = self.handlers[descriptor.flow_id]
            try:
                if not handler.eligibility(facts, perception):
                    continue
            except Exception:
                continue
            recurrence_class = (
                descriptor.recurrence_class.value
                if descriptor.recurrence_class is not None
                else descriptor.cadence
            )
            recurrence_projection = facts.projections.get(descriptor.flow_id)
            repeat_ordinal = descriptor.recurrence.repeat_ordinal if descriptor.recurrence else 0
            repeat_limit = descriptor.recurrence.repeat_limit if descriptor.recurrence else None
            if recurrence_class == RecurrenceClass.BOUNDED_REPEAT.value and repeat_limit is not None:
                repeat_ordinal = self.repository.next_repeat_ordinal(identity, repeat_limit)
                if repeat_ordinal is None:
                    continue
            claim = self.repository.claim_occurrence(
                identity,
                now,
                recurrence_class=recurrence_class,
                repeat_ordinal=repeat_ordinal,
                next_eligible_at=(
                    recurrence_projection.next_eligible_at
                    if recurrence_projection is not None
                    else descriptor.recurrence.next_eligible_at
                    if descriptor.recurrence is not None
                    else None
                ),
                projection=(
                    recurrence_projection
                    if recurrence_projection is not None
                    else descriptor.recurrence
                ),
                pulse_token=f"{now:.9f}",
            )
            if claim is not None:
                selected = PulseCandidate(descriptor, identity, claim.occurrence_key, claim)
                break
        if selected is None:
            return PulseReport(None, None, self._next_wake(now, facts), "NO_ELIGIBLE_TASK")

        handler = self.handlers[selected.descriptor.flow_id]
        try:
            post_selection_ok = self._post_selection_revalidate(handler, facts, perception)
        except Exception as exc:
            scheduler_result = self._unknown_result(
                selected.identity,
                "POST_SELECTION_REVALIDATION_EXCEPTION:" + type(exc).__name__,
            )
            self.repository.finalize_claim(selected.claim, scheduler_result, now)
            return PulseReport(selected, scheduler_result, self._next_wake(now, facts), scheduler_result.reason_code)
        if not post_selection_ok:
            self.repository.abandon_claim(selected.claim, now)
            return PulseReport(selected, None, self._next_wake(now, facts), "POST_SELECTION_REVALIDATION_FAILED")

        try:
            plan = handler.plan(facts, perception)
            normalized = plan if isinstance(plan, NormalizedResult) else handler.reconcile(plan, perception)
            if not isinstance(normalized, NormalizedResult):
                raise TypeError("handler did not return a normalized result")
            scheduler_result = self._to_scheduler_result(selected.identity, normalized)
        except Exception as exc:
            scheduler_result = self._unknown_result(
                selected.identity,
                "HANDLER_EXCEPTION_RECONCILIATION_REQUIRED:" + type(exc).__name__,
            )
        try:
            self.repository.finalize_claim(selected.claim, scheduler_result, now)
        except SchedulerConcurrencyError:
            return PulseReport(selected, self._unknown_result(selected.identity, "CLAIM_CAS_FAILED"), self._next_wake(now, facts), "CLAIM_CAS_FAILED")
        return PulseReport(
            selected,
            scheduler_result,
            self._next_wake(now, facts),
            scheduler_result.reason_code,
        )

    def run(self, facts: SchedulerFacts, *, perception: PerceptionEnvelope | None = None) -> PulseReport:
        return self.pulse(facts, perception=perception)


PulseCoordinator = UtcPulseCoordinator
