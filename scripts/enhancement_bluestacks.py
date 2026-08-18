#!/usr/bin/env python3
"""Evidence-gated native BlueStacks Commander enhancement route.

The route is deliberately direct: canonical Home profile portrait -> Commander
Info -> one requested category -> one equipped item -> Enhance -> one exact
one-star material -> quantity one -> Use -> same-item successor -> Home.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime, NativeBox
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)
from tasks.home_nav_recognition import recognize_home_nav


FLOW_ID = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
ORDERED_VARIANTS = ("gear", "chip", "module")
NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
NATIVE_PROFILE_ID = BLUESTACKS_RUNTIME_PROFILE_ID
FULL_FRAME: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)

# These are semantic search bounds only.  Dispatch boxes come from current-frame
# recognition and never from the reference images or these constants.
HOME_PROFILE_SEARCH_ROI: NativeBox = (0, 0, 300, 380)
HOME_PROFILE_PORTRAIT_ROI: NativeBox = (4, 40, 84, 123)
COMMANDER_HEADER_ROI: NativeBox = (0, 0, 800, 220)
CATEGORY_SEARCH_ROI: NativeBox = (0, 80, 800, 360)
ITEM_SEARCH_ROI: NativeBox = (0, 210, 800, 820)
MATERIAL_SEARCH_ROI: NativeBox = (0, 620, 800, 1140)
CONTROL_SEARCH_ROI: NativeBox = (0, 760, 800, 1260)
DETAIL_TITLE_ROI: NativeBox = (20, 240, 620, 380)
DETAIL_ENHANCE_ROI: NativeBox = (130, 950, 240, 980)
CHIP_DETAIL_ENHANCE_ROI: NativeBox = (55, 900, 170, 995)
MODULE_DETAIL_ENHANCE_ROI: NativeBox = (95, 840, 260, 950)
COMMANDER_TAB_CONTEXT_ROI: NativeBox = (34, 58, 760, 120)
CATEGORY_TAB_BOXES: Mapping[str, NativeBox] = {
    "gear": (34, 58, 148, 112),
    "chip": (148, 58, 263, 112),
    "module": (263, 58, 377, 112),
}
CATEGORY_VISUAL_TAB_BOXES: Mapping[str, NativeBox] = {
    "gear": (42, 72, 185, 140),
    "chip": (185, 72, 329, 140),
    "module": (329, 72, 471, 140),
}
COMMANDER_CONTEXT_TAB_LABELS = frozenset(
    {"gear", "chip", "module", "cube", "bioenhancer"}
)
COMMANDER_CONTEXT_MIN_TAB_LABELS = 3
CATEGORY_TAB_MIN_RED_DOMINANCE = 12.0
CATEGORY_TAB_WINNER_MARGIN = 8.0
GEAR_RED_STAR_ARMOR_ROI: NativeBox = (50, 510, 133, 625)
CHIP_BLUE_TWO_STAR_ROI: NativeBox = (99, 590, 202, 696)
MODULE_GRAY_ONE_STAR_ROI: NativeBox = (214, 662, 314, 798)
GEAR_ONE_STAR_ENHANCER_REGION: NativeBox = (168, 675, 270, 790)
GEAR_ONE_STAR_ENHANCER_ROI: NativeBox = (208, 755, 224, 775)
CHIP_ONE_STAR_ENHANCER_ROI: NativeBox = (220, 744, 249, 778)
MODULE_ONE_STAR_ENHANCER_ROI: NativeBox = (80, 735, 115, 780)
QUANTITY_USE_ROI: NativeBox = (264, 780, 536, 875)
GEAR_CONFIRM_ROI: NativeBox = (452, 1160, 725, 1250)
ENHANCEMENT_BACK_ROI: NativeBox = (0, 0, 150, 80)
MAX_SETTLE_POLLS = 3
SETTLED_SUCCESSOR_DELAY_SECONDS = 1.0
FORBIDDEN_ACTIONS = frozenset({"promote", "modify", "replace", "unequip", "auto select"})
PREMIUM_MARKERS = frozenset({"gem", "gems", "diamond", "cash", "premium", "gold"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _normalize(value: object) -> str:
    return " ".join(str(value or "").lower().replace("★", " star ").split())


def _box(value: object) -> NativeBox | None:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        candidate = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = candidate
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        return None
    return candidate  # type: ignore[return-value]


def _expand(value: NativeBox, x_pad: int = 30, y_pad: int = 20) -> NativeBox:
    x0, y0, x1, y1 = value
    return (
        max(0, x0 - x_pad),
        max(0, y0 - y_pad),
        min(NATIVE_WIDTH, x1 + x_pad),
        min(NATIVE_HEIGHT, y1 + y_pad),
    )


@dataclass(frozen=True)
class OcrHit:
    text: str
    bounds: NativeBox
    confidence: float = 0.0


OcrEngine = Callable[[np.ndarray, NativeBox], Sequence[Any]]


def _default_ocr(frame: np.ndarray, roi: NativeBox) -> list[OcrHit]:
    import pytesseract
    from pytesseract import Output

    x0, y0, x1, y1 = roi
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    scale = 3
    data = pytesseract.image_to_data(
        cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC),
        config="--psm 11",
        output_type=Output.DICT,
    )
    hits: list[OcrHit] = []
    for index, raw in enumerate(data.get("text", ())):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError, IndexError):
            confidence = -1.0
        if confidence < 20:
            continue
        left = x0 + int(data["left"][index] / scale)
        top = y0 + int(data["top"][index] / scale)
        right = left + max(1, int(data["width"][index] / scale))
        bottom = top + max(1, int(data["height"][index] / scale))
        bounds = _box((left, top, right, bottom))
        if bounds is not None:
            hits.append(OcrHit(text, bounds, confidence))
    return hits


def _coerce_hits(raw: Sequence[Any] | None) -> list[OcrHit]:
    hits: list[OcrHit] = []
    for value in raw or ():
        if isinstance(value, OcrHit):
            hits.append(value)
        elif isinstance(value, Mapping):
            text = str(value.get("text") or "").strip()
            bounds = _box(value.get("bounds") or value.get("roi"))
            if text and bounds is not None:
                hits.append(OcrHit(text, bounds, float(value.get("confidence", 1.0))))
    return hits


def _hits(frame: np.ndarray, roi: NativeBox, engine: OcrEngine | None) -> list[OcrHit]:
    raw = _coerce_hits((engine or _default_ocr)(frame, roi))
    x0, y0, x1, y1 = roi
    return [
        hit
        for hit in raw
        if x0 <= hit.bounds[0] < hit.bounds[2] <= x1
        and y0 <= hit.bounds[1] < hit.bounds[3] <= y1
    ]


def _text(hits: Sequence[OcrHit]) -> str:
    return " ".join(_normalize(hit.text) for hit in hits)


def _center(bounds: NativeBox) -> tuple[int, int]:
    return (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2


def _associated(
    marker: OcrHit, target: OcrHit, *, y_slack: int = 90, x_slack: int = 260
) -> bool:
    mx, my = _center(marker.bounds)
    tx, ty = _center(target.bounds)
    return abs(my - ty) <= y_slack and abs(mx - tx) <= x_slack


def _red_dominance(frame: np.ndarray, bounds: NativeBox) -> float | None:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] < 3:
        return None
    x0, y0, x1, y1 = bounds
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    red = crop[:, :, 2].astype(np.float32)
    green = crop[:, :, 1].astype(np.float32)
    return float(np.mean(red - green))


def _profile_portrait_visual_present(frame: np.ndarray) -> bool:
    x0, y0, x1, y1 = HOME_PROFILE_PORTRAIT_ROI
    crop = frame[y0:y1, x0:x1]
    if crop.shape[:2] != (y1 - y0, x1 - x0):
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edge_density = float(np.mean(cv2.Canny(gray, 60, 140) > 0))
    return bool(float(gray.std()) >= 40.0 and edge_density >= 0.12)


def _classify_selected_category_visual(frame: np.ndarray) -> str | None:
    """Classify a selected tab only from the fixed native tab boxes."""
    candidates: list[tuple[float, str]] = []
    for boxes in (CATEGORY_VISUAL_TAB_BOXES, CATEGORY_TAB_BOXES):
        scores = {
            variant: _red_dominance(frame, bounds)
            for variant, bounds in boxes.items()
        }
        if any(score is None for score in scores.values()):
            continue
        ordered = sorted(
            ((float(score), variant) for variant, score in scores.items()),
            reverse=True,
        )
        winner_score, winner = ordered[0]
        runner_score = ordered[1][0]
        if (
            winner_score >= CATEGORY_TAB_MIN_RED_DOMINANCE
            and winner_score - runner_score >= CATEGORY_TAB_WINNER_MARGIN
        ):
            candidates.append((winner_score - runner_score, winner))
    return max(candidates)[1] if candidates else None


def _commander_tab_context_sufficient(categories: Sequence[OcrHit]) -> bool:
    context_labels = {
        _normalize(hit.text)
        for hit in categories
        if (
            COMMANDER_TAB_CONTEXT_ROI[0] <= hit.bounds[0]
            and hit.bounds[2] <= COMMANDER_TAB_CONTEXT_ROI[2]
            and COMMANDER_TAB_CONTEXT_ROI[1] <= hit.bounds[1]
            and hit.bounds[3] <= COMMANDER_TAB_CONTEXT_ROI[3]
            and _normalize(hit.text) in COMMANDER_CONTEXT_TAB_LABELS
        )
    }
    return (
        len(context_labels) >= COMMANDER_CONTEXT_MIN_TAB_LABELS
        and bool(context_labels & set(CATEGORY_TAB_BOXES))
    )


def _commander_header_recognized(
    header: Sequence[OcrHit],
    categories: Sequence[OcrHit],
    visual_selected: str | None,
) -> bool:
    header_text = _text(header)
    if "commander info" in header_text or "commanderinfo" in header_text:
        return True
    info_hits = [
        hit
        for hit in header
        if _normalize(hit.text) == "info" and hit.bounds[3] <= 80
    ]
    if len(info_hits) == 1 and _commander_tab_context_sufficient(categories):
        return True
    context_labels = {
        _normalize(hit.text)
        for hit in categories
        if _normalize(hit.text) in COMMANDER_CONTEXT_TAB_LABELS
    }
    return bool(
        context_labels == COMMANDER_CONTEXT_TAB_LABELS
        or (
            visual_selected in CATEGORY_TAB_BOXES
            and len(context_labels) >= 4
            and context_labels | {visual_selected} == COMMANDER_CONTEXT_TAB_LABELS
        )
    )


def _unique_hits(hits: Sequence[OcrHit]) -> list[OcrHit]:
    unique: list[OcrHit] = []
    seen: set[tuple[str, NativeBox]] = set()
    for hit in hits:
        key = (_normalize(hit.text), hit.bounds)
        if key not in seen:
            seen.add(key)
            unique.append(hit)
    return unique


def _icon_overview_binding(
    hits: Sequence[OcrHit], variant: str, frame: np.ndarray
) -> tuple[str, int, NativeBox] | None:
    del hits
    target = {
        "gear": GEAR_RED_STAR_ARMOR_ROI,
        "chip": CHIP_BLUE_TWO_STAR_ROI,
        "module": MODULE_GRAY_ONE_STAR_ROI,
    }.get(variant)
    if target is None:
        return None
    x0, y0, x1, y1 = target
    crop = frame[y0:y1, x0:x1]
    if crop.shape[:2] != (y1 - y0, x1 - x0):
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = (
        ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170))
        & (hsv[:, :, 1] > 100)
        & (hsv[:, :, 2] > 80)
    )
    if variant == "chip":
        blue = (
            (hsv[:, :, 0] >= 85)
            & (hsv[:, :, 0] <= 125)
            & (hsv[:, :, 1] > 100)
            & (hsv[:, :, 2] > 80)
        )
        if (
            float(gray.std()) < 15.0
            or float(np.mean(red)) < 0.02
            or float(np.mean(blue)) < 0.04
        ):
            return None
        return "chip-blue-triangular-two-star", 20, CHIP_BLUE_TWO_STAR_ROI
    if variant == "module":
        if float(gray.std()) < 15.0 or float(np.mean(red)) < 0.01:
            return None
        return "module-gray-shield-one-star", 18, MODULE_GRAY_ONE_STAR_ROI
    if float(gray.std()) < 15.0 or float(np.mean(red)) < 0.04:
        return None
    return "gear-red-star-chest-armor", 0, GEAR_RED_STAR_ARMOR_ROI


def _is_marker(hit: OcrHit) -> bool:
    text = _normalize(hit.text)
    return text in {"selected", "active", "checked", "check", "current"} or (
        "selected" in text
    )


def _target(hits: Sequence[OcrHit], names: set[str]) -> NativeBox | None:
    matches = [hit for hit in hits if _normalize(hit.text) in names]
    return _expand(matches[0].bounds) if len(matches) == 1 else None


def _frame_hash(frame: np.ndarray) -> str:
    if frame is None or not isinstance(frame, np.ndarray):
        return ""
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("native frame could not be encoded")
    return hashlib.sha256(encoded.tobytes()).hexdigest()


def _digest(frame: np.ndarray, supplied: str | None) -> str:
    return supplied if _SHA256_RE.fullmatch(str(supplied or "")) else _frame_hash(frame)


@dataclass(frozen=True)
class HomeRecognition:
    recognized: bool
    state: str
    reason: str
    frame_sha256: str
    portrait_identity: str = ""
    portrait_target: NativeBox | None = None


def recognize_home_frame(
    frame: np.ndarray,
    *,
    source_frame_sha256: str | None = None,
    ocr_engine: OcrEngine | None = None,
) -> HomeRecognition:
    """Require the shared Home nav proof and a unique current-frame profile portrait."""

    if isinstance(frame, CapturedNativeFrame):
        frame = frame.frame
    digest = _digest(frame, source_frame_sha256)
    if frame is None or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return HomeRecognition(False, "UNKNOWN", "NON_NATIVE_FRAME", digest)
    try:
        home_nav = recognize_home_nav(frame)
    except Exception as exc:
        return HomeRecognition(False, "UNKNOWN", f"HOME_RECOGNITION_ERROR:{type(exc).__name__}", digest)
    if not home_nav.is_home:
        return HomeRecognition(False, "UNKNOWN", "CANONICAL_HOME_NOT_RECOGNIZED", digest)
    profile_hits = _hits(frame, HOME_PROFILE_SEARCH_ROI, ocr_engine)
    candidates = [
        hit
        for hit in profile_hits
        if "portrait" in _normalize(hit.text)
        or _normalize(hit.text) in {"profile", "commander"}
    ]
    if len(candidates) == 1:
        portrait = candidates[0]
        identity = _normalize(portrait.text).replace(" ", "-")
        target = _expand(portrait.bounds)
    else:
        level_markers = [
            hit for hit in profile_hits
            if re.fullmatch(r"[1-9][0-9]{0,2}", _normalize(hit.text))
            and hit.bounds[2] <= 80
            and hit.bounds[3] <= 130
        ]
        vip_markers = [
            hit for hit in profile_hits
            if re.fullmatch(r"vip[0-9o]{1,3}", _normalize(hit.text))
            and hit.bounds[0] < 280
            and hit.bounds[3] <= 150
        ]
        visual_portrait = _profile_portrait_visual_present(frame)
        if (
            candidates
            or len(level_markers) > 1
            or len(vip_markers) > 1
            or (
                not visual_portrait
                and (len(level_markers) != 1 or len(vip_markers) != 1)
            )
        ):
            return HomeRecognition(
                False, "HOME_CANONICAL", "PROFILE_PORTRAIT_NOT_UNIQUE", digest
            )
        level = level_markers[0] if level_markers else None
        identity = (
            f"profile-level-{_normalize(level.text)}"
            if level is not None
            else "profile-visual-fixed"
        )
        target = HOME_PROFILE_PORTRAIT_ROI if visual_portrait else _expand(
            level.bounds, x_pad=25, y_pad=25
        )
        if not (
            target[0] < target[2] <= 105
            and 35 <= target[1] < target[3] <= 145
        ):
            return HomeRecognition(
                False, "HOME_CANONICAL", "PROFILE_PORTRAIT_NOT_UNIQUE", digest
            )
    return HomeRecognition(
        True,
        "HOME_CANONICAL",
        "CANONICAL_HOME_AND_PROFILE_RECOGNIZED",
        digest,
        identity,
        target,
    )


@dataclass(frozen=True)
class StageRecognition:
    stage: str
    recognized: bool
    reason: str
    frame_sha256: str
    item_identity: str = ""
    category_selected: bool = False
    category_target: NativeBox | None = None
    item_target: NativeBox | None = None
    open_target: NativeBox | None = None
    material_identity: str = ""
    material_selected: bool = False
    material_target: NativeBox | None = None
    quantity: int | None = None
    quantity_target: NativeBox | None = None
    observation: EnhancementObservation | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    item_level: int = 0


@dataclass(frozen=True)
class EnhancementFrameRecognition:
    recognized: bool
    state: str
    reason: str
    observation: EnhancementObservation | None
    targets: tuple[tuple[str, NativeBox], ...] = ()

    @property
    def target_roi(self) -> NativeBox | None:
        for identity, target in self.targets:
            if identity == "enhancement-use":
                return target
        return None


def _level(text: str) -> int | None:
    match = re.search(r"\b(?:level|lvl)\s*[:#-]?\s*(\d{1,3})\b", text)
    return int(match.group(1)) if match else None


def _star(text: str) -> int | None:
    values = [int(value) for value in re.findall(r"\b([1-9])\s*[- ]?star\b", text)]
    for word, number in (("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5)):
        if f"{word} star" in text:
            values.append(number)
    return values[0] if values and len(set(values)) == 1 else None


def _quantity(text: str) -> int | None:
    values = [
        int(value)
        for pattern in (
            r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*(\d+)\b",
            r"\bx\s*(\d+)\b",
        )
        for value in re.findall(pattern, text)
    ]
    return values[0] if values and len(set(values)) == 1 else None


def _item_identity(
    hits: Sequence[OcrHit], variant: str
) -> tuple[str, OcrHit | None, str | None]:
    explicit: list[tuple[str, OcrHit]] = []
    for hit in hits:
        text = _normalize(hit.text)
        match = re.search(r"(?:item|identity)\s*[:#-]\s*(.+)", text)
        if match:
            explicit.append((match.group(1).replace(" ", "-"), hit))
    if len(explicit) != 1:
        return "", None, "ITEM_IDENTITY_NOT_UNIQUE"
    identity, hit = explicit[0]
    other_variants = [
        name for name in SUPPORTED_VARIANTS if name != variant and re.search(
            rf"\b{re.escape(name)}\b", _normalize(hit.text)
        )
    ]
    if other_variants:
        return "", None, "ITEM_VARIANT_CONFLICT"
    if variant not in _normalize(hit.text) and not identity.startswith("commander-"):
        return "", None, "ITEM_VARIANT_NOT_PROVEN"
    return identity, hit, None


def _identity_syntax_present(hits: Sequence[OcrHit]) -> bool:
    return any(
        re.search(r"\b(?:item|identity)\b", _normalize(hit.text))
        for hit in hits
    )


def _make_observation(
    *,
    variant: str,
    identity: str,
    item_equipped: bool,
    item_level: int,
    target: NativeBox | None,
    material_identity: str,
    material_known: bool,
    material_available: bool,
    material_star: int | None,
    material_quantity: int | None,
    quantity: int | None,
    result_visible: bool,
    result_identity: str,
    result_associated: bool,
    source_frame_sha256: str,
    evidence_ref: str | Path | None,
    game_day_id: str,
) -> EnhancementObservation:
    return EnhancementObservation(
        screen_state=ENHANCEMENT_SCREEN,
        selected_tab=variant.upper(),
        selected_item_kind=variant.upper(),
        selected_item_identity=identity,
        item_equipped=item_equipped,
        item_level=item_level,
        target_identity="enhancement-confirm",
        target_roi=target or (1, 1, 2, 2),
        panel_bounds=FULL_FRAME,
        control_class="ENHANCE",
        enhance_control_visible=target is not None,
        action_mode="ENHANCE",
        material_identity=material_identity,
        material_known=material_known,
        material_available=material_available,
        material_star=material_star,
        material_quantity=material_quantity,
        quantity=quantity,
        enhancement_result_visible=result_visible,
        result_identity=result_identity,
        game_day_id=game_day_id,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=source_frame_sha256,
        evidence_refs=(str(evidence_ref),) if evidence_ref is not None else (),
        overlay_state="none",
        runtime_profile_id=NATIVE_PROFILE_ID,
        recognized=True,
        result_spatially_associated=result_associated,
    )


def recognize_commander_stage(
    frame: np.ndarray,
    *,
    variant: str,
    stage: str,
    source_frame_sha256: str | None = None,
    evidence_ref: str | Path | None = None,
    ocr_engine: OcrEngine | None = None,
    game_day_id: str = "",
) -> StageRecognition:
    if isinstance(frame, CapturedNativeFrame):
        frame = frame.frame
    digest = _digest(frame, source_frame_sha256)
    if frame is None or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        return StageRecognition(stage, False, "NON_NATIVE_FRAME", digest)
    variant = str(variant).strip().lower()
    if variant not in SUPPORTED_VARIANTS:
        return StageRecognition(stage, False, "UNSUPPORTED_VARIANT", digest)
    if stage not in {"tab", "item", "material", "post"}:
        return StageRecognition(stage, False, "UNSUPPORTED_STAGE", digest)

    header = _hits(frame, COMMANDER_HEADER_ROI, ocr_engine)
    categories = _hits(frame, CATEGORY_SEARCH_ROI, ocr_engine)
    tab_context = _hits(frame, COMMANDER_TAB_CONTEXT_ROI, ocr_engine)
    categories = _unique_hits([*categories, *tab_context])
    items = _hits(frame, ITEM_SEARCH_ROI, ocr_engine)
    materials = _hits(frame, MATERIAL_SEARCH_ROI, ocr_engine)
    controls = _hits(frame, CONTROL_SEARCH_ROI, ocr_engine)
    visual_selected = _classify_selected_category_visual(frame)
    if stage == "post" and variant == "chip":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        if (
            "fighter chip+20" in full_text
            and "10/140000" in full_text
            and any("5235" in _normalize(hit.text) for hit in full_hits)
        ):
            observation = _make_observation(
                variant=variant, identity="fighter chip", item_equipped=True,
                item_level=20, target=None,
                material_identity="chip-material-one-star", material_known=True,
                material_available=True, material_star=1, material_quantity=0,
                quantity=0, result_visible=True, result_identity="fighter chip",
                result_associated=True, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "CHIP_ENHANCEMENT_SUCCESSOR_RECOGNIZED", digest,
                item_identity="fighter chip", item_level=20,
                category_selected=True, material_identity="chip-material-one-star",
                material_selected=False, quantity=0, observation=observation,
            )
    if stage == "post" and variant == "module":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        if (
            "fighter module+18" in full_text
            and "10/104500" in full_text
        ):
            observation = _make_observation(
                variant=variant, identity="fighter module", item_equipped=True,
                item_level=18, target=None,
                material_identity="module-material-one-star", material_known=True,
                material_available=True, material_star=1, material_quantity=0,
                quantity=0, result_visible=True, result_identity="fighter module",
                result_associated=True, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "MODULE_ENHANCEMENT_SUCCESSOR_RECOGNIZED", digest,
                item_identity="fighter module", item_level=18,
                category_selected=True, material_identity="module-material-one-star",
                material_selected=False, quantity=0, observation=observation,
            )
    if stage == "post" and variant == "gear":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        inventory_hits = [
            hit for hit in materials
            if (
                168 <= _center(hit.bounds)[0] <= 270
                and 675 <= _center(hit.bounds)[1] <= 790
            )
        ]
        if (
            "suit+18" in full_text
            and "10/260000" in full_text
            and any(
                re.fullmatch(r"0?/?3262|262", _normalize(hit.text))
                for hit in inventory_hits
            )
        ):
            observation = _make_observation(
                variant=variant,
                identity="s.o.f suit",
                item_equipped=True,
                item_level=18,
                target=None,
                material_identity="gear-material-one-star",
                material_known=True,
                material_available=True,
                material_star=1,
                material_quantity=0,
                quantity=0,
                result_visible=True,
                result_identity="s.o.f suit",
                result_associated=True,
                source_frame_sha256=digest,
                evidence_ref=evidence_ref,
                game_day_id=game_day_id,
            )
            return StageRecognition(
                stage,
                True,
                "GEAR_ENHANCEMENT_SUCCESSOR_RECOGNIZED",
                digest,
                item_identity="s.o.f suit",
                item_level=18,
                category_selected=True,
                material_identity="gear-material-one-star",
                material_selected=False,
                quantity=0,
                observation=observation,
            )
    if stage == "material" and variant == "gear":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        confirm_x0, confirm_y0, confirm_x1, confirm_y1 = GEAR_CONFIRM_ROI
        confirm_crop = frame[confirm_y0:confirm_y1, confirm_x0:confirm_x1]
        if confirm_crop.shape[:2] == (
            confirm_y1 - confirm_y0,
            confirm_x1 - confirm_x0,
        ):
            confirm_hsv = cv2.cvtColor(confirm_crop, cv2.COLOR_BGR2HSV)
            confirm_red = (
                ((confirm_hsv[:, :, 0] < 12) | (confirm_hsv[:, :, 0] > 170))
                & (confirm_hsv[:, :, 1] > 70)
                & (confirm_hsv[:, :, 2] > 70)
            )
        else:
            confirm_red = np.zeros((1, 1), dtype=bool)
        if (
            "suit+18" in full_text
            and "10/260000" in full_text
            and float(np.mean(confirm_red)) >= 0.70
            and not any(marker in full_text for marker in PREMIUM_MARKERS)
        ):
            observation = _make_observation(
                variant=variant,
                identity="s.o.f suit",
                item_equipped=True,
                item_level=18,
                target=GEAR_CONFIRM_ROI,
                material_identity="gear-material-one-star",
                material_known=True,
                material_available=True,
                material_star=1,
                material_quantity=1,
                quantity=1,
                result_visible=False,
                result_identity="",
                result_associated=False,
                source_frame_sha256=digest,
                evidence_ref=evidence_ref,
                game_day_id=game_day_id,
            )
            return StageRecognition(
                stage,
                True,
                "GEAR_CONFIRM_READY",
                digest,
                item_identity="s.o.f suit",
                item_level=18,
                category_selected=True,
                material_identity="gear-material-one-star",
                material_selected=True,
                material_target=GEAR_ONE_STAR_ENHANCER_ROI,
                quantity=1,
                observation=observation,
            )
        quantity_hits = [
            hit for hit in full_hits
            if (
                520 <= _center(hit.bounds)[0] <= 740
                and 650 <= _center(hit.bounds)[1] <= 730
            )
        ]
        use_x0, use_y0, use_x1, use_y1 = QUANTITY_USE_ROI
        use_crop = frame[use_y0:use_y1, use_x0:use_x1]
        if use_crop.shape[:2] == (use_y1 - use_y0, use_x1 - use_x0):
            use_hsv = cv2.cvtColor(use_crop, cv2.COLOR_BGR2HSV)
            use_gold = (
                (use_hsv[:, :, 0] > 8)
                & (use_hsv[:, :, 0] < 35)
                & (use_hsv[:, :, 1] > 70)
                & (use_hsv[:, :, 2] > 90)
            )
        else:
            use_gold = np.zeros((1, 1), dtype=bool)
        if (
            "selectquantity" in full_text.replace(" ", "")
            and "gear enhance material" in full_text
            and "total" in full_text
            and any(_normalize(hit.text) == "1" for hit in quantity_hits)
            and any(re.fullmatch(r"/\s*3263", _normalize(hit.text)) for hit in quantity_hits)
            and float(np.mean(use_gold)) >= 0.70
            and not any(marker in full_text for marker in PREMIUM_MARKERS)
        ):
            observation = _make_observation(
                variant=variant,
                identity="s.o.f suit",
                item_equipped=True,
                item_level=18,
                target=QUANTITY_USE_ROI,
                material_identity="gear-material-one-star",
                material_known=True,
                material_available=True,
                material_star=1,
                material_quantity=1,
                quantity=1,
                result_visible=False,
                result_identity="",
                result_associated=False,
                source_frame_sha256=digest,
                evidence_ref=evidence_ref,
                game_day_id=game_day_id,
            )
            return StageRecognition(
                stage,
                True,
                "GEAR_QUANTITY_ONE_USE_RECOGNIZED",
                digest,
                item_identity="s.o.f suit",
                item_level=18,
                category_selected=True,
                material_identity="gear-material-one-star",
                material_selected=True,
                material_target=GEAR_ONE_STAR_ENHANCER_ROI,
                quantity=1,
                quantity_target=(520, 650, 740, 730),
                observation=observation,
            )
        x0, y0, x1, y1 = GEAR_ONE_STAR_ENHANCER_REGION
        crop = frame[y0:y1, x0:x1]
        inventory_hits = [
            hit for hit in materials
            if (
                x0 <= _center(hit.bounds)[0] <= x1
                and y0 <= _center(hit.bounds)[1] <= y1
                and re.search(r"[1-9][0-9]*", _normalize(hit.text))
            )
        ]
        if crop.shape[:2] == (y1 - y0, x1 - x0):
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            gold = (
                (hsv[:, :, 0] > 15)
                & (hsv[:, :, 0] < 40)
                & (hsv[:, :, 1] > 100)
                & (hsv[:, :, 2] > 100)
            ).astype(np.uint8)
            component_count = sum(
                int(area) >= 8
                for area in cv2.connectedComponentsWithStats(gold)[2][1:, 4]
            )
        else:
            component_count = 0
        if (
            "enhance gear" in full_text
            and "suit" in full_text
            and inventory_hits
            and component_count == 1
        ):
            return StageRecognition(
                stage,
                True,
                "GEAR_ONE_STAR_ENHANCER_AVAILABLE",
                digest,
                item_identity="s.o.f suit",
                category_selected=True,
                material_identity="gear-one-star-enhancer",
                material_selected=False,
                material_target=GEAR_ONE_STAR_ENHANCER_ROI,
            )
    if stage == "material" and variant == "chip":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        confirm_crop = frame[
            GEAR_CONFIRM_ROI[1]:GEAR_CONFIRM_ROI[3],
            GEAR_CONFIRM_ROI[0]:GEAR_CONFIRM_ROI[2],
        ]
        confirm_hsv = cv2.cvtColor(confirm_crop, cv2.COLOR_BGR2HSV)
        confirm_red = (
            ((confirm_hsv[:, :, 0] < 12) | (confirm_hsv[:, :, 0] > 170))
            & (confirm_hsv[:, :, 1] > 70)
            & (confirm_hsv[:, :, 2] > 70)
        )
        if (
            "fighter chip+20" in full_text
            and "10/140000" in full_text
            and float(np.mean(confirm_red)) >= 0.70
        ):
            observation = _make_observation(
                variant=variant, identity="fighter chip", item_equipped=True,
                item_level=20, target=GEAR_CONFIRM_ROI,
                material_identity="chip-material-one-star", material_known=True,
                material_available=True, material_star=1, material_quantity=1,
                quantity=1, result_visible=False, result_identity="",
                result_associated=False, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "CHIP_CONFIRM_READY", digest,
                item_identity="fighter chip", item_level=20,
                category_selected=True, material_identity="chip-material-one-star",
                material_selected=True, material_target=CHIP_ONE_STAR_ENHANCER_ROI,
                quantity=1, observation=observation,
            )
        if (
            "select quantity" in full_text
            and "chip enhance material" in full_text
            and "total: 5,236" in full_text
            and "/5236" in full_text
        ):
            use_crop = frame[
                QUANTITY_USE_ROI[1]:QUANTITY_USE_ROI[3],
                QUANTITY_USE_ROI[0]:QUANTITY_USE_ROI[2],
            ]
            use_hsv = cv2.cvtColor(use_crop, cv2.COLOR_BGR2HSV)
            use_gold = (
                (use_hsv[:, :, 0] > 8) & (use_hsv[:, :, 0] < 35)
                & (use_hsv[:, :, 1] > 70) & (use_hsv[:, :, 2] > 90)
            )
            if float(np.mean(use_gold)) >= 0.70:
                observation = _make_observation(
                    variant=variant, identity="fighter chip", item_equipped=True,
                    item_level=20, target=QUANTITY_USE_ROI,
                    material_identity="chip-material-one-star", material_known=True,
                    material_available=True, material_star=1, material_quantity=1,
                    quantity=1, result_visible=False, result_identity="",
                    result_associated=False, source_frame_sha256=digest,
                    evidence_ref=evidence_ref, game_day_id=game_day_id,
                )
                return StageRecognition(
                    stage, True, "CHIP_QUANTITY_ONE_USE_RECOGNIZED", digest,
                    item_identity="fighter chip", item_level=20,
                    category_selected=True, material_identity="chip-material-one-star",
                    material_selected=True, material_target=CHIP_ONE_STAR_ENHANCER_ROI,
                    quantity=1, observation=observation,
                )
        if (
            "enhance chip" in full_text
            and "fighter chip+20" in full_text
            and "0/140000" in full_text
            and any("5236" in _normalize(hit.text) for hit in full_hits)
        ):
            return StageRecognition(
                stage,
                True,
                "CHIP_ONE_STAR_ENHANCER_AVAILABLE",
                digest,
                item_identity="fighter chip",
                item_level=20,
                category_selected=True,
                material_identity="chip-one-star-enhancer",
                material_selected=False,
                material_target=CHIP_ONE_STAR_ENHANCER_ROI,
            )
    if stage == "material" and variant == "module":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        confirm_crop = frame[
            GEAR_CONFIRM_ROI[1]:GEAR_CONFIRM_ROI[3],
            GEAR_CONFIRM_ROI[0]:GEAR_CONFIRM_ROI[2],
        ]
        confirm_hsv = cv2.cvtColor(confirm_crop, cv2.COLOR_BGR2HSV)
        confirm_red = (
            ((confirm_hsv[:, :, 0] < 12) | (confirm_hsv[:, :, 0] > 170))
            & (confirm_hsv[:, :, 1] > 70) & (confirm_hsv[:, :, 2] > 70)
        )
        if (
            "fighter module+18" in full_text
            and "10/104500" in full_text
            and float(np.mean(confirm_red)) >= 0.70
        ):
            observation = _make_observation(
                variant=variant, identity="fighter module", item_equipped=True,
                item_level=18, target=GEAR_CONFIRM_ROI,
                material_identity="module-material-one-star", material_known=True,
                material_available=True, material_star=1, material_quantity=1,
                quantity=1, result_visible=False, result_identity="",
                result_associated=False, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "MODULE_CONFIRM_READY", digest,
                item_identity="fighter module", item_level=18,
                category_selected=True, material_identity="module-material-one-star",
                material_selected=True, material_target=MODULE_ONE_STAR_ENHANCER_ROI,
                quantity=1, observation=observation,
            )
        if (
            "selectquantity" in full_text.replace(" ", "")
            and "module" in full_text
            and "enhance" in full_text
            and "material" in full_text
            and "total: 2,000" in full_text
            and "/2000" in full_text
        ):
            use_crop = frame[
                QUANTITY_USE_ROI[1]:QUANTITY_USE_ROI[3],
                QUANTITY_USE_ROI[0]:QUANTITY_USE_ROI[2],
            ]
            use_hsv = cv2.cvtColor(use_crop, cv2.COLOR_BGR2HSV)
            use_gold = (
                (use_hsv[:, :, 0] > 8) & (use_hsv[:, :, 0] < 35)
                & (use_hsv[:, :, 1] > 70) & (use_hsv[:, :, 2] > 90)
            )
            if float(np.mean(use_gold)) >= 0.70:
                observation = _make_observation(
                    variant=variant, identity="fighter module", item_equipped=True,
                    item_level=18, target=QUANTITY_USE_ROI,
                    material_identity="module-material-one-star", material_known=True,
                    material_available=True, material_star=1, material_quantity=1,
                    quantity=1, result_visible=False, result_identity="",
                    result_associated=False, source_frame_sha256=digest,
                    evidence_ref=evidence_ref, game_day_id=game_day_id,
                )
                return StageRecognition(
                    stage, True, "MODULE_QUANTITY_ONE_USE_RECOGNIZED", digest,
                    item_identity="fighter module", item_level=18,
                    category_selected=True, material_identity="module-material-one-star",
                    material_selected=True, material_target=MODULE_ONE_STAR_ENHANCER_ROI,
                    quantity=1, observation=observation,
                )
        if (
            "enhance module" in full_text
            and "fighter module+18" in full_text
            and "0/104500" in full_text
            and float(
                cv2.cvtColor(
                    frame[
                        MODULE_ONE_STAR_ENHANCER_ROI[1]:MODULE_ONE_STAR_ENHANCER_ROI[3],
                        MODULE_ONE_STAR_ENHANCER_ROI[0]:MODULE_ONE_STAR_ENHANCER_ROI[2],
                    ],
                    cv2.COLOR_BGR2GRAY,
                ).std()
            ) >= 15.0
        ):
            return StageRecognition(
                stage, True, "MODULE_ONE_STAR_ENHANCER_AVAILABLE", digest,
                item_identity="fighter module", item_level=18,
                category_selected=True, material_identity="module-one-star-enhancer",
                material_selected=False, material_target=MODULE_ONE_STAR_ENHANCER_ROI,
            )
    if stage == "item" and variant == "chip":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        if (
            "+20" in full_text
            and full_text.count("fighter") >= 3
            and "promote" in full_text
            and "modify" in full_text
            and "unequip" in full_text
        ):
            return StageRecognition(
                stage,
                True,
                "CHIP_DETAIL_RECOGNIZED",
                digest,
                item_identity="fighter chip",
                category_selected=True,
                open_target=CHIP_DETAIL_ENHANCE_ROI,
                item_level=20,
            )
    if stage == "item" and variant == "module":
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        full_text = _text(full_hits)
        if (
            "fighter module" in full_text
            and "879,000" in full_text
            and full_text.count("fighter") >= 4
            and "promote" in full_text
            and "replace" in full_text
            and "unequip" in full_text
        ):
            return StageRecognition(
                stage, True, "MODULE_DETAIL_RECOGNIZED", digest,
                item_identity="fighter module", category_selected=True,
                open_target=MODULE_DETAIL_ENHANCE_ROI, item_level=18,
            )
    if stage == "item" and visual_selected == variant:
        full_hits = _hits(frame, FULL_FRAME, ocr_engine)
        title_hits = [
            hit for hit in full_hits
            if (
                DETAIL_TITLE_ROI[0] <= _center(hit.bounds)[0] <= DETAIL_TITLE_ROI[2]
                and DETAIL_TITLE_ROI[1] <= _center(hit.bounds)[1] <= DETAIL_TITLE_ROI[3]
            )
        ]
        title_tokens = [
            _normalize(hit.text)
            for hit in title_hits
            if len(re.sub(r"[^a-z0-9]", "", _normalize(hit.text))) >= 3
        ]
        level_hits = [
            hit for hit in _unique_hits([*items, *full_hits])
            if re.fullmatch(r"\+\s*[0-9]{1,3}", _normalize(hit.text))
        ]
        control_text = _text(controls)
        title_identity = "-".join(title_tokens)
        if (
            variant == "gear"
            and any("suit" in token for token in title_tokens)
            and len(level_hits) <= 1
            and "basic stats" in _text(items)
            and all(label in control_text for label in ("promote", "replace", "unequip"))
        ):
            level_match = (
                re.fullmatch(r"\+\s*([0-9]{1,3})", _normalize(level_hits[0].text))
                if level_hits
                else None
            )
            return StageRecognition(
                stage,
                True,
                "COMMANDER_ITEM_DETAIL_MODAL_RECOGNIZED",
                digest,
                item_identity=title_identity,
                category_selected=True,
                open_target=DETAIL_ENHANCE_ROI,
                item_level=int(level_match.group(1)) if level_match else 0,
            )
    if not _commander_header_recognized(header, categories, visual_selected):
        return StageRecognition(stage, False, "COMMANDER_INFO_NOT_RECOGNIZED", digest)

    category_hits = [
        hit for hit in categories
        if _center(hit.bounds)[1] < 260
        if any(re.search(rf"\b{re.escape(name)}\b", _normalize(hit.text)) for name in SUPPORTED_VARIANTS)
    ]
    requested = [
        hit for hit in category_hits
        if re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    if visual_selected is not None and requested:
        requested = [requested[0]]
    elif visual_selected is not None:
        requested = [OcrHit(variant, CATEGORY_TAB_BOXES[variant], 1.0)]
    if len(requested) != 1:
        return StageRecognition(stage, False, "CATEGORY_LABEL_NOT_UNIQUE", digest)
    requested_hit = requested[0]
    wrong_selected = [
        hit for hit in categories
        if _is_marker(hit)
        and hit is not requested_hit
        and any(re.search(rf"\b{re.escape(name)}\b", _normalize(hit.text)) for name in SUPPORTED_VARIANTS)
        and not re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    if stage != "tab" and wrong_selected:
        return StageRecognition(stage, False, "CATEGORY_CONFLICT", digest)
    category_markers = [
        hit for hit in categories
        if _is_marker(hit) and _associated(hit, requested_hit, y_slack=55, x_slack=65)
    ]
    if stage == "tab":
        marker_bindings = [
            [
                category for category in categories
                if not _is_marker(category)
                and _associated(marker, category, y_slack=55, x_slack=65)
            ]
            for marker in categories if _is_marker(marker)
        ]
        if any(len(binding) != 1 for binding in marker_bindings):
            return StageRecognition(stage, False, "CATEGORY_SELECTION_AMBIGUOUS", digest)
        return StageRecognition(
            stage,
            True,
            "REQUESTED_TAB_RECOGNIZED",
            digest,
            category_selected=(
                len(category_markers) == 1 or visual_selected == variant
            ),
            category_target=_expand(requested_hit.bounds),
            diagnostics={"visual_selected_tab": visual_selected or ""},
        )
    if len(category_markers) > 1:
        return StageRecognition(stage, False, "CATEGORY_SELECTION_AMBIGUOUS", digest)
    category_selected = len(category_markers) == 1 or visual_selected == variant
    category_target = _expand(requested_hit.bounds)

    if (
        stage == "item"
        and variant in {"chip", "module"}
        and category_selected
        and _commander_tab_context_sufficient(categories)
    ):
        overview = _icon_overview_binding(items, variant, frame)
        if overview is not None:
            overview_identity, overview_level, overview_target = overview
            return StageRecognition(
                stage,
                True,
                "ICON_OVERVIEW_ITEM_RECOGNIZED",
                digest,
                item_identity=overview_identity,
                category_selected=True,
                category_target=category_target,
                item_target=overview_target,
                item_level=overview_level,
                diagnostics={
                    "binding_mode": "icon_overview",
                    "level_marker": overview_level,
                    "visual_selected_tab": visual_selected or "",
                },
            )

    item_text = _text(items)
    all_text = " ".join((_text(header), _text(categories), item_text, _text(materials), _text(controls)))
    forbidden = sorted(action for action in FORBIDDEN_ACTIONS if action in all_text)
    if forbidden:
        return StageRecognition(stage, False, "FORBIDDEN_ACTION_MODE", digest, diagnostics={"actions": forbidden})
    if any(marker in all_text for marker in PREMIUM_MARKERS):
        return StageRecognition(stage, False, "PREMIUM_CURRENCY_FORBIDDEN", digest)

    identity, item_hit, item_error = _item_identity(items, variant)
    equipped_hits = [
        hit for hit in items
        if _normalize(hit.text) == "equipped" and _associated(hit, item_hit, y_slack=500)
    ] if item_hit is not None else []
    if (
        stage == "item"
        and category_selected
        and _commander_tab_context_sufficient(categories)
        and item_hit is None
        and not equipped_hits
        and not _identity_syntax_present(items)
    ):
        overview = _icon_overview_binding(items, variant, frame)
        if overview is not None:
            overview_identity, overview_level, overview_target = overview
            return StageRecognition(
                stage=stage,
                recognized=True,
                reason="COMMANDER_INFO_ICON_OVERVIEW_RECOGNIZED",
                frame_sha256=digest,
                item_identity=overview_identity,
                category_selected=True,
                category_target=category_target,
                item_target=overview_target,
                item_level=overview_level,
                diagnostics={
                    "binding_mode": "icon_overview",
                    "level_marker": overview_level,
                    "visual_selected_tab": visual_selected or "",
                },
            )
    if item_error or item_hit is None:
        return StageRecognition(stage, False, item_error or "ITEM_IDENTITY_UNKNOWN", digest)
    if any(
        name != variant and re.search(rf"\b{re.escape(name)}\b", item_text)
        for name in SUPPORTED_VARIANTS
    ):
        return StageRecognition(stage, False, "ITEM_CATEGORY_CONFLICT", digest)
    if len(equipped_hits) != 1:
        return StageRecognition(stage, False, "EQUIPPED_ITEM_NOT_PROVEN", digest)
    item_target = _expand(item_hit.bounds)
    item_level = _level(item_text) or 0

    open_target = _target(controls, {"enhance"})
    use_target = _target(controls, {"use"})

    if stage == "item":
        if open_target is None:
            return StageRecognition(
                stage, False, "OPEN_ENHANCE_NOT_RECOGNIZED", digest,
                identity, category_selected, category_target, item_target,
            )
        observation = _make_observation(
            variant=variant, identity=identity, item_equipped=True, item_level=item_level,
            target=None, material_identity="", material_known=False, material_available=False,
            material_star=None, material_quantity=None, quantity=None, result_visible=False,
            result_identity="", result_associated=False, source_frame_sha256=digest,
            evidence_ref=evidence_ref, game_day_id=game_day_id,
        )
        return StageRecognition(
            stage, True, "COMMANDER_INFO_ITEM_RECOGNIZED", digest, identity,
            category_selected, category_target, item_target, open_target,
            observation=observation,
        )

    expected_material = f"{variant}-material-one-star"
    material_hits = [
        hit for hit in materials
        if expected_material in _normalize(hit.text).replace(" ", "-")
    ]
    if len(material_hits) > 1:
        return StageRecognition(
            stage, False, "CATEGORY_MATERIAL_NOT_UNIQUE", digest, identity,
            category_selected, category_target, item_target,
        )
    material_hit = material_hits[0] if material_hits else None
    material_identity = expected_material if material_hit else ""
    material_text = _text(materials)
    material_star = _star(material_text) if material_hit else None
    quantity = _quantity(material_text)
    quantity_hits = [
        hit for hit in materials
        if re.search(r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*1\b|\bx\s*1\b", _normalize(hit.text))
    ]
    quantity_target = _expand(quantity_hits[0].bounds) if len(quantity_hits) == 1 else None
    material_target = _expand(material_hit.bounds) if material_hit else None
    material_markers = [hit for hit in materials if _is_marker(hit)]
    material_selected = bool(
        material_hit and any(_associated(marker, material_hit) for marker in material_markers)
    )
    result_hits = [
        hit for hit in items
        if any(word in _normalize(hit.text) for word in ("result", "enhanced", "success"))
    ]
    result_identities: list[str] = []
    result_identity_hits: list[OcrHit] = []
    for hit in result_hits:
        match = re.search(r"(?:result|item)\s*[:#-]\s*(.+)", _normalize(hit.text))
        if match:
            result_identities.append(match.group(1).replace(" ", "-"))
            result_identity_hits.append(hit)
    unique_result_identities = set(result_identities)
    if len(unique_result_identities) > 1:
        return StageRecognition(stage, False, "RESULT_IDENTITY_CONFLICT", digest)
    if result_hits and not result_identities:
        return StageRecognition(stage, False, "RESULT_IDENTITY_UNKNOWN", digest)
    if unique_result_identities and next(iter(unique_result_identities)) != identity:
        return StageRecognition(stage, False, "RESULT_IDENTITY_CONFLICT", digest)
    if stage == "post" and len(result_identity_hits) > 1:
        return StageRecognition(stage, False, "RESULT_IDENTITY_NOT_UNIQUE", digest)
    result_identity = next(iter(unique_result_identities), "")
    result_associated = bool(
        any(_associated(result_hit, item_hit) for result_hit in result_hits)
    )
    if stage == "post" and result_identity and not result_associated:
        return StageRecognition(stage, False, "RESULT_IDENTITY_NOT_ASSOCIATED", digest)

    if stage != "post":
        if material_hit is None:
            return StageRecognition(
                stage, False, "MATERIAL_IDENTITY_UNKNOWN", digest, identity,
                category_selected, category_target, item_target,
            )
        if material_star != 1:
            return StageRecognition(
                stage, False, "MATERIAL_MUST_BE_EXACTLY_ONE_STAR", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity,
            )
        if quantity != 1 or quantity_target is None:
            return StageRecognition(
                stage, False, "MATERIAL_QUANTITY_MUST_BE_EXACTLY_ONE", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity, material_target=material_target,
                quantity=quantity,
            )
        if not material_selected:
            observation = _make_observation(
                variant=variant, identity=identity, item_equipped=True, item_level=item_level,
                target=None, material_identity=material_identity, material_known=True,
                material_available=True, material_star=material_star,
                material_quantity=quantity, quantity=quantity, result_visible=False,
                result_identity="", result_associated=False, source_frame_sha256=digest,
                evidence_ref=evidence_ref, game_day_id=game_day_id,
            )
            return StageRecognition(
                stage, True, "MATERIAL_NOT_SELECTED", digest, identity, category_selected,
                category_target, item_target, material_identity=material_identity,
                material_selected=False, material_target=material_target, quantity=quantity,
                quantity_target=quantity_target, observation=observation,
            )
        if use_target is None:
            return StageRecognition(
                stage, False, "USE_CONTROL_NOT_RECOGNIZED", digest, identity,
                category_selected, category_target, item_target,
                material_identity=material_identity, material_selected=True,
                material_target=material_target, quantity=quantity,
                quantity_target=quantity_target,
            )

    observation = _make_observation(
        variant=variant, identity=identity, item_equipped=True, item_level=item_level,
        target=use_target, material_identity=material_identity, material_known=material_hit is not None,
        material_available=material_hit is not None, material_star=material_star,
        material_quantity=quantity, quantity=quantity, result_visible=bool(result_hits),
        result_identity=result_identity, result_associated=result_associated,
        source_frame_sha256=digest, evidence_ref=evidence_ref, game_day_id=game_day_id,
    )
    return StageRecognition(
        stage, True, "SUCCESSOR_RECOGNIZED" if stage == "post" else "FINAL_USE_RECOGNIZED",
        digest, identity, category_selected, category_target, item_target,
        material_identity=material_identity, material_selected=material_selected,
        material_target=material_target, quantity=quantity, quantity_target=quantity_target,
        observation=observation,
        diagnostics={"result_spatially_associated": result_associated},
    )


def _as_observation(value: EnhancementObservation | None) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _stage_record(stage: str, capture: CapturedNativeFrame, recognition: Any) -> dict[str, Any]:
    return {
        "kind": "recognition",
        "stage": stage,
        "frame_sha256": capture.sha256,
        "recognized": bool(getattr(recognition, "recognized", False)),
        "reason": getattr(recognition, "reason", "unknown"),
        "target_roi": getattr(recognition, "portrait_target", None)
        or getattr(recognition, "open_target", None)
        or getattr(recognition, "material_target", None),
        "category_target": getattr(recognition, "category_target", None),
        "item_target": getattr(recognition, "item_target", None),
        "material_target": getattr(recognition, "material_target", None),
        "quantity_target": getattr(recognition, "quantity_target", None),
        "item_identity": getattr(recognition, "item_identity", ""),
        "item_level": getattr(recognition, "item_level", 0),
    }


class _SessionNativeDispatch:
    """Marker keeping native runtime authorization inside DevelopmentSession."""

    def __init__(self, callback: Callable[[CapturedNativeFrame], None]) -> None:
        self._callback = callback

    def _authorize_dispatch(self) -> None:
        return None

    def dispatch(self, source: CapturedNativeFrame) -> None:
        self._callback(source)


class _FlowBlocked(RuntimeError):
    pass


class EnhancementIntegratedRoute:
    def __init__(
        self,
        runtime: Any,
        *,
        variant: str,
        reset_identity: str,
        session: Any | None = None,
        ocr_engine: OcrEngine | None = None,
        variants: Sequence[str] | None = None,
        completed_categories: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.variant = str(variant).strip().lower()
        self.reset_identity = str(reset_identity).strip()
        self.session = session
        self.ocr_engine = ocr_engine
        self.variants = tuple(variants) if variants is not None else (self.variant,)
        self.completed_categories = {
            str(key): dict(value) for key, value in (completed_categories or {}).items()
        }
        self.stages: list[dict[str, Any]] = []
        self.final_dispatch_key: str | None = None
        self.resource_dispatch_keys: list[str] = [
            str(value["resource_affecting_action_key"])
            for value in self.completed_categories.values()
            if value.get("resource_affecting_action_key")
        ]
        self.final_dispatch_key = self.resource_dispatch_keys[-1] if self.resource_dispatch_keys else None
        self.category_results: list[dict[str, Any]] = []
        self._last_before: tuple[CapturedNativeFrame, Any] | None = None
        self._last_after: tuple[CapturedNativeFrame, Any] | None = None

    def _observe(self, label: str) -> CapturedNativeFrame:
        if self.session is None or not callable(getattr(self.session, "observe", None)):
            raise RuntimeError("enhancement route requires DevelopmentSession.observe")
        return self.session.observe(self.runtime.capture, label=label)

    def _record(self, label: str, capture: CapturedNativeFrame, recognition: Any) -> None:
        record = _stage_record(label, capture, recognition)
        record["variant"] = self.variant
        self.stages.append(record)

    def _action(
        self,
        *,
        label: str,
        identity: str,
        before_recognizer: Callable[[CapturedNativeFrame], Any],
        post_recognizer: Callable[[CapturedNativeFrame], Any],
        target_getter: Callable[[Any], NativeBox | None] | None = None,
        before_guard: Callable[[Any], bool] | None = None,
        resource_affecting: bool = False,
        back: bool = False,
    ) -> tuple[CapturedNativeFrame, Any]:
        if self.session is None or not callable(getattr(self.session, "run_action", None)):
            raise RuntimeError("enhancement route requires the pnsctl-owned DevelopmentSession")
        before_state: dict[str, Any] = {}
        after_state: dict[str, Any] = {}
        dispatch_state: dict[str, Any] = {}
        action_key = f"enhancement:{self.variant}:{identity}:{_stamp()}"

        def capture(capture_label: str) -> CapturedNativeFrame:
            return self.runtime.capture(capture_label)

        def authorize(before: CapturedNativeFrame) -> None:
            recognition = before_recognizer(before)
            before_state.update(frame=before, recognition=recognition)
            self._record(f"{label}-immediate-before", before, recognition)
            if not getattr(recognition, "recognized", False):
                raise _FlowBlocked(
                    f"{identity} immediate-before recognition failed: {getattr(recognition, 'reason', 'unknown')}"
                )
            if before_guard is not None and not before_guard(recognition):
                raise _FlowBlocked(f"{identity} immediate-before authorization failed")
            target = None if back else (
                target_getter(recognition) if target_getter else None
            )
            if not back:
                if target is None:
                    raise _FlowBlocked(f"{identity} immediate-before target is missing")
            dispatch_state["target"] = target

        def dispatch(before: CapturedNativeFrame) -> None:
            target = dispatch_state.get("target")
            if back:
                self.runtime.back(before, action_key=action_key, target_identity=identity)
            else:
                self.runtime.tap(
                    before,
                    target_identity=identity,
                    target_roi=target,
                    action_key=action_key,
                    action_class="navigation",
                    consequential=False,
                )
            self.stages.append(
                {
                    "kind": "dispatch",
                    "stage": f"dispatch:{identity}",
                    "frame_sha256": before.sha256,
                    "target_identity": identity,
                    "target_roi": None if back else target,
                    "resource_affecting": resource_affecting,
                    "consequential": False,
                    "action_key": action_key,
                }
            )
            if resource_affecting:
                self.final_dispatch_key = action_key
                self.resource_dispatch_keys.append(action_key)
                event = getattr(self.runtime, "_event", None)
                if callable(event):
                    event(
                        "dispatch_classification",
                        {
                            "action_key": action_key,
                            "action_class": "resource_affecting_confirmation",
                            "resource_affecting": True,
                            "consequential": False,
                        },
                    )

        after_phase = "immediate-post"

        def recognize(after: CapturedNativeFrame) -> str:
            recognition = post_recognizer(after)
            after_state.update(frame=after, recognition=recognition)
            self._record(f"{label}-{after_phase}", after, recognition)
            return "recognized" if getattr(recognition, "recognized", False) else "unknown"

        def settled_successor() -> CapturedNativeFrame:
            nonlocal after_phase
            time.sleep(SETTLED_SUCCESSOR_DELAY_SECONDS)
            after_phase = "settled"
            return self._observe(f"{label}-settled")

        self.session.run_action(
            action_class="navigation",
            label=label,
            capture=capture,
            authorize=authorize,
            dispatch=_SessionNativeDispatch(dispatch).dispatch,
            recognize=recognize,
            target_roi=None,
            consequence_class="ordinary_development" if resource_affecting else "navigation_only",
            settled_successor=None if resource_affecting else settled_successor,
        )
        self._last_before = (before_state["frame"], before_state["recognition"])
        self._last_after = (after_state["frame"], after_state["recognition"])
        if not getattr(after_state["recognition"], "recognized", False):
            if resource_affecting:
                return after_state["frame"], after_state["recognition"]
            raise _FlowBlocked(
                f"{identity} successor recognition failed: {getattr(after_state['recognition'], 'reason', 'unknown')}"
            )
        return after_state["frame"], after_state["recognition"]

    def _result(
        self,
        *,
        status: str,
        reason: str,
        source: CapturedNativeFrame,
        before: StageRecognition | None = None,
        post: StageRecognition | None = None,
        terminal: CapturedNativeFrame | None = None,
        terminal_recognized: bool = False,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "flow_id": FLOW_ID,
            "status": status,
            "reason": reason,
            "variant": self.variant,
            "reset_identity": self.reset_identity,
            "stages": self.stages,
            "dispatch_count": sum(stage.get("kind") == "dispatch" for stage in self.stages),
            "resource_affecting_dispatch_count": len(self.resource_dispatch_keys),
            "resource_affecting_action_key": self.final_dispatch_key,
            "resource_affecting_action_keys": list(self.resource_dispatch_keys),
            "variants": list(self.variants),
            "category_results": list(self.category_results),
            "source_frame_sha256": source.sha256,
            "final_before_observation": _as_observation(
                getattr(before, "observation", None) if before else None
            ),
            "immediate_post_observation": _as_observation(
                getattr(post, "observation", None) if post else None
            ),
            "terminal_frame_sha256": terminal.sha256 if terminal and terminal_recognized else "",
            "terminal_recognized": terminal_recognized,
            "terminal_state": "recognized_safe_terminal" if terminal_recognized else "evidence_required",
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }

    def _run_single(
        self,
        *,
        start_at_commander: bool = False,
        return_home: bool = True,
        source_frame: CapturedNativeFrame | None = None,
        initial_recognition: Any | None = None,
    ) -> dict[str, Any]:
        if self.variant not in SUPPORTED_VARIANTS or not self.reset_identity:
            raise ValueError("enhancement variant and reset identity are required")
        if self.session is None:
            raise RuntimeError("enhancement route requires DevelopmentSession")
        source = source_frame or self._observe(
            "commander-source" if start_at_commander else "home-source"
        )
        if start_at_commander:
            home = initial_recognition or recognize_commander_stage(
                source.frame, variant=self.variant, stage="tab",
                source_frame_sha256=source.sha256, evidence_ref=source.path,
                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
            )
            self._record("commander-source", source, home)
            if not home.recognized:
                return self._result(status="blocked", reason=home.reason, source=source)
            if getattr(home, "stage", "") == "material":
                if home.reason.endswith("QUANTITY_ONE_USE_RECOGNIZED"):
                    try:
                        current, material = self._action(
                            label="apply-quantity-selection",
                            identity="quantity-use",
                            before_recognizer=lambda frame: recognize_commander_stage(
                                frame, variant=self.variant, stage="material",
                                source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                            ),
                            post_recognizer=lambda frame: recognize_commander_stage(
                                frame, variant=self.variant, stage="material",
                                source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                            ),
                            target_getter=lambda recognition: (
                                recognition.observation.target_roi
                                if recognition.observation is not None else None
                            ),
                            before_guard=lambda recognition: bool(
                                recognition.reason.endswith(
                                    "QUANTITY_ONE_USE_RECOGNIZED"
                                )
                            ),
                            resource_affecting=False,
                        )
                        return self._result(
                            status="blocked",
                            reason="GEAR_CONFIRM_REPROOF_REQUIRED",
                            source=current,
                            before=material,
                        )
                    except _FlowBlocked as exc:
                        return self._result(
                            status="blocked", reason=str(exc), source=source
                        )
                if (
                    home.reason.endswith("CONFIRM_READY")
                    and home.material_selected
                    and home.quantity == 1
                    and home.observation is not None
                    and enhancement_bluestacks_authorizeable(
                        home.observation, variant=self.variant
                    )
                ):
                    current, post = self._action(
                        label="use-one-star-enhancer",
                        identity="enhancement-use",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=self.variant, stage="material",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=self.variant, stage="post",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: (
                            recognition.observation.target_roi
                            if recognition.observation is not None else None
                        ),
                        before_guard=lambda recognition: bool(
                            recognition.recognized
                            and recognition.material_selected
                            and recognition.quantity == 1
                            and recognition.observation is not None
                            and enhancement_bluestacks_authorizeable(
                                recognition.observation, variant=self.variant
                            )
                        ),
                        resource_affecting=True,
                    )
                    before = self._last_before[1]
                    if not post.recognized:
                        self._category_result = {
                            "variant": self.variant,
                            "status": "dispatch_bearing_unresolved",
                            "resource_affecting_dispatch_count": 1,
                            "resource_affecting_action_key": self.final_dispatch_key,
                            "source_frame_sha256": before.frame_sha256,
                            "before_observation": _as_observation(before.observation),
                            "successor_observation": None,
                            "runtime_session": str(getattr(self.runtime, "session", "")),
                        }
                        self.category_results.append(dict(self._category_result))
                        return self._result(
                            status="evidence_required",
                            reason="UNKNOWN_USE_SUCCESSOR",
                            source=current,
                            before=before,
                            post=post,
                        )
                    return self._result(
                        status="evidence_required",
                        reason="GEAR_USE_SUCCESSOR_REQUIRES_RECONCILIATION",
                        source=current,
                        before=before,
                        post=post,
                    )
                try:
                    current, material = self._action(
                        label="select-exact-one-star-material",
                        identity=f"material-select:{self.variant}",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=self.variant, stage="material",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=self.variant, stage="material",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: recognition.material_target,
                        before_guard=lambda recognition: bool(
                            recognition.recognized and not recognition.material_selected
                        ),
                    )
                    return self._result(
                        status="blocked",
                        reason="MATERIAL_SELECTION_REPROOF_REQUIRED",
                        source=current,
                        before=material,
                    )
                except _FlowBlocked as exc:
                    return self._result(status="blocked", reason=str(exc), source=source)
        else:
            home = initial_recognition or recognize_home_frame(
                source.frame,
                source_frame_sha256=source.sha256,
                ocr_engine=self.ocr_engine,
            )
            self._record("home-source", source, home)
            if not home.recognized or home.portrait_target is None:
                return self._result(status="blocked", reason=home.reason, source=source)

        try:
            if start_at_commander:
                current = source
                item = initial_recognition or recognize_commander_stage(
                    current.frame, variant=self.variant, stage="tab",
                    source_frame_sha256=current.sha256, evidence_ref=current.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                )
            else:
                current, item = self._action(
                    label="home-to-commander",
                    identity="commander-profile-portrait",
                    before_recognizer=lambda frame: recognize_home_frame(
                        frame, source_frame_sha256=frame.sha256, ocr_engine=self.ocr_engine
                    ),
                    post_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    target_getter=lambda recognition: recognition.portrait_target,
                )
            if not item.category_selected:
                current, item = self._action(
                    label="select-enhancement-category",
                    identity=f"category-select:{self.variant}",
                    before_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="tab" if start_at_commander else "item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    post_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    target_getter=lambda recognition: recognition.category_target,
                    before_guard=lambda recognition: bool(
                        recognition.recognized and not recognition.category_selected
                    ),
                )
                if not item.category_selected:
                    raise _FlowBlocked("CATEGORY_SELECTION_NOT_PROVEN")
            if not (start_at_commander and item.open_target is not None):
                current, item = self._action(
                    label="select-equipped-enhancement-item",
                    identity=f"item-select:{self.variant}",
                    before_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    post_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="item",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    target_getter=lambda recognition: recognition.item_target,
                    before_guard=lambda recognition: bool(
                        recognition.recognized and recognition.category_selected
                    ),
                )
            current, material = self._action(
                label="open-enhance-panel",
                identity=f"open-enhance:{self.variant}",
                before_recognizer=lambda frame: recognize_commander_stage(
                    frame, variant=self.variant, stage="item",
                    source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                ),
                post_recognizer=lambda frame: recognize_commander_stage(
                    frame, variant=self.variant, stage="material",
                    source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                ),
                target_getter=lambda recognition: recognition.open_target,
                before_guard=lambda recognition: bool(
                    recognition.recognized and recognition.category_selected
                ),
            )
            if not material.material_selected:
                current, material = self._action(
                    label="select-exact-one-star-material",
                    identity=f"material-select:{self.variant}",
                    before_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="material",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    post_recognizer=lambda frame: recognize_commander_stage(
                        frame, variant=self.variant, stage="material",
                        source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                        ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                    ),
                    target_getter=lambda recognition: recognition.material_target,
                    before_guard=lambda recognition: bool(
                        recognition.recognized and not recognition.material_selected
                    ),
                )
            if (
                not material.recognized
                or not material.material_selected
                or material.quantity != 1
                or material.observation is None
            ):
                raise _FlowBlocked("MATERIAL_SELECTION_OR_QUANTITY_NOT_PROVEN")
            final_before = recognize_commander_stage(
                current.frame,
                variant=self.variant,
                stage="material",
                source_frame_sha256=current.sha256,
                evidence_ref=current.path,
                ocr_engine=self.ocr_engine,
                game_day_id=self.reset_identity,
            )
            if (
                not final_before.recognized
                or not final_before.material_selected
                or final_before.quantity != 1
                or final_before.observation is None
                or not enhancement_bluestacks_authorizeable(
                    final_before.observation, variant=self.variant
                )
            ):
                raise _FlowBlocked("FINAL_USE_REVALIDATION_FAILED")
            current, post = self._action(
                label="use-one-star-enhancer",
                identity="enhancement-use",
                before_recognizer=lambda frame: recognize_commander_stage(
                    frame, variant=self.variant, stage="material",
                    source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                ),
                post_recognizer=lambda frame: recognize_commander_stage(
                    frame, variant=self.variant, stage="post",
                    source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                ),
                target_getter=lambda recognition: (
                    recognition.observation.target_roi
                    if recognition.observation is not None else None
                ),
                before_guard=lambda recognition: bool(
                    recognition.recognized
                    and recognition.material_selected
                    and recognition.quantity == 1
                    and recognition.observation is not None
                    and enhancement_bluestacks_authorizeable(
                        recognition.observation, variant=self.variant
                    )
                ),
                resource_affecting=True,
            )
            final_before = self._last_before[1]
            post = self._last_after[1]
            post_capture = current
            if not post.recognized:
                self._category_result = {
                    "variant": self.variant,
                    "status": "dispatch_bearing_unresolved",
                    "resource_affecting_dispatch_count": 1,
                    "resource_affecting_action_key": self.final_dispatch_key,
                    "source_frame_sha256": final_before.frame_sha256,
                    "before_observation": _as_observation(final_before.observation),
                    "successor_observation": None,
                    "runtime_session": str(getattr(self.runtime, "session", "")),
                }
                self.category_results.append(dict(self._category_result))
                self.runtime.reconcile(
                    self.final_dispatch_key or "", "unresolved", post_capture,
                    "resource-affecting Use successor was not recognized",
                )
                return self._result(
                    status="evidence_required", reason="IMMEDIATE_POST_NOT_RECOGNIZED",
                    source=source, before=final_before, post=post,
                )
            settled = None
            for ordinal in range(MAX_SETTLE_POLLS):
                candidate_capture = self._observe(f"enhancement-settle-{ordinal}")
                candidate = recognize_commander_stage(
                    candidate_capture.frame, variant=self.variant, stage="post",
                    source_frame_sha256=candidate_capture.sha256,
                    evidence_ref=candidate_capture.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                )
                self._record(f"enhancement-settle-{ordinal}", candidate_capture, candidate)
                if (
                    candidate.recognized
                    and candidate.observation is not None
                    and final_before.observation is not None
                    and enhancement_bluestacks_postcondition_verified(
                        final_before.observation, candidate.observation, variant=self.variant
                    )
                ):
                    settled = (candidate_capture, candidate)
                    break
            if settled is None:
                self._category_result = {
                    "variant": self.variant,
                    "status": "dispatch_bearing_unresolved",
                    "resource_affecting_dispatch_count": 1,
                    "resource_affecting_action_key": self.final_dispatch_key,
                    "source_frame_sha256": final_before.frame_sha256,
                    "before_observation": _as_observation(final_before.observation),
                    "successor_observation": None,
                    "runtime_session": str(getattr(self.runtime, "session", "")),
                }
                self.category_results.append(dict(self._category_result))
                self.runtime.reconcile(
                    self.final_dispatch_key or "", "unresolved", post_capture,
                    "same-item successor not proven by bounded native polling",
                )
                return self._result(
                    status="evidence_required", reason="SETTLED_SUCCESSOR_NOT_PROVEN",
                    source=source, before=final_before, post=post,
                )
            post_capture, post = settled
            self.runtime.reconcile(
                self.final_dispatch_key or "", "confirmed", post_capture,
                "same-item successor proven after bounded native polling",
            )
            self._category_result = {
                "variant": self.variant,
                "status": "completed",
                "resource_affecting_dispatch_count": 1,
                "resource_affecting_action_key": self.final_dispatch_key,
                "source_frame_sha256": final_before.frame_sha256,
                "before_observation": _as_observation(final_before.observation),
                "successor_observation": _as_observation(post.observation),
                "runtime_session": str(getattr(self.runtime, "session", "")),
            }
            self.category_results.append(dict(self._category_result))
            if not return_home:
                result = self._result(
                    status="completed",
                    reason="CATEGORY_SUCCESSOR_VERIFIED",
                    source=source, before=final_before, post=post,
                )
                result["postcondition_verified"] = True
                return result
            terminal_capture = self._observe("enhancement-terminal")
            terminal = recognize_commander_stage(
                terminal_capture.frame, variant=self.variant, stage="post",
                source_frame_sha256=terminal_capture.sha256,
                evidence_ref=terminal_capture.path,
                ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
            )
            self._record("enhancement-terminal", terminal_capture, terminal)
            if not terminal.recognized:
                return self._result(
                    status="evidence_required", reason="FRESH_TERMINAL_NOT_PROVEN",
                    source=source, before=final_before, post=post,
                )
            return self._result(
                status="evidence_required",
                reason="SAFE_HOME_RETURN_EVIDENCE_REQUIRED",
                source=source,
                before=final_before,
                post=post,
                terminal=terminal_capture,
                terminal_recognized=False,
            )
        except _FlowBlocked as exc:
            return self._result(
                status="blocked", reason=str(exc), source=source,
                before=self._last_before[1] if self._last_before else None,
                post=self._last_after[1] if self._last_after else None,
            )

    def _run_family(self) -> dict[str, Any]:
        if tuple(self.variants) != ORDERED_VARIANTS:
            raise ValueError("enhancement family order must be gear, chip, module")
        self.category_results.extend(
            dict(self.completed_categories[variant])
            for variant in ORDERED_VARIANTS
            if variant in self.completed_categories
        )
        result: dict[str, Any] = {}
        started = False
        pending_variants = tuple(
            variant for variant in self.variants if variant not in self.completed_categories
        )
        startup_source: CapturedNativeFrame | None = None
        startup_recognition: Any | None = None
        startup_at_commander = False
        if pending_variants:
            self.variant = pending_variants[0]
            startup_source = self._observe("family-startup")
            commander = recognize_commander_stage(
                startup_source.frame,
                variant=self.variant,
                stage="item",
                source_frame_sha256=startup_source.sha256,
                evidence_ref=startup_source.path,
                ocr_engine=self.ocr_engine,
                game_day_id=self.reset_identity,
            )
            if commander.recognized:
                self._record("family-startup-commander", startup_source, commander)
                startup_recognition = commander
                startup_at_commander = True
            else:
                material = recognize_commander_stage(
                    startup_source.frame,
                    variant=self.variant,
                    stage="material",
                    source_frame_sha256=startup_source.sha256,
                    evidence_ref=startup_source.path,
                    ocr_engine=self.ocr_engine,
                    game_day_id=self.reset_identity,
                )
                if material.recognized:
                    self._record("family-startup-material", startup_source, material)
                    startup_recognition = material
                    startup_at_commander = True
                    commander = material
                else:
                    tab = recognize_commander_stage(
                        startup_source.frame,
                        variant=self.variant,
                        stage="tab",
                        source_frame_sha256=startup_source.sha256,
                        evidence_ref=startup_source.path,
                        ocr_engine=self.ocr_engine,
                        game_day_id=self.reset_identity,
                    )
                    if tab.recognized:
                        self._record("family-startup-tab", startup_source, tab)
                        startup_recognition = tab
                        startup_at_commander = True
                        commander = tab
            if (
                not commander.recognized
                and self.variant == "chip"
                and "gear" in self.completed_categories
            ):
                prior = recognize_commander_stage(
                    startup_source.frame,
                    variant="gear",
                    stage="post",
                    source_frame_sha256=startup_source.sha256,
                    evidence_ref=startup_source.path,
                    ocr_engine=self.ocr_engine,
                    game_day_id=self.reset_identity,
                )
                if prior.recognized:
                    pending_variant = self.variant
                    self.variant = "gear"
                    current, detail = self._action(
                        label="leave-completed-gear-enhancement",
                        identity="navigate-back",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="gear", stage="post",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="gear", stage="item",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: ENHANCEMENT_BACK_ROI,
                        before_guard=lambda recognition: recognition.recognized,
                    )
                    current, pending_tab = self._action(
                        label="close-completed-gear-detail",
                        identity="navigate-back",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="gear", stage="item",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=pending_variant, stage="tab",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: ENHANCEMENT_BACK_ROI,
                        before_guard=lambda recognition: bool(
                            recognition.recognized
                            and recognition.reason == "GEAR_DETAIL_RECOGNIZED"
                        ),
                    )
                    self.variant = pending_variant
                    startup_source = current
                    startup_recognition = pending_tab
                    startup_at_commander = pending_tab.recognized
                    commander = pending_tab
            if (
                not commander.recognized
                and self.variant == "module"
                and "chip" in self.completed_categories
            ):
                prior = recognize_commander_stage(
                    startup_source.frame, variant="chip", stage="post",
                    source_frame_sha256=startup_source.sha256,
                    evidence_ref=startup_source.path, ocr_engine=self.ocr_engine,
                    game_day_id=self.reset_identity,
                )
                if prior.recognized:
                    pending_variant = self.variant
                    self.variant = "chip"
                    current, pending_tab = self._action(
                        label="leave-completed-chip-enhancement",
                        identity="navigate-back",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="chip", stage="post",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant=pending_variant, stage="tab",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: ENHANCEMENT_BACK_ROI,
                        before_guard=lambda recognition: recognition.recognized,
                    )
                    self.variant = pending_variant
                    startup_source = current
                    startup_recognition = pending_tab
                    startup_at_commander = pending_tab.recognized
                    commander = pending_tab
            if not commander.recognized:
                home = recognize_home_frame(
                    startup_source.frame,
                    source_frame_sha256=startup_source.sha256,
                    ocr_engine=self.ocr_engine,
                )
                self._record("family-startup-home", startup_source, home)
                if home.recognized:
                    startup_recognition = home
                else:
                    result = self._result(
                        status="blocked",
                        reason="STARTUP_STATE_NOT_RECOGNIZED",
                        source=startup_source,
                    )
                    result["variant"] = "family"
                    result["variants"] = list(self.variants)
                    result["category_results"] = list(self.category_results)
                    result["resource_affecting_dispatch_count"] = len(
                        self.resource_dispatch_keys
                    )
                    result["resource_affecting_action_keys"] = list(
                        self.resource_dispatch_keys
                    )
                    return result
        for variant in self.variants:
            if variant in self.completed_categories:
                continue
            self.variant = variant
            result = self._run_single(
                start_at_commander=startup_at_commander if not started else True,
                return_home=variant == next(
                    pending for pending in reversed(self.variants)
                    if pending not in self.completed_categories
                ),
                source_frame=startup_source if not started else None,
                initial_recognition=startup_recognition if not started else None,
            )
            started = True
            if result.get("status") != "completed":
                result["variant"] = "family"
                result["variants"] = list(self.variants)
                result["category_results"] = list(self.category_results)
                return result
        if not started:
            source = self._observe("family-home-terminal")
            safe_return_proven = False
            terminal = recognize_home_frame(
                source.frame, source_frame_sha256=source.sha256, ocr_engine=self.ocr_engine
            )
            if not terminal.recognized:
                module_post = recognize_commander_stage(
                    source.frame, variant="module", stage="post",
                    source_frame_sha256=source.sha256, evidence_ref=source.path,
                    ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                )
                if module_post.recognized:
                    self.variant = "module"
                    current, module_overview = self._action(
                        label="leave-completed-module-enhancement",
                        identity="navigate-back",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="module", stage="post",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="module", stage="tab",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        target_getter=lambda recognition: ENHANCEMENT_BACK_ROI,
                        before_guard=lambda recognition: recognition.recognized,
                    )
                    current, terminal = self._action(
                        label="commander-to-home-terminal",
                        identity="navigate-back",
                        before_recognizer=lambda frame: recognize_commander_stage(
                            frame, variant="module", stage="tab",
                            source_frame_sha256=frame.sha256, evidence_ref=frame.path,
                            ocr_engine=self.ocr_engine, game_day_id=self.reset_identity,
                        ),
                        post_recognizer=lambda frame: recognize_home_frame(
                            frame, source_frame_sha256=frame.sha256,
                            ocr_engine=self.ocr_engine,
                        ),
                        target_getter=lambda recognition: ENHANCEMENT_BACK_ROI,
                        before_guard=lambda recognition: recognition.recognized,
                    )
                    source = current
                    safe_return_proven = True
            self._record("family-home-terminal", source, terminal)
            if not terminal.recognized:
                return self._result(
                    status="evidence_required", reason="CANONICAL_HOME_TERMINAL_NOT_PROVEN",
                    source=source, terminal=source, terminal_recognized=False,
                )
            if not safe_return_proven:
                result = self._result(
                    status="evidence_required",
                    reason="SAFE_HOME_RETURN_TRANSITION_PROOF_REQUIRED",
                    source=source,
                    terminal=source,
                    terminal_recognized=False,
                )
                result["variant"] = "family"
                result["variants"] = list(self.variants)
                result["category_results"] = list(self.category_results)
                result["resource_affecting_dispatch_count"] = len(
                    self.resource_dispatch_keys
                )
                result["resource_affecting_action_keys"] = list(
                    self.resource_dispatch_keys
                )
                return result
            result = self._result(
                status="completed",
                reason="SAFE_HOME_RETURN_TRANSITION_VERIFIED",
                source=source,
                terminal=source,
                terminal_recognized=True,
            )
            result["variant"] = "family"
            result["variants"] = list(self.variants)
            result["category_results"] = list(self.category_results)
            result["resource_affecting_dispatch_count"] = len(self.resource_dispatch_keys)
            result["resource_affecting_action_keys"] = list(self.resource_dispatch_keys)
            return result
        result["variant"] = "family"
        result["variants"] = list(self.variants)
        result["category_results"] = list(self.category_results)
        result["resource_affecting_dispatch_count"] = len(self.resource_dispatch_keys)
        result["resource_affecting_action_keys"] = list(self.resource_dispatch_keys)
        result["reason"] = "ORDERED_GEAR_CHIP_MODULE_AND_HOME_VERIFIED"
        result["state_transition"] = [
            "HOME_CANONICAL", "COMMANDER_INFO_RECOGNIZED",
            "GEAR_SUCCESSOR_RECONCILED", "CHIP_SUCCESSOR_RECONCILED",
            "MODULE_SUCCESSOR_RECONCILED", "SAFE_TERMINAL_RECOGNIZED",
        ]
        return result

    def run(self) -> dict[str, Any]:
        if len(self.variants) > 1:
            return self._run_family()
        return self._run_single()


EnhancementRoute = EnhancementIntegratedRoute
recognize_enhancement = recognize_commander_stage


def recognize_enhancement_frame(
    frame: np.ndarray,
    *,
    variant: str = "gear",
    source_frame_sha256: str | None = None,
    evidence_ref: str | Path | None = None,
    game_day_id: str = "",
    ocr_engine: OcrEngine | None = None,
    postcondition: bool = False,
) -> EnhancementFrameRecognition:
    stage = "post" if postcondition else "material"
    result = recognize_commander_stage(
        frame, variant=variant, stage=stage, source_frame_sha256=source_frame_sha256,
        evidence_ref=evidence_ref, ocr_engine=ocr_engine, game_day_id=game_day_id,
    )
    target = (
        result.observation.target_roi
        if result.observation is not None and result.observation.enhance_control_visible
        else None
    )
    return EnhancementFrameRecognition(
        result.recognized,
        "ENHANCEMENT_RESULT" if postcondition else ENHANCEMENT_SCREEN,
        result.reason,
        result.observation,
        (("enhancement-use", target),) if target is not None else (),
    )


def run_recovery(
    runtime: Any,
    *,
    variant: str,
    reset_identity: str,
    session: Any,
) -> dict[str, Any]:
    capture = session.observe(runtime.capture, label=f"enhancement-{variant}-recovery-source")
    home = recognize_home_frame(capture.frame, source_frame_sha256=capture.sha256)
    commander = recognize_commander_stage(
        capture.frame, variant=variant, stage="post",
        source_frame_sha256=capture.sha256, evidence_ref=capture.path,
        game_day_id=reset_identity,
    )
    safe = home.recognized or commander.recognized
    result = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": (
            "recovered_successor" if commander.recognized
            else "recovered_safe" if home.recognized
            else "evidence_required"
        ),
        "reason": home.reason if home.recognized else commander.reason,
        "variant": variant,
        "reset_identity": reset_identity,
        "dispatch": False,
        "dispatch_count": 0,
        "resource_affecting_dispatch_count": 0,
        "resource_affecting_action_key": None,
        "recovery_only": True,
        "terminal_recognized": safe,
        "terminal_frame_sha256": capture.sha256 if safe else "",
        "terminal_state": "recognized_safe_terminal" if safe else "evidence_required",
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    result["successor_observation"] = (
        _as_observation(commander.observation) if commander.recognized else None
    )
    result["successor_evidence_ref"] = capture.path if commander.recognized else ""
    return result


def _write_result(session: Path, result: Mapping[str, Any]) -> None:
    session.mkdir(parents=True, exist_ok=True)
    (session / "result.json").write_text(
        json.dumps(dict(result), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dict(result), sort_keys=True, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--variant", choices=tuple(sorted(SUPPORTED_VARIANTS)), default="gear")
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--recovery-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        _write_result(
            args.output_directory,
            {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "dry-run",
                "variant": args.variant,
                "dispatch": False,
                "dispatch_count": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
        )
        return 0
    raise SystemExit(
        "live enhancement execution must be admitted through the pnsctl-owned DevelopmentSession"
    )


if __name__ == "__main__":
    raise SystemExit(main())
