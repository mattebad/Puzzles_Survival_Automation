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
from scripts.bounded_tesseract import call_ocr, tesseract_string

SCARLETT_THREE_DAY_PACK = "SCARLETT_THREE_DAY_PACK"
SCARLETT_SURFACE_KIND = "full_page"
SCARLETT_NATIVE_GEOMETRY = (NATIVE_WIDTH, NATIVE_HEIGHT)
# Fixture digests are provenance facts, not recognition allowlists. Live game
# animation can legitimately change the full-frame digest.
SCARLETT_FRAME_SHA256 = "f828bfa09af4d8085d69d432d471ede67f7bc5562a43a5fc58454ff3bd3ecbdc"
SCARLETT_TITLE_ROI = (230, 0, 570, 80)
SCARLETT_SAFE_BACK_TARGET_IDENTITY = "scarlett-three-day-pack-in-game-back"
SCARLETT_SAFE_BACK_ROI = (39, 0, 168, 61)
SCARLETT_BENEFITS_ROI = (50, 265, 750, 465)
SCARLETT_DAYS_ROI = (50, 670, 155, 1020)
SCARLETT_NOTICE_ROI = (130, 1045, 700, 1115)
# Retained hashes of these current regions are evidence metadata only.
SCARLETT_EVIDENCE_ROIS = (
    ("title", SCARLETT_TITLE_ROI),
    ("safe_back", SCARLETT_SAFE_BACK_ROI),
    ("benefits", SCARLETT_BENEFITS_ROI),
    ("days", SCARLETT_DAYS_ROI),
    ("notice", SCARLETT_NOTICE_ROI),
)
SCARLETT_FORBIDDEN_PURCHASE_ROIS = (
    (78, 111, 800, 1280),
    (556, 1110, 800, 1280),
)
SCARLETT_EXPECTED_SUCCESSOR = "retained_successor_required"
SCARLETT_MAX_INPUTS = 1

CASH_MALL = "CASH_MALL"
CASH_MALL_TITLE_ROI = (300, 8, 515, 55)
CASH_MALL_SAFE_BACK_TARGET_IDENTITY = "cash-mall-in-game-back"
CASH_MALL_FORBIDDEN_ROIS = ((180, 0, 800, 1280), (0, 65, 180, 1280))

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
# Home event offers live in the edge HUD. Inspect the gameplay center for
# payment surfaces only after independent current-frame Home recognition.
HOME_COMMERCIAL_SCENE_ROI = (100, 180, 600, 1120)
COMMERCIAL_OCR_TIMEOUT_SECONDS = 3.0


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
        title = _crop(frame, SCARLETT_TITLE_ROI)
        enlarged = cv2.resize(title, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
        return _normalise(call_ocr(
            tesseract_string, enlarged, call_timeout=3.0, config="--psm 7"
        ))
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


def _evidence_roi_hashes(frame: np.ndarray) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            identity,
            hashlib.sha256(
                np.ascontiguousarray(_crop(frame, roi)).tobytes()
            ).hexdigest(),
        )
        for identity, roi in SCARLETT_EVIDENCE_ROIS
    )


def _scarlett_page_context(frame: np.ndarray) -> bool:
    """Require the current offer's text/layout, excluding character artwork."""
    try:
        def text(roi, scale=1.0):
            pixels = _crop(frame, roi)
            if scale != 1.0:
                pixels = cv2.resize(pixels, None, fx=scale, fy=scale)
            return _normalise(call_ocr(
                tesseract_string, pixels, call_timeout=3.0, config="--psm 11"
            ))

        benefits = _letters(text(SCARLETT_BENEFITS_ROI))
        benefit_terms = ("maxeffect", "buildspeed", "freespeeduptime")
        if not all(term in benefits for term in benefit_terms):
            # Gold italic text over animated flames needs line segmentation
            # and color contrast; whole-panel sparse OCR can merge its strokes.
            lines = []
            for roi, gold in (((55, 280, 250, 325), False),
                    ((50, 330, 520, 392), True), ((50, 395, 750, 455), True)):
                pixels = _crop(frame, roi)
                pixels = (255 - cv2.inRange(cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV),
                    np.array((15, 80, 150), np.uint8), np.array((45, 255, 255), np.uint8))
                    if gold else cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY))
                pixels = cv2.resize(pixels, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
                pixels = cv2.copyMakeBorder(pixels, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
                lines.append(_letters(call_ocr(tesseract_string, pixels, call_timeout=3.0, config="--psm 7")))
            benefits = " ".join(line if term in line else "" for line, term in zip(lines, benefit_terms))
        days = _letters(text(SCARLETT_DAYS_ROI, 2.0))
        notice = _letters(text(SCARLETT_NOTICE_ROI))
        center = _letters(text((180, 350, 640, 1020)))
    except Exception:
        return False
    return bool(
        all(term in benefits for term in benefit_terms)
        and all(term in days for term in ("day1", "day2", "day3"))
        and "onlybuyone" in notice and "1sttopuppack" in notice
        and not any(term in center for term in (
            "confirm", "cancel", "payment", "checkout", "close", "areyousure",
        ))
    )


def _scarlett_back_arrow(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual

    target = _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)
    if target is None:
        return None
    x0, y0, x1, y1 = target
    sx0, sy0, sx1, sy1 = SCARLETT_SAFE_BACK_ROI
    return target if sx0 <= x0 < x1 <= sx1 and sy0 <= y0 < y1 <= sy1 else None


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
    from scripts.startup_normalization import classify_home_base_live

    home = classify_home_base_live(
        frame, cash_mall_rejected=True, safe_os_surface=True
    )
    home_context = bool(
        home.get("state") == "HOME_BASE"
        and home.get("recognized") is True
        and not home.get("overlay")
        and not home.get("blocking_unknown_modal")
        and not home.get("manual_only_state")
    )
    candidate = _crop(frame, HOME_COMMERCIAL_SCENE_ROI) if home_context else frame
    try:
        text = _normalise(call_ocr(
            tesseract_string, candidate, call_timeout=COMMERCIAL_OCR_TIMEOUT_SECONDS, config="--psm 11"
        ))
    except Exception:
        text = ""
    terms = tuple(sorted(term for term in COMMERCIAL_TERMS if term in text))
    # Home event labels alone are not payment surfaces. Unknown source pages
    # retain whole-frame commercial detection; central purchase dialogs still
    # block even when Home context remains visible behind them.
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
    page_context_verified: bool = False
    measured_back_roi: tuple[int, int, int, int] | None = None

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
    critical_roi_hashes = _evidence_roi_hashes(frame)
    page_context = title_identity and _scarlett_page_context(frame)
    back_arrow = _scarlett_back_arrow(frame) if title_identity else None
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
        "current_offer_benefits_and_three_day_rows",
        "current_first_topup_notice",
    )
    recognized = bool(
        frame_bytes_bound
        and page_context
        and back_arrow is not None
        and title_identity
        and target_exact
        and exclusion_verified
    )
    if not frame_bytes_bound:
        reason = "frame_bytes_do_not_match_current_pixels"
    elif not title_identity:
        reason = "exact_title_semantics_missing"
    elif not page_context:
        reason = "current_scarlett_page_context_missing_or_overlaid"
    elif back_arrow is None:
        reason = "current_safe_back_arrow_not_uniquely_bound"
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
        bool(page_context),
        back_arrow,
    )
    return result.to_mapping()


def _cash_mall_recognition(
    frame: np.ndarray, frame_bytes: bytes | None,
) -> dict[str, Any]:
    """Bind only the current Cash Mall title and isolated standard game Back."""
    from scripts.bluestacks_popup_recognition import recognize_shared_interruption

    try:
        title = _normalise(call_ocr(
            tesseract_string,
            cv2.resize(_crop(frame, CASH_MALL_TITLE_ROI), None, fx=4.0, fy=4.0),
            call_timeout=3.0, config="--psm 7",
        ))
    except Exception:
        title = ""

    title_identity = _letters(title) == "cashmall"
    arrow = _scarlett_back_arrow(frame) if title_identity else None
    interruption = recognize_shared_interruption(frame) if title_identity else {}
    recognized = bool(
        title_identity and arrow is not None
        and _frame_bytes_match_pixels(frame, frame_bytes)
        and not interruption.get("recognized") and not interruption.get("blocking_unknown_modal")
    )
    return StartupSurfaceRecognition(
        recognized, CASH_MALL if recognized else None,
        "full_page" if recognized else None,
        NATIVE_RUNTIME_PROFILE_ID if recognized else None,
        NATIVE_WIDTH, NATIVE_HEIGHT, _raw_frame_hash(frame, frame_bytes),
        title, title_identity,
        ("title:Cash Mall", "visible_in_game_back_upper_left", "purchase_regions_excluded")
        if recognized else (),
        CASH_MALL_SAFE_BACK_TARGET_IDENTITY if recognized else None,
        SCARLETT_SAFE_BACK_ROI if recognized else None,
        CASH_MALL_FORBIDDEN_ROIS if recognized else (),
        SCARLETT_EXPECTED_SUCCESSOR if recognized else None,
        1 if recognized else 0, 1 if arrow is not None else 0, recognized,
        _evidence_roi_hashes(frame),
        "exact_cash_mall_title_and_safe_back" if recognized else "cash_mall_not_safely_bound",
        recognized, arrow,
    ).to_mapping()


def is_exact_startup_surface_recognition(recognition: Mapping[str, Any]) -> bool:
    """Validate either allowlisted page; never authorize an arrow by itself."""
    if recognition.get("surface_identity") != CASH_MALL:
        return is_exact_scarlett_recognition(recognition)
    arrow = recognition.get("measured_back_roi")
    return bool(
        recognition.get("recognized") is True
        and recognition.get("runtime_profile_id") == NATIVE_RUNTIME_PROFILE_ID
        and (recognition.get("width"), recognition.get("height")) == SCARLETT_NATIVE_GEOMETRY
        and recognition.get("surface_kind") == "full_page"
        and _letters(str(recognition.get("title_text") or "")) == "cashmall"
        and recognition.get("safe_exit_target_identity") == CASH_MALL_SAFE_BACK_TARGET_IDENTITY
        and recognition.get("safe_exit_roi") == SCARLETT_SAFE_BACK_ROI
        and recognition.get("forbidden_purchase_rois") == CASH_MALL_FORBIDDEN_ROIS
        and recognition.get("purchase_exclusion_verified") is True
        and recognition.get("title_identity") is True
        and recognition.get("page_context_verified") is True
        and recognition.get("expected_successor") == SCARLETT_EXPECTED_SUCCESSOR
        and recognition.get("max_inputs") == 1 and recognition.get("target_count") == 1
        and isinstance(arrow, (tuple, list)) and len(arrow) == 4
        and SCARLETT_SAFE_BACK_ROI[0] <= arrow[0] < arrow[2] <= SCARLETT_SAFE_BACK_ROI[2]
        and SCARLETT_SAFE_BACK_ROI[1] <= arrow[1] < arrow[3] <= SCARLETT_SAFE_BACK_ROI[3]
        and re.fullmatch(r"[0-9a-f]{64}", str(recognition.get("frame_sha256") or "")) is not None
    )


def recognize_startup_surface(frame: np.ndarray, frame_bytes: bytes | None = None) -> dict[str, Any]:
    """Return exact known startup-page recognition or blocking commercial evidence."""
    scarlett = recognize_scarlett_three_day_pack(frame, frame_bytes)
    if _valid_frame(frame) and not scarlett.get("recognized"):
        cash_mall = _cash_mall_recognition(frame, frame_bytes)
        if cash_mall["recognized"]:
            return dict(cash_mall, commercial_looking=False, commercial_terms=(), commercial_text="")
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
    required_evidence = {
        "title:Scarlett 3-Day Pack", "full_page_real_money_promotion",
        "visible_in_game_back_upper_left", "purchase_regions_excluded",
        "current_offer_benefits_and_three_day_rows", "current_first_topup_notice",
    }
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
        arrow = tuple(int(value) for value in recognition.get("measured_back_roi", ()))
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
        and recognition.get("page_context_verified") is True
        and len(arrow) == 4
        and target[0] <= arrow[0] < arrow[2] <= target[2]
        and target[1] <= arrow[1] < arrow[3] <= target[3]
        and isinstance(current_frame_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", current_frame_sha256) is not None
    )


recognize_scarlett_surface = recognize_scarlett_three_day_pack
classify_startup_surface = recognize_startup_surface
