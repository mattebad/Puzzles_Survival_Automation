#!/usr/bin/env python3
"""Validate durable governance state without touching runtime or evidence."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
HANDOFF_PATH = ROOT / "CURRENT_HANDOFF.md"
BACKLOG_PATH = ROOT / "BACKLOG.md"
MANIFEST_PATH = ROOT / "evidence" / "current-evidence-manifest.json"
INDEXING_IGNORE_PATH = ROOT / ".cursorindexingignore"

CURRENT_TASK_STATES = {
    "pending",
    "in_progress",
    "blocked",
    "completed",
    "completed_offline",
}
NEXT_TASK_ACTIVATION_STATES = {
    "awaiting_explicit_activation",
    "dependency_blocked",
    "not_applicable",
    "ready",
}
MANIFEST_STATUSES = {
    "PRESENT_VERIFIED",
    "PRESENT_HASH_MISMATCH",
    "MISSING",
    "NOT_LOCATED",
    "UNKNOWN",
    "NOT_VERIFIED_THIS_RUN",
    "NOT_APPLICABLE",
}



HANDOFF_SCHEMA_VERSION = 3
HANDOFF_STRUCTURED_MAX_BYTES = 15000
HANDOFF_TOTAL_MAX_BYTES = 30000

HANDOFF_REQUIRED_KEYS = {
    "schema_version",
    "branch",
    "head_binding",
    "last_product_candidate_head",
    "ahead_behind",
    "attributable_dirty_paths",
    "task_start_worktree",
    "protected_user_owned_paths",
    "current_task_id",
    "current_task_state",
    "next_task_id",
    "next_task_activation_status",
    "active_task_or_flow",
    "active_delivery_stage",
    "active_execution_manifest_path",
    "development_lease_state",
    "runtime_ownership_state",
    "writable_agent_state",
    "unresolved_action_state",
    "latest_focused_validation_result",
    "latest_architecture_validation_result",
    "latest_full_suite_result",
    "current_live_attempt_state",
    "current_evidence_or_session_reference",
    "last_safe_completed_step",
    "exact_next_permitted_action",
    "current_blocker",
    "prohibited_repeated_action",
    "stage_revision",
    "stage_type",
    "product_precondition",
    "failure_class",
    "budgets",
    "registration_and_scheduler",
    "journals_and_lease",
    "evidence",
    "control_owner",
    "control_parent_conversation_id",
    "deferred_independent_review",
    "stage_7_ordered_plan",
    "next_three_atomic_tasks",
}

HANDOFF_FORBIDDEN_KEYS = {
    "actions_already_performed",
    "actions_not_to_repeat",
    "collector",
    "game_day",
    "runtime",
    "tests",
    "next_action",
    "phase",
    "objective",
    "next_permitted_action",
    "repository",
}

HANDOFF_NESTED_KEYS = {
    "ahead_behind": {
        "source",
    },
    "task_start_worktree": {
        "tracked_dirty_paths",
        "protected_untracked_paths",
    },
    "budgets": {
        "stage_revisions_used",
        "managed_turns_used",
        "live_attempts_used",
        "runtime_inputs_used",
    },
    "registration_and_scheduler": {
        "production_registration",
        "scheduler_enabled",
        "active_runtime",
    },
    "journals_and_lease": {
        "development_lease_status",
        "active_prepared_input_sent_unresolved_action_ids",
        "historical_journals",
    },
    "evidence": {
        "evidence_requirement",
        "monitoring_issue",
        "do_not_recursively_inspect_parent_evidence_tree",
    },
}

TASK_REQUIRED_LABELS = (
    "Task ID",
    "Title",
    "Status",
    "Milestone",
    "Dependencies",
    "Blocked by",
    "Objective",
    "Established facts",
    "Direct implementation files",
    "Shared dependencies",
    "Transitive regression set",
    "Allowed changes",
    "Prohibited changes",
    "Authorized runtime action",
    "Maximum transport inputs",
    "Navigation-only recovery",
    "Consequential action",
    "Registration changes",
    "Scheduler changes",
    "Actions that must not be repeated",
    "Required source",
    "Exact target semantics",
    "Required local association",
    "Negative controls",
    "Coordinate space",
    "Accepted signals",
    "Rejected weak signals",
    "Ambiguous-result behavior",
    "Zero-cost requirement",
    "Quantity limits",
    "Resource consumption policy",
    "Premium or strategic restrictions",
    "Active evidence manifest",
    "Required artifacts",
    "Immediate-before/immediate-post/result/journal",
    "Additional task-specific artifacts",
    "Focused tests",
    "Integration tests",
    "Transitive regression tests",
    "Full-suite requirement",
    "Validators",
    "Known baseline failures",
    "Evidence requirement",
    "Valid blocked outcomes",
    "Blocked-result commit policy",
    "Commit policy",
    "Expected focused commits",
    "Completion criteria",
)

REQUIRED_INDEXING_PATTERNS = {
    "evidence/**/*.png",
    "evidence/**/*.jpg",
    "evidence/**/*.jpeg",
    "evidence/**/*.webp",
    "evidence/**/*.sqlite",
    "evidence/**/*.sqlite3",
    "evidence/**/*.db",
    "evidence/**/raw/**",
    "evidence/**/duplicate-frame*/",
    "evidence/**/duplicates/**",
    "evidence/**/transfer/**",
    "evidence/**/remote-cache/**",
    "evidence/**/*.zip",
    "evidence/**/*.zip.*",
    "evidence/**/*transcript*.md",
    ".local-captures/**",
    ".specstory/**",
    "." + "local-reference/**",
    ".local-orchestrator/**",
    ".vscode/**",
    ".pytest_cache/**",
    "**/__pycache__/**",
    "artifacts/evidence-audit*.json",
    "artifacts/evidence-audit*.md",
    "autonomous_iteration_prompt.md",
    "/Puzzle_Survival_Runtime_POC*.zip",
    "/*.7z",
    "evidence/**/*.jsonl",
    "evidence/**/*.mp4",
    "evidence/**/*.mov",
    "evidence/**/*.avi",
    "evidence/**/*.log",
    "evidence/**/*.sqlite3-wal",
    "evidence/**/*.sqlite3-shm",
    "evidence/**/sessions/*/",
}


class GovernanceValidationError(ValueError):
    """Raised for deterministic governance contract violations."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_handoff(path: Path = HANDOFF_PATH) -> Dict[str, Any]:
    text = _read(path)
    begin = "<!-- CURRENT_HANDOFF_STATE_BEGIN -->"
    end = "<!-- CURRENT_HANDOFF_STATE_END -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise GovernanceValidationError("handoff must contain one structured state block")
    raw = text.split(begin, 1)[1].split(end, 1)[0].strip()
    raw_bytes = raw.encode("utf-8")
    total_bytes = text.encode("utf-8")
    if len(raw_bytes) > HANDOFF_STRUCTURED_MAX_BYTES:
        raise GovernanceValidationError(
            f"handoff structured state exceeds {HANDOFF_STRUCTURED_MAX_BYTES} UTF-8 bytes"
        )
    if len(total_bytes) > HANDOFF_TOTAL_MAX_BYTES:
        raise GovernanceValidationError(
            f"handoff total size exceeds {HANDOFF_TOTAL_MAX_BYTES} UTF-8 bytes"
        )
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GovernanceValidationError(f"handoff state is not valid JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise GovernanceValidationError("handoff state must be a JSON object")
    if state.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise GovernanceValidationError(
            f"handoff schema_version must be {HANDOFF_SCHEMA_VERSION}"
        )
    missing = HANDOFF_REQUIRED_KEYS - set(state)
    if missing:
        raise GovernanceValidationError(
            "handoff missing structured keys: " + ", ".join(sorted(missing))
        )
    forbidden = HANDOFF_FORBIDDEN_KEYS & set(state)
    if forbidden:
        raise GovernanceValidationError(
            "handoff contains forbidden historical keys: " + ", ".join(sorted(forbidden))
        )
    for name, required in HANDOFF_NESTED_KEYS.items():
        value = state.get(name)
        if not isinstance(value, dict):
            raise GovernanceValidationError(f"handoff field {name} must be an object")
        missing_nested = required - set(value)
        if missing_nested:
            raise GovernanceValidationError(
                f"handoff {name} missing keys: {', '.join(sorted(missing_nested))}"
            )
    active_manifest = state["active_execution_manifest_path"]
    if active_manifest is not None:
        if (
            not isinstance(active_manifest, str)
            or not active_manifest.strip()
            or "\\" in active_manifest
        ):
            raise GovernanceValidationError(
                "active_execution_manifest_path must be a repository-relative path or null"
            )
        manifest_path = Path(active_manifest)
        if manifest_path.is_absolute() or ".." in manifest_path.parts:
            raise GovernanceValidationError(
                "active_execution_manifest_path must stay inside the repository"
            )
        if not (path.parent / manifest_path).is_file():
            raise GovernanceValidationError(
                "active_execution_manifest_path does not identify a retained manifest"
            )
    if state["current_task_state"] not in CURRENT_TASK_STATES:
        raise GovernanceValidationError("invalid current_task_state")
    if state["next_task_activation_status"] not in NEXT_TASK_ACTIVATION_STATES:
        raise GovernanceValidationError("invalid next_task_activation_status")
    if not isinstance(state["current_task_id"], str) or not state["current_task_id"].strip():
        raise GovernanceValidationError("current_task_id must be a non-empty string")
    if state["next_task_id"] is not None and not isinstance(state["next_task_id"], str):
        raise GovernanceValidationError("next_task_id must be a string or null")
    if state["current_task_id"] == state["next_task_id"]:
        raise GovernanceValidationError("current and next task IDs must be distinct")
    if state["next_task_id"] is None and state["next_task_activation_status"] != "not_applicable":
        raise GovernanceValidationError(
            "null next_task_id requires not_applicable activation status"
        )
    if not isinstance(state["exact_next_permitted_action"], str) or not state[
        "exact_next_permitted_action"
    ].strip():
        raise GovernanceValidationError("exact_next_permitted_action must be non-empty")
    if not isinstance(state["unresolved_action_state"], str) or not state[
        "unresolved_action_state"
    ].strip():
        raise GovernanceValidationError("unresolved_action_state must be non-empty")
    for name in (
        "attributable_dirty_paths",
        "protected_user_owned_paths",
        "stage_7_ordered_plan",
        "next_three_atomic_tasks",
    ):
        value = state[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise GovernanceValidationError(f"{name} must be a list of strings")
    for name in ("tracked_dirty_paths", "protected_untracked_paths"):
        value = state["task_start_worktree"][name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise GovernanceValidationError(
                f"task_start_worktree.{name} must be a list of strings"
            )
    for name in ("head_binding", "last_product_candidate_head"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(state[name])):
            raise GovernanceValidationError(f"{name} must be a full Git SHA")
    if state["ahead_behind"]["source"] != "compute_from_git":
        raise GovernanceValidationError("ahead_behind source must be compute_from_git")
    if len(state["next_three_atomic_tasks"]) != 3:
        raise GovernanceValidationError("next_three_atomic_tasks must contain exactly three tasks")
    for name, value in state["budgets"].items():
        if type(value) is not int or value < 0:
            raise GovernanceValidationError(f"budget {name} must be a nonnegative integer")
    registration = state["registration_and_scheduler"]
    if registration["production_registration"] != "NOT_REGISTERED":
        raise GovernanceValidationError("production registration must remain NOT_REGISTERED")
    if registration["scheduler_enabled"] is not False:
        raise GovernanceValidationError("scheduler must remain disabled")
    for name in (
        "branch",
        "active_delivery_stage",
        "latest_focused_validation_result",
        "latest_architecture_validation_result",
        "latest_full_suite_result",
        "current_live_attempt_state",
        "current_evidence_or_session_reference",
        "last_safe_completed_step",
        "current_blocker",
        "prohibited_repeated_action",
        "stage_revision",
        "stage_type",
        "product_precondition",
        "failure_class",
        "control_parent_conversation_id",
        "deferred_independent_review",
    ):
        if not isinstance(state[name], str) or not state[name].strip():
            raise GovernanceValidationError(f"{name} must be a non-empty string")
    for name in ("evidence_requirement", "monitoring_issue"):
        value = state["evidence"][name]
        if not isinstance(value, str) or not value.strip():
            raise GovernanceValidationError(f"evidence.{name} must be a non-empty string")
    if state["control_owner"] != "sol_parent":
        raise GovernanceValidationError("handoff control_owner must be sol_parent")
    if state["evidence"]["do_not_recursively_inspect_parent_evidence_tree"] is not True:
        raise GovernanceValidationError("handoff must prohibit recursive evidence inspection")
    validate_lifecycle_relations(state)
    return state



def validate_lifecycle_relations(state: Dict[str, Any]) -> None:
    if state["next_task_activation_status"] == "awaiting_explicit_activation":
        if state["active_task_or_flow"] != "none":
            raise GovernanceValidationError(
                "awaiting_explicit_activation requires no active task or flow"
            )
        if state["active_execution_manifest_path"] is not None:
            raise GovernanceValidationError(
                "awaiting_explicit_activation must not name an execution manifest"
            )
        if state["registration_and_scheduler"]["production_registration"] != "NOT_REGISTERED":
            raise GovernanceValidationError(
                "awaiting_explicit_activation requires NOT_REGISTERED"
            )
        if state["registration_and_scheduler"]["scheduler_enabled"] is not False:
            raise GovernanceValidationError(
                "awaiting_explicit_activation requires scheduler disabled"
            )
        if state["runtime_ownership_state"] != "none":
            raise GovernanceValidationError(
                "awaiting_explicit_activation requires no runtime owner"
            )
    if state["current_task_state"] in {"completed", "completed_offline"}:
        if state["active_task_or_flow"] != "none":
            raise GovernanceValidationError(
                "completed stage must not retain an active task or flow"
            )
        if state["active_execution_manifest_path"] is not None:
            raise GovernanceValidationError(
                "completed stage must not retain an execution manifest"
            )
        if state["development_lease_state"] != "absent":
            raise GovernanceValidationError("completed stage requires an absent lease")
        if state["journals_and_lease"]["development_lease_status"] != "absent":
            raise GovernanceValidationError("completed stage requires an absent journal lease")
        if state["runtime_ownership_state"] != "none":
            raise GovernanceValidationError("completed stage requires no runtime owner")
        if state["writable_agent_state"] != "none":
            raise GovernanceValidationError("completed stage requires no writable agent")
        if state["unresolved_action_state"] != "clear":
            raise GovernanceValidationError("completed stage requires clear unresolved action")
        if state["journals_and_lease"]["active_prepared_input_sent_unresolved_action_ids"]:
            raise GovernanceValidationError(
                "completed stage must have no unresolved prepared inputs"
            )


def _validate_git_binding(root: Path, field_name: str, commit: str, reviewed_head: str) -> None:
    try:
        commit_check = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GovernanceValidationError(f"unable to inspect Git for {field_name}") from exc
    if commit_check.returncode != 0:
        raise GovernanceValidationError(f"{field_name} does not identify a repository commit")
    try:
        ancestor_check = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, reviewed_head],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GovernanceValidationError(f"unable to inspect Git ancestry for {field_name}") from exc
    if ancestor_check.returncode != 0:
        raise GovernanceValidationError(
            f"{field_name} must be an ancestor of the reviewed HEAD"
        )


def validate_git_bindings(root: Path, state: Dict[str, Any]) -> None:
    try:
        reviewed_head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GovernanceValidationError("unable to inspect the reviewed Git HEAD") from exc
    if reviewed_head.returncode != 0:
        raise GovernanceValidationError("unable to resolve the reviewed Git HEAD")
    head = reviewed_head.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise GovernanceValidationError("reviewed Git HEAD must be a full Git SHA")
    for field_name in ("head_binding", "last_product_candidate_head"):
        _validate_git_binding(root, field_name, state[field_name], head)



def task_block(backlog_text: str, task_id: str) -> str:
    heading = re.compile(
        rf"^### {re.escape(task_id)}(?:\s+—.*)?$", flags=re.MULTILINE
    )
    match = heading.search(backlog_text)
    if not match:
        raise GovernanceValidationError(f"missing backlog task: {task_id}")
    end_match = re.search(r"^### [A-Z0-9-]+(?:\s+—.*)?$", backlog_text[match.end() :], re.MULTILINE)
    end = match.end() + end_match.start() if end_match else len(backlog_text)
    return backlog_text[match.start() : end]


def _contract_fields(block: str, task_id: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for label in TASK_REQUIRED_LABELS:
        match = re.search(
            rf"^\s*-\s+{re.escape(label)}:\s*(.*)$",
            block,
            flags=re.MULTILINE,
        )
        if match is None:
            raise GovernanceValidationError(f"{task_id} missing contract field: {label}")
        value = match.group(1).strip()
        if not value:
            raise GovernanceValidationError(f"{task_id} contract field is empty: {label}")
        fields[label] = value
    return fields


def validate_task_contract(block: str, task_id: str) -> Dict[str, str]:
    fields = _contract_fields(block, task_id)
    if f"`{task_id}`" not in block:
        raise GovernanceValidationError(f"{task_id} contract does not identify its task ID")
    if "allowed paths" not in block:
        raise GovernanceValidationError(f"{task_id} missing per-commit allowed paths")
    if "no push" not in block.casefold():
        raise GovernanceValidationError(f"{task_id} must prohibit push by default")
    requirement = fields["Evidence requirement"].split(None, 1)[0].rstrip(":,.;").upper()
    if requirement not in {"REQUIRED", "TASK_LOCAL", "NOT_APPLICABLE"}:
        raise GovernanceValidationError(
            f"{task_id} has invalid evidence requirement: {fields['Evidence requirement']}"
        )
    if requirement == "NOT_APPLICABLE" and len(fields["Evidence requirement"].split(None, 1)) == 1:
        raise GovernanceValidationError(
            f"{task_id} NOT_APPLICABLE evidence requirement needs a reason"
        )
    return fields


def _evidence_requirement(fields: Dict[str, str], task_id: str) -> str:
    value = fields["Evidence requirement"].split(None, 1)[0].rstrip(":,.;").upper()
    if value not in {"REQUIRED", "TASK_LOCAL", "NOT_APPLICABLE"}:
        raise GovernanceValidationError(f"{task_id} has invalid evidence requirement: {value}")
    return value


def _canonical_status(value: str) -> Optional[str]:
    lowered = value.casefold()
    if lowered.startswith("pending"):
        return "pending"
    if lowered.startswith("in progress") or lowered.startswith("in_progress"):
        return "in_progress"
    if lowered.startswith("blocked"):
        return "blocked"
    if lowered.startswith("completed") or lowered.startswith("passed"):
        return "completed"
    return None


def validate_active_task_state(state: Dict[str, Any], fields: Dict[str, str], task_id: str) -> None:
    backlog_status = _canonical_status(fields["Status"])
    if backlog_status is not None and backlog_status != state["current_task_state"]:
        raise GovernanceValidationError(
            f"{task_id} backlog status {backlog_status} disagrees with handoff state "
            f"{state['current_task_state']}"
        )


def _safe_manifest_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise GovernanceValidationError("active evidence manifest path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise GovernanceValidationError("active evidence manifest path must be repository-relative")
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise GovernanceValidationError("active evidence manifest path escapes repository root")
    return candidate


def validate_task_evidence(
    state: Dict[str, Any],
    fields: Dict[str, str],
    task_id: str,
    root: Path,
) -> Optional[Dict[str, Any]]:
    requirement = _evidence_requirement(fields, task_id)
    evidence = state["evidence"]
    if evidence.get("evidence_requirement") != requirement:
        raise GovernanceValidationError(
            f"{task_id} handoff evidence requirement must be {requirement}"
        )
    reason = evidence.get("evidence_requirement_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise GovernanceValidationError(f"{task_id} handoff evidence requirement needs a reason")
    manifest_value = evidence.get("active_evidence_manifest")
    if requirement == "NOT_APPLICABLE":
        if manifest_value is not None:
            raise GovernanceValidationError(
                f"{task_id} NOT_APPLICABLE evidence must not name an active manifest"
            )
        return None
    manifest_path = _safe_manifest_path(root, manifest_value)
    return validate_manifest(
        manifest_path,
        expected_active_task_id=task_id,
        expected_next_task_id=state["next_task_id"],
    )


def validate_successor(backlog: str, state: Dict[str, Any]) -> None:
    successor = state["next_task_id"]
    if successor is None:
        return
    block = task_block(backlog, successor)
    if not block.strip():
        raise GovernanceValidationError("declared successor task is empty")

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(
    path: Path = MANIFEST_PATH,
    expected_active_task_id: Optional[str] = None,
    expected_next_task_id: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        manifest = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise GovernanceValidationError(f"evidence manifest is not valid JSON: {exc}") from exc
    required = {
        "schema_version",
        "manifest_id",
        "active_task_id",
        "next_task_id",
        "relevant_transaction_action_ids",
        "canonical_evidence_session",
        "read_first",
        "artifacts",
        "unresolved_evidence",
        "integrity",
        "must_not_be_compacted",
        "allowed_historical_references",
        "do_not_recursively_inspect_parent_evidence_tree",
    }
    missing = required - set(manifest)
    if missing:
        raise GovernanceValidationError(
            "evidence manifest missing keys: " + ", ".join(sorted(missing))
        )
    if (
        expected_active_task_id is not None
        and manifest["active_task_id"] != expected_active_task_id
    ):
        raise GovernanceValidationError(
            f"manifest active_task_id must be {expected_active_task_id}"
        )
    if (
        expected_next_task_id is not None
        and manifest["next_task_id"] != expected_next_task_id
    ):
        raise GovernanceValidationError(
            f"manifest next_task_id must be {expected_next_task_id}"
        )
    if manifest["do_not_recursively_inspect_parent_evidence_tree"] is not True:
        raise GovernanceValidationError("manifest must prohibit recursive evidence inspection")
    if not manifest["integrity"].get("all_present_verified_entries_hashed"):
        raise GovernanceValidationError("manifest integrity must require verified hashes")
    artifact_keys = {
        "artifact_id",
        "status",
        "path",
        "expected_sha256",
        "actual_sha256",
        "reason",
    }
    for artifact in manifest["artifacts"]:
        if set(artifact) != artifact_keys:
            raise GovernanceValidationError(
                f"artifact {artifact.get('artifact_id')} must use the fixed artifact schema"
            )
        status = artifact["status"]
        if status not in MANIFEST_STATUSES:
            raise GovernanceValidationError(f"invalid artifact status: {status}")
        if not artifact["reason"]:
            raise GovernanceValidationError(
                f"artifact {artifact['artifact_id']} must explain its status"
            )
        if status == "PRESENT_VERIFIED":
            relative = artifact["path"]
            if not isinstance(relative, str) or not relative:
                raise GovernanceValidationError(
                    f"verified artifact {artifact['artifact_id']} needs an exact path"
                )
            target = ROOT / relative
            if not target.is_file():
                raise GovernanceValidationError(
                    f"verified artifact path does not exist: {relative}"
                )
            actual = _sha256(target)
            if actual != artifact["expected_sha256"] or actual != artifact["actual_sha256"]:
                raise GovernanceValidationError(
                    f"verified artifact hash mismatch: {relative}"
                )
        elif status in {"MISSING", "NOT_LOCATED", "UNKNOWN", "NOT_APPLICABLE"}:
            if artifact["path"] is not None:
                raise GovernanceValidationError(
                    f"{status} artifact {artifact['artifact_id']} must not invent a path"
                )
        elif status == "NOT_VERIFIED_THIS_RUN":
            if artifact["path"] is not None:
                if not isinstance(artifact["path"], str) or not artifact["path"]:
                    raise GovernanceValidationError(
                        f"{status} artifact {artifact['artifact_id']} needs a valid path"
                    )
                target = ROOT / artifact["path"]
                if not target.exists():
                    raise GovernanceValidationError(
                        f"not-verified artifact path does not exist: {artifact['path']}"
                    )
            if artifact["expected_sha256"] is not None or artifact["actual_sha256"] is not None:
                raise GovernanceValidationError(
                    f"{status} artifact {artifact['artifact_id']} must not claim a hash"
                )
        elif status == "PRESENT_HASH_MISMATCH":
            if not isinstance(artifact["path"], str) or not artifact["path"]:
                raise GovernanceValidationError(
                    f"mismatch artifact {artifact['artifact_id']} needs its exact path"
                )
    return manifest


def validate_indexing_rules(path: Path = INDEXING_IGNORE_PATH) -> None:
    lines = {
        line.strip()
        for line in _read(path).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = REQUIRED_INDEXING_PATTERNS - lines
    if missing:
        raise GovernanceValidationError(
            "indexing exclusions missing: " + ", ".join(sorted(missing))
        )
    for lightweight in (
        "evidence/current-evidence-manifest.json",
        "docs/research/bioenhancer_e2e_validation_manifest.json",
        "docs/pns-operations-runbook.md",
    ):
        if any(fnmatch.fnmatch(lightweight, pattern) for pattern in lines):
            raise GovernanceValidationError(
                f"lightweight authoritative artifact is excluded: {lightweight}"
            )


def validate_flow_delivery_loop_policy(root: Path = ROOT) -> Dict[str, Any]:
    path = root / "tasks" / "flow_delivery_loop_policy.json"
    try:
        payload = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise GovernanceValidationError(f"loop policy is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GovernanceValidationError("loop policy must be a JSON object")
    required = {
        "schema_version",
        "registry_kind",
        "max_completed_flows_per_parent_conversation",
    }
    if set(payload) != required:
        raise GovernanceValidationError("loop policy schema mismatch")
    if payload.get("schema_version") != 1:
        raise GovernanceValidationError("unsupported loop-policy schema")
    if payload.get("registry_kind") != "flow_delivery_loop_policy":
        raise GovernanceValidationError("wrong loop-policy registry kind")
    maximum = payload.get("max_completed_flows_per_parent_conversation")
    if type(maximum) is not int or maximum < 0:
        raise GovernanceValidationError(
            "max_completed_flows_per_parent_conversation must be a nonnegative integer"
        )
    gitignore = _read(root / ".gitignore")
    if ".local-orchestrator/" not in gitignore:
        raise GovernanceValidationError(
            "parent conversation progress path is not covered by .gitignore"
        )
    command = _read(root / ".cursor" / "commands" / "pns-flow-delivery-loop.md")
    skill = _read(root / ".cursor" / "skills" / "pns-flow-delivery" / "SKILL.md")
    for label, text in (("command", command), ("skill", skill)):
        if "flow_delivery_loop_policy.json" not in text:
            raise GovernanceValidationError(f"{label} must reference the loop policy")
        if "PARENT_CONVERSATION_ROLLOVER_REQUIRED" not in text:
            raise GovernanceValidationError(f"{label} must name the rollover stop reason")
        if f"max_completed_flows_per_parent_conversation\": {maximum}" in text:
            raise GovernanceValidationError(
                f"{label} hardcodes a competing numeric maximum"
            )
    return payload


def validate_repository(root: Path = ROOT) -> Tuple[List[str], List[str]]:
    state = parse_handoff(root / "CURRENT_HANDOFF.md")
    backlog = _read(root / "BACKLOG.md")
    validate_git_bindings(root, state)
    validate_lifecycle_relations(state)
    active_heading = re.search(
        rf"^### {re.escape(state['current_task_id'])}(?:\s+—.*)?$",
        backlog,
        flags=re.MULTILINE,
    )
    if active_heading is not None:
        active_block = task_block(backlog, state["current_task_id"])
        fields = validate_task_contract(active_block, state["current_task_id"])
        validate_active_task_state(state, fields, state["current_task_id"])
        validate_task_evidence(state, fields, state["current_task_id"], root)
        validate_successor(backlog, state)
    validate_flow_delivery_loop_policy(root)
    validate_indexing_rules(root / ".cursorindexingignore")
    warnings: List[str] = []
    for match in re.finditer(
        r"^### ([A-Z0-9-]+)(?:\s+—.*)?$", backlog, flags=re.MULTILINE
    ):
        task_id = match.group(1)
        if task_id in {state["current_task_id"], state["next_task_id"]}:
            continue
        block = task_block(backlog, task_id)
        status_match = re.search(r"^- Status:\s*(.+)$", block, flags=re.MULTILINE)
        if status_match and any(
            marker in status_match.group(1).casefold()
            for marker in ("ready", "in progress", "blocked")
        ):
            warnings.append(
                f"untouched legacy nonterminal task not migrated: {task_id}"
            )
    return [], warnings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        errors, warnings = validate_repository(args.root.resolve())
    except (OSError, GovernanceValidationError, json.JSONDecodeError) as exc:
        print(f"governance validation failed: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print("governance validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
