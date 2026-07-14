"""Offline queue model for disabled Daily troop training.

Fighter, Rider, Shooter, and Vehicle retain separate objective ownership.  This module recognizes
typed queue observations and verifies arithmetic in replay fixtures, but product policy blocks
every training dispatch.  No transaction specification, runtime registration, persistence, or
scheduler path exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .contracts import ROI, TaskOutcome, TaskResult
from .profile import PROFILE_ID


TRAINING_SCREEN = "TRAINING"
TRAINING_TARGET = "training-start"
DISABLED_POLICY_REASON = "TRAINING_DISABLED_POLICY"
BLISS_NATIVE_TARGET_PROVENANCE = "bliss-native"
SUPPORTED_VARIANTS = {
    "fighter": ("FIGHTER", "train_fighter"),
    "rider": ("RIDER", "train_rider"),
    "shooter": ("SHOOTER", "train_shooter"),
    "vehicle": ("VEHICLE", "train_vehicle"),
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TrainingObservation:
    """Semantic queue evidence with no executable training target."""

    screen_state: str
    selected_daily_row: bool
    objective_key: str
    unit_variant: str
    unit_identity: str
    facility_identity: str
    selected_facility: bool
    target_identity: str
    target_roi: ROI
    panel_bounds: ROI
    control_class: str
    training_control_visible: bool
    queue_quantity_before: int
    requested_quantity: int
    queue_capacity: int
    queue_slot_available: bool
    unit_tier: Optional[int]
    cost_known: bool
    cost_resource: str
    cost_amount: Optional[int]
    daily_progress_before: int
    queue_quantity_after: Optional[int] = None
    daily_progress_after: Optional[int] = None
    successor_state: str = ""
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = PROFILE_ID
    recognized: bool = True


def _variant_identity(variant: str) -> tuple[str, str]:
    normalized = str(variant).strip().lower()
    try:
        return SUPPORTED_VARIANTS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported training variant: {variant!r}") from exc


def _target_inside_panel(observation: TrainingObservation) -> bool:
    try:
        px0, py0, px1, py1 = observation.panel_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(px0 <= tx0 < tx1 <= px1 and py0 <= ty0 < ty1 <= py1)


def _has_bliss_native_source(observation: TrainingObservation) -> bool:
    refs = tuple(str(ref) for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLISS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "local-reference" not in ref for ref in refs)
        and any(ref.startswith(("evidence/", "synthetic:")) for ref in refs)
        and observation.runtime_profile_id == PROFILE_ID
    )


def training_queue_authorizeable(
    observation: TrainingObservation,
    *,
    variant: str = "fighter",
) -> bool:
    """Recognize one exact troop queue state; this does not authorize training."""

    expected_unit, expected_objective = _variant_identity(variant)
    return bool(
        observation.screen_state == TRAINING_SCREEN
        and observation.selected_daily_row
        and observation.objective_key == expected_objective
        and observation.unit_variant == str(variant).strip().lower()
        and observation.unit_identity == expected_unit
        and bool(observation.facility_identity.strip())
        and observation.selected_facility
        and observation.target_identity == f"{TRAINING_TARGET}:{expected_unit.lower()}"
        and observation.control_class == "TRAIN"
        and observation.training_control_visible
        and _target_inside_panel(observation)
        and observation.queue_quantity_before >= 0
        and observation.requested_quantity == 250
        and observation.queue_capacity >= observation.queue_quantity_before
        and observation.queue_quantity_before + observation.requested_quantity
        <= observation.queue_capacity
        and observation.queue_slot_available
        and observation.unit_tier is not None
        and observation.unit_tier > 0
        and observation.cost_known
        and bool(observation.cost_resource.strip())
        and observation.cost_amount is not None
        and observation.cost_amount > 0
        and 0 <= observation.daily_progress_before < 250
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and observation.recognized
        and _has_bliss_native_source(observation)
    )


def training_queue_postcondition_verified(
    before: TrainingObservation,
    after: TrainingObservation | None,
    *,
    variant: str = "fighter",
) -> bool:
    """Verify offline queue arithmetic without implying permission to create the delta."""

    if not training_queue_authorizeable(before, variant=variant) or after is None:
        return False
    expected_unit, expected_objective = _variant_identity(variant)
    if (
        after.screen_state != TRAINING_SCREEN
        or not after.selected_daily_row
        or after.objective_key != expected_objective
        or after.unit_variant != str(variant).strip().lower()
        or after.unit_identity != expected_unit
        or after.facility_identity != before.facility_identity
        or after.game_day_id != before.game_day_id
        or after.successor_state != "QUEUE_RECONCILED"
        or not _has_bliss_native_source(after)
        or after.queue_quantity_after is None
        or after.daily_progress_after is None
    ):
        return False
    return bool(
        after.queue_quantity_after
        == before.queue_quantity_before + before.requested_quantity
        and after.queue_quantity_after <= before.queue_capacity
        and before.daily_progress_before
        < after.daily_progress_after
        <= 250
    )


def training_disabled_dispatch(
    observation: TrainingObservation,
    *,
    variant: str = "fighter",
) -> TaskResult:
    """Always block training dispatch under current product policy."""

    if not training_queue_authorizeable(observation, variant=variant):
        return TaskResult(
            TaskOutcome.BLOCKED,
            "NO_VALID_TRAINING_QUEUE_OBSERVATION",
            verified=True,
            state=TRAINING_SCREEN,
        )
    return TaskResult(
        TaskOutcome.BLOCKED,
        DISABLED_POLICY_REASON,
        verified=True,
        state=TRAINING_SCREEN,
        details={"requested_quantity": observation.requested_quantity, "dispatch_count": 0},
    )
