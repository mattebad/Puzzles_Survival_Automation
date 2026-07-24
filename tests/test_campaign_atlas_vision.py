from __future__ import annotations

import unittest

import cv2
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
        from tasks.campaign_atlas_vision import (
            loop_closure_accepted,
            overlap_association_accepted,
            registration_progress_outcome,
        )

        failed = RegistrationMeasurement(
            "none", None, 0.0, float("inf"), 0, 0, 0.0, "insufficient_features", 0.0
        )
        self.assertEqual(registration_progress_outcome(failed), "unresolved")
        inf_residual = RegistrationMeasurement(
            "none", None, 0.0, float("inf"), 0, 3, 0.0, "insufficient_matches", 0.0
        )
        self.assertEqual(registration_progress_outcome(inf_residual), "unresolved")
        no_progress = RegistrationMeasurement(
            "translation", None, 1.0, 2.0, 30, 40, 0.9, "measured", 3.0
        )
        self.assertEqual(registration_progress_outcome(no_progress), "no_progress")
        progress = RegistrationMeasurement(
            "translation", None, 1.0, 4.0, 30, 40, 0.7, "measured", 40.0
        )
        self.assertEqual(registration_progress_outcome(progress), "progress")
        self.assertTrue(overlap_association_accepted(progress))
        self.assertFalse(loop_closure_accepted(progress))
        self.assertTrue(loop_closure_accepted(no_progress))
        weak = RegistrationMeasurement(
            "translation", None, 0.2, 3.0, 12, 12, 0.9, "measured", 2.0
        )
        self.assertFalse(overlap_association_accepted(weak))

    def test_tier_targets_are_measured_from_shifted_current_frame(self) -> None:
        from pathlib import Path

        from tasks.campaign_atlas_vision import measured_survey_target
        from tasks.campaign_auto_battle_vision import ASSET_ROOT, TIER_ONE_ROI, TIER_TWO_ROI

        root = Path(__file__).resolve().parents[1]
        session = (
            root
            / ".local-captures/flow-delivery/CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / "survey-20260724T012057293610Z"
            / "runtime"
            / "frames"
        )
        if session.is_dir():
            f258 = cv2.imread(str(session / "0258-difficulty-tier-1-immediate-before.png"))
            f261 = cv2.imread(str(session / "0261-difficulty-tier-2-immediate-before.png"))
            self.assertIsNotNone(f258)
            self.assertIsNotNone(f261)
            assert f258 is not None and f261 is not None
            # Shift the top control band by a few pixels to prove dynamic binding.
            shifted = np.zeros_like(f261)
            shifted[:, 3:] = f261[:, :-3]
            tier_two, score_two = measured_survey_target(shifted, "campaign-tier-2")
            self.assertGreater(score_two, 0.90)
            self.assertNotEqual(tier_two, TIER_TWO_ROI)
            self.assertEqual(tier_two[0], 525)  # 522 + 3px shift
            tier_one, score_one = measured_survey_target(f258, "campaign-tier-1")
            self.assertGreater(score_one, 0.90)
            self.assertNotEqual(tier_one, TIER_ONE_ROI)
            self.assertLess(tier_one[2], tier_two[0])
            return

        # Offline fallback when retained frames are unavailable.
        tier1_u = cv2.imread(str(ASSET_ROOT / "tier1_unselected.png"), cv2.IMREAD_COLOR)
        tier2_s = cv2.imread(str(ASSET_ROOT / "tier2_selected.png"), cv2.IMREAD_COLOR)
        self.assertIsNotNone(tier1_u)
        self.assertIsNotNone(tier2_s)
        assert tier1_u is not None and tier2_s is not None
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[65:133, 415:512] = (30, 30, 30)
        frame[65:133, 525:625] = (40, 190, 230)
        x0, y0 = 418, 68
        h, w = tier1_u.shape[:2]
        frame[y0 : y0 + h, x0 : x0 + w] = tier1_u
        hs, ws = tier2_s.shape[:2]
        frame[y0 : y0 + hs, 525 : 525 + ws] = tier2_s
        tier_one, score_one = measured_survey_target(frame, "campaign-tier-1")
        self.assertGreater(score_one, 0.90)
        self.assertNotEqual(tier_one, TIER_ONE_ROI)

    def test_selected_state_disambiguation_and_mismatch_zero_bind(self) -> None:
        from pathlib import Path

        from tasks.campaign_atlas_vision import (
            CURRENT_TARGET_TEMPLATE_THRESHOLD,
            measured_survey_target,
        )

        root = Path(__file__).resolve().parents[1]
        session = (
            root
            / ".local-captures/flow-delivery/CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / "survey-20260724T012057293610Z"
            / "runtime"
            / "frames"
        )
        if not session.is_dir():
            self.skipTest("retained survey frames unavailable")
        f258 = cv2.imread(str(session / "0258-difficulty-tier-1-immediate-before.png"))
        f261 = cv2.imread(str(session / "0261-difficulty-tier-2-immediate-before.png"))
        self.assertIsNotNone(f258)
        self.assertIsNotNone(f261)
        assert f258 is not None and f261 is not None
        roi, score = measured_survey_target(f261, "campaign-tier-2")
        self.assertGreaterEqual(score, CURRENT_TARGET_TEMPLATE_THRESHOLD)
        self.assertEqual(roi, (522, 65, 620, 133))
        with self.assertRaises(RuntimeError) as blocked:
            measured_survey_target(f258, "campaign-tier-2")
        self.assertIn("tier selection state mismatch", str(blocked.exception))
        # Dual-control template remains above-threshold only for the old selected look;
        # survey binding must not fall back to it or lower the 0.55 threshold.
        from tasks.campaign_auto_battle_vision import ASSET_ROOT

        dual = cv2.imread(str(ASSET_ROOT / "tier_controls.png"), cv2.IMREAD_GRAYSCALE)
        search = cv2.cvtColor(f261[35:190, 320:710], cv2.COLOR_BGR2GRAY)
        response = cv2.matchTemplate(search, dual, cv2.TM_CCOEFF_NORMED)
        _, dual_score, _, _ = cv2.minMaxLoc(response)
        self.assertLess(dual_score, CURRENT_TARGET_TEMPLATE_THRESHOLD)
        self.assertAlmostEqual(dual_score, 0.474, places=2)

    def test_campaign_exit_unhighlighted_and_highlighted_dynamic_bind(self) -> None:
        from pathlib import Path

        from tasks.campaign_atlas_vision import (
            CAMPAIGN_EXIT_TEMPLATE_THRESHOLD,
            measured_survey_target,
        )
        from tasks.campaign_auto_battle_vision import ASSET_ROOT, CAMPAIGN_EXIT_ROI

        root = Path(__file__).resolve().parents[1]
        frame_path = (
            root
            / ".local-captures/flow-delivery/CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
            / "survey-20260724T021222146973Z"
            / "runtime"
            / "frames"
            / "0006-campaign-exit-home-immediate-before.png"
        )
        if not frame_path.is_file():
            self.skipTest("retained exit-before frame unavailable")
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        assert frame is not None
        # Highlighted-only template is below threshold on the unhighlighted control.
        highlighted = cv2.imread(str(ASSET_ROOT / "campaign_exit.png"), cv2.IMREAD_GRAYSCALE)
        search = cv2.cvtColor(frame[780:1140, 560:800], cv2.COLOR_BGR2GRAY)
        response = cv2.matchTemplate(search, highlighted, cv2.TM_CCOEFF_NORMED)
        _, highlighted_score, _, _ = cv2.minMaxLoc(response)
        self.assertLess(highlighted_score, CAMPAIGN_EXIT_TEMPLATE_THRESHOLD)
        self.assertAlmostEqual(highlighted_score, 0.199, places=2)
        roi, score = measured_survey_target(frame, "campaign-exit-base")
        self.assertGreaterEqual(score, CAMPAIGN_EXIT_TEMPLATE_THRESHOLD)
        self.assertEqual(roi, (690, 920, 800, 1060))
        # Shifted frame proves measurement is dynamic, not a static-coordinate authorize.
        shifted = np.zeros_like(frame)
        shifted[:, :-3] = frame[:, 3:]
        shifted_roi, shifted_score = measured_survey_target(shifted, "campaign-exit-base")
        self.assertGreaterEqual(shifted_score, CAMPAIGN_EXIT_TEMPLATE_THRESHOLD)
        self.assertEqual(shifted_roi, (687, 920, 797, 1060))
        self.assertNotEqual(shifted_roi, CAMPAIGN_EXIT_ROI)
        # Highlighted compatibility: paste highlighted template into search band.
        highlighted_bgr = cv2.imread(str(ASSET_ROOT / "campaign_exit.png"), cv2.IMREAD_COLOR)
        self.assertIsNotNone(highlighted_bgr)
        assert highlighted_bgr is not None
        synthetic = np.zeros((1280, 800, 3), dtype=np.uint8)
        hy, hx = 860, 600
        hh, hw = highlighted_bgr.shape[:2]
        synthetic[hy : hy + hh, hx : hx + hw] = highlighted_bgr
        highlighted_roi, highlighted_bind = measured_survey_target(
            synthetic, "campaign-exit-base"
        )
        self.assertGreaterEqual(highlighted_bind, CAMPAIGN_EXIT_TEMPLATE_THRESHOLD)
        self.assertEqual(highlighted_roi, (hx, hy, hx + hw, hy + hh))
        self.assertNotEqual(highlighted_roi, CAMPAIGN_EXIT_ROI)

    def test_campaign_exit_rejects_static_fallback_without_template_match(self) -> None:
        from types import SimpleNamespace

        from scripts.flow_delivery_campaign_atlas_bluestacks import require_bound_survey_target
        from tasks.campaign_atlas_vision import (
            is_compile_time_static_survey_roi,
            measured_survey_target,
        )
        from tasks.campaign_auto_battle_vision import CAMPAIGN_EXIT_ROI

        self.assertTrue(
            is_compile_time_static_survey_roi("campaign-exit-base", CAMPAIGN_EXIT_ROI)
        )
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        with self.assertRaises(RuntimeError) as missing:
            measured_survey_target(blank, "campaign-exit-base")
        self.assertIn("campaign-exit-base not bound", str(missing.exception))
        with self.assertRaises(RuntimeError) as no_frame:
            require_bound_survey_target(
                SimpleNamespace(targets=(("campaign-exit-base", CAMPAIGN_EXIT_ROI),)),
                "campaign-exit-base",
                frame=None,
            )
        self.assertIn("current native frame is required", str(no_frame.exception))
        with self.assertRaises(RuntimeError) as base_request:
            require_bound_survey_target(
                SimpleNamespace(targets=()),
                "campaign-base-request",
                frame=blank,
            )
        self.assertIn("campaign-base-request", str(base_request.exception).casefold())

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

    def test_frame_digest_differs_from_raw_png_payload_hash(self) -> None:
        import hashlib

        import cv2
        import numpy as np

        from tasks.campaign_atlas_vision import frame_digest

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[500:700, 200:400] = (10, 20, 30)
        ok, encoded = cv2.imencode(".png", frame)
        self.assertTrue(ok)
        payload = encoded.tobytes()
        # Transport/file hash is the payload; semantic is frame_digest(decoded).
        transport = hashlib.sha256(payload).hexdigest()
        semantic = frame_digest(frame)
        self.assertEqual(semantic, hashlib.sha256(payload).hexdigest())
        # A raw on-disk payload that is not the cv2 re-encode must not be forced equal.
        rawish = b"\x89PNG\r\n\x1a\n" + payload[8:]
        if rawish != payload:
            self.assertNotEqual(hashlib.sha256(rawish).hexdigest(), semantic)
        self.assertEqual(len(transport), 64)
        self.assertEqual(len(semantic), 64)

    def test_measure_requires_semantic_digest_not_transport_payload_hash(self) -> None:
        import hashlib

        import numpy as np

        from tasks.campaign_atlas import NativeFrameProvenance
        from tasks.campaign_atlas_vision import (
            OrbTranslationBackend,
            frame_digest,
            measure_campaign_frame_pair,
        )

        reference = np.zeros((1280, 800, 3), dtype=np.uint8)
        reference[400:800, 200:600] = (25, 40, 55)
        candidate = np.zeros((1280, 800, 3), dtype=np.uint8)
        candidate[420:820, 220:620] = (25, 40, 55)
        # Fake a transport payload hash that is not the semantic digest.
        fake_transport = "a" * 64
        semantic_ref = frame_digest(reference)
        semantic_cand = frame_digest(candidate)
        self.assertNotEqual(fake_transport, semantic_ref)
        with self.assertRaises(ValueError):
            measure_campaign_frame_pair(
                candidate,
                reference,
                candidate_provenance=NativeFrameProvenance(
                    source_id="c",
                    capture_kind="fixture",
                    runtime_session_id="s",
                    capture_ordinal=1,
                    capture_completed_monotonic=0.0,
                    transport_sha256=fake_transport,
                    semantic_sha256=fake_transport,
                    captured_at_utc="2026-07-24T00:00:00+00:00",
                    width=800,
                    height=1280,
                ),
                reference_provenance=NativeFrameProvenance(
                    source_id="r",
                    capture_kind="fixture",
                    runtime_session_id="s",
                    capture_ordinal=2,
                    capture_completed_monotonic=1.0,
                    transport_sha256=fake_transport,
                    semantic_sha256=fake_transport,
                    captured_at_utc="2026-07-24T00:00:01+00:00",
                    width=800,
                    height=1280,
                ),
                backend=OrbTranslationBackend(),
            )
        observation = measure_campaign_frame_pair(
            candidate,
            reference,
            candidate_provenance=NativeFrameProvenance(
                source_id="c",
                capture_kind="fixture",
                runtime_session_id="s",
                capture_ordinal=1,
                capture_completed_monotonic=0.0,
                transport_sha256=hashlib.sha256(b"transport-cand").hexdigest(),
                semantic_sha256=semantic_cand,
                captured_at_utc="2026-07-24T00:00:00+00:00",
                width=800,
                height=1280,
            ),
            reference_provenance=NativeFrameProvenance(
                source_id="r",
                capture_kind="fixture",
                runtime_session_id="s",
                capture_ordinal=2,
                capture_completed_monotonic=1.0,
                transport_sha256=hashlib.sha256(b"transport-ref").hexdigest(),
                semantic_sha256=semantic_ref,
                captured_at_utc="2026-07-24T00:00:01+00:00",
                width=800,
                height=1280,
            ),
            backend=OrbTranslationBackend(),
        )
        self.assertEqual(observation.candidate_sha256, semantic_cand)
        self.assertEqual(observation.reference_sha256, semantic_ref)


if __name__ == "__main__":
    unittest.main()
