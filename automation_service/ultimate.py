"""Canonical Ultimate daily adapter over the existing native route and reset guard."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Mapping

import cv2
import numpy as np

from tasks.scheduler_task_result import SchedulerIdentity
from tasks.ultimate_challenge_daily import (
    FLOW_ID, ULTIMATE_CHALLENGE_OBJECTIVE, COMPLETION_UNKNOWN,
    TERMINAL_ALREADY_COMPLETED, TERMINAL_COMPLETE_FOR_RESET, TERMINAL_NAVIGATION_ONLY_COMPLETE,
    evaluate_already_completed, evaluate_navigation_only, load_reset_window_state,
    record_pending_home, record_verified_home_success, save_reset_window_state,
)
from .contracts import FlowDescriptor, FlowSpec, NormalizedOutcome, NormalizedResult
from .registry import RegisteredDispatchSnapshot
from .recruitment import recruitment_reset


PRODUCT_ID = ULTIMATE_CHALLENGE_OBJECTIVE
PRODUCT_REVISION = "ultimate_challenge_daily-v1"
PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
MAX_INPUTS = 16
RESET_STATE_PATH = Path(__file__).resolve().parents[1] / ".local-captures/ultimate-challenge-daily-reset-window.json"
_DAILY_TARGETS = frozenset({"tap_challenge", "tap_lineup_challenge", "tap_upper_right_exit", "tap_flee"})


class UltimateExecutionHandler:
    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = 1

    def __init__(self, snapshot, execute, *, flow_spec: FlowSpec | None = None):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Ultimate execution requires a typed registration")
        if (snapshot.flow_id, snapshot.product_id, snapshot.product_revision, snapshot.profile) != (
                FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Ultimate registration identity mismatch")
        if not callable(execute):
            raise TypeError("Ultimate executor must be callable")
        if flow_spec is not None:
            if not isinstance(flow_spec, FlowSpec) or flow_spec.flow_id != FLOW_ID:
                raise ValueError("Ultimate observation-only opt-in requires its matching flow spec")
            self.flow_spec = flow_spec
        self.snapshot, self._execute = snapshot, execute

    def describe(self):
        return FlowDescriptor(flow_id=FLOW_ID, owner="automation_service", family=PRODUCT_ID,
            variant="one_daily_flee", cadence="daily_once_per_reset", reset_scoped=True,
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
        return self.recover("ULTIMATE_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("ULTIMATE_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": FLOW_ID, "selection_only": False, "transport_count": 0}


class UltimateRunnerError(RuntimeError):
    def __init__(self, reason, partial_result):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def _epoch(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Ultimate {name} must be a finite UTC epoch")
    return float(value)


def _consumption(runtime):
    if runtime is None:
        return 0, 0, 0, True
    inputs, actions, keys = runtime.input_count, runtime.frame_actions, runtime.action_keys
    counts = {target: sum(item[1] == target for item in actions) for target in _DAILY_TARGETS}
    valid = (type(inputs) is int and 0 <= inputs <= MAX_INPUTS
             and len(actions) == len(keys) == inputs and all(count <= 1 for count in counts.values()))
    return inputs, int(any(counts.values())) if valid else None, counts["tap_flee"], valid


def _current_flee_proof(runtime, native):
    """Corroborate only this attempt's Flee, including its actual native PNGs."""
    if runtime is None or not runtime.events.is_file():
        return None
    rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    dispatches = [row for row in rows if row.get("type") == "dispatch"
                  and row.get("target_identity") == "tap_flee" and row.get("execute") is True]
    if not dispatches:
        return None
    if len(dispatches) != 1:
        raise ValueError("Ultimate current attempt has ambiguous Flee dispatches")
    dispatch = dispatches[0]
    confirmed = [row for row in rows if row.get("type") == "reconcile"
                 and row.get("action_key") == dispatch.get("action_key") and row.get("status") == "confirmed"]
    if not confirmed:
        return None
    if len(confirmed) != 1:
        raise ValueError("Ultimate Flee has ambiguous confirmation")

    def frame(digest):
        for row in rows:
            if row.get("type") != "capture" or row.get("sha256") != digest:
                continue
            path = Path(row["path"])
            path.resolve().relative_to(runtime.session.resolve())
            if path.is_symlink():
                raise ValueError("Ultimate current capture is a link")
            raw = path.read_bytes()
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if (hashlib.sha256(raw).hexdigest() == digest and image is not None
                    and image.shape == (1280, 800, 3)):
                return image
        raise ValueError("Ultimate Flee current native capture integrity failed")

    before, after = dispatch["source_sha256"], confirmed[0]["post_sha256"]
    warning = native._bind_flee_warning_button(frame(before))
    successor = frame(after)
    if (warning is None or list(warning) != dispatch.get("target_roi")
            or (native._recognize_ultimate_main(successor) is None
                and native._bind_ultimate_defeat_continue(successor) is None)):
        raise ValueError("Ultimate current Flee source or successor is not recognized")
    return {"action": "tap_flee", "action_key": dispatch["action_key"], "target_roi": warning,
            "before_sha256": before, "post_sha256": after}


def _startup_frame(session: Path, value: Mapping):
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png

    reference = value.get("frame_path")
    if (type(reference) is not str or not reference or Path(reference).is_absolute()
            or ".." in Path(reference).parts):
        raise ValueError("Ultimate startup capture path is invalid")
    path = session / reference
    path.resolve().relative_to(session.resolve())
    if path.is_symlink():
        raise ValueError("Ultimate startup capture is a link")
    captured = captured_native_frame_from_png(path.read_bytes(),
        captured_monotonic=_epoch(value.get("captured_monotonic"), "startup capture"), path=path)
    if captured.sha256 != value.get("frame_sha256"):
        raise ValueError("Ultimate startup capture changed")
    return captured


def _startup_events(session: Path):
    path = session / "events.jsonl"
    if path.is_symlink():
        raise ValueError("Ultimate startup ledger is a link")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Ultimate startup ledger is malformed")
    return rows


def _startup_navigation_proof(session, source, settled, home, action_key, helper, steps):
    """Replay every known dismissal before accepting this route's fresh Home."""
    from scripts import startup_recovery as startup
    from scripts import bluestacks_ultimate_challenge as native

    session = Path(session).resolve()
    if (not isinstance(helper, Mapping) or helper.get("resume_ready") is not True
            or helper.get("dismissed") is not True or helper.get("popup_absent") is not True
            or type(helper.get("input_count")) is not int or helper["input_count"] not in (1, 2)
            or not isinstance(steps, list) or len(steps) != helper["input_count"]
            or type(helper.get("reason")) is not str or not helper["reason"]):
        raise ValueError("Ultimate startup helper did not verify its known dismissals")
    rows = _startup_events(session)

    def path_for(row):
        path = Path(row["path"])
        if not path.is_absolute() and not path.resolve().is_relative_to(session):
            path = session / path
        path.resolve().relative_to(session)
        return path

    def capture_record(captured):
        if not startup._contextual_startup_frame_valid(captured):
            raise ValueError("Ultimate startup native capture is invalid")
        path = captured.path.resolve()
        relative = path.relative_to(session).as_posix()
        if captured.path.is_symlink() or path.read_bytes() != captured.png:
            raise ValueError("Ultimate startup native PNG changed")
        matches = [(index, row) for index, row in enumerate(rows)
                   if row.get("type") == "capture" and path_for(row).resolve() == path
                   and row.get("sha256") == captured.sha256
                   and row.get("captured_monotonic") == captured.captured_monotonic]
        if len(matches) != 1:
            raise ValueError("Ultimate startup capture is not bound to its current ledger")
        return {"frame_path": relative, "frame_sha256": captured.sha256,
                "captured_monotonic": captured.captured_monotonic}, matches[0][0]

    def step_frame(step, name):
        return _startup_frame(session, {"frame_path": step.get(name + "_frame"),
            "frame_sha256": step.get(name + "_sha256"),
            "captured_monotonic": step.get(name + "_captured_monotonic")})

    p, pi = capture_record(source)
    r, ri = capture_record(settled)
    h, hi = capture_record(home)
    seen, dispatches, verified_steps = set(), [], []
    previous = source
    first_immediate = None
    previous_reconcile_index = None
    for ordinal, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise ValueError("Ultimate startup step is missing")
        proposal, immediate, post = (step_frame(step, name) for name in ("source", "immediate_before", "settled"))
        proposal_ref, proposal_index = capture_record(proposal)
        immediate_ref, immediate_index = capture_record(immediate)
        post_ref, post_index = capture_record(post)
        identity = startup.contextual_startup_identity(proposal)
        if (identity is None or identity in seen or startup.contextual_startup_identity(immediate) != identity
                or proposal.path.resolve() != previous.path.resolve() or proposal.sha256 != previous.sha256
                or proposal.captured_monotonic != previous.captured_monotonic):
            raise ValueError("Ultimate startup sequence is not continuous distinct known overlays")
        seen.add(identity)
        key = startup.contextual_startup_action_key(action_key, ordinal)
        matches = [(index, row) for index, row in enumerate(rows)
                   if row.get("type") == "dispatch" and row.get("action_key") == key]
        if len(matches) != 1:
            raise ValueError("Ultimate startup requires exactly one dispatch per step")
        dispatch_index, dispatch = matches[0]
        vip = identity == "VIP_POINTS_GET_PTS"
        target = startup.VIP_RESET_TARGET if vip else startup.SCARLETT_SAFE_BACK_TARGET_IDENTITY
        before_label = "contextual-vip-popup-dispatch-before" if vip else "contextual-startup-scarlett-before"
        post_label = "contextual-vip-popup-post" if vip else "contextual-startup-scarlett-post"
        detail = startup.recognize_reset_popup(immediate.frame) if vip else startup.recognize_startup_surface(immediate.frame, immediate.png)
        roi = startup._contextual_target(detail) if vip else tuple(detail["safe_exit_roi"])
        if not vip:
            proposal_detail = startup.recognize_startup_surface(proposal.frame, proposal.png)
            if roi != tuple(proposal_detail["safe_exit_roi"]):
                raise ValueError("Ultimate startup measured Back changed")
        reconciles = [(index, row) for index, row in enumerate(rows)
                      if row.get("type") == "reconcile" and row.get("action_key") == key]
        if (dispatch.get("target_identity") != target or list(roi or ()) != dispatch.get("target_roi")
                or dispatch.get("point") != [(roi[0] + roi[2]) // 2, (roi[1] + roi[3]) // 2]
                or dispatch.get("source_sha256") != immediate.sha256
                or dispatch.get("action_class") != "navigation" or dispatch.get("consequential") is not False
                or dispatch.get("execute") is not True or dispatch.get("continuation_of") is not None
                or len(reconciles) != 1 or reconciles[0][1].get("status") != "confirmed"
                or reconciles[0][1].get("post_sha256") != post.sha256
                or not proposal_index < immediate_index < dispatch_index < post_index < reconciles[0][0] < hi
                or not proposal.captured_monotonic < immediate.captured_monotonic < post.captured_monotonic
                or rows[immediate_index].get("label") != before_label or rows[post_index].get("label") != post_label
                or (previous_reconcile_index is not None and previous_reconcile_index >= immediate_index)):
            raise ValueError("Ultimate startup dispatch, chronology or reconciliation is invalid")
        expected = startup.ContextualStartupRecoveryStep(identity, key, proposal, immediate, post, target, roi,
                                                         1, True, step.get("reason")).to_mapping(session)
        if (step != expected or type(step.get("input_count")) is not int
                or step.get("confirmed") is not True or type(step.get("reason")) is not str or not step["reason"]):
            raise ValueError("Ultimate startup step differs from its current native proof")
        verified_steps.append(expected)
        dispatches.append(dispatch)
        previous = post
        previous_reconcile_index = reconciles[0][0]
        if first_immediate is None:
            first_immediate = immediate_ref
    prefix = [row for index, row in enumerate(rows) if index < hi and row.get("type") == "dispatch"]
    surface = startup.recognize_startup_surface(settled.frame, settled.png)
    popup = startup.recognize_reset_popup(settled.frame)
    if (previous.path.resolve() != settled.path.resolve() or previous.sha256 != settled.sha256 or prefix != dispatches
            or not ri < hi or not settled.captured_monotonic < home.captured_monotonic
            or surface.get("recognized") or surface.get("commercial_looking")
            or popup.get("recognized") or popup.get("blocking_unknown_modal")
            or not native._home_nav_terminal(settled.frame) or not native._home_nav_terminal(home.frame)):
        raise ValueError("Ultimate startup final Home proof is invalid")
    first = verified_steps[0]
    return {"runtime_session": str(session), "action_key": action_key,
            "target_identity": first["target_identity"], "target_roi": first["target_roi"],
            "source": p, "immediate_before": first_immediate, "settled": r, "home": h,
            "helper": dict(helper), "steps": verified_steps}


def _validate_startup_result(result):
    count = result.get("startup_navigation_count", 0)
    if type(count) is not int or count not in (0, 1, 2):
        raise ValueError("Ultimate startup navigation count is invalid")
    proof = result.get("startup_navigation_proof")
    if count == 0:
        if proof is not None:
            raise ValueError("Ultimate zero-input startup cannot claim a dismissal proof")
        return count
    if not isinstance(proof, Mapping) or not isinstance(result.get("session_directory"), str):
        raise ValueError("Ultimate startup requires current native proof")
    session = Path(result["session_directory"]).resolve()
    if proof.get("runtime_session") != str(session):
        raise ValueError("Ultimate startup proof belongs to another runtime")
    verified = _startup_navigation_proof(session,
        _startup_frame(session, proof["source"]), _startup_frame(session, proof["settled"]),
        _startup_frame(session, proof["home"]), proof.get("action_key"), proof.get("helper"), proof.get("steps"))
    if (verified != proof or result.get("initial_source_frame") != proof["source"]["frame_path"]
            or result.get("initial_source_frame_sha256") != proof["source"]["frame_sha256"]
            or result.get("initial_home_frame") != proof["home"]["frame_path"]
            or result.get("initial_home_frame_sha256") != proof["home"]["frame_sha256"]):
        raise ValueError("Ultimate startup proof does not match its route source/Home")
    return count


class UltimateRunner:
    """No device work until called under the service's held owner/run checkpoint."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path, utc_clock=time.time,
                 post_input_delay: float = 1.0, maximum_pans: int = 4):
        self.adb, self.serial, self.output_directory = adb, serial, Path(output_directory).resolve()
        self.utc_clock = utc_clock
        self.post_input_delay = _epoch(post_input_delay, "post_input_delay")
        if type(maximum_pans) is not int or not 0 <= maximum_pans <= 4:
            raise ValueError("Ultimate Home pans must be bounded by four")
        self.maximum_pans = maximum_pans

    def _identity(self, identity):
        if (not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID
                or identity.reset_id != recruitment_reset(_epoch(self.utc_clock(), "clock"))):
            raise ValueError("Ultimate task identity/reset is not current")

    def _result(self, identity, runtime, result):
        inputs, attempts, flee, valid = _consumption(runtime)
        completed = _epoch(self.utc_clock(), "completion")
        return {**result, "flow_id": FLOW_ID, "account_id": identity.account_id,
            "server_id": identity.server_id, "reset_id": identity.reset_id, "reset_identity": identity.reset_id,
            "task_id": PRODUCT_ID, "runtime_profile_id": PROFILE_ID,
            "time_basis": "utc", "completed_at_utc": completed,
            "next_eligible_at": (math.floor(completed / 86400) + 1) * 86400,
            "input_count": inputs, "total_input_count": inputs, "ultimate_dispatch_count": attempts,
            "flee_transport_calls": flee, "accounting_verified": valid,
            "session_directory": str(runtime.session.resolve()) if runtime is not None else None,
            "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0}}

    def _write_result(self, runtime, native, result):
        path = runtime.session / "result.json"
        if path.exists():
            raise ValueError("Ultimate current result was already finalized")
        native._write_operator_artifacts(runtime.session, result["terminal"])
        raw = (json.dumps(result, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        path.write_bytes(raw)
        (runtime.session / "flow-delivery-result.json").write_text(json.dumps({
            "flow_id": FLOW_ID, "serial": self.serial, "native_width": 800, "native_height": 1280,
            "runtime_profile_id": PROFILE_ID, "ultimate_challenge_result": result,
        }, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
        return hashlib.sha256(raw).hexdigest()

    def __call__(self, identity, previous_reset_id, checkpoint):
        from scripts import bluestacks_ultimate_challenge as native
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        from scripts.navigation_development_boundary import open_canonical_action_store
        from scripts.flow_delivery_ultimate_challenge_bluestacks import _validated_flee_recovery
        del previous_reset_id
        runtime, store, leased = None, None, False
        owner, state, proof = None, None, None
        result = {"status": "unresolved", "terminal": "blocked_fail_closed", "committed_action_count": 0,
                  "terminal_home_verified": False, "completed_actions": [], "startup_navigation_count": 0}
        failure = None
        try:
            checkpoint()
            self._identity(identity)
            state = load_reset_window_state(RESET_STATE_PATH)
            for recorded_reset in (state.reset_identity, state.last_success_reset_identity):
                if recorded_reset is not None:
                    if not isinstance(recorded_reset, str) or not recorded_reset.startswith("game-day-"):
                        raise ValueError("Ultimate retained reset identity requires inspection")
                    day = date.fromisoformat(recorded_reset.removeprefix("game-day-"))
                    if recorded_reset != f"game-day-{day.isoformat()}" or recorded_reset > identity.reset_id:
                        raise ValueError("Ultimate retained reset is invalid or in the future")
            precheck = evaluate_already_completed(state, current_reset_identity=identity.reset_id)
            if (state.completion_state == COMPLETION_UNKNOWN or state.pending_home_session
                    or (precheck.reason != "not already_completed" and precheck.terminal != TERMINAL_ALREADY_COMPLETED)):
                raise ValueError(precheck.reason or "Ultimate pending/unknown completion requires inspection")
            if state.last_success_reset_identity == identity.reset_id and precheck.terminal != TERMINAL_ALREADY_COMPLETED:
                raise ValueError("Ultimate reset state contradicts an existing current-day success")
            runtime = LocalBlueStacksRuntime.connect(adb=self.adb, serial=self.serial,
                output_directory=self.output_directory, workflow="ultimate-daily", execute=True)
            runtime.max_inputs = min(runtime.max_inputs, MAX_INPUTS)

            def current_checkpoint():
                checkpoint()
                self._identity(identity)
                if store is not None and not store.lease_valid_for(owner, self.utc_clock()):
                    raise RuntimeError("Ultimate action lease lost")

            runtime.checkpoint = current_checkpoint
            source = runtime.capture("ultimate-service-current-home")
            result.update(initial_source_frame=str(source.path.relative_to(runtime.session)).replace("\\", "/"),
                          initial_source_frame_sha256=source.sha256)
            if runtime.measure_foreground_package() != "com.global.ztmslg":
                raise ValueError("Ultimate startup foreground is not the game")
            if not native._home_nav_terminal(source.frame):
                from scripts.startup_recovery import recover_contextual_startup_overlay

                original = source
                action_key = f"ultimate-startup-known-overlay:{runtime.session.name}"
                before = runtime.input_count
                try:
                    recovery = recover_contextual_startup_overlay(
                        runtime, original, source_context="ultimate_canonical_home_startup",
                        recognize_successor=lambda captured: native._home_nav_terminal(captured.frame),
                        action_key=action_key, settle_seconds=self.post_input_delay,
                    )
                finally:
                    result["startup_navigation_count"] = runtime.input_count - before
                if (not recovery.resume_ready or type(recovery.input_count) is not int
                        or recovery.input_count != result["startup_navigation_count"]
                        or result["startup_navigation_count"] not in (0, 1, 2)):
                    raise ValueError(f"Ultimate known startup recovery is not ready: {recovery.reason}")
                source = runtime.capture("ultimate-service-startup-home")
                if result["startup_navigation_count"]:
                    helper = {name: getattr(recovery, name) for name in (
                        "resume_ready", "dismissed", "popup_absent", "input_count", "reason")}
                    result["startup_navigation_proof"] = _startup_navigation_proof(
                        runtime.session, original, recovery.settled_frame, source, action_key, helper,
                        [step.to_mapping(runtime.session) for step in recovery.steps])
            if not native._home_nav_terminal(source.frame) or runtime.measure_foreground_package() != "com.global.ztmslg":
                raise ValueError("Ultimate requires fresh canonical Home; unrelated battle/Lineup cannot be adopted")
            result.update(initial_home_frame=str(source.path.relative_to(runtime.session)).replace("\\", "/"),
                          initial_home_frame_sha256=source.sha256)
            if precheck.terminal == TERMINAL_ALREADY_COMPLETED:
                result.update(status=TERMINAL_ALREADY_COMPLETED, terminal=TERMINAL_ALREADY_COMPLETED,
                    terminal_home_verified=True, reset_guard_completed=True, reason=precheck.reason,
                    home_frame=str(source.path.relative_to(runtime.session)).replace("\\", "/"),
                    home_frame_sha256=source.sha256, home_nav_recognized=True)
            else:
                store = open_canonical_action_store()
                owner = f"automation-service:ultimate:{runtime.session.name}"
                store.acquire_lease(owner, self.utc_clock(), 3600.0)
                leased = True
                current_checkpoint()
                events = runtime.session / "ultimate-events.jsonl"
                normalized, detail = native._normalize_ultimate_home_before_campaign(
                    runtime=runtime, session=runtime.session, events=events, atlas_path=native.DEFAULT_HOME_ATLAS,
                    adb=Path(self.adb), serial=self.serial, source=source, maximum_pans=self.maximum_pans,
                    post_input_delay=self.post_input_delay)
                if not normalized:
                    raise ValueError(str(detail.get("reason") or "Ultimate Home normalization is not verified"))
                entry = native.run_verified_ultimate_challenge_campaign_door(runtime, atlas_path=native.DEFAULT_HOME_ATLAS,
                    maximum_pans=self.maximum_pans, execute=True, settle_seconds=self.post_input_delay,
                    semantic_opened_check=native._campaign_entry_semantically_opened)
                if entry.get("status") != "opened":
                    raise ValueError(str(entry.get("reason") or "Ultimate Campaign door did not open"))
                campaign = runtime.capture("ultimate-service-entry-bind")
                observed = native._bind_ultimate_challenge_entry(campaign.frame, reset_identity=identity.reset_id)
                decision = evaluate_navigation_only(state, observed, current_reset_identity=identity.reset_id)
                if decision.terminal != TERMINAL_NAVIGATION_ONLY_COMPLETE:
                    raise ValueError(decision.reason)
                terminal, detail = native._run_daily_route(runtime=runtime, session=runtime.session,
                    frames=runtime.frames, events=events, atlas_path=native.DEFAULT_HOME_ATLAS,
                    reset_identity=identity.reset_id, maximum_pans=self.maximum_pans,
                    post_input_delay=self.post_input_delay, entry_observation=observed, starting_state="campaign_entry")
                result.update(detail)
                proof = _current_flee_proof(runtime, native)
                if terminal != TERMINAL_COMPLETE_FOR_RESET or proof is None:
                    raise ValueError(str(detail.get("reason") or "Ultimate Flee/Home terminal is not verified"))
                inputs, attempts, flee, accounting = _consumption(runtime)
                if not accounting or attempts != 1 or flee != 1:
                    raise ValueError("Ultimate current input/Flee accounting is not one bounded daily attempt")
                home = runtime.capture("ultimate-service-terminal-home")
                if not native._home_nav_terminal(home.frame):
                    raise ValueError("Ultimate terminal canonical Home is not currently recognized")
                current_checkpoint()
                stamp = datetime.fromtimestamp(self.utc_clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                save_reset_window_state(RESET_STATE_PATH, record_verified_home_success(
                    state, reset_identity=identity.reset_id, success_at=stamp))
                result.update(status=TERMINAL_COMPLETE_FOR_RESET, terminal=TERMINAL_COMPLETE_FOR_RESET,
                    committed_action_count=1, terminal_home_verified=True, reset_guard_completed=True,
                    home_frame=str(home.path.relative_to(runtime.session)).replace("\\", "/"),
                    home_frame_sha256=home.sha256, home_nav_recognized=True)
            current_checkpoint()
            result.update(effect_reconciliation_required=False, identical_retry_denied=False)
        except Exception as exc:
            result.update(status="unresolved", terminal="blocked_fail_closed", reason=str(exc),
                committed_action_count=0, effect_reconciliation_required=True, identical_retry_denied=True)
            failure = exc
        finally:
            if store is not None:
                cleanup = []
                try:
                    if leased:
                        store.release_lease(owner, self.utc_clock())
                except Exception as exc:
                    cleanup.append(str(exc))
                try:
                    store.close()
                except Exception as exc:
                    cleanup.append(str(exc))
                if cleanup:
                    reason = "; ".join(([str(failure)] if failure else []) + cleanup)
                    result.update(status="unresolved", terminal="blocked_fail_closed", reason=reason,
                                  effect_reconciliation_required=True, identical_retry_denied=True)
                    failure = RuntimeError(reason)
        if failure is not None and runtime is not None and state is not None:
            try:
                proof = proof or _current_flee_proof(runtime, native)
                if proof is not None:
                    actions = list(result.get("completed_actions") or [])
                    if not any(action.get("action") == "tap_flee" for action in actions):
                        actions.append(proof)
                    result["completed_actions"] = actions
            except Exception as exc:
                result["flee_proof_error"] = str(exc)
        result = self._result(identity, runtime, result)
        if runtime is not None:
            try:
                digest = self._write_result(runtime, native, result)
                if (failure is not None and proof is not None and state is not None
                        and result.get("reset_guard_completed") is not True):
                    _validated_flee_recovery(runtime.session, identity.reset_id, digest)
                    save_reset_window_state(RESET_STATE_PATH, record_pending_home(state,
                        reset_identity=identity.reset_id, session_directory=str(runtime.session), result_sha256=digest))
            except Exception as exc:
                reason = "; ".join(([str(failure)] if failure else []) + [f"Ultimate evidence/reset persistence: {exc}"])
                result.update(status="unresolved", terminal="blocked_fail_closed", reason=reason,
                              effect_reconciliation_required=True, identical_retry_denied=True)
                raise UltimateRunnerError(reason, result) from exc
        if failure is not None:
            raise UltimateRunnerError(str(failure), result) from failure
        return result


def ultimate_next_due(result, identity, started_at):
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Ultimate result requires its exact task identity")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if (completed < _epoch(started_at, "start") or recruitment_reset(completed) != identity.reset_id
            or result.get("time_basis") != "utc" or result.get("runtime_profile_id") != PROFILE_ID
            or (result.get("account_id"), result.get("server_id"), result.get("reset_id"), result.get("task_id")) != (
                identity.account_id, identity.server_id, identity.reset_id, PRODUCT_ID)
            or result.get("flow_id") != FLOW_ID or result.get("terminal_home_verified") is not True
            or result.get("reset_guard_completed") is not True or result.get("accounting_verified") is not True
            or result.get("effect_reconciliation_required") or result.get("identical_retry_denied")):
        raise ValueError("Ultimate identity, reset, accounting, or Home result is not verified")
    inputs, attempts, flee, committed = (result.get(key) for key in (
        "total_input_count", "ultimate_dispatch_count", "flee_transport_calls", "committed_action_count"))
    if (type(inputs) is not int or not 0 <= inputs <= MAX_INPUTS
            or any(type(value) is not int or value not in (0, 1) for value in (attempts, flee, committed))):
        raise ValueError("Ultimate input/effect counts are invalid")
    startup_inputs = _validate_startup_result(result)
    if result.get("status") == TERMINAL_ALREADY_COMPLETED:
        if (inputs, attempts, flee, committed) != (startup_inputs, 0, 0, 0):
            raise ValueError("Ultimate already-completed observation permits only its verified startup navigation")
        if isinstance(result.get("session_directory"), str):
            rows = _startup_events(Path(result["session_directory"]).resolve())
            dispatches = [row for row in rows if row.get("type") == "dispatch"]
            if (len(dispatches) != startup_inputs or (startup_inputs
                    and dispatches[0].get("action_key") != result["startup_navigation_proof"]["action_key"])):
                raise ValueError("Ultimate already-completed native ledger contains another input")
        if startup_inputs:
            home = result["startup_navigation_proof"]["home"]
            if (result.get("home_frame") != home["frame_path"]
                    or result.get("home_frame_sha256") != home["frame_sha256"]
                    or result.get("home_nav_recognized") is not True):
                raise ValueError("Ultimate startup Home does not match its completed-reset observation")
    elif result.get("status") == TERMINAL_COMPLETE_FOR_RESET:
        if attempts != 1 or flee != 1 or committed != 1 or inputs < startup_inputs + 1:
            raise ValueError("Ultimate daily completion requires one current Flee/Home effect")
    else:
        raise ValueError("Ultimate pending/unknown result requires inspection")
    due = (math.floor(completed / 86400) + 1) * 86400
    if result.get("next_eligible_at") != due:
        raise ValueError("Ultimate next deadline is not the next UTC reset")
    return due
