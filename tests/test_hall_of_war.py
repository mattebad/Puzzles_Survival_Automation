from __future__ import annotations

import pytest

from tasks.hall_of_war import (
    Action,
    AttemptState,
    ChallengeObservation,
    CostState,
    RewardObservation,
    RewardState,
    action_key,
    aggregate_action_count,
    plan_dispatch,
    plan_reward,
)


FRAME = "a" * 64
COST_ROI = "b" * 64
LOSS_ROI = "c" * 64


def challenge(**overrides):
    facts = dict(
        page_identity="ZOMBIE_ZERO",
        page_exact=True,
        attempt=AttemptState.READY,
        cost=CostState.EXPLICIT_ZERO,
        cost_amount=0,
        saved_military_verified=True,
        troop_set_one_selected=True,
        troop_set_one_applied=True,
        five_heroes_populated=True,
        current_troops=160200,
        troop_capacity=160200,
        cost_roi_sha256=COST_ROI,
        loss_effect_known_and_approved=True,
        loss_roi_sha256=LOSS_ROI,
        today_highest_damage=0,
        attempt_source_frame_sha256=FRAME,
        dispatch_page_identity="ZOMBIE_ZERO_DISPATCH",
        dispatch_page_exact=True,
        attempt_ordinal=1,
        source_frame_sha256=FRAME,
    )
    facts.update(overrides)
    return ChallengeObservation(**facts)


def test_dispatch_requires_every_explicit_current_gate():
    assert plan_dispatch(challenge(), saved_military_verified=True).action is Action.DISPATCH
    rejected = (
        {"cost": CostState.UNKNOWN, "cost_amount": None, "cost_roi_sha256": None},
        {"cost": CostState.NONZERO, "cost_amount": 1},
        {"loss_effect_known_and_approved": False, "loss_roi_sha256": None},
        {"saved_military_verified": False},
        {"troop_set_one_selected": False},
        {"five_heroes_populated": False},
        {"current_troops": 160199},
        {"current_troops": None},
        {"today_highest_damage": None},
    )
    for change in rejected:
        result = plan_dispatch(challenge(**change), saved_military_verified=True)
        assert result.action is Action.BLOCKED


def test_dispatch_busy_unavailable_and_prior_same_reset_use_are_not_actions():
    assert plan_dispatch(challenge(attempt=AttemptState.BUSY), saved_military_verified=True).action is Action.NO_WORK
    assert plan_dispatch(challenge(attempt=AttemptState.UNAVAILABLE), saved_military_verified=True).action is Action.NO_WORK
    assert plan_dispatch(challenge(today_highest_damage=321), saved_military_verified=True).action is Action.NO_WORK


def test_reward_row_is_independent_and_never_fabricates_claim_state():
    ready = RewardObservation("ZOMBIE_ZERO", True, RewardState.READY, True, False, FRAME)
    assert plan_reward(ready, same_reset_participation_proven=True).action is Action.CLAIM_REWARD
    assert plan_reward(ready, same_reset_participation_proven=False).action is Action.BLOCKED
    claimed = RewardObservation("ZOMBIE_ZERO", True, RewardState.CLAIMED, False, True, FRAME)
    assert plan_reward(claimed, same_reset_participation_proven=True).action is Action.NO_WORK
    unavailable = RewardObservation("ZOMBIE_ZERO", True, RewardState.UNAVAILABLE, False, False, FRAME)
    assert plan_reward(unavailable, same_reset_participation_proven=True).action is Action.NO_WORK


def test_reset_and_ordinal_are_bound_into_independent_action_keys():
    values = dict(runtime_scope="scope", account_id="account", server_id="server")
    dispatch = action_key(category="dispatch", reset_id="game-day-2025-01-02", **values)
    reward = action_key(category="reward", reset_id="game-day-2025-01-02", **values)
    next_reset = action_key(category="dispatch", reset_id="game-day-2025-01-03", **values)
    assert dispatch.startswith("hall-of-war:dispatch:daily:game-day-2025-01-02:attempt-1:")
    assert reward.startswith("hall-of-war:reward:daily:game-day-2025-01-02:claim-1:")
    assert len({dispatch, reward, next_reset}) == 3


def test_aggregate_counts_dispatch_reward_and_any_switch_effect():
    assert aggregate_action_count(dispatch_transport_calls=1, reward_claim_transport_calls=1) == 2
    assert aggregate_action_count(
        dispatch_transport_calls=0, reward_claim_transport_calls=0, talent_switch_transport_calls=1
    ) == 1
    with pytest.raises(ValueError):
        aggregate_action_count(dispatch_transport_calls=2, reward_claim_transport_calls=0)
