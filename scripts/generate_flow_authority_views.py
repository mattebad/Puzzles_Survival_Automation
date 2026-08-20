#!/usr/bin/env python3
"""Generate and check deterministic projections of bound product authority."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.product_authority import (  # noqa: E402
    CONTRACT_BINDING_FIELD,
    DEFAULT_AUTHORITY_PATH,
    PRODUCT_RECORDS_FIELD,
    canonical_digest,
    load_product_authority,
    validate_contract_product_authority_bindings,
)


DEFAULT_CONTRACTS_DIR = REPO_ROOT / "tasks" / "gameplay_flow_contracts"
VIEW_SCHEMA_VERSION = 1
VIEW_KIND = "flow_delivery_product_authority_view"


class AuthorityViewError(ValueError):
    """Raised when a generated authority view is malformed or tampered."""


def _read_contracts(contracts_dir: Path) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == "schema.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorityViewError(f"cannot read contract: {path}") from exc
        flow_id = payload.get("flow_id", path.stem)
        if not isinstance(flow_id, str) or not flow_id.strip():
            raise AuthorityViewError(f"contract has no flow_id: {path}")
        if flow_id in contracts:
            raise AuthorityViewError(f"duplicate contract flow_id: {flow_id}")
        payload["_source_path"] = path
        contracts[flow_id] = payload
    return contracts


def _contract_digest(contract: Mapping[str, Any]) -> str:
    unsigned = dict(contract)
    unsigned.pop("_source_path", None)
    return canonical_digest(unsigned)


def _record_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project only product semantics, with a safe Supply Depot summary."""

    record_id = record["record_id"]
    if record_id == "supply_depot":
        # The native Free target is useful evidence, but this view must not
        # turn it into a collection or Daily 5/5 completion assertion.
        return {
            "record_id": record_id,
            "record_revision": record["record_revision"],
            "record_digest": record["record_digest"],
            "objective": record["objective"],
            "semantic_entry_route": deepcopy(record["semantic_entry_route"]),
            "target": {
                "kind": record["target"]["kind"],
                "free_control": record["target"]["free_control"],
            },
            "quantity_cost": deepcopy(record["quantity_cost"]),
            "semantic_effect": {
                "free_disappears_required": True,
                "daily_ownership": "none",
                "action_claim": False,
            },
            "forbidden_actions": [
                "paid control",
                "diamond control",
                "real-money confirmation",
            ],
            "terminal_requirement": deepcopy(record["terminal_requirement"]),
            "daily_ownership": {
                "daily_owner": None,
                "point_credit_trigger": None,
                "selected_daily_prerequisite": False,
                "notes": "No Daily attribution.",
            },
        }
    return {
        "record_id": record["record_id"],
        "record_revision": record["record_revision"],
        "record_digest": record["record_digest"],
        "record_type": record["record_type"],
        "purpose": record["purpose"],
        "recurrence": record["recurrence"],
        "semantic_entry_route": deepcopy(record["semantic_entry_route"]),
        "objective": record["objective"],
        "action": record["action"],
        "target": deepcopy(record["target"]),
        "quantity_cost": deepcopy(record["quantity_cost"]),
        **({"actions": deepcopy(record["actions"])} if "actions" in record else {}),
        "semantic_effect": deepcopy(record["semantic_effect"]),
        "forbidden_actions": deepcopy(record["forbidden_actions"]),
        "terminal_requirement": deepcopy(record["terminal_requirement"]),
        "daily_ownership": deepcopy(record["daily_ownership"]),
    }


def _contract_projection(
    contract: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    record_id = binding["product_record_id"]
    scenario = next(
        (
            item
            for item in contract.get("scenarios", [])
            if isinstance(item, Mapping)
        ),
        {},
    )
    permitted_inputs = list(scenario.get("permitted_inputs", []))
    if record_id == "supply_depot":
        # Never emit collection controls from the evidence-only contract.
        permitted_inputs = [
            item
            for item in permitted_inputs
            if "free" not in str(item).casefold()
            and "collect" not in str(item).casefold()
            and "hold" not in str(item).casefold()
        ]
    return {
        "flow_id": contract["flow_id"],
        "schema_version": contract.get("schema_version"),
        "contract_source_digest": _contract_digest(contract),
        "product_record_id": record_id,
        "product_authority_binding": deepcopy(dict(binding)),
        "home_authority": binding["home_authority"],
        "terminal_home_authority": binding["terminal_home_authority"],
        "scenario_mode": scenario.get("mode"),
        "permitted_inputs": permitted_inputs,
        "required_transitions": list(scenario.get("required_transitions", [])),
        "evidence_requirements": list(contract.get("evidence_requirements", [])),
    }


def build_authority_view(
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
) -> dict[str, Any]:
    """Build the same JSON projection for every invocation."""

    authority = load_product_authority(authority_path)
    contracts = _read_contracts(contracts_dir)
    validate_contract_product_authority_bindings(authority, contracts)
    record_by_id = {
        record["record_id"]: record
        for record in authority[PRODUCT_RECORDS_FIELD]
    }
    bound = []
    for flow_id in sorted(contracts):
        contract = contracts[flow_id]
        binding = contract.get(CONTRACT_BINDING_FIELD)
        if not isinstance(binding, Mapping):
            continue
        record_id = binding["product_record_id"]
        bound.append(
            {
                "flow_id": flow_id,
                "record": _record_projection(record_by_id[record_id]),
                "contract": _contract_projection(contract, binding),
            }
        )
    source_digests = {
        "authority": authority["authority_digest"],
        "records": {
            record_id: record_by_id[record_id]["record_digest"]
            for record_id in sorted(record_by_id)
        },
        "contracts": {
            item["flow_id"]: item["contract"]["contract_source_digest"]
            for item in bound
        },
    }
    unsigned = {
        "schema_version": VIEW_SCHEMA_VERSION,
        "view_kind": VIEW_KIND,
        "authority_revision": authority["authority_revision"],
        "source_digests": source_digests,
        "bound_flows": bound,
    }
    return {
        **unsigned,
        "view_digest": canonical_digest(unsigned),
    }


def render_authority_view(view: Mapping[str, Any]) -> str:
    """Render a view with a validated self-excluded digest."""

    unsigned = dict(view)
    declared = unsigned.pop("view_digest", None)
    expected = canonical_digest(unsigned)
    if declared != expected:
        raise AuthorityViewError("view_digest does not match deterministic projection")
    return json.dumps(view, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_authority_view(
    output_path: Path,
    *,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
) -> None:
    view = build_authority_view(authority_path, contracts_dir)
    rendered = render_authority_view(view)
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)


def check_authority_view(
    output_path: Path,
    *,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
) -> None:
    expected = render_authority_view(build_authority_view(authority_path, contracts_dir))
    try:
        actual = output_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthorityViewError(f"generated authority view is missing: {output_path}") from exc
    if actual != expected:
        raise AuthorityViewError("generated authority view is stale or hand-edited")


generate_view = build_authority_view
generate_authority_view = build_authority_view
check_view = check_authority_view


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=DEFAULT_AUTHORITY_PATH)
    parser.add_argument("--contracts-dir", type=Path, default=DEFAULT_CONTRACTS_DIR)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check:
            check_authority_view(
                args.output,
                authority_path=args.authority,
                contracts_dir=args.contracts_dir,
            )
        else:
            write_authority_view(
                args.output,
                authority_path=args.authority,
                contracts_dir=args.contracts_dir,
            )
    except (AuthorityViewError, OSError, ValueError) as exc:
        print(f"authority view invalid: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
