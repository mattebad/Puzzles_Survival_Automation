"""Current BlueStacks popup recognition shared by active flows.

This module contains the retained, benign VIP Points reset-popup recognition
contract and the exact ``Disconnected. Reconnect now?[10054]`` network
disconnect recognition contract.  It intentionally does not own transport,
persistence, or runtime authority: a recognition result never grants input.
"""

from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np

from scripts.bounded_tesseract import call_ocr, tesseract_string

from tasks.perception_bundle import (
    ModalSurfaceClass,
    RecoveryBehavior,
    SourceContextModalClassification,
    classify_source_context_modal,
)


RESET_POPUP_CLOSE_REGION = (260, 750, 540, 870)
VIP_POPUP_TITLE_REGION = (260, 390, 540, 440)
VIP_POPUP_BODY_REGION = (120, 480, 680, 720)
VIP_POPUP_PANEL_REGION = (40, 370, 600, 890)
OLD_INVALID_CLOSE_POINT = (320, 650)
VIP_CLOSE_CENTER_Y_RANGE = (780, 830)
VIP_CLOSE_INTERIOR_MARGIN = 12
MAX_VIP_POPUP_INPUTS = 1

NETWORK_DISCONNECT_IDENTITY = "NETWORK_DISCONNECTED_10054"
NETWORK_DISCONNECT_TARGET = "network-disconnect-confirm"
NETWORK_DISCONNECT_CODE = "10054"
NETWORK_DISCONNECT_PROFILE_SHAPE = (1280, 800, 3)
# Calibrated from the immutable 800x1280 native capture (sha256 2c20c29f...690b):
# panel edges and the gold Confirm component, both as half-open (x0, y0, x1, y1).
DISCONNECT_PANEL_EXPECTED = (76, 413, 724, 777)
DISCONNECT_PANEL_TOLERANCE = 12
DISCONNECT_PANEL_EDGE_ROWS = (480, 770)
DISCONNECT_PANEL_EDGE_COLUMNS = (100, 700)
DISCONNECT_PANEL_LEFT_SEARCH = (60, 100)
DISCONNECT_PANEL_RIGHT_SEARCH = (700, 740)
DISCONNECT_PANEL_TOP_SEARCH = (395, 440)
DISCONNECT_PANEL_BOTTOM_SEARCH = (755, 800)
DISCONNECT_PANEL_MIN_EDGE_CONTRAST = 8.0
DISCONNECT_PANEL_MARGIN_REGIONS = ((86, 480, 100, 770), (700, 480, 714, 770))
DISCONNECT_OUTSIDE_REGIONS = ((10, 480, 60, 770), (740, 480, 790, 770))
DISCONNECT_MIN_OUTSIDE_CONTRAST = 10.0
DISCONNECT_BODY_BLANK_REGION = (100, 560, 700, 650)
DISCONNECT_BODY_MAX_STD = 6.0
DISCONNECT_BODY_MAX_MARGIN_DELTA = 10.0
DISCONNECT_TEXT_REGION = (90, 490, 710, 550)
DISCONNECT_BUTTON_SEARCH_REGION = (180, 640, 620, 775)
DISCONNECT_BUTTON_EXPECTED = (278, 672, 522, 750)
DISCONNECT_BUTTON_TOLERANCE = 12
DISCONNECT_BUTTON_MIN_COMPONENT_AREA = 2000
DISCONNECT_BUTTON_MIN_FILL = 0.8
DISCONNECT_BUTTON_GOLD_HSV = ((8, 90, 120), (30, 255, 255))
DISCONNECT_BUTTON_LABEL_INSET = 8
DISCONNECT_BUTTON_LABEL_MIN_GRAY = 215
DISCONNECT_BUTTON_LABEL_CENTER_TOLERANCE = (24, 12)
DISCONNECT_BUTTON_PANEL_CENTER_TOLERANCE = 12
DISCONNECT_CODE_PATTERN = re.compile(r"[\[({]\s*(\d+)\s*[\])}]\s*$")
DISCONNECT_MESSAGE_PATTERN = re.compile(r"disconnected\s*[.,]?\s*reconnect\s+now\s*\??")


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


def _within(value: int, expected: int, tolerance: int) -> bool:
    return expected - tolerance <= value <= expected + tolerance


def _bounds_within(
    bounds: tuple[int, int, int, int],
    expected: tuple[int, int, int, int],
    tolerance: int,
) -> bool:
    return all(_within(value, target, tolerance) for value, target in zip(bounds, expected))


def _region_mean(gray: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    return float(crop(gray, roi).mean())


def _measure_disconnect_panel(gray: np.ndarray) -> dict[str, Any]:
    """Measure the current modal panel edges inside bounded profile searches."""
    row0, row1 = DISCONNECT_PANEL_EDGE_ROWS
    col0, col1 = DISCONNECT_PANEL_EDGE_COLUMNS
    column_steps = np.diff(gray[row0:row1, :].mean(axis=0))
    row_steps = np.diff(gray[:, col0:col1].mean(axis=1))

    def rising(steps: np.ndarray, window: tuple[int, int]) -> tuple[int, float]:
        index = int(np.argmax(steps[window[0]:window[1]]))
        return window[0] + index + 1, float(steps[window[0] + index])

    def falling(steps: np.ndarray, window: tuple[int, int]) -> tuple[int, float]:
        index = int(np.argmin(steps[window[0]:window[1]]))
        return window[0] + index + 1, float(-steps[window[0] + index])

    left, left_contrast = rising(column_steps, DISCONNECT_PANEL_LEFT_SEARCH)
    right, right_contrast = falling(column_steps, DISCONNECT_PANEL_RIGHT_SEARCH)
    top, top_contrast = rising(row_steps, DISCONNECT_PANEL_TOP_SEARCH)
    bottom, bottom_contrast = falling(row_steps, DISCONNECT_PANEL_BOTTOM_SEARCH)
    bounds = (left, top, right, bottom)
    margin_mean = min(_region_mean(gray, roi) for roi in DISCONNECT_PANEL_MARGIN_REGIONS)
    outside_mean = max(_region_mean(gray, roi) for roi in DISCONNECT_OUTSIDE_REGIONS)
    edge_contrast = min(left_contrast, right_contrast, top_contrast, bottom_contrast)
    geometry_valid = bool(
        _bounds_within(bounds, DISCONNECT_PANEL_EXPECTED, DISCONNECT_PANEL_TOLERANCE)
        and edge_contrast >= DISCONNECT_PANEL_MIN_EDGE_CONTRAST
        and margin_mean - outside_mean >= DISCONNECT_MIN_OUTSIDE_CONTRAST
    )
    body = crop(gray, DISCONNECT_BODY_BLANK_REGION)
    body_blank = bool(
        float(body.std()) <= DISCONNECT_BODY_MAX_STD
        and abs(float(body.mean()) - margin_mean) <= DISCONNECT_BODY_MAX_MARGIN_DELTA
    )
    return {
        "bounds": bounds,
        "edge_contrast": edge_contrast,
        "margin_mean": margin_mean,
        "outside_mean": outside_mean,
        "geometry_valid": geometry_valid,
        "body_blank": body_blank,
    }


def _measure_disconnect_button(
    frame: np.ndarray,
    panel_bounds: tuple[int, int, int, int],
    panel_valid: bool,
) -> dict[str, Any]:
    """Derive the single gold Confirm button from current pixels."""
    search = crop(frame, DISCONNECT_BUTTON_SEARCH_REGION)
    lower, upper = DISCONNECT_BUTTON_GOLD_HSV
    gold = cv2.inRange(
        cv2.cvtColor(search, cv2.COLOR_BGR2HSV),
        np.array(lower, np.uint8),
        np.array(upper, np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(gold)
    candidates = [
        tuple(int(value) for value in stats[index])
        for index in range(1, count)
        if stats[index, 4] >= DISCONNECT_BUTTON_MIN_COMPONENT_AREA
    ]
    bounds = None
    geometry_valid = False
    if len(candidates) == 1:
        left, top, width, height, area = candidates[0]
        bounds = translate_crop_bounds(
            (left, top, left + width, top + height),
            DISCONNECT_BUTTON_SEARCH_REGION,
        )
        center = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
        panel_center_x = (panel_bounds[0] + panel_bounds[2]) // 2
        geometry_valid = bool(
            _bounds_within(bounds, DISCONNECT_BUTTON_EXPECTED, DISCONNECT_BUTTON_TOLERANCE)
            and area / float(width * height) >= DISCONNECT_BUTTON_MIN_FILL
            and point_inside(bounds, center, margin=DISCONNECT_BUTTON_LABEL_INSET)
            and (
                not panel_valid
                or (
                    abs(center[0] - panel_center_x) <= DISCONNECT_BUTTON_PANEL_CENTER_TOLERANCE
                    and point_inside(panel_bounds, (bounds[0], bounds[1]))
                    and point_inside(panel_bounds, (bounds[2], bounds[3]))
                )
            )
        )
    return {"candidates": len(candidates), "bounds": bounds, "geometry_valid": geometry_valid}


def _disconnect_label_roi(button_bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = button_bounds
    inset = DISCONNECT_BUTTON_LABEL_INSET
    return x0 + inset, y0 + inset, x1 - inset, y1 - inset


def _disconnect_label_isolated(frame: np.ndarray, button_bounds: tuple[int, int, int, int]) -> bool:
    """Require one centered bright label inside the button interior."""
    label_roi = _disconnect_label_roi(button_bounds)
    gray = cv2.cvtColor(crop(frame, label_roi), cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(gray >= DISCONNECT_BUTTON_LABEL_MIN_GRAY)
    if xs.size == 0:
        return False
    height, width = gray.shape
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    if x0 == 0 or y0 == 0 or x1 == width or y1 == height:
        return False
    tolerance_x, tolerance_y = DISCONNECT_BUTTON_LABEL_CENTER_TOLERANCE
    return bool(
        abs((x0 + x1) / 2.0 - width / 2.0) <= tolerance_x
        and abs((y0 + y1) / 2.0 - height / 2.0) <= tolerance_y
    )


def _read_disconnect_message(frame: np.ndarray) -> str:
    """Bounded single-line OCR of the current disconnect message region."""
    gray = cv2.cvtColor(crop(frame, DISCONNECT_TEXT_REGION), cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    binary = cv2.threshold(enlarged, 85, 255, cv2.THRESH_BINARY_INV)[1]
    return normalized(call_ocr(tesseract_string, binary, config="--psm 7"))


def _read_disconnect_confirm(frame: np.ndarray, button_bounds: tuple[int, int, int, int]) -> str:
    """Bounded single-line OCR of the measured button interior only."""
    gray = cv2.cvtColor(crop(frame, _disconnect_label_roi(button_bounds)), cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    binary = cv2.threshold(enlarged, 200, 255, cv2.THRESH_BINARY_INV)[1]
    return normalized(call_ocr(tesseract_string, binary, config="--psm 7"))


def parse_disconnect_message(text: str) -> tuple[bool, str | None]:
    """Return (exact message identity, trailing bracketed code digits)."""
    value = normalized(text or "")
    code_match = DISCONNECT_CODE_PATTERN.search(value)
    code_text = code_match.group(1) if code_match else None
    message = value[: code_match.start()].strip() if code_match else value
    return bool(DISCONNECT_MESSAGE_PATTERN.fullmatch(message)), code_text


def recognize_network_disconnect(frame: np.ndarray) -> dict[str, Any]:
    """Recognize only the exact native 10054 disconnect modal and its one Confirm.

    Recognition is evidence only; it never grants input authority.  A current
    modal with this blank-body layout, disconnect text, or a literal Confirm on
    the measured button stays ``blocking_unknown_modal`` if its identity fails.
    """
    result: dict[str, Any] = {
        "recognized": False,
        "popup_identity": None,
        "target_identity": None,
        "target": None,
        "target_center": None,
        "blocking_unknown_modal": False,
        "reason": "profile_dimensions_mismatch",
        "message_text": None,
        "message_identity": False,
        "code_text": None,
        "code_identity": False,
        "matched_confirm_text": None,
        "literal_confirm": False,
        "label_isolated": False,
        "panel_bounds": None,
        "panel_geometry_valid": False,
        "body_blank": False,
        "button_candidates": 0,
        "measured_button_bounds": None,
        "button_geometry_valid": False,
        "text_region": DISCONNECT_TEXT_REGION,
        "button_search_region": DISCONNECT_BUTTON_SEARCH_REGION,
    }
    if (
        not isinstance(frame, np.ndarray)
        or frame.shape != NETWORK_DISCONNECT_PROFILE_SHAPE
        or frame.dtype != np.uint8
    ):
        return result

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    panel = _measure_disconnect_panel(gray)
    button = _measure_disconnect_button(frame, panel["bounds"], panel["geometry_valid"])
    result.update(
        panel_bounds=panel["bounds"],
        panel_geometry_valid=panel["geometry_valid"],
        body_blank=panel["body_blank"],
        button_candidates=button["candidates"],
        measured_button_bounds=button["bounds"],
        button_geometry_valid=button["geometry_valid"],
    )
    if not panel["geometry_valid"] and not button["candidates"]:
        result["reason"] = "disconnect_dialog_absent"
        return result

    message_text = _read_disconnect_message(frame)
    message_identity, code_text = parse_disconnect_message(message_text)
    code_identity = code_text == NETWORK_DISCONNECT_CODE
    confirm_text = None
    literal_confirm = False
    label_isolated = False
    if button["geometry_valid"]:
        confirm_text = _read_disconnect_confirm(frame, button["bounds"])
        literal_confirm = confirm_text == "confirm"
        label_isolated = _disconnect_label_isolated(frame, button["bounds"])
    result.update(
        message_text=message_text,
        message_identity=message_identity,
        code_text=code_text,
        code_identity=code_identity,
        matched_confirm_text=confirm_text,
        literal_confirm=literal_confirm,
        label_isolated=label_isolated,
    )

    checks = (
        (panel["geometry_valid"], "disconnect_panel_geometry_mismatch"),
        (panel["body_blank"], "disconnect_layout_mismatch"),
        (button["candidates"] > 0, "confirm_button_missing"),
        (button["candidates"] < 2, "confirm_button_ambiguous"),
        (button["geometry_valid"], "confirm_button_geometry_mismatch"),
        (literal_confirm, "confirm_text_mismatch"),
        (label_isolated, "confirm_label_not_isolated"),
        (message_identity, "disconnect_text_mismatch"),
        (code_text is not None, "disconnect_code_missing"),
        (code_identity, "disconnect_code_mismatch"),
    )
    failure = next((reason for passed, reason in checks if not passed), None)
    if failure is not None:
        result["reason"] = failure
        result["blocking_unknown_modal"] = bool(
            (panel["geometry_valid"] and (panel["body_blank"] or message_identity))
            or (literal_confirm and button["geometry_valid"])
        )
        return result

    bounds = button["bounds"]
    result.update(
        recognized=True,
        popup_identity=NETWORK_DISCONNECT_IDENTITY,
        target_identity=NETWORK_DISCONNECT_TARGET,
        target=bounds,
        target_center=((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2),
        reason="network_disconnect_10054_recognized",
    )
    return result


def recognize_reset_popup(frame: np.ndarray) -> dict[str, Any]:
    """Recognize only the retained VIP Points modal and literal Close button."""
    if frame.shape != (1280, 800, 3):
        return {"recognized": False, "reason": "profile_dimensions_mismatch"}

    title_crop = cv2.resize(crop(frame, VIP_POPUP_TITLE_REGION), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    title_gray = cv2.cvtColor(title_crop, cv2.COLOR_BGR2GRAY)
    title_binary = cv2.threshold(title_gray, 120, 255, cv2.THRESH_BINARY)[1]
    title_text = normalized(call_ocr(tesseract_string, title_binary, config="--psm 7"))
    title_identity = re.sub(r"[^a-z]", "", title_text) in {"getpts", "getpoints"}

    body_crop = cv2.resize(crop(frame, VIP_POPUP_BODY_REGION), None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    body_text = normalized(call_ocr(tesseract_string, body_crop, config="--psm 6"))
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
    close_text = normalized(call_ocr(tesseract_string, close_enlarged, config="--psm 7"))
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
    # A current-frame modal with the same independently measured Close geometry
    # remains blocking even when its semantic body is not the allowlisted VIP popup.
    blocking_unknown_modal = bool(
        not recognized and literal_close and geometry_valid and panel_present
    )
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
        "blocking_unknown_modal": blocking_unknown_modal,
        "close_region": RESET_POPUP_CLOSE_REGION,
    }


def vip_popup_handled(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    recognized_successor: bool,
) -> bool:
    return bool(before.get("recognized") and not after.get("recognized") and recognized_successor)


def classify_popup_recovery(
    recognition: dict[str, Any],
    *,
    source_context: str,
    successor_context: str | None = None,
) -> SourceContextModalClassification:
    """Project popup recognition into a typed, source-bound recovery result.

    The recognizer remains recognition-only.  The result records whether a
    contextual dismissal is meaningful and carries the source context for
    successor checks.  It never exposes generic Confirm authority.
    """

    if not isinstance(recognition, dict):
        return classify_source_context_modal(
            source_context=source_context,
            successor_context=successor_context,
            surface_class=ModalSurfaceClass.UNKNOWN,
            recovery_behavior=RecoveryBehavior.UNKNOWN,
            recognized=False,
            supporting_evidence=("popup_recognition_not_mapping",),
        )
    recognized = bool(recognition.get("recognized"))
    identity = recognition.get("popup_identity")
    target = recognition.get("target_identity")
    if not recognized:
        return classify_source_context_modal(
            source_context=source_context,
            successor_context=successor_context,
            surface_identity=str(identity) if identity else None,
            surface_class=ModalSurfaceClass.UNKNOWN,
            recovery_behavior=RecoveryBehavior.UNKNOWN,
            recognized=False,
            supporting_evidence=(str(recognition.get("reason") or "unrecognized_popup"),),
        )
    successor_matches = successor_context is None or successor_context == source_context
    recovery = RecoveryBehavior.DISMISS_CONTEXTUAL if successor_matches and target else RecoveryBehavior.RETURN_TO_SOURCE
    return classify_source_context_modal(
        source_context=source_context,
        successor_context=successor_context,
        surface_identity=str(identity) if identity else None,
        surface_class=ModalSurfaceClass.CONTEXTUAL_MODAL,
        recovery_behavior=recovery,
        dismiss_target_identity=str(target) if target else None,
        recognized=bool(identity and target),
        confidence=1.0 if identity and target else 0.0,
        supporting_evidence=tuple(
            str(item)
            for item in (
                recognition.get("title_text"),
                recognition.get("body_text"),
                recognition.get("matched_close_text"),
            )
            if item
        ),
    )


# Neutral aliases used by replay consumers.
classify_source_context_popup = classify_popup_recovery
