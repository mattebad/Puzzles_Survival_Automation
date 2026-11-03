"""Guarded service -> native runner -> real controller, with no device transport."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from automation_service.recruitment import recruitment_next_due, recruitment_reset
from automation_service.registry import RECRUITMENT_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from scripts import navigation_development_boundary as boundary
from tasks.noahs_tavern_recruit import RecruitTier
from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID, NoahMaintenanceState
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support import recruitment_service as support


class ServiceRecruitmentTests(support.RecruitmentServiceCase):
    def test_native_pass_cooldown_restart_and_later_eligibility(self):
        reports = []
        def emit(report):
            with self.assertRaises(boundary.NavigationBoundaryError):
                with boundary.RuntimeInputLock(owner="second", invocation_id="contender"):
                    self.fail("second controller acquired runtime ownership")
            reports.append(report)
            self.stop.set()
        self.serve(emit)
        self.assertEqual(reports[0]["status"], "completed", reports)
        self.assertEqual(reports[0]["result"]["actions_completed"], 1)
        self.assertEqual(reports[0]["result"]["maintenance_state"]["basic_daily_count"], 1)
        due = self.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc
        persisted_due = reports[0]["result"]["maintenance_state"]["tiers"][
            RecruitTier.BASIC.value
        ]["next_eligible_at"]
        self.assertEqual(due, persisted_due)
        run_budget = self.state._db.execute(
            "SELECT max_inputs, max_actions, consumed_inputs, consumed_actions FROM runs "
            "WHERE flow_id=? ORDER BY claimed_at_utc DESC LIMIT 1",
            (RECRUITMENT_FLOW_ID,),
        ).fetchone()
        self.assertEqual((run_budget["max_inputs"], run_budget["max_actions"]), (12, 3))
        self.assertEqual(
            (run_budget["consumed_inputs"], run_budget["consumed_actions"]),
            (4, 1),
        )
        self.assertEqual(self.runtimes[0]._screen(), "HOME_BASE")
        self.assertEqual([kind for kind, _ in self.runtimes[0].calls], ["tap", "tap", "tap", "back"])
        # Restart reads persisted due state; no new route until the deadline.
        self.stop.stopped = False
        with BotStateManager(self.state_path) as restarted:
            self.service = AutomationService(mode="supervised", state=restarted, recruitment_runner=self.runner)
            self.serve(emit)
        self.assertEqual(len(self.runtimes), 2)
        # The route preserves the observed 00:09:52 cooldown instead of
        # replacing it with the nominal ten-minute policy duration.
        self.assertEqual(sum(self.stop.waits), 592)
        self.assertTrue(all(0 < delay <= 30 for delay in self.stop.waits))
        self.assertEqual(reports[1]["result"]["maintenance_state"]["basic_daily_count"], 2)
        self.assertEqual(
            self.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc,
            reports[1]["result"]["maintenance_state"]["tiers"][RecruitTier.BASIC.value]["next_eligible_at"],
        )
        # Midnight resets only Basic's count; independent long cooldowns survive.
        self.stop.now = (self.stop.now // 86400 + 1) * 86400
        self.stop.stopped = False
        self.service = AutomationService(mode="supervised", state=self.state, recruitment_runner=self.runner)
        self.serve(emit)
        rolled = reports[-1]["result"]["maintenance_state"]
        self.assertEqual(rolled["basic_daily_count"], 1)
        for tier in (RecruitTier.INT, RecruitTier.ADV):
            self.assertEqual(rolled["tiers"][tier.value]["next_eligible_at"],
                             reports[0]["result"]["maintenance_state"]["tiers"][tier.value]["next_eligible_at"])

    def test_stop_after_consuming_input_prevents_further_input(self):
        original_tap = support.GuardedRecruitmentRuntime.tap
        def tap(runtime, source, **kwargs):
            original_tap(runtime, source, **kwargs)
            if runtime.input_count == 2:
                self.stop.set()
        reports = []
        with patch.object(support.GuardedRecruitmentRuntime, "tap", tap):
            self.serve(reports.append)
        self.assertEqual(self.runtimes[0].input_count, 2)
        self.assertEqual(reports[-1]["status"], "blocked")
        self.assertTrue(self.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_service_lease().owner_instance_id)

    def test_unresolved_consumption_blocks_restart_without_retry(self):
        self.unresolved = True
        reports = []
        self.serve(lambda report: (reports.append(report), self.stop.set()))
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(len(self.runtimes[0].calls), 3)
        run_budget = self.state._db.execute(
            "SELECT consumed_inputs, consumed_actions FROM runs "
            "WHERE flow_id=? ORDER BY claimed_at_utc DESC LIMIT 1",
            (RECRUITMENT_FLOW_ID,),
        ).fetchone()
        self.assertEqual(
            (run_budget["consumed_inputs"], run_budget["consumed_actions"]),
            (3, 1),
        )
        self.assertTrue(self.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertIsNone(self.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc)
        self.stop.stopped = False
        self.serve(lambda report: (reports.append(report), self.stop.set()))
        self.assertEqual(reports[-1]["status"], "paused")
        self.assertEqual(len(self.runtimes), 1)

    def test_popup_navigation_does_not_advance_unresolved_next_due(self):
        identity = SchedulerIdentity(
            "account",
            "server",
            recruitment_reset(self.stop.now),
            MAINTENANCE_TASK_ID,
        )
        maintenance = NoahMaintenanceState.for_identity(identity)
        completed_at = self.stop.now
        completed = {
            "status": "completed",
            "terminal_home_verified": True,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "time_basis": "utc",
            "completed_at_utc": completed_at,
            "maintenance_state": json.loads(maintenance.to_json()),
            "recruitment_transport_count": 1,
            "recruitment_action_count": 1,
            "contextual_popup_recoveries": [
                {
                    "source_sha256": "a" * 64,
                    "settled_sha256": "b" * 64,
                    "source_context": "recruit-result-advanced",
                    "dismissed": True,
                    "popup_absent": True,
                    "resume_ready": True,
                    "input_count": 1,
                    "reason": "popup_dismissed_resume_ready",
                }
            ],
        }
        next_due = recruitment_next_due(
            completed, identity, started_at=completed_at - 1
        )
        self.assertEqual(next_due, completed_at + 30)

        unresolved = dict(
            completed,
            status="unresolved",
            terminal_home_verified=False,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        with self.assertRaises(ValueError):
            recruitment_next_due(unresolved, identity, started_at=completed_at - 1)
        self.assertEqual(next_due, completed_at + 30)

    def test_idle_stop_releases_owner_and_emergency_stop_prevents_input(self):
        self.state.update_schedule(RECRUITMENT_FLOW_ID, next_due_at_utc=self.stop.now + 600)
        self.stop.on_wait = self.stop.set
        self.serve(lambda report: None)
        self.assertEqual(len(self.runtimes), 0)
        with boundary.RuntimeInputLock(owner="second", invocation_id="after-stop"):
            pass
        self.stop.on_wait = None
        self.stop.stopped = False
        self.state.update_schedule(RECRUITMENT_FLOW_ID, next_due_at_utc=None)
        actual = self.runner
        def stop_before_native(identity, previous, checkpoint):
            self.state.set_service_enabled(False)
            return actual(identity, previous, checkpoint)
        self.service.recruitment_runner = stop_before_native
        reports = []
        self.serve(reports.append)
        self.assertEqual(len(self.runtimes), 0)
        self.assertTrue(self.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertEqual(reports[-1]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
