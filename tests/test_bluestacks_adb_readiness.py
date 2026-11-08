from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from subprocess import CompletedProcess, TimeoutExpired
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import hashlib
import json
import time
from unittest.mock import patch

from scripts.bluestacks_adb_readiness import (
    ADBReadinessError,
    ensure_adb_ready,
    reset_adb_readiness_cache,
)
from scripts import bluestacks_flow_collector as collector
from scripts import pnsctl
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.startup_recovery import StartupRecoveryPlan
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


def _prepare_consequential_action(
    database: Path,
    *,
    action_id: str,
    task_id: str,
    action_key: str | None = None,
) -> str:
    now = time.time()
    reset_id = recruitment_reset(now)
    if action_key is None:
        binding = resource_fixed_runtime_binding()
        identity = training_identity_digest(
            binding.runtime_scope,
            binding.account_id,
            binding.server_id,
        )
        action_key = make_training_start_action_key(identity, reset_id, "fighter", 1)
    intent = ActionIntent(
        action_id=action_id,
        action_key=action_key,
        task_id=task_id,
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
    try:
        store.prepare_action(
            intent,
            PolicyResult(PolicyDecision.AUTHORIZE, "test-authorized", "", now, {}),
            now,
        )
    finally:
        store.close()
    return action_key


class _FakeTrainingRuntime:
    def __init__(self, output_directory: Path) -> None:
        self.session = output_directory
        self.execute = True
        self.input_count = 0
        self.max_inputs = None
        self.checkpoint = None

    def capture(self, _label: str) -> SimpleNamespace:
        payload = b"training-recovery-source"
        return SimpleNamespace(png=payload, sha256=hashlib.sha256(payload).hexdigest())


class CanonicalTrainingRecoveryHistoryTests(unittest.TestCase):
    def _isolated(self, root: Path, database: Path) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", database))
        stack.enter_context(
            patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3")
        )
        stack.enter_context(patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"))
        stack.enter_context(patch.object(pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()))
        return stack

    def test_history_candidate_comes_from_read_only_canonical_sqlite(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "actions.sqlite3"
            action_key = _prepare_consequential_action(
                database,
                action_id="training-start",
                task_id=TROOP_TRAINING_FLOW_ID,
            )
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

    def test_recover_home_runs_from_canonical_history_without_legacy_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "actions.sqlite3"
            _prepare_consequential_action(
                database,
                action_id="training-start",
                task_id=TROOP_TRAINING_FLOW_ID,
            )
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            held_during_route: list[bool] = []

            def native_recovery(runtime, *, session, checkpoint, max_inputs):
                checkpoint()
                held_during_route.append(session.runtime_input_lock.held)
                self.assertEqual(max_inputs, pnsctl.TROOP_TRAINING_MAX_INPUTS)
                return {"status": "completed", "final_home_recognized": True}

            clear = StartupRecoveryPlan(
                status="clear",
                flow_id=TROOP_TRAINING_FLOW_ID,
                popup_identity=None,
                recovery_owner=None,
                input_authority=False,
                reason="clear",
            )
            with (
                self._isolated(root, database),
                patch.object(
                    LocalBlueStacksRuntime,
                    "connect",
                    side_effect=lambda **kwargs: _FakeTrainingRuntime(
                        kwargs["output_directory"]
                    ),
                ),
                patch("scripts.startup_recovery.classify_startup_frame", return_value=clear),
                patch(
                    "scripts.troop_training_bluestacks.run_troop_training_home_recovery",
                    side_effect=native_recovery,
                ),
            ):
                result = json.loads(pnsctl.bluestacks_recover_home())
                # The singleton lock was released and is immediately reacquirable.
                with boundary.RuntimeInputLock(owner="next-owner", invocation_id="next-1"):
                    pass

            self.assertEqual(held_during_route, [True])
            self.assertEqual(result["status"], "navigation_complete")
            self.assertEqual(result["recovery_mode"], "manual_navigation_only")
            self.assertEqual(result["canonical_training_history"]["action_ids"], ["training-start"])
            self.assertEqual(result["training_effect_status"], "unchanged_unresolved")
            self.assertFalse(result["training_action_resolved"])
            self.assertEqual(result["training_dispatch_count"], 0)
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_recover_home_fails_closed_without_canonical_history(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                self._isolated(root, root / "missing-actions.sqlite3"),
                patch.object(
                    boundary,
                    "DevelopmentSession",
                    side_effect=AssertionError("must not acquire runtime ownership"),
                ),
                patch.object(LocalBlueStacksRuntime, "connect") as connect,
                self.assertRaisesRegex(
                    pnsctl.OperatorError,
                    "canonical SQLite action/resource history",
                ),
            ):
                pnsctl.bluestacks_recover_home()
            connect.assert_not_called()

    def test_recover_home_blocks_unrelated_unknown_effect_before_runtime_ownership(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "actions.sqlite3"
            _prepare_consequential_action(
                database,
                action_id="training-start",
                task_id=TROOP_TRAINING_FLOW_ID,
            )
            _prepare_consequential_action(
                database,
                action_id="other-effect",
                task_id="OTHER-CONSEQUENTIAL-FLOW",
                action_key="other-consequential-flow:unknown-effect",
            )
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            with (
                self._isolated(root, database),
                patch.object(
                    boundary,
                    "DevelopmentSession",
                    side_effect=AssertionError("must not acquire runtime ownership"),
                ),
                patch.object(LocalBlueStacksRuntime, "connect") as connect,
                self.assertRaisesRegex(pnsctl.OperatorError, "unrelated unresolved effect"),
            ):
                pnsctl.bluestacks_recover_home()
            connect.assert_not_called()
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_recover_home_requires_the_singleton_runtime_input_lock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "actions.sqlite3"
            _prepare_consequential_action(
                database,
                action_id="training-start",
                task_id=TROOP_TRAINING_FLOW_ID,
            )
            stderr = io.StringIO()
            stdout = io.StringIO()
            with (
                self._isolated(root, database),
                patch.object(LocalBlueStacksRuntime, "connect") as connect,
                redirect_stderr(stderr),
                redirect_stdout(stdout),
            ):
                with boundary.RuntimeInputLock(
                    owner="automation-service",
                    invocation_id="service-pass",
                ):
                    code = pnsctl.main(["bluestacks", "recover-home"])
            connect.assert_not_called()
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            refusal = json.loads(stderr.getvalue())
            self.assertEqual(refusal["status"], "failed")
            self.assertEqual(refusal["command"], "bluestacks recover-home")
            self.assertIn("held by another owner", refusal["error"])

    def test_recover_home_rejects_history_changed_before_lock(self):
        admitted = {"action_ids": ["training-start"], "pending_statuses": ["prepared"]}
        changed = {"action_ids": ["training-start"], "pending_statuses": ["unresolved"]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                self._isolated(root, root / "actions.sqlite3"),
                patch.object(
                    pnsctl,
                    "_troop_training_recovery_history",
                    side_effect=[admitted, changed],
                ),
                patch.object(LocalBlueStacksRuntime, "connect") as connect,
            ):
                with self.assertRaisesRegex(pnsctl.OperatorError, "history changed"):
                    pnsctl.bluestacks_recover_home()
                with boundary.RuntimeInputLock(owner="next-owner", invocation_id="next-1"):
                    pass
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
