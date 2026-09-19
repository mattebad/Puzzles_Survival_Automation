"""Thin composition facade for local status, observation, and one-pulse execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Any

from contextlib import contextmanager


@contextmanager
def _state_boundary():
    """Expose bounded SQLite contention without leaking driver exceptions."""

    try:
        yield
    except (StateBusyError, sqlite3.OperationalError) as exc:
        if isinstance(exc, StateBusyError):
            reason = exc.reason
            retryable = exc.retryable
        elif any(
            marker in str(exc).casefold() for marker in ("busy", "locked")
        ):
            reason = "SQLITE_BUSY"
            retryable = True
        else:
            raise
        raise ServiceError(
            str(exc),
            reason=reason,
            retryable=retryable,
        ) from exc


from .adapters import (
    AdapterKind,
    DeviceAdapter,
    FakeDeviceAdapter,
    SupervisedBlueStacksAdapter,
)
from .contracts import FlowSpec, PerceptionEnvelope, SchedulerFacts, ServiceMode
from .handlers import (
    CampaignApSelectionHandler,
    DisabledHandler,
    RecruitmentMaintenanceSelectionHandler,
    NovaPraiseSelectionHandler,
    WorldNavigationSelectionHandler,
)
from .operations import HealthSnapshot, OperationsService
from .registry import (
    CAMPAIGN_FLOW_ID,
    CANONICAL_FLOW_REGISTRY,
    CanonicalFlowRegistration,
    DisabledProductionEntry,
    NOVA_FLOW_ID,
    RECRUITMENT_FLOW_ID,
    RegisteredDispatchSnapshot,
    WORLD_FLOW_ID,
    canonical_descriptors,
    canonical_flow_specs,
)
from .state import BotStateManager, StateBusyError, resolve_state_path
from .scheduler import DisabledProductionAuthority, PulseReport, UtcPulseCoordinator
_CANONICAL_TABLE_COLUMNS = {
    "service_control": {
        "singleton_id",
        "enabled",
        "generation",
        "emergency_reason",
        "emergency_at_utc",
        "updated_at_utc",
        "row_version",
    },
    "flow_state": {
        "flow_id",
        "enabled",
        "generation",
        "blocked",
        "priority",
        "cadence",
        "max_attempts",
        "next_occurrence_key",
        "row_version",
    },
    "runs": {
        "run_id",
        "flow_id",
        "occurrence_key",
        "reset_id",
        "claimed_flow_generation",
        "service_generation",
        "owner_instance_id",
        "mode",
        "state",
        "max_inputs",
        "max_actions",
        "row_version",
    },
    "actions": {
        "action_id",
        "run_id",
        "sequence_no",
        "idempotency_key",
        "semantic_action_key",
        "state",
        "row_version",
    },
}


def _canonical_database_probe(path: str) -> bool:
    """Check the canonical BotStateManager schema without creating/migrating it."""

    if path in {":memory:", ""}:
        return True
    resolved_path = resolve_state_path(path)
    if resolved_path in {":memory:", ""}:
        return True
    try:
        connection = sqlite3.connect(
            f"file:{Path(resolved_path).resolve()}?mode=ro",
            uri=True,
        )
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                return False
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if set(_CANONICAL_TABLE_COLUMNS) - tables:
                return False
            return all(
                expected <= {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                for table, expected in _CANONICAL_TABLE_COLUMNS.items()
            )
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False




class ServiceError(RuntimeError):
    """Expected service-boundary failure with machine-readable metadata."""

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.reason = reason
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class ServiceStatus:
    mode: ServiceMode
    adapter_kind: str
    registered_flows: tuple[str, ...]
    disabled_flows: tuple[str, ...]
    scheduler_eligible: bool
    service_enabled: bool = False
    flow_enabled: dict[str, bool] | None = None
def registry_descriptor(
    entry: DisabledProductionEntry | CanonicalFlowRegistration,
):
    """Compose a descriptor from either static canonical or legacy facts.

    ``path=`` compatibility callers retain the legacy parser, but the normal
    service path supplies :class:`CanonicalFlowRegistration` directly.
    """

    if isinstance(entry, CanonicalFlowRegistration):
        return entry.descriptor
    from .contracts import FlowDescriptor, RecurrenceClass, RecurrenceProjection

    registered = entry.registered
    if entry.flow_id == WORLD_FLOW_ID:
        family = "world_map_navigation"
        variant = "navigation_only"
    elif entry.flow_id == NOVA_FLOW_ID:
        family = "nova_praise"
        variant = "supervised_one_free_pulse"
    elif entry.flow_id == RECRUITMENT_FLOW_ID:
        family = "recruitment"
        variant = "free_attempt_maintenance"
    elif entry.flow_id == CAMPAIGN_FLOW_ID:
        family = "campaign_ap"
        variant = "one_auto_battle"
    else:
        family = "disabled"
        variant = "disabled"
    if entry.flow_id == RECRUITMENT_FLOW_ID and registered:
        cadence = "cooldown_pulse"
    elif entry.flow_id == CAMPAIGN_FLOW_ID and registered:
        cadence = "ap_regeneration_pulse"
    else:
        cadence = "daily_once_per_reset"
    recurrence = (
        RecurrenceProjection(
            RecurrenceClass.AP_REGENERATION,
            observed_at_utc=0.0,
            observed_balance=0.0,
        )
        if entry.flow_id == CAMPAIGN_FLOW_ID and registered
        else None
    )
    return FlowDescriptor(
        flow_id=entry.flow_id,
        owner="automation_service",
        family=family if registered else "disabled",
        variant=variant if registered else "disabled",
        cadence=cadence,
        reset_scoped=entry.flow_id not in {RECRUITMENT_FLOW_ID, CAMPAIGN_FLOW_ID},
        priority=1 if registered else 100,
        scheduler_eligible=registered and entry.scheduler_eligible,
        accepted_product=entry.product_id if registered else False,
        product_revision=entry.product_revision if registered else None,
        registration_status=entry.registration_status,
        recurrence=recurrence,
    )


def registry_flow_spec(
    entry: DisabledProductionEntry | CanonicalFlowRegistration,
) -> FlowSpec:
    """Return static facts for first-time SQLite initialization."""

    if isinstance(entry, CanonicalFlowRegistration):
        return entry.spec
    descriptor = registry_descriptor(entry)
    return FlowSpec(
        flow_id=descriptor.flow_id,
        default_enabled=False,
        priority=descriptor.priority,
        cadence=descriptor.cadence,
    )


def legacy_registry_scheduler_components(
    repository,
    *,
    path=None,
    clock=time.time,
):
    """Compose legacy registry components for unmigrated repositories only.

    The legacy JSON registration file is an input to this API by design.  It
    must never be used with :class:`BotStateManager`, whose coordinator is
    composed from the immutable canonical registry below.
    """

    if isinstance(repository, BotStateManager):
        raise ValueError(
            "legacy registry composition cannot use BotStateManager; "
            "use registry_scheduler_components without path"
        )
    from .registry import load_disabled_registry

    entries = load_disabled_registry(path)
    descriptors = tuple(registry_descriptor(entry) for entry in entries)
    handlers: dict[str, Any] = {}
    for entry, descriptor in zip(entries, descriptors):
        if entry.registered and entry.flow_id == WORLD_FLOW_ID:
            handlers[entry.flow_id] = WorldNavigationSelectionHandler(
                RegisteredDispatchSnapshot.from_entry(entry)
            )
        elif entry.registered and entry.flow_id == NOVA_FLOW_ID:
            handlers[entry.flow_id] = NovaPraiseSelectionHandler(
                RegisteredDispatchSnapshot.from_entry(entry)
            )
        elif entry.registered and entry.flow_id == RECRUITMENT_FLOW_ID:
            handlers[entry.flow_id] = RecruitmentMaintenanceSelectionHandler(
                RegisteredDispatchSnapshot.from_entry(entry)
            )
        elif entry.registered and entry.flow_id == CAMPAIGN_FLOW_ID:
            handlers[entry.flow_id] = CampaignApSelectionHandler(
                RegisteredDispatchSnapshot.from_entry(entry)
            )
        else:
            handlers[entry.flow_id] = DisabledHandler(descriptor)
    activation_authority = DisabledProductionAuthority()
    activation_authority._entries = {entry.flow_id: entry for entry in entries}
    coordinator = UtcPulseCoordinator(
        repository,
        descriptors,
        handlers,
        activation_authority=activation_authority,
        clock=clock,
    )
    return entries, descriptors, handlers, coordinator


def _canonical_registry_scheduler_components(
    repository: BotStateManager,
    *,
    clock,
    initialize: bool = True,
):
    """Compose scheduler solely from static canonical facts and SQLite state."""

    registrations = CANONICAL_FLOW_REGISTRY
    if initialize and not getattr(repository, "read_only", False):
        repository.initialize_flows(entry.spec for entry in registrations)
    descriptors = canonical_descriptors()
    handlers = {
        entry.flow_id: entry.build_handler() for entry in registrations
    }
    return (
        registrations,
        descriptors,
        handlers,
        UtcPulseCoordinator(repository, descriptors, handlers, clock=clock),
    )


def registry_scheduler_components(
    repository=None,
    *,
    state_manager: BotStateManager | None = None,
    path=None,
    clock=time.time,
    initialize: bool = True,
):
    """Build canonical components from ``BotStateManager``.

    ``path`` names the retired JSON registration authority and is rejected for
    canonical state managers.  Unmigrated repository callers can opt into the
    separate :func:`legacy_registry_scheduler_components` API.  Canonical
    initialization is explicit for callers that perform real/control work;
    read-only managers always skip it.
    """

    if repository is not None and state_manager is not None and repository is not state_manager:
        raise ValueError("repository and state_manager must refer to one authority")
    repository = state_manager or repository
    if repository is None:
        raise ValueError("state_manager is required")
    if isinstance(repository, BotStateManager):
        if path is not None:
            raise ValueError(
                "canonical scheduler rejects legacy registry path; "
                "use legacy_registry_scheduler_components for unmigrated callers"
            )
        return _canonical_registry_scheduler_components(
            repository, clock=clock, initialize=initialize
        )
    if path is None:
        raise ValueError(
            "canonical scheduler requires BotStateManager; "
            "use legacy_registry_scheduler_components for unmigrated callers"
        )
    return legacy_registry_scheduler_components(repository, path=path, clock=clock)




# Public descriptive aliases used by offline callers and focused contract checks.
build_registry_scheduler = registry_scheduler_components
build_scheduler_components = registry_scheduler_components




class AutomationService:
    """Composition root backed by the canonical SQLite runtime authority.

    Construction composes static scheduler facts only.  Flow initialization
    occurs at explicit status/control or real-execution boundaries, never while
    preparing an observation.
    """

    def __init__(
        self,
        *,
        mode: ServiceMode | str = ServiceMode.DISABLED,
        adapter: DeviceAdapter | None = None,
        coordinator: UtcPulseCoordinator | None = None,
        operations: OperationsService | None = None,
        state_manager: BotStateManager | None = None,
        state: BotStateManager | None = None,
        recruitment_runner=None,
    ) -> None:
        if state_manager is not None and state is not None and state_manager is not state:
            raise ServiceError("state and state_manager must refer to one authority")
        self.state = state_manager or state
        if str(mode).casefold() == "automatic":
            raise ServiceError("automatic mode is unsupported")
        try:
            resolved_mode = mode if isinstance(mode, ServiceMode) else ServiceMode(mode)
        except ValueError as exc:
            raise ServiceError(f"unsupported service mode: {mode}") from exc
        self.mode = resolved_mode
        self.adapter = adapter or FakeDeviceAdapter()
        self.recruitment_runner = recruitment_runner
        self.coordinator = coordinator
        if self.coordinator is None and self.state is not None:
            with _state_boundary():
                _entries, _descriptors, _handlers, self.coordinator = (
                    registry_scheduler_components(self.state, initialize=False)
                )
        if self.state is None and self.coordinator is not None:
            candidate_state = getattr(self.coordinator, "repository", None)
            if isinstance(candidate_state, BotStateManager):
                self.state = candidate_state
        if self.mode is ServiceMode.SUPERVISED and self.recruitment_runner is None and not isinstance(
            self.adapter, SupervisedBlueStacksAdapter
        ):
            raise ServiceError(
                "supervised mode requires the executor-bound BlueStacks adapter"
            )
        if self.mode is ServiceMode.SUPERVISED and (
            self.coordinator is None
            or (
                getattr(self.coordinator, "_canonical", None) is None
                and type(getattr(self.coordinator, "activation_authority", None))
                is not DisabledProductionAuthority
            )
        ):
            raise ServiceError(
                "supervised mode requires a canonical state-backed coordinator"
            )
        if self.mode is ServiceMode.DRY_RUN and self.adapter.kind not in {
            AdapterKind.FAKE,
            AdapterKind.REPLAY,
        }:
            raise ServiceError("dry_run requires fake or replay adapter")
        self.operations = operations or OperationsService(
            adapter_status=self.adapter.status,
            database_probe=lambda: (
                self.state is not None
                and (
                    self.state.db_path in {":memory:", ""}
                    or _canonical_database_probe(self.state.db_path)
                )
            ),
            lease_held=lambda: False,
        )

    def _initialize_canonical_state(self) -> None:
        """Seed static flow rows only for a mutating control/run path."""

        if self.state is None:
            raise ServiceError("state manager is not configured")
        if getattr(self.state, "read_only", False):
            raise ServiceError("read-only state manager cannot initialize flows")
        with _state_boundary():
            self.state.initialize_flows(canonical_flow_specs())

    def status(self) -> ServiceStatus:
        # Route identity is static code authority; enablement and blocks are
        # read from the persisted state manager below.
        registrations = CANONICAL_FLOW_REGISTRY
        registered = tuple(item.flow_id for item in registrations if item.registered)
        flow_ids = tuple(item.flow_id for item in registrations)
        if self.state is None:
            return ServiceStatus(
                mode=self.mode,
                adapter_kind=self.adapter.kind.value,
                registered_flows=registered,
                disabled_flows=flow_ids,
                scheduler_eligible=False,
                flow_enabled={flow_id: False for flow_id in flow_ids},
            )
        with _state_boundary():
            if not getattr(self.state, "read_only", False):
                self.state.initialize_flows(canonical_flow_specs())
            service = self.state.get_service()
            states = {
                flow_id: self.state.get_flow(flow_id) for flow_id in flow_ids
            }
            return ServiceStatus(
                mode=self.mode,
                adapter_kind=self.adapter.kind.value,
                registered_flows=registered,
                disabled_flows=tuple(
                    flow_id
                    for flow_id, flow_state in states.items()
                    if flow_state is None or not flow_state.enabled
                ),
                scheduler_eligible=service.enabled and any(
                    item.scheduler_eligible
                    and states[item.flow_id] is not None
                    and states[item.flow_id].enabled
                    and not states[item.flow_id].blocked
                    for item in registrations
                ),
                service_enabled=service.enabled,
                flow_enabled={
                    flow_id: bool(flow_state is not None and flow_state.enabled)
                    for flow_id, flow_state in states.items()
                },
            )
    def flow_descriptor(self, flow_id: str):
        """Return a static descriptor without consulting a legacy registry."""

        return next(
            (
                entry.descriptor
                for entry in CANONICAL_FLOW_REGISTRY
                if entry.flow_id == flow_id
            ),
            None,
        )


    def set_flow_enabled(
        self,
        flow_id: str,
        enabled: bool,
        *,
        now_utc_epoch: float | None = None,
    ):
        if self.state is None:
            raise ServiceError("state manager is not configured")
        self._initialize_canonical_state()
        with _state_boundary():
            result = self.state.set_flow_enabled(
                flow_id, enabled, now_utc_epoch=now_utc_epoch
            )
        if result is None:
            raise ServiceError(f"unknown flow: {flow_id}")
        return result

    def enable_flow(self, flow_id: str, *, now_utc_epoch: float | None = None):
        if self.state is None:
            raise ServiceError("state manager is not configured")
        self._initialize_canonical_state()
        with _state_boundary():
            result = self.state.set_flow_enabled(
                flow_id, True, now_utc_epoch=now_utc_epoch
            )
        if result is None:
            raise ServiceError(f"unknown flow: {flow_id}")
        return result

    def disable_flow(self, flow_id: str, *, now_utc_epoch: float | None = None):
        if self.state is None:
            raise ServiceError("state manager is not configured")
        self._initialize_canonical_state()
        with _state_boundary():
            result = self.state.set_flow_enabled(
                flow_id, False, now_utc_epoch=now_utc_epoch
            )
        if result is None:
            raise ServiceError(f"unknown flow: {flow_id}")
        return result

    def set_service_enabled(
        self,
        enabled: bool,
        *,
        emergency_reason: str | None = None,
        now_utc_epoch: float | None = None,
    ):
        if self.state is None:
            raise ServiceError("state manager is not configured")
        self._initialize_canonical_state()
        with _state_boundary():
            return self.state.set_service_enabled(
                enabled,
                emergency_reason=emergency_reason,
                now_utc_epoch=now_utc_epoch,
            )

    def emergency_stop(
        self, reason: str = "emergency stop", *, now_utc_epoch: float | None = None
    ):
        return self.set_service_enabled(
            False, emergency_reason=reason, now_utc_epoch=now_utc_epoch
        )

    def observe(self):
        """Capture only; observation never reserves, claims, or enables."""
        return self.adapter.capture()

    def pulse(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
        shadow: bool = False,
    ) -> PulseReport:
        if self.coordinator is None:
            raise ServiceError("pulse coordinator is not configured")
        if self.mode in {ServiceMode.DISABLED, ServiceMode.OBSERVE_ONLY} and not shadow:
            raise ServiceError(f"{self.mode.value} service cannot execute a pulse")
        if self.mode is ServiceMode.DRY_RUN and self.adapter.kind not in {
            AdapterKind.FAKE,
            AdapterKind.REPLAY,
        }:
            raise ServiceError("dry_run requires fake or replay adapter")
        if self.mode is ServiceMode.SUPERVISED and not isinstance(
            self.adapter, SupervisedBlueStacksAdapter
        ):
            raise ServiceError(
                "supervised mode requires the executor-bound BlueStacks adapter"
            )
        if not shadow:
            self._initialize_canonical_state()
        try:
            return self.coordinator.pulse(
                facts, perception=perception, shadow=shadow
            )
        except (StateBusyError, sqlite3.OperationalError) as exc:
            if isinstance(exc, StateBusyError) or any(
                marker in str(exc).casefold() for marker in ("busy", "locked")
            ):
                return PulseReport(None, None, facts.now_utc_epoch, "SQLITE_BUSY")
            raise

    def serve(self, *, account_id: str, server_id: str, stop, emit, clock=time.time) -> None:
        """Drive one native recruitment handler through the existing pulse lifecycle."""
        from tasks.scheduler_task_result import SchedulerIdentity
        from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID
        from scripts.navigation_development_boundary import RuntimeInputLock
        from .contracts import NormalizedOutcome, NormalizedResult, RecurrenceClass, RecurrenceProjection
        from .recruitment import RecruitmentExecutionHandler, recruitment_next_due, recruitment_reset
        from .registry import RECRUITMENT_FLOW_ID

        if self.mode is not ServiceMode.SUPERVISED or self.recruitment_runner is None or self.state is None:
            raise ServiceError("serve requires an explicitly configured recruitment runner")
        if not account_id.strip() or not server_id.strip():
            raise ServiceError("serve requires account and server identity")
        state = self.state
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == RECRUITMENT_FLOW_ID)
        interrupted = "RECRUITMENT_INTERRUPTED_REQUIRES_INSPECTION"
        with RuntimeInputLock(owner="automation-service", invocation_id=state.owner_instance_id) as owner:
            def execute(run, facts):
                identity = SchedulerIdentity(account_id, server_id, facts.reset_id, MAINTENANCE_TASK_ID)

                def checkpoint():
                    owner.assert_held(owner.owner, owner.invocation_id)
                    if stop.is_set():
                        raise ServiceError("STOP_REQUESTED")
                    current = state.get_flow(RECRUITMENT_FLOW_ID)
                    control = state.get_service()
                    if (not control.enabled or control.generation != run.service_generation
                            or current is None or not current.enabled
                            or current.generation != run.claimed_flow_generation
                            or (current.blocked and current.blocked_reason != interrupted)):
                        raise ServiceError("SERVICE_OR_FLOW_DISABLED")
                    now = clock()
                    if not state.observe_clock(now).accepted:
                        raise ServiceError("CLOCK_ROLLBACK")
                    if recruitment_reset(now) != identity.reset_id:
                        raise ServiceError("RESET_CHANGED_DURING_RECRUITMENT")
                    if state.renew_service_lease(
                        owner_instance_id=run.owner_instance_id,
                        process_start_token=run.process_start_token,
                        lease_generation=run.lease_generation, now_utc_epoch=now,
                    ) is None:
                        raise ServiceError("SERVICE_LEASE_LOST")

                # Native ordinary inputs use the existing session lock, not action
                # leases. Keep a local crash marker until terminal projection succeeds.
                state.block_flow(RECRUITMENT_FLOW_ID, interrupted)
                result = {}
                try:
                    checkpoint()
                    result = self.recruitment_runner(identity, previous_reset, checkpoint)
                    due = recruitment_next_due(result, identity, facts.now_utc_epoch)
                    checkpoint()
                    return NormalizedResult(
                        NormalizedOutcome.DEFERRED, "RECRUITMENT_PASS_VERIFIED",
                        verified=True, next_eligible_at=due,
                        action_count=result["actions_completed"], observed_progress=result,
                    )
                except Exception as exc:
                    state.block_flow(RECRUITMENT_FLOW_ID, f"RECRUITMENT_REQUIRES_INSPECTION:{exc}")
                    return NormalizedResult(
                        NormalizedOutcome.BLOCKED, f"RECRUITMENT_REQUIRES_INSPECTION:{exc}",
                        verified=False, observed_progress=result if isinstance(result, dict) else {},
                    )

            handler = RecruitmentExecutionHandler(entry.registration, execute)
            coordinator = UtcPulseCoordinator(state, (entry.descriptor,), {entry.flow_id: handler}, clock=clock)
            while not stop.is_set():
                if not state.get_service_enabled():
                    emit({"status": "stopped", "reason": "SERVICE_DISABLED"})
                    return
                now = clock()
                flow = state.get_flow(RECRUITMENT_FLOW_ID)
                previous_reset = flow.reset_id if flow else None
                if flow is None or not flow.enabled or flow.blocked:
                    emit({"status": "paused", "reason": flow.blocked_reason if flow and flow.blocked else "FLOW_DISABLED"})
                    stop.wait(30)
                    continue
                facts = SchedulerFacts(
                    account_id, server_id, recruitment_reset(now), now,
                    health_ok=True, accepted_product=entry.product_id,
                    product_revision=entry.product_revision, registration_status=entry.registration_status,
                    scheduler_eligible=entry.scheduler_eligible, owner_available=owner.held,
                    clock_ok=True, reset_agreement=True,
                    projections={entry.flow_id: RecurrenceProjection(
                        RecurrenceClass.COOLDOWN, observed_at_utc=now,
                        next_eligible_at=flow.next_due_at_utc,
                    )},
                )
                report = coordinator.pulse(facts)
                if report.result is not None:
                    result = report.result
                    completed = result.verified and result.reason_code == "RECRUITMENT_PASS_VERIFIED"
                    if completed:
                        state.unblock_flow(RECRUITMENT_FLOW_ID)
                    emit({"status": "completed" if completed else "blocked",
                          "flow_id": entry.flow_id, "reason": report.reason_code,
                          "next_due_at_utc": result.next_eligible_at,
                          "result": dict(result.observed_progress)})
                due = state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc
                if stop.is_set() or not state.get_service_enabled():
                    continue
                delay = due - clock() if due is not None else 30
                stop.wait(min(30, delay) if delay > 0 else 30)

    def run(
        self,
        flow_id: str,
        facts: SchedulerFacts,
        *,
        live: bool = False,
        perception: PerceptionEnvelope | None = None,
        operator_request_id: str | None = None,
    ) -> PulseReport:
        if self.coordinator is None:
            raise ServiceError("pulse coordinator is not configured")
        if live and self.mode in {
            ServiceMode.DISABLED,
            ServiceMode.OBSERVE_ONLY,
        }:
            raise ServiceError(f"{self.mode.value} service cannot execute a live run")
        if not live:
            try:
                return self.coordinator.shadow(
                    facts, perception=perception, flow_id=flow_id
                )
            except (StateBusyError, sqlite3.OperationalError) as exc:
                if isinstance(exc, StateBusyError) or any(
                    marker in str(exc).casefold() for marker in ("busy", "locked")
                ):
                    return PulseReport(None, None, facts.now_utc_epoch, "SQLITE_BUSY")
                raise
        if self.state is None:
            raise ServiceError("live runs require canonical state manager")
        self._initialize_canonical_state()
        request_id = (
            operator_request_id.strip()
            if isinstance(operator_request_id, str) and operator_request_id.strip()
            else f"manual:{flow_id}:{facts.account_id}:{facts.server_id}:{facts.reset_id}"
        )
        with _state_boundary():
            if not self.state.get_service_enabled():
                raise ServiceError("SERVICE_DISABLED")
            if not self.state.get_flow_enabled(flow_id):
                raise ServiceError("FLOW_DISABLED")
            return self.coordinator.run_manual(
                flow_id,
                facts,
                perception=perception,
                operator_request_id=request_id,
            )

    def health(self, **kwargs: Any) -> HealthSnapshot:
        if "mode" in kwargs:
            raise ServiceError("health mode is owned by the service")
        return self.operations.health(mode=self.mode, **kwargs)
