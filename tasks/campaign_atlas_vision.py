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
from pathlib import Path
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
    ASSET_ROOT,
    CAMPAIGN_EXIT_ROI,
    MAP_SEARCH_ROI,
    TIER_ONE_ROI,
    TIER_TWO_ROI,
    _selected_tier,
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
HUD_SAFE_PAN_HALF_TRAVEL_STRONG_PX = 200
NO_PROGRESS_TRANSLATION_PX = 8.0
NO_PROGRESS_RESIDUAL_PX = 6.0
MIN_ASSOCIATION_MATCHES = 24
MIN_ASSOCIATION_CONFIDENCE = 0.30
MAX_ASSOCIATION_RESIDUAL_PX = 12.0
MIN_ASSOCIATION_OVERLAP_RATIO = 0.25
# Home-parity: reject near-duplicate viewports whose centers collapse together.
MIN_VIEWPORT_CENTER_SEPARATION_PX = 32.0
CURRENT_TARGET_TEMPLATE_THRESHOLD = 0.55
TIER_CONTROL_SEARCH_ROI = (320, 35, 710, 190)
CAMPAIGN_EXIT_SEARCH_ROI = (560, 780, 800, 1140)
CAMPAIGN_EXIT_TEMPLATE_THRESHOLD = 0.72
# Highlighted (legacy) plus current-frame unhighlighted appearance.
CAMPAIGN_EXIT_ASSETS: tuple[str, ...] = (
    "campaign_exit_unhighlighted.png",
    "campaign_exit.png",
)
TIER_SELECTION_ASSETS: Mapping[str, Mapping[str, str]] = {
    "campaign-tier-1": {
        "unselected": "tier1_unselected.png",
        "selected": "tier1_selected.png",
    },
    "campaign-tier-2": {
        "unselected": "tier2_unselected.png",
        "selected": "tier2_selected.png",
    },
}
# Pre-tap selection required before authorizing the opposite unselected button.
TIER_TAP_REQUIRED_SELECTED: Mapping[str, int] = {
    "campaign-tier-1": 2,
    "campaign-tier-2": 1,
}


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


def hud_safe_pan_gesture(
    direction: str,
    *,
    travel_px: int | None = None,
) -> HudSafePanGesture:
    """Build a finger swipe that pans the map toward ``direction`` inside HUD-safe content."""

    region = hud_safe_central_region()
    cx = (region.left + region.right) // 2
    cy = (region.top + region.bottom) // 2
    travel = HUD_SAFE_PAN_HALF_TRAVEL_PX if travel_px is None else int(travel_px)
    if travel <= 0:
        raise ValueError("HUD-safe pan travel must be positive")
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


def overlap_association_accepted(measurement: RegistrationMeasurement) -> bool:
    """Conservative measured association used to retain overlapping viewports."""

    return bool(
        registration_measurement_is_finite(measurement)
        and measurement.matches >= MIN_ASSOCIATION_MATCHES
        and measurement.inliers >= MIN_ASSOCIATION_MATCHES
        and measurement.confidence >= MIN_ASSOCIATION_CONFIDENCE
        and measurement.residual_px <= MAX_ASSOCIATION_RESIDUAL_PX
        and measurement.overlap_ratio >= MIN_ASSOCIATION_OVERLAP_RATIO
    )


def loop_closure_accepted(measurement: RegistrationMeasurement) -> bool:
    """Require a strong finite near-identity registration for loop closure."""

    return bool(
        overlap_association_accepted(measurement)
        and measurement.translation_px <= NO_PROGRESS_TRANSLATION_PX
        and measurement.residual_px <= NO_PROGRESS_RESIDUAL_PX
    )


def _locate_template(
    frame: np.ndarray,
    *,
    asset_name: str,
    search_roi: tuple[int, int, int, int],
    threshold: float = CURRENT_TARGET_TEMPLATE_THRESHOLD,
) -> tuple[tuple[int, int, int, int], float]:
    if frame.shape != (1280, 800, 3):
        raise RuntimeError("current-frame target binding requires native 800x1280 BGR")
    template_path = Path(ASSET_ROOT) / asset_name
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise RuntimeError(f"missing project-owned target template: {asset_name}")
    x0, y0, x1, y1 = search_roi
    search = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        raise RuntimeError(f"target search region is smaller than template: {asset_name}")
    response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(response)
    if not math.isfinite(score) or score < threshold:
        raise RuntimeError(
            f"current-frame template target {asset_name} not bound: score={score:.3f}"
        )
    left, top = x0 + point[0], y0 + point[1]
    height, width = template.shape
    return (left, top, left + width, top + height), float(score)


def require_tier_map_selection_state(
    frame: np.ndarray, *, selected_tier: int
) -> tuple[int, dict[str, float]]:
    """Fail closed unless gold-ratio selection matches the required Story difficulty."""

    observed, ratios = _selected_tier(frame)
    if observed != int(selected_tier):
        raise RuntimeError(
            "tier selection state mismatch: "
            f"required_selected={selected_tier} observed={observed} ratios={ratios}"
        )
    return int(observed), ratios


def measured_survey_target(
    frame: np.ndarray, identity: str
) -> tuple[tuple[int, int, int, int], float]:
    """Bind a survey control from the current native frame, never a retained coordinate."""

    if identity in TIER_SELECTION_ASSETS:
        assets = TIER_SELECTION_ASSETS[identity]
        required_selected = TIER_TAP_REQUIRED_SELECTED[identity]
        require_tier_map_selection_state(frame, selected_tier=required_selected)
        unselected_roi, unselected_score = _locate_template(
            frame,
            asset_name=assets["unselected"],
            search_roi=TIER_CONTROL_SEARCH_ROI,
            threshold=CURRENT_TARGET_TEMPLATE_THRESHOLD,
        )
        selected_roi, selected_score = _locate_template(
            frame,
            asset_name=assets["selected"],
            search_roi=TIER_CONTROL_SEARCH_ROI,
            threshold=-1.0,
        )
        if unselected_score <= selected_score:
            raise RuntimeError(
                "tier button selection-aware bind rejected: "
                f"{identity} unselected_score={unselected_score:.3f} "
                f"selected_score={selected_score:.3f} "
                f"unselected_roi={unselected_roi} selected_roi={selected_roi}"
            )
        if is_compile_time_static_survey_roi(identity, unselected_roi):
            raise RuntimeError(
                "evidence_required: measured tier ROI matched compile-time static ROI; "
                "fresh dynamic geometry is required"
            )
        # Geometry sanity: tier1 left of tier2 centerline within the search band.
        cx = (unselected_roi[0] + unselected_roi[2]) // 2
        search_left, _search_top, search_right, _search_bottom = TIER_CONTROL_SEARCH_ROI
        mid = (search_left + search_right) // 2
        if identity == "campaign-tier-1" and cx >= mid:
            raise RuntimeError("campaign-tier-1 bound right of expected control band")
        if identity == "campaign-tier-2" and cx <= mid:
            raise RuntimeError("campaign-tier-2 bound left of expected control band")
        return unselected_roi, float(unselected_score)
    if identity == "campaign-exit-base":
        best_roi: tuple[int, int, int, int] | None = None
        best_score = float("-inf")
        best_asset = ""
        failures: list[str] = []
        for asset_name in CAMPAIGN_EXIT_ASSETS:
            try:
                roi, score = _locate_template(
                    frame,
                    asset_name=asset_name,
                    search_roi=CAMPAIGN_EXIT_SEARCH_ROI,
                    threshold=CAMPAIGN_EXIT_TEMPLATE_THRESHOLD,
                )
            except RuntimeError as exc:
                failures.append(f"{asset_name}:{exc}")
                continue
            if score > best_score:
                best_roi = roi
                best_score = float(score)
                best_asset = asset_name
        if best_roi is None:
            raise RuntimeError(
                "current-frame campaign-exit-base not bound by highlighted or "
                f"unhighlighted template; failures={failures}"
            )
        left, top, right, bottom = best_roi
        search_left, search_top, search_right, search_bottom = CAMPAIGN_EXIT_SEARCH_ROI
        if not (
            search_left <= left < right <= search_right
            and search_top <= top < bottom <= search_bottom
        ):
            raise RuntimeError(
                "campaign-exit-base measured ROI escapes exit search geometry: "
                f"roi={best_roi} asset={best_asset}"
            )
        # Authority is template measurement on the fresh frame. Compile-time
        # CAMPAIGN_EXIT_ROI is crop metadata only and never a live fallback.
        return best_roi, float(best_score)
    raise RuntimeError(f"no current-frame measured selector for survey target: {identity}")


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
    """Measurement-only ORB/translation backend. Never authorizes input.

    Transform convention matches Home: ``transform_candidate_to_reference`` maps
    candidate pixel coordinates into the reference frame (destination - source
    where source is candidate and destination is reference).
    """

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
        kp_candidate, des_candidate = orb.detectAndCompute(candidate, mask)
        kp_reference, des_reference = orb.detectAndCompute(reference, mask)
        if (
            des_candidate is None
            or des_reference is None
            or len(kp_candidate) < 8
            or len(kp_reference) < 8
        ):
            return RegistrationMeasurement(
                "none", None, 0.0, float("inf"), 0, 0, 0.0, "insufficient_features", 0.0
            )
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(des_candidate, des_reference)
        if len(matches) < 8:
            return RegistrationMeasurement(
                "none", None, 0.0, float("inf"), 0, len(matches), 0.0, "insufficient_matches", 0.0
            )
        matches = sorted(matches, key=lambda item: item.distance)[:200]
        # Home convention: source=candidate, destination=reference.
        source = np.float32([kp_candidate[item.queryIdx].pt for item in matches])
        destination = np.float32([kp_reference[item.trainIdx].pt for item in matches])
        delta = destination - source
        tx, ty = float(np.median(delta[:, 0])), float(np.median(delta[:, 1]))
        translation = float(np.hypot(tx, ty))
        residual = float(np.median(np.linalg.norm(delta - np.array([tx, ty]), axis=1)))
        matrix = np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]], dtype=np.float64)
        corners = np.float32([[0, 0], [800, 0], [800, 1280], [0, 1280]])
        projected = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        x0, y0 = np.maximum(projected.min(axis=0), (0.0, 0.0))
        x1, y1 = np.minimum(projected.max(axis=0), (800.0, 1280.0))
        overlap = float(max(0.0, x1 - x0) * max(0.0, y1 - y0) / float(800 * 1280))
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


# ---------------------------------------------------------------------------
# Atlas build / localize / current-frame destination bind (offline)
# ---------------------------------------------------------------------------

from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path

from .campaign_atlas import (
    ACCEPTED_LANDMARK_SESSION_ID,
    ACCEPTED_SURVEY_ROOT,
    ACCEPTED_TERMINAL_SESSION_ID,
    ACCEPTED_TRAVERSAL_SESSION_ID,
    CAMPAIGN_PACKAGE,
    CAMPAIGN_PLATFORM,
    CampaignAmbiguityState,
    CampaignAtlas,
    CampaignAtlasLandmark,
    CampaignAtlasViewport,
    CampaignDestinationBinding,
    CampaignDestinationKind,
    CampaignLocalizationResult,
    DEFAULT_ATLAS_ARTIFACT_ROOT,
    DEFAULT_ATLAS_ID,
    INTEGRATION_FLOW_ID,
    LandmarkKind,
    NATIVE_HEIGHT,
    NATIVE_WIDTH,
    Matrix3,
    campaign_atlas_to_dict,
    project_landmark_search_roi,
    resolve_campaign_consumer_destination,
    save_campaign_atlas,
)


def _transport_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_bgr(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None or not native_campaign_frame_guard(frame):
        raise ValueError(f"native Campaign frame required: {path}")
    return frame


def _compose_translation(left: Matrix3, right: Matrix3) -> Matrix3:
    lx, ly = float(left[0][2]), float(left[1][2])
    rx, ry = float(right[0][2]), float(right[1][2])
    return (
        (1.0, 0.0, lx + rx),
        (0.0, 1.0, ly + ry),
        (0.0, 0.0, 1.0),
    )


def _invert_translation(matrix: Matrix3) -> Matrix3:
    return (
        (1.0, 0.0, -float(matrix[0][2])),
        (0.0, 1.0, -float(matrix[1][2])),
        (0.0, 0.0, 1.0),
    )


def _matrix_from_ndarray(matrix: np.ndarray) -> Matrix3:
    return tuple(tuple(float(cell) for cell in row) for row in matrix)  # type: ignore[return-value]


def index_survey_frames_by_semantic_sha(
    survey_root: Path = ACCEPTED_SURVEY_ROOT,
) -> dict[str, Path]:
    """Map semantic frame digests to retained native PNGs under accepted survey sessions."""

    indexed: dict[str, Path] = {}
    if not survey_root.is_dir():
        return indexed
    for session_dir in sorted(survey_root.iterdir()):
        frames_dir = session_dir / "runtime" / "frames"
        if not frames_dir.is_dir():
            continue
        for path in sorted(frames_dir.glob("*.png")):
            try:
                frame = _load_bgr(path)
            except ValueError:
                continue
            digest = frame_digest(frame)
            indexed.setdefault(digest, path)
            transport = _transport_sha256(path)
            indexed.setdefault(transport, path)
    return indexed


def _provenance_for_path(path: Path, *, ordinal: int, semantic: str, transport: str) -> NativeFrameProvenance:
    session_id = path.parents[2].name if len(path.parents) >= 3 else path.parent.name
    return NativeFrameProvenance(
        source_id=str(path).replace("\\", "/"),
        capture_kind="fixture",
        runtime_session_id=f"campaign-atlas-build-{session_id}",
        capture_ordinal=ordinal,
        capture_completed_monotonic=float(ordinal),
        transport_sha256=transport,
        semantic_sha256=semantic,
        captured_at_utc="2026-07-24T00:00:00Z",
        width=NATIVE_WIDTH,
        height=NATIVE_HEIGHT,
    )


def _try_register_viewport(
    *,
    candidate_path: Path,
    candidate_frame: np.ndarray,
    candidate_semantic: str,
    reference_path: Path,
    reference_frame: np.ndarray,
    reference_semantic: str,
    reference_transform: Matrix3,
    backend: OrbTranslationBackend,
    ordinal: int,
) -> tuple[Matrix3, object] | None:
    observation = measure_campaign_frame_pair(
        candidate_frame,
        reference_frame,
        candidate_provenance=_provenance_for_path(
            candidate_path,
            ordinal=ordinal,
            semantic=candidate_semantic,
            transport=_transport_sha256(candidate_path),
        ),
        reference_provenance=_provenance_for_path(
            reference_path,
            ordinal=max(1, ordinal - 1),
            semantic=reference_semantic,
            transport=_transport_sha256(reference_path),
        ),
        backend=backend,
    )
    measurement = observation.measurement
    if (
        measurement.transform_candidate_to_reference is None
        or measurement.matches < MIN_ASSOCIATION_MATCHES
        or measurement.confidence < MIN_ASSOCIATION_CONFIDENCE
        or measurement.residual_px > MAX_ASSOCIATION_RESIDUAL_PX
        or measurement.overlap_ratio < MIN_ASSOCIATION_OVERLAP_RATIO
    ):
        return None
    relative = _matrix_from_ndarray(measurement.transform_candidate_to_reference)
    absolute = _compose_translation(reference_transform, relative)
    return absolute, measurement


def build_campaign_atlas_from_accepted_survey(
    *,
    survey_root: Path = ACCEPTED_SURVEY_ROOT,
    output_root: Path = DEFAULT_ATLAS_ARTIFACT_ROOT,
    atlas_id: str = DEFAULT_ATLAS_ID,
    max_viewports: int = 96,
) -> CampaignAtlas:
    """Build a hash-bound Campaign atlas from the accepted native survey (offline).

    Primary geometry comes from chaining sequential retained traversal ``*-post.png``
    frames (Home-style), not from disconnected terminal-report overlap pairs.
    Landmark-session frames are registered onto that chain for chapter/UC ROIs.
    """

    survey_root = Path(survey_root)
    terminal_report_path = (
        survey_root / ACCEPTED_TERMINAL_SESSION_ID / "survey-session-report.json"
    )
    if not terminal_report_path.is_file():
        raise FileNotFoundError(
            f"accepted terminal survey report missing: {terminal_report_path}"
        )
    report = json.loads(terminal_report_path.read_text(encoding="utf-8"))
    if report.get("disposition") != "native_survey_complete":
        raise RuntimeError("accepted survey report is not native_survey_complete")
    if bool(report.get("cross_difficulty", {}).get("used_as_recenter", False)):
        raise RuntimeError("survey used difficulty switching as recentering")

    traversal_frames = survey_root / ACCEPTED_TRAVERSAL_SESSION_ID / "runtime" / "frames"
    if not traversal_frames.is_dir():
        raise FileNotFoundError(f"accepted traversal frames missing: {traversal_frames}")

    ordered_paths: list[Path] = []
    source = traversal_frames / "0001-source.png"
    if source.is_file():
        ordered_paths.append(source)
    for path in sorted(traversal_frames.glob("*-post.png")):
        name = path.name.casefold()
        # Difficulty comparison frames must not recenter or warp the atlas chain.
        if "difficulty" in name or "tier" in name:
            continue
        ordered_paths.append(path)
    if len(ordered_paths) < 2:
        raise RuntimeError("accepted traversal lacks sequential post frames for atlas chain")

    if len(ordered_paths) > max_viewports:
        # Keep endpoints and sample evenly so mosaic coverage stays map-wide.
        keep = {0, len(ordered_paths) - 1}
        stride = max(1, (len(ordered_paths) - 1) // (max_viewports - 1))
        keep.update(range(0, len(ordered_paths), stride))
        ordered_paths = [ordered_paths[i] for i in sorted(keep)][:max_viewports]

    backend = OrbTranslationBackend()
    output_root = Path(output_root)
    tiles_dir = output_root / atlas_id / "tiles"
    if tiles_dir.exists():
        shutil.rmtree(tiles_dir)
    tiles_dir.mkdir(parents=True, exist_ok=True)

    viewports: list[CampaignAtlasViewport] = []
    transforms: dict[str, Matrix3] = {}
    path_by_semantic: dict[str, Path] = {}
    frame_by_semantic: dict[str, np.ndarray] = {}

    seed_path = ordered_paths[0]
    seed_frame = _load_bgr(seed_path)
    seed_sha = frame_digest(seed_frame)
    transforms[seed_sha] = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    path_by_semantic[seed_sha] = seed_path
    frame_by_semantic[seed_sha] = seed_frame
    tile_name = "viewport-001.png"
    shutil.copy2(seed_path, tiles_dir / tile_name)
    viewports.append(
        CampaignAtlasViewport(
            viewport_id="viewport-001",
            image_path=f"tiles/{tile_name}",
            source_sha256=seed_sha,
            transport_sha256=_transport_sha256(seed_path),
            transform_to_atlas=transforms[seed_sha],
            residual_px=0.0,
            overlap_ratio=1.0,
            source_session_id=ACCEPTED_TRAVERSAL_SESSION_ID,
        )
    )
    ordinal = 2
    previous_sha = seed_sha

    def _append(
        *,
        path: Path,
        frame: np.ndarray,
        semantic: str,
        absolute: Matrix3,
        residual_px: float,
        overlap_ratio: float,
        session_id: str,
    ) -> bool:
        nonlocal ordinal
        if semantic in transforms:
            return False
        center_x = float(absolute[0][2]) + (NATIVE_WIDTH / 2.0)
        center_y = float(absolute[1][2]) + (NATIVE_HEIGHT / 2.0)
        nearest = None
        nearest_dist = float("inf")
        for existing in viewports:
            prior_x = float(existing.transform_to_atlas[0][2]) + (NATIVE_WIDTH / 2.0)
            prior_y = float(existing.transform_to_atlas[1][2]) + (NATIVE_HEIGHT / 2.0)
            dist = math.hypot(center_x - prior_x, center_y - prior_y)
            if dist < nearest_dist:
                nearest = existing
                nearest_dist = dist
        if nearest is not None and nearest_dist < MIN_VIEWPORT_CENTER_SEPARATION_PX:
            # Alias the frame onto the nearest accepted viewport so landmark ROIs
            # can still resolve without stacking a near-duplicate mosaic tile.
            transforms[semantic] = nearest.transform_to_atlas
            path_by_semantic[semantic] = path
            frame_by_semantic[semantic] = frame
            return False
        transforms[semantic] = absolute
        path_by_semantic[semantic] = path
        frame_by_semantic[semantic] = frame
        tile = f"viewport-{ordinal:03d}.png"
        shutil.copy2(path, tiles_dir / tile)
        viewports.append(
            CampaignAtlasViewport(
                viewport_id=f"viewport-{ordinal:03d}",
                image_path=f"tiles/{tile}",
                source_sha256=semantic,
                transport_sha256=_transport_sha256(path),
                transform_to_atlas=absolute,
                residual_px=float(residual_px),
                overlap_ratio=float(overlap_ratio),
                source_session_id=session_id,
            )
        )
        ordinal += 1
        return True

    # Sequential Home-style chain: each post registers against the previous accepted tile.
    for path in ordered_paths[1:]:
        frame = _load_bgr(path)
        semantic = frame_digest(frame)
        if semantic in transforms:
            previous_sha = semantic
            continue
        registered = None
        # Prefer immediate predecessor; fall back to a few earlier accepted tiles.
        search = [previous_sha] + [
            item.source_sha256 for item in reversed(viewports[:-1])
        ][:3]
        seen_refs: set[str] = set()
        for ref_sha in search:
            if ref_sha in seen_refs or ref_sha not in transforms:
                continue
            seen_refs.add(ref_sha)
            registered = _try_register_viewport(
                candidate_path=path,
                candidate_frame=frame,
                candidate_semantic=semantic,
                reference_path=path_by_semantic[ref_sha],
                reference_frame=frame_by_semantic[ref_sha],
                reference_semantic=ref_sha,
                reference_transform=transforms[ref_sha],
                backend=backend,
                ordinal=ordinal,
            )
            if registered is not None:
                break
        if registered is None:
            continue
        absolute, measurement = registered
        if not _append(
            path=path,
            frame=frame,
            semantic=semantic,
            absolute=absolute,
            residual_px=float(measurement.residual_px),
            overlap_ratio=float(measurement.overlap_ratio),
            session_id=ACCEPTED_TRAVERSAL_SESSION_ID,
        ):
            continue
        previous_sha = semantic

    if len(viewports) < 8:
        raise RuntimeError(
            f"traversal chain produced only {len(viewports)} viewports; "
            "accepted survey posts failed to associate into a map atlas"
        )

    # Register landmark-session frames onto the traversal atlas for chapter/UC ROIs.
    landmark_session = survey_root / ACCEPTED_LANDMARK_SESSION_ID
    landmark_frames_dir = landmark_session / "runtime" / "frames"
    for name in (
        "0001-source.png",
        "0002-difficulty-tier-2-before.png",
        "0004-difficulty-tier-2-post.png",
    ):
        path = landmark_frames_dir / name
        if not path.is_file():
            continue
        frame = _load_bgr(path)
        semantic = frame_digest(frame)
        if semantic in transforms:
            continue
        best = None
        for existing in viewports:
            registered = _try_register_viewport(
                candidate_path=path,
                candidate_frame=frame,
                candidate_semantic=semantic,
                reference_path=path_by_semantic[existing.source_sha256],
                reference_frame=frame_by_semantic[existing.source_sha256],
                reference_semantic=existing.source_sha256,
                reference_transform=existing.transform_to_atlas,
                backend=backend,
                ordinal=ordinal,
            )
            if registered is None:
                continue
            absolute, measurement = registered
            score = (float(measurement.confidence), -float(measurement.residual_px))
            if best is None or score > best[0]:
                best = (score, absolute, measurement)
        if best is None:
            continue
        _append(
            path=path,
            frame=frame,
            semantic=semantic,
            absolute=best[1],
            residual_px=float(best[2].residual_px),
            overlap_ratio=float(best[2].overlap_ratio),
            session_id=ACCEPTED_LANDMARK_SESSION_ID,
        )

    annotation_dir = landmark_session / "annotations"
    landmarks: list[CampaignAtlasLandmark] = []
    if annotation_dir.is_dir():
        for annotation_path in sorted(annotation_dir.glob("*.json")):
            payload = json.loads(annotation_path.read_text(encoding="utf-8"))
            source_sha = str(payload["source_sha256"])
            roi = tuple(int(v) for v in payload["roi"])
            if len(roi) != 4:
                continue
            label = str(payload.get("label", ""))
            if label.startswith("campaign-chapter-"):
                kind = LandmarkKind.CHAPTER
                number = label.rsplit("-", 1)[-1]
                display = f"Chapter {number}"
            elif "ultimate" in label.casefold():
                kind = LandmarkKind.ULTIMATE_CHALLENGE
                display = "Ultimate Challenge"
            else:
                continue
            # Resolve annotation hash through traversal/landmark frames.
            path = None
            semantic = None
            if source_sha in path_by_semantic:
                path = path_by_semantic[source_sha]
                semantic = source_sha
            else:
                for candidate in sorted(landmark_frames_dir.glob("*.png")):
                    frame = _load_bgr(candidate)
                    digest = frame_digest(frame)
                    if digest == source_sha or _transport_sha256(candidate) == source_sha:
                        path = candidate
                        semantic = digest
                        break
            if path is None or semantic is None or semantic not in transforms:
                continue
            transform = transforms[semantic]
            tx = float(transform[0][2])
            ty = float(transform[1][2])
            source_viewport_id = next(
                (
                    item.viewport_id
                    for item in viewports
                    if item.source_sha256 == semantic
                    or item.transform_to_atlas == transform
                ),
                viewports[0].viewport_id,
            )
            atlas_roi = (
                int(roi[0] + tx),
                int(roi[1] + ty),
                int(roi[2] + tx),
                int(roi[3] + ty),
            )
            landmarks.append(
                CampaignAtlasLandmark(
                    landmark_id=f"{kind.value}-{display.casefold().replace(' ', '-')}",
                    kind=kind,
                    label=display,
                    atlas_roi=atlas_roi,
                    supporting_frame_sha256=semantic,
                    source_viewport_id=source_viewport_id,
                    spatially_associated=True,
                )
            )

    if not landmarks:
        raise RuntimeError(
            "atlas build produced zero landmarks; accepted landmark annotations must attach"
        )

    xs = [float(v.transform_to_atlas[0][2]) for v in viewports] + [0.0]
    ys = [float(v.transform_to_atlas[1][2]) for v in viewports] + [0.0]
    width = int(max(xs) - min(xs)) + NATIVE_WIDTH
    height = int(max(ys) - min(ys)) + NATIVE_HEIGHT
    loop = report.get("loop_closure") or {}
    cross = report.get("cross_difficulty") or {}
    atlas = CampaignAtlas(
        schema_version=1,
        atlas_id=atlas_id,
        flow_id=INTEGRATION_FLOW_ID,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
        native_width=NATIVE_WIDTH,
        native_height=NATIVE_HEIGHT,
        width=max(NATIVE_WIDTH, width),
        height=max(NATIVE_HEIGHT, height),
        source_survey_session_ids=(
            ACCEPTED_TRAVERSAL_SESSION_ID,
            ACCEPTED_LANDMARK_SESSION_ID,
            ACCEPTED_TERMINAL_SESSION_ID,
        ),
        viewports=tuple(viewports),
        landmarks=tuple(landmarks),
        loop_closure_residual_px=float(loop.get("residual_px", 0.0)),
        cross_difficulty_compared=bool(cross.get("compared", False)),
        difficulty_used_as_recenter=bool(cross.get("used_as_recenter", False)),
        image_path=None,
        created_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    manifest_path = output_root / atlas_id / "atlas.json"
    save_campaign_atlas(atlas, manifest_path)
    atlas = render_campaign_atlas_mosaic(atlas, manifest_path)
    (output_root / atlas_id / "provenance.json").write_text(
        json.dumps(
            {
                "atlas_id": atlas.atlas_id,
                "terminal_report": str(terminal_report_path).replace("\\", "/"),
                "viewport_count": len(atlas.viewports),
                "landmark_count": len(atlas.landmarks),
                "image_path": atlas.image_path,
                "build_mode": "sequential_traversal_post_chain",
                "source_survey_session_ids": list(atlas.source_survey_session_ids),
                "manifest": campaign_atlas_to_dict(atlas),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return atlas


def render_campaign_atlas_mosaic(
    atlas: CampaignAtlas,
    atlas_manifest_path: Path,
    *,
    mosaic_name: str = "atlas.png",
) -> CampaignAtlas:
    """Stitch accepted Campaign tiles into a Home-style atlas.png mosaic (offline)."""

    root = Path(atlas_manifest_path).resolve().parent
    accepted = [item for item in atlas.viewports if item.accepted]
    if not accepted:
        raise RuntimeError("Campaign atlas has no accepted viewports to mosaic")

    corners = np.float32(
        [[0, 0], [NATIVE_WIDTH, 0], [NATIVE_WIDTH, NATIVE_HEIGHT], [0, NATIVE_HEIGHT]]
    )
    transforms: list[np.ndarray] = []
    frames: list[np.ndarray] = []
    for viewport in accepted:
        tile_path = (root / viewport.image_path).resolve()
        frame = _load_bgr(tile_path)
        if frame_digest(frame) != viewport.source_sha256:
            raise ValueError(f"atlas tile digest mismatch while mosaicing: {viewport.viewport_id}")
        matrix = np.asarray(viewport.transform_to_atlas, dtype=np.float64)
        transforms.append(matrix)
        frames.append(frame)

    projected = [
        cv2.perspectiveTransform(corners.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        for matrix in transforms
    ]
    all_points = np.vstack(projected)
    minimum = np.floor(all_points.min(axis=0)).astype(int)
    maximum = np.ceil(all_points.max(axis=0)).astype(int)
    shift = np.array(
        [[1.0, 0.0, float(-minimum[0])], [0.0, 1.0, float(-minimum[1])], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    width = int(maximum[0] - minimum[0])
    height = int(maximum[1] - minimum[1])
    if width <= 0 or height <= 0 or width * height > 80_000_000:
        raise RuntimeError("Campaign atlas mosaic bounds are invalid or unexpectedly large")

    weighted = np.zeros((height, width, 3), np.float64)
    weights = np.zeros((height, width), np.float64)
    source_mask = campaign_hud_mask().astype(np.float32) / 255.0
    for frame, matrix in zip(frames, transforms):
        final_transform = shift @ matrix
        warped = cv2.warpPerspective(frame, final_transform, (width, height), flags=cv2.INTER_LINEAR)
        warped_mask = cv2.warpPerspective(
            source_mask, final_transform, (width, height), flags=cv2.INTER_NEAREST
        )
        weighted += warped.astype(np.float64) * warped_mask[..., None]
        weights += warped_mask

    mosaic = np.zeros((height, width, 3), np.uint8)
    covered = weights > 0
    mosaic[covered] = np.clip(weighted[covered] / weights[covered, None], 0, 255).astype(np.uint8)
    mosaic_path = root / mosaic_name
    if not cv2.imwrite(str(mosaic_path), mosaic):
        raise RuntimeError(f"could not write Campaign atlas mosaic: {mosaic_path}")

    # Persist shifted transforms so mosaic coordinates and atlas.json stay aligned.
    shifted_viewports = []
    for viewport, matrix in zip(accepted, transforms):
        final = shift @ matrix
        shifted_viewports.append(
            CampaignAtlasViewport(
                viewport_id=viewport.viewport_id,
                image_path=viewport.image_path,
                source_sha256=viewport.source_sha256,
                transport_sha256=viewport.transport_sha256,
                transform_to_atlas=_matrix_from_ndarray(final),
                residual_px=viewport.residual_px,
                overlap_ratio=viewport.overlap_ratio,
                accepted=viewport.accepted,
                source_session_id=viewport.source_session_id,
            )
        )

    # Landmark atlas ROIs were expressed in the pre-shift atlas frame; apply the same shift.
    sx = float(-minimum[0])
    sy = float(-minimum[1])
    shifted_landmarks = []
    for landmark in atlas.landmarks:
        left, top, right, bottom = landmark.atlas_roi
        shifted_landmarks.append(
            CampaignAtlasLandmark(
                landmark_id=landmark.landmark_id,
                kind=landmark.kind,
                label=landmark.label,
                atlas_roi=(
                    int(left + sx),
                    int(top + sy),
                    int(right + sx),
                    int(bottom + sy),
                ),
                supporting_frame_sha256=landmark.supporting_frame_sha256,
                source_viewport_id=landmark.source_viewport_id,
                spatially_associated=landmark.spatially_associated,
            )
        )

    updated = CampaignAtlas(
        schema_version=atlas.schema_version,
        atlas_id=atlas.atlas_id,
        flow_id=atlas.flow_id,
        profile_id=atlas.profile_id,
        platform=atlas.platform,
        package=atlas.package,
        native_width=atlas.native_width,
        native_height=atlas.native_height,
        width=width,
        height=height,
        source_survey_session_ids=atlas.source_survey_session_ids,
        viewports=tuple(shifted_viewports),
        landmarks=tuple(shifted_landmarks),
        loop_closure_residual_px=atlas.loop_closure_residual_px,
        cross_difficulty_compared=atlas.cross_difficulty_compared,
        difficulty_used_as_recenter=atlas.difficulty_used_as_recenter,
        image_path=mosaic_name,
        created_at_utc=atlas.created_at_utc,
    )
    save_campaign_atlas(updated, atlas_manifest_path)
    return updated


class BlueStacksCampaignLocalizer:
    """Localize an arbitrary current Campaign viewport against the atlas tiles."""

    def __init__(self, atlas: CampaignAtlas, atlas_manifest_path: Path) -> None:
        if atlas.profile_id != CAMPAIGN_PROFILE_ID:
            raise ValueError("Campaign localizer refuses a non-BlueStacks atlas profile")
        self.atlas = atlas
        self.root = Path(atlas_manifest_path).resolve().parent
        self.backend = OrbTranslationBackend()
        self.references: list[tuple[CampaignAtlasViewport, np.ndarray]] = []
        for viewport in atlas.viewports:
            if not viewport.accepted:
                continue
            path = (self.root / viewport.image_path).resolve()
            frame = _load_bgr(path)
            if frame_digest(frame) != viewport.source_sha256:
                raise ValueError(f"atlas tile digest mismatch: {viewport.viewport_id}")
            self.references.append((viewport, frame))
        if not self.references:
            raise ValueError("atlas contains no accepted Campaign viewports")

    def localize(
        self,
        frame: np.ndarray,
        *,
        campaign_screen_recognized: bool = True,
        stale: bool = False,
    ) -> CampaignLocalizationResult:
        digest = frame_digest(frame) if native_campaign_frame_guard(frame) else ""
        if not native_campaign_frame_guard(frame):
            return CampaignLocalizationResult(
                False,
                CAMPAIGN_PROFILE_ID,
                None,
                0.0,
                None,
                (),
                CampaignAmbiguityState.WRONG_PROFILE,
                digest,
            )
        if stale:
            return CampaignLocalizationResult(
                False,
                CAMPAIGN_PROFILE_ID,
                None,
                0.0,
                None,
                (),
                CampaignAmbiguityState.STALE_FRAME,
                digest,
            )
        if not campaign_screen_recognized:
            return CampaignLocalizationResult(
                False,
                CAMPAIGN_PROFILE_ID,
                None,
                0.0,
                None,
                (),
                CampaignAmbiguityState.WRONG_SCREEN,
                digest,
            )
        candidates: list[tuple[float, float, str, Matrix3]] = []
        for viewport, reference in self.references:
            observation = measure_campaign_frame_pair(
                frame,
                reference,
                candidate_provenance=_provenance_for_path(
                    Path("current-frame.png"),
                    ordinal=1,
                    semantic=digest,
                    transport=digest,
                ),
                reference_provenance=_provenance_for_path(
                    self.root / viewport.image_path,
                    ordinal=1,
                    semantic=viewport.source_sha256,
                    transport=viewport.transport_sha256,
                ),
                backend=self.backend,
            )
            measurement = observation.measurement
            if measurement.transform_candidate_to_reference is None:
                continue
            if (
                measurement.matches < MIN_ASSOCIATION_MATCHES
                or measurement.confidence < MIN_ASSOCIATION_CONFIDENCE
                or measurement.residual_px > MAX_ASSOCIATION_RESIDUAL_PX
            ):
                continue
            relative = _matrix_from_ndarray(measurement.transform_candidate_to_reference)
            absolute = _compose_translation(viewport.transform_to_atlas, relative)
            candidates.append(
                (
                    float(measurement.confidence),
                    float(measurement.residual_px),
                    viewport.viewport_id,
                    absolute,
                )
            )
        if not candidates:
            return CampaignLocalizationResult(
                False,
                CAMPAIGN_PROFILE_ID,
                None,
                0.0,
                None,
                (),
                CampaignAmbiguityState.INSUFFICIENT_LANDMARKS,
                digest,
            )
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best = candidates[0]
        if len(candidates) > 1 and candidates[1][0] >= best[0] - 0.04:
            dx = abs(best[3][0][2] - candidates[1][3][0][2])
            dy = abs(best[3][1][2] - candidates[1][3][1][2])
            if (dx + dy) > 48:
                return CampaignLocalizationResult(
                    False,
                    CAMPAIGN_PROFILE_ID,
                    None,
                    best[0],
                    best[1],
                    (best[2], candidates[1][2]),
                    CampaignAmbiguityState.CONFLICTING_TRANSFORMS,
                    digest,
                )
        return CampaignLocalizationResult(
            True,
            CAMPAIGN_PROFILE_ID,
            best[3],
            best[0],
            best[1],
            tuple(item[2] for item in candidates[:3]),
            CampaignAmbiguityState.NONE,
            digest,
        )


def bind_campaign_destination_from_current_frame(
    frame: np.ndarray,
    *,
    atlas: CampaignAtlas,
    localization: CampaignLocalizationResult,
    consumer: str,
    destination_id: str,
) -> CampaignDestinationBinding:
    """Bind a destination from the current native frame; atlas projection only narrows search."""

    digest = frame_digest(frame) if native_campaign_frame_guard(frame) else ""
    if not native_campaign_frame_guard(frame):
        return CampaignDestinationBinding(
            CampaignDestinationKind.CHAPTER,
            destination_id,
            False,
            None,
            digest,
            0.0,
            False,
            None,
            "current frame is not native 800x1280",
        )
    kind, label = resolve_campaign_consumer_destination(consumer, destination_id)
    landmark_kind = (
        LandmarkKind.ULTIMATE_CHALLENGE
        if kind is CampaignDestinationKind.ULTIMATE_CHALLENGE
        else LandmarkKind.CHAPTER
    )
    landmark = atlas.lookup_landmark(kind=landmark_kind, label=label)
    if landmark is None:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            0.0,
            False,
            None,
            f"atlas landmark missing for {label}",
        )
    search_roi = project_landmark_search_roi(localization, landmark)
    # Current-frame semantic association: require the landmark's supporting crop to
    # match inside the projected search window (or full map-search ROI as fallback).
    source_viewport = next(
        (item for item in atlas.viewports if item.viewport_id == landmark.source_viewport_id),
        None,
    )
    if source_viewport is None:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            0.0,
            search_roi is not None,
            search_roi,
            "landmark source viewport missing from atlas",
        )
    # Reconstruct template from atlas tile using original frame-space ROI.
    tx = float(source_viewport.transform_to_atlas[0][2])
    ty = float(source_viewport.transform_to_atlas[1][2])
    frame_roi = (
        int(landmark.atlas_roi[0] - tx),
        int(landmark.atlas_roi[1] - ty),
        int(landmark.atlas_roi[2] - tx),
        int(landmark.atlas_roi[3] - ty),
    )
    tile_path = Path(source_viewport.image_path)
    # Caller supplies atlas root via localizer usually; resolve relative to CWD artifact.
    # Prefer reading through ACCEPTED survey index by semantic hash.
    indexed = index_survey_frames_by_semantic_sha()
    if landmark.supporting_frame_sha256 in indexed:
        source_frame = _load_bgr(indexed[landmark.supporting_frame_sha256])
    else:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            0.0,
            search_roi is not None,
            search_roi,
            "landmark supporting native frame is not retained",
        )
    left, top, right, bottom = frame_roi
    left = max(0, left)
    top = max(0, top)
    right = min(NATIVE_WIDTH, right)
    bottom = min(NATIVE_HEIGHT, bottom)
    if right - left < 8 or bottom - top < 8:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            0.0,
            search_roi is not None,
            search_roi,
            "landmark template ROI is empty",
        )
    template = source_frame[top:bottom, left:right]
    window = search_roi or MAP_SEARCH_ROI
    x0, y0, x1, y1 = window
    haystack = frame[y0:y1, x0:x1]
    if haystack.size == 0 or template.size == 0 or haystack.shape[0] < template.shape[0] or haystack.shape[1] < template.shape[1]:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            0.0,
            search_roi is not None,
            search_roi,
            "search window cannot contain landmark template",
        )
    result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    if float(max_val) < 0.52:
        return CampaignDestinationBinding(
            kind,
            label,
            False,
            None,
            digest,
            float(max_val),
            search_roi is not None,
            search_roi,
            f"current-frame template score too low: {max_val:.3f}",
        )
    th, tw = template.shape[:2]
    bound_roi = (
        x0 + int(max_loc[0]),
        y0 + int(max_loc[1]),
        x0 + int(max_loc[0]) + tw,
        y0 + int(max_loc[1]) + th,
    )
    return CampaignDestinationBinding(
        kind,
        label,
        True,
        bound_roi,
        digest,
        float(max_val),
        search_roi is not None,
        search_roi,
        "current-frame semantic destination bound",
    )
