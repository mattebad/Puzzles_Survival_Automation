"""Shared frame-identity-bound semantic OCR crop pipeline.

Every crop and OCR observation is bound to a complete NativeFrameIdentity (capture event,
transport digest, and semantic digest). Recognition never authorizes transport or dispatch.
Debug crop artifacts are disabled by default and, when enabled, are deterministic and temporary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import math
import multiprocessing
import pickle
from numbers import Integral
import os
import tempfile
from pathlib import Path
import signal
from types import MappingProxyType
import time
from typing import Any, Callable, Mapping, Tuple

import cv2
import numpy as np

from tasks.perception_bundle import ImmutableOcrObservation, NativeFrameIdentity, PerceptionBundleError


SCHEMA_NAME = "semantic_ocr_crop"
SCHEMA_VERSION = 1

Box = Tuple[int, int, int, int]
OcrEngine = Callable[[np.ndarray, int], str]

MAX_PADDING_PX = 64
MAX_OCR_ROI_PIXELS = 262_144
DEFAULT_OCR_TIMEOUT_SECONDS = 2.0
_SHA256_HEX_LEN = 64


class SemanticOcrCropError(ValueError):
    """Fail-closed crop, mask, identity, or OCR-mode denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class OcrMode(str, Enum):
    """Closed OCR mode contract. Arbitrary PSM integers and free-form modes are rejected."""

    UNIFORM_BLOCK = "uniform_block"
    SPARSE_TEXT = "sparse_text"
    UNIFORM_AND_SPARSE = "uniform_and_sparse"


class NormalizationOp(str, Enum):
    """Bounded normalization operations only. No arbitrary callbacks or unconstrained modes."""

    TO_GRAYSCALE = "to_grayscale"
    UPSCALE_2X = "upscale_2x"
    UPSCALE_3X = "upscale_3x"


class ObservationStatus(str, Enum):
    OK = "ok"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


_OCR_MODE_PSMS: Mapping[OcrMode, tuple[int, ...]] = MappingProxyType(
    {
        OcrMode.UNIFORM_BLOCK: (6,),
        OcrMode.SPARSE_TEXT: (11,),
        OcrMode.UNIFORM_AND_SPARSE: (6, 11),
    }
)


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise SemanticOcrCropError("INVALID_BOX", field)
    return int(value)


def _coerce_box(box: object, field: str) -> Box:
    if not isinstance(box, tuple) or len(box) != 4:
        raise SemanticOcrCropError("INVALID_BOX", field)
    coerced = (
        _as_int(box[0], field),
        _as_int(box[1], field),
        _as_int(box[2], field),
        _as_int(box[3], field),
    )
    if not (coerced[0] < coerced[2] and coerced[1] < coerced[3]):
        raise SemanticOcrCropError("INVALID_BOX", field)
    return coerced


def _coerce_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", field)
    return tuple(value)


def _coerce_padding_tuple(value: object) -> tuple[int, int, int, int]:
    if not isinstance(value, tuple) or len(value) != 4:
        raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "padding")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, Integral):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "padding")
        normalized = int(item)
        if normalized < 0 or normalized > MAX_PADDING_PX:
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "padding")
        result.append(normalized)
    return (result[0], result[1], result[2], result[3])


def _validate_normalization_plan(operations: object) -> tuple[NormalizationOp, ...]:
    """Return one closed, bounded normalization plan."""

    if not isinstance(operations, tuple):
        raise SemanticOcrCropError("INVALID_NORMALIZATION_SEQUENCE")
    if any(not isinstance(operation, NormalizationOp) for operation in operations):
        raise SemanticOcrCropError("INVALID_NORMALIZATION_SEQUENCE")
    allowed = {
        (),
        (NormalizationOp.TO_GRAYSCALE,),
        (NormalizationOp.UPSCALE_2X,),
        (NormalizationOp.UPSCALE_3X,),
        (NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_2X),
        (NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_3X),
    }
    normalized = tuple(operations)
    if normalized not in allowed:
        raise SemanticOcrCropError("INVALID_NORMALIZATION_SEQUENCE")
    return normalized




@dataclass(frozen=True)
class PaddingSpec:
    """Explicit per-edge padding in native full-frame pixels."""

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    def __post_init__(self) -> None:
        for edge, value in (
            ("left", self.left),
            ("top", self.top),
            ("right", self.right),
            ("bottom", self.bottom),
        ):
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise SemanticOcrCropError("INVALID_PADDING", edge)
            coerced = int(value)
            object.__setattr__(self, edge, coerced)
            if coerced < 0:
                raise SemanticOcrCropError("NEGATIVE_PADDING", edge)
            if coerced > MAX_PADDING_PX:
                raise SemanticOcrCropError("PADDING_EXCEEDS_BOUND", edge)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class ExclusionMask:
    """Axis-aligned exclusion in parent native full-frame coordinates.

    Boxes use half-open semantics matching numpy slicing: [x0, x1) x [y0, y1).
    Declared exclusions must remain outside the effective padded crop; padding may not
    silently expand into an exclusion.
    """

    box: Box

    def __post_init__(self) -> None:
        object.__setattr__(self, "box", _coerce_box(self.box, "exclusion_mask"))


@dataclass(frozen=True)
class CropRoiRequest:
    """Identity-bound native ROI and (when OCR is requested) deadline contract.

    ``ocr_mode`` and ``deadline_monotonic`` are optional only for the crop-preparation
    API.  ``run_semantic_ocr`` requires both values on this single request object.
    """

    source_frame: NativeFrameIdentity
    roi: Box
    padding: PaddingSpec = PaddingSpec()
    exclusion_masks: tuple[ExclusionMask, ...] = ()
    ocr_mode: OcrMode | None = None
    deadline_monotonic: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_frame, NativeFrameIdentity):
            raise SemanticOcrCropError("INVALID_SOURCE_FRAME")
        if not isinstance(self.padding, PaddingSpec):
            raise SemanticOcrCropError("INVALID_PADDING")
        object.__setattr__(self, "roi", _coerce_box(self.roi, "roi"))
        if not isinstance(self.exclusion_masks, tuple):
            raise SemanticOcrCropError("INVALID_EXCLUSION_MASK")
        for mask in self.exclusion_masks:
            if not isinstance(mask, ExclusionMask):
                raise SemanticOcrCropError("INVALID_EXCLUSION_MASK")
        object.__setattr__(self, "exclusion_masks", tuple(self.exclusion_masks))
        if self.ocr_mode is not None and not isinstance(self.ocr_mode, OcrMode):
            raise SemanticOcrCropError("UNKNOWN_OCR_MODE")
        if self.deadline_monotonic is not None:
            if isinstance(self.deadline_monotonic, bool):
                raise SemanticOcrCropError("INVALID_DEADLINE")
            try:
                deadline = float(self.deadline_monotonic)
            except (TypeError, ValueError):
                raise SemanticOcrCropError("INVALID_DEADLINE") from None
            if not math.isfinite(deadline) or deadline < 0:
                raise SemanticOcrCropError("INVALID_DEADLINE")
            object.__setattr__(self, "deadline_monotonic", deadline)


@dataclass(frozen=True)
class CropProvenance:
    """Immutable crop provenance. Never retains pixel buffers."""

    source_frame: NativeFrameIdentity
    requested_roi: Box
    effective_roi: Box
    padding: tuple[int, int, int, int]
    exclusion_masks: tuple[Box, ...]
    normalization: tuple[NormalizationOp, ...]
    transport_sha256: str
    semantic_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_frame, NativeFrameIdentity):
            raise SemanticOcrCropError("INVALID_SOURCE_FRAME")
        object.__setattr__(self, "requested_roi", _coerce_box(self.requested_roi, "requested_roi"))
        object.__setattr__(self, "effective_roi", _coerce_box(self.effective_roi, "effective_roi"))
        object.__setattr__(self, "padding", _coerce_padding_tuple(self.padding))
        if not isinstance(self.exclusion_masks, tuple):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "exclusion_masks")
        object.__setattr__(
            self,
            "exclusion_masks",
            tuple(_coerce_box(mask, "exclusion_mask") for mask in self.exclusion_masks),
        )
        object.__setattr__(
            self,
            "normalization",
            _validate_normalization_plan(self.normalization),
        )
        if self.transport_sha256 != self.source_frame.transport_sha256:
            raise SemanticOcrCropError("TRANSPORT_DIGEST_MISMATCH")
        if self.semantic_sha256 != self.source_frame.semantic_sha256:
            raise SemanticOcrCropError("SEMANTIC_DIGEST_MISMATCH")


@dataclass(frozen=True)
class SemanticOcrObservation:
    """Immutable OCR observation. Never retains mutable numpy buffers."""

    source_frame: NativeFrameIdentity
    text: str
    requested_roi: Box
    effective_roi: Box
    ocr_mode: OcrMode
    normalization: tuple[NormalizationOp, ...]
    exclusion_masks: tuple[Box, ...]
    padding: tuple[int, int, int, int]
    status: ObservationStatus
    reason_code: str
    confidence: float
    supporting_evidence: tuple[str, ...] = ()
    debug_artifact_name: str | None = None
    debug_artifact_sha256: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_frame, NativeFrameIdentity):
            raise SemanticOcrCropError("INVALID_SOURCE_FRAME")
        if not isinstance(self.ocr_mode, OcrMode):
            raise SemanticOcrCropError("UNKNOWN_OCR_MODE")
        if not isinstance(self.status, ObservationStatus):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "status")
        if not isinstance(self.text, str) or not isinstance(self.reason_code, str):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "text_or_reason")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "confidence")
        object.__setattr__(self, "confidence", float(self.confidence))
        if self.debug_artifact_name is not None and not isinstance(
            self.debug_artifact_name, str
        ):
            raise SemanticOcrCropError(
                "INVALID_IMMUTABLE_FIELD",
                "debug_artifact_name",
            )
        if self.debug_artifact_sha256 is not None and not isinstance(
            self.debug_artifact_sha256, str
        ):
            raise SemanticOcrCropError(
                "INVALID_IMMUTABLE_FIELD",
                "debug_artifact_sha256",
            )
        object.__setattr__(self, "requested_roi", _coerce_box(self.requested_roi, "requested_roi"))
        object.__setattr__(self, "effective_roi", _coerce_box(self.effective_roi, "effective_roi"))
        object.__setattr__(
            self,
            "normalization",
            _validate_normalization_plan(self.normalization),
        )
        if not isinstance(self.exclusion_masks, tuple):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "exclusion_masks")
        object.__setattr__(
            self,
            "exclusion_masks",
            tuple(_coerce_box(mask, "exclusion_mask") for mask in self.exclusion_masks),
        )
        object.__setattr__(self, "padding", _coerce_padding_tuple(self.padding))
        object.__setattr__(
            self,
            "supporting_evidence",
            _coerce_string_tuple(self.supporting_evidence, "supporting_evidence"),
        )
        if not isinstance(self.metadata, Mapping):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "metadata")
        copied_metadata = dict(self.metadata)
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in copied_metadata.items()
        ):
            raise SemanticOcrCropError("INVALID_IMMUTABLE_FIELD", "metadata")
        object.__setattr__(self, "metadata", MappingProxyType(copied_metadata))
        _require_same_parent_digests(self.source_frame)


def _require_same_parent_digests(identity: NativeFrameIdentity) -> None:
    if len(identity.transport_sha256) != _SHA256_HEX_LEN or len(identity.semantic_sha256) != _SHA256_HEX_LEN:
        raise SemanticOcrCropError("INVALID_DIGEST")


def compute_transport_digest(frame: np.ndarray) -> str:
    """PNG transport digest for the supplied native frame pixels."""

    if not isinstance(frame, np.ndarray):
        raise SemanticOcrCropError("INVALID_FRAME")
    ok, payload = cv2.imencode(".png", frame)
    if not ok:
        raise SemanticOcrCropError("FRAME_ENCODE_FAILED")
    return hashlib.sha256(payload.tobytes()).hexdigest()


def _boxes_intersect(a: Box, b: Box) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _validate_identity_against_frame(frame: np.ndarray, identity: NativeFrameIdentity) -> str:
    if not isinstance(frame, np.ndarray):
        raise SemanticOcrCropError("INVALID_FRAME")
    if frame.ndim not in (2, 3):
        raise SemanticOcrCropError("INVALID_FRAME")
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if width != identity.width or height != identity.height:
        raise SemanticOcrCropError("FRAME_GEOMETRY_MISMATCH")
    transport = compute_transport_digest(frame)
    if transport != identity.transport_sha256:
        raise SemanticOcrCropError("TRANSPORT_DIGEST_MISMATCH")
    return transport


def _validate_masks_in_frame(identity: NativeFrameIdentity, masks: tuple[ExclusionMask, ...]) -> tuple[Box, ...]:
    validated: list[Box] = []
    for mask in masks:
        x0, y0, x1, y1 = mask.box
        if not (0 <= x0 < x1 <= identity.width and 0 <= y0 < y1 <= identity.height):
            raise SemanticOcrCropError("EXCLUSION_OUT_OF_BOUNDS")
        validated.append(mask.box)
    return tuple(validated)


def _resolve_effective_roi(
    identity: NativeFrameIdentity,
    requested: Box,
    padding: PaddingSpec,
    exclusion_boxes: tuple[Box, ...],
) -> Box:
    x0, y0, x1, y1 = requested
    if (x0, y0, x1, y1) == (0, 0, identity.width, identity.height):
        raise SemanticOcrCropError("ROI_FULL_FRAME")
    if not (0 <= x0 < x1 <= identity.width and 0 <= y0 < y1 <= identity.height):
        raise SemanticOcrCropError("ROI_OUT_OF_BOUNDS")
    for excluded in exclusion_boxes:
        if _boxes_intersect(requested, excluded):
            raise SemanticOcrCropError("ROI_INTERSECTS_EXCLUSION")
    padded = (
        x0 - padding.left,
        y0 - padding.top,
        x1 + padding.right,
        y1 + padding.bottom,
    )
    px0, py0, px1, py1 = padded
    if px0 < 0 or py0 < 0 or px1 > identity.width or py1 > identity.height:
        raise SemanticOcrCropError("PADDING_OUT_OF_BOUNDS")
    for excluded in exclusion_boxes:
        if _boxes_intersect(padded, excluded):
            raise SemanticOcrCropError("PADDING_ESCAPES_EXCLUSION")
    if padded == (0, 0, identity.width, identity.height):
        raise SemanticOcrCropError("ROI_FULL_FRAME")
    if (px1 - px0) * (py1 - py0) > MAX_OCR_ROI_PIXELS:
        raise SemanticOcrCropError("ROI_TOO_LARGE")
    return padded


def _apply_normalization(
    crop: np.ndarray,
    operations: tuple[NormalizationOp, ...],
) -> np.ndarray:
    current = crop
    for operation in operations:
        if operation is NormalizationOp.TO_GRAYSCALE:
            if current.ndim == 2:
                continue
            if current.ndim != 3 or current.shape[2] not in (3, 4):
                raise SemanticOcrCropError("INVALID_FRAME")
            current = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        elif operation is NormalizationOp.UPSCALE_2X:
            current = cv2.resize(current, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        elif operation is NormalizationOp.UPSCALE_3X:
            current = cv2.resize(current, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        else:
            raise SemanticOcrCropError("UNKNOWN_NORMALIZATION", operation.value)
    return current




def _default_ocr_engine(image: np.ndarray, psm: int) -> str:
    import pytesseract

    return pytesseract.image_to_string(image, config=f"--psm {psm}")


class _OcrWorkerError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


_MAX_OCR_WORKER_RESULT_BYTES = 4 * 1024 * 1024
_OCR_CLEANUP_RESERVE_SECONDS = 0.25


def _write_ocr_worker_message(path: str, message: tuple[Any, ...]) -> None:
    payload = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    if len(payload) > _MAX_OCR_WORKER_RESULT_BYTES:
        raise ValueError("OCR worker result is too large")
    Path(path).write_bytes(payload)


def _ocr_worker_entry(
    ready_event: Any,
    run_event: Any,
    done_event: Any,
    result_path: str,
    pixels: np.ndarray,
    engine: OcrEngine,
    psms: tuple[int, ...],
) -> None:
    """Execute injected OCR in a process whose lifetime the parent owns."""

    if os.name != "nt":
        try:
            os.setsid()
        except OSError:
            try:
                _write_ocr_worker_message(result_path, ("unsupported",))
            except BaseException:
                pass
            ready_event.set()
            done_event.set()
            return
    ready_event.set()
    if not run_event.wait():
        done_event.set()
        return
    try:
        _write_ocr_worker_message(
            result_path,
            ("result", tuple(str(engine(pixels, psm)) for psm in psms)),
        )
    except KeyboardInterrupt:
        try:
            _write_ocr_worker_message(result_path, ("interrupt",))
        except BaseException:
            pass
    except BaseException as exc:
        try:
            _write_ocr_worker_message(result_path, ("error", type(exc).__name__))
        except BaseException:
            pass
    finally:
        done_event.set()
        # Retain the session leader until the parent tears down the entire tree.
        while True:
            time.sleep(60.0)

def _create_windows_ocr_job(pid: int) -> Any:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_longlong),
            ("per_job_user_time_limit", ctypes.c_longlong),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operations", ctypes.c_ulonglong),
            ("write_operations", ctypes.c_ulonglong),
            ("other_operations", ctypes.c_ulonglong),
            ("read_transfer", ctypes.c_ulonglong),
            ("write_transfer", ctypes.c_ulonglong),
            ("other_transfer", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", BasicLimitInformation),
            ("io_info", IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    class BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_longlong),
            ("total_kernel_time", ctypes.c_longlong),
            ("this_period_total_user_time", ctypes.c_longlong),
            ("this_period_total_kernel_time", ctypes.c_longlong),
            ("total_page_fault_count", wintypes.DWORD),
            ("total_processes", wintypes.DWORD),
            ("active_processes", wintypes.DWORD),
            ("total_terminated_processes", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [handle, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = handle
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = handle
    kernel32.SetInformationJobObject.argtypes = [handle, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [handle, handle]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [handle]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [handle, wintypes.UINT]
    kernel32.QueryInformationJobObject.argtypes = [
        handle,
        wintypes.INT,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    process = kernel32.OpenProcess(0x0001 | 0x0100, False, pid)
    if not job or not process:
        if process:
            kernel32.CloseHandle(process)
        if job:
            kernel32.CloseHandle(job)
        raise _OcrWorkerError("OCR_WORKER_UNSUPPORTED")
    info = ExtendedLimitInformation()
    info.basic_limit_information.limit_flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    ) or not kernel32.AssignProcessToJobObject(job, process):
        kernel32.CloseHandle(process)
        kernel32.CloseHandle(job)
        raise _OcrWorkerError("OCR_WORKER_UNSUPPORTED")
    kernel32.CloseHandle(process)
    return (kernel32, job, BasicAccountingInformation)

def _windows_job_has_active_processes(job: Any) -> bool | None:
    if job is None:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32, handle, accounting_type = job
    info = accounting_type()
    returned = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
        handle,
        1,
        ctypes.byref(info),
        ctypes.sizeof(info),
        ctypes.byref(returned),
    ):
        return None
    return int(info.active_processes) > 0


def _drain_windows_ocr_job(job: Any, deadline: float) -> bool:
    while time.monotonic() < deadline:
        active = _windows_job_has_active_processes(job)
        if active is False:
            return True
        if active is None:
            return False
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    return _windows_job_has_active_processes(job) is False


def _close_windows_ocr_job(job: Any) -> None:
    if job is not None:
        job[0].CloseHandle(job[1])

def _posix_group_has_executing_processes(pgid: int) -> bool | None:
    """Return whether a process group still has a non-zombie member."""

    if os.name == "nt":
        return False
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            stat = Path("/proc") / entry / "stat"
            data = stat.read_text(encoding="ascii")
            fields = data[data.rfind(")") + 2 :].split()
            if len(fields) >= 3 and int(fields[2]) == pgid and fields[0] not in {"Z", "X"}:
                return True
        except (OSError, ValueError):
            continue
    return False


def _wait_for_posix_group_drain(pgid: int, deadline: float) -> bool:
    while True:
        active = _posix_group_has_executing_processes(pgid)
        if active is not True:
            return active is False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
def _terminate_and_reap_ocr_worker(
    worker: Any,
    job: Any,
    deadline: float,
    process_group: int | None,
) -> None:
    """Drain the owned tree and reap its held root within the reserved budget."""

    safe_group = os.name != "nt" and process_group is not None and process_group != os.getpgrp()
    if job is not None:
        job[0].TerminateJobObject(job[1], 1)
    elif safe_group:
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        try:
            worker.terminate()
        except (OSError, AssertionError):
            pass
    worker.join(min(0.02, max(0.0, deadline - time.monotonic())))
    # Kill remaining group members even if the root exited on SIGTERM.
    if safe_group:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if worker.is_alive():
        worker.kill()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise _OcrWorkerError("OCR_WORKER_REAP_FAILED")
    if job is not None and not _drain_windows_ocr_job(job, deadline):
        raise _OcrWorkerError("OCR_WORKER_REAP_FAILED")
    if safe_group and not _wait_for_posix_group_drain(process_group, deadline):
        raise _OcrWorkerError("OCR_WORKER_REAP_FAILED")


def _wait_ocr_worker_event(event: Any, worker: Any, deadline_monotonic: float) -> None:
    """Wait in short bounded slices so no IPC receive can overrun the deadline."""

    while True:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise _OcrWorkerError("OCR_DEADLINE")
        if event.wait(min(remaining, 0.01)):
            return
        if not worker.is_alive():
            raise _OcrWorkerError("OCR_WORKER_ERROR")


def _run_bounded_ocr_process(
    pixels: np.ndarray,
    engine: OcrEngine,
    psms: tuple[int, ...],
    deadline_monotonic: float,
) -> tuple[str, ...]:
    """Run one crop under a monotonic deadline; unsupported engines fail closed."""

    if not callable(engine):
        raise _OcrWorkerError("OCR_ENGINE_UNSUPPORTED")
    try:
        pickle.dumps(engine)
    except Exception:
        raise _OcrWorkerError("OCR_ENGINE_UNSUPPORTED") from None
    execution_deadline = deadline_monotonic - _OCR_CLEANUP_RESERVE_SECONDS
    if execution_deadline <= time.monotonic():
        raise _OcrWorkerError("OCR_DEADLINE")
    if os.name != "nt" and not Path("/proc/self/stat").is_file():
        raise _OcrWorkerError("OCR_WORKER_UNSUPPORTED")
    context = multiprocessing.get_context("spawn")
    ready_event = context.Event()
    run_event = context.Event()
    done_event = context.Event()
    result_file = tempfile.NamedTemporaryFile(prefix="semantic-ocr-", suffix=".result", delete=False)
    result_path = result_file.name
    result_file.close()
    try:
        os.unlink(result_path)
    except OSError:
        pass
    worker = context.Process(
        target=_ocr_worker_entry,
        args=(
            ready_event,
            run_event,
            done_event,
            result_path,
            np.ascontiguousarray(pixels),
            engine,
            psms,
        ),
        name="semantic-ocr-worker",
    )
    worker.daemon = False
    job = None
    process_group = None
    try:
        try:
            worker.start()
        except (AttributeError, OSError, TypeError, ValueError):
            raise _OcrWorkerError("OCR_ENGINE_UNSUPPORTED") from None
        pid = int(worker.pid or 0)
        _wait_ocr_worker_event(ready_event, worker, execution_deadline)
        if os.name == "nt":
            job = _create_windows_ocr_job(pid)
        else:
            process_group = os.getpgid(pid)
            if process_group != pid or process_group == os.getpgrp():
                raise _OcrWorkerError("OCR_WORKER_UNSUPPORTED")
        run_event.set()
        _wait_ocr_worker_event(done_event, worker, execution_deadline)
        if not worker.is_alive():
            raise _OcrWorkerError("OCR_WORKER_ERROR")
        if time.monotonic() >= execution_deadline:
            raise _OcrWorkerError("OCR_DEADLINE")
        if worker.exitcode not in (0, None):
            raise _OcrWorkerError("OCR_WORKER_ERROR")
        try:
            payload = Path(result_path).read_bytes()
            if len(payload) > _MAX_OCR_WORKER_RESULT_BYTES:
                raise ValueError("OCR worker result is too large")
            message = pickle.loads(payload)
        except (OSError, EOFError, TypeError, ValueError, pickle.PickleError):
            raise _OcrWorkerError("OCR_WORKER_ERROR") from None
        if time.monotonic() >= execution_deadline:
            raise _OcrWorkerError("OCR_DEADLINE")
        if not isinstance(message, tuple) or not message:
            raise _OcrWorkerError("OCR_WORKER_ERROR")
        if message[0] == "interrupt":
            raise KeyboardInterrupt
        if message[0] == "error":
            raise _OcrWorkerError("OCR_ENGINE_ERROR")
        if message[0] == "unsupported":
            raise _OcrWorkerError("OCR_WORKER_UNSUPPORTED")
        if message[0] != "result" or len(message) != 2 or not isinstance(message[1], tuple):
            raise _OcrWorkerError("OCR_WORKER_ERROR")
        if any(not isinstance(item, str) for item in message[1]):
            raise _OcrWorkerError("OCR_WORKER_ERROR")
        return message[1]
    finally:
        try:
            if worker.pid is not None:
                _terminate_and_reap_ocr_worker(worker, job, deadline_monotonic, process_group)
        finally:
            _close_windows_ocr_job(job)
            try:
                os.unlink(result_path)
            except OSError:
                pass


def _psms_for_mode(mode: OcrMode) -> tuple[int, ...]:
    if not isinstance(mode, OcrMode):
        raise SemanticOcrCropError("UNKNOWN_OCR_MODE")
    try:
        return _OCR_MODE_PSMS[mode]
    except KeyError as exc:
        raise SemanticOcrCropError("UNKNOWN_OCR_MODE", str(mode)) from exc


def _debug_artifact_basename(identity: NativeFrameIdentity, effective_roi: Box, ocr_mode: OcrMode) -> str:
    material = "|".join(
        (
            identity.capture_kind,
            identity.runtime_session_id,
            str(identity.capture_ordinal),
            identity.transport_sha256,
            identity.semantic_sha256,
            ",".join(str(value) for value in effective_roi),
            ocr_mode.value,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    x0, y0, x1, y1 = effective_roi
    return f"ocr-crop-{identity.capture_ordinal}-{x0}_{y0}_{x1}_{y1}-{ocr_mode.value}-{digest}.png"


def _write_debug_artifact(path: Path, image: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, payload = cv2.imencode(".png", image)
    if not ok:
        raise SemanticOcrCropError("DEBUG_ARTIFACT_ENCODE_FAILED")
    data = payload.tobytes()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def prepare_ocr_crop(
    frame: np.ndarray,
    request: CropRoiRequest,
    *,
    normalization: tuple[NormalizationOp, ...] = (),
) -> tuple[CropProvenance, np.ndarray]:
    """Validate identity binding, ROI, padding, and masks; return provenance plus ephemeral pixels.

    The returned ndarray is for immediate OCR only and must not be retained on observations.
    """

    if not isinstance(request, CropRoiRequest):
        raise SemanticOcrCropError("INVALID_REQUEST")
    validated_normalization = _validate_normalization_plan(normalization)
    identity = request.source_frame
    transport = _validate_identity_against_frame(frame, identity)
    exclusion_boxes = _validate_masks_in_frame(identity, request.exclusion_masks)
    effective = _resolve_effective_roi(identity, request.roi, request.padding, exclusion_boxes)
    x0, y0, x1, y1 = effective
    crop = np.ascontiguousarray(frame[y0:y1, x0:x1].copy())
    normalized = _apply_normalization(crop, validated_normalization)
    provenance = CropProvenance(
        source_frame=identity,
        requested_roi=request.roi,
        effective_roi=effective,
        padding=request.padding.as_tuple(),
        exclusion_masks=exclusion_boxes,
        normalization=validated_normalization,
        transport_sha256=transport,
        semantic_sha256=identity.semantic_sha256,
    )
    return provenance, normalized


def run_semantic_ocr(
    frame: np.ndarray,
    request: CropRoiRequest,
    *,
    normalization: tuple[NormalizationOp, ...] = (
        NormalizationOp.TO_GRAYSCALE,
        NormalizationOp.UPSCALE_3X,
    ),
    ocr_engine: OcrEngine | None = None,
    enable_debug_artifacts: bool = False,
    debug_dir: Path | str | None = None,
) -> SemanticOcrObservation:
    """Run bounded OCR on the request's identity-bound crop; never authorizes dispatch."""

    if not isinstance(request, CropRoiRequest):
        raise SemanticOcrCropError("INVALID_REQUEST")
    mode = request.ocr_mode if isinstance(request.ocr_mode, OcrMode) else OcrMode.UNIFORM_BLOCK
    try:
        fallback_normalization = _validate_normalization_plan(normalization)
    except SemanticOcrCropError:
        fallback_normalization = ()

    def invalid_observation(reason_code: str) -> SemanticOcrObservation:
        return SemanticOcrObservation(
            source_frame=request.source_frame,
            text="",
            requested_roi=request.roi,
            effective_roi=request.roi,
            ocr_mode=mode,
            normalization=fallback_normalization,
            exclusion_masks=tuple(mask.box for mask in request.exclusion_masks),
            padding=request.padding.as_tuple(),
            status=ObservationStatus.INVALID,
            reason_code=reason_code,
            confidence=0.0,
            supporting_evidence=(reason_code,),
        )

    def unknown_observation(reason_code: str) -> SemanticOcrObservation:
        return SemanticOcrObservation(
            source_frame=request.source_frame,
            text="",
            requested_roi=request.roi,
            effective_roi=request.roi,
            ocr_mode=mode,
            normalization=fallback_normalization,
            exclusion_masks=tuple(mask.box for mask in request.exclusion_masks),
            padding=request.padding.as_tuple(),
            status=ObservationStatus.UNKNOWN,
            reason_code=reason_code,
            confidence=0.0,
            supporting_evidence=(reason_code,),
        )

    try:
        if request.ocr_mode is None:
            raise SemanticOcrCropError("UNKNOWN_OCR_MODE")
        if request.deadline_monotonic is None:
            raise SemanticOcrCropError("INVALID_DEADLINE")
        if enable_debug_artifacts and debug_dir is None:
            raise SemanticOcrCropError("DEBUG_DIR_REQUIRED")
        if debug_dir is not None and not enable_debug_artifacts:
            raise SemanticOcrCropError("DEBUG_NOT_ENABLED")
        psms = _psms_for_mode(request.ocr_mode)
        if request.deadline_monotonic <= time.monotonic():
            return unknown_observation("OCR_DEADLINE")
        provenance, pixels = prepare_ocr_crop(frame, request, normalization=normalization)
        texts = _run_bounded_ocr_process(
            pixels,
            ocr_engine or _default_ocr_engine,
            psms,
            request.deadline_monotonic,
        )
        if time.monotonic() >= request.deadline_monotonic:
            return unknown_observation("OCR_DEADLINE")
        combined = " ".join(part.strip() for part in texts if part and str(part).strip()).strip()
        debug_name: str | None = None
        debug_sha: str | None = None
        if enable_debug_artifacts:
            assert debug_dir is not None
            debug_name = _debug_artifact_basename(request.source_frame, provenance.effective_roi, mode)
            debug_sha = _write_debug_artifact(Path(debug_dir) / debug_name, pixels)
        if not combined:
            return SemanticOcrObservation(
                source_frame=request.source_frame,
                text="",
                requested_roi=provenance.requested_roi,
                effective_roi=provenance.effective_roi,
                ocr_mode=mode,
                normalization=provenance.normalization,
                exclusion_masks=provenance.exclusion_masks,
                padding=provenance.padding,
                status=ObservationStatus.UNKNOWN,
                reason_code="OCR_EMPTY",
                confidence=0.0,
                supporting_evidence=("empty_ocr",),
                debug_artifact_name=debug_name,
                debug_artifact_sha256=debug_sha,
            )
        return SemanticOcrObservation(
            source_frame=request.source_frame,
            text=combined,
            requested_roi=provenance.requested_roi,
            effective_roi=provenance.effective_roi,
            ocr_mode=mode,
            normalization=provenance.normalization,
            exclusion_masks=provenance.exclusion_masks,
            padding=provenance.padding,
            status=ObservationStatus.OK,
            reason_code="ok",
            confidence=1.0 if len(psms) == 1 else 0.99,
            supporting_evidence=(f"ocr_mode:{mode.value}",),
            debug_artifact_name=debug_name,
            debug_artifact_sha256=debug_sha,
        )
    except _OcrWorkerError as exc:
        if exc.reason_code == "OCR_DEADLINE":
            return unknown_observation("OCR_DEADLINE")
        return invalid_observation(exc.reason_code)
    except SemanticOcrCropError as exc:
        return invalid_observation(exc.reason_code)
    except PerceptionBundleError as exc:
        return invalid_observation(getattr(exc, "reason_code", "INVALID_IDENTITY"))


def ambiguous_observation(
    source_frame: NativeFrameIdentity,
    *,
    requested_roi: Box,
    effective_roi: Box,
    ocr_mode: OcrMode,
    reason_code: str,
    text: str = "",
    normalization: tuple[NormalizationOp, ...] = (),
    exclusion_masks: tuple[Box, ...] = (),
    padding: tuple[int, int, int, int] = (0, 0, 0, 0),
    supporting_evidence: tuple[str, ...] = (),
) -> SemanticOcrObservation:
    """Explicit negative-control helper for ambiguous OCR without inventing authoritative text."""

    return SemanticOcrObservation(
        source_frame=source_frame,
        text=text,
        requested_roi=requested_roi,
        effective_roi=effective_roi,
        ocr_mode=ocr_mode,
        normalization=tuple(normalization),
        exclusion_masks=tuple(exclusion_masks),
        padding=padding,
        status=ObservationStatus.AMBIGUOUS,
        reason_code=reason_code,
        confidence=0.0,
        supporting_evidence=supporting_evidence or (reason_code,),
    )


def to_immutable_ocr_observation(observation: SemanticOcrObservation) -> ImmutableOcrObservation:
    """Project a successful OCR observation into the perception-bundle OCR snapshot."""

    if observation.status is not ObservationStatus.OK:
        raise SemanticOcrCropError("OBSERVATION_NOT_OK", observation.reason_code)
    return ImmutableOcrObservation(
        source_frame=observation.source_frame,
        text=observation.text,
        roi=observation.effective_roi,
        confidence=observation.confidence,
        supporting_evidence=observation.supporting_evidence,
    )


def observation_grants_dispatch(_observation: SemanticOcrObservation) -> bool:
    """OCR never grants dispatch authority."""

    return False
