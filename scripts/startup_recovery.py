"""Shared fail-closed recovery for exact, allowlisted startup overlays."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Callable

import cv2
import numpy as np

from automation_service.registry import ULTIMATE_FLOW_ID
from automation_service.state import BotStateManager
from safe_action_core import (
    ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest,
    SafeActionExecutor, SafetyStore, TransportResult,
)
from safe_action_core.path_safety import UnsafePathError, require_no_untrusted_symlinks
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame, LocalBlueStacksRuntime, NATIVE_RUNTIME_PROFILE_ID,
)
from scripts.navigation_development_boundary import ORCHESTRATOR_DIR
from scripts.bluestacks_popup_recognition import (
    MAX_VIP_POPUP_INPUTS, classify_popup_recovery, recognize_reset_popup,
    vip_popup_handled,
    NETWORK_DISCONNECT_IDENTITY, NETWORK_DISCONNECT_TARGET,
    recognize_network_disconnect, recognize_shared_interruption,
)
from scripts.startup_surface_recognition import (
    CASH_MALL,
    CASH_MALL_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_EXPECTED_SUCCESSOR,
    SCARLETT_MAX_INPUTS,
    SCARLETT_SAFE_BACK_ROI,
    SCARLETT_SAFE_BACK_TARGET_IDENTITY,
    SCARLETT_THREE_DAY_PACK,
    is_exact_startup_surface_recognition,
    recognize_startup_surface,
)

VIP_RESET_ACTION = "DISMISS_RESET_POPUP"
VIP_RESET_TARGET = "reset-popup-close"
VIP_RESET_SUCCESSOR = "HOME_BASE"
VIP_RESET_ACTION_KEY = "startup-recovery:vip-reset-close"
STARTUP_RECOVERY_STORE_PATH = ORCHESTRATOR_DIR / "startup-recovery-actions.sqlite3"

class StartupRecoveryError(RuntimeError):
    """An allowlisted startup recovery could not reach its exact successor."""


class NetworkDisconnectError(StartupRecoveryError):
    """A retained current interruption invalidates the route's input context."""

    def __init__(self, captured: CapturedNativeFrame, detail: dict[str, object]) -> None:
        self.captured = captured
        self.recognition = detail
        super().__init__("network_disconnect_requires_fresh_context:" + str(detail.get("reason")))


def require_network_clear(captured: CapturedNativeFrame) -> None:
    """Stop a route; never dismiss or recover from inside its pending input."""
    detail = recognize_shared_interruption(captured.frame)
    if detail.get("recognized") or detail.get("blocking_unknown_modal"):
        raise NetworkDisconnectError(captured, detail)


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
        try:
            root = require_no_untrusted_symlinks(Path(session)).resolve()
        except UnsafePathError as exc:
            raise ValueError("Startup recovery session reference contains a symlink") from exc
        value = {"popup_identity": self.popup_identity, "action_key": self.action_key,
                 "target_identity": self.target_identity, "target_roi": list(self.target_roi),
                 "input_count": self.input_count, "confirmed": self.confirmed, "reason": self.reason}
        for name, frame in (("source", self.source_frame), ("immediate_before", self.immediate_before),
                            ("settled", self.settled_frame)):
            relative = None
            if frame:
                try:
                    frame_path = require_no_untrusted_symlinks(frame.path).resolve()
                except UnsafePathError as exc:
                    raise ValueError("Startup recovery capture reference contains a symlink") from exc
                relative = frame_path.relative_to(root).as_posix()
            value[name + "_frame"] = relative
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
    network = recognize_shared_interruption(frame)
    if network.get("recognized") or network.get("blocking_unknown_modal"):
        return StartupRecoveryPlan(
            "recovery_required" if network.get("recognized") else "blocked",
            flow_id, str(network.get("popup_identity") or NETWORK_DISCONNECT_IDENTITY) if network.get("recognized") else None,
            "shared_network_recovery" if network.get("recognized") else None,
            False, str(network["reason"]), frame_sha256=frame_sha256,
            recognition=network,
        )
    startup_detail = recognize_startup_surface(frame, frame_bytes)
    if startup_detail.get("recognized"):
        return StartupRecoveryPlan(
            "recovery_required",
            flow_id,
            str(startup_detail["surface_identity"]),
            "shared_startup_surface_recovery",
            False,
            "exact known startup surface requires shared recovery",
            surface_kind=str(startup_detail.get("surface_kind") or "full_page"),
            frame_sha256=frame_sha256,
            recognition=dict(startup_detail),
        )
    if flow_id == ULTIMATE_FLOW_ID:
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
        captured.captured_monotonic > after.captured_monotonic
        and captured.path.resolve() != after.path.resolve()
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
    network = recognize_shared_interruption(captured.frame)
    if network.get("recognized") or network.get("blocking_unknown_modal"):
        popup = dict(popup, blocking_unknown_modal=True, network_interruption=network)
    identity = None
    if not popup.get("blocking_unknown_modal"):
        if surface.get("recognized"):
            if (not popup.get("recognized") and is_exact_startup_surface_recognition(surface)
                    and surface.get("frame_sha256") == captured.sha256):
                identity = surface["surface_identity"]
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
               SCARLETT_THREE_DAY_PACK: SCARLETT_SAFE_BACK_TARGET_IDENTITY,
               CASH_MALL: CASH_MALL_SAFE_BACK_TARGET_IDENTITY}
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


def _startup_surface_observation(
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
            str(detail["surface_identity"])
            if not successor
            else "RETAINED_STARTUP_SUCCESSOR"
        ),
        overlay_state="none" if not successor else "none_observed",
        target_identity=(
            str(detail["safe_exit_target_identity"]) if roi and not successor else None
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
            (("startup_safe_back", _roi_hash(captured.frame, roi)),)
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


def _startup_surface_request(
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
        semantic_action=SCARLETT_BACK_ACTION if observation.source_state == SCARLETT_THREE_DAY_PACK else "DISMISS_CASH_MALL",
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
        action_kind=SCARLETT_BACK_ACTION if observation.source_state == SCARLETT_THREE_DAY_PACK else "DISMISS_CASH_MALL",
        subject=observation.target_identity,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(str(observation.source_state), "full_page", "in_game_back"),
        semantic_postconditions=(SCARLETT_EXPECTED_SUCCESSOR,),
        runtime_session_id=session_id,
    )


def _recover_startup_surface(
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
    if not is_exact_startup_surface_recognition(initial_detail):
        raise StartupRecoveryError("exact startup surface recognition is not input-authoritative")
    if runtime.input_count >= runtime.max_inputs:
        raise StartupRecoveryError("startup recovery input budget is exhausted")
    scope = str(recovery_scope or "startup")
    # Navigation recovery is once per invocation, not a game-day resource effect.
    scope_digest = hashlib.sha256(json.dumps(
        (task_id, scope, str(runtime.session.resolve())), separators=(",", ":")
    ).encode()).hexdigest()[:16]
    identity = str(initial_detail["surface_identity"])
    target_identity = str(initial_detail["safe_exit_target_identity"])
    prefix = SCARLETT_BACK_ACTION_KEY if identity == SCARLETT_THREE_DAY_PACK else "startup-recovery:cash-mall-back"
    action_key = f"{prefix}:{scope_digest}"
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
            not is_exact_startup_surface_recognition(authorization_detail)
            or authorization_detail.get("surface_identity") != identity
            or authorization_detail.get("safe_exit_roi")
            != initial_detail.get("safe_exit_roi")
        ):
            raise StartupRecoveryError(
                "Scarlett stable identity or safe Back target changed before authorization"
            )
        authorized_observation = _startup_surface_observation(authorization_frame, authorization_detail)
        request = _startup_surface_request(task_id, owner, str(runtime.session), action_key, authorized_observation)
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
                not is_exact_startup_surface_recognition(detail)
                or detail.get("surface_identity") != identity
                or detail.get("safe_exit_roi")
                != authorization_detail.get("safe_exit_roi")
            ):
                raise StartupRecoveryError(
                    "Scarlett stable identity or safe Back target changed before dispatch"
                )
            holder.update(before=current, detail=detail)
            return _startup_surface_observation(current, detail)

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
                target_identity=target_identity,
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
            return (_startup_surface_observation(post, after, successor=disappeared),)

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
            "evidence_required_unknown_startup_successor"
            if confirmed and not successor_admissible
            else result.reason
        )
        evidence = StartupRecoveryResult(
            terminal_status, input_count, identity,
            "RETAINED_STARTUP_SUCCESSOR" if confirmed else None,
            authorized_observation.frame_sha256,
            post.sha256 if isinstance(post, CapturedNativeFrame) else None,
            action_key, terminal_reason, surface_kind="full_page",
            safe_exit_target_identity=target_identity,
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
        return _recover_startup_surface(
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


def recover_network_disconnect(
    runtime: LocalBlueStacksRuntime,
    *,
    state_manager: BotStateManager,
    action_store: SafetyStore,
    owner: str,
    checkpoint: Callable[[], None],
    observe_context: Callable[[CapturedNativeFrame], str],
    relaunch: Callable[[], dict[str, object]],
    restart: Callable[[], dict[str, object]] | None = None,
    scope_key: str,
    authorization: str,
    recognize_successor: Callable[[CapturedNativeFrame], bool] | None = None,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 1.0,
    utc_clock: Callable[[], float] = time.time,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Recover one exact interruption on the caller's owner, Core and SQLite.

    A known launcher acknowledges only the popup's exit, not connectivity.
    Relaunch remains the existing launcher-only lifecycle operation. An unknown
    post-input state retains Core's unresolved action and cannot authorize it.
    """
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError("current network recovery authorization is required")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 90
            or type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
            or not 0 < poll_seconds <= timeout_seconds):
        raise ValueError("network recovery needs a finite positive observation budget")
    checkpoint()
    before_count = runtime.input_count
    launches = 0
    stops = 0
    episode = state_manager.get_network_recovery(scope_key)
    mono_deadline = (
        monotonic_clock() + max(0.0, episode.deadline_at_utc - utc_clock())
        if episode is not None else None
    )
    source = runtime.capture("network-recovery-source")
    last = source
    immediate = None
    connected_contexts = {"HOME_BASE", "KNOWN_STARTUP_OVERLAY"}

    def connected(captured: CapturedNativeFrame, context: str) -> bool:
        if context in connected_contexts:
            return True
        if context != "UNKNOWN" or recognize_successor is None:
            return False
        _identity, surface, popup = _contextual_startup_details(captured)
        return bool(
            isinstance(surface, dict) and isinstance(popup, dict)
            and not surface.get("recognized") and not surface.get("commercial_looking")
            and not popup.get("recognized") and not popup.get("blocking_unknown_modal")
            and recognize_successor(captured)
        )

    def take(label: str) -> CapturedNativeFrame:
        nonlocal last
        checkpoint()
        captured = runtime.capture(label)
        if not _contextual_startup_frame_valid(captured, after=last):
            raise StartupRecoveryError("network recovery capture is stale or not intact")
        last = captured
        checkpoint()
        return captured

    def record(status: str, reason: str, **transport) -> None:
        nonlocal episode
        if episode is None:
            return
        checkpoint()
        updated = state_manager.update_network_recovery(
            episode.episode_id, expected_row_version=episode.row_version,
            status=status, last_frame_hash=last.sha256, reason=reason,
            now_utc_epoch=utc_clock(), **transport,
        )
        if updated is None:
            raise StartupRecoveryError("network recovery state fence rejected")
        episode = updated

    def network_action_pending() -> bool:
        if episode is None:
            return False
        action = action_store.get_action_by_key(f"network-recovery:{episode.episode_id}:confirm")
        return action is not None and action["final_status"] in {"prepared", "input_sent", "unresolved"}

    def finish(status: str, reason: str) -> dict[str, object]:
        count = runtime.input_count - before_count
        # Navigation UNKNOWN is deliberately not a global consequential-action
        # block. It still owns this episode and must never regain Confirm.
        unresolved = (
            action_store.has_action_block() or network_action_pending()
            or episode is not None and (
                episode.relaunch_attempts == 1
                and episode.relaunch_transport_status in {"attempted", "unknown"}
                or episode.restart_attempts == 1
                and episode.restart_transport_status in {"attempted", "unknown"}
            )
        )
        value = {
            "status": status, "reason": reason, "scope_key": scope_key,
            "authorization": authorization, "episode_id": episode.episode_id if episode else None,
            "episode": asdict(episode) if episode else None,
            "interruption_identity": episode.interruption_identity if episode else None,
            "episode_source_sha256": episode.source_frame_hash if episode else None,
            "input_count": count, "game_input_count": count,
            "system_launch_count": launches, "system_stop_count": stops,
            "accounting_verified": count in (0, 1) and launches in (0, 1) and stops in (0, 1),
            "unresolved_action": unresolved,
            "route_ready": status == "recovered" and not unresolved,
            "next_observe_at_utc": episode.next_observe_at_utc if episode else None,
            "source_frame": str(source.path), "source_sha256": source.sha256,
            "immediate_before_frame": str(immediate.path) if immediate else None,
            "immediate_before_sha256": immediate.sha256 if immediate else None,
            "after_frame": str(last.path), "after_sha256": last.sha256,
            "terminal_frame": str(last.path), "terminal_sha256": last.sha256,
        }
        path = runtime.session / f"network-recovery-{runtime.ordinal:04d}.json"
        value["result_path"] = str(path)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        return value

    def budget_open() -> bool:
        now = utc_clock()
        return (
            episode is not None and episode.updated_at_utc <= now < episode.deadline_at_utc
            and mono_deadline is not None and monotonic_clock() < mono_deadline
        )

    def launch_known_launcher() -> dict[str, object]:
        nonlocal episode, launches
        checkpoint()
        if episode is None or action_store.has_action_block() or network_action_pending():
            return finish("unresolved", "prior_action_requires_inspection")
        if episode.status not in {"OPEN", "DEFERRED"} or episode.relaunch_attempts:
            return finish("manual_required", "network_relaunch_budget_or_state_denied")
        action = action_store.get_action_by_key(f"network-recovery:{episode.episode_id}:confirm")
        if (episode.confirm_attempts != 1 or action is None
                or action["final_status"] != "confirmed"
                or observe_context(last) != "BLUESTACKS_LAUNCHER" or not budget_open()):
            record("MANUAL_REQUIRED", "network_relaunch_context_not_permitted")
            return finish("manual_required", "network_relaunch_context_not_permitted")
        if episode.confirm_transport_status == "attempted":
            # A crash may occur after Core's positive acknowledgement but before
            # this episode records the already-proven transport fact.
            record("OPEN", "network_confirm_core_confirmation_observed",
                   step="confirm", transport_status="returned")
        reserved = state_manager.reserve_network_recovery_step(
            episode.episode_id, "relaunch", expected_row_version=episode.row_version,
            now_utc_epoch=utc_clock(),
        )
        if reserved is None:
            record("MANUAL_REQUIRED", "network_relaunch_budget_or_state_denied")
            return finish("manual_required", "network_relaunch_budget_or_state_denied")
        episode = reserved
        try:
            startup = relaunch()
        except Exception as exc:
            attempted = getattr(exc, "startup_result", {})
            launches = attempted.get("system_launch_count", 0) if isinstance(attempted, dict) else 0
            record("MANUAL_REQUIRED", "network_relaunch_unresolved",
                   step="relaunch", transport_status="unknown")
            return finish("unresolved", "network_relaunch_unresolved")
        launches = startup.get("system_launch_count")
        if (type(launches) is not int or launches != 1 or startup.get("game_input_count") != 0
                or startup.get("transport_status") != "returned"):
            record("MANUAL_REQUIRED", "network_relaunch_accounting_invalid",
                   step="relaunch", transport_status="unknown")
            return finish("unresolved", "network_relaunch_accounting_invalid")
        record("OPEN" if budget_open() else "MANUAL_REQUIRED", "network_relaunch_transport_returned",
               step="relaunch", transport_status="returned")
        if not budget_open():
            return finish("manual_required", "network_recovery_deadline_exhausted")
        post = take("network-recovery-relaunch-after")
        after = recognize_shared_interruption(post.frame)
        if (not connected(post, observe_context(post))
                or after.get("recognized") or after.get("blocking_unknown_modal") or not budget_open()):
            record("MANUAL_REQUIRED", "network_connected_context_not_verified")
            return finish("manual_required", "network_connected_context_not_verified")
        record("RECOVERED", "network_relaunch_connected_context_verified")
        return finish("recovered", "network_relaunch_connected_context_verified")

    if not _contextual_startup_frame_valid(source):
        return finish("blocked", "network_source_not_intact")
    context = observe_context(source)
    detail = recognize_shared_interruption(source.frame)
    is_update = detail.get("recognized") and detail.get("popup_identity") == "UPDATE_RESTART_REQUIRED"
    if is_update:
        episode = state_manager.begin_network_recovery(
            scope_key=scope_key, source_frame_hash=source.sha256,
            now_utc_epoch=utc_clock(), timeout_seconds=timeout_seconds,
            interruption_identity="UPDATE_RESTART_REQUIRED",
        )
        mono_deadline = monotonic_clock() + max(0.0, episode.deadline_at_utc - utc_clock())
        if (action_store.has_action_block() or network_action_pending()
                or not action_store.lease_valid_for(owner, utc_clock())
                or state_manager._db.execute(
                    "SELECT 1 FROM actions WHERE state IN ('RESERVED','DISPATCHING','UNKNOWN') LIMIT 1"
                ).fetchone() is not None
                or episode.interruption_identity != "UPDATE_RESTART_REQUIRED"
                or episode.confirm_attempts or episode.relaunch_attempts):
            return finish("unresolved", "update_prior_action_or_episode_requires_inspection")
        if (restart is None or context != "UNKNOWN" or episode.status not in {"OPEN", "DEFERRED"}
                or episode.restart_attempts or not budget_open()):
            return finish("manual_required", "update_restart_budget_or_context_denied")
        immediate = take("update-restart-immediate-before")
        exact = recognize_shared_interruption(immediate.frame)
        if (not exact.get("recognized") or exact.get("popup_identity") != "UPDATE_RESTART_REQUIRED"
                or observe_context(immediate) != "UNKNOWN"):
            record("MANUAL_REQUIRED", "update_source_changed_before_restart")
            return finish("manual_required", "update_source_changed_before_restart")
        checkpoint()
        if action_store.has_action_block():
            return finish("unresolved", "update_prior_action_requires_inspection")
        reserved = state_manager.reserve_network_recovery_step(
            episode.episode_id, "restart", expected_row_version=episode.row_version,
            now_utc_epoch=utc_clock(),
        )
        if reserved is None:
            return finish("manual_required", "update_restart_budget_or_state_denied")
        episode = reserved
        try:
            startup = restart()
        except Exception as exc:
            startup = getattr(exc, "startup_result", {})
            if isinstance(startup, dict):
                stops = startup.get("system_stop_count", 0)
                launches = startup.get("system_launch_count", 0)
            record("MANUAL_REQUIRED", "update_restart_transport_unknown",
                   step="restart", transport_status="unknown")
            return finish("unresolved", "update_restart_transport_unknown")
        stops = startup.get("system_stop_count")
        launches = startup.get("system_launch_count")
        if (type(stops) is not int or stops != 1 or type(launches) is not int or launches != 1
                or startup.get("game_input_count") != 0 or runtime.input_count != before_count
                or startup.get("transport_status") != "returned" or not budget_open()):
            record("MANUAL_REQUIRED", "update_restart_accounting_or_deadline_invalid",
                   step="restart", transport_status="unknown")
            return finish("unresolved", "update_restart_accounting_or_deadline_invalid")
        record("OPEN", "update_restart_transport_returned", step="restart", transport_status="returned")
        post = take("update-restart-fresh-context")
        after = recognize_shared_interruption(post.frame)
        if (after.get("recognized") or after.get("blocking_unknown_modal")
                or not connected(post, observe_context(post)) or not budget_open()):
            record("MANUAL_REQUIRED", "update_restart_fresh_context_not_verified")
            return finish("manual_required", "update_restart_fresh_context_not_verified")
        record("RECOVERED", "update_restart_fresh_context_verified")
        return finish("recovered", "update_restart_fresh_context_verified")
    if not (detail.get("recognized") or detail.get("blocking_unknown_modal")) and connected(source, context):
        if action_store.has_action_block() or network_action_pending():
            return finish("unresolved", "prior_action_requires_inspection")
        if episode is not None and (
                episode.relaunch_transport_status in {"attempted", "unknown"}
                or episode.restart_transport_status in {"attempted", "unknown"}):
            return finish("unresolved", "network_relaunch_requires_inspection")
        if episode is not None and episode.status != "RECOVERED":
            record("RECOVERED", "fresh_connected_context_observed")
        return finish("recovered", "fresh_connected_context_observed")
    if (context == "BLUESTACKS_LAUNCHER" and episode is not None
            and not detail.get("recognized") and not detail.get("blocking_unknown_modal")):
        return launch_known_launcher()
    if not detail.get("recognized") or context != "UNKNOWN":
        if episode is not None and episode.status != "RECOVERED":
            record("MANUAL_REQUIRED", "unknown_or_manual_network_source")
        return finish("manual_required", "unknown_or_manual_network_source")
    if network_action_pending():
        if episode.status != "RECOVERED":
            record("MANUAL_REQUIRED", "prior_network_action_requires_inspection")
        return finish("unresolved", "prior_network_action_requires_inspection")
    episode = state_manager.begin_network_recovery(
        scope_key=scope_key, source_frame_hash=source.sha256,
        now_utc_epoch=utc_clock(), timeout_seconds=timeout_seconds,
    )
    if action_store.has_action_block():
        record("MANUAL_REQUIRED", "prior_action_requires_inspection")
        return finish("blocked", "prior_action_requires_inspection")
    if episode.status == "MANUAL_REQUIRED":
        return finish("manual_required", "network_episode_requires_inspection")
    now = utc_clock()
    if now >= episode.deadline_at_utc:
        record("MANUAL_REQUIRED", "network_recovery_deadline_exhausted")
        return finish("manual_required", "network_recovery_deadline_exhausted")
    if episode.next_observe_at_utc is not None and now < episode.next_observe_at_utc:
        return finish("deferred", "network_recovery_observation_not_due")
    if episode.confirm_attempts:
        record("MANUAL_REQUIRED", "network_confirm_already_attempted")
        return finish("manual_required", "network_confirm_already_attempted")

    task_id = "RUNTIME-NETWORK-DISCONNECT-RECOVERY"
    action_key = f"network-recovery:{episode.episode_id}:confirm"
    policy = CentralPolicy(supervised_tasks=frozenset({task_id}))
    holder: dict[str, object] = {"transport": "not_attempted", "context": "UNKNOWN", "connected": False}

    def observation(captured: CapturedNativeFrame, current: dict[str, object]) -> Observation:
        roi = current.get("target") if current.get("recognized") else None
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
            width=800, height=1280, valid_png=True, corrupt=False, black=False,
            source_state=NETWORK_DISCONNECT_IDENTITY, overlay_state="network_disconnect_10054",
            recognized=bool(current.get("recognized")),
            target_identity=NETWORK_DISCONNECT_TARGET if roi else None, target_roi=roi,
            control_class="POPUP_DISMISS_CONFIRM", consequence="navigate_zero_cost",
            cost_type="none", cost_amount=0, quantity=1,
            expected_postcondition="NETWORK_RECONNECT_ACKNOWLEDGED",
            critical_roi_hashes=(
                ("network_disconnect_dialog", _roi_hash(captured.frame, tuple(current["panel_bounds"]))),
                ("network_disconnect_confirm", _roi_hash(captured.frame, tuple(roi))),
            ) if roi else (),
            evidence_refs=(str(captured.path),), target_isolated=roi is not None,
            package_foreground=True, os_surface=False, hard_stop_detected=False,
        )

    authorization_frame = take("network-recovery-authorization-before")
    current = recognize_network_disconnect(authorization_frame.frame)
    if not current.get("recognized") or current.get("target") != detail.get("target"):
        record("MANUAL_REQUIRED", "network_source_changed_before_authorization")
        return finish("blocked", "network_source_changed_before_authorization")
    request = PolicyRequest(
        action_id=action_key, action_key=action_key, task_id=task_id,
        task_mode="supervised_validation", semantic_action="RECOVER_NETWORK_DISCONNECT",
        expected_runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID,
        observation=observation(authorization_frame, current),
        monotonic_now=monotonic_clock(), observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0, lease_owner=owner, lease_valid=True,
        unresolved_action=False, duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY, action_kind="RECOVER_NETWORK_DISCONNECT",
        subject=NETWORK_DISCONNECT_TARGET, resource_or_currency="none", maximum_cost=0,
        free_only=True, semantic_preconditions=(NETWORK_DISCONNECT_IDENTITY,),
        semantic_postconditions=("NETWORK_RECONNECT_ACKNOWLEDGED",),
        runtime_session_id=str(runtime.session),
    )
    decision = policy.evaluate(request)
    if not decision.authorized:
        record("MANUAL_REQUIRED", decision.reason_code)
        return finish("blocked", decision.reason_code)
    checkpoint()
    reserved = state_manager.reserve_network_recovery_step(
        episode.episode_id, "confirm", expected_row_version=episode.row_version,
        now_utc_epoch=utc_clock(),
    )
    if reserved is None:
        return finish("blocked", "network_confirm_budget_or_state_denied")
    episode = reserved
    mono_deadline = monotonic_clock() + max(0.0, episode.deadline_at_utc - utc_clock())

    def recapture() -> Observation:
        nonlocal immediate
        immediate = take("network-recovery-immediate-before")
        latest = recognize_network_disconnect(immediate.frame)
        if not latest.get("recognized") or latest.get("target") != current.get("target"):
            raise ValueError("network source changed before Confirm")
        return observation(immediate, latest)

    def transport(_intent) -> TransportResult:
        checkpoint()
        if not budget_open():
            raise StartupRecoveryError("network recovery original deadline exhausted")
        if immediate is None or runtime.input_count != before_count:
            raise StartupRecoveryError("network Confirm input budget denied")
        holder["transport"] = "attempted"
        runtime.tap(
            immediate, target_identity=NETWORK_DISCONNECT_TARGET,
            target_roi=tuple(current["target"]), action_key=action_key,
            action_class="network_reconnect", consequential=False,
        )
        holder["transport"] = "returned"
        return TransportResult(True, "NETWORK_CONFIRM_DISPATCHED")

    def post_observe() -> tuple[Observation, ...]:
        polls = max(1, math.ceil(timeout_seconds / poll_seconds))
        for index in range(polls):
            checkpoint()
            sleep(min(poll_seconds, max(0.0, mono_deadline - monotonic_clock())))
            post = take(f"network-recovery-after-{index:03d}")
            after = recognize_shared_interruption(post.frame)
            observed = observe_context(post)
            clear = not (after.get("recognized") or after.get("blocking_unknown_modal"))
            route_connected = clear and connected(post, observed)
            acknowledged = clear and (route_connected or observed == "BLUESTACKS_LAUNCHER") and budget_open()
            holder["context"] = observed
            holder["connected"] = route_connected
            # Removing the popup can first expose a loading frame over the
            # interrupted route. Observe only; never resend Confirm or infer
            # readiness from dismissal. Manual/other-modal states stop now.
            if acknowledged or observed == "MANUAL_REQUIRED" or after.get("blocking_unknown_modal") or (
                index == polls - 1
                or utc_clock() >= episode.deadline_at_utc or monotonic_clock() >= mono_deadline
            ):
                return (Observation(
                    frame_sha256=post.sha256,
                    capture_completed_monotonic=post.captured_monotonic,
                    runtime_profile_id=NATIVE_RUNTIME_PROFILE_ID, width=800, height=1280,
                    valid_png=True, corrupt=False, black=False, recognized=acknowledged,
                    target_identity=None, target_roi=None,
                    source_state="NETWORK_RECONNECT_ACKNOWLEDGED" if acknowledged else "UNKNOWN",
                    overlay_state="none_observed" if clear else "network_disconnect_10054",
                    expected_postcondition="NETWORK_RECONNECT_ACKNOWLEDGED",
                    evidence_refs=(str(post.path),),
                ),)
        return ()

    previous_checkpoint = runtime.checkpoint
    def deadline_checkpoint():
        checkpoint()
        if not budget_open():
            raise StartupRecoveryError("network recovery original deadline exhausted")
    runtime.checkpoint = deadline_checkpoint
    try:
        executed = SafeActionExecutor(
            action_store, policy, owner, monotonic_clock, transport, recapture,
            post_observe,
            lambda _intent, observed: observed.recognized
            and observed.source_state == "NETWORK_RECONNECT_ACKNOWLEDGED",
            wall_clock=utc_clock, max_pre_dispatch_attempts=1,
        ).execute(request)
    finally:
        runtime.checkpoint = previous_checkpoint
    transport_state = holder["transport"]
    if transport_state != "not_attempted":
        record(
            "OPEN" if budget_open() else "MANUAL_REQUIRED", "network_confirm_transport_observed", step="confirm",
            transport_status="returned" if transport_state == "returned" else "unknown",
        )
    if runtime.input_count > before_count:
        runtime.reconcile(
            action_key, "confirmed" if executed.status is ActionStatus.CONFIRMED else "unresolved",
            last, executed.reason,
        )
    if executed.status is not ActionStatus.CONFIRMED:
        record("MANUAL_REQUIRED", "network_confirm_outcome_requires_inspection")
        return finish("unresolved" if action_store.has_action_block() or network_action_pending() else "blocked", executed.reason)
    if holder["connected"]:
        record("RECOVERED", "network_connected_context_verified")
        return finish("recovered", "network_connected_context_verified")
    return launch_known_launcher()


def inspect_network_disconnect_context(
    runtime: LocalBlueStacksRuntime, *, state_manager: BotStateManager,
    action_store: SafetyStore, owner: str, checkpoint: Callable[[], None],
    observe_context: Callable[[CapturedNativeFrame], str], scope_key: str,
    authorization: str, utc_clock: Callable[[], float] = time.time,
) -> dict[str, object]:
    """Explicit zero-input inspection, never acceptance of the original run.

    Only a returned, zero-cost Confirm with no relaunch can be reconciled.
    Its original deadline, counters, source and raw receipt remain unchanged.
    Ordinary recovery never calls this path or silently resolves UNKNOWN.
    """
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError("current network inspection authorization is required")
    if runtime.input_count != 0 or runtime.max_inputs != 0:
        raise ValueError("network context inspection requires a zero-input runtime")
    checkpoint()
    episode = state_manager.get_network_recovery(scope_key)
    result: dict[str, object] = {
        "status": "blocked", "reason": "network_episode_not_inspectable",
        "authorization": authorization, "input_count": 0, "game_input_count": 0,
        "system_launch_count": 0, "route_ready": False,
        "original_canary_accepted": False, "fresh_invocation_required": True,
        "scope_key": scope_key,
    }
    path = runtime.session / "network-context-inspection.json"
    result["result_path"] = str(path)

    def finish(reason: str) -> dict[str, object]:
        result["reason"] = reason
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
        return result

    if (episode is None or episode.status != "MANUAL_REQUIRED"
            or episode.confirm_attempts != 1 or episode.confirm_transport_status != "returned"
            or episode.relaunch_attempts != 0 or episode.relaunch_transport_status != "not_attempted"):
        return finish("network_episode_not_inspectable")
    result.update({
        "episode_id": episode.episode_id, "original_deadline_at_utc": episode.deadline_at_utc,
        "original_source_sha256": episode.source_frame_hash,
    })
    if action_store.has_action_block() or not action_store.lease_valid_for(owner, utc_clock()):
        return finish("prior_effect_or_owner_requires_inspection")
    key = f"network-recovery:{episode.episode_id}:confirm"
    row = action_store.get_action_by_key(key)
    if row is None:
        return finish("network_confirm_record_unavailable")
    try:
        transport = json.loads(row["transport_result_json"] or "{}")
    except (TypeError, ValueError):
        return finish("network_confirm_transport_not_verified")
    if (row["final_status"] not in {"unresolved", "confirmed"}
            or row["task_id"] != "RUNTIME-NETWORK-DISCONNECT-RECOVERY"
            or row["semantic_action"] != "RECOVER_NETWORK_DISCONNECT"
            or row["source_state"] != NETWORK_DISCONNECT_IDENTITY
            or row["target_identity"] != NETWORK_DISCONNECT_TARGET
            or row["expected_postcondition"] != "NETWORK_RECONNECT_ACKNOWLEDGED"
            or row["runtime_profile_id"] != NATIVE_RUNTIME_PROFILE_ID
            or row["consequential"] != 0 or row["cost_type"] != "none"
            or row["cost_amount"] != 0 or row["quantity"] != 1
            or not isinstance(transport, dict) or transport.get("dispatched") is not True
            or transport.get("transport_code") != "NETWORK_CONFIRM_DISPATCHED"):
        return finish("network_confirm_not_inspectable")
    captures = []
    for ordinal in range(2):
        checkpoint()
        captured = runtime.capture(f"network-context-inspection-{ordinal}")
        captures.append(captured)
        result["terminal_frame"] = str(captured.path)
        result["terminal_sha256"] = captured.sha256
        if not _contextual_startup_frame_valid(captured, after=captures[-2] if ordinal else None):
            return finish("network_inspection_capture_not_fresh")
        detail = recognize_shared_interruption(captured.frame)
        if (detail.get("recognized") or detail.get("blocking_unknown_modal")
                or observe_context(captured) != "HOME_BASE"
                or not _contextual_startup_frame_valid(captured, after=captures[-2] if ordinal else None)):
            return finish("network_inspection_requires_fresh_home")
        checkpoint()
    now = utc_clock()
    if (action_store.has_action_block() or not action_store.lease_valid_for(owner, now)
            or not _contextual_startup_frame_valid(captures[-1], after=captures[-2])):
        return finish("network_inspection_context_owner_or_effect_changed")
    evidence = {
        "confirmed": True, "operator_inspection": "network_home_context",
        "episode_id": episode.episode_id, "authorization": authorization,
        "original_canary_accepted": False,
        "after_original_deadline": now >= episode.deadline_at_utc,
        "input_count": 0, "system_launch_count": 0,
        "frames": [{"path": str(c.path), "sha256": c.sha256} for c in captures],
    }
    # Core's existing reconciliation retains the earlier transition in audit;
    # the immutable native receipt is not edited or reclassified as accepted.
    if row["final_status"] == "unresolved":
        action_store.reconcile_confirmed(row["action_id"], now, evidence)
    action_store.audit(row["task_id"], "operator_network_context_inspection", now,
                       evidence, row["action_id"])
    updated = state_manager.update_network_recovery(
        episode.episode_id, expected_row_version=episode.row_version,
        status="RECOVERED", last_frame_hash=captures[-1].sha256,
        reason="operator_inspected_fresh_home_not_original_run_acceptance",
        now_utc_epoch=now,
    )
    if updated is None:
        return finish("network_inspection_state_fence_rejected")
    result["status"] = "inspected_connected_context"
    result["after_original_deadline"] = evidence["after_original_deadline"]
    return finish("operator_inspected_fresh_home_not_original_run_acceptance")
