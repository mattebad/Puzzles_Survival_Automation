"""Offline contract for the aggregate Daily Quest Claim control."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult


DAILY_QUEST_SCREEN = "DAILY_QUEST"
DAILY_QUEST_CLAIM_TARGET = "daily-quest-claim"
BLUESTACKS_NATIVE_TARGET_PROVENANCE = "bluestacks-native"
BLUESTACKS_NATIVE_RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AvailableDailyClaimObservation:
    """Evidence for one aggregate ordinary Daily Claim control.

    Objective and progress fields remain descriptive legacy observation data so retained
    evidence can load, but authorization intentionally does not inspect them.
    """

    screen_state: str
    selected_daily_quest: bool
    objective_key: str
    objective_name: str
    current_progress: int
    required_progress: int
    row_bounds: ROI
    target_identity: str
    target_roi: ROI
    control_class: str
    row_fully_visible: bool
    claim_fully_visible: bool
    cost_type: str = "unknown"
    cost_amount: Optional[float] = None
    quantity: Optional[int] = None
    game_day_id: Optional[str] = None
    target_provenance: str = "unknown"
    source_frame_sha256: str = ""
    evidence_refs: tuple[str, ...] = ()
    milestone_reward: bool = False
    clipped: bool = False
    overlay_state: str = "none_observed"
    reset_guard_active: bool = False
    runtime_profile_id: str = BLUESTACKS_NATIVE_RUNTIME_PROFILE_ID
    recognized: bool = True
    points: Optional[int] = None
    reward_points: Optional[int] = None
    reset_timer: Optional[str] = None
    catalog_reconciled: bool = False
    # These fields are deliberately separate from the legacy cost/quantity
    # values.  A production recognizer must positively prove the ordinary
    # reward control rather than treating missing OCR as proof of "free".
    ordinary_reward_claim: Optional[bool] = None
    free_control_proven: Optional[bool] = None
    quantity_one_proven: Optional[bool] = None
    cost_region_scan: Optional[Mapping[str, object]] = None
    cost_icon_scan: Optional[Mapping[str, object]] = None
    row_panel_proven: Optional[bool] = None
    row_panel_source: str = ""
    reset_timer_seconds: Optional[int] = None
    reset_observed_utc: Optional[str] = None
    reset_deadline_utc: Optional[str] = None
    reset_deadline_identity: Optional[str] = None
    reset_deadline_tolerance_seconds: Optional[int] = None
    available_claim_controls: Optional[int] = None


def _target_inside_row(observation: AvailableDailyClaimObservation) -> bool:
    try:
        rx0, ry0, rx1, ry1 = observation.row_bounds
        tx0, ty0, tx1, ty1 = observation.target_roi
    except (TypeError, ValueError):
        return False
    return bool(rx0 <= tx0 < tx1 <= rx1 and ry0 <= ty0 < ty1 <= ry1)


def _has_bluestacks_native_source(observation: AvailableDailyClaimObservation) -> bool:
    """Require a current native BlueStacks source, never a synthetic reference."""

    refs = tuple(str(ref).strip() for ref in observation.evidence_refs)
    return bool(
        observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
        and _SHA256_RE.fullmatch(observation.source_frame_sha256 or "")
        and refs
        and all(ref and "synthetic:" not in ref and "local-reference" not in ref for ref in refs)
        and observation.runtime_profile_id == BLUESTACKS_NATIVE_RUNTIME_PROFILE_ID
    )


def _positive_free_semantics(observation: AvailableDailyClaimObservation) -> bool:
    """Require positive control semantics when the recognizer supplies them.

    ``None`` is retained as a compatibility value for the older offline
    contract fixtures.  The BlueStacks recognizer always supplies explicit
    booleans, so a false production finding cannot pass through this fallback.
    """

    if observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE:
        return bool(
            observation.ordinary_reward_claim is True
            and observation.free_control_proven is True
            and observation.quantity_one_proven is True
        )
    return bool(
        observation.ordinary_reward_claim is not False
        and observation.free_control_proven is not False
        and observation.quantity_one_proven is not False
    )


def _cost_scan_is_clear(observation: AvailableDailyClaimObservation) -> bool:
    scan = observation.cost_region_scan
    if scan is None:
        if observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE:
            return False
        return observation.cost_icon_scan is None
    if not isinstance(scan, Mapping):
        return False
    clear = bool(
        scan.get("attached_cost") is not True
        and scan.get("numeric_only_cost") is not True
        and scan.get("icon_only_cost") is not True
        and scan.get("currency_icon") is not True
        and scan.get("currency_amount") is not True
    )
    icon_scan = observation.cost_icon_scan
    if icon_scan is not None:
        if not isinstance(icon_scan, Mapping):
            return False
        clear = clear and icon_scan.get("currency_icon") is not True
    return clear


def _reset_deadline_identities_match(
    expected: object,
    actual: object,
    *,
    tolerance_seconds: int,
) -> bool:
    if expected == actual:
        return True
    if not (
        isinstance(expected, str)
        and isinstance(actual, str)
        and expected.startswith("reset-deadline:")
        and actual.startswith("reset-deadline:")
    ):
        return False
    try:
        from datetime import datetime

        expected_utc = datetime.fromisoformat(expected.split(":", 1)[1].replace("Z", "+00:00"))
        actual_utc = datetime.fromisoformat(actual.split(":", 1)[1].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return abs((expected_utc - actual_utc).total_seconds()) <= max(0, tolerance_seconds)


def _reset_identity_is_bound(observation: AvailableDailyClaimObservation) -> bool:
    values = (
        observation.reset_deadline_identity,
        observation.reset_deadline_utc,
        observation.reset_observed_utc,
        observation.reset_timer_seconds,
    )
    if all(value is None for value in values):
        # Historical pure observations predate deadline evidence.  They still
        # require the explicit non-empty game-day value below.
        return observation.target_provenance != BLUESTACKS_NATIVE_TARGET_PROVENANCE
    if not all(value is not None for value in values):
        return False
    return bool(
        _reset_deadline_identities_match(
            observation.reset_deadline_identity,
            observation.game_day_id,
            tolerance_seconds=observation.reset_deadline_tolerance_seconds or 0,
        )
        and isinstance(observation.reset_timer_seconds, int)
        and observation.reset_timer_seconds > 0
        and isinstance(observation.reset_deadline_utc, str)
        and isinstance(observation.reset_observed_utc, str)
        and isinstance(observation.reset_deadline_tolerance_seconds, int)
        and observation.reset_deadline_tolerance_seconds >= 0
    )


def available_daily_claim_authorizeable(observation: AvailableDailyClaimObservation) -> bool:
    """Require a current selected-Daily aggregate Claim target."""

    return bool(
        observation.screen_state == DAILY_QUEST_SCREEN
        and observation.selected_daily_quest
        and observation.row_fully_visible
        and observation.claim_fully_visible
        and observation.target_identity == DAILY_QUEST_CLAIM_TARGET
        and observation.control_class == "CLAIM"
        and observation.cost_type == "none"
        and observation.cost_amount == 0
        and observation.quantity == 1
        and _positive_free_semantics(observation)
        and _cost_scan_is_clear(observation)
        and (
            observation.row_panel_proven is True
            if observation.target_provenance == BLUESTACKS_NATIVE_TARGET_PROVENANCE
            else observation.row_panel_proven is not False
        )
        and _target_inside_row(observation)
        and not observation.milestone_reward
        and not observation.clipped
        and observation.overlay_state in {"none", "none_observed"}
        and bool(observation.game_day_id)
        and not observation.reset_guard_active
        and _reset_identity_is_bound(observation)
        and observation.recognized
        and _has_bluestacks_native_source(observation)
    )


def available_daily_claim_transaction_spec(observation: AvailableDailyClaimObservation) -> ActionTransactionSpec:
    if not available_daily_claim_authorizeable(observation):
        raise ValueError("generalized Daily Quest Claim preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="CLAIM_DAILY_QUEST",
        expected_source_screen=DAILY_QUEST_SCREEN,
        subject="Selected Daily aggregate Claim",
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        allowed_confirmation_dialogs=(),
        semantic_preconditions=(
            "daily_quest_screen",
            "selected_daily_quest",
            "accepted_native_target_evidence",
            "explicit_zero_cost",
            "ordinary_claim_control",
            "not_milestone",
        ),
        semantic_postconditions=(
            "same_selected_daily_and_reset_identity",
            "points_increase",
            "no_available_ordinary_claim_controls",
        ),
    )


def available_daily_claim_postcondition_verified(
    before: AvailableDailyClaimObservation,
    after: AvailableDailyClaimObservation | None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    row_disappeared: bool = False,
) -> bool:
    """Require selected Daily/reset continuity, points increase, and Claim exhaustion."""

    if not available_daily_claim_authorizeable(before) or after is None:
        return False
    if (
        after.screen_state != DAILY_QUEST_SCREEN
        or not after.selected_daily_quest
        or after.game_day_id != before.game_day_id
    ):
        return False
    if (
        before.reset_deadline_identity is not None
        or after.reset_deadline_identity is not None
    ):
        if (
            before.reset_deadline_identity is None
            or after.reset_deadline_identity is None
            or not _reset_deadline_identities_match(
                before.reset_deadline_identity,
                after.reset_deadline_identity,
                tolerance_seconds=(
                    after.reset_deadline_tolerance_seconds
                    if after.reset_deadline_tolerance_seconds is not None
                    else before.reset_deadline_tolerance_seconds or 0
                ),
            )
        ):
            return False
        tolerance = max(
            0,
            int(
                after.reset_deadline_tolerance_seconds
                if after.reset_deadline_tolerance_seconds is not None
                else before.reset_deadline_tolerance_seconds or 0
            ),
        )
        if (
            before.reset_timer_seconds is None
            or after.reset_timer_seconds is None
            or after.reset_timer_seconds - before.reset_timer_seconds > tolerance
        ):
            return False
        if before.reset_observed_utc and after.reset_observed_utc:
            try:
                from datetime import datetime

                before_utc = datetime.fromisoformat(
                    before.reset_observed_utc.replace("Z", "+00:00")
                )
                after_utc = datetime.fromisoformat(
                    after.reset_observed_utc.replace("Z", "+00:00")
                )
                elapsed = max(0.0, (after_utc - before_utc).total_seconds())
                countdown_delta = before.reset_timer_seconds - after.reset_timer_seconds
                if abs(countdown_delta - elapsed) > tolerance + 1.0:
                    return False
            except (TypeError, ValueError):
                return False
    controls_exhausted = bool(
        after.available_claim_controls == 0
        if after.available_claim_controls is not None
        else (
            row_disappeared
            or after.target_identity != DAILY_QUEST_CLAIM_TARGET
            or after.control_class != "CLAIM"
            or not after.claim_fully_visible
        )
    )
    observed_points_before = before.points if points_before is None else points_before
    observed_points_after = after.points if points_after is None else points_after
    points_changed = (
        isinstance(observed_points_before, int)
        and not isinstance(observed_points_before, bool)
        and isinstance(observed_points_after, int)
        and not isinstance(observed_points_after, bool)
        and observed_points_after > observed_points_before
    )
    return bool(controls_exhausted and points_changed)


def available_daily_claim_perform_one_pulse(
    before: AvailableDailyClaimObservation,
    after: AvailableDailyClaimObservation | None = None,
    *,
    points_before: Optional[int] = None,
    points_after: Optional[int] = None,
    row_disappeared: bool = False,
) -> TaskResult:
    """Return a pure result; transport remains outside this evidence-gated module."""

    if not available_daily_claim_authorizeable(before):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_DAILY_CLAIM_TARGET", verified=True, state=DAILY_QUEST_SCREEN)
    if after is None:
        return TaskResult.progress("CLAIM_DAILY_QUEST is authorized by the offline contract; dispatch remains evidence-gated", DAILY_QUEST_SCREEN)
    if not available_daily_claim_postcondition_verified(
        before,
        after,
        points_before=points_before,
        points_after=points_after,
        row_disappeared=row_disappeared,
    ):
        return TaskResult(TaskOutcome.FAILED_SAFE, "DAILY_CLAIM_POSTCONDITION_NOT_PROVEN", state=DAILY_QUEST_SCREEN)
    return TaskResult.done(
        "generalized Daily Quest Claim postcondition verified",
        "daily-quest:aggregate-claimed",
        DAILY_QUEST_SCREEN,
    )
