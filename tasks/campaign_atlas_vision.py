"""Map-agnostic visual seams for future Campaign atlas evidence.

Registration is dependency-injected and measurement-only.  No backend,
threshold, acceptance policy, target binding, or input authority is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol

import cv2
import numpy as np

from .campaign_atlas import (
    CAMPAIGN_PROFILE_ID,
    HudMaskContract,
    NativeFrameProvenance,
    Rect,
)


CAMPAIGN_HUD_MASK = HudMaskContract(
    contract_id="campaign-map-fixed-hud-v1",
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


@dataclass(frozen=True)
class CampaignRegistrationObservation:
    candidate_sha256: str
    reference_sha256: str
    measurement: RegistrationMeasurement
    accepted: bool = False
    authorizes_input: bool = False
    reason: str = "measurement_only_pending_native_evidence_and_reviewed_policy"


class RegistrationBackend(Protocol):
    def measure(
        self,
        candidate: np.ndarray,
        reference: np.ndarray,
        mask: np.ndarray,
    ) -> RegistrationMeasurement: ...


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
