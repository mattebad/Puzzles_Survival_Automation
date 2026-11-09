"""Canonical Hall of War adapter; explicit manual occurrences retain reset-scoped Core keys."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import time
from types import MappingProxyType
from typing import Mapping

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
    HALL_OF_WAR_FLOW_ID,
    HALL_OF_WAR_MAX_INPUTS,
    HALL_OF_WAR_PRODUCT_ID,
    HALL_OF_WAR_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    HALL_OF_WAR_PROFILE_ID,
    canonical_entry,
)
from .recruitment import recruitment_reset


FLOW_ID = HALL_OF_WAR_FLOW_ID
PRODUCT_ID = HALL_OF_WAR_PRODUCT_ID
PRODUCT_REVISION = HALL_OF_WAR_PRODUCT_REVISION
PROFILE_ID = HALL_OF_WAR_PROFILE_ID
MAX_INPUTS = HALL_OF_WAR_MAX_INPUTS
MAX_ACTIONS = 3
RECHECK_SECONDS = 300.0


class HallOfWarExecutionHandler:
    """Execution-only task handler; the native route owns screen/action semantics."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Hall of War requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID
        ):
            raise ValueError("Hall of War registration identity mismatch")
        if not callable(execute):
            raise TypeError("Hall of War executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Hall of War requires its matching flow spec")
        self.snapshot = snapshot
        self._execute = execute
        self.flow_spec = flow_spec

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
        return self.recover("HALL_OF_WAR_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("HALL_OF_WAR_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "hall_of_war_dispatch_count": 0}



def _epoch(value, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Hall of War {name} must be a finite UTC epoch")
    return float(value)


def _fixed_identity(identity: SchedulerIdentity, *, now: float, serial: str):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Hall of War requires its canonical scheduler identity")
    sample = datetime.fromtimestamp(_epoch(now, "identity clock"), timezone.utc)
    scheduler_reset = recruitment_reset(float(now))
    window = derive_static_utc_reset(sample)
    binding = resource_fixed_runtime_binding()
    if serial != BLUESTACKS_SERIAL or binding.serial != serial:
        raise ValueError("Hall of War requires the fixed BlueStacks runtime")
    backend = derive_resource_runtime_identity(binding, sample)
    if (
        identity.reset_id != scheduler_reset
        or (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id)
        or (backend.reset_start_utc, backend.reset_deadline_utc)
        != (window.reset_start_text, window.reset_deadline_text)
    ):
        raise ValueError("Hall of War scheduler/backend reset-window identity mismatch")
    return backend


def _backend_identity_mapping(backend) -> dict[str, object]:
    return {
        "runtime_scope": backend.runtime_scope,
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "reset_id": backend.reset_id,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
        "assurance": backend.assurance.value,
        "runtime_binding_digest": backend.runtime_binding_digest,
    }


def _counts(result: Mapping[str, object]) -> tuple[int, int, int, int, int]:
    dispatch = result.get("dispatch_transport_calls")
    reward = result.get("reward_claim_transport_calls")
    talent = result.get("talent_switch_transport_calls", 0)
    total = result.get("hall_of_war_dispatch_count")
    committed = result.get("committed_action_count")
    if any(type(value) is not int or value not in (0, 1) for value in (dispatch, reward, talent)):
        raise ValueError("Hall of War consequential transport detail counts are invalid")
    expected = dispatch + reward + talent
    if type(total) is not int or total != expected:
        raise ValueError("Hall of War attempted transport counts disagree")
    if type(committed) is not int or not 0 <= committed <= expected:
        raise ValueError("Hall of War committed action count exceeds semantic success evidence")
    if expected > MAX_ACTIONS:
        raise ValueError("Hall of War action budget exceeded")
    return dispatch, reward, talent, expected, committed


def _failure_mapping(
    *,
    identity: object,
    occurrence_key: object,
    reason: str,
    partial: Mapping[str, object],
    outcome: object | None,
    started: float | None,
    completed: float | None,
    backend_identity: Mapping[str, object],
    transport_possible: bool = True,
) -> dict[str, object]:
    result = dict(partial)
    count_names = (
        "dispatch_transport_calls",
        "reward_claim_transport_calls",
        "talent_switch_transport_calls",
    )
    raw_counts = tuple(result.get(name) for name in count_names)
    if (
        not all(type(value) is int and value in (0, 1) for value in raw_counts)
        and outcome is not None
        and getattr(outcome, "accounting_verified", False) is True
        and getattr(outcome, "input_count", None) == 0
    ):
        raw_counts = (0, 0, 0)
    count_values_known = all(type(value) is int and value in (0, 1) for value in raw_counts)
    reported_total = result.get("hall_of_war_dispatch_count")
    derived_total = sum(raw_counts) if count_values_known else None
    counts_consistent = bool(
        count_values_known
        and (reported_total is None or type(reported_total) is int and reported_total == derived_total)
    )
    attempted = derived_total if counts_consistent else None
    raw_committed = result.get("committed_action_count")
    if (
        attempted is not None
        and type(raw_committed) is int
        and 0 <= raw_committed <= attempted
    ):
        committed = raw_committed
    elif attempted == 0 and raw_committed is None:
        committed = 0
    else:
        committed = None
    input_count = getattr(outcome, "input_count", None) if outcome is not None else None
    if type(input_count) is not int or input_count < 0:
        input_count = result.get("total_input_count", result.get("input_count"))
    native_accounting = getattr(outcome, "accounting_verified", False) if outcome is not None else False
    effect_unknown = bool(
        result.get("effect_reconciliation_required") is True
        or result.get("status") == "unresolved"
        or not counts_consistent
        or attempted is None
        or committed is None
        or attempted is not None and committed is not None and committed < attempted
        or transport_possible and native_accounting is not True
    )
    if outcome is not None and getattr(outcome, "failure", None) is not None:
        effect_unknown = effect_unknown or attempted is None or committed is None or committed < (attempted or 0)
    status = "unresolved" if effect_unknown else "blocked"
    retry_denied = bool(
        result.get("identical_retry_denied") is True
        or effect_unknown
        or attempted is None
        or attempted > 0
    )
    valid_input_count = type(input_count) is int and 0 <= input_count <= MAX_INPUTS
    result.update(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        task_id=PRODUCT_ID,
        runtime_profile_id=PROFILE_ID,
        account_id=getattr(identity, "account_id", None),
        server_id=getattr(identity, "server_id", None),
        reset_id=getattr(identity, "reset_id", None),
        occurrence_key=occurrence_key,
        status=status,
        reason=reason,
        dispatch_transport_calls=(
            raw_counts[0] if type(raw_counts[0]) is int and raw_counts[0] in (0, 1) else None
        ),
        reward_claim_transport_calls=(
            raw_counts[1] if type(raw_counts[1]) is int and raw_counts[1] in (0, 1) else None
        ),
        talent_switch_transport_calls=(
            raw_counts[2] if type(raw_counts[2]) is int and raw_counts[2] in (0, 1) else None
        ),
        hall_of_war_dispatch_count=attempted,
        committed_action_count=committed,
        effect_reconciliation_required=effect_unknown,
        identical_retry_denied=retry_denied,
        accounting_verified=bool(
            native_accounting is True and counts_consistent and committed is not None and valid_input_count
        ),
        native_execution_verified=False,
        input_count=input_count,
        total_input_count=input_count,
        started_at_utc=started,
        completed_at_utc=completed,
        time_basis="utc",
    )
    if backend_identity:
        result["backend_identity"] = dict(backend_identity)
    return result


def _verify_backend_identity(value, identity, completed: float) -> None:
    expected = _backend_identity_mapping(
        _fixed_identity(identity, now=completed, serial=BLUESTACKS_SERIAL)
    )
    if value != expected:
        raise ValueError("Hall of War verified backend identity proof is inconsistent")


def _require_terminal_home(result: Mapping[str, object]) -> None:
    proof = result.get("terminal_home_frame")
    if (
        result.get("terminal_home_verified") is not True
        or not isinstance(proof, Mapping)
        or not isinstance(proof.get("frame_path"), str)
        or not proof.get("frame_path")
        or not isinstance(proof.get("frame_sha256"), str)
        or len(proof["frame_sha256"]) != 64
    ):
        raise ValueError("Hall of War requires a current terminal Home frame")


class HallOfWarRunner:
    """Device-free construction over the injected fixed Hall of War native boundary."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None = None,
        adb=BLUESTACKS_ADB,
        serial=BLUESTACKS_SERIAL,
        output_directory: Path,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 0.65,
    ) -> None:
        self.native = native
        self.adb, self.serial = str(adb), str(serial)
        if Path(self.adb).resolve() != Path(BLUESTACKS_ADB).resolve() or self.serial != BLUESTACKS_SERIAL:
            raise ValueError("Hall of War requires its fixed BlueStacks backend")
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = float(_epoch(settle_seconds, "settle delay"))
        if not callable(utc_clock) or not callable(monotonic_clock):
            raise ValueError("Hall of War runner requires UTC and monotonic clocks")
        if native is not None and getattr(native, "flow_id", None) != FLOW_ID:
            raise ValueError("Hall of War native binding identity mismatch")

    def __call__(
        self,
        identity,
        previous_reset_id,
        checkpoint,
        *,
        runtime_input_lock,
        occurrence_key,
        operator_request_id: str | None = None,
    ) -> Mapping[str, object]:
        started = None
        completed = None
        backend_identity: dict[str, object] = {}
        outcome = None
        native_result: dict[str, object] = {}
        native_started = False
        try:
            if operator_request_id is not None and (
                not isinstance(operator_request_id, str)
                or not operator_request_id.strip()
                or operator_request_id != operator_request_id.strip()
                or len(operator_request_id) > 256
            ):
                raise ValueError("Hall of War replay requires its claimed operator request")
            started = _epoch(self.utc_clock(), "start time")
            if self.native is None:
                return _failure_mapping(
                    identity=identity,
                    occurrence_key=occurrence_key,
                    reason="HALL_OF_WAR_NATIVE_BINDING_REQUIRED",
                    partial={
                        "dispatch_transport_calls": 0,
                        "reward_claim_transport_calls": 0,
                        "talent_switch_transport_calls": 0,
                        "hall_of_war_dispatch_count": 0,
                        "committed_action_count": 0,
                        "input_count": 0,
                        "total_input_count": 0,
                    },
                    outcome=None,
                    started=started,
                    completed=started,
                    backend_identity={},
                    transport_possible=False,
                )

            def validate_identity() -> None:
                backend = _fixed_identity(identity, now=_epoch(self.utc_clock(), "identity clock"), serial=self.serial)
                backend_identity.clear()
                backend_identity.update(_backend_identity_mapping(backend))

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
                arguments=MappingProxyType(
                    {} if operator_request_id is None else {
                        "operator_request_id": operator_request_id,
                        "manual_occurrence_key": occurrence_key,
                    }
                ),
                utc_clock=self.utc_clock,
                monotonic_clock=self.monotonic_clock,
            )
            native_started = True
            outcome = self.native.run(request)
            native_result = dict(outcome.native_result)
            if outcome.flow_id != FLOW_ID:
                native_result.update(
                    status="unresolved",
                    effect_reconciliation_required=True,
                    identical_retry_denied=True,
                )
                raise ValueError("Hall of War native outcome flow mismatch")
            if outcome.failure is not None or outcome.accounting_verified is not True:
                partial = dict(outcome.partial_result or native_result)
                completed = _epoch(self.utc_clock(), "completion time")
                return _failure_mapping(
                    identity=identity,
                    occurrence_key=occurrence_key,
                    reason=outcome.failure or "HALL_OF_WAR_ACCOUNTING_UNVERIFIED",
                    partial=partial,
                    outcome=outcome,
                    started=started,
                    completed=completed,
                    backend_identity=backend_identity,
                )
            dispatch, reward, talent, total, committed = _counts(native_result)
            status = native_result.get("status")
            if status not in {"complete_for_reset", "deferred", "blocked", "unresolved"}:
                raise ValueError("Hall of War native route returned an unsupported terminal status")
            effect_unknown = native_result.get("effect_reconciliation_required")
            retry_denied = native_result.get("identical_retry_denied")
            if type(effect_unknown) is not bool or type(retry_denied) is not bool:
                raise ValueError("Hall of War native result lacks exact effect/retry flags")
            if effect_unknown and status != "unresolved":
                raise ValueError("Hall of War unresolved effect has a non-unresolved terminal status")
            if status == "unresolved" and not effect_unknown:
                raise ValueError("Hall of War unresolved status lacks an effect reconciliation guard")
            if committed < total and not effect_unknown:
                raise ValueError("Hall of War attempted action lacks positive semantic completion")
            if effect_unknown and not retry_denied:
                raise ValueError("Hall of War unresolved action does not deny an identical retry")
            if status == "complete_for_reset":
                _require_terminal_home(native_result)
                if (
                    native_result.get("challenge_status") not in {"confirmed", "confirmed_prior_canonical_action"}
                    or native_result.get("reward_status") not in {"claimed", "already_claimed"}
                ):
                    raise ValueError("Hall of War completion lacks both independent reset outcomes")
            elif status == "deferred" and native_result.get("terminal_home_verified") is not True:
                raise ValueError("Hall of War deferred result has no verified Home return")
            completed = _epoch(self.utc_clock(), "completion time")
            if completed < started:
                raise ValueError("Hall of War completion clock predates its run")
            validate_identity()
            if native_result.get("scheduler_reset_id") != identity.reset_id:
                raise ValueError("Hall of War scheduler reset differs from the route result")
            _verify_backend_identity(native_result.get("backend_identity_proof"), identity, completed)
            input_count = outcome.input_count
            if type(input_count) is not int or not 0 <= input_count <= MAX_INPUTS:
                raise ValueError("Hall of War native input count exceeds its budget")
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
                runtime_profile_id=PROFILE_ID,
                occurrence_key=occurrence_key,
                completed_at_utc=completed,
                time_basis="utc",
                input_count=input_count,
                total_input_count=input_count,
                dispatch_transport_calls=dispatch,
                reward_claim_transport_calls=reward,
                talent_switch_transport_calls=talent,
                hall_of_war_dispatch_count=total,
                committed_action_count=committed,
                accounting_verified=outcome.accounting_verified,
                startup_recovery=outcome.startup_recovery,
                session_directory=outcome.session_directory,
            )
            validate_identity()
            checkpoint()
            return result
        except Exception as exc:
            partial = dict(getattr(exc, "partial_result", {}) or {})
            if not partial:
                partial = dict(outcome.partial_result or native_result) if outcome is not None else {}
            if not native_started:
                partial.setdefault("dispatch_transport_calls", 0)
                partial.setdefault("reward_claim_transport_calls", 0)
                partial.setdefault("talent_switch_transport_calls", 0)
                partial.setdefault("hall_of_war_dispatch_count", 0)
                partial.setdefault("committed_action_count", 0)
                partial.setdefault("input_count", 0)
                partial.setdefault("total_input_count", 0)
            try:
                completed = _epoch(self.utc_clock(), "completion time")
                if started is not None and completed < started:
                    completed = None
            except Exception:
                completed = None
            return _failure_mapping(
                identity=identity,
                occurrence_key=occurrence_key,
                reason=str(exc),
                partial=partial,
                outcome=outcome,
                started=started,
                completed=completed,
                backend_identity=backend_identity,
                transport_possible=native_started,
            )


def hall_of_war_next_due(result: Mapping[str, object], identity: SchedulerIdentity, started_at: float) -> float | None:
    """Use the real reset or a bounded policy re-observation of known deferrals."""
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Hall of War outcome requires its exact scheduler identity")
    started = _epoch(started_at, "start time")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if completed < started or recruitment_reset(completed) != identity.reset_id:
        raise ValueError("Hall of War outcome is outside its claimed reset window")
    deadline = derive_static_utc_reset(datetime.fromtimestamp(completed, timezone.utc)).reset_deadline_utc.timestamp()
    if result.get("status") == "complete_for_reset" or result.get("challenge_status") == "deferred_unexplained_prior_same_reset_use":
        return deadline
    if result.get("status") == "deferred":
        # This is a policy recheck, not a claimed game cooldown or an unknown-effect retry.
        return min(completed + RECHECK_SECONDS, deadline)
    return None
