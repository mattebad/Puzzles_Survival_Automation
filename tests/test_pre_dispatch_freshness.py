"""Deterministic freshness, OCR binding, and bounded pre-dispatch tests."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safe_action_core import (
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
    ocr_reuse_denial,
)

PROFILE = "pns-blissos-poc-virgl-800x1280-v1"
ROI_HASH = "d" * 64


class Clock:
    def __init__(self, value: float):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def observation(**changes) -> Observation:
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity="home-quest-entry",
        target_roi=(250, 1130, 410, 1280),
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="QUEST",
        critical_roi_hashes=(("semantic_target", ROI_HASH),),
        ocr_result_frame_sha256="a" * 64,
    )
    return replace(base, **changes)


def request(obs: Observation | None = None, **changes) -> PolicyRequest:
    base = PolicyRequest(
        action_id="freshness-action",
        action_key="freshness-key",
        task_id="MVP-QUEST-TO-CLAIM",
        task_mode="supervised_validation",
        semantic_action="NAVIGATE_HOME_TO_QUEST",
        expected_runtime_profile_id=PROFILE,
        observation=obs or observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=3.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
    )
    return replace(base, **changes)


class FreshnessPolicyCase(unittest.TestCase):
    def test_capture_age_begins_at_successful_capture_completion(self):
        completed = observation(capture_completed_monotonic=999.9)
        self.assertTrue(CentralPolicy().evaluate(request(completed)).authorized)
        command_started = replace(completed, capture_completed_monotonic=996.0)
        self.assertEqual(CentralPolicy().evaluate(request(command_started)).reason_code, "STALE_FRAME")

    def test_ocr_duration_advances_frame_age(self):
        obs = observation(capture_completed_monotonic=100.0)
        result = CentralPolicy().evaluate(request(obs, monotonic_now=102.1, policy_phase="pre_dispatch"))
        self.assertEqual(result.reason_code, "STALE_FRAME")

    def test_wall_clock_adjustment_does_not_change_policy_freshness(self):
        obs = observation(capture_completed_monotonic=500.0)
        first = CentralPolicy().evaluate(request(obs, monotonic_now=500.5))
        second = CentralPolicy().evaluate(request(obs, monotonic_now=500.5))
        self.assertEqual((first.decision, first.reason_code), (second.decision, second.reason_code))

    def test_frame_hash_timestamp_and_roi_binding_are_snapshot_bound(self):
        result = CentralPolicy().evaluate(request())
        snapshot = result.request_snapshot["observation"]
        self.assertEqual(snapshot["frame_sha256"], "a" * 64)
        self.assertEqual(snapshot["capture_completed_monotonic"], 999.5)
        self.assertEqual(snapshot["critical_roi_hashes"], [["semantic_target", ROI_HASH]])


class ExecutorHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SafetyStore(Path(self.temp.name) / "actions.sqlite3")
        self.monotonic = Clock(1000.0)
        self.wall = Clock(5000.0)
        self.store.acquire_lease("executor", self.wall(), 100.0)
        self.transport_calls = 0
        self.recapture_calls = 0

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def transport(self, _intent):
        self.transport_calls += 1
        return TransportResult(True, "MOCK_DISPATCHED")

    def execute(self, immediate, *, attempts=2, posts=None):
        sequence = list(immediate) if isinstance(immediate, (list, tuple)) else [immediate]

        def recapture():
            index = self.recapture_calls
            self.recapture_calls += 1
            item = sequence[min(index, len(sequence) - 1)]
            if isinstance(item, tuple):
                item, clock_value = item
                self.monotonic.value = clock_value
            return item

        post = observation(
            frame_sha256="f" * 64,
            capture_completed_monotonic=1000.1,
            source_state="QUEST",
            target_identity=None,
            target_roi=None,
            ocr_result_frame_sha256=None,
            critical_roi_hashes=(),
        )
        executor = SafeActionExecutor(
            self.store,
            CentralPolicy(),
            "executor",
            self.monotonic,
            self.transport,
            recapture,
            lambda: [post] if posts is None else posts,
            lambda _intent, obs: obs.source_state == "QUEST",
            wall_clock=self.wall,
            max_pre_dispatch_attempts=attempts,
        )
        return executor.execute(request())

    def fresh(self, **changes):
        base = observation(
            frame_sha256="b" * 64,
            capture_completed_monotonic=999.9,
            ocr_result_frame_sha256="b" * 64,
        )
        return replace(base, **changes)

    def test_fast_path_passes_and_dispatches_exactly_once(self):
        result = self.execute(self.fresh())
        self.assertEqual((result.status, result.transport_calls, self.transport_calls), (ActionStatus.CONFIRMED, 1, 1))

    def test_slow_ocr_stale_then_fresh_attempt_uses_one_semantic_action(self):
        stale = self.fresh(capture_completed_monotonic=999.6)
        fresh = self.fresh(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1002.1,
            ocr_result_frame_sha256="c" * 64,
        )
        result = self.execute([(stale, 1002.0), (fresh, 1002.2)])
        self.assertEqual((result.status, self.recapture_calls, self.transport_calls), (ActionStatus.CONFIRMED, 2, 1))
        audits = self.store.audit_events("freshness-action")
        self.assertEqual(len(audits), 6)
        self.assertEqual(sum(e["event_type"] == "pre_input_attempt" for e in audits), 2)

    def test_exhausted_attempts_cancel_before_dispatch(self):
        first = self.fresh(capture_completed_monotonic=999.6)
        second = self.fresh(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1002.1,
            ocr_result_frame_sha256="c" * 64,
        )
        result = self.execute([(first, 1002.0), (second, 1004.5)])
        self.assertEqual((result.status, result.reason, self.transport_calls), (ActionStatus.CANCELLED, "STALE_FRAME", 0))
        attempts = [e for e in self.store.audit_events("freshness-action") if e["event_type"] == "pre_input_attempt"]
        self.assertEqual(len(attempts), 2)

    def test_no_recapture_loop_occurs_after_transport(self):
        result = self.execute(self.fresh(), posts=[])
        self.assertEqual((result.status, self.recapture_calls, self.transport_calls), (ActionStatus.UNRESOLVED, 1, 1))

    def test_identical_critical_roi_allows_explicit_ocr_reuse(self):
        reused = self.fresh(
            ocr_result_frame_sha256="a" * 64,
            ocr_reused=True,
        )
        self.assertIsNone(ocr_reuse_denial(observation(), reused))
        self.assertEqual(self.execute(reused).status, ActionStatus.CONFIRMED)

    def test_changed_critical_roi_forces_fresh_ocr(self):
        changed = self.fresh(critical_roi_hashes=(("semantic_target", "e" * 64),))
        self.assertIsNone(ocr_reuse_denial(observation(), changed))
        self.assertEqual(self.execute(changed).status, ActionStatus.CONFIRMED)

    def test_changed_critical_roi_cannot_reuse_prior_ocr(self):
        changed = self.fresh(
            critical_roi_hashes=(("semantic_target", "e" * 64),),
            ocr_result_frame_sha256="a" * 64,
            ocr_reused=True,
        )
        self.assertEqual(ocr_reuse_denial(observation(), changed), "CRITICAL_ROI_CHANGED")
        self.assertEqual((self.execute(changed).status, self.transport_calls), (ActionStatus.CANCELLED, 0))

    def test_changed_target_cost_quantity_overlay_or_source_denies(self):
        cases = (
            {"target_identity": "different"},
            {"cost_type": "premium", "cost_amount": 1},
            {"quantity": 2},
            {"overlay_state": "unknown"},
            {"source_state": "QUEST"},
        )
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                if index:
                    self.store.close()
                    self.store = SafetyStore(Path(self.temp.name) / ("actions-%d.sqlite3" % index))
                    self.store.acquire_lease("executor", self.wall(), 100.0)
                self.transport_calls = 0
                result = self.execute(self.fresh(**changes))
                self.assertEqual((result.status, self.transport_calls), (ActionStatus.CANCELLED, 0))

    def test_profile_mismatch_remains_global_lock(self):
        result = self.execute(self.fresh(runtime_profile_id="wrong"))
        self.assertEqual((result.status, result.reason, self.transport_calls), (ActionStatus.CANCELLED, "PROFILE_MISMATCH", 0))

    def test_pre_dispatch_attempts_remain_prepared_until_terminal_decision(self):
        stale = self.fresh(capture_completed_monotonic=999.6)
        result = self.execute([(stale, 1002.0)], attempts=1)
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        transitions = [e for e in self.store.audit_events("freshness-action") if e["event_type"] == "action_transition"]
        self.assertEqual([(e["lifecycle_from"], e["lifecycle_to"]) for e in transitions], [(None, "prepared"), ("prepared", "cancelled")])

    def test_restart_after_prepared_reconciles_without_dispatch(self):
        first_policy = CentralPolicy().evaluate(request())
        from safe_action_core.models import ActionIntent

        obs = observation()
        intent = ActionIntent(
            action_id="crash-loop",
            action_key="crash-loop-key",
            task_id="MVP-QUEST-TO-CLAIM",
            semantic_action="NAVIGATE_HOME_TO_QUEST",
            source_state=obs.source_state,
            target_identity=obs.target_identity or "",
            target_roi=obs.target_roi or (0, 0, 1, 1),
            source_frame_sha256=obs.frame_sha256,
            source_frame_captured_at=obs.capture_completed_monotonic,
            runtime_profile_id=PROFILE,
            game_day_id=None,
            expected_postcondition=obs.expected_postcondition or "QUEST",
            consequence=obs.consequence or "navigate_zero_cost",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            evidence_refs=(),
        )
        self.store.prepare_action(intent, first_policy, self.wall())
        self.store.audit("MVP-QUEST-TO-CLAIM", "pre_input_attempt", self.wall(), {"attempt": 1, "transport_calls": 0}, "crash-loop")
        self.store.close()
        self.store = SafetyStore(Path(self.temp.name) / "actions.sqlite3")
        self.assertEqual(self.store.get_action("crash-loop")["final_status"], "prepared")
        self.assertEqual(self.store.startup_reconcile(self.wall()), ["crash-loop"])
        self.assertEqual(self.store.get_action("crash-loop")["final_status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
