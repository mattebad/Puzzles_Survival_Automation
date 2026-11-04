"""Canonical Enhancement family adapter; native reservations remain wrapper-owned."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from scripts import flow_delivery_enhancement_bluestacks as native
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation, DevelopmentSession, RuntimeInputLock,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import NormalizedOutcome, NormalizedResult
from .registry import (
    ENHANCEMENT_MAX_INPUTS,
    ENHANCEMENT_PRODUCT_ID,
    ENHANCEMENT_PRODUCT_REVISION,
    RegisteredDispatchSnapshot,
    canonical_entry,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL


FLOW_ID = native.FLOW_ID
PRODUCT_ID = ENHANCEMENT_PRODUCT_ID
PRODUCT_REVISION = ENHANCEMENT_PRODUCT_REVISION
PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
MAX_INPUTS = ENHANCEMENT_MAX_INPUTS
MAX_ACTIONS = 3
_CATEGORIES = ("gear", "chip", "module")


class EnhancementNativePartialResultError(RuntimeError):
    def __init__(self, message: str, *, partial_result: Mapping[str, Any]):
        super().__init__(message)
        self.partial_result = dict(partial_result)


class EnhancementExecutionHandler:
    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Enhancement execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
            FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID,
        ):
            raise ValueError("Enhancement registration identity mismatch")
        if not callable(execute):
            raise TypeError("Enhancement executor must be callable")
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
        return self.recover("ENHANCEMENT_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("ENHANCEMENT_UNKNOWN_RESULT")

    def recover(self, reason_code):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


def _epoch(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Enhancement {label} must be a finite UTC epoch")
    return float(value)


def _reset(now: float, reset_id: str) -> tuple[str, float]:
    day = datetime.fromtimestamp(now, timezone.utc).date()
    if reset_id != f"game-day-{day.isoformat()}":
        raise ValueError("Enhancement reset is not the current canonical UTC day")
    tomorrow = day + timedelta(days=1)
    return (
        f"local-{day.isoformat()}-enhancement-family",
        datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc).timestamp(),
    )


def _runtime_directory(outer: Path, summary: Mapping[str, Any] | None = None) -> Path | None:
    root = outer / "runtime"
    if root.is_symlink():
        raise ValueError("Enhancement runtime directory is a symlink")
    if summary and summary.get("session_directory"):
        path = Path(str(summary["session_directory"]))
        path.resolve().relative_to(root.resolve())
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Enhancement native session is not a current regular directory")
        return path
    if not root.exists():
        return None
    directories = list(root.iterdir())
    if len(directories) != 1 or directories[0].is_symlink() or not directories[0].is_dir():
        raise ValueError("Enhancement native runtime session is ambiguous")
    return directories[0]


def _consumption(session, runtime_directory: Path | None):
    count = getattr(session, "input_count", 0) if session is not None else 0
    exact = type(count) is int and 0 <= count <= MAX_INPUTS
    count = count if type(count) is int and count >= 0 else 0
    if runtime_directory is None:
        return count, 0, exact and count == 0, []
    try:
        rows = native._read_event_rows(runtime_directory / "events.jsonl")
    except Exception:
        return count, 0, False, []
    dispatches = native._dispatch_rows(rows)
    uses = native._resource_dispatch_rows(rows)
    keys = [row.get("action_key") for row in dispatches]
    exact = bool(exact and count == len(dispatches) and len(uses) <= MAX_ACTIONS
                 and all(type(key) is str and key for key in keys)
                 and len(set(keys)) == len(keys))
    return max(count, len(dispatches)), len(uses), exact, rows


def _terminal_home_frame(runtime_directory: Path, route, rows):
    digest = route.get("terminal_frame_sha256")
    matches = [row for row in rows if row.get("type") == "capture" and row.get("sha256") == digest]
    if not matches:
        raise ValueError("Enhancement current terminal Home capture is missing")
    row = matches[-1]
    path = Path(str(row.get("path") or ""))
    if not path.is_absolute():
        path = runtime_directory / path
    relative = path.resolve().relative_to(runtime_directory.resolve())
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Enhancement terminal Home capture changed")
    return {"frame_path": relative.as_posix(), "frame_sha256": digest}


def _source_inventory(value, native_reset: str, categories) -> dict[str, dict[str, Any]]:
    """Check the shape of metadata returned by native independent replay."""
    expected = [variant for variant in _CATEGORIES if variant in categories]
    if (
        any(variant not in _CATEGORIES for variant in categories)
        or not isinstance(value, Mapping) or set(value) != set(expected)
    ):
        raise ValueError("Enhancement category source inventory is incomplete or contains unknown categories")
    sources: dict[str, dict[str, Any]] = {}
    keys: set[str] = set()
    for variant in expected:
        source = value[variant]
        if not isinstance(source, Mapping):
            raise ValueError("Enhancement category source metadata is malformed")
        key, digest, session = (source.get(name) for name in (
            "resource_affecting_action_key", "delivery_sha256", "runtime_session",
        ))
        if (
            source.get("status") != "verified" or source.get("variant") != variant
            or source.get("reset_identity") != native_reset
            or not isinstance(key, str) or not key.startswith(f"enhancement:{variant}:") or key in keys
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(session, str) or not session or not Path(session).is_absolute()
        ):
            raise ValueError("Enhancement category source identity is malformed or mismatched")
        keys.add(key)
        sources[variant] = dict(source)
    return sources


def _family_inventory(verification, native_reset: str):
    if not isinstance(verification, Mapping) or verification.get("status") != "verified":
        raise ValueError("Enhancement independent family verification is missing")
    current, retained = (verification.get(name) for name in ("current_categories", "retained_categories"))
    if (
        not isinstance(current, list) or not isinstance(retained, list)
        or current != [variant for variant in _CATEGORIES if variant in current]
        or retained != [variant for variant in _CATEGORIES if variant in retained]
        or set(current) & set(retained) or set(current) | set(retained) != set(_CATEGORIES)
        or verification.get("categories_verified") != list(_CATEGORIES)
        or type(verification.get("retained_category_count")) is not int
        or verification["retained_category_count"] != len(retained)
        or type(verification.get("current_resource_affecting_dispatch_count")) is not int
        or verification["current_resource_affecting_dispatch_count"] != len(current)
    ):
        raise ValueError("Enhancement current and retained category accounting is not exact")
    sources = _source_inventory(verification.get("category_source_proofs"), native_reset, _CATEGORIES)
    for variant, source in sources.items():
        if source.get("origin", "current" if variant in current else "retained") != (
            "current" if variant in current else "retained"
        ):
            raise ValueError("Enhancement category source origin is inconsistent")
    return sources, current, retained


class EnhancementRunner:
    """Construction is device-free; the full existing wrapper owns family effects."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path, utc_clock=time.time):
        self.adb, self.serial = adb, serial
        self.output_directory = Path(output_directory)
        self.utc_clock = utc_clock

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock,
                 operator_request_id: str | None = None):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime

        del previous_reset_id
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
            raise ValueError("Enhancement task identity mismatch")
        if (not isinstance(runtime_input_lock, RuntimeInputLock)
                or runtime_input_lock.owner != "automation-service" or not callable(checkpoint)):
            raise ValueError("Enhancement requires the canonical held owner and checkpoint")
        runtime_input_lock.assert_held("automation-service", runtime_input_lock.invocation_id)
        checkpoint()
        started = _epoch(self.utc_clock(), "start")
        native_reset, _ = _reset(started, identity.reset_id)
        pnsctl = native._pnsctl()
        if (str(self.adb), self.serial) != (str(BLUESTACKS_ADB), BLUESTACKS_SERIAL):
            raise ValueError("Enhancement runtime configuration differs from its existing wrapper")
        invocation = f"enhancement-{datetime.fromtimestamp(started, timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
        session = None
        summary = {}
        runtime_directory = None
        try:
            with DevelopmentSession(
                owner="automation-service:enhancement", invocation_id=invocation,
                session_directory=self.output_directory / invocation, max_inputs=MAX_INPUTS,
                runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
            ) as session:
                checkpoint()
                _, selected_reset, completed_categories = native._select_family_state(
                    pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID, native_reset, checkpoint=checkpoint,
                    operator_request_id=operator_request_id,
                )
                if selected_reset != native_reset:
                    raise ValueError("Enhancement retained family reset selection changed")
                retained = _source_inventory(
                    native._verify_retained_categories(completed_categories, native_reset, checkpoint=checkpoint),
                    native_reset, completed_categories,
                )
                checkpoint()
                initial_runtime = LocalBlueStacksRuntime.connect(
                    adb=self.adb, serial=self.serial,
                    output_directory=session.session_directory / "initial",
                    workflow="enhancement-canonical-initial", execute=True,
                )
                initial_runtime.checkpoint = checkpoint
                initial_runtime.max_inputs = MAX_INPUTS
                initial = session.observe(initial_runtime.capture, label="enhancement-canonical-initial")
                (session.session_directory / "source.png").write_bytes(initial.png)
                bound = session.set_initial_observation(DevelopmentInitialObservation(
                    {"frame_sha256": initial.sha256, "device_state": "device",
                     "foreground_package": "com.global.ztmslg", "native_width": 800, "native_height": 1280},
                    initial.sha256, frame_path="source.png", invocation_id=invocation,
                ))
                if len(retained) == MAX_ACTIONS:
                    from scripts.startup_normalization import is_clean_home_frame

                    runtime_directory = initial_runtime.session
                    count, calls, accounting, _ = _consumption(session, runtime_directory)
                    if count or calls or not accounting or not is_clean_home_frame(initial.frame):
                        raise ValueError("Enhancement retained completion requires fresh zero-input canonical Home")
                    completed = _epoch(self.utc_clock(), "completion")
                    completed_reset, next_reset = _reset(completed, identity.reset_id)
                    if completed < started or completed_reset != native_reset:
                        raise ValueError("Enhancement retained completion crossed its UTC reset")
                    home = {"frame_path": "source.png", "frame_sha256": initial.sha256,
                            "captured_monotonic": initial.captured_monotonic}
                    verification = {
                        "status": "verified", "flow_id": FLOW_ID, "variant": "family",
                        "categories_verified": list(_CATEGORIES), "retained_category_count": MAX_ACTIONS,
                        "current_resource_affecting_dispatch_count": 0,
                        "current_categories": [], "retained_categories": list(_CATEGORIES),
                        "category_source_proofs": retained,
                        "proof_topology": "retained_categories_plus_current_home",
                    }
                    result = {
                        "status": "already_completed", "no_work": True,
                        "flow_id": FLOW_ID, "product_id": PRODUCT_ID,
                        "product_revision": PRODUCT_REVISION, "task_id": PRODUCT_ID,
                        "account_id": identity.account_id, "server_id": identity.server_id,
                        "reset_id": identity.reset_id, "native_reset_identity": native_reset,
                        "operator_request_id": operator_request_id,
                        "time_basis": "utc", "completed_at_utc": completed,
                        "next_reset_at_utc": next_reset, "total_input_count": 0, "input_count": 0,
                        "enhancement_dispatch_count": 0, "resource_affecting_dispatch_count": 0,
                        "categories_completed": MAX_ACTIONS, "accounting_verified": True,
                        "terminal_home_verified": True, "terminal_home_frame": home,
                        "current_home_proof": dict(home), "retained_category_proofs": retained,
                        "family_verification": verification,
                        "proof_topology": "retained_categories_plus_current_home",
                        "effect_reconciliation_required": False, "identical_retry_denied": False,
                        "session_directory": str(session.session_directory),
                    }
                    checkpoint()
                    enhancement_next_due(result, identity, started)
                    checkpoint()
                    return result
                lease = {
                    "development_session": session, "owner": runtime_input_lock.owner,
                    "runtime_input_lock": runtime_input_lock, "checkpoint": checkpoint,
                    "initial_observation": bound, "initial_frame_sha256": initial.sha256,
                    "enhancement_reset_identity": native_reset, "enhancement_variant": "gear",
                    "operator_request_id": operator_request_id,
                    "max_inputs": MAX_INPUTS,
                }
                checkpoint()
                summary = json.loads(native.run_enhancement_family({}, lease, live=True))
                if not isinstance(summary, dict):
                    raise ValueError("Enhancement native result must be an object")
                runtime_directory = _runtime_directory(session.session_directory, summary)
                count, calls, accounting, rows = _consumption(session, runtime_directory)
                if runtime_directory is None or not accounting:
                    raise ValueError("Enhancement native input accounting is not exact")
                delivery_path = runtime_directory / "flow-delivery-result.json"
                if delivery_path.is_symlink():
                    raise ValueError("Enhancement delivery result must not be a symlink")
                delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
                route = delivery.get("enhancement_result")
                if not isinstance(route, dict) or route.get("reset_identity") != native_reset:
                    raise ValueError("Enhancement native family reset mismatch")
                if (
                    summary.get("status") != "completed" or delivery.get("status") != "completed"
                    or route.get("terminal_recognized") is not True
                ):
                    reason = str(route.get("reason") or delivery.get("reason") or summary.get("reason")
                                 or "Enhancement native family did not complete")
                    summary.update(native_status=route.get("status"), native_reason=reason)
                    raise ValueError(reason)
                checkpoint()
                verification = native.verify_enhancement_family(
                    {"result": delivery, "session_directory": str(runtime_directory),
                     "frames": delivery.get("frames")}, {}, lease,
                )
                checkpoint()
                sources, current_categories, retained_categories = _family_inventory(verification, native_reset)
                if (
                    current_categories != [variant for variant in _CATEGORIES if variant not in retained]
                    or retained_categories != list(retained) or calls != len(current_categories)
                    or any(any(sources[variant].get(name) != retained[variant].get(name) for name in (
                        "runtime_session", "resource_affecting_action_key", "delivery_sha256",
                    )) for variant in retained)
                ):
                    raise ValueError("Enhancement family is incomplete or its current Home/effect proof is unverified")
                completed = _epoch(self.utc_clock(), "completion")
                completed_reset, next_reset = _reset(completed, identity.reset_id)
                if completed < started or completed_reset != native_reset:
                    raise ValueError("Enhancement completion crossed its UTC reset")
                result = dict(
                    delivery, no_work=False, flow_id=FLOW_ID, product_id=PRODUCT_ID,
                    product_revision=PRODUCT_REVISION, task_id=PRODUCT_ID,
                    account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id,
                    operator_request_id=operator_request_id,
                    native_reset_identity=native_reset, time_basis="utc", completed_at_utc=completed,
                    next_reset_at_utc=next_reset, total_input_count=count, input_count=count,
                    enhancement_dispatch_count=calls, resource_affecting_dispatch_count=calls,
                    categories_completed=MAX_ACTIONS, accounting_verified=True,
                    terminal_home_verified=True, terminal_home_frame=_terminal_home_frame(runtime_directory, route, rows),
                    family_verification=verification, effect_reconciliation_required=False,
                    identical_retry_denied=False, session_directory=str(runtime_directory),
                )
                checkpoint()
                enhancement_next_due(result, identity, started)
                checkpoint()
                return result
        except Exception as exc:
            accounting_error = None
            try:
                if runtime_directory is None and session is not None:
                    runtime_directory = _runtime_directory(session.session_directory)
                count, calls, accounting, _ = _consumption(session, runtime_directory)
            except Exception as accounting_exc:
                count = getattr(session, "input_count", 0)
                count = count if type(count) is int and count >= 0 else 0
                calls, accounting = 0, False
                accounting_error = str(accounting_exc)
            partial = dict(summary) if isinstance(summary, dict) else {}
            partial.update(
                status="unresolved" if count else "blocked", reason=str(exc),
                flow_id=FLOW_ID, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID, total_input_count=count, input_count=count,
                enhancement_dispatch_count=calls, resource_affecting_dispatch_count=calls,
                accounting_verified=accounting, accounting_error=accounting_error,
                effect_reconciliation_required=bool(calls or (count and not accounting)),
                identical_retry_denied=bool(count or calls or not accounting),
                terminal_home_verified=False,
            )
            raise EnhancementNativePartialResultError(str(exc), partial_result=partial) from exc


def enhancement_next_due(result, identity, started_at: float) -> float:
    """Complete the family while charging only this run's verified inputs."""
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Enhancement outcome requires its exact task identity")
    no_work = result.get("no_work") is True
    if (
        result.get("status") != ("already_completed" if no_work else "completed")
        or result.get("terminal_home_verified") is not True
        or result.get("accounting_verified") is not True or result.get("effect_reconciliation_required")
        or result.get("identical_retry_denied") or result.get("time_basis") != "utc"
        or (result.get("flow_id"), result.get("product_id"), result.get("product_revision"), result.get("task_id"))
        != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PRODUCT_ID)
        or (result.get("account_id"), result.get("server_id"), result.get("reset_id"))
        != (identity.account_id, identity.server_id, identity.reset_id)
    ):
        raise ValueError("Enhancement outcome identity, Home, or effect proof is not verified")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    native_reset, next_reset = _reset(completed, identity.reset_id)
    count, calls = result.get("total_input_count"), result.get("enhancement_dispatch_count")
    verification = result.get("family_verification")
    sources, current_categories, retained_categories = _family_inventory(verification, native_reset)
    home = result.get("terminal_home_frame")
    topology = (
        "retained_categories_plus_current_home" if no_work
        else "composite" if retained_categories else "continuous"
    )
    runtime = result.get("session_directory")
    if (
        completed < _epoch(started_at, "start") or result.get("next_reset_at_utc") != next_reset
        or result.get("native_reset_identity") != native_reset
        or type(count) is not int or not (count == 0 if no_work else len(current_categories) <= count <= MAX_INPUTS)
        or type(result.get("input_count")) is not int or result.get("input_count") != count
        or type(calls) is not int or calls != len(current_categories)
        or type(result.get("resource_affecting_dispatch_count")) is not int
        or result.get("resource_affecting_dispatch_count") != calls
        or (not no_work and not current_categories)
        or (no_work and (current_categories or retained_categories != list(_CATEGORIES)))
        or result.get("categories_completed") != MAX_ACTIONS
        or result.get("proof_topology") != topology or verification.get("proof_topology") != topology
        or not isinstance(runtime, str) or not runtime or not Path(runtime).is_absolute()
        or not isinstance(home, Mapping) or not isinstance(home.get("frame_path"), str)
        or not home["frame_path"] or Path(home["frame_path"]).is_absolute() or ".." in Path(home["frame_path"]).parts
        or not isinstance(home.get("frame_sha256"), str) or len(home["frame_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in home["frame_sha256"])
    ):
        raise ValueError("Enhancement exact family accounting or UTC reset proof is missing")
    for variant, source in sources.items():
        if (Path(source["runtime_session"]).resolve() == Path(runtime).resolve()) != (variant in current_categories):
            raise ValueError("Enhancement current and retained source sessions are not separated")
    if no_work:
        if (
            result.get("current_home_proof") != home
            or result.get("retained_category_proofs") != sources
        ):
            raise ValueError("Enhancement retained family/current Home proof is incomplete")
    return next_reset
