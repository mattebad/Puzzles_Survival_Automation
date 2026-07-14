"""Offline specification for disabled Daily stamina consumption.

This module validates counter observations and successor math only.  Product policy explicitly
prohibits stamina spending, so every dispatch request returns BLOCKED regardless of evidence.
There is no transaction specification, runtime registration, scheduler path, or live input.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


STAMINA_SCREEN = "WORLD"
STAMINA_OBJECTIVE_KEY = "consume_stamina"
DISABLED_POLICY_REASON = "STAMINA_SPEND_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DisabledStaminaObservation:
    """Semantic Daily/counter evidence with no executable action target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    current_stamina: int
    target_roi: ROI
    panel_bounds: ROI
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _counter_inside_panel(observation: DisabledStaminaObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: DisabledStaminaObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def stamina_counter_authorizeable(
    observation: DisabledStaminaObservation,
) -> bool:
    """Recognize a Daily stamina counter; this does not authorize spending."""

    return bool(
        observation.screen_state == STAMINA_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == STAMINA_OBJECTIVE_KEY
        and observation.current_stamina >= 0
        and _counter_inside_panel(observation)
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def stamina_counter_postcondition_verified(
    before: DisabledStaminaObservation,
    after: DisabledStaminaObservation | None,
    *,
    expected_delta: int,
) -> bool:
    """Verify offline counter arithmetic without implying permission to create the delta."""

    if (
        expected_delta <= 0
        or not stamina_counter_authorizeable(before)
        or after is None
        or not stamina_counter_authorizeable(after)
    ):
        return False
    return bool(
        after.game_day_id == before.game_day_id
        and after.current_stamina == before.current_stamina - expected_delta
    )


def stamina_disabled_dispatch(
    observation: DisabledStaminaObservation,
    *,
    requested_cost: int,
) -> TaskResult:
    """Always block dispatch under product policy, even for valid offline observations."""

    if not stamina_counter_authorizeable(observation):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_STAMINA_COUNTER_OBSERVATION",
            verified=True,
            state=STAMINA_SCREEN,
        )
    if requested_cost <= 0:
        return TaskResult(
            TaskOutcome.BLOCKED,
            "STAMINA_COST_NOT_POSITIVE",
            verified=True,
            state=STAMINA_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=STAMINA_SCREEN,
        details={"requested_cost": requested_cost, "dispatch_count": 0},
    )
