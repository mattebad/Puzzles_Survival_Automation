"""Legacy production-registration records retained for compatibility.

Canonical scheduler admission is persisted in ``BotStateManager``.  The
consume-once helpers below remain available only to not-yet-migrated routes;
they are never consulted by the new scheduler/service path.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from .contracts import FlowDescriptor, FlowSpec, RecurrenceClass, RecurrenceProjection


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
NOVA_FLOW_ID = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
NOVA_PRODUCT_ID = "nova_praise"
NOVA_PRODUCT_REVISION = "nova_praise-v1"
NOVA_HANDLER_ID = "nova_praise_selection_handler"
NOVA_PROFILE_ID = WORLD_PROFILE_ID
NOVA_PHASE_MODE = "phase_canary"
# Explicit aliases keep the fixed binding easy to consume without introducing
# a second registration vocabulary.
NOVA_SELECTION_HANDLER_ID = NOVA_HANDLER_ID
NOVA_PROFILE = NOVA_PROFILE_ID
NOVA_PRODUCT = NOVA_PRODUCT_ID
NOVA_REVISION = NOVA_PRODUCT_REVISION
RECRUITMENT_FLOW_ID = "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"
RECRUITMENT_PRODUCT_ID = "noahs_tavern_recruitment"
RECRUITMENT_PRODUCT_REVISION = "noahs_tavern_recruitment-v1"
RECRUITMENT_HANDLER_ID = "recruitment_maintenance_selection_handler"
RECRUITMENT_PROFILE_ID = WORLD_PROFILE_ID
RECRUITMENT_PHASE_MODE = "phase_canary"
RECRUITMENT_SELECTION_HANDLER_ID = RECRUITMENT_HANDLER_ID
RECRUITMENT_PROFILE = RECRUITMENT_PROFILE_ID
RECRUITMENT_PRODUCT = RECRUITMENT_PRODUCT_ID
RECRUITMENT_REVISION = RECRUITMENT_PRODUCT_REVISION
CAMPAIGN_FLOW_ID = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
CAMPAIGN_PRODUCT_ID = "campaign_ap"
CAMPAIGN_PRODUCT_REVISION = "campaign_ap-v1"
CAMPAIGN_HANDLER_ID = "campaign_ap_selection_handler"
CAMPAIGN_PROFILE_ID = WORLD_PROFILE_ID
CAMPAIGN_PHASE_MODE = "phase_canary"
CAMPAIGN_SELECTION_HANDLER_ID = CAMPAIGN_HANDLER_ID
CAMPAIGN_PROFILE = CAMPAIGN_PROFILE_ID
CAMPAIGN_PRODUCT = CAMPAIGN_PRODUCT_ID
CAMPAIGN_REVISION = CAMPAIGN_PRODUCT_REVISION


_FIXED_BINDINGS = {
    WORLD_FLOW_ID: {
        "flow_id": WORLD_FLOW_ID,
        "product_id": WORLD_PRODUCT_ID,
        "product_revision": WORLD_PRODUCT_REVISION,
        "production_handler": WORLD_HANDLER_ID,
        "profile": WORLD_PROFILE_ID,
        "mode": WORLD_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    NOVA_FLOW_ID: {
        "flow_id": NOVA_FLOW_ID,
        "product_id": NOVA_PRODUCT_ID,
        "product_revision": NOVA_PRODUCT_REVISION,
        "production_handler": NOVA_HANDLER_ID,
        "profile": NOVA_PROFILE_ID,
        "mode": NOVA_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    RECRUITMENT_FLOW_ID: {
        "flow_id": RECRUITMENT_FLOW_ID,
        "product_id": RECRUITMENT_PRODUCT_ID,
        "product_revision": RECRUITMENT_PRODUCT_REVISION,
        "production_handler": RECRUITMENT_HANDLER_ID,
        "profile": RECRUITMENT_PROFILE_ID,
        "mode": RECRUITMENT_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    CAMPAIGN_FLOW_ID: {
        "flow_id": CAMPAIGN_FLOW_ID,
        "product_id": CAMPAIGN_PRODUCT_ID,
        "product_revision": CAMPAIGN_PRODUCT_REVISION,
        "production_handler": CAMPAIGN_HANDLER_ID,
        "profile": CAMPAIGN_PROFILE_ID,
        "mode": CAMPAIGN_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
}

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
    """Immutable dispatch-time copy of one accepted fixed registration."""

    flow_id: str
    product_id: str
    product_revision: str
    production_handler: str
    profile: str
    mode: str
    registration_status: str
    scheduler_eligible: bool

    def __post_init__(self) -> None:
        expected = _FIXED_BINDINGS.get(self.flow_id)
        actual = self.to_mapping()
        if (
            expected is None
            or actual != expected
            or type(self.scheduler_eligible) is not bool
        ):
            raise ValueError(
                "dispatch registration snapshot is not a fixed phase binding"
            )

    @classmethod
    def from_entry(cls, entry: DisabledProductionEntry) -> "RegisteredDispatchSnapshot":
        if not _entry_is_registered(entry):
            raise ValueError("only an exact registered phase entry can be dispatched")
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

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RegisteredDispatchSnapshot":
        """Rehydrate and strictly validate retained dispatch evidence."""

        fields = {
            "flow_id",
            "product_id",
            "product_revision",
            "production_handler",
            "profile",
            "mode",
            "registration_status",
            "scheduler_eligible",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("dispatch registration snapshot is incomplete")
        return cls(
            flow_id=value["flow_id"],
            product_id=value["product_id"],
            product_revision=value["product_revision"],
            production_handler=value["production_handler"],
            profile=value["profile"],
            mode=value["mode"],
            registration_status=value["registration_status"],
            scheduler_eligible=value["scheduler_eligible"],
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


@dataclass(frozen=True)
class CanonicalFlowRegistration:
    """Static, typed composition facts for a canonical service flow.

    This registry is code-owned and intentionally independent of the legacy
    disabled-production JSON and the BlueStacks runner registry.  It describes
    which offline handler is available; mutable enablement remains exclusively
    in ``BotStateManager``.
    """

    spec: FlowSpec
    descriptor: FlowDescriptor
    registration: RegisteredDispatchSnapshot
    handler_id: str

    @property
    def flow_id(self) -> str:
        return self.spec.flow_id

    @property
    def registered(self) -> bool:
        return self.descriptor.registration_status == "REGISTERED"

    @property
    def registration_status(self) -> str:
        return self.descriptor.registration_status

    @property
    def scheduler_eligible(self) -> bool:
        return self.descriptor.scheduler_eligible

    @property
    def product_id(self) -> str:
        return self.registration.product_id

    @property
    def product_revision(self) -> str:
        return self.registration.product_revision

    @property
    def production_handler(self) -> str:
        return self.handler_id

    @property
    def profile(self) -> str:
        return self.registration.profile

    @property
    def mode(self) -> str:
        return self.registration.mode

    @property
    def supported_profiles(self) -> tuple[str, ...]:
        return (self.profile,)

    def build_handler(self) -> Any:
        """Instantiate the fixed handler without importing handlers at module load."""

        from .handlers import (
            CampaignApSelectionHandler,
            NovaPraiseSelectionHandler,
            RecruitmentMaintenanceSelectionHandler,
            WorldNavigationSelectionHandler,
        )

        handler_types = {
            CAMPAIGN_FLOW_ID: CampaignApSelectionHandler,
            NOVA_FLOW_ID: NovaPraiseSelectionHandler,
            RECRUITMENT_FLOW_ID: RecruitmentMaintenanceSelectionHandler,
            WORLD_FLOW_ID: WorldNavigationSelectionHandler,
        }
        handler_type = handler_types.get(self.flow_id)
        if handler_type is None:
            raise ValueError(f"no canonical handler for flow: {self.flow_id}")
        return handler_type(self.registration)


def _canonical_registration(
    flow_id: str,
    *,
    family: str,
    variant: str,
    cadence: str,
    reset_scoped: bool = True,
    recurrence: RecurrenceProjection | None = None,
) -> CanonicalFlowRegistration:
    binding = _FIXED_BINDINGS[flow_id]
    snapshot = RegisteredDispatchSnapshot(
        flow_id=flow_id,
        product_id=binding["product_id"],
        product_revision=binding["product_revision"],
        production_handler=binding["production_handler"],
        profile=binding["profile"],
        mode=binding["mode"],
        registration_status="REGISTERED",
        scheduler_eligible=True,
    )
    descriptor = FlowDescriptor(
        flow_id=flow_id,
        owner="automation_service",
        family=family,
        variant=variant,
        cadence=cadence,
        priority=1,
        reset_scoped=reset_scoped,
        scheduler_eligible=True,
        accepted_product=binding["product_id"],
        product_revision=binding["product_revision"],
        registration_status="REGISTERED",
        recurrence=recurrence,
    )
    return CanonicalFlowRegistration(
        spec=FlowSpec(
            flow_id=flow_id,
            default_enabled=False,
            priority=descriptor.priority,
            cadence=cadence,
        ),
        descriptor=descriptor,
        registration=snapshot,
        handler_id=binding["production_handler"],
    )


# The tuple is immutable and deterministic.  Do not derive it from a file,
# environment, queue, or runner registration.
CANONICAL_FLOW_REGISTRY: tuple[CanonicalFlowRegistration, ...] = (
    _canonical_registration(
        WORLD_FLOW_ID,
        family="world_map_navigation",
        variant="navigation_only",
        cadence="daily_once_per_reset",
    ),
    _canonical_registration(
        NOVA_FLOW_ID,
        family="nova_praise",
        variant="supervised_one_free_pulse",
        cadence="daily_once_per_reset",
    ),
    _canonical_registration(
        RECRUITMENT_FLOW_ID,
        family="recruitment",
        variant="free_attempt_maintenance",
        cadence="cooldown_pulse",
        reset_scoped=False,
    ),
    _canonical_registration(
        CAMPAIGN_FLOW_ID,
        family="campaign_ap",
        variant="one_auto_battle",
        cadence="ap_regeneration_pulse",
        reset_scoped=False,
        recurrence=RecurrenceProjection(
            RecurrenceClass.AP_REGENERATION,
            observed_at_utc=0.0,
            observed_balance=0.0,
        ),
    ),
)


def load_canonical_registry() -> tuple[CanonicalFlowRegistration, ...]:
    """Return static canonical flow composition facts.

    A function keeps call sites symmetrical with the retired registry loader,
    while returning the immutable code-owned tuple rather than reading disk.
    """

    return CANONICAL_FLOW_REGISTRY


canonical_registry = load_canonical_registry


def canonical_flow_specs() -> tuple[FlowSpec, ...]:
    """Return disabled-by-default static specs for SQLite initialization."""

    return tuple(entry.spec for entry in CANONICAL_FLOW_REGISTRY)


def canonical_descriptors() -> tuple[FlowDescriptor, ...]:
    """Return canonical descriptors without consulting any external registry."""

    return tuple(entry.descriptor for entry in CANONICAL_FLOW_REGISTRY)


def build_canonical_handler(flow_id: str) -> Any:
    """Build one fixed canonical handler by flow identity."""

    entry = next(
        (item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == flow_id),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown canonical flow: {flow_id}")
    return entry.build_handler()


_REGISTRY_LOCK = threading.RLock()


def _entry_is_registered(entry: DisabledProductionEntry) -> bool:
    expected = _FIXED_BINDINGS.get(entry.flow_id)
    return bool(
        expected is not None
        and entry.production_handler == expected["production_handler"]
        and entry.profile == expected["profile"]
        and entry.supported_profiles == (expected["profile"],)
        and entry.product_id == expected["product_id"]
        and entry.product_revision == expected["product_revision"]
        and entry.mode == expected["mode"]
        and entry.registration_status == expected["registration_status"]
        and entry.scheduler_eligible is expected["scheduler_eligible"]
    )


def _entry_is_world_registered(entry: DisabledProductionEntry) -> bool:
    return entry.flow_id == WORLD_FLOW_ID and _entry_is_registered(entry)


def _entry_is_nova_registered(entry: DisabledProductionEntry) -> bool:
    return entry.flow_id == NOVA_FLOW_ID and _entry_is_registered(entry)


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
            if not _entry_is_registered(entry):
                raise ValueError(
                    "only an exact fixed phase-canary registration is allowed"
                )
        elif not _entry_is_disabled(entry):
            raise ValueError("all non-registered entries must remain fully disabled")
        entries.append(entry)

    registered = [entry for entry in entries if entry.registered]
    if len(registered) > 1:
        raise ValueError("production registry permits at most one registered flow")
    if registered and not _entry_is_registered(registered[0]):
        raise ValueError("registered production entry is not a fixed phase binding")
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
    """Legacy-only atomic snapshot consumption for unmigrated routes."""

    registry_path = Path(REGISTRY_PATH if path is None else path)
    if flow_id not in _FIXED_BINDINGS:
        return None
    with _REGISTRY_LOCK, _registry_file_lock(registry_path):
        payload = dict(_load_payload(registry_path))
        entries = _parse_entries(payload)
        entry = next((item for item in entries if item.flow_id == flow_id), None)
        if entry is None or not _entry_is_registered(entry):
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


def consume_nova_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Nova entry."""

    return consume_registered_entry(NOVA_FLOW_ID, path=path)


def consume_recruitment_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Recruitment maintenance entry."""

    return consume_registered_entry(RECRUITMENT_FLOW_ID, path=path)

def consume_campaign_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Campaign AP entry."""

    return consume_registered_entry(CAMPAIGN_FLOW_ID, path=path)


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


def nova_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the exact registered Nova snapshot without consuming it."""

    entry = next(
        (item for item in load_disabled_registry(path) if item.flow_id == NOVA_FLOW_ID),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


def recruitment_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the registered Recruitment snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == RECRUITMENT_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )

def campaign_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the registered Campaign AP snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == CAMPAIGN_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


__all__ = [
    "CanonicalFlowRegistration",
    "CANONICAL_FLOW_REGISTRY",
    "canonical_descriptors",
    "canonical_flow_specs",
    "canonical_registry",
    "build_canonical_handler",
    "load_canonical_registry",
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
    "NOVA_FLOW_ID",
    "NOVA_PRODUCT_ID",
    "NOVA_PRODUCT_REVISION",
    "NOVA_HANDLER_ID",
    "NOVA_SELECTION_HANDLER_ID",
    "NOVA_PROFILE_ID",
    "NOVA_PROFILE",
    "NOVA_PRODUCT",
    "NOVA_REVISION",
    "NOVA_PHASE_MODE",
    "RECRUITMENT_FLOW_ID",
    "RECRUITMENT_PRODUCT_ID",
    "RECRUITMENT_PRODUCT_REVISION",
    "RECRUITMENT_HANDLER_ID",
    "RECRUITMENT_SELECTION_HANDLER_ID",
    "RECRUITMENT_PROFILE_ID",
    "RECRUITMENT_PROFILE",
    "RECRUITMENT_PRODUCT",
    "RECRUITMENT_REVISION",
    "RECRUITMENT_PHASE_MODE",
    "CAMPAIGN_FLOW_ID",
    "CAMPAIGN_PRODUCT_ID",
    "CAMPAIGN_PRODUCT_REVISION",
    "CAMPAIGN_HANDLER_ID",
    "CAMPAIGN_SELECTION_HANDLER_ID",
    "CAMPAIGN_PROFILE_ID",
    "CAMPAIGN_PROFILE",
    "CAMPAIGN_PRODUCT",
    "CAMPAIGN_REVISION",
    "CAMPAIGN_PHASE_MODE",
    "consume_registered_entry",
    "consume_world_registration",
    "consume_nova_registration",
    "consume_recruitment_registration",
    "consume_campaign_registration",
    "load_disabled_registry",
    "load_production_registry",
    "nova_registration_snapshot",
    "recruitment_registration_snapshot",
    "campaign_registration_snapshot",
    "world_registration_snapshot",
]
