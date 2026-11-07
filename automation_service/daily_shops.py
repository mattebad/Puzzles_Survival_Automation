"""Canonical two-tab Daily Shops adapter over the fixed native boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import time
from types import MappingProxyType
from typing import Any, Mapping
from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from .registry import RegisteredDispatchSnapshot, canonical_entry

from .native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from .registry import (
    DAILY_SHOPS_FLOW_ID as FLOW_ID,
    DAILY_SHOPS_MAX_INPUTS as MAX_INPUTS,
    DAILY_SHOPS_PRODUCT_ID as PRODUCT_ID,
    DAILY_SHOPS_PRODUCT_REVISION as PRODUCT_REVISION,
)
from .recruitment import recruitment_reset
from tasks.purchases_disabled import (
    RARE_EARTH_CURRENCY,
    RARE_EARTH_MODULE_ITEM,
    RARE_EARTH_SHOP,
    RUINS_CHIP_ITEM,
    RUINS_CURRENCY,
    RUINS_SHOP,
    canonical_purchase_action_key,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL, derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity

PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_ACTIONS = 2
RECHECK_SECONDS = 300.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TABS = ("ruins", "rare_earth")


def _epoch(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"Daily Shops {field} must be a finite UTC epoch")
    return float(value)


def _validated_due_context(result: Mapping[str, Any], identity: SchedulerIdentity,
                           started_at: float) -> tuple[float, float]:
    if not isinstance(result, Mapping) or not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Daily Shops outcome requires its exact result and scheduler identity")
    started = _epoch(started_at, "start")
    recorded_start = _epoch(result.get("started_at_utc"), "recorded start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if (recorded_start < started or completed < recorded_start
            or recruitment_reset(started) != identity.reset_id
            or recruitment_reset(completed) != identity.reset_id):
        raise ValueError("Daily Shops outcome crossed or mismatched its scheduler reset")
    if (
        (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or result.get("runtime_profile_id") != PROFILE_ID
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
        or result.get("time_basis") != "utc"
        or not isinstance(result.get("occurrence_key"), str) or not result.get("occurrence_key")
        or result.get("native_failure") is not None
        or result.get("native_execution_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("terminal_home_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
    ):
        raise ValueError("Daily Shops identity, accounting, effect, or Home proof is incomplete")
    counts = tuple(result.get(name) for name in (
        "input_count", "total_input_count", "session_input_count", "runtime_input_count",
    ))
    if (any(type(value) is not int for value in counts) or len(set(counts)) != 1
            or not 0 <= counts[0] <= MAX_INPUTS
            or result.get("max_inputs") != MAX_INPUTS or result.get("max_actions") != MAX_ACTIONS):
        raise ValueError("Daily Shops native and session input accounting differs")
    source = result.get("source_frame")
    if (not isinstance(source, Mapping) or not isinstance(source.get("frame_path"), str)
            or not source.get("frame_path") or not isinstance(source.get("frame_sha256"), str)
            or _SHA256_RE.fullmatch(source["frame_sha256"]) is None):
        raise ValueError("Daily Shops current Home source evidence is missing")
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(completed, timezone.utc))
    backend_result = result.get("backend_identity")
    if (not isinstance(backend_result, Mapping)
            or backend_result.get("runtime_scope") != backend.runtime_scope
            or backend_result.get("account_id") != identity.account_id
            or backend_result.get("server_id") != identity.server_id
            or backend_result.get("backend_reset_id") != backend.reset_id):
        raise ValueError("Daily Shops fixed backend identity proof is incomplete")
    reset_start = datetime.fromtimestamp(completed, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return completed, (reset_start + timedelta(days=1)).timestamp()


def _validate_tab_offer(row: Mapping[str, Any], tab: str, *, no_work: bool) -> None:
    expected = {
        "ruins": (RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY),
        "rare_earth": (RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY),
    }[tab]
    price, balance, stock = row.get("unit_price"), row.get("balance_before"), row.get("stock_before")
    quantity = row.get("quantity")
    if (
        row.get("shop_identity") != expected[0] or row.get("item_identity") != expected[1]
        or row.get("currency_identity") != expected[2] or row.get("rarity") != 3
        or not isinstance(row.get("offer_identity"), str) or not row["offer_identity"]
        or type(price) is not int or price <= 0
        or type(balance) is not int or balance < 0
        or type(stock) is not int or stock < 0
        or type(row.get("item_quantity_before")) is not int or row["item_quantity_before"] < 0
        or type(quantity) is not int
        or not isinstance(row.get("source_frame_ref"), str) or not row["source_frame_ref"]
        or not isinstance(row.get("source_frame_sha256"), str)
        or _SHA256_RE.fullmatch(row["source_frame_sha256"]) is None
    ):
        raise ValueError("Daily Shops tab lacks current numeric offer/source evidence")
    affordable = min(stock, balance // price)
    if no_work:
        if quantity != 0 or affordable != 0 or row.get("total") is not None:
            raise ValueError("Daily Shops deferred tab is affordable or has inconsistent totals")
    elif (quantity <= 0 or quantity != affordable
          or type(row.get("total")) is not int or row["total"] != quantity * price):
        raise ValueError("Daily Shops purchase is not maximum-affordable and stock-capped")


def daily_shops_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Admit two reconciled tabs, a restart-safe partial visit, or exact no-work tabs."""
    completed, reset_due = _validated_due_context(result, identity, started_at)
    if result.get("effect_reconciliation_required") is not False or result.get("identical_retry_denied") is not False:
        raise ValueError("Daily Shops purchase effect is unknown")
    tabs = result.get("tab_results")
    if not isinstance(tabs, Mapping) or set(tabs) != set(_TABS):
        raise ValueError("Daily Shops per-tab results are incomplete")
    expected_keys = {
        "ruins": canonical_purchase_action_key(FLOW_ID, PRODUCT_ID, identity, "ruins_shop"),
        "rare_earth": canonical_purchase_action_key(FLOW_ID, PRODUCT_ID, identity, "rare_earth_shop"),
    }
    confirmed = already_confirmed = deferred = 0
    for tab in _TABS:
        row = tabs.get(tab)
        if not isinstance(row, Mapping) or row.get("action_key") != expected_keys[tab]:
            raise ValueError("Daily Shops tab action identity is not reset-stable")
        status = row.get("status")
        if status == "confirmed":
            confirmed += 1
            if row.get("effect_verified") is not True:
                raise ValueError("Daily Shops newly confirmed tab lacks paired effect proof")
            _validate_tab_offer(row, tab, no_work=False)
        elif status == "already_confirmed":
            already_confirmed += 1
            if row.get("effect_verified") is not True:
                raise ValueError("Daily Shops restart tab lacks paired effect proof")
        elif status == "deferred":
            deferred += 1
            if row.get("effect_verified") is not False:
                raise ValueError("Daily Shops deferred tab cannot claim a verified effect")
            if row.get("reason") == "TAB_NO_AFFORDABLE_STOCK":
                _validate_tab_offer(row, tab, no_work=True)
            elif row.get("reason") == "TAB_ITEM_EFFECT_EVIDENCE_REQUIRED":
                source_ref, source_hash = row.get("source_frame_ref"), row.get("source_frame_sha256")
                if (
                    type(row.get("quantity")) is not int or row["quantity"] != 0
                    or row.get("total") is not None
                    or any(row.get(field) is not None for field in (
                        "offer_identity", "shop_identity", "item_identity", "currency_identity",
                        "rarity", "unit_price", "balance_before", "stock_before", "item_quantity_before",
                    ))
                    or not isinstance(source_ref, str) or not source_ref.strip()
                    or not isinstance(source_hash, str) or _SHA256_RE.fullmatch(source_hash) is None
                ):
                    raise ValueError("Daily Shops unproved tab requires retained source and zero purchase")
            else:
                raise ValueError("Daily Shops deferred tab lacks an exact no-work or evidence-required reason")
        else:
            raise ValueError("Daily Shops tab is blocked or unresolved")
    calls = result.get("purchase_transport_calls")
    committed = result.get("committed_action_count")
    if (type(calls) is not int or type(committed) is not int or calls != committed
            or committed != confirmed or confirmed + already_confirmed > MAX_ACTIONS
            or not 0 <= calls <= MAX_ACTIONS):
        raise ValueError("Daily Shops durable tab and transport counts differ")
    status = result.get("status")
    if status == "complete_for_reset":
        if confirmed + already_confirmed != MAX_ACTIONS or deferred:
            raise ValueError("Daily Shops reset completion requires both exact tabs")
        return reset_due
    if status != "deferred" or deferred == 0:
        raise ValueError("Daily Shops result is neither full completion nor a known partial/no-work visit")
    return min(completed + RECHECK_SECONDS, reset_due)



class DailyShopsRunner:
    """Preserve each shop tab's canonical daily action across service pulses."""

    def __init__(self, *, native: NativeRouteBoundary | None = None,
                 adb: str = str(BLUESTACKS_ADB), serial: str = BLUESTACKS_SERIAL,
                 output_directory: Path, utc_clock=time.time,
                 monotonic_clock=time.monotonic, settle_seconds=1.0):
        self.native = native
        self.adb, self.serial = str(adb), serial
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        if type(settle_seconds) not in (int, float) or not 0 <= float(settle_seconds) <= 5:
            raise ValueError("Daily Shops settle delay must be bounded")
        self.settle_seconds = float(settle_seconds)
        if native is not None and (
            native.flow_id != FLOW_ID or native.product_id != PRODUCT_ID
            or native.product_revision != PRODUCT_REVISION
            or native.runtime_profile_id != PROFILE_ID
            or native.max_inputs != MAX_INPUTS or native.max_actions != MAX_ACTIONS
        ):
            raise ValueError("Daily Shops native binding identity mismatch")

    def __call__(self, identity: SchedulerIdentity, previous_reset_id: str | None,
                 checkpoint, *, runtime_input_lock, occurrence_key: str) -> Mapping[str, Any]:
        try:
            return self._execute(
                identity, previous_reset_id, checkpoint,
                runtime_input_lock=runtime_input_lock, occurrence_key=occurrence_key,
            )
        except Exception as exc:
            started = None
            try:
                started = self._epoch(self.utc_clock(), "start")
            except (TypeError, ValueError, OverflowError):
                pass
            partial = getattr(exc, "partial_result", None)
            result = self._blocked(
                identity, previous_reset_id, occurrence_key, started,
                f"DAILY_SHOPS_NATIVE_FAILURE:{type(exc).__name__}",
            )
            if isinstance(partial, Mapping):
                result.update(partial)
            calls = result.get("purchase_transport_calls", 0)
            unknown = bool(result.get("effect_reconciliation_required") is True
                           or type(calls) is not int or calls > 0)
            result.update(
                status="unresolved" if unknown else "blocked",
                native_execution_verified=False,
                native_failure=str(exc),
                effect_reconciliation_required=unknown,
                identical_retry_denied=unknown,
            )
            return result

    def _execute(self, identity: SchedulerIdentity, previous_reset_id: str | None,
                 checkpoint, *, runtime_input_lock, occurrence_key: str) -> Mapping[str, Any]:
        started = self._epoch(self.utc_clock(), "start")
        backend = self._validate_identity(identity, started)
        if (self.adb, self.serial) != (str(BLUESTACKS_ADB), BLUESTACKS_SERIAL):
            raise ValueError("Daily Shops runtime differs from its fixed BlueStacks binding")
        if (getattr(runtime_input_lock, "owner", None) != "automation-service"
                or not isinstance(getattr(runtime_input_lock, "invocation_id", None), str)
                or not runtime_input_lock.invocation_id or not callable(checkpoint)):
            raise ValueError("Daily Shops requires the canonical held runtime owner")
        if not isinstance(occurrence_key, str) or not occurrence_key.strip():
            raise ValueError("Daily Shops service occurrence key is required")
        runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
        action_keys = {
            "ruins": canonical_purchase_action_key(FLOW_ID, PRODUCT_ID, identity, "ruins_shop"),
            "rare_earth": canonical_purchase_action_key(FLOW_ID, PRODUCT_ID, identity, "rare_earth_shop"),
        }
        if self.native is None:
            return self._blocked(identity, previous_reset_id, occurrence_key, started,
                                 "DAILY_SHOPS_NATIVE_BINDING_UNAVAILABLE")

        def validate_identity():
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            checkpoint()
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            self._validate_identity(identity, self._epoch(self.utc_clock(), "identity checkpoint"))

        request = NativeRouteRequest(
            flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            runtime_profile_id=PROFILE_ID, identity=identity,
            previous_reset_id=previous_reset_id, occurrence_key=occurrence_key,
            checkpoint=checkpoint, validate_identity=validate_identity,
            runtime_input_lock=runtime_input_lock, adb=self.adb, serial=self.serial,
            output_directory=self.output_directory, max_inputs=MAX_INPUTS,
            max_actions=MAX_ACTIONS, settle_seconds=self.settle_seconds,
            arguments=MappingProxyType({"action_keys": action_keys, "backend_identity": backend}),
            utc_clock=self.utc_clock, monotonic_clock=self.monotonic_clock,
        )
        outcome = self.native.run(request)
        if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
            raise TypeError("Daily Shops native binding returned an invalid outcome")
        result = dict(outcome.partial_result or {})
        result.update(dict(outcome.native_result or {}))
        completed = self._epoch(self.utc_clock(), "completion")
        input_count = outcome.input_count
        accounting_counts_valid = (
            type(input_count) is int and type(outcome.session_input_count) is int
            and type(outcome.runtime_input_count) is int
            and input_count == outcome.session_input_count == outcome.runtime_input_count
            and 0 <= input_count <= MAX_INPUTS
        )
        accounting = bool(
            outcome.accounting_verified is True and accounting_counts_valid
            and result.get("accounting_verified") is True
            and result.get("total_input_count") == input_count
        )
        tabs = result.get("tab_results")
        statuses = [
            row.get("status") for row in tabs.values() if isinstance(row, Mapping)
        ] if isinstance(tabs, Mapping) else []
        native_status = result.get("status")
        if outcome.failure is not None:
            calls = result.get("purchase_transport_calls", 0)
            committed = result.get("committed_action_count", 0)
            unknown = bool(result.get("effect_reconciliation_required") is True
                           or type(calls) is not int or type(committed) is not int or calls > committed)
            if unknown:
                result["effect_reconciliation_required"] = True
                if type(calls) is int and calls > 0:
                    result["identical_retry_denied"] = True
            status = "unresolved" if unknown else "blocked"
        elif result.get("effect_reconciliation_required") is True or "unresolved" in statuses:
            status = "unresolved"
        elif (not isinstance(tabs, Mapping) or set(tabs) != set(_TABS)
              or len(statuses) != MAX_ACTIONS
              or any(value not in {"confirmed", "already_confirmed", "deferred", "blocked", "unresolved"}
                     for value in statuses)):
            status = "blocked"
        elif "blocked" in statuses:
            status = "blocked"
        elif (result.get("terminal_home_verified") is True and accounting
              and all(value in {"confirmed", "already_confirmed"} for value in statuses)
              and all(row.get("effect_verified") is True for row in tabs.values())):
            status = "complete_for_reset"
        elif "deferred" in statuses:
            status = "deferred"
        else:
            status = "blocked"
        if status != native_status:
            result.setdefault("native_status", native_status)
        result.setdefault("flow_id", FLOW_ID)
        result.setdefault("product_id", PRODUCT_ID)
        result.setdefault("product_revision", PRODUCT_REVISION)
        result.setdefault("task_id", PRODUCT_ID)
        result.setdefault("account_id", identity.account_id)
        result.setdefault("server_id", identity.server_id)
        result.setdefault("reset_id", identity.reset_id)
        result.setdefault("previous_reset_id", previous_reset_id)
        result.setdefault("occurrence_key", occurrence_key)
        result.setdefault("runtime_profile_id", PROFILE_ID)
        result.setdefault("time_basis", "utc")
        result.setdefault("started_at_utc", started)
        result.setdefault("completed_at_utc", completed)
        result["status"] = status
        result["input_count"] = input_count
        result.setdefault("max_inputs", MAX_INPUTS)
        result.setdefault("max_actions", MAX_ACTIONS)
        result["session_input_count"] = outcome.session_input_count
        result["runtime_input_count"] = outcome.runtime_input_count
        result["accounting_verified"] = accounting
        result["native_execution_verified"] = outcome.execution_verified is True
        result.setdefault("native_failure", outcome.failure)
        result.setdefault("backend_identity", {
            "runtime_scope": backend.runtime_scope, "account_id": backend.account_id,
            "server_id": backend.server_id, "backend_reset_id": backend.reset_id,
        })
        return result

    @staticmethod
    def _epoch(value, field):
        if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"Daily Shops {field} must be a finite UTC epoch")
        return float(value)

    @staticmethod
    def _validate_identity(identity, now):
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Daily Shops scheduler identity mismatch")
        if identity.reset_id != recruitment_reset(now):
            raise ValueError("Daily Shops scheduler reset identity is not current")
        binding = resource_fixed_runtime_binding()
        backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
        if (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id):
            raise ValueError("Daily Shops scheduler identity differs from the fixed backend")
        return backend

    @staticmethod
    def _blocked(identity, previous_reset_id, occurrence_key, started, reason):
        return {
            "status": "blocked", "reason": reason, "flow_id": FLOW_ID,
            "product_id": PRODUCT_ID, "product_revision": PRODUCT_REVISION,
            "task_id": PRODUCT_ID,
            "account_id": getattr(identity, "account_id", None),
            "server_id": getattr(identity, "server_id", None),
            "reset_id": getattr(identity, "reset_id", None),
            "previous_reset_id": previous_reset_id,
            "occurrence_key": occurrence_key, "runtime_profile_id": PROFILE_ID,
            "time_basis": "utc", "started_at_utc": started,
            "completed_at_utc": started, "max_inputs": MAX_INPUTS,
            "max_actions": MAX_ACTIONS, "input_count": 0,
            "total_input_count": 0, "session_input_count": 0,
            "runtime_input_count": 0, "accounting_verified": False,
            "native_execution_verified": False, "native_failure": reason,
            "terminal_home_verified": False, "effect_reconciliation_required": False,
            "identical_retry_denied": False, "purchase_transport_calls": 0,
            "committed_action_count": 0,
        }


class DailyShopsExecutionHandler:
    """Canonical dispatch handler; all execution is delegated to the injected runner."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Daily Shops requires a typed registered dispatch snapshot")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Daily Shops registration identity mismatch")
        if not callable(execute):
            raise TypeError("Daily Shops executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Daily Shops requires its matching route specification")
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
        return self.recover("DAILY_SHOPS_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("DAILY_SHOPS_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


__all__ = [
    "DailyShopsExecutionHandler",
    "DailyShopsRunner",
    "FLOW_ID",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "daily_shops_next_due",
]
