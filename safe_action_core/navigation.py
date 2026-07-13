from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Optional, Sequence, Tuple

from .models import ActionClass, Observation, PolicyDecision, PolicyRequest, TransportResult
from .policy import CentralPolicy
from .store import SafetyStore


class NavigationStatus(str, Enum):
    PROPOSED = "proposed"
    DISPATCHED = "dispatched"
    REACHED_SUCCESSOR = "reached_successor"
    SAFE_NO_EFFECT = "safe_no_effect"
    NAVIGATION_FAILED = "navigation_failed"


@dataclass(frozen=True)
class NavigationStep:
    name: str
    source_state: str
    semantic_action: str
    expected_successors: Tuple[str, ...]
    timeout_seconds: float = 10.0
    allow_one_safe_retry: bool = True


@dataclass(frozen=True)
class NavigationResult:
    status: NavigationStatus
    reason: str
    transport_calls: int
    attempts: int
    recovery_required: bool = False


class NavigationRunner:
    """Bounded local-ROI navigation, separate from consequential action reconciliation."""
    def __init__(self, store: SafetyStore, policy: CentralPolicy, owner_id: str, clock: Callable[[], float]):
        self.store, self.policy, self.owner_id, self.clock = store, policy, owner_id, clock

    @staticmethod
    def _local_change(before: Observation, after: Observation) -> Optional[str]:
        for name in ("runtime_profile_id", "source_state", "overlay_state", "target_identity", "target_roi", "forbidden_region_intersects_target", "package_foreground", "os_surface", "hard_stop_detected"):
            if getattr(before, name) != getattr(after, name):
                return name.upper() + "_CHANGED"
        if after.capture_completed_monotonic <= before.capture_completed_monotonic:
            return "IMMEDIATE_RECAPTURE_NOT_FRESH"
        return None

    def run(self, step: NavigationStep, request: PolicyRequest, recapture: Callable[[], Observation], transport: Callable[[Tuple[int, int, int, int]], TransportResult], observe: Callable[[], Iterable[Observation]]) -> NavigationResult:
        calls = 0
        now = self.clock()
        if not self.store.lease_valid_for(self.owner_id, now):
            return NavigationResult(NavigationStatus.NAVIGATION_FAILED, "LEASE_REQUIRED", 0, 0)
        request = request.__class__(**{**request.__dict__, "action_class": ActionClass.NAVIGATION_ONLY, "lease_valid": True, "lease_owner": self.owner_id, "monotonic_now": now})
        first = self.policy.evaluate(request)
        self.store.audit(request.task_id, "navigation_proposed", now, {"step": step,
            "policy": first}, request.action_id)
        if not first.authorized:
            return NavigationResult(NavigationStatus.NAVIGATION_FAILED, first.reason_code, 0, 0)
        max_attempts = 2 if step.allow_one_safe_retry else 1
        for attempt in range(1, max_attempts + 1):
            immediate = recapture()
            pre = request.with_observation(immediate, self.clock())
            pre = pre.__class__(**{**pre.__dict__, "action_class": ActionClass.NAVIGATION_ONLY, "lease_valid": True, "lease_owner": self.owner_id})
            decision = self.policy.evaluate(pre)
            changed = self._local_change(request.observation, immediate)
            if not decision.authorized or changed:
                return NavigationResult(NavigationStatus.NAVIGATION_FAILED, changed or decision.reason_code, calls, attempt)
            calls += 1
            tr = transport(immediate.target_roi)
            self.store.audit(request.task_id, "navigation_dispatched", self.clock(), {"attempt": attempt, "transport": tr}, request.action_id)
            if not tr.dispatched:
                return NavigationResult(NavigationStatus.NAVIGATION_FAILED, "NOT_DISPATCHED", calls, attempt)
            posts = list(observe())
            for post in posts:
                if post.recognized and post.source_state in step.expected_successors:
                    self.store.audit(request.task_id, "navigation_reached_successor", self.clock(), {"state": post.source_state}, request.action_id)
                    return NavigationResult(NavigationStatus.REACHED_SUCCESSOR, "POSITIVE_SUCCESSOR", calls, attempt)
            no_effect = any(p.recognized and p.source_state == step.source_state and p.target_identity == immediate.target_identity and p.overlay_state in ("none", "none_observed") for p in posts)
            if no_effect and attempt < max_attempts:
                self.store.audit(request.task_id, "navigation_safe_no_effect", self.clock(), {"attempt": attempt}, request.action_id)
                continue
            return NavigationResult(NavigationStatus.NAVIGATION_FAILED, "UNKNOWN_SUCCESSOR", calls, attempt, True)
        return NavigationResult(NavigationStatus.NAVIGATION_FAILED, "RETRY_EXHAUSTED", calls, max_attempts)
