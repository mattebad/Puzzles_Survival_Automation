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
    STAGE9_VERIFIED,
    STAGE9_CHAPTER2_MANIFEST,
    STAGE9_CHAPTER15_MANIFEST,
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
CHAPTER15_MAP = ROOT / (
    ".local-captures/campaign-ap-live/1-15-9-20260724T220628066834Z/frames/frame-chapter-map.png"
)
CHAPTER15_DIALOG = ROOT / (
    ".local-captures/campaign-ap-live/1-15-9-20260724T220628066834Z/frames/frame-stage-dialog.png"
)
CHAPTER2_MAP = ROOT / (
    ".local-captures/campaign-ap-live/2-2-9-20260724T221321850089Z/frames/frame-chapter-map.png"
)
CHAPTER2_DIALOG = ROOT / (
    ".local-captures/campaign-ap-live/2-2-9-20260724T221321850089Z/frames/frame-stage-dialog.png"
)

EXPECTED_CHAPTER20_MAP_SHA256 = (
    hashlib.sha256(CHAPTER20_MAP.read_bytes()).hexdigest() if CHAPTER20_MAP.is_file() else ""
)
EXPECTED_CHAPTER20_DIALOG_SHA256 = (
    hashlib.sha256(CHAPTER20_DIALOG.read_bytes()).hexdigest() if CHAPTER20_DIALOG.is_file() else ""
)
EXPECTED_CHAPTER15_MAP_SHA256 = (
    hashlib.sha256(CHAPTER15_MAP.read_bytes()).hexdigest() if CHAPTER15_MAP.is_file() else ""
)
EXPECTED_CHAPTER2_MAP_SHA256 = (
    hashlib.sha256(CHAPTER2_MAP.read_bytes()).hexdigest() if CHAPTER2_MAP.is_file() else ""
)

INDEPENDENT_STAGE9_ROI_CH20 = (556, 402, 603, 449)
INDEPENDENT_STAGE9_ROI_CH15 = (155, 382, 202, 428)
INDEPENDENT_STAGE9_ROI_CH2 = (150, 536, 197, 583)


@unittest.skipUnless(STAGE9_CHAPTER20_MANIFEST.is_file(), "Stage-9 Chapter 20 ground truth missing")
@unittest.skipUnless(CHAPTER20_MAP.is_file() and CHAPTER20_DIALOG.is_file(), "retained native Stage-9 frames missing")
class CampaignStage9ProvenanceTests(unittest.TestCase):
    def test_catalog_loads_all_three_destinations_with_independent_hashes(self) -> None:
        catalog = load_stage9_ground_truth_catalog()
        self.assertEqual(set(catalog), {"1-20-9", "1-15-9", "2-2-9"})
        self.assertEqual(catalog["1-20-9"].source_frame_sha256, EXPECTED_CHAPTER20_MAP_SHA256)
        self.assertEqual(catalog["1-20-9"].dialog_source_frame_sha256, EXPECTED_CHAPTER20_DIALOG_SHA256)
        self.assertEqual(catalog["1-20-9"].crop_roi_xyxy, INDEPENDENT_STAGE9_ROI_CH20)
        self.assertEqual(catalog["1-20-9"].dialog_identity, "[20-9]")
        self.assertIn("Ch.20", catalog["1-20-9"].nearby_semantic_label)

        self.assertTrue(STAGE9_CHAPTER15_MANIFEST.is_file())
        self.assertTrue(STAGE9_CHAPTER2_MANIFEST.is_file())
        self.assertEqual(catalog["1-15-9"].source_frame_sha256, EXPECTED_CHAPTER15_MAP_SHA256)
        self.assertEqual(catalog["1-15-9"].crop_roi_xyxy, INDEPENDENT_STAGE9_ROI_CH15)
        self.assertEqual(catalog["1-15-9"].dialog_identity, "[15-9]")
        self.assertIn("Ch.15", catalog["1-15-9"].nearby_semantic_label)
        self.assertEqual(catalog["1-15-9"].static_ap_cost, 14)

        self.assertEqual(catalog["2-2-9"].source_frame_sha256, EXPECTED_CHAPTER2_MAP_SHA256)
        self.assertEqual(catalog["2-2-9"].crop_roi_xyxy, INDEPENDENT_STAGE9_ROI_CH2)
        self.assertEqual(catalog["2-2-9"].dialog_identity, "[2-9]")
        self.assertIn("Ch.2", catalog["2-2-9"].nearby_semantic_label)
        self.assertEqual(catalog["2-2-9"].static_ap_cost, 20)

    def test_stage9_rebinds_on_retained_chapter20_native_frames(self) -> None:
        decision = evaluate_stage9_on_retained_native_evidence("1-20-9")
        self.assertEqual(decision.status, STAGE9_VERIFIED)
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.transport_count, 0)
        self.assertEqual(decision.recognized_stage_identity, "campaign-stage-1-20-9")
        self.assertEqual(decision.recognized_dialog_identity, "[20-9]")

    @unittest.skipUnless(CHAPTER15_MAP.is_file() and CHAPTER15_DIALOG.is_file(), "Ch.15 retained frames missing")
    def test_stage9_rebinds_on_retained_chapter15_native_frames(self) -> None:
        decision = evaluate_stage9_on_retained_native_evidence("1-15-9")
        self.assertEqual(decision.status, STAGE9_VERIFIED)
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.transport_count, 0)
        self.assertEqual(decision.recognized_stage_identity, "campaign-stage-1-15-9")
        self.assertEqual(decision.recognized_dialog_identity, "[15-9]")

    @unittest.skipUnless(CHAPTER2_MAP.is_file() and CHAPTER2_DIALOG.is_file(), "Ch.2 retained frames missing")
    def test_stage9_rebinds_on_retained_chapter2_native_frames(self) -> None:
        decision = evaluate_stage9_on_retained_native_evidence("2-2-9")
        self.assertEqual(decision.status, STAGE9_VERIFIED)
        self.assertFalse(decision.dispatch_authorized)
        self.assertEqual(decision.transport_count, 0)
        self.assertEqual(decision.recognized_stage_identity, "campaign-stage-2-2-9")
        self.assertEqual(decision.recognized_dialog_identity, "[2-9]")


@unittest.skipUnless(STAGE9_CHAPTER20_MANIFEST.is_file(), "Stage-9 Chapter 20 ground truth missing")
@unittest.skipUnless(STAGE9_CHAPTER15_MANIFEST.is_file(), "Stage-9 Chapter 15 ground truth missing")
@unittest.skipUnless(STAGE9_CHAPTER2_MANIFEST.is_file(), "Stage-9 Chapter 2 ground truth missing")
class CampaignApDestinationZeroTransportReplayTests(unittest.TestCase):
    def test_1_20_9_destination_verified_without_dispatch(self) -> None:
        result = run_campaign_ap_destination_zero_transport_replay("1-20-9")
        self.assertEqual(result.status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(result.atlas_id, "campaign-atlas-native-800x1280-v4")
        self.assertEqual(result.chapter_label, "Chapter 20")
        self.assertEqual(result.static_ap_cost, 16)
        self.assertFalse(result.dispatch_authorized)
        self.assertEqual(result.transport_count, 0)

    def test_all_three_destinations_verified_zero_transport(self) -> None:
        report = run_all_campaign_ap_destination_zero_transport_replays()
        self.assertEqual(report.status, DESTINATION_REPLAY_VERIFIED)
        self.assertFalse(report.evidence_required)
        self.assertFalse(report.dispatch_authorized)
        self.assertEqual(report.transport_count, 0)
        by_dest = {item.destination: item for item in report.results}
        self.assertEqual(by_dest["1-20-9"].status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(by_dest["1-15-9"].status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(by_dest["2-2-9"].status, DESTINATION_REPLAY_VERIFIED)
        self.assertEqual(by_dest["1-15-9"].static_ap_cost, 14)
        self.assertEqual(by_dest["2-2-9"].static_ap_cost, 20)


if __name__ == "__main__":
    unittest.main()
