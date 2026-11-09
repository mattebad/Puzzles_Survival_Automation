from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from automation_service.contracts import NormalizedOutcome
from automation_service.food_farm_boost import (
    FLOW_ID,
    MAX_ACTIONS,
    MAX_INPUTS,
    PRODUCT_ID,
    PRODUCT_REVISION,
    FoodFarmBoostRunner,
    food_farm_boost_next_due,
)
from automation_service.native_execution import NativeRouteOutcome
from automation_service.recruitment import recruitment_reset
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import resource_fixed_runtime_binding
from tasks.runtime_identity import derive_resource_runtime_identity
from tasks.scheduler_task_result import SchedulerIdentity


class _HeldInputLock:
    owner = "automation-service:food-farm-boost"
    invocation_id = "food-farm-service-test"

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("wrong runtime lock identity")


class _FakeNativeBoundary:
    def __init__(self, native_result, *, failure=None, accounting_verified=True, partial_result=None):
        self.native_result = native_result
        self.failure = failure
        self.accounting_verified = accounting_verified
        self.partial_result = partial_result
        self.request = None

    def run(self, request):
        self.request = request
        request.validate_identity()
        count = 4 if self.accounting_verified else 0
        return NativeRouteOutcome(
            flow_id=FLOW_ID,
            failure=self.failure,
            native_result=self.native_result,
            partial_result=(
                self.partial_result if self.partial_result is not None
                else self.native_result if self.failure else None
            ),
            invocation_id="native-invocation",
            session_directory="native-session",
            startup_recovery=None,
            input_count=count,
            session_input_count=count,
            runtime_input_count=count,
            accounting_verified=self.accounting_verified,
        )


def _identity(epoch: float) -> SchedulerIdentity:
    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(epoch, timezone.utc))
    return SchedulerIdentity(
        account_id=backend.account_id,
        server_id=backend.server_id,
        reset_id=recruitment_reset(epoch),
        task_id=PRODUCT_ID,
    )


def _native_result(status="deferred"):
    result = {
        "status": status,
        "reason": "FOOD_FARM_INVENTORY_NOT_OBSERVED",
        "collection_transport_calls": 0,
        "boost_transport_calls": 0,
        "food_farm_dispatch_count": 0,
        "collection_count": 0,
        "collection_effect_accounted": False,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": True,
        "terminal_home_frame_sha256": "a" * 64,
        "farm_identity": "home.building.farm.02",
    }
    if status == "completed":
        result.update(
            reason="FOOD_FARM_BOOST_CONFIRMED_WITH_POSITIVE_TIMER",
            boost_transport_calls=1,
            food_farm_dispatch_count=1,
            boost_decision="owned_item",
            boost_duration_seconds=86_400,
            boost_timer_remaining_seconds=86_390,
            boost_timer_farm_identity="home.building.farm.02",
        )
    elif status == "already_active":
        result.update(
            reason="FOOD_FARM_BOOST_ALREADY_ACTIVE",
            active_remaining_seconds=3_600,
            active_timer_farm_identity="home.building.farm.02",
        )
    elif status == "already_complete":
        result.update(
            reason="FOOD_FARM_BOOST_CONFIRMED_FOR_RESET",
            boost_decision="owned_item",
            boost_duration_seconds=86_400,
            prior_boost_confirmation={
                "confirmed": True, "frame_sha256": "b" * 64,
            },
            prior_boost_confirmation_farm_identity="home.building.farm.02",
            prior_boost_confirmation_duration_seconds=86_400,
        )
    return result


class FoodFarmBoostServiceTests(unittest.TestCase):
    def _run(
        self, native_result, *, failure=None, accounting_verified=True,
        partial_result=None, epoch=None,
    ):
        epoch = (
            datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc).timestamp()
            if epoch is None else epoch
        )
        native = _FakeNativeBoundary(
            native_result, failure=failure, accounting_verified=accounting_verified,
            partial_result=partial_result,
        )
        runner = FoodFarmBoostRunner(
            output_directory=Path("native-output"),
            native=native,
            utc_clock=lambda: epoch,
            monotonic_clock=lambda: 20.0,
            settle_seconds=0.0,
        )
        checkpoints = []
        outcome = runner(
            _identity(epoch), None, lambda: checkpoints.append(True),
            runtime_input_lock=_HeldInputLock(), occurrence_key="scheduler-occurrence-001",
        )
        return outcome, native, epoch, checkpoints

    def test_service_runner_forwards_canonical_occurrence_and_bounds_deferred_recheck(self):
        outcome, native, epoch, checkpoints = self._run(_native_result())
        self.assertEqual(native.request.flow_id, FLOW_ID)
        self.assertEqual(native.request.product_id, PRODUCT_ID)
        self.assertEqual(native.request.product_revision, PRODUCT_REVISION)
        self.assertEqual(native.request.occurrence_key, "scheduler-occurrence-001")
        self.assertGreaterEqual(len(checkpoints), 1)
        self.assertEqual(native.request.max_inputs, MAX_INPUTS)
        self.assertEqual(native.request.max_actions, MAX_ACTIONS)
        self.assertEqual(outcome.outcome, NormalizedOutcome.DEFERRED)
        self.assertTrue(outcome.verified)
        self.assertEqual(outcome.action_count, 0)
        self.assertEqual(outcome.next_eligible_at, epoch + 300.0)
        self.assertEqual(outcome.consequence["collection_transport_calls"], 0)
        self.assertEqual(outcome.consequence["boost_transport_calls"], 0)

    def test_deferred_recheck_never_crosses_the_reset_deadline(self):
        epoch = datetime(2026, 11, 6, 23, 59, tzinfo=timezone.utc).timestamp()
        outcome, _native, _epoch, _checkpoints = self._run(_native_result(), epoch=epoch)
        self.assertEqual(outcome.outcome, NormalizedOutcome.DEFERRED)
        self.assertEqual(outcome.next_eligible_at, epoch + 60.0)

    def test_same_farm_positive_active_timer_is_already_complete_and_reset_bounded(self):
        outcome, native, epoch, _checkpoints = self._run(_native_result("already_active"))
        self.assertEqual(outcome.outcome, NormalizedOutcome.ALREADY_COMPLETE)
        self.assertEqual(outcome.action_count, 0)
        self.assertGreater(outcome.next_eligible_at, epoch)
        result = dict(outcome.consequence["native_result"])
        for invalid in (
            {**result, "active_remaining_seconds": 0},
            {**result, "active_timer_farm_identity": "home.building.farm.03"},
        ):
            with self.assertRaises(ValueError):
                food_farm_boost_next_due(invalid, native.request.identity, epoch)

    def test_reset_completion_preserves_prior_positive_proof_without_demanding_the_same_farm(self):
        outcome, native, epoch, _checkpoints = self._run(
            _native_result("already_complete"),
        )
        self.assertEqual(outcome.outcome, NormalizedOutcome.ALREADY_COMPLETE)
        result = dict(outcome.consequence["native_result"])
        other_farm = {**result, "prior_boost_confirmation_farm_identity": "home.building.farm.03"}
        self.assertEqual(food_farm_boost_next_due(other_farm, native.request.identity, epoch),
                         outcome.next_eligible_at)
        for invalid in (
            {**result, "prior_boost_confirmation_farm_identity": "not-a-farm"},
            {
                **result,
                "prior_boost_confirmation": {"confirmed": False, "frame_sha256": "b" * 64},
            },
        ):
            with self.assertRaises(ValueError):
                food_farm_boost_next_due(invalid, native.request.identity, epoch)

    def test_positive_timer_completion_counts_boost_and_collection_separately(self):
        result = _native_result("completed")
        result.update(
            collection_transport_calls=1,
            collection_count=1,
            food_farm_dispatch_count=2,
            collection_effect_accounted=True,
        )
        outcome, native, epoch, _checkpoints = self._run(result)
        self.assertEqual(outcome.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(outcome.action_count, 2)
        self.assertEqual(outcome.consequence["collection_transport_calls"], 1)
        self.assertEqual(outcome.consequence["boost_transport_calls"], 1)
        self.assertEqual(outcome.consequence["food_farm_dispatch_count"], 2)
        self.assertEqual(
            outcome.next_eligible_at,
            food_farm_boost_next_due(
                outcome.consequence["native_result"], native.request.identity, epoch
            ),
        )

    def test_optional_collection_does_not_gate_owned_or_capped_premium_boost_completion(self):
        for choice in ("owned_item", "diamonds"):
            with self.subTest(choice=choice):
                result = _native_result("completed")
                result.update(collection_transport_calls=1, collection_count=0,
                    collection_effect_accounted=True, collection_successor="home",
                    food_farm_dispatch_count=2, boost_decision=choice)
                if choice == "diamonds":
                    result.update(boost_cost=48, boost_diamond_balance=100, owned_item_unavailable=True)
                outcome, native, epoch, _checks = self._run(result)
                self.assertEqual(outcome.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
                self.assertEqual(outcome.consequence["collection_count"], 0)
                self.assertFalse(outcome.unresolved_action)
                if choice == "diamonds":
                    raw = outcome.consequence["native_result"]
                    for changes in ({"boost_cost": 49}, {"boost_diamond_balance": 47},
                                    {"owned_item_unavailable": False}):
                        with self.assertRaises(ValueError):
                            food_farm_boost_next_due({**raw, **changes}, native.request.identity, epoch)

    def test_persisted_collection_commit_is_not_counted_as_a_new_transport(self):
        native_result = _native_result("completed")
        native_result.update(
            collection_count=1, collection_effect_accounted=True,
        )
        outcome, _native, _epoch, _checkpoints = self._run(native_result)
        self.assertEqual(outcome.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(outcome.action_count, 1)
        self.assertEqual(outcome.consequence["collection_transport_calls"], 0)
        self.assertEqual(outcome.consequence["collection_count"], 1)

    def test_unknown_sent_effect_remains_reconciliation_required_after_restart(self):
        partial = _native_result("unresolved")
        partial.update(
            reason="FOOD_FARM_COLLECTION_REQUIRES_RECONCILIATION",
            collection_transport_calls=1,
            collection_count=0,
            food_farm_dispatch_count=1,
            collection_effect_accounted=False,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
        for _ in range(2):
            outcome, _native, _epoch, _checkpoints = self._run(
                partial, failure="native route stopped after collection input"
            )
            self.assertEqual(outcome.outcome, NormalizedOutcome.RECONCILIATION_REQUIRED)
            self.assertTrue(outcome.unresolved_action)
            self.assertEqual(outcome.action_count, 1)
            self.assertEqual(outcome.consequence["native_result"]["collection_count"], 0)

    def test_partial_lifecycle_result_preserves_attempted_transport_count(self):
        native_result = _native_result("unresolved")
        native_result.update(
            collection_transport_calls=1, collection_count=0,
            food_farm_dispatch_count=1, effect_reconciliation_required=True,
        )
        outcome, _native, _epoch, _checkpoints = self._run(
            native_result, failure="native accounting incomplete",
            accounting_verified=False, partial_result={"status": "unresolved"},
        )
        self.assertEqual(outcome.outcome, NormalizedOutcome.RECONCILIATION_REQUIRED)
        self.assertTrue(outcome.unresolved_action)
        self.assertEqual(outcome.action_count, 1)
        self.assertTrue(
            outcome.consequence["native_result"]["identical_retry_denied"]
        )

    def test_evidence_block_after_confirmed_collection_keeps_progress_without_unresolved_effect(self):
        native_result = _native_result("blocked")
        native_result.update(
            reason="FOOD_FARM_INVENTORY_NOT_OBSERVED",
            collection_transport_calls=1, collection_count=1,
            food_farm_dispatch_count=1, collection_effect_accounted=True,
            evidence_required=True,
        )
        outcome, _native, _epoch, _checkpoints = self._run(native_result)
        self.assertEqual(outcome.outcome, NormalizedOutcome.BLOCKED)
        self.assertTrue(outcome.verified)
        self.assertEqual(outcome.action_count, 1)
        self.assertFalse(outcome.unresolved_action)
        self.assertTrue(outcome.consequence["collection_effect_accounted"])

    def test_bad_scheduler_reset_fails_before_native_boundary(self):
        epoch = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc).timestamp()
        next_epoch = epoch + 86_400
        native = _FakeNativeBoundary(_native_result())
        runner = FoodFarmBoostRunner(
            output_directory=Path("native-output"), native=native,
            utc_clock=lambda: epoch, monotonic_clock=lambda: 20.0,
        )
        correct = _identity(epoch)
        wrong = SchedulerIdentity(
            account_id=correct.account_id, server_id=correct.server_id,
            reset_id=recruitment_reset(next_epoch), task_id=PRODUCT_ID,
        )
        outcome = runner(
            wrong, None, lambda: None, runtime_input_lock=_HeldInputLock(),
            occurrence_key="scheduler-occurrence-002",
        )
        self.assertEqual(outcome.outcome, NormalizedOutcome.BLOCKED)
        self.assertIsNone(native.request)

    def test_due_guard_rejects_wrong_duration_timer_and_action_limit(self):
        outcome, native, epoch, _checkpoints = self._run(_native_result("completed"))
        result = dict(outcome.consequence["native_result"])
        invalid_results = (
            {**result, "boost_timer_remaining_seconds": 86_401},
            {**result, "boost_duration_seconds": 3_600},
            {**result, "boost_decision": "diamonds"},
            {
                **result, "collection_transport_calls": 2, "collection_count": 2,
                "food_farm_dispatch_count": 3, "collection_effect_accounted": True,
            },
        )
        for invalid in invalid_results:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    food_farm_boost_next_due(invalid, native.request.identity, epoch)


if __name__ == "__main__":
    unittest.main()
