"""Shared offline Noah's Tavern Daily and free-attempt maintenance pass.

This controller consumes independently recognized tier evidence and produces scheduler-aware
results without transport.  It deliberately owns no scheduler loop, runtime lease, Claim action,
or registration path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import json
import math
import re
from typing import Mapping, Optional

from .noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NoahTavernObservation,
    RecruitTier,
    noah_recruit_authorizeable,
    noah_result_postcondition_verified,
    parse_cooldown_seconds,
)
from .scheduler_task_result import (
    SchedulerAwareTaskResult,
    SchedulerIdentity,
    SchedulerInvocationState,
    SchedulerTaskOutcome,
)


MAINTENANCE_TASK_ID = "recruitment-free-attempt-maintenance"
DAILY_RECRUITMENT_TASK_ID = "recruit_noahs_tavern"
MAINTENANCE_STATE_SCHEMA = "noahs-tavern-maintenance-v1"
TIER_COOLDOWN_SECONDS: dict[RecruitTier, int] = {
    RecruitTier.BASIC: 600,
    RecruitTier.INT: 86_400,
    RecruitTier.ADV: 172_800,
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class TierPassOutcome(str, Enum):
    ACTION_PERFORMED = "action_performed"
    DEFERRED = "deferred"
    ALREADY_COMPLETE = "already_complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PersistedTierState:
    attempts_remaining: int
    next_eligible_at: Optional[float] = None
    cooldown_seconds: int = 0
    last_outcome: str = "never_observed"

    def __post_init__(self) -> None:
        if self.attempts_remaining < 0:
            raise ValueError("attempts_remaining cannot be negative")
        if self.next_eligible_at is not None and not math.isfinite(self.next_eligible_at):
            raise ValueError("next_eligible_at must be finite")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")


def _default_tiers() -> dict[RecruitTier, PersistedTierState]:
    return {
        RecruitTier.BASIC: PersistedTierState(5, cooldown_seconds=600),
        RecruitTier.INT: PersistedTierState(1, cooldown_seconds=86_400),
        RecruitTier.ADV: PersistedTierState(1, cooldown_seconds=172_800),
    }


@dataclass
class NoahMaintenanceState:
    """Reset-scoped Basic count plus independent per-tier eligibility state."""

    account_id: str
    server_id: str
    reset_id: str
    basic_daily_count: int = 0
    tiers: dict[RecruitTier, PersistedTierState] = field(default_factory=_default_tiers)
    revision: int = 0

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.account_id, self.server_id, self.reset_id)):
            raise ValueError("maintenance state requires account, server, and reset identity")
        if not 0 <= self.basic_daily_count <= 5:
            raise ValueError("Basic Daily count must be between 0 and 5")
        for tier in RecruitTier:
            if tier not in self.tiers:
                self.tiers[tier] = PersistedTierState(
                    5 if tier is RecruitTier.BASIC else 1,
                    cooldown_seconds=TIER_COOLDOWN_SECONDS[tier],
                )

    @classmethod
    def for_identity(cls, identity: SchedulerIdentity) -> "NoahMaintenanceState":
        return cls(identity.account_id, identity.server_id, identity.reset_id)

    def identity(self) -> SchedulerIdentity:
        return SchedulerIdentity(self.account_id, self.server_id, self.reset_id, MAINTENANCE_TASK_ID)

    @classmethod
    def from_scheduler_invocation(cls, invocation) -> "NoahMaintenanceState":
        """Restore durable pass state from the existing scheduler invocation repository row."""

        progress = json.loads(invocation.observed_progress_json or "{}")
        tiers = {
            RecruitTier(key): PersistedTierState(**value)
            for key, value in progress.get("tiers", {}).items()
            if isinstance(value, dict)
        }
        return cls(
            invocation.identity.account_id,
            invocation.identity.server_id,
            invocation.identity.reset_id,
            basic_daily_count=int(progress.get("basic_daily_count", 0)),
            tiers=tiers,
            revision=int(invocation.revision),
        )

    def to_json(self) -> str:
        payload = {
            "schema": MAINTENANCE_STATE_SCHEMA,
            "account_id": self.account_id,
            "server_id": self.server_id,
            "reset_id": self.reset_id,
            "basic_daily_count": self.basic_daily_count,
            "revision": self.revision,
            "tiers": {
                tier.value: asdict(state)
                for tier, state in sorted(self.tiers.items(), key=lambda item: item[0].value)
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "NoahMaintenanceState":
        try:
            payload = json.loads(raw)
            if payload.get("schema") != MAINTENANCE_STATE_SCHEMA:
                raise ValueError("unsupported maintenance state schema")
            tiers = {
                RecruitTier(key): PersistedTierState(**value)
                for key, value in payload.get("tiers", {}).items()
            }
            return cls(
                account_id=str(payload["account_id"]),
                server_id=str(payload["server_id"]),
                reset_id=str(payload["reset_id"]),
                basic_daily_count=int(payload.get("basic_daily_count", 0)),
                tiers=tiers,
                revision=int(payload.get("revision", 0)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid Noah maintenance state") from exc


@dataclass(frozen=True)
class TierPassEvidence:
    """One tier's current frame, result overlay, and fresh post-close frame."""

    before: NoahTavernObservation
    result: Optional[NoahTavernObservation] = None
    after_close: Optional[NoahTavernObservation] = None
    transport_observed: bool = False


@dataclass(frozen=True)
class TierPassResult:
    tier: RecruitTier
    outcome: TierPassOutcome
    reason: str
    next_eligible_at: Optional[float] = None


@dataclass(frozen=True)
class NoahMaintenancePassResult:
    scheduler_result: SchedulerAwareTaskResult
    tier_results: tuple[TierPassResult, ...]
    terminal_home_verified: bool
    recruitment_dispatch_count: int
    verified_transition_count: int
    state: NoahMaintenanceState


def _home_terminal_verified(observation: NoahTavernObservation | None) -> bool:
    return bool(
        observation
        and observation.screen_state == HOME_BASE_SCREEN
        and observation.recognized
        and not observation.stale
        and observation.overlay_state in {"none", "none_observed"}
        and _HASH_RE.fullmatch(observation.frame_sha256 or "")
    )


class NoahTavernMaintenanceController:
    """Evaluate one complete three-tab pass; never dispatch transport."""

    def __init__(self, state: NoahMaintenanceState, *, now: float = 0.0) -> None:
        self.state = state
        self.now = now

    def current_tier_eligible(self, observation: NoahTavernObservation, tier: RecruitTier, *, now: float | None = None) -> bool:
        """Apply persisted ownership/cooldown policy to one fresh current-frame tier."""

        clock = self.now if now is None else now
        state = self.state.tiers[tier]
        if tier is RecruitTier.BASIC and self.state.basic_daily_count >= 5:
            return False
        if state.next_eligible_at is not None and state.next_eligible_at > clock:
            return False
        observed = observation.tier(tier)
        if state.attempts_remaining == 0:
            # A matured Int./Advanced cooldown re-arms only from fresh free-control evidence.
            if tier is RecruitTier.BASIC and self.state.basic_daily_count >= 5:
                return False
            auth_observation = replace(observation, selected_tier=tier)
            if observed.attempts_remaining and not observed.cooldown_active and noah_recruit_authorizeable(auth_observation, tier):
                self.state.tiers[tier] = PersistedTierState(observed.attempts_remaining, None, TIER_COOLDOWN_SECONDS[tier], "rearmed")
                return True
            return False
        auth_observation = replace(observation, selected_tier=tier)
        return bool(observed.attempts_remaining and not observed.cooldown_active and noah_recruit_authorizeable(auth_observation, tier))

    def tier_selectable(self, observation: NoahTavernObservation, tier: RecruitTier, *, now: float | None = None) -> bool:
        """Allow navigation to an independently recognized tab; free control is revalidated there."""

        clock = self.now if now is None else now
        state = self.state.tiers[tier]
        observed = observation.tier(tier)
        if tier is RecruitTier.BASIC and self.state.basic_daily_count >= 5:
            return False
        if state.next_eligible_at is not None and state.next_eligible_at > clock:
            return False
        return bool(observed.recognized and (state.attempts_remaining > 0 or observed.attempts_remaining))

    def record_verified_transition(self, tier: RecruitTier, after_close: NoahTavernObservation, *, now: float | None = None) -> None:
        """Persist one verified result transition from the executable controller path."""

        observed = after_close.tier(tier)
        clock = self.now if now is None else now
        self.state.tiers[tier] = PersistedTierState(
            observed.attempts_remaining or 0,
            clock + TIER_COOLDOWN_SECONDS[tier],
            TIER_COOLDOWN_SECONDS[tier],
            "action_performed",
        )
        if tier is RecruitTier.BASIC:
            self.state.basic_daily_count = min(5, self.state.basic_daily_count + 1)
        self.state.revision += 1

    def run_pass(
        self,
        evidence: Mapping[RecruitTier, TierPassEvidence],
        terminal_home: NoahTavernObservation | None,
        *,
        identity: SchedulerIdentity | None = None,
        now: float | None = None,
    ) -> NoahMaintenancePassResult:
        if now is not None:
            self.now = now
        maintenance_identity = identity or self.state.identity()
        if maintenance_identity.task_id not in {MAINTENANCE_TASK_ID, DAILY_RECRUITMENT_TASK_ID}:
            raise ValueError("unexpected scheduler task identity")
        if (maintenance_identity.account_id, maintenance_identity.server_id, maintenance_identity.reset_id) != (
            self.state.account_id,
            self.state.server_id,
            self.state.reset_id,
        ):
            raise ValueError("scheduler identity does not match persisted maintenance state")
        missing = [tier for tier in RecruitTier if tier not in evidence]
        if missing:
            return self._result(
                maintenance_identity,
                tuple(TierPassResult(tier, TierPassOutcome.BLOCKED, "tier_not_independently_inspected") for tier in missing),
                terminal_home,
                self.state,
                reason="all_three_tiers_required",
            )
        candidate = NoahMaintenanceState.from_json(self.state.to_json())
        tier_results: list[TierPassResult] = []
        action_count = 0
        blocked = False
        for tier in RecruitTier:
            item = evidence[tier]
            before = item.before
            if (
                before.screen_state != NOAHS_TAVERN_SCREEN
                or not before.recognized
                or before.stale
                or before.overlay_state not in {"none", "none_observed"}
            ):
                tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "tavern_source_not_proven"))
                blocked = True
                break
            selected = before.tier(tier)
            persisted = candidate.tiers[tier]
            if tier is RecruitTier.BASIC and candidate.basic_daily_count >= 5:
                tier_results.append(TierPassResult(tier, TierPassOutcome.ALREADY_COMPLETE, "basic_daily_maximum_reached"))
                persisted = PersistedTierState(persisted.attempts_remaining, persisted.next_eligible_at, 600, "already_complete")
                candidate.tiers[tier] = persisted
                continue
            # Persisted state is authoritative against stale/optimistic frame counts: never issue
            # a sixth Basic or replay an Int./Advanced single before its saved next eligibility.
            if persisted.attempts_remaining == 0:
                if persisted.next_eligible_at is not None and persisted.next_eligible_at > self.now:
                    tier_results.append(TierPassResult(tier, TierPassOutcome.DEFERRED, "persisted_tier_cooldown", persisted.next_eligible_at))
                    continue
                # Matured Int./Advanced cooldowns may re-arm from fresh positive free evidence.
                persisted = PersistedTierState(selected.attempts_remaining or 0, None, TIER_COOLDOWN_SECONDS[tier], "rearmed")
                candidate.tiers[tier] = persisted
                if not persisted.attempts_remaining:
                    tier_results.append(TierPassResult(tier, TierPassOutcome.ALREADY_COMPLETE, "persisted_tier_exhausted"))
                    continue
            if persisted.next_eligible_at is not None and persisted.next_eligible_at > self.now:
                tier_results.append(TierPassResult(tier, TierPassOutcome.DEFERRED, "persisted_next_eligibility", persisted.next_eligible_at))
                continue
            if selected.cooldown_active or selected.attempts_remaining == 0:
                next_at = selected.next_eligible_timestamp or persisted.next_eligible_at
                if next_at is None:
                    tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "cooldown_without_next_eligibility"))
                    blocked = True
                else:
                    tier_results.append(TierPassResult(tier, TierPassOutcome.DEFERRED, "tier_cooldown_active", next_at))
                    candidate.tiers[tier] = PersistedTierState(
                        max(0, selected.attempts_remaining or 0), next_at, TIER_COOLDOWN_SECONDS[tier], "deferred"
                    )
                continue
            if not noah_recruit_authorizeable(before, tier):
                tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "zero_cost_single_not_proven"))
                blocked = True
                break
            if item.transport_observed:
                tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "transport_forbidden_in_offline_replay"))
                blocked = True
                break
            if not noah_result_postcondition_verified(
                before,
                item.result,
                item.after_close,
                tier,
                require_daily_progress=False,
                cooldown_tolerance_seconds=30,
            ):
                tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "result_decrement_cooldown_not_proven"))
                blocked = True
                break
            after_tier = item.after_close.tier(tier)  # type: ignore[union-attr]
            observed_seconds = parse_cooldown_seconds(after_tier.cooldown_text)
            if (
                observed_seconds is None
                or observed_seconds > TIER_COOLDOWN_SECONDS[tier]
                or TIER_COOLDOWN_SECONDS[tier] - observed_seconds > 30
            ):
                tier_results.append(TierPassResult(tier, TierPassOutcome.BLOCKED, "exact_tier_cooldown_not_proven"))
                blocked = True
                break
            next_at = self.now + TIER_COOLDOWN_SECONDS[tier]
            candidate.tiers[tier] = PersistedTierState(
                after_tier.attempts_remaining or 0,
                next_at,
                TIER_COOLDOWN_SECONDS[tier],
                "action_performed",
            )
            if tier is RecruitTier.BASIC:
                candidate.basic_daily_count += 1
            action_count += 1
            tier_results.append(TierPassResult(tier, TierPassOutcome.ACTION_PERFORMED, "zero_transport_postcondition_verified", next_at))
        if blocked or not _home_terminal_verified(terminal_home):
            reason = "canonical_home_terminal_not_proven" if not _home_terminal_verified(terminal_home) else "tier_pass_blocked"
            return self._result(maintenance_identity, tuple(tier_results), terminal_home, self.state, reason=reason, action_count=0)
        candidate.revision += 1
        self.state = candidate
        return self._result(maintenance_identity, tuple(tier_results), terminal_home, candidate, reason="three_tab_maintenance_pass_verified", action_count=action_count)

    def _result(self, identity, tier_results, terminal_home, state, *, reason, action_count=0):
        terminal = _home_terminal_verified(terminal_home)
        blocked = any(item.outcome is TierPassOutcome.BLOCKED for item in tier_results) or not terminal
        deferred = any(item.outcome is TierPassOutcome.DEFERRED for item in tier_results)
        scheduled_tiers = [tier for tier in RecruitTier if not (tier is RecruitTier.BASIC and state.basic_daily_count >= 5)]
        next_due = min(
            (state.tiers[tier].next_eligible_at for tier in scheduled_tiers if state.tiers[tier].next_eligible_at is not None),
            default=None,
        )
        progress = {
            "basic_daily_count": state.basic_daily_count,
            "tiers": {
                tier.value: {
                    "attempts_remaining": state.tiers[tier].attempts_remaining,
                    "next_eligible_at": state.tiers[tier].next_eligible_at,
                    "cooldown_seconds": state.tiers[tier].cooldown_seconds,
                    "last_outcome": state.tiers[tier].last_outcome,
                }
                for tier in RecruitTier
            },
            "terminal_home_verified": terminal,
        }
        if blocked:
            scheduler_result = SchedulerAwareTaskResult.blocked(identity, reason, observed_progress=progress, action_count=0)
        elif action_count:
            # Replay records verified intended transitions, never runtime actions.  A deferred
            # scheduler result carries the next eligibility without inflating action accounting.
            scheduler_result = SchedulerAwareTaskResult.deferred(
                identity,
                reason,
                next_due or self.now,
                observed_progress=progress,
                intended_actions=tuple(f"RECRUIT_FREE:{tier.value}" for tier in RecruitTier if any(r.tier is tier and r.outcome is TierPassOutcome.ACTION_PERFORMED for r in tier_results)),
                dispatched_actions=(),
                consequence={"transport_observed": False, "claim_dispatched": False},
            )
        elif deferred:
            scheduler_result = SchedulerAwareTaskResult.deferred(identity, reason, next_due or self.now, observed_progress=progress)
        else:
            scheduler_result = SchedulerAwareTaskResult.already_complete(identity, reason, observed_progress=progress)
        return NoahMaintenancePassResult(scheduler_result, tuple(tier_results), terminal, 0, action_count, state)


def replay_noahs_tavern_maintenance(
    state_json: str,
    evidence: Mapping[RecruitTier, TierPassEvidence],
    terminal_home: NoahTavernObservation | None,
    *,
    identity: SchedulerIdentity,
    now: float,
    repository=None,
) -> tuple[NoahMaintenancePassResult, str]:
    """Production-shaped zero-transport replay with explicit persistence round trip."""

    state = NoahMaintenanceState.from_json(state_json)
    controller = NoahTavernMaintenanceController(state, now=now)
    result = controller.run_pass(evidence, terminal_home, identity=identity, now=now)
    if repository is not None:
        repository.apply_result(result.scheduler_result, now)
    return result, controller.state.to_json()


def rollover_maintenance_state(state: NoahMaintenanceState, new_reset_id: str) -> NoahMaintenanceState:
    """Rollover only Basic Daily ownership; retain Int./Advanced cooldown state."""

    if not new_reset_id.strip() or new_reset_id == state.reset_id:
        raise ValueError("new reset identity is required")
    retained = dict(state.tiers)
    retained[RecruitTier.BASIC] = PersistedTierState(5, None, TIER_COOLDOWN_SECONDS[RecruitTier.BASIC], "reset_rollover")
    return NoahMaintenanceState(
        state.account_id,
        state.server_id,
        new_reset_id,
        basic_daily_count=0,
        tiers=retained,
        revision=state.revision + 1,
    )


def rollover_persisted_maintenance_state(state: NoahMaintenanceState, new_reset_id: str, repository, updated_at: float) -> NoahMaintenanceState:
    """Write a new-reset invocation row through the existing repository, retaining long cooldowns."""

    rolled = rollover_maintenance_state(state, new_reset_id)
    identity = rolled.identity()
    progress = {
        "basic_daily_count": rolled.basic_daily_count,
        "tiers": {tier.value: asdict(rolled.tiers[tier]) for tier in RecruitTier},
        "terminal_home_verified": False,
    }
    repository.save(
        SchedulerInvocationState(
            identity=identity,
            status="deferred",
            revision=rolled.revision,
            next_eligible_at=min((item.next_eligible_at for item in rolled.tiers.values() if item.next_eligible_at is not None), default=None),
            last_reason_code="reset_rollover_basic_only",
            observed_progress_json=json.dumps(progress, sort_keys=True),
            action_count_total=0,
            unresolved_action=False,
            evidence_refs_json="[]",
        ),
        updated_at,
    )
    return rolled
