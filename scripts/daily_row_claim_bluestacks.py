"""Bounded Home -> Quest -> Daily reconnaissance for local BlueStacks.

This module owns only two receipt-authorized navigation taps.  It never claims a
row, spends resources, performs recovery, or talks to ADB directly.  Runtime
capture and transport are supplied by ``LocalBlueStacksRuntime``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, NativeBox


NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
EXPECTED_PACKAGE = "com.global.ztmslg"
HOME_SEARCH_ROI: NativeBox = (0, 1000, NATIVE_WIDTH, NATIVE_HEIGHT)
QUEST_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
DAILY_TAB_SEARCH_ROI: NativeBox = (0, 35, NATIVE_WIDTH, 230)
FULL_FRAME_SEARCH_ROI: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

HOME_STATE = "HOME"
QUEST_STATE = "QUEST"
DAILY_SELECTED_STATE = "DAILY_SELECTED"
UNKNOWN_STATE = "UNKNOWN"

HOME_QUEST_IDENTITY = "home-quest-entry"
QUEST_DAILY_IDENTITY = "quest-daily-tab"
NAVIGATION_ACTION_CLASS = "navigation"
NAVIGATION_CONSEQUENCE_CLASS = "navigation_only"

_HOME_WORDS = frozenset({"quest", "world", "hero", "bag", "mail", "alliance", "more"})
_OVERLAY_MARKERS = frozenset(
    {"loading", "retry", "cancel", "confirm", "purchase", "payment", "popup", "captcha"}
)


class DailyRowClaimRecognitionError(RuntimeError):
    """Raised when a bounded route cannot prove a required recognition."""


class RuntimeLike(Protocol):
    execute: bool
    session: Any

    def capture(self, label: str) -> CapturedNativeFrame: ...

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None: ...


class SessionLike(Protocol):
    input_count: int
    actions: list[dict[str, Any]]
    terminal_status: str | None
    blocker: str | None
    next_action: str | None
    session_directory: Any

    def observe(
        self,
        capture: Callable[[str], CapturedNativeFrame],
        *,
        label: str,
    ) -> CapturedNativeFrame: ...

    def run_action(self, **kwargs: Any) -> Any: ...


class _NativeTapDispatch:
    """Keep receipt reservation ownership with the native runtime tap."""

    def __init__(self, callback: Callable[[CapturedNativeFrame], None]) -> None:
        self._callback = callback

    def _authorize_dispatch(self) -> None:
        # DevelopmentSession uses this marker to avoid a second generic
        # delegated reservation.  LocalBlueStacksRuntime.tap performs the
        # actual current-frame and receipt-bound authorization.
        return None

    def dispatch(self, source: CapturedNativeFrame) -> None:
        self._callback(source)


@dataclass(frozen=True)
class OCRToken:
    text: str
    roi: NativeBox
    confidence: float | None = None


@dataclass(frozen=True)
class FrameRecognition:
    state: str
    recognized: bool
    target_identity: str | None = None
    target_roi: NativeBox | None = None
    ocr_text: str = ""
    visual_evidence: Mapping[str, Any] | None = None
    reason: str | None = None
    tokens: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _clamp_roi(roi: Sequence[int]) -> NativeBox | None:
    if len(roi) != 4:
        return None
    x0, y0, x1, y1 = (int(value) for value in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(NATIVE_WIDTH, x1), min(NATIVE_HEIGHT, y1)
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        return None
    return (x0, y0, x1, y1)


def _default_ocr(image: np.ndarray) -> Mapping[str, Sequence[object]]:
    import pytesseract

    return pytesseract.image_to_data(
        image,
        config="--psm 11",
        output_type=pytesseract.Output.DICT,
    )


def _ocr_tokens(
    frame: np.ndarray,
    roi: NativeBox,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[OCRToken, ...]:
    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return ()
    scale = 2.0
    enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    data = ocr(enlarged)
    texts = data.get("text", ())
    lefts = data.get("left", ())
    tops = data.get("top", ())
    widths = data.get("width", ())
    heights = data.get("height", ())
    confidences = data.get("conf", ())
    count = min(len(texts), len(lefts), len(tops), len(widths), len(heights))
    tokens: list[OCRToken] = []
    for index in range(count):
        text = _normalize_text(texts[index])
        if not text:
            continue
        try:
            left = round(float(lefts[index]) / scale) + x0
            top = round(float(tops[index]) / scale) + y0
            width = round(float(widths[index]) / scale)
            height = round(float(heights[index]) / scale)
            confidence = (
                float(confidences[index])
                if index < len(confidences) and str(confidences[index]).strip()
                else None
            )
        except (TypeError, ValueError):
            continue
        token_roi = _clamp_roi((left, top, left + width, top + height))
        if token_roi is None:
            continue
        tokens.append(OCRToken(text=text, roi=token_roi, confidence=confidence))
    return tuple(tokens)


def _token_rows(tokens: Sequence[OCRToken]) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "text": token.text,
            "roi": token.roi,
            "confidence": token.confidence,
        }
        for token in tokens
    )


def _frame_shape_ok(frame: np.ndarray) -> bool:
    return frame.shape == (NATIVE_HEIGHT, NATIVE_WIDTH, 3)


def _visual_button_evidence(frame: np.ndarray, target: NativeBox) -> dict[str, Any]:
    x0, y0, x1, y1 = target
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return {"recognized": False, "edge_ratio": 0.0, "accent_ratio": 0.0}
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    accent = cv2.inRange(hsv, (0, 45, 70), (179, 255, 255))
    edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
    accent_ratio = float(np.count_nonzero(accent)) / float(accent.size)
    # Text plus a bounded button/icon patch is the minimum independent
    # structural evidence.  The target is always derived from this frame's
    # OCR box; these are not retained coordinates.
    recognized = bool(edge_ratio >= 0.004 or accent_ratio >= 0.025)
    return {
        "recognized": recognized,
        "edge_ratio": round(edge_ratio, 6),
        "accent_ratio": round(accent_ratio, 6),
    }


def _bind_text_target(
    frame: np.ndarray,
    token: OCRToken,
    *,
    identity: str,
    min_y: int,
    max_y: int,
) -> tuple[NativeBox | None, dict[str, Any]]:
    tx0, ty0, tx1, ty1 = token.roi
    center_y = (ty0 + ty1) // 2
    if not (min_y <= center_y <= max_y):
        return None, {"recognized": False, "reason": "token_outside_structural_region"}
    padding_x = max(18, min(80, (tx1 - tx0) * 2))
    padding_y = max(16, min(48, (ty1 - ty0) * 2))
    target = _clamp_roi((tx0 - padding_x, ty0 - padding_y, tx1 + padding_x, ty1 + padding_y))
    if target is None:
        return None, {"recognized": False, "reason": "target_out_of_bounds"}
    visual = _visual_button_evidence(frame, target)
    details = {
        "recognized": bool(visual["recognized"]),
        "target_identity": identity,
        "target_roi": target,
        "ocr_roi": token.roi,
        "visual": visual,
    }
    return (target if visual["recognized"] else None), details


def _contains_overlay_marker(tokens: Sequence[OCRToken]) -> bool:
    words = {word for token in tokens for word in token.text.split()}
    return bool(words & _OVERLAY_MARKERS)


def _full_frame_overlay_markers(
    frame: np.ndarray,
    ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]],
) -> tuple[str, ...]:
    """Reject explicit modal markers found anywhere in the current frame."""

    tokens = _ocr_tokens(frame, FULL_FRAME_SEARCH_ROI, ocr)
    words = {word for token in tokens for word in token.text.split()}
    return tuple(sorted(words & _OVERLAY_MARKERS))


def _tab_visual_score(frame: np.ndarray, token: OCRToken) -> float:
    x0, y0, x1, y1 = token.roi
    roi = _clamp_roi((x0 - 20, y0 - 12, x1 + 20, y1 + 28))
    if roi is None:
        return 0.0
    rx0, ry0, rx1, ry1 = roi
    patch = frame[ry0:ry1, rx0:rx1]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    saturation = float(np.mean(hsv[:, :, 1])) / 255.0
    value = float(np.mean(hsv[:, :, 2])) / 255.0
    edges = cv2.Canny(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 60, 160)
    edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
    return round(0.55 * saturation + 0.30 * value + 0.15 * min(edge_ratio * 8.0, 1.0), 6)


class DailyRowClaimRecognizer:
    """Recognize only the three states needed by the frozen route."""

    def __init__(
        self,
        *,
        ocr: Callable[[np.ndarray], Mapping[str, Sequence[object]]] | None = None,
    ) -> None:
        self._ocr = ocr or _default_ocr

    def recognize_home(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(HOME_STATE, False, reason="profile_dimensions_mismatch")
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, HOME_SEARCH_ROI, self._ocr)
        quest = next((token for token in tokens if token.text == "quest"), None)
        target = None
        visual: dict[str, Any] = {
            "bottom_navigation": len(tokens) >= 2,
            "known_navigation_labels": sorted(
                {word for token in tokens for word in token.text.split()} & _HOME_WORDS
            ),
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        if quest is not None:
            target, binding = _bind_text_target(
                frame,
                quest,
                identity=HOME_QUEST_IDENTITY,
                min_y=1040,
                max_y=1270,
            )
            visual["quest_binding"] = binding
        recognized = bool(
            quest is not None
            and visual["bottom_navigation"]
            and target is not None
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else "home-quest-target-not-proven"
        )
        return FrameRecognition(
            HOME_STATE if recognized else UNKNOWN_STATE,
            recognized,
            HOME_QUEST_IDENTITY if recognized else None,
            target if recognized else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
        )

    def recognize_quest(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(QUEST_STATE, False, reason="profile_dimensions_mismatch")
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, QUEST_TAB_SEARCH_ROI, self._ocr)
        quest_header = next(
            (token for token in tokens if "quest" in token.text and token.roi[1] < 90),
            None,
        )
        daily = next((token for token in tokens if token.text == "daily"), None)
        target = None
        visual: dict[str, Any] = {
            "quest_header": quest_header.roi if quest_header else None,
            "tab_structure": bool(daily and 35 <= (daily.roi[1] + daily.roi[3]) // 2 <= 220),
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        if daily is not None:
            target, binding = _bind_text_target(
                frame,
                daily,
                identity=QUEST_DAILY_IDENTITY,
                min_y=35,
                max_y=220,
            )
            visual["daily_binding"] = binding
        recognized = bool(
            quest_header is not None
            and daily is not None
            and visual["tab_structure"]
            and target is not None
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else "quest-daily-target-not-proven"
        )
        return FrameRecognition(
            QUEST_STATE if recognized else UNKNOWN_STATE,
            recognized,
            QUEST_DAILY_IDENTITY if recognized else None,
            target if recognized else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
        )

    def recognize_daily_selected(self, frame: np.ndarray) -> FrameRecognition:
        if not _frame_shape_ok(frame):
            return FrameRecognition(DAILY_SELECTED_STATE, False, reason="profile_dimensions_mismatch")
        overlay_markers = _full_frame_overlay_markers(frame, self._ocr)
        tokens = _ocr_tokens(frame, DAILY_TAB_SEARCH_ROI, self._ocr)
        daily = next((token for token in tokens if token.text == "daily"), None)
        main = next(
            (token for token in tokens if token.text in {"main", "main quest", "quest"}),
            None,
        )
        daily_score = _tab_visual_score(frame, daily) if daily else 0.0
        main_score = _tab_visual_score(frame, main) if main else 0.0
        visual: dict[str, Any] = {
            "daily_tab_score": daily_score,
            "main_tab_score": main_score,
            "selected_margin": round(daily_score - main_score, 6),
            "main_tab_present": main is not None,
            "full_frame_overlay": {
                "recognized": bool(overlay_markers),
                "markers": overlay_markers,
            },
        }
        recognized = bool(
            daily is not None
            and main is not None
            and daily_score >= 0.12
            and daily_score >= main_score + 0.015
            and not _contains_overlay_marker(tokens)
            and not overlay_markers
        )
        reason = (
            "full-frame overlay/modal detected"
            if overlay_markers
            else None
            if recognized
            else "selected-daily-semantics-not-proven"
        )
        return FrameRecognition(
            DAILY_SELECTED_STATE if recognized else UNKNOWN_STATE,
            recognized,
            "daily-quest-selected" if recognized else None,
            daily.roi if recognized and daily else None,
            " ".join(token.text for token in tokens),
            visual,
            reason,
            _token_rows(tokens),
        )


def _ensure_fresh(frame: CapturedNativeFrame, runtime: RuntimeLike) -> None:
    age = time.monotonic() - frame.captured_monotonic
    maximum = float(getattr(runtime, "frame_max_age_seconds", 30.0))
    if age < 0 or age > maximum:
        raise DailyRowClaimRecognitionError("dispatch source frame is stale")


def _ensure_runtime_ready(runtime: RuntimeLike) -> None:
    device_state = getattr(runtime, "measure_device_state", None)
    if callable(device_state) and device_state() != "device":
        raise DailyRowClaimRecognitionError("local BlueStacks device state is not ready")
    foreground = getattr(runtime, "measure_foreground_package", None)
    if callable(foreground) and foreground() != EXPECTED_PACKAGE:
        raise DailyRowClaimRecognitionError("Puzzles & Survival is not the foreground package")


def _require_recognition(
    recognition: FrameRecognition,
    *,
    state: str,
    target_identity: str | None = None,
) -> None:
    if not recognition.recognized or recognition.state != state:
        raise DailyRowClaimRecognitionError(recognition.reason or f"{state.lower()} recognition failed")
    if target_identity is not None and recognition.target_identity != target_identity:
        raise DailyRowClaimRecognitionError("recognized target identity is not manifest-bound")
    if target_identity is not None and recognition.target_roi is None:
        raise DailyRowClaimRecognitionError("recognized target geometry is missing")


def _frame_ref(frame: CapturedNativeFrame, session_directory: Any) -> dict[str, Any]:
    path = frame.path
    try:
        relative = path.resolve().relative_to(session_directory.resolve())
        path_value = str(relative).replace("\\", "/")
    except (AttributeError, OSError, ValueError):
        path_value = str(path)
    return {
        "path": path_value,
        "sha256": frame.sha256,
        "captured_monotonic": frame.captured_monotonic,
    }


def _failure(
    session: SessionLike,
    *,
    reason: str,
    frames: Mapping[str, CapturedNativeFrame],
    recognitions: Mapping[str, FrameRecognition],
) -> dict[str, Any]:
    session.terminal_status = "evidence_required"
    session.blocker = reason
    session.next_action = "retain evidence_required and repair recognition or transport"
    return {
        "status": "evidence_required",
        "reason": reason,
        "input_count": int(session.input_count),
        "resource_affecting_inputs": 0,
        "combat_confirmations": 0,
        "frames": {
            name: _frame_ref(frame, session.session_directory)
            for name, frame in frames.items()
        },
        "recognitions": {
            name: recognition.as_dict() for name, recognition in recognitions.items()
        },
        "actions": [dict(row) for row in session.actions],
    }


def run_daily_row_reconnaissance(
    runtime: RuntimeLike,
    session: SessionLike,
    *,
    recognizer: DailyRowClaimRecognizer | Any | None = None,
) -> dict[str, Any]:
    """Run exactly Home -> Quest -> selected Daily, without recovery."""

    if not bool(getattr(runtime, "execute", False)):
        return _failure(
            session,
            reason="runtime execution is required for reconnaissance",
            frames={},
            recognitions={},
        )
    recognizer = recognizer or DailyRowClaimRecognizer()
    frames: dict[str, CapturedNativeFrame] = {}
    recognitions: dict[str, FrameRecognition] = {}

    try:
        def capture(label: str) -> CapturedNativeFrame:
            captured = runtime.capture(label)
            frame_names = {
                "home-source": "source",
                "home-quest-entry-immediate-before": "home_immediate_before",
                "home-quest-entry-immediate-post": "quest_successor",
                "quest-daily-tab-immediate-before": "daily_immediate_before",
                "quest-daily-tab-immediate-post": "daily_terminal",
            }
            name = frame_names.get(label)
            if name is not None:
                frames[name] = captured
            return captured

        source = session.observe(capture, label="home-source")
        frames["source"] = source
        source_recognition = recognizer.recognize_home(source.frame)
        recognitions["source"] = source_recognition
        _require_recognition(
            source_recognition,
            state=HOME_STATE,
            target_identity=HOME_QUEST_IDENTITY,
        )

        first_post_recognition: FrameRecognition | None = None

        def dispatch_quest(before: CapturedNativeFrame) -> None:
            rebound = recognizer.recognize_home(before.frame)
            recognitions["home_immediate_before"] = rebound
            _require_recognition(
                rebound,
                state=HOME_STATE,
                target_identity=HOME_QUEST_IDENTITY,
            )
            _ensure_fresh(before, runtime)
            _ensure_runtime_ready(runtime)
            runtime.tap(
                before,
                target_identity=HOME_QUEST_IDENTITY,
                target_roi=rebound.target_roi,  # type: ignore[arg-type]
                action_key=HOME_QUEST_IDENTITY,
            )

        def recognize_quest_successor(after: CapturedNativeFrame) -> str:
            nonlocal first_post_recognition
            first_post_recognition = recognizer.recognize_quest(after.frame)
            recognitions["quest_successor"] = first_post_recognition
            return first_post_recognition.state if first_post_recognition.recognized else UNKNOWN_STATE

        quest_dispatch = _NativeTapDispatch(dispatch_quest)
        first_action = session.run_action(
            action_class=NAVIGATION_ACTION_CLASS,
            label=HOME_QUEST_IDENTITY,
            capture=capture,
            dispatch=quest_dispatch.dispatch,
            recognize=recognize_quest_successor,
            consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
        )
        if (
            first_action.status != "completed"
            or first_post_recognition is None
            or not first_post_recognition.recognized
        ):
            return _failure(
                session,
                reason="Quest successor was not positively recognized",
                frames=frames,
                recognitions=recognitions,
            )

        second_post_recognition: FrameRecognition | None = None

        def dispatch_daily(before: CapturedNativeFrame) -> None:
            rebound = recognizer.recognize_quest(before.frame)
            recognitions["daily_immediate_before"] = rebound
            _require_recognition(
                rebound,
                state=QUEST_STATE,
                target_identity=QUEST_DAILY_IDENTITY,
            )
            _ensure_fresh(before, runtime)
            _ensure_runtime_ready(runtime)
            runtime.tap(
                before,
                target_identity=QUEST_DAILY_IDENTITY,
                target_roi=rebound.target_roi,  # type: ignore[arg-type]
                action_key=QUEST_DAILY_IDENTITY,
            )

        def recognize_daily_successor(after: CapturedNativeFrame) -> str:
            nonlocal second_post_recognition
            second_post_recognition = recognizer.recognize_daily_selected(after.frame)
            recognitions["daily_terminal"] = second_post_recognition
            return second_post_recognition.state if second_post_recognition.recognized else UNKNOWN_STATE

        daily_dispatch = _NativeTapDispatch(dispatch_daily)
        second_action = session.run_action(
            action_class=NAVIGATION_ACTION_CLASS,
            label=QUEST_DAILY_IDENTITY,
            capture=capture,
            dispatch=daily_dispatch.dispatch,
            recognize=recognize_daily_successor,
            consequence_class=NAVIGATION_CONSEQUENCE_CLASS,
        )
        if (
            second_action.status != "completed"
            or second_post_recognition is None
            or not second_post_recognition.recognized
        ):
            return _failure(
                session,
                reason="selected Daily terminal was not positively recognized",
                frames=frames,
                recognitions=recognitions,
            )

        session.terminal_status = "observed"
        return {
            "status": "observed",
            "reason": "selected Daily positively recognized",
            "input_count": int(session.input_count),
            "resource_affecting_inputs": 0,
            "combat_confirmations": 0,
            "frames": {
                name: _frame_ref(frame, session.session_directory)
                for name, frame in frames.items()
            },
            "recognitions": {
                name: recognition.as_dict() for name, recognition in recognitions.items()
            },
            "actions": [dict(row) for row in session.actions],
        }
    except BaseException as exc:
        return _failure(
            session,
            reason=f"{type(exc).__name__}: {exc}",
            frames=frames,
            recognitions=recognitions,
        )

