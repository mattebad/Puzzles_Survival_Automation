from __future__ import annotations

import unittest

import numpy as np

from tasks.campaign_atlas import NativeFrameProvenance
from tasks.campaign_atlas_vision import (
    RegistrationMeasurement,
    campaign_hud_mask,
    measure_campaign_frame_pair,
    native_campaign_frame_guard,
    registration_residual_report,
)


def provenance(semantic_sha256: str, ordinal: int) -> NativeFrameProvenance:
    return NativeFrameProvenance(
        source_id=f"native/frame-{ordinal:03d}.png",
        capture_kind="fixture",
        runtime_session_id="campaign-registration-test",
        capture_ordinal=ordinal,
        capture_completed_monotonic=float(ordinal),
        transport_sha256=semantic_sha256,
        semantic_sha256=semantic_sha256,
        captured_at_utc="2026-07-23T18:30:00+00:00",
        width=800,
        height=1280,
    )


class RecordingBackend:
    def __init__(self) -> None:
        self.mask: np.ndarray | None = None

    def measure(
        self, candidate: np.ndarray, reference: np.ndarray, mask: np.ndarray
    ) -> RegistrationMeasurement:
        self.mask = mask.copy()
        return RegistrationMeasurement("fake", None, 1.0, 0.0, 10, 12, 0.5, "measured")


class CampaignAtlasVisionTests(unittest.TestCase):
    def test_native_guard_accepts_only_exact_bgr_geometry(self) -> None:
        self.assertTrue(native_campaign_frame_guard(np.zeros((1280, 800, 3), dtype=np.uint8)))
        self.assertFalse(native_campaign_frame_guard(np.zeros((800, 1280, 3), dtype=np.uint8)))
        self.assertFalse(native_campaign_frame_guard(np.zeros((1280, 800), dtype=np.uint8)))

    def test_hud_mask_excludes_fixed_hud_and_preserves_scene(self) -> None:
        mask = campaign_hud_mask()
        self.assertEqual(mask.shape, (1280, 800))
        self.assertEqual(int(mask[20, 400]), 0)
        self.assertEqual(int(mask[400, 40]), 0)
        self.assertEqual(int(mask[300, 700]), 0)
        self.assertEqual(int(mask[1100, 400]), 0)
        self.assertEqual(int(mask[600, 400]), 255)

    def test_registration_requires_hash_bound_native_frames_and_injected_backend(self) -> None:
        candidate = np.zeros((1280, 800, 3), dtype=np.uint8)
        reference = np.full((1280, 800, 3), 7, dtype=np.uint8)
        backend = RecordingBackend()
        observation = measure_campaign_frame_pair(
            candidate,
            reference,
            candidate_provenance=provenance(
                "fa8f2c0951575503ea34bd706b9fc84f26d0d9ceb7272afc59d41fb77339e77d", 1
            ),
            reference_provenance=provenance(
                "55e517e14a9c602b8b46ae9ea4cb3d119bc0c526b600a6a0f6fcb778efc39ace", 2
            ),
            backend=backend,
        )
        self.assertIsNotNone(backend.mask)
        self.assertEqual(observation.measurement.model, "fake")
        self.assertFalse(observation.accepted)
        self.assertFalse(observation.authorizes_input)
        self.assertIn("never_authorizes_input", observation.reason)
        residual = registration_residual_report(observation)
        self.assertFalse(residual.authorizes_input)
        self.assertEqual(residual.inliers, 10)
        self.assertEqual(residual.overlap_ratio, 0.5)

    def test_hud_safe_pan_stays_inside_map_search_and_mask(self) -> None:
        from tasks.campaign_atlas_vision import hud_safe_central_region, hud_safe_pan_gesture
        from tasks.campaign_auto_battle_vision import MAP_SEARCH_ROI

        region = hud_safe_central_region()
        left, top, right, bottom = MAP_SEARCH_ROI
        self.assertGreaterEqual(region.left, left)
        self.assertGreaterEqual(region.top, top)
        self.assertLessEqual(region.right, right)
        self.assertLessEqual(region.bottom, bottom)
        for direction in ("top", "right", "bottom", "left"):
            gesture = hud_safe_pan_gesture(direction)
            for point in (gesture.start, gesture.end):
                self.assertTrue(region.left <= point[0] < region.right)
                self.assertTrue(region.top <= point[1] < region.bottom)

    def test_consequential_targets_are_rejected_for_survey(self) -> None:
        from tasks.campaign_atlas_vision import survey_target_is_consequential

        self.assertTrue(survey_target_is_consequential("campaign-challenge-1-20-9"))
        self.assertTrue(survey_target_is_consequential("campaign-lineup-challenge"))
        self.assertFalse(survey_target_is_consequential("campaign-tier-1"))
        self.assertFalse(survey_target_is_consequential("campaign-exit-base"))
        self.assertFalse(survey_target_is_consequential("campaign-chapter-9"))

    def test_registration_rejects_digest_mismatch(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            measure_campaign_frame_pair(
                frame,
                frame,
                candidate_provenance=NativeFrameProvenance(
                    **{
                        **vars(
                            provenance(
                                "fa8f2c0951575503ea34bd706b9fc84f26d0d9ceb7272afc59d41fb77339e77d",
                                1,
                            )
                        ),
                        "semantic_sha256": "f" * 64,
                    }
                ),
                reference_provenance=provenance(
                    "fa8f2c0951575503ea34bd706b9fc84f26d0d9ceb7272afc59d41fb77339e77d", 2
                ),
                backend=RecordingBackend(),
            )

    def test_failed_registration_is_unresolved_never_progress(self) -> None:
        from tasks.campaign_atlas_vision import registration_progress_outcome

        failed = RegistrationMeasurement(
            "none", None, 0.0, float("inf"), 0, 0, 0.0, "insufficient_features", 0.0
        )
        self.assertEqual(registration_progress_outcome(failed), "unresolved")
        inf_residual = RegistrationMeasurement(
            "none", None, 0.0, float("inf"), 0, 3, 0.0, "insufficient_matches", 0.0
        )
        self.assertEqual(registration_progress_outcome(inf_residual), "unresolved")
        no_progress = RegistrationMeasurement(
            "translation", None, 1.0, 2.0, 20, 40, 0.9, "measured", 3.0
        )
        self.assertEqual(registration_progress_outcome(no_progress), "no_progress")
        progress = RegistrationMeasurement(
            "translation", None, 1.0, 4.0, 20, 40, 0.7, "measured", 40.0
        )
        self.assertEqual(registration_progress_outcome(progress), "progress")

    def test_static_roi_targets_are_refused(self) -> None:
        from types import SimpleNamespace
        from tasks.campaign_atlas_vision import (
            COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS,
            require_measured_nonstatic_survey_target,
        )

        for identity, roi in COMPILE_TIME_STATIC_SURVEY_TARGET_ROIS.items():
            with self.subTest(identity=identity):
                recognition = SimpleNamespace(targets=((identity, roi),))
                with self.assertRaises(RuntimeError) as ctx:
                    require_measured_nonstatic_survey_target(recognition, identity)
                self.assertIn("evidence_required", str(ctx.exception))
                self.assertIn("static ROI", str(ctx.exception))

        measured = SimpleNamespace(targets=(("campaign-tier-1", (410, 70, 510, 128)),))
        self.assertEqual(
            require_measured_nonstatic_survey_target(measured, "campaign-tier-1"),
            (410, 70, 510, 128),
        )

    def test_weak_ocr_chapter_and_prison_binds_are_rejected(self) -> None:
        from tasks.campaign_atlas_vision import (
            chapter_roi_from_strong_spatial_evidence,
            prison_trial_roi_from_strong_spatial_evidence,
        )

        self.assertIsNone(
            chapter_roi_from_strong_spatial_evidence(
                number=7, targets={}, hits={"7": (10, 20, 30, 40)}
            )
        )
        self.assertEqual(
            chapter_roi_from_strong_spatial_evidence(
                number=7, targets={}, hits={"Chapter 7": (10, 20, 90, 50)}
            ),
            (10, 20, 90, 50),
        )
        self.assertIsNone(
            prison_trial_roi_from_strong_spatial_evidence({"Prison": (1, 2, 3, 4)})
        )
        self.assertEqual(
            prison_trial_roi_from_strong_spatial_evidence({"Prison Trial": (5, 6, 80, 40)}),
            (5, 6, 80, 40),
        )

    def test_measured_content_annotation_roi_is_not_map_search(self) -> None:
        from tasks.campaign_atlas_vision import measured_content_annotation_roi
        from tasks.campaign_auto_battle_vision import MAP_SEARCH_ROI

        roi = measured_content_annotation_roi()
        self.assertNotEqual(tuple(roi), tuple(MAP_SEARCH_ROI))


if __name__ == "__main__":
    unittest.main()
