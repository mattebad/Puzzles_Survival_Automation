"""Device-forbidden cooldown rollover lifecycle and fail-closed boundaries."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import BIOENHANCER_FLOW_ID
from automation_service.service import AutomationService, ServiceError
from automation_service.state import (
    BotStateManager, DispatchValidation, RunState, TerminalProjectionError,
)
from scripts import navigation_development_boundary as boundary
from scripts.bioenhancer_free_research_canary import parse_free_research_cooldown
from scripts.pnsctl import ApplicationStartupError


DUE = 1_793_404_799.979242
MIDNIGHT = 1_793_404_800.0
OLD_RESET = "game-day-2026-10-30"
NEW_RESET = "game-day-2026-10-31"


class VirtualStop:
    def __init__(self):
        self.now = DUE
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.now += seconds
        self.set()
        return True


class ServiceCooldownResetEdgeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        scratch = Path(__file__).resolve().parents[1] / ".local-validation" / "cooldown-reset-edge"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=scratch)))
        self.stack.enter_context(patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "runtime-lock.sqlite3"))
        self.core_clear = self.stack.enter_context(patch.object(
            boundary, "require_canonical_unresolved_clear", return_value=None))
        self.stack.enter_context(patch(
            "scripts.bluestacks_native_runtime.ADBRunner",
            side_effect=AssertionError("device forbidden")))
        self.stack.enter_context(patch(
            "scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
            side_effect=AssertionError("device forbidden")))
        self.stop = VirtualStop()
        self.path = self.root / "state.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner_calls = []
        self.gameplay_inputs = []
        self.startup_markers = []
        self.runner_hook = None
        self.startup_hook = None
        self.service = self.make_service(self.state)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(BIOENHANCER_FLOW_ID, True)
        self.state.update_schedule(
            BIOENHANCER_FLOW_ID, next_due_at_utc=DUE, now_utc_epoch=DUE)

    def make_service(self, state):
        return AutomationService(mode="supervised", state=state,
            bioenhancer_runner=self.runner, application_startup=self.startup)

    @staticmethod
    def ready_startup(*, launch_count=0):
        return {"status": "launched" if launch_count else "already_foreground",
                "system_launch_count": launch_count, "game_input_count": 0,
                "route_ready": True,
                "transport_status": "returned" if launch_count else "not_attempted"}

    def startup(self, flow_id, run_id, owner, checkpoint):
        owner.assert_held(owner.owner, owner.invocation_id)
        self.startup_markers.append(self.state.get_flow(flow_id).blocked_reason)
        if self.startup_hook is not None:
            return self.startup_hook(checkpoint)
        return self.ready_startup()

    def runner(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        self.runner_calls.append(identity)
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        if self.runner_hook is not None:
            return self.runner_hook(identity, checkpoint)
        checkpoint()
        cooldown = parse_free_research_cooldown(
            "Free in 01:00:00", now=datetime.fromtimestamp(self.stop.now, timezone.utc))
        return {
            "status": "completed", "no_work": True,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "time_basis": "utc",
            "completed_at_utc": self.stop.now, "accounting_verified": True,
            "terminal_home_verified": True, "cooldown_proof_verified": True,
            "total_input_count": 0, "free_research_transport_calls": 0,
            "cooldown": cooldown, "next_due_utc": cooldown["next_due_utc"],
        }

    def once(self, *, state=None):
        self.stop.stopped = False
        reports = []
        service = self.service if state is None else self.make_service(state)
        service.serve(account_id="account", server_id="server", stop=self.stop,
            emit=lambda report: (reports.append(report), self.stop.set()),
            clock=lambda: self.stop.now, flow_ids=(BIOENHANCER_FLOW_ID,))
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY rowid")]

    def cross_reset(self, checkpoint):
        self.stop.now = MIDNIGHT
        checkpoint()
        self.fail("old-reset checkpoint admitted execution")

    def assert_rollover_deferred_and_new_reset_admits(self):
        report, = self.once()
        self.assertEqual(report["status"], "deferred", report)
        self.assertFalse(report["result"].get("terminal_home_verified", False))
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(self.gameplay_inputs, [])
        old, = self.runs()
        self.assertEqual((old.state, old.reset_id), (RunState.DEFERRED, OLD_RESET))
        self.assertEqual((old.consumed_inputs, old.consumed_actions), (0, 0))
        self.assertEqual(self.startup_markers, [f"EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:{old.run_id}"])
        flow = self.state.get_flow(BIOENHANCER_FLOW_ID)
        self.assertFalse(flow.blocked)
        self.assertIsNone(flow.blocked_reason)
        self.assertEqual(flow.consecutive_failures, 0)
        self.assertEqual(flow.next_due_at_utc, MIDNIGHT)
        self.startup_hook = None
        self.stop.now = MIDNIGHT + 1
        with BotStateManager(self.path) as restarted:
            completed, = self.once(state=restarted)
        self.assertEqual(completed["status"], "completed", completed)
        old_again, new = self.runs()
        self.assertEqual(old_again, old)
        self.assertEqual((new.state, new.reset_id), (RunState.DEFERRED, NEW_RESET))
        self.assertNotEqual(old.occurrence_key, new.occurrence_key)
        self.assertEqual([identity.reset_id for identity in self.runner_calls], [NEW_RESET])

    def assert_inspection_blocks_restart(self):
        report, = self.once()
        self.assertEqual(report["status"], "blocked", report)
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(self.gameplay_inputs, [])
        self.assertTrue(self.state.get_flow(BIOENHANCER_FLOW_ID).blocked)
        before = self.runs()
        self.stop.now = MIDNIGHT + 60
        with BotStateManager(self.path) as restarted:
            paused, = self.once(state=restarted)
        self.assertEqual(paused["status"], "paused", paused)
        self.assertEqual(self.runs(), before)
        self.assertEqual(self.runner_calls, [])

    def test_exact_due_startup_rollover_defers_without_entering_runner(self):
        self.startup_hook = self.cross_reset
        self.assert_rollover_deferred_and_new_reset_admits()

    def test_continuous_serve_waits_then_admits_new_reset_without_restart(self):
        test = self

        class ContinuousStop(VirtualStop):
            def __init__(self):
                super().__init__()
                self.waits = []

            def wait(self, seconds):
                self.waits.append(seconds)
                test.assertLessEqual(len(self.waits), 1, "new reset failed to admit after normal wait")
                test.assertGreater(seconds, 0, "service hot-looped after deferral")
                self.now += seconds
                return self.stopped

        self.stop = ContinuousStop()

        def startup(checkpoint):
            self.startup_hook = None
            self.cross_reset(checkpoint)

        self.startup_hook = startup
        reports = []
        first_terminal = None
        clock_reads = 0

        def clock():
            nonlocal clock_reads
            clock_reads += 1
            self.assertLess(clock_reads, 256, "service did not reach a bounded second claim")
            return self.stop.now

        def emit(report):
            nonlocal first_terminal
            reports.append(report)
            self.assertLessEqual(len(reports), 2, "service emitted extra reports before completion")
            if len(reports) == 1:
                first_terminal, = self.runs()
            else:
                self.stop.set()

        self.service.serve(account_id="account", server_id="server", stop=self.stop,
            emit=emit, clock=clock, flow_ids=(BIOENHANCER_FLOW_ID,))
        self.assertEqual([report["status"] for report in reports], ["deferred", "completed"])
        self.assertFalse(reports[0]["result"].get("terminal_home_verified", False))
        old, new = self.runs()
        self.assertEqual(old, first_terminal)
        self.assertEqual((old.state, old.reset_id), (RunState.DEFERRED, OLD_RESET))
        self.assertEqual((old.consumed_inputs, old.consumed_actions), (0, 0))
        self.assertEqual((new.state, new.reset_id), (RunState.DEFERRED, NEW_RESET))
        self.assertNotEqual(old.occurrence_key, new.occurrence_key)
        self.assertEqual(old.owner_instance_id, new.owner_instance_id)
        self.assertEqual([identity.reset_id for identity in self.runner_calls], [NEW_RESET])
        self.assertEqual(self.gameplay_inputs, [])
        self.assertEqual(len(self.stop.waits), 1)
        self.assertFalse(self.state.get_flow(BIOENHANCER_FLOW_ID).blocked)

    def test_wrapped_startup_rollover_with_no_launch_defers(self):
        def startup(checkpoint):
            try:
                self.cross_reset(checkpoint)
            except Exception as exc:
                raise ApplicationStartupError(str(exc), {
                    "status": "unresolved", "system_launch_count": 0,
                    "game_input_count": 0, "transport_status": "not_attempted",
                }) from exc
        self.startup_hook = startup
        self.assert_rollover_deferred_and_new_reset_admits()

    def test_successfully_returned_launch_can_defer_before_runner(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            return self.ready_startup(launch_count=1)
        self.startup_hook = startup
        self.assert_rollover_deferred_and_new_reset_admits()

    def test_ambiguous_startup_launch_is_not_retried_on_new_reset(self):
        def startup(checkpoint):
            try:
                self.cross_reset(checkpoint)
            except Exception as exc:
                raise ApplicationStartupError(str(exc), {
                    "status": "unresolved", "system_launch_count": 1,
                    "game_input_count": 0, "transport_status": "attempted",
                }) from exc
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_reset_after_runner_entry_remains_blocked_even_before_gameplay(self):
        def runner(_identity, checkpoint):
            self.cross_reset(checkpoint)
        self.runner_hook = runner
        report, = self.once()
        self.assertEqual(report["status"], "blocked", report)
        old, = self.runs()
        self.assertEqual(old.state, RunState.BLOCKED)
        self.assertEqual((old.consumed_inputs, old.consumed_actions), (0, 0))
        self.assertEqual(len(self.runner_calls), 1)
        self.assertEqual(self.gameplay_inputs, [])
        self.stop.now = MIDNIGHT + 60
        paused, = self.once()
        self.assertEqual(paused["status"], "paused", paused)
        self.assertEqual(len(self.runner_calls), 1)

    def test_terminal_projection_failure_keeps_interruption_marker(self):
        self.startup_hook = self.cross_reset
        with patch.object(self.state, "project_terminal",
                          side_effect=TerminalProjectionError("terminal fence lost")):
            report, = self.once()
        self.assertEqual(report["status"], "blocked", report)
        old, = self.runs()
        self.assertEqual(old.state, RunState.RUNNING)
        self.assertEqual((old.consumed_inputs, old.consumed_actions), (0, 0))
        flow = self.state.get_flow(BIOENHANCER_FLOW_ID)
        self.assertTrue(flow.blocked)
        self.assertEqual(flow.blocked_reason, f"EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:{old.run_id}")
        self.assertEqual(self.runner_calls, [])

    def test_control_loss_after_rollover_signal_cannot_defer(self):
        def startup(checkpoint):
            try:
                self.cross_reset(checkpoint)
            except Exception as exc:
                self.state.set_flow_enabled(BIOENHANCER_FLOW_ID, False)
                raise ApplicationStartupError(str(exc), {
                    "status": "unresolved", "system_launch_count": 0,
                    "game_input_count": 0, "transport_status": "not_attempted",
                }) from exc
        self.startup_hook = startup
        report, = self.once()
        self.assertEqual(report["status"], "blocked", report)
        flow = self.state.get_flow(BIOENHANCER_FLOW_ID)
        self.assertFalse(flow.enabled)
        self.assertTrue(flow.blocked)
        self.assertNotEqual(self.runs()[0].state, RunState.DEFERRED)
        self.assertEqual(self.runner_calls, [])

    def test_dispatch_fence_loss_after_rollover_signal_cannot_defer(self):
        def startup(checkpoint):
            try:
                self.cross_reset(checkpoint)
            except Exception as exc:
                self.stack.enter_context(patch.object(self.state, "validate_dispatch",
                    return_value=DispatchValidation(False, "RUN_TOKEN_MISMATCH")))
                raise ApplicationStartupError(str(exc), {
                    "status": "unresolved", "system_launch_count": 0,
                    "game_input_count": 0, "transport_status": "not_attempted",
                }) from exc
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_unresolved_core_effect_blocks_pre_runner_rollover(self):
        self.core_clear.side_effect = boundary.NavigationBoundaryError("unresolved fake action")
        self.startup_hook = self.cross_reset
        self.assert_inspection_blocks_restart()

    def test_untyped_reset_text_never_authorizes_deferral(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            raise ServiceError("RESET_CHANGED_DURING_BIOENHANCER")
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_invalid_startup_result_stays_blocked_after_midnight(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            return {"status": "unresolved", "system_launch_count": 0,
                    "game_input_count": 0}
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_successful_looking_attempted_launch_is_still_ambiguous(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            return dict(self.ready_startup(launch_count=1), transport_status="attempted")
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_successful_looking_unknown_launch_is_still_ambiguous(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            return dict(self.ready_startup(launch_count=1), transport_status="unknown")
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()

    def test_boolean_gameplay_count_is_not_verified_zero_consumption(self):
        def startup(_checkpoint):
            self.stop.now = MIDNIGHT
            return dict(self.ready_startup(), game_input_count=False)
        self.startup_hook = startup
        self.assert_inspection_blocks_restart()


if __name__ == "__main__":
    unittest.main()
