"""Campaign atlas-backed chapter navigation for live Campaign AP.

ORB tile localization can fail on live Story maps (large residual). When that happens,
visible OCR chapter nodes that also exist as atlas landmarks become control points for a
translation-only screen↔atlas estimate. That estimate projects the configured chapter
landmark, narrows template search, and chooses HUD-safe pans — OCR residual number-pans
are not the primary navigator.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from tasks.campaign_atlas import (
    CAMPAIGN_PROFILE_ID,
    DEFAULT_ATLAS_ARTIFACT_ROOT,
    DEFAULT_ATLAS_ID,
    Box,
    CampaignAmbiguityState,
    CampaignAtlas,
    CampaignDestinationKind,
    CampaignLocalizationResult,
    LandmarkKind,
    load_campaign_atlas,
    resolve_campaign_consumer_destination,
)
from tasks.campaign_atlas_vision import (
    BlueStacksCampaignLocalizer,
    bind_campaign_destination_from_current_frame,
    frame_digest,
    hud_safe_pan_gesture,
    native_campaign_frame_guard,
)

NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
DEFAULT_CAMPAIGN_ATLAS_PATH = DEFAULT_ATLAS_ARTIFACT_ROOT / DEFAULT_ATLAS_ID / "atlas.json"


@dataclass(frozen=True)
class AtlasChapterNavDecision:
    kind: str  # tap | swipe | blocked
    reason: str
    target_identity: str | None = None
    target_roi: Box | None = None
    swipe: tuple[int, int, int, int, int] | None = None
    pan_direction: str | None = None
    localization_recognized: bool = False
    binding_bound: bool = False
    projected_screen_center: tuple[float, float] | None = None
    distance_to_screen_center_px: float | None = None
    anchor_count: int = 0
    localization_support: tuple[str, ...] = ()
    localization_residual_px: float | None = None


_ATLAS: CampaignAtlas | None = None
_LOCALIZER: BlueStacksCampaignLocalizer | None = None
_ATLAS_PATH: Path | None = None


def default_campaign_atlas_path() -> Path:
    return DEFAULT_CAMPAIGN_ATLAS_PATH


def load_live_campaign_atlas(atlas_path: Path | None = None) -> tuple[CampaignAtlas, Path]:
    path = Path(atlas_path) if atlas_path is not None else default_campaign_atlas_path()
    if not path.is_file():
        raise FileNotFoundError(f"accepted Campaign atlas is absent: {path.as_posix()}")
    return load_campaign_atlas(path), path


def _cached_atlas_and_localizer(
    atlas_path: Path | None = None,
) -> tuple[CampaignAtlas, BlueStacksCampaignLocalizer, Path]:
    global _ATLAS, _LOCALIZER, _ATLAS_PATH
    path = Path(atlas_path) if atlas_path is not None else default_campaign_atlas_path()
    if _ATLAS is None or _LOCALIZER is None or _ATLAS_PATH != path.resolve():
        atlas, resolved = load_live_campaign_atlas(path)
        _ATLAS = atlas
        _ATLAS_PATH = resolved.resolve()
        _LOCALIZER = BlueStacksCampaignLocalizer(atlas, resolved)
    return _ATLAS, _LOCALIZER, _ATLAS_PATH


def _box_center(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def localization_from_single_near_anchor(
    *,
    atlas: CampaignAtlas,
    visible_chapter_rois: Mapping[int, Box],
    frame_sha256: str,
    target_chapter: int,
) -> tuple[CampaignLocalizationResult | None, int]:
    """Project using one atlas-known chapter within 8 of the destination."""

    near: list[tuple[int, Box]] = []
    for number, roi in visible_chapter_rois.items():
        if abs(number - target_chapter) > 8:
            continue
        landmark = atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label=f"Chapter {number}")
        if landmark is None or not landmark.spatially_associated:
            continue
        near.append((number, roi))
    if not near:
        return None, 0
    near.sort(key=lambda item: abs(item[0] - target_chapter))
    number, roi = near[0]
    landmark = atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label=f"Chapter {number}")
    assert landmark is not None
    screen = _box_center(roi)
    atlas_center = _box_center(landmark.atlas_roi)
    tx = atlas_center[0] - screen[0]
    ty = atlas_center[1] - screen[1]
    matrix = (
        (1.0, 0.0, tx),
        (0.0, 1.0, ty),
        (0.0, 0.0, 1.0),
    )
    return (
        CampaignLocalizationResult(
            True,
            CAMPAIGN_PROFILE_ID,
            matrix,
            0.7,
            0.0,
            (f"chapter-{number}",),
            CampaignAmbiguityState.NONE,
            frame_sha256,
        ),
        1,
    )


def localization_from_chapter_anchors(
    *,
    atlas: CampaignAtlas,
    visible_chapter_rois: Mapping[int, Box],
    frame_sha256: str,
    target_chapter: int | None = None,
) -> tuple[CampaignLocalizationResult | None, int]:
    """Estimate translation-only screen→atlas from OCR chapters that exist in the atlas."""

    candidates: list[tuple[int, float, float, str]] = []
    for number, roi in sorted(visible_chapter_rois.items()):
        landmark = atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label=f"Chapter {number}")
        if landmark is None or not landmark.spatially_associated:
            continue
        screen = _box_center(roi)
        atlas_center = _box_center(landmark.atlas_roi)
        # screen_to_atlas translation: atlas = screen + (tx, ty)
        candidates.append(
            (
                number,
                atlas_center[0] - screen[0],
                atlas_center[1] - screen[1],
                f"chapter-{number}",
            )
        )
    if target_chapter is not None and len(candidates) > 2:
        # Prefer atlas-known chapters near the destination; distant OCR digits are weak anchors.
        candidates.sort(key=lambda item: abs(item[0] - target_chapter))
        near = [item for item in candidates if abs(item[0] - target_chapter) <= 8]
        if len(near) >= 2:
            candidates = near
        else:
            candidates = candidates[: max(2, min(4, len(candidates)))]
    if len(candidates) < 2:
        return None, len(candidates)

    txs = sorted(item[1] for item in candidates)
    tys = sorted(item[2] for item in candidates)
    mid = len(candidates) // 2
    if len(candidates) % 2:
        median_tx = txs[mid]
        median_ty = tys[mid]
    else:
        median_tx = (txs[mid - 1] + txs[mid]) / 2.0
        median_ty = (tys[mid - 1] + tys[mid]) / 2.0
    inliers = [
        item
        for item in candidates
        if ((item[1] - median_tx) ** 2 + (item[2] - median_ty) ** 2) ** 0.5 <= 120.0
    ]
    if len(inliers) < 2:
        inliers = candidates[:2]
    tx = float(sum(item[1] for item in inliers) / len(inliers))
    ty = float(sum(item[2] for item in inliers) / len(inliers))
    residual = float(
        sum((((item[1] - tx) ** 2 + (item[2] - ty) ** 2) ** 0.5) for item in inliers)
        / len(inliers)
    )
    matrix: tuple[tuple[float, float, float], ...] = (
        (1.0, 0.0, tx),
        (0.0, 1.0, ty),
        (0.0, 0.0, 1.0),
    )
    return (
        CampaignLocalizationResult(
            True,
            CAMPAIGN_PROFILE_ID,
            matrix,
            min(0.95, 0.55 + 0.08 * len(inliers)),
            residual,
            tuple(item[3] for item in inliers[:3]),
            CampaignAmbiguityState.NONE,
            frame_sha256,
        ),
        len(inliers),
    )


def projected_landmark_screen_center(
    localization: CampaignLocalizationResult,
    atlas_roi: Box,
) -> tuple[float, float] | None:
    if not localization.recognized or localization.screen_to_atlas is None:
        return None
    tx = float(localization.screen_to_atlas[0][2])
    ty = float(localization.screen_to_atlas[1][2])
    ax, ay = _box_center(atlas_roi)
    return (ax - tx, ay - ty)


def pan_direction_toward_screen_point(screen_x: float, screen_y: float) -> str:
    dx = screen_x - (NATIVE_WIDTH / 2.0)
    dy = screen_y - (NATIVE_HEIGHT / 2.0)
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "bottom" if dy > 0 else "top"


ORB_PREFERRED_RESIDUAL_PX = 12.0
CHAPTER_SAFE_VIEWPORT: Box = (160, 180, 700, 980)
LOCAL_OCR_PAD_PX = 120
LOCAL_OCR_MAX_PROJECTION_DISTANCE_PX = 100.0


def projection_is_safely_framed(screen_x: float, screen_y: float) -> bool:
    """True when a projected chapter center is clear of fixed HUD and edge overlays."""

    x0, y0, x1, y1 = CHAPTER_SAFE_VIEWPORT
    return x0 <= screen_x <= x1 and y0 <= screen_y <= y1


def chapter_roi_is_safely_framed(roi: Box) -> bool:
    """Require the complete current-frame chapter binding inside the safe viewport."""

    x0, y0, x1, y1 = CHAPTER_SAFE_VIEWPORT
    return x0 <= roi[0] and y0 <= roi[1] and roi[2] <= x1 and roi[3] <= y1


def ocr_chapter_roi_near_projection(
    frame: np.ndarray,
    *,
    chapter: int,
    projected_screen_center: tuple[float, float],
    pad_px: int = LOCAL_OCR_PAD_PX,
) -> Box | None:
    """Bind the chapter digit near an atlas projection when the red-badge OCR pass misses it."""

    import cv2
    import pytesseract

    cx, cy = projected_screen_center
    x0 = max(0, int(cx) - pad_px)
    y0 = max(0, int(cy) - pad_px)
    x1 = min(NATIVE_WIDTH, int(cx) + pad_px)
    y1 = min(NATIVE_HEIGHT, int(cy) + pad_px)
    if x1 - x0 < 24 or y1 - y0 < 24:
        return None
    crop = frame[y0:y1, x0:x1]
    if crop.ndim != 3 or crop.shape[2] < 3:
        variants = (np.asarray(crop),)
    else:
        # Live captures may be RGB or BGR; try both gray conversions plus inversions.
        variants = (
            cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY),
            cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
        )
    needle = str(chapter)
    best: tuple[float, Box] | None = None
    for gray in variants:
        for image in (gray, 255 - gray):
            enlarged = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            for processed, scale in ((image, 1.0), (enlarged, 2.0)):
                for psm in (6, 11):
                    data = pytesseract.image_to_data(
                        processed,
                        config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
                        output_type=pytesseract.Output.DICT,
                    )
                    for index, text in enumerate(data["text"]):
                        token = str(text).strip()
                        if token != needle:
                            continue
                        left = int(round(int(data["left"][index]) / scale))
                        top = int(round(int(data["top"][index]) / scale))
                        width = int(round(int(data["width"][index]) / scale))
                        height = int(round(int(data["height"][index]) / scale))
                        # Native chapter medallion digits are materially larger than HUD/event
                        # badge counters. Reject tiny isolated digits before proximity ranking so
                        # a projected Chapter 2 cannot bind the unrelated lower-left "2x3" badge.
                        if width < 14 or height < 24 or width > 60 or height > 60:
                            continue
                        roi = (x0 + left, y0 + top, x0 + left + width, y0 + top + height)
                        center = _box_center(roi)
                        dist = ((center[0] - cx) ** 2 + (center[1] - cy) ** 2) ** 0.5
                        if dist > LOCAL_OCR_MAX_PROJECTION_DISTANCE_PX:
                            continue
                        if best is None or dist < best[0]:
                            best = (float(dist), roi)
    if best is not None:
        return best[1]

    # Chapter 2's dark medallion digit is weak on the current BlueStacks renderer,
    # while its independently retained semantic label "Eclipolis" remains clear.
    # The difficulty-2 atlas landmark can be displaced from the rendered medallion,
    # so use a wider bounded search. Prefer digit+label association; when the dark
    # digit is not OCR-readable, derive the medallion immediately left of the exact
    # retained Eclipolis renderer stem. Never tap the text label itself.
    if chapter == 2:
        wide_pad = 220
        wx0 = max(0, int(cx) - wide_pad)
        wy0 = max(0, int(cy) - wide_pad)
        wx1 = min(NATIVE_WIDTH, int(cx) + wide_pad)
        wy1 = min(NATIVE_HEIGHT, int(cy) + wide_pad)
        wide = frame[wy0:wy1, wx0:wx1]
        wide_variants = (
            cv2.cvtColor(wide, cv2.COLOR_RGB2GRAY),
            cv2.cvtColor(wide, cv2.COLOR_BGR2GRAY),
        )
        digit_candidates: list[Box] = []
        label_candidates: list[Box] = []
        for gray in wide_variants:
            enlarged = cv2.resize(
                gray,
                None,
                fx=2.0,
                fy=2.0,
                interpolation=cv2.INTER_CUBIC,
            )
            for processed, scale in ((gray, 1.0), (enlarged, 2.0)):
                digit_data = pytesseract.image_to_data(
                    processed,
                    config="--psm 11 -c tessedit_char_whitelist=0123456789",
                    output_type=pytesseract.Output.DICT,
                )
                for index, text in enumerate(digit_data["text"]):
                    if str(text).strip() != "2":
                        continue
                    left = int(round(int(digit_data["left"][index]) / scale))
                    top = int(round(int(digit_data["top"][index]) / scale))
                    width = int(round(int(digit_data["width"][index]) / scale))
                    height = int(round(int(digit_data["height"][index]) / scale))
                    if width < 10 or height < 24 or width > 60 or height > 60:
                        continue
                    roi = (
                        wx0 + left,
                        wy0 + top,
                        wx0 + left + width,
                        wy0 + top + height,
                    )
                    center = _box_center(roi)
                    if (
                        (center[0] - cx) ** 2 + (center[1] - cy) ** 2
                    ) ** 0.5 <= wide_pad:
                        digit_candidates.append(roi)
                data = pytesseract.image_to_data(
                    processed,
                    config="--psm 11",
                    output_type=pytesseract.Output.DICT,
                )
                for index, text in enumerate(data["text"]):
                    token = "".join(character for character in str(text).casefold() if character.isalpha())
                    if token not in {"eclipolis", "eclips"}:
                        continue
                    left = int(round(int(data["left"][index]) / scale))
                    top = int(round(int(data["top"][index]) / scale))
                    width = int(round(int(data["width"][index]) / scale))
                    height = int(round(int(data["height"][index]) / scale))
                    label_roi = (
                        wx0 + left,
                        wy0 + top,
                        wx0 + left + width,
                        wy0 + top + height,
                    )
                    label_candidates.append(label_roi)
        associated: list[tuple[float, Box]] = []
        for digit_roi in digit_candidates:
            digit_center = _box_center(digit_roi)
            for label_roi in label_candidates:
                label_center = _box_center(label_roi)
                separation = (
                    (digit_center[0] - label_center[0]) ** 2
                    + (digit_center[1] - label_center[1]) ** 2
                ) ** 0.5
                if separation <= 160.0:
                    associated.append((separation, digit_roi))
        for _separation, target in sorted(associated, key=lambda item: item[0]):
            if chapter_roi_is_safely_framed(target):
                return target
        for label_roi in label_candidates:
            label_center = _box_center(label_roi)
            target = (
                max(0, label_roi[0] - 100),
                max(0, int(round(label_center[1])) - 45),
                max(0, label_roi[0] - 20),
                min(NATIVE_HEIGHT, int(round(label_center[1])) + 45),
            )
            target_center = _box_center(target)
            projection_distance = (
                (target_center[0] - cx) ** 2
                + (target_center[1] - cy) ** 2
            ) ** 0.5
            if (
                projection_distance <= wide_pad
                and target[2] <= label_roi[0]
                and chapter_roi_is_safely_framed(target)
            ):
                return target
    return None


def _pick_localization(
    *,
    atlas: CampaignAtlas,
    localizer: BlueStacksCampaignLocalizer,
    frame: np.ndarray,
    digest: str,
    visible_chapter_rois: Mapping[int, Box] | None,
    target_chapter: int,
) -> tuple[CampaignLocalizationResult, int, str]:
    """Prefer low-residual ORB over weak single OCR anchors that skip the atlas tiles."""

    anchored: CampaignLocalizationResult | None = None
    single: CampaignLocalizationResult | None = None
    anchor_count = 0
    if visible_chapter_rois:
        anchored, anchor_count = localization_from_chapter_anchors(
            atlas=atlas,
            visible_chapter_rois=visible_chapter_rois,
            frame_sha256=digest,
            target_chapter=target_chapter,
        )
        single, single_count = localization_from_single_near_anchor(
            atlas=atlas,
            visible_chapter_rois=visible_chapter_rois,
            frame_sha256=digest,
            target_chapter=target_chapter,
        )
        if single is not None and anchor_count < 2:
            anchor_count = single_count

    orb = localizer.localize(frame, campaign_screen_recognized=True)
    orb_state = str(orb.ambiguity_state)
    orb_residual = float(orb.residual_px) if orb.recognized and orb.residual_px is not None else None
    if orb.recognized and orb_residual is not None and orb_residual <= ORB_PREFERRED_RESIDUAL_PX:
        return orb, anchor_count, f"orb_residual={orb_residual:.2f}"

    if anchored is not None and (anchored.residual_px or 0) <= 120.0:
        return anchored, anchor_count, f"ocr_anchors={anchor_count};orb={orb_state}"
    if single is not None:
        return single, max(anchor_count, 1), f"ocr_single_anchor;orb={orb_state}"
    if anchored is not None:
        return anchored, anchor_count, f"ocr_anchors_weak={anchor_count};orb={orb_state}"
    return orb, anchor_count, f"orb_fallback={orb_state}"


def resolve_atlas_chapter_navigation(
    frame: np.ndarray,
    *,
    destination_id: str,
    visible_chapter_rois: Mapping[int, Box] | None = None,
    atlas_path: Path | None = None,
) -> AtlasChapterNavDecision:
    """Prefer atlas landmark bind; otherwise atlas-directed HUD-safe pan; never OCR number-pan."""

    if not native_campaign_frame_guard(frame):
        return AtlasChapterNavDecision(
            kind="blocked",
            reason="Campaign atlas chapter navigation requires a native 800x1280 frame",
        )
    try:
        atlas, localizer, _path = _cached_atlas_and_localizer(atlas_path)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return AtlasChapterNavDecision(
            kind="blocked",
            reason=f"Campaign atlas unavailable for chapter navigation: {exc}",
        )

    digest = frame_digest(frame)
    kind, label = resolve_campaign_consumer_destination("campaign_ap", destination_id)
    if kind is not CampaignDestinationKind.CHAPTER:
        return AtlasChapterNavDecision(
            kind="blocked",
            reason="Campaign AP atlas chapter navigation requires a chapter destination",
        )
    landmark = atlas.lookup_landmark(kind=LandmarkKind.CHAPTER, label=label)
    if landmark is None or not landmark.spatially_associated:
        return AtlasChapterNavDecision(
            kind="blocked",
            reason=f"accepted Campaign atlas lacks spatially associated landmark for {label}",
        )

    target_chapter = int(destination_id.split("-")[1])
    localization, anchor_count, loc_state = _pick_localization(
        atlas=atlas,
        localizer=localizer,
        frame=frame,
        digest=digest,
        visible_chapter_rois=visible_chapter_rois,
        target_chapter=target_chapter,
    )
    support = tuple(str(item) for item in (localization.supporting_viewports or ()))
    residual = float(localization.residual_px) if localization.residual_px is not None else None

    binding = bind_campaign_destination_from_current_frame(
        frame,
        atlas=atlas,
        localization=localization,
        consumer="campaign_ap",
        destination_id=destination_id,
    )
    projected = projected_landmark_screen_center(localization, landmark.atlas_roi)
    distance = None
    if projected is not None:
        distance = float(
            ((projected[0] - NATIVE_WIDTH / 2.0) ** 2 + (projected[1] - NATIVE_HEIGHT / 2.0) ** 2)
            ** 0.5
        )

    target_identity = f"campaign-chapter-{destination_id.split('-')[1]}"
    safely_projected = bool(
        localization.recognized
        and projected is not None
        and projection_is_safely_framed(projected[0], projected[1])
    )
    if localization.recognized and projected is not None and not safely_projected:
        direction = pan_direction_toward_screen_point(projected[0], projected[1])
        gesture = hud_safe_pan_gesture(direction)
        return AtlasChapterNavDecision(
            kind="swipe",
            reason=(
                f"Campaign atlas-directed pan {direction} to safely frame {label} before binding "
                f"(bound={binding.bound}; {binding.reason}; {loc_state})"
            ),
            swipe=gesture.as_swipe(),
            pan_direction=direction,
            localization_recognized=True,
            binding_bound=False,
            projected_screen_center=projected,
            distance_to_screen_center_px=distance,
            anchor_count=anchor_count,
            localization_support=support,
            localization_residual_px=residual,
        )

    if (
        safely_projected
        and binding.bound
        and binding.current_frame_roi is not None
        and chapter_roi_is_safely_framed(binding.current_frame_roi)
    ):
        return AtlasChapterNavDecision(
            kind="tap",
            reason=f"Campaign atlas current-frame bind for {label}",
            target_identity=target_identity,
            target_roi=binding.current_frame_roi,
            localization_recognized=bool(localization.recognized),
            binding_bound=True,
            projected_screen_center=projected,
            distance_to_screen_center_px=distance,
            anchor_count=anchor_count,
            localization_support=support,
            localization_residual_px=residual,
        )

    if (
        localization.recognized
        and projected is not None
        and safely_projected
    ):
        ocr_roi = ocr_chapter_roi_near_projection(
            frame,
            chapter=target_chapter,
            projected_screen_center=projected,
        )
        if ocr_roi is not None and chapter_roi_is_safely_framed(ocr_roi):
            return AtlasChapterNavDecision(
                kind="tap",
                reason=(
                    f"Campaign atlas projection + local OCR bind for {label} "
                    f"(template={binding.reason}; {loc_state})"
                ),
                target_identity=target_identity,
                target_roi=ocr_roi,
                localization_recognized=True,
                binding_bound=False,
                projected_screen_center=projected,
                distance_to_screen_center_px=distance,
                anchor_count=anchor_count,
                localization_support=support,
                localization_residual_px=residual,
            )
        return AtlasChapterNavDecision(
            kind="blocked",
            reason=(
                f"Campaign atlas projected {label} on-screen but could not bind it "
                f"(template={binding.reason}; local OCR miss/unsafe/misaligned; {loc_state})"
            ),
            localization_recognized=True,
            binding_bound=False,
            projected_screen_center=projected,
            distance_to_screen_center_px=distance,
            anchor_count=anchor_count,
            localization_support=support,
            localization_residual_px=residual,
        )

    if localization.recognized and projected is not None:
        direction = pan_direction_toward_screen_point(projected[0], projected[1])
        gesture = hud_safe_pan_gesture(direction)
        return AtlasChapterNavDecision(
            kind="swipe",
            reason=(
                f"Campaign atlas-directed pan {direction} toward {label} "
                f"(bound={binding.bound}; {binding.reason}; {loc_state})"
            ),
            swipe=gesture.as_swipe(),
            pan_direction=direction,
            localization_recognized=True,
            binding_bound=False,
            projected_screen_center=projected,
            distance_to_screen_center_px=distance,
            anchor_count=anchor_count,
            localization_support=support,
            localization_residual_px=residual,
        )

    return AtlasChapterNavDecision(
        kind="blocked",
        reason=(
            "Campaign atlas could not localize the current Story map or bind "
            f"{label} ({loc_state}; anchors={anchor_count}; bind={binding.reason})"
        ),
        localization_recognized=bool(localization.recognized),
        binding_bound=False,
        projected_screen_center=projected,
        distance_to_screen_center_px=distance,
        anchor_count=anchor_count,
        localization_support=support,
        localization_residual_px=residual,
    )
