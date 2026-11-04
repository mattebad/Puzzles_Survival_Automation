"""Checked-in delivery, reservation, and evidence validation for Commander enhancement."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from automation_service.registry import ENHANCEMENT_FLOW_ID
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL
from safe_action_core.path_safety import UnsafePathError, require_no_untrusted_symlinks


FLOW_ID = ENHANCEMENT_FLOW_ID
RUNNER_ID = "enhancement_family_bluestacks_runner"
VALIDATOR_ID = "enhancement_family_bluestacks_evidence"
RECOVERY_ID = "enhancement_family_bluestacks_recovery"
MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY = 1
MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS = 3
MAX_DISPATCH_BEARING_CANARY_RUNS = MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS
MAX_DISPATCH_BEARING_CANARY_RUNS_PER_VARIANT = MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_STAMP_RE = re.compile(r"^\d{8}T\d{12}Z$")
_RETAINED_ZERO_DISPATCH_VARIANT = "gear"
_RETAINED_ZERO_DISPATCH_RESERVED_AT = "20260818T171954671861Z"
_CONFIRMED_NO_EFFECT_STATUS = "confirmed_no_effect"
_RECOVERED_NO_EFFECT_STATUS = "recovered_no_effect"
_ZERO_SELECTED_CONFIRM_PROOF = "zero_selected_confirm"
_NO_EFFECT_REPLAY_REASON = "legacy_static_selected_quantity_shortcut_rejected"
_NO_EFFECT_RECEIPT_NAME = "no-effect-recovery-receipt.json"
_POSITIVE_RECEIPT_NAME = "settled-successor-receipt.json"
_NO_EFFECT_ACCOUNTING_REFS = "accounted_no_effect_receipts"
_PRE_RUNTIME_IMPORT_FAILURE_RE = re.compile(
    r"^Traceback \(most recent call last\):\r?\n"
    r'  File "[^"\r\n]*[\\/]+scripts[\\/]+enhancement_bluestacks\.py", '
    r"line \d+, in <module>\r?\n"
    r"    from scripts\.bluestacks_native_runtime import \(\r?\n"
    r"ModuleNotFoundError: No module named 'scripts'\r?\n?$"
)


def _atomic_family_progress(path: Path, categories: Mapping[str, Any]) -> None:
    """Replace mutable progress only after the complete new document is flushed."""
    rendered = json.dumps({"schema_version": 1, "flow_id": FLOW_ID, "categories": categories},
                          indent=2, sort_keys=True, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _same_validated_path_identity(first: Any, second: Any) -> bool:
    """Compare physical path identities only after validating each raw spelling."""
    if not isinstance(first, (str, Path)) or not isinstance(second, (str, Path)):
        return False
    try:
        first_path = Path(first)
        second_path = Path(second)
        if not first_path.is_absolute() or not second_path.is_absolute():
            return False
        return (
            require_no_untrusted_symlinks(first_path).resolve()
            == require_no_untrusted_symlinks(second_path).resolve()
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


class _VerificationInterrupted(RuntimeError):
    """Keep an owner/lease fence failure distinct from unrecognized evidence."""


def _verification_checkpoint(checkpoint: Callable[[], None] | None) -> None:
    if checkpoint is None:
        return
    if not callable(checkpoint):
        raise _pnsctl().OperatorError("Enhancement verification checkpoint must be callable")
    try:
        checkpoint()
    except _VerificationInterrupted:
        raise
    except Exception as exc:
        raise _VerificationInterrupted(str(exc)) from exc


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _session_max_inputs(lease: Mapping[str, Any]) -> int:
    try:
        value = int(lease.get("max_inputs", os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", 1)))
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError("development session max_inputs is required") from exc
    if not 1 <= value <= 100:
        raise _pnsctl().OperatorError("development session max_inputs must be between 1 and 100")
    return value


def _read_event_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement event journal is missing")
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement event journal is unreadable") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _pnsctl().OperatorError("Enhancement event journal contains invalid JSON") from exc
        if not isinstance(row, dict):
            raise _pnsctl().OperatorError("Enhancement event row is not an object")
        rows.append(row)
    return rows


def _dispatch_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("type") == "dispatch"]


def _resource_dispatch_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        row
        for row in rows
        if row.get("type") == "dispatch"
        and (
            row.get("resource_affecting") is True
            or row.get("target_identity") == "enhancement-use"
        )
    ]


def _variant_from_path(path: Path) -> str | None:
    match = re.search(r"(?:run|reservation)-(?P<variant>gear|chip|module)(?:-|\.|$)", str(path), re.I)
    return match.group("variant").lower() if match else None


def _artifact_usage(flow_root: Path) -> dict[str, int]:
    usage = {variant: 0 for variant in SUPPORTED_VARIANTS}
    if not flow_root.is_dir():
        return usage
    for reservation in flow_root.glob("reservation-*.json"):
        variant = _variant_from_path(reservation)
        if variant in usage:
            usage[variant] += 1
    for events_path in flow_root.rglob("events.jsonl"):
        rows = _read_event_rows(events_path)
        if not _dispatch_rows(rows):
            continue
        result_path = events_path.parent / "flow-delivery-result.json"
        variant = None
        if result_path.is_file() and not result_path.is_symlink():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise _pnsctl().OperatorError("prior Enhancement result is unreadable") from exc
            if isinstance(result, dict):
                variant = str(result.get("variant") or "").lower()
                if variant == "family":
                    categories = result.get("enhancement_result", {}).get("category_results", [])
                    variants = {
                        str(item.get("variant") or "").lower()
                        for item in categories
                        if isinstance(item, Mapping)
                    }
                    for category in variants:
                        if category in usage and not (flow_root / f"reservation-{category}.json").is_file():
                            usage[category] += 1
                    continue
        variant = variant or _variant_from_path(events_path)
        if variant not in usage:
            raise _pnsctl().OperatorError("dispatch-bearing Enhancement artifact has no category")
        if not (flow_root / f"reservation-{variant}.json").is_file():
            usage[variant] += 1
    return usage


def _reserve(flow_root: Path, variant: str) -> Path:
    flow_root.mkdir(parents=True, exist_ok=True)
    usage = _artifact_usage(flow_root)
    if sum(usage.values()) >= MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS:
        raise _pnsctl().OperatorError("Enhancement total dispatch-bearing canary budget is exhausted")
    if usage[variant] >= MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY:
        raise _pnsctl().OperatorError(f"Enhancement {variant} dispatch-bearing canary budget is exhausted")
    path = flow_root / f"reservation-{variant}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "flow_id": FLOW_ID,
                    "variant": variant,
                    "status": "reserved",
                    "reserved_at": _stamp(),
                    "dispatch_bearing": True,
                },
                handle,
                sort_keys=True,
            )
            handle.write("\n")
    except FileExistsError as exc:
        raise _pnsctl().OperatorError(
            f"Enhancement {variant} has an unresolved canary reservation"
        ) from exc
    return path


def _require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise _pnsctl().OperatorError(f"Enhancement {field} hash is invalid")
    return value


def _decode_native(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement retained frame is not a regular file")
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement retained frame is unreadable") from exc
    digest = hashlib.sha256(raw).hexdigest()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (1280, 800):
        raise _pnsctl().OperatorError("Enhancement retained frame is not a native 800x1280 PNG")
    return digest


def _retained_path(session: Path, reference: str, field: str) -> Path:
    """Join and validate a retained reference before resolving it."""
    raw = Path(reference)
    if not raw.is_absolute():
        raw = session / raw
    try:
        safe_session = require_no_untrusted_symlinks(session)
        safe_raw = require_no_untrusted_symlinks(raw)
    except UnsafePathError as exc:
        raise _pnsctl().OperatorError(
            f"Enhancement {field} reference contains a symlink"
        ) from exc
    try:
        resolved = safe_raw.resolve()
        resolved.relative_to(safe_session.resolve())
    except ValueError as exc:
        raise _pnsctl().OperatorError(f"Enhancement {field} reference escaped session") from exc
    if resolved.is_symlink():
        raise _pnsctl().OperatorError(f"Enhancement {field} reference resolves through a symlink")
    return resolved


def _validate_zero_dispatch_nested_result(nested_root: Path, *, variant: str) -> None:
    """Accept only the immutable, native, capture-only retained child session."""

    if nested_root.is_symlink() or not nested_root.is_dir():
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch session is malformed")
    if {child.name for child in nested_root.iterdir()} != {"events.jsonl", "frames", "result.json"}:
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch session has unexpected artifacts")
    frames = nested_root / "frames"
    if frames.is_symlink() or not frames.is_dir():
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch frame directory is malformed")
    frame_paths = sorted(frames.glob("*.png"))
    if not frame_paths or any(path.is_symlink() or not path.is_file() for path in frame_paths):
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch frames are malformed")
    frame_hashes = {_decode_native(path) for path in frame_paths}
    rows = _read_event_rows(nested_root / "events.jsonl")
    if not rows or any(row.get("type") != "capture" for row in rows):
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch events are malformed")
    event_hashes: set[str] = set()
    for row in rows:
        digest = _require_hash(row.get("sha256"), "retained capture")
        event_hashes.add(digest)
        reference = row.get("path")
        if not isinstance(reference, str) or not reference:
            raise _pnsctl().OperatorError("Enhancement retained zero-dispatch capture path is missing")
        path = Path(reference)
        if not path.is_absolute():
            path = nested_root / path
        path = path.resolve()
        try:
            path.relative_to(nested_root.resolve())
        except ValueError as exc:
            raise _pnsctl().OperatorError("Enhancement retained zero-dispatch capture escaped its session") from exc
        if path.is_symlink() or not path.is_file() or _decode_native(path) != digest:
            raise _pnsctl().OperatorError("Enhancement retained zero-dispatch capture is invalid")
    result_path = nested_root / "result.json"
    if result_path.is_symlink() or not result_path.is_file():
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch result is not a regular file")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch result is unreadable") from exc
    stages = result.get("stages") if isinstance(result, dict) else None
    source_hash = _require_hash(result.get("source_frame_sha256"), "retained source") if isinstance(result, dict) else ""
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != 1
        or result.get("flow_id") != FLOW_ID
        or result.get("variant") != variant
        or result.get("status") != "blocked"
        or result.get("dispatch") not in (False, None)
        or type(result.get("dispatch_count")) is not int
        or result.get("dispatch_count") != 0
        or type(result.get("resource_affecting_dispatch_count")) is not int
        or result.get("resource_affecting_dispatch_count") != 0
        or result.get("resource_affecting_action_key") is not None
        or result.get("terminal_recognized") is not False
        or result.get("terminal_frame_sha256") != ""
        or result.get("terminal_state") != "evidence_required"
        or result.get("production_registration") != "NOT_REGISTERED"
        or result.get("scheduler_enabled") is not False
        or not isinstance(result.get("reset_identity"), str)
        or not result["reset_identity"].strip()
        or not isinstance(result.get("reason"), str)
        or not result["reason"].strip()
        or not isinstance(stages, list)
        or not stages
        or any(
            not isinstance(stage, Mapping)
            or stage.get("kind") == "dispatch"
            or str(stage.get("stage") or "").startswith("dispatch:")
            or stage.get("recognized") is not False
            for stage in stages
        )
        or source_hash not in frame_hashes
        or source_hash not in event_hashes
        or event_hashes - frame_hashes
    ):
        raise _pnsctl().OperatorError(
            "Enhancement retained zero-dispatch result is not eligible for replacement"
        )
    if not any(stage.get("frame_sha256") == source_hash for stage in stages):
        raise _pnsctl().OperatorError("Enhancement retained zero-dispatch source is not bound to a stage")


def _continuation_reservation(flow_root: Path, variant: str) -> bool:
    """Release only the explicitly retained Gear startup-failure reservation."""

    path = flow_root / f"reservation-{variant}.json"
    if variant != _RETAINED_ZERO_DISPATCH_VARIANT:
        return False
    if path.is_symlink():
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
    if not path.exists():
        return False
    if not path.is_file():
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
    try:
        reservation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed") from exc
    base_keys = {"dispatch_bearing", "flow_id", "reserved_at", "status", "variant"}
    continuation = reservation.get("continuation") if isinstance(reservation, dict) else None
    if (
        not isinstance(reservation, dict)
        or set(reservation) not in (base_keys, base_keys | {"continuation"})
        or reservation.get("flow_id") != FLOW_ID
        or reservation.get("variant") != variant
        or reservation.get("status") != "reserved"
        or reservation.get("dispatch_bearing") is not True
        or reservation.get("reserved_at") != _RETAINED_ZERO_DISPATCH_RESERVED_AT
        or not _STAMP_RE.fullmatch(str(reservation.get("reserved_at") or ""))
    ):
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is not eligible for continuation")
    if continuation is not None and (
        not isinstance(continuation, Mapping)
        or set(continuation) != {"decision", "reason", "recorded_at", "run_directory"}
        or continuation.get("decision") != "continue_once"
        or continuation.get("reason") != "pre-runtime-module-import"
        or continuation.get("run_directory") != f"run-{variant}-{reservation['reserved_at']}"
        or not _STAMP_RE.fullmatch(str(continuation.get("recorded_at") or ""))
    ):
        raise _pnsctl().OperatorError("Enhancement reservation continuation is malformed")

    run_root = flow_root / f"run-{variant}-{reservation['reserved_at']}"
    if not run_root.is_dir() or run_root.is_symlink():
        raise _pnsctl().OperatorError("Enhancement retained startup failure has unexpected runtime evidence")
    children = {child.name for child in run_root.iterdir()}
    if "operator-stdout.log" not in children or "operator-stderr.log" not in children:
        raise _pnsctl().OperatorError("Enhancement retained startup failure has unexpected runtime evidence")
    nested = [
        child for child in run_root.iterdir()
        if child.name not in {"operator-stdout.log", "operator-stderr.log"}
    ]
    if len(nested) != 1:
        raise _pnsctl().OperatorError("Enhancement retained startup failure has unexpected runtime evidence")
    nested_root = nested[0]
    if (
        not re.fullmatch(rf"enhancement-{variant}-\d{{8}}T\d{{12}}Z", nested_root.name, re.I)
        or nested_root.is_symlink()
        or not nested_root.is_dir()
    ):
        raise _pnsctl().OperatorError("Enhancement retained startup failure has unexpected runtime evidence")
    stdout_path = run_root / "operator-stdout.log"
    stderr_path = run_root / "operator-stderr.log"
    if (
        stdout_path.is_symlink() or not stdout_path.is_file()
        or stderr_path.is_symlink() or not stderr_path.is_file()
    ):
        raise _pnsctl().OperatorError("Enhancement retained startup logs are not regular files")
    try:
        stdout = stdout_path.read_text(encoding="utf-8")
        stderr = stderr_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement retained startup logs are unreadable") from exc
    if stdout != "" or not _PRE_RUNTIME_IMPORT_FAILURE_RE.fullmatch(stderr):
        raise _pnsctl().OperatorError("Enhancement retained failure is not the authorized pre-runtime import failure")
    _validate_zero_dispatch_nested_result(nested_root, variant=variant)
    try:
        path.unlink()
    except OSError as exc:
        raise _pnsctl().OperatorError(
            f"Enhancement {variant} zero-dispatch reservation could not be released"
        ) from exc
    return True


def _reserve_or_continue(flow_root: Path, variant: str) -> Path:
    if _continuation_reservation(flow_root, variant):
        return _reserve(flow_root, variant)
    return _reserve(flow_root, variant)


def _existing_reservation(flow_root: Path, variant: str) -> Path | None:
    path = flow_root / f"reservation-{variant}.json"
    if path.is_symlink():
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
    if not path.exists():
        return None
    if not path.is_file():
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("flow_id") != FLOW_ID
        or value.get("variant") != variant
        or value.get("status") != "reserved"
        or value.get("dispatch_bearing") is not True
        or not _STAMP_RE.fullmatch(str(value.get("reserved_at") or ""))
    ):
        raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
    return path


def _ensure_family_reservations(flow_root: Path) -> dict[str, Path]:
    """Keep one durable dispatch reservation for every ordered category."""
    reservations: dict[str, Path] = {}
    for variant in ("gear", "chip", "module"):
        path = _existing_reservation(flow_root, variant)
        if path is not None:
            reservations[variant] = path
        else:
            reservations[variant] = _reserve_or_continue(flow_root, variant)
    return reservations


def _native_frames(session: Path) -> list[str]:
    frame_dir = session / "frames"
    if not frame_dir.is_dir() or frame_dir.is_symlink():
        raise _pnsctl().OperatorError("Enhancement route produced no native frame directory")
    candidates = sorted(frame_dir.glob("*.png"))
    if any(path.is_symlink() or not path.is_file() for path in candidates):
        raise _pnsctl().OperatorError("Enhancement route produced invalid native frame evidence")
    paths = candidates
    if not paths:
        raise _pnsctl().OperatorError("Enhancement route produced no native frame evidence")
    return [str(path.relative_to(session)).replace("\\", "/") for path in paths]


_NAVIGATION_ONLY_RECOVERY_TARGETS = (
    "commander-profile-portrait",
    "item-select:gear",
)


def _validate_navigation_only_recovery_source(
    recovery_session: Path | str,
    *,
    reset_identity: str,
) -> dict[str, Any]:
    """Validate the immutable, two-navigation, zero-Use Enhancement child."""
    raw_session = Path(str(recovery_session or ""))
    try:
        session = require_no_untrusted_symlinks(raw_session).resolve()
    except UnsafePathError as exc:
        raise _pnsctl().OperatorError(
            "Enhancement navigation recovery source contains a symlink"
        ) from exc
    if not session.is_dir() or session.is_symlink():
        raise _pnsctl().OperatorError("Enhancement navigation recovery source is unavailable")
    delivery_path = session / "flow-delivery-result.json"
    if delivery_path.is_symlink() or not delivery_path.is_file():
        raise _pnsctl().OperatorError("Enhancement navigation recovery result is missing")
    try:
        result = json.loads(delivery_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement navigation recovery result is unreadable") from exc
    if not isinstance(result, Mapping):
        raise _pnsctl().OperatorError("Enhancement navigation recovery result is malformed")
    route = result.get("enhancement_result")
    if (
        result.get("flow_id") != FLOW_ID
        or result.get("variant") != "family"
        or result.get("status") != "blocked"
        or result.get("reset_identity") not in (None, reset_identity)
        or type(result.get("dispatch_count")) is not int
        or type(result.get("input_count")) is not int
        or result.get("dispatch_count") != 2
        or result.get("input_count") != result.get("dispatch_count")
        or type(result.get("max_inputs")) is not int
        or result.get("max_inputs") < result.get("input_count")
        or result.get("resource_affecting_dispatch_count") != 0
        or result.get("effect_reconciliation_required") is not False
        or result.get("terminal_recognized") is not False
        or not isinstance(route, Mapping)
        or route.get("flow_id") != FLOW_ID
        or route.get("variant") != "family"
        or route.get("status") != "blocked"
        or route.get("reset_identity") != reset_identity
        or route.get("dispatch_count") != 2
        or route.get("resource_affecting_dispatch_count") != 0
        or route.get("resource_affecting_action_key") is not None
        or route.get("resource_affecting_action_keys") != []
        or route.get("category_results") != []
        or route.get("terminal_recognized") is not False
        or route.get("terminal_frame_sha256") != ""
        or not str(route.get("reason") or "").startswith(
            "open-enhance:gear immediate-before recognition failed:"
        )
    ):
        raise _pnsctl().OperatorError(
            "Enhancement navigation recovery source is not the known zero-Use blocked child"
        )

    frames = result.get("frames")
    if not isinstance(frames, list) or not frames or len(set(frames)) != len(frames):
        raise _pnsctl().OperatorError("Enhancement navigation recovery frames are malformed")
    frame_hashes: set[str] = set()
    for reference in frames:
        if not isinstance(reference, str) or not reference:
            raise _pnsctl().OperatorError("Enhancement navigation recovery frame reference is invalid")
        path = _retained_path(session, reference, "navigation recovery frame")
        if path.suffix.lower() != ".png":
            raise _pnsctl().OperatorError("Enhancement navigation recovery frame is not PNG")
        digest = _decode_native(path)
        frame_hashes.add(digest)

    initial = result.get("initial_observation")
    initial_digest = _require_hash(result.get("initial_frame_sha256"), "navigation recovery initial")
    if (
        not isinstance(initial, Mapping)
        or initial.get("frame_sha256") != initial_digest
        or not isinstance(initial.get("frame_path"), str)
        or _decode_native(_retained_path(session, initial["frame_path"], "navigation recovery initial"))
        != initial_digest
        or initial_digest not in frame_hashes
        or route.get("source_frame_sha256") not in frame_hashes
    ):
        raise _pnsctl().OperatorError("Enhancement navigation recovery initial capture is invalid")

    events_reference = result.get("events_path")
    if not isinstance(events_reference, str) or not events_reference:
        raise _pnsctl().OperatorError("Enhancement navigation recovery event reference is missing")
    events_path = _retained_path(session, events_reference, "navigation recovery events")
    rows = _read_event_rows(events_path)
    captures: list[str] = []
    dispatches: list[Mapping[str, Any]] = []
    for row in rows:
        kind = row.get("type")
        if kind == "capture":
            digest = _require_hash(row.get("sha256"), "navigation recovery capture")
            reference = row.get("path")
            if not isinstance(reference, str) or not reference:
                raise _pnsctl().OperatorError("Enhancement navigation recovery capture path is missing")
            path = _retained_path(session, reference, "navigation recovery capture")
            if path.suffix.lower() != ".png":
                raise _pnsctl().OperatorError("Enhancement navigation recovery capture is not PNG")
            if _decode_native(path) != digest or digest not in frame_hashes:
                raise _pnsctl().OperatorError("Enhancement navigation recovery capture is not retained")
            captures.append(digest)
        elif kind == "dispatch":
            if (
                row.get("execute") is not True
                or row.get("action_class") != "navigation"
                or row.get("consequential") is not False
                or row.get("resource_affecting") is True
                or row.get("target_identity") not in _NAVIGATION_ONLY_RECOVERY_TARGETS
                or row.get("source_sha256") not in captures
            ):
                raise _pnsctl().OperatorError(
                    "Enhancement navigation recovery contains an unauthorized dispatch"
                )
            dispatches.append(row)
        else:
            raise _pnsctl().OperatorError(
                "Enhancement navigation recovery contains an unknown event"
            )
    targets = tuple(str(row.get("target_identity")) for row in dispatches)
    if targets != _NAVIGATION_ONLY_RECOVERY_TARGETS:
        raise _pnsctl().OperatorError(
            "Enhancement navigation recovery dispatch ledger is not the known two-navigation child"
        )
    if len(dispatches) != result.get("dispatch_count"):
        raise _pnsctl().OperatorError("Enhancement navigation recovery dispatch ledger is inconsistent")

    stages = route.get("stages")
    if not isinstance(stages, list) or not stages:
        raise _pnsctl().OperatorError("Enhancement navigation recovery stage proof is missing")
    for stage in stages:
        if (
            not isinstance(stage, Mapping)
            or stage.get("kind") not in {"recognition", "dispatch"}
            or _require_hash(stage.get("frame_sha256"), "navigation recovery stage") not in frame_hashes
        ):
            raise _pnsctl().OperatorError("Enhancement navigation recovery stage proof is invalid")
    stage_dispatches = [stage for stage in stages if stage.get("kind") == "dispatch"]
    if len(stage_dispatches) != len(dispatches):
        raise _pnsctl().OperatorError("Enhancement navigation recovery dispatch stage proof is incomplete")
    for stage, event in zip(stage_dispatches, dispatches):
        if (
            stage.get("resource_affecting") is not False
            or stage.get("target_identity") != event.get("target_identity")
            or stage.get("action_key") != event.get("action_key")
            or stage.get("frame_sha256") != event.get("source_sha256")
        ):
            raise _pnsctl().OperatorError("Enhancement navigation recovery dispatch proof is inconsistent")
    final_stage = stages[-1]
    if (
        final_stage.get("stage") != "open-enhance-panel-immediate-before"
        or final_stage.get("kind") != "recognition"
        or final_stage.get("recognized") is not False
        or final_stage.get("reason") != "COMMANDER_INFO_NOT_RECOGNIZED"
    ):
        raise _pnsctl().OperatorError("Enhancement navigation recovery terminal failure is not bound")
    return {
        "session_directory": str(session),
        "reset_identity": reset_identity,
        "dispatch_count": len(dispatches),
        "resource_affecting_dispatch_count": 0,
        "frame_hashes": tuple(sorted(frame_hashes)),
    }


def _outer_session(lease: Mapping[str, Any]) -> Any:
    from scripts.navigation_development_boundary import DevelopmentSession

    session = lease.get("development_session")
    if (
        not isinstance(session, DevelopmentSession)
        or session.is_active is not True
        or not callable(getattr(session, "run_action", None))
        or not callable(getattr(session, "observe", None))
    ):
        raise _pnsctl().OperatorError("Enhancement flow requires the pnsctl-owned DevelopmentSession")
    if str(session.owner) == f"pnsctl-development-session:{FLOW_ID}":
        return session
    if str(session.owner) == "automation-service:enhancement":
        checkpoint = lease.get("checkpoint")
        lock = session.runtime_input_lock
        if (
            lease.get("owner") != "automation-service"
            or lease.get("runtime_input_lock") is not lock
            or lock.owner != "automation-service"
            or not callable(checkpoint)
        ):
            raise _pnsctl().OperatorError("Enhancement canonical owner or checkpoint is invalid")
        lock.assert_held("automation-service", lock.invocation_id)
        checkpoint()
        lock.assert_held("automation-service", lock.invocation_id)
        return session
    raise _pnsctl().OperatorError("Enhancement flow requires its exact session owner")


def _initial_observation(lease: Mapping[str, Any], session: Any) -> dict[str, Any]:
    from scripts.navigation_development_boundary import DevelopmentInitialObservation

    value = lease.get("initial_observation")
    bound = session.initial_observation
    if not isinstance(value, DevelopmentInitialObservation):
        raise _pnsctl().OperatorError(
            "Enhancement initial observation must be typed session evidence"
        )
    if not isinstance(bound, DevelopmentInitialObservation) or value is not bound:
        raise _pnsctl().OperatorError(
            "Enhancement initial observation is not exactly session-bound"
        )
    digest = str(value.frame_sha256 or "")
    if (
        not _HASH_RE.fullmatch(digest)
        or digest != str(lease.get("initial_frame_sha256") or "")
        or value.invocation_id != session.invocation_id
    ):
        raise _pnsctl().OperatorError(
            "Enhancement initial observation hash or invocation binding is invalid"
        )
    return value.to_mapping()


def _write_read_only_causal_trace(
    session: Path,
    *,
    result: Mapping[str, Any],
    initial_observation: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _read_event_rows(session / "events.jsonl")
    dispatches = _dispatch_rows(rows)
    resource_dispatches = _resource_dispatch_rows(rows)
    navigation_only = result.get("navigation_only_recovery") is True
    no_effect_recovery = result.get("no_effect_recovery") is True
    trace = {
        "schema_version": 1,
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "stages": (
            [
                "observation",
                "zero_selected_original_attempt",
                "zero_selected_immediate_recovery",
                "zero_selected_later_fresh_recovery",
            ]
            if no_effect_recovery
            else [
                "observation",
                "navigation_only_recovery_source",
                "visible_exit_navigation",
                "terminal_home",
            ]
            if navigation_only
            else [
                "observation",
                "commander_navigation",
                "exact_variant_binding",
                "quantity_use_selection",
                "consuming_confirm",
                "same_item_successor",
                "terminal_home",
            ]
        ),
        "proof_topology": str(result.get("proof_topology") or "composite"),
        "flow_id": FLOW_ID,
        "invocation_id": str(initial_observation.get("invocation_id") or ""),
        "initial_frame_sha256": str(initial_observation.get("frame_sha256") or ""),
        "transport_count": len(dispatches),
        "resource_affecting_dispatch_count": len(resource_dispatches),
        "event_count": len(rows),
        "status": str(result.get("status") or "unknown"),
        "effect_reconciliation_required": bool(
            result.get("effect_reconciliation_required")
        ),
        "navigation_only_recovery": navigation_only,
        "no_effect_recovery": no_effect_recovery,
        "recovery_source_validated": result.get("recovery_source_validated") is True,
    }
    (session / "causal-trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return trace


def _read_family_progress_categories(
    flow_root: Path,
) -> tuple[Path, dict[str, Any]]:
    path = flow_root / "family-progress.json"
    if path.is_symlink():
        raise _pnsctl().OperatorError("Enhancement family progress is not a regular file")
    if not path.exists():
        return path, {}
    if not path.is_file():
        raise _pnsctl().OperatorError("Enhancement family progress is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement family progress is malformed") from exc
    categories = payload.get("categories") if isinstance(payload, Mapping) else None
    if (
        not isinstance(payload, Mapping)
        or payload.get("flow_id") != FLOW_ID
        or not isinstance(categories, Mapping)
    ):
        raise _pnsctl().OperatorError("Enhancement family progress is malformed")
    if any(
        key not in SUPPORTED_VARIANTS or not isinstance(value, Mapping)
        for key, value in categories.items()
    ):
        raise _pnsctl().OperatorError("Enhancement family progress has a malformed category")
    return path, {str(key): dict(value) for key, value in categories.items()}


def _pending_reset_identity(value: Mapping[str, Any], variant: str) -> str:
    """Read pending identity without granting authority to legacy material facts."""
    before = value.get("before_observation")
    if (
        not isinstance(before, Mapping)
        or value.get("variant") != variant
        or before.get("selected_tab") != variant.upper()
        or before.get("selected_item_kind") != variant.upper()
        or before.get("target_provenance") != BLUESTACKS_NATIVE_TARGET_PROVENANCE
        or before.get("runtime_profile_id") != BLUESTACKS_RUNTIME_PROFILE_ID
        or before.get("source_frame_sha256") != value.get("source_frame_sha256")
    ):
        raise _pnsctl().OperatorError("Enhancement pending recovery identity is malformed")
    reset = _validate_family_reset(str(before.get("game_day_id") or ""))
    if value.get("reset_identity") not in (None, reset):
        raise _pnsctl().OperatorError("Enhancement pending recovery reset is inconsistent")
    return reset


def _event_utc(row: Mapping[str, Any], field: str) -> float:
    try:
        value = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
        epoch = value.timestamp()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _pnsctl().OperatorError(f"Enhancement {field} capture time is malformed") from exc
    if value.tzinfo is None or not math.isfinite(epoch) or epoch < 0:
        raise _pnsctl().OperatorError(f"Enhancement {field} capture time is malformed")
    return epoch


def _no_effect_capture(
    session: Path,
    rows: list[Mapping[str, Any]],
    observation: EnhancementObservation,
    digest: str,
    *,
    field: str,
    variant: str,
    reset_identity: str,
) -> tuple[int, Path, float, float]:
    """Bind one real capture event and independently replay that exact PNG."""
    from scripts.enhancement_bluestacks import recognize_commander_stage

    refs = observation.evidence_refs
    if len(refs) != 1:
        raise _pnsctl().OperatorError(f"Enhancement {field} needs one exact native capture")
    path = _retained_path(session, str(refs[0]), field)
    if _decode_native(path) != digest:
        raise _pnsctl().OperatorError(f"Enhancement {field} frame hash is inconsistent")
    matched = []
    for index, row in enumerate(rows):
        if row.get("type") != "capture" or row.get("sha256") != digest:
            continue
        reference = row.get("path")
        if not isinstance(reference, str) or not reference:
            raise _pnsctl().OperatorError(f"Enhancement {field} capture path is missing")
        event_path = _retained_path(session, reference, field)
        if _decode_native(event_path) != digest:
            raise _pnsctl().OperatorError(f"Enhancement {field} event frame is inconsistent")
        if event_path == path:
            monotonic = row.get("captured_monotonic")
            if type(monotonic) not in (int, float) or not math.isfinite(monotonic) or monotonic < 0:
                raise _pnsctl().OperatorError(f"Enhancement {field} actual capture clock is missing")
            utc = _event_utc(row, field)
            if datetime.fromtimestamp(utc, timezone.utc).date().isoformat() != reset_identity[6:16]:
                raise _pnsctl().OperatorError(f"Enhancement {field} capture crosses its reset")
            matched.append((index, path, float(monotonic), utc))
    if len(matched) != 1:
        raise _pnsctl().OperatorError(f"Enhancement {field} capture event is missing or duplicated")
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    replay = recognize_commander_stage(
        image, variant=variant, stage="material", source_frame_sha256=digest,
        evidence_ref=path, game_day_id=reset_identity,
    )
    replayed = getattr(replay, "observation", None)
    if not replay.recognized or not isinstance(replayed, EnhancementObservation):
        raise _pnsctl().OperatorError(f"Enhancement {field} strict native replay is unavailable; evidence_required")
    _validate_native_observation_contract(replayed, field)
    if (
        replayed.source_frame_sha256 != digest
        or _native_observation_semantics(replayed) != _native_observation_semantics(observation)
    ):
        raise _pnsctl().OperatorError(f"Enhancement {field} no-effect facts disagree with its PNG")
    return matched[0]


def _zero_selected_no_effect_observations(
    observations: tuple[EnhancementObservation, ...],
    *,
    variant: str,
    reset_identity: str,
) -> bool:
    """Require the narrow no-selection/no-effect state across all captures."""

    if len(observations) != 4 or variant not in SUPPORTED_VARIANTS:
        return False
    try:
        expected_tab = variant.upper()
        first = observations[0]
        first_semantics = _native_observation_semantics(first)
        for observation in observations:
            _validate_native_observation_contract(observation, "no-effect recovery")
            if (
                observation.selected_tab != expected_tab
                or observation.selected_item_kind != expected_tab
                or observation.target_provenance != BLUESTACKS_NATIVE_TARGET_PROVENANCE
                or observation.runtime_profile_id != BLUESTACKS_RUNTIME_PROFILE_ID
                or observation.game_day_id != reset_identity
                or observation.selected_item_identity != first.selected_item_identity
                or observation.item_level != first.item_level
                or observation.item_exp_current != first.item_exp_current
                or observation.item_exp_required != first.item_exp_required
                or observation.material_slot_facts != first.material_slot_facts
                or observation.material_inventory_count != first.material_inventory_count
                or observation.material_quantity != 0
                or observation.quantity != 0
                or observation.enhancement_result_visible
                or observation.result_identity
                or observation.result_spatially_associated
            ):
                return False
            cells = observation.material_slot_facts
            if not cells or any(cell[2] != 0 for cell in cells):
                return False
            if _native_observation_semantics(observation) != first_semantics:
                return False
    except Exception:
        return False
    return True


def _validate_zero_selected_no_effect_receipt(
    receipt: Mapping[str, Any],
    original_attempt: Mapping[str, Any],
    *,
    variant: str,
    reset_identity: str,
    require_retained_receipt: bool = False,
) -> dict[str, Any]:
    """Replay the exact zero-selection Confirm and four real native captures."""
    required = {
        "proof_kind", "semantic_replay_reason", "original_action_key",
        "original_runtime_session", "recovery_session_directory",
        "original_source_frame_sha256", "original_immediate_post_frame_sha256",
        "immediate_recovery_frame_sha256", "later_recovery_frame_sha256",
        "original_before_observation", "original_immediate_post_observation",
        "immediate_recovery_observation", "later_recovery_observation",
        "reset_identity", "input_count", "dispatch_count", "resource_affecting_dispatch_count",
    }
    if (
        not isinstance(receipt, Mapping) or not required <= set(receipt)
        or receipt.get("proof_kind") != _ZERO_SELECTED_CONFIRM_PROOF
        or receipt.get("semantic_replay_reason") != _NO_EFFECT_REPLAY_REASON
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect receipt is incomplete")
    reset_identity = _validate_family_reset(reset_identity)
    action_key = str(original_attempt.get("resource_affecting_action_key") or "")
    if (
        original_attempt.get("status") != "dispatch_bearing_unresolved"
        or not action_key.startswith(f"enhancement:{variant}:")
        or _pending_reset_identity(original_attempt, variant) != reset_identity
        or receipt.get("original_action_key") != action_key
        or not _same_validated_path_identity(
            receipt.get("original_runtime_session"), original_attempt.get("runtime_session")
        )
        or receipt.get("original_source_frame_sha256") != original_attempt.get("source_frame_sha256")
        or receipt.get("reset_identity") != reset_identity
        or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in (
            "input_count", "dispatch_count", "resource_affecting_dispatch_count",
        ))
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect receipt identity or accounting is invalid")
    observations = tuple(_observation(receipt[key], key.replace("_", " ")) for key in (
        "original_before_observation", "original_immediate_post_observation",
        "immediate_recovery_observation", "later_recovery_observation",
    ))
    hashes = tuple(_require_hash(receipt[key], key.replace("_", " ")) for key in (
        "original_source_frame_sha256", "original_immediate_post_frame_sha256",
        "immediate_recovery_frame_sha256", "later_recovery_frame_sha256",
    ))
    if tuple(observation.source_frame_sha256 for observation in observations) != hashes:
        raise _pnsctl().OperatorError("Enhancement no-effect observations are not bound to their frames")
    if not _zero_selected_no_effect_observations(observations, variant=variant, reset_identity=reset_identity):
        raise _pnsctl().OperatorError("Enhancement zero-selected no-effect facts are inconsistent")
    retained_before = original_attempt["before_observation"]
    if (
        retained_before.get("selected_item_identity") != observations[0].selected_item_identity
        or retained_before.get("item_level") != observations[0].item_level
        or retained_before.get("quantity") != 1
        or retained_before.get("material_quantity") != 1
        or retained_before.get("material_star") != 1
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect replay does not match the legacy Confirm hypothesis")
    try:
        original_session = require_no_untrusted_symlinks(
            Path(str(receipt["original_runtime_session"]))
        ).resolve()
        recovery_session = require_no_untrusted_symlinks(
            Path(str(receipt["recovery_session_directory"]))
        ).resolve()
    except UnsafePathError as exc:
        raise _pnsctl().OperatorError("Enhancement no-effect session is unavailable") from exc
    if any(session.is_symlink() or not session.is_dir() for session in (original_session, recovery_session)):
        raise _pnsctl().OperatorError("Enhancement no-effect session is unavailable")
    if original_session == recovery_session:
        raise _pnsctl().OperatorError("Enhancement no-effect recovery must use a fresh session")
    original_delivery_path = _retained_path(original_session, "flow-delivery-result.json", "original result")
    if original_delivery_path.is_symlink() or not original_delivery_path.is_file():
        raise _pnsctl().OperatorError("Enhancement original no-effect result is missing")
    try:
        original_delivery = json.loads(original_delivery_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement original no-effect result is unreadable") from exc
    if not isinstance(original_delivery, Mapping):
        raise _pnsctl().OperatorError("Enhancement original no-effect result is malformed")
    original_route = original_delivery.get("enhancement_result")
    category_proofs = original_route.get("category_results") if isinstance(original_route, Mapping) else None
    proofs = [proof for proof in category_proofs or [] if isinstance(proof, Mapping) and proof.get("variant") == variant]
    if (
        original_delivery.get("flow_id") != FLOW_ID or len(proofs) != 1
        or original_delivery.get("serial") != BLUESTACKS_SERIAL
        or (original_delivery.get("native_width"), original_delivery.get("native_height")) != (800, 1280)
        or proofs[0].get("status") != "dispatch_bearing_unresolved"
        or proofs[0].get("resource_affecting_action_key") != action_key
        or proofs[0].get("resource_affecting_dispatch_count") != 1
        or proofs[0].get("before_observation") != original_attempt.get("before_observation")
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect proof does not match the original pending attempt")
    original_rows = _read_event_rows(original_session / "events.jsonl")
    recovery_rows = _read_event_rows(recovery_session / "events.jsonl")
    if any(row.get("type") == "dispatch" for row in recovery_rows):
        raise _pnsctl().OperatorError("Enhancement no-effect recovery contains an input")
    dispatches = [(index, row) for index, row in enumerate(original_rows)
                  if row.get("type") == "dispatch" and row.get("action_key") == action_key]
    if len(dispatches) != 1:
        raise _pnsctl().OperatorError("Enhancement original no-effect dispatch is missing or duplicated")
    dispatch_index, dispatch = dispatches[0]
    if (
        dispatch.get("execute") is not True or dispatch.get("target_identity") != "enhancement-use"
        or dispatch.get("source_sha256") != hashes[0]
        or any(row.get("type") == "dispatch" for row in original_rows[dispatch_index + 1:])
        or dispatch.get("target_roi") != retained_before.get("target_roi")
    ):
        raise _pnsctl().OperatorError("Enhancement original no-effect dispatch has a changed source or intervening input")
    actions = original_delivery.get("actions")
    if not isinstance(actions, list):
        raise _pnsctl().OperatorError("Enhancement original no-effect actions are missing")
    matching = [action for action in actions if isinstance(action, Mapping)
                and action.get("label") == "use-one-star-enhancer"
                and action.get("before_sha256") == hashes[0]]
    if len(matching) != 1 or (
        matching[0].get("action_key", action_key) != action_key
        or matching[0].get("immediate_post_sha256") != hashes[1]
        or matching[0].get("after_sha256") != hashes[1]
    ):
        raise _pnsctl().OperatorError("Enhancement original no-effect action capture chain is invalid")
    # The legacy before_observation may contain the fabricated quantity-one
    # shortcut. Preserve it unchanged above; independently replay its actual PNG.
    captures = tuple(_no_effect_capture(
        original_session if index < 2 else recovery_session,
        original_rows if index < 2 else recovery_rows,
        observation, digest, field=field, variant=variant, reset_identity=reset_identity,
    ) for index, (observation, digest, field) in enumerate(zip(observations, hashes, (
        "original source", "original immediate post", "immediate recovery", "later recovery",
    ))))
    before, post, immediate, later = captures
    prior_captures = [index for index, row in enumerate(original_rows[:dispatch_index]) if row.get("type") == "capture"]
    following_captures = [index for index, row in enumerate(original_rows[dispatch_index + 1:], dispatch_index + 1) if row.get("type") == "capture"]
    dispatch_utc = _event_utc(dispatch, "original dispatch")
    if (
        not prior_captures or not following_captures
        or before[0] != prior_captures[-1] or post[0] != following_captures[0]
        or not before[0] < dispatch_index < post[0]
        or not immediate[0] < later[0] or immediate[1] == later[1]
        or not before[2] < post[2] < immediate[2] < later[2]
        or not before[3] <= dispatch_utc <= post[3] < immediate[3] < later[3]
        or dispatch_utc - before[3] > 30.0
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect capture paths, clocks or event order are invalid")
    if require_retained_receipt:
        path = _retained_path(recovery_session, _NO_EFFECT_RECEIPT_NAME, "no-effect receipt")
        if not path.is_file() or path.is_symlink():
            raise _pnsctl().OperatorError("Enhancement immutable no-effect receipt is missing")
        try:
            retained = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("Enhancement immutable no-effect receipt is unreadable") from exc
        if retained != json.loads(json.dumps(receipt, default=str)):
            raise _pnsctl().OperatorError("Enhancement immutable no-effect receipt does not match progress")
    return {
        "proof_kind": _ZERO_SELECTED_CONFIRM_PROOF, "original_action_key": action_key,
        "original_runtime_session": str(original_session), "recovery_session_directory": str(recovery_session),
        "reset_identity": reset_identity, "input_count": 0, "dispatch_count": 0,
        "resource_affecting_dispatch_count": 0,
    }


def _validate_confirmed_no_effect_entry(
    value: Mapping[str, Any], *, variant: str, reset_identity: str | None,
    allow_claimed: bool = False,
) -> None:
    if value.get("status") != _CONFIRMED_NO_EFFECT_STATUS:
        raise _pnsctl().OperatorError("Enhancement no-effect progress status is invalid")
    original = value.get("original_attempt")
    receipt = value.get("no_effect_receipt")
    if not isinstance(original, Mapping) or not isinstance(receipt, Mapping):
        raise _pnsctl().OperatorError("Enhancement no-effect progress audit is missing")
    expected_reset = str(reset_identity or value.get("reset_identity") or "")
    if not expected_reset:
        raise _pnsctl().OperatorError("Enhancement no-effect reset identity is missing")
    _validate_zero_selected_no_effect_receipt(
        receipt, original, variant=variant, reset_identity=expected_reset,
        require_retained_receipt=True,
    )
    claim = value.get("continuation_claim")
    if claim is not None and not allow_claimed:
        raise _pnsctl().OperatorError(
            "Enhancement no-effect continuation is already claimed; evidence_required"
        )


def _no_effect_history(value: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    history = value.get("no_effect_history", [])
    if not isinstance(history, list) or any(not isinstance(item, Mapping) for item in history):
        raise _pnsctl().OperatorError("Enhancement no-effect history is malformed")
    retained = [dict(item) for item in history]
    if value.get("status") == _CONFIRMED_NO_EFFECT_STATUS:
        retained.append({
            "original_attempt": dict(value.get("original_attempt") or {}),
            "no_effect_receipt": dict(value.get("no_effect_receipt") or {}),
            "continuation_claim": value.get("continuation_claim"),
        })
    return retained


def _find_no_effect_entry(
    flow_root: Path, variant: str, reset_identity: str,
) -> dict[str, Any] | None:
    _path, categories = _read_family_progress_categories(flow_root)
    value = categories.get(variant)
    if value is None:
        return None
    if value.get("status") != _CONFIRMED_NO_EFFECT_STATUS:
        return None
    _validate_confirmed_no_effect_entry(
        value, variant=variant, reset_identity=reset_identity,
    )
    return dict(value)


def _claim_no_effect_continuation(
    flow_root: Path,
    variant: str,
    *,
    invocation_id: str,
    session_directory: str,
) -> dict[str, Any]:
    if not invocation_id.strip() or not session_directory.strip():
        raise _pnsctl().OperatorError("Enhancement no-effect continuation identity is missing")
    path, categories = _read_family_progress_categories(flow_root)
    value = categories.get(variant)
    if not isinstance(value, Mapping):
        raise _pnsctl().OperatorError("Enhancement no-effect continuation is unavailable")
    _validate_confirmed_no_effect_entry(
        value, variant=variant,
        reset_identity=str(value.get("reset_identity") or ""),
    )
    claimed = {
        "invocation_id": invocation_id,
        "session_directory": session_directory,
        "claimed_at": _stamp(),
        "hypothesis": "strict_one_star_selection_after_zero_selected_confirm",
    }
    categories[variant] = {**dict(value), "continuation_claim": claimed}
    _atomic_family_progress(path, categories)
    return claimed


def _require_changed_continuation(
    prior: Mapping[str, Any], replacement: Mapping[str, Any],
) -> None:
    """A resolved slot belongs to one new session and one new resource key."""
    claim = prior.get("continuation_claim")
    if (
        not isinstance(claim, Mapping)
        or not str(claim.get("invocation_id") or "").strip()
        or not _STAMP_RE.fullmatch(str(claim.get("claimed_at") or ""))
        or claim.get("hypothesis") != "strict_one_star_selection_after_zero_selected_confirm"
        or not str(replacement.get("resource_affecting_action_key") or "").strip()
        or replacement.get("resource_affecting_action_key") == prior.get("resource_affecting_action_key")
    ):
        raise _pnsctl().OperatorError("Enhancement changed continuation is unclaimed or identical")
    claimed_session = Path(str(claim.get("session_directory") or ""))
    replacement_session = Path(str(replacement.get("runtime_session") or ""))
    if not claimed_session.is_absolute() or not replacement_session.is_absolute():
        raise _pnsctl().OperatorError("Enhancement changed continuation session is missing")
    _retained_path(claimed_session, str(replacement_session), "changed continuation")


def _load_family_progress(
    flow_root: Path, *, reset_identity: str | None = None,
    allow_unresolved: bool = False,
    allow_claimed_no_effect: bool = False,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    path = flow_root / "family-progress.json"
    if path.is_symlink():
        raise _pnsctl().OperatorError("Enhancement family progress is not a regular file")
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement family progress is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement family progress is malformed") from exc
    categories = payload.get("categories") if isinstance(payload, Mapping) else None
    if (
        not isinstance(payload, Mapping)
        or payload.get("flow_id") != FLOW_ID
        or not isinstance(categories, Mapping)
    ):
        raise _pnsctl().OperatorError("Enhancement family progress is malformed")
    completed: dict[str, dict[str, Any]] = {}
    no_effect_entries: list[Mapping[str, Any]] = []
    for variant, value in categories.items():
        _verification_checkpoint(checkpoint)
        if variant not in {"gear", "chip", "module"}:
            raise _pnsctl().OperatorError("Enhancement family progress has an unknown category")
        if isinstance(value, Mapping) and value.get("status") == _CONFIRMED_NO_EFFECT_STATUS:
            _validate_confirmed_no_effect_entry(
                value, variant=variant, reset_identity=reset_identity,
                allow_claimed=allow_claimed_no_effect,
            )
            _verification_checkpoint(checkpoint)
            if value.get("continuation_claim") is None:
                no_effect_entries.append(value)
            # A proven no-effect attempt is accounted for but is deliberately
            # not returned as completed_categories: the next normal run must
            # make a fresh, changed-hypothesis selection.
            continue
        if (
            isinstance(value, Mapping)
            and value.get("status") == "dispatch_bearing_unresolved"
            and _is_reconciled_quantity_setup(value)
        ):
            continue
        unresolved = isinstance(value, Mapping) and value.get("status") == "dispatch_bearing_unresolved"
        if unresolved and not allow_unresolved:
            raise _pnsctl().OperatorError(
                f"Enhancement {variant} has an unresolved dispatch-bearing Use; continuation is blocked"
            )
        if not isinstance(value, Mapping) or value.get("status") not in {"completed", "dispatch_bearing_unresolved"}:
            raise _pnsctl().OperatorError("Enhancement category progress is malformed")
        session = Path(str(value.get("runtime_session") or ""))
        if session.is_symlink() or not session.is_dir():
            raise _pnsctl().OperatorError("Enhancement completed category evidence is missing")
        delivery_path = session / "flow-delivery-result.json"
        if delivery_path.is_symlink() or not delivery_path.is_file():
            raise _pnsctl().OperatorError("Enhancement completed category result is missing")
        try:
            delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("Enhancement completed category result is malformed") from exc
        route = delivery.get("enhancement_result") if isinstance(delivery, Mapping) else None
        rows = _read_event_rows(session / "events.jsonl")
        actions = [
            row for row in _resource_dispatch_rows(rows)
            if str(row.get("action_key") or "") == str(value.get("resource_affecting_action_key") or "")
        ]
        match = next(
            (
                item for item in (route.get("category_results", []) if isinstance(route, Mapping) else [])
                if isinstance(item, Mapping) and item.get("variant") == variant
            ),
            None,
        )
        if unresolved:
            if (
                len(actions) != 1 or not isinstance(match, Mapping)
                or match.get("status") != "dispatch_bearing_unresolved"
                or match.get("resource_affecting_dispatch_count") != 1
                or match.get("resource_affecting_action_key") != value.get("resource_affecting_action_key")
                or match.get("before_observation") != value.get("before_observation")
                or not str(value.get("resource_affecting_action_key") or "").startswith(f"enhancement:{variant}:")
            ):
                raise _pnsctl().OperatorError("Enhancement pending recovery lacks retained Use proof")
            pending_reset = _pending_reset_identity(value, variant)
            if reset_identity is not None and pending_reset != reset_identity:
                raise _pnsctl().OperatorError("Enhancement pending recovery reset is missing or mismatched")
            completed[variant] = dict(value)
            continue
        reconciled = bool(
            value.get("reconciliation") == "zero-input settled successor"
            and isinstance(match, Mapping)
            and match.get("status") == "dispatch_bearing_unresolved"
            and match.get("resource_affecting_dispatch_count") == 1
            and match.get("resource_affecting_action_key")
            == value.get("resource_affecting_action_key")
            and match.get("before_observation") == value.get("before_observation")
            and match.get("successor_observation") is None
            and value.get("successor_observation")
        )
        original_completed = bool(
            isinstance(match, Mapping)
            and match.get("status") == "completed"
            and match.get("resource_affecting_dispatch_count") == 1
            and match.get("before_observation")
            and match.get("successor_observation")
        )
        if (
            len(actions) != 1
            or not str(value.get("resource_affecting_action_key") or "").startswith(
                f"enhancement:{variant}:"
            )
            or not (original_completed or reconciled)
        ):
            raise _pnsctl().OperatorError("Enhancement completed category evidence is not eligible to skip")
        if reconciled:
            _read_positive_receipt(value, variant, str(reset_identity or _pending_reset_identity(value, variant)),
                                   checkpoint=checkpoint)
        proof = value if reconciled else match
        before = _observation(proof["before_observation"], f"{variant} retained before")
        successor = _observation(proof["successor_observation"], f"{variant} retained successor")
        if not enhancement_bluestacks_postcondition_verified(before, successor, variant=variant):
            raise _pnsctl().OperatorError("Enhancement retained successor proof is invalid")
        if reset_identity is not None and (
            before.game_day_id != reset_identity or successor.game_day_id != reset_identity
            or not isinstance(value.get("before_observation"), Mapping)
            or value["before_observation"].get("game_day_id") != reset_identity
            or not isinstance(value.get("successor_observation"), Mapping)
            or value["successor_observation"].get("game_day_id") != reset_identity
        ):
            raise _pnsctl().OperatorError("Enhancement retained proof belongs to another reset")
        completed[variant] = dict(value)
    if reset_identity is not None:
        for value in completed.values():
            refs = []
            for entry in no_effect_entries:
                original = entry["original_attempt"]
                if Path(str(original["runtime_session"])).resolve() != Path(str(value["runtime_session"])).resolve():
                    continue
                recovery = Path(str(entry["no_effect_receipt"]["recovery_session_directory"]))
                receipt_path = _retained_path(recovery, _NO_EFFECT_RECEIPT_NAME, "no-effect accounting receipt")
                refs.append({
                    "recovery_session_directory": str(recovery),
                    "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                    "continuation_claim": None,
                })
            if refs:
                value[_NO_EFFECT_ACCOUNTING_REFS] = refs
        _verify_retained_categories(
            {variant: value for variant, value in completed.items() if value.get("status") == "completed"},
            reset_identity, checkpoint=checkpoint,
        )
    return completed


def _validate_family_reset(reset_identity: str) -> str:
    match = re.fullmatch(r"local-(\d{4}-\d{2}-\d{2})-enhancement-family", reset_identity)
    if match is None:
        raise _pnsctl().OperatorError("Enhancement family reset identity is invalid")
    try:
        datetime.strptime(match[1], "%Y-%m-%d")
    except ValueError as exc:
        raise _pnsctl().OperatorError("Enhancement family reset date is invalid") from exc
    return reset_identity


def _family_state_roots(base_root: Path, *, include_manual: bool = True) -> list[Path]:
    """Inventory only state roots, without traversing retained runtime evidence."""
    if base_root.is_symlink() or (base_root.exists() and not base_root.is_dir()):
        raise _pnsctl().OperatorError("Enhancement base state directory is unsafe")
    roots = [base_root]
    occurrences = base_root / "occurrences"
    if occurrences.is_symlink() or (occurrences.exists() and not occurrences.is_dir()):
        raise _pnsctl().OperatorError("Enhancement occurrence directory is unsafe")
    if occurrences.exists():
        for path in sorted(occurrences.iterdir()):
            _validate_family_reset(path.name)
            if path.is_symlink() or not path.is_dir():
                raise _pnsctl().OperatorError("Enhancement occurrence is not a regular directory")
            roots.append(path)
    manual = base_root / "manual-runs"
    if manual.is_symlink() or (manual.exists() and not manual.is_dir()):
        raise _pnsctl().OperatorError("Enhancement manual state directory is unsafe")
    if manual.exists():
        if not include_manual:
            raise _pnsctl().OperatorError("Enhancement nested manual state is unsafe")
        for path in sorted(manual.iterdir()):
            if path.is_symlink() or not path.is_dir() or not _HASH_RE.fullmatch(path.name):
                raise _pnsctl().OperatorError("Enhancement manual request directory is unsafe")
            roots.extend(_family_state_roots(path, include_manual=False))
    return roots


def _pending_recovery_record(
    flow_root: Path, variant: str, reset_identity: str,
) -> dict[str, Any]:
    """Validate only the requested pending record for a zero-input recovery."""
    _path, categories = _read_family_progress_categories(flow_root)
    value = categories.get(variant)
    if (
        not isinstance(value, Mapping)
        or value.get("status") != "dispatch_bearing_unresolved"
        or type(value.get("resource_affecting_dispatch_count")) is not int
        or value.get("resource_affecting_dispatch_count") != 1
        or _pending_reset_identity(value, variant) != reset_identity
    ):
        raise _pnsctl().OperatorError("Enhancement recovery requires the requested current-reset pending category")
    session = Path(str(value.get("runtime_session") or ""))
    path = _retained_path(session, "flow-delivery-result.json", "pending recovery result")
    if session.is_symlink() or not session.is_dir() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement pending recovery result is missing")
    try:
        delivery = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement pending recovery result is malformed") from exc
    route = delivery.get("enhancement_result") if isinstance(delivery, Mapping) else None
    proofs = route.get("category_results") if isinstance(route, Mapping) else None
    key = value.get("resource_affecting_action_key")
    matches = [proof for proof in proofs or [] if isinstance(proof, Mapping) and proof.get("variant") == variant]
    rows = _read_event_rows(session / "events.jsonl")
    actions = [row for row in _resource_dispatch_rows(rows) if row.get("action_key") == key]
    if (
        not isinstance(delivery, Mapping) or delivery.get("flow_id") != FLOW_ID
        or len(matches) != 1 or len(actions) != 1
        or not str(key or "").startswith(f"enhancement:{variant}:")
        or matches[0].get("status") != "dispatch_bearing_unresolved"
        or matches[0].get("resource_affecting_dispatch_count") != 1
        or matches[0].get("resource_affecting_action_key") != key
        or matches[0].get("before_observation") != value.get("before_observation")
        or actions[0].get("execute") is not True
        or actions[0].get("source_sha256") != value.get("source_frame_sha256")
    ):
        raise _pnsctl().OperatorError("Enhancement pending recovery lacks its exact retained action proof")
    return dict(value)


def _historical_family_accounting(
    flow_root: Path, current_reset: str, expected_reset: str | None,
) -> set[str]:
    """Authenticate older completion metadata without accepting current effects."""
    _path, categories = _read_family_progress_categories(flow_root)
    accounted: set[str] = set()
    current_date = datetime.strptime(current_reset[6:16], "%Y-%m-%d").date()
    for variant, value in categories.items():
        status = value.get("status")
        if status == "dispatch_bearing_unresolved":
            raise _pnsctl().OperatorError(f"Enhancement {variant} has an unresolved dispatch-bearing Use; continuation is blocked")
        before = value.get("before_observation")
        if status == _CONFIRMED_NO_EFFECT_STATUS:
            original = value.get("original_attempt")
            original_before = original.get("before_observation") if isinstance(original, Mapping) else None
            day = str(value.get("reset_identity") or (
                original_before.get("game_day_id") if isinstance(original_before, Mapping) else ""
            ) or "")
        else:
            day = str(before.get("game_day_id") or "") if isinstance(before, Mapping) else ""
        match = re.fullmatch(r"local-(\d{4}-\d{2}-\d{2})-enhancement-(?:family|gear|chip|module)", day)
        try:
            recorded_date = datetime.strptime(match.group(1), "%Y-%m-%d").date() if match else None
        except ValueError:
            recorded_date = None
        if recorded_date is None or recorded_date >= current_date:
            raise _pnsctl().OperatorError("Enhancement record outside the current occurrence is not strictly historical")
        if expected_reset is not None and expected_reset[6:16] != recorded_date.isoformat():
            raise _pnsctl().OperatorError("Enhancement historical record belongs to another reset")
        if status == _CONFIRMED_NO_EFFECT_STATUS:
            _validate_confirmed_no_effect_entry(value, variant=variant, reset_identity=day)
            accounted.add(variant)
            continue
        if status != "completed":
            raise _pnsctl().OperatorError("Enhancement historical category has an unknown state")
        key = str(value.get("resource_affecting_action_key") or "")
        session = Path(str(value.get("runtime_session") or ""))
        source = _require_hash(before.get("source_frame_sha256"), "historical source")
        successor = value.get("successor_observation")
        if (
            value.get("variant") != variant or not key.startswith(f"enhancement:{variant}:")
            or type(value.get("resource_affecting_dispatch_count")) is not int
            or value.get("resource_affecting_dispatch_count") != 1
            or value.get("source_frame_sha256", source) != source
            or before.get("selected_tab") != variant.upper()
            or before.get("selected_item_kind") != variant.upper()
            or before.get("target_provenance") != BLUESTACKS_NATIVE_TARGET_PROVENANCE
            or before.get("runtime_profile_id") != BLUESTACKS_RUNTIME_PROFILE_ID
            or not isinstance(successor, Mapping) or successor.get("game_day_id") != day
            or successor.get("selected_item_identity") != before.get("selected_item_identity")
            or not str(before.get("selected_item_identity") or "").strip()
        ):
            raise _pnsctl().OperatorError("Enhancement historical completion identity is malformed")
        path = _retained_path(session, "flow-delivery-result.json", "historical result")
        try:
            delivery = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("Enhancement historical result is unavailable") from exc
        route = delivery.get("enhancement_result") if isinstance(delivery, Mapping) else None
        proofs = route.get("category_results") if isinstance(route, Mapping) else None
        matches = [proof for proof in proofs or [] if isinstance(proof, Mapping) and proof.get("variant") == variant]
        rows = _read_event_rows(session / "events.jsonl")
        actions = [row for row in _resource_dispatch_rows(rows) if row.get("action_key") == key]
        original_complete = len(matches) == 1 and matches[0].get("status") == "completed" and matches[0].get("successor_observation") == successor
        recorded_recovery = (len(matches) == 1 and matches[0].get("status") == "dispatch_bearing_unresolved"
                             and value.get("reconciliation") == "zero-input settled successor")
        if recorded_recovery and (
            "successor_receipt_path" in value or "successor_receipt_sha256" in value
        ):
            _read_positive_receipt(value, variant, day)
        if (
            not isinstance(delivery, Mapping) or delivery.get("flow_id") != FLOW_ID
            or len(matches) != 1 or len(actions) != 1 or not (original_complete or recorded_recovery)
            or matches[0].get("resource_affecting_action_key") != key
            or matches[0].get("resource_affecting_dispatch_count") != 1
            or matches[0].get("before_observation") != before
            or actions[0].get("source_sha256") != source
            or actions[0].get("execute") is not True
        ):
            raise _pnsctl().OperatorError("Enhancement historical completion lacks its recorded action linkage")
        refs = before.get("evidence_refs")
        if not isinstance(refs, (list, tuple)) or not refs or not any(
            _decode_native(_retained_path(session, str(ref), "historical source")) == source for ref in refs
        ):
            raise _pnsctl().OperatorError("Enhancement historical source hash is not retained")
        accounted.add(variant)
    return accounted


def _select_family_state(
    base_root: Path, reset_identity: str, *, recovery_variant: str | None = None,
    checkpoint: Callable[[], None] | None = None,
    operator_request_id: str | None = None,
) -> tuple[Path, str, dict[str, dict[str, Any]]]:
    """Select current acceptance, or one exact current pending zero-input recovery."""
    _verification_checkpoint(checkpoint)
    _validate_family_reset(reset_identity)
    current = base_root / "occurrences" / reset_identity
    if operator_request_id is not None:
        if (not isinstance(operator_request_id, str) or not operator_request_id.strip()
                or len(operator_request_id) > 256 or recovery_variant is not None):
            raise _pnsctl().OperatorError("Enhancement repeat requires one explicit nonempty request")
        key = hashlib.sha256(operator_request_id.strip().encode("utf-8")).hexdigest()
        current = base_root / "manual-runs" / key / "occurrences" / reset_identity
    if recovery_variant is not None:
        if recovery_variant not in SUPPORTED_VARIANTS:
            raise _pnsctl().OperatorError("Enhancement recovery category is unsupported")
        _retained_path(base_root, f"occurrences/{reset_identity}/family-progress.json", "current recovery progress")
        _pending_recovery_record(current, recovery_variant, reset_identity)
        # This does not accept, skip, or reconcile any category. Native may only
        # observe the requested pending action; its separate proof remains strict.
        return current, reset_identity, {}
    completed = {}
    for root in _family_state_roots(base_root):
        _verification_checkpoint(checkpoint)
        reserved = set()
        for variant in ("gear", "chip", "module"):
            if _existing_reservation(root, variant) is not None:
                reserved.add(variant)
        expected_reset = None if root == base_root or _HASH_RE.fullmatch(root.name) else root.name
        if root != current:
            if expected_reset is not None and expected_reset[6:16] == reset_identity[6:16]:
                # A separately authorized same-day run is a peer, never this
                # occurrence's completion. Replay it and retain unresolved barriers.
                peer = _load_family_progress(root, reset_identity=expected_reset, checkpoint=checkpoint)
                accounted = set(peer)
            else:
                accounted = _historical_family_accounting(root, reset_identity, expected_reset)
            if reserved - accounted:
                raise _pnsctl().OperatorError("Enhancement prior reservation lacks reconciled category evidence")
        else:
            completed = _load_family_progress(root, reset_identity=reset_identity, checkpoint=checkpoint)
    _verification_checkpoint(checkpoint)
    return current, reset_identity, completed


def _is_reconciled_quantity_setup(value: Mapping[str, Any]) -> bool:
    """Recognize the one retained Gear quantity-Use misclassification.

    The quantity modal's Use only stages one material; Confirm is the actual
    resource-affecting action. Preserve the original evidence while allowing
    continuation only when its before/post frames are byte-identical.
    """

    if (
        value.get("variant") != "gear"
        or not str(value.get("resource_affecting_action_key") or "").startswith(
            "enhancement:gear:enhancement-use:"
        )
    ):
        return False
    runtime_session = Path(str(value.get("runtime_session") or ""))
    result_path = runtime_session / "flow-delivery-result.json"
    if (
        not runtime_session.is_dir()
        or runtime_session.is_symlink()
        or not result_path.is_file()
        or result_path.is_symlink()
    ):
        return False
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    actions = payload.get("actions")
    before = value.get("before_observation")
    return bool(
        isinstance(actions, list)
        and len(actions) == 1
        and actions[0].get("label") == "use-one-star-enhancer"
        and actions[0].get("before_sha256")
        == actions[0].get("immediate_post_sha256")
        == actions[0].get("after_sha256")
        == value.get("source_frame_sha256")
        and isinstance(before, Mapping)
        and before.get("selected_item_identity") == "s.o.f suit"
        and before.get("material_identity") == "gear-material-one-star"
        and before.get("quantity") == 1
        and before.get("target_roi") == [264, 780, 536, 875]
        and payload.get("enhancement_result", {}).get("reason")
        == "UNKNOWN_USE_SUCCESSOR"
    )


def _write_family_progress(flow_root: Path, route: Mapping[str, Any]) -> None:
    _progress_path, prior_categories = _read_family_progress_categories(flow_root)
    _load_family_progress(flow_root, allow_unresolved=True, allow_claimed_no_effect=True)
    # A different category may finish before the claimed continuation reaches
    # its Confirm. Never erase that durable barrier or its reconciliation audit.
    completed = dict(prior_categories)
    for value in route.get("category_results", []):
        if isinstance(value, Mapping) and value.get("status") in {
            "completed", "dispatch_bearing_unresolved"
        }:
            variant = str(value.get("variant") or "")
            if variant in {"gear", "chip", "module"}:
                replacement = dict(value)
                replacement.pop(_NO_EFFECT_ACCOUNTING_REFS, None)
                prior = prior_categories.get(variant)
                if isinstance(prior, Mapping) and prior.get("status") == _CONFIRMED_NO_EFFECT_STATUS:
                    _require_changed_continuation(prior, replacement)
                history = _no_effect_history(prior_categories.get(variant))
                if history:
                    replacement["no_effect_history"] = history
                completed[variant] = replacement
    if not completed:
        return
    _atomic_family_progress(flow_root / "family-progress.json", completed)


def _persist_unresolved_dispatch(
    flow_root: Path, runtime_session: Path, rows: list[Mapping[str, Any]],
    route: Mapping[str, Any] | None,
) -> None:
    progress_path, categories = _read_family_progress_categories(flow_root)
    if isinstance(route, Mapping):
        for proof in route.get("category_results", []):
            if isinstance(proof, Mapping) and proof.get("status") == "completed":
                variant = str(proof.get("variant") or "")
                replacement = dict(proof)
                replacement.pop(_NO_EFFECT_ACCOUNTING_REFS, None)
                prior = categories.get(variant)
                if isinstance(prior, Mapping) and prior.get("status") == _CONFIRMED_NO_EFFECT_STATUS:
                    _require_changed_continuation(prior, replacement)
                history = _no_effect_history(categories.get(variant))
                if history:
                    replacement["no_effect_history"] = history
                categories[variant] = replacement
    for row in _resource_dispatch_rows(rows):
        key = str(row.get("action_key") or "")
        match = re.match(r"enhancement:(gear|chip|module):", key)
        if match:
            variant = match.group(1)
            prior = categories.get(variant)
            if prior is not None and prior.get("status") != _CONFIRMED_NO_EFFECT_STATUS:
                continue
            if prior is not None and prior.get("resource_affecting_action_key") == key:
                raise _pnsctl().OperatorError(
                    "Enhancement identical no-effect continuation is denied"
                )
            replacement = {
                "variant": variant,
                "status": "dispatch_bearing_unresolved",
                "resource_affecting_dispatch_count": 1,
                "resource_affecting_action_key": key,
                "runtime_session": str(runtime_session),
            }
            if isinstance(prior, Mapping) and prior.get("status") == _CONFIRMED_NO_EFFECT_STATUS:
                _require_changed_continuation(prior, replacement)
            history = _no_effect_history(prior)
            if history:
                replacement["no_effect_history"] = history
            categories[variant] = replacement
    if categories:
        _atomic_family_progress(progress_path, categories)


def _validate_positive_receipt(
    retained: Mapping[str, Any], variant: str, reset: str, receipt: Mapping[str, Any],
    *, checkpoint: Callable[[], None] | None = None,
) -> None:
    """Replay the immutable original selection and two fresh zero-input successors."""
    from scripts.enhancement_bluestacks import recognize_commander_stage

    _verification_checkpoint(checkpoint)
    if (not isinstance(receipt, Mapping) or receipt.get("proof_kind") != "settled_successor"
            or receipt.get("read_only") is not True or receipt.get("input_authority") is not False
            or receipt.get("reset_identity") != reset
            or receipt.get("original_action_key") != retained.get("resource_affecting_action_key")
            or not _same_validated_path_identity(
                receipt.get("original_runtime_session"), retained.get("runtime_session")
            )
            or receipt.get("original_source_frame_sha256") != retained.get("source_frame_sha256")
            or any(type(receipt.get(name)) is not int or receipt[name] != 0 for name in
                   ("input_count", "dispatch_count", "resource_affecting_dispatch_count"))):
        raise _pnsctl().OperatorError("Enhancement settled-successor receipt identity is invalid")
    original = Path(str(retained.get("runtime_session") or ""))
    original_path = _retained_path(original, "flow-delivery-result.json", "original delivery")
    raw = original_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt.get("original_delivery_sha256"):
        raise _pnsctl().OperatorError("Enhancement original delivery hash changed")
    delivery = json.loads(raw)
    delivery, original, original_rows, hashes = _verify_native_structure({
        "result": delivery, "session_directory": str(original), "frames": delivery.get("frames"),
    }, checkpoint=checkpoint)
    route = delivery.get("enhancement_result")
    proofs = route.get("category_results") if isinstance(route, Mapping) else None
    matches = [item for item in proofs or [] if isinstance(item, Mapping) and item.get("variant") == variant]
    key = retained.get("resource_affecting_action_key")
    resources = [row for row in _resource_dispatch_rows(original_rows) if row.get("action_key") == key]
    classifications = [row for row in original_rows if row.get("type") == "dispatch_classification"
                       and row.get("action_key") == key]
    if (not isinstance(route, Mapping) or route.get("reset_identity") != reset
            or len(matches) != 1 or matches[0].get("status") != "dispatch_bearing_unresolved"
            or matches[0].get("before_observation") != retained.get("before_observation")
            or matches[0].get("resource_affecting_dispatch_count") != 1
            or not _same_validated_path_identity(matches[0].get("runtime_session"), original)
            or matches[0].get("successor_observation") is not None
            or matches[0].get("resource_affecting_action_key") != key
            or matches[0].get("source_frame_sha256") != retained.get("source_frame_sha256")
            or len(resources) != 1 or len(classifications) != 1
            or classifications[0].get("resource_affecting") is not True
            or classifications[0].get("consequential") is not False):
        raise _pnsctl().OperatorError("Enhancement original pending action is not uniquely bound")
    successor = _observation(receipt.get("successor_observation"), "settled successor")
    if (not successor.evidence_refs or str(successor.evidence_refs[0]) != str(receipt.get("successor_evidence_ref"))):
        raise _pnsctl().OperatorError("Enhancement original settled successor reference differs")
    replay_proof = {**dict(matches[0]), "successor_observation": dict(receipt["successor_observation"])}
    before, after = _replay_category_observations(replay_proof, variant=variant, reset=reset,
        session=original, rows=original_rows, frame_hashes=hashes, actions=delivery.get("actions"),
        checkpoint=checkpoint)
    original_capture = _context_capture(original, original_rows, str(successor.evidence_refs[0]), reset=reset)
    recovery_raw = receipt.get("recovery_session_directory")
    if not isinstance(recovery_raw, str) or not Path(recovery_raw).is_absolute():
        raise _pnsctl().OperatorError("Enhancement recovery session is missing")
    recovery = Path(recovery_raw)
    recovery_path = _retained_path(recovery, "flow-delivery-result.json", "recovery delivery")
    recovery = recovery_path.parent
    if recovery == original:
        raise _pnsctl().OperatorError("Enhancement recovery must have its own session")
    recovery_bytes = recovery_path.read_bytes()
    recovery_delivery = json.loads(recovery_bytes)
    recovery_delivery, recovery, recovery_rows, recovery_hashes = _verify_native_structure({
        "result": recovery_delivery, "session_directory": str(recovery),
        "frames": recovery_delivery.get("frames"),
    }, checkpoint=checkpoint)
    recovery_events = _retained_path(
        recovery, str(recovery_delivery.get("events_path") or "events.jsonl"), "recovery events"
    )
    recovery_journal = recovery_events.read_bytes()
    recovered = recovery_delivery.get("enhancement_result")
    if (recovery_delivery.get("status") != "recovered_successor"
            or any(recovery_delivery.get(name) != 0 for name in
                   ("input_count", "dispatch_count", "resource_affecting_dispatch_count"))
            or any(row.get("type") == "dispatch" for row in recovery_rows)
            or not isinstance(recovered, Mapping) or recovered.get("status") != "recovered_successor"
            or recovered.get("semantic_successor_proven") is not True
            or recovered.get("proof_kind") != "settled_successor"
            or recovered.get("read_only") is not True or recovered.get("input_authority") is not False
            or recovered.get("dispatch") is not False
            or recovered.get("terminal_recognized") is not False
            or any(type(recovered.get(name)) is not int or recovered[name] != 0 for name in
                   ("input_count", "dispatch_count", "resource_affecting_dispatch_count"))
            or recovered.get("recovery_only") is not True
            or recovered.get("successor_receipt") != receipt
            or recovered.get("successor_observation") != receipt.get("successor_observation")
            or recovered.get("successor_evidence_ref") != receipt.get("successor_evidence_ref")):
        raise _pnsctl().OperatorError("Enhancement recovery delivery does not bind zero-input receipt")
    last = original_capture
    for field in ("immediate_recovery_observation", "later_recovery_observation"):
        _verification_checkpoint(checkpoint)
        observed = _observation(receipt.get(field), field)
        _verify_observation_binding(observed, recovery, recovery_hashes, field)
        current = _context_capture(recovery, recovery_rows, str(observed.evidence_refs[0]), reset=reset)
        if (current[0].captured_monotonic <= last[0].captured_monotonic or current[2] < last[2]
                or current[0].path == last[0].path):
            raise _pnsctl().OperatorError("Enhancement recovery captures are not fresh and ordered")
        replayed = recognize_commander_stage(current[0].frame, variant=variant, stage="post",
            source_frame_sha256=current[0].sha256, evidence_ref=current[0].path, game_day_id=reset)
        _verification_checkpoint(checkpoint)
        if (not replayed.recognized or not isinstance(replayed.observation, EnhancementObservation)
                or _native_observation_semantics(replayed.observation) != _native_observation_semantics(observed)
                or _native_observation_semantics(replayed.observation) != _native_observation_semantics(after)
                or not enhancement_bluestacks_postcondition_verified(before, replayed.observation, variant=variant)):
            raise _pnsctl().OperatorError("Enhancement recovery PNG does not match the committed successor")
        last = current
    if (original_path.read_bytes() != raw or recovery_path.read_bytes() != recovery_bytes
            or recovery_events.read_bytes() != recovery_journal):
        raise _pnsctl().OperatorError("Enhancement source or recovery evidence changed during replay")
    _verification_checkpoint(checkpoint)


def _read_positive_receipt(value: Mapping[str, Any], variant: str, reset: str,
                           *, checkpoint: Callable[[], None] | None = None) -> None:
    path = Path(str(value.get("successor_receipt_path") or ""))
    if not path.is_absolute() or path.name != _POSITIVE_RECEIPT_NAME:
        raise _pnsctl().OperatorError("Enhancement settled receipt path is invalid")
    path = _retained_path(path.parent, path.name, "settled successor receipt")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != value.get("successor_receipt_sha256"):
        raise _pnsctl().OperatorError("Enhancement settled receipt hash differs")
    receipt = json.loads(raw)
    if (not _same_validated_path_identity(receipt.get("recovery_session_directory"), path.parent)
            or receipt.get("successor_observation") != value.get("successor_observation")
            or receipt.get("successor_evidence_ref") != value.get("successor_evidence_ref")):
        raise _pnsctl().OperatorError("Enhancement settled receipt differs from family progress")
    _validate_positive_receipt(value, variant, reset, receipt, checkpoint=checkpoint)


def _reconcile_recovery_successor(flow_root: Path, variant: str, route: Mapping[str, Any],
                                  *, checkpoint: Callable[[], None] | None = None) -> None:
    progress_path, categories = _read_family_progress_categories(flow_root)
    retained = categories.get(variant)
    receipt = route.get("successor_receipt")
    if (not isinstance(retained, Mapping) or retained.get("status") != "dispatch_bearing_unresolved"
            or not isinstance(receipt, Mapping) or route.get("status") != "recovered_successor"
            or route.get("semantic_successor_proven") is not True
            or route.get("successor_observation") != receipt.get("successor_observation")
            or route.get("successor_evidence_ref") != receipt.get("successor_evidence_ref")):
        raise _pnsctl().OperatorError("Enhancement recovery is not a pending settled successor")
    reset = _pending_reset_identity(retained, variant)
    _validate_positive_receipt(retained, variant, reset, receipt, checkpoint=checkpoint)
    recovery = Path(str(receipt["recovery_session_directory"]))
    receipt_path = _retained_path(recovery, _POSITIVE_RECEIPT_NAME, "settled successor receipt")
    encoded = (json.dumps(dict(receipt), indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    with receipt_path.open("xb") as handle:
        handle.write(encoded)
    _verification_checkpoint(checkpoint)
    current_path, current = _read_family_progress_categories(flow_root)
    if current_path != progress_path or current.get(variant) != retained:
        raise _pnsctl().OperatorError("Enhancement pending progress changed before reconciliation")
    current[variant] = {**dict(retained), "status": "completed",
        "successor_observation": dict(receipt["successor_observation"]),
        "successor_evidence_ref": str(receipt["successor_evidence_ref"]),
        "reconciliation": "zero-input settled successor", "successor_receipt_path": str(receipt_path),
        "successor_receipt_sha256": hashlib.sha256(encoded).hexdigest()}
    _read_positive_receipt(current[variant], variant, reset, checkpoint=checkpoint)
    _verification_checkpoint(checkpoint)
    _atomic_family_progress(progress_path, current)


def _reconcile_recovery_no_effect(
    flow_root: Path,
    variant: str,
    route: Mapping[str, Any],
    *,
    recovery_session: Path,
) -> None:
    """Consume one pending Use with an independently proven zero-effect receipt."""

    progress_path, categories = _read_family_progress_categories(flow_root)
    retained = categories.get(variant)
    if not isinstance(retained, Mapping) or retained.get("status") != "dispatch_bearing_unresolved":
        raise _pnsctl().OperatorError(
            "Enhancement no-effect recovery requires one retained pending Use"
        )
    if route.get("status") != _RECOVERED_NO_EFFECT_STATUS:
        raise _pnsctl().OperatorError("Enhancement no-effect recovery status is invalid")
    if (
        route.get("proof_kind") != _ZERO_SELECTED_CONFIRM_PROOF
        or any(type(route.get(key)) is not int or route[key] != 0 for key in (
            "input_count", "dispatch_count", "resource_affecting_dispatch_count",
        ))
    ):
        raise _pnsctl().OperatorError("Enhancement no-effect recovery accounting is invalid")
    receipt = route.get("no_effect_receipt")
    if not isinstance(receipt, Mapping):
        raise _pnsctl().OperatorError("Enhancement no-effect recovery receipt is missing")
    receipt = dict(receipt)
    if not _same_validated_path_identity(receipt.get("recovery_session_directory"), recovery_session):
        raise _pnsctl().OperatorError(
            "Enhancement no-effect recovery session is not source-bound"
        )
    _validate_zero_selected_no_effect_receipt(
        receipt,
        retained,
        variant=variant,
        reset_identity=_pending_reset_identity(retained, variant),
    )
    receipt_path = _retained_path(recovery_session, _NO_EFFECT_RECEIPT_NAME, "no-effect receipt")
    try:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n")
    except FileExistsError as exc:
        raise _pnsctl().OperatorError("Enhancement immutable no-effect receipt already exists") from exc
    original = dict(retained)
    categories[variant] = {
        "variant": variant,
        "status": _CONFIRMED_NO_EFFECT_STATUS,
        "reset_identity": _pending_reset_identity(retained, variant),
        "resource_affecting_dispatch_count": 1,
        "resource_affecting_action_key": retained.get("resource_affecting_action_key"),
        "source_frame_sha256": retained.get("source_frame_sha256"),
        "before_observation": retained.get("before_observation"),
        "successor_observation": None,
        "runtime_session": retained.get("runtime_session"),
        "original_status": "dispatch_bearing_unresolved",
        "original_attempt": original,
        "no_effect_receipt": receipt,
        "continuation_claim": None,
    }
    _atomic_family_progress(progress_path, categories)


def _recover_family_startup(runtime, session):
    try:
        return _run_family_startup(runtime, session)
    finally:
        session.adopt_retained_transport_count(runtime.input_count, source=str(runtime.events))


def _run_family_startup(runtime, session):
    from scripts.startup_normalization import is_clean_home_frame
    from scripts.startup_recovery import classify_startup_frame, recover_contextual_startup_overlay

    source = session.observe(runtime.capture, label="enhancement-startup-overlay-source")
    plan = classify_startup_frame(FLOW_ID, source.png)
    if plan.status == "blocked":
        raise _pnsctl().OperatorError(plan.reason)
    if plan.status != "recovery_required":
        return None
    before = runtime.input_count
    recovery = recover_contextual_startup_overlay(
        runtime, source, source_context="enhancement_family_startup",
        recognize_successor=lambda frame: is_clean_home_frame(frame.frame),
        action_key=f"enhancement:startup:{runtime.session.name}",
    )
    if (type(recovery.input_count) is not int or recovery.input_count not in (1, 2)
            or runtime.input_count != before + recovery.input_count or not recovery.resume_ready
            or recovery.settled_frame is None or len(recovery.steps) != recovery.input_count):
        raise _pnsctl().OperatorError(f"Enhancement startup recovery failed: {recovery.reason}")
    return {"input_count": recovery.input_count,
            "steps": [step.to_mapping(runtime.session) for step in recovery.steps]}


def run_enhancement_family(
    queue: Mapping[str, Any], lease: Mapping[str, Any], *, live: bool = True
) -> str:
    """Run the direct Home -> Commander Info enhancement route in one session."""

    del queue
    pnsctl = _pnsctl()
    variant = str(lease.get("enhancement_variant") or "gear").strip().lower()
    if variant not in SUPPORTED_VARIANTS:
        raise pnsctl.OperatorError("Enhancement category is unsupported")
    ordered_variants = ("gear", "chip", "module")
    maximum = _session_max_inputs(lease)
    recovery_only = bool(lease.get("enhancement_recovery_only"))
    navigation_only_recovery = bool(recovery_only and str(lease.get("recovery_session") or "").strip())
    flow_root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID
    reservations: dict[str, Path] = {}
    completed_categories: dict[str, dict[str, Any]] = {}
    root = flow_root / f"run-{variant}-{_stamp()}"
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "variant": "family",
                "dispatch": False,
                "dispatch_count": 0,
                "max_inputs": maximum,
                "session_directory": str(root),
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    outer_session = _outer_session(lease)
    initial_observation = _initial_observation(lease, outer_session)
    reset_identity = str(lease.get("enhancement_reset_identity") or "").strip()
    if not recovery_only and not reset_identity:
        raise pnsctl.OperatorError("Enhancement reset identity is required")
    recovery_source = None
    no_effect_continuation = None
    if navigation_only_recovery:
        if maximum < 2:
            raise pnsctl.OperatorError(
                "Enhancement navigation recovery requires max_inputs >= 2"
            )
        recovery_source = _validate_navigation_only_recovery_source(
            str(lease.get("recovery_session") or ""), reset_identity=reset_identity,
        )
        flow_root, reset_identity, completed_categories = _select_family_state(
            flow_root, reset_identity, checkpoint=lease.get("checkpoint"),
        )
        if completed_categories:
            raise pnsctl.OperatorError(
                "Enhancement navigation recovery cannot replace current-day category proof"
            )
    else:
        flow_root, reset_identity, completed_categories = _select_family_state(
            flow_root, reset_identity,
            recovery_variant=variant if recovery_only else None,
            checkpoint=lease.get("checkpoint"),
            operator_request_id=lease.get("operator_request_id"),
        )
    if not recovery_only:
        reservations = _ensure_family_reservations(flow_root)
        claims = {}
        for category in ordered_variants:
            if _find_no_effect_entry(flow_root, category, reset_identity) is not None:
                claims[category] = _claim_no_effect_continuation(
                    flow_root, category,
                    invocation_id=str(getattr(outer_session, "invocation_id", "")),
                    session_directory=str(getattr(outer_session, "session_directory", "")),
                )
        no_effect_continuation = claims or None
    pending_attempt = None
    if recovery_only and not navigation_only_recovery:
        _progress_path, pending_categories = _read_family_progress_categories(flow_root)
        pending_attempt = pending_categories.get(variant)
        if (
            not isinstance(pending_attempt, Mapping)
            or pending_attempt.get("status") != "dispatch_bearing_unresolved"
            or _pending_reset_identity(pending_attempt, variant) != reset_identity
        ):
            raise pnsctl.OperatorError("Enhancement pending recovery changed before capture")
    if not reset_identity:
        raise pnsctl.OperatorError("Enhancement reset identity is required")
    outer_directory = Path(outer_session.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_session = outer_directory
    route: dict[str, Any] | None = None
    startup_recovery = None
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    try:
        os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(maximum)
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(BLUESTACKS_ADB),
            serial=BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow="enhancement-family",
            execute=True,
        )
        if str(outer_session.owner) == "automation-service:enhancement":
            runtime.checkpoint = lease["checkpoint"]
        elif callable(lease.get("checkpoint")):
            runtime.checkpoint = lease["checkpoint"]
        runtime.max_inputs = maximum
        if recovery_only and not navigation_only_recovery:
            # Pending-effect recovery only observes; the controller's legacy
            # minimum input budget does not grant this child input authority.
            runtime.max_inputs = 0
        runtime_session = runtime.session
        source_path = outer_directory / "source.png"
        if source_path.is_file():
            retained_initial = runtime_session / "frames" / "0000-initial-observation.png"
            retained_initial.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, retained_initial)
            initial_observation["frame_path"] = "frames/0000-initial-observation.png"
        from scripts.enhancement_bluestacks import EnhancementIntegratedRoute, run_recovery

        if not recovery_only:
            startup_recovery = _recover_family_startup(runtime, outer_session)

        route = (
            run_recovery(
                runtime,
                variant=variant,
                reset_identity=reset_identity,
                session=outer_session,
                navigation_only=navigation_only_recovery,
                pending_attempt=pending_attempt,
            )
            if recovery_only
            else EnhancementIntegratedRoute(
                runtime,
                session=outer_session,
                variant="gear",
                variants=ordered_variants,
                completed_categories=completed_categories,
                reset_identity=reset_identity,
            ).run()
        )
        if recovery_only and route.get("status") == _RECOVERED_NO_EFFECT_STATUS:
            _reconcile_recovery_no_effect(
                flow_root,
                variant,
                route,
                recovery_session=runtime_session,
            )
        rows = _read_event_rows(runtime_session / "events.jsonl")
        frames = _native_frames(runtime_session)
        dispatches = _dispatch_rows(rows)
        resource_dispatches = _resource_dispatch_rows(rows)
        input_count = int(getattr(outer_session, "input_count", 0))
        if len(resource_dispatches) > MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS:
            raise pnsctl.OperatorError("Enhancement route exceeded the family Use limit")
        resource_by_variant = {
            variant_name: sum(
                1
                for row in resource_dispatches
                if str(row.get("action_key") or "").startswith(f"enhancement:{variant_name}:")
            )
            for variant_name in ("gear", "chip", "module")
        }
        for category, retained in completed_categories.items():
            if retained.get("resource_affecting_action_key"):
                resource_by_variant[category] += 1
        proofs = {
            str(item.get("variant")): item
            for item in route.get("category_results", [])
            if isinstance(item, Mapping)
        } if isinstance(route.get("category_results"), list) else {}
        for category, count in resource_by_variant.items():
            expected = 1 if category in proofs else 0
            if count != expected:
                raise pnsctl.OperatorError(
                    f"Enhancement {category} resource Use accounting is inconsistent"
                )
        if route.get("status") == "completed" and any(
            resource_by_variant[category] != 1 for category in ("gear", "chip", "module")
        ):
            raise pnsctl.OperatorError("Enhancement completed family lacks one Use per category")
        if input_count > maximum or len(dispatches) > maximum:
            raise pnsctl.OperatorError("Enhancement route exceeded its development input bound")
        if input_count != len(dispatches):
            raise pnsctl.OperatorError("Enhancement session accounting does not match native events")
    except Exception:
        # Accounting, safety, and native evidence failures are fail-closed.
        # In particular, never convert a completed route into synthetic
        # evidence after a post-run invariant mismatch.
        if runtime is not None and not navigation_only_recovery:
            event_path = runtime_session / "events.jsonl"
            if event_path.is_file() and not event_path.is_symlink():
                try:
                    _persist_unresolved_dispatch(
                        flow_root, runtime_session, _read_event_rows(event_path), route
                    )
                except Exception as persist_exc:
                    raise pnsctl.OperatorError(
                        "Enhancement dispatch-bearing unresolved state could not be retained"
                    ) from persist_exc
        raise
    finally:
        if previous_limit is None:
            os.environ.pop("PNS_DEVELOPMENT_MAX_INPUTS", None)
        else:
            os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = previous_limit
    if route is None:
        raise pnsctl.OperatorError("Enhancement route produced no result")
    route_status = str(route.get("status") or "unknown")
    if route_status not in {
        "completed", "blocked", "unresolved", "evidence_required",
        "manual_required", "observed", "recovered_safe", "recovered_successor",
        _RECOVERED_NO_EFFECT_STATUS,
    }:
        raise pnsctl.OperatorError("Enhancement route returned an unknown terminal status")
    delivery_status = (
        "completed"
        if route_status == "completed" and route.get("terminal_recognized") is True
        else "unresolved"
        if route_status in {"unresolved", "evidence_required", "manual_required"}
        else _RECOVERED_NO_EFFECT_STATUS
        if route_status == _RECOVERED_NO_EFFECT_STATUS
        else "recovered_successor"
        if route_status == "recovered_successor"
        else "blocked"
    )
    uninterrupted_family = bool(
        delivery_status == "completed"
        and not recovery_only
        and not completed_categories
        and len(resource_dispatches) == MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS
    )
    proof_topology = "continuous" if uninterrupted_family else "composite"
    effect_reconciliation_required = bool(
        resource_dispatches and delivery_status != "completed"
    )
    if effect_reconciliation_required:
        delivery_status = "effect_reconciliation_required"
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "variant": "family",
        "serial": BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": "recognized_safe_terminal"
        if route.get("terminal_recognized") is True else "safe_blocked_terminal",
        "terminal_recognized": route.get("terminal_recognized") is True,
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "actions": list(getattr(outer_session, "actions", [])),
        "startup_recovery": startup_recovery,
        "dispatch": bool(dispatches),
        "dispatch_count": len(dispatches),
        "input_count": input_count,
        "max_inputs": maximum,
        "resource_affecting_dispatch_count": len(resource_dispatches),
        "enhancement_result": route,
        "proof_topology": proof_topology,
        "initial_observation": initial_observation,
        "initial_frame_sha256": initial_observation["frame_sha256"],
        "causal_trace_count": 1,
        "effect_reconciliation_required": effect_reconciliation_required,
        "navigation_only_recovery": navigation_only_recovery,
        "no_effect_recovery": route_status == _RECOVERED_NO_EFFECT_STATUS,
        "no_effect_continuation_claim": no_effect_continuation,
        "recovery_source_validated": recovery_source is not None,
        "recovery_source_session_directory": (
            recovery_source.get("session_directory") if recovery_source is not None else None
        ),
        "recovery_source_dispatch_count": (
            recovery_source.get("dispatch_count", 0) if recovery_source is not None else 0
        ),
        "terminal_home_verified": (
            route.get("terminal_home_verified") is True
            if navigation_only_recovery else (
                not recovery_only and delivery_status == "completed"
                and route.get("terminal_recognized") is True
            )
        ),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    trace = _write_read_only_causal_trace(
        runtime_session,
        result=delivery,
        initial_observation=initial_observation,
    )
    delivery["causal_trace"] = trace
    outer_session.set_causal_trace(trace)
    outer_session.remember_control("enhancement_route_status", delivery_status)
    outer_session.remember_control(
        "target_history",
        [
            str(row.get("label") or row.get("action_key") or "")
            for row in outer_session.actions
        ],
    )
    outer_session.remember_control(
        "recovery_result",
        "verified_home" if delivery_status == "completed" else route.get("reason"),
    )
    (runtime_session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if recovery_only and route_status == "recovered_successor":
        if (len(dispatches) != 0 or len(resource_dispatches) != 0 or input_count != 0
                or route.get("terminal_recognized") is not False):
            raise pnsctl.OperatorError("Enhancement positive recovery accounting is not zero-input")
        _reconcile_recovery_successor(flow_root, variant, route, checkpoint=lease.get("checkpoint"))
    if not recovery_only:
        _write_family_progress(flow_root, route)
    return json.dumps(
        {
            "status": delivery_status,
            "flow_id": FLOW_ID,
            "variant": "family",
            "session_directory": str(runtime_session),
            "dispatch": bool(dispatches),
            "dispatch_count": len(dispatches),
            "input_count": input_count,
            "proof_topology": proof_topology,
            "causal_trace_count": 1,
            "effect_reconciliation_required": effect_reconciliation_required,
            "navigation_only_recovery": navigation_only_recovery,
            "no_effect_recovery": route_status == _RECOVERED_NO_EFFECT_STATUS,
            "no_effect_continuation_claim": no_effect_continuation,
            "recovery_source_validated": recovery_source is not None,
            "recovery_source_session_directory": (
                recovery_source.get("session_directory") if recovery_source is not None else None
            ),
            "recovery_source_dispatch_count": (
                recovery_source.get("dispatch_count", 0) if recovery_source is not None else 0
            ),
            "terminal_home_verified": delivery["terminal_home_verified"],
        },
        sort_keys=True,
    )


def _validate_native_observation_contract(
    observation: EnhancementObservation, field: str,
) -> None:
    """Reject native observations that predate the typed material contract."""

    native = (
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        or observation.runtime_profile_id == BLUESTACKS_RUNTIME_PROFILE_ID
    )
    if not native:
        return
    if (
        type(observation.item_exp_current) is not int
        or type(observation.item_exp_required) is not int
        or observation.item_exp_current < 0
        or observation.item_exp_required <= 0
        or observation.item_exp_current >= observation.item_exp_required
    ):
        raise _pnsctl().OperatorError(
            f"Enhancement {field} native EXP facts are missing or malformed; evidence_required"
        )
    cells = observation.material_slot_facts
    if not isinstance(cells, tuple) or not cells or len(cells) > 36:
        raise _pnsctl().OperatorError(
            f"Enhancement {field} native material-slot facts are missing; evidence_required"
        )
    seen: set[int] = set()
    for index, cell in enumerate(cells):
        if (
            not isinstance(cell, tuple)
            or len(cell) != 4
            or any(type(value) is not int for value in cell)
        ):
            raise _pnsctl().OperatorError(
                f"Enhancement {field} native material slot {index} is malformed; evidence_required"
            )
        slot, stars, selected, owned = cell
        if (
            slot < 0
            or slot in seen
            or not 0 <= stars <= 9
            or selected < 0
            or owned < 0
            or selected > owned
        ):
            raise _pnsctl().OperatorError(
                f"Enhancement {field} native material slot {index} is invalid; evidence_required"
            )
        seen.add(slot)
    if observation.quantity == 1 and (
        type(observation.item_exp_preview) is not int
        or not observation.item_exp_current < observation.item_exp_preview < observation.item_exp_required
        or not isinstance(observation.selection_baseline_frame_sha256, str)
        or not _HASH_RE.fullmatch(observation.selection_baseline_frame_sha256)
        or not isinstance(observation.selection_baseline_evidence_ref, str)
        or not observation.selection_baseline_evidence_ref
    ):
        raise _pnsctl().OperatorError(
            f"Enhancement {field} native selection baseline or EXP preview is missing; evidence_required"
        )


def _observation(value: Any, field: str) -> EnhancementObservation:
    if not isinstance(value, Mapping):
        raise _pnsctl().OperatorError(f"Enhancement {field} observation is missing")
    payload = dict(value)
    for key in ("target_roi", "panel_bounds"):
        if isinstance(payload.get(key), list):
            payload[key] = tuple(payload[key])
    if isinstance(payload.get("evidence_refs"), list):
        payload["evidence_refs"] = tuple(payload["evidence_refs"])
    if "material_slot_facts" in payload:
        cells = payload["material_slot_facts"]
        if isinstance(cells, list):
            converted: list[tuple[Any, ...]] = []
            for cell in cells:
                if isinstance(cell, list):
                    converted.append(tuple(cell))
                elif isinstance(cell, tuple):
                    converted.append(cell)
                else:
                    raise _pnsctl().OperatorError(
                        f"Enhancement {field} material slot facts are malformed"
                    )
            payload["material_slot_facts"] = tuple(converted)
        elif isinstance(cells, tuple):
            payload["material_slot_facts"] = tuple(
                tuple(cell) if isinstance(cell, list) else cell for cell in cells
            )
    try:
        observation = EnhancementObservation(**payload)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(f"Enhancement {field} observation is malformed") from exc
    _validate_native_observation_contract(observation, field)
    return observation


def _verify_native_structure(
    structure: Mapping[str, Any],
    *, checkpoint: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], set[str]]:
    _verification_checkpoint(checkpoint)
    pnsctl = _pnsctl()
    result = structure.get("result")
    if not isinstance(result, dict) or result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Enhancement evidence belongs to another flow")
    variant = str(result.get("variant") or "").lower()
    if variant != "family":
        raise pnsctl.OperatorError("Enhancement evidence must be an R4 family result")
    raw_session = Path(str(structure.get("session_directory") or ""))
    try:
        session = require_no_untrusted_symlinks(raw_session).resolve()
    except UnsafePathError as exc:
        raise pnsctl.OperatorError("Enhancement evidence session path contains a symlink") from exc
    if not session.is_dir() or session.is_symlink():
        raise pnsctl.OperatorError("Enhancement evidence session directory is unavailable")
    delivery_path = session / "flow-delivery-result.json"
    if not delivery_path.is_file() or delivery_path.is_symlink():
        raise pnsctl.OperatorError("Enhancement flow-delivery-result.json is required")
    retained = json.loads(delivery_path.read_text(encoding="utf-8"))
    if retained != json.loads(json.dumps(result, sort_keys=True, default=str)):
        raise pnsctl.OperatorError("Enhancement retained result does not match verifier input")
    if (
        result.get("serial") != BLUESTACKS_SERIAL
        or (result.get("native_width"), result.get("native_height")) != (800, 1280)
        or result.get("production_registration") != "NOT_REGISTERED"
        or result.get("scheduler_enabled") is not False
    ):
        raise pnsctl.OperatorError("Enhancement evidence runtime or registration profile is invalid")
    if result.get("status") not in {
        "completed", "blocked", "evidence_required", "unresolved", "manual_required",
        "effect_reconciliation_required", _RECOVERED_NO_EFFECT_STATUS, "recovered_successor",
    }:
        raise pnsctl.OperatorError("Enhancement delivery status is invalid")
    frames = structure.get("frames") or result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise pnsctl.OperatorError("Enhancement native frame evidence is required")
    frame_hashes: set[str] = set()
    for value in frames:
        _verification_checkpoint(checkpoint)
        if not isinstance(value, str) or not value:
            raise pnsctl.OperatorError("Enhancement frame references are invalid")
        path = _retained_path(session, value, "frame")
        if not path.is_file() or path.suffix.lower() != ".png":
            raise pnsctl.OperatorError("Enhancement frame evidence is missing or not PNG")
        frame_hashes.add(_decode_native(path))
        _verification_checkpoint(checkpoint)
    rows = _read_event_rows(_retained_path(
        session, str(result.get("events_path") or "events.jsonl"), "event journal",
    ))
    declared = result.get("dispatch_count")
    if type(declared) is not int or declared != len(_dispatch_rows(rows)):
        raise pnsctl.OperatorError("Enhancement dispatch count does not match native events")
    if (
        type(result.get("input_count")) is not int or result.get("input_count") != declared
        or type(result.get("resource_affecting_dispatch_count")) is not int
        or result.get("resource_affecting_dispatch_count") != len(_resource_dispatch_rows(rows))
    ):
        raise pnsctl.OperatorError("Enhancement source input or resource accounting is not exact")
    if len(_resource_dispatch_rows(rows)) > MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS:
        raise pnsctl.OperatorError("Enhancement evidence exceeds the family resource Use limit")
    return result, session, rows, frame_hashes


def _ordered_category_proofs(route: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    proofs = route.get("category_results")
    categories = ("gear", "chip", "module")
    if (
        not isinstance(proofs, list) or len(proofs) != len(categories)
        or any(not isinstance(proof, Mapping) for proof in proofs)
        or any(proof.get("variant") not in categories for proof in proofs)
        or {proof.get("variant") for proof in proofs} != set(categories)
    ):
        raise _pnsctl().OperatorError("Enhancement family requires one proof per category")
    return [next(proof for proof in proofs if proof["variant"] == category) for category in categories]


def _verify_event_order(
    rows: list[dict[str, Any]], route: Mapping[str, Any], frame_hashes: set[str],
    *, current_categories: tuple[str, ...] = ("gear", "chip", "module"),
) -> None:
    captured: list[str] = []
    for row in rows:
        if row.get("type") == "capture":
            digest = _require_hash(row.get("sha256"), "capture")
            if digest not in frame_hashes:
                raise _pnsctl().OperatorError("Enhancement capture hash is not retained")
            captured.append(digest)
        elif row.get("type") == "dispatch":
            digest = _require_hash(row.get("source_sha256"), "dispatch source")
            if digest not in captured:
                raise _pnsctl().OperatorError("Enhancement dispatch occurred without prior source capture")
    use_rows = [
        row for row in rows
        if row.get("type") == "dispatch" and row.get("target_identity") == "enhancement-use"
    ]
    categories = ("gear", "chip", "module")
    proofs = _ordered_category_proofs(route)
    if (
        len(use_rows) != len(current_categories)
        or len(_resource_dispatch_rows(rows)) != len(use_rows)
        or route.get("resource_affecting_dispatch_count") != 3
    ):
        raise _pnsctl().OperatorError("Enhancement current Uses do not match its remaining categories")
    seen_keys: set[str] = set()
    use_positions: list[int] = []
    for category, proof in zip(categories, proofs):
        if (
            not isinstance(proof, Mapping)
            or proof.get("status") != "completed"
            or proof.get("resource_affecting_dispatch_count") != 1
        ):
            raise _pnsctl().OperatorError(f"Enhancement {category} successor proof is incomplete")
        expected_key = str(proof.get("resource_affecting_action_key") or "")
        if not expected_key or expected_key in seen_keys:
            raise _pnsctl().OperatorError("Enhancement resource Use action keys are not unique")
        seen_keys.add(expected_key)
        if category not in current_categories:
            if any(row.get("action_key") == expected_key for row in use_rows):
                raise _pnsctl().OperatorError("Enhancement retained category was dispatched again")
            continue
        matches = [
            row for row in use_rows
            if row.get("action_key") == expected_key
            and str(expected_key).startswith(f"enhancement:{category}:")
        ]
        if len(matches) != 1:
            raise _pnsctl().OperatorError(f"Enhancement {category} Use event is missing or duplicated")
        use_positions.append(next(index for index, row in enumerate(rows) if row is matches[0]))
        before = _observation(proof.get("before_observation"), f"{category} before")
        successor = _observation(proof.get("successor_observation"), f"{category} successor")
        source_hash = _require_hash(matches[0].get("source_sha256"), f"{category} Use source")
        if source_hash != before.source_frame_sha256 or source_hash not in frame_hashes:
            raise _pnsctl().OperatorError(f"Enhancement {category} Use is not bound to immediate-before")
        if not enhancement_bluestacks_postcondition_verified(before, successor, variant=category):
            raise _pnsctl().OperatorError(f"Enhancement {category} successor is not same-item proof")
        classifications = [
            row for row in rows
            if row.get("type") == "dispatch_classification"
            and row.get("action_key") == expected_key
        ]
        if (
            len(classifications) != 1
            or classifications[0].get("resource_affecting") is not True
            or classifications[0].get("consequential") is not False
        ):
            raise _pnsctl().OperatorError(f"Enhancement {category} Use class is missing")
    if use_positions != sorted(use_positions):
        raise _pnsctl().OperatorError("Enhancement family Uses are out of order")


def _verify_observation_binding(
    observation: EnhancementObservation,
    session: Path,
    frame_hashes: set[str],
    field: str,
) -> None:
    digest = _require_hash(observation.source_frame_sha256, f"{field} source")
    if digest not in frame_hashes:
        raise _pnsctl().OperatorError(f"Enhancement {field} source is not retained")
    if (
        observation.target_provenance != BLUESTACKS_NATIVE_TARGET_PROVENANCE
        or observation.runtime_profile_id != BLUESTACKS_RUNTIME_PROFILE_ID
    ):
        raise _pnsctl().OperatorError(f"Enhancement {field} provenance is invalid")
    refs = observation.evidence_refs
    selected = observation.quantity == 1
    if len(refs) != (4 if selected else 1):
        raise _pnsctl().OperatorError(f"Enhancement {field} exact evidence references are missing")
    paths: list[Path] = []
    for index, reference in enumerate(refs):
        path = _retained_path(session, str(reference), f"{field} evidence")
        if not path.is_file() or path.suffix.lower() != ".png":
            raise _pnsctl().OperatorError(f"Enhancement {field} evidence reference is invalid")
        actual = _decode_native(path)
        if actual not in frame_hashes or (index == 0 and actual != digest):
            raise _pnsctl().OperatorError(f"Enhancement {field} evidence does not match its source")
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise _pnsctl().OperatorError(f"Enhancement {field} evidence captures are duplicated")
    if selected and (
        _retained_path(session, str(observation.selection_baseline_evidence_ref or ""), field) != paths[2]
        or _decode_native(paths[2]) != observation.selection_baseline_frame_sha256
    ):
        raise _pnsctl().OperatorError(f"Enhancement {field} selection baseline is not bound")


def _context_capture(
    session: Path, rows: list[dict[str, Any]], reference: str, *, reset: str,
) -> tuple[Any, int, float]:
    """Recover one exact retained capture rather than choosing by its PNG hash."""
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png

    path = _retained_path(session, reference, "selection witness")
    if path.parent != (session / "frames").resolve() or path.suffix.lower() != ".png":
        raise _pnsctl().OperatorError("Enhancement selection witness is outside native frames")
    digest = _decode_native(path)
    matches: list[tuple[Any, int, float]] = []
    for index, row in enumerate(rows):
        if row.get("type") != "capture":
            continue
        event_ref = row.get("path")
        if not isinstance(event_ref, str) or not event_ref:
            raise _pnsctl().OperatorError("Enhancement selection capture path is missing")
        if _retained_path(session, event_ref, "selection capture") != path:
            continue
        clock = row.get("captured_monotonic")
        utc = _event_utc(row, "selection witness")
        if (
            row.get("sha256") != digest
            or type(clock) not in (int, float) or not math.isfinite(clock) or clock < 0
            or datetime.fromtimestamp(utc, timezone.utc).date().isoformat() != reset[6:16]
        ):
            raise _pnsctl().OperatorError("Enhancement selection capture facts are invalid")
        matches.append((captured_native_frame_from_png(
            path.read_bytes(), captured_monotonic=float(clock), path=path,
        ), index, utc))
    if len(matches) != 1:
        raise _pnsctl().OperatorError("Enhancement exact selection capture is missing or duplicated")
    return matches[0]


def _replay_category_observations(
    proof: Mapping[str, Any], *, variant: str, reset: str,
    session: Path, rows: list[dict[str, Any]], frame_hashes: set[str], actions: Any,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[EnhancementObservation, EnhancementObservation]:
    """Bind the fresh equipped/selection witnesses and their actual input chain."""
    from scripts.enhancement_bluestacks import (
        recognize_commander_stage, recognize_selection_context,
    )

    _verification_checkpoint(checkpoint)
    before = _observation(proof.get("before_observation"), f"{variant} before")
    after = _observation(proof.get("successor_observation"), f"{variant} successor")
    if (
        not _same_validated_path_identity(proof.get("runtime_session"), session)
        or proof.get("source_frame_sha256") != before.source_frame_sha256
    ):
        raise _pnsctl().OperatorError("Enhancement category is not bound to its native runtime")
    _verify_observation_binding(before, session, frame_hashes, f"{variant} before")
    _verify_observation_binding(after, session, frame_hashes, f"{variant} successor")
    current, modal, baseline, quantity = (
        _context_capture(session, rows, ref, reset=reset) for ref in before.evidence_refs
    )
    successor = _context_capture(session, rows, after.evidence_refs[0], reset=reset)
    ordered = (modal, baseline, quantity, current, successor)
    if any(
        left[1] >= right[1]
        or left[0].captured_monotonic >= right[0].captured_monotonic
        or left[2] > right[2]
        for left, right in zip(ordered, ordered[1:])
    ):
        raise _pnsctl().OperatorError("Enhancement selection witness order is invalid")
    _verification_checkpoint(checkpoint)
    context = recognize_selection_context(
        current[0], modal=modal[0], baseline=baseline[0], quantity=quantity[0],
        variant=variant, game_day_id=reset,
    )
    _verification_checkpoint(checkpoint)
    replayed_before = getattr(context, "observation", None)
    post = recognize_commander_stage(
        successor[0].frame, variant=variant, stage="post",
        source_frame_sha256=successor[0].sha256, evidence_ref=successor[0].path,
        game_day_id=reset,
    )
    _verification_checkpoint(checkpoint)
    replayed_after = getattr(post, "observation", None)
    if (
        not context.recognized or not post.recognized
        or not isinstance(replayed_before, EnhancementObservation)
        or not isinstance(replayed_after, EnhancementObservation)
    ):
        raise _pnsctl().OperatorError("Enhancement selection context cannot be independently replayed")
    targets = context.diagnostics.get("selection_context_targets")
    if not isinstance(targets, Mapping):
        raise _pnsctl().OperatorError("Enhancement selection witness controls are missing")
    expected = (
        (modal, f"open-enhance:{variant}", targets.get("modal_enhance")),
        (baseline, f"material-select:{variant}", targets.get("baseline_card")),
        (quantity, "quantity-use", targets.get("quantity_use")),
        (current, "enhancement-use", replayed_before.target_roi),
    )
    dispatches = [
        (index, row) for index, row in enumerate(rows)
        if row.get("type") == "dispatch" and modal[1] < index < successor[1]
    ]
    if len(dispatches) != len(expected):
        raise _pnsctl().OperatorError("Enhancement selection has missing or intervening inputs")
    keys: set[str] = set()
    for position, ((capture, identity, target), (index, row)) in enumerate(zip(expected, dispatches)):
        prior_captures = [i for i, event in enumerate(rows[:index]) if event.get("type") == "capture"]
        next_capture = ordered[position + 1]
        key = row.get("action_key")
        if (
            target is None or not prior_captures or prior_captures[-1] != capture[1]
            or not capture[1] < index < next_capture[1]
            or row.get("source_sha256") != capture[0].sha256
            or row.get("target_identity") != identity
            or tuple(row.get("target_roi") or ()) != tuple(target)
            or tuple(row.get("point") or ()) != ((target[0] + target[2]) // 2, (target[1] + target[3]) // 2)
            or row.get("execute") is not True or row.get("consequential") is not False
            or row.get("action_class") != "navigation"
            or not isinstance(key, str) or not key.startswith(f"enhancement:{variant}:") or key in keys
            or (position == 3 and key != proof.get("resource_affecting_action_key"))
        ):
            raise _pnsctl().OperatorError("Enhancement selection input is not bound to its measured source")
        keys.add(key)
        dispatched_at = _event_utc(row, "selection input")
        if not capture[2] <= dispatched_at <= next_capture[2]:
            raise _pnsctl().OperatorError("Enhancement selection dispatch clock is invalid")
    confirm_index = dispatches[-1][0]
    immediate_index = next(
        index for index in range(confirm_index + 1, len(rows))
        if rows[index].get("type") == "capture"
    )
    immediate = _context_capture(
        session, rows, str(rows[immediate_index].get("path") or ""), reset=reset,
    )
    envelopes = [
        action for action in actions if isinstance(action, Mapping)
        and action.get("label") == "use-one-star-enhancer"
        and action.get("before_sha256") == current[0].sha256
    ] if isinstance(actions, list) else []
    if (
        immediate[0].sha256 not in frame_hashes
        or immediate[1] > successor[1]
        or immediate[0].captured_monotonic <= current[0].captured_monotonic
        or (immediate[1] != successor[1]
            and immediate[0].captured_monotonic >= successor[0].captured_monotonic)
        or not _event_utc(dispatches[-1][1], "Confirm") <= immediate[2] <= successor[2]
        or len(envelopes) != 1
        or envelopes[0].get("immediate_post_sha256") != immediate[0].sha256
        or envelopes[0].get("after_sha256") != immediate[0].sha256
        or envelopes[0].get("recovery_used") is not False
        or envelopes[0].get("action_key", proof.get("resource_affecting_action_key"))
        != proof.get("resource_affecting_action_key")
    ):
        raise _pnsctl().OperatorError("Enhancement Confirm action lacks its exact immediate-post envelope")
    if (
        _native_observation_semantics(replayed_before) != _native_observation_semantics(before)
        or _native_observation_semantics(replayed_after) != _native_observation_semantics(after)
        or not enhancement_bluestacks_authorizeable(replayed_before, variant=variant)
        or not enhancement_bluestacks_postcondition_verified(replayed_before, replayed_after, variant=variant)
    ):
        raise _pnsctl().OperatorError("Enhancement selection or committed effect disagrees with its PNGs")
    return replayed_before, replayed_after


def _verified_no_effect_resource_keys(
    completed: Mapping[str, Any], reset_identity: str,
    *, checkpoint: Callable[[], None] | None = None,
) -> set[tuple[str, str]]:
    """Account immutable zero-effect attempts without completing or rearming them."""
    sources = {str(Path(str(value["runtime_session"])).resolve())
               for value in completed.values() if isinstance(value, Mapping) and value.get("runtime_session")}
    refs: list[Mapping[str, Any]] = []
    for value in completed.values():
        _verification_checkpoint(checkpoint)
        if not isinstance(value, Mapping):
            continue
        listed = value.get(_NO_EFFECT_ACCOUNTING_REFS, [])
        if not isinstance(listed, list) or any(not isinstance(ref, Mapping) for ref in listed):
            raise _pnsctl().OperatorError("Enhancement no-effect accounting references are malformed")
        refs.extend(listed)
        for history in _no_effect_history(value):
            original = history.get("original_attempt")
            receipt = history.get("no_effect_receipt")
            if not isinstance(original, Mapping) or not isinstance(receipt, Mapping):
                raise _pnsctl().OperatorError("Enhancement no-effect accounting history is malformed")
            if str(Path(str(original.get("runtime_session") or "")).resolve()) not in sources:
                continue
            retained_original = _original_no_effect_attempt(receipt)
            if any(original.get(field) != retained_original.get(field) for field in (
                "variant", "runtime_session", "resource_affecting_action_key", "before_observation",
            )):
                raise _pnsctl().OperatorError("Enhancement no-effect accounting original attempt changed")
            _require_changed_continuation({
                **history, "resource_affecting_action_key": original.get("resource_affecting_action_key"),
            }, value)
            recovery = Path(str(receipt.get("recovery_session_directory") or ""))
            path = _retained_path(recovery, _NO_EFFECT_RECEIPT_NAME, "historical no-effect receipt")
            try:
                retained_receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise _pnsctl().OperatorError("Enhancement no-effect accounting receipt is unavailable") from exc
            if retained_receipt != receipt:
                raise _pnsctl().OperatorError("Enhancement no-effect accounting history changed")
            refs.append({"recovery_session_directory": str(recovery),
                "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "continuation_claim": None})
    accounted: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        _verification_checkpoint(checkpoint)
        if set(ref) != {"recovery_session_directory", "receipt_sha256", "continuation_claim"} or ref["continuation_claim"] is not None:
            raise _pnsctl().OperatorError("Enhancement no-effect accounting reference is claimed or incomplete")
        recovery_ref = ref["recovery_session_directory"]
        if not isinstance(recovery_ref, str) or not recovery_ref or not Path(recovery_ref).is_absolute():
            raise _pnsctl().OperatorError("Enhancement no-effect accounting session is missing")
        digest = _require_hash(ref["receipt_sha256"], "no-effect accounting receipt")
        identity = (str(Path(recovery_ref).resolve()), digest)
        if identity in seen:
            continue
        seen.add(identity)
        path = _retained_path(Path(recovery_ref), _NO_EFFECT_RECEIPT_NAME, "no-effect accounting receipt")
        try:
            encoded = path.read_bytes()
            receipt = json.loads(encoded)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("Enhancement no-effect accounting receipt is unavailable") from exc
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise _pnsctl().OperatorError("Enhancement no-effect accounting receipt changed")
        if not isinstance(receipt, Mapping) or receipt.get("recovery_session_directory") != recovery_ref:
            raise _pnsctl().OperatorError("Enhancement no-effect accounting receipt session is mismatched")
        original = _original_no_effect_attempt(receipt)
        variant = str(original.get("variant") or "")
        _validate_confirmed_no_effect_entry({
            "status": _CONFIRMED_NO_EFFECT_STATUS, "reset_identity": reset_identity,
            "original_attempt": original, "no_effect_receipt": receipt, "continuation_claim": None,
        }, variant=variant, reset_identity=reset_identity)
        _verification_checkpoint(checkpoint)
        source = str(Path(str(original["runtime_session"])).resolve())
        key = str(original["resource_affecting_action_key"])
        if source not in sources or any(isinstance(value, Mapping) and value.get("resource_affecting_action_key") == key for value in completed.values()):
            raise _pnsctl().OperatorError("Enhancement no-effect accounting cannot complete or repeat its original key")
        accounted.add((source, key))
    return accounted


def _verify_retained_categories(
    completed: Mapping[str, Any], reset_identity: str,
    *, checkpoint: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Replay original category effects before treating any of them as work done."""
    _verification_checkpoint(checkpoint)
    _validate_family_reset(reset_identity)
    if not isinstance(completed, Mapping) or set(completed) - SUPPORTED_VARIANTS:
        raise _pnsctl().OperatorError("Enhancement retained categories are malformed")
    verified: dict[str, dict[str, Any]] = {}
    keys: set[str] = set()
    no_effect_keys = _verified_no_effect_resource_keys(completed, reset_identity, checkpoint=checkpoint)
    for variant in ("gear", "chip", "module"):
        _verification_checkpoint(checkpoint)
        if variant not in completed:
            continue
        value = completed[variant]
        if (
            not isinstance(value, Mapping) or value.get("status") != "completed"
            or value.get("variant") != variant
            or type(value.get("resource_affecting_dispatch_count")) is not int
            or value.get("resource_affecting_dispatch_count") != 1
        ):
            raise _pnsctl().OperatorError("Enhancement retained category is not completed")
        source = value.get("runtime_session")
        if not isinstance(source, str) or not source or not Path(source).is_absolute():
            raise _pnsctl().OperatorError("Enhancement retained source session is missing")
        session = Path(source)
        delivery_path = _retained_path(session, "flow-delivery-result.json", "retained category result")
        if not delivery_path.is_file():
            raise _pnsctl().OperatorError("Enhancement retained source result is missing")
        try:
            encoded = delivery_path.read_bytes()
            delivery = json.loads(encoded)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("Enhancement retained source result is malformed") from exc
        delivery, session, rows, frame_hashes = _verify_native_structure({
            "result": delivery, "session_directory": str(session),
            "frames": delivery.get("frames") if isinstance(delivery, Mapping) else None,
        }, checkpoint=checkpoint)
        route = delivery.get("enhancement_result")
        proofs = route.get("category_results") if isinstance(route, Mapping) else None
        matches = [
            proof for proof in proofs
            if isinstance(proof, Mapping) and proof.get("variant") == variant
        ] if isinstance(proofs, list) else []
        key = value.get("resource_affecting_action_key")
        for resource in _resource_dispatch_rows(rows):
            source_key = str(resource.get("action_key") or "")
            source_variant = re.match(r"enhancement:(gear|chip|module):", source_key)
            accounted = completed.get(source_variant[1]) if source_variant else None
            if (str(session), source_key) not in no_effect_keys and (
                not isinstance(accounted, Mapping)
                or accounted.get("resource_affecting_action_key") != source_key
                or not isinstance(accounted.get("runtime_session"), str)
                or Path(accounted["runtime_session"]).resolve() != session
            ):
                raise _pnsctl().OperatorError("Enhancement retained source contains an orphan or repeated resource Use")
        resource_rows = [
            row for row in _resource_dispatch_rows(rows)
            if str(row.get("action_key") or "").startswith(f"enhancement:{variant}:")
        ]
        if value.get("reconciliation") == "zero-input settled successor":
            if (not isinstance(key, str) or key in keys or len(resource_rows) != 1
                    or resource_rows[0].get("action_key") != key):
                raise _pnsctl().OperatorError("Enhancement reconciled source resource key is invalid")
            _read_positive_receipt(value, variant, reset_identity, checkpoint=checkpoint)
            keys.add(key)
            verified[variant] = {
                "status": "verified", "variant": variant, "reset_identity": reset_identity,
                "runtime_session": str(session), "resource_affecting_action_key": key,
                "delivery_sha256": hashlib.sha256(encoded).hexdigest(),
            }
            continue
        if (
            not isinstance(route, Mapping) or route.get("reset_identity") != reset_identity
            or len(matches) != 1 or len(resource_rows) != 1
            or not isinstance(key, str) or not key.startswith(f"enhancement:{variant}:") or key in keys
            or resource_rows[0].get("action_key") != key
            or matches[0].get("status") != "completed"
            or matches[0].get("resource_affecting_dispatch_count") != 1
            or any(matches[0].get(field) != value.get(field) for field in (
                "resource_affecting_action_key", "runtime_session", "source_frame_sha256",
                "before_observation", "successor_observation",
            ))
        ):
            raise _pnsctl().OperatorError("Enhancement retained category does not match its original source")
        classifications = [
            row for row in rows if row.get("type") == "dispatch_classification"
            and row.get("action_key") == key
        ]
        if (
            len(classifications) != 1 or classifications[0].get("resource_affecting") is not True
            or classifications[0].get("consequential") is not False
        ):
            raise _pnsctl().OperatorError("Enhancement retained resource classification is missing")
        before, after = _replay_category_observations(
            matches[0], variant=variant, reset=reset_identity, session=session,
            rows=rows, frame_hashes=frame_hashes, actions=delivery.get("actions"),
            checkpoint=checkpoint,
        )
        _verification_checkpoint(checkpoint)
        if (
            before.game_day_id != reset_identity or after.game_day_id != reset_identity
            or delivery_path.read_bytes() != encoded
        ):
            raise _pnsctl().OperatorError("Enhancement retained source changed or crosses its reset")
        keys.add(key)
        verified[variant] = {
            "status": "verified", "variant": variant, "reset_identity": reset_identity,
            "runtime_session": str(session), "resource_affecting_action_key": key,
            "delivery_sha256": hashlib.sha256(encoded).hexdigest(),
        }
    return verified


def _semantic_stage_for_phase(
    name: str, *, detail_state: str | None = None,
) -> str | None:
    """Map recorded route phases to the recognizer contract they actually used."""
    if name in {"home-source", "family-startup-home", "family-home-terminal"}:
        return "home"
    if name.startswith("home-to-commander-immediate-before"):
        return "home"
    if name.startswith("home-to-commander-immediate-post") or name.startswith(
        "home-to-commander-settled"
    ):
        return "tab"

    if name == "commander-source" and detail_state is not None:
        return {
            "item_modal": "item", "commander_overview": "tab",
            "enhancement_panel": "material", "enhancement_post": "post",
            "quantity_modal": "material",
        }.get(detail_state)
    if name in {"commander-source", "family-startup-tab"}:
        return "tab"
    if name == "family-startup-commander":
        return "item"
    if name == "family-startup-material":
        return "material"

    if name.startswith("select-enhancement-category-immediate-before"):
        return "tab"
    if name.startswith("select-enhancement-category-"):
        return "item"
    if name.startswith("select-equipped-enhancement-item-"):
        return "item"
    if name.startswith("open-enhance-panel-immediate-before"):
        return "item"
    if name.startswith("open-enhance-panel-immediate-post") or name.startswith(
        "open-enhance-panel-settled"
    ):
        return "material"
    if name.startswith("select-exact-one-star-material-"):
        return "material"
    if name.startswith("apply-quantity-selection-"):
        return "material"

    if name.startswith("use-one-star-enhancer-immediate-before"):
        return "material"
    if name.startswith("use-one-star-enhancer-immediate-post"):
        return "post"
    if name.startswith("enhancement-settle-") or name == "enhancement-terminal":
        return "post"

    if name.startswith((
        "leave-completed-gear-enhancement-immediate-before",
        "leave-completed-chip-enhancement-immediate-before",
        "leave-completed-module-enhancement-immediate-before",
    )):
        return "post"
    if name.startswith((
        "leave-completed-gear-enhancement-immediate-post",
        "leave-completed-gear-enhancement-settled",
        "leave-completed-chip-enhancement-immediate-post",
        "leave-completed-chip-enhancement-settled",
        "leave-completed-module-enhancement-immediate-post",
        "leave-completed-module-enhancement-settled",
    )):
        return "tab"

    if name.startswith("close-completed-gear-detail-immediate-before"):
        return "item"
    if name.startswith("close-completed-gear-detail-immediate-post") or name.startswith(
        "close-completed-gear-detail-settled"
    ):
        return "tab"
    if name.startswith("commander-to-home-terminal-immediate-before"):
        return "tab"
    if name.startswith("commander-to-home-terminal-immediate-post") or name.startswith(
        "commander-to-home-terminal-settled"
    ):
        return "home"
    if name.startswith("return-home-immediate-post") or name.startswith(
        "return-home-settled"
    ):
        return "home"
    if name.startswith(("return-home-", "commander-return-")):
        state_stage = {
            "item_modal": "item",
            "commander_overview": "tab",
            "enhancement_post": "post",
            "enhancement_panel": "material",
            "home": "home",
        }
        if detail_state in state_stage:
            return state_stage[detail_state]
    if name == "return-home-source":
        return "post"
    return None


def _native_observation_semantics(
    observation: EnhancementObservation,
) -> tuple[Any, ...]:
    """Return only the semantic fields that must survive native replay."""

    return (
        observation.screen_state,
        observation.selected_tab,
        observation.selected_item_kind,
        observation.selected_item_identity,
        observation.item_equipped,
        observation.item_level,
        observation.material_identity,
        observation.material_known,
        observation.material_available,
        observation.material_star,
        observation.material_quantity,
        observation.quantity,
        observation.material_inventory_count,
        observation.item_exp_current,
        observation.item_exp_required,
        observation.item_exp_preview,
        observation.selection_baseline_frame_sha256,
        observation.selection_baseline_evidence_ref,
        observation.material_slot_facts,
        observation.enhancement_result_visible,
        observation.result_identity,
        observation.result_spatially_associated,
        observation.target_identity,
        observation.target_roi,
        observation.panel_bounds,
        observation.control_class,
        observation.enhance_control_visible,
        observation.action_mode,
        observation.auto_select_enabled,
        observation.cost_type,
        observation.cost_amount,
        observation.overlay_state,
        observation.reset_guard_active,
        observation.game_day_id,
        observation.recognized,
    )


def _rerun_semantics(
    result: Mapping[str, Any], session: Path, frame_hashes: set[str],
    *, checkpoint: Callable[[], None] | None = None,
) -> bool:
    from scripts.enhancement_bluestacks import recognize_commander_stage, recognize_home_frame

    _verification_checkpoint(checkpoint)
    default_variant = str(result.get("variant") or "")
    route = result.get("enhancement_result")
    if not isinstance(route, Mapping):
        return False
    reset = str(route.get("reset_identity") or "")
    if result.get("reset_identity") not in (None, reset):
        return False
    stages = route.get("stages")
    if not isinstance(stages, list) or not stages:
        return False
    try:
        proofs = _ordered_category_proofs(route)
    except Exception:
        return False
    replayed_categories: dict[str, tuple[EnhancementObservation, EnhancementObservation]] = {}
    retained_categories: set[str] = set()
    try:
        rows = _read_event_rows(_retained_path(
            session, str(result.get("events_path") or "events.jsonl"), "event journal",
        ))
        retained_proofs = {}
        for proof in proofs:
            _verification_checkpoint(checkpoint)
            category = str(proof["variant"])
            source = proof.get("runtime_session")
            if not isinstance(source, str) or not source:
                return False
            if Path(source).resolve() == session.resolve():
                replayed_categories[category] = _replay_category_observations(
                    proof, variant=category, reset=reset, session=session, rows=rows,
                    frame_hashes=frame_hashes, actions=result.get("actions"),
                    checkpoint=checkpoint,
                )
            else:
                retained_proofs[category] = proof
                retained_categories.add(category)
        _verify_retained_categories(retained_proofs, reset, checkpoint=checkpoint)
    except _VerificationInterrupted:
        raise
    except Exception:
        return False
    recognized_records: list[tuple[str, str, str]] = []
    recognized_observations: dict[tuple[str, str, str], EnhancementObservation] = {}
    home_terminal_hashes: set[str] = set()
    frames_by_hash: dict[str, list[Path]] = {}
    for path in (session / "frames").glob("*.png"):
        _verification_checkpoint(checkpoint)
        frames_by_hash.setdefault(_decode_native(path), []).append(path)
    for stage in stages:
        _verification_checkpoint(checkpoint)
        if (
            not isinstance(stage, Mapping)
            or stage.get("kind") != "recognition"
            or stage.get("recognized") is not True
        ):
            continue
        observation = None
        digest = stage.get("frame_sha256")
        if not isinstance(digest, str) or digest not in frame_hashes:
            return False
        refs = frames_by_hash.get(digest, [])
        if not refs or _decode_native(refs[0]) != digest:
            return False
        frame = cv2.imread(str(refs[0]), cv2.IMREAD_COLOR)
        name = str(stage.get("stage") or "")
        variant = str(stage.get("variant") or default_variant)
        if variant not in SUPPORTED_VARIANTS:
            return False
        stage_name = _semantic_stage_for_phase(
            name, detail_state=str(stage.get("detail_state") or "") or None,
        )
        if stage_name == "home":
            recognition = recognize_home_frame(frame, source_frame_sha256=digest)
            if name == "family-home-terminal" or name.startswith((
                "return-home-immediate-post",
                "return-home-settled",
                "return-home-source-",
                "return-home-1-",
                "return-home-2-",
                "return-home-3-",
                "commander-to-home-terminal-immediate-post",
                "commander-to-home-terminal-settled",
            )):
                home_terminal_hashes.add(digest)
        elif stage_name is not None:
            if name.startswith("use-one-star-enhancer-") and name.endswith("-immediate-before"):
                if variant in retained_categories:
                    return False
                before = replayed_categories[variant][0]
                if before.source_frame_sha256 != digest:
                    return False
                observation = before
                recognition = None
            else:
                recognition = recognize_commander_stage(
                    frame, variant=variant, stage=stage_name,
                    source_frame_sha256=digest, evidence_ref=refs[0],
                    game_day_id=reset,
                )
        else:
            return False
        _verification_checkpoint(checkpoint)
        if recognition is not None and not recognition.recognized:
            return False
        if recognition is not None:
            observation = getattr(recognition, "observation", None)
        requires_native_observation = (
            stage_name == "post"
            or name.startswith("use-one-star-enhancer-")
        )
        if requires_native_observation:
            if not isinstance(observation, EnhancementObservation):
                return False
            try:
                _validate_native_observation_contract(observation, f"replayed {name}")
            except Exception:
                return False
            recognized_observations[(variant, name, digest)] = observation
        recognized_records.append((variant, name, digest))
    if not recognized_records or not home_terminal_hashes:
        return False
    for category in ("gear", "chip", "module"):
        _verification_checkpoint(checkpoint)
        proof = next(
            (
                value for value in proofs
                if isinstance(value, Mapping) and value.get("variant") == category
            ),
            None,
        )
        if not isinstance(proof, Mapping):
            return False
        if category in retained_categories:
            continue
        before = proof.get("before_observation")
        successor = proof.get("successor_observation")
        if not isinstance(before, Mapping) or not isinstance(successor, Mapping):
            return False
        before_hash = before.get("source_frame_sha256")
        successor_hash = successor.get("source_frame_sha256")
        if not isinstance(before_hash, str) or not isinstance(successor_hash, str):
            return False
        if not any(
            variant == category
            and digest == before_hash
            and name.startswith("use-one-star-enhancer-")
            and name.endswith("-immediate-before")
            for variant, name, digest in recognized_records
        ):
            return False
        if not any(
            variant == category
            and digest == successor_hash
            and name.startswith("enhancement-settle-")
            for variant, name, digest in recognized_records
        ):
            return False
        before_key = next(
            (
                (variant, name, digest)
                for variant, name, digest in recognized_records
                if variant == category
                and digest == before_hash
                and name.startswith("use-one-star-enhancer-")
                and name.endswith("-immediate-before")
            ),
            None,
        )
        successor_key = next(
            (
                (variant, name, digest)
                for variant, name, digest in recognized_records
                if variant == category
                and digest == successor_hash
                and name.startswith("enhancement-settle-")
            ),
            None,
        )
        if before_key is None or successor_key is None:
            return False
        replayed_before = recognized_observations.get(before_key)
        replayed_successor = recognized_observations.get(successor_key)
        if replayed_before is None or replayed_successor is None:
            return False
        try:
            retained_before = _observation(before, f"{category} retained before")
            retained_successor = _observation(
                successor, f"{category} retained successor"
            )
        except Exception:
            return False
        if (
            _native_observation_semantics(replayed_before)
            != _native_observation_semantics(retained_before)
            or _native_observation_semantics(replayed_successor)
            != _native_observation_semantics(retained_successor)
            or not enhancement_bluestacks_authorizeable(
                replayed_before, variant=category
            )
            or not enhancement_bluestacks_postcondition_verified(
                replayed_before, replayed_successor, variant=category
            )
        ):
            return False
    terminal_hash = route.get("terminal_frame_sha256")
    _verification_checkpoint(checkpoint)
    return isinstance(terminal_hash, str) and terminal_hash in home_terminal_hashes


def _original_no_effect_attempt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the immutable original record for read-only public verification."""
    session = Path(str(receipt.get("original_runtime_session") or ""))
    path = _retained_path(session, "flow-delivery-result.json", "original no-effect result")
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement original no-effect result is missing")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Enhancement original no-effect result is unreadable") from exc
    route = result.get("enhancement_result") if isinstance(result, Mapping) else None
    categories = route.get("category_results") if isinstance(route, Mapping) else None
    if not isinstance(categories, list):
        raise _pnsctl().OperatorError("Enhancement original no-effect category proof is missing")
    matches = [value for value in categories if isinstance(value, Mapping)
               and value.get("resource_affecting_action_key") == receipt.get("original_action_key")]
    if len(matches) != 1:
        raise _pnsctl().OperatorError("Enhancement original no-effect category is not unique")
    original = dict(matches[0])
    if original.get("runtime_session") != str(session):
        raise _pnsctl().OperatorError("Enhancement original no-effect session is inconsistent")
    return original


def _verify_family_startup_step(recovery, session, rows, reset, dispatch_row, *, final):
    from scripts.enhancement_bluestacks import recognize_home_frame
    from scripts.startup_recovery import (
        SCARLETT_SAFE_BACK_TARGET_IDENTITY, VIP_RESET_TARGET, classify_startup_frame, contextual_startup_identity,
    )

    if (not isinstance(recovery, Mapping) or type(recovery.get("input_count")) is not int
            or recovery["input_count"] != 1 or recovery.get("confirmed") is not True):
        raise _pnsctl().OperatorError("Enhancement startup recovery accounting is missing")
    source = _context_capture(session, rows, recovery["source_frame"], reset=reset)
    settled = _context_capture(session, rows, recovery["settled_frame"], reset=reset)
    index, dispatch = dispatch_row
    prior = [row for row in rows[:index] if row.get("type") == "capture"]
    if not prior:
        raise _pnsctl().OperatorError("Enhancement startup immediate source is missing")
    immediate = _context_capture(session, rows, prior[-1]["path"], reset=reset)
    proposal = classify_startup_frame(FLOW_ID, source[0].png)
    current = classify_startup_frame(FLOW_ID, immediate[0].png)
    detail = current.recognition or {}
    target = detail.get("target") or detail.get("safe_exit_roi")
    identity = VIP_RESET_TARGET if current.popup_identity == "VIP_POINTS_GET_PTS" else SCARLETT_SAFE_BACK_TARGET_IDENTITY
    vip = identity == VIP_RESET_TARGET
    before_label = "contextual-vip-popup-dispatch-before" if vip else "contextual-startup-scarlett-before"
    post_label = "contextual-vip-popup-post" if vip else "contextual-startup-scarlett-post"
    if (
        proposal.status != "recovery_required" or current.status != "recovery_required"
        or prior[-1].get("label") != before_label or rows[settled[1]].get("label") != post_label
        or (not vip and tuple((proposal.recognition or {}).get("safe_exit_roi") or ()) != tuple(target or ()))
        or contextual_startup_identity(source[0]) != recovery.get("popup_identity")
        or contextual_startup_identity(immediate[0]) != recovery.get("popup_identity")
        or recovery.get("immediate_before_frame") != immediate[0].path.resolve().relative_to(session.resolve()).as_posix()
        or recovery.get("immediate_before_sha256") != immediate[0].sha256
        or recovery.get("immediate_before_captured_monotonic") != immediate[0].captured_monotonic
        or recovery.get("source_captured_monotonic") != source[0].captured_monotonic
        or recovery.get("settled_captured_monotonic") != settled[0].captured_monotonic
        or recovery.get("target_identity") != identity or tuple(recovery.get("target_roi") or ()) != tuple(target or ())
        or proposal.popup_identity != current.popup_identity or current.popup_identity != recovery.get("popup_identity")
        or source[0].sha256 != recovery.get("source_sha256")
        or settled[0].sha256 != recovery.get("settled_sha256")
        or not source[1] < immediate[1] < index < settled[1]
        or not source[0].captured_monotonic < immediate[0].captured_monotonic < settled[0].captured_monotonic
        or len([row for row in rows[source[1]:settled[1]] if row.get("type") == "dispatch"]) != 1
        or dispatch.get("action_key") != recovery.get("action_key")
        or dispatch.get("target_identity") != identity or target is None
        or tuple(dispatch.get("target_roi") or ()) != tuple(target)
        or tuple(dispatch.get("point") or ()) != ((target[0] + target[2]) // 2, (target[1] + target[3]) // 2)
        or dispatch.get("source_sha256") != immediate[0].sha256
        or dispatch.get("execute") is not True or dispatch.get("action_class") != "navigation"
        or dispatch.get("consequential") is not False
        or not immediate[2] <= _event_utc(dispatch, "startup input") <= settled[2]
        or (final and (classify_startup_frame(FLOW_ID, settled[0].png).status != "clear"
            or not recognize_home_frame(settled[0].frame, source_frame_sha256=settled[0].sha256).recognized))
    ):
        raise _pnsctl().OperatorError("Enhancement startup recovery cannot be independently replayed")
    return source, settled, current, immediate


def _verify_family_startup(result, session, rows):
    from scripts.startup_recovery import (
        SCARLETT_SAFE_BACK_TARGET_IDENTITY, VIP_RESET_TARGET, classify_startup_frame, contextual_startup_action_key,
    )

    recovery = result.get("startup_recovery")
    dispatches = [(index, row) for index, row in enumerate(rows)
                  if row.get("type") == "dispatch" and (
                      row.get("target_identity") in {VIP_RESET_TARGET, SCARLETT_SAFE_BACK_TARGET_IDENTITY}
                      or str(row.get("action_key") or "").startswith("enhancement:startup:"))]
    if recovery is None and not dispatches:
        return
    steps = recovery.get("steps") if isinstance(recovery, Mapping) else None
    if (not isinstance(steps, list) or not 1 <= len(steps) <= 2
            or type(recovery.get("input_count")) is not int
            or recovery["input_count"] != len(steps) or len(dispatches) != len(steps)):
        raise _pnsctl().OperatorError("Enhancement startup recovery accounting is missing")
    all_dispatches = [(index, row) for index, row in enumerate(rows) if row.get("type") == "dispatch"]
    if all_dispatches[:len(dispatches)] != dispatches:
        raise _pnsctl().OperatorError("Enhancement startup must precede every route and resource dispatch")
    reset = result["enhancement_result"]["reset_identity"]
    previous = None
    previous_reconcile_index = None
    identities = set()
    for ordinal, (step, dispatch) in enumerate(zip(steps, dispatches)):
        if not isinstance(step, Mapping) or step.get("action_key") != contextual_startup_action_key(
                f"enhancement:startup:{session.name}", ordinal):
            raise _pnsctl().OperatorError("Enhancement startup action sequence is not current")
        source, settled, current, immediate = _verify_family_startup_step(
            step, session, rows, reset, dispatch, final=ordinal == len(steps) - 1,
        )
        if current.popup_identity in identities:
            raise _pnsctl().OperatorError("Enhancement startup repeated a known surface")
        identities.add(current.popup_identity)
        if previous is not None and (source[1] != previous[1] or source[0].sha256 != previous[0].sha256):
            raise _pnsctl().OperatorError("Enhancement startup stack is not continuous")
        reconciles = [(index, row) for index, row in enumerate(rows)
                      if row.get("type") == "reconcile" and row.get("action_key") == step.get("action_key")]
        if (len(reconciles) != 1 or reconciles[0][1].get("status") != "confirmed"
                or reconciles[0][1].get("post_sha256") != settled[0].sha256
                or reconciles[0][0] <= settled[1]
                or (previous_reconcile_index is not None and previous_reconcile_index >= immediate[1])):
            raise _pnsctl().OperatorError("Enhancement startup dismissal is not reconciled")
        if ordinal != len(steps) - 1:
            successor = classify_startup_frame(FLOW_ID, settled[0].png)
            if (successor.status != "recovery_required" or successor.popup_identity in identities
                    or successor.popup_identity != steps[ordinal + 1].get("popup_identity")):
                raise _pnsctl().OperatorError("Enhancement startup stack has an unexpected successor")
        previous = settled
        previous_reconcile_index = reconciles[0][0]
    if len(all_dispatches) > len(dispatches) and previous_reconcile_index >= all_dispatches[len(dispatches)][0]:
        raise _pnsctl().OperatorError("Enhancement startup must reconcile before any route or resource dispatch")


def verify_enhancement_family(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    del queue
    checkpoint = lease.get("checkpoint")
    _verification_checkpoint(checkpoint)
    result, session, rows, frame_hashes = _verify_native_structure(structure, checkpoint=checkpoint)
    route = result.get("enhancement_result")
    if not isinstance(route, Mapping):
        return {"status": "evidence_required", "flow_id": FLOW_ID, "reason": "route semantics missing"}
    if result.get("status") == "recovered_successor":
        receipt = route.get("successor_receipt")
        if not isinstance(receipt, Mapping) or not _same_validated_path_identity(
            receipt.get("recovery_session_directory"), session
        ):
            raise _pnsctl().OperatorError("Enhancement settled recovery receipt is not bound")
        original = _original_no_effect_attempt(receipt)
        receipt_path = _retained_path(session, _POSITIVE_RECEIPT_NAME, "settled successor receipt")
        encoded = receipt_path.read_bytes()
        if json.loads(encoded) != receipt:
            raise _pnsctl().OperatorError("Enhancement retained settled receipt differs")
        _validate_positive_receipt(original, str(original.get("variant") or ""),
            str(receipt.get("reset_identity") or ""), receipt, checkpoint=checkpoint)
        return {"status": "evidence_required", "flow_id": FLOW_ID,
                "variant": result.get("variant"), "session_directory": str(session),
                "reason": "settled successor reconciled; family remains incomplete",
                "successor_recovered": True, "family_completed": False,
                "dispatch_count": 0, "input_count": 0}
    if result.get("status") == _RECOVERED_NO_EFFECT_STATUS:
        if (
            route.get("status") != _RECOVERED_NO_EFFECT_STATUS
            or result.get("input_count") != 0
            or result.get("dispatch_count") != 0
            or result.get("resource_affecting_dispatch_count") != 0
            or route.get("proof_kind") != _ZERO_SELECTED_CONFIRM_PROOF
        ):
            raise _pnsctl().OperatorError("Enhancement no-effect recovery accounting is invalid")
        receipt = route.get("no_effect_receipt")
        if not isinstance(receipt, Mapping) or not _same_validated_path_identity(
            receipt.get("recovery_session_directory"), session
        ):
            raise _pnsctl().OperatorError("Enhancement no-effect receipt is not bound to recovery")
        original = _original_no_effect_attempt(receipt)
        _validate_zero_selected_no_effect_receipt(
            receipt, original, variant=str(original.get("variant") or ""),
            reset_identity=str(receipt.get("reset_identity") or ""),
            require_retained_receipt=True,
        )
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result.get("variant"),
            "session_directory": str(session),
            "reason": "confirmed no-effect recovery is not family completion",
            "no_effect_recovered": True,
            "family_completed": False,
            "dispatch_count": 0,
            "input_count": 0,
        }
    initial = result.get("initial_observation")
    trace = result.get("causal_trace")
    initial_ok = False
    if isinstance(initial, Mapping):
        digest = str(initial.get("frame_sha256") or "")
        frame_path = str(initial.get("frame_path") or "")
        try:
            retained_initial = _retained_path(
                session, frame_path, "initial observation"
            )
            initial_ok = bool(
                _HASH_RE.fullmatch(digest)
                and retained_initial.is_file()
                and _decode_native(retained_initial) == digest
                and digest == result.get("initial_frame_sha256")
                and str(initial.get("invocation_id") or "")
            )
        except Exception:
            initial_ok = False
    dispatch_count = len(_dispatch_rows(rows))
    resource_count = len(_resource_dispatch_rows(rows))
    trace_ok = bool(
        result.get("causal_trace_count") == 1
        and isinstance(trace, Mapping)
        and trace.get("trace_count") == 1
        and trace.get("read_only") is True
        and trace.get("input_authority") is False
        and trace.get("flow_id") == FLOW_ID
        and trace.get("proof_topology") == result.get("proof_topology")
        and trace.get("initial_frame_sha256") == result.get("initial_frame_sha256")
        and trace.get("transport_count") == dispatch_count
        and trace.get("resource_affecting_dispatch_count") == resource_count
    )
    if (
        not initial_ok
        or not trace_ok
        or result.get("proof_topology") not in {"continuous", "composite"}
        or type(result.get("input_count")) is not int or result.get("input_count") != dispatch_count
        or type(result.get("resource_affecting_dispatch_count")) is not int
        or result.get("resource_affecting_dispatch_count") != resource_count
        or result.get("effect_reconciliation_required") is not False
    ):
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result["variant"],
            "session_directory": str(session),
            "initial_observation_verified": initial_ok,
            "causal_trace_verified": trace_ok,
            "proof_topology": result.get("proof_topology"),
            "transport_accounting_verified": dispatch_count == result.get("dispatch_count"),
        }
    if result["status"] != "completed":
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result["variant"],
            "session_directory": str(session),
            "dispatch_count": result["dispatch_count"],
        }
    _verify_family_startup(result, session, rows)
    if (
        route.get("postcondition_verified") is not True
        or route.get("terminal_recognized") is not True
        or route.get("state_transition") != [
            "HOME_CANONICAL",
            "COMMANDER_INFO_RECOGNIZED",
            "GEAR_SUCCESSOR_RECONCILED",
            "CHIP_SUCCESSOR_RECONCILED",
            "MODULE_SUCCESSOR_RECONCILED",
            "SAFE_TERMINAL_RECOGNIZED",
        ]
    ):
        raise _pnsctl().OperatorError("completed Enhancement family lacks ordered terminal proof")
    proofs = _ordered_category_proofs(route)
    if route.get("resource_affecting_dispatch_count") != 3:
        raise _pnsctl().OperatorError("completed Enhancement family requires three Uses")
    reset = _validate_family_reset(str(route.get("reset_identity") or ""))
    current_categories: list[str] = []
    retained: dict[str, Mapping[str, Any]] = {}
    source_proofs: dict[str, dict[str, Any]] = {}
    delivery_digest = hashlib.sha256((session / "flow-delivery-result.json").read_bytes()).hexdigest()
    for proof in proofs:
        category = proof["variant"]
        source = proof.get("runtime_session")
        if not isinstance(source, str) or not source or not Path(source).is_absolute():
            raise _pnsctl().OperatorError("Enhancement family category source is missing")
        if Path(source).resolve() == session:
            current_categories.append(category)
            source_proofs[category] = {
                "status": "verified", "variant": category, "reset_identity": reset,
                "runtime_session": str(session), "delivery_sha256": delivery_digest,
                "resource_affecting_action_key": proof.get("resource_affecting_action_key"),
            }
        else:
            retained[category] = proof
    topology = "composite" if retained else "continuous"
    if result.get("proof_topology") != topology:
        raise _pnsctl().OperatorError("Enhancement family topology does not match its actual category sources")
    if topology == "continuous" and [proof["variant"] for proof in route["category_results"]] != ["gear", "chip", "module"]:
        raise _pnsctl().OperatorError("Enhancement continuous family category order is invalid")
    source_proofs.update(_verify_retained_categories(retained, reset, checkpoint=checkpoint))
    _verify_event_order(rows, route, frame_hashes, current_categories=tuple(current_categories))
    for category, proof in zip(("gear", "chip", "module"), proofs):
        _verification_checkpoint(checkpoint)
        before = _observation(proof.get("before_observation"), f"{category} before")
        after = _observation(proof.get("successor_observation"), f"{category} successor")
        if before.game_day_id != reset or after.game_day_id != reset:
            raise _pnsctl().OperatorError("Enhancement category proof crosses its current reset")
        if category in current_categories:
            _verify_observation_binding(before, session, frame_hashes, f"{category} before")
            _verify_observation_binding(after, session, frame_hashes, f"{category} successor")
        if not enhancement_bluestacks_authorizeable(before, variant=category):
            raise _pnsctl().OperatorError(f"Enhancement {category} immediate-before is not authorized")
        if not enhancement_bluestacks_postcondition_verified(before, after, variant=category):
            raise _pnsctl().OperatorError(f"Enhancement {category} same-item successor is not proven")
    variant = "family"
    terminal_hash = _require_hash(route.get("terminal_frame_sha256"), "terminal")
    if terminal_hash not in frame_hashes or (dispatch_count and terminal_hash == _require_hash(
        route.get("source_frame_sha256"), "route source"
    )):
        raise _pnsctl().OperatorError("Enhancement terminal frame is missing or reused source")
    if not _rerun_semantics(result, session, frame_hashes, checkpoint=checkpoint):
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": variant,
            "session_directory": str(session),
            "reason": "independent semantic re-recognition unavailable",
        }
    _verification_checkpoint(checkpoint)
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "variant": variant,
        "session_directory": str(session),
        "dispatch_count": result["dispatch_count"],
        "item_identity": before.selected_item_identity,
        "postcondition_verified": True,
        "independent_rerecognition": True,
        "initial_observation_verified": initial_ok,
        "causal_trace_verified": trace_ok,
        "transport_accounting_verified": True,
        "proof_topology": topology,
        "categories_verified": ["gear", "chip", "module"],
        "current_categories": current_categories,
        "retained_categories": [category for category in ("gear", "chip", "module") if category in retained],
        "retained_category_count": len(retained),
        "current_resource_affecting_dispatch_count": resource_count,
        "category_source_proofs": {category: source_proofs[category] for category in ("gear", "chip", "module")},
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def recover_enhancement_family(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    recovery_lease = dict(lease)
    recovery_lease["enhancement_recovery_only"] = True
    recovery_lease.setdefault("enhancement_variant", "gear")
    recovery_lease.setdefault("max_inputs", 1)
    recovery_lease.setdefault("enhancement_reset_identity", _stamp())
    return run_enhancement_family(queue, recovery_lease, live=True)


def register(
    runners: dict[str, Any], validators: dict[str, Any], handlers: dict[str, Any]
) -> None:
    runners[RUNNER_ID] = run_enhancement_family
    validators[VALIDATOR_ID] = verify_enhancement_family
    handlers[RECOVERY_ID] = recover_enhancement_family


run_enhancement_bluestacks = run_enhancement_family
verify_enhancement_bluestacks = verify_enhancement_family
recover_enhancement_bluestacks = recover_enhancement_family
