"""Offline tests for immutable capture-event perception bundles.

Synthetic fixtures prove composition/freshness contracts only. They are not production
recognition coverage.
"""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import unittest
from unittest import mock

from tasks.home_atlas import AmbiguityState, BuildingBinding, LocalizationResult, ZoomIdentity
from tasks import perception_bundle as perception_bundle_module
from tasks.perception_bundle import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ContextualClass,
    FrameContextClassification,
    FrameValidityState,
    ImmutableForbiddenSurfaceObservation,
    ImmutableFrameValidationObservation,
    ImmutableKnownModalObservation,
    ImmutableRadialObservation,
    ImmutableRecognizedScreenObservation,
    ImmutableTargetObservation,
    NativeFrameIdentity,
    PerceptionBundleError,
    SemanticValidity,
    TransportFreshness,
    assert_semantic_valid,
    assert_transport_fresh,
    binding_from_result,
    bundle_evidence_snapshot,
    bundle_from_identity,
    classify_and_attach,
    classify_frame_context,
    localization_from_result,
    semantic_validity,
    transport_freshness,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "perception_bundle_evidence.json"
PROFILE = "pns-bluestacks-5-p64-800x1280-v1"
PLATFORM = "BlueStacks 5 / Android"


def digest(tag: str) -> str:
    """Return a valid 64-hex digest derived from a single hex nibble tag."""

    nibble = tag[:1].lower()
    if nibble not in "0123456789abcdef":
        raise AssertionError("digest tag must be a hex nibble")
    return nibble * 64


def fixture_identity(
    *,
    session: str = "fixture-session",
    ordinal: int = 1,
    monotonic: float = 1000.0,
    transport: str = "a",
    semantic: str = "b",
    label: str = "fixture-frame",
    profile_id: str = PROFILE,
    width: int = 800,
    height: int = 1280,
) -> NativeFrameIdentity:
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=session,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=digest(transport),
        semantic_sha256=digest(semantic),
        runtime_profile_id=profile_id,
        width=width,
        height=height,
        label=label,
    )


def frame_validation(
    identity: NativeFrameIdentity,
    *,
    validity: FrameValidityState = FrameValidityState.VALID_NATIVE,
    expected_profile_id: str = PROFILE,
    expected_width: int = 800,
    expected_height: int = 1280,
    expected_platform: str = PLATFORM,
) -> ImmutableFrameValidationObservation:
    return ImmutableFrameValidationObservation(
        source_frame=identity,
        validity=validity,
        expected_profile_id=expected_profile_id,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_platform=expected_platform,
        package_ok=True,
        orientation_ok=True,
        supporting_evidence=("fixture-validation",),
    )


def localization_result(identity: NativeFrameIdentity, **overrides) -> LocalizationResult:
    values = dict(
        recognized=True,
        platform=PLATFORM,
        profile_id=PROFILE,
        zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
        screen_to_atlas=((1.0, 0.0, 100.0), (0.0, 1.0, 200.0), (0.0, 0.0, 1.0)),
        viewport_polygon=((100.0, 200.0), (900.0, 200.0), (900.0, 1480.0), (100.0, 1480.0)),
        confidence=0.95,
        supporting_landmarks=("v1",),
        residual_px=0.2,
        ambiguity_state=AmbiguityState.NONE,
        map_edge_state="interior",
        frame_sha256=identity.semantic_sha256,
        timestamp="2026-07-18T00:00:00+00:00",
        stale=False,
        overlay=False,
    )
    values.update(overrides)
    return LocalizationResult(**values)


def binding_result(identity: NativeFrameIdentity, **overrides) -> BuildingBinding:
    values = dict(
        building_id="home.building.supply_depot",
        target_roi=(320, 420, 420, 520),
        frame_sha256=identity.semantic_sha256,
        confidence=0.94,
        semantic_evidence=("current-frame OCR: Supply Depot",),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )
    values.update(overrides)
    return BuildingBinding(**values)


def home_bundle(identity: NativeFrameIdentity | None = None, *, with_binding: bool = False):
    identity = identity or fixture_identity()
    bundle = (
        bundle_from_identity(identity)
        .with_frame_validation(frame_validation(identity))
        .with_localization(localization_from_result(identity, localization_result(identity)))
    )
    if with_binding:
        bundle = bundle.with_building_binding(binding_from_result(identity, binding_result(identity)))
    return classify_and_attach(bundle)


class PerceptionBundleTests(unittest.TestCase):
    def test_same_capture_event_composition_succeeds(self):
        identity = fixture_identity()
        bundle = home_bundle(identity, with_binding=True)
        localization, binding = bundle.checked_navigation_inputs()
        self.assertEqual(localization.frame_sha256, identity.semantic_sha256)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.frame_sha256, identity.semantic_sha256)

    def test_cross_capture_event_binding_rejected(self):
        first = fixture_identity(ordinal=1, semantic="a")
        second = fixture_identity(ordinal=2, semantic="c", monotonic=1001.0)
        bundle = home_bundle(first)
        foreign = binding_from_result(second, binding_result(second))
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.with_building_binding(foreign)
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_localization_from_another_frame_rejected_against_independent_identity(self):
        identity = fixture_identity(semantic="b")
        foreign = fixture_identity(ordinal=9, monotonic=2000.0, semantic="d")
        self.assertNotEqual(identity.semantic_sha256, foreign.semantic_sha256)
        with self.assertRaises(PerceptionBundleError) as raised:
            localization_from_result(identity, localization_result(foreign))
        self.assertEqual(raised.exception.reason_code, "SEMANTIC_DIGEST_MISMATCH")
        bundle = bundle_from_identity(identity).with_frame_validation(frame_validation(identity))
        with self.assertRaises(PerceptionBundleError):
            bundle.with_localization(localization_from_result(foreign, localization_result(foreign)))

    def test_identity_digests_must_be_hexadecimal(self):
        with self.assertRaises(PerceptionBundleError) as raised:
            NativeFrameIdentity(
                "fixture",
                "session",
                1,
                1.0,
                "t" * 64,
                "b" * 64,
                PROFILE,
                800,
                1280,
            )
        self.assertEqual(raised.exception.reason_code, "INVALID_DIGEST")

    def test_transport_stale_and_future_rejection(self):
        identity = fixture_identity(monotonic=1000.0)
        self.assertEqual(transport_freshness(identity, 1005.0, 30.0), TransportFreshness.OK)
        self.assertEqual(transport_freshness(identity, 1040.0, 30.0), TransportFreshness.STALE)
        self.assertEqual(transport_freshness(identity, 999.0, 30.0), TransportFreshness.FUTURE)
        with self.assertRaises(PerceptionBundleError) as stale:
            assert_transport_fresh(identity, 1040.0, 30.0)
        self.assertEqual(stale.exception.reason_code, "TRANSPORT_FRAME_STALE")
        with self.assertRaises(PerceptionBundleError) as future:
            assert_transport_fresh(identity, 999.0, 30.0)
        self.assertEqual(future.exception.reason_code, "TRANSPORT_FRAME_FUTURE")

    def test_semantic_invalid_stale_localization(self):
        identity = fixture_identity()
        stale = localization_result(identity, stale=True, ambiguity_state=AmbiguityState.STALE_FRAME)
        bundle = (
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, stale))
        )
        status, reason = semantic_validity(bundle)
        self.assertEqual(status, SemanticValidity.INVALID)
        self.assertEqual(reason, "SEMANTIC_FRAME_INVALID")
        with self.assertRaises(PerceptionBundleError):
            assert_semantic_valid(bundle)

    def test_known_modal_never_allows_interaction_even_with_home_binding(self):
        identity = fixture_identity()
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
            .with_building_binding(binding_from_result(identity, binding_result(identity)))
            .with_known_modal(ImmutableKnownModalObservation(identity, "alliance_fort_wave_alert", 0.99, ("title",)))
        )
        self.assertEqual(bundle.context.contextual_class, ContextualClass.KNOWN_MODAL)
        self.assertTrue(bundle.context.context_recognized)
        self.assertFalse(bundle.context.context_allows_interaction)

    def test_overlay_flag_without_recognized_identity_is_unknown(self):
        identity = fixture_identity()
        overlay_loc = localization_result(identity, overlay=True)
        context = classify_frame_context(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, overlay_loc))
        )
        self.assertEqual(context.contextual_class, ContextualClass.UNKNOWN)
        self.assertFalse(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.reason_code, "UNKNOWN_OVERLAY")

    def test_wrong_profile_validation_classifies_non_native(self):
        identity = fixture_identity(profile_id="other-profile")
        context = classify_frame_context(
            bundle_from_identity(identity).with_frame_validation(
                frame_validation(identity, validity=FrameValidityState.WRONG_PROFILE)
            )
        )
        self.assertEqual(context.contextual_class, ContextualClass.NON_NATIVE_OR_INVALID)
        self.assertFalse(context.context_allows_interaction)

    def test_context_recognized_without_interaction_candidate(self):
        bundle = home_bundle()
        self.assertEqual(bundle.context.contextual_class, ContextualClass.CANONICAL_HOME)
        self.assertTrue(bundle.context.context_recognized)
        self.assertFalse(bundle.context.context_allows_interaction)

    def test_canonical_home_allows_interaction_only_with_valid_binding(self):
        bundle = home_bundle(with_binding=True)
        self.assertTrue(bundle.context.context_allows_interaction)
        identity = fixture_identity()
        forbidden = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
            .with_building_binding(binding_from_result(identity, binding_result(identity)))
            .with_forbidden_surface(ImmutableForbiddenSurfaceObservation(identity, "unexpected_warehouse_surface"))
        )
        self.assertFalse(forbidden.context.context_allows_interaction)

    def test_versioned_deterministic_evidence_snapshot_matches_fixture(self):
        identity = fixture_identity()
        bundle = home_bundle(identity)
        generated = bundle_evidence_snapshot(bundle)
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(generated, fixture)
        self.assertEqual(generated["schema_name"], SCHEMA_NAME)
        self.assertEqual(generated["schema_version"], SCHEMA_VERSION)
        encoded = json.dumps(generated, sort_keys=True)
        self.assertNotIn("numpy", encoded.lower())
        self.assertNotIn("ndarray", encoded.lower())

    def test_transport_digest_differs_from_semantic_digest(self):
        identity = fixture_identity(transport="a", semantic="b")
        self.assertNotEqual(identity.transport_sha256, identity.semantic_sha256)
        localization = localization_result(identity)
        self.assertEqual(localization.frame_sha256, identity.semantic_sha256)
        self.assertNotEqual(localization.frame_sha256, identity.transport_sha256)

    def test_identical_pixels_different_capture_events_cannot_exchange_observations(self):
        shared_transport = digest("a")
        shared_semantic = digest("b")
        first = NativeFrameIdentity(
            "fixture", "session-a", 1, 1000.0, shared_transport, shared_semantic, PROFILE, 800, 1280
        )
        second = NativeFrameIdentity(
            "fixture", "session-a", 2, 1001.0, shared_transport, shared_semantic, PROFILE, 800, 1280
        )
        self.assertFalse(first.same_capture_event(second))
        bundle = bundle_from_identity(first).with_frame_validation(frame_validation(first))
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.with_localization(localization_from_result(second, localization_result(second)))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_session_and_ordinal_mismatch_rejection(self):
        first = fixture_identity(session="alpha", ordinal=1)
        second = fixture_identity(session="beta", ordinal=1, semantic="b")
        bundle = bundle_from_identity(first)
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.with_target(ImmutableTargetObservation(second, "home-quest", (10, 20, 30, 40), 0.9))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_deep_immutability_of_nested_observation_data(self):
        identity = fixture_identity()
        observation = localization_from_result(identity, localization_result(identity))
        with self.assertRaises(Exception):
            observation.supporting_landmarks.append("mutated")  # type: ignore[attr-defined]
        with self.assertRaises(Exception):
            observation.source_frame.runtime_session_id = "mutated"  # type: ignore[misc]
        bundle = bundle_from_identity(identity).with_localization(observation)
        with self.assertRaises(Exception):
            bundle.localization = None  # type: ignore[misc]

    def test_serialized_bundle_retains_no_numpy_frame(self):
        payload = bundle_evidence_snapshot(home_bundle())
        blob = json.dumps(payload, sort_keys=True)
        self.assertNotIn("dtype", blob)
        self.assertNotIn("ndarray", blob)

    def test_neutral_module_has_no_capture_dependency(self):
        source = inspect.getsource(perception_bundle_module)
        self.assertNotIn("CapturedNativeFrame", source)
        self.assertNotIn("ADBRunner", source)
        self.assertNotIn("bluestacks_native_runtime", source)
        self.assertNotIn("import cv2", source)
        self.assertNotIn("import numpy", source)
        self.assertNotRegex(source, r"(?m)^\s*def\s+capture\s*\(")
        self.assertFalse(hasattr(perception_bundle_module, "capture"))
        with mock.patch.object(
            perception_bundle_module, "bundle_from_identity", wraps=perception_bundle_module.bundle_from_identity
        ) as wrapped:
            identity = fixture_identity()
            classify_and_attach(
                perception_bundle_module.bundle_from_identity(identity).with_frame_validation(
                    frame_validation(identity)
                )
            )
            wrapped.assert_called()

    def test_input_invalidates_pre_input_bundle_for_successor_decisions(self):
        bundle = home_bundle(with_binding=True)
        invalidated = bundle.invalidate_after_input()
        self.assertTrue(invalidated.invalidated_after_input)
        with self.assertRaises(PerceptionBundleError) as raised:
            invalidated.checked_navigation_inputs()
        self.assertEqual(raised.exception.reason_code, "BUNDLE_INVALIDATED_AFTER_INPUT")

    def test_classifier_precedence_with_conflicting_observations(self):
        identity = fixture_identity()
        bundle = (
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
            .with_radial(ImmutableRadialObservation(identity, "home.building.fighter_camp", 0.9))
            .with_recognized_screen(
                ImmutableRecognizedScreenObservation(identity, "supply_depot", 0.98, ("title",))
            )
            .with_known_modal(ImmutableKnownModalObservation(identity, "update_restart_alert", 0.97))
        )
        context = classify_frame_context(bundle)
        self.assertEqual(context.contextual_class, ContextualClass.KNOWN_MODAL)
        self.assertFalse(context.context_allows_interaction)
        without_modal = classify_frame_context(replace(bundle, known_modal=None))
        self.assertEqual(without_modal.contextual_class, ContextualClass.KNOWN_FULLSCREEN_SURFACE)
        self.assertFalse(without_modal.context_allows_interaction)

    def test_checked_navigation_rejects_stale_localization(self):
        identity = fixture_identity()
        stale = localization_result(identity, stale=True, ambiguity_state=AmbiguityState.STALE_FRAME)
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, stale))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"SEMANTIC_FRAME_INVALID", "CONTEXT_NOT_CANONICAL_HOME"})

    def test_checked_navigation_rejects_wrong_profile(self):
        identity = fixture_identity()
        wrong = localization_result(identity, profile_id="wrong-profile")
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, wrong))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertEqual(raised.exception.reason_code, "WRONG_PROFILE")

    def test_checked_navigation_rejects_wrong_geometry(self):
        identity = fixture_identity(width=400, height=640)
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(
                frame_validation(
                    identity,
                    validity=FrameValidityState.WRONG_GEOMETRY,
                    expected_width=800,
                    expected_height=1280,
                )
            )
            .with_localization(localization_from_result(identity, localization_result(identity)))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"NON_NATIVE_OR_INVALID", "WRONG_GEOMETRY_OR_PROFILE"})

    def test_checked_navigation_rejects_unknown_context(self):
        identity = fixture_identity()
        # Recognized but non-canonical zoom classifies as unknown, not canonical_home.
        zoomed = localization_result(identity, zoom_identity=ZoomIdentity.ZOOMED_IN)
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, zoomed))
        )
        self.assertEqual(bundle.context.contextual_class, ContextualClass.UNKNOWN)
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"NONCANONICAL_ZOOM", "CONTEXT_NOT_CANONICAL_HOME"})

    def test_checked_navigation_rejects_overlay(self):
        identity = fixture_identity()
        overlay = localization_result(identity, overlay=True)
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, overlay))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"OVERLAY_PRESENT", "CONTEXT_NOT_CANONICAL_HOME"})

    def test_checked_navigation_rejects_forbidden_surface(self):
        identity = fixture_identity()
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
            .with_forbidden_surface(ImmutableForbiddenSurfaceObservation(identity, "unexpected_surface"))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"FORBIDDEN_SURFACE", "CONTEXT_NOT_CANONICAL_HOME"})

    def test_checked_navigation_rejects_noncanonical_zoom(self):
        identity = fixture_identity()
        zoomed = localization_result(identity, zoom_identity=ZoomIdentity.ZOOMED_IN)
        bundle = classify_and_attach(
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, zoomed))
        )
        with self.assertRaises(PerceptionBundleError) as raised:
            bundle.checked_navigation_inputs()
        self.assertIn(raised.exception.reason_code, {"NONCANONICAL_ZOOM", "CONTEXT_NOT_CANONICAL_HOME"})

    def test_checked_navigation_allows_missing_attached_context_when_derived_is_canonical(self):
        identity = fixture_identity()
        bundle = (
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
        )
        self.assertIsNone(bundle.context)
        localization, _ = bundle.checked_navigation_inputs()
        self.assertEqual(localization.frame_sha256, identity.semantic_sha256)

    def test_forged_canonical_home_context_rejected_when_modal_present(self):
        identity = fixture_identity()
        bundle = (
            bundle_from_identity(identity)
            .with_frame_validation(frame_validation(identity))
            .with_localization(localization_from_result(identity, localization_result(identity)))
            .with_known_modal(ImmutableKnownModalObservation(identity, "alliance_fort_wave_alert", 0.99))
        )
        forged = FrameContextClassification(
            ContextualClass.CANONICAL_HOME,
            True,
            True,
            1.0,
            ("forged",),
            "canonical_home",
        )
        forged_bundle = replace(bundle, context=forged)
        with self.assertRaises(PerceptionBundleError) as raised:
            forged_bundle.checked_navigation_inputs()
        self.assertEqual(raised.exception.reason_code, "CONTEXT_CLASSIFICATION_MISMATCH")

    def test_surface_safe_target_same_frame_accepted(self):
        identity = fixture_identity()
        target = ImmutableTargetObservation(identity, "screen-close", (10, 20, 30, 40), 0.9)
        screen = ImmutableRecognizedScreenObservation(
            identity, "supply_depot", 0.98, ("title",), (target,)
        )
        bundle = bundle_from_identity(identity).with_recognized_screen(screen)
        self.assertEqual(bundle.recognized_screen.surface_safe_targets[0].target_identity, "screen-close")
        context = classify_frame_context(bundle)
        self.assertEqual(context.contextual_class, ContextualClass.KNOWN_FULLSCREEN_SURFACE)
        self.assertTrue(context.context_allows_interaction)

    def test_surface_safe_target_foreign_session_rejected(self):
        identity = fixture_identity(session="alpha")
        foreign = fixture_identity(session="beta", semantic="b")
        target = ImmutableTargetObservation(foreign, "screen-close", (10, 20, 30, 40), 0.9)
        with self.assertRaises(PerceptionBundleError) as raised:
            ImmutableRecognizedScreenObservation(identity, "supply_depot", 0.98, ("title",), (target,))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_surface_safe_target_foreign_ordinal_rejected(self):
        identity = fixture_identity(ordinal=1)
        foreign = fixture_identity(ordinal=2, monotonic=1001.0, semantic="b")
        target = ImmutableTargetObservation(foreign, "screen-close", (10, 20, 30, 40), 0.9)
        with self.assertRaises(PerceptionBundleError) as raised:
            ImmutableRecognizedScreenObservation(identity, "supply_depot", 0.98, (), (target,))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_surface_safe_target_identical_pixels_different_capture_rejected(self):
        shared_transport = digest("a")
        shared_semantic = digest("b")
        first = NativeFrameIdentity(
            "fixture", "session-a", 1, 1000.0, shared_transport, shared_semantic, PROFILE, 800, 1280
        )
        second = NativeFrameIdentity(
            "fixture", "session-a", 2, 1001.0, shared_transport, shared_semantic, PROFILE, 800, 1280
        )
        target = ImmutableTargetObservation(second, "screen-close", (10, 20, 30, 40), 0.9)
        with self.assertRaises(PerceptionBundleError) as raised:
            ImmutableRecognizedScreenObservation(first, "supply_depot", 0.98, (), (target,))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")
        with self.assertRaises(PerceptionBundleError):
            bundle_from_identity(first).with_recognized_screen(
                # Construct via replace to bypass screen __post_init__ nested check is already at construction
                # so composition path: build valid screen on foreign then try attach to first
                ImmutableRecognizedScreenObservation(second, "supply_depot", 0.98, (), (target,))
            )

    def test_valid_native_rejects_package_or_orientation_false(self):
        identity = fixture_identity()
        with self.assertRaises(PerceptionBundleError) as package:
            ImmutableFrameValidationObservation(
                identity,
                FrameValidityState.VALID_NATIVE,
                PROFILE,
                800,
                1280,
                PLATFORM,
                package_ok=False,
                orientation_ok=True,
            )
        self.assertEqual(package.exception.reason_code, "FRAME_VALIDATION_INCONSISTENT")
        with self.assertRaises(PerceptionBundleError) as orientation:
            ImmutableFrameValidationObservation(
                identity,
                FrameValidityState.VALID_NATIVE,
                PROFILE,
                800,
                1280,
                PLATFORM,
                package_ok=True,
                orientation_ok=False,
            )
        self.assertEqual(orientation.exception.reason_code, "FRAME_VALIDATION_INCONSISTENT")

    def test_bundle_enforced_planner_integration_rejects_unchecked_inputs(self):
        identity = fixture_identity()
        localization = localization_result(identity)
        binding = binding_result(identity)
        bundle = home_bundle(identity, with_binding=True)
        checked_localization, checked_binding = bundle.checked_navigation_inputs()
        self.assertIsNot(checked_localization, localization)
        self.assertIsNot(checked_binding, binding)
        foreign = fixture_identity(ordinal=9, monotonic=2000.0, semantic="d")
        with self.assertRaises(PerceptionBundleError):
            bundle.with_building_binding(binding_from_result(foreign, binding_result(foreign)))

    def test_fixture_capture_kind_is_explicit(self):
        identity = fixture_identity()
        self.assertEqual(identity.capture_kind, "fixture")
        live = NativeFrameIdentity(
            "live",
            "runtime-session",
            1,
            10.0,
            digest("a"),
            digest("b"),
            PROFILE,
            800,
            1280,
        )
        self.assertEqual(live.capture_kind, "live")
        self.assertFalse(identity.same_capture_event(live))


if __name__ == "__main__":
    unittest.main()
