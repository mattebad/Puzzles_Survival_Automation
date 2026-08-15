"""Local health, summary, alert, and retention classification operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import shutil
from typing import Any, Callable, Mapping, Protocol

from .adapters import AdapterStatus
from .contracts import ServiceMode


class AlertSink(Protocol):
    def emit(self, level: str, code: str, detail: str) -> None:
        ...


class LocalAlertSink:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def emit(self, level: str, code: str, detail: str) -> None:
        self.events.append({"level": level, "code": code, "detail": detail})


class FakeAlertSink(LocalAlertSink):
    pass


@dataclass(frozen=True)
class HealthSnapshot:
    mode: str
    heartbeat_utc_epoch: float
    lease_held: bool
    database_ok: bool
    disk_free_bytes: int
    disk_quota_bytes: int | None
    last_frame_id: str | None
    last_frame_age_seconds: float | None
    adapter_kind: str
    adapter_connected: bool
    current_state: str
    current_task: str | None
    breakers: tuple[str, ...]
    unresolved_action: bool
    next_wake_utc_epoch: float | None
    disk_ok: bool
    frame_fresh: bool
    lease_required: bool
    adapter_required: bool

    @property
    def healthy(self) -> bool:
        return (
            self.database_ok
            and self.disk_ok
            and self.frame_fresh
            and (not self.lease_required or self.lease_held)
            and (not self.adapter_required or self.adapter_connected)
            and not self.breakers
            and not self.unresolved_action
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self) | {"healthy": self.healthy}


@dataclass(frozen=True)
class RetentionClassification:
    path: str
    classification: str
    reason: str
    deletion_allowed: bool = False


class OperationsService:
    def __init__(
        self,
        *,
        adapter_status: Callable[[], AdapterStatus],
        database_probe: Callable[[], bool],
        lease_held: Callable[[], bool],
        disk_path: str = ".",
        disk_quota_bytes: int | None = None,
        alert_sink: AlertSink | None = None,
    ) -> None:
        self._adapter_status = adapter_status
        self._database_probe = database_probe
        self._lease_held = lease_held
        self._disk_path = disk_path
        self._disk_quota_bytes = disk_quota_bytes
        self.alert_sink = alert_sink or LocalAlertSink()

    def health(
        self,
        *,
        current_state: str = "unknown",
        current_task: str | None = None,
        breakers: tuple[str, ...] = (),
        unresolved_action: bool = False,
        next_wake_utc_epoch: float | None = None,
        last_frame_age_seconds: float | None = None,
        mode: ServiceMode | str = ServiceMode.DISABLED,
        minimum_disk_free_bytes: int = 0,
        require_fresh_frame: bool | None = None,
        fresh_frame_max_age_seconds: float = 30.0,
    ) -> HealthSnapshot:
        usage = shutil.disk_usage(self._disk_path)
        adapter = self._adapter_status()
        resolved_mode = mode if isinstance(mode, ServiceMode) else ServiceMode(mode)
        active = resolved_mode is ServiceMode.SUPERVISED
        required_free_bytes = max(
            minimum_disk_free_bytes,
            self._disk_quota_bytes or 0,
        )
        frame_fresh = (
            last_frame_age_seconds is not None
            and 0 <= last_frame_age_seconds <= fresh_frame_max_age_seconds
        )
        frame_required = active if require_fresh_frame is None else require_fresh_frame
        snapshot = HealthSnapshot(
            mode=resolved_mode.value,
            heartbeat_utc_epoch=datetime.now(timezone.utc).timestamp(),
            lease_held=bool(self._lease_held()),
            database_ok=bool(self._database_probe()),
            disk_free_bytes=usage.free,
            disk_quota_bytes=self._disk_quota_bytes,
            last_frame_id=adapter.last_frame_id,
            last_frame_age_seconds=last_frame_age_seconds,
            adapter_kind=adapter.kind.value,
            adapter_connected=adapter.connected,
            current_state=current_state,
            current_task=current_task,
            breakers=tuple(breakers),
            unresolved_action=unresolved_action,
            next_wake_utc_epoch=next_wake_utc_epoch,
            disk_ok=usage.free >= required_free_bytes,
            frame_fresh=(frame_fresh if frame_required else True),
            lease_required=active,
            adapter_required=active,
        )
        if not snapshot.healthy:
            self.alert_sink.emit("warning", "SERVICE_UNHEALTHY", snapshot_to_reason(snapshot))
        return snapshot

    def status(self, **kwargs: Any) -> dict[str, Any]:
        return self.health(**kwargs).to_mapping()

    @staticmethod
    def classify_retention(path: str, *, category: str, reason: str = "") -> RetentionClassification:
        if not path.strip() or not category.strip():
            raise ValueError("retention classification requires path and category")
        return RetentionClassification(
            path=path,
            classification=category,
            reason=reason or "classification only; deletion requires a separate evidence workflow",
            deletion_allowed=False,
        )


def snapshot_to_reason(snapshot: HealthSnapshot) -> str:
    reasons: list[str] = []
    if snapshot.lease_required and not snapshot.lease_held:
        reasons.append("lease_not_held")
    if not snapshot.database_ok:
        reasons.append("database_probe_failed")
    if snapshot.breakers:
        reasons.extend(f"breaker:{item}" for item in snapshot.breakers)
    if snapshot.unresolved_action:
        reasons.append("unresolved_action")
    if not snapshot.disk_ok:
        reasons.append("disk_quota_failed")
    if not snapshot.frame_fresh:
        reasons.append("frame_stale")
    if snapshot.adapter_required and not snapshot.adapter_connected:
        reasons.append("adapter_disconnected")
    return ",".join(reasons) or "adapter_unavailable"


def structured_summary(
    *,
    health: HealthSnapshot,
    task_summaries: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "automation-service-summary-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "health": health.to_mapping(),
        "tasks": {str(key): dict(value) for key, value in (task_summaries or {}).items()},
    }

