"""Shared fail-closed recovery for exact, allowlisted startup overlays."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
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
    MAX_VIP_POPUP_INPUTS, classify_popup_recovery, recognize_reset_popup,
    vip_popup_handled,
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


@dataclass(frozen=True)
class ContextualStartupRecoveryStep:
    popup_identity: str
    action_key: str
    source_frame: CapturedNativeFrame
    immediate_before: CapturedNativeFrame
    settled_frame: CapturedNativeFrame | None
    target_identity: str
    target_roi: tuple[int, int, int, int]
    input_count: int
    confirmed: bool
    reason: str

    def to_mapping(self, session) -> dict[str, object]:
        value = {"popup_identity": self.popup_identity, "action_key": self.action_key,
                 "target_identity": self.target_identity, "target_roi": list(self.target_roi),
                 "input_count": self.input_count, "confirmed": self.confirmed, "reason": self.reason}
        for name, frame in (("source", self.source_frame), ("immediate_before", self.immediate_before),
                            ("settled", self.settled_frame)):
            value[name + "_frame"] = frame.path.relative_to(session).as_posix() if frame else None
            value[name + "_sha256"] = frame.sha256 if frame else None
            value[name + "_captured_monotonic"] = frame.captured_monotonic if frame else None
        return value


@dataclass(frozen=True)
class ContextualPopupRecoveryResult:
    settled_frame: CapturedNativeFrame | None
    dismissed: bool | None
    popup_absent: bool | None
    resume_ready: bool
    input_count: int
    reason: str
    steps: tuple[ContextualStartupRecoveryStep, ...] = ()


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
        return StartupRecoveryPlan(
            "recovery_required",
            flow_id,
            SCARLETT_THREE_DAY_PACK,
            "shared_startup_surface_recovery",
            False,
            "exact Scarlett startup surface requires shared recovery",
            surface_kind=str(startup_detail.get("surface_kind") or "full_page"),
            frame_sha256=frame_sha256,
            recognition=dict(startup_detail),
        )
    if flow_id == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION":
        from scripts.bluestacks_ultimate_challenge import _bind_ultimate_defeat_continue

        target = _bind_ultimate_defeat_continue(frame)
        if target is not None:
            return StartupRecoveryPlan(
                "route_owned", flow_id, "ULTIMATE_DEFEAT", "flow_specific_popup_recovery", False,
                "verified_defeat_requires_post_flee_route_owned_continuation",
                frame_sha256=frame_sha256,
                recognition={"state": "ULTIMATE_DEFEAT", "continue_roi": target},
            )
    if startup_detail.get("commercial_looking"):
        return StartupRecoveryPlan(
            "blocked", flow_id, None, None, False,
            "unknown_commercial_startup_surface",
            frame_sha256=frame_sha256,
            recognition=dict(startup_detail),
        )
    detail = recognize_reset_popup(frame)
    if detail.get("blocking_unknown_modal"):
        return StartupRecoveryPlan(
            "blocked", flow_id, None, None, False,
            "blocking_unknown_startup_modal",
            frame_sha256=frame_sha256,
            recognition=dict(detail),
        )
    if not detail.get("recognized"):
        return StartupRecoveryPlan(
            "clear", flow_id, None, None, False,
            "no_exact_allowlisted_startup_overlay", frame_sha256=frame_sha256,
        )
    identity = str(detail.get("popup_identity") or "")
    return StartupRecoveryPlan(
        "recovery_required", flow_id, identity,
        "shared_home_startup_recovery", False,
        "exact_vip_reset_popup_requires_child_ledger_recovery",
        frame_sha256=frame_sha256, recognition=dict(detail),
    )


def _persist(runtime: LocalBlueStacksRuntime, result: StartupRecoveryResult) -> None:
    path = runtime.session / "startup-recovery-result.json"
    ordinal = 2
    while path.exists():
        path = runtime.session / f"startup-recovery-result-{ordinal:02d}.json"
        ordinal += 1
    path.write_text(
        json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _roi_hash(frame: np.ndarray, roi: tuple[int, int, int, int]) -> str:
    x0, y0, x1, y1 = roi
    pixels = np.ascontiguousarray(frame[y0:y1, x0:x1]).tobytes()
    return hashlib.sha256(pixels).hexdigest()


def _contextual_exception_is_control(exc: BaseException) -> bool:
    """Keep stop/checkpoint/cancellation exceptions out of recovery mapping."""

    if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit, StopIteration, StopAsyncIteration)):
        return True
    marker = f"{type(exc).__name__} {exc}".casefold()
    return any(token in marker for token in ("stop", "checkpoint", "cancel", "abort"))


def _contextual_native_frame(frame: object) -> bool:
    image = getattr(frame, "frame", None)
    return bool(
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.ndim == 3
        and image.shape == (1280, 800, 3)
    )


def _contextual_target(detail: object) -> tuple[int, int, int, int] | None:
    if not isinstance(detail, dict):
        return None
    target = detail.get("target")
    if not isinstance(target, (tuple, list)) or len(target) != 4:
        return None
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in target):
        return None
    bounds = tuple(target)
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        return None
    return bounds


def _contextual_exact_vip(detail: object) -> bool:
    """Require the exact recognizer identity without duplicating OCR policy."""

    if not isinstance(detail, dict) or not bool(detail.get("recognized")):
        return False
    if detail.get("popup_identity") != "VIP_POINTS_GET_PTS":
        return False
    if detail.get("target_identity") != VIP_RESET_TARGET:
        return False
    for field in (
        "title_identity",
        "body_identity",
        "literal_close",
        "geometry_valid",
        "panel_present",
    ):
        if field in detail and not bool(detail[field]):
            return False
    return _contextual_target(detail) is not None


def _contextual_runtime_count(runtime: object) -> int | None:
    value = getattr(runtime, "input_count", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _contextual_runtime_has_key(runtime: object, action_key: str) -> bool:
    for attribute in ("action_keys", "keys"):
        values = getattr(runtime, attribute, None)
        if values is None:
            continue
        try:
            if action_key in values:
                return True
        except TypeError:
            continue
    return False

def _contextual_runtime_state_changed(
    runtime: object,
    *,
    before_count: int | None,
    action_key: str,
) -> bool:
    after_count = _contextual_runtime_count(runtime)
    if before_count is not None and after_count is not None and after_count != before_count:
        return True
    return _contextual_runtime_has_key(runtime, action_key)


def _contextual_runtime_denied(runtime: object, action_key: str) -> bool:
    if _contextual_runtime_has_key(runtime, action_key):
        return True
    count = _contextual_runtime_count(runtime)
    maximum = getattr(runtime, "max_inputs", None)
    if count is None or maximum is None:
        return False
    try:
        return count >= int(maximum)
    except (TypeError, ValueError):
        return False


def _contextual_input_delta(runtime: object, before: int | None) -> int:
    after = _contextual_runtime_count(runtime)
    if before is not None and after is not None:
        return max(0, min(1, after - before))
    return 0


def _contextual_result(
    *,
    settled_frame: CapturedNativeFrame | None,
    dismissed: bool | None,
    popup_absent: bool | None,
    resume_ready: bool,
    input_count: int,
    reason: str,
) -> ContextualPopupRecoveryResult:
    return ContextualPopupRecoveryResult(
        settled_frame=settled_frame,
        dismissed=dismissed,
        popup_absent=popup_absent,
        resume_ready=bool(resume_ready),
        input_count=max(0, min(1, int(input_count))),
        reason=reason,
    )


def recover_contextual_vip_popup(
    runtime: LocalBlueStacksRuntime,
    captured: CapturedNativeFrame,
    *,
    source_context: str,
    recognize_successor: Callable[[CapturedNativeFrame], bool],
    action_key: str,
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
) -> ContextualPopupRecoveryResult:
    """Dismiss one exact VIP popup without owning route state or a durable ledger."""

    if not isinstance(source_context, str) or not source_context.strip():
        raise ValueError("source_context is required")
    if not isinstance(action_key, str) or not action_key.strip():
        raise ValueError("action_key is required")
    if not _contextual_native_frame(captured):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )

    try:
        initial_detail = recognize_reset_popup(captured.frame)
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if (
        not isinstance(initial_detail, dict)
        or "recognized" not in initial_detail
    ):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if not bool(initial_detail.get("recognized")):
        if initial_detail.get("reason") == "profile_dimensions_mismatch":
            return _contextual_result(
                settled_frame=None,
                dismissed=False,
                popup_absent=None,
                resume_ready=False,
                input_count=0,
                reason="vip_popup_revalidation_failed",
            )
        if bool(initial_detail.get("blocking_unknown_modal")):
            return _contextual_result(
                settled_frame=captured,
                dismissed=False,
                popup_absent=True,
                resume_ready=False,
                input_count=0,
                reason="blocking_unknown_modal_present",
            )
        try:
            successor = bool(recognize_successor(captured))
        except BaseException as exc:
            if _contextual_exception_is_control(exc):
                raise
            successor = False
        return _contextual_result(
            settled_frame=captured,
            dismissed=False,
            popup_absent=True,
            resume_ready=successor,
            input_count=0,
            reason="exact_vip_popup_absent",
        )

    try:
        initial_classification = classify_popup_recovery(
            initial_detail,
            source_context=source_context,
        )
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if (
        not _contextual_exact_vip(initial_detail)
        or not bool(getattr(initial_classification, "allows_dismissal", False))
    ):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_dismissal_not_allowed",
        )
    if _contextual_runtime_denied(runtime, action_key):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_dispatch_not_authorized",
        )

    try:
        dispatch_before = runtime.capture("contextual-vip-popup-dispatch-before")
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if not _contextual_native_frame(dispatch_before):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    try:
        dispatch_detail = recognize_reset_popup(dispatch_before.frame)
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if not isinstance(dispatch_detail, dict):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if (
        not _contextual_exact_vip(dispatch_detail)
        or dispatch_detail.get("popup_identity")
        != initial_detail.get("popup_identity")
        or dispatch_detail.get("target_identity")
        != initial_detail.get("target_identity")
    ):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    target = _contextual_target(dispatch_detail)
    if target is None:
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_revalidation_failed",
        )
    if _contextual_runtime_denied(runtime, action_key):
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_dispatch_not_authorized",
        )

    before_count = _contextual_runtime_count(runtime)
    tap_error: BaseException | None = None
    try:
        runtime.tap(
            dispatch_before,
            target_identity=VIP_RESET_TARGET,
            target_roi=target,
            action_key=action_key,
            action_class="navigation",
            consequential=False,
        )
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        tap_error = exc

    input_delta = _contextual_input_delta(runtime, before_count)
    transport_started = bool(
        _contextual_runtime_state_changed(
            runtime,
            before_count=before_count,
            action_key=action_key,
        )
        or (
            tap_error is not None
            and (
                bool(getattr(tap_error, "dispatched", False))
                or bool(getattr(tap_error, "uncertain", False))
            )
        )
    )
    if tap_error is not None and not transport_started:
        return _contextual_result(
            settled_frame=None,
            dismissed=False,
            popup_absent=None,
            resume_ready=False,
            input_count=0,
            reason="vip_popup_dispatch_not_authorized",
        )
    if tap_error is not None:
        reason = "vip_popup_transport_uncertain"
        try:
            sleep(max(0.0, float(settle_seconds)))
            uncertain_post = runtime.capture("contextual-vip-popup-post")
        except BaseException as exc:
            if _contextual_exception_is_control(exc):
                raise
            uncertain_post = None
        if _contextual_native_frame(uncertain_post):
            runtime.reconcile(action_key, "unresolved", uncertain_post, reason)
        return _contextual_result(
            settled_frame=None,
            dismissed=None,
            popup_absent=None,
            resume_ready=False,
            input_count=1,
            reason=reason,
        )

    input_count = 1 if input_delta == 0 else input_delta
    try:
        sleep(max(0.0, float(settle_seconds)))
        post = runtime.capture("contextual-vip-popup-post")
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        return _contextual_result(
            settled_frame=None,
            dismissed=True,
            popup_absent=None,
            resume_ready=False,
            input_count=input_count,
            reason="vip_popup_post_capture_failed",
        )
    if not _contextual_native_frame(post):
        return _contextual_result(
            settled_frame=None,
            dismissed=True,
            popup_absent=None,
            resume_ready=False,
            input_count=input_count,
            reason="vip_popup_post_capture_failed",
        )
    try:
        post_detail = recognize_reset_popup(post.frame)
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        runtime.reconcile(
            action_key,
            "unresolved",
            post,
            "vip_popup_post_capture_failed",
        )
        return _contextual_result(
            settled_frame=None,
            dismissed=True,
            popup_absent=None,
            resume_ready=False,
            input_count=input_count,
            reason="vip_popup_post_capture_failed",
        )
    if (
        not isinstance(post_detail, dict)
        or "recognized" not in post_detail
        or post_detail.get("reason") == "profile_dimensions_mismatch"
    ):
        runtime.reconcile(
            action_key,
            "unresolved",
            post,
            "vip_popup_post_capture_failed",
        )
        return _contextual_result(
            settled_frame=None,
            dismissed=True,
            popup_absent=None,
            resume_ready=False,
            input_count=input_count,
            reason="vip_popup_post_capture_failed",
        )
    if _contextual_exact_vip(post_detail):
        reason = "vip_popup_persisted"
        runtime.reconcile(action_key, "unresolved", post, reason)
        return _contextual_result(
            settled_frame=post,
            dismissed=True,
            popup_absent=False,
            resume_ready=False,
            input_count=input_count,
            reason=reason,
        )

    if bool(post_detail.get("blocking_unknown_modal")):
        reason = "blocking_unknown_modal_present"
        runtime.reconcile(action_key, "confirmed", post, reason)
        return _contextual_result(
            settled_frame=post,
            dismissed=True,
            popup_absent=True,
            resume_ready=False,
            input_count=input_count,
            reason=reason,
        )

    try:
        successor = bool(recognize_successor(post))
    except BaseException as exc:
        if _contextual_exception_is_control(exc):
            raise
        successor = False
    reason = (
        "popup_dismissed_resume_ready"
        if successor
        else "popup_dismissed_context_not_ready"
    )
    runtime.reconcile(action_key, "confirmed", post, reason)
    return _contextual_result(
        settled_frame=post,
        dismissed=True,
        popup_absent=True,
        resume_ready=successor,
        input_count=input_count,
        reason=reason,
    )


def _contextual_startup_frame_valid(captured: object, *, after: CapturedNativeFrame | None = None) -> bool:
    if not isinstance(captured, CapturedNativeFrame) or not _contextual_native_frame(captured):
        return False
    if (not isinstance(captured.png, bytes) or not captured.png
            or hashlib.sha256(captured.png).hexdigest() != captured.sha256
            or type(captured.captured_monotonic) not in (int, float)
            or not math.isfinite(captured.captured_monotonic) or captured.captured_monotonic < 0):
        return False
    try:
        decoded = cv2.imdecode(np.frombuffer(captured.png, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return False
    if decoded is None or not np.array_equal(decoded, captured.frame):
        return False
    return after is None or (
        captured.captured_monotonic > after.captured_monotonic and captured.path != after.path
    )


def _contextual_startup_manual_context(source_context: str) -> bool:
    context = "_" + source_context.casefold().replace("-", "_").replace(" ", "_") + "_"
    return any(f"_{state}_" in context for state in (
        "login", "credentials", "account_switch", "account_selection", "tutorial",
        "captcha", "manual_only", "manual_required",
    ))


def _contextual_startup_details(captured):
    surface = recognize_startup_surface(captured.frame, captured.png)
    popup = recognize_reset_popup(captured.frame)
    if not isinstance(surface, dict) or not isinstance(popup, dict):
        raise StartupRecoveryError("startup recognizer returned no current classification")
    identity = None
    if not popup.get("blocking_unknown_modal"):
        if surface.get("recognized"):
            if (not popup.get("recognized") and is_exact_scarlett_recognition(surface)
                    and surface.get("frame_sha256") == captured.sha256):
                identity = SCARLETT_THREE_DAY_PACK
        elif not surface.get("commercial_looking") and _contextual_exact_vip(popup):
            identity = "VIP_POINTS_GET_PTS"
    return identity, surface, popup


def contextual_startup_identity(captured: CapturedNativeFrame) -> str | None:
    """Return only an exact known overlay identity on an intact current PNG."""
    if not _contextual_startup_frame_valid(captured):
        return None
    return _contextual_startup_details(captured)[0]


def contextual_startup_action_key(action_key: str, ordinal: int) -> str:
    return action_key if ordinal == 0 else f"{action_key}:{ordinal}"


def recover_contextual_startup_overlay(
    runtime: LocalBlueStacksRuntime,
    captured: CapturedNativeFrame,
    *,
    source_context: str,
    recognize_successor: Callable[[CapturedNativeFrame], bool],
    action_key: str,
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
) -> ContextualPopupRecoveryResult:
    """Recover up to two distinct known overlays on the caller's native ledger.

    A known next overlay confirms only the preceding dismissal. Continuation
    still requires a clear frame accepted by the active route. No ownership,
    lease, resource authority, transport or input budget is created here.
    """
    if not isinstance(source_context, str) or not source_context.strip():
        raise ValueError("source_context is required")
    if not isinstance(action_key, str) or not action_key.strip():
        raise ValueError("action_key is required")
    if not callable(recognize_successor):
        raise ValueError("recognize_successor is required")
    if type(settle_seconds) not in (int, float) or not math.isfinite(settle_seconds) or settle_seconds < 0:
        raise ValueError("settle_seconds must be finite and non-negative")

    steps = []
    consumed = 0
    classifications = {}

    def checkpoint():
        current = getattr(runtime, "checkpoint", None)
        if current is not None:
            current()

    def result(reason, *, post=None, ready=False, absent=None):
        return ContextualPopupRecoveryResult(post, bool(steps) if ready else (None if consumed else False),
                                             absent, ready, consumed, reason, tuple(steps))

    def classify(frame):
        if not _contextual_startup_frame_valid(frame):
            raise StartupRecoveryError("startup capture is no longer intact")
        if id(frame) not in classifications:
            classifications[id(frame)] = _contextual_startup_details(frame)
        return classifications[id(frame)]

    def clear_successor(frame):
        _identity, surface, popup = classify(frame)
        return bool(isinstance(surface, dict) and isinstance(popup, dict)
                    and not surface.get("recognized") and not surface.get("commercial_looking")
                    and not popup.get("recognized") and not popup.get("blocking_unknown_modal")
                    and recognize_successor(frame))

    checkpoint()
    if _contextual_startup_manual_context(source_context) or not _contextual_startup_frame_valid(captured):
        return result("startup_source_not_recoverable")
    source = captured
    targets = {"VIP_POINTS_GET_PTS": VIP_RESET_TARGET,
               SCARLETT_THREE_DAY_PACK: SCARLETT_SAFE_BACK_TARGET_IDENTITY}
    actions = getattr(runtime, "frame_actions", None)
    seen = {identity for identity, target in targets.items()
            if any(isinstance(item, tuple) and len(item) >= 2 and item[1] == target
                   for item in actions)} if isinstance(actions, set) else set()
    for ordinal in range(2):
        checkpoint()
        try:
            identity, surface, popup = classify(source)
            if identity is None:
                ready = clear_successor(source)
                checkpoint()
                return result("startup_successor_observed" if ready else "unknown_startup_surface",
                              post=source, ready=ready, absent=True if ready else None)
        except Exception as exc:
            if _contextual_exception_is_control(exc):
                raise
            return result("startup_source_not_recognized", post=source)
        key = contextual_startup_action_key(action_key, ordinal)
        count, maximum = getattr(runtime, "input_count", None), getattr(runtime, "max_inputs", None)
        if (not isinstance(actions, set) or identity in seen or type(count) is not int or type(maximum) is not int
                or not 0 <= count < maximum or _contextual_runtime_has_key(runtime, key)):
            return result("startup_recovery_budget_or_occurrence_denied", post=source)
        target = targets[identity]
        vip = identity == "VIP_POINTS_GET_PTS"
        before_label = "contextual-vip-popup-dispatch-before" if vip else "contextual-startup-scarlett-before"
        post_label = "contextual-vip-popup-post" if vip else "contextual-startup-scarlett-post"
        try:
            checkpoint()
            immediate = runtime.capture(before_label)
            if (not _contextual_startup_frame_valid(immediate, after=source)
                    or classify(immediate)[0] != identity):
                return result("startup_revalidation_not_fresh_or_changed", post=source)
            _identity, current_surface, current_popup = classify(immediate)
            detail = current_popup if vip else current_surface
            roi = _contextual_target(detail) if vip else tuple(detail["safe_exit_roi"])
            proposal_roi = _contextual_target(popup) if vip else tuple(surface["safe_exit_roi"])
            if roi is None or (not vip and roi != proposal_roi):
                return result("startup_back_target_changed", post=source)
        except Exception as exc:
            if _contextual_exception_is_control(exc):
                raise
            return result("startup_revalidation_failed", post=source)
        checkpoint()
        before = runtime.input_count
        transport_error = None
        try:
            runtime.tap(immediate, target_identity=target, target_roi=roi, action_key=key,
                        action_class="navigation", consequential=False)
        except Exception as exc:
            if _contextual_exception_is_control(exc):
                raise
            transport_error = exc
        delta = runtime.input_count - before
        consumed += max(0, delta)
        seen.add(identity)
        post, next_identity, ready = None, None, False
        reason = "startup_dispatch_not_accounted"
        confirmed = False
        if delta == 1:
            reason = "startup_successor_not_verified"
            try:
                checkpoint()
                sleep(float(settle_seconds))
                post = runtime.capture(post_label)
                if _contextual_startup_frame_valid(post, after=immediate):
                    next_identity = classify(post)[0]
                    ready = next_identity is None and clear_successor(post)
                    confirmed = transport_error is None and (ready or (next_identity is not None and next_identity not in seen))
                    reason = "startup_overlay_recovered" if ready else (
                        "startup_next_known_overlay" if confirmed else "startup_successor_not_verified")
                else:
                    reason = "startup_successor_capture_not_fresh"
            except Exception as exc:
                if _contextual_exception_is_control(exc):
                    raise
                reason = "startup_successor_not_verified"
        if transport_error is not None:
            confirmed, ready = False, False
            reason = "vip_popup_transport_uncertain" if vip else "startup_transport_uncertain"
        steps.append(ContextualStartupRecoveryStep(identity, key, source, immediate, post, target, roi,
                                                   max(0, delta), confirmed, reason))
        checkpoint()
        if post is not None:
            runtime.reconcile(key, "confirmed" if confirmed else "unresolved", post, reason)
        if not confirmed:
            return result(reason, post=post)
        if ready:
            return result("startup_overlay_recovered", post=post, ready=True, absent=True)
        source = post
    return result("startup_recovery_budget_or_occurrence_denied", post=source)


def _popup_observation(captured: CapturedNativeFrame, detail: dict[str, object], *, successor_state: str = VIP_RESET_SUCCESSOR) -> Observation:
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
        expected_postcondition=successor_state,
        evidence_refs=(str(captured.path),),
        critical_roi_hashes=(("popup_close", _roi_hash(captured.frame, roi)),) if roi else (),
        target_isolated=roi is not None, package_foreground=True,
        os_surface=False, hard_stop_detected=False,
    )


def _successor_observation(
    captured: CapturedNativeFrame, *, popup_present: bool, successor_recognized: bool,
    successor_state: str = VIP_RESET_SUCCESSOR,
) -> Observation:
    recognized = bool(not popup_present and successor_recognized)
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        width=int(captured.frame.shape[1]), height=int(captured.frame.shape[0]),
        valid_png=True, corrupt=False, black=not bool(np.any(captured.frame)),
        source_state=successor_state if recognized else "UNKNOWN",
        overlay_state="none_observed" if not popup_present else "known_reset_popup",
        target_identity=None, target_roi=None, recognized=recognized,
        consequence="navigate_zero_cost", cost_type="none", cost_amount=0, quantity=1,
        expected_postcondition=successor_state,
        evidence_refs=(str(captured.path),), package_foreground=True,
        os_surface=False, hard_stop_detected=False,
    )


def _request(
    task_id: str,
    owner: str,
    session_id: str,
    action_key: str,
    observation: Observation,
    successor_state: str = VIP_RESET_SUCCESSOR,
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
        semantic_postconditions=(successor_state,), runtime_session_id=session_id,
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
    if runtime.input_count >= runtime.max_inputs:
        raise StartupRecoveryError("startup recovery input budget is exhausted")
    scope = str(recovery_scope or "startup")
    # Navigation recovery is once per invocation, not a game-day resource effect.
    scope_digest = hashlib.sha256(json.dumps(
        (task_id, scope, str(runtime.session.resolve())), separators=(",", ":")
    ).encode()).hexdigest()[:16]
    action_key = f"{SCARLETT_BACK_ACTION_KEY}:{scope_digest}"
    store = action_store_factory() if action_store_factory is not None else SafetyStore(STARTUP_RECOVERY_STORE_PATH)
    owner = f"startup-recovery:{task_id}"
    try:
        store.acquire_lease(owner, time.time(), 300.0)
    except BaseException:
        store.close()
        raise
    try:
        prior = store.get_action_by_key(action_key)
        if prior is not None or store.has_action_block():
            reason = "startup_recovery_occurrence_already_recorded" if prior is not None else "startup_recovery_unresolved_action_block"
            raise StartupRecoveryError(reason)
        authorization_frame = runtime.capture("startup-recovery-scarlett-authorization-before")
        authorization_detail = recognize_startup_surface(authorization_frame.frame, authorization_frame.png)
        if (
            not is_exact_scarlett_recognition(authorization_detail)
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
    finally:
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
    successor_state: str = VIP_RESET_SUCCESSOR,
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
        successor_state=successor_state,
    )
    request = _request(
        task_id,
        owner,
        str(runtime.session),
        action_key,
        authorized_observation,
        successor_state,
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
        return _popup_observation(dispatch_before, dispatch_detail, successor_state=successor_state)

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
            successor_state=successor_state,
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
            and observation.source_state == successor_state
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
        successor_state if holder.get("successor") else None,
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
    successor_state: str = VIP_RESET_SUCCESSOR,
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

    scope = str(recovery_scope or "startup")
    # A later startup may recover again without reusing this invocation's action.
    scope_digest = hashlib.sha256(json.dumps(
        (task_id, scope, str(runtime.session.resolve())), separators=(",", ":")
    ).encode()).hexdigest()[:16]
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
            successor_state=successor_state,
        )
    finally:
        _release_store(store, owner)
