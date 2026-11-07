"""Canonical Food Farm boost service over the injected native route boundary."""
from __future__ import annotations

import re
from datetime import datetime, timezone
import math
from pathlib import Path
import time
from typing import Any, Mapping

from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteRequest
from .registry import (
    FOOD_FARM_BOOST_FLOW_ID as FLOW_ID,
    FOOD_FARM_BOOST_MAX_INPUTS as MAX_INPUTS,
    FOOD_FARM_BOOST_PRODUCT_ID as PRODUCT_ID,
    FOOD_FARM_BOOST_PRODUCT_REVISION as PRODUCT_REVISION,
    FOOD_FARM_BOOST_PROFILE_ID as PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from .recruitment import recruitment_reset


MAX_ACTIONS = 2
RECHECK_SECONDS = 300.0
ONE_DAY_SECONDS = 86_400


def _epoch(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Food Farm {field} must be a finite UTC epoch")
    return float(value)


def _backend_window(identity: SchedulerIdentity, sampled_utc: float):
    """Bind scheduler and fixed-backend reset windows at the same UTC sample."""
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Food Farm scheduler identity has the wrong task")
    if recruitment_reset(sampled_utc) != identity.reset_id:
        raise ValueError("Food Farm scheduler identity is outside its current UTC reset")
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(
        binding, datetime.fromtimestamp(sampled_utc, timezone.utc)
    )
    window = derive_static_utc_reset(datetime.fromtimestamp(sampled_utc, timezone.utc))
    if (
        backend.reset_id != window.reset_identity_id
        or backend.reset_start_utc != window.reset_start_text
        or backend.reset_deadline_utc != window.reset_deadline_text
        or backend.account_id != identity.account_id
        or backend.server_id != identity.server_id
    ):
        raise ValueError("Food Farm scheduler and fixed-backend identities do not share one reset window")
    return backend, window, binding


def _backend_signature(backend, window) -> tuple[object, ...]:
    return (
        backend.account_id,
        backend.server_id,
        backend.runtime_binding_digest,
        backend.reset_id,
        backend.reset_start_utc,
        backend.reset_deadline_utc,
        window.reset_identity_id,
        window.reset_start_text,
        window.reset_deadline_text,
        backend.assurance.value,
    )


def _backend_result(backend) -> dict[str, str]:
    return {
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "runtime_binding_digest": backend.runtime_binding_digest,
        "reset_id": backend.reset_id,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
        "identity_assurance": backend.assurance.value,
    }


def _result_counts(result: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """Validate transport attempts and committed collection effects independently."""
    collection_calls = result.get("collection_transport_calls")
    boost_calls = result.get("boost_transport_calls")
    dispatch_count = result.get("food_farm_dispatch_count")
    collection_count = result.get("collection_count")
    if any(type(value) is not int or value < 0 for value in (
        collection_calls, boost_calls, dispatch_count, collection_count
    )):
        raise ValueError("Food Farm route action accounting is missing or invalid")
    collection_accounted = result.get("collection_effect_accounted")
    reconciliation_required = result.get("effect_reconciliation_required")
    if (
        collection_calls > 1 or boost_calls > 1
        or dispatch_count != collection_calls + boost_calls
        or collection_count > 1
        or (collection_count > 0 and collection_accounted is not True)
        or (
            collection_calls > 0 and collection_accounted is True
            and collection_count != 1
        )
        or (
            collection_calls > 0 and collection_accounted is not True
            and reconciliation_required is not True
        )
    ):
        raise ValueError("Food Farm collection/boost accounting is inconsistent")
    return collection_calls, boost_calls, dispatch_count, collection_count


def _attempted_dispatch_count(result: Mapping[str, Any]) -> int:
    """Retain every known transport attempt even when native accounting is malformed."""
    counts = [
        result.get("collection_transport_calls"),
        result.get("boost_transport_calls"),
    ]
    transport_total = sum(value for value in counts if type(value) is int and value >= 0)
    reported = result.get("food_farm_dispatch_count")
    return max(transport_total, reported if type(reported) is int and reported >= 0 else 0)


def _merge_partial_result(
    result: Mapping[str, Any], partial: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge lifecycle partials without dropping monotonic transport-attempt counts."""
    merged = dict(result)
    supplied = dict(partial) if isinstance(partial, Mapping) else {}
    merged.update(supplied)
    for field in (
        "collection_transport_calls", "boost_transport_calls", "collection_count",
        "food_farm_dispatch_count",
    ):
        values = [
            source.get(field) for source in (result, supplied)
            if type(source.get(field)) is int and source.get(field) >= 0
        ]
        if values:
            merged[field] = max(values)
    collection_calls = merged.get("collection_transport_calls")
    boost_calls = merged.get("boost_transport_calls")
    if type(collection_calls) is int and type(boost_calls) is int:
        merged["food_farm_dispatch_count"] = _attempted_dispatch_count(merged)
        collection_counts = [
            source.get("collection_count") for source in (result, supplied)
            if type(source.get("collection_count")) is int and source.get("collection_count") >= 0
        ]
        if collection_counts:
            merged["collection_count"] = max(collection_counts)
    for field in ("effect_reconciliation_required", "identical_retry_denied", "collection_effect_accounted"):
        merged[field] = any(
            source.get(field) is True for source in (result, supplied)
        )
    if _attempted_dispatch_count(merged):
        merged["identical_retry_denied"] = True
    return merged


def _utc_timestamp(value: object, field: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"Food Farm {field} must be an exact UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Food Farm {field} must be an exact UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"Food Farm {field} must be timezone-aware UTC")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError(f"Food Farm {field} is not canonical UTC")
    return parsed


def food_farm_boost_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Schedule only verified Home outcomes inside the same scheduler/backend reset."""
    if not isinstance(result, Mapping) or not isinstance(identity, SchedulerIdentity):
        raise ValueError("Food Farm due-time validation requires a result and SchedulerIdentity")
    if identity.task_id != PRODUCT_ID:
        raise ValueError("Food Farm due-time identity task differs")
    started = _epoch(started_at, "start time")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if (
        result.get("flow_id") != FLOW_ID
        or result.get("product_id") != PRODUCT_ID
        or result.get("product_revision") != PRODUCT_REVISION
        or result.get("task_id") != PRODUCT_ID
        or result.get("account_id") != identity.account_id
        or result.get("server_id") != identity.server_id
        or result.get("reset_id") != identity.reset_id
        or result.get("scheduler_reset_id") != identity.reset_id
        or result.get("occurrence_key") is None
        or result.get("time_basis") != "utc"
        or result.get("accounting_verified") is not True
        or result.get("terminal_home_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
        or result.get("status") not in {"completed", "already_active", "already_complete", "deferred"}
        or completed < started
    ):
        raise ValueError("Food Farm result is not verified for reset-bounded scheduling")
    occurrence_key = result.get("occurrence_key")
    if type(occurrence_key) is not str or not occurrence_key or occurrence_key != occurrence_key.strip():
        raise ValueError("Food Farm result lost its canonical service occurrence key")
    if not result.get("terminal_home_frame_sha256"):
        raise ValueError("Food Farm result has no verified terminal Home frame")
    collection_calls, boost_calls, dispatch_count, collection_count = _result_counts(result)
    if dispatch_count > MAX_ACTIONS:
        raise ValueError("Food Farm action count exceeds the route limit")
    if collection_calls and result.get("collection_effect_accounted") is not True:
        raise ValueError("Food Farm collection dispatch lacks its broad effect reconciliation")
    if result.get("status") == "completed" and (
        boost_calls != 1
        or result.get("boost_decision") != "owned_item"
        or result.get("boost_duration_seconds") != ONE_DAY_SECONDS
        or type(result.get("boost_timer_remaining_seconds")) is not int
        or not 0 < result.get("boost_timer_remaining_seconds") <= ONE_DAY_SECONDS
        or type(result.get("farm_identity")) is not str
        or re.fullmatch(r"home\.building\.farm\.\d{2}", result.get("farm_identity", "")) is None
        or result.get("boost_timer_farm_identity") != result.get("farm_identity")
    ):
        raise ValueError("Food Farm completion lacks its exact one-day same-Farm positive timer")
    if result.get("status") == "already_active" and (
        boost_calls != 0
        or type(result.get("active_remaining_seconds")) is not int
        or not 0 < result.get("active_remaining_seconds") <= ONE_DAY_SECONDS
        or type(result.get("farm_identity")) is not str
        or re.fullmatch(r"home\.building\.farm\.\d{2}", result.get("farm_identity", "")) is None
        or result.get("active_timer_farm_identity") != result.get("farm_identity")
    ):
        raise ValueError("Food Farm already-active result lacks a same-Farm one-day-range timer")
    if result.get("status") == "already_complete":
        farm_id = result.get("farm_identity")
        confirmation = result.get("prior_boost_confirmation")
        prior_active = result.get("prior_active_boost_observation")
        confirmed_action = bool(
            isinstance(confirmation, Mapping)
            and confirmation.get("confirmed") is True
            and isinstance(confirmation.get("frame_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", confirmation["frame_sha256"]) is not None
            and result.get("prior_boost_confirmation_farm_identity") == farm_id
            and result.get("prior_boost_confirmation_duration_seconds") == ONE_DAY_SECONDS
        )
        active_seconds = prior_active.get("remaining_seconds") if isinstance(prior_active, Mapping) else None
        confirmed_active = bool(
            isinstance(prior_active, Mapping)
            and prior_active.get("reset_id") == result.get("reset_id")
            and prior_active.get("farm_identity") == farm_id
            and type(active_seconds) is int and 0 < active_seconds <= ONE_DAY_SECONDS
            and isinstance(prior_active.get("source_frame_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", prior_active["source_frame_sha256"]) is not None
        )
        if (
            boost_calls != 0
            or type(farm_id) is not str
            or re.fullmatch(r"home\.building\.farm\.\d{2}", farm_id) is None
            or not (confirmed_action or confirmed_active)
        ):
            raise ValueError("Food Farm already-complete result lacks same-Farm positive boost proof")
    if result.get("status") == "deferred" and boost_calls != 0:
        raise ValueError("Food Farm deferred outcome cannot have a boost dispatch")
    backend_at_start, window_at_start, _binding = _backend_window(identity, started)
    backend_at_completion, window_at_completion, _binding = _backend_window(identity, completed)
    proof = result.get("backend_identity")
    if not isinstance(proof, Mapping):
        raise ValueError("Food Farm result is missing fixed-backend identity proof")
    expected_start = _backend_signature(backend_at_start, window_at_start)
    expected_completion = _backend_signature(backend_at_completion, window_at_completion)
    actual = (
        proof.get("account_id"), proof.get("server_id"), proof.get("runtime_binding_digest"),
        proof.get("reset_id"), proof.get("reset_start_utc"), proof.get("reset_deadline_utc"),
        result.get("backend_reset_identity_id"), result.get("backend_reset_start_utc"),
        result.get("backend_reset_deadline_utc"),
        proof.get("identity_assurance"),
    )
    if expected_start != expected_completion or actual != expected_completion:
        raise ValueError("Food Farm scheduler and backend reset proofs do not match")
    if result.get("runtime_profile_id") != PROFILE_ID:
        raise ValueError("Food Farm runtime profile differs")
    total_inputs = result.get("total_input_count")
    session_inputs = result.get("session_input_count")
    runtime_inputs = result.get("runtime_input_count")
    if (type(total_inputs) is not int or not 0 <= total_inputs <= MAX_INPUTS
            or session_inputs != total_inputs or runtime_inputs != total_inputs):
        raise ValueError("Food Farm native input accounting is invalid")
    if result.get("input_count") != total_inputs:
        raise ValueError("Food Farm total input accounting is inconsistent")
    deadline = _utc_timestamp(proof.get("reset_deadline_utc"), "backend reset deadline").timestamp()
    if result.get("status") == "deferred":
        return min(completed + RECHECK_SECONDS, deadline)
    return max(completed, deadline)


def _normalized_result(
    result: Mapping[str, Any], *, verified: bool, failure: str | None = None,
    next_due: float | None = None,
) -> NormalizedResult:
    status = result.get("status")
    try:
        _collection, _boost, dispatch_count, _collection_count = _result_counts(result)
    except ValueError:
        dispatch_count = _attempted_dispatch_count(result)
        verified = False
    reason = str(result.get("reason") or failure or "food_farm_native_result_unknown")
    if verified and status in {"completed", "already_active", "already_complete", "deferred"} and next_due is None:
        verified = False
        reason = "FOOD_FARM_NEXT_DUE_VALIDATION_FAILED"
    consequence = {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "food_farm_dispatch_count": dispatch_count,
        "collection_transport_calls": result.get("collection_transport_calls"),
        "boost_transport_calls": result.get("boost_transport_calls"),
        "collection_count": result.get("collection_count"),
        "collection_effect_accounted": result.get("collection_effect_accounted"),
        "effect_reconciliation_required": result.get("effect_reconciliation_required"),
        "identical_retry_denied": result.get("identical_retry_denied"),
        "terminal_home_verified": result.get("terminal_home_verified"),
        "native_result": dict(result),
    }
    evidence = tuple(
        value for value in (
            result.get("terminal_home_frame"),
            (result.get("collection_action") or {}).get("successor_frame")
            if isinstance(result.get("collection_action"), Mapping) else None,
            (result.get("boost_action") or {}).get("successor_frame")
            if isinstance(result.get("boost_action"), Mapping) else None,
        ) if isinstance(value, str) and value
    )
    if not verified or result.get("effect_reconciliation_required") is True:
        if dispatch_count or result.get("effect_reconciliation_required") is True:
            return NormalizedResult(
                NormalizedOutcome.RECONCILIATION_REQUIRED, reason,
                action_count=dispatch_count, verified=False,
                observed_progress={"status": status}, consequence=consequence,
                evidence_refs=evidence, unresolved_action=True,
            )
        return NormalizedResult(
            NormalizedOutcome.BLOCKED, reason, action_count=0, verified=False,
            observed_progress={"status": status}, consequence=consequence, evidence_refs=evidence,
        )
    if status == "completed":
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET, reason, action_count=dispatch_count,
            verified=True, next_eligible_at=next_due,
            observed_progress={"boost_decision": result.get("boost_decision")},
            consequence=consequence, evidence_refs=evidence,
        )
    if status in {"already_active", "already_complete"}:
        return NormalizedResult(
            NormalizedOutcome.ALREADY_COMPLETE, reason, action_count=dispatch_count,
            verified=True, next_eligible_at=next_due,
            observed_progress={"boost_decision": result.get("boost_decision")},
            consequence=consequence, evidence_refs=evidence,
        )
    if status == "deferred":
        return NormalizedResult(
            NormalizedOutcome.DEFERRED, reason, action_count=dispatch_count,
            verified=True, next_eligible_at=next_due,
            observed_progress={"boost_decision": result.get("boost_decision")},
            consequence=consequence, evidence_refs=evidence,
        )

    if (
        status == "blocked"
        and verified
        and result.get("effect_reconciliation_required") is False
        and result.get("identical_retry_denied") is False
    ):
        return NormalizedResult(
            NormalizedOutcome.BLOCKED, reason, action_count=dispatch_count,
            verified=True, observed_progress={"status": status},
            consequence=consequence, evidence_refs=evidence,
        )

    if dispatch_count:
        return NormalizedResult(
            NormalizedOutcome.RECONCILIATION_REQUIRED, reason,
            action_count=dispatch_count, verified=False,
            observed_progress={"status": status}, consequence=consequence,
            evidence_refs=evidence, unresolved_action=True,
        )
    return NormalizedResult(
        NormalizedOutcome.BLOCKED, reason, action_count=0,
        verified=True, observed_progress={"status": status},
        consequence=consequence, evidence_refs=evidence,
    )


class FoodFarmBoostExecutionHandler:
    """Thin registered handler; route authority remains with the injected native boundary."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute: Any, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Food Farm execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID
        ):
            raise ValueError("Food Farm registration identity mismatch")
        if not callable(execute):
            raise TypeError("Food Farm executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Food Farm requires its matching FlowSpec")
        self.snapshot, self._execute, self.flow_spec = snapshot, execute, flow_spec

    def describe(self):
        return canonical_entry(FLOW_ID).descriptor

    def eligibility(self, facts, perception=None):
        return bool(
            not facts.gate_failures(self.describe())
            and facts.accepted_product == PRODUCT_ID
            and facts.product_revision == PRODUCT_REVISION
            and facts.registration_status == "REGISTERED"
            and facts.scheduler_eligible is True
            and (perception is None or perception.profile_id == PROFILE_ID)
        )

    revalidate = eligibility

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)

    def plan(self, facts, perception=None):
        return self.recover("FOOD_FARM_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        if isinstance(plan, NormalizedResult) and plan.outcome in {
            NormalizedOutcome.RECONCILIATION_REQUIRED, NormalizedOutcome.UNRESOLVED,
        }:
            return plan
        return self.recover("FOOD_FARM_UNKNOWN_RESULT_REQUIRES_OPERATOR_RECONCILIATION")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class FoodFarmBoostRunner:
    """Device-free construction and reuse of the fixed native lifecycle binding."""

    def __init__(
        self, *, adb: str = str(BLUESTACKS_ADB), serial: str = BLUESTACKS_SERIAL,
        output_directory: Path, native: NativeRouteBoundary | None = None,
        utc_clock=time.time, monotonic_clock=time.monotonic, settle_seconds: float = 1.0,
    ) -> None:
        if not callable(utc_clock) or not callable(monotonic_clock):
            raise ValueError("Food Farm route clocks must be callable")
        if not math.isfinite(float(settle_seconds)) or settle_seconds < 0:
            raise ValueError("Food Farm settle delay must be finite and non-negative")
        self.adb, self.serial = str(adb), str(serial)
        self.output_directory = Path(output_directory)
        self.native = native
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = float(settle_seconds)

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key):
        if self.native is None:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED, "FOOD_FARM_NATIVE_BINDING_REQUIRED", verified=False
            )
        result: dict[str, Any] = {}
        try:
            if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
                raise ValueError("Food Farm requires its exact scheduler identity")
            binding = resource_fixed_runtime_binding()
            if self.serial != binding.serial or binding.runtime_profile_id != PROFILE_ID:
                raise ValueError("Food Farm requires the fixed BlueStacks runtime profile")
            sampled_now = _epoch(self.utc_clock(), "initial clock")
            backend_identity, reset_window, binding = _backend_window(identity, sampled_now)
            if not callable(checkpoint) or type(occurrence_key) is not str or not occurrence_key.strip():
                raise ValueError("Food Farm requires an exact service occurrence and checkpoint")
            assert_held = getattr(runtime_input_lock, "assert_held", None)
            if not callable(assert_held):
                raise ValueError("Food Farm requires the held runtime input lock")
            assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
            expected_backend = _backend_signature(backend_identity, reset_window)

            def validate_identity() -> None:
                checkpoint()
                current_now = _epoch(self.utc_clock(), "identity checkpoint")
                current_backend, current_window, current_binding = _backend_window(identity, current_now)
                if current_binding.binding_digest != binding.binding_digest:
                    raise ValueError("Food Farm fixed runtime binding changed")
                if _backend_signature(current_backend, current_window) != expected_backend:
                    raise ValueError("Food Farm fixed-backend account/server/reset window changed")

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
            native_outcome = self.native.run(request)
            result = dict(native_outcome.native_result)
            if native_outcome.flow_id != FLOW_ID:
                raise ValueError("Food Farm native boundary returned another route")
            if not native_outcome.execution_verified:
                result = _merge_partial_result(result, native_outcome.partial_result)
                result.setdefault(
                    "status",
                    "unresolved" if result.get("effect_reconciliation_required") else "blocked",
                )
                result.setdefault("reason", native_outcome.failure or "food_farm_native_execution_unverified")
            completed_at = _epoch(self.utc_clock(), "completion clock")
            completion_backend, completion_window, _ = _backend_window(identity, completed_at)
            if _backend_signature(completion_backend, completion_window) != expected_backend:
                raise ValueError("Food Farm completion crossed its verified reset window")
            result.update({
                "flow_id": FLOW_ID,
                "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION,
                "task_id": PRODUCT_ID,
                "profile_id": PROFILE_ID,
                "runtime_profile_id": PROFILE_ID,
                "account_id": identity.account_id,
                "server_id": identity.server_id,
                "reset_id": identity.reset_id,
                "scheduler_reset_id": identity.reset_id,
                "occurrence_key": occurrence_key,
                "time_basis": "utc",
                "completed_at_utc": completed_at,
                "backend_identity": _backend_result(backend_identity),
                "backend_reset_identity_id": reset_window.reset_identity_id,
                "backend_reset_start_utc": reset_window.reset_start_text,
                "backend_reset_deadline_utc": reset_window.reset_deadline_text,
                "total_input_count": native_outcome.input_count,
                "input_count": native_outcome.input_count,
                "session_input_count": native_outcome.session_input_count,
                "runtime_input_count": native_outcome.runtime_input_count,
                "accounting_verified": native_outcome.accounting_verified,
            })
            try:
                due = food_farm_boost_next_due(result, identity, sampled_now)
            except (TypeError, ValueError, OverflowError):
                due = None
            return _normalized_result(
                result, verified=native_outcome.execution_verified and native_outcome.accounting_verified,
                failure=native_outcome.failure, next_due=due,
            )
        except Exception as exc:
            partial = _merge_partial_result(result, getattr(exc, "partial_result", None))
            action_count = _attempted_dispatch_count(partial)
            unresolved = bool(action_count or partial.get("effect_reconciliation_required"))
            return NormalizedResult(
                NormalizedOutcome.RECONCILIATION_REQUIRED if unresolved else NormalizedOutcome.BLOCKED,
                f"FOOD_FARM_PREFLIGHT:{type(exc).__name__}",
                action_count=action_count,
                verified=False,
                observed_progress={"reason": str(exc)},
                consequence=partial,
                unresolved_action=unresolved,
            )


__all__ = [
    "FoodFarmBoostExecutionHandler",
    "FoodFarmBoostRunner",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "food_farm_boost_next_due",
]
