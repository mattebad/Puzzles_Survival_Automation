#!/usr/bin/env python3
"""Validate durable governance state without touching runtime or evidence."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
HANDOFF_PATH = ROOT / "CURRENT_HANDOFF.md"
BACKLOG_PATH = ROOT / "BACKLOG.md"
MANIFEST_PATH = ROOT / "evidence" / "current-evidence-manifest.json"
INDEXING_IGNORE_PATH = ROOT / ".cursorindexingignore"
CURRENT_TASK_ID = "GOV-DURABLE-STATE"
NEXT_TASK_ID = "MVP-QUEST-TO-CLAIM"

CURRENT_TASK_STATES = {"pending", "in_progress", "blocked", "completed"}
NEXT_TASK_ACTIVATION_STATES = {
    "ready",
    "contract_migration_required",
    "dependency_blocked",
    "not_applicable",
}
MANIFEST_STATUSES = {
    "PRESENT_VERIFIED",
    "PRESENT_HASH_MISMATCH",
    "MISSING",
    "NOT_LOCATED",
    "UNKNOWN",
    "NOT_APPLICABLE",
}

HANDOFF_REQUIRED_KEYS = {
    "schema_version",
    "repository",
    "current_task_id",
    "current_task_state",
    "next_task_id",
    "next_task_activation_status",
    "phase",
    "objective",
    "last_safe_completed_step",
    "next_permitted_action",
    "actions_already_performed",
    "actions_not_to_repeat",
    "runtime",
    "journals_and_lease",
    "game_day",
    "registration_and_scheduler",
    "tests",
    "evidence",
    "next_action",
}

HANDOFF_NESTED_KEYS = {
    "repository": {
        "branch",
        "head",
        "origin_relationship",
        "staged_paths",
        "relevant_unstaged_paths",
        "protected_untracked_paths_or_categories",
        "most_recent_task_scoped_commits",
    },
    "runtime": {
        "vm_state",
        "worker_state",
        "active_operator_collector_automation_test_emulator_processes",
        "adb_exposure_and_connection_state",
        "expected_fixed_profile",
        "observed_current_profile",
        "foreground_package_activity",
        "manual_only_screen_state",
    },
    "journals_and_lease": {
        "authoritative_operational_journal_path",
        "lease_owner",
        "lease_status",
        "lease_expiry",
        "active_prepared_input_sent_unresolved_action_ids",
        "latest_confirmed_consequential_action",
        "relevant_navigation_only_records",
        "historical_source_journal_references",
        "historical_unresolved_classification",
    },
    "game_day": {
        "game_day_id",
        "reset_status_or_next_reset",
        "derivation",
        "active_task_cycle_binding",
    },
    "registration_and_scheduler": {
        "registered_operator_tasks",
        "scheduler_enabled_disabled",
        "scheduler_eligible_flows",
        "live_task_state_row_count",
        "pending_promotion_gates",
    },
    "tests": {
        "pinned_environment",
        "last_full_suite_count",
        "known_accepted_baseline_failures",
        "new_regressions",
        "last_relevant_focused_tests",
    },
    "evidence": {
        "active_evidence_manifest",
        "raw_source",
        "immediate_before",
        "immediate_post",
        "semantic_result",
        "operational_journal",
        "historical_source_journal",
        "unresolved_evidence",
        "must_retain_artifacts",
        "do_not_recursively_inspect_parent_evidence_tree",
    },
    "next_action": {
        "permitted_actions",
        "prohibited_actions",
        "exact_stop_condition",
        "expected_next_atomic_task",
        "expected_next_activation_status",
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
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GovernanceValidationError(f"handoff state is not valid JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise GovernanceValidationError("handoff state must be a JSON object")
    missing = HANDOFF_REQUIRED_KEYS - set(state)
    if missing:
        raise GovernanceValidationError(
            "handoff missing structured keys: " + ", ".join(sorted(missing))
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
    if state["current_task_state"] not in CURRENT_TASK_STATES:
        raise GovernanceValidationError("invalid current_task_state")
    if state["next_task_activation_status"] not in NEXT_TASK_ACTIVATION_STATES:
        raise GovernanceValidationError("invalid next_task_activation_status")
    if state["current_task_id"] != CURRENT_TASK_ID:
        raise GovernanceValidationError("current_task_id must be GOV-DURABLE-STATE")
    if state["next_task_id"] != NEXT_TASK_ID:
        raise GovernanceValidationError("next_task_id must be MVP-QUEST-TO-CLAIM")
    if state["current_task_id"] == state["next_task_id"]:
        raise GovernanceValidationError("current and next task IDs must be distinct")
    if state["evidence"]["do_not_recursively_inspect_parent_evidence_tree"] is not True:
        raise GovernanceValidationError("handoff must prohibit recursive evidence inspection")
    return state


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


def validate_task_contract(block: str, task_id: str = CURRENT_TASK_ID) -> None:
    for label in TASK_REQUIRED_LABELS:
        if not re.search(rf"^\s*-\s+{re.escape(label)}:", block, flags=re.MULTILINE):
            raise GovernanceValidationError(f"{task_id} missing contract field: {label}")
    if f"`{task_id}`" not in block:
        raise GovernanceValidationError(f"{task_id} contract does not identify its task ID")
    if "docs(agent): define durable execution policy" not in block:
        raise GovernanceValidationError(f"{task_id} missing docs commit allowlist")
    if "docs(handoff): standardize current operational state" not in block:
        raise GovernanceValidationError(f"{task_id} missing handoff commit allowlist")
    if "chore(governance): validate durable state contracts" not in block:
        raise GovernanceValidationError(f"{task_id} missing validator commit allowlist")
    if "allowed paths" not in block:
        raise GovernanceValidationError(f"{task_id} missing per-commit allowed paths")
    if "MVP-QUEST-TO-CLAIM" not in block:
        raise GovernanceValidationError(f"{task_id} must preserve the next product task")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(path: Path = MANIFEST_PATH) -> Dict[str, Any]:
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
    if manifest["active_task_id"] != CURRENT_TASK_ID:
        raise GovernanceValidationError("manifest active_task_id must be GOV-DURABLE-STATE")
    if manifest["next_task_id"] != NEXT_TASK_ID:
        raise GovernanceValidationError("manifest next_task_id must be MVP-QUEST-TO-CLAIM")
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


def validate_repository(root: Path = ROOT) -> Tuple[List[str], List[str]]:
    state = parse_handoff(root / "CURRENT_HANDOFF.md")
    backlog = _read(root / "BACKLOG.md")
    active_block = task_block(backlog, state["current_task_id"])
    validate_task_contract(active_block, state["current_task_id"])
    validate_manifest(root / state["evidence"]["active_evidence_manifest"])
    validate_indexing_rules(root / ".cursorindexingignore")
    warnings: List[str] = []
    for match in re.finditer(
        r"^### ([A-Z0-9-]+)(?:\s+—.*)?$", backlog, flags=re.MULTILINE
    ):
        task_id = match.group(1)
        if task_id in {CURRENT_TASK_ID, NEXT_TASK_ID}:
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
