from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.campaign_ap import (
    CampaignAPObservation,
    campaign_ap_authorizeable,
    campaign_ap_perform_one_pulse,
    campaign_ap_postcondition_verified,
    campaign_ap_transaction_spec,
)
from tasks.contracts import TaskOutcome


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_campaign_ap_observations.json"


def load_fixture(name: str) -> CampaignAPObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return CampaignAPObservation(**payload)


class CampaignAPContractTests(unittest.TestCase):
    def test_sweep_and_auto_complete_are_allowlisted(self):
        sweep = load_fixture("sweep_synthetic")
        self.assertTrue(campaign_ap_authorizeable(sweep))
        sweep_spec = campaign_ap_transaction_spec(sweep)
        self.assertEqual(sweep_spec.action_kind, "CONSUME_AP_SWEEP")
        self.assertEqual(sweep_spec.resource_or_currency, "AP")
        self.assertEqual(sweep_spec.maximum_cost, 20)

        auto = load_fixture("auto_complete_synthetic")
        self.assertTrue(campaign_ap_authorizeable(auto))
        self.assertEqual(
            campaign_ap_transaction_spec(auto).action_kind,
            "CONSUME_AP_AUTO_COMPLETE",
        )

    def test_main_and_static_reference_states_fail_closed(self):
        self.assertFalse(campaign_ap_authorizeable(load_fixture("main_negative")))
        self.assertFalse(
            campaign_ap_authorizeable(load_fixture("static_reference_negative"))
        )

    def test_budget_and_resource_guards_are_required(self):
        observation = load_fixture("sweep_synthetic")
        for changes in (
            {"ap_cost": 21},
            {"ap_cost": 0},
            {"ap_budget": 0},
            {"ap_before": 9},
            {"ap_refill_visible": True},
            {"battle_mode_visible": True},
            {"stage_known": False},
            {"action_mode": "BATTLE"},
            {"control_class": "BATTLE"},
            {"target_identity": "generic-campaign"},
            {"overlay_state": "unknown"},
        ):
            self.assertFalse(campaign_ap_authorizeable(replace(observation, **changes)))

    def test_postcondition_requires_exact_ap_delta_and_result(self):
        before = load_fixture("sweep_synthetic")
        result = replace(
            before,
            ap_before=30,
            stage_result_visible=True,
            result_identity="campaign-stage-1-1-result",
        )
        self.assertTrue(campaign_ap_postcondition_verified(before, result))
        self.assertFalse(
            campaign_ap_postcondition_verified(
                before, replace(result, ap_before=29)
            )
        )
        self.assertFalse(
            campaign_ap_postcondition_verified(
                before, replace(result, stage_identity="campaign-stage-2-1")
            )
        )
        self.assertFalse(
            campaign_ap_postcondition_verified(
                before, replace(result, game_day_id="next-day")
            )
        )

    def test_one_pulse_is_pure_and_dormant(self):
        before = load_fixture("sweep_synthetic")
        prepared = campaign_ap_perform_one_pulse(before)
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        done = campaign_ap_perform_one_pulse(
            before,
            replace(
                before,
                ap_before=30,
                stage_result_visible=True,
                result_identity="campaign-stage-1-1-result",
            ),
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(done.completion_key, "campaign-ap:campaign-stage-1-1:completed")


if __name__ == "__main__":
    unittest.main()
