"""Canonical Resource-item service adapter over the fixed native route boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path, PurePosixPath
import re
import time
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from .registry import (
    RESOURCE_ITEM_FLOW_ID,
    RESOURCE_ITEM_MAX_INPUTS,
    RESOURCE_ITEM_PRODUCT_ID,
    RESOURCE_ITEM_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from .recruitment import recruitment_reset
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity


FLOW_ID = RESOURCE_ITEM_FLOW_ID
PRODUCT_ID = RESOURCE_ITEM_PRODUCT_ID
PRODUCT_REVISION = RESOURCE_ITEM_PRODUCT_REVISION
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = RESOURCE_ITEM_MAX_INPUTS
MAX_ACTIONS = 1
_RESOURCE_OCCURRENCE_KEY_RE = re.compile(r"^occ:v1:[0-9a-f]{64}$")
_RESOURCE_ACTION_KEY_RE = re.compile(
    r"^(occ:v1:[0-9a-f]{64}):effect:1:generation:([1-9][0-9]*)$"
)
_RESOURCE_ACTION_ID_RE = re.compile(r"^resource-action:v1:[0-9a-f]{64}$")
_RESOURCE_OCCURRENCE_ID_RE = re.compile(r"^occurrence:v1:[0-9a-f]{64}$")
_RESOURCE_RESERVATION_ID_RE = re.compile(r"^reservation:v1:[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResourceItemExecutionHandler:
    """Installable fixed reset-scoped Resource item execution handler."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Resource-item execution requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Resource-item registration identity mismatch")
        if not callable(execute):
            raise TypeError("Resource-item executor must be callable")
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
        return self.recover("RESOURCE_ITEM_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return (
            plan
            if isinstance(plan, NormalizedResult)
            else self.recover("RESOURCE_ITEM_UNKNOWN_RESULT")
        )

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class ResourceItemRunnerError(RuntimeError):
    """A route failure retaining its native partial result and exact accounting."""

    def __init__(self, reason: str, *, partial_result: Mapping[str, Any]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Resource-item {field} must be a finite UTC epoch")
    return float(value)


def _resource_backend_window(identity: SchedulerIdentity, epoch: float):
    """Validate scheduler and fixed-backend reset windows at one UTC sample."""
    if recruitment_reset(epoch) != identity.reset_id:
        raise ValueError("Resource-item scheduler identity is outside its UTC reset")
    evaluated = datetime.fromtimestamp(epoch, timezone.utc)
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(binding, evaluated)
    window = derive_static_utc_reset(evaluated)
    if (
        backend.reset_id != window.reset_identity_id
        or backend.reset_start_utc != window.reset_start_text
        or backend.reset_deadline_utc != window.reset_deadline_text
        or backend.account_id != identity.account_id
        or backend.server_id != identity.server_id
    ):
        raise ValueError("Resource-item scheduler and fixed-backend identities do not share one reset window")
    return backend, window


def _utc_timestamp(value: object, field: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"Resource-item {field} must be an exact UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Resource-item {field} must be an exact UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"Resource-item {field} must be timezone-aware UTC")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError(f"Resource-item {field} is not canonical UTC")
    return parsed


def _frame_ref(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Resource-item {field} frame evidence is missing")
    path, digest = value.get("path"), value.get("sha256")
    if (
        type(path) is not str
        or not path
        or path != path.strip()
        or "\\" in path
        or PurePosixPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts)
        or type(digest) is not str
        or _SHA256_RE.fullmatch(digest) is None
    ):
        raise ValueError(f"Resource-item {field} frame reference is invalid")
    return value


def resource_item_next_due(
    result: Mapping[str, Any],
    identity: SchedulerIdentity,
    started_at: float,
    occurrence_key: str,
) -> float:
    """Admit one exact confirmed owned-item decrement and return next UTC reset."""
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Resource-item outcome requires its exact task identity")
    if type(occurrence_key) is not str or not occurrence_key or occurrence_key != occurrence_key.strip():
        raise ValueError("Resource-item service occurrence key is invalid")
    if result.get("occurrence_key") != occurrence_key:
        raise ValueError("Resource-item result lost its service occurrence key")
    if (
        result.get("status") != "complete_for_reset"
        or result.get("flow_id") != FLOW_ID
        or result.get("product_id") != PRODUCT_ID
        or result.get("product_revision") != PRODUCT_REVISION
        or result.get("task_id") != PRODUCT_ID
        or result.get("max_actions") != MAX_ACTIONS
        or result.get("time_basis") != "utc"
        or result.get("accounting_verified") is not True
        or result.get("resource_delta_verified") is not True
        or result.get("terminal_home_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
        or result.get("reservation_state") != "EFFECT_CONFIRMED"
        or result.get("resource_effect_state") != "CONFIRMED"
        or result.get("journal_status") != "confirmed"
        or result.get("terminal_observation_state") != "HOME_CANONICAL"
        or result.get("action_task_id") != FLOW_ID
        or result.get("action_semantic_action") != "USE_RESOURCE_ITEM"
        or result.get("action_source_state") != "RESOURCES_1K_FOOD_READY"
        or result.get("action_target_identity") != "daily-resource-item:use-1k-food"
        or result.get("action_expected_postcondition") != "RESOURCES_1K_FOOD_USED"
        or result.get("action_consequence") != "ordinary_non_idempotent_resource_item_use"
        or result.get("action_cost_type") != "owned_inventory_item"
        or type(result.get("action_cost_amount")) not in (int, float)
        or isinstance(result.get("action_cost_amount"), bool)
        or float(result.get("action_cost_amount")) != 1.0
        or result.get("action_quantity") != 1
    ):
        raise ValueError("Resource-item outcome requires one confirmed owned-item effect and canonical Home")
    if (
        result.get("account_id"),
        result.get("server_id"),
        result.get("reset_id"),
    ) != (identity.account_id, identity.server_id, identity.reset_id):
        raise ValueError("Resource-item result identity mismatch")
    started = _epoch(started_at, "start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if completed < started or recruitment_reset(completed) != identity.reset_id:
        raise ValueError("Resource-item completion is outside its current game-day")
    backend, window = _resource_backend_window(identity, started)
    completed_backend, completed_window = _resource_backend_window(identity, completed)
    backend_start = _utc_timestamp(result.get("resource_reset_start_utc"), "Resource reset start")
    backend_deadline = _utc_timestamp(result.get("resource_reset_deadline_utc"), "Resource reset deadline")
    backend_reset_id = window.reset_identity_id
    if (
        completed_backend.reset_id != backend_reset_id
        or completed_window.reset_identity_id != backend_reset_id
        or result.get("resource_account_id") != backend.account_id
        or result.get("resource_server_id") != backend.server_id
        or result.get("resource_identity_assurance")
        != "fixed_runtime_binding_static_utc_reset"
        or result.get("resource_backend_identity_reset_id") != backend_reset_id
        or backend_start != window.reset_start_utc
        or backend_deadline != window.reset_deadline_utc
        or result.get("resource_reset_identity_id") != backend_reset_id
        or result.get("action_game_day_id") != backend_reset_id
    ):
        raise ValueError("Resource-item fixed-backend reset proof does not match this service occurrence")

    count = result.get("total_input_count")
    if type(count) is not int or not 0 <= count <= MAX_INPUTS:
        raise ValueError("Resource-item input budget is invalid")
    if result.get("input_count") != count or result.get("max_inputs") != MAX_INPUTS:
        raise ValueError("Resource-item native input accounting is inconsistent")
    for field in ("session_input_count", "runtime_input_count"):
        if type(result.get(field)) is not int or result[field] != count:
            raise ValueError(f"Resource-item {field} differs from total input accounting")
    if result.get("item_use_transport_calls") != 1 or result.get("committed_action_count") != 1:
        raise ValueError("Resource-item must account for exactly one committed Use effect")
    if result.get("action_count") != 1:
        raise ValueError("Resource-item action accounting is not exactly one")

    before, after = result.get("before_owned_quantity"), result.get("after_owned_quantity")
    if (
        type(before) is not int
        or type(after) is not int
        or before < 1
        or after != before - 1
        or result.get("owned_item_decrement") != 1
    ):
        raise ValueError("Resource-item owned quantity did not decrement by exactly one")
    _frame_ref(result.get("terminal_home_frame"), "terminal Home")
    semantic = result.get("semantic_evidence")
    if not isinstance(semantic, Mapping):
        raise ValueError("Resource-item semantic evidence is missing")
    _frame_ref(semantic.get("item_before_frame"), "before-item")
    _frame_ref(semantic.get("item_after_frame"), "after-item")
    semantic_home = _frame_ref(semantic.get("terminal_home_frame"), "semantic terminal Home")
    top_home = _frame_ref(result.get("terminal_home_frame"), "terminal Home")
    if semantic_home.get("sha256") != top_home.get("sha256"):
        raise ValueError("Resource-item terminal Home frame references disagree")

    resource_key = result.get("resource_occurrence_key")
    action_key = result.get("action_key")
    key_match = _RESOURCE_ACTION_KEY_RE.fullmatch(action_key) if type(action_key) is str else None
    if (
        type(resource_key) is not str
        or _RESOURCE_OCCURRENCE_KEY_RE.fullmatch(resource_key) is None
        or key_match is None
        or key_match.group(1) != resource_key
        or type(result.get("resource_occurrence_id")) is not str
        or _RESOURCE_OCCURRENCE_ID_RE.fullmatch(result["resource_occurrence_id"]) is None
        or type(result.get("resource_action_key")) is not str
        or result["resource_action_key"] != action_key
        or type(result.get("action_id")) is not str
        or _RESOURCE_ACTION_ID_RE.fullmatch(result["action_id"]) is None
        or result.get("resource_action_id") != result.get("action_id")
        or type(result.get("reservation_id")) is not str
        or _RESOURCE_RESERVATION_ID_RE.fullmatch(result["reservation_id"]) is None
        or type(result.get("resource_attempt_id")) is not str
        or not result["resource_attempt_id"].startswith("attempt:v1:")
    ):
        raise ValueError("Resource-item canonical effect identities are incomplete or inconsistent")
    return max(completed, backend_deadline.timestamp())


def normalize_resource_item_result(
    result: Mapping[str, Any],
    identity: SchedulerIdentity,
    started_at: float,
    occurrence_key: str,
) -> NormalizedResult:
    """Translate only fully reconciled Resource evidence to reset completion."""
    try:
        due = resource_item_next_due(result, identity, started_at, occurrence_key)
    except (TypeError, ValueError, OverflowError) as exc:
        attempted = bool(
            result.get("item_use_transport_calls")
            or result.get("committed_action_count")
            or result.get("reservation_id")
            or result.get("effect_reconciliation_required")
        )
        return NormalizedResult(
            NormalizedOutcome.RECONCILIATION_REQUIRED if attempted else NormalizedOutcome.BLOCKED,
            "RESOURCE_ITEM_RECONCILIATION_REQUIRED" if attempted else "RESOURCE_ITEM_BLOCKED",
            action_count=1 if attempted else 0,
            verified=False,
            observed_progress={
                "status": result.get("status"),
                "reason": str(exc),
                "occurrence_key": result.get("occurrence_key"),
                "resource_reset_identity_id": result.get("resource_reset_identity_id"),
            },
            consequence={"item": "1k_food", "quantity": 1},
            evidence_refs=tuple(
                f"frame:{frame['sha256']}"
                for frame in (
                    result.get("terminal_home_frame"),
                    (result.get("semantic_evidence") or {}).get("item_before_frame")
                    if isinstance(result.get("semantic_evidence"), Mapping)
                    else None,
                    (result.get("semantic_evidence") or {}).get("item_after_frame")
                    if isinstance(result.get("semantic_evidence"), Mapping)
                    else None,
                )
                if isinstance(frame, Mapping) and type(frame.get("sha256")) is str
            ),
        )
    return NormalizedResult(
        NormalizedOutcome.COMPLETE_FOR_RESET,
        "RESOURCE_ITEM_EFFECT_CONFIRMED",
        action_count=1,
        verified=True,
        next_eligible_at=due,
        observed_progress={
            "occurrence_key": occurrence_key,
            "resource_occurrence_key": result["resource_occurrence_key"],
            "before_owned_quantity": result["before_owned_quantity"],
            "after_owned_quantity": result["after_owned_quantity"],
            "resource_reset_identity_id": result["resource_reset_identity_id"],
        },
        consequence={"item": "1k_food", "quantity": 1, "owned_item_decrement": 1},
        evidence_refs=tuple(
            f"frame:{frame['sha256']}"
            for frame in (
                result["terminal_home_frame"],
                result["semantic_evidence"]["item_before_frame"],
                result["semantic_evidence"]["item_after_frame"],
            )
        ),
    )


class ResourceItemRunner:
    """Call one fixed native binding under the service-owned runtime/input lease."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None = None,
        adb: str = str(BLUESTACKS_ADB),
        serial: str = BLUESTACKS_SERIAL,
        output_directory: Path,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 1.0,
    ):
        self.native = native
        self.adb, self.serial = str(adb), serial
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")
        if native is not None and (
            native.flow_id != FLOW_ID
            or native.product_id != PRODUCT_ID
            or native.product_revision != PRODUCT_REVISION
            or native.runtime_profile_id != PROFILE_ID
            or native.max_inputs != MAX_INPUTS
            or native.max_actions != MAX_ACTIONS
        ):
            raise ValueError("Resource-item native binding identity mismatch")

    def __call__(
        self,
        identity: SchedulerIdentity,
        previous_reset_id: str | None,
        checkpoint,
        *,
        runtime_input_lock,
        occurrence_key: str,
    ) -> dict[str, Any]:
        started = _epoch(self.utc_clock(), "start")
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Resource-item task identity mismatch")
        _resource_backend_window(identity, started)
        if type(occurrence_key) is not str or not occurrence_key or occurrence_key != occurrence_key.strip():
            raise ValueError("Resource-item service occurrence key is invalid")
        # `previous_reset_id` is carried unchanged into the native boundary.
        if (
            getattr(runtime_input_lock, "owner", None) != "automation-service"
            or not isinstance(getattr(runtime_input_lock, "invocation_id", None), str)
            or not runtime_input_lock.invocation_id
            or not callable(checkpoint)
        ):
            raise ValueError("Resource-item requires the canonical held owner and checkpoint")
        runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
        if self.native is None:
            return _blocked_result(
                identity,
                previous_reset_id,
                occurrence_key,
                started,
                "Resource-item native route binding is unavailable",
            )
        if (self.adb, self.serial) != (str(BLUESTACKS_ADB), BLUESTACKS_SERIAL):
            raise ValueError("Resource-item runtime configuration differs from its fixed BlueStacks binding")

        def validate_identity() -> None:
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            checkpoint()
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            now = _epoch(self.utc_clock(), "identity checkpoint")
            if identity.task_id != PRODUCT_ID:
                raise ValueError("Resource-item scheduler identity changed during native execution")
            _resource_backend_window(identity, now)

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
            utc_clock=self.utc_clock,
            monotonic_clock=self.monotonic_clock,
            settle_seconds=self.settle_seconds,
            arguments=MappingProxyType({}),
        )
        outcome: NativeRouteOutcome | None = None
        failure: str | None = None
        exception_partial: Mapping[str, Any] = {}
        try:
            validate_identity()
            outcome = self.native.run(request)
            if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
                raise TypeError("Resource-item native binding returned an invalid outcome")
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            candidate = getattr(exc, "partial_result", {})
            exception_partial = candidate if isinstance(candidate, Mapping) else {}
            outcome = getattr(exc, "partial_outcome", None)

        partial = outcome.partial_result if isinstance(outcome, NativeRouteOutcome) else {}
        native_result = outcome.native_result if isinstance(outcome, NativeRouteOutcome) else {}
        result: dict[str, Any] = dict(exception_partial)
        if isinstance(partial, Mapping):
            result.update(partial)
        if isinstance(native_result, Mapping):
            result.update(native_result)

        completed = _epoch(self.utc_clock(), "completion")
        calls = result.get("item_use_transport_calls", 0)
        calls = calls if type(calls) is int and calls >= 0 else 0
        attempted = bool(calls or result.get("reservation_id") or result.get("effect_reconciliation_required"))
        accounting = bool(
            isinstance(outcome, NativeRouteOutcome)
            and outcome.accounting_verified is True
            and result.get("accounting_verified") is True
            and type(outcome.input_count) is int
            and 0 <= outcome.input_count <= MAX_INPUTS
            and outcome.session_input_count == outcome.input_count
            and outcome.runtime_input_count == outcome.input_count
            and result.get("total_input_count", outcome.input_count) == outcome.input_count
        )
        result.update(
            flow_id=FLOW_ID,
            product_id=PRODUCT_ID,
            product_revision=PRODUCT_REVISION,
            task_id=PRODUCT_ID,
            account_id=identity.account_id,
            server_id=identity.server_id,
            reset_id=identity.reset_id,
            previous_reset_id=previous_reset_id,
            occurrence_key=occurrence_key,
            time_basis="utc",
            started_at_utc=started,
            completed_at_utc=completed,
            max_inputs=MAX_INPUTS,
            max_actions=MAX_ACTIONS,
            total_input_count=(
                outcome.input_count if isinstance(outcome, NativeRouteOutcome)
                else result.get("total_input_count", 0)
            ),
            input_count=(
                outcome.input_count if isinstance(outcome, NativeRouteOutcome)
                else result.get("input_count", 0)
            ),
            session_input_count=(
                outcome.session_input_count if isinstance(outcome, NativeRouteOutcome)
                else result.get("session_input_count", 0)
            ),
            runtime_input_count=(
                outcome.runtime_input_count if isinstance(outcome, NativeRouteOutcome)
                else result.get("runtime_input_count", 0)
            ),
            accounting_verified=accounting,
            native_invocation_id=(outcome.invocation_id if isinstance(outcome, NativeRouteOutcome) else None),
            session_directory=(outcome.session_directory if isinstance(outcome, NativeRouteOutcome) else None),
        )
        if isinstance(outcome, NativeRouteOutcome) and outcome.failure:
            failure = failure or str(outcome.failure)
        if failure:
            result["reason"] = failure
            result["status"] = "unresolved" if attempted else "blocked"
            result["effect_reconciliation_required"] = attempted
            result["identical_retry_denied"] = attempted
        elif not accounting:
            result["reason"] = "Resource-item native input accounting is not exact"
            result["status"] = "unresolved" if attempted else "blocked"
            result["effect_reconciliation_required"] = attempted
            result["identical_retry_denied"] = attempted
        try:
            due = resource_item_next_due(result, identity, started, occurrence_key)
        except (TypeError, ValueError, OverflowError) as exc:
            if result.get("status") == "complete_for_reset":
                result["reason"] = str(exc)
                result["status"] = "unresolved" if attempted else "blocked"
                result["effect_reconciliation_required"] = attempted
                result["identical_retry_denied"] = attempted
            return result
        result["next_eligible_at_utc"] = due
        result["next_reset_at_utc"] = due
        return result


def _blocked_result(
    identity: SchedulerIdentity,
    previous_reset_id: str | None,
    occurrence_key: str,
    started_at: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": reason,
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "task_id": PRODUCT_ID,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "previous_reset_id": previous_reset_id,
        "occurrence_key": occurrence_key,
        "time_basis": "utc",
        "started_at_utc": started_at,
        "completed_at_utc": started_at,
        "max_inputs": MAX_INPUTS,
        "max_actions": MAX_ACTIONS,
        "total_input_count": 0,
        "input_count": 0,
        "session_input_count": 0,
        "runtime_input_count": 0,
        "item_use_transport_calls": 0,
        "committed_action_count": 0,
        "action_count": 0,
        "accounting_verified": False,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
    }


__all__ = [
    "FLOW_ID",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "ResourceItemExecutionHandler",
    "ResourceItemRunner",
    "ResourceItemRunnerError",
    "normalize_resource_item_result",
    "resource_item_next_due",
]
