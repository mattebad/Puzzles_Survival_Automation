from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safe_action_core.executor import GlobalActionBlock, SafeActionExecutor
from safe_action_core.models import (
    ActionIntent,
    ActionStatus,
    Observation,
    PolicyDecision,
    PolicyRequest,
    TransportResult,
)
from safe_action_core.policy import CentralPolicy
from safe_action_core.store import (
    CURRENT_SCHEMA_VERSION,
    DuplicateActionError,
    InvalidTransitionError,
    LeaseError,
    SafetyStore,
    SchemaVersionError,
    is_no_effect_cancelled,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "runtime-profile/manifest.json").read_text(encoding="utf-8"))
RETAINED_PROFILE_ID = PROFILE["profile_id"]
PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
M6_MANIFEST = ROOT / "evidence/sessions/20260712-m6-dq-bootstrap/assets/asset-manifest.json"
TEST_TASK_ID = "TEST-SUPERVISED-R1"
TEST_TASKS = frozenset({TEST_TASK_ID})


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def observation(**changes):
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="DAILY_QUEST",
        overlay_state="none_observed",
        target_identity="synthetic-test-only-claim-control",
        target_roi=(550, 500, 730, 580),
        recognized=True,
        control_class="CLAIM",
        consequence="claim_zero_cost_reward",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="row_claimed_or_points_increased",
        evidence_refs=("synthetic:test-only",),
    )
    return replace(base, **changes)


def request(obs=None, **changes):
    base = PolicyRequest(
        action_id="action-1",
        action_key="day-1:claim:row-1",
        task_id=TEST_TASK_ID,
        task_mode="supervised_validation",
        semantic_action="CLAIM_DAILY_QUEST",
        expected_runtime_profile_id=PROFILE_ID,
        observation=obs or observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor-1",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        game_day_id="day-1",
    )
    return replace(base, **changes)


def intent(action_id="action-1", action_key="day-1:claim:row-1"):
    obs = observation()
    return ActionIntent(
        action_id=action_id,
        action_key=action_key,
        task_id=TEST_TASK_ID,
        semantic_action="CLAIM_DAILY_QUEST",
        source_state=obs.source_state,
        target_identity=obs.target_identity,
        target_roi=obs.target_roi,
        source_frame_sha256=obs.frame_sha256,
        source_frame_captured_at=obs.capture_completed_monotonic,
        runtime_profile_id=obs.runtime_profile_id,
        game_day_id="day-1",
        expected_postcondition=obs.expected_postcondition,
        consequence=obs.consequence,
        cost_type=obs.cost_type,
        cost_amount=obs.cost_amount,
        quantity=obs.quantity,
        evidence_refs=obs.evidence_refs,
    )


class StoreFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "safety.sqlite3"
        self.store = SafetyStore(self.path)
        self.policy = CentralPolicy(TEST_TASKS).evaluate(request())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()


class StoreCase(StoreFixture, unittest.TestCase):

    def test_database_creation_and_schema_version(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)

    def test_empty_database_migrates_to_current_schema(self):
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)

    def test_future_schema_rejected(self):
        other = Path(self.temp.name) / "future.sqlite3"
        db = sqlite3.connect(str(other))
        db.execute("CREATE TABLE schema_version(singleton INTEGER PRIMARY KEY, version INTEGER)")
        db.execute("INSERT INTO schema_version VALUES(1, 99)")
        db.commit()
        db.close()
        with self.assertRaises(SchemaVersionError):
            SafetyStore(other)

    def test_transactional_transitions_and_durable_reload(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_input_sent("action-1", 1000.1, TransportResult(True, "OK"))
        self.store.mark_confirmed("action-1", 1000.2, {"confirmed": True})
        self.store.close()
        self.store = SafetyStore(self.path)
        self.assertEqual(self.store.get_action("action-1")["final_status"], "confirmed")
        self.assertEqual(len(self.store.audit_events("action-1")), 3)

    def test_invalid_transition_rejected(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        with self.assertRaises(InvalidTransitionError):
            self.store.mark_confirmed("action-1", 1000.1, {"confirmed": True})
        self.assertEqual(self.store.get_action("action-1")["final_status"], "prepared")

    def test_duplicate_action_key_rejected(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        with self.assertRaises(DuplicateActionError):
            self.store.prepare_action(intent("action-2"), self.policy, 1000.1)

    def test_no_effect_cancelled_action_can_be_superseded_and_reprepared(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_cancelled("action-1", 1000.1, "pre_input_revalidation:STALE_FRAME")
        self.assertTrue(is_no_effect_cancelled(self.store.get_action("action-1")))

        self.store.supersede_no_effect_cancelled_action(
            "action-1",
            1000.2,
            "superseded_no_effect_cancelled_retry",
        )

        self.assertIsNone(self.store.get_action_by_key("day-1:claim:row-1"))
        superseded = [
            event
            for event in self.store.audit_events("action-1")
            if event["event_type"] == "action_superseded"
        ]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0]["lifecycle_from"], "cancelled")
        self.assertIsNone(superseded[0]["lifecycle_to"])
        self.assertEqual(
            json.loads(superseded[0]["payload_json"])["reason"],
            "superseded_no_effect_cancelled_retry",
        )

        self.store.prepare_action(intent("retry"), self.policy, 1000.3)
        self.assertEqual(
            self.store.get_action_by_key("day-1:claim:row-1")["action_id"],
            "retry",
        )

    def test_no_effect_cancelled_predicate_is_exact(self):
        self.store.prepare_action(intent("prepared", "key-prepared"), self.policy, 1000.0)
        self.store.prepare_action(intent("cancelled", "key-cancelled"), self.policy, 1000.0)
        self.store.mark_cancelled("cancelled", 1000.1, "pre_input_revalidation:STALE_FRAME")
        self.store.prepare_action(intent("input-sent", "key-input-sent"), self.policy, 1000.0)
        self.store.mark_input_sent("input-sent", 1000.1, TransportResult(True, "OK"))
        self.store.prepare_action(intent("confirmed", "key-confirmed"), self.policy, 1000.0)
        self.store.mark_input_sent("confirmed", 1000.1, TransportResult(True, "OK"))
        self.store.mark_confirmed("confirmed", 1000.2, {"confirmed": True})
        self.store.prepare_action(intent("unresolved", "key-unresolved"), self.policy, 1000.0)
        self.store.mark_unresolved("unresolved", 1000.1, "ambiguous")

        self.assertFalse(is_no_effect_cancelled(self.store.get_action("prepared")))
        self.assertTrue(is_no_effect_cancelled(self.store.get_action("cancelled")))
        self.assertFalse(is_no_effect_cancelled(self.store.get_action("input-sent")))
        self.assertFalse(is_no_effect_cancelled(self.store.get_action("confirmed")))
        self.assertFalse(is_no_effect_cancelled(self.store.get_action("unresolved")))

    def test_supersede_refuses_transported_or_unresolved_actions(self):
        self.store.prepare_action(intent("confirmed", "key-confirmed"), self.policy, 1000.0)
        self.store.mark_input_sent("confirmed", 1000.1, TransportResult(True, "OK"))
        self.store.mark_confirmed("confirmed", 1000.2, {"confirmed": True})
        self.store.prepare_action(intent("input-sent", "key-input-sent"), self.policy, 1000.0)
        self.store.mark_input_sent("input-sent", 1000.1, TransportResult(True, "OK"))
        self.store.prepare_action(intent("unresolved", "key-unresolved"), self.policy, 1000.0)
        self.store.mark_unresolved("unresolved", 1000.1, "ambiguous")

        for action_id in ("confirmed", "input-sent", "unresolved"):
            with self.subTest(action_id=action_id):
                with self.assertRaises(InvalidTransitionError):
                    self.store.supersede_no_effect_cancelled_action(action_id, 1000.3, "retry")

    def test_startup_reconcile_marks_prepared_unresolved(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.assertEqual(self.store.startup_reconcile(1001.0), ["action-1"])
        self.assertTrue(self.store.has_unresolved_action())

    def test_startup_reconcile_marks_input_sent_unresolved(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_input_sent("action-1", 1000.1, TransportResult(True, "OK"))
        self.store.startup_reconcile(1001.0)
        self.assertEqual(self.store.get_action("action-1")["final_status"], "unresolved")

    def test_positive_reconciler_can_confirm_without_erasing_history(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.startup_reconcile(1001.0)
        self.store.reconcile_confirmed("action-1", 1002.0, {"positive": "points_increased"})
        transitions = [(e["lifecycle_from"], e["lifecycle_to"]) for e in self.store.audit_events("action-1")]
        self.assertIn(("unresolved", "confirmed"), transitions)


class LeaseCase(StoreFixture, unittest.TestCase):
    def test_acquire_second_owner_release_and_history(self):
        lease = self.store.acquire_lease("one", 1000.0, 10.0)
        self.assertTrue(lease["valid"])
        with self.assertRaises(LeaseError):
            self.store.acquire_lease("two", 1001.0, 10.0)
        self.store.release_lease("one", 1002.0)
        self.store.acquire_lease("two", 1003.0, 10.0)
        self.assertEqual(self.store.get_lease(1003.0)["owner_id"], "two")

    def test_stale_lease_takeover_is_deterministic(self):
        self.store.acquire_lease("one", 1000.0, 5.0)
        lease = self.store.acquire_lease("two", 1005.0, 5.0)
        self.assertEqual(lease["owner_id"], "two")
        self.assertEqual(lease["acquired_at"], 1005.0)

    def test_unresolved_blocks_stale_takeover(self):
        self.store.acquire_lease("one", 1000.0, 5.0)
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_unresolved("action-1", 1001.0, "ambiguous")
        with self.assertRaises(LeaseError):
            self.store.acquire_lease("two", 1005.0, 5.0)

    def test_unresolved_blocks_expired_same_owner_reacquisition(self):
        self.store.acquire_lease("one", 1000.0, 5.0)
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_unresolved("action-1", 1001.0, "ambiguous")
        with self.assertRaises(LeaseError):
            self.store.acquire_lease("one", 1005.0, 5.0)

    def test_lease_persists_across_restart_and_heartbeat(self):
        self.store.acquire_lease("one", 1000.0, 10.0)
        self.store.close()
        self.store = SafetyStore(self.path)
        self.assertTrue(self.store.lease_valid_for("one", 1001.0))
        self.store.heartbeat_lease("one", 1001.0, 20.0)
        self.assertEqual(self.store.get_lease(1001.0)["expires_at"], 1021.0)


class PolicyCase(unittest.TestCase):
    def setUp(self):
        self.policy = CentralPolicy(TEST_TASKS)

    def decision(self, req):
        return self.policy.evaluate(req)

    def test_valid_supervised_zero_cost_r1(self):
        self.assertEqual(self.decision(request()).decision, PolicyDecision.AUTHORIZE)

    def test_retired_profile_agreement_global_lock(self):
        retired = request(
            observation(runtime_profile_id=RETAINED_PROFILE_ID),
            expected_runtime_profile_id=RETAINED_PROFILE_ID,
        )
        result = self.decision(retired)
        self.assertEqual(result.decision, PolicyDecision.GLOBAL_INPUT_LOCK)
        self.assertEqual(result.reason_code, "PROFILE_MISMATCH")

    def test_stale_frame_denied(self):
        self.assertEqual(
            self.decision(request(observation(capture_completed_monotonic=990))).reason_code,
            "STALE_FRAME",
        )

    def test_profile_mismatch_global_lock(self):
        result = self.decision(request(observation(runtime_profile_id="wrong")))
        self.assertEqual(result.decision, PolicyDecision.GLOBAL_INPUT_LOCK)

    def test_corrupt_black_resized_and_invalid_denied(self):
        for changes in ({"corrupt": True}, {"black": True}, {"width": 799}, {"valid_png": False}):
            with self.subTest(changes=changes):
                self.assertEqual(self.decision(request(observation(**changes))).reason_code, "INVALID_FRAME")

    def test_unknown_source_and_overlay_denied(self):
        self.assertEqual(self.decision(request(observation(source_state="UNKNOWN"))).reason_code, "UNKNOWN_SOURCE")
        self.assertEqual(self.decision(request(observation(overlay_state="unknown"))).reason_code, "UNKNOWN_OVERLAY")

    def test_coordinate_only_target_denied(self):
        self.assertEqual(self.decision(request(observation(target_identity=None))).reason_code, "SEMANTIC_TARGET_REQUIRED")

    def test_unknown_consequence_cost_quantity_denied(self):
        self.assertEqual(self.decision(request(observation(consequence="unknown"))).reason_code, "UNKNOWN_CONSEQUENCE")
        self.assertEqual(self.decision(request(observation(cost_type=None))).reason_code, "UNKNOWN_COST")
        self.assertEqual(self.decision(request(observation(quantity=None))).reason_code, "UNKNOWN_QUANTITY")

    def test_premium_and_ordinary_resource_denied(self):
        premium = observation(cost_type="premium", cost_amount=1)
        resource = observation(cost_type="food", cost_amount=1)
        self.assertEqual(self.decision(request(premium)).reason_code, "PREMIUM_COST_DENIED")
        self.assertEqual(self.decision(request(resource)).reason_code, "RESOURCE_COST_DENIED")

    def test_forbidden_consequences_denied(self):
        for value in ("consume_item", "use_ap", "use_stamina", "dispatch_march", "occupy_queue", "combat", "strategic", "unreviewed_zero_cost"):
            with self.subTest(value=value):
                self.assertEqual(self.decision(request(observation(consequence=value))).reason_code, "CONSEQUENCE_DENIED")

    def test_unresolved_absent_lease_duplicate_denied(self):
        self.assertEqual(self.decision(request(unresolved_action=True)).decision, PolicyDecision.GLOBAL_INPUT_LOCK)
        self.assertEqual(self.decision(request(lease_valid=False)).reason_code, "LEASE_REQUIRED")
        self.assertEqual(self.decision(request(duplicate_action_key=True)).reason_code, "DUPLICATE_ACTION_KEY")

    def test_clipped_ambiguous_and_go_as_claim_denied(self):
        self.assertEqual(self.decision(request(observation(clipped=True))).reason_code, "CLIPPED_TARGET")
        self.assertEqual(self.decision(request(observation(ambiguous=True))).reason_code, "AMBIGUOUS_TARGET")
        self.assertEqual(self.decision(request(observation(control_class="GO"))).reason_code, "GO_NOT_CLAIM")

    def test_task_control_class_and_roi_must_be_exact(self):
        self.assertEqual(self.decision(request(task_id="OTHER-TASK")).reason_code, "TASK_NOT_ENABLED")
        self.assertEqual(CentralPolicy(supervised_tasks=()).evaluate(request()).reason_code, "TASK_NOT_ENABLED")
        self.assertEqual(self.decision(request(observation(control_class=None))).reason_code, "CLAIM_TARGET_NOT_RECOGNIZED")
        self.assertEqual(self.decision(request(observation(target_roi=(700, 1200, 900, 1300)))).reason_code, "INVALID_TARGET_ROI")


class ExecutorCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "safety.sqlite3"
        self.store = SafetyStore(self.path)
        self.clock = FakeClock()
        self.store.acquire_lease("executor-1", self.clock(), 100.0)
        self.transport_calls = 0
        self.initial = observation()
        self.pre = observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        self.post = observation(
            frame_sha256="c" * 64,
            capture_completed_monotonic=1000.1,
            source_state="DAILY_QUEST_POST",
            target_identity=None,
            target_roi=None,
            control_class=None,
        )

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def transport(self, action):
        self.transport_calls += 1
        return TransportResult(True, "MOCK_DISPATCHED")

    def executor(self, pre=None, posts=None, reconciler=None, transport=None):
        return SafeActionExecutor(
            self.store,
            CentralPolicy(TEST_TASKS),
            "executor-1",
            self.clock,
            transport or self.transport,
            lambda: pre or self.pre,
            lambda: posts if posts is not None else [self.post],
            reconciler or (lambda action, obs: obs.source_state == "DAILY_QUEST_POST"),
        )

    def test_confirmed_happy_path_exactly_one_input(self):
        result = self.executor().execute(request(self.initial))
        self.assertEqual(result.status, ActionStatus.CONFIRMED)
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(self.transport_calls, 1)

    def test_capability_firewall_preserves_single_executor_and_optional_path(self):
        from safe_action_core import ActionTransaction, InputCapability
        from safe_action_core.models import ActionClass

        self.assertIs(ActionTransaction, SafeActionExecutor)
        result = self.executor().execute(request(self.initial))
        self.assertEqual(result.status, ActionStatus.CONFIRMED)
        self.assertEqual(result.transport_calls, 1)
        with self.assertRaises(TypeError):
            InputCapability()
        nav = request(
            observation(
                source_state="HOME_BASE",
                target_identity="home-quest-entry",
                target_roi=(250, 1130, 410, 1280),
                control_class=None,
                consequence="navigate_zero_cost",
                expected_postcondition="QUEST",
            ),
            semantic_action="HOME_TO_QUEST",
            action_class=ActionClass.NAVIGATION_ONLY,
            runtime_session_id="safe-action-core-regression-session",
        )
        issued = CentralPolicy(TEST_TASKS).issue_capability(nav)
        self.assertTrue(issued.authorized)
        self.assertIsNotNone(issued.capability)

    def test_source_or_target_change_prevents_dispatch(self):
        for changed in (
            observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8, source_state="QUEST"),
            observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8, target_roi=(1, 1, 2, 2)),
        ):
            with self.subTest(changed=changed.source_state):
                result = self.executor(pre=changed).execute(request(self.initial, action_id="a" + changed.frame_sha256[:1], action_key="k" + str(changed.target_roi)))
                self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(self.transport_calls, 0)

    def test_policy_change_prevents_dispatch(self):
        result = self.executor(pre=replace(self.pre, cost_type="premium", cost_amount=1)).execute(request(self.initial))
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(self.transport_calls, 0)

    def test_transport_success_without_postcondition_unresolved(self):
        result = self.executor(posts=[]).execute(request(self.initial))
        self.assertEqual((result.status, result.reason), (ActionStatus.UNRESOLVED, "verification_timeout"))
        self.assertEqual(self.transport_calls, 1)

    def test_unexpected_successor_unresolved(self):
        result = self.executor(reconciler=lambda action, obs: False).execute(request(self.initial))
        self.assertEqual((result.status, result.reason), (ActionStatus.UNRESOLVED, "unexpected_successor"))

    def test_ambiguous_transport_failure_unresolved(self):
        def broken(action):
            self.transport_calls += 1
            raise OSError("ambiguous")
        result = self.executor(transport=broken).execute(request(self.initial))
        self.assertEqual(result.status, ActionStatus.UNRESOLVED)
        self.assertEqual(self.transport_calls, 1)

    def test_unresolved_blocks_next_action(self):
        first = self.executor(posts=[])
        first.execute(request(self.initial))
        second = self.executor()
        result = second.execute(request(self.initial, action_id="action-2", action_key="day-1:claim:row-2"))
        self.assertEqual(result.reason, "UNRESOLVED_ACTION")
        self.assertEqual(self.transport_calls, 1)

    def test_confirmed_and_duplicate_do_not_repeat_after_restart(self):
        self.executor().execute(request(self.initial))
        self.store.close()
        self.store = SafetyStore(self.path)
        result = self.executor().execute(request(self.initial, action_id="action-2"))
        self.assertEqual(result.reason, "DUPLICATE_ACTION_KEY")
        self.assertEqual(self.transport_calls, 1)

    def test_persistence_failure_after_dispatch_blocks_future_actions(self):
        original = self.store.mark_input_sent
        self.store.mark_input_sent = lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("disk"))
        executor = self.executor()
        result = executor.execute(request(self.initial))
        self.assertEqual(result.status, ActionStatus.UNRESOLVED)
        self.assertIsNotNone(executor.global_block_reason)
        with self.assertRaises(GlobalActionBlock):
            executor.execute(request(self.initial, action_id="action-2", action_key="key-2"))
        self.store.mark_input_sent = original

    def test_evidence_persistence_failure_after_dispatch_is_unresolved(self):
        original = self.store.mark_confirmed
        self.store.mark_confirmed = lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("evidence disk"))
        executor = self.executor()
        result = executor.execute(request(self.initial))
        self.assertEqual((result.status, result.reason), (ActionStatus.UNRESOLVED, "evidence_persistence_failure_after_dispatch"))
        self.assertEqual(self.store.get_action("action-1")["final_status"], "unresolved")
        self.assertIsNotNone(executor.global_block_reason)
        self.store.mark_confirmed = original


class CrashBoundaryCase(StoreFixture, unittest.TestCase):
    def test_crash_before_prepare_leaves_no_action(self):
        self.assertEqual(self.store.list_nonterminal_actions(), [])

    def test_crash_after_prepare_never_replays(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.close()
        self.store = SafetyStore(self.path)
        self.store.startup_reconcile(1001.0)
        self.assertEqual(self.store.get_action("action-1")["final_status"], "unresolved")

    def test_crash_during_dispatch_or_after_return_before_persist_is_unresolved(self):
        for suffix in ("during", "after-return"):
            action_id = "action-" + suffix
            self.store.prepare_action(intent(action_id, "key-" + suffix), self.policy, 1000.0)
        self.store.close()
        self.store = SafetyStore(self.path)
        reconciled = self.store.startup_reconcile(1001.0)
        self.assertEqual(len(reconciled), 2)
        self.assertEqual(len(self.store.list_unresolved_actions()), 2)

    def test_crash_after_input_sent_or_during_verification_is_unresolved(self):
        for suffix in ("after-sent", "during-verify"):
            action_id = "action-" + suffix
            self.store.prepare_action(intent(action_id, "key-" + suffix), self.policy, 1000.0)
            self.store.mark_input_sent(action_id, 1000.1, TransportResult(True, "OK"))
        self.store.close()
        self.store = SafetyStore(self.path)
        self.store.startup_reconcile(1001.0)
        self.assertEqual(len(self.store.list_unresolved_actions()), 2)

    def test_crash_after_confirmed_stays_confirmed(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_input_sent("action-1", 1000.1, TransportResult(True, "OK"))
        self.store.mark_confirmed("action-1", 1000.2, {"confirmed": True})
        self.store.close()
        self.store = SafetyStore(self.path)
        self.assertEqual(self.store.startup_reconcile(1001.0), [])
        self.assertEqual(self.store.get_action("action-1")["final_status"], "confirmed")

    def test_unresolved_mistarget_can_only_be_terminally_reconciled_with_proof(self):
        self.store.prepare_action(intent(), self.policy, 1000.0)
        self.store.mark_unresolved("action-1", 1000.1, "unexpected_successor")
        with self.assertRaises(InvalidTransitionError):
            self.store.mark_cancelled("action-1", 1000.2, "operator_guess")
        self.store.mark_cancelled("action-1", 1000.3, "proven_no_effect_mistarget")
        self.assertEqual(self.store.get_action("action-1")["final_status"], "cancelled")
        self.assertEqual(self.store.list_unresolved_actions(), [])


class M6FixtureCase(unittest.TestCase):
    def test_six_promoted_assets_match_locked_profile(self):
        manifest = json.loads(M6_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["assets"]), 6)
        self.assertTrue(all(asset["profile_id"] == RETAINED_PROFILE_ID for asset in manifest["assets"]))
        self.assertTrue(all(asset["profile_content_sha256"] == PROFILE["profile_content_sha256"] for asset in manifest["assets"]))

    def test_go_negative_and_clipped_fixture_cannot_authorize_claim(self):
        manifest = json.loads(M6_MANIFEST.read_text(encoding="utf-8"))
        negative = next(asset for asset in manifest["assets"] if asset["asset_id"] == "m6-dq-go-not-claim-negative-v1")
        daily = next(asset for asset in manifest["assets"] if asset["asset_id"] == "m6-dq-daily-incomplete-go-clipped-v1")
        base = observation(
            frame_sha256=negative["sha256"],
            capture_completed_monotonic=999.5,
            control_class="GO",
            evidence_refs=(negative["source_evidence_path"],),
        )
        self.assertEqual(CentralPolicy(TEST_TASKS).evaluate(request(base)).reason_code, "GO_NOT_CLAIM")
        clipped = replace(base, frame_sha256=daily["sha256"], control_class="CLAIM", clipped=True)
        self.assertEqual(CentralPolicy(TEST_TASKS).evaluate(request(clipped)).reason_code, "CLIPPED_TARGET")

    def test_ambiguous_stale_and_profile_mismatch_fail_closed(self):
        policy = CentralPolicy(TEST_TASKS)
        self.assertEqual(policy.evaluate(request(observation(ambiguous=True))).reason_code, "AMBIGUOUS_TARGET")
        self.assertEqual(
            policy.evaluate(request(observation(capture_completed_monotonic=1))).reason_code,
            "STALE_FRAME",
        )
        self.assertEqual(policy.evaluate(request(observation(runtime_profile_id="mismatch"))).decision, PolicyDecision.GLOBAL_INPUT_LOCK)


if __name__ == "__main__":
    unittest.main()
