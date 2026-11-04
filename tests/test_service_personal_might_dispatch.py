"""Personal Might daily dispatch and identity fences without device access."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service import personal_might as adapter
from automation_service.registry import PERSONAL_MIGHT_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedPersonalMightRunner


class ServicePersonalMightDispatchTests(unittest.TestCase):
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
        self.runner = GuardedPersonalMightRunner(self.stop)
        self.service = AutomationService(mode="supervised", state=self.state, personal_might_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(PERSONAL_MIGHT_FLOW_ID, True)

    def once(self, *, state=None):
        reports = []
        self.stop.on_wait = self.stop.set
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, personal_might_runner=self.runner,
        )
        service.serve(
            account_id="logical-account", server_id="logical-server", stop=self.stop,
            emit=lambda report: (reports.append(report), self.stop.set()),
            clock=lambda: self.stop.now, flow_ids=(PERSONAL_MIGHT_FLOW_ID,),
        )
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid",
        )]

    def test_one_praise_completes_reset_with_bounded_counts_and_borrowed_owner(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "complete_for_reset")
        self.assertEqual((run.max_inputs, run.max_actions), (8, 1))
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (6, 1))
        self.assertEqual(self.runner.calls[0][0].task_id, adapter.PRODUCT_ID)
        self.assertEqual(self.runner.praise_calls, 1)
        due = (self.stop.now // 86400 + 1) * 86400
        self.assertEqual(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).next_due_at_utc, due)
        self.assertEqual(reports[0]["next_due_at_utc"], due)
        self.assertFalse(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).blocked)

    def test_confirmed_no_work_keeps_navigation_counts_and_fixed_backend_identity(self):
        self.runner.no_work = True
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.SUCCEEDED)
        self.assertEqual(run.terminal_outcome, "already_complete")
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (5, 0))
        self.assertEqual(self.runner.praise_calls, 0)
        result = reports[0]["result"]
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(self.stop.now, timezone.utc),
        )
        self.assertEqual(result["backend_identity"], asdict(backend))
        self.assertEqual(result["action_key"], adapter._key(backend))
        self.assertEqual(result["account_id"], "logical-account")
        self.assertEqual(result["server_id"], "logical-server")
        self.assertNotEqual(result["backend_identity"]["account_id"], result["account_id"])
        self.assertNotEqual(result["backend_identity"]["server_id"], result["server_id"])
        self.assertEqual(result["journal_status"], "confirmed")
        self.assertFalse(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).blocked)


if __name__ == "__main__":
    unittest.main()
