"""Durable Daily Quest objective catalog.

The catalog is declarative production knowledge.  Runtime text may match an alias, but it may
not create a new objective or change a consequence class.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


CATALOG_PATH = Path(__file__).with_name("daily_quest_catalog.json")
PROVENANCE_AUDIT_PATH = CATALOG_PATH.with_name("daily_quest_provenance_audit.json")
VALID_STATES = {
    "CATALOGED",
    "ROUTE_KNOWN",
    "OFFLINE_TESTED",
    "LIVE_VALIDATED",
    "AUTOMATIC_ENABLED",
    "DISABLED_POLICY",
}


@dataclass(frozen=True)
class ObjectiveSpec:
    objective_key: str
    aliases: tuple[str, ...]
    handler_family: str
    route_name: str
    consequence_class: str
    policy_mode: str
    implementation_status: str
    live_validation_status: str
    progress_format: str
    claim_support: str
    next_development_priority: int
    evidence_provenance: str
    observed_variant: str
    completion_quantity: int
    identity_provenance: tuple[str, ...]
    quantity_provenance: tuple[str, ...]

    def matches(self, text: str) -> bool:
        normalized = " ".join(text.casefold().split())
        return any(normalized == " ".join(alias.casefold().split()) for alias in self.aliases)


def _load_raw(path: Path = CATALOG_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_catalog(path: Path = CATALOG_PATH) -> tuple[ObjectiveSpec, ...]:
    raw = _load_raw(path)
    if raw.get("catalog_version") != 3:
        raise ValueError("unsupported Daily Quest catalog version")
    admission = raw.get("admission_rule")
    if not isinstance(admission, dict) or not all(
        admission.get(field) is True
        for field in (
            "requires_selected_daily_provenance",
            "requires_accepted_evidence_source",
            "requires_objective_list_region",
            "requires_non_main_classification",
        )
    ):
        raise ValueError("Daily Quest catalog admission rule is incomplete")
    audit_path = path.with_name(PROVENANCE_AUDIT_PATH.name)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_admission = audit.get("admission_rule")
    accepted_source_types = set(
        audit_admission.get("accepted_source_types", ())
        if isinstance(audit_admission, dict)
        else ()
    )
    inventory_proof = audit.get("proven_daily_inventory", {})
    inventory_path = inventory_proof.get("inventory_path")
    if (
        inventory_proof.get("classification") != "PROVEN_DAILY_OBJECTIVE"
        or inventory_proof.get("source_type") not in accepted_source_types
        or inventory_proof.get("quest_screen_positive") is not True
        or inventory_proof.get("daily_tab_positive") is not True
        or inventory_proof.get("main_negative") is not True
        or inventory_proof.get("non_main_classification") != "NON_MAIN"
        or not inventory_proof.get("objective_list_region")
        or not isinstance(inventory_proof.get("raw_frame_paths"), list)
        or not inventory_proof["raw_frame_paths"]
        or not isinstance(inventory_path, str)
    ):
        raise ValueError("selected-Daily provenance proof is incomplete")
    rows = raw.get("objectives")
    metadata = raw.get("observation_metadata")
    authority = raw.get("authority")
    source_inventories = raw.get("source_inventories")
    reconciliation = raw.get("reconciliation_records")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Daily Quest catalog must contain reconciled objectives")
    if (
        not isinstance(metadata, dict)
        or not isinstance(authority, dict)
        or not isinstance(source_inventories, list)
        or inventory_path not in source_inventories
        or not isinstance(reconciliation, list)
    ):
        raise ValueError("catalog authority and observation metadata are required")
    if authority.get("legacy_status_fields_are_non_authoritative") is not True:
        raise ValueError("catalog legacy status marker is required")
    inventory_file_name = Path(inventory_path).name
    inventory_path_on_disk = path.parents[1] / inventory_path
    try:
        inventory = json.loads(inventory_path_on_disk.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("selected-Daily inventory provenance is unreadable") from exc
    inventory_names = {
        row.get("name")
        for row in inventory.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    reconciliation_by_key = {
        record.get("objective_key"): record
        for record in reconciliation
        if isinstance(record, dict)
    }
    result = []
    keys = set()
    for row in rows:
        required = {
            "objective_key", "aliases", "handler_family", "route_name", "consequence_class",
            "policy_mode", "implementation_status", "live_validation_status", "progress_format",
            "claim_support", "next_development_priority", "evidence_provenance",
        }
        if not required.issubset(row):
            raise ValueError("catalog row is missing required metadata")
        if inventory_file_name not in str(row["evidence_provenance"]):
            raise ValueError("catalog row lacks accepted selected-Daily provenance")
        if row["objective_key"] in keys:
            raise ValueError("catalog objective keys must be unique")
        if row["implementation_status"] not in VALID_STATES:
            raise ValueError("catalog row has an invalid implementation status")
        if not row["aliases"] or not all(isinstance(alias, str) and alias.strip() for alias in row["aliases"]):
            raise ValueError("catalog row requires text aliases")
        row_metadata = metadata.get(row["objective_key"])
        if not isinstance(row_metadata, dict):
            raise ValueError("catalog objective lacks observation metadata")
        if int(row_metadata.get("completion_quantity", 0)) < 1:
            raise ValueError("catalog objective requires a positive completion quantity")
        if not row_metadata.get("identity_provenance") or not row_metadata.get("quantity_provenance"):
            raise ValueError("catalog objective requires separate identity and quantity provenance")
        if not all(
            inventory_file_name in str(source)
            for source in (
                *row_metadata["identity_provenance"],
                *row_metadata["quantity_provenance"],
            )
        ):
            raise ValueError("catalog objective provenance is not tied to selected-Daily inventory")
        reconciliation_row = reconciliation_by_key.get(row["objective_key"])
        if (
            not isinstance(reconciliation_row, dict)
            or reconciliation_row.get("classification") != "exact_existing_key"
            or inventory_file_name not in {
                Path(str(source)).name
                for source in reconciliation_row.get("source_refs", ())
            }
            or reconciliation_row.get("observed_name") not in inventory_names
        ):
            raise ValueError("catalog objective lacks exact selected-Daily row provenance")
        keys.add(row["objective_key"])
        values = {key: row[key] for key in required}
        values["aliases"] = tuple(values["aliases"])
        values["observed_variant"] = str(row_metadata["observed_variant"])
        values["completion_quantity"] = int(row_metadata["completion_quantity"])
        values["identity_provenance"] = tuple(str(item) for item in row_metadata["identity_provenance"])
        values["quantity_provenance"] = tuple(str(item) for item in row_metadata["quantity_provenance"])
        result.append(ObjectiveSpec(**values))
    if set(metadata) != keys:
        raise ValueError("catalog observation metadata keys must equal objective keys")
    return tuple(result)


def objective_for_text(text: str, catalog: Iterable[ObjectiveSpec] | None = None) -> Optional[ObjectiveSpec]:
    return next((item for item in (catalog or load_catalog()) if item.matches(text)), None)


def catalog_summary(path: Path = CATALOG_PATH) -> Dict[str, Any]:
    items = load_catalog(path)
    return {
        "catalog_path": str(path),
        "count": len(items),
        "implementation_status": {
            status: sum(item.implementation_status == status for item in items)
            for status in sorted(VALID_STATES)
        },
        "priority_order": [item.objective_key for item in sorted(items, key=lambda item: item.next_development_priority)],
    }
