"""Canonical Alliance Shop adapter over the fixed native execution boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping
from .contracts import (
    FlowDescriptor, FlowSpec, NormalizedOutcome, NormalizedResult,
    PerceptionEnvelope, SchedulerFacts,
)
from .registry import RegisteredDispatchSnapshot, canonical_entry
from .state import RunRecord

from .native_execution import (
    NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest, RuntimeInputLockPort,
)
from .registry import (
    ALLIANCE_SHOP_FLOW_ID as FLOW_ID,
    ALLIANCE_SHOP_MAX_INPUTS as MAX_INPUTS,
    ALLIANCE_SHOP_PRODUCT_ID as PRODUCT_ID,
    ALLIANCE_SHOP_PRODUCT_REVISION as PRODUCT_REVISION,
)
from tasks.purchases_disabled import (
    ALLIANCE_CURRENCY,
    ALLIANCE_FALLBACK_ITEM,
    ALLIANCE_OTHER_SHOP,
    ALLIANCE_WEEKLY_ITEMS,
    ALLIANCE_WEEKLY_SHOP,
    canonical_purchase_action_key,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    VerifiedRuntimeIdentity,
    derive_resource_runtime_identity,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity
from .recruitment import recruitment_reset

PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_ACTIONS = 1
RECHECK_SECONDS = 300.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _epoch(value: object, field: str) -> float:
    if (not isinstance(value, (int, float)) or type(value) not in (int, float)
            or not math.isfinite(float(value)) or value < 0):
        raise ValueError(f"Alliance Shop {field} must be a finite UTC epoch")
    return float(value)


def _validated_due_context(result: Mapping[str, Any], identity: SchedulerIdentity,
                           started_at: float) -> tuple[float, float]:
    if not isinstance(result, Mapping) or not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Alliance Shop outcome requires its exact result and scheduler identity")
    started = _epoch(started_at, "start")
    recorded_start = _epoch(result.get("started_at_utc"), "recorded start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if (recorded_start < started or completed < recorded_start
            or recruitment_reset(started) != identity.reset_id
            or recruitment_reset(completed) != identity.reset_id):
        raise ValueError("Alliance Shop outcome crossed or mismatched its scheduler reset")
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
        raise ValueError("Alliance Shop identity, accounting, effect, or Home proof is incomplete")
    counts = tuple(result.get(name) for name in (
        "input_count", "total_input_count", "session_input_count", "runtime_input_count",
    ))
    input_count = counts[0]
    if (any(type(value) is not int for value in counts) or len(set(counts)) != 1
            or type(input_count) is not int or not 0 <= input_count <= MAX_INPUTS
            or result.get("max_inputs") != MAX_INPUTS or result.get("max_actions") != MAX_ACTIONS):
        raise ValueError("Alliance Shop native and session input accounting differs")
    source = result.get("source_frame")
    if (not isinstance(source, Mapping) or not isinstance(source.get("frame_path"), str)
            or not source.get("frame_path") or not isinstance(source.get("frame_sha256"), str)
            or _SHA256_RE.fullmatch(source["frame_sha256"]) is None):
        raise ValueError("Alliance Shop current Home source evidence is missing")
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(completed, timezone.utc))
    backend_result = result.get("backend_identity")
    if (not isinstance(backend_result, Mapping)
            or backend_result.get("runtime_scope") != backend.runtime_scope
            or backend_result.get("account_id") != identity.account_id
            or backend_result.get("server_id") != identity.server_id
            or backend_result.get("backend_reset_id") != backend.reset_id):
        raise ValueError("Alliance Shop fixed backend identity proof is incomplete")
    reset_start = datetime.fromtimestamp(completed, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return completed, (reset_start + timedelta(days=1)).timestamp()


def _validate_scan_readiness(value: Any, *, required_reason: str | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("complete") is not True:
        raise ValueError("Alliance Shop inventory scan is not complete")
    refs, hashes = value.get("frame_refs"), value.get("frame_sha256s")
    if (not isinstance(refs, (tuple, list)) or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or not isinstance(hashes, (tuple, list)) or len(hashes) != len(refs)
            or any(not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None for digest in hashes)):
        raise ValueError("Alliance Shop inventory scan lacks captured frame evidence")
    if required_reason is not None and value.get("reason") != required_reason:
        raise ValueError("Alliance Shop inventory absence is not proven")
    return value


def _validate_offer_evidence(row: Any, *, shop: str, item: str, rarity: int | None) -> None:
    if not isinstance(row, Mapping):
        raise ValueError("Alliance Shop selection offer evidence is malformed")
    price, balance, stock = row.get("unit_price"), row.get("balance"), row.get("stock")
    available = row.get("available")
    if (
        row.get("shop_identity") != shop or row.get("item_identity") != item
        or row.get("currency_identity") != ALLIANCE_CURRENCY or row.get("rarity") != rarity
        or row.get("recognized") is not True or row.get("premium") is not False
        or not isinstance(row.get("offer_identity"), str) or not row["offer_identity"]
        or (row.get("price_shortage") is not True and (
            type(price) is not int or price <= 0
            or type(balance) is not int or balance < 0
            or type(stock) is not int or stock < 0
            or type(available) is not bool or available != (stock > 0)))
    ):
        raise ValueError("Alliance Shop offer identity or numeric readiness is unverified")


def _selected_offer_matches_row(selected: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return all((
        selected.get("shop_identity") == row.get("shop_identity"),
        selected.get("offer_identity") == row.get("offer_identity"),
        selected.get("item_identity") == row.get("item_identity"),
        selected.get("currency_identity") == row.get("currency_identity"),
        selected.get("rarity") == row.get("rarity"),
        selected.get("unit_price") == row.get("unit_price"),
        selected.get("balance_before") == row.get("balance"),
        selected.get("stock_before") == row.get("stock"),
    ))


def _validate_selection_evidence(result: Mapping[str, Any], selected: Mapping[str, Any]) -> None:
    evidence = result.get("selection_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("Alliance Shop selected purchase lacks preferred inventory evidence")
    weekly_inventory = _validate_scan_readiness(evidence.get("weekly_inventory"))
    if weekly_inventory.get("reason") not in {"", None}:
        raise ValueError("Alliance Shop Weekly selection scan is unresolved")
    weekly_offers = evidence.get("weekly_offers")
    if not isinstance(weekly_offers, (tuple, list)):
        raise ValueError("Alliance Shop selected purchase lacks exact Weekly offer rows")
    seen = set()
    for row in weekly_offers:
        if not isinstance(row, Mapping):
            raise ValueError("Alliance Shop Weekly selection row is malformed")
        item = row.get("item_identity")
        if item not in ALLIANCE_WEEKLY_ITEMS or item in seen:
            raise ValueError("Alliance Shop Weekly selection rows are not uniquely allowlisted")
        seen.add(item)
        _validate_offer_evidence(row, shop=ALLIANCE_WEEKLY_SHOP, item=item, rarity=None)

    shop, item = selected.get("shop_identity"), selected.get("item_identity")
    if shop == ALLIANCE_WEEKLY_SHOP:
        if evidence.get("fallback_inventory") is not None or evidence.get("fallback_offer") is not None:
            raise ValueError("Alliance Shop Weekly selection contains an unrelated fallback scan")
        matching = [row for row in weekly_offers if row.get("item_identity") == item]
        if (len(matching) != 1 or matching[0].get("price_shortage") is True or not matching[0].get("available")
                or matching[0].get("balance", 0) < matching[0].get("unit_price", 1)
                or not _selected_offer_matches_row(selected, matching[0])):
            raise ValueError("Alliance Shop Weekly purchase was not the exact affordable scanned offer")
        for row in weekly_offers:
            if ALLIANCE_WEEKLY_ITEMS.index(row["item_identity"]) < ALLIANCE_WEEKLY_ITEMS.index(item):
                _validate_unaffordable_offer(
                    row, shop=ALLIANCE_WEEKLY_SHOP, item=row["item_identity"], rarity=None,
                )
        return

    if shop != ALLIANCE_OTHER_SHOP or item != ALLIANCE_FALLBACK_ITEM:
        raise ValueError("Alliance Shop selected offer is outside Weekly and exact Other fallback")
    for row in weekly_offers:
        _validate_unaffordable_offer(
            row, shop=ALLIANCE_WEEKLY_SHOP, item=row["item_identity"], rarity=None,
        )
    fallback_inventory = evidence.get("fallback_inventory")
    fallback_offer = evidence.get("fallback_offer")
    fallback_inventory = _validate_scan_readiness(fallback_inventory)
    if fallback_inventory.get("reason") not in {"", None} or not isinstance(fallback_offer, Mapping):
        raise ValueError("Alliance Shop Other fallback scan is unresolved")
    _validate_offer_evidence(
        fallback_offer, shop=ALLIANCE_OTHER_SHOP, item=ALLIANCE_FALLBACK_ITEM, rarity=1,
    )
    if (fallback_offer.get("price_shortage") is True or not fallback_offer.get("available")
            or fallback_offer["balance"] < fallback_offer["unit_price"]
            or not _selected_offer_matches_row(selected, fallback_offer)):
        raise ValueError("Alliance Shop fallback was not affordable or did not match its fresh scan")


def _validate_unaffordable_offer(row: Any, *, shop: str, item: str, rarity: int | None) -> None:
    _validate_offer_evidence(row, shop=shop, item=item, rarity=rarity)
    if row.get("price_shortage") is not True and row["available"] and row["balance"] >= row["unit_price"]:
        raise ValueError("Alliance Shop offer is affordable")


def _validate_no_work_readiness(result: Mapping[str, Any]) -> None:
    evidence = result.get("no_work_evidence")
    if (not isinstance(evidence, Mapping)
            or evidence.get("reason") != "NO_AFFORDABLE_ALLOWLISTED_OFFER"
            or result.get("reason") != evidence.get("reason")):
        raise ValueError("Alliance Shop no-work result lacks its exact route reason")
    weekly_inventory = _validate_scan_readiness(evidence.get("weekly_inventory"))
    if weekly_inventory.get("reason") not in {"", None}:
        raise ValueError("Alliance Shop weekly offer scan has an unresolved state")
    weekly_offers = evidence.get("weekly_offers")
    if not isinstance(weekly_offers, (tuple, list)):
        raise ValueError("Alliance Shop weekly offers are not an exact inventory")
    seen = set()
    for row in weekly_offers:
        if not isinstance(row, Mapping):
            raise ValueError("Alliance Shop weekly offer evidence is malformed")
        item = row.get("item_identity")
        if item not in ALLIANCE_WEEKLY_ITEMS or item in seen:
            raise ValueError("Alliance Shop preferred inventory is not uniquely allowlisted")
        seen.add(item)
        _validate_unaffordable_offer(row, shop=ALLIANCE_WEEKLY_SHOP, item=item, rarity=None)
    fallback_inventory = evidence.get("fallback_inventory")
    fallback_offer = evidence.get("fallback_offer")
    if fallback_offer is None:
        _validate_scan_readiness(fallback_inventory, required_reason="EXACT_FALLBACK_NOT_PRESENT")
    else:
        fallback_inventory = _validate_scan_readiness(fallback_inventory)
        if fallback_inventory.get("reason") not in {"", None}:
            raise ValueError("Alliance Shop fallback scan has an unresolved state")
        _validate_unaffordable_offer(
            fallback_offer, shop=ALLIANCE_OTHER_SHOP, item=ALLIANCE_FALLBACK_ITEM, rarity=1,
        )


def alliance_shop_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Admit one exact purchase, a restart-confirmed purchase, or an evidenced no-work pulse."""
    completed, reset_due = _validated_due_context(result, identity, started_at)
    calls = result.get("purchase_transport_calls")
    committed = result.get("committed_action_count")
    prior = result.get("prior_confirmed_action_count")
    if (type(calls) is not int or type(committed) is not int or type(prior) is not int
            or not 0 <= calls <= MAX_ACTIONS or not 0 <= committed <= MAX_ACTIONS
            or not 0 <= prior <= MAX_ACTIONS or calls != committed
            or committed + prior > MAX_ACTIONS):
        raise ValueError("Alliance Shop purchase and durable action counts are invalid")
    status = result.get("status")
    if status == "complete_for_reset":
        if committed == 0 and prior == 1 and calls == 0:
            if result.get("native_status") != "already_complete":
                raise ValueError("Alliance Shop restart completion lacks its durable confirmed-action state")
            return reset_due
        offer = result.get("selected_offer")
        if (committed != 1 or prior != 0 or calls != 1
                or result.get("offer_effect_verified") is not True
                or not isinstance(offer, Mapping)
                or type(offer.get("quantity")) is not int or offer["quantity"] != 1
                or type(offer.get("unit_price")) is not int or offer["unit_price"] <= 0
                or type(offer.get("total")) is not int or offer["total"] != offer["unit_price"]
                or type(offer.get("balance_before")) is not int
                or offer["balance_before"] < offer["unit_price"]
                or type(offer.get("stock_before")) is not int or offer["stock_before"] < 1
                or offer.get("currency_identity") != ALLIANCE_CURRENCY
                or not isinstance(offer.get("offer_identity"), str) or not offer["offer_identity"]):
            raise ValueError("Alliance Shop completion lacks its exact paired purchase proof")
        shop, item, rarity = offer.get("shop_identity"), offer.get("item_identity"), offer.get("rarity")
        if not ((shop == ALLIANCE_WEEKLY_SHOP and item in ALLIANCE_WEEKLY_ITEMS and rarity is None)
                or (shop == ALLIANCE_OTHER_SHOP and item == ALLIANCE_FALLBACK_ITEM and rarity == 1)):
            raise ValueError("Alliance Shop completed offer is outside the exact allowlist")
        _validate_selection_evidence(result, offer)
        return reset_due
    if (status != "deferred" or calls != 0 or committed != 0 or prior != 0
            or result.get("reason") != "NO_AFFORDABLE_ALLOWLISTED_OFFER"
            or result.get("selected_offer") is not None
            or result.get("offer_effect_verified") is not False):
        raise ValueError("Alliance Shop result is neither verified completion nor exact no-work")
    _validate_no_work_readiness(result)
    return min(completed + RECHECK_SECONDS, reset_due)



class AllianceShopRunner:
    """Pass one reset-stable offer action through the injected native binding."""

    def __init__(self, *, native: NativeRouteBoundary | None = None,
                 adb: str = str(BLUESTACKS_ADB), serial: str = BLUESTACKS_SERIAL,
                 output_directory: Path, utc_clock: Callable[[], float] = time.time,
                 monotonic_clock: Callable[[], float] = time.monotonic,
                 settle_seconds: float = 1.0) -> None:
        self.native = native
        self.adb, self.serial = str(adb), serial
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        if type(settle_seconds) not in (int, float) or not 0 <= float(settle_seconds) <= 5:
            raise ValueError("Alliance Shop settle delay must be bounded")
        self.settle_seconds = float(settle_seconds)
        if native is not None and (
            native.flow_id != FLOW_ID or native.product_id != PRODUCT_ID
            or native.product_revision != PRODUCT_REVISION
            or native.runtime_profile_id != PROFILE_ID
            or native.max_inputs != MAX_INPUTS or native.max_actions != MAX_ACTIONS
        ):
            raise ValueError("Alliance Shop native binding identity mismatch")

    def __call__(self, identity: SchedulerIdentity, previous_reset_id: str | None,
                 checkpoint: Callable[[], None], *, runtime_input_lock: RuntimeInputLockPort,
                 occurrence_key: str) -> Mapping[str, Any]:
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
                f"ALLIANCE_SHOP_NATIVE_FAILURE:{type(exc).__name__}",
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
                 checkpoint: Callable[[], None], *, runtime_input_lock: RuntimeInputLockPort,
                 occurrence_key: str) -> Mapping[str, Any]:
        started = self._epoch(self.utc_clock(), "start")
        backend = self._validate_identity(identity, started)
        if (self.adb, self.serial) != (str(BLUESTACKS_ADB), BLUESTACKS_SERIAL):
            raise ValueError("Alliance Shop runtime differs from its fixed BlueStacks binding")
        if (getattr(runtime_input_lock, "owner", None) != "automation-service"
                or not isinstance(getattr(runtime_input_lock, "invocation_id", None), str)
                or not runtime_input_lock.invocation_id or not callable(checkpoint)):
            raise ValueError("Alliance Shop requires the canonical held runtime owner")
        if not isinstance(occurrence_key, str) or not occurrence_key.strip():
            raise ValueError("Alliance Shop service occurrence key is required")
        runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
        action_key = canonical_purchase_action_key(FLOW_ID, PRODUCT_ID, identity, "alliance_shop")
        if self.native is None:
            return self._blocked(identity, previous_reset_id, occurrence_key, started,
                                 "ALLIANCE_SHOP_NATIVE_BINDING_UNAVAILABLE")

        def validate_identity() -> None:
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            checkpoint()
            runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
            now = self._epoch(self.utc_clock(), "identity checkpoint")
            self._validate_identity(identity, now)

        request = NativeRouteRequest(
            flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            runtime_profile_id=PROFILE_ID, identity=identity,
            previous_reset_id=previous_reset_id, occurrence_key=occurrence_key,
            checkpoint=checkpoint, validate_identity=validate_identity,
            runtime_input_lock=runtime_input_lock, adb=self.adb, serial=self.serial,
            output_directory=self.output_directory, max_inputs=MAX_INPUTS,
            max_actions=MAX_ACTIONS, settle_seconds=self.settle_seconds,
            arguments=MappingProxyType({"action_key": action_key, "backend_identity": backend}),
            utc_clock=self.utc_clock, monotonic_clock=self.monotonic_clock,
        )
        outcome = self.native.run(request)
        if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != FLOW_ID:
            raise TypeError("Alliance Shop native binding returned an invalid outcome")
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
        status = result.get("status")
        if outcome.failure is not None:
            result["native_status"] = status
            calls = result.get("purchase_transport_calls", 0)
            committed = result.get("committed_action_count", 0)
            unknown = bool(result.get("effect_reconciliation_required") is True
                           or type(calls) is not int or type(committed) is not int or calls > committed)
            if unknown:
                result["effect_reconciliation_required"] = True
                if type(calls) is int and calls > 0:
                    result["identical_retry_denied"] = True
            status = "unresolved" if unknown else "blocked"
        elif status in {"completed", "already_complete"}:
            result.setdefault("native_status", status)
            status = "complete_for_reset"
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
        result["status"] = status or "blocked"
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
    def _epoch(value: object, field: str) -> float:
        if (not isinstance(value, (int, float)) or type(value) not in (int, float)
                or not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError(f"Alliance Shop {field} must be a finite UTC epoch")
        return float(value)

    @staticmethod
    def _validate_identity(identity: SchedulerIdentity, now: float) -> VerifiedRuntimeIdentity:
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Alliance Shop scheduler identity mismatch")
        if identity.reset_id != recruitment_reset(now):
            raise ValueError("Alliance Shop scheduler reset identity is not current")
        binding = resource_fixed_runtime_binding()
        backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
        if (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id):
            raise ValueError("Alliance Shop scheduler identity differs from the fixed backend")
        return backend

    @staticmethod
    def _blocked(identity: SchedulerIdentity, previous_reset_id: str | None,
                 occurrence_key: str, started: float | None, reason: str) -> dict[str, Any]:
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
            "committed_action_count": 0, "prior_confirmed_action_count": 0,
        }


class AllianceShopExecutionHandler:
    """Canonical dispatch handler; all execution is delegated to the injected runner."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot,
                 execute: Callable[[RunRecord, SchedulerFacts], NormalizedResult], *,
                 flow_spec: FlowSpec | None = None) -> None:
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Alliance Shop requires a typed registered dispatch snapshot")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Alliance Shop registration identity mismatch")
        if not callable(execute):
            raise TypeError("Alliance Shop executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Alliance Shop requires its matching route specification")
        self.snapshot, self._execute = snapshot, execute
        self.flow_spec = flow_spec

    def describe(self) -> FlowDescriptor:
        return canonical_entry(FLOW_ID).descriptor

    def eligibility(self, facts: SchedulerFacts, perception: PerceptionEnvelope | None = None) -> bool:
        return bool(not facts.gate_failures(self.describe())
            and facts.accepted_product == PRODUCT_ID
            and facts.product_revision == PRODUCT_REVISION
            and facts.registration_status == "REGISTERED"
            and facts.scheduler_eligible is True
            and (perception is None or perception.profile_id == PROFILE_ID))

    revalidate = eligibility

    def execute_run(self, run: RunRecord, facts: SchedulerFacts,
                    perception: PerceptionEnvelope | None = None) -> NormalizedResult:
        return self._execute(run, facts)

    def plan(self, facts: SchedulerFacts,
             perception: PerceptionEnvelope | None = None) -> NormalizedResult:
        return self.recover("ALLIANCE_SHOP_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan: object,
                  perception: PerceptionEnvelope | None = None) -> NormalizedResult:
        return plan if isinstance(plan, NormalizedResult) else self.recover("ALLIANCE_SHOP_UNKNOWN_RESULT")

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self) -> Mapping[str, object]:
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


__all__ = [
    "AllianceShopExecutionHandler",
    "AllianceShopRunner",
    "FLOW_ID",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "alliance_shop_next_due",
]
