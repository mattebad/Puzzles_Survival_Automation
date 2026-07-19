"""Offline tests for the frame-identity-bound semantic OCR crop pipeline."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from types import MappingProxyType

import numpy as np

from tasks.perception_bundle import NativeFrameIdentity, bundle_from_identity
from tasks import semantic_ocr_crop as crop_module
from tasks.semantic_ocr_crop import (
    CropProvenance,
    CropRoiRequest,
    ExclusionMask,
    MAX_PADDING_PX,
    NormalizationOp,
    ObservationStatus,
    OcrMode,
    PaddingSpec,
    SemanticOcrCropError,
    SemanticOcrObservation,
    ambiguous_observation,
    compute_transport_digest,
    observation_grants_dispatch,
    prepare_ocr_crop,
    run_semantic_ocr,
    to_immutable_ocr_observation,
)


PROFILE = "pns-bluestacks-5-p64-800x1280-v1"


def make_frame(*, width: int = 800, height: int = 1280, seed: int = 0) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (seed & 0xFF, (seed * 3) & 0xFF, (seed * 7) & 0xFF)
    frame[100:140, 200:360] = (240, 240, 240)
    return frame


def make_identity(frame: np.ndarray, **overrides) -> NativeFrameIdentity:
    transport = compute_transport_digest(frame)
    values = dict(
        capture_kind="fixture",
        runtime_session_id="ocr-crop-fixture",
        capture_ordinal=1,
        capture_completed_monotonic=1000.0,
        transport_sha256=transport,
        semantic_sha256=hashlib.sha256((transport + ":semantic").encode("ascii")).hexdigest(),
        runtime_profile_id=PROFILE,
        width=int(frame.shape[1]),
        height=int(frame.shape[0]),
        label="fixture-ocr-crop",
    )
    values.update(overrides)
    return NativeFrameIdentity(**values)


class SemanticOcrCropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = make_frame(seed=11)
        self.identity = make_identity(self.frame)

    def test_roi_within_bounds_and_rejects_out_of_bounds(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        provenance, pixels = prepare_ocr_crop(self.frame, request)
        self.assertEqual(provenance.effective_roi, (200, 100, 360, 140))
        self.assertEqual(pixels.shape[0], 40)
        self.assertEqual(pixels.shape[1], 160)
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(self.frame, CropRoiRequest(self.identity, (-1, 0, 10, 10)))
        self.assertEqual(raised.exception.reason_code, "ROI_OUT_OF_BOUNDS")
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(self.frame, CropRoiRequest(self.identity, (790, 0, 810, 10)))
        self.assertEqual(raised.exception.reason_code, "ROI_OUT_OF_BOUNDS")

    def test_bounded_padding_expands_roi_and_rejects_over_bound(self) -> None:
        padding = PaddingSpec(left=4, top=2, right=6, bottom=3)
        request = CropRoiRequest(self.identity, (200, 100, 360, 140), padding=padding)
        provenance, _pixels = prepare_ocr_crop(self.frame, request)
        self.assertEqual(provenance.effective_roi, (196, 98, 366, 143))
        self.assertEqual(provenance.padding, (4, 2, 6, 3))
        with self.assertRaises(SemanticOcrCropError) as raised:
            PaddingSpec(left=MAX_PADDING_PX + 1)
        self.assertEqual(raised.exception.reason_code, "PADDING_EXCEEDS_BOUND")
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(
                self.frame,
                CropRoiRequest(self.identity, (1, 1, 10, 10), padding=PaddingSpec(left=2)),
            )
        self.assertEqual(raised.exception.reason_code, "PADDING_OUT_OF_BOUNDS")

    def test_exclusion_masks_block_roi_and_padding_escape(self) -> None:
        mask = ExclusionMask((350, 90, 400, 150))
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(
                self.frame,
                CropRoiRequest(self.identity, (200, 100, 360, 140), exclusion_masks=(mask,)),
            )
        self.assertEqual(raised.exception.reason_code, "ROI_INTERSECTS_EXCLUSION")
        escape = ExclusionMask((360, 90, 380, 150))
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(
                self.frame,
                CropRoiRequest(
                    self.identity,
                    (200, 100, 360, 140),
                    padding=PaddingSpec(right=10),
                    exclusion_masks=(escape,),
                ),
            )
        self.assertEqual(raised.exception.reason_code, "PADDING_ESCAPES_EXCLUSION")
        safe = ExclusionMask((500, 500, 560, 560))
        provenance, _ = prepare_ocr_crop(
            self.frame,
            CropRoiRequest(
                self.identity,
                (200, 100, 360, 140),
                padding=PaddingSpec(right=5),
                exclusion_masks=(safe,),
            ),
        )
        self.assertEqual(provenance.exclusion_masks, (safe.box,))

    def test_constrained_ocr_modes_and_unknown_mode_fail_closed(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        calls: list[int] = []

        def engine(_image, psm: int) -> str:
            calls.append(psm)
            return f"token{psm}"

        uniform = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=engine,
        )
        self.assertEqual(uniform.status, ObservationStatus.OK)
        self.assertEqual(calls, [6])
        calls.clear()
        sparse = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.SPARSE_TEXT,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=engine,
        )
        self.assertEqual(sparse.text, "token11")
        calls.clear()
        both = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_AND_SPARSE,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=engine,
        )
        self.assertEqual(calls, [6, 11])
        self.assertIn("token6", both.text)
        self.assertIn("token11", both.text)
        with self.assertRaises(SemanticOcrCropError) as raised:
            crop_module._psms_for_mode("fuzzy")  # type: ignore[arg-type]
        self.assertEqual(raised.exception.reason_code, "UNKNOWN_OCR_MODE")

    def test_bounded_normalization_only(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        _prov, gray = prepare_ocr_crop(
            self.frame,
            request,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
        )
        self.assertEqual(gray.ndim, 2)
        _prov, scaled = prepare_ocr_crop(
            self.frame,
            request,
            normalization=(NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_2X),
        )
        self.assertEqual(scaled.shape[0], 80)
        self.assertEqual(scaled.shape[1], 320)
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(self.frame, request, normalization=("blur",))  # type: ignore[arg-type]
        self.assertEqual(raised.exception.reason_code, "INVALID_NORMALIZATION_SEQUENCE")

    def test_normalization_sequence_is_closed_and_non_compounding(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        accepted = (
            (),
            (NormalizationOp.TO_GRAYSCALE,),
            (NormalizationOp.UPSCALE_2X,),
            (NormalizationOp.UPSCALE_3X,),
            (NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_2X),
            (NormalizationOp.TO_GRAYSCALE, NormalizationOp.UPSCALE_3X),
        )
        for plan in accepted:
            provenance, _pixels = prepare_ocr_crop(
                self.frame,
                request,
                normalization=plan,
            )
            self.assertEqual(provenance.normalization, plan)

        rejected = (
            (NormalizationOp.TO_GRAYSCALE, NormalizationOp.TO_GRAYSCALE),
            (NormalizationOp.UPSCALE_2X, NormalizationOp.UPSCALE_3X),
            (NormalizationOp.UPSCALE_3X, NormalizationOp.UPSCALE_3X),
            (NormalizationOp.UPSCALE_2X, NormalizationOp.TO_GRAYSCALE),
            ("blur",),
        )
        for plan in rejected:
            with self.subTest(plan=plan):
                with self.assertRaises(SemanticOcrCropError) as raised:
                    prepare_ocr_crop(
                        self.frame,
                        request,
                        normalization=plan,  # type: ignore[arg-type]
                    )
                self.assertEqual(
                    raised.exception.reason_code,
                    "INVALID_NORMALIZATION_SEQUENCE",
                )
                observation = run_semantic_ocr(
                    self.frame,
                    request,
                    ocr_mode=OcrMode.UNIFORM_BLOCK,
                    normalization=plan,  # type: ignore[arg-type]
                    ocr_engine=lambda _image, _psm: "unreachable",
                )
                self.assertEqual(observation.status, ObservationStatus.INVALID)
                self.assertEqual(
                    observation.reason_code,
                    "INVALID_NORMALIZATION_SEQUENCE",
                )

    def test_same_capture_identity_binds_observation(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        observation = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=lambda _image, _psm: "Supply Depot",
        )
        self.assertTrue(observation.source_frame.same_capture_event(self.identity))
        self.assertEqual(observation.source_frame.transport_sha256, self.identity.transport_sha256)
        self.assertEqual(observation.source_frame.semantic_sha256, self.identity.semantic_sha256)
        bundle = bundle_from_identity(self.identity).with_ocr(to_immutable_ocr_observation(observation))
        self.assertEqual(len(bundle.ocr_observations), 1)

    def test_forged_and_cross_capture_identities_rejected(self) -> None:
        other_frame = make_frame(seed=99)
        other_identity = make_identity(
            other_frame,
            capture_ordinal=2,
            runtime_session_id="other",
        )
        forged = replace(self.identity, transport_sha256=other_identity.transport_sha256)
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(self.frame, CropRoiRequest(forged, (200, 100, 360, 140)))
        self.assertEqual(raised.exception.reason_code, "TRANSPORT_DIGEST_MISMATCH")
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(other_frame, CropRoiRequest(self.identity, (200, 100, 360, 140)))
        self.assertEqual(raised.exception.reason_code, "TRANSPORT_DIGEST_MISMATCH")
        wrong_geometry = replace(self.identity, width=640, height=1136)
        with self.assertRaises(SemanticOcrCropError) as raised:
            prepare_ocr_crop(self.frame, CropRoiRequest(wrong_geometry, (200, 100, 360, 140)))
        self.assertEqual(raised.exception.reason_code, "FRAME_GEOMETRY_MISMATCH")
        observation = run_semantic_ocr(
            self.frame,
            CropRoiRequest(other_identity, (200, 100, 360, 140)),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            ocr_engine=lambda _image, _psm: "x",
        )
        self.assertEqual(observation.status, ObservationStatus.INVALID)
        self.assertEqual(observation.reason_code, "TRANSPORT_DIGEST_MISMATCH")

    def test_immutability_and_no_numpy_retention(self) -> None:
        observation = run_semantic_ocr(
            self.frame,
            CropRoiRequest(self.identity, (200, 100, 360, 140)),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=lambda _image, _psm: "text",
        )
        with self.assertRaises(Exception):
            observation.text = "mutated"  # type: ignore[misc]
        with self.assertRaises(Exception):
            observation.supporting_evidence.append("x")  # type: ignore[attr-defined]
        with self.assertRaises(TypeError):
            observation.metadata["k"] = "v"  # type: ignore[index]
        self.assertIsInstance(observation.metadata, MappingProxyType)
        encoded = json.dumps(
            {
                "text": observation.text,
                "roi": observation.effective_roi,
                "status": observation.status.value,
                "mode": observation.ocr_mode.value,
            },
            sort_keys=True,
        )
        self.assertNotIn("ndarray", encoded.lower())
        self.assertNotIn("dtype", encoded.lower())
        for name, value in observation.__dict__.items():
            self.assertFalse(isinstance(value, np.ndarray), name)

    def test_metadata_copies_mappingproxy_backing_dict(self) -> None:
        backing = {"source": "fixture"}
        observation = SemanticOcrObservation(
            source_frame=self.identity,
            text="text",
            requested_roi=(200, 100, 360, 140),
            effective_roi=(200, 100, 360, 140),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            exclusion_masks=(),
            padding=(0, 0, 0, 0),
            status=ObservationStatus.OK,
            reason_code="ok",
            confidence=1.0,
            metadata=MappingProxyType(backing),
        )
        backing["source"] = "mutated"
        backing["new"] = "value"
        self.assertEqual(dict(observation.metadata), {"source": "fixture"})
        with self.assertRaises(SemanticOcrCropError) as raised:
            SemanticOcrObservation(
                source_frame=self.identity,
                text="text",
                requested_roi=(200, 100, 360, 140),
                effective_roi=(200, 100, 360, 140),
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(),
                exclusion_masks=(),
                padding=(0, 0, 0, 0),
                status=ObservationStatus.OK,
                reason_code="ok",
                confidence=1.0,
                metadata={"bad": 1},  # type: ignore[dict-item]
            )
        self.assertEqual(raised.exception.reason_code, "INVALID_IMMUTABLE_FIELD")

    def test_provenance_validates_immutable_tuple_elements(self) -> None:
        with self.assertRaises(SemanticOcrCropError) as raised:
            CropProvenance(
                source_frame=self.identity,
                requested_roi=(200, 100, 360, 140),
                effective_roi=(200, 100, 360, 140),
                padding=(0, 0, 0, "bad"),  # type: ignore[arg-type]
                exclusion_masks=(),
                normalization=(),
                transport_sha256=self.identity.transport_sha256,
                semantic_sha256=self.identity.semantic_sha256,
            )
        self.assertEqual(raised.exception.reason_code, "INVALID_IMMUTABLE_FIELD")
        with self.assertRaises(SemanticOcrCropError) as raised:
            CropProvenance(
                source_frame=self.identity,
                requested_roi=(200, 100, 360, 140),
                effective_roi=(200, 100, 360, 140),
                padding=(0, 0, 0, 0),
                exclusion_masks=(),
                normalization=("blur",),  # type: ignore[arg-type]
                transport_sha256=self.identity.transport_sha256,
                semantic_sha256=self.identity.semantic_sha256,
            )
        self.assertEqual(
            raised.exception.reason_code,
            "INVALID_NORMALIZATION_SEQUENCE",
        )

    def test_debug_artifacts_opt_in_deterministic_and_default_off(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))
        quiet = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=lambda _image, _psm: "a",
        )
        self.assertIsNone(quiet.debug_artifact_name)
        self.assertIsNone(quiet.debug_artifact_sha256)
        with tempfile.TemporaryDirectory() as directory:
            first = run_semantic_ocr(
                self.frame,
                request,
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(NormalizationOp.TO_GRAYSCALE,),
                ocr_engine=lambda _image, _psm: "a",
                enable_debug_artifacts=True,
                debug_dir=directory,
            )
            second = run_semantic_ocr(
                self.frame,
                request,
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(NormalizationOp.TO_GRAYSCALE,),
                ocr_engine=lambda _image, _psm: "a",
                enable_debug_artifacts=True,
                debug_dir=directory,
            )
            self.assertEqual(first.debug_artifact_name, second.debug_artifact_name)
            self.assertEqual(first.debug_artifact_sha256, second.debug_artifact_sha256)
            path = Path(directory) / first.debug_artifact_name
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), first.debug_artifact_sha256)
            self.assertNotIn("tests/fixtures", path.as_posix())
            self.assertNotIn("evidence/", path.as_posix())
        disabled = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            ocr_engine=lambda _image, _psm: "a",
            enable_debug_artifacts=False,
            debug_dir="should-not-write",
        )
        self.assertEqual(disabled.status, ObservationStatus.INVALID)
        self.assertEqual(disabled.reason_code, "DEBUG_NOT_ENABLED")

    def test_ocr_empty_and_ambiguous_negative_controls(self) -> None:
        empty = run_semantic_ocr(
            self.frame,
            CropRoiRequest(self.identity, (200, 100, 360, 140)),
            ocr_mode=OcrMode.SPARSE_TEXT,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=lambda _image, _psm: "   ",
        )
        self.assertEqual(empty.status, ObservationStatus.UNKNOWN)
        self.assertEqual(empty.reason_code, "OCR_EMPTY")
        ambiguous = ambiguous_observation(
            self.identity,
            requested_roi=(200, 100, 360, 140),
            effective_roi=(200, 100, 360, 140),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            reason_code="OCR_AMBIGUOUS",
            text="??? ",
        )
        self.assertEqual(ambiguous.status, ObservationStatus.AMBIGUOUS)
        with self.assertRaises(SemanticOcrCropError):
            to_immutable_ocr_observation(ambiguous)
        self.assertFalse(observation_grants_dispatch(empty))
        self.assertFalse(observation_grants_dispatch(ambiguous))

    def test_invalid_unknown_fail_closed_and_no_dispatch_authority(self) -> None:
        invalid = run_semantic_ocr(
            self.frame,
            CropRoiRequest(self.identity, (0, 0, 900, 10)),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            ocr_engine=lambda _image, _psm: "should-not-run",
        )
        self.assertEqual(invalid.status, ObservationStatus.INVALID)
        self.assertEqual(invalid.reason_code, "ROI_OUT_OF_BOUNDS")
        self.assertFalse(observation_grants_dispatch(invalid))
        ok = SemanticOcrObservation(
            source_frame=self.identity,
            text="ok",
            requested_roi=(1, 1, 2, 2),
            effective_roi=(1, 1, 2, 2),
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(),
            exclusion_masks=(),
            padding=(0, 0, 0, 0),
            status=ObservationStatus.OK,
            reason_code="ok",
            confidence=1.0,
        )
        self.assertFalse(observation_grants_dispatch(ok))

    def test_invalid_source_frame_and_request_fail_deterministically(self) -> None:
        with self.assertRaises(SemanticOcrCropError) as raised:
            CropRoiRequest(None, (1, 1, 2, 2))  # type: ignore[arg-type]
        self.assertEqual(raised.exception.reason_code, "INVALID_SOURCE_FRAME")
        with self.assertRaises(SemanticOcrCropError) as raised:
            run_semantic_ocr(
                self.frame,
                object(),  # type: ignore[arg-type]
                ocr_mode=OcrMode.UNIFORM_BLOCK,
            )
        self.assertEqual(raised.exception.reason_code, "INVALID_REQUEST")
        with self.assertRaises(SemanticOcrCropError) as raised:
            CropRoiRequest(self.identity, "not-a-box")  # type: ignore[arg-type]
        self.assertEqual(raised.exception.reason_code, "INVALID_BOX")

    def test_ocr_engine_exception_returns_invalid_without_swallowing_baseexception(self) -> None:
        request = CropRoiRequest(self.identity, (200, 100, 360, 140))

        def failed_engine(_image, _psm):
            raise RuntimeError("engine unavailable")

        failed = run_semantic_ocr(
            self.frame,
            request,
            ocr_mode=OcrMode.UNIFORM_BLOCK,
            normalization=(NormalizationOp.TO_GRAYSCALE,),
            ocr_engine=failed_engine,
        )
        self.assertEqual(failed.status, ObservationStatus.INVALID)
        self.assertEqual(failed.reason_code, "OCR_ENGINE_ERROR")

        def interrupted_engine(_image, _psm):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            run_semantic_ocr(
                self.frame,
                request,
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(NormalizationOp.TO_GRAYSCALE,),
                ocr_engine=interrupted_engine,
            )

    def test_module_keeps_ocr_and_authorization_distinct(self) -> None:
        source = inspect.getsource(crop_module)
        self.assertNotIn("AUTHORIZE", source)
        self.assertNotIn("dispatch_input", source)
        self.assertNotIn("pnsctl", source)
        self.assertIn("never grants dispatch", observation_grants_dispatch.__doc__.lower())


if __name__ == "__main__":
    unittest.main()
