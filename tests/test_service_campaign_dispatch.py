"""Canonical Campaign AP admission, cadence and dispatch without device access."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.contracts import RecurrenceClass, RecurrenceProjection
from automation_service.registry import CAMPAIGN_FLOW_ID, CANONICAL_FLOW_REGISTRY
from automation_service.recruitment import recruitment_reset
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.campaign_auto_battle import CAMPAIGN_DRAIN_MAX_RUNS, CAMPAIGN_MAX_INPUTS
from tests.support.service_stop import VirtualStop
from tests.support.service_route_fakes import GuardedCampaignRunner


class ServiceCampaignDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "runtime-lock.sqlite3",
        ))
        self.stack.enter_context(patch(
            "scripts.bluestacks_native_runtime.ADBRunner",
            side_effect=AssertionError("device access forbidden"),
        ))
        self.stack.enter_context(patch(
            "scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
            side_effect=AssertionError("device access forbidden"),
        ))
        self.stop = VirtualStop(1_800_000_000.0)
        self.path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = GuardedCampaignRunner(self.stop)
        self.service = AutomationService(
            mode="supervised", state=self.state, campaign_runner=self.runner,
        )
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(CAMPAIGN_FLOW_ID, True)

    def serve(self, emit, *, state=None):
        service = self.service if state is None else AutomationService(
            mode="supervised", state=state, campaign_runner=self.runner,
        )
        service.serve(
            account_id="account", server_id="server", stop=self.stop, emit=emit,
            clock=lambda: self.stop.now, flow_ids=(CAMPAIGN_FLOW_ID,),
        )

    def once(self, *, state=None):
        reports = []
        self.stop.on_wait = self.stop.set
        self.serve(lambda report: (reports.append(report), self.stop.set()), state=state)
        return reports

    def runs(self):
        ids = self.state._db.execute("SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid").fetchall()
        return [self.state.get_run(row[0]) for row in ids]

    def assert_no_dispatch(self):
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(self.runs(), [])

    def test_game_observation_begins_only_after_canonical_claim(self):
        def check_claim():
            run, = self.runs()
            self.assertIn(run.state, {RunState.RUNNING, RunState.CLAIMED})
            self.assertEqual(run.consumed_inputs, 0)
        self.runner.on_entry = check_claim
        self.assertEqual(self.once()[0]["status"], "completed")
        self.assertEqual(len(self.runner.observations), 1)

    def test_low_ap_is_measured_inside_claim_and_defers_without_input(self):
        self.runner.ap_current = 12
        self.assertEqual(self.once()[0]["status"], "completed")
        run, = self.runs()
        self.assertEqual(run.state, RunState.DEFERRED)
        self.assertEqual(run.consumed_inputs, 0)
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual(self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, self.stop.now + 300)

    def test_one_battle_drains_remaining_ap_and_persists_utc_next_due(self):
        reports = self.once()
        self.assertEqual(reports[0]["status"], "completed", reports)
        run, = self.runs()
        self.assertEqual(run.state, RunState.DEFERRED)
        self.assertEqual((run.max_inputs, run.max_actions), (CAMPAIGN_MAX_INPUTS, CAMPAIGN_DRAIN_MAX_RUNS))
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (6, 1))
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 6)
        self.assertEqual(self.runner.ap_current, 6)
        flow = self.state.get_flow(CAMPAIGN_FLOW_ID)
        self.assertEqual(flow.next_due_at_utc, self.stop.now + 300)
        self.assertFalse(flow.blocked)
        self.assertEqual(reports[0]["result"]["committed_ap_effect_count"], 1)

    def test_new_service_before_due_skips_observation_and_execution_then_due_runs_once(self):
        self.runner.ap_current = 120
        self.assertEqual(self.once()[0]["status"], "completed")
        due = self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
        self.assertEqual(len(self.runner.observations), 1)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 48)
        self.assertEqual(len(self.runs()), 1)
        self.stop.now = due
        self.runner.ap_current += 14
        self.stop.stopped = False
        self.assertEqual(self.once()[0]["status"], "completed")
        first, second = self.runs()
        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
        self.assertEqual(second.state, RunState.DEFERRED)
        self.assertEqual(len(self.runner.observations), 2)
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(len(self.runner.inputs), 54)

    def test_legacy_persisted_cadence_keeps_ap_recurrence_and_deadline_after_restart(self):
        entry = next(item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == CAMPAIGN_FLOW_ID)
        path = self.root / "legacy-cadence.sqlite3"
        with BotStateManager(path) as legacy:
            legacy.initialize_flows((replace(entry.spec, cadence="ap_regeneration_pulse"),))
            service = AutomationService(mode="supervised", state=legacy, campaign_runner=self.runner)
            service.set_service_enabled(True)
            service.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
            self.assertEqual(self.once(state=legacy)[0]["status"], "completed")
            flow = legacy.get_flow(CAMPAIGN_FLOW_ID)
            self.assertEqual(flow.cadence, "ap_regeneration_pulse")
            due = flow.next_due_at_utc
            self.assertEqual(due, self.stop.now + 300)
        self.stop.stopped = False
        with BotStateManager(path) as restarted:
            self.assertEqual(self.once(state=restarted), [])
            self.assertEqual(restarted.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, due)
        self.assertEqual(len(self.runner.observations), 1)
        self.assertEqual(len(self.runner.calls), 1)

    def test_full_ap_and_regeneration_drain_in_one_run_then_wait_from_final_completion(self):
        self.runner.ap_current = 120
        self.runner.regenerated_ap = 6
        self.runner.battle_seconds = 10
        started = self.stop.now
        result = self.once()[0]["result"]
        run, = self.runs()
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual((result["ap_before"], result["ap_after"]), (120, 0))
        self.assertEqual(result["progress"]["ap_regenerated"], 6)
        self.assertEqual(result["progress"]["ap_spent"], 126)
        self.assertEqual(result["progress"]["completed_runs"], 9)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (54, 9))
        self.assertEqual(result["completed_at_utc"], started + 90)
        self.assertEqual(self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc, started + 90 + 300)

    def test_one_battle_canary_with_affordable_ap_cannot_schedule_completed_drain(self):
        self.runner.ap_current = 120
        self.runner.fault = "canary"
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (6, 1))
        self.assertTrue(self.state.get_flow(CAMPAIGN_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc)

    def test_stop_during_claimed_observation_prevents_resource_input(self):
        self.runner.on_entry = self.stop.set
        self.once()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runner.inputs, [])

    def test_generation_change_during_claimed_observation_prevents_resource_input(self):
        def change_generation():
            self.state.set_flow_enabled(CAMPAIGN_FLOW_ID, False)
            self.state.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
        self.runner.on_entry = change_generation
        self.once()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runner.inputs, [])

    def test_midnight_during_claimed_observation_retains_ap_occurrence_identity(self):
        midnight = (int(self.stop.now) // 86400 + 1) * 86400
        self.stop.now = midnight - 1
        self.runner.on_entry = lambda: setattr(self.stop, "now", midnight + 1)
        report, = self.once()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(self.runner.calls[0][0].reset_id, recruitment_reset(midnight - 1))
        self.assertEqual(len(self.runs()), 1)

    def test_unknown_execution_retains_consumption_and_blocks_identical_next_pass(self):
        self.runner.fault = "unknown"
        self.assertEqual(self.once()[0]["status"], "blocked")
        run, = self.runs()
        self.assertEqual(run.state, RunState.BLOCKED)
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (6, 1))
        self.assertTrue(self.state.get_flow(CAMPAIGN_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        with BotStateManager(self.path) as restarted:
            self.assertEqual(self.once(state=restarted)[0]["status"], "paused")
        self.assertEqual(len(self.runner.observations), 1)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 6)

    def test_unknown_next_entry_preserves_prior_effects_and_blocks_retry_without_due(self):
        self.runner.ap_current = 88
        self.runner.fault = "partial"
        self.runner.partial_after_wins = 2
        report, = self.once()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["result"]["committed_ap_effect_count"], 2)
        self.assertEqual(report["result"]["progress"]["ap_spent"], 28)
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (14, 3))
        self.assertTrue(self.state.get_flow(CAMPAIGN_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(CAMPAIGN_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        self.assertEqual(self.once()[0]["status"], "paused")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 14)

if __name__ == "__main__":
    unittest.main()
