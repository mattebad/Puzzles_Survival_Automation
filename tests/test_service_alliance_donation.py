from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity

from automation_service.alliance_donation import (
    AllianceDonationRunner,
    MAX_ACTIONS,
    MAX_INPUTS,
    alliance_donation_next_due,
)
from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID,
    ALLIANCE_DONATION_PRODUCT_ID,
    ALLIANCE_DONATION_PRODUCT_REVISION,
    ALLIANCE_DONATION_PROFILE_ID,
)
from automation_service.recruitment import recruitment_reset


class FakeRuntimeInputLock:
    owner = "automation-service"
    invocation_id = "service-invocation-1"
    held = True

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("runtime lock identity changed")


class FakeNativeBoundary:
    def __init__(self, native_result):
        self.native_result = native_result
        self.request = None

    def run(self, request: NativeRouteRequest):
        self.request = request
        return NativeRouteOutcome(
            flow_id=ALLIANCE_DONATION_FLOW_ID,
            native_result=self.native_result,
            partial_result=None,
            failure=None,
            invocation_id="service-invocation-1",
            session_directory="/synthetic/alliance-donation",
            startup_recovery=None,
            input_count=3,
            session_input_count=3,
            runtime_input_count=3,
            accounting_verified=True,
        )


class AllianceDonationServiceAdapterTests(unittest.TestCase):
    def _identity(self, now: float = 1_700_000_000.0):
        binding = resource_fixed_runtime_binding()
        backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
        identity = SchedulerIdentity(
            account_id=backend.account_id,
            server_id=backend.server_id,
            reset_id=recruitment_reset(now),
            task_id=ALLIANCE_DONATION_PRODUCT_ID,
        )
        return binding, backend, identity, now

    @staticmethod
    def _successful_result(**overrides):
        result = {
            "status": "complete_for_reset",
            "reason": "ten_confirmed_ordinary_donations_reached",
            "donation_transport_calls": 10,
            "committed_action_count": 10,
            "daily_committed_action_count": 10,
            "terminal_home_verified": True,
            "terminal_status": "completed",
            "terminal_frame_sha256": "a" * 64,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "evidence_refs": ("native-frame://frames/terminal.png",),
        }
        result.update(overrides)
        return result

    def _execute(self, native_result, *, now=1_700_000_000.0):
        binding, backend, identity, now = self._identity(now)
        native = FakeNativeBoundary(native_result)
        with tempfile.TemporaryDirectory() as directory:
            runner = AllianceDonationRunner(
                serial=binding.serial, output_directory=Path(directory),
                native=native, utc_clock=lambda: now, monotonic_clock=lambda: 50.0,
            )
            result = runner(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-occurrence/value:do-not-parse",
            )
        return result, native, identity, backend, now

    def test_runner_returns_mapping_with_unlossy_native_accounting_and_reset_due(self):
        result, native, identity, backend, now = self._execute(self._successful_result())
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["committed_action_count"], 10)
        self.assertEqual(result["daily_committed_action_count"], 10)
        self.assertEqual(result["donation_transport_calls"], 10)
        self.assertEqual(result["backend_identity"]["account_id"], backend.account_id)
        self.assertTrue(result["accounting_verified"])
        expected_reset = datetime.fromtimestamp(now, timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp() + 86400
        self.assertEqual(alliance_donation_next_due(result, identity, now), expected_reset)
        request = native.request
        self.assertIsInstance(request, NativeRouteRequest)
        self.assertIs(request.identity, identity)
        self.assertEqual(request.occurrence_key, "opaque-occurrence/value:do-not-parse")
        self.assertEqual(request.flow_id, ALLIANCE_DONATION_FLOW_ID)
        self.assertEqual(request.product_id, ALLIANCE_DONATION_PRODUCT_ID)
        self.assertEqual(request.product_revision, ALLIANCE_DONATION_PRODUCT_REVISION)
        self.assertEqual(request.runtime_profile_id, ALLIANCE_DONATION_PROFILE_ID)
        self.assertEqual((request.max_inputs, request.max_actions), (MAX_INPUTS, MAX_ACTIONS))
        self.assertEqual(request.runtime_input_lock.owner, FakeRuntimeInputLock.owner)
        request.validate_identity()

    def test_partial_quota_restarts_from_durable_count_and_observed_timer(self):
        now = 1_700_000_000.0
        _binding, _backend, identity, now = self._identity(now)
        result, _native, identity, _backend, now = self._execute(
            self._successful_result(
                status="deferred", reason="no_attempts", donation_transport_calls=3,
                committed_action_count=3, daily_committed_action_count=5,
                next_eligible_at=now + 120,
                availability_evidence={
                    "reason": "no_attempts", "observed_at_utc": now,
                    "source_frame_sha256": "b" * 64, "evidence_ref": "evidence/donation-source",
                    "tech_identity": "current automatic HOT tech", "game_day_id": identity.reset_id,
                    "available_attempts": 0, "attempt_capacity": 20,
                    "cost_affordable": True,
                    "donation_amount": 1000, "next_attempt_available_in_seconds": 120,
                    "next_eligibility_source": "observed_attempt_timer",
                },
            ), now=now,
        )
        self.assertEqual(result["committed_action_count"], 3)
        self.assertEqual(result["daily_committed_action_count"], 5)
        self.assertEqual(alliance_donation_next_due(result, identity, now), now + 120)

    def test_deferred_donation_without_native_eligibility_is_rejected(self):
        now = 1_700_000_000.0
        _binding, _backend, identity, now = self._identity(now)
        result, _native, identity, _backend, now = self._execute(
            self._successful_result(
                status="deferred", reason="insufficient_resource", donation_transport_calls=2,
                committed_action_count=2, daily_committed_action_count=4,
                availability_evidence={
                    "reason": "insufficient_resource", "observed_at_utc": now,
                    "source_frame_sha256": "c" * 64, "evidence_ref": "evidence/donation-source",
                    "tech_identity": "current automatic HOT tech", "game_day_id": identity.reset_id,
                    "available_attempts": 18, "attempt_capacity": 20,
                    "cost_affordable": False,
                    "donation_amount": 1000, "next_eligibility_source": "safe_resource_recheck",
                },
            ), now=now,
        )
        with self.assertRaises(ValueError):
            alliance_donation_next_due(result, identity, now)


    def test_observed_red_cost_defers_without_wallet_until_bounded_recheck(self):
        now = 1_700_000_000.0
        _binding, _backend, identity, now = self._identity(now)
        evidence = {
            "reason": "insufficient_resource", "observed_at_utc": now,
            "source_frame_sha256": "c" * 64, "evidence_ref": "evidence/donation-source",
            "tech_identity": "2", "game_day_id": identity.reset_id,
            "available_attempts": 18, "attempt_capacity": 20,
            "cost_affordable": False, "donation_amount": 1000,
            "next_eligibility_source": "safe_resource_recheck",
        }
        result, _native, identity, _backend, now = self._execute(
            self._successful_result(
                status="deferred", reason="insufficient_resource", donation_transport_calls=2,
                committed_action_count=2, daily_committed_action_count=4,
                availability_evidence=evidence, next_eligible_at=now + 300,
            ), now=now,
        )
        self.assertEqual(alliance_donation_next_due(result, identity, now), now + 300)
        for affordable in (None, True):
            with self.subTest(affordable=affordable), self.assertRaises(ValueError):
                alliance_donation_next_due({**result, "availability_evidence": {
                    **evidence, "cost_affordable": affordable}}, identity, now)
    def test_unknown_dispatched_donation_preserves_effect_and_denies_retry(self):
        result, _native, identity, _backend, now = self._execute(self._successful_result(
            status="reconciliation_required", reason="unexpected_successor",
            donation_transport_calls=1, committed_action_count=0,
            daily_committed_action_count=0, terminal_home_verified=False,
            effect_reconciliation_required=True, identical_retry_denied=True,
        ))
        self.assertEqual(result["donation_transport_calls"], 1)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        with self.assertRaises(ValueError):
            alliance_donation_next_due(result, identity, now)
    def test_stale_scheduler_reset_is_blocked_before_native_boundary(self):
        binding, _backend, identity, now = self._identity()
        stale = SchedulerIdentity(identity.account_id, identity.server_id, "game-day-2023-11-13", identity.task_id)
        native = FakeNativeBoundary(self._successful_result())
        with tempfile.TemporaryDirectory() as directory:
            runner = AllianceDonationRunner(
                serial=binding.serial, output_directory=Path(directory),
                native=native, utc_clock=lambda: now,
            )
            result = runner(stale, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                            occurrence_key="opaque-stale")
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(native.request)

    def test_nonfixed_adb_is_blocked_before_native_boundary(self):
        binding, _backend, identity, now = self._identity()
        native = FakeNativeBoundary(self._successful_result())
        with tempfile.TemporaryDirectory() as directory:
            runner = AllianceDonationRunner(
                adb="synthetic-unapproved-adb", serial=binding.serial,
                output_directory=Path(directory), native=native, utc_clock=lambda: now,
            )
            result = runner(identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                            occurrence_key="opaque-nonfixed")
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(native.request)

    def test_missing_native_binding_fails_closed_with_mapping(self):
        _binding, _backend, identity, _now = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            runner = AllianceDonationRunner(output_directory=Path(directory), native=None)
            result = runner(identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                            occurrence_key="opaque-missing")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "ALLIANCE_DONATION_NATIVE_BINDING_REQUIRED")


if __name__ == "__main__":
    unittest.main()
