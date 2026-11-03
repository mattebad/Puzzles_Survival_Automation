"""Supply reset cadence and guarded service dispatch without device access."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.registry import (
    CANONICAL_FLOW_REGISTRY, REGISTRY_PATH, SUPPLY_FLOW_ID, RegisteredDispatchSnapshot,
    canonical_flow_specs,
)
from automation_service.service import AutomationService, ServiceError
from automation_service.state import BotStateManager, RunState
from automation_service.supply import PRODUCT_ID, PRODUCT_REVISION, SupplyNativePartialResultError
from scripts import navigation_development_boundary as boundary
from tests.support.service_stop import VirtualStop


class GuardedSupplyRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs = [], []
        self.consume, self.partial = False, False
        self.on_input = self.on_entry = None

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry(runtime_input_lock)
        count = holds = 0
        error = None
        try:
            for index in range(4):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                count += 1
                holds += int(self.consume and index == 2)
                if self.on_input:
                    self.on_input(index)
                if self.partial and holds:
                    raise RuntimeError("native successor lost after free hold")
        except Exception as exc:
            error = exc
        next_reset = (self.stop.now // 86400 + 1) * 86400
        result = {
            "status": "unresolved" if error else "completed",
            "flow_id": SUPPLY_FLOW_ID, "product_id": PRODUCT_ID,
            "product_revision": PRODUCT_REVISION, "task_id": PRODUCT_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "time_basis": "utc",
            "completed_at_utc": self.stop.now, "next_reset_at_utc": next_reset,
            "total_input_count": count, "hold_transport_calls": holds,
            "accounting_verified": True, "no_work": not self.consume,
            "free_attempts_before": 3 if self.consume else 0,
            "free_attempts_after": None if error else 0,
            "terminal_home_verified": error is None,
            "terminal_home_frame": {"frame_path": "current-home.png", "frame_sha256": "a" * 64},
            "effect_reconciliation_required": error is not None and holds > 0,
            "identical_retry_denied": error is not None,
        }
        if error:
            raise SupplyNativePartialResultError(str(error), partial_result=result) from error
        return result


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

    def test_compiled_defaults_and_legacy_controls_remain_disabled_with_explicit_cli_selection(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == SUPPLY_FLOW_ID)
        self.assertEqual((entry.product_id, entry.product_revision), (PRODUCT_ID, PRODUCT_REVISION))
        self.assertTrue(entry.descriptor.reset_scoped)
        self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.DAILY_ONCE_PER_RESET)
        self.assertTrue(entry.build_handler().selection_only)
        self.assertEqual(RegisteredDispatchSnapshot.from_mapping(entry.registration.to_mapping()), entry.registration)
        self.assertTrue(all(not spec.default_enabled for spec in canonical_flow_specs()))
        self.assertTrue(entry.spec.observation_only_completion)
        with BotStateManager(self.root / "fresh.sqlite3") as fresh:
            rows = fresh.initialize_flows(canonical_flow_specs())
            self.assertFalse(fresh.get_service_enabled())
            self.assertTrue(all(not row.enabled for row in rows))
        legacy = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.assertTrue(all(
            row["registration_status"] == "NOT_REGISTERED" and not row["scheduler_eligible"]
            for row in legacy["flows"].values()
        ))
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        self.assertEqual(parser.parse_args(["serve", "--flow", "supply"]).flow, ["supply"])
        with self.assertRaises(ServiceError):
            self.service.serve(account_id="account", server_id="server", stop=self.stop, emit=lambda _report: None)
        self.assertEqual(self.runner.calls, [])

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

    def test_restart_before_due_skips_runner_and_new_reset_runs_exactly_once(self):
        self.assertEqual(self.once()[0]["status"], "completed")
        due = self.state.get_flow(SUPPLY_FLOW_ID).next_due_at_utc
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 4)
        self.runner.consume = True
        self.stop.now, self.stop.stopped = due, False
        self.assertEqual(self.once()[0]["status"], "completed")
        first, second = self.runs()
        self.assertNotEqual(first.reset_id, second.reset_id)
        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
        self.assertEqual(second.state, RunState.SUCCEEDED)
        self.assertEqual(second.terminal_outcome, "complete_for_reset")
        self.assertEqual((second.consumed_inputs, second.consumed_actions), (4, 1))
        self.assertEqual(self.runner.calls[1][1], first.reset_id)
        self.assertEqual(self.state.get_flow(SUPPLY_FLOW_ID).next_due_at_utc, due + 86400)
        self.stop.stopped = False
        self.assertEqual(self.once(), [])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(len(self.runner.inputs), 8)

    def test_service_passes_held_owner_to_supply_and_releases_after_completion(self):
        def check_owner(owner):
            owner.assert_held(owner.owner, owner.invocation_id)
            run, = self.runs()
            self.assertEqual(run.state, RunState.RUNNING)
            self.assertTrue(self.state.get_flow(SUPPLY_FLOW_ID).blocked)
            with self.assertRaises(boundary.NavigationBoundaryError):
                with boundary.RuntimeInputLock(owner="contender", invocation_id="parallel"):
                    self.fail("a parallel runtime owner acquired the lock")

        self.runner.on_entry = check_owner
        self.assertEqual(self.once()[0]["status"], "completed")
        with boundary.RuntimeInputLock(owner="next-owner", invocation_id="after-serve"):
            pass

    def test_partial_hold_retains_consumption_blocks_restart_and_never_retries(self):
        self.runner.consume, self.runner.partial = True, True
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (3, 1))
        self.assertTrue(self.state.get_flow(SUPPLY_FLOW_ID).blocked)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 3)

    def test_generation_change_after_one_input_stops_further_dispatch(self):
        def toggle(_index):
            self.state.set_flow_enabled(SUPPLY_FLOW_ID, False)
            self.state.set_flow_enabled(SUPPLY_FLOW_ID, True)

        self.runner.on_input = toggle
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 0))
        self.assertEqual(len(self.runner.inputs), 1)


if __name__ == "__main__":
    unittest.main()
