"""Canonical Supply Depot execution through the bounded native route.

The native route owns perception and the concrete BlueStacks gestures.  This
adapter owns only the service boundary: fixed identity, borrowed ownership,
input accounting, current terminal-Home proof, and the reset-scoped outcome.
It deliberately does not consult retained flow history as input authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4
from typing import Any, Mapping

import cv2
import numpy as np

from scripts.flow_delivery_supply_depot_bluestacks import (
    FLOW_ID,
    MAX_HOLD_TRANSPORT_CALLS,
    MAX_INPUTS,
)
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)

from .contracts import FlowDescriptor, NormalizedOutcome, NormalizedResult
from .registry import RegisteredDispatchSnapshot
from tasks.scheduler_task_result import SchedulerIdentity


PRODUCT_ID = "supply_depot"
PRODUCT_REVISION = "supply_depot-v2"
PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"


class SupplyNativePartialResultError(RuntimeError):
    """The native route stopped before a complete, retryable outcome existed."""

    def __init__(self, message: str, *, partial_result: Mapping[str, Any]):
        super().__init__(message)
        self.partial_result = dict(partial_result)


class SupplyExecutionHandler:
    """Installable service handler for the exact reset-scoped Supply flow."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = 1

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Supply execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID,
            PRODUCT_ID,
            PRODUCT_REVISION,
            PROFILE_ID,
        ):
            raise ValueError("Supply registration identity mismatch")
        if not callable(execute):
            raise TypeError("Supply executor must be callable")
        self.snapshot, self._execute = snapshot, execute

    def describe(self):
        return FlowDescriptor(
            flow_id=FLOW_ID,
            owner="automation_service",
            family=PRODUCT_ID,
            variant="free_until_exhausted",
            cadence="daily_once_per_reset",
            reset_scoped=True,
            priority=1,
            scheduler_eligible=True,
            accepted_product=PRODUCT_ID,
            product_revision=PRODUCT_REVISION,
            registration_status="REGISTERED",
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
        return self.recover("SUPPLY_DEPOT_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("SUPPLY_DEPOT_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


def _epoch(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Supply {label} must be a finite UTC epoch")
    return float(value)


def _event_rows(runtime) -> tuple[list[dict[str, Any]], bool, str | None]:
    path = getattr(runtime, "events", None)
    if not isinstance(path, (str, Path)):
        return [], False, "native event ledger is unavailable"
    try:
        rows: list[dict[str, Any]] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("type"), str):
                return rows, False, "native event ledger contains a malformed row"
            rows.append(row)
        return rows, True, None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return [], False, f"native event ledger is unreadable: {type(exc).__name__}"


def _consumption(runtime, session=None) -> tuple[int, int, bool, str | None]:
    """Return actual attempted input count, free holds, and exactness."""

    if runtime is None:
        return 0, 0, True, None
    count = getattr(runtime, "input_count", None)
    keys = getattr(runtime, "action_keys", None)
    valid = type(count) is int and 0 <= count <= MAX_INPUTS and isinstance(keys, set)
    reason = None
    if not valid:
        return (count if type(count) is int and count >= 0 else 0), 0, False, "runtime input accounting is malformed"
    if any(type(key) is not str or not key.strip() for key in keys):
        valid = False
        reason = "runtime action keys are not normalized strings"
    if len(keys) != count:
        valid = False
        reason = "runtime action keys do not match input count"
    if session is not None and type(session.input_count) is int and session.input_count != count:
        valid = False
        reason = reason or "session and runtime input counts disagree"
    rows, rows_ok, rows_error = _event_rows(runtime)
    if not rows_ok:
        return count, sum(str(key).startswith("supply-depot-free-hold:") for key in keys), False, rows_error
    dispatch_rows = [row for row in rows if row.get("type") == "dispatch"]
    dispatch_keys = [row.get("action_key") for row in dispatch_rows]
    if len(dispatch_rows) != count or len(set(dispatch_keys)) != len(dispatch_keys) or set(dispatch_keys) != keys:
        valid = False
        reason = reason or "native dispatch ledger does not match runtime input accounting"
    calls = sum(str(key).startswith("supply-depot-free-hold:") for key in keys)
    if calls > MAX_HOLD_TRANSPORT_CALLS:
        valid = False
        reason = reason or "Supply free-hold transport budget exceeded"
    return count, calls, valid, reason


def _terminal_home_proof(
    runtime,
    *,
    started_at: float,
    completed_at: float,
    reset_id: str,
) -> dict[str, Any]:
    """Replay the current settled Home PNG and return only its metadata.

    The route's boolean is not sufficient on its own: this reopens the exact
    current retained PNG, checks native dimensions/bytes, and runs the shared
    clean-Home recognizer on that same frame.  The event timestamp is retained
    evidence, so it must be a real UTC timestamp in this invocation's window
    and on the established game-day.
    """

    rows, valid, error = _event_rows(runtime)
    if not valid:
        raise ValueError(error or "native event ledger is unavailable")
    matches = [row for row in rows if row.get("type") == "capture" and row.get("label") == "supply-depot-home-settled"]
    if len(matches) != 1:
        raise ValueError("Supply terminal Home requires exactly one current settled capture")
    row = matches[0]
    raw_path = row.get("path")
    declared = row.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(declared, str) or len(declared) != 64:
        raise ValueError("Supply terminal Home capture metadata is incomplete")
    path = Path(raw_path)
    session = Path(runtime.session)
    if not path.is_absolute():
        path = session / path
    try:
        resolved = path.resolve()
        resolved.relative_to(session.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("Supply terminal Home capture escaped the native session") from exc
    if path.is_symlink():
        raise ValueError("Supply terminal Home capture must not be a symlink")
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != declared:
        raise ValueError("Supply terminal Home capture changed")
    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or tuple(frame.shape[:2]) != (1280, 800):
        raise ValueError("Supply terminal Home capture is not a native 800x1280 PNG")
    from scripts.startup_normalization import is_clean_home_frame

    if not is_clean_home_frame(frame):
        raise ValueError("Supply terminal Home capture is not a clean Home frame")
    timestamp = row.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("Supply terminal Home capture has no recorded UTC timestamp")
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Supply terminal Home capture timestamp is malformed") from exc
    if observed.tzinfo is None:
        raise ValueError("Supply terminal Home capture timestamp is not timezone-aware")
    captured_at = observed.timestamp()
    if not started_at <= captured_at <= completed_at:
        raise ValueError("Supply terminal Home capture is outside this invocation")
    if not isinstance(reset_id, str) or not reset_id.startswith("game-day-"):
        raise ValueError("Supply terminal Home capture has no established reset")
    if observed.astimezone(timezone.utc).date().isoformat() != reset_id.removeprefix("game-day-"):
        raise ValueError("Supply terminal Home capture is outside the current reset")
    proof: dict[str, Any] = {
        "frame_path": resolved.relative_to(session.resolve()).as_posix(),
        "frame_sha256": actual,
        "captured_at_utc": timestamp,
    }
    if type(row.get("captured_monotonic")) in (int, float) and not isinstance(row.get("captured_monotonic"), bool):
        proof["captured_monotonic"] = float(row["captured_monotonic"])
    return proof


def _next_reset_at_utc(completed: float, reset_id: str) -> float:
    """Project the already-established fixed UTC game-day reset, never regen."""

    prefix = "game-day-"
    if not isinstance(reset_id, str) or not reset_id.startswith(prefix):
        raise ValueError("Supply reset identity is not an established UTC game-day")
    try:
        reset_date = datetime.strptime(reset_id[len(prefix):], "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("Supply reset identity has no canonical UTC date") from exc
    current_date = datetime.fromtimestamp(completed, timezone.utc).date()
    if reset_date != current_date:
        raise ValueError("Supply reset identity is not current at completion")
    next_date = reset_date + timedelta(days=1)
    return datetime(next_date.year, next_date.month, next_date.day, tzinfo=timezone.utc).timestamp()


class SupplyRunner:
    """Device-free construction; execute only under the caller's borrowed owner."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path, utc_clock=time.time):
        self.adb, self.serial = adb, serial
        self.output_directory = Path(output_directory)
        self.utc_clock = utc_clock

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts import supply_depot_free_canary as route
        from scripts.startup_normalization import is_clean_home_frame
        from scripts.startup_recovery import recover_contextual_startup_overlay

        del previous_reset_id
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Supply task identity mismatch")
        runtime = None
        session = None
        native_result: dict[str, Any] = {}
        startup: dict[str, Any] = {}
        started = None
        try:
            checkpoint()
            started = _epoch(self.utc_clock(), "start")
            invocation = (
                f"supply-depot-{datetime.fromtimestamp(started, timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
                f"-{uuid4().hex[:8]}"
            )
            with DevelopmentSession(
                owner="automation-service:supply-depot",
                invocation_id=invocation,
                session_directory=self.output_directory / invocation,
                max_inputs=MAX_INPUTS,
                runtime_input_lock=runtime_input_lock,
                checkpoint=checkpoint,
            ) as session:
                runtime = LocalBlueStacksRuntime.connect(
                    adb=self.adb,
                    serial=self.serial,
                    output_directory=session.session_directory,
                    workflow="supply-depot-native",
                    execute=True,
                )
                owner_fence = (runtime_input_lock.owner, runtime_input_lock.invocation_id)
                def current_checkpoint():
                    session.runtime_input_lock.assert_held(*owner_fence)
                    checkpoint()
                    session.runtime_input_lock.assert_held(*owner_fence)
                runtime.checkpoint, runtime.max_inputs = current_checkpoint, MAX_INPUTS
                initial = session.observe(runtime.capture, label="supply-depot-canonical-initial")
                def frame_reference(frame):
                    return {"frame_path": frame.path.relative_to(runtime.session).as_posix(),
                            "frame_sha256": frame.sha256,
                            "captured_monotonic": frame.captured_monotonic}

                def recognized_source(frame):
                    return bool(is_clean_home_frame(frame.frame)
                        or route._recognize(runtime, frame, "supply-depot-startup").recognized
                        or route._arena_exit_target(frame.frame) is not None
                        or route.recognize_supply_depot_radial(frame.frame,
                            source_frame=route._identity(runtime, frame, "supply-depot-startup"),
                            source_png=frame.png))

                startup.update(source_frame=frame_reference(initial), input_count=0,
                    resume_ready=False, clean_home_verified=False,
                    accounting_verified=False, reason="startup_recovery_interrupted",
                    native_events_path=str(runtime.events))
                try:
                    recovered = recover_contextual_startup_overlay(runtime, initial,
                        source_context=FLOW_ID, recognize_successor=recognized_source,
                        action_key=f"supply-depot-startup-overlay:{initial.sha256}")
                    startup.update(reason=recovered.reason, dismissed=recovered.dismissed,
                        popup_absent=recovered.popup_absent, resume_ready=recovered.resume_ready,
                        reported_input_count=recovered.input_count,
                        settled_frame=frame_reference(recovered.settled_frame) if recovered.settled_frame else None)
                finally:
                    startup["input_count"] = runtime.input_count
                    session.adopt_retained_transport_count(runtime.input_count, source=str(runtime.events))
                    _count, startup_holds, startup_accounting, startup_error = _consumption(runtime, session)
                    startup.update(accounting_verified=bool(startup_accounting and startup_holds == 0),
                        accounting_error=startup_error)
                if type(runtime.input_count) is not int or not 0 <= runtime.input_count <= 1:
                    raise ValueError("Supply startup input accounting is invalid")
                if not startup["accounting_verified"]:
                    raise ValueError("Supply startup native ledger is not exact zero-hold navigation")
                if type(recovered.input_count) is not int or recovered.input_count != runtime.input_count:
                    raise ValueError("Supply startup result differs from its native input ledger")
                if not recovered.resume_ready:
                    raise ValueError(f"Supply startup blocked: {recovered.reason}")
                if recovered.settled_frame is None:
                    raise ValueError("Supply startup has no current route source")
                initial = recovered.settled_frame
                if runtime.input_count:
                    initial = session.observe(runtime.capture, label="supply-depot-canonical-after-startup")
                    startup["route_source_frame"] = frame_reference(initial)
                    if not is_clean_home_frame(initial.frame):
                        raise ValueError("Supply startup did not reach fresh clean Home")
                    startup["clean_home_verified"] = True
                else:
                    startup["clean_home_verified"] = is_clean_home_frame(initial.frame)
                    startup["route_source_frame"] = frame_reference(initial)
                session.set_initial_observation(DevelopmentInitialObservation(
                    {
                        "frame_sha256": initial.sha256,
                        "device_state": "device",
                        "foreground_package": "com.global.ztmslg",
                        "native_width": 800,
                        "native_height": 1280,
                    },
                    initial.sha256,
                    frame_path=initial.path.relative_to(session.session_directory).as_posix(),
                    invocation_id=invocation,
                ))
                native_result = route.run(
                    session=session,
                    runtime=runtime,
                    session_directory=runtime.session,
                    settle_seconds=1.5,
                )
                if not isinstance(native_result, dict):
                    raise ValueError("Supply native route returned a non-object result")
                count, calls, accounting, accounting_error = _consumption(runtime, session)
                if not accounting:
                    raise ValueError(accounting_error or "Supply native input accounting mismatch")
                if native_result.get("status") != "completed":
                    raise ValueError(str(native_result.get("reason") or "Supply native route is incomplete"))
                before = native_result.get("free_attempts_before")
                after = native_result.get("free_attempts_after")
                if type(before) is not int or not 0 <= before <= MAX_INPUTS:
                    raise ValueError("Supply native before-count is not exact")
                if type(after) is not int or not 0 <= after <= MAX_INPUTS:
                    raise ValueError("Supply native after-count is not exact")
                reported_calls = native_result.get("hold_transport_calls")
                if type(reported_calls) is not int or reported_calls != calls or reported_calls not in (0, 1):
                    raise ValueError("Supply native hold accounting is not exact")
                no_work = before == after == 0 and calls == 0
                consumed = before > 0 and after == 0 and calls == 1
                if not (no_work or consumed):
                    raise ValueError("Supply free-only before/after effect is not verified")
                if native_result.get("terminal_home_verified") is not True:
                    raise ValueError(str(native_result.get("reason") or "Supply terminal Home is not verified"))
                completed = _epoch(self.utc_clock(), "completion")
                if completed < started:
                    raise ValueError("Supply completion clock predates run")
                home = _terminal_home_proof(
                    runtime,
                    started_at=started,
                    completed_at=completed,
                    reset_id=identity.reset_id,
                )
                next_reset = _next_reset_at_utc(completed, identity.reset_id)
                result = dict(
                    native_result,
                    status="completed",
                    no_work=no_work,
                    flow_id=FLOW_ID,
                    product_id=PRODUCT_ID,
                    product_revision=PRODUCT_REVISION,
                    task_id=PRODUCT_ID,
                    account_id=identity.account_id,
                    server_id=identity.server_id,
                    reset_id=identity.reset_id,
                    time_basis="utc",
                    completed_at_utc=completed,
                    next_reset_at_utc=next_reset,
                    total_input_count=count,
                    input_count=count,
                    hold_transport_calls=calls,
                    accounting_verified=True,
                    terminal_home_verified=True,
                    terminal_home_frame=home,
                    startup_recovery=startup,
                    route_input_count=count - startup.get("input_count", 0),
                    effect_reconciliation_required=False,
                    identical_retry_denied=False,
                    session_directory=str(runtime.session),
                )
                supply_next_due(result, identity, started)
                (session.session_directory / "supply-result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                )
                checkpoint()
                return result
        except Exception as exc:
            count, calls, accounting, accounting_error = _consumption(runtime, session)
            partial = dict(native_result) if isinstance(native_result, Mapping) else {}
            partial.update(
                status="unresolved" if count or calls else "blocked",
                reason=str(exc),
                flow_id=FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                total_input_count=count,
                input_count=count,
                hold_transport_calls=calls,
                accounting_verified=accounting,
                accounting_error=accounting_error,
                effect_reconciliation_required=bool(calls),
                identical_retry_denied=bool(count or calls),
                terminal_home_verified=False,
                startup_recovery=startup,
                route_input_count=count - startup.get("input_count", 0),
            )
            raise SupplyNativePartialResultError(str(exc), partial_result=partial) from exc


def supply_next_due(result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float) -> float:
    """Admit only a current reset's exact free-only outcome and actual UTC reset."""

    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Supply outcome requires its exact task identity")
    if (
        result.get("status") != "completed"
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True
        or result.get("effect_reconciliation_required")
        or result.get("identical_retry_denied")
        or result.get("time_basis") != "utc"
        or (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
    ):
        raise ValueError("Supply outcome identity, Home, or effect proof is not verified")
    started = _epoch(started_at, "start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    next_reset = _epoch(result.get("next_reset_at_utc"), "next reset")
    if completed < started or next_reset <= completed or next_reset != _next_reset_at_utc(completed, identity.reset_id):
        raise ValueError("Supply UTC completion/reset boundary is not exact")
    count, calls = result.get("total_input_count"), result.get("hold_transport_calls")
    before, after = result.get("free_attempts_before"), result.get("free_attempts_after")
    if (
        type(count) is not int or not 0 <= count <= MAX_INPUTS
        or type(calls) is not int or calls not in (0, 1)
        or type(before) is not int or not 0 <= before <= MAX_INPUTS
        or type(after) is not int or not 0 <= after <= MAX_INPUTS
        or (result.get("no_work") is True and (before != 0 or after != 0 or calls != 0))
        or (result.get("no_work") is not True and not (before > 0 and after == 0 and calls == 1))
        or (calls and count < 1)
    ):
        raise ValueError("Supply free-only input/effect accounting is invalid")
    home = result.get("terminal_home_frame")
    if (
        not isinstance(home, Mapping)
        or not isinstance(home.get("frame_path"), str)
        or not home.get("frame_path")
        or Path(home["frame_path"]).is_absolute()
        or ".." in Path(home["frame_path"]).parts
        or not isinstance(home.get("frame_sha256"), str)
        or len(home["frame_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in home["frame_sha256"])
    ):
        raise ValueError("Supply terminal Home current-frame proof is missing")
    return next_reset


__all__ = [
    "FLOW_ID",
    "MAX_INPUTS",
    "MAX_HOLD_TRANSPORT_CALLS",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "PROFILE_ID",
    "SupplyExecutionHandler",
    "SupplyNativePartialResultError",
    "SupplyRunner",
    "supply_next_due",
]
