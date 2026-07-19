"""Offline tests for the deterministic native-frame replay harness."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tasks.perception_bundle import NativeFrameIdentity
from tasks import native_frame_replay as replay
from tasks.native_frame_replay import (
    EXACT_SOURCE_ORDER,
    EXPECTED_CHANNELS,
    EXPECTED_HEIGHT,
    EXPECTED_PROFILE_ID,
    EXPECTED_WIDTH,
    NativeFrameReplayError,
    ReplayFrameObservation,
    ReplayManifest,
    ReplayResult,
    ReplaySourceDeclaration,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    assert_fixture_capture_kind,
    build_fixture_identity,
    built_in_perception_ocr_callback,
    coerce_identity_capture_kind,
    deterministic_fixture_session_id,
    generate_images_supported,
    iter_replay_observations,
    load_replay_manifest,
    mutation_operators_available,
    reject_fixture_as_live_freshness,
    reject_live_capture_request,
    replay_native_frames,
    serialize_replay_result,
    source_paths_are_writable,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "native_frame_replay_manifest.json"


def _write_manifest(directory: Path, payload: dict) -> Path:
    path = directory / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _forge_frozen(instance, **changes):  # type: ignore[no-untyped-def]
    """Build a malformed frozen record to verify serialization defenses."""

    forged = object.__new__(type(instance))
    for field in fields(instance):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(instance, field.name)),
        )
    return forged


class NativeFrameReplayTests(unittest.TestCase):
    def test_exact_manifest_parsing_and_two_source_order(self) -> None:
        manifest = load_replay_manifest(MANIFEST_PATH, root=ROOT)
        self.assertEqual(manifest.schema_name, SCHEMA_NAME)
        self.assertEqual(manifest.schema_version, SCHEMA_VERSION)
        self.assertEqual(manifest.capture_kind, "fixture")
        self.assertEqual(manifest.runtime_profile_id, EXPECTED_PROFILE_ID)
        self.assertEqual(len(manifest.sources), 2)
        self.assertEqual(
            tuple(source.relative_path for source in manifest.sources),
            EXACT_SOURCE_ORDER,
        )
        self.assertEqual(
            tuple(source.ordinal for source in manifest.sources),
            (1, 2),
        )
        self.assertEqual(
            manifest.fixture_session_id,
            deterministic_fixture_session_id(manifest.sources),
        )

    def test_manifest_public_construction_enforces_exact_top_level_types(self) -> None:
        manifest = load_replay_manifest(root=ROOT)
        with self.assertRaises(NativeFrameReplayError) as raised:
            ReplayManifest(
                manifest.schema_name,
                True,
                manifest.runtime_profile_id,
                manifest.capture_kind,
                manifest.fixture_session_id,
                800.0,
                1280.0,
                4.0,
                manifest.sources,
            )
        self.assertEqual(raised.exception.reason_code, "UNSUPPORTED_SCHEMA")

        cases = (
            ({"schema_name": 7}, "UNSUPPORTED_SCHEMA_NAME"),
            ({"schema_name": ""}, "UNSUPPORTED_SCHEMA_NAME"),
            ({"schema_version": True}, "UNSUPPORTED_SCHEMA"),
            ({"runtime_profile_id": 7}, "INVALID_PROFILE"),
            ({"capture_kind": 7}, "LIVE_MASQUERADE"),
            ({"fixture_session_id": 7}, "MISSING_FIXTURE_SESSION"),
            ({"expected_width": 800.0}, "UNSUPPORTED_SCHEMA"),
            ({"expected_height": "1280"}, "UNSUPPORTED_SCHEMA"),
            ({"expected_channels": 4.0}, "UNSUPPORTED_SCHEMA"),
            ({"expected_channels": True}, "UNSUPPORTED_SCHEMA"),
            ({"sources": list(manifest.sources)}, "INVALID_SOURCE_COUNT"),
        )
        for changes, reason_code in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(NativeFrameReplayError) as raised:
                    replace(manifest, **changes)
                self.assertEqual(raised.exception.reason_code, reason_code)

    def test_manifest_loader_preserves_top_level_type_failures(self) -> None:
        payload = _base_payload()
        cases = (
            ("schema_name", 7, "UNSUPPORTED_SCHEMA_NAME"),
            ("schema_version", True, "UNSUPPORTED_SCHEMA"),
            ("runtime_profile_id", 7, "INVALID_PROFILE"),
            ("capture_kind", 7, "LIVE_MASQUERADE"),
            ("fixture_session_id", 7, "MISSING_FIXTURE_SESSION"),
            ("expected_width", 800.0, "UNSUPPORTED_SCHEMA"),
            ("expected_height", "1280", "UNSUPPORTED_SCHEMA"),
            ("expected_channels", 4.0, "UNSUPPORTED_SCHEMA"),
        )
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for field, value, reason_code in cases:
                mutated = json.loads(json.dumps(payload))
                mutated[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(NativeFrameReplayError) as raised:
                        load_replay_manifest(_write_manifest(temp, mutated), root=ROOT)
                    self.assertEqual(raised.exception.reason_code, reason_code)

    def test_replay_revalidates_forged_manifest_instances(self) -> None:
        manifest = load_replay_manifest(root=ROOT)
        forged = _forge_frozen(manifest, schema_version=True)
        with self.assertRaises(NativeFrameReplayError) as raised:
            replay_native_frames(forged, root=ROOT)
        self.assertEqual(raised.exception.reason_code, "UNSUPPORTED_SCHEMA")

    def test_hash_dimension_and_profile_validation(self) -> None:
        manifest = load_replay_manifest(MANIFEST_PATH, root=ROOT)
        result = replay_native_frames(manifest, root=ROOT)
        for observation, declaration in zip(result.observations, manifest.sources):
            path = ROOT / declaration.relative_path
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                observation.source_sha256,
            )
            self.assertEqual(observation.width, EXPECTED_WIDTH)
            self.assertEqual(observation.height, EXPECTED_HEIGHT)
            self.assertEqual(observation.channels, EXPECTED_CHANNELS)
            self.assertEqual(observation.identity.runtime_profile_id, EXPECTED_PROFILE_ID)
            self.assertEqual(observation.identity.width, EXPECTED_WIDTH)
            self.assertEqual(observation.identity.height, EXPECTED_HEIGHT)
            self.assertNotEqual(observation.transport_sha256, observation.semantic_sha256)

    def test_deterministic_repeated_replay_serialization(self) -> None:
        first = serialize_replay_result(replay_native_frames(root=ROOT))
        second = serialize_replay_result(replay_native_frames(root=ROOT))
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(payload["capture_kind"], "fixture")
        self.assertEqual(len(payload["observations"]), 2)
        self.assertEqual(payload["observations"][0]["ordinal"], 1)
        self.assertEqual(payload["observations"][1]["ordinal"], 2)

    def test_complete_same_capture_perception_ocr_composition(self) -> None:
        result = replay_native_frames(
            root=ROOT,
            callback=built_in_perception_ocr_callback(),
        )
        self.assertEqual(len(result.observations), 2)
        for observation in result.observations:
            self.assertEqual(observation.identity.capture_kind, "fixture")
            self.assertEqual(observation.callback_payload["same_capture"], "true")
            self.assertEqual(observation.callback_payload["bundle_capture_kind"], "fixture")
            self.assertEqual(
                observation.callback_payload["bundle_ordinal"],
                str(observation.ordinal),
            )
            self.assertEqual(observation.callback_payload["ocr_status"], "ok")
            self.assertEqual(observation.callback_payload["ocr_text"], "fixture-ocr")
            assert_fixture_capture_kind(observation.identity)

    def test_distinct_identities_even_with_duplicate_pixel_simulation(self) -> None:
        result = replay_native_frames(root=ROOT)
        first, second = result.observations
        self.assertFalse(first.identity.same_capture_event(second.identity))
        self.assertNotEqual(first.ordinal, second.ordinal)
        self.assertNotEqual(first.relative_path, second.relative_path)
        self.assertNotEqual(first.source_sha256, second.source_sha256)
        self.assertNotEqual(first.identity.capture_ordinal, second.identity.capture_ordinal)
        # Simulate equal pixel digests while preserving distinct capture identities.
        twin = replace(
            second.identity,
            transport_sha256=first.identity.transport_sha256,
            semantic_sha256=first.identity.semantic_sha256,
        )
        self.assertEqual(twin.transport_sha256, first.identity.transport_sha256)
        self.assertFalse(first.identity.same_capture_event(twin))

    def test_live_masquerade_and_freshness_rejection(self) -> None:
        result = replay_native_frames(root=ROOT)
        identity = result.observations[0].identity
        self.assertEqual(identity.capture_kind, "fixture")
        with self.assertRaises(NativeFrameReplayError) as raised:
            reject_live_capture_request(requested_capture_kind="live")
        self.assertEqual(raised.exception.reason_code, "LIVE_CAPTURE_REQUESTED")
        with self.assertRaises(NativeFrameReplayError) as raised:
            coerce_identity_capture_kind(identity, capture_kind="live")
        self.assertEqual(raised.exception.reason_code, "LIVE_MASQUERADE")
        with self.assertRaises(NativeFrameReplayError) as raised:
            reject_fixture_as_live_freshness(identity)
        self.assertEqual(raised.exception.reason_code, "FIXTURE_NOT_LIVE_FRESHNESS")
        live = NativeFrameIdentity(
            capture_kind="live",
            runtime_session_id="live-session",
            capture_ordinal=1,
            capture_completed_monotonic=identity.capture_completed_monotonic,
            transport_sha256=identity.transport_sha256,
            semantic_sha256=identity.semantic_sha256,
            runtime_profile_id=EXPECTED_PROFILE_ID,
            width=EXPECTED_WIDTH,
            height=EXPECTED_HEIGHT,
        )
        with self.assertRaises(NativeFrameReplayError) as raised:
            assert_fixture_capture_kind(live)
        self.assertEqual(raised.exception.reason_code, "LIVE_MASQUERADE")
        # Fixture monotonic values are records only; harness refuses live freshness authority.
        self.assertIsInstance(identity.capture_completed_monotonic, float)

    def test_path_traversal_and_forbidden_trees_fail_closed(self) -> None:
        payload = _base_payload()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for bad_path, code in (
                ("../secrets/frame.png", "PATH_TRAVERSAL"),
                ("evidence/sessions/frame.png", "FORBIDDEN_SOURCE_TREE"),
                (".local-captures/frame.png", "FORBIDDEN_SOURCE_TREE"),
                ("tasks/assets/not-allowlisted.png", "NON_PROJECT_OWNED_SOURCE"),
            ):
                mutated = json.loads(json.dumps(payload))
                mutated["sources"][0]["relative_path"] = bad_path
                path = _write_manifest(temp, mutated)
                with self.assertRaises(NativeFrameReplayError) as raised:
                    load_replay_manifest(path, root=ROOT)
                self.assertEqual(raised.exception.reason_code, code)

    def test_duplicate_sources_and_ordinals_fail_closed(self) -> None:
        payload = _base_payload()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            dup_path = json.loads(json.dumps(payload))
            dup_path["sources"][1]["relative_path"] = EXACT_SOURCE_ORDER[0]
            dup_path["sources"][1]["source_sha256"] = payload["sources"][0]["source_sha256"]
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, dup_path), root=ROOT)
            self.assertIn(
                raised.exception.reason_code,
                {"MANIFEST_OUT_OF_ORDER", "DUPLICATE_SOURCE"},
            )
            dup_ord = json.loads(json.dumps(payload))
            dup_ord["sources"][1]["ordinal"] = 1
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, dup_ord), root=ROOT)
            self.assertIn(
                raised.exception.reason_code,
                {"MANIFEST_OUT_OF_ORDER", "DUPLICATE_ORDINAL"},
            )

    def test_bad_hash_dimensions_schema_format_and_missing_source(self) -> None:
        payload = _base_payload()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            bad_hash = json.loads(json.dumps(payload))
            bad_hash["sources"][0]["source_sha256"] = "0" * 64
            bad_hash["fixture_session_id"] = deterministic_fixture_session_id(
                tuple(
                    ReplaySourceDeclaration(
                        ordinal=item["ordinal"],
                        relative_path=item["relative_path"],
                        source_sha256=item["source_sha256"],
                        width=item["width"],
                        height=item["height"],
                        channels=item["channels"],
                        label=item["label"],
                        capture_completed_monotonic=item["capture_completed_monotonic"],
                    )
                    for item in bad_hash["sources"]
                )
            )
            with self.assertRaises(NativeFrameReplayError) as raised:
                replay_native_frames(
                    load_replay_manifest(_write_manifest(temp, bad_hash), root=ROOT),
                    root=ROOT,
                )
            self.assertEqual(raised.exception.reason_code, "SOURCE_HASH_MISMATCH")

            bad_dims = json.loads(json.dumps(payload))
            bad_dims["sources"][0]["width"] = 801
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, bad_dims), root=ROOT)
            self.assertEqual(raised.exception.reason_code, "INVALID_DIMENSIONS")

            bad_schema = json.loads(json.dumps(payload))
            bad_schema["schema_version"] = 99
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, bad_schema), root=ROOT)
            self.assertEqual(raised.exception.reason_code, "UNSUPPORTED_SCHEMA_VERSION")

            bad_kind = json.loads(json.dumps(payload))
            bad_kind["capture_kind"] = "live"
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, bad_kind), root=ROOT)
            self.assertEqual(raised.exception.reason_code, "LIVE_MASQUERADE")

            shadow_root = temp / "shadow"
            with self.assertRaises(NativeFrameReplayError) as raised:
                replay_native_frames(
                    load_replay_manifest(MANIFEST_PATH, root=ROOT),
                    root=shadow_root,
                )
            self.assertEqual(raised.exception.reason_code, "MISSING_SOURCE")

    def test_source_schema_rejects_integer_lookalikes(self) -> None:
        payload = _base_payload()
        cases = (
            ("width", 800.0, "INVALID_DIMENSIONS"),
            ("width", True, "INVALID_DIMENSIONS"),
            ("height", "1280", "INVALID_DIMENSIONS"),
            ("height", False, "INVALID_DIMENSIONS"),
            ("channels", 4.0, "INVALID_CHANNELS"),
            ("channels", True, "INVALID_CHANNELS"),
            ("channels", "4", "INVALID_CHANNELS"),
        )
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for field, value, reason_code in cases:
                mutated = json.loads(json.dumps(payload))
                mutated["sources"][0][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(NativeFrameReplayError) as raised:
                        load_replay_manifest(_write_manifest(temp, mutated), root=ROOT)
                    self.assertEqual(raised.exception.reason_code, reason_code)

    def test_source_schema_rejects_invalid_fixture_monotonic_values(self) -> None:
        payload = _base_payload()
        cases = (
            float("nan"),
            float("inf"),
            float("-inf"),
            -1,
            True,
            "1000.0",
        )
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for value in cases:
                mutated = json.loads(json.dumps(payload))
                mutated["sources"][0]["capture_completed_monotonic"] = value
                path = _write_manifest(temp, mutated)
                # Python's JSON loader accepts NaN and Infinity by default; schema validation must not.
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("capture_completed_monotonic", loaded["sources"][0])
                with self.subTest(value=repr(value)):
                    with self.assertRaises(NativeFrameReplayError) as raised:
                        load_replay_manifest(path, root=ROOT)
                    self.assertEqual(raised.exception.reason_code, "INVALID_MONOTONIC")

    def test_source_schema_rejects_empty_labels(self) -> None:
        payload = _base_payload()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for value in ("", "   ", None, 7):
                mutated = json.loads(json.dumps(payload))
                mutated["sources"][0]["label"] = value
                with self.subTest(value=value):
                    with self.assertRaises(NativeFrameReplayError) as raised:
                        load_replay_manifest(_write_manifest(temp, mutated), root=ROOT)
                    self.assertEqual(raised.exception.reason_code, "INVALID_LABEL")

    def test_source_schema_accepts_finite_nonnegative_fixture_monotonic(self) -> None:
        payload = _base_payload()
        payload["sources"][0]["capture_completed_monotonic"] = 0
        with tempfile.TemporaryDirectory() as directory:
            manifest = load_replay_manifest(
                _write_manifest(Path(directory), payload),
                root=ROOT,
            )
        self.assertEqual(manifest.sources[0].capture_completed_monotonic, 0.0)

    def test_reordered_manifest_and_malformed_json_fail_closed(self) -> None:
        payload = _base_payload()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            reordered = json.loads(json.dumps(payload))
            reordered["sources"] = list(reversed(reordered["sources"]))
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(_write_manifest(temp, reordered), root=ROOT)
            self.assertEqual(raised.exception.reason_code, "MANIFEST_OUT_OF_ORDER")

            malformed = temp / "bad.json"
            malformed.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(NativeFrameReplayError) as raised:
                load_replay_manifest(malformed, root=ROOT)
            self.assertEqual(raised.exception.reason_code, "MALFORMED_JSON")

    def test_callback_mutation_and_exception_fail_closed(self) -> None:
        def mutates(context):  # type: ignore[no-untyped-def]
            return {"pixels": context.pixels_bgr()}

        with self.assertRaises(NativeFrameReplayError) as raised:
            replay_native_frames(root=ROOT, callback=mutates)
        self.assertEqual(raised.exception.reason_code, "NUMPY_RETAINED")

        def explodes(_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("callback boom")

        with self.assertRaises(NativeFrameReplayError) as raised:
            replay_native_frames(root=ROOT, callback=explodes)
        self.assertEqual(raised.exception.reason_code, "CALLBACK_EXCEPTION")

    def test_no_mutation_api_or_writable_sources_and_no_numpy_retained(self) -> None:
        self.assertFalse(mutation_operators_available())
        self.assertFalse(generate_images_supported())
        self.assertFalse(source_paths_are_writable())
        public_names = set(replay.__all__)
        for forbidden in ("mutate_frame", "augment_corpus", "write_source", "fuzz_pixels"):
            self.assertNotIn(forbidden, {name.lower() for name in public_names})
        self.assertNotIn("mutate", [name for name in public_names if name.startswith("mutate")])
        self.assertIn("generate_images_supported", public_names)
        self.assertFalse(generate_images_supported())
        result = replay_native_frames(root=ROOT)
        serialized = serialize_replay_result(result)
        self.assertNotIn("dtype", serialized)
        self.assertNotIn("ndarray", serialized)
        for observation in result.observations:
            self.assertNotIsInstance(observation, np.ndarray)
            for value in observation.__dict__.values():
                self.assertFalse(isinstance(value, np.ndarray))
            self.assertIsInstance(observation, ReplayFrameObservation)
            self.assertIsInstance(observation.identity, NativeFrameIdentity)

    def test_iter_observations_preserves_order_and_fixture_session(self) -> None:
        observations = list(iter_replay_observations(root=ROOT))
        self.assertEqual([item.ordinal for item in observations], [1, 2])
        self.assertEqual(
            {item.identity.runtime_session_id for item in observations},
            {load_replay_manifest(root=ROOT).fixture_session_id},
        )

    def test_build_fixture_identity_rejects_live_session_label(self) -> None:
        manifest = load_replay_manifest(root=ROOT)
        declaration = manifest.sources[0]
        with self.assertRaises(NativeFrameReplayError) as raised:
            build_fixture_identity(
                declaration,
                fixture_session_id="live-capture-session",
                transport_sha256="a" * 64,
                semantic_sha256="b" * 64,
            )
        self.assertEqual(raised.exception.reason_code, "LIVE_MASQUERADE")

    def test_result_type_is_immutable_and_fixture_only(self) -> None:
        result = replay_native_frames(root=ROOT)
        self.assertIsInstance(result, ReplayResult)
        with self.assertRaises(Exception):
            result.capture_kind = "live"  # type: ignore[misc]
        self.assertEqual(result.capture_kind, "fixture")
        self.assertTrue(all(item.identity.capture_kind == "fixture" for item in result.observations))

    def test_direct_observation_construction_rejects_structural_inconsistency(self) -> None:
        first = replay_native_frames(root=ROOT).observations[0]
        cases = (
            ({"width": 800.0}, "INVALID_DIMENSIONS"),
            ({"height": 1279}, "INVALID_DIMENSIONS"),
            ({"channels": True}, "INVALID_CHANNELS"),
            ({"ordinal": "1"}, "INVALID_ORDINAL"),
            ({"relative_path": 7}, "INVALID_SOURCE_PATH"),
            ({"relative_path": EXACT_SOURCE_ORDER[1]}, "MANIFEST_OUT_OF_ORDER"),
            ({"label": 7}, "INVALID_LABEL"),
            ({"label": "different-label"}, "LABEL_MISMATCH"),
            (
                {"identity": replace(first.identity, width=EXPECTED_WIDTH + 1)},
                "IDENTITY_GEOMETRY_MISMATCH",
            ),
            (
                {"identity": replace(first.identity, runtime_profile_id="wrong-profile")},
                "INVALID_PROFILE",
            ),
        )
        for changes, reason_code in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(NativeFrameReplayError) as raised:
                    replace(first, **changes)
                self.assertEqual(raised.exception.reason_code, reason_code)

    def test_inconsistent_forged_observation_cannot_serialize(self) -> None:
        result = replay_native_frames(root=ROOT)
        forged = _forge_frozen(result.observations[0], width=EXPECTED_WIDTH + 1)
        forged_result = _forge_frozen(
            result,
            observations=(forged, result.observations[1]),
        )
        with self.assertRaises(NativeFrameReplayError) as raised:
            serialize_replay_result(forged_result)
        self.assertEqual(raised.exception.reason_code, "INVALID_DIMENSIONS")

    def test_direct_result_construction_rejects_structural_inconsistency(self) -> None:
        result = replay_native_frames(root=ROOT)
        first, second = result.observations
        cases = (
            ({"schema_name": 7}, "UNSUPPORTED_SCHEMA"),
            ({"schema_version": True}, "UNSUPPORTED_SCHEMA"),
            ({"capture_kind": 7}, "LIVE_MASQUERADE"),
            ({"fixture_session_id": 7}, "MISSING_FIXTURE_SESSION"),
            ({"fixture_session_id": ""}, "MISSING_FIXTURE_SESSION"),
            ({"fixture_session_id": "   "}, "MISSING_FIXTURE_SESSION"),
            ({"fixture_session_id": "other-fixture-session"}, "SESSION_MISMATCH"),
            ({"observations": list(result.observations)}, "INVALID_OBSERVATIONS"),
            ({"observations": (first, first)}, "DUPLICATE_CAPTURE_EVENT"),
            ({"observations": (second, first)}, "MANIFEST_OUT_OF_ORDER"),
        )
        for changes, reason_code in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(NativeFrameReplayError) as raised:
                    ReplayResult(
                        schema_name=changes.get("schema_name", result.schema_name),
                        schema_version=changes.get(
                            "schema_version",
                            result.schema_version,
                        ),
                        fixture_session_id=changes.get(
                            "fixture_session_id",
                            result.fixture_session_id,
                        ),
                        capture_kind=changes.get("capture_kind", result.capture_kind),
                        observations=changes.get("observations", result.observations),
                    )
                self.assertEqual(raised.exception.reason_code, reason_code)

    def test_forged_result_top_level_types_cannot_serialize(self) -> None:
        result = replay_native_frames(root=ROOT)
        cases = (
            ({"schema_name": 7}, "UNSUPPORTED_SCHEMA"),
            ({"schema_version": True}, "UNSUPPORTED_SCHEMA"),
            ({"capture_kind": 7}, "LIVE_MASQUERADE"),
            ({"fixture_session_id": 7}, "MISSING_FIXTURE_SESSION"),
            ({"observations": list(result.observations)}, "INVALID_OBSERVATIONS"),
        )
        for changes, reason_code in cases:
            with self.subTest(changes=changes):
                forged = _forge_frozen(result, **changes)
                with self.assertRaises(NativeFrameReplayError) as raised:
                    serialize_replay_result(forged)
                self.assertEqual(raised.exception.reason_code, reason_code)

    def test_result_rechecks_fixture_identity_and_distinct_capture_events(self) -> None:
        result = replay_native_frames(root=ROOT)
        first, second = result.observations
        live_identity = replace(first.identity, capture_kind="live")
        live_observation = _forge_frozen(first, identity=live_identity)
        with self.assertRaises(NativeFrameReplayError) as raised:
            ReplayResult(
                schema_name=result.schema_name,
                schema_version=result.schema_version,
                fixture_session_id=result.fixture_session_id,
                capture_kind="fixture",
                observations=(live_observation, second),
            )
        self.assertEqual(raised.exception.reason_code, "LIVE_MASQUERADE")

        duplicate_event = _forge_frozen(second, identity=first.identity, ordinal=1)
        with self.assertRaises(NativeFrameReplayError) as raised:
            ReplayResult(
                schema_name=result.schema_name,
                schema_version=result.schema_version,
                fixture_session_id=result.fixture_session_id,
                capture_kind="fixture",
                observations=(first, duplicate_event),
            )
        self.assertEqual(raised.exception.reason_code, "DUPLICATE_CAPTURE_EVENT")

        duplicate_ordinal = _forge_frozen(second, ordinal=1)
        with self.assertRaises(NativeFrameReplayError) as raised:
            ReplayResult(
                schema_name=result.schema_name,
                schema_version=result.schema_version,
                fixture_session_id=result.fixture_session_id,
                capture_kind="fixture",
                observations=(first, duplicate_ordinal),
            )
        self.assertEqual(
            raised.exception.reason_code,
            "DUPLICATE_ORDINAL",
        )


if __name__ == "__main__":
    unittest.main()
