"""Evidence-gated contracts for native Campaign map survey preparation and activation.

Prep retains a zero-input dry-run boundary. The activated scan contract is a separate
explicit budget (272 navigation-only inputs, one session) with fail-closed session,
manifest, journal, and accounting schemas. Registration measurements never authorize
input. No atlas geometry, consumer integration, or consequential surfaces live here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any, Iterable, Mapping


CAMPAIGN_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
CAMPAIGN_PLATFORM = "BlueStacks 5 / Android"
CAMPAIGN_PACKAGE = "com.global.ztmslg"
NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
FLOW_ID = "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
MASK_CONTRACT_ID = "campaign-map-fixed-hud-v1"

ACTIVATED_EDGE_STEPS_PER_DIRECTION = 32
ACTIVATED_EDGE_DIRECTIONS = 4
ACTIVATED_EDGE_STEPS_TOTAL = ACTIVATED_EDGE_STEPS_PER_DIRECTION * ACTIVATED_EDGE_DIRECTIONS
ACTIVATED_OVERLAP_STEPS = 128
ACTIVATED_AUXILIARY_INPUTS = 16
ACTIVATED_TRANSPORT_INPUT_CEILING = (
    ACTIVATED_EDGE_STEPS_TOTAL + ACTIVATED_OVERLAP_STEPS + ACTIVATED_AUXILIARY_INPUTS
)
ACTIVATED_MAXIMUM_SESSIONS = 1
# Upper bound only: each navigation input retains source/before/transport/post/result refs.
ACTIVATED_MAXIMUM_NATIVE_FRAMES = ACTIVATED_TRANSPORT_INPUT_CEILING * 5

# Live survey remains inadmissible until these evidence gaps close.
LIVE_SURVEY_PREFLIGHT_BLOCKERS: tuple[str, ...] = (
    (
        "evidence_required: overlap_association_and_coverage_policy_absent;"
        "do_not_spend_overlap_inputs_without_reviewed_measurement_association"
    ),
    (
        "evidence_required: difficulty_exit_base_targets_are_compile_time_static_rois;"
        "require_current_frame_measured_template_or_ocr_associated_geometry_before_tap"
    ),
    (
        "evidence_required: safe_action_successor_reconciliation_is_non_trivial_and_absent;"
        "require_fresh_recapture_and_semantic_successor_proof_before_live_clearance"
    ),
)


def live_survey_preflight_blockers() -> tuple[str, ...]:
    """Exact pre-input blockers; nonempty means live_preflight is inadmissible."""

    return LIVE_SURVEY_PREFLIGHT_BLOCKERS


def live_survey_preflight_is_admissible() -> bool:
    return len(live_survey_preflight_blockers()) == 0


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIFFICULTY_SWITCH_POLICY = "explicit_comparison_only_never_recenter"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.right, self.bottom)
        if any(type(value) is not int for value in values):
            raise ValueError("rectangle coordinates must be integers")
        if not (0 <= self.left < self.right <= NATIVE_WIDTH):
            raise ValueError("rectangle x bounds exceed the native viewport")
        if not (0 <= self.top < self.bottom <= NATIVE_HEIGHT):
            raise ValueError("rectangle y bounds exceed the native viewport")


@dataclass(frozen=True)
class NativeFrameProvenance:
    """Hash-bound metadata required before a native frame can enter a survey."""

    source_id: str
    capture_kind: str
    runtime_session_id: str
    capture_ordinal: int
    capture_completed_monotonic: float
    transport_sha256: str
    semantic_sha256: str
    captured_at_utc: str
    width: int
    height: int
    profile_id: str = CAMPAIGN_PROFILE_ID
    platform: str = CAMPAIGN_PLATFORM
    package: str = CAMPAIGN_PACKAGE

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.capture_kind not in ("live", "fixture"):
            raise ValueError("capture_kind must be live or fixture")
        if not self.runtime_session_id.strip():
            raise ValueError("runtime_session_id is required")
        if type(self.capture_ordinal) is not int or self.capture_ordinal < 1:
            raise ValueError("capture_ordinal must be a positive integer")
        if not math.isfinite(self.capture_completed_monotonic) or self.capture_completed_monotonic < 0:
            raise ValueError("capture_completed_monotonic must be finite and nonnegative")
        if not _SHA256.fullmatch(self.transport_sha256):
            raise ValueError("transport_sha256 must be a lowercase SHA-256 digest")
        if not _SHA256.fullmatch(self.semantic_sha256):
            raise ValueError("semantic_sha256 must be a lowercase SHA-256 digest")
        try:
            captured = datetime.fromisoformat(self.captured_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("captured_at_utc must be ISO-8601") from exc
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("captured_at_utc must include a UTC offset")
        if captured.utcoffset().total_seconds() != 0:
            raise ValueError("captured_at_utc must be expressed in UTC")
        if (self.width, self.height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
            raise ValueError("Campaign survey frames must be native 800x1280")
        if self.profile_id != CAMPAIGN_PROFILE_ID:
            raise ValueError("unsupported Campaign runtime profile")
        if self.platform != CAMPAIGN_PLATFORM:
            raise ValueError("unsupported Campaign platform")
        if self.package != CAMPAIGN_PACKAGE:
            raise ValueError("unsupported Campaign package")


@dataclass(frozen=True)
class HudMaskContract:
    contract_id: str
    profile_id: str
    width: int
    height: int
    excluded_rectangles: tuple[Rect, ...]

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("mask contract_id is required")
        if self.profile_id != CAMPAIGN_PROFILE_ID:
            raise ValueError("mask must be bound to the Campaign runtime profile")
        if (self.width, self.height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
            raise ValueError("mask must be bound to native 800x1280")
        if not self.excluded_rectangles:
            raise ValueError("mask must declare fixed-HUD exclusions")


class SurveyPhase(str, Enum):
    EDGE_TOP = "edge_top"
    EDGE_RIGHT = "edge_right"
    EDGE_BOTTOM = "edge_bottom"
    EDGE_LEFT = "edge_left"
    OVERLAPPING_VIEWPORTS = "overlapping_viewports"
    DIFFICULTY_GEOMETRY_PAIR = "difficulty_geometry_pair"
    SAFE_TERMINAL = "safe_terminal"


class ContractKind(str, Enum):
    PREP = "prep"
    ACTIVATED = "activated"


class CollectorDisposition(str, Enum):
    EVIDENCE_REQUIRED = "evidence_required"
    BLOCKED_FAIL_CLOSED = "blocked_fail_closed"
    NATIVE_SURVEY_COMPLETE = "native_survey_complete"


class FrameDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FrameRejectionReason(str, Enum):
    NON_NATIVE_DIMENSIONS = "non_native_dimensions"
    UNHASHED = "unhashed"
    LOCAL_CANDIDATE = "local_candidate"
    WRONG_PROFILE = "wrong_profile"
    WRONG_PACKAGE = "wrong_package"
    WRONG_MASK = "wrong_mask"
    ORDINAL_OR_TIME_INVALID = "ordinal_or_time_invalid"
    SOURCE_IDENTITY_INVALID = "source_identity_invalid"
    HASH_MISMATCH = "hash_mismatch"
    SYNTHETIC_OR_PLACEHOLDER = "synthetic_or_placeholder"


class InputBudgetCategory(str, Enum):
    EDGE_CLAMP = "edge_clamp"
    OVERLAP = "overlap"
    AUXILIARY = "auxiliary"


class LandmarkKind(str, Enum):
    CHAPTER = "chapter"
    PRISON_TRIAL = "prison_trial"
    ULTIMATE_CHALLENGE = "ultimate_challenge"


@dataclass(frozen=True)
class CampaignScanContract:
    """Bounded survey topology. Prep is zero-input; activated is the 272 ceiling."""

    phases: tuple[SurveyPhase, ...]
    maximum_edge_steps_per_direction: int
    maximum_overlapping_viewports: int
    maximum_auxiliary_inputs: int
    overlap_evidence_required: bool
    maximum_transport_inputs: int
    maximum_native_frames: int
    maximum_sessions: int
    explicit_activation_required: bool
    build_atlas: bool
    contract_kind: ContractKind
    difficulty_switch_policy: str = _DIFFICULTY_SWITCH_POLICY

    def __post_init__(self) -> None:
        required = tuple(SurveyPhase)
        if self.phases != required:
            raise ValueError("scan phases must preserve the bounded reviewed topology")
        if type(self.maximum_edge_steps_per_direction) is not int or not (
            1 <= self.maximum_edge_steps_per_direction <= ACTIVATED_EDGE_STEPS_PER_DIRECTION
        ):
            raise ValueError("edge survey cap must be between 1 and 32 steps per direction")
        if type(self.maximum_overlapping_viewports) is not int or not (
            1 <= self.maximum_overlapping_viewports <= ACTIVATED_OVERLAP_STEPS
        ):
            raise ValueError("overlap survey cap must be between 1 and 128 viewports")
        if type(self.maximum_auxiliary_inputs) is not int or self.maximum_auxiliary_inputs < 0:
            raise ValueError("auxiliary input cap must be a nonnegative integer")
        if not self.overlap_evidence_required:
            raise ValueError("overlapping viewport evidence must be required")
        if self.difficulty_switch_policy != _DIFFICULTY_SWITCH_POLICY:
            raise ValueError("difficulty switching is explicit comparison only")
        if self.build_atlas:
            raise ValueError("atlas construction is prohibited before native survey evidence")
        if self.contract_kind is ContractKind.PREP:
            if (
                self.maximum_transport_inputs != 0
                or self.maximum_native_frames != 0
                or self.maximum_auxiliary_inputs != 0
                or self.maximum_sessions != 0
            ):
                raise ValueError("prep contract must retain zero input and zero acquisition budgets")
            if not self.explicit_activation_required:
                raise ValueError("prep contract must require separate explicit activation")
            return
        if self.contract_kind is not ContractKind.ACTIVATED:
            raise ValueError("unknown Campaign scan contract kind")
        if self.explicit_activation_required:
            raise ValueError("activated contract is already the explicit activation surface")
        if self.maximum_edge_steps_per_direction != ACTIVATED_EDGE_STEPS_PER_DIRECTION:
            raise ValueError("activated edge cap must be exactly 32 steps per direction")
        if self.maximum_overlapping_viewports != ACTIVATED_OVERLAP_STEPS:
            raise ValueError("activated overlap cap must be exactly 128 steps")
        if self.maximum_auxiliary_inputs != ACTIVATED_AUXILIARY_INPUTS:
            raise ValueError("activated auxiliary cap must be exactly 16 inputs")
        if self.maximum_transport_inputs != ACTIVATED_TRANSPORT_INPUT_CEILING:
            raise ValueError("activated transport ceiling must be exactly 272")
        if self.maximum_sessions != ACTIVATED_MAXIMUM_SESSIONS:
            raise ValueError("activated survey allows exactly one session")
        if self.maximum_native_frames != ACTIVATED_MAXIMUM_NATIVE_FRAMES:
            raise ValueError("activated native-frame ceiling must match the evidence-sequence bound")
        edge_total = self.maximum_edge_steps_per_direction * ACTIVATED_EDGE_DIRECTIONS
        if (
            edge_total + self.maximum_overlapping_viewports + self.maximum_auxiliary_inputs
            != self.maximum_transport_inputs
        ):
            raise ValueError("activated budget partitions must sum to the transport ceiling")


@dataclass(frozen=True)
class CollectorReport:
    disposition: CollectorDisposition
    reason: str
    transport_dispatched: bool
    transport_input_count: int
    native_frames_acquired: int
    evidence_artifacts: tuple[str, ...]
    atlas_created: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["disposition"] = self.disposition.value
        payload["evidence_artifacts"] = list(self.evidence_artifacts)
        return payload


@dataclass(frozen=True)
class InputBudgetAccounting:
    edge_clamp_used: int = 0
    overlap_used: int = 0
    auxiliary_used: int = 0
    maximum_edge_clamp: int = ACTIVATED_EDGE_STEPS_TOTAL
    maximum_overlap: int = ACTIVATED_OVERLAP_STEPS
    maximum_auxiliary: int = ACTIVATED_AUXILIARY_INPUTS

    def __post_init__(self) -> None:
        for name in (
            "edge_clamp_used",
            "overlap_used",
            "auxiliary_used",
            "maximum_edge_clamp",
            "maximum_overlap",
            "maximum_auxiliary",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.edge_clamp_used > self.maximum_edge_clamp:
            raise ValueError("edge-clamp budget exceeded")
        if self.overlap_used > self.maximum_overlap:
            raise ValueError("overlap budget exceeded")
        if self.auxiliary_used > self.maximum_auxiliary:
            raise ValueError("auxiliary budget exceeded")

    @property
    def transport_inputs_used(self) -> int:
        return self.edge_clamp_used + self.overlap_used + self.auxiliary_used

    @property
    def maximum_transport_inputs(self) -> int:
        return self.maximum_edge_clamp + self.maximum_overlap + self.maximum_auxiliary

    def record(self, category: InputBudgetCategory) -> "InputBudgetAccounting":
        if category is InputBudgetCategory.EDGE_CLAMP:
            return InputBudgetAccounting(
                edge_clamp_used=self.edge_clamp_used + 1,
                overlap_used=self.overlap_used,
                auxiliary_used=self.auxiliary_used,
                maximum_edge_clamp=self.maximum_edge_clamp,
                maximum_overlap=self.maximum_overlap,
                maximum_auxiliary=self.maximum_auxiliary,
            )
        if category is InputBudgetCategory.OVERLAP:
            return InputBudgetAccounting(
                edge_clamp_used=self.edge_clamp_used,
                overlap_used=self.overlap_used + 1,
                auxiliary_used=self.auxiliary_used,
                maximum_edge_clamp=self.maximum_edge_clamp,
                maximum_overlap=self.maximum_overlap,
                maximum_auxiliary=self.maximum_auxiliary,
            )
        if category is InputBudgetCategory.AUXILIARY:
            return InputBudgetAccounting(
                edge_clamp_used=self.edge_clamp_used,
                overlap_used=self.overlap_used,
                auxiliary_used=self.auxiliary_used + 1,
                maximum_edge_clamp=self.maximum_edge_clamp,
                maximum_overlap=self.maximum_overlap,
                maximum_auxiliary=self.maximum_auxiliary,
            )
        raise ValueError("unknown input budget category")

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_clamp_used": self.edge_clamp_used,
            "overlap_used": self.overlap_used,
            "auxiliary_used": self.auxiliary_used,
            "transport_inputs_used": self.transport_inputs_used,
            "maximum_edge_clamp": self.maximum_edge_clamp,
            "maximum_overlap": self.maximum_overlap,
            "maximum_auxiliary": self.maximum_auxiliary,
            "maximum_transport_inputs": self.maximum_transport_inputs,
        }


@dataclass(frozen=True)
class SurveySessionManifest:
    schema_version: int
    flow_id: str
    session_id: str
    contract_kind: ContractKind
    profile_id: str
    platform: str
    package: str
    mask_contract_id: str
    native_width: int
    native_height: int
    maximum_transport_inputs: int
    maximum_sessions: int
    session_index: int
    created_at_utc: str
    difficulty_switch_policy: str = _DIFFICULTY_SWITCH_POLICY
    registration_authorizes_input: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported survey session manifest schema")
        if self.flow_id != FLOW_ID:
            raise ValueError("manifest flow_id mismatch")
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if self.contract_kind is not ContractKind.ACTIVATED:
            raise ValueError("live survey manifest requires the activated contract")
        if self.profile_id != CAMPAIGN_PROFILE_ID:
            raise ValueError("manifest profile mismatch")
        if self.platform != CAMPAIGN_PLATFORM:
            raise ValueError("manifest platform mismatch")
        if self.package != CAMPAIGN_PACKAGE:
            raise ValueError("manifest package mismatch")
        if self.mask_contract_id != MASK_CONTRACT_ID:
            raise ValueError("manifest mask identity mismatch")
        if (self.native_width, self.native_height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
            raise ValueError("manifest must declare native 800x1280")
        if self.maximum_transport_inputs != ACTIVATED_TRANSPORT_INPUT_CEILING:
            raise ValueError("manifest transport ceiling must be 272")
        if self.maximum_sessions != ACTIVATED_MAXIMUM_SESSIONS:
            raise ValueError("manifest allows exactly one session")
        if self.session_index != 1:
            raise ValueError("only session_index 1 is authorized")
        if self.difficulty_switch_policy != _DIFFICULTY_SWITCH_POLICY:
            raise ValueError("manifest difficulty policy mismatch")
        if self.registration_authorizes_input:
            raise ValueError("registration measurement must never authorize input")
        _require_utc(self.created_at_utc)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["contract_kind"] = self.contract_kind.value
        return payload


@dataclass(frozen=True)
class FrameClassification:
    disposition: FrameDisposition
    provenance: NativeFrameProvenance | None
    mask_contract_id: str
    rejection_reason: FrameRejectionReason | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.disposition is FrameDisposition.ACCEPTED:
            if self.provenance is None:
                raise ValueError("accepted frames require provenance")
            if self.rejection_reason is not None:
                raise ValueError("accepted frames cannot carry a rejection reason")
            if self.mask_contract_id != MASK_CONTRACT_ID:
                raise ValueError("accepted frames must bind the Campaign HUD mask")
            return
        if self.disposition is FrameDisposition.REJECTED:
            if self.rejection_reason is None:
                raise ValueError("rejected frames require an explicit reason")
            return
        raise ValueError("unknown frame disposition")

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "provenance": asdict(self.provenance) if self.provenance is not None else None,
            "mask_contract_id": self.mask_contract_id,
            "rejection_reason": None
            if self.rejection_reason is None
            else self.rejection_reason.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class NavigationEvidenceSequence:
    source_path: str
    immediate_before_path: str
    transport_record_path: str
    immediate_post_path: str
    semantic_result_path: str

    def __post_init__(self) -> None:
        for name in (
            "source_path",
            "immediate_before_path",
            "transport_record_path",
            "immediate_post_path",
            "semantic_result_path",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required for every navigation input")


class InputLifecycle(str, Enum):
    PREPARED = "prepared"
    INPUT_SENT = "input_sent"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class NavigationJournalEntry:
    input_ordinal: int
    phase: SurveyPhase
    budget_category: InputBudgetCategory
    evidence: NavigationEvidenceSequence
    terminal_classification: str
    identical_retry: bool = False
    lifecycle: InputLifecycle = InputLifecycle.TERMINAL
    prior_progress_proven: bool = False
    swipe_geometry: tuple[int, int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if type(self.input_ordinal) is not int or self.input_ordinal < 1:
            raise ValueError("input_ordinal must be a positive integer")
        if self.identical_retry:
            raise ValueError("identical blind retries are prohibited")
        if not self.terminal_classification.strip():
            raise ValueError("terminal_classification is required")
        if self.lifecycle is InputLifecycle.UNRESOLVED and self.terminal_classification == "safe_terminal":
            raise ValueError("unresolved navigation cannot claim safe terminal")

    def to_dict(self) -> dict[str, object]:
        return {
            "input_ordinal": self.input_ordinal,
            "phase": self.phase.value,
            "budget_category": self.budget_category.value,
            "evidence": asdict(self.evidence),
            "terminal_classification": self.terminal_classification,
            "identical_retry": self.identical_retry,
            "lifecycle": self.lifecycle.value,
            "prior_progress_proven": self.prior_progress_proven,
            "swipe_geometry": list(self.swipe_geometry) if self.swipe_geometry else None,
        }


@dataclass(frozen=True)
class EdgeClampReport:
    direction: str
    clamp_observed: bool
    supporting_frame_sha256: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.direction not in {"top", "right", "bottom", "left"}:
            raise ValueError("edge clamp direction must be one of top/right/bottom/left")
        if not _SHA256.fullmatch(self.supporting_frame_sha256):
            raise ValueError("edge clamp requires a supporting native frame hash")


@dataclass(frozen=True)
class OverlapAssociationReport:
    reference_sha256: str
    candidate_sha256: str
    overlap_ratio: float
    associated: bool
    notes: str = ""

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.reference_sha256) or not _SHA256.fullmatch(
            self.candidate_sha256
        ):
            raise ValueError("overlap association requires hash-bound frames")
        if not math.isfinite(self.overlap_ratio) or not (0.0 <= self.overlap_ratio <= 1.0):
            raise ValueError("overlap_ratio must be finite in [0, 1]")


@dataclass(frozen=True)
class RegistrationResidualReport:
    candidate_sha256: str
    reference_sha256: str
    residual_px: float
    inliers: int
    matches: int
    overlap_ratio: float
    authorizes_input: bool = False

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.candidate_sha256) or not _SHA256.fullmatch(
            self.reference_sha256
        ):
            raise ValueError("registration residual report requires hash-bound frames")
        if self.authorizes_input:
            raise ValueError("registration measurement must never authorize input")
        if not math.isfinite(self.residual_px) or self.residual_px < 0:
            raise ValueError("residual_px must be finite and nonnegative")
        if type(self.inliers) is not int or self.inliers < 0:
            raise ValueError("inliers must be a nonnegative integer")
        if type(self.matches) is not int or self.matches < 0:
            raise ValueError("matches must be a nonnegative integer")
        if not math.isfinite(self.overlap_ratio) or not (0.0 <= self.overlap_ratio <= 1.0):
            raise ValueError("overlap_ratio must be finite in [0, 1]")


@dataclass(frozen=True)
class CoverageGapReport:
    gap_id: str
    description: str
    unresolved: bool

    def __post_init__(self) -> None:
        if not self.gap_id.strip() or not self.description.strip():
            raise ValueError("coverage gaps require identity and description")


@dataclass(frozen=True)
class LoopClosureReport:
    closed: bool
    residual_px: float
    supporting_frame_sha256: str

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.supporting_frame_sha256):
            raise ValueError("loop closure requires a supporting native frame hash")
        if not math.isfinite(self.residual_px) or self.residual_px < 0:
            raise ValueError("loop closure residual must be finite and nonnegative")


@dataclass(frozen=True)
class CrossDifficultyGeometryReport:
    difficulty_a: int
    difficulty_b: int
    compared: bool
    used_as_recenter: bool
    conclusion: str

    def __post_init__(self) -> None:
        if {self.difficulty_a, self.difficulty_b} != {1, 2}:
            raise ValueError("cross-difficulty comparison must be Story difficulties 1 and 2")
        if self.used_as_recenter:
            raise ValueError("difficulty switching must never be used as recentering")
        if not self.compared:
            raise ValueError("cross-difficulty geometry requires an explicit comparison")
        if not self.conclusion.strip():
            raise ValueError("cross-difficulty conclusion is required")


@dataclass(frozen=True)
class LandmarkBindingReport:
    kind: LandmarkKind
    label: str
    supporting_frame_sha256: str
    spatially_associated: bool
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("landmark label is required")
        if not _SHA256.fullmatch(self.supporting_frame_sha256):
            raise ValueError("landmark binding requires a supporting native frame hash")
        if not self.spatially_associated:
            raise ValueError("landmark OCR/text must be spatially associated with the target")


@dataclass(frozen=True)
class SafeTerminalReport:
    recognized: bool
    terminal_state: str
    supporting_frame_sha256: str

    def __post_init__(self) -> None:
        if not self.recognized:
            raise ValueError("safe terminal must be positively recognized")
        if not self.terminal_state.strip():
            raise ValueError("terminal_state is required")
        if not _SHA256.fullmatch(self.supporting_frame_sha256):
            raise ValueError("safe terminal requires a supporting native frame hash")


@dataclass(frozen=True)
class SurveySessionReport:
    manifest: SurveySessionManifest
    accounting: InputBudgetAccounting
    accepted_frames: tuple[FrameClassification, ...]
    rejected_frames: tuple[FrameClassification, ...]
    journal: tuple[NavigationJournalEntry, ...]
    edge_clamps: tuple[EdgeClampReport, ...]
    overlaps: tuple[OverlapAssociationReport, ...]
    registration_residuals: tuple[RegistrationResidualReport, ...]
    coverage_gaps: tuple[CoverageGapReport, ...]
    loop_closure: LoopClosureReport | None
    cross_difficulty: CrossDifficultyGeometryReport | None
    landmarks: tuple[LandmarkBindingReport, ...]
    safe_terminal: SafeTerminalReport | None
    disposition: CollectorDisposition
    reason: str
    transport_dispatched: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "accounting": self.accounting.to_dict(),
            "accepted_frames": [item.to_dict() for item in self.accepted_frames],
            "rejected_frames": [item.to_dict() for item in self.rejected_frames],
            "journal": [item.to_dict() for item in self.journal],
            "edge_clamps": [asdict(item) for item in self.edge_clamps],
            "overlaps": [asdict(item) for item in self.overlaps],
            "registration_residuals": [asdict(item) for item in self.registration_residuals],
            "coverage_gaps": [asdict(item) for item in self.coverage_gaps],
            "loop_closure": None if self.loop_closure is None else asdict(self.loop_closure),
            "cross_difficulty": None
            if self.cross_difficulty is None
            else asdict(self.cross_difficulty),
            "landmarks": [
                {**asdict(item), "kind": item.kind.value} for item in self.landmarks
            ],
            "safe_terminal": None if self.safe_terminal is None else asdict(self.safe_terminal),
            "disposition": self.disposition.value,
            "reason": self.reason,
            "transport_dispatched": self.transport_dispatched,
        }


def _require_utc(value: str) -> None:
    try:
        captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601 UTC") from exc
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    if captured.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must be expressed in UTC")


def default_prep_scan_contract() -> CampaignScanContract:
    return CampaignScanContract(
        phases=tuple(SurveyPhase),
        maximum_edge_steps_per_direction=ACTIVATED_EDGE_STEPS_PER_DIRECTION,
        maximum_overlapping_viewports=ACTIVATED_OVERLAP_STEPS,
        maximum_auxiliary_inputs=0,
        overlap_evidence_required=True,
        maximum_transport_inputs=0,
        maximum_native_frames=0,
        maximum_sessions=0,
        explicit_activation_required=True,
        build_atlas=False,
        contract_kind=ContractKind.PREP,
    )


def default_activated_scan_contract() -> CampaignScanContract:
    return CampaignScanContract(
        phases=tuple(SurveyPhase),
        maximum_edge_steps_per_direction=ACTIVATED_EDGE_STEPS_PER_DIRECTION,
        maximum_overlapping_viewports=ACTIVATED_OVERLAP_STEPS,
        maximum_auxiliary_inputs=ACTIVATED_AUXILIARY_INPUTS,
        overlap_evidence_required=True,
        maximum_transport_inputs=ACTIVATED_TRANSPORT_INPUT_CEILING,
        maximum_native_frames=ACTIVATED_MAXIMUM_NATIVE_FRAMES,
        maximum_sessions=ACTIVATED_MAXIMUM_SESSIONS,
        explicit_activation_required=False,
        build_atlas=False,
        contract_kind=ContractKind.ACTIVATED,
    )


def dry_run_campaign_survey(
    contract: CampaignScanContract,
    *,
    observed_frames: Iterable[NativeFrameProvenance] = (),
) -> CollectorReport:
    """Exercise only the fail-closed prep collector boundary; never acquire evidence."""

    if contract.contract_kind is not ContractKind.PREP:
        raise ValueError("dry-run collector accepts only the prep contract")
    frames = tuple(observed_frames)
    for frame in frames:
        if not isinstance(frame, NativeFrameProvenance):
            return CollectorReport(
                disposition=CollectorDisposition.BLOCKED_FAIL_CLOSED,
                reason="invalid native frame provenance",
                transport_dispatched=False,
                transport_input_count=0,
                native_frames_acquired=0,
                evidence_artifacts=(),
                atlas_created=False,
            )
        try:
            NativeFrameProvenance(**asdict(frame))
        except (TypeError, ValueError):
            return CollectorReport(
                disposition=CollectorDisposition.BLOCKED_FAIL_CLOSED,
                reason="invalid native frame provenance",
                transport_dispatched=False,
                transport_input_count=0,
                native_frames_acquired=0,
                evidence_artifacts=(),
                atlas_created=False,
            )
    if frames:
        return CollectorReport(
            disposition=CollectorDisposition.BLOCKED_FAIL_CLOSED,
            reason="prep collector cannot accept or promote a native corpus",
            transport_dispatched=False,
            transport_input_count=0,
            native_frames_acquired=0,
            evidence_artifacts=(),
            atlas_created=False,
        )
    if contract.maximum_transport_inputs != 0 or contract.maximum_native_frames != 0:
        raise ValueError("dry-run collector requires zero input and acquisition budgets")
    return CollectorReport(
        disposition=CollectorDisposition.EVIDENCE_REQUIRED,
        reason="native Campaign survey evidence requires a later explicitly authorized task",
        transport_dispatched=False,
        transport_input_count=0,
        native_frames_acquired=0,
        evidence_artifacts=(),
        atlas_created=False,
    )


def classify_frame_candidate(
    *,
    provenance: Mapping[str, Any] | NativeFrameProvenance | None,
    mask_contract_id: str,
    capture_kind_hint: str | None = None,
    local_candidate: bool = False,
    bytes_empty: bool = False,
) -> FrameClassification:
    """Fail-closed native-frame gate used by session accounting and validators."""

    if local_candidate:
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=None,
            mask_contract_id=mask_contract_id,
            rejection_reason=FrameRejectionReason.LOCAL_CANDIDATE,
            notes="retained local Campaign frames are non-authorizing candidates only",
        )
    if bytes_empty:
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=None,
            mask_contract_id=mask_contract_id,
            rejection_reason=FrameRejectionReason.SYNTHETIC_OR_PLACEHOLDER,
            notes="empty or placeholder frames are rejected",
        )
    if provenance is None:
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=None,
            mask_contract_id=mask_contract_id,
            rejection_reason=FrameRejectionReason.SOURCE_IDENTITY_INVALID,
        )
    try:
        if isinstance(provenance, NativeFrameProvenance):
            identity = NativeFrameProvenance(**asdict(provenance))
        else:
            identity = NativeFrameProvenance(**dict(provenance))
    except (TypeError, ValueError) as exc:
        message = str(exc).casefold()
        if "800x1280" in message or "width" in message or "height" in message:
            reason = FrameRejectionReason.NON_NATIVE_DIMENSIONS
        elif "sha-256" in message or "digest" in message:
            reason = FrameRejectionReason.UNHASHED
        elif "profile" in message:
            reason = FrameRejectionReason.WRONG_PROFILE
        elif "package" in message:
            reason = FrameRejectionReason.WRONG_PACKAGE
        elif "ordinal" in message or "utc" in message or "monotonic" in message:
            reason = FrameRejectionReason.ORDINAL_OR_TIME_INVALID
        else:
            reason = FrameRejectionReason.SOURCE_IDENTITY_INVALID
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=None,
            mask_contract_id=mask_contract_id,
            rejection_reason=reason,
            notes=str(exc),
        )
    if capture_kind_hint == "synthetic":
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=identity,
            mask_contract_id=mask_contract_id,
            rejection_reason=FrameRejectionReason.SYNTHETIC_OR_PLACEHOLDER,
        )
    if mask_contract_id != MASK_CONTRACT_ID:
        return FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=identity,
            mask_contract_id=mask_contract_id,
            rejection_reason=FrameRejectionReason.WRONG_MASK,
        )
    return FrameClassification(
        disposition=FrameDisposition.ACCEPTED,
        provenance=identity,
        mask_contract_id=MASK_CONTRACT_ID,
    )


def validate_survey_session_report(report: SurveySessionReport) -> None:
    """Fail-closed structural validation for an activated survey session report."""

    if report.manifest.contract_kind is not ContractKind.ACTIVATED:
        raise ValueError("session report requires the activated manifest")
    if report.accounting.maximum_transport_inputs != ACTIVATED_TRANSPORT_INPUT_CEILING:
        raise ValueError("session accounting ceiling must be 272")
    if report.accounting.transport_inputs_used != len(report.journal):
        raise ValueError("journal length must equal transport inputs used")
    ordinals = [entry.input_ordinal for entry in report.journal]
    if ordinals != list(range(1, len(ordinals) + 1)):
        raise ValueError("journal input ordinals must be contiguous from 1")
    for entry in report.journal:
        NavigationJournalEntry(
            input_ordinal=entry.input_ordinal,
            phase=entry.phase,
            budget_category=entry.budget_category,
            evidence=entry.evidence,
            terminal_classification=entry.terminal_classification,
            identical_retry=entry.identical_retry,
            lifecycle=entry.lifecycle,
            prior_progress_proven=entry.prior_progress_proven,
            swipe_geometry=entry.swipe_geometry,
        )
    for frame in report.accepted_frames:
        if frame.disposition is not FrameDisposition.ACCEPTED:
            raise ValueError("accepted_frames contains a non-accepted classification")
    for frame in report.rejected_frames:
        if frame.disposition is not FrameDisposition.REJECTED:
            raise ValueError("rejected_frames contains a non-rejected classification")
    for residual in report.registration_residuals:
        if residual.authorizes_input:
            raise ValueError("registration residual must not authorize input")
    if report.cross_difficulty is not None and report.cross_difficulty.used_as_recenter:
        raise ValueError("difficulty switching cannot recenter")
    if report.disposition is CollectorDisposition.NATIVE_SURVEY_COMPLETE:
        if report.safe_terminal is None or not report.safe_terminal.recognized:
            raise ValueError("complete survey requires a recognized safe terminal")
        if report.loop_closure is None or not report.loop_closure.closed:
            raise ValueError("complete survey requires defensible closed loop-closure")
        if report.cross_difficulty is None:
            raise ValueError("complete survey requires cross-difficulty reporting")
        if any(not item.associated for item in report.overlaps):
            raise ValueError("complete survey requires policy-accepted overlap associations")
        kinds = {item.kind for item in report.landmarks}
        if LandmarkKind.CHAPTER not in kinds:
            raise ValueError("complete survey requires chapter landmark binding")
        if LandmarkKind.PRISON_TRIAL not in kinds and LandmarkKind.ULTIMATE_CHALLENGE not in kinds:
            raise ValueError("complete survey requires Prison Trial/Ultimate Challenge landmark")
        if len(report.edge_clamps) < 4:
            raise ValueError("complete survey requires four edge-clamp reports")
    if any(entry.lifecycle is InputLifecycle.UNRESOLVED for entry in report.journal):
        if report.disposition is CollectorDisposition.NATIVE_SURVEY_COMPLETE:
            raise ValueError("unresolved navigation inputs forbid native_survey_complete")
        if report.safe_terminal is not None and report.safe_terminal.recognized:
            raise ValueError("unresolved navigation cannot claim recognized safe terminal")


def build_empty_activated_session_report(
    *,
    session_id: str,
    created_at_utc: str,
) -> SurveySessionReport:
    """Create a zero-input activated session scaffold. Does not claim evidence."""

    manifest = SurveySessionManifest(
        schema_version=1,
        flow_id=FLOW_ID,
        session_id=session_id,
        contract_kind=ContractKind.ACTIVATED,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
        mask_contract_id=MASK_CONTRACT_ID,
        native_width=NATIVE_WIDTH,
        native_height=NATIVE_HEIGHT,
        maximum_transport_inputs=ACTIVATED_TRANSPORT_INPUT_CEILING,
        maximum_sessions=ACTIVATED_MAXIMUM_SESSIONS,
        session_index=1,
        created_at_utc=created_at_utc,
    )
    report = SurveySessionReport(
        manifest=manifest,
        accounting=InputBudgetAccounting(),
        accepted_frames=(),
        rejected_frames=(),
        journal=(),
        edge_clamps=(),
        overlaps=(),
        registration_residuals=(),
        coverage_gaps=(),
        loop_closure=None,
        cross_difficulty=None,
        landmarks=(),
        safe_terminal=None,
        disposition=CollectorDisposition.EVIDENCE_REQUIRED,
        reason="activated survey session is prepared; native corpus has not been acquired",
        transport_dispatched=False,
    )
    validate_survey_session_report(report)
    return report
