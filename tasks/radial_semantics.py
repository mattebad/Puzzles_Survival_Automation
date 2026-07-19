"""Platform-neutral Home radial semantic contract.

Binds owning-facility, radial, and control observations to one complete
NativeFrameIdentity capture event. Recognition, actionability, and authorization
remain distinct: recognition never grants actionability, and actionability never
grants dispatch authorization. This module carries no transport authority,
capability grant, adapter geometry, OCR thresholds, or profile-specific taps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from types import MappingProxyType
from typing import Mapping, Tuple

from tasks.perception_bundle import NativeFrameIdentity, PerceptionBundleError


SCHEMA_NAME = "home_radial_semantics"
SCHEMA_VERSION = 1

KNOWN_RADIAL_SUCCESSORS: frozenset[str] = frozenset(
    {
        "home.canonical",
        "home.with_known_radial",
        "facility.screen",
        "facility.train_queue",
        "facility.upgrade",
        "facility.claim_supply",
        "radial.closed_exterior",
        "radial.remaining_open",
    }
)


class RadialSemanticsError(ValueError):
    """Fail-closed radial semantic construction or association denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class RecognitionState(str, Enum):
    RECOGNIZED = "recognized"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class ActionabilityState(str, Enum):
    ACTIONABLE = "actionable"
    NON_ACTIONABLE = "non_actionable"


class ControlRole(str, Enum):
    PRIMARY_ACTION = "primary_action"
    SECONDARY_ACTION = "secondary_action"
    CLOSE = "close"
    UPGRADE = "upgrade"
    TRAIN = "train"
    CLAIM = "claim"
    INFO = "info"


class RadialAmbiguityState(str, Enum):
    NONE = "none"
    MULTIPLE_OWNERS = "multiple_owners"
    MULTIPLE_CONTROLS = "multiple_controls"
    OWNER_RADIAL_MISMATCH = "owner_radial_mismatch"
    UNRESOLVED = "unresolved"


def _require_native_frame(value: object, field: str) -> NativeFrameIdentity:
    if not isinstance(value, NativeFrameIdentity):
        raise RadialSemanticsError("INVALID_SOURCE_FRAME", field)
    return value


def _require_nonempty_semantic_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RadialSemanticsError("INVALID_SEMANTIC_ID", field)
    return value


def _require_confidence(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RadialSemanticsError("INVALID_CONFIDENCE", field)
    confidence = float(value)
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        raise RadialSemanticsError("INVALID_CONFIDENCE", field)
    return confidence


def _require_same_capture(
    left: NativeFrameIdentity,
    right: NativeFrameIdentity,
    *,
    field: str,
) -> None:
    if left.same_capture_event(right):
        return
    # Digest-only agreement without a complete capture-event match fails closed.
    if (
        left.transport_sha256 == right.transport_sha256
        or left.semantic_sha256 == right.semantic_sha256
    ):
        raise RadialSemanticsError("DIGEST_ONLY_JOIN_REJECTED", field)
    raise RadialSemanticsError("CAPTURE_EVENT_MISMATCH", field)


def _coerce_successor_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise RadialSemanticsError("INVALID_SUCCESSOR_SET", field)
    if not value:
        raise RadialSemanticsError("EMPTY_SUCCESSOR_SET", field)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise RadialSemanticsError("INVALID_SUCCESSOR_NAME", field)
        if item not in KNOWN_RADIAL_SUCCESSORS:
            raise RadialSemanticsError("UNKNOWN_SUCCESSOR", item)
        if item in seen:
            raise RadialSemanticsError("DUPLICATE_SUCCESSOR", item)
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _require_disjoint_successors(
    expected: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    overlap = frozenset(expected) & frozenset(forbidden)
    if overlap:
        raise RadialSemanticsError(
            "CONTRADICTORY_SUCCESSORS",
            ",".join(sorted(overlap)),
        )


def _coerce_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise RadialSemanticsError("INVALID_IMMUTABLE_FIELD", field)
    return tuple(value)


def _coerce_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise RadialSemanticsError("INVALID_IMMUTABLE_FIELD", "metadata")
    copied = dict(value)
    if any(not isinstance(key, str) or not isinstance(val, str) for key, val in copied.items()):
        raise RadialSemanticsError("INVALID_IMMUTABLE_FIELD", "metadata")
    return MappingProxyType(copied)


@dataclass(frozen=True)
class OwningFacilityObservation:
    """Positive owning-facility semantic identity for one capture event."""

    source_frame: NativeFrameIdentity
    facility_semantic_id: str
    recognition_state: RecognitionState
    recognition_confidence: float
    ambiguity_state: RadialAmbiguityState = RadialAmbiguityState.NONE
    supporting_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_frame",
            _require_native_frame(self.source_frame, "owning_facility.source_frame"),
        )
        object.__setattr__(
            self,
            "facility_semantic_id",
            _require_nonempty_semantic_id(
                self.facility_semantic_id,
                "facility_semantic_id",
            ),
        )
        if not isinstance(self.recognition_state, RecognitionState):
            raise RadialSemanticsError("INVALID_RECOGNITION_STATE", "owning_facility")
        if not isinstance(self.ambiguity_state, RadialAmbiguityState):
            raise RadialSemanticsError("INVALID_AMBIGUITY_STATE", "owning_facility")
        object.__setattr__(
            self,
            "recognition_confidence",
            _require_confidence(self.recognition_confidence, "owning_facility.confidence"),
        )
        object.__setattr__(
            self,
            "supporting_evidence",
            _coerce_string_tuple(self.supporting_evidence, "owning_facility.supporting_evidence"),
        )
        if (
            self.recognition_state is RecognitionState.RECOGNIZED
            and self.ambiguity_state is not RadialAmbiguityState.NONE
        ):
            raise RadialSemanticsError("AMBIGUOUS_OWNER_CLAIM", "owning_facility")


@dataclass(frozen=True)
class RadialControlObservation:
    """One radial control. Actionability never implies dispatch authorization."""

    source_frame: NativeFrameIdentity
    control_id: str
    label: str
    role: ControlRole
    recognition_state: RecognitionState
    recognition_confidence: float
    actionability_state: ActionabilityState
    actionability_reason: str
    expected_successors: tuple[str, ...]
    forbidden_successors: tuple[str, ...]
    owner_facility_semantic_id: str
    ambiguity_state: RadialAmbiguityState = RadialAmbiguityState.NONE
    supporting_evidence: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_frame",
            _require_native_frame(self.source_frame, "control.source_frame"),
        )
        object.__setattr__(
            self,
            "control_id",
            _require_nonempty_semantic_id(self.control_id, "control_id"),
        )
        if not isinstance(self.label, str) or not self.label.strip():
            raise RadialSemanticsError("INVALID_CONTROL_LABEL", self.control_id)
        if not isinstance(self.role, ControlRole):
            raise RadialSemanticsError("INVALID_CONTROL_ROLE", self.control_id)
        if not isinstance(self.recognition_state, RecognitionState):
            raise RadialSemanticsError("INVALID_RECOGNITION_STATE", self.control_id)
        if not isinstance(self.actionability_state, ActionabilityState):
            raise RadialSemanticsError("INVALID_ACTIONABILITY_STATE", self.control_id)
        if not isinstance(self.actionability_reason, str) or not self.actionability_reason.strip():
            raise RadialSemanticsError("INVALID_ACTIONABILITY_REASON", self.control_id)
        if not isinstance(self.ambiguity_state, RadialAmbiguityState):
            raise RadialSemanticsError("INVALID_AMBIGUITY_STATE", self.control_id)
        object.__setattr__(
            self,
            "recognition_confidence",
            _require_confidence(self.recognition_confidence, f"{self.control_id}.confidence"),
        )
        object.__setattr__(
            self,
            "owner_facility_semantic_id",
            _require_nonempty_semantic_id(
                self.owner_facility_semantic_id,
                "owner_facility_semantic_id",
            ),
        )
        expected = _coerce_successor_tuple(self.expected_successors, "expected_successors")
        forbidden = _coerce_successor_tuple(self.forbidden_successors, "forbidden_successors")
        _require_disjoint_successors(expected, forbidden)
        object.__setattr__(self, "expected_successors", expected)
        object.__setattr__(self, "forbidden_successors", forbidden)
        object.__setattr__(
            self,
            "supporting_evidence",
            _coerce_string_tuple(self.supporting_evidence, "control.supporting_evidence"),
        )
        object.__setattr__(self, "metadata", _coerce_metadata(self.metadata))
        if (
            self.recognition_state is RecognitionState.RECOGNIZED
            and self.ambiguity_state is not RadialAmbiguityState.NONE
        ):
            raise RadialSemanticsError("AMBIGUOUS_CONTROL_CLAIM", self.control_id)
        if self.actionability_state is ActionabilityState.ACTIONABLE:
            if self.recognition_state is not RecognitionState.RECOGNIZED:
                raise RadialSemanticsError(
                    "ACTIONABLE_REQUIRES_RECOGNITION",
                    self.control_id,
                )
            if self.ambiguity_state is not RadialAmbiguityState.NONE:
                raise RadialSemanticsError(
                    "ACTIONABLE_REQUIRES_UNAMBIGUOUS_CONTROL",
                    self.control_id,
                )


@dataclass(frozen=True)
class HomeRadialSemantics:
    """Same-capture Home radial semantics. Never authorizes transport or dispatch."""

    source_frame: NativeFrameIdentity
    radial_identity: str
    recognition_state: RecognitionState
    recognition_confidence: float
    owning_facility: OwningFacilityObservation
    controls: Tuple[RadialControlObservation, ...]
    ambiguity_state: RadialAmbiguityState = RadialAmbiguityState.NONE
    supporting_evidence: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_frame",
            _require_native_frame(self.source_frame, "radial.source_frame"),
        )
        object.__setattr__(
            self,
            "radial_identity",
            _require_nonempty_semantic_id(self.radial_identity, "radial_identity"),
        )
        if not isinstance(self.recognition_state, RecognitionState):
            raise RadialSemanticsError("INVALID_RECOGNITION_STATE", "radial")
        if not isinstance(self.ambiguity_state, RadialAmbiguityState):
            raise RadialSemanticsError("INVALID_AMBIGUITY_STATE", "radial")
        if not isinstance(self.owning_facility, OwningFacilityObservation):
            raise RadialSemanticsError("INVALID_OWNING_FACILITY")
        object.__setattr__(
            self,
            "recognition_confidence",
            _require_confidence(self.recognition_confidence, "radial.confidence"),
        )
        if not isinstance(self.controls, tuple):
            raise RadialSemanticsError("INVALID_CONTROL_INVENTORY")
        if any(not isinstance(control, RadialControlObservation) for control in self.controls):
            raise RadialSemanticsError("INVALID_CONTROL_INVENTORY")
        object.__setattr__(self, "controls", tuple(self.controls))
        object.__setattr__(
            self,
            "supporting_evidence",
            _coerce_string_tuple(self.supporting_evidence, "radial.supporting_evidence"),
        )
        object.__setattr__(self, "metadata", _coerce_metadata(self.metadata))

        _require_same_capture(
            self.source_frame,
            self.owning_facility.source_frame,
            field="owning_facility",
        )
        seen_control_ids: set[str] = set()
        for control in self.controls:
            _require_same_capture(
                self.source_frame,
                control.source_frame,
                field=f"control:{control.control_id}",
            )
            if control.control_id in seen_control_ids:
                raise RadialSemanticsError("DUPLICATE_CONTROL_ID", control.control_id)
            seen_control_ids.add(control.control_id)

        if (
            self.recognition_state is RecognitionState.RECOGNIZED
            and self.ambiguity_state is not RadialAmbiguityState.NONE
        ):
            raise RadialSemanticsError("AMBIGUOUS_RADIAL_CLAIM", self.radial_identity)

        owner_positive = (
            self.owning_facility.recognition_state is RecognitionState.RECOGNIZED
            and self.owning_facility.ambiguity_state is RadialAmbiguityState.NONE
        )
        radial_positive = (
            self.recognition_state is RecognitionState.RECOGNIZED
            and self.ambiguity_state is RadialAmbiguityState.NONE
        )

        for control in self.controls:
            if control.actionability_state is ActionabilityState.ACTIONABLE:
                if not radial_positive:
                    raise RadialSemanticsError(
                        "ACTIONABLE_REQUIRES_RECOGNIZED_RADIAL",
                        control.control_id,
                    )
                if not owner_positive:
                    raise RadialSemanticsError(
                        "ACTIONABLE_REQUIRES_RECOGNIZED_OWNER",
                        control.control_id,
                    )
                if (
                    control.owner_facility_semantic_id
                    != self.owning_facility.facility_semantic_id
                ):
                    raise RadialSemanticsError(
                        "OWNER_SEMANTIC_ID_MISMATCH",
                        control.control_id,
                    )

    @property
    def recognized(self) -> bool:
        return self.recognition_state is RecognitionState.RECOGNIZED

    @property
    def any_actionable_control(self) -> bool:
        return any(
            control.actionability_state is ActionabilityState.ACTIONABLE
            for control in self.controls
        )


def radial_semantics_authorize_dispatch(_semantics: HomeRadialSemantics) -> bool:
    """Radial semantics alone never authorize dispatch.

    Recognition and actionability remain non-authorizing observations. This helper
    always returns False and provides no capability, policy grant, or transport
    authority.
    """

    return False


def assert_radial_semantics_do_not_authorize(semantics: HomeRadialSemantics) -> None:
    """Fail closed if a caller treats radial semantics as dispatch authority."""

    if radial_semantics_authorize_dispatch(semantics):
        raise RadialSemanticsError("RADIAL_SEMANTICS_MUST_NOT_AUTHORIZE")


def radial_semantics_evidence_snapshot(semantics: HomeRadialSemantics) -> dict[str, object]:
    """Deterministic JSON-safe evidence snapshot. Not a full object deserializer."""

    if not isinstance(semantics, HomeRadialSemantics):
        raise RadialSemanticsError("INVALID_RADIAL_SEMANTICS")
    payload = _json_safe(_plain_for_snapshot(semantics))
    if not isinstance(payload, dict):
        raise RadialSemanticsError("SNAPSHOT_FAILED")
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "radial_semantics": payload,
    }


def _plain_for_snapshot(value: object) -> object:
    """Convert immutable radial records into plain JSON-safe structures."""

    if isinstance(value, MappingProxyType):
        return {str(key): _plain_for_snapshot(item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, NativeFrameIdentity):
        from dataclasses import fields as dataclass_fields

        return {
            field.name: _plain_for_snapshot(getattr(value, field.name))
            for field in dataclass_fields(value)
        }
    if isinstance(value, (OwningFacilityObservation, RadialControlObservation, HomeRadialSemantics)):
        from dataclasses import fields as dataclass_fields

        return {
            field.name: _plain_for_snapshot(getattr(value, field.name))
            for field in dataclass_fields(value)
        }
    if isinstance(value, tuple):
        return [_plain_for_snapshot(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _plain_for_snapshot(item) for key, item in value.items()}
    return value


def _json_safe(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def to_immutable_radial_observation(semantics: HomeRadialSemantics):
    """Project typed radial semantics into the perception-bundle radial slot.

    Imports lazily to keep the shared contract free of adapter capture hooks while
    still allowing narrow typed adoption on ImmutableRadialObservation.
    """

    from tasks.perception_bundle import ImmutableRadialObservation

    if not isinstance(semantics, HomeRadialSemantics):
        raise RadialSemanticsError("INVALID_RADIAL_SEMANTICS")
    return ImmutableRadialObservation(
        source_frame=semantics.source_frame,
        facility_identity=semantics.owning_facility.facility_semantic_id,
        confidence=semantics.recognition_confidence,
        supporting_evidence=semantics.supporting_evidence,
        semantics=semantics,
    )


def validate_bundle_radial_semantics(
    frame: NativeFrameIdentity,
    semantics: HomeRadialSemantics,
) -> None:
    """Reject cross-capture owner/radial/control composition on a perception bundle."""

    if not isinstance(semantics, HomeRadialSemantics):
        raise PerceptionBundleError("INVALID_RADIAL_SEMANTICS")
    try:
        if not frame.same_capture_event(semantics.source_frame):
            if (
                frame.transport_sha256 == semantics.source_frame.transport_sha256
                or frame.semantic_sha256 == semantics.source_frame.semantic_sha256
            ):
                raise PerceptionBundleError("DIGEST_ONLY_JOIN_REJECTED")
            raise PerceptionBundleError("CAPTURE_EVENT_MISMATCH")
        _require_same_capture(frame, semantics.owning_facility.source_frame, field="owner")
        for control in semantics.controls:
            _require_same_capture(frame, control.source_frame, field=control.control_id)
    except RadialSemanticsError as exc:
        raise PerceptionBundleError(exc.reason_code, str(exc)) from exc
