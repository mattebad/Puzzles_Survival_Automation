#!/usr/bin/env python3
"""Checked-in PnS flow-delivery subagent routing policy loader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTING_POLICY_PATH = (
    REPO_ROOT / "tasks" / "flow_delivery_subagent_routing_policy.json"
)


class RoutingPolicyError(RuntimeError):
    """Raised when the checked-in routing policy cannot be loaded safely."""


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutingPolicyError(f"routing policy {field} must be a nonempty string")
    return value


def load_subagent_routing_policy(
    path: Path | None = None,
) -> dict[str, Any]:
    policy_path = path or DEFAULT_ROUTING_POLICY_PATH
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoutingPolicyError("subagent routing policy is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoutingPolicyError("subagent routing policy is unreadable") from exc
    if not isinstance(payload, dict):
        raise RoutingPolicyError("subagent routing policy must be an object")
    if payload.get("schema_version") != 1:
        raise RoutingPolicyError("unsupported subagent routing policy schema")
    if payload.get("policy_id") != "pns-flow-delivery-subagent-routing":
        raise RoutingPolicyError("unexpected subagent routing policy identity")
    approved_model = _require_nonempty_string(payload.get("approved_model"), "approved_model")
    prefix = _require_nonempty_string(
        payload.get("agent_namespace_prefix"),
        "agent_namespace_prefix",
    )
    stage_agents = payload.get("stage_agents")
    if not isinstance(stage_agents, dict) or not stage_agents:
        raise RoutingPolicyError("routing policy stage_agents must be a nonempty object")
    allowed_agents = payload.get("allowed_agents")
    if not isinstance(allowed_agents, list) or not allowed_agents:
        raise RoutingPolicyError("routing policy allowed_agents must be a nonempty list")
    for agent in allowed_agents:
        _require_nonempty_string(agent, "allowed_agents[]")
        if not str(agent).startswith(prefix):
            raise RoutingPolicyError("allowed agent escapes the project namespace")
    normalized_stages: dict[str, str] = {}
    for stage, agent in stage_agents.items():
        stage_name = _require_nonempty_string(stage, "stage_agents.key")
        agent_name = _require_nonempty_string(agent, f"stage_agents.{stage_name}")
        if agent_name not in allowed_agents:
            raise RoutingPolicyError("stage agent is not in allowed_agents")
        normalized_stages[stage_name] = agent_name
    denied_models = payload.get("denied_models") or []
    denied_builtin = payload.get("denied_builtin_agents") or []
    if not isinstance(denied_models, list) or not isinstance(denied_builtin, list):
        raise RoutingPolicyError("denied model/agent lists must be arrays")
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        raise RoutingPolicyError("routing policy execution block is required")
    for flag in ("ide_native_only", "foreground_required", "cursor_cli_forbidden"):
        if execution.get(flag) is not True:
            raise RoutingPolicyError(f"routing policy execution.{flag} must be true")
    return {
        "schema_version": 1,
        "policy_id": payload["policy_id"],
        "approved_model": approved_model,
        "agent_namespace_prefix": prefix,
        "stage_agents": normalized_stages,
        "allowed_agents": sorted(str(item) for item in allowed_agents),
        "denied_models": [str(item) for item in denied_models],
        "denied_builtin_agents": [str(item) for item in denied_builtin],
        "execution": {
            "ide_native_only": True,
            "foreground_required": True,
            "cursor_cli_forbidden": True,
        },
        "source_path": str(policy_path.as_posix()),
    }


def routing_policy_digest(policy: Mapping[str, Any] | None = None) -> str:
    payload = dict(policy or load_subagent_routing_policy())
    payload.pop("source_path", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
