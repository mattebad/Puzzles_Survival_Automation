"""Exact saved Commander Talent Memory identities and current-frame parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
from typing import Any, Iterable


class TalentPreset(str, Enum):
    MILITARY = "Military"
    ECONOMY = "Economy"
    TRAINING = "Training"


class PresetRowState(str, Enum):
    APPLIED = "Applied"
    APPLY = "Apply"
    UNKNOWN = "unknown"


PRESET_NAMES = tuple(preset.value for preset in TalentPreset)


@dataclass(frozen=True)
class PresetRow:
    name: str
    state: PresetRowState
    status_target: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class TalentMemoryObservation:
    recognized: bool
    preset_name: str
    row_state: PresetRowState
    applied_preset: str | None
    apply_target: tuple[int, int, int, int] | None
    source_frame_sha256: str
    evidence_ref: str
    reason: str



@dataclass(frozen=True)
class TalentPresetNativeResult:
    status: str
    verified: bool
    preset_name: str
    reason: str
    evidence_refs: tuple[str, ...]
    input_count: int
    switch_action_key: str | None = None
    switch_transport_attempted: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"already_applied", "switched", "deferred", "unknown"}:
            raise ValueError("talent native result status is unsupported")
        if type(self.verified) is not bool:
            raise ValueError("talent native result verified flag must be boolean")
        if self.preset_name not in PRESET_NAMES:
            raise ValueError("talent native result preset name is unsupported")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("talent native result reason is required")
        if type(self.evidence_refs) is not tuple or any(
            type(reference) is not str or not reference.strip() for reference in self.evidence_refs
        ):
            raise ValueError("talent native result evidence references are invalid")
        if type(self.input_count) is not int or self.input_count < 0:
            raise ValueError("talent native result input count is invalid")
        if type(self.switch_transport_attempted) is not bool:
            raise ValueError("talent switch transport-attempted flag must be boolean")
        if self.switch_action_key is not None and (
            type(self.switch_action_key) is not str or not self.switch_action_key.strip()
        ):
            raise ValueError("talent switch action key is invalid")
        if self.verified and self.status not in {"already_applied", "switched"}:
            raise ValueError("only verified preset outcomes may authorize a route")
        if self.status == "switched" and (not self.switch_action_key or not self.switch_transport_attempted):
            raise ValueError("a switched result requires its attempted canonical action key")
        if self.status == "already_applied" and self.switch_action_key is not None:
            raise ValueError("an already-applied result cannot bind a switch action")
        if self.status == "deferred" and (self.switch_action_key is not None or self.switch_transport_attempted):
            raise ValueError("a deferred result cannot report a switch attempt")


@dataclass(frozen=True)
class TalentSwitchPermit:
    """One-shot permit emitted only after canonical action preparation."""

    action_key: str

    def __post_init__(self) -> None:
        if type(self.action_key) is not str or not self.action_key.strip():
            raise ValueError("talent switch permit requires a canonical action key")



@dataclass(frozen=True)
class TalentMemoryRecognition:
    recognized: bool
    rows: tuple[PresetRow, ...]
    applied_preset: str | None
    reason: str


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _center_y(bounds: tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _center_x(bounds: tuple[int, int, int, int]) -> int:
    return (bounds[0] + bounds[2]) // 2


def _bounds(hit: Any) -> tuple[int, int, int, int] | None:
    value = getattr(hit, "bounds", None)
    if type(value) not in (tuple, list) or len(value) != 4:
        return None
    try:
        box = tuple(int(part) for part in value)
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
        return None
    return box  # type: ignore[return-value]


def _text(hit: Any) -> str:
    return _normalized(getattr(hit, "text", ""))


def _associated(status_hit: Any, name_hit: Any) -> bool:
    status_box = _bounds(status_hit)
    name_box = _bounds(name_hit)
    return bool(
        status_box is not None
        and name_box is not None
        and abs(_center_y(status_box) - _center_y(name_box)) <= 48
        and _center_x(status_box) > _center_x(name_box) + 150
    )




def recognize_talent_memory(hits: Iterable[Any]) -> TalentMemoryRecognition:
    """Recognize all exact named rows and their Applied/Apply state from one frame.

    A row is only bound when its status word is on the same row, to the right of
    the preset name. Missing, duplicated, or contradictory labels are unknown.
    """

    materialized = tuple(hits)
    normalized_names = {name.casefold(): name for name in PRESET_NAMES}
    names_by_value: dict[str, list[Any]] = {name: [] for name in PRESET_NAMES}
    statuses: list[Any] = []
    for hit in materialized:
        text = _text(hit)
        if text in normalized_names:
            names_by_value[normalized_names[text]].append(hit)
        elif text in {"applied", "apply"}:
            statuses.append(hit)
    if any(len(names_by_value[name]) != 1 for name in PRESET_NAMES):
        return TalentMemoryRecognition(False, (), None, "PRESET_NAMES_MISSING_OR_AMBIGUOUS")

    rows: list[PresetRow] = []
    used_statuses: set[int] = set()
    for name in PRESET_NAMES:
        name_hit = names_by_value[name][0]
        matches = [hit for hit in statuses if _associated(hit, name_hit)]
        if len(matches) != 1 or id(matches[0]) in used_statuses:
            return TalentMemoryRecognition(False, (), None, "PRESET_STATUS_MISSING_OR_AMBIGUOUS")
        status_hit = matches[0]
        used_statuses.add(id(status_hit))
        state = PresetRowState.APPLIED if _text(status_hit) == "applied" else PresetRowState.APPLY
        rows.append(PresetRow(name=name, state=state, status_target=_bounds(status_hit)))
    if len(used_statuses) != len(statuses):
        return TalentMemoryRecognition(False, (), None, "UNBOUND_PRESET_STATUS")
    applied = [row.name for row in rows if row.state is PresetRowState.APPLIED]
    if len(applied) != 1:
        return TalentMemoryRecognition(False, (), None, "APPLIED_PRESET_NOT_UNIQUE")
    return TalentMemoryRecognition(True, tuple(rows), applied[0], "TALENT_MEMORY_ROWS_RECOGNIZED")


def observe_preset(
    recognition: TalentMemoryRecognition,
    preset_name: str,
    *,
    source_frame_sha256: str,
    evidence_ref: str,
) -> TalentMemoryObservation:
    """Bind one recognized row to its source frame and requested exact preset."""

    if preset_name not in PRESET_NAMES:
        raise ValueError("required preset must be Military, Economy, or Training")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source_frame_sha256)):
        raise ValueError("source frame SHA-256 must be lowercase hexadecimal")
    if type(evidence_ref) is not str or not evidence_ref.strip():
        raise ValueError("preset evidence reference is required")
    if not recognition.recognized:
        return TalentMemoryObservation(
            False, preset_name, PresetRowState.UNKNOWN, None, None,
            source_frame_sha256, evidence_ref, recognition.reason,
        )
    row = next((item for item in recognition.rows if item.name == preset_name), None)
    if row is None:
        return TalentMemoryObservation(
            False, preset_name, PresetRowState.UNKNOWN, recognition.applied_preset, None,
            source_frame_sha256, evidence_ref, "REQUIRED_PRESET_ROW_MISSING",
        )
    return TalentMemoryObservation(
        True,
        preset_name,
        row.state,
        recognition.applied_preset,
        row.status_target if row.state is PresetRowState.APPLY else None,
        source_frame_sha256,
        evidence_ref,
        "PRESET_APPLIED" if row.state is PresetRowState.APPLIED else "PRESET_AVAILABLE_TO_APPLY",
    )


def context_fingerprint(context: Any) -> str:
    """Stable digest for explicit, JSON-compatible context continuity."""

    import json

    try:
        payload = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("talent preset context must be JSON-compatible") from exc
    if not payload or payload == "null":
        raise ValueError("talent preset context is required")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
