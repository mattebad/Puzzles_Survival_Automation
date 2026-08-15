"""Read-only validation for the minimal disabled production registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "tasks"
    / "flow_delivery_disabled_production_registry.json"
)
ENTRY_FIELDS = frozenset(
    {
        "production_handler",
        "profile",
        "supported_profiles",
        "mode",
        "registration_status",
        "scheduler_eligible",
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


def load_disabled_registry(path: Path = REGISTRY_PATH) -> tuple[DisabledProductionEntry, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("registry_kind") != "disabled_production_handlers":
        raise ValueError("unsupported disabled production registry")
    flows = payload.get("flows")
    if not isinstance(flows, Mapping) or not flows:
        raise ValueError("disabled production registry requires flows")
    entries: list[DisabledProductionEntry] = []
    for flow_id, value in flows.items():
        if not isinstance(flow_id, str) or not isinstance(value, Mapping):
            raise ValueError("invalid disabled production registry entry")
        if set(value) != ENTRY_FIELDS:
            raise ValueError("registry entry owns only handler/profile/mode/registration/scheduler fields")
        entry = DisabledProductionEntry(
            flow_id=flow_id,
            production_handler=value["production_handler"],
            profile=value["profile"],
            supported_profiles=tuple(value["supported_profiles"]),
            mode=str(value["mode"]),
            registration_status=str(value["registration_status"]),
            scheduler_eligible=value["scheduler_eligible"],
        )
        if entry.production_handler is not None and (
            not isinstance(entry.production_handler, str) or not entry.production_handler.strip()
        ):
            raise ValueError("production handler must be unavailable or non-empty")
        if entry.profile is not None and (
            not isinstance(entry.profile, str) or not entry.profile.strip()
        ):
            raise ValueError("profile must be unavailable or non-empty")
        if type(value["supported_profiles"]) is not list or any(
            not isinstance(profile, str) or not profile.strip()
            for profile in value["supported_profiles"]
        ):
            raise ValueError("supported_profiles must be a list of non-empty strings")
        if (
            entry.mode != "disabled"
            or entry.registration_status != "NOT_REGISTERED"
            or entry.scheduler_eligible is not False
        ):
            raise ValueError("all production registry entries must remain disabled")
        entries.append(entry)
    return tuple(sorted(entries, key=lambda item: item.flow_id))

