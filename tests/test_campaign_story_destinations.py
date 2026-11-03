from __future__ import annotations

import json
import unittest
from pathlib import Path

from tasks.campaign_auto_battle import (
    REJECTED_CAMPAIGN_AP_DESTINATIONS,
    SUPPORTED_CAMPAIGN_STORY_DESTINATIONS,
    parse_supported_campaign_story_destination,
)

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "tasks" / "flow_delivery_queue.json"
POLICY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"
SCHEDULER_PATH = ROOT / "automation_service" / "scheduler.py"


class CampaignStoryDestinationParserTests(unittest.TestCase):
    def test_accepts_exact_supported_destinations(self) -> None:
        for destination in ("1-20-9", "1-15-9", "2-2-9"):
            stage = parse_supported_campaign_story_destination(destination)
            self.assertEqual(stage.identity, destination)
            self.assertIn(destination, SUPPORTED_CAMPAIGN_STORY_DESTINATIONS)

    def test_product_tuple_semantics(self) -> None:
        stage = parse_supported_campaign_story_destination("1-20-9")
        self.assertEqual(stage.story_difficulty, 1)
        self.assertEqual(stage.story_chapter, 20)
        self.assertEqual(stage.story_stage, 9)
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
        self.assertEqual(accepted.story_chapter, 2)
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("2-20-9")
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("2-15-9")


class CampaignUltimateChallengeSeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_ultimate_challenge_has_distinct_queue_and_policy_entries(self) -> None:
        flow_ids = [item["flow_id"] for item in self.queue["flows"]]
        self.assertIn("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", flow_ids)
        for flow_id in (
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        ):
            self.assertEqual(flow_ids.count(flow_id), 1)
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

    def test_campaign_parser_cannot_select_ultimate_challenge(self) -> None:
        with self.assertRaises(ValueError):
            parse_supported_campaign_story_destination("ultimate-challenge")
        campaign_policy = next(
            item
            for item in self.policy["policies"]
            if item["policy_id"] == "campaign-supported-destinations"
        )
        campaign = next(
            item
            for item in self.queue["flows"]
            if item["flow_id"] == "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
        )
        self.assertEqual(campaign["destination_policy_id"], "campaign-supported-destinations")
        self.assertNotIn("supported_story_destinations", campaign)
        self.assertNotIn("rejected_destinations", campaign)
        self.assertNotIn("ultimate-challenge", campaign_policy["supported_story_destinations"])
        self.assertIn("ultimate-challenge", campaign_policy["rejected_destinations"])

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
        self.assertNotIn("flow_delivery_queue", scheduler)
        self.assertNotIn("ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION", scheduler)
        by_id = {flow["flow_id"]: flow for flow in self.queue["flows"]}
        for flow_id in (
            "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
            "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
        ):
            flow = by_id[flow_id]
            self.assertNotEqual(flow.get("product_policy_status"), "explicitly_approved")


if __name__ == "__main__":
    unittest.main()
