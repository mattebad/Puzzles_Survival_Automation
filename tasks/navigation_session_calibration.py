"""Strictly bounded session-local BlueStacks gesture calibration adaptation.

Preserves an immutable original GestureCalibration baseline, computes an effective
session-local calibration without modifying or persisting the source, and records
every considered measurement with exact acceptance or rejection reasons.

This module grants no capability, transport, or dispatch authority. Serialization
never authorizes persistence. Bliss calibration remains completely separate.
CONFIRMED_NOT_DISPATCHED stays unavailable via NON_DISPATCH_AUTHORITY_UNAVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tasks.home_atlas_planner import GestureCalibration
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID
from tasks.navigation_observability import NavigationObservabilityReport, report_navigation_session
from tasks.navigation_session import (
    NavigationCheckpoint,
    NavigationSession,
    NavigationSessionError,
    TrustedTransportNonDispatchAuthority,
    UncertainPreparedResolution,
)


SCHEMA_NAME = "navigation_session_calibration"
SCHEMA_VERSION = 1

BLISS_REJECTED_PLATFORM = "Bliss OS"
BLISS_REJECTED_PROFILE_ID = "pns-800x1280-v1"

# Explicit deterministic adaptation limits (session-local only).
MAX_PER_MEASUREMENT_INFLUENCE = 0.15
MAX_PER_ADJUSTMENT_SCALE = 0.25
MAX_TOTAL_DRIFT = 0.35
MAX_DIRECTIONAL_SKEW = 0.20
MAX_ACCEPTED_ADJUSTMENTS = 4
MAX_EVIDENCE_COUNT = 16
MAX_MEASUREMENT_AGE_PANS = 8
OUTLIER_TOLERANCE_RATIO = 0.40
MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG = 0.5
MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG = 5.0
MIN_COMPONENT_ABS = 1.0e-9

REPORT_FIELD_ORDER: tuple[str, ...] = (
    "schema_name",
    "schema_version",
    "navigation_session_id",
    "platform",
    "profile_id",
    "calibration_id",
    "original_calibration",
    "effective_calibration",
    "effective_revision",
    "adaptation_status",
    "accepted_adjustment_count",
    "considered_measurement_count",
    "rejected_measurement_count",
    "rejection_reason_counts",
    "bounded_drift",
    "revision_history",
    "considerations",
    "persistence_authorized",
    "authorize_dispatch",
    "capability_grant",
    "non_dispatch_authority",
    "observability_integration",
)

_CONSTRUCTION_TOKEN = object()

Point = tuple[float, float]
Box = tuple[int, int, int, int]

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "platform",
    "profile_id",
    "calibration_id",
    "revision",
    "drag_origin",
    "drag_bounds",
    "camera_px_per_drag_x",
    "camera_px_per_drag_y",
    "minimum_drag_px",
    "maximum_drag_x",
    "maximum_drag_y",
    "minimum_progress_px",
    "wrong_direction_tolerance_px",
)
_PROPOSED_FIELDS: tuple[str, ...] = (
    "delta_camera_px_per_drag_x",
    "delta_camera_px_per_drag_y",
    "influence",
    "estimated_camera_px_per_drag_x",
    "estimated_camera_px_per_drag_y",
)
_ACCEPTED_FIELDS: tuple[str, ...] = (
    "revision",
    "pan_ordinal",
    "event_ordinal",
    "chronology_ordinal",
    "delta_camera_px_per_drag_x",
    "delta_camera_px_per_drag_y",
    "camera_px_per_drag_x_after",
    "camera_px_per_drag_y_after",
    "influence",
    "source_checkpoint",
    "destination_checkpoint",
)
_MEASUREMENT_FIELDS: tuple[str, ...] = (
    "navigation_session_id",
    "platform",
    "profile_id",
    "calibration_id",
    "calibration_revision",
    "source_checkpoint",
    "destination_checkpoint",
    "pan_ordinal",
    "event_ordinal",
    "chronology_ordinal",
    "requested",
    "predicted",
    "measured",
    "progress_px",
    "progress_reason",
    "localization_recognized",
    "localization_ambiguous",
    "stale",
    "repeated_viewport",
    "camera_map_clamp",
    "pan_limit_reached",
    "source_capture_ordinal",
    "destination_capture_ordinal",
    "drag_vector",
    "maximum_pans",
)
_CONSIDERATION_FIELDS: tuple[str, ...] = (
    "chronology_ordinal",
    "measurement",
    "validation_accepted",
    "rejection_reason",
    "proposed_adjustment",
    "accepted_adjustment",
    "effective_revision_after",
)
_DRIFT_FIELDS: tuple[str, ...] = (
    "drift_x",
    "drift_y",
    "abs_drift_x",
    "abs_drift_y",
    "directional_skew",
    "within_limits",
)
_OBSERVABILITY_FIELDS: tuple[str, ...] = (
    "schema_name",
    "schema_version",
    "navigation_session_id",
    "report_integrity",
    "requested_present",
    "measured_present",
    "residual_present",
    "mutates_session_ledger",
)
_ALLOWED_PROGRESS_REASONS = frozenset(
    {
        "measured_progress",
        "no_measured_progress",
        "no_progress",
        "zero_progress",
        "zero_displacement",
        "movement_wrong_direction",
        "wrong_direction",
        "post_pan_localization_failed",
        "post_pan_localization_invalid",
        "repeated_viewport",
        "camera_map_edge_clamp",
        "map_edge_clamp",
        "pan_limit",
        "maximum_pans",
        "max_pans",
        "localization_failed",
        "localization_invalid",
        "ambiguous_localization",
    }
)


class SessionCalibrationError(ValueError):
    """Fail-closed session-calibration denial with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class AdaptationStatus(str, Enum):
    NONE = "none"
    ADAPTED = "adapted"
    REJECTED_ONLY = "rejected_only"
    SATURATED = "saturated"


class RejectionReason(str, Enum):
    WRONG_DIRECTION = "WRONG_DIRECTION"
    NO_PROGRESS = "NO_PROGRESS"
    PROHIBITED_NEGATIVE_OR_ZERO_PROGRESS = "PROHIBITED_NEGATIVE_OR_ZERO_PROGRESS"
    NON_FINITE = "NON_FINITE"
    BOOL_LOOKALIKE = "BOOL_LOOKALIKE"
    NUMERIC_LOOKALIKE = "NUMERIC_LOOKALIKE"
    IMPLAUSIBLE = "IMPLAUSIBLE"
    OUT_OF_BOUND = "OUT_OF_BOUND"
    OUTLIER = "OUTLIER"
    CAMERA_MAP_EDGE_CLAMP = "CAMERA_MAP_EDGE_CLAMP"
    REPEATED_VIEWPORT = "REPEATED_VIEWPORT"
    INSUFFICIENT_LOCALIZATION = "INSUFFICIENT_LOCALIZATION"
    AMBIGUOUS_LOCALIZATION = "AMBIGUOUS_LOCALIZATION"
    STALE = "STALE"
    CROSS_CAPTURE = "CROSS_CAPTURE"
    CROSS_SESSION = "CROSS_SESSION"
    CROSS_PLATFORM = "CROSS_PLATFORM"
    CROSS_PROFILE = "CROSS_PROFILE"
    CROSS_CALIBRATION = "CROSS_CALIBRATION"
    REORDERED_SAMPLE = "REORDERED_SAMPLE"
    DUPLICATE_SAMPLE = "DUPLICATE_SAMPLE"
    MISSING_SAMPLE = "MISSING_SAMPLE"
    CONTRADICTORY_SAMPLE = "CONTRADICTORY_SAMPLE"
    MAX_ACCEPTED_COUNT = "MAX_ACCEPTED_COUNT"
    MAX_TOTAL_DRIFT = "MAX_TOTAL_DRIFT"
    MAX_PER_ADJUSTMENT = "MAX_PER_ADJUSTMENT"
    MAX_EVIDENCE_COUNT = "MAX_EVIDENCE_COUNT"
    MEASUREMENT_TOO_OLD = "MEASUREMENT_TOO_OLD"
    INVALID_PROPOSED_ADJUSTMENT = "INVALID_PROPOSED_ADJUSTMENT"
    INVALID_PROGRESS_REASON = "INVALID_PROGRESS_REASON"
    DIRECTIONAL_SKEW = "DIRECTIONAL_SKEW"
    PAN_LIMIT = "PAN_LIMIT"


_ALLOWED_REJECTION_REASONS = frozenset(item.value for item in RejectionReason)
_ALLOWED_ADAPTATION_STATUSES = frozenset(item.value for item in AdaptationStatus)
_ALLOWED_CHECKPOINTS = frozenset(item.value for item in NavigationCheckpoint)
_PROGRESS_NO_PROGRESS_TOKENS = frozenset(
    {"no_measured_progress", "no_progress", "zero_displacement", "zero_progress"}
)
_PROGRESS_WRONG_DIRECTION_TOKENS = frozenset(
    {"movement_wrong_direction", "wrong_direction"}
)
_CLAMP_TOKENS = ("clamp", "map_edge")
_REPEATED_VIEWPORT_TOKENS = ("repeated_viewport",)
_LOCALIZATION_FAIL_TOKENS = (
    "localization_failed",
    "localization_invalid",
    "post_pan_localization",
)
_PAN_LIMIT_TOKENS = ("pan_limit", "maximum_pans", "max_pans")


def _require_exact_str(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise SessionCalibrationError("INVALID_STRING", field_name)
    return value


def _require_exact_int(
    value: object, field_name: str, *, minimum: int | None = None
) -> int:
    if type(value) is bool:
        raise SessionCalibrationError("BOOL_LOOKALIKE", field_name)
    if type(value) is not int:
        raise SessionCalibrationError("NUMERIC_LOOKALIKE", field_name)
    if minimum is not None and value < minimum:
        raise SessionCalibrationError("INVALID_INT", field_name)
    return value


def _require_exact_float(value: object, field_name: str) -> float:
    if type(value) is bool:
        raise SessionCalibrationError("BOOL_LOOKALIKE", field_name)
    if type(value) is not float:
        raise SessionCalibrationError("NUMERIC_LOOKALIKE", field_name)
    if not math.isfinite(value):
        raise SessionCalibrationError("NON_FINITE", field_name)
    return value


def _coerce_calibration_float(value: object, field_name: str) -> float:
    """Normalize GestureCalibration numeric fields to exact floats without bool lookalikes."""

    if type(value) is bool:
        raise SessionCalibrationError("BOOL_LOOKALIKE", field_name)
    if type(value) is float:
        if not math.isfinite(value):
            raise SessionCalibrationError("NON_FINITE", field_name)
        return value
    if type(value) is int:
        return float(value)
    raise SessionCalibrationError("NUMERIC_LOOKALIKE", field_name)


def _require_exact_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise SessionCalibrationError("INVALID_BOOL", field_name)
    return value


def _require_point(value: object, field_name: str) -> Point:
    if type(value) is not tuple or len(value) != 2:
        raise SessionCalibrationError("INVALID_POINT", field_name)
    return (
        _require_exact_float(value[0], f"{field_name}.x"),
        _require_exact_float(value[1], f"{field_name}.y"),
    )


def _require_box(value: object, field_name: str) -> Box:
    if type(value) is not tuple or len(value) != 4:
        raise SessionCalibrationError("INVALID_BOX", field_name)
    return (
        _require_exact_int(value[0], f"{field_name}.x0"),
        _require_exact_int(value[1], f"{field_name}.y0"),
        _require_exact_int(value[2], f"{field_name}.x1"),
        _require_exact_int(value[3], f"{field_name}.y1"),
    )


def _require_optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_exact_int(value, field_name, minimum=0)


def _freeze_json(value: Any, field_name: str) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise SessionCalibrationError("NON_FINITE", field_name)
        return value
    if type(value) in (dict, MappingProxyType):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise SessionCalibrationError("NON_STRING_MAPPING_KEY", field_name)
            frozen[key] = _freeze_json(item, field_name)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(_freeze_json(item, field_name) for item in value)
    raise SessionCalibrationError("NON_JSON_SAFE_VALUE", type(value).__name__)


def _plain(value: Any) -> Any:
    if type(value) is MappingProxyType:
        return {key: _plain(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain(item) for item in value]
    return value


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def calibration_identity_for(calibration: GestureCalibration) -> str:
    """Deterministic identity of an immutable original calibration snapshot."""

    if type(calibration) is not GestureCalibration:
        raise SessionCalibrationError("INVALID_CALIBRATION_TYPE")
    payload = {
        "platform": calibration.platform,
        "profile_id": calibration.profile_id,
        "drag_origin": [calibration.drag_origin[0], calibration.drag_origin[1]],
        "drag_bounds": [
            calibration.drag_bounds[0],
            calibration.drag_bounds[1],
            calibration.drag_bounds[2],
            calibration.drag_bounds[3],
        ],
        "camera_px_per_drag_x": _coerce_calibration_float(
            calibration.camera_px_per_drag_x, "camera_px_per_drag_x"
        ),
        "camera_px_per_drag_y": _coerce_calibration_float(
            calibration.camera_px_per_drag_y, "camera_px_per_drag_y"
        ),
        "minimum_drag_px": _coerce_calibration_float(
            calibration.minimum_drag_px, "minimum_drag_px"
        ),
        "maximum_drag_x": _coerce_calibration_float(
            calibration.maximum_drag_x, "maximum_drag_x"
        ),
        "maximum_drag_y": _coerce_calibration_float(
            calibration.maximum_drag_y, "maximum_drag_y"
        ),
        "minimum_progress_px": _coerce_calibration_float(
            calibration.minimum_progress_px, "minimum_progress_px"
        ),
        "wrong_direction_tolerance_px": _coerce_calibration_float(
            calibration.wrong_direction_tolerance_px,
            "wrong_direction_tolerance_px",
        ),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _snapshot_from_gesture(
    calibration: GestureCalibration,
    *,
    calibration_id: str,
    revision: int,
) -> "CalibrationSnapshot":
    return CalibrationSnapshot(
        platform=_require_exact_str(calibration.platform, "platform"),
        profile_id=_require_exact_str(calibration.profile_id, "profile_id"),
        calibration_id=_require_exact_str(calibration_id, "calibration_id"),
        revision=_require_exact_int(revision, "revision", minimum=0),
        drag_origin=(
            _require_exact_int(calibration.drag_origin[0], "drag_origin.x"),
            _require_exact_int(calibration.drag_origin[1], "drag_origin.y"),
        ),
        drag_bounds=_require_box(tuple(calibration.drag_bounds), "drag_bounds"),
        camera_px_per_drag_x=_coerce_calibration_float(
            calibration.camera_px_per_drag_x, "camera_px_per_drag_x"
        ),
        camera_px_per_drag_y=_coerce_calibration_float(
            calibration.camera_px_per_drag_y, "camera_px_per_drag_y"
        ),
        minimum_drag_px=_coerce_calibration_float(
            calibration.minimum_drag_px, "minimum_drag_px"
        ),
        maximum_drag_x=_coerce_calibration_float(
            calibration.maximum_drag_x, "maximum_drag_x"
        ),
        maximum_drag_y=_coerce_calibration_float(
            calibration.maximum_drag_y, "maximum_drag_y"
        ),
        minimum_progress_px=_coerce_calibration_float(
            calibration.minimum_progress_px, "minimum_progress_px"
        ),
        wrong_direction_tolerance_px=_coerce_calibration_float(
            calibration.wrong_direction_tolerance_px,
            "wrong_direction_tolerance_px",
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


@dataclass(frozen=True)
class CalibrationSnapshot:
    platform: str
    profile_id: str
    calibration_id: str
    revision: int
    drag_origin: tuple[int, int]
    drag_bounds: Box
    camera_px_per_drag_x: float
    camera_px_per_drag_y: float
    minimum_drag_px: float
    maximum_drag_x: float
    maximum_drag_y: float
    minimum_progress_px: float
    wrong_direction_tolerance_px: float
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            raise SessionCalibrationError("UNTRUSTED_CALIBRATION_SNAPSHOT")
        _require_exact_str(self.platform, "platform")
        _require_exact_str(self.profile_id, "profile_id")
        _require_exact_str(self.calibration_id, "calibration_id")
        _require_exact_int(self.revision, "revision", minimum=0)
        if type(self.drag_origin) is not tuple or len(self.drag_origin) != 2:
            raise SessionCalibrationError("INVALID_DRAG_ORIGIN")
        _require_exact_int(self.drag_origin[0], "drag_origin.x")
        _require_exact_int(self.drag_origin[1], "drag_origin.y")
        object.__setattr__(self, "drag_bounds", _require_box(self.drag_bounds, "drag_bounds"))
        for name in (
            "camera_px_per_drag_x",
            "camera_px_per_drag_y",
            "minimum_drag_px",
            "maximum_drag_x",
            "maximum_drag_y",
            "minimum_progress_px",
            "wrong_direction_tolerance_px",
        ):
            _require_exact_float(getattr(self, name), name)
        if self.camera_px_per_drag_x <= 0.0 or self.camera_px_per_drag_y <= 0.0:
            raise SessionCalibrationError("UNCALIBRATED_SCALE")
        if (
            self.minimum_drag_px <= 0.0
            or self.maximum_drag_x < self.minimum_drag_px
            or self.maximum_drag_y < self.minimum_drag_px
        ):
            raise SessionCalibrationError("INVALID_GESTURE_BOUNDS")
        _validate_snapshot(self, "calibration_snapshot", require_identity=False)

    def to_gesture_calibration(self) -> GestureCalibration:
        return GestureCalibration(
            platform=self.platform,
            profile_id=self.profile_id,
            drag_origin=self.drag_origin,
            drag_bounds=self.drag_bounds,
            camera_px_per_drag_x=self.camera_px_per_drag_x,
            camera_px_per_drag_y=self.camera_px_per_drag_y,
            minimum_drag_px=self.minimum_drag_px,
            maximum_drag_x=self.maximum_drag_x,
            maximum_drag_y=self.maximum_drag_y,
            minimum_progress_px=self.minimum_progress_px,
            wrong_direction_tolerance_px=self.wrong_direction_tolerance_px,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "profile_id": self.profile_id,
            "calibration_id": self.calibration_id,
            "revision": self.revision,
            "drag_origin": [self.drag_origin[0], self.drag_origin[1]],
            "drag_bounds": [
                self.drag_bounds[0],
                self.drag_bounds[1],
                self.drag_bounds[2],
                self.drag_bounds[3],
            ],
            "camera_px_per_drag_x": self.camera_px_per_drag_x,
            "camera_px_per_drag_y": self.camera_px_per_drag_y,
            "minimum_drag_px": self.minimum_drag_px,
            "maximum_drag_x": self.maximum_drag_x,
            "maximum_drag_y": self.maximum_drag_y,
            "minimum_progress_px": self.minimum_progress_px,
            "wrong_direction_tolerance_px": self.wrong_direction_tolerance_px,
        }


@dataclass(frozen=True)
class ProposedAdjustment:
    delta_camera_px_per_drag_x: float
    delta_camera_px_per_drag_y: float
    influence: float
    estimated_camera_px_per_drag_x: float
    estimated_camera_px_per_drag_y: float

    def __post_init__(self) -> None:
        for name in (
            "delta_camera_px_per_drag_x",
            "delta_camera_px_per_drag_y",
            "influence",
            "estimated_camera_px_per_drag_x",
            "estimated_camera_px_per_drag_y",
        ):
            _require_exact_float(getattr(self, name), name)
        _validate_proposed_adjustment(self, "proposed_adjustment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_camera_px_per_drag_x": self.delta_camera_px_per_drag_x,
            "delta_camera_px_per_drag_y": self.delta_camera_px_per_drag_y,
            "influence": self.influence,
            "estimated_camera_px_per_drag_x": self.estimated_camera_px_per_drag_x,
            "estimated_camera_px_per_drag_y": self.estimated_camera_px_per_drag_y,
        }


@dataclass(frozen=True)
class AcceptedAdjustment:
    revision: int
    pan_ordinal: int
    event_ordinal: int
    chronology_ordinal: int
    delta_camera_px_per_drag_x: float
    delta_camera_px_per_drag_y: float
    camera_px_per_drag_x_after: float
    camera_px_per_drag_y_after: float
    influence: float
    source_checkpoint: str
    destination_checkpoint: str

    def __post_init__(self) -> None:
        for name in ("revision", "pan_ordinal", "event_ordinal", "chronology_ordinal"):
            _require_exact_int(getattr(self, name), name, minimum=0)
        for name in (
            "delta_camera_px_per_drag_x",
            "delta_camera_px_per_drag_y",
            "camera_px_per_drag_x_after",
            "camera_px_per_drag_y_after",
            "influence",
        ):
            _require_exact_float(getattr(self, name), name)
        _require_exact_str(self.source_checkpoint, "source_checkpoint")
        _require_exact_str(self.destination_checkpoint, "destination_checkpoint")
        if self.source_checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", "source_checkpoint")
        if self.destination_checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", "destination_checkpoint")
        _validate_accepted_adjustment(self, "accepted_adjustment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "pan_ordinal": self.pan_ordinal,
            "event_ordinal": self.event_ordinal,
            "chronology_ordinal": self.chronology_ordinal,
            "delta_camera_px_per_drag_x": self.delta_camera_px_per_drag_x,
            "delta_camera_px_per_drag_y": self.delta_camera_px_per_drag_y,
            "camera_px_per_drag_x_after": self.camera_px_per_drag_x_after,
            "camera_px_per_drag_y_after": self.camera_px_per_drag_y_after,
            "influence": self.influence,
            "source_checkpoint": self.source_checkpoint,
            "destination_checkpoint": self.destination_checkpoint,
        }


@dataclass(frozen=True)
class SessionCalibrationMeasurement:
    """One offline measured pan sample bound to session/calibration identity."""

    navigation_session_id: str
    platform: str
    profile_id: str
    calibration_id: str
    calibration_revision: int
    source_checkpoint: str
    destination_checkpoint: str
    pan_ordinal: int
    event_ordinal: int
    chronology_ordinal: int
    requested: Point
    predicted: Point
    measured: Point
    progress_px: float
    progress_reason: str
    localization_recognized: bool
    localization_ambiguous: bool
    stale: bool
    repeated_viewport: bool
    camera_map_clamp: bool
    pan_limit_reached: bool
    source_capture_ordinal: int | None = None
    destination_capture_ordinal: int | None = None
    drag_vector: Point | None = None
    maximum_pans: int | None = None

    def __post_init__(self) -> None:
        _require_exact_str(self.navigation_session_id, "navigation_session_id")
        _require_exact_str(self.platform, "platform")
        _require_exact_str(self.profile_id, "profile_id")
        _require_exact_str(self.calibration_id, "calibration_id")
        _require_exact_int(self.calibration_revision, "calibration_revision", minimum=0)
        _require_exact_str(self.source_checkpoint, "source_checkpoint")
        _require_exact_str(self.destination_checkpoint, "destination_checkpoint")
        if self.source_checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", "source_checkpoint")
        if self.destination_checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", "destination_checkpoint")
        for name in ("pan_ordinal", "event_ordinal", "chronology_ordinal"):
            _require_exact_int(getattr(self, name), name, minimum=0)
        object.__setattr__(self, "requested", _require_point(self.requested, "requested"))
        object.__setattr__(self, "predicted", _require_point(self.predicted, "predicted"))
        object.__setattr__(self, "measured", _require_point(self.measured, "measured"))
        _require_exact_float(self.progress_px, "progress_px")
        _require_exact_str(self.progress_reason, "progress_reason")
        for name in (
            "localization_recognized",
            "localization_ambiguous",
            "stale",
            "repeated_viewport",
            "camera_map_clamp",
            "pan_limit_reached",
        ):
            _require_exact_bool(getattr(self, name), name)
        object.__setattr__(
            self,
            "source_capture_ordinal",
            _require_optional_int(self.source_capture_ordinal, "source_capture_ordinal"),
        )
        object.__setattr__(
            self,
            "destination_capture_ordinal",
            _require_optional_int(
                self.destination_capture_ordinal, "destination_capture_ordinal"
            ),
        )
        if self.drag_vector is not None:
            object.__setattr__(self, "drag_vector", _require_point(self.drag_vector, "drag_vector"))
        if self.maximum_pans is not None:
            object.__setattr__(
                self,
                "maximum_pans",
                _require_exact_int(self.maximum_pans, "maximum_pans", minimum=1),
            )
        _validate_measurement(self, "measurement")

    def to_dict(self) -> dict[str, Any]:
        return {
            "navigation_session_id": self.navigation_session_id,
            "platform": self.platform,
            "profile_id": self.profile_id,
            "calibration_id": self.calibration_id,
            "calibration_revision": self.calibration_revision,
            "source_checkpoint": self.source_checkpoint,
            "destination_checkpoint": self.destination_checkpoint,
            "pan_ordinal": self.pan_ordinal,
            "event_ordinal": self.event_ordinal,
            "chronology_ordinal": self.chronology_ordinal,
            "requested": [self.requested[0], self.requested[1]],
            "predicted": [self.predicted[0], self.predicted[1]],
            "measured": [self.measured[0], self.measured[1]],
            "progress_px": self.progress_px,
            "progress_reason": self.progress_reason,
            "localization_recognized": self.localization_recognized,
            "localization_ambiguous": self.localization_ambiguous,
            "stale": self.stale,
            "repeated_viewport": self.repeated_viewport,
            "camera_map_clamp": self.camera_map_clamp,
            "pan_limit_reached": self.pan_limit_reached,
            "source_capture_ordinal": self.source_capture_ordinal,
            "destination_capture_ordinal": self.destination_capture_ordinal,
            "drag_vector": (
                None
                if self.drag_vector is None
                else [self.drag_vector[0], self.drag_vector[1]]
            ),
            "maximum_pans": self.maximum_pans,
        }


@dataclass(frozen=True)
class MeasurementConsideration:
    chronology_ordinal: int
    measurement: SessionCalibrationMeasurement
    validation_accepted: bool
    rejection_reason: str | None
    proposed_adjustment: ProposedAdjustment | None
    accepted_adjustment: AcceptedAdjustment | None
    effective_revision_after: int
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            raise SessionCalibrationError("UNTRUSTED_MEASUREMENT_CONSIDERATION")
        _require_exact_int(self.chronology_ordinal, "chronology_ordinal", minimum=0)
        if type(self.measurement) is not SessionCalibrationMeasurement:
            raise SessionCalibrationError("INVALID_MEASUREMENT")
        _require_exact_bool(self.validation_accepted, "validation_accepted")
        if self.rejection_reason is not None:
            _require_exact_str(self.rejection_reason, "rejection_reason")
            if self.rejection_reason not in _ALLOWED_REJECTION_REASONS:
                raise SessionCalibrationError("INVALID_REJECTION_REASON")
        if self.validation_accepted:
            if self.rejection_reason is not None:
                raise SessionCalibrationError("CONTRADICTORY_CONSIDERATION")
            if type(self.accepted_adjustment) is not AcceptedAdjustment:
                raise SessionCalibrationError("MISSING_ACCEPTED_ADJUSTMENT")
        else:
            if self.rejection_reason is None:
                raise SessionCalibrationError("MISSING_REJECTION_REASON")
            if self.accepted_adjustment is not None:
                raise SessionCalibrationError("CONTRADICTORY_CONSIDERATION")
        if self.proposed_adjustment is not None and type(self.proposed_adjustment) is not ProposedAdjustment:
            raise SessionCalibrationError("INVALID_PROPOSED_ADJUSTMENT")
        _require_exact_int(self.effective_revision_after, "effective_revision_after", minimum=0)
        _validate_consideration(self, "measurement_consideration")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chronology_ordinal": self.chronology_ordinal,
            "measurement": self.measurement.to_dict(),
            "validation_accepted": self.validation_accepted,
            "rejection_reason": self.rejection_reason,
            "proposed_adjustment": (
                None if self.proposed_adjustment is None else self.proposed_adjustment.to_dict()
            ),
            "accepted_adjustment": (
                None if self.accepted_adjustment is None else self.accepted_adjustment.to_dict()
            ),
            "effective_revision_after": self.effective_revision_after,
        }


@dataclass(frozen=True)
class BoundedDriftReport:
    drift_x: float
    drift_y: float
    abs_drift_x: float
    abs_drift_y: float
    directional_skew: float
    within_limits: bool

    def __post_init__(self) -> None:
        for name in ("drift_x", "drift_y", "abs_drift_x", "abs_drift_y", "directional_skew"):
            _require_exact_float(getattr(self, name), name)
        _require_exact_bool(self.within_limits, "within_limits")
        _validate_drift(self, "bounded_drift")

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_x": self.drift_x,
            "drift_y": self.drift_y,
            "abs_drift_x": self.abs_drift_x,
            "abs_drift_y": self.abs_drift_y,
            "directional_skew": self.directional_skew,
            "within_limits": self.within_limits,
        }


@dataclass(frozen=True)
class SessionCalibrationState:
    """Immutable session-local adaptation state over one original calibration."""

    navigation_session_id: str
    platform: str
    profile_id: str
    calibration_id: str
    original: CalibrationSnapshot
    effective: CalibrationSnapshot
    considerations: tuple[MeasurementConsideration, ...]
    accepted_adjustments: tuple[AcceptedAdjustment, ...]
    revision_history: tuple[int, ...]
    adaptation_status: str
    next_chronology_ordinal: int
    last_pan_ordinal: int | None
    last_event_ordinal: int | None
    expected_chronology_ordinal: int
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            raise SessionCalibrationError("UNTRUSTED_SESSION_CALIBRATION_STATE")
        _require_exact_str(self.navigation_session_id, "navigation_session_id")
        _require_exact_str(self.platform, "platform")
        _require_exact_str(self.profile_id, "profile_id")
        _require_exact_str(self.calibration_id, "calibration_id")
        if type(self.original) is not CalibrationSnapshot:
            raise SessionCalibrationError("INVALID_ORIGINAL_SNAPSHOT")
        if type(self.effective) is not CalibrationSnapshot:
            raise SessionCalibrationError("INVALID_EFFECTIVE_SNAPSHOT")
        if self.original.revision != 0:
            raise SessionCalibrationError("ORIGINAL_REVISION_MUST_BE_ZERO")
        if self.original.calibration_id != self.calibration_id:
            raise SessionCalibrationError("CALIBRATION_ID_MISMATCH")
        if self.effective.calibration_id != self.calibration_id:
            raise SessionCalibrationError("CALIBRATION_ID_MISMATCH")
        if type(self.considerations) is not tuple:
            raise SessionCalibrationError("INVALID_CONSIDERATIONS")
        if type(self.accepted_adjustments) is not tuple:
            raise SessionCalibrationError("INVALID_ACCEPTED_ADJUSTMENTS")
        if type(self.revision_history) is not tuple:
            raise SessionCalibrationError("INVALID_REVISION_HISTORY")
        if type(self.adaptation_status) is not str or self.adaptation_status not in _ALLOWED_ADAPTATION_STATUSES:
            raise SessionCalibrationError("INVALID_ADAPTATION_STATUS")
        _require_exact_int(self.next_chronology_ordinal, "next_chronology_ordinal", minimum=0)
        _require_exact_int(self.expected_chronology_ordinal, "expected_chronology_ordinal", minimum=0)
        if self.last_pan_ordinal is not None:
            _require_exact_int(self.last_pan_ordinal, "last_pan_ordinal", minimum=0)
        if self.last_event_ordinal is not None:
            _require_exact_int(self.last_event_ordinal, "last_event_ordinal", minimum=0)
        if self.platform != BLUESTACKS_PLATFORM or self.profile_id != BLUESTACKS_PROFILE_ID:
            raise SessionCalibrationError("NON_BLUESTACKS_SESSION_CALIBRATION")
        if self.original.platform != BLUESTACKS_PLATFORM or self.original.profile_id != BLUESTACKS_PROFILE_ID:
            raise SessionCalibrationError("NON_BLUESTACKS_ORIGINAL_CALIBRATION")
        _validate_state_graph(self)

    def effective_gesture_calibration(self) -> GestureCalibration:
        return self.effective.to_gesture_calibration()

    def original_gesture_calibration(self) -> GestureCalibration:
        return self.original.to_gesture_calibration()

    def bounded_drift(self) -> BoundedDriftReport:
        return _compute_bounded_drift(self.original, self.effective)


def _require_sha256(value: object, field_name: str) -> str:
    value = _require_exact_str(value, field_name)
    if _SHA256_HEX.fullmatch(value) is None:
        raise SessionCalibrationError("INVALID_SHA256", field_name)
    return value


def _require_exact_mapping_shape(
    value: object, expected_fields: tuple[str, ...], field_name: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise SessionCalibrationError("INVALID_OBJECT", field_name)
    if tuple(value.keys()) != expected_fields:
        raise SessionCalibrationError("SCHEMA_MISMATCH", field_name)
    for key in value:
        if type(key) is not str:
            raise SessionCalibrationError("NON_STRING_MAPPING_KEY", field_name)
    return value


def _require_exact_json_list(value: object, field_name: str) -> list[Any]:
    if type(value) is not list:
        raise SessionCalibrationError("INVALID_LIST", field_name)
    return value


def _require_exact_optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_exact_int(value, field_name, minimum=0)


def _require_dataclass_shape(value: object, cls: type, field_name: str) -> None:
    if type(value) is not cls:
        raise SessionCalibrationError("INVALID_DATACLASS", field_name)
    try:
        actual = set(vars(value))
    except (TypeError, AttributeError) as exc:
        raise SessionCalibrationError("INVALID_DATACLASS", field_name) from exc
    expected = {item.name for item in fields(cls)}
    if actual != expected:
        raise SessionCalibrationError("DATACLASS_FIELDS_MISMATCH", field_name)


def _snapshot_identity(snapshot: CalibrationSnapshot) -> str:
    payload = {
        "platform": snapshot.platform,
        "profile_id": snapshot.profile_id,
        "drag_origin": [snapshot.drag_origin[0], snapshot.drag_origin[1]],
        "drag_bounds": [
            snapshot.drag_bounds[0],
            snapshot.drag_bounds[1],
            snapshot.drag_bounds[2],
            snapshot.drag_bounds[3],
        ],
        "camera_px_per_drag_x": snapshot.camera_px_per_drag_x,
        "camera_px_per_drag_y": snapshot.camera_px_per_drag_y,
        "minimum_drag_px": snapshot.minimum_drag_px,
        "maximum_drag_x": snapshot.maximum_drag_x,
        "maximum_drag_y": snapshot.maximum_drag_y,
        "minimum_progress_px": snapshot.minimum_progress_px,
        "wrong_direction_tolerance_px": snapshot.wrong_direction_tolerance_px,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _validate_snapshot(
    snapshot: object, field_name: str, *, require_identity: bool = True
) -> None:
    _require_dataclass_shape(snapshot, CalibrationSnapshot, field_name)
    assert isinstance(snapshot, CalibrationSnapshot)
    if snapshot._construction_token is not _CONSTRUCTION_TOKEN:
        raise SessionCalibrationError("UNTRUSTED_CALIBRATION_SNAPSHOT", field_name)
    _require_exact_str(snapshot.platform, f"{field_name}.platform")
    _require_exact_str(snapshot.profile_id, f"{field_name}.profile_id")
    _require_sha256(snapshot.calibration_id, f"{field_name}.calibration_id")
    _require_exact_int(snapshot.revision, f"{field_name}.revision", minimum=0)
    if type(snapshot.drag_origin) is not tuple or len(snapshot.drag_origin) != 2:
        raise SessionCalibrationError("INVALID_TUPLE", f"{field_name}.drag_origin")
    _require_exact_int(snapshot.drag_origin[0], f"{field_name}.drag_origin.x")
    _require_exact_int(snapshot.drag_origin[1], f"{field_name}.drag_origin.y")
    if type(snapshot.drag_bounds) is not tuple or len(snapshot.drag_bounds) != 4:
        raise SessionCalibrationError("INVALID_TUPLE", f"{field_name}.drag_bounds")
    for index, item in enumerate(snapshot.drag_bounds):
        _require_exact_int(item, f"{field_name}.drag_bounds.{index}")
    x0, y0, x1, y1 = snapshot.drag_bounds
    if not (x0 < x1 and y0 < y1):
        raise SessionCalibrationError("INVALID_GESTURE_BOUNDS", field_name)
    if not (x0 <= snapshot.drag_origin[0] <= x1 and y0 <= snapshot.drag_origin[1] <= y1):
        raise SessionCalibrationError("INVALID_DRAG_ORIGIN", field_name)
    for name in (
        "camera_px_per_drag_x",
        "camera_px_per_drag_y",
        "minimum_drag_px",
        "maximum_drag_x",
        "maximum_drag_y",
        "minimum_progress_px",
        "wrong_direction_tolerance_px",
    ):
        _require_exact_float(getattr(snapshot, name), f"{field_name}.{name}")
    if snapshot.camera_px_per_drag_x <= 0.0 or snapshot.camera_px_per_drag_y <= 0.0:
        raise SessionCalibrationError("UNCALIBRATED_SCALE", field_name)
    if (
        snapshot.minimum_drag_px <= 0.0
        or snapshot.maximum_drag_x < snapshot.minimum_drag_px
        or snapshot.maximum_drag_y < snapshot.minimum_drag_px
        or snapshot.minimum_progress_px < 0.0
        or snapshot.wrong_direction_tolerance_px < 0.0
    ):
        raise SessionCalibrationError("INVALID_CALIBRATION_LIMIT", field_name)
    if (
        snapshot.camera_px_per_drag_x < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or snapshot.camera_px_per_drag_x > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or snapshot.camera_px_per_drag_y < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or snapshot.camera_px_per_drag_y > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
    ):
        raise SessionCalibrationError("OUT_OF_BOUND", field_name)
    if require_identity and _snapshot_identity(snapshot) != snapshot.calibration_id:
        raise SessionCalibrationError("CALIBRATION_ID_CONTENT_MISMATCH", field_name)


def _validate_proposed_adjustment(
    proposed: object, field_name: str
) -> None:
    _require_dataclass_shape(proposed, ProposedAdjustment, field_name)
    assert isinstance(proposed, ProposedAdjustment)
    for name in _PROPOSED_FIELDS:
        _require_exact_float(getattr(proposed, name), f"{field_name}.{name}")
    if proposed.influence != MAX_PER_MEASUREMENT_INFLUENCE:
        raise SessionCalibrationError("INVALID_INFLUENCE", field_name)
    for name in (
        "estimated_camera_px_per_drag_x",
        "estimated_camera_px_per_drag_y",
    ):
        value = getattr(proposed, name)
        if not (MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG <= value <= MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG):
            raise SessionCalibrationError("OUT_OF_BOUND", f"{field_name}.{name}")
    if (
        abs(proposed.delta_camera_px_per_drag_x) > MAX_PER_ADJUSTMENT_SCALE
        or abs(proposed.delta_camera_px_per_drag_y) > MAX_PER_ADJUSTMENT_SCALE
    ):
        raise SessionCalibrationError("MAX_PER_ADJUSTMENT", field_name)


def _validate_accepted_adjustment(
    accepted: object, field_name: str
) -> None:
    _require_dataclass_shape(accepted, AcceptedAdjustment, field_name)
    assert isinstance(accepted, AcceptedAdjustment)
    for name in ("revision", "pan_ordinal", "event_ordinal", "chronology_ordinal"):
        _require_exact_int(getattr(accepted, name), f"{field_name}.{name}", minimum=0)
    for name in (
        "delta_camera_px_per_drag_x",
        "delta_camera_px_per_drag_y",
        "camera_px_per_drag_x_after",
        "camera_px_per_drag_y_after",
        "influence",
    ):
        _require_exact_float(getattr(accepted, name), f"{field_name}.{name}")
    if accepted.influence != MAX_PER_MEASUREMENT_INFLUENCE:
        raise SessionCalibrationError("INVALID_INFLUENCE", field_name)
    if (
        abs(accepted.delta_camera_px_per_drag_x) > MAX_PER_ADJUSTMENT_SCALE
        or abs(accepted.delta_camera_px_per_drag_y) > MAX_PER_ADJUSTMENT_SCALE
    ):
        raise SessionCalibrationError("MAX_PER_ADJUSTMENT", field_name)
    for name in ("camera_px_per_drag_x_after", "camera_px_per_drag_y_after"):
        value = getattr(accepted, name)
        if not (MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG <= value <= MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG):
            raise SessionCalibrationError("OUT_OF_BOUND", f"{field_name}.{name}")
    for name in ("source_checkpoint", "destination_checkpoint"):
        checkpoint = _require_exact_str(getattr(accepted, name), f"{field_name}.{name}")
        if checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", f"{field_name}.{name}")


def _validate_measurement(
    measurement: object, field_name: str
) -> None:
    _require_dataclass_shape(measurement, SessionCalibrationMeasurement, field_name)
    assert isinstance(measurement, SessionCalibrationMeasurement)
    for name in ("navigation_session_id", "platform", "profile_id", "calibration_id"):
        _require_exact_str(getattr(measurement, name), f"{field_name}.{name}")
    _require_sha256(measurement.calibration_id, f"{field_name}.calibration_id")
    _require_exact_int(
        measurement.calibration_revision,
        f"{field_name}.calibration_revision",
        minimum=0,
    )
    for name in ("source_checkpoint", "destination_checkpoint"):
        checkpoint = _require_exact_str(getattr(measurement, name), f"{field_name}.{name}")
        if checkpoint not in _ALLOWED_CHECKPOINTS:
            raise SessionCalibrationError("INVALID_CHECKPOINT", f"{field_name}.{name}")
    for name in ("pan_ordinal", "event_ordinal", "chronology_ordinal"):
        _require_exact_int(getattr(measurement, name), f"{field_name}.{name}", minimum=0)
    for name in ("requested", "predicted", "measured"):
        point = getattr(measurement, name)
        if type(point) is not tuple or len(point) != 2:
            raise SessionCalibrationError("INVALID_TUPLE", f"{field_name}.{name}")
        _require_exact_float(point[0], f"{field_name}.{name}.x")
        _require_exact_float(point[1], f"{field_name}.{name}.y")
    _require_exact_float(measurement.progress_px, f"{field_name}.progress_px")
    progress_reason = _require_exact_str(measurement.progress_reason, f"{field_name}.progress_reason")
    for name in (
        "localization_recognized",
        "localization_ambiguous",
        "stale",
        "repeated_viewport",
        "camera_map_clamp",
        "pan_limit_reached",
    ):
        _require_exact_bool(getattr(measurement, name), f"{field_name}.{name}")
    for name in ("source_capture_ordinal", "destination_capture_ordinal"):
        value = getattr(measurement, name)
        _require_exact_optional_int(value, f"{field_name}.{name}")
    if measurement.drag_vector is not None:
        if type(measurement.drag_vector) is not tuple or len(measurement.drag_vector) != 2:
            raise SessionCalibrationError("INVALID_TUPLE", f"{field_name}.drag_vector")
        _require_exact_float(measurement.drag_vector[0], f"{field_name}.drag_vector.x")
        _require_exact_float(measurement.drag_vector[1], f"{field_name}.drag_vector.y")
    if measurement.maximum_pans is not None:
        _require_exact_int(measurement.maximum_pans, f"{field_name}.maximum_pans", minimum=1)


def _validate_consideration(
    consideration: object, field_name: str
) -> None:
    _require_dataclass_shape(consideration, MeasurementConsideration, field_name)
    assert isinstance(consideration, MeasurementConsideration)
    if consideration._construction_token is not _CONSTRUCTION_TOKEN:
        raise SessionCalibrationError("UNTRUSTED_MEASUREMENT_CONSIDERATION", field_name)
    _require_exact_int(consideration.chronology_ordinal, f"{field_name}.chronology_ordinal", minimum=0)
    _validate_measurement(consideration.measurement, f"{field_name}.measurement")
    _require_exact_bool(consideration.validation_accepted, f"{field_name}.validation_accepted")
    if consideration.rejection_reason is not None:
        reason = _require_exact_str(consideration.rejection_reason, f"{field_name}.rejection_reason")
        if reason not in _ALLOWED_REJECTION_REASONS:
            raise SessionCalibrationError("INVALID_REJECTION_REASON", field_name)
    if consideration.proposed_adjustment is not None:
        _validate_proposed_adjustment(
            consideration.proposed_adjustment, f"{field_name}.proposed_adjustment"
        )
    if consideration.accepted_adjustment is not None:
        _validate_accepted_adjustment(
            consideration.accepted_adjustment, f"{field_name}.accepted_adjustment"
        )
    if consideration.validation_accepted:
        if consideration.rejection_reason is not None or consideration.accepted_adjustment is None:
            raise SessionCalibrationError("CONTRADICTORY_CONSIDERATION", field_name)
        if consideration.proposed_adjustment is None:
            raise SessionCalibrationError("MISSING_PROPOSED_ADJUSTMENT", field_name)
    elif consideration.rejection_reason is None or consideration.accepted_adjustment is not None:
        raise SessionCalibrationError("CONTRADICTORY_CONSIDERATION", field_name)
    _require_exact_int(
        consideration.effective_revision_after,
        f"{field_name}.effective_revision_after",
        minimum=0,
    )


def _validate_drift(drift: object, field_name: str) -> None:
    _require_dataclass_shape(drift, BoundedDriftReport, field_name)
    assert isinstance(drift, BoundedDriftReport)
    for name in (
        "drift_x",
        "drift_y",
        "abs_drift_x",
        "abs_drift_y",
        "directional_skew",
    ):
        _require_exact_float(getattr(drift, name), f"{field_name}.{name}")
    _require_exact_bool(drift.within_limits, f"{field_name}.within_limits")
    if drift.abs_drift_x < 0.0 or drift.abs_drift_y < 0.0 or drift.directional_skew < 0.0:
        raise SessionCalibrationError("INVALID_DRIFT", field_name)
    if (
        drift.abs_drift_x != abs(drift.drift_x)
        or drift.abs_drift_y != abs(drift.drift_y)
        or drift.directional_skew != abs(drift.drift_x - drift.drift_y)
    ):
        raise SessionCalibrationError("DERIVED_VALUE_MISMATCH", field_name)
    expected = (
        drift.abs_drift_x <= MAX_TOTAL_DRIFT + MIN_COMPONENT_ABS
        and drift.abs_drift_y <= MAX_TOTAL_DRIFT + MIN_COMPONENT_ABS
        and drift.directional_skew <= MAX_DIRECTIONAL_SKEW + MIN_COMPONENT_ABS
    )
    if drift.within_limits is not expected:
        raise SessionCalibrationError("DERIVED_VALUE_MISMATCH", field_name)


def _validate_state_graph(state: object) -> None:
    """Revalidate a complete possibly-forged state before any derived math."""

    try:
        _require_dataclass_shape(state, SessionCalibrationState, "state")
        assert isinstance(state, SessionCalibrationState)
        if state._construction_token is not _CONSTRUCTION_TOKEN:
            raise SessionCalibrationError("UNTRUSTED_SESSION_CALIBRATION_STATE")
        for name in ("navigation_session_id", "platform", "profile_id", "calibration_id"):
            _require_exact_str(getattr(state, name), f"state.{name}")
        _require_sha256(state.calibration_id, "state.calibration_id")
        if state.platform != BLUESTACKS_PLATFORM or state.profile_id != BLUESTACKS_PROFILE_ID:
            raise SessionCalibrationError("NON_BLUESTACKS_SESSION_CALIBRATION")
        _validate_snapshot(state.original, "state.original", require_identity=True)
        _validate_snapshot(state.effective, "state.effective", require_identity=False)
        for name in (
            "drag_origin",
            "drag_bounds",
            "minimum_drag_px",
            "maximum_drag_x",
            "maximum_drag_y",
            "minimum_progress_px",
            "wrong_direction_tolerance_px",
        ):
            if getattr(state.original, name) != getattr(state.effective, name):
                raise SessionCalibrationError(
                    "EFFECTIVE_CALIBRATION_STRUCTURE_MISMATCH", name
                )
        for snapshot_name, snapshot in (
            ("original", state.original),
            ("effective", state.effective),
        ):
            if snapshot.platform != state.platform or snapshot.profile_id != state.profile_id:
                raise SessionCalibrationError("PROFILE_BINDING_MISMATCH", f"state.{snapshot_name}")
            if snapshot.calibration_id != state.calibration_id:
                raise SessionCalibrationError("CALIBRATION_ID_MISMATCH", f"state.{snapshot_name}")
        if state.original.revision != 0:
            raise SessionCalibrationError("ORIGINAL_REVISION_MUST_BE_ZERO")
        if state.effective.revision < state.original.revision:
            raise SessionCalibrationError("REVISION_REGRESSION")
        if type(state.considerations) is not tuple:
            raise SessionCalibrationError("INVALID_TUPLE", "state.considerations")
        if type(state.accepted_adjustments) is not tuple:
            raise SessionCalibrationError("INVALID_TUPLE", "state.accepted_adjustments")
        if type(state.revision_history) is not tuple:
            raise SessionCalibrationError("INVALID_TUPLE", "state.revision_history")
        _require_exact_int(state.next_chronology_ordinal, "state.next_chronology_ordinal", minimum=0)
        _require_exact_int(state.expected_chronology_ordinal, "state.expected_chronology_ordinal", minimum=0)
        if state.last_pan_ordinal is not None:
            _require_exact_int(state.last_pan_ordinal, "state.last_pan_ordinal", minimum=0)
        if state.last_event_ordinal is not None:
            _require_exact_int(state.last_event_ordinal, "state.last_event_ordinal", minimum=0)
        if type(state.adaptation_status) is not str or state.adaptation_status not in _ALLOWED_ADAPTATION_STATUSES:
            raise SessionCalibrationError("INVALID_ADAPTATION_STATUS")
        if len(state.considerations) > MAX_EVIDENCE_COUNT + 1:
            raise SessionCalibrationError("MAX_EVIDENCE_COUNT")
        if len(state.considerations) == MAX_EVIDENCE_COUNT + 1:
            overflow = state.considerations[-1]
            if (
                overflow.validation_accepted
                or overflow.rejection_reason != RejectionReason.MAX_EVIDENCE_COUNT.value
            ):
                raise SessionCalibrationError("MAX_EVIDENCE_COUNT")
        accepted_count = sum(
            1 for item in state.considerations if item.validation_accepted
        )
        if accepted_count > MAX_ACCEPTED_ADJUSTMENTS:
            raise SessionCalibrationError("MAX_ACCEPTED_COUNT")
        current_revision = 0
        previous_pan: int | None = None
        previous_event: int | None = None
        for index, consideration in enumerate(state.considerations):
            _validate_consideration(consideration, f"state.considerations[{index}]")
            if consideration.chronology_ordinal != index:
                raise SessionCalibrationError("CHRONOLOGY_MISMATCH", f"state.considerations[{index}]")
            if (
                consideration.measurement.chronology_ordinal != index
                and not (
                    not consideration.validation_accepted
                    and consideration.rejection_reason
                    == RejectionReason.MISSING_SAMPLE.value
                    and consideration.measurement.chronology_ordinal > index
                )
            ):
                raise SessionCalibrationError("CHRONOLOGY_MISMATCH", f"state.considerations[{index}].measurement")
            measurement = consideration.measurement
            if (
                measurement.navigation_session_id != state.navigation_session_id
                or measurement.platform != state.platform
                or measurement.profile_id != state.profile_id
                or measurement.calibration_id != state.calibration_id
            ) and consideration.validation_accepted:
                raise SessionCalibrationError("MEASUREMENT_BINDING_MISMATCH", f"state.considerations[{index}]")
            if measurement.progress_reason not in _ALLOWED_PROGRESS_REASONS:
                if (
                    consideration.validation_accepted
                    or consideration.rejection_reason
                    != RejectionReason.INVALID_PROGRESS_REASON.value
                ):
                    raise SessionCalibrationError(
                        "INVALID_PROGRESS_REASON", f"state.considerations[{index}]"
                    )
            if (
                previous_pan is not None
                and measurement.pan_ordinal < previous_pan
                and (
                    consideration.validation_accepted
                    or consideration.rejection_reason
                    not in {
                        RejectionReason.REORDERED_SAMPLE.value,
                        RejectionReason.DUPLICATE_SAMPLE.value,
                        RejectionReason.MISSING_SAMPLE.value,
                    }
                )
            ):
                raise SessionCalibrationError("REORDERED_SAMPLE", f"state.considerations[{index}]")
            if (
                previous_pan is not None
                and measurement.pan_ordinal == previous_pan
                and previous_event is not None
                and measurement.event_ordinal <= previous_event
                and (
                    consideration.validation_accepted
                    or consideration.rejection_reason
                    not in {
                        RejectionReason.DUPLICATE_SAMPLE.value,
                        RejectionReason.MISSING_SAMPLE.value,
                    }
                )
            ):
                raise SessionCalibrationError("DUPLICATE_SAMPLE", f"state.considerations[{index}]")
            if (
                measurement.calibration_revision != current_revision
                and not (
                    not consideration.validation_accepted
                    and consideration.rejection_reason
                    == RejectionReason.CROSS_CALIBRATION.value
                )
            ):
                raise SessionCalibrationError("MEASUREMENT_REVISION_MISMATCH", f"state.considerations[{index}]")
            expected_after = current_revision + (
                1 if consideration.validation_accepted else 0
            )
            if consideration.effective_revision_after != expected_after:
                raise SessionCalibrationError(
                    "REVISION_SEQUENCE_MISMATCH", f"state.considerations[{index}]"
                )
            current_revision = expected_after
            previous_pan = measurement.pan_ordinal
            previous_event = measurement.event_ordinal
        expected_revision_history = tuple(range(state.effective.revision + 1))
        if state.revision_history != expected_revision_history:
            raise SessionCalibrationError("REVISION_HISTORY_MISMATCH")
        if state.next_chronology_ordinal != len(state.considerations):
            raise SessionCalibrationError("CHRONOLOGY_MISMATCH")
        if state.expected_chronology_ordinal != len(state.considerations):
            raise SessionCalibrationError("CHRONOLOGY_MISMATCH")
        accepted_from_considerations = tuple(
            item.accepted_adjustment
            for item in state.considerations
            if item.validation_accepted
        )
        if any(item is None for item in accepted_from_considerations):
            raise SessionCalibrationError("MISSING_ACCEPTED_ADJUSTMENT")
        if state.accepted_adjustments != accepted_from_considerations:
            raise SessionCalibrationError("ACCEPTED_ADJUSTMENT_LINK_MISMATCH")
        if len(state.accepted_adjustments) != state.effective.revision:
            raise SessionCalibrationError("REVISION_COUNT_MISMATCH")
        accepted_considerations = tuple(
            item for item in state.considerations if item.validation_accepted
        )
        previous_after_x = state.original.camera_px_per_drag_x
        previous_after_y = state.original.camera_px_per_drag_y
        for index, (adjustment, consideration) in enumerate(
            zip(state.accepted_adjustments, accepted_considerations), start=1
        ):
            assert adjustment is not None
            _validate_accepted_adjustment(adjustment, f"state.accepted_adjustments[{index - 1}]")
            if adjustment.revision != index:
                raise SessionCalibrationError("REVISION_SEQUENCE_MISMATCH")
            measurement = consideration.measurement
            if (
                adjustment.pan_ordinal != measurement.pan_ordinal
                or adjustment.event_ordinal != measurement.event_ordinal
                or adjustment.chronology_ordinal != consideration.chronology_ordinal
                or adjustment.source_checkpoint != measurement.source_checkpoint
                or adjustment.destination_checkpoint != measurement.destination_checkpoint
            ):
                raise SessionCalibrationError("ACCEPTED_ADJUSTMENT_LINK_MISMATCH")
            proposed = consideration.proposed_adjustment
            if proposed is None:
                raise SessionCalibrationError("MISSING_PROPOSED_ADJUSTMENT")
            if (
                adjustment.delta_camera_px_per_drag_x != proposed.delta_camera_px_per_drag_x
                or adjustment.delta_camera_px_per_drag_y != proposed.delta_camera_px_per_drag_y
                or adjustment.influence != proposed.influence
                or proposed.delta_camera_px_per_drag_x
                != (
                    proposed.estimated_camera_px_per_drag_x - previous_after_x
                )
                * proposed.influence
                or proposed.delta_camera_px_per_drag_y
                != (
                    proposed.estimated_camera_px_per_drag_y - previous_after_y
                )
                * proposed.influence
                or adjustment.camera_px_per_drag_x_after
                != previous_after_x + adjustment.delta_camera_px_per_drag_x
                or adjustment.camera_px_per_drag_y_after
                != previous_after_y + adjustment.delta_camera_px_per_drag_y
            ):
                raise SessionCalibrationError("ACCEPTED_ADJUSTMENT_VALUE_MISMATCH")
            previous_after_x = adjustment.camera_px_per_drag_x_after
            previous_after_y = adjustment.camera_px_per_drag_y_after
        # Rebuild the effective camera scales from the immutable baseline. This catches
        # forged effective values before bounded-drift arithmetic.
        expected_x = (
            state.original.camera_px_per_drag_x
            if not state.accepted_adjustments
            else state.accepted_adjustments[-1].camera_px_per_drag_x_after
        )
        expected_y = (
            state.original.camera_px_per_drag_y
            if not state.accepted_adjustments
            else state.accepted_adjustments[-1].camera_px_per_drag_y_after
        )
        if (
            state.effective.camera_px_per_drag_x != expected_x
            or state.effective.camera_px_per_drag_y != expected_y
        ):
            raise SessionCalibrationError("EFFECTIVE_CALIBRATION_MISMATCH")
        expected_status = _adaptation_status_for(state.considerations, state.accepted_adjustments)
        if state.adaptation_status != expected_status:
            raise SessionCalibrationError("ADAPTATION_STATUS_MISMATCH")
        if state.considerations:
            last = state.considerations[-1].measurement
            if state.last_pan_ordinal != last.pan_ordinal or state.last_event_ordinal != last.event_ordinal:
                raise SessionCalibrationError("LAST_ORDINAL_MISMATCH")
        elif state.last_pan_ordinal is not None or state.last_event_ordinal is not None:
            raise SessionCalibrationError("LAST_ORDINAL_MISMATCH")
    except SessionCalibrationError:
        raise
    except Exception as exc:
        raise SessionCalibrationError("INVALID_STATE_GRAPH") from exc


def _raw_point(value: object, field_name: str) -> tuple[float, float]:
    values = _require_exact_json_list(value, field_name)
    if len(values) != 2:
        raise SessionCalibrationError("INVALID_LIST", field_name)
    return (
        _require_exact_float(values[0], f"{field_name}.x"),
        _require_exact_float(values[1], f"{field_name}.y"),
    )


def _raw_int_tuple(
    value: object, length: int, field_name: str
) -> tuple[int, ...]:
    values = _require_exact_json_list(value, field_name)
    if len(values) != length:
        raise SessionCalibrationError("INVALID_LIST", field_name)
    return tuple(
        _require_exact_int(item, f"{field_name}.{index}")
        for index, item in enumerate(values)
    )


def _snapshot_from_payload(
    payload: object, field_name: str, *, require_identity: bool
) -> CalibrationSnapshot:
    mapping = _require_exact_mapping_shape(payload, _SNAPSHOT_FIELDS, field_name)
    snapshot = CalibrationSnapshot(
        platform=_require_exact_str(mapping["platform"], f"{field_name}.platform"),
        profile_id=_require_exact_str(mapping["profile_id"], f"{field_name}.profile_id"),
        calibration_id=_require_sha256(
            mapping["calibration_id"], f"{field_name}.calibration_id"
        ),
        revision=_require_exact_int(mapping["revision"], f"{field_name}.revision", minimum=0),
        drag_origin=_raw_int_tuple(mapping["drag_origin"], 2, f"{field_name}.drag_origin"),
        drag_bounds=_raw_int_tuple(mapping["drag_bounds"], 4, f"{field_name}.drag_bounds"),
        camera_px_per_drag_x=_require_exact_float(
            mapping["camera_px_per_drag_x"], f"{field_name}.camera_px_per_drag_x"
        ),
        camera_px_per_drag_y=_require_exact_float(
            mapping["camera_px_per_drag_y"], f"{field_name}.camera_px_per_drag_y"
        ),
        minimum_drag_px=_require_exact_float(
            mapping["minimum_drag_px"], f"{field_name}.minimum_drag_px"
        ),
        maximum_drag_x=_require_exact_float(
            mapping["maximum_drag_x"], f"{field_name}.maximum_drag_x"
        ),
        maximum_drag_y=_require_exact_float(
            mapping["maximum_drag_y"], f"{field_name}.maximum_drag_y"
        ),
        minimum_progress_px=_require_exact_float(
            mapping["minimum_progress_px"], f"{field_name}.minimum_progress_px"
        ),
        wrong_direction_tolerance_px=_require_exact_float(
            mapping["wrong_direction_tolerance_px"],
            f"{field_name}.wrong_direction_tolerance_px",
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_snapshot(snapshot, field_name, require_identity=require_identity)
    return snapshot


def _proposed_from_payload(
    payload: object, field_name: str
) -> ProposedAdjustment:
    mapping = _require_exact_mapping_shape(payload, _PROPOSED_FIELDS, field_name)
    proposed = ProposedAdjustment(
        delta_camera_px_per_drag_x=_require_exact_float(
            mapping["delta_camera_px_per_drag_x"],
            f"{field_name}.delta_camera_px_per_drag_x",
        ),
        delta_camera_px_per_drag_y=_require_exact_float(
            mapping["delta_camera_px_per_drag_y"],
            f"{field_name}.delta_camera_px_per_drag_y",
        ),
        influence=_require_exact_float(mapping["influence"], f"{field_name}.influence"),
        estimated_camera_px_per_drag_x=_require_exact_float(
            mapping["estimated_camera_px_per_drag_x"],
            f"{field_name}.estimated_camera_px_per_drag_x",
        ),
        estimated_camera_px_per_drag_y=_require_exact_float(
            mapping["estimated_camera_px_per_drag_y"],
            f"{field_name}.estimated_camera_px_per_drag_y",
        ),
    )
    _validate_proposed_adjustment(proposed, field_name)
    return proposed


def _accepted_from_payload(
    payload: object, field_name: str
) -> AcceptedAdjustment:
    mapping = _require_exact_mapping_shape(payload, _ACCEPTED_FIELDS, field_name)
    accepted = AcceptedAdjustment(
        revision=_require_exact_int(mapping["revision"], f"{field_name}.revision", minimum=0),
        pan_ordinal=_require_exact_int(
            mapping["pan_ordinal"], f"{field_name}.pan_ordinal", minimum=0
        ),
        event_ordinal=_require_exact_int(
            mapping["event_ordinal"], f"{field_name}.event_ordinal", minimum=0
        ),
        chronology_ordinal=_require_exact_int(
            mapping["chronology_ordinal"], f"{field_name}.chronology_ordinal", minimum=0
        ),
        delta_camera_px_per_drag_x=_require_exact_float(
            mapping["delta_camera_px_per_drag_x"],
            f"{field_name}.delta_camera_px_per_drag_x",
        ),
        delta_camera_px_per_drag_y=_require_exact_float(
            mapping["delta_camera_px_per_drag_y"],
            f"{field_name}.delta_camera_px_per_drag_y",
        ),
        camera_px_per_drag_x_after=_require_exact_float(
            mapping["camera_px_per_drag_x_after"],
            f"{field_name}.camera_px_per_drag_x_after",
        ),
        camera_px_per_drag_y_after=_require_exact_float(
            mapping["camera_px_per_drag_y_after"],
            f"{field_name}.camera_px_per_drag_y_after",
        ),
        influence=_require_exact_float(mapping["influence"], f"{field_name}.influence"),
        source_checkpoint=_require_exact_str(
            mapping["source_checkpoint"], f"{field_name}.source_checkpoint"
        ),
        destination_checkpoint=_require_exact_str(
            mapping["destination_checkpoint"], f"{field_name}.destination_checkpoint"
        ),
    )
    _validate_accepted_adjustment(accepted, field_name)
    return accepted


def _measurement_from_payload(
    payload: object, field_name: str
) -> SessionCalibrationMeasurement:
    mapping = _require_exact_mapping_shape(payload, _MEASUREMENT_FIELDS, field_name)
    drag_vector = (
        None
        if mapping["drag_vector"] is None
        else _raw_point(mapping["drag_vector"], f"{field_name}.drag_vector")
    )
    measurement = SessionCalibrationMeasurement(
        navigation_session_id=_require_exact_str(
            mapping["navigation_session_id"], f"{field_name}.navigation_session_id"
        ),
        platform=_require_exact_str(mapping["platform"], f"{field_name}.platform"),
        profile_id=_require_exact_str(mapping["profile_id"], f"{field_name}.profile_id"),
        calibration_id=_require_sha256(
            mapping["calibration_id"], f"{field_name}.calibration_id"
        ),
        calibration_revision=_require_exact_int(
            mapping["calibration_revision"],
            f"{field_name}.calibration_revision",
            minimum=0,
        ),
        source_checkpoint=_require_exact_str(
            mapping["source_checkpoint"], f"{field_name}.source_checkpoint"
        ),
        destination_checkpoint=_require_exact_str(
            mapping["destination_checkpoint"], f"{field_name}.destination_checkpoint"
        ),
        pan_ordinal=_require_exact_int(
            mapping["pan_ordinal"], f"{field_name}.pan_ordinal", minimum=0
        ),
        event_ordinal=_require_exact_int(
            mapping["event_ordinal"], f"{field_name}.event_ordinal", minimum=0
        ),
        chronology_ordinal=_require_exact_int(
            mapping["chronology_ordinal"], f"{field_name}.chronology_ordinal", minimum=0
        ),
        requested=_raw_point(mapping["requested"], f"{field_name}.requested"),
        predicted=_raw_point(mapping["predicted"], f"{field_name}.predicted"),
        measured=_raw_point(mapping["measured"], f"{field_name}.measured"),
        progress_px=_require_exact_float(
            mapping["progress_px"], f"{field_name}.progress_px"
        ),
        progress_reason=_require_exact_str(
            mapping["progress_reason"], f"{field_name}.progress_reason"
        ),
        localization_recognized=_require_exact_bool(
            mapping["localization_recognized"], f"{field_name}.localization_recognized"
        ),
        localization_ambiguous=_require_exact_bool(
            mapping["localization_ambiguous"], f"{field_name}.localization_ambiguous"
        ),
        stale=_require_exact_bool(mapping["stale"], f"{field_name}.stale"),
        repeated_viewport=_require_exact_bool(
            mapping["repeated_viewport"], f"{field_name}.repeated_viewport"
        ),
        camera_map_clamp=_require_exact_bool(
            mapping["camera_map_clamp"], f"{field_name}.camera_map_clamp"
        ),
        pan_limit_reached=_require_exact_bool(
            mapping["pan_limit_reached"], f"{field_name}.pan_limit_reached"
        ),
        source_capture_ordinal=_require_exact_optional_int(
            mapping["source_capture_ordinal"], f"{field_name}.source_capture_ordinal"
        ),
        destination_capture_ordinal=_require_exact_optional_int(
            mapping["destination_capture_ordinal"],
            f"{field_name}.destination_capture_ordinal",
        ),
        drag_vector=drag_vector,
        maximum_pans=_require_exact_optional_int(
            mapping["maximum_pans"], f"{field_name}.maximum_pans"
        ),
    )
    _validate_measurement(measurement, field_name)
    return measurement


def _consideration_from_payload(
    payload: object, field_name: str
) -> MeasurementConsideration:
    mapping = _require_exact_mapping_shape(payload, _CONSIDERATION_FIELDS, field_name)
    proposed = (
        None
        if mapping["proposed_adjustment"] is None
        else _proposed_from_payload(
            mapping["proposed_adjustment"], f"{field_name}.proposed_adjustment"
        )
    )
    accepted = (
        None
        if mapping["accepted_adjustment"] is None
        else _accepted_from_payload(
            mapping["accepted_adjustment"], f"{field_name}.accepted_adjustment"
        )
    )
    consideration = MeasurementConsideration(
        chronology_ordinal=_require_exact_int(
            mapping["chronology_ordinal"],
            f"{field_name}.chronology_ordinal",
            minimum=0,
        ),
        measurement=_measurement_from_payload(
            mapping["measurement"], f"{field_name}.measurement"
        ),
        validation_accepted=_require_exact_bool(
            mapping["validation_accepted"], f"{field_name}.validation_accepted"
        ),
        rejection_reason=(
            None
            if mapping["rejection_reason"] is None
            else _require_exact_str(
                mapping["rejection_reason"], f"{field_name}.rejection_reason"
            )
        ),
        proposed_adjustment=proposed,
        accepted_adjustment=accepted,
        effective_revision_after=_require_exact_int(
            mapping["effective_revision_after"],
            f"{field_name}.effective_revision_after",
            minimum=0,
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_consideration(consideration, field_name)
    return consideration


def _drift_from_payload(payload: object, field_name: str) -> BoundedDriftReport:
    mapping = _require_exact_mapping_shape(payload, _DRIFT_FIELDS, field_name)
    drift = BoundedDriftReport(
        drift_x=_require_exact_float(mapping["drift_x"], f"{field_name}.drift_x"),
        drift_y=_require_exact_float(mapping["drift_y"], f"{field_name}.drift_y"),
        abs_drift_x=_require_exact_float(
            mapping["abs_drift_x"], f"{field_name}.abs_drift_x"
        ),
        abs_drift_y=_require_exact_float(
            mapping["abs_drift_y"], f"{field_name}.abs_drift_y"
        ),
        directional_skew=_require_exact_float(
            mapping["directional_skew"], f"{field_name}.directional_skew"
        ),
        within_limits=_require_exact_bool(
            mapping["within_limits"], f"{field_name}.within_limits"
        ),
    )
    _validate_drift(drift, field_name)
    return drift


def _validate_observability_payload(payload: object, field_name: str) -> None:
    mapping = _require_exact_mapping_shape(payload, _OBSERVABILITY_FIELDS, field_name)
    schema_name = mapping["schema_name"]
    schema_version = mapping["schema_version"]
    report_integrity = mapping["report_integrity"]
    if schema_name is None:
        if schema_version is not None or report_integrity != "unavailable":
            raise SessionCalibrationError("INVALID_OBSERVABILITY_INTEGRATION", field_name)
        for name in ("requested_present", "measured_present", "residual_present"):
            if mapping[name] != "unavailable":
                raise SessionCalibrationError("INVALID_OBSERVABILITY_INTEGRATION", field_name)
    else:
        if schema_name != "navigation_session_observability":
            raise SessionCalibrationError("INVALID_OBSERVABILITY_SCHEMA", field_name)
        if type(schema_version) is not int or type(schema_version) is bool or schema_version != 1:
            raise SessionCalibrationError("INVALID_OBSERVABILITY_VERSION", field_name)
        if report_integrity not in {"valid", "incomplete", "malformed", "contradictory"}:
            raise SessionCalibrationError("INVALID_OBSERVABILITY_INTEGRITY", field_name)
        for name in ("requested_present", "measured_present", "residual_present"):
            if mapping[name] not in {
                "present",
                "unknown",
                "unavailable",
                "contradictory",
                "malformed",
            }:
                raise SessionCalibrationError("INVALID_OBSERVABILITY_AVAILABILITY", field_name)
    _require_exact_str(mapping["navigation_session_id"], f"{field_name}.navigation_session_id")
    _require_exact_bool(mapping["mutates_session_ledger"], f"{field_name}.mutates_session_ledger")
    if mapping["mutates_session_ledger"] is not False:
        raise SessionCalibrationError("OBSERVABILITY_MUTATION_FORBIDDEN", field_name)


def _validate_state_and_derive_report_values(state: SessionCalibrationState) -> BoundedDriftReport:
    _validate_state_graph(state)
    drift = state.bounded_drift()
    _validate_drift(drift, "state.bounded_drift")
    return drift


def _validate_report_payload(payload: object) -> SessionCalibrationState:
    """Validate and reconstruct a report graph before exposing any values."""

    try:
        mapping = _require_exact_mapping_shape(
            payload, REPORT_FIELD_ORDER, "report"
        )
        if mapping["schema_name"] != SCHEMA_NAME:
            raise SessionCalibrationError("SCHEMA_NAME_MISMATCH")
        if type(mapping["schema_version"]) is not int or mapping["schema_version"] != SCHEMA_VERSION:
            raise SessionCalibrationError("SCHEMA_VERSION_MISMATCH")
        navigation_session_id = _require_exact_str(
            mapping["navigation_session_id"], "report.navigation_session_id"
        )
        platform = _require_exact_str(mapping["platform"], "report.platform")
        profile_id = _require_exact_str(mapping["profile_id"], "report.profile_id")
        calibration_id = _require_sha256(mapping["calibration_id"], "report.calibration_id")
        if platform != BLUESTACKS_PLATFORM or profile_id != BLUESTACKS_PROFILE_ID:
            raise SessionCalibrationError("NON_BLUESTACKS_SESSION_CALIBRATION")
        original = _snapshot_from_payload(
            mapping["original_calibration"],
            "report.original_calibration",
            require_identity=True,
        )
        effective = _snapshot_from_payload(
            mapping["effective_calibration"],
            "report.effective_calibration",
            require_identity=False,
        )
        if (
            original.platform != platform
            or original.profile_id != profile_id
            or effective.platform != platform
            or effective.profile_id != profile_id
            or original.calibration_id != calibration_id
            or effective.calibration_id != calibration_id
        ):
            raise SessionCalibrationError("REPORT_CALIBRATION_BINDING_MISMATCH")
        effective_revision = _require_exact_int(
            mapping["effective_revision"], "report.effective_revision", minimum=0
        )
        if effective.revision != effective_revision:
            raise SessionCalibrationError("REVISION_MISMATCH")
        adaptation_status = _require_exact_str(
            mapping["adaptation_status"], "report.adaptation_status"
        )
        if adaptation_status not in _ALLOWED_ADAPTATION_STATUSES:
            raise SessionCalibrationError("INVALID_ADAPTATION_STATUS")
        accepted_count = _require_exact_int(
            mapping["accepted_adjustment_count"],
            "report.accepted_adjustment_count",
            minimum=0,
        )
        considered_count = _require_exact_int(
            mapping["considered_measurement_count"],
            "report.considered_measurement_count",
            minimum=0,
        )
        rejected_count = _require_exact_int(
            mapping["rejected_measurement_count"],
            "report.rejected_measurement_count",
            minimum=0,
        )
        revision_history_values = _require_exact_json_list(
            mapping["revision_history"], "report.revision_history"
        )
        revision_history = tuple(
            _require_exact_int(item, "report.revision_history.item", minimum=0)
            for item in revision_history_values
        )
        considerations_payload = _require_exact_json_list(
            mapping["considerations"], "report.considerations"
        )
        considerations = tuple(
            _consideration_from_payload(item, f"report.considerations[{index}]")
            for index, item in enumerate(considerations_payload)
        )
        accepted_adjustments = tuple(
            item.accepted_adjustment
            for item in considerations
            if item.validation_accepted
        )
        if any(item is None for item in accepted_adjustments):
            raise SessionCalibrationError("MISSING_ACCEPTED_ADJUSTMENT")
        typed_accepted = tuple(item for item in accepted_adjustments if item is not None)
        state = SessionCalibrationState(
            navigation_session_id=navigation_session_id,
            platform=platform,
            profile_id=profile_id,
            calibration_id=calibration_id,
            original=original,
            effective=effective,
            considerations=considerations,
            accepted_adjustments=typed_accepted,
            revision_history=revision_history,
            adaptation_status=adaptation_status,
            next_chronology_ordinal=len(considerations),
            last_pan_ordinal=(
                None if not considerations else considerations[-1].measurement.pan_ordinal
            ),
            last_event_ordinal=(
                None if not considerations else considerations[-1].measurement.event_ordinal
            ),
            expected_chronology_ordinal=len(considerations),
            _construction_token=_CONSTRUCTION_TOKEN,
        )
        _validate_state_graph(state)
        if (
            accepted_count != len(typed_accepted)
            or considered_count != len(considerations)
            or rejected_count != considered_count - accepted_count
        ):
            raise SessionCalibrationError("REPORT_COUNT_MISMATCH")
        if revision_history != tuple(range(effective_revision + 1)):
            raise SessionCalibrationError("REVISION_HISTORY_MISMATCH")
        reason_counts = mapping["rejection_reason_counts"]
        if type(reason_counts) is not dict:
            raise SessionCalibrationError("INVALID_REASON_COUNTS")
        if list(reason_counts.keys()) != sorted(reason_counts.keys()):
            raise SessionCalibrationError("REASON_COUNT_ORDER_MISMATCH")
        counted: dict[str, int] = {}
        for reason, count in reason_counts.items():
            if type(reason) is not str or reason not in _ALLOWED_REJECTION_REASONS:
                raise SessionCalibrationError("INVALID_REJECTION_REASON", "report.rejection_reason_counts")
            counted[reason] = _require_exact_int(
                count, f"report.rejection_reason_counts.{reason}", minimum=1
            )
        if counted != _rejection_reason_counts(considerations):
            raise SessionCalibrationError("REASON_COUNT_MISMATCH")
        drift = _drift_from_payload(mapping["bounded_drift"], "report.bounded_drift")
        expected_drift = state.bounded_drift()
        if drift.to_dict() != expected_drift.to_dict():
            raise SessionCalibrationError("DRIFT_MISMATCH")
        _validate_observability_payload(
            mapping["observability_integration"], "report.observability_integration"
        )
        observability = mapping["observability_integration"]
        if observability["navigation_session_id"] != navigation_session_id:
            raise SessionCalibrationError("OBSERVABILITY_SESSION_MISMATCH")
        if type(mapping["persistence_authorized"]) is not bool or mapping["persistence_authorized"] is not False:
            raise SessionCalibrationError("PERSISTENCE_MUST_REMAIN_UNAUTHORIZED")
        if type(mapping["authorize_dispatch"]) is not bool or mapping["authorize_dispatch"] is not False:
            raise SessionCalibrationError("DISPATCH_MUST_REMAIN_UNAUTHORIZED")
        if mapping["capability_grant"] is not None:
            raise SessionCalibrationError("CAPABILITY_GRANT_FORBIDDEN")
        non_dispatch = _require_exact_mapping_shape(
            mapping["non_dispatch_authority"],
            ("resolution", "reason_code"),
            "report.non_dispatch_authority",
        )
        if (
            non_dispatch["resolution"]
            != UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value
            or non_dispatch["reason_code"] != "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
        ):
            raise SessionCalibrationError("NON_DISPATCH_AUTHORITY_CHANGED")
        _require_exact_str(non_dispatch["resolution"], "report.non_dispatch_authority.resolution")
        _require_exact_str(non_dispatch["reason_code"], "report.non_dispatch_authority.reason_code")
        return state
    except SessionCalibrationError:
        raise
    except Exception as exc:
        raise SessionCalibrationError("INVALID_REPORT_GRAPH") from exc


def _compute_bounded_drift(
    original: CalibrationSnapshot, effective: CalibrationSnapshot
) -> BoundedDriftReport:
    drift_x = (effective.camera_px_per_drag_x / original.camera_px_per_drag_x) - 1.0
    drift_y = (effective.camera_px_per_drag_y / original.camera_px_per_drag_y) - 1.0
    abs_x = abs(drift_x)
    abs_y = abs(drift_y)
    skew = abs(drift_x - drift_y)
    within = (
        abs_x <= MAX_TOTAL_DRIFT + MIN_COMPONENT_ABS
        and abs_y <= MAX_TOTAL_DRIFT + MIN_COMPONENT_ABS
        and skew <= MAX_DIRECTIONAL_SKEW + MIN_COMPONENT_ABS
    )
    return BoundedDriftReport(
        drift_x=float(drift_x),
        drift_y=float(drift_y),
        abs_drift_x=float(abs_x),
        abs_drift_y=float(abs_y),
        directional_skew=float(skew),
        within_limits=within,
    )


def _adaptation_status_for(
    considerations: Sequence[MeasurementConsideration],
    accepted: Sequence[AcceptedAdjustment],
) -> str:
    if not considerations:
        return AdaptationStatus.NONE.value
    if len(accepted) >= MAX_ACCEPTED_ADJUSTMENTS:
        return AdaptationStatus.SATURATED.value
    if accepted:
        return AdaptationStatus.ADAPTED.value
    return AdaptationStatus.REJECTED_ONLY.value


def create_session_calibration(
    *,
    navigation_session_id: str,
    original_calibration: GestureCalibration,
) -> SessionCalibrationState:
    """Create a session-local adapter state over an immutable original calibration."""

    session_id = _require_exact_str(navigation_session_id, "navigation_session_id")
    if type(original_calibration) is not GestureCalibration:
        raise SessionCalibrationError("INVALID_CALIBRATION_TYPE")
    if (
        original_calibration.platform != BLUESTACKS_PLATFORM
        or original_calibration.profile_id != BLUESTACKS_PROFILE_ID
    ):
        raise SessionCalibrationError("NON_BLUESTACKS_ORIGINAL_CALIBRATION")
    if (
        original_calibration.platform == BLISS_REJECTED_PLATFORM
        or original_calibration.profile_id == BLISS_REJECTED_PROFILE_ID
    ):
        raise SessionCalibrationError("BLISS_CALIBRATION_FORBIDDEN")
    calibration_id = calibration_identity_for(original_calibration)
    original = _snapshot_from_gesture(
        original_calibration, calibration_id=calibration_id, revision=0
    )
    effective = _snapshot_from_gesture(
        original_calibration, calibration_id=calibration_id, revision=0
    )
    return SessionCalibrationState(
        navigation_session_id=session_id,
        platform=original.platform,
        profile_id=original.profile_id,
        calibration_id=calibration_id,
        original=original,
        effective=effective,
        considerations=(),
        accepted_adjustments=(),
        revision_history=(0,),
        adaptation_status=AdaptationStatus.NONE.value,
        next_chronology_ordinal=0,
        last_pan_ordinal=None,
        last_event_ordinal=None,
        expected_chronology_ordinal=0,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _token_match(reason: str, tokens: Sequence[str] | frozenset[str]) -> bool:
    lowered = reason.lower()
    return any(token in lowered for token in tokens)


def _reject(
    state: SessionCalibrationState,
    measurement: SessionCalibrationMeasurement,
    reason: str,
    *,
    proposed: ProposedAdjustment | None = None,
) -> SessionCalibrationState:
    if reason not in _ALLOWED_REJECTION_REASONS:
        raise SessionCalibrationError("INVALID_REJECTION_REASON", reason)
    # Preserve a single terminal evidence-cap record without allowing the
    # immutable in-memory evidence tuple to grow beyond its deterministic bound.
    if (
        len(state.considerations) > MAX_EVIDENCE_COUNT
        and reason == RejectionReason.MAX_EVIDENCE_COUNT.value
    ):
        return state
    chronology = state.next_chronology_ordinal
    consideration = MeasurementConsideration(
        chronology_ordinal=chronology,
        measurement=measurement,
        validation_accepted=False,
        rejection_reason=reason,
        proposed_adjustment=proposed,
        accepted_adjustment=None,
        effective_revision_after=state.effective.revision,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    considerations = state.considerations + (consideration,)
    return SessionCalibrationState(
        navigation_session_id=state.navigation_session_id,
        platform=state.platform,
        profile_id=state.profile_id,
        calibration_id=state.calibration_id,
        original=state.original,
        effective=state.effective,
        considerations=considerations,
        accepted_adjustments=state.accepted_adjustments,
        revision_history=state.revision_history,
        adaptation_status=_adaptation_status_for(considerations, state.accepted_adjustments),
        next_chronology_ordinal=chronology + 1,
        last_pan_ordinal=measurement.pan_ordinal,
        last_event_ordinal=measurement.event_ordinal,
        expected_chronology_ordinal=chronology + 1,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _derive_drag_vector(
    measurement: SessionCalibrationMeasurement, effective: CalibrationSnapshot
) -> Point | str:
    if measurement.drag_vector is not None:
        return measurement.drag_vector
    pred = measurement.predicted
    if abs(pred[0]) < MIN_COMPONENT_ABS and abs(pred[1]) < MIN_COMPONENT_ABS:
        return RejectionReason.NO_PROGRESS.value
    drag_x = -pred[0] / effective.camera_px_per_drag_x
    drag_y = -pred[1] / effective.camera_px_per_drag_y
    return (float(drag_x), float(drag_y))


def _estimate_scales(
    measured: Point, drag: Point, current: CalibrationSnapshot
) -> tuple[float, float] | str:
    est_x = current.camera_px_per_drag_x
    est_y = current.camera_px_per_drag_y
    if abs(drag[0]) >= MIN_COMPONENT_ABS:
        est_x = -measured[0] / drag[0]
    if abs(drag[1]) >= MIN_COMPONENT_ABS:
        est_y = -measured[1] / drag[1]
    if not math.isfinite(est_x) or not math.isfinite(est_y):
        return RejectionReason.NON_FINITE.value
    if est_x <= 0.0 or est_y <= 0.0:
        return RejectionReason.PROHIBITED_NEGATIVE_OR_ZERO_PROGRESS.value
    if (
        est_x < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or est_y < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or est_x > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or est_y > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
    ):
        return RejectionReason.IMPLAUSIBLE.value
    return (float(est_x), float(est_y))


def _validate_measurement_guards(
    state: SessionCalibrationState, measurement: SessionCalibrationMeasurement
) -> str | None:
    if measurement.navigation_session_id != state.navigation_session_id:
        return RejectionReason.CROSS_SESSION.value
    if measurement.platform != state.platform or measurement.platform == BLISS_REJECTED_PLATFORM:
        return RejectionReason.CROSS_PLATFORM.value
    if (
        measurement.profile_id != state.profile_id
        or measurement.profile_id == BLISS_REJECTED_PROFILE_ID
    ):
        return RejectionReason.CROSS_PROFILE.value
    if measurement.calibration_id != state.calibration_id:
        return RejectionReason.CROSS_CALIBRATION.value
    if measurement.calibration_revision != state.effective.revision:
        return RejectionReason.CROSS_CALIBRATION.value
    if measurement.chronology_ordinal != state.expected_chronology_ordinal:
        if measurement.chronology_ordinal < state.expected_chronology_ordinal:
            return RejectionReason.DUPLICATE_SAMPLE.value
        if measurement.chronology_ordinal > state.expected_chronology_ordinal:
            return RejectionReason.MISSING_SAMPLE.value
        return RejectionReason.REORDERED_SAMPLE.value
    if len(state.considerations) >= MAX_EVIDENCE_COUNT:
        return RejectionReason.MAX_EVIDENCE_COUNT.value
    for prior in state.considerations:
        if (
            prior.measurement.pan_ordinal == measurement.pan_ordinal
            and prior.measurement.event_ordinal == measurement.event_ordinal
        ):
            return RejectionReason.DUPLICATE_SAMPLE.value
    if state.last_pan_ordinal is not None:
        if measurement.pan_ordinal < state.last_pan_ordinal:
            return RejectionReason.REORDERED_SAMPLE.value
        if (
            measurement.pan_ordinal == state.last_pan_ordinal
            and state.last_event_ordinal is not None
            and measurement.event_ordinal < state.last_event_ordinal
        ):
            return RejectionReason.REORDERED_SAMPLE.value
        age = measurement.pan_ordinal - state.last_pan_ordinal
        if age > MAX_MEASUREMENT_AGE_PANS:
            return RejectionReason.MEASUREMENT_TOO_OLD.value
    if (
        measurement.source_capture_ordinal is not None
        and measurement.destination_capture_ordinal is not None
        and measurement.destination_capture_ordinal < measurement.source_capture_ordinal
    ):
        return RejectionReason.CROSS_CAPTURE.value
    if (
        measurement.source_capture_ordinal is not None
        and measurement.destination_capture_ordinal is not None
        and measurement.destination_capture_ordinal == measurement.source_capture_ordinal
    ):
        return RejectionReason.STALE.value
    if measurement.stale:
        return RejectionReason.STALE.value
    if measurement.repeated_viewport or _token_match(
        measurement.progress_reason, _REPEATED_VIEWPORT_TOKENS
    ):
        return RejectionReason.REPEATED_VIEWPORT.value
    if measurement.camera_map_clamp or _token_match(measurement.progress_reason, _CLAMP_TOKENS):
        return RejectionReason.CAMERA_MAP_EDGE_CLAMP.value
    if measurement.pan_limit_reached or _token_match(
        measurement.progress_reason, _PAN_LIMIT_TOKENS
    ):
        return RejectionReason.PAN_LIMIT.value
    if measurement.localization_ambiguous:
        return RejectionReason.AMBIGUOUS_LOCALIZATION.value
    if not measurement.localization_recognized or _token_match(
        measurement.progress_reason, _LOCALIZATION_FAIL_TOKENS
    ):
        return RejectionReason.INSUFFICIENT_LOCALIZATION.value
    if measurement.progress_reason not in _ALLOWED_PROGRESS_REASONS:
        return RejectionReason.INVALID_PROGRESS_REASON.value
    reason_lower = measurement.progress_reason.lower()
    if reason_lower in _PROGRESS_WRONG_DIRECTION_TOKENS or "wrong_direction" in reason_lower:
        return RejectionReason.WRONG_DIRECTION.value
    if reason_lower in _PROGRESS_NO_PROGRESS_TOKENS:
        return RejectionReason.NO_PROGRESS.value
    if measurement.progress_px <= 0.0:
        return RejectionReason.PROHIBITED_NEGATIVE_OR_ZERO_PROGRESS.value
    requested = measurement.requested
    measured = measurement.measured
    dot = measured[0] * requested[0] + measured[1] * requested[1]
    if math.hypot(*requested) >= MIN_COMPONENT_ABS and dot < -state.effective.wrong_direction_tolerance_px:
        return RejectionReason.WRONG_DIRECTION.value
    if math.hypot(*measured) < state.effective.minimum_progress_px:
        return RejectionReason.NO_PROGRESS.value
    if measurement.maximum_pans is not None and measurement.pan_ordinal > measurement.maximum_pans:
        return RejectionReason.PAN_LIMIT.value
    # Contradictory: claimed measured progress but predicted/measured disagree on sign strongly
    # while progress_reason claims measured_progress with zero predicted.
    if (
        measurement.progress_reason == "measured_progress"
        and math.hypot(*measurement.predicted) < MIN_COMPONENT_ABS
        and math.hypot(*measurement.measured) >= state.effective.minimum_progress_px
    ):
        return RejectionReason.CONTRADICTORY_SAMPLE.value
    return None


def consider_measurement(
    state: SessionCalibrationState,
    measurement: SessionCalibrationMeasurement,
) -> SessionCalibrationState:
    """Consider one measurement; return a new immutable state (never mutates input)."""

    if type(state) is not SessionCalibrationState:
        raise SessionCalibrationError("INVALID_STATE")
    if type(measurement) is not SessionCalibrationMeasurement:
        raise SessionCalibrationError("INVALID_MEASUREMENT")
    _validate_state_graph(state)
    _validate_measurement(measurement, "measurement")

    guard = _validate_measurement_guards(state, measurement)
    if guard is not None:
        return _reject(state, measurement, guard)

    if len(state.accepted_adjustments) >= MAX_ACCEPTED_ADJUSTMENTS:
        return _reject(state, measurement, RejectionReason.MAX_ACCEPTED_COUNT.value)

    drag = _derive_drag_vector(measurement, state.effective)
    if type(drag) is str:
        return _reject(state, measurement, drag)

    estimates = _estimate_scales(measurement.measured, drag, state.effective)
    if type(estimates) is str:
        return _reject(state, measurement, estimates)
    est_x, est_y = estimates

    cur_x = state.effective.camera_px_per_drag_x
    cur_y = state.effective.camera_px_per_drag_y
    # Outlier relative to current effective scales.
    if (
        abs(est_x / cur_x - 1.0) > OUTLIER_TOLERANCE_RATIO
        or abs(est_y / cur_y - 1.0) > OUTLIER_TOLERANCE_RATIO
    ):
        return _reject(state, measurement, RejectionReason.OUTLIER.value)

    # Bounded influence toward estimate; influence itself is a design limit, not silent clamp
    # of an out-of-bound proposal into validity.
    raw_delta_x = est_x - cur_x
    raw_delta_y = est_y - cur_y
    influence = MAX_PER_MEASUREMENT_INFLUENCE
    delta_x = raw_delta_x * influence
    delta_y = raw_delta_y * influence
    proposed = ProposedAdjustment(
        delta_camera_px_per_drag_x=float(delta_x),
        delta_camera_px_per_drag_y=float(delta_y),
        influence=float(influence),
        estimated_camera_px_per_drag_x=float(est_x),
        estimated_camera_px_per_drag_y=float(est_y),
    )

    if abs(delta_x) > MAX_PER_ADJUSTMENT_SCALE or abs(delta_y) > MAX_PER_ADJUSTMENT_SCALE:
        return _reject(
            state,
            measurement,
            RejectionReason.MAX_PER_ADJUSTMENT.value,
            proposed=proposed,
        )

    new_x = cur_x + delta_x
    new_y = cur_y + delta_y
    if new_x <= 0.0 or new_y <= 0.0:
        return _reject(
            state,
            measurement,
            RejectionReason.INVALID_PROPOSED_ADJUSTMENT.value,
            proposed=proposed,
        )
    if (
        new_x < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or new_y < MIN_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or new_x > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
        or new_y > MAX_PLAUSIBLE_CAMERA_PX_PER_DRAG
    ):
        return _reject(
            state,
            measurement,
            RejectionReason.OUT_OF_BOUND.value,
            proposed=proposed,
        )

    orig = state.original
    drift_x = (new_x / orig.camera_px_per_drag_x) - 1.0
    drift_y = (new_y / orig.camera_px_per_drag_y) - 1.0
    if abs(drift_x) > MAX_TOTAL_DRIFT or abs(drift_y) > MAX_TOTAL_DRIFT:
        return _reject(
            state,
            measurement,
            RejectionReason.MAX_TOTAL_DRIFT.value,
            proposed=proposed,
        )
    if abs(drift_x - drift_y) > MAX_DIRECTIONAL_SKEW:
        return _reject(
            state,
            measurement,
            RejectionReason.DIRECTIONAL_SKEW.value,
            proposed=proposed,
        )

    new_revision = state.effective.revision + 1
    new_effective = CalibrationSnapshot(
        platform=state.effective.platform,
        profile_id=state.effective.profile_id,
        calibration_id=state.calibration_id,
        revision=new_revision,
        drag_origin=state.effective.drag_origin,
        drag_bounds=state.effective.drag_bounds,
        camera_px_per_drag_x=float(new_x),
        camera_px_per_drag_y=float(new_y),
        minimum_drag_px=state.effective.minimum_drag_px,
        maximum_drag_x=state.effective.maximum_drag_x,
        maximum_drag_y=state.effective.maximum_drag_y,
        minimum_progress_px=state.effective.minimum_progress_px,
        wrong_direction_tolerance_px=state.effective.wrong_direction_tolerance_px,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    accepted = AcceptedAdjustment(
        revision=new_revision,
        pan_ordinal=measurement.pan_ordinal,
        event_ordinal=measurement.event_ordinal,
        chronology_ordinal=state.next_chronology_ordinal,
        delta_camera_px_per_drag_x=float(delta_x),
        delta_camera_px_per_drag_y=float(delta_y),
        camera_px_per_drag_x_after=float(new_x),
        camera_px_per_drag_y_after=float(new_y),
        influence=float(influence),
        source_checkpoint=measurement.source_checkpoint,
        destination_checkpoint=measurement.destination_checkpoint,
    )
    chronology = state.next_chronology_ordinal
    consideration = MeasurementConsideration(
        chronology_ordinal=chronology,
        measurement=measurement,
        validation_accepted=True,
        rejection_reason=None,
        proposed_adjustment=proposed,
        accepted_adjustment=accepted,
        effective_revision_after=new_revision,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    considerations = state.considerations + (consideration,)
    accepted_adjustments = state.accepted_adjustments + (accepted,)
    revision_history = state.revision_history + (new_revision,)
    return SessionCalibrationState(
        navigation_session_id=state.navigation_session_id,
        platform=state.platform,
        profile_id=state.profile_id,
        calibration_id=state.calibration_id,
        original=state.original,
        effective=new_effective,
        considerations=considerations,
        accepted_adjustments=accepted_adjustments,
        revision_history=revision_history,
        adaptation_status=_adaptation_status_for(considerations, accepted_adjustments),
        next_chronology_ordinal=chronology + 1,
        last_pan_ordinal=measurement.pan_ordinal,
        last_event_ordinal=measurement.event_ordinal,
        expected_chronology_ordinal=chronology + 1,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _non_dispatch_authority_payload() -> dict[str, Any]:
    try:
        TrustedTransportNonDispatchAuthority(authority_id="session-calibration-probe")
    except NavigationSessionError as exc:
        if exc.reason_code == "NON_DISPATCH_AUTHORITY_UNAVAILABLE":
            return {
                "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
                "reason_code": "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
            }
        return {
            "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
            "reason_code": exc.reason_code,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
            "reason_code": "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
            "detail": type(exc).__name__,
        }
    return {
        "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
        "reason_code": "NON_DISPATCH_AUTHORITY_UNEXPECTEDLY_AVAILABLE",
    }


def _rejection_reason_counts(
    considerations: Sequence[MeasurementConsideration],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in considerations:
        if item.rejection_reason is None:
            continue
        counts[item.rejection_reason] = counts.get(item.rejection_reason, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def report_session_calibration(
    state: SessionCalibrationState,
    *,
    navigation_session: NavigationSession | None = None,
    observability_report: NavigationObservabilityReport | None = None,
) -> Mapping[str, Any]:
    """Deterministic calibration report for HOME-NAVIGATION-OBSERVABILITY consumers.

    Never mutates NavigationSession. Persistence remains unauthorized.
    """

    if type(state) is not SessionCalibrationState:
        raise SessionCalibrationError("INVALID_STATE")
    bounded_drift = _validate_state_and_derive_report_values(state)

    obs_integration: dict[str, Any]
    if observability_report is not None:
        try:
            if type(observability_report) is not NavigationObservabilityReport:
                raise SessionCalibrationError("INVALID_OBSERVABILITY_REPORT")
            if observability_report.navigation_session_id != state.navigation_session_id:
                raise SessionCalibrationError("OBSERVABILITY_SESSION_MISMATCH")
            obs_integration = {
                "schema_name": observability_report.schema_name,
                "schema_version": observability_report.schema_version,
                "navigation_session_id": observability_report.navigation_session_id,
                "report_integrity": observability_report.report_integrity,
                "requested_present": observability_report.requested_atlas_displacement.availability,
                "measured_present": observability_report.measured_atlas_displacement.availability,
                "residual_present": observability_report.residual_vector.availability,
                "mutates_session_ledger": False,
            }
        except SessionCalibrationError:
            raise
        except Exception as exc:
            raise SessionCalibrationError("INVALID_OBSERVABILITY_REPORT") from exc
    elif navigation_session is not None:
        try:
            if type(navigation_session) is not NavigationSession:
                raise SessionCalibrationError("INVALID_NAVIGATION_SESSION")
            if navigation_session.navigation_session_id != state.navigation_session_id:
                raise SessionCalibrationError("SESSION_ID_MISMATCH")
            built = report_navigation_session(navigation_session)
            obs_integration = {
                "schema_name": built.schema_name,
                "schema_version": built.schema_version,
                "navigation_session_id": built.navigation_session_id,
                "report_integrity": built.report_integrity,
                "requested_present": built.requested_atlas_displacement.availability,
                "measured_present": built.measured_atlas_displacement.availability,
                "residual_present": built.residual_vector.availability,
                "mutates_session_ledger": False,
            }
        except SessionCalibrationError:
            raise
        except Exception as exc:
            raise SessionCalibrationError("INVALID_NAVIGATION_SESSION") from exc
    else:
        obs_integration = {
            "schema_name": None,
            "schema_version": None,
            "navigation_session_id": state.navigation_session_id,
            "report_integrity": "unavailable",
            "requested_present": "unavailable",
            "measured_present": "unavailable",
            "residual_present": "unavailable",
            "mutates_session_ledger": False,
        }

    rejected = sum(1 for item in state.considerations if not item.validation_accepted)
    payload = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "navigation_session_id": state.navigation_session_id,
        "platform": state.platform,
        "profile_id": state.profile_id,
        "calibration_id": state.calibration_id,
        "original_calibration": state.original.to_dict(),
        "effective_calibration": state.effective.to_dict(),
        "effective_revision": state.effective.revision,
        "adaptation_status": state.adaptation_status,
        "accepted_adjustment_count": len(state.accepted_adjustments),
        "considered_measurement_count": len(state.considerations),
        "rejected_measurement_count": rejected,
        "rejection_reason_counts": _rejection_reason_counts(state.considerations),
        "bounded_drift": bounded_drift.to_dict(),
        "revision_history": list(state.revision_history),
        "considerations": [item.to_dict() for item in state.considerations],
        "persistence_authorized": False,
        "authorize_dispatch": False,
        "capability_grant": None,
        "non_dispatch_authority": _non_dispatch_authority_payload(),
        "observability_integration": obs_integration,
    }
    if tuple(payload.keys()) != REPORT_FIELD_ORDER:
        raise SessionCalibrationError("REPORT_FIELD_ORDER_MISMATCH")
    _validate_report_payload(_plain(_freeze_json(payload, "report")))
    return MappingProxyType(_freeze_json(payload, "report"))


def serialize_session_calibration_report(report: Mapping[str, Any]) -> str:
    """Versioned deterministic strict JSON. Does not authorize persistence."""

    if type(report) not in (dict, MappingProxyType):
        raise SessionCalibrationError("INVALID_REPORT")
    plain = _plain(_freeze_json(dict(report), "report"))
    _validate_report_payload(plain)
    text = json.dumps(plain, sort_keys=False, separators=(",", ":"), allow_nan=False)
    # Round-trip revalidation against forged graphs.
    deserialize_session_calibration_report(text)
    return text


def deserialize_session_calibration_report(text: str) -> Mapping[str, Any]:
    if type(text) is not str or not text:
        raise SessionCalibrationError("INVALID_SERIALIZED_REPORT")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise SessionCalibrationError("DUPLICATE_JSON_KEY", key)
            seen.add(key)
            out[key] = value
        return out

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicate_pairs, parse_constant=lambda _c: (_ for _ in ()).throw(SessionCalibrationError("NON_FINITE")))
    except SessionCalibrationError:
        raise
    except json.JSONDecodeError as exc:
        raise SessionCalibrationError("INVALID_JSON", str(exc)) from exc
    if type(payload) is not dict:
        raise SessionCalibrationError("INVALID_REPORT_ROOT")
    _validate_report_payload(payload)
    return MappingProxyType(_freeze_json(payload, "report"))


def assert_no_persistence_api() -> None:
    """Honesty seam: this module exposes no disk/profile persistence writer."""

    forbidden = (
        "save_session_calibration",
        "persist_session_calibration",
        "write_calibration_profile",
        "store_learned_calibration",
    )
    module_globals = globals()
    for name in forbidden:
        if name in module_globals:
            raise SessionCalibrationError("PERSISTENCE_API_PRESENT", name)