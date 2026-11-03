"""BlueStacks-native Supply Depot building and screen recognition.

This adapter is intentionally profile-specific.  It never reuses Bliss coordinates,
templates, or thresholds and never dispatches input. Explicitly identified captures use
the shared semantic OCR crop pipeline. Calls that omit an identity retain the legacy
adapter-local crop behavior and make no capture-event claim. OCR never grants authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Callable

import cv2
import numpy as np

from scripts.bounded_tesseract import call_ocr, tesseract_data, tesseract_string

from .home_atlas import BuildingBinding
from .home_atlas_vision import BLUESTACKS_PROFILE_ID, HUD_MASK_RECTS, frame_digest, native_frame_guard
from .perception_bundle import NativeFrameIdentity
from .semantic_ocr_crop import (
    CropRoiRequest,
    DEFAULT_OCR_TIMEOUT_SECONDS,
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
SUPPLY_DEPOT_TITLE_ROI: Box = (200, 5, 620, 70)
SUPPLY_DEPOT_PANEL_ROI: Box = (30, 940, 770, 1270)
SUPPLY_DEPOT_ATTEMPTS_ROI: Box = (100, 800, 700, 950)
SUPPLY_DEPOT_CONTROL_BANDS: tuple[Box, ...] = (
    (0, 1140, 200, 1280),
    (200, 1140, 400, 1280),
    (400, 1140, 600, 1280),
    (600, 1140, 800, 1280),
)
# Radials move with the camera. Search the gameplay band, while actionability
# below independently rejects any target intersecting fixed HUD geometry.
SUPPLY_DEPOT_RADIAL_ROIS: tuple[Box, ...] = (
    (145, 620, 800, 1020), (145, 840, 800, 1120),
    (145, 400, 800, 800), (145, 180, 800, 580),
)
_CLAIM_ICON_PATH = Path(__file__).parent / "assets/supply_depot/800x1280/claim-supply-suitcase.png"
_DETAILS_ICON_PATH = Path(__file__).parent / "assets/supply_depot/800x1280/radial-details-paper.png"


def _default_ocr(image: np.ndarray, psm: int) -> str:
    return call_ocr(tesseract_string, image, config=f"--psm {psm}")


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
    source_png: bytes | None = None,
    padding: PaddingSpec | None = None,
) -> np.ndarray:
    if source_png is not None and source_frame is None:
        raise ValueError("SOURCE_FRAME_REQUIRED")
    if source_frame is None:
        if padding is not None and padding != PaddingSpec():
            raise ValueError("legacy crop does not support padding")
        return _legacy_crop(frame, roi)
    try:
        _validate_explicit_identity(source_frame)
        request = CropRoiRequest(
            source_frame=source_frame,
            source_png=source_png,
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
    source_png: bytes | None = None,
    scale: int = 3,
    grayscale: bool = True,
) -> str:
    if source_png is not None and source_frame is None:
        raise ValueError("SOURCE_FRAME_REQUIRED")
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
            CropRoiRequest(
                source_frame,
                roi,
                ocr_mode=OcrMode.UNIFORM_AND_SPARSE,
                deadline_monotonic=time.monotonic() + DEFAULT_OCR_TIMEOUT_SECONDS,
                source_png=source_png,
            ),
            normalization=tuple(normalization),
            ocr_engine=ocr,
        )
        if observation.status is ObservationStatus.INVALID or observation.reason_code == "OCR_DEADLINE":
            raise ValueError(observation.reason_code)
        return observation.text
    except SemanticOcrCropError as exc:
        raise ValueError("ROI is outside native BlueStacks bounds") from exc


def _claim_text_roi_from_data(data: dict[str, list], *, search_roi: Box, scale: float = 2.0) -> Box | None:
    """Measure the complete, unique current Claim word."""
    claims = []
    for index, raw in enumerate(data.get("text", ())):
        normalized = _normalized(str(raw))
        if normalized.startswith("clai"):
            if normalized != "claim":
                return None
            x = search_roi[0] + float(data["left"][index]) / scale
            y = search_roi[1] + float(data["top"][index]) / scale
            width = float(data["width"][index]) / scale
            height = float(data["height"][index]) / scale
            if not (25 <= width <= 100 and 12 <= height <= 36):
                return None
            if not (search_roi[0] < x < x + width < search_roi[2]
                    and search_roi[1] < y < y + height < search_roi[3]):
                return None
            claims.append((x, y, x + width, y + height))
    if len(claims) != 1:
        return None
    return tuple(int(value) for value in (math.floor(claims[0][0]), math.floor(claims[0][1]),
                                        math.ceil(claims[0][2]), math.ceil(claims[0][3])))


def _claim_label_row_from_data(data: dict[str, list], *, search_roi: Box, scale: float = 2.0) -> Box | None:
    """Find one current Claim control and isolate its stacked lower label row."""
    claim = _claim_text_roi_from_data(data, search_roi=search_roi, scale=scale)
    if claim is None:
        return None
    x0, _y0, x1, y1 = claim
    row = (int(math.floor(x0 - 10)), int(math.ceil(y1 + 2)), int(math.ceil(x1 + 20)), int(math.ceil(y1 + 32)))
    return row if 0 <= row[0] < row[2] <= 800 and 0 <= row[1] < row[3] <= 1280 else None


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def bind_home_event_drawer_toggle(frame: np.ndarray, *, expanded: bool) -> Box | None:
    """Measure a unique down/up chevron inside the native dark drawer rail.

    The caller must independently verify Home before navigation. This binds
    only the drawer toggle; it never grants a building or resource target.
    """
    if not native_frame_guard(frame) or type(expanded) is not bool:
        return None
    x0, y0, x1, y1 = 680, 980, 795, 1110
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array((0, 0, 185), np.uint8), np.array((179, 80, 255), np.uint8))
    _count, labels, stats, _centers = cv2.connectedComponentsWithStats(white)
    candidates = []
    for index, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if not (20 <= width <= 36 and 7 <= height <= 16 and .2 <= area / (width * height) <= .65):
            continue
        glyph = labels[y:y + height, x:x + width] == index
        if not expanded:
            glyph = np.flipud(glyph)
        top = np.flatnonzero(np.any(glyph[:2], axis=0))
        tip = np.flatnonzero(np.any(glyph[-2:], axis=0))
        if (not len(top) or not len(tip) or top[-1] - top[0] < .8 * width
                or tip[-1] - tip[0] > .45 * width
                or abs((tip[-1] + tip[0]) / 2 - (width - 1) / 2) > .15 * width):
            continue
        cy = y0 + y + height // 2
        # The expanded rail extends leftward; its persistent toggle segment
        # remains at the right after collapse and carries the up-chevron/count.
        rail = cv2.cvtColor(frame[cy - 18:cy + 18, 680:790], cv2.COLOR_BGR2GRAY)
        if float(np.mean(rail < 80)) < .85:
            continue
        candidates.append((int(x0 + x - 4), int(y0 + y - 4),
                           int(x0 + x + width + 4), int(y0 + y + height + 4)))
    return candidates[0] if len(candidates) == 1 else None


def _safe_claim_label_region(label: Box) -> Box | None:
    """Choose a real interior of the measured label outside every fixed HUD mask."""
    x0, y0, x1, y1 = label
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        return None
    regions = [(x0 + 2, y0 + 2, x1 - 2, y1 - 2)]
    for hx0, hy0, hx1, hy1 in HUD_MASK_RECTS:
        remaining = []
        for rx0, ry0, rx1, ry1 in regions:
            if rx1 <= hx0 or hx1 <= rx0 or ry1 <= hy0 or hy1 <= ry0:
                remaining.append((rx0, ry0, rx1, ry1))
                continue
            remaining.extend(((rx0, ry0, min(rx1, hx0), ry1),
                              (max(rx0, hx1), ry0, rx1, ry1),
                              (rx0, ry0, rx1, min(ry1, hy0)),
                              (rx0, max(ry0, hy1), rx1, ry1)))
        regions = [box for box in remaining if box[2] - box[0] >= 16 and box[3] - box[1] >= 12]
    return max(regions, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), default=None)


def _validated_icon_template(path: Path, *, identity: str, shape: tuple[int, int]) -> np.ndarray | None:
    try:
        raw = path.read_bytes()
        manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or manifest.get("id") != identity
                or manifest.get("runtime_profile") != "native-800x1280"
                or manifest.get("file_sha256") != hashlib.sha256(raw).hexdigest()):
            return None
        icon = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        return icon if icon is not None and icon.shape == shape else None
    except (OSError, ValueError, TypeError):
        return None


def _claim_icon_template() -> np.ndarray | None:
    return _validated_icon_template(_CLAIM_ICON_PATH, identity="claim-supply-suitcase", shape=(38, 42))


def _details_radial_candidate_roi(frame: np.ndarray) -> Box | None:
    """Propose a tight OCR crop; this generic icon grants no menu or target authority."""
    icon = _validated_icon_template(_DETAILS_ICON_PATH, identity="radial-details-paper", shape=(43, 38))
    if icon is None or not native_frame_guard(frame):
        return None
    pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    pixels = cv2.normalize(pixels, None, 0, 255, cv2.NORM_MINMAX)
    icon = cv2.normalize(icon, None, 0, 255, cv2.NORM_MINMAX)
    scores = cv2.matchTemplate(pixels, icon, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if not math.isfinite(score) or score < .90:
        return None
    other = scores.copy()
    other[max(0, y - 30):y + 31, max(0, x - 30):x + 31] = -1.
    if float(other.max()) >= .90:
        return None
    return (max(0, x - 25), max(0, y - 48), min(800, x + 319), min(1280, y + 122))


def _claim_button_interior(frame: np.ndarray, claim: Box, label_row: Box) -> Box | None:
    """Bind the measured circular button; text below the button is not clickable."""
    height = claim[3] - claim[1]
    width = claim[2] - claim[0]
    search = (max(0, claim[0] - width), max(0, claim[1] - 5 * height),
              min(800, claim[2] + width), min(1280, label_row[3] + 4))
    x0, y0, x1, y1 = search
    pixels = cv2.normalize(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY),
                           None, 0, 255, cv2.NORM_MINMAX)
    icon = _claim_icon_template()
    if icon is None or pixels.shape[0] < icon.shape[0] or pixels.shape[1] < icon.shape[1]:
        return None
    scores = cv2.matchTemplate(pixels, icon, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    if not math.isfinite(score) or score < .88:
        return None
    ix, iy = location
    # Nearby peaks describe the same icon; a second separated match is ambiguous.
    other = scores.copy()
    other[max(0, iy - 19):iy + 20, max(0, ix - 21):ix + 22] = -1.
    if float(other.max()) >= .88:
        return None
    icon_box = (x0 + ix, y0 + iy, x0 + ix + icon.shape[1], y0 + iy + icon.shape[0])
    icon_center = ((icon_box[0] + icon_box[2]) / 2., (icon_box[1] + icon_box[3]) / 2.)
    # Preserve established circle proposals. If contrast suppresses the proposal
    # entirely, try broader voting but require tighter centering on the measured
    # icon. Final boundary support and safe interior checks remain unchanged.
    smoothed = cv2.GaussianBlur(pixels, (5, 5), 1.2)
    circles = cv2.HoughCircles(smoothed, cv2.HOUGH_GRADIENT,
        dp=1, minDist=45, param1=80, param2=30, minRadius=28, maxRadius=48)
    fallback_proposal = circles is None
    if fallback_proposal:
        circles = cv2.HoughCircles(smoothed, cv2.HOUGH_GRADIENT,
            dp=1, minDist=45, param1=80, param2=20, minRadius=28, maxRadius=48)
    if circles is None:
        return None
    candidates = []
    edges = cv2.Canny(pixels, 50, 150)
    for local_x, local_y, radius in circles[0]:
        cx, cy, radius = float(local_x + x0), float(local_y + y0), float(radius)
        if (not x0 + 2 < cx - radius < cx + radius < x1 - 2
                or not y0 + 2 < cy - radius < cy + radius < y1 - 2
                or abs(cx - (claim[0] + claim[2]) / 2.) > radius * .35
                or not radius * .35 <= claim[1] - cy <= radius * 1.2
                or math.dist((cx, cy), icon_center) > radius * .3
                or (fallback_proposal and math.dist((cx, cy), icon_center) > max(icon.shape) * .15)
                or any(math.dist((cx, cy), point) > radius - 3 for point in (
                    icon_box[:2], icon_box[2:], (icon_box[0], icon_box[3]), (icon_box[2], icon_box[1])))):
            continue
        support = 0
        for angle in np.linspace(0., 2. * math.pi, 72, endpoint=False):
            supported = False
            for distance in np.linspace(radius - 3, radius + 3, 7):
                px = int(round(local_x + distance * math.cos(angle)))
                py = int(round(local_y + distance * math.sin(angle)))
                supported |= bool(np.any(edges[max(0, py - 1):py + 2, max(0, px - 1):px + 2]))
            support += supported
        if support < 58:
            continue
        # Erosion proves every pixel of the eventual 16x12 rectangle lies in
        # the true circle interior and outside every unchanged fixed HUD mask.
        yy, xx = np.ogrid[y0:y1, x0:x1]
        allowed = np.uint8((xx - cx) ** 2 + (yy - cy) ** 2 <= (radius - 4) ** 2)
        for hx0, hy0, hx1, hy1 in HUD_MASK_RECTS:
            allowed[max(0, hy0 - y0):max(0, min(y1, hy1) - y0),
                    max(0, hx0 - x0):max(0, min(x1, hx1) - x0)] = 0
        centers = cv2.erode(allowed, np.ones((12, 16), dtype=np.uint8), borderType=cv2.BORDER_CONSTANT)
        points = np.argwhere(centers)
        if not len(points):
            continue
        clearance = cv2.distanceTransform(allowed, cv2.DIST_L2, 5)
        py, px = max(points, key=lambda point: (float(clearance[point[0], point[1]]),
                    -math.dist((point[1] + x0, point[0] + y0), (cx, cy))))
        target = (int(px + x0 - 8), int(py + y0 - 6), int(px + x0 + 8), int(py + y0 + 6))
        if any(math.dist((cx, cy), point) > radius - 4 for point in (
                target[:2], target[2:], (target[0], target[3]), (target[2], target[1]))):
            continue
        candidates.append(target)
    return candidates[0] if len(candidates) == 1 else None






def _recognized_supply_radial_roi(
    frame: np.ndarray,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
    source_png: bytes | None = None,
) -> Box | None:
    if not native_frame_guard(frame):
        return None
    # A generic Details icon only proposes a smaller crop; all identity checks
    # below remain mandatory. Broad bands retain the existing fallback.
    candidate = _details_radial_candidate_roi(frame)
    rois = ((candidate,) if candidate is not None else ()) + SUPPLY_DEPOT_RADIAL_ROIS
    for roi in rois:
        try:
            text = _normalized(_ocr_roi_text(
                frame, roi, ocr, source_frame=source_frame,
                source_png=source_png, scale=2,
            ))
        except ValueError:
            if candidate is not None and roi == candidate:
                continue
            return None
        if (
            ("claim" in text or "clai" in text)
            and ("supply" in text or "supp" in text or re.search(r"(?:^| )sup[a-z]*(?: |$)", text))
            and ("upgrade" in text or "pgrade" in text or "grade" in text or "rage" in text)
            # Sparse OCR can split the edge-clipped Details caption as "Det".
            # This identifies the menu only; binding still needs a complete
            # Claim label and an independent suitcase/circle interior clear of HUD.
            and ("details" in text or "deta" in text or "etail" in text
                 or re.search(r"(?:^| )det(?: |$)", text))
        ):
            return roi
    return None


def recognize_supply_depot_radial(
    frame: np.ndarray,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
    source_png: bytes | None = None,
) -> bool:
    """Recognize the menu identity separately from actionable label binding."""
    return _recognized_supply_radial_roi(
        frame, ocr=ocr, source_frame=source_frame, source_png=source_png,
    ) is not None


def bind_supply_depot_claim_supply(
    frame: np.ndarray,
    *,
    ocr: OCR = _default_ocr,
    source_frame: NativeFrameIdentity | None = None,
    source_png: bytes | None = None,
) -> BuildingBinding | None:
    """Bind navigation by exact Claim, identified radial and clear button body.

    The lower Supply caption may be covered while the button remains provable.
    It supplies no target authority: the unique suitcase, circular interior and
    every target pixel's HUD clearance are independently required below.
    """

    from scripts.bluestacks_popup_recognition import recognize_reset_popup

    if not native_frame_guard(frame):
        return None
    popup = recognize_reset_popup(frame)
    if popup.get("recognized") or popup.get("blocking_unknown_modal"):
        return None
    search_roi = _recognized_supply_radial_roi(frame, ocr=ocr, source_frame=source_frame, source_png=source_png)
    if search_roi is None:
        return None
    try:
        radial = _crop(frame, search_roi, source_frame=source_frame, source_png=source_png)
        radial = cv2.cvtColor(radial, cv2.COLOR_BGR2GRAY) if radial.ndim == 3 else radial
        radial = cv2.resize(radial, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        data = call_ocr(tesseract_data, radial, call_timeout=5, config="--psm 11")
    except (RuntimeError, OSError, ValueError):
        return None
    claim = _claim_text_roi_from_data(data, search_roi=search_roi)
    label_row = _claim_label_row_from_data(data, search_roi=search_roi)
    if claim is None and not any(_normalized(str(word)).startswith("clai") for word in data.get("text", ())):
        # Adjacent HUD artwork can merge the Claim caption in the broad sparse
        # pass. The unique current Details icon proposes only a tighter OCR band;
        # complete Claim text and the independent safe button remain mandatory.
        candidate = _details_radial_candidate_roi(frame)
        if candidate is not None:
            x, y, _, _ = candidate
            caption_roi = (x + 185, y + 70, min(800, x + 280), min(1280, y + 130))
            try:
                caption = _crop(frame, caption_roi, source_frame=source_frame, source_png=source_png)
                caption = cv2.cvtColor(caption, cv2.COLOR_BGR2GRAY) if caption.ndim == 3 else caption
                caption = cv2.resize(caption, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                caption_data = call_ocr(tesseract_data, caption, call_timeout=5, config="--psm 11")
                claim = _claim_text_roi_from_data(caption_data, search_roi=caption_roi)
                label_row = _claim_label_row_from_data(caption_data, search_roi=caption_roi)
            except (RuntimeError, OSError, ValueError):
                return None
    if claim is None or label_row is None:
        return None
    # Captions are evidence, not tap targets: do not impose the button's 16x12
    # clickable minimum on text, but reject a caption wholly behind fixed HUD.
    if any(x0 <= claim[0] and claim[2] <= x1 and y0 <= claim[1] and claim[3] <= y1
           for x0, y0, x1, y1 in HUD_MASK_RECTS):
        return None
    # The measured lower row bounds the icon search; its partially covered
    # text is not substituted for a current button observation.
    target_roi = _claim_button_interior(frame, claim, label_row)
    if target_roi is None:
        return None
    return BuildingBinding(
        building_id=SUPPLY_DEPOT_BUILDING_ID,
        target_roi=target_roi,
        frame_sha256=frame_digest(frame),
        confidence=0.97,
        semantic_evidence=("current-frame Supply Depot radial", "OCR: complete Claim with Supply radial context", "separate Upgrade control observed",
                           "unique current suitcase icon inside measured circular Claim button",
                           "all target pixels inside button and clear of fixed HUD"),
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
    source_png: bytes | None = None,
) -> SupplyDepotScreenRecognition:
    """Recognize exact Supply Depot identity and classify every visible bottom control."""

    if not native_frame_guard(frame):
        return SupplyDepotScreenRecognition(False, "unknown", "", (), False, False, "non_native_frame", "", None)

    def _title_ocr(*, explicit: NativeFrameIdentity | None) -> str:
        return _ocr_roi_text(frame, SUPPLY_DEPOT_TITLE_ROI, ocr, source_frame=explicit, source_png=source_png, scale=3)

    try:
        title_text = _title_ocr(explicit=source_frame)
    except ValueError:
        if source_frame is None:
            return SupplyDepotScreenRecognition(
                False, "unknown", "", (), False, False, "non_native_frame", frame_digest(frame), None
            )
        return _invalid_ocr_screen(frame, title_text="", reason="ocr_invalid_title")
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
                    source_png=source_png,
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
                CropRoiRequest(
                    source_frame,
                    SUPPLY_DEPOT_PANEL_ROI,
                    ocr_mode=OcrMode.UNIFORM_BLOCK,
                    deadline_monotonic=time.monotonic() + DEFAULT_OCR_TIMEOUT_SECONDS,
                    source_png=source_png,
                ),
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
        else:
            if panel_observation.status is ObservationStatus.INVALID or panel_observation.reason_code == "OCR_DEADLINE":
                return _invalid_ocr_screen(
                    frame,
                    title_text=title_text,
                    reason="ocr_invalid_panel",
                    daily_free_attempts=daily_free_attempts,
                )
            else:
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
                        source_png=source_png,
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
