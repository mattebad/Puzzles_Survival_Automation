"""Deterministic, dormant controller for the Noah's Tavern Daily Free workflow."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional

from .noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NoahTavernObservation,
    DailyQuestProgress,
    RecruitTier,
    TierState,
    noah_recruit_authorizeable,
    noah_result_postcondition_verified,
    update_progress,
)
from .noahs_tavern_recruit_vision import TAVERN_FREE_ROI, TAVERN_CARDS_ROI
from .noahs_tavern_recruit_maintenance import (
    NoahMaintenanceState,
    NoahMaintenancePassResult,
    NoahTavernMaintenanceController,
    TierPassEvidence,
)
from .scheduler_task_result import SchedulerAwareTaskResult, SchedulerIdentity


class NoahAction(str, Enum):
    OPEN_TAVERN = "OPEN_TAVERN"
    SELECT_TIER = "SELECT_TIER"
    RECRUIT_FREE = "RECRUIT_FREE"
    CLOSE_RESULT = "CLOSE_RESULT"
    WAIT_COOLDOWN = "WAIT_COOLDOWN"
    RETURN_HOME = "RETURN_HOME"
    STOP = "STOP"


@dataclass(frozen=True)
class NoahCommand:
    action: NoahAction
    target_identity: Optional[str] = None
    target_roi: Optional[tuple[int, int, int, int]] = None
    tier: Optional[RecruitTier] = None
    terminal: bool = False
    scheduler_ready: bool = False
    reason: str = ""
    next_eligible_timestamp: Optional[float] = None
    action_key: Optional[str] = None


@dataclass
class NoahRecruitProgress:
    daily_quest: DailyQuestProgress = field(default_factory=DailyQuestProgress)
    tiers: dict[RecruitTier, TierState] = field(default_factory=dict)
    inspected_tiers: set[RecruitTier] = field(default_factory=set)
    dispatched_action_keys: set[str] = field(default_factory=set)
    seen_frame_hashes: set[str] = field(default_factory=set)
    awaiting_postcondition: bool = False
    awaiting_tier: Optional[RecruitTier] = None
    awaiting_before: Optional[NoahTavernObservation] = None
    result_observed: bool = False
    last_dispatch_state: str = "none"


class NoahTavernRecruitRuntimeController:
    """One-command-at-a-time state machine with no Claim or scheduler promotion path."""

    def __init__(self, *, now: float = 0.0, maintenance_state: NoahMaintenanceState | None = None, repository=None, scheduler_identity: SchedulerIdentity | None = None) -> None:
        self.now = now
        self.progress = NoahRecruitProgress()
        self.maintenance_controller = NoahTavernMaintenanceController(
            maintenance_state or NoahMaintenanceState("offline-account", "offline-server", "offline-reset"),
            now=now,
        )
        self.repository = repository
        self.scheduler_identity = scheduler_identity

    def persist_maintenance_state(self, *, now: float | None = None) -> None:
        """Persist current verified maintenance progress through the existing repository seam."""

        if self.repository is None or self.scheduler_identity is None:
            return
        state = self.maintenance_controller.state
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
            "terminal_home_verified": False,
        }
        self.repository.apply_result(
            SchedulerAwareTaskResult.deferred(
                self.scheduler_identity,
                "verified_transition_persisted",
                min((item.next_eligible_at for item in state.tiers.values() if item.next_eligible_at is not None), default=now or self.now),
                observed_progress=progress,
            ),
            now or self.now,
        )

    def run_maintenance_pass(
        self,
        evidence: dict[RecruitTier, TierPassEvidence],
        terminal_home: NoahTavernObservation | None,
        *,
        identity: SchedulerIdentity | None = None,
        now: float | None = None,
    ) -> NoahMaintenancePassResult:
        """Delegate the integrated route's maintenance decision to the shared policy engine."""

        return self.maintenance_controller.run_pass(evidence, terminal_home, identity=identity, now=now)

    def _stop(self, reason: str) -> NoahCommand:
        return NoahCommand(NoahAction.STOP, terminal=True, reason=reason)

    def _remember_tier(self, observation: NoahTavernObservation, tier: RecruitTier) -> None:
        item = observation.tier(tier)
        if item.attempts_remaining is None:
            return
        self.progress.inspected_tiers.add(tier)
        prior = self.progress.tiers.get(tier)
        self.progress.tiers[tier] = TierState(
            tier=tier,
            daily_attempt_maximum=item.daily_attempt_maximum,
            attempts_remaining=item.attempts_remaining,
            cooldown_duration_seconds=item.cooldown_duration_seconds or (prior.cooldown_duration_seconds if prior else None),
            cooldown_active=item.cooldown_active,
            next_eligible_timestamp=item.next_eligible_timestamp,
            last_dispatch_state=prior.last_dispatch_state if prior else "never_dispatched",
            last_postcondition_state=prior.last_postcondition_state if prior else "not_observed",
        )

    def _eligible_tiers(self) -> list[RecruitTier]:
        result = []
        for tier in RecruitTier:
            state = self.progress.tiers.get(tier)
            if state and state.attempts_remaining and not state.cooldown_active:
                result.append(tier)
        return result

    def next_command(self, recognition, *, now: float | None = None) -> NoahCommand:
        if now is not None:
            self.now = now
        obs: NoahTavernObservation = recognition.observation
        if not obs.recognized or obs.screen_state == "UNKNOWN" or obs.stale:
            return self._stop("unknown_or_stale_noahs_tavern_state")
        if obs.screen_state == HOME_BASE_SCREEN:
            if obs.home_tavern_target_roi is None:
                return self._stop("home_tavern_target_not_current_frame_bound")
            return NoahCommand(NoahAction.OPEN_TAVERN, "noahs-tavern-building", obs.home_tavern_target_roi, reason="recognized_home_base")
        if obs.screen_state == HERO_RECRUIT_RESULT_SCREEN:
            if not self.progress.awaiting_postcondition or self.progress.awaiting_tier is None:
                return self._stop("unexpected_recruit_result_without_dispatch")
            if not obs.safe_close_visible or not obs.result_identity.strip():
                return self._stop("unknown_or_ambiguous_recruit_result_close")
            self.progress.result_observed = True
            return NoahCommand(NoahAction.CLOSE_RESULT, "noahs-tavern-result-close", obs.safe_close_roi, tier=self.progress.awaiting_tier, reason="recognized_safe_close")
        if self.progress.awaiting_postcondition:
            return self._stop("awaiting_fresh_recruit_postcondition")
        if obs.screen_state != NOAHS_TAVERN_SCREEN or obs.overlay_state not in {"none", "none_observed"}:
            return self._stop("unknown_or_overlaid_noahs_tavern_screen")
        # Daily-row Claim readiness is deliberately separate from this maintenance pass.
        # It must never terminate tier inspection: Basic owns the reset-scoped five count,
        # while independently eligible Int./Advanced singles remain actionable.
        if not obs.selected_tier:
            return self._stop("missing_selected_tier")
        self._remember_tier(obs, obs.selected_tier)
        # Shared persisted policy is authoritative for executable decisions. A stale frame cannot
        # bypass Basic's five-count cap or an Int./Advanced cooldown.
        if not self.maintenance_controller.current_tier_eligible(obs, obs.selected_tier, now=self.now):
            for tier in RecruitTier:
                legacy = self.progress.tiers.get(tier)
                if legacy and (legacy.cooldown_active or (legacy.next_eligible_timestamp is not None and legacy.next_eligible_timestamp > self.now) or not legacy.attempts_remaining):
                    continue
                if tier != obs.selected_tier and self.maintenance_controller.tier_selectable(obs, tier, now=self.now):
                    item = obs.tier(tier)
                    return NoahCommand(NoahAction.SELECT_TIER, item.target_identity, item.target_roi, tier=tier, reason="select_next_shared_policy_eligible_tier")
            cooldowns = [
                item.next_eligible_timestamp
                for item in obs.tiers
                if item.cooldown_active and item.next_eligible_timestamp is not None and item.next_eligible_timestamp > self.now
            ]
            cooldowns.extend(
                state.next_eligible_timestamp
                for state in self.progress.tiers.values()
                if state.cooldown_active and state.next_eligible_timestamp is not None and state.next_eligible_timestamp > self.now
            )
            if cooldowns:
                return NoahCommand(NoahAction.WAIT_COOLDOWN, scheduler_ready=True, next_eligible_timestamp=min(cooldowns), reason="all_shared_policy_tiers_deferred")
            return self._stop("no_shared_policy_eligible_free_tier")
        current = self.progress.tiers.get(obs.selected_tier)
        if current and current.attempts_remaining and not current.cooldown_active:
            if recognition.frame_sha256 in self.progress.seen_frame_hashes:
                return self._stop("duplicate_frame_dispatch_guard")
            action_key = f"{obs.selected_tier.name}:{recognition.frame_sha256}:{current.attempts_remaining}:{current.next_eligible_timestamp}"
            if action_key in self.progress.dispatched_action_keys:
                return self._stop("duplicate_action_key_guard")
            if not noah_recruit_authorizeable(obs, obs.selected_tier):
                return self._stop("free_control_disabled_or_premium_ambiguous")
            self.progress.awaiting_postcondition = True
            self.progress.awaiting_tier = obs.selected_tier
            self.progress.awaiting_before = obs
            self.progress.dispatched_action_keys.add(action_key)
            self.progress.seen_frame_hashes.add(recognition.frame_sha256)
            self.progress.last_dispatch_state = "dispatched_awaiting_result"
            return NoahCommand(
                NoahAction.RECRUIT_FREE,
                "noahs-tavern-daily-free",
                TAVERN_FREE_ROI,
                tier=obs.selected_tier,
                reason="one_zero_cost_free_recruit",
                action_key=action_key,
            )
        known_uninspected = [tier for tier in RecruitTier if tier not in self.progress.inspected_tiers and obs.tier(tier).recognized]
        if known_uninspected:
            tier = known_uninspected[0]
            item = obs.tier(tier)
            return NoahCommand(NoahAction.SELECT_TIER, item.target_identity, item.target_roi, tier=tier, reason="inspect_next_visible_tier")
        eligible = self._eligible_tiers()
        if eligible:
            tier = eligible[0]
            item = obs.tier(tier)
            return NoahCommand(NoahAction.SELECT_TIER, item.target_identity, item.target_roi, tier=tier, reason="select_next_eligible_tier")
        timestamps = [state.next_eligible_timestamp for state in self.progress.tiers.values() if state.next_eligible_timestamp and state.next_eligible_timestamp > self.now]
        if len(self.progress.inspected_tiers) == len(RecruitTier) and timestamps:
            next_at = min(timestamps)
            return NoahCommand(NoahAction.WAIT_COOLDOWN, scheduler_ready=True, next_eligible_timestamp=next_at, reason="all_known_tiers_in_cooldown")
        return self._stop("no_authorized_free_tier")

    def accept_postcondition(self, result_recognition, after_close: NoahTavernObservation) -> bool:
        """Accept only a result plus a fresh post-close Tavern frame proving all invariants."""

        if not self.progress.awaiting_postcondition or self.progress.awaiting_before is None or self.progress.awaiting_tier is None:
            return False
        result: NoahTavernObservation = result_recognition.observation
        tier = self.progress.awaiting_tier
        if result.result_tier is None:
            result = result.__class__(**{**result.__dict__, "result_tier": tier})
        if not noah_result_postcondition_verified(
            self.progress.awaiting_before,
            result,
            after_close,
            tier,
            require_daily_progress=False,
            require_attempt_decrement=False,
        ):
            self.progress.last_dispatch_state = "postcondition_unresolved"
            return False
        normalized_after = after_close
        after_tier = after_close.tier(tier)
        if after_tier.attempts_remaining is None:
            before_remaining = self.progress.awaiting_before.tier(tier).attempts_remaining
            if before_remaining is None or before_remaining <= 0:
                self.progress.last_dispatch_state = "postcondition_unresolved"
                return False
            normalized_tier = replace(after_tier, attempts_remaining=before_remaining - 1)
            normalized_after = replace(
                after_close,
                tiers=tuple(normalized_tier if item.tier == tier else item for item in after_close.tiers),
            )
        self._remember_tier(normalized_after, tier)
        self.progress.daily_quest.recruits_completed += 1
        self.progress.daily_quest.claim_dormant = True
        state = self.progress.tiers[tier]
        self.progress.tiers[tier] = TierState(
            tier=tier,
            daily_attempt_maximum=state.daily_attempt_maximum,
            attempts_remaining=state.attempts_remaining,
            cooldown_duration_seconds=state.cooldown_duration_seconds,
            cooldown_active=state.cooldown_active,
            next_eligible_timestamp=state.next_eligible_timestamp,
            last_dispatch_state="completed",
            last_postcondition_state="verified",
        )
        self.maintenance_controller.record_verified_transition(tier, normalized_after, now=after_close.captured_monotonic or self.now)
        self.persist_maintenance_state(now=after_close.captured_monotonic or self.now)
        self.progress.awaiting_postcondition = False
        self.progress.awaiting_tier = None
        self.progress.awaiting_before = None
        self.progress.result_observed = False
        return True
