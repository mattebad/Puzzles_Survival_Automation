"""Platform-neutral immutable perception bundle for one capture event.

Every observation is bound to a complete NativeFrameIdentity. Transport PNG digests and
semantic frame digests are distinct and never interchangeable. Contextual classification
never authorizes transport by itself. Expected native geometry/profile are adapter-supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
import re
from typing import Literal, Tuple

from safe_action_core.models import snapshot
from tasks.home_atlas import (
    AmbiguityState,
    BuildingBinding,
    LocalizationResult,
    Matrix3,
    ZoomIdentity,
)


SCHEMA_NAME = "frame_perception_bundle"
SCHEMA_VERSION = 1

CaptureKind = Literal["live", "fixture"]
Box = Tuple[int, int, int, int]
Point = Tuple[float, float]
Polygon = Tuple[Point, ...]
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class PerceptionBundleError(ValueError):
    """Fail-closed perception composition or freshness denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class ContextualClass(str, Enum):
    CANONICAL_HOME = "canonical_home"
    HOME_WITH_KNOWN_RADIAL = "home_with_known_radial"
    KNOWN_MODAL = "known_modal"
    KNOWN_FULLSCREEN_SURFACE = "known_fullscreen_surface"
    NON_NATIVE_OR_INVALID = "non_native_or_invalid"
    UNKNOWN = "unknown"


class ModalSurfaceClass(str, Enum):
    """Flow-neutral source-context surface classification."""

    NONE = "none"
    CONTEXTUAL_MODAL = "contextual_modal"
    FULLSCREEN_SURFACE = "fullscreen_surface"
    LIST_OR_CARD = "list_or_card"
    UNKNOWN = "unknown"
    CONTRADICTORY = "contradictory"


class RecoveryBehavior(str, Enum):
    NONE = "none"
    DISMISS_CONTEXTUAL = "dismiss_contextual"
    RETURN_TO_SOURCE = "return_to_source"
    STOP = "stop"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceContextModalClassification:
    """Recognition-only modal/recovery result bound to its source context.

    ``confirm_authorized`` is permanently false.  A caller may use the
    dismissal/recovery classification to decide whether a known benign close
    is meaningful, but this value never grants a generic Confirm action.
    """

    source_context: str
    surface_class: ModalSurfaceClass
    recovery_behavior: RecoveryBehavior
    successor_context: str | None = None
    surface_identity: str | None = None
    dismiss_target_identity: str | None = None
    recognized: bool = False
    contradictory: bool = False
    confidence: float = 0.0
    supporting_evidence: tuple[str, ...] = ()
    reason_code: str = ""
    confirm_authorized: bool = False

    @property
    def allows_dismissal(self) -> bool:
        return self.recovery_behavior is RecoveryBehavior.DISMISS_CONTEXTUAL and self.recognized and not self.contradictory

    @property
    def allows_recovery(self) -> bool:
        return self.recovery_behavior in {RecoveryBehavior.DISMISS_CONTEXTUAL, RecoveryBehavior.RETURN_TO_SOURCE} and self.recognized and not self.contradictory

    @property
    def context(self) -> str:
        return self.source_context

    @property
    def modal_class(self) -> ModalSurfaceClass:
        return self.surface_class

    @property
    def recovery(self) -> RecoveryBehavior:
        return self.recovery_behavior


def classify_source_context_modal(
    *,
    source_context: str,
    successor_context: str | None = None,
    surface_identity: str | None = None,
    surface_class: ModalSurfaceClass | str = ModalSurfaceClass.NONE,
    recovery_behavior: RecoveryBehavior | str = RecoveryBehavior.NONE,
    dismiss_target_identity: str | None = None,
    recognized: bool = False,
    contradictory: bool = False,
    confidence: float = 0.0,
    supporting_evidence: tuple[str, ...] = (),
) -> SourceContextModalClassification:
    """Build a fail-closed contextual classification from typed evidence.

    Source context is mandatory. Unknown or contradictory surfaces are
    represented rather than guessed, and a dismissal target is accepted only
    for a recognized contextual modal. Generic confirmation is never exposed.
    """

    if not str(source_context).strip():
        raise PerceptionBundleError("MISSING_SOURCE_CONTEXT")
    try:
        modal = surface_class if isinstance(surface_class, ModalSurfaceClass) else ModalSurfaceClass(str(surface_class))
    except ValueError:
        modal = ModalSurfaceClass.UNKNOWN
    try:
        recovery = recovery_behavior if isinstance(recovery_behavior, RecoveryBehavior) else RecoveryBehavior(str(recovery_behavior))
    except ValueError:
        recovery = RecoveryBehavior.UNKNOWN
    try:
        numeric_confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise PerceptionBundleError("INVALID_MODAL_CONFIDENCE") from exc
    if not math.isfinite(numeric_confidence) or not 0.0 <= numeric_confidence <= 1.0:
        raise PerceptionBundleError("INVALID_MODAL_CONFIDENCE")
    contradiction = bool(contradictory) or modal is ModalSurfaceClass.CONTRADICTORY
    valid_recognition = bool(recognized) and not contradiction and modal not in {ModalSurfaceClass.UNKNOWN, ModalSurfaceClass.CONTRADICTORY}
    if modal is ModalSurfaceClass.CONTEXTUAL_MODAL:
        if recovery is RecoveryBehavior.NONE:
            recovery = RecoveryBehavior.UNKNOWN
        if recovery is RecoveryBehavior.DISMISS_CONTEXTUAL and not dismiss_target_identity:
            valid_recognition = False
            recovery = RecoveryBehavior.UNKNOWN
    elif recovery is not RecoveryBehavior.NONE:
        # Recovery behavior without a modal/surface context is ambiguous.
        valid_recognition = False
        recovery = RecoveryBehavior.UNKNOWN
    return SourceContextModalClassification(
        source_context=str(source_context),
        successor_context=str(successor_context) if successor_context is not None else None,
        surface_class=modal,
        recovery_behavior=recovery,
        surface_identity=str(surface_identity) if surface_identity is not None else None,
        dismiss_target_identity=str(dismiss_target_identity) if dismiss_target_identity is not None else None,
        recognized=valid_recognition,
        contradictory=contradiction,
        confidence=numeric_confidence if valid_recognition else 0.0,
        supporting_evidence=tuple(str(item) for item in supporting_evidence),
        reason_code=("CONTRADICTORY_SURFACE" if contradiction else "UNKNOWN_SURFACE" if modal is ModalSurfaceClass.UNKNOWN else "CONTEXTUAL_MODAL" if valid_recognition else "RECOVERY_CONTEXT_INVALID"),
        confirm_authorized=False,
    )


# Names are intentionally generic; adapters may import whichever reads most
# naturally without embedding product-specific policy in this module.
ModalRecoveryClassification = SourceContextModalClassification
ModalRecoveryResult = SourceContextModalClassification
classify_modal_recovery = classify_source_context_modal


class TransportFreshness(str, Enum):
    OK = "ok"
    STALE = "stale"
    FUTURE = "future"


class SemanticValidity(str, Enum):
    OK = "ok"
    INVALID = "invalid"


class FrameValidityState(str, Enum):
    VALID_NATIVE = "valid_native"
    CORRUPT_OR_INVALID = "corrupt_or_invalid"
    WRONG_GEOMETRY = "wrong_geometry"
    WRONG_PROFILE = "wrong_profile"
    WRONG_PACKAGE = "wrong_package"
    WRONG_ORIENTATION = "wrong_orientation"


def _require_digest(value: str, field: str) -> None:
    if not _SHA256_HEX.fullmatch(value):
        raise PerceptionBundleError("INVALID_DIGEST", field)


@dataclass(frozen=True)
class NativeFrameIdentity:
    """One capture event identity with distinct transport and semantic digests."""

    capture_kind: CaptureKind
    runtime_session_id: str
    capture_ordinal: int
    capture_completed_monotonic: float
    transport_sha256: str
    semantic_sha256: str
    runtime_profile_id: str
    width: int
    height: int
    label: str = ""
    evidence_path: str = ""

    def __post_init__(self) -> None:
        if self.capture_kind not in ("live", "fixture"):
            raise PerceptionBundleError("INVALID_CAPTURE_KIND", self.capture_kind)
        if not self.runtime_session_id:
            raise PerceptionBundleError("MISSING_SESSION_ID")
        if self.capture_ordinal < 1:
            raise PerceptionBundleError("INVALID_CAPTURE_ORDINAL")
        _require_digest(self.transport_sha256, "transport_sha256")
        _require_digest(self.semantic_sha256, "semantic_sha256")
        if self.width <= 0 or self.height <= 0:
            raise PerceptionBundleError("INVALID_GEOMETRY")
        if not self.runtime_profile_id:
            raise PerceptionBundleError("MISSING_PROFILE_ID")

    def same_capture_event(self, other: "NativeFrameIdentity") -> bool:
        return (
            self.capture_kind == other.capture_kind
            and self.runtime_session_id == other.runtime_session_id
            and self.capture_ordinal == other.capture_ordinal
            and self.capture_completed_monotonic == other.capture_completed_monotonic
            and self.transport_sha256 == other.transport_sha256
            and self.semantic_sha256 == other.semantic_sha256
            and self.runtime_profile_id == other.runtime_profile_id
            and self.width == other.width
            and self.height == other.height
        )


@dataclass(frozen=True)
class FrameContextClassification:
    """Contextual recognition only. context_allows_interaction never authorizes transport."""

    contextual_class: ContextualClass
    context_recognized: bool
    context_allows_interaction: bool
    confidence: float
    supporting_observations: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True)
class ImmutableFrameValidationObservation:
    """Adapter-supplied native-frame validation. Neutral code does not hard-code geometry."""

    source_frame: NativeFrameIdentity
    validity: FrameValidityState
    expected_profile_id: str
    expected_width: int
    expected_height: int
    expected_platform: str = ""
    package_ok: bool | None = None
    orientation_ok: bool | None = None
    supporting_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.expected_profile_id:
            raise PerceptionBundleError("MISSING_EXPECTED_PROFILE")
        if self.expected_width <= 0 or self.expected_height <= 0:
            raise PerceptionBundleError("INVALID_EXPECTED_GEOMETRY")
        identity = self.source_frame
        if self.validity is FrameValidityState.VALID_NATIVE:
            if (
                identity.width != self.expected_width
                or identity.height != self.expected_height
                or identity.runtime_profile_id != self.expected_profile_id
            ):
                raise PerceptionBundleError("FRAME_VALIDATION_INCONSISTENT")
            if self.package_ok is False or self.orientation_ok is False:
                raise PerceptionBundleError("FRAME_VALIDATION_INCONSISTENT")
        if self.validity is FrameValidityState.WRONG_PACKAGE and self.package_ok is not None and self.package_ok is not False:
            raise PerceptionBundleError("FRAME_VALIDATION_INCONSISTENT")
        if (
            self.validity is FrameValidityState.WRONG_ORIENTATION
            and self.orientation_ok is not None
            and self.orientation_ok is not False
        ):
            raise PerceptionBundleError("FRAME_VALIDATION_INCONSISTENT")


@dataclass(frozen=True)
class ImmutableLocalizationObservation:
    source_frame: NativeFrameIdentity
    recognized: bool
    platform: str
    profile_id: str
    zoom_identity: ZoomIdentity
    screen_to_atlas: Matrix3 | None
    viewport_polygon: Polygon
    confidence: float
    supporting_landmarks: tuple[str, ...]
    residual_px: float | None
    ambiguity_state: AmbiguityState
    map_edge_state: str
    frame_sha256: str
    timestamp: str
    stale: bool = False
    overlay: bool = False

    def __post_init__(self) -> None:
        _require_digest(self.frame_sha256, "localization.frame_sha256")
        if self.frame_sha256 != self.source_frame.semantic_sha256:
            raise PerceptionBundleError(
                "SEMANTIC_DIGEST_MISMATCH",
                "localization frame_sha256 must equal source_frame.semantic_sha256",
            )


@dataclass(frozen=True)
class ImmutableBuildingBindingObservation:
    source_frame: NativeFrameIdentity
    building_id: str
    target_roi: Box
    confidence: float
    semantic_evidence: tuple[str, ...]
    frame_sha256: str
    overlay_intersects: bool = False
    ambiguous_overlap: bool = False

    def __post_init__(self) -> None:
        _require_digest(self.frame_sha256, "binding.frame_sha256")
        if self.frame_sha256 != self.source_frame.semantic_sha256:
            raise PerceptionBundleError(
                "SEMANTIC_DIGEST_MISMATCH",
                "binding frame_sha256 must equal source_frame.semantic_sha256",
            )


@dataclass(frozen=True)
class ImmutableKnownModalObservation:
    source_frame: NativeFrameIdentity
    modal_identity: str
    confidence: float
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableTargetObservation:
    """Current-frame interaction candidate. Presence never authorizes dispatch alone."""

    source_frame: NativeFrameIdentity
    target_identity: str
    target_roi: Box
    confidence: float
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableRecognizedScreenObservation:
    source_frame: NativeFrameIdentity
    screen_identity: str
    confidence: float
    supporting_evidence: tuple[str, ...] = ()
    surface_safe_targets: tuple[ImmutableTargetObservation, ...] = ()

    def __post_init__(self) -> None:
        for target in self.surface_safe_targets:
            if not self.source_frame.same_capture_event(target.source_frame):
                raise PerceptionBundleError(
                    "CAPTURE_EVENT_MISMATCH",
                    "surface_safe_target must share the screen observation capture event",
                )


@dataclass(frozen=True)
class ImmutableOverlayObservation:
    source_frame: NativeFrameIdentity
    overlay_identity: str
    confidence: float
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableForbiddenSurfaceObservation:
    source_frame: NativeFrameIdentity
    reason_code: str
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableOcrObservation:
    source_frame: NativeFrameIdentity
    text: str
    roi: Box
    confidence: float
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableRadialObservation:
    """Radial summary for one capture event.

    Optional ``semantics`` may carry the platform-neutral HomeRadialSemantics
    contract. Presence of radial recognition never authorizes transport.
    """

    source_frame: NativeFrameIdentity
    facility_identity: str
    confidence: float
    supporting_evidence: tuple[str, ...] = ()
    semantics: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_frame, NativeFrameIdentity):
            raise PerceptionBundleError("INVALID_SOURCE_FRAME", "radial")
        if not isinstance(self.facility_identity, str) or not self.facility_identity:
            raise PerceptionBundleError("INVALID_RADIAL_FACILITY", "facility_identity")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise PerceptionBundleError("INVALID_RADIAL_CONFIDENCE")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
            raise PerceptionBundleError("INVALID_RADIAL_CONFIDENCE")
        object.__setattr__(self, "confidence", confidence)
        if not isinstance(self.supporting_evidence, tuple) or any(
            not isinstance(item, str) for item in self.supporting_evidence
        ):
            raise PerceptionBundleError("INVALID_RADIAL_EVIDENCE")
        if self.semantics is None:
            return
        # Lazy import keeps production modules free of radial-contract circularity.
        from tasks.radial_semantics import HomeRadialSemantics, validate_bundle_radial_semantics

        if not isinstance(self.semantics, HomeRadialSemantics):
            raise PerceptionBundleError("INVALID_RADIAL_SEMANTICS")
        validate_bundle_radial_semantics(self.source_frame, self.semantics)
        if self.semantics.owning_facility.facility_semantic_id != self.facility_identity:
            raise PerceptionBundleError("RADIAL_OWNER_IDENTITY_MISMATCH")
        if self.semantics.recognition_confidence != self.confidence:
            raise PerceptionBundleError("RADIAL_CONFIDENCE_MISMATCH")


def localization_from_result(
    identity: NativeFrameIdentity,
    localization: LocalizationResult,
) -> ImmutableLocalizationObservation:
    if localization.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError(
            "SEMANTIC_DIGEST_MISMATCH",
            "LocalizationResult.frame_sha256 must equal identity.semantic_sha256",
        )
    return ImmutableLocalizationObservation(
        source_frame=identity,
        recognized=localization.recognized,
        platform=localization.platform,
        profile_id=localization.profile_id,
        zoom_identity=localization.zoom_identity,
        screen_to_atlas=localization.screen_to_atlas,
        viewport_polygon=tuple(tuple(point) for point in localization.viewport_polygon),
        confidence=localization.confidence,
        supporting_landmarks=tuple(localization.supporting_landmarks),
        residual_px=localization.residual_px,
        ambiguity_state=localization.ambiguity_state,
        map_edge_state=localization.map_edge_state,
        frame_sha256=localization.frame_sha256,
        timestamp=localization.timestamp,
        stale=localization.stale,
        overlay=localization.overlay,
    )


def binding_from_result(
    identity: NativeFrameIdentity,
    binding: BuildingBinding,
) -> ImmutableBuildingBindingObservation:
    if binding.frame_sha256 != identity.semantic_sha256:
        raise PerceptionBundleError(
            "SEMANTIC_DIGEST_MISMATCH",
            "BuildingBinding.frame_sha256 must equal identity.semantic_sha256",
        )
    return ImmutableBuildingBindingObservation(
        source_frame=identity,
        building_id=binding.building_id,
        target_roi=tuple(binding.target_roi),
        confidence=binding.confidence,
        semantic_evidence=tuple(binding.semantic_evidence),
        frame_sha256=binding.frame_sha256,
        overlay_intersects=binding.overlay_intersects,
        ambiguous_overlap=binding.ambiguous_overlap,
    )


def _require_same_capture(identity: NativeFrameIdentity, observation_frame: NativeFrameIdentity) -> None:
    if not identity.same_capture_event(observation_frame):
        if (
            identity.runtime_session_id != observation_frame.runtime_session_id
            or identity.capture_ordinal != observation_frame.capture_ordinal
        ):
            raise PerceptionBundleError("CAPTURE_EVENT_MISMATCH")
        raise PerceptionBundleError("CROSS_FRAME_COMPOSITION")


def _home_interaction_candidate(bundle: "FramePerceptionBundle") -> bool:
    if bundle.forbidden_surfaces:
        return False
    if bundle.building_binding is not None:
        binding = bundle.building_binding
        return (
            bool(binding.semantic_evidence)
            and not binding.overlay_intersects
            and not binding.ambiguous_overlap
            and binding.confidence > 0
        )
    if bundle.targets:
        return True
    return False


@dataclass(frozen=True)
class FramePerceptionBundle:
    frame: NativeFrameIdentity
    frame_validation: ImmutableFrameValidationObservation | None = None
    localization: ImmutableLocalizationObservation | None = None
    building_binding: ImmutableBuildingBindingObservation | None = None
    known_modal: ImmutableKnownModalObservation | None = None
    recognized_screen: ImmutableRecognizedScreenObservation | None = None
    overlay: ImmutableOverlayObservation | None = None
    forbidden_surfaces: tuple[ImmutableForbiddenSurfaceObservation, ...] = ()
    ocr_observations: tuple[ImmutableOcrObservation, ...] = ()
    targets: tuple[ImmutableTargetObservation, ...] = ()
    radial: ImmutableRadialObservation | None = None
    context: FrameContextClassification | None = None
    invalidated_after_input: bool = False

    def with_frame_validation(
        self, observation: ImmutableFrameValidationObservation
    ) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        return replace(self, frame_validation=observation, context=None)

    def with_localization(self, observation: ImmutableLocalizationObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        if observation.frame_sha256 != self.frame.semantic_sha256:
            raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
        return replace(self, localization=observation, context=None)

    def with_building_binding(
        self, observation: ImmutableBuildingBindingObservation
    ) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        if observation.frame_sha256 != self.frame.semantic_sha256:
            raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
        if self.localization is not None and observation.frame_sha256 != self.localization.frame_sha256:
            raise PerceptionBundleError("CROSS_FRAME_COMPOSITION")
        return replace(self, building_binding=observation, context=None)

    def with_known_modal(self, observation: ImmutableKnownModalObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        return replace(self, known_modal=observation, context=None)

    def with_recognized_screen(
        self, observation: ImmutableRecognizedScreenObservation
    ) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        for target in observation.surface_safe_targets:
            _require_same_capture(self.frame, target.source_frame)
        return replace(self, recognized_screen=observation, context=None)

    def with_overlay(self, observation: ImmutableOverlayObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        if not observation.overlay_identity:
            raise PerceptionBundleError("UNKNOWN_OVERLAY", "recognized overlay identity required")
        return replace(self, overlay=observation, context=None)

    def with_forbidden_surface(
        self, observation: ImmutableForbiddenSurfaceObservation
    ) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        return replace(
            self,
            forbidden_surfaces=self.forbidden_surfaces + (observation,),
            context=None,
        )

    def with_ocr(self, observation: ImmutableOcrObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        return replace(self, ocr_observations=self.ocr_observations + (observation,), context=None)

    def with_target(self, observation: ImmutableTargetObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        return replace(self, targets=self.targets + (observation,), context=None)

    def with_radial(self, observation: ImmutableRadialObservation) -> "FramePerceptionBundle":
        _require_same_capture(self.frame, observation.source_frame)
        if observation.semantics is not None:
            from tasks.radial_semantics import validate_bundle_radial_semantics

            validate_bundle_radial_semantics(self.frame, observation.semantics)
        return replace(self, radial=observation, context=None)

    def attach_classified_context(self) -> "FramePerceptionBundle":
        """Attach classifier-owned context only. Callers cannot supply a forged classification."""

        return replace(self, context=classify_frame_context(self))

    def invalidate_after_input(self) -> "FramePerceptionBundle":
        """Mark this pre-input bundle unusable for successor-state decisions."""

        return replace(self, invalidated_after_input=True, context=None)

    def checked_navigation_inputs(self) -> tuple[LocalizationResult, BuildingBinding | None]:
        return self.checked_home_context_inputs(
            allowed_contextual_classes=frozenset({ContextualClass.CANONICAL_HOME})
        )

    def checked_home_context_inputs(
        self,
        *,
        allowed_contextual_classes: frozenset[ContextualClass],
    ) -> tuple[LocalizationResult, BuildingBinding | None]:
        if not allowed_contextual_classes:
            raise PerceptionBundleError("MISSING_ALLOWED_CONTEXT_CLASSES")
        if self.invalidated_after_input:
            raise PerceptionBundleError("BUNDLE_INVALIDATED_AFTER_INPUT")
        if self.localization is None:
            raise PerceptionBundleError("MISSING_LOCALIZATION")
        if self.frame_validation is None:
            raise PerceptionBundleError("MISSING_FRAME_VALIDATION")
        _require_same_capture(self.frame, self.localization.source_frame)
        _require_same_capture(self.frame, self.frame_validation.source_frame)
        if self.localization.frame_sha256 != self.frame.semantic_sha256:
            raise PerceptionBundleError("SEMANTIC_DIGEST_MISMATCH")
        status, reason = semantic_validity(self)
        if status is SemanticValidity.INVALID:
            raise PerceptionBundleError(reason)
        if self.frame_validation.validity is not FrameValidityState.VALID_NATIVE:
            raise PerceptionBundleError("NON_NATIVE_OR_INVALID")
        if self.frame_validation.package_ok is False or self.frame_validation.orientation_ok is False:
            raise PerceptionBundleError("FRAME_VALIDATION_INCONSISTENT")
        expected = self.frame_validation
        if (
            self.frame.width != expected.expected_width
            or self.frame.height != expected.expected_height
            or self.frame.runtime_profile_id != expected.expected_profile_id
        ):
            raise PerceptionBundleError("WRONG_GEOMETRY_OR_PROFILE")
        loc = self.localization
        if not loc.recognized:
            raise PerceptionBundleError("LOCALIZATION_NOT_RECOGNIZED")
        if expected.expected_platform and loc.platform != expected.expected_platform:
            raise PerceptionBundleError("WRONG_PLATFORM")
        if loc.profile_id != expected.expected_profile_id:
            raise PerceptionBundleError("WRONG_PROFILE")
        if loc.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
            raise PerceptionBundleError("NONCANONICAL_ZOOM")
        if loc.overlay or self.overlay is not None:
            raise PerceptionBundleError("OVERLAY_PRESENT")
        if loc.stale or loc.ambiguity_state is not AmbiguityState.NONE:
            raise PerceptionBundleError("SEMANTIC_FRAME_INVALID")
        if self.forbidden_surfaces:
            raise PerceptionBundleError("FORBIDDEN_SURFACE")
        derived = classify_frame_context(self)
        if self.context is not None and self.context != derived:
            raise PerceptionBundleError("CONTEXT_CLASSIFICATION_MISMATCH")
        if not derived.context_recognized or derived.contextual_class not in allowed_contextual_classes:
            if allowed_contextual_classes == frozenset({ContextualClass.CANONICAL_HOME}):
                raise PerceptionBundleError("CONTEXT_NOT_CANONICAL_HOME")
            raise PerceptionBundleError(
                "CONTEXT_NOT_PERMITTED_FOR_CHECKPOINT",
                derived.contextual_class.value,
            )
        localization = LocalizationResult(
            recognized=loc.recognized,
            platform=loc.platform,
            profile_id=loc.profile_id,
            zoom_identity=loc.zoom_identity,
            screen_to_atlas=loc.screen_to_atlas,
            viewport_polygon=loc.viewport_polygon,
            confidence=loc.confidence,
            supporting_landmarks=loc.supporting_landmarks,
            residual_px=loc.residual_px,
            ambiguity_state=loc.ambiguity_state,
            map_edge_state=loc.map_edge_state,
            frame_sha256=loc.frame_sha256,
            timestamp=loc.timestamp,
            stale=loc.stale,
            overlay=loc.overlay,
        )
        binding: BuildingBinding | None = None
        if self.building_binding is not None:
            _require_same_capture(self.frame, self.building_binding.source_frame)
            if self.building_binding.frame_sha256 != localization.frame_sha256:
                raise PerceptionBundleError("CROSS_FRAME_COMPOSITION")
            binding = BuildingBinding(
                building_id=self.building_binding.building_id,
                target_roi=self.building_binding.target_roi,
                frame_sha256=self.building_binding.frame_sha256,
                confidence=self.building_binding.confidence,
                semantic_evidence=self.building_binding.semantic_evidence,
                overlay_intersects=self.building_binding.overlay_intersects,
                ambiguous_overlap=self.building_binding.ambiguous_overlap,
            )
        return localization, binding


def bundle_from_identity(identity: NativeFrameIdentity) -> FramePerceptionBundle:
    """Create an empty bundle. Performs no capture."""

    return FramePerceptionBundle(frame=identity)


def transport_freshness(
    identity: NativeFrameIdentity,
    now_monotonic: float,
    max_age_seconds: float,
) -> TransportFreshness:
    age = now_monotonic - identity.capture_completed_monotonic
    if age < 0:
        return TransportFreshness.FUTURE
    if age > max_age_seconds:
        return TransportFreshness.STALE
    return TransportFreshness.OK


def assert_transport_fresh(
    identity: NativeFrameIdentity,
    now_monotonic: float,
    max_age_seconds: float,
) -> None:
    status = transport_freshness(identity, now_monotonic, max_age_seconds)
    if status is TransportFreshness.STALE:
        raise PerceptionBundleError("TRANSPORT_FRAME_STALE")
    if status is TransportFreshness.FUTURE:
        raise PerceptionBundleError("TRANSPORT_FRAME_FUTURE")


def semantic_validity(bundle: FramePerceptionBundle) -> tuple[SemanticValidity, str]:
    """Evaluate semantic validity. Does not use transport age or claim content difference proves freshness."""

    if bundle.invalidated_after_input:
        return SemanticValidity.INVALID, "BUNDLE_INVALIDATED_AFTER_INPUT"
    identity = bundle.frame
    if identity.width <= 0 or identity.height <= 0 or not identity.runtime_profile_id:
        return SemanticValidity.INVALID, "INVALID_GEOMETRY_OR_PROFILE"
    if bundle.frame_validation is not None:
        validation = bundle.frame_validation
        if not identity.same_capture_event(validation.source_frame):
            return SemanticValidity.INVALID, "CAPTURE_EVENT_MISMATCH"
        if validation.validity is not FrameValidityState.VALID_NATIVE:
            return SemanticValidity.INVALID, "NON_NATIVE_OR_INVALID"
        if (
            identity.width != validation.expected_width
            or identity.height != validation.expected_height
            or identity.runtime_profile_id != validation.expected_profile_id
        ):
            return SemanticValidity.INVALID, "WRONG_GEOMETRY_OR_PROFILE"
    if bundle.localization is not None:
        loc = bundle.localization
        if not identity.same_capture_event(loc.source_frame):
            return SemanticValidity.INVALID, "CAPTURE_EVENT_MISMATCH"
        if loc.frame_sha256 != identity.semantic_sha256:
            return SemanticValidity.INVALID, "SEMANTIC_DIGEST_MISMATCH"
        if loc.stale or loc.ambiguity_state is AmbiguityState.STALE_FRAME:
            return SemanticValidity.INVALID, "SEMANTIC_FRAME_INVALID"
        if loc.profile_id and bundle.frame_validation is not None:
            if loc.profile_id != bundle.frame_validation.expected_profile_id:
                return SemanticValidity.INVALID, "WRONG_PROFILE"
        elif loc.profile_id and loc.profile_id != identity.runtime_profile_id:
            return SemanticValidity.INVALID, "WRONG_PROFILE"
    if bundle.building_binding is not None:
        binding = bundle.building_binding
        if not identity.same_capture_event(binding.source_frame):
            return SemanticValidity.INVALID, "CAPTURE_EVENT_MISMATCH"
        if binding.frame_sha256 != identity.semantic_sha256:
            return SemanticValidity.INVALID, "SEMANTIC_DIGEST_MISMATCH"
        if bundle.localization is not None and binding.frame_sha256 != bundle.localization.frame_sha256:
            return SemanticValidity.INVALID, "CROSS_FRAME_COMPOSITION"
    return SemanticValidity.OK, "ok"


def assert_semantic_valid(bundle: FramePerceptionBundle) -> None:
    status, reason = semantic_validity(bundle)
    if status is SemanticValidity.INVALID:
        raise PerceptionBundleError(reason)


def classify_frame_context(bundle: FramePerceptionBundle) -> FrameContextClassification:
    """Classify only from explicitly supplied same-frame observations. No capture."""

    if bundle.invalidated_after_input:
        return FrameContextClassification(
            ContextualClass.UNKNOWN,
            False,
            False,
            0.0,
            ("invalidated_after_input",),
            "BUNDLE_INVALIDATED_AFTER_INPUT",
        )

    if bundle.frame_validation is not None and bundle.frame_validation.validity is not FrameValidityState.VALID_NATIVE:
        return FrameContextClassification(
            ContextualClass.NON_NATIVE_OR_INVALID,
            False,
            False,
            1.0,
            (f"frame_validation:{bundle.frame_validation.validity.value}",),
            "non_native_or_invalid",
        )

    identity = bundle.frame
    if identity.width <= 0 or identity.height <= 0 or not identity.runtime_profile_id:
        return FrameContextClassification(
            ContextualClass.NON_NATIVE_OR_INVALID,
            False,
            False,
            1.0,
            ("invalid_geometry_or_profile",),
            "non_native_or_invalid",
        )

    supports: list[str] = []

    if bundle.known_modal is not None:
        supports.append(f"known_modal:{bundle.known_modal.modal_identity}")
        return FrameContextClassification(
            ContextualClass.KNOWN_MODAL,
            True,
            False,
            bundle.known_modal.confidence,
            tuple(supports),
            "known_modal",
        )

    if bundle.recognized_screen is not None:
        supports.append(f"recognized_screen:{bundle.recognized_screen.screen_identity}")
        # This task has no surface-associated safe-target model beyond an empty tuple.
        allows = bool(bundle.recognized_screen.surface_safe_targets) and not bundle.forbidden_surfaces
        return FrameContextClassification(
            ContextualClass.KNOWN_FULLSCREEN_SURFACE,
            True,
            allows,
            bundle.recognized_screen.confidence,
            tuple(supports),
            "known_fullscreen_surface",
        )

    localization = bundle.localization
    if localization is not None and localization.overlay and bundle.overlay is None:
        supports.append("localization_overlay_without_recognized_identity")
        return FrameContextClassification(
            ContextualClass.UNKNOWN,
            False,
            False,
            max(localization.confidence, 0.0),
            tuple(supports),
            "UNKNOWN_OVERLAY",
        )

    if localization is not None and localization.overlay:
        supports.append("overlay_flag")
        return FrameContextClassification(
            ContextualClass.UNKNOWN,
            False,
            False,
            localization.confidence,
            tuple(supports),
            "UNKNOWN_OVERLAY",
        )

    if bundle.overlay is not None:
        supports.append(f"overlay:{bundle.overlay.overlay_identity}")
        return FrameContextClassification(
            ContextualClass.UNKNOWN,
            False,
            False,
            bundle.overlay.confidence,
            tuple(supports),
            "UNKNOWN_OVERLAY",
        )

    if bundle.forbidden_surfaces:
        supports.append(f"forbidden:{bundle.forbidden_surfaces[0].reason_code}")
        return FrameContextClassification(
            ContextualClass.UNKNOWN,
            False,
            False,
            0.0,
            tuple(supports),
            "FORBIDDEN_SURFACE",
        )

    if (
        localization is not None
        and localization.recognized
        and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
        and not localization.stale
        and localization.ambiguity_state is AmbiguityState.NONE
        and not localization.overlay
    ):
        supports.append("canonical_home_localization")
        allows = _home_interaction_candidate(bundle)
        if bundle.radial is not None:
            supports.append(f"radial:{bundle.radial.facility_identity}")
            if bundle.radial.semantics is not None:
                from tasks.radial_semantics import (
                    ActionabilityState,
                    HomeRadialSemantics,
                    RadialAmbiguityState,
                    RecognitionState,
                )

                semantics = bundle.radial.semantics
                if not isinstance(semantics, HomeRadialSemantics):
                    return FrameContextClassification(
                        ContextualClass.UNKNOWN,
                        False,
                        False,
                        0.0,
                        tuple(supports + ["typed_radial:invalid"]),
                        "TYPED_RADIAL_INVALID",
                    )
                supports.append(
                    "typed_radial:"
                    f"{semantics.recognition_state.value}:"
                    f"{semantics.ambiguity_state.value}"
                )
                if semantics.recognition_state is RecognitionState.UNKNOWN:
                    return FrameContextClassification(
                        ContextualClass.UNKNOWN,
                        False,
                        False,
                        0.0,
                        tuple(supports),
                        "TYPED_RADIAL_UNKNOWN",
                    )
                if (
                    semantics.recognition_state is not RecognitionState.RECOGNIZED
                    or semantics.ambiguity_state is not RadialAmbiguityState.NONE
                ):
                    return FrameContextClassification(
                        ContextualClass.UNKNOWN,
                        False,
                        False,
                        0.0,
                        tuple(supports),
                        "TYPED_RADIAL_AMBIGUOUS",
                    )
                owner = semantics.owning_facility
                supports.append(
                    "typed_radial_owner:"
                    f"{owner.recognition_state.value}:"
                    f"{owner.ambiguity_state.value}"
                )
                if owner.recognition_state is RecognitionState.UNKNOWN:
                    return FrameContextClassification(
                        ContextualClass.UNKNOWN,
                        False,
                        False,
                        0.0,
                        tuple(supports),
                        "TYPED_RADIAL_OWNER_UNKNOWN",
                    )
                if (
                    owner.recognition_state is not RecognitionState.RECOGNIZED
                    or owner.ambiguity_state is not RadialAmbiguityState.NONE
                ):
                    return FrameContextClassification(
                        ContextualClass.UNKNOWN,
                        False,
                        False,
                        0.0,
                        tuple(supports),
                        "TYPED_RADIAL_OWNER_AMBIGUOUS",
                    )
                # Typed radial semantics own interaction candidacy. A building
                # binding or generic target cannot upgrade non-actionable controls.
                allows = any(
                    control.actionability_state is ActionabilityState.ACTIONABLE
                    for control in semantics.controls
                )
            return FrameContextClassification(
                ContextualClass.HOME_WITH_KNOWN_RADIAL,
                True,
                allows,
                min(localization.confidence, bundle.radial.confidence),
                tuple(supports),
                "home_with_known_radial",
            )
        return FrameContextClassification(
            ContextualClass.CANONICAL_HOME,
            True,
            allows,
            localization.confidence,
            tuple(supports),
            "canonical_home",
        )

    if localization is not None:
        supports.append(f"localization:{localization.ambiguity_state.value}")
    return FrameContextClassification(
        ContextualClass.UNKNOWN,
        False,
        False,
        0.0,
        tuple(supports) or ("insufficient_observations",),
        "CONTEXT_UNKNOWN",
    )


def classify_and_attach(bundle: FramePerceptionBundle) -> FramePerceptionBundle:
    return bundle.attach_classified_context()


def bundle_evidence_snapshot(bundle: FramePerceptionBundle) -> dict[str, object]:
    """Deterministic JSON-safe evidence snapshot. Not a full object deserializer."""

    payload = snapshot(bundle)
    if not isinstance(payload, dict):
        raise PerceptionBundleError("SNAPSHOT_FAILED")
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "bundle": payload,
    }
