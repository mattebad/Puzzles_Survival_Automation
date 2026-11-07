from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from safe_action_core.store import SafetyStore

from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from scripts import base_route_native_runtime as native_runtime
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.navigation_development_boundary import NavigationBoundaryError, RuntimeInputLock
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_SERIAL
FIXED_NOW = 1_800_000_000.0


def _assert_store_lease_released(store_path: Path) -> None:
    store = SafetyStore(store_path)
    try:
        store.acquire_lease("post-run-verifier", FIXED_NOW, 3600.0)
        store.release_lease("post-run-verifier", FIXED_NOW)
    finally:
        store.close()
def _assert_borrowed_runtime_lock(test_case: unittest.TestCase, lock: RuntimeInputLock) -> None:
    test_case.assertTrue(lock.held)
    competing = RuntimeInputLock(owner="another-controller", invocation_id="competitor")
    try:
        with test_case.assertRaises(NavigationBoundaryError):
            competing.acquire()
    finally:
        if competing.held:
            competing.release()



class _Runtime:
    def __init__(self, output_directory: Path) -> None:
        self.session = output_directory / "native-runtime"
        self.session.mkdir(parents=True, exist_ok=True)
        self.events = self.session / "events.jsonl"
        self.input_count = 0
        self.max_inputs = 40
        self.checkpoint = None
        self._capture_ordinal = 0

    @classmethod
    def connect(cls, *, adb, serial, output_directory, workflow, execute):
        if execute is not True:
            raise AssertionError("native boundary must explicitly own live runtime")
        return cls(output_directory)

    def capture(self, label: str) -> CapturedNativeFrame:
        if self.checkpoint is not None:
            self.checkpoint()
        self._capture_ordinal += 1
        path = self.session / f"{self._capture_ordinal:04d}-{label}.png"
        payload = b"offline-native-frame"
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        return CapturedNativeFrame(
            frame=frame,
            png=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            captured_monotonic=float(self._capture_ordinal),
            path=path,
        )

    def measure_device_state(self) -> str:
        return "device"

    def measure_foreground_package(self) -> str:
        return "com.global.ztmslg"


class NativeExecutionContractTests(unittest.TestCase):

    def test_request_preserves_service_occurrence_and_rejects_unbounded_inputs(self) -> None:
        route_arguments = {"selector": "fixed-route"}
        request = NativeRouteRequest(
            flow_id="daily_rewards",
            product_id="daily_rewards",
            product_revision="daily_rewards-v1",
            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            identity=object(),
            previous_reset_id=None,
            occurrence_key="service-occurrence-17",
            checkpoint=lambda: None,
            validate_identity=lambda: None,
            runtime_input_lock=object(),
            adb=str(BLUESTACKS_ADB),
            serial=BLUESTACKS_SERIAL,
            output_directory=Path("sessions"),
            max_inputs=16,
            max_actions=12,
            settle_seconds=0.0,
            arguments=route_arguments,
        )
        self.assertEqual(request.occurrence_key, "service-occurrence-17")
        route_arguments["selector"] = "mutated-after-request"
        self.assertEqual(request.arguments["selector"], "fixed-route")
        with self.assertRaises(TypeError):
            request.arguments["selector"] = "caller-mutation"
        with self.assertRaisesRegex(ValueError, "max_inputs"):
            NativeRouteRequest(
                flow_id="daily_rewards",
                product_id="daily_rewards",
                product_revision="daily_rewards-v1",
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                identity=object(),
                previous_reset_id=None,
                occurrence_key="service-occurrence-17",
                checkpoint=lambda: None,
                validate_identity=lambda: None,
                runtime_input_lock=object(),
                adb=str(BLUESTACKS_ADB),
                serial=BLUESTACKS_SERIAL,
                output_directory=Path("sessions"),
                max_inputs=True,
                max_actions=12,
                settle_seconds=0.0,
            )

    def test_outcome_never_accepts_stale_result_after_error_or_bad_accounting(self) -> None:
        failed = NativeRouteOutcome(
            flow_id="daily_rewards",
            native_result={},
            partial_result={"status": "completed"},
            failure="native driver failed after partial work",
            invocation_id="run-1",
            session_directory="session-1",
            startup_recovery=None,
            input_count=1,
            session_input_count=1,
            runtime_input_count=1,
            accounting_verified=True,
        )
        self.assertFalse(failed.execution_verified)
        unaccounted = NativeRouteOutcome(
            flow_id="daily_rewards",
            native_result={"status": "completed"},
            partial_result=None,
            failure=None,
            invocation_id="run-2",
            session_directory="session-2",
            startup_recovery=None,
            input_count=1,
            session_input_count=0,
            runtime_input_count=1,
            accounting_verified=False,
        )
        self.assertFalse(unaccounted.execution_verified)

    def test_fixed_binding_owns_session_store_and_verifies_accounting(self) -> None:
        captured = {}
        opened_stores = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action_store_path = root / "actions.sqlite3"
            output = root / "sessions"
            output.mkdir()

            def store_factory(path):
                captured["requested_store_path"] = path
                store = SafetyStore(action_store_path)
                opened_stores.append(store)
                return store

            def driver(context, arguments):
                captured["context"] = context
                captured["arguments"] = arguments
                context.bind_initial_observation()
                return {"status": "observed", "occurrence_key": context.occurrence_key}

            with patch("scripts.navigation_development_boundary.RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                lock = RuntimeInputLock(owner="automation-service", invocation_id="outer-run").acquire()
                try:
                    with patch.object(native_runtime.LocalBlueStacksRuntime, "connect", _Runtime.connect), \
                         patch.object(native_runtime, "open_canonical_action_store", side_effect=AssertionError("bound store factory must be used")):
                        binding = native_runtime.make_native_route_binding(
                            flow_id="daily_rewards",
                            product_id="daily_rewards",
                            product_revision="daily_rewards-v1",
                            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                            owner="automation-service:daily-rewards",
                            workflow="daily-rewards-native",
                            max_inputs=16,
                            max_actions=12,
                            driver=driver,
                            action_store_factory=store_factory,
                        )
                        request = NativeRouteRequest(
                            flow_id="daily_rewards",
                            product_id="daily_rewards",
                            product_revision="daily_rewards-v1",
                            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                            identity=object(),
                            previous_reset_id=None,
                            occurrence_key="actual-service-occurrence",
                            checkpoint=lambda: None,
                            validate_identity=lambda: None,
                            runtime_input_lock=lock,
                            adb=str(BLUESTACKS_ADB),
                            serial=BLUESTACKS_SERIAL,
                            output_directory=output,
                            max_inputs=16,
                            max_actions=12,
                            settle_seconds=0.0,
                            arguments={"fixed": "route-owned"},
                            utc_clock=lambda: FIXED_NOW,
                        )
                        outcome = binding.run(request)
                    _assert_borrowed_runtime_lock(self, lock)
                finally:
                    lock.release()

            self.assertTrue(outcome.execution_verified, outcome.failure)
            self.assertEqual(outcome.native_result["occurrence_key"], "actual-service-occurrence")
            self.assertEqual(outcome.input_count, 0)
            self.assertIs(captured["context"].action_store, opened_stores[0])
            self.assertEqual(captured["context"].runtime_input_lock.owner, "automation-service")
            self.assertEqual(captured["arguments"]["fixed"], "route-owned")
            self.assertEqual(
                captured["requested_store_path"],
                native_runtime.CANONICAL_ACTION_STORE_PATH,
            )
            self.assertEqual(len(opened_stores), 1)
            _assert_store_lease_released(action_store_path)

    def test_driver_failure_preserves_partial_result_and_consumed_inputs(self) -> None:
        captured = {}
        opened_stores = []

        def driver(context, arguments):
            captured["session_directory"] = context.session.session_directory
            context.runtime.input_count = 1
            context.session.adopt_retained_transport_count(1, source="events.jsonl")
            error = RuntimeError("native result became unknown")
            error.partial_result = {"status": "completed", "effect_reconciliation_required": True}
            raise error

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action_store_path = root / "actions.sqlite3"
            output = root / "sessions"
            output.mkdir()

            def store_factory(path):
                store = SafetyStore(action_store_path)
                opened_stores.append(store)
                return store

            with patch("scripts.navigation_development_boundary.RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                lock = RuntimeInputLock(owner="automation-service", invocation_id="outer-run").acquire()
                try:
                    with patch.object(native_runtime.LocalBlueStacksRuntime, "connect", _Runtime.connect):
                        binding = native_runtime.make_native_route_binding(
                            flow_id="daily_rewards",
                            product_id="daily_rewards",
                            product_revision="daily_rewards-v1",
                            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                            owner="automation-service:daily-rewards",
                            workflow="daily-rewards-native",
                            max_inputs=16,
                            max_actions=12,
                            driver=driver,
                            action_store_factory=store_factory,
                        )
                        outcome = binding.run(NativeRouteRequest(
                            flow_id="daily_rewards",
                            product_id="daily_rewards",
                            product_revision="daily_rewards-v1",
                            runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                            identity=object(),
                            previous_reset_id=None,
                            occurrence_key="service-occurrence-reused-on-retry",
                            checkpoint=lambda: None,
                            validate_identity=lambda: None,
                            runtime_input_lock=lock,
                            adb=str(BLUESTACKS_ADB),
                            serial=BLUESTACKS_SERIAL,
                            output_directory=output,
                            max_inputs=16,
                            max_actions=12,
                            settle_seconds=0.0,
                            utc_clock=lambda: FIXED_NOW,
                        ))
                    _assert_borrowed_runtime_lock(self, lock)
                finally:
                    lock.release()

            self.assertFalse(outcome.execution_verified)
            self.assertEqual(outcome.native_result, {})
            self.assertEqual(outcome.partial_result["status"], "completed")
            self.assertTrue(outcome.accounting_verified)
            self.assertEqual((outcome.input_count, outcome.session_input_count), (1, 1))
            self.assertEqual(outcome.runtime_input_count, 1)
            summary = json.loads(
                (captured["session_directory"] / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["input_count"], 1)
            self.assertEqual(summary["runtime_ownership"], "borrowed")
            self.assertTrue(summary["borrowed_owner_retained"])
            self.assertEqual(len(opened_stores), 1)
            _assert_store_lease_released(action_store_path)


if __name__ == "__main__":
    unittest.main()
