"""UTC, restart-safe pulse coordination over the existing invocation repository."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
    RecurrenceProjection,
    SchedulerFacts,
)
from .handlers import FlowHandler
from .state import (
    BotStateManager,
    FlowState,
    RunRecord,
    RunState,
    StateBusyError,
    TerminalProjectionError,
)
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
    claim: SchedulerOccurrenceClaim | RunRecord | None = None


@dataclass(frozen=True)
class PulseReport:
    candidate: PulseCandidate | None
    result: SchedulerAwareTaskResult | None
    next_wake_utc_epoch: float | None
    reason_code: str


class _CanonicalPulseCoordinator:
    """SQLite-backed scheduler using :class:`BotStateManager` exclusively."""

    def __init__(
        self,
        state: BotStateManager,
        descriptors: Sequence[FlowDescriptor],
        handlers: Mapping[str, FlowHandler],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state = state
        self.descriptors = tuple(
            sorted(descriptors, key=lambda item: (item.priority, item.flow_id))
        )
        self.handlers = dict(handlers)
        self.clock = clock

    @staticmethod
    def _identity(facts: SchedulerFacts, descriptor: FlowDescriptor) -> SchedulerIdentity:
        return SchedulerIdentity(
            facts.account_id, facts.server_id, facts.reset_id, descriptor.flow_id
        )

    @staticmethod
    def _runtime_gate_reason(facts: SchedulerFacts) -> str | None:
        if not facts.health_ok:
            return "GLOBAL_HEALTH_BREAKER"
        if facts.unresolved_action:
            return "GLOBAL_UNRESOLVED_ACTION"
        if facts.breakers:
            return "TASK_BREAKER:" + facts.breakers[0]
        if not facts.owner_available:
            return "SINGLETON_OWNER_UNAVAILABLE"
        if not facts.clock_ok or facts.clock_rollback:
            return "UTC_CLOCK_INVALID"
        if not facts.reset_agreement or (
            facts.observed_reset_id is not None
            and facts.observed_reset_id != facts.reset_id
        ):
            return "RESET_DISAGREEMENT"
        return None
    def _clock_allows_selection(self, now: float) -> bool:
        """Read the persisted wall-clock high-water before selection."""

        get_clock = getattr(self.state, "get_clock", None)
        if not callable(get_clock):
            return False
        observation = get_clock()
        high_water = getattr(observation, "high_water_utc", None)
        return high_water is None or float(high_water) <= now

    def _observe_clock(self, now: float) -> bool:
        """Advance the canonical clock high-water, rejecting rollback."""

        observe_clock = getattr(self.state, "observe_clock", None)
        if not callable(observe_clock):
            return False
        observation = observe_clock(now_utc_epoch=now)
        return bool(getattr(observation, "accepted", False)) and not bool(
            getattr(observation, "clock_rollback", False)
        )

    def _next_wake(
        self, now: float, facts: SchedulerFacts | None = None
    ) -> float | None:
        wakes: list[float] = []
        for descriptor in self.descriptors:
            state = self.state.get_flow(descriptor.flow_id)
            if state is not None:
                for deadline in (state.next_due_at_utc, state.retry_not_before_utc):
                    if deadline is not None and float(deadline) > now:
                        wakes.append(float(deadline))
            if facts is not None:
                projection = self._recurrence_projection(descriptor, facts)
                if (
                    projection is not None
                    and projection.next_eligible_at is not None
                    and projection.next_eligible_at > now
                ):
                    wakes.append(float(projection.next_eligible_at))
        return min(wakes) if wakes else None

    @staticmethod
    def _recurrence_projection(
        descriptor: FlowDescriptor, facts: SchedulerFacts
    ) -> RecurrenceProjection | None:
        """Return the fact-bound projection for a descriptor's recurrence.

        A projection supplied by the caller is authoritative, but it must still
        describe the same recurrence class as the static descriptor.  Falling
        back to the descriptor projection is safe for static time/cadence
        metadata and keeps selection deterministic.
        """

        expected = descriptor.recurrence_class
        projection = facts.projections.get(descriptor.flow_id)
        if projection is not None and expected is not None:
            if projection.recurrence_class is not expected:
                return None
        if projection is None:
            projection = descriptor.recurrence
        return projection

    @staticmethod
    def _projection_key(projection: RecurrenceProjection | None) -> str | None:
        """Return a stable identity for one accepted recurrence projection.

        Observation timestamps are freshness metadata, not occurrence identity.
        In particular, rescanning the same timer slot or generation must not
        create a second occurrence merely because the frame was captured later.
        """

        if projection is None:
            return None
        recurrence_class = projection.recurrence_class
        if recurrence_class in {RecurrenceClass.TIMER, RecurrenceClass.COOLDOWN}:
            values = (recurrence_class.value, projection.next_eligible_at)
        elif recurrence_class in {
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
            RecurrenceClass.QUEUE_GENERATION,
            RecurrenceClass.MARCH_GENERATION,
        } and projection.generation is not None:
            values = (recurrence_class.value, projection.generation)
        elif recurrence_class is RecurrenceClass.BOUNDED_REPEAT:
            values = (
                recurrence_class.value,
                projection.generation,
                projection.repeat_ordinal,
            )
        elif recurrence_class is RecurrenceClass.EVENT_WINDOW:
            values = (
                recurrence_class.value,
                projection.window_open_at,
                projection.window_close_at,
            )
        else:
            values = (
                recurrence_class.value,
                projection.next_eligible_at,
                projection.generation,
                projection.observed_balance,
                projection.repeat_ordinal,
                projection.repeat_limit,
                projection.window_open_at,
                projection.window_close_at,
            )
        return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()

    @classmethod
    def _occurrence_binding(
        cls,
        descriptor: FlowDescriptor,
        facts: SchedulerFacts,
        state: FlowState,
        *,
        mode: str = "scheduled",
        operator_request_id: str | None = None,
        ordinal: int | None = None,
    ) -> dict[str, object]:
        """Translate descriptor facts into the state claim identity contract."""

        occurrence_ordinal = state.next_occurrence_key if ordinal is None else ordinal
        if mode == "manual":
            if operator_request_id is None or not operator_request_id.strip():
                raise ValueError("manual pulse requires operator_request_id")
            basis = operator_request_id.strip()
            return {
                "occurrence_kind": "manual",
                "occurrence_basis": basis,
                "operator_request_id": basis,
                "occurrence_key": BotStateManager.occurrence_key(
                    descriptor.flow_id,
                    facts.reset_id,
                    occurrence_ordinal,
                    occurrence_kind="manual",
                    occurrence_basis=basis,
                    operator_request_id=basis,
                ),
            }

        recurrence_class = descriptor.recurrence_class
        projection = cls._recurrence_projection(descriptor, facts)
        if recurrence_class is None or recurrence_class in {
            RecurrenceClass.DAILY_ONCE_PER_RESET,
            RecurrenceClass.RESET_BOUNDED,
        }:
            kind = (
                "daily"
                if recurrence_class is None
                else recurrence_class.value
            )
            basis = facts.reset_id
            return {
                "occurrence_kind": kind,
                "occurrence_basis": basis,
                "occurrence_key": BotStateManager.occurrence_key(
                    descriptor.flow_id,
                    facts.reset_id,
                    occurrence_ordinal,
                    occurrence_kind=kind,
                    occurrence_basis=basis,
                ),
            }

        kind = recurrence_class.value
        retry_basis = (
            state.next_occurrence_basis
            if mode == "scheduled"
            and state.retry_not_before_utc is not None
            and state.next_occurrence_kind.replace("-", "_").lower() == kind
            else None
        )
        values: dict[str, object] = {
            "occurrence_kind": kind,
        }
        if recurrence_class in {RecurrenceClass.TIMER, RecurrenceClass.COOLDOWN}:
            slot: float | str | None = (
                retry_basis
                if retry_basis is not None
                else projection.next_eligible_at
                if projection is not None and projection.next_eligible_at is not None
                else state.schedule_anchor_utc
            )
            if slot is None and projection is not None:
                slot = projection.observed_at_utc
            if slot is None:
                raise ValueError("timer/cooldown occurrence requires a persisted slot")
            values.update({"timer_slot": slot, "occurrence_basis": str(slot)})
        elif recurrence_class in {
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        }:
            generation = (
                retry_basis
                if retry_basis is not None
                else projection.generation
                if projection is not None and projection.generation is not None
                else cls._projection_key(projection)
            )
            if generation is None:
                raise ValueError("resource occurrence requires projection generation")
            values.update(
                {
                    "projection_generation": generation,
                    "occurrence_basis": str(generation),
                }
            )
        elif recurrence_class is RecurrenceClass.BOUNDED_REPEAT:
            if retry_basis is not None and ":" in retry_basis:
                sequence, ordinal_text = retry_basis.rsplit(":", 1)
                try:
                    repeat_ordinal = int(ordinal_text)
                except ValueError:
                    sequence = retry_basis
                    repeat_ordinal = (
                        projection.repeat_ordinal if projection is not None else 0
                    )
            else:
                sequence = (
                    projection.generation
                    if projection is not None and projection.generation is not None
                    else cls._projection_key(projection)
                )
                repeat_ordinal = projection.repeat_ordinal if projection is not None else 0
            if sequence is None or projection is None:
                raise ValueError("bounded-repeat occurrence requires sequence")
            values.update(
                {
                    "repeat_sequence": sequence,
                    "repeat_ordinal": repeat_ordinal,
                    "occurrence_basis": f"{sequence}:{repeat_ordinal}",
                }
            )
        elif recurrence_class is RecurrenceClass.QUEUE_GENERATION:
            generation = (
                retry_basis
                if retry_basis is not None
                else projection.generation if projection is not None else None
            )
            if not generation:
                raise ValueError("queue occurrence requires generation")
            values.update(
                {
                    "queue_generation": generation,
                    "occurrence_basis": str(generation),
                }
            )
        elif recurrence_class is RecurrenceClass.MARCH_GENERATION:
            generation = (
                retry_basis
                if retry_basis is not None
                else projection.generation if projection is not None else None
            )
            if not generation:
                raise ValueError("march occurrence requires generation")
            values.update(
                {
                    "march_generation": generation,
                    "occurrence_basis": str(generation),
                }
            )
        else:
            basis = retry_basis or cls._projection_key(projection)
            if basis is None:
                raise ValueError("projection occurrence requires identity")
            values["occurrence_basis"] = basis
        key_values = dict(values)
        key_values.pop("occurrence_key", None)
        values["occurrence_key"] = BotStateManager.occurrence_key(
            descriptor.flow_id,
            facts.reset_id,
            occurrence_ordinal,
            **key_values,
        )
        return values

    @classmethod
    def _recurrence_allows(
        cls, descriptor: FlowDescriptor, facts: SchedulerFacts, now: float
    ) -> bool:
        expected = descriptor.recurrence_class
        projection = cls._recurrence_projection(descriptor, facts)
        if expected is None:
            return True
        if projection is not None and projection.recurrence_class is not expected:
            return False
        if expected in {
            RecurrenceClass.COOLDOWN,
            RecurrenceClass.TIMER,
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        }:
            if (
                projection is None
                or projection.observed_at_utc is None
                or projection.observed_at_utc > now
                or now - projection.observed_at_utc > facts.projection_freshness_seconds
            ):
                return False
        if expected in {
            RecurrenceClass.AP_REGENERATION,
            RecurrenceClass.STAMINA_REGENERATION,
        } and projection is not None and projection.observed_balance is None:
            return False
        if expected in {
            RecurrenceClass.QUEUE_GENERATION,
            RecurrenceClass.MARCH_GENERATION,
        } and (projection is None or not projection.generation):
            return False
        if expected is RecurrenceClass.BOUNDED_REPEAT and (
            projection is None
            or projection.repeat_limit is None
            or projection.repeat_ordinal >= projection.repeat_limit
        ):
            return False
        if expected is RecurrenceClass.EVENT_WINDOW and (
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

    @staticmethod
    def _descriptor_gate_reason(
        descriptor: FlowDescriptor, facts: SchedulerFacts
    ) -> str | None:
        failures = list(facts.gate_failures(descriptor))
        # ``SchedulerFacts.gate_failures`` intentionally tolerates absent
        # optional revisions for callers that do not have product metadata.
        # Canonical scheduling has a static product binding, so absence or a
        # type mismatch is not an admission.
        if descriptor.product_revision and (
            facts.product_revision != descriptor.product_revision
        ):
            if "PRODUCT_REVISION_MISMATCH" not in failures:
                failures.append("PRODUCT_REVISION_MISMATCH")
        if isinstance(descriptor.accepted_product, str) and (
            facts.accepted_product != descriptor.accepted_product
        ):
            if "ACCEPTED_PRODUCT_MISMATCH" not in failures:
                failures.append("ACCEPTED_PRODUCT_MISMATCH")
        return failures[0] if failures else None

    @staticmethod
    def _due_anchor(state: FlowState, now: float) -> float:
        values = [
            float(value)
            for value in (state.eligible_since_utc, state.next_due_at_utc)
            if value is not None
        ]
        return min(values) if values else now

    @staticmethod
    def _is_reset_scoped(descriptor: FlowDescriptor) -> bool:
        recurrence_class = descriptor.recurrence_class
        if recurrence_class is None:
            return bool(descriptor.reset_scoped)
        return recurrence_class in {
            RecurrenceClass.DAILY_ONCE_PER_RESET,
            RecurrenceClass.RESET_BOUNDED,
        }

    def _eligible(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None,
        flow_id: str | None = None,
        mode: str = "scheduled",
        allow_service_disabled: bool = False,
    ) -> list[tuple[FlowDescriptor, FlowState, float, bool]]:
        now = facts.now_utc_epoch
        if self._runtime_gate_reason(facts) is not None:
            return []
        if not self._clock_allows_selection(now):
            return []
        if not allow_service_disabled and not self.state.get_service().enabled:
            return []
        eligible: list[tuple[FlowDescriptor, FlowState, float, bool]] = []
        for descriptor in self.descriptors:
            if flow_id is not None and descriptor.flow_id != flow_id:
                continue
            if self._descriptor_gate_reason(descriptor, facts) is not None:
                continue
            if not descriptor.scheduler_eligible:
                continue
            state = self.state.get_flow(descriptor.flow_id)
            if state is None or not state.enabled or state.blocked:
                continue
            reset_scoped = self._is_reset_scoped(descriptor)
            if mode == "scheduled" and reset_scoped and (
                state.reset_id not in (None, facts.reset_id)
            ):
                # A reset rollover gets ordinal zero.  The normal path persists
                # this rollover immediately before claiming; shadow does not.
                ordinal = 0
            else:
                ordinal = state.next_occurrence_key
            if (
                mode == "scheduled"
                and reset_scoped
                and state.reset_id == facts.reset_id
                and state.next_occurrence_key > 0
            ):
                # Reset-scoped occurrences are admitted once per reset. The
                # ordinal remains the durable proof that one already advanced.
                continue
            if state.next_due_at_utc is not None and state.next_due_at_utc > now:
                continue
            if state.consecutive_failures >= state.max_attempts:
                continue
            if (
                state.retry_not_before_utc is not None
                and state.retry_not_before_utc > now
            ):
                continue
            if not self._recurrence_allows(descriptor, facts, now):
                continue
            projection_key = self._projection_key(
                self._recurrence_projection(descriptor, facts)
            )
            if (
                mode == "scheduled"
                and projection_key is not None
                and state.last_accepted_projection_key == projection_key
            ):
                continue
            handler = self.handlers[descriptor.flow_id]
            if not self._profile_allowed(handler, perception):
                continue
            try:
                if not handler.eligibility(facts, perception):
                    continue
            except Exception:
                continue
            anchor = self._due_anchor(state, now)
            wait = state.max_wait_seconds
            starved = bool(
                wait is not None and now - anchor >= float(wait)
            )
            eligible.append((descriptor, state, anchor, starved))
        return eligible
    @staticmethod
    def _profile_allowed(
        handler: FlowHandler, perception: PerceptionEnvelope | None
    ) -> bool:
        """Apply a handler's fixed profile binding before eligibility logic."""

        if perception is None:
            return True
        expected: str | None = None
        for source in (
            handler,
            getattr(handler, "snapshot", None),
            getattr(handler, "_snapshot", None),
        ):
            if source is None:
                continue
            value = getattr(source, "profile_id", None)
            if value is None:
                value = getattr(source, "profile", None)
            if isinstance(value, str) and value.strip():
                expected = value
                break
            supported = getattr(source, "supported_profiles", None)
            if supported is not None and perception.profile_id not in supported:
                return False
        return expected is None or perception.profile_id == expected

    def _select_candidate(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None,
        flow_id: str | None = None,
        mode: str = "scheduled",
        operator_request_id: str | None = None,
        allow_service_disabled: bool = False,
    ) -> PulseCandidate | None:
        options = self._eligible(
            facts,
            perception=perception,
            flow_id=flow_id,
            mode=mode,
            allow_service_disabled=allow_service_disabled,
        )
        if not options:
            return None
        options.sort(
            key=lambda item: (
                0 if item[3] else 1,
                item[1].priority,
                item[2],
                item[0].flow_id,
            )
        )
        descriptor, state, _anchor, _starved = options[0]
        ordinal = (
            0
            if mode == "scheduled"
            and self._is_reset_scoped(descriptor)
            and state.reset_id not in (None, facts.reset_id)
            else state.next_occurrence_key
        )
        try:
            binding = self._occurrence_binding(
                descriptor,
                facts,
                state,
                mode=mode,
                operator_request_id=operator_request_id,
                ordinal=ordinal,
            )
        except (TypeError, ValueError):
            return None
        return PulseCandidate(
            descriptor=descriptor,
            identity=self._identity(facts, descriptor),
            occurrence_key=str(binding["occurrence_key"]),
        )

    def _prepare_claim(
        self,
        facts: SchedulerFacts,
        descriptor: FlowDescriptor,
        *,
        mode: str = "scheduled",
        operator_request_id: str | None = None,
    ) -> None:
        """Persist only selected schedule facts immediately before claiming."""

        now = facts.now_utc_epoch
        state = self.state.get_flow(descriptor.flow_id)
        if state is None or not state.enabled or state.blocked:
            return
        reset_changed = (
            mode == "scheduled"
            and self._is_reset_scoped(descriptor)
            and state.reset_id != facts.reset_id
        )
        if reset_changed:
            state = self.state.update_reset(
                descriptor.flow_id, facts.reset_id, now_utc_epoch=now
            )
        if state is None or (
            state.next_due_at_utc is not None and state.next_due_at_utc > now
        ):
            return
        ordinal = 0 if reset_changed else state.next_occurrence_key
        binding = self._occurrence_binding(
            descriptor,
            facts,
            state,
            mode=mode,
            operator_request_id=operator_request_id,
            ordinal=ordinal,
        )
        if mode == "scheduled":
            updates: dict[str, object] = {
                "next_occurrence_kind": binding["occurrence_kind"],
                "next_occurrence_basis": binding["occurrence_basis"],
                "now_utc_epoch": now,
            }
            if state.eligible_since_utc is None or reset_changed:
                updates["eligible_since_utc"] = now
            if "timer_slot" in binding:
                updates["schedule_anchor_utc"] = binding["timer_slot"]
            self.state.update_schedule(descriptor.flow_id, **updates)

    @staticmethod
    def _run_state(result: NormalizedResult) -> RunState:
        if result.outcome is NormalizedOutcome.DEFERRED:
            return RunState.DEFERRED
        if result.outcome in {
            NormalizedOutcome.BLOCKED,
            NormalizedOutcome.MANUAL_REQUIRED,
        }:
            return RunState.BLOCKED
        if result.outcome in {
            NormalizedOutcome.UNRESOLVED,
            NormalizedOutcome.RECONCILIATION_REQUIRED,
        }:
            return RunState.FAILED
        return RunState.SUCCEEDED


    @staticmethod
    def _to_scheduler_result(
        identity: SchedulerIdentity, result: NormalizedResult
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
            return SchedulerAwareTaskResult.action_performed(
                identity, result.reason_code, **kwargs
            )
        if result.outcome is NormalizedOutcome.DEFERRED:
            return SchedulerAwareTaskResult.deferred(
                identity, result.reason_code, float(result.next_eligible_at), **kwargs
            )
        if result.outcome is NormalizedOutcome.COMPLETE_FOR_RESET:
            return SchedulerAwareTaskResult.complete_for_reset(
                identity, result.reason_code, **kwargs
            )
        if result.outcome is NormalizedOutcome.ALREADY_COMPLETE:
            return SchedulerAwareTaskResult.already_complete(
                identity, result.reason_code, **kwargs
            )
        if result.outcome is NormalizedOutcome.MANUAL_REQUIRED:
            kwargs["unresolved_action"] = False
            return SchedulerAwareTaskResult.manual_required(
                identity, result.reason_code, **kwargs
            )
        if result.outcome is NormalizedOutcome.BLOCKED:
            kwargs["unresolved_action"] = False
            return SchedulerAwareTaskResult.blocked(
                identity, result.reason_code, **kwargs
            )
        return SchedulerAwareTaskResult.reconciliation_required(
            identity, result.reason_code, **kwargs
        )
    @staticmethod
    def _unknown_result(
        identity: SchedulerIdentity, reason: str
    ) -> SchedulerAwareTaskResult:
        """Normalize terminal projection races as unresolved scheduler results."""

        return SchedulerAwareTaskResult(
            SchedulerTaskOutcome.UNKNOWN,
            reason,
            identity,
            verified=False,
            unresolved_action=True,
        )

    @staticmethod
    def _retry_deadline(
        state: FlowState | None, terminal_state: RunState, now: float
    ) -> float | None:
        """Bound failure retries while retaining the claimed occurrence key."""

        if terminal_state is not RunState.FAILED or state is None:
            return None
        # The first retry is one second later; each subsequent failure doubles
        # the delay, capped to keep a damaged route from monopolizing a pulse.
        return now + float(2 ** min(state.consecutive_failures, 10))

    def _project_terminal(
        self,
        run: RunRecord,
        terminal_state: RunState,
        *,
        reason: str,
        outcome: str,
        now: float,
        expected_state: RunState = RunState.RUNNING,
        expected_row_version: int | None = None,
        next_due_at_utc: float | None = None,
        retry_not_before_utc: float | None = None,
        accepted_projection_key: str | None = None,
    ) -> RunRecord:
        """Project one terminal result through the canonical state authority."""

        project = getattr(self.state, "project_terminal", None)
        if not callable(project):
            raise TerminalProjectionError("TERMINAL_PROJECTION_UNAVAILABLE")
        kwargs = {
            "owner_instance_id": run.owner_instance_id,
            "process_start_token": run.process_start_token,
            "run_token": run.run_token,
            "lease_generation": run.lease_generation,
            "expected_state": expected_state,
            "expected_row_version": expected_row_version,
            "outcome": outcome,
            "reason": reason,
            "next_due_at_utc": next_due_at_utc,
            "retry_not_before_utc": retry_not_before_utc,
            "now_utc_epoch": now,
        }
        if accepted_projection_key is not None:
            kwargs["accepted_projection_key"] = accepted_projection_key
        projected = project(run.run_id, terminal_state, **kwargs)
        if projected is None:
            raise TerminalProjectionError("TERMINAL_CAS_FAILED")
        return projected

    def select(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        flow_id: str | None = None,
    ) -> PulseCandidate | None:
        """Compute a candidate without changing any SQLite row.

        Public selection is subject to exactly the same external facts and
        persisted service/flow gates as a pulse.  In particular, selection
        cannot be used to bypass health, registration, product, reset, or
        clock fences.
        """

        if self._runtime_gate_reason(facts) is not None:
            return None
        if not self.state.get_service().enabled:
            return None
        return self._select_candidate(
            facts, perception=perception, flow_id=flow_id
        )

    def pulse(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        mode: str = "scheduled",
        flow_id: str | None = None,
        operator_request_id: str | None = None,
        shadow: bool = False,
    ) -> PulseReport:
        if mode not in {"scheduled", "manual"}:
            raise ValueError("mode must be scheduled or manual")
        if mode == "manual":
            if flow_id is None:
                raise ValueError("manual pulse requires flow_id")
            if operator_request_id is None:
                operator_request_id = (
                    f"service:{flow_id}:{facts.reset_id}:"
                    f"{facts.now_utc_epoch:.9f}"
                )
            elif not operator_request_id.strip():
                raise ValueError("manual pulse requires operator_request_id")
        now = facts.now_utc_epoch
        gate_reason = self._runtime_gate_reason(facts)
        if gate_reason is not None:
            return PulseReport(None, None, self._next_wake(now, facts), gate_reason)
        if shadow:
            # A shadow is a read-only forecast.  It intentionally ignores the
            # global enable bit while retaining every external and per-flow gate.
            candidate = self._select_candidate(
                facts,
                perception=perception,
                flow_id=flow_id,
                mode=mode,
                operator_request_id=operator_request_id,
                allow_service_disabled=True,
            )
            return PulseReport(
                candidate,
                None,
                self._next_wake(now, facts),
                "SHADOW_CANDIDATE"
                if candidate is not None
                else "SHADOW_NO_ELIGIBLE_TASK",
            )
        service = self.state.get_service()
        if not service.enabled:
            return PulseReport(None, None, self._next_wake(now, facts), "SERVICE_DISABLED")

        # Acquire before recovery and selection so all state reconciliation is
        # fenced by this pulse's exact service lease.  The lease is released
        # below for every claim, terminal, CAS, and exception path.
        try:
            lease = self.state.acquire_service_lease(
                owner_instance_id=self.state.owner_instance_id,
                process_start_token=self.state.process_start_token,
                process_id=self.state.process_id,
                now_utc_epoch=now,
            )
        except StateBusyError:
            return PulseReport(
                None,
                None,
                self._next_wake(now, facts),
                "SQLITE_BUSY",
            )
        if lease is None:
            return PulseReport(
                None,
                None,
                self._next_wake(now, facts),
                "SERVICE_LEASE_UNAVAILABLE",
            )
        lease_owner = lease.owner_instance_id or self.state.owner_instance_id
        lease_token = lease.process_start_token or self.state.process_start_token
        lease_generation = lease.lease_generation
        try:
            if not self._observe_clock(now):
                return PulseReport(
                    None,
                    None,
                    self._next_wake(now, facts),
                    "CLOCK_ROLLBACK",
                )

            # Reconcile stale reservations before selecting. A stale run with
            # no dispatch is safely terminalized and reclaimed. UNKNOWN
            # effects remain RECOVERING and require an explicit reconciliation.
            try:
                recovered = self.state.recover_orphans(now_utc_epoch=now)
                if any(
                    run.state is RunState.RECOVERING
                    or self.state.has_unresolved_actions(run.run_id)
                    for run in recovered
                ):
                    return PulseReport(
                        None,
                        None,
                        self._next_wake(now, facts),
                        "ORPHAN_RECONCILIATION_REQUIRED",
                    )
            except StateBusyError:
                return PulseReport(
                    None, None, self._next_wake(now, facts), "SQLITE_BUSY"
                )
            except Exception as exc:
                return PulseReport(
                    None,
                    None,
                    self._next_wake(now, facts),
                    "ORPHAN_RECOVERY_FAILED:" + type(exc).__name__,
                )

            candidate = self._select_candidate(
                facts,
                perception=perception,
                flow_id=flow_id,
                mode=mode,
                operator_request_id=operator_request_id,
            )
            if candidate is None:
                if mode == "manual" and flow_id is not None:
                    state = self.state.get_flow(flow_id)
                    descriptor = next(
                        (
                            item
                            for item in self.descriptors
                            if item.flow_id == flow_id
                        ),
                        None,
                    )
                    reason = (
                        "FLOW_UNKNOWN"
                        if state is None or descriptor is None
                        else "FLOW_DISABLED"
                        if not state.enabled
                        else "FLOW_BLOCKED"
                        if state.blocked
                        else self._descriptor_gate_reason(descriptor, facts)
                        or "NO_ELIGIBLE_TASK"
                    )
                    return PulseReport(
                        None, None, self._next_wake(now, facts), reason
                    )
                return PulseReport(
                    None, None, self._next_wake(now, facts), "NO_ELIGIBLE_TASK"
                )

            # Selection is read-only; persist only the selected reset rollover
            # and recurrence anchor immediately before asking SQLite to claim.
            try:
                self._prepare_claim(
                    facts,
                    candidate.descriptor,
                    mode=mode,
                    operator_request_id=operator_request_id,
                )
                prepared_state = self.state.get_flow(candidate.descriptor.flow_id)
                if prepared_state is None:
                    return PulseReport(
                        None, None, self._next_wake(now, facts), "CLAIM_UNAVAILABLE"
                    )
                binding = self._occurrence_binding(
                    candidate.descriptor,
                    facts,
                    prepared_state,
                    mode=mode,
                    operator_request_id=operator_request_id,
                    ordinal=(
                        0
                        if mode == "scheduled"
                        and self._is_reset_scoped(candidate.descriptor)
                        and prepared_state.reset_id != facts.reset_id
                        else prepared_state.next_occurrence_key
                    ),
                )
                claim_values = dict(binding)
                claim_values.pop("occurrence_key", None)
                claim = self.state.claim_occurrence(
                    candidate.descriptor.flow_id,
                    facts.reset_id,
                    now_utc_epoch=now,
                    mode=mode,
                    occurrence_key=candidate.occurrence_key,
                    owner_instance_id=lease_owner,
                    process_start_token=lease_token,
                    lease_generation=lease_generation,
                    max_inputs=1,
                    max_actions=1,
                    **claim_values,
                )
            except StateBusyError:
                return PulseReport(
                    candidate, None, self._next_wake(now, facts), "SQLITE_BUSY"
                )
            except (TypeError, ValueError):
                return PulseReport(
                    candidate, None, self._next_wake(now, facts), "CLAIM_UNAVAILABLE"
                )
            if claim is None:
                return PulseReport(
                    candidate, None, self._next_wake(now, facts), "CLAIM_UNAVAILABLE"
                )
            candidate = PulseCandidate(
                candidate.descriptor,
                candidate.identity,
                claim.occurrence_key,
                claim,
            )
            running = self.state.transition_run(
                claim.run_id,
                RunState.RUNNING,
                expected_state=RunState.CLAIMED,
                owner_instance_id=claim.owner_instance_id,
                process_start_token=claim.process_start_token,
                run_token=claim.run_token,
                lease_generation=claim.lease_generation,
                now_utc_epoch=now,
            )
            if running is None:
                unknown = self._unknown_result(candidate.identity, "RUN_CAS_FAILED")
                return PulseReport(
                    candidate, unknown, self._next_wake(now, facts), unknown.reason_code
                )
            validation = self.state.validate_dispatch(
                claim.run_id,
                owner_instance_id=running.owner_instance_id,
                process_start_token=running.process_start_token,
                run_token=running.run_token,
                lease_generation=running.lease_generation,
                now_utc_epoch=now,
            )
            if not validation.valid:
                try:
                    self._project_terminal(
                        running,
                        RunState.BLOCKED,
                        expected_state=RunState.RUNNING,
                        expected_row_version=running.row_version,
                        reason=validation.reason,
                        outcome="BLOCKED",
                        now=now,
                    )
                except TerminalProjectionError as exc:
                    unknown = self._unknown_result(
                        candidate.identity,
                        getattr(exc, "reason", None) or "TERMINAL_CAS_FAILED",
                    )
                    return PulseReport(
                        candidate,
                        unknown,
                        self._next_wake(now, facts),
                        unknown.reason_code,
                    )
                return PulseReport(
                    candidate, None, self._next_wake(now, facts), validation.reason
                )
            handler = self.handlers[candidate.descriptor.flow_id]
            try:
                if not handler.revalidate(facts, perception):
                    try:
                        self._project_terminal(
                            running,
                            RunState.FAILED,
                            expected_row_version=running.row_version,
                            reason="POST_SELECTION_REVALIDATION_FAILED",
                            outcome="RECONCILIATION_REQUIRED",
                            retry_not_before_utc=self._retry_deadline(
                                self.state.get_flow(running.flow_id),
                                RunState.FAILED,
                                now,
                            ),
                            now=now,
                        )
                    except TerminalProjectionError as exc:
                        unknown = self._unknown_result(
                            candidate.identity,
                            getattr(exc, "reason", None)
                            or "TERMINAL_CAS_FAILED",
                        )
                        return PulseReport(
                            candidate,
                            unknown,
                            self._next_wake(now, facts),
                            unknown.reason_code,
                        )
                    return PulseReport(
                        candidate,
                        None,
                        self._next_wake(now, facts),
                        "POST_SELECTION_REVALIDATION_FAILED",
                    )
                validation = self.state.validate_dispatch(
                    claim.run_id,
                    owner_instance_id=running.owner_instance_id,
                    process_start_token=running.process_start_token,
                    run_token=running.run_token,
                    lease_generation=running.lease_generation,
                    now_utc_epoch=now,
                )
                if not validation.valid:
                    try:
                        self._project_terminal(
                            running,
                            RunState.BLOCKED,
                            expected_row_version=running.row_version,
                            reason="DISPATCH_FENCE_FAILED:" + validation.reason,
                            outcome="BLOCKED",
                            now=now,
                        )
                    except TerminalProjectionError as exc:
                        unknown = self._unknown_result(
                            candidate.identity,
                            getattr(exc, "reason", None)
                            or "TERMINAL_CAS_FAILED",
                        )
                        return PulseReport(
                            candidate,
                            unknown,
                            self._next_wake(now, facts),
                            unknown.reason_code,
                        )
                    return PulseReport(
                        candidate,
                        None,
                        self._next_wake(now, facts),
                        "DISPATCH_FENCE_FAILED",
                    )
                plan = handler.plan(facts, perception)
                normalized = (
                    plan
                    if isinstance(plan, NormalizedResult)
                    else handler.reconcile(plan, perception)
                )
                if not isinstance(normalized, NormalizedResult):
                    raise TypeError("handler did not return a normalized result")
                scheduler_result = self._to_scheduler_result(
                    candidate.identity, normalized
                )
                terminal_state = self._run_state(normalized)
            except Exception as exc:
                scheduler_result = SchedulerAwareTaskResult.reconciliation_required(
                    candidate.identity,
                    "HANDLER_EXCEPTION_RECONCILIATION_REQUIRED:"
                    + type(exc).__name__,
                    verified=False,
                    unresolved_action=True,
                )
                terminal_state = RunState.FAILED
            try:
                self._project_terminal(
                    running,
                    terminal_state,
                    expected_row_version=running.row_version,
                    reason=scheduler_result.reason_code,
                    outcome=scheduler_result.outcome.value,
                    next_due_at_utc=(
                        scheduler_result.next_eligible_at
                        if terminal_state is RunState.DEFERRED
                        else None
                    ),
                    retry_not_before_utc=self._retry_deadline(
                        self.state.get_flow(running.flow_id), terminal_state, now
                    ),
                    accepted_projection_key=(
                        self._projection_key(
                            self._recurrence_projection(candidate.descriptor, facts)
                        )
                        if terminal_state is RunState.SUCCEEDED
                        else None
                    ),
                    now=now,
                )
            except TerminalProjectionError as exc:
                scheduler_result = self._unknown_result(
                    candidate.identity,
                    getattr(exc, "reason", None) or "TERMINAL_CAS_FAILED",
                )
            return PulseReport(
                candidate,
                scheduler_result,
                self._next_wake(now, facts),
                scheduler_result.reason_code,
            )
        except StateBusyError:
            return PulseReport(
                None, None, self._next_wake(now, facts), "SQLITE_BUSY"
            )
        finally:
            # Release only the generation acquired by this pulse.  A takeover
            # can advance the generation; the exact-match state API then
            try:
                self.state.release_service_lease(
                    owner_instance_id=lease_owner,
                    process_start_token=lease_token,
                    lease_generation=lease_generation,
                )
            except StateBusyError:
                # The pulse is already fenced; a later owner can release an
                # expired lease. Never mask the pulse result with contention.
                pass
class UtcPulseCoordinator:
    """Select, atomically claim, and execute at most one handler per UTC pulse.

    Selection never binds targets, creates a session, acquires runtime ownership,
    or grants transport authority.
    """

    def __init__(
        self,
        repository: SQLiteSchedulerInvocationRepository | BotStateManager | None = None,
        descriptors: Sequence[FlowDescriptor] = (),
        handlers: Mapping[str, FlowHandler] = (),
        *,
        state_manager: BotStateManager | None = None,
        activation_authority: ActivationAuthority | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if repository is not None and state_manager is not None and repository is not state_manager:
            raise ValueError("repository and state_manager must refer to one authority")
        repository = state_manager or repository
        if repository is None:
            raise ValueError("state_manager or repository is required")
        self.repository = repository
        self.descriptors = tuple(
            sorted(descriptors, key=lambda item: (item.priority, item.flow_id))
        )
        self.handlers = dict(handlers)
        self.clock = clock
        self._canonical = (
            _CanonicalPulseCoordinator(
                repository, self.descriptors, self.handlers, clock=clock
            )
            if isinstance(repository, BotStateManager)
            else None
        )
        # The registry authority is retained solely for the legacy repository
        # path.  Canonical state-manager scheduling never consults it.
        self.activation_authority = (
            None
            if self._canonical is not None
            else activation_authority or DisabledProductionAuthority()
        )
        descriptor_ids = [item.flow_id for item in self.descriptors]
        if len(descriptor_ids) != len(set(descriptor_ids)):
            raise ValueError("scheduler descriptors must have unique flow IDs")
        missing = [
            item.flow_id for item in self.descriptors if item.flow_id not in self.handlers
        ]
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
        mode: str = "scheduled",
        flow_id: str | None = None,
        shadow: bool = False,
    ) -> PulseReport:
        if self._canonical is not None:
            return self._canonical.pulse(
                facts,
                perception=perception,
                mode=mode,
                flow_id=flow_id,
                shadow=shadow,
            )
        if mode != "scheduled" or flow_id is not None or shadow:
            raise ValueError("manual and shadow modes require BotStateManager")
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

    def select(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        flow_id: str | None = None,
    ) -> PulseCandidate | None:
        if self._canonical is None:
            raise ValueError("mutation-free selection requires BotStateManager")
        return self._canonical.select(
            facts, perception=perception, flow_id=flow_id
        )

    def shadow(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        flow_id: str | None = None,
        operator_request_id: str | None = None,
    ) -> PulseReport:
        if self._canonical is None:
            raise ValueError("shadow scheduling requires BotStateManager")
        return self._canonical.pulse(
            facts,
            perception=perception,
            flow_id=flow_id,
            operator_request_id=operator_request_id,
            shadow=True,
        )

    def run_manual(
        self,
        flow_id: str,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        operator_request_id: str | None = None,
    ) -> PulseReport:
        if self._canonical is None:
            raise ValueError("manual runs require BotStateManager")
        return self._canonical.pulse(
            facts,
            perception=perception,
            mode="manual",
            flow_id=flow_id,
            operator_request_id=operator_request_id,
        )

    def run(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        flow_id: str | None = None,
        operator_request_id: str | None = None,
        live: bool = False,
        shadow: bool = False,
    ) -> PulseReport:
        if self._canonical is not None and (flow_id is not None or live or shadow):
            if shadow:
                return self.shadow(
                    facts,
                    perception=perception,
                    flow_id=flow_id,
                    operator_request_id=operator_request_id,
                )
            if flow_id is None:
                raise ValueError("live manual run requires flow_id")
            return self.run_manual(
                flow_id,
                facts,
                perception=perception,
                operator_request_id=operator_request_id,
            )
        return self.pulse(
            facts,
            perception=perception,
            operator_request_id=operator_request_id,
        )


PulseCoordinator = UtcPulseCoordinator
CanonicalPulseCoordinator = _CanonicalPulseCoordinator
