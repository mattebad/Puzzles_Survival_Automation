"""Native 800x1280 OCR/color recognition for the Research Lab Nova route."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from .nova_praise import (
    NOVA_HOME,
    NOVA_INTERACTION_TARGET,
    NOVA_LAB_MENU,
    NOVA_PRAISE_TARGET,
    NOVA_SCREEN,
    NovaPraiseObservation,
    parse_cooldown_seconds,
)


PROFILE_SIZE = (800, 1280)
Box = tuple[int, int, int, int]
_ASSETS_ROOT = Path(__file__).resolve().parent / "assets" / "nova_praise" / "800x1280"
NOVA_RADIAL_TEMPLATE_PATH = _ASSETS_ROOT / "nova-radial-portrait.png"
NOVA_RADIAL_TEMPLATE_MANIFEST_PATH = _ASSETS_ROOT / "manifest.json"
NOVA_TEMPLATE_MATCH_METHOD = "cv2.TM_CCOEFF_NORMED"
NOVA_TEMPLATE_SCALES = (0.92, 0.96, 1.0, 1.04, 1.08)
NOVA_TEMPLATE_MIN_SCORE = 0.90
NOVA_TEMPLATE_MIN_MARGIN = 0.08
NOVA_TEMPLATE_SEARCH_PAD_PX = 56
NOVA_TEMPLATE_EDGE_CLIP_PX = 2
RESEARCH_LAB_UPGRADE_SCREEN = "RESEARCH_LAB_UPGRADE"

RESEARCH_LAB_ROI: Box = (455, 410, 665, 650)
LAB_MENU_ROI: Box = (330, 570, 760, 780)
NOVA_MENU_ROI: Box = (500, 600, 640, 760)
NOVA_HEADER_ROI: Box = (260, 0, 540, 92)
NOVA_BODY_ROI: Box = (80, 80, 730, 930)
NOVA_PRAISE_ROI: Box = (270, 975, 530, 1115)
NOVA_ATTEMPTS_ROI: Box = (150, 1125, 650, 1235)
# The native CD timer is above the interaction buttons; keep it separate from the
# attempts counter so a clipped lower panel cannot masquerade as cooldown evidence.
NOVA_COOLDOWN_ROI: Box = (100, 900, 700, 1000)
NOVA_OVERLAY_ROI: Box = (0, 0, 800, 1280)
_ATTEMPTS_RE = re.compile(r"(?:attempts?|interactions?)[^0-9]{0,20}(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class NovaFrameRecognition:
    observation: NovaPraiseObservation
    frame_sha256: str
    targets: tuple[tuple[str, Box], ...]
    diagnostics: dict[str, object]

    def target(self, identity: str) -> Box | None:
        return dict(self.targets).get(identity)


@dataclass(frozen=True)
class ResearchLabTapProvenance:
    action_key: str
    target_identity: str
    source_frame_sha256: str
    target_roi: Box
    dispatched_monotonic: float


@dataclass(frozen=True)
class ResearchLabRadialEvidence:
    semantic_state: str
    recognized: bool
    confidence: float
    supporting_observations: tuple[str, ...]
    rejected_or_missing_observations: tuple[str, ...]
    source_frame_sha256: str
    nova_target_roi: Box | None
    geometry_anchors: tuple[str, ...]
    ocr_terms: tuple[str, ...]
    ambiguous_geometry: bool = False


def evaluate_research_lab_radial_evidence(
    *,
    source_frame_sha256: str,
    provenance_valid: bool,
    fresh_successor: bool,
    home_context_visible: bool,
    geometry_anchors: tuple[str, ...],
    ocr_terms: tuple[str, ...],
    nova_target_roi: Box | None,
    ambiguous_geometry: bool = False,
    incompatible_state: bool = False,
    nova_template_accepted: bool = False,
    initial_unprovenanced_composite: bool = False,
) -> ResearchLabRadialEvidence:
    """Require template-bound composite evidence; Hough anchors are never sufficient."""

    anchors = set(geometry_anchors)
    terms = set(ocr_terms)
    supporting: list[str] = []
    missing: list[str] = []
    template_composite = bool(
        nova_template_accepted and "nova" in anchors and nova_target_roi is not None
    )
    compatible_geometry = template_composite
    tap_authority = bool(provenance_valid and fresh_successor)
    initial_authority = bool(
        initial_unprovenanced_composite
        and template_composite
        and not provenance_valid
    )
    if provenance_valid:
        supporting.append("verified_immediately_preceding_research_lab_tap")
    elif initial_authority:
        supporting.append("strong_initial_radial_without_tap_provenance")
    else:
        missing.append("research_lab_tap_provenance")
    if fresh_successor:
        supporting.append("fresh_post_tap_frame")
    elif initial_authority:
        supporting.append("fresh_native_current_frame")
    else:
        missing.append("fresh_post_tap_frame")
    if home_context_visible:
        supporting.append("localized_home_visible_beneath_radial")
    else:
        missing.append("localized_home_context")
    if compatible_geometry:
        supporting.append("compatible_radial_control_arrangement_template")
    else:
        missing.append("compatible_radial_control_arrangement")
    if "research" in terms and len(terms) >= 2:
        supporting.append("compatible_research_lab_ocr")
    else:
        missing.append("compatible_research_lab_ocr")
    if nova_target_roi is not None and not ambiguous_geometry:
        supporting.append("current_frame_nova_target_bound")
    else:
        missing.append(
            "ambiguous_radial_geometry"
            if ambiguous_geometry
            else "current_frame_nova_target"
        )
    if incompatible_state:
        missing.append("incompatible_full_screen_or_modal_state")
    else:
        supporting.append("no_incompatible_full_screen_or_modal_state")
    authority_ok = tap_authority or initial_authority
    confidence = min(
        0.99,
        (0.20 if provenance_valid or initial_authority else 0.0)
        + (0.15 if fresh_successor or initial_authority else 0.0)
        + (0.20 if home_context_visible else 0.0)
        + (0.20 if template_composite else 0.0)
        + (0.10 * min(len(terms), 2))
        + (0.10 if not incompatible_state else 0.0)
        + (0.05 if template_composite else 0.0),
    )
    recognized = bool(
        authority_ok
        and home_context_visible
        and compatible_geometry
        and "research" in terms
        and len(terms) >= 2
        and nova_target_roi is not None
        and not ambiguous_geometry
        and not incompatible_state
        and confidence >= 0.85
    )
    return ResearchLabRadialEvidence(
        semantic_state=NOVA_LAB_MENU if recognized else "UNKNOWN",
        recognized=recognized,
        confidence=confidence,
        supporting_observations=tuple(supporting),
        rejected_or_missing_observations=tuple(missing),
        source_frame_sha256=source_frame_sha256,
        nova_target_roi=nova_target_roi if recognized else None,
        geometry_anchors=tuple(sorted(anchors)),
        ocr_terms=tuple(sorted(terms)),
        ambiguous_geometry=ambiguous_geometry,
    )


def _crop(frame: np.ndarray, box: Box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return frame[y0:y1, x0:x1]


def _text(frame: np.ndarray, box: Box, *, psm: int = 6) -> str:
    crop = cv2.resize(_crop(frame, box), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    value = pytesseract.image_to_string(crop, config=f"--psm {psm}")
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def _ocr_boxes(frame: np.ndarray) -> list[tuple[str, Box]]:
    enlarged = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(enlarged, config="--psm 11", output_type=Output.DICT)
    found: list[tuple[str, Box]] = []
    for index, raw in enumerate(data["text"]):
        text = " ".join(str(raw).casefold().split())
        if not text:
            continue
        x = int(data["left"][index]) // 3
        y = int(data["top"][index]) // 3
        width = max(1, int(data["width"][index]) // 3)
        height = max(1, int(data["height"][index]) // 3)
        found.append((text, (x, y, min(800, x + width), min(1280, y + height))))
    return found


def _gold_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([8, 70, 100], dtype=np.uint8), np.array([42, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(mask)) / float(mask.size)


def _red_ratio(frame: np.ndarray, box: Box) -> float:
    hsv = cv2.cvtColor(_crop(frame, box), cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array([0, 80, 60], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
    high = cv2.inRange(hsv, np.array([165, 80, 60], dtype=np.uint8), np.array([179, 255, 255], dtype=np.uint8))
    return float(cv2.countNonZero(cv2.bitwise_or(low, high))) / float(low.size)


def _attempts(text: str) -> int | None:
    match = _ATTEMPTS_RE.search(text)
    return int(match.group(1)) if match else None


_RADIAL_ANCHOR_OFFSETS: dict[str, tuple[int, int]] = {
    "details": (-223, 94),
    "upgrade": (-185, 130),
    "research": (-9, 52),
    "bioenhancer": (-62, 127),
    "nova": (-32, 143),
}
_RESEARCH_TO_NOVA_OFFSET: tuple[int, int] = (
    _RADIAL_ANCHOR_OFFSETS["nova"][0] - _RADIAL_ANCHOR_OFFSETS["research"][0],
    _RADIAL_ANCHOR_OFFSETS["nova"][1] - _RADIAL_ANCHOR_OFFSETS["research"][1],
)
_HOUGH_SEARCH_ROI: Box = (0, 450, 450, 800)
# Bounded Home radial sector used for initial unprovenanced Nova template search.
_INITIAL_NOVA_RADIAL_SEARCH_ROI: Box = _HOUGH_SEARCH_ROI

_NOVA_TEMPLATE_CACHE: tuple[np.ndarray, str] | None = None
_AUTHORIZED_TEMPLATE_BIND_METHODS = frozenset(
    {
        "template_nova_from_research_tap",
        "template_nova_initial",
    }
)
_AMBIGUOUS_TEMPLATE_BIND_METHODS = frozenset(
    {
        "ambiguous_or_duplicated_template_match",
        "ambiguous_template_pairings",
    }
)


def _hough_radial_circle_candidates(frame: np.ndarray) -> list[tuple[int, int, int]]:
    gray = cv2.medianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 5)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=30,
        param1=100,
        param2=35,
        minRadius=18,
        maxRadius=48,
    )
    if circles is None:
        return []
    x0, y0, x1, y1 = _HOUGH_SEARCH_ROI
    return [
        (int(round(x)), int(round(y)), int(round(radius)))
        for x, y, radius in circles[0]
        if x0 < x < x1 and y0 < y < y1
    ]


def _load_nova_radial_template() -> tuple[np.ndarray | None, dict[str, object]]:
    global _NOVA_TEMPLATE_CACHE
    diagnostics: dict[str, object] = {
        "template_path": str(NOVA_RADIAL_TEMPLATE_PATH),
        "manifest_path": str(NOVA_RADIAL_TEMPLATE_MANIFEST_PATH),
        "provenance_valid": False,
    }
    if not NOVA_RADIAL_TEMPLATE_PATH.is_file() or not NOVA_RADIAL_TEMPLATE_MANIFEST_PATH.is_file():
        diagnostics["reject_reason"] = "missing_template_or_manifest"
        return None, diagnostics
    raw = NOVA_RADIAL_TEMPLATE_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(
            NOVA_RADIAL_TEMPLATE_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        entry = next(
            item
            for item in manifest.get("templates", [])
            if item.get("id") == "nova-radial-portrait"
        )
    except (OSError, StopIteration, TypeError, ValueError, KeyError):
        diagnostics["reject_reason"] = "stale_or_invalid_template_provenance"
        return None, diagnostics
    if entry.get("file_sha256") != digest:
        diagnostics["reject_reason"] = "stale_or_invalid_template_provenance"
        return None, diagnostics
    if entry.get("runtime_profile") != "native-800x1280":
        diagnostics["reject_reason"] = "incompatible_runtime_profile"
        return None, diagnostics
    if _NOVA_TEMPLATE_CACHE is not None and _NOVA_TEMPLATE_CACHE[1] == digest:
        template = _NOVA_TEMPLATE_CACHE[0]
    else:
        decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.size == 0:
            diagnostics["reject_reason"] = "template_decode_failed"
            return None, diagnostics
        _NOVA_TEMPLATE_CACHE = (decoded, digest)
        template = decoded
    diagnostics.update(
        {
            "provenance_valid": True,
            "template_sha256": digest,
            "source_path": entry.get("source", {}).get("path"),
            "source_sha256": entry.get("source", {}).get("file_sha256"),
            "source_crop_xyxy": entry.get("source", {}).get("crop_xyxy"),
            "intended_visual_variant": entry.get("intended_visual_variant"),
            "runtime_profile": entry.get("runtime_profile"),
        }
    )
    return template, diagnostics


def _research_lab_radial_geometry(
    frame: np.ndarray,
    provenance: ResearchLabTapProvenance | None,
) -> tuple[tuple[str, ...], Box | None, bool, dict[str, object]]:
    candidates = _hough_radial_circle_candidates(frame)
    inferred_ambiguous = False
    tap_x = tap_y = None
    if provenance is not None:
        x0, y0, x1, y1 = provenance.target_roi
        tap_x, tap_y = (x0 + x1) // 2, (y0 + y1) // 2
    else:
        origins: list[tuple[int, int, int]] = []
        for _identity, (dx, dy) in _RADIAL_ANCHOR_OFFSETS.items():
            for x, y, _radius in candidates:
                origin_x, origin_y = x - dx, y - dy
                score = sum(
                    any(
                        (candidate_x - (origin_x + anchor_dx)) ** 2
                        + (candidate_y - (origin_y + anchor_dy)) ** 2
                        <= 25**2
                        for candidate_x, candidate_y, _candidate_radius in candidates
                    )
                    for anchor_dx, anchor_dy in _RADIAL_ANCHOR_OFFSETS.values()
                )
                origins.append((score, origin_x, origin_y))
        origins.sort(reverse=True)
        if not origins or origins[0][0] < 4:
            diagnostics = {
                "method": "hough_circles",
                "hough_anchors": (),
                "hough_nova_roi": None,
                "hough_ambiguous": False,
                "hough_candidate_count": len(candidates),
                "hough_candidates": candidates,
                "search_roi": _HOUGH_SEARCH_ROI,
            }
            return (), None, False, diagnostics
        best_score, tap_x, tap_y = origins[0]
        inferred_ambiguous = any(
            score == best_score
            and (origin_x - tap_x) ** 2 + (origin_y - tap_y) ** 2 > 25**2
            for score, origin_x, origin_y in origins[1:]
        )
    matches: dict[str, tuple[int, int, int]] = {}
    ambiguous = inferred_ambiguous
    for identity, (dx, dy) in _RADIAL_ANCHOR_OFFSETS.items():
        expected_x, expected_y = tap_x + dx, tap_y + dy
        ranked = sorted(
            (
                ((x - expected_x) ** 2 + (y - expected_y) ** 2, (x, y, radius))
                for x, y, radius in candidates
                if (x - expected_x) ** 2 + (y - expected_y) ** 2 <= 25**2
            ),
            key=lambda item: item[0],
        )
        if ranked:
            matches[identity] = ranked[0][1]
            if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < 6**2:
                ambiguous = True
    hough_target = None
    if provenance is not None and "nova" in matches and not ambiguous:
        x, y, _radius = matches["nova"]
        hough_target = (
            max(0, x - 22),
            max(0, y - 22),
            min(800, x + 22),
            min(1280, y + 22),
        )
    anchors = tuple(sorted(matches))
    diagnostics = {
        "method": "hough_circles",
        "hough_anchors": anchors,
        "hough_nova_roi": hough_target,
        "hough_ambiguous": ambiguous,
        "hough_candidate_count": len(candidates),
        "hough_candidates": candidates,
        "search_roi": _HOUGH_SEARCH_ROI,
        "tap_point": (tap_x, tap_y),
    }
    return anchors, hough_target, ambiguous, diagnostics


def _boxes_overlap(left: Box, right: Box) -> bool:
    return not (
        left[2] <= right[0]
        or right[2] <= left[0]
        or left[3] <= right[1]
        or right[3] <= left[1]
    )


def _template_match_in_search_roi(
    frame: np.ndarray,
    template: np.ndarray,
    search_roi: Box,
) -> dict[str, object] | None:
    sx0, sy0, sx1, sy1 = search_roi
    search = frame[sy0:sy1, sx0:sx1]
    if search.size == 0:
        return None
    ranked: list[tuple[float, float, float, Box]] = []
    for scale in NOVA_TEMPLATE_SCALES:
        height = max(8, int(round(template.shape[0] * scale)))
        width = max(8, int(round(template.shape[1] * scale)))
        if search.shape[0] < height or search.shape[1] < width:
            continue
        scaled = cv2.resize(
            template,
            (width, height),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
        )
        response = cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(response)
        suppressed = response.copy()
        mx, my = max_loc
        suppressed[
            max(0, my - height // 2) : my + height // 2 + 1,
            max(0, mx - width // 2) : mx + width // 2 + 1,
        ] = -1.0
        _min_val2, second_val, _min_loc2, _max_loc2 = cv2.minMaxLoc(suppressed)
        match_roi = (
            sx0 + mx,
            sy0 + my,
            sx0 + mx + width,
            sy0 + my + height,
        )
        ranked.append((float(max_val), float(max_val - second_val), float(scale), match_roi))
    if not ranked:
        return None
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    best_score, best_margin, best_scale, best_roi = ranked[0]
    overlapping_peers = [
        item for item in ranked[1:] if _boxes_overlap(best_roi, item[3])
    ]
    spatially_distinct = [
        item for item in ranked[1:] if not _boxes_overlap(best_roi, item[3])
    ]
    competing_margin = best_margin
    if spatially_distinct:
        competing_margin = min(
            competing_margin,
            best_score - spatially_distinct[0][0],
        )
    strong_distinct = [
        item for item in spatially_distinct if item[0] >= NOVA_TEMPLATE_MIN_SCORE
    ]
    return {
        "score": best_score,
        "margin": competing_margin,
        "scale": best_scale,
        "match_roi": best_roi,
        "overlapping_peer_count": len(overlapping_peers),
        "spatially_distinct_strong_count": len(strong_distinct),
        "ambiguous_within_sector": bool(strong_distinct)
        or competing_margin < NOVA_TEMPLATE_MIN_MARGIN,
    }


def _nova_sector_search_roi(expected_x: int, expected_y: int) -> Box:
    pad = NOVA_TEMPLATE_SEARCH_PAD_PX
    return (
        max(0, expected_x - pad),
        max(0, expected_y - pad),
        min(PROFILE_SIZE[0], expected_x + pad),
        min(PROFILE_SIZE[1], expected_y + pad),
    )


def _finalize_template_match(
    diagnostics: dict[str, object],
    *,
    score: float,
    margin: float,
    scale: float,
    match_roi: Box,
    search_roi: Box,
    overlapping_peer_count: int,
    spatially_distinct_strong_count: int,
    ambiguous_within_sector: bool,
) -> dict[str, object]:
    diagnostics.update(
        {
            "score": score,
            "margin": margin,
            "scale": scale,
            "match_roi": match_roi,
            "search_roi": search_roi,
            "overlapping_peer_count": overlapping_peer_count,
            "spatially_distinct_strong_count": spatially_distinct_strong_count,
        }
    )
    bx0, by0, bx1, by1 = match_roi
    if (
        bx0 <= NOVA_TEMPLATE_EDGE_CLIP_PX
        or by0 <= NOVA_TEMPLATE_EDGE_CLIP_PX
        or bx1 >= PROFILE_SIZE[0] - NOVA_TEMPLATE_EDGE_CLIP_PX
        or by1 >= PROFILE_SIZE[1] - NOVA_TEMPLATE_EDGE_CLIP_PX
    ):
        diagnostics["reject_reason"] = "clipped_or_partial_template_match"
        return diagnostics
    if score < NOVA_TEMPLATE_MIN_SCORE:
        diagnostics["reject_reason"] = "weak_template_match"
        return diagnostics
    if ambiguous_within_sector:
        diagnostics["reject_reason"] = "ambiguous_or_duplicated_template_match"
        return diagnostics
    diagnostics["accepted"] = True
    diagnostics["reject_reason"] = None
    return diagnostics


def _match_nova_radial_template(
    frame: np.ndarray,
    provenance: ResearchLabTapProvenance | None,
    *,
    research_circle_candidates: tuple[tuple[int, int, int], ...] | None = None,
) -> dict[str, object]:
    """Match the checked-in Nova crop; research_circle_candidates are ignored (diagnostics only)."""

    del research_circle_candidates  # Hough seeding is not authorizing.
    template, provenance_diag = _load_nova_radial_template()
    diagnostics: dict[str, object] = {
        "method": NOVA_TEMPLATE_MATCH_METHOD,
        "accepted": False,
        "score": None,
        "margin": None,
        "scale": None,
        "search_roi": None,
        "match_roi": None,
        "reject_reason": None,
        "template": provenance_diag,
        "min_score": NOVA_TEMPLATE_MIN_SCORE,
        "min_margin": NOVA_TEMPLATE_MIN_MARGIN,
        "scales": list(NOVA_TEMPLATE_SCALES),
        "research_candidate_count": 0,
        "accepted_pairing_count": 0,
        "winning_research_circle": None,
    }
    if template is None:
        diagnostics["reject_reason"] = provenance_diag.get("reject_reason") or "missing_template"
        return diagnostics
    if provenance is not None:
        x0, y0, x1, y1 = provenance.target_roi
        tap_x, tap_y = (x0 + x1) // 2, (y0 + y1) // 2
        expected_dx, expected_dy = _RADIAL_ANCHOR_OFFSETS["nova"]
        expected_x, expected_y = tap_x + expected_dx, tap_y + expected_dy
        search_roi = _nova_sector_search_roi(expected_x, expected_y)
        match = _template_match_in_search_roi(frame, template, search_roi)
        if match is None:
            diagnostics["search_roi"] = search_roi
            diagnostics["reject_reason"] = "no_template_response_in_nova_sector"
            return diagnostics
        return _finalize_template_match(
            diagnostics,
            score=float(match["score"]),
            margin=float(match["margin"]),
            scale=float(match["scale"]),
            match_roi=match["match_roi"],  # type: ignore[arg-type]
            search_roi=search_roi,
            overlapping_peer_count=int(match["overlapping_peer_count"]),
            spatially_distinct_strong_count=int(match["spatially_distinct_strong_count"]),
            ambiguous_within_sector=bool(match["ambiguous_within_sector"]),
        )

    # Initial already-open radial: unique strong match inside the known radial sector.
    search_roi = _INITIAL_NOVA_RADIAL_SEARCH_ROI
    match = _template_match_in_search_roi(frame, template, search_roi)
    if match is None:
        diagnostics["search_roi"] = search_roi
        diagnostics["reject_reason"] = "no_template_response_in_radial_region"
        return diagnostics
    return _finalize_template_match(
        diagnostics,
        score=float(match["score"]),
        margin=float(match["margin"]),
        scale=float(match["scale"]),
        match_roi=match["match_roi"],  # type: ignore[arg-type]
        search_roi=search_roi,
        overlapping_peer_count=int(match["overlapping_peer_count"]),
        spatially_distinct_strong_count=int(match["spatially_distinct_strong_count"]),
        ambiguous_within_sector=bool(match["ambiguous_within_sector"]),
    )


def _radial_ocr_terms(text: str) -> tuple[str, ...]:
    normalized = text.replace("researgh", "research")
    return tuple(
        term
        for term in ("research", "bioenhancer", "nova", "details", "upgrade")
        if term in normalized
    )


def recognize_nova_frame(
    frame: np.ndarray,
    *,
    captured_monotonic: float | None = None,
    stale: bool = False,
    research_lab_tap_provenance: ResearchLabTapProvenance | None = None,
    home_context_visible: bool = False,
    incompatible_state: bool = False,
) -> NovaFrameRecognition:
    if frame is None or frame.shape[:2] != (PROFILE_SIZE[1], PROFILE_SIZE[0]):
        raise ValueError("Nova frame must be a native 800x1280 image")
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    header = _text(frame, NOVA_HEADER_ROI, psm=11)
    menu_text = _text(frame, LAB_MENU_ROI)
    nova_text = _text(frame, NOVA_BODY_ROI)
    attempts_text = _text(frame, NOVA_ATTEMPTS_ROI)
    cooldown_text = _text(frame, NOVA_COOLDOWN_ROI)
    diagnostics: dict[str, object] = {
        "header_text": header,
        "menu_text": menu_text,
        "nova_text": nova_text,
        "attempts_text": attempts_text,
        "cooldown_text": cooldown_text,
        "lab_gold_ratio": _gold_ratio(frame, RESEARCH_LAB_ROI),
        "praise_red_ratio": _red_ratio(frame, NOVA_PRAISE_ROI),
    }
    is_research_lab_upgrade = bool(
        ("nova" in nova_text or "ova mil" in nova_text)
        and "mil. pt cost" in nova_text
        and "ecn. pt cost" in nova_text
        and "materials required" in nova_text
        and "upgrade" in attempts_text
    )
    diagnostics["research_lab_upgrade_screen"] = is_research_lab_upgrade
    if is_research_lab_upgrade:
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=RESEARCH_LAB_UPGRADE_SCREEN,
                research_lab_identity=True,
                nova_control_visible=False,
                selected_nova=False,
                praise_enabled=False,
                praise_target_identity="",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=None,
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=True,
            ),
            digest,
            (),
            diagnostics,
        )
    is_nova = "nova" in header and ("skill" in nova_text or "praise" in nova_text or "interaction" in attempts_text)
    if is_nova:
        remaining = _attempts(attempts_text)
        cooldown_seconds = parse_cooldown_seconds(cooldown_text)
        praise_label = "praise" in _text(frame, NOVA_PRAISE_ROI)
        enabled = praise_label and _red_ratio(frame, NOVA_PRAISE_ROI) >= 0.08 and cooldown_seconds in (None, 0)
        targets = ((NOVA_PRAISE_TARGET, NOVA_PRAISE_ROI),) if enabled else ()
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_SCREEN,
                research_lab_identity=True,
                nova_control_visible=False,
                selected_nova=True,
                praise_enabled=enabled,
                praise_target_identity=NOVA_PRAISE_TARGET if praise_label else "",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=remaining,
                cooldown_text=cooldown_text,
                cooldown_active=bool(cooldown_seconds and cooldown_seconds > 0),
                cooldown_seconds=cooldown_seconds,
                next_eligible_at=(
                    captured_monotonic + cooldown_seconds
                    if captured_monotonic is not None and cooldown_seconds and cooldown_seconds > 0
                    else None
                ),
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=remaining is not None and praise_label,
            ),
            digest,
            targets,
            diagnostics,
        )
    hough_anchors, hough_target, hough_ambiguous, hough_diag = _research_lab_radial_geometry(
        frame,
        research_lab_tap_provenance,
    )
    # Hough remains diagnostics-only; it never authorizes bind or recognition.
    template_diag = _match_nova_radial_template(frame, research_lab_tap_provenance)
    diagnostics["research_lab_radial_hough"] = hough_diag
    diagnostics["nova_radial_template"] = template_diag
    template_accepted = bool(template_diag.get("accepted"))
    template_roi = template_diag.get("match_roi") if template_accepted else None
    if (
        isinstance(template_roi, tuple)
        and len(template_roi) == 4
        and all(isinstance(value, int) for value in template_roi)
    ):
        pass
    else:
        template_roi = None
    nova_target_roi = None
    # Template ambiguity may fail-closed as radial-like; Hough ambiguity alone may not.
    ambiguous_geometry = False
    bind_method = "none"
    geometry_anchors: tuple[str, ...] = ()
    if template_accepted and template_roi is not None and research_lab_tap_provenance is not None:
        nova_target_roi = template_roi
        geometry_anchors = ("nova",)
        bind_method = "template_nova_from_research_tap"
    elif (
        template_accepted
        and template_roi is not None
        and research_lab_tap_provenance is None
        and not stale
        and captured_monotonic is not None
    ):
        nova_target_roi = template_roi
        geometry_anchors = ("nova",)
        bind_method = "template_nova_initial"
    elif template_diag.get("reject_reason") in _AMBIGUOUS_TEMPLATE_BIND_METHODS:
        ambiguous_geometry = True
        bind_method = str(template_diag.get("reject_reason"))
    provenance_valid = bool(
        research_lab_tap_provenance is not None
        and research_lab_tap_provenance.target_identity
        == "home.building.research_lab"
        and research_lab_tap_provenance.action_key
        and research_lab_tap_provenance.source_frame_sha256
    )
    fresh_successor = bool(
        research_lab_tap_provenance is not None
        and captured_monotonic is not None
        and not stale
        and captured_monotonic > research_lab_tap_provenance.dispatched_monotonic
        and captured_monotonic - research_lab_tap_provenance.dispatched_monotonic <= 30.0
    )
    initial_unprovenanced_composite = bool(
        research_lab_tap_provenance is None
        and not stale
        and captured_monotonic is not None
        and bind_method == "template_nova_initial"
        and template_accepted
        and nova_target_roi is not None
    )
    radial = evaluate_research_lab_radial_evidence(
        source_frame_sha256=digest,
        provenance_valid=provenance_valid,
        fresh_successor=fresh_successor,
        home_context_visible=home_context_visible,
        geometry_anchors=geometry_anchors,
        ocr_terms=_radial_ocr_terms(f"{menu_text} {nova_text}"),
        nova_target_roi=nova_target_roi,
        ambiguous_geometry=ambiguous_geometry,
        incompatible_state=incompatible_state or is_nova,
        nova_template_accepted=template_accepted
        and bind_method in _AUTHORIZED_TEMPLATE_BIND_METHODS,
        initial_unprovenanced_composite=initial_unprovenanced_composite,
    )
    radial_diag = asdict(radial)
    radial_diag["bind_method"] = bind_method
    radial_diag["hough_only_anchors"] = hough_diag.get("hough_anchors") or hough_anchors
    radial_diag["hough_only_nova_roi"] = hough_diag.get("hough_nova_roi")
    radial_diag["hough_search_roi"] = hough_diag.get("search_roi")
    radial_diag["hough_ambiguous"] = hough_ambiguous
    radial_diag["hough_target_ignored"] = hough_target
    radial_diag["template_score"] = template_diag.get("score")
    radial_diag["template_margin"] = template_diag.get("margin")
    radial_diag["template_scale"] = template_diag.get("scale")
    radial_diag["template_search_roi"] = template_diag.get("search_roi")
    radial_diag["template_match_roi"] = template_diag.get("match_roi")
    radial_diag["template_method"] = template_diag.get("method")
    radial_diag["winning_research_circle"] = template_diag.get("winning_research_circle")
    radial_diag["initial_unprovenanced_composite"] = initial_unprovenanced_composite
    diagnostics["research_lab_radial"] = radial_diag
    if radial.recognized and radial.nova_target_roi is not None:
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_LAB_MENU,
                research_lab_identity=True,
                nova_control_visible=True,
                selected_nova=False,
                praise_enabled=False,
                praise_target_identity="",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=None,
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=True,
            ),
            digest,
            ((NOVA_INTERACTION_TARGET, radial.nova_target_roi),),
            diagnostics,
        )
    home_text = _text(frame, (0, 0, 800, 1280), psm=11)
    if "research lab" in home_text:
        return NovaFrameRecognition(
            NovaPraiseObservation(
                screen_state=NOVA_HOME,
                research_lab_identity=True,
                nova_control_visible=False,
                selected_nova=False,
                praise_enabled=False,
                praise_target_identity="",
                praise_target_roi=NOVA_PRAISE_ROI,
                attempts_remaining=None,
                frame_sha256=digest,
                captured_monotonic=captured_monotonic,
                stale=stale,
                recognized=True,
            ),
            digest,
            (("research-lab-building", RESEARCH_LAB_ROI),),
            diagnostics,
        )
    return NovaFrameRecognition(
        NovaPraiseObservation(
            screen_state="UNKNOWN",
            research_lab_identity=False,
            nova_control_visible=False,
            selected_nova=False,
            praise_enabled=False,
            praise_target_identity="",
            praise_target_roi=NOVA_PRAISE_ROI,
            attempts_remaining=None,
            frame_sha256=digest,
            captured_monotonic=captured_monotonic,
            stale=stale,
            recognized=False,
        ),
        digest,
        (),
        diagnostics,
    )
