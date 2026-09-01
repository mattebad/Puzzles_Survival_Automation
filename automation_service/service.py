"""Thin composition facade for local status, observation, and one-pulse execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Any

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
from .state import BotStateManager
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
    try:
        connection = sqlite3.connect(
            f"file:{Path(path).expanduser().resolve()}?mode=ro",
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
    pass


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
):
    """Compose scheduler solely from static canonical facts and SQLite state."""

    registrations = CANONICAL_FLOW_REGISTRY
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
):
    """Build canonical components from ``BotStateManager``.

    ``path`` names the retired JSON registration authority and is rejected for
    canonical state managers.  Unmigrated repository callers can opt into the
    separate :func:`legacy_registry_scheduler_components` API.
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
        return _canonical_registry_scheduler_components(repository, clock=clock)
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
    """Composition root backed by the canonical SQLite runtime authority."""

    def __init__(
        self,
        *,
        mode: ServiceMode | str = ServiceMode.DISABLED,
        adapter: DeviceAdapter | None = None,
        coordinator: UtcPulseCoordinator | None = None,
        operations: OperationsService | None = None,
        state_manager: BotStateManager | None = None,
        state: BotStateManager | None = None,
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
        self.coordinator = coordinator
        if self.coordinator is None and self.state is not None:
            _entries, _descriptors, _handlers, self.coordinator = (
                registry_scheduler_components(self.state)
            )
        if self.state is None and self.coordinator is not None:
            candidate_state = getattr(self.coordinator, "repository", None)
            if isinstance(candidate_state, BotStateManager):
                self.state = candidate_state
        if self.mode is ServiceMode.SUPERVISED and not isinstance(
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
        result = self.state.set_flow_enabled(
            flow_id, enabled, now_utc_epoch=now_utc_epoch
        )
        if result is None:
            raise ServiceError(f"unknown flow: {flow_id}")
        return result

    def enable_flow(self, flow_id: str, *, now_utc_epoch: float | None = None):
        if self.state is None:
            raise ServiceError("state manager is not configured")
        result = self.state.set_flow_enabled(
            flow_id, True, now_utc_epoch=now_utc_epoch
        )
        if result is None:
            raise ServiceError(f"unknown flow: {flow_id}")
        return result

    def disable_flow(self, flow_id: str, *, now_utc_epoch: float | None = None):
        if self.state is None:
            raise ServiceError("state manager is not configured")
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
        return self.coordinator.pulse(
            facts, perception=perception, shadow=shadow
        )

    def run(
        self,
        flow_id: str,
        facts: SchedulerFacts,
        *,
        live: bool = False,
        perception: PerceptionEnvelope | None = None,
    ) -> PulseReport:
        if self.coordinator is None:
            raise ServiceError("pulse coordinator is not configured")
        if live and self.mode in {
            ServiceMode.DISABLED,
            ServiceMode.OBSERVE_ONLY,
        }:
            raise ServiceError(f"{self.mode.value} service cannot execute a live run")
        if not live:
            return self.coordinator.shadow(
                facts, perception=perception, flow_id=flow_id
            )
        if self.state is None:
            raise ServiceError("live runs require canonical state manager")
        if not self.state.get_service_enabled():
            raise ServiceError("SERVICE_DISABLED")
        if not self.state.get_flow_enabled(flow_id):
            raise ServiceError("FLOW_DISABLED")
        return self.coordinator.run_manual(
            flow_id, facts, perception=perception
        )

    def health(self, **kwargs: Any) -> HealthSnapshot:
        if "mode" in kwargs:
            raise ServiceError("health mode is owned by the service")
        return self.operations.health(mode=self.mode, **kwargs)
