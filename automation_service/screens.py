"""Canonical immutable capture and screen-perception boundaries.

The router intentionally owns recognition order and caching.  Route modules may provide
small template/geometry/OCR functions, but may not turn a stale frame or a full-frame
hash into an input authority.  A target is authoritative only when its semantic identity
and stable ROI are rebound on the current capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
import hashlib
import inspect
import math
import re
import time
import threading
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol
from tasks.perception_bundle import NativeFrameIdentity, PerceptionBundleError
from tasks.semantic_ocr_crop import (
    CropRoiRequest,
    OcrEngine,
    OcrMode,
    ObservationStatus,
    SemanticOcrCropError,
    SemanticOcrObservation,
    run_semantic_ocr,
)
from .temporal import TemporalPolicy

import cv2
import numpy as np

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _coerce_screen(value: Any) -> "ScreenId":
    if isinstance(value, ScreenId):
        return value
    return ScreenId(str(value))


def _coerce_overlay(value: Any) -> "OverlayId":
    if isinstance(value, OverlayId):
        return value
    return OverlayId(str(value))


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _payload_sha256(value: Any) -> str:
    def canonical(item: Any) -> Any:
        if isinstance(item, (bytearray, memoryview)):
            return bytes(item)
        if isinstance(item, Mapping):
            return ("mapping", tuple((canonical(key), canonical(value)) for key, value in item.items()))
        if isinstance(item, (list, tuple)):
            return ("sequence", tuple(canonical(value) for value in item))
        if isinstance(item, (set, frozenset)):
            return ("set", tuple(sorted((canonical(value) for value in item), key=repr)))
        if is_dataclass(item):
            return ("dataclass", tuple((field.name, canonical(getattr(item, field.name))) for field in fields(item)))
        return item

    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        raw = repr(canonical(value)).encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()

def _freeze(value: Any) -> Any:
    """Snapshot the small value vocabulary allowed across the perception seam."""

    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, Mapping):
        return MappingProxyType({_freeze(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if is_dataclass(value):
        params = getattr(type(value), "__dataclass_params__", None)
        if params is not None and getattr(params, "frozen", False):
            snapshot = replace(
                value,
                **{
                    item.name: _freeze(getattr(value, item.name))
                    for item in fields(value)
                    if item.init
                },
            )
            for item in fields(value):
                if not item.init:
                    object.__setattr__(snapshot, item.name, _freeze(getattr(value, item.name)))
            return snapshot
        return MappingProxyType(
            {item.name: _freeze(getattr(value, item.name)) for item in fields(value)}
        )
    raise ScreenRecognitionError("capture payload contains mutable unsupported data")

class _RecognitionTimeout(TimeoutError):
    """A perception callback exceeded its hard execution deadline."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


Box = tuple[int, int, int, int]




def _decode_capture_image(cycle: CaptureCycle) -> np.ndarray:
    """Decode an explicit native image payload; never treat metadata as pixels."""

    payload = cycle.payload
    if isinstance(payload, np.ndarray):
        image = payload
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        encoded = np.frombuffer(bytes(payload), dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    elif isinstance(payload, Mapping):
        candidate = payload.get("frame", payload.get("png", payload.get("image")))
        if isinstance(candidate, np.ndarray):
            image = candidate
        elif isinstance(candidate, (bytes, bytearray, memoryview)):
            encoded = np.frombuffer(bytes(candidate), dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        else:
            raise ScreenRecognitionError("OCR_IMAGE_UNSUPPORTED")
    else:
        raise ScreenRecognitionError("OCR_IMAGE_UNSUPPORTED")
    if image is None or not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        raise ScreenRecognitionError("OCR_IMAGE_UNSUPPORTED")
    return np.ascontiguousarray(image)




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

    ``frame_hash`` is the full-frame transport hash and a cache key only.  It is
    deliberately not used as proof that a target has remained at the same
    location; that proof comes from a current stable ROI and semantic identity.
    """

    capture_id: str
    frame_hash: str
    payload: Any = None
    captured_monotonic: float = 0.0
    capture_ordinal: int = 0
    width: int | None = None
    height: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    runtime_session_id: str = ""
    transport_sha256: str = ""
    semantic_sha256: str = ""
    stable_roi_digest: str | None = None
    payload_sha256: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, str) or not self.capture_id.strip():
            raise ScreenRecognitionError("capture identity is required")
        if not isinstance(self.frame_hash, str) or not self.frame_hash.strip():
            raise ScreenRecognitionError("frame hash is required")
        try:
            captured_monotonic = float(self.captured_monotonic)
        except (TypeError, ValueError):
            raise ScreenRecognitionError("capture time must be finite") from None
        if not math.isfinite(captured_monotonic):
            raise ScreenRecognitionError("capture time must be finite")
        object.__setattr__(self, "captured_monotonic", captured_monotonic)
        if type(self.capture_ordinal) is not int or self.capture_ordinal < 0:
            raise ScreenRecognitionError("capture ordinal must be non-negative")
        if self.runtime_session_id is not None and not isinstance(self.runtime_session_id, str):
            raise ScreenRecognitionError("runtime session identity must be a string")
        if self.width is not None and (type(self.width) is not int or self.width <= 0):
            raise ScreenRecognitionError("capture width must be positive")
        if self.height is not None and (type(self.height) is not int or self.height <= 0):
            raise ScreenRecognitionError("capture height must be positive")
        if self.transport_sha256 and not _valid_digest(self.transport_sha256):
            raise ScreenRecognitionError("transport digest must be lowercase SHA-256")
        if self.semantic_sha256 and not _valid_digest(self.semantic_sha256):
            raise ScreenRecognitionError("semantic digest must be lowercase SHA-256")
        frozen_payload = _freeze(self.payload)
        computed_payload_sha256 = _payload_sha256(frozen_payload)
        if self.payload_sha256 and self.payload_sha256 != computed_payload_sha256:
            raise ScreenRecognitionError("payload digest does not match capture payload")
        object.__setattr__(self, "payload_sha256", computed_payload_sha256)
        if self.stable_roi_digest is not None and (
            not isinstance(self.stable_roi_digest, str) or not self.stable_roi_digest.strip()
        ):
            raise ScreenRecognitionError("stable ROI digest cannot be blank")
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({key: _freeze(value) for key, value in self.metadata.items()}),
        )
        if self.runtime_session_id is None:
            object.__setattr__(self, "runtime_session_id", "")
        if not self.transport_sha256:
            object.__setattr__(self, "transport_sha256", self.frame_hash)
        if not self.semantic_sha256:
            object.__setattr__(self, "semantic_sha256", self.frame_hash)

    @property
    def frame_sha256(self) -> str:
        """Compatibility spelling used by existing native-frame records."""

        return self.frame_hash

    @property
    def identity(self) -> tuple[str, int, str, str, str, str, str, str | None]:
        """The event identity used by the router recognition cache."""

        return (
            self.runtime_session_id,
            self.capture_ordinal,
            self.capture_id,
            self.frame_hash,
            self.payload_sha256,
            self.transport_sha256,
            self.semantic_sha256,
            self.stable_roi_digest,
        )


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
        try:
            roi = tuple(self.roi)
        except TypeError as exc:
            raise ScreenRecognitionError("target ROI must have four coordinates") from exc
        if len(roi) != 4:
            raise ScreenRecognitionError("target ROI must have four coordinates")
        x0, y0, x1, y1 = roi
        if not all(type(value) is int for value in roi) or not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ScreenRecognitionError("target ROI is invalid")
        object.__setattr__(self, "roi", roi)
        if self.semantic_identity is not None and not isinstance(self.semantic_identity, str):
            raise ScreenRecognitionError("semantic identity must be a string")
        if self.semantic_identity is not None and not self.semantic_identity.strip():
            raise ScreenRecognitionError("semantic identity cannot be blank")
        if self.stable_roi_digest is not None and not isinstance(self.stable_roi_digest, str):
            raise ScreenRecognitionError("stable ROI digest must be a string")
        if self.stable_roi_digest is not None and not self.stable_roi_digest.strip():
            raise ScreenRecognitionError("stable ROI digest cannot be blank")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ScreenRecognitionError("target confidence must be in [0, 1]")
        object.__setattr__(self, "supporting_evidence", tuple(str(item) for item in self.supporting_evidence))

    @property
    def complete_identity(self) -> bool:
        return (
            bool(self.target_identity.strip())
            and bool(self.semantic_identity and self.semantic_identity.strip())
            and bool(self.stable_roi_digest and self.stable_roi_digest.strip())
        )

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

        if not isinstance(fresh, TargetBinding) or not self.complete_identity or not fresh.complete_identity:
            return False
        if (
            self.target_identity != fresh.target_identity
            or self.roi != fresh.roi
            or self.semantic_identity != fresh.semantic_identity
            or self.stable_roi_digest != fresh.stable_roi_digest
        ):
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
    runtime_session_id: str = ""
    capture_ordinal: int = 0
    captured_monotonic: float = 0.0
    width: int | None = None
    height: int | None = None
    transport_sha256: str = ""
    semantic_sha256: str = ""
    payload_sha256: str = ""

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
        if len(set(normalized_overlays)) != len(normalized_overlays):
            raise ScreenRecognitionError("screen overlays contain contradictory duplicates")
        object.__setattr__(self, "overlays", tuple(normalized_overlays))
        if not isinstance(self.frame_sha256, str) or not self.frame_sha256.strip():
            raise ScreenRecognitionError("screen observation requires frame hash")
        if self.capture_id is None:
            object.__setattr__(self, "capture_id", "")
        elif not isinstance(self.capture_id, str):
            raise ScreenRecognitionError("observation capture identity must be a string")
        if self.runtime_session_id is None:
            object.__setattr__(self, "runtime_session_id", "")
        elif not isinstance(self.runtime_session_id, str):
            raise ScreenRecognitionError("observation session identity must be a string")
        if type(self.capture_ordinal) is not int or self.capture_ordinal < 0:
            raise ScreenRecognitionError("observation capture ordinal must be non-negative")
        if not math.isfinite(float(self.captured_monotonic)):
            raise ScreenRecognitionError("observation capture time must be finite")
        if self.width is not None and (type(self.width) is not int or self.width <= 0):
            raise ScreenRecognitionError("observation width must be positive")
        if self.height is not None and (type(self.height) is not int or self.height <= 0):
            raise ScreenRecognitionError("observation height must be positive")
        for digest, name in (
            (self.transport_sha256, "transport"),
            (self.semantic_sha256, "semantic"),
            (self.payload_sha256, "payload"),
        ):
            if digest and not _valid_digest(digest):
                raise ScreenRecognitionError(f"observation {name} digest must be lowercase SHA-256")
        if self.stable_roi_digest is not None and not isinstance(self.stable_roi_digest, str):
            raise ScreenRecognitionError("observation stable ROI digest must be a string")
        if self.stable_roi_digest is not None and not self.stable_roi_digest.strip():
            raise ScreenRecognitionError("observation stable ROI digest cannot be blank")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ScreenRecognitionError("screen confidence must be in [0, 1]")
        if any(not isinstance(target, TargetBinding) for target in self.targets):
            raise ScreenRecognitionError("screen targets must be TargetBinding values")
        identities = [target.target_identity for target in self.targets]
        if len(set(identities)) != len(identities):
            raise ScreenRecognitionError("screen targets contain contradictory duplicates")
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        if self.recognized is None:
            object.__setattr__(self, "recognized", self.screen is not ScreenId.UNKNOWN and self.confidence > 0.0)
        if self.screen is ScreenId.UNKNOWN:
            object.__setattr__(self, "recognized", False)
        if self.recognized and OverlayId.UNKNOWN in self.overlays:
            object.__setattr__(self, "recognized", False)

    @property
    def frame_hash(self) -> str:
        return self.frame_sha256

    @property
    def is_unknown(self) -> bool:
        return self.screen is ScreenId.UNKNOWN or not self.recognized

    @property
    def complete_provenance(self) -> bool:
        try:
            captured = float(self.captured_monotonic)
        except (TypeError, ValueError):
            return False
        return (
            bool(self.capture_id.strip())
            and bool(self.runtime_session_id.strip())
            and type(self.capture_ordinal) is int
            and self.capture_ordinal >= 1
            and type(self.width) is int
            and self.width > 0
            and type(self.height) is int
            and self.height > 0
            and math.isfinite(captured)
            and captured > 0
            and _valid_digest(self.frame_sha256)
            and _valid_digest(self.payload_sha256)
            and _valid_digest(self.transport_sha256)
            and _valid_digest(self.semantic_sha256)
        )

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

    def revalidate_target(
        self,
        fresh: "ScreenObservation",
        identity: str,
        *,
        now_monotonic: float | None = None,
    ) -> tuple[bool, str]:
        """Require a typed, newer same-session capture and a complete rebind."""

        if not isinstance(fresh, ScreenObservation):
            return False, "UNKNOWN_FRESH_SCREEN"
        if self.is_unknown:
            return False, "UNKNOWN_SOURCE_SCREEN"
        if fresh.is_unknown:
            return False, "UNKNOWN_FRESH_SCREEN"
        if not self.complete_provenance or not fresh.complete_provenance:
            return False, "INCOMPLETE_CAPTURE_PROVENANCE"
        if now_monotonic is not None:
            try:
                now = float(now_monotonic)
            except (TypeError, ValueError):
                return False, "INVALID_CAPTURE_TIME"
            if not math.isfinite(now):
                return False, "INVALID_CAPTURE_TIME"
            if self.captured_monotonic > now or fresh.captured_monotonic > now:
                return False, "FUTURE_CAPTURE"
            if (
                now - self.captured_monotonic > TemporalPolicy.max_age_seconds
                or now - fresh.captured_monotonic > TemporalPolicy.max_age_seconds
            ):
                return False, "STALE_CAPTURE_REVALIDATION"
        if self.runtime_session_id != fresh.runtime_session_id:
            return False, "CROSS_SESSION_OBSERVATION"
        if self.capture_id == fresh.capture_id and self.capture_ordinal == fresh.capture_ordinal:
            return False, "SAME_CAPTURE_REVALIDATION"
        if fresh.capture_ordinal <= self.capture_ordinal:
            return False, "STALE_CAPTURE_REVALIDATION"
        if fresh.captured_monotonic < self.captured_monotonic:
            return False, "STALE_CAPTURE_REVALIDATION"
        if (self.width, self.height) != (fresh.width, fresh.height):
            return False, "SOURCE_DIMENSIONS_CHANGED"
        if self.overlays != fresh.overlays:
            return False, "SOURCE_OVERLAYS_CHANGED"
        if fresh.screen is not self.screen:
            return False, "SOURCE_SCREEN_CHANGED"
        # The observation-level stable ROI is the authoritative source
        # fingerprint. A full-frame or transport hash is not authority.
        if not self.stable_roi_digest or not fresh.stable_roi_digest:
            return False, "SOURCE_STABLE_ROI_REQUIRED"
        if self.stable_roi_digest != fresh.stable_roi_digest:
            return False, "STALE_OR_CHANGED_SOURCE_ROI"
        source = self.target(identity)
        rebound = fresh.target(identity)
        if source is None or rebound is None:
            return False, "TARGET_NOT_RECOGNIZED"
        if not source.complete_identity or not rebound.complete_identity:
            return False, "INCOMPLETE_TARGET_IDENTITY"
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
    ocr: OcrEngine | None = None
    recognizer: Callable[..., Any] | None = None
    priority: int = 100
    overlays: tuple[OverlayId | str, ...] = ()
    ocr_request: CropRoiRequest | Callable[[CaptureCycle, float], CropRoiRequest] | None = None
    ocr_recognizer: Callable[[SemanticOcrObservation, CaptureCycle], Any] | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "screen", self.screen if isinstance(self.screen, ScreenId) else ScreenId(str(self.screen)))
        except ValueError:
            object.__setattr__(self, "screen", ScreenId.UNKNOWN)
        if type(self.priority) is not int:
            raise ScreenRecognitionError("screen priority must be an integer")
        overlays: list[OverlayId] = []
        for item in self.overlays:
            try:
                overlays.append(item if isinstance(item, OverlayId) else OverlayId(str(item)))
            except ValueError:
                overlays.append(OverlayId.UNKNOWN)
        if len(set(overlays)) != len(overlays):
            raise ScreenRecognitionError("screen definition overlays contain duplicates")
        object.__setattr__(self, "overlays", tuple(overlays))


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
        self._max_capture_age_seconds = TemporalPolicy.max_age_seconds
        self._definitions: list[Any] = []
        self._cache: dict[tuple[str, int, str, str, str, str, str, str | None], ScreenObservation] = {}
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

    def observe(
        self,
        cycle: CaptureCycle,
        *,
        deadline_monotonic: float | None = None,
        _bypass_cache: bool = False,
    ) -> ScreenObservation:
        if not isinstance(cycle, CaptureCycle):
            raise TypeError("ScreenRouter.observe requires a CaptureCycle")
        try:
            deadline = deadline_monotonic
            if deadline is not None and self._clock() >= deadline:
                result = self._unknown(cycle, "RECOGNITION_DEADLINE")
                if not _bypass_cache:
                    self._cache[cycle.identity] = result
                return result
            if not _bypass_cache:
                cached = self._cache.get(cycle.identity)
                if cached is not None:
                    return cached
            matches: list[ScreenObservation] = []
            for entry in self._definitions:
                result = self._recognize_entry(entry, cycle, deadline)
                if result is None:
                    continue
                if result.is_unknown:
                    if result.reason_code in {"", "RECOGNIZED"}:
                        result = self._unknown(cycle, "UNKNOWN_SCREEN")
                    if not _bypass_cache:
                        self._cache[cycle.identity] = result
                    return result
                matches.append(result)
            if deadline is not None and self._clock() >= deadline:
                result = self._unknown(cycle, "RECOGNITION_DEADLINE")
            elif not matches:
                result = self._unknown(cycle, "UNKNOWN_SCREEN")
            elif self._contradictory(matches):
                result = self._unknown(cycle, "CONTRADICTORY_RECOGNITION")
            else:
                result = matches[0]
        except _RecognitionTimeout as exc:
            result = self._unknown(cycle, exc.reason)
        except Exception as exc:
            # Recognition callbacks are untrusted perception code. Never allow a
            # callback or malformed callback result to escape into an input path.
            result = self._unknown(cycle, f"RECOGNITION_EXCEPTION:{type(exc).__name__}")
        if not _bypass_cache:
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
            now = float(self._clock())
            captured = float(cycle.captured_monotonic)
            if not math.isfinite(now) or not math.isfinite(captured) or captured <= 0:
                fresh = self._unknown(cycle, "INVALID_CAPTURE_TIME")
                return False, fresh, fresh.reason_code
            if captured > now:
                fresh = self._unknown(cycle, "FUTURE_CAPTURE")
                return False, fresh, fresh.reason_code
            if now - captured > self._max_capture_age_seconds:
                fresh = self._unknown(cycle, "STALE_CAPTURE_REVALIDATION")
                return False, fresh, fresh.reason_code
            fresh = self.observe(
                cycle,
                deadline_monotonic=deadline_monotonic,
                _bypass_cache=True,
            )
            if fresh.is_unknown:
                return False, fresh, fresh.reason_code
            if not isinstance(source, ScreenObservation):
                return False, fresh, "UNKNOWN_SOURCE_SCREEN"
            if not source.complete_provenance or not fresh.complete_provenance:
                return False, fresh, "INCOMPLETE_CAPTURE_PROVENANCE"
            now = float(self._clock())
            if not math.isfinite(now):
                return False, fresh, "INVALID_CAPTURE_TIME"
            if source.captured_monotonic > now:
                return False, fresh, "FUTURE_SOURCE_CAPTURE"
            if fresh.captured_monotonic > now:
                return False, fresh, "FUTURE_CAPTURE"
            if (
                now - source.captured_monotonic > self._max_capture_age_seconds
                or now - fresh.captured_monotonic > self._max_capture_age_seconds
            ):
                return False, fresh, "STALE_CAPTURE_REVALIDATION"
            if fresh.captured_monotonic < source.captured_monotonic:
                return False, fresh, "STALE_CAPTURE_REVALIDATION"
            if deadline_monotonic is not None and self._clock() >= deadline_monotonic:
                fresh = self._unknown(cycle, "RECOGNITION_DEADLINE")
                return False, fresh, fresh.reason_code
            if target_identity is None:
                if source.runtime_session_id != fresh.runtime_session_id:
                    return False, fresh, "CROSS_SESSION_OBSERVATION"
                if source.capture_ordinal >= fresh.capture_ordinal:
                    return False, fresh, "STALE_CAPTURE_REVALIDATION"
                if source.screen is not fresh.screen:
                    return False, fresh, "SOURCE_SCREEN_CHANGED"
                if (source.width, source.height) != (fresh.width, fresh.height):
                    return False, fresh, "SOURCE_DIMENSIONS_CHANGED"
                if source.overlays != fresh.overlays:
                    return False, fresh, "SOURCE_OVERLAYS_CHANGED"
                if not source.stable_roi_digest or not fresh.stable_roi_digest:
                    return False, fresh, "SOURCE_STABLE_ROI_REQUIRED"
                if source.stable_roi_digest != fresh.stable_roi_digest:
                    return False, fresh, "STALE_OR_CHANGED_SOURCE_ROI"
                return True, fresh, "OK"
            valid, reason = source.revalidate_target(
                fresh,
                target_identity,
                now_monotonic=now,
            )
            return valid, fresh, reason
        except Exception as exc:
            # Stable-ROI revalidation is an input authority.  A faulty source,
            # target, or compatibility implementation must never be treated as
            # valid merely because recognition completed.
            if isinstance(cycle, CaptureCycle):
                fresh = self._unknown(cycle, f"TARGET_REVALIDATION_EXCEPTION:{type(exc).__name__}")
                return False, fresh, fresh.reason_code
            raise

    def _screen_ocr_request(
        self,
        entry: ScreenDefinition,
        cycle: CaptureCycle,
        deadline: float | None,
    ) -> tuple[CropRoiRequest, np.ndarray]:
        """Build one canonical request, bind it to this capture, and decode it."""

        real_now = time.monotonic()
        try:
            clock_now = float(self._clock())
            remaining = self._callback_timeout_seconds
            if deadline is not None:
                remaining = min(remaining, float(deadline) - clock_now)
        except (TypeError, ValueError):
            raise _RecognitionTimeout("OCR_DEADLINE") from None
        if not math.isfinite(clock_now) or not math.isfinite(remaining) or remaining <= 0:
            raise _RecognitionTimeout("OCR_DEADLINE")
        hard_deadline = real_now + remaining
        factory = entry.ocr_request
        if isinstance(factory, CropRoiRequest):
            request = factory
        elif callable(factory):
            try:
                request = factory(cycle, hard_deadline)
            except (SemanticOcrCropError, PerceptionBundleError) as exc:
                raise ScreenRecognitionError(getattr(exc, "reason_code", "OCR_CONTRACT_INVALID")) from exc
        else:
            raise ScreenRecognitionError("OCR_CONTRACT_INVALID")
        if not isinstance(request, CropRoiRequest):
            raise ScreenRecognitionError("OCR_CONTRACT_INVALID")
        if not isinstance(request.ocr_mode, OcrMode):
            raise ScreenRecognitionError("OCR_MODE_INVALID")
        source = request.source_frame
        if not isinstance(source, NativeFrameIdentity):
            raise ScreenRecognitionError("OCR_CONTRACT_INVALID")
        envelope = cycle.metadata.get("envelope") if isinstance(cycle.metadata, Mapping) else None
        profile_id = getattr(envelope, "profile_id", None)
        if profile_id is not None and source.runtime_profile_id != profile_id:
            raise ScreenRecognitionError("OCR_CAPTURE_MISMATCH")
        if (
            cycle.width is None
            or cycle.height is None
            or source.runtime_session_id != cycle.runtime_session_id
            or source.capture_ordinal != cycle.capture_ordinal
            or source.capture_completed_monotonic != cycle.captured_monotonic
            or source.width != cycle.width
            or source.height != cycle.height
            or source.transport_sha256 != cycle.transport_sha256
            or source.semantic_sha256 != cycle.semantic_sha256
        ):
            raise ScreenRecognitionError("OCR_CAPTURE_MISMATCH")
        if request.deadline_monotonic is None:
            raise ScreenRecognitionError("OCR_DEADLINE_INVALID")
        request = replace(
            request,
            deadline_monotonic=min(float(request.deadline_monotonic), hard_deadline),
        )
        return request, _decode_capture_image(cycle)

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
            if entry.ocr_recognizer is None:
                return self._unknown(cycle, "OCR_MATCHER_REQUIRED")
            try:
                request, image = self._screen_ocr_request(entry, cycle, deadline)
            except _RecognitionTimeout as exc:
                return self._unknown(cycle, exc.reason)
            except ScreenRecognitionError as exc:
                return self._unknown(cycle, str(exc))
            ocr_observation = run_semantic_ocr(
                image,
                request,
                ocr_engine=entry.ocr,
            )
            if not isinstance(ocr_observation, SemanticOcrObservation):
                return self._unknown(cycle, "OCR_RESULT_INVALID")
            if ocr_observation.status is not ObservationStatus.OK:
                return self._unknown(cycle, ocr_observation.reason_code or "OCR_UNKNOWN")
            if time.monotonic() >= request.deadline_monotonic:
                return self._unknown(cycle, "OCR_DEADLINE")
            value = self._call(
                entry.ocr_recognizer,
                cycle,
                request.deadline_monotonic,
                timeout_reason="OCR_DEADLINE",
                call_args=(ocr_observation, cycle),
                deadline_is_real=True,
            )
            return self._normalize(value, cycle, entry)
        return self._normalize(True, cycle, entry)

    def _call(
        self,
        fn: Callable[..., Any],
        cycle: CaptureCycle,
        deadline: float | None,
        *,
        timeout_reason: str = "RECOGNITION_DEADLINE",
        call_args: tuple[Any, ...] | None = None,
        deadline_is_real: bool = False,
    ) -> Any:
        """Run an untrusted callback behind a hard cancellable boundary."""

        clock_now = float(self._clock())
        real_now = time.monotonic()
        if deadline_is_real:
            configured_deadline = real_now + self._callback_timeout_seconds
            hard_deadline = configured_deadline if deadline is None else min(float(deadline), configured_deadline)
            remaining = hard_deadline - real_now
            expired = lambda: time.monotonic() >= hard_deadline
        else:
            configured_deadline = clock_now + self._callback_timeout_seconds
            hard_deadline = configured_deadline if deadline is None else min(float(deadline), configured_deadline)
            remaining = hard_deadline - clock_now
            expired = lambda: self._clock() >= hard_deadline
        if not math.isfinite(hard_deadline) or remaining <= 0:
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
                if call_args is not None:
                    result["value"] = fn(*call_args)
                elif accepts_varargs or len(positional) >= 2:
                    result["value"] = fn(cycle, deadline)
                else:
                    result["value"] = fn(cycle)
            except Exception as exc:
                result["error"] = exc

        worker = threading.Thread(target=invoke, name="screen-perception", daemon=True)
        worker.start()
        worker.join(max(0.0, remaining))
        if worker.is_alive() or expired():
            raise _RecognitionTimeout(timeout_reason)
        error = result.get("error")
        if error is not None:
            raise error
        return result.get("value")


    @staticmethod
    def _contradictory(matches: list[ScreenObservation]) -> bool:
        first = matches[0]
        first_targets = {
            target.target_identity: (
                target.roi,
                target.semantic_identity,
                target.stable_roi_digest,
            )
            for target in first.targets
        }
        for other in matches[1:]:
            if (
                other.screen is not first.screen
                or set(other.overlays) != set(first.overlays)
                or other.stable_roi_digest != first.stable_roi_digest
            ):
                return True
            other_targets = {
                target.target_identity: (
                    target.roi,
                    target.semantic_identity,
                    target.stable_roi_digest,
                )
                for target in other.targets
            }
            if other_targets != first_targets:
                return True
        return False
    @staticmethod
    def _cycle_provenance(cycle: CaptureCycle) -> dict[str, Any]:
        return {
            "capture_id": cycle.capture_id,
            "runtime_session_id": cycle.runtime_session_id,
            "capture_ordinal": cycle.capture_ordinal,
            "captured_monotonic": cycle.captured_monotonic,
            "width": cycle.width,
            "height": cycle.height,
            "payload_sha256": cycle.payload_sha256,
            "transport_sha256": cycle.transport_sha256,
            "semantic_sha256": cycle.semantic_sha256,
        }

    @classmethod
    def _bind_observation(
        cls,
        value: ScreenObservation,
        cycle: CaptureCycle,
    ) -> ScreenObservation:
        provenance = cls._cycle_provenance(cycle)
        if value.capture_id and value.capture_id != cycle.capture_id:
            return cls._unknown(cycle, "CROSS_CAPTURE_OBSERVATION")
        if not (
            isinstance(value.capture_id, str)
            and value.capture_id.strip()
            and isinstance(value.runtime_session_id, str)
            and value.runtime_session_id.strip()
            and type(value.capture_ordinal) is int
            and value.capture_ordinal >= 1
            and isinstance(value.captured_monotonic, (int, float))
            and not isinstance(value.captured_monotonic, bool)
            and math.isfinite(float(value.captured_monotonic))
            and value.captured_monotonic > 0
            and type(value.width) is int
            and value.width > 0
            and type(value.height) is int
            and value.height > 0
            and _valid_digest(value.payload_sha256)
            and _valid_digest(value.transport_sha256)
            and _valid_digest(value.semantic_sha256)
        ):
            return cls._unknown(cycle, "INCOMPLETE_CAPTURE_PROVENANCE")
        if value.capture_id != cycle.capture_id:
            return cls._unknown(cycle, "CROSS_CAPTURE_OBSERVATION")
        for name in (
            "runtime_session_id",
            "capture_ordinal",
            "width",
            "height",
            "payload_sha256",
            "transport_sha256",
            "semantic_sha256",
        ):
            supplied = getattr(value, name)
            expected = provenance[name]
            if supplied != expected:
                return cls._unknown(cycle, "CAPTURE_PROVENANCE_MISMATCH")
        if value.captured_monotonic != cycle.captured_monotonic:
            return cls._unknown(cycle, "CAPTURE_PROVENANCE_MISMATCH")
        if value.frame_sha256 != cycle.frame_hash:
            return cls._unknown(cycle, "FRAME_HASH_MISMATCH")
        if (
            value.stable_roi_digest is not None
            and cycle.stable_roi_digest is not None
            and value.stable_roi_digest != cycle.stable_roi_digest
        ):
            return cls._unknown(cycle, "CAPTURE_PROVENANCE_MISMATCH")
        return ScreenObservation(
            screen=value.screen,
            overlays=value.overlays,
            frame_sha256=cycle.frame_hash,
            confidence=value.confidence,
            targets=value.targets,
            stable_roi_digest=(
                value.stable_roi_digest
                if value.stable_roi_digest is not None
                else cycle.stable_roi_digest
            ),
            evidence=value.evidence,
            reason_code=value.reason_code,
            recognized=value.recognized,
            **provenance,
        )

    @classmethod
    def _mapping_provenance_matches(cls, value: Mapping[str, Any], cycle: CaptureCycle) -> bool:
        expected = cls._cycle_provenance(cycle)
        required = (
            "capture_id",
            "runtime_session_id",
            "capture_ordinal",
            "captured_monotonic",
            "width",
            "height",
            "payload_sha256",
            "transport_sha256",
            "semantic_sha256",
        )
        if any(name not in value for name in required) or "stable_roi_digest" not in value:
            return False
        if not ("frame_hash" in value or "frame_sha256" in value):
            return False
        if any(value[name] != expected[name] for name in required):
            return False
        if "frame_hash" in value and value["frame_hash"] != cycle.frame_hash:
            return False
        if "frame_sha256" in value and value["frame_sha256"] != cycle.frame_hash:
            return False
        if cycle.stable_roi_digest is not None and value["stable_roi_digest"] != cycle.stable_roi_digest:
            return False
        return (
            isinstance(value["capture_id"], str)
            and bool(value["capture_id"].strip())
            and isinstance(value["runtime_session_id"], str)
            and bool(value["runtime_session_id"].strip())
            and type(value["capture_ordinal"]) is int
            and value["capture_ordinal"] >= 1
            and isinstance(value["captured_monotonic"], (int, float))
            and not isinstance(value["captured_monotonic"], bool)
            and math.isfinite(float(value["captured_monotonic"]))
            and float(value["captured_monotonic"]) > 0
            and type(value["width"]) is int
            and value["width"] > 0
            and type(value["height"]) is int
            and value["height"] > 0
            and _valid_digest(value["payload_sha256"])
            and _valid_digest(value["transport_sha256"])
            and _valid_digest(value["semantic_sha256"])
            and isinstance(value["stable_roi_digest"], str)
            and bool(value["stable_roi_digest"].strip())
        )
    def _normalize(self, value: Any, cycle: CaptureCycle, definition: ScreenDefinition | None) -> ScreenObservation | None:
        if value is None or value is False:
            return None
        if isinstance(value, ScreenObservation):
            if definition is not None and value.screen is not definition.screen:
                return self._unknown(cycle, "CONTRADICTORY_SCREEN")
            if definition is not None and definition.overlays and set(value.overlays) != set(definition.overlays):
                return self._unknown(cycle, "CONTRADICTORY_OVERLAY")
            return self._bind_observation(value, cycle)
        if isinstance(value, Mapping):
            if not self._mapping_provenance_matches(value, cycle):
                return self._unknown(cycle, "CAPTURE_PROVENANCE_MISMATCH")
            screen = value.get("screen", definition.screen if definition else ScreenId.UNKNOWN)
            try:
                normalized_screen = _coerce_screen(screen)
            except ValueError:
                return self._unknown(cycle, "CONTRADICTORY_SCREEN")
            if "screen" in value and definition is not None and normalized_screen is not definition.screen:
                return self._unknown(cycle, "CONTRADICTORY_SCREEN")
            if "overlays" in value:
                try:
                    overlays = tuple(_coerce_overlay(item) for item in value["overlays"])
                except ValueError:
                    return self._unknown(cycle, "CONTRADICTORY_OVERLAY")
                if definition is not None and definition.overlays and set(overlays) != set(definition.overlays):
                    return self._unknown(cycle, "CONTRADICTORY_OVERLAY")
            else:
                overlays = definition.overlays if definition else ()
            targets = tuple(value.get("targets", ()))
            converted_targets = tuple(
                target if isinstance(target, TargetBinding) else TargetBinding(**target) for target in targets
            )
            return ScreenObservation(
                screen=normalized_screen,
                overlays=overlays,
                frame_sha256=cycle.frame_hash,
                confidence=float(value.get("confidence", 1.0)),
                targets=converted_targets,
                stable_roi_digest=value["stable_roi_digest"],
                evidence=tuple(value.get("evidence", ())),
                reason_code=str(value.get("reason_code", "RECOGNIZED")),
                recognized=value.get("recognized", True),
                **self._cycle_provenance(cycle),
            )
        if value is True and definition is not None:
            return ScreenObservation(
                screen=definition.screen,
                overlays=definition.overlays,
                frame_sha256=cycle.frame_hash,
                confidence=1.0,
                targets=(),
                stable_roi_digest=cycle.stable_roi_digest,
                reason_code="RECOGNIZED",
                recognized=True,
                **self._cycle_provenance(cycle),
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
            reason_code=reason,
            recognized=False,
            **ScreenRouter._cycle_provenance(cycle),
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
