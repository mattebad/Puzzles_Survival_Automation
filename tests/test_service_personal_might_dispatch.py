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
from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.registry import (
    CANONICAL_FLOW_REGISTRY, PERSONAL_MIGHT_FLOW_ID, canonical_flow_specs,
)
from automation_service.service import AutomationService, ServiceError
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tests.support.service_stop import VirtualStop


class GuardedPersonalMightRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs, self.backend_identities = [], [], []
        self.no_work = self.partial = False
        self.praise_calls = 0
        self.on_entry = self.on_input = None

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry(runtime_input_lock)
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(self.stop.now, timezone.utc),
        )
        self.backend_identities.append(asdict(backend))
        count = praise = 0
        error = None
        try:
            for index in range(5 if self.no_work else 6):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                count += 1
                if not self.no_work and index == 3:
                    praise = 1
                    self.praise_calls += 1
                if self.on_input:
                    self.on_input(index)
                if self.partial and praise:
                    raise RuntimeError("native gray successor lost after Praise")
        except Exception as exc:
            error = exc
        result = {
            "status": "unresolved" if error else "already_complete" if self.no_work else "complete_for_reset",
            "no_work": self.no_work, "flow_id": PERSONAL_MIGHT_FLOW_ID, "task_id": adapter.PRODUCT_ID,
            "runtime_profile_id": adapter.PROFILE_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "time_basis": "utc", "completed_at_utc": self.stop.now,
            "next_eligible_at": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "praise_transport_calls": praise,
            "committed_action_count": int(praise and error is None), "accounting_verified": True,
            "journal_status": "unresolved" if error else "confirmed",
            "action_id": "current-day-canonical-praise", "action_key": adapter._key(backend),
            "backend_identity": asdict(backend), "terminal_home_verified": error is None,
            "source_frame": {"frame_path": "source.png", "frame_sha256": "a" * 64},
            "praise_result_frame": {"frame_path": "current-gray.png", "frame_sha256": "b" * 64},
            "terminal_home_frame": {"frame_path": "current-home.png", "frame_sha256": "c" * 64},
            "effect_reconciliation_required": error is not None and praise > 0,
            "identical_retry_denied": error is not None,
        }
        if error:
            raise adapter.PersonalMightRunnerError(str(error), partial_result=result) from error
        return result


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

    def test_compiled_binding_is_disabled_and_cli_preserves_explicit_selection(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == PERSONAL_MIGHT_FLOW_ID)
        self.assertEqual((entry.product_id, entry.product_revision), (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION))
        self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.DAILY_ONCE_PER_RESET)
        self.assertTrue(entry.descriptor.reset_scoped)
        self.assertTrue(entry.spec.observation_only_completion)
        self.assertTrue(entry.build_handler().selection_only)
        self.assertTrue(all(not spec.default_enabled for spec in canonical_flow_specs()))
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        self.assertEqual(parser.parse_args(["serve", "--flow", "personal-might"]).flow, ["personal-might"])
        with self.assertRaises(ServiceError):
            self.service.serve(account_id="logical-account", server_id="logical-server",
                               stop=self.stop, emit=lambda _report: None)
        self.assertEqual(self.runner.calls, [])

    def test_one_praise_completes_reset_with_bounded_counts_and_borrowed_owner(self):
        def check_owner(owner):
            owner.assert_held(owner.owner, owner.invocation_id)
            run, = self.runs()
            self.assertEqual(run.state, RunState.RUNNING)
            self.assertTrue(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).blocked)
            with self.assertRaises(boundary.NavigationBoundaryError):
                with boundary.RuntimeInputLock(owner="contender", invocation_id="parallel"):
                    self.fail("a parallel runtime owner acquired the lock")

        self.runner.on_entry = check_owner
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
        with boundary.RuntimeInputLock(owner="next-owner", invocation_id="after-serve"):
            pass

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

    def test_restart_before_due_skips_runner_then_new_reset_runs_once(self):
        self.assertEqual(self.once()[0]["status"], "completed")
        due = self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).next_due_at_utc
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 6)
        self.stop.now, self.stop.stopped = due, False
        self.assertEqual(self.once()[0]["status"], "completed")
        first, second = self.runs()
        self.assertNotEqual(first.reset_id, second.reset_id)
        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
        self.assertEqual(second.state, RunState.SUCCEEDED)
        self.assertEqual((second.consumed_inputs, second.consumed_actions), (6, 1))
        self.assertEqual(self.runner.calls[1][1], first.reset_id)
        self.assertEqual(self.runner.praise_calls, 2)
        self.assertEqual(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).next_due_at_utc, due + 86400)
        self.stop.stopped = False
        self.assertEqual(self.once(), [])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.runner.praise_calls, 2)

    def test_partial_praise_retains_counts_blocks_restart_and_never_retries(self):
        self.runner.partial = True
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(reports[0]["result"]["committed_action_count"], 0)
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (4, 1))
        self.assertTrue(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 4)
        self.assertEqual(self.runner.praise_calls, 1)

    def test_generation_change_after_first_input_prevents_praise(self):
        def toggle(_index):
            self.state.set_flow_enabled(PERSONAL_MIGHT_FLOW_ID, False)
            self.state.set_flow_enabled(PERSONAL_MIGHT_FLOW_ID, True)

        self.runner.on_input = toggle
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 0))
        self.assertEqual(len(self.runner.inputs), 1)
        self.assertEqual(self.runner.praise_calls, 0)
        self.assertTrue(self.state.get_flow(PERSONAL_MIGHT_FLOW_ID).blocked)


if __name__ == "__main__":
    unittest.main()
