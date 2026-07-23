"""Map-agnostic visual seams for Campaign atlas survey measurement.

Registration is dependency-injected and measurement-only. No backend threshold,
acceptance policy, target binding, or input authority is supplied. Measurement
reports never authorize transport. HUD-safe pan gestures are derived only from
native 800x1280 geometry and the fixed Campaign HUD mask / map-search ROI.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Mapping, Protocol

import cv2
import numpy as np

from .campaign_atlas import (
    CAMPAIGN_PROFILE_ID,
    HudMaskContract,
    MASK_CONTRACT_ID,
    NativeFrameProvenance,
    Rect,
    RegistrationResidualReport,
)
from .campaign_auto_battle_vision import (
    CAMPAIGN_EXIT_ROI,
    MAP_SEARCH_ROI,
    TIER_ONE_ROI,
    TIER_TWO_ROI,
)

# Compile-time static ROIs from the Campaign recognizer seam. Survey taps must
# never treat these as current-frame measured geometry.
COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS: Mapping[str, tuple[int, int, int, int]] = {
    "campaign-tier-1": TIER_ONE_ROI,
    "campaign-tier-2": TIER_TWO_ROI,
    "campaign-exit-base": CAMPAIGN_EXIT_ROI,
    "campaign-base-request": (0, 1170, 132, 1280),
}

REGISTRATION_FAILURE_REASONS = frozenset(
    {
        "shape_mismatch",
        "insufficient_features",
        "insufficient_matches",
    }
)


CAMPAIGN_HUD_MASK = HudMaskContract(
    contract_id=MASK_CONTRACT_ID,
    profile_id=CAMPAIGN_PROFILE_ID,
    width=800,
    height=1280,
    excluded_rectangles=(
        Rect(0, 0, 800, 150),
        Rect(0, 150, 138, 760),
        Rect(560, 150, 800, 640),
        Rect(675, 640, 800, 1020),
        Rect(0, 1020, 800, 1280),
    ),
)

# Finger travel for one map pan inside the HUD-safe central corridor.
HUD_SAFE_PAN_HALF_TRAVEL_PX = 140
NO_PROGRESS_TRANSLATION_PX = 8.0
NO_PROGRESS_RESIDUAL_PX = 6.0


@dataclass(frozen=True)
class RegistrationMeasurement:
    model: str
    transform_candidate_to_reference: np.ndarray | None
    confidence: float
    residual_px: float
    inliers: int
    matches: int
    overlap_ratio: float
    reason: str
    translation_px: float = 0.0


@dataclass(frozen=True)
class CampaignRegistrationObservation:
    candidate_sha256: str
    reference_sha256: str
    measurement: RegistrationMeasurement
    accepted: bool = False
    authorizes_input: bool = False
    reason: str = "measurement_only_never_authorizes_input"


class RegistrationBackend(Protocol):
    def measure(
        self,
        candidate: np.ndarray,
        reference: np.ndarray,
        mask: np.ndarray,
    ) -> RegistrationMeasurement: ...


@dataclass(frozen=True)
class HudSafePanGesture:
    direction: str
    start: tuple[int, int]
    end: tuple[int, int]
    duration_ms: int = 350

    def as_swipe(self) -> tuple[int, int, int, int, int]:
        return (*self.start, *self.end, self.duration_ms)


def native_campaign_frame_guard(frame: np.ndarray) -> bool:
    return bool(frame is not None and frame.shape == (1280, 800, 3))


def frame_digest(frame: np.ndarray) -> str:
    if not native_campaign_frame_guard(frame):
        raise ValueError("digest requires a native 800x1280 BGR frame")
    encoded, payload = cv2.imencode(".png", frame)
    if not encoded:
        raise RuntimeError("cannot encode Campaign frame for hashing")
    return hashlib.sha256(payload.tobytes()).hexdigest()


def campaign_hud_mask(contract: HudMaskContract = CAMPAIGN_HUD_MASK) -> np.ndarray:
    if contract.profile_id != CAMPAIGN_PROFILE_ID or (contract.width, contract.height) != (800, 1280):
        raise ValueError("unsupported Campaign HUD mask contract")
    mask = np.full((1280, 800), 255, dtype=np.uint8)
    for rect in contract.excluded_rectangles:
        mask[rect.top : rect.bottom, rect.left : rect.right] = 0
    return mask


def hud_safe_central_region(
    *,
    map_search_roi: tuple[int, int, int, int] = MAP_SEARCH_ROI,
    mask_contract: HudMaskContract = CAMPAIGN_HUD_MASK,
) -> Rect:
    """Intersect checked-in map-search ROI with the unmasked Campaign scene."""

    left, top, right, bottom = map_search_roi
    mask = campaign_hud_mask(mask_contract)
    ys, xs = np.where(mask[top:bottom, left:right] > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise ValueError("HUD-safe central region is empty")
    return Rect(
        left + int(xs.min()),
        top + int(ys.min()),
        left + int(xs.max()) + 1,
        top + int(ys.max()) + 1,
    )


def _point_in_rect(point: tuple[int, int], rect: Rect) -> bool:
    x, y = point
    return rect.left <= x < rect.right and rect.top <= y < rect.bottom


def hud_safe_pan_gesture(direction: str) -> HudSafePanGesture:
    """Build a finger swipe that pans the map toward ``direction`` inside HUD-safe content."""

    region = hud_safe_central_region()
    cx = (region.left + region.right) // 2
    cy = (region.top + region.bottom) // 2
    travel = HUD_SAFE_PAN_HALF_TRAVEL_PX
    # Finger motion opposite the desired content edge (drag map toward that edge).
    if direction == "top":
        start, end = (cx, cy - 20), (cx, cy + travel)
    elif direction == "bottom":
        start, end = (cx, cy + 20), (cx, cy - travel)
    elif direction == "left":
        start, end = (cx - 20, cy), (cx + travel, cy)
    elif direction == "right":
        start, end = (cx + 20, cy), (cx - travel, cy)
    else:
        raise ValueError("pan direction must be top/right/bottom/left")
    if not _point_in_rect(start, region) or not _point_in_rect(end, region):
        raise ValueError("HUD-safe pan gesture escapes the central map region")
    mask = campaign_hud_mask()
    for x, y in (start, end):
        if mask[y, x] == 0:
            raise ValueError("HUD-safe pan gesture intersects excluded HUD")
    return HudSafePanGesture(direction=direction, start=start, end=end)


def clamp_detected(measurement: RegistrationMeasurement) -> bool:
    """True when a finite registration shows no meaningful map progress."""

    if not registration_measurement_is_finite(measurement):
        return False
    return (
        measurement.translation_px <= NO_PROGRESS_TRANSLATION_PX
        and measurement.residual_px <= NO_PROGRESS_RESIDUAL_PX
    )


def registration_measurement_is_finite(measurement: RegistrationMeasurement) -> bool:
    return (
        measurement.reason == "measured"
        and math.isfinite(float(measurement.residual_px))
        and math.isfinite(float(measurement.translation_px))
        and float(measurement.residual_px) != float("inf")
    )


def registration_progress_outcome(measurement: RegistrationMeasurement) -> str:
    """Classify post-pan registration: progress | no_progress | unresolved.

    Failed registration (inf residual / insufficient features) is never progress.
    Only a finite reviewed measurement may authorize same-geometry continuation.
    """

    if measurement.reason in REGISTRATION_FAILURE_REASONS:
        return "unresolved"
    if not registration_measurement_is_finite(measurement):
        return "unresolved"
    if clamp_detected(measurement):
        return "no_progress"
    return "progress"


def is_compile_time_static_survey_roi(
    identity: str, roi: tuple[int, int, int, int]
) -> bool:
    expected = COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS.get(identity)
    if expected is None:
        return False
    return tuple(int(v) for v in roi) == tuple(int(v) for v in expected)


def measured_content_annotation_roi(
    measurement: RegistrationMeasurement | None = None,
) -> tuple[int, int, int, int]:
    """Content ROI for edge/overlap annotations: HUD-safe measured region, not MAP_SEARCH_ROI."""

    del measurement  # reserved for future translation-aware crops; region is already measured
    region = hud_safe_central_region()
    return (region.left, region.top, region.right, region.bottom)


def chapter_roi_from_strong_spatial_evidence(
    *,
    number: int,
    targets: Mapping[str, tuple[int, int, int, int]],
    hits: Mapping[str, tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """Bind chapter only via recognizer target or multi-token OCR; reject digit-only."""

    target_id = f"campaign-chapter-{number}"
    if target_id in targets:
        return targets[target_id]
    needles = (
        f"chapter {number}",
        f"ch. {number}",
        f"ch.{number}",
        f"ch {number}",
    )
    for text, box in hits.items():
        folded = " ".join(str(text).casefold().split())
        if folded == str(number) or folded.isdigit():
            continue  # digit-only is weak / non-authorizing
        if not any(needle in folded for needle in needles):
            continue
        tokens = [tok for tok in folded.replace(".", " ").split() if tok]
        if len(tokens) >= 2:
            return box
    return None


def prison_trial_roi_from_strong_spatial_evidence(
    hits: Mapping[str, tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """Require spatially tied multi-token Prison+Trial evidence; reject single-token binds."""

    for text, box in hits.items():
        folded = " ".join(str(text).casefold().split())
        if "prison" in folded and "trial" in folded:
            tokens = [tok for tok in folded.replace("-", " ").split() if tok]
            if len(tokens) >= 2:
                return box
    prison_boxes = [
        box
        for text, box in hits.items()
        if "prison" in str(text).casefold() and "trial" not in str(text).casefold()
    ]
    trial_boxes = [
        box
        for text, box in hits.items()
        if "trial" in str(text).casefold() and "prison" not in str(text).casefold()
    ]
    if not prison_boxes or not trial_boxes:
        return None
    # Spatially associate nearest prison/trial pair within a small gap.
    best: tuple[int, int, int, int] | None = None
    best_gap: int | None = None
    for left in prison_boxes:
        for right in trial_boxes:
            gap = abs(((left[0] + left[2]) // 2) - ((right[0] + right[2]) // 2)) + abs(
                ((left[1] + left[3]) // 2) - ((right[1] + right[3]) // 2)
            )
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = (
                    min(left[0], right[0]),
                    min(left[1], right[1]),
                    max(left[2], right[2]),
                    max(left[3], right[3]),
                )
    if best is None or best_gap is None or best_gap > 220:
        return None
    return best


class OrbTranslationBackend:
    """Measurement-only ORB/translation backend. Never authorizes input."""

    def measure(
        self,
        candidate: np.ndarray,
        reference: np.ndarray,
        mask: np.ndarray,
    ) -> RegistrationMeasurement:
        if candidate.shape != reference.shape or mask.shape != candidate.shape[:2]:
            return RegistrationMeasurement(
                "none", None, 0.0, float("inf"), 0, 0, 0.0, "shape_mismatch", 0.0
            )
        orb = cv2.ORB_create(1200)
        kp1, des1 = orb.detectAndCompute(reference, mask)
        kp2, des2 = orb.detectAndCompute(candidate, mask)
        if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
            return RegistrationMeasurement(
                "none", None, 0.0, float("inf"), 0, 0, 0.0, "insufficient_features", 0.0
            )
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(des1, des2)
        if len(matches) < 8:
            return RegistrationMeasurement(
                "none", None, 0.0, float("inf"), 0, len(matches), 0.0, "insufficient_matches", 0.0
            )
        matches = sorted(matches, key=lambda item: item.distance)[:200]
        src = np.float32([kp1[item.queryIdx].pt for item in matches])
        dst = np.float32([kp2[item.trainIdx].pt for item in matches])
        delta = dst - src
        tx, ty = float(np.median(delta[:, 0])), float(np.median(delta[:, 1]))
        translation = float(np.hypot(tx, ty))
        residual = float(np.median(np.linalg.norm(delta - np.array([tx, ty]), axis=1)))
        matrix = np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]], dtype=np.float64)
        overlap = max(0.0, 1.0 - translation / 400.0)
        return RegistrationMeasurement(
            model="translation",
            transform_candidate_to_reference=matrix,
            confidence=min(1.0, len(matches) / 80.0),
            residual_px=residual,
            inliers=len(matches),
            matches=len(matches),
            overlap_ratio=overlap,
            reason="measured",
            translation_px=translation,
        )


def measure_campaign_frame_pair(
    candidate: np.ndarray,
    reference: np.ndarray,
    *,
    candidate_provenance: NativeFrameProvenance,
    reference_provenance: NativeFrameProvenance,
    backend: RegistrationBackend,
    mask_contract: HudMaskContract = CAMPAIGN_HUD_MASK,
) -> CampaignRegistrationObservation:
    if not native_campaign_frame_guard(candidate) or not native_campaign_frame_guard(reference):
        raise ValueError("registration requires native 800x1280 BGR frames")
    if candidate_provenance.semantic_sha256 != frame_digest(candidate):
        raise ValueError("candidate provenance does not match the current frame")
    if reference_provenance.semantic_sha256 != frame_digest(reference):
        raise ValueError("reference provenance does not match the current frame")
    if candidate_provenance.profile_id != reference_provenance.profile_id:
        raise ValueError("registration frames must use the same runtime profile")
    measurement = backend.measure(candidate, reference, campaign_hud_mask(mask_contract))
    return CampaignRegistrationObservation(
        candidate_sha256=candidate_provenance.semantic_sha256,
        reference_sha256=reference_provenance.semantic_sha256,
        measurement=measurement,
    )


def registration_residual_report(
    observation: CampaignRegistrationObservation,
) -> RegistrationResidualReport:
    """Convert a measurement-only observation into a fail-closed residual report."""

    if observation.accepted or observation.authorizes_input:
        raise ValueError("registration observation must remain measurement-only")
    return RegistrationResidualReport(
        candidate_sha256=observation.candidate_sha256,
        reference_sha256=observation.reference_sha256,
        residual_px=float(observation.measurement.residual_px),
        inliers=int(observation.measurement.inliers),
        matches=int(observation.measurement.matches),
        overlap_ratio=float(observation.measurement.overlap_ratio),
        authorizes_input=False,
    )


SURVEY_FORBIDDEN_TARGET_SUBSTRINGS = (
    "challenge",
    "auto",
    "refill",
    "flee",
    "buy",
    "sweep",
    "blitz",
    "complete",
)


def survey_target_is_consequential(identity: str) -> bool:
    folded = identity.casefold()
    if folded in {
        "campaign-exit-base",
        "campaign-base-request",
        "campaign-tier-1",
        "campaign-tier-2",
    }:
        return False
    if folded.startswith("campaign-chapter-"):
        return False
    return any(token in folded for token in SURVEY_FORBIDDEN_TARGET_SUBSTRINGS)


def require_measured_nonstatic_survey_target(
    recognition: object, identity: str
) -> tuple[int, int, int, int]:
    """Fail closed unless identity is bound with current-frame non-static geometry."""

    if survey_target_is_consequential(identity):
        raise RuntimeError(f"consequential target prohibited for survey: {identity}")
    targets = dict(getattr(recognition, "targets"))
    if identity not in targets:
        raise RuntimeError(
            f"target {identity!r} not positively bound in current immediate-before recognition"
        )
    roi = tuple(int(v) for v in targets[identity])
    if len(roi) != 4:
        raise RuntimeError(f"target {identity!r} ROI must be a 4-tuple")
    if is_compile_time_static_survey_roi(identity, roi):  # type: ignore[arg-type]
        raise RuntimeError(
            "evidence_required: "
            f"{identity} recognizer box is a compile-time static ROI; "
            "current-frame measured template/OCR-associated geometry is required before tap"
        )
    return roi  # type: ignore[return-value]
