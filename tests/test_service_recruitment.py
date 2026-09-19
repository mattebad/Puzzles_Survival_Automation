"""Guarded service -> native runner -> real controller, with no device transport."""
from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import replace
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation_service.recruitment import (
    RecruitmentRunner,
    recruitment_next_due,
    recruitment_reset,
)
from automation_service.registry import RECRUITMENT_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from scripts import navigation_development_boundary as boundary
from scripts import noahs_tavern_recruit_bluestacks as native
from tasks.noahs_tavern_recruit import RecruitTier
from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID, NoahMaintenanceState, PersistedTierState
from tasks.noahs_tavern_recruit_runtime import NoahTavernRecruitRuntimeController
from tasks.scheduler_task_result import SchedulerIdentity
from tests.test_noahs_tavern_navigation import ScriptedTavernRuntime, _observation
from tests.test_noahs_tavern_recruit import NoahFixtures


class VirtualStop:
    def __init__(self, now):
        self.now = now
        self.stopped = False
        self.waits = []
        self.on_wait = None

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        if self.stopped:
            return True
        self.waits.append(seconds)
        self.now += seconds
        if self.on_wait:
            self.on_wait()
        return self.stopped


class GuardedRecruitmentRuntime(ScriptedTavernRuntime):
    def __init__(self, session, *, unresolved=False):
        super().__init__(["HOME_BASE", "BEFORE", "RESULT", "AFTER", "HOME_BASE"])
        self.session = session
        session.mkdir()
        self.events = session / "events.jsonl"
        self.max_inputs = 12
        self.input_count = 0
        self.checkpoint = None
        self.fixture = NoahFixtures()
        self.unresolved = unresolved

    def capture(self, label):
        if self.checkpoint:
            self.checkpoint()
        return super().capture(label)

    def tap(self, source, **kwargs):
        if self.checkpoint:
            self.checkpoint()
        self.input_count += 1
        super().tap(source, **kwargs)

    def back(self, source, **kwargs):
        if self.checkpoint:
            self.checkpoint()
        self.input_count += 1
        super().back(source, **kwargs)

    def recognizer(self, frame, *, captured_monotonic=None, stale=False):
        screen = self._screen()
        if screen == "HOME_BASE":
            return _observation(screen, captured_monotonic)
        before = self.fixture.tavern()
        if screen == "BEFORE":
            obs = before
        elif screen == "RESULT":
            obs = self.fixture.result()
        else:
            obs = self.fixture.after(before)
            if self.unresolved:
                obs = replace(obs, recognized=False)
            obs = replace(obs, tiers=tuple(
                replace(item, next_eligible_timestamp=captured_monotonic + item.cooldown_duration_seconds)
                if item.cooldown_active and captured_monotonic is not None else item
                for item in obs.tiers
            ))
        # Int/Advanced are cooling independently. Fresh Basic successor is real
        # controller input; the controller, not this fixture, increments its count.
        return replace(obs, captured_monotonic=captured_monotonic)


class ServiceRecruitmentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "input-lock.sqlite3"))
        self.stop = VirtualStop(1_800_000_000.0)
        self.state_path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.state_path))
        self.maintenance_path = self.root / "maintenance.sqlite3"
        self.runner = RecruitmentRunner(adb="FORBIDDEN", serial="offline-guard", output_directory=self.root,
                                        maintenance_path=self.maintenance_path, utc_clock=lambda: self.stop.now)
        self.service = AutomationService(mode="supervised", state=self.state, recruitment_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(RECRUITMENT_FLOW_ID, True)
        identity = SchedulerIdentity("account", "server", recruitment_reset(self.stop.now), MAINTENANCE_TASK_ID)
        maintenance = NoahMaintenanceState.for_identity(identity)
        maintenance.tiers[RecruitTier.INT] = PersistedTierState(0, self.stop.now + 86400, 86400, "deferred")
        maintenance.tiers[RecruitTier.ADV] = PersistedTierState(0, self.stop.now + 172800, 172800, "deferred")
        with closing(SafetyStore(self.maintenance_path)) as store:
            controller = NoahTavernRecruitRuntimeController(maintenance_state=maintenance,
                scheduler_identity=identity, repository=SQLiteSchedulerInvocationRepository(store))
            controller.persist_maintenance_state(now=self.stop.now)
        self.runtimes = []
        self.unresolved = False

        def connect(**kwargs):
            runtime = GuardedRecruitmentRuntime(self.root / f"session-{len(self.runtimes)}", unresolved=self.unresolved)
            self.runtimes.append(runtime)
            return runtime

        self.stack.enter_context(patch.object(native.LocalBlueStacksRuntime, "connect", side_effect=connect))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("live transport forbidden")))
        self.stack.enter_context(patch.object(native, "recognize_home_zoom_source", return_value=(True, {})))
        self.stack.enter_context(patch(
            "scripts.startup_recovery.recognize_reset_popup",
            return_value={"recognized": False, "reason": "not_recognized"},
        ))
        self.stack.enter_context(patch.object(native, "recognize_noahs_tavern_frame",
            side_effect=lambda *a, **k: self.runtimes[-1].recognizer(*a, **k)))
        step = SimpleNamespace(disposition=SimpleNamespace(value="bind"), reason="offline-home",
                               localization=SimpleNamespace(recognized=False, zoom_identity=SimpleNamespace(value="fully_zoomed_out")))
        self.stack.enter_context(patch("scripts.home_atlas_bluestacks.BlueStacksLocalizeFirstHomeDriver",
                                      return_value=SimpleNamespace(observe=lambda frame: step)))
        self.stack.enter_context(patch.object(native.NoahTavernNavigationCanaryRoute, "_atlas_binding",
                                              return_value=(100, 300, 260, 470)))
        route_type = native.NoahTavernIntegratedRoute

        def route(runtime, **kwargs):
            kwargs["recognizer"] = runtime.recognizer
            kwargs["post_input_delay"] = 0
            return route_type(runtime, **kwargs)

        self.stack.enter_context(patch.object(native, "NoahTavernIntegratedRoute", side_effect=route))

    def serve(self, emit):
        self.service.serve(account_id="account", server_id="server", stop=self.stop,
                           emit=emit, clock=lambda: self.stop.now)

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
        self.assertEqual(due, self.stop.now + 600)
        run_budget = self.state._db.execute(
            "SELECT max_inputs, max_actions FROM runs "
            "WHERE flow_id=? ORDER BY claimed_at_utc DESC LIMIT 1",
            (RECRUITMENT_FLOW_ID,),
        ).fetchone()
        self.assertEqual((run_budget["max_inputs"], run_budget["max_actions"]), (12, 3))
        self.assertEqual(self.runtimes[0]._screen(), "HOME_BASE")
        self.assertEqual([kind for kind, _ in self.runtimes[0].calls], ["tap", "tap", "tap", "back"])
        # Restart reads persisted due state; no new route until the deadline.
        self.stop.stopped = False
        with BotStateManager(self.state_path) as restarted:
            self.service = AutomationService(mode="supervised", state=restarted, recruitment_runner=self.runner)
            self.serve(emit)
        self.assertEqual(len(self.runtimes), 2)
        self.assertEqual(sum(self.stop.waits), 600)
        self.assertTrue(all(0 < delay <= 30 for delay in self.stop.waits))
        self.assertEqual(reports[1]["result"]["maintenance_state"]["basic_daily_count"], 2)
        self.assertEqual(self.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc, due + 600)
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
        original_tap = GuardedRecruitmentRuntime.tap
        def tap(runtime, source, **kwargs):
            original_tap(runtime, source, **kwargs)
            if runtime.input_count == 2:
                self.stop.set()
        reports = []
        with patch.object(GuardedRecruitmentRuntime, "tap", tap):
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
