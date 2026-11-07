"""Canonical Recommended Research service runner over an injected native boundary."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import math
import re
from pathlib import Path
import time
from typing import Any, Mapping

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
from .recruitment import recruitment_reset
from .registry import (
    RECOMMENDED_RESEARCH_FLOW_ID as FLOW_ID,
    RECOMMENDED_RESEARCH_HANDLER_ID as HANDLER_ID,
    RECOMMENDED_RESEARCH_MAX_INPUTS as MAX_INPUTS,
    RECOMMENDED_RESEARCH_PRODUCT_ID as PRODUCT_ID,
    RECOMMENDED_RESEARCH_PRODUCT_REVISION as PRODUCT_REVISION,
    RECOMMENDED_RESEARCH_PROFILE_ID as PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)


MAX_ACTIONS = 1
OBSERVATION_INTERVAL_SECONDS = 300
_RESOURCES = ("food", "wood", "steel", "gas")


def _epoch(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Recommended Research {field} must be a finite UTC epoch")
    return float(value)


def _scheduler_backend(identity: SchedulerIdentity, sampled_utc: float):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Recommended Research requires its exact scheduler identity")
    if recruitment_reset(sampled_utc) != identity.reset_id:
        raise ValueError("Recommended Research scheduler identity is outside its current game-day reset")
    binding = resource_fixed_runtime_binding()
    at = datetime.fromtimestamp(sampled_utc, timezone.utc)
    backend = derive_resource_runtime_identity(binding, at)
    window = derive_static_utc_reset(at)
    if (
        backend.account_id != identity.account_id
        or backend.server_id != identity.server_id
        or backend.reset_id != window.reset_identity_id
        or backend.reset_start_utc != window.reset_start_text
        or backend.reset_deadline_utc != window.reset_deadline_text
    ):
        raise ValueError("Recommended Research scheduler and fixed-backend reset window differ")
    return backend, window, binding


def _backend_signature(backend: Any, window: Any) -> tuple[object, ...]:
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
    )


def _backend_mapping(backend: Any) -> dict[str, Any]:
    value = asdict(backend)
    value["assurance"] = backend.assurance.value
    value["evidence_refs"] = list(backend.evidence_refs)
    return value


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _terminal_home(result: Mapping[str, Any]) -> bool:
    frame = result.get("terminal_home_frame")
    if not isinstance(frame, Mapping):
        return False
    path = frame.get("frame_path")
    if (
        type(path) is not str
        or not path
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        or not _valid_sha256(frame.get("frame_sha256"))
    ):
        return False
    return _valid_sha256(result.get("terminal_home_frame_sha256")) and result["terminal_home_frame_sha256"] == frame["frame_sha256"]


def _research_counts(result: Mapping[str, Any]) -> tuple[int, int, int]:
    calls = result.get("research_transport_calls")
    committed = result.get("committed_action_count")
    actions = result.get("total_action_count")
    if any(type(value) is not int or value < 0 for value in (calls, committed, actions)):
        raise ValueError("Recommended Research action accounting is missing or malformed")
    if calls > 1 or committed > 1 or actions != calls or committed > calls:
        raise ValueError("Recommended Research action accounting exceeds its one-start bound")
    if committed and (calls != 1 or actions != 1):
        raise ValueError("Recommended Research committed effect lacks its one transport call")
    return calls, committed, actions


def _selection_constraints_verified(result: Mapping[str, Any]) -> bool:
    first = result.get("first_recommendation_identity")
    prerequisite_evidence = result.get("prerequisite_evidence")
    return bool(
        isinstance(first, str)
        and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", first, flags=re.ASCII)
        and type(result.get("recommendation_position")) is int
        and result["recommendation_position"] == 1
        and result.get("target_identity") == f"recommended-research:{first}:detail-research-button"
        and result.get("queue1_state") == "idle"
        and result.get("queue1_remaining_seconds") is None
        and result.get("requirements_scrolled") is True
        and result.get("research_start_visible") is True
        and result.get("control_class") == "RESEARCH_START"
        and result.get("queue2_activate_tapped") is False
        and result.get("prerequisites_known") is True
        and result.get("prerequisites_met") is True
        and isinstance(prerequisite_evidence, (list, tuple))
        and bool(prerequisite_evidence)
        and all(
            isinstance(item, str)
            and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item, flags=re.ASCII)
            and item.startswith("research-center")
            for item in prerequisite_evidence
        )
        and type(result.get("research_now_diamonds")) is int
        and result["research_now_diamonds"] > 0
        and result.get("research_now_target_identity") == "research-now-diamonds"
        and result.get("research_now_tapped") is False
        and result.get("overlay_state") in {"none", "none_observed"}
    )


def _semantic_start_verified(result: Mapping[str, Any]) -> bool:
    first = result.get("first_recommendation_identity")
    costs = result.get("exact_resource_costs")
    before = result.get("exact_resource_prebalances")
    after = result.get("exact_resource_balances")
    return bool(
        _selection_constraints_verified(result)
        and result.get("start_semantically_verified") is True
        and result.get("research_transport_calls") == 1
        and result.get("active_technology") == first
        and type(result.get("remaining_seconds")) is int
        and result["remaining_seconds"] > 0
        and type(result.get("research_duration_seconds")) is int
        and result["research_duration_seconds"] >= result["remaining_seconds"]
        and isinstance(costs, Mapping)
        and isinstance(before, Mapping)
        and isinstance(after, Mapping)
        and set(costs) == set(_RESOURCES)
        and set(before) == set(_RESOURCES)
        and set(after) == set(_RESOURCES)
        and all(
            type(costs[key]) is int
            and costs[key] >= 0
            and type(before[key]) is int
            and before[key] >= 0
            and type(after[key]) is int
            and after[key] >= 0
            and before[key] - after[key] == costs[key]
            for key in _RESOURCES
        )
    )


def recommended_research_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Admit only identity-bound timer completion or exact normal deferral."""
    if not isinstance(result, Mapping) or not isinstance(identity, SchedulerIdentity):
        raise ValueError("Recommended Research due-time validation requires a result and SchedulerIdentity")
    started = _epoch(started_at, "start time")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    status = result.get("status")
    identical_retry_denied = result.get("identical_retry_denied")
    if (
        identity.task_id != PRODUCT_ID
        or recruitment_reset(started) != identity.reset_id
        or recruitment_reset(completed) != identity.reset_id
        or completed < started
        or (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"), result.get("scheduler_reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id, identity.reset_id)
        or result.get("runtime_profile_id") != PROFILE_ID
        or result.get("time_basis") != "utc"
        or result.get("accounting_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or type(identical_retry_denied) is not bool
        or (status in {"completed", "already_complete"} and identical_retry_denied is not True)
        or (status == "deferred" and identical_retry_denied is not False)
        or result.get("terminal_home_verified") is not True
        or not _terminal_home(result)
    ):
        raise ValueError("Recommended Research result identity, accounting, effect, or terminal Home is unverified")
    occurrence = result.get("occurrence_key")
    if type(occurrence) is not str or not occurrence or occurrence != occurrence.strip():
        raise ValueError("Recommended Research result lost its canonical scheduler occurrence")
    calls, committed, actions = _research_counts(result)
    inputs = result.get("total_input_count")
    if (
        type(inputs) is not int
        or not 0 <= inputs <= MAX_INPUTS
        or result.get("input_count") != inputs
        or result.get("session_input_count") != inputs
        or result.get("runtime_input_count") != inputs
        or actions > inputs
    ):
        raise ValueError("Recommended Research native input/action accounting is invalid")
    backend, window, _binding = _scheduler_backend(identity, completed)
    proof = result.get("backend_identity")
    if not isinstance(proof, Mapping) or dict(proof) != _backend_mapping(backend):
        raise ValueError("Recommended Research fixed-backend identity evidence is not exact")
    if (
        result.get("backend_reset_identity_id") != window.reset_identity_id
        or result.get("backend_reset_start_utc") != window.reset_start_text
        or result.get("backend_reset_deadline_utc") != window.reset_deadline_text
    ):
        raise ValueError("Recommended Research backend reset window evidence differs")

    if status == "already_complete":
        if calls or committed or actions or result.get("already_confirmed") is not True:
            raise ValueError("Recommended Research already-complete result lacks its confirmed reset-scoped action")
        deadline = datetime.fromisoformat(window.reset_deadline_text.replace("Z", "+00:00"))
        if deadline.tzinfo is None or deadline.utcoffset() != timezone.utc.utcoffset(deadline):
            raise ValueError("Recommended Research reset deadline is not canonical UTC")
        return max(completed, deadline.timestamp())

    if status == "completed":
        first = result.get("first_recommendation_identity")
        if (
            calls != 1
            or committed != 1
            or actions != 1
            or result.get("completed") is not True
            or not _semantic_start_verified(result)
            or not first
            or result.get("active_technology") != first
            or type(result.get("remaining_seconds")) is not int
            or result["remaining_seconds"] <= 0
            or type(result.get("research_duration_seconds")) is not int
            or result["research_duration_seconds"] < result["remaining_seconds"]
            or result.get("target_identity") != f"recommended-research:{first}:detail-research-button"
            or not isinstance(result.get("exact_resource_costs"), Mapping)
            or not isinstance(result.get("exact_resource_prebalances"), Mapping)
            or not isinstance(result.get("exact_resource_balances"), Mapping)
            or set(result["exact_resource_costs"]) != set(_RESOURCES)
            or set(result["exact_resource_prebalances"]) != set(_RESOURCES)
            or set(result["exact_resource_balances"]) != set(_RESOURCES)
            or any(type(result["exact_resource_costs"][key]) is not int or result["exact_resource_costs"][key] < 0 for key in _RESOURCES)
            or any(type(result["exact_resource_prebalances"][key]) is not int or result["exact_resource_prebalances"][key] < 0 for key in _RESOURCES)
            or any(type(result["exact_resource_balances"][key]) is not int or result["exact_resource_balances"][key] < 0 for key in _RESOURCES)
            or any(
                result["exact_resource_prebalances"][key] - result["exact_resource_balances"][key]
                != result["exact_resource_costs"][key]
                for key in _RESOURCES
            )
        ):
            raise ValueError("Recommended Research completion lacks exact target, duration, timer, costs, or paired balances")
        return completed + result["remaining_seconds"]

    if status != "deferred" or calls or committed or actions:
        raise ValueError("Recommended Research outcome is not a timer-backed completion or normal defer")
    due = _epoch(result.get("next_due_utc"), "next observation")
    if result.get("queue1_state") == "busy":
        remaining = result.get("queue1_remaining_seconds")
        if type(remaining) is not int or remaining <= 0 or due != completed + remaining:
            raise ValueError("Recommended Research busy-queue defer lacks its exact observed timer")
        return due
    interval = result.get("observation_interval_seconds")
    shortages = result.get("shortages")
    if (
        type(interval) is not int
        or interval != OBSERVATION_INTERVAL_SECONDS
        or due != completed + OBSERVATION_INTERVAL_SECONDS
        or not isinstance(shortages, list)
        or not shortages
        or any(
            not isinstance(row, Mapping)
            or row.get("resource") not in _RESOURCES
            or type(row.get("shortage")) is not int
            or row["shortage"] <= 0
            for row in shortages
        )
        or len({row["resource"] for row in shortages}) != len(shortages)
        or not _selection_constraints_verified(result)
    ):
        raise ValueError("Recommended Research shortage defer lacks exact target, prerequisite, and configured observation evidence")
    costs = result.get("exact_resource_costs")
    balances = result.get("exact_resource_balances")
    if (
        not isinstance(costs, Mapping)
        or not isinstance(balances, Mapping)
        or set(costs) != set(_RESOURCES)
        or set(balances) != set(_RESOURCES)
        or any(type(costs[key]) is not int or costs[key] < 0 for key in _RESOURCES)
        or any(type(balances[key]) is not int or balances[key] < 0 for key in _RESOURCES)
    ):
        raise ValueError("Recommended Research shortage rows do not reconcile with all four exact resource rows")
    exact_shortages = [
        {"resource": key, "shortage": costs[key] - balances[key]}
        for key in _RESOURCES
        if costs[key] > balances[key]
    ]
    if not exact_shortages or shortages != exact_shortages:
        raise ValueError("Recommended Research shortage list is not the complete exact ordinary-resource shortage")
    return due


def _normalized_result(
    result: Mapping[str, Any], *, verified: bool, failure: str | None, next_due: float | None
) -> NormalizedResult:
    counts_valid = True
    try:
        calls, committed, actions = _research_counts(result)
    except ValueError:
        calls = committed = actions = 0
        counts_valid = False
        verified = False
    status = result.get("status")
    reason = str(result.get("reason") or failure or "recommended_research_native_result_unknown")
    evidence = tuple(
        value for value in (
            result.get("terminal_home_frame"),
            (result.get("start_action") or {}).get("source_frame")
            if isinstance(result.get("start_action"), Mapping) else None,
            (result.get("start_action") or {}).get("successor_frame")
            if isinstance(result.get("start_action"), Mapping) else None,
        ) if isinstance(value, (str, Mapping)) and value
    )
    consequence = {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "research_transport_calls": calls,
        "committed_action_count": committed,
        "total_action_count": actions,
        "effect_reconciliation_required": result.get("effect_reconciliation_required"),
        "identical_retry_denied": result.get("identical_retry_denied"),
        "terminal_home_verified": result.get("terminal_home_verified"),
        "native_result": dict(result),
    }

    if not counts_valid:
        return NormalizedResult(
            NormalizedOutcome.RECONCILIATION_REQUIRED,
            reason,
            action_count=1,
            verified=False,
            observed_progress={"status": status},
            consequence=consequence,
            evidence_refs=evidence,
            unresolved_action=True,
        )
    if not verified or result.get("effect_reconciliation_required") is True:
        if calls or result.get("effect_reconciliation_required") is True:
            return NormalizedResult(
                NormalizedOutcome.RECONCILIATION_REQUIRED,
                reason,
                action_count=max(calls, actions),
                verified=False,
                observed_progress={"status": status},
                consequence=consequence,
                evidence_refs=evidence,
                unresolved_action=True,
            )
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            reason,
            action_count=0,
            verified=False,
            observed_progress={"status": status},
            consequence=consequence,
            evidence_refs=evidence,
        )
    if status == "completed":
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            reason,
            action_count=actions,
            verified=True,
            next_eligible_at=next_due,
            observed_progress={"active_technology": result.get("active_technology")},
            consequence=consequence,
            evidence_refs=evidence,
        )
    if status == "deferred":
        return NormalizedResult(
            NormalizedOutcome.DEFERRED,
            reason,
            action_count=0,
            verified=True,
            next_eligible_at=next_due,
            observed_progress={"shortages": result.get("shortages", []), "queue1_state": result.get("queue1_state")},
            consequence=consequence,
            evidence_refs=evidence,
        )
    if status == "already_complete":
        return NormalizedResult(
            NormalizedOutcome.ALREADY_COMPLETE,
            reason,
            action_count=0,
            verified=True,
            next_eligible_at=next_due,
            observed_progress={"already_confirmed": result.get("already_confirmed") is True},
            consequence=consequence,
            evidence_refs=evidence,
        )
    return NormalizedResult(
        NormalizedOutcome.BLOCKED,
        reason,
        action_count=actions,
        verified=True,
        observed_progress={"status": status},
        consequence=consequence,
        evidence_refs=evidence,
    )


class RecommendedResearchExecutionHandler:
    """Canonical registered handler; the injected native route owns gameplay."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute: Any, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Recommended Research execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID
        ):
            raise ValueError("Recommended Research registration identity mismatch")
        if not callable(execute):
            raise TypeError("Recommended Research executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Recommended Research requires its matching FlowSpec")
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
        return self.recover("RECOMMENDED_RESEARCH_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        if isinstance(plan, NormalizedResult) and plan.outcome in {
            NormalizedOutcome.RECONCILIATION_REQUIRED,
            NormalizedOutcome.UNRESOLVED,
        }:
            return plan
        return self.recover("RECOMMENDED_RESEARCH_UNKNOWN_RESULT_REQUIRES_RECONCILIATION")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class RecommendedResearchRunner:
    """Device-free service runner for one fixed native boundary and held owner lease."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None,
        output_directory: Path,
        adb: str = str(BLUESTACKS_ADB),
        serial: str = BLUESTACKS_SERIAL,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 1.0,
    ) -> None:
        if not callable(utc_clock) or not callable(monotonic_clock):
            raise ValueError("Recommended Research clocks must be callable")
        if (
            not isinstance(settle_seconds, (int, float))
            or isinstance(settle_seconds, bool)
            or not math.isfinite(float(settle_seconds))
            or settle_seconds < 0
        ):
            raise ValueError("Recommended Research settle delay must be finite and non-negative")
        self.native = native
        self.output_directory = Path(output_directory)
        self.adb, self.serial = str(adb), str(serial)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = float(settle_seconds)

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key):
        if self.native is None:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "RECOMMENDED_RESEARCH_NATIVE_BINDING_REQUIRED",
                verified=False,
            )
        native_result: dict[str, Any] = {}
        try:
            if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
                raise ValueError("Recommended Research requires its exact scheduler identity")
            if self.serial != BLUESTACKS_SERIAL:
                raise ValueError("Recommended Research requires the fixed BlueStacks serial")
            if not callable(checkpoint) or type(occurrence_key) is not str or not occurrence_key.strip():
                raise ValueError("Recommended Research requires an exact occurrence and checkpoint")
            initial_now = _epoch(self.utc_clock(), "initial clock")
            backend, window, binding = _scheduler_backend(identity, initial_now)
            if binding.runtime_profile_id != PROFILE_ID:
                raise ValueError("Recommended Research fixed runtime profile differs")
            assert_held = getattr(runtime_input_lock, "assert_held", None)
            owner = getattr(runtime_input_lock, "owner", None)
            invocation_id = getattr(runtime_input_lock, "invocation_id", None)
            if not callable(assert_held) or not owner or not invocation_id:
                raise ValueError("Recommended Research requires the held runtime input lock")
            assert_held(owner, invocation_id)
            expected_backend = _backend_signature(backend, window)

            def validate_identity() -> None:
                checkpoint()
                current_now = _epoch(self.utc_clock(), "identity checkpoint")
                current_backend, current_window, current_binding = _scheduler_backend(identity, current_now)
                if current_binding.binding_digest != binding.binding_digest:
                    raise ValueError("Recommended Research fixed runtime binding changed")
                if _backend_signature(current_backend, current_window) != expected_backend:
                    raise ValueError("Recommended Research account/server/reset window changed")

            checkpoint()
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
            input_accounting_verified = bool(
                outcome.accounting_verified is True
                and type(outcome.input_count) is int
                and 0 <= outcome.input_count <= MAX_INPUTS
                and type(outcome.session_input_count) is int
                and outcome.session_input_count == outcome.input_count
                and type(outcome.runtime_input_count) is int
                and outcome.runtime_input_count == outcome.input_count
            )
            native_result = dict(outcome.native_result)
            if outcome.flow_id != FLOW_ID:
                raise ValueError("Recommended Research native boundary returned another flow")
            if not outcome.execution_verified:
                native_result = dict(outcome.partial_result or native_result)
                native_result.setdefault(
                    "status",
                    "unresolved" if native_result.get("effect_reconciliation_required") else "blocked",
                )
                native_result.setdefault("reason", outcome.failure or "recommended_research_native_execution_unverified")
            completed_at = _epoch(self.utc_clock(), "completion clock")
            completed_backend, completed_window, completed_binding = _scheduler_backend(identity, completed_at)
            if completed_binding.binding_digest != binding.binding_digest or _backend_signature(completed_backend, completed_window) != expected_backend:
                raise ValueError("Recommended Research backend identity changed during the claimed run")
            calls, reported_committed, _reported_actions = _research_counts(native_result)
            status = native_result.get("status")
            if status not in {"completed", "deferred", "already_complete", "blocked", "unresolved"}:
                possible_effect = bool(calls or native_result.get("effect_reconciliation_required") is True)
                status = "unresolved" if possible_effect else "blocked"
                native_result.update(
                    status=status,
                    effect_reconciliation_required=possible_effect,
                    identical_retry_denied=possible_effect,
                )
                input_accounting_verified = False
            elif status == "unresolved":
                native_result["effect_reconciliation_required"] = True
                native_result["identical_retry_denied"] = True
            semantic_commit = calls == 1 and _semantic_start_verified(native_result)
            committed = int(semantic_commit)
            if reported_committed != committed:
                native_result["native_reported_committed_action_count"] = reported_committed
                input_accounting_verified = False
            action_count = calls
            if status == "completed" and (
                calls != 1
                or committed != 1
                or not outcome.execution_verified
                or not input_accounting_verified
            ):
                status = "unresolved"
                native_result["status"] = status
                native_result["effect_reconciliation_required"] = True
                native_result["identical_retry_denied"] = True
            result = {
                **native_result,
                "flow_id": FLOW_ID,
                "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION,
                "task_id": PRODUCT_ID,
                "handler_id": HANDLER_ID,
                "profile_id": PROFILE_ID,
                "runtime_profile_id": PROFILE_ID,
                "account_id": identity.account_id,
                "server_id": identity.server_id,
                "reset_id": identity.reset_id,
                "scheduler_reset_id": identity.reset_id,
                "previous_reset_id": previous_reset_id,
                "occurrence_key": occurrence_key,
                "time_basis": "utc",
                "completed_at_utc": completed_at,
                "backend_identity": _backend_mapping(completed_backend),
                "backend_reset_identity_id": completed_window.reset_identity_id,
                "backend_reset_start_utc": completed_window.reset_start_text,
                "backend_reset_deadline_utc": completed_window.reset_deadline_text,
                "total_input_count": outcome.input_count,
                "input_count": outcome.input_count,
                "session_input_count": outcome.session_input_count,
                "runtime_input_count": outcome.runtime_input_count,
                "accounting_verified": input_accounting_verified,
                "research_transport_calls": calls,
                "committed_action_count": committed,
                "total_action_count": action_count,
                "effect_reconciliation_required": bool(
                    native_result.get("effect_reconciliation_required") is True
                    or status == "unresolved"
                    or (calls and not committed)
                ),
                "identical_retry_denied": bool(
                    calls
                    or native_result.get("identical_retry_denied") is True
                    or status in {"already_complete", "unresolved"}
                ),
            }
            if result["effect_reconciliation_required"]:
                result["identical_retry_denied"] = True
            if status == "completed":
                remaining = result.get("remaining_seconds")
                if type(remaining) is int and remaining > 0:
                    result["next_due_utc"] = completed_at + remaining
            elif status == "deferred":
                if result.get("queue1_state") == "busy" and type(result.get("queue1_remaining_seconds")) is int:
                    result["next_due_utc"] = completed_at + result["queue1_remaining_seconds"]
                elif result.get("observation_interval_seconds") == OBSERVATION_INTERVAL_SECONDS:
                    result["next_due_utc"] = completed_at + OBSERVATION_INTERVAL_SECONDS
            next_due = None
            try:
                next_due = recommended_research_next_due(result, identity, initial_now)
            except (TypeError, ValueError, OverflowError):
                pass
            if status in {"completed", "deferred", "already_complete"} and next_due is None:
                if calls:
                    result.update(status="unresolved", effect_reconciliation_required=True, identical_retry_denied=True)
                    result["total_action_count"] = calls
                else:
                    result["status"] = status = "blocked"
                input_accounting_verified = False
            return _normalized_result(
                result,
                verified=outcome.execution_verified and input_accounting_verified and next_due is not None
                if status in {"completed", "deferred", "already_complete"}
                else outcome.execution_verified and input_accounting_verified,
                failure=outcome.failure,
                next_due=next_due,
            )
        except Exception as exc:
            raw_calls = native_result.get("research_transport_calls", 0)
            counts_valid = True
            try:
                calls, _committed, _actions = _research_counts(native_result)
            except ValueError:
                calls = raw_calls if type(raw_calls) is int else 0
                counts_valid = False
            observed_outcome = locals().get("outcome")
            input_counts = tuple(
                getattr(observed_outcome, field, None)
                for field in ("input_count", "session_input_count", "runtime_input_count")
            ) if observed_outcome is not None else ()
            input_attempt_possible = any(type(value) is not int or value > 0 for value in input_counts)
            unresolved = bool(
                (counts_valid and calls > 0)
                or (not counts_valid and bool(native_result))
                or input_attempt_possible
                or native_result.get("effect_reconciliation_required") is True
            )
            return NormalizedResult(
                NormalizedOutcome.RECONCILIATION_REQUIRED if unresolved else NormalizedOutcome.BLOCKED,
                "RECOMMENDED_RESEARCH_RUNNER_FAILED:" + type(exc).__name__,
                action_count=1 if unresolved else 0,
                verified=False,
                observed_progress={
                    "error": str(exc),
                    "status": native_result.get("status"),
                    "native_input_accounting": input_counts,
                },
                consequence={"native_result": native_result},
                unresolved_action=unresolved,
            )


__all__ = [
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "OBSERVATION_INTERVAL_SECONDS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "RecommendedResearchExecutionHandler",
    "RecommendedResearchRunner",
    "recommended_research_next_due",
]
