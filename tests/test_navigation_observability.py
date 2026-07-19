"""Offline tests for NavigationSession ledger observability."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

from tasks.navigation_observability import (
    AvailabilityValue,
    REPORT_FIELD_ORDER,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    DirectionAgreement,
    FieldAvailability,
    NavigationObservabilityError,
    ReportIntegrity,
    TerminalReportClass,
    deserialize_navigation_observability_report,
    navigation_observability_snapshot,
    report_navigation_session,
    serialize_navigation_observability_report,
)
from tasks.navigation_session import (
    ContinuationMode,
    LedgerStatus,
    NavigationCheckpoint,
    NavigationSessionError,
    SessionOutcome,
    TrustedTransportNonDispatchAuthority,
    UncertainPreparedResolution,
    complete_route_at_target_bound,
    compute_pan_gesture_fingerprint,
    create_session,
    load_session,
    make_pan_action_key,
    mark_blocked,
    mark_uncertain,
    record_home_recovered,
    record_pan_dispatched,
    record_pan_prepared,
    record_plan,
    record_radial_verified,
    record_safe_exit,
    record_target_bound,
    reconcile_pan,
    save_session,
)
from tests.test_navigation_session import (
    binding_result,
    identity,
    prepared_uncertain_session,
    scope,
    verified_session,
)


def _prepare_and_dispatch(session, frame, *, requested=(10.0, 0.0), predicted=(9.0, 0.0)):
    record_plan(
        session,
        requested=requested,
        predicted=predicted,
        remaining=(1.0, 0.0),
        reason="calculated_direct_pan",
        seen_viewport=(100, 200),
    )
    next_pan = session.pan_ordinal + 1
    fingerprint = compute_pan_gesture_fingerprint(
        session,
        pan_ordinal=next_pan,
        requested=requested,
        predicted=predicted,
        source_frame=frame,
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
    record_pan_dispatched(session, action_key)
    return action_key


class NavigationObservabilityTests(unittest.TestCase):
    def test_complete_route_report_fields_and_no_session_mutation(self):
        session, frame = verified_session()
        before = copy.deepcopy(session.to_dict())
        action_key = _prepare_and_dispatch(session, frame, requested=(10.0, 0.0), predicted=(9.0, 0.0))
        post = identity(ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(8.0, 0.0),
            residual=(2.0, 0.0),
            progress_px=8.0,
            accepted=True,
            reason="measured_progress",
            localization_confidence=0.93,
        )
        bind_frame = identity(ordinal=3, transport="5", semantic="6", monotonic=1002.0)
        record_target_bound(
            session,
            frame=bind_frame,
            binding=binding_result(bind_frame),
        )
        radial_frame = identity(ordinal=4, transport="7", semantic="8", monotonic=1003.0)
        record_radial_verified(session, frame=radial_frame)
        exit_frame = identity(ordinal=5, transport="9", semantic="a", monotonic=1004.0)
        record_safe_exit(session, frame=exit_frame)
        home_frame = identity(ordinal=6, transport="b", semantic="c", monotonic=1005.0)
        record_home_recovered(session, frame=home_frame)

        report = report_navigation_session(session)
        after = session.to_dict()
        self.assertEqual(before["navigation_session_id"], after["navigation_session_id"])
        # Mutating APIs above changed the session intentionally; reporting itself must not.
        frozen = copy.deepcopy(session.to_dict())
        _ = report_navigation_session(session)
        self.assertEqual(session.to_dict(), frozen)

        self.assertEqual(report.schema_name, SCHEMA_NAME)
        self.assertEqual(report.schema_version, SCHEMA_VERSION)
        self.assertEqual(report.navigation_session_id, session.navigation_session_id)
        self.assertEqual(report.route_id, session.route_id)
        self.assertEqual(report.source_checkpoint.value, NavigationCheckpoint.CREATED.value)
        self.assertEqual(
            report.terminal_checkpoint.value, NavigationCheckpoint.HOME_RECOVERED.value
        )
        self.assertEqual(report.localization_confidence.availability, FieldAvailability.PRESENT.value)
        self.assertEqual(report.requested_atlas_displacement.availability, FieldAvailability.PRESENT.value)
        self.assertEqual(report.requested_atlas_displacement.x, 10.0)
        self.assertEqual(report.measured_atlas_displacement.x, 8.0)
        self.assertEqual(report.residual_vector.x, 2.0)
        self.assertEqual(report.direction_agreement.value, DirectionAgreement.AGREE.value)
        self.assertAlmostEqual(report.progress_ratio.value, 0.8)
        self.assertEqual(report.safe_exit_availability.value, "verified")
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value)
        self.assertEqual(
            report.non_dispatch_authority.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
        )
        self.assertEqual(
            report.non_dispatch_authority.availability, FieldAvailability.UNAVAILABLE.value
        )
        self.assertGreaterEqual(report.total_frame_count.value, 1)
        self.assertIn("home_recovered", report.per_state_frame_counts.value["checkpoint_visit_counts"])
        self.assertTrue(report.recovery_only_history.value["recovery_only_active"])
        self.assertEqual(
            report.action_authority_separation.transport_confirmed.availability,
            FieldAvailability.PRESENT.value,
        )
        self.assertEqual(
            report.action_authority_separation.authorized.value["authorize_dispatch"], False
        )

    def test_incomplete_active_session_keeps_absent_fields_unknown(self):
        session, _frame = verified_session()
        report = report_navigation_session(session)
        self.assertEqual(report.report_integrity, ReportIntegrity.INCOMPLETE.value)
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.INCOMPLETE.value)
        self.assertEqual(
            report.measured_atlas_displacement.availability, FieldAvailability.UNKNOWN.value
        )
        self.assertEqual(
            report.direction_agreement.availability, FieldAvailability.UNKNOWN.value
        )
        self.assertEqual(report.progress_ratio.availability, FieldAvailability.UNKNOWN.value)
        self.assertEqual(
            report.radial_binding_confidence.availability, FieldAvailability.UNKNOWN.value
        )
        self.assertEqual(
            report.semantic_facility_binding_confidence.availability,
            FieldAvailability.UNKNOWN.value,
        )
        self.assertIsNone(report.repeated_viewports.value["detected"])
        self.assertIsNone(report.camera_map_clamps.value["detected"])

    def test_failed_blocked_session_is_rejection_not_success(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(session, frame)
        post = identity(ordinal=2, transport="3", semantic="4")
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(0.0, 0.0),
            residual=(10.0, 0.0),
            progress_px=0.0,
            accepted=False,
            reason="movement_wrong_direction",
            localization_confidence=0.2,
        )
        report = report_navigation_session(session)
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.REJECTION.value)
        self.assertNotEqual(report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value)
        self.assertEqual(report.direction_agreement.availability, FieldAvailability.UNKNOWN.value)

    def test_mark_blocked_with_clamp_reason_surfaces_clamp_signal(self):
        session, _frame = verified_session()
        record_plan(
            session,
            requested=(40.0, 0.0),
            predicted=(30.0, 0.0),
            remaining=(40.0, 0.0),
            reason="map_edge_clamp_before_target",
            seen_viewport=(10, 20),
        )
        mark_blocked(session, reason="map_edge_clamp_before_target")
        report = report_navigation_session(session)
        self.assertEqual(report.camera_map_clamps.availability, FieldAvailability.PRESENT.value)
        self.assertTrue(report.camera_map_clamps.value["detected"])
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.REJECTION.value)

    def test_repeated_viewport_reason_is_explicit(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(session, frame)
        post = identity(ordinal=2, transport="3", semantic="4")
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(0.0, 0.0),
            residual=(10.0, 0.0),
            progress_px=0.0,
            accepted=False,
            reason="repeated_viewport",
        )
        report = report_navigation_session(session)
        self.assertEqual(report.repeated_viewports.availability, FieldAvailability.PRESENT.value)
        self.assertTrue(report.repeated_viewports.value["detected"])

    def test_resumed_uncertain_prepared_does_not_confirm_transport(self):
        session, _frame, action_key, _fingerprint = prepared_uncertain_session()
        mark_uncertain(session, reason="crash_window", suppress_action_keys=(action_key,))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            save_session(session, path)
            loaded = load_session(path)
        report = report_navigation_session(loaded)
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.UNCERTAIN.value)
        self.assertEqual(
            report.action_authority_separation.dispatched.availability,
            FieldAvailability.UNAVAILABLE.value,
        )
        self.assertEqual(
            report.action_authority_separation.transport_confirmed.availability,
            FieldAvailability.UNAVAILABLE.value,
        )
        self.assertEqual(
            report.action_authority_separation.transport_confirmed.reason_code,
            "UNCERTAIN_PREPARED_NOT_TRANSPORT",
        )
        self.assertEqual(report.action_ledger_summary.suppressed_count, 1)
        self.assertEqual(
            report.non_dispatch_authority.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
        )

    def test_recovery_only_history_and_safe_exit(self):
        session, frame = verified_session()
        bind = identity(ordinal=2, transport="3", semantic="4")
        # Skip pans: plan then bind requires TARGET_BOUND path without pan when planner allows.
        record_plan(session, requested=(0.0, 0.0), predicted=(0.0, 0.0), reason="already_in_view")
        record_target_bound(session, frame=bind, binding=binding_result(bind))
        radial = identity(ordinal=3, transport="5", semantic="6")
        record_radial_verified(session, frame=radial)
        self.assertEqual(session.continuation_mode, ContinuationMode.RECOVERY_ONLY)
        report = report_navigation_session(session)
        self.assertTrue(report.recovery_only_history.value["recovery_only_active"])
        self.assertIn(
            NavigationCheckpoint.RADIAL_VERIFIED.value,
            report.recovery_only_history.value["recovery_checkpoints"],
        )
        self.assertEqual(
            report.safe_exit_availability.availability, FieldAvailability.UNKNOWN.value
        )
        self.assertEqual(
            report.radial_binding_confidence.reason_code, "RADIAL_VERIFIED_WITHOUT_CONFIDENCE"
        )
        exit_frame = identity(ordinal=4, transport="7", semantic="8")
        record_safe_exit(session, frame=exit_frame)
        report2 = report_navigation_session(session)
        self.assertEqual(report2.safe_exit_availability.value, "verified")

    def test_duplicate_suppressed_ledger_summary(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(session, frame)
        mark_uncertain(session, reason="operator_pause", suppress_action_keys=(action_key,))
        report = report_navigation_session(session)
        self.assertEqual(report.action_ledger_summary.suppressed_count, 1)
        self.assertEqual(report.action_ledger_summary.entries[0]["status"], LedgerStatus.SUPPRESSED.value)
        self.assertEqual(
            report.action_ledger_summary.entries[0]["pre_uncertainty_status"],
            LedgerStatus.DISPATCHED.value,
        )

    def test_facility_binding_confidence_from_ledger(self):
        session, _frame = verified_session()
        bind = identity(ordinal=2, transport="3", semantic="4")
        record_plan(session, requested=(0.0, 0.0), reason="already_in_view")
        record_target_bound(session, frame=bind, binding=binding_result(bind, confidence=0.88))
        report = report_navigation_session(session)
        self.assertEqual(
            report.semantic_facility_binding_confidence.availability,
            FieldAvailability.PRESENT.value,
        )
        self.assertAlmostEqual(report.semantic_facility_binding_confidence.value["confidence"], 0.88)

    def test_malformed_session_never_normalizes_to_success(self):
        session = create_session(scope())
        session.checkpoint_history = ["created", "not_a_checkpoint"]
        session.event_ordinal = 1
        report = report_navigation_session(session)
        self.assertEqual(report.report_integrity, ReportIntegrity.MALFORMED.value)
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.MALFORMED.value)
        self.assertNotEqual(report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value)

    def test_contradictory_completed_history_is_not_success(self):
        from dataclasses import replace

        session = create_session(scope())
        # Force an inconsistent completed claim while bypassing normal APIs.
        session.outcome = SessionOutcome.COMPLETED
        session.terminal_reason = "forged_success"
        session.route_result = replace(session.route_result, status="completed", reason="forged_success")
        report = report_navigation_session(session)
        self.assertIn(
            report.report_integrity,
            {ReportIntegrity.MALFORMED.value, ReportIntegrity.CONTRADICTORY.value},
        )
        self.assertNotEqual(report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value)

    def test_direction_disagree_and_progress_ratio(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(
            session, frame, requested=(10.0, 0.0), predicted=(9.0, 0.0)
        )
        post = identity(ordinal=2, transport="3", semantic="4")
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(-5.0, 0.0),
            residual=(15.0, 0.0),
            progress_px=5.0,
            accepted=True,
            reason="measured_progress",
            localization_confidence=0.9,
        )
        report = report_navigation_session(session)
        self.assertEqual(report.direction_agreement.value, DirectionAgreement.DISAGREE.value)
        self.assertAlmostEqual(report.progress_ratio.value, 0.5)

    def test_deterministic_json_serialization_and_revalidation(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(session, frame)
        post = identity(ordinal=2, transport="3", semantic="4", monotonic=1100.5)
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(7.0, 0.0),
            residual=(3.0, 0.0),
            progress_px=7.0,
            accepted=True,
            reason="measured_progress",
            localization_confidence=0.91,
        )
        report = report_navigation_session(session)
        text_a = serialize_navigation_observability_report(report)
        text_b = serialize_navigation_observability_report(report)
        self.assertEqual(text_a, text_b)
        payload = json.loads(text_a)
        self.assertEqual(list(payload.keys()), list(REPORT_FIELD_ORDER))
        self.assertEqual(payload["schema_name"], SCHEMA_NAME)
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        # No NaN/Infinity and JSON-safe.
        json.dumps(payload, allow_nan=False)
        snap = navigation_observability_snapshot(report)
        self.assertEqual(list(snap.keys()), list(REPORT_FIELD_ORDER))

    def test_public_nested_values_are_deeply_frozen(self):
        value = AvailabilityValue(
            FieldAvailability.PRESENT.value,
            {"outer": [1, {"inner": "value"}]},
        )
        self.assertIs(type(value.value), MappingProxyType)
        self.assertIs(type(value.value["outer"]), tuple)
        with self.assertRaises(TypeError):
            value.value["new"] = "forbidden"
        with self.assertRaises(TypeError):
            value.value["outer"][1]["inner"] = "forbidden"

        session, frame = verified_session()
        _prepare_and_dispatch(session, frame)
        report = report_navigation_session(session)
        self.assertIs(type(report.action_ledger_summary.entries[0]), MappingProxyType)
        with self.assertRaises(TypeError):
            report.action_ledger_summary.entries[0]["status"] = "forged"

    def test_forged_report_graph_is_rejected_before_serialization(self):
        session, _frame = verified_session()
        report = report_navigation_session(session)
        object.__setattr__(report.localization_confidence, "value", {"mutable": []})
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report)

        session2, frame2 = verified_session()
        _prepare_and_dispatch(session2, frame2)
        report2 = report_navigation_session(session2)
        object.__setattr__(report2.requested_atlas_displacement, "x", 1)
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report2)

        report3 = report_navigation_session(session2)
        object.__setattr__(report3.action_ledger_summary, "entries", ({},))
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report3)

    def test_field_availability_cannot_hide_retained_values(self):
        def fresh_report():
            session, _frame = verified_session()
            return report_navigation_session(session)

        report = fresh_report()
        object.__setattr__(report.non_dispatch_authority, "value", None)
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report)

        report = fresh_report()
        object.__setattr__(report.localization_confidence, "availability", "unknown")
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report)

        report = fresh_report()
        object.__setattr__(report.source_checkpoint, "availability", "unknown")
        with self.assertRaises(NavigationObservabilityError):
            serialize_navigation_observability_report(report)

        payload = json.loads(serialize_navigation_observability_report(fresh_report()))
        payload["non_dispatch_authority"]["value"] = None
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(payload))

        payload = json.loads(serialize_navigation_observability_report(fresh_report()))
        payload["localization_confidence"]["availability"] = "unknown"
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(payload))

        payload = json.loads(serialize_navigation_observability_report(fresh_report()))
        payload["source_checkpoint"]["availability"] = "unknown"
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(payload))

    def test_strict_snapshot_deserialization_rejects_forgery_and_lookalikes(self):
        session, _frame = verified_session()
        report = report_navigation_session(session)
        serialized = serialize_navigation_observability_report(report)
        restored = deserialize_navigation_observability_report(serialized)
        self.assertEqual(
            serialize_navigation_observability_report(restored),
            serialized,
        )

        payload = json.loads(serialized)
        mutations = (
            ("schema_version", True),
            ("navigation_session_id", 123),
            ("runtime_capture_session_id", False),
            ("report_integrity", "forged"),
        )
        for key, value in mutations:
            forged = copy.deepcopy(payload)
            forged[key] = value
            with self.assertRaises(NavigationObservabilityError):
                deserialize_navigation_observability_report(json.dumps(forged))

        forged = copy.deepcopy(payload)
        forged["localization_confidence"]["availability"] = "forged"
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(forged))

        forged = copy.deepcopy(payload)
        forged["requested_atlas_displacement"]["x"] = 1
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(forged))

        forged = copy.deepcopy(payload)
        forged["total_frame_count"]["value"] = True
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(forged))

        forged = copy.deepcopy(payload)
        forged["terminal_state"]["value"]["class"] = TerminalReportClass.SUCCESS.value
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(json.dumps(forged))

        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report(
                '{"schema_name":"x","schema_name":"y"}'
            )
        with self.assertRaises(NavigationObservabilityError):
            deserialize_navigation_observability_report('{"schema_version":NaN}')

    def test_malformed_identity_counts_and_enum_fields_remain_malformed(self):
        session, _frame = verified_session()
        before = copy.deepcopy(session.__dict__)
        object.__setattr__(session, "navigation_session_id", True)
        object.__setattr__(session, "route_id", 123)
        object.__setattr__(session, "runtime_capture_session_id", None)
        object.__setattr__(session, "event_ordinal", True)
        object.__setattr__(session, "pan_ordinal", 1.0)
        object.__setattr__(session, "maximum_pans", "4")
        object.__setattr__(session, "checkpoint", "created")
        object.__setattr__(session, "outcome", "completed")
        object.__setattr__(session.route_result, "status", False)
        object.__setattr__(session.route_result, "continuations", True)

        report = report_navigation_session(session)
        self.assertEqual(report.report_integrity, ReportIntegrity.MALFORMED.value)
        self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.MALFORMED.value)
        self.assertIsNone(report.navigation_session_id)
        self.assertIsNone(report.route_id)
        self.assertIsNone(report.runtime_capture_session_id)
        self.assertNotEqual(
            report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value
        )
        self.assertEqual(session.__dict__, session.__dict__)
        self.assertNotEqual(before, session.__dict__)
        # Reporting itself does not make a second mutation.
        after = copy.deepcopy(session.__dict__)
        report_navigation_session(session)
        self.assertEqual(session.__dict__, after)

    def test_nonfinite_frame_timing_is_explicitly_malformed(self):
        session, _frame = verified_session()
        frame = session.known_frame_identities[0]
        object.__setattr__(frame, "capture_completed_monotonic", math.nan)
        before = copy.deepcopy(session.__dict__)
        report = report_navigation_session(session)
        self.assertEqual(report.report_integrity, ReportIntegrity.MALFORMED.value)
        self.assertEqual(report.state_timing.availability, FieldAvailability.MALFORMED.value)
        self.assertEqual(session.__dict__, before)

    def test_no_numpy_retention_in_snapshot(self):
        session, _frame = verified_session()
        report = report_navigation_session(session)
        payload = navigation_observability_snapshot(report)
        blob = repr(payload)
        self.assertNotIn("numpy", blob.lower())
        self.assertNotIn("ndarray", blob.lower())

    def test_confirmed_not_dispatched_remains_unavailable(self):
        with self.assertRaises(NavigationSessionError) as ctx:
            TrustedTransportNonDispatchAuthority(authority_id="test")
        self.assertEqual(ctx.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        session, _frame, action_key, _fp = prepared_uncertain_session()
        mark_uncertain(session, reason="crash", suppress_action_keys=(action_key,))
        report = report_navigation_session(session)
        self.assertEqual(
            report.non_dispatch_authority.value["resolution"],
            UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED.value,
        )
        self.assertEqual(
            report.non_dispatch_authority.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE"
        )

    def test_state_timing_from_known_frames(self):
        session, frame = verified_session()
        action_key = _prepare_and_dispatch(session, frame)
        post = identity(ordinal=2, transport="3", semantic="4", monotonic=1500.0)
        reconcile_pan(
            session,
            action_key,
            post_frame=post,
            measured=(4.0, 0.0),
            residual=(6.0, 0.0),
            progress_px=4.0,
            accepted=True,
            reason="measured_progress",
            localization_confidence=0.9,
        )
        report = report_navigation_session(session)
        self.assertEqual(report.state_timing.availability, FieldAvailability.PRESENT.value)
        self.assertGreaterEqual(report.state_timing.value["span_seconds"], 0.0)
        self.assertEqual(report.state_timing.value["latest_capture_completed_monotonic"], 1500.0)

    def test_rejects_non_session_input(self):
        with self.assertRaises(NavigationObservabilityError) as ctx:
            report_navigation_session(object())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.reason_code, "INVALID_SESSION")

    def test_leg_complete_dry_path_still_incomplete_or_success_by_outcome(self):
        session, _frame = verified_session()
        bind = identity(ordinal=2, transport="3", semantic="4")
        record_plan(session, requested=(0.0, 0.0), reason="already_in_view")
        record_target_bound(session, frame=bind, binding=binding_result(bind))
        complete_route_at_target_bound(session)
        report = report_navigation_session(session)
        # Completed at target-bound is a terminal success class when outcome completed.
        if session.outcome is SessionOutcome.COMPLETED:
            self.assertEqual(report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value)
        else:
            self.assertNotEqual(
                report.terminal_state.value["class"], TerminalReportClass.SUCCESS.value
            )


if __name__ == "__main__":
    unittest.main()
