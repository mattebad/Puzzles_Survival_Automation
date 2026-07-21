from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from scripts import flow_delivery_control as control
from tasks.campaign_auto_battle import (
    REJECTED_CAMPAIGN_AP_DESTINATIONS,
    SUPPORTED_CAMPAIGN_STORY_DESTINATIONS,
    parse_supported_campaign_story_destination,
)


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"
COVERAGE_PATH = ROOT / "tasks" / "flow_delivery_coverage.json"
SCHEDULER_PATH = ROOT / "tasks" / "scheduler.py"


class CampaignStoryDestinationParserTests(unittest.TestCase):
    def test_accepts_exact_supported_destinations(self) -> None:
        for destination in ("1-20-9", "1-15-9", "2-2-9"):
            stage = parse_supported_campaign_story_destination(destination)
            self.assertEqual(stage.identity, destination)
            self.assertIn(destination, SUPPORTED_CAMPAIGN_STORY_DESTINATIONS)

    def test_product_tuple_semantics(self) -> None:
        stage = parse_supported_campaign_story_destination("1-20-9")
        self.assertEqual(stage.story_difficulty, 1)
        self.assertEqual(stage.story_stage, 20)
        self.assertEqual(stage.story_chapter, 9)
        self.assertEqual(stage.dialog_identity, "[20-9]")

    def test_rejects_removed_and_unsupported_destinations(self) -> None:
        for destination in (
            "1-2-9",
            "ultimate-challenge",
            "ULTIMATE-CHALLENGE",
            "2-20-9",
            "1-15-8",
            "3-2-9",
            "1-20-8",
        ):
            with self.assertRaises(ValueError):
                parse_supported_campaign_story_destination(destination)
        self.assertEqual(REJECTED_CAMPAIGN_AP_DESTINATIONS, frozenset({"1-2-9", "ultimate-challenge"}))

    def test_difficulty_two_only_where_explicitly_registered(self) -> None:
        accepted = parse_supported_campaign_story_destination("2-2-9")
        self.assertEqual(accepted.story_difficulty, 2)
        self.assertEqual(accepted.story_stage, 2)
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("2-20-9")
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("2-15-9")


class CampaignUltimateChallengeSeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))

    def test_ultimate_challenge_has_distinct_queue_and_policy_entries(self) -> None:
        flow_ids = [item["flow_id"] for item in self.queue["flows"]]
        self.assertIn("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", flow_ids)
        self.assertEqual(
            flow_ids[0],
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
        )
        self.assertEqual(flow_ids[1], "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")
        policy_ids = {item["policy_id"] for item in self.policy["policies"]}
        self.assertIn("ultimate-challenge-flow-separation", policy_ids)
        self.assertIn("ultimate-challenge-navigation-validation", policy_ids)
        self.assertIn("ultimate-challenge-one-success-per-reset", policy_ids)
        campaign_policy = next(
            item
            for item in self.policy["policies"]
            if item["policy_id"] == "campaign-supported-destinations"
        )
        self.assertEqual(
            campaign_policy["supported_story_destinations"],
            ["1-20-9", "1-15-9", "2-2-9"],
        )
        self.assertEqual(
            campaign_policy["rejected_destinations"],
            ["1-2-9", "ultimate-challenge"],
        )

    def test_completion_states_remain_independent(self) -> None:
        queue = deepcopy(self.queue)
        campaign = next(
            item
            for item in queue["flows"]
            if item["flow_id"] == "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
        )
        ultimate = next(
            item
            for item in queue["flows"]
            if item["flow_id"] == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
        )
        campaign["status"] = "completed"
        campaign["last_completed_stage"] = "completed"
        self.assertEqual(ultimate["status"], "ready")
        selected = control.FlowDeliveryController().select_next(queue)
        self.assertEqual(selected["flow_id"], "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")

        ultimate["status"] = "completed"
        ultimate["last_completed_stage"] = "completed"
        campaign["status"] = "ready"
        campaign["last_completed_stage"] = None
        selected_campaign = control.FlowDeliveryController().select_next(queue)
        self.assertEqual(
            selected_campaign["flow_id"],
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
        )

    def test_campaign_parser_cannot_select_ultimate_challenge(self) -> None:
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("ultimate-challenge")
        campaign = self.queue["flows"][0]
        self.assertNotIn("ultimate-challenge", campaign["supported_story_destinations"])
        self.assertIn("ultimate-challenge", campaign["rejected_destinations"])

    def test_queue_still_selects_campaign_first(self) -> None:
        selected = control.FlowDeliveryController().select_next(self.queue)
        self.assertEqual(
            selected["flow_id"],
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
        )

    def test_next_after_campaign_follows_corrected_order(self) -> None:
        queue = deepcopy(self.queue)
        queue["flows"][0]["status"] = "blocked"
        queue["flows"][0]["blocked_reason"] = "test blocker"
        selected = control.FlowDeliveryController().select_next(queue)
        self.assertEqual(selected["flow_id"], "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION")

    def test_coverage_keeps_objectives_separate(self) -> None:
        campaign = self.coverage["flows"]["CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"]
        ultimate = self.coverage["flows"]["ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"]
        for field in (
            "home_navigation_state",
            "story_destination_navigation_state",
            "ap_execution_state",
            "supported_story_destinations",
        ):
            self.assertIn(field, campaign)
        for field in (
            "campaign_entry_state",
            "ultimate_challenge_navigation_state",
            "daily_execution_state",
            "already_completed_detection_state",
            "reset_idempotency_state",
        ):
            self.assertIn(field, ultimate)
        self.assertEqual(
            campaign["supported_story_destinations"],
            ["1-20-9", "1-15-9", "2-2-9"],
        )
        self.assertEqual(ultimate["supported_story_destinations"], [])
        self.assertEqual(campaign["ultimate_challenge_coverage"], "not_applicable_to_this_flow")
        self.assertEqual(ultimate["campaign_ap_coverage"], "not_applicable_to_this_flow")

    def test_campaign_home_atlas_entry_seam_is_canonical(self) -> None:
        from scripts.home_atlas_bluestacks import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID,
            campaign_home_atlas_building_id,
            dispatch_verified_navigate_pan,
            require_campaign_home_atlas_building,
            run_verified_campaign_home_atlas_entry,
        )
        from tasks.campaign_auto_battle_runtime import (
            CAMPAIGN_HOME_ATLAS_BUILDING_ID as RUNTIME_ID,
        )

        self.assertEqual(campaign_home_atlas_building_id(), "home.building.campaign")
        self.assertEqual(CAMPAIGN_HOME_ATLAS_BUILDING_ID, RUNTIME_ID)
        self.assertEqual(require_campaign_home_atlas_building(), CAMPAIGN_HOME_ATLAS_BUILDING_ID)
        self.assertTrue(callable(dispatch_verified_navigate_pan))
        self.assertTrue(callable(run_verified_campaign_home_atlas_entry))

    def test_production_scheduler_and_registration_remain_unchanged(self) -> None:
        self.assertFalse(self.queue["gameplay_scheduler"])
        scheduler = SCHEDULER_PATH.read_text(encoding="utf-8")
        self.assertIn("offline Phase F work", scheduler)
        self.assertNotIn("flow_delivery_queue", scheduler)
        self.assertNotIn("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", scheduler)
        for flow in self.queue["flows"][:2]:
            self.assertNotEqual(flow.get("product_policy_status"), "explicitly_approved")


if __name__ == "__main__":
    unittest.main()
