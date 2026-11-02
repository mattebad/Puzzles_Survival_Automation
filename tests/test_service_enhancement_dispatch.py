"""Enhancement daily dispatch and canonical fences without device access."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.enhancement import (
    PRODUCT_ID, PRODUCT_REVISION, EnhancementNativePartialResultError,
)
from automation_service.registry import (
    CANONICAL_FLOW_REGISTRY, ENHANCEMENT_FLOW_ID, canonical_flow_specs,
)
from automation_service.service import AutomationService, ServiceError
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tests.test_service_recruitment import VirtualStop


class GuardedEnhancementRunner:
    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs = [], []
        self.no_work = self.partial = False
        self.retained_count = 0
        self.use_calls = 0
        self.on_entry = self.on_input = None

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry(runtime_input_lock)
        count = uses = 0
        error = None
        try:
            if not self.no_work:
                for index in range((3 - self.retained_count) * 2):
                    checkpoint()
                    self.inputs.append((identity.reset_id, index))
                    count += 1
                    if index % 2:
                        uses += 1
                        self.use_calls += 1
                    if self.on_input:
                        self.on_input(index)
                    if self.partial and uses:
                        raise RuntimeError("native successor lost after first Use")
        except Exception as exc:
            error = exc
        native_reset = f"local-{identity.reset_id.removeprefix('game-day-')}-enhancement-family"
        home = {"frame_path": "current-home.png", "frame_sha256": "a" * 64}
        variants = ("gear", "chip", "module")
        retained = list(variants) if self.no_work else list(variants[:self.retained_count])
        current = [variant for variant in variants if variant not in retained]
        runtime = str(self.output / "current-canonical-session")
        topology = "retained_categories_plus_current_home" if self.no_work else "composite" if retained else "continuous"
        sources = {variant: {
            "status": "verified", "variant": variant, "reset_identity": native_reset,
            "runtime_session": str(self.output / "original-family") if variant in retained else runtime,
            "delivery_sha256": "b" * 64,
            "resource_affecting_action_key": f"enhancement:{variant}:enhancement-use:{'retained' if variant in retained else 'current'}",
        } for variant in variants}
        verification = {
            "status": "verified", "proof_topology": topology,
            "categories_verified": list(variants), "current_categories": current, "retained_categories": retained,
            "retained_category_count": len(retained), "current_resource_affecting_dispatch_count": len(current),
            "category_source_proofs": sources,
        }
        result = {
            "status": "unresolved" if error else "already_completed" if self.no_work else "completed",
            "no_work": self.no_work, "flow_id": ENHANCEMENT_FLOW_ID,
            "product_id": PRODUCT_ID, "product_revision": PRODUCT_REVISION, "task_id": PRODUCT_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "native_reset_identity": native_reset,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "next_reset_at_utc": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "input_count": count, "enhancement_dispatch_count": uses,
            "resource_affecting_dispatch_count": uses, "categories_completed": 3,
            "accounting_verified": True, "terminal_home_verified": error is None,
            "terminal_home_frame": home, "family_verification": verification,
            "proof_topology": topology, "session_directory": runtime,
            "effect_reconciliation_required": error is not None and uses > 0,
            "identical_retry_denied": error is not None,
        }
        if self.no_work:
            result.update(
                current_home_proof=dict(home),
                retained_category_proofs=sources,
            )
        if error:
            raise EnhancementNativePartialResultError(str(error), partial_result=result) from error
        return result


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

    def test_compiled_daily_binding_is_disabled_and_cli_keeps_explicit_selection(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == ENHANCEMENT_FLOW_ID)
        self.assertEqual((entry.product_id, entry.product_revision), (PRODUCT_ID, PRODUCT_REVISION))
        self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.DAILY_ONCE_PER_RESET)
        self.assertTrue(entry.descriptor.reset_scoped)
        self.assertTrue(entry.spec.observation_only_completion)
        self.assertTrue(entry.build_handler().selection_only)
        self.assertTrue(all(not spec.default_enabled for spec in canonical_flow_specs()))
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        self.assertEqual(parser.parse_args(["serve", "--flow", "enhancement"]).flow, ["enhancement"])
        with self.assertRaises(ServiceError):
            self.service.serve(account_id="account", server_id="server", stop=self.stop, emit=lambda _report: None)
        self.assertEqual(self.runner.calls, [])

    def test_three_uses_complete_reset_with_bounded_counts_and_borrowed_owner(self):
        def check_owner(owner):
            owner.assert_held(owner.owner, owner.invocation_id)
            run, = self.runs()
            self.assertEqual(run.state, RunState.RUNNING)
            self.assertTrue(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)
            with self.assertRaises(boundary.NavigationBoundaryError):
                with boundary.RuntimeInputLock(owner="contender", invocation_id="parallel"):
                    self.fail("a parallel runtime owner acquired the lock")

        self.runner.on_entry = check_owner
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
        with boundary.RuntimeInputLock(owner="next-owner", invocation_id="after-serve"):
            pass

    def test_restart_before_due_skips_runner_then_new_reset_runs_once(self):
        self.assertEqual(self.once()[0]["status"], "completed")
        due = self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc
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
        self.assertEqual((second.consumed_inputs, second.consumed_actions), (6, 3))
        self.assertEqual(self.runner.calls[1][1], first.reset_id)
        self.assertEqual(self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc, due + 86400)
        self.stop.stopped = False
        self.assertEqual(self.once(), [])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.runner.use_calls, 6)

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

    def test_partial_first_use_retains_counts_blocks_restart_and_never_retries(self):
        self.runner.partial = True
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (2, 1))
        self.assertTrue(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(ENHANCEMENT_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 2)
        self.assertEqual(self.runner.use_calls, 1)

    def test_generation_change_after_first_input_prevents_any_use(self):
        def toggle(_index):
            self.state.set_flow_enabled(ENHANCEMENT_FLOW_ID, False)
            self.state.set_flow_enabled(ENHANCEMENT_FLOW_ID, True)

        self.runner.on_input = toggle
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 0))
        self.assertEqual(len(self.runner.inputs), 1)
        self.assertEqual(self.runner.use_calls, 0)
        self.assertTrue(self.state.get_flow(ENHANCEMENT_FLOW_ID).blocked)


if __name__ == "__main__":
    unittest.main()
