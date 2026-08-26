"""Thin composition facade for local status, observation, and one-pulse execution."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .adapters import (
    AdapterKind,
    DeviceAdapter,
    FakeDeviceAdapter,
    SupervisedBlueStacksAdapter,
)
from .contracts import PerceptionEnvelope, SchedulerFacts, ServiceMode
from .handlers import (
    DisabledHandler,
    RecruitmentMaintenanceSelectionHandler,
    NovaPraiseSelectionHandler,
    WorldNavigationSelectionHandler,
)
from .operations import HealthSnapshot, OperationsService
from .registry import (
    DisabledProductionEntry,
    RegisteredDispatchSnapshot,
    NOVA_FLOW_ID,
    RECRUITMENT_FLOW_ID,
    WORLD_FLOW_ID,
    load_disabled_registry,
)
from .scheduler import DisabledProductionAuthority, PulseReport, UtcPulseCoordinator
from safe_action_core import SQLiteSchedulerInvocationRepository


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceStatus:
    mode: ServiceMode
    adapter_kind: str
    registered_flows: tuple[str, ...]
    disabled_flows: tuple[str, ...]
    scheduler_eligible: bool


def registry_descriptor(entry: DisabledProductionEntry):
    """Compose a scheduler descriptor from one validated registry entry."""

    from .contracts import FlowDescriptor

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
    else:
        family = "disabled"
        variant = "disabled"
    cadence = (
        "cooldown_pulse"
        if entry.flow_id == RECRUITMENT_FLOW_ID and registered
        else "daily_once_per_reset"
    )
    return FlowDescriptor(
        flow_id=entry.flow_id,
        owner="automation_service",
        family=family if registered else "disabled",
        variant=variant if registered else "disabled",
        cadence=cadence,
        reset_scoped=entry.flow_id != RECRUITMENT_FLOW_ID,
        priority=1 if registered else 100,
        scheduler_eligible=registered and entry.scheduler_eligible,
        accepted_product=entry.product_id if registered else False,
        product_revision=entry.product_revision if registered else None,
        registration_status=entry.registration_status,
    )


def registry_scheduler_components(
    repository: SQLiteSchedulerInvocationRepository,
    *,
    path=None,
    clock=time.time,
) -> tuple[
    tuple[DisabledProductionEntry, ...],
    tuple[Any, ...],
    dict[str, Any],
    UtcPulseCoordinator,
]:
    """Build the offline scheduler solely from the checked-in registry."""

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
        else:
            handlers[entry.flow_id] = DisabledHandler(descriptor)
    # Keep authority and descriptors bound to the same validated registry
    # snapshot.  DisabledProductionAuthority normally loads the default path
    # itself; replacing its private projection avoids a second, potentially
    # different registration authority when callers supply a registry path.
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


# Public descriptive aliases used by offline callers and focused contract checks.
build_registry_scheduler = registry_scheduler_components
build_scheduler_components = registry_scheduler_components


class AutomationService:
    """Composition root that keeps production admission disabled by default."""

    def __init__(
        self,
        *,
        mode: ServiceMode | str = ServiceMode.DISABLED,
        adapter: DeviceAdapter | None = None,
        coordinator: UtcPulseCoordinator | None = None,
        operations: OperationsService | None = None,
    ) -> None:
        if str(mode).casefold() == "automatic":
            raise ServiceError("automatic mode is unsupported")
        try:
            resolved_mode = mode if isinstance(mode, ServiceMode) else ServiceMode(mode)
        except ValueError as exc:
            raise ServiceError(f"unsupported service mode: {mode}") from exc
        self.mode = resolved_mode
        self.adapter = adapter or FakeDeviceAdapter()
        self.coordinator = coordinator
        if self.mode is ServiceMode.SUPERVISED and not isinstance(
            self.adapter, SupervisedBlueStacksAdapter
        ):
            raise ServiceError(
                "supervised mode requires the executor-bound BlueStacks adapter"
            )
        if self.mode is ServiceMode.SUPERVISED and (
            self.coordinator is None
            or type(self.coordinator.activation_authority)
            is not DisabledProductionAuthority
        ):
            raise ServiceError(
                "supervised mode requires the registry-backed production authority"
            )
        if self.mode is ServiceMode.DRY_RUN and self.adapter.kind not in {
            AdapterKind.FAKE,
            AdapterKind.REPLAY,
        }:
            raise ServiceError("dry_run requires fake or replay adapter")
        self.operations = operations or OperationsService(
            adapter_status=self.adapter.status,
            database_probe=lambda: True,
            lease_held=lambda: False,
        )

    def status(self) -> ServiceStatus:
        registry = load_disabled_registry()
        registered = tuple(item.flow_id for item in registry if item.registered)
        return ServiceStatus(
            mode=self.mode,
            adapter_kind=self.adapter.kind.value,
            registered_flows=registered,
            disabled_flows=tuple(
                item.flow_id for item in registry if not item.registered
            ),
            scheduler_eligible=any(item.scheduler_eligible for item in registry),
        )

    def observe(self):
        return self.adapter.capture()

    def pulse(
        self,
        facts: SchedulerFacts,
        *,
        perception: PerceptionEnvelope | None = None,
    ) -> PulseReport:
        if self.mode in {ServiceMode.DISABLED, ServiceMode.OBSERVE_ONLY}:
            raise ServiceError(f"{self.mode.value} service cannot execute a pulse")
        if self.coordinator is None:
            raise ServiceError("pulse coordinator is not configured")
        if self.mode is ServiceMode.DRY_RUN:
            if self.adapter.kind not in {AdapterKind.FAKE, AdapterKind.REPLAY}:
                raise ServiceError("dry_run requires fake or replay adapter")
            if isinstance(
                self.coordinator.activation_authority, DisabledProductionAuthority
            ):
                raise ServiceError(
                    "dry_run requires an explicitly injected offline authority"
                )
        if self.mode is ServiceMode.SUPERVISED and not isinstance(
            self.adapter, SupervisedBlueStacksAdapter
        ):
            raise ServiceError(
                "supervised mode requires the executor-bound BlueStacks adapter"
            )
        return self.coordinator.pulse(facts, perception=perception)

    def health(self, **kwargs: Any) -> HealthSnapshot:
        if "mode" in kwargs:
            raise ServiceError("health mode is owned by the service")
        return self.operations.health(mode=self.mode, **kwargs)
