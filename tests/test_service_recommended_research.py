from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from scripts import recommended_research_bluestacks as native_route

from automation_service.native_execution import NativeRouteOutcome
from automation_service.recommended_research import (
    FLOW_ID,
    PROFILE_ID,
    MAX_ACTIONS,
    MAX_INPUTS,
    OBSERVATION_INTERVAL_SECONDS,
    PRODUCT_ID,
    PRODUCT_REVISION,
    RecommendedResearchRunner,
)
from automation_service.recruitment import recruitment_reset
from tasks.runtime_identity import BLUESTACKS_SERIAL, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity


NOW = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc).timestamp()
_FRAME = {"frame_path": "frames/home.png", "frame_sha256": "a" * 64}
_RESOURCES = ("food", "wood", "steel", "gas")


def _identity() -> SchedulerIdentity:
    binding = resource_fixed_runtime_binding()
    return SchedulerIdentity(
        account_id=binding.account_id,
        server_id=binding.server_id,
        reset_id=recruitment_reset(NOW),
        task_id=PRODUCT_ID,
    )


def _result(status: str, **overrides):
    result = {
        "status": status,
        "reason": "synthetic-native-result",
        "terminal_home_verified": True,
        "terminal_home_frame": dict(_FRAME),
        "terminal_home_frame_sha256": _FRAME["frame_sha256"],
        "research_transport_calls": 0,
        "committed_action_count": 0,
        "total_action_count": 0,
        "effect_reconciliation_required": False,
        "identical_retry_denied": status == "already_complete",
    }
    result.update(overrides)
    return result


def _selection_evidence():
    return {
        "recommendation_position": 1,
        "queue2_activate_tapped": False,
        "prerequisites_known": True,
        "prerequisites_met": True,
        "prerequisite_evidence": ["research-center-lv-24"],
        "requirements_scrolled": True,
        "research_start_visible": True,
        "control_class": "RESEARCH_START",
        "research_now_diamonds": 714,
        "research_now_target_identity": "research-now-diamonds",
        "research_now_tapped": False,
        "overlay_state": "none_observed",
    }


def _outcome(result, *, failure=None, partial=None, input_count=5, session_count=None, runtime_count=None):
    return NativeRouteOutcome(
        flow_id=FLOW_ID,
        native_result=result,
        partial_result=partial,
        failure=failure,
        invocation_id="native-invocation-1",
        session_directory="run/native-invocation-1",
        startup_recovery=None,
        input_count=input_count,
        session_input_count=input_count if session_count is None else session_count,
        runtime_input_count=input_count if runtime_count is None else runtime_count,
        accounting_verified=True,
    )


class _HeldInputLock:
    owner = "automation-service"
    invocation_id = "held-input-owner-1"
    held = True

    def assert_held(self, owner, invocation_id):
        if owner != self.owner or invocation_id != self.invocation_id or not self.held:
            raise AssertionError("input lock was not held by the expected invocation")


class _FakeNativeBoundary:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        request.runtime_input_lock.assert_held(
            request.runtime_input_lock.owner, request.runtime_input_lock.invocation_id
        )
        request.validate_identity()
        return self.outcomes.pop(0)


class RecommendedResearchServiceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identity = _identity()
        self.lock = _HeldInputLock()
        self.checkpoints = []
        self.runner_kwargs = dict(
            output_directory=Path(self.temp.name),
            serial=BLUESTACKS_SERIAL,
            utc_clock=lambda: NOW,
            monotonic_clock=lambda: 7.0,
            settle_seconds=0.0,
        )

    def _run(self, outcomes, *, previous_reset_id=None, occurrence="research-occurrence-1"):
        boundary = _FakeNativeBoundary(outcomes)
        runner = RecommendedResearchRunner(native=boundary, **self.runner_kwargs)
        result = runner(
            self.identity,
            previous_reset_id,
            lambda: self.checkpoints.append("checkpoint"),
            runtime_input_lock=self.lock,
            occurrence_key=occurrence,
        )
        return result, boundary

    def test_missing_native_binding_blocks_without_claiming_effect(self):
        runner = RecommendedResearchRunner(native=None, **self.runner_kwargs)
        result = runner(
            self.identity,
            None,
            lambda: self.checkpoints.append("checkpoint"),
            runtime_input_lock=self.lock,
            occurrence_key="research-occurrence-1",
        )
        self.assertEqual(result.outcome.value, "blocked")
        self.assertFalse(result.verified)
        self.assertFalse(result.unresolved_action)

    def test_canonical_request_forwards_identity_limits_and_held_owner(self):
        home = SimpleNamespace(path=Path("run/native/frames/home.png"), sha256="a" * 64, frame=object())
        context = SimpleNamespace(
            runtime=SimpleNamespace(session=Path("run/native"), capture=lambda label: home),
            session=SimpleNamespace(observe=lambda capture, label: capture(label)),
            is_clean_home=lambda frame: frame is home.frame,
            utc_clock=lambda: NOW,
            accounting=lambda: SimpleNamespace(
                input_count=5, session_input_count=5, runtime_input_count=5, verified=True,
            ),
        )
        native = native_route._normal_result(
            context, status="completed", reason="paired_debit_verified",
            terminal_home_verified=True, start_calls=1,
            completed=True,
            start_semantically_verified=True,
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            committed_action_count=1,
            effect_reconciliation_required=False,
            identical_retry_denied=True,
            first_recommendation_identity="troop-load-ii",
            active_technology="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            remaining_seconds=3_600,
            research_duration_seconds=21_413,
            exact_resource_costs={key: 0 for key in _RESOURCES},
            exact_resource_prebalances={"food": 3_003_682, "wood": 757_050, "steel": 129_702, "gas": 47_775},
            exact_resource_balances={"food": 3_003_682, "wood": 757_050, "steel": 129_702, "gas": 47_775},
        )
        result, boundary = self._run([_outcome(native)])
        self.assertEqual(result.outcome.value, "complete_for_reset")
        self.assertTrue(result.verified)
        self.assertEqual(result.next_eligible_at, NOW + 3_600)
        self.assertEqual(len(boundary.requests), 1)
        request = boundary.requests[0]
        self.assertEqual(
            (request.flow_id, request.product_id, request.product_revision, request.runtime_profile_id),
            (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID),
        )
        self.assertEqual((request.max_inputs, request.max_actions), (MAX_INPUTS, MAX_ACTIONS))
        self.assertIs(request.runtime_input_lock, self.lock)
        self.assertEqual(request.occurrence_key, "research-occurrence-1")
        self.assertEqual(request.arguments, {})
        self.assertGreaterEqual(len(self.checkpoints), 2)

    def test_busy_timer_and_exact_shortage_use_distinct_normal_deferrals(self):
        busy = _result(
            "deferred",
            queue1_state="busy",
            queue1_remaining_seconds=731,
            identical_retry_denied=False,
        )
        busy_result, _ = self._run([_outcome(busy)])
        self.assertEqual(busy_result.outcome.value, "deferred")
        self.assertEqual(busy_result.next_eligible_at, NOW + 731)

        costs = {"food": 100, "wood": 20, "steel": 0, "gas": 0}
        balances = {"food": 20, "wood": 80, "steel": 10, "gas": 10}
        shortage = _result(
            "deferred",
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
            shortages=[{"resource": "food", "shortage": 80}],
            exact_resource_costs=costs,
            exact_resource_balances=balances,
            first_recommendation_identity="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            research_duration_seconds=21_413,
            identical_retry_denied=False,
        )
        shortage_result, _ = self._run([_outcome(shortage)])
        self.assertEqual(shortage_result.outcome.value, "deferred")
        self.assertEqual(shortage_result.next_eligible_at, NOW + OBSERVATION_INTERVAL_SECONDS)
        self.assertEqual(shortage_result.observed_progress["shortages"], [{"resource": "food", "shortage": 80}])

    def test_unknown_partial_and_restart_confirmation_never_repeat_start(self):
        partial = _result(
            "unresolved",
            reason="research_start_successor_or_paired_debit_unknown",
            research_transport_calls=1,
            committed_action_count=0,
            total_action_count=1,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        unresolved, first_boundary = self._run([
            _outcome({}, failure="native driver lost successor", partial=partial)
        ])
        self.assertEqual(unresolved.outcome.value, "reconciliation_required")
        self.assertTrue(unresolved.unresolved_action)
        self.assertEqual(unresolved.action_count, 1)
        self.assertEqual(first_boundary.requests[0].max_actions, 1)

        already = _result("already_complete", already_confirmed=True, identical_retry_denied=True)
        restarted, second_boundary = self._run([_outcome(already, input_count=0)])
        self.assertEqual(restarted.outcome.value, "already_complete")
        self.assertEqual(restarted.action_count, 0)
        self.assertEqual(restarted.next_eligible_at, self._reset_deadline())
        self.assertEqual(second_boundary.requests[0].max_actions, 1)

    def test_semantic_start_and_unknown_transport_accounting_preserve_partial_progress(self):
        partial = _result(
            "unresolved",
            research_transport_calls=1,
            committed_action_count=1,
            total_action_count=1,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
            start_semantically_verified=True,
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            first_recommendation_identity="troop-load-ii",
            active_technology="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            remaining_seconds=3_600,
            research_duration_seconds=21_413,
            exact_resource_costs={key: 0 for key in _RESOURCES},
            exact_resource_prebalances={"food": 100, "wood": 80, "steel": 50, "gas": 40},
            exact_resource_balances={"food": 100, "wood": 80, "steel": 50, "gas": 40},
        )
        result, _ = self._run([
            _outcome({}, failure="native cleanup failed after active research proof", partial=partial)
        ])
        self.assertEqual(result.outcome.value, "reconciliation_required")
        self.assertEqual(result.action_count, 1)
        native = result.consequence["native_result"]
        self.assertEqual(native["committed_action_count"], 1)
        self.assertTrue(native["start_semantically_verified"])
        self.assertTrue(native["identical_retry_denied"])

        malformed = _result(
            "unresolved",
            research_transport_calls="unknown",
            committed_action_count=0,
            total_action_count=0,
            effect_reconciliation_required=False,
        )
        ambiguous, _ = self._run([_outcome(malformed, input_count=0)])
        self.assertEqual(ambiguous.outcome.value, "reconciliation_required")
        self.assertEqual(ambiguous.action_count, 1)
        self.assertTrue(ambiguous.unresolved_action)
        missing_result, _ = self._run([_outcome({}, input_count=2)])
        self.assertEqual(missing_result.outcome.value, "reconciliation_required")
        self.assertEqual(missing_result.action_count, 1)
        self.assertTrue(missing_result.unresolved_action)


    def test_inconsistent_accounting_and_missing_terminal_home_fail_closed(self):
        completed = _result(
            "completed",
            completed=True,
            start_semantically_verified=True,
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            research_transport_calls=1,
            committed_action_count=1,
            effect_reconciliation_required=False,
            identical_retry_denied=True,
            first_recommendation_identity="troop-load-ii",
            active_technology="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            remaining_seconds=3_600,
            research_duration_seconds=21_413,
            exact_resource_costs={key: 0 for key in _RESOURCES},
            exact_resource_prebalances={key: 100 for key in _RESOURCES},
            exact_resource_balances={key: 100 for key in _RESOURCES},
        )
        mismatched, _ = self._run([_outcome(completed, runtime_count=6)])
        self.assertEqual(mismatched.outcome.value, "reconciliation_required")
        self.assertTrue(mismatched.unresolved_action)

        missing_resource = dict(completed)
        missing_resource["exact_resource_costs"] = {"food": 0}
        malformed_costs, _ = self._run([_outcome(missing_resource)])

        queue2 = dict(completed)
        queue2["queue2_activate_tapped"] = True
        rejected_queue2, _ = self._run([_outcome(queue2)])
        self.assertEqual(rejected_queue2.outcome.value, "reconciliation_required")
        self.assertEqual(malformed_costs.outcome.value, "reconciliation_required")

        wrong_shortage = _result(
            "deferred",
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
            shortages=[{"resource": "food", "shortage": 79}],
            exact_resource_costs={"food": 100, "wood": 0, "steel": 0, "gas": 0},
            exact_resource_balances={"food": 20, "wood": 10, "steel": 10, "gas": 10},
            first_recommendation_identity="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            research_duration_seconds=21_413,
            identical_retry_denied=False,
        )
        rejected_shortage, _ = self._run([_outcome(wrong_shortage, input_count=0)])
        self.assertEqual(rejected_shortage.outcome.value, "blocked")
        self.assertIsNone(rejected_shortage.next_eligible_at)

        omitted_shortage = _result(
            "deferred",
            **_selection_evidence(),
            queue1_state="idle",
            queue1_remaining_seconds=None,
            observation_interval_seconds=OBSERVATION_INTERVAL_SECONDS,
            shortages=[{"resource": "food", "shortage": 80}],
            exact_resource_costs={"food": 100, "wood": 100, "steel": 0, "gas": 0},
            exact_resource_balances={"food": 20, "wood": 80, "steel": 10, "gas": 10},
            first_recommendation_identity="troop-load-ii",
            target_identity="recommended-research:troop-load-ii:detail-research-button",
            research_duration_seconds=21_413,
            identical_retry_denied=False,
        )
        omitted, _ = self._run([_outcome(omitted_shortage, input_count=0)])
        self.assertEqual(omitted.outcome.value, "blocked")
        self.assertIsNone(omitted.next_eligible_at)

        no_home = _result("deferred", queue1_state="busy", queue1_remaining_seconds=20)
        no_home["terminal_home_verified"] = False
        no_home["terminal_home_frame"] = None
        no_home["terminal_home_frame_sha256"] = None
        blocked, _ = self._run([_outcome(no_home, input_count=0)])
        self.assertEqual(blocked.outcome.value, "blocked")
        self.assertIsNone(blocked.next_eligible_at)

    def _reset_deadline(self):
        from tasks.runtime_identity import derive_static_utc_reset

        window = derive_static_utc_reset(datetime.fromtimestamp(NOW, timezone.utc))
        return datetime.fromisoformat(window.reset_deadline_text.replace("Z", "+00:00")).timestamp()


if __name__ == "__main__":
    unittest.main()
