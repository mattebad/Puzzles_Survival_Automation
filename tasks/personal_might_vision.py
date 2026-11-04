"""Native Personal Might navigation bindings and persistent Praise postconditions."""
from __future__ import annotations

import math
import re
from typing import Callable

import cv2
import numpy as np

from scripts.bounded_tesseract import call_ocr, tesseract_data

from tasks.home_atlas_vision import BLUESTACKS_PROFILE_ID, native_frame_guard
from tasks.perception_bundle import ImmutableTargetObservation, NativeFrameIdentity
from tasks.semantic_ocr_crop import CropRoiRequest, NormalizationOp, SemanticOcrCropError, prepare_ocr_crop
from tasks.personal_might_praise import TARGET_IDENTITY

MORE_LABEL_ROI = (690, 1240, 795, 1278)
MORE_TARGET = "personal-might-home-more"
RANKINGS_TARGET = "personal-might-rankings"
CHECK_TARGET = "personal-might-check"
MENU_CELLS = {"friend": (500, 1140, 585, 1175), "rankings": (595, 1140, 700, 1175), "settings": (700, 1140, 795, 1175)}
HEADER_ROI = (180, 0, 650, 80)
RANKING_ROW_BANDS = tuple((180, y, 550, min(y + 300, 1240)) for y in (80, 330, 580, 830, 1080))


def _normalized(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _tokens(frame, roi, *, source_frame, source_png, psm=7, scale=2, whitelist: str | None = None):
    if not native_frame_guard(frame) or source_frame.runtime_profile_id != BLUESTACKS_PROFILE_ID:
        return ()
    try:
        upscale = NormalizationOp.UPSCALE_3X if scale == 3 else NormalizationOp.UPSCALE_2X
        _provenance, pixels = prepare_ocr_crop(frame, CropRoiRequest(source_frame, roi, source_png=source_png), normalization=(NormalizationOp.TO_GRAYSCALE, upscale))
        config = f"--psm {psm}"
        if whitelist is not None:
            config += f" -c tessedit_char_whitelist={whitelist}"
        data = call_ocr(tesseract_data, pixels, call_timeout=2, config=config)
    except (SemanticOcrCropError, RuntimeError, OSError, ValueError):
        return ()
    result = []
    for index, raw in enumerate(data.get("text", ())):
        text = _normalized(raw)
        if not text:
            continue
        x0 = roi[0] + float(data["left"][index]) / scale
        y0 = roi[1] + float(data["top"][index]) / scale
        x1 = x0 + float(data["width"][index]) / scale
        y1 = y0 + float(data["height"][index]) / scale
        if not (roi[0] <= x0 < x1 <= roi[2] and roi[1] <= y0 < y1 <= roi[3]):
            return ()
        result.append((text, (x0, y0, x1, y1)))
    return tuple(result)


def _label_box(frame, roi, expected, *, join_fragments=False, **source):
    tokens = _tokens(frame, roi, **source)
    separator = "" if join_fragments else " "
    if separator.join(text for text, _ in tokens) != expected:
        return None
    return (math.floor(min(box[0] for _, box in tokens)), math.floor(min(box[1] for _, box in tokens)), math.ceil(max(box[2] for _, box in tokens)), math.ceil(max(box[3] for _, box in tokens)))


def _target(source_frame, identity, box, *evidence):
    if box is None or not (25 <= box[2] - box[0] <= 150 and 12 <= box[3] - box[1] <= 45):
        return None
    return ImmutableTargetObservation(source_frame, identity, box, 0.97, tuple(evidence))


def more_menu_present(frame, *, source_frame, source_png):
    source = {"source_frame": source_frame, "source_png": source_png}
    return any(_label_box(frame, roi, label, **source) is not None for label, roi in MENU_CELLS.items())


def recognize_more_menu(frame, *, source_frame, source_png, home_is_clean):
    source = {"source_frame": source_frame, "source_png": source_png}
    # The tiny Strategy Guides caption touches animated icon artwork. The two
    # larger flanking captions provide stable independent menu context.
    return bool(home_is_clean(frame) and all(_label_box(frame, MENU_CELLS[label], label, **source) is not None for label in ("friend", "settings")))


def bind_home_more(frame: np.ndarray, *, source_frame: NativeFrameIdentity, source_png: bytes, home_is_clean: Callable[[np.ndarray], bool]):
    source = {"source_frame": source_frame, "source_png": source_png}
    if not home_is_clean(frame) or more_menu_present(frame, **source):
        return None
    return _target(source_frame, MORE_TARGET, _label_box(frame, MORE_LABEL_ROI, "more", **source), "current canonical Home", "current native More glyph")


def bind_more_rankings(frame, *, source_frame, source_png, home_is_clean):
    source = {"source_frame": source_frame, "source_png": source_png}
    if not recognize_more_menu(frame, **source, home_is_clean=home_is_clean):
        return None
    label = _label_box(frame, MENU_CELLS["rankings"], "rankings", join_fragments=True, **source)
    if label is None:
        return None
    return _target(source_frame, RANKINGS_TARGET, _rankings_trophy_body(frame, label), "native More menu Friend/Settings context", "current unique Rankings glyph", "current gold trophy body above caption")


def _rankings_trophy_body(frame, label):
    # A native caption-center tap triggered Home Help. Bind the visible trophy
    # itself, using only its current caption and pixels.
    center = (label[0] + label[2]) / 2
    half_width = (label[2] - label[0]) / 4
    x0, x1 = math.floor(center - half_width), math.ceil(center + half_width)
    y0, y1 = label[1] - 60, label[1] - 3
    if not (0 <= x0 < x1 <= frame.shape[1] and 0 <= y0 < y1 <= frame.shape[0]):
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array((8, 65, 80), dtype=np.uint8), np.array((45, 255, 255), dtype=np.uint8))
    _count, _labels, components, _centers = cv2.connectedComponentsWithStats(gold)
    bodies = [(int(x), int(y), int(w), int(h)) for x, y, w, h, area in components[1:]
              if area >= 500 and 30 <= w <= 75 and 25 <= h <= 55 and abs(x0 + x + w / 2 - center) <= 6]
    if len(bodies) != 1:
        return None
    x, y, width, height = bodies[0]
    # Keep the dispatch center in the upper cup, clear of the failed caption
    # point and the notification badge beside the trophy.
    return (x0 + x, y0 + y, x0 + x + width, y0 + y + height // 2)


def is_rankings(frame, *, source_frame, source_png):
    return _label_box(frame, HEADER_ROI, "leaderboard", source_frame=source_frame, source_png=source_png) is not None


def is_personal_might(frame, *, source_frame, source_png):
    return _label_box(frame, HEADER_ROI, "personal might rank", source_frame=source_frame, source_png=source_png) is not None


def _popup_clear(frame):
    from scripts.bluestacks_popup_recognition import recognize_reset_popup
    popup = recognize_reset_popup(frame)
    return not (popup.get("recognized") or popup.get("blocking_unknown_modal"))


def _rank_1_context(frame, *, source_frame, source_png):
    source = {"source_frame": source_frame, "source_png": source_png}
    if not is_personal_might(frame, **source) or not _popup_clear(frame):
        return None
    if _label_box(frame, (70, 80, 740, 130), "rank commander might", **source) is None:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    medal_mask = cv2.inRange(hsv[135:1145, 65:140], np.array((12, 70, 80), dtype=np.uint8), np.array((45, 255, 255), dtype=np.uint8))
    _count, _labels, components, _centers = cv2.connectedComponentsWithStats(medal_mask)
    medals = [(int(x) + 65, int(y) + 135, int(w), int(h)) for x, y, w, h, area in components[1:] if 500 <= area <= 1500 and 50 <= w <= 75 and 35 <= h <= 65]
    if len(medals) != 1:
        return None
    x, y, width, height = medals[0]
    digit = (math.floor(x + width * .29), math.floor(y + height * .1), math.ceil(x + width * .77), math.ceil(y + height * .9))
    # Read the medal's numeric field, not an unconstrained alphabetic glyph.
    # Keep all digits available: another rank must not be coerced into Rank 1.
    if _label_box(frame, digit, "1", **source, psm=10, scale=3, whitelist="0123456789") is None:
        return None
    return y + height / 2


def _thumb(frame, rank_y, *, disabled):
    hsv = cv2.cvtColor(frame[135:1145, 695:750], cv2.COLOR_BGR2HSV)
    lower, upper = ((0, 0, 35), (179, 20, 170)) if disabled else ((12, 100, 120), (42, 255, 255))
    thumb_mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    _count, _labels, components, _centers = cv2.connectedComponentsWithStats(thumb_mask)
    circles = [(int(a) + 695, int(b) + 135, int(w), int(h)) for a, b, w, h, area in components[1:] if 700 <= area <= 1600 and 32 <= w <= 50 and 32 <= h <= 50 and .85 <= w / h <= 1.15]
    if len(circles) != 1:
        return None
    tx, ty, tw, th = circles[0]
    if abs(ty + th / 2 - rank_y) > 15:
        return None
    interior = cv2.cvtColor(frame[ty + 5:ty + th - 5, tx + 5:tx + tw - 5], cv2.COLOR_BGR2GRAY)
    _count, _labels, dark, _centers = cv2.connectedComponentsWithStats(cv2.inRange(interior, 0, 90 if disabled else 135))
    fingers = [(int(a), int(b), int(w), int(h)) for a, b, w, h, area in dark[1:] if 200 <= area <= 600 and 12 <= w <= 25 and 20 <= h <= 30]
    cuffs = [(int(a), int(b), int(w), int(h)) for a, b, w, h, area in dark[1:] if (20 if disabled else 30) <= area <= 150 and (2 if disabled else 3) <= w <= 10 and 8 <= h <= 20]
    if len(fingers) != 1 or len(cuffs) != 1 or cuffs[0][0] + cuffs[0][2] >= fingers[0][0]:
        return None
    return (tx, ty, tx + tw, ty + th)


def bind_personal_might_praise(frame, *, source_frame, source_png):
    rank_y = _rank_1_context(frame, source_frame=source_frame, source_png=source_png)
    if rank_y is None:
        return None
    return _target(source_frame, TARGET_IDENTITY, _thumb(frame, rank_y, disabled=False), "exact Personal Might Rank and table headers", "current unique gold Rank 1 medal and exact 1 glyph", "unique gold thumb with visible finger and cuff in Rank 1 row")


def personal_might_praised(frame, *, source_frame, source_png):
    """Persistent disabled state; effect confirmation also requires own gold P/I."""
    rank_y = _rank_1_context(frame, source_frame=source_frame, source_png=source_png)
    return bool(rank_y is not None and _thumb(frame, rank_y, disabled=True) is not None and _thumb(frame, rank_y, disabled=False) is None)


def praise_reward_toasts(frame, *, source_frame, source_png):
    rewards = []
    for roi in ((180, 270, 650, 310), (180, 360, 650, 410)):
        words = " ".join(text for text, _box in _tokens(frame, roi, source_frame=source_frame, source_png=source_png))
        match = re.fullmatch(r"obtained (10|30) min omni speedup x ?1", words)
        if match:
            rewards.append(int(match.group(1)))
    return tuple(rewards)


def bind_back(frame, *, source_frame, source_png, personal_page):
    source = {"source_frame": source_frame, "source_png": source_png}
    if not (is_personal_might(frame, **source) if personal_page else is_rankings(frame, **source)) or not _popup_clear(frame):
        return None
    from scripts.daily_resource_item_bluestacks import _bag_back_arrow_visual
    box = _bag_back_arrow_visual(frame, maximum_left=90, search_right=180)
    if box is None:
        return None
    return ImmutableTargetObservation(source_frame, "personal-might-back" if personal_page else "leaderboard-back", box, .97, ("current exact page header", "current measured visible Back arrow"))


def _unique_boxes(boxes):
    result = []
    for box in boxes:
        if not any(all(abs(a - b) <= 5 for a, b in zip(box, previous)) for previous in result):
            result.append(box)
    return result


def _personal_might_rank_labels(tokens):
    labels = []
    for index in range(len(tokens)):
        for length in (1, 2, 3):
            words = tokens[index:index + length]
            if " ".join(text for text, _box in words) != "personal might rank":
                continue
            boxes = [box for _text, box in words]
            if any(not (0 <= right[0] - left[2] <= 40 and abs((right[1] + right[3] - left[1] - left[3]) / 2) <= 12) for left, right in zip(boxes, boxes[1:])):
                continue
            labels.append((min(box[0] for box in boxes), min(box[1] for box in boxes), max(box[2] for box in boxes), max(box[3] for box in boxes)))
    return _unique_boxes(labels)


def _personal_row_check(tokens):
    labels = _personal_might_rank_labels(tokens)
    checks = _unique_boxes([box for text, box in tokens if text == "check"])
    if len(labels) != 1:
        return None
    label = labels[0]
    same_row = [box for box in checks if box[0] > label[2] + 10 and abs((box[1] + box[3] - label[1] - label[3]) / 2) <= 30]
    if len(same_row) != 1:
        return None
    return tuple(math.floor(value) if index < 2 else math.ceil(value) for index, value in enumerate(same_row[0]))


def bind_personal_might_check(frame, *, source_frame, source_png):
    source = {"source_frame": source_frame, "source_png": source_png}
    if not is_rankings(frame, **source):
        return None
    if not _popup_clear(frame):
        return None
    tokens = tuple(token for roi in RANKING_ROW_BANDS for token in _tokens(frame, roi, **source, psm=11))
    labels = _personal_might_rank_labels(tokens)
    if len(labels) != 1:
        return None
    label = labels[0]
    row_center = (label[1] + label[3]) / 2
    # Native leaderboard buttons sit below the row's title baseline. Read
    # their interior in the title's own row, excluding red chrome and badges.
    check_roi = (575, math.floor(row_center + 7), 720, math.ceil(row_center + 49))
    checks = _tokens(frame, check_roi, **source)
    if " ".join(text for text, _box in checks) != "check":
        return None
    return _target(source_frame, CHECK_TARGET, _personal_row_check((*tokens, *checks)), "current Leaderboard header", "unique Personal Might Rank row and same-row exact Check")
