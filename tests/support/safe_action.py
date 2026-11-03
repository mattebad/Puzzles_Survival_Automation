"""Shared safe-action core fixtures for offline tests."""

from __future__ import annotations

from dataclasses import replace

from safe_action_core.models import ActionIntent, Observation, PolicyRequest
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
TEST_TASK_ID = "TEST-SUPERVISED-R1"


def observation(**changes):
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="DAILY_QUEST",
        overlay_state="none_observed",
        target_identity="synthetic-test-only-claim-control",
        target_roi=(550, 500, 730, 580),
        recognized=True,
        control_class="CLAIM",
        consequence="claim_zero_cost_reward",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="row_claimed_or_points_increased",
        evidence_refs=("synthetic:test-only",),
    )
    return replace(base, **changes)


def request(obs=None, **changes):
    base = PolicyRequest(
        action_id="action-1",
        action_key="day-1:claim:row-1",
        task_id=TEST_TASK_ID,
        task_mode="supervised_validation",
        semantic_action="CLAIM_DAILY_QUEST",
        expected_runtime_profile_id=PROFILE_ID,
        observation=obs or observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor-1",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        game_day_id="day-1",
    )
    return replace(base, **changes)


def intent(action_id="action-1", action_key="day-1:claim:row-1"):
    obs = observation()
    return ActionIntent(
        action_id=action_id,
        action_key=action_key,
        task_id=TEST_TASK_ID,
        semantic_action="CLAIM_DAILY_QUEST",
        source_state=obs.source_state,
        target_identity=obs.target_identity,
        target_roi=obs.target_roi,
        source_frame_sha256=obs.frame_sha256,
        source_frame_captured_at=obs.capture_completed_monotonic,
        runtime_profile_id=obs.runtime_profile_id,
        game_day_id="day-1",
        expected_postcondition=obs.expected_postcondition,
        consequence=obs.consequence,
        cost_type=obs.cost_type,
        cost_amount=obs.cost_amount,
        quantity=obs.quantity,
        evidence_refs=obs.evidence_refs,
    )
