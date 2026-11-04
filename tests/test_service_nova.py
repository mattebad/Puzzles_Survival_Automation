"""Canonical cadence and executor fences with a device-forbidden Nova runner."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.nova import NovaRunner, nova_next_due
from automation_service.registry import NOVA_FLOW_ID
from automation_service.recruitment import recruitment_reset
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedNovaRunner


class ServiceNovaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "lock.sqlite3"))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.ADBRunner",
                                      side_effect=AssertionError("device access forbidden")))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
                                      side_effect=AssertionError("device access forbidden")))
        self.stop = VirtualStop(1_800_000_000.0)
        self.path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = GuardedNovaRunner(self.stop)
        self.service = AutomationService(mode="supervised", state=self.state, nova_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(NOVA_FLOW_ID, True)

    def serve(self, emit, *, state=None):
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, nova_runner=self.runner
        )
        service.serve(account_id="account", server_id="server", stop=self.stop,
                      emit=emit, clock=lambda: self.stop.now, flow_ids=(NOVA_FLOW_ID,))

    def once(self, **kwargs):
        reports = []
        self.serve(lambda report: (reports.append(report), self.stop.set()), **kwargs)
        return reports

    def test_cooldown_survives_restart_then_one_due_pulse_and_reset(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        due = self.state.get_flow(NOVA_FLOW_ID).next_due_at_utc
        self.assertEqual(due, self.stop.now + 300)
        row = self.state._db.execute("SELECT max_inputs,max_actions,consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (8, 1, 4, 1))
        self.assertEqual(self.runner.remaining, 1)
        self.stop.stopped = False
        self.stop.on_wait = self.stop.set
        with BotStateManager(self.path) as restarted:
            self.serve(lambda _report: self.fail("route ran before persisted due"), state=restarted)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 4)
        self.stop.stopped = False
        self.stop.on_wait = None
        self.stop.now = due
        self.once()
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.runner.remaining, 0)
        next_reset = (self.stop.now // 86400 + 1) * 86400
        self.assertEqual(self.state.get_flow(NOVA_FLOW_ID).next_due_at_utc, next_reset)
        self.stop.now = next_reset
        self.stop.stopped = False
        self.once()
        self.assertEqual(len(self.runner.calls), 3)
        self.assertEqual(self.runner.remaining, 1)
        self.assertEqual(self.runner.calls[-1][0].reset_id, recruitment_reset(next_reset))

    def test_operator_block_before_marker_install_is_preserved_without_input(self):
        original = self.state.block_flow
        def block(flow_id, reason, **kwargs):
            if reason.startswith("EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:"):
                original(flow_id, "OPERATOR_PAUSE")
            return original(flow_id, reason, **kwargs)
        with patch.object(self.state, "block_flow", side_effect=block):
            reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(self.state.get_flow(NOVA_FLOW_ID).blocked_reason, "OPERATOR_PAUSE")

    def test_operator_block_before_marker_clear_is_not_erased(self):
        original = self.state.unblock_flow
        def unblock(flow_id, **kwargs):
            self.state.block_flow(flow_id, "OPERATOR_PAUSE")
            return original(flow_id, **kwargs)
        with patch.object(self.state, "unblock_flow", side_effect=unblock):
            self.once()
        self.assertTrue(self.state.get_flow(NOVA_FLOW_ID).blocked)
        self.assertEqual(self.state.get_flow(NOVA_FLOW_ID).blocked_reason, "OPERATOR_PAUSE")

    def test_run_stop_request_stops_input_and_retains_terminal_consumption(self):
        def request_stop(_index):
            row = self.state._db.execute("SELECT run_id FROM runs ORDER BY claimed_at_utc DESC LIMIT 1").fetchone()
            run = self.state.get_run(row[0])
            self.state.transition_run(
                run.run_id, RunState.STOP_REQUESTED, expected_state=RunState.RUNNING,
                owner_instance_id=run.owner_instance_id, process_start_token=run.process_start_token,
                run_token=run.run_token, lease_generation=run.lease_generation,
                now_utc_epoch=self.stop.now,
            )
        self.runner.on_input = request_stop
        self.assertEqual(self.once()[0]["status"], "blocked")
        self.assertEqual(len(self.runner.inputs), 1)
        row = self.state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (1, 0))

    def test_native_exception_counts_are_accounted_before_blocking(self):
        from scripts.nova_praise_bluestacks import NovaNativePartialResultError

        def interrupted(identity, previous, checkpoint):
            checkpoint()
            raise NovaNativePartialResultError(
                "native stop after observed input",
                partial_result={"status": "unresolved", "terminal_home_verified": False,
                                "total_input_count": 1, "praise_transport_calls": 0},
            )
        self.service.nova_runner = interrupted
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(reports[0]["result"]["total_input_count"], 1)
        row = self.state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (1, 0))

    def test_native_partial_exception_crosses_runner_and_service_without_normalizing_success(self):
        from scripts.nova_praise_bluestacks import NovaNativePartialResultError

        observed_inputs = []
        self.service.nova_runner = NovaRunner(
            adb="FORBIDDEN", serial="emulator-5554", output_directory=self.root,
            utc_clock=lambda: self.stop.now, monotonic_clock=lambda: 100.0,
        )

        def native(args, identity):
            args.checkpoint()
            observed_inputs.append("one attempted Praise")
            raise NovaNativePartialResultError(
                "Praise transport attempted; successor capture interrupted",
                partial_result={
                    "status": "unresolved", "terminal_home_verified": False,
                    "total_input_count": 1, "praise_transport_calls": 1,
                    "effect_reconciliation_required": True,
                    "accounting_verified": True,
                },
            )

        with (
            patch("scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse", side_effect=native),
            patch("automation_service.nova.nova_next_due",
                  side_effect=AssertionError("partial failure must not normalize as success")),
        ):
            reports = self.once()
            self.assertEqual(reports[0]["status"], "blocked")
            self.assertEqual(reports[0]["result"]["praise_transport_calls"], 1)
            self.assertFalse(reports[0]["result"]["terminal_home_verified"])
            self.assertIsNone(self.state.get_flow(NOVA_FLOW_ID).next_due_at_utc)
            self.stop.stopped = False
            self.assertEqual(self.once()[0]["status"], "paused")
        self.assertEqual(observed_inputs, ["one attempted Praise"])
        row = self.state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (1, 1))

    def test_unverified_native_partial_lower_bound_is_not_recorded_as_exact(self):
        from scripts.nova_praise_bluestacks import NovaNativePartialResultError

        self.service.nova_runner = NovaRunner(
            adb="FORBIDDEN", serial="emulator-5554", output_directory=self.root,
            utc_clock=lambda: self.stop.now, monotonic_clock=lambda: 100.0,
        )
        observed_inputs = []

        def native(args, identity):
            args.checkpoint()
            observed_inputs.append("one attempted input")
            raise NovaNativePartialResultError(
                "dispatch accounting is incomplete",
                partial_result={
                    "status": "unresolved", "terminal_home_verified": False,
                    "total_input_count": 1, "praise_transport_calls": 1,
                    "runtime_input_count": 1, "accounting_lower_bound": 1,
                    "accounting_verified": False,
                    "accounting_error": "conflicting duplicate dispatch identity",
                    "effect_reconciliation_required": True,
                },
            )

        with patch("scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse", side_effect=native):
            reports = self.once()
            self.stop.stopped = False
            self.assertEqual(self.once()[0]["status"], "paused")
        self.assertEqual(reports[0]["status"], "blocked")
        partial = reports[0]["result"]
        self.assertEqual(partial["canonical_accounting"], "rejected")
        self.assertFalse(partial["accounting_verified"])
        self.assertEqual(partial["accounting_lower_bound"], 1)
        self.assertEqual(partial["runtime_input_count"], 1)
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(self.state.get_flow(NOVA_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(NOVA_FLOW_ID).next_due_at_utc)
        self.assertEqual(observed_inputs, ["one attempted input"])
        row = self.state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (0, 0))

    def test_lease_loss_retains_partial_counts_without_stale_writer_permission(self):
        def expire(_index):
            self.stop.now += 1000
        self.runner.on_input = expire
        reports = self.once()
        self.assertEqual(len(self.runner.inputs), 1)
        self.assertEqual(reports[0]["result"]["total_input_count"], 1)
        self.assertIn("accounting_rejected", self.state.get_flow(NOVA_FLOW_ID).blocked_reason)
        row = self.state._db.execute("SELECT consumed_inputs,consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (0, 0))


class NovaNormalizationTests(unittest.TestCase):
    def identity(self):
        return SchedulerIdentity("account", "server", "game-day-2027-01-15", NOVA_TASK_ID)

    def result(self):
        return {"status": "deferred", "terminal_home_verified": True,
                "time_basis": "utc", "completed_at_utc": 1_800_000_010.0,
                "account_id": "account", "server_id": "server", "reset_id": self.identity().reset_id,
                "praise_transport_calls": 0, "attempts_before": 2, "attempts_after": 2,
                "cooldown_seconds": 20, "next_eligible_at": 1_800_000_030.0}

    def test_observed_no_work_defers_without_claiming_a_praise(self):
        result = self.result()
        self.assertEqual(nova_next_due(result, self.identity(), 1_800_000_000), 1_800_000_030)
        result.update(status="complete_for_reset", attempts_before=0, attempts_after=0,
                      cooldown_seconds=None, next_eligible_at=None)
        self.assertEqual(nova_next_due(result, self.identity(), 1_800_000_000),
                         (1_800_000_010 // 86400 + 1) * 86400)

    def test_wrong_identity_missing_effect_and_bad_deadlines_are_rejected(self):
        for changes in ({"reset_id": "wrong"}, {"terminal_home_verified": False},
                        {"praise_transport_calls": 1}, {"praise_transport_calls": 2},
                        {"next_eligible_at": float("nan")}, {"cooldown_seconds": 301},
                        {"time_basis": "monotonic"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                nova_next_due(dict(self.result(), **changes), self.identity(), 1_800_000_000)

    def test_runner_preserves_native_utc_deadline_without_second_conversion(self):
        result = {"status": "completed", "transport_calls": 4, "time_basis": "utc",
                  "completed_at_utc": 1_800_000_000.0,
                  "next_eligible_at": 1_800_000_280.0,
                  "next_eligible_at_utc": 1_800_000_280.0}

        def forbid_adapter_clock_sampling():
            raise AssertionError("native UTC deadlines must not be converted again")

        runner = NovaRunner(adb="forbidden", serial="emulator-5554", output_directory=Path("unused"),
                            utc_clock=forbid_adapter_clock_sampling,
                            monotonic_clock=forbid_adapter_clock_sampling)
        checkpoints = []
        with patch("scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                   return_value=json.dumps(result)) as native:
            converted = runner(self.identity(), None, lambda: checkpoints.append(True))
        args, verified = native.call_args.args
        self.assertEqual(args.max_inputs, 8)
        self.assertEqual(verified.account_id, "account")
        self.assertEqual(converted["next_eligible_at"], 1_800_000_280.0)
        self.assertEqual(converted["next_eligible_at_utc"], result["next_eligible_at_utc"])
        self.assertEqual(converted["completed_at_utc"], result["completed_at_utc"])
        self.assertEqual(converted["total_input_count"], 4)
        self.assertEqual(converted["time_basis"], "utc")
        self.assertEqual(checkpoints, [True])
        self.assertIs(args.monotonic_clock, forbid_adapter_clock_sampling)

    def test_runner_rejects_missing_monotonic_or_nonfinite_native_clocks(self):
        from scripts.nova_praise_bluestacks import NovaNativePartialResultError

        valid = {"status": "completed", "transport_calls": 4, "praise_transport_calls": 1,
                 "time_basis": "utc", "completed_at_utc": 1_800_000_000.0,
                 "next_eligible_at": 1_800_000_280.0}
        candidates = [
            {key: value for key, value in valid.items() if key != "time_basis"},
            {key: value for key, value in valid.items() if key != "completed_at_utc"},
            {key: value for key, value in valid.items() if key != "next_eligible_at"},
            dict(valid, time_basis="monotonic"),
            dict(valid, completed_at_utc=float("nan")),
            dict(valid, completed_at_utc=float("inf")),
            dict(valid, next_eligible_at=float("nan")),
            dict(valid, next_eligible_at=float("inf")),
            dict(valid, next_eligible_at_utc=float("nan")),
            dict(valid, next_eligible_at_utc=1_800_000_281.0),
        ]
        runner = NovaRunner(adb="forbidden", serial="emulator-5554", output_directory=Path("unused"))
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with patch("scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                           return_value=json.dumps(candidate)):
                    with self.assertRaises(NovaNativePartialResultError) as caught:
                        runner(self.identity(), None, lambda: None)
                self.assertEqual(caught.exception.partial_result["total_input_count"], 4)
                self.assertEqual(caught.exception.partial_result["praise_transport_calls"], 1)
                self.assertEqual(caught.exception.partial_result["status"], "unresolved")
