"""Canonical same-context native route for Nano production followed by Normal Craft."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
import math
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from automation_service.nanoweapon import MAX_ACTIONS
from automation_service.registry import (
    NANOWEAPON_FLOW_ID,
    NANOWEAPON_MAX_INPUTS,
    NANOWEAPON_PRODUCT_ID,
    NANOWEAPON_PRODUCT_REVISION,
    NANOWEAPON_PROFILE_ID,
)
from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from scripts.bounded_tesseract import call_ocr, tesseract_data, tesseract_string
from scripts.home_atlas_bluestacks import load_home_atlas
from tasks.home_atlas_vision import BlueStacksHomeLocalizer
from tasks.nano_material_production import NANO_MATERIAL_PRODUCTION_TARGET
from tasks.nanoweapon import (
    CRAFT_WEAPON_TAB,
    NANOWEAPON_NORMAL_TARGET,
    NORMAL_CRAFT_DURATION_SECONDS,
    NANO_PARTS_REQUIRED,
    NanoweaponObservation,
    nanoweapon_active_craft_authorizeable,
    nanoweapon_active_craft_due_at,
    nanoweapon_authorizeable,
    nanoweapon_claim_authorizeable,
    nanoweapon_claim_postcondition_verified,
    nanoweapon_claim_transaction_spec,
    nanoweapon_current_reset_start_known,
    nanoweapon_known_material_shortage,
    nanoweapon_postcondition_verified,
    nanoweapon_shortage_due_at,
    nanoweapon_transaction_spec,
)
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE
from tasks.runtime_identity import FIXED_RUNTIME_SCOPE


FLOW_ID = NANOWEAPON_FLOW_ID
PRODUCT_ID = NANOWEAPON_PRODUCT_ID
PRODUCT_REVISION = NANOWEAPON_PRODUCT_REVISION
PROFILE_ID = NANOWEAPON_PROFILE_ID
MAX_INPUTS = NANOWEAPON_MAX_INPUTS
DEFAULT_OBSERVATION_INTERVAL_SECONDS = 300
DEFAULT_ATLAS = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_TIMER_RE = re.compile(r"(?<![0-9])([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])(?![0-9])", re.ASCII)
_AMOUNT_RE = re.compile(r"(?<![0-9])([0-9][0-9,]*)(?![0-9])", re.ASCII)


@dataclass(frozen=True)
class _Word:
    text: str
    roi: tuple[int, int, int, int]
    confidence: float
    line: tuple[int, int, int]


@dataclass(frozen=True)
class NanoweaponScreen:
    observation: NanoweaponObservation
    lines: tuple[tuple[str, tuple[_Word, ...]], ...]
    craft_tab_roi: tuple[int, int, int, int] | None
    claim_roi: tuple[int, int, int, int] | None
    craft_roi: tuple[int, int, int, int] | None
    back_roi: tuple[int, int, int, int] | None
    screen_recognized: bool
    reason: str


def _normalize(text: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold(), re.ASCII))


def _read_words(
    frame: np.ndarray,
    *,
    token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None,
) -> tuple[_Word, ...]:
    if not isinstance(frame, np.ndarray) or frame.shape != (1280, 800, 3):
        return ()
    try:
        raw = call_ocr(token_reader or tesseract_data, frame, config="--psm 11", call_timeout=5.0)
    except Exception:
        return ()
    if not isinstance(raw, Mapping):
        return ()
    names = ("text", "left", "top", "width", "height", "conf", "block_num", "par_num", "line_num")
    if any(not isinstance(raw.get(name), (tuple, list)) for name in names):
        return ()
    size = min(len(raw[name]) for name in names)
    words: list[_Word] = []
    for index in range(size):
        text = str(raw["text"][index]).strip()
        if not text:
            continue
        try:
            x, y = int(raw["left"][index]), int(raw["top"][index])
            width, height = int(raw["width"][index]), int(raw["height"][index])
            confidence = float(raw["conf"][index])
            line = (int(raw["block_num"][index]), int(raw["par_num"][index]), int(raw["line_num"][index]))
        except (TypeError, ValueError, OverflowError):
            continue
        if width <= 0 or height <= 0 or confidence < 35:
            continue
        x1, y1 = min(800, x + width), min(1280, y + height)
        if 0 <= x < x1 and 0 <= y < y1:
            words.append(_Word(text, (x, y, x1, y1), confidence, line))
    return tuple(words)


def _lines(words: tuple[_Word, ...]) -> tuple[tuple[str, tuple[_Word, ...]], ...]:
    groups: dict[tuple[int, int, int], list[_Word]] = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    return tuple(
        (" ".join(word.text for word in ordered), ordered)
        for _key, group in sorted(groups.items())
        for ordered in (tuple(sorted(group, key=lambda item: item.roi[0])),)
    )


def _phrase_boxes(lines: Sequence[tuple[str, tuple[_Word, ...]]], phrase: str) -> list[tuple[int, int, int, int]]:
    expected = _normalize(phrase)
    found = []
    for text, words in lines:
        normalized = [_normalize(word.text) for word in words]
        joined = " ".join(value for value in normalized if value)
        if joined == expected:
            found.append(_box(words))
            continue
        if expected and f" {expected} " in f" {joined} ":
            span = len(expected.split())
            phrase_words = expected.split()
            for start in range(max(0, len(normalized) - span + 1)):
                if normalized[start : start + span] == phrase_words:
                    found.append(_box(words[start : start + span]))
                    break
    return [item for item in found if item is not None]


def _box(words: Sequence[_Word], *, pad_x: int = 8, pad_y: int = 8) -> tuple[int, int, int, int] | None:
    if not words:
        return None
    return (
        max(0, min(word.roi[0] for word in words) - pad_x),
        max(0, min(word.roi[1] for word in words) - pad_y),
        min(800, max(word.roi[2] for word in words) + pad_x),
        min(1280, max(word.roi[3] for word in words) + pad_y),
    )


def _exact_word_boxes(lines: Sequence[tuple[str, tuple[_Word, ...]]], word: str) -> list[tuple[int, int, int, int]]:
    expected = _normalize(word)
    return [tuple(token.roi) for _text, tokens in lines for token in tokens if _normalize(token.text) == expected]


def _button_roi(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    if roi is None:
        return None
    x0, y0, x1, y1 = roi
    x0, y0, x1, y1 = max(0, x0 - 44), max(0, y0 - 20), min(800, x1 + 44), min(1280, y1 + 20)
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 55, 65), (38, 255, 255))
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(gray, 60, 160)
    if float(np.count_nonzero(orange)) / float(orange.size) < 0.10:
        return None
    if float(np.count_nonzero(edge)) / float(edge.size) < 0.003:
        return None
    return (x0, y0, x1, y1)


def _overlay_clear(frame: np.ndarray) -> bool:
    try:
        from scripts.daily_row_claim_bluestacks import _generic_modal_overlay_evidence
        result = _generic_modal_overlay_evidence(frame)
    except Exception:
        return False
    return result.get("recognized") is False and result.get("state") == "none_observed"


def _timer(line: str) -> int | None:
    match = _TIMER_RE.search(line)
    if match is None:
        return None
    hours, minutes, seconds = (int(value) for value in match.groups())
    value = hours * 3600 + minutes * 60 + seconds
    return value if 0 < value <= NORMAL_CRAFT_DURATION_SECONDS else None


def _balance(lines: Sequence[tuple[str, tuple[_Word, ...]]]) -> int | None:
    candidates: list[int] = []
    for text, words in lines:
        normalized = _normalize(text)
        if "nano parts" not in normalized or not words or min(word.roi[1] for word in words) > 260:
            continue
        if any(marker in normalized for marker in ("cost", "required", "recipe", "consume")):
            continue
        amounts = [int(value.replace(",", "")) for value in _AMOUNT_RE.findall(text)]
        if len(amounts) == 1 and amounts[0] >= 0:
            candidates.append(amounts[0])
    return candidates[0] if len(candidates) == 1 else None


def _normal_recipe_name(lines: Sequence[tuple[str, tuple[_Word, ...]]]) -> str:
    excluded = {
        "normal craft", "craft weapon", "exclusive craft", "nanoweapon", "nano parts",
        "duration", "craft", "claim", "12 00 00", "43200 seconds",
    }
    candidates = []
    for text, words in lines:
        normalized = _normalize(text)
        if not normalized or normalized in excluded or not words:
            continue
        y = min(word.roi[1] for word in words)
        if 240 <= y <= 920 and not any(word in normalized for word in ("cost", "duration", "parts", "claim", "craft")):
            if len(normalized.split()) <= 4 and any(char.isalpha() for char in text):
                candidates.append(text.strip())
    return candidates[0] if len(candidates) == 1 else ""


def recognize_nanoweapon_screen(
    frame: np.ndarray,
    *,
    captured_at: float,
    frame_sha256: str,
    now: float | None = None,
    game_day_id: str | None = None,
    starts_this_reset: int | None = None,
    start_reset_id: str | None = None,
    prior_material_production_reconciled: bool = False,
    evidence_ref: str | None = None,
    text_reader: Callable[..., str] | None = None,
    token_reader: Callable[..., Mapping[str, Sequence[object]]] | None = None,
) -> NanoweaponScreen:
    """Recognize only current OCR-bound Normal Craft state; unknown labels stay unknown."""
    del now
    invalid = (
        not isinstance(frame, np.ndarray)
        or frame.shape != (1280, 800, 3)
        or type(captured_at) not in (int, float)
        or isinstance(captured_at, bool)
        or type(frame_sha256) is not str
        or not _SHA256_RE.fullmatch(frame_sha256)
    )
    if invalid:
        empty = NanoweaponObservation(
            screen_state="UNKNOWN", selected_nanoweapon=False, selected_tab="UNKNOWN", recipe_name="",
            recipe_known=False, materials_known=False, materials_available=False, nano_parts=None,
            craft_mode="UNKNOWN", target_identity="unknown", target_roi=(0, 0, 1, 1), panel_bounds=(0, 0, 800, 1280),
            control_class="unknown", recognized=False, source_frame_sha256=str(frame_sha256 or ""),
            prior_material_production_reconciled=prior_material_production_reconciled,
        )
        return NanoweaponScreen(empty, (), None, None, None, None, False, "invalid_frame_identity")

    words = _read_words(frame, token_reader=token_reader)
    lines = _lines(words)
    try:
        if text_reader is not None:
            full_text = str(call_ocr(text_reader, frame, config="--psm 11", call_timeout=5.0))
        else:
            full_text = " ".join(text for text, _line_words in lines)
    except Exception:
        full_text = ""
    normalized_text = _normalize(full_text)
    title_found = "nanoweapon" in normalized_text or "nano weapon" in normalized_text
    overlay_clear = _overlay_clear(frame)
    craft_tab_boxes = _phrase_boxes(lines, "Craft Weapon")
    material_tab_boxes = _phrase_boxes(lines, "Material Production")
    normal_selected = bool(
        re.search(
            r"\bnormal\s+craft\s+(?:selected|active)\b|\bselected\s+normal\s+craft\b|\bnormal\s+recipe\s+selected\b",
            normalized_text,
            re.ASCII,
        )
    )
    exclusive_selected = bool(re.search(r"\bexclusive\s+craft\s+(?:selected|active)\b", normalized_text, re.ASCII))
    rotating_selected = bool(re.search(r"\b(?:rotating|display)\s+(?:weapon|recipe)\s+(?:selected|active)\b", normalized_text, re.ASCII))
    recipe_name = _normal_recipe_name(lines)

    craft_label_boxes = _exact_word_boxes(lines, "Craft")
    claim_label_boxes = _exact_word_boxes(lines, "Claim")
    claim_roi = claim_label_boxes[0] if len(claim_label_boxes) == 1 else None
    craft_candidates = [roi for roi in craft_label_boxes if roi[1] >= 400]
    craft_roi = _button_roi(frame, craft_candidates[0]) if len(craft_candidates) == 1 else None
    # The exact Claim label is the control; cost and successor semantics below distinguish it
    # from any unrelated Claim elsewhere on the page.
    completed_marker = bool(re.search(r"\b(?:craft\s+complete|completed\s+craft|ready\s+to\s+claim)\b", normalized_text, re.ASCII))
    claim_visible = bool(claim_roi is not None and completed_marker and title_found)

    balance = _balance(lines)
    numeric_material_lines = []
    forbidden_payment_terms = False
    for text, line_words in lines:
        normalized = _normalize(text)
        if min((word.roi[1] for word in line_words), default=0) < 220:
            continue
        if re.search(r"\b(?:duration|craft\s+time|time\s+left|timer|quantity|qty)\b", normalized, re.ASCII):
            continue
        if _AMOUNT_RE.search(text):
            numeric_material_lines.append(normalized)
        if re.search(
            r"\b(?:diamonds?|coins?|gems?|cash|gold|silver|credits?|coupons?|premium|money|food|wood|steel|gas|boxes?|currency|tokens?|substitute)\b",
            normalized,
            re.ASCII,
        ):
            forbidden_payment_terms = True
    cost_known = bool(
        len(numeric_material_lines) == 1
        and re.fullmatch(
            r"(?:cost\s+)?(?:100\s+nano\s+parts|nano\s+parts\s+100)",
            numeric_material_lines[0],
            re.ASCII,
        )
        and not forbidden_payment_terms
    )
    duration_text = full_text + " " + " ".join(text for text, _line_words in lines)
    duration_known = bool(
        re.search(r"\b(?:duration|craft\s+time|time)\s*[:=-]?\s*(?:12\s*:\s*00\s*:\s*00|43200\s*(?:seconds?|s)|12\s*(?:hours?|hrs?))\b", duration_text, re.IGNORECASE | re.ASCII)
    )
    duration = NORMAL_CRAFT_DURATION_SECONDS if duration_known else None
    timer_lines = []
    for text, line_words in lines:
        normalized = _normalize(text)
        if any(marker in normalized for marker in ("remaining", "timer", "time left", "active")):
            value = _timer(text)
            if value is not None:
                timer_lines.append(value)
    duration_line_present = any(
        any(marker in _normalize(text) for marker in ("duration", "craft time"))
        for text, _line_words in lines
    )
    if not timer_lines and not completed_marker and not duration_line_present:
        visible_timers = [value for text, _line_words in lines if (value := _timer(text)) is not None]
        if len(visible_timers) == 1 and normal_selected:
            timer_lines = visible_timers
    timer_remaining = timer_lines[0] if len(timer_lines) == 1 else 0
    timer_active = bool(timer_remaining > 0 and not claim_visible)
    active_count = 1 if timer_active else 0 if (claim_visible or normal_selected) else None
    production_marker = any(
        marker in normalized_text for marker in ("production active", "active production", "production idle", "production complete")
    )
    selected_tab = CRAFT_WEAPON_TAB if title_found and craft_tab_boxes and normal_selected else "UNKNOWN"
    if title_found and material_tab_boxes and production_marker and not normal_selected:
        selected_tab = "MATERIAL_PRODUCTION"
    recipe_known = bool(
        title_found and normal_selected and recipe_name and not exclusive_selected and not rotating_selected
    )
    mode = "normal_recipe" if recipe_known else "unknown"
    normal_panel = bool(title_found and selected_tab == CRAFT_WEAPON_TAB and recipe_known)
    target_roi = craft_roi or (claim_roi if claim_visible else None)
    if target_roi is None and craft_tab_boxes:
        target_roi = craft_tab_boxes[0]
    if target_roi is None:
        target_roi = (120, 180, 680, 1100)
    target_identity = NANOWEAPON_NORMAL_TARGET if normal_panel else "unknown"
    control_class = "CLAIM" if claim_visible else "CRAFT" if craft_roi is not None else "unknown"
    evidence_refs = (evidence_ref,) if isinstance(evidence_ref, str) and evidence_ref.startswith(("evidence/", "synthetic:")) else ()
    observation = NanoweaponObservation(
        screen_state="NANOWEAPON" if title_found else "UNKNOWN",
        selected_nanoweapon=bool(title_found),
        selected_tab=selected_tab,
        recipe_name=recipe_name,
        recipe_known=recipe_known,
        materials_known=bool(balance is not None and cost_known),
        materials_available=bool(balance is not None and balance >= NANO_PARTS_REQUIRED),
        nano_parts=balance,
        craft_mode="CRAFT" if normal_panel else "UNKNOWN",
        target_identity=target_identity,
        target_roi=tuple(target_roi),
        panel_bounds=(80, 120, 720, 1180),
        control_class=control_class,
        craft_ready=bool(craft_roi is not None and cost_known and duration_known and recipe_known),
        duration_policy_approved=bool(duration_known),
        craft_duration_seconds=duration,
        cost_type="NANO_PARTS" if cost_known else "unknown",
        cost_amount=NANO_PARTS_REQUIRED if cost_known else None,
        quantity=1 if re.search(r"\b(?:quantity|qty|x)\s*1\b", normalized_text, re.ASCII) else None,
        craft_count=1 if claim_visible else active_count,
        craft_result_visible=bool(claim_visible and completed_marker),
        result_identity="",  # Pixels prove completion, never a durable craft instance.
        craft_timer_active=timer_active,
        game_day_id=game_day_id,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=frame_sha256,
        evidence_refs=evidence_refs,
        overlay_state="none" if overlay_clear else "unknown",
        reset_guard_active=False,
        runtime_profile_id=PROFILE_ID,
        recognized=bool(title_found and overlay_clear and selected_tab in {CRAFT_WEAPON_TAB, "MATERIAL_PRODUCTION"}),
        active_craft_count=active_count,
        craft_enabled=bool(craft_roi is not None),
        starts_this_reset=starts_this_reset,
        claim_visible=claim_visible,
        recipe_selection_mode=mode,
        craft_timer_seconds_remaining=timer_remaining,
        prior_material_production_reconciled=prior_material_production_reconciled,
    )
    back = _exact_word_boxes(lines, "Back")
    return NanoweaponScreen(
        observation=observation,
        lines=lines,
        craft_tab_roi=craft_tab_boxes[0] if len(craft_tab_boxes) == 1 else None,
        claim_roi=claim_roi,
        craft_roi=craft_roi,
        back_roi=back[0] if len(back) == 1 else None,
        screen_recognized=bool(title_found and overlay_clear),
        reason="recognized" if title_found and overlay_clear else "nanoweapon_surface_unrecognized",
    )


def _safe_home(context, frame: np.ndarray) -> bool:
    if not context.is_clean_home(frame):
        return False
    try:
        atlas = load_home_atlas(DEFAULT_ATLAS)
        localized = BlueStacksHomeLocalizer(atlas, DEFAULT_ATLAS).localize(frame)
    except Exception:
        return False
    return bool(localized.recognized and not localized.stale and not localized.overlay)


def _action_key(kind: str, *, reset_id: str, identity: Any, result_identity: str = "") -> str:
    scope = "\0".join((FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id))
    digest = hashlib.sha256(f"{scope}\0{result_identity}".encode("utf-8")).hexdigest()
    return f"{PRODUCT_ID}:{kind}:{reset_id}:{digest}"


def _previous_reset_id(reset_id: str) -> str | None:
    prefix = "game-day-"
    if not isinstance(reset_id, str) or not reset_id.startswith(prefix):
        return None
    try:
        return f"{prefix}{date.fromisoformat(reset_id[len(prefix):]) - timedelta(days=1)}"
    except ValueError:
        return None


def _canonical_action_confirmed(
    record: Mapping[str, Any] | None,
    *,
    action_key: str,
    semantic_action: str,
    target_identity: str,
    game_day_id: str,
    consequence: str,
    postcondition: str,
    cost_type: str,
    cost_amount: int,
    action_id: str | None = None,
) -> bool:
    if not isinstance(record, Mapping):
        return False
    expected = {
        "action_key": action_key,
        "task_id": FLOW_ID,
        "semantic_action": semantic_action,
        "source_state": "NANOWEAPON",
        "target_identity": target_identity,
        "runtime_profile_id": PROFILE_ID,
        "game_day_id": game_day_id,
        "consequence": consequence,
        "expected_postcondition": postcondition,
        "cost_type": cost_type,
        "cost_amount": cost_amount,
        "quantity": 1,
        "consequential": 1,
        "final_status": ActionStatus.CONFIRMED.value,
    }
    if action_id is not None:
        expected["action_id"] = action_id
    cost_amount_value = record.get("cost_amount")
    return bool(
        type(record.get("action_id")) is str
        and bool(record.get("action_id"))
        and type(record.get("quantity")) is int
        and type(cost_amount_value) in (int, float)
        and math.isfinite(cost_amount_value)
        and type(record.get("consequential")) is int
        and all(record.get(field) == value for field, value in expected.items())
    )


def _confirmed_start_record(
    record: Mapping[str, Any] | None,
    *,
    action_key: str,
    game_day_id: str,
) -> bool:
    return _canonical_action_confirmed(
        record,
        action_key=action_key,
        semantic_action="start_one_normal_nanoweapon_craft",
        target_identity=NANOWEAPON_NORMAL_TARGET,
        game_day_id=game_day_id,
        consequence="nanoweapon_normal_craft",
        postcondition="NANOWEAPON_NORMAL_CRAFT_ACTIVE",
        cost_type="NANO_PARTS",
        cost_amount=NANO_PARTS_REQUIRED,
    )


def _claim_instance_key(identity: Any, start: Mapping[str, Any]) -> str:
    return _action_key(
        "claim-instance",
        reset_id=start["game_day_id"],
        identity=identity,
        result_identity=start["action_id"],
    )


def _completed_craft_binding(context: Any) -> tuple[str, str]:
    """Resolve the sole unclaimed journaled start without inventing a manual instance.

    Legacy reset-scoped claims are retained and consumed only when their preceding
    start is unambiguous. Ordering is journal history, not an estimated craft time.
    """
    identity = context.identity
    records = context.action_store.list_actions_for_task(FLOW_ID)
    starts: list[Mapping[str, Any]] = []
    claimed: set[str] = set()
    for record in records:
        reset = record.get("game_day_id")
        if type(reset) is not str or not reset:
            continue
        start_key = _action_key("start", reset_id=reset, identity=identity)
        if record.get("action_key") == start_key:
            if not _confirmed_start_record(record, action_key=start_key, game_day_id=reset):
                raise ValueError("Normal Craft instance has unresolved start history")
            starts.append(record)
    for start in starts:
        key = _claim_instance_key(identity, start)
        claim = context.action_store.get_action_by_key(key)
        if claim is not None:
            if not _canonical_action_confirmed(
                claim, action_key=key, semantic_action="claim_completed_nanoweapon",
                target_identity="nanoweapon-completed-claim",
                game_day_id=claim.get("game_day_id"),
                consequence="nanoweapon_completed_claim",
                postcondition="NANOWEAPON_CRAFT_CLAIMED", cost_type="none", cost_amount=0,
            ):
                raise ValueError("Normal Craft instance claim is unresolved; identical retry denied")
            claimed.add(start["action_id"])
    for record in records:
        reset = record.get("game_day_id")
        if type(reset) is not str or not reset:
            continue
        legacy_key = _action_key(
            "claim", reset_id=reset, identity=identity,
            result_identity="completed-normal-craft",
        )
        if record.get("action_key") != legacy_key:
            continue
        if not _canonical_action_confirmed(
            record, action_key=legacy_key, semantic_action="claim_completed_nanoweapon",
            target_identity="nanoweapon-completed-claim", game_day_id=reset,
            consequence="nanoweapon_completed_claim",
            postcondition="NANOWEAPON_CRAFT_CLAIMED", cost_type="none", cost_amount=0,
        ):
            raise ValueError("legacy Normal Craft claim is unresolved; identical retry denied")
        preceding = [
            start for start in starts
            if start["action_id"] not in claimed
            and start["prepared_at"] < record["prepared_at"]
        ]
        if len(preceding) > 1 or any(
            start["prepared_at"] == record["prepared_at"] for start in starts
        ):
            raise ValueError("legacy Normal Craft claim instance is ambiguous; evidence_required")
        if preceding:
            claimed.add(preceding[0]["action_id"])
    unclaimed = [start for start in starts if start["action_id"] not in claimed]
    if len(unclaimed) != 1:
        raise ValueError("completed Normal Craft has no unique unclaimed durable instance; evidence_required")
    start = unclaimed[0]
    return f"craft-instance:{start['action_id']}", _claim_instance_key(identity, start)

def _frame_observation(
    context: Any,
    captured: Any,
    *,
    source_state: str,
    target_identity: str,
    target_roi: tuple[int, int, int, int],
    control_class: str,
    consequence: str,
    postcondition: str,
    cost_type: str = "none",
    cost_amount: int = 0,
    quantity: int = 1,
) -> Observation:
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=PROFILE_ID,
        width=int(captured.frame.shape[1]),
        height=int(captured.frame.shape[0]),
        valid_png=True,
        corrupt=False,
        black=not bool(captured.frame.any()),
        source_state=source_state,
        overlay_state="none",
        target_identity=target_identity,
        target_roi=target_roi,
        recognized=True,
        control_class=control_class,
        consequence=consequence,
        cost_type=cost_type,
        cost_amount=cost_amount,
        quantity=quantity,
        expected_postcondition=postcondition,
        evidence_refs=(str(captured.path),),
        source_family="nanoweapon",
        target_isolated=True,
        package_foreground=str(context.runtime.measure_foreground_package()) == "com.global.ztmslg",
    )
def _evidence_ref(context: Any, captured: Any) -> str:
    try:
        relative = Path(captured.path).resolve().relative_to(
            Path(context.session.session_directory).resolve()
        )
    except (OSError, ValueError, TypeError):
        return ""
    return "evidence/" + relative.as_posix()


def _recognize_capture(context: Any, captured: Any, *, bind_completed_instance: bool = True,
                       **kwargs: Any) -> NanoweaponScreen:
    screen = recognize_nanoweapon_screen(
        captured.frame,
        captured_at=captured.captured_monotonic,
        frame_sha256=captured.sha256,
        evidence_ref=_evidence_ref(context, captured),
        **kwargs,
    )
    if bind_completed_instance and screen.observation.claim_visible:
        instance, _key = _completed_craft_binding(context)
        screen = replace(screen, observation=replace(screen.observation, result_identity=instance))
    return screen


def _execute_consequential(
    context: Any,
    *,
    before_capture: Any,
    before: NanoweaponObservation,
    action_key: str,
    action_kind: str,
    monotonic_clock: Callable[[], float],
    wall_clock: Callable[[], float],
) -> dict[str, Any]:
    claim = action_kind == "CLAIM_NANOWEAPON_COMPLETED"
    spec = nanoweapon_claim_transaction_spec(before) if claim else nanoweapon_transaction_spec(before)
    if before_capture.sha256 != before.source_frame_sha256:
        return {"status": "blocked", "reason": "nanoweapon_source_frame_changed", "transport_calls": 0}
    target_identity = spec.subject
    target_roi = tuple(before.target_roi)
    postcondition = (
        "NANOWEAPON_CRAFT_CLAIMED"
        if claim else "NANOWEAPON_NORMAL_CRAFT_ACTIVE"
    )
    semantic_action = "claim_completed_nanoweapon" if claim else "start_one_normal_nanoweapon_craft"
    consequence = "nanoweapon_completed_claim" if claim else "nanoweapon_normal_craft"
    control_class = "CLAIM" if claim else "CRAFT"
    action_class = ActionClass.ZERO_COST_CONSEQUENTIAL if claim else ActionClass.SPEND_OR_STRATEGIC
    maximum_cost = 0 if claim else NANO_PARTS_REQUIRED
    resource = "none" if claim else "NANO_PARTS"
    currency = None if claim else "NANO_PARTS"
    free_only = claim
    monotonic_now = float(monotonic_clock())
    wall_now = float(wall_clock())
    store = context.action_store
    request = PolicyRequest(
        action_id=f"nanoweapon:{action_kind.lower()}:{hashlib.sha256((action_key + before_capture.sha256).encode()).hexdigest()[:24]}",
        action_key=action_key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action=semantic_action,
        expected_runtime_profile_id=PROFILE_ID,
        observation=_frame_observation(
            context,
            before_capture,
            source_state="NANOWEAPON",
            target_identity=target_identity,
            target_roi=target_roi,
            control_class=control_class,
            consequence=consequence,
            postcondition=postcondition,
            cost_type=resource,
            cost_amount=maximum_cost,
            quantity=1,
        ),
        monotonic_now=monotonic_now,
        observation_max_age_seconds=2.0,
        dispatch_max_age_seconds=2.0,
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, wall_now),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        game_day_id=before.game_day_id,
        action_class=action_class,
        action_kind=action_kind,
        subject=target_identity,
        resource_or_currency=currency,
        maximum_cost=maximum_cost,
        free_only=free_only,
        semantic_preconditions=spec.semantic_preconditions,
        semantic_postconditions=(postcondition,),
        runtime_session_id=str(context.runtime.session),
    )
    policy = CentralPolicy(frozenset({FLOW_ID}))

    successors: list[tuple[Any, NanoweaponObservation | None, bool]] = []
    runtime = context.runtime
    session_capture_returned = False
    immediate = {"capture": before_capture}

    def recognize_successor(captured: Any) -> bool:
        after_screen = _recognize_capture(
            context,
            captured,
            game_day_id=before.game_day_id,
            starts_this_reset=before.starts_this_reset if claim else 1,
            start_reset_id=before.game_day_id,
            prior_material_production_reconciled=True,
        )
        after = after_screen.observation
        verified = (
            nanoweapon_claim_postcondition_verified(before, after)
            if claim
            else nanoweapon_postcondition_verified(before, after)
        )
        successors.append((captured, after, bool(verified)))
        return bool(verified)

    def recapture() -> Observation:
        nonlocal before_capture, before
        if immediate.get("observation") is not None:
            return immediate["observation"]
        context.checkpoint()
        context.validate_identity()
        fresh_capture = runtime.capture(f"nanoweapon-{action_kind.lower()}-pre-dispatch")
        fresh_screen = _recognize_capture(
            context,
            fresh_capture,
            game_day_id=before.game_day_id,
            starts_this_reset=before.starts_this_reset,
            start_reset_id=before.game_day_id,
            prior_material_production_reconciled=True,
        )
        fresh = fresh_screen.observation
        authorizeable = (
            nanoweapon_claim_authorizeable(fresh)
            if claim
            else nanoweapon_authorizeable(fresh)
        )
        if (
            not fresh_screen.screen_recognized
            or not authorizeable
            or fresh.target_identity != before.target_identity
            or fresh.target_roi != before.target_roi
            or fresh.nano_parts != before.nano_parts
            or fresh.game_day_id != before.game_day_id
            or fresh.selected_tab != before.selected_tab
            or fresh.claim_visible != before.claim_visible
            or fresh.craft_timer_seconds_remaining != before.craft_timer_seconds_remaining
            or fresh.result_identity != before.result_identity
            or fresh.starts_this_reset != before.starts_this_reset
        ):
            raise ValueError("Nanoweapon immediate pre-dispatch state changed")
        before_capture = fresh_capture
        before = fresh
        immediate["capture"] = fresh_capture
        immediate["observation"] = _frame_observation(
            context,
            fresh_capture,
            source_state="NANOWEAPON",
            target_identity=target_identity,
            target_roi=tuple(fresh.target_roi),
            control_class=control_class,
            consequence=consequence,
            postcondition=postcondition,
            cost_type=resource,
            cost_amount=maximum_cost,
            quantity=1,
        )
        return immediate["observation"]

    capability_observation = recapture()
    issue_time = float(wall_clock())
    capability_request = replace(
        request,
        observation=capability_observation,
        monotonic_now=float(monotonic_clock()),
        lease_owner=context.session.owner,
        lease_valid=store.lease_valid_for(context.session.owner, issue_time),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(action_key),
        policy_phase="pre_dispatch",
    )
    issued = policy.issue_capability(capability_request)
    store.audit(FLOW_ID, "capability_issued", issue_time, issued.audit, request.action_id)
    if not issued.authorized or issued.capability is None:
        return {
            "status": "blocked",
            "reason": issued.reason_code,
            "transport_calls": 0,
            "action_key": action_key,
        }

    def one_immediate(label: str):
        nonlocal session_capture_returned
        if not session_capture_returned:
            session_capture_returned = True
            return immediate["capture"]
        return runtime.capture(label)

    def transport(_intent: Any) -> TransportResult:
        start_inputs = int(runtime.input_count)

        def authorize(current: Any) -> None:
            rebound_screen = _recognize_capture(
                context,
                current,
                game_day_id=before.game_day_id,
                starts_this_reset=before.starts_this_reset,
                start_reset_id=before.game_day_id,
                prior_material_production_reconciled=True,
                bind_completed_instance=False,
            )
            rebound = rebound_screen.observation
            if claim:
                prepared = store.get_action_by_key(action_key)
                if (prepared is None or prepared["action_id"] != request.action_id
                        or prepared["final_status"] != "prepared"):
                    raise RuntimeError("Normal Craft Claim lacks its current prepared intent")
                # Identity comes from the unique confirmed start bound before
                # preparation, not pixels. Do not mistake our own prepared claim
                # for an uncertain prior invocation when rechecking that frame.
                rebound = replace(rebound, result_identity=before.result_identity)
            same = (
                current.sha256 == before_capture.sha256
                and rebound.source_frame_sha256 == before.source_frame_sha256
                and rebound.target_identity == before.target_identity
                and rebound.target_roi == before.target_roi
                and rebound.nano_parts == before.nano_parts
                and rebound.game_day_id == before.game_day_id
                and rebound.selected_tab == before.selected_tab
                and rebound.claim_visible == before.claim_visible
                and rebound.craft_timer_seconds_remaining == before.craft_timer_seconds_remaining
                and (nanoweapon_claim_authorizeable(rebound) if claim else nanoweapon_authorizeable(rebound))
            )
            if not same:
                raise RuntimeError("Nanoweapon selector or source changed before dispatch")
            context.checkpoint()
            context.validate_identity()

        def dispatch(current: Any) -> None:
            context.checkpoint()
            context.validate_identity()
            runtime.tap(
                current,
                target_identity=target_identity,
                target_roi=target_roi,
                action_key=action_key,
                action_class=action_kind,
                consequential=True,
            )

        def settled():
            time.sleep(float(context.settle_seconds))
            context.checkpoint()
            return runtime.capture(f"nanoweapon-{action_kind.lower()}-successor-settled")

        try:
            context.session.run_action(
                action_class=action_kind,
                label=f"nanoweapon-{action_kind.lower()}",
                capture=one_immediate,
                authorize=authorize,
                dispatch=dispatch,
                recognize=lambda captured: postcondition if recognize_successor(captured) else "unknown",
                settled_successor=settled,
                consequence_class=consequence,
            )
        except Exception as exc:
            sent = int(runtime.input_count) - start_inputs
            return TransportResult(sent == 1, f"NANOWEAPON_{action_kind}_{type(exc).__name__}")
        sent = int(runtime.input_count) - start_inputs
        return TransportResult(sent == 1, "NANOWEAPON_INPUT_SENT" if sent == 1 else "NANOWEAPON_INPUT_NOT_SENT")

    def post_observe():
        for captured, after, verified in successors:
            yield Observation(
                frame_sha256=str(captured.sha256),
                capture_completed_monotonic=float(captured.captured_monotonic),
                runtime_profile_id=PROFILE_ID,
                width=800,
                height=1280,
                valid_png=True,
                corrupt=False,
                black=not bool(captured.frame.any()),
                source_state=postcondition if verified else "UNKNOWN",
                overlay_state="none" if verified else "unknown",
                target_identity=target_identity if verified else None,
                target_roi=tuple(after.target_roi) if verified and after is not None else None,
                recognized=bool(verified),
                evidence_refs=(str(captured.path),),
            )

    executor = SafeActionExecutor(
        store,
        policy,
        context.session.owner,
        monotonic_clock,
        transport,
        recapture,
        post_observe,
        lambda _intent, observed: bool(
            successors and successors[-1][2]
            and observed.frame_sha256 == successors[-1][0].sha256
        ),
        wall_clock=wall_clock,
        max_pre_dispatch_attempts=1,
    )
    starting_inputs = getattr(runtime, "input_count", None)
    try:
        execution = executor.execute(request, issued.capability)
        action_record = store.get_action_by_key(action_key)
        after = successors[-1][0] if successors else None
        after_observation = successors[-1][1] if successors else None
        if after is not None and callable(getattr(runtime, "reconcile", None)):
            runtime.reconcile(
                action_key,
                "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved",
                after,
                execution.reason,
            )
        confirmed = (
            execution.status is ActionStatus.CONFIRMED
            and _canonical_action_confirmed(
                action_record,
                action_key=action_key,
                semantic_action=semantic_action,
                target_identity=target_identity,
                game_day_id=before.game_day_id,
                consequence=consequence,
                postcondition=postcondition,
                cost_type=resource,
                cost_amount=maximum_cost,
                action_id=request.action_id,
            )
            and bool(successors and successors[-1][2])
        )
        sent = int(runtime.input_count) - starting_inputs
        return {
            "status": "confirmed" if confirmed else "unresolved" if sent else "blocked",
            "reason": execution.reason,
            "transport_calls": sent,
            "action_key": action_key,
            "journal_status": action_record.get("final_status") if action_record else None,
            "successor_capture": after,
            "successor_observation": after_observation,
            "effect_reconciliation_required": bool(sent and not confirmed),
            "identical_retry_denied": bool(sent or action_record is not None),
        }
    except Exception as exc:
        ending_inputs = getattr(runtime, "input_count", None)
        accounting_known = (
            type(starting_inputs) is int
            and type(ending_inputs) is int
            and ending_inputs >= starting_inputs
        )
        sent = ending_inputs - starting_inputs if accounting_known else 0
        try:
            journal_blocked = bool(store.has_action_block())
        except Exception:
            journal_blocked = True
        unresolved = bool(sent or journal_blocked or not accounting_known)
        return {
            "status": "unresolved" if unresolved else "blocked",
            "reason": f"{type(exc).__name__}:{exc}",
            "transport_calls": sent,
            "action_key": action_key,
            "journal_status": None,
            "successor_capture": None,
            "successor_observation": None,
            "effect_reconciliation_required": unresolved,
            "identical_retry_denied": unresolved,
        }


def _execute_navigation(
    context: Any,
    *,
    source_capture: Any,
    target_identity: str,
    target_roi: tuple[int, int, int, int],
    semantic_action: str,
    postcondition: str,
    bind_target: Callable[[Any], tuple[int, int, int, int] | None],
    recognize_successor: Callable[[Any], bool],
) -> dict[str, Any]:
    from scripts import nano_material_production_bluestacks as production

    if not production._safe_nav_roi(target_roi):
        return {"status": "blocked", "reason": "navigation_target_outside_safe_region", "transport_calls": 0}
    runtime, session, store = context.runtime, context.session, context.action_store
    key = f"{PRODUCT_ID}:{semantic_action}:{context.invocation_id}:{source_capture.sha256}"
    request = PolicyRequest(
        action_id=f"nanoweapon-navigation:{hashlib.sha256(key.encode()).hexdigest()[:24]}",
        action_key=key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action=semantic_action,
        expected_runtime_profile_id=PROFILE_ID,
        observation=_frame_observation(
            context,
            source_capture,
            source_state="NANOWEAPON",
            target_identity=target_identity,
            target_roi=target_roi,
            control_class="GO",
            consequence="navigate_zero_cost",
            postcondition=postcondition,
        ),
        monotonic_now=float(context.monotonic_clock()),
        observation_max_age_seconds=2.0,
        dispatch_max_age_seconds=2.0,
        lease_owner=session.owner,
        lease_valid=store.lease_valid_for(session.owner, float(context.utc_clock())),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(key),
        game_day_id=str(context.identity.reset_id),
        action_class=ActionClass.NAVIGATION_ONLY,
        action_kind=semantic_action,
        subject=target_identity,
        resource_or_currency="none",
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(),
        semantic_postconditions=(postcondition,),
        runtime_session_id=str(runtime.session),
    )
    policy = CentralPolicy(frozenset({FLOW_ID}))

    successors: list[tuple[Any, bool]] = []
    current_target = {"roi": target_roi}

    def classify(captured: Any) -> bool:
        verified = bool(recognize_successor(captured))
        successors.append((captured, verified))
        return verified

    immediate_observation = None

    def recapture() -> Observation:
        nonlocal immediate_observation
        if immediate_observation is not None:
            return immediate_observation
        context.checkpoint()
        context.validate_identity()
        fresh = runtime.capture(f"nanoweapon-{semantic_action}-pre-dispatch")
        roi = bind_target(fresh)
        if not production._safe_nav_roi(roi) or tuple(roi) != tuple(target_roi):
            raise ValueError("navigation target could not be rebound from a fresh OCR frame")
        current_target["roi"] = tuple(roi)
        immediate_observation = _frame_observation(
            context,
            fresh,
            source_state="NANOWEAPON",
            target_identity=target_identity,
            target_roi=tuple(roi),
            control_class="GO",
            consequence="navigate_zero_cost",
            postcondition=postcondition,
        )
        return immediate_observation

    try:
        capability_observation = recapture()
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"{type(exc).__name__}:{exc}",
            "transport_calls": 0,
            "action_key": key,
        }
    issue_time = float(context.utc_clock())
    capability_request = replace(
        request,
        observation=capability_observation,
        monotonic_now=float(context.monotonic_clock()),
        lease_owner=session.owner,
        lease_valid=store.lease_valid_for(session.owner, issue_time),
        unresolved_action=store.has_action_block(),
        duplicate_action_key=store.action_key_exists(key),
        policy_phase="pre_dispatch",
    )
    issued = policy.issue_capability(capability_request)
    store.audit(FLOW_ID, "capability_issued", issue_time, issued.audit, request.action_id)
    if not issued.authorized or issued.capability is None:
        return {
            "status": "blocked",
            "reason": issued.reason_code,
            "transport_calls": 0,
            "action_key": key,
        }
    def transport(_intent: Any) -> TransportResult:
        starting = int(runtime.input_count)

        def authorize(before: Any) -> None:
            roi = bind_target(before)
            if not production._safe_nav_roi(roi) or tuple(roi) != tuple(current_target["roi"]):
                raise RuntimeError("Nanoweapon navigation selector changed before dispatch")
            context.checkpoint()
            context.validate_identity()

        def dispatch(before: Any) -> None:
            context.checkpoint()
            runtime.tap(
                before,
                target_identity=target_identity,
                target_roi=tuple(current_target["roi"]),
                action_key=key,
                action_class="navigation",
                consequential=False,
            )

        def settled():
            time.sleep(float(context.settle_seconds))
            context.checkpoint()
            return runtime.capture(f"nanoweapon-{semantic_action}-settled")

        try:
            session.run_action(
                action_class="navigation",
                label=f"nanoweapon-{semantic_action}",
                capture=runtime.capture,
                authorize=authorize,
                dispatch=dispatch,
                recognize=lambda captured: postcondition if classify(captured) else "unknown",
                settled_successor=settled,
                consequence_class="navigation_only",
            )
        except Exception as exc:
            sent = int(runtime.input_count) - starting
            return TransportResult(sent == 1, f"NANOWEAPON_NAV_{type(exc).__name__}")
        sent = int(runtime.input_count) - starting
        return TransportResult(sent == 1, "NANOWEAPON_NAV_SENT" if sent == 1 else "NANOWEAPON_NAV_NOT_SENT")

    def post_observe():
        for captured, verified in successors:
            yield _frame_observation(
                context,
                captured,
                source_state=postcondition if verified else "UNKNOWN",
                target_identity=target_identity,
                target_roi=tuple(current_target["roi"]),
                control_class="GO",
                consequence="navigate_zero_cost",
                postcondition=postcondition,
            )

    execution = SafeActionExecutor(
        store,
        policy,
        session.owner,
        context.monotonic_clock,
        transport,
        recapture,
        post_observe,
        lambda _intent, observed: bool(
            successors and successors[-1][1] and observed.source_state == postcondition
        ),
        wall_clock=context.utc_clock,
        max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    row = store.get_action_by_key(key)
    final = successors[-1][0] if successors else None
    if final is not None and callable(getattr(runtime, "reconcile", None)):
        runtime.reconcile(
            key,
            "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved",
            final,
            execution.reason,
        )
    confirmed = bool(
        execution.status is ActionStatus.CONFIRMED
        and row is not None
        and row.get("final_status") == ActionStatus.CONFIRMED.value
        and successors
        and successors[-1][1]
    )
    return {
        "status": "confirmed" if confirmed else "unresolved" if execution.transport_calls else "blocked",
        "reason": execution.reason,
        "transport_calls": execution.transport_calls,
        "action_key": key,
        "successor_capture": final,
        "journal_status": row.get("final_status") if row else None,
    }


def _select_craft_tab(context: Any, current: Any, game_day_id: str) -> tuple[Any | None, NanoweaponScreen | None]:
    screen = _recognize_capture(
        context,
        current,
        game_day_id=game_day_id,
        starts_this_reset=0,
        prior_material_production_reconciled=True,
    )
    if not screen.screen_recognized:
        return None, screen
    if screen.observation.selected_tab == CRAFT_WEAPON_TAB:
        return current, screen
    if screen.observation.selected_tab != "MATERIAL_PRODUCTION" or screen.craft_tab_roi is None:
        return None, screen

    def bind(captured: Any) -> tuple[int, int, int, int] | None:
        fresh = _recognize_capture(
            context,
            captured,
            game_day_id=game_day_id,
            starts_this_reset=0,
            prior_material_production_reconciled=True,
        )
        if (
            fresh.screen_recognized
            and fresh.observation.selected_tab == "MATERIAL_PRODUCTION"
            and fresh.craft_tab_roi is not None
        ):
            return fresh.craft_tab_roi
        return None

    def successor(captured: Any) -> bool:
        fresh = _recognize_capture(
            context,
            captured,
            game_day_id=game_day_id,
            starts_this_reset=0,
            prior_material_production_reconciled=True,
            bind_completed_instance=False,
        )
        return bool(fresh.screen_recognized and fresh.observation.selected_tab == CRAFT_WEAPON_TAB)

    navigation = _execute_navigation(
        context,
        source_capture=current,
        target_identity="nanoweapon:craft-weapon-tab",
        target_roi=screen.craft_tab_roi,
        semantic_action="select_normal_craft",
        postcondition="NANOWEAPON_CRAFT_WEAPON_TAB",
        bind_target=bind,
        recognize_successor=successor,
    )
    if navigation.get("status") != "confirmed" or navigation.get("successor_capture") is None:
        return None, None
    captured = navigation["successor_capture"]
    fresh_screen = _recognize_capture(
        context,
        captured,
        game_day_id=game_day_id,
        starts_this_reset=0,
        prior_material_production_reconciled=True,
    )
    if not fresh_screen.screen_recognized or fresh_screen.observation.selected_tab != CRAFT_WEAPON_TAB:
        return None, fresh_screen
    return captured, fresh_screen

def _return_home(context: Any, *, occurrence_key: str, current: Any) -> tuple[Any | None, dict[str, Any] | None]:
    from scripts import nano_material_production_bluestacks as production

    fresh = production._capture(context, "nanoweapon-return-home-source")
    if fresh.captured_monotonic <= current.captured_monotonic:
        return None, None
    home, captured = production._return_home(context, occurrence_key=occurrence_key, current=fresh)
    if not home or captured is None or not _safe_home(context, captured.frame):
        return None, None
    try:
        frame, reference = context.capture_reference(captured.path, captured.sha256)
    except Exception:
        return None, None
    if not _safe_home(context, frame.frame):
        return None, None
    proof = {
        "terminal_home_state": "HOME_BASE",
        "terminal_home_recognized": True,
        "terminal_home_frame": {
            "frame_path": reference.frame_path,
            "frame_sha256": reference.frame_sha256,
            "observed_utc": reference.observed_utc,
            "capture_ordinal": reference.capture_ordinal,
        },
        "terminal_home_frame_path": str(captured.path),
        "terminal_home_frame_sha256": str(captured.sha256),
        "terminal_home_verified": True,
    }
    return captured, proof


def _empty_result(context: Any, *, occurrence_key: str, production_calls: int = 0, craft_calls: int = 0) -> dict[str, Any]:
    return {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "native_occurrence_key": occurrence_key,
        "occurrence_key": occurrence_key,
        "status": "blocked",
        "production_transport_calls": production_calls,
        "craft_transport_calls": craft_calls,
        "craft_claim_transport_calls": 0,
        "craft_start_transport_calls": 0,
        "nanoweapon_dispatch_count": production_calls + craft_calls,
        "attempted_action_count": production_calls + craft_calls,
        "attempted_action_count_known": True,
        "committed_action_count": 0,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "accounting_verified": False,
        "terminal_home_verified": False,
        "prior_material_production_reconciled": False,
        "zero_resource_cost_confirmed": False,
        "next_eligible_at": None,
        "due_reason": None,
    }


def _finalize(context: Any, result: dict[str, Any], *, current: Any, occurrence_key: str) -> Mapping[str, object]:
    terminal, proof = _return_home(context, occurrence_key=occurrence_key, current=current) if current is not None else (None, None)
    if proof is not None:
        result.update(proof)
    else:
        result.update(terminal_home_verified=False, terminal_home_recognized=False)
    accounting = context.accounting()
    session_count = getattr(context.session, "input_count", None)
    runtime_count = getattr(context.runtime, "input_count", None)
    accounting_verified = bool(
        getattr(accounting, "verified", False)
        and type(session_count) is int
        and type(runtime_count) is int
        and session_count == runtime_count == getattr(accounting, "input_count", None)
        and session_count <= MAX_INPUTS
    )
    result.update(
        accounting_verified=accounting_verified,
        input_count=int(session_count) if type(session_count) is int else 0,
        session_input_count=int(session_count) if type(session_count) is int else 0,
        runtime_input_count=int(runtime_count) if type(runtime_count) is int else 0,
    )
    production_calls = result.get("production_transport_calls")
    craft_calls = result.get("craft_transport_calls")
    claim_calls = result.get("craft_claim_transport_calls")
    start_calls = result.get("craft_start_transport_calls")
    attempted_known = bool(
        result.get("attempted_action_count_known") is True
        and type(production_calls) is int
        and 0 <= production_calls <= 2
        and type(craft_calls) is int
        and 0 <= craft_calls <= 2
        and type(claim_calls) is int
        and claim_calls in (0, 1)
        and type(start_calls) is int
        and start_calls in (0, 1)
        and claim_calls + start_calls == craft_calls
        and production_calls + craft_calls <= MAX_ACTIONS
    )
    attempted = production_calls + craft_calls if attempted_known else None
    result["attempted_action_count"] = attempted
    result["nanoweapon_dispatch_count"] = attempted
    committed = result.get("committed_action_count")
    committed_known = bool(
        type(committed) is int
        and 0 <= committed <= MAX_ACTIONS
        and (not attempted_known or committed <= attempted)
    )
    if not committed_known:
        result["committed_action_count"] = None
    effect_unresolved = bool(
        not accounting_verified
        or not attempted_known
        or not committed_known
        or (attempted_known and committed != attempted)
        or result.get("effect_reconciliation_required")
        or result.get("identical_retry_denied")
    )
    home_unresolved = bool(
        not result.get("terminal_home_verified")
        and (not attempted_known or (attempted is not None and attempted > 0))
    )
    unresolved = bool(effect_unresolved or home_unresolved)
    if unresolved:
        result.update(effect_reconciliation_required=True, identical_retry_denied=True)
    if not accounting_verified:
        result.update(status="unresolved", reason="native_input_accounting_mismatch")
    elif not result.get("terminal_home_verified"):
        result.update(
            status="unresolved" if unresolved else "blocked",
            reason="canonical_home_successor_not_verified",
        )
    elif unresolved:
        result.update(
            status="unresolved",
            reason=result.get("reason") or "native_action_effect_unresolved",
        )
    if terminal is not None:
        result["terminal_home_capture"] = str(terminal.path)
    return result


def run_nanoweapon_in_context(
    context: Any,
    *,
    occurrence_key: str,
    observation_interval_seconds: int = DEFAULT_OBSERVATION_INTERVAL_SECONDS,
) -> Mapping[str, object]:
    """Run production maintenance first, then at most one confirmed Normal Craft start."""
    if (
        type(occurrence_key) is not str
        or not occurrence_key.strip()
        or occurrence_key != occurrence_key.strip()
        or occurrence_key != getattr(context, "occurrence_key", None)
    ):
        raise ValueError("Nanoweapon requires the exact borrowed native occurrence key")
    if context.runtime_profile_id != PROFILE_ID:
        raise ValueError("Nanoweapon native context profile is not canonical")
    if type(observation_interval_seconds) is not int or observation_interval_seconds != DEFAULT_OBSERVATION_INTERVAL_SECONDS:
        raise ValueError("Nanoweapon observation interval must remain exactly 300 seconds")
    context.checkpoint()
    context.validate_identity()
    identity = context.identity
    game_day_id = getattr(identity, "reset_id", None)
    if type(game_day_id) is not str or not game_day_id or game_day_id != game_day_id.strip():
        raise ValueError("Nanoweapon current game-day/reset identity is missing or malformed")

    result = _empty_result(context, occurrence_key=occurrence_key)
    current = None
    production_result: Mapping[str, object] = {}
    try:
        # This is deliberately the first route operation: production performs the canonical
        # Home -> Gear Factory -> Nanoweapon visit and remains on that screen for Craft Weapon.
        from scripts.nano_material_production_bluestacks import run_material_production_in_context
        production_result = run_material_production_in_context(
            context,
            occurrence_key=context.occurrence_key,
            return_home=False,
        )
        production_calls = production_result.get("production_transport_calls")
        production_calls_known = type(production_calls) is int and 0 <= production_calls <= 2
        production_committed = production_result.get("committed_action_count")
        production_committed_known = bool(
            type(production_committed) is int
            and 0 <= production_committed <= MAX_ACTIONS
            and (not production_calls_known or production_committed <= production_calls)
        )
        result["committed_action_count"] = (
            production_committed if production_committed_known else None
        )
        result["effect_reconciliation_required"] = bool(
            production_result.get("effect_reconciliation_required")
        )
        result["identical_retry_denied"] = bool(production_result.get("identical_retry_denied"))
        if not production_calls_known:
            result.update(
                attempted_action_count_known=False,
                production_transport_calls=None,
                effect_reconciliation_required=True,
                identical_retry_denied=True,
            )
            raise ValueError("same-visit production transport count is invalid")
        result["production_transport_calls"] = production_calls
        if not production_committed_known:
            result.update(effect_reconciliation_required=True, identical_retry_denied=True)
            raise ValueError("same-visit production committed count is invalid")
        state_frame = production_result.get("production_state_frame")
        state_sha256 = production_result.get("production_state_observation_sha256")
        state_frame_confirmed = bool(
            isinstance(state_frame, Mapping)
            and type(state_frame.get("frame_path")) is str
            and bool(state_frame.get("frame_path"))
            and type(state_frame.get("frame_sha256")) is str
            and _SHA256_RE.fullmatch(state_frame["frame_sha256"])
            and state_frame["frame_sha256"] == state_sha256
            and type(state_frame.get("observed_utc")) is str
            and bool(state_frame.get("observed_utc"))
            and type(state_frame.get("capture_ordinal")) is int
            and state_frame["capture_ordinal"] > 0
            and production_result.get("production_occurrence_key") == occurrence_key
            and production_result.get("production_target_identity") == NANO_MATERIAL_PRODUCTION_TARGET
        )
        production_confirmed = bool(
            state_frame_confirmed
            and production_result.get("status") in {"completed", "deferred"}
            and production_result.get("native_occurrence_key") == occurrence_key
            and production_result.get("occurrence_key") == occurrence_key
            and production_result.get("production_state") == "active"
            and type(production_result.get("active_production_count")) is int
            and production_result.get("active_production_count") == 1
            and type(production_result.get("production_duration_seconds")) is int
            and production_result.get("production_duration_seconds") == 21600
            and type(production_result.get("timer_seconds_remaining")) is int
            and 0 < production_result["timer_seconds_remaining"] <= 21600
            and type(production_result.get("next_eligible_at")) in (int, float)
            and math.isfinite(production_result["next_eligible_at"])
            and production_result["next_eligible_at"] > 0
            and production_result.get("zero_resource_cost_confirmed") is True
            and production_result.get("effect_reconciliation_required") is False
            and production_result.get("identical_retry_denied") is False
            and type(production_result.get("committed_action_count")) is int
            and production_result.get("committed_action_count") == production_calls
            and production_result.get("accounting_verified") is True
        )
        if not production_confirmed:
            raise ValueError("same-visit Nano Material Production result is not confirmed active zero-cost state")
        result["committed_action_count"] = production_result["committed_action_count"]
        result.update(
            prior_material_production_reconciled=True,
            zero_resource_cost_confirmed=True,
            production_state="active",
            production_active_count=1,
            production_duration_seconds=21600,
            production_timer_seconds_remaining=production_result["timer_seconds_remaining"],
            production_next_eligible_at=production_result.get("next_eligible_at"),
            production_occurrence_key=production_result["production_occurrence_key"],
            production_target_identity=production_result["production_target_identity"],
            production_state_frame=state_frame,
            production_state_observation_sha256=state_sha256,
        )
        current = context.session.observe(context.runtime.capture, label="nanoweapon-after-production")
        reset_key = _action_key("start", reset_id=game_day_id, identity=identity)
        current_start_record = context.action_store.get_action_by_key(reset_key)
        start_confirmed = _confirmed_start_record(
            current_start_record,
            action_key=reset_key,
            game_day_id=game_day_id,
        )
        start_reset_id = game_day_id if start_confirmed else None
        start_state = 1 if start_confirmed else 0
        current_screen = _recognize_capture(
            context,
            current,
            game_day_id=game_day_id,
            starts_this_reset=start_state,
            start_reset_id=start_reset_id,
            prior_material_production_reconciled=True,
        )
        if not current_screen.screen_recognized:
            raise ValueError("post-production Nanoweapon screen is not positively recognized")
        if current_screen.observation.selected_tab != CRAFT_WEAPON_TAB:
            current, current_screen = _select_craft_tab(context, current, game_day_id)
            if current is None or current_screen is None:
                raise ValueError("Normal Craft tab is not positively selected after production")
        current = context.session.observe(context.runtime.capture, label="nanoweapon-normal-craft-immediate")
        current_screen = _recognize_capture(
            context,
            current,
            game_day_id=game_day_id,
            starts_this_reset=start_state,
            start_reset_id=start_reset_id,
            prior_material_production_reconciled=True,
        )
        observation = current_screen.observation
        if not current_screen.screen_recognized or observation.selected_tab != CRAFT_WEAPON_TAB:
            raise ValueError("Normal Craft screen selector is unknown")

        craft_claim_calls = 0
        craft_start_calls = 0
        claim_result_identity = observation.result_identity
        if observation.claim_visible:
            if not nanoweapon_claim_authorizeable(observation):
                raise ValueError("completed Normal Craft Claim is not positively recognized")
            bound_instance, claim_key = _completed_craft_binding(context)
            if bound_instance != claim_result_identity:
                raise ValueError("completed Normal Craft durable instance changed")
            claim = _execute_consequential(
                context,
                before_capture=current,
                before=observation,
                action_key=claim_key,
                action_kind="CLAIM_NANOWEAPON_COMPLETED",
                monotonic_clock=context.monotonic_clock,
                wall_clock=context.utc_clock,
            )
            raw_claim_calls = claim.get("transport_calls")
            if claim.get("status") == "confirmed" and claim.get("successor_observation") is not None:
                result["committed_action_count"] += 1
            if type(raw_claim_calls) is not int or not 0 <= raw_claim_calls <= 1:
                result.update(
                    attempted_action_count_known=False,
                    craft_claim_transport_calls=None,
                    craft_transport_calls=None,
                    effect_reconciliation_required=True,
                    identical_retry_denied=True,
                )
                raise ValueError("completed Normal Craft Claim attempt count is unknown")
            craft_claim_calls = raw_claim_calls
            result["craft_claim_transport_calls"] = craft_claim_calls
            result["craft_transport_calls"] = craft_claim_calls
            result["effect_reconciliation_required"] = bool(claim.get("effect_reconciliation_required"))
            result["identical_retry_denied"] = bool(claim.get("identical_retry_denied"))
            if claim.get("status") != "confirmed" or claim.get("successor_observation") is None:
                raise ValueError(str(claim.get("reason") or "completed Normal Craft Claim successor unknown"))
            if craft_claim_calls != 1:
                result.update(effect_reconciliation_required=True, identical_retry_denied=True)
                raise ValueError("completed Normal Craft Claim was confirmed without one accounted input")
            current = context.session.observe(context.runtime.capture, label="nanoweapon-after-claim")
            current_screen = _recognize_capture(
                context,
                current,
                game_day_id=game_day_id,
                starts_this_reset=start_state,
                start_reset_id=start_reset_id,
                prior_material_production_reconciled=True,
            )
            observation = current_screen.observation
            if not current_screen.screen_recognized or observation.selected_tab != CRAFT_WEAPON_TAB:
                raise ValueError("Normal Craft claim successor is not a recognized same-screen state")

        previous_day = _previous_reset_id(game_day_id)
        previous_key = (
            _action_key("start", reset_id=previous_day, identity=identity)
            if previous_day is not None else None
        )
        previous_start_record = context.action_store.get_action_by_key(previous_key) if previous_key else None
        previous_start_confirmed = bool(
            previous_key is not None
            and previous_day is not None
            and _confirmed_start_record(
                previous_start_record,
                action_key=previous_key,
                game_day_id=previous_day,
            )
        )
        start_reset_id = game_day_id if start_confirmed else previous_day if previous_start_confirmed else None
        starts_this_reset = 1 if start_confirmed else 0
        observation = replace(
            observation,
            starts_this_reset=starts_this_reset,
            game_day_id=game_day_id,
            prior_material_production_reconciled=True,
            craft_duration_seconds=(NORMAL_CRAFT_DURATION_SECONDS if start_confirmed or previous_start_confirmed else observation.craft_duration_seconds),
            duration_policy_approved=(True if start_confirmed or previous_start_confirmed else observation.duration_policy_approved),
            craft_timer_seconds_remaining=observation.craft_timer_seconds_remaining,
        )
        if observation.claim_visible:
            raise ValueError("completed Normal Craft remains visible after its one allowed claim")

        start_succeeded_now = False
        precraft_balance: int | None = None
        if nanoweapon_active_craft_authorizeable(observation):
            if observation.starts_this_reset == 1 and start_confirmed:
                due_reason = "current_reset_start"
            elif observation.starts_this_reset == 0 and previous_start_confirmed:
                due_reason = "previous_reset_active_timer"
            else:
                raise ValueError("active Normal Craft start reset cannot be bound to the canonical journal")
        elif nanoweapon_current_reset_start_known(observation):
            due_reason = "current_reset_start"
        elif nanoweapon_known_material_shortage(observation):
            due_reason = "known_material_shortage"
        elif nanoweapon_authorizeable(observation):
            if context.action_store.get_action_by_key(reset_key) is not None:
                result.update(effect_reconciliation_required=True, identical_retry_denied=True)
                raise ValueError("current-reset Normal Craft key already exists; duplicate start denied")
            precraft_balance = observation.nano_parts
            prestart_observation = observation
            craft_key = reset_key
            start = _execute_consequential(
                context,
                before_capture=current,
                before=observation,
                action_key=craft_key,
                action_kind="START_NORMAL_NANOWEAPON_CRAFT",
                monotonic_clock=context.monotonic_clock,
                wall_clock=context.utc_clock,
            )
            raw_start_calls = start.get("transport_calls")
            if start.get("status") == "confirmed" and start.get("successor_observation") is not None:
                result["committed_action_count"] += 1
            if type(raw_start_calls) is not int or not 0 <= raw_start_calls <= 1:
                result.update(
                    attempted_action_count_known=False,
                    craft_start_transport_calls=None,
                    craft_transport_calls=None,
                    effect_reconciliation_required=True,
                    identical_retry_denied=True,
                )
                raise ValueError("Normal Craft start attempt count is unknown")
            craft_start_calls = raw_start_calls
            result["craft_start_transport_calls"] = craft_start_calls
            result["craft_transport_calls"] = craft_claim_calls + craft_start_calls
            result["effect_reconciliation_required"] = bool(start.get("effect_reconciliation_required"))
            result["identical_retry_denied"] = bool(start.get("identical_retry_denied"))
            if start.get("status") != "confirmed" or start.get("successor_observation") is None:
                raise ValueError(str(start.get("reason") or "Normal Craft successor unknown"))
            if craft_start_calls != 1:
                result.update(effect_reconciliation_required=True, identical_retry_denied=True)
                raise ValueError("Normal Craft start was confirmed without one accounted input")
            current = context.session.observe(context.runtime.capture, label="nanoweapon-after-start")
            current_screen = _recognize_capture(
                context,
                current,
                game_day_id=game_day_id,
                starts_this_reset=1,
                start_reset_id=game_day_id,
                prior_material_production_reconciled=True,
            )
            observation = current_screen.observation
            if not nanoweapon_postcondition_verified(prestart_observation, observation):
                raise ValueError("Normal Craft active timer is not positively confirmed in the current frame")
            start_confirmed = True
            start_reset_id = game_day_id
            start_succeeded_now = True
            due_reason = "current_reset_start"
        else:
            raise ValueError("Normal Craft state is unknown; no due time is permitted")

        if start_confirmed and start_reset_id == game_day_id:
            due = (math.floor(float(context.utc_clock()) / 86400.0) + 1) * 86400.0
            if nanoweapon_active_craft_authorizeable(observation):
                due = min(
                    due,
                    nanoweapon_active_craft_due_at(
                        float(context.utc_clock()),
                        observation.craft_timer_seconds_remaining,
                    ),
                )
            due_reason = "current_reset_start"
        elif (
            start_reset_id is not None
            and start_reset_id != game_day_id
            and nanoweapon_active_craft_authorizeable(observation)
        ):
            due = nanoweapon_active_craft_due_at(float(context.utc_clock()), observation.craft_timer_seconds_remaining)
            due_reason = "previous_reset_active_timer"
        elif nanoweapon_known_material_shortage(observation):
            due = nanoweapon_shortage_due_at(float(context.utc_clock()), observation_interval_seconds)
            due_reason = "known_material_shortage"
        else:
            raise ValueError("Nanoweapon due-time state is unknown")
        production_due = result.get("production_next_eligible_at")
        if (
            type(production_due) not in (int, float)
            or not math.isfinite(production_due)
            or production_due < 0
        ):
            raise ValueError("same-visit production due time is not positively recognized")
        due = min(due, float(production_due))

        craft_active = observation.active_craft_count == 1 and observation.craft_timer_active is True
        craft_state = "active" if craft_active else "idle"
        current_balance = observation.nano_parts
        if type(current_balance) is not int:
            raise ValueError("current NANO_PARTS balance is unknown")
        if start_succeeded_now and (precraft_balance is None or precraft_balance - current_balance != NANO_PARTS_REQUIRED):
            raise ValueError("Normal Craft NANO_PARTS consumption is not exactly 100")
        result.update(
            status="completed" if start_succeeded_now else "deferred",
            reason="NORMAL_CRAFT_STARTED_FOR_RESET" if start_succeeded_now else due_reason.upper(),
            craft_state=craft_state,
            craft_active_count=1 if craft_active else 0,
            craft_duration_seconds=NORMAL_CRAFT_DURATION_SECONDS,
            active_craft_timer_seconds_remaining=observation.craft_timer_seconds_remaining if craft_active else 0,
            starts_this_reset=1 if start_confirmed else 0,
            craft_start_confirmed=bool(start_confirmed or previous_start_confirmed),
            craft_start_reset_id=start_reset_id,
            game_day_id=game_day_id,
            nano_parts_balance=current_balance,
            precraft_nano_parts_balance=precraft_balance if start_succeeded_now else None,
            craft_start_transport_calls=craft_start_calls,
            craft_claim_transport_calls=craft_claim_calls,
            craft_transport_calls=craft_claim_calls + craft_start_calls,
            due_reason=due_reason,
            next_eligible_at=due,
            observation_interval_seconds=observation_interval_seconds,
            effect_reconciliation_required=False,
            identical_retry_denied=False,
        )
    except Exception as exc:
        production_calls = result.get("production_transport_calls")
        craft_calls = result.get("craft_transport_calls")
        attempts_known = bool(
            result.get("attempted_action_count_known") is True
            and type(production_calls) is int
            and 0 <= production_calls <= 2
            and type(craft_calls) is int
            and 0 <= craft_calls <= 2
            and production_calls + craft_calls <= MAX_ACTIONS
        )
        dispatch_count = production_calls + craft_calls if attempts_known else None
        result["attempted_action_count"] = dispatch_count
        result["nanoweapon_dispatch_count"] = dispatch_count
        committed = result.get("committed_action_count")
        journal_blocked = bool(context.action_store.has_action_block())
        unresolved = bool(
            not attempts_known
            or (dispatch_count is not None and committed != dispatch_count)
            or journal_blocked
            or result.get("effect_reconciliation_required")
            or result.get("identical_retry_denied")
            or type(committed) is not int
        )
        result.update(
            status="unresolved" if unresolved else "blocked",
            reason=f"{type(exc).__name__}:{exc}",
            effect_reconciliation_required=bool(result.get("effect_reconciliation_required") or unresolved),
            identical_retry_denied=bool(result.get("identical_retry_denied") or unresolved),
        )
        if current is None:
            try:
                current = context.session.observe(
                    context.runtime.capture,
                    label="nanoweapon-safe-terminal-source",
                )
            except Exception:
                current = None
    return _finalize(context, result, current=current, occurrence_key=occurrence_key)


def _service_driver(context: Any, arguments: Mapping[str, object]) -> Mapping[str, Any]:
    if (
        context.flow_id != FLOW_ID
        or context.product_id != PRODUCT_ID
        or context.product_revision != PRODUCT_REVISION
        or context.runtime_profile_id != PROFILE_ID
    ):
        raise ValueError("Nanoweapon native context binding mismatch")
    if not isinstance(arguments, Mapping):
        raise ValueError("Nanoweapon native arguments must be a mapping")
    interval = arguments.get("observation_interval_seconds", DEFAULT_OBSERVATION_INTERVAL_SECONDS)
    return run_nanoweapon_in_context(
        context,
        occurrence_key=context.occurrence_key,
        observation_interval_seconds=interval,
    )


def create_service_binding(make_native_route_binding: Callable[..., Any]) -> Any:
    """Bind this route to the one canonical native owner and already-leased SafetyStore."""
    if not callable(make_native_route_binding):
        raise TypeError("Nanoweapon requires the controller's native route binding builder")
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:nanoweapon",
        workflow="nanoweapon-native",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=_service_driver,
        validator=None,
        action_store_factory=lambda path: SafetyStore(path),
    )
