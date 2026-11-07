from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import unittest

from automation_service import nano_material_production as service
from automation_service.contracts import FlowSpec, NormalizedOutcome
from automation_service.native_execution import NativeRouteOutcome
from automation_service.registry import RegisteredDispatchSnapshot
from automation_service.recruitment import recruitment_reset
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.scheduler import make_facts

SERVICE_NOW = datetime(2026, 10, 29, 10, tzinfo=timezone.utc).timestamp()
SERVICE_RESET = recruitment_reset(SERVICE_NOW)
SERVICE_BACKEND = derive_resource_runtime_identity(
    resource_fixed_runtime_binding(),
    datetime.fromtimestamp(SERVICE_NOW, timezone.utc),
)
SERVICE_IDENTITY = SchedulerIdentity(
    SERVICE_BACKEND.account_id,
    SERVICE_BACKEND.server_id,
    SERVICE_RESET,
    service.PRODUCT_ID,
)
SERVICE_OCCURRENCE = "occurrence:nano-material-production:2026-10-29"


class _FixedNativeBoundary:
    def __init__(self, flow_id, outcome):
        self.flow_id = flow_id
        self.outcome = outcome
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        request.validate_identity()
        request.checkpoint()
        return self.outcome


def _production_outcome(
    *,
    status="completed",
    calls=1,
    committed=None,
    input_count=4,
    accounting_verified=True,
    flow_id=service.FLOW_ID,
    result_changes=None,
    partial_result=None,
    failure=None,
    session_input_count=None,
    runtime_input_count=None,
):
    committed = calls if committed is None else committed
    result = {
        "status": status,
        "production_state": "active",
        "active_production_count": 1,
        "production_duration_seconds": 21_600,
        "zero_resource_cost_confirmed": True,
        "production_transport_calls": calls,
        "committed_action_count": committed,
        "total_input_count": 999,
        "timer_seconds_remaining": 21_000,
        "next_eligible_at": SERVICE_NOW + 21_000,
        "native_occurrence_key": SERVICE_OCCURRENCE,
        "occurrence_key": SERVICE_OCCURRENCE,
        "production_occurrence_key": SERVICE_OCCURRENCE,
        "production_target_identity": service.NANO_MATERIAL_PRODUCTION_TARGET,
        "production_state_frame": {
            "frame_path": "evidence/production-state.png",
            "frame_sha256": "b" * 64,
            "observed_utc": "2026-10-29T10:00:00Z",
            "capture_ordinal": 7,
        },
        "production_state_observation_sha256": "b" * 64,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": True,
        "terminal_home_state": "HOME_BASE",
        "terminal_home_recognized": True,
        "terminal_home_frame": {
            "frame_path": "evidence/terminal-home.png",
            "frame_sha256": "f" * 64,
        },
    }
    result.update(result_changes or {})
    return NativeRouteOutcome(
        flow_id=flow_id,
        native_result=result,
        partial_result=partial_result,
        failure=failure,
        invocation_id="fake-invocation",
        session_directory="fake-session",
        startup_recovery=None,
        input_count=input_count,
        session_input_count=input_count if session_input_count is None else session_input_count,
        runtime_input_count=input_count if runtime_input_count is None else runtime_input_count,
        accounting_verified=accounting_verified,
    )


class NanoMaterialProductionServiceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.checkpoints = 0
        self.input_lock = object()

    def checkpoint(self):
        self.checkpoints += 1

    def runner(self, outcome, *, boundary_flow=service.FLOW_ID):
        return service.NanoMaterialProductionRunner(
            native=_FixedNativeBoundary(boundary_flow, outcome),
            adb=BLUESTACKS_ADB,
            serial=BLUESTACKS_SERIAL,
            output_directory=Path("device-free-output"),
            utc_clock=lambda: SERVICE_NOW,
            monotonic_clock=lambda: 12.5,
            settle_seconds=0.25,
        )

    def run_route(self, runner, *, identity=SERVICE_IDENTITY, previous_reset_id=None):
        return runner(
            identity,
            previous_reset_id,
            self.checkpoint,
            runtime_input_lock=self.input_lock,
            occurrence_key=SERVICE_OCCURRENCE,
        )

    def test_binding_and_flow_mismatches_fail_closed(self):
        with self.assertRaises(service.NanoMaterialProductionRunnerError) as absent:
            service.NanoMaterialProductionRunner(
                native=None,
                output_directory=Path("device-free-output"),
                utc_clock=lambda: SERVICE_NOW,
            )(
                SERVICE_IDENTITY,
                None,
                self.checkpoint,
                runtime_input_lock=self.input_lock,
                occurrence_key=SERVICE_OCCURRENCE,
            )
        self.assertEqual(absent.exception.partial_result["status"], "blocked")
        self.assertEqual(absent.exception.partial_result["production_transport_calls"], 0)

        with self.assertRaises(ValueError):
            self.runner(_production_outcome(), boundary_flow="other-flow")

        mismatched = self.runner(_production_outcome(flow_id="other-flow"))
        with self.assertRaises(service.NanoMaterialProductionRunnerError) as caught:
            self.run_route(mismatched)
        self.assertEqual(caught.exception.partial_result["status"], "unresolved")
        self.assertEqual(caught.exception.partial_result["production_transport_calls"], 1)
        self.assertEqual(caught.exception.partial_result["committed_action_count"], 1)
        self.assertTrue(caught.exception.partial_result["effect_reconciliation_required"])
        self.assertTrue(caught.exception.partial_result["identical_retry_denied"])
        self.assertIn("flow mismatch", caught.exception.partial_result["reason"])

    def test_runner_request_and_normalized_evidence_include_claims_in_action_budget(self):
        boundary = _FixedNativeBoundary(
            service.FLOW_ID,
            _production_outcome(calls=2, committed=2, input_count=5),
        )
        runner = service.NanoMaterialProductionRunner(
            native=boundary,
            adb=BLUESTACKS_ADB,
            serial=BLUESTACKS_SERIAL,
            output_directory=Path("device-free-output"),
            utc_clock=lambda: SERVICE_NOW,
            monotonic_clock=lambda: 12.5,
            settle_seconds=0.25,
        )
        result = self.run_route(runner, previous_reset_id="game-day-2026-10-28")
        request, = boundary.requests
        self.assertEqual(
            (
                request.flow_id,
                request.product_id,
                request.product_revision,
                request.runtime_profile_id,
                request.identity,
                request.previous_reset_id,
                request.occurrence_key,
                request.adb,
                request.serial,
                request.max_inputs,
                request.max_actions,
                request.settle_seconds,
                dict(request.arguments),
            ),
            (
                service.FLOW_ID,
                service.PRODUCT_ID,
                service.PRODUCT_REVISION,
                service.PROFILE_ID,
                SERVICE_IDENTITY,
                "game-day-2026-10-28",
                SERVICE_OCCURRENCE,
                str(BLUESTACKS_ADB),
                BLUESTACKS_SERIAL,
                service.MAX_INPUTS,
                2,
                0.25,
                {},
            ),
        )
        self.assertEqual(request.output_directory, Path("device-free-output"))
        self.assertIs(request.runtime_input_lock, self.input_lock)
        self.assertEqual(request.utc_clock(), SERVICE_NOW)
        self.assertEqual(request.monotonic_clock(), 12.5)
        self.assertEqual((result["production_transport_calls"], result["committed_action_count"]), (2, 2))
        self.assertEqual((result["input_count"], result["total_input_count"]), (5, 5))
        self.assertEqual(result["production_state"], "active")
        self.assertEqual(result["active_production_count"], 1)
        self.assertEqual(result["production_duration_seconds"], 21_600)
        self.assertTrue(result["zero_resource_cost_confirmed"])
        self.assertEqual(result["occurrence_key"], SERVICE_OCCURRENCE)
        self.assertEqual(result["native_occurrence_key"], SERVICE_OCCURRENCE)
        self.assertEqual(result["account_id"], SERVICE_BACKEND.account_id)
        self.assertEqual(result["server_id"], SERVICE_BACKEND.server_id)
        self.assertEqual(result["reset_id"], SERVICE_RESET)
        self.assertEqual(result["backend_identity"]["runtime_scope"], SERVICE_BACKEND.runtime_scope)
        self.assertEqual(result["backend_identity"]["backend_reset_id"], SERVICE_BACKEND.reset_id)
        reset_window = derive_static_utc_reset(datetime.fromtimestamp(SERVICE_NOW, timezone.utc))
        self.assertEqual(result["backend_identity"]["reset_start_utc"], reset_window.reset_start_text)
        self.assertEqual(result["backend_identity"]["reset_deadline_utc"], reset_window.reset_deadline_text)
        self.assertEqual(result["terminal_home_state"], "HOME_BASE")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["terminal_home_frame"]["frame_sha256"], "f" * 64)
        self.assertIs(result["accounting_verified"], True)
        self.assertEqual(result["completed_at_utc"], SERVICE_NOW)
        self.assertGreaterEqual(self.checkpoints, 2)

    def test_budget_accounting_home_and_reset_identity_mismatches_block(self):
        invalid_outcomes = (
            _production_outcome(calls=3, input_count=4),
            _production_outcome(input_count=service.MAX_INPUTS + 1),
            _production_outcome(
                input_count=3,
                accounting_verified=False,
                partial_result={"production_transport_calls": 1},
            ),
            _production_outcome(
                calls=1,
                committed=0,
                input_count=3,
            ),
            _production_outcome(
                calls=1,
                input_count=3,
                result_changes={"terminal_home_frame": {"frame_path": "", "frame_sha256": "f" * 64}},
            ),
            _production_outcome(result_changes={"occurrence_key": "occurrence:other"}),
            _production_outcome(
                result_changes={"production_occurrence_key": "occurrence:other"},
            ),
            _production_outcome(
                result_changes={"production_target_identity": "other-target"},
            ),
            _production_outcome(result_changes={"production_state_frame": {}}),
        )
        for outcome in invalid_outcomes:
            with self.subTest(outcome=outcome):
                with self.assertRaises(service.NanoMaterialProductionRunnerError):
                    self.run_route(self.runner(outcome))

        wrong_reset = replace(SERVICE_IDENTITY, reset_id="game-day-2026-10-28")
        with self.assertRaises(service.NanoMaterialProductionRunnerError) as caught:
            self.run_route(self.runner(_production_outcome()), identity=wrong_reset)
        self.assertEqual(caught.exception.partial_result["status"], "blocked")

    def test_success_no_work_and_deferred_results_schedule_from_current_timer(self):
        cases = (
            ("completed", 1, 4),
            ("completed", 0, 2),
            ("deferred", 0, 1),
        )
        for status, calls, inputs in cases:
            with self.subTest(status=status, calls=calls):
                result = self.run_route(
                    self.runner(
                        _production_outcome(status=status, calls=calls, input_count=inputs)
                    )
                )
                self.assertEqual(result["status"], status)
                self.assertEqual(
                    service.nano_material_production_next_due(result, SERVICE_IDENTITY, SERVICE_NOW),
                    SERVICE_NOW + 21_000,
                )
                self.assertEqual(result["production_transport_calls"], calls)
                self.assertTrue(result["terminal_home_verified"])
                self.assertIs(result["identical_retry_denied"], False)
                self.assertIs(result["effect_reconciliation_required"], False)

    def test_next_due_rejects_stale_occurrence_home_and_unknown_timer_evidence(self):
        result = self.run_route(self.runner(_production_outcome()))
        mutations = (
            {"native_occurrence_key": "occurrence:other"},
            {"production_occurrence_key": "occurrence:other"},
            {"production_target_identity": "other-target"},
            {"production_state_frame": {}},
            {"occurrence_key": "occurrence:other"},
            {"terminal_home_verified": False},
            {"terminal_home_state": "UNKNOWN"},
            {"terminal_home_frame": {}},
            {"timer_seconds_remaining": 0},
            {"timer_seconds_remaining": 21_601},
            {"timer_seconds_remaining": True},
            {"timer_seconds_remaining": 1.5},
            {"production_state": "idle"},
            {"active_production_count": 0},
            {"production_duration_seconds": 21_599},
            {"production_duration_seconds": 21_600.0},
            {"zero_resource_cost_confirmed": False},
            {"next_eligible_at": SERVICE_NOW + 20_999},
            {"identical_retry_denied": True},
            {"effect_reconciliation_required": True},
        )
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.nano_material_production_next_due(
                    dict(result, **changes), SERVICE_IDENTITY, SERVICE_NOW,
                )
        other_identity = replace(SERVICE_IDENTITY, account_id="other-account")
        with self.assertRaises(ValueError):
            service.nano_material_production_next_due(result, other_identity, SERVICE_NOW)

    def test_partial_unknown_action_is_unresolved_and_identical_retry_is_denied(self):
        outcome = _production_outcome(
            calls=1,
            committed=0,
            input_count=2,
            accounting_verified=False,
            partial_result={
                "production_transport_calls": 1,
                "committed_action_count": 0,
                "effect_reconciliation_required": True,
            },
            failure="unknown post-action successor",
        )
        with self.assertRaises(service.NanoMaterialProductionRunnerError) as caught:
            self.run_route(self.runner(outcome))
        self.assertEqual(caught.exception.partial_result["status"], "unresolved")
        self.assertEqual(caught.exception.partial_result["production_transport_calls"], 1)
        self.assertEqual(caught.exception.partial_result["committed_action_count"], 0)
        self.assertTrue(caught.exception.partial_result["effect_reconciliation_required"])
        self.assertTrue(caught.exception.partial_result["identical_retry_denied"])

class NanoMaterialProductionExecutionHandlerTests(unittest.TestCase):
    def test_handler_binds_exact_registered_product_and_only_installed_execute(self):
        entry = service.canonical_entry(service.FLOW_ID)
        snapshot = entry.registration
        calls = []
        flow_spec = FlowSpec(service.FLOW_ID, default_enabled=False)
        handler = service.NanoMaterialProductionExecutionHandler(
            snapshot,
            lambda run, facts: calls.append((run, facts)) or "installed-execution",
            flow_spec=flow_spec,
        )
        facts = make_facts(
            accepted_product=service.PRODUCT_ID,
            product_revision=service.PRODUCT_REVISION,
        )
        descriptor = handler.describe()
        self.assertEqual(
            (descriptor.flow_id, descriptor.accepted_product, descriptor.product_revision),
            (service.FLOW_ID, service.PRODUCT_ID, service.PRODUCT_REVISION),
        )
        self.assertTrue(handler.eligibility(facts))
        self.assertFalse(
            handler.eligibility(
                make_facts(
                    accepted_product=service.PRODUCT_ID,
                    product_revision=service.PRODUCT_REVISION,
                    scheduler_eligible=False,
                )
            )
        )
        self.assertEqual(
            handler.execute_run("canonical-run", facts),
            "installed-execution",
        )
        self.assertEqual(calls, [("canonical-run", facts)])
        self.assertFalse(handler.selection_only)
        self.assertEqual((handler.max_inputs, handler.max_actions), (service.MAX_INPUTS, 2))
        self.assertEqual(handler.plan(facts).outcome, NormalizedOutcome.BLOCKED)
        with self.assertRaises(TypeError):
            service.NanoMaterialProductionExecutionHandler(entry, lambda *_: None)
        with self.assertRaises(ValueError):
            service.NanoMaterialProductionExecutionHandler(
                snapshot,
                lambda *_: None,
                flow_spec=FlowSpec("unrelated-flow", default_enabled=False),
            )


if __name__ == "__main__":
    unittest.main()
