"""Deterministic offline observability over an existing NavigationSession ledger.

This module is read-only. It never mutates session state, never persists a second
store, never invents missing measurements or transport, and never grants dispatch
authority. Requested, authorized, dispatched, transport-confirmed, and verified
remain distinct. Absent or non-finite data stays explicitly unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tasks.navigation_session import (
    ActionLedgerEntry,
    ContinuationMode,
    DisplacementRecord,
    FrameIdentityRecord,
    HistoricalBindingRecord,
    LedgerStatus,
    NavigationCheckpoint,
    NavigationSession,
    NavigationSessionError,
    SessionOutcome,
    TrustedTransportNonDispatchAuthority,
    UncertainPreparedResolution,
    validate_session,
)


SCHEMA_NAME = "navigation_session_observability"
SCHEMA_VERSION = 1

REPORT_FIELD_ORDER: tuple[str, ...] = (
    "schema_name",
    "schema_version",
    "navigation_session_id",
    "route_id",
    "runtime_capture_session_id",
    "report_integrity",
    "source_checkpoint",
    "terminal_checkpoint",
    "localization_confidence",
    "requested_atlas_displacement",
    "measured_atlas_displacement",
    "residual_vector",
    "direction_agreement",
    "progress_ratio",
    "correction_count",
    "repeated_viewports",
    "camera_map_clamps",
    "semantic_facility_binding_confidence",
    "radial_binding_confidence",
    "safe_exit_availability",
    "state_timing",
    "total_frame_count",
    "per_state_frame_counts",
    "pan_attempt_history",
    "action_ledger_summary",
    "continuation_history",
    "recovery_only_history",
    "action_authority_separation",
    "terminal_state",
    "non_dispatch_authority",
)

_CLAMP_REASON_TOKENS = ("clamp", "map_edge")
_REPEATED_VIEWPORT_TOKENS = ("repeated_viewport",)


class NavigationObservabilityError(ValueError):
    """Fail-closed observability denial with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class FieldAvailability(str, Enum):
    PRESENT = "present"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    CONTRADICTORY = "contradictory"
    MALFORMED = "malformed"


class ReportIntegrity(str, Enum):
    VALID = "valid"
    INCOMPLETE = "incomplete"
    MALFORMED = "malformed"
    CONTRADICTORY = "contradictory"


class TerminalReportClass(str, Enum):
    SUCCESS = "success"
    REJECTION = "rejection"
    INCOMPLETE = "incomplete"
    UNCERTAIN = "uncertain"
    CONTRADICTORY = "contradictory"
    MALFORMED = "malformed"


class DirectionAgreement(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    ORTHOGONAL = "orthogonal"
    UNKNOWN = "unknown"


class SafeExitAvailability(str, Enum):
    VERIFIED = "verified"
    NOT_REPRESENTED = "not_represented"
    UNKNOWN = "unknown"


_ALLOWED_AVAILABILITIES = frozenset(item.value for item in FieldAvailability)
_ALLOWED_REPORT_INTEGRITIES = frozenset(item.value for item in ReportIntegrity)
_ALLOWED_TERMINAL_CLASSES = frozenset(item.value for item in TerminalReportClass)
_ALLOWED_DIRECTIONS = frozenset(item.value for item in DirectionAgreement)
_ALLOWED_SAFE_EXIT_VALUES = frozenset(item.value for item in SafeExitAvailability)
_ALLOWED_CHECKPOINTS = frozenset(item.value for item in NavigationCheckpoint)
_ALLOWED_LEDGER_STATUSES = frozenset(item.value for item in LedgerStatus)
_ALLOWED_ROUTE_STATUSES = frozenset(
    {"active", "blocked", "uncertain", "dry_run", "leg_complete", "completed"}
)
_ALLOWED_PAN_PHASES = frozenset(
    {"planned", "measured", "mixed", "reason_only", "empty", "malformed"}
)


@dataclass(frozen=True)
class AvailabilityValue:
    availability: str
    value: Any = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        if type(self.availability) is not str or self.availability not in _ALLOWED_AVAILABILITIES:
            raise NavigationObservabilityError("INVALID_AVAILABILITY")
        if type(self.reason_code) is not str:
            raise NavigationObservabilityError("INVALID_REASON_CODE")
        frozen_value = _freeze_json(self.value, "availability_value")
        object.__setattr__(self, "value", frozen_value)


@dataclass(frozen=True)
class VectorReport:
    availability: str
    x: float | None = None
    y: float | None = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        if type(self.availability) is not str or self.availability not in _ALLOWED_AVAILABILITIES:
            raise NavigationObservabilityError("INVALID_AVAILABILITY")
        if type(self.reason_code) is not str:
            raise NavigationObservabilityError("INVALID_REASON_CODE")
        if self.availability == FieldAvailability.PRESENT.value:
            if (
                type(self.x) is not float
                or type(self.y) is not float
                or not math.isfinite(self.x)
                or not math.isfinite(self.y)
            ):
                raise NavigationObservabilityError("INVALID_VECTOR_COMPONENT")
        elif self.x is not None or self.y is not None:
            raise NavigationObservabilityError("INVALID_VECTOR_COMPONENT")


@dataclass(frozen=True)
class PanAttemptReport:
    pan_ordinal: int | None
    event_ordinal: int | None
    phase: str
    requested: VectorReport
    predicted: VectorReport
    measured: VectorReport
    residual: VectorReport
    progress_px: AvailabilityValue
    reason: AvailabilityValue
    capture_ordinal: int | None = None

    def __post_init__(self) -> None:
        if type(self.phase) is not str or self.phase not in _ALLOWED_PAN_PHASES:
            raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_PHASE")
        for name in ("pan_ordinal", "event_ordinal", "capture_ordinal"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_ORDINAL", name)
        for name in ("requested", "predicted", "measured", "residual"):
            if type(getattr(self, name)) is not VectorReport:
                raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_VECTOR", name)
        for name in ("progress_px", "reason"):
            if type(getattr(self, name)) is not AvailabilityValue:
                raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_VALUE", name)


@dataclass(frozen=True)
class ActionLedgerSummary:
    total_entries: int
    prepared_count: int
    dispatched_count: int
    reconciled_count: int
    suppressed_count: int
    unknown_status_count: int
    entries: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for name in (
            "total_entries",
            "prepared_count",
            "dispatched_count",
            "reconciled_count",
            "suppressed_count",
            "unknown_status_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_COUNT", name)
        if type(self.entries) is not tuple:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRIES")
        frozen_entries: list[MappingProxyType] = []
        for entry in self.entries:
            if type(entry) not in (dict, MappingProxyType):
                raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY")
            frozen = _freeze_json(entry, "ledger_summary_entry")
            if type(frozen) is not MappingProxyType:
                raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY")
            frozen_entries.append(frozen)
        object.__setattr__(self, "entries", tuple(frozen_entries))
        if self.total_entries != len(self.entries):
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_TOTAL")
        if (
            self.prepared_count
            + self.dispatched_count
            + self.reconciled_count
            + self.suppressed_count
            + self.unknown_status_count
            != self.total_entries
        ):
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_COUNTS")


@dataclass(frozen=True)
class ActionAuthoritySeparation:
    requested: AvailabilityValue
    authorized: AvailabilityValue
    dispatched: AvailabilityValue
    transport_confirmed: AvailabilityValue
    verified: AvailabilityValue

    def __post_init__(self) -> None:
        for name in (
            "requested",
            "authorized",
            "dispatched",
            "transport_confirmed",
            "verified",
        ):
            value = getattr(self, name)
            if type(value) is not AvailabilityValue:
                raise NavigationObservabilityError("INVALID_AUTHORITY_FIELD", name)
            _validate_availability_value(value)


@dataclass(frozen=True)
class NavigationObservabilityReport:
    schema_name: str
    schema_version: int
    navigation_session_id: str
    route_id: str
    runtime_capture_session_id: str
    report_integrity: str
    source_checkpoint: AvailabilityValue
    terminal_checkpoint: AvailabilityValue
    localization_confidence: AvailabilityValue
    requested_atlas_displacement: VectorReport
    measured_atlas_displacement: VectorReport
    residual_vector: VectorReport
    direction_agreement: AvailabilityValue
    progress_ratio: AvailabilityValue
    correction_count: AvailabilityValue
    repeated_viewports: AvailabilityValue
    camera_map_clamps: AvailabilityValue
    semantic_facility_binding_confidence: AvailabilityValue
    radial_binding_confidence: AvailabilityValue
    safe_exit_availability: AvailabilityValue
    state_timing: AvailabilityValue
    total_frame_count: AvailabilityValue
    per_state_frame_counts: AvailabilityValue
    pan_attempt_history: tuple[PanAttemptReport, ...]
    action_ledger_summary: ActionLedgerSummary
    continuation_history: AvailabilityValue
    recovery_only_history: AvailabilityValue
    action_authority_separation: ActionAuthoritySeparation
    terminal_state: AvailabilityValue
    non_dispatch_authority: AvailabilityValue

    def __post_init__(self) -> None:
        _validate_report(self)


def report_navigation_session(session: NavigationSession) -> NavigationObservabilityReport:
    """Build an immutable observability report from an existing NavigationSession.

    The supplied session object is never mutated. Missing or non-finite ledger
    fields remain explicit unknowns. Transport is never inferred from absence.
    """

    if type(session) is not NavigationSession:
        raise NavigationObservabilityError("INVALID_SESSION")

    integrity = ReportIntegrity.VALID
    integrity_reason = ""
    try:
        validate_session(session)
    except NavigationSessionError as exc:
        integrity = ReportIntegrity.MALFORMED
        integrity_reason = exc.reason_code
    except Exception:
        integrity = ReportIntegrity.MALFORMED
        integrity_reason = "SESSION_VALIDATION_FAILED"

    snapshot = _snapshot_session(session)
    if integrity is ReportIntegrity.VALID:
        malformed_reason = _snapshot_malformed_reason(snapshot)
        if malformed_reason is not None:
            integrity = ReportIntegrity.MALFORMED
            integrity_reason = malformed_reason
        else:
            contradiction = _detect_contradiction(snapshot)
            if contradiction is not None:
                integrity = ReportIntegrity.CONTRADICTORY
                integrity_reason = contradiction
            elif snapshot.outcome is SessionOutcome.ACTIVE and snapshot.terminal_reason:
                integrity = ReportIntegrity.INCOMPLETE
                integrity_reason = "ACTIVE_WITH_TERMINAL_REASON"
            elif snapshot.outcome is SessionOutcome.ACTIVE:
                integrity = ReportIntegrity.INCOMPLETE
                integrity_reason = "SESSION_ACTIVE"

    pan_attempts = _pan_attempt_history(snapshot)
    requested, measured, residual = _aggregate_displacements(pan_attempts)
    direction = _direction_agreement(requested, measured)
    progress = _progress_ratio(requested, measured, pan_attempts)
    terminal = _terminal_state(snapshot, integrity, integrity_reason)
    authority = _action_authority_separation(snapshot)

    report = NavigationObservabilityReport(
        schema_name=SCHEMA_NAME,
        schema_version=SCHEMA_VERSION,
        navigation_session_id=snapshot.navigation_session_id,
        route_id=snapshot.route_id,
        runtime_capture_session_id=snapshot.runtime_capture_session_id,
        report_integrity=integrity.value,
        source_checkpoint=_checkpoint_field(snapshot.checkpoint_history, index=0),
        terminal_checkpoint=_checkpoint_field(snapshot.checkpoint_history, index=-1),
        localization_confidence=_localization_confidence(snapshot),
        requested_atlas_displacement=requested,
        measured_atlas_displacement=measured,
        residual_vector=residual,
        direction_agreement=direction,
        progress_ratio=progress,
        correction_count=_correction_count(snapshot),
        repeated_viewports=_repeated_viewports(snapshot),
        camera_map_clamps=_camera_map_clamps(snapshot),
        semantic_facility_binding_confidence=_facility_binding_confidence(snapshot),
        radial_binding_confidence=_radial_binding_confidence(snapshot),
        safe_exit_availability=_safe_exit_availability(snapshot),
        state_timing=_state_timing(snapshot),
        total_frame_count=_total_frame_count(snapshot),
        per_state_frame_counts=_per_state_frame_counts(snapshot),
        pan_attempt_history=pan_attempts,
        action_ledger_summary=_action_ledger_summary(snapshot),
        continuation_history=_continuation_history(snapshot),
        recovery_only_history=_recovery_only_history(snapshot),
        action_authority_separation=authority,
        terminal_state=terminal,
        non_dispatch_authority=_non_dispatch_authority(),
    )
    # Revalidate public schema before return.
    _validate_report(report)
    return report


def _snapshot_malformed_reason(snapshot: _SessionSnapshot) -> str | None:
    if snapshot.malformed_fields:
        return snapshot.malformed_fields[0]
    if type(snapshot.checkpoint_history) is not tuple or any(
        type(item) is not str or item not in _ALLOWED_CHECKPOINTS
        for item in snapshot.checkpoint_history
    ):
        return "CHECKPOINT_HISTORY_SCHEMA_INVALID"
    if type(snapshot.seen_viewports) is not tuple:
        return "SEEN_VIEWPORTS_SCHEMA_INVALID"
    for viewport in snapshot.seen_viewports:
        if (
            type(viewport) is not tuple
            or len(viewport) != 2
            or type(viewport[0]) is not int
            or type(viewport[1]) is not int
        ):
            return "SEEN_VIEWPORT_SCHEMA_INVALID"
    if type(snapshot.displacement_history) is not tuple:
        return "DISPLACEMENT_HISTORY_SCHEMA_INVALID"
    for record in snapshot.displacement_history:
        if type(record) is not DisplacementRecord:
            return "DISPLACEMENT_RECORD_SCHEMA_INVALID"
        if (
            type(record.pan_ordinal) is not int
            or record.pan_ordinal < 0
            or type(record.event_ordinal) is not int
            or record.event_ordinal < 0
            or _finite_point(record.requested) is None
            or _finite_point(record.predicted) is None
            or _finite_point(record.measured) is None
            or _finite_point(record.residual) is None
            or type(record.progress_px) is not float
            or not math.isfinite(record.progress_px)
            or type(record.reason) is not str
        ):
            return "DISPLACEMENT_RECORD_FIELD_INVALID"
    if type(snapshot.known_frame_identities) is not tuple:
        return "FRAME_IDENTITY_COLLECTION_INVALID"
    for frame in snapshot.known_frame_identities:
        if type(frame) is not FrameIdentityRecord:
            return "FRAME_IDENTITY_RECORD_INVALID"
        if (
            type(frame.capture_kind) is not str
            or not frame.capture_kind
            or type(frame.runtime_capture_session_id) is not str
            or not frame.runtime_capture_session_id
            or type(frame.capture_ordinal) is not int
            or frame.capture_ordinal < 1
            or type(frame.capture_completed_monotonic) is not float
            or not math.isfinite(frame.capture_completed_monotonic)
            or frame.capture_completed_monotonic < 0.0
            or type(frame.transport_sha256) is not str
            or not frame.transport_sha256
            or type(frame.semantic_sha256) is not str
            or not frame.semantic_sha256
            or type(frame.runtime_profile_id) is not str
            or not frame.runtime_profile_id
            or type(frame.width) is not int
            or frame.width <= 0
            or type(frame.height) is not int
            or frame.height <= 0
            or type(frame.label) is not str
        ):
            return "FRAME_TIMING_INVALID"
    if type(snapshot.action_ledger) is not tuple:
        return "ACTION_LEDGER_COLLECTION_INVALID"
    for entry in snapshot.action_ledger:
        if type(entry) is not ActionLedgerEntry:
            return "ACTION_LEDGER_ENTRY_INVALID"
        if (
            type(entry.action_key) is not str
            or not entry.action_key
            or type(entry.kind) is not str
            or not entry.kind
            or type(entry.target_identity) is not str
            or not entry.target_identity
            or type(entry.status) is not LedgerStatus
            or type(entry.pan_ordinal) is not int
            or entry.pan_ordinal < 0
            or type(entry.event_ordinal) is not int
            or entry.event_ordinal < 0
            or type(entry.source_frame) is not FrameIdentityRecord
            or type(entry.source_frame.capture_ordinal) is not int
            or entry.source_frame.capture_ordinal < 1
            or type(entry.source_frame.capture_completed_monotonic) is not float
            or not math.isfinite(entry.source_frame.capture_completed_monotonic)
            or (
                entry.pre_uncertainty_status is not None
                and (
                    type(entry.pre_uncertainty_status) is not str
                    or entry.pre_uncertainty_status not in _ALLOWED_LEDGER_STATUSES
                )
            )
            or type(entry.gesture_fingerprint) is not str
        ):
            return "ACTION_LEDGER_ENTRY_FIELD_INVALID"
    if type(snapshot.historical_bindings) is not tuple or any(
        type(item) is not HistoricalBindingRecord for item in snapshot.historical_bindings
    ):
        return "HISTORICAL_BINDING_INVALID"
    bindings = list(snapshot.historical_bindings)
    if snapshot.current_binding is not None:
        if type(snapshot.current_binding) is not HistoricalBindingRecord:
            return "CURRENT_BINDING_INVALID"
        bindings.append(snapshot.current_binding)
    for binding in bindings:
        if (
            type(binding.building_id) is not str
            or not binding.building_id
            or type(binding.frame_semantic_sha256) is not str
            or not binding.frame_semantic_sha256
            or type(binding.confidence) is not float
            or not math.isfinite(binding.confidence)
            or type(binding.stale) is not bool
            or (
                binding.historical_target_roi is not None
                and (
                    type(binding.historical_target_roi) is not tuple
                    or len(binding.historical_target_roi) != 4
                    or any(
                        type(item) is not int for item in binding.historical_target_roi
                    )
                )
            )
        ):
            return "BINDING_FIELD_INVALID"
    for name in ("pending_suppressions", "pending_gesture_suppressions"):
        values = getattr(snapshot, name)
        if type(values) is not tuple or any(type(item) is not str for item in values):
            return f"{name.upper()}_INVALID"
    if snapshot.observation_summary is not None and type(snapshot.observation_summary) is not str:
        return "OBSERVATION_SUMMARY_INVALID"
    if snapshot.localization_recognized is not None and type(snapshot.localization_recognized) is not bool:
        return "LOCALIZATION_RECOGNIZED_INVALID"
    for name in ("localization_confidence", "localization_residual_px"):
        value = getattr(snapshot, name)
        if value is not None and (type(value) is not float or not math.isfinite(value)):
            return f"{name.upper()}_INVALID"
    if snapshot.route_status is not None and snapshot.route_status not in _ALLOWED_ROUTE_STATUSES:
        return "ROUTE_STATUS_INVALID"
    return None


def serialize_navigation_observability_report(report: NavigationObservabilityReport) -> str:
    """Deterministic JSON-safe serialization with fixed field order and revalidation."""

    if type(report) is not NavigationObservabilityReport:
        raise NavigationObservabilityError("INVALID_REPORT")
    _validate_report(report)
    payload = navigation_observability_snapshot(report)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    reloaded = json.loads(text)
    if list(reloaded.keys()) != list(REPORT_FIELD_ORDER):
        raise NavigationObservabilityError("NON_DETERMINISTIC_FIELD_ORDER")
    revalidated = _report_from_snapshot(reloaded)
    _validate_report(revalidated)
    return text


def deserialize_navigation_observability_report(
    serialized: str,
) -> NavigationObservabilityReport:
    """Strictly deserialize and revalidate a report snapshot."""

    if type(serialized) is not str:
        raise NavigationObservabilityError("INVALID_SERIALIZED_REPORT")

    def reject_constant(value: str) -> object:
        raise NavigationObservabilityError("NON_FINITE_SERIALIZED_VALUE", value)

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise NavigationObservabilityError("DUPLICATE_SERIALIZED_KEY", key)
            result[key] = value
        return result

    try:
        payload = json.loads(
            serialized,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_pairs,
        )
    except NavigationObservabilityError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NavigationObservabilityError("INVALID_SERIALIZED_REPORT") from exc
    return _report_from_snapshot(payload)


def navigation_observability_snapshot(report: NavigationObservabilityReport) -> dict[str, Any]:
    """Ordered plain dict suitable for JSON. Never retains NumPy or frame buffers."""

    if type(report) is not NavigationObservabilityReport:
        raise NavigationObservabilityError("INVALID_REPORT")
    _validate_report(report)
    payload = {
        "schema_name": report.schema_name,
        "schema_version": report.schema_version,
        "navigation_session_id": report.navigation_session_id,
        "route_id": report.route_id,
        "runtime_capture_session_id": report.runtime_capture_session_id,
        "report_integrity": report.report_integrity,
        "source_checkpoint": _availability_to_dict(report.source_checkpoint),
        "terminal_checkpoint": _availability_to_dict(report.terminal_checkpoint),
        "localization_confidence": _availability_to_dict(report.localization_confidence),
        "requested_atlas_displacement": _vector_to_dict(report.requested_atlas_displacement),
        "measured_atlas_displacement": _vector_to_dict(report.measured_atlas_displacement),
        "residual_vector": _vector_to_dict(report.residual_vector),
        "direction_agreement": _availability_to_dict(report.direction_agreement),
        "progress_ratio": _availability_to_dict(report.progress_ratio),
        "correction_count": _availability_to_dict(report.correction_count),
        "repeated_viewports": _availability_to_dict(report.repeated_viewports),
        "camera_map_clamps": _availability_to_dict(report.camera_map_clamps),
        "semantic_facility_binding_confidence": _availability_to_dict(
            report.semantic_facility_binding_confidence
        ),
        "radial_binding_confidence": _availability_to_dict(report.radial_binding_confidence),
        "safe_exit_availability": _availability_to_dict(report.safe_exit_availability),
        "state_timing": _availability_to_dict(report.state_timing),
        "total_frame_count": _availability_to_dict(report.total_frame_count),
        "per_state_frame_counts": _availability_to_dict(report.per_state_frame_counts),
        "pan_attempt_history": [_pan_attempt_to_dict(item) for item in report.pan_attempt_history],
        "action_ledger_summary": _ledger_summary_to_dict(report.action_ledger_summary),
        "continuation_history": _availability_to_dict(report.continuation_history),
        "recovery_only_history": _availability_to_dict(report.recovery_only_history),
        "action_authority_separation": {
            "requested": _availability_to_dict(report.action_authority_separation.requested),
            "authorized": _availability_to_dict(report.action_authority_separation.authorized),
            "dispatched": _availability_to_dict(report.action_authority_separation.dispatched),
            "transport_confirmed": _availability_to_dict(
                report.action_authority_separation.transport_confirmed
            ),
            "verified": _availability_to_dict(report.action_authority_separation.verified),
        },
        "terminal_state": _availability_to_dict(report.terminal_state),
        "non_dispatch_authority": _availability_to_dict(report.non_dispatch_authority),
    }
    if tuple(payload.keys()) != REPORT_FIELD_ORDER:
        raise NavigationObservabilityError("FIELD_ORDER_MISMATCH")
    _assert_json_safe(payload, "report_snapshot")
    return payload


@dataclass(frozen=True)
class _SessionSnapshot:
    navigation_session_id: object
    route_id: object
    runtime_capture_session_id: object
    checkpoint: object
    outcome: object
    terminal_reason: object
    continuation_mode: object
    event_ordinal: object
    pan_ordinal: object
    maximum_pans: object
    localization_confidence: object
    localization_recognized: object
    localization_residual_px: object
    observation_summary: object
    displacement_history: object
    seen_viewports: object
    action_ledger: object
    known_frame_identities: object
    historical_bindings: object
    current_binding: object
    checkpoint_history: object
    route_corrections: object
    route_continuations: object
    route_status: object
    route_reason: object
    pending_suppressions: object
    pending_gesture_suppressions: object
    malformed_fields: tuple[str, ...]


def _snapshot_session(session: NavigationSession) -> _SessionSnapshot:
    malformed: list[str] = []

    def raw(name: str, default: object = None) -> object:
        try:
            return getattr(session, name)
        except Exception:
            malformed.append(name)
            return default

    def identity(name: str, *, allow_empty: bool = False) -> object:
        value = raw(name)
        if type(value) is str and (allow_empty or bool(value)):
            return value
        malformed.append(name)
        return None

    def optional_string(name: str) -> object:
        value = raw(name)
        if value is None or type(value) is str:
            return value
        malformed.append(name)
        return None

    def enum_value(name: str, enum_type: type[Enum]) -> object:
        value = raw(name)
        if isinstance(value, enum_type):
            return value
        malformed.append(name)
        return None

    def exact_nonnegative_int(name: str) -> object:
        value = raw(name)
        if type(value) is int and value >= 0:
            return value
        malformed.append(name)
        return None

    def collection(name: str) -> object:
        value = raw(name)
        if type(value) in (list, tuple):
            return tuple(value)
        malformed.append(name)
        return ()

    observation = raw("latest_observation")
    if observation is None:
        malformed.append("latest_observation")
        observation_confidence = None
        observation_recognized = None
        observation_residual = None
        observation_summary = None
    else:
        observation_confidence = getattr(observation, "localization_confidence", None)
        observation_recognized = getattr(observation, "localization_recognized", None)
        observation_residual = getattr(observation, "localization_residual_px", None)
        observation_summary = getattr(observation, "summary", None)
        if type(observation_summary) is not str:
            malformed.append("latest_observation.summary")
            observation_summary = None

    route = raw("route_result")
    if route is None:
        malformed.append("route_result")
        route_continuations = None
        route_status = None
        route_reason = None
        route_corrections = ()
    else:
        route_pan_count = getattr(route, "pan_count", None)
        if type(route_pan_count) is not int or route_pan_count < 0:
            malformed.append("route_result.pan_count")
        route_continuations = getattr(route, "continuations", None)
        if type(route_continuations) is not int or route_continuations < 0:
            malformed.append("route_result.continuations")
            route_continuations = None
        route_status = getattr(route, "status", None)
        if type(route_status) is not str:
            malformed.append("route_result.status")
            route_status = None
        route_reason = getattr(route, "reason", None)
        if type(route_reason) is not str:
            malformed.append("route_result.reason")
            route_reason = None
        raw_corrections = getattr(route, "corrections", None)
        if type(raw_corrections) in (list, tuple) and all(
            type(item) is str for item in raw_corrections
        ):
            route_corrections = tuple(raw_corrections)
        else:
            malformed.append("route_result.corrections")
            route_corrections = ()

    return _SessionSnapshot(
        navigation_session_id=identity("navigation_session_id"),
        route_id=identity("route_id"),
        runtime_capture_session_id=identity("runtime_capture_session_id", allow_empty=True),
        checkpoint=enum_value("checkpoint", NavigationCheckpoint),
        outcome=enum_value("outcome", SessionOutcome),
        terminal_reason=optional_string("terminal_reason"),
        continuation_mode=enum_value("continuation_mode", ContinuationMode),
        event_ordinal=exact_nonnegative_int("event_ordinal"),
        pan_ordinal=exact_nonnegative_int("pan_ordinal"),
        maximum_pans=exact_nonnegative_int("maximum_pans"),
        localization_confidence=observation_confidence,
        localization_recognized=observation_recognized,
        localization_residual_px=observation_residual,
        observation_summary=observation_summary,
        displacement_history=collection("displacement_history"),
        seen_viewports=collection("seen_viewports"),
        action_ledger=collection("action_ledger"),
        known_frame_identities=collection("known_frame_identities"),
        historical_bindings=collection("historical_bindings"),
        current_binding=raw("current_binding"),
        checkpoint_history=collection("checkpoint_history"),
        route_corrections=route_corrections,
        route_continuations=route_continuations,
        route_status=route_status,
        route_reason=route_reason,
        pending_suppressions=collection("pending_suppressions"),
        pending_gesture_suppressions=collection("pending_gesture_suppressions"),
        malformed_fields=tuple(dict.fromkeys(malformed)),
    )


def _detect_contradiction(snapshot: _SessionSnapshot) -> str | None:
    if not snapshot.checkpoint_history:
        return "CHECKPOINT_HISTORY_EMPTY"
    if snapshot.checkpoint_history[-1] != snapshot.checkpoint.value:
        return "CHECKPOINT_HISTORY_END_MISMATCH"
    if snapshot.outcome is SessionOutcome.COMPLETED:
        if snapshot.checkpoint is NavigationCheckpoint.HOME_RECOVERED:
            return None
        if snapshot.route_status in ("completed", "dry_run", "leg_complete") and snapshot.checkpoint in (
            NavigationCheckpoint.TARGET_BOUND,
            NavigationCheckpoint.HOME_RECOVERED,
        ):
            return None
        return "COMPLETED_WITHOUT_TERMINAL_SUCCESS"
    if snapshot.checkpoint is NavigationCheckpoint.HOME_RECOVERED and snapshot.outcome is not SessionOutcome.COMPLETED:
        return "HOME_RECOVERED_OUTCOME_MISMATCH"
    if snapshot.outcome is SessionOutcome.BLOCKED and not snapshot.terminal_reason:
        return "BLOCKED_WITHOUT_REASON"
    return None


def _checkpoint_field(history: Sequence[str], *, index: int) -> AvailabilityValue:
    if type(history) is not tuple:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "CHECKPOINT_HISTORY_TYPE")
    if not history:
        return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "CHECKPOINT_HISTORY_ABSENT")
    try:
        raw = history[index]
    except IndexError:
        return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "CHECKPOINT_INDEX_MISSING")
    if type(raw) is not str or not raw:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "CHECKPOINT_VALUE_INVALID")
    try:
        checkpoint = NavigationCheckpoint(raw)
    except ValueError:
        return AvailabilityValue(
            FieldAvailability.MALFORMED.value,
            None,
            "CHECKPOINT_VALUE_UNKNOWN",
        )
    return AvailabilityValue(FieldAvailability.PRESENT.value, checkpoint.value, "")


def _localization_confidence(snapshot: _SessionSnapshot) -> AvailabilityValue:
    value = snapshot.localization_confidence
    if value is None:
        return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "LOCALIZATION_CONFIDENCE_ABSENT")
    if type(value) is not float:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "LOCALIZATION_CONFIDENCE_TYPE")
    if not math.isfinite(value):
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "LOCALIZATION_CONFIDENCE_NON_FINITE")
    return AvailabilityValue(FieldAvailability.PRESENT.value, value, "")


def _finite_point(point: object) -> tuple[float, float] | None:
    if type(point) not in (tuple, list) or len(point) != 2:
        return None
    x, y = point
    if type(x) is not float or type(y) is not float:
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return (x, y)


def _vector_present(point: tuple[float, float], *, reason_code: str = "") -> VectorReport:
    return VectorReport(FieldAvailability.PRESENT.value, point[0], point[1], reason_code)


def _vector_unknown(reason_code: str) -> VectorReport:
    return VectorReport(FieldAvailability.UNKNOWN.value, None, None, reason_code)


def _vector_unavailable(reason_code: str) -> VectorReport:
    return VectorReport(FieldAvailability.UNAVAILABLE.value, None, None, reason_code)


def _classify_displacement_phase(record: DisplacementRecord) -> str:
    measured = _finite_point(record.measured)
    requested = _finite_point(record.requested)
    predicted = _finite_point(record.predicted)
    progress = record.progress_px if type(record.progress_px) is float else None
    reason = record.reason if type(record.reason) is str else ""
    has_measure = measured is not None and (
        measured != (0.0, 0.0)
        or (progress is not None and progress != 0.0)
        or "progress" in reason
        or "measured" in reason
        or reason
        in (
            "measured_progress",
            "no_measured_progress",
            "movement_wrong_direction",
            "repeated_viewport",
            "post_pan_localization_failed",
            "post_pan_localization_invalid",
        )
    )
    has_plan = requested is not None and (
        requested != (0.0, 0.0)
        or (predicted is not None and predicted != (0.0, 0.0))
        or (
            measured == (0.0, 0.0)
            and progress == 0.0
            and bool(reason)
            and not has_measure
        )
    )
    if has_measure and has_plan:
        return "mixed"
    if has_measure:
        return "measured"
    if has_plan:
        return "planned"
    if reason:
        return "reason_only"
    return "empty"


def _pan_attempt_history(snapshot: _SessionSnapshot) -> tuple[PanAttemptReport, ...]:
    attempts: list[PanAttemptReport] = []
    for record in snapshot.displacement_history:
        if type(record) is not DisplacementRecord:
            attempts.append(
                PanAttemptReport(
                    pan_ordinal=None,
                    event_ordinal=None,
                    phase="malformed",
                    requested=_vector_unknown("MALFORMED_DISPLACEMENT_RECORD"),
                    predicted=_vector_unknown("MALFORMED_DISPLACEMENT_RECORD"),
                    measured=_vector_unknown("MALFORMED_DISPLACEMENT_RECORD"),
                    residual=_vector_unknown("MALFORMED_DISPLACEMENT_RECORD"),
                    progress_px=AvailabilityValue(
                        FieldAvailability.MALFORMED.value, None, "MALFORMED_DISPLACEMENT_RECORD"
                    ),
                    reason=AvailabilityValue(
                        FieldAvailability.MALFORMED.value, None, "MALFORMED_DISPLACEMENT_RECORD"
                    ),
                )
            )
            continue
        phase = _classify_displacement_phase(record)
        requested = _finite_point(record.requested)
        predicted = _finite_point(record.predicted)
        measured = _finite_point(record.measured)
        residual = _finite_point(record.residual)
        progress_value = record.progress_px
        if type(progress_value) is not float:
            progress = AvailabilityValue(FieldAvailability.MALFORMED.value, None, "PROGRESS_TYPE")
        else:
            if not math.isfinite(progress_value):
                progress = AvailabilityValue(
                    FieldAvailability.MALFORMED.value, None, "PROGRESS_NON_FINITE"
                )
            elif phase in ("measured", "mixed") or progress_value != 0.0:
                progress = AvailabilityValue(FieldAvailability.PRESENT.value, progress_value, "")
            else:
                progress = AvailabilityValue(
                    FieldAvailability.UNKNOWN.value, None, "PROGRESS_NOT_REPRESENTED"
                )
        reason_text = record.reason
        if type(reason_text) is not str:
            reason = AvailabilityValue(FieldAvailability.MALFORMED.value, None, "REASON_TYPE")
        elif reason_text:
            reason = AvailabilityValue(FieldAvailability.PRESENT.value, reason_text, "")
        else:
            reason = AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "REASON_ABSENT")
        capture_ordinal = None
        for entry in snapshot.action_ledger:
            if entry.pan_ordinal == record.pan_ordinal:
                capture_ordinal = entry.source_frame.capture_ordinal
                break
        attempts.append(
            PanAttemptReport(
                pan_ordinal=record.pan_ordinal if type(record.pan_ordinal) is int else None,
                event_ordinal=record.event_ordinal if type(record.event_ordinal) is int else None,
                phase=phase,
                requested=(
                    _vector_present(requested)
                    if requested is not None and (phase in ("planned", "mixed") or requested != (0.0, 0.0))
                    else (
                        _vector_present(requested, reason_code="ZERO_VECTOR_REPRESENTED")
                        if requested is not None and phase == "planned"
                        else _vector_unknown("REQUESTED_NOT_REPRESENTED")
                    )
                ),
                predicted=(
                    _vector_present(predicted)
                    if predicted is not None and (phase in ("planned", "mixed") or predicted != (0.0, 0.0))
                    else _vector_unknown("PREDICTED_NOT_REPRESENTED")
                ),
                measured=(
                    _vector_present(measured)
                    if measured is not None and phase in ("measured", "mixed")
                    else (
                        _vector_present(measured)
                        if measured is not None and measured != (0.0, 0.0)
                        else _vector_unknown("MEASURED_NOT_REPRESENTED")
                    )
                ),
                residual=(
                    _vector_present(residual)
                    if residual is not None and (phase != "empty" or residual != (0.0, 0.0))
                    else _vector_unknown("RESIDUAL_NOT_REPRESENTED")
                ),
                progress_px=progress,
                reason=reason,
                capture_ordinal=capture_ordinal,
            )
        )
    return tuple(attempts)


def _aggregate_displacements(
    attempts: Sequence[PanAttemptReport],
) -> tuple[VectorReport, VectorReport, VectorReport]:
    requested = _vector_unknown("REQUESTED_ABSENT")
    measured = _vector_unknown("MEASURED_ABSENT")
    residual = _vector_unknown("RESIDUAL_ABSENT")
    for attempt in attempts:
        if attempt.requested.availability == FieldAvailability.PRESENT.value:
            requested = attempt.requested
        if attempt.measured.availability == FieldAvailability.PRESENT.value:
            measured = attempt.measured
        if attempt.residual.availability == FieldAvailability.PRESENT.value:
            residual = attempt.residual
    return requested, measured, residual


def _direction_agreement(requested: VectorReport, measured: VectorReport) -> AvailabilityValue:
    if (
        requested.availability != FieldAvailability.PRESENT.value
        or measured.availability != FieldAvailability.PRESENT.value
    ):
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value, DirectionAgreement.UNKNOWN.value, "PAIR_INCOMPLETE"
        )
    assert requested.x is not None and requested.y is not None
    assert measured.x is not None and measured.y is not None
    req_mag = math.hypot(requested.x, requested.y)
    meas_mag = math.hypot(measured.x, measured.y)
    if req_mag == 0.0 or meas_mag == 0.0:
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value, DirectionAgreement.UNKNOWN.value, "ZERO_MAGNITUDE"
        )
    dot = requested.x * measured.x + requested.y * measured.y
    if abs(dot) <= 1e-12:
        value = DirectionAgreement.ORTHOGONAL.value
    elif dot > 0.0:
        value = DirectionAgreement.AGREE.value
    else:
        value = DirectionAgreement.DISAGREE.value
    return AvailabilityValue(FieldAvailability.PRESENT.value, value, "")


def _progress_ratio(
    requested: VectorReport,
    measured: VectorReport,
    attempts: Sequence[PanAttemptReport],
) -> AvailabilityValue:
    if (
        requested.availability == FieldAvailability.PRESENT.value
        and measured.availability == FieldAvailability.PRESENT.value
        and requested.x is not None
        and requested.y is not None
        and measured.x is not None
        and measured.y is not None
    ):
        req_mag = math.hypot(requested.x, requested.y)
        if req_mag > 0.0:
            ratio = math.hypot(measured.x, measured.y) / req_mag
            if math.isfinite(ratio):
                return AvailabilityValue(FieldAvailability.PRESENT.value, float(ratio), "")
            return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "RATIO_NON_FINITE")
        return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "REQUESTED_ZERO_MAGNITUDE")
    # Fall back to ledger progress_px only when explicitly present; never invent ratio.
    for attempt in reversed(attempts):
        if attempt.progress_px.availability == FieldAvailability.PRESENT.value:
            return AvailabilityValue(
                FieldAvailability.UNKNOWN.value,
                None,
                "PROGRESS_PX_WITHOUT_REQUESTED_MEASURED_PAIR",
            )
    return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "PROGRESS_RATIO_ABSENT")


def _correction_count(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if "route_result.corrections" in snapshot.malformed_fields:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "CORRECTIONS_TYPE")
    corrections = snapshot.route_corrections
    if type(corrections) is not tuple:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "CORRECTIONS_TYPE")
    return AvailabilityValue(FieldAvailability.PRESENT.value, len(corrections), "")


def _ledger_reason_texts(snapshot: _SessionSnapshot) -> tuple[str, ...]:
    reasons: list[str] = []
    for record in snapshot.displacement_history:
        reason = getattr(record, "reason", "")
        if type(reason) is str and reason:
            reasons.append(reason)
    if type(snapshot.terminal_reason) is str and snapshot.terminal_reason:
        reasons.append(snapshot.terminal_reason)
    if type(snapshot.observation_summary) is str and snapshot.observation_summary:
        reasons.append(snapshot.observation_summary)
    if type(snapshot.route_reason) is str and snapshot.route_reason:
        reasons.append(snapshot.route_reason)
    return tuple(reasons)


def _repeated_viewports(snapshot: _SessionSnapshot) -> AvailabilityValue:
    reason_hits = [
        reason
        for reason in _ledger_reason_texts(snapshot)
        if any(token in reason for token in _REPEATED_VIEWPORT_TOKENS)
    ]
    unique = []
    seen: set[tuple[int, int]] = set()
    for item in snapshot.seen_viewports:
        if type(item) is not tuple or len(item) != 2:
            return AvailabilityValue(
                FieldAvailability.MALFORMED.value,
                {
                    "detected": None,
                    "unique_viewport_count": 0,
                    "unique_viewports": (),
                    "reason_signals": (),
                },
                "VIEWPORT_MALFORMED",
            )
        if type(item[0]) is not int or type(item[1]) is not int:
            return AvailabilityValue(
                FieldAvailability.MALFORMED.value,
                {
                    "detected": None,
                    "unique_viewport_count": 0,
                    "unique_viewports": (),
                    "reason_signals": (),
                },
                "VIEWPORT_TYPE",
            )
        if item not in seen:
            seen.add(item)
            unique.append([item[0], item[1]])
    if reason_hits:
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {
                "detected": True,
                "unique_viewport_count": len(unique),
                "unique_viewports": unique,
                "reason_signals": list(reason_hits),
            },
            "REPEATED_VIEWPORT_REASON",
        )
    if unique:
        # Unique list alone cannot prove repeats; remain explicit.
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value,
            {
                "detected": None,
                "unique_viewport_count": len(unique),
                "unique_viewports": unique,
                "reason_signals": [],
            },
            "REPEAT_NOT_REPRESENTED",
        )
    return AvailabilityValue(
        FieldAvailability.UNKNOWN.value,
        {"detected": None, "unique_viewport_count": 0, "unique_viewports": [], "reason_signals": []},
        "VIEWPORTS_ABSENT",
    )


def _camera_map_clamps(snapshot: _SessionSnapshot) -> AvailabilityValue:
    hits = [
        reason
        for reason in _ledger_reason_texts(snapshot)
        if any(token in reason.lower() for token in _CLAMP_REASON_TOKENS)
    ]
    if hits:
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {"detected": True, "reason_signals": hits},
            "CLAMP_REASON",
        )
    if snapshot.displacement_history:
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value,
            {"detected": None, "reason_signals": []},
            "CLAMP_NOT_REPRESENTED",
        )
    return AvailabilityValue(
        FieldAvailability.UNKNOWN.value,
        {"detected": None, "reason_signals": []},
        "DISPLACEMENT_HISTORY_ABSENT",
    )


def _facility_binding_confidence(snapshot: _SessionSnapshot) -> AvailabilityValue:
    binding = snapshot.current_binding
    if binding is not None and type(binding) is not HistoricalBindingRecord:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FACILITY_BINDING_RECORD")
    if any(type(item) is not HistoricalBindingRecord for item in snapshot.historical_bindings):
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FACILITY_BINDING_RECORD")
    if binding is None and snapshot.historical_bindings:
        binding = snapshot.historical_bindings[-1]
    if binding is None:
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value, None, "FACILITY_BINDING_ABSENT"
        )
    confidence = binding.confidence
    if type(confidence) is not float:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FACILITY_CONFIDENCE_TYPE")
    if not math.isfinite(confidence):
        return AvailabilityValue(
            FieldAvailability.MALFORMED.value, None, "FACILITY_CONFIDENCE_NON_FINITE"
        )
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "confidence": confidence,
            "building_id": binding.building_id,
            "stale": True if binding.stale else False,
            "frame_semantic_sha256": binding.frame_semantic_sha256,
        },
        "",
    )


def _radial_binding_confidence(snapshot: _SessionSnapshot) -> AvailabilityValue:
    # NavigationSession does not persist radial confidence; never invent it.
    if NavigationCheckpoint.RADIAL_VERIFIED.value in snapshot.checkpoint_history:
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value,
            None,
            "RADIAL_VERIFIED_WITHOUT_CONFIDENCE",
        )
    return AvailabilityValue(
        FieldAvailability.UNKNOWN.value, None, "RADIAL_CONFIDENCE_NOT_REPRESENTED"
    )


def _safe_exit_availability(snapshot: _SessionSnapshot) -> AvailabilityValue:
    history = snapshot.checkpoint_history
    if NavigationCheckpoint.SAFE_EXIT_VERIFIED.value in history or (
        NavigationCheckpoint.HOME_RECOVERED.value in history
    ):
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            SafeExitAvailability.VERIFIED.value,
            "SAFE_EXIT_VERIFIED",
        )
    if NavigationCheckpoint.RADIAL_VERIFIED.value in history:
        return AvailabilityValue(
            FieldAvailability.UNKNOWN.value,
            SafeExitAvailability.NOT_REPRESENTED.value,
            "SAFE_EXIT_NOT_YET_REPRESENTED",
        )
    return AvailabilityValue(
        FieldAvailability.UNKNOWN.value,
        SafeExitAvailability.NOT_REPRESENTED.value,
        "SAFE_EXIT_ABSENT",
    )


def _state_timing(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if "known_frame_identities" in snapshot.malformed_fields:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FRAME_TIMING_TYPE")
    times: list[float] = []
    for frame in snapshot.known_frame_identities:
        if type(frame) is not FrameIdentityRecord:
            return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FRAME_TIMING_RECORD")
        value = frame.capture_completed_monotonic
        if type(value) is not float:
            return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "TIMING_TYPE")
        if not math.isfinite(value) or value < 0.0:
            return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "TIMING_NON_FINITE")
        times.append(value)
    if not times:
        return AvailabilityValue(FieldAvailability.UNKNOWN.value, None, "FRAME_TIMING_ABSENT")
    earliest = min(times)
    latest = max(times)
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "earliest_capture_completed_monotonic": earliest,
            "latest_capture_completed_monotonic": latest,
            "span_seconds": latest - earliest,
            "checkpoint_sequence": list(snapshot.checkpoint_history),
            "sample_count": len(times),
        },
        "",
    )


def _total_frame_count(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if "known_frame_identities" in snapshot.malformed_fields:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FRAME_COUNT_TYPE")
    if any(type(frame) is not FrameIdentityRecord for frame in snapshot.known_frame_identities):
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "FRAME_COUNT_RECORD")
    return AvailabilityValue(
        FieldAvailability.PRESENT.value, len(snapshot.known_frame_identities), ""
    )


def _per_state_frame_counts(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if "checkpoint_history" in snapshot.malformed_fields:
        return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "STATE_NAME_TYPE")
    counts: dict[str, int] = {}
    for raw in snapshot.checkpoint_history:
        if type(raw) is not str or raw not in _ALLOWED_CHECKPOINTS:
            return AvailabilityValue(FieldAvailability.MALFORMED.value, None, "STATE_NAME_INVALID")
        counts[raw] = counts.get(raw, 0) + 1
    ordered_unique: dict[str, int] = {}
    for name in snapshot.checkpoint_history:
        if name not in ordered_unique and name in counts:
            ordered_unique[name] = counts[name]
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "checkpoint_visit_counts": ordered_unique,
            "total_checkpoint_visits": len(snapshot.checkpoint_history),
            "known_frame_count": len(snapshot.known_frame_identities),
        },
        "",
    )


def _action_ledger_summary(snapshot: _SessionSnapshot) -> ActionLedgerSummary:
    if "action_ledger" in snapshot.malformed_fields:
        return ActionLedgerSummary(
            total_entries=0,
            prepared_count=0,
            dispatched_count=0,
            reconciled_count=0,
            suppressed_count=0,
            unknown_status_count=0,
            entries=(),
        )
    if (
        any(type(entry) is not ActionLedgerEntry for entry in snapshot.action_ledger)
        or any(
            type(entry.status) is not LedgerStatus
            for entry in snapshot.action_ledger
            if type(entry) is ActionLedgerEntry
        )
    ):
        return ActionLedgerSummary(
            total_entries=0,
            prepared_count=0,
            dispatched_count=0,
            reconciled_count=0,
            suppressed_count=0,
            unknown_status_count=0,
            entries=(),
        )
    prepared = dispatched = reconciled = suppressed = unknown = 0
    entries: list[dict[str, Any]] = []
    for entry in snapshot.action_ledger:
        status = entry.status
        if status is LedgerStatus.PREPARED:
            prepared += 1
            status_value = status.value
        elif status is LedgerStatus.DISPATCHED:
            dispatched += 1
            status_value = status.value
        elif status is LedgerStatus.RECONCILED:
            reconciled += 1
            status_value = status.value
        elif status is LedgerStatus.SUPPRESSED:
            suppressed += 1
            status_value = status.value
        else:
            unknown += 1
            status_value = ""
        entries.append(
            {
                "action_key": entry.action_key,
                "kind": entry.kind,
                "status": status_value,
                "pan_ordinal": entry.pan_ordinal,
                "event_ordinal": entry.event_ordinal,
                "capture_ordinal": entry.source_frame.capture_ordinal,
                "target_identity": entry.target_identity,
                "pre_uncertainty_status": entry.pre_uncertainty_status,
                "gesture_fingerprint": entry.gesture_fingerprint or None,
            }
        )
    return ActionLedgerSummary(
        total_entries=len(snapshot.action_ledger),
        prepared_count=prepared,
        dispatched_count=dispatched,
        reconciled_count=reconciled,
        suppressed_count=suppressed,
        unknown_status_count=unknown,
        entries=tuple(entries),
    )


def _continuation_history(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if not isinstance(snapshot.continuation_mode, ContinuationMode) or type(
        snapshot.route_continuations
    ) is not int:
        return AvailabilityValue(
            FieldAvailability.MALFORMED.value,
            {
                "continuation_mode": None,
                "route_continuations": 0,
                "continuation_markers": (),
                "continuation_ready": False,
            },
            "CONTINUATION_STATE_INVALID",
        )
    continuation_markers = [item for item in snapshot.route_corrections if item == "continuation"]
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "continuation_mode": snapshot.continuation_mode.value,
            "route_continuations": snapshot.route_continuations,
            "continuation_markers": continuation_markers,
            "continuation_ready": bool(snapshot.route_continuations or continuation_markers),
        },
        "",
    )


def _recovery_only_history(snapshot: _SessionSnapshot) -> AvailabilityValue:
    if not isinstance(snapshot.continuation_mode, ContinuationMode):
        return AvailabilityValue(
            FieldAvailability.MALFORMED.value,
            {
                "continuation_mode": None,
                "recovery_only_active": False,
                "recovery_checkpoints": (),
            },
            "RECOVERY_STATE_INVALID",
        )
    recovery_checkpoints = [
        name
        for name in snapshot.checkpoint_history
        if name
        in (
            NavigationCheckpoint.RADIAL_VERIFIED.value,
            NavigationCheckpoint.SAFE_EXIT_VERIFIED.value,
            NavigationCheckpoint.HOME_RECOVERED.value,
        )
    ]
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "continuation_mode": snapshot.continuation_mode.value,
            "recovery_only_active": snapshot.continuation_mode is ContinuationMode.RECOVERY_ONLY,
            "recovery_checkpoints": recovery_checkpoints,
        },
        "",
    )


def _underlying_status(entry: ActionLedgerEntry) -> LedgerStatus | None:
    if entry.status is LedgerStatus.SUPPRESSED:
        if entry.pre_uncertainty_status == LedgerStatus.PREPARED.value:
            return LedgerStatus.PREPARED
        if entry.pre_uncertainty_status == LedgerStatus.DISPATCHED.value:
            return LedgerStatus.DISPATCHED
        return None
    return entry.status


def _action_authority_separation(snapshot: _SessionSnapshot) -> ActionAuthoritySeparation:
    has_plan = any(
        _classify_displacement_phase(record) in ("planned", "mixed")
        for record in snapshot.displacement_history
        if type(record) is DisplacementRecord
    )
    has_prepared = any(
        _underlying_status(entry) is LedgerStatus.PREPARED
        for entry in snapshot.action_ledger
        if type(entry) is ActionLedgerEntry
    )
    requested = AvailabilityValue(
        FieldAvailability.PRESENT.value if (has_plan or has_prepared) else FieldAvailability.UNKNOWN.value,
        {
            "plan_represented": has_plan,
            "prepared_ledger_represented": has_prepared,
        },
        "" if (has_plan or has_prepared) else "REQUEST_NOT_REPRESENTED",
    )
    authorized = AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "action_class": "navigation_only_scope_present",
            "authorize_dispatch": False,
        },
        "AUTHORIZATION_SCOPE_ONLY",
    )
    dispatched_entries = [
        entry
        for entry in snapshot.action_ledger
        if type(entry) is ActionLedgerEntry
        if _underlying_status(entry) in (LedgerStatus.DISPATCHED, LedgerStatus.RECONCILED)
        or entry.status is LedgerStatus.DISPATCHED
        or entry.status is LedgerStatus.RECONCILED
    ]
    # PREPARED-only never counts as dispatched.
    prepared_only = [
        entry
        for entry in snapshot.action_ledger
        if type(entry) is ActionLedgerEntry
        if _underlying_status(entry) is LedgerStatus.PREPARED
        or (
            entry.status is LedgerStatus.SUPPRESSED
            and entry.pre_uncertainty_status == LedgerStatus.PREPARED.value
        )
    ]
    if dispatched_entries:
        dispatched = AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {"count": len(dispatched_entries)},
            "LEDGER_DISPATCHED_OR_RECONCILED",
        )
    elif prepared_only:
        dispatched = AvailabilityValue(
            FieldAvailability.UNAVAILABLE.value,
            {"prepared_only_count": len(prepared_only)},
            "PREPARED_NOT_DISPATCH_PROOF",
        )
    else:
        dispatched = AvailabilityValue(
            FieldAvailability.UNKNOWN.value, {"count": 0}, "DISPATCH_NOT_REPRESENTED"
        )

    transport_confirmed_entries = [
        entry
        for entry in snapshot.action_ledger
        if type(entry) is ActionLedgerEntry and entry.status is LedgerStatus.RECONCILED
    ]
    # Suppressed PREPARED with localization must never become transport-confirmed.
    ambiguous_prepared = [
        entry
        for entry in snapshot.action_ledger
        if type(entry) is ActionLedgerEntry
        if entry.status is LedgerStatus.SUPPRESSED
        and entry.pre_uncertainty_status == LedgerStatus.PREPARED.value
    ]
    if transport_confirmed_entries:
        transport = AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {"reconciled_count": len(transport_confirmed_entries)},
            "RECONCILED_AFTER_DISPATCH",
        )
    elif ambiguous_prepared:
        transport = AvailabilityValue(
            FieldAvailability.UNAVAILABLE.value,
            {"uncertain_prepared_count": len(ambiguous_prepared)},
            "UNCERTAIN_PREPARED_NOT_TRANSPORT",
        )
    else:
        transport = AvailabilityValue(
            FieldAvailability.UNKNOWN.value, {"reconciled_count": 0}, "TRANSPORT_NOT_REPRESENTED"
        )

    verified_checkpoints = [
        name
        for name in snapshot.checkpoint_history
        if name
        in (
            NavigationCheckpoint.TARGET_BOUND.value,
            NavigationCheckpoint.RADIAL_VERIFIED.value,
            NavigationCheckpoint.SAFE_EXIT_VERIFIED.value,
            NavigationCheckpoint.HOME_RECOVERED.value,
        )
    ]
    if verified_checkpoints:
        verified = AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {"checkpoints": verified_checkpoints},
            "VERIFICATION_CHECKPOINTS",
        )
    else:
        verified = AvailabilityValue(
            FieldAvailability.UNKNOWN.value, {"checkpoints": []}, "VERIFICATION_ABSENT"
        )
    return ActionAuthoritySeparation(
        requested=requested,
        authorized=authorized,
        dispatched=dispatched,
        transport_confirmed=transport,
        verified=verified,
    )


def _terminal_state(
    snapshot: _SessionSnapshot,
    integrity: ReportIntegrity,
    integrity_reason: str,
) -> AvailabilityValue:
    if integrity is ReportIntegrity.MALFORMED:
        return AvailabilityValue(
            FieldAvailability.MALFORMED.value,
            {
                "class": TerminalReportClass.MALFORMED.value,
                "outcome": snapshot.outcome.value if isinstance(snapshot.outcome, SessionOutcome) else None,
                "checkpoint": snapshot.checkpoint.value if isinstance(snapshot.checkpoint, NavigationCheckpoint) else None,
                "terminal_reason": snapshot.terminal_reason,
                "route_status": snapshot.route_status,
                "integrity_reason": integrity_reason,
            },
            integrity_reason or "MALFORMED_SESSION",
        )
    if integrity is ReportIntegrity.CONTRADICTORY:
        return AvailabilityValue(
            FieldAvailability.CONTRADICTORY.value,
            {
                "class": TerminalReportClass.CONTRADICTORY.value,
                "outcome": snapshot.outcome.value,
                "checkpoint": snapshot.checkpoint.value,
                "terminal_reason": snapshot.terminal_reason,
                "route_status": snapshot.route_status,
                "integrity_reason": integrity_reason,
            },
            integrity_reason or "CONTRADICTORY_SESSION",
        )
    if snapshot.outcome is SessionOutcome.COMPLETED:
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {
                "class": TerminalReportClass.SUCCESS.value,
                "outcome": snapshot.outcome.value,
                "checkpoint": snapshot.checkpoint.value,
                "terminal_reason": snapshot.terminal_reason,
                "route_status": snapshot.route_status,
                "integrity_reason": integrity_reason,
            },
            "",
        )
    if snapshot.outcome is SessionOutcome.BLOCKED:
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {
                "class": TerminalReportClass.REJECTION.value,
                "outcome": snapshot.outcome.value,
                "checkpoint": snapshot.checkpoint.value,
                "terminal_reason": snapshot.terminal_reason,
                "route_status": snapshot.route_status,
                "integrity_reason": integrity_reason,
            },
            "",
        )
    if snapshot.outcome is SessionOutcome.UNCERTAIN:
        return AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {
                "class": TerminalReportClass.UNCERTAIN.value,
                "outcome": snapshot.outcome.value,
                "checkpoint": snapshot.checkpoint.value,
                "terminal_reason": snapshot.terminal_reason,
                "route_status": snapshot.route_status,
                "integrity_reason": integrity_reason,
            },
            "",
        )
    return AvailabilityValue(
        FieldAvailability.PRESENT.value,
        {
            "class": TerminalReportClass.INCOMPLETE.value,
            "outcome": snapshot.outcome.value,
            "checkpoint": snapshot.checkpoint.value,
            "terminal_reason": snapshot.terminal_reason,
            "route_status": snapshot.route_status,
            "integrity_reason": integrity_reason,
        },
        "",
    )


def _non_dispatch_authority() -> AvailabilityValue:
    """CONFIRMED_NOT_DISPATCHED remains unavailable without a trusted transport authority."""

    try:
        TrustedTransportNonDispatchAuthority(authority_id="observability-probe")
    except NavigationSessionError as exc:
        if exc.reason_code == "NON_DISPATCH_AUTHORITY_UNAVAILABLE":
            return AvailabilityValue(
                FieldAvailability.UNAVAILABLE.value,
                {
                    "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
                    "reason_code": "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
                },
                "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
            )
        return AvailabilityValue(
            FieldAvailability.UNAVAILABLE.value,
            {
                "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
                "reason_code": exc.reason_code,
            },
            exc.reason_code,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return AvailabilityValue(
            FieldAvailability.UNAVAILABLE.value,
            {
                "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
                "reason_code": "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
                "detail": type(exc).__name__,
            },
            "NON_DISPATCH_AUTHORITY_UNAVAILABLE",
        )
    return AvailabilityValue(
        FieldAvailability.CONTRADICTORY.value,
        {
            "resolution": UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
            "reason_code": "NON_DISPATCH_AUTHORITY_UNEXPECTEDLY_AVAILABLE",
        },
        "NON_DISPATCH_AUTHORITY_UNEXPECTEDLY_AVAILABLE",
    )


def _availability_to_dict(value: AvailabilityValue) -> dict[str, Any]:
    return {
        "availability": value.availability,
        "value": _plain(value.value),
        "reason_code": value.reason_code,
    }


def _vector_to_dict(value: VectorReport) -> dict[str, Any]:
    return {
        "availability": value.availability,
        "x": value.x,
        "y": value.y,
        "reason_code": value.reason_code,
    }


def _pan_attempt_to_dict(value: PanAttemptReport) -> dict[str, Any]:
    return {
        "pan_ordinal": value.pan_ordinal,
        "event_ordinal": value.event_ordinal,
        "capture_ordinal": value.capture_ordinal,
        "phase": value.phase,
        "requested": _vector_to_dict(value.requested),
        "predicted": _vector_to_dict(value.predicted),
        "measured": _vector_to_dict(value.measured),
        "residual": _vector_to_dict(value.residual),
        "progress_px": _availability_to_dict(value.progress_px),
        "reason": _availability_to_dict(value.reason),
    }


def _ledger_summary_to_dict(value: ActionLedgerSummary) -> dict[str, Any]:
    return {
        "total_entries": value.total_entries,
        "prepared_count": value.prepared_count,
        "dispatched_count": value.dispatched_count,
        "reconciled_count": value.reconciled_count,
        "suppressed_count": value.suppressed_count,
        "unknown_status_count": value.unknown_status_count,
        "entries": [_plain(entry) for entry in value.entries],
    }


def _plain(value: Any) -> Any:
    if value is None or type(value) in (str, int, float, bool):
        if type(value) is float and not math.isfinite(value):
            raise NavigationObservabilityError("NON_FINITE_SNAPSHOT_VALUE")
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is tuple:
        return [_plain(item) for item in value]
    if type(value) is list:
        return [_plain(item) for item in value]
    if type(value) in (dict, MappingProxyType):
        return {key: _plain(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    raise NavigationObservabilityError("NON_JSON_SAFE_SNAPSHOT_VALUE", type(value).__name__)


def _freeze_json(value: Any, field: str) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise NavigationObservabilityError("NON_FINITE_SNAPSHOT_VALUE", field)
        return value
    if type(value) in (dict, MappingProxyType):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise NavigationObservabilityError("NON_STRING_MAPPING_KEY", field)
            frozen[key] = _freeze_json(item, field)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(_freeze_json(item, field) for item in value)
    raise NavigationObservabilityError("NON_JSON_SAFE_SNAPSHOT_VALUE", type(value).__name__)


def _assert_json_safe(value: Any, field: str) -> None:
    frozen = _freeze_json(value, field)
    _validate_frozen_json(frozen, field)
    try:
        json.dumps(_plain(frozen), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise NavigationObservabilityError("NON_JSON_SAFE_VALUE", field) from exc


def _contains_numpy(value: Any) -> bool:
    module = getattr(type(value), "__module__", "") or ""
    if module.startswith("numpy"):
        return True
    if type(value) in (list, tuple):
        return any(_contains_numpy(item) for item in value)
    if type(value) in (dict, MappingProxyType):
        return any(_contains_numpy(item) for item in value.values())
    return False


def _validate_frozen_json(value: Any, field: str) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise NavigationObservabilityError("NON_FINITE_SNAPSHOT_VALUE", field)
        return
    if type(value) is tuple:
        for item in value:
            _validate_frozen_json(item, field)
        return
    if type(value) is MappingProxyType:
        for key, item in value.items():
            if type(key) is not str:
                raise NavigationObservabilityError("NON_STRING_MAPPING_KEY", field)
            _validate_frozen_json(item, field)
        return
    if _contains_numpy(value):
        raise NavigationObservabilityError("NUMPY_RETAINED", field)
    raise NavigationObservabilityError("MUTABLE_OR_NON_JSON_VALUE", field)


def _validate_exact_dataclass_shape(value: object, cls: type, field: str) -> None:
    if type(value) is not cls:
        raise NavigationObservabilityError("INVALID_DATACLASS", field)
    try:
        actual = set(vars(value))
    except TypeError as exc:
        raise NavigationObservabilityError("INVALID_DATACLASS", field) from exc
    expected = {item.name for item in fields(cls)}
    if actual != expected:
        raise NavigationObservabilityError("INVALID_DATACLASS_FIELDS", field)


def _validate_availability_value(value: AvailabilityValue) -> None:
    _validate_exact_dataclass_shape(value, AvailabilityValue, "availability")
    if type(value.availability) is not str or value.availability not in _ALLOWED_AVAILABILITIES:
        raise NavigationObservabilityError("INVALID_AVAILABILITY")
    if type(value.reason_code) is not str:
        raise NavigationObservabilityError("INVALID_REASON_CODE")
    _validate_frozen_json(value.value, "availability_value")


def _validate_vector_report(value: VectorReport) -> None:
    _validate_exact_dataclass_shape(value, VectorReport, "vector")
    if type(value.availability) is not str or value.availability not in _ALLOWED_AVAILABILITIES:
        raise NavigationObservabilityError("INVALID_AVAILABILITY")
    if type(value.reason_code) is not str:
        raise NavigationObservabilityError("INVALID_REASON_CODE")
    if value.availability == FieldAvailability.PRESENT.value:
        if (
            type(value.x) is not float
            or type(value.y) is not float
            or not math.isfinite(value.x)
            or not math.isfinite(value.y)
        ):
            raise NavigationObservabilityError("INVALID_VECTOR_COMPONENT")
    elif value.x is not None or value.y is not None:
        raise NavigationObservabilityError("INVALID_VECTOR_COMPONENT")


_LEDGER_ENTRY_KEYS = (
    "action_key",
    "kind",
    "status",
    "pan_ordinal",
    "event_ordinal",
    "capture_ordinal",
    "target_identity",
    "pre_uncertainty_status",
    "gesture_fingerprint",
)


def _validate_ledger_entry_snapshot(entry: object) -> None:
    if type(entry) is not MappingProxyType:
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY")
    if tuple(entry.keys()) != _LEDGER_ENTRY_KEYS:
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_KEYS")
    for name in ("action_key", "kind", "target_identity"):
        value = entry[name]
        if type(value) is not str or not value:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_FIELD", name)
    if type(entry["status"]) is not str or entry["status"] not in _ALLOWED_LEDGER_STATUSES:
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_STATUS")
    for name in ("pan_ordinal", "event_ordinal", "capture_ordinal"):
        value = entry[name]
        if type(value) is not int or value < 0:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_ORDINAL", name)
    for name in ("pre_uncertainty_status", "gesture_fingerprint"):
        value = entry[name]
        if value is not None and type(value) is not str:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_FIELD", name)


def _validate_action_ledger_summary(value: ActionLedgerSummary) -> None:
    _validate_exact_dataclass_shape(value, ActionLedgerSummary, "action_ledger_summary")
    for name in (
        "total_entries",
        "prepared_count",
        "dispatched_count",
        "reconciled_count",
        "suppressed_count",
        "unknown_status_count",
    ):
        count = getattr(value, name)
        if type(count) is not int or count < 0:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_COUNT", name)
    if type(value.entries) is not tuple:
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRIES")
    if value.total_entries != len(value.entries):
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_TOTAL")
    if (
        value.prepared_count
        + value.dispatched_count
        + value.reconciled_count
        + value.suppressed_count
        + value.unknown_status_count
        != value.total_entries
    ):
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_COUNTS")
    calculated = {
        LedgerStatus.PREPARED.value: 0,
        LedgerStatus.DISPATCHED.value: 0,
        LedgerStatus.RECONCILED.value: 0,
        LedgerStatus.SUPPRESSED.value: 0,
    }
    for entry in value.entries:
        _validate_ledger_entry_snapshot(entry)
        calculated[entry["status"]] += 1
    if (
        value.prepared_count != calculated[LedgerStatus.PREPARED.value]
        or value.dispatched_count != calculated[LedgerStatus.DISPATCHED.value]
        or value.reconciled_count != calculated[LedgerStatus.RECONCILED.value]
        or value.suppressed_count != calculated[LedgerStatus.SUPPRESSED.value]
        or value.unknown_status_count != 0
    ):
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_DERIVATION")


def _validate_pan_attempt(value: PanAttemptReport) -> None:
    _validate_exact_dataclass_shape(value, PanAttemptReport, "pan_attempt")
    if type(value.phase) is not str or value.phase not in _ALLOWED_PAN_PHASES:
        raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_PHASE")
    for name in ("pan_ordinal", "event_ordinal", "capture_ordinal"):
        ordinal = getattr(value, name)
        if ordinal is not None and (type(ordinal) is not int or ordinal < 0):
            raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_ORDINAL", name)
    for name in ("requested", "predicted", "measured", "residual"):
        _validate_vector_report(getattr(value, name))
    _validate_availability_value(value.progress_px)
    _validate_availability_value(value.reason)


def _validate_report_field(name: str, value: AvailabilityValue) -> None:
    _validate_availability_value(value)
    if name in ("source_checkpoint", "terminal_checkpoint"):
        if value.availability == FieldAvailability.PRESENT.value:
            if type(value.value) is not str or value.value not in _ALLOWED_CHECKPOINTS:
                raise NavigationObservabilityError("INVALID_CHECKPOINT_VALUE")
        elif value.value is not None:
            raise NavigationObservabilityError("NON_PRESENT_CHECKPOINT_VALUE")
    elif name == "direction_agreement":
        if type(value.value) is not str or value.value not in _ALLOWED_DIRECTIONS:
            raise NavigationObservabilityError("INVALID_DIRECTION_VALUE")
    elif name == "safe_exit_availability":
        if type(value.value) is not str or value.value not in _ALLOWED_SAFE_EXIT_VALUES:
            raise NavigationObservabilityError("INVALID_SAFE_EXIT_VALUE")
    elif name in ("localization_confidence", "progress_ratio"):
        if value.availability == FieldAvailability.PRESENT.value:
            if type(value.value) is not float or not math.isfinite(value.value):
                raise NavigationObservabilityError("INVALID_SCALAR_VALUE", name)
        elif value.value is not None:
            raise NavigationObservabilityError("NON_PRESENT_SCALAR_VALUE", name)
    elif name in ("correction_count", "total_frame_count"):
        if value.availability == FieldAvailability.PRESENT.value:
            if type(value.value) is not int or value.value < 0:
                raise NavigationObservabilityError("INVALID_COUNT_VALUE", name)
        elif value.value is not None:
            raise NavigationObservabilityError("NON_PRESENT_COUNT_VALUE", name)
    elif name == "radial_binding_confidence":
        if (
            value.availability != FieldAvailability.UNKNOWN.value
            or value.value is not None
        ):
            raise NavigationObservabilityError("RADIAL_CONFIDENCE_MUST_REMAIN_UNKNOWN")
    elif name == "terminal_state":
        _validate_terminal_state_value(value.value)
    elif name == "non_dispatch_authority":
        _validate_non_dispatch_authority_value(value.value)
    elif name == "state_timing":
        if (
            value.availability == FieldAvailability.PRESENT.value
            or value.value is not None
        ):
            _validate_state_timing_value(value.value)
    elif name == "per_state_frame_counts":
        if (
            value.availability == FieldAvailability.PRESENT.value
            or value.value is not None
        ):
            _validate_per_state_counts_value(value.value)
    elif name == "repeated_viewports":
        _validate_repeated_viewports_value(value.value)
    elif name == "camera_map_clamps":
        _validate_clamp_value(value.value)
    elif name == "semantic_facility_binding_confidence":
        if value.availability == FieldAvailability.PRESENT.value:
            _validate_facility_value(value.value)
        elif value.value is not None:
            raise NavigationObservabilityError("NON_PRESENT_FACILITY_VALUE")
    elif name == "continuation_history":
        _validate_continuation_value(value.availability, value.value)
    elif name == "recovery_only_history":
        _validate_recovery_value(value.availability, value.value)


def _mapping(value: object, keys: tuple[str, ...], field: str) -> MappingProxyType:
    if type(value) is not MappingProxyType or tuple(value.keys()) != keys:
        raise NavigationObservabilityError("INVALID_NESTED_SHAPE", field)
    return value


def _validate_terminal_state_value(value: object) -> None:
    mapping = _mapping(
        value,
        ("class", "outcome", "checkpoint", "terminal_reason", "route_status", "integrity_reason"),
        "terminal_state",
    )
    if type(mapping["class"]) is not str or mapping["class"] not in _ALLOWED_TERMINAL_CLASSES:
        raise NavigationObservabilityError("INVALID_TERMINAL_CLASS")
    if mapping["outcome"] is not None and (
        type(mapping["outcome"]) is not str
        or mapping["outcome"] not in {item.value for item in SessionOutcome}
    ):
        raise NavigationObservabilityError("INVALID_TERMINAL_OUTCOME")
    if mapping["checkpoint"] is not None and (
        type(mapping["checkpoint"]) is not str or mapping["checkpoint"] not in _ALLOWED_CHECKPOINTS
    ):
        raise NavigationObservabilityError("INVALID_TERMINAL_CHECKPOINT")
    for name in ("terminal_reason", "route_status", "integrity_reason"):
        if mapping[name] is not None and type(mapping[name]) is not str:
            raise NavigationObservabilityError("INVALID_TERMINAL_FIELD", name)


def _validate_non_dispatch_authority_value(value: object) -> None:
    mapping = _mapping(
        value,
        ("resolution", "reason_code"),
        "non_dispatch_authority",
    )
    if (
        type(mapping["resolution"]) is not str
        or mapping["resolution"] != UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value
    ):
        raise NavigationObservabilityError("INVALID_NON_DISPATCH_RESOLUTION")
    if (
        type(mapping["reason_code"]) is not str
        or mapping["reason_code"] != "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
    ):
        raise NavigationObservabilityError("INVALID_NON_DISPATCH_REASON")


def _validate_state_timing_value(value: object) -> None:
    mapping = _mapping(
        value,
        (
            "earliest_capture_completed_monotonic",
            "latest_capture_completed_monotonic",
            "span_seconds",
            "checkpoint_sequence",
            "sample_count",
        ),
        "state_timing",
    )
    for name in (
        "earliest_capture_completed_monotonic",
        "latest_capture_completed_monotonic",
        "span_seconds",
    ):
        if type(mapping[name]) is not float or not math.isfinite(mapping[name]):
            raise NavigationObservabilityError("INVALID_TIMING_VALUE", name)
    if type(mapping["checkpoint_sequence"]) is not tuple or any(
        type(item) is not str or item not in _ALLOWED_CHECKPOINTS
        for item in mapping["checkpoint_sequence"]
    ):
        raise NavigationObservabilityError("INVALID_TIMING_CHECKPOINTS")
    if type(mapping["sample_count"]) is not int or mapping["sample_count"] < 0:
        raise NavigationObservabilityError("INVALID_TIMING_SAMPLE_COUNT")


def _validate_per_state_counts_value(value: object) -> None:
    mapping = _mapping(
        value,
        ("checkpoint_visit_counts", "total_checkpoint_visits", "known_frame_count"),
        "per_state_frame_counts",
    )
    counts = mapping["checkpoint_visit_counts"]
    if type(counts) is not MappingProxyType:
        raise NavigationObservabilityError("INVALID_STATE_COUNT_MAP")
    for key, count in counts.items():
        if type(key) is not str or key not in _ALLOWED_CHECKPOINTS:
            raise NavigationObservabilityError("INVALID_STATE_COUNT_KEY")
        if type(count) is not int or count < 0:
            raise NavigationObservabilityError("INVALID_STATE_COUNT_VALUE")
    for name in ("total_checkpoint_visits", "known_frame_count"):
        if type(mapping[name]) is not int or mapping[name] < 0:
            raise NavigationObservabilityError("INVALID_STATE_COUNT_VALUE", name)


def _validate_repeated_viewports_value(value: object) -> None:
    mapping = _mapping(
        value,
        ("detected", "unique_viewport_count", "unique_viewports", "reason_signals"),
        "repeated_viewports",
    )
    if mapping["detected"] is not None and type(mapping["detected"]) is not bool:
        raise NavigationObservabilityError("INVALID_REPEAT_FLAG")
    if type(mapping["unique_viewport_count"]) is not int or mapping["unique_viewport_count"] < 0:
        raise NavigationObservabilityError("INVALID_VIEWPORT_COUNT")
    if type(mapping["unique_viewports"]) is not tuple:
        raise NavigationObservabilityError("INVALID_VIEWPORTS")
    for viewport in mapping["unique_viewports"]:
        if (
            type(viewport) is not tuple
            or len(viewport) != 2
            or type(viewport[0]) is not int
            or type(viewport[1]) is not int
        ):
            raise NavigationObservabilityError("INVALID_VIEWPORT")
    if type(mapping["reason_signals"]) is not tuple or any(
        type(reason) is not str for reason in mapping["reason_signals"]
    ):
        raise NavigationObservabilityError("INVALID_REPEAT_REASONS")


def _validate_clamp_value(value: object) -> None:
    mapping = _mapping(value, ("detected", "reason_signals"), "camera_map_clamps")
    if mapping["detected"] is not None and type(mapping["detected"]) is not bool:
        raise NavigationObservabilityError("INVALID_CLAMP_FLAG")
    if type(mapping["reason_signals"]) is not tuple or any(
        type(reason) is not str for reason in mapping["reason_signals"]
    ):
        raise NavigationObservabilityError("INVALID_CLAMP_REASONS")


def _validate_facility_value(value: object) -> None:
    mapping = _mapping(
        value,
        ("confidence", "building_id", "stale", "frame_semantic_sha256"),
        "semantic_facility_binding_confidence",
    )
    if type(mapping["confidence"]) is not float or not math.isfinite(mapping["confidence"]):
        raise NavigationObservabilityError("INVALID_FACILITY_CONFIDENCE")
    if type(mapping["building_id"]) is not str or not mapping["building_id"]:
        raise NavigationObservabilityError("INVALID_FACILITY_ID")
    if type(mapping["stale"]) is not bool:
        raise NavigationObservabilityError("INVALID_FACILITY_STALE")
    if type(mapping["frame_semantic_sha256"]) is not str:
        raise NavigationObservabilityError("INVALID_FACILITY_DIGEST")


def _validate_continuation_value(availability: str, value: object) -> None:
    mapping = _mapping(
        value,
        ("continuation_mode", "route_continuations", "continuation_markers", "continuation_ready"),
        "continuation_history",
    )
    if mapping["continuation_mode"] is None:
        if availability != FieldAvailability.MALFORMED.value:
            raise NavigationObservabilityError("INVALID_CONTINUATION_MODE")
    elif (
        type(mapping["continuation_mode"]) is not str
        or mapping["continuation_mode"] not in {item.value for item in ContinuationMode}
    ):
        raise NavigationObservabilityError("INVALID_CONTINUATION_MODE")
    if type(mapping["route_continuations"]) is not int or mapping["route_continuations"] < 0:
        raise NavigationObservabilityError("INVALID_CONTINUATION_COUNT")
    if type(mapping["continuation_markers"]) is not tuple or any(
        type(marker) is not str for marker in mapping["continuation_markers"]
    ):
        raise NavigationObservabilityError("INVALID_CONTINUATION_MARKERS")
    if type(mapping["continuation_ready"]) is not bool:
        raise NavigationObservabilityError("INVALID_CONTINUATION_READY")


def _validate_recovery_value(availability: str, value: object) -> None:
    mapping = _mapping(
        value,
        ("continuation_mode", "recovery_only_active", "recovery_checkpoints"),
        "recovery_only_history",
    )
    if mapping["continuation_mode"] is None:
        if availability != FieldAvailability.MALFORMED.value:
            raise NavigationObservabilityError("INVALID_RECOVERY_MODE")
    elif (
        type(mapping["continuation_mode"]) is not str
        or mapping["continuation_mode"] not in {item.value for item in ContinuationMode}
    ):
        raise NavigationObservabilityError("INVALID_RECOVERY_MODE")
    if type(mapping["recovery_only_active"]) is not bool:
        raise NavigationObservabilityError("INVALID_RECOVERY_FLAG")
    if type(mapping["recovery_checkpoints"]) is not tuple or any(
        type(checkpoint) is not str or checkpoint not in _ALLOWED_CHECKPOINTS
        for checkpoint in mapping["recovery_checkpoints"]
    ):
        raise NavigationObservabilityError("INVALID_RECOVERY_CHECKPOINTS")


def _validate_authority_value(name: str, value: AvailabilityValue) -> None:
    if value.value is None or type(value.value) is not MappingProxyType:
        raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
    if name == "requested":
        mapping = _mapping(
            value.value,
            ("plan_represented", "prepared_ledger_represented"),
            "authority.requested",
        )
        if any(type(mapping[key]) is not bool for key in mapping):
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
    elif name == "authorized":
        mapping = _mapping(
            value.value,
            ("action_class", "authorize_dispatch"),
            "authority.authorized",
        )
        if (
            type(mapping["action_class"]) is not str
            or not mapping["action_class"]
            or type(mapping["authorize_dispatch"]) is not bool
            or mapping["authorize_dispatch"]
        ):
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
    elif name == "dispatched":
        if tuple(value.value.keys()) not in (("count",), ("prepared_only_count",)):
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
        count = next(iter(value.value.values()))
        if type(count) is not int or count < 0:
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
    elif name == "transport_confirmed":
        if tuple(value.value.keys()) not in (("reconciled_count",), ("uncertain_prepared_count",)):
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
        count = next(iter(value.value.values()))
        if type(count) is not int or count < 0:
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)
    elif name == "verified":
        mapping = _mapping(value.value, ("checkpoints",), "authority.verified")
        if type(mapping["checkpoints"]) is not tuple or any(
            type(item) is not str or item not in _ALLOWED_CHECKPOINTS
            for item in mapping["checkpoints"]
        ):
            raise NavigationObservabilityError("INVALID_AUTHORITY_VALUE", name)


def _validate_report(report: NavigationObservabilityReport) -> None:
    _validate_exact_dataclass_shape(report, NavigationObservabilityReport, "report")
    if report.schema_name != SCHEMA_NAME:
        raise NavigationObservabilityError("INVALID_SCHEMA_NAME")
    if type(report.schema_version) is not int or report.schema_version != SCHEMA_VERSION:
        raise NavigationObservabilityError("INVALID_SCHEMA_VERSION")
    if type(report.report_integrity) is not str or report.report_integrity not in _ALLOWED_REPORT_INTEGRITIES:
        raise NavigationObservabilityError("INVALID_REPORT_INTEGRITY")
    for name in ("navigation_session_id", "route_id"):
        value = getattr(report, name)
        if type(value) is not str or not value:
            if report.report_integrity == ReportIntegrity.MALFORMED.value and value is None:
                continue
            raise NavigationObservabilityError("INVALID_IDENTITY", name)
    if type(report.runtime_capture_session_id) is not str:
        if report.report_integrity == ReportIntegrity.MALFORMED.value and report.runtime_capture_session_id is None:
            pass
        else:
            raise NavigationObservabilityError("INVALID_RUNTIME_CAPTURE_SESSION_ID")
    for name in REPORT_FIELD_ORDER:
        if name in {
            "schema_name",
            "schema_version",
            "navigation_session_id",
            "route_id",
            "runtime_capture_session_id",
            "report_integrity",
            "pan_attempt_history",
            "action_ledger_summary",
            "action_authority_separation",
            "requested_atlas_displacement",
            "measured_atlas_displacement",
            "residual_vector",
        }:
            continue
        value = getattr(report, name)
        if type(value) is not AvailabilityValue:
            raise NavigationObservabilityError("INVALID_REPORT_FIELD", name)
        _validate_report_field(name, value)
    for name in (
        "requested_atlas_displacement",
        "measured_atlas_displacement",
        "residual_vector",
    ):
        _validate_vector_report(getattr(report, name))
    if type(report.pan_attempt_history) is not tuple:
        raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_HISTORY")
    for item in report.pan_attempt_history:
        _validate_pan_attempt(item)
    _validate_action_ledger_summary(report.action_ledger_summary)
    _validate_exact_dataclass_shape(
        report.action_authority_separation,
        ActionAuthoritySeparation,
        "action_authority_separation",
    )
    for name in (
        "requested",
        "authorized",
        "dispatched",
        "transport_confirmed",
        "verified",
    ):
        _validate_availability_value(getattr(report.action_authority_separation, name))
        _validate_authority_value(name, getattr(report.action_authority_separation, name))
    if type(report.terminal_state.value) is MappingProxyType:
        terminal_class = report.terminal_state.value["class"]
        expected_class = {
            ReportIntegrity.MALFORMED.value: TerminalReportClass.MALFORMED.value,
            ReportIntegrity.CONTRADICTORY.value: TerminalReportClass.CONTRADICTORY.value,
            ReportIntegrity.INCOMPLETE.value: TerminalReportClass.INCOMPLETE.value,
        }.get(report.report_integrity)
        if expected_class is not None and terminal_class != expected_class:
            raise NavigationObservabilityError("TERMINAL_INTEGRITY_MISMATCH")
    if (
        report.non_dispatch_authority.availability
        != FieldAvailability.UNAVAILABLE.value
        or report.non_dispatch_authority.reason_code
        != "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
    ):
        raise NavigationObservabilityError("NON_DISPATCH_AUTHORITY_MUST_STAY_UNAVAILABLE")


def _report_from_snapshot(payload: Mapping[str, Any]) -> NavigationObservabilityReport:
    if type(payload) is not dict:
        raise NavigationObservabilityError("INVALID_SNAPSHOT")
    if list(payload.keys()) != list(REPORT_FIELD_ORDER):
        raise NavigationObservabilityError("FIELD_ORDER_MISMATCH")

    def exact_dict(raw: object, keys: tuple[str, ...], field: str) -> dict[str, Any]:
        if type(raw) is not dict or tuple(raw.keys()) != keys:
            raise NavigationObservabilityError("INVALID_OBJECT_SHAPE", field)
        return raw

    def exact_int(raw: object, field: str, *, nonnegative: bool = False) -> int:
        if type(raw) is not int or (nonnegative and raw < 0):
            raise NavigationObservabilityError("INVALID_INTEGER", field)
        return raw

    def optional_int(raw: object, field: str) -> int | None:
        if raw is None:
            return None
        return exact_int(raw, field, nonnegative=True)

    def exact_string(raw: object, field: str, *, nonempty: bool = False) -> str:
        if type(raw) is not str or (nonempty and not raw):
            raise NavigationObservabilityError("INVALID_STRING", field)
        return raw

    def avail(raw: object, field: str) -> AvailabilityValue:
        value = exact_dict(raw, ("availability", "value", "reason_code"), field)
        availability = exact_string(value["availability"], f"{field}.availability", nonempty=True)
        if availability not in _ALLOWED_AVAILABILITIES:
            raise NavigationObservabilityError("INVALID_AVAILABILITY", field)
        reason_code = exact_string(value["reason_code"], f"{field}.reason_code")
        frozen = _freeze_json(value["value"], f"{field}.value")
        return AvailabilityValue(
            availability=availability,
            value=frozen,
            reason_code=reason_code,
        )

    def vector(raw: object, field: str) -> VectorReport:
        value = exact_dict(raw, ("availability", "x", "y", "reason_code"), field)
        availability = exact_string(value["availability"], f"{field}.availability", nonempty=True)
        if availability not in _ALLOWED_AVAILABILITIES:
            raise NavigationObservabilityError("INVALID_AVAILABILITY", field)
        x = value["x"]
        y = value["y"]
        for component, component_value in (("x", x), ("y", y)):
            if component_value is not None and (
                type(component_value) is not float or not math.isfinite(component_value)
            ):
                raise NavigationObservabilityError("INVALID_VECTOR_COMPONENT", f"{field}.{component}")
        return VectorReport(
            availability=availability,
            x=x,
            y=y,
            reason_code=exact_string(value["reason_code"], f"{field}.reason_code"),
        )

    attempts_raw = payload.get("pan_attempt_history")
    if type(attempts_raw) is not list:
        raise NavigationObservabilityError("INVALID_PAN_ATTEMPT_HISTORY")
    attempts: list[PanAttemptReport] = []
    for item in attempts_raw:
        item = exact_dict(
            item,
            (
                "pan_ordinal",
                "event_ordinal",
                "capture_ordinal",
                "phase",
                "requested",
                "predicted",
                "measured",
                "residual",
                "progress_px",
                "reason",
            ),
            "pan_attempt",
        )
        attempts.append(
            PanAttemptReport(
                pan_ordinal=optional_int(item["pan_ordinal"], "pan_attempt.pan_ordinal"),
                event_ordinal=optional_int(item["event_ordinal"], "pan_attempt.event_ordinal"),
                capture_ordinal=optional_int(
                    item["capture_ordinal"], "pan_attempt.capture_ordinal"
                ),
                phase=exact_string(item["phase"], "pan_attempt.phase", nonempty=True),
                requested=vector(item["requested"], "pan_attempt.requested"),
                predicted=vector(item["predicted"], "pan_attempt.predicted"),
                measured=vector(item["measured"], "pan_attempt.measured"),
                residual=vector(item["residual"], "pan_attempt.residual"),
                progress_px=avail(item["progress_px"], "pan_attempt.progress_px"),
                reason=avail(item["reason"], "pan_attempt.reason"),
            )
        )
    ledger_raw = payload.get("action_ledger_summary")
    ledger_raw = exact_dict(
        ledger_raw,
        (
            "total_entries",
            "prepared_count",
            "dispatched_count",
            "reconciled_count",
            "suppressed_count",
            "unknown_status_count",
            "entries",
        ),
        "action_ledger_summary",
    )
    entries_raw = ledger_raw.get("entries")
    if type(entries_raw) is not list:
        raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRIES")
    entries: list[dict[str, Any]] = []
    for raw_entry in entries_raw:
        entry = exact_dict(raw_entry, _LEDGER_ENTRY_KEYS, "action_ledger_summary.entry")
        for name in ("action_key", "kind", "target_identity"):
            exact_string(entry[name], f"action_ledger_summary.entry.{name}", nonempty=True)
        status = exact_string(entry["status"], "action_ledger_summary.entry.status", nonempty=True)
        if status not in _ALLOWED_LEDGER_STATUSES:
            raise NavigationObservabilityError("INVALID_LEDGER_SUMMARY_ENTRY_STATUS")
        for name in ("pan_ordinal", "event_ordinal", "capture_ordinal"):
            exact_int(entry[name], f"action_ledger_summary.entry.{name}", nonnegative=True)
        for name in ("pre_uncertainty_status", "gesture_fingerprint"):
            if entry[name] is not None:
                exact_string(entry[name], f"action_ledger_summary.entry.{name}")
        entries.append(entry)
    ledger = ActionLedgerSummary(
        total_entries=exact_int(ledger_raw["total_entries"], "ledger.total_entries", nonnegative=True),
        prepared_count=exact_int(
            ledger_raw["prepared_count"], "ledger.prepared_count", nonnegative=True
        ),
        dispatched_count=exact_int(
            ledger_raw["dispatched_count"], "ledger.dispatched_count", nonnegative=True
        ),
        reconciled_count=exact_int(
            ledger_raw["reconciled_count"], "ledger.reconciled_count", nonnegative=True
        ),
        suppressed_count=exact_int(
            ledger_raw["suppressed_count"], "ledger.suppressed_count", nonnegative=True
        ),
        unknown_status_count=exact_int(
            ledger_raw["unknown_status_count"], "ledger.unknown_status_count", nonnegative=True
        ),
        entries=tuple(entries),
    )
    authority_raw = payload.get("action_authority_separation")
    authority_raw = exact_dict(
        authority_raw,
        ("requested", "authorized", "dispatched", "transport_confirmed", "verified"),
        "action_authority_separation",
    )
    authority = ActionAuthoritySeparation(
        requested=avail(authority_raw["requested"], "authority.requested"),
        authorized=avail(authority_raw["authorized"], "authority.authorized"),
        dispatched=avail(authority_raw["dispatched"], "authority.dispatched"),
        transport_confirmed=avail(
            authority_raw["transport_confirmed"], "authority.transport_confirmed"
        ),
        verified=avail(authority_raw["verified"], "authority.verified"),
    )
    schema_name = exact_string(payload["schema_name"], "schema_name", nonempty=True)
    schema_version = exact_int(payload["schema_version"], "schema_version")
    if schema_name != SCHEMA_NAME or schema_version != SCHEMA_VERSION:
        raise NavigationObservabilityError("UNSUPPORTED_SCHEMA_VERSION")
    report_integrity = exact_string(payload["report_integrity"], "report_integrity", nonempty=True)
    if report_integrity not in _ALLOWED_REPORT_INTEGRITIES:
        raise NavigationObservabilityError("INVALID_REPORT_INTEGRITY")

    def identity_value(raw: object, field: str) -> str | None:
        if type(raw) is str and raw:
            return raw
        if raw is None and report_integrity == ReportIntegrity.MALFORMED.value:
            return None
        raise NavigationObservabilityError("INVALID_IDENTITY", field)

    runtime_capture_session_id = payload["runtime_capture_session_id"]
    if type(runtime_capture_session_id) is not str:
        if runtime_capture_session_id is None and report_integrity == ReportIntegrity.MALFORMED.value:
            runtime_capture_session_id = None
        else:
            raise NavigationObservabilityError("INVALID_RUNTIME_CAPTURE_SESSION_ID")
    return NavigationObservabilityReport(
        schema_name=schema_name,
        schema_version=schema_version,
        navigation_session_id=identity_value(payload["navigation_session_id"], "navigation_session_id"),
        route_id=identity_value(payload["route_id"], "route_id"),
        runtime_capture_session_id=runtime_capture_session_id,
        report_integrity=report_integrity,
        source_checkpoint=avail(payload["source_checkpoint"], "source_checkpoint"),
        terminal_checkpoint=avail(payload["terminal_checkpoint"], "terminal_checkpoint"),
        localization_confidence=avail(
            payload["localization_confidence"], "localization_confidence"
        ),
        requested_atlas_displacement=vector(
            payload["requested_atlas_displacement"], "requested_atlas_displacement"
        ),
        measured_atlas_displacement=vector(
            payload["measured_atlas_displacement"], "measured_atlas_displacement"
        ),
        residual_vector=vector(payload["residual_vector"], "residual_vector"),
        direction_agreement=avail(payload["direction_agreement"], "direction_agreement"),
        progress_ratio=avail(payload["progress_ratio"], "progress_ratio"),
        correction_count=avail(payload["correction_count"], "correction_count"),
        repeated_viewports=avail(payload["repeated_viewports"], "repeated_viewports"),
        camera_map_clamps=avail(payload["camera_map_clamps"], "camera_map_clamps"),
        semantic_facility_binding_confidence=avail(
            payload["semantic_facility_binding_confidence"],
            "semantic_facility_binding_confidence",
        ),
        radial_binding_confidence=avail(
            payload["radial_binding_confidence"], "radial_binding_confidence"
        ),
        safe_exit_availability=avail(payload["safe_exit_availability"], "safe_exit_availability"),
        state_timing=avail(payload["state_timing"], "state_timing"),
        total_frame_count=avail(payload["total_frame_count"], "total_frame_count"),
        per_state_frame_counts=avail(
            payload["per_state_frame_counts"], "per_state_frame_counts"
        ),
        pan_attempt_history=tuple(attempts),
        action_ledger_summary=ledger,
        continuation_history=avail(payload["continuation_history"], "continuation_history"),
        recovery_only_history=avail(payload["recovery_only_history"], "recovery_only_history"),
        action_authority_separation=authority,
        terminal_state=avail(payload["terminal_state"], "terminal_state"),
        non_dispatch_authority=avail(
            payload["non_dispatch_authority"], "non_dispatch_authority"
        ),
    )


__all__ = [
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "REPORT_FIELD_ORDER",
    "NavigationObservabilityError",
    "FieldAvailability",
    "ReportIntegrity",
    "TerminalReportClass",
    "DirectionAgreement",
    "SafeExitAvailability",
    "AvailabilityValue",
    "VectorReport",
    "PanAttemptReport",
    "ActionLedgerSummary",
    "ActionAuthoritySeparation",
    "NavigationObservabilityReport",
    "report_navigation_session",
    "serialize_navigation_observability_report",
    "deserialize_navigation_observability_report",
    "navigation_observability_snapshot",
]
