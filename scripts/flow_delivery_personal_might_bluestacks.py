"""Personal Might native route and one canonical daily zero-cost Praise."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import shutil
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping

import cv2
import numpy as np

from safe_action_core.path_safety import require_no_untrusted_symlinks
from automation_service.registry import PERSONAL_MIGHT_FLOW_ID, PERSONAL_MIGHT_MAX_INPUTS
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, captured_native_frame_from_png
from scripts.home_atlas_bluestacks import identity_from_captured
from scripts.navigation_development_boundary import DevelopmentInitialObservation, DevelopmentSession
from tasks.runtime_identity import (
    RuntimeIdentityAssurance,
    VerifiedRuntimeIdentity,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    resource_fixed_runtime_binding,
)
from tasks import personal_might_vision as vision
from tasks.personal_might_praise import SEMANTIC_ACTION, SOURCE_STATE, TARGET_IDENTITY, CONSEQUENCE, POSTCONDITION, personal_might_daily_key
from scripts.startup_normalization import is_clean_home_frame
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

FLOW_ID = PERSONAL_MIGHT_FLOW_ID
RUNNER_ID = "personal_might_bluestacks_runner"
VALIDATOR_ID = "personal_might_bluestacks_evidence"
MAX_INPUTS = PERSONAL_MIGHT_MAX_INPUTS
MAX_PRAISE_INPUTS = 1


def _validate_identity(identity, binding, now):
    window = derive_static_utc_reset(now)
    if (
        identity.assurance is not RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET
        or identity.runtime_scope != binding.runtime_scope
        or identity.account_id != binding.account_id
        or identity.server_id != binding.server_id
        or identity.runtime_binding_digest != binding.binding_digest
        or identity.reset_id != window.reset_identity_id
        or identity.reset_start_utc != window.reset_start_text
        or identity.reset_deadline_utc != window.reset_deadline_text
        or not identity.permits_production_consequential
        or not (datetime.fromisoformat(identity.observed_utc.replace("Z", "+00:00")) <= now < datetime.fromisoformat(identity.expires_utc.replace("Z", "+00:00")))
    ):
        raise RuntimeError("Personal Might fixed-slot identity or UTC reset authorization expired")


def _events(path: Path):
    source = path / "events.jsonl"
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()] if source.is_file() else []


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Personal Might evidence timestamp must include UTC")
    return parsed.astimezone(timezone.utc)


def _retained_result(root, retained):
    names = [name for name in ("flow-delivery-result.json", "personal-might-result.json") if (root / name).exists() or (root / name).is_symlink()]
    if len(names) != 1:
        raise ValueError("Personal Might requires one unambiguous retained result")
    result_path = retained(names[0])
    record = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("Personal Might retained result is malformed")
    if names[0] == "personal-might-result.json":
        backend = record.get("backend_identity")
        if (record.get("task_id") != "personal_might_praise" or record.get("runtime_profile_id") != ACTIVE_RUNTIME_PROFILE_ID
                or record.get("time_basis") != "utc" or not isinstance(backend, dict)
                or record.get("reset_id") != "game-day-" + str(backend.get("reset_start_utc", ""))[:10]):
            raise ValueError("Personal Might canonical source identity differs")
        record = {**record, "runtime_identity": backend}
    return result_path, record


def _recovery_proof(source_session, *, store, identity, binding):
    """Read-only validation of one original, transported gold -> gray action."""
    root = require_no_untrusted_symlinks(Path(source_session)).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Personal Might recovery source is not a retained session")

    def retained(value):
        path = Path(value)
        path = path if path.is_absolute() else root / path
        path = require_no_untrusted_symlinks(path).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Personal Might recovery artifact escapes its source session")
        return path

    result_path, record = _retained_result(root, retained)
    key = personal_might_daily_key(runtime_scope=identity.runtime_scope, account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id)
    if (record.get("flow_id") != FLOW_ID
            or require_no_untrusted_symlinks(Path(record.get("session_directory", ""))).resolve() != root
            or record.get("praise_transport_calls") != 1 or record.get("action_key") != key):
        raise ValueError("Personal Might recovery receipt/action identity is not exact")
    old_payload = dict(record["runtime_identity"])
    old_payload["assurance"] = RuntimeIdentityAssurance(old_payload["assurance"])
    old_payload["evidence_refs"] = tuple(old_payload["evidence_refs"])
    old_identity = VerifiedRuntimeIdentity(**old_payload)
    if any(getattr(old_identity, field) != getattr(identity, field) for field in ("runtime_scope", "account_id", "server_id", "reset_id", "runtime_binding_digest", "reset_start_utc", "reset_deadline_utc")):
        raise ValueError("Personal Might recovery belongs to another fixed slot or reset")
    action = store.get_action_by_key(key)
    expected = {"action_id": record.get("action_id"), "task_id": FLOW_ID, "semantic_action": SEMANTIC_ACTION, "source_state": SOURCE_STATE, "target_identity": TARGET_IDENTITY, "game_day_id": identity.reset_id, "consequence": CONSEQUENCE, "expected_postcondition": POSTCONDITION, "cost_type": "none", "cost_amount": 0, "quantity": 1, "consequential": 1}
    if action is None or any(action.get(field) != value for field, value in expected.items()) or action.get("final_status") not in {"unresolved", "input_sent"} or action.get("input_attempt_at") is None:
        raise ValueError("Personal Might recovery canonical action is not the exact sent/unresolved action")
    transport = json.loads(action.get("transport_result_json") or "null")
    if not isinstance(transport, dict) or transport.get("dispatched") is not True:
        raise ValueError("Personal Might recovery lacks a canonical dispatched receipt")
    request = json.loads(action["policy_request_json"])
    request_session = request.get("runtime_session_id")
    if (request.get("free_only") is not True or request.get("maximum_cost") != 0
            or request.get("action_class") != "zero_cost_consequential"
            or not isinstance(request_session, str) or not request_session
            or require_no_untrusted_symlinks(Path(request_session)).resolve(strict=True) != root):
        raise ValueError("Personal Might recovery lacks its canonical zero-cost request")
    events_path = retained(record.get("events_path", "events.jsonl"))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    dispatches = [(index, event) for index, event in enumerate(events) if event.get("type") == "dispatch" and event.get("target_identity") == TARGET_IDENTITY]
    if len(dispatches) != 1:
        raise ValueError("Personal Might recovery requires exactly one Praise dispatch")
    dispatch_index, dispatch = dispatches[0]
    if dispatch.get("action_key") != key or dispatch.get("execute") is not True or dispatch.get("action_class") != "free_action":
        raise ValueError("Personal Might recovery dispatch is not exact")
    _validate_identity(old_identity, binding, _utc(dispatch["timestamp"]))
    canonical_times = []
    for field in ("prepared_at", "input_attempt_at"):
        epoch = action.get(field)
        if type(epoch) not in (int, float) or not math.isfinite(epoch):
            raise ValueError("Personal Might canonical input timestamp is invalid")
        value = datetime.fromtimestamp(epoch, timezone.utc)
        _validate_identity(old_identity, binding, value)
        canonical_times.append(value)
    if not canonical_times[0] <= _utc(dispatch["timestamp"]) <= canonical_times[1]:
        raise ValueError("Personal Might canonical input/dispatch timeline is inconsistent")

    def capture(value):
        path = retained(value)
        matches = [(index, event, ordinal) for ordinal, (index, event) in enumerate(((i, e) for i, e in enumerate(events) if e.get("type") == "capture"), 1) if retained(event["path"]) == path]
        if len(matches) != 1:
            raise ValueError("Personal Might recovery capture is not unique")
        index, event, ordinal = matches[0]
        payload = path.read_bytes()
        mono = event.get("captured_monotonic")
        if type(mono) not in (int, float) or not math.isfinite(mono) or mono <= 0 or hashlib.sha256(payload).hexdigest() != event.get("sha256"):
            raise ValueError("Personal Might recovery capture digest/timestamp mismatch")
        frame = captured_native_frame_from_png(payload, path=path, captured_monotonic=mono)
        source = {"source_frame": identity_from_captured(frame, session_id=str(root), ordinal=ordinal, label="retained-personal-might-reconciliation"), "source_png": payload}
        return index, event, frame, source

    proposal_index, proposal_event, proposal, proposal_source = capture(record["proposal_frame"])
    immediate_index, immediate_event, immediate, immediate_source = capture(record["immediate_frame"])
    if not (proposal_index < immediate_index < dispatch_index and proposal.captured_monotonic < immediate.captured_monotonic) or proposal.sha256 != record.get("proposal_sha256") or immediate.sha256 != record.get("immediate_sha256") or action["source_frame_sha256"] != proposal.sha256 or action["source_frame_captured_at"] != proposal.captured_monotonic or dispatch.get("source_sha256") != immediate.sha256:
        raise ValueError("Personal Might recovery P/I/dispatch provenance mismatch")
    _validate_identity(old_identity, binding, _utc(proposal_event["timestamp"]))
    _validate_identity(old_identity, binding, _utc(immediate_event["timestamp"]))
    if _utc(immediate_event["timestamp"]) > canonical_times[0]:
        raise ValueError("Personal Might canonical prepare precedes its immediate capture")
    targets = [vision.bind_personal_might_praise(frame.frame, **source) for frame, source in ((proposal, proposal_source), (immediate, immediate_source))]
    roi = tuple(dispatch.get("target_roi", ()))
    if any(target is None or target.target_roi != roi for target in targets) or tuple(json.loads(action["target_roi_json"])) != roi:
        raise ValueError("Personal Might recovery gold P/I control does not match the sent action")
    positives = []
    previous_index, previous_mono, previous_utc = dispatch_index, immediate.captured_monotonic, _utc(dispatch["timestamp"])
    for value in record.get("praise_result_frames", ()):
        index, event, frame, source = capture(value)
        if index <= previous_index or frame.captured_monotonic <= previous_mono or _utc(event["timestamp"]) <= previous_utc:
            raise ValueError("Personal Might recovery successor precedes its dispatch")
        previous_index, previous_mono, previous_utc = index, frame.captured_monotonic, _utc(event["timestamp"])
        if vision.personal_might_praised(frame.frame, **source):
            if [i for i, row in enumerate(events) if proposal_index < i < index and row.get("type") == "dispatch"] != [dispatch_index]:
                raise ValueError("Personal Might recovery contains intervening input")
            positives.append(frame)
    if len(positives) < 2 or positives[-1].path != frame.path:
        raise ValueError("Personal Might recovery requires two distinct original gray Rank 1 captures ending disabled")
    positive = positives[-1]
    return {"confirmed": True, "zero_praise_input": True, "reason": "validated_personal_might_gold_to_persistent_gray", "action_id": action["action_id"], "action_key": key, "source_session": str(root), "source_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(), "source_events_sha256": hashlib.sha256(events_path.read_bytes()).hexdigest(), "proposal_sha256": proposal.sha256, "immediate_sha256": immediate.sha256, "post_sha256": positive.sha256, "post_frame": str(positive.path), "original_gray_frames": [str(frame.path) for frame in positives]}


def reconcile_personal_might(*, session, runtime, store, identity, binding, validate_identity, source_session):
    """Observe-only confirmation of the single explicitly linked original action."""
    proof = _recovery_proof(source_session, store=store, identity=identity, binding=binding)
    validate_identity()
    current = session.observe(runtime.capture, label="personal-might-reconciliation-current")
    source = {"source_frame": identity_from_captured(current, session_id=str(runtime.session), ordinal=runtime.ordinal, label="personal-might-reconciliation-current"), "source_png": current.png}
    if runtime.measure_foreground_package() != "com.global.ztmslg" or not vision.personal_might_praised(current.frame, **source) or not 0 <= time.monotonic() - current.captured_monotonic <= 30:
        raise ValueError("Personal Might recovery current disabled Rank 1 state is not proven")
    validate_identity()
    evidence = {**proof, "current_frame": str(current.path), "current_sha256": current.sha256, "current_identity": asdict(identity)}
    store.reconcile_confirmed(proof["action_id"], time.time(), evidence)
    store.audit(FLOW_ID, "personal_might_observe_only_reconciliation", time.time(), evidence, proof["action_id"])
    return {"status": "confirmed", "reason": "personal_might_prior_praise_reconciled", "action_id": proof["action_id"], "action_key": proof["action_key"], "journal_status": "confirmed", "effect_reconciliation_required": False, "praise_transport_calls": 0, "recovery_only": True, "source_praise_transport_calls": 1, "source_session": proof["source_session"], "source_proof": evidence}


def run_personal_might(queue: Mapping[str, Any], lease: Mapping[str, Any], *, live: bool = True) -> str:
    del queue
    from scripts import pnsctl

    maximum = lease.get("max_inputs", MAX_INPUTS)
    if type(maximum) is not int or not 1 <= maximum <= MAX_INPUTS:
        raise pnsctl.OperatorError(f"Personal Might max_inputs must be between 1 and {MAX_INPUTS}")
    if not live:
        return json.dumps({"status": "dry_run", "flow_id": FLOW_ID, "dispatch": False, "input_count": 0, "praise_transport_calls": 0})
    outer = lease.get("development_session")
    initial = lease.get("initial_observation")
    if not isinstance(outer, DevelopmentSession) or not outer.is_active or outer.owner != f"pnsctl-development-session:{FLOW_ID}":
        raise pnsctl.OperatorError("Personal Might requires its active pnsctl DevelopmentSession")
    if not isinstance(initial, DevelopmentInitialObservation) or initial is not outer.initial_observation or initial.frame_sha256 != lease.get("initial_frame_sha256") or initial.invocation_id != outer.invocation_id:
        raise pnsctl.OperatorError("Personal Might initial observation is not session-bound")
    directory = Path(outer.session_directory)
    source = directory / "source.png"
    if not source.is_file() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != initial.frame_sha256:
        raise pnsctl.OperatorError("Personal Might retained initial frame is not identity-bound")
    recovery_only = lease.get("recovery_only") is True
    if recovery_only and not lease.get("recovery_session"):
        raise pnsctl.OperatorError("Personal Might recovery requires its original session")
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(BLUESTACKS_ADB), serial=BLUESTACKS_SERIAL,
        output_directory=directory / "runtime", workflow="personal-might-discovery",
        execute=True,
    )
    child = Path(runtime.session)
    from scripts import personal_might_praise_bluestacks as route
    from scripts.navigation_development_boundary import open_canonical_action_store
    binding = resource_fixed_runtime_binding()
    identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc), evidence_refs=("identity-source:fixed-login-slot", "identity-source:static-UTC-reset", f"session-owner:{outer.owner}", f"session-invocation:{outer.invocation_id}"))
    validate_identity = lambda: _validate_identity(identity, binding, datetime.now(timezone.utc))
    store = open_canonical_action_store()
    leased = False
    result = {}
    try:
        if recovery_only:
            result = reconcile_personal_might(session=outer, runtime=runtime, store=store, identity=identity, binding=binding, validate_identity=validate_identity, source_session=lease["recovery_session"])
            store.acquire_lease(outer.owner, time.time(), 600.0)
            leased = True
            result.update(route.return_home(session=outer, runtime=runtime, settle_seconds=float(lease.get("settle_seconds", 1.0))))
        elif store.has_action_block():
            result = {"status": "blocked", "reason": "canonical_unresolved_action", "praise_transport_calls": 0, "effect_reconciliation_required": True}
        else:
            validate_identity()
            store.acquire_lease(outer.owner, time.time(), 600.0)
            leased = True
            boundary = route.PersonalMightPraiseBoundary(session=outer, runtime=runtime, store=store, identity=identity, validate_identity=validate_identity, settle_seconds=float(lease.get("settle_seconds", 1.0)))
            result = route.run(session=outer, runtime=runtime, settle_seconds=float(lease.get("settle_seconds", 1.0)), praise_boundary=boundary)
    except Exception as exc:
        result = {**result, "status": "blocked", "reason": f"{type(exc).__name__}: {exc}", "praise_transport_calls": result.get("praise_transport_calls", 0), "terminal_home_verified": False}
    finally:
        try:
            if leased:
                store.release_lease(outer.owner, time.time())
        finally:
            store.close()
    events = _events(child)
    count = sum(row.get("type") == "dispatch" and row.get("execute") is not False for row in events)
    praise = sum(row.get("type") == "dispatch" and row.get("target_identity") == "personal-might-praise" for row in events)
    if count != outer.input_count or count > maximum or praise > MAX_PRAISE_INPUTS or (recovery_only and (praise or count > 2)):
        raise pnsctl.OperatorError("Personal Might transport accounting or single-Praise boundary failed")
    retained = child / "frames" / "0000-initial-observation.png"
    retained.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(directory / "source.png", retained)
    initial_mapping = {**initial.to_mapping(), "frame_path": "frames/0000-initial-observation.png"}
    trace = {
        "schema_version": 1, "trace_count": 1, "read_only": True, "input_authority": False,
        "proof_topology": "composite" if recovery_only else "continuous", "flow_id": FLOW_ID,
        "initial_frame_sha256": initial.frame_sha256,
        "invocation_id": initial.invocation_id,
        "transport_count": count, "praise_transport_calls": praise,
        "stages": ["typed_initial_observation", *result.get("verified_navigation", []), result.get("reason", "native_evidence_required")],
    }
    if recovery_only:
        trace.update(source_session=result.get("source_session"), recovery_session=str(child), source_praise_transport_calls=result.get("source_praise_transport_calls", 0), source_proof=result.get("source_proof"))
    (child / "causal-trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    payload = {
        **result, "schema_version": 1, "flow_id": FLOW_ID, "session_directory": str(child),
        "input_count": count, "max_inputs": maximum, "dispatch": count > 0,
        "praise_transport_calls": praise, "effect_reconciliation_required": bool(result.get("effect_reconciliation_required") or (praise and result.get("journal_status") != "confirmed")),
        "runtime_identity": asdict(identity), "identity_semantics": "fixed_runtime_binding_plus_static_utc_reset",
        "production_registration": "NOT_REGISTERED", "scheduler_enabled": False,
        "initial_observation": initial_mapping, "initial_frame_sha256": initial.frame_sha256,
        "causal_trace_count": 1, "causal_trace": trace, "proof_topology": trace["proof_topology"],
    }
    outer.set_causal_trace(trace)
    delivery = {
        **payload, "serial": BLUESTACKS_SERIAL,
        "native_width": 800, "native_height": 1280, "runtime_owner": outer.owner,
        "terminal_runtime_state": "recognized_home" if result.get("terminal_home_verified") is True else "safe_blocked_terminal", "actions": [],
        "frames": [path.relative_to(child).as_posix() for path in (child / "frames").glob("*.png")],
        "required_artifacts": ["events_path"], "events_path": "events.jsonl",
        "causal_trace_path": "causal-trace.json",
    }
    (child / "flow-delivery-result.json").write_text(json.dumps(delivery, indent=2) + "\n", encoding="utf-8")
    return json.dumps(payload, sort_keys=True)


def _validation_session(value):
    root = require_no_untrusted_symlinks(Path(value)).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Personal Might retained session is invalid")

    def path(value):
        found = Path(value)
        found = found if found.is_absolute() else root / found
        found = require_no_untrusted_symlinks(found).resolve(strict=True)
        if not found.is_file() or not found.is_relative_to(root):
            raise ValueError("Personal Might retained artifact escapes its session")
        return found

    result_path, record = _retained_result(root, path)
    if (not isinstance(record, dict) or record.get("flow_id") != FLOW_ID
            or require_no_untrusted_symlinks(Path(record.get("session_directory", ""))).resolve() != root):
        raise ValueError("Personal Might retained result identity differs")
    events_path = path(record.get("events_path", "events.jsonl"))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    captures = {}
    previous_mono = -1
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError("Personal Might retained event is malformed")
        if event.get("type") != "capture":
            continue
        found = path(event["path"])
        mono = event.get("captured_monotonic")
        if found in captures or type(mono) not in (int, float) or not math.isfinite(mono) or mono <= previous_mono:
            raise ValueError("Personal Might capture sequence is not unique and increasing")
        previous_mono = mono
        if hashlib.sha256(found.read_bytes()).hexdigest() != event.get("sha256"):
            raise ValueError("Personal Might retained capture hash differs")
        captures[found] = (index, event, len(captures) + 1)
    cache = {}

    def capture(value):
        found = path(value)
        if found not in captures:
            raise ValueError("Personal Might frame has no retained capture event")
        if found not in cache:
            index, event, ordinal = captures[found]
            payload = found.read_bytes()
            if hashlib.sha256(payload).hexdigest() != event.get("sha256"):
                raise ValueError("Personal Might retained capture hash differs")
            native = captured_native_frame_from_png(payload, path=found, captured_monotonic=event["captured_monotonic"])
            source = {"source_frame": identity_from_captured(native, session_id=str(root), ordinal=ordinal, label="read-only-personal-might-validation"), "source_png": payload}
            cache[found] = (index, event, native, source)
        return cache[found]

    return root, record, events, captures, path, capture, result_path, events_path


def _validation_identity(record, sample):
    from scripts import pnsctl
    values = dict(record["runtime_identity"])
    values["assurance"] = RuntimeIdentityAssurance(values["assurance"])
    values["evidence_refs"] = tuple(values["evidence_refs"])
    identity = VerifiedRuntimeIdentity(**values)
    _validate_identity(identity, resource_fixed_runtime_binding(), _utc(sample))
    key = personal_might_daily_key(runtime_scope=identity.runtime_scope, account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id)
    if record.get("action_key") != key:
        raise ValueError("Personal Might daily action identity differs")
    return identity


def _validation_effect(data, *, action_id, action_key, require_stable_gray):
    _root, record, events, _captures, _path, capture, _result_path, _events_path = data
    praise = [(index, event) for index, event in enumerate(events) if event.get("type") == "dispatch" and event.get("target_identity") == TARGET_IDENTITY]
    if len(praise) != 1 or record.get("action_id") != action_id or record.get("action_key") != action_key or record.get("praise_transport_calls") != 1:
        raise ValueError("Personal Might source effect is not exactly one linked Praise")
    dispatch_index, dispatch = praise[0]
    identity = _validation_identity(record, dispatch["timestamp"])
    pi, pe, proposal, ps = capture(record["proposal_frame"])
    ii, ie, immediate, ins = capture(record["immediate_frame"])
    if not pi < ii < dispatch_index or immediate.captured_monotonic <= proposal.captured_monotonic or proposal.sha256 != record.get("proposal_sha256") or immediate.sha256 != record.get("immediate_sha256") or dispatch.get("source_sha256") != immediate.sha256 or dispatch.get("execute") is not True or dispatch.get("action_class") != "free_action" or dispatch.get("action_key") != action_key:
        raise ValueError("Personal Might source P/I/dispatch chain differs")
    if not _utc(pe["timestamp"]) < _utc(ie["timestamp"]) < _utc(dispatch["timestamp"]):
        raise ValueError("Personal Might source UTC capture order differs")
    _validation_identity(record, pe["timestamp"])
    _validation_identity(record, ie["timestamp"])
    for frame, source in ((proposal, ps), (immediate, ins)):
        target = vision.bind_personal_might_praise(frame.frame, **source)
        if target is None or target.target_roi != tuple(dispatch.get("target_roi", ())):
            raise ValueError("Personal Might source Praise glyph is not exact")
    positives = []
    previous_index, previous_mono, previous_utc = dispatch_index, immediate.captured_monotonic, _utc(dispatch["timestamp"])
    for value in record.get("praise_result_frames", ()):
        index, event, native, source = capture(value)
        if index <= previous_index or native.captured_monotonic <= previous_mono or _utc(event["timestamp"]) <= previous_utc:
            raise ValueError("Personal Might source successor precedes its input")
        previous_index, previous_mono, previous_utc = index, native.captured_monotonic, _utc(event["timestamp"])
        if vision.personal_might_praised(native.frame, **source):
            if [i for i, row in enumerate(events) if ii < i < index and row.get("type") == "dispatch"] != [dispatch_index]:
                raise ValueError("Personal Might source effect has intervening input")
            positives.append(native)
    if len(positives) < (2 if require_stable_gray else 1) or positives[-1].path != native.path:
        raise ValueError("Personal Might source disabled Rank 1 result is missing")
    return identity, proposal, immediate, positives[-1]


def verify_personal_might(structure, queue, lease):
    """Read retained bytes only. Verification never grants input or mutates a store."""
    del queue, lease
    report = {"status": "evidence_required", "flow_id": FLOW_ID, "session_directory": structure.get("session_directory"), "production_registration": "NOT_REGISTERED", "scheduler_enabled": False, "read_only": True, "input_authority": False, "current_effect_verified": False, "source_effect_verified": False, "source_praise_transport_calls": 0}
    try:
        data = _validation_session(structure["session_directory"])
        root, result, events, captures, path, capture, _result_path, _events_path = data
        if structure.get("result") is not None and structure["result"] != result:
            raise ValueError("Personal Might supplied and retained results differ")
        if result.get("status") != "completed" or result.get("terminal_home_verified") is not True or result.get("journal_status") != "confirmed" or result.get("effect_reconciliation_required") is not False:
            raise ValueError("Personal Might route is not semantically complete")
        dispatches = [(i, row) for i, row in enumerate(events) if row.get("type") == "dispatch"]
        reconciliations = [(i, row) for i, row in enumerate(events) if row.get("type") == "reconcile"]
        keys = [row.get("action_key") for _index, row in dispatches]
        if len(set(keys)) != len(keys) or not all(keys) or any(row.get("action_key") not in keys for _i, row in reconciliations):
            raise ValueError("Personal Might action/reconciliation keys are duplicated or orphaned")
        praise_count = sum(row.get("target_identity") == TARGET_IDENTITY for _index, row in dispatches)
        maximum = result.get("max_inputs")
        if type(maximum) is not int or not 1 <= maximum <= MAX_INPUTS or not 0 < len(dispatches) <= maximum or result.get("input_count") != len(dispatches) or praise_count != result.get("praise_transport_calls") or praise_count > 1:
            raise ValueError("Personal Might retained transport counts differ")
        initial = result["initial_observation"]
        initial_bytes = path(initial["frame_path"]).read_bytes()
        initial_pixels = cv2.imdecode(np.frombuffer(initial_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if initial_pixels is None or initial_pixels.shape != (1280, 800, 3) or initial.get("device_state") != "device" or initial.get("foreground_package") != "com.global.ztmslg" or initial.get("native_width") != 800 or initial.get("native_height") != 1280 or hashlib.sha256(initial_bytes).hexdigest() != initial.get("frame_sha256") or initial["frame_sha256"] != result.get("initial_frame_sha256"):
            raise ValueError("Personal Might typed initial bytes differ")
        trace = json.loads(path(result["causal_trace_path"]).read_text(encoding="utf-8"))
        if trace != result.get("causal_trace") or result.get("causal_trace_count") != 1 or trace.get("trace_count") != 1 or trace.get("read_only") is not True or trace.get("input_authority") is not False or trace.get("initial_frame_sha256") != initial["frame_sha256"] or trace.get("invocation_id") != initial.get("invocation_id") or trace.get("transport_count") != len(dispatches) or trace.get("praise_transport_calls") != praise_count or trace.get("proof_topology") != result.get("proof_topology"):
            raise ValueError("Personal Might retained causal trace differs")
        identity = _validation_identity(result, dispatches[0][1]["timestamp"])
        for _index, dispatch in dispatches:
            _validation_identity(result, dispatch["timestamp"])
        clean_home = lambda native, source: is_clean_home_frame(native.frame) and not vision.more_menu_present(native.frame, **source)
        bindings = {
            vision.MORE_TARGET: (lambda n, s: vision.bind_home_more(n.frame, **s, home_is_clean=is_clean_home_frame), lambda n, s: vision.recognize_more_menu(n.frame, **s, home_is_clean=is_clean_home_frame)),
            vision.RANKINGS_TARGET: (lambda n, s: vision.bind_more_rankings(n.frame, **s, home_is_clean=is_clean_home_frame), lambda n, s: vision.is_rankings(n.frame, **s)),
            vision.CHECK_TARGET: (lambda n, s: vision.bind_personal_might_check(n.frame, **s), lambda n, s: vision.is_personal_might(n.frame, **s)),
            "personal-might-back": (lambda n, s: vision.bind_back(n.frame, **s, personal_page=True), lambda n, s: vision.is_rankings(n.frame, **s)),
            "leaderboard-back": (lambda n, s: vision.bind_back(n.frame, **s, personal_page=False), clean_home),
            TARGET_IDENTITY: (lambda n, s: vision.bind_personal_might_praise(n.frame, **s), lambda n, s: vision.personal_might_praised(n.frame, **s)),
        }
        final = None
        for ordinal, (index, dispatch) in enumerate(dispatches):
            if dispatch.get("target_identity") not in bindings or dispatch.get("execute") is not True:
                raise ValueError("Personal Might dispatch is not an exact allowed control")
            if dispatch.get("action_class") != ("free_action" if dispatch["target_identity"] == TARGET_IDENTITY else "navigation") or dispatch.get("consequential") is not False:
                raise ValueError("Personal Might retained action class differs")
            before = [value for value in captures.values() if value[0] < index and value[1].get("sha256") == dispatch.get("source_sha256")]
            if not before:
                raise ValueError("Personal Might input has no current source capture")
            before_index, before_event, _capture_ordinal = max(before, key=lambda value: value[0])
            if not 0 <= (_utc(dispatch["timestamp"]) - _utc(before_event["timestamp"])).total_seconds() <= 30:
                raise ValueError("Personal Might input source was stale")
            _bi, _be, native, source = capture(before_event["path"])
            binder, successor = bindings[dispatch["target_identity"]]
            target = binder(native, source)
            if target is None or target.target_roi != tuple(dispatch.get("target_roi", ())):
                raise ValueError("Personal Might retained target is not bound from its source")
            if list(dispatch.get("point", ())) != [(target.target_roi[0] + target.target_roi[2]) // 2, (target.target_roi[1] + target.target_roi[3]) // 2]:
                raise ValueError("Personal Might actual dispatch point differs from its bound control")
            if dispatch["target_identity"] == "personal-might-back" and not vision.personal_might_praised(native.frame, **source):
                raise ValueError("Personal Might persistent disabled state before return is missing")
            linked = [(ri, row) for ri, row in reconciliations if row.get("action_key") == dispatch["action_key"]]
            if len(linked) != 1 or linked[0][1].get("status") != "confirmed":
                raise ValueError("Personal Might successor is unresolved or ambiguous")
            ri, reconciliation = linked[0]
            ai, _ae, after, after_source = capture(reconciliation["post_path"])
            next_input = dispatches[ordinal + 1][0] if ordinal + 1 < len(dispatches) else len(events)
            if not before_index < index < ai < ri < next_input or after.sha256 != reconciliation.get("post_sha256") or not successor(after, after_source):
                raise ValueError("Personal Might action successor chain differs")
            final = after, after_source
        if final is None or str(final[0].path) != str(path(result["successor_frame"])) or final[0].sha256 != result.get("successor_sha256") or not clean_home(*final):
            raise ValueError("Personal Might final clean Home is not proven")
        targets = [row["target_identity"] for _i, row in dispatches]
        if result.get("proof_topology") == "continuous":
            expected = [vision.MORE_TARGET, vision.RANKINGS_TARGET, vision.CHECK_TARGET] + ([TARGET_IDENTITY] if praise_count else []) + ["personal-might-back", "leaderboard-back"]
            if targets != expected or (not praise_count and result.get("no_work") is not True):
                raise ValueError("Personal Might continuous Home round trip is incomplete")
            gray = [capture(row["path"]) for row in events if row.get("type") == "capture" and row.get("label") == "personal-might-already-praised"]
            if not praise_count and (len(gray) != 1 or not vision.personal_might_praised(gray[0][2].frame, **gray[0][3])):
                raise ValueError("Personal Might no-work disabled state is missing")
            if praise_count:
                _validation_effect(data, action_id=result["action_id"], action_key=result["action_key"], require_stable_gray=False)
                report["current_effect_verified"] = True
            report["proof_scope"] = "continuous_praise_round_trip" if praise_count else "continuous_no_work_round_trip"
        elif result.get("proof_topology") == "composite":
            proof = result["source_proof"]
            if praise_count or targets != ["personal-might-back", "leaderboard-back"] or result.get("source_praise_transport_calls") != 1 or proof.get("confirmed") is not True or proof.get("zero_praise_input") is not True or proof.get("action_id") != result.get("action_id") or proof.get("action_key") != result.get("action_key"):
                raise ValueError("Personal Might composite source link is not exact")
            if trace.get("source_proof") != proof or trace.get("source_session") != result["source_session"] or proof.get("source_session") != result["source_session"] or require_no_untrusted_symlinks(Path(trace.get("recovery_session", ""))).resolve() != root or trace.get("source_praise_transport_calls") != 1:
                raise ValueError("Personal Might composite trace link differs")
            prior = _validation_session(result["source_session"])
            if hashlib.sha256(prior[6].read_bytes()).hexdigest() != proof.get("source_result_sha256") or hashlib.sha256(prior[7].read_bytes()).hexdigest() != proof.get("source_events_sha256"):
                raise ValueError("Personal Might linked source artifacts differ")
            old_identity, proposal, immediate, post = _validation_effect(prior, action_id=result["action_id"], action_key=result["action_key"], require_stable_gray=True)
            if any(getattr(old_identity, field) != getattr(identity, field) for field in ("runtime_scope", "account_id", "server_id", "reset_id")) or any(proof.get(field) != value for field, value in (("proposal_sha256", proposal.sha256), ("immediate_sha256", immediate.sha256), ("post_sha256", post.sha256))):
                raise ValueError("Personal Might linked source identity or frame hashes differ")
            _ci, _ce, current, current_source = capture(proof["current_frame"])
            if _ci >= dispatches[0][0] or current.sha256 != proof.get("current_sha256") or proof.get("current_identity") != result["runtime_identity"] or not vision.personal_might_praised(current.frame, **current_source):
                raise ValueError("Personal Might recovery fresh gray state is missing")
            report.update(source_effect_verified=True, source_praise_transport_calls=1, proof_scope="composite_source_praise_and_home_recovery")
        else:
            raise ValueError("Personal Might proof topology is unsupported")
        report.update(status="verified", reason=None, retained_transport_count=len(dispatches), praise_transport_calls=praise_count, terminal_home_verified=True)
    except (KeyError, TypeError, ValueError, OSError, RuntimeError, AttributeError, cv2.error) as exc:
        report["reason"] = f"Personal Might retained proof is incomplete: {exc}"
    return report


def register(runners, validators):
    runners[RUNNER_ID] = run_personal_might
    validators[VALIDATOR_ID] = verify_personal_might
