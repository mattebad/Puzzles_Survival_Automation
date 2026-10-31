"""Bounded native Personal Might route with one canonical, daily-fenced Praise."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from typing import Any

from safe_action_core import ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
from scripts.home_atlas_bluestacks import identity_from_captured
from scripts.startup_normalization import is_clean_home_frame
from tasks import personal_might_vision as vision
from tasks.perception_bundle import PerceptionBundleError
from tasks.personal_might_praise import FLOW_ID, SEMANTIC_ACTION, SOURCE_STATE, TARGET_IDENTITY, CONTROL_CLASS, CONSEQUENCE, POSTCONDITION, personal_might_daily_key


class PersonalMightPraiseBoundary:
    """Reuse the canonical executor and store for a single actual P -> I input."""

    def __init__(self, *, session, runtime, store, identity, validate_identity, settle_seconds=1.0, monotonic_clock=time.monotonic, wall_clock=time.time):
        self.session, self.runtime, self.store, self.identity = session, runtime, store, identity
        self.validate_identity = validate_identity
        self.settle_seconds, self.monotonic_clock, self.wall_clock = settle_seconds, monotonic_clock, wall_clock
        self.used = False

    def _observation(self, captured):
        source = identity_from_captured(captured, session_id=str(self.runtime.session), ordinal=self.runtime.ordinal, label="personal-might-praise")
        target = vision.bind_personal_might_praise(captured.frame, source_frame=source, source_png=captured.png)
        if target is None:
            raise PerceptionBundleError("PERSONAL_MIGHT_PRAISE_TARGET_NOT_BOUND")
        package = self.runtime.measure_foreground_package()
        return Observation(
            frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=source.runtime_profile_id, width=source.width, height=source.height,
            valid_png=True, corrupt=False, black=False, source_state=SOURCE_STATE, overlay_state="none_observed",
            target_identity=TARGET_IDENTITY, target_roi=target.target_roi, recognized=True,
            control_class=CONTROL_CLASS, consequence=CONSEQUENCE, cost_type="none", cost_amount=0,
            quantity=1, expected_postcondition=POSTCONDITION, evidence_refs=(str(captured.path),),
            critical_roi_hashes=(("personal-might-thumb", hashlib.sha256(captured.frame[target.target_roi[1]:target.target_roi[3], target.target_roi[0]:target.target_roi[2]].tobytes()).hexdigest()),),
            ocr_result_frame_sha256=captured.sha256, ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="personal_might_praise", target_isolated=True, package_foreground=package == "com.global.ztmslg",
        )

    def execute(self):
        if self.used:
            raise RuntimeError("Personal Might boundary is single-use")
        self.used = True
        self.validate_identity()
        key = personal_might_daily_key(runtime_scope=self.identity.runtime_scope, account_id=self.identity.account_id, server_id=self.identity.server_id, reset_id=self.identity.reset_id)
        action_id = "personal-might-praise-" + hashlib.sha256(f"{key}:{self.session.invocation_id}".encode()).hexdigest()
        existing = self.store.get_action_by_key(key)
        base = {"action_id": action_id, "action_key": key, "praise_transport_calls": 0, "praise_dispatch_supported": True, "effect_reconciliation_required": False}
        if existing is not None:
            if existing["final_status"] == ActionStatus.CONFIRMED.value:
                current = self.runtime.capture("personal-might-already-praised")
                if self._praised(current):
                    return {**base, "action_id": existing["action_id"], "status": "confirmed", "reason": "personal_might_already_praised", "journal_status": "confirmed", "no_work": True, "successor_frame": str(current.path), "prior_confirmation_proof": json.loads(existing["reconciliation_result_json"]), "effect_source_session": json.loads(existing["policy_request_json"])["runtime_session_id"]}
            return {**base, "status": "blocked", "reason": f"personal_might_existing_action_{existing['final_status']}", "journal_status": existing["final_status"], "effect_reconciliation_required": existing["final_status"] not in {ActionStatus.CONFIRMED.value, ActionStatus.CANCELLED.value}}
        if self.store.has_action_block():
            return {**base, "status": "blocked", "reason": "canonical_unresolved_action", "effect_reconciliation_required": True}
        proposal_capture = self.runtime.capture("personal-might-praise-proposal")
        proposal = self._observation(proposal_capture)
        immediate_capture = self.runtime.capture("personal-might-praise-policy-immediate-before")
        try:
            immediate = self._observation(immediate_capture)
        except PerceptionBundleError:
            return {**base, "status": "blocked", "reason": "personal_might_praise_immediate_target_changed", "immediate_frame": str(immediate_capture.path)}
        if immediate.capture_completed_monotonic <= proposal.capture_completed_monotonic:
            return {**base, "status": "blocked", "reason": "personal_might_praise_immediate_not_newer", "immediate_frame": str(immediate_capture.path)}

        def request(observed):
            return PolicyRequest(
                action_id=action_id, action_key=key, task_id=FLOW_ID, task_mode="supervised_validation",
                semantic_action=SEMANTIC_ACTION, expected_runtime_profile_id=observed.runtime_profile_id,
                observation=observed, monotonic_now=self.monotonic_clock(), observation_max_age_seconds=30.0,
                dispatch_max_age_seconds=30.0, lease_owner=self.session.owner,
                lease_valid=self.store.lease_valid_for(self.session.owner, self.wall_clock()),
                unresolved_action=self.store.has_action_block(), duplicate_action_key=self.store.action_key_exists(key),
                game_day_id=self.identity.reset_id, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                action_kind=SEMANTIC_ACTION, subject=TARGET_IDENTITY, maximum_cost=0, free_only=True,
                semantic_preconditions=("current_personal_might_rank", "unique_rank_1_enabled_thumb", "fixed_runtime_static_utc_reset"),
                semantic_postconditions=(POSTCONDITION,), runtime_session_id=str(self.runtime.session),
            )

        self.validate_identity()
        policy = CentralPolicy({FLOW_ID})
        issue_request = request(immediate)
        issued = policy.issue_capability(issue_request)
        self.store.audit(FLOW_ID, "capability_issued", self.wall_clock(), issued.audit, action_id)
        if not issued.authorized or issued.capability is None:
            return {**base, "status": "blocked", "reason": issued.reason_code}
        post_captures = []
        post_states = {}
        immediate_returned = False
        consume_returned = False

        def recapture():
            nonlocal consume_returned
            if consume_returned:
                raise ValueError("Personal Might immediate observation is single-use")
            consume_returned = True
            return immediate

        def single_immediate(label):
            nonlocal immediate_returned
            if not immediate_returned:
                immediate_returned = True
                return immediate_capture
            return self.runtime.capture(label)

        def successor(after):
            if str(after.path) not in post_states:
                post_captures.append(after)
                post_states[str(after.path)] = self._praised(after)
            return POSTCONDITION if len(post_captures) >= 2 and post_states[str(after.path)] else "unknown"

        def settled():
            for ordinal in (1, 2):
                time.sleep(self.settle_seconds)
                after = self.runtime.capture(f"personal-might-praise-settled-{ordinal}")
                if successor(after) != "unknown":
                    break
            return after

        def transport(_intent):
            self.validate_identity()
            self.session.run_action(
                action_class="free_action", label="personal-might-praise", capture=single_immediate,
                dispatch=lambda before: self.runtime.tap(before, target_identity=TARGET_IDENTITY, target_roi=immediate.target_roi, action_key=key, action_class="free_action", consequential=False),
                recognize=successor, settled_successor=settled, consequence_class="personal_might_praise_effect",
            )
            return TransportResult(True, "BLUESTACKS_PRAISE_DISPATCHED")

        def post_observe():
            for captured in post_captures:
                positive = post_states[str(captured.path)]
                yield Observation(
                    frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                    runtime_profile_id=immediate.runtime_profile_id, width=800, height=1280,
                    valid_png=True, corrupt=False, black=False, source_state=POSTCONDITION if positive else "UNKNOWN", overlay_state="none_observed" if positive else "unknown",
                    target_identity=None, target_roi=None, recognized=positive, evidence_refs=(str(captured.path),),
                )

        execution = SafeActionExecutor(
            self.store, policy, self.session.owner, self.monotonic_clock, transport,
            recapture, post_observe, lambda _intent, observed: bool(post_captures and observed.capture_completed_monotonic == post_captures[-1].captured_monotonic and observed.frame_sha256 == post_captures[-1].sha256 and post_states[str(post_captures[-1].path)]),
            wall_clock=self.wall_clock, max_pre_dispatch_attempts=1,
        ).execute(replace(issue_request, observation=proposal, monotonic_now=self.monotonic_clock()), issued.capability)
        journal = self.store.get_action_by_key(key)
        if post_captures and callable(getattr(self.runtime, "reconcile", None)):
            self.runtime.reconcile(key, "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved", post_captures[-1], execution.reason)
        return {
            **base, "status": "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved" if execution.status is ActionStatus.UNRESOLVED else "blocked",
            "reason": execution.reason, "praise_transport_calls": execution.transport_calls,
            "effect_reconciliation_required": execution.status is ActionStatus.UNRESOLVED,
            "journal_status": journal["final_status"] if journal is not None else None,
            "proposal_frame": str(proposal_capture.path), "proposal_sha256": proposal_capture.sha256,
            "immediate_frame": str(immediate_capture.path), "immediate_sha256": immediate_capture.sha256,
            "praise_result_frames": [str(captured.path) for captured in post_captures],
            "successor_frame": str(post_captures[-1].path) if post_captures else None,
            "successor_sha256": post_captures[-1].sha256 if post_captures else None,
        }

    def _praised(self, captured):
        source = identity_from_captured(captured, session_id=str(self.runtime.session), ordinal=self.runtime.ordinal, label="personal-might-disabled-thumb")
        return vision.personal_might_praised(captured.frame, source_frame=source, source_png=captured.png)


def _source(runtime, captured):
    return {"source_frame": identity_from_captured(captured, session_id=str(runtime.session), ordinal=runtime.ordinal, label="personal-might-navigation"), "source_png": captured.png}


def _navigate(*, session, runtime, result, name, binder, successor, settle_seconds):
    current = {}

    def authorize(before):
        target = binder(before)
        if target is None:
            raise PerceptionBundleError("PERSONAL_MIGHT_NAVIGATION_TARGET_CHANGED")
        current["target"] = target

    def dispatch(before):
        target = current["target"]
        current["key"] = f"personal-might:{name}:{before.sha256[:12]}"
        runtime.tap(before, target_identity=target.target_identity, target_roi=target.target_roi, action_key=current["key"])

    def recognize(after):
        current["after"] = after
        result["successor_frame"] = str(after.path)
        result["successor_sha256"] = after.sha256
        return name if successor(after) else "unknown"

    def settled():
        time.sleep(settle_seconds)
        return runtime.capture(f"personal-might-{name}-settled")

    action = session.run_action(action_class="navigation", label=f"personal-might-{name}", capture=runtime.capture, authorize=authorize, dispatch=dispatch, recognize=recognize, settled_successor=settled, consequence_class="navigation_only")
    if current.get("after") is not None and callable(getattr(runtime, "reconcile", None)):
        runtime.reconcile(current["key"], "confirmed" if action.status == "completed" else "unresolved", current["after"], action.reason)
    result["navigation_outcome"] = action.status
    if action.status != "completed":
        result["reason"] = f"personal_might_{name}_successor_unknown"
        return None
    result.setdefault("verified_navigation", []).append(name)
    return current["after"]


def return_home(*, session, runtime, settle_seconds=1.0):
    """At most two visible Back inputs; caller must have cleared the effect fence."""
    result = {"status": "blocked", "reason": "personal_might_return_source_not_bound", "terminal_home_verified": False, "verified_navigation": []}
    current = session.observe(runtime.capture, label="personal-might-return-source")
    if vision.is_personal_might(current.frame, **_source(runtime, current)):
        if not vision.personal_might_praised(current.frame, **_source(runtime, current)):
            return result
        current = _navigate(session=session, runtime=runtime, result=result, name="back_leaderboard", binder=lambda before: vision.bind_back(before.frame, **_source(runtime, before), personal_page=True), successor=lambda after: vision.is_rankings(after.frame, **_source(runtime, after)), settle_seconds=settle_seconds)
        if current is None:
            return result
    if vision.is_rankings(current.frame, **_source(runtime, current)):
        current = _navigate(session=session, runtime=runtime, result=result, name="back_home", binder=lambda before: vision.bind_back(before.frame, **_source(runtime, before), personal_page=False), successor=lambda after: is_clean_home_frame(after.frame) and not vision.more_menu_present(after.frame, **_source(runtime, after)), settle_seconds=settle_seconds)
        if current is None:
            return result
    if is_clean_home_frame(current.frame) and not vision.more_menu_present(current.frame, **_source(runtime, current)):
        result.update(status="completed", reason="personal_might_praise_home_verified", terminal_home_verified=True)
    return result


def run(*, session, runtime, settle_seconds: float = 1.0, praise_boundary=None) -> dict[str, Any]:
    result = {"status": "blocked", "reason": "personal_might_source_not_bound", "praise_transport_calls": 0, "praise_dispatch_supported": False, "terminal_home_verified": False, "verified_navigation": []}

    def source(captured):
        return _source(runtime, captured)

    def home_more(captured):
        return vision.bind_home_more(captured.frame, **source(captured), home_is_clean=is_clean_home_frame)

    def rankings(captured):
        return vision.bind_more_rankings(captured.frame, **source(captured), home_is_clean=is_clean_home_frame)

    def check(captured):
        return vision.bind_personal_might_check(captured.frame, **source(captured))

    def more_menu(captured):
        return vision.recognize_more_menu(captured.frame, **source(captured), home_is_clean=is_clean_home_frame)

    def rankings_page(captured):
        return vision.is_rankings(captured.frame, **source(captured))

    def personal_page(captured):
        return vision.is_personal_might(captured.frame, **source(captured))

    def navigate(name, binder, successor):
        return _navigate(session=session, runtime=runtime, result=result, name=name, binder=binder, successor=successor, settle_seconds=settle_seconds)

    current = session.observe(runtime.capture, label="personal-might-source")
    if not rankings_page(current) and not personal_page(current):
        if not more_menu(current):
            if home_more(current) is None:
                session.terminal_status = "evidence_required"
                return result
            current = navigate("more_menu", home_more, more_menu)
            if current is None:
                session.terminal_status = "evidence_required"
                return result
        if rankings(current) is None:
            result["reason"] = "personal_might_rankings_glyph_not_bound"
            session.terminal_status = "evidence_required"
            return result
        current = navigate("rankings_page", rankings, rankings_page)
        if current is None:
            session.terminal_status = "evidence_required"
            return result
    if not personal_page(current):
        if check(current) is None:
            result["reason"] = "personal_might_rankings_row_native_evidence_required"
            session.terminal_status = "evidence_required"
            return result
        current = navigate("personal_might_page", check, personal_page)
        if current is None:
            session.terminal_status = "evidence_required"
            return result
    if praise_boundary is not None:
        result.update(praise_boundary.execute())
        if result.get("journal_status") == "confirmed" and result.get("status") == "confirmed":
            earlier_navigation = result["verified_navigation"]
            home = return_home(session=session, runtime=runtime, settle_seconds=settle_seconds)
            result.update(home)
            result["verified_navigation"] = [*earlier_navigation, *home["verified_navigation"]]
    else:
        result["reason"] = "personal_might_canonical_praise_boundary_required"
    session.terminal_status = "completed" if result.get("status") == "completed" and result.get("terminal_home_verified") is True else "evidence_required"
    return result
