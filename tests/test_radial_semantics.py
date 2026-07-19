"""Offline tests for platform-neutral Home radial semantic contract."""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
import math
from pathlib import Path
from types import MappingProxyType
import unittest

from tasks.perception_bundle import (
    ContextualClass,
    FrameValidityState,
    ImmutableFrameValidationObservation,
    ImmutableRadialObservation,
    ImmutableTargetObservation,
    NativeFrameIdentity,
    PerceptionBundleError,
    bundle_from_identity,
    classify_frame_context,
    localization_from_result,
)
from tasks.home_atlas import AmbiguityState, LocalizationResult, ZoomIdentity
from tasks import radial_semantics as radial_semantics_module
from tasks.radial_semantics import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ActionabilityState,
    ControlRole,
    HomeRadialSemantics,
    OwningFacilityObservation,
    RadialAmbiguityState,
    RadialControlObservation,
    RadialSemanticsError,
    RecognitionState,
    assert_radial_semantics_do_not_authorize,
    radial_semantics_authorize_dispatch,
    radial_semantics_evidence_snapshot,
    to_immutable_radial_observation,
)


ROOT = Path(__file__).resolve().parents[1]
REPLAY_MANIFEST = ROOT / "tests" / "fixtures" / "native_frame_replay_manifest.json"


def _load_replay_fixture_identity(ordinal: int = 1) -> NativeFrameIdentity:
    payload = json.loads(REPLAY_MANIFEST.read_text(encoding="utf-8"))
    source = next(item for item in payload["sources"] if item["ordinal"] == ordinal)
    digest = source["source_sha256"]
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=payload["fixture_session_id"],
        capture_ordinal=int(source["ordinal"]),
        capture_completed_monotonic=float(source["capture_completed_monotonic"]),
        transport_sha256=digest,
        semantic_sha256=digest,
        runtime_profile_id=payload["runtime_profile_id"],
        width=int(source["width"]),
        height=int(source["height"]),
        label=str(source["label"]),
    )


def _owner(
    identity: NativeFrameIdentity,
    *,
    facility_id: str = "home.building.supply_depot",
    recognition_state: RecognitionState = RecognitionState.RECOGNIZED,
    confidence: float = 0.97,
    ambiguity: RadialAmbiguityState = RadialAmbiguityState.NONE,
) -> OwningFacilityObservation:
    return OwningFacilityObservation(
        source_frame=identity,
        facility_semantic_id=facility_id,
        recognition_state=recognition_state,
        recognition_confidence=confidence,
        ambiguity_state=ambiguity,
        supporting_evidence=("fixture-owner",),
    )


def _control(
    identity: NativeFrameIdentity,
    *,
    control_id: str = "home.radial.supply_depot.claim_supply",
    label: str = "Claim Supply",
    role: ControlRole = ControlRole.CLAIM,
    recognition_state: RecognitionState = RecognitionState.RECOGNIZED,
    confidence: float = 0.95,
    actionability: ActionabilityState = ActionabilityState.ACTIONABLE,
    reason: str = "recognized_owner_and_control",
    expected: tuple[str, ...] = ("facility.claim_supply",),
    forbidden: tuple[str, ...] = ("facility.upgrade", "radial.closed_exterior"),
    owner_id: str = "home.building.supply_depot",
    ambiguity: RadialAmbiguityState = RadialAmbiguityState.NONE,
    metadata: MappingProxyType | dict[str, str] | None = None,
) -> RadialControlObservation:
    return RadialControlObservation(
        source_frame=identity,
        control_id=control_id,
        label=label,
        role=role,
        recognition_state=recognition_state,
        recognition_confidence=confidence,
        actionability_state=actionability,
        actionability_reason=reason,
        expected_successors=expected,
        forbidden_successors=forbidden,
        owner_facility_semantic_id=owner_id,
        ambiguity_state=ambiguity,
        supporting_evidence=("fixture-control",),
        metadata=metadata if metadata is not None else MappingProxyType({}),
    )


def _radial(
    identity: NativeFrameIdentity,
    *,
    owner: OwningFacilityObservation | None = None,
    controls: tuple[RadialControlObservation, ...] | None = None,
    recognition_state: RecognitionState = RecognitionState.RECOGNIZED,
    confidence: float = 0.96,
    ambiguity: RadialAmbiguityState = RadialAmbiguityState.NONE,
    radial_identity: str = "home.radial.supply_depot",
) -> HomeRadialSemantics:
    owning = owner if owner is not None else _owner(identity)
    inventory = controls if controls is not None else (_control(identity),)
    return HomeRadialSemantics(
        source_frame=identity,
        radial_identity=radial_identity,
        recognition_state=recognition_state,
        recognition_confidence=confidence,
        owning_facility=owning,
        controls=inventory,
        ambiguity_state=ambiguity,
        supporting_evidence=("fixture-radial",),
    )


def _canonical_bundle_with_typed_radial(
    identity: NativeFrameIdentity,
    semantics: HomeRadialSemantics,
):
    localization = LocalizationResult(
        recognized=True,
        platform="fixture-platform",
        profile_id=identity.runtime_profile_id,
        zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
        screen_to_atlas=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        viewport_polygon=((0.0, 0.0), (800.0, 0.0), (800.0, 1280.0), (0.0, 1280.0)),
        confidence=0.99,
        supporting_landmarks=("fixture",),
        residual_px=0.1,
        ambiguity_state=AmbiguityState.NONE,
        map_edge_state="none",
        frame_sha256=identity.semantic_sha256,
        timestamp="fixture",
    )
    return (
        bundle_from_identity(identity)
        .with_frame_validation(
            ImmutableFrameValidationObservation(
                source_frame=identity,
                validity=FrameValidityState.VALID_NATIVE,
                expected_profile_id=identity.runtime_profile_id,
                expected_width=identity.width,
                expected_height=identity.height,
                package_ok=True,
                orientation_ok=True,
            )
        )
        .with_localization(localization_from_result(identity, localization))
        # The generic target deliberately makes the legacy interaction candidate
        # true. Typed radial semantics must still own actionability.
        .with_target(
            ImmutableTargetObservation(
                source_frame=identity,
                target_identity="fixture.generic_target",
                target_roi=(1, 1, 2, 2),
                confidence=1.0,
            )
        )
        .with_radial(to_immutable_radial_observation(semantics))
    )


class RadialSemanticsTests(unittest.TestCase):
    def test_valid_same_capture_owner_radial_controls(self) -> None:
        identity = _load_replay_fixture_identity(1)
        semantics = _radial(identity)
        self.assertTrue(semantics.recognized)
        self.assertTrue(semantics.any_actionable_control)
        self.assertTrue(identity.same_capture_event(semantics.owning_facility.source_frame))
        self.assertTrue(identity.same_capture_event(semantics.controls[0].source_frame))
        self.assertEqual(
            semantics.controls[0].owner_facility_semantic_id,
            semantics.owning_facility.facility_semantic_id,
        )

    def test_cross_capture_owner_rejected(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        with self.assertRaises(RadialSemanticsError) as raised:
            _radial(first, owner=_owner(second))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_cross_capture_control_rejected(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        with self.assertRaises(RadialSemanticsError) as raised:
            _radial(first, controls=(_control(second),))
        self.assertEqual(raised.exception.reason_code, "CAPTURE_EVENT_MISMATCH")

    def test_same_digest_different_event_rejected(self) -> None:
        first = _load_replay_fixture_identity(1)
        twin = replace(
            first,
            capture_ordinal=99,
            capture_completed_monotonic=first.capture_completed_monotonic + 1.0,
            label="forged-twin",
        )
        self.assertEqual(first.transport_sha256, twin.transport_sha256)
        self.assertEqual(first.semantic_sha256, twin.semantic_sha256)
        self.assertFalse(first.same_capture_event(twin))
        with self.assertRaises(RadialSemanticsError) as raised:
            _radial(first, owner=_owner(twin))
        self.assertEqual(raised.exception.reason_code, "DIGEST_ONLY_JOIN_REJECTED")

    def test_owner_semantic_id_mismatch_blocks_actionable(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(RadialSemanticsError) as raised:
            _radial(
                identity,
                controls=(_control(identity, owner_id="home.building.fighter_camp"),),
            )
        self.assertEqual(raised.exception.reason_code, "OWNER_SEMANTIC_ID_MISMATCH")

    def test_recognized_vs_actionable_vs_authorized_separation(self) -> None:
        identity = _load_replay_fixture_identity(1)
        recognized_only = _radial(
            identity,
            controls=(
                _control(
                    identity,
                    actionability=ActionabilityState.NON_ACTIONABLE,
                    reason="recognized_but_not_actionable",
                ),
            ),
        )
        self.assertTrue(recognized_only.recognized)
        self.assertFalse(recognized_only.any_actionable_control)
        self.assertFalse(radial_semantics_authorize_dispatch(recognized_only))

        actionable = _radial(identity)
        self.assertTrue(actionable.recognized)
        self.assertTrue(actionable.any_actionable_control)
        self.assertFalse(radial_semantics_authorize_dispatch(actionable))
        assert_radial_semantics_do_not_authorize(actionable)

    def test_unknown_owner_cannot_be_actionable(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(RadialSemanticsError) as raised:
            _radial(
                identity,
                owner=_owner(identity, recognition_state=RecognitionState.UNKNOWN),
                controls=(_control(identity),),
            )
        self.assertEqual(raised.exception.reason_code, "ACTIONABLE_REQUIRES_RECOGNIZED_OWNER")

    def test_ambiguous_radial_cannot_be_actionable(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(RadialSemanticsError) as raised:
            HomeRadialSemantics(
                source_frame=identity,
                radial_identity="home.radial.supply_depot",
                recognition_state=RecognitionState.AMBIGUOUS,
                recognition_confidence=0.4,
                owning_facility=_owner(identity),
                controls=(_control(identity),),
                ambiguity_state=RadialAmbiguityState.UNRESOLVED,
            )
        self.assertIn(
            raised.exception.reason_code,
            {"ACTIONABLE_REQUIRES_RECOGNIZED_RADIAL", "AMBIGUOUS_RADIAL_CLAIM"},
        )

    def test_unknown_control_recognition_cannot_claim_actionable(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(RadialSemanticsError) as raised:
            _control(
                identity,
                recognition_state=RecognitionState.UNKNOWN,
                actionability=ActionabilityState.ACTIONABLE,
            )
        self.assertEqual(raised.exception.reason_code, "ACTIONABLE_REQUIRES_RECOGNITION")

    def test_confidence_rejects_nan_inf_range_bool_string(self) -> None:
        identity = _load_replay_fixture_identity(1)
        for bad in (math.nan, math.inf, -math.inf, -0.01, 1.01, True, False, "0.5"):
            with self.subTest(bad=bad):
                with self.assertRaises(RadialSemanticsError) as raised:
                    _owner(identity, confidence=bad)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.reason_code, "INVALID_CONFIDENCE")

    def test_successor_disjointness_and_fail_closed_cases(self) -> None:
        identity = _load_replay_fixture_identity(1)
        with self.assertRaises(RadialSemanticsError) as overlap:
            _control(
                identity,
                expected=("facility.claim_supply",),
                forbidden=("facility.claim_supply", "radial.closed_exterior"),
            )
        self.assertEqual(overlap.exception.reason_code, "CONTRADICTORY_SUCCESSORS")

        with self.assertRaises(RadialSemanticsError) as empty:
            _control(identity, expected=(), forbidden=("radial.closed_exterior",))
        self.assertEqual(empty.exception.reason_code, "EMPTY_SUCCESSOR_SET")

        with self.assertRaises(RadialSemanticsError) as duplicate:
            _control(
                identity,
                expected=("facility.claim_supply", "facility.claim_supply"),
                forbidden=("radial.closed_exterior",),
            )
        self.assertEqual(duplicate.exception.reason_code, "DUPLICATE_SUCCESSOR")

        with self.assertRaises(RadialSemanticsError) as unknown:
            _control(
                identity,
                expected=("not.a.known.successor",),
                forbidden=("radial.closed_exterior",),
            )
        self.assertEqual(unknown.exception.reason_code, "UNKNOWN_SUCCESSOR")

        with self.assertRaises(RadialSemanticsError) as list_form:
            RadialControlObservation(
                source_frame=identity,
                control_id="home.radial.supply_depot.claim_supply",
                label="Claim Supply",
                role=ControlRole.CLAIM,
                recognition_state=RecognitionState.RECOGNIZED,
                recognition_confidence=0.9,
                actionability_state=ActionabilityState.NON_ACTIONABLE,
                actionability_reason="list_rejected",
                expected_successors=["facility.claim_supply"],  # type: ignore[arg-type]
                forbidden_successors=("radial.closed_exterior",),
                owner_facility_semantic_id="home.building.supply_depot",
            )
        self.assertEqual(list_form.exception.reason_code, "INVALID_SUCCESSOR_SET")

    def test_immutability_and_no_numpy_retention(self) -> None:
        identity = _load_replay_fixture_identity(1)
        semantics = _radial(
            identity,
            controls=(
                _control(
                    identity,
                    metadata={"note": "immutable"},
                ),
            ),
        )
        self.assertIsInstance(semantics.metadata, MappingProxyType)
        self.assertIsInstance(semantics.controls[0].metadata, MappingProxyType)
        with self.assertRaises(TypeError):
            semantics.metadata["note"] = "mutated"  # type: ignore[index]
        with self.assertRaises(TypeError):
            semantics.controls[0].metadata["note"] = "mutated"  # type: ignore[index]
        encoded = json.dumps(radial_semantics_evidence_snapshot(semantics), sort_keys=True)
        self.assertNotIn("ndarray", encoded.lower())
        self.assertNotIn("numpy", encoded.lower())
        self.assertNotIn("dtype", encoded.lower())

    def test_deterministic_serialization_snapshot(self) -> None:
        identity = _load_replay_fixture_identity(1)
        semantics = _radial(identity)
        first = radial_semantics_evidence_snapshot(semantics)
        second = radial_semantics_evidence_snapshot(semantics)
        self.assertEqual(first, second)
        self.assertEqual(first["schema_name"], SCHEMA_NAME)
        self.assertEqual(first["schema_version"], SCHEMA_VERSION)
        left = json.dumps(first, sort_keys=True, separators=(",", ":"))
        right = json.dumps(second, sort_keys=True, separators=(",", ":"))
        self.assertEqual(left, right)

    def test_perception_bundle_typed_adoption_and_regression(self) -> None:
        identity = _load_replay_fixture_identity(1)
        semantics = _radial(identity)
        observation = to_immutable_radial_observation(semantics)
        self.assertIsInstance(observation, ImmutableRadialObservation)
        self.assertIs(observation.semantics, semantics)
        bundle = bundle_from_identity(identity).with_radial(observation)
        self.assertIs(bundle.radial, observation)
        # Legacy summary construction without typed semantics remains valid.
        legacy = ImmutableRadialObservation(identity, "home.building.fighter_camp", 0.9)
        legacy_bundle = bundle_from_identity(identity).with_radial(legacy)
        self.assertIsNone(legacy_bundle.radial.semantics)
        self.assertEqual(legacy_bundle.radial.facility_identity, "home.building.fighter_camp")

    def test_bundle_rejects_cross_capture_semantics_composition(self) -> None:
        first = _load_replay_fixture_identity(1)
        second = _load_replay_fixture_identity(2)
        semantics = _radial(second)
        with self.assertRaises(PerceptionBundleError) as raised:
            ImmutableRadialObservation(
                source_frame=first,
                facility_identity=semantics.owning_facility.facility_semantic_id,
                confidence=semantics.recognition_confidence,
                semantics=semantics,
            )
        self.assertIn(
            raised.exception.reason_code,
            {"CAPTURE_EVENT_MISMATCH", "DIGEST_ONLY_JOIN_REJECTED"},
        )

    def test_typed_unknown_radial_context_fails_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        control = _control(
            identity,
            actionability=ActionabilityState.NON_ACTIONABLE,
            reason="radial_unknown",
        )
        semantics = _radial(
            identity,
            controls=(control,),
            recognition_state=RecognitionState.UNKNOWN,
            confidence=0.0,
        )
        context = classify_frame_context(
            _canonical_bundle_with_typed_radial(identity, semantics)
        )
        self.assertEqual(context.contextual_class, ContextualClass.UNKNOWN)
        self.assertFalse(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.0)
        self.assertEqual(context.reason_code, "TYPED_RADIAL_UNKNOWN")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
                "typed_radial:unknown:none",
            ),
        )
        self.assertIs(control.actionability_state, ActionabilityState.NON_ACTIONABLE)
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))

    def test_typed_ambiguous_radial_context_fails_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        control = _control(
            identity,
            actionability=ActionabilityState.NON_ACTIONABLE,
            reason="radial_ambiguous",
        )
        semantics = _radial(
            identity,
            controls=(control,),
            recognition_state=RecognitionState.AMBIGUOUS,
            confidence=0.4,
            ambiguity=RadialAmbiguityState.UNRESOLVED,
        )
        context = classify_frame_context(
            _canonical_bundle_with_typed_radial(identity, semantics)
        )
        self.assertEqual(context.contextual_class, ContextualClass.UNKNOWN)
        self.assertFalse(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.0)
        self.assertEqual(context.reason_code, "TYPED_RADIAL_AMBIGUOUS")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
                "typed_radial:ambiguous:unresolved",
            ),
        )
        self.assertIs(control.actionability_state, ActionabilityState.NON_ACTIONABLE)
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))

    def test_typed_unknown_owner_context_fails_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        control = _control(
            identity,
            actionability=ActionabilityState.NON_ACTIONABLE,
            reason="owner_unknown",
        )
        semantics = _radial(
            identity,
            owner=_owner(
                identity,
                recognition_state=RecognitionState.UNKNOWN,
                confidence=0.0,
            ),
            controls=(control,),
        )
        context = classify_frame_context(
            _canonical_bundle_with_typed_radial(identity, semantics)
        )
        self.assertEqual(context.contextual_class, ContextualClass.UNKNOWN)
        self.assertFalse(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.0)
        self.assertEqual(context.reason_code, "TYPED_RADIAL_OWNER_UNKNOWN")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
                "typed_radial:recognized:none",
                "typed_radial_owner:unknown:none",
            ),
        )
        self.assertIs(control.actionability_state, ActionabilityState.NON_ACTIONABLE)
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))

    def test_typed_ambiguous_owner_context_fails_closed(self) -> None:
        identity = _load_replay_fixture_identity(1)
        control = _control(
            identity,
            actionability=ActionabilityState.NON_ACTIONABLE,
            reason="owner_ambiguous",
        )
        semantics = _radial(
            identity,
            owner=_owner(
                identity,
                recognition_state=RecognitionState.AMBIGUOUS,
                confidence=0.4,
                ambiguity=RadialAmbiguityState.MULTIPLE_OWNERS,
            ),
            controls=(control,),
        )
        context = classify_frame_context(
            _canonical_bundle_with_typed_radial(identity, semantics)
        )
        self.assertEqual(context.contextual_class, ContextualClass.UNKNOWN)
        self.assertFalse(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.0)
        self.assertEqual(context.reason_code, "TYPED_RADIAL_OWNER_AMBIGUOUS")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
                "typed_radial:recognized:none",
                "typed_radial_owner:ambiguous:multiple_owners",
            ),
        )
        self.assertIs(control.actionability_state, ActionabilityState.NON_ACTIONABLE)
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))

    def test_typed_positive_non_actionable_context_is_recognized_not_interactive(self) -> None:
        identity = _load_replay_fixture_identity(1)
        control = _control(
            identity,
            actionability=ActionabilityState.NON_ACTIONABLE,
            reason="recognized_but_policy_not_actionable",
        )
        semantics = _radial(identity, controls=(control,))
        context = classify_frame_context(
            _canonical_bundle_with_typed_radial(identity, semantics)
        )
        self.assertEqual(
            context.contextual_class,
            ContextualClass.HOME_WITH_KNOWN_RADIAL,
        )
        self.assertTrue(context.context_recognized)
        self.assertFalse(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.96)
        self.assertEqual(context.reason_code, "home_with_known_radial")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
                "typed_radial:recognized:none",
                "typed_radial_owner:recognized:none",
            ),
        )
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))

    def test_legacy_untyped_radial_context_behavior_is_preserved(self) -> None:
        identity = _load_replay_fixture_identity(1)
        typed = _radial(identity)
        bundle = _canonical_bundle_with_typed_radial(identity, typed)
        legacy = replace(
            bundle,
            radial=ImmutableRadialObservation(
                source_frame=identity,
                facility_identity="home.building.supply_depot",
                confidence=0.96,
            ),
        )
        context = classify_frame_context(legacy)
        self.assertEqual(
            context.contextual_class,
            ContextualClass.HOME_WITH_KNOWN_RADIAL,
        )
        self.assertTrue(context.context_recognized)
        self.assertTrue(context.context_allows_interaction)
        self.assertEqual(context.confidence, 0.96)
        self.assertEqual(context.reason_code, "home_with_known_radial")
        self.assertEqual(
            context.supporting_observations,
            (
                "canonical_home_localization",
                "radial:home.building.supply_depot",
            ),
        )

    def test_shared_module_source_scan_forbids_adapter_transport(self) -> None:
        source = inspect.getsource(radial_semantics_module)
        forbidden = (
            "BlueStacks",
            "bluestacks",
            "ADB",
            "adb ",
            "Unraid",
            "pnsctl",
            "tap(",
            "dispatch_input",
            "import cv2",
            "import numpy",
            "CapturedNativeFrame",
            "800, 1280",
            "(400,",
            "runtime_profile_id=",
        )
        for needle in forbidden:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, source)
        self.assertIn("never authorize dispatch", radial_semantics_authorize_dispatch.__doc__.lower())
        self.assertFalse(hasattr(radial_semantics_module, "dispatch"))
        self.assertFalse(hasattr(radial_semantics_module, "tap"))

    def test_non_actionable_unknown_owner_radial_is_constructible(self) -> None:
        identity = _load_replay_fixture_identity(1)
        semantics = HomeRadialSemantics(
            source_frame=identity,
            radial_identity="home.radial.unknown",
            recognition_state=RecognitionState.UNKNOWN,
            recognition_confidence=0.0,
            owning_facility=_owner(
                identity,
                facility_id="home.building.unknown",
                recognition_state=RecognitionState.UNKNOWN,
                confidence=0.0,
            ),
            controls=(
                _control(
                    identity,
                    control_id="home.radial.unknown.control",
                    label="Unknown",
                    role=ControlRole.INFO,
                    recognition_state=RecognitionState.UNKNOWN,
                    confidence=0.0,
                    actionability=ActionabilityState.NON_ACTIONABLE,
                    reason="unknown_owner_and_radial",
                    owner_id="home.building.unknown",
                ),
            ),
            ambiguity_state=RadialAmbiguityState.UNRESOLVED,
        )
        self.assertFalse(semantics.recognized)
        self.assertFalse(semantics.any_actionable_control)
        self.assertFalse(radial_semantics_authorize_dispatch(semantics))


if __name__ == "__main__":
    unittest.main()
