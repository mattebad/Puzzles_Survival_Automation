"""BlueStacks-only current-frame Home safe-exit binder.

All inputs and outputs are bound to one complete NativeFrameIdentity capture
event in exact BlueStacks native 800x1280 adapter space. Planner-projected
recovery zones are frame-bound, non-authorizing search provenance only.
Recognition, candidate actionability, policy authorization, and transport are
distinct; this module provides no capability, policy grant, or dispatch API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Mapping, Tuple

from tasks.home_atlas_planner import PredictedRecoverySearchZone
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID
from tasks.perception_bundle import NativeFrameIdentity


SCHEMA_NAME = "bluestacks_home_safe_exit"
SCHEMA_VERSION = 1

BLUESTACKS_SAFE_EXIT_WIDTH = 800
BLUESTACKS_SAFE_EXIT_HEIGHT = 1280
BLUESTACKS_SAFE_EXIT_PROFILE_ID = BLUESTACKS_PROFILE_ID
BLUESTACKS_SAFE_EXIT_PLATFORM = BLUESTACKS_PLATFORM
BLISS_REJECTED_PROFILE_ID = "pns-800x1280-v1"
BLISS_REJECTED_PLATFORM = "Bliss OS"

Box = Tuple[int, int, int, int]
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

CONSERVATIVE_GEOMETRY_POLICY = (
    "strict_complete_containment_and_open_exclusion_clearance"
)
GEOMETRY_POLICY_RULES: tuple[str, ...] = (
    "candidate_must_be_completely_contained_in_permitted_safe_space",
    "candidate_must_be_completely_contained_in_search_envelope_when_envelope_constrains",
    "candidate_must_be_openly_disjoint_from_every_exclusion",
    "shared_edges_or_corners_with_exclusions_are_edge_touch_failures",
    "partial_overlap_with_permitted_space_or_exclusions_is_rejected",
    "degenerate_nan_inf_bool_float_and_non_exact_integer_geometry_are_rejected",
)
PROJECTION_PROVENANCE_HONESTY: tuple[str, ...] = (
    "planner_projected_recovery_search_zone_is_non_authorizing_provenance_only",
    "projected_search_envelope_may_constrain_search_but_never_becomes_tap_roi",
    "executable_recovery_coordinate_must_remain_none",
    "current_frame_safe_exit_binding_still_required",
    "projection_does_not_authorize_safe_exit_input",
)


class SafeExitBindingError(ValueError):
    """Fail-closed safe-exit construction or association denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class ExclusionCategory(str, Enum):
    HUD = "hud"
    BUILDINGS = "buildings"
    RADIAL_CONTROLS = "radial_controls"
    SEMANTIC_TARGETS = "semantic_targets"
    KNOWN_INTERACTIVE_REGIONS = "known_interactive_regions"


REQUIRED_EXCLUSION_CATEGORIES: frozenset[ExclusionCategory] = frozenset(
    ExclusionCategory
)


class SafeExitBindingStatus(str, Enum):
    BOUND = "bound"
    UNAVAILABLE = "unavailable"


class SafeExitActionability(str, Enum):
    CANDIDATE = "candidate"
    NON_ACTIONABLE = "non_actionable"


_UNAVAILABLE_REASON_CODES = frozenset(
    {
        "NO_CANDIDATE_PROPOSALS",
        "DUPLICATE_CANDIDATE_ID",
        "NO_VALID_SAFE_EXIT_CANDIDATE",
        "AMBIGUOUS_MULTIPLE_VALID_CANDIDATES",
    }
)
_RESULT_REASON_CODES = _UNAVAILABLE_REASON_CODES | {"SAFE_EXIT_CANDIDATE_BOUND"}


def _require_exact_string(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise SafeExitBindingError("INVALID_STRING", field)
    return value


def _require_exact_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise SafeExitBindingError("INVALID_BOOL", field)
    return value


def _require_exact_int(value: object, field: str) -> int:
    # Deliberately rejects bool, float (including integral floats), NumPy integer
    # lookalikes, strings, NaN, and infinity. Projection geometry is never truncated.
    if type(value) is not int:
        raise SafeExitBindingError("INVALID_GEOMETRY", field)
    return value


def _require_string_tuple(
    value: object,
    field: str,
    *,
    nonempty: bool = False,
    canonical: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", field)
    result = tuple(_require_exact_string(item, field) for item in value)
    if nonempty and not result:
        raise SafeExitBindingError("EMPTY_IMMUTABLE_FIELD", field)
    if len(set(result)) != len(result):
        raise SafeExitBindingError("DUPLICATE_IMMUTABLE_VALUE", field)
    if canonical and result != tuple(sorted(result)):
        raise SafeExitBindingError("NON_CANONICAL_ORDER", field)
    return result


def _require_box(box: object, field: str) -> Box:
    if type(box) is not tuple or len(box) != 4:
        raise SafeExitBindingError("INVALID_BOX", field)
    normalized = (
        _require_exact_int(box[0], f"{field}.x0"),
        _require_exact_int(box[1], f"{field}.y0"),
        _require_exact_int(box[2], f"{field}.x1"),
        _require_exact_int(box[3], f"{field}.y1"),
    )
    if not (normalized[0] < normalized[2] and normalized[1] < normalized[3]):
        raise SafeExitBindingError("DEGENERATE_BOX", field)
    return normalized


def _require_box_in_frame(box: Box, field: str) -> None:
    if not (
        0 <= box[0] < box[2] <= BLUESTACKS_SAFE_EXIT_WIDTH
        and 0 <= box[1] < box[3] <= BLUESTACKS_SAFE_EXIT_HEIGHT
    ):
        raise SafeExitBindingError("BOX_OUT_OF_FRAME", field)


def _require_native_frame(value: object, field: str) -> NativeFrameIdentity:
    if type(value) is not NativeFrameIdentity:
        raise SafeExitBindingError("INVALID_SOURCE_FRAME", field)
    _validate_bluestacks_identity(value)
    return value


def _validate_bluestacks_identity(identity: NativeFrameIdentity) -> None:
    """Revalidate complete identity, including instances forged after construction."""

    if type(identity.capture_kind) is not str or identity.capture_kind not in (
        "live",
        "fixture",
    ):
        raise SafeExitBindingError("INVALID_CAPTURE_KIND", "capture_kind")
    _require_exact_string(identity.runtime_session_id, "runtime_session_id")
    if type(identity.capture_ordinal) is not int or identity.capture_ordinal < 1:
        raise SafeExitBindingError("INVALID_CAPTURE_ORDINAL", "capture_ordinal")
    if type(identity.capture_completed_monotonic) not in (int, float):
        raise SafeExitBindingError(
            "INVALID_CAPTURE_MONOTONIC", "capture_completed_monotonic"
        )
    if type(identity.capture_completed_monotonic) is bool or not math.isfinite(
        float(identity.capture_completed_monotonic)
    ):
        raise SafeExitBindingError(
            "INVALID_CAPTURE_MONOTONIC", "capture_completed_monotonic"
        )
    if identity.capture_completed_monotonic < 0:
        raise SafeExitBindingError(
            "INVALID_CAPTURE_MONOTONIC", "capture_completed_monotonic"
        )
    for field, digest in (
        ("transport_sha256", identity.transport_sha256),
        ("semantic_sha256", identity.semantic_sha256),
    ):
        if type(digest) is not str or not _SHA256_HEX.fullmatch(digest):
            raise SafeExitBindingError("INVALID_DIGEST", field)
    profile_id = _require_exact_string(
        identity.runtime_profile_id, "runtime_profile_id"
    )
    label = identity.label
    if type(label) is not str:
        raise SafeExitBindingError("INVALID_STRING", "label")
    if type(identity.evidence_path) is not str:
        raise SafeExitBindingError("INVALID_STRING", "evidence_path")
    if (
        profile_id == BLISS_REJECTED_PROFILE_ID
        or "bliss" in profile_id.lower()
        or "bliss" in label.lower()
    ):
        raise SafeExitBindingError("BLISS_PROFILE_REJECTED", profile_id)
    if profile_id != BLUESTACKS_SAFE_EXIT_PROFILE_ID:
        raise SafeExitBindingError("WRONG_BLUESTACKS_PROFILE", profile_id)
    if (
        type(identity.width) is not int
        or type(identity.height) is not int
        or identity.width != BLUESTACKS_SAFE_EXIT_WIDTH
        or identity.height != BLUESTACKS_SAFE_EXIT_HEIGHT
    ):
        raise SafeExitBindingError(
            "WRONG_BLUESTACKS_GEOMETRY",
            f"{identity.width}x{identity.height}",
        )


def _require_same_capture(
    left: NativeFrameIdentity,
    right: NativeFrameIdentity,
    *,
    field: str,
) -> None:
    _validate_bluestacks_identity(left)
    _validate_bluestacks_identity(right)
    if left.same_capture_event(right):
        return
    if (
        left.transport_sha256 == right.transport_sha256
        or left.semantic_sha256 == right.semantic_sha256
    ):
        raise SafeExitBindingError("DIGEST_ONLY_JOIN_REJECTED", field)
    raise SafeExitBindingError("CAPTURE_EVENT_MISMATCH", field)


def _completely_contained(inner: Box, outer: Box) -> bool:
    return (
        outer[0] <= inner[0]
        and inner[2] <= outer[2]
        and outer[1] <= inner[1]
        and inner[3] <= outer[3]
    )


def _openly_disjoint(a: Box, b: Box) -> bool:
    return a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]


def _boxes_partially_overlap(a: Box, b: Box) -> bool:
    intersection = (
        max(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        min(a[3], b[3]),
    )
    if not (intersection[0] < intersection[2] and intersection[1] < intersection[3]):
        return False
    return not (_completely_contained(a, b) or _completely_contained(b, a))


def _qualified_region_id(region: "ExclusionRegion") -> str:
    return f"{region.category.value}:{region.region_id}"


@dataclass(frozen=True)
class BlueStacksSafeExitProfile:
    platform: str
    profile_id: str
    width: int
    height: int
    geometry_policy: str = CONSERVATIVE_GEOMETRY_POLICY

    def __post_init__(self) -> None:
        if (
            type(self.platform) is not str
            or self.platform != BLUESTACKS_SAFE_EXIT_PLATFORM
        ):
            raise SafeExitBindingError("WRONG_PLATFORM", "platform")
        if (
            type(self.profile_id) is not str
            or self.profile_id != BLUESTACKS_SAFE_EXIT_PROFILE_ID
        ):
            raise SafeExitBindingError("WRONG_BLUESTACKS_PROFILE", "profile_id")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or self.width != BLUESTACKS_SAFE_EXIT_WIDTH
            or self.height != BLUESTACKS_SAFE_EXIT_HEIGHT
        ):
            raise SafeExitBindingError("WRONG_BLUESTACKS_GEOMETRY")
        if (
            type(self.geometry_policy) is not str
            or self.geometry_policy != CONSERVATIVE_GEOMETRY_POLICY
        ):
            raise SafeExitBindingError("INVALID_GEOMETRY_POLICY")


def bluestacks_safe_exit_profile() -> BlueStacksSafeExitProfile:
    return BlueStacksSafeExitProfile(
        platform=BLUESTACKS_SAFE_EXIT_PLATFORM,
        profile_id=BLUESTACKS_SAFE_EXIT_PROFILE_ID,
        width=BLUESTACKS_SAFE_EXIT_WIDTH,
        height=BLUESTACKS_SAFE_EXIT_HEIGHT,
    )


@dataclass(frozen=True)
class ExclusionRegion:
    source_frame: NativeFrameIdentity
    category: ExclusionCategory
    region_id: str
    box: Box
    supporting_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_exclusion_region(self, canonicalize=True)


def _validate_exclusion_region(
    region: ExclusionRegion, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(region.source_frame, "exclusion.source_frame")
    if type(region.category) is not ExclusionCategory:
        raise SafeExitBindingError("INVALID_EXCLUSION_CATEGORY", "category")
    region_id = _require_exact_string(region.region_id, "region_id")
    box = _require_box(region.box, region_id)
    _require_box_in_frame(box, region_id)
    evidence = _require_string_tuple(region.supporting_evidence, "supporting_evidence")
    canonical_evidence = tuple(sorted(evidence))
    if not canonicalize and evidence != canonical_evidence:
        raise SafeExitBindingError("NON_CANONICAL_ORDER", "supporting_evidence")
    if canonicalize:
        object.__setattr__(region, "source_frame", source)
        object.__setattr__(region, "box", box)
        object.__setattr__(region, "supporting_evidence", canonical_evidence)


@dataclass(frozen=True)
class CategoryCoverageProof:
    source_frame: NativeFrameIdentity
    category: ExclusionCategory
    regions: tuple[ExclusionRegion, ...]
    observed_empty: bool

    def __post_init__(self) -> None:
        _validate_category_coverage(self, canonicalize=True)


def _validate_category_coverage(
    proof: CategoryCoverageProof, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(proof.source_frame, "coverage.source_frame")
    if type(proof.category) is not ExclusionCategory:
        raise SafeExitBindingError(
            "INVALID_EXCLUSION_CATEGORY", "coverage.category"
        )
    _require_exact_bool(proof.observed_empty, "observed_empty")
    if type(proof.regions) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "regions")
    seen: set[str] = set()
    normalized: list[ExclusionRegion] = []
    for region in proof.regions:
        if type(region) is not ExclusionRegion:
            raise SafeExitBindingError("INVALID_EXCLUSION_REGION")
        _validate_exclusion_region(region)
        _require_same_capture(
            source,
            region.source_frame,
            field=f"coverage.{proof.category.value}.{region.region_id}",
        )
        if region.category is not proof.category:
            raise SafeExitBindingError(
                "EXCLUSION_CATEGORY_MISMATCH", region.region_id
            )
        if region.region_id in seen:
            raise SafeExitBindingError("DUPLICATE_EXCLUSION_REGION", region.region_id)
        seen.add(region.region_id)
        normalized.append(region)
    canonical_regions = tuple(
        sorted(
            normalized,
            key=lambda region: (
                region.category.value,
                region.region_id,
                region.box,
                region.supporting_evidence,
            ),
        )
    )
    if not canonicalize and proof.regions != canonical_regions:
        raise SafeExitBindingError("NON_CANONICAL_ORDER", "regions")
    if proof.observed_empty and canonical_regions:
        raise SafeExitBindingError("OBSERVED_EMPTY_WITH_REGIONS", proof.category.value)
    if not proof.observed_empty and not canonical_regions:
        raise SafeExitBindingError("MISSING_CATEGORY_PROOF", proof.category.value)
    if canonicalize:
        object.__setattr__(proof, "source_frame", source)
        object.__setattr__(proof, "regions", canonical_regions)


@dataclass(frozen=True)
class ExclusionInventory:
    source_frame: NativeFrameIdentity
    coverage: tuple[CategoryCoverageProof, ...]

    def __post_init__(self) -> None:
        _validate_exclusion_inventory(self, canonicalize=True)

    def all_regions(self) -> tuple[ExclusionRegion, ...]:
        _validate_exclusion_inventory(self)
        return tuple(
            region for proof in self.coverage for region in proof.regions
        )


def _validate_exclusion_inventory(
    inventory: ExclusionInventory, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(inventory.source_frame, "inventory.source_frame")
    if type(inventory.coverage) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "coverage")
    by_category: dict[ExclusionCategory, CategoryCoverageProof] = {}
    global_region_ids: set[str] = set()
    for proof in inventory.coverage:
        if type(proof) is not CategoryCoverageProof:
            raise SafeExitBindingError("INVALID_CATEGORY_COVERAGE")
        _validate_category_coverage(proof)
        _require_same_capture(
            source, proof.source_frame, field=f"inventory.{proof.category.value}"
        )
        if proof.category in by_category:
            raise SafeExitBindingError(
                "DUPLICATE_CATEGORY_COVERAGE", proof.category.value
            )
        by_category[proof.category] = proof
        for region in proof.regions:
            if region.region_id in global_region_ids:
                raise SafeExitBindingError(
                    "DUPLICATE_EXCLUSION_REGION_ID", region.region_id
                )
            global_region_ids.add(region.region_id)
    missing = REQUIRED_EXCLUSION_CATEGORIES - frozenset(by_category)
    if missing:
        raise SafeExitBindingError(
            "MISSING_CATEGORY_PROOF",
            ",".join(sorted(item.value for item in missing)),
        )
    if len(by_category) != len(REQUIRED_EXCLUSION_CATEGORIES):
        raise SafeExitBindingError("INVALID_CATEGORY_COVERAGE")
    canonical_coverage = tuple(
        by_category[category]
        for category in sorted(by_category, key=lambda item: item.value)
    )
    if not canonicalize and inventory.coverage != canonical_coverage:
        raise SafeExitBindingError("NON_CANONICAL_ORDER", "coverage")
    if canonicalize:
        object.__setattr__(inventory, "source_frame", source)
        object.__setattr__(inventory, "coverage", canonical_coverage)


@dataclass(frozen=True)
class ProjectedRecoverySearchEnvelope:
    """Frame-bound projection provenance; never executable or authorizing."""

    source_frame: NativeFrameIdentity
    available: bool
    zone_box: Box | None
    executable_recovery_coordinate: None = None
    provenance: tuple[str, ...] = PROJECTION_PROVENANCE_HONESTY
    derived_directly_from_projection: bool = False

    def __post_init__(self) -> None:
        _validate_search_envelope(self, canonicalize=True)


def _validate_search_envelope(
    envelope: ProjectedRecoverySearchEnvelope, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(envelope.source_frame, "envelope.source_frame")
    available = _require_exact_bool(envelope.available, "available")
    if envelope.executable_recovery_coordinate is not None:
        raise SafeExitBindingError(
            "EXECUTABLE_RECOVERY_COORDINATE_FORBIDDEN",
            "executable_recovery_coordinate",
        )
    derived = _require_exact_bool(
        envelope.derived_directly_from_projection,
        "derived_directly_from_projection",
    )
    if derived is not False:
        raise SafeExitBindingError(
            "PROJECTION_MUST_NOT_BECOME_EXECUTABLE_ROI",
            "derived_directly_from_projection",
        )
    if type(envelope.provenance) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "provenance")
    if envelope.provenance != PROJECTION_PROVENANCE_HONESTY:
        raise SafeExitBindingError("INVALID_PROJECTION_HONESTY", "provenance")
    zone_box: Box | None = None
    if envelope.zone_box is not None:
        zone_box = _require_box(envelope.zone_box, "envelope.zone_box")
        _require_box_in_frame(zone_box, "envelope.zone_box")
    if available and zone_box is None:
        raise SafeExitBindingError("ENVELOPE_AVAILABLE_WITHOUT_ZONE", "zone_box")
    if not available and zone_box is not None:
        raise SafeExitBindingError("ENVELOPE_UNAVAILABLE_WITH_ZONE", "zone_box")
    if canonicalize:
        object.__setattr__(envelope, "source_frame", source)
        object.__setattr__(envelope, "zone_box", zone_box)


def projected_recovery_zone_as_search_envelope(
    zone: PredictedRecoverySearchZone | None,
    *,
    source_frame: NativeFrameIdentity,
) -> ProjectedRecoverySearchEnvelope | None:
    """Bind planner projection to an explicit capture identity without invention."""

    source = _require_native_frame(source_frame, "projection.source_frame")
    if zone is None:
        return None
    if type(zone) is not PredictedRecoverySearchZone:
        raise SafeExitBindingError("INVALID_PREDICTED_RECOVERY_ZONE")
    if type(zone.available) is not bool:
        raise SafeExitBindingError("INVALID_ENVELOPE", "zone.available")
    if zone.executable_recovery_coordinate is not None:
        raise SafeExitBindingError(
            "EXECUTABLE_RECOVERY_COORDINATE_FORBIDDEN",
            "predicted_recovery_search_zone",
        )
    zone_box: Box | None = None
    if zone.zone_box is not None:
        # No int(...) conversion: non-exact projection geometry fails closed.
        zone_box = _require_box(
            zone.zone_box, "predicted_recovery_search_zone.zone_box"
        )
        _require_box_in_frame(
            zone_box, "predicted_recovery_search_zone.zone_box"
        )
    return ProjectedRecoverySearchEnvelope(
        source_frame=source,
        available=zone.available and zone_box is not None,
        zone_box=zone_box if zone.available else None,
        executable_recovery_coordinate=None,
        provenance=PROJECTION_PROVENANCE_HONESTY,
        derived_directly_from_projection=False,
    )


@dataclass(frozen=True)
class SafeExitCandidateProposal:
    source_frame: NativeFrameIdentity
    candidate_id: str
    box: Box

    def __post_init__(self) -> None:
        _validate_candidate_proposal(self, canonicalize=True)


def _validate_candidate_proposal(
    proposal: SafeExitCandidateProposal, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(proposal.source_frame, "proposal.source_frame")
    candidate_id = _require_exact_string(proposal.candidate_id, "candidate_id")
    box = _require_box(proposal.box, candidate_id)
    _require_box_in_frame(box, candidate_id)
    if canonicalize:
        object.__setattr__(proposal, "source_frame", source)
        object.__setattr__(proposal, "box", box)


@dataclass(frozen=True)
class BoundSafeExitCandidate:
    source_frame: NativeFrameIdentity
    candidate_id: str
    box: Box
    geometry_policy: str
    cleared_exclusion_ids: tuple[str, ...]
    search_envelope_applied: bool
    actionability: SafeExitActionability = SafeExitActionability.CANDIDATE
    authorize_dispatch: bool = False
    capability_grant: None = None
    policy_grant: None = None

    def __post_init__(self) -> None:
        _validate_bound_candidate(self, canonicalize=True)


def _validate_bound_candidate(
    candidate: BoundSafeExitCandidate, *, canonicalize: bool = False
) -> None:
    source = _require_native_frame(candidate.source_frame, "bound.source_frame")
    candidate_id = _require_exact_string(candidate.candidate_id, "candidate_id")
    box = _require_box(candidate.box, candidate_id)
    _require_box_in_frame(box, candidate_id)
    if (
        type(candidate.geometry_policy) is not str
        or candidate.geometry_policy != CONSERVATIVE_GEOMETRY_POLICY
    ):
        raise SafeExitBindingError("INVALID_GEOMETRY_POLICY")
    cleared = _require_string_tuple(
        candidate.cleared_exclusion_ids,
        "cleared_exclusion_ids",
        canonical=True,
    )
    _require_exact_bool(
        candidate.search_envelope_applied, "search_envelope_applied"
    )
    if type(candidate.actionability) is not SafeExitActionability:
        raise SafeExitBindingError("INVALID_ACTIONABILITY")
    if candidate.actionability is not SafeExitActionability.CANDIDATE:
        raise SafeExitBindingError("INVALID_ACTIONABILITY")
    if type(candidate.authorize_dispatch) is not bool:
        raise SafeExitBindingError("INVALID_BOOL", "authorize_dispatch")
    if candidate.authorize_dispatch is not False:
        raise SafeExitBindingError("SAFE_EXIT_MUST_NOT_AUTHORIZE")
    if candidate.capability_grant is not None or candidate.policy_grant is not None:
        raise SafeExitBindingError("SAFE_EXIT_MUST_NOT_GRANT")
    if canonicalize:
        object.__setattr__(candidate, "source_frame", source)
        object.__setattr__(candidate, "box", box)
        object.__setattr__(candidate, "cleared_exclusion_ids", cleared)


@dataclass(frozen=True)
class SafeExitBindingResult:
    status: SafeExitBindingStatus
    reason_code: str
    source_frame: NativeFrameIdentity
    permitted_safe_space: Box
    geometry_policy: str
    exclusion_inventory: ExclusionInventory
    candidate: BoundSafeExitCandidate | None
    rejected_candidates: tuple[tuple[str, str], ...]
    search_envelope: ProjectedRecoverySearchEnvelope | None
    projection_honesty: tuple[str, ...]
    actionability: SafeExitActionability
    authorize_dispatch: bool = False
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        _validate_binding_result(self, canonicalize=True)


def _validate_rejected_candidates(
    value: object, *, canonicalize: bool
) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "rejected_candidates")
    normalized: list[tuple[str, str]] = []
    for entry in value:
        if type(entry) is not tuple or len(entry) != 2:
            raise SafeExitBindingError(
                "INVALID_REJECTED_CANDIDATE", "rejected_candidates"
            )
        candidate_id = _require_exact_string(entry[0], "rejected_candidate.id")
        reason = _require_exact_string(entry[1], "rejected_candidate.reason")
        exact_reasons = {
            "PARTIAL_SAFE_SPACE_OVERLAP",
            "NOT_CONTAINED_IN_SAFE_SPACE",
            "PARTIAL_ENVELOPE_OVERLAP",
            "OUTSIDE_SEARCH_ENVELOPE",
            "PROJECTION_ZONE_MUST_NOT_BECOME_CANDIDATE_ROI",
        }
        exclusion_prefixes = (
            "PARTIAL_EXCLUSION_OVERLAP:",
            "EXCLUSION_CONTAINMENT:",
            "EDGE_TOUCH_OR_OVERLAP:",
        )
        if reason not in exact_reasons and not any(
            reason.startswith(prefix)
            and len(reason) > len(prefix)
            and ":" in reason[len(prefix) :]
            for prefix in exclusion_prefixes
        ):
            raise SafeExitBindingError(
                "INVALID_REJECTED_CANDIDATE_REASON", reason
            )
        normalized.append((candidate_id, reason))
    canonical_value = tuple(sorted(normalized))
    if len(set(canonical_value)) != len(canonical_value):
        raise SafeExitBindingError("DUPLICATE_REJECTED_CANDIDATE")
    if not canonicalize and value != canonical_value:
        raise SafeExitBindingError("NON_CANONICAL_ORDER", "rejected_candidates")
    return canonical_value


def _validate_metadata(
    value: object, *, canonicalize: bool
) -> MappingProxyType:
    if type(value) not in (dict, MappingProxyType):
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "metadata")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[
            _require_exact_string(key, "metadata.key")
        ] = _require_exact_string(item, "metadata.value")
    canonical_items = sorted(normalized.items())
    if not canonicalize and list(value.items()) != canonical_items:
        raise SafeExitBindingError("NON_CANONICAL_ORDER", "metadata")
    return MappingProxyType(dict(canonical_items))


def _validate_binding_result(
    result: SafeExitBindingResult, *, canonicalize: bool = False
) -> None:
    if type(result.status) is not SafeExitBindingStatus:
        raise SafeExitBindingError("INVALID_BINDING_STATUS")
    reason = _require_exact_string(result.reason_code, "reason_code")
    if reason not in _RESULT_REASON_CODES:
        raise SafeExitBindingError("INVALID_REASON_CODE", reason)
    source = _require_native_frame(result.source_frame, "result.source_frame")
    permitted = _require_box(result.permitted_safe_space, "permitted_safe_space")
    _require_box_in_frame(permitted, "permitted_safe_space")
    if (
        type(result.geometry_policy) is not str
        or result.geometry_policy != CONSERVATIVE_GEOMETRY_POLICY
    ):
        raise SafeExitBindingError("INVALID_GEOMETRY_POLICY")
    if type(result.exclusion_inventory) is not ExclusionInventory:
        raise SafeExitBindingError("INVALID_EXCLUSION_INVENTORY")
    _validate_exclusion_inventory(result.exclusion_inventory)
    _require_same_capture(
        source,
        result.exclusion_inventory.source_frame,
        field="result.exclusion_inventory",
    )
    candidate = result.candidate
    if candidate is not None:
        if type(candidate) is not BoundSafeExitCandidate:
            raise SafeExitBindingError("INVALID_BOUND_CANDIDATE")
        _validate_bound_candidate(candidate)
        _require_same_capture(source, candidate.source_frame, field="result.candidate")
        if not _completely_contained(candidate.box, permitted):
            raise SafeExitBindingError("CANDIDATE_OUTSIDE_SAFE_SPACE")
        expected_clearance = tuple(
            sorted(
                _qualified_region_id(region)
                for region in result.exclusion_inventory.all_regions()
            )
        )
        if candidate.cleared_exclusion_ids != expected_clearance:
            raise SafeExitBindingError("INVALID_CLEARED_EXCLUSION_PROVENANCE")
        for region in result.exclusion_inventory.all_regions():
            if not _openly_disjoint(candidate.box, region.box):
                raise SafeExitBindingError("CANDIDATE_INTERSECTS_EXCLUSION")
    envelope = result.search_envelope
    if envelope is not None:
        if type(envelope) is not ProjectedRecoverySearchEnvelope:
            raise SafeExitBindingError("INVALID_ENVELOPE")
        _validate_search_envelope(envelope)
        _require_same_capture(source, envelope.source_frame, field="result.search_envelope")
    if candidate is not None:
        expected_applied = envelope is not None and envelope.available
        if candidate.search_envelope_applied is not expected_applied:
            raise SafeExitBindingError("INVALID_SEARCH_ENVELOPE_APPLIED")
        if expected_applied:
            assert envelope is not None and envelope.zone_box is not None
            if not _completely_contained(candidate.box, envelope.zone_box):
                raise SafeExitBindingError("CANDIDATE_OUTSIDE_SEARCH_ENVELOPE")
            if candidate.box == envelope.zone_box:
                raise SafeExitBindingError(
                    "PROJECTION_ZONE_MUST_NOT_BECOME_CANDIDATE_ROI"
                )
    if type(result.projection_honesty) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "projection_honesty")
    if result.projection_honesty != PROJECTION_PROVENANCE_HONESTY:
        raise SafeExitBindingError("INVALID_PROJECTION_HONESTY")
    if type(result.actionability) is not SafeExitActionability:
        raise SafeExitBindingError("INVALID_ACTIONABILITY")
    if type(result.authorize_dispatch) is not bool:
        raise SafeExitBindingError("INVALID_BOOL", "authorize_dispatch")
    if result.authorize_dispatch is not False:
        raise SafeExitBindingError("SAFE_EXIT_MUST_NOT_AUTHORIZE")
    rejected = _validate_rejected_candidates(
        result.rejected_candidates, canonicalize=canonicalize
    )
    metadata = _validate_metadata(result.metadata, canonicalize=canonicalize)
    if result.status is SafeExitBindingStatus.BOUND:
        if reason != "SAFE_EXIT_CANDIDATE_BOUND" or candidate is None:
            raise SafeExitBindingError("INVALID_BOUND_RESULT")
        if result.actionability is not SafeExitActionability.CANDIDATE:
            raise SafeExitBindingError("INVALID_ACTIONABILITY")
    else:
        if reason not in _UNAVAILABLE_REASON_CODES or candidate is not None:
            raise SafeExitBindingError("INVALID_UNAVAILABLE_RESULT")
        if result.actionability is not SafeExitActionability.NON_ACTIONABLE:
            raise SafeExitBindingError("INVALID_ACTIONABILITY")
    if canonicalize:
        object.__setattr__(result, "source_frame", source)
        object.__setattr__(result, "permitted_safe_space", permitted)
        object.__setattr__(result, "rejected_candidates", rejected)
        object.__setattr__(result, "metadata", metadata)


def safe_exit_authorize_dispatch(_result: SafeExitBindingResult) -> bool:
    """Safe-exit binding alone never authorizes dispatch."""

    return False


def assert_safe_exit_does_not_authorize(result: SafeExitBindingResult) -> None:
    _validate_binding_result(result)
    if safe_exit_authorize_dispatch(result):
        raise SafeExitBindingError("SAFE_EXIT_MUST_NOT_AUTHORIZE")


def _evaluate_candidate(
    proposal: SafeExitCandidateProposal,
    *,
    permitted_safe_space: Box,
    exclusions: tuple[ExclusionRegion, ...],
    envelope: ProjectedRecoverySearchEnvelope | None,
) -> tuple[BoundSafeExitCandidate | None, str]:
    box = proposal.box
    if not _completely_contained(box, permitted_safe_space):
        if _boxes_partially_overlap(box, permitted_safe_space):
            return None, "PARTIAL_SAFE_SPACE_OVERLAP"
        return None, "NOT_CONTAINED_IN_SAFE_SPACE"
    envelope_applied = False
    if envelope is not None and envelope.available:
        assert envelope.zone_box is not None
        envelope_applied = True
        if not _completely_contained(box, envelope.zone_box):
            if _boxes_partially_overlap(box, envelope.zone_box):
                return None, "PARTIAL_ENVELOPE_OVERLAP"
            return None, "OUTSIDE_SEARCH_ENVELOPE"
        if box == envelope.zone_box:
            return None, "PROJECTION_ZONE_MUST_NOT_BECOME_CANDIDATE_ROI"
    cleared: list[str] = []
    for exclusion in exclusions:
        qualified = _qualified_region_id(exclusion)
        if not _openly_disjoint(box, exclusion.box):
            if _boxes_partially_overlap(box, exclusion.box):
                return None, f"PARTIAL_EXCLUSION_OVERLAP:{qualified}"
            if _completely_contained(box, exclusion.box) or _completely_contained(
                exclusion.box, box
            ):
                return None, f"EXCLUSION_CONTAINMENT:{qualified}"
            return None, f"EDGE_TOUCH_OR_OVERLAP:{qualified}"
        cleared.append(qualified)
    return (
        BoundSafeExitCandidate(
            source_frame=proposal.source_frame,
            candidate_id=proposal.candidate_id,
            box=box,
            geometry_policy=CONSERVATIVE_GEOMETRY_POLICY,
            cleared_exclusion_ids=tuple(sorted(cleared)),
            search_envelope_applied=envelope_applied,
            actionability=SafeExitActionability.CANDIDATE,
            authorize_dispatch=False,
            capability_grant=None,
            policy_grant=None,
        ),
        "ok",
    )


def _result(
    *,
    status: SafeExitBindingStatus,
    reason_code: str,
    source_frame: NativeFrameIdentity,
    permitted_safe_space: Box,
    exclusion_inventory: ExclusionInventory,
    candidate: BoundSafeExitCandidate | None,
    rejected_candidates: tuple[tuple[str, str], ...],
    search_envelope: ProjectedRecoverySearchEnvelope | None,
    metadata: Mapping[str, str] | None,
) -> SafeExitBindingResult:
    return SafeExitBindingResult(
        status=status,
        reason_code=reason_code,
        source_frame=source_frame,
        permitted_safe_space=permitted_safe_space,
        geometry_policy=CONSERVATIVE_GEOMETRY_POLICY,
        exclusion_inventory=exclusion_inventory,
        candidate=candidate,
        rejected_candidates=tuple(sorted(rejected_candidates)),
        search_envelope=search_envelope,
        projection_honesty=PROJECTION_PROVENANCE_HONESTY,
        actionability=(
            SafeExitActionability.CANDIDATE
            if status is SafeExitBindingStatus.BOUND
            else SafeExitActionability.NON_ACTIONABLE
        ),
        authorize_dispatch=False,
        metadata={} if metadata is None else metadata,
    )


def bind_bluestacks_home_safe_exit(
    *,
    source_frame: NativeFrameIdentity,
    permitted_safe_space: Box,
    exclusion_inventory: ExclusionInventory,
    proposed_candidates: tuple[SafeExitCandidateProposal, ...],
    search_envelope: ProjectedRecoverySearchEnvelope | None = None,
    metadata: Mapping[str, str] | None = None,
) -> SafeExitBindingResult:
    """Bind exactly one valid candidate or fail closed without authority."""

    source = _require_native_frame(source_frame, "source_frame")
    permitted = _require_box(permitted_safe_space, "permitted_safe_space")
    _require_box_in_frame(permitted, "permitted_safe_space")
    if type(exclusion_inventory) is not ExclusionInventory:
        raise SafeExitBindingError("INVALID_EXCLUSION_INVENTORY")
    _validate_exclusion_inventory(exclusion_inventory)
    _require_same_capture(
        source, exclusion_inventory.source_frame, field="exclusion_inventory"
    )
    if search_envelope is not None:
        if type(search_envelope) is not ProjectedRecoverySearchEnvelope:
            raise SafeExitBindingError("INVALID_ENVELOPE")
        _validate_search_envelope(search_envelope)
        _require_same_capture(
            source, search_envelope.source_frame, field="search_envelope"
        )
    if type(proposed_candidates) is not tuple:
        raise SafeExitBindingError("INVALID_IMMUTABLE_FIELD", "proposed_candidates")
    if metadata is not None:
        _validate_metadata(metadata, canonicalize=True)
    if not proposed_candidates:
        return _result(
            status=SafeExitBindingStatus.UNAVAILABLE,
            reason_code="NO_CANDIDATE_PROPOSALS",
            source_frame=source,
            permitted_safe_space=permitted,
            exclusion_inventory=exclusion_inventory,
            candidate=None,
            rejected_candidates=(),
            search_envelope=search_envelope,
            metadata=metadata,
        )
    proposals: list[SafeExitCandidateProposal] = []
    seen_ids: set[str] = set()
    for proposal in proposed_candidates:
        if type(proposal) is not SafeExitCandidateProposal:
            raise SafeExitBindingError("INVALID_CANDIDATE_PROPOSAL")
        _validate_candidate_proposal(proposal)
        _require_same_capture(source, proposal.source_frame, field=proposal.candidate_id)
        if proposal.candidate_id in seen_ids:
            return _result(
                status=SafeExitBindingStatus.UNAVAILABLE,
                reason_code="DUPLICATE_CANDIDATE_ID",
                source_frame=source,
                permitted_safe_space=permitted,
                exclusion_inventory=exclusion_inventory,
                candidate=None,
                rejected_candidates=(),
                search_envelope=search_envelope,
                metadata=metadata,
            )
        seen_ids.add(proposal.candidate_id)
        proposals.append(proposal)
    proposals.sort(key=lambda item: (item.candidate_id, item.box))
    exclusions = exclusion_inventory.all_regions()
    accepted: list[BoundSafeExitCandidate] = []
    rejected: list[tuple[str, str]] = []
    for proposal in proposals:
        candidate, reason = _evaluate_candidate(
            proposal,
            permitted_safe_space=permitted,
            exclusions=exclusions,
            envelope=search_envelope,
        )
        if candidate is None:
            rejected.append((proposal.candidate_id, reason))
        else:
            accepted.append(candidate)
    if not accepted:
        return _result(
            status=SafeExitBindingStatus.UNAVAILABLE,
            reason_code="NO_VALID_SAFE_EXIT_CANDIDATE",
            source_frame=source,
            permitted_safe_space=permitted,
            exclusion_inventory=exclusion_inventory,
            candidate=None,
            rejected_candidates=tuple(rejected),
            search_envelope=search_envelope,
            metadata=metadata,
        )
    if len(accepted) > 1:
        return _result(
            status=SafeExitBindingStatus.UNAVAILABLE,
            reason_code="AMBIGUOUS_MULTIPLE_VALID_CANDIDATES",
            source_frame=source,
            permitted_safe_space=permitted,
            exclusion_inventory=exclusion_inventory,
            candidate=None,
            rejected_candidates=tuple(rejected),
            search_envelope=search_envelope,
            metadata=metadata,
        )
    return _result(
        status=SafeExitBindingStatus.BOUND,
        reason_code="SAFE_EXIT_CANDIDATE_BOUND",
        source_frame=source,
        permitted_safe_space=permitted,
        exclusion_inventory=exclusion_inventory,
        candidate=accepted[0],
        rejected_candidates=tuple(rejected),
        search_envelope=search_envelope,
        metadata=metadata,
    )


def safe_exit_evidence_snapshot(result: SafeExitBindingResult) -> dict[str, object]:
    """Deterministic JSON-safe snapshot after full forged-state revalidation."""

    if type(result) is not SafeExitBindingResult:
        raise SafeExitBindingError("INVALID_BINDING_RESULT")
    _validate_binding_result(result)
    payload = _plain_for_snapshot(result)
    if type(payload) is not dict:
        raise SafeExitBindingError("SNAPSHOT_FAILED")
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "platform": BLUESTACKS_SAFE_EXIT_PLATFORM,
        "profile_id": BLUESTACKS_SAFE_EXIT_PROFILE_ID,
        "geometry_policy": CONSERVATIVE_GEOMETRY_POLICY,
        "authorize_dispatch": False,
        "safe_exit_binding": payload,
    }


def _plain_for_snapshot(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, NativeFrameIdentity):
        _validate_bluestacks_identity(value)
        from dataclasses import fields

        return {field.name: _plain_for_snapshot(getattr(value, field.name)) for field in fields(value)}
    if isinstance(
        value,
        (
            ExclusionRegion,
            CategoryCoverageProof,
            ExclusionInventory,
            ProjectedRecoverySearchEnvelope,
            SafeExitCandidateProposal,
            BoundSafeExitCandidate,
            SafeExitBindingResult,
            BlueStacksSafeExitProfile,
        ),
    ):
        from dataclasses import fields

        return {field.name: _plain_for_snapshot(getattr(value, field.name)) for field in fields(value)}
    if type(value) is tuple:
        return [_plain_for_snapshot(item) for item in value]
    if type(value) in (dict, MappingProxyType):
        return {
            key: _plain_for_snapshot(item)
            for key, item in sorted(value.items())
        }
    if type(value) in (str, int, float, bool) or value is None:
        if type(value) is float and not math.isfinite(value):
            raise SafeExitBindingError("NON_FINITE_SNAPSHOT_VALUE")
        return value
    raise SafeExitBindingError("NON_JSON_SAFE_SNAPSHOT_VALUE", type(value).__name__)
