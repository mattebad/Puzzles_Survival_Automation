"""Campaign AP Stage-9 provenance and destination zero-transport replay tests."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from tasks.campaign_auto_battle import (
    DESTINATION_REPLAY_EVIDENCE_REQUIRED,
    DESTINATION_REPLAY_VERIFIED,
    run_all_campaign_ap_destination_zero_transport_replays,
    run_campaign_ap_destination_zero_transport_replay,
)
from tasks.campaign_stage9 import (
    EVIDENCE_REQUIRED,
    STAGE9_VERIFIED,
    STAGE9_CHAPTER20_MANIFEST,
    evaluate_stage9_on_retained_native_evidence,
    load_stage9_ground_truth_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
CHAPTER20_MAP = ROOT / (
    ".local-captures/campaign-ap-live/1-20-9-20260716T050321849157Z/frames/frame-0006.png"
)
CHAPTER20_DIALOG = ROOT / (
    ".local-captures/campaign-ap-live/1-20-9-20260716T050321849157Z/frames/frame-0007.png"
)
# Independent expected hashes measured from retained files (not copied from production constants).
EXPECTED_CHAPTER20_MAP_SHA256 = hashlib.sha256(CHAPTER20_MAP.read_bytes()).hexdigest() if CHAPTER20_MAP.is_file() else ""
EXPECTED_CHAPTER20_DIALOG_SHA256 = (
    hashlib.sha256(CHAPTER20_DIALOG.read_bytes()).hexdigest() if CHAPTER20_DIALOG.is_file() else ""
)
# Independent Stage-9 ROI recorded in retained events.jsonl observation targets.
INDEPENDENT_STAGE9_ROI = (556, 402, 603, 449)


@unittest.skipUnless(STAGE9_CHAPTER20_MANIFEST.is_file(), "Stage-9 Chapter 20 ground truth missing")
@unittest.skipUnless(CHAPTER20_MAP.is_file() and CHAPTER20_DIALOG.is_file(), "retained native Stage-9 frames missing")
class CampaignStage9ProvenanceTests(unittest.TestCase):
    def test_catalog_loads_only_chapter20_with_independent_hashes(self) -> None:
        catalog = load_stage9_ground_truth_catalog()
        self.assertEqual(set(catalog), {"1-20-9"})
        item = catalog["1-20-9"]
        self.assertEqual(item.source_frame_sha256, EXPECTED_CHAPTER20_MAP_SHA256)
        self.assertEqual(item.dialog_source_frame_sha256, EXPECTED_CHAPTER20_DIALOG_SHA256)
        self.assertEqual(item.crop_roi_xyxy, INDEPENDENT_STAGE9_ROI)
        self.assertEqual(item.dialog_identity, "[20-9]")
        self.assertIn("Ch.20", item.nearby_semantic_label)
        self.assertNotIn("1-15-9", catalog)
        self.assertNotIn("2-2-9", catalog)

    def test_stage9_rebinds_on_retained_chapter20_native_frames(self) -> None:
        decision = evaluate_stage9_on_retained_native_evidence("1-20-9")
        self.assertEqual(decision.status, STAGE9_VERIFIED)
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.transport_count, 0)
        self.assertEqual(decision.recognized_stage_identity, "campaign-stage-1-20-9")
        self.assertEqual(decision.recognized_dialog_identity, "[20-9]")

    def test_missing_chapter15_and_chapter2_are_evidence_required(self) -> None:
        for destination in ("1-15-9", "2-2-9"):
            decision = evaluate_stage9_on_retained_native_evidence(destination)
            self.assertEqual(decision.status, EVIDENCE_REQUIRED)
            self.assertTrue(decision.evidence_required)
            self.assertFalse(decision.dispatch_authorized)
            self.assertEqual(decision.transport_count, 0)


@unittest.skipUnless(STAGE9_CHAPTER20_MANIFEST.is_file(), "Stage-9 Chapter 20 ground truth missing")
class CampaignApDestinationZeroTransportReplayTests(unittest.TestCase):
    def test_1_20_9_destination_verified_without_dispatch(self) -> None:
        result = run_campaign_ap_destination_zero_transport_replay("1-20-9")
        self.assertEqual(result.status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(result.atlas_id, "campaign-atlas-native-800x1280-v4")
        self.assertEqual(result.chapter_label, "Chapter 20")
        self.assertEqual(result.static_ap_cost, 16)
        self.assertFalse(result.dispatch_authorized)
        self.assertEqual(result.transport_count, 0)

    def test_aggregate_report_is_evidence_required_for_missing_stage9(self) -> None:
        report = run_all_campaign_ap_destination_zero_transport_replays()
        self.assertEqual(report.status, DESTINATION_REPLAY_EVIDENCE_REQUIRED)
        self.assertTrue(report.evidence_required)
        self.assertFalse(report.dispatch_authorized)
        self.assertEqual(report.transport_count, 0)
        by_dest = {item.destination: item for item in report.results}
        self.assertEqual(by_dest["1-20-9"].status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(by_dest["1-15-9"].status, DESTINATION_REPLAY_EVIDENCE_REQUIRED)
        self.assertEqual(by_dest["2-2-9"].status, DESTINATION_REPLAY_EVIDENCE_REQUIRED)


if __name__ == "__main__":
    unittest.main()
