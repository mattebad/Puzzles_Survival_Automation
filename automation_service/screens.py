"""Canonical immutable capture and screen-perception boundaries.

The router intentionally owns recognition order and caching.  Route modules may provide
small template/geometry/OCR functions, but may not turn a stale frame or a full-frame
hash into an input authority.  A target is authoritative only when its semantic identity
and stable ROI are rebound on the current capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import inspect
import math
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

class _RecognitionTimeout(TimeoutError):
    """A perception callback exceeded its hard execution deadline."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


Box = tuple[int, int, int, int]


class ScreenId(str, Enum):
    UNKNOWN = "UNKNOWN"
    HOME = "HOME"
    HOME_ATLAS = "HOME_ATLAS"
    DAILY = "DAILY"
    VIP_RESET = "VIP_RESET"
    EXIT_DIALOG = "EXIT_DIALOG"
    INFORMATION_MODAL = "INFORMATION_MODAL"


class OverlayId(str, Enum):
    VIP_RESET = "VIP_RESET"
    EXIT_CONFIRMATION = "EXIT_CONFIRMATION"
    INFORMATION_MODAL = "INFORMATION_MODAL"
    UNKNOWN = "UNKNOWN"


class ScreenRecognitionError(ValueError):
    """Fail-closed perception or capture-contract error."""


@dataclass(frozen=True)
class CaptureCycle:
    """One immutable capture event shared by all recognition stages.

    ``frame_hash`` is provenance and a cache key only.  It is deliberately not used as
    proof that a target has remained at the same location; that proof comes from a
    current :class:`TargetBinding` stable ROI and semantic identity.
    """

    capture_id: str
    frame_hash: str
    payload: Any = None
    captured_monotonic: float = 0.0
    capture_ordinal: int = 0
    width: int | None = None
    height: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, str) or not self.capture_id.strip():
            raise ScreenRecognitionError("capture identity is required")
        if not isinstance(self.frame_hash, str) or not self.frame_hash.strip():
            raise ScreenRecognitionError("frame hash is required")
        if not math.isfinite(float(self.captured_monotonic)):
            raise ScreenRecognitionError("capture time must be finite")
        if type(self.capture_ordinal) is not int or self.capture_ordinal < 0:
            raise ScreenRecognitionError("capture ordinal must be non-negative")
        if self.width is not None and (type(self.width) is not int or self.width <= 0):
            raise ScreenRecognitionError("capture width must be positive")
        if self.height is not None and (type(self.height) is not int or self.height <= 0):
            raise ScreenRecognitionError("capture height must be positive")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def frame_sha256(self) -> str:
        """Compatibility spelling used by existing native-frame records."""

        return self.frame_hash

    @property
    def identity(self) -> tuple[str, str]:
        """The only identity used by the router recognition cache."""

        return self.capture_id, self.frame_hash


@dataclass(frozen=True)
class TargetBinding:
    """A current semantic target and its stable, dispatchable geometry."""

    target_identity: str
    roi: Box
    semantic_identity: str | None = None
    stable_roi_digest: str | None = None
    confidence: float = 1.0
    supporting_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.target_identity, str) or not self.target_identity.strip():
            raise ScreenRecognitionError("target identity is required")
        if len(self.roi) != 4:
            raise ScreenRecognitionError("target ROI must have four coordinates")
        x0, y0, x1, y1 = self.roi
        if not all(type(value) is int for value in self.roi) or not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ScreenRecognitionError("target ROI is invalid")
        if self.semantic_identity is not None and not str(self.semantic_identity).strip():
            raise ScreenRecognitionError("semantic identity cannot be blank")
        if self.stable_roi_digest is not None and not str(self.stable_roi_digest).strip():
            raise ScreenRecognitionError("stable ROI digest cannot be blank")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ScreenRecognitionError("target confidence must be in [0, 1]")

    @property
    def binding_digest(self) -> str:
        """Stable digest for persistence; never a substitute for revalidation."""

        raw = "|".join(
            (
                self.target_identity,
                self.semantic_identity or "",
                self.stable_roi_digest or "",
                ",".join(str(value) for value in self.roi),
            )
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def compatible_with(self, fresh: "TargetBinding") -> bool:
        """Return whether a fresh binding preserves authoritative source semantics."""

        if not isinstance(fresh, TargetBinding):
            return False
        if self.target_identity != fresh.target_identity or self.roi != fresh.roi:
            return False
        if self.semantic_identity is not None and self.semantic_identity != fresh.semantic_identity:
            return False
        if self.stable_roi_digest is not None and self.stable_roi_digest != fresh.stable_roi_digest:
            return False
        return True


@dataclass(frozen=True)
class ScreenObservation:
    """Typed screen result bound to exactly one capture cycle."""

    screen: ScreenId | str
    overlays: tuple[OverlayId | str, ...] = ()
    frame_sha256: str = ""
    confidence: float = 0.0
    targets: tuple[TargetBinding, ...] = ()
    capture_id: str = ""
    stable_roi_digest: str | None = None
    evidence: tuple[str, ...] = ()
    reason_code: str = ""
    recognized: bool | None = None

    def __post_init__(self) -> None:
        try:
            screen = self.screen if isinstance(self.screen, ScreenId) else ScreenId(str(self.screen))
        except ValueError:
            screen = ScreenId.UNKNOWN
        object.__setattr__(self, "screen", screen)
        normalized_overlays: list[OverlayId] = []
        for item in self.overlays:
            try:
                normalized_overlays.append(item if isinstance(item, OverlayId) else OverlayId(str(item)))
            except ValueError:
                normalized_overlays.append(OverlayId.UNKNOWN)
        object.__setattr__(self, "overlays", tuple(normalized_overlays))
        if not isinstance(self.frame_sha256, str) or not self.frame_sha256.strip():
            raise ScreenRecognitionError("screen observation requires frame hash")
        if self.capture_id is None:
            object.__setattr__(self, "capture_id", "")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ScreenRecognitionError("screen confidence must be in [0, 1]")
        if any(not isinstance(target, TargetBinding) for target in self.targets):
            raise ScreenRecognitionError("screen targets must be TargetBinding values")
        if self.recognized is None:
            object.__setattr__(self, "recognized", self.screen is not ScreenId.UNKNOWN and self.confidence > 0.0)
        if self.screen is ScreenId.UNKNOWN:
            object.__setattr__(self, "recognized", False)

    @property
    def frame_hash(self) -> str:
        return self.frame_sha256

    @property
    def is_unknown(self) -> bool:
        return self.screen is ScreenId.UNKNOWN or not self.recognized

    def has_overlay(self, overlay: OverlayId | str) -> bool:
        try:
            expected = overlay if isinstance(overlay, OverlayId) else OverlayId(str(overlay))
        except ValueError:
            expected = OverlayId.UNKNOWN
        return expected in self.overlays

    def target(self, identity: str) -> TargetBinding | None:
        return next((item for item in self.targets if item.target_identity == identity), None)

    def requires_target(self, identity: str) -> TargetBinding:
        binding = self.target(identity)
        if binding is None:
            raise ScreenRecognitionError("TARGET_NOT_RECOGNIZED")
        return binding

    def revalidate_target(self, fresh: "ScreenObservation", identity: str) -> tuple[bool, str]:
        """Revalidate source and target bindings without trusting full-frame hashes."""

        if not isinstance(fresh, ScreenObservation) or fresh.is_unknown:
            return False, "UNKNOWN_FRESH_SCREEN"
        if self.is_unknown:
            return False, "UNKNOWN_SOURCE_SCREEN"
        if fresh.screen is not self.screen:
            return False, "SOURCE_SCREEN_CHANGED"
        # The observation-level stable ROI is the authoritative source
        # fingerprint.  A matching target binding is insufficient when the
        # surrounding source ROI changed (for example, an animation changed a
        # row or opened a different panel while preserving the button box).
        if self.stable_roi_digest != fresh.stable_roi_digest:
            return False, "STALE_OR_CHANGED_SOURCE_ROI"
        source = self.target(identity)
        rebound = fresh.target(identity)
        if source is None or rebound is None:
            return False, "TARGET_NOT_RECOGNIZED"
        if not source.compatible_with(rebound):
            return False, "STALE_OR_CHANGED_TARGET_ROI"
        return True, "OK"


class ScreenStage(Protocol):
    def __call__(self, cycle: CaptureCycle, deadline_monotonic: float | None = None) -> Any:
        ...


@dataclass(frozen=True)
class ScreenDefinition:
    """Registry entry.  Cheap template/geometry gates always precede OCR."""

    screen: ScreenId | str
    template: Callable[..., Any] | None = None
    geometry: Callable[..., Any] | None = None
    ocr: Callable[..., Any] | None = None
    recognizer: Callable[..., Any] | None = None
    priority: int = 100
    overlays: tuple[OverlayId | str, ...] = ()

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "screen", self.screen if isinstance(self.screen, ScreenId) else ScreenId(str(self.screen)))
        except ValueError:
            object.__setattr__(self, "screen", ScreenId.UNKNOWN)
        if type(self.priority) is not int:
            raise ScreenRecognitionError("screen priority must be an integer")


class ScreenRouter:
    """Registry-driven, one-capture recognition and stable target revalidation."""

    def __init__(
        self,
        registry: Mapping[ScreenId | str, Any] | Iterable[Any] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
        callback_timeout_seconds: float = 2.0,
        recognition_timeout_seconds: float | None = None,
    ) -> None:
        timeout = callback_timeout_seconds if recognition_timeout_seconds is None else recognition_timeout_seconds
        if isinstance(timeout, bool) or not math.isfinite(float(timeout)) or float(timeout) <= 0:
            raise ValueError("callback timeout must be finite and positive")
        self._clock = clock
        self._callback_timeout_seconds = float(timeout)
        self._definitions: list[Any] = []
        self._cache: dict[tuple[str, str], ScreenObservation] = {}
        if isinstance(registry, Mapping):
            for screen, recognizer in registry.items():
                self.register(ScreenDefinition(screen=screen, recognizer=recognizer))
        else:
            for definition in registry:
                self.register(definition)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def register(self, definition: Any, recognizer: Callable[..., Any] | None = None) -> None:
        if isinstance(definition, ScreenDefinition):
            entry = definition
        elif recognizer is None and callable(getattr(definition, "recognize", None)):
            # Preserve recognizer objects as recognizers.  Treating them as a
            # screen identifier would fall through to an unconditional
            # truthy observation and bypass their recognition result.
            entry = definition
        elif callable(definition) and recognizer is None:
            entry = definition
        else:
            entry = ScreenDefinition(screen=definition, recognizer=recognizer)
        self._definitions.append(entry)
        self._definitions.sort(key=lambda item: getattr(item, "priority", 100))

    def invalidate(self) -> None:
        """Forget all prior recognition after any input."""

        self._cache.clear()

    def observe(self, cycle: CaptureCycle, *, deadline_monotonic: float | None = None) -> ScreenObservation:
        if not isinstance(cycle, CaptureCycle):
            raise TypeError("ScreenRouter.observe requires a CaptureCycle")
        try:
            cached = self._cache.get(cycle.identity)
            if cached is not None:
                return cached
            deadline = deadline_monotonic
            if deadline is not None and self._clock() >= deadline:
                result = self._unknown(cycle, "RECOGNITION_DEADLINE")
                self._cache[cycle.identity] = result
                return result
            for entry in self._definitions:
                result = self._recognize_entry(entry, cycle, deadline)
                if result is not None:
                    self._cache[cycle.identity] = result
                    return result
            result = self._unknown(cycle, "UNKNOWN_SCREEN")
        except _RecognitionTimeout as exc:
            result = self._unknown(cycle, exc.reason)
        except Exception as exc:
            # Recognition callbacks are untrusted perception code.  Never allow a
            # callback or malformed callback result to escape into an input path.
            result = self._unknown(cycle, f"RECOGNITION_EXCEPTION:{type(exc).__name__}")
        self._cache[cycle.identity] = result
        return result

    def revalidate(
        self,
        source: ScreenObservation,
        cycle: CaptureCycle,
        *,
        target_identity: str | None = None,
        deadline_monotonic: float | None = None,
    ) -> tuple[bool, ScreenObservation, str]:
        try:
            fresh = self.observe(cycle, deadline_monotonic=deadline_monotonic)
            if target_identity is None:
                if source.is_unknown or fresh.is_unknown:
                    return False, fresh, "UNKNOWN_SCREEN"
                if source.screen is not fresh.screen:
                    return False, fresh, "SOURCE_SCREEN_CHANGED"
                return True, fresh, "OK"
            valid, reason = source.revalidate_target(fresh, target_identity)
            return valid, fresh, reason
        except Exception as exc:
            # Stable-ROI revalidation is an input authority.  A faulty source,
            # target, or compatibility implementation must never be treated as
            # valid merely because recognition completed.
            if isinstance(cycle, CaptureCycle):
                fresh = self._unknown(cycle, f"TARGET_REVALIDATION_EXCEPTION:{type(exc).__name__}")
                return False, fresh, fresh.reason_code
            raise

    def _recognize_entry(self, entry: Any, cycle: CaptureCycle, deadline: float | None) -> ScreenObservation | None:
        if not isinstance(entry, ScreenDefinition):
            recognizer = getattr(entry, "recognize", None)
            if callable(recognizer):
                return self._normalize(self._call(recognizer, cycle, deadline), cycle, None)
            if callable(entry):
                return self._normalize(self._call(entry, cycle, deadline), cycle, None)
            return None
        if entry.template is not None:
            template = self._call(entry.template, cycle, deadline)
            if not bool(template):
                return None
        if entry.geometry is not None:
            geometry = self._call(entry.geometry, cycle, deadline)
            if not bool(geometry):
                return None
        if entry.recognizer is not None:
            recognizer = getattr(entry.recognizer, "recognize", None)
            callback = recognizer if callable(recognizer) else entry.recognizer
            return self._normalize(self._call(callback, cycle, deadline), cycle, entry)
        if entry.ocr is not None:
            if deadline is not None and self._clock() >= deadline:
                return self._unknown(cycle, "OCR_DEADLINE")
            value = self._call(entry.ocr, cycle, deadline, timeout_reason="OCR_DEADLINE")
            if deadline is not None and self._clock() >= deadline:
                return self._unknown(cycle, "OCR_DEADLINE")
            return self._normalize(value, cycle, entry)
        return self._normalize(True, cycle, entry)

    def _call(
        self,
        fn: Callable[..., Any],
        cycle: CaptureCycle,
        deadline: float | None,
        *,
        timeout_reason: str = "RECOGNITION_DEADLINE",
    ) -> Any:
        """Run an untrusted perception callback behind a hard cancellable boundary.

        Python cannot safely kill a running thread.  The daemon worker therefore
        owns no router/session state, and a timed-out result is discarded forever;
        only a joined result can reach normalization or input authority.
        """

        now = self._clock()
        configured_deadline = now + self._callback_timeout_seconds
        hard_deadline = configured_deadline if deadline is None else min(float(deadline), configured_deadline)
        if not math.isfinite(hard_deadline):
            raise _RecognitionTimeout(timeout_reason)
        remaining = hard_deadline - now
        if remaining <= 0:
            raise _RecognitionTimeout(timeout_reason)
        try:
            params = inspect.signature(fn).parameters.values()
            positional = [item for item in params if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)]
            accepts_varargs = any(item.kind is item.VAR_POSITIONAL for item in params)
        except (TypeError, ValueError):
            positional, accepts_varargs = (), True

        result: dict[str, Any] = {}

        def invoke() -> None:
            try:
                if accepts_varargs or len(positional) >= 2:
                    result["value"] = fn(cycle, deadline)
                else:
                    result["value"] = fn(cycle)
            except Exception as exc:
                result["error"] = exc

        worker = threading.Thread(target=invoke, name="screen-perception", daemon=True)
        worker.start()
        worker.join(max(0.0, remaining))
        if worker.is_alive() or self._clock() >= hard_deadline:
            raise _RecognitionTimeout(timeout_reason)
        error = result.get("error")
        if error is not None:
            raise error
        return result.get("value")


    def _normalize(self, value: Any, cycle: CaptureCycle, definition: ScreenDefinition | None) -> ScreenObservation | None:
        if value is None or value is False:
            return None
        if isinstance(value, ScreenObservation):
            if value.capture_id and value.capture_id != cycle.capture_id:
                return self._unknown(cycle, "CROSS_CAPTURE_OBSERVATION")
            if value.frame_sha256 != cycle.frame_hash:
                return self._unknown(cycle, "FRAME_HASH_MISMATCH")
            if not value.capture_id:
                return ScreenObservation(
                    value.screen,
                    value.overlays,
                    cycle.frame_hash,
                    value.confidence,
                    value.targets,
                    cycle.capture_id,
                    value.stable_roi_digest,
                    value.evidence,
                    value.reason_code,
                    value.recognized,
                )
            return value
        if isinstance(value, Mapping):
            screen = value.get("screen", definition.screen if definition else ScreenId.UNKNOWN)
            overlays = tuple(value.get("overlays", definition.overlays if definition else ()))
            targets = tuple(value.get("targets", ()))
            converted_targets = tuple(
                target if isinstance(target, TargetBinding) else TargetBinding(**target) for target in targets
            )
            return ScreenObservation(
                screen=screen,
                overlays=overlays,
                frame_sha256=cycle.frame_hash,
                confidence=float(value.get("confidence", 1.0)),
                targets=converted_targets,
                capture_id=cycle.capture_id,
                stable_roi_digest=value.get("stable_roi_digest"),
                evidence=tuple(value.get("evidence", ())),
                reason_code=str(value.get("reason_code", "RECOGNIZED")),
                recognized=value.get("recognized", True),
            )
        if value is True and definition is not None:
            return ScreenObservation(
                definition.screen,
                definition.overlays,
                cycle.frame_hash,
                1.0,
                (),
                cycle.capture_id,
                reason_code="RECOGNIZED",
                recognized=True,
            )
        return None

    @staticmethod
    def _unknown(cycle: CaptureCycle, reason: str) -> ScreenObservation:
        return ScreenObservation(
            screen=ScreenId.UNKNOWN,
            overlays=(),
            frame_sha256=cycle.frame_hash,
            confidence=0.0,
            targets=(),
            capture_id=cycle.capture_id,
            reason_code=reason,
            recognized=False,
        )


__all__ = [
    "Box",
    "CaptureCycle",
    "OverlayId",
    "ScreenDefinition",
    "ScreenId",
    "ScreenObservation",
    "ScreenRecognitionError",
    "ScreenRouter",
    "TargetBinding",
]
