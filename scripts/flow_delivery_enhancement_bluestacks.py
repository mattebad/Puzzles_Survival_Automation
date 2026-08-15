"""Checked-in delivery, reservation, and evidence validation for native enhancement."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

import cv2

from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
RUNNER_ID = "enhancement_family_bluestacks_runner"
VALIDATOR_ID = "enhancement_family_bluestacks_evidence"
RECOVERY_ID = "enhancement_family_bluestacks_recovery"
MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY = 1
MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS = 3
MAX_DISPATCH_BEARING_CANARY_RUNS = MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS
MAX_DISPATCH_BEARING_CANARY_RUNS_PER_VARIANT = (
    MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_VARIANT_RE = re.compile(r"\b(?:gear|chip|module)\b", re.IGNORECASE)


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _session_max_inputs(lease: Mapping[str, Any]) -> int:
    try:
        value = int(
            lease.get("max_inputs", os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", 1))
        )
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError(
            "development session max_inputs is required"
        ) from exc
    if not 1 <= value <= 100:
        raise _pnsctl().OperatorError(
            "development session max_inputs must be between 1 and 100"
        )
    return value


def _result_line(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise _pnsctl().OperatorError("Enhancement route did not emit a JSON result")


def _read_event_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Enhancement event journal is missing")
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _pnsctl().OperatorError(
            "Enhancement event journal is unreadable"
        ) from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _pnsctl().OperatorError(
                "Enhancement event journal contains invalid JSON"
            ) from exc
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
            or row.get("target_identity") == "enhancement-confirm"
        )
    ]


def _variant_from_path(path: Path) -> str | None:
    match = re.search(
        r"(?:run|reservation)-(?P<variant>gear|chip|module)(?:-|\.|$)",
        str(path),
        re.IGNORECASE,
    )
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
        variant = None
        result_path = events_path.parent / "flow-delivery-result.json"
        if result_path.is_file() and not result_path.is_symlink():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise _pnsctl().OperatorError(
                    "prior Enhancement result is unreadable"
                ) from exc
            if isinstance(result, dict):
                variant = str(result.get("variant") or "").lower()
        variant = variant or _variant_from_path(events_path)
        if variant not in usage:
            raise _pnsctl().OperatorError(
                "dispatch-bearing Enhancement artifact has no category"
            )
        # A retained reservation already accounts for its run.  Only count a
        # dispatch artifact when its reservation is absent.
        reservation = flow_root / f"reservation-{variant}.json"
        if not reservation.is_file():
            usage[variant] += 1
    return usage


def _reserve(flow_root: Path, variant: str) -> Path:
    flow_root.mkdir(parents=True, exist_ok=True)
    usage = _artifact_usage(flow_root)
    if sum(usage.values()) >= MAX_TOTAL_DISPATCH_BEARING_CANARY_RUNS:
        raise _pnsctl().OperatorError(
            "Enhancement total dispatch-bearing canary budget is exhausted"
        )
    if usage[variant] >= MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY:
        raise _pnsctl().OperatorError(
            f"Enhancement {variant} dispatch-bearing canary budget is exhausted"
        )
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
    except FileExistsError as exc:
        raise _pnsctl().OperatorError(
            f"Enhancement {variant} has an unresolved canary reservation"
        ) from exc
    return path


def _clear_zero_dispatch_reservation(
    path: Path, rows: list[Mapping[str, Any]], route: Mapping[str, Any]
) -> None:
    if (
        path.is_file()
        and not _dispatch_rows(rows)
        and str(route.get("status") or "")
        in {"blocked", "evidence_required", "observed", "recovered_safe"}
        and route.get("terminal_recognized") is not True
    ):
        path.unlink()


def _native_frames(session: Path) -> list[str]:
    frame_dir = session / "frames"
    if not frame_dir.is_dir() or frame_dir.is_symlink():
        raise _pnsctl().OperatorError(
            "Enhancement route produced no native frame directory"
        )
    paths = sorted(
        path
        for path in frame_dir.glob("*.png")
        if path.is_file() and not path.is_symlink()
    )
    if not paths:
        raise _pnsctl().OperatorError(
            "Enhancement route produced no native frame evidence"
        )
    return [str(path.relative_to(session)).replace("\\", "/") for path in paths]


def run_enhancement_family(
    queue: Mapping[str, Any], lease: Mapping[str, Any], *, live: bool = True
) -> str:
    del queue
    pnsctl = _pnsctl()
    variant = str(lease.get("enhancement_variant") or "gear").strip().lower()
    if variant not in SUPPORTED_VARIANTS:
        raise pnsctl.OperatorError("Enhancement category is unsupported")
    maximum = _session_max_inputs(lease)
    recovery_only = bool(lease.get("enhancement_recovery_only"))
    flow_root = (pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID).resolve()
    reservation: Path | None = None
    if live and not recovery_only:
        reservation = _reserve(flow_root, variant)
    root = flow_root / f"run-{variant}-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "variant": variant,
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
    if not reset_identity:
        raise pnsctl.OperatorError("Enhancement reset identity is required")
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "enhancement_bluestacks.py"),
        "--adb",
        str(pnsctl.BLUESTACKS_ADB),
        "--serial",
        pnsctl.BLUESTACKS_SERIAL,
        "--variant",
        variant,
        "--reset-identity",
        reset_identity,
        "--output-directory",
        str(root),
        "--execute",
        "--yes",
    ]
    if recovery_only:
        command.append("--recovery-only")
    child_env = dict(os.environ)
    child_env["PNS_DEVELOPMENT_MAX_INPUTS"] = str(maximum)
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )
    (root / "operator-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (root / "operator-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    try:
        route = _result_line(completed.stdout or "")
        session = Path(str(route.get("session") or root)).resolve()
        if not session.is_dir():
            raise pnsctl.OperatorError(
                "Enhancement route session directory is unavailable"
            )
        frames = _native_frames(session)
        rows = _read_event_rows(session / "events.jsonl")
    except Exception:
        # The reservation deliberately remains durable on a crash or malformed
        # child result.  A later run must not consume the same canary.
        raise
    _clear_zero_dispatch_reservation(reservation or Path(), rows, route)
    dispatches = _dispatch_rows(rows)
    resource_dispatches = _resource_dispatch_rows(rows)
    if len(resource_dispatches) > 1:
        raise pnsctl.OperatorError(
            "Enhancement route repeated resource-affecting confirmation"
        )
    if len(dispatches) > maximum:
        raise pnsctl.OperatorError(
            "Enhancement route exceeded its development input bound"
        )
    route_status = str(route.get("status") or "unknown")
    if route_status not in {
        "completed",
        "blocked",
        "unresolved",
        "evidence_required",
        "manual_required",
        "observed",
        "recovered_safe",
    }:
        raise pnsctl.OperatorError(
            "Enhancement route returned an unknown terminal status"
        )
    delivery_status = (
        "completed"
        if route_status == "completed" and route.get("terminal_recognized") is True
        else (
            "evidence_required"
            if route_status in {"unresolved", "evidence_required", "manual_required"}
            else "blocked"
        )
    )
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "variant": variant,
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "terminal_runtime_state": "recognized_safe_terminal"
        if route.get("terminal_recognized") is True
        else "safe_blocked_terminal",
        "terminal_recognized": route.get("terminal_recognized") is True,
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "dispatch": bool(dispatches),
        "dispatch_count": len(dispatches),
        "resource_affecting_dispatch_count": len(resource_dispatches),
        "enhancement_result": route,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
        "operator_returncode": completed.returncode,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return json.dumps(
        {
            "status": delivery_status,
            "flow_id": FLOW_ID,
            "variant": variant,
            "session_directory": str(session),
            "dispatch": bool(dispatches),
            "dispatch_count": len(dispatches),
        },
        sort_keys=True,
    )


def _require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise _pnsctl().OperatorError(f"Enhancement {field} hash is invalid")
    return value


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
        raise _pnsctl().OperatorError(
            f"Enhancement {field} observation is malformed"
        ) from exc


def _decode_native(path: Path) -> str:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    image = cv2.imdecode(
        __import__("numpy").frombuffer(raw, dtype="uint8"), cv2.IMREAD_COLOR
    )
    if image is None or image.shape[:2] != (1280, 800):
        raise _pnsctl().OperatorError(
            "Enhancement retained frame is not a native 800x1280 PNG"
        )
    return digest


def _verify_native_structure(
    structure: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], set[str]]:
    pnsctl = _pnsctl()
    result = structure.get("result")
    if not isinstance(result, dict) or result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Enhancement evidence belongs to another flow")
    variant = str(result.get("variant") or "").lower()
    if variant not in SUPPORTED_VARIANTS:
        raise pnsctl.OperatorError("Enhancement evidence category is invalid")
    session = Path(str(structure.get("session_directory") or "")).resolve()
    if not session.is_dir() or session.is_symlink():
        raise pnsctl.OperatorError(
            "Enhancement evidence session directory is unavailable"
        )
    delivery_path = session / "flow-delivery-result.json"
    if not delivery_path.is_file() or delivery_path.is_symlink():
        raise pnsctl.OperatorError("Enhancement flow-delivery-result.json is required")
    retained = json.loads(delivery_path.read_text(encoding="utf-8"))
    if retained != json.loads(json.dumps(result, sort_keys=True, default=str)):
        raise pnsctl.OperatorError(
            "Enhancement retained result does not match verifier input"
        )
    if result.get("serial") != pnsctl.BLUESTACKS_SERIAL or (
        result.get("native_width"),
        result.get("native_height"),
    ) != (800, 1280):
        raise pnsctl.OperatorError("Enhancement evidence runtime profile is invalid")
    if (
        result.get("production_registration") != "NOT_REGISTERED"
        or result.get("scheduler_enabled") is not False
    ):
        raise pnsctl.OperatorError(
            "Enhancement production registration or scheduler is enabled"
        )
    if result.get("status") not in {
        "completed",
        "blocked",
        "evidence_required",
        "unresolved",
        "manual_required",
    }:
        raise pnsctl.OperatorError("Enhancement delivery status is invalid")
    frames = structure.get("frames") or result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise pnsctl.OperatorError("Enhancement native frame evidence is required")
    frame_hashes: set[str] = set()
    for value in frames:
        if not isinstance(value, str) or not value:
            raise pnsctl.OperatorError("Enhancement frame references are invalid")
        path = (session / value).resolve()
        try:
            path.relative_to(session)
        except ValueError as exc:
            raise pnsctl.OperatorError(
                "Enhancement frame reference escaped the session"
            ) from exc
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".png":
            raise pnsctl.OperatorError(
                "Enhancement frame evidence is missing or not PNG"
            )
        frame_hashes.add(_decode_native(path))
    rows = _read_event_rows(session / str(result.get("events_path") or "events.jsonl"))
    declared = result.get("dispatch_count")
    if type(declared) is not int or declared != len(_dispatch_rows(rows)):
        raise pnsctl.OperatorError(
            "Enhancement dispatch count does not match native events"
        )
    if len(_resource_dispatch_rows(rows)) > 1:
        raise pnsctl.OperatorError(
            "Enhancement evidence contains repeated resource confirmation"
        )
    return result, session, rows, frame_hashes


def _verify_event_order(
    rows: list[dict[str, Any]], route: Mapping[str, Any], frame_hashes: set[str]
) -> None:
    captured: list[str] = []
    for row in rows:
        if row.get("type") == "capture":
            digest = _require_hash(row.get("sha256"), "capture")
            if digest not in frame_hashes:
                raise _pnsctl().OperatorError(
                    "Enhancement capture hash is not retained"
                )
            captured.append(digest)
        if row.get("type") == "dispatch":
            digest = _require_hash(row.get("source_sha256"), "dispatch source")
            if digest not in captured:
                raise _pnsctl().OperatorError(
                    "Enhancement dispatch occurred without prior source capture"
                )
    final_rows = [
        row
        for row in rows
        if row.get("type") == "dispatch"
        and row.get("target_identity") == "enhancement-confirm"
    ]
    if route.get("resource_affecting_dispatch_count") == 1:
        if len(final_rows) != 1:
            raise _pnsctl().OperatorError(
                "Enhancement final resource dispatch is not uniquely recorded"
            )
        before_hash = _require_hash(route.get("source_frame_sha256"), "route source")
        final_hash = _require_hash(
            final_rows[0].get("source_sha256"), "final dispatch source"
        )
        before = _observation(route.get("final_before_observation"), "final-before")
        if (
            final_hash
            != _require_hash(before.source_frame_sha256, "final-before source")
            or final_hash not in frame_hashes
        ):
            raise _pnsctl().OperatorError(
                "Enhancement final dispatch source is not immediate-before"
            )
        roi = final_rows[0].get("target_roi")
        if tuple(roi or ()) != tuple(before.target_roi):
            raise _pnsctl().OperatorError(
                "Enhancement final dispatch ROI does not match immediate-before"
            )
        if final_hash == before_hash:
            raise _pnsctl().OperatorError(
                "Enhancement source and final immediate-before are not distinct"
            )
        classifications = [
            row
            for row in rows
            if row.get("type") == "dispatch_classification"
            and row.get("action_key") == final_rows[0].get("action_key")
        ]
        if (
            len(classifications) != 1
            or classifications[0].get("resource_affecting") is not True
            or classifications[0].get("consequential") is not False
        ):
            raise _pnsctl().OperatorError(
                "Enhancement resource-affecting dispatch class is missing"
            )


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
        raise _pnsctl().OperatorError(
            f"Enhancement {field} evidence reference is missing"
        )
    for reference in observation.evidence_refs:
        path = Path(str(reference))
        if not path.is_absolute():
            path = session / path
        path = path.resolve()
        try:
            path.relative_to(session)
        except ValueError as exc:
            raise _pnsctl().OperatorError(
                f"Enhancement {field} evidence escaped session"
            ) from exc
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".png":
            raise _pnsctl().OperatorError(
                f"Enhancement {field} evidence reference is invalid"
            )
        if _decode_native(path) != digest:
            raise _pnsctl().OperatorError(
                f"Enhancement {field} evidence does not match its source"
            )


def _rerun_semantics(
    result: Mapping[str, Any], session: Path, frame_hashes: set[str]
) -> bool:
    from scripts.enhancement_bluestacks import (
        recognize_commander_stage,
        recognize_daily_frame,
    )

    variant = str(result["variant"])
    reset = str(result.get("reset_identity") or "")
    for stage in result.get("enhancement_result", {}).get("stages", []):
        if not isinstance(stage, Mapping) or not stage.get("recognized"):
            continue
        digest = stage.get("frame_sha256")
        if not isinstance(digest, str) or digest not in frame_hashes:
            return False
        refs = [
            path
            for path in (session / "frames").glob("*.png")
            if _decode_native(path) == digest
        ]
        if not refs:
            return False
        frame = cv2.imread(str(refs[0]), cv2.IMREAD_COLOR)
        name = str(stage.get("stage") or "")
        if name.startswith("daily"):
            recognition = recognize_daily_frame(
                frame,
                variant=variant,
                source_frame_sha256=digest,
                completed=name == "daily-successor",
            )
        elif name.startswith(("commander", "material", "category", "enhancement")):
            stage = (
                "post"
                if ("settle" in name or "terminal" in name)
                else "material"
                if ("material" in name or "final-confirm" in name)
                else "item"
            )
            recognition = recognize_commander_stage(
                frame,
                variant=variant,
                stage=stage,
                source_frame_sha256=digest,
                evidence_ref=refs[0],
                game_day_id=reset,
            )
        else:
            continue
        if not recognition.recognized:
            return False
    return True


def verify_enhancement_family(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    del queue, lease
    result, session, rows, frame_hashes = _verify_native_structure(structure)
    route = result.get("enhancement_result")
    if not isinstance(route, Mapping):
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "reason": "route semantics missing",
        }
    _verify_event_order(rows, route, frame_hashes)
    status = str(result["status"])
    if status != "completed":
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result["variant"],
            "session_directory": str(session),
            "dispatch_count": result["dispatch_count"],
        }
    if (
        route.get("postcondition_verified") is not True
        or route.get("terminal_recognized") is not True
    ):
        raise _pnsctl().OperatorError(
            "completed Enhancement route lacks terminal proof"
        )
    daily_before = route.get("daily_before")
    daily_after = route.get("daily_after")
    expected_objective = f"enhance_{str(result['variant']).lower()}"
    if (
        not isinstance(daily_before, Mapping)
        or not isinstance(daily_after, Mapping)
        or daily_before.get("selected_daily_row") is not True
        or daily_after.get("selected_daily_row") is not True
        or daily_before.get("objective_key") != expected_objective
        or daily_after.get("objective_key") != expected_objective
        or daily_before.get("daily_progress_before") != 0
        or daily_before.get("daily_progress_total") != 1
        or daily_after.get("daily_progress_after") != 1
        or daily_after.get("daily_progress_total") != 1
    ):
        raise _pnsctl().OperatorError(
            "completed Enhancement route lacks Daily 0-to-1 ownership proof"
        )
    if route.get("resource_affecting_dispatch_count") != 1:
        raise _pnsctl().OperatorError(
            "completed Enhancement route requires one resource-affecting dispatch"
        )
    before = _observation(route.get("final_before_observation"), "final-before")
    after = _observation(route.get("immediate_post_observation"), "post")
    _verify_observation_binding(before, session, frame_hashes, "final-before")
    _verify_observation_binding(after, session, frame_hashes, "post")
    if not enhancement_bluestacks_authorizeable(before, variant=str(result["variant"])):
        raise _pnsctl().OperatorError(
            "Enhancement immediate-before semantics are not authorized"
        )
    if not enhancement_bluestacks_postcondition_verified(
        before, after, variant=str(result["variant"])
    ):
        raise _pnsctl().OperatorError("Enhancement same-item successor is not proven")
    terminal_hash = _require_hash(route.get("terminal_frame_sha256"), "terminal")
    if terminal_hash not in frame_hashes or terminal_hash == _require_hash(
        route.get("source_frame_sha256"), "route source"
    ):
        raise _pnsctl().OperatorError(
            "Enhancement terminal frame is missing or reused source"
        )
    if not _rerun_semantics(result, session, frame_hashes):
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "variant": result["variant"],
            "session_directory": str(session),
            "reason": "independent semantic re-recognition unavailable",
        }
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "variant": result["variant"],
        "session_directory": str(session),
        "dispatch_count": result["dispatch_count"],
        "item_identity": before.selected_item_identity,
        "postcondition_verified": True,
        "independent_rerecognition": True,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def recover_enhancement_family(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    recovery_lease = dict(lease)
    recovery_lease["enhancement_recovery_only"] = True
    recovery_lease.setdefault("enhancement_variant", "gear")
    recovery_lease.setdefault("max_inputs", 4)
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
