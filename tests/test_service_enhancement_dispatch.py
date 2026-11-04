"""Enhancement daily dispatch and canonical fences without device access."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.enhancement import PRODUCT_ID
from automation_service.registry import ENHANCEMENT_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedEnhancementRunner


class ServiceEnhancementDispatchTests(unittest.TestCase):
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
        self.runner = GuardedEnhancementRunner(self.stop, self.root)
        self.service = AutomationService(mode="supervised", state=self.state, enhancement_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(ENHANCEMENT_FLOW_ID, True)

    def once(self, *, state=None):
        reports = []
        self.stop.on_wait = self.stop.set
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, enhancement_runner=self.runner,
        )
        service.serve(
            account_id="account", server_id="server", stop=self.stop,
            emit=lambda report: (reports.append(report), self.stop.set()),
            clock=lambda: self.stop.now, flow_ids=(ENHANCEMENT_FLOW_ID,),
        )
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid",
        )]

    def test_three_uses_complete_reset_with_bounded_counts_and_borrowed_owner(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "complete_for_reset")
        self.assertEqual((run.max_inputs, run.max_actions), (24, 3))
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (6, 3))
        self.assertEqual(self.runner.calls[0][0].task_id, PRODUCT_ID)
        self.assertEqual(self.runner.use_calls, 3)
        due = (self.stop.now // 86400 + 1) * 86400
        self.assertEqual(self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc, due)
        self.assertEqual(reports[0]["next_due_at_utc"], due)
        self.assertFalse(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)

    def test_fresh_database_retained_family_and_current_home_complete_with_zero_input(self):
        self.runner.no_work = True
        self.assertEqual(self.runs(), [])
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "already_complete")
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(self.runner.use_calls, 0)
        self.assertEqual(self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc,
                         (self.stop.now // 86400 + 1) * 86400)
        self.assertFalse(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)

    def test_one_retained_category_completes_reset_with_only_two_new_uses(self):
        self.runner.retained_count = 1
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (4, 2))
        self.assertEqual(self.runner.use_calls, 2)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc,
                         (self.stop.now // 86400 + 1) * 86400)
        self.assertFalse(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)

if __name__ == "__main__":
    unittest.main()
