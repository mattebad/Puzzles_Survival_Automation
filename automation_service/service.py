"""Thin composition facade for local status, observation, and one-pulse execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    BIOENHANCER_FLOW_ID,
    CAMPAIGN_FLOW_ID,
    CANONICAL_FLOW_REGISTRY,
    CanonicalFlowRegistration,
    DisabledProductionEntry,
    ENHANCEMENT_FLOW_ID,
    NOVA_FLOW_ID,
    PERSONAL_MIGHT_FLOW_ID,
    RECRUITMENT_FLOW_ID,
    RegisteredDispatchSnapshot,
    SUPPLY_FLOW_ID,
    ULTIMATE_FLOW_ID,
    WORLD_FLOW_ID,
    canonical_descriptors,
    canonical_flow_specs,
    servable_flow_names,
)
from .state import BotStateManager, RunState, StateBusyError, resolve_state_path
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
        variant = "drain_available_ap"
    else:
        family = "disabled"
        variant = "disabled"
    if entry.flow_id == RECRUITMENT_FLOW_ID and registered:
        cadence = "cooldown_pulse"
    elif entry.flow_id == CAMPAIGN_FLOW_ID and registered:
        cadence = "after_ap_drain"
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
        nova_runner=None,
        campaign_runner=None,
        bioenhancer_runner=None,
        supply_runner=None,
        ultimate_runner=None,
        enhancement_runner=None,
        personal_might_runner=None,
        application_startup=None,
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
        self.nova_runner = nova_runner
        self.campaign_runner = campaign_runner
        self.bioenhancer_runner = bioenhancer_runner
        self.supply_runner = supply_runner
        self.ultimate_runner = ultimate_runner
        self.enhancement_runner = enhancement_runner
        self.personal_might_runner = personal_might_runner
        if application_startup is not None and not callable(application_startup):
            raise ServiceError("application startup must be callable")
        self.application_startup = application_startup
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
        if self.mode is ServiceMode.SUPERVISED and all(runner is None for runner in (
            self.recruitment_runner, self.nova_runner, self.campaign_runner, self.bioenhancer_runner,
            self.supply_runner,
            self.ultimate_runner,
            self.enhancement_runner,
            self.personal_might_runner,
        )) and not isinstance(
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

    def serve(self, *, account_id: str, server_id: str, stop, emit,
              clock=time.time, flow_ids=None, operator_request_id: str | None = None) -> None:
        """Drive explicitly selected native routes serially under one owner."""
        from tasks.scheduler_task_result import SchedulerIdentity
        from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID
        from tasks.nova_praise_pulse import NOVA_TASK_ID
        from scripts.navigation_development_boundary import RuntimeInputLock, require_canonical_unresolved_clear
        from .contracts import NormalizedOutcome, NormalizedResult, RecurrenceClass, RecurrenceProjection
        from .recruitment import RecruitmentExecutionHandler, recruitment_next_due, recruitment_reset
        from .nova import NovaExecutionHandler, nova_next_due
        from .campaign import CampaignExecutionHandler, campaign_next_due
        from .bioenhancer import BioenhancerExecutionHandler, PRODUCT_ID as BIOENHANCER_TASK_ID, bioenhancer_next_due
        from .supply import SupplyExecutionHandler, PRODUCT_ID as SUPPLY_TASK_ID, supply_next_due
        from .ultimate import UltimateExecutionHandler, PRODUCT_ID as ULTIMATE_TASK_ID, ultimate_next_due
        from .enhancement import EnhancementExecutionHandler, PRODUCT_ID as ENHANCEMENT_TASK_ID, enhancement_next_due
        from .personal_might import PersonalMightExecutionHandler, PRODUCT_ID as PERSONAL_MIGHT_TASK_ID, personal_might_next_due

        if self.mode is not ServiceMode.SUPERVISED or self.state is None:
            raise ServiceError("serve requires an explicitly configured native runner")
        if not account_id.strip() or not server_id.strip():
            raise ServiceError("serve requires account and server identity")
        selected = tuple(dict.fromkeys(flow_ids if flow_ids is not None else (RECRUITMENT_FLOW_ID,)))
        if operator_request_id is not None:
            if (not isinstance(operator_request_id, str) or not operator_request_id.strip()
                    or len(operator_request_id) > 256
                    or any(item not in {ENHANCEMENT_FLOW_ID, ULTIMATE_FLOW_ID} for item in selected)):
                raise ServiceError("one-time repeat requires a nonempty request and only Enhancement/Ultimate")
            operator_request_id = operator_request_id.strip()
        if not selected or any(item not in servable_flow_names().values() for item in selected):
            raise ServiceError("serve requires an explicitly supported native route")
        runners = {RECRUITMENT_FLOW_ID: self.recruitment_runner, NOVA_FLOW_ID: self.nova_runner,
                   CAMPAIGN_FLOW_ID: self.campaign_runner, BIOENHANCER_FLOW_ID: self.bioenhancer_runner,
                   SUPPLY_FLOW_ID: self.supply_runner, ULTIMATE_FLOW_ID: self.ultimate_runner,
                   ENHANCEMENT_FLOW_ID: self.enhancement_runner, PERSONAL_MIGHT_FLOW_ID: self.personal_might_runner}
        if any(not callable(runners[item]) for item in selected):
            raise ServiceError("serve requires an explicitly configured runner for every selected flow")
        state = self.state
        entries = tuple(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id in selected)
        effective_descriptors = {entry.flow_id: (
            replace(entry.descriptor, allows_pending_resource_observation=True)
            if entry.flow_id == CAMPAIGN_FLOW_ID else entry.descriptor
        ) for entry in entries}
        previous_resets = {}
        executor_results = {}
        with RuntimeInputLock(owner="automation-service", invocation_id=state.owner_instance_id) as owner:
            def execute(run, facts):
                flow_id = run.flow_id
                descriptor = effective_descriptors[flow_id]
                executor_results[flow_id] = {}
                recruitment = flow_id == RECRUITMENT_FLOW_ID
                prefix = {RECRUITMENT_FLOW_ID: "RECRUITMENT", NOVA_FLOW_ID: "NOVA",
                          CAMPAIGN_FLOW_ID: "CAMPAIGN", BIOENHANCER_FLOW_ID: "BIOENHANCER",
                          SUPPLY_FLOW_ID: "SUPPLY", ULTIMATE_FLOW_ID: "ULTIMATE",
                          ENHANCEMENT_FLOW_ID: "ENHANCEMENT", PERSONAL_MIGHT_FLOW_ID: "PERSONAL_MIGHT"}[flow_id]
                interrupted = f"EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:{run.run_id}"
                task_id = {RECRUITMENT_FLOW_ID: MAINTENANCE_TASK_ID, NOVA_FLOW_ID: NOVA_TASK_ID,
                           CAMPAIGN_FLOW_ID: CAMPAIGN_FLOW_ID, BIOENHANCER_FLOW_ID: BIOENHANCER_TASK_ID,
                           SUPPLY_FLOW_ID: SUPPLY_TASK_ID, ULTIMATE_FLOW_ID: ULTIMATE_TASK_ID,
                           ENHANCEMENT_FLOW_ID: ENHANCEMENT_TASK_ID, PERSONAL_MIGHT_FLOW_ID: PERSONAL_MIGHT_TASK_ID}[flow_id]
                identity = SchedulerIdentity(account_id, server_id, facts.reset_id, task_id)
                previous_reset = previous_resets.get(flow_id)
                reset_change = None

                def checkpoint_fences():
                    owner.assert_held(owner.owner, owner.invocation_id)
                    if stop.is_set():
                        raise ServiceError("STOP_REQUESTED")
                    current = state.get_flow(flow_id)
                    control = state.get_service()
                    if (not control.enabled or control.generation != run.service_generation
                            or current is None or not current.enabled
                            or current.generation != run.claimed_flow_generation
                            or (current.blocked and current.blocked_reason != interrupted)):
                        raise ServiceError("SERVICE_OR_FLOW_DISABLED")
                    now = clock()
                    if not state.observe_clock(now).accepted:
                        raise ServiceError("CLOCK_ROLLBACK")
                    if state.renew_service_lease(
                        owner_instance_id=run.owner_instance_id,
                        process_start_token=run.process_start_token,
                        lease_generation=run.lease_generation, now_utc_epoch=now,
                    ) is None:
                        raise ServiceError("SERVICE_LEASE_LOST")
                    validation = state.validate_dispatch(
                        run.run_id, owner_instance_id=run.owner_instance_id,
                        process_start_token=run.process_start_token, run_token=run.run_token,
                        lease_generation=run.lease_generation, now_utc_epoch=now,
                        allow_executor_marker=True,
                    )
                    if not validation.valid:
                        raise ServiceError(f"DISPATCH_FENCE_FAILED:{validation.reason}")
                    return now

                def checkpoint():
                    nonlocal reset_change
                    now = checkpoint_fences()
                    # AP occurrences retain their claim identity across midnight;
                    # a calendar date change does not reset ordinary AP spending.
                    if (recruitment_reset(now) != identity.reset_id
                            and (descriptor.reset_scoped
                                 or descriptor.recurrence_class is not RecurrenceClass.AP_REGENERATION)):
                        reset_change = ServiceError(f"RESET_CHANGED_DURING_{prefix}")
                        raise reset_change

                # Keep the existing crash marker until terminal projection succeeds.
                result = {}
                startup_result = None
                startup_verified = False
                runner_entered = False
                accounted = False
                action_count_field = {
                    RECRUITMENT_FLOW_ID: "recruitment_dispatch_count",
                    NOVA_FLOW_ID: "praise_transport_calls",
                    CAMPAIGN_FLOW_ID: "campaign_dispatch_count",
                    BIOENHANCER_FLOW_ID: "free_research_transport_calls",
                    SUPPLY_FLOW_ID: "hold_transport_calls",
                    ULTIMATE_FLOW_ID: "ultimate_dispatch_count",
                    ENHANCEMENT_FLOW_ID: "enhancement_dispatch_count",
                    PERSONAL_MIGHT_FLOW_ID: "praise_transport_calls",
                }[flow_id]

                def record_consumption():
                    nonlocal accounted
                    if result.get("accounting_verified") is False:
                        raise ServiceError(
                            f"{prefix}_CONSUMPTION_ACCOUNTING_UNVERIFIED:"
                            f"{result.get('accounting_error') or 'native totals are a lower bound'}"
                        )
                    consumed_inputs = result.get("total_input_count", result.get("input_count"))
                    consumed_actions = result.get(action_count_field)
                    if type(consumed_inputs) is not int or type(consumed_actions) is not int:
                        raise ServiceError(f"{prefix}_CONSUMPTION_ACCOUNTING_MISSING")
                    recorded = state.record_executor_consumption(
                        run.run_id,
                        consumed_inputs=consumed_inputs, consumed_actions=consumed_actions,
                        owner_instance_id=run.owner_instance_id,
                        process_start_token=run.process_start_token,
                        run_token=run.run_token, lease_generation=run.lease_generation,
                        now_utc_epoch=clock(),
                        terminal_accounting=True,
                    )
                    if recorded is None:
                        raise ServiceError(f"{prefix}_CONSUMPTION_ACCOUNTING_REJECTED")
                    accounted = True
                    return consumed_actions

                try:
                    current = state.get_flow(flow_id)
                    if current is None or state.block_flow(
                        flow_id, interrupted, expected_row_version=current.row_version,
                        expected_generation=run.claimed_flow_generation,
                        expected_blocked_reason=None,
                    ) is None:
                        raise ServiceError("EXECUTOR_MARKER_INSTALL_REJECTED")
                    checkpoint()
                    if self.application_startup is not None:
                        startup_result = self.application_startup(flow_id, run.run_id, owner, checkpoint)
                        if (not isinstance(startup_result, dict)
                                or type(startup_result.get("system_launch_count")) is not int
                                or startup_result["system_launch_count"] not in (0, 1)
                                or type(startup_result.get("game_input_count")) is not int
                                or startup_result.get("game_input_count") != 0
                                or startup_result.get("status") not in {"already_foreground", "launched"}
                                or (startup_result["status"] == "already_foreground"
                                    and (startup_result["system_launch_count"] != 0
                                         or startup_result.get("transport_status") not in (None, "not_attempted")))
                                or (startup_result["status"] == "launched"
                                    and (startup_result["system_launch_count"] != 1
                                         or startup_result.get("route_ready") is not True
                                         or startup_result.get("transport_status") != "returned"))):
                            raise ServiceError("APPLICATION_STARTUP_ACCOUNTING_INVALID")
                        startup_verified = True
                        checkpoint()
                    options = {"runtime_input_lock": owner} if flow_id in {BIOENHANCER_FLOW_ID, SUPPLY_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID} else {}
                    if operator_request_id is not None:
                        if run.mode != "manual" or run.occurrence_basis != operator_request_id:
                            raise ServiceError("MANUAL_REPEAT_CLAIM_MISMATCH")
                        options["operator_request_id"] = operator_request_id
                    runner_entered = True
                    result = runners[flow_id](identity, previous_reset, checkpoint, **options)
                    if startup_result is not None:
                        result = dict(result, application_startup=startup_result,
                                      system_launch_count=startup_result.get("system_launch_count"))
                    executor_results[flow_id] = result
                    consumed_actions = record_consumption()
                    due = {RECRUITMENT_FLOW_ID: recruitment_next_due, NOVA_FLOW_ID: nova_next_due,
                           CAMPAIGN_FLOW_ID: campaign_next_due, BIOENHANCER_FLOW_ID: bioenhancer_next_due,
                           SUPPLY_FLOW_ID: supply_next_due, ULTIMATE_FLOW_ID: ultimate_next_due,
                           ENHANCEMENT_FLOW_ID: enhancement_next_due, PERSONAL_MIGHT_FLOW_ID: personal_might_next_due}[flow_id](
                        result, identity, facts.now_utc_epoch
                    )
                    checkpoint()
                    outcome = NormalizedOutcome.DEFERRED
                    if flow_id in {SUPPLY_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID}:
                        # Verified no-work observes prior completion; current
                        # dispatches complete this reset's route effect.
                        outcome = (NormalizedOutcome.ALREADY_COMPLETE if result.get("no_work") is True
                                   else NormalizedOutcome.COMPLETE_FOR_RESET)
                    elif flow_id == ULTIMATE_FLOW_ID:
                        outcome = (NormalizedOutcome.ALREADY_COMPLETE if result.get("status") == "already_completed"
                                   else NormalizedOutcome.COMPLETE_FOR_RESET)
                    return NormalizedResult(
                        outcome, f"{prefix}_PASS_VERIFIED",
                        verified=True, next_eligible_at=due,
                        action_count=(result["committed_ap_effect_count"] if flow_id == CAMPAIGN_FLOW_ID
                                      else result["committed_action_count"] if flow_id in {ULTIMATE_FLOW_ID, PERSONAL_MIGHT_FLOW_ID}
                                      else result["actions_completed"] if recruitment else consumed_actions),
                        observed_progress=result,
                    )
                except Exception as exc:
                    failed_startup = getattr(exc, "startup_result", None)
                    if isinstance(failed_startup, dict):
                        startup_result = failed_startup
                    cause, seen_causes = exc, set()
                    while cause is not None and cause is not reset_change and id(cause) not in seen_causes:
                        seen_causes.add(id(cause))
                        cause = cause.__cause__
                    startup_has_no_attempt = (startup_result is None or (
                        type(startup_result.get("system_launch_count")) is int
                        and startup_result["system_launch_count"] == 0
                        and type(startup_result.get("game_input_count")) is int
                        and startup_result["game_input_count"] == 0
                        and startup_result.get("transport_status") in (None, "not_attempted")
                    ))
                    if (not runner_entered and reset_change is not None and cause is reset_change
                            and (startup_verified or startup_has_no_attempt)):
                        try:
                            now = checkpoint_fences()
                            require_canonical_unresolved_clear()
                            result = {"status": "deferred_reset_change", "reset_rollover_deferred": True,
                                      "native_runner_entered": False, "accounting_verified": True,
                                      "input_count": 0, "total_input_count": 0, action_count_field: 0,
                                      "account_id": account_id, "server_id": server_id,
                                      "reset_id": identity.reset_id, "observed_reset_id": recruitment_reset(now),
                                      "completed_at_utc": now}
                            if startup_result is not None:
                                result.update(application_startup=startup_result,
                                              system_launch_count=startup_result["system_launch_count"])
                            record_consumption()
                            executor_results[flow_id] = result
                            return NormalizedResult(
                                NormalizedOutcome.DEFERRED, f"{prefix}_RESET_ROLLOVER_DEFERRED",
                                verified=False, next_eligible_at=now, action_count=0,
                                observed_progress=result,
                            )
                        except Exception as fence_error:
                            exc = fence_error
                    partial_result = getattr(exc, "partial_result", None)
                    if isinstance(partial_result, dict):
                        result = partial_result
                    accounting_error = None
                    if result and not accounted:
                        try:
                            record_consumption()
                        except Exception as accounting_exc:
                            accounting_error = str(accounting_exc)
                    if startup_result is not None:
                        result = dict(result, application_startup=startup_result,
                                      system_launch_count=startup_result.get("system_launch_count"))
                    reason = f"{prefix}_REQUIRES_INSPECTION:{exc}"
                    if accounting_error:
                        reason += f"; accounting_rejected:{accounting_error}"
                        result = dict(result, canonical_accounting="rejected",
                                      canonical_accounting_reason=accounting_error)
                    executor_results[flow_id] = result
                    state.block_flow(
                        flow_id, reason, expected_blocked_reason=interrupted,
                        expected_generation=run.claimed_flow_generation,
                    )
                    return NormalizedResult(
                        NormalizedOutcome.BLOCKED, reason, verified=False,
                        observed_progress=result if isinstance(result, dict) else {},
                    )

            handlers = {}
            for entry in entries:
                handler_type = {RECRUITMENT_FLOW_ID: RecruitmentExecutionHandler,
                                NOVA_FLOW_ID: NovaExecutionHandler,
                                CAMPAIGN_FLOW_ID: CampaignExecutionHandler,
                                BIOENHANCER_FLOW_ID: BioenhancerExecutionHandler,
                                SUPPLY_FLOW_ID: SupplyExecutionHandler,
                                ULTIMATE_FLOW_ID: UltimateExecutionHandler,
                                ENHANCEMENT_FLOW_ID: EnhancementExecutionHandler,
                                PERSONAL_MIGHT_FLOW_ID: PersonalMightExecutionHandler}[entry.flow_id]
                options = ({"stage": self.campaign_runner.stage} if entry.flow_id == CAMPAIGN_FLOW_ID
                           else {"flow_spec": entry.spec} if entry.flow_id in {ULTIMATE_FLOW_ID, PERSONAL_MIGHT_FLOW_ID} else {})
                handlers[entry.flow_id] = handler_type(entry.registration, execute, **options)
                if entry.flow_id in {SUPPLY_FLOW_ID, ENHANCEMENT_FLOW_ID}:
                    handlers[entry.flow_id].flow_spec = entry.spec
            coordinator = UtcPulseCoordinator(
                state, tuple(effective_descriptors[entry.flow_id] for entry in entries), handlers, clock=clock,
                allow_completed_daily=operator_request_id is not None,
            )
            while not stop.is_set():
                if not state.get_service_enabled():
                    emit({"status": "stopped", "reason": "SERVICE_DISABLED"})
                    return
                for entry in entries:
                    if stop.is_set() or not state.get_service_enabled():
                        break
                    now = clock()
                    flow = state.get_flow(entry.flow_id)
                    previous_resets[entry.flow_id] = flow.reset_id if flow else None
                    if flow is None or not flow.enabled or flow.blocked:
                        emit({"status": "paused", "flow_id": entry.flow_id,
                              "reason": flow.blocked_reason if flow and flow.blocked else "FLOW_DISABLED"})
                        continue
                    if (entry.flow_id == RECRUITMENT_FLOW_ID and flow.reset_id == recruitment_reset(now)
                            and flow.next_due_at_utc is not None):
                        observation_deadline = getattr(runners[entry.flow_id], "observation_deadline", None)
                        if callable(observation_deadline):
                            identity = SchedulerIdentity(account_id, server_id, flow.reset_id, MAINTENANCE_TASK_ID)
                            deadline = observation_deadline(identity, flow.last_completed_at_utc, now)
                            if deadline is not None and deadline < flow.next_due_at_utc:
                                flow = state.update_schedule(
                                    entry.flow_id, next_due_at_utc=deadline,
                                    expected_row_version=flow.row_version, expected_generation=flow.generation,
                                    expected_reset_id=flow.reset_id,
                                    expected_next_due_at_utc=flow.next_due_at_utc,
                                    require_enabled_unblocked=True,
                                )
                                if flow is None:
                                    continue
                    projection = RecurrenceProjection(
                        (RecurrenceClass.DAILY_ONCE_PER_RESET if entry.flow_id in {SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID}
                         else RecurrenceClass.COOLDOWN), observed_at_utc=now,
                        next_eligible_at=None if operator_request_id is not None else flow.next_due_at_utc,
                    )
                    if entry.flow_id == CAMPAIGN_FLOW_ID:
                        # A restart before due must not connect to the device.
                        if flow.next_due_at_utc is not None and flow.next_due_at_utc > now:
                            continue
                        # Scheduler metadata admits an observation inside the claim;
                        # it asserts neither an AP balance nor a game observation time.
                        projection = RecurrenceProjection(
                            RecurrenceClass.AP_REGENERATION,
                            next_eligible_at=flow.next_due_at_utc,
                            generation=str(flow.next_occurrence_key),
                            observation_pending=True,
                        )
                    facts = SchedulerFacts(
                        account_id, server_id, recruitment_reset(now), now,
                        health_ok=True, accepted_product=entry.product_id,
                        product_revision=entry.product_revision, registration_status=entry.registration_status,
                        scheduler_eligible=entry.scheduler_eligible, owner_available=owner.held,
                        clock_ok=True, reset_agreement=True,
                        projections={entry.flow_id: projection},
                    )
                    report = (coordinator.run_manual(entry.flow_id, facts, operator_request_id=operator_request_id)
                              if operator_request_id is not None else coordinator.pulse(facts, flow_id=entry.flow_id))
                    if operator_request_id is not None and report.result is None:
                        emit({"status": "refused", "flow_id": entry.flow_id,
                              "operator_request_id": operator_request_id, "reason": report.reason_code})
                        return
                    if report.result is not None:
                        result = report.result
                        prefix = {RECRUITMENT_FLOW_ID: "RECRUITMENT", NOVA_FLOW_ID: "NOVA",
                                  CAMPAIGN_FLOW_ID: "CAMPAIGN", BIOENHANCER_FLOW_ID: "BIOENHANCER",
                                  SUPPLY_FLOW_ID: "SUPPLY", ULTIMATE_FLOW_ID: "ULTIMATE",
                                  ENHANCEMENT_FLOW_ID: "ENHANCEMENT", PERSONAL_MIGHT_FLOW_ID: "PERSONAL_MIGHT"}[entry.flow_id]
                        completed = result.verified and result.reason_code == f"{prefix}_PASS_VERIFIED"
                        rollover_deferred = (
                            result.reason_code == f"{prefix}_RESET_ROLLOVER_DEFERRED"
                            and result.verified is False
                            and result.observed_progress.get("reset_rollover_deferred") is True
                            and (retained_run := state.get_run(report.candidate.claim.run_id)) is not None
                            and retained_run.state is RunState.DEFERRED
                            and retained_run.consumed_inputs == retained_run.consumed_actions == 0
                            and not state.has_unresolved_actions(retained_run.run_id)
                        )
                        if completed or rollover_deferred:
                            claim = report.candidate.claim
                            unblocked = state.unblock_flow(
                                entry.flow_id, expected_generation=claim.claimed_flow_generation,
                                expected_blocked_reason=f"EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:{claim.run_id}",
                            )
                            if rollover_deferred and unblocked is None:
                                rollover_deferred = False
                        emit({"status": "completed" if completed else "deferred" if rollover_deferred else "blocked",
                              "flow_id": entry.flow_id, "reason": report.reason_code,
                              "next_due_at_utc": result.next_eligible_at,
                              "result": dict(result.observed_progress)
                              or executor_results.get(entry.flow_id, {})})
                if operator_request_id is not None:
                    return
                if stop.is_set() or not state.get_service_enabled():
                    continue
                deadlines = [flow.next_due_at_utc for entry in entries
                             if (flow := state.get_flow(entry.flow_id)) is not None
                             and flow.enabled and not flow.blocked and flow.next_due_at_utc is not None
                             and flow.next_due_at_utc > clock()]
                delay = min(deadlines) - clock() if deadlines else 30
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
