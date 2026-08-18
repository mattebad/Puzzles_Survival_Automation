"""Checked-in delivery, reservation, and evidence validation for Commander enhancement."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)


FLOW_ID = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
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
_PRE_RUNTIME_IMPORT_FAILURE_RE = re.compile(
    r"^Traceback \(most recent call last\):\r?\n"
    r'  File "[^"\r\n]*[\\/]+scripts[\\/]+enhancement_bluestacks\.py", '
    r"line \d+, in <module>\r?\n"
    r"    from scripts\.bluestacks_native_runtime import \(\r?\n"
    r"ModuleNotFoundError: No module named 'scripts'\r?\n?$"
)


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


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
        cursor = raw
        while True:
            if cursor.is_symlink():
                raise _pnsctl().OperatorError(f"Enhancement {field} reference contains a symlink")
            if cursor == cursor.parent:
                break
            cursor = cursor.parent
        resolved = raw.resolve()
        resolved.relative_to(session.resolve())
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


def _ensure_family_reservations(flow_root: Path) -> dict[str, Path]:
    """Keep one durable dispatch reservation for every ordered category."""
    reservations: dict[str, Path] = {}
    for variant in ("gear", "chip", "module"):
        path = flow_root / f"reservation-{variant}.json"
        if path.exists():
            if path.is_symlink() or not path.is_file():
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
            ):
                raise _pnsctl().OperatorError(f"Enhancement {variant} reservation is malformed")
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


def _outer_session(lease: Mapping[str, Any]) -> Any:
    session = lease.get("development_session")
    if (
        session is None
        or not callable(getattr(session, "run_action", None))
        or not callable(getattr(session, "observe", None))
    ):
        raise _pnsctl().OperatorError("Enhancement flow requires the pnsctl-owned DevelopmentSession")
    return session


def _load_family_progress(flow_root: Path) -> dict[str, dict[str, Any]]:
    path = flow_root / "family-progress.json"
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
    for variant, value in categories.items():
        if variant not in {"gear", "chip", "module"}:
            raise _pnsctl().OperatorError("Enhancement family progress has an unknown category")
        if (
            isinstance(value, Mapping)
            and value.get("status") == "dispatch_bearing_unresolved"
            and _is_reconciled_quantity_setup(value)
        ):
            continue
        if isinstance(value, Mapping) and value.get("status") == "dispatch_bearing_unresolved":
            raise _pnsctl().OperatorError(
                f"Enhancement {variant} has an unresolved dispatch-bearing Use; continuation is blocked"
            )
        if not isinstance(value, Mapping) or value.get("status") != "completed":
            continue
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
        proof = value if reconciled else match
        before = _observation(proof["before_observation"], f"{variant} retained before")
        successor = _observation(proof["successor_observation"], f"{variant} retained successor")
        if not enhancement_bluestacks_postcondition_verified(before, successor, variant=variant):
            raise _pnsctl().OperatorError("Enhancement retained successor proof is invalid")
        completed[variant] = dict(value)
    return completed


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
    completed = _load_family_progress(flow_root)
    for value in route.get("category_results", []):
        if isinstance(value, Mapping) and value.get("status") in {
            "completed", "dispatch_bearing_unresolved"
        }:
            variant = str(value.get("variant") or "")
            if variant in {"gear", "chip", "module"}:
                completed[variant] = dict(value)
    if not completed:
        return
    flow_root.mkdir(parents=True, exist_ok=True)
    (flow_root / "family-progress.json").write_text(
        json.dumps(
            {"schema_version": 1, "flow_id": FLOW_ID, "categories": completed},
            indent=2, sort_keys=True, default=str,
        ) + "\n",
        encoding="utf-8",
    )


def _persist_unresolved_dispatch(
    flow_root: Path, runtime_session: Path, rows: list[Mapping[str, Any]],
    route: Mapping[str, Any] | None,
) -> None:
    categories: dict[str, Any] = {}
    progress_path = flow_root / "family-progress.json"
    if progress_path.is_file() and not progress_path.is_symlink():
        try:
            prior = json.loads(progress_path.read_text(encoding="utf-8"))
            categories.update(prior.get("categories", {}))
        except (OSError, UnicodeError, json.JSONDecodeError):
            categories = {}
    if isinstance(route, Mapping):
        for proof in route.get("category_results", []):
            if isinstance(proof, Mapping) and proof.get("status") == "completed":
                categories[str(proof.get("variant"))] = dict(proof)
    for row in _resource_dispatch_rows(rows):
        key = str(row.get("action_key") or "")
        match = re.match(r"enhancement:(gear|chip|module):", key)
        if match and match.group(1) not in categories:
            categories[match.group(1)] = {
                "variant": match.group(1),
                "status": "dispatch_bearing_unresolved",
                "resource_affecting_dispatch_count": 1,
                "resource_affecting_action_key": key,
                "runtime_session": str(runtime_session),
            }
    if categories:
        flow_root.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps({"schema_version": 1, "flow_id": FLOW_ID, "categories": categories},
                       indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


def _reconcile_recovery_successor(
    flow_root: Path, variant: str, route: Mapping[str, Any]
) -> None:
    progress_path = flow_root / "family-progress.json"
    if not progress_path.is_file() or progress_path.is_symlink():
        raise _pnsctl().OperatorError(
            "Enhancement recovery has no regular family progress file"
        )
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        categories = progress["categories"]
        retained = categories[variant]
        before = EnhancementObservation(**retained["before_observation"])
        after = EnhancementObservation(**route["successor_observation"])
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _pnsctl().OperatorError(
            "Enhancement recovery evidence is malformed"
        ) from exc
    if (
        retained.get("status") != "dispatch_bearing_unresolved"
        or not enhancement_bluestacks_postcondition_verified(
            before, after, variant=variant
        )
    ):
        raise _pnsctl().OperatorError(
            "Enhancement recovery does not prove the retained dispatch successor"
        )
    categories[variant] = {
        **dict(retained),
        "status": "completed",
        "successor_observation": dict(route["successor_observation"]),
        "successor_evidence_ref": str(route.get("successor_evidence_ref") or ""),
        "reconciliation": "zero-input settled successor",
    }
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


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
    flow_root = (pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID).resolve()
    reservations: dict[str, Path] = {}
    completed_categories: dict[str, dict[str, Any]] = {}
    if live and not recovery_only:
        reservations = _ensure_family_reservations(flow_root)
        completed_categories = _load_family_progress(flow_root)
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
    reset_identity = str(lease.get("enhancement_reset_identity") or "").strip()
    if recovery_only:
        progress_path = flow_root / "family-progress.json"
        if progress_path.is_file() and not progress_path.is_symlink():
            try:
                retained_progress = json.loads(progress_path.read_text(encoding="utf-8"))
                retained_day = retained_progress["categories"][variant][
                    "before_observation"
                ]["game_day_id"]
                if retained_day:
                    reset_identity = str(retained_day)
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
            ):
                pass
    if not reset_identity:
        raise pnsctl.OperatorError("Enhancement reset identity is required")
    outer_session = _outer_session(lease)
    outer_directory = Path(outer_session.session_directory)
    runtime: LocalBlueStacksRuntime | None = None
    runtime_session = outer_directory
    route: dict[str, Any] | None = None
    previous_limit = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    try:
        os.environ["PNS_DEVELOPMENT_MAX_INPUTS"] = str(maximum)
        runtime = LocalBlueStacksRuntime.connect(
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            output_directory=outer_directory / "runtime",
            workflow="enhancement-family",
            execute=True,
        )
        runtime_session = runtime.session
        from scripts.enhancement_bluestacks import EnhancementIntegratedRoute, run_recovery

        route = (
            run_recovery(
                runtime,
                variant=variant,
                reset_identity=reset_identity,
                session=outer_session,
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
        if recovery_only and route.get("status") == "recovered_successor":
            _reconcile_recovery_successor(flow_root, variant, route)
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
        if runtime is not None:
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
    }:
        raise pnsctl.OperatorError("Enhancement route returned an unknown terminal status")
    delivery_status = (
        "completed"
        if route_status == "completed" and route.get("terminal_recognized") is True
        else "unresolved"
        if route_status in {"unresolved", "evidence_required", "manual_required"}
        else "blocked"
    )
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "variant": "family",
        "serial": pnsctl.BLUESTACKS_SERIAL,
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
        "dispatch": bool(dispatches),
        "dispatch_count": len(dispatches),
        "input_count": input_count,
        "max_inputs": maximum,
        "resource_affecting_dispatch_count": len(resource_dispatches),
        "enhancement_result": route,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (runtime_session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
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
        },
        sort_keys=True,
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
    try:
        return EnhancementObservation(**payload)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(f"Enhancement {field} observation is malformed") from exc


def _verify_native_structure(
    structure: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], set[str]]:
    pnsctl = _pnsctl()
    result = structure.get("result")
    if not isinstance(result, dict) or result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Enhancement evidence belongs to another flow")
    variant = str(result.get("variant") or "").lower()
    if variant != "family":
        raise pnsctl.OperatorError("Enhancement evidence must be an R4 family result")
    raw_session = Path(str(structure.get("session_directory") or ""))
    cursor = raw_session
    while True:
        if cursor.is_symlink():
            raise pnsctl.OperatorError("Enhancement evidence session path contains a symlink")
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    session = raw_session.resolve()
    if not session.is_dir() or session.is_symlink():
        raise pnsctl.OperatorError("Enhancement evidence session directory is unavailable")
    delivery_path = session / "flow-delivery-result.json"
    if not delivery_path.is_file() or delivery_path.is_symlink():
        raise pnsctl.OperatorError("Enhancement flow-delivery-result.json is required")
    retained = json.loads(delivery_path.read_text(encoding="utf-8"))
    if retained != json.loads(json.dumps(result, sort_keys=True, default=str)):
        raise pnsctl.OperatorError("Enhancement retained result does not match verifier input")
    if (
        result.get("serial") != pnsctl.BLUESTACKS_SERIAL
        or (result.get("native_width"), result.get("native_height")) != (800, 1280)
        or result.get("production_registration") != "NOT_REGISTERED"
        or result.get("scheduler_enabled") is not False
    ):
        raise pnsctl.OperatorError("Enhancement evidence runtime or registration profile is invalid")
    if result.get("status") not in {
        "completed", "blocked", "evidence_required", "unresolved", "manual_required"
    }:
        raise pnsctl.OperatorError("Enhancement delivery status is invalid")
    frames = structure.get("frames") or result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise pnsctl.OperatorError("Enhancement native frame evidence is required")
    frame_hashes: set[str] = set()
    for value in frames:
        if not isinstance(value, str) or not value:
            raise pnsctl.OperatorError("Enhancement frame references are invalid")
        path = _retained_path(session, value, "frame")
        if not path.is_file() or path.suffix.lower() != ".png":
            raise pnsctl.OperatorError("Enhancement frame evidence is missing or not PNG")
        frame_hashes.add(_decode_native(path))
    rows = _read_event_rows(session / str(result.get("events_path") or "events.jsonl"))
    declared = result.get("dispatch_count")
    if type(declared) is not int or declared != len(_dispatch_rows(rows)):
        raise pnsctl.OperatorError("Enhancement dispatch count does not match native events")
    if len(_resource_dispatch_rows(rows)) > MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS:
        raise pnsctl.OperatorError("Enhancement evidence exceeds the family resource Use limit")
    return result, session, rows, frame_hashes


def _verify_event_order(
    rows: list[dict[str, Any]], route: Mapping[str, Any], frame_hashes: set[str]
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
    proofs = route.get("category_results")
    if not isinstance(proofs, list) or [p.get("variant") for p in proofs if isinstance(p, Mapping)] != list(categories):
        raise _pnsctl().OperatorError("Enhancement family category proof order is invalid")
    if len(use_rows) != 3 or route.get("resource_affecting_dispatch_count") != 3:
        raise _pnsctl().OperatorError("Enhancement family requires exactly three resource Uses")
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
    if not observation.evidence_refs:
        raise _pnsctl().OperatorError(f"Enhancement {field} evidence reference is missing")
    for reference in observation.evidence_refs:
        path = _retained_path(session, str(reference), f"{field} evidence")
        if not path.is_file() or path.suffix.lower() != ".png":
            raise _pnsctl().OperatorError(f"Enhancement {field} evidence reference is invalid")
        if _decode_native(path) != digest:
            raise _pnsctl().OperatorError(f"Enhancement {field} evidence does not match its source")


def _rerun_semantics(result: Mapping[str, Any], session: Path, frame_hashes: set[str]) -> bool:
    from scripts.enhancement_bluestacks import recognize_commander_stage, recognize_home_frame

    default_variant = str(result.get("variant") or "")
    reset = str(result.get("reset_identity") or "")
    route = result.get("enhancement_result")
    if not isinstance(route, Mapping):
        return False
    stages = route.get("stages")
    if not isinstance(stages, list) or not stages:
        return False
    recognized_records: list[tuple[str, str, str]] = []
    home_terminal_hashes: set[str] = set()
    for stage in stages:
        if (
            not isinstance(stage, Mapping)
            or stage.get("kind") != "recognition"
            or stage.get("recognized") is not True
        ):
            continue
        digest = stage.get("frame_sha256")
        if not isinstance(digest, str) or digest not in frame_hashes:
            return False
        refs = [
            path for path in (session / "frames").glob("*.png")
            if _decode_native(path) == digest
        ]
        if not refs:
            return False
        frame = cv2.imread(str(refs[0]), cv2.IMREAD_COLOR)
        name = str(stage.get("stage") or "")
        variant = str(stage.get("variant") or default_variant)
        if variant == "family":
            continue
        if (
            name == "home-source"
            or name.startswith("home-to-commander-immediate-before")
            or (name.startswith("return-home") and name.endswith("immediate-post"))
        ):
            recognition = recognize_home_frame(frame, source_frame_sha256=digest)
            if name.startswith("return-home") and name.endswith("immediate-post"):
                home_terminal_hashes.add(digest)
        elif name.startswith(("commander", "category", "material", "enhancement", "select", "open", "use", "return-home")):
            stage_name = (
                "post" if any(token in name for token in ("settle", "terminal", "return-home"))
                else "material" if any(token in name for token in ("material", "use"))
                else "item"
            )
            recognition = recognize_commander_stage(
                frame, variant=variant, stage=stage_name,
                source_frame_sha256=digest, evidence_ref=refs[0],
                game_day_id=reset,
            )
        else:
            continue
        if not recognition.recognized:
            return False
        recognized_records.append((variant, name, digest))
    if not recognized_records or not home_terminal_hashes:
        return False
    proofs = route.get("category_results")
    if not isinstance(proofs, list):
        return False
    for category in ("gear", "chip", "module"):
        proof = next(
            (
                value for value in proofs
                if isinstance(value, Mapping) and value.get("variant") == category
            ),
            None,
        )
        if not isinstance(proof, Mapping):
            return False
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
    terminal_hash = route.get("terminal_frame_sha256")
    return isinstance(terminal_hash, str) and terminal_hash in home_terminal_hashes


def verify_enhancement_family(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    del queue, lease
    result, session, rows, frame_hashes = _verify_native_structure(structure)
    route = result.get("enhancement_result")
    if not isinstance(route, Mapping):
        return {"status": "evidence_required", "flow_id": FLOW_ID, "reason": "route semantics missing"}
    if result["status"] != "completed":
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result["variant"],
            "session_directory": str(session),
            "dispatch_count": result["dispatch_count"],
        }
    _verify_event_order(rows, route, frame_hashes)
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
    proofs = route.get("category_results")
    if route.get("resource_affecting_dispatch_count") != 3 or not isinstance(proofs, list):
        raise _pnsctl().OperatorError("completed Enhancement family requires three Uses")
    if [p.get("variant") for p in proofs if isinstance(p, Mapping)] != ["gear", "chip", "module"]:
        raise _pnsctl().OperatorError("completed Enhancement family category order is invalid")
    for category, proof in zip(("gear", "chip", "module"), proofs):
        before = _observation(proof.get("before_observation"), f"{category} before")
        after = _observation(proof.get("successor_observation"), f"{category} successor")
        _verify_observation_binding(before, session, frame_hashes, f"{category} before")
        _verify_observation_binding(after, session, frame_hashes, f"{category} successor")
        if not enhancement_bluestacks_authorizeable(before, variant=category):
            raise _pnsctl().OperatorError(f"Enhancement {category} immediate-before is not authorized")
        if not enhancement_bluestacks_postcondition_verified(before, after, variant=category):
            raise _pnsctl().OperatorError(f"Enhancement {category} same-item successor is not proven")
    variant = "family"
    terminal_hash = _require_hash(route.get("terminal_frame_sha256"), "terminal")
    if terminal_hash not in frame_hashes or terminal_hash == _require_hash(
        route.get("source_frame_sha256"), "route source"
    ):
        raise _pnsctl().OperatorError("Enhancement terminal frame is missing or reused source")
    if not _rerun_semantics(result, session, frame_hashes):
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": variant,
            "session_directory": str(session),
            "reason": "independent semantic re-recognition unavailable",
        }
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "variant": variant,
        "session_directory": str(session),
        "dispatch_count": result["dispatch_count"],
        "item_identity": before.selected_item_identity,
        "postcondition_verified": True,
        "independent_rerecognition": True,
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
