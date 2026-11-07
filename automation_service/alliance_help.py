"""Canonical, reset-scoped Alliance Help execution through the native route boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path, PurePosixPath
import re
import time
from types import MappingProxyType
from typing import Any, Mapping

from safe_action_core.path_safety import require_no_untrusted_symlinks
from tasks.alliance_help import (
    CONSEQUENCE, DAILY_REQUEST_LIMIT, INDIVIDUAL_TARGET_IDENTITY,
    POSTCONDITION, SEMANTIC_ACTION, SOURCE_STATE, alliance_help_action_key,
)
from tasks.runtime_identity import (
    BLUESTACKS_ADB, BLUESTACKS_SERIAL, VerifiedRuntimeIdentity,
    derive_resource_runtime_identity, resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from .registry import (
    ALLIANCE_HELP_FLOW_ID, ALLIANCE_HELP_MAX_INPUTS, ALLIANCE_HELP_PRODUCT_ID,
    ALLIANCE_HELP_PRODUCT_REVISION, ALLIANCE_HELP_PROFILE_ID,
    RegisteredDispatchSnapshot, canonical_entry,
)
from .recruitment import recruitment_reset


FLOW_ID = ALLIANCE_HELP_FLOW_ID
PRODUCT_ID = ALLIANCE_HELP_PRODUCT_ID
PRODUCT_REVISION = ALLIANCE_HELP_PRODUCT_REVISION
PROFILE_ID = ALLIANCE_HELP_PROFILE_ID
MAX_INPUTS = ALLIANCE_HELP_MAX_INPUTS
MAX_ACTIONS = DAILY_REQUEST_LIMIT
OBSERVATION_RETRY_SECONDS = 300.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AllianceHelpExecutionHandler:
    """Installable handler: all execution is delegated to the canonical runner."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Alliance Help requires a typed registered dispatch snapshot")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Alliance Help registration identity mismatch")
        if not callable(execute):
            raise TypeError("Alliance Help executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Alliance Help requires its matching route specification")
        self.snapshot, self._execute = snapshot, execute
        self.flow_spec = flow_spec

    def describe(self):
        return canonical_entry(FLOW_ID).descriptor

    def eligibility(self, facts, perception=None):
        return bool(not facts.gate_failures(self.describe())
            and facts.accepted_product == PRODUCT_ID
            and facts.product_revision == PRODUCT_REVISION
            and facts.registration_status == "REGISTERED"
            and facts.scheduler_eligible is True
            and (perception is None or perception.profile_id == PROFILE_ID))

    revalidate = eligibility

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)

    def plan(self, facts, perception=None):
        return self.recover("ALLIANCE_HELP_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("ALLIANCE_HELP_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


def _epoch(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Alliance Help {name} must be a finite UTC epoch")
    return float(value)


def _same_backend_window(left: VerifiedRuntimeIdentity, right: VerifiedRuntimeIdentity) -> bool:
    return (left.runtime_scope, left.account_id, left.server_id, left.reset_id,
            left.runtime_binding_digest, left.reset_start_utc, left.reset_deadline_utc) == (
            right.runtime_scope, right.account_id, right.server_id, right.reset_id,
            right.runtime_binding_digest, right.reset_start_utc, right.reset_deadline_utc)


def _read_frame_reference(root_value: Path | str, path_value: object, digest_value: object, field: str) -> dict[str, str]:
    if (type(path_value) is not str or not path_value or path_value != path_value.strip()
            or type(digest_value) is not str or _SHA256_RE.fullmatch(digest_value) is None):
        raise ValueError(f"Alliance Help {field} evidence reference is malformed")
    root = require_no_untrusted_symlinks(Path(root_value)).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Alliance Help native session directory is not a directory")
    supplied = Path(path_value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    resolved = require_no_untrusted_symlinks(candidate).resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Alliance Help {field} escapes its native session") from exc
    if not resolved.is_file() or hashlib.sha256(resolved.read_bytes()).hexdigest() != digest_value:
        raise ValueError(f"Alliance Help {field} bytes differ from the retained capture hash")
    return {"frame_path": PurePosixPath(relative.as_posix()).as_posix(), "frame_sha256": digest_value}


def _normalize_native_frames(value: Mapping[str, Any], session_directory: str | None) -> dict[str, Any]:
    if not isinstance(session_directory, str) or not session_directory.strip():
        raise ValueError("Alliance Help native output omitted its session directory")
    root = Path(session_directory)
    result = dict(value)
    for field in ("source_frame", "terminal_home_frame"):
        reference = result.get(field)
        if reference is not None:
            if not isinstance(reference, Mapping):
                raise ValueError(f"Alliance Help {field} is malformed")
            result[field] = _read_frame_reference(root, reference.get("frame_path"),
                reference.get("frame_sha256"), field)
    no_work = result.get("no_work_evidence")
    if no_work is not None:
        if not isinstance(no_work, Mapping):
            raise ValueError("Alliance Help no-work evidence is malformed")
        normalized = dict(no_work)
        ref = _read_frame_reference(root, normalized.get("frame_path"), normalized.get("frame_sha256"), "no-work")
        normalized.update(ref)
        result["no_work_evidence"] = normalized
    actions = result.get("request_actions", ())
    if not isinstance(actions, (list, tuple)):
        raise ValueError("Alliance Help request actions are malformed")
    normalized_actions: list[dict[str, Any]] = []
    for index, raw in enumerate(actions):
        if not isinstance(raw, Mapping):
            raise ValueError("Alliance Help request action is malformed")
        action = dict(raw)
        for path_field, digest_field in (("proposal_frame", "proposal_sha256"),
                                         ("immediate_before_frame", "immediate_before_sha256")):
            if action.get(path_field) is not None:
                action[path_field] = _read_frame_reference(root, action.get(path_field),
                    action.get(digest_field), f"request-action-{index}-{path_field}")
        action_no_work = action.get("no_work_evidence")
        if action_no_work is not None:
            if not isinstance(action_no_work, Mapping):
                raise ValueError("Alliance Help request action no-work evidence is malformed")
            normalized_no_work = dict(action_no_work)
            normalized_no_work.update(_read_frame_reference(root,
                normalized_no_work.get("frame_path"), normalized_no_work.get("frame_sha256"),
                f"request-action-{index}-no-work"))
            action["no_work_evidence"] = normalized_no_work
        evidence = action.get("request_result_evidence", ())
        frames = action.get("request_result_frames", ())
        if not isinstance(evidence, (list, tuple)) or not isinstance(frames, (list, tuple)):
            raise ValueError("Alliance Help request result frames are malformed")
        normalized_evidence: list[dict[str, Any]] = []
        for frame_index, raw_frame in enumerate(evidence):
            if not isinstance(raw_frame, Mapping):
                raise ValueError("Alliance Help request result frame is malformed")
            frame = dict(raw_frame)
            frame.update(_read_frame_reference(root, frame.get("frame_path"),
                frame.get("frame_sha256"), f"request-action-{index}-result-{frame_index}"))
            normalized_evidence.append(frame)
        if len(frames) != len(normalized_evidence):
            raise ValueError("Alliance Help request result references do not match retained frames")
        for old_path, new_frame in zip(frames, normalized_evidence):
            old_ref = _read_frame_reference(root, old_path, new_frame.get("frame_sha256"),
                f"request-action-{index}-result-list")
            if old_ref["frame_path"] != new_frame["frame_path"]:
                raise ValueError("Alliance Help request result frame order differs")
        action["request_result_frames"] = [frame["frame_path"] for frame in normalized_evidence]
        action["request_result_evidence"] = normalized_evidence
        normalized_actions.append(action)
    result["request_actions"] = normalized_actions
    return result


def _backend_proof(result: Mapping[str, Any], identity: SchedulerIdentity, completed: float) -> Mapping[str, Any]:
    proof = result.get("backend_identity")
    if not isinstance(proof, Mapping):
        raise ValueError("Alliance Help fixed backend identity proof is missing")
    binding = resource_fixed_runtime_binding()
    expected = derive_resource_runtime_identity(binding,
        datetime.fromtimestamp(completed, timezone.utc))
    if (proof.get("runtime_scope"), proof.get("account_id"), proof.get("server_id"),
            proof.get("reset_id"), proof.get("runtime_binding_digest"),
            proof.get("reset_start_utc"), proof.get("reset_deadline_utc"),
            proof.get("assurance")) != (
            expected.runtime_scope, expected.account_id, expected.server_id, expected.reset_id,
            expected.runtime_binding_digest, expected.reset_start_utc, expected.reset_deadline_utc,
            expected.assurance.value):
        raise ValueError("Alliance Help backend identity proof does not match the current fixed reset window")
    if (identity.account_id, identity.server_id) != (expected.account_id, expected.server_id):
        raise ValueError("Alliance Help scheduler/backend account or server differs")
    refs = proof.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(type(item) is not str or not item.strip() for item in refs):
        raise ValueError("Alliance Help backend identity evidence references are missing")
    observed_text, expires_text = proof.get("observed_utc"), proof.get("expires_utc")
    if type(observed_text) is not str or type(expires_text) is not str:
        raise ValueError("Alliance Help backend identity freshness timestamps are missing")
    try:
        observed = datetime.fromisoformat(observed_text.replace("Z", "+00:00")).timestamp()
        expires = datetime.fromisoformat(expires_text.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ValueError("Alliance Help backend identity freshness timestamps are malformed") from exc
    if not observed <= completed < expires:
        raise ValueError("Alliance Help backend identity expired during execution")
    return proof


def _canonical_confirmations(result: Mapping[str, Any], identity: SchedulerIdentity,
                             backend: Mapping[str, Any]) -> tuple[int, list[Mapping[str, Any]]]:
    count = result.get("confirmed_request_count")
    records = result.get("confirmed_request_records")
    if type(count) is not int or not 0 <= count <= DAILY_REQUEST_LIMIT or not isinstance(records, list):
        raise ValueError("Alliance Help durable confirmed request prefix is malformed")
    if len(records) != count:
        raise ValueError("Alliance Help confirmed count differs from canonical request records")
    runtime_scope = backend.get("runtime_scope")
    backend_reset = backend.get("reset_id")
    accepted: list[Mapping[str, Any]] = []
    for ordinal, record in enumerate(records, 1):
        if not isinstance(record, Mapping):
            raise ValueError("Alliance Help canonical request record is malformed")
        key = alliance_help_action_key(runtime_scope=str(runtime_scope), account_id=identity.account_id,
            server_id=identity.server_id, reset_id=str(backend_reset), ordinal=ordinal)
        expected = {
            "request_ordinal": ordinal, "action_key": key, "task_id": FLOW_ID,
            "semantic_action": SEMANTIC_ACTION, "source_state": SOURCE_STATE,
            "target_identity": INDIVIDUAL_TARGET_IDENTITY, "game_day_id": backend_reset,
            "expected_postcondition": POSTCONDITION, "consequence": CONSEQUENCE,
            "cost_type": "none", "cost_amount": 0, "quantity": 1,
            "consequential": 1, "final_status": "confirmed",
        }
        if any(record.get(field) != value for field, value in expected.items()):
            raise ValueError("Alliance Help canonical request identity or result differs")
        if type(record.get("action_id")) is not str or not record["action_id"].strip():
            raise ValueError("Alliance Help canonical request action id is missing")
        accepted.append(record)
    return count, accepted


def _validate_successful_dispatches(result: Mapping[str, Any], count: int) -> int:
    calls = result.get("help_transport_calls")
    actions = result.get("request_actions", [])
    dispatches = result.get("help_dispatch_evidence", [])
    if (type(calls) is not int or not 0 <= calls <= MAX_ACTIONS
            or not isinstance(actions, list) or not isinstance(dispatches, list)
            or len(dispatches) != calls):
        raise ValueError("Alliance Help transport evidence is incomplete")
    confirmed = [action for action in actions if isinstance(action, Mapping)
                 and action.get("status") == "confirmed"]
    if len(confirmed) != calls or count < len(confirmed):
        raise ValueError("Alliance Help transport evidence differs from confirmed successor count")
    by_key = {record.get("action_key"): record for record in result["confirmed_request_records"]}
    dispatch_by_key: dict[str, Mapping[str, Any]] = {}
    for dispatch in dispatches:
        if not isinstance(dispatch, Mapping):
            raise ValueError("Alliance Help dispatch evidence is malformed")
        key, digest = dispatch.get("action_key"), dispatch.get("immediate_before_sha256")
        if (dispatch.get("target_identity") != INDIVIDUAL_TARGET_IDENTITY
                or type(key) is not str or key in dispatch_by_key
                or type(digest) is not str or _SHA256_RE.fullmatch(digest) is None):
            raise ValueError("Alliance Help dispatch target or identity is invalid")
        dispatch_by_key[key] = dispatch
    for action in confirmed:
        ordinal, key = action.get("request_ordinal"), action.get("action_key")
        if type(ordinal) is not int or not 1 <= ordinal <= count or by_key.get(key) is None:
            raise ValueError("Alliance Help transported action is not in the canonical confirmed prefix")
        if (action.get("journal_status") != "confirmed"
                or action.get("verified_request_count") != 1
                or action.get("help_transport_calls") != 1
                or action.get("effect_reconciliation_required") is not False
                or _SHA256_RE.fullmatch(str(action.get("selected_request_sha256", ""))) is None):
            raise ValueError("Alliance Help request action did not confirm one exact free request")
        immediate_sha = action.get("immediate_before_sha256")
        dispatch = dispatch_by_key.get(key)
        if (not isinstance(dispatch, Mapping) or dispatch.get("immediate_before_sha256") != immediate_sha
                or not isinstance(action.get("immediate_before_frame"), Mapping)):
            raise ValueError("Alliance Help transport is not bound to its immediate-before frame")
        before_balance = action.get("immediate_daily_alliance_coin_balance")
        before_limit = action.get("immediate_daily_alliance_coin_limit")
        evidence = action.get("request_result_evidence")
        if (type(before_balance) is not int or type(before_limit) is not int
                or not isinstance(evidence, list) or len(evidence) < 2):
            raise ValueError("Alliance Help request result lacks a bound coin counter or stable frames")
        def absent_on_help(frame: Mapping[str, Any]) -> bool:
            return (frame.get("selected_request_absent") is True
                    and frame.get("screen_state") == SOURCE_STATE
                    and frame.get("source_fresh") is True
                    and frame.get("overlay_clear") is True)

        # The native boundary retains pending captures before the positive
        # transition. Only a positive frame followed by the final stable
        # successor establishes success; earlier evidence must remain intact.
        if any(not isinstance(frame, Mapping) for frame in evidence):
            raise ValueError("Alliance Help request result evidence is malformed")
        stable = evidence[-1]
        if not absent_on_help(stable):
            raise ValueError("Alliance Help selected request disappearance is ambiguous")
        positive = [frame for frame in evidence[:-1] if absent_on_help(frame)
                    and frame.get("success_message") is True
                    and type(frame.get("daily_alliance_coin_balance")) is int
                    and 0 <= before_balance < frame["daily_alliance_coin_balance"] <= before_limit
                    and frame.get("daily_alliance_coin_limit") == before_limit
                    and stable.get("daily_alliance_coin_balance") == frame["daily_alliance_coin_balance"]
                    and stable.get("daily_alliance_coin_limit") == before_limit]
        if not positive:
            raise ValueError("Alliance Help request lacks its exact success toast and stable positive same-cap coin delta")
    if set(dispatch_by_key) != {action.get("action_key") for action in confirmed}:
        raise ValueError("Alliance Help includes a dispatch without one confirmed request result")
    return calls


def _validate_no_work(result: Mapping[str, Any]) -> None:
    if result.get("no_work") is not True:
        raise ValueError("Alliance Help deferred result is not a current no-work observation")
    evidence = result.get("no_work_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("Alliance Help no-work source evidence is missing")
    if (evidence.get("screen_state") != SOURCE_STATE or evidence.get("source_fresh") is not True
            or evidence.get("overlay_clear") is not True or evidence.get("cost_marker_seen") is not False
            or type(evidence.get("free_request_controls")) is not int
            or evidence.get("free_request_controls") != 0
            or type(evidence.get("frame_sha256")) is not str
            or _SHA256_RE.fullmatch(evidence["frame_sha256"]) is None
            or type(evidence.get("frame_path")) is not str or not evidence["frame_path"]):
        raise ValueError("Alliance Help no-work evidence is stale, ambiguous, or paid")
    if (result.get("reason") == "exact_no_requests_message"
            and evidence.get("exact_no_requests_message") is not True):
        raise ValueError("Alliance Help exact no-request result message is unproven")
    if result.get("reason") not in {"exact_no_requests_message", "no_current_free_request_control"}:
        raise ValueError("Alliance Help deferred reason is not an observed availability stop")


def alliance_help_next_due(result: Mapping[str, Any], identity: SchedulerIdentity,
                           started_at: float) -> float:
    """Admit exact ten-request completion or a normal, Home-closed availability pulse."""
    started = _epoch(started_at, "start time")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Alliance Help outcome requires its exact scheduler task identity")
    if completed < started or recruitment_reset(completed) != identity.reset_id:
        raise ValueError("Alliance Help outcome crossed or mismatched its scheduler reset")
    if (result.get("flow_id") != FLOW_ID or result.get("product_id") != PRODUCT_ID
            or result.get("product_revision") != PRODUCT_REVISION or result.get("task_id") != PRODUCT_ID
            or result.get("scheduler_reset_id") != identity.reset_id
            or result.get("account_id") != identity.account_id or result.get("server_id") != identity.server_id
            or result.get("time_basis") != "utc" or result.get("occurrence_key") is None
            or result.get("native_failure") is not None or result.get("native_execution_verified") is not True
            or result.get("accounting_verified") is not True
            or result.get("effect_reconciliation_required") is not False
            or result.get("identical_retry_denied") is not False
            or result.get("terminal_home_verified") is not True):
        raise ValueError("Alliance Help outcome lacks exact current identity, accounting, or safe Home closure")
    if (result.get("max_inputs") != MAX_INPUTS or result.get("max_actions") != MAX_ACTIONS
            or type(result.get("input_count")) is not int
            or result.get("input_count") != result.get("total_input_count")
            or result.get("input_count") != result.get("session_input_count")
            or result.get("input_count") != result.get("runtime_input_count")
            or not 0 <= result["input_count"] <= MAX_INPUTS):
        raise ValueError("Alliance Help native and session input accounting differs")
    backend = _backend_proof(result, identity, completed)
    if result.get("backend_reset_id") != backend.get("reset_id"):
        raise ValueError("Alliance Help backend reset identity was not preserved separately")
    count, _records = _canonical_confirmations(result, identity, backend)
    calls = _validate_successful_dispatches(result, count)
    if result.get("committed_action_count") != count or result.get("verified_request_count") != count:
        raise ValueError("Alliance Help committed request count is not the durable confirmed prefix")
    if result.get("status") == "complete_for_reset":
        if count != DAILY_REQUEST_LIMIT:
            raise ValueError("Alliance Help reset completion requires ten confirmed requests")
        reset_due = datetime.fromisoformat(str(backend["reset_deadline_utc"]).replace("Z", "+00:00"))
        return max(completed, reset_due.timestamp())
    if result.get("status") != "deferred" or count >= DAILY_REQUEST_LIMIT or calls > count:
        raise ValueError("Alliance Help outcome is not a resumable partial/no-work result")
    _validate_no_work(result)
    return min(completed + OBSERVATION_RETRY_SECONDS,
               datetime.fromisoformat(str(backend["reset_deadline_utc"]).replace("Z", "+00:00")).timestamp())


def normalize_alliance_help_result(result: Mapping[str, Any], identity: SchedulerIdentity,
                                   started_at: float) -> NormalizedResult:
    """Translate only verified completion or an exact partial availability observation."""
    status = result.get("status")
    calls = result.get("help_transport_calls", 0)
    unresolved = bool(result.get("effect_reconciliation_required") or calls or result.get("native_failure"))
    if status in {"complete_for_reset", "deferred"}:
        due = alliance_help_next_due(result, identity, started_at)
        count = result["confirmed_request_count"]
        actions = result.get("request_actions", [])
        performed = sum(isinstance(item, Mapping) and item.get("status") == "confirmed" for item in actions)
        refs = []
        terminal = result.get("terminal_home_frame")
        if isinstance(terminal, Mapping):
            refs.append(f"frame:{terminal.get('frame_sha256')}")
        no_work = result.get("no_work_evidence")
        if isinstance(no_work, Mapping):
            refs.append(f"frame:{no_work.get('frame_sha256')}")
        outcome = NormalizedOutcome.COMPLETE_FOR_RESET if status == "complete_for_reset" else NormalizedOutcome.DEFERRED
        return NormalizedResult(outcome, "ALLIANCE_HELP_TEN_CONFIRMED" if status == "complete_for_reset"
            else "ALLIANCE_HELP_AVAILABILITY_DEFERRED", action_count=performed, verified=True,
            next_eligible_at=due, observed_progress={"confirmed_request_count": count,
                "remaining_request_target": DAILY_REQUEST_LIMIT - count},
            consequence={"committed_action_count": count, "help_transport_calls": calls,
                "remaining_request_target": DAILY_REQUEST_LIMIT - count}, evidence_refs=tuple(refs))
    if unresolved or status == "reconciliation_required":
        return NormalizedResult(NormalizedOutcome.RECONCILIATION_REQUIRED,
            "ALLIANCE_HELP_EFFECT_REQUIRES_RECONCILIATION", action_count=0, verified=False,
            observed_progress={"confirmed_request_count": result.get("confirmed_request_count", 0),
                "remaining_request_target": max(0, DAILY_REQUEST_LIMIT - int(result.get("confirmed_request_count", 0) or 0))},
            unresolved_action=True)
    return NormalizedResult(NormalizedOutcome.BLOCKED, "ALLIANCE_HELP_NATIVE_RESULT_NOT_VERIFIED",
        action_count=0, verified=False, unresolved_action=False)


class AllianceHelpRunner:
    """Device-free construction over an injected, fixed native route binding."""

    def __init__(self, *, native: NativeRouteBoundary | None = None,
                 adb: str = str(BLUESTACKS_ADB), serial: str = BLUESTACKS_SERIAL,
                 output_directory: Path, utc_clock=time.time, monotonic_clock=time.monotonic,
                 settle_seconds: float = 1.0):
        self.native = native
        self.adb, self.serial = str(adb), serial
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")
        if self.settle_seconds > 30.0:
            raise ValueError("Alliance Help settle delay exceeds its reviewed bound")
        if native is not None and (native.flow_id, native.product_id, native.product_revision,
                native.runtime_profile_id, native.max_inputs, native.max_actions) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID, MAX_INPUTS, MAX_ACTIONS):
            raise ValueError("Alliance Help native binding identity or budget mismatch")

    def __call__(self, identity: SchedulerIdentity, previous_reset_id: str | None, checkpoint,
                 *, runtime_input_lock, occurrence_key: str) -> dict[str, Any]:
        started = _epoch(self.utc_clock(), "start time")
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Alliance Help scheduler task identity mismatch")
        if recruitment_reset(started) != identity.reset_id:
            raise ValueError("Alliance Help scheduler reset identity is not current")
        if type(occurrence_key) is not str or not occurrence_key or occurrence_key != occurrence_key.strip():
            raise ValueError("Alliance Help requires the canonical service occurrence key")
        if (getattr(runtime_input_lock, "owner", None) != "automation-service"
                or not isinstance(getattr(runtime_input_lock, "invocation_id", None), str)
                or not runtime_input_lock.invocation_id or not callable(checkpoint)):
            raise ValueError("Alliance Help requires the canonical held owner and checkpoint")
        runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
        if (self.adb, self.serial) != (str(BLUESTACKS_ADB), BLUESTACKS_SERIAL):
            raise ValueError("Alliance Help runtime configuration differs from its fixed BlueStacks binding")
        binding = resource_fixed_runtime_binding()
        backend_identity = derive_resource_runtime_identity(binding,
            datetime.fromtimestamp(started, timezone.utc))
        if (identity.account_id, identity.server_id) != (backend_identity.account_id, backend_identity.server_id):
            raise ValueError("Alliance Help scheduler and fixed backend account/server differ")

        def validate_identity() -> None:
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            checkpoint()
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            now = _epoch(self.utc_clock(), "identity checkpoint")
            if identity.task_id != PRODUCT_ID or recruitment_reset(now) != identity.reset_id:
                raise ValueError("Alliance Help scheduler reset changed during native execution")
            current = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
            if not _same_backend_window(current, backend_identity):
                raise ValueError("Alliance Help fixed backend identity or reset window changed")

        if self.native is None:
            completed = _epoch(self.utc_clock(), "completion time")
            return {"status": "blocked", "flow_id": FLOW_ID, "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION, "task_id": PRODUCT_ID,
                "account_id": identity.account_id, "server_id": identity.server_id,
                "reset_id": identity.reset_id, "scheduler_reset_id": identity.reset_id,
                "occurrence_key": occurrence_key, "time_basis": "utc", "started_at_utc": started,
                "completed_at_utc": completed, "help_transport_calls": 0,
                "confirmed_request_count": 0, "committed_action_count": 0,
                "remaining_request_target": DAILY_REQUEST_LIMIT,
                "accounting_verified": False, "native_execution_verified": False,
                "native_failure": "Alliance Help native route binding is unavailable",
                "effect_reconciliation_required": False, "identical_retry_denied": False}

        request = NativeRouteRequest(
            flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            runtime_profile_id=PROFILE_ID, identity=identity, previous_reset_id=previous_reset_id,
            occurrence_key=occurrence_key, checkpoint=checkpoint, validate_identity=validate_identity,
            runtime_input_lock=runtime_input_lock, adb=self.adb, serial=self.serial,
            output_directory=self.output_directory, max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
            settle_seconds=self.settle_seconds, arguments=MappingProxyType({}),
            utc_clock=self.utc_clock, monotonic_clock=self.monotonic_clock,
        )
        outcome: NativeRouteOutcome | None = None
        failure: str | None = None
        try:
            validate_identity()
            outcome = self.native.run(request)
            if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
                raise TypeError("Alliance Help native boundary returned an invalid outcome")
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            outcome = getattr(exc, "partial_outcome", None)

        raw_result: dict[str, Any] = {}
        if isinstance(outcome, NativeRouteOutcome):
            for candidate in (outcome.partial_result, outcome.native_result):
                if isinstance(candidate, Mapping):
                    raw_result.update(candidate)
            failure = failure or outcome.failure
            if outcome.session_directory and raw_result:
                try:
                    raw_result = _normalize_native_frames(raw_result, outcome.session_directory)
                except (OSError, ValueError, RuntimeError) as exc:
                    failure = failure or f"Alliance Help retained frame validation failed: {exc}"

        completed = _epoch(self.utc_clock(), "completion time")
        raw_calls = raw_result.get("help_transport_calls", 0)
        calls = raw_calls if type(raw_calls) is int and 0 <= raw_calls <= MAX_ACTIONS else 0
        outcome_accounting = bool(isinstance(outcome, NativeRouteOutcome)
            and outcome.accounting_verified is True
            and type(outcome.input_count) is int and 0 <= outcome.input_count <= MAX_INPUTS
            and outcome.session_input_count == outcome.input_count
            and outcome.runtime_input_count == outcome.input_count)
        native_verified = bool(outcome_accounting and failure is None)
        if failure is not None:
            raw_result["status"] = "reconciliation_required" if calls or raw_result.get("effect_reconciliation_required") else "blocked"
        result = dict(raw_result)
        backend = result.get("backend_identity")
        backend_reset = backend.get("reset_id") if isinstance(backend, Mapping) else None
        result.update(
            flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            task_id=PRODUCT_ID, account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id, scheduler_reset_id=identity.reset_id,
            backend_reset_id=backend_reset, occurrence_key=occurrence_key, time_basis="utc",
            started_at_utc=started, completed_at_utc=completed,
            max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
            help_transport_calls=calls,
            native_execution_verified=native_verified, native_failure=failure,
            native_invocation_id=outcome.invocation_id if isinstance(outcome, NativeRouteOutcome) else None,
            native_session_directory=outcome.session_directory if isinstance(outcome, NativeRouteOutcome) else None,
            native_input_count=outcome.input_count if isinstance(outcome, NativeRouteOutcome) else 0,
            input_count=outcome.input_count if isinstance(outcome, NativeRouteOutcome) else 0,
            total_input_count=outcome.input_count if isinstance(outcome, NativeRouteOutcome) else 0,
            session_input_count=outcome.session_input_count if isinstance(outcome, NativeRouteOutcome) else 0,
            runtime_input_count=outcome.runtime_input_count if isinstance(outcome, NativeRouteOutcome) else 0,
            accounting_verified=bool(native_verified and result.get("accounting_verified") is True),
            effect_reconciliation_required=bool(result.get("effect_reconciliation_required") or (failure and calls)),
            identical_retry_denied=bool(result.get("identical_retry_denied") or (failure and calls)),
        )
        result["remaining_request_target"] = max(0,
            DAILY_REQUEST_LIMIT - int(result.get("confirmed_request_count", 0) or 0))
        return result
