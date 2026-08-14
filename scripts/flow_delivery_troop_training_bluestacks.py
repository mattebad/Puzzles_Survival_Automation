"""Checked-in development-session binding for Troop Training consolidation.

The binding delegates gameplay to the existing Troop Training route.  It does not
manufacture runtime evidence, widen the caller's input bound, or retry a prior
canary.  Native ``frames/`` and ``events.jsonl`` are the required development
artifacts; legacy ledger/journal files are intentionally omitted by this
development-session contract.
"""

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

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
MAX_DISPATCH_BEARING_CANARY_RUNS = 100
RUNNER_ID = "troop_training_consolidation_runner"
VALIDATOR_ID = "troop_training_consolidation_evidence"
RECOVERY_ID = "troop_training_consolidation_recovery"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_ROUTE_STATUSES = frozenset({"completed", "blocked", "unresolved", "manual_required", "dry-run"})


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _session_max_inputs(lease: Mapping[str, Any]) -> int:
    value = lease.get("max_inputs")
    if value is None:
        value = os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS")
    if value is None:
        raise _pnsctl().OperatorError("development session max_inputs is required")
    try:
        maximum = int(value)
    except (TypeError, ValueError) as exc:
        raise _pnsctl().OperatorError("development session max_inputs must be an integer") from exc
    if not 1 <= maximum <= 100:
        raise _pnsctl().OperatorError("development session max_inputs must be between 1 and 100")
    return maximum


def _result_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise _pnsctl().OperatorError("Troop Training route did not emit a JSON result")


def _read_event_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise _pnsctl().OperatorError("Troop Training route produced no native event journal")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _pnsctl().OperatorError("Troop Training event journal is unreadable") from exc
    if not lines:
        raise _pnsctl().OperatorError("Troop Training native event journal is empty")
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _pnsctl().OperatorError("Troop Training event journal contains invalid JSON") from exc
        if not isinstance(row, dict):
            raise _pnsctl().OperatorError("Troop Training event journal rows must be objects")
        rows.append(row)
    if not rows:
        raise _pnsctl().OperatorError("Troop Training native event journal is empty")
    return rows


def _dispatch_count(rows: list[Mapping[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("type") == "dispatch")


def _prior_dispatch_bearing_runs(flow_root: Path) -> list[str]:
    """Return dispatch-bearing run artifacts, or fail closed on ambiguity."""

    if not flow_root.is_dir():
        return []
    result_paths = sorted(flow_root.rglob("flow-delivery-result.json"))
    seen_event_paths: set[Path] = set()
    dispatch_bearing: list[str] = []
    for result_path in result_paths:
        if result_path.is_symlink() or not result_path.is_file():
            raise _pnsctl().OperatorError("prior Troop Training canary result path is unsafe")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _pnsctl().OperatorError("prior Troop Training canary result is unreadable") from exc
        if not isinstance(result, dict) or result.get("flow_id") != FLOW_ID:
            continue
        event_path = result_path.parent / str(result.get("events_path") or "events.jsonl")
        if event_path.is_file():
            if event_path.is_symlink():
                raise _pnsctl().OperatorError("prior Troop Training event path is unsafe")
            seen_event_paths.add(event_path.resolve())
            rows = _read_event_rows(event_path)
            event_dispatches = _dispatch_count(rows) > 0
        else:
            event_dispatches = False
        dispatch_count = result.get("dispatch_count")
        if dispatch_count is not None and type(dispatch_count) is not int:
            raise _pnsctl().OperatorError("prior Troop Training canary dispatch count is malformed")
        if event_dispatches or bool(result.get("dispatch")) or (dispatch_count or 0) > 0:
            dispatch_bearing.append(str(result_path))
    for event_path in sorted(flow_root.rglob("events.jsonl")):
        if event_path.resolve() in seen_event_paths:
            continue
        rows = _read_event_rows(event_path)
        if _dispatch_count(rows) > 0:
            dispatch_bearing.append(str(event_path))
    return dispatch_bearing


def _native_frames(session: Path) -> list[str]:
    frame_dir = session / "frames"
    if not frame_dir.is_dir():
        raise _pnsctl().OperatorError("Troop Training route produced no native frame directory")
    paths = sorted(path for path in frame_dir.glob("*.png") if path.is_file() and not path.is_symlink())
    if not paths:
        raise _pnsctl().OperatorError("Troop Training route produced no native frame evidence")
    return [str(path.relative_to(session)).replace("\\", "/") for path in paths]


def run_troop_training_consolidation(
    queue: Mapping[str, Any], lease: Mapping[str, Any], *, live: bool = True
) -> str:
    """Delegate one bounded development-session run to troop_training_bluestacks.py."""

    del queue
    pnsctl = _pnsctl()
    maximum = _session_max_inputs(lease)
    recovery_only = bool(lease.get("troop_training_recovery_only"))
    flow_root = (pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID).resolve()
    if live and not recovery_only:
        prior_runs = _prior_dispatch_bearing_runs(flow_root)
        if len(prior_runs) >= MAX_DISPATCH_BEARING_CANARY_RUNS:
            raise pnsctl.OperatorError(
                "Troop Training maximum-live-canary admission is exhausted by prior dispatch-bearing runs: "
                + ", ".join(prior_runs[:MAX_DISPATCH_BEARING_CANARY_RUNS])
            )
    root = flow_root / f"run-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    if not live:
        return json.dumps(
            {
                "status": "dry_run",
                "flow_id": FLOW_ID,
                "dispatch": False,
                "dispatch_count": 0,
                "max_inputs": maximum,
                "session_directory": str(root),
                "delegated_route": "scripts/troop_training_bluestacks.py",
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            sort_keys=True,
        )
    reset_identity = str(lease.get("troop_training_reset_identity") or "").strip()
    if not reset_identity:
        raise pnsctl.OperatorError("Troop Training reset identity is required")
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "troop_training_bluestacks.py"),
        "--adb", str(pnsctl.BLUESTACKS_ADB),
        "--serial", pnsctl.BLUESTACKS_SERIAL,
        "--reset-identity", reset_identity,
        "--output-directory", str(root),
        "--execute", "--yes",
    ]
    if recovery_only:
        # Recovery is a bounded, observe-and-Back route.  The existing route
        # performs fresh queue identity checks and canonical Home proof; no
        # Canonical Train action is admitted by this command shape.
        command.extend((
            "--return-home-only",
            "--recovery-active-queue",
            "--recovery-training-screen",
            "--radial-troop-type",
            "fighter",
        ))
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
    except pnsctl.OperatorError as exc:
        # Preserve a machine-readable failure record even when the delegated
        # CLI crashes before emitting its normal JSON route result.  Native
        # stdout/stderr remain in their sibling files; this record is strictly
        # diagnostic and can never authorize recovery or dispatch.
        failure = {
            "schema_version": 1,
            "flow_id": FLOW_ID,
            "status": "blocked",
            "reason": "delegated Troop Training route emitted no JSON result",
            "operator_returncode": completed.returncode,
            "operator_stdout_path": "operator-stdout.log",
            "operator_stderr_path": "operator-stderr.log",
            "command": command,
            "dispatch": False,
            "dispatch_count": 0,
            "recovery_only": recovery_only,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        (root / "operator-failure.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise pnsctl.OperatorError(
            f"Troop Training route emitted no JSON result (returncode {completed.returncode}); "
            "see operator-failure.json and native stdout/stderr"
        ) from exc
    try:
        session = Path(str(route.get("session") or root))
        if not session.is_absolute():
            session = (REPO_ROOT / session).resolve()
        if not session.is_dir():
            raise pnsctl.OperatorError("Troop Training route session directory is unavailable")
        frames = _native_frames(session)
        event_rows = _read_event_rows(session / "events.jsonl")
    except (OSError, pnsctl.OperatorError) as exc:
        failure = {
            "schema_version": 1,
            "flow_id": FLOW_ID,
            "status": "blocked",
            "reason": "delegated Troop Training route did not produce required native evidence",
            "operator_returncode": completed.returncode,
            "operator_stdout_path": "operator-stdout.log",
            "operator_stderr_path": "operator-stderr.log",
            "command": command,
            "route_result": route,
            "child_session": str(route.get("session") or ""),
            "dispatch": False,
            "dispatch_count": 0,
            "recovery_only": recovery_only,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        (root / "operator-failure.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        raise pnsctl.OperatorError(
            "Troop Training route did not produce required native evidence; "
            "see operator-failure.json and native stdout/stderr"
        ) from exc
    dispatch_count = _dispatch_count(event_rows)
    if dispatch_count > maximum:
        raise pnsctl.OperatorError("Troop Training route exceeded its development-session input bound")
    route_status = str(route.get("status") or "unknown")
    if route_status not in _TERMINAL_ROUTE_STATUSES:
        raise pnsctl.OperatorError("Troop Training route returned an unknown terminal status")
    final_home = route.get("final_home_recognized") is True
    if route_status == "dry-run":
        delivery_status = "dry_run"
        terminal_state = "blocked"
    elif route_status == "completed" and final_home:
        delivery_status = "completed"
        terminal_state = "recognized_home"
    elif route_status in {"unresolved", "manual_required"}:
        delivery_status = route_status
        terminal_state = route_status
    else:
        delivery_status = "blocked"
        terminal_state = "recognized_home" if final_home else "blocked"
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": delivery_status,
        "serial": pnsctl.BLUESTACKS_SERIAL,
        "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
        "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
        "runtime_owner": str(lease.get("owner") or "pnsctl-development-session"),
        "reset_identity": reset_identity,
        "terminal_runtime_state": terminal_state,
        "actions": (
            [{"troop_training_recovery": route}]
            if recovery_only
            else [{"troop_training": item} for item in route.get("training", [])]
        ),
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "ledger_path": None,
        "journal_path": None,
        "capability_audit_path": None,
        "artifact_contract": {
            "required": ["frames", "events_path"],
            "optional": ["ledger_path", "journal_path", "capability_audit_path"],
            "basis": "native development-session route emits frames and events; legacy bookkeeping is not required",
        },
        "dispatch": dispatch_count > 0,
        "dispatch_count": dispatch_count,
        "max_inputs": maximum,
        "troop_training_result": route,
        "recovery_only": recovery_only,
        "operator_returncode": completed.returncode,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return json.dumps(
        {
            "status": delivery_status,
            "flow_id": FLOW_ID,
            "session_directory": str(session),
            "dispatch": dispatch_count > 0,
            "dispatch_count": dispatch_count,
            "max_inputs": maximum,
            "recovery_only": recovery_only,
        },
        sort_keys=True,
    )


def _require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise _pnsctl().OperatorError(f"Troop Training {field} hash is missing or invalid")
    return value


def _verify_native_structure(
    structure: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], set[str]]:
    result = structure.get("result")
    if not isinstance(result, dict) or result.get("flow_id") != FLOW_ID:
        raise _pnsctl().OperatorError("Troop Training evidence belongs to another flow")
    session_text = structure.get("session_directory")
    if not isinstance(session_text, str) or not session_text.strip():
        raise _pnsctl().OperatorError("Troop Training evidence session directory is required")
    session = Path(session_text).resolve()
    if not session.is_dir() or session.is_symlink():
        raise _pnsctl().OperatorError("Troop Training evidence session directory is unavailable")
    delivery_path = session / "flow-delivery-result.json"
    if not delivery_path.is_file():
        raise _pnsctl().OperatorError("Troop Training flow-delivery-result.json is required")
    try:
        retained = json.loads(delivery_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _pnsctl().OperatorError("Troop Training flow-delivery-result.json is unreadable") from exc
    if retained != result:
        raise _pnsctl().OperatorError("Troop Training retained result does not match verifier input")
    result_status = result.get("status")
    terminal_state = result.get("terminal_runtime_state")
    if result_status == "completed":
        if terminal_state != "recognized_home":
            raise _pnsctl().OperatorError("Troop Training completed route lacks canonical Home terminal proof")
    elif result_status not in {"blocked", "unresolved", "manual_required"} or terminal_state not in {
        "blocked", "unresolved", "manual_required"
    }:
        raise _pnsctl().OperatorError("Troop Training route terminal state is invalid")
    frames = structure.get("frames") or result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise _pnsctl().OperatorError("Troop Training native frame evidence is required")
    frame_hashes: set[str] = set()
    for value in frames:
        if not isinstance(value, str) or not value.strip():
            raise _pnsctl().OperatorError("Troop Training frame references are invalid")
        frame = (session / value).resolve()
        try:
            frame.relative_to(session)
        except ValueError as exc:
            raise _pnsctl().OperatorError("Troop Training frame reference escaped the session") from exc
        if frame.is_symlink() or not frame.is_file() or frame.stat().st_size == 0:
            raise _pnsctl().OperatorError("Troop Training frame evidence is missing")
        frame_hashes.add(hashlib.sha256(frame.read_bytes()).hexdigest())
    required = result.get("required_artifacts")
    if required != ["events_path"]:
        raise _pnsctl().OperatorError("Troop Training required artifact contract is invalid")
    events = session / str(result.get("events_path") or "")
    rows = _read_event_rows(events)
    if result.get("dispatch_count") != _dispatch_count(rows):
        raise _pnsctl().OperatorError("Troop Training dispatch count does not match native event evidence")
    return result, session, rows, frame_hashes


def _verify_training_records(
    route: Mapping[str, Any], frame_hashes: set[str], event_rows: list[Mapping[str, Any]]
) -> None:
    from tasks.troop_training import RESOURCE_NAMES, TROOP_TYPES
    from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID

    config = route.get("resolved_config")
    records = route.get("training")
    if not isinstance(config, dict) or not isinstance(records, (list, tuple)):
        raise _pnsctl().OperatorError("Troop Training resolved config and per-type records are required")

    def validate_frame_resources(record: Mapping[str, Any], troop_type: str) -> None:
        hashes = (
            _require_hash(record.get("source_frame_hash"), f"{troop_type} source"),
            _require_hash(record.get("immediate_before_frame_hash") or record.get("source_frame_hash"), f"{troop_type} immediate-before"),
            _require_hash(record.get("immediate_post_frame_hash"), f"{troop_type} immediate-post"),
        )
        if any(value not in frame_hashes for value in hashes):
            raise _pnsctl().OperatorError(f"{troop_type} evidence hash is not bound to native frame evidence")
        for field in ("resources_before", "resources_after"):
            resources = record.get(field)
            if (
                not isinstance(resources, list)
                or len(resources) != len(RESOURCE_NAMES)
                or {item.get("name") for item in resources if isinstance(item, Mapping)} != set(RESOURCE_NAMES)
            ):
                raise _pnsctl().OperatorError(f"{troop_type} resource readings/delta are missing or unknown")
            if any(
                not isinstance(resource_entry, Mapping)
                or type(resource_entry.get("held")) is not int
                or resource_entry.get("held") < 0
                or type(resource_entry.get("required")) is not int
                or resource_entry.get("required") < 0
                for resource_entry in resources
            ):
                raise _pnsctl().OperatorError(f"{troop_type} resource readings/delta are not known numeric values")
    enabled_types = [
        troop_type
        for troop_type in TROOP_TYPES
        if isinstance(config.get(troop_type), Mapping)
        and config[troop_type].get("enabled") is True
        and config[troop_type].get("training_policy") != "disabled"
    ]
    if enabled_types:
        entry_navigation = route.get("entry_navigation")
        if not isinstance(entry_navigation, Mapping):
            raise _pnsctl().OperatorError("Troop Training canonical entry evidence is required")
        source_localization = entry_navigation.get("source_localization")
        if not isinstance(source_localization, Mapping) or source_localization.get("recognized") is not True:
            raise _pnsctl().OperatorError("Troop Training canonical Home entry proof is missing")
        if (
            source_localization.get("platform") != BLUESTACKS_PLATFORM
            or source_localization.get("profile_id") != BLUESTACKS_PROFILE_ID
            or str(source_localization.get("zoom_identity")) not in {
                "fully_zoomed_out",
                "ZoomIdentity.FULLY_ZOOMED_OUT",
            }
            or source_localization.get("screen_to_atlas") is None
            or source_localization.get("stale") is True
            or source_localization.get("overlay") is True
        ):
            raise _pnsctl().OperatorError("Troop Training source Home localization is not canonical")
        source_hash = _require_hash(source_localization.get("frame_sha256"), "canonical Home source")
        if source_hash not in frame_hashes:
            raise _pnsctl().OperatorError("Troop Training source Home localization hash is not native evidence")
        if not isinstance(entry_navigation.get("final_binding"), Mapping):
            raise _pnsctl().OperatorError("Troop Training facility binding evidence is missing")
        if not isinstance(entry_navigation.get("radial_binding"), Mapping):
            raise _pnsctl().OperatorError("Troop Training radial entry evidence is missing")
        terminal_localization = entry_navigation.get("terminal_home_localization")
        if not isinstance(terminal_localization, Mapping) or terminal_localization.get("recognized") is not True:
            raise _pnsctl().OperatorError("Troop Training terminal Home localization is missing")
        if str(terminal_localization.get("zoom_identity")) not in {
            "fully_zoomed_out",
            "ZoomIdentity.FULLY_ZOOMED_OUT",
        }:
            raise _pnsctl().OperatorError("Troop Training terminal Home is not at canonical zoom")
        terminal_hash = _require_hash(terminal_localization.get("frame_sha256"), "canonical Home terminal")
        declared_terminal_hash = _require_hash(entry_navigation.get("terminal_home_frame_hash"), "canonical Home terminal")
        if terminal_hash != declared_terminal_hash or terminal_hash not in frame_hashes:
            raise _pnsctl().OperatorError("Troop Training terminal Home localization hash is not native evidence")
        if not records or not isinstance(records[-1], Mapping):
            raise _pnsctl().OperatorError("Troop Training terminal Home record binding is missing")
        record_terminal_hash = _require_hash(records[-1].get("terminal_home_frame_hash"), "terminal Home record")
        if record_terminal_hash != terminal_hash:
            raise _pnsctl().OperatorError("Troop Training terminal Home evidence is not bound to the final record")
        first_type = enabled_types[0]
        facility_dispatches = [
            row for row in event_rows
            if row.get("type") == "dispatch"
            and row.get("target_identity") == f"facility:{first_type}"
        ]
        if len(facility_dispatches) != 1:
            raise _pnsctl().OperatorError("Troop Training canonical route must enter exactly one facility")
        facility_targets = [
            str(row.get("target_identity"))
            for row in event_rows
            if row.get("type") == "dispatch"
            and str(row.get("target_identity") or "").startswith("facility:")
        ]
        if facility_targets != [f"facility:{first_type}"]:
            raise _pnsctl().OperatorError("Troop Training canonical route must enter exactly one facility")
        tab_targets = [
            str(row.get("target_identity"))
            for row in event_rows
            if row.get("type") == "dispatch"
            and row.get("consequential") is False
            and str(row.get("target_identity") or "").startswith("tab:")
            and not str(row.get("target_identity") or "").endswith(":claim-completed")
        ]
        expected_tabs = [f"tab:{troop_type}" for troop_type in enabled_types[1:]]
        if tab_targets != expected_tabs:
            raise _pnsctl().OperatorError(
                "Troop Training shared-tab processing order or cardinality is invalid"
            )
    by_type: dict[str, list[Mapping[str, Any]]] = {troop_type: [] for troop_type in TROOP_TYPES}
    for record in records:
        if not isinstance(record, Mapping) or record.get("troop_type") not in by_type:
            raise _pnsctl().OperatorError("Troop Training record has an unknown troop type")
        by_type[str(record["troop_type"])].append(record)
    for troop_type in TROOP_TYPES:
        item = config.get(troop_type)
        if not isinstance(item, Mapping):
            raise _pnsctl().OperatorError(f"Troop Training resolved config omits {troop_type}")
        required = {"enabled", "target_tier", "quantity_mode", "training_policy", "allow_resource_boxes", "resolved_quantity"}
        if not required.issubset(item):
            raise _pnsctl().OperatorError(f"Troop Training resolved config for {troop_type} is incomplete")
        if troop_type in {"shooter", "rider"} and item.get("allow_resource_boxes") is not False:
            raise _pnsctl().OperatorError(f"resource boxes are forbidden for {troop_type}")
        enabled = bool(item.get("enabled")) and item.get("training_policy") != "disabled"
        target_tier = item.get("target_tier")
        if enabled and (type(target_tier) is not int or not 1 <= target_tier <= 13):
            raise _pnsctl().OperatorError(f"{troop_type} target tier is invalid")
        if item.get("quantity_mode") == "fixed":
            quantity = item.get("quantity")
            if enabled and (type(quantity) is not int or not 1 <= quantity <= 1000):
                raise _pnsctl().OperatorError(f"{troop_type} fixed quantity is invalid")
        elif item.get("quantity_mode") == "current_max" and item.get("quantity") is not None:
            raise _pnsctl().OperatorError(f"{troop_type} current_max must not carry fixed quantity")
        else:
            if item.get("quantity_mode") not in {"fixed", "current_max"}:
                raise _pnsctl().OperatorError(f"{troop_type} quantity mode is invalid")
        if not item.get("enabled") or item.get("training_policy") == "disabled":
            continue
        rows = by_type[troop_type]
        claim_rows = [row for row in rows if row.get("completion_policy") == "completed_batch_claim_reconciled"]
        if len(claim_rows) > 1:
            raise _pnsctl().OperatorError(f"Troop Training has duplicate completed claims for {troop_type}")
        if claim_rows:
            claim = claim_rows[0]
            validate_frame_resources(claim, troop_type)
            claim_targets = [
                str(event.get("target_identity"))
                for event in event_rows
                if event.get("type") == "dispatch"
                and event.get("consequential") is False
                and event.get("target_identity") == f"tab:{troop_type}:claim-completed"
            ]
            if claim_targets != [f"tab:{troop_type}:claim-completed"]:
                raise _pnsctl().OperatorError(f"{troop_type} completed claim dispatch evidence is missing or duplicated")
            if item.get("training_policy") == "once_daily":
                if len(rows) != 1:
                    raise _pnsctl().OperatorError(f"{troop_type} once_daily claim must be terminal")
            elif item.get("training_policy") == "continuous":
                if len(rows) != 2 or sum(row is not claim for row in rows) != 1:
                    raise _pnsctl().OperatorError(f"{troop_type} continuous claim must be followed by one Train record")
            else:
                raise _pnsctl().OperatorError(f"completed batch claim is invalid for {troop_type}")
            if not isinstance(claim.get("batch_identity"), str) or not claim["batch_identity"].startswith(f"{troop_type}:"):
                raise _pnsctl().OperatorError(f"{troop_type} completed batch identity is mismatched")
            if not isinstance(claim.get("action_key"), str) or not claim["action_key"].strip():
                raise _pnsctl().OperatorError(f"{troop_type} completed claim action identity is missing")
            if not isinstance(claim.get("reset_identity"), str) or not claim["reset_identity"].strip():
                raise _pnsctl().OperatorError(f"{troop_type} completed claim reset identity is missing")
            if (
                item.get("training_policy") == "once_daily"
                and (
                    claim.get("daily_initiation_state") != "initiated"
                    or item.get("daily_initiation_state") != "initiated"
                )
            ):
                raise _pnsctl().OperatorError(f"{troop_type} once_daily persistence claim is missing")
            if item.get("training_policy") == "once_daily":
                row = claim
                policy = "completed_batch_claim_reconciled"
            else:
                row = next(row for row in rows if row is not claim)
                policy = str(row.get("completion_policy") or "")
        else:
            if len(rows) != 1:
                raise _pnsctl().OperatorError(f"Troop Training requires exactly one evidence record for {troop_type}")
            row = rows[0]
            policy = str(row.get("completion_policy") or "")
            validate_frame_resources(row, troop_type)
        policy = str(row.get("completion_policy") or "")
        if claim_rows and policy != "completed_batch_claim_reconciled":
            validate_frame_resources(row, troop_type)
        normal_train_events = [
            event for event in event_rows
            if event.get("type") == "dispatch"
            and event.get("consequential") is True
            and str(event.get("target_identity") or "").startswith("normal-train:")
        ]
        normal_train_targets = [str(event.get("target_identity")) for event in normal_train_events]
        expected_train = f"normal-train:{troop_type}"
        if policy == "completed_batch_claim_reconciled":
            if expected_train in normal_train_targets:
                raise _pnsctl().OperatorError(f"{troop_type} completed claim has an unexpected Train dispatch")
        elif policy == "read_only_existing_queue":
            if expected_train in normal_train_targets:
                raise _pnsctl().OperatorError(f"{troop_type} read-only queue evidence has an unexpected Train dispatch")
        else:
            type_train_events = [event for event in normal_train_events if event.get("target_identity") == expected_train]
            if len(type_train_events) not in {1, 2}:
                raise _pnsctl().OperatorError(f"{troop_type} exact normal Train dispatch evidence is missing or duplicated")
            if len(type_train_events) == 2:
                action_keys = [str(event.get("action_key") or "") for event in type_train_events]
                reconciled = {
                    str(event.get("action_key")): event
                    for event in event_rows
                    if event.get("type") == "reconcile" and event.get("action_key") in action_keys
                }
                first_reconcile = reconciled.get(action_keys[0], {})
                second_reconcile = reconciled.get(action_keys[1], {})
                if (
                    len(set(action_keys)) != 2
                    or not action_keys[0]
                    or not action_keys[1]
                    or first_reconcile.get("status") != "failed_confirmed"
                    or second_reconcile.get("status") != "confirmed"
                    or "resource boxes positively applied" not in str(first_reconcile.get("reason") or "")
                    or "queue remained empty" not in str(first_reconcile.get("reason") or "")
                ):
                    raise _pnsctl().OperatorError(f"{troop_type} duplicate Train dispatch lacks a reconciled resource-box predecessor")
        if any(target not in {f"normal-train:{name}" for name in enabled_types} for target in normal_train_targets):
            raise _pnsctl().OperatorError("Troop Training contains an unknown normal Train dispatch")
        if policy == "completed_batch_claim_reconciled":
            if item.get("training_policy") != "once_daily":
                raise _pnsctl().OperatorError(f"completed batch claim is invalid for {troop_type}")
            if not isinstance(row.get("batch_identity"), str) or not row["batch_identity"].strip():
                raise _pnsctl().OperatorError(f"{troop_type} completed batch identity is missing")
            if not row["batch_identity"].startswith(f"{troop_type}:"):
                raise _pnsctl().OperatorError(f"{troop_type} completed batch identity is mismatched")
            if not isinstance(row.get("action_key"), str) or not row["action_key"].strip():
                raise _pnsctl().OperatorError(f"{troop_type} completed claim action identity is missing")
            if not isinstance(row.get("reset_identity"), str) or not row["reset_identity"].strip():
                raise _pnsctl().OperatorError(f"{troop_type} completed claim reset identity is missing")
            if row.get("daily_initiation_state") != "initiated" or item.get("daily_initiation_state") != "initiated":
                raise _pnsctl().OperatorError(f"{troop_type} once_daily persistence claim is missing")
            continue
        if row.get("facility_identity") is None or row.get("selected_tier") != item.get("target_tier"):
            raise _pnsctl().OperatorError(f"{troop_type} facility or tier evidence is inconsistent")
        if type(row.get("quantity")) is not int or not 1 <= row["quantity"] <= 1000:
            raise _pnsctl().OperatorError(f"{troop_type} selected quantity evidence is invalid")
        if type(item.get("resolved_quantity")) is not int or not 1 <= item["resolved_quantity"] <= 1000:
            raise _pnsctl().OperatorError(f"{troop_type} resolved quantity evidence is invalid")
        if row.get("quantity") != item.get("resolved_quantity"):
            raise _pnsctl().OperatorError(f"{troop_type} resolved quantity evidence is inconsistent")
        if item.get("quantity_mode") == "current_max":
            if not isinstance(row.get("quantity_maximum"), int) or row.get("quantity_maximum") <= 0:
                raise _pnsctl().OperatorError(f"{troop_type} current numeric maximum is missing")
            if row.get("quantity") != row.get("quantity_maximum") or row.get("maximum_equality_proven") is not True:
                raise _pnsctl().OperatorError(f"{troop_type} selected quantity does not prove current maximum")
        else:
            if row.get("quantity") != item.get("quantity"):
                raise _pnsctl().OperatorError(f"{troop_type} fixed quantity evidence is inconsistent")
        if not isinstance(row.get("queue_label"), str) or not row["queue_label"].strip():
            raise _pnsctl().OperatorError(f"{troop_type} queue label identity is missing")
        if row.get("queue_troop_type") != troop_type or row.get("queue_tier") != item.get("target_tier") or row.get("queue_quantity") != row.get("quantity"):
            raise _pnsctl().OperatorError(f"{troop_type} queue label identity is inconsistent")
        if not isinstance(row.get("displayed_training_duration_seconds"), int) or row.get("displayed_training_duration_seconds") <= 0:
            raise _pnsctl().OperatorError(f"{troop_type} positive queue timer is missing")
        if row.get("duration_source") != "queue_band" or row.get("queue_spatially_associated") is not True:
            raise _pnsctl().OperatorError(f"{troop_type} queue timer spatial association is missing")
        queue_roi = row.get("queue_roi")
        if not isinstance(queue_roi, (list, tuple)) or len(queue_roi) != 4 or any(type(value) is not int for value in queue_roi):
            raise _pnsctl().OperatorError(f"{troop_type} queue ROI provenance is missing")


def verify_troop_training_consolidation(
    structure: Mapping[str, Any], queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> dict[str, Any]:
    import cv2

    from scripts.troop_training_bluestacks import _canonical_home_proof
    from tasks.troop_training_vision import recognize_home, recognize_training

    del queue, lease
    result, session, _event_rows, frame_hashes = _verify_native_structure(structure)
    route = result.get("troop_training_result")
    if not isinstance(route, Mapping):
        raise _pnsctl().OperatorError("Troop Training route result is required")
    if result.get("recovery_only") is True:
        recovery_reconciled = False
        if route.get("status") != "completed" or route.get("final_home_recognized") is not True:
            # A pre-fix recovery may have safely issued Back and returned a
            # native Home frame while its older recognizer reported blocked.
            # Reconcile that retained terminal frame with the repaired Home
            # recognizer and Atlas localizer; never infer Home from the route
            # status alone.
            final_capture = next(
                (
                    row
                    for row in reversed(_event_rows)
                    if row.get("type") == "capture"
                    and str(row.get("label") or "").startswith("return-home-final")
                    and isinstance(row.get("path"), str)
                ),
                None,
            )
            if final_capture is None:
                raise _pnsctl().OperatorError("Troop Training recovery lacks retained terminal Home frame")
            final_path = Path(str(final_capture["path"])).resolve()
            try:
                final_path.relative_to(session)
            except ValueError as exc:
                raise _pnsctl().OperatorError("Troop Training recovery terminal frame escaped the session") from exc
            if final_path.is_symlink() or not final_path.is_file() or final_path.stat().st_size == 0:
                raise _pnsctl().OperatorError("Troop Training recovery terminal frame is unavailable")
            final_frame = cv2.imread(str(final_path), cv2.IMREAD_COLOR)
            atlas_path = _pnsctl().REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
            if final_frame is None or not atlas_path.is_file():
                raise _pnsctl().OperatorError("Troop Training recovery terminal Home evidence is unreadable")
            home = recognize_home(final_frame, reset_identity=str(result.get("reset_identity") or "recovery"))
            if not _canonical_home_proof(final_frame, home, atlas_path):
                raise _pnsctl().OperatorError("Troop Training recovery lacks canonical Home proof")
            recovery_reconciled = True
        return {
            "status": "verified",
            "flow_id": FLOW_ID,
            "session_directory": str(session),
            "recovery_only": True,
            "recovery_reconciled": recovery_reconciled,
            "dispatch_count": result.get("dispatch_count"),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    if route.get("status") in {"unresolved", "blocked", "manual_required"}:
        # A post-session review may positively prove the queue successor while
        # still lacking terminal Home.  Return an explicit evidence-required
        # verdict rather than claiming the end-to-end contract completed.
        reconcile = next(
            (
                row
                for row in _event_rows
                if row.get("type") == "reconcile"
                and row.get("status") == "unresolved"
                and isinstance(row.get("post_path"), str)
            ),
            None,
        )
        if reconcile is None:
            raise _pnsctl().OperatorError("Troop Training unresolved route lacks native reconcile evidence")
        dispatches = [
            row
            for row in _event_rows
            if row.get("type") == "dispatch" and row.get("consequential") is True
        ]
        if len(dispatches) != 1 or not str(dispatches[0].get("target_identity") or "").startswith("normal-train:"):
            raise _pnsctl().OperatorError("Troop Training unresolved route lacks the exact consequential Train dispatch")
        post = Path(str(reconcile["post_path"]))
        if not post.is_absolute():
            post = session / post
        post = post.resolve()
        try:
            post.relative_to(session)
        except ValueError as exc:
            raise _pnsctl().OperatorError("Troop Training reconcile frame escaped the session") from exc
        if post.is_symlink() or not post.is_file() or post.stat().st_size == 0:
            raise _pnsctl().OperatorError("Troop Training reconcile frame is missing")
        frame = cv2.imread(str(post), cv2.IMREAD_COLOR)
        if frame is None:
            raise _pnsctl().OperatorError("Troop Training reconcile frame is unreadable")
        observation = recognize_training(frame)
        if not (
            observation.recognized
            and observation.queue_active
            and observation.queue_label
            and observation.queue_troop_type
            and isinstance(observation.queue_tier, int)
            and isinstance(observation.queue_quantity, int)
            and observation.queue_quantity > 0
            and isinstance(observation.training_duration_seconds, int)
            and observation.training_duration_seconds > 0
            and observation.diagnostics.get("duration_source") == "queue_band"
            and observation.diagnostics.get("queue_spatially_associated") is True
        ):
            raise _pnsctl().OperatorError("Troop Training unresolved route lacks an exact spatially bound active queue")
        final_capture = next(
            (
                row for row in _event_rows
                if row.get("type") == "capture"
                and str(row.get("label") or "").startswith("final-home")
                and isinstance(row.get("path"), str)
            ),
            None,
        )
        terminal_home = False
        terminal_home_hash = None
        if final_capture is not None:
            final_path = Path(str(final_capture["path"])).resolve()
            try:
                final_path.relative_to(session)
            except ValueError as exc:
                raise _pnsctl().OperatorError("Troop Training terminal Home frame escaped the session") from exc
            final_frame = cv2.imread(str(final_path), cv2.IMREAD_COLOR)
            atlas_path = _pnsctl().REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
            if final_frame is not None and atlas_path.is_file():
                home = recognize_home(final_frame, reset_identity=str(result.get("reset_identity") or "recovery"))
                terminal_home = _canonical_home_proof(final_frame, home, atlas_path)
                terminal_home_hash = str(final_capture.get("sha256") or "") if terminal_home else None
        if terminal_home:
            return {
                "status": "verified",
                "flow_id": FLOW_ID,
                "session_directory": str(session),
                "queue_label": observation.queue_label,
                "queue_troop_type": observation.queue_troop_type,
                "queue_tier": observation.queue_tier,
                "queue_quantity": observation.queue_quantity,
                "displayed_training_duration_seconds": observation.training_duration_seconds,
                "duration_source": observation.diagnostics.get("duration_source"),
                "queue_roi": observation.diagnostics.get("queue_band"),
                "post_frame_hash": observation.frame_sha256,
                "terminal_home_frame_hash": terminal_home_hash,
                "recovery_reconciled": True,
                "dispatch_count": 1,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            }
        return {
            "status": "evidence_required",
            "flow_id": FLOW_ID,
            "session_directory": str(session),
            "reason": "active queue is positively retained but canonical terminal Home was not proven",
            "queue_label": observation.queue_label,
            "queue_troop_type": observation.queue_troop_type,
            "queue_tier": observation.queue_tier,
            "queue_quantity": observation.queue_quantity,
            "displayed_training_duration_seconds": observation.training_duration_seconds,
            "duration_source": observation.diagnostics.get("duration_source"),
            "queue_roi": observation.diagnostics.get("queue_band"),
            "post_frame_hash": observation.frame_sha256,
            "dispatch_count": result.get("dispatch_count"),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
    if route.get("status") != "completed" or route.get("final_home_recognized") is not True:
        raise _pnsctl().OperatorError("Troop Training route lacks positively proven terminal Home")
    _verify_training_records(route, frame_hashes, _event_rows)
    if route.get("training"):
        terminal_hashes = [
            _require_hash(row.get("terminal_home_frame_hash"), "terminal Home")
            for row in route.get("training", [])
            if isinstance(row, Mapping) and row.get("terminal_home_frame_hash") is not None
        ]
        if not terminal_hashes or not any(value in frame_hashes for value in terminal_hashes):
            raise _pnsctl().OperatorError("Troop Training terminal Home frame hash is missing")
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "session_directory": str(session),
        "training_records": len(route.get("training") or []),
        "resolved_config": route["resolved_config"],
        "dispatch_count": result.get("dispatch_count"),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def recover_troop_training_consolidation(queue: Mapping[str, Any], lease: Mapping[str, Any]) -> str:
    del queue, lease
    pnsctl = _pnsctl()
    root = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"recovery-{_stamp()}"
    root.mkdir(parents=True, exist_ok=False)
    return json.dumps(
        {
            "status": "observed",
            "flow_id": FLOW_ID,
            "session_directory": str(root),
            "dispatch": False,
            "recovery": "observe_only_safe_stop",
        },
        sort_keys=True,
    )


def register(runners: dict[str, Any], validators: dict[str, Any], handlers: dict[str, Any]) -> None:
    runners[RUNNER_ID] = run_troop_training_consolidation
    validators[VALIDATOR_ID] = verify_troop_training_consolidation
    handlers[RECOVERY_ID] = recover_troop_training_consolidation
