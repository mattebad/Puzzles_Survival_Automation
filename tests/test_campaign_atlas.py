from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from tasks.campaign_atlas import (
    ACTIVATED_TRANSPORT_INPUT_CEILING,
    CollectorDisposition,
    ContractKind,
    CrossDifficultyGeometryReport,
    FrameDisposition,
    FrameRejectionReason,
    InputBudgetAccounting,
    InputBudgetCategory,
    LandmarkBindingReport,
    LandmarkKind,
    NativeFrameProvenance,
    Rect,
    RegistrationResidualReport,
    SurveyPhase,
    build_empty_activated_session_report,
    classify_frame_candidate,
    default_activated_scan_contract,
    default_prep_scan_contract,
    dry_run_campaign_survey,
    validate_survey_session_report,
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
        self.assertEqual(contract.contract_kind, ContractKind.PREP)
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
        self.assertEqual(contract.maximum_auxiliary_inputs, 0)
        self.assertEqual(contract.maximum_sessions, 0)
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

    def test_activated_scan_contract_enforces_272_partitioned_ceiling(self) -> None:
        contract = default_activated_scan_contract()
        self.assertEqual(contract.contract_kind, ContractKind.ACTIVATED)
        self.assertEqual(contract.maximum_transport_inputs, ACTIVATED_TRANSPORT_INPUT_CEILING)
        self.assertEqual(contract.maximum_transport_inputs, 272)
        self.assertEqual(contract.maximum_edge_steps_per_direction * 4, 128)
        self.assertEqual(contract.maximum_overlapping_viewports, 128)
        self.assertEqual(contract.maximum_auxiliary_inputs, 16)
        self.assertEqual(contract.maximum_sessions, 1)
        self.assertFalse(contract.explicit_activation_required)
        self.assertFalse(contract.build_atlas)
        self.assertEqual(
            contract.difficulty_switch_policy,
            "explicit_comparison_only_never_recenter",
        )
        with self.assertRaises(ValueError):
            replace(contract, maximum_transport_inputs=271)
        with self.assertRaises(ValueError):
            replace(contract, maximum_auxiliary_inputs=17)
        with self.assertRaises(ValueError):
            replace(contract, maximum_sessions=2)

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

    def test_dry_run_rejects_activated_contract(self) -> None:
        with self.assertRaises(ValueError):
            dry_run_campaign_survey(default_activated_scan_contract())

    def test_frame_classifier_rejects_local_non_native_and_unhashed_candidates(self) -> None:
        local = classify_frame_candidate(
            provenance=None,
            mask_contract_id="campaign-map-fixed-hud-v1",
            local_candidate=True,
        )
        self.assertEqual(local.disposition, FrameDisposition.REJECTED)
        self.assertEqual(local.rejection_reason, FrameRejectionReason.LOCAL_CANDIDATE)

        non_native = classify_frame_candidate(
            provenance={
                **vars(provenance()),
                "width": 400,
                "height": 640,
            },
            mask_contract_id="campaign-map-fixed-hud-v1",
        )
        self.assertEqual(non_native.rejection_reason, FrameRejectionReason.NON_NATIVE_DIMENSIONS)

        unhashed = classify_frame_candidate(
            provenance={**vars(provenance()), "semantic_sha256": "nope"},
            mask_contract_id="campaign-map-fixed-hud-v1",
        )
        self.assertEqual(unhashed.rejection_reason, FrameRejectionReason.UNHASHED)

        accepted = classify_frame_candidate(
            provenance=provenance(),
            mask_contract_id="campaign-map-fixed-hud-v1",
        )
        self.assertEqual(accepted.disposition, FrameDisposition.ACCEPTED)

    def test_input_budget_accounting_partitions_and_rejects_overrun(self) -> None:
        accounting = InputBudgetAccounting()
        self.assertEqual(accounting.maximum_transport_inputs, 272)
        updated = accounting.record(InputBudgetCategory.EDGE_CLAMP)
        self.assertEqual(updated.edge_clamp_used, 1)
        with self.assertRaises(ValueError):
            InputBudgetAccounting(edge_clamp_used=129)

    def test_empty_activated_session_report_is_evidence_required_zero_input(self) -> None:
        report = build_empty_activated_session_report(
            session_id="campaign-survey-test-session",
            created_at_utc="2026-07-23T20:00:00Z",
        )
        validate_survey_session_report(report)
        self.assertEqual(report.disposition, CollectorDisposition.EVIDENCE_REQUIRED)
        self.assertFalse(report.transport_dispatched)
        self.assertEqual(report.accounting.transport_inputs_used, 0)
        self.assertEqual(report.manifest.maximum_transport_inputs, 272)
        self.assertFalse(report.manifest.registration_authorizes_input)

    def test_registration_residual_never_authorizes_input(self) -> None:
        with self.assertRaises(ValueError):
            RegistrationResidualReport(
                candidate_sha256="a" * 64,
                reference_sha256="b" * 64,
                residual_px=1.0,
                inliers=4,
                matches=8,
                overlap_ratio=0.4,
                authorizes_input=True,
            )

    def test_cross_difficulty_rejects_recenter_use(self) -> None:
        with self.assertRaises(ValueError):
            CrossDifficultyGeometryReport(
                difficulty_a=1,
                difficulty_b=2,
                compared=True,
                used_as_recenter=True,
                conclusion="invalid",
            )

    def test_landmark_requires_spatial_association(self) -> None:
        with self.assertRaises(ValueError):
            LandmarkBindingReport(
                kind=LandmarkKind.CHAPTER,
                label="Chapter 9",
                supporting_frame_sha256="c" * 64,
                spatially_associated=False,
            )


    def test_complete_requires_closed_loop_and_associated_overlaps(self) -> None:
        report = build_empty_activated_session_report(
            session_id="campaign-survey-complete-gate",
            created_at_utc="2026-07-23T22:00:00Z",
        )
        # Empty evidence_required report validates.
        validate_survey_session_report(report)
        with self.assertRaises(ValueError):
            # Force complete without closed loop / associations.
            from dataclasses import replace

            validate_survey_session_report(
                replace(
                    report,
                    disposition=CollectorDisposition.NATIVE_SURVEY_COMPLETE,
                    reason="invalid",
                )
            )

    def test_unresolved_journal_rejects_safe_terminal_claim(self) -> None:
        from tasks.campaign_atlas import (
            InputLifecycle,
            NavigationEvidenceSequence,
            NavigationJournalEntry,
            InputBudgetCategory,
            SurveyPhase,
        )

        evidence = NavigationEvidenceSequence(
            source_path="a.png",
            immediate_before_path="b.png",
            transport_record_path="t.json",
            immediate_post_path="c.png",
            semantic_result_path="r.json",
        )
        with self.assertRaises(ValueError):
            NavigationJournalEntry(
                input_ordinal=1,
                phase=SurveyPhase.EDGE_TOP,
                budget_category=InputBudgetCategory.EDGE_CLAMP,
                evidence=evidence,
                terminal_classification="safe_terminal",
                lifecycle=InputLifecycle.UNRESOLVED,
            )


if __name__ == "__main__":
    unittest.main()
