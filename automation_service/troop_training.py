"""Canonical service binding for the fixed four-variant troop-training route."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import math
from pathlib import Path
import re
import time as time_module
from types import MappingProxyType
from typing import Any, Mapping

from automation_service.contracts import NormalizedOutcome, NormalizedResult
from automation_service.native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from automation_service.registry import (
    TROOP_TRAINING_FLOW_ID as FLOW_ID,
    TROOP_TRAINING_HANDLER_ID as HANDLER_ID,
    TROOP_TRAINING_MAX_INPUTS as MAX_INPUTS,
    TROOP_TRAINING_PHASE_MODE as PHASE_MODE,
    TROOP_TRAINING_PRODUCT_ID as PRODUCT_ID,
    TROOP_TRAINING_PRODUCT_REVISION as PRODUCT_REVISION,
    TROOP_TRAINING_PROFILE_ID as PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.troop_training import TROOP_TYPES


MAX_ACTIONS = 12
RESET_SCOPED = True
_ACTION_PREFIX = "troop-training"
_START_KEY = re.compile(
    r"^troop-training:([0-9a-f]{64}):([0-9a-f]{64}):(fighter|vehicle|shooter|rider):g([1-9][0-9]*):start$"
)
_COUNTABLE_ACTION_STATUSES = frozenset({"prepared", "input_sent", "confirmed", "unresolved"})




class TrainingActionHistoryError(ValueError):
    """Canonical training actions do not describe a safe, unique queue history."""


@dataclass(frozen=True)
class TrainingActionState:
    runtime_identity_sha256: str
    queue_generations: Mapping[str, int]
    per_reset_variant_start_counts: Mapping[str, int]
    per_reset_variant_claim_counts: Mapping[str, int]
    prior_daily_initiations: frozenset[str]
    pending_start_action_keys: Mapping[str, str]
    pending_start_reset_ids: Mapping[str, str]
    next_start_action_keys: Mapping[str, str]
    blocked_start_variants: Mapping[str, str]


def _exact_identity_part(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip() or any(ch.isspace() for ch in value):
        raise ValueError(f"{field} must be a normalized, whitespace-free identity token")
    return value


def training_identity_digest(runtime_scope: str, account_id: str, server_id: str) -> str:
    scope = _exact_identity_part(runtime_scope, "runtime_scope")
    account = _exact_identity_part(account_id, "account_id")
    server = _exact_identity_part(server_id, "server_id")
    return hashlib.sha256((scope + "\0" + account + "\0" + server).encode("utf-8")).hexdigest()


def training_reset_digest(game_day_id: str) -> str:
    reset = _exact_identity_part(game_day_id, "game_day_id")
    return hashlib.sha256(reset.encode("utf-8")).hexdigest()


def make_training_start_action_key(
    runtime_identity_sha256: str,
    game_day_id: str,
    troop_type: str,
    queue_generation: int,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_identity_sha256):
        raise ValueError("training identity digest must be lowercase SHA-256")
    if troop_type not in TROOP_TYPES or type(queue_generation) is not int or queue_generation < 1:
        raise ValueError("training start key requires a fixed variant and positive queue generation")
    return (
        f"{_ACTION_PREFIX}:{runtime_identity_sha256}:{training_reset_digest(game_day_id)}:"
        f"{troop_type}:g{queue_generation}:start"
    )


def make_training_claim_action_key(confirmed_start_action_key: str) -> str:
    parsed = _START_KEY.fullmatch(confirmed_start_action_key)
    if parsed is None:
        raise ValueError("training claim key requires an exact canonical start action key")
    return f"{confirmed_start_action_key}:claim"


def _parse_start_key(action_key: str, expected_identity_digest: str) -> tuple[str, str, int] | None:
    match = _START_KEY.fullmatch(action_key)
    if match is None:
        if action_key.startswith(f"{_ACTION_PREFIX}:{expected_identity_digest}:"):
            raise TrainingActionHistoryError("malformed canonical troop-training action key")
        return None
    identity_digest, reset_digest, troop_type, generation_text = match.groups()
    if identity_digest != expected_identity_digest:
        return None
    return reset_digest, troop_type, int(generation_text)


def derive_training_action_state(
    action_rows: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    runtime_scope: str,
    account_id: str,
    server_id: str,
    game_day_id: str,
) -> TrainingActionState:
    """Recover per-variant quota, queue generation, and outstanding batch from SafetyStore rows."""

    identity_digest = training_identity_digest(runtime_scope, account_id, server_id)

    starts: dict[str, tuple[Mapping[str, Any], str, int, str]] = {}
    claims: dict[str, Mapping[str, Any]] = {}
    start_counts = {troop_type: 0 for troop_type in TROOP_TYPES}
    claim_counts = {troop_type: 0 for troop_type in TROOP_TYPES}
    confirmed_generations = {troop_type: [] for troop_type in TROOP_TYPES}

    blocked: dict[str, str] = {}
    for row in action_rows:
        if row.get("task_id") != FLOW_ID:
            continue
        key = row.get("action_key")
        if type(key) is not str or not key.startswith(f"{_ACTION_PREFIX}:{identity_digest}:"):
            continue
        suffix = None
        start_key = key
        for candidate in (":claim", ":resource-box", ":warehouse"):
            if key.endswith(candidate):
                start_key = key[: -len(candidate)]
                suffix = candidate[1:]
                break
        parsed = _parse_start_key(start_key, identity_digest)
        if parsed is None:
            raise TrainingActionHistoryError("canonical training action has no valid start-key identity")
        reset_digest, troop_type, generation = parsed
        status = row.get("final_status")
        if type(status) is not str or status not in _COUNTABLE_ACTION_STATUSES | {"cancelled"}:
            raise TrainingActionHistoryError("canonical training action has an unknown status")
        row_reset = row.get("game_day_id")
        if type(row_reset) is not str or not row_reset:
            raise TrainingActionHistoryError("canonical training action lacks its stored game day")
        if suffix is None:
            if training_reset_digest(row_reset) != reset_digest:
                raise TrainingActionHistoryError("training start key and stored game day disagree")
            if row.get("semantic_action") != "TROOP_TRAINING_START":
                raise TrainingActionHistoryError("training start key has a different semantic action")
            if key in starts:
                raise TrainingActionHistoryError("duplicate canonical training start identity")
            starts[key] = (row, troop_type, generation, row_reset)
            if status in _COUNTABLE_ACTION_STATUSES:
                if row_reset == game_day_id:
                    start_counts[troop_type] += 1
                if status == "confirmed":
                    confirmed_generations[troop_type].append(generation)
        elif suffix == "claim":
            if row.get("semantic_action") != "TROOP_TRAINING_COMPLETED_BATCH_CLAIM":
                raise TrainingActionHistoryError("training claim key has a different semantic action")
            if start_key in claims:
                raise TrainingActionHistoryError("duplicate canonical claim identity")
            claims[start_key] = row
            if status in _COUNTABLE_ACTION_STATUSES and row_reset == game_day_id:
                claim_counts[troop_type] += 1
        elif suffix in {"resource-box", "warehouse"}:
            raise TrainingActionHistoryError(
                f"troop-training {suffix} continuation {key!r} ({status}) requires manual "
                "reconciliation; no automatic replay is authorized"
            )
        else:
            raise TrainingActionHistoryError("unsupported troop-training continuation action")

    generations = {troop_type: 0 for troop_type in TROOP_TYPES}
    for troop_type, variant_generations in confirmed_generations.items():
        if len(variant_generations) != len(set(variant_generations)):
            raise TrainingActionHistoryError("variant queue generation is duplicated")
        if variant_generations:
            generations[troop_type] = max(variant_generations)
    if any(start_key not in starts for start_key in claims):
        raise TrainingActionHistoryError("training claim is not bound to a persisted start")

    pending: dict[str, str] = {}
    pending_resets: dict[str, str] = {}
    for start_key, (row, troop_type, _generation, start_reset) in starts.items():
        if row.get("final_status") != "confirmed":
            continue
        claim = claims.get(start_key)
        if claim is not None and claim.get("final_status") == "confirmed":
            continue
        if troop_type in pending:
            raise TrainingActionHistoryError("multiple unclaimed confirmed queues exist for one troop variant")
        pending[troop_type] = start_key
        pending_resets[troop_type] = start_reset

    next_keys: dict[str, str] = {}
    for troop_type in TROOP_TYPES:
        if troop_type in pending:
            continue
        candidate_generation = generations[troop_type] + 1
        candidate_key = make_training_start_action_key(
            identity_digest, game_day_id, troop_type, candidate_generation
        )
        if candidate_key in starts:
            blocked.setdefault(troop_type, "start generation already has a canonical action; no identical retry")
        elif troop_type not in blocked:
            next_keys[troop_type] = candidate_key

    return TrainingActionState(
        runtime_identity_sha256=identity_digest,
        queue_generations=MappingProxyType(generations),
        per_reset_variant_start_counts=MappingProxyType(start_counts),
        per_reset_variant_claim_counts=MappingProxyType(claim_counts),
        prior_daily_initiations=frozenset(
            troop_type
            for troop_type in ("shooter", "rider")
            if start_counts[troop_type] > 0
        ),
        pending_start_action_keys=MappingProxyType(pending),
        pending_start_reset_ids=MappingProxyType(pending_resets),
        next_start_action_keys=MappingProxyType(next_keys),
        blocked_start_variants=MappingProxyType(blocked),
    )


def _finite_epoch(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative epoch")
    return float(value)


def _scheduler_identity_validator(identity: object, utc_clock) -> tuple[Any, Any]:
    from automation_service.recruitment import recruitment_reset
    from tasks.scheduler_task_result import SchedulerIdentity

    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("troop training requires the canonical scheduler task identity")
    binding = resource_fixed_runtime_binding()

    def validate() -> tuple[Any, Any]:
        now = _finite_epoch(utc_clock(), "native identity clock")
        scheduler_reset = recruitment_reset(now)
        backend = derive_resource_runtime_identity(
            binding, datetime.fromtimestamp(now, timezone.utc)
        )
        backend_window = derive_static_utc_reset(datetime.fromtimestamp(now, timezone.utc))
        if (
            identity.account_id != binding.account_id
            or identity.server_id != binding.server_id
            or identity.reset_id != scheduler_reset
            or backend.runtime_scope != binding.runtime_scope
            or backend.account_id != identity.account_id
            or backend.server_id != identity.server_id
            or backend.runtime_binding_digest != binding.binding_digest
            or backend.reset_id != backend_window.reset_identity_id
            or backend_window.reset_start_utc.date().isoformat()
            != identity.reset_id.removeprefix("game-day-")
        ):
            raise ValueError("scheduler identity and fixed-backend UTC reset window disagree")
        return backend, backend_window

    return binding, validate


class TroopTrainingRunner:
    """Device-free service runner for one statically bound native training route."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None,
        output_directory: Path,
        adb: str = str(BLUESTACKS_ADB),
        serial: str = BLUESTACKS_SERIAL,
        utc_clock=time_module.time,
        monotonic_clock=time_module.monotonic,
        settle_seconds: float = 0.75,
    ) -> None:
        self.native = native
        self.output_directory = Path(output_directory)
        self.adb = str(adb)
        self.serial = str(serial)
        self.utc_clock = utc_clock
        self.monotonic_clock = monotonic_clock
        self.settle_seconds = float(settle_seconds)
        if self.adb != str(BLUESTACKS_ADB) or self.serial != BLUESTACKS_SERIAL:
            raise ValueError("troop training is bound to the fixed BlueStacks runtime")
        if not math.isfinite(self.settle_seconds) or self.settle_seconds < 0:
            raise ValueError("troop-training settle interval must be finite and non-negative")

    def __call__(
        self,
        identity: object,
        previous_reset_id: str | None,
        checkpoint,
        *,
        runtime_input_lock,
        occurrence_key: str,
    ) -> Mapping[str, Any]:
        if self.native is None:
            return {
                "flow_id": FLOW_ID,
                "task_id": PRODUCT_ID,
                "native_task_id": FLOW_ID,
                "product_id": PRODUCT_ID,
                "product_revision": PRODUCT_REVISION,
                "status": "blocked",
                "reason": "NATIVE_ROUTE_BOUNDARY_REQUIRED",
                "occurrence_key": occurrence_key,
                "total_input_count": 0,
                "input_count": 0,
                "training_dispatch_count": 0,
                "training_start_transport_calls": 0,
                "claim_dispatch_count": 0,
                "resource_box_dispatch_count": 0,
                "warehouse_dispatch_count": 0,
                "committed_action_count": 0,
                "terminal_home_verified": False,
                "accounting_verified": False,
                "native_execution_verified": False,
                "effect_reconciliation_required": False,
                "identical_retry_denied": False,
            }
        for name, expected in (
            ("flow_id", FLOW_ID),
            ("product_id", PRODUCT_ID),
            ("product_revision", PRODUCT_REVISION),
            ("runtime_profile_id", PROFILE_ID),
            ("max_inputs", MAX_INPUTS),
            ("max_actions", MAX_ACTIONS),
        ):
            if getattr(self.native, name, None) != expected:
                raise ValueError(f"troop-training native binding mismatch for {name}")
        binding, validate_identity = _scheduler_identity_validator(identity, self.utc_clock)
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
        if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
            raise TypeError("troop-training native boundary returned a foreign outcome")
        partial = outcome.partial_result if outcome.failure is not None else None
        native_result = dict(outcome.native_result or partial or {})
        completed_at = _finite_epoch(self.utc_clock(), "native completion clock")
        dispatch_count = _nonnegative_result_count(native_result, "training_dispatch_count")
        start_count = _nonnegative_result_count(native_result, "training_start_transport_calls")
        claim_count = _nonnegative_result_count(native_result, "claim_dispatch_count")
        box_count = _nonnegative_result_count(native_result, "resource_box_dispatch_count")
        warehouse_count = _nonnegative_result_count(native_result, "warehouse_dispatch_count")
        committed_count = _nonnegative_result_count(native_result, "committed_action_count")
        if dispatch_count != start_count + claim_count + box_count + warehouse_count:
            raise ValueError("native troop-training dispatch details do not sum to consequential dispatches")
        if committed_count > dispatch_count:
            raise ValueError("native troop-training confirmed action count exceeds actual dispatches")
        budget_valid = outcome.input_count <= MAX_INPUTS and dispatch_count <= MAX_ACTIONS
        accounting_verified = outcome.accounting_verified and budget_valid
        unresolved = bool(native_result.get("effect_reconciliation_required")) or dispatch_count > committed_count
        if outcome.failure is not None or not budget_valid or not accounting_verified:
            unresolved = unresolved or dispatch_count > committed_count
            status = "unresolved" if unresolved else "blocked"
            if outcome.failure is not None:
                native_result["reason"] = outcome.failure
            elif not budget_valid:
                native_result["reason"] = "NATIVE_TROOP_TRAINING_BUDGET_EXCEEDED"
            else:
                native_result["reason"] = "NATIVE_TROOP_TRAINING_ACCOUNTING_UNVERIFIED"
        else:
            status = str(native_result.get("status", "blocked"))
        result = {
            **native_result,
            "flow_id": FLOW_ID,
            "task_id": PRODUCT_ID,
            "native_task_id": FLOW_ID,
            "product_id": PRODUCT_ID,
            "product_revision": PRODUCT_REVISION,
            "account_id": getattr(identity, "account_id", None),
            "server_id": getattr(identity, "server_id", None),
            "reset_id": getattr(identity, "reset_id", None),
            "backend_runtime_scope": binding.runtime_scope,
            "backend_identity_reset_id": None,
            "backend_runtime_binding_digest": binding.binding_digest,
            "occurrence_key": occurrence_key,
            "status": status,
            "time_basis": "utc",
            "completed_at_utc": completed_at,
            "total_input_count": outcome.input_count,
            "input_count": outcome.input_count,
            "native_input_count": outcome.input_count,
            "session_input_count": outcome.session_input_count,
            "runtime_input_count": outcome.runtime_input_count,
            "accounting_verified": accounting_verified,
            "native_execution_verified": outcome.execution_verified and accounting_verified,
            "native_failure": outcome.failure,
            "native_invocation_id": outcome.invocation_id,
            "session_directory": outcome.session_directory,
            "training_dispatch_count": dispatch_count,
            "training_start_transport_calls": start_count,
            "claim_dispatch_count": claim_count,
            "resource_box_dispatch_count": box_count,
            "warehouse_dispatch_count": warehouse_count,
            "committed_action_count": committed_count,
            "effect_reconciliation_required": unresolved,
            "identical_retry_denied": bool(native_result.get("identical_retry_denied")) or unresolved,
            "terminal_home_verified": bool(native_result.get("terminal_home_verified"))
            and outcome.failure is None
            and accounting_verified,
            "startup_recovery": outcome.startup_recovery,
        }
        try:
            backend, _window = validate_identity()
            result["backend_identity_reset_id"] = backend.reset_id
            result["backend_identity_expires_utc"] = backend.expires_utc
        except Exception as exc:
            result["status"] = "unresolved" if dispatch_count else "blocked"
            result["reason"] = f"IDENTITY_REVALIDATION_FAILED:{exc}"
            result["effect_reconciliation_required"] = bool(dispatch_count)
            result["identical_retry_denied"] = bool(dispatch_count)
            result["terminal_home_verified"] = False
        return result


def _nonnegative_result_count(result: Mapping[str, Any], field: str) -> int:
    value = result.get(field, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"native troop-training {field} must be a non-negative integer")
    return value


def _epoch_in_future(value: object, name: str, completed: float) -> float:
    result = _finite_epoch(value, name)
    if result < completed:
        raise ValueError(f"{name} predates troop-training completion")
    return result


def troop_training_next_due(result: Mapping[str, Any], identity: object, started_at: float) -> float:
    """Schedule from positively observed queue timers or the established next UTC reset."""

    from automation_service.recruitment import recruitment_reset
    from tasks.scheduler_task_result import SchedulerIdentity

    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("troop-training result requires its canonical scheduler identity")
    if (
        result.get("status") not in {"completed", "deferred", "partial"}
        or result.get("flow_id") != FLOW_ID
        or result.get("product_revision") != PRODUCT_REVISION
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("native_execution_verified") is not True
        or result.get("effect_reconciliation_required") is True
        or result.get("identical_retry_denied") is True
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
    ):
        raise ValueError("troop-training outcome requires inspection")
    completed = _finite_epoch(result.get("completed_at_utc"), "completion")
    start = _finite_epoch(started_at, "start")
    if completed < start or recruitment_reset(completed) != identity.reset_id:
        raise ValueError("troop-training completion crossed or mismatched the scheduler reset")
    inputs = _nonnegative_result_count(result, "total_input_count")
    dispatches = _nonnegative_result_count(result, "training_dispatch_count")
    committed = _nonnegative_result_count(result, "committed_action_count")
    if inputs > MAX_INPUTS or dispatches > MAX_ACTIONS or committed > dispatches:
        raise ValueError("troop-training input/action budget is invalid")
    explicit_due = result.get("next_due_utc")
    if explicit_due is not None:
        return _epoch_in_future(explicit_due, "next_due_utc", completed)
    queue_due: list[float] = []
    for item in result.get("training", ()):
        if not isinstance(item, Mapping) or item.get("queue_state") != "active":
            continue
        value = item.get("expected_completion_timestamp")
        if isinstance(value, datetime):
            timestamp = value.timestamp()
        elif type(value) is str:
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError as exc:
                raise ValueError("active troop queue timer is not a valid timestamp") from exc
        else:
            raise ValueError("active troop queue lacks a positively observed timer timestamp")
        queue_due.append(_epoch_in_future(timestamp, "queue completion projection", completed))
    if queue_due:
        return min(queue_due)
    day_text = identity.reset_id.removeprefix("game-day-")
    try:
        reset_date = date.fromisoformat(day_text)
    except ValueError as exc:
        raise ValueError("scheduler game-day reset is not canonical") from exc
    next_reset = datetime.combine(reset_date + timedelta(days=1), time.min, tzinfo=timezone.utc).timestamp()
    if next_reset <= completed:
        raise ValueError("next training reset does not follow the completed run")
    return next_reset


class TroopTrainingExecutionHandler:
    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Troop Training execution requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Troop Training registration identity mismatch")
        if not callable(execute):
            raise TypeError("Troop Training executor must be callable")
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
        return self.recover("TROOP_TRAINING_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("TROOP_TRAINING_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


__all__ = [
    "FLOW_ID",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "HANDLER_ID",
    "PROFILE_ID",
    "MAX_INPUTS",
    "MAX_ACTIONS",
    "RESET_SCOPED",
    "PHASE_MODE",
    "TrainingActionHistoryError",
    "TrainingActionState",
    "training_identity_digest",
    "training_reset_digest",
    "make_training_start_action_key",
    "make_training_claim_action_key",
    "derive_training_action_state",
    "TroopTrainingRunner",
    "TroopTrainingExecutionHandler",
    "troop_training_next_due",
]
