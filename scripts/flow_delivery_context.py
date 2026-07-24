#!/usr/bin/env python3
"""Deterministic backlog indexing and bounded flow-delivery context packets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKLOG_PATH = REPO_ROOT / "BACKLOG.md"
QUEUE_PATH = REPO_ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = REPO_ROOT / "tasks" / "flow_delivery_product_policy.json"
COVERAGE_PATH = REPO_ROOT / "tasks" / "flow_delivery_coverage.json"
INDEX_PATH = REPO_ROOT / "tasks" / "backlog_task_index.json"
HANDOFF_PATH = REPO_ROOT / "CURRENT_HANDOFF.md"
CONTEXT_ROOT = REPO_ROOT / ".local-orchestrator" / "context"
BLUESTACKS_REGISTRY_PATH = REPO_ROOT / "tasks" / "flow_delivery_bluestacks_registry.json"

PACKET_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
MAX_PACKET_BYTES = 30000
MAX_RECENT_COMMITS = 5

PROHIBITED_PACKET_PATH_PREFIXES = (
    ".git/",
    ".specstory/",
    "." + "local-reference/",
    ".local-captures/",
    ".local-orchestrator/logs/",
    ".vscode/",
)
PROHIBITED_PACKET_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".mp4",
    ".mov",
    ".avi",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".zip",
    ".7z",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY"),
    re.compile(r"(?i)UNRAID_TEMP_(USERNAME|PASSWORD)\s*[:=]\s*\S+"),
)
ALLOWLISTED_EVIDENCE_SUFFIXES = (
    "current-evidence-manifest.json",
    "-evidence-manifest.json",
)
ALLOWLISTED_EVIDENCE_NAME_FRAGMENTS = (
    "summary.md",
    "reconciliation",
    "status.md",
    "manifest.json",
)

TASK_HEADING_RE = re.compile(r"^### ([A-Z0-9-]+)(?:\s+—.*)?$", re.MULTILINE)


class ContextPacketError(RuntimeError):
    """Raised when backlog indexing or packet generation fails closed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return _sha256_text(_canonical_json(payload))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def repo_head() -> str:
    return _git("rev-parse", "HEAD")


def working_tree_fingerprint() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    snapshot: dict[str, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        raw_path = line[3:]
        paths = raw_path.split(" -> ") if " -> " in raw_path else [raw_path]
        for raw in paths:
            path = raw.strip('"').replace("\\", "/")
            candidate = REPO_ROOT / path
            try:
                stat = candidate.stat()
                size = stat.st_size if candidate.is_file() else None
                modified_ns = stat.st_mtime_ns
            except OSError:
                size = None
                modified_ns = None
            snapshot[path] = {
                "status": status,
                "size": size,
                "modified_ns": modified_ns,
            }
    return _canonical_digest(snapshot)


def attributable_git_status_summary() -> dict[str, Any]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return {
        "dirty_count": len(lines),
        "sample": lines[:20],
    }


def recent_commits(limit: int = MAX_RECENT_COMMITS) -> list[str]:
    output = _git("log", f"-{limit}", "--pretty=format:%h %s")
    if not output:
        return []
    return output.splitlines()[:limit]


def parse_backlog_sections(text: str) -> dict[str, dict[str, Any]]:
    matches = list(TASK_HEADING_RE.finditer(text))
    if not matches:
        raise ContextPacketError("BACKLOG.md contains no task headings")
    sections: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in sections:
            raise ContextPacketError(f"duplicate backlog task ID: {task_id}")
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if end <= start:
            raise ContextPacketError(f"malformed backlog section for {task_id}")
        body = text[start:end]
        if index > 0 and start < matches[index - 1].end():
            raise ContextPacketError(f"overlapping backlog section for {task_id}")
        status_match = re.search(r"^- Status:\s*(.+)$", body, flags=re.MULTILINE)
        status = status_match.group(1).strip() if status_match else "UNKNOWN"
        dep_match = re.search(r"^- Dependencies:\s*(.+)$", body, flags=re.MULTILINE)
        dependency_ids = re.findall(r"`([A-Z0-9-]+)`", dep_match.group(1) if dep_match else "")
        sections[task_id] = {
            "task_id": task_id,
            "heading": match.group(0).strip(),
            "normalized_status": status,
            "section_start": start,
            "section_end": end,
            "section_digest": _sha256_text(body),
            "direct_dependency_ids": dependency_ids,
            "section_text": body,
        }
    return sections


def build_backlog_index(
    *,
    backlog_path: Path = BACKLOG_PATH,
    queue_path: Path = QUEUE_PATH,
    index_path: Path = INDEX_PATH,
    persist: bool = False,
) -> dict[str, Any]:
    backlog_text = backlog_path.read_text(encoding="utf-8")
    if "\r\n" in backlog_text:
        raise ContextPacketError("BACKLOG.md must use LF line endings")
    sections = parse_backlog_sections(backlog_text)
    queue = _read_json(queue_path)
    referenced: dict[str, list[str]] = {}
    for flow in queue.get("flows", []):
        task_id = flow.get("backlog_task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ContextPacketError(f"queue flow missing backlog_task_id: {flow.get('flow_id')}")
        referenced.setdefault(task_id, []).append(flow["flow_id"])
        if task_id not in sections:
            raise ContextPacketError(f"queue references missing backlog task: {task_id}")
    tasks = []
    for task_id in sorted(referenced):
        section = sections[task_id]
        tasks.append(
            {
                "task_id": task_id,
                "exact_markdown_heading": section["heading"],
                "normalized_status": section["normalized_status"],
                "section_start": section["section_start"],
                "section_end": section["section_end"],
                "section_digest": section["section_digest"],
                "direct_dependency_ids": section["direct_dependency_ids"],
                "queue_flow_ids": sorted(referenced[task_id]),
            }
        )
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "backlog_path": "BACKLOG.md",
        "backlog_sha256": _sha256_text(backlog_text),
        "generated_from_head": repo_head(),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    if persist:
        _write_json(index_path, payload)
    return payload


def load_backlog_index(
    *,
    index_path: Path = INDEX_PATH,
    backlog_path: Path = BACKLOG_PATH,
    require_current: bool = True,
) -> dict[str, Any]:
    if not index_path.is_file():
        raise ContextPacketError("backlog index is missing; run index first")
    index = _read_json(index_path)
    if index.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise ContextPacketError("unsupported backlog index schema")
    backlog_text = backlog_path.read_text(encoding="utf-8")
    current_digest = _sha256_text(backlog_text)
    if require_current and index.get("backlog_sha256") != current_digest:
        raise ContextPacketError("backlog index is stale; regenerate with index")
    sections = parse_backlog_sections(backlog_text)
    for task in index.get("tasks", []):
        task_id = task["task_id"]
        section = sections.get(task_id)
        if section is None:
            raise ContextPacketError(f"indexed task missing from backlog: {task_id}")
        if section["section_digest"] != task["section_digest"]:
            raise ContextPacketError(f"stale backlog section digest for {task_id}")
        if (
            section["section_start"] != task["section_start"]
            or section["section_end"] != task["section_end"]
        ):
            raise ContextPacketError(f"stale backlog section bounds for {task_id}")
    return index


def _section_from_index(index: Mapping[str, Any], task_id: str, backlog_text: str) -> dict[str, Any]:
    for task in index["tasks"]:
        if task["task_id"] == task_id:
            body = backlog_text[task["section_start"] : task["section_end"]]
            if _sha256_text(body) != task["section_digest"]:
                raise ContextPacketError(f"backlog section digest mismatch for {task_id}")
            return {
                "task_id": task_id,
                "heading": task["exact_markdown_heading"],
                "normalized_status": task["normalized_status"],
                "section_digest": task["section_digest"],
                "section_text": body,
                "direct_dependency_ids": list(task["direct_dependency_ids"]),
            }
    raise ContextPacketError(f"task not present in backlog index: {task_id}")


def _normalize_repo_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _is_allowlisted_evidence_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized.startswith("evidence/"):
        return False
    name = Path(normalized).name
    if any(normalized.endswith(suffix) for suffix in ALLOWLISTED_EVIDENCE_SUFFIXES):
        return True
    if name.endswith(".md") and any(fragment in name for fragment in ALLOWLISTED_EVIDENCE_NAME_FRAGMENTS):
        return True
    if name.endswith(".json") and "manifest" in name:
        return True
    return False


def assert_packet_path_allowed(path: str) -> None:
    normalized = _normalize_repo_path(path)
    if normalized == "evidence" or normalized.startswith("evidence/"):
        if not _is_allowlisted_evidence_path(normalized):
            raise ContextPacketError(f"prohibited raw evidence path: {normalized}")
        return
    for prefix in PROHIBITED_PACKET_PATH_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            raise ContextPacketError(f"prohibited packet path: {normalized}")
    lowered = normalized.casefold()
    if lowered.endswith(PROHIBITED_PACKET_SUFFIXES):
        raise ContextPacketError(f"prohibited packet path suffix: {normalized}")
    if "Puzzle_Survival_Runtime_POC" in normalized and normalized.endswith((".zip", ".7z")):
        raise ContextPacketError(f"prohibited archive path: {normalized}")


def _scan_for_secrets(text: str) -> None:
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            raise ContextPacketError("packet contains a secret indicator")


def _file_hash_if_present(path: str) -> dict[str, Any] | None:
    assert_packet_path_allowed(path)
    candidate = REPO_ROOT / path
    if not candidate.is_file():
        raise ContextPacketError(f"packet references missing authority file: {path}")
    return {"path": path, "sha256": _sha256_file(candidate), "size": candidate.stat().st_size}


def _compact_handoff_state() -> dict[str, Any]:
    text = HANDOFF_PATH.read_text(encoding="utf-8")
    begin = "<!-- CURRENT_HANDOFF_STATE_BEGIN -->"
    end = "<!-- CURRENT_HANDOFF_STATE_END -->"
    raw = text.split(begin, 1)[1].split(end, 1)[0].strip()
    state = json.loads(raw)
    keep = {
        "schema_version",
        "branch",
        "head",
        "ahead_behind",
        "current_task_id",
        "current_task_state",
        "next_task_id",
        "active_task_or_flow",
        "active_delivery_stage",
        "first_ready_flow",
        "next_ready_flow",
        "development_lease_state",
        "runtime_ownership_state",
        "writable_agent_state",
        "unresolved_action_state",
        "exact_next_permitted_action",
        "current_blocker",
        "latest_full_suite_result",
    }
    return {key: state[key] for key in keep if key in state}


def _stage_deliverable(stage: str) -> str:
    mapping = {
        "reconnaissance": "Return one concise implementation packet for the active flow.",
        "implementation": "Implement only the parent-approved allowlist for the active flow.",
        "implementation_review": "Review the attributable implementation diff and call graph.",
        "correction": "Apply only reproduced defects from the parent review.",
        "evidence_review": "Review one generated BlueStacks session for terminal acceptable evidence.",
        "focused_validation": "Run focused and architecture validation profiles for the active flow.",
        "full_validation": "Run the authoritative full-suite validation profile for the active flow.",
        "selected": "Confirm selection gates and prepare reconnaissance.",
        "commit": "Create the focused attributable commit for the active flow.",
        "live_preflight": "Verify live preflight gates without inventing authorization.",
        "live_execution": "Execute only authorized live validation for the active flow.",
        "blocked": "Record the exact blocker and stop.",
        "completed": "Flow already completed; do not continue.",
    }
    if stage not in mapping:
        raise ContextPacketError(f"unsupported delivery stage: {stage}")
    return mapping[stage]


def _stage_acceptance(flow: Mapping[str, Any], stage: str) -> list[Any]:
    base = list(flow.get("acceptance_criteria", []))
    if stage in {"reconnaissance", "implementation", "implementation_review", "correction"}:
        return base
    if stage in {"focused_validation", "full_validation"}:
        return list(flow.get("completion_tests", []))
    if stage == "evidence_review":
        return list(flow.get("required_terminal_states", []))
    return base[:5]


def _stage_prohibitions(flow: Mapping[str, Any], stage: str) -> list[Any]:
    prohibitions = list(flow.get("scope_prohibitions", []))
    prohibitions.append("packet does not grant runtime or product authorization")
    if stage != "live_execution":
        prohibitions.append("no BlueStacks input in this stage packet")
    return prohibitions


def packet_path(flow_id: str, stage: str) -> Path:
    return CONTEXT_ROOT / flow_id / f"{stage}.json"


def _previous_stage(stage: str) -> str | None:
    order = [
        "selected",
        "reconnaissance",
        "implementation",
        "implementation_review",
        "correction",
        "focused_validation",
        "full_validation",
        "live_preflight",
        "live_execution",
        "evidence_review",
        "commit",
        "completed",
    ]
    if stage not in order:
        return None
    index = order.index(stage)
    return order[index - 1] if index > 0 else None


def _compact_queue_entry_for_packet(flow: Mapping[str, Any]) -> dict[str, Any]:
    """Keep packet-bound queue metadata under budget without dropping authority fields."""

    compact = deepcopy(dict(flow))
    history = compact.get("historical_live_attempts")
    if isinstance(history, list) and history:
        compact["historical_live_attempt_count"] = int(
            compact.get("historical_live_attempt_count") or len(history)
        )
        compact["historical_live_attempts"] = [
            {
                "ordinal": item.get("ordinal"),
                "terminal_outcome": item.get("terminal_outcome"),
                "diagnosis": str(item.get("diagnosis") or "")[:160],
            }
            for item in history
            if isinstance(item, Mapping)
        ]
    # Allowlist seed is still hashed via referenced_file_hashes; omit bulky duplicate list.
    if isinstance(compact.get("implementation_allowlist_seed"), list):
        compact["implementation_allowlist_seed_count"] = len(compact["implementation_allowlist_seed"])
        compact["implementation_allowlist_seed"] = list(compact["implementation_allowlist_seed"])[:8]
    return compact


def _compact_backlog_section_for_packet(section: Mapping[str, Any], *, limit: int = 2400) -> dict[str, Any]:
    text = str(section.get("section_text") or "")
    if len(text.encode("utf-8")) > limit:
        encoded = text.encode("utf-8")[:limit]
        text = encoded.decode("utf-8", errors="ignore") + "\n…[truncated for packet budget]"
    return {
        "task_id": section["task_id"],
        "heading": section["heading"],
        "normalized_status": section["normalized_status"],
        "section_digest": section["section_digest"],
        "section_text": text,
    }


def build_context_packet(
    *,
    flow_id: str,
    stage: str,
    reuse_if_current: bool = True,
    queue_path: Path = QUEUE_PATH,
    policy_path: Path = POLICY_PATH,
    coverage_path: Path = COVERAGE_PATH,
    index_path: Path = INDEX_PATH,
) -> dict[str, Any]:
    from scripts.flow_delivery_control import (  # local import avoids cycles at module import
        READY_FLOW_PACKET_FIELDS,
        validate_queue,
        validate_policy,
    )

    queue = _read_json(queue_path)
    validate_queue(queue)
    policy = _read_json(policy_path)
    validate_policy(policy)
    coverage = _read_json(coverage_path)
    flows = {item["flow_id"]: item for item in queue["flows"]}
    if flow_id not in flows:
        raise ContextPacketError(f"unknown flow_id: {flow_id}")
    flow = flows[flow_id]
    if flow["status"] == "ready":
        missing = READY_FLOW_PACKET_FIELDS - set(flow)
        if missing:
            raise ContextPacketError(
                f"required ready-flow metadata absent: {sorted(missing)}"
            )
    index = load_backlog_index(index_path=index_path, require_current=True)
    backlog_text = BACKLOG_PATH.read_text(encoding="utf-8")
    active_section = _section_from_index(index, flow["backlog_task_id"], backlog_text)
    dependency_sections = []
    for dependency_flow_id in flow.get("dependencies", []):
        dependency = flows[dependency_flow_id]
        dependency_sections.append(
            _section_from_index(index, dependency["backlog_task_id"], backlog_text)
        )
    for dep_task_id in active_section["direct_dependency_ids"]:
        if dep_task_id in {item["task_id"] for item in dependency_sections}:
            continue
        # Direct backlog dependencies may be historical; include only when indexed.
        if any(task["task_id"] == dep_task_id for task in index["tasks"]):
            dependency_sections.append(_section_from_index(index, dep_task_id, backlog_text))

    policy_entry = None
    for item in policy.get("policies", []):
        if flow_id.casefold() in item.get("scope", "").casefold() or flow_id in json.dumps(item):
            policy_entry = item
            break
    if policy_entry is None and flow_id.startswith("CAMPAIGN"):
        for item in policy.get("policies", []):
            if item.get("policy_id", "").startswith("campaign-"):
                policy_entry = item
                break
    if policy_entry is None and flow_id.startswith("ULTIMATE-CHALLENGE"):
        for item in policy.get("policies", []):
            if item.get("policy_id", "").startswith("ultimate-challenge-"):
                policy_entry = item
                break

    coverage_entry = coverage.get("flows", {}).get(flow_id)
    bluestacks_entry = None
    if BLUESTACKS_REGISTRY_PATH.is_file():
        registry = _read_json(BLUESTACKS_REGISTRY_PATH)
        # The canonical registry keys flows by flow_id (schema flow_delivery_bluestacks).
        flows = registry.get("flows", {}) if isinstance(registry, dict) else {}
        contract = flows.get(flow_id) if isinstance(flows, dict) else None
        if isinstance(contract, dict):
            bluestacks_entry = {"flow_id": flow_id, **contract}

    referenced_files: list[dict[str, Any]] = []
    for path in list(flow.get("implementation_entrypoints", [])) + list(
        flow.get("focused_tests", [])
    ) + list(flow.get("reference_docs", [])) + list(
        flow.get("implementation_allowlist_seed", [])
    ):
        if not isinstance(path, str):
            continue
        # Binary assets may remain on the delivery allowlist for review/commit attribution,
        # but never enter the text context packet.
        if path.casefold().endswith(PROHIBITED_PACKET_SUFFIXES):
            continue
        assert_packet_path_allowed(path)
        info = _file_hash_if_present(path)
        if info is not None and info not in referenced_files:
            referenced_files.append(info)

    evidence_refs: list[dict[str, Any]] = []
    for candidate in (
        "evidence/current-evidence-manifest.json",
        "evidence/mvp-quest-to-claim-evidence-manifest.json",
    ):
        if (REPO_ROOT / candidate).is_file():
            assert_packet_path_allowed(candidate)
            evidence_refs.append(
                {
                    "path": candidate,
                    "sha256": _sha256_file(REPO_ROOT / candidate),
                    "kind": "allowlisted_manifest",
                }
            )

    head = repo_head()
    fingerprint = working_tree_fingerprint()
    queue_entry_digest = _canonical_digest(flow)
    product_policy_digest = _canonical_digest(policy_entry or {"policy_id": None})
    coverage_digest = _canonical_digest(coverage_entry or {"flow_id": flow_id, "coverage": None})
    previous = _previous_stage(stage)
    previous_digest = None
    changed_since_previous: list[str] = []
    if previous is not None:
        prior_path = packet_path(flow_id, previous)
        if prior_path.is_file():
            prior = _read_json(prior_path)
            previous_digest = prior.get("packet_digest")
            prior_refs = {
                item["path"]: item.get("sha256")
                for item in prior.get("referenced_file_hashes", [])
            }
            for item in referenced_files:
                if prior_refs.get(item["path"]) != item["sha256"]:
                    changed_since_previous.append(item["path"])

    unsigned = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "active_flow_id": flow_id,
        "active_delivery_stage": stage,
        "active_queue_entry": _compact_queue_entry_for_packet(flow),
        "active_product_policy_entry": policy_entry,
        "active_coverage_entry": coverage_entry,
        "active_bluestacks_registry_entry": bluestacks_entry,
        "active_backlog_section": _compact_backlog_section_for_packet(active_section, limit=3200),
        "direct_dependency_sections": [
            _compact_backlog_section_for_packet(item, limit=1800)
            for item in dependency_sections
        ],
        "implementation_entrypoint_hashes": [
            item
            for item in referenced_files
            if item["path"] in set(flow.get("implementation_entrypoints", []))
        ],
        "focused_test_hashes": [
            item for item in referenced_files if item["path"] in set(flow.get("focused_tests", []))
        ],
        "exact_reference_document_paths": list(flow.get("reference_docs", [])),
        "attributable_git_status_summary": attributable_git_status_summary(),
        "bounded_attributable_diff_summary": {
            "note": "Use git diff for exact content; packet stores status summary only.",
            "dirty_count": attributable_git_status_summary()["dirty_count"],
        },
        "recent_relevant_commits": recent_commits(),
        "compact_handoff_state": _compact_handoff_state(),
        "retained_evidence_summaries": evidence_refs,
        "stage_specific_acceptance_criteria": _stage_acceptance(flow, stage),
        "stage_specific_prohibitions": _stage_prohibitions(flow, stage),
        "stage_specific_requested_deliverable": _stage_deliverable(stage),
        "built_from_head": head,
        "working_tree_fingerprint": fingerprint,
        "queue_entry_digest": queue_entry_digest,
        "product_policy_digest": product_policy_digest,
        "coverage_entry_digest": coverage_digest,
        "backlog_section_digest": active_section["section_digest"],
        "dependency_section_digests": {
            item["task_id"]: item["section_digest"] for item in dependency_sections
        },
        "referenced_file_hashes": referenced_files,
        "previous_stage_packet_digest": previous_digest,
        "attributable_changed_paths_since_previous_stage": changed_since_previous,
        "authorization_note": "Context only; does not grant runtime or product authorization.",
    }
    packet = dict(unsigned)
    packet["packet_digest"] = _canonical_digest(unsigned)
    serialized = (_canonical_json(packet) + "\n").encode("utf-8")
    if len(serialized) > MAX_PACKET_BYTES:
        raise ContextPacketError(
            f"packet exceeds {MAX_PACKET_BYTES} UTF-8 bytes: {len(serialized)}"
        )
    _scan_for_secrets(serialized.decode("utf-8"))
    target = packet_path(flow_id, stage)
    if reuse_if_current and target.is_file():
        existing = target.read_bytes()
        if existing == serialized:
            return {
                "cache_hit": True,
                "packet_path": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
                "packet_digest": packet["packet_digest"],
                "bytes": len(existing),
            }
        existing_obj = json.loads(existing.decode("utf-8"))
        if (
            existing_obj.get("packet_digest") == packet["packet_digest"]
            and existing_obj.get("built_from_head") == head
            and existing_obj.get("working_tree_fingerprint") == fingerprint
            and existing_obj.get("queue_entry_digest") == queue_entry_digest
            and existing_obj.get("backlog_section_digest") == active_section["section_digest"]
        ):
            # Authority unchanged but serialization differed only by optional formatting; rewrite
            # only when digests already match and keep byte-identical future hits.
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(serialized)
    return {
        "cache_hit": False,
        "packet_path": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
        "packet_digest": packet["packet_digest"],
        "bytes": len(serialized),
    }


def validate_context_packet(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_PACKET_BYTES:
        raise ContextPacketError(f"packet exceeds {MAX_PACKET_BYTES} UTF-8 bytes")
    text = raw.decode("utf-8")
    _scan_for_secrets(text)
    packet = json.loads(text)
    required = {
        "packet_schema_version",
        "active_flow_id",
        "active_delivery_stage",
        "active_queue_entry",
        "packet_digest",
        "built_from_head",
        "working_tree_fingerprint",
        "queue_entry_digest",
        "product_policy_digest",
        "coverage_entry_digest",
        "backlog_section_digest",
        "referenced_file_hashes",
        "stage_specific_requested_deliverable",
    }
    missing = required - set(packet)
    if missing:
        raise ContextPacketError(f"packet missing fields: {sorted(missing)}")
    if packet["packet_schema_version"] != PACKET_SCHEMA_VERSION:
        raise ContextPacketError("unsupported packet schema")
    unsigned = dict(packet)
    digest = unsigned.pop("packet_digest")
    if digest != _canonical_digest(unsigned):
        raise ContextPacketError("packet digest mismatch")
    if packet["built_from_head"] != repo_head():
        raise ContextPacketError("packet HEAD is stale")
    if packet["working_tree_fingerprint"] != working_tree_fingerprint():
        raise ContextPacketError("packet working-tree fingerprint is stale")
    load_backlog_index(require_current=True)
    for item in packet.get("referenced_file_hashes", []):
        path_value = item.get("path")
        if not isinstance(path_value, str):
            raise ContextPacketError("referenced file path must be a string")
        assert_packet_path_allowed(path_value)
        info = _file_hash_if_present(path_value)
        if info is None or info["sha256"] != item.get("sha256"):
            raise ContextPacketError(f"referenced file hash mismatch: {path_value}")
    for item in packet.get("retained_evidence_summaries", []):
        assert_packet_path_allowed(item["path"])
    queue = _read_json(QUEUE_PATH)
    flow = next(item for item in queue["flows"] if item["flow_id"] == packet["active_flow_id"])
    if _canonical_digest(flow) != packet["queue_entry_digest"]:
        raise ContextPacketError("queue entry digest is stale")
    return {
        "ok": True,
        "packet_path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "packet_digest": digest,
        "bytes": len(raw),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("index", help="Create or refresh tasks/backlog_task_index.json")

    build = sub.add_parser("build", help="Build or reuse a stage context packet")
    build.add_argument("--flow-id", required=True)
    build.add_argument("--stage", required=True)
    build.add_argument("--reuse-if-current", action="store_true", default=True)
    build.add_argument("--force-rebuild", action="store_true")

    validate = sub.add_parser("validate", help="Validate an existing context packet")
    validate.add_argument("--packet", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "index":
            payload = build_backlog_index(persist=True)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "task_count": payload["task_count"],
                        "backlog_sha256": payload["backlog_sha256"],
                        "index_path": "tasks/backlog_task_index.json",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "build":
            if not INDEX_PATH.is_file():
                build_backlog_index(persist=True)
            result = build_context_packet(
                flow_id=args.flow_id,
                stage=args.stage,
                reuse_if_current=not args.force_rebuild,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "validate":
            result = validate_context_packet((REPO_ROOT / args.packet).resolve())
            print(json.dumps(result, sort_keys=True))
            return 0
    except (ContextPacketError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
