"""Canonical service adapter for zero-resource Nano Material Production."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import time
from types import MappingProxyType
from typing import Mapping

from tasks.nano_material_production import (
    NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
    NANO_MATERIAL_PRODUCTION_TARGET,
)
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
from .registry import (
    NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
    NANO_MATERIAL_PRODUCTION_PRODUCT_ID,
    NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from .native_execution import NativeRouteBoundary, NativeRouteRequest
from .recruitment import recruitment_reset


FLOW_ID = NANO_MATERIAL_PRODUCTION_FLOW_ID
PRODUCT_ID = NANO_MATERIAL_PRODUCTION_PRODUCT_ID
PRODUCT_REVISION = NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = NANO_MATERIAL_PRODUCTION_MAX_INPUTS
MAX_ACTIONS = 2


class NanoMaterialProductionExecutionHandler:
    """Use canonical scheduler admission and delegate the active run to its service."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Nano Material Production requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Nano Material Production registration identity mismatch")
        if not callable(execute):
            raise TypeError("Nano Material Production executor must be callable")
        if flow_spec is not None:
            if not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID:
                raise ValueError("Nano Material Production requires its matching flow spec")
            self.flow_spec = flow_spec
        self.snapshot, self._execute = snapshot, execute

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
        return self.recover("NANO_MATERIAL_PRODUCTION_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover(
            "NANO_MATERIAL_PRODUCTION_UNKNOWN_RESULT"
        )

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}




class NanoMaterialProductionRunnerError(RuntimeError):
    def __init__(self, reason: str, *, partial_result: Mapping[str, object]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Nano Material Production {name} must be a finite UTC epoch")
    return float(value)


def _fixed_identity(identity, *, now: float, serial: str):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Nano Material Production requires its canonical scheduler identity")
    sample = datetime.fromtimestamp(now, timezone.utc)
    scheduler_reset = recruitment_reset(now)
    window = derive_static_utc_reset(sample)
    binding = resource_fixed_runtime_binding()
    if serial != BLUESTACKS_SERIAL or binding.serial != serial:
        raise ValueError("Nano Material Production requires the fixed BlueStacks runtime")
    backend = derive_resource_runtime_identity(binding, sample)
    if (
        identity.reset_id != scheduler_reset
        or (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id)
        or (backend.reset_start_utc, backend.reset_deadline_utc)
        != (window.reset_start_text, window.reset_deadline_text)
    ):
        raise ValueError("Nano Material Production scheduler/backend reset-window identity mismatch")
    return backend


def _backend_identity_mapping(backend) -> dict[str, object]:
    return {
        "runtime_scope": backend.runtime_scope,
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "backend_reset_id": backend.reset_id,
        "assurance": backend.assurance.value,
        "runtime_binding_digest": backend.runtime_binding_digest,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
        "evidence_refs": list(backend.evidence_refs),
    }

def _verify_backend_identity(value, identity, completed: float) -> None:
    expected = _backend_identity_mapping(
        _fixed_identity(identity, now=completed, serial=BLUESTACKS_SERIAL)
    )
    if value != expected:
        raise ValueError("Nano Material Production backend identity proof is inconsistent")


def _required_route_counts(result: Mapping[str, object]) -> tuple[int, int]:
    calls = result.get("production_transport_calls")
    committed = result.get("committed_action_count")
    if (
        type(calls) is not int
        or not 0 <= calls <= MAX_ACTIONS
        or type(committed) is not int
        or committed != calls
    ):
        raise ValueError("Nano Material Production action accounting is not exact")
    return calls, committed
def _require_terminal_home(result: Mapping[str, object]) -> None:
    proof = result.get("terminal_home_frame")
    if (
        result.get("terminal_home_state") != "HOME_BASE"
        or result.get("terminal_home_recognized") is not True
        or not isinstance(proof, Mapping)
        or not isinstance(proof.get("frame_path"), str)
        or not proof.get("frame_path")
        or not isinstance(proof.get("frame_sha256"), str)
        or len(proof["frame_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in proof["frame_sha256"])
    ):
        raise ValueError("Nano Material Production requires current canonical Home frame evidence")


def _require_production_frame(result: Mapping[str, object]) -> None:
    frame = result.get("production_state_frame")
    digest = result.get("production_state_observation_sha256")
    if (
        not isinstance(frame, Mapping)
        or type(frame.get("frame_path")) is not str
        or not frame.get("frame_path")
        or type(frame.get("frame_sha256")) is not str
        or len(frame["frame_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in frame["frame_sha256"])
        or digest != frame.get("frame_sha256")
        or type(frame.get("observed_utc")) is not str
        or not frame.get("observed_utc")
        or type(frame.get("capture_ordinal")) is not int
        or frame["capture_ordinal"] < 1
    ):
        raise ValueError("Nano Material Production requires retained production frame evidence")


def _require_effect_evidence(result: Mapping[str, object]) -> None:
    if result.get("zero_resource_cost_confirmed") is not True:
        raise ValueError("Nano Material Production performed free effects are unproven")
    evidence = result.get("last_action_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("Nano Material Production action evidence is missing")
    for phase in ("before", "after"):
        frame = evidence.get(phase)
        _require_production_frame({
            "production_state_frame": frame,
            "production_state_observation_sha256": frame.get("frame_sha256") if isinstance(frame, Mapping) else None,
        })
    before, after = evidence["before"], evidence["after"]
    if before["frame_sha256"] == after["frame_sha256"] or after["capture_ordinal"] <= before["capture_ordinal"]:
        raise ValueError("Nano Material Production effect successor is not distinct and ordered")

class NanoMaterialProductionRunner:
    """Device-free construction over an injected, fixed native route binding."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None = None,
        adb=BLUESTACKS_ADB,
        serial=BLUESTACKS_SERIAL,
        output_directory: Path,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 1.0,
    ) -> None:
        self.native = native
        self.adb, self.serial = str(adb), str(serial)
        if native is not None and getattr(native, "flow_id", None) != FLOW_ID:
            raise ValueError("Nano Material Production native binding identity mismatch")
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        if (
            type(settle_seconds) not in (int, float)
            or not math.isfinite(settle_seconds)
            or settle_seconds < 0
        ):
            raise ValueError("Nano Material Production settle delay must be finite and non-negative")
        self.settle_seconds = float(settle_seconds)

    def __call__(
        self,
        identity,
        previous_reset_id,
        checkpoint,
        *,
        runtime_input_lock,
        occurrence_key,
    ):
        if self.native is None:
            raise NanoMaterialProductionRunnerError(
                "NANO_MATERIAL_PRODUCTION_NATIVE_BINDING_REQUIRED",
                partial_result={
                    "status": "blocked",
                    "production_transport_calls": 0,
                    "committed_action_count": 0,
                    "effect_reconciliation_required": False,
                    "identical_retry_denied": False,
                },
            )
        started = _epoch(self.utc_clock(), "start time")
        backend_identity = {}
        outcome = None
        native_result = {}

        def validate_identity() -> None:
            backend = _fixed_identity(
                identity,
                now=_epoch(self.utc_clock(), "identity clock"),
                serial=self.serial,
            )
            backend_identity.clear()
            backend_identity.update(_backend_identity_mapping(backend))

        try:
            validate_identity()
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
                arguments=MappingProxyType({}),
                utc_clock=self.utc_clock,
                monotonic_clock=self.monotonic_clock,
            )
            outcome = self.native.run(request)
            native_result = dict(outcome.native_result)
            if outcome.flow_id != FLOW_ID:
                raise ValueError("Nano Material Production native outcome flow mismatch")
            if outcome.failure is not None or outcome.accounting_verified is not True:
                partial = dict(native_result)
                partial.update(dict(outcome.partial_result or {}))
                raw_calls = partial.get("production_transport_calls")
                count_known = type(raw_calls) is int and raw_calls >= 0
                calls = raw_calls if count_known else 0
                unresolved = bool(
                    (calls != partial.get("committed_action_count"))
                    or not count_known
                    or not outcome.accounting_verified
                    or partial.get("effect_reconciliation_required")
                    or partial.get("status") == "unresolved"
                )
                partial.update(
                    status="unresolved" if unresolved else "blocked",
                    reason=outcome.failure or "NANO_MATERIAL_PRODUCTION_ACCOUNTING_UNVERIFIED",
                    accounting_verified=outcome.accounting_verified,
                    effect_reconciliation_required=unresolved,
                    identical_retry_denied=bool(unresolved or not outcome.accounting_verified),
                )
                raise NanoMaterialProductionRunnerError(str(partial["reason"]), partial_result=partial)
            calls, committed = _required_route_counts(native_result)
            inputs = (outcome.input_count, outcome.session_input_count, outcome.runtime_input_count)
            if (
                any(type(value) is not int for value in inputs)
                or not 0 <= inputs[0] <= MAX_INPUTS
                or len(set(inputs)) != 1 or calls > inputs[0]
            ):
                native_result["accounting_verified"] = False
                raise ValueError("Nano Material Production SDK input accounting is disputed")
            if calls:
                _require_effect_evidence(native_result)
            if (
                native_result.get("status") == "blocked"
                and calls == committed == 1
                and type(native_result.get("active_production_count")) is int
                and type(native_result.get("completed_batch_count")) is int
                and native_result.get("production_state") == "idle"
                and native_result.get("active_production_count") == 0
                and native_result.get("completed_batch_count") == 0
                and native_result.get("effect_reconciliation_required") is False
                and native_result.get("identical_retry_denied") is False
                and native_result.get("terminal_home_verified") is True
            ):
                _require_terminal_home(native_result)
                _require_production_frame(native_result)
                if (
                    native_result.get("native_occurrence_key") != occurrence_key
                    or native_result.get("occurrence_key") != occurrence_key
                    or native_result.get("production_occurrence_key") != occurrence_key
                    or native_result.get("production_target_identity") != NANO_MATERIAL_PRODUCTION_TARGET
                    or native_result["last_action_evidence"]["after"]["frame_sha256"]
                    != native_result.get("production_state_observation_sha256")
                ):
                    raise ValueError("Nano Material Production partial claim source/occurrence is unproven")
                validate_identity()
                partial = dict(
                    native_result, flow_id=FLOW_ID, product_id=PRODUCT_ID,
                    product_revision=PRODUCT_REVISION, task_id=PRODUCT_ID,
                    account_id=identity.account_id, server_id=identity.server_id,
                    reset_id=identity.reset_id, backend_identity=dict(backend_identity),
                    runtime_profile_id=PROFILE_ID, accounting_verified=True,
                    input_count=inputs[0], total_input_count=inputs[0],
                    next_eligible_at=None, startup_recovery=outcome.startup_recovery,
                    session_directory=outcome.session_directory,
                )
                # A known partial is not a timer completion and has no invented due.
                raise NanoMaterialProductionRunnerError(str(partial["reason"]), partial_result=partial)
            if (
                native_result.get("status") not in {"completed", "deferred"}
                or native_result.get("terminal_home_verified") is not True
                or native_result.get("effect_reconciliation_required") is not False
                or native_result.get("identical_retry_denied") is not False
            ):
                raise ValueError("Nano Material Production route has no verified terminal Home result")
            _require_terminal_home(native_result)
            timer = native_result.get("timer_seconds_remaining")
            if (
                native_result.get("production_state") != "active"
                or type(native_result.get("active_production_count")) is not int
                or native_result.get("active_production_count") != 1
                or (native_result.get("production_duration_seconds") is not None and (
                    type(native_result.get("production_duration_seconds")) is not int
                    or native_result.get("production_duration_seconds") != NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
                ))
                or type(timer) is not int
                or not 0 < timer <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
                or native_result.get("native_occurrence_key") != occurrence_key
                or native_result.get("occurrence_key") != occurrence_key
            ):
                raise ValueError("Nano Material Production active zero-cost occurrence is not positively proven")
            completed = _epoch(self.utc_clock(), "completion time")
            if completed < started:
                raise ValueError("Nano Material Production completion clock predates its run")
            validate_identity()
            input_count = outcome.input_count
            if type(input_count) is not int or not 0 <= input_count <= MAX_INPUTS:
                raise ValueError("Nano Material Production native input count exceeds its budget")
            result = dict(
                native_result,
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                account_id=identity.account_id,
                server_id=identity.server_id,
                reset_id=identity.reset_id,
                backend_identity=dict(backend_identity),
                occurrence_key=occurrence_key,
                completed_at_utc=completed,
                runtime_profile_id=PROFILE_ID,
                time_basis="utc",
                input_count=input_count,
                total_input_count=input_count,
                production_transport_calls=calls,
                next_eligible_at=completed + timer,
                accounting_verified=outcome.accounting_verified,
                terminal_home_verified=True,
                startup_recovery=outcome.startup_recovery,
                session_directory=outcome.session_directory,
            )
            nano_material_production_next_due(result, identity, started)
            validate_identity()
            checkpoint()
            return result
        except NanoMaterialProductionRunnerError:
            raise
        except Exception as exc:
            partial = dict(native_result) if isinstance(native_result, Mapping) else {}
            partial.update(dict(getattr(exc, "partial_result", {}) or {}))
            if isinstance(partial.get("reason"), str):
                partial.setdefault("native_reason", partial["reason"])
            raw_calls = partial.get("production_transport_calls")
            count_known = type(raw_calls) is int and raw_calls >= 0
            calls = raw_calls if count_known else 0
            unresolved = bool(
                (calls != partial.get("committed_action_count"))
                or (outcome is not None and not count_known)
                or (outcome is not None and not outcome.accounting_verified)
                or partial.get("accounting_verified") is False
                or partial.get("effect_reconciliation_required")
                or partial.get("status") == "unresolved"
            )
            partial.update(
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                account_id=getattr(identity, "account_id", None),
                server_id=getattr(identity, "server_id", None),
                reset_id=getattr(identity, "reset_id", None),
                occurrence_key=occurrence_key,
                status="unresolved" if unresolved else "blocked",
                reason=str(exc),
                effect_reconciliation_required=unresolved,
                identical_retry_denied=bool(unresolved or partial.get("identical_retry_denied")),
            )
            raise NanoMaterialProductionRunnerError(str(exc), partial_result=partial) from exc


def nano_material_production_next_due(result, identity, started_at: float) -> float:
    """Accept only current occurrence action/no-work evidence with active timer and Home."""

    started = _epoch(started_at, "start time")
    if (
        result.get("flow_id") != FLOW_ID
        or result.get("product_id") != PRODUCT_ID
        or result.get("product_revision") != PRODUCT_REVISION
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
        or result.get("status") not in {"completed", "deferred"}
        or result.get("time_basis") != "utc"
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
    ):
        raise ValueError("Nano Material Production result is not verified for scheduling")
    _require_terminal_home(result)
    if (
        result.get("production_state") != "active"
        or type(result.get("active_production_count")) is not int
        or result.get("active_production_count") != 1
        or (result.get("production_duration_seconds") is not None and (
            type(result.get("production_duration_seconds")) is not int
            or result.get("production_duration_seconds") != NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        ))
    ):
        raise ValueError("Nano Material Production current active single-slot state is unproven")
    if (
        result.get("task_id") != PRODUCT_ID
        or result.get("runtime_profile_id") != PROFILE_ID
    ):
        raise ValueError("Nano Material Production task/profile identity is not canonical")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if completed < started:
        raise ValueError("Nano Material Production completion precedes run start")
    _verify_backend_identity(result.get("backend_identity"), identity, completed)
    if (
        type(result.get("occurrence_key")) is not str
        or not result.get("occurrence_key")
        or result.get("native_occurrence_key") != result.get("occurrence_key")
        or result.get("production_occurrence_key") != result.get("occurrence_key")
        or result.get("production_target_identity") != NANO_MATERIAL_PRODUCTION_TARGET
    ):
        raise ValueError("Nano Material Production occurrence/target binding is missing")
    _require_production_frame(result)
    inputs = result.get("total_input_count")
    input_count = result.get("input_count")
    calls, committed = _required_route_counts(result)
    if calls:
        _require_effect_evidence(result)
    if (
        type(inputs) is not int
        or type(input_count) is not int
        or input_count != inputs
        or not 0 <= inputs <= MAX_INPUTS
        or calls != committed
        or calls > inputs
    ):
        raise ValueError("Nano Material Production input/action count mismatch")
    timer = result.get("timer_seconds_remaining")
    if type(timer) is not int or not 0 < timer <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS:
        raise ValueError("Nano Material Production active timer is not positively recognized")
    due = completed + timer
    if result.get("next_eligible_at") != due:
        raise ValueError("Nano Material Production due time does not match its observed timer")
    return due
