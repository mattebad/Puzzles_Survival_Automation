"""Canonical aggregate Daily rewards execution over the existing native route."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import time
from typing import Any, Mapping

from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.activity_milestones import ACTIVITY_MILESTONE_TARGET
from tasks.available_daily_claim import DAILY_QUEST_CLAIM_TARGET
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from .recruitment import recruitment_reset
from .registry import (
    DAILY_REWARDS_FLOW_ID,
    DAILY_REWARDS_MAX_INPUTS,
    DAILY_REWARDS_PRODUCT_ID,
    DAILY_REWARDS_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    canonical_entry,
)


FLOW_ID = DAILY_REWARDS_FLOW_ID
PRODUCT_ID = DAILY_REWARDS_PRODUCT_ID
PRODUCT_REVISION = DAILY_REWARDS_PRODUCT_REVISION
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = DAILY_REWARDS_MAX_INPUTS
MAX_ACTIONS = 6
OBSERVATION_INTERVAL_SECONDS = 300


class DailyRewardsExecutionHandler:
    """Use normal scheduler admission and delegate only the active service run."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Daily rewards execution requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Daily rewards registration identity mismatch")
        if not callable(execute):
            raise TypeError("Daily rewards executor must be callable")
        if flow_spec is not None:
            if not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID:
                raise ValueError("Daily rewards requires its matching flow spec")
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
        return self.recover("DAILY_REWARDS_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("DAILY_REWARDS_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class DailyRewardsRunnerError(RuntimeError):
    def __init__(self, reason: str, *, partial_result: Mapping[str, Any]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Daily rewards {name} must be a finite UTC epoch")
    return float(value)


def _scheduler_identity(identity: Any, now: Any) -> None:
    if (
        not isinstance(identity, SchedulerIdentity)
        or identity.task_id != PRODUCT_ID
        or identity.reset_id != recruitment_reset(_epoch(now, "identity clock"))
    ):
        raise ValueError("Daily rewards requires its current scheduler game-day identity")


def _backend_identity(identity: SchedulerIdentity, binding, now: float):
    backend = derive_resource_runtime_identity(
        binding, datetime.fromtimestamp(now, timezone.utc)
    )
    expected_reset = derive_static_utc_reset(
        datetime.fromtimestamp(now, timezone.utc)
    ).reset_identity_id
    if (
        backend.account_id != identity.account_id
        or backend.server_id != identity.server_id
        or backend.reset_id != expected_reset
    ):
        raise ValueError("Daily rewards scheduler and fixed runtime identity differ")
    return backend


def _backend_mapping(backend) -> dict[str, Any]:
    value = asdict(backend)
    value["assurance"] = backend.assurance.value
    value["evidence_refs"] = list(backend.evidence_refs)
    return value


def _outcome_payload(outcome: Any) -> dict[str, Any]:
    if isinstance(outcome, Mapping):
        return dict(outcome)
    partial = getattr(outcome, "partial_result", None)
    if isinstance(partial, Mapping):
        return dict(partial)
    if getattr(outcome, "failure", None) is not None:
        return {}
    for name in ("native_result", "result"):
        value = getattr(outcome, name, None)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _evidence_pair(value: Mapping[str, Any], label: str) -> None:
    source = value.get("source_frame_sha256")
    successor = value.get("successor_frame_sha256")
    if (
        not _valid_sha256(source)
        or not _valid_sha256(successor)
        or source == successor
    ):
        raise ValueError(f"Daily rewards {label} lacks distinct source/successor frame evidence")


def daily_rewards_next_due(
    result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float
) -> float:
    """Admit only exact verified completion and schedule a bounded observation pulse."""
    if not isinstance(result, Mapping):
        raise ValueError("Daily rewards result must be a mapping")
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Daily rewards outcome requires its exact task identity")
    started = _epoch(started_at, "start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    _scheduler_identity(identity, completed)
    if (
        completed < started
        or recruitment_reset(started) != identity.reset_id
        or result.get("status") != "completed"
        or result.get("time_basis") != "utc"
        or result.get("runtime_profile_id") != PROFILE_ID
        or (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or type(result.get("effect_reconciliation_required")) is not bool
        or result.get("effect_reconciliation_required") is not False
        or type(result.get("identical_retry_denied")) is not bool
    ):
        raise ValueError("Daily rewards result identity, accounting, effect, or Home is unverified")

    interval = result.get("observation_interval_seconds")
    due = _epoch(result.get("next_due_at_utc"), "next observation")
    if (
        type(interval) is not int
        or not 1 <= interval <= 86400
        or due != completed + interval
    ):
        raise ValueError("Daily rewards observation deadline is not the exact configured interval")

    inputs = result.get("total_input_count")
    actions = result.get("total_action_count")
    calls = result.get("reward_claim_transport_calls")
    committed = result.get("committed_action_count")
    if (
        type(inputs) is not int
        or not 0 <= inputs <= MAX_INPUTS
        or type(actions) is not int
        or not 0 <= actions <= MAX_ACTIONS
        or type(calls) is not int
        or calls != actions
        or type(committed) is not int
        or committed != actions
        or actions > inputs
    ):
        raise ValueError("Daily rewards input and canonical action accounting is invalid")

    aggregate = result.get("aggregate_claim")
    chests = result.get("chests_collected")
    if not isinstance(aggregate, Mapping) or not isinstance(chests, list):
        raise ValueError("Daily rewards aggregate/chest accounting is missing")
    aggregate_dispatches = aggregate.get("dispatch_count")
    if (
        type(aggregate_dispatches) is not int
        or aggregate_dispatches not in (0, 1)
        or aggregate.get("status") != ("confirmed" if aggregate_dispatches else "none")
        or aggregate.get("confirmed") is not (aggregate_dispatches == 1)
    ):
        raise ValueError("Daily rewards aggregate batch is not exactly none-or-confirmed-once")
    if aggregate_dispatches:
        if (
            not isinstance(aggregate.get("batch_identity"), str)
            or not aggregate["batch_identity"].strip()
            or aggregate.get("reset_id") != identity.reset_id
            or aggregate.get("ready_batch_proven") is not True
            or aggregate.get("free_only") is not True
            or aggregate.get("control_identity") != DAILY_QUEST_CLAIM_TARGET
            or aggregate.get("ordinary_claim_controls_cleared") is not True
        ):
            raise ValueError("Daily rewards aggregate lacks exact current free batch/reset evidence")
        _evidence_pair(aggregate, "aggregate claim")

    chest_keys: set[str] = set()
    for chest in chests:
        if not isinstance(chest, Mapping):
            raise ValueError("Daily rewards chest result is malformed")
        key = chest.get("milestone_key")
        if (
            not isinstance(key, str)
            or not key.strip()
            or key in chest_keys
            or chest.get("status") != "confirmed"
            or chest.get("reset_id") != identity.reset_id
            or chest.get("target_identity") != ACTIVITY_MILESTONE_TARGET
            or chest.get("control_class") != "MILESTONE_CHEST"
            or chest.get("ready_state_proven") is not True
            or chest.get("free_only") is not True
            or chest.get("cost_type") != "none"
            or chest.get("successor_milestone_key") != key
            or chest.get("successor_state") not in {"claimed", "opened", "removed"}
        ):
            raise ValueError("Daily rewards chest lacks exact ready/free same-chest successor evidence")
        _evidence_pair(chest, "milestone chest")
        chest_keys.add(key)
    scan = result.get("milestone_scan")
    ready_keys = scan.get("ready_chest_keys") if isinstance(scan, Mapping) else None
    static_keys = scan.get("static_or_locked_chest_keys") if isinstance(scan, Mapping) else None
    if (
        not isinstance(scan, Mapping)
        or scan.get("status") != "verified"
        or scan.get("selected_daily") is not True
        or scan.get("reset_id") != identity.reset_id
        or not _valid_sha256(scan.get("source_frame_sha256"))
        or type(scan.get("ready_chest_count")) is not int
        or not isinstance(ready_keys, list)
        or any(not isinstance(key, str) or not key.strip() for key in ready_keys)
        or len(set(ready_keys)) != len(ready_keys)
        or scan.get("ready_chest_count") != len(ready_keys)
        or set(ready_keys) != chest_keys
        or not isinstance(static_keys, list)
        or any(not isinstance(key, str) or not key.strip() for key in static_keys)
        or len(set(static_keys)) != len(static_keys)
        or set(ready_keys) & set(static_keys)
        or len(ready_keys) + len(static_keys) != 5
    ):
        raise ValueError("Daily rewards lacks a complete current Daily chest-state scan")

    if actions != aggregate_dispatches + len(chests):
        raise ValueError("Daily rewards committed actions do not reconcile with aggregate/chests")
    if (
        type(result.get("unclaimed_ready_chest_count")) is not int
        or result.get("unclaimed_ready_chest_count") != 0
    ):
        raise ValueError("Daily rewards left a ready chest unclaimed or failed to prove the chest scan")
    no_work = result.get("no_work")
    if type(no_work) is not bool or no_work != (actions == 0):
        raise ValueError("Daily rewards no-work classification differs from confirmed actions")
    if no_work:
        evidence = result.get("no_work_evidence")
        locked_keys = evidence.get("static_or_locked_chest_keys") if isinstance(evidence, Mapping) else None
        if (
            aggregate.get("status") != "none"
            or chests
            or not isinstance(evidence, Mapping)
            or evidence.get("selected_daily") is not True
            or evidence.get("reset_id") != identity.reset_id
            or not _valid_sha256(evidence.get("source_frame_sha256"))
            or type(evidence.get("ordinary_claim_controls")) is not int
            or evidence.get("ordinary_claim_controls") != 0
            or type(evidence.get("ready_chest_count")) is not int
            or evidence.get("ready_chest_count") != 0
            or not isinstance(locked_keys, list)
            or not locked_keys
            or any(not isinstance(key, str) or not key.strip() for key in locked_keys)
            or len(set(locked_keys)) != len(locked_keys)
        ):
            raise ValueError("Daily rewards no-work requires exact current Daily/control/chest evidence")
        if (
            ready_keys
            or static_keys != locked_keys
            or evidence.get("source_frame_sha256") != scan.get("source_frame_sha256")
        ):
            raise ValueError("Daily rewards no-work chest scan does not match its locked/static evidence")
    if actions > 0 and result.get("identical_retry_denied") is not True:
        raise ValueError("Daily rewards confirmed batch must deny its identical retry")

    home = result.get("terminal_home_frame")
    if (
        not isinstance(home, Mapping)
        or not isinstance(home.get("frame_path"), str)
        or not home["frame_path"]
        or Path(home["frame_path"]).is_absolute()
        or ".." in Path(home["frame_path"]).parts
        or not _valid_sha256(home.get("frame_sha256"))
    ):
        raise ValueError("Daily rewards terminal Home current-frame proof is missing")
    session_directory = result.get("native_session_directory")
    if not isinstance(session_directory, str) or not session_directory:
        raise ValueError("Daily rewards native session directory is missing")
    session_root = Path(session_directory).resolve()
    home_path = (session_root / home["frame_path"]).resolve()
    if (
        not home_path.is_relative_to(session_root)
        or not home_path.is_file()
        or hashlib.sha256(home_path.read_bytes()).hexdigest() != home["frame_sha256"]
    ):
        raise ValueError("Daily rewards terminal Home frame does not match retained native evidence")

    backend = result.get("backend_identity")
    if not isinstance(backend, Mapping):
        raise ValueError("Daily rewards fixed runtime identity proof is missing")
    binding = resource_fixed_runtime_binding()
    expected = _backend_identity(identity, binding, completed)
    expected_mapping = _backend_mapping(expected)
    if dict(backend) != expected_mapping:
        raise ValueError("Daily rewards fixed runtime identity evidence is not exact")
    return due


class DailyRewardsRunner:
    """Device-free adapter; use only the caller's borrowed canonical native boundary."""

    def __init__(
        self,
        *,
        native: NativeRouteBoundary | None,
        adb: str | Path = BLUESTACKS_ADB,
        serial: str = BLUESTACKS_SERIAL,
        output_directory: Path,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        settle_seconds: float = 1.0,
        observation_interval_seconds: int = OBSERVATION_INTERVAL_SECONDS,
    ) -> None:
        if type(observation_interval_seconds) is not int or not 1 <= observation_interval_seconds <= 86400:
            raise ValueError("Daily rewards observation interval must be an integer from 1 to 86400")
        self.native = native
        if native is not None:
            expected_binding = (
                FLOW_ID,
                PRODUCT_ID,
                PRODUCT_REVISION,
                PROFILE_ID,
                MAX_INPUTS,
                MAX_ACTIONS,
            )
            actual_binding = tuple(
                getattr(native, field, None)
                for field in (
                    "flow_id",
                    "product_id",
                    "product_revision",
                    "runtime_profile_id",
                    "max_inputs",
                    "max_actions",
                )
            )
            if actual_binding != expected_binding or not callable(
                getattr(native, "run", None)
            ):
                raise ValueError("Daily rewards native boundary binding identity mismatch")
        self.adb = str(adb)
        self.serial = serial
        self.output_directory = Path(output_directory)
        self.utc_clock = utc_clock
        self.monotonic_clock = monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")
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
        partial: dict[str, Any] = {}
        try:
            checkpoint()
            started = _epoch(self.utc_clock(), "start")
            _scheduler_identity(identity, started)
            if not isinstance(occurrence_key, str) or not occurrence_key.strip():
                raise ValueError("Daily rewards requires the persisted scheduler occurrence key")
            if self.native is None or not callable(getattr(self.native, "run", None)):
                raise RuntimeError("Daily rewards canonical native boundary is unavailable")
            lock_invocation = getattr(runtime_input_lock, "invocation_id", None)
            if (
                getattr(runtime_input_lock, "owner", None) != "automation-service"
                or getattr(runtime_input_lock, "held", None) is not True
                or not isinstance(lock_invocation, str)
                or not lock_invocation
                or not callable(getattr(runtime_input_lock, "assert_held", None))
            ):
                raise ValueError("Daily rewards requires the held automation-service runtime lock")
            runtime_input_lock.assert_held("automation-service", lock_invocation)
            binding = resource_fixed_runtime_binding()
            if (
                Path(self.adb).resolve() != Path(BLUESTACKS_ADB).resolve()
                or self.serial != binding.serial
                or binding.runtime_profile_id != PROFILE_ID
            ):
                raise ValueError("Daily rewards requires the fixed BlueStacks backend")
            backend = _backend_identity(identity, binding, started)

            def validate_identity() -> None:
                now = _epoch(self.utc_clock(), "identity checkpoint")
                _scheduler_identity(identity, now)
                current = _backend_identity(identity, binding, now)
                if current.runtime_binding_digest != backend.runtime_binding_digest:
                    raise ValueError("Daily rewards fixed runtime binding changed during invocation")

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
                arguments={"observation_interval_seconds": self.observation_interval_seconds},
            )
            outcome = self.native.run(request)
            if not isinstance(outcome, NativeRouteOutcome):
                raise RuntimeError("Daily rewards native boundary returned an untyped outcome")
            if (
                outcome.flow_id != FLOW_ID
                or not outcome.invocation_id
                or not outcome.session_directory
            ):
                raise RuntimeError("Daily rewards native outcome identity is incomplete")
            partial.update(_outcome_payload(outcome))
            partial.update(
                accounting_verified=outcome.accounting_verified is True,
                total_input_count=outcome.input_count,
                session_input_count=outcome.session_input_count,
                runtime_input_count=outcome.runtime_input_count,
                native_invocation_id=outcome.invocation_id,
                native_session_directory=outcome.session_directory,
            )
            if outcome.failure is not None:
                partial["native_failure"] = outcome.failure
                raise RuntimeError(f"Daily rewards native boundary failed: {outcome.failure}")
            accounting_counts = (
                outcome.input_count,
                outcome.session_input_count,
                outcome.runtime_input_count,
            )
            counts_valid = bool(
                all(type(count) is int and 0 <= count <= MAX_INPUTS for count in accounting_counts)
                and accounting_counts[0] == accounting_counts[1] == accounting_counts[2]
            )
            partial["accounting_verified"] = bool(
                outcome.accounting_verified is True and counts_valid
            )
            if not partial["accounting_verified"]:
                raise RuntimeError("Daily rewards native input accounting is inconsistent")
            output_root = self.output_directory.resolve()
            native_session = Path(outcome.session_directory).resolve()
            if (
                native_session == output_root
                or not native_session.is_relative_to(output_root)
                or not native_session.is_dir()
            ):
                raise RuntimeError("Daily rewards native session is outside the fixed output directory")
            partial["native_session_directory"] = str(native_session)
            now = _epoch(self.utc_clock(), "completion")
            completed = _epoch(partial.get("completed_at_utc", now), "completion")
            completed_backend = _backend_identity(identity, binding, completed)
            partial.update(
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                account_id=identity.account_id,
                server_id=identity.server_id,
                reset_id=identity.reset_id,
                runtime_profile_id=PROFILE_ID,
                time_basis="utc",
                started_at_utc=started,
                completed_at_utc=completed,
                observation_interval_seconds=self.observation_interval_seconds,
                next_due_at_utc=completed + self.observation_interval_seconds,
                occurrence_key=occurrence_key,
                backend_identity=_backend_mapping(completed_backend),
            )
            if partial.get("status") != "completed":
                raise RuntimeError(str(partial.get("reason") or "Daily rewards native route is not complete"))
            if (
                partial.get("terminal_home_verified") is not True
                or partial.get("effect_reconciliation_required") is not False
                or partial.get("accounting_verified") is not True
            ):
                raise RuntimeError("Daily rewards native owner/lease/state, Home, or reconciliation proof is incomplete")
            return partial
        except Exception as exc:
            payload = getattr(exc, "partial_result", None)
            if isinstance(payload, Mapping):
                partial.update(payload)
            has_dispatch = bool(
                partial.get("reward_claim_transport_calls")
                or partial.get("total_action_count")
            )
            partial["status"] = (
                "unresolved"
                if has_dispatch
                and partial.get("effect_reconciliation_required") is not False
                else "blocked"
            )
            partial.setdefault("reason", str(exc))
            if has_dispatch:
                partial.setdefault(
                    "effect_reconciliation_required",
                    partial["status"] == "unresolved",
                )
                partial["identical_retry_denied"] = True
            raise DailyRewardsRunnerError(str(exc), partial_result=partial) from exc


__all__ = [
    "DAILY_REWARDS_MAX_ACTIONS",
    "DailyRewardsExecutionHandler",
    "DailyRewardsRunner",
    "DailyRewardsRunnerError",
    "FLOW_ID",
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "OBSERVATION_INTERVAL_SECONDS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "daily_rewards_next_due",
]

DAILY_REWARDS_MAX_ACTIONS = MAX_ACTIONS
