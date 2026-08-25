"""Strict, atomic production-registration authority for bounded flow canaries."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator, Mapping


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "tasks"
    / "flow_delivery_disabled_production_registry.json"
)
WORLD_FLOW_ID = "WORLD-MAP-NAVIGATION-FOUNDATION"
WORLD_PRODUCT_ID = "world_map_navigation"
WORLD_PRODUCT_REVISION = "world_map_navigation-v1"
WORLD_HANDLER_ID = "world_map_navigation_foundation_selection_handler"
WORLD_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
WORLD_PHASE_MODE = "phase_canary"
# Explicit aliases keep the fixed binding easy to consume without introducing
# a second registration vocabulary.
WORLD_SELECTION_HANDLER_ID = WORLD_HANDLER_ID
WORLD_PROFILE = WORLD_PROFILE_ID
WORLD_PRODUCT = WORLD_PRODUCT_ID
WORLD_REVISION = WORLD_PRODUCT_REVISION

# Entry fields are deliberately closed.  Runtime, queue, target, and scheduler
# implementation details do not belong in the production registration file.
ENTRY_FIELDS = frozenset(
    {
        "production_handler",
        "profile",
        "supported_profiles",
        "mode",
        "registration_status",
        "scheduler_eligible",
        "product_id",
        "product_revision",
    }
)


@dataclass(frozen=True)
class DisabledProductionEntry:
    flow_id: str
    production_handler: str | None
    profile: str | None
    supported_profiles: tuple[str, ...]
    mode: str
    registration_status: str
    scheduler_eligible: bool
    product_id: str | None = None
    product_revision: str | None = None

    @property
    def handler_id(self) -> str | None:
        """Stable spelling used by dispatch/evidence callers."""

        return self.production_handler

    @property
    def registered(self) -> bool:
        return self.registration_status == "REGISTERED"


@dataclass(frozen=True)
class RegisteredDispatchSnapshot:
    """Immutable dispatch-time copy of the one accepted World registration."""

    flow_id: str
    product_id: str
    product_revision: str
    production_handler: str
    profile: str
    mode: str
    registration_status: str
    scheduler_eligible: bool

    def __post_init__(self) -> None:
        expected = {
            "flow_id": WORLD_FLOW_ID,
            "product_id": WORLD_PRODUCT_ID,
            "product_revision": WORLD_PRODUCT_REVISION,
            "production_handler": WORLD_HANDLER_ID,
            "profile": WORLD_PROFILE_ID,
            "mode": WORLD_PHASE_MODE,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
        }
        actual = self.to_mapping()
        if actual != expected:
            raise ValueError(
                "dispatch registration snapshot is not the fixed World binding"
            )

    @classmethod
    def from_entry(cls, entry: DisabledProductionEntry) -> "RegisteredDispatchSnapshot":
        if not _entry_is_world_registered(entry):
            raise ValueError("only the exact registered World entry can be dispatched")
        return cls(
            flow_id=entry.flow_id,
            product_id=entry.product_id or "",
            product_revision=entry.product_revision or "",
            production_handler=entry.production_handler or "",
            profile=entry.profile or "",
            mode=entry.mode,
            registration_status=entry.registration_status,
            scheduler_eligible=entry.scheduler_eligible,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "product_id": self.product_id,
            "product_revision": self.product_revision,
            "production_handler": self.production_handler,
            "profile": self.profile,
            "mode": self.mode,
            "registration_status": self.registration_status,
            "scheduler_eligible": self.scheduler_eligible,
        }

    @property
    def handler_id(self) -> str:
        return self.production_handler


_REGISTRY_LOCK = threading.RLock()


def _entry_is_world_registered(entry: DisabledProductionEntry) -> bool:
    return bool(
        entry.flow_id == WORLD_FLOW_ID
        and entry.production_handler == WORLD_HANDLER_ID
        and entry.profile == WORLD_PROFILE_ID
        and entry.supported_profiles == (WORLD_PROFILE_ID,)
        and entry.product_id == WORLD_PRODUCT_ID
        and entry.product_revision == WORLD_PRODUCT_REVISION
        and entry.mode == WORLD_PHASE_MODE
        and entry.registration_status == "REGISTERED"
        and entry.scheduler_eligible is True
    )


def _entry_is_disabled(entry: DisabledProductionEntry) -> bool:
    return bool(
        entry.production_handler is None
        and entry.profile is None
        and entry.supported_profiles == ()
        and entry.product_id is None
        and entry.product_revision is None
        and entry.mode == "disabled"
        and entry.registration_status == "NOT_REGISTERED"
        and entry.scheduler_eligible is False
    )


def _validate_string_or_none(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(
            f"{field} must be unavailable or a normalized non-empty string"
        )
    return value


def _parse_entries(payload: Mapping[str, Any]) -> tuple[DisabledProductionEntry, ...]:
    if (
        payload.get("schema_version") != 1
        or payload.get("registry_kind") != "disabled_production_handlers"
    ):
        raise ValueError("unsupported disabled production registry")
    flows = payload.get("flows")
    if not isinstance(flows, Mapping) or not flows:
        raise ValueError("disabled production registry requires flows")

    entries: list[DisabledProductionEntry] = []
    for flow_id, value in flows.items():
        if (
            not isinstance(flow_id, str)
            or not flow_id.strip()
            or flow_id != flow_id.strip()
            or not isinstance(value, Mapping)
        ):
            raise ValueError("invalid disabled production registry entry")
        if set(value) != ENTRY_FIELDS:
            raise ValueError(
                "registry entry owns only fixed product/handler/profile registration fields"
            )
        supported = value["supported_profiles"]
        if type(supported) is not list or any(
            not isinstance(profile, str)
            or not profile.strip()
            or profile != profile.strip()
            for profile in supported
        ):
            raise ValueError(
                "supported_profiles must be a list of normalized non-empty strings"
            )
        eligible = value["scheduler_eligible"]
        if type(eligible) is not bool:
            raise ValueError("scheduler_eligible must be a boolean")
        mode = value["mode"]
        status = value["registration_status"]
        if not isinstance(mode, str) or not mode.strip() or mode != mode.strip():
            raise ValueError("registry mode must be a normalized string")
        if not isinstance(status, str) or status not in {
            "REGISTERED",
            "NOT_REGISTERED",
        }:
            raise ValueError("unsupported registry registration status")
        entry = DisabledProductionEntry(
            flow_id=flow_id,
            production_handler=_validate_string_or_none(
                value["production_handler"], "production_handler"
            ),
            profile=_validate_string_or_none(value["profile"], "profile"),
            supported_profiles=tuple(supported),
            mode=mode,
            registration_status=status,
            scheduler_eligible=eligible,
            product_id=_validate_string_or_none(value["product_id"], "product_id"),
            product_revision=_validate_string_or_none(
                value["product_revision"], "product_revision"
            ),
        )
        if entry.registration_status == "REGISTERED":
            if not _entry_is_world_registered(entry):
                raise ValueError(
                    "only the exact World phase-canary registration is allowed"
                )
        elif not _entry_is_disabled(entry):
            raise ValueError("all non-registered entries must remain fully disabled")
        entries.append(entry)

    registered = [entry for entry in entries if entry.registered]
    if len(registered) > 1:
        raise ValueError("production registry permits at most one registered flow")
    if registered and not _entry_is_world_registered(registered[0]):
        raise ValueError("registered production entry is not the fixed World binding")
    return tuple(sorted(entries, key=lambda item: item.flow_id))


def _load_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot load disabled production registry") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("disabled production registry must be an object")
    return payload


def load_disabled_registry(
    path: Path | None = None,
) -> tuple[DisabledProductionEntry, ...]:
    """Load and strictly validate the checked-in registration authority."""

    registry_path = Path(REGISTRY_PATH if path is None else path)
    with _REGISTRY_LOCK:
        return _parse_entries(_load_payload(registry_path))


load_production_registry = load_disabled_registry


@contextmanager
def _registry_file_lock(path: Path) -> Iterator[None]:
    """Serialize cross-process read/replace operations without a second authority."""

    lock_path = Path(str(path) + ".lock")
    descriptor: int | None = None
    started = time.monotonic()
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # A stale lock can only be reclaimed after a bounded wait; normal
            # concurrent callers wait for the holder and then retry.
            if time.monotonic() - started > 10.0:
                try:
                    if time.time() - lock_path.stat().st_mtime > 10.0:
                        lock_path.unlink()
                        continue
                except OSError:
                    pass
            time.sleep(0.005)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _write_payload_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def consume_registered_entry(
    flow_id: str = WORLD_FLOW_ID,
    *,
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered entry before any live runner input."""

    registry_path = Path(REGISTRY_PATH if path is None else path)
    if flow_id != WORLD_FLOW_ID:
        return None
    with _REGISTRY_LOCK, _registry_file_lock(registry_path):
        payload = dict(_load_payload(registry_path))
        entries = _parse_entries(payload)
        entry = next((item for item in entries if item.flow_id == flow_id), None)
        if entry is None or not _entry_is_world_registered(entry):
            return None
        snapshot = RegisteredDispatchSnapshot.from_entry(entry)
        flows = dict(payload["flows"])
        flows[flow_id] = {
            "production_handler": None,
            "profile": None,
            "supported_profiles": [],
            "mode": "disabled",
            "registration_status": "NOT_REGISTERED",
            "scheduler_eligible": False,
            "product_id": None,
            "product_revision": None,
        }
        payload["flows"] = flows
        # Validate the post-consumption state before replacing the authority.
        _parse_entries(payload)
        _write_payload_atomic(registry_path, payload)
        return snapshot


consume_world_registration = consume_registered_entry


def world_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the exact registered World snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == WORLD_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


__all__ = [
    "DisabledProductionEntry",
    "ENTRY_FIELDS",
    "REGISTRY_PATH",
    "RegisteredDispatchSnapshot",
    "WORLD_FLOW_ID",
    "WORLD_PRODUCT_ID",
    "WORLD_PRODUCT_REVISION",
    "WORLD_HANDLER_ID",
    "WORLD_SELECTION_HANDLER_ID",
    "WORLD_PROFILE_ID",
    "WORLD_PROFILE",
    "WORLD_PRODUCT",
    "WORLD_REVISION",
    "WORLD_PHASE_MODE",
    "consume_registered_entry",
    "consume_world_registration",
    "load_disabled_registry",
    "load_production_registry",
    "world_registration_snapshot",
]
