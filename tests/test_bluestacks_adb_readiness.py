from __future__ import annotations

from subprocess import CompletedProcess, TimeoutExpired
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import hashlib
import time
from unittest.mock import patch

from scripts.bluestacks_adb_readiness import (
    ADBReadinessError,
    ensure_adb_ready,
    reset_adb_readiness_cache,
)
from scripts import bluestacks_flow_collector as collector
from scripts import pnsctl
from automation_service.recruitment import recruitment_reset
from automation_service.registry import TROOP_TRAINING_FLOW_ID
from automation_service.troop_training import (
    make_training_start_action_key,
    training_identity_digest,
)
from safe_action_core.models import (
    ActionClass,
    ActionIntent,
    PolicyDecision,
    PolicyResult,
)
from safe_action_core.store import SafetyStore
from scripts import navigation_development_boundary as boundary
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import resource_fixed_runtime_binding
from tasks.runtime_identity import BLUESTACKS_SERIAL


class BlueStacksADBReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_adb_readiness_cache()

    def tearDown(self) -> None:
        reset_adb_readiness_cache()

    def test_default_start_timeout_probes_fixed_serial_unqualified(self) -> None:
        calls: list[list[str]] = []

        def run(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                self.assertEqual(kwargs["timeout"], 5.0)
                raise TimeoutExpired(command, kwargs["timeout"])
            return CompletedProcess([], 0, "device\n", "")

        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run)
        self.assertEqual(calls, [
            ["HD-Adb.exe", "start-server"],
            ["HD-Adb.exe", "-s", "emulator-5554", "get-state"],
        ])

    def test_server_starts_before_probe_and_success_is_cached(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                CompletedProcess([], 0, "server started", ""),
                CompletedProcess([], 0, "device\n", ""),
            )
        )

        def run(command, **kwargs):
            calls.append(command)
            return next(responses)

        cache: set[tuple[str, str]] = set()
        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run, cache=cache)
        ensure_adb_ready("HD-Adb.exe", "emulator-5554", run=run, cache=cache)
        self.assertEqual(calls, [
            ["HD-Adb.exe", "start-server"],
            ["HD-Adb.exe", "-s", "emulator-5554", "get-state"],
        ])
        self.assertNotIn("connect", calls[0])

    def test_transient_offline_then_device_retries_with_bounded_sleep(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                CompletedProcess([], 0, "", "server started"),
                CompletedProcess([], 1, "offline\n", "device offline"),
                CompletedProcess([], 0, "device\n", ""),
            )
        )
        run = lambda command, **kwargs: (calls.append(command) or next(responses))
        sleeps: list[float] = []
        ensure_adb_ready(
            "adb",
            "emulator-5554",
            run=run,
            sleep=sleeps.append,
            monotonic=iter((0.0, 0.0, 0.0, 0.01, 0.02)).__next__,
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.05])

    def test_timeout_has_compact_diagnostics_and_never_connects(self) -> None:
        calls: list[list[str]] = []
        responses = iter(
            (
                TimeoutExpired(["adb", "start-server"], 5.0),
                CompletedProcess([], 1, "offline\n", "offline"),
            )
        )
        def run(command, **kwargs):
            calls.append(command)
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        clock = iter((0.0, 0.0, 0.0, 1.0, 2.0, 3.0)).__next__
        with self.assertRaisesRegex(
            ADBReadinessError, r"ADB readiness timed out.*start-server timed out; offline"
        ):
            ensure_adb_ready(
                "adb",
                "emulator-5554",
                run=run,
                sleep=lambda _seconds: None,
                monotonic=clock,
                deadline_seconds=1.0,
            )
        self.assertTrue(calls)
        self.assertTrue(all("connect" not in command for command in calls))

    def test_parent_fixed_command_invokes_readiness_before_serial_command(self) -> None:
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "HD-Adb.exe"
            executable.write_bytes(b"stub")
            with patch.object(pnsctl, "BLUESTACKS_ADB", executable), patch.object(
                pnsctl, "ensure_adb_ready"
            ) as ready, patch.object(
                pnsctl.subprocess,
                "run",
                return_value=CompletedProcess([], 0, "device\n", ""),
            ) as run:
                pnsctl._run_fixed_bluestacks_adb("get-state")
            ready.assert_called_once_with(str(executable), BLUESTACKS_SERIAL)
            self.assertEqual(run.call_args.args[0][1:3], ["-s", BLUESTACKS_SERIAL])

    def test_child_runner_invokes_readiness_before_list_devices(self) -> None:
        runner = collector.ADBRunner("HD-Adb.exe", "emulator-5554")
        with patch.object(collector, "ensure_adb_ready") as ready, patch.object(
            collector.subprocess,
            "run",
            return_value=CompletedProcess(
                [], 0, b"List of devices attached\nemulator-5554\tdevice\n", b""
            ),
        ):
            devices = runner.list_devices()
        ready.assert_called_once_with("HD-Adb.exe", "emulator-5554")
        self.assertEqual([(device.serial, device.state) for device in devices], [("emulator-5554", "device")])

    def test_child_serial_selection_lists_devices_without_fake_serial_probe(self) -> None:
        runner = collector.ADBRunner("HD-Adb.exe", "__selection__")
        with patch.object(collector, "ensure_adb_ready") as ready, patch.object(
            collector.subprocess,
            "run",
            return_value=CompletedProcess(
                [], 0, b"List of devices attached\nemulator-5554\tdevice\n", b""
            ),
        ) as run:
            devices = runner.list_devices()
        ready.assert_called_once_with("HD-Adb.exe", None)
        self.assertEqual(run.call_args.args[0], ["HD-Adb.exe", "devices", "-l"])
        self.assertEqual(devices[0].serial, "emulator-5554")


class CanonicalTrainingRecoveryHistoryTests(unittest.TestCase):
    def test_history_candidate_comes_from_read_only_canonical_sqlite(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "actions.sqlite3"
            now = time.time()
            reset_id = recruitment_reset(now)
            binding = resource_fixed_runtime_binding()
            identity = training_identity_digest(
                binding.runtime_scope,
                binding.account_id,
                binding.server_id,
            )
            action_key = make_training_start_action_key(
                identity,
                reset_id,
                "fighter",
                1,
            )
            intent = ActionIntent(
                action_id="training-start",
                action_key=action_key,
                task_id=TROOP_TRAINING_FLOW_ID,
                semantic_action="TROOP_TRAINING_START",
                source_state="TRAINING",
                target_identity="training-start",
                target_roi=(100, 100, 200, 200),
                source_frame_sha256="a" * 64,
                source_frame_captured_at=time.monotonic(),
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
                game_day_id=reset_id,
                expected_postcondition="exact_active_training_queue",
                consequence="training_start",
                cost_type="none",
                cost_amount=0.0,
                quantity=1,
                evidence_refs=("synthetic:test-only",),
                consequential=True,
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            )
            store = SafetyStore(database)
            store.prepare_action(
                intent,
                PolicyResult(
                    PolicyDecision.AUTHORIZE,
                    "test-authorized",
                    "",
                    now,
                    {},
                ),
                now,
            )
            store.close()
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            with patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", database):
                history = pnsctl._troop_training_recovery_history()

            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
            self.assertIsNotNone(history)
            self.assertEqual(history["task_id"], TROOP_TRAINING_FLOW_ID)
            self.assertEqual(history["action_ids"], ["training-start"])
            self.assertEqual(history["action_keys"], [action_key])
            self.assertEqual(history["pending_statuses"], ["prepared"])
            self.assertEqual(
                history["source"],
                "canonical_sqlite_action_and_resource_history",
            )

    def test_recover_home_gates_released_training_on_canonical_history(self):
        queue = {"active_flow_id": TROOP_TRAINING_FLOW_ID}
        lease = {
            "active_flow": TROOP_TRAINING_FLOW_ID,
            "active_stage": "evidence_review",
            "runtime_ownership_state": "released",
            "unresolved_action_state": "unresolved",
        }
        history = {
            "action_ids": ["training-start"],
            "pending_statuses": ["unresolved"],
        }
        with (
            patch.object(
                pnsctl,
                "_load_flow_delivery_state",
                return_value=(queue, lease),
            ),
            patch.object(
                pnsctl,
                "_troop_training_recovery_history",
                return_value=history,
            ) as canonical_history,
            patch.object(
                pnsctl,
                "_run_troop_training_return_home",
                return_value='{"status":"navigation_complete"}',
            ) as native_recovery,
        ):
            result = pnsctl.bluestacks_recover_home()

        self.assertEqual(result, '{"status":"navigation_complete"}')
        canonical_history.assert_called_once()
        native_recovery.assert_called_once_with(
            queue,
            lease,
            history_required=True,
            runtime_input_lock=None,
            checkpoint=None,
        )

    def test_released_training_recovery_fails_closed_without_canonical_history(self):
        queue = {"active_flow_id": TROOP_TRAINING_FLOW_ID}
        lease = {
            "active_flow": TROOP_TRAINING_FLOW_ID,
            "active_stage": "evidence_review",
            "runtime_ownership_state": "released",
            "unresolved_action_state": "clear",
        }
        with (
            patch.object(
                pnsctl,
                "_load_flow_delivery_state",
                return_value=(queue, lease),
            ),
            patch.object(
                pnsctl,
                "_troop_training_recovery_history",
                return_value=None,
            ),
            patch.object(pnsctl, "_run_troop_training_return_home") as native_recovery,
            self.assertRaisesRegex(
                pnsctl.OperatorError,
                "canonical SQLite action/resource history",
            ),
        ):
            pnsctl.bluestacks_recover_home()
        native_recovery.assert_not_called()

if __name__ == "__main__":
    unittest.main()
