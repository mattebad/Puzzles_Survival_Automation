#!/usr/bin/env python3
"""Single-use delegated runtime receipts consumed by ``pnsctl`` development commands.

A receipt binds one reconnaissance or canary run to an exact clean candidate commit, command,
scenario, input budget and action bindings.  This module never executes gameplay input itself.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class DelegatedReceiptError(RuntimeError):
    """Raised when a delegated runtime receipt fails closed."""


DELEGATED_RECEIPT_SCHEMA_VERSION = 1
DEFAULT_DELEGATED_RECEIPT_STATE_PATH = (
    REPO_ROOT / ".local-orchestrator" / "delegated-runtime-receipts.sqlite3"
)
DELEGATED_RECEIPT_CLASSES = frozenset({"reconnaissance", "canary"})
SUPPORTED_DELEGATED_TERMINAL_STATES = frozenset(
    {"completed", "blocked", "failed", "evidence_required", "dry_run", "observed"}
)
RECONNAISSANCE_ACTION_CLASSES = frozenset({"observation", "navigation"})
RECONNAISSANCE_FORBIDDEN_MARKERS = frozenset(
    {
        "purchase",
        "claim",
        "craft",
        "donation",
        "upgrade",
        "resource",
        "item-use",
        "item_use",
        "march",
        "combat",
        "premium",
        "real-money",
        "cash-mall",
    }
)
RESOURCE_ACTION_MARKERS = frozenset(
    {
        "resource",
        "item-use",
        "item_use",
        "premium",
        "currency",
        "claim",
        "craft",
        "donation",
        "enhancer",
        "enhancement-use",
    }
)
COMBAT_ACTION_MARKERS = frozenset(
    {"combat", "march", "attack", "battle", "dispatch", "confirmation"}
)

def _delegated_error(message: str) -> DelegatedReceiptError:
    return DelegatedReceiptError(f"delegated receipt denied: {message}")

def _git_content_fingerprint(repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise _delegated_error("Git content inventory is unavailable") from exc
    if result.returncode:
        raise _delegated_error("Git content inventory failed")
    entries: list[dict[str, str]] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _delegated_error("Git content inventory contains invalid UTF-8") from exc
        candidate = repo_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise _delegated_error(f"tracked candidate is not a regular file: {relative}")
        entries.append(
            {
                "path": relative.replace("\\", "/"),
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
        )
    return _canonical_digest({"schema_version": 1, "files": entries})

def _git_status(repo_root: Path = REPO_ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise _delegated_error("Git status is unavailable")
    return [line for line in result.stdout.splitlines() if line.strip()]

def _canonical_argv(argv: Sequence[str]) -> list[str]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise _delegated_error("canonical pnsctl argv is required")
    values = [str(item) for item in argv]
    if any(not value for value in values):
        raise _delegated_error("canonical pnsctl argv is malformed")
    if values[0] != "development-session":
        raise _delegated_error("receipt command must be beneath development-session")
    return values

def _require_receipt_list(
    value: Any,
    field: str,
    *,
    allow_duplicates: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not value or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise _delegated_error(f"{field} must be a non-empty string list")
    if not allow_duplicates and len(set(value)) != len(value):
        raise _delegated_error(f"{field} must not contain duplicates")
    return list(value)


def _action_bindings(
    identities: Sequence[str],
    classes: Sequence[str],
    consequence_class: str,
    supplied: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    def flags(identity: str, action_class: str) -> dict[str, bool]:
        text = f"{identity} {action_class} {consequence_class}".lower().replace("_", "-")
        return {
            "resource_affecting": any(marker in text for marker in RESOURCE_ACTION_MARKERS),
            "combat_confirmation": any(marker in text for marker in COMBAT_ACTION_MARKERS),
        }

    if supplied is None:
        if len(identities) != len(classes):
            raise _delegated_error("action identities and classes require exact pairings")
        supplied = [
            {
                "action_identity": identity,
                "action_class": action_class,
                "consequence_class": consequence_class,
                **flags(identity, action_class),
            }
            for identity, action_class in zip(identities, classes)
        ]
    result: list[dict[str, Any]] = []
    for binding in supplied:
        if not isinstance(binding, Mapping):
            raise _delegated_error("action binding must be an object")
        required = {"action_identity", "action_class", "consequence_class", "resource_affecting", "combat_confirmation"}
        if set(binding) != required:
            raise _delegated_error("action binding schema mismatch")
        if any(not isinstance(binding[field], str) or not binding[field].strip()
               for field in ("action_identity", "action_class", "consequence_class")):
            raise _delegated_error("action binding identity or class is empty")
        if any(type(binding[field]) is not bool for field in ("resource_affecting", "combat_confirmation")):
            raise _delegated_error("action binding budget flags must be boolean")
        binding_text = (
            f"{binding['action_identity']} {binding['action_class']} "
            f"{binding['consequence_class']}"
        ).lower().replace("_", "-")
        if any(
            marker in binding_text for marker in ("enhancer", "enhancement-use")
        ) and not binding["resource_affecting"]:
            raise _delegated_error("resource-affecting action binding cannot weaken classification")
        result.append(dict(binding))
    if not result or len({item["action_identity"] for item in result}) != len(result):
        raise _delegated_error("action bindings must be unique and non-empty")
    expected_pairs = list(zip(identities, classes))
    actual_pairs = [
        (item["action_identity"], item["action_class"]) for item in result
    ]
    if actual_pairs != expected_pairs:
        raise _delegated_error("action lists do not match exact bindings")
    return result


def _validate_delegated_receipt(receipt: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "receipt_id",
        "task_id",
        "flow_id",
        "receipt_class",
        "agent_identity",
        "repository_head",
        "working_tree_fingerprint",
        "command_argv",
        "scenario",
        "variant",
        "permitted_action_identities",
        "permitted_action_classes",
        "action_bindings",
        "consequence_class",
        "max_total_inputs",
        "max_resource_affecting_inputs",
        "max_combat_confirmations",
        "issued_at",
        "expires_at",
        "permitted_terminal_states",
        "evidence_result_binding",
        "frozen_candidate_fingerprint",
        "implementation_self_check_evidence",
        "independent_read_only_tester_evidence",
        "parent_integration_acceptance",
        "receipt_digest",
    }
    if set(receipt) != required or receipt.get("schema_version") != DELEGATED_RECEIPT_SCHEMA_VERSION:
        raise _delegated_error("receipt schema mismatch")
    for field in (
        "receipt_id",
        "task_id",
        "flow_id",
        "agent_identity",
        "repository_head",
        "working_tree_fingerprint",
        "scenario",
        "variant",
        "consequence_class",
        "frozen_candidate_fingerprint",
    ):
        _require_nonempty_string(receipt.get(field), f"receipt.{field}")
    if receipt["receipt_class"] not in DELEGATED_RECEIPT_CLASSES:
        raise _delegated_error("unsupported receipt class")
    _canonical_argv(receipt["command_argv"])
    _require_receipt_list(
        receipt["permitted_action_identities"], "receipt.permitted_action_identities"
    )
    _require_receipt_list(
        receipt["permitted_action_classes"],
        "receipt.permitted_action_classes",
        allow_duplicates=True,
    )
    bindings = _action_bindings(
        receipt["permitted_action_identities"],
        receipt["permitted_action_classes"],
        receipt["consequence_class"],
        receipt["action_bindings"],
    )
    _require_receipt_list(
        receipt["permitted_terminal_states"], "receipt.permitted_terminal_states"
    )
    if not set(receipt["permitted_terminal_states"]) <= SUPPORTED_DELEGATED_TERMINAL_STATES:
        raise _delegated_error("receipt terminal vocabulary is unsupported")
    for field in (
        "max_total_inputs",
        "max_resource_affecting_inputs",
        "max_combat_confirmations",
    ):
        if type(receipt[field]) is not int or receipt[field] < 0 or receipt[field] > 100:
            raise _delegated_error(f"receipt.{field} is outside the bounded range")
    if receipt["max_resource_affecting_inputs"] > receipt["max_total_inputs"]:
        raise _delegated_error("resource budget exceeds total budget")
    if receipt["max_combat_confirmations"] > receipt["max_total_inputs"]:
        raise _delegated_error("combat budget exceeds total budget")
    if receipt["receipt_class"] == "reconnaissance":
        if (
            receipt["max_total_inputs"] < 0
            or receipt["max_resource_affecting_inputs"] != 0
            or receipt["max_combat_confirmations"] != 0
            or receipt["consequence_class"] != "navigation_only"
            or not set(receipt["permitted_action_classes"]) <= RECONNAISSANCE_ACTION_CLASSES
            or any(item["resource_affecting"] or item["combat_confirmation"] for item in bindings)
        ):
            raise _delegated_error("reconnaissance capability or budget is invalid")
        forbidden = [
            item
            for item in [
                *receipt["permitted_action_identities"],
                *receipt["permitted_action_classes"],
            ]
            if any(marker in item.lower().replace("_", "-") for marker in RECONNAISSANCE_FORBIDDEN_MARKERS)
        ]
        if forbidden:
            raise _delegated_error("reconnaissance manifest contains forbidden capability")
        if any(state not in {"observed", "blocked", "failed", "evidence_required", "dry_run"} for state in receipt["permitted_terminal_states"]):
            raise _delegated_error("reconnaissance terminal state is unsupported")
    if any(
        marker in f"{receipt['permitted_action_identities']} {receipt['permitted_action_classes']} {receipt['consequence_class']}".lower().replace("_", "-")
        for marker in ("cash-mall", "real-money", "payment", "checkout")
    ):
        raise _delegated_error("real-money confirmation is unsupported")
    if receipt["receipt_class"] == "canary":
        if not receipt["implementation_self_check_evidence"]:
            raise _delegated_error("canary implementation self-check evidence is required")
        if not receipt["independent_read_only_tester_evidence"]:
            raise _delegated_error("canary independent tester evidence is required")
        if not receipt["parent_integration_acceptance"]:
            raise _delegated_error("canary parent integration acceptance is required")
    if not isinstance(receipt["evidence_result_binding"], dict):
        raise _delegated_error("evidence_result_binding must be an object")
    _require_nonempty_string(
        receipt["evidence_result_binding"].get("result_identity"),
        "receipt.evidence_result_binding.result_identity",
    )
    for field in (
        "issued_at",
        "expires_at",
    ):
        _parse_timestamp(receipt[field], f"receipt.{field}")
    if _parse_timestamp(receipt["expires_at"], "receipt.expires_at") <= _parse_timestamp(
        receipt["issued_at"], "receipt.issued_at"
    ):
        raise _delegated_error("receipt expiration must follow issuance")
    unsigned = dict(receipt)
    digest = unsigned.pop("receipt_digest")
    if digest != _canonical_digest(unsigned):
        raise _delegated_error("receipt digest mismatch")


class DelegatedRuntimeReceiptController:
    def __init__(
        self,
        state_path: Path = DEFAULT_DELEGATED_RECEIPT_STATE_PATH,
        *,
        repo_root: Path = REPO_ROOT,
        now: Any = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.repo_root = Path(repo_root)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _connection(self) -> sqlite3.Connection:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.state_path), timeout=0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delegated_receipts (
                receipt_id TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                consumed_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delegated_reservations (
                receipt_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                action_identity TEXT NOT NULL,
                action_class TEXT NOT NULL,
                consequence_class TEXT NOT NULL,
                source_evidence_hash TEXT,
                action_key TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(receipt_id, ordinal)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delegated_results (
                receipt_id TEXT PRIMARY KEY,
                result_identity TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(delegated_reservations)")}
        for name in ("resource_affecting", "combat_confirmation"):
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE delegated_reservations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                )
        return connection

    def _candidate(self) -> tuple[str, str]:
        status = _git_status(self.repo_root)
        managed = self.state_path.resolve()
        dirty: list[str] = []
        for line in status:
            raw = line[3:].split(" -> ")[-1].strip('"')
            candidate = (self.repo_root / raw).resolve()
            if candidate != managed:
                dirty.append(line)
        if dirty:
            raise _delegated_error("candidate worktree is dirty or has untracked files")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if head.returncode or not head.stdout.strip():
            raise _delegated_error("candidate HEAD is unavailable")
        return head.stdout.strip(), _git_content_fingerprint(self.repo_root)

    def _assert_receipt_candidate(self, receipt: Mapping[str, Any]) -> None:
        head, fingerprint = self._candidate()
        if receipt["repository_head"] != head or receipt["working_tree_fingerprint"] != fingerprint:
            raise _delegated_error("candidate changed while delegated ownership was held")

    def issue(
        self,
        *,
        task_id: str,
        flow_id: str,
        receipt_class: str,
        agent_identity: str,
        command_argv: Sequence[str],
        scenario: str,
        variant: str,
        permitted_action_identities: Sequence[str],
        permitted_action_classes: Sequence[str],
        action_bindings: Sequence[Mapping[str, Any]] | None = None,
        consequence_class: str,
        max_total_inputs: int,
        max_resource_affecting_inputs: int,
        max_combat_confirmations: int,
        permitted_terminal_states: Sequence[str],
        result_identity: str,
        expires_in_seconds: float = 900.0,
        repository_head: str | None = None,
        working_tree_fingerprint: str | None = None,
        implementation_self_check_evidence: Any = "",
        independent_read_only_tester_evidence: Any = "",
        parent_integration_acceptance: Any = "",
        frozen_candidate_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        candidate_head, candidate_fingerprint = self._candidate()
        if repository_head is not None and repository_head != candidate_head:
            raise _delegated_error("frozen HEAD does not match the clean candidate")
        if working_tree_fingerprint is not None and working_tree_fingerprint != candidate_fingerprint:
            raise _delegated_error("frozen candidate fingerprint does not match the clean candidate")
        if frozen_candidate_fingerprint is not None and frozen_candidate_fingerprint != candidate_fingerprint:
            raise _delegated_error("frozen candidate fingerprint does not match the clean candidate")
        if receipt_class not in DELEGATED_RECEIPT_CLASSES:
            raise _delegated_error("unsupported receipt class")
        if not isinstance(expires_in_seconds, (int, float)) or not 0 < expires_in_seconds <= 86400:
            raise _delegated_error("expiration must be between zero and 86400 seconds")
        issued = self.now().astimezone(timezone.utc)
        raw_action_classes = list(permitted_action_classes)
        unsigned: dict[str, Any] = {
            "schema_version": DELEGATED_RECEIPT_SCHEMA_VERSION,
            "receipt_id": str(uuid.uuid4()),
            "task_id": _require_nonempty_string(task_id, "task_id"),
            "flow_id": _require_nonempty_string(flow_id, "flow_id"),
            "receipt_class": receipt_class,
            "agent_identity": _require_nonempty_string(agent_identity, "agent_identity"),
            "repository_head": repository_head or candidate_head,
            "working_tree_fingerprint": working_tree_fingerprint or candidate_fingerprint,
            "command_argv": _canonical_argv(command_argv),
            "scenario": _require_nonempty_string(scenario, "scenario"),
            "variant": _require_nonempty_string(variant, "variant"),
            "permitted_action_identities": list(permitted_action_identities),
            "permitted_action_classes": raw_action_classes,
            "consequence_class": _require_nonempty_string(consequence_class, "consequence_class"),
            "max_total_inputs": max_total_inputs,
            "max_resource_affecting_inputs": max_resource_affecting_inputs,
            "max_combat_confirmations": max_combat_confirmations,
            "issued_at": issued.isoformat().replace("+00:00", "Z"),
            "expires_at": (issued + timedelta(seconds=expires_in_seconds)).isoformat().replace("+00:00", "Z"),
            "permitted_terminal_states": list(permitted_terminal_states),
            "evidence_result_binding": {"result_identity": _require_nonempty_string(result_identity, "result_identity")},
            "frozen_candidate_fingerprint": frozen_candidate_fingerprint or (working_tree_fingerprint or candidate_fingerprint),
            "implementation_self_check_evidence": implementation_self_check_evidence,
            "independent_read_only_tester_evidence": independent_read_only_tester_evidence,
            "parent_integration_acceptance": parent_integration_acceptance,
        }
        unsigned["action_bindings"] = _action_bindings(
            unsigned["permitted_action_identities"],
            raw_action_classes,
            consequence_class,
            action_bindings,
        )
        unsigned["receipt_digest"] = _canonical_digest(unsigned)
        _validate_delegated_receipt(unsigned)
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT receipt_id, payload_json FROM delegated_receipts WHERE status='issued'"
            ).fetchone()
            if active:
                active_payload = json.loads(active[1])
                if _parse_timestamp(active_payload["expires_at"], "receipt.expires_at") <= self.now().astimezone(timezone.utc):
                    connection.execute(
                        "UPDATE delegated_receipts SET status='expired' WHERE receipt_id=?",
                        (active[0],),
                    )
                else:
                    raise _delegated_error("another receipt is already issued")
            connection.execute(
                "INSERT INTO delegated_receipts VALUES (?, ?, ?, 'issued', ?, NULL)",
                (
                    unsigned["receipt_id"],
                    unsigned["receipt_digest"],
                    json.dumps(unsigned, sort_keys=True),
                    unsigned["issued_at"],
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        return deepcopy(unsigned)

    def inspect(self, receipt_id: str | None = None) -> dict[str, Any]:
        connection = self._connection()
        try:
            query = (
                "SELECT receipt_id, payload_json, status, consumed_at FROM delegated_receipts "
                "WHERE receipt_id=?"
            )
            row = connection.execute(
                query, (receipt_id,)
            ).fetchone() if receipt_id else connection.execute(
                "SELECT receipt_id, payload_json, status, consumed_at FROM delegated_receipts ORDER BY issued_at DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise _delegated_error("receipt is unavailable")
        payload = json.loads(row[1])
        _validate_delegated_receipt(payload)
        if row[2] == "issued" and _parse_timestamp(payload["expires_at"], "receipt.expires_at") <= self.now().astimezone(timezone.utc):
            row = (row[0], row[1], "expired", row[3])
        return {
            "receipt": payload,
            "receipt_id": row[0],
            "status": row[2],
            "consumed_at": row[3],
        }

    def consume(
        self,
        receipt_id: str,
        *,
        agent_identity: str,
        task_id: str,
        flow_id: str,
        receipt_class: str,
        command_argv: Sequence[str],
        scenario: str,
        variant: str,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (receipt_id, agent_identity, task_id, flow_id, receipt_class, scenario, variant)
        ):
            raise _delegated_error("all consume bindings are required")
        candidate_head, candidate_fingerprint = self._candidate()
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT receipt_id, digest, payload_json, status, consumed_at FROM delegated_receipts "
                "WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if row is None:
                raise _delegated_error("receipt is unavailable")
            payload = json.loads(row[2])
            _validate_delegated_receipt(payload)
            if row[3] != "issued":
                raise _delegated_error("receipt was already consumed or expired")
            if payload["repository_head"] != candidate_head:
                raise _delegated_error("candidate HEAD changed after issuance")
            if payload["working_tree_fingerprint"] != candidate_fingerprint:
                raise _delegated_error("candidate content fingerprint changed after issuance")
            now = self.now().astimezone(timezone.utc)
            if _parse_timestamp(payload["expires_at"], "receipt.expires_at") <= now:
                connection.execute(
                    "UPDATE delegated_receipts SET status='expired' WHERE receipt_id=?",
                    (row[0],),
                )
                raise _delegated_error("receipt is expired")
            checks = {
                "agent_identity": agent_identity,
                "task_id": task_id,
                "flow_id": flow_id,
                "receipt_class": receipt_class,
                "scenario": scenario,
                "variant": variant,
            }
            checks["command_argv"] = _canonical_argv(command_argv)
            checks.update(expected or {})
            for field, value in checks.items():
                if payload.get(field) != value:
                    raise _delegated_error(f"{field} does not match the receipt")
            consumed_at = now.isoformat().replace("+00:00", "Z")
            connection.execute(
                "UPDATE delegated_receipts SET status='consumed', consumed_at=? WHERE receipt_id=? AND status='issued'",
                (consumed_at, row[0]),
            )
            if connection.total_changes != 1:
                raise _delegated_error("receipt consumption race")
            connection.execute("COMMIT")
            return payload
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def reserve_input(
        self,
        receipt: Mapping[str, Any],
        *,
        action_identity: str,
        action_class: str,
        consequence_class: str,
        source_evidence_hash: str | None = None,
        action_key: str | None = None,
    ) -> dict[str, Any]:
        _validate_delegated_receipt(receipt)
        self._assert_receipt_candidate(receipt)
        if not action_identity or not action_class or not consequence_class:
            raise _delegated_error("reservation identity and classes are required")
        if action_identity not in receipt["permitted_action_identities"]:
            raise _delegated_error("action identity is outside the receipt manifest")
        if action_class not in receipt["permitted_action_classes"]:
            raise _delegated_error("action class is outside the receipt manifest")
        binding = next(
            (
                item
                for item in receipt["action_bindings"]
                if item["action_identity"] == action_identity
                and item["action_class"] == action_class
                and item["consequence_class"] == consequence_class
            ),
            None,
        )
        if binding is None:
            raise _delegated_error("action binding does not match the receipt manifest")
        resource = bool(binding["resource_affecting"])
        combat = bool(binding["combat_confirmation"])
        connection = self._connection()
        now = self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT 1 FROM delegated_reservations WHERE receipt_id=? AND status IN ('reserved','input_sent','unresolved') LIMIT 1",
                (receipt["receipt_id"],),
            ).fetchone()
            if unresolved:
                raise _delegated_error("an unresolved reservation blocks further input")
            duplicate = connection.execute(
                "SELECT 1 FROM delegated_reservations WHERE receipt_id=? AND action_identity=?",
                (receipt["receipt_id"], action_identity),
            ).fetchone()
            if duplicate:
                raise _delegated_error("identical action retry is forbidden")
            count = connection.execute(
                "SELECT COUNT(*) FROM delegated_reservations WHERE receipt_id=?",
                (receipt["receipt_id"],),
            ).fetchone()[0]
            resource_count = connection.execute(
                "SELECT COUNT(*) FROM delegated_reservations WHERE receipt_id=? AND resource_affecting=1",
                (receipt["receipt_id"],),
            ).fetchone()[0]
            combat_count = connection.execute(
                "SELECT COUNT(*) FROM delegated_reservations WHERE receipt_id=? AND combat_confirmation=1",
                (receipt["receipt_id"],),
            ).fetchone()[0]
            if count >= receipt["max_total_inputs"]:
                raise _delegated_error("total input budget exhausted")
            if resource and resource_count >= receipt["max_resource_affecting_inputs"]:
                raise _delegated_error("resource-affecting input budget exhausted")
            if combat and combat_count >= receipt["max_combat_confirmations"]:
                raise _delegated_error("combat-confirmation budget exhausted")
            ordinal = int(count) + 1
            connection.execute(
                "INSERT INTO delegated_reservations "
                "(receipt_id, ordinal, action_identity, action_class, consequence_class, "
                "source_evidence_hash, action_key, status, created_at, updated_at, "
                "resource_affecting, combat_confirmation) VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?)",
                (
                    receipt["receipt_id"],
                    ordinal,
                    action_identity,
                    action_class,
                    consequence_class,
                    source_evidence_hash,
                    action_key,
                    now,
                    now,
                    int(resource),
                    int(combat),
                ),
            )
            connection.execute("COMMIT")
            return {"receipt_id": receipt["receipt_id"], "ordinal": ordinal, "status": "reserved"}
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def update_reservation(
        self,
        receipt_id: str,
        ordinal: int,
        status: str,
    ) -> None:
        if status not in {"input_sent", "reconciled", "unresolved"}:
            raise _delegated_error("invalid reservation status")
        connection = self._connection()
        try:
            connection.execute(
                "UPDATE delegated_reservations SET status=?, updated_at=? WHERE receipt_id=? AND ordinal=?",
                (
                    status,
                    self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    receipt_id,
                    ordinal,
                ),
            )
        finally:
            connection.close()

    def record_result(
        self,
        receipt: Mapping[str, Any],
        *,
        status: str,
        result_identity: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        _validate_delegated_receipt(receipt)
        self._assert_receipt_candidate(receipt)
        if status not in receipt["permitted_terminal_states"]:
            raise _delegated_error("terminal state is not permitted by the receipt")
        if result_identity != receipt["evidence_result_binding"]["result_identity"]:
            raise _delegated_error("result identity does not match the receipt")
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM delegated_results WHERE receipt_id=?", (receipt["receipt_id"],)
            ).fetchone()
            if existing:
                raise _delegated_error("receipt already has a terminal result")
            if status in {"completed", "observed", "dry_run"} and connection.execute(
                "SELECT 1 FROM delegated_reservations WHERE receipt_id=? "
                "AND status IN ('reserved','input_sent','unresolved') LIMIT 1",
                (receipt["receipt_id"],),
            ).fetchone():
                raise _delegated_error("pending reservation blocks terminal success")
            if status in {"evidence_required", "failed", "blocked"}:
                connection.execute(
                    "UPDATE delegated_reservations SET status='unresolved', updated_at=? "
                    "WHERE receipt_id=? AND status IN ('reserved','input_sent')",
                    (
                        self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        receipt["receipt_id"],
                    ),
                )
            connection.execute(
                "INSERT INTO delegated_results VALUES (?, ?, ?, ?, ?)",
                (
                    receipt["receipt_id"],
                    result_identity,
                    status,
                    json.dumps(dict(payload), sort_keys=True, default=str),
                    self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        return {"receipt_id": receipt["receipt_id"], "status": status, "result_identity": result_identity}


class DelegatedRuntimeContext:
    def __init__(
        self,
        controller: DelegatedRuntimeReceiptController,
        receipt: Mapping[str, Any],
        *,
        result_identity: str,
    ) -> None:
        _validate_delegated_receipt(receipt)
        self.controller = controller
        self.receipt = dict(receipt)
        self.result_identity = result_identity
        self._reservations: dict[str, dict[str, Any]] = {}

    def reserve_input(
        self,
        *,
        action_identity: str,
        action_class: str,
        consequence_class: str,
        source_evidence_hash: str | None = None,
        action_key: str | None = None,
    ) -> dict[str, Any]:
        reservation = self.controller.reserve_input(
            self.receipt,
            action_identity=action_identity,
            action_class=action_class,
            consequence_class=consequence_class,
            source_evidence_hash=source_evidence_hash,
            action_key=action_key,
        )
        self._reservations[action_key or action_identity] = reservation
        return reservation

    def mark_transported(self, action_key: str | None) -> None:
        reservation = self._reservations.get(action_key or "")
        if reservation is not None:
            self.controller.update_reservation(
                self.receipt["receipt_id"], reservation["ordinal"], "input_sent"
            )

    def mark_reconciled(self, action_key: str | None, *, unresolved: bool = False) -> None:
        reservation = self._reservations.get(action_key or "")
        if reservation is not None:
            self.controller.update_reservation(
                self.receipt["receipt_id"],
                reservation["ordinal"],
                "unresolved" if unresolved else "reconciled",
            )

    def record_terminal(self, *, status: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.controller.record_result(
            self.receipt,
            status=status,
            result_identity=self.result_identity,
            payload=payload,
        )


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DelegatedReceiptError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DelegatedReceiptError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise DelegatedReceiptError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)



def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelegatedReceiptError(f"{field} must be a non-empty string")
    return value



def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
