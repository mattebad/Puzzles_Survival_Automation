"""Canonical Campaign AP admission, cadence and dispatch without device access."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.campaign import CampaignApRunnerError
from automation_service.contracts import RecurrenceClass, RecurrenceProjection
from automation_service.registry import (
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, CAMPAIGN_PROFILE_ID, CANONICAL_FLOW_REGISTRY,
    ENHANCEMENT_FLOW_ID, NOVA_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, RECRUITMENT_FLOW_ID,
    SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
)
from automation_service.recruitment import recruitment_reset
from automation_service.service import AutomationService
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.campaign_auto_battle import CAMPAIGN_DRAIN_MAX_RUNS, CAMPAIGN_MAX_INPUTS
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tests.support.service_stop import VirtualStop


class GuardedCampaignRunner:
    stage = "1-15-9"

    def __init__(self, stop):
        self.stop = stop
        self.ap_current = 20
        self.observations = []
        self.calls = []
        self.inputs = []
        self.admission_override = None
        self.on_admission = None
        self.check_runtime_owner = None
        self.fault = None
        self.partial_after_wins = 0
        self.regenerated_ap = 0
        self.battle_seconds = 0

    def observe_home_ap(self, identity, checkpoint):
        raise AssertionError("preclaim game observation forbidden")

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        self.calls.append((identity, previous_reset))
        self.observations.append(identity)
        if self.on_admission:
            self.on_admission()
        checkpoint()
        if self.check_runtime_owner:
            self.check_runtime_owner()
        before = self.ap_current
        consumed = 0
        entries = battles = wins = regenerated = 0
        while self.ap_current >= 14:
            entries += 1
            pending = self.fault == "partial" and wins == self.partial_after_wins
            for index in range(2 if pending else 6):
                checkpoint()
                self.inputs.append((identity.reset_id, entries, index))
                consumed += 1
            if pending:
                break
            battles += 1
            if self.fault == "unknown":
                break
            self.ap_current -= 14
            wins += 1
            self.stop.now += self.battle_seconds
            if wins == 1:
                self.ap_current += self.regenerated_ap
                regenerated = self.regenerated_ap
            if self.fault == "canary":
                break
        failed = self.fault in {"partial", "unknown"}
        result = {
            "status": "unresolved" if failed else "completed" if wins else "deferred",
            "destination": self.stage, "ap_cost": 14,
            "ap_before": before, "ap_after": self.ap_current,
            "progress": {"initial_ap": before, "current_ap": self.ap_current,
                         "ap_spent": 14 * wins, "completed_runs": wins,
                         "ap_regenerated": regenerated, "loss_seen": False},
            "battle_outcome": "victory" if wins else None,
            "result_successor_verified": not failed and bool(wins),
            "terminal_home_verified": not failed,
            "stage_entry_transport_count": entries,
            "new_battle_count": battles,
            "committed_ap_effect_count": wins,
            "campaign_dispatch_count": entries, "total_input_count": consumed,
            "accounting_verified": True,
            "effect_reconciliation_required": failed, "identical_retry_denied": failed,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "cadence_seconds": 300.0, "next_eligible_at": self.stop.now + 300.0,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "task_id": identity.task_id,
            "runtime_profile_id": CAMPAIGN_PROFILE_ID,
        }
        if self.fault == "partial":
            raise CampaignApRunnerError("native successor lost after Stage dispatch", result)
        return result


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
        self.runner.on_admission = check_claim
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
        def assert_owner_held():
            with self.assertRaises(boundary.NavigationBoundaryError):
                with boundary.RuntimeInputLock(owner="contender", invocation_id="parallel"):
                    self.fail("a parallel runtime owner acquired the lock")

        self.runner.check_runtime_owner = assert_owner_held
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
        self.runner.on_admission = self.stop.set
        self.once()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runner.inputs, [])

    def test_generation_change_during_claimed_observation_prevents_resource_input(self):
        def change_generation():
            self.state.set_flow_enabled(CAMPAIGN_FLOW_ID, False)
            self.state.set_flow_enabled(CAMPAIGN_FLOW_ID, True)
        self.runner.on_admission = change_generation
        self.once()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runner.inputs, [])

    def test_midnight_during_claimed_observation_retains_ap_occurrence_identity(self):
        midnight = (int(self.stop.now) // 86400 + 1) * 86400
        self.stop.now = midnight - 1
        self.runner.on_admission = lambda: setattr(self.stop, "now", midnight + 1)
        report, = self.once()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(self.runner.calls[0][0].reset_id, recruitment_reset(midnight - 1))
        self.assertEqual(len(self.runs()), 1)

    def test_other_seven_routes_keep_their_execution_reset_guard(self):
        midnight = (int(self.stop.now) // 86400 + 1) * 86400
        for flow_id, runner_name in (
            (NOVA_FLOW_ID, "nova_runner"), (RECRUITMENT_FLOW_ID, "recruitment_runner"),
            (BIOENHANCER_FLOW_ID, "bioenhancer_runner"), (SUPPLY_FLOW_ID, "supply_runner"),
            (ULTIMATE_FLOW_ID, "ultimate_runner"), (ENHANCEMENT_FLOW_ID, "enhancement_runner"),
            (PERSONAL_MIGHT_FLOW_ID, "personal_might_runner"),
        ):
            with self.subTest(flow_id=flow_id):
                stop = VirtualStop(midnight - 1)
                stop.on_wait = stop.set
                calls, reports = [], []
                def cross_midnight(identity, previous, checkpoint, **options):
                    calls.append(identity)
                    stop.now = midnight + 1
                    checkpoint()
                    self.fail("reset-scoped execution continued after the day changed")
                with BotStateManager(self.root / f"reset-guard-{runner_name}.sqlite3") as state:
                    service = AutomationService(mode="supervised", state=state, **{runner_name: cross_midnight})
                    service.set_service_enabled(True)
                    service.set_flow_enabled(flow_id, True)
                    service.serve(account_id="account", server_id="server", stop=stop,
                                  emit=lambda report: (reports.append(report), stop.set()),
                                  clock=lambda: stop.now, flow_ids=(flow_id,))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(len(reports), 1)
                    self.assertEqual(reports[0]["status"], "blocked")
                    self.assertIn("RESET_CHANGED_DURING_", reports[0]["reason"])
                    self.assertTrue(state.get_flow(flow_id).blocked)

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

    def test_partial_exception_retains_attempted_stage_without_claiming_ap_success(self):
        self.runner.fault = "partial"
        reports = self.once()
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(reports[0]["result"]["committed_ap_effect_count"], 0)
        run, = self.runs()
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (2, 1))
        self.assertTrue(self.state.get_flow(CAMPAIGN_FLOW_ID).blocked)
        self.stop.stopped = False
        self.assertEqual(self.once()[0]["status"], "paused")
        self.assertEqual(len(self.runner.observations), 1)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(len(self.runner.inputs), 2)

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

    def test_selected_nova_and_recruitment_do_not_observe_or_dispatch_campaign(self):
        calls = []

        def nova(identity, previous, checkpoint):
            checkpoint()
            calls.append(identity)
            return {
                "status": "completed", "terminal_home_verified": True,
                "time_basis": "utc", "completed_at_utc": self.stop.now,
                "account_id": identity.account_id, "server_id": identity.server_id,
                "reset_id": identity.reset_id, "attempts_before": 2, "attempts_after": 1,
                "praise_transport_calls": 1, "total_input_count": 1,
                "journal_status": "confirmed", "cooldown_seconds": 300,
                "next_eligible_at": self.stop.now + 300,
            }

        def recruitment(identity, previous, checkpoint):
            checkpoint()
            calls.append(identity)
            return {
                "status": "completed", "terminal_home_verified": True,
                "time_basis": "utc", "completed_at_utc": self.stop.now,
                "maintenance_state": json.loads(NoahMaintenanceState.for_identity(identity).to_json()),
                "total_input_count": 1, "recruitment_dispatch_count": 1, "actions_completed": 1,
            }

        self.service.nova_runner = nova
        self.service.recruitment_runner = recruitment
        for flow_id in (NOVA_FLOW_ID, RECRUITMENT_FLOW_ID):
            self.service.set_flow_enabled(flow_id, True)
        reports = []

        def emit(report):
            reports.append(report)
            if len(reports) == 2:
                self.stop.set()

        self.service.serve(
            account_id="account", server_id="server", stop=self.stop, emit=emit,
            clock=lambda: self.stop.now, flow_ids=(NOVA_FLOW_ID, RECRUITMENT_FLOW_ID),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual({report["flow_id"] for report in reports}, {NOVA_FLOW_ID, RECRUITMENT_FLOW_ID})
        self.assertTrue(all(report["status"] == "completed" for report in reports), reports)
        self.assertEqual(self.runner.observations, [])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.runner.inputs, [])
        self.assertEqual({run.flow_id for run in self.runs()}, {NOVA_FLOW_ID, RECRUITMENT_FLOW_ID})


if __name__ == "__main__":
    unittest.main()
