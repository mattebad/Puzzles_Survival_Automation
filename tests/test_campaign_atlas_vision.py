from __future__ import annotations

import unittest

import numpy as np

from tasks.campaign_atlas import NativeFrameProvenance
from tasks.campaign_atlas_vision import (
    RegistrationMeasurement,
    campaign_hud_mask,
    measure_campaign_frame_pair,
    native_campaign_frame_guard,
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
        self.assertIn("pending_native_evidence", observation.reason)

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


if __name__ == "__main__":
    unittest.main()
