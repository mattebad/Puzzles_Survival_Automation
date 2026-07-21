"""Native 800x1280 OCR/color recognition for the Research Lab Nova route."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
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
) -> ResearchLabRadialEvidence:
    """Require composite current-frame evidence; OCR alone is never sufficient."""

    anchors = set(geometry_anchors)
    terms = set(ocr_terms)
    supporting: list[str] = []
    missing: list[str] = []
    if provenance_valid:
        supporting.append("verified_immediately_preceding_research_lab_tap")
    else:
        missing.append("research_lab_tap_provenance")
    if fresh_successor:
        supporting.append("fresh_post_tap_frame")
    else:
        missing.append("fresh_post_tap_frame")
    if home_context_visible:
        supporting.append("localized_home_visible_beneath_radial")
    else:
        missing.append("localized_home_context")
    if {"research", "nova"}.issubset(anchors) and len(anchors) >= 4:
        supporting.append("compatible_radial_control_arrangement")
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
    confidence = min(
        0.99,
        (0.20 if provenance_valid else 0.0)
        + (0.15 if fresh_successor else 0.0)
        + (0.20 if home_context_visible else 0.0)
        + (0.05 * min(len(anchors), 5))
        + (0.10 * min(len(terms), 2))
        + (0.10 if not incompatible_state else 0.0),
    )
    recognized = bool(
        provenance_valid
        and fresh_successor
        and home_context_visible
        and {"research", "nova"}.issubset(anchors)
        and len(anchors) >= 4
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
    "nova": (-121, 134),
}


def _research_lab_radial_geometry(
    frame: np.ndarray,
    provenance: ResearchLabTapProvenance | None,
) -> tuple[tuple[str, ...], Box | None, bool]:
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
    candidates = []
    if circles is not None:
        candidates = [
            (int(round(x)), int(round(y)), int(round(radius)))
            for x, y, radius in circles[0]
            if 0 < x < 450 and 450 < y < 800
        ]
    inferred_ambiguous = False
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
            return (), None, False
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
    target = None
    if provenance is not None and "nova" in matches and not ambiguous:
        x, y, _radius = matches["nova"]
        target = (
            max(0, x - 22),
            max(0, y - 22),
            min(800, x + 22),
            min(1280, y + 22),
        )
    return tuple(sorted(matches)), target, ambiguous


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
    radial_geometry = _research_lab_radial_geometry(
        frame,
        research_lab_tap_provenance,
    )
    radial = evaluate_research_lab_radial_evidence(
        source_frame_sha256=digest,
        provenance_valid=bool(
            research_lab_tap_provenance is not None
            and research_lab_tap_provenance.target_identity
            == "home.building.research_lab"
            and research_lab_tap_provenance.action_key
            and research_lab_tap_provenance.source_frame_sha256
        ),
        fresh_successor=bool(
            research_lab_tap_provenance is not None
            and captured_monotonic is not None
            and not stale
            and captured_monotonic > research_lab_tap_provenance.dispatched_monotonic
            and captured_monotonic - research_lab_tap_provenance.dispatched_monotonic <= 30.0
        ),
        home_context_visible=home_context_visible,
        geometry_anchors=radial_geometry[0],
        ocr_terms=_radial_ocr_terms(f"{menu_text} {nova_text}"),
        nova_target_roi=radial_geometry[1],
        ambiguous_geometry=radial_geometry[2],
        incompatible_state=incompatible_state or is_nova,
    )
    diagnostics["research_lab_radial"] = asdict(radial)
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
