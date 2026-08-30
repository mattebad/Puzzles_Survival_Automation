"""Fail-closed recognition for the retained Scarlett startup surface.

This module is recognition-only.  It never owns transport, runtime leases, or
input authority.  Scarlett identity is bound from stable local regions on the
current native frame; the full-frame hash records provenance and freshness but
is not a permanent screen fingerprint.  Unobserved commercial variants remain
unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import NATIVE_HEIGHT, NATIVE_RUNTIME_PROFILE_ID, NATIVE_WIDTH

SCARLETT_THREE_DAY_PACK = "SCARLETT_THREE_DAY_PACK"
SCARLETT_SURFACE_KIND = "full_page"
SCARLETT_NATIVE_GEOMETRY = (NATIVE_WIDTH, NATIVE_HEIGHT)
# Fixture digests are provenance facts, not recognition allowlists. Live game
# animation can legitimately change the full-frame digest.
SCARLETT_FRAME_SHA256 = "f828bfa09af4d8085d69d432d471ede67f7bc5562a43a5fc58454ff3bd3ecbdc"
SCARLETT_PIXEL_SHA256 = "cba2a6d58e71fec2dc2792f55a95645f70a2fab1de418b750582e80175c88b54"
SCARLETT_TITLE_ROI = (230, 0, 570, 80)
SCARLETT_SAFE_BACK_TARGET_IDENTITY = "scarlett-three-day-pack-in-game-back"
SCARLETT_SAFE_BACK_ROI = (39, 0, 168, 61)
SCARLETT_SURFACE_IDENTITY_ROI = (80, 120, 720, 360)
SCARLETT_CRITICAL_ROI_HASHES = (
    ("title", "cbb90e2485ccdaebbeb0cdae910a8ffdbfe3a80552882da116b534f9f55da16c"),
    ("safe_back", "cef6a2d627791be82f0cc81e0e2488b204f64199770dd3fdb9657f91425cfd6a"),
    ("surface_identity", "dbfb22593ee2980cc0340ca5ccb4586459b6e462460dfd78ea9a2337f7b087e3"),
)
SCARLETT_CRITICAL_ROIS = (
    ("title", SCARLETT_TITLE_ROI),
    ("safe_back", SCARLETT_SAFE_BACK_ROI),
    ("surface_identity", SCARLETT_SURFACE_IDENTITY_ROI),
)
SCARLETT_FORBIDDEN_PURCHASE_ROIS = (
    (78, 111, 800, 1280),
    (556, 1110, 800, 1280),
)
SCARLETT_EXPECTED_SUCCESSOR = "retained_successor_required"
SCARLETT_MAX_INPUTS = 1

COMMERCIAL_TERMS = frozenset(
    {
        "buy",
        "purchase",
        "pack",
        "offer",
        "top-up",
        "topup",
        "premium",
        "payment",
        "checkout",
        "price",
        "usd",
        "dollar",
        "gift",
    }
)


def _normalise(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalise(text))


def _valid_frame(frame: object) -> bool:
    return (
        isinstance(frame, np.ndarray)
        and frame.dtype == np.uint8
        and frame.ndim == 3
        and frame.shape == (NATIVE_HEIGHT, NATIVE_WIDTH, 3)
    )


def _crop(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def _title_text(frame: np.ndarray) -> str:
    try:
        import pytesseract

        title = _crop(frame, SCARLETT_TITLE_ROI)
        enlarged = cv2.resize(title, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
        return _normalise(pytesseract.image_to_string(enlarged, config="--psm 7"))
    except Exception:
        return ""


def _title_matches(text: str) -> bool:
    compact = _letters(text)
    return compact == "scarlett3daypack"


def _raw_frame_hash(frame: np.ndarray, frame_bytes: bytes | None) -> str:
    if isinstance(frame_bytes, bytes) and frame_bytes:
        return hashlib.sha256(frame_bytes).hexdigest()
    return hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest()


def _frame_bytes_match_pixels(frame: np.ndarray, frame_bytes: bytes | None) -> bool:
    """Reject stale/cross-frame byte provenance without requiring a fixture hash."""
    if frame_bytes is None:
        return True
    if not isinstance(frame_bytes, bytes) or not frame_bytes:
        return False
    encoded = np.frombuffer(frame_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    return bool(
        isinstance(decoded, np.ndarray)
        and decoded.shape == frame.shape
        and np.array_equal(decoded, frame)
    )


def _critical_roi_hashes(frame: np.ndarray) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            identity,
            hashlib.sha256(
                np.ascontiguousarray(_crop(frame, roi)).tobytes()
            ).hexdigest(),
        )
        for identity, roi in SCARLETT_CRITICAL_ROIS
    )


def _roi_valid(roi: Sequence[int], *, width: int = NATIVE_WIDTH, height: int = NATIVE_HEIGHT) -> bool:
    try:
        x0, y0, x1, y1 = (int(value) for value in roi)
    except (TypeError, ValueError):
        return False
    return 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height


def _intersects(left: Sequence[int], right: Sequence[int]) -> bool:
    lx0, ly0, lx1, ly1 = (int(value) for value in left)
    rx0, ry0, rx1, ry1 = (int(value) for value in right)
    return max(lx0, rx0) < min(lx1, rx1) and max(ly0, ry0) < min(ly1, ry1)


def _target_set_is_exact(targets: object) -> bool:
    if targets is None:
        return True
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        return False
    values = list(targets)
    if len(values) != 1:
        return False
    candidate = values[0]
    if isinstance(candidate, Mapping):
        identity = candidate.get("target_identity") or candidate.get("identity")
        roi = candidate.get("roi") or candidate.get("target_roi")
    elif isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)) and len(candidate) == 2:
        identity, roi = candidate
    else:
        return False
    try:
        normalized_roi = tuple(int(value) for value in roi)
    except (TypeError, ValueError):
        return False
    return identity == SCARLETT_SAFE_BACK_TARGET_IDENTITY and normalized_roi == SCARLETT_SAFE_BACK_ROI


def commercial_surface_signal(frame: np.ndarray) -> dict[str, Any]:
    """Return conservative evidence that an unallowlisted commercial surface is present."""
    if not _valid_frame(frame):
        return {"commercial_looking": False, "terms": (), "text": ""}
    try:
        import pytesseract

        text = _normalise(pytesseract.image_to_string(frame, config="--psm 11"))
    except Exception:
        text = ""
    terms = tuple(sorted(term for term in COMMERCIAL_TERMS if term in text))
    # Any commercial term is enough to prevent an unknown startup frame from
    # being treated as clear Home; recognition never grants purchase authority.
    commercial = bool(terms) or any(term in text for term in ("buy one", "top-up", "payment", "checkout"))
    return {"commercial_looking": commercial, "terms": terms, "text": text}


@dataclass(frozen=True)
class StartupSurfaceRecognition:
    recognized: bool
    surface_identity: str | None
    surface_kind: str | None
    runtime_profile_id: str | None
    width: int
    height: int
    frame_sha256: str
    title_text: str
    title_identity: bool
    semantic_evidence: tuple[str, ...]
    safe_exit_target_identity: str | None
    safe_exit_roi: tuple[int, int, int, int] | None
    forbidden_purchase_rois: tuple[tuple[int, int, int, int], ...]
    expected_successor: str | None
    max_inputs: int
    target_count: int
    purchase_exclusion_verified: bool
    critical_roi_hashes: tuple[tuple[str, str], ...]
    reason: str

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def recognize_scarlett_three_day_pack(
    frame: np.ndarray,
    frame_bytes: bytes | None = None,
    *,
    target_candidates: Sequence[object] | None = None,
) -> dict[str, Any]:
    """Recognize Scarlett from stable current-frame regions and safe Back geometry."""
    width = int(frame.shape[1]) if isinstance(frame, np.ndarray) and frame.ndim >= 2 else 0
    height = int(frame.shape[0]) if isinstance(frame, np.ndarray) and frame.ndim >= 2 else 0
    digest = _raw_frame_hash(frame, frame_bytes) if _valid_frame(frame) else ""
    if not _valid_frame(frame):
        result = StartupSurfaceRecognition(
            False, None, None, None, width, height, digest, "", False, (), None, None,
            (), None, 0, 0, False, (), "native_800x1280_profile_required",
        )
        return result.to_mapping()
    title = _title_text(frame)
    title_identity = _title_matches(title)
    frame_bytes_bound = _frame_bytes_match_pixels(frame, frame_bytes)
    critical_roi_hashes = _critical_roi_hashes(frame)
    stable_identity = critical_roi_hashes == SCARLETT_CRITICAL_ROI_HASHES
    target_exact = _target_set_is_exact(target_candidates)
    exclusion_verified = bool(
        _roi_valid(SCARLETT_SAFE_BACK_ROI)
        and all(_roi_valid(roi) for roi in SCARLETT_FORBIDDEN_PURCHASE_ROIS)
        and all(not _intersects(SCARLETT_SAFE_BACK_ROI, roi) for roi in SCARLETT_FORBIDDEN_PURCHASE_ROIS)
    )
    semantic = (
        "title:Scarlett 3-Day Pack",
        "full_page_real_money_promotion",
        "visible_in_game_back_upper_left",
        "purchase_regions_excluded",
    )
    recognized = bool(
        frame_bytes_bound
        and stable_identity
        and title_identity
        and target_exact
        and exclusion_verified
    )
    if not frame_bytes_bound:
        reason = "frame_bytes_do_not_match_current_pixels"
    elif not stable_identity:
        reason = "stable_scarlett_roi_signature_mismatch"
    elif not title_identity:
        reason = "exact_title_semantics_missing"
    elif not target_exact:
        reason = "safe_back_target_is_ambiguous_or_wrong_geometry"
    elif not exclusion_verified:
        reason = "purchase_exclusion_missing_or_intersects_safe_target"
    else:
        reason = "exact_scarlett_three_day_pack_full_page_matched"
    result = StartupSurfaceRecognition(
        recognized,
        SCARLETT_THREE_DAY_PACK if recognized else None,
        SCARLETT_SURFACE_KIND if recognized else None,
        NATIVE_RUNTIME_PROFILE_ID if recognized else None,
        NATIVE_WIDTH,
        NATIVE_HEIGHT,
        digest,
        title,
        title_identity,
        semantic if recognized else (),
        SCARLETT_SAFE_BACK_TARGET_IDENTITY if recognized else None,
        SCARLETT_SAFE_BACK_ROI if recognized else None,
        SCARLETT_FORBIDDEN_PURCHASE_ROIS if recognized else (),
        SCARLETT_EXPECTED_SUCCESSOR if recognized else None,
        SCARLETT_MAX_INPUTS if recognized else 0,
        1 if target_exact else 0,
        exclusion_verified,
        critical_roi_hashes,
        reason,
    )
    return result.to_mapping()


def recognize_startup_surface(frame: np.ndarray, frame_bytes: bytes | None = None) -> dict[str, Any]:
    """Return exact Scarlett recognition or conservative commercial evidence."""
    scarlett = recognize_scarlett_three_day_pack(frame, frame_bytes)
    if scarlett.get("recognized"):
        return {
            **scarlett,
            "commercial_looking": False,
            "commercial_terms": (),
            "commercial_text": "",
        }
    signal = commercial_surface_signal(frame)
    return {
        **scarlett,
        "commercial_looking": bool(signal.get("commercial_looking")),
        "commercial_terms": signal.get("terms", ()),
        "commercial_text": signal.get("text", ""),
    }


def is_exact_scarlett_recognition(recognition: Mapping[str, Any]) -> bool:
    """Validate a recognition record before any caller grants a recovery input."""
    if not isinstance(recognition, Mapping) or recognition.get("recognized") is not True:
        return False
    if recognition.get("surface_identity") != SCARLETT_THREE_DAY_PACK:
        return False
    if recognition.get("surface_kind") != SCARLETT_SURFACE_KIND:
        return False
    if recognition.get("runtime_profile_id") != NATIVE_RUNTIME_PROFILE_ID:
        return False
    if (recognition.get("width"), recognition.get("height")) != SCARLETT_NATIVE_GEOMETRY:
        return False
    if recognition.get("safe_exit_target_identity") != SCARLETT_SAFE_BACK_TARGET_IDENTITY:
        return False
    if not _title_matches(str(recognition.get("title_text") or "")):
        return False
    evidence = recognition.get("semantic_evidence")
    required_evidence = {"title:Scarlett 3-Day Pack", "full_page_real_money_promotion", "visible_in_game_back_upper_left", "purchase_regions_excluded"}
    if not isinstance(evidence, (tuple, list)):
        return False
    try:
        evidence_set = set(evidence)
    except (TypeError, ValueError):
        return False
    if not required_evidence.issubset(evidence_set):
        return False
    try:
        target = tuple(int(value) for value in recognition.get("safe_exit_roi", ()))
        forbidden = tuple(tuple(int(value) for value in roi) for roi in recognition.get("forbidden_purchase_rois", ()))
        critical_roi_hashes = tuple((str(identity), str(digest)) for identity, digest in recognition.get("critical_roi_hashes", ()))
    except (TypeError, ValueError):
        return False
    current_frame_sha256 = recognition.get("frame_sha256")
    return bool(
        target == SCARLETT_SAFE_BACK_ROI
        and forbidden == SCARLETT_FORBIDDEN_PURCHASE_ROIS
        and recognition.get("purchase_exclusion_verified") is True
        and recognition.get("expected_successor") == SCARLETT_EXPECTED_SUCCESSOR
        and recognition.get("max_inputs") == SCARLETT_MAX_INPUTS
        and recognition.get("target_count") == 1
        and recognition.get("title_identity") is True
        and critical_roi_hashes == SCARLETT_CRITICAL_ROI_HASHES
        and isinstance(current_frame_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", current_frame_sha256) is not None
    )


recognize_scarlett_surface = recognize_scarlett_three_day_pack
classify_startup_surface = recognize_startup_surface
