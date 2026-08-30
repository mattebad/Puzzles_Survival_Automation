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
from scripts.startup_surface_recognition import (
    SCARLETT_EXPECTED_SUCCESSOR,
    SCARLETT_MAX_INPUTS,
    SCARLETT_SAFE_BACK_ROI,
    SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
    is_exact_scarlett_recognition,
    recognize_startup_surface,
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
    surface_kind: str | None = None
    safe_exit_target_identity: str | None = None
    safe_exit_roi: tuple[int, int, int, int] | None = None
    forbidden_purchase_rois: tuple[tuple[int, int, int, int], ...] = ()
    expected_successor: str | None = None
    successor_captured: bool = False

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
    surface_kind: str | None = None
    frame_sha256: str | None = None
    recognition: dict[str, object] | None = None

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
    frame_sha256 = hashlib.sha256(frame_bytes).hexdigest()
    if frame is None:
        return StartupRecoveryPlan(
            "unclassified", flow_id, None, None, False,
            "initial_frame_not_decodable", frame_sha256=frame_sha256,
        )
    startup_detail = recognize_startup_surface(frame, frame_bytes)
    if startup_detail.get("recognized"):
        owner = (
            "shared_home_startup_recovery"
            if flow_id in SHARED_HOME_RECOVERY_FLOW_IDS
            else None
        )
        return StartupRecoveryPlan(
            "recovery_required" if owner else "blocked",
            flow_id,
            SCARLETT_THREE_DAY_PACK,
            owner,
            False,
            (
                "exact Scarlett startup surface requires shared recovery"
                if owner
                else "exact Scarlett startup surface has no recovery owner"
            ),
            surface_kind=str(startup_detail.get("surface_kind") or "full_page"),
            frame_sha256=frame_sha256,
            recognition=dict(startup_detail),
        )
    if startup_detail.get("commercial_looking"):
        return StartupRecoveryPlan(
            "blocked", flow_id, None, None, False,
            "unknown_commercial_startup_surface",
            frame_sha256=frame_sha256,
            recognition=dict(startup_detail),
        )
    detail = recognize_reset_popup(frame)
    if not detail.get("recognized"):
        return StartupRecoveryPlan(
            "clear", flow_id, None, None, False,
            "no_exact_allowlisted_startup_overlay", frame_sha256=frame_sha256,
        )
    identity = str(detail.get("popup_identity") or "")
    if flow_id in SHARED_HOME_RECOVERY_FLOW_IDS:
        return StartupRecoveryPlan(
            "recovery_required", flow_id, identity,
            "shared_home_startup_recovery", False,
            "exact_vip_reset_popup_requires_child_ledger_recovery",
            frame_sha256=frame_sha256, recognition=dict(detail),
        )
    if flow_id in ROUTE_OWNED_RECOVERY_FLOW_IDS:
        return StartupRecoveryPlan(
            "route_owned", flow_id, identity,
            "flow_specific_popup_recovery", False,
            "exact_vip_reset_popup_deferred_to_route_owned_recovery",
            frame_sha256=frame_sha256, recognition=dict(detail),
        )
    return StartupRecoveryPlan(
        "blocked", flow_id, identity, None, False,
        "exact_vip_reset_popup_has_no_registered_recovery_owner",
        frame_sha256=frame_sha256, recognition=dict(detail),
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


SCARLETT_BACK_ACTION = "DISMISS_SCARLETT_THREE_DAY_PACK"
SCARLETT_BACK_ACTION_KEY = "startup-recovery:scarlett-three-day-pack-back"


def _scarlett_observation(
    captured: CapturedNativeFrame,
    detail: dict[str, object],
    *,
    successor: bool = False,
) -> Observation:
    target = detail.get("safe_exit_roi")
    roi = (
        tuple(int(value) for value in target)
        if isinstance(target, (tuple, list)) and len(target) == 4
        else None
    )
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        width=int(captured.frame.shape[1]),
        height=int(captured.frame.shape[0]),
        valid_png=True,
        corrupt=False,
        black=not bool(np.any(captured.frame)),
        source_state=(
            SCARLETT_THREE_DAY_PACK
            if not successor
            else "RETAINED_STARTUP_SUCCESSOR"
        ),
        overlay_state="none" if not successor else "none_observed",
        target_identity=(
            SCARLETT_SAFE_BACK_TARGET_IDENTITY if roi and not successor else None
        ),
        target_roi=roi if not successor else None,
        recognized=True,
        control_class="SAFE_PROMOTIONAL_BACK" if not successor else None,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=(
            SCARLETT_EXPECTED_SUCCESSOR
            if not successor
            else "RETAINED_STARTUP_SUCCESSOR"
        ),
        evidence_refs=(str(captured.path),),
        critical_roi_hashes=(
            (("scarlett_safe_back", _roi_hash(captured.frame, roi)),)
            if roi and not successor
            else ()
        ),
        source_family="promotional" if not successor else None,
        target_isolated=bool(roi and not successor),
        forbidden_region_intersects_target=False,
        arrow_geometry="standard_game_back_arrow" if not successor else None,
        forbidden_regions=(
            tuple(
                (
                    f"scarlett_forbidden_{index}",
                    tuple(int(value) for value in region),
                )
                for index, region in enumerate(
                    detail.get("forbidden_purchase_rois", ())
                )
            )
            if not successor
            else ()
        ),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )


def _scarlett_request(
    task_id: str,
    owner: str,
    session_id: str,
    action_key: str,
    observation: Observation,
) -> PolicyRequest:
    return PolicyRequest(
        action_id=f"{task_id}:{action_key}",
        action_key=action_key,
        task_id=task_id,
        task_mode="supervised_validation",
        semantic_action=SCARLETT_BACK_ACTION,
        expected_runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        observation=observation,
        monotonic_now=time.monotonic(),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0,
        lease_owner=owner,
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY,
        action_kind=SCARLETT_BACK_ACTION,
        subject=SCARLETT_SAFE_BACK_TARGET_IDENTITY,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(SCARLETT_THREE_DAY_PACK, "full_page", "in_game_back"),
        semantic_postconditions=(SCARLETT_EXPECTED_SUCCESSOR,),
        runtime_session_id=session_id,
    )


def _recover_scarlett_surface(
    runtime: LocalBlueStacksRuntime,
    *,
    task_id: str,
    initial_frame: CapturedNativeFrame,
    initial_detail: dict[str, object],
    recognize_successor: Callable[[np.ndarray], bool],
    settle_seconds: float,
    sleep: Callable[[float], None],
    recovery_scope: str | None,
    action_store_factory: Callable[[], SafetyStore] | None,
) -> StartupRecoveryResult:
    del initial_frame
    if not is_exact_scarlett_recognition(initial_detail):
        raise StartupRecoveryError("exact Scarlett recognition is not input-authoritative")
    if runtime.input_count >= min(runtime.max_inputs, SCARLETT_MAX_INPUTS):
        raise StartupRecoveryError("startup recovery input budget is exhausted")
    scope = str(recovery_scope or datetime.now(timezone.utc).date().isoformat())
    scope_digest = hashlib.sha256(f"{task_id}:{scope}".encode()).hexdigest()[:16]
    action_key = f"{SCARLETT_BACK_ACTION_KEY}:{scope_digest}"
    store = action_store_factory() if action_store_factory is not None else SafetyStore(STARTUP_RECOVERY_STORE_PATH)
    owner = f"startup-recovery:{task_id}"
    store.acquire_lease(owner, time.time(), 300.0)
    try:
        prior = store.get_action_by_key(action_key)
        if prior is not None or store.has_action_block():
            reason = "startup_recovery_occurrence_already_recorded" if prior is not None else "startup_recovery_unresolved_action_block"
            raise StartupRecoveryError(reason)
        authorization_frame = runtime.capture("startup-recovery-scarlett-authorization-before")
        authorization_detail = recognize_startup_surface(authorization_frame.frame, authorization_frame.png)
        if (
            not is_exact_scarlett_recognition(authorization_detail)
            or authorization_detail.get("critical_roi_hashes")
            != initial_detail.get("critical_roi_hashes")
            or authorization_detail.get("safe_exit_roi")
            != initial_detail.get("safe_exit_roi")
        ):
            raise StartupRecoveryError(
                "Scarlett stable identity or safe Back target changed before authorization"
            )
        authorized_observation = _scarlett_observation(authorization_frame, authorization_detail)
        request = _scarlett_request(task_id, owner, str(runtime.session), action_key, authorized_observation)
        policy = CentralPolicy(supervised_tasks=frozenset({task_id}))
        authorized = policy.evaluate(request)
        if not authorized.authorized:
            raise StartupRecoveryError(f"startup recovery policy denied: {authorized.reason_code}")
        before_count = runtime.input_count
        holder: dict[str, object] = {}

        def recapture() -> Observation:
            current = runtime.capture("startup-recovery-scarlett-dispatch-before")
            detail = recognize_startup_surface(current.frame, current.png)
            if (
                not is_exact_scarlett_recognition(detail)
                or detail.get("critical_roi_hashes")
                != authorization_detail.get("critical_roi_hashes")
                or detail.get("safe_exit_roi")
                != authorization_detail.get("safe_exit_roi")
            ):
                raise StartupRecoveryError(
                    "Scarlett stable identity or safe Back target changed before dispatch"
                )
            holder.update(before=current, detail=detail)
            return _scarlett_observation(current, detail)

        def transport(_intent) -> TransportResult:
            before = holder.get("before")
            detail = holder.get("detail")
            target = detail.get("safe_exit_roi") if isinstance(detail, dict) else None
            if (
                runtime.input_count - before_count >= SCARLETT_MAX_INPUTS
                or not isinstance(before, CapturedNativeFrame)
                or not isinstance(target, (tuple, list))
                or tuple(int(value) for value in target) != tuple(initial_detail["safe_exit_roi"])
            ):
                raise StartupRecoveryError("Scarlett safe Back target is no longer exact")
            runtime.tap(
                before,
                target_identity=SCARLETT_SAFE_BACK_TARGET_IDENTITY,
                target_roi=tuple(int(value) for value in target),
                action_key=action_key,
                action_class="navigation",
                consequential=False,
            )
            return TransportResult(True, "STARTUP_SCARLETT_IN_GAME_BACK_DISPATCHED")

        def post_observe() -> tuple[Observation, ...]:
            sleep(max(0.0, float(settle_seconds)))
            post = runtime.capture("startup-recovery-scarlett-post")
            after = recognize_startup_surface(post.frame, post.png)
            disappeared = not bool(after.get("recognized"))
            successor_admissible = bool(
                disappeared
                and not after.get("commercial_looking")
                and recognize_successor(post.frame)
            )
            holder.update(post=post, after=after, successor=disappeared, successor_admissible=successor_admissible)
            return (_scarlett_observation(post, after, successor=disappeared),)

        def reconcile(_intent, observation: Observation) -> bool:
            after = holder.get("after")
            return bool(isinstance(after, dict) and not after.get("recognized") and observation.source_state == "RETAINED_STARTUP_SUCCESSOR")

        executor = SafeActionExecutor(
            store, policy, owner, time.monotonic, transport, recapture,
            post_observe, reconcile, wall_clock=time.time, max_pre_dispatch_attempts=1,
        )
        result = executor.execute(request)
        post = holder.get("post")
        input_count = runtime.input_count - before_count
        confirmed = result.status is ActionStatus.CONFIRMED and input_count == 1
        successor_admissible = bool(holder.get("successor_admissible"))
        terminal_status = (
            "surface_dismissed_successor_captured"
            if confirmed and successor_admissible
            else "evidence_required"
            if confirmed
            else result.status.value
        )
        terminal_reason = (
            "evidence_required_unknown_scarlett_successor"
            if confirmed and not successor_admissible
            else result.reason
        )
        evidence = StartupRecoveryResult(
            terminal_status, input_count, SCARLETT_THREE_DAY_PACK,
            "RETAINED_STARTUP_SUCCESSOR" if confirmed else None,
            authorized_observation.frame_sha256,
            post.sha256 if isinstance(post, CapturedNativeFrame) else None,
            action_key, terminal_reason, surface_kind="full_page",
            safe_exit_target_identity=SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            safe_exit_roi=SCARLETT_SAFE_BACK_ROI,
            forbidden_purchase_rois=tuple(tuple(int(value) for value in region) for region in initial_detail["forbidden_purchase_rois"]),
            expected_successor=SCARLETT_EXPECTED_SUCCESSOR,
            successor_captured=confirmed,
        )
        _persist(runtime, evidence)
        if isinstance(post, CapturedNativeFrame):
            runtime.reconcile(action_key, "confirmed" if confirmed else "unresolved", post, terminal_reason)
        if not confirmed:
            raise StartupRecoveryError(f"startup recovery failed after dispatch: {result.status.value}:{terminal_reason}")
        return evidence
    except BaseException:
        _release_store(store, owner)
        raise
    else:
        _release_store(store, owner)


def _recover_vip_reset_popup(
    runtime: LocalBlueStacksRuntime,
    *,
    task_id: str,
    recognize_successor: Callable[[np.ndarray], bool],
    settle_seconds: float,
    sleep: Callable[[float], None],
    initial: dict[str, object],
    probe: CapturedNativeFrame,
    store: SafetyStore,
    owner: str,
    action_key: str,
) -> StartupRecoveryResult:
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
    result = executor.execute(request)

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
    if result.status is not ActionStatus.CONFIRMED or input_count != 1:
        raise StartupRecoveryError(
            f"startup recovery failed after dispatch: {result.status.value}:{result.reason}"
        )
    return evidence


def recover_known_startup_overlay(
    runtime: LocalBlueStacksRuntime,
    *,
    task_id: str,
    recognize_successor: Callable[[np.ndarray], bool],
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
    recovery_scope: str | None = None,
    action_store_factory: Callable[[], SafetyStore] | None = None,
    expected_source_sha256: str | None = None,
) -> StartupRecoveryResult:
    """Dismiss one exact allowlisted startup surface and capture its successor."""
    probe = runtime.capture("startup-recovery-probe")
    scarlett = recognize_startup_surface(probe.frame, probe.png)
    if scarlett.get("recognized"):
        if expected_source_sha256 is not None and (
            len(expected_source_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_source_sha256
            )
        ):
            raise StartupRecoveryError(
                "startup recovery source provenance hash is invalid"
            )
        return _recover_scarlett_surface(
            runtime,
            task_id=task_id,
            initial_frame=probe,
            initial_detail=dict(scarlett),
            recognize_successor=recognize_successor,
            settle_seconds=settle_seconds,
            sleep=sleep,
            recovery_scope=recovery_scope,
            action_store_factory=action_store_factory,
        )
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
    try:
        store.acquire_lease(owner, time.time(), 300.0)
    except BaseException:
        store.close()
        raise
    try:
        return _recover_vip_reset_popup(
            runtime,
            task_id=task_id,
            recognize_successor=recognize_successor,
            settle_seconds=settle_seconds,
            sleep=sleep,
            initial=dict(initial),
            probe=probe,
            store=store,
            owner=owner,
            action_key=action_key,
        )
    finally:
        _release_store(store, owner)
