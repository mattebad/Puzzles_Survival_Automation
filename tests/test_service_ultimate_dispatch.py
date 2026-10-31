"""Ultimate daily dispatch, reset suppression and uncertain-result accounting offline."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.recruitment import recruitment_reset
from automation_service.registry import CANONICAL_FLOW_REGISTRY, ULTIMATE_FLOW_ID, canonical_flow_specs
from automation_service.service import AutomationService, ServiceError
from automation_service.state import BotStateManager, RunState
from automation_service.ultimate import PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID, UltimateRunnerError
from scripts import navigation_development_boundary as boundary
from tests.test_service_recruitment import VirtualStop


class GuardedUltimateRunner:
    def __init__(self, stop):
        self.stop = stop
        self.completed_reset = recruitment_reset(stop.now)
        self.pending = self.fail_after_flee = False
        self.calls, self.connections, self.inputs = [], [], []
        self.flee_calls = 0
        self.on_input = None

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        self.calls.append((identity, previous_reset))
        already = self.completed_reset == identity.reset_id
        count = attempts = flee = 0
        error = None
        try:
            if self.pending:
                raise RuntimeError("retained daily Flee awaits Home reconciliation")
            self.connections.append(identity.reset_id)
            if not already:
                for index in range(4):
                    checkpoint()
                    self.inputs.append((identity.reset_id, index))
                    count += 1
                    attempts = 1
                    if index == 3:
                        flee = 1
                        self.flee_calls += 1
                        if self.fail_after_flee:
                            self.pending = True
                            raise RuntimeError("Flee dispatched but terminal Home unknown")
                    if self.on_input:
                        self.on_input(index)
                self.completed_reset = identity.reset_id
        except Exception as exc:
            error = exc
        result = {
            "status": "unresolved" if error else "already_completed" if already else "complete_for_reset",
            "flow_id": ULTIMATE_FLOW_ID, "account_id": identity.account_id,
            "server_id": identity.server_id, "reset_id": identity.reset_id,
            "reset_identity": identity.reset_id, "task_id": PRODUCT_ID,
            "runtime_profile_id": PROFILE_ID, "time_basis": "utc",
            "completed_at_utc": self.stop.now,
            "next_eligible_at": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "ultimate_dispatch_count": attempts,
            "flee_transport_calls": flee, "committed_action_count": int(not error and not already),
            "accounting_verified": True, "terminal_home_verified": error is None,
            "reset_guard_completed": error is None, "effect_reconciliation_required": error is not None,
            "identical_retry_denied": error is not None,
            "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
        }
        if error:
            raise UltimateRunnerError(str(error), result) from error
        return result


class ServiceUltimateDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "runtime-lock.sqlite3",
        ))
        for target in ("ADBRunner", "LocalBlueStacksRuntime.connect"):
            self.stack.enter_context(patch(
                f"scripts.bluestacks_native_runtime.{target}",
                side_effect=AssertionError("device access forbidden"),
            ))
        self.stop = VirtualStop(1_800_000_000.0)
        self.path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = GuardedUltimateRunner(self.stop)
        self.service = AutomationService(mode="supervised", state=self.state, ultimate_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(ULTIMATE_FLOW_ID, True)

    def once(self, *, state=None):
        reports = []
        self.stop.on_wait = self.stop.set
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, ultimate_runner=self.runner,
        )
        service.serve(
            account_id="account", server_id="server", stop=self.stop,
            emit=lambda report: (reports.append(report), self.stop.set()),
            clock=lambda: self.stop.now, flow_ids=(ULTIMATE_FLOW_ID,),
        )
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid",
        )]

    def test_compiled_daily_binding_is_disabled_and_cli_preserves_explicit_selection(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == ULTIMATE_FLOW_ID)
        self.assertEqual((entry.product_id, entry.product_revision), (PRODUCT_ID, PRODUCT_REVISION))
        self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.DAILY_ONCE_PER_RESET)
        self.assertTrue(entry.descriptor.reset_scoped)
        self.assertTrue(entry.spec.observation_only_completion)
        self.assertTrue(entry.build_handler().selection_only)
        self.assertTrue(all(not spec.default_enabled for spec in canonical_flow_specs()))
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        self.assertEqual(parser.parse_args(["serve", "--flow", "ultimate"]).flow, ["ultimate"])
        with self.assertRaises(ServiceError):
            self.service.serve(account_id="account", server_id="server", stop=self.stop, emit=lambda _report: None)
        self.assertEqual(self.runner.calls, [])

    def test_current_reset_already_complete_succeeds_with_zero_input_and_next_utc_reset(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "already_complete")
        self.assertEqual((run.max_inputs, run.max_actions), (16, 1))
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assertEqual(self.runner.calls[0][0].task_id, PRODUCT_ID)
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(self.runner.flee_calls, 0)
        due = (self.stop.now // 86400 + 1) * 86400
        self.assertEqual(self.state.get_flow(ULTIMATE_FLOW_ID).next_due_at_utc, due)
        self.assertEqual(reports[0]["next_due_at_utc"], due)
        self.assertFalse(self.state.get_flow(ULTIMATE_FLOW_ID).blocked)

    def test_restart_before_due_never_connects_and_new_reset_runs_one_flee(self):
        self.once()
        due = self.state.get_flow(ULTIMATE_FLOW_ID).next_due_at_utc
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.connections), 1)
        self.assertEqual(self.runner.inputs, [])
        self.stop.now, self.stop.stopped = due, False
        self.assertEqual(self.once()[0]["status"], "completed")
        first, second = self.runs()
        self.assertNotEqual(first.reset_id, second.reset_id)
        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
        self.assertEqual(second.state, RunState.SUCCEEDED)
        self.assertEqual(second.terminal_outcome, "complete_for_reset")
        self.assertEqual((second.consumed_inputs, second.consumed_actions), (4, 1))
        self.assertEqual(self.runner.calls[1][1], first.reset_id)
        self.assertEqual(self.runner.flee_calls, 1)
        self.assertEqual(self.state.get_flow(ULTIMATE_FLOW_ID).next_due_at_utc, due + 86400)
        self.stop.stopped = False
        self.assertEqual(self.once(), [])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(len(self.runner.connections), 2)
        self.assertEqual(self.runner.flee_calls, 1)

    def test_retained_pending_home_blocks_fresh_service_without_input_or_retry(self):
        self.runner.pending = True
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assertTrue(self.state.get_flow(ULTIMATE_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(ULTIMATE_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.connections, [])
        self.assertEqual(self.runner.inputs, [])

    def test_uncertain_flee_retains_actual_dispatch_and_blocks_restart(self):
        self.runner.completed_reset = None
        self.runner.fail_after_flee = True
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(reports[0]["result"]["committed_action_count"], 0)
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (4, 1))
        self.assertTrue(self.state.get_flow(ULTIMATE_FLOW_ID).blocked)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.flee_calls, 1)
        self.assertEqual(len(self.runner.inputs), 4)

    def test_generation_change_after_one_input_stops_later_flee(self):
        self.runner.completed_reset = None

        def toggle(_index):
            self.state.set_flow_enabled(ULTIMATE_FLOW_ID, False)
            self.state.set_flow_enabled(ULTIMATE_FLOW_ID, True)

        self.runner.on_input = toggle
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 1))
        self.assertEqual(len(self.runner.inputs), 1)
        self.assertEqual(self.runner.flee_calls, 0)


if __name__ == "__main__":
    unittest.main()
