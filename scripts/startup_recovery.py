"""Shared fail-closed recovery for exact, allowlisted startup overlays."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Callable

import cv2
import numpy as np

from safe_action_core import (
    ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest,
    SafeActionExecutor, SafetyStore, TransportResult,
)
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame, LocalBlueStacksRuntime, NATIVE_RUNTIME_PROFILE_ID,
)
from scripts.navigation_development_boundary import ORCHESTRATOR_DIR
from scripts.bluestacks_popup_recognition import (
    MAX_VIP_POPUP_INPUTS, recognize_reset_popup, vip_popup_handled,
)

VIP_RESET_ACTION = "DISMISS_RESET_POPUP"
VIP_RESET_TARGET = "reset-popup-close"
VIP_RESET_SUCCESSOR = "HOME_BASE"
VIP_RESET_ACTION_KEY = "startup-recovery:vip-reset-close"
STARTUP_RECOVERY_STORE_PATH = ORCHESTRATOR_DIR / "startup-recovery-actions.sqlite3"

SHARED_HOME_RECOVERY_FLOW_IDS = frozenset(
    {
        "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
        "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY",
        "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
        "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE",
    }
)
ROUTE_OWNED_RECOVERY_FLOW_IDS = frozenset(
    {
        "WORLD-MAP-NAVIGATION-FOUNDATION",
        "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
        "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
    }
)


class StartupRecoveryError(RuntimeError):
    """An allowlisted startup recovery could not reach its exact successor."""


@dataclass(frozen=True)
class StartupRecoveryResult:
    status: str
    input_count: int
    popup_identity: str | None
    successor_state: str | None
    before_sha256: str
    after_sha256: str | None
    action_key: str | None
    reason: str

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StartupRecoveryPlan:
    status: str
    flow_id: str
    popup_identity: str | None
    recovery_owner: str | None
    input_authority: bool
    reason: str

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def classify_startup_frame(
    flow_id: str,
    frame_bytes: bytes,
) -> StartupRecoveryPlan:
    """Classify the already-retained first frame without granting input.

    Every flow passes this seam. Exact allowlisted overlays must have an
    explicit recovery owner; a new flow cannot silently bypass an encountered
    popup. Transport remains with the route-owned runtime and its input ledger.
    """

    encoded = np.frombuffer(frame_bytes, dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if frame is None:
        return StartupRecoveryPlan(
            "unclassified",
            flow_id,
            None,
            None,
            False,
            "initial_frame_not_decodable",
        )
    detail = recognize_reset_popup(frame)
    if not detail.get("recognized"):
        return StartupRecoveryPlan(
            "clear",
            flow_id,
            None,
            None,
            False,
            "no_exact_allowlisted_startup_overlay",
        )
    identity = str(detail.get("popup_identity") or "")
    if flow_id in SHARED_HOME_RECOVERY_FLOW_IDS:
        return StartupRecoveryPlan(
            "recovery_required",
            flow_id,
            identity,
            "shared_home_startup_recovery",
            False,
            "exact_vip_reset_popup_requires_child_ledger_recovery",
        )
    if flow_id in ROUTE_OWNED_RECOVERY_FLOW_IDS:
        return StartupRecoveryPlan(
            "route_owned",
            flow_id,
            identity,
            "flow_specific_popup_recovery",
            False,
            "exact_vip_reset_popup_deferred_to_route_owned_recovery",
        )
    return StartupRecoveryPlan(
        "blocked",
        flow_id,
        identity,
        None,
        False,
        "exact_vip_reset_popup_has_no_registered_recovery_owner",
    )


def _persist(runtime: LocalBlueStacksRuntime, result: StartupRecoveryResult) -> None:
    (runtime.session / "startup-recovery-result.json").write_text(
        json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _roi_hash(frame: np.ndarray, roi: tuple[int, int, int, int]) -> str:
    x0, y0, x1, y1 = roi
    pixels = np.ascontiguousarray(frame[y0:y1, x0:x1]).tobytes()
    return hashlib.sha256(pixels).hexdigest()


def _popup_observation(captured: CapturedNativeFrame, detail: dict[str, object]) -> Observation:
    target = detail.get("target")
    roi = tuple(int(v) for v in target) if isinstance(target, (tuple, list)) and len(target) == 4 else None
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        width=int(captured.frame.shape[1]), height=int(captured.frame.shape[0]),
        valid_png=True, corrupt=False, black=not bool(np.any(captured.frame)),
        source_state="RESET_POPUP", overlay_state="known_reset_popup",
        target_identity=VIP_RESET_TARGET if roi else None, target_roi=roi,
        recognized=bool(detail.get("recognized")), control_class="RESET_CLOSE",
        consequence="navigate_zero_cost", cost_type="none", cost_amount=0, quantity=1,
        expected_postcondition=VIP_RESET_SUCCESSOR,
        evidence_refs=(str(captured.path),),
        critical_roi_hashes=(("popup_close", _roi_hash(captured.frame, roi)),) if roi else (),
        target_isolated=roi is not None, package_foreground=True,
        os_surface=False, hard_stop_detected=False,
    )


def _successor_observation(
    captured: CapturedNativeFrame, *, popup_present: bool, successor_recognized: bool,
) -> Observation:
    recognized = bool(not popup_present and successor_recognized)
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        width=int(captured.frame.shape[1]), height=int(captured.frame.shape[0]),
        valid_png=True, corrupt=False, black=not bool(np.any(captured.frame)),
        source_state=VIP_RESET_SUCCESSOR if recognized else "UNKNOWN",
        overlay_state="none_observed" if not popup_present else "known_reset_popup",
        target_identity=None, target_roi=None, recognized=recognized,
        consequence="navigate_zero_cost", cost_type="none", cost_amount=0, quantity=1,
        expected_postcondition=VIP_RESET_SUCCESSOR,
        evidence_refs=(str(captured.path),), package_foreground=True,
        os_surface=False, hard_stop_detected=False,
    )


def _request(
    task_id: str,
    owner: str,
    session_id: str,
    action_key: str,
    observation: Observation,
) -> PolicyRequest:
    return PolicyRequest(
        action_id=f"{task_id}:{action_key}", action_key=action_key,
        task_id=task_id, task_mode="supervised_validation", semantic_action=VIP_RESET_ACTION,
        expected_runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID, observation=observation,
        monotonic_now=time.monotonic(), observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0, lease_owner=owner, lease_valid=True,
        unresolved_action=False, duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY, action_kind=VIP_RESET_ACTION,
        subject=VIP_RESET_TARGET, resource_or_currency="none", maximum_cost=0,
        free_only=True, semantic_preconditions=("RESET_POPUP", "known_reset_popup"),
        semantic_postconditions=(VIP_RESET_SUCCESSOR,), runtime_session_id=session_id,
    )


def _release_store(store: SafetyStore, owner: str) -> None:
    try:
        store.release_lease(owner, time.time())
    finally:
        store.close()


def recover_known_startup_overlay(
    runtime: LocalBlueStacksRuntime,
    *,
    task_id: str,
    recognize_successor: Callable[[np.ndarray], bool],
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
    recovery_scope: str | None = None,
    action_store_factory: Callable[[], SafetyStore] | None = None,
) -> StartupRecoveryResult:
    """Dismiss one exact VIP reset popup and require canonical Home afterward."""
    probe = runtime.capture("startup-recovery-probe")
    initial = recognize_reset_popup(probe.frame)
    if not initial.get("recognized"):
        return StartupRecoveryResult(
            "not_present", 0, None, None, probe.sha256, None, None,
            "no_exact_allowlisted_startup_overlay",
        )
    if runtime.input_count >= runtime.max_inputs:
        _persist(runtime, StartupRecoveryResult(
            "blocked", 0, str(initial.get("popup_identity") or ""), None,
            probe.sha256, None, None, "startup_recovery_input_budget_exhausted",
        ))
        raise StartupRecoveryError("startup recovery input budget is exhausted")

    scope = str(recovery_scope or datetime.now(timezone.utc).date().isoformat())
    scope_digest = hashlib.sha256(f"{task_id}:{scope}".encode()).hexdigest()[:16]
    action_key = f"{VIP_RESET_ACTION_KEY}:{scope_digest}"
    store = (
        action_store_factory()
        if action_store_factory is not None
        else SafetyStore(STARTUP_RECOVERY_STORE_PATH)
    )
    owner = f"startup-recovery:{task_id}"
    store.acquire_lease(owner, time.time(), 300.0)
    prior = store.get_action_by_key(action_key)
    if prior is not None or store.has_action_block():
        reason = (
            "startup_recovery_occurrence_already_recorded"
            if prior is not None
            else "startup_recovery_unresolved_action_block"
        )
        _persist(runtime, StartupRecoveryResult(
            "blocked", 0, str(initial.get("popup_identity") or ""), None,
            probe.sha256, None, action_key, reason,
        ))
        _release_store(store, owner)
        raise StartupRecoveryError(reason)

    policy = CentralPolicy(supervised_tasks=frozenset({task_id}))
    authorization_frame = runtime.capture("startup-recovery-authorization-before")
    authorization_detail = recognize_reset_popup(authorization_frame.frame)
    if (
        not authorization_detail.get("recognized")
        or authorization_detail.get("popup_identity") != initial.get("popup_identity")
        or authorization_detail.get("target") != initial.get("target")
    ):
        _persist(runtime, StartupRecoveryResult(
            "blocked", 0, str(initial.get("popup_identity") or ""), None,
            probe.sha256, authorization_frame.sha256, action_key,
            "popup_or_target_changed",
        ))
        _release_store(store, owner)
        raise StartupRecoveryError(
            "startup recovery popup or Close target changed before authorization"
        )

    authorized_observation = _popup_observation(
        authorization_frame,
        authorization_detail,
    )
    request = _request(
        task_id,
        owner,
        str(runtime.session),
        action_key,
        authorized_observation,
    )
    authorized = policy.evaluate(request)
    if not authorized.authorized:
        _persist(runtime, StartupRecoveryResult(
            "blocked", 0, str(initial.get("popup_identity") or ""), None,
            probe.sha256, authorization_frame.sha256, action_key,
            authorized.reason_code,
        ))
        _release_store(store, owner)
        raise StartupRecoveryError(
            f"startup recovery policy denied: {authorized.reason_code}"
        )

    before_count = runtime.input_count
    holder: dict[str, object] = {}

    def recapture() -> Observation:
        dispatch_before = runtime.capture("startup-recovery-dispatch-before")
        dispatch_detail = recognize_reset_popup(dispatch_before.frame)
        if (
            not dispatch_detail.get("recognized")
            or dispatch_detail.get("popup_identity") != initial.get("popup_identity")
            or dispatch_detail.get("target") != initial.get("target")
        ):
            raise StartupRecoveryError(
                "startup recovery popup or Close target changed before dispatch"
            )
        holder["before"] = dispatch_before
        holder["detail"] = dispatch_detail
        return _popup_observation(dispatch_before, dispatch_detail)

    def transport(_intent) -> TransportResult:
        before = holder.get("before")
        current_detail = holder.get("detail")
        target = current_detail.get("target") if isinstance(current_detail, dict) else None
        if (
            runtime.input_count - before_count >= MAX_VIP_POPUP_INPUTS
            or not isinstance(before, CapturedNativeFrame)
            or not isinstance(target, (tuple, list))
            or len(target) != 4
        ):
            raise StartupRecoveryError("startup recovery target is no longer exact")
        runtime.tap(
            before,
            target_identity=VIP_RESET_TARGET,
            target_roi=tuple(int(value) for value in target),
            action_key=action_key,
            action_class="navigation",
            consequential=False,
        )
        return TransportResult(True, "STARTUP_VIP_RESET_CLOSE_DISPATCHED")

    def post_observe() -> tuple[Observation, ...]:
        sleep(max(0.0, float(settle_seconds)))
        post = runtime.capture("startup-recovery-post")
        after = recognize_reset_popup(post.frame)
        successor = bool(recognize_successor(post.frame))
        holder.update(post=post, after=after, successor=successor)
        return (_successor_observation(
            post,
            popup_present=bool(after.get("recognized")),
            successor_recognized=successor,
        ),)

    def reconcile(_intent, observation: Observation) -> bool:
        after = holder.get("after")
        return bool(
            isinstance(after, dict)
            and vip_popup_handled(
                initial,
                after,
                recognized_successor=bool(holder.get("successor")),
            )
            and observation.source_state == VIP_RESET_SUCCESSOR
        )

    executor = SafeActionExecutor(
        store, policy, owner, time.monotonic, transport, recapture,
        post_observe, reconcile, wall_clock=time.time,
        max_pre_dispatch_attempts=1,
    )
    try:
        result = executor.execute(request)
    except BaseException:
        _release_store(store, owner)
        raise

    post = holder.get("post")
    input_count = runtime.input_count - before_count
    evidence = StartupRecoveryResult(
        "recovered" if result.status is ActionStatus.CONFIRMED else result.status.value,
        input_count,
        str(initial.get("popup_identity") or ""),
        VIP_RESET_SUCCESSOR if holder.get("successor") else None,
        authorized_observation.frame_sha256,
        post.sha256 if isinstance(post, CapturedNativeFrame) else None,
        action_key,
        result.reason,
    )
    _persist(runtime, evidence)
    if isinstance(post, CapturedNativeFrame):
        status = "confirmed" if result.status is ActionStatus.CONFIRMED else "unresolved"
        runtime.reconcile(action_key, status, post, result.reason)
    _release_store(store, owner)
    if result.status is not ActionStatus.CONFIRMED or input_count != 1:
        raise StartupRecoveryError(
            f"startup recovery failed after dispatch: {result.status.value}:{result.reason}"
        )
    return evidence
