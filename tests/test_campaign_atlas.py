from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from tasks.campaign_atlas import (
    CampaignScanContract,
    CollectorDisposition,
    NativeFrameProvenance,
    Rect,
    SurveyPhase,
    default_prep_scan_contract,
    dry_run_campaign_survey,
)


def provenance(**changes: object) -> NativeFrameProvenance:
    values: dict[str, object] = {
        "source_id": "reviewed/native/frame-001.png",
        "capture_kind": "fixture",
        "runtime_session_id": "campaign-survey-test",
        "capture_ordinal": 1,
        "capture_completed_monotonic": 12.5,
        "transport_sha256": "a" * 64,
        "semantic_sha256": "b" * 64,
        "captured_at_utc": "2026-07-23T18:30:00Z",
        "width": 800,
        "height": 1280,
    }
    values.update(changes)
    return NativeFrameProvenance(**values)  # type: ignore[arg-type]


class CampaignAtlasContractTests(unittest.TestCase):
    def test_provenance_is_immutable_and_native_profile_bound(self) -> None:
        identity = provenance()
        self.assertEqual((identity.width, identity.height), (800, 1280))
        self.assertEqual(identity.package, "com.global.ztmslg")
        with self.assertRaises(FrozenInstanceError):
            identity.width = 799  # type: ignore[misc]

    def test_provenance_rejects_invalid_identity_fields(self) -> None:
        for changes in (
            {"semantic_sha256": "not-a-digest"},
            {"transport_sha256": "A" * 64},
            {"capture_kind": "unknown"},
            {"runtime_session_id": ""},
            {"capture_ordinal": 0},
            {"captured_at_utc": "2026-07-23T18:30:00"},
            {"width": 799},
            {"profile_id": "other-profile"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                provenance(**changes)

    def test_rect_rejects_non_native_or_empty_bounds(self) -> None:
        for args in ((-1, 0, 1, 1), (0, 0, 801, 1), (0, 0, 1, 1281), (3, 3, 3, 4)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Rect(*args)

    def test_scan_contract_is_bounded_to_zero_input_prep_topology(self) -> None:
        contract = default_prep_scan_contract()
        self.assertEqual(
            contract.phases,
            (
                SurveyPhase.EDGE_TOP,
                SurveyPhase.EDGE_RIGHT,
                SurveyPhase.EDGE_BOTTOM,
                SurveyPhase.EDGE_LEFT,
                SurveyPhase.OVERLAPPING_VIEWPORTS,
                SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
                SurveyPhase.SAFE_TERMINAL,
            ),
        )
        self.assertEqual(contract.maximum_transport_inputs, 0)
        self.assertEqual(contract.maximum_native_frames, 0)
        self.assertEqual(contract.maximum_edge_steps_per_direction, 32)
        self.assertEqual(contract.maximum_overlapping_viewports, 128)
        self.assertTrue(contract.overlap_evidence_required)
        self.assertFalse(contract.build_atlas)
        self.assertNotIn("coordinate", vars(contract))
        self.assertNotIn("anchor", vars(contract))
        with self.assertRaises(ValueError):
            replace(contract, maximum_transport_inputs=1)
        with self.assertRaises(ValueError):
            replace(contract, maximum_edge_steps_per_direction=33)
        with self.assertRaises(ValueError):
            replace(contract, overlap_evidence_required=False)

    def test_missing_corpus_returns_evidence_required_without_artifacts(self) -> None:
        report = dry_run_campaign_survey(default_prep_scan_contract())
        self.assertEqual(report.disposition, CollectorDisposition.EVIDENCE_REQUIRED)
        self.assertFalse(report.transport_dispatched)
        self.assertEqual(report.transport_input_count, 0)
        self.assertEqual(report.native_frames_acquired, 0)
        self.assertEqual(report.evidence_artifacts, ())
        self.assertFalse(report.atlas_created)

    def test_prep_collector_refuses_to_promote_observed_frames(self) -> None:
        report = dry_run_campaign_survey(
            default_prep_scan_contract(), observed_frames=(provenance(),)
        )
        self.assertEqual(report.disposition, CollectorDisposition.BLOCKED_FAIL_CLOSED)
        self.assertEqual(report.native_frames_acquired, 0)
        self.assertEqual(report.evidence_artifacts, ())

    def test_prep_collector_revalidates_and_rejects_invalid_provenance(self) -> None:
        invalid = object.__new__(NativeFrameProvenance)
        for name, value in vars(provenance()).items():
            object.__setattr__(invalid, name, value)
        object.__setattr__(invalid, "semantic_sha256", "invalid")
        report = dry_run_campaign_survey(
            default_prep_scan_contract(), observed_frames=(invalid,)
        )
        self.assertEqual(report.disposition, CollectorDisposition.BLOCKED_FAIL_CLOSED)
        self.assertEqual(report.reason, "invalid native frame provenance")
        self.assertEqual(report.transport_input_count, 0)
        self.assertEqual(report.evidence_artifacts, ())


if __name__ == "__main__":
    unittest.main()
