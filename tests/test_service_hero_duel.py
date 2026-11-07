from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tasks.runtime_identity import BLUESTACKS_ADB, derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity

from automation_service.hero_duel import (
    MAX_ACTIONS,
    MAX_INPUTS,
    FLOW_ID,
    PRODUCT_ID,
    PRODUCT_REVISION,
    PROFILE_ID,
    HeroDuelRunner,
    HeroDuelRunnerError,
    _backend_mapping,
    hero_duel_next_due,
)
from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from automation_service.recruitment import recruitment_reset


class FakeRuntimeInputLock:
    owner = "automation-service"
    invocation_id = "hero-duel-invocation-1"
    held = True


class FakeNativeBoundary:
    flow_id = FLOW_ID
    product_id = PRODUCT_ID
    product_revision = PRODUCT_REVISION
    runtime_profile_id = PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, result, *, input_count=20, failure=None, accounting=True, partial_result=None):
        self.request = None
        self.result = result
        self.input_count = input_count
        self.failure = failure
        self.accounting = accounting
        self.partial_result = partial_result

    def run(self, request: NativeRouteRequest):
        self.request = request
        return NativeRouteOutcome(
            flow_id=FLOW_ID,
            native_result=self.result,
            partial_result=self.partial_result,
            failure=self.failure,
            invocation_id="hero-duel-invocation-1",
            session_directory="/synthetic/hero-duel",
            startup_recovery=None,
            input_count=self.input_count,
            session_input_count=self.input_count,
            runtime_input_count=self.input_count,
            accounting_verified=self.accounting,
        )


def test_identity(now=1_700_000_000.0):
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
    identity = SchedulerIdentity(
        account_id=backend.account_id,
        server_id=backend.server_id,
        reset_id=recruitment_reset(now),
        task_id=PRODUCT_ID,
    )
    return binding, backend, identity, now


def cycle_proof(event_identity, reset_id, ordinal):
    before = 4 - ordinal
    return {
        "ordinal": ordinal,
        "reset_id": reset_id,
        "event_identity": event_identity,
        "entry_action_key": f"entry:{ordinal}",
        "flee_action_key": f"flee:{ordinal}",
        "free_before": before,
        "free_after": before - 1,
        "pass_before": 123,
        "pass_after": 123,
        "wave_text": "Wave 1/1",
        "battle_board_verified": True,
        "exit_confirmed": True,
        "flee_confirmed": True,
        "loss_result_seen": True,
        "tap_to_continue_confirmed": True,
    }


def native_complete_result(reset_id, *, status="complete_for_reset", **overrides):
    event_identity = f"survival_{reset_id}_ends_28333333"
    result = {
        "status": status,
        "reason": "three_canonical_free_loss_cycles_and_home_verified",
        "runtime_profile_id": PROFILE_ID,
        "reset_id": reset_id,
        "hero_duel_event_identity": event_identity,
        "current_event_active": True,
        "duel_dispatch_count": 3,
        "entry_transport_calls": 3,
        "flee_transport_calls": 3,
        "defense_save_transport_calls": 1,
        "defense_selection_transport_calls": 5,
        "committed_action_count": 3,
        "canonical_confirmed_cycle_ordinals": [1, 2, 3],
        "cycle_proofs": [cycle_proof(event_identity, reset_id, ordinal) for ordinal in (1, 2, 3)],
        "final_free_entries_remaining": 0,
        "final_pass_balance": 123,
        "total_input_count": 20,
        "terminal_home_verified": True,
        "terminal_home_frame": {"frame_path": "frames/hero-duel-home.png", "frame_sha256": "a" * 64},
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "accounting_verified": True,
        "availability_observed_at_utc": 1_700_000_000.0,
    }
    result.update(overrides)
    return result


def service_result(now, identity, backend, *, status="complete_for_reset", **overrides):
    event_identity = f"survival_{identity.reset_id}_ends_28333333"
    result = {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "task_id": PRODUCT_ID,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "runtime_profile_id": PROFILE_ID,
        "time_basis": "utc",
        "started_at_utc": now - 2,
        "completed_at_utc": now,
        "input_count": 20,
        "total_input_count": 20,
        "duel_dispatch_count": 3,
        "entry_transport_calls": 3,
        "flee_transport_calls": 3,
        "defense_save_transport_calls": 1,
        "defense_selection_transport_calls": 5,
        "committed_action_count": 3,
        "canonical_confirmed_cycle_ordinals": [1, 2, 3],
        "cycle_proofs": [cycle_proof(event_identity, identity.reset_id, ordinal) for ordinal in (1, 2, 3)],
        "final_free_entries_remaining": 0,
        "final_pass_balance": 123,
        "hero_duel_event_identity": event_identity,
        "current_event_active": True,
        "terminal_home_verified": True,
        "terminal_home_frame": {"frame_path": "frames/hero-duel-home.png", "frame_sha256": "b" * 64},
        "accounting_verified": True,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "backend_identity": _backend_mapping(backend),
        "status": status,
    }
    result.update(overrides)
    return result


class HeroDuelServiceAdapterTests(unittest.TestCase):

    def test_runner_rejects_unknown_or_unaccounted_native_route_results(self):
        binding, _backend, identity, now = test_identity()
        for bad_result in (
            native_complete_result(identity.reset_id, status="reconciliation_required",
                                   effect_reconciliation_required=True, identical_retry_denied=True),
            native_complete_result(identity.reset_id, terminal_home_verified=False),
            native_complete_result(identity.reset_id, final_free_entries_remaining=1),
        ):
            native = FakeNativeBoundary(bad_result)
            with tempfile.TemporaryDirectory() as directory:
                runner = HeroDuelRunner(native=native, output_directory=Path(directory), adb=str(BLUESTACKS_ADB),
                                        serial=binding.serial, utc_clock=lambda: now)
                with self.assertRaises(HeroDuelRunnerError):
                    runner(identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(), occurrence_key="occ:hero-duel:bad")
    def test_attempted_unknown_entry_stays_unresolved_and_uncommitted(self):
        binding, _backend, identity, now = test_identity()
        attempted = native_complete_result(
            identity.reset_id,
            status="reconciliation_required",
            duel_dispatch_count=1,
            entry_transport_calls=1,
            flee_transport_calls=0,
            committed_action_count=0,
            canonical_confirmed_cycle_ordinals=[],
            cycle_proofs=[],
            final_free_entries_remaining=2,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        native = FakeNativeBoundary(attempted)
        with tempfile.TemporaryDirectory() as directory:
            runner = HeroDuelRunner(
                native=native, output_directory=Path(directory), adb=str(BLUESTACKS_ADB),
                serial=binding.serial, utc_clock=lambda: now,
            )
            with self.assertRaises(HeroDuelRunnerError) as caught:
                runner(identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                    occurrence_key="opaque:attempt-1")
        partial = caught.exception.partial_result
        self.assertEqual(partial["status"], "unresolved")
        self.assertEqual(partial["entry_transport_calls"], 1)
        self.assertEqual(partial["committed_action_count"], 0)
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])
        failed = FakeNativeBoundary(
            attempted, failure="native-boundary-outcome-unknown", accounting=False,
            partial_result={
                "status": "blocked",
                "duel_dispatch_count": 0,
                "entry_transport_calls": 0,
                "flee_transport_calls": 0,
                "committed_action_count": 0,
                "cycle_proofs": [],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            runner = HeroDuelRunner(
                native=failed, output_directory=Path(directory), adb=str(BLUESTACKS_ADB),
                serial=binding.serial, utc_clock=lambda: now,
            )
            with self.assertRaises(HeroDuelRunnerError) as caught:
                runner(identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                    occurrence_key="opaque:attempt-1")
        partial = caught.exception.partial_result
        self.assertEqual(partial["status"], "unresolved")
        self.assertEqual(partial["entry_transport_calls"], 1)
        self.assertEqual(partial["committed_action_count"], 0)
        self.assertTrue(partial["identical_retry_denied"])


    def test_stale_scheduler_reset_is_blocked_before_native_dispatch(self):
        binding, _backend, identity, now = test_identity()
        stale = SchedulerIdentity(identity.account_id, identity.server_id, "game-day-2023-11-13", PRODUCT_ID)
        native = FakeNativeBoundary(native_complete_result(identity.reset_id))
        with tempfile.TemporaryDirectory() as directory:
            runner = HeroDuelRunner(native=native, output_directory=Path(directory), adb=str(BLUESTACKS_ADB),
                                    serial=binding.serial, utc_clock=lambda: now)
            with self.assertRaises(ValueError):
                runner(stale, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(), occurrence_key="occ:stale")
        self.assertIsNone(native.request)

    def test_current_reset_completion_uses_exact_backend_deadline(self):
        _binding, backend, identity, now = test_identity()
        result = service_result(now, identity, backend)
        due = hero_duel_next_due(result, identity, now - 2)
        expected = datetime.fromisoformat(backend.reset_deadline_utc.replace("Z", "+00:00")).timestamp()
        self.assertEqual(due, expected)
    def test_next_due_requires_committed_cycle_semantics(self):
        _binding, backend, identity, now = test_identity()
        valid = service_result(now, identity, backend)
        invalid = (
            {**valid, "committed_action_count": 2},
            {**valid, "cycle_proofs": valid["cycle_proofs"][:-1]},
            {**valid, "final_pass_balance": 122},
            {
                **valid,
                "cycle_proofs": [
                    *valid["cycle_proofs"][:2],
                    {**valid["cycle_proofs"][2], "flee_confirmed": False},
                ],
            },
        )
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(ValueError):
                hero_duel_next_due(result, identity, now - 2)


    def test_deferred_restart_needs_fresh_free_opportunity_and_exact_cycle_proof(self):
        _binding, backend, identity, now = test_identity()
        event_identity = f"survival_{identity.reset_id}_ends_28333333"
        deferred = service_result(
            now, identity, backend,
            status="deferred",
            duel_dispatch_count=0,
            entry_transport_calls=0,
            flee_transport_calls=1,
            defense_save_transport_calls=0,
            defense_selection_transport_calls=0,
            committed_action_count=1,
            canonical_confirmed_cycle_ordinals=[1],
            cycle_proofs=[cycle_proof(event_identity, identity.reset_id, 1)],
            final_free_entries_remaining=2,
            availability_observed_at_utc=now - 0.5,
            no_work=False,
        )
        self.assertEqual(hero_duel_next_due(deferred, identity, now - 2), now)
        for changes in (
            {"availability_observed_at_utc": now - 31},
            {"final_free_entries_remaining": 0},
            {"canonical_confirmed_cycle_ordinals": []},
            {"current_event_active": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                hero_duel_next_due({**deferred, **changes}, identity, now - 2)

    def test_unexplained_exhaustion_and_unknown_status_never_get_next_due(self):
        _binding, backend, identity, now = test_identity()
        exhausted = service_result(
            now, identity, backend,
            status="reconciliation_required",
            canonical_confirmed_cycle_ordinals=[1],
            final_free_entries_remaining=0,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        with self.assertRaises(ValueError):
            hero_duel_next_due(exhausted, identity, now - 2)
        with self.assertRaises(ValueError):
            hero_duel_next_due({**service_result(now, identity, backend), "status": "blocked"}, identity, now - 2)


if __name__ == "__main__":
    unittest.main()
