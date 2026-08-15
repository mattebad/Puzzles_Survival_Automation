"""Freshness and transient-to-settled perception policy.

This module stores metadata only.  It neither reads retained evidence nor performs capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable


class TemporalError(ValueError):
    pass


class RoiMaskKind(str, Enum):
    DYNAMIC = "dynamic"
    STABLE = "stable"


@dataclass(frozen=True)
class CaptureProvenance:
    capture_id: str
    runtime_session_id: str
    capture_ordinal: int
    captured_monotonic: float
    profile_id: str
    width: int
    height: int
    transport_sha256: str
    semantic_sha256: str

    def __post_init__(self) -> None:
        if not self.capture_id.strip() or not self.runtime_session_id.strip() or not self.profile_id.strip():
            raise TemporalError("capture provenance requires identity")
        if self.capture_ordinal < 1 or not math.isfinite(self.captured_monotonic):
            raise TemporalError("capture provenance ordinal/time is invalid")
        if self.width <= 0 or self.height <= 0:
            raise TemporalError("capture geometry must be positive")
        for digest in (self.transport_sha256, self.semantic_sha256):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise TemporalError("capture digests must be lowercase SHA-256 values")


@dataclass(frozen=True)
class RoiMask:
    name: str
    kind: RoiMaskKind
    roi: tuple[int, int, int, int]
    reason: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.reason.strip():
            raise TemporalError("ROI masks require identity and reason")
        x0, y0, x1, y1 = self.roi
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise TemporalError("ROI mask bounds are invalid")


@dataclass(frozen=True)
class CandidateEvidence:
    identity: str
    confidence: float
    runner_up_confidence: float = 0.0
    negative_evidence: tuple[str, ...] = ()
    source: str = ""

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise TemporalError("candidate identity is required")
        for value in (self.confidence, self.runner_up_confidence):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise TemporalError("candidate confidence must be in [0, 1]")
        if self.runner_up_confidence > self.confidence:
            raise TemporalError("runner-up confidence cannot exceed candidate confidence")

    @property
    def margin(self) -> float:
        return self.confidence - self.runner_up_confidence


@dataclass(frozen=True)
class TemporalPolicy:
    minimum_confidence: float = 0.8
    minimum_margin: float = 0.1
    consecutive_agreement: int = 2
    settle_polls: int = 2
    max_age_seconds: float = 30.0
    disqualifying_negative_evidence: frozenset[str] = frozenset(
        {"ambiguous", "unknown", "manual_only", "overlay", "loading"}
    )

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise TemporalError("minimum confidence must be in [0, 1]")
        if self.minimum_margin < 0 or self.consecutive_agreement < 1 or self.settle_polls < 1:
            raise TemporalError("temporal thresholds must be positive")
        if self.max_age_seconds <= 0 or not math.isfinite(self.max_age_seconds):
            raise TemporalError("maximum age must be finite and positive")


@dataclass(frozen=True)
class TemporalObservation:
    provenance: CaptureProvenance
    candidate: CandidateEvidence | None
    transient: bool = True
    stable_roi_masks: tuple[RoiMask, ...] = ()
    dynamic_roi_masks: tuple[RoiMask, ...] = ()

    def __post_init__(self) -> None:
        for mask in self.stable_roi_masks:
            if mask.kind is not RoiMaskKind.STABLE:
                raise TemporalError("stable ROI collection contains a dynamic mask")
        for mask in self.dynamic_roi_masks:
            if mask.kind is not RoiMaskKind.DYNAMIC:
                raise TemporalError("dynamic ROI collection contains a stable mask")


@dataclass(frozen=True)
class TemporalDecision:
    settled: bool
    candidate: CandidateEvidence | None
    reason_code: str
    agreement_count: int


class TemporalPerception:
    """Consecutive-agreement gate that invalidates pre-input authority."""

    def __init__(self, policy: TemporalPolicy | None = None) -> None:
        self.policy = policy or TemporalPolicy()
        self._observations: list[TemporalObservation] = []
        self._invalidated = False
        self._last_provenance: CaptureProvenance | None = None
        self._seen_capture_ids: set[str] = set()
        self._seen_digests: set[tuple[str, str]] = set()
        self._last_now_monotonic: float | None = None

    @property
    def invalidated_after_input(self) -> bool:
        return self._invalidated

    def observe(self, observation: TemporalObservation, *, now_monotonic: float) -> TemporalDecision:
        if self._invalidated:
            return TemporalDecision(False, None, "INVALIDATED_AFTER_INPUT", 0)
        age = now_monotonic - observation.provenance.captured_monotonic
        if age < 0:
            self._observations.clear()
            return TemporalDecision(False, None, "FUTURE_CAPTURE", 0)
        if age > self.policy.max_age_seconds:
            self._observations.clear()
            return TemporalDecision(False, None, "STALE_CAPTURE", 0)
        provenance = observation.provenance
        if self._last_provenance is not None:
            if provenance.runtime_session_id != self._last_provenance.runtime_session_id:
                self._observations.clear()
                self._last_provenance = None
                return TemporalDecision(False, None, "CROSS_SESSION", 0)
            if provenance.profile_id != self._last_provenance.profile_id:
                self._observations.clear()
                return TemporalDecision(False, None, "PROFILE_CHANGED", 0)
            if provenance.capture_ordinal <= self._last_provenance.capture_ordinal:
                self._observations.clear()
                return TemporalDecision(False, None, "OUT_OF_ORDER_CAPTURE", 0)
        digest_pair = (provenance.transport_sha256, provenance.semantic_sha256)
        if provenance.capture_id in self._seen_capture_ids or digest_pair in self._seen_digests:
            self._observations.clear()
            return TemporalDecision(False, None, "DUPLICATE_CAPTURE", 0)
        self._seen_capture_ids.add(provenance.capture_id)
        self._seen_digests.add(digest_pair)
        self._last_provenance = provenance
        self._last_now_monotonic = now_monotonic
        if observation.candidate is None:
            self._observations.clear()
            return TemporalDecision(False, None, "NO_CANDIDATE", 0)
        candidate = observation.candidate
        if observation.transient:
            self._observations.clear()
            return TemporalDecision(False, candidate, "TRANSIENT_OBSERVATION", 0)
        if any(
            evidence.casefold() in self.policy.disqualifying_negative_evidence
            for evidence in candidate.negative_evidence
        ):
            self._observations.clear()
            return TemporalDecision(False, candidate, "NEGATIVE_EVIDENCE", 0)
        if candidate.confidence < self.policy.minimum_confidence:
            self._observations.clear()
            return TemporalDecision(False, candidate, "LOW_CONFIDENCE", 0)
        if candidate.margin < self.policy.minimum_margin:
            self._observations.clear()
            return TemporalDecision(False, candidate, "RUNNER_UP_TOO_CLOSE", 0)
        self._observations.append(observation)
        agreement = 0
        for prior in reversed(self._observations):
            if prior.candidate is None or prior.candidate.identity != candidate.identity:
                break
            agreement += 1
        required = max(self.policy.consecutive_agreement, self.policy.settle_polls)
        if agreement < required:
            return TemporalDecision(False, candidate, "TRANSIENT_WAIT", agreement)
        return TemporalDecision(True, candidate, "SETTLED", agreement)

    def invalidate_after_input(self) -> None:
        self._invalidated = True
        self._observations.clear()

    def reset(self) -> None:
        self._invalidated = False
        self._observations.clear()
        self._last_provenance = None
        self._seen_capture_ids.clear()
        self._seen_digests.clear()
        self._last_now_monotonic = None

    def settled_candidate(self, *, now_monotonic: float) -> CandidateEvidence | None:
        if not math.isfinite(now_monotonic):
            raise TemporalError("settled-candidate time must be finite")
        if self._invalidated or len(self._observations) < self.policy.consecutive_agreement:
            return None
        required = max(self.policy.consecutive_agreement, self.policy.settle_polls)
        if len(self._observations) < required:
            return None
        if any(
            now_monotonic - item.provenance.captured_monotonic < 0
            or now_monotonic - item.provenance.captured_monotonic
            > self.policy.max_age_seconds
            or item.transient
            or item.candidate is None
            or item.candidate.confidence < self.policy.minimum_confidence
            or item.candidate.margin < self.policy.minimum_margin
            or any(
                evidence.casefold() in self.policy.disqualifying_negative_evidence
                for evidence in item.candidate.negative_evidence
            )
            for item in self._observations[-required:]
        ):
            return None
        last = self._observations[-1].candidate
        if last is None:
            return None
        matching = list(
            observation.candidate
            for observation in self._observations[-required:]
            if observation.candidate is not None and observation.candidate.identity == last.identity
        )
        return last if len(matching) == required else None

    def extend(self, observations: Iterable[TemporalObservation], *, now_monotonic: float) -> TemporalDecision:
        decision = TemporalDecision(False, None, "NO_OBSERVATIONS", 0)
        for observation in observations:
            decision = self.observe(observation, now_monotonic=now_monotonic)
        return decision

