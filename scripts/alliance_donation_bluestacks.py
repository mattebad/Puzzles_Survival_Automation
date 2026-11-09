"""Fixed native route for ten individually confirmed ordinary Alliance Tech donations."""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    TransportResult,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.bounded_tesseract import call_ocr, tesseract_data
from scripts.startup_normalization import is_clean_home_frame
from safe_action_core.models import ROI
from tasks.donation_disabled import (
    ALLIANCE_TECH_SCREEN,
    DONATION_ACTION,
    DONATION_CONSEQUENCE,
    DONATION_POSTCONDITION,
    DONATION_RESOURCE,
    DONATION_TARGET,
    MAX_DONATIONS_PER_RESET,
    DonationActionReconciliationError,
    DonationDisposition,
    DonationObservation,
    confirmed_donation_count,
    donation_action_key,
    donation_authorizeable,
    donation_disposition,
    donation_postcondition_verified,
)
from tasks.home_nav_recognition import recognize_home_nav
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID, BLUESTACKS_NATIVE_TARGET_PROVENANCE

from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID as FLOW_ID,
    ALLIANCE_DONATION_MAX_INPUTS as MAX_INPUTS,
    ALLIANCE_DONATION_PRODUCT_ID as PRODUCT_ID,
    ALLIANCE_DONATION_PRODUCT_REVISION as PRODUCT_REVISION,
    ALLIANCE_DONATION_PROFILE_ID as PROFILE_ID,
)

_EXACT_AMOUNT_RE = re.compile(r"^[0-9][0-9,]*$", re.ASCII)
_TIMER_RE = re.compile(r"(?<![0-9])([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])(?![0-9])", re.ASCII)
_LEVEL_RE = re.compile(r"^level ([0-9]{1,3}) ([0-9]{1,3})$", re.ASCII)
HOT_TREE_TARGET = "alliance-tech:hot:current-selected-node"
# Pixels a stationary HOT widget may jitter between captures; larger moves mean the tree is still scrolling.
_HOT_STABLE_PIXELS = 6

# Keep Back/border art out of title OCR, without clipping the glyphs at y=17.
SCREEN_TITLE_ROI = (260, 6, 540, 60)


@dataclass(frozen=True)
class TextWord:
    text: str
    roi: ROI
    line_key: tuple[int, int, int]
    confidence: float


@dataclass(frozen=True)
class TextLine:
    text: str
    roi: ROI
    words: tuple[TextWord, ...]


@dataclass(frozen=True)
class DonationSurface:
    state: str
    frame_sha256: str
    evidence_ref: str
    target_identity: str | None = None
    target_roi: ROI | None = None
    tech_identity: str | None = None
    tech_slug: str | None = None
    donation: DonationObservation | None = None
    premium_roi: ROI | None = None
    hot_roi: ROI | None = None
    reason: str = "recognized"


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _slug(text: str) -> str | None:
    normalized = _normalize(text)
    slug = "-".join(token for token in normalized.split() if token)
    return slug if slug and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug, re.ASCII) else None


def _words(
    frame: np.ndarray,
    roi: ROI,
    *,
    ocr_reader: Callable[..., Mapping[str, Any]] | None = None,
) -> tuple[TextWord, ...]:
    x0, y0, x1, y1 = roi
    if (not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (1280, 800)
            or not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280)):
        return ()
    crop = np.ascontiguousarray(frame[y0:y1, x0:x1])
    reader = ocr_reader or tesseract_data
    # call_ocr owns the bounded per-call timeout; passing ``timeout`` here collides with it (TypeError).
    data = call_ocr(reader, crop, config="--psm 6")
    if not isinstance(data, Mapping):
        return ()
    fields = ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")
    if any(not isinstance(data.get(field), (list, tuple)) for field in fields):
        return ()
    length = min(len(data[field]) for field in fields)
    result: list[TextWord] = []
    for index in range(length):
        text = str(data["text"][index]).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            line_key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        except (TypeError, ValueError, OverflowError):
            continue
        if confidence < 35 or width <= 0 or height <= 0:
            continue
        wx0, wy0 = x0 + left, y0 + top
        wx1, wy1 = min(800, wx0 + width), min(1280, wy0 + height)
        if 0 <= wx0 < wx1 and 0 <= wy0 < wy1:
            result.append(TextWord(text, (wx0, wy0, wx1, wy1), line_key, confidence))
    return tuple(result)


def _lines(words: tuple[TextWord, ...]) -> tuple[TextLine, ...]:
    groups: dict[tuple[int, int, int], list[TextWord]] = {}
    for word in words:
        groups.setdefault(word.line_key, []).append(word)
    result: list[TextLine] = []
    for group in groups.values():
        ordered = tuple(sorted(group, key=lambda word: word.roi[0]))
        result.append((TextLine(" ".join(word.text for word in ordered),
                                (min(word.roi[0] for word in ordered), min(word.roi[1] for word in ordered),
                                 max(word.roi[2] for word in ordered), max(word.roi[3] for word in ordered)), ordered)))
    return tuple(sorted(result, key=lambda line: (line.roi[1], line.roi[0])))


def _union(boxes: tuple[ROI, ...] | list[ROI], *, pad_x: int = 0, pad_y: int = 0) -> ROI | None:
    if not boxes:
        return None
    x0 = max(0, min(box[0] for box in boxes) - pad_x)
    y0 = max(0, min(box[1] for box in boxes) - pad_y)
    x1 = min(800, max(box[2] for box in boxes) + pad_x)
    y1 = min(1280, max(box[3] for box in boxes) + pad_y)
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _red_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return (((hsv[:, :, 0] <= 9) | (hsv[:, :, 0] >= 170))
            & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 70)).astype(np.uint8)


def _tree_hot_marker(frame: np.ndarray, *, ocr_reader=None) -> TextWord | None:
    """Read HOT inside measured red ribbons, including the viewport's bottom edge."""
    mask = _red_mask(frame)
    mask[:235] = 0  # Fixed chrome is not scrollable tree content.
    markers = []
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, width, height = cv2.boundingRect(contour)
        if not (80 <= width <= 160 and 25 <= height <= 65 and 40 <= x < x + width <= 760):
            continue
        # The ribbon's left third contains the star; OCR only its text-bearing interior.
        roi = (x + width * 30 // 100, y + height // 10,
               x + width * 85 // 100, y + height * 92 // 100)
        words = _words(frame, roi, ocr_reader=ocr_reader)
        if len(words) == 1 and _normalize(words[0].text) == "hot":
            markers.append(words[0])
    return markers[0] if len(markers) == 1 else None


def _exact_integer(text: str) -> int | None:
    if not _EXACT_AMOUNT_RE.fullmatch(text):
        return None
    try:
        value = int(text.replace(",", ""))
    except (ValueError, OverflowError):
        return None
    return value if value >= 0 else None


def _modal_hot_ribbon(frame: np.ndarray, attempts: ROI, *, ocr_reader=None) -> tuple[TextWord, ROI] | None:
    """Read HOT inside the one measured red modal-header ribbon."""
    markers = []
    for contour in cv2.findContours(_red_mask(frame), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, width, height = cv2.boundingRect(contour)
        ribbon = (x, y, x + width, y + height)
        if not (100 <= width <= 180 and 35 <= height <= 65 and x < attempts[0]
                and 150 <= attempts[1] - ribbon[3] <= 500):
            continue
        words = _words(frame, (x + width // 5, y, x + width, y + height), ocr_reader=ocr_reader)
        if len(words) == 1 and _normalize(words[0].text) == "hot":
            markers.append((words[0], ribbon))
    return markers[0] if len(markers) == 1 else None


def _modal_title(frame: np.ndarray, ribbon: ROI, attempts: ROI, *, ocr_reader=None) -> TextLine | None:
    """Bind the title above the adjacent Level row; names may be short, numeric or wrapped."""
    body = _lines(_words(frame, (ribbon[0], ribbon[3], min(800, 802 - ribbon[0]), attempts[1]),
                         ocr_reader=ocr_reader))
    levels = [(index, line) for index, line in enumerate(body) if _LEVEL_RE.fullmatch(_normalize(line.text))]
    if len(levels) != 1:
        return None
    index, level = levels[0]
    title_lines = [line for line in body[:index] if abs(line.roi[0] - level.roi[0]) <= 12]
    if not title_lines or not 0 < level.roi[1] - title_lines[-1].roi[3] <= 40:
        return None
    title_words = tuple(word for line in title_lines for word in line.words)
    title = " ".join(line.text for line in title_lines)
    roi = _union([line.roi for line in title_lines])
    return TextLine(title, roi, title_words) if roi is not None and _slug(title) else None


def _modal_buttons(frame: np.ndarray, attempts: ROI, *, ocr_reader=None):
    """Bind one gold ordinary Donate and a disjoint red gem-priced premium Donate."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) & (hsv[:, :, 1] >= 120)
            & (hsv[:, :, 2] >= 150)).astype(np.uint8)
    gem = ((hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 115)
           & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 150))
    found = {"ordinary": [], "premium": []}
    for kind, mask in (("ordinary", gold), ("premium", _red_mask(frame))):
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, width, height = cv2.boundingRect(contour)
            roi = (x, y, x + width, y + height)
            if not (180 <= width <= 300 and 55 <= height <= 100 and 0 <= y - attempts[3] <= 60):
                continue
            words = _words(frame, (x + 4, y + 4, x + width - 4, y + height - 4), ocr_reader=ocr_reader)
            controls = [word for word in words if _normalize(word.text) == "donate"]
            costs = [word for word in words if _exact_integer(word.text.replace(" ", "")) is not None]
            if len(controls) != 1 or len(costs) != 1 or costs[0].roi[3] > controls[0].roi[1] + 4:
                continue
            gem_pixels = int(np.count_nonzero(gem[y:y + height // 2 + 6, x:x + width]))
            if (kind == "premium") != (gem_pixels >= 150):
                continue
            found[kind].append((costs[0], _exact_integer(costs[0].text.replace(" ", "")), roi))
    if len(found["ordinary"]) != 1 or len(found["premium"]) != 1:
        return None
    ordinary, premium = found["ordinary"][0], found["premium"][0]
    a, b = ordinary[2], premium[2]
    if (abs((a[1] + a[3]) - (b[1] + b[3])) > 24
            or (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])):
        return None
    return ordinary, premium


def _cost_affordable(frame: np.ndarray, cost: TextWord) -> bool | None:
    """Read the ordinary cost's white amount or red shortage, without a wallet census."""
    x0, y0, x1, y1 = cost.roi
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    white = int(np.count_nonzero((s <= 60) & (v >= 200)))
    red = int(np.count_nonzero(((h <= 8) | (h >= 170)) & (s >= 120) & (v >= 120)))
    if red >= 30 and red > white:
        return False
    return True if white >= 30 and white > red else None


def _panel_observation(
    captured: Any, *, reset_id: str, evidence_ref: str, words: tuple[TextWord, ...], ocr_reader=None,
) -> DonationSurface | None:
    lines = _lines(words)
    attempt_lines = [line for line in lines if "donation attempts" in _normalize(line.text)]
    if len(attempt_lines) != 1:
        return None
    attempts_line = attempt_lines[0]
    ribbon = _modal_hot_ribbon(captured.frame, attempts_line.roi, ocr_reader=ocr_reader)
    title = _modal_title(captured.frame, ribbon[1], attempts_line.roi, ocr_reader=ocr_reader) if ribbon else None
    hot = ribbon is not None
    attempts_match = re.search(r"([0-9]{1,2})\s*/\s*([0-9]{1,2})", attempts_line.text, re.ASCII)
    attempts = int(attempts_match.group(1)) if attempts_match else None
    capacity = int(attempts_match.group(2)) if attempts_match else None
    # Only the modal's recharge timer counts; the tree's daily clock is not a refill.
    timer_matches = [_TIMER_RE.search(line.text) for line in lines
                     if ribbon and ribbon[1][3] <= line.roi[1] <= attempts_line.roi[3] + 140
                     and ribbon[1][0] <= line.roi[0] < 800 - ribbon[1][0]]
    timer_matches = [match for match in timer_matches if match is not None]
    timer_seconds = None
    if len(timer_matches) == 1:
        match = timer_matches[0]
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        if 0 <= seconds <= 1800:
            timer_seconds = seconds
    buttons = _modal_buttons(captured.frame, attempts_line.roi, ocr_reader=ocr_reader)
    chosen, premium = buttons if buttons else (None, None)
    target_roi = chosen[2] if chosen else None
    premium_roi = premium[2] if premium else None
    tech_identity = title.text.strip() if title else ""
    tech_slug = _slug(tech_identity)
    panel_bounds = _union([attempts_line.roi] + ([title.roi] if title else [])
                          + ([ribbon[1]] if ribbon else []) + ([target_roi] if target_roi else [])
                          + ([premium_roi] if premium_roi else []), pad_x=22, pad_y=18)
    donation = DonationObservation(
        screen_state=ALLIANCE_TECH_SCREEN, auto_hot_marker=hot, tech_identity=tech_identity,
        target_identity=DONATION_TARGET if chosen else "unknown", target_roi=target_roi or (0, 0, 1, 1),
        panel_bounds=panel_bounds or (0, 0, 1, 1), control_class="DONATE" if chosen else "UNKNOWN",
        donate_control_visible=chosen is not None, control_enabled=buttons is not None, quantity=1,
        donation_amount=chosen[1] if chosen else None,
        cost_affordable=_cost_affordable(captured.frame, chosen[0]) if chosen else None,
        available_attempts=attempts, attempt_capacity=capacity,
        next_attempt_available_in_seconds=timer_seconds, game_day_id=reset_id,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE, source_frame_sha256=captured.sha256,
        evidence_refs=(evidence_ref,), overlay_state="none", reset_guard_active=False,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, recognized=bool(hot and panel_bounds),
    )
    return DonationSurface("DONATION_PANEL", captured.sha256, evidence_ref,
                           DONATION_TARGET if chosen else None, target_roi, tech_identity or None,
                           tech_slug, donation, premium_roi, ribbon[0].roi if ribbon else None,
                           "current_hot_panel" if hot else "current_hot_marker_unproven")


def _alliance_tech_entry(words: tuple[TextWord, ...]) -> ROI | None:
    """Bind the menu label, not the OCR line shared with Alliance War."""
    matches: list[ROI] = []
    for line in _lines(words):
        for left, right in zip(line.words, line.words[1:]):
            if (_normalize(left.text) == "alliance" and _normalize(right.text) == "tech"
                    and 400 <= left.roi[0] < right.roi[0]
                    and 430 <= left.roi[1] <= 880
                    and abs(left.roi[1] - right.roi[1]) <= 12
                    and 0 <= right.roi[0] - left.roi[2] <= 30):
                bound = _union([left.roi, right.roi], pad_x=18, pad_y=14)
                if bound is not None:
                    matches.append(bound)
    return matches[0] if len(matches) == 1 else None


def _alliance_menu_clear(frame: np.ndarray) -> bool:
    from scripts.daily_row_claim_bluestacks import _generic_modal_overlay_evidence

    overlay = _generic_modal_overlay_evidence(frame)
    return overlay.get("recognized") is False and overlay.get("state") in {"none_observed", "none"}



def recognize_surface(
    captured: Any,
    *,
    reset_id: str,
    evidence_ref: str,
    ocr_reader: Callable[..., Mapping[str, Any]] | None = None,
) -> DonationSurface:
    """Bind Home, Alliance Tech entry, auto-HOT tree target, or donation panel."""
    frame = getattr(captured, "frame", None)
    digest = getattr(captured, "sha256", "")
    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (1280, 800) or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        return DonationSurface("UNKNOWN", str(digest), evidence_ref, reason="invalid_native_capture")
    home = recognize_home_nav(frame)
    if home.is_home and is_clean_home_frame(frame):
        return DonationSurface("HOME", digest, evidence_ref)
    words = _words(frame, (0, 35, 800, 1195), ocr_reader=ocr_reader)
    panel = _panel_observation(captured, reset_id=reset_id, evidence_ref=evidence_ref, words=words,
                               ocr_reader=ocr_reader)
    if panel is not None:
        return panel
    title_words = _words(frame, SCREEN_TITLE_ROI, ocr_reader=ocr_reader)
    header = _normalize(" ".join(word.text for word in sorted(title_words, key=lambda word: word.roi[0])))
    if header == "alliance tech":
        hot_word = _tree_hot_marker(frame, ocr_reader=ocr_reader)
        target_roi = _union([hot_word.roi], pad_x=18, pad_y=12) if hot_word else None
        # Tree names may be clipped or abbreviated. HOT selects the node; the modal supplies identity.
        return DonationSurface("TECH_TREE", digest, evidence_ref,
                               HOT_TREE_TARGET if hot_word else None, target_roi,
                               hot_roi=hot_word.roi if hot_word else None,
                               reason=("current_hot_bound" if target_roi else
                                       "waiting_for_auto_hot_scroll"))
    if header == "alliance" and _alliance_menu_clear(frame):
        target_roi = _alliance_tech_entry(words)
        return DonationSurface("ALLIANCE_HOME", digest, evidence_ref,
                               "alliance:tech-entry" if target_roi else None, target_roi,
                               reason="alliance_tech_entry_bound" if target_roi else "alliance_tech_entry_not_visible")
    return DonationSurface("UNKNOWN", digest, evidence_ref, reason="alliance_surface_unrecognized")


def to_policy_observation(captured: Any, surface: DonationSurface) -> Observation:
    donation = surface.donation
    if donation is None or surface.target_roi is None:
        raise ValueError("Alliance donation policy requires a current exact control binding")
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=ALLIANCE_TECH_SCREEN,
        overlay_state=donation.overlay_state,
        target_identity=DONATION_TARGET,
        target_roi=surface.target_roi,
        recognized=donation.recognized,
        clipped=False,
        ambiguous=False,
        control_class=donation.control_class,
        consequence=DONATION_CONSEQUENCE,
        cost_type="ordinary_resource",
        cost_amount=donation.donation_amount,
        quantity=1,
        expected_postcondition=DONATION_POSTCONDITION,
        evidence_refs=donation.evidence_refs,
        target_isolated=bool(surface.premium_roi is not None and surface.target_roi != surface.premium_roi),
        forbidden_region_intersects_target=False,
        forbidden_regions=(("premium-diamond-donate", surface.premium_roi),) if surface.premium_roi else (),
        package_foreground=True,
    )


def policy_preconditions(donation: DonationObservation, *, product_id: str, product_revision: str,
                         ordinal: int) -> tuple[str, ...]:
    if not donation_authorizeable(donation, ordinal - 1):
        raise ValueError("current affordable ordinary donation facts are required for policy")
    slug = _slug(donation.tech_identity)
    if slug is None or type(ordinal) is not int or not 1 <= ordinal <= MAX_DONATIONS_PER_RESET:
        raise ValueError("current HOT target or donation ordinal is invalid")
    return (
        f"alliance_donation_product={product_id}",
        f"alliance_donation_product_revision={product_revision}",
        f"alliance_donation_game_day={donation.game_day_id}",
        "alliance_donation_hot_marker=true",
        f"alliance_donation_target={slug}",
        f"alliance_donation_attempts={donation.available_attempts}/{donation.attempt_capacity}",
        "alliance_donation_cost_affordable=true",
        f"alliance_donation_resource={DONATION_RESOURCE}",
        f"alliance_donation_cost={donation.donation_amount}",
        "alliance_donation_quantity=1",
        "alliance_donation_single_tap=true",
        "alliance_donation_no_premium=true",
        "alliance_donation_no_refill=true",
        "alliance_donation_no_hold=true",
        f"alliance_donation_daily_action_count={ordinal - 1}",
    )


MAX_AUTO_HOT_WAIT_SECONDS = 30.0
RESOURCE_RECHECK_SECONDS = 300.0


def _identity_value(identity: Any, field: str) -> str:
    value = getattr(identity, field, None)
    if type(value) is not str or not value.strip():
        raise ValueError(f"Alliance donation identity requires {field}")
    return value


def _capture_surface(context: Any, captured: CapturedNativeFrame) -> tuple[CapturedNativeFrame, DonationSurface]:
    if not isinstance(captured, CapturedNativeFrame):
        raise TypeError("Alliance donation requires a native captured frame")
    context.checkpoint()
    context.validate_identity()
    retained, reference = context.capture_reference(captured.path, expected_sha256=captured.sha256)
    if (not isinstance(reference.frame_sha256, str) or reference.frame_sha256 != captured.sha256
            or reference.frame_path is None):
        raise RuntimeError("Alliance donation evidence reference differs from current capture")
    evidence_ref = f"native-frame://{reference.frame_path}"
    reset_id = _identity_value(context.identity, "reset_id")
    surface = recognize_surface(retained, reset_id=reset_id, evidence_ref=evidence_ref)
    return retained, surface


def _capture(context: Any, label: str) -> tuple[CapturedNativeFrame, DonationSurface]:
    context.checkpoint()
    context.validate_identity()
    captured = context.runtime.capture(label)
    return _capture_surface(context, captured)


def _home_alliance_target(captured: CapturedNativeFrame) -> tuple[str, tuple[int, int, int, int]] | None:
    if not isinstance(captured, CapturedNativeFrame):
        return None
    home = recognize_home_nav(captured.frame)
    point = home.button_tap_point("alliance")
    if not home.is_home or point is None:
        return None
    x, y = point
    return "home-nav:alliance", (x - 40, 1213, x + 40, 1280)


def _same_donation_facts(left: DonationObservation, right: DonationObservation) -> bool:
    fields = (
        "screen_state", "auto_hot_marker", "tech_identity", "target_identity", "target_roi",
        "control_class", "donate_control_visible", "control_enabled", "quantity",
        "donation_amount", "cost_affordable", "attempt_capacity",
        "game_day_id", "overlay_state", "reset_guard_active", "runtime_profile_id", "recognized",
    )
    if not all(getattr(left, name) == getattr(right, name) for name in fields):
        return False
    # A positive attempt balance can regenerate before dispatch. The fresh capability observation
    # supplies the actual baseline; the countdown itself never imposes a wait.
    return (all(type(value) is int and 0 < value <= 20
                for value in (left.available_attempts, right.available_attempts))
            and right.available_attempts in (left.available_attempts, left.available_attempts + 1))


def _unknown_policy_observation(captured: CapturedNativeFrame, evidence_ref: str) -> Observation:
    return Observation(
        frame_sha256=captured.sha256,
        capture_completed_monotonic=captured.captured_monotonic,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="UNKNOWN",
        overlay_state="unknown",
        target_identity=None,
        target_roi=None,
        recognized=False,
        evidence_refs=(evidence_ref,),
    )


def _navigation_action(
    context: Any,
    *,
    label: str,
    source_state: str,
    destination_state: str,
    bind_target: Callable[[CapturedNativeFrame, DonationSurface], tuple[str, tuple[int, int, int, int]] | None],
) -> tuple[CapturedNativeFrame, DonationSurface] | None:
    runtime, session = context.runtime, context.session
    pending: dict[str, Any] = {}

    def authorize(before: CapturedNativeFrame) -> None:
        captured, surface = _capture_surface(context, before)
        if surface.state != source_state:
            raise RuntimeError("Alliance donation navigation source changed")
        target = bind_target(captured, surface)
        if target is None:
            raise RuntimeError("Alliance donation current-frame navigation target is unavailable")
        pending["target"] = target
        pending["source_sha256"] = captured.sha256

    def dispatch(before: CapturedNativeFrame) -> None:
        target = pending.get("target")
        if target is None or before.sha256 != pending.get("source_sha256"):
            raise RuntimeError("Alliance donation navigation source was not authorized")
        context.checkpoint()
        context.validate_identity()
        identity, roi = target
        key = f"alliance-donation-nav:{context.occurrence_key}:{label}:{before.sha256[:16]}"
        pending["action_key"] = key
        runtime.tap(before, target_identity=identity, target_roi=roi, action_key=key,
                    action_class="navigation", consequential=False)

    def recognize(after: CapturedNativeFrame) -> str:
        captured, surface = _capture_surface(context, after)
        pending["after"] = (captured, surface)
        if surface.state != destination_state:
            return "unknown"
        if destination_state == "DONATION_PANEL" and (
                surface.donation is None or not surface.donation.recognized
                or not surface.donation.auto_hot_marker or not surface.tech_slug):
            return "unknown"
        return destination_state

    def settled() -> CapturedNativeFrame:
        time.sleep(max(0.0, float(context.settle_seconds)))
        context.checkpoint()
        return runtime.capture(f"{label}-settled")

    outcome = session.run_action(
        action_class="navigation",
        label=f"alliance-donation-{label}",
        capture=runtime.capture,
        authorize=authorize,
        dispatch=dispatch,
        recognize=recognize,
        settled_successor=settled,
        consequence_class="navigation_only",
    )
    action_key = pending.get("action_key")
    post = pending.get("after")
    if action_key and post is not None and callable(getattr(runtime, "reconcile", None)):
        runtime.reconcile(action_key, "confirmed" if outcome.status == "completed" else "unresolved",
                          post[0], outcome.reason)
    if outcome.status != "completed" or post is None:
        return None
    return post


def _bind_surface_target(_captured: CapturedNativeFrame, surface: DonationSurface):
    if surface.target_identity is None or surface.target_roi is None:
        return None
    return surface.target_identity, surface.target_roi




def _back_action(context: Any, surface: DonationSurface) -> tuple[CapturedNativeFrame, DonationSurface] | None:
    parent = {"DONATION_PANEL": "TECH_TREE", "TECH_TREE": "ALLIANCE_HOME", "ALLIANCE_HOME": "HOME"}.get(surface.state)
    if parent is None:
        return None
    runtime, session = context.runtime, context.session
    pending: dict[str, Any] = {}

    def authorize(before: CapturedNativeFrame) -> None:
        captured, current = _capture_surface(context, before)
        if current.state != surface.state:
            raise RuntimeError("Alliance donation Back source is not the recognized current route screen")
        pending["source_sha256"] = captured.sha256

    def dispatch(before: CapturedNativeFrame) -> None:
        if before.sha256 != pending.get("source_sha256"):
            raise RuntimeError("Alliance donation Back source changed")
        context.checkpoint()
        context.validate_identity()
        key = f"alliance-donation-back:{context.occurrence_key}:{surface.state}:{before.sha256[:16]}"
        pending["action_key"] = key
        runtime.back(before, action_key=key, target_identity=f"alliance-donation:back:{surface.state}")

    def recognize(after: CapturedNativeFrame) -> str:
        captured, current = _capture_surface(context, after)
        pending["after"] = (captured, current)
        return parent if current.state == parent else "unknown"

    def settled() -> CapturedNativeFrame:
        time.sleep(max(0.0, float(context.settle_seconds)))
        context.checkpoint()
        return runtime.capture(f"alliance-donation-back-{surface.state}-settled")

    outcome = session.run_action(action_class="navigation", label=f"alliance-donation-back-{surface.state}",
                                 capture=runtime.capture, authorize=authorize, dispatch=dispatch,
                                 recognize=recognize, settled_successor=settled,
                                 consequence_class="navigation_only")
    action_key, post = pending.get("action_key"), pending.get("after")
    if action_key and post is not None and callable(getattr(runtime, "reconcile", None)):
        runtime.reconcile(action_key, "confirmed" if outcome.status == "completed" else "unresolved",
                          post[0], outcome.reason)
    return post if outcome.status == "completed" else None


def _return_home(context: Any, current: tuple[CapturedNativeFrame, DonationSurface] | None):
    if current is None:
        return None, False
    captured, surface = current
    for _ in range(3):
        if surface.state == "HOME":
            return (captured, surface), True
        next_screen = _back_action(context, surface)
        if next_screen is None:
            return (captured, surface), False
        captured, surface = next_screen
    return (captured, surface), surface.state == "HOME"



def _canonical_count(context: Any) -> int:
    identity = context.identity
    return confirmed_donation_count(
        context.action_store.list_actions_for_task(FLOW_ID),
        flow_id=FLOW_ID,
        account_id=_identity_value(identity, "account_id"),
        server_id=_identity_value(identity, "server_id"),
        game_day_id=_identity_value(identity, "reset_id"),
    )

def _action_prefix(context: Any) -> str:
    identity = context.identity
    return donation_action_key(
        account_id=_identity_value(identity, "account_id"),
        server_id=_identity_value(identity, "server_id"),
        game_day_id=_identity_value(identity, "reset_id"),
        ordinal=1,
    ).rsplit(":", 1)[0] + ":"


def _action_once(context: Any, *, captured: CapturedNativeFrame, surface: DonationSurface,
                 ordinal: int) -> tuple[str, str, int]:
    identity = context.identity
    account_id = _identity_value(identity, "account_id")
    server_id = _identity_value(identity, "server_id")
    reset_id = _identity_value(identity, "reset_id")
    action_key = donation_action_key(account_id=account_id, server_id=server_id,
                                     game_day_id=reset_id, ordinal=ordinal)
    store, runtime, session = context.action_store, context.runtime, context.session
    existing = store.get_action_by_key(action_key)
    if existing is not None:
        if existing.get("final_status") == "cancelled":
            return "blocked", "stable_donation_ordinal_was_cancelled_without_effect", 0
        return "reconciliation_required", "stable_donation_ordinal_already_exists", 0
    if store.has_action_block():
        return "reconciliation_required", "canonical_action_requires_observe_only_reconciliation", 0
    if surface.donation is None or not donation_authorizeable(surface.donation, ordinal - 1):
        return "blocked", "fresh_ordinary_donation_control_not_authorizeable", 0
    original = surface.donation
    if original.game_day_id != reset_id or surface.tech_slug is None:
        return "blocked", "current_hot_reset_or_identity_mismatch", 0

    # Rebind to this current capture, including any newly regenerated available attempt.
    capability_frame, capability_surface = _capture(
        context, f"alliance-donation-immediate-before-{ordinal:02d}",
    )
    capability_donation = capability_surface.donation
    if (capability_surface.state != "DONATION_PANEL" or capability_donation is None
            or not _same_donation_facts(original, capability_donation)
            or not donation_authorizeable(capability_donation, ordinal - 1)):
        return "blocked", "fresh_ordinary_donation_quote_changed_before_capability", 0
    policy = CentralPolicy({FLOW_ID})
    capability_observation = to_policy_observation(capability_frame, capability_surface)
    request = PolicyRequest(
        action_id=f"alliance-donation-{ordinal:02d}-{capability_frame.sha256[:12]}",
        action_key=action_key, task_id=FLOW_ID, task_mode="supervised_validation",
        semantic_action=DONATION_ACTION, expected_runtime_profile_id=PROFILE_ID,
        observation=capability_observation, monotonic_now=float(context.monotonic_clock()),
        observation_max_age_seconds=15.0, dispatch_max_age_seconds=10.0,
        lease_owner=session.owner, lease_valid=store.lease_valid_for(session.owner, float(context.utc_clock())),
        unresolved_action=store.has_action_block(), duplicate_action_key=store.action_key_exists(action_key),
        game_day_id=reset_id, action_class=ActionClass.SPEND_OR_STRATEGIC, action_kind=PRODUCT_REVISION,
        subject=capability_surface.tech_slug, resource_or_currency=DONATION_RESOURCE,
        maximum_cost=capability_donation.donation_amount, free_only=False,
        semantic_preconditions=policy_preconditions(capability_donation, product_id=PRODUCT_ID,
                                                    product_revision=PRODUCT_REVISION, ordinal=ordinal),
        semantic_postconditions=(DONATION_POSTCONDITION,), runtime_session_id=str(runtime.session),
    )
    issued = policy.issue_capability(request)
    store.audit(FLOW_ID, "capability_issued", float(context.utc_clock()), issued.audit, request.action_id)
    if not issued.authorized or issued.capability is None:
        return "blocked", issued.reason_code, 0

    before_state: dict[str, Any] = {
        "captured": capability_frame, "surface": capability_surface,
        "dispatch_target": (capability_surface.target_identity, capability_surface.target_roi),
    }
    post: list[tuple[CapturedNativeFrame, DonationSurface]] = []
    transport_calls = 0

    def recapture() -> Observation:
        return capability_observation

    def transport(_intent: Any) -> TransportResult:
        nonlocal transport_calls
        starting_runtime_count = int(getattr(runtime, "input_count", 0))
        capture_is_bound_source = True

        def capture_for_action(label):
            nonlocal capture_is_bound_source
            if capture_is_bound_source:
                capture_is_bound_source = False
                return before_state["captured"]
            return runtime.capture(label)

        def authorize_session(session_before: CapturedNativeFrame) -> None:
            fresh, fresh_surface = _capture_surface(context, session_before)
            if (fresh_surface.state != "DONATION_PANEL" or fresh_surface.donation is None
                    or fresh_surface.tech_slug != surface.tech_slug
                    or fresh_surface.target_identity != capability_surface.target_identity
                    or fresh_surface.target_roi != capability_surface.target_roi
                    or not _same_donation_facts(original, fresh_surface.donation)
                    or not donation_authorizeable(fresh_surface.donation, ordinal - 1)):
                raise RuntimeError("Alliance donation action changed at immediate-before")
            before_state["captured"], before_state["surface"] = fresh, fresh_surface
            before_state["dispatch_target"] = (fresh_surface.target_identity, fresh_surface.target_roi)

        def dispatch_session(session_before: CapturedNativeFrame) -> None:
            nonlocal transport_calls
            target = before_state.get("dispatch_target")
            if target is None or session_before.sha256 != before_state["captured"].sha256:
                raise RuntimeError("Alliance donation immediate-before target was not authorized")
            context.checkpoint()
            context.validate_identity()
            transport_calls += 1
            runtime.tap(session_before, target_identity=target[0], target_roi=target[1],
                        action_key=action_key, action_class="alliance_donation_effect", consequential=True)

        def recognize(after: CapturedNativeFrame) -> str:
            settled_frame, after_surface = _capture_surface(context, after)
            post.append((settled_frame, after_surface))
            after_donation = after_surface.donation
            return (DONATION_POSTCONDITION if after_donation is not None and donation_postcondition_verified(
                before_state["surface"].donation, after_donation, ordinal - 1,
                elapsed_seconds=settled_frame.captured_monotonic - before_state["captured"].captured_monotonic)
                    else "unknown")

        def settled_successor() -> CapturedNativeFrame:
            time.sleep(max(0.0, float(context.settle_seconds)))
            context.checkpoint()
            return runtime.capture(f"alliance-donation-{ordinal:02d}-settled")

        session.run_action(
            action_class="alliance_donation_effect",
            label=f"alliance-donation-{ordinal:02d}",
            capture=capture_for_action,
            authorize=authorize_session,
            dispatch=dispatch_session,
            recognize=recognize,
            settled_successor=settled_successor,
            consequence_class=DONATION_CONSEQUENCE,
        )
        current_runtime_count = int(getattr(runtime, "input_count", 0))
        dispatched = current_runtime_count == starting_runtime_count + 1
        return TransportResult(dispatched, "ALLIANCE_DONATION_DISPATCHED" if dispatched else
                               "ALLIANCE_DONATION_NOT_DISPATCHED")

    def post_observe():
        for frame, post_surface in post:
            if post_surface.donation is None:
                yield _unknown_policy_observation(frame, f"native-frame://{frame.path}")
                continue
            try:
                yield to_policy_observation(frame, post_surface)
            except ValueError:
                yield _unknown_policy_observation(frame, f"native-frame://{frame.path}")

    def reconcile(_intent: Any, observed: Observation) -> bool:
        candidate = next((item for item in post if item[0].sha256 == observed.frame_sha256), None)
        if candidate is None or candidate[1].donation is None:
            return False
        return donation_postcondition_verified(
            before_state["surface"].donation, candidate[1].donation, ordinal - 1,
            elapsed_seconds=candidate[0].captured_monotonic - before_state["captured"].captured_monotonic)

    execution = SafeActionExecutor(
        store,
        policy,
        session.owner,
        context.monotonic_clock,
        transport=transport,
        recapture=recapture,
        post_observe=post_observe,
        reconcile=reconcile,
        wall_clock=context.utc_clock,
        max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    action_row = store.get_action_by_key(action_key)
    if post and callable(getattr(runtime, "reconcile", None)):
        runtime.reconcile(action_key,
                          "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved",
                          post[-1][0], execution.reason)
    if (execution.status is ActionStatus.CONFIRMED and action_row is not None
            and action_row.get("final_status") == ActionStatus.CONFIRMED.value):
        persisted_count = _canonical_count(context)
        if persisted_count != ordinal:
            return "reconciliation_required", "canonical_donation_count_mismatch_after_confirmation", transport_calls
        return "confirmed", "ordinary_donation_confirmed", transport_calls
    if execution.status in {ActionStatus.UNRESOLVED, ActionStatus.INPUT_SENT} or transport_calls:
        return "reconciliation_required", execution.reason, max(transport_calls, execution.transport_calls)
    return "blocked", execution.reason, max(transport_calls, execution.transport_calls)


def _empty_result(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "donation_transport_calls": 0,
        "committed_action_count": 0,
        "daily_committed_action_count": 0,
        "terminal_home_verified": False,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
    }


def run_alliance_donation(context: Any, arguments: Mapping[str, object]) -> Mapping[str, object]:
    """Run only through the borrowed service-owned runtime/session and canonical store."""
    del arguments
    result = _empty_result("blocked", "alliance_donation_initial_home_not_proven")
    current: tuple[CapturedNativeFrame, DonationSurface] | None = None
    committed_this_run = 0
    next_eligible_at = None
    try:
        context.validate_identity()
        if context.flow_id != FLOW_ID or context.product_id != PRODUCT_ID or context.product_revision != PRODUCT_REVISION:
            raise ValueError("Alliance donation native context binding mismatch")
        if (context.runtime_profile_id != PROFILE_ID or context.max_inputs != MAX_INPUTS
                or context.max_actions != MAX_DONATIONS_PER_RESET):
            raise ValueError("Alliance donation profile or input/action budget mismatch")
        captured, surface = _capture_surface(context, context.initial_frame)
        if surface.state != "HOME":
            result["reason"] = "alliance_donation_requires_recognized_home_start"
            current = (captured, surface)
            return _finish(context, result, current, committed_this_run)
        current = (captured, surface)
        if getattr(context.session, "initial_observation", None) is None:
            context.bind_initial_observation(captured, extra={"alliance_donation_source": "recognized_home"})
        if context.action_store.has_action_block():
            result.update(status="reconciliation_required",
                          reason="canonical_action_requires_observe_only_reconciliation",
                          effect_reconciliation_required=True, identical_retry_denied=True)
            return _finish(context, result, current, committed_this_run)
        try:
            initial_count = _canonical_count(context)
        except DonationActionReconciliationError as exc:
            result.update(status="reconciliation_required", reason=str(exc),
                          effect_reconciliation_required=True, identical_retry_denied=True)
            return _finish(context, result, current, committed_this_run)
        if initial_count >= MAX_DONATIONS_PER_RESET:
            result.update(status="complete_for_reset", reason="ten_confirmed_ordinary_donations_reached")
            return _finish(context, result, current, committed_this_run)

        if _home_alliance_target(captured) is None:
            result["reason"] = "alliance_donation_home_alliance_target_unbound"
            return _finish(context, result, current, committed_this_run)
        entered = _navigation_action(
            context,
            label="open-alliance",
            source_state="HOME",
            destination_state="ALLIANCE_HOME",
            bind_target=lambda before, _surface: _home_alliance_target(before),
        )
        if entered is None:
            result["reason"] = "alliance_donation_alliance_successor_unproven"
            current = _capture(context, "alliance-donation-after-alliance-entry")
            return _finish(context, result, current, committed_this_run)
        current = entered

        menu = _navigation_action(
            context,
            label="open-alliance-tech",
            source_state="ALLIANCE_HOME",
            destination_state="TECH_TREE",
            bind_target=_bind_surface_target,
        )
        if menu is None:
            result["reason"] = "alliance_donation_tech_entry_successor_unproven"
            current = _capture(context, "alliance-donation-after-tech-entry")
            return _finish(context, result, current, committed_this_run)
        current = menu

        hot_deadline = float(context.monotonic_clock()) + MAX_AUTO_HOT_WAIT_SECONDS
        previous_roi = None
        while current is not None and current[1].state == "TECH_TREE":
            roi = current[1].target_roi
            if roi is not None and previous_roi is not None and all(
                    abs(a - b) <= _HOT_STABLE_PIXELS for a, b in zip(roi, previous_roi)):
                break
            if float(context.monotonic_clock()) >= hot_deadline:
                result["reason"] = "alliance_donation_auto_hot_marker_not_stable"
                return _finish(context, result, current, committed_this_run)
            previous_roi = roi
            context.checkpoint()
            time.sleep(min(0.5, max(0.05, float(context.settle_seconds))))
            current = _capture(context, "alliance-donation-wait-auto-hot")
        if current is None or current[1].state != "TECH_TREE" or current[1].target_roi is None:
            result["reason"] = "alliance_donation_auto_hot_tree_unrecognized"
            return _finish(context, result, current, committed_this_run)
        stable_roi = current[1].target_roi

        def bind_current_hot(_captured, fresh):
            if fresh.target_roi is None or any(
                    abs(a - b) > _HOT_STABLE_PIXELS for a, b in zip(stable_roi, fresh.target_roi)):
                return None
            return _bind_surface_target(_captured, fresh)

        opened = _navigation_action(
            context, label="open-current-auto-hot-tech", source_state="TECH_TREE",
            destination_state="DONATION_PANEL", bind_target=bind_current_hot,
        )
        if opened is None:
            result["reason"] = "alliance_donation_hot_panel_successor_unproven"
            current = _capture(context, "alliance-donation-after-hot-panel")
            return _finish(context, result, current, committed_this_run)
        current = opened

        if context.action_store.has_action_block():
            result["status"] = "reconciliation_required"
            result["reason"] = "canonical_action_requires_observe_only_reconciliation"
            result["effect_reconciliation_required"] = True
            result["identical_retry_denied"] = True
            return _finish(context, result, current, committed_this_run)

        while True:
            context.validate_identity()
            current = _capture(context, "alliance-donation-fresh-current-hot")
            captured, surface = current
            if surface.state != "DONATION_PANEL" or surface.donation is None:
                result["status"] = "blocked"
                result["reason"] = "alliance_donation_current_hot_panel_lost"
                break
            if surface.donation.game_day_id != _identity_value(context.identity, "reset_id"):
                result["status"] = "blocked"
                result["reason"] = "alliance_donation_reset_identity_mismatch"
                break
            try:
                daily_count = _canonical_count(context)
            except DonationActionReconciliationError as exc:
                result["status"] = "reconciliation_required"
                result["reason"] = str(exc)
                result["effect_reconciliation_required"] = True
                result["identical_retry_denied"] = True
                break
            if daily_count >= MAX_DONATIONS_PER_RESET:
                result["status"] = "complete_for_reset"
                result["reason"] = "ten_confirmed_ordinary_donations_reached"
                break
            disposition = donation_disposition(surface.donation, daily_count)
            if disposition in {DonationDisposition.NO_ATTEMPTS, DonationDisposition.INSUFFICIENT_RESOURCE}:
                result["status"] = "deferred"
                result["reason"] = disposition.value
                donation = surface.donation
                observed_at = float(context.utc_clock())
                seconds = donation.next_attempt_available_in_seconds
                if disposition is DonationDisposition.NO_ATTEMPTS and type(seconds) is int and seconds > 0:
                    delay = seconds
                    eligibility_source = "observed_attempt_timer"
                    timer = seconds
                elif disposition is DonationDisposition.NO_ATTEMPTS:
                    delay = RESOURCE_RECHECK_SECONDS
                    eligibility_source = "safe_attempt_recheck"
                    timer = None
                else:
                    delay = RESOURCE_RECHECK_SECONDS
                    eligibility_source = "safe_resource_recheck"
                    timer = None
                next_eligible_at = observed_at + float(delay)
                result["availability_evidence"] = {
                    "reason": disposition.value,
                    "observed_at_utc": observed_at,
                    "source_frame_sha256": donation.source_frame_sha256,
                    "evidence_ref": donation.evidence_refs[0] if donation.evidence_refs else "",
                    "tech_identity": donation.tech_identity,
                    "available_attempts": donation.available_attempts,
                    "attempt_capacity": donation.attempt_capacity,
                    "cost_affordable": donation.cost_affordable,
                    "donation_amount": donation.donation_amount,
                    "game_day_id": donation.game_day_id,
                    "next_attempt_available_in_seconds": timer,
                    "next_eligibility_source": eligibility_source,
                }
                break
            if disposition is not DonationDisposition.READY:
                result["status"] = "blocked"
                result["reason"] = "alliance_donation_current_target_cost_or_control_unproven"
                break
            outcome, reason, calls = _action_once(context, captured=captured, surface=surface,
                                                  ordinal=daily_count + 1)
            result["donation_transport_calls"] += calls
            result["status"] = outcome
            result["reason"] = reason
            if outcome == "confirmed":
                committed_this_run += 1
                continue
            if outcome == "reconciliation_required":
                result["effect_reconciliation_required"] = True
                result["identical_retry_denied"] = True
            break
    except DonationActionReconciliationError as exc:
        result["status"] = "reconciliation_required"
        result["reason"] = str(exc)
        result["effect_reconciliation_required"] = True
        result["identical_retry_denied"] = True
    except Exception as exc:
        result["status"] = "reconciliation_required" if context.action_store.has_action_block() else "blocked"
        result["reason"] = f"{type(exc).__name__}:{exc}"
        result["effect_reconciliation_required"] = bool(context.action_store.has_action_block())
        result["identical_retry_denied"] = bool(context.action_store.has_action_block())
        try:
            current = _capture(context, "alliance-donation-after-error")
        except Exception:
            current = None
    result["next_eligible_at"] = next_eligible_at
    return _finish(context, result, current, committed_this_run)


def _finish(context: Any, result: dict[str, Any], current: tuple[CapturedNativeFrame, DonationSurface] | None,
            committed_this_run: int):
    returned, home_verified = _return_home(context, current)
    if returned is not None:
        current = returned
    result["terminal_home_verified"] = home_verified
    result["daily_committed_action_count"] = 0
    try:
        actions = context.action_store.list_actions_for_task(FLOW_ID)
        # Report the confirmed prefix even when a later ordinal requires reconciliation.
        result["daily_committed_action_count"] = confirmed_donation_count(
            [action for action in actions if action.get("final_status") == "confirmed"],
            flow_id=FLOW_ID, account_id=_identity_value(context.identity, "account_id"),
            server_id=_identity_value(context.identity, "server_id"),
            game_day_id=_identity_value(context.identity, "reset_id"),
        )
        runtime_keys = getattr(context.runtime, "action_keys", set())
        if isinstance(runtime_keys, set):
            prefix = _action_prefix(context)
            confirmed_keys = {
                action.get("action_key") for action in actions
                if action.get("final_status") == "confirmed"
                and type(action.get("action_key")) is str
                and action["action_key"].startswith(prefix)
            }
            result["committed_action_count"] = len(runtime_keys & confirmed_keys)
        else:
            result["committed_action_count"] = committed_this_run
        _canonical_count(context)  # Unresolved/corrupt later rows still deny eligibility and retries.
    except Exception as exc:
        result["committed_action_count"] = committed_this_run
        result["status"] = "reconciliation_required"
        result["reason"] = f"canonical_donation_count_unavailable:{type(exc).__name__}"
        result["effect_reconciliation_required"] = True
        result["identical_retry_denied"] = True
    if current is not None:
        result["terminal_frame_sha256"] = current[0].sha256
        result["evidence_refs"] = (current[1].evidence_ref,)
    if not home_verified:
        result["home_return_reason"] = "alliance_donation_terminal_home_not_verified"
        if result.get("status") not in {"reconciliation_required", "unresolved"}:
            result["status"] = "blocked"
            result["reason"] = result.get("home_return_reason")
    result["terminal_status"] = "completed" if home_verified else "evidence_required"
    context.session.terminal_status = result["terminal_status"]
    return result


def create_service_binding(make_native_route_binding):
    """Return the fixed device-free service binding for the canonical runtime."""
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:alliance-donation",
        workflow="alliance-donation",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_DONATIONS_PER_RESET,
        driver=run_alliance_donation,
        lease_seconds=3600.0,
    )


__all__ = ["create_service_binding", "run_alliance_donation"]
