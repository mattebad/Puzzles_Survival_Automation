"""Current BlueStacks popup recognition shared by active flows.

This module contains only the retained, benign VIP Points reset-popup
recognition contract.  It intentionally does not own transport or runtime
authority.
"""

from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np
import pytesseract


RESET_POPUP_CLOSE_REGION = (260, 750, 540, 870)
VIP_POPUP_TITLE_REGION = (260, 390, 540, 440)
VIP_POPUP_BODY_REGION = (120, 480, 680, 720)
VIP_POPUP_PANEL_REGION = (40, 370, 600, 890)
OLD_INVALID_CLOSE_POINT = (320, 650)
VIP_CLOSE_CENTER_Y_RANGE = (780, 830)
VIP_CLOSE_INTERIOR_MARGIN = 12
MAX_VIP_POPUP_INPUTS = 1


def crop(frame: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    return frame[y0:y1, x0:x1]


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def translate_crop_bounds(
    local_bounds: tuple[int, int, int, int],
    crop_roi: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Translate crop-local OCR geometry into full-frame coordinates."""
    lx0, ly0, lx1, ly1 = local_bounds
    cx0, cy0, _cx1, _cy1 = crop_roi
    return cx0 + lx0, cy0 + ly0, cx0 + lx1, cy0 + ly1


def point_inside(
    bounds: tuple[int, int, int, int],
    point: tuple[int, int],
    *,
    margin: int = 0,
) -> bool:
    x0, y0, x1, y1 = bounds
    x, y = point
    return x0 + margin <= x <= x1 - margin and y0 + margin <= y <= y1 - margin


def recognize_reset_popup(frame: np.ndarray) -> dict[str, Any]:
    """Recognize only the retained VIP Points modal and literal Close button."""
    if frame.shape != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}

    title_crop = cv2.resize(crop(frame, VIP_POPUP_TITLE_REGION), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    title_gray = cv2.cvtColor(title_crop, cv2.COLOR_BGR2GRAY)
    title_binary = cv2.threshold(title_gray, 120, 255, cv2.THRESH_BINARY)[1]
    title_text = normalized(pytesseract.image_to_string(title_binary, config="--psm 7"))
    title_identity = re.sub(r"[^a-z]", "", title_text) in {"getpts", "getpoints"}

    body_crop = cv2.resize(crop(frame, VIP_POPUP_BODY_REGION), None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    body_text = normalized(pytesseract.image_to_string(body_crop, config="--psm 6"))
    # Prefer exact phrase match; letter-compact fallback tolerates OCR separators
    # (e.g. "vip | nip" for "vip pt") without loosening the semantic requirements.
    body_letters = re.sub(r"[^a-z]", "", body_text)
    body_identity = bool(
        (
            "log in every day to get vip pt" in body_text
            or "logineverydaytogetvip" in body_letters
        )
        and (
            "obtained vip pt" in body_text
            or "obtaind vip pt" in body_text
            or "obtainedvippt" in body_letters
            or "obtaindvippt" in body_letters
        )
    )

    close_crop = crop(frame, RESET_POPUP_CLOSE_REGION)
    close_enlarged = cv2.resize(close_crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    close_text = normalized(pytesseract.image_to_string(close_enlarged, config="--psm 7"))
    literal_close = close_text == "close"

    hsv = cv2.cvtColor(close_crop, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, np.array([0, 35, 70], np.uint8), np.array([35, 255, 220], np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(orange)
    candidates = [tuple(int(value) for value in stats[index]) for index in range(1, count) if stats[index, 4] >= 5000]
    component = max(candidates, key=lambda item: item[4], default=None)
    button_bounds = None
    if component:
        left, top, width, height, _area = component
        button_bounds = translate_crop_bounds(
            (left, top, left + width, top + height),
            RESET_POPUP_CLOSE_REGION,
        )

    target_center = (
        ((button_bounds[0] + button_bounds[2]) // 2, (button_bounds[1] + button_bounds[3]) // 2)
        if button_bounds else None
    )
    geometry_valid = bool(
        button_bounds
        and 250 <= button_bounds[0] <= 300
        and 750 <= button_bounds[1] <= 790
        and 500 <= button_bounds[2] <= 550
        and 830 <= button_bounds[3] <= 870
        and button_bounds[1] > 740
        and button_bounds[3] < 880
        and target_center
        and VIP_CLOSE_CENTER_Y_RANGE[0] <= target_center[1] <= VIP_CLOSE_CENTER_Y_RANGE[1]
        and point_inside(button_bounds, target_center, margin=VIP_CLOSE_INTERIOR_MARGIN)
        and not point_inside(button_bounds, OLD_INVALID_CLOSE_POINT)
    )
    panel = crop(frame, VIP_POPUP_PANEL_REGION)
    panel_present = float(panel.mean()) > 20.0
    recognized = bool(title_identity and body_identity and literal_close and geometry_valid and panel_present)
    return {
        "recognized": recognized,
        "popup_identity": "VIP_POINTS_GET_PTS" if recognized else None,
        "title_text": title_text,
        "title_identity": title_identity,
        "body_text": body_text,
        "body_identity": body_identity,
        "matched_close_text": close_text,
        "literal_close": literal_close,
        "target": button_bounds if recognized else None,
        "target_center": target_center if recognized else None,
        "target_identity": "reset-popup-close" if recognized else None,
        "geometry_valid": geometry_valid,
        "panel_present": panel_present,
        "close_region": RESET_POPUP_CLOSE_REGION,
    }


def vip_popup_handled(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    recognized_successor: bool,
) -> bool:
    return bool(before.get("recognized") and not after.get("recognized") and recognized_successor)
