"""Canonical reset-scoped service adapter for Hero Duel–Survival participation."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from pathlib import Path
import time
from typing import Any, Mapping

from tasks.runtime_identity import (
    BLUESTACKS_ADB, BLUESTACKS_SERIAL,
    derive_resource_runtime_identity, derive_static_utc_reset, resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteRequest
from .recruitment import recruitment_reset
from .registry import (
    HERO_DUEL_FLOW_ID, HERO_DUEL_HANDLER_ID, HERO_DUEL_MAX_INPUTS,
    HERO_DUEL_PRODUCT_ID, HERO_DUEL_PRODUCT_REVISION, HERO_DUEL_PROFILE_ID,
    RegisteredDispatchSnapshot, canonical_entry,
)


FLOW_ID = HERO_DUEL_FLOW_ID
PRODUCT_ID = HERO_DUEL_PRODUCT_ID
PRODUCT_REVISION = HERO_DUEL_PRODUCT_REVISION
PROFILE_ID = HERO_DUEL_PROFILE_ID
MAX_INPUTS = HERO_DUEL_MAX_INPUTS
MAX_ACTIONS = 3


class HeroDuelExecutionHandler:
    """Execution-only route handler for the single fixed Hero Duel product."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Hero Duel requires a typed canonical registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Hero Duel registration identity mismatch")
        if not callable(execute):
            raise TypeError("Hero Duel executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Hero Duel requires its matching canonical flow spec")
        self.snapshot = snapshot
        self._execute = execute
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
        return self.recover("HERO_DUEL_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("HERO_DUEL_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class HeroDuelRunnerError(RuntimeError):
    def __init__(self, reason: str, *, partial_result: Mapping[str, object]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Hero Duel {label} must be a finite non-negative UTC epoch")
    return float(value)


def _fixed_backend_identity(identity: SchedulerIdentity, *, now: float, serial: str):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Hero Duel requires its canonical scheduler identity")
    sample = datetime.fromtimestamp(now, timezone.utc)
    scheduler_reset = recruitment_reset(now)
    window = derive_static_utc_reset(sample)
    binding = resource_fixed_runtime_binding()
    if serial != BLUESTACKS_SERIAL or binding.serial != serial:
        raise ValueError("Hero Duel requires the fixed BlueStacks runtime binding")
    backend = derive_resource_runtime_identity(binding, sample)
    if (
        identity.reset_id != scheduler_reset
        or (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id)
        or (backend.reset_start_utc, backend.reset_deadline_utc)
        != (window.reset_start_text, window.reset_deadline_text)
    ):
        raise ValueError("Hero Duel scheduler/backend reset-window identity mismatch")
    return backend


def _backend_mapping(backend) -> dict[str, object]:
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


def _verified_terminal_home(result: Mapping[str, Any]) -> None:
    proof = result.get("terminal_home_frame")
    if (result.get("terminal_home_verified") is not True
            or not isinstance(proof, Mapping)
            or not isinstance(proof.get("frame_path"), str) or not proof["frame_path"]
            or not isinstance(proof.get("frame_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", proof["frame_sha256"]) is None):
        raise ValueError("Hero Duel requires current terminal clean-Home evidence")


_TRANSPORT_COUNT_FIELDS = (
    "duel_dispatch_count", "entry_transport_calls", "flee_transport_calls",
    "defense_save_transport_calls", "defense_selection_transport_calls",
)

def _counts(result: Mapping[str, Any]) -> tuple[int, int, int, int, int]:
    fields = _TRANSPORT_COUNT_FIELDS
    values = [result.get(field) for field in fields]
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Hero Duel native action/input counts are malformed")
    duel, entry, flee, save, selection = values
    committed = result.get("committed_action_count")
    if (duel != entry or duel > MAX_ACTIONS or flee > MAX_ACTIONS or save > 1
            or selection > 10 or type(committed) is not int or not 0 <= committed <= MAX_ACTIONS
            or duel > committed or flee > committed):
        raise ValueError("Hero Duel entry/Flee/defense counts exceed their independent route bounds")
    return duel, entry, flee, save, selection

def _has_transport_attempt(result: Mapping[str, Any]) -> bool:
    return any(
        type(result.get(field)) is int and result[field] > 0
        for field in _TRANSPORT_COUNT_FIELDS
    )

def _merge_partial_result(native_result: Mapping[str, Any], partial_result: object) -> dict[str, Any]:
    merged = dict(native_result)
    if not isinstance(partial_result, Mapping):
        return merged
    prior_counts = {
        field: merged.get(field)
        for field in (*_TRANSPORT_COUNT_FIELDS, "committed_action_count")
    }
    prior_proofs = merged.get("cycle_proofs")
    prior_canonical = merged.get("canonical_confirmed_cycle_ordinals")
    prior_evidence = merged.get("evidence")
    merged.update(partial_result)
    for field, prior in prior_counts.items():
        current = merged.get(field)
        if type(prior) is int and prior >= 0 and (type(current) is not int or current < prior):
            merged[field] = prior
    current_proofs = merged.get("cycle_proofs")
    if (type(prior_proofs) is list and type(current_proofs) is list
            and len(prior_proofs) > len(current_proofs)):
        merged["cycle_proofs"] = prior_proofs
    current_canonical = merged.get("canonical_confirmed_cycle_ordinals")
    if (type(prior_canonical) is list and type(current_canonical) is list
            and len(prior_canonical) > len(current_canonical)):
        merged["canonical_confirmed_cycle_ordinals"] = prior_canonical
    current_evidence = merged.get("evidence")
    if (type(prior_evidence) is list and type(current_evidence) is list
            and len(prior_evidence) > len(current_evidence)):
        merged["evidence"] = prior_evidence
    return merged


class HeroDuelRunner:
    """Device-free native runner; the injected boundary owns runtime and durable actions."""

    def __init__(self, *, native: NativeRouteBoundary | None = None,
                 output_directory: Path, adb=BLUESTACKS_ADB, serial=BLUESTACKS_SERIAL,
                 utc_clock=time.time, monotonic_clock=time.monotonic, settle_seconds: float = 1.0):
        self.native = native
        self.output_directory = Path(output_directory)
        self.adb, self.serial = str(adb), str(serial)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        if (type(settle_seconds) not in (int, float) or isinstance(settle_seconds, bool)
                or not math.isfinite(float(settle_seconds)) or settle_seconds < 0):
            raise ValueError("Hero Duel settle delay must be finite and non-negative")
        self.settle_seconds = float(settle_seconds)
        if native is not None and (native.flow_id, native.product_id, native.product_revision,
                native.runtime_profile_id, native.max_inputs, native.max_actions) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID, MAX_INPUTS, MAX_ACTIONS):
            raise ValueError("Hero Duel native route binding identity/budget mismatch")

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key):
        if self.native is None:
            raise HeroDuelRunnerError("HERO_DUEL_NATIVE_BINDING_REQUIRED", partial_result={
                "status": "blocked", "reason": "native_route_binding_required",
                "duel_dispatch_count": 0, "entry_transport_calls": 0,
                "flee_transport_calls": 0, "defense_save_transport_calls": 0,
                "defense_selection_transport_calls": 0, "committed_action_count": 0,
                "effect_reconciliation_required": False, "identical_retry_denied": False,
            })
        started = _epoch(self.utc_clock(), "start")
        backend = _fixed_backend_identity(identity, now=started, serial=self.serial)

        def validate_identity() -> None:
            current = _fixed_backend_identity(identity, now=_epoch(self.utc_clock(), "identity clock"), serial=self.serial)
            if (current.runtime_scope, current.account_id, current.server_id, current.reset_id,
                    current.runtime_binding_digest, current.reset_start_utc, current.reset_deadline_utc) != (
                    backend.runtime_scope, backend.account_id, backend.server_id, backend.reset_id,
                    backend.runtime_binding_digest, backend.reset_start_utc, backend.reset_deadline_utc):
                raise ValueError("Hero Duel fixed backend identity/reset window changed during route")

        checkpoint()
        request = NativeRouteRequest(
            flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            runtime_profile_id=PROFILE_ID, identity=identity, previous_reset_id=previous_reset_id,
            occurrence_key=occurrence_key, checkpoint=checkpoint, validate_identity=validate_identity,
            runtime_input_lock=runtime_input_lock, adb=self.adb, serial=self.serial,
            output_directory=self.output_directory, max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
            settle_seconds=self.settle_seconds,
            arguments={"atlas_path": str(Path(__file__).resolve().parents[1] / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"),
                       "arena_building_id": "home.building.arena"},
            utc_clock=self.utc_clock, monotonic_clock=self.monotonic_clock,
        )
        outcome = self.native.run(request)
        native_result = dict(outcome.native_result)
        if outcome.flow_id != FLOW_ID:
            partial = _merge_partial_result(native_result, outcome.partial_result)
            attempted = _has_transport_attempt(partial)
            unresolved = (attempted or outcome.accounting_verified is not True
                or partial.get("effect_reconciliation_required") is True
                or partial.get("identical_retry_denied") is True)
            partial.update(status="unresolved" if unresolved else "blocked",
                reason="HERO_DUEL_NATIVE_FLOW_MISMATCH",
                effect_reconciliation_required=bool(partial.get("effect_reconciliation_required") or unresolved),
                identical_retry_denied=bool(partial.get("identical_retry_denied") or unresolved),
                accounting_verified=outcome.accounting_verified)
            raise HeroDuelRunnerError(str(partial["reason"]), partial_result=partial)
        if outcome.failure is not None or outcome.accounting_verified is not True:
            partial = _merge_partial_result(native_result, outcome.partial_result)
            attempted = _has_transport_attempt(partial)
            unresolved = (attempted or outcome.accounting_verified is not True
                or partial.get("effect_reconciliation_required") is True
                or partial.get("identical_retry_denied") is True
                or partial.get("status") in {"unresolved", "reconciliation_required"})
            partial.update(status="unresolved" if unresolved else "blocked",
                reason=outcome.failure or "HERO_DUEL_ACCOUNTING_UNVERIFIED",
                effect_reconciliation_required=bool(partial.get("effect_reconciliation_required") or unresolved),
                identical_retry_denied=bool(partial.get("identical_retry_denied") or unresolved),
                accounting_verified=outcome.accounting_verified)
            raise HeroDuelRunnerError(str(partial["reason"]), partial_result=partial)
        try:
            duel, entry, flee, save, selection = _counts(native_result)
            if native_result.get("status") not in {"complete_for_reset", "already_complete", "deferred"}:
                raise ValueError("Hero Duel native route has no accepted terminal disposition")
            if native_result.get("effect_reconciliation_required") is not False or native_result.get("identical_retry_denied") is not False:
                raise ValueError("Hero Duel effect state requires reconciliation or prohibits retry")
            _verified_terminal_home(native_result)
            if native_result.get("runtime_profile_id") != PROFILE_ID or native_result.get("reset_id") != identity.reset_id:
                raise ValueError("Hero Duel result does not match the current canonical scheduler reset")
            if native_result.get("total_input_count") != outcome.input_count or not 0 <= outcome.input_count <= MAX_INPUTS:
                raise ValueError("Hero Duel native input accounting differs from the retained session")
            canonical = native_result.get("canonical_confirmed_cycle_ordinals")
            if type(canonical) is not list or canonical != sorted(set(canonical)) or any(type(n) is not int or n not in (1, 2, 3) for n in canonical):
                raise ValueError("Hero Duel canonical cycle ordinal proof is malformed")
            proofs = native_result.get("cycle_proofs")
            if type(proofs) is not list or any(not isinstance(proof, Mapping) for proof in proofs):
                raise ValueError("Hero Duel route lacks typed cycle proof records")
            if len(proofs) != len(canonical) or native_result.get("committed_action_count") != len(proofs):
                raise ValueError("Hero Duel committed action count differs from canonical semantic cycle proofs")
            proof_ordinals = []
            for proof in proofs:
                ordinal = proof.get("ordinal")
                before_free, after_free = proof.get("free_before"), proof.get("free_after")
                before_pass, after_pass = proof.get("pass_before"), proof.get("pass_after")
                if (type(ordinal) is not int or ordinal not in (1, 2, 3) or ordinal in proof_ordinals
                        or ordinal not in canonical
                        or proof.get("wave_text") != "Wave 1/1" or proof.get("battle_board_verified") is not True
                        or proof.get("exit_confirmed") is not True or proof.get("flee_confirmed") is not True
                        or proof.get("loss_result_seen") is not True or proof.get("tap_to_continue_confirmed") is not True
                        or type(before_free) is not int or before_free != 4 - ordinal
                        or type(after_free) is not int or after_free != before_free - 1
                        or type(before_pass) is not int or before_pass < 0
                        or type(after_pass) is not int or after_pass != before_pass
                        or proof.get("event_identity") != native_result.get("hero_duel_event_identity")
                        or proof.get("reset_id") != identity.reset_id):
                    raise ValueError("Hero Duel cycle lacks exact free/pass and loss-path proof")
                proof_ordinals.append(ordinal)
            if proof_ordinals != canonical:
                raise ValueError("Hero Duel cycle proofs do not match canonical ordinal order")
            final_pass = native_result.get("final_pass_balance")
            if (type(final_pass) is not int or final_pass < 0
                    or any(proof["pass_after"] != final_pass for proof in proofs)):
                raise ValueError("Hero Duel final pass balance differs from committed cycle receipts")
            if (not isinstance(native_result.get("hero_duel_event_identity"), str)
                    or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", native_result["hero_duel_event_identity"]) is None
                    or native_result.get("current_event_active") is not True):
                raise ValueError("Hero Duel current event instance is not proven")
            if native_result.get("status") in {"complete_for_reset", "already_complete"}:
                if canonical != [1, 2, 3] or native_result.get("final_free_entries_remaining") != 0:
                    raise ValueError("Hero Duel completion requires exactly three canonical cycles and no Free entries")
                if native_result.get("status") == "already_complete" and (duel or native_result.get("no_work") is not True):
                    raise ValueError("Hero Duel already-complete outcome must be no-work")
            completed = _epoch(self.utc_clock(), "completion")
            if completed < started:
                raise ValueError("Hero Duel completion clock predates the service claim")
            if native_result.get("status") == "deferred":
                free = native_result.get("final_free_entries_remaining")
                available_at = _epoch(native_result.get("availability_observed_at_utc"), "availability observation")
                if (type(free) is not int or not 0 < free <= MAX_ACTIONS or len(canonical) + free != MAX_ACTIONS
                        or not proofs or available_at < started or available_at > completed
                        or completed - available_at > 30.0):
                    raise ValueError("Hero Duel deferred outcome lacks fresh canonical Free-availability proof")
            validate_identity()
            result = dict(native_result,
                flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID, account_id=identity.account_id, server_id=identity.server_id,
                reset_id=identity.reset_id, occurrence_key=occurrence_key,
                completed_at_utc=completed, started_at_utc=started, time_basis="utc",
                total_input_count=outcome.input_count, input_count=outcome.input_count,
                duel_dispatch_count=duel, entry_transport_calls=entry, flee_transport_calls=flee,
                defense_save_transport_calls=save, defense_selection_transport_calls=selection,
                committed_action_count=native_result["committed_action_count"],
                backend_identity=_backend_mapping(backend),
                native_invocation_id=outcome.invocation_id,
                session_directory=outcome.session_directory,
                startup_recovery=outcome.startup_recovery,
            )
            return result
        except Exception as exc:
            partial = dict(native_result)
            attempted = _has_transport_attempt(partial)
            unresolved = (attempted or partial.get("effect_reconciliation_required") is True
                or partial.get("identical_retry_denied") is True
                or partial.get("status") in {"unresolved", "reconciliation_required"})
            partial.update(status="unresolved" if unresolved else "blocked", reason=str(exc), flow_id=FLOW_ID,
                product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION, task_id=PRODUCT_ID,
                account_id=getattr(identity, "account_id", None), server_id=getattr(identity, "server_id", None),
                reset_id=getattr(identity, "reset_id", None), occurrence_key=occurrence_key,
                effect_reconciliation_required=bool(partial.get("effect_reconciliation_required") or unresolved),
                identical_retry_denied=bool(partial.get("identical_retry_denied") or unresolved))
            raise HeroDuelRunnerError(str(exc), partial_result=partial) from exc


def hero_duel_next_due(result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float) -> float:
    """Accept only exact three-cycle completion or a proven active Free opportunity."""
    started = _epoch(started_at, "start")
    if (not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID
            or identity.reset_id != recruitment_reset(started)):
        raise ValueError("Hero Duel requires its current canonical scheduler reset")
    if (result.get("flow_id") != FLOW_ID or result.get("product_id") != PRODUCT_ID
            or result.get("product_revision") != PRODUCT_REVISION
            or (result.get("account_id"), result.get("server_id"), result.get("reset_id"), result.get("task_id"))
            != (identity.account_id, identity.server_id, identity.reset_id, PRODUCT_ID)
            or result.get("runtime_profile_id") != PROFILE_ID or result.get("time_basis") != "utc"
            or result.get("terminal_home_verified") is not True
            or result.get("accounting_verified") is not True
            or result.get("effect_reconciliation_required") is not False
            or result.get("identical_retry_denied") is not False):
        raise ValueError("Hero Duel identity, Home, action, or reconciliation state is not verified")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if completed < started:
        raise ValueError("Hero Duel completion precedes route start")
    duel, entry, flee, save, selection = _counts(result)
    if result.get("total_input_count") != result.get("input_count") or type(result.get("input_count")) is not int or not 0 <= result["input_count"] <= MAX_INPUTS:
        raise ValueError("Hero Duel input accounting changed after execution")
    backend_payload = result.get("backend_identity")
    if not isinstance(backend_payload, Mapping):
        raise ValueError("Hero Duel lacks its fixed backend reset-window proof")
    sample_backend = _fixed_backend_identity(identity, now=completed, serial=BLUESTACKS_SERIAL)
    if dict(backend_payload) != _backend_mapping(sample_backend):
        raise ValueError("Hero Duel backend identity proof does not match the completion-time reset window")
    _verified_terminal_home(result)
    canonical = result.get("canonical_confirmed_cycle_ordinals")
    if (type(canonical) is not list
            or any(type(item) is not int or item not in (1, 2, 3) for item in canonical)
            or canonical != sorted(set(canonical))):
        raise ValueError("Hero Duel canonical cycle proof is malformed")
    event_identity = result.get("hero_duel_event_identity")
    if (not isinstance(event_identity, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", event_identity) is None
            or result.get("current_event_active") is not True):
        raise ValueError("Hero Duel current event instance is not proven")
    proofs = result.get("cycle_proofs")
    if (type(proofs) is not list or len(proofs) != len(canonical)
            or result.get("committed_action_count") != len(proofs)):
        raise ValueError("Hero Duel next due requires exact committed cycle proofs")
    for ordinal, proof in zip(canonical, proofs):
        if not isinstance(proof, Mapping):
            raise ValueError("Hero Duel next due cycle proof is not typed")
        before_free, after_free = proof.get("free_before"), proof.get("free_after")
        before_pass, after_pass = proof.get("pass_before"), proof.get("pass_after")
        if (type(proof.get("ordinal")) is not int or proof.get("ordinal") != ordinal
                or proof.get("event_identity") != event_identity
                or proof.get("reset_id") != identity.reset_id
                or type(before_free) is not int or before_free != 4 - ordinal
                or type(after_free) is not int or after_free != before_free - 1
                or type(before_pass) is not int or before_pass < 0
                or type(after_pass) is not int or after_pass != before_pass
                or proof.get("wave_text") != "Wave 1/1" or proof.get("battle_board_verified") is not True
                or proof.get("exit_confirmed") is not True or proof.get("flee_confirmed") is not True
                or proof.get("loss_result_seen") is not True
                or proof.get("tap_to_continue_confirmed") is not True):
            raise ValueError("Hero Duel next due cycle proof is incomplete or inconsistent")
    final_pass = result.get("final_pass_balance")
    if (type(final_pass) is not int or final_pass < 0
            or any(proof["pass_after"] != final_pass for proof in proofs)):
        raise ValueError("Hero Duel next due pass balance differs from committed cycle receipts")
    if result.get("status") in {"complete_for_reset", "already_complete"}:
        if canonical != [1, 2, 3] or result.get("final_free_entries_remaining") != 0:
            raise ValueError("Hero Duel reset completion requires all three canonical cycles")
        if result.get("status") == "already_complete" and (duel or result.get("no_work") is not True):
            raise ValueError("Hero Duel already-complete status requires canonical no-work")
        due = _epoch(datetime.fromisoformat(sample_backend.reset_deadline_utc.replace("Z", "+00:00")).timestamp(), "next reset")
        if result.get("next_eligible_at") not in (None, due):
            raise ValueError("Hero Duel next due differs from the exact backend reset deadline")
        return due
    if result.get("status") == "deferred":
        free = result.get("final_free_entries_remaining")
        event_active = result.get("current_event_active")
        event_identity = result.get("hero_duel_event_identity")
        if (type(free) is not int or not 0 < free <= MAX_ACTIONS or len(canonical) + free != MAX_ACTIONS
                or event_active is not True or not isinstance(event_identity, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", event_identity) is None):
            raise ValueError("Hero Duel deferred outcome lacks current observed Free availability")
        available_at = _epoch(result.get("availability_observed_at_utc"), "availability observation")
        if available_at < started or available_at > completed or completed - available_at > 30.0:
            raise ValueError("Hero Duel Free availability observation is stale")
        return completed
    raise ValueError("Hero Duel blocked, exhausted, partial, or unreconciled route has no evidenced next due")
