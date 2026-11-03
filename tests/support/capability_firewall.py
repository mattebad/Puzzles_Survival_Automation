"""Shared input-capability firewall fixtures for offline tests."""

from __future__ import annotations

from dataclasses import replace

from safe_action_core import ActionClass, Observation, PolicyRequest
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


PROFILE = ACTIVE_RUNTIME_PROFILE_ID
SESSION = "runtime-session-capability-1"
NAV_ROI = (250, 1130, 410, 1280)
TEST_TASK_ID = "TEST-CAPABILITY-FIREWALL"
TEST_TASKS = frozenset({TEST_TASK_ID})


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def nav_observation(**changes) -> Observation:
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity="home-quest-entry",
        target_roi=NAV_ROI,
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="QUEST",
        evidence_refs=("synthetic:capability-nav",),
    )
    return replace(base, **changes)


def nav_request(obs: Observation | None = None, **changes) -> PolicyRequest:
    base = PolicyRequest(
        action_id="nav-capability-1",
        action_key="nav:capability:home-quest",
        task_id=TEST_TASK_ID,
        task_mode="supervised_validation",
        semantic_action="HOME_TO_QUEST",
        expected_runtime_profile_id=PROFILE,
        observation=obs or nav_observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor-1",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=SESSION,
    )
    return replace(base, **changes)
