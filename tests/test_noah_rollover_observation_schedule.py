from contextlib import closing
from dataclasses import replace
import json
import unittest

from automation_service.recruitment import recruitment_next_due, recruitment_reset
from automation_service.registry import RECRUITMENT_FLOW_ID
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from tasks.noahs_tavern_recruit import RecruitTier
from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID, NoahMaintenanceState, PersistedTierState
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support import recruitment_service as fixtures


class ObservationScheduleTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.RecruitmentServiceCase('runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.now = self.case.stop.now
        self.identity = SchedulerIdentity('account', 'server', recruitment_reset(self.now), MAINTENANCE_TASK_ID)
        self.maintenance = NoahMaintenanceState.for_identity(self.identity)
        self.maintenance.basic_daily_count = 0
        self.maintenance.tiers[RecruitTier.BASIC] = PersistedTierState(5, None, 600, 'reset_rollover')
        self.maintenance.tiers[RecruitTier.INT] = PersistedTierState(0, self.now + 86400, 86400, 'deferred')
        self.maintenance.tiers[RecruitTier.ADV] = PersistedTierState(0, self.now + 172800, 172800, 'deferred')
        with closing(SafetyStore(self.case.maintenance_path)) as store:
            repo = SQLiteSchedulerInvocationRepository(store)
            old = repo.get(self.identity)
            progress = {'basic_daily_count': 0, 'tiers': json.loads(self.maintenance.to_json())['tiers'],
                        'terminal_home_verified': True}
            repo.save(replace(old, status='deferred', unresolved_action=False,
                              observed_progress_json=json.dumps(progress)), self.now)
        self.case.state._db.execute('UPDATE flow_state SET reset_id=?, last_completed_at_utc=?, next_due_at_utc=? WHERE flow_id=?',
            (self.identity.reset_id, self.now - 900, self.now + 7200, RECRUITMENT_FLOW_ID))

    def test_due_policy_preserves_other_tier_deadlines_and_exhaustion(self):
        def due(state):
            return recruitment_next_due({'status': 'completed', 'terminal_home_verified': True,
                'time_basis': 'utc', 'completed_at_utc': self.now,
                'maintenance_state': json.loads(state.to_json())}, self.identity, self.now)
        self.assertEqual(due(self.maintenance), self.now + 600)
        self.maintenance.basic_daily_count = 5
        self.assertEqual(due(self.maintenance), self.now + 600)
        self.maintenance.tiers[RecruitTier.BASIC] = PersistedTierState(0, None, 600, 'already_complete')
        expected = min((int(self.now // 86400) + 1) * 86400, self.now + 86400, self.now + 172800)
        self.assertEqual(due(self.maintenance), expected)

    def test_reconciliation_claims_before_startup_and_route(self):
        events = []
        runner = self.case.runner
        class Runner:
            observation_deadline = runner.observation_deadline
            def __call__(inner, identity, previous, checkpoint):
                events.append('route')
                raise RuntimeError('offline test stop')
        def startup(flow, run_id, owner, checkpoint):
            self.assertIsNotNone(self.case.state.get_run(run_id))
            events.append('startup')
            return {'system_launch_count': 0, 'game_input_count': 0, 'status': 'already_foreground'}
        self.case.service.recruitment_runner = Runner()
        self.case.service.application_startup = startup
        self.case.serve(lambda report: self.case.stop.set())
        self.assertEqual(events, ['startup', 'route'])
        self.assertEqual(self.case.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc, self.now - 300)

    def test_before_deadline_no_route_or_startup(self):
        self.case.state._db.execute('UPDATE flow_state SET last_completed_at_utc=? WHERE flow_id=?',
                                    (self.now - 300, RECRUITMENT_FLOW_ID))
        self.case.service.application_startup = lambda *args: self.fail('startup before claim')
        self.case.stop.on_wait = self.case.stop.set
        self.case.serve(lambda report: self.fail(str(report)))
        self.assertEqual(self.case.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc, self.now + 300)
        self.assertEqual(self.case.runtimes, [])

    def test_zero_work_pass_advances_observation_deadline(self):
        runner = self.case.runner
        calls = []
        maintenance = self.maintenance
        class Runner:
            observation_deadline = runner.observation_deadline
            def __call__(inner, identity, previous, checkpoint):
                calls.append(self.case.stop.now)
                return {'status': 'completed', 'terminal_home_verified': True, 'time_basis': 'utc',
                        'completed_at_utc': self.case.stop.now,
                        'maintenance_state': json.loads(maintenance.to_json()),
                        'total_input_count': 0, 'recruitment_dispatch_count': 0,
                        'actions_completed': 0}
        self.case.service.recruitment_runner = Runner()
        self.case.stop.on_wait = self.case.stop.set
        self.case.serve(lambda report: None)
        self.assertEqual(calls, [self.now])
        self.assertEqual(self.case.state.get_flow(RECRUITMENT_FLOW_ID).next_due_at_utc, self.now + 600)

    def test_snapshot_rejects_missing_identity_and_completed_basic(self):
        deadline = self.case.runner.observation_deadline
        self.assertEqual(deadline(self.identity, self.now - 900, self.now), self.now - 300)
        self.assertIsNone(deadline(replace(self.identity, reset_id='other'), self.now - 900, self.now))
        self.assertIsNone(deadline(self.identity, self.now + 1, self.now))
        with closing(SafetyStore(self.case.maintenance_path)) as store:
            repo = SQLiteSchedulerInvocationRepository(store)
            old = repo.get(self.identity)
            progress = json.loads(old.observed_progress_json)
            progress['tiers'][RecruitTier.BASIC.value]['attempts_remaining'] = 0
            repo.save(replace(old, observed_progress_json=json.dumps(progress)), self.now)
        self.assertIsNone(deadline(self.identity, self.now - 900, self.now))

    def test_schedule_cas_rejects_conflicts(self):
        state = self.case.state
        flow = state.get_flow(RECRUITMENT_FLOW_ID)
        args = dict(next_due_at_utc=self.now, expected_row_version=flow.row_version,
                    expected_generation=flow.generation, expected_reset_id=flow.reset_id,
                    expected_next_due_at_utc=flow.next_due_at_utc, require_enabled_unblocked=True)
        for key, value in [('expected_row_version', flow.row_version + 1),
                           ('expected_generation', flow.generation + 1),
                           ('expected_reset_id', 'other'), ('expected_next_due_at_utc', self.now)]:
            self.assertIsNone(state.update_schedule(RECRUITMENT_FLOW_ID, **dict(args, **{key: value})))
        state.block_flow(RECRUITMENT_FLOW_ID, 'test')
        self.assertIsNone(state.update_schedule(RECRUITMENT_FLOW_ID, **args))
