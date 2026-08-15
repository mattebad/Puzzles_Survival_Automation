"""Thin composition facade for local status, observation, and one-pulse execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapters import AdapterKind, DeviceAdapter, FakeDeviceAdapter, SupervisedBlueStacksAdapter
from .contracts import PerceptionEnvelope, SchedulerFacts, ServiceMode
from .operations import HealthSnapshot, OperationsService
from .registry import load_disabled_registry
from .scheduler import DisabledProductionAuthority, PulseReport, UtcPulseCoordinator


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceStatus:
    mode: ServiceMode
    adapter_kind: str
    registered_flows: tuple[str, ...]
    disabled_flows: tuple[str, ...]
    scheduler_eligible: bool


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
            raise ServiceError("supervised mode requires the executor-bound BlueStacks adapter")
        if (
            self.mode is ServiceMode.SUPERVISED
            and (
                self.coordinator is None
                or type(self.coordinator.activation_authority)
                is not DisabledProductionAuthority
            )
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
        return ServiceStatus(
            mode=self.mode,
            adapter_kind=self.adapter.kind.value,
            registered_flows=(),
            disabled_flows=tuple(item.flow_id for item in registry),
            scheduler_eligible=False,
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
            if isinstance(self.coordinator.activation_authority, DisabledProductionAuthority):
                raise ServiceError("dry_run requires an explicitly injected offline authority")
        if self.mode is ServiceMode.SUPERVISED and not isinstance(
            self.adapter, SupervisedBlueStacksAdapter
        ):
            raise ServiceError("supervised mode requires the executor-bound BlueStacks adapter")
        return self.coordinator.pulse(facts, perception=perception)

    def health(self, **kwargs: Any) -> HealthSnapshot:
        if "mode" in kwargs:
            raise ServiceError("health mode is owned by the service")
        return self.operations.health(mode=self.mode, **kwargs)

