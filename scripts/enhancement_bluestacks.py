#!/usr/bin/env python3
"""Evidence-gated native BlueStacks Daily enhancement route.

The route starts from a selected Daily enhancement row.  It uses OCR only as
spatially associated evidence, binds every UI target from the current frame,
and never treats an unknown or ambiguous frame as authorization.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
    NativeBox,
)
from tasks.daily_enhancement import (
    DailyEnhancementObservation,
    daily_enhancement_bluestacks_postcondition_verified,
)
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
    EnhancementObservation,
    SUPPORTED_VARIANTS,
    enhancement_bluestacks_authorizeable,
    enhancement_bluestacks_postcondition_verified,
)


NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
NATIVE_PROFILE_ID = BLUESTACKS_RUNTIME_PROFILE_ID
FULL_FRAME: NativeBox = (0, 0, NATIVE_WIDTH, NATIVE_HEIGHT)
# These are semantic search bounds only.  Dispatch boxes are always measured
# from a current OCR hit and are never taken from these constants.
DAILY_SEARCH_ROI: NativeBox = FULL_FRAME
COMMANDER_HEADER_ROI: NativeBox = (0, 0, 800, 220)
CATEGORY_SEARCH_ROI: NativeBox = (0, 120, 800, 390)
ITEM_SEARCH_ROI: NativeBox = (0, 210, 800, 820)
MATERIAL_SEARCH_ROI: NativeBox = (0, 620, 800, 1140)
CONTROL_SEARCH_ROI: NativeBox = (0, 760, 800, 1260)
# Compatibility names are search bounds only; callers must still bind current
# OCR geometry before dispatch.
CATEGORY_ROI = CATEGORY_SEARCH_ROI
ITEM_ROI = ITEM_SEARCH_ROI
MATERIAL_ROI = MATERIAL_SEARCH_ROI
CONTROL_ROI = CONTROL_SEARCH_ROI
MAX_SETTLE_POLLS = 3
FORBIDDEN_ACTIONS = frozenset({"promote", "modify", "replace", "unequip"})
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
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        return None
    return candidate  # type: ignore[return-value]


def _expand(value: NativeBox, x_pad: int = 30, y_pad: int = 20) -> NativeBox:
    x0, y0, x1, y1 = value
    return (
        max(0, x0 - x_pad),
        max(0, y0 - y_pad),
        min(800, x1 + x_pad),
        min(1280, y1 + y_pad),
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
    enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(
        enlarged, config="--psm 11", output_type=Output.DICT
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
            continue
        if not isinstance(value, Mapping):
            continue
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


def _is_marker(hit: OcrHit) -> bool:
    text = _normalize(hit.text)
    return (
        text in {"selected", "active", "checked", "check", "current"}
        or "selected" in text
    )


def _target(hits: Sequence[OcrHit], names: set[str]) -> NativeBox | None:
    matches = [hit for hit in hits if _normalize(hit.text) in names]
    return _expand(matches[0].bounds) if len(matches) == 1 else None


def _frame_hash(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("native frame could not be encoded")
    return hashlib.sha256(encoded.tobytes()).hexdigest()


@dataclass(frozen=True)
class DailyRecognition:
    recognized: bool
    reason: str
    frame_sha256: str
    objective_key: str = ""
    progress: tuple[int, int] | None = None
    selected: bool = False
    go_target: NativeBox | None = None


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
    diagnostics: Mapping[str, Any] = ()


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
            if identity == "enhancement-confirm":
                return target
        return None


def _daily_progress(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b([01])\s*(?:/|of)\s*([01])\b", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def recognize_daily_frame(
    frame: np.ndarray,
    *,
    variant: str,
    source_frame_sha256: str | None = None,
    ocr_engine: OcrEngine | None = None,
    completed: bool = False,
) -> DailyRecognition:
    digest = (
        source_frame_sha256
        if _SHA256_RE.fullmatch(str(source_frame_sha256 or ""))
        else _frame_hash(frame)
    )
    if frame is None or frame.shape[:2] != (1280, 800):
        return DailyRecognition(False, "NON_NATIVE_FRAME", digest)
    if variant not in SUPPORTED_VARIANTS:
        return DailyRecognition(False, "UNSUPPORTED_VARIANT", digest)
    hits = _hits(frame, DAILY_SEARCH_ROI, ocr_engine)
    aliases = {
        f"enhance {variant}",
        f"{variant} enhancement",
        f"enhance {variant} daily",
    }
    objectives = [
        hit for hit in hits if any(alias in _normalize(hit.text) for alias in aliases)
    ]
    if len(objectives) != 1:
        return DailyRecognition(False, "DAILY_OBJECTIVE_AMBIGUOUS", digest)
    objective = objectives[0]
    progress = _daily_progress(_normalize(objective.text))
    if progress is None:
        nearby = " ".join(
            _normalize(hit.text)
            for hit in hits
            if abs(_center(hit.bounds)[1] - _center(objective.bounds)[1]) <= 80
        )
        progress = _daily_progress(nearby)
    expected = (1, 1) if completed else (0, 1)
    if progress != expected:
        return DailyRecognition(
            False, "DAILY_PROGRESS_NOT_EXACT", digest, progress=progress
        )
    markers = [hit for hit in hits if _is_marker(hit)]
    selected = any(_associated(marker, objective) for marker in markers)
    if not selected:
        return DailyRecognition(
            False,
            "DAILY_ROW_NOT_SELECTED",
            digest,
            f"enhance_{variant}",
            progress,
            False,
        )
    go_hits = [
        hit
        for hit in hits
        if _normalize(hit.text) == "go"
        and _associated(hit, objective, y_slack=120, x_slack=600)
    ]
    if not completed and len(go_hits) != 1:
        return DailyRecognition(
            False,
            "DAILY_ROW_LOCAL_GO_NOT_EXACT",
            digest,
            f"enhance_{variant}",
            progress,
            True,
        )
    return DailyRecognition(
        True,
        "DAILY_COMPLETED" if completed else "DAILY_ENTRY_RECOGNIZED",
        digest,
        f"enhance_{variant}",
        progress,
        True,
        _expand(go_hits[0].bounds) if go_hits else None,
    )


def _item_identity(hits: Sequence[OcrHit], variant: str) -> str:
    for hit in hits:
        text = _normalize(hit.text)
        match = re.search(r"(?:item|identity)\s*[:#-]\s*(.+)", text)
        if match:
            return match.group(1).replace(" ", "-")
    candidates = [
        hit
        for hit in hits
        if variant in _normalize(hit.text) and "level" not in _normalize(hit.text)
    ]
    return (
        _normalize(candidates[0].text).replace(" ", "-") if len(candidates) == 1 else ""
    )


def _level(text: str) -> int | None:
    match = re.search(r"\b(?:level|lvl)\s*[:#-]?\s*(\d{1,3})\b", text)
    return int(match.group(1)) if match else None


def _star(text: str) -> int | None:
    values = [int(value) for value in re.findall(r"\b([1-9])\s*[- ]?star\b", text)]
    for word, number in (
        ("one", 1),
        ("two", 2),
        ("three", 3),
        ("four", 4),
        ("five", 5),
    ):
        if f"{word} star" in text:
            values.append(number)
    return values[0] if len(set(values)) == 1 else None


def _quantity(text: str) -> int | None:
    values = [
        int(value)
        for pattern in (
            r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*(\d+)\b",
            r"\bx\s*(\d+)\b",
        )
        for value in re.findall(pattern, text)
    ]
    return values[0] if len(set(values)) == 1 else None


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
    digest = (
        source_frame_sha256
        if _SHA256_RE.fullmatch(str(source_frame_sha256 or ""))
        else _frame_hash(frame)
    )
    if frame is None or frame.shape[:2] != (1280, 800):
        return StageRecognition(stage, False, "NON_NATIVE_FRAME", digest)
    if variant not in SUPPORTED_VARIANTS:
        return StageRecognition(stage, False, "UNSUPPORTED_VARIANT", digest)
    header = _hits(frame, COMMANDER_HEADER_ROI, ocr_engine)
    categories = _hits(frame, CATEGORY_SEARCH_ROI, ocr_engine)
    items = _hits(frame, ITEM_SEARCH_ROI, ocr_engine)
    materials = _hits(frame, MATERIAL_SEARCH_ROI, ocr_engine)
    controls = _hits(frame, CONTROL_SEARCH_ROI, ocr_engine)
    header_text, category_text = _text(header), _text(categories)
    if "commander info" not in header_text and "commanderinfo" not in header_text:
        return StageRecognition(stage, False, "COMMANDER_INFO_NOT_RECOGNIZED", digest)
    category_hits = [
        hit
        for hit in categories
        if _center(hit.bounds)[1] < 260
        if any(
            re.search(rf"\b{re.escape(name)}\b", _normalize(hit.text))
            for name in SUPPORTED_VARIANTS
        )
    ]
    requested = [
        hit
        for hit in category_hits
        if re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    conflicting = [
        hit
        for hit in category_hits
        if not re.search(rf"\b{re.escape(variant)}\b", _normalize(hit.text))
    ]
    if (
        len(requested) != 1
        or conflicting
        and any(
            "selected" in _normalize(hit.text) or "active" in _normalize(hit.text)
            for hit in conflicting
        )
    ):
        return StageRecognition(stage, False, "CATEGORY_CONFLICT", digest)
    if len(requested) != 1:
        return StageRecognition(stage, False, "CATEGORY_LABEL_MISSING", digest)
    category_markers = [
        hit for hit in categories if _is_marker(hit) and _associated(hit, requested[0])
    ]
    category_selected = len(category_markers) == 1
    category_target = _expand(requested[0].bounds)
    item_text = _text(items)
    item_labels = [name for name in SUPPORTED_VARIANTS if name in item_text]
    if any(name != variant for name in item_labels):
        return StageRecognition(stage, False, "ITEM_CATEGORY_CONFLICT", digest)
    identity = _item_identity(items, variant)
    equipped = any(
        _normalize(hit.text) == "equipped"
        and _associated(hit, requested[0], y_slack=500)
        for hit in items
    )
    item_level = _level(item_text)
    if not identity or not equipped or item_level is None:
        return StageRecognition(stage, False, "EQUIPPED_ITEM_NOT_PROVEN", digest)
    item_hits = [
        hit
        for hit in items
        if (
            identity.replace("-", " ") in _normalize(hit.text)
            or "item" in _normalize(hit.text)
        )
        and not any(
            word in _normalize(hit.text) for word in ("result", "enhanced", "success")
        )
    ]
    item_target = _expand(item_hits[0].bounds) if len(item_hits) == 1 else None
    forbidden = sorted(
        action for action in FORBIDDEN_ACTIONS if action in _text(controls)
    )
    if forbidden:
        return StageRecognition(
            stage,
            False,
            "FORBIDDEN_ACTION_MODE",
            digest,
            diagnostics={"actions": forbidden},
        )
    if any(
        marker
        in " ".join(
            (header_text, category_text, item_text, _text(materials), _text(controls))
        )
        for marker in PREMIUM_MARKERS
    ):
        return StageRecognition(stage, False, "PREMIUM_CURRENCY_FORBIDDEN", digest)

    if stage == "item":
        open_target = _target(controls, {"enhance"})
        if open_target is None:
            return StageRecognition(stage, False, "OPEN_ENHANCE_NOT_RECOGNIZED", digest)
        return StageRecognition(
            stage,
            True,
            "COMMANDER_INFO_ITEM_RECOGNIZED",
            digest,
            identity,
            category_selected,
            category_target,
            item_target,
            open_target,
        )

    material_text = _text(materials)
    material_hits = [
        hit
        for hit in materials
        if "material" in _normalize(hit.text) and variant in _normalize(hit.text)
    ]
    if len(material_hits) != 1 and stage != "post":
        return StageRecognition(
            stage,
            False,
            "CATEGORY_MATERIAL_NOT_UNIQUE",
            digest,
            identity,
            category_selected,
            category_target,
            item_target,
        )
    material_hit = material_hits[0] if material_hits else None
    material_identity = (
        _normalize(material_hit.text).replace(" ", "-") if material_hit else ""
    )
    markers = [hit for hit in materials if _is_marker(hit)]
    material_selected = bool(
        material_hit and any(_associated(marker, material_hit) for marker in markers)
    )
    material_target = _expand(material_hit.bounds) if material_hit else None
    quantity = _quantity(material_text)
    quantity_hits = [
        hit
        for hit in materials
        if re.search(
            r"\b(?:quantity|qty|count|owned|available)\s*[:=]\s*1\b|\bx\s*1\b",
            _normalize(hit.text),
        )
    ]
    quantity_target = (
        _expand(quantity_hits[0].bounds) if len(quantity_hits) == 1 else None
    )
    final_target = _target(controls, {"confirm", "enhance"})
    result_hits = [
        hit
        for hit in items
        if any(
            word in _normalize(hit.text) for word in ("result", "enhanced", "success")
        )
    ]
    result_identity = ""
    for hit in result_hits:
        match = re.search(r"(?:result|item)\s*[:#-]\s*(.+)", _normalize(hit.text))
        if match:
            result_identity = match.group(1).replace(" ", "-")
    if result_identity and result_identity != identity:
        return StageRecognition(stage, False, "RESULT_IDENTITY_CONFLICT", digest)
    result_associated = bool(
        len(item_hits) == 1
        and any(_associated(result_hit, item_hits[0]) for result_hit in result_hits)
    )
    if stage != "post":
        if material_hit is None:
            return StageRecognition(
                stage,
                False,
                "MATERIAL_IDENTITY_UNKNOWN",
                digest,
                identity,
                category_selected,
                category_target,
                item_target,
            )
        star = _star(material_text)
        if star != 1:
            return StageRecognition(
                stage,
                False,
                "MATERIAL_MUST_BE_EXACTLY_ONE_STAR",
                digest,
                identity,
                category_selected,
                category_target,
                item_target,
                material_identity=material_identity,
            )
        if quantity != 1 or quantity_target is None:
            return StageRecognition(
                stage,
                False,
                "MATERIAL_QUANTITY_MUST_BE_EXACTLY_ONE",
                digest,
                identity,
                category_selected,
                category_target,
                item_target,
                material_identity=material_identity,
                material_selected=material_selected,
                material_target=material_target,
                quantity=quantity,
            )
        if not material_selected:
            return StageRecognition(
                stage,
                True,
                "MATERIAL_NOT_SELECTED",
                digest,
                identity,
                category_selected,
                category_target,
                item_target,
                material_identity=material_identity,
                material_selected=False,
                material_target=material_target,
                quantity=quantity,
                quantity_target=quantity_target,
            )
        if final_target is None:
            return StageRecognition(
                stage,
                False,
                "FINAL_CONFIRM_NOT_RECOGNIZED",
                digest,
                identity,
                category_selected,
                category_target,
                item_target,
                material_identity=material_identity,
                material_selected=True,
                material_target=material_target,
                quantity=quantity,
                quantity_target=quantity_target,
            )
    observation = EnhancementObservation(
        screen_state=ENHANCEMENT_SCREEN,
        selected_tab=variant.upper(),
        selected_item_kind=variant.upper(),
        selected_item_identity=identity,
        item_equipped=equipped,
        item_level=item_level,
        target_identity="enhancement-confirm",
        target_roi=final_target or (1, 1, 2, 2),
        panel_bounds=(0, 0, 800, 1280),
        control_class="ENHANCE",
        enhance_control_visible=final_target is not None,
        action_mode="ENHANCE",
        material_identity=material_identity,
        material_known=material_hit is not None,
        material_available=material_hit is not None,
        material_star=_star(material_text) if material_hit else None,
        material_quantity=quantity,
        quantity=quantity,
        enhancement_result_visible=bool(result_hits),
        result_identity=result_identity,
        game_day_id=game_day_id,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=digest,
        evidence_refs=(str(evidence_ref),) if evidence_ref is not None else (),
        overlay_state="none",
        runtime_profile_id=NATIVE_PROFILE_ID,
        recognized=True,
        result_spatially_associated=result_associated,
    )
    return StageRecognition(
        stage,
        True,
        "SUCCESSOR_RECOGNIZED" if stage == "post" else "FINAL_TARGET_RECOGNIZED",
        digest,
        identity,
        category_selected,
        category_target,
        item_target,
        None,
        material_identity,
        material_selected,
        material_target,
        quantity,
        quantity_target,
        observation,
        {"result_spatially_associated": result_associated},
    )


def _as_observation(value: EnhancementObservation | None) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _stage_record(
    stage: str, capture: CapturedNativeFrame, recognition: Any
) -> dict[str, Any]:
    return {
        "stage": stage,
        "frame_sha256": capture.sha256,
        "recognized": recognition.recognized,
        "reason": recognition.reason,
        "target_roi": getattr(recognition, "target", None)
        or getattr(recognition, "go_target", None),
        "category_target": getattr(recognition, "category_target", None),
        "material_target": getattr(recognition, "material_target", None),
        "quantity_target": getattr(recognition, "quantity_target", None),
        "item_identity": getattr(recognition, "item_identity", ""),
    }


class EnhancementIntegratedRoute:
    def __init__(
        self,
        runtime: Any,
        *,
        variant: str,
        reset_identity: str,
        ocr_engine: OcrEngine | None = None,
    ) -> None:
        self.runtime = runtime
        self.variant = str(variant).strip().lower()
        self.reset_identity = str(reset_identity).strip()
        self.ocr_engine = ocr_engine
        self.stages: list[dict[str, Any]] = []
        self.final_dispatch_key: str | None = None

    def _capture_daily(
        self, label: str, *, completed: bool = False
    ) -> tuple[CapturedNativeFrame, DailyRecognition]:
        capture = self.runtime.capture(label)
        recognition = recognize_daily_frame(
            capture.frame,
            variant=self.variant,
            source_frame_sha256=capture.sha256,
            ocr_engine=self.ocr_engine,
            completed=completed,
        )
        self.stages.append(_stage_record(label, capture, recognition))
        return capture, recognition

    def _capture_commander(
        self, label: str, stage: str
    ) -> tuple[CapturedNativeFrame, StageRecognition]:
        capture = self.runtime.capture(label)
        recognition = recognize_commander_stage(
            capture.frame,
            variant=self.variant,
            stage=stage,
            source_frame_sha256=capture.sha256,
            evidence_ref=capture.path,
            ocr_engine=self.ocr_engine,
            game_day_id=self.reset_identity,
        )
        self.stages.append(_stage_record(label, capture, recognition))
        return capture, recognition

    def _tap(
        self,
        capture: CapturedNativeFrame,
        target: NativeBox,
        identity: str,
        *,
        resource_affecting: bool = False,
    ) -> str:
        action_key = f"enhancement:{self.variant}:{identity}:{_stamp()}"
        self.runtime.tap(
            capture,
            target_identity=identity,
            target_roi=target,
            action_key=action_key,
            consequential=False,
        )
        self.stages.append(
            {
                "stage": f"dispatch:{identity}",
                "frame_sha256": capture.sha256,
                "target_identity": identity,
                "target_roi": target,
                "resource_affecting": resource_affecting,
                "consequential": False,
                "action_key": action_key,
            }
        )
        if resource_affecting:
            self.final_dispatch_key = action_key
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
        return action_key

    def _result(
        self,
        *,
        status: str,
        reason: str,
        source: CapturedNativeFrame,
        terminal: CapturedNativeFrame | None = None,
        terminal_recognized: bool = False,
        before: StageRecognition | None = None,
        post: StageRecognition | None = None,
        daily_before: DailyRecognition | None = None,
        daily_after: DailyRecognition | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "flow_id": "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
            "status": status,
            "reason": reason,
            "variant": self.variant,
            "reset_identity": self.reset_identity,
            "stages": self.stages,
            "dispatch_count": sum(
                1
                for stage in self.stages
                if stage.get("stage", "").startswith("dispatch:")
            ),
            "resource_affecting_dispatch_count": 1 if self.final_dispatch_key else 0,
            "resource_affecting_action_key": self.final_dispatch_key,
            "source_frame_sha256": source.sha256,
            "final_before_observation": _as_observation(
                before.observation if before else None
            ),
            "immediate_post_observation": _as_observation(
                post.observation if post else None
            ),
            "daily_progress_before": daily_before.progress[0]
            if daily_before and daily_before.progress
            else None,
            "daily_progress_after": daily_after.progress[0]
            if daily_after and daily_after.progress
            else None,
            "daily_before": (
                {
                    "selected_daily_row": daily_before.selected,
                    "objective_key": daily_before.objective_key,
                    "daily_progress_before": daily_before.progress[0]
                    if daily_before.progress
                    else None,
                    "daily_progress_total": daily_before.progress[1]
                    if daily_before.progress
                    else None,
                }
                if daily_before
                else None
            ),
            "daily_after": (
                {
                    "selected_daily_row": daily_after.selected,
                    "objective_key": daily_after.objective_key,
                    "daily_progress_after": daily_after.progress[0]
                    if daily_after.progress
                    else None,
                    "daily_progress_total": daily_after.progress[1]
                    if daily_after.progress
                    else None,
                }
                if daily_after
                else None
            ),
            "terminal_frame_sha256": terminal.sha256
            if terminal and terminal_recognized
            else "",
            "terminal_recognized": terminal_recognized,
            "terminal_state": "recognized_fresh_terminal"
            if terminal_recognized
            else "evidence_required",
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }

    def run(self) -> dict[str, Any]:
        if self.variant not in SUPPORTED_VARIANTS or not self.reset_identity:
            raise ValueError("enhancement variant and reset identity are required")
        source, daily = self._capture_daily("daily-entry-source")
        if not daily.recognized or daily.progress != (0, 1) or daily.go_target is None:
            return self._result(status="blocked", reason=daily.reason, source=source)
        immediate_daily, daily_before = self._capture_daily("daily-go-immediate-before")
        if not daily_before.recognized or daily_before.go_target is None:
            return self._result(
                status="blocked", reason="DAILY_GO_REVALIDATION_FAILED", source=source
            )
        self._tap(
            immediate_daily,
            daily_before.go_target,
            f"daily-enhancement-go:{self.variant}",
        )
        current, item = self._capture_commander("commander-info-after-daily-go", "item")
        if not item.recognized:
            return self._result(
                status="blocked",
                reason=item.reason,
                source=source,
                daily_before=daily_before,
            )
        if not item.category_selected:
            if item.category_target is None:
                return self._result(
                    status="blocked",
                    reason="CATEGORY_SELECTION_TARGET_MISSING",
                    source=source,
                    daily_before=daily_before,
                )
            self._tap(current, item.category_target, f"category-select:{self.variant}")
            current, item = self._capture_commander("category-select-successor", "item")
            if not item.recognized or not item.category_selected:
                return self._result(
                    status="blocked",
                    reason="CATEGORY_SELECTION_NOT_PROVEN",
                    source=source,
                    daily_before=daily_before,
                )
        if item.item_target is None:
            return self._result(
                status="blocked",
                reason="EQUIPPED_ITEM_TARGET_MISSING",
                source=source,
                daily_before=daily_before,
            )
        self._tap(current, item.item_target, f"item-select:{self.variant}")
        current, item = self._capture_commander("item-select-successor", "item")
        if not item.recognized or not item.category_selected:
            return self._result(
                status="blocked",
                reason="ITEM_SELECTION_NOT_PROVEN",
                source=source,
                daily_before=daily_before,
            )
        if item.open_target is None:
            return self._result(
                status="blocked",
                reason="OPEN_ENHANCE_TARGET_MISSING",
                source=source,
                daily_before=daily_before,
            )
        self._tap(current, item.open_target, f"open-enhance:{self.variant}")
        current, material = self._capture_commander(
            "material-panel-after-open", "material"
        )
        if not material.recognized:
            return self._result(
                status="blocked",
                reason=material.reason,
                source=source,
                daily_before=daily_before,
            )
        if not material.material_selected:
            if material.material_target is None:
                return self._result(
                    status="blocked",
                    reason="MATERIAL_SELECTION_TARGET_MISSING",
                    source=source,
                    daily_before=daily_before,
                )
            self._tap(
                current, material.material_target, f"material-select:{self.variant}"
            )
            current, material = self._capture_commander(
                "material-select-successor", "material"
            )
        if (
            not material.recognized
            or not material.material_selected
            or material.quantity != 1
        ):
            return self._result(
                status="blocked",
                reason="MATERIAL_SELECTION_OR_QUANTITY_NOT_PROVEN",
                source=source,
                daily_before=daily_before,
            )
        immediate_final, final = self._capture_commander(
            "final-confirm-immediate-before", "material"
        )
        if (
            not final.recognized
            or not final.material_selected
            or final.quantity != 1
            or final.observation is None
            or not enhancement_bluestacks_authorizeable(
                final.observation, variant=self.variant
            )
        ):
            return self._result(
                status="blocked",
                reason="FINAL_CONFIRM_REVALIDATION_FAILED",
                source=source,
                daily_before=daily_before,
                before=final,
            )
        final_target = final.observation.target_roi
        self._tap(
            immediate_final,
            final_target,
            "enhancement-confirm",
            resource_affecting=True,
        )
        post_capture: CapturedNativeFrame | None = None
        post: StageRecognition | None = None
        for ordinal in range(MAX_SETTLE_POLLS):
            post_capture, candidate = self._capture_commander(
                f"enhancement-settle-{ordinal}", "post"
            )
            if (
                candidate.recognized
                and candidate.observation is not None
                and enhancement_bluestacks_postcondition_verified(
                    final.observation, candidate.observation, variant=self.variant
                )
            ):
                post = candidate
                break
        if post is None or post_capture is None:
            self.runtime.reconcile(
                self.final_dispatch_key or "",
                "unresolved",
                post_capture or immediate_final,
                "settled same-item successor not proven",
            )
            return self._result(
                status="evidence_required",
                reason="SETTLED_SUCCESSOR_NOT_PROVEN",
                source=source,
                daily_before=daily_before,
                before=final,
                post=post,
            )
        self.runtime.reconcile(
            self.final_dispatch_key or "",
            "confirmed",
            post_capture,
            "same-item category successor proven after bounded settle polling",
        )
        terminal_capture, terminal = self._capture_commander(
            "enhancement-terminal", "post"
        )
        if not terminal.recognized or terminal_capture.sha256 == source.sha256:
            return self._result(
                status="evidence_required",
                reason="FRESH_TERMINAL_NOT_PROVEN",
                source=source,
                terminal=terminal_capture,
                before=final,
                post=post,
                daily_before=daily_before,
            )
        self.runtime.back(
            terminal_capture, action_key=f"return-daily:{self.variant}:{_stamp()}"
        )
        daily_terminal_capture, daily_after = self._capture_daily(
            "daily-successor", completed=True
        )
        if not daily_after.recognized or daily_after.progress != (1, 1):
            return self._result(
                status="evidence_required",
                reason="DAILY_ZERO_TO_ONE_NOT_PROVEN",
                source=source,
                terminal=terminal_capture,
                terminal_recognized=True,
                before=final,
                post=post,
                daily_before=daily_before,
            )
        daily_before_contract = DailyEnhancementObservation(
            selected_daily_row=True,
            objective_key=f"enhance_{self.variant}",
            daily_progress_before=0,
            enhancement=final.observation,
        )
        daily_after_contract = DailyEnhancementObservation(
            selected_daily_row=True,
            objective_key=f"enhance_{self.variant}",
            daily_progress_before=0,
            daily_progress_after=1,
            successor_state=f"DAILY_{self.variant.upper()}_ENHANCEMENT_COMPLETE",
            enhancement=post.observation,
        )
        if not daily_enhancement_bluestacks_postcondition_verified(
            daily_before_contract, daily_after_contract, variant=self.variant
        ):
            return self._result(
                status="evidence_required",
                reason="DAILY_CONTRACT_SUCCESSOR_NOT_PROVEN",
                source=source,
                terminal=daily_terminal_capture,
                terminal_recognized=True,
                before=final,
                post=post,
                daily_before=daily_before,
                daily_after=daily_after,
            )
        result = self._result(
            status="completed",
            reason="DAILY_ENHANCEMENT_ZERO_TO_ONE_VERIFIED",
            source=source,
            terminal=daily_terminal_capture,
            terminal_recognized=True,
            before=final,
            post=post,
            daily_before=daily_before,
            daily_after=daily_after,
        )
        result["state_transition"] = [
            "DAILY_ROW_SELECTED",
            "DAILY_GO_DISPATCHED",
            "COMMANDER_INFO_RECOGNIZED",
            "CATEGORY_SELECTED",
            "ENHANCE_PANEL_OPENED",
            "MATERIAL_SELECTED",
            "QUANTITY_ONE_RECOGNIZED",
            "FINAL_CONFIRM_DISPATCHED",
            "SETTLED_SUCCESSOR_RECONCILED",
            "DAILY_ZERO_TO_ONE_RECONCILED",
        ]
        result["postcondition_verified"] = True
        return result


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
        frame,
        variant=variant,
        stage=stage,
        source_frame_sha256=source_frame_sha256,
        evidence_ref=evidence_ref,
        ocr_engine=ocr_engine,
        game_day_id=game_day_id,
    )
    return EnhancementFrameRecognition(
        result.recognized,
        "ENHANCEMENT_RESULT" if postcondition else ENHANCEMENT_SCREEN,
        result.reason,
        result.observation,
        (("enhancement-confirm", result.observation.target_roi),)
        if result.observation and result.recognized
        else (),
    )


def run_recovery(runtime: Any, *, variant: str, reset_identity: str) -> dict[str, Any]:
    capture = runtime.capture(f"enhancement-{variant}-recovery-source")
    daily = recognize_daily_frame(
        capture.frame, variant=variant, source_frame_sha256=capture.sha256
    )
    commander = recognize_commander_stage(
        capture.frame,
        variant=variant,
        stage="post",
        source_frame_sha256=capture.sha256,
        evidence_ref=capture.path,
        game_day_id=reset_identity,
    )
    safe = daily.recognized or (
        commander.recognized and commander.observation is not None
    )
    return {
        "schema_version": 1,
        "flow_id": "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
        "status": "recovered_safe" if safe else "evidence_required",
        "reason": daily.reason if daily.recognized else commander.reason,
        "variant": variant,
        "dispatch": False,
        "dispatch_count": 0,
        "recovery_only": True,
        "terminal_recognized": safe,
        "terminal_frame_sha256": capture.sha256 if safe else "",
        "terminal_state": "recognized_safe_terminal" if safe else "evidence_required",
        "frames": [
            str(path.relative_to(runtime.session)).replace("\\", "/")
            for path in sorted((runtime.session / "frames").glob("*.png"))
            if path.is_file()
        ],
        "session": str(runtime.session),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def _write_result(session: Path, result: Mapping[str, Any]) -> None:
    session.mkdir(parents=True, exist_ok=True)
    (session / "result.json").write_text(
        json.dumps(dict(result), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dict(result), sort_keys=True, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument(
        "--variant", choices=tuple(sorted(SUPPORTED_VARIANTS)), default="gear"
    )
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
                "flow_id": "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION",
                "status": "dry-run",
                "variant": args.variant,
                "dispatch": False,
                "dispatch_count": 0,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
        )
        return 0
    if not args.yes:
        raise SystemExit("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=str(args.serial),
        output_directory=args.output_directory,
        workflow=f"enhancement-{args.variant}",
        execute=True,
    )
    result = (
        run_recovery(runtime, variant=args.variant, reset_identity=args.reset_identity)
        if args.recovery_only
        else EnhancementIntegratedRoute(
            runtime, variant=args.variant, reset_identity=args.reset_identity
        ).run()
    )
    _write_result(runtime.session, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
