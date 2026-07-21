"""Deterministic loader/validator for gameplay flow contracts."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

CONTRACTS_DIR = Path(__file__).with_name("gameplay_flow_contracts")
SCHEMA_PATH = CONTRACTS_DIR / "schema.json"

_REQUIRED = (
    "schema_version",
    "flow_id",
    "product_purpose",
    "trigger_cadence_type",
    "reset_scope",
    "required_starting_context",
    "shared_primitive_dependencies",
    "recognized_states",
    "state_transitions",
    "permitted_inputs",
    "local_postconditions",
    "consequential_action_class",
    "cost_quantity_requirements",
    "completion_identity",
    "terminal_outcomes",
    "cooldown_deferred_behavior",
    "bounded_recovery_behavior",
    "evidence_requirements",
    "replay_fixture_requirements",
    "live_validation_scenarios",
    "unsupported_or_manual_only_states",
    "implementation_status",
    "proof_state",
)

_TERMINAL = frozenset(
    {
        "action_performed",
        "deferred",
        "complete_for_reset",
        "already_complete",
        "blocked",
        "manual_required",
    }
)
_CADENCE = frozenset(
    {
        "reset_pulse",
        "cooldown_pulse",
        "daily_once",
        "eligibility_pulse",
        "navigation_foundation",
        "evidence_gated",
    }
)
_START = frozenset(
    {
        "home_ready",
        "home_localized",
        "home_canonical",
        "world_map",
        "quest_screen",
        "unknown_requires_evidence",
    }
)
_IMPL = frozenset(
    {
        "contract_only",
        "shared_foundation",
        "reference_implemented",
        "live_validated",
        "scheduler_eligible",
    }
)
_PROOF = frozenset({"current", "regression_required", "evidence_required", "not_implemented"})
_FIXTURE_STATUS = frozenset({"available", "required_evidence", "synthetic_policy_ok"})
_LIVE_MODE = frozenset(
    {"navigation_only", "consequential_supervised", "observe_only", "blocked_until_policy"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FlowContractError(ValueError):
    """Raised when a gameplay flow contract fails deterministic validation."""


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_flow_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one contract without inventing missing gameplay behavior."""

    missing = [key for key in _REQUIRED if key not in payload]
    if missing:
        raise FlowContractError(f"missing required fields: {', '.join(missing)}")
    if payload.get("schema_version") != 1:
        raise FlowContractError("unsupported schema_version")
    flow_id = payload["flow_id"]
    if not isinstance(flow_id, str) or not flow_id.strip():
        raise FlowContractError("flow_id required")
    if payload["trigger_cadence_type"] not in _CADENCE:
        raise FlowContractError("invalid trigger_cadence_type")
    if not isinstance(payload["required_starting_context"], list) or not payload["required_starting_context"]:
        raise FlowContractError("required_starting_context must be a non-empty list")
    if any(item not in _START for item in payload["required_starting_context"]):
        raise FlowContractError("invalid required_starting_context entry")
    if not isinstance(payload["recognized_states"], list) or not payload["recognized_states"]:
        raise FlowContractError("recognized_states required")
    if not isinstance(payload["state_transitions"], list):
        raise FlowContractError("state_transitions must be a list")
    for transition in payload["state_transitions"]:
        if not isinstance(transition, Mapping) or not {"from", "to", "via"} <= set(transition):
            raise FlowContractError("state transition requires from/to/via")
    cost = payload["cost_quantity_requirements"]
    if not isinstance(cost, Mapping) or not {"free_only", "maximum_cost", "quantity"} <= set(cost):
        raise FlowContractError("cost_quantity_requirements incomplete")
    terminals = payload["terminal_outcomes"]
    if not isinstance(terminals, list) or not terminals or any(item not in _TERMINAL for item in terminals):
        raise FlowContractError("invalid terminal_outcomes")
    if payload["implementation_status"] not in _IMPL:
        raise FlowContractError("invalid implementation_status")
    if payload["proof_state"] not in _PROOF:
        raise FlowContractError("invalid proof_state")
    if not isinstance(payload["evidence_requirements"], list):
        raise FlowContractError("evidence_requirements must be a list")
    # Uncertain requirements must be explicit; empty is allowed only when implementation is reference+.
    if (
        payload["implementation_status"] == "contract_only"
        and not payload["evidence_requirements"]
        and payload["proof_state"] not in {"evidence_required", "not_implemented"}
    ):
        raise FlowContractError("contract_only flows require evidence_requirements or evidence proof_state")
    for fixture in payload["replay_fixture_requirements"]:
        if not isinstance(fixture, Mapping) or "fixture_id" not in fixture or fixture.get("status") not in _FIXTURE_STATUS:
            raise FlowContractError("invalid replay_fixture_requirements entry")
        if fixture["status"] == "available":
            if not fixture.get("path"):
                raise FlowContractError("available fixture requires path")
            if not _SHA256.fullmatch(str(fixture.get("sha256", ""))):
                raise FlowContractError("available fixture requires sha256")
        for evidence_ref in fixture.get("evidence_refs", ()):
            if (
                not isinstance(evidence_ref, Mapping)
                or not evidence_ref.get("path")
                or not evidence_ref.get("kind")
                or not _SHA256.fullmatch(str(evidence_ref.get("sha256", "")))
            ):
                raise FlowContractError("invalid replay fixture evidence_ref")
    for scenario in payload["live_validation_scenarios"]:
        if not isinstance(scenario, Mapping) or scenario.get("mode") not in _LIVE_MODE:
            raise FlowContractError("invalid live_validation_scenarios entry")
    # Reject accidental claims of live/scheduler completion for stubs.
    if payload["implementation_status"] in {"live_validated", "scheduler_eligible"} and payload["proof_state"] != "current":
        raise FlowContractError("live/scheduler status requires current proof_state")
    for key in ("offline_proof_state", "replay_fixture_proof_state", "supervised_live_proof_state"):
        if key in payload and payload[key] not in _PROOF:
            raise FlowContractError(f"invalid {key}")
    if "production_eligible" in payload and not isinstance(payload["production_eligible"], bool):
        raise FlowContractError("production_eligible must be boolean")
    return dict(payload)


def load_flow_contract(flow_id: str, *, directory: Path = CONTRACTS_DIR) -> dict[str, Any]:
    path = directory / f"{flow_id}.json"
    if not path.is_file():
        raise FlowContractError(f"missing contract: {flow_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("flow_id") != flow_id:
        raise FlowContractError("flow_id does not match filename")
    return validate_flow_contract(payload)


def list_flow_contract_ids(*, directory: Path = CONTRACTS_DIR) -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in directory.glob("*.json") if path.name != "schema.json"))


def load_all_flow_contracts(*, directory: Path = CONTRACTS_DIR) -> dict[str, dict[str, Any]]:
    return {flow_id: load_flow_contract(flow_id, directory=directory) for flow_id in list_flow_contract_ids(directory=directory)}


def mark_regression_required_for_dependency(
    contracts: Mapping[str, Mapping[str, Any]],
    *,
    primitive_id: str,
) -> dict[str, dict[str, Any]]:
    """Return copies with proof_state=regression_required for dependent flows."""

    updated: dict[str, dict[str, Any]] = {}
    for flow_id, contract in contracts.items():
        copy = dict(contract)
        deps = contract.get("shared_primitive_dependencies") or []
        if any(isinstance(dep, Mapping) and dep.get("primitive_id") == primitive_id for dep in deps):
            if copy.get("proof_state") == "current":
                copy["proof_state"] = "regression_required"
        updated[flow_id] = copy
    return updated
