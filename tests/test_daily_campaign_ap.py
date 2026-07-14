from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.campaign_ap import CampaignAPObservation
from tasks.contracts import TaskOutcome
from tasks.daily_campaign_ap import (
    DailyCampaignAPObservation,
    daily_campaign_ap_authorizeable,
    daily_campaign_ap_postcondition_verified,
    daily_campaign_ap_replay,
    daily_campaign_ap_transaction_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_campaign_ap_observations.json"
MATRIX = ROOT / "tasks/daily_quest_execution_matrix.json"


def load_campaign(name: str) -> CampaignAPObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return CampaignAPObservation(**payload)


def load_pair() -> tuple[DailyCampaignAPObservation, DailyCampaignAPObservation]:
    before = DailyCampaignAPObservation(
        selected_daily_row=True,
        objective_key="consume_ap",
        daily_progress_before=0,
        campaign=load_campaign("sweep_synthetic"),
    )
    after = DailyCampaignAPObservation(
        selected_daily_row=True,
        objective_key="consume_ap",
        daily_progress_before=0,
        daily_progress_after=10,
        successor_state="DAILY_CAMPAIGN_AP_PROGRESS",
        campaign=replace(
            before.campaign,
            ap_before=30,
            stage_result_visible=True,
            result_identity="campaign-stage-1-1-result",
        ),
    )
    return before, after


class DailyCampaignAPContractTests(unittest.TestCase):
    def test_selected_daily_row_and_exact_ap_action_are_required(self):
        before, _ = load_pair()
        self.assertTrue(daily_campaign_ap_authorizeable(before))
        spec = daily_campaign_ap_transaction_spec(before)
        self.assertEqual(spec.action_kind, "CONSUME_AP_SWEEP")
        self.assertEqual(spec.resource_or_currency, "AP")
        for changes in (
            {"selected_daily_row": False},
            {"objective_key": "ruins_challenge"},
            {"daily_progress_before": 20},
            {"campaign": replace(before.campaign, ap_budget=9)},
            {"campaign": replace(before.campaign, action_mode="BATTLE")},
        ):
            self.assertFalse(daily_campaign_ap_authorizeable(replace(before, **changes)))

    def test_exact_ap_and_daily_progress_successor_is_required(self):
        before, after = load_pair()
        self.assertTrue(daily_campaign_ap_postcondition_verified(before, after))
        self.assertFalse(
            daily_campaign_ap_postcondition_verified(
                before, replace(after, daily_progress_after=11)
            )
        )
        self.assertFalse(
            daily_campaign_ap_postcondition_verified(
                before,
                replace(
                    after,
                    campaign=replace(after.campaign, ap_before=29),
                ),
            )
        )

    def test_replay_keeps_dispatch_and_claim_separate(self):
        before, after = load_pair()
        pending = daily_campaign_ap_replay(before)
        self.assertEqual(pending.outcome, TaskOutcome.PROGRESS)
        self.assertEqual(pending.details["dispatch_count"], 0)
        self.assertEqual(
            daily_campaign_ap_replay(before, after).outcome,
            TaskOutcome.PROGRESS,
        )
        complete_before = replace(
            after,
            daily_progress_before=10,
            daily_progress_after=None,
            successor_state="",
            campaign=replace(
                after.campaign,
                ap_before=30,
                stage_result_visible=False,
                result_identity="",
            ),
        )
        complete_after = replace(
            after,
            daily_progress_before=10,
            daily_progress_after=20,
            successor_state="DAILY_CAMPAIGN_AP_COMPLETE",
            campaign=replace(after.campaign, ap_before=20),
        )
        done = daily_campaign_ap_replay(complete_before, complete_after)
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.details["dispatch_count"], 0)
        self.assertEqual(done.completion_key, "daily-campaign-ap:completed")

    def test_main_static_and_oversized_action_fail_closed(self):
        before, _ = load_pair()
        self.assertFalse(
            daily_campaign_ap_authorizeable(
                replace(
                    before,
                    selected_daily_row=False,
                    campaign=load_campaign("main_negative"),
                )
            )
        )
        self.assertFalse(
            daily_campaign_ap_authorizeable(
                replace(
                    before,
                    campaign=load_campaign("static_reference_negative"),
                )
            )
        )
        self.assertFalse(
            daily_campaign_ap_authorizeable(
                replace(
                    before,
                    campaign=replace(before.campaign, ap_cost=21),
                )
            )
        )

    def test_matrix_keeps_campaign_evidence_gated_and_dormant(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "consume_ap"
        )
        self.assertEqual(row["implementation_status"], "OFFLINE_CONTRACT_ONLY")
        self.assertEqual(row["promotion_state"], "EVIDENCE_GATED")
        self.assertEqual(row["current_runtime_registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])


if __name__ == "__main__":
    unittest.main()
