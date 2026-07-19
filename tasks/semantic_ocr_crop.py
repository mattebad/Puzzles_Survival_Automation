"""Shared frame-identity-bound semantic OCR crop pipeline.

Every crop and OCR observation is bound to a complete NativeFrameIdentity (capture event,
transport digest, and semantic digest). Recognition never authorizes transport or dispatch.
Debug crop artifacts are disabled by default and, when enabled, are deterministic and temporary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from numbers import Integral
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Tuple

import cv2
import numpy as np

from tasks.perception_bundle import ImmutableOcrObservation, NativeFrameIdentity, PerceptionBundleError


SCHEMA_NAME = "semantic_ocr_crop"
SCHEMA_VERSION = 1

Box = Tuple[int, int, int, int]
OcrEngine = Callable[[np.ndarray, int], str]

MAX_PADDING_PX = 64
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
    """Controlled native full-frame ROI request bound to one capture identity."""

    source_frame: NativeFrameIdentity
    roi: Box
    padding: PaddingSpec = PaddingSpec()
    exclusion_masks: tuple[ExclusionMask, ...] = ()

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
    metadata: Mapping[str, str] = MappingProxyType({})

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
    ocr_mode: OcrMode,
    normalization: tuple[NormalizationOp, ...] = (NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_3X),
    ocr_engine: OcrEngine | None = None,
    enable_debug_artifacts: bool = False,
    debug_dir: Path | str | None = None,
) -> SemanticOcrObservation:
    """Run constrained OCR on an identity-bound crop. Never authorizes dispatch."""

    if not isinstance(request, CropRoiRequest):
        raise SemanticOcrCropError("INVALID_REQUEST")
    fallback_mode = ocr_mode if isinstance(ocr_mode, OcrMode) else OcrMode.UNIFORM_BLOCK
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
            ocr_mode=fallback_mode,
            normalization=fallback_normalization,
            exclusion_masks=tuple(mask.box for mask in request.exclusion_masks),
            padding=request.padding.as_tuple(),
            status=ObservationStatus.INVALID,
            reason_code=reason_code,
            confidence=0.0,
            supporting_evidence=(reason_code,),
        )

    try:
        if enable_debug_artifacts and debug_dir is None:
            raise SemanticOcrCropError("DEBUG_DIR_REQUIRED")
        if debug_dir is not None and not enable_debug_artifacts:
            raise SemanticOcrCropError("DEBUG_NOT_ENABLED")
        psms = _psms_for_mode(ocr_mode)
        provenance, pixels = prepare_ocr_crop(frame, request, normalization=normalization)
        engine = ocr_engine or _default_ocr_engine
        texts: list[str] = []
        try:
            for psm in psms:
                texts.append(str(engine(pixels, psm)))
        except Exception:
            return invalid_observation("OCR_ENGINE_ERROR")
        combined = " ".join(part.strip() for part in texts if part and str(part).strip()).strip()
        debug_name: str | None = None
        debug_sha: str | None = None
        if enable_debug_artifacts:
            assert debug_dir is not None
            debug_name = _debug_artifact_basename(
                request.source_frame,
                provenance.effective_roi,
                ocr_mode,
            )
            debug_path = Path(debug_dir) / debug_name
            debug_sha = _write_debug_artifact(debug_path, pixels)
        if not combined:
            return SemanticOcrObservation(
                source_frame=request.source_frame,
                text="",
                requested_roi=provenance.requested_roi,
                effective_roi=provenance.effective_roi,
                ocr_mode=ocr_mode,
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
            ocr_mode=ocr_mode,
            normalization=provenance.normalization,
            exclusion_masks=provenance.exclusion_masks,
            padding=provenance.padding,
            status=ObservationStatus.OK,
            reason_code="ok",
            confidence=1.0 if len(psms) == 1 else 0.99,
            supporting_evidence=(f"ocr_mode:{ocr_mode.value}",),
            debug_artifact_name=debug_name,
            debug_artifact_sha256=debug_sha,
        )
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
