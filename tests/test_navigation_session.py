"""Offline tests for resumable navigation sessions (review-corrected)."""

from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.home_atlas_bluestacks import command_navigate_building
from tasks.home_atlas import AmbiguityState, BuildingBinding, LocalizationResult, ZoomIdentity
from tasks.home_atlas_planner import GestureCalibration, SafeInteractionRegion
from tasks.navigation_session import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    AuthorizationScope,
    ContinuationMode,
    ConclusiveNonDispatchEvidence,
    ConclusiveNonDispatchReason,
    LedgerStatus,
    NavigationCheckpoint,
    NavigationSessionError,
    SessionOutcome,
    TrustedTransportNonDispatchAuthority,
    UncertainPreparedResolution,
    begin_continuation,
    complete_route_at_target_bound,
    compute_pan_gesture_fingerprint,
    create_session,
    make_pan_action_key,
    mark_blocked,
    mark_dry_run,
    record_home_recovered,
    record_pan_dispatched,
    record_pan_prepared,
    record_plan,
    record_radial_verified,
    record_safe_exit,
    record_source_home_verified,
    record_target_bound,
    reconcile_pan,
    reconcile_uncertain_pan,
    save_session,
    load_session,
    executable_tap_roi_from_session,
    derive_allowed_actions,
)
from tasks.perception_bundle import (
    ContextualClass,
    FrameValidityState,
    ImmutableFrameValidationObservation,
    ImmutableRadialObservation,
    NativeFrameIdentity,
    binding_from_result,
    bundle_from_identity,
    classify_and_attach,
    localization_from_result,
)


PROFILE = "pns-bluestacks-5-p64-800x1280-v1"
PLATFORM = "BlueStacks 5 / Android"
BUILDING = "home.building.supply_depot"


def digest(tag: str) -> str:
    nibble = tag[:1].lower()
    if nibble not in "0123456789abcdef":
        raise AssertionError("digest tag must be a hex nibble")
    return nibble * 64


def scope(**overrides) -> AuthorizationScope:
    values = dict(
        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
        owner_operator="test-operator",
        action_class="navigation_only",
        platform=PLATFORM,
        profile=PROFILE,
        environment="fixture",
        target_building_id=BUILDING,
    )
    values.update(overrides)
    return AuthorizationScope(**values)


def identity(
    *,
    session: str = "runtime-session-a",
    ordinal: int = 1,
    monotonic: float = 1000.0,
    transport: str = "a",
    semantic: str = "b",
    label: str = "fixture",
    profile_id: str = PROFILE,
) -> NativeFrameIdentity:
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=session,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=digest(transport),
        semantic_sha256=digest(semantic),
        runtime_profile_id=profile_id,
        width=800,
        height=1280,
        label=label,
    )


def localization_result(frame: NativeFrameIdentity, **overrides) -> LocalizationResult:
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
        frame_sha256=frame.semantic_sha256,
        timestamp="2026-07-19T00:00:00+00:00",
        stale=False,
        overlay=False,
    )
    values.update(overrides)
    return LocalizationResult(**values)


def binding_result(frame: NativeFrameIdentity, **overrides) -> BuildingBinding:
    values = dict(
        building_id=BUILDING,
        target_roi=(320, 420, 420, 520),
        frame_sha256=frame.semantic_sha256,
        confidence=0.94,
        semantic_evidence=("current-frame OCR: Supply Depot",),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )
    values.update(overrides)
    return BuildingBinding(**values)


def frame_validation(frame: NativeFrameIdentity) -> ImmutableFrameValidationObservation:
    return ImmutableFrameValidationObservation(
        source_frame=frame,
        validity=FrameValidityState.VALID_NATIVE,
        expected_profile_id=PROFILE,
        expected_width=800,
        expected_height=1280,
        expected_platform=PLATFORM,
        package_ok=True,
        orientation_ok=True,
        supporting_evidence=("fixture",),
    )


def home_bundle(
    frame: NativeFrameIdentity,
    *,
    with_binding: bool = False,
    localization_overrides: dict | None = None,
    binding_overrides: dict | None = None,
):
    loc = localization_result(frame, **(localization_overrides or {}))
    bundle = (
        bundle_from_identity(frame)
        .with_frame_validation(frame_validation(frame))
        .with_localization(localization_from_result(frame, loc))
    )
    if with_binding:
        bundle = bundle.with_building_binding(
            binding_from_result(frame, binding_result(frame, **(binding_overrides or {})))
        )
    return classify_and_attach(bundle)


def radial_home_bundle(
    frame: NativeFrameIdentity,
    *,
    facility_identity: str = BUILDING,
    localization_overrides: dict | None = None,
):
    loc = localization_result(frame, **(localization_overrides or {}))
    bundle = (
        bundle_from_identity(frame)
        .with_frame_validation(frame_validation(frame))
        .with_localization(localization_from_result(frame, loc))
        .with_radial(ImmutableRadialObservation(frame, facility_identity, 0.91, ("fixture-radial",)))
    )
    classified = classify_and_attach(bundle)
    assert classified.context is not None
    assert classified.context.contextual_class is ContextualClass.HOME_WITH_KNOWN_RADIAL
    return classified


def prepared_uncertain_session(requested=(10.0, 0.0), predicted=(9.0, 0.0)):
    session, frame = verified_session()
    record_plan(session, requested=requested, predicted=predicted)
    next_pan = session.pan_ordinal + 1
    fingerprint = compute_pan_gesture_fingerprint(
        session, pan_ordinal=next_pan, requested=requested, predicted=predicted, source_frame=frame
    )
    action_key = make_pan_action_key(session, fingerprint, next_pan)
    record_pan_prepared(
        session,
        action_key=action_key,
        source_frame=frame,
        requested=requested,
        predicted=predicted,
        gesture_fingerprint=fingerprint,
    )
    return session, frame, action_key, fingerprint


def save_reload(session):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session.json"
        save_session(session, path)
        return load_session(path)


def verified_session(*, runtime: str = "runtime-session-a"):
    session = create_session(scope(), runtime_capture_session_id=runtime, maximum_pans=4)
    frame = identity(session=runtime, ordinal=1, transport="1", semantic="2")
    record_source_home_verified(session, frame=frame, localization_confidence=0.95)
    return session, frame


def prepare_and_dispatch(session, frame, *, requested=(10.0, 0.0), predicted=(9.0, 0.0), key=None):
    record_plan(session, requested=requested, predicted=predicted)
    next_pan = session.pan_ordinal + 1
    fingerprint = compute_pan_gesture_fingerprint(
        session,
        pan_ordinal=next_pan,
        requested=requested,
        predicted=predicted,
        source_frame=frame,
    )
    action_key = key or make_pan_action_key(session, fingerprint, next_pan)
    record_pan_prepared(
        session,
        action_key=action_key,
        source_frame=frame,
        requested=requested,
        predicted=predicted,
        gesture_fingerprint=fingerprint,
    )
    record_pan_dispatched(session, action_key)
    return action_key, fingerprint


class NavigationSessionTests(unittest.TestCase):
    def test_resume_after_pan_restores_history_without_auto_dispatch(self):
        session, frame = verified_session()
        action_key, _ = prepare_and_dispatch(session, frame)
        post = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        reconcile_pan(session, action_key, post_frame=post, accepted=True, reason="progress_ok", measured=(9.0, 0.0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            save_session(session, path)
            loaded = load_session(path)
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PAN_RELOCALIZED)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        decision = begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        self.assertIn("plan", decision.allowed_actions)
        self.assertNotIn("dispatch", decision.allowed_actions)

    def test_failed_post_pan_observation_reconcile_then_replan(self):
        session, frame = verified_session()
        action_key, _ = prepare_and_dispatch(session, frame)
        post = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        reconcile_pan(session, action_key, post_frame=post, accepted=False, reason="post_pan_localization_failed")
        self.assertEqual(session.outcome, SessionOutcome.BLOCKED)
        self.assertEqual(session.checkpoint, NavigationCheckpoint.PAN_DISPATCHED)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.json"
            save_session(session, path)
            loaded = load_session(path)
        self.assertEqual(loaded.outcome, SessionOutcome.BLOCKED)
        self.assertTrue(any(e.status is LedgerStatus.SUPPRESSED for e in loaded.action_ledger))
        fresh = identity(session=frame.runtime_session_id, ordinal=9, transport="7", semantic="8", monotonic=2000.0)
        decision = begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        self.assertEqual(decision.allowed_actions, ("observe", "reconcile_observation"))
        self.assertNotIn("plan", decision.allowed_actions)
        self.assertNotIn("bind", decision.allowed_actions)
        reconcile_uncertain_pan(
            loaded,
            action_key=action_key,
            post_frame=fresh,
            accepted=True,
            reason="observation_only_recovery",
            measured=(8.0, 0.0),
            residual=(2.0, 0.0),
            progress_px=8.0,
        )
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PAN_RELOCALIZED)
        self.assertEqual(loaded.outcome, SessionOutcome.ACTIVE)
        # Materially different correction after recovery.
        record_plan(loaded, requested=(40.0, 5.0), predicted=(35.0, 4.0))
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PLAN_CREATED)
        next_frame = identity(session=frame.runtime_session_id, ordinal=10, transport="9", semantic="a", monotonic=2001.0)
        next_pan = loaded.pan_ordinal + 1
        fingerprint = compute_pan_gesture_fingerprint(
            loaded,
            pan_ordinal=next_pan,
            requested=(40.0, 5.0),
            predicted=(35.0, 4.0),
            source_frame=next_frame,
        )
        new_key = make_pan_action_key(loaded, fingerprint, next_pan)
        record_pan_prepared(
            loaded,
            action_key=new_key,
            source_frame=next_frame,
            requested=(40.0, 5.0),
            predicted=(35.0, 4.0),
            gesture_fingerprint=fingerprint,
        )
        self.assertEqual(loaded.action_ledger[-1].status, LedgerStatus.PREPARED)

    def test_recovery_only_from_recognized_radial_public_api_chain(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        self.assertEqual(session.outcome, SessionOutcome.ACTIVE)
        self.assertEqual(session.route_result.status, "leg_complete")
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        exit_frame = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        record_safe_exit(session, frame=exit_frame)
        home = identity(session=frame.runtime_session_id, ordinal=4, transport="7", semantic="8", monotonic=1003.0)
        record_home_recovered(session, frame=home)
        self.assertEqual(session.checkpoint, NavigationCheckpoint.HOME_RECOVERED)
        self.assertEqual(session.outcome, SessionOutcome.COMPLETED)
        fresh = identity(session="proc-b", ordinal=1, transport="9", semantic="a", monotonic=1.0)
        # Completed sessions reject continuation via SESSION_NOT_ACTIVE on mutating APIs;
        # begin_continuation validate allows load of completed but recovery mode checks.
        with self.assertRaises(NavigationSessionError):
            begin_continuation(
                session, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
            )

    def test_recovery_only_allowed_actions_from_radial(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        decision = begin_continuation(
            session,
            authorization=scope(),
            fresh_identity=fresh,
            perception_factory=lambda: radial_home_bundle(fresh),
        )
        self.assertEqual(decision.mode, ContinuationMode.RECOVERY_ONLY)
        self.assertEqual(decision.allowed_actions, ("observe", "safe_exit"))
        self.assertNotIn("plan", decision.allowed_actions)

    def test_radial_verified_continuation_accepts_home_with_known_radial(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        bundle = radial_home_bundle(fresh, facility_identity=BUILDING)
        self.assertEqual(bundle.context.contextual_class, ContextualClass.HOME_WITH_KNOWN_RADIAL)
        decision = begin_continuation(
            session,
            authorization=scope(),
            fresh_identity=fresh,
            perception_factory=lambda: bundle,
        )
        self.assertEqual(decision.mode, ContinuationMode.RECOVERY_ONLY)
        self.assertEqual(decision.allowed_actions, ("observe", "safe_exit"))
        self.assertEqual(session.latest_observation.contextual_class, ContextualClass.HOME_WITH_KNOWN_RADIAL.value)

    def test_radial_verified_rejects_wrong_facility(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        before = session.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=fresh,
                perception_factory=lambda: radial_home_bundle(
                    fresh, facility_identity="home.building.fighter_camp"
                ),
            )
        self.assertEqual(raised.exception.reason_code, "RADIAL_FACILITY_MISMATCH")
        self.assertEqual(session.to_dict(), before)

    def test_radial_verified_rejects_missing_radial(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        before = session.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=fresh,
                perception_factory=lambda: home_bundle(fresh),
            )
        self.assertEqual(raised.exception.reason_code, "RADIAL_OBSERVATION_MISSING")
        self.assertEqual(session.to_dict(), before)

    def test_blocked_at_created_continuation_advertises_verify_source(self):
        session = create_session(scope(), runtime_capture_session_id="runtime-created")
        self.assertEqual(session.checkpoint, NavigationCheckpoint.CREATED)
        mark_blocked(session, reason="source_home_unrecognized")
        fresh = identity(session="runtime-created", ordinal=1, transport="1", semantic="2")
        decision = begin_continuation(
            session, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        self.assertIn("verify_source", decision.allowed_actions)
        self.assertNotEqual(decision.allowed_actions, ("observe",))

    def test_stale_binding_rejection(self):
        session, frame = verified_session()
        record_plan(session)
        stale = binding_result(frame, frame_sha256=digest("9"))
        before = session.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            record_target_bound(session, binding=stale, frame=frame)
        self.assertEqual(raised.exception.reason_code, "STALE_BINDING")
        self.assertEqual(session.to_dict(), before)
        self.assertIsNone(executable_tap_roi_from_session(session))

    def test_authorization_profile_platform_building_mismatches(self):
        session, frame = verified_session()
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(owner_operator="other"),
                fresh_identity=fresh,
                perception_factory=lambda: home_bundle(fresh),
            )
        self.assertEqual(raised.exception.reason_code, "AUTHORIZATION_MISMATCH")

        bad_profile_id = identity(
            session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0, profile_id="wrong-profile"
        )
        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=bad_profile_id,
                perception_factory=lambda: home_bundle(bad_profile_id),
            )
        self.assertEqual(raised.exception.reason_code, "RUNTIME_PROFILE_MISMATCH")

        # Force checked_navigation_inputs to succeed with Bliss platform, then fail auth compare.
        bliss = "Bliss OS"
        identity_ok = fresh

        def bliss_bundle():
            loc = localization_result(identity_ok, platform=bliss, profile_id=PROFILE)
            return classify_and_attach(
                bundle_from_identity(identity_ok)
                .with_frame_validation(
                    ImmutableFrameValidationObservation(
                        source_frame=identity_ok,
                        validity=FrameValidityState.VALID_NATIVE,
                        expected_profile_id=PROFILE,
                        expected_width=800,
                        expected_height=1280,
                        expected_platform=bliss,
                        package_ok=True,
                        orientation_ok=True,
                        supporting_evidence=("fixture",),
                    )
                )
                .with_localization(localization_from_result(identity_ok, loc))
            )

        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=identity_ok,
                perception_factory=bliss_bundle,
            )
        self.assertEqual(raised.exception.reason_code, "LOCALIZATION_PLATFORM_MISMATCH")

        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=fresh,
                perception_factory=lambda: home_bundle(
                    fresh, localization_overrides={"profile_id": "other-profile"}
                ),
            )
        self.assertEqual(raised.exception.reason_code, "LOCALIZATION_PROFILE_MISMATCH")

        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=fresh,
                perception_factory=lambda: home_bundle(
                    fresh, with_binding=True, binding_overrides={"building_id": "home.building.bank"}
                ),
            )
        self.assertEqual(raised.exception.reason_code, "BINDING_BUILDING_MISMATCH")

    def test_duplicate_gesture_new_key_rejected_and_material_correction_accepted(self):
        session, frame = verified_session()
        record_plan(session, requested=(10.0, 0.0), predicted=(9.0, 0.0))
        next_pan = session.pan_ordinal + 1
        fingerprint = compute_pan_gesture_fingerprint(
            session, pan_ordinal=next_pan, requested=(10.0, 0.0), predicted=(9.0, 0.0), source_frame=frame
        )
        key1 = make_pan_action_key(session, fingerprint, next_pan)
        record_pan_prepared(
            session,
            action_key=key1,
            source_frame=frame,
            requested=(10.0, 0.0),
            predicted=(9.0, 0.0),
            gesture_fingerprint=fingerprint,
        )
        with self.assertRaises(NavigationSessionError) as raised:
            record_pan_prepared(
                session,
                action_key=key1 + "-alt",
                source_frame=frame,
                requested=(10.0, 0.0),
                predicted=(9.0, 0.0),
            )
        self.assertEqual(raised.exception.reason_code, "DUPLICATE_GESTURE_SUPPRESSED")

        # Crash-suppress then confirm dispatched+relocalized with positive progress.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gest.json"
            save_session(session, path)
            loaded = load_session(path)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        reconcile_uncertain_pan(
            loaded,
            post_frame=fresh,
            resolution=UncertainPreparedResolution.CONFIRMED_DISPATCHED_AND_RELOCALIZED,
            reason="uncertain_prepared_confirmed_dispatched",
            measured=(8.0, 0.0),
            residual=(1.0, 0.0),
            progress_px=8.0,
        )
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PAN_RELOCALIZED)
        record_plan(loaded, requested=(55.0, 12.0), predicted=(50.0, 10.0))
        next_frame = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        next_pan = loaded.pan_ordinal + 1
        new_fp = compute_pan_gesture_fingerprint(
            loaded,
            pan_ordinal=next_pan,
            requested=(55.0, 12.0),
            predicted=(50.0, 10.0),
            source_frame=next_frame,
        )
        new_key = make_pan_action_key(loaded, new_fp, next_pan)
        record_pan_prepared(
            loaded,
            action_key=new_key,
            source_frame=next_frame,
            requested=(55.0, 12.0),
            predicted=(50.0, 10.0),
            gesture_fingerprint=new_fp,
        )
        self.assertNotEqual(new_fp, fingerprint)

    def test_crash_after_transport_before_dispatched_persistence(self):
        session, frame, _action_key, _fingerprint = prepared_uncertain_session()
        loaded = save_reload(session)
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PLAN_CREATED)
        self.assertEqual(loaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(loaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertEqual(loaded.action_ledger[0].pre_uncertainty_status, LedgerStatus.PREPARED.value)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        decision = begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        self.assertEqual(decision.allowed_actions, ("observe", "reconcile_observation"))
        reconcile_uncertain_pan(
            loaded,
            post_frame=fresh,
            resolution=UncertainPreparedResolution.CONFIRMED_DISPATCHED_AND_RELOCALIZED,
            reason="uncertain_prepared_may_have_dispatched",
            measured=(9.0, 0.0),
            residual=(1.0, 0.0),
            progress_px=9.0,
        )
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PAN_RELOCALIZED)
        self.assertEqual(loaded.outcome, SessionOutcome.ACTIVE)
        self.assertEqual(
            loaded.route_result.reason,
            "uncertain_prepared_confirmed_dispatched_and_relocalized",
        )
        self.assertEqual(loaded.pan_ordinal, 1)
        self.assertTrue(loaded.displacement_history)

    def test_confirmed_not_dispatched_unavailable_without_runtime_owned_verifier(self):
        session, frame, action_key, fingerprint = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        before = loaded.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            reconcile_uncertain_pan(
                loaded,
                post_frame=fresh,
                resolution=UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED,
                reason="zero_movement_alone",
                measured=(0.0, 0.0),
                progress_px=0.0,
            )
        self.assertEqual(raised.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        self.assertEqual(loaded.to_dict(), before)
        self.assertEqual(loaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertIn(action_key, loaded.pending_suppressions)
        self.assertIn(fingerprint, loaded.pending_gesture_suppressions)
        self.assertNotIn("plan", derive_allowed_actions(loaded))

    def test_transport_non_dispatch_authority_cannot_be_caller_instantiated(self):
        with self.assertRaises(NavigationSessionError) as raised:
            TrustedTransportNonDispatchAuthority(authority_id="caller-selected-authority")
        self.assertEqual(raised.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")

    def test_forged_non_dispatch_evidence_rejected(self):
        session, frame, action_key, _fp = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        before = loaded.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            ConclusiveNonDispatchEvidence(
                action_key=action_key,
                gesture_fingerprint=loaded.action_ledger[0].gesture_fingerprint,
                route_id=loaded.route_id,
                navigation_session_id=loaded.navigation_session_id,
                runtime_capture_session_id=frame.runtime_session_id,
                transport_attempt_id="forged",
                reason=ConclusiveNonDispatchReason.NEVER_SUBMITTED_TO_DEVICE,
                authority_id="forged-caller",
                attestation_digest=digest("e"),
            )
        self.assertEqual(raised.exception.reason_code, "UNTRUSTED_NON_DISPATCH_EVIDENCE")
        self.assertEqual(loaded.to_dict(), before)

    def test_save_load_preserves_suppression_without_non_dispatch_authority(self):
        session, frame, action_key, fingerprint = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        reconcile_uncertain_pan(
            loaded,
            post_frame=fresh,
            resolution=UncertainPreparedResolution.STILL_AMBIGUOUS,
            reason="waiting_for_transport_ledger",
        )
        reloaded = save_reload(loaded)
        self.assertEqual(reloaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(reloaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertIn(action_key, reloaded.pending_suppressions)
        self.assertIn(fingerprint, reloaded.pending_gesture_suppressions)
        next_fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        begin_continuation(
            reloaded,
            authorization=scope(),
            fresh_identity=next_fresh,
            perception_factory=lambda: home_bundle(next_fresh),
        )
        before = reloaded.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            reconcile_uncertain_pan(
                reloaded,
                post_frame=next_fresh,
                resolution=UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED,
                reason="caller_claims_never_submitted",
            )
        self.assertEqual(raised.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        self.assertEqual(reloaded.to_dict(), before)
        self.assertEqual(reloaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(reloaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertIn(action_key, reloaded.pending_suppressions)

    def test_uncertain_prepared_dispatched_requires_positive_progress(self):
        session, frame, _action_key, _fp = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        before = loaded.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            reconcile_uncertain_pan(
                loaded,
                post_frame=fresh,
                resolution=UncertainPreparedResolution.CONFIRMED_DISPATCHED_AND_RELOCALIZED,
                reason="zero_progress",
                measured=(0.0, 0.0),
                residual=(0.0, 0.0),
                progress_px=0.0,
            )
        self.assertEqual(raised.exception.reason_code, "POSITIVE_PROGRESS_REQUIRED")
        self.assertEqual(loaded.to_dict(), before)

    def test_uncertain_prepared_still_ambiguous_survives_save_load_continuation(self):
        session, frame, action_key, fingerprint = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        reconcile_uncertain_pan(
            loaded,
            post_frame=fresh,
            resolution=UncertainPreparedResolution.STILL_AMBIGUOUS,
            reason="observation_failed",
            localization_recognized=False,
        )
        self.assertEqual(loaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(loaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertIn(action_key, loaded.pending_suppressions)
        self.assertIn(fingerprint, loaded.pending_gesture_suppressions)
        self.assertNotIn("plan", derive_allowed_actions(loaded))
        reloaded = save_reload(loaded)
        self.assertEqual(reloaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(reloaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        next_fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        decision = begin_continuation(
            reloaded,
            authorization=scope(),
            fresh_identity=next_fresh,
            perception_factory=lambda: home_bundle(next_fresh),
        )
        self.assertEqual(decision.allowed_actions, ("observe", "reconcile_observation"))
        self.assertNotIn("plan", decision.allowed_actions)
        self.assertNotIn("bind", decision.allowed_actions)
        self.assertIn(action_key, reloaded.pending_suppressions)

    def test_uncertain_prepared_failed_observation_defaults_to_still_ambiguous(self):
        session, frame, action_key, _fp = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        before = loaded.to_dict()
        with self.assertRaises(NavigationSessionError) as raised:
            reconcile_uncertain_pan(
                loaded,
                post_frame=fresh,
                accepted=False,
                reason="legacy_accepted_not_allowed",
            )
        self.assertEqual(raised.exception.reason_code, "PREPARED_REQUIRES_EXPLICIT_RESOLUTION")
        self.assertEqual(loaded.to_dict(), before)
        reconcile_uncertain_pan(
            loaded,
            post_frame=fresh,
            resolution=UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED,
            reason="unrecognized_forces_ambiguous",
            localization_recognized=False,
            measured=(0.0, 0.0),
            progress_px=0.0,
        )
        self.assertEqual(loaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertEqual(loaded.action_ledger[0].status, LedgerStatus.SUPPRESSED)
        self.assertIn(action_key, loaded.pending_suppressions)

    def test_unreconciled_dispatched_suppressed_on_load(self):
        session, frame = verified_session()
        action_key, _ = prepare_and_dispatch(session, frame)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dispatched.json"
            save_session(session, path)
            loaded = load_session(path)
        self.assertEqual(loaded.outcome, SessionOutcome.UNCERTAIN)
        self.assertIn(action_key, loaded.pending_suppressions)

    def test_complete_route_at_target_bound_is_explicit(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        self.assertEqual(session.outcome, SessionOutcome.ACTIVE)
        complete_route_at_target_bound(session)
        self.assertEqual(session.outcome, SessionOutcome.COMPLETED)
        self.assertEqual(session.route_result.status, "completed")

    def test_composed_route_result_preserves_route_id(self):
        session, frame = verified_session()
        route_id = session.route_id
        action_key, _ = prepare_and_dispatch(session, frame)
        post = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        reconcile_pan(session, action_key, post_frame=post, accepted=True, reason="ok", measured=(1.0, 0.0))
        record_plan(session, requested=(2.0, 0.0))
        bind_frame = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        record_target_bound(session, binding=binding_result(bind_frame), frame=bind_frame)
        self.assertEqual(session.route_result.route_id, route_id)
        self.assertEqual(session.route_result.status, "leg_complete")

    def test_corrupt_and_unsupported_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.json"
            empty.write_text("", encoding="utf-8")
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(empty)
            self.assertEqual(raised.exception.reason_code, "CORRUPT_SESSION_JSON")
            truncated = root / "truncated.json"
            truncated.write_text('{"schema_name":"navigation_session"', encoding="utf-8")
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(truncated)
            self.assertEqual(raised.exception.reason_code, "CORRUPT_SESSION_JSON")
            unsupported = root / "badver.json"
            unsupported.write_text(
                json.dumps(
                    {
                        "schema_name": SCHEMA_NAME,
                        "schema_version": SCHEMA_VERSION + 99,
                        "route_id": "r",
                        "navigation_session_id": "n",
                        "authorization": asdict_scope(),
                        "checkpoint": "created",
                        "outcome": "active",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(unsupported)
            self.assertEqual(raised.exception.reason_code, "UNSUPPORTED_SCHEMA_VERSION")

    def test_deserialize_rejects_inconsistent_history(self):
        session, _frame = verified_session()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "badhist.json"
            save_session(session, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["checkpoint_history"] = ["created", "target_bound"]
            payload["checkpoint"] = "target_bound"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(path)
            self.assertEqual(raised.exception.reason_code, "CHECKPOINT_HISTORY_INVALID")

    def test_deserialize_rejects_event_ordinal_inconsistent_with_history(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        self.assertEqual(session.checkpoint, NavigationCheckpoint.TARGET_BOUND)
        self.assertGreater(session.event_ordinal, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "badord.json"
            save_session(session, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["event_ordinal"] = 0
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(path)
            self.assertEqual(raised.exception.reason_code, "EVENT_ORDINAL_INCONSISTENT_WITH_HISTORY")

    def test_deserialize_rejects_oversized_event_ordinal(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bigoord.json"
            save_session(session, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["event_ordinal"] = session.event_ordinal + 5
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(NavigationSessionError) as raised:
                load_session(path)
            self.assertEqual(raised.exception.reason_code, "EVENT_ORDINAL_INCONSISTENT_WITH_HISTORY")

    def test_rejected_radial_continuation_leaves_serialized_state_unchanged(self):
        session, frame = verified_session()
        record_plan(session)
        record_target_bound(session, binding=binding_result(frame), frame=frame)
        radial = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        record_radial_verified(session, frame=radial)
        fresh = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        before = session.to_dict()
        with self.assertRaises(NavigationSessionError):
            begin_continuation(
                session,
                authorization=scope(),
                fresh_identity=fresh,
                perception_factory=lambda: radial_home_bundle(
                    fresh, facility_identity="home.building.bank"
                ),
            )
        self.assertEqual(session.to_dict(), before)

    def test_dry_run_does_not_mark_dispatched(self):
        session, _frame = verified_session()
        record_plan(session)
        mark_dry_run(session)
        self.assertEqual(session.route_result.status, "dry_run")
        self.assertFalse(session.action_ledger)

    def test_atomic_replacement_failure_preserves_prior_file(self):
        session, _frame = verified_session()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            save_session(session, path)
            prior = path.read_text(encoding="utf-8")
            session.terminal_reason = "mutated"

            def boom(_src: str, _dst: str) -> None:
                raise OSError("replace failed")

            with self.assertRaises(NavigationSessionError) as raised:
                save_session(session, path, replace=boom)
            self.assertEqual(raised.exception.reason_code, "ATOMIC_REPLACE_FAILED")
            self.assertEqual(path.read_text(encoding="utf-8"), prior)

    def test_exception_safe_rejected_prepare_leaves_session_unchanged(self):
        session, frame = verified_session()
        record_plan(session)
        before = session.to_dict()
        with self.assertRaises(NavigationSessionError):
            record_pan_prepared(session, action_key="", source_frame=frame)
        self.assertEqual(session.to_dict(), before)

    def test_cross_process_freshness(self):
        session, frame = verified_session(runtime="process-a")
        with self.assertRaises(NavigationSessionError):
            begin_continuation(
                session, authorization=scope(), fresh_identity=frame, perception_factory=lambda: home_bundle(frame)
            )
        fresh = identity(session="process-b", ordinal=1, transport="9", semantic="a", monotonic=0.5)
        decision = begin_continuation(
            session, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        self.assertEqual(decision.reason_code, "continuation_ready")

    def test_perception_fresh_identity_mismatch(self):
        session, frame = verified_session()
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        other = identity(session=frame.runtime_session_id, ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        with self.assertRaises(NavigationSessionError) as raised:
            begin_continuation(
                session, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(other)
            )
        self.assertEqual(raised.exception.reason_code, "PERCEPTION_FRESH_IDENTITY_MISMATCH")

    def test_navigate_building_persistence_ordering_with_fakes(self):
        """Invoke command_navigate_building and assert prepared save before swipe, dispatched after."""

        from tasks.home_atlas import AtlasViewport, HomeAtlas, PlatformProfile, SemanticBuilding
        from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest

        events: list[str] = []

        class Runtime:
            execute = True
            in_flight_action = None
            ordinal = 0

            def __init__(self, session: Path):
                self.session = session
                self.swipes = 0

            def capture(self, label):
                self.ordinal += 1
                frame = np.zeros((1280, 800, 3), np.uint8)
                frame[0, 0] = (self.ordinal % 200, 10, 10)
                png = f"png-{self.ordinal}".encode()
                return CapturedNativeFrame(
                    frame,
                    png,
                    "f" * 64,
                    float(self.ordinal),
                    self.session / f"{label}.png",
                )

            def swipe(self, *args, **kwargs):
                events.append("swipe")
                self.swipes += 1

        profile = PlatformProfile(BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, (800, 1280), "com.global.ztmslg")
        far = SemanticBuilding(
            "home.building.bank",
            "Bank",
            ((900.0, 900.0), (1040.0, 900.0), (1040.0, 1040.0), (900.0, 1040.0)),
            0.98,
            ("v1",),
            recognition={"bluestacks": {"label": "Bank"}},
            semantic_proof=("visible Bank label",),
            interaction_eligible=True,
            platform_binding_policy={"bluestacks": {"label": "Bank"}},
        )
        viewport = AtlasViewport(
            "v1",
            "unused.png",
            "a" * 64,
            "now",
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            ((0, 0), (800, 0), (800, 1280), (0, 1280)),
            1,
            0,
            "translation",
        )
        polygons = (((0, 0), (1500, 0), (1500, 2800), (0, 2800)),)
        world = HomeAtlas(
            3,
            "test",
            "1",
            profile,
            "fully_zoomed_out",
            "atlas pixels",
            (0, 0),
            1500,
            2800,
            "atlas.png",
            "test",
            "test",
            polygons,
            (),
            (viewport,),
            (far,),
            polygons,
            (0.0, 0.0, 1500.0, 2800.0),
        )

        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            sample = runtime.capture("seed")
            loc = LocalizationResult(
                recognized=True,
                platform=PLATFORM,
                profile_id=PROFILE,
                zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
                screen_to_atlas=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                viewport_polygon=((0.0, 0.0), (800.0, 0.0), (800.0, 1280.0), (0.0, 1280.0)),
                confidence=0.95,
                supporting_landmarks=("v1",),
                residual_px=0.4,
                ambiguity_state=AmbiguityState.NONE,
                map_edge_state="interior",
                frame_sha256=frame_digest(sample.frame),
                timestamp="now",
            )
            args = SimpleNamespace(
                execute=True,
                yes=True,
                atlas=Path(directory) / "atlas.json",
                building_id=far.semantic_id,
                maximum_pans=4,
                settle_seconds=0,
                adb="unused",
                serial="emulator-5554",
                output_directory=Path(directory),
            )
            fake_localizer = SimpleNamespace(
                localize=lambda frame: replace(loc, frame_sha256=frame_digest(frame))
            )
            real_save = save_session

            def tracking_save(session, path, **kwargs):
                ledger_status = session.action_ledger[-1].status.value if session.action_ledger else "none"
                events.append(f"save:{session.checkpoint.value}:{ledger_status}")
                return real_save(session, path, **kwargs)

            with patch("scripts.home_atlas_bluestacks.load_home_atlas", return_value=world), patch(
                "scripts.home_atlas_bluestacks.BlueStacksHomeLocalizer", return_value=fake_localizer
            ), patch("scripts.home_atlas_bluestacks.connect_runtime", return_value=runtime), patch(
                "scripts.home_atlas_bluestacks.bind_visible_building", return_value=None
            ), patch("scripts.home_atlas_bluestacks.save_session", side_effect=tracking_save):
                command_navigate_building(args)

            prepared_indices = [i for i, e in enumerate(events) if e.endswith(":prepared")]
            swipe_indices = [i for i, e in enumerate(events) if e == "swipe"]
            dispatched_indices = [i for i, e in enumerate(events) if e.endswith(":dispatched")]
            self.assertTrue(prepared_indices, events)
            self.assertTrue(swipe_indices, events)
            self.assertTrue(dispatched_indices, events)
            self.assertLess(prepared_indices[0], swipe_indices[0], events)
            self.assertLess(swipe_indices[0], dispatched_indices[0], events)
            session_path = runtime.session / "navigate-session.json"
            self.assertTrue(session_path.exists())
            loaded = load_session(session_path)
            self.assertEqual(loaded.authorization.target_building_id, far.semantic_id)

    def test_continuation_reconcile_does_not_transport(self):
        session, frame = verified_session()
        action_key, _ = prepare_and_dispatch(session, frame)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json"
            save_session(session, path)
            loaded = load_session(path)
        transports = []
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        reconcile_uncertain_pan(
            loaded, action_key=action_key, post_frame=fresh, accepted=True, reason="obs", measured=(1.0, 0.0), progress_px=1.0
        )
        self.assertEqual(transports, [])
        self.assertEqual(loaded.checkpoint, NavigationCheckpoint.PAN_RELOCALIZED)


def asdict_scope() -> dict:
    return {
        "task_id": "RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
        "owner_operator": "test-operator",
        "action_class": "navigation_only",
        "platform": PLATFORM,
        "profile": PROFILE,
        "environment": "fixture",
        "target_building_id": BUILDING,
    }


if __name__ == "__main__":
    unittest.main()
