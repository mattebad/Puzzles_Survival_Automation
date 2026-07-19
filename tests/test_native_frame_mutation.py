"""Offline tests for the controlled native-frame mutation corpus."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2

from tasks.native_frame_mutation import (
    DEFAULT_MANIFEST_RELATIVE,
    ExpectedOutcome,
    MAX_TRANSLATION_PX,
    MutationCase,
    MutationDecision,
    MutationEvaluation,
    MutationOperator,
    NativeFrameMutationError,
    generate_mutation_corpus,
    load_mutation_manifest,
    measure_mutation_metrics,
    serialize_mutation_result,
)
from tasks.semantic_ocr_crop import (
    CropRoiRequest,
    OcrMode,
    ObservationStatus,
    run_semantic_ocr,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / DEFAULT_MANIFEST_RELATIVE


def _payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class NativeFrameMutationTests(unittest.TestCase):
    def test_exact_manifest_and_operator_set(self) -> None:
        manifest = load_mutation_manifest(root=ROOT)
        self.assertEqual(manifest.schema_version, 1)
        self.assertEqual(manifest.max_translation_px, MAX_TRANSLATION_PX)
        self.assertEqual(len(manifest.cases), len(tuple(MutationOperator)))
        self.assertEqual(
            {case.operator for case in manifest.cases},
            set(MutationOperator),
        )
        self.assertEqual(
            {case.expected_outcome for case in manifest.cases},
            {ExpectedOutcome.ACCEPTED, ExpectedOutcome.REJECTED},
        )

    def test_manifest_rejects_extra_keys_and_parent_hash_drift(self) -> None:
        payload = _payload()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            extra = json.loads(json.dumps(payload))
            extra["unexpected"] = True
            path.write_text(json.dumps(extra), encoding="utf-8")
            with self.assertRaises(NativeFrameMutationError) as raised:
                load_mutation_manifest(path, root=ROOT)
            self.assertEqual(raised.exception.reason_code, "INVALID_SCHEMA_KEYS")

            drift = json.loads(json.dumps(payload))
            drift["cases"][0]["parent_source_sha256"] = "0" * 64
            path.write_text(json.dumps(drift), encoding="utf-8")
            with self.assertRaises(NativeFrameMutationError) as raised:
                load_mutation_manifest(path, root=ROOT)
            self.assertEqual(raised.exception.reason_code, "PARENT_SOURCE_HASH_MISMATCH")

    def test_public_case_contract_rejects_unbounded_translation_and_bad_parameters(self) -> None:
        manifest = load_mutation_manifest(root=ROOT)
        base = manifest.cases[3]
        with self.assertRaises(NativeFrameMutationError) as raised:
            replace(
                base,
                parameters={"dx": MAX_TRANSLATION_PX + 1, "dy": 0},
            )
        self.assertEqual(raised.exception.reason_code, "TRANSLATION_EXCEEDS_BOUND")
        with self.assertRaises(NativeFrameMutationError) as raised:
            replace(base, parameters={"dx": 1, "dy": 0.5})
        self.assertEqual(raised.exception.reason_code, "INVALID_SCHEMA")

    def test_generation_is_deterministic_and_preserves_sources(self) -> None:
        source_paths = [
            ROOT / case.parent_relative_path
            for case in load_mutation_manifest(root=ROOT).cases
        ]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = generate_mutation_corpus(root=ROOT, output_dir=first_dir)
            second = generate_mutation_corpus(root=ROOT, output_dir=second_dir)
        self.assertEqual(
            [item.output_sha256 for item in first.artifacts],
            [item.output_sha256 for item in second.artifacts],
        )
        self.assertEqual(first.metrics.unresolved_count, len(first.artifacts) - 1)
        self.assertEqual(first.metrics.observed_reject_count, 1)
        self.assertEqual(first.metrics.false_accept_count, 0)
        self.assertEqual(first.metrics.false_reject_count, 0)
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
        self.assertEqual(before, after)

    def test_all_outputs_are_native_rgba_and_records_have_distinct_mutation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(root=ROOT, output_dir=directory)
            for artifact in result.artifacts:
                self.assertTrue(Path(artifact.storage_path).is_file())
                self.assertEqual((artifact.width, artifact.height, artifact.channels), (800, 1280, 4))
                self.assertEqual(artifact.identity_status, "valid" if artifact.operator is not MutationOperator.STALE_FRAME_SUBSTITUTION else "rejected")
                self.assertFalse(
                    artifact.parent_identity.same_capture_event(artifact.mutation_identity)
                )
                decoded = cv2.imread(artifact.storage_path, cv2.IMREAD_UNCHANGED)
                self.assertIsNotNone(decoded)
                assert decoded is not None
                self.assertEqual(decoded.shape, (1280, 800, 4))

    def test_stale_substitution_fails_closed_against_parent_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(root=ROOT, output_dir=directory)
            stale = next(
                item
                for item in result.artifacts
                if item.operator is MutationOperator.STALE_FRAME_SUBSTITUTION
            )
            self.assertEqual(stale.identity_status, "rejected")
            self.assertEqual(stale.identity_reason, "CAPTURE_IDENTITY_MISMATCH")
            evaluation = next(
                item for item in result.evaluations if item.mutation_id == stale.mutation_id
            )
            self.assertEqual(evaluation.observed_outcome, MutationDecision.REJECTED)
            self.assertFalse(evaluation.false_accept)

    def test_stale_output_is_rejected_by_semantic_ocr_identity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(root=ROOT, output_dir=directory)
            stale = next(
                item
                for item in result.artifacts
                if item.operator is MutationOperator.STALE_FRAME_SUBSTITUTION
            )
            frame = cv2.imread(stale.storage_path, cv2.IMREAD_COLOR)
            self.assertIsNotNone(frame)
            assert frame is not None
            observation = run_semantic_ocr(
                frame,
                CropRoiRequest(stale.claimed_source_frame, (40, 40, 120, 80)),
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                ocr_engine=lambda _image, _psm: "must-not-authorize",
            )
            self.assertEqual(observation.status, ObservationStatus.INVALID)
            self.assertEqual(observation.reason_code, "TRANSPORT_DIGEST_MISMATCH")

    def test_classifier_metrics_keep_false_accept_and_false_reject_separate(self) -> None:
        def classifier(case, _pixels, _claimed, _mutation):  # type: ignore[no-untyped-def]
            if case.operator in {
                MutationOperator.BRIGHTNESS,
                MutationOperator.CONTRAST,
                MutationOperator.BOUNDED_COMPRESSION,
                MutationOperator.TRANSLATION,
            }:
                return MutationDecision.ACCEPTED
            return MutationDecision.REJECTED

        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(
                root=ROOT,
                output_dir=directory,
                classifier=classifier,
            )
        self.assertEqual(result.metrics.false_accept_count, 0)
        self.assertEqual(result.metrics.false_reject_count, 0)
        self.assertEqual(result.metrics.ambiguous_count, 0)
        self.assertEqual(result.metrics.unresolved_count, 0)
        self.assertNotIn("error_rate", result.metrics.as_dict())

    def test_ambiguous_and_unresolved_are_not_false_accept_or_false_reject(self) -> None:
        def classifier(case, _pixels, _claimed, _mutation):  # type: ignore[no-untyped-def]
            if case.operator is MutationOperator.BRIGHTNESS:
                return MutationDecision.AMBIGUOUS
            if case.operator is MutationOperator.CONTRAST:
                return MutationDecision.UNRESOLVED
            return MutationDecision.REJECTED

        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(
                root=ROOT,
                output_dir=directory,
                classifier=classifier,
            )
        self.assertEqual(result.metrics.ambiguous_count, 1)
        self.assertEqual(result.metrics.unresolved_count, 1)
        self.assertEqual(result.metrics.false_accept_count, 0)
        self.assertEqual(result.metrics.false_reject_count, 2)

    def test_classifier_exception_becomes_unresolved_fail_closed(self) -> None:
        def classifier(_case, _pixels, _claimed, _mutation):  # type: ignore[no-untyped-def]
            raise RuntimeError("classifier unavailable")

        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(
                root=ROOT,
                output_dir=directory,
                classifier=classifier,
            )
        self.assertEqual(result.metrics.unresolved_count, 7)
        self.assertEqual(result.metrics.false_accept_count, 0)
        self.assertEqual(result.metrics.false_reject_count, 0)
        self.assertTrue(
            all(
                evaluation.reason_code.startswith("CLASSIFIER_EXCEPTION")
                or evaluation.observed_outcome is MutationDecision.REJECTED
                for evaluation in result.evaluations
            )
        )

    def test_forbidden_output_trees_are_rejected(self) -> None:
        for relative in ("evidence/mutations", ".local-captures/mutations", ".local-reference/mutations"):
            with self.subTest(relative=relative):
                with self.assertRaises(NativeFrameMutationError) as raised:
                    generate_mutation_corpus(
                        root=ROOT,
                        output_dir=ROOT / relative,
                    )
                self.assertEqual(raised.exception.reason_code, "FORBIDDEN_OUTPUT_PATH")

    def test_metrics_validate_expected_classes_and_rates(self) -> None:
        manifest = load_mutation_manifest(root=ROOT)
        evaluations = tuple(
            (
                # One accepted mutation is deliberately observed rejected.
                # All other cases observe their declared expected class.
                MutationEvaluation(
                    mutation_id=case.mutation_id,
                    expected_outcome=case.expected_outcome,
                    observed_outcome=(
                        MutationDecision.REJECTED
                        if case.operator is MutationOperator.BRIGHTNESS
                        else MutationDecision(case.expected_outcome.value)
                    ),
                    reason_code="test",
                )
            )
            for case in manifest.cases
        )
        metrics = measure_mutation_metrics(evaluations)
        self.assertEqual(metrics.false_reject_count, 1)
        self.assertEqual(metrics.false_accept_count, 0)
        self.assertGreater(metrics.false_reject_rate, 0.0)
        self.assertEqual(metrics.false_accept_rate, 0.0)

    def test_serialization_contains_metadata_only_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = generate_mutation_corpus(root=ROOT, output_dir=directory)
            first = serialize_mutation_result(result)
            second = serialize_mutation_result(result)
        self.assertEqual(first, second)
        self.assertIn('"false_accept_count":0', first)
        self.assertIn('"false_reject_count":0', first)
        self.assertNotIn("ndarray", first)
        self.assertNotIn("dtype", first)


if __name__ == "__main__":
    unittest.main()
