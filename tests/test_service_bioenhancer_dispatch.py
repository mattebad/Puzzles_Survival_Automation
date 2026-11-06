"""Canonical Bioenhancer dispatch, persistent cadence and borrowed ownership offline."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.bioenhancer import PRODUCT_ID
from automation_service.registry import BIOENHANCER_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedBioenhancerRunner


class ServiceBioenhancerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "runtime-lock.sqlite3"))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("device forbidden")))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect", side_effect=AssertionError("device forbidden")))
        self.stop = VirtualStop(1_800_000_000.0)
        self.path = self.root / "state.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = GuardedBioenhancerRunner(self.stop, self.root)
        self.service = AutomationService(mode="supervised", state=self.state, bioenhancer_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(BIOENHANCER_FLOW_ID, True)

    def serve(self, emit, *, state=None):
        service = self.service if state is None else AutomationService(mode="supervised", state=state, bioenhancer_runner=self.runner)
        service.serve(account_id="account", server_id="server", stop=self.stop, emit=emit,
                      clock=lambda: self.stop.now, flow_ids=(BIOENHANCER_FLOW_ID,))

    def once(self, **kwargs):
        reports = []
        self.serve(lambda report: (reports.append(report), self.stop.set()), **kwargs)
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute("SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid")]

    def test_no_work_persists_deferred_run_then_restart_waits_and_due_runs_once(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        first, = self.runs()
        self.assertEqual(first.state, RunState.DEFERRED)
        self.assertEqual((first.max_inputs, first.max_actions, first.consumed_inputs, first.consumed_actions), (8, 1, 5, 0))
        self.assertEqual(self.runner.calls[0][0].task_id, PRODUCT_ID)
        due = self.state.get_flow(BIOENHANCER_FLOW_ID).next_due_at_utc
        self.assertEqual(due, self.stop.now + 3600)
        self.stop.stopped = False
        self.stop.on_wait = self.stop.set
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 5)
        self.stop.stopped, self.stop.on_wait, self.stop.now = False, None, due
        self.assertEqual(self.once()[0]["status"], "completed")
        first, second = self.runs()
        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
        self.assertEqual(len(self.runner.calls), 2)

if __name__ == "__main__":
    unittest.main()
