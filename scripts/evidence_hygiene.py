#!/usr/bin/env python3
"""Audit, plan, archive, and verify local evidence without unsafe cleanup.

The audit is deliberately conservative. It hashes regular files incrementally, never follows
symlinks, distinguishes Git states, scans repository text references, inspects action journals
read-only, and protects all tracked, referenced, decisive, unresolved, and journal evidence.
Only an explicit ``archive --execute`` may remove a file, and only after a content-addressed
archive blob and path manifest have been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "evidence"
DEFAULT_AUDIT_PATH = REPO_ROOT / "artifacts" / "evidence-audit.json"
DEFAULT_SUMMARY_PATH = REPO_ROOT / "docs" / "evidence-retention-report.md"
DEFAULT_ARCHIVE_ROOT = REPO_ROOT.parent / "Puzzles_Survival_Automation_evidence_archive"
CHUNK_SIZE = 1024 * 1024
AUDIT_SCHEMA = "evidence-hygiene-v1"
LOCAL_REFERENCE_NAME = "." + "local-reference"
RETENTION_CLASSES = (
    "PORTABLE_TEST_FIXTURE", "RUNTIME_TEMPLATE", "DECISIVE_CONSEQUENTIAL_EVIDENCE",
    "UNRESOLVED_ACTION_EVIDENCE", "JOURNAL_SOURCE", "RECONCILED_JOURNAL",
    "REFERENCED_SUPPORTING_EVIDENCE", "NAVIGATION_DIAGNOSTIC", "GENERATED_DERIVATIVE",
    "EXACT_DUPLICATE", "REPEATED_IDENTICAL_FRAME", "TRANSFER_COPY",
    "SUPERSEDED_ZERO_INPUT_ATTEMPT", "LOCAL_RAW_SESSION", "ARCHIVE_ONLY",
    "UNKNOWN_REVIEW_REQUIRED",
)
PROTECTED_CLASSES = frozenset({
    "PORTABLE_TEST_FIXTURE", "RUNTIME_TEMPLATE", "DECISIVE_CONSEQUENTIAL_EVIDENCE",
    "UNRESOLVED_ACTION_EVIDENCE", "JOURNAL_SOURCE", "RECONCILED_JOURNAL",
    "REFERENCED_SUPPORTING_EVIDENCE", "ARCHIVE_ONLY", "UNKNOWN_REVIEW_REQUIRED",
})
TEXT_SUFFIXES = frozenset({
    ".csv", ".json", ".md", ".ndjson", ".py", ".ps1", ".sh", ".txt", ".xml", ".yaml", ".yml",
})
JOURNAL_NAME_RE = re.compile(r"(?:action|journal|reconcil|unresolved|pre-dispatch)", re.I)
REFERENCE_RE = re.compile(r"(?:/|\b)evidence/[A-Za-z0-9._+@~/-]+")
TRAILING_REFERENCE_CHARS = ".,;:)]}>\"'`"


class HygieneError(RuntimeError):
    """Base error for evidence hygiene operations."""


class SymlinkSafetyError(HygieneError):
    """Raised instead of traversing a symlink in or below evidence."""


class ConcurrentChangeError(HygieneError):
    """Raised when a file changes while it is being hashed or archived."""


def _run_git(repo_root: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(["git", "-C", str(repo_root), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def _nul_paths(payload: bytes) -> set[str]:
    return {os.fsdecode(item) for item in payload.split(b"\0") if item}


def git_path_sets(repo_root: Path, evidence_root: Path) -> dict[str, set[str]]:
    """Return tracked, untracked, and ignored repository-relative evidence paths."""
    prefix = evidence_root.resolve().relative_to(repo_root.resolve()).as_posix().rstrip("/")
    return {
        "tracked": _nul_paths(_run_git(repo_root, ["ls-files", "-z", "--", prefix])),
        "untracked": _nul_paths(_run_git(repo_root, ["ls-files", "--others", "--exclude-standard", "-z", "--", prefix])),
        "ignored": _nul_paths(_run_git(repo_root, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", prefix])),
    }


def iter_regular_files(root: Path) -> Iterator[Path]:
    """Yield regular files without following symlinks or entering local reference material."""
    root = root.absolute()
    if LOCAL_REFERENCE_NAME in root.parts:
        raise HygieneError("local reference material is excluded from every hygiene operation")
    if root.is_symlink():
        raise SymlinkSafetyError(f"evidence root is a symlink: {root}")
    if not root.is_dir():
        raise HygieneError(f"evidence root is not a directory: {root}")

    def walk(directory: Path) -> Iterator[Path]:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                raise SymlinkSafetyError(f"refusing to traverse symlink: {path}")
            if entry.is_dir(follow_symlinks=False):
                if entry.name != LOCAL_REFERENCE_NAME:
                    yield from walk(path)
            elif entry.is_file(follow_symlinks=False):
                yield path

    yield from walk(root)


def sha256_stream(path: Path, chunk_size: int = CHUNK_SIZE) -> tuple[str, int]:
    """Hash a regular file incrementally and report the bytes read."""
    before = path.stat(follow_symlinks=False)
    if not path.is_file() or path.is_symlink():
        raise SymlinkSafetyError(f"hashing requires a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    after = path.stat(follow_symlinks=False)
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ConcurrentChangeError(f"file changed while hashing: {path}")
    return digest.hexdigest(), size


def _file_type(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".sqlite3-wal"):
        return "sqlite3-wal"
    if name.endswith(".sqlite3-shm"):
        return "sqlite3-shm"
    if name.endswith(".sqlite3") or name.endswith(".db"):
        return "sqlite3"
    mime, _ = mimetypes.guess_type(path.name)
    return mime or (path.suffix.lower().lstrip(".") or "no_extension")


def _session_name(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 3 and parts[0:2] == ("evidence", "sessions"):
        return parts[2]
    if len(parts) >= 2 and parts[0] == "evidence":
        return parts[1]
    return "evidence-root"


def _reference_kind(reference_path: str) -> str:
    lower = reference_path.replace("\\", "/").lower()
    if "/tests/" in f"/{lower}" or lower.startswith("tests/"):
        return "tests"
    if lower == "backlog.md":
        return "backlog"
    if lower == "current_handoff.md":
        return "handoff"
    if ".plan." in lower or lower.endswith("plan.md"):
        return "plan"
    if lower.startswith("docs/"):
        return "documentation"
    if lower.startswith("runtime-profile/"):
        return "runtime"
    if lower.startswith(("scripts/", "tasks/", "safe_action_core/", "calibration/")):
        return "source"
    if lower.startswith("evidence/"):
        return "evidence-record"
    return "repository-text"


def _normalise_reference(candidate: str) -> str:
    candidate = candidate.replace("\\", "/").lstrip("./")
    if candidate.startswith("/evidence/"):
        candidate = candidate[1:]
    return candidate.rstrip(TRAILING_REFERENCE_CHARS)


def _candidate_matches(candidate: str, evidence_paths: set[str]) -> set[str]:
    candidate = _normalise_reference(candidate)
    matches = {candidate} if candidate in evidence_paths else set()
    prefix = candidate.rstrip("/") + "/"
    matches.update(path for path in evidence_paths if path.startswith(prefix))
    return matches


def scan_references(repo_root: Path, evidence_paths: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    """Build a reverse map from evidence paths to tracked repository text references."""
    evidence_paths = set(evidence_paths)
    reverse: dict[str, set[tuple[str, str]]] = defaultdict(set)
    tracked = sorted(_nul_paths(_run_git(repo_root, ["ls-files", "-z"])))
    for relative in tracked:
        if relative.startswith(LOCAL_REFERENCE_NAME + "/"):
            continue
        path = repo_root / relative
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        carry = ""
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                text = carry + chunk.decode("utf-8", errors="ignore")
                for match in REFERENCE_RE.finditer(text):
                    candidate = _normalise_reference(match.group(0))
                    for target in _candidate_matches(candidate, evidence_paths):
                        reverse[target].add((relative, _reference_kind(relative)))
                carry = text[-512:]
    return {path: [{"path": item[0], "kind": item[1]} for item in sorted(values)] for path, values in sorted(reverse.items())}


def _extract_references(text: str, evidence_paths: set[str]) -> set[str]:
    found = set()
    for match in REFERENCE_RE.finditer(text):
        found.update(_candidate_matches(match.group(0), evidence_paths))
    return found


def inspect_journals(evidence_paths: Iterable[str], absolute_paths: Mapping[str, Path]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], set[str]]:
    """Inspect action databases and journal-like text read-only."""
    evidence_paths = set(evidence_paths)
    refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    journal_meta: dict[str, dict[str, Any]] = {}

    def record_reference(source: str, text: str) -> None:
        for target in _extract_references(text, evidence_paths):
            refs[target].append({"path": source, "kind": "action-journal-or-reconciliation"})

    for relative, path in sorted(absolute_paths.items()):
        lower = path.name.lower()
        if lower.endswith((".sqlite3-wal", ".sqlite3-shm")):
            journal_meta[relative] = {"kind": "JOURNAL_SOURCE", "unresolved": False, "nonterminal": False, "status_counts": {}}
            continue
        if not lower.endswith((".sqlite3", ".db")):
            if JOURNAL_NAME_RE.search(path.name) and path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    with path.open("rb") as handle:
                        while chunk := handle.read(CHUNK_SIZE):
                            record_reference(relative, chunk.decode("utf-8", errors="ignore"))
                except OSError:
                    pass
            if "reconcil" in lower:
                journal_meta[relative] = {"kind": "RECONCILED_JOURNAL", "unresolved": False, "nonterminal": False, "status_counts": {}}
            continue
        metadata: dict[str, Any] = {"kind": "RECONCILED_JOURNAL" if "reconcil" in lower else "JOURNAL_SOURCE", "unresolved": False, "nonterminal": False, "status_counts": {}}
        try:
            connection = sqlite3.connect(f"file:{path}?immutable=1", uri=True, timeout=0.1)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "actions" in tables:
                rows = connection.execute("SELECT final_status, COUNT(*) FROM actions GROUP BY final_status").fetchall()
                counts = {str(status): int(count) for status, count in rows}
                metadata["status_counts"] = counts
                metadata["unresolved"] = counts.get("unresolved", 0) > 0
                metadata["nonterminal"] = any(counts.get(status, 0) > 0 for status in ("prepared", "input_sent"))
                columns = {row[1] for row in connection.execute("PRAGMA table_info(actions)")}
                for column in ("evidence_refs_json", "reconciliation_result_json", "policy_request_json"):
                    if column in columns:
                        for (value,) in connection.execute(f"SELECT {column} FROM actions WHERE {column} IS NOT NULL"):
                            if value:
                                record_reference(relative, str(value))
            if "audit_events" in tables:
                for (value,) in connection.execute("SELECT payload_json FROM audit_events WHERE payload_json IS NOT NULL"):
                    if value:
                        record_reference(relative, str(value))
            connection.close()
        except (OSError, sqlite3.Error):
            metadata["inspection_error"] = True
        journal_meta[relative] = metadata
    unresolved_sessions = {_session_name(relative) for relative, metadata in journal_meta.items() if metadata.get("unresolved") or metadata.get("nonterminal")}
    return ({path: sorted(values, key=lambda item: (item["path"], item["kind"])) for path, values in sorted(refs.items())}, journal_meta, unresolved_sessions)


def group_duplicates(records: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("sha256"):
            groups[str(record["sha256"])].append(record)
    return {digest: sorted(values, key=lambda item: str(item["relative_path"])) for digest, values in sorted(groups.items()) if len(values) > 1}


def _is_decisive(relative: str, session: str) -> bool:
    lower = relative.lower()
    tokens = ("claim-success", "praise-success", "daily-claim-evidence", "help-all-validation", "help-all-semantic-fix", "alliance-help-1783986842", "personal-might-claim")
    return any(token in lower or token in session.lower() for token in tokens)


def _is_navigation(relative: str, session: str) -> bool:
    lower = f"{relative} {session}".lower()
    return any(token in lower for token in ("navigation", "nav-", "route-", "home-to-", "more-to-", "quest-to-", "rankings", "back-"))


def _is_generated(relative: str) -> bool:
    lower = relative.lower()
    return any(token in lower for token in ("annotated", "annotation", ".sha256"))


def _is_transfer(relative: str) -> bool:
    return any(token in relative.lower().split("/") for token in ("remote-cache", "worker-copy", "transfer", "worker", "remote"))


def classify_retention(*, relative: str, status: str, session: str, reference_entries: Sequence[Mapping[str, str]], journal_entries: Sequence[Mapping[str, Any]], journal_meta: Mapping[str, Any] | None, unresolved_session: bool) -> tuple[str, bool]:
    """Return (retention class, protected) before duplicate-specific refinement."""
    name = Path(relative).name.lower()
    kinds = {str(entry.get("kind")) for entry in reference_entries}
    if journal_meta and journal_meta.get("kind") == "RECONCILED_JOURNAL":
        return "RECONCILED_JOURNAL", True
    if name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db")) or "journal" in name:
        return "JOURNAL_SOURCE", True
    if unresolved_session or any(entry.get("kind") == "action-journal-or-reconciliation" for entry in journal_entries):
        return "UNRESOLVED_ACTION_EVIDENCE", True
    if _is_decisive(relative, session):
        return "DECISIVE_CONSEQUENTIAL_EVIDENCE", True
    if "tests" in kinds and not _is_navigation(relative, session):
        return "PORTABLE_TEST_FIXTURE", True
    if kinds.intersection({"source", "runtime"}):
        return "RUNTIME_TEMPLATE", True
    if reference_entries:
        return "REFERENCED_SUPPORTING_EVIDENCE", True
    if _is_generated(relative):
        return "GENERATED_DERIVATIVE", False
    if _is_navigation(relative, session):
        return "NAVIGATION_DIAGNOSTIC", False
    if any(token in session.lower() for token in ("no-input", "observe", "precheck")):
        return "SUPERSEDED_ZERO_INPUT_ATTEMPT", False
    if status == "tracked":
        return "ARCHIVE_ONLY", True
    if status in {"untracked", "ignored"}:
        return "LOCAL_RAW_SESSION", False
    return "UNKNOWN_REVIEW_REQUIRED", True


def _history_report(repo_root: Path) -> dict[str, Any]:
    current_oids = set()
    for line in _run_git(repo_root, ["ls-files", "-s", "--", "evidence"]).decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            current_oids.add(fields[1])
    objects: dict[str, str] = {}
    for line in _run_git(repo_root, ["rev-list", "--objects", "--all"]).decode("utf-8", errors="replace").splitlines():
        fields = line.split(" ", 1)
        if len(fields) == 2 and fields[1].startswith("evidence/"):
            objects[fields[0]] = fields[1]
    sizes: dict[str, int] = {}
    if objects:
        query = ("\n".join(sorted(objects)) + "\n").encode()
        raw = subprocess.run(["git", "-C", str(repo_root), "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"], input=query, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode("utf-8", errors="replace")
        for line in raw.splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[1] == "blob":
                sizes[fields[0]] = int(fields[2])
    def directory_bytes(path: Path) -> int:
        result = subprocess.run(["du", "-sb", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return int(result.stdout.split()[0])
    return {
        "reachable_evidence_blob_count": len(sizes),
        "reachable_evidence_blob_bytes": sum(sizes.values()),
        "history_only_evidence_blob_bytes_upper_bound": sum(size for oid, size in sizes.items() if oid not in current_oids),
        "history_rewrite_savings_without_rewrite": 0,
        "git_dir_bytes": directory_bytes(repo_root / ".git"),
        "git_objects_bytes": directory_bytes(repo_root / ".git" / "objects"),
        "history_rewrite_performed": False,
        "history_rewrite_commands_used": [],
    }


def build_audit(repo_root: Path = REPO_ROOT, evidence_root: Path = DEFAULT_EVIDENCE_ROOT, *, include_history: bool = True, generated_at: str | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    evidence_root = evidence_root.resolve()
    absolute_paths = {path.relative_to(repo_root).as_posix(): path for path in iter_regular_files(evidence_root)}
    statuses = git_path_sets(repo_root, evidence_root)
    reference_map = scan_references(repo_root, absolute_paths)
    journal_map, journal_meta, unresolved_sessions = inspect_journals(absolute_paths, absolute_paths)
    records: list[dict[str, Any]] = []
    for relative, path in sorted(absolute_paths.items()):
        status = next((state for state in ("tracked", "untracked", "ignored") if relative in statuses[state]), "unknown")
        digest, size = sha256_stream(path)
        refs = reference_map.get(relative, [])
        journal_refs = journal_map.get(relative, [])
        session = _session_name(relative)
        retention, protected = classify_retention(relative=relative, status=status, session=session, reference_entries=refs, journal_entries=journal_refs, journal_meta=journal_meta.get(relative), unresolved_session=session in unresolved_sessions)
        records.append({
            "relative_path": relative, "size": size, "sha256": digest, "git_status": status, "session_name": session,
            "file_type": _file_type(path), "referenced_by_tracked_text": refs,
            "referenced_by_action_journal_or_reconciliation": journal_refs, "duplicate_group": None,
            "retention_class": retention, "protected": protected,
            "proposed_action": "RETAIN_TRACKED" if status == "tracked" else "RETAIN_PROTECTED" if protected else "RETAIN_LOCAL_UNTRACKED",
            "estimated_recoverable_bytes": 0, "journal_metadata": journal_meta.get(relative),
            "tracked_historical_only": status == "tracked" and not refs and not journal_refs and not protected,
        })
    duplicate_groups = group_duplicates(records)
    duplicate_summaries = []
    for digest, group in duplicate_groups.items():
        tracked_group = [record for record in group if record["git_status"] == "tracked"]
        protected_group = [record for record in group if record["protected"]]
        canonical = str(sorted(tracked_group or protected_group or group, key=lambda item: str(item["relative_path"]))[0]["relative_path"])
        for record in group:
            record["duplicate_group"] = digest
            record["duplicate_group_size"] = len(group)
            record["duplicate_canonical"] = canonical
            if record["relative_path"] == canonical or record["git_status"] not in {"untracked", "ignored"} or record["file_type"] in {"sqlite3", "sqlite3-wal", "sqlite3-shm"}:
                continue
            record["retention_class"] = "TRANSFER_COPY" if _is_transfer(record["relative_path"]) else "REPEATED_IDENTICAL_FRAME" if record["file_type"] == "image/png" else "EXACT_DUPLICATE"
            record["proposed_action"] = "ARCHIVE_AND_REMOVE_DUPLICATE"
            record["estimated_recoverable_bytes"] = record["size"]
        duplicate_summaries.append({
            "sha256": digest, "file_count": len(group), "total_bytes": sum(int(record["size"]) for record in group),
            "recoverable_bytes": sum(int(record["estimated_recoverable_bytes"]) for record in group), "canonical_path": canonical,
            "paths": [str(record["relative_path"]) for record in group],
        })
    status_totals = {}
    for status in ("tracked", "untracked", "ignored", "unknown"):
        selected = [record for record in records if record["git_status"] == status]
        status_totals[status] = {"files": len(selected), "bytes": sum(int(record["size"]) for record in selected)}
    retention_totals = {}
    for retention in RETENTION_CLASSES:
        selected = [record for record in records if record["retention_class"] == retention]
        retention_totals[retention] = {"files": len(selected), "bytes": sum(int(record["size"]) for record in selected), "recoverable_bytes": sum(int(record["estimated_recoverable_bytes"]) for record in selected)}
    session_totals = {}
    for session in sorted({record["session_name"] for record in records}):
        selected = [record for record in records if record["session_name"] == session]
        session_totals[session] = {"files": len(selected), "bytes": sum(int(record["size"]) for record in selected)}
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA, "generated_at_utc": generated_at, "repository_root": ".",
        "evidence_root": evidence_root.relative_to(repo_root).as_posix(), "excluded_roots": [LOCAL_REFERENCE_NAME],
        "retention_classes": list(RETENTION_CLASSES), "git_status_totals": status_totals,
        "retention_totals": retention_totals, "session_totals": session_totals,
        "duplicate_group_count": len(duplicate_summaries), "duplicate_file_count": sum(int(group["file_count"]) for group in duplicate_summaries),
        "duplicate_total_bytes": sum(int(group["total_bytes"]) for group in duplicate_summaries),
        "estimated_active_checkout_savings_bytes": sum(int(record["estimated_recoverable_bytes"]) for record in records),
        "estimated_git_history_savings_without_rewrite_bytes": 0,
        "largest_files": sorted(records, key=lambda record: (-int(record["size"]), record["relative_path"]))[:20],
        "largest_duplicate_groups": sorted(duplicate_summaries, key=lambda group: (-int(group["recoverable_bytes"]), group["sha256"]))[:20],
        "history": _history_report(repo_root) if include_history else {"history_not_run": True}, "records": records,
    }
    stable = json.dumps({key: value for key, value in audit.items() if key != "generated_at_utc"}, sort_keys=True, separators=(",", ":")).encode()
    audit["audit_id"] = hashlib.sha256(stable).hexdigest()[:20]
    return audit


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_audit_outputs(audit: Mapping[str, Any], audit_path: Path = DEFAULT_AUDIT_PATH, summary_path: Path = DEFAULT_SUMMARY_PATH) -> None:
    _write_json(audit_path, audit)
    status, classes, history = audit["git_status_totals"], audit["retention_totals"], audit.get("history", {})
    lines = [
        "# Evidence retention report", "", f"Audit `{audit['audit_id']}`; generated {audit['generated_at_utc']}. The JSON detail is local output at `artifacts/evidence-audit.json` and is intentionally not stored under `evidence/`.",
        "", "This report is a dry-run inventory. No evidence was moved or deleted by the audit.", "", "## Current footprint", "", "| Git state | Files | Bytes |", "|---|---:|---:|",
    ]
    for key in ("tracked", "untracked", "ignored", "unknown"):
        lines.append(f"| {key} | {status[key]['files']} | {status[key]['bytes']:,} |")
    lines.extend([
        f"| **evidence total** | {sum(item['files'] for item in status.values())} | {sum(item['bytes'] for item in status.values()):,} |", "",
        f"Estimated safe duplicate-compaction recovery: **{audit['estimated_active_checkout_savings_bytes']:,} bytes**. Git history savings without a history rewrite: **0 bytes**.", "",
        "## Retention totals", "", "| Retention class | Files | Bytes | Candidate recovery |", "|---|---:|---:|---:|",
    ])
    for key in RETENTION_CLASSES:
        item = classes[key]
        if item["files"]:
            lines.append(f"| `{key}` | {item['files']} | {item['bytes']:,} | {item['recoverable_bytes']:,} |")
    lines.extend(["", "## Largest files", "", "| Bytes | Git state | Retention | Path |", "|---:|---|---|---|"])
    for item in audit["largest_files"]:
        lines.append(f"| {item['size']:,} | {item['git_status']} | `{item['retention_class']}` | `{item['relative_path']}` |")
    lines.extend(["", "## Largest duplicate groups", "", "| Recoverable bytes | Files | Total bytes | Canonical path | SHA-256 |", "|---:|---:|---:|---|---|"])
    for group in audit["largest_duplicate_groups"]:
        lines.append(f"| {group['recoverable_bytes']:,} | {group['file_count']} | {group['total_bytes']:,} | `{group['canonical_path']}` | `{group['sha256']}` |")
    lines.extend([
        "", "## Git history", "",
        f"Reachable evidence blobs: {history.get('reachable_evidence_blob_count', 'not measured')} totaling {history.get('reachable_evidence_blob_bytes', 'not measured'):,} bytes." if isinstance(history.get("reachable_evidence_blob_bytes"), int) else "Reachable evidence blob size was not measured.",
        f"Current `.git` directory: {history.get('git_dir_bytes', 'not measured'):,} bytes; object database: {history.get('git_objects_bytes', 'not measured'):,} bytes." if isinstance(history.get('git_dir_bytes'), int) else "Current `.git` size was not measured.",
        f"Potential history-only evidence blob upper bound: {history.get('history_only_evidence_blob_bytes_upper_bound', 'not measured'):,} bytes." if isinstance(history.get("history_only_evidence_blob_bytes_upper_bound"), int) else "Potential history-only evidence blob size was not measured.",
        "No history rewrite, reflog expiration, repack, or destructive cleanup was performed.", "", "## Operating rule", "",
        "Use `python3 scripts/evidence_hygiene.py plan` for a dry-run candidate list. Use `archive --archive-root <external-path> --execute` only after reviewing the manifest; the tool verifies every content-addressed blob before removing an untracked or ignored duplicate. Tracked, referenced, fixture, runtime-template, decisive, unresolved, and journal artifacts remain protected.", "",
        "Policy: [`docs/evidence-retention-policy.md`](evidence-retention-policy.md).",
    ])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_audit(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != AUDIT_SCHEMA:
        raise HygieneError(f"unsupported audit schema in {path}")
    return value


def archive_blob_path(archive_root: Path, digest: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HygieneError(f"invalid SHA-256 for archive blob: {digest}")
    return archive_root / "blobs" / digest


def _assert_external_archive(repo_root: Path, archive_root: Path) -> Path:
    archive_root = archive_root.absolute()
    repo_root = repo_root.resolve()
    if archive_root == repo_root or repo_root in archive_root.parents:
        raise HygieneError("archive root must be outside the repository")
    if LOCAL_REFERENCE_NAME in archive_root.parts:
        raise HygieneError("archive root may not be inside local reference material")
    return archive_root


def _copy_and_verify(source: Path, destination: Path, digest: str, expected_size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        found, size = sha256_stream(destination)
        if found != digest or size != expected_size:
            raise HygieneError(f"archive blob does not verify: {destination}")
        return
    temporary = destination.with_name(destination.name + ".tmp")
    before = source.stat(follow_symlinks=False)
    with source.open("rb") as source_handle, temporary.open("wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=CHUNK_SIZE)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    after = source.stat(follow_symlinks=False)
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        temporary.unlink(missing_ok=True)
        raise ConcurrentChangeError(f"file changed while archiving: {source}")
    os.replace(temporary, destination)
    found, size = sha256_stream(destination)
    if found != digest or size != expected_size:
        raise HygieneError(f"copied archive blob failed verification: {destination}")


def _manifest_path(archive_root: Path, audit: Mapping[str, Any]) -> Path:
    return archive_root / "manifests" / f"operation-{audit['audit_id']}.json"


def archive_audit(audit: Mapping[str, Any], repo_root: Path, archive_root: Path, *, execute: bool = False) -> dict[str, Any]:
    archive_root = _assert_external_archive(repo_root, archive_root)
    candidates = sorted((record for record in audit["records"] if record.get("proposed_action") == "ARCHIVE_AND_REMOVE_DUPLICATE"), key=lambda record: str(record["relative_path"]))
    manifest_path = _manifest_path(archive_root, audit)
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    results = {item["relative_path"]: item for item in (existing or {}).get("entries", [])}
    operation: dict[str, Any] = {"schema": "evidence-archive-operation-v1", "audit_id": audit["audit_id"], "dry_run": not execute, "archive_root": str(archive_root), "entries": [results[path] for path in sorted(results)]}
    if not execute:
        operation["entries"] = [{"relative_path": record["relative_path"], "sha256": record["sha256"], "size": record["size"], "blob": str(archive_blob_path(archive_root, record["sha256"])), "status": "planned"} for record in candidates]
        return operation
    archive_root.mkdir(parents=True, exist_ok=True)
    for record in candidates:
        relative = str(record["relative_path"])
        if relative in _nul_paths(_run_git(repo_root, ["ls-files", "-z", "--", relative])):
            raise HygieneError(f"planned duplicate became tracked; refusing removal: {relative}")
        source = repo_root / relative
        if relative in results and results[relative].get("status") == "source_removed":
            continue
        if not source.exists():
            if relative in results and results[relative].get("status") == "archived_verified":
                continue
            raise HygieneError(f"planned source is missing before archive: {source}")
        if source.is_symlink() or not source.is_file():
            raise SymlinkSafetyError(f"planned archive source is not a regular file: {source}")
        current_digest, current_size = sha256_stream(source)
        if current_digest != record["sha256"] or current_size != int(record["size"]):
            raise ConcurrentChangeError(f"planned source changed since audit: {source}")
        blob = archive_blob_path(archive_root, current_digest)
        _copy_and_verify(source, blob, current_digest, current_size)
        entry = {"relative_path": relative, "sha256": current_digest, "size": current_size, "blob": str(blob), "status": "archived_verified"}
        results[relative] = entry
        operation["entries"] = [results[path] for path in sorted(results)]
        _write_json(manifest_path, operation)
        path_index = archive_root / "path-index.json"
        index = json.loads(path_index.read_text(encoding="utf-8")) if path_index.exists() else {}
        index[relative] = {"sha256": current_digest, "size": current_size, "blob": str(blob), "manifest": str(manifest_path)}
        _write_json(path_index, dict(sorted(index.items())))
        if sha256_stream(source) != (current_digest, current_size):
            raise ConcurrentChangeError(f"planned source changed before removal: {source}")
        source.unlink()
        entry["status"] = "source_removed"
        operation["entries"] = [results[path] for path in sorted(results)]
        _write_json(manifest_path, operation)
    return operation


def verify_archive(archive_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    archive_root = archive_root.absolute()
    manifests = [manifest_path] if manifest_path else sorted((archive_root / "manifests").glob("operation-*.json"))
    checked, errors = 0, []
    for manifest in manifests:
        operation = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in operation.get("entries", []):
            blob = Path(entry["blob"])
            if not blob.is_absolute():
                blob = archive_root / blob
            try:
                digest, size = sha256_stream(blob)
            except (OSError, HygieneError) as exc:
                errors.append(f"{manifest}: {entry.get('relative_path')}: {exc}")
                continue
            checked += 1
            if digest != entry["sha256"] or size != int(entry["size"]):
                errors.append(f"{manifest}: {entry.get('relative_path')}: blob mismatch")
    result = {"archive_root": str(archive_root), "manifests": len(manifests), "blobs_checked": checked, "errors": errors, "verified": not errors}
    if errors:
        raise HygieneError(json.dumps(result, sort_keys=True))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit", help="stream a full evidence audit")
    audit_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    audit_parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    audit_parser.add_argument("--output", type=Path, default=DEFAULT_AUDIT_PATH)
    audit_parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    audit_parser.add_argument("--no-history", action="store_true")
    plan_parser = sub.add_parser("plan", help="print the dry-run compaction plan")
    plan_parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    plan_parser.add_argument("--json", action="store_true")
    archive_parser = sub.add_parser("archive", help="archive planned files; dry-run unless --execute is explicit")
    archive_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    archive_parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    archive_parser.add_argument("--archive-root", type=Path, required=True)
    archive_parser.add_argument("--execute", action="store_true", help="verify, archive, and then remove planned duplicates")
    verify_parser = sub.add_parser("verify", help="verify external archive blobs and manifests")
    verify_parser.add_argument("--archive-root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            audit = build_audit(args.repo_root, args.evidence_root, include_history=not args.no_history)
            write_audit_outputs(audit, args.output, args.summary)
            print(json.dumps({"audit": str(args.output), "summary": str(args.summary), "audit_id": audit["audit_id"], "files": len(audit["records"]), "active_checkout_savings_bytes": audit["estimated_active_checkout_savings_bytes"]}, sort_keys=True))
        elif args.command == "plan":
            audit = _load_audit(args.audit)
            plan = [record for record in audit["records"] if record.get("proposed_action") == "ARCHIVE_AND_REMOVE_DUPLICATE"]
            print(json.dumps({"audit_id": audit["audit_id"], "dry_run": True, "candidate_count": len(plan), "candidate_bytes": sum(int(item["size"]) for item in plan), "candidates": plan}, indent=2 if args.json else None, sort_keys=True))
        elif args.command == "archive":
            operation = archive_audit(_load_audit(args.audit), args.repo_root.resolve(), args.archive_root, execute=args.execute)
            print(json.dumps({"dry_run": operation["dry_run"], "archive_root": operation["archive_root"], "entries": len(operation["entries"]), "bytes": sum(int(item["size"]) for item in operation["entries"])}, sort_keys=True))
        else:
            print(json.dumps(verify_archive(args.archive_root, args.manifest), sort_keys=True))
        return 0
    except (HygieneError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"evidence_hygiene: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
