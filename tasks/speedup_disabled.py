"""Offline model for disabled Daily item-based speedups."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


SPEEDUP_SCREEN = "SPEEDUP"
SPEEDUP_TARGET = "speedup-control"
DISABLED_POLICY_REASON = "SPEEDUP_DISABLED_POLICY"
REQUIRED_MINUTES = 180
REQUIRED_SECONDS = REQUIRED_MINUTES * 60
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SpeedupObservation:
    """Semantic timer/item evidence with no executable speedup target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    timer_identity: str
    timer_active: bool
    timer_seconds_before: Optional[int]
    item_identity: str
    item_known: bool
    item_quantity_before: Optional[int]
    speedup_minutes: Optional[int]
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    speedup_control_visible: bool
    premium_item: bool
    daily_progress_before: int
    timer_seconds_after: Optional[int] = None
    item_quantity_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    speedup_confirmed: bool = False
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _target_inside_panel(observation: SpeedupObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: SpeedupObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def speedup_authorizeable(observation: SpeedupObservation) -> bool:
    """Recognize exact 180-minute item/timer evidence; this does not authorize speedup."""

    return bool(
        observation.screen_state == SPEEDUP_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == "speedup_using_items"
        and bool(observation.timer_identity.strip())
        and observation.timer_active
        and observation.timer_seconds_before is not None
        and observation.timer_seconds_before >= REQUIRED_SECONDS
        and bool(observation.item_identity.strip())
        and observation.item_known
        and observation.item_quantity_before is not None
        and observation.item_quantity_before >= 1
        and observation.speedup_minutes == REQUIRED_MINUTES
        and observation.target_identity == SPEEDUP_TARGET
        and observation.control_class == "SPEEDUP"
        and observation.speedup_control_visible
        and _target_inside_panel(observation)
        and not observation.premium_item
        and observation.daily_progress_before == 0
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def speedup_postcondition_verified(
    before: SpeedupObservation,
    after: SpeedupObservation | None,
) -> bool:
    """Verify offline timer/item arithmetic without implying permission to spend."""

    if not speedup_authorizeable(before) or after is None:
        return False
    return bool(
        speedup_authorizeable(after)
        and after.timer_identity == before.timer_identity
        and after.item_identity == before.item_identity
        and after.game_day_id == before.game_day_id
        and after.speedup_confirmed
        and after.timer_seconds_after
        == before.timer_seconds_before - REQUIRED_SECONDS
        and after.item_quantity_after == before.item_quantity_before - 1
        and after.daily_progress_after == 1
        and after.successor_state == "SPEEDUP_RECONCILED"
    )


def speedup_disabled_dispatch(observation: SpeedupObservation) -> TaskResult:
    """Always block item-based speedup dispatch under current policy."""

    if not speedup_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_SPEEDUP_OBSERVATION",
            verified=True,
            state=SPEEDUP_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=SPEEDUP_SCREEN,
        details={"dispatch_count": 0},
    )
