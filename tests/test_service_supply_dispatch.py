"""Supply reset cadence and guarded service dispatch without device access."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import SUPPLY_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from automation_service.supply import PRODUCT_ID
from scripts import navigation_development_boundary as boundary
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedSupplyRunner


class ServiceSupplyDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "input-lock.sqlite3",
        ))
        for target in ("ADBRunner", "LocalBlueStacksRuntime.connect"):
            self.stack.enter_context(patch(
                f"scripts.bluestacks_native_runtime.{target}",
                side_effect=AssertionError("device access forbidden"),
            ))
        self.stop = VirtualStop(1_800_000_000.0)
        self.path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = GuardedSupplyRunner(self.stop)
        self.service = AutomationService(mode="supervised", state=self.state, supply_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(SUPPLY_FLOW_ID, True)

    def serve(self, emit, *, state=None):
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, supply_runner=self.runner,
        )
        service.serve(
            account_id="account", server_id="server", stop=self.stop,
            emit=emit, clock=lambda: self.stop.now, flow_ids=(SUPPLY_FLOW_ID,),
        )

    def once(self, *, state=None):
        reports = []
        self.stop.on_wait = self.stop.set
        self.serve(lambda report: (reports.append(report), self.stop.set()), state=state)
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid",
        )]

    def test_no_work_completes_reset_and_commits_deadline_with_succeeded_run(self):
        next_reset = (self.stop.now // 86400 + 1) * 86400
        original = self.state.project_terminal
        transitions = []

        def project(run_id, target, **kwargs):
            before = self.state.get_flow(SUPPLY_FLOW_ID).next_due_at_utc
            result = original(run_id, target, **kwargs)
            transitions.append((before, self.state.get_run(run_id).state,
                                self.state.get_flow(SUPPLY_FLOW_ID).next_due_at_utc))
            return result

        with patch.object(self.state, "project_terminal", side_effect=project):
            reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "already_complete")
        self.assertEqual((run.max_inputs, run.max_actions, run.consumed_inputs, run.consumed_actions), (10, 1, 4, 0))
        self.assertEqual(self.runner.calls[0][0].task_id, PRODUCT_ID)
        self.assertEqual(transitions, [(None, RunState.SUCCEEDED, next_reset)])
        self.assertEqual(reports[0]["next_due_at_utc"], next_reset)
        self.assertFalse(self.state.get_flow(SUPPLY_FLOW_ID).blocked)


if __name__ == "__main__":
    unittest.main()
