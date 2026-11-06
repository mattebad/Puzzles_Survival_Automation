from __future__ import annotations

from dataclasses import replace
import unittest

from safe_action_core.models import ActionClass, Observation, PolicyDecision, PolicyRequest
from safe_action_core.policy import (
    CAMPAIGN_AP_COSTS,
    CAMPAIGN_AP_FLOW_ID,
    CAMPAIGN_AP_PRODUCT_REVISION,
    CentralPolicy,
)
from tasks.campaign_auto_battle import CAMPAIGN_STAGE_COSTS, CampaignRouteProgress
from tasks.campaign_ap_challenge import (
    CampaignApRouteResult,
    campaign_ap_challenge_policy_request,
    campaign_ap_drain_verified,
    campaign_ap_effect_verified,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
FLOW_ID = CAMPAIGN_AP_FLOW_ID


def _observation(**changes):
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="CAMPAIGN_STAGE_DIALOG",
        overlay_state="none_observed",
        target_identity="campaign-challenge-1-15-9",
        target_roi=(119, 842, 365, 921),
        recognized=True,
        control_class="CHALLENGE",
        consequence="campaign_ap_auto_battle",
        cost_type="AP",
        cost_amount=14,
        quantity=1,
        expected_postcondition="CAMPAIGN_HERO_LINEUP",
        target_isolated=True,
        package_foreground=True,
    )
    return replace(base, **changes)


def _base_request(observation=None, **changes):
    base = PolicyRequest(
        action_id="campaign-action-1",
        action_key="campaign:1-15-9:entry:1",
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action="dispatch_campaign_ap_auto_battle",
        expected_runtime_profile_id=PROFILE_ID,
        observation=observation or _observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="campaign-runner",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        game_day_id="game-day-2026-10-29",
    )
    return replace(base, **changes)


def _request(*, stage="1-15-9", current_ap=114, target_roi=(119, 842, 365, 921)):
    observation = _observation(
        target_identity=f"campaign-challenge-{stage}",
        cost_amount=CAMPAIGN_AP_COSTS[stage],
        target_roi=target_roi,
    )
    return campaign_ap_challenge_policy_request(
        _base_request(observation),
        stage_identity=stage,
        current_ap=current_ap,
        target_roi=target_roi,
    )


class CampaignApChallengePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CentralPolicy({FLOW_ID})

    def test_stage_challenge_is_authorized_as_entry_only(self):
        result = self.policy.evaluate(_request())
        self.assertEqual(result.decision, PolicyDecision.AUTHORIZE)
        self.assertEqual(result.reason_code, "AUTHORIZED_CAMPAIGN_AP_ENTRY")

    def test_all_current_story_destinations_bind_exact_costs(self):
        for stage, current_ap in (("1-15-9", 14), ("1-20-9", 16), ("2-2-9", 20)):
            with self.subTest(stage=stage):
                result = self.policy.evaluate(_request(stage=stage, current_ap=current_ap))
                self.assertEqual(result.reason_code, "AUTHORIZED_CAMPAIGN_AP_ENTRY")

    def test_ap_balance_must_cover_cost_and_stay_bounded(self):
        self.assertEqual(
            self.policy.evaluate(_request(stage="1-15-9", current_ap=13)).reason_code,
            "CAMPAIGN_AP_BALANCE_INSUFFICIENT",
        )
        with self.assertRaises(ValueError):
            _request(stage="1-15-9", current_ap=121)

    def test_policy_cost_table_matches_native_route_authority(self):
        self.assertEqual(CAMPAIGN_AP_COSTS, CAMPAIGN_STAGE_COSTS)

    def test_request_factory_does_not_promote_wrong_observation(self):
        for observation in (
            _observation(source_state="HOME_BASE"),
            _observation(target_identity="campaign-challenge-1-20-9"),
            _observation(cost_amount=16),
            _observation(control_class="BLITZ"),
            _observation(expected_postcondition="CAMPAIGN_BATTLE"),
            _observation(recognized=False),
        ):
            with self.subTest(observation=observation):
                with self.assertRaises(ValueError):
                    campaign_ap_challenge_policy_request(
                        _base_request(observation),
                        stage_identity="1-15-9",
                        current_ap=114,
                        target_roi=(119, 842, 365, 921),
                    )

    def test_request_factory_preserves_exact_recognized_observation(self):
        observation = _observation()
        request = campaign_ap_challenge_policy_request(
            _base_request(observation),
            stage_identity="1-15-9",
            current_ap=114,
            target_roi=(119, 842, 365, 921),
        )
        self.assertIs(request.observation, observation)

    def test_exact_product_flow_target_and_successor_are_required(self):
        request = _request()
        cases = (
            (replace(request, task_id="OTHER"), "TASK_NOT_ENABLED"),
            (replace(request, action_kind="other-v1"), "CAMPAIGN_AP_PRODUCT_REVISION_MISMATCH"),
            (replace(request, subject="1-20-9"), "CAMPAIGN_AP_ACTION_NOT_EXACT"),
            (replace(request, observation=_observation(target_identity="generic-campaign")), "CAMPAIGN_AP_ACTION_NOT_EXACT"),
            (replace(request, observation=_observation(expected_postcondition="CAMPAIGN_BATTLE")), "CAMPAIGN_AP_ACTION_NOT_EXACT"),
        )
        for candidate, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(self.policy.evaluate(candidate).reason_code, reason)

    def test_no_refill_or_extra_effect_marker_is_required(self):
        request = _request()
        for preconditions in (
            ("campaign_ap_product=campaign_ap", "campaign_ap_current_ap=114", "campaign_ap_effect_ordinal=1"),
            ("campaign_ap_product=wrong", "campaign_ap_current_ap=114", "campaign_ap_no_refill", "campaign_ap_effect_ordinal=1"),
            ("campaign_ap_product=campaign_ap", "campaign_ap_current_ap=114", "campaign_ap_no_refill", "campaign_ap_effect_ordinal=2"),
        ):
            with self.subTest(preconditions=preconditions):
                self.assertEqual(
                    self.policy.evaluate(replace(request, semantic_preconditions=preconditions)).reason_code,
                    "CAMPAIGN_AP_BALANCE_NOT_EXACT",
                )

    def test_other_cost_bearing_controls_are_not_campaign_challenge(self):
        request = _request()
        for control in ("SWEEP", "BLITZ", "AUTO_COMPLETE", "ULTIMATE_CHALLENGE"):
            with self.subTest(control=control):
                candidate = replace(
                    request,
                    observation=_observation(control_class=control),
                )
                self.assertEqual(
                    self.policy.evaluate(candidate).reason_code,
                    "CAMPAIGN_AP_ACTION_NOT_EXACT",
                )

    def test_fresh_recognized_target_guards_remain_fail_closed(self):
        request = _request()
        for observation in (
            _observation(recognized=False),
            _observation(target_isolated=False),
            _observation(ambiguous=True),
            _observation(clipped=True),
            _observation(package_foreground=False),
            _observation(os_surface=True),
        ):
            with self.subTest(observation=observation):
                result = self.policy.evaluate(replace(request, observation=observation))
                self.assertIn(result.reason_code, {
                    "UNKNOWN_SOURCE",
                    "CAMPAIGN_AP_ACTION_NOT_EXACT",
                    "AMBIGUOUS_TARGET",
                    "CLIPPED_TARGET",
                    "CAMPAIGN_AP_HARD_STOP",
                })

    def test_legacy_spend_class_stays_disabled(self):
        request = _request()
        request = replace(request, action_class=ActionClass.SPEND_OR_STRATEGIC)
        self.assertEqual(self.policy.evaluate(request).reason_code, "SPEND_OR_STRATEGIC_DISABLED")


class CampaignApEffectTests(unittest.TestCase):
    def test_route_result_requires_explicit_proof_fields(self):
        with self.assertRaises(TypeError):
            CampaignApRouteResult(stage_identity="1-15-9", ap_before=114, ap_after=100)

    def test_effect_commits_only_after_exact_victory_delta_and_home(self):
        self.assertTrue(
            campaign_ap_effect_verified(
                CampaignApRouteResult(
                    stage_identity="1-15-9",
                    ap_before=114,
                    ap_after=100,
                    ap_regenerated=0,
                    battle_outcome="victory",
                    result_successor="CAMPAIGN_CHAPTER_MAP",
                    terminal_home="HOME_BASE",
                    effect_ordinal=1,
                    refill_seen=False,
                )
            )
        )
        for changes in (
            {"ap_after": 101},
            {"battle_outcome": "defeat"},
            {"result_successor": "CAMPAIGN_BATTLE"},
            {"terminal_home": "CAMPAIGN_TIER_MAP"},
            {"refill_seen": True},
            {"refill_seen": None},
            {"refill_seen": 0},
            {"effect_ordinal": 2},
        ):
            with self.subTest(changes=changes):
                result = CampaignApRouteResult(
                    stage_identity="1-15-9",
                    ap_before=114,
                    ap_after=100,
                    ap_regenerated=0,
                    battle_outcome="victory",
                    result_successor="CAMPAIGN_CHAPTER_MAP",
                    terminal_home="HOME_BASE",
                    effect_ordinal=1,
                    refill_seen=False,
                )
                result = replace(result, **changes)
                self.assertFalse(campaign_ap_effect_verified(result))


class CampaignApDrainTests(unittest.TestCase):
    def setUp(self):
        self.progress = CampaignRouteProgress(
            initial_ap=114, current_ap=5, completed_runs=8,
            ap_spent=112, ap_regenerated=3,
        )

    def verified(self, progress=None, *, stage="1-15-9", **changes):
        arguments = dict(battle_outcome="victory", result_successor_verified=True,
                         terminal_home_verified=True, refill_seen=False)
        arguments.update(changes)
        return campaign_ap_drain_verified(
            stage, self.progress if progress is None else progress, **arguments,
        )

    def test_multiple_victories_include_observed_regeneration_before_completion(self):
        self.assertTrue(self.verified())
        self.assertFalse(self.verified(replace(self.progress, ap_regenerated=0)))
        self.assertFalse(self.verified(replace(self.progress, current_ap=8)))

    def test_each_approved_stage_finishes_with_less_than_its_own_cost(self):
        for stage, cost in CAMPAIGN_STAGE_COSTS.items():
            with self.subTest(stage=stage):
                progress = CampaignRouteProgress(
                    initial_ap=4 * cost - 1, current_ap=cost - 1,
                    completed_runs=3, ap_spent=3 * cost,
                )
                self.assertTrue(self.verified(progress, stage=stage))
                still_affordable = replace(progress, initial_ap=4 * cost, current_ap=cost)
                self.assertFalse(self.verified(still_affordable, stage=stage))

    def test_one_and_twelve_verified_battles_can_finish_a_drain(self):
        for progress in (
            CampaignRouteProgress(initial_ap=14, current_ap=0, completed_runs=1, ap_spent=14),
            CampaignRouteProgress(initial_ap=120, current_ap=0, completed_runs=12,
                                  ap_spent=168, ap_regenerated=48),
        ):
            with self.subTest(progress=progress):
                self.assertTrue(self.verified(progress))

    def test_run_cap_does_not_accept_affordable_ap_or_more_than_twelve_battles(self):
        for progress in (
            CampaignRouteProgress(initial_ap=120, current_ap=14, completed_runs=12,
                                  ap_spent=168, ap_regenerated=62),
            CampaignRouteProgress(initial_ap=120, current_ap=0, completed_runs=13,
                                  ap_spent=182, ap_regenerated=62),
            CampaignRouteProgress(initial_ap=13, current_ap=13),
        ):
            with self.subTest(progress=progress):
                self.assertFalse(self.verified(progress))

    def test_exact_battle_debits_and_ap_conservation_are_required(self):
        for changes in (
            {"ap_spent": 111}, {"completed_runs": 7}, {"initial_ap": 113},
            {"initial_ap": 121, "ap_regenerated": 0, "current_ap": 9},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.verified(replace(self.progress, **changes)))

    def test_progress_counts_must_be_integers_without_bool_or_float_coercion(self):
        for field in ("initial_ap", "current_ap", "completed_runs", "ap_spent", "ap_regenerated"):
            with self.subTest(field=field):
                self.assertFalse(self.verified(replace(
                    self.progress, **{field: float(getattr(self.progress, field))},
                )))
        one = CampaignRouteProgress(initial_ap=14, current_ap=0, completed_runs=1, ap_spent=14)
        for changes in ({"completed_runs": True}, {"current_ap": False}, {"ap_regenerated": False}):
            with self.subTest(changes=changes):
                self.assertFalse(self.verified(replace(one, **changes)))

    def test_untyped_progress_and_unsupported_or_malformed_stage_are_rejected(self):
        for progress in (None, dict(self.progress.__dict__), object(), "completed"):
            with self.subTest(progress=progress):
                self.assertFalse(campaign_ap_drain_verified(
                    "1-15-9", progress, battle_outcome="victory",
                    result_successor_verified=True, terminal_home_verified=True,
                ))
        for stage in ("1-2-9", "ultimate-challenge", None, 14, True, ["1-15-9"]):
            with self.subTest(stage=stage):
                self.assertFalse(self.verified(stage=stage))

    def test_loss_refill_and_missing_or_coerced_terminal_proof_never_complete(self):
        for loss in (True, None, 0):
            with self.subTest(loss=loss):
                self.assertFalse(self.verified(replace(self.progress, loss_seen=loss)))
        for changes in (
            {"battle_outcome": "defeat"}, {"battle_outcome": None},
            {"result_successor_verified": False}, {"result_successor_verified": 1},
            {"terminal_home_verified": False}, {"terminal_home_verified": 1},
            {"refill_seen": True}, {"refill_seen": None}, {"refill_seen": 0},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.verified(**changes))


if __name__ == "__main__":
    unittest.main()
