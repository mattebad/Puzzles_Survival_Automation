"""Canonical Bioenhancer execution through the existing bounded native route."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4

import cv2

from scripts.flow_delivery_bioenhancer_bluestacks import FLOW_ID, MAX_INPUTS
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation, DevelopmentSession,
)

from .contracts import FlowDescriptor, NormalizedOutcome, NormalizedResult
from .registry import RegisteredDispatchSnapshot


PRODUCT_ID = "bioenhancer_research"
PRODUCT_REVISION = "bioenhancer_research-v1"
PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"


class BioenhancerNativePartialResultError(RuntimeError):
    def __init__(self, message, *, partial_result):
        super().__init__(message)
        self.partial_result = dict(partial_result)


class BioenhancerExecutionHandler:
    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = 1

    def __init__(self, snapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Bioenhancer execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID,
        ):
            raise ValueError("Bioenhancer registration identity mismatch")
        if not callable(execute):
            raise TypeError("Bioenhancer executor must be callable")
        self.snapshot, self._execute = snapshot, execute

    def describe(self):
        return FlowDescriptor(
            flow_id=FLOW_ID, owner="automation_service", family=PRODUCT_ID,
            variant="one_free_pulse", cadence="cooldown_pulse", reset_scoped=False,
            priority=1, scheduler_eligible=True, accepted_product=PRODUCT_ID,
            product_revision=PRODUCT_REVISION, registration_status="REGISTERED",
        )

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
        return self.recover("BIOENHANCER_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("BIOENHANCER_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


def _epoch(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Bioenhancer {label} must be a finite UTC epoch")
    return float(value)


def _consumption(runtime):
    if runtime is None:
        return 0, 0, True
    count = getattr(runtime, "input_count", None)
    keys = getattr(runtime, "action_keys", None)
    valid = type(count) is int and 0 <= count <= MAX_INPUTS and isinstance(keys, set)
    calls = sum(str(key).startswith("free-research-1x:") for key in keys) if isinstance(keys, set) else 0
    valid = bool(valid and len(keys) == count and calls <= 1)
    return count if type(count) is int else 0, calls, valid


def _current_cooldown(runtime, result):
    from scripts.bioenhancer_free_research_canary import recognize_free_research_cooldown

    if result.get("no_work") is True:
        return dict(result.get("cooldown") or {})
    # These are captures from this just-executed route, never imported history.
    rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    captures = [row for row in rows if row.get("type") == "capture"
                and row.get("label") == "free-research-post-settled"
                and row.get("sha256") == result.get("post_sha256")]
    if len(captures) != 1:
        raise ValueError("Bioenhancer consuming result lacks exact cooldown capture")
    capture = captures[0]
    path = Path(capture["path"])
    path.resolve().relative_to(runtime.session.resolve())
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != result["post_sha256"]:
        raise ValueError("Bioenhancer cooldown capture changed")
    cooldown = recognize_free_research_cooldown(
        cv2.imread(str(path)), now=datetime.fromisoformat(capture["timestamp"]),
    )
    if cooldown is None:
        raise ValueError("Bioenhancer consuming cooldown is not recognized")
    return {**cooldown, "frame_path": path.relative_to(runtime.session).as_posix(),
            "frame_sha256": capture["sha256"]}


def _startup_context(session, runtime, initial, result):
    from scripts.bioenhancer_free_research_canary import bind_bioenhancer_back
    from scripts.startup_normalization import is_clean_home_frame
    from scripts.startup_recovery import recover_contextual_startup_overlay

    def reference(captured):
        return {"frame_path": captured.path.relative_to(runtime.session).as_posix(),
                "frame_sha256": captured.sha256}

    startup = {"source_context": "bioenhancer_canonical_startup",
               "initial_frame": reference(initial), "events_path": "events.jsonl",
               "input_count": 0, "resume_ready": False, "accounting_verified": False}
    result["startup_recovery"] = startup
    recovered = None
    try:
        recovered = recover_contextual_startup_overlay(
            runtime, initial, source_context=startup["source_context"],
            recognize_successor=lambda captured: bool(
                is_clean_home_frame(captured.frame)
                or bind_bioenhancer_back(captured.frame) is not None),
            action_key=f"bioenhancer-startup:{session.invocation_id}",
        )
        startup.update(dismissed=recovered.dismissed, popup_absent=recovered.popup_absent,
                       resume_ready=recovered.resume_ready, reason=recovered.reason,
                       reported_input_count=recovered.input_count)
        if recovered.settled_frame is not None:
            startup["settled_frame"] = reference(recovered.settled_frame)
    except Exception as exc:
        startup["reason"] = str(exc)
        raise
    finally:
        count, calls, accounting = _consumption(runtime)
        startup.update(input_count=count, accounting_verified=bool(
            accounting and calls == 0 and 0 <= count <= 1
            and (recovered is None or recovered.input_count == count)))
        # The shared helper dispatches directly on this same runtime. Preserve
        # that input before any failure, then let ordinary route actions count.
        session.adopt_retained_transport_count(count, source="events.jsonl:contextual-startup")
    if not startup["accounting_verified"] or not recovered.resume_ready:
        raise ValueError(str(startup.get("reason") or "Bioenhancer startup is not verified"))
    if startup["input_count"]:
        home = session.observe(runtime.capture, label="bioenhancer-startup-clean-home")
        startup["home_frame"] = reference(home)
        if not is_clean_home_frame(home.frame):
            raise ValueError("Bioenhancer startup popup did not return to fresh clean Home")
        return home
    return initial


class BioenhancerRunner:
    """Device-free construction; execute only under the caller's held run owner."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path, utc_clock=time.time):
        self.adb, self.serial = adb, serial
        self.output_directory = Path(output_directory)
        self.utc_clock = utc_clock

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts.bioenhancer_free_research_canary import run
        from scripts.flow_delivery_bioenhancer_bluestacks import _verify_no_work_frames

        del previous_reset_id
        if identity.task_id != PRODUCT_ID:
            raise ValueError("Bioenhancer task identity mismatch")
        runtime, result = None, {}
        try:
            checkpoint()
            started = _epoch(self.utc_clock(), "start")
            invocation = f"bioenhancer-{datetime.fromtimestamp(started, timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
            with DevelopmentSession(
                owner="automation-service:bioenhancer", invocation_id=invocation,
                session_directory=self.output_directory / invocation,
                max_inputs=MAX_INPUTS, runtime_input_lock=runtime_input_lock,
                checkpoint=checkpoint,
            ) as session:
                owner_fence = runtime_input_lock.owner, runtime_input_lock.invocation_id

                def current_checkpoint():
                    session.runtime_input_lock.assert_held(*owner_fence)
                    checkpoint()
                    session.runtime_input_lock.assert_held(*owner_fence)

                runtime = LocalBlueStacksRuntime.connect(
                    adb=self.adb, serial=self.serial, output_directory=session.session_directory,
                    workflow="bioenhancer-native", execute=True,
                )
                runtime.checkpoint, runtime.max_inputs = current_checkpoint, MAX_INPUTS
                initial = session.observe(runtime.capture, label="bioenhancer-canonical-initial")
                initial = _startup_context(session, runtime, initial, result)
                session.set_initial_observation(DevelopmentInitialObservation(
                    {"frame_sha256": initial.sha256, "device_state": "device",
                     "foreground_package": "com.global.ztmslg", "native_width": 800, "native_height": 1280},
                    initial.sha256, frame_path=initial.path.relative_to(session.session_directory).as_posix(),
                    invocation_id=invocation,
                ))
                result.update(run(session=session, runtime=runtime, session_directory=runtime.session,
                                  max_inputs=MAX_INPUTS, settle_seconds=1.))
                count, calls, accounting = _consumption(runtime)
                if not accounting or count != session.input_count:
                    raise ValueError("Bioenhancer native input accounting mismatch")
                if result.get("status") != "completed":
                    raise ValueError(str(result.get("reason") or "Bioenhancer native route did not complete"))
                cooldown = _current_cooldown(runtime, result)
                home = result.get("terminal_home_frame") or result.get("return_home", {}).get("terminal_home_frame")
                result = dict(result, cooldown=cooldown, terminal_home_frame=home,
                              next_due_utc=cooldown.get("next_due_utc"))
                verified_frames = _verify_no_work_frames(runtime.session, result)
                returned = result.get("return_home", {}).get("status") == "home_returned"
                result.update(
                    flow_id=FLOW_ID, account_id=identity.account_id, server_id=identity.server_id,
                    reset_id=identity.reset_id, time_basis="utc",
                    completed_at_utc=_epoch(self.utc_clock(), "completion"),
                    total_input_count=count, input_count=count,
                    route_input_count=count - result["startup_recovery"]["input_count"],
                    free_research_transport_calls=calls, accounting_verified=True,
                    terminal_home_verified=bool(returned and verified_frames),
                    cooldown_proof_verified=verified_frames,
                    effect_reconciliation_required=bool(calls and (result.get("status") != "completed" or not verified_frames)),
                    identical_retry_denied=bool(result.get("status") != "completed"),
                    session_directory=str(runtime.session),
                )
                checkpoint()
                bioenhancer_next_due(result, identity, started)
                (session.session_directory / "bioenhancer-result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                )
                return result
        except Exception as exc:
            count, calls, accounting = _consumption(runtime)
            accounting = bool(accounting and result.get("startup_recovery", {}).get("accounting_verified", True))
            partial = dict(result, status="unresolved" if count else "blocked", reason=str(exc),
                           total_input_count=count, input_count=count,
                           route_input_count=count - result.get("startup_recovery", {}).get("input_count", 0),
                           free_research_transport_calls=calls, accounting_verified=accounting,
                           effect_reconciliation_required=bool(calls), identical_retry_denied=bool(count))
            raise BioenhancerNativePartialResultError(str(exc), partial_result=partial) from exc


def bioenhancer_next_due(result, identity, started_at: float) -> float:
    """Admit only this run's verified free effect or positive no-work cooldown."""
    from scripts.flow_delivery_bioenhancer_bluestacks import _valid_cooldown_metadata

    if (result.get("status") != "completed" or result.get("terminal_home_verified") is not True
            or result.get("cooldown_proof_verified") is not True
            or result.get("effect_reconciliation_required") or result.get("identical_retry_denied")
            or result.get("accounting_verified") is not True or result.get("time_basis") != "utc"):
        raise ValueError("Bioenhancer outcome requires inspection")
    if (result.get("account_id"), result.get("server_id"), result.get("reset_id")) != (
        identity.account_id, identity.server_id, identity.reset_id,
    ):
        raise ValueError("Bioenhancer result identity mismatch")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if completed < _epoch(started_at, "start"):
        raise ValueError("Bioenhancer completion clock predates run")
    count, calls = result.get("total_input_count"), result.get("free_research_transport_calls")
    if type(count) is not int or not 0 <= count <= MAX_INPUTS or type(calls) is not int or calls not in (0, 1) or calls > count:
        raise ValueError("Bioenhancer input/action budget is invalid")
    if calls:
        post = result.get("semantic_postcondition")
        if result.get("no_work") is True or not isinstance(post, dict) or post.get("proven") is not True or post.get("timer_proven") is not True:
            raise ValueError("Bioenhancer single free research effect is not verified")
    elif result.get("no_work") is not True:
        raise ValueError("Bioenhancer zero-action result lacks positive no-work proof")
    cooldown = result.get("cooldown")
    if not _valid_cooldown_metadata(cooldown):
        raise ValueError("Bioenhancer UTC cooldown is invalid")
    observed = datetime.fromisoformat(cooldown["observed_utc"]).timestamp()
    due = datetime.fromisoformat(cooldown["next_due_utc"]).timestamp()
    if not started_at <= observed <= completed or result.get("next_due_utc") != cooldown["next_due_utc"]:
        raise ValueError("Bioenhancer cooldown does not belong to current run clock")
    return max(completed, due)
