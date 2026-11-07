"""Canonical service adapter for reset-bounded Alliance Tech donation execution."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import time
from typing import Any, Mapping
from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult


from tasks.donation_disabled import MAX_DONATIONS_PER_RESET
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .native_execution import NativeRouteBoundary, NativeRouteRequest, NativeRouteOutcome


from .recruitment import recruitment_reset
from .registry import (
    ALLIANCE_DONATION_FLOW_ID as FLOW_ID,
    ALLIANCE_DONATION_MAX_INPUTS as MAX_INPUTS,
    ALLIANCE_DONATION_PRODUCT_ID as PRODUCT_ID,
    ALLIANCE_DONATION_PRODUCT_REVISION as PRODUCT_REVISION,
    ALLIANCE_DONATION_PROFILE_ID as PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)

MAX_ACTIONS = MAX_DONATIONS_PER_RESET
RECHECK_SECONDS = 300.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _epoch(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"Alliance donation {name} must be a finite non-negative UTC epoch")
    return float(value)


def _identity_matches(identity: object, now: float, binding: Any) -> Any:
    sample = datetime.fromtimestamp(now, timezone.utc)
    if (not isinstance(identity, SchedulerIdentity)
            or identity.task_id != PRODUCT_ID
            or identity.reset_id != recruitment_reset(now)):
        raise ValueError("Alliance donation scheduler identity is not the current daily reset")
    scheduler_window = derive_static_utc_reset(sample)
    backend = derive_resource_runtime_identity(binding, sample)
    if (scheduler_window.reset_start_utc.date() != sample.date()
            or backend.reset_start_utc != scheduler_window.reset_start_text
            or backend.reset_deadline_utc != scheduler_window.reset_deadline_text
            or identity.reset_id != recruitment_reset(scheduler_window.evaluated_utc.timestamp())):
        raise ValueError("Alliance donation scheduler and fixed-backend reset windows differ")
    if identity.account_id != backend.account_id or identity.server_id != backend.server_id:
        raise ValueError("Alliance donation scheduler identity differs from the fixed backend account/server")
    return backend


def alliance_donation_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Admit only verified ten-action completion or an evidence-backed availability defer."""
    if not isinstance(result, Mapping):
        raise ValueError("Alliance donation result must be a mapping")
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Alliance donation outcome requires its exact scheduler identity")
    started = _epoch(started_at, "start")
    recorded_start = _epoch(result.get("started_at_utc"), "recorded start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if (recorded_start < started or completed < recorded_start
            or recruitment_reset(started) != identity.reset_id
            or recruitment_reset(completed) != identity.reset_id):
        raise ValueError("Alliance donation outcome crossed or mismatched its scheduler reset")
    if (
        (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or result.get("runtime_profile_id") != PROFILE_ID
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
        or result.get("scheduler_reset_id") != identity.reset_id
        or result.get("time_basis") != "utc"
        or not isinstance(result.get("occurrence_key"), str)
        or not result.get("occurrence_key")
        or result.get("native_failure") is not None
        or result.get("native_execution_verified") is not True
        or result.get("terminal_status") != "completed"
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
    ):
        raise ValueError("Alliance donation identity, accounting, effect, or Home proof is incomplete")
    inputs = tuple(result.get(key) for key in (
        "input_count", "total_input_count", "session_input_count", "runtime_input_count",
    ))
    if (any(type(value) is not int for value in inputs)
            or len(set(inputs)) != 1 or not 0 <= inputs[0] <= MAX_INPUTS
            or result.get("max_inputs") != MAX_INPUTS
            or result.get("max_actions") != MAX_ACTIONS):
        raise ValueError("Alliance donation input accounting does not match its fixed native budget")
    committed = result.get("committed_action_count")
    daily_count = result.get("daily_committed_action_count")
    calls = result.get("donation_transport_calls")
    if (type(committed) is not int or not 0 <= committed <= MAX_ACTIONS
            or type(daily_count) is not int or not committed <= daily_count <= MAX_ACTIONS
            or type(calls) is not int or calls != committed or calls > MAX_ACTIONS):
        raise ValueError("Alliance donation durable quota and transport accounting differ")
    refs = result.get("evidence_refs")
    terminal_hash = result.get("terminal_frame_sha256")
    if (not isinstance(refs, (tuple, list)) or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or not isinstance(terminal_hash, str) or _SHA256_RE.fullmatch(terminal_hash) is None):
        raise ValueError("Alliance donation terminal Home evidence is missing")
    backend = result.get("backend_identity")
    if not isinstance(backend, Mapping) or (
        backend.get("account_id") != identity.account_id
        or backend.get("server_id") != identity.server_id
        or not isinstance(backend.get("runtime_binding_digest"), str)
        or not backend.get("runtime_binding_digest")
    ):
        raise ValueError("Alliance donation fixed backend identity proof is incomplete")
    reset_start = datetime.fromtimestamp(completed, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    reset_deadline = reset_start + timedelta(days=1)
    expected_start = reset_start.isoformat().replace("+00:00", "Z")
    expected_deadline = reset_deadline.isoformat().replace("+00:00", "Z")
    if (backend.get("reset_start_utc") != expected_start
            or backend.get("reset_deadline_utc") != expected_deadline):
        raise ValueError("Alliance donation backend reset deadline is not the actual UTC reset")

    if result.get("status") == "complete_for_reset":
        if daily_count != MAX_ACTIONS:
            raise ValueError("Alliance donation reset completion lacks ten durable confirmed actions")
        return reset_deadline.timestamp()
    if result.get("status") != "deferred" or daily_count >= MAX_ACTIONS:
        raise ValueError("Alliance donation result is not a known complete or deferred state")
    evidence = result.get("availability_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("Alliance donation defer lacks current no-work evidence")
    reason = result.get("reason")
    attempts, capacity = evidence.get("available_attempts"), evidence.get("attempt_capacity")
    observed = _epoch(evidence.get("observed_at_utc"), "availability observation")
    source_hash = evidence.get("source_frame_sha256")
    if (not isinstance(evidence.get("tech_identity"), str) or not evidence["tech_identity"].strip()
            or evidence.get("game_day_id") != identity.reset_id
            or not isinstance(source_hash, str) or _SHA256_RE.fullmatch(source_hash) is None
            or not isinstance(evidence.get("evidence_ref"), str) or not evidence.get("evidence_ref")
            or evidence.get("reason") != reason
            or type(attempts) is not int or type(capacity) is not int or capacity != 20
            or observed < recorded_start or observed > completed):
        raise ValueError("Alliance donation availability evidence is stale or incomplete")
    next_due = _epoch(result.get("next_eligible_at"), "next eligibility")
    source = evidence.get("next_eligibility_source")
    if reason == "no_attempts":
        timer = evidence.get("next_attempt_available_in_seconds")
        if attempts != 0:
            raise ValueError("Alliance donation attempt defer has stored attempts")
        if source == "observed_attempt_timer":
            if type(timer) is not int or timer <= 0 or next_due != observed + timer:
                raise ValueError("Alliance donation timer deadline is not the observed recharge")
        elif source == "safe_attempt_recheck":
            if timer is not None or next_due != observed + RECHECK_SECONDS:
                raise ValueError("Alliance donation attempt recheck is not the explicit safe policy")
        else:
            raise ValueError("Alliance donation attempt defer has no permitted timer policy")
    elif reason == "insufficient_resource":
        balance, cost = evidence.get("resource_balance"), evidence.get("donation_amount")
        resource = evidence.get("resource_identity")
        if (attempts <= 0 or type(balance) is not int or type(cost) is not int
                or resource not in {"FOOD", "WOOD", "STEEL", "GAS"}
                or balance < 0 or cost <= 0 or balance >= cost
                or source != "safe_resource_recheck" or next_due != observed + RECHECK_SECONDS):
            raise ValueError("Alliance donation resource defer lacks a safe, exact recheck proof")
    else:
        raise ValueError("Alliance donation defer reason is not an observed availability stop")
    return min(max(completed, next_due), reset_deadline.timestamp())






class AllianceDonationRunner:
    """Device-free construction and reuse of one statically-bound native boundary."""

    def __init__(
        self,
        *,
        adb: str = str(BLUESTACKS_ADB),
        serial: str = BLUESTACKS_SERIAL,
        output_directory: Path,
        native: NativeRouteBoundary | None = None,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 1.0,
    ) -> None:
        if not callable(utc_clock) or not callable(monotonic_clock):
            raise ValueError("Alliance donation route clocks must be callable")
        if not math.isfinite(float(settle_seconds)) or settle_seconds < 0:
            raise ValueError("Alliance donation settle delay must be finite and non-negative")
        self.adb, self.serial = str(adb), str(serial)
        self.output_directory = Path(output_directory)
        self.native = native
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = float(settle_seconds)

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key) -> Mapping[str, Any]:
        try:
            started = _epoch(self.utc_clock(), "initial clock")
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": f"ALLIANCE_DONATION_PREFLIGHT:{type(exc).__name__}",
                "native_execution_verified": False,
                "native_failure": str(exc),
            }
        if self.native is None:
            return self._blocked(identity, previous_reset_id, occurrence_key, started,
                                 "ALLIANCE_DONATION_NATIVE_BINDING_REQUIRED")
        backend_identity = None
        result: dict[str, Any] = {}
        try:
            if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
                raise ValueError("Alliance donation scheduler identity task differs")
            binding = resource_fixed_runtime_binding()
            if (self.adb != str(BLUESTACKS_ADB) or self.serial != BLUESTACKS_SERIAL
                    or binding.runtime_profile_id != PROFILE_ID):
                raise ValueError("Alliance donation requires the fixed BlueStacks runtime profile")
            backend_identity = _identity_matches(identity, started, binding)
            if (not callable(checkpoint) or not isinstance(occurrence_key, str)
                    or not occurrence_key.strip()):
                raise ValueError("Alliance donation requires an exact service occurrence and checkpoint")
            if (getattr(runtime_input_lock, "owner", None) != "automation-service"
                    or not isinstance(getattr(runtime_input_lock, "invocation_id", None), str)
                    or not runtime_input_lock.invocation_id):
                raise ValueError("Alliance donation requires the canonical runtime owner")
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)

            def validate_identity() -> None:
                runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
                checkpoint()
                runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
                now = _epoch(self.utc_clock(), "identity checkpoint")
                current_backend = _identity_matches(identity, now, binding)
                fields = ("account_id", "server_id", "runtime_binding_digest", "reset_start_utc", "reset_deadline_utc")
                if any(getattr(current_backend, field) != getattr(backend_identity, field) for field in fields):
                    raise ValueError("Alliance donation fixed backend identity/reset window changed")

            request = NativeRouteRequest(
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                runtime_profile_id=PROFILE_ID,
                identity=identity,
                previous_reset_id=previous_reset_id,
                occurrence_key=occurrence_key,
                checkpoint=checkpoint,
                validate_identity=validate_identity,
                runtime_input_lock=runtime_input_lock,
                adb=self.adb,
                serial=self.serial,
                output_directory=self.output_directory,
                max_inputs=MAX_INPUTS,
                max_actions=MAX_ACTIONS,
                settle_seconds=self.settle_seconds,
                arguments={},
                utc_clock=self.utc_clock,
                monotonic_clock=self.monotonic_clock,
            )
            outcome = self.native.run(request)
            if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
                raise TypeError("Alliance donation native binding returned an invalid outcome")
            result = dict(outcome.partial_result or {})
            result.update(dict(outcome.native_result or {}))
            calls = result.get("donation_transport_calls", 0)
            committed = result.get("committed_action_count", 0)
            if not outcome.execution_verified:
                result["native_status"] = result.get("status")
                unknown = bool(result.get("effect_reconciliation_required")
                               or type(calls) is not int or calls > committed)
                result["status"] = "reconciliation_required" if unknown else "blocked"
                if type(calls) is int and calls > 0:
                    result["identical_retry_denied"] = True
                result.setdefault("reason", outcome.failure or "alliance_donation_native_execution_unverified")
            raw_accounting = result.get("accounting_verified", True)
            counts_valid = all(type(value) is int for value in (
                outcome.input_count, outcome.session_input_count, outcome.runtime_input_count,
            ))
            accounting = bool(
                outcome.accounting_verified is True and raw_accounting is True and counts_valid
                and outcome.input_count == outcome.session_input_count == outcome.runtime_input_count
                and 0 <= outcome.input_count <= MAX_INPUTS
            )
            if not accounting and type(calls) is int and calls > 0:
                result["effect_reconciliation_required"] = True
                result["identical_retry_denied"] = True
                result["status"] = "reconciliation_required"
            completed = _epoch(self.utc_clock(), "completion")
            result.setdefault("flow_id", FLOW_ID)
            result.setdefault("product_id", PRODUCT_ID)
            result.setdefault("product_revision", PRODUCT_REVISION)
            result.setdefault("task_id", PRODUCT_ID)
            result.setdefault("account_id", identity.account_id)
            result.setdefault("server_id", identity.server_id)
            result.setdefault("reset_id", identity.reset_id)
            result.setdefault("previous_reset_id", previous_reset_id)
            result.setdefault("occurrence_key", occurrence_key)
            result.setdefault("scheduler_reset_id", identity.reset_id)
            result.setdefault("time_basis", "utc")
            result.setdefault("runtime_profile_id", PROFILE_ID)
            result.setdefault("started_at_utc", started)
            result.setdefault("completed_at_utc", completed)
            result.setdefault("max_inputs", MAX_INPUTS)
            result.setdefault("max_actions", MAX_ACTIONS)
            result["input_count"] = outcome.input_count
            result.setdefault("total_input_count", outcome.input_count)
            result["session_input_count"] = outcome.session_input_count
            result["runtime_input_count"] = outcome.runtime_input_count
            result["accounting_verified"] = accounting
            result["native_execution_verified"] = outcome.execution_verified is True
            result.setdefault("native_failure", outcome.failure)
            result.setdefault("terminal_status", "completed" if result.get("terminal_home_verified") is True
                              else "evidence_required")
            raw_backend = result.get("backend_identity")
            if raw_backend is not None:
                result.setdefault("native_backend_identity", raw_backend)
            result["backend_identity"] = {
                "account_id": backend_identity.account_id,
                "server_id": backend_identity.server_id,
                "reset_start_utc": backend_identity.reset_start_utc,
                "reset_deadline_utc": backend_identity.reset_deadline_utc,
                "runtime_binding_digest": backend_identity.runtime_binding_digest,
            }
            return result
        except Exception as exc:
            partial = getattr(exc, "partial_result", None)
            if isinstance(partial, Mapping):
                result.update(partial)
            calls = result.get("donation_transport_calls", 0)
            unknown = bool(result.get("effect_reconciliation_required")
                           or type(calls) is not int or calls > 0)
            result.update(
                status="reconciliation_required" if unknown else "blocked",
                reason=f"ALLIANCE_DONATION_PREFLIGHT:{type(exc).__name__}",
                native_execution_verified=False,
                native_failure=str(exc),
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                account_id=getattr(identity, "account_id", None),
                server_id=getattr(identity, "server_id", None),
                reset_id=getattr(identity, "reset_id", None),
                previous_reset_id=previous_reset_id,
                occurrence_key=occurrence_key,
                scheduler_reset_id=getattr(identity, "reset_id", None),
                runtime_profile_id=PROFILE_ID,
                time_basis="utc",
                started_at_utc=started,
                completed_at_utc=started,
                max_inputs=MAX_INPUTS,
                max_actions=MAX_ACTIONS,
                terminal_status="evidence_required",
                terminal_home_verified=False,
                effect_reconciliation_required=unknown,
                identical_retry_denied=unknown,
            )
            if backend_identity is not None:
                result["backend_identity"] = {
                    "account_id": backend_identity.account_id,
                    "server_id": backend_identity.server_id,
                    "reset_start_utc": backend_identity.reset_start_utc,
                    "reset_deadline_utc": backend_identity.reset_deadline_utc,
                    "runtime_binding_digest": backend_identity.runtime_binding_digest,
                }
            return result

    @staticmethod
    def _blocked(identity, previous_reset_id, occurrence_key, started, reason):
        return {
            "status": "blocked", "reason": reason, "flow_id": FLOW_ID,
            "product_id": PRODUCT_ID, "product_revision": PRODUCT_REVISION,
            "task_id": PRODUCT_ID, "account_id": getattr(identity, "account_id", None),
            "server_id": getattr(identity, "server_id", None),
            "reset_id": getattr(identity, "reset_id", None),
            "scheduler_reset_id": getattr(identity, "reset_id", None),
            "previous_reset_id": previous_reset_id, "occurrence_key": occurrence_key,
            "runtime_profile_id": PROFILE_ID, "time_basis": "utc",
            "started_at_utc": started, "completed_at_utc": started,
            "max_inputs": MAX_INPUTS, "max_actions": MAX_ACTIONS,
            "input_count": 0, "total_input_count": 0,
            "session_input_count": 0, "runtime_input_count": 0,
            "accounting_verified": False, "native_execution_verified": False,
            "native_failure": reason, "terminal_status": "evidence_required",
            "terminal_home_verified": False, "effect_reconciliation_required": False,
            "identical_retry_denied": False, "donation_transport_calls": 0,
            "committed_action_count": 0, "daily_committed_action_count": 0,
        }


class AllianceDonationExecutionHandler:
    """Canonical dispatch handler; all execution is delegated to the injected runner."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Alliance Donation requires a typed registered dispatch snapshot")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Alliance Donation registration identity mismatch")
        if not callable(execute):
            raise TypeError("Alliance Donation executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Alliance Donation requires its matching route specification")
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
        return self.recover("ALLIANCE_DONATION_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("ALLIANCE_DONATION_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


__all__ = [
    "AllianceDonationExecutionHandler",
    "AllianceDonationRunner",
    "FLOW_ID",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "alliance_donation_next_due",
]
