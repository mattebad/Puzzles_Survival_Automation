from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from automation_service import alliance_help as adapter
from automation_service.contracts import NormalizedOutcome
from automation_service.native_execution import NativeRouteOutcome
from automation_service.recruitment import recruitment_reset
from safe_action_core.store import LeaseError, SafetyStore
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from tests.test_alliance_help_bluestacks import _run_replay_route
from tests.test_service_alliance_help import FakeRuntimeInputLock


NOW = 1_800_000_000.0


class _ReplayBoundary:
    flow_id = adapter.FLOW_ID
    product_id = adapter.PRODUCT_ID
    product_revision = adapter.PRODUCT_REVISION
    runtime_profile_id = adapter.PROFILE_ID
    max_inputs = adapter.MAX_INPUTS
    max_actions = adapter.MAX_ACTIONS

    def __init__(self, result, session, runtime):
        self.result, self.session, self.runtime = result, session, runtime

    def run(self, request):
        request.validate_identity()
        return NativeRouteOutcome(
            flow_id=self.flow_id, native_result=self.result, partial_result=None,
            failure=None, invocation_id=FakeRuntimeInputLock.invocation_id,
            session_directory=str(self.session.session_directory), startup_recovery=None,
            input_count=self.runtime.input_count,
            session_input_count=self.session.input_count,
            runtime_input_count=self.runtime.input_count,
            accounting_verified=self.result['accounting_verified'])


def _adapt(root, raw, session, runtime):
    backend = derive_resource_runtime_identity(resource_fixed_runtime_binding(),
        datetime.fromtimestamp(NOW, timezone.utc))
    identity = SchedulerIdentity(backend.account_id, backend.server_id,
        recruitment_reset(NOW), adapter.PRODUCT_ID)
    runner = adapter.AllianceHelpRunner(native=_ReplayBoundary(raw, session, runtime),
        output_directory=root / 'adapter', utc_clock=lambda: NOW,
        monotonic_clock=runtime.clock.now, settle_seconds=0)
    result = runner(identity, None, lambda: None,
        runtime_input_lock=FakeRuntimeInputLock(), occurrence_key=raw['occurrence_key'])
    return result, identity


class BatchBReviewRegressions(unittest.TestCase):
    def test_actual_native_dispatch_delayed_success_projects_partial_and_complete(self):
        for count in (1, 10):
            with self.subTest(requests=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw, blocked, session, runtime = _run_replay_route(root,
                    requests=count, native_dispatch=True, delayed_success=True)
                self.assertIsInstance(runtime, LocalBlueStacksRuntime)
                self.assertFalse(blocked)
                self.assertEqual(runtime.help_taps, count)
                self.assertEqual(raw['confirmed_request_count'], count)
                self.assertEqual(raw['help_transport_calls'], count)
                self.assertEqual(len(raw['help_dispatch_evidence']), count)
                self.assertTrue(raw['accounting_verified'])
                events = [json.loads(line) for line in runtime.events.read_text().splitlines()]
                # The emitted canonical keys must be the actual native dispatch keys.
                dispatches = [event for event in events if event['type'] == 'dispatch']
                for dispatch in raw['help_dispatch_evidence']:
                    self.assertIsInstance(dispatch['action_key'], str)
                    self.assertIn(dispatch['action_key'], runtime.action_keys)
                    self.assertTrue(any(event['action_key'] == dispatch['action_key']
                        and event['source_sha256'] == dispatch['immediate_before_sha256']
                        and event['target_identity'] == dispatch['target_identity']
                        and event['target_roi'] == list(dispatch['target_roi'])
                        for event in dispatches))
                    self.assertIn((dispatch['immediate_before_sha256'],
                        dispatch['target_identity'], dispatch['target_roi']), runtime.frame_actions)
                self.assertTrue(events)
                result, identity = _adapt(root, raw, session, runtime)
                evidence = result['request_actions'][0]['request_result_evidence']
                self.assertEqual(len(evidence), 3)
                self.assertFalse(evidence[0]['selected_request_absent'])
                self.assertTrue(evidence[1]['selected_request_absent'])
                self.assertTrue(evidence[1]['success_message'])
                self.assertTrue(evidence[2]['selected_request_absent'])
                self.assertEqual(len(result['request_actions'][0]['request_result_frames']), 3)
                outcome = adapter.normalize_alliance_help_result(result, identity, NOW)
                self.assertEqual(outcome.outcome, NormalizedOutcome.COMPLETE_FOR_RESET
                    if count == 10 else NormalizedOutcome.DEFERRED)
                due = adapter.alliance_help_next_due(result, identity, NOW)
                self.assertEqual(due, datetime.fromisoformat(raw['backend_identity'][
                    'reset_deadline_utc'].replace('Z', '+00:00')).timestamp()
                    if count == 10 else NOW + adapter.OBSERVATION_RETRY_SECONDS)
                for field, value in (('selected_request_absent', False),
                                     ('daily_alliance_coin_balance', 0),
                                     ('daily_alliance_coin_limit', 60000)):
                    corrupt = deepcopy(result)
                    corrupt['request_actions'][0]['request_result_evidence'][-1][field] = value
                    with self.assertRaises(ValueError):
                        adapter.alliance_help_next_due(corrupt, identity, NOW)

    def test_native_unknown_persists_without_retry_or_recurrence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'actions.sqlite3'
            raw, blocked, session, runtime = _run_replay_route(root / 'first', requests=1,
                native_dispatch=True, suppress_effects=True, store_path=db)
            self.assertTrue(blocked)
            self.assertEqual(runtime.help_taps, 1)
            self.assertEqual(raw['confirmed_request_count'], 0)
            self.assertTrue(raw['identical_retry_denied'])
            result, identity = _adapt(root, raw, session, runtime)
            outcome = adapter.normalize_alliance_help_result(result, identity, NOW)
            self.assertEqual(outcome.outcome, NormalizedOutcome.RECONCILIATION_REQUIRED)
            self.assertIsNone(outcome.next_eligible_at)
            inspection = SafetyStore(db)
            try:
                preserved = inspection.list_actions_for_task(adapter.FLOW_ID)
                self.assertTrue(inspection.has_action_block())
            finally:
                inspection.close()
            # Canonical UNKNOWN prevents fresh ownership before any new native
            # visit; the fixture must not bypass that earlier safety boundary.
            with self.assertRaises(LeaseError):
                _run_replay_route(root / 'restarted', requests=1, native_dispatch=True, store_path=db)
            inspection = SafetyStore(db)
            try:
                self.assertTrue(inspection.has_action_block())
                self.assertEqual(inspection.list_actions_for_task(adapter.FLOW_ID), preserved)
            finally:
                inspection.close()
