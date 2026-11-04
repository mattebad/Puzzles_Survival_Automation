"""Ultimate daily dispatch, reset suppression and uncertain-result accounting offline."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import ULTIMATE_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from automation_service.ultimate import PRODUCT_ID
from scripts import navigation_development_boundary as boundary
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedUltimateRunner


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

    def test_explicit_repeat_claim_runs_once_preserves_daily_due_and_rejects_request_reuse(self):
        self.once()
        before = self.state.get_flow(ULTIMATE_FLOW_ID)
        self.stop.stopped = False
        original = self.runner
        requests = []

        def repeat(identity, previous, checkpoint, *, operator_request_id):
            requests.append(operator_request_id)
            original.completed_reset = None
            return original(identity, previous, checkpoint)

        self.service.ultimate_runner = repeat
        reports = []
        for _ in range(2):
            self.service.serve(account_id="account", server_id="server", stop=self.stop,
                emit=reports.append, clock=lambda: self.stop.now, flow_ids=(ULTIMATE_FLOW_ID,),
                operator_request_id="user-extra-ultimate")
        after = self.state.get_flow(ULTIMATE_FLOW_ID)
        self.assertEqual(requests, ["user-extra-ultimate"])
        self.assertEqual([r["status"] for r in reports], ["completed", "refused"])
        self.assertEqual((after.next_due_at_utc, after.next_occurrence_key),
                         (before.next_due_at_utc, before.next_occurrence_key))
        self.assertEqual(original.flee_calls, 1)
        run = self.runs()[-1]
        self.assertEqual((run.mode, run.occurrence_basis, run.consumed_actions),
                         ("manual", "user-extra-ultimate", 1))

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

if __name__ == "__main__":
    unittest.main()
