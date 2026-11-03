"""Canonical Bioenhancer dispatch, persistent cadence and borrowed ownership offline."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from automation_service.bioenhancer import BioenhancerNativePartialResultError, PRODUCT_ID
from automation_service.cli import build_parser
from automation_service.registry import BIOENHANCER_FLOW_ID, CANONICAL_FLOW_REGISTRY, RegisteredDispatchSnapshot
from automation_service.service import AutomationService, ServiceError
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from scripts.bioenhancer_free_research_canary import parse_free_research_cooldown
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tests.support.service_stop import VirtualStop


class GuardedBioenhancerRunner:
    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs = [], []
        self.consume, self.fault = False, None
        self.on_input = self.on_entry = None

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        self.calls.append(identity)
        if self.on_entry:
            self.on_entry(runtime_input_lock)
        count = actions = 0
        current = self.output / f"native-{len(self.calls)}"
        ordinal = 0
        def capture(label):
            nonlocal ordinal
            ordinal += 1
            image = np.full((1280, 800, 3), ordinal, np.uint8)
            raw = cv2.imencode(".png", image)[1].tobytes()
            path = current / f"{ordinal}-{label}.png"
            path.write_bytes(raw)
            return CapturedNativeFrame(image, raw, hashlib.sha256(raw).hexdigest(), float(ordinal), path)

        error = None
        try:
            with boundary.DevelopmentSession(
                owner="bio-test-route", invocation_id=current.name,
                session_directory=current, max_inputs=8,
                runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
            ) as session:
                for index in range(5):
                    resource = self.consume and index == 2
                    def dispatch(_frame):
                        nonlocal count, actions
                        checkpoint()
                        self.inputs.append((identity.reset_id, index))
                        count += 1
                        actions += int(resource)
                        if self.on_input:
                            self.on_input(index)
                    session.run_action(action_class="free_action" if resource else "navigation",
                                       label=f"step-{index}", capture=capture, dispatch=dispatch,
                                       recognize=lambda _frame: "known_successor")
                    if self.fault == "partial" and resource:
                        raise RuntimeError("native lost successor after Research")
        except Exception as exc:
            error = exc
        unknown = error is not None or self.fault == "unknown"
        cooldown = parse_free_research_cooldown("Free in 01:00:00", now=datetime.fromtimestamp(self.stop.now, timezone.utc))
        result = {
            "status": "unresolved" if unknown else "completed", "terminal_home_verified": not unknown,
            "cooldown_proof_verified": not unknown, "accounting_verified": True,
            "account_id": identity.account_id, "server_id": identity.server_id, "reset_id": identity.reset_id,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "no_work": not self.consume, "total_input_count": count, "free_research_transport_calls": actions,
            "cooldown": cooldown, "next_due_utc": cooldown["next_due_utc"],
            "semantic_postcondition": {"proven": True, "timer_proven": True} if actions else None,
            "effect_reconciliation_required": unknown and actions > 0,
            "identical_retry_denied": unknown,
        }
        if error:
            raise BioenhancerNativePartialResultError(str(error), partial_result=result) from error
        return result


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

    def test_exact_compiled_binding_is_disabled_by_default_and_cli_selection_is_explicit(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == BIOENHANCER_FLOW_ID)
        self.assertFalse(entry.spec.default_enabled)
        self.assertEqual((entry.product_id, entry.product_revision), (PRODUCT_ID, "bioenhancer_research-v1"))
        self.assertFalse(entry.descriptor.reset_scoped)
        self.assertEqual(entry.descriptor.cadence, "cooldown_pulse")
        self.assertTrue(entry.build_handler().selection_only)
        self.assertEqual(RegisteredDispatchSnapshot.from_mapping(entry.registration.to_mapping()), entry.registration)
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        self.assertEqual(parser.parse_args(["serve", "--flow", "bioenhancer"]).flow, ["bioenhancer"])
        with self.assertRaises(ServiceError):
            self.service.serve(account_id="account", server_id="server", stop=self.stop, emit=lambda _report: None)
        self.assertEqual(self.runner.calls, [])

    def test_no_work_persists_deferred_run_then_restart_waits_and_due_runs_once(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        first, = self.runs()
        self.assertEqual(first.state, RunState.DEFERRED)
        self.assertEqual((first.max_inputs, first.max_actions, first.consumed_inputs, first.consumed_actions), (8, 1, 5, 0))
        self.assertEqual(self.runner.calls[0].task_id, PRODUCT_ID)
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

    def test_service_marker_and_single_owner_are_preserved_through_borrowed_route(self):
        def entry(owner):
            owner.assert_held(owner.owner, owner.invocation_id)
            flow = self.state.get_flow(BIOENHANCER_FLOW_ID)
            self.assertTrue(flow.blocked_reason.startswith("EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:"))
        self.runner.on_entry = entry
        acquire = boundary.RuntimeInputLock.acquire
        with patch.object(boundary.RuntimeInputLock, "acquire", autospec=True, side_effect=acquire) as acquired:
            self.assertEqual(self.once()[0]["status"], "completed")
            self.assertEqual(acquired.call_count, 1)
        with boundary.RuntimeInputLock(owner="next-owner", invocation_id="after-serve"):
            pass

    def test_partial_research_retains_counts_blocks_restart_and_never_retries(self):
        self.runner.consume, self.runner.fault = True, "partial"
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (3, 1))
        self.assertTrue(self.state.get_flow(BIOENHANCER_FLOW_ID).blocked)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 3)

    def test_generation_change_after_one_input_prevents_any_further_dispatch(self):
        def toggle(_index):
            self.state.set_flow_enabled(BIOENHANCER_FLOW_ID, False)
            self.state.set_flow_enabled(BIOENHANCER_FLOW_ID, True)
        self.runner.on_input = toggle
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (1, 0))
        self.assertEqual(len(self.runner.inputs), 1)


if __name__ == "__main__":
    unittest.main()
