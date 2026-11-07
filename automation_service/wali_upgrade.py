"""Canonical Wali single-level upgrades over the fixed native execution boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path, PurePosixPath
import re
import time
from typing import Mapping

from tasks.hero_upgrade_disabled import (
    HeroUpgradeObservation,
    hero_evolution_postcondition_verified,
    hero_upgrade_postcondition_verified,
)
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
    WALI_UPGRADE_FLOW_ID as FLOW_ID,
    WALI_UPGRADE_MAX_INPUTS as MAX_INPUTS,
    WALI_UPGRADE_PRODUCT_ID as PRODUCT_ID,
    WALI_UPGRADE_PRODUCT_REVISION as PRODUCT_REVISION,
    WALI_UPGRADE_PROFILE_ID as PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)

MAX_ACTIONS = 6
RECHECK_SECONDS = 300.0
_SHA256 = re.compile(r"[0-9a-f]{64}")


class WaliUpgradeExecutionHandler:
    """Only canonical supervised serve installs an executor."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Wali requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID
        ):
            raise ValueError("Wali registration identity mismatch")
        if not callable(execute):
            raise TypeError("Wali executor must be callable")
        if flow_spec is not None and (not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID):
            raise ValueError("Wali requires its matching flow spec")
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
        return self.recover("WALI_UPGRADE_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("WALI_UPGRADE_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "total_action_count": 0}


def _epoch(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Wali {name} must be a finite UTC epoch")
    return float(value)


def _backend(identity: SchedulerIdentity, now: float, serial: str):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Wali requires its exact scheduler identity")
    sample = datetime.fromtimestamp(_epoch(now, "identity clock"), timezone.utc)
    binding = resource_fixed_runtime_binding()
    window = derive_static_utc_reset(sample)
    backend = derive_resource_runtime_identity(binding, sample)
    if (
        serial != BLUESTACKS_SERIAL or binding.serial != serial
        or identity.reset_id != recruitment_reset(now)
        or (identity.account_id, identity.server_id) != (backend.account_id, backend.server_id)
        or (backend.reset_start_utc, backend.reset_deadline_utc)
        != (window.reset_start_text, window.reset_deadline_text)
    ):
        raise ValueError("Wali fixed runtime/account/server/reset identity mismatch")
    return backend


def _observation(value: object) -> HeroUpgradeObservation:
    if not isinstance(value, Mapping):
        raise ValueError("Wali action row requires typed observation fields")
    fields = dict(value)
    for name in ("target_roi", "panel_bounds", "evidence_refs", "material_usage_receipts"):
        if name in fields:
            fields[name] = tuple(fields[name])
    return HeroUpgradeObservation(**fields)


def _count(result: Mapping[str, object], name: str, maximum: int) -> int:
    value = result.get(name)
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Wali {name} is outside its action bound")
    return value


def _home(result: Mapping[str, object]) -> None:
    proof = result.get("terminal_home_frame")
    if not isinstance(proof, Mapping):
        raise ValueError("Wali has no terminal Home frame")
    path, digest = proof.get("frame_path"), proof.get("frame_sha256")
    if (
        result.get("terminal_home_verified") is not True
        or not isinstance(path, str) or not path
        or "\\" in path or ":" in path
        or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
        or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None
        or result.get("terminal_home_frame_sha256") != digest
    ):
        raise ValueError("Wali terminal Home evidence is inconsistent")


def _validate_result(result: Mapping[str, object], *, game_day_id: str, occurrence_key: str) -> None:
    prior = _count(result, "prior_confirmed_upgrades", 3)
    confirmed = _count(result, "confirmed_upgrades", 3)
    upgrades = _count(result, "level_upgrade_committed_count", 3)
    evolutions = _count(result, "evolution_committed_count", 3)
    upgrade_attempts = _count(result, "upgrade_transport_calls", 3)
    evolution_attempts = _count(result, "evolution_transport_calls", 3)
    attempted = _count(result, "total_action_count", MAX_ACTIONS)
    committed = _count(result, "committed_action_count", MAX_ACTIONS)
    if (
        confirmed != prior + upgrades
        or upgrades > upgrade_attempts or evolutions > evolution_attempts
        or attempted != upgrade_attempts + evolution_attempts
        or committed != upgrades + evolutions
    ):
        raise ValueError("Wali attempts, normal quota and supporting evolution counts disagree")
    if (
        result.get("hero_identity") != "Wali"
        or result.get("game_day_id") != game_day_id
        or result.get("occurrence_key") != occurrence_key
        or result.get("campaign_reset_evidence_required") is not True
        or type(result.get("reset_transport_calls")) is not int or result["reset_transport_calls"] != 0
        or result.get("reset_count_unchanged") is not True
    ):
        raise ValueError("Wali result violates its selected hero/reset/occurrence or blocked reset boundary")
    seen: set[str] = set()
    progression = []
    for name, count, predicate in (
        ("level_upgrades", upgrades, hero_upgrade_postcondition_verified),
        ("evolutions", evolutions, hero_evolution_postcondition_verified),
    ):
        rows = result.get(name)
        if not isinstance(rows, (list, tuple)) or len(rows) != count:
            raise ValueError(f"Wali {name} count lacks its action evidence")
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or row.get("semantic_verified") is not True:
                raise ValueError("Wali action row has no verified semantic successor")
            key = row.get("action_key")
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError("Wali action keys are missing or duplicated")
            seen.add(key)
            before, after = _observation(row.get("before")), _observation(row.get("after"))
            if (
                before.game_day_id != game_day_id or after.game_day_id != game_day_id
                or not predicate(before, after)
                or name == "level_upgrades" and before.confirmed_upgrades != prior + index
                or name == "evolutions" and not prior <= before.confirmed_upgrades <= confirmed
            ):
                raise ValueError("Wali action row does not establish its claimed normal upgrade or standard evolution")
            progression.append((before, after))
    progression.sort(key=lambda row: row[0].current_level)
    for index in range(1, len(progression)):
        previous, current = progression[index - 1][1], progression[index][0]
        if (
            previous.current_level, previous.evolution_cap, previous.confirmed_upgrades
        ) != (
            current.current_level, current.evolution_cap, current.confirmed_upgrades
        ):
            raise ValueError("Wali action successors do not form one normal/evolution progression")
    status = result.get("status")
    unknown = result.get("unknown_action_sent")
    retry_denied = result.get("identical_retry_denied")
    if status not in {"completed", "deferred", "blocked", "unknown"}:
        raise ValueError("Wali returned an unsupported terminal status")
    if type(unknown) is not bool or type(retry_denied) is not bool:
        raise ValueError("Wali lacks exact unknown/retry flags")
    if unknown != (status == "unknown") or committed < attempted and not unknown:
        raise ValueError("Wali attempted action has no confirmed successor or unknown guard")
    if unknown and not retry_denied:
        raise ValueError("Wali unknown action does not deny an identical retry")
    if status == "completed" and confirmed != 3:
        raise ValueError("Wali completion requires three actual normal upgrades, excluding evolution")
    if status in {"completed", "deferred"}:
        _home(result)


def _verified_partial_actions(result, identity, started):
    """Keep independently proved actions, not a rejected native summary's totals."""
    prior = result.get("prior_confirmed_upgrades")
    if type(prior) is not int or not 0 <= prior <= 3:
        return None, [], []
    try:
        _backend(identity, started, BLUESTACKS_SERIAL)
        game_day_id = identity.reset_id
    except (OSError, OverflowError, TypeError, ValueError):
        return None, [], []
    normal, evolutions, seen = [], [], set()
    for name, accepted, predicate in (
        ("level_upgrades", normal, hero_upgrade_postcondition_verified),
        ("evolutions", evolutions, hero_evolution_postcondition_verified),
    ):
        rows = result.get(name, ())
        if not isinstance(rows, (list, tuple)):
            continue
        for index, row in enumerate(rows):
            if index >= 3:
                break
            try:
                if not isinstance(row, Mapping) or row.get("semantic_verified") is not True:
                    break
                key = row.get("action_key")
                before, after = _observation(row.get("before")), _observation(row.get("after"))
                if (
                    not isinstance(key, str) or not key or key in seen
                    or before.game_day_id != game_day_id or after.game_day_id != game_day_id
                    or name == "level_upgrades" and before.confirmed_upgrades != prior + len(normal)
                    or name == "level_upgrades" and normal
                    and before.current_level < normal[-1]["after"]["current_level"]
                    or name == "evolutions" and not prior <= before.confirmed_upgrades <= prior + len(normal)
                    or not predicate(before, after)
                ):
                    break
                seen.add(key)
                accepted.append(row)
            except (AttributeError, KeyError, TypeError, ValueError):
                break
    return prior, normal, evolutions


def _failed(*, identity, occurrence_key, reason, partial, outcome, started, completed, native_started):
    result = dict(partial)
    attempted = result.get("total_action_count")
    result["native_reported_counts"] = {
        name: result.get(name) for name in (
            "prior_confirmed_upgrades", "confirmed_upgrades", "level_upgrade_committed_count",
            "evolution_committed_count", "committed_action_count", "total_action_count",
        )
    }
    prior, normal, evolutions = _verified_partial_actions(result, identity, started)
    result["reported_level_upgrades"] = result.get("level_upgrades")
    result["reported_evolutions"] = result.get("evolutions")
    result.update(
        prior_confirmed_upgrades=prior,
        confirmed_upgrades=None if prior is None else prior + len(normal),
        level_upgrades=normal, evolutions=evolutions,
        level_upgrade_committed_count=len(normal), evolution_committed_count=len(evolutions),
    )
    committed = len(normal) + len(evolutions)
    counts_known = type(attempted) is int and committed <= attempted <= MAX_ACTIONS
    if not native_started:
        result.update(
            upgrade_transport_calls=0, evolution_transport_calls=0,
            total_action_count=0, committed_action_count=0,
            level_upgrade_committed_count=0, evolution_committed_count=0,
        )
        attempted, committed, counts_known = 0, 0, True
    accounting = outcome is not None and outcome.accounting_verified is True
    unknown = bool(
        result.get("unknown_action_sent") is True
        or result.get("effect_reconciliation_required") is True
        or native_started and (not accounting or not counts_known or attempted > 0)
    )
    count = outcome.input_count if outcome is not None else 0 if not native_started else None
    result.update(
        flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
        task_id=PRODUCT_ID, runtime_profile_id=PROFILE_ID,
        account_id=getattr(identity, "account_id", None),
        server_id=getattr(identity, "server_id", None), reset_id=getattr(identity, "reset_id", None),
        occurrence_key=occurrence_key, status="unknown" if unknown else "blocked", reason=reason,
        total_action_count=attempted if counts_known else None,
        committed_action_count=committed,
        unknown_action_sent=unknown, effect_reconciliation_required=unknown,
        identical_retry_denied=bool(result.get("identical_retry_denied") is True or unknown or attempted),
        input_count=count, total_input_count=count,
        accounting_verified=bool(accounting and counts_known), native_execution_verified=False,
        started_at_utc=started, completed_at_utc=completed, time_basis="utc",
    )
    return result


class WaliUpgradeRunner:
    """No store or device is opened until the canonical native boundary is called."""

    def __init__(self, *, native: NativeRouteBoundary | None = None, adb=BLUESTACKS_ADB,
                 serial=BLUESTACKS_SERIAL, output_directory: Path, utc_clock=time.time,
                 monotonic_clock=time.monotonic, settle_seconds: float = 0.65):
        self.native = native
        self.adb, self.serial = str(adb), str(serial)
        if Path(self.adb).resolve() != Path(BLUESTACKS_ADB).resolve() or self.serial != BLUESTACKS_SERIAL:
            raise ValueError("Wali requires its fixed BlueStacks backend")
        if native is not None and getattr(native, "flow_id", None) != FLOW_ID:
            raise ValueError("Wali native binding identity mismatch")
        if not callable(utc_clock) or not callable(monotonic_clock):
            raise ValueError("Wali requires UTC and monotonic clocks")
        self.output_directory = Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key):
        started = completed = None
        outcome = None
        result: dict[str, object] = {}
        native_started = False
        try:
            started = _epoch(self.utc_clock(), "start time")
            if self.native is None:
                raise ValueError("WALI_UPGRADE_NATIVE_BINDING_REQUIRED")
            if not isinstance(occurrence_key, str) or not occurrence_key:
                raise ValueError("Wali requires its claimed occurrence key")

            def validate_identity():
                return _backend(identity, _epoch(self.utc_clock(), "identity clock"), self.serial)

            validate_identity()
            checkpoint()
            request = NativeRouteRequest(
                flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
                runtime_profile_id=PROFILE_ID, identity=identity, previous_reset_id=previous_reset_id,
                occurrence_key=occurrence_key, checkpoint=checkpoint, validate_identity=validate_identity,
                runtime_input_lock=runtime_input_lock, adb=self.adb, serial=self.serial,
                output_directory=self.output_directory, max_inputs=MAX_INPUTS, max_actions=MAX_ACTIONS,
                settle_seconds=self.settle_seconds, arguments={},
                utc_clock=self.utc_clock, monotonic_clock=self.monotonic_clock,
            )
            native_started = True
            outcome = self.native.run(request)
            result = dict(outcome.native_result)
            if outcome.flow_id != FLOW_ID:
                raise ValueError("Wali native outcome flow mismatch")
            if not outcome.execution_verified:
                result = dict(outcome.partial_result or result)
                raise ValueError(outcome.failure or "WALI_UPGRADE_ACCOUNTING_UNVERIFIED")
            if type(outcome.input_count) is not int or not 0 <= outcome.input_count <= MAX_INPUTS:
                raise ValueError("Wali native input count exceeds its budget")
            _validate_result(result, game_day_id=identity.reset_id, occurrence_key=occurrence_key)
            completed = _epoch(self.utc_clock(), "completion time")
            if completed < started:
                raise ValueError("Wali completion clock predates its run")
            validate_identity()
            checkpoint()
            result.update(
                flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID, account_id=identity.account_id, server_id=identity.server_id,
                reset_id=identity.reset_id, runtime_profile_id=PROFILE_ID, occurrence_key=occurrence_key,
                input_count=outcome.input_count, total_input_count=outcome.input_count,
                accounting_verified=True, native_execution_verified=True,
                effect_reconciliation_required=result["unknown_action_sent"],
                started_at_utc=started, completed_at_utc=completed, time_basis="utc",
                session_directory=outcome.session_directory, startup_recovery=outcome.startup_recovery,
            )
            return result
        except Exception as exc:
            partial = dict(getattr(exc, "partial_result", {}) or {})
            if not partial:
                partial = dict(outcome.partial_result or result) if outcome is not None else result
            try:
                completed = _epoch(self.utc_clock(), "completion time")
                if started is not None and completed < started:
                    completed = None
            except Exception:
                completed = None
            return _failed(
                identity=identity, occurrence_key=occurrence_key, reason=str(exc), partial=partial,
                outcome=outcome, started=started, completed=completed, native_started=native_started,
            )


def wali_upgrade_next_due(result: Mapping[str, object], identity: SchedulerIdentity, started_at: float) -> float | None:
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Wali outcome requires its exact scheduler identity")
    started = _epoch(started_at, "start time")
    completed = _epoch(result.get("completed_at_utc"), "completion time")
    if completed < started or recruitment_reset(completed) != identity.reset_id:
        raise ValueError("Wali outcome is outside its claimed reset window")
    deadline = derive_static_utc_reset(datetime.fromtimestamp(completed, timezone.utc)).reset_deadline_utc.timestamp()
    if result.get("status") == "completed":
        return deadline
    if result.get("status") == "deferred":
        # Policy re-observation interval, not a claimed game cooldown or effect retry.
        return min(completed + RECHECK_SECONDS, deadline)
    return None
