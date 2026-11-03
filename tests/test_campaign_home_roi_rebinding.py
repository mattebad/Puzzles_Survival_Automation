"""Typed Campaign ROI drift uses the real executor and capability firewall."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from safe_action_core import (
    ActionClass, ActionStatus, CentralPolicy, SafeActionExecutor, SafetyStore, TransportResult,
)
from tests.support.capability_firewall import Clock, TEST_TASKS, nav_observation, nav_request


SEMANTIC = "CAMPAIGN_HOME_ATLAS_BUILDING_OPEN"
TARGET = "home.building.campaign"
PROPOSAL_ROI = (402, 183, 560, 342)
IMMEDIATE_ROI = (402, 184, 560, 343)


class CampaignHomeRoiRebindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = SafetyStore(Path(self.temporary.name) / "actions.sqlite3")
        self.addCleanup(self.store.close)
        self.store.acquire_lease("executor-1", 1000.0, 100.0)
        self.policy = CentralPolicy(supervised_tasks=TEST_TASKS)
        self.clock = Clock()
        self.transported = []
        self.ordinal = 0
        self.proposal = nav_observation(target_identity=TARGET, target_roi=PROPOSAL_ROI,
                                        expected_postcondition="CAMPAIGN_TIER_MAP_OR_EQUIVALENT")
        self.immediate = replace(self.proposal, frame_sha256="b" * 64,
                                 capture_completed_monotonic=999.8, target_roi=IMMEDIATE_ROI,
                                 evidence_refs=("synthetic:independent-current-Campaign-target",))

    def execute(self, *, request_changes=None, immediate_changes=None, capability_changes=None, advance=0):
        self.ordinal += 1
        self.clock.value = 1000.0
        request = nav_request(self.proposal, semantic_action=SEMANTIC,
                              action_id=f"Campaign-{self.ordinal}", action_key=f"Campaign-key-{self.ordinal}",
                              observation_max_age_seconds=30.0, dispatch_max_age_seconds=15.0)
        request = replace(request, **(request_changes or {}))
        current = replace(self.immediate, **(immediate_changes or {}))
        capability_source = replace(self.immediate, **(capability_changes or {}))
        issued = self.policy.issue_capability(replace(request, observation=capability_source,
                                                       action_class=ActionClass.NAVIGATION_ONLY))
        self.assertTrue(issued.authorized)
        self.assertIsNotNone(issued.capability)

        def transport(intent):
            self.transported.append(intent)
            return TransportResult(True, "MOCK_CAMPAIGN_NAVIGATION")

        post = replace(current, source_state="CAMPAIGN", target_identity=None, target_roi=None,
                       frame_sha256="c" * 64, capture_completed_monotonic=1000.2)
        executor = SafeActionExecutor(self.store, self.policy, "executor-1", self.clock, transport,
                                      lambda: current, lambda: (post,),
                                      lambda _intent, observed: observed.source_state == "CAMPAIGN",
                                      max_pre_dispatch_attempts=1)
        self.clock.advance(advance)
        return executor.execute(request, issued.capability), issued.capability

    def test_current_capability_dispatches_exact_immediate_roi_hash_time_and_evidence(self):
        result, capability = self.execute()
        self.assertEqual(result.status, ActionStatus.CONFIRMED)
        self.assertEqual(result.transport_calls, 1)
        self.assertTrue(capability.consumed)
        self.assertEqual(len(self.transported), 1)
        intent = self.transported[0]
        self.assertEqual(intent.target_roi, IMMEDIATE_ROI)
        self.assertEqual(intent.source_frame_sha256, self.immediate.frame_sha256)
        self.assertEqual(intent.source_frame_captured_at, self.immediate.capture_completed_monotonic)
        self.assertEqual(intent.evidence_refs, self.immediate.evidence_refs)
        retained = self.store.get_action(result.action_id)
        self.assertEqual(retained["source_frame_sha256"], self.proposal.frame_sha256)
        self.assertEqual(retained["source_frame_captured_at"], self.proposal.capture_completed_monotonic)

    def test_other_semantic_does_not_gain_roi_drift_permission(self):
        result, _ = self.execute(request_changes={"semantic_action": "HOME_TO_QUEST"})
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.reason, "TARGET_ROI_CHANGED")
        self.assertEqual(result.transport_calls, 0)
        self.assertFalse(self.transported)

    def test_changed_identity_cost_or_overlay_still_dispatches_nothing(self):
        for changed in ({"target_identity": "home.building.research_lab"},
                        {"source_state": "CAMPAIGN"}, {"cost_amount": 1},
                        {"overlay_state": "unknown_modal"}):
            with self.subTest(changed=changed):
                result, _ = self.execute(immediate_changes=changed)
                self.assertEqual(result.status, ActionStatus.CANCELLED)
                self.assertEqual(result.transport_calls, 0)
                self.assertFalse(self.transported)

    def test_expired_current_capture_still_dispatches_nothing(self):
        result, _ = self.execute(advance=16.0)
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.reason, "CAPABILITY_STALE_OBSERVATION")
        self.assertEqual(result.transport_calls, 0)
        self.assertFalse(self.transported)

    def test_capability_bound_to_planning_capture_cannot_authorize_immediate_target(self):
        result, capability = self.execute(capability_changes={
            "frame_sha256": self.proposal.frame_sha256,
            "capture_completed_monotonic": self.proposal.capture_completed_monotonic,
            "target_roi": PROPOSAL_ROI,
        })
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.transport_calls, 0)
        self.assertTrue(capability.consumed)
        self.assertFalse(self.transported)

    def test_resource_class_cannot_use_campaign_navigation_exception(self):
        for action_class in (ActionClass.OWNED_ITEM_NON_IDEMPOTENT, ActionClass.CAMPAIGN_AP_CHALLENGE):
            with self.subTest(action_class=action_class):
                result, _ = self.execute(request_changes={"action_class": action_class})
                self.assertEqual(result.status, ActionStatus.CANCELLED)
                if action_class is ActionClass.OWNED_ITEM_NON_IDEMPOTENT:
                    self.assertEqual(result.reason, "RESOURCE_AUTHORITY_REQUIRED")
                self.assertEqual(result.transport_calls, 0)
                self.assertFalse(self.transported)


if __name__ == "__main__":
    unittest.main()
