"""Reset-scoped Resource item service boundary and accounting tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from automation_service.contracts import NormalizedOutcome
from automation_service.native_execution import NativeRouteOutcome
from automation_service.recruitment import recruitment_reset
from automation_service.resource_item import (
    FLOW_ID,
    MAX_ACTIONS,
    MAX_INPUTS,
    PRODUCT_ID,
    PRODUCT_REVISION,
    ResourceItemRunner,
    normalize_resource_item_result,
    resource_item_next_due,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity


class _HeldLock:
    owner = "automation-service"
    invocation_id = "service-invocation"

    def __init__(self):
        self.assertions = 0

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("wrong runtime owner assertion")
        self.assertions += 1


def _identity_and_result(now: float):
    binding = resource_fixed_runtime_binding()
    evaluated = datetime.fromtimestamp(now, timezone.utc)
    backend = derive_resource_runtime_identity(binding, evaluated)
    window = derive_static_utc_reset(evaluated)
    identity = SchedulerIdentity(
        backend.account_id,
        backend.server_id,
        recruitment_reset(now),
        PRODUCT_ID,
    )
    frame_before = {"path": "frames/item-before.png", "sha256": "1" * 64}
    frame_after = {"path": "frames/item-after.png", "sha256": "2" * 64}
    frame_home = {"path": "frames/home.png", "sha256": "3" * 64}
    resource_occurrence_key = "occ:v1:" + "d" * 64
    result = {
        "status": "complete_for_reset",
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "task_id": PRODUCT_ID,
        "max_actions": MAX_ACTIONS,
        "time_basis": "utc",
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "occurrence_key": "occ:v1:" + "f" * 64,
        "completed_at_utc": now + 1,
        "accounting_verified": True,
        "resource_delta_verified": True,
        "terminal_home_verified": True,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "reservation_state": "EFFECT_CONFIRMED",
        "resource_effect_state": "CONFIRMED",
        "journal_status": "confirmed",
        "terminal_observation_state": "HOME_CANONICAL",
        "resource_account_id": backend.account_id,
        "resource_server_id": backend.server_id,
        "resource_runtime_scope": backend.runtime_scope,
        "resource_identity_assurance": backend.assurance.value,
        "resource_backend_identity_reset_id": backend.reset_id,
        "resource_reset_start_utc": window.reset_start_text,
        "resource_reset_deadline_utc": window.reset_deadline_text,
        "resource_reset_identity_id": window.reset_identity_id,
        "action_game_day_id": backend.reset_id,
        "action_task_id": FLOW_ID,
        "action_semantic_action": "USE_RESOURCE_ITEM",
        "action_source_state": "RESOURCES_1K_FOOD_READY",
        "action_target_identity": "daily-resource-item:use-1k-food",
        "action_expected_postcondition": "RESOURCES_1K_FOOD_USED",
        "action_consequence": "ordinary_non_idempotent_resource_item_use",
        "action_cost_type": "owned_inventory_item",
        "action_cost_amount": 1,
        "action_quantity": 1,
        "max_inputs": MAX_INPUTS,
        "total_input_count": 3,
        "input_count": 3,
        "session_input_count": 3,
        "runtime_input_count": 3,
        "item_use_transport_calls": 1,
        "committed_action_count": 1,
        "action_count": 1,
        "before_owned_quantity": 3,
        "after_owned_quantity": 2,
        "owned_item_decrement": 1,
        "terminal_home_frame": frame_home,
        "semantic_evidence": {
            "item_before_frame": frame_before,
            "item_after_frame": frame_after,
            "terminal_home_frame": frame_home,
        },
        "resource_occurrence_key": resource_occurrence_key,
        "resource_occurrence_id": "occurrence:v1:" + "e" * 64,
        "action_key": f"{resource_occurrence_key}:effect:1:generation:1",
        "resource_action_key": f"{resource_occurrence_key}:effect:1:generation:1",
        "action_id": "resource-action:v1:" + "a" * 64,
        "resource_action_id": "resource-action:v1:" + "a" * 64,
        "reservation_id": "reservation:v1:" + "b" * 64,
        "resource_attempt_id": "attempt:v1:" + "c" * 64,
    }
    return identity, backend, window, result


class _FakeNative:
    flow_id = FLOW_ID
    product_id = PRODUCT_ID
    product_revision = PRODUCT_REVISION
    runtime_profile_id = ACTIVE_RUNTIME_PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, result, *, failure=None):
        self.result = deepcopy(result)
        self.failure = failure
        self.calls = 0
        self.request = None

    def run(self, request):
        self.calls += 1
        self.request = request
        request.validate_identity()
        return NativeRouteOutcome(
            flow_id=request.flow_id,
            native_result=self.result,
            partial_result=self.result,
            failure=self.failure,
            invocation_id="native-invocation",
            session_directory="sessions/resource-item",
            startup_recovery=None,
            input_count=self.result["total_input_count"],
            session_input_count=self.result["session_input_count"],
            runtime_input_count=self.result["runtime_input_count"],
            accounting_verified=True,
        )


class ResourceItemServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 6, 1, 12, tzinfo=timezone.utc).timestamp()
        self.identity, self.backend, self.window, self.result = _identity_and_result(self.now)
        self.occurrence_key = "occ:v1:" + "f" * 64

    def test_exact_confirmed_owned_item_sets_fixed_backend_reset_due(self):
        result = deepcopy(self.result)
        result["occurrence_key"] = self.occurrence_key
        due = resource_item_next_due(result, self.identity, self.now, self.occurrence_key)
        self.assertEqual(due, self.window.reset_deadline_utc.timestamp())
        normalized = normalize_resource_item_result(
            result, self.identity, self.now, self.occurrence_key
        )
        self.assertEqual(normalized.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertTrue(normalized.verified)
        self.assertEqual(normalized.action_count, 1)

    def test_cost_source_item_count_decrement_and_home_are_required(self):
        prior_reset = derive_static_utc_reset(
            self.window.reset_start_utc - timedelta(seconds=1)
        ).reset_identity_id
        invalid = (
            {"action_cost_type": "premium_currency"},
            {"action_cost_amount": 0},
            {"action_cost_amount": True},
            {"action_quantity": 2},
            {"action_source_state": "UNKNOWN"},
            {"action_target_identity": "daily-resource-item:other"},
            {"action_semantic_action": "CLAIM_REWARD"},
            {"resource_backend_identity_reset_id": prior_reset},
            {"resource_reset_identity_id": prior_reset},
            {"action_game_day_id": prior_reset},
            {"max_actions": 2},
            {"before_owned_quantity": 0},
            {"after_owned_quantity": 3},
            {"after_owned_quantity": 1},
            {"item_use_transport_calls": 2},
            {"terminal_observation_state": "RESOURCES"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                result = deepcopy(self.result)
                result["occurrence_key"] = self.occurrence_key
                result.update(changes)
                with self.assertRaises(ValueError):
                    resource_item_next_due(
                        result, self.identity, self.now, self.occurrence_key
                    )

    def test_runner_preserves_occurrence_reset_owner_and_native_accounting(self):
        result = deepcopy(self.result)
        result["occurrence_key"] = self.occurrence_key
        native = _FakeNative(result)
        lock = _HeldLock()
        runner = ResourceItemRunner(
            native=native,
            output_directory=Path("sessions"),
            utc_clock=lambda: self.now,
        )
        previous_reset_id = "game-day-2025-05-31"
        observed = runner(
            self.identity,
            previous_reset_id,
            lambda: None,
            runtime_input_lock=lock,
            occurrence_key=self.occurrence_key,
        )
        self.assertEqual(native.calls, 1)
        self.assertIs(native.request.identity, self.identity)
        self.assertEqual(native.request.previous_reset_id, previous_reset_id)
        self.assertEqual(native.request.occurrence_key, self.occurrence_key)
        self.assertEqual(native.request.flow_id, FLOW_ID)
        self.assertEqual(native.request.max_inputs, MAX_INPUTS)
        self.assertEqual(native.request.max_actions, 1)
        self.assertEqual(dict(native.request.arguments), {})
        self.assertEqual(observed["occurrence_key"], self.occurrence_key)
        self.assertEqual(observed["previous_reset_id"], previous_reset_id)
        self.assertEqual(observed["resource_occurrence_key"], self.result["resource_occurrence_key"])
        self.assertEqual(observed["total_input_count"], 3)
        self.assertTrue(observed["accounting_verified"])
        self.assertEqual(observed["status"], "complete_for_reset")
        self.assertGreaterEqual(lock.assertions, 3)

    def test_unknown_dispatched_effect_is_unresolved_and_never_normalized_complete(self):
        result = deepcopy(self.result)
        result.update(
            status="unresolved",
            occurrence_key=self.occurrence_key,
            item_use_transport_calls=1,
            committed_action_count=0,
            action_count=0,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
            reservation_state="TRANSPORT_UNKNOWN",
            resource_effect_state="UNKNOWN",
            journal_status="unknown",
        )
        native = _FakeNative(result, failure="effect evidence unresolved")
        lock = _HeldLock()
        runner = ResourceItemRunner(
            native=native,
            output_directory=Path("sessions"),
            utc_clock=lambda: self.now,
        )
        observed = runner(
            self.identity,
            None,
            lambda: None,
            runtime_input_lock=lock,
            occurrence_key=self.occurrence_key,
        )
        self.assertEqual(native.calls, 1)
        self.assertEqual(observed["status"], "unresolved")
        self.assertEqual(observed["item_use_transport_calls"], 1)
        self.assertEqual(observed["committed_action_count"], 0)
        self.assertTrue(observed["effect_reconciliation_required"])
        normalized = normalize_resource_item_result(
            observed, self.identity, self.now, self.occurrence_key
        )
        self.assertEqual(normalized.outcome, NormalizedOutcome.RECONCILIATION_REQUIRED)
        self.assertFalse(normalized.verified)


if __name__ == "__main__":
    unittest.main()
