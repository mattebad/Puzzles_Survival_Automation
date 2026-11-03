"""Canonical Personal Might daily execution over the existing Praise boundary."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from tasks.personal_might_praise import (
    FLOW_ID, SEMANTIC_ACTION, SOURCE_STATE, TARGET_IDENTITY, CONSEQUENCE,
    POSTCONDITION, personal_might_daily_key,
)
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import FlowDescriptor, FlowSpec, NormalizedOutcome, NormalizedResult
from .recruitment import recruitment_reset
from .registry import RegisteredDispatchSnapshot
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


PRODUCT_ID = "personal_might_praise"
PRODUCT_REVISION = "personal_might_praise-v1"
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = 8


class PersonalMightExecutionHandler:
    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = 1

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Personal Might execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Personal Might registration identity mismatch")
        if not callable(execute):
            raise TypeError("Personal Might executor must be callable")
        if flow_spec is not None:
            if not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID:
                raise ValueError("Personal Might requires its matching flow spec")
            self.flow_spec = flow_spec
        self.snapshot, self._execute = snapshot, execute

    def describe(self):
        return FlowDescriptor(flow_id=FLOW_ID, owner="automation_service", family=PRODUCT_ID,
            variant="one_daily_praise", cadence="daily_once_per_reset", reset_scoped=True,
            priority=1, scheduler_eligible=True, accepted_product=PRODUCT_ID,
            product_revision=PRODUCT_REVISION, registration_status="REGISTERED")

    def eligibility(self, facts, perception=None):
        return bool(not facts.gate_failures(self.describe())
            and facts.accepted_product == PRODUCT_ID and facts.product_revision == PRODUCT_REVISION
            and facts.registration_status == "REGISTERED" and facts.scheduler_eligible is True
            and (perception is None or perception.profile_id == PROFILE_ID))

    revalidate = eligibility

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)

    def plan(self, facts, perception=None):
        return self.recover("PERSONAL_MIGHT_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("PERSONAL_MIGHT_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class PersonalMightRunnerError(RuntimeError):
    def __init__(self, reason, *, partial_result):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Personal Might {name} must be a finite UTC epoch")
    return float(value)


def _scheduler_identity(identity, now):
    if (not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID
            or identity.reset_id != recruitment_reset(_epoch(now, "identity clock"))):
        raise ValueError("Personal Might requires its current scheduler game-day identity")


def _key(identity):
    return personal_might_daily_key(runtime_scope=identity.runtime_scope,
        account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id)


def _confirmed_action(store, identity, result):
    action = store.get_action_by_key(_key(identity))
    expected = {"action_id": result.get("action_id"), "task_id": FLOW_ID,
        "semantic_action": SEMANTIC_ACTION, "source_state": SOURCE_STATE,
        "target_identity": TARGET_IDENTITY, "game_day_id": identity.reset_id,
        "consequence": CONSEQUENCE, "expected_postcondition": POSTCONDITION,
        "cost_type": "none", "cost_amount": 0, "quantity": 1, "consequential": 1,
        "final_status": "confirmed"}
    if (action is None or result.get("action_key") != _key(identity)
            or any(action.get(field) != value for field, value in expected.items())):
        raise ValueError("Personal Might current-day canonical confirmation is not exact")
    return action


def _consumption(runtime, session):
    if runtime is None:
        return 0, 0, session is None or session.input_count == 0
    count, keys, actions = runtime.input_count, runtime.action_keys, runtime.frame_actions
    action_set = isinstance(actions, set) and all(isinstance(item, tuple) and len(item) == 3 for item in actions)
    calls = sum(item[1] == TARGET_IDENTITY for item in actions) if action_set else 0
    valid = (type(count) is int and 0 <= count <= MAX_INPUTS
        and isinstance(keys, set) and action_set
        and len(keys) == len(actions) == count and calls <= 1
        and session is not None and session.input_count == count)
    # A native reservation is consumed even if transport or its result is unknown.
    native_count = count if type(count) is int and count >= 0 else 0
    session_count = session.input_count if session is not None else 0
    return max(native_count, session_count), calls, bool(valid)


def _current_capture(runtime, value, expected_sha=None):
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png

    path = Path(value)
    path.resolve().relative_to(runtime.session.resolve())
    if path.is_symlink():
        raise ValueError("Personal Might current evidence cannot be a link")
    rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    captures = [row for row in rows if row.get("type") == "capture"]
    matches = [(ordinal, row) for ordinal, row in enumerate(captures, 1) if Path(row["path"]) == path]
    if len(matches) != 1:
        raise ValueError("Personal Might current capture must be unique")
    ordinal, row = matches[0]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row.get("sha256") or (expected_sha is not None and digest != expected_sha):
        raise ValueError("Personal Might current capture digest changed")
    frame = captured_native_frame_from_png(raw, path=path,
        captured_monotonic=_epoch(row.get("captured_monotonic"), "capture timestamp"))
    return frame, {"frame_path": path.relative_to(runtime.session).as_posix(), "frame_sha256": digest,
                   "observed_utc": row["timestamp"], "capture_ordinal": ordinal}


def _replay_source(runtime, captured, reference):
    from scripts.home_atlas_bluestacks import identity_from_captured
    return {"source_frame": identity_from_captured(captured, session_id=str(runtime.session),
                ordinal=reference["capture_ordinal"], label="personal-might-service-replay"),
            "source_png": captured.png}


class PersonalMightRunner:
    """Device-free construction; borrow the caller's actual held runtime owner."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path,
                 utc_clock=time.time, monotonic_clock=time.monotonic, settle_seconds=1.0):
        self.adb, self.serial, self.output_directory = adb, serial, Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock):
        from scripts import personal_might_praise_bluestacks as route
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts.flow_delivery_personal_might_bluestacks import _validate_identity
        from scripts.navigation_development_boundary import (
            DevelopmentInitialObservation, DevelopmentSession, open_canonical_action_store,
        )
        from scripts.startup_normalization import is_clean_home_frame
        from scripts.startup_recovery import recover_contextual_startup_overlay

        del previous_reset_id
        runtime, session, store, leased = None, None, None, False
        result, failure = {}, None
        started = None
        try:
            checkpoint()
            started = _epoch(self.utc_clock(), "start")
            _scheduler_identity(identity, started)
            binding = resource_fixed_runtime_binding()
            if self.serial != binding.serial or binding.runtime_profile_id != PROFILE_ID:
                raise ValueError("Personal Might requires the fixed BlueStacks backend")
            backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(started, timezone.utc))
            invocation = f"personal-might-{datetime.fromtimestamp(started, timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
            with DevelopmentSession(owner="automation-service:personal-might", invocation_id=invocation,
                    session_directory=self.output_directory / invocation, max_inputs=MAX_INPUTS,
                    runtime_input_lock=runtime_input_lock, checkpoint=checkpoint) as session:
                def current_checkpoint():
                    session.runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
                    checkpoint()
                    session.runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
                    now = _epoch(self.utc_clock(), "checkpoint")
                    _scheduler_identity(identity, now)
                    _validate_identity(backend, binding, datetime.fromtimestamp(now, timezone.utc))
                    if leased and not store.lease_valid_for(session.owner, now):
                        raise RuntimeError("Personal Might canonical action lease lost")

                current_checkpoint()
                store = open_canonical_action_store()
                if store.has_action_block():
                    raise RuntimeError("Personal Might canonical unresolved action requires inspection")
                store.acquire_lease(session.owner, self.utc_clock(), 600.0)
                leased = True
                runtime = LocalBlueStacksRuntime.connect(adb=self.adb, serial=self.serial,
                    output_directory=session.session_directory, workflow="personal-might-native", execute=True)
                runtime.checkpoint, runtime.max_inputs = current_checkpoint, MAX_INPUTS
                source = session.observe(runtime.capture, label="personal-might-canonical-startup-source")
                result["startup_recovery"] = {"input_count": 0, "resume_ready": False,
                    "source_context": "personal_might_canonical_startup", "events_path": "events.jsonl",
                    "reason": "startup_recovery_interrupted", "source_frame": _current_capture(runtime, source.path, source.sha256)[1]}
                try:
                    recovery = recover_contextual_startup_overlay(runtime, source,
                        source_context="personal_might_canonical_startup",
                        recognize_successor=lambda frame: is_clean_home_frame(frame.frame),
                        action_key=f"personal-might-startup:{invocation}")
                finally:
                    startup_count = runtime.input_count
                    result["startup_recovery"]["input_count"] = startup_count
                    if type(startup_count) is not int or startup_count < 0:
                        raise ValueError("Personal Might startup input accounting is invalid")
                    session.adopt_retained_transport_count(startup_count, source=str(runtime.events))
                    if startup_count > 2:
                        raise ValueError("Personal Might startup exceeded two inputs")
                result["startup_recovery"].update(reason=recovery.reason, dismissed=recovery.dismissed,
                    popup_absent=recovery.popup_absent, resume_ready=recovery.resume_ready,
                    reported_input_count=recovery.input_count,
                    steps=[step.to_mapping(runtime.session) for step in recovery.steps],
                    accounting_verified=type(recovery.input_count) is int and recovery.input_count == startup_count,
                    settled_frame=_current_capture(runtime, recovery.settled_frame.path, recovery.settled_frame.sha256)[1]
                        if recovery.settled_frame is not None else None)
                if (type(recovery.input_count) is not int or recovery.input_count != startup_count
                        or not recovery.resume_ready):
                    raise ValueError(f"Personal Might startup is not ready: {recovery.reason}")
                if startup_count:
                    source = session.observe(runtime.capture, label="personal-might-canonical-initial-home")
                source_binding = route._source(runtime, source)
                if (runtime.measure_foreground_package() != "com.global.ztmslg"
                        or not is_clean_home_frame(source.frame)
                        or (route.vision.more_menu_present(source.frame, **source_binding)
                            and not route.vision.recognize_more_menu(source.frame, **source_binding, home_is_clean=is_clean_home_frame))):
                    raise ValueError("Personal Might requires fresh Home or its recognized More menu")
                session.set_initial_observation(DevelopmentInitialObservation(
                    {"frame_sha256": source.sha256, "device_state": "device",
                     "foreground_package": "com.global.ztmslg", "native_width": 800, "native_height": 1280},
                    source.sha256, frame_path=source.path.relative_to(session.session_directory).as_posix(),
                    invocation_id=invocation))
                result.update(source_frame={"frame_path": source.path.relative_to(runtime.session).as_posix(),
                                            "frame_sha256": source.sha256}, backend_identity=asdict(backend))
                boundary = route.PersonalMightPraiseBoundary(session=session, runtime=runtime,
                    store=store, identity=backend, validate_identity=current_checkpoint,
                    settle_seconds=self.settle_seconds, monotonic_clock=self.monotonic_clock,
                    wall_clock=self.utc_clock)
                result.update(route.run(session=session, runtime=runtime,
                    settle_seconds=self.settle_seconds, praise_boundary=boundary))
                count, calls, accounting = _consumption(runtime, session)
                if (not accounting or result.get("status") != "completed"
                        or result.get("journal_status") != "confirmed"
                        or result.get("terminal_home_verified") is not True
                        or result.get("effect_reconciliation_required")
                        or result.get("praise_transport_calls") != calls):
                    raise ValueError(str(result.get("reason") or "Personal Might native route is not verified"))
                _confirmed_action(store, backend, result)
                home, home_ref = _current_capture(runtime, result["successor_frame"], result.get("successor_sha256"))
                if (not is_clean_home_frame(home.frame)
                        or route.vision.more_menu_present(home.frame, **_replay_source(runtime, home, home_ref))
                        or not 0 <= self.monotonic_clock() - home.captured_monotonic <= 30):
                    raise ValueError("Personal Might current terminal Home is not proven")
                if calls == 0 and result.get("no_work") is True:
                    rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines() if line.strip()]
                    candidates = [row["path"] for row in rows if row.get("type") == "capture" and row.get("label") == "personal-might-already-praised"]
                    if len(candidates) != 1:
                        raise ValueError("Personal Might no-work requires its current gray observation")
                    gray_path = candidates[0]
                elif calls == 1 and result.get("no_work") is not True and result.get("praise_result_frames"):
                    gray_path = result["praise_result_frames"][-1]
                else:
                    raise ValueError("Personal Might action/no-work accounting is contradictory")
                gray, gray_ref = _current_capture(runtime, gray_path)
                if not route.vision.personal_might_praised(gray.frame, **_replay_source(runtime, gray, gray_ref)):
                    raise ValueError("Personal Might current gray Rank 1 is not proven")
                current_checkpoint()
                result.update(status="complete_for_reset" if calls else "already_complete",
                    terminal_home_frame=home_ref, praise_result_frame=gray_ref,
                    terminal_home_verified=True, effect_reconciliation_required=False,
                    identical_retry_denied=False, committed_action_count=calls)
                session.terminal_status = "completed"
        except Exception as exc:
            failure = exc
        finally:
            if store is not None:
                try:
                    if leased:
                        store.release_lease(session.owner, self.utc_clock())
                except Exception as exc:
                    failure = RuntimeError(f"{failure}; {exc}" if failure else str(exc))
                finally:
                    try:
                        store.close()
                    except Exception as exc:
                        failure = RuntimeError(f"{failure}; {exc}" if failure else str(exc))
        count, calls, accounting = _consumption(runtime, session)
        try:
            completed = _epoch(self.utc_clock(), "completion")
        except Exception as exc:
            completed = None
            failure = RuntimeError(f"{failure}; {exc}" if failure else str(exc))
        result.update(flow_id=FLOW_ID, task_id=PRODUCT_ID, runtime_profile_id=PROFILE_ID,
            account_id=getattr(identity, "account_id", None), server_id=getattr(identity, "server_id", None),
            reset_id=getattr(identity, "reset_id", None), time_basis="utc", completed_at_utc=completed,
            total_input_count=count, input_count=count, praise_transport_calls=calls,
            accounting_verified=accounting, session_directory=str(runtime.session) if runtime else None)
        result["route_input_count"] = count - result.get("startup_recovery", {}).get("input_count", 0)
        if failure is None:
            result["next_eligible_at"] = (math.floor(result["completed_at_utc"] / 86400) + 1) * 86400
            try:
                personal_might_next_due(result, identity, started)
            except Exception as exc:
                failure = exc
        if failure is not None:
            result.update(status="unresolved" if count else "blocked", reason=str(failure),
                effect_reconciliation_required=bool(calls), identical_retry_denied=bool(count))
        if runtime is not None:
            try:
                (runtime.session / "personal-might-result.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                failure = exc
                result.update(status="unresolved", reason=str(exc), effect_reconciliation_required=bool(calls), identical_retry_denied=True)
        if failure is not None:
            raise PersonalMightRunnerError(str(failure), partial_result=result) from failure
        return result


def personal_might_next_due(result, identity, started_at):
    """Accept only this run's confirmed daily Praise or confirmed gray no-work/Home."""
    completed = _epoch(result.get("completed_at_utc"), "completion")
    _scheduler_identity(identity, completed)
    if (completed < _epoch(started_at, "start") or recruitment_reset(started_at) != identity.reset_id
            or result.get("time_basis") != "utc" or result.get("runtime_profile_id") != PROFILE_ID
            or (result.get("account_id"), result.get("server_id"), result.get("reset_id"), result.get("task_id")) != (
                identity.account_id, identity.server_id, identity.reset_id, PRODUCT_ID)
            or result.get("flow_id") != FLOW_ID or result.get("terminal_home_verified") is not True
            or result.get("journal_status") != "confirmed" or result.get("accounting_verified") is not True
            or result.get("effect_reconciliation_required") or result.get("identical_retry_denied")):
        raise ValueError("Personal Might result identity, confirmation, accounting or Home is not verified")
    inputs, calls, committed = (result.get(field) for field in (
        "total_input_count", "praise_transport_calls", "committed_action_count"))
    if (type(inputs) is not int or not 0 <= inputs <= MAX_INPUTS
            or any(type(value) is not int or value not in (0, 1) for value in (calls, committed))
            or committed != calls or calls > inputs):
        raise ValueError("Personal Might input/effect counts are invalid")
    if result.get("status") == "already_complete":
        if calls or result.get("no_work") is not True:
            raise ValueError("Personal Might already-complete requires zero Praise and current gray proof")
    elif result.get("status") == "complete_for_reset":
        if calls != 1 or result.get("no_work") is True:
            raise ValueError("Personal Might completion requires one current confirmed Praise")
    else:
        raise ValueError("Personal Might unknown or pending result requires inspection")
    from scripts.flow_delivery_personal_might_bluestacks import _validate_identity
    from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
    try:
        recorded = dict(result.get("backend_identity") or {})
        recorded["assurance"] = RuntimeIdentityAssurance(recorded["assurance"])
        recorded["evidence_refs"] = tuple(recorded["evidence_refs"])
        backend = VerifiedRuntimeIdentity(**recorded)
        _validate_identity(backend, resource_fixed_runtime_binding(), datetime.fromtimestamp(completed, timezone.utc))
        if result.get("action_key") != _key(backend):
            raise ValueError("daily key mismatch")
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise ValueError("Personal Might backend fixed-slot daily identity is not exact") from exc
    for field in ("source_frame", "praise_result_frame", "terminal_home_frame"):
        proof = result.get(field)
        if (not isinstance(proof, dict) or not proof.get("frame_path")
                or not isinstance(proof.get("frame_sha256"), str) or len(proof["frame_sha256"]) != 64):
            raise ValueError("Personal Might current source/gray/Home proof is incomplete")
    due = (math.floor(completed / 86400) + 1) * 86400
    if result.get("next_eligible_at") != due:
        raise ValueError("Personal Might next deadline must be the next UTC reset")
    return due
