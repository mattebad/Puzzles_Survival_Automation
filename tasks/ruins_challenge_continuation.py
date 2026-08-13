"""Crash-safe continuation checkpoint for chest-only Ruins runs.

The checkpoint is deliberately small and evidence-bound.  It records only claims
whose native postcondition was reconciled as ``confirmed``; a route result,
resource delta, or ``newly_claimed_chests`` list is never sufficient to create a
record.  Coordinates and UI state are intentionally absent so a resumed route
must recognize and bind every row from a fresh frame.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


FLOW_ID = "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
SCHEMA_NAME = "ruins_chest_continuation"
SCHEMA_VERSION = 1
RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
PACKAGE_ID = "com.global.ztmslg"

# Keep this tuple literal.  It is the durable contract, rather than a value
# derived from the production enum (which would make completeness tests circular).
CANONICAL_IDENTITIES: tuple[str, ...] = (
    "Hero Challenge",
    "Weapon Trial",
    "Tech Challenge",
    "Gear Challenge",
    "Core Challenge",
    "Nova Challenge",
    "Module Challenge",
    "Glory Challenge",
    "Bioenhancer Challenge",
    "Ultimate Challenge",
    "Chip Challenge",
    "Cube Challenge",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DAYS = frozenset({"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
_CLAIM_STATUS = "confirmed"


class RuinsContinuationError(ValueError):
    """Fail-closed continuation validation error."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(detail or reason)


def _digest_payload(value: Mapping[str, Any]) -> bytes:
    unsigned = {key: item for key, item in value.items() if key not in {"schema_digest", "digest"}}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def continuation_schema_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical digest for a signed (unsigned-field) checkpoint."""

    return hashlib.sha256(_digest_payload(value)).hexdigest()


# Short alias useful to callers that already use ``schema_digest`` naming.
schema_digest = continuation_schema_digest
compute_schema_digest = continuation_schema_digest
continuation_digest = continuation_schema_digest
CONTINUATION_SCHEMA_VERSION = SCHEMA_VERSION
CONTINUATION_FLOW_ID = FLOW_ID
KNOWN_CANONICAL_IDENTITIES = CANONICAL_IDENTITIES


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise RuinsContinuationError("malformed", field)
    return value


def _require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RuinsContinuationError("malformed", field)
    return value


def _evidence_root(path: Path) -> Path:
    """Infer the deterministic flow root for ``<flow>/<nav>/<session>/...``.

    A minted checkpoint stores evidence paths relative to the flow directory,
    not its child session.  Walking ancestors until the exact flow identifier
    is found makes direct reload use the same root as the writer while still
    rejecting paths outside that flow.
    """

    current = path.resolve().parent
    for ancestor in (current, *current.parents):
        if ancestor.name == FLOW_ID:
            return ancestor
    # A caller may validate an isolated fixture with an explicitly supplied
    # root; absent that contract, fail closed rather than guessing a broad root.
    raise RuinsContinuationError("artifact_path_escape", "checkpoint is outside Ruins flow root")


def _contained_path(raw: Any, root: Path, field: str) -> tuple[str, Path]:
    text = _require_text(raw, field)
    candidate = Path(text)
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuinsContinuationError("evidence_path_escape", field) from exc
    if not resolved.is_file():
        raise RuinsContinuationError("evidence_missing", field)
    # Persist stable flow-root-relative POSIX paths; never carry an absolute path
    # or a path containing a parent traversal into a continuation artifact.
    return resolved.relative_to(root).as_posix(), resolved


def _frame_fields(record: Mapping[str, Any], prefix: str) -> tuple[Any, Any]:
    path = record.get(f"{prefix}_frame_path")
    digest = record.get(f"{prefix}_frame_sha256")
    # Accept the compact event-journal spellings when importing a verified
    # reconciliation record, then normalize to the checkpoint names.
    if path is None:
        path = record.get(f"{prefix}_path")
    if digest is None:
        digest = record.get(f"{prefix}_sha256")
    nested = record.get(f"{prefix}_frame")
    if (path is None or digest is None) and isinstance(nested, Mapping):
        path = nested.get("path", path)
        digest = nested.get("sha256", digest)
    return path, digest


def _validate_claim(
    raw: Any,
    *,
    root: Path,
    expected_reset_identity: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuinsContinuationError("malformed", "claim record")
    identity = raw.get("identity")
    if identity not in CANONICAL_IDENTITIES:
        raise RuinsContinuationError("unknown_identity", str(identity))
    action_key = _require_text(raw.get("action_key"), "action_key")
    if raw.get("status") != _CLAIM_STATUS:
        raise RuinsContinuationError("unresolved_claim", identity)
    medal_delta = raw.get("medal_delta", raw.get("ruins_medals"))
    if isinstance(medal_delta, bool) or not isinstance(medal_delta, int) or medal_delta < 0:
        raise RuinsContinuationError("malformed", "medal_delta")
    claim_reset = raw.get("reset_identity", expected_reset_identity)
    if claim_reset != expected_reset_identity:
        raise RuinsContinuationError("identity_mismatch", "claim reset_identity")

    post_path, post_hash = _frame_fields(raw, "post")
    if post_path is None or post_hash is None:
        raise RuinsContinuationError("malformed", "post-frame evidence required")
    post_rel, post_abs = _contained_path(post_path, root, "post_frame_path")
    post_digest = _require_hash(post_hash, "post_frame_sha256")
    try:
        actual = hashlib.sha256(post_abs.read_bytes()).hexdigest()
    except OSError as exc:
        raise RuinsContinuationError("evidence_unreadable", "post_frame_path") from exc
    if actual != post_digest:
        raise RuinsContinuationError("evidence_hash_mismatch", "post_frame_sha256")

    normalized: dict[str, Any] = {
        "identity": identity,
        "action_key": action_key,
        "status": _CLAIM_STATUS,
        "reset_identity": expected_reset_identity,
        "medal_delta": medal_delta,
        "post_frame_path": post_rel,
        "post_frame_sha256": post_digest,
    }
    for prefix in ("source", "terminal"):
        optional_path, optional_hash = _frame_fields(raw, prefix)
        if optional_path is None and optional_hash is None:
            continue
        if optional_path is None or optional_hash is None:
            raise RuinsContinuationError("malformed", f"{prefix}-frame evidence pair")
        rel, absolute = _contained_path(optional_path, root, f"{prefix}_frame_path")
        digest = _require_hash(optional_hash, f"{prefix}_frame_sha256")
        try:
            actual = hashlib.sha256(absolute.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuinsContinuationError("evidence_unreadable", f"{prefix}_frame_path") from exc
        if actual != digest:
            raise RuinsContinuationError("evidence_hash_mismatch", f"{prefix}_frame_sha256")
        normalized[f"{prefix}_frame_path"] = rel
        normalized[f"{prefix}_frame_sha256"] = digest
    return normalized


def validate_continuation(
    value: Mapping[str, Any],
    *,
    evidence_root: Path | None = None,
    expected_flow_id: str = FLOW_ID,
    expected_reset_identity: str | None = None,
    expected_current_day: str | None = None,
    expected_runtime_profile_id: str = RUNTIME_PROFILE_ID,
    expected_package_id: str = PACKAGE_ID,
) -> dict[str, Any]:
    """Validate and normalize a continuation mapping.

    ``evidence_root`` is mandatory in practice for persisted claims; when omitted,
    the current directory is used so callers can validate in-memory fixtures with
    relative evidence paths.
    """

    if not isinstance(value, Mapping):
        raise RuinsContinuationError("malformed", "checkpoint must be an object")
    root = (evidence_root or Path.cwd()).resolve()
    required_keys = {
        "schema_name", "schema_version", "flow_id", "reset_identity", "current_day",
        "runtime_profile_id", "package_id", "canonical_identities", "claims", "schema_digest",
    }
    if set(value) - required_keys:
        raise RuinsContinuationError("malformed", "unknown checkpoint fields")
    if "schema_name" not in value or value.get("schema_name") != SCHEMA_NAME:
        raise RuinsContinuationError("schema_mismatch", "schema_name")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise RuinsContinuationError("schema_mismatch", "schema_version")
    if expected_flow_id != FLOW_ID or expected_runtime_profile_id != RUNTIME_PROFILE_ID or expected_package_id != PACKAGE_ID:
        raise RuinsContinuationError("identity_mismatch", "unsupported expected contract")
    if value.get("flow_id") != expected_flow_id:
        raise RuinsContinuationError("identity_mismatch", "flow_id")
    reset_identity = _require_text(value.get("reset_identity"), "reset_identity")
    current_day = _require_text(value.get("current_day"), "current_day")
    if current_day not in _DAYS:
        raise RuinsContinuationError("malformed", "current_day")
    runtime_profile = _require_text(value.get("runtime_profile_id"), "runtime_profile_id")
    if "package_id" not in value:
        raise RuinsContinuationError("malformed", "package_id")
    package_id = _require_text(value.get("package_id"), "package_id")
    if expected_reset_identity is not None and reset_identity != expected_reset_identity:
        raise RuinsContinuationError("identity_mismatch", "reset_identity")
    if expected_current_day is not None and current_day != expected_current_day:
        raise RuinsContinuationError("identity_mismatch", "current_day")
    if runtime_profile != expected_runtime_profile_id:
        raise RuinsContinuationError("identity_mismatch", "runtime_profile_id")
    if package_id != expected_package_id:
        raise RuinsContinuationError("identity_mismatch", "package_id")
    identities = value.get("canonical_identities")
    if identities != list(CANONICAL_IDENTITIES):
        raise RuinsContinuationError("identity_mismatch", "canonical_identities")
    supplied_digest = value.get("schema_digest", value.get("digest"))
    if _SHA256.fullmatch(supplied_digest or "") is None or supplied_digest != continuation_schema_digest(value):
        raise RuinsContinuationError("digest_mismatch", "schema_digest")
    claims = value.get("claims", value.get("confirmed_claims"))
    if not isinstance(claims, list):
        raise RuinsContinuationError("malformed", "claims")
    normalized_claims = []
    seen_identities: set[str] = set()
    seen_actions: set[str] = set()
    for raw in claims:
        claim = _validate_claim(raw, root=root, expected_reset_identity=reset_identity)
        if claim["identity"] in seen_identities or claim["action_key"] in seen_actions:
            raise RuinsContinuationError("duplicate_claim", claim["identity"])
        seen_identities.add(claim["identity"])
        seen_actions.add(claim["action_key"])
        normalized_claims.append(claim)
    normalized = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "flow_id": FLOW_ID,
        "reset_identity": reset_identity,
        "current_day": current_day,
        "runtime_profile_id": runtime_profile,
        "package_id": package_id,
        "canonical_identities": list(CANONICAL_IDENTITIES),
        "claims": normalized_claims,
    }
    normalized["schema_digest"] = continuation_schema_digest(normalized)
    return normalized


def _normalize_claim_for_build(raw: Mapping[str, Any], root: Path, reset_identity: str) -> dict[str, Any]:
    # Build uses the same strict evidence checks as load, while accepting absolute
    # paths from CapturedNativeFrame and converting them to flow-root-relative form.
    candidate = dict(raw)
    candidate.setdefault("reset_identity", reset_identity)
    return _validate_claim(candidate, root=root, expected_reset_identity=reset_identity)


def validate_claim_record(
    value: Mapping[str, Any], *, evidence_root: Path, expected_reset_identity: str
) -> dict[str, Any]:
    """Validate one confirmed claim using the checkpoint evidence contract."""

    return _validate_claim(
        value,
        root=evidence_root.resolve(),
        expected_reset_identity=expected_reset_identity,
    )


def build_continuation(
    *,
    reset_identity: str,
    current_day: str,
    claims: Iterable[Mapping[str, Any]],
    evidence_root: Path,
    flow_id: str = FLOW_ID,
    runtime_profile_id: str = RUNTIME_PROFILE_ID,
    package_id: str = PACKAGE_ID,
) -> dict[str, Any]:
    if flow_id != FLOW_ID:
        raise RuinsContinuationError("identity_mismatch", "flow_id")
    if runtime_profile_id != RUNTIME_PROFILE_ID:
        raise RuinsContinuationError("identity_mismatch", "runtime_profile_id")
    if package_id != PACKAGE_ID:
        raise RuinsContinuationError("identity_mismatch", "package_id")
    root = evidence_root.resolve()
    normalized_claims = [_normalize_claim_for_build(item, root, reset_identity) for item in claims]
    value: dict[str, Any] = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "flow_id": flow_id,
        "reset_identity": reset_identity,
        "current_day": current_day,
        "runtime_profile_id": runtime_profile_id,
        "package_id": package_id,
        "canonical_identities": list(CANONICAL_IDENTITIES),
        "claims": normalized_claims,
    }
    value["schema_digest"] = continuation_schema_digest(value)
    return validate_continuation(
        value,
        evidence_root=root,
        expected_reset_identity=reset_identity,
        expected_current_day=current_day,
        expected_runtime_profile_id=runtime_profile_id,
        expected_package_id=package_id,
    )


def write_continuation(
    path: Path,
    *,
    reset_identity: str,
    current_day: str,
    claims: Iterable[Mapping[str, Any]],
    evidence_root: Path,
    flow_id: str = FLOW_ID,
    runtime_profile_id: str = RUNTIME_PROFILE_ID,
    package_id: str = PACKAGE_ID,
) -> Path:
    """Atomically write a validated checkpoint inside the caller's capture area."""

    destination = path.resolve()
    root = evidence_root.resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise RuinsContinuationError("artifact_path_escape", str(destination)) from exc
    payload = build_continuation(
        reset_identity=reset_identity,
        current_day=current_day,
        claims=claims,
        evidence_root=root,
        flow_id=flow_id,
        runtime_profile_id=runtime_profile_id,
        package_id=package_id,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def load_continuation(
    path: Path,
    *,
    evidence_root: Path | None = None,
    expected_flow_id: str = FLOW_ID,
    expected_reset_identity: str | None = None,
    expected_current_day: str | None = None,
    expected_runtime_profile_id: str = RUNTIME_PROFILE_ID,
    expected_package_id: str = PACKAGE_ID,
) -> dict[str, Any]:
    checkpoint = path.resolve()
    root = (evidence_root or _evidence_root(checkpoint)).resolve()
    try:
        checkpoint.relative_to(root)
    except ValueError as exc:
        raise RuinsContinuationError("artifact_path_escape", str(checkpoint)) from exc
    try:
        value = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuinsContinuationError("malformed", "checkpoint unreadable") from exc
    return validate_continuation(
        value,
        evidence_root=root,
        expected_flow_id=expected_flow_id,
        expected_reset_identity=expected_reset_identity,
        expected_current_day=expected_current_day,
        expected_runtime_profile_id=expected_runtime_profile_id,
        expected_package_id=expected_package_id,
    )


def confirmed_identities(value: Mapping[str, Any]) -> frozenset[str]:
    """Return only identities represented by validated ``confirmed`` records."""

    return frozenset(claim["identity"] for claim in value.get("claims", ()) if claim.get("status") == _CLAIM_STATUS)


def confirmed_claim_records(value: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(claim for claim in value.get("claims", ()) if claim.get("status") == _CLAIM_STATUS)


def make_claim_record(
    *,
    identity: str,
    action_key: str,
    medal_delta: int,
    post_frame_path: Path | str,
    post_frame_sha256: str,
    source_frame_path: Path | str | None = None,
    source_frame_sha256: str | None = None,
    terminal_frame_path: Path | str | None = None,
    terminal_frame_sha256: str | None = None,
    reset_identity: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "identity": identity,
        "action_key": action_key,
        "status": _CLAIM_STATUS,
        "medal_delta": medal_delta,
        "post_frame_path": str(post_frame_path),
        "post_frame_sha256": post_frame_sha256,
    }
    if source_frame_path is not None or source_frame_sha256 is not None:
        record["source_frame_path"] = str(source_frame_path) if source_frame_path is not None else None
        record["source_frame_sha256"] = source_frame_sha256
    if terminal_frame_path is not None or terminal_frame_sha256 is not None:
        record["terminal_frame_path"] = str(terminal_frame_path) if terminal_frame_path is not None else None
        record["terminal_frame_sha256"] = terminal_frame_sha256
    if reset_identity is not None:
        record["reset_identity"] = reset_identity
    return record


# Compatibility names for callers that prefer explicit load/validate verbs.
validate_ruins_continuation = validate_continuation
load_ruins_continuation = load_continuation
write_ruins_continuation = write_continuation
validate_ruins_chest_continuation = validate_continuation
load_ruins_chest_continuation = load_continuation
write_ruins_chest_continuation = write_continuation
build_ruins_chest_continuation = build_continuation
