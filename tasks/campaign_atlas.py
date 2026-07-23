"""Evidence-gated contracts for a future native Campaign map survey.

This module deliberately contains no atlas geometry, semantic destinations,
recognition thresholds, runtime transport, localization, or navigation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import math
import re
from typing import Iterable


CAMPAIGN_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
CAMPAIGN_PLATFORM = "BlueStacks 5 / Android"
CAMPAIGN_PACKAGE = "com.global.ztmslg"
NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True)
class CampaignScanContract:
    """Abstract survey topology with no gestures, coordinates, or atlas geometry."""

    phases: tuple[SurveyPhase, ...]
    maximum_edge_steps_per_direction: int
    maximum_overlapping_viewports: int
    overlap_evidence_required: bool
    maximum_transport_inputs: int
    maximum_native_frames: int
    explicit_activation_required: bool
    build_atlas: bool

    def __post_init__(self) -> None:
        required = tuple(SurveyPhase)
        if self.phases != required:
            raise ValueError("scan phases must preserve the bounded reviewed topology")
        if type(self.maximum_edge_steps_per_direction) is not int or not (
            1 <= self.maximum_edge_steps_per_direction <= 32
        ):
            raise ValueError("edge survey cap must be between 1 and 32 steps per direction")
        if type(self.maximum_overlapping_viewports) is not int or not (
            1 <= self.maximum_overlapping_viewports <= 128
        ):
            raise ValueError("overlap survey cap must be between 1 and 128 viewports")
        if not self.overlap_evidence_required:
            raise ValueError("overlapping viewport evidence must be required")
        if self.maximum_transport_inputs != 0 or self.maximum_native_frames != 0:
            raise ValueError("prep contract must retain zero input and zero acquisition budgets")
        if not self.explicit_activation_required:
            raise ValueError("native survey must require separate explicit activation")
        if self.build_atlas:
            raise ValueError("atlas construction is prohibited before native survey evidence")


class CollectorDisposition(str, Enum):
    EVIDENCE_REQUIRED = "evidence_required"
    BLOCKED_FAIL_CLOSED = "blocked_fail_closed"


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


def default_prep_scan_contract() -> CampaignScanContract:
    return CampaignScanContract(
        phases=tuple(SurveyPhase),
        maximum_edge_steps_per_direction=32,
        maximum_overlapping_viewports=128,
        overlap_evidence_required=True,
        maximum_transport_inputs=0,
        maximum_native_frames=0,
        explicit_activation_required=True,
        build_atlas=False,
    )


def dry_run_campaign_survey(
    contract: CampaignScanContract,
    *,
    observed_frames: Iterable[NativeFrameProvenance] = (),
) -> CollectorReport:
    """Exercise only the fail-closed collector boundary; never acquire evidence."""

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
