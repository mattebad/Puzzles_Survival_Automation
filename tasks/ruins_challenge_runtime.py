"""Fail-closed Ruins Challenge controller/state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .ruins_challenge import (
    RuinsChallengeRow,
    RuinsDailyState,
    RuinsDetailObservation,
    RuinsDispatchState,
    RuinsResult,
    RuinsResultObservation,
    RuinsScreenObservation,
    challenge_action_authorized,
    chest_claim_authorized,
    chest_claim_postcondition_verified,
    detail_attack_authorized,
    dispatch_authorized,
    result_verified,
)


class RuinsRuntimeState(str, Enum):
    HOME = "home"
    ENTER_RUINS = "enter_ruins"
    RUINS_LIST = "ruins_list"
    DETAIL = "detail"
    DISPATCH = "dispatch"
    AWAIT_RESULT = "await_result"
    RECONCILE = "reconcile"
    CLAIM_CHEST = "claim_chest"
    RETURN_HOME = "return_home"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RuinsRuntimeCommand:
    kind: str
    identity: str
    reason: str
    action_key: str
    terminal: bool = False


class RuinsRuntimeController:
    """One-pulse controller with independent challenge/chest ledgers and duplicate guards."""

    def __init__(
        self,
        *,
        reset_identity: str,
        required_challenges: int = 1,
        allow_optional_second: bool = False,
    ) -> None:
        if not reset_identity:
            raise ValueError("Ruins controller requires a reset identity")
        self.reset_identity = reset_identity
        self.allow_optional_second = allow_optional_second
        self.state = RuinsRuntimeState.HOME
        self.daily = RuinsDailyState(required_challenges=required_challenges)
        self.rows: dict[str, RuinsChallengeRow] = {}
        self.challenge_action_keys: set[str] = set()
        self.challenge_identities_attempted: set[str] = set()
        self.chest_action_keys: set[str] = set()
        self.frame_hashes: set[str] = set()
        self.in_flight_action: str | None = None
        self.unresolved_reason: str | None = None

    def observe_list(self, observation: RuinsScreenObservation) -> None:
        if observation.reset_identity != self.reset_identity:
            self.state = RuinsRuntimeState.BLOCKED
            self.unresolved_reason = "reset identity changed"
            return
        if not observation.recognized or observation.screen_identity != "RUINS_CHALLENGE":
            self.state = RuinsRuntimeState.BLOCKED
            self.unresolved_reason = "unknown Ruins screen"
            return
        self.rows.update({row.identity: row for row in observation.rows})
        self.frame_hashes.add(observation.source_frame_sha256)
        self.state = RuinsRuntimeState.RUINS_LIST

    def plan_challenge(
        self,
        observation: RuinsScreenObservation,
        row: RuinsChallengeRow,
        *,
        current_day: str,
        action_key: str,
    ) -> RuinsRuntimeCommand:
        if self.in_flight_action is not None:
            return RuinsRuntimeCommand("blocked", row.identity, "prior action unresolved", action_key, True)
        if self.daily.initiation_complete and not self.allow_optional_second:
            return RuinsRuntimeCommand("blocked", row.identity, "daily initiation complete", action_key, True)
        if row.identity in self.challenge_identities_attempted:
            return RuinsRuntimeCommand("blocked", row.identity, "challenge identity already attempted", action_key, True)
        if not challenge_action_authorized(
            observation,
            row,
            current_day=current_day,
            action_key=action_key,
            seen_action_keys=self.challenge_action_keys,
            # The current immediate-before frame is safe evidence for this action.  Only
            # prior frames are duplicate evidence; rejecting the current hash would make
            # every freshly observed target fail closed for the wrong reason.
            seen_frame_hashes=self.frame_hashes - {observation.source_frame_sha256},
        ):
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", row.identity, "challenge authorization failed", action_key, True)
        self.challenge_action_keys.add(action_key)
        self.challenge_identities_attempted.add(row.identity)
        self.in_flight_action = action_key
        self.state = RuinsRuntimeState.DETAIL
        return RuinsRuntimeCommand("open_detail", row.identity, "fresh available current-day challenge", action_key)

    def plan_attack(self, detail: RuinsDetailObservation, *, action_key: str) -> RuinsRuntimeCommand:
        if self.in_flight_action != action_key or not detail_attack_authorized(detail):
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", detail.identity, "detail attack authorization failed", action_key, True)
        self.state = RuinsRuntimeState.DISPATCH
        return RuinsRuntimeCommand("attack", detail.identity, "zero-cost NPC challenge detail", action_key)

    def plan_dispatch(self, detail: RuinsDetailObservation, *, action_key: str) -> RuinsRuntimeCommand:
        if self.in_flight_action != action_key or not dispatch_authorized(detail):
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", detail.identity, "dispatch authorization failed", action_key, True)
        self.state = RuinsRuntimeState.AWAIT_RESULT
        return RuinsRuntimeCommand("dispatch", detail.identity, "NPC troops provided; no resource cost", action_key)

    def reconcile_result(self, before: RuinsChallengeRow, result: RuinsResultObservation) -> RuinsRuntimeCommand:
        if self.in_flight_action is None or before.identity not in self.rows:
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", before.identity, "no matching in-flight challenge", "", True)
        if result.result == RuinsResult.AMBIGUOUS or not result_verified(before, result):
            self.state = RuinsRuntimeState.BLOCKED
            self.unresolved_reason = "ambiguous or unverified challenge result"
            return RuinsRuntimeCommand("blocked", before.identity, self.unresolved_reason, self.in_flight_action, True)
        self.rows[before.identity] = RuinsChallengeRow(
            **{**before.__dict__,
               "progress_current": result.progress_after if result.progress_after is not None else before.progress_current,
               "last_successful_level": result.level_after if result.result == RuinsResult.SUCCESS else before.last_successful_level,
               "last_dispatch_state": RuinsDispatchState.CONFIRMED,
               "last_postcondition_state": result.result.value},
        )
        self.daily.challenge_initiations_completed += 1
        if result.result == RuinsResult.SUCCESS:
            self.daily.successful_challenges_completed += 1
        self.in_flight_action = None
        self.state = RuinsRuntimeState.RUINS_LIST
        return RuinsRuntimeCommand("reconciled", before.identity, result.result.value, "", terminal=False)

    def plan_chest_claim(self, observation: RuinsScreenObservation, row: RuinsChallengeRow, *, action_key: str) -> RuinsRuntimeCommand:
        if self.in_flight_action is not None:
            return RuinsRuntimeCommand("blocked", row.identity, "prior action unresolved", action_key, True)
        if not chest_claim_authorized(observation, row, action_key=action_key, seen_action_keys=self.chest_action_keys):
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", row.identity, "chest authorization failed", action_key, True)
        self.chest_action_keys.add(action_key)
        self.in_flight_action = action_key
        self.state = RuinsRuntimeState.CLAIM_CHEST
        return RuinsRuntimeCommand("claim_chest", row.identity, "exact available Ruins chest", action_key)

    def reconcile_chest(self, before: RuinsChallengeRow, after: RuinsChallengeRow, *, action_key: str) -> RuinsRuntimeCommand:
        if self.in_flight_action != action_key or not chest_claim_postcondition_verified(before, after):
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", before.identity, "chest postcondition unresolved", action_key, True)
        self.rows[before.identity] = after
        self.in_flight_action = None
        self.state = RuinsRuntimeState.RUINS_LIST
        return RuinsRuntimeCommand("chest_reconciled", before.identity, "claimed exactly once", "")

    def finish(self) -> RuinsRuntimeCommand:
        if self.in_flight_action is not None or self.unresolved_reason:
            self.state = RuinsRuntimeState.BLOCKED
            return RuinsRuntimeCommand("blocked", "", "unresolved action remains", self.in_flight_action or "", True)
        self.state = RuinsRuntimeState.RETURN_HOME
        return RuinsRuntimeCommand("return_home", "Home/Base", "Ruins work complete", "return-home")
