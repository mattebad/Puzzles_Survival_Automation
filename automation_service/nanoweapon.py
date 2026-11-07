"""Canonical same-visit adapter for Nano Material maintenance and Normal Craft."""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
from pathlib import Path
import time
from types import MappingProxyType
from typing import Mapping

from tasks.nano_material_production import (
    NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
    NANO_MATERIAL_PRODUCTION_TARGET,
)
from tasks.nanoweapon import NANO_PARTS_REQUIRED, NORMAL_CRAFT_DURATION_SECONDS
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
    NANOWEAPON_FLOW_ID,
    NANOWEAPON_MAX_INPUTS,
    NANOWEAPON_PRODUCT_ID,
    NANOWEAPON_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from .recruitment import recruitment_reset


FLOW_ID = NANOWEAPON_FLOW_ID
PRODUCT_ID = NANOWEAPON_PRODUCT_ID
PRODUCT_REVISION = NANOWEAPON_PRODUCT_REVISION
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = NANOWEAPON_MAX_INPUTS
MAX_ACTIONS = 4
DEFAULT_OBSERVATION_INTERVAL_SECONDS = 300


class NanoweaponExecutionHandler:
    """Use canonical scheduler admission and delegate the active run to its service."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Nanoweapon requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Nanoweapon registration identity mismatch")
        if not callable(execute):
            raise TypeError("Nanoweapon executor must be callable")
        if flow_spec is not None:
            if not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID:
                raise ValueError("Nanoweapon requires its matching flow spec")
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
        return self.recover("NANOWEAPON_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover(
            "NANOWEAPON_UNKNOWN_RESULT"
        )

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}




class NanoweaponRunnerError(RuntimeError):
    def __init__(self, reason: str, *, partial_result: Mapping[str, object]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Nanoweapon {name} must be a finite UTC epoch")
    return float(value)


def _fixed_identity(identity, *, now: float, serial: str):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Nanoweapon requires its canonical scheduler identity")
    sample = datetime.fromtimestamp(now, timezone.utc)
    scheduler_reset = recruitment_reset(now)
    window = derive_static_utc_reset(sample)
    binding = resource_fixed_runtime_binding()
    if serial != BLUESTACKS_SERIAL or binding.serial != serial:
        raise ValueError("Nanoweapon requires the fixed BlueStacks runtime")
    backend = derive_resource_runtime_identity(binding, sample)
    if (
        identity.reset_id != scheduler_reset
        or (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id)
        or (backend.reset_start_utc, backend.reset_deadline_utc)
        != (window.reset_start_text, window.reset_deadline_text)
    ):
        raise ValueError("Nanoweapon scheduler/backend reset-window identity mismatch")
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
        raise ValueError("Nanoweapon backend identity proof is inconsistent")


def _counts(result: Mapping[str, object]) -> tuple[int, int, int]:
    production = result.get("production_transport_calls")
    craft = result.get("craft_transport_calls")
    total = result.get("nanoweapon_dispatch_count")
    attempted = result.get("attempted_action_count")
    committed = result.get("committed_action_count")
    if (
        type(production) is not int
        or not 0 <= production <= 2
        or type(craft) is not int
        or not 0 <= craft <= 2
        or type(total) is not int
        or total != production + craft
        or total > MAX_ACTIONS
        or type(attempted) is not int
        or attempted != total
        or type(committed) is not int
        or committed != total
    ):
        raise ValueError("Nanoweapon combined production/craft action accounting is not exact")
    return production, craft, total


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
        raise ValueError("Nanoweapon requires current canonical Home frame evidence")



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
        raise ValueError("Nanoweapon requires retained same-visit production frame evidence")

class NanoweaponRunner:
    """Device-free construction over the injected, fixed Nanoweapon route binding."""

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
        observation_interval_seconds: int = DEFAULT_OBSERVATION_INTERVAL_SECONDS,
    ) -> None:
        self.native = native
        self.adb, self.serial = str(adb), str(serial)
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        if (
            type(settle_seconds) not in (int, float)
            or not math.isfinite(settle_seconds)
            or settle_seconds < 0
        ):
            raise ValueError("Nanoweapon settle delay must be finite and non-negative")
        if (
            type(observation_interval_seconds) is not int
            or observation_interval_seconds != DEFAULT_OBSERVATION_INTERVAL_SECONDS
        ):
            raise ValueError("Nanoweapon observation interval is fixed at 300 seconds")
        if native is not None and getattr(native, "flow_id", None) != FLOW_ID:
            raise ValueError("Nanoweapon native binding identity mismatch")
        self.settle_seconds = float(settle_seconds)
        self.observation_interval_seconds = observation_interval_seconds

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
            raise NanoweaponRunnerError(
                "NANOWEAPON_NATIVE_BINDING_REQUIRED",
                partial_result={
                    "status": "blocked",
                    "production_transport_calls": 0,
                    "craft_transport_calls": 0,
                    "nanoweapon_dispatch_count": 0,
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
                arguments=MappingProxyType(
                    {"observation_interval_seconds": self.observation_interval_seconds}
                ),
                utc_clock=self.utc_clock,
                monotonic_clock=self.monotonic_clock,
            )
            outcome = self.native.run(request)
            native_result = dict(outcome.native_result)
            if outcome.flow_id != FLOW_ID:
                raise ValueError("Nanoweapon native outcome flow mismatch")
            if outcome.failure is not None or outcome.accounting_verified is not True:
                partial = dict(native_result)
                partial.update(dict(outcome.partial_result or {}))
                raw_total = partial.get("nanoweapon_dispatch_count")
                raw_attempted = partial.get("attempted_action_count")
                raw_production = partial.get("production_transport_calls")
                raw_craft = partial.get("craft_transport_calls")
                total_known = type(raw_total) is int and raw_total >= 0
                attempted_known = type(raw_attempted) is int and raw_attempted >= 0
                components_known = (
                    type(raw_production) is int
                    and raw_production >= 0
                    and type(raw_craft) is int
                    and raw_craft >= 0
                )
                component_total = raw_production + raw_craft if components_known else 0
                total = max(
                    raw_total if total_known else 0,
                    raw_attempted if attempted_known else 0,
                    component_total,
                )
                count_known = bool(
                    total_known
                    and attempted_known
                    and components_known
                    and raw_total == raw_attempted == component_total
                )
                unresolved = bool(
                    total
                    or not count_known
                    or not outcome.accounting_verified
                    or partial.get("effect_reconciliation_required")
                    or partial.get("status") == "unresolved"
                )
                partial.update(
                    attempted_action_count=total if count_known else None,
                    nanoweapon_dispatch_count=total if count_known else None,
                    status="unresolved" if unresolved else "blocked",
                    reason=outcome.failure or "NANOWEAPON_ACCOUNTING_UNVERIFIED",
                    accounting_verified=outcome.accounting_verified,
                    effect_reconciliation_required=unresolved,
                    identical_retry_denied=bool(unresolved or not outcome.accounting_verified),
                )
                raise NanoweaponRunnerError(str(partial["reason"]), partial_result=partial)
            production, craft, total = _counts(native_result)
            if (
                native_result.get("status") not in {"completed", "deferred"}
                or native_result.get("terminal_home_verified") is not True
                or native_result.get("effect_reconciliation_required") is not False
                or native_result.get("identical_retry_denied") is not False
            ):
                raise ValueError("Nanoweapon route has no verified terminal Home result")
            _require_terminal_home(native_result)
            if (
                native_result.get("native_occurrence_key") != occurrence_key
                or native_result.get("occurrence_key") != occurrence_key
            ):
                raise ValueError("Nanoweapon native result is bound to a different occurrence")
            completed = _epoch(self.utc_clock(), "completion time")
            if completed < started:
                raise ValueError("Nanoweapon completion clock predates its run")
            validate_identity()
            input_count = outcome.input_count
            if type(input_count) is not int or not 0 <= input_count <= MAX_INPUTS:
                raise ValueError("Nanoweapon native input count exceeds its budget")
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
                production_transport_calls=production,
                craft_transport_calls=craft,
                nanoweapon_dispatch_count=total,
                committed_action_count=total,
                accounting_verified=outcome.accounting_verified,
                terminal_home_verified=True,
                startup_recovery=outcome.startup_recovery,
                session_directory=outcome.session_directory,
                observation_interval_seconds=self.observation_interval_seconds,
            )
            production_timer = result.get("production_timer_seconds_remaining")
            if (
                type(production_timer) is not int
                or not 0 < production_timer <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
            ):
                raise ValueError("Nanoweapon production timer is not positively recognized")
            production_due = completed + production_timer
            result["production_next_eligible_at"] = production_due
            due_reason = result.get("due_reason")
            if due_reason == "current_reset_start":
                craft_due = _next_reset_utc(completed)
                if result.get("craft_state") == "active":
                    remaining = result.get("active_craft_timer_seconds_remaining")
                    if type(remaining) is not int or not 0 < remaining <= NORMAL_CRAFT_DURATION_SECONDS:
                        raise ValueError("Current-reset active craft timer is not positively recognized")
                    craft_due = min(craft_due, completed + remaining)
                elif result.get("craft_state") != "idle":
                    raise ValueError("Current-reset Normal Craft state is not recognized")
            elif due_reason == "previous_reset_active_timer":
                remaining = result.get("active_craft_timer_seconds_remaining")
                if type(remaining) is not int or not 0 < remaining <= NORMAL_CRAFT_DURATION_SECONDS:
                    raise ValueError("Prior-reset active craft timer is not positively recognized")
                craft_due = completed + remaining
            elif due_reason == "known_material_shortage":
                craft_due = completed + self.observation_interval_seconds
            else:
                raise ValueError("Nanoweapon unknown state has no permitted cooldown-pulse due time")
            result["next_eligible_at"] = min(production_due, craft_due)
            nanoweapon_next_due(result, identity, started)
            validate_identity()
            checkpoint()
            return result
        except NanoweaponRunnerError:
            raise
        except Exception as exc:
            partial = dict(native_result) if isinstance(native_result, Mapping) else {}
            partial.update(dict(getattr(exc, "partial_result", {}) or {}))
            raw_total = partial.get("nanoweapon_dispatch_count")
            raw_attempted = partial.get("attempted_action_count")
            raw_production = partial.get("production_transport_calls")
            raw_craft = partial.get("craft_transport_calls")
            total_known = type(raw_total) is int and raw_total >= 0
            attempted_known = type(raw_attempted) is int and raw_attempted >= 0
            components_known = (
                type(raw_production) is int
                and raw_production >= 0
                and type(raw_craft) is int
                and raw_craft >= 0
            )
            component_total = raw_production + raw_craft if components_known else 0
            total = max(
                raw_total if total_known else 0,
                raw_attempted if attempted_known else 0,
                component_total,
            )
            count_known = bool(
                total_known
                and attempted_known
                and components_known
                and raw_total == raw_attempted == component_total
            )
            unresolved = bool(
                total
                or (outcome is not None and not count_known)
                or (outcome is not None and not outcome.accounting_verified)
                or partial.get("effect_reconciliation_required")
                or partial.get("status") == "unresolved"
            )
            if outcome is not None or total_known or attempted_known or components_known:
                partial["attempted_action_count"] = total if count_known else None
                partial["nanoweapon_dispatch_count"] = total if count_known else None
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
            raise NanoweaponRunnerError(str(exc), partial_result=partial) from exc


def _next_reset_utc(completed: float) -> float:
    return (math.floor(completed / 86400.0) + 1) * 86400.0

def _scheduler_reset_date(reset_id: str) -> date:
    prefix = "game-day-"
    if not isinstance(reset_id, str) or not reset_id.startswith(prefix):
        raise ValueError("scheduler reset id is not canonical")
    return date.fromisoformat(reset_id[len(prefix):])


def nanoweapon_next_due(result, identity, started_at: float) -> float:
    """Validate the bounded Normal Craft cooldown outcome."""

    started = _epoch(started_at, "start time")
    if (
        result.get("flow_id") != FLOW_ID
        or result.get("product_id") != PRODUCT_ID
        or result.get("product_revision") != PRODUCT_REVISION
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
        or result.get("status") not in {"completed", "deferred"}
        or type(result.get("occurrence_key")) is not str
        or not result.get("occurrence_key")
        or result.get("occurrence_key") != result.get("native_occurrence_key")
        or result.get("production_occurrence_key") != result.get("occurrence_key")
        or result.get("production_target_identity") != NANO_MATERIAL_PRODUCTION_TARGET
        or result.get("time_basis") != "utc"
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("effect_reconciliation_required") is not False
        or result.get("identical_retry_denied") is not False
    ):
        raise ValueError("Nanoweapon result is not verified for cooldown-pulse scheduling")
    _require_terminal_home(result)
    _require_production_frame(result)
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if completed < started:
        raise ValueError("Nanoweapon completion precedes run start")
    if result.get("task_id") != PRODUCT_ID:
        raise ValueError("Nanoweapon task identity is not canonical")
    _verify_backend_identity(result.get("backend_identity"), identity, completed)
    if result.get("runtime_profile_id") != PROFILE_ID:
        raise ValueError("Nanoweapon runtime profile is not canonical")
    if (
        result.get("prior_material_production_reconciled") is not True
        or result.get("production_state") != "active"
        or type(result.get("production_active_count")) is not int
        or result.get("production_active_count") != 1
        or type(result.get("production_duration_seconds")) is not int
        or result.get("production_duration_seconds") != NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        or type(result.get("production_timer_seconds_remaining")) is not int
        or not 0 < result["production_timer_seconds_remaining"] <= NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        or result.get("zero_resource_cost_confirmed") is not True
        or result.get("game_day_id") != identity.reset_id
        or type(result.get("craft_duration_seconds")) is not int
        or result.get("craft_duration_seconds") != NORMAL_CRAFT_DURATION_SECONDS
    ):
        raise ValueError("Same-visit production and Normal Craft state are not positively proven")
    production_timer = result["production_timer_seconds_remaining"]
    production_due = _epoch(result.get("production_next_eligible_at"), "production due time")
    if production_due != completed + production_timer:
        raise ValueError("Nanoweapon production due does not match its current active timer")
    inputs = result.get("total_input_count")
    input_count = result.get("input_count")
    production, craft, total = _counts(result)
    if (
        type(inputs) is not int
        or type(input_count) is not int
        or input_count != inputs
        or not 0 <= inputs <= MAX_INPUTS
        or total > inputs
    ):
        raise ValueError("Nanoweapon input/action count mismatch")
    if result.get("production_transport_calls") != production or result.get("craft_transport_calls") != craft:
        raise ValueError("Nanoweapon separate action counts changed after execution")
    start_calls = result.get("craft_start_transport_calls")
    claim_calls = result.get("craft_claim_transport_calls")
    if (
        type(start_calls) is not int
        or start_calls not in {0, 1}
        or type(claim_calls) is not int
        or claim_calls not in {0, 1}
        or start_calls + claim_calls != craft
    ):
        raise ValueError("Nanoweapon claim/start call accounting is not exact")
    reason = result.get("due_reason")
    due = result.get("next_eligible_at")
    craft_state = result.get("craft_state")
    craft_count = result.get("craft_active_count")
    craft_timer = result.get("active_craft_timer_seconds_remaining")
    starts_this_reset = result.get("starts_this_reset")
    if type(craft_timer) is not int or not 0 <= craft_timer <= NORMAL_CRAFT_DURATION_SECONDS:
        raise ValueError("Nanoweapon current craft timer is not positively bounded")
    if reason == "current_reset_start":
        if (
            result.get("craft_start_confirmed") is not True
            or result.get("craft_start_reset_id") != identity.reset_id
            or type(starts_this_reset) is not int
            or starts_this_reset != 1
            or craft_state not in {"active", "idle"}
            or type(craft_count) is not int
            or (craft_state == "active" and (craft_count != 1 or craft_timer <= 0))
            or (craft_state == "idle" and (craft_count != 0 or craft_timer != 0))
            or (start_calls == 1 and craft_state != "active")
        ):
            raise ValueError("Current-reset Nanoweapon start lacks its canonical quota/state proof")
        if start_calls == 1:
            before_balance = result.get("precraft_nano_parts_balance")
            balance = result.get("nano_parts_balance")
            if (
                type(before_balance) is not int
                or before_balance < NANO_PARTS_REQUIRED
                or type(balance) is not int
                or before_balance - balance != NANO_PARTS_REQUIRED
            ):
                raise ValueError("Current Normal Craft start lacks exact 100-part consumption proof")
        expected = _next_reset_utc(completed)
        if craft_state == "active":
            expected = min(expected, completed + craft_timer)
    elif reason == "previous_reset_active_timer":
        active_reset = result.get("craft_start_reset_id")
        if (
            not isinstance(active_reset, str)
            or type(starts_this_reset) is not int
            or starts_this_reset != 0
            or result.get("craft_start_confirmed") is not True
            or active_reset == identity.reset_id
            or craft_state != "active"
            or type(craft_count) is not int
            or craft_count != 1
            or craft_timer <= 0
            or start_calls != 0
            or claim_calls != 0
        ):
            raise ValueError("Prior-reset active craft lacks exact timer/reset evidence")
        try:
            active_date = _scheduler_reset_date(active_reset)
            current_date = _scheduler_reset_date(identity.reset_id)
            if active_date >= current_date:
                raise ValueError("active craft reset is not prior to current reset")
        except ValueError as exc:
            raise ValueError("active craft prior-reset identity is invalid") from exc
        expected = completed + craft_timer
    elif reason == "known_material_shortage":
        balance = result.get("nano_parts_balance")
        interval = result.get("observation_interval_seconds")
        if (
            type(balance) is not int
            or balance < 0
            or balance >= NANO_PARTS_REQUIRED
            or type(interval) is not int
            or interval < 1
            or interval != DEFAULT_OBSERVATION_INTERVAL_SECONDS
            or type(starts_this_reset) is not int
            or starts_this_reset != 0
            or craft_state != "idle"
            or type(craft_count) is not int
            or craft_count != 0
            or craft_timer != 0
            or start_calls != 0
        ):
            raise ValueError("Nanoweapon material-shortage observation is not exact")
        expected = completed + interval
    else:
        raise ValueError("Nanoweapon unknown state has no permitted cooldown-pulse due time")
    expected = min(expected, production_due)
    if type(due) not in (int, float) or not math.isfinite(due) or due != expected:
        raise ValueError("Nanoweapon next due does not match its proven reset/timer/observation cadence")
    return float(due)
