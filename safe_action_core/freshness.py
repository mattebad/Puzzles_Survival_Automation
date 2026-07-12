"""Exact frame/ROI bindings used by pre-dispatch perception reuse."""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping, Optional

from .models import Observation


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def roi_hash_map(observation: Observation) -> Mapping[str, str]:
    return dict(observation.critical_roi_hashes)


def ocr_reuse_denial(
    proposal: Observation,
    immediate: Observation,
    required_roi_ids: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Return a fail-closed reason when prior-frame OCR is not safely reusable."""
    if not immediate.ocr_reused:
        if (
            immediate.ocr_result_frame_sha256 is not None
            and immediate.ocr_result_frame_sha256 != immediate.frame_sha256
        ):
            return "OCR_NOT_BOUND_TO_IMMEDIATE_FRAME"
        return None
    if immediate.ocr_result_frame_sha256 != proposal.frame_sha256:
        return "OCR_REUSE_SOURCE_MISMATCH"
    if (
        immediate.ocr_result_capture_completed_monotonic
        != proposal.capture_completed_monotonic
    ):
        return "OCR_REUSE_CAPTURE_MISMATCH"
    before = roi_hash_map(proposal)
    after = roi_hash_map(immediate)
    required = tuple(required_roi_ids or before.keys())
    if not required:
        return "OCR_REUSE_WITHOUT_CRITICAL_ROI"
    for roi_id in required:
        if not before.get(roi_id) or before.get(roi_id) != after.get(roi_id):
            return "CRITICAL_ROI_CHANGED"
    semantic_fields = (
        "runtime_profile_id",
        "source_state",
        "overlay_state",
        "target_identity",
        "target_roi",
        "consequence",
        "cost_type",
        "cost_amount",
        "quantity",
        "expected_postcondition",
    )
    if any(getattr(proposal, name) != getattr(immediate, name) for name in semantic_fields):
        return "OCR_REUSE_SEMANTICS_CHANGED"
    return None
