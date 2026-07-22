"""Offline Nova Praise semantic contract.

Nova Praise is a separate Research Lab workflow.  This module owns semantic state,
cooldown scheduling, and the one-attempt transaction boundary; it never owns device
transport, registration, or scheduler promotion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Optional

from .contracts import ActionTransactionSpec, ROI, TaskOutcome, TaskResult


NOVA_SCREEN = "NOVA"
NOVA_LAB_MENU = "RESEARCH_LAB_MENU"
NOVA_HOME = "HOME_BASE"
NOVA_PRAISE_TARGET = "nova-praise"
NOVA_INTERACTION_TARGET = "research-lab-nova"
# Checked-in product-policy cooldown; retained 2026-07-16 proof observed CD 00:04:38 (278s).
NOVA_POLICY_COOLDOWN_SECONDS = 300
NOVA_COOLDOWN_CAPTURE_TOLERANCE_SECONDS = 25
# Immediate post frames must not accept implausibly short OCR; retained 278s remains valid.
NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS = 270
NOVA_COOLDOWN_RE = re.compile(
    r"(?:next\s+(?:attempt|interaction)|cooldown|try\s+again|cd)\s*[^0-9]{0,24}"
    r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*"
    r"(hours?|hrs?|minutes?|mins?|seconds?|secs?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NovaPraiseObservation:
    """Current-frame semantic evidence for the Nova Praise action."""

    screen_state: str
    research_lab_identity: bool
    nova_control_visible: bool
    selected_nova: bool
    praise_enabled: bool
    praise_target_identity: str
    praise_target_roi: ROI
    attempts_remaining: Optional[int]
    cooldown_text: str = ""
    cooldown_active: bool = False
    cooldown_seconds: Optional[int] = None
    next_eligible_at: Optional[float] = None
    overlay_state: str = "none_observed"
    frame_sha256: str = ""
    captured_monotonic: Optional[float] = None
    stale: bool = False
    recognized: bool = True


def parse_cooldown_seconds(text: str) -> Optional[int]:
    """Parse a visible cooldown as seconds; reject ambiguous numeric text."""

    match = NOVA_COOLDOWN_RE.search(" ".join(str(text).split()))
    if not match:
        return None
    first, second, third, unit = match.groups()
    first = int(first)
    second = int(second) if second is not None else None
    third = int(third) if third is not None else None
    if third is not None:
        return first * 3600 + second * 60 + third
    if second is not None:
        return first * 60 + second
    if unit and (unit.casefold().startswith("hour") or unit.casefold().startswith("hr")):
        return first * 3600
    if unit and (unit.casefold().startswith("minute") or unit.casefold().startswith("min")):
        return first * 60
    return first


def nova_remaining(observation: NovaPraiseObservation) -> Optional[int]:
    value = observation.attempts_remaining
    if not observation.recognized or value is None or value < 0:
        return None
    return value


def nova_authorizeable(observation: NovaPraiseObservation, *, now: Optional[float] = None) -> bool:
    """Require a fresh, unambiguous, enabled Nova Praise target."""

    if now is not None and observation.captured_monotonic is not None:
        if now < observation.captured_monotonic or now - observation.captured_monotonic > 3.0:
            return False
    return bool(
        observation.screen_state == NOVA_SCREEN
        and observation.research_lab_identity
        and observation.selected_nova
        and observation.praise_enabled
        and observation.praise_target_identity == NOVA_PRAISE_TARGET
        and observation.attempts_remaining is not None
        and observation.attempts_remaining > 0
        and not observation.cooldown_active
        and observation.cooldown_seconds in (None, 0)
        and observation.overlay_state in {"none", "none_observed"}
        and not observation.stale
        and observation.recognized
    )


def nova_transaction_spec(observation: NovaPraiseObservation) -> ActionTransactionSpec:
    if not nova_authorizeable(observation):
        raise ValueError("Nova Praise preconditions are not positively recognized")
    return ActionTransactionSpec(
        action_kind="PRAISE_NOVA",
        expected_source_screen=NOVA_SCREEN,
        subject="Nova Praise",
        quantity=1,
        resource_or_currency=None,
        maximum_cost=0,
        free_only=True,
        semantic_preconditions=(
            "research_lab_nova_screen",
            "enabled_nova_praise",
            "positive_attempt_count",
            "no_cooldown",
            "fresh_native_frame",
        ),
        semantic_postconditions=(
            "attempt_count_decreases_by_one",
            "cooldown_visible_or_zero_terminal",
        ),
    )


def nova_cooldown_consistent_with_policy(
    before: NovaPraiseObservation,
    after: NovaPraiseObservation,
    *,
    policy_cooldown_seconds: int = NOVA_POLICY_COOLDOWN_SECONDS,
    capture_tolerance_seconds: int = NOVA_COOLDOWN_CAPTURE_TOLERANCE_SECONDS,
) -> bool:
    """Require visible cooldown consistent with the fixed policy after capture delay.

    Preserves the retained 278-second proof (policy 300 minus ~22s capture delay) while
    rejecting missing, over-policy (301+), and implausibly short timers.
    """

    if (
        not after.cooldown_active
        or after.cooldown_seconds is None
        or after.cooldown_seconds <= 0
        or after.cooldown_seconds > policy_cooldown_seconds
        or after.cooldown_seconds < NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS
    ):
        return False
    if before.captured_monotonic is None or after.captured_monotonic is None:
        return False
    elapsed = after.captured_monotonic - before.captured_monotonic
    if elapsed < 0:
        return False
    expected = policy_cooldown_seconds - elapsed
    lower = max(
        NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS,
        int(expected - capture_tolerance_seconds),
    )
    upper = min(policy_cooldown_seconds, int(expected + capture_tolerance_seconds))
    if upper < lower:
        return False
    return lower <= after.cooldown_seconds <= upper


def nova_postcondition_verified(
    before: NovaPraiseObservation,
    after: Optional[NovaPraiseObservation],
    *,
    now: Optional[float] = None,
) -> bool:
    """Require exactly one decrement and a policy-consistent cooldown successor."""

    # Source freshness is enforced immediately before transport. Reapplying the three-second
    # dispatch window after OCR/result polling would reject valid delayed postconditions.
    if after is None or not nova_authorizeable(before):
        return False
    if (
        after.screen_state != NOVA_SCREEN
        or not after.research_lab_identity
        or not after.selected_nova
        or not after.recognized
        or after.stale
        or after.overlay_state not in {"none", "none_observed"}
        or before.attempts_remaining is None
        or after.attempts_remaining != before.attempts_remaining - 1
    ):
        return False
    fresh = (
        before.frame_sha256
        and after.frame_sha256
        and before.frame_sha256 != after.frame_sha256
        and after.captured_monotonic is not None
        and (before.captured_monotonic is None or after.captured_monotonic > before.captured_monotonic)
    )
    if not fresh:
        return False
    if after.praise_enabled:
        return False
    if after.next_eligible_at is not None and now is not None and after.next_eligible_at < now:
        return False
    return nova_cooldown_consistent_with_policy(before, after)


def next_eligible_timestamp(observation: NovaPraiseObservation, *, now: float) -> Optional[float]:
    """Return the scheduler wake time, never a busy-loop delay."""

    if nova_remaining(observation) in (None, 0):
        return None
    if not observation.cooldown_active or observation.cooldown_seconds is None:
        return now
    return observation.next_eligible_at or now + observation.cooldown_seconds


def nova_perform_one_pulse(
    before: NovaPraiseObservation,
    after: Optional[NovaPraiseObservation] = None,
    *,
    now: Optional[float] = None,
) -> TaskResult:
    """Pure one-pulse result; the adapter supplies transport and fresh after evidence."""

    if not nova_authorizeable(before, now=now):
        return TaskResult(TaskOutcome.BLOCKED, "NO_AUTHORIZED_NOVA_PRAISE", verified=True, state=NOVA_SCREEN)
    if after is None:
        return TaskResult.progress("PRAISE_NOVA is authorized; dispatch exactly one attempt", NOVA_SCREEN)
    if not nova_postcondition_verified(before, after, now=now):
        return TaskResult(TaskOutcome.FAILED_SAFE, "NOVA_PRAISE_POSTCONDITION_NOT_PROVEN", state=NOVA_SCREEN)
    if after.attempts_remaining == 0:
        return TaskResult.done("Nova Praise attempts are consumed", "nova:praise:complete", NOVA_SCREEN)
    eligible = next_eligible_timestamp(after, now=now or 0.0)
    return TaskResult.progress(
        "Nova Praise cooldown recorded; scheduler may run other work",
        NOVA_SCREEN,
        attempts_remaining=after.attempts_remaining,
        next_eligible_at=eligible,
        cooldown_seconds=after.cooldown_seconds,
    )


def with_cooldown(observation: NovaPraiseObservation, *, now: float) -> NovaPraiseObservation:
    """Attach a scheduler timestamp after deterministic cooldown parsing."""

    seconds = observation.cooldown_seconds or parse_cooldown_seconds(observation.cooldown_text)
    return replace(
        observation,
        cooldown_seconds=seconds,
        cooldown_active=bool(seconds and seconds > 0),
        next_eligible_at=(now + seconds if seconds and seconds > 0 else None),
    )
