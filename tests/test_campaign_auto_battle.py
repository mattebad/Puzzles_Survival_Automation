from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.campaign_auto_battle import (
    BattleResult,
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignRouteObservation,
    CampaignRouteProgress,
    CampaignScreen,
    CampaignStage,
    campaign_next_decision,
    classify_battle_result,
    planned_run_count,
    reconcile_observed_ap,
    record_verified_victory,
)


class CampaignAutoBattleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stage = CampaignStage.parse("1-20-9")
        self.config = CampaignAutoBattleConfig(
            target_stage=self.stage,
            ap_cost=20,
            ap_budget=100,
            max_runs=10,
            battle_poll_seconds=1,
            battle_timeout_seconds=180,
        )
        self.progress = CampaignRouteProgress(initial_ap=100, current_ap=100)

    def decide(self, observation: CampaignRouteObservation):
        return campaign_next_decision(self.config, self.progress, observation)

    def test_stage_identity_and_bounded_repeat_plan(self):
        self.assertEqual(self.stage.identity, "1-20-9")
        self.assertEqual(self.stage.dialog_identity, "[20-9]")
        self.assertEqual(
            CampaignStage.parse("campaign-stage-1-20-9"),
            self.stage,
        )
        for bad in ("1-20", "0-20-9", "1-x-9", "1-20-0"):
            with self.assertRaises(ValueError):
                CampaignStage.parse(bad)
        self.assertEqual(
            planned_run_count(
                ap_available=100,
                ap_cost=20,
                ap_budget=100,
                max_runs=10,
            ),
            5,
        )
        self.assertEqual(
            planned_run_count(
                ap_available=95,
                ap_cost=20,
                ap_budget=60,
                max_runs=10,
            ),
            3,
        )
        self.assertEqual(
            planned_run_count(
                ap_available=19,
                ap_cost=20,
                ap_budget=100,
                max_runs=10,
            ),
            0,
        )

    def test_tier_chapter_and_stage_are_selected_semantically(self):
        home = self.decide(CampaignRouteObservation(screen=CampaignScreen.HOME_BASE))
        self.assertEqual(home.action, CampaignAction.OPEN_CAMPAIGN)
        self.assertFalse(home.dispatch_authorized)

        tier = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=2,
            )
        )
        self.assertEqual(tier.action, CampaignAction.SELECT_TIER)
        self.assertEqual(tier.target_identity, "campaign-tier-1")

        missing_chapter = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=3,
            )
        )
        self.assertEqual(missing_chapter.action, CampaignAction.BLOCKED)

        chapter = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=3,
                chapter_navigation_available=True,
            )
        )
        self.assertEqual(chapter.action, CampaignAction.NAVIGATE_CHAPTER)
        self.assertEqual(chapter.target_identity, "campaign-chapter-20")

        enter_chapter = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.TIER_MAP,
                selected_tier=1,
                chapter_number=20,
                chapter_navigation_available=True,
            )
        )
        self.assertEqual(enter_chapter.action, CampaignAction.NAVIGATE_CHAPTER)

        stage = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.CHAPTER_MAP,
                selected_tier=1,
                chapter_number=20,
                visible_stage_numbers=(7, 8, 9),
            )
        )
        self.assertEqual(stage.action, CampaignAction.SELECT_STAGE)
        self.assertEqual(stage.target_identity, "campaign-stage-1-20-9")

    def test_exact_stage_ap_and_lineup_gates(self):
        dialog = CampaignRouteObservation(
            screen=CampaignScreen.STAGE_DIALOG,
            stage_dialog=self.stage,
            ap_current=100,
            ap_cost=20,
            challenge_ready=True,
        )
        self.assertEqual(self.decide(dialog).action, CampaignAction.CHALLENGE_STAGE)
        for changed in (
            replace(dialog, stage_dialog=CampaignStage.parse("1-20-8")),
            replace(dialog, ap_current=99),
            replace(dialog, ap_cost=10),
            replace(dialog, refill_visible=True),
            replace(dialog, challenge_ready=False),
        ):
            self.assertEqual(self.decide(changed).action, CampaignAction.BLOCKED)

        lineup = self.decide(
            CampaignRouteObservation(
                screen=CampaignScreen.HERO_LINEUP,
                lineup_challenge_ready=True,
            )
        )
        self.assertEqual(lineup.action, CampaignAction.CONFIRM_LINEUP)

    def test_battle_polls_until_explicit_success_or_loss(self):
        battle = CampaignRouteObservation(
            screen=CampaignScreen.BATTLE,
            auto_enabled=False,
            battle_elapsed_seconds=1,
        )
        self.assertEqual(classify_battle_result(battle), BattleResult.ACTIVE)
        self.assertEqual(self.decide(battle).action, CampaignAction.ENABLE_AUTO)
        self.assertEqual(
            self.decide(replace(battle, auto_enabled=True)).action,
            CampaignAction.WAIT_FOR_BATTLE_RESULT,
        )
        self.assertEqual(
            self.decide(
                replace(
                    battle,
                    auto_enabled=True,
                    battle_elapsed_seconds=180,
                )
            ).action,
            CampaignAction.BLOCKED,
        )

        victory = replace(
            battle,
            screen=CampaignScreen.RESULT,
            winner_visible=True,
            loot_visible=True,
            tap_to_continue_visible=True,
        )
        self.assertEqual(classify_battle_result(victory), BattleResult.VICTORY)
        self.assertEqual(self.decide(victory).action, CampaignAction.CONTINUE_VICTORY)
        self.assertEqual(
            self.decide(replace(victory, loot_visible=False)).action,
            CampaignAction.BLOCKED,
        )

        defeat = replace(
            battle,
            screen=CampaignScreen.RESULT,
            defeat_visible=True,
            return_control_visible=True,
        )
        self.assertEqual(classify_battle_result(defeat), BattleResult.DEFEAT)
        self.assertEqual(
            self.decide(defeat).action,
            CampaignAction.RETURN_HOME_AFTER_DEFEAT,
        )
        self.assertEqual(
            self.decide(defeat).expected_successor,
            CampaignScreen.CHAPTER_MAP,
        )

    def test_repeat_requires_exact_ap_delta_and_stops_at_home(self):
        progress = record_verified_victory(self.progress, ap_cost=20, ap_after=80)
        self.assertEqual(progress.completed_runs, 1)
        self.assertEqual(progress.ap_spent, 20)
        with self.assertRaises(ValueError):
            record_verified_victory(self.progress, ap_cost=20, ap_after=79)

        for expected_ap in (60, 40, 20, 0):
            progress = record_verified_victory(
                progress,
                ap_cost=20,
                ap_after=expected_ap,
            )
        completed = campaign_next_decision(
            self.config,
            progress,
            CampaignRouteObservation(screen=CampaignScreen.HOME_BASE),
        )
        self.assertEqual(completed.action, CampaignAction.COMPLETE)
        self.assertTrue(completed.terminal)

        after_loss = replace(self.progress, loss_seen=True)
        stopped = campaign_next_decision(
            self.config,
            after_loss,
            CampaignRouteObservation(screen=CampaignScreen.HOME_BASE),
        )
        self.assertEqual(stopped.action, CampaignAction.COMPLETE)

        for screen, expected in (
            (CampaignScreen.STAGE_DIALOG, CampaignAction.CLOSE_STAGE_DIALOG),
            (CampaignScreen.CHAPTER_MAP, CampaignAction.LEAVE_CHAPTER_MAP),
            (CampaignScreen.TIER_MAP, CampaignAction.RETURN_HOME),
        ):
            with self.subTest(screen=screen):
                self.assertEqual(
                    campaign_next_decision(
                        self.config,
                        after_loss,
                        CampaignRouteObservation(screen=screen),
                    ).action,
                    expected,
                )

    def test_ap_regeneration_is_reconciled_without_hiding_spend(self):
        progress = record_verified_victory(self.progress, ap_cost=20, ap_after=80)
        progress = reconcile_observed_ap(progress, ap_observed=81)
        self.assertEqual(progress.current_ap, 81)
        self.assertEqual(progress.ap_regenerated, 1)

        progress = record_verified_victory(
            progress,
            ap_cost=20,
            ap_after=62,
            ap_regenerated=1,
        )
        self.assertEqual(progress.ap_spent, 40)
        self.assertEqual(progress.ap_regenerated, 2)
        self.assertEqual(progress.current_ap, 62)

        with self.assertRaises(ValueError):
            reconcile_observed_ap(progress, ap_observed=61)

    def test_insufficient_ap_unwinds_campaign_without_refill(self):
        progress = CampaignRouteProgress(initial_ap=6, current_ap=6)
        dialog = CampaignRouteObservation(
            screen=CampaignScreen.STAGE_DIALOG,
            stage_dialog=self.stage,
            ap_current=6,
            ap_cost=20,
            challenge_ready=False,
        )
        self.assertEqual(
            campaign_next_decision(self.config, progress, dialog).action,
            CampaignAction.CLOSE_STAGE_DIALOG,
        )
        self.assertEqual(
            campaign_next_decision(
                self.config,
                progress,
                CampaignRouteObservation(
                    screen=CampaignScreen.CHAPTER_MAP,
                    selected_tier=1,
                    chapter_number=20,
                ),
            ).action,
            CampaignAction.LEAVE_CHAPTER_MAP,
        )
        self.assertEqual(
            campaign_next_decision(
                self.config,
                progress,
                CampaignRouteObservation(screen=CampaignScreen.TIER_MAP),
            ).action,
            CampaignAction.RETURN_HOME,
        )


if __name__ == "__main__":
    unittest.main()
