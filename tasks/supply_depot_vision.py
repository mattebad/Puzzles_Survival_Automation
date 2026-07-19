"""BlueStacks-native Supply Depot building and screen recognition.

This adapter is intentionally profile-specific.  It never reuses Bliss coordinates,
templates, or thresholds and never dispatches input. Explicitly identified captures use
the shared semantic OCR crop pipeline. Calls that omit an identity retain the legacy
adapter-local crop behavior and make no capture-event claim. OCR never grants authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable

import cv2
import numpy as np
import pytesseract

from .home_atlas import BuildingBinding, LocalizationResult, SemanticBuilding
from .home_atlas_vision import BLUESTACKS_PROFILE_ID, frame_digest, native_frame_guard
from .perception_bundle import NativeFrameIdentity
from .semantic_ocr_crop import (
    CropRoiRequest,
    NormalizationOp,
    ObservationStatus,
    OcrMode,
    PaddingSpec,
    SemanticOcrCropError,
    prepare_ocr_crop,
    run_semantic_ocr,
)


Box = tuple[int, int, int, int]
OCR = Callable[[np.ndarray, int], str]
SUPPLY_DEPOT_BUILDING_ID = "home.building.supply_depot"
SUPPLY_DEPOT_SAFE_SCENE: Box = (138, 150, 650, 1010)
SUPPLY_DEPOT_TITLE_ROI: Box = (120, 0, 680, 110)
SUPPLY_DEPOT_PANEL_ROI: Box = (30, 940, 770, 1270)
SUPPLY_DEPOT_ATTEMPTS_ROI: Box = (100, 800, 700, 950)
SUPPLY_DEPOT_CONTROL_BANDS: tuple[Box, ...] = (
    (0, 1140, 200, 1280),
    (200, 1140, 400, 1280),
    (400, 1140, 600, 1280),
    (600, 1140, 800, 1280),
)
SUPPLY_DEPOT_RADIAL_ROI: Box = (400, 450, 800, 900)
SUPPLY_DEPOT_CLAIM_SUPPLY_ROI: Box = (640, 740, 735, 835)


def _default_ocr(image: np.ndarray, psm: int) -> str:
    return pytesseract.image_to_string(image, config=f"--psm {psm}")


def _validate_explicit_identity(source_frame: NativeFrameIdentity) -> None:
    if not isinstance(source_frame, NativeFrameIdentity):
        raise ValueError("invalid native frame identity")
    if source_frame.width != 800 or source_frame.height != 1280:
        raise ValueError("identity geometry is not native BlueStacks")
    if source_frame.runtime_profile_id != BLUESTACKS_PROFILE_ID:
        raise ValueError("identity profile is not native BlueStacks")


def _legacy_crop(frame: np.ndarray, roi: Box) -> np.ndarray:
    """Pre-pipeline compatibility path. It creates no capture identity."""

    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        raise ValueError("ROI is outside native BlueStacks bounds")
    return frame[y0:y1, x0:x1]


def _crop(
    frame: np.ndarray,
    roi: Box,
    *,
    source_frame: NativeFrameIdentity | None = None,
    padding: PaddingSpec | None = None,
) -> np.ndarray:
    if source_frame is None:
        if padding is not None and padding != PaddingSpec():
            raise ValueError("legacy crop does not support padding")
        return _legacy_crop(frame, roi)
    try:
        _validate_explicit_identity(source_frame)
        request = CropRoiRequest(
            source_frame=source_frame,
            roi=roi,
            padding=padding or PaddingSpec(),
        )
        _provenance, pixels = prepare_ocr_crop(frame, request)
        return pixels
    except SemanticOcrCropError as exc:
        raise ValueError("ROI is outside native BlueStacks bounds") from exc


def _ocr_roi_text(
    frame: np.ndarray,
    roi: Box,
    ocr: OCR,
    *,
    source_frame: NativeFrameIdentity | None = None,
    scale: int = 3,
    grayscale: bool = True,
) -> str:
    if scale not in (1, 2, 3):
        raise ValueError("unsupported OCR upscale")
    if source_frame is None:
        image = _legacy_crop(frame, roi)
        if grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if scale != 1:
            image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )
        return f"{ocr(image, 6)} {ocr(image, 11)}"
    try:
        _validate_explicit_identity(source_frame)
        normalization: list[NormalizationOp] = []
        if grayscale:
            normalization.append(NormalizationOp.TO_GRAYSCALE)
        if scale == 2:
            normalization.append(NormalizationOp.UPSCALE_2X)
        elif scale == 3:
            normalization.append(NormalizationOp.UPSCALE_3X)
        observation = run_semantic_ocr(
            frame,
            CropRoiRequest(source_frame, roi),
            ocr_mode=OcrMode.UNIFORM_AND_SPARSE,
            normalization=tuple(normalization),
            ocr_engine=ocr,
        )
        if observation.status is ObservationStatus.INVALID:
            raise ValueError("ROI is outside native BlueStacks bounds")
        return observation.text
    except SemanticOcrCropError as exc:
        raise ValueError("ROI is outside native BlueStacks bounds") from exc


def _claim_supply_roi_from_data(data: dict[str, list], *, scale: float = 2.0) -> Box | None:
    boxes = []
    ox, oy = SUPPLY_DEPOT_RADIAL_ROI[:2]
    for index, raw in enumerate(data.get("text", ())):
        token = _normalized(str(raw))
        if not (token.startswith("clai") or token.startswith("sup")):
            continue
        x0 = ox + float(data["left"][index]) / scale
        y0 = oy + float(data["top"][index]) / scale
        x1 = x0 + float(data["width"][index]) / scale
        y1 = y0 + float(data["height"][index]) / scale
        boxes.append((x0, y0, x1, y1))
    if len(boxes) < 2:
        return None
    x0 = max(SUPPLY_DEPOT_RADIAL_ROI[0], int(math.floor(min(box[0] for box in boxes) - 10)))
    y0 = max(SUPPLY_DEPOT_RADIAL_ROI[1], int(math.floor(min(box[1] for box in boxes) - 10)))
    x1 = min(SUPPLY_DEPOT_RADIAL_ROI[2], int(math.ceil(max(box[2] for box in boxes) + 10)))
    y1 = min(SUPPLY_DEPOT_RADIAL_ROI[3], int(math.ceil(max(box[3] for box in boxes) + 10)))
    return (x0, y0, x1, y1) if x1 - x0 >= 40 and y1 - y0 >= 30 else None


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _project_atlas_polygon_to_screen(localization: LocalizationResult, building: SemanticBuilding) -> np.ndarray:
    if not localization.recognized or localization.screen_to_atlas is None:
        raise ValueError("building binding requires a recognized current localization")
    matrix = np.asarray(localization.screen_to_atlas, dtype=np.float64)
    inverse = np.linalg.inv(matrix)
    points = np.asarray(building.polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, inverse).reshape(-1, 2)


def bind_supply_depot_building(
    frame: np.ndarray,
    localization: LocalizationResult,
    building: SemanticBuilding,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
) -> BuildingBinding | None:
    """Bind only a current-frame Supply Depot label inside its atlas-predicted region."""

    if (
        not native_frame_guard(frame)
        or localization.profile_id != BLUESTACKS_PROFILE_ID
        or localization.frame_sha256 != frame_digest(frame)
        or building.semantic_id != SUPPLY_DEPOT_BUILDING_ID
    ):
        return None
    polygon = _project_atlas_polygon_to_screen(localization, building)
    x0, y0 = np.floor(polygon.min(axis=0)).astype(int)
    x1, y1 = np.ceil(polygon.max(axis=0)).astype(int)
    search = (max(0, x0 - 10), max(0, y1 - 55), min(800, x1 + 10), min(1280, y1 + 35))
    if search[0] >= search[2] or search[1] >= search[3]:
        return None
    try:
        text = _normalized(_ocr_roi_text(frame, search, ocr, source_frame=source_frame, scale=3))
    except ValueError:
        return None
    if "supply depot" not in text:
        return None

    sx0, sy0, sx1, sy1 = SUPPLY_DEPOT_SAFE_SCENE
    ax0, ay0 = max(x0, sx0), max(y0, sy0)
    ax1, ay1 = min(x1, sx1), min(y1, sy1)
    if ax1 - ax0 < 55 or ay1 - ay0 < 55:
        return None
    inset_x = min(18, max(5, (ax1 - ax0) // 8))
    inset_y = min(18, max(5, (ay1 - ay0) // 8))
    target = tuple(int(value) for value in (ax0 + inset_x, ay0 + inset_y, ax1 - inset_x, ay1 - inset_y))
    if target[0] >= target[2] or target[1] >= target[3]:
        return None
    return BuildingBinding(
        building_id=building.semantic_id,
        target_roi=target,
        frame_sha256=localization.frame_sha256,
        confidence=min(localization.confidence, building.confidence, 0.99),
        semantic_evidence=("current-frame OCR: Supply Depot", "atlas-predicted helicopter-pad region"),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )


def bind_supply_depot_claim_supply(
    frame: np.ndarray,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
) -> BuildingBinding | None:
    """Bind the navigation-only Claim Supply control on the exact building radial."""

    if not native_frame_guard(frame):
        return None
    try:
        text = _normalized(
            _ocr_roi_text(
                frame,
                SUPPLY_DEPOT_RADIAL_ROI,
                ocr,
                source_frame=source_frame,
                scale=2,
            )
        )
    except ValueError:
        return None
    if not (
        ("claim" in text or "clai" in text)
        and ("supply" in text or "supp" in text or re.search(r"(?:^| )sup[a-z]*(?: |$)", text))
        and ("upgrade" in text or "pgrade" in text or "grade" in text or "rage" in text)
        and ("details" in text or "deta" in text or "etail" in text)
    ):
        return None
    target_roi = SUPPLY_DEPOT_CLAIM_SUPPLY_ROI
    if ocr is _default_ocr:
        radial = _crop(
            frame,
            SUPPLY_DEPOT_RADIAL_ROI,
            source_frame=source_frame,
        )
        radial = cv2.cvtColor(radial, cv2.COLOR_BGR2GRAY) if radial.ndim == 3 else radial
        radial = cv2.resize(radial, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        data = pytesseract.image_to_data(radial, config="--psm 11", output_type=pytesseract.Output.DICT)
        dynamic_roi = _claim_supply_roi_from_data(data)
        if dynamic_roi is None:
            return None
        target_roi = dynamic_roi
    return BuildingBinding(
        building_id=SUPPLY_DEPOT_BUILDING_ID,
        target_roi=target_roi,
        frame_sha256=frame_digest(frame),
        confidence=0.97,
        semantic_evidence=("current-frame Supply Depot radial", "OCR: Claim Supply", "separate Upgrade control observed"),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )


@dataclass(frozen=True)
class SupplyDepotControl:
    column: int
    roi: Box
    reward_kind: str
    state: str
    zero_cost: bool
    confidence: float


@dataclass(frozen=True)
class SupplyDepotScreenRecognition:
    recognized: bool
    state: str
    title_text: str
    controls: tuple[SupplyDepotControl, ...]
    premium_or_purchase_visible: bool
    overlay: bool
    ambiguity: str
    frame_sha256: str
    daily_free_attempts: int | None


def _invalid_ocr_screen(
    frame: np.ndarray,
    *,
    title_text: str,
    reason: str,
    daily_free_attempts: int | None = None,
) -> SupplyDepotScreenRecognition:
    """Return a deterministic, non-actionable explicit-identity OCR failure."""

    return SupplyDepotScreenRecognition(
        recognized=False,
        state="unknown",
        title_text=title_text,
        controls=(),
        premium_or_purchase_visible=False,
        overlay=False,
        ambiguity=reason,
        frame_sha256=frame_digest(frame),
        daily_free_attempts=daily_free_attempts,
    )


def recognize_supply_depot_screen(
    frame: np.ndarray,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
) -> SupplyDepotScreenRecognition:
    """Recognize exact Supply Depot identity and classify every visible bottom control."""

    if not native_frame_guard(frame):
        return SupplyDepotScreenRecognition(False, "unknown", "", (), False, False, "non_native_frame", "", None)
    try:
        title_text = _ocr_roi_text(frame, SUPPLY_DEPOT_TITLE_ROI, ocr, source_frame=source_frame, scale=3)
    except ValueError:
        return SupplyDepotScreenRecognition(False, "unknown", "", (), False, False, "non_native_frame", "", None)
    title = _normalized(title_text)
    if "supply depot" not in title:
        return SupplyDepotScreenRecognition(False, "unknown", title_text, (), False, False, "title_not_recognized", frame_digest(frame), None)

    if source_frame is None:
        attempts_text = _normalized(
            _ocr_roi_text(
                frame,
                SUPPLY_DEPOT_ATTEMPTS_ROI,
                ocr,
                source_frame=None,
                scale=3,
            )
        )
    else:
        try:
            attempts_text = _normalized(
                _ocr_roi_text(
                    frame,
                    SUPPLY_DEPOT_ATTEMPTS_ROI,
                    ocr,
                    source_frame=source_frame,
                    scale=3,
                )
            )
        except ValueError:
            return _invalid_ocr_screen(
                frame,
                title_text=title_text,
                reason="ocr_invalid_attempts",
            )
    attempts_match = re.search(r"daily free attempts\s*(\d{1,2})\b", attempts_text)
    zero_match = re.search(r"daily free attempts\s*o\b", attempts_text)
    daily_free_attempts = int(attempts_match.group(1)) if attempts_match else (0 if zero_match else None)

    if source_frame is None:
        panel_text = _normalized(ocr(_legacy_crop(frame, SUPPLY_DEPOT_PANEL_ROI), 6))
    else:
        try:
            _validate_explicit_identity(source_frame)
            panel_observation = run_semantic_ocr(
                frame,
                CropRoiRequest(source_frame, SUPPLY_DEPOT_PANEL_ROI),
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(),
                ocr_engine=ocr,
            )
        except (SemanticOcrCropError, ValueError):
            return _invalid_ocr_screen(
                frame,
                title_text=title_text,
                reason="ocr_invalid_panel",
                daily_free_attempts=daily_free_attempts,
            )
        if panel_observation.status is ObservationStatus.INVALID:
            return _invalid_ocr_screen(
                frame,
                title_text=title_text,
                reason="ocr_invalid_panel",
                daily_free_attempts=daily_free_attempts,
            )
        panel_text = _normalized(
            panel_observation.text
            if panel_observation.status is ObservationStatus.OK
            else ""
        )
    premium = any(token in panel_text for token in ("diamond", "mall", "purchase", "buy", "$"))
    reward_kinds = ("food", "wood", "steel", "gas")
    controls = []
    for column, (roi, reward_kind) in enumerate(zip(SUPPLY_DEPOT_CONTROL_BANDS, reward_kinds)):
        if source_frame is None:
            text = _normalized(
                _ocr_roi_text(
                    frame,
                    roi,
                    ocr,
                    source_frame=None,
                    scale=3,
                )
            )
        else:
            try:
                text = _normalized(
                    _ocr_roi_text(
                        frame,
                        roi,
                        ocr,
                        source_frame=source_frame,
                        scale=3,
                    )
                )
            except ValueError:
                return _invalid_ocr_screen(
                    frame,
                    title_text=title_text,
                    reason=f"ocr_invalid_control_{column}",
                    daily_free_attempts=daily_free_attempts,
                )
        if "free" in text:
            state, zero_cost, confidence = "available_free", True, 0.98
        elif any(word in text for word in ("cooldown", "collected", "claimed")) or re.search(r"\b\d{1,2}:\d{2}\b", text):
            state, zero_cost, confidence = "collected_or_cooldown", False, 0.90
        elif any(word in text for word in ("mall", "buy", "diamond", "purchase")) or re.search(r"\b\d+\b", text):
            state, zero_cost, confidence = "paid_or_purchase", False, 0.80
            premium = True
        elif not text:
            state, zero_cost, confidence = "not_visible", False, 0.50
        else:
            state, zero_cost, confidence = "ambiguous", False, 0.20
        controls.append(SupplyDepotControl(column, roi, reward_kind, state, zero_cost, confidence))
    ambiguity_reasons = []
    if any(item.state == "ambiguous" for item in controls):
        ambiguity_reasons.append("ambiguous_control")
    if daily_free_attempts is None:
        ambiguity_reasons.append("daily_free_attempts_not_recognized")
    ambiguity = "+".join(ambiguity_reasons) if ambiguity_reasons else "none"
    state = "available" if any(item.zero_cost for item in controls) else "exhausted_or_cooldown"
    if premium and not any(item.zero_cost for item in controls):
        state = "paid_or_purchase"
    return SupplyDepotScreenRecognition(
        True,
        state,
        title_text,
        tuple(controls),
        premium,
        False,
        ambiguity,
        frame_digest(frame),
        daily_free_attempts,
    )
