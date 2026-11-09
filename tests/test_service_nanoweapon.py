from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import unittest

from automation_service import nanoweapon as service
from automation_service.contracts import FlowSpec, NormalizedOutcome
from automation_service.native_execution import NativeRouteOutcome
from automation_service.registry import RegisteredDispatchSnapshot
from automation_service.recruitment import recruitment_reset
from tasks.nanoweapon import NORMAL_CRAFT_DURATION_SECONDS
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.scheduler import make_facts

NANOWEAPON_SERVICE_NOW = datetime(2026, 10, 29, 10, tzinfo=timezone.utc).timestamp()
NANOWEAPON_SERVICE_RESET = recruitment_reset(NANOWEAPON_SERVICE_NOW)
NANOWEAPON_SERVICE_BACKEND = derive_resource_runtime_identity(
    resource_fixed_runtime_binding(),
    datetime.fromtimestamp(NANOWEAPON_SERVICE_NOW, timezone.utc),
)
NANOWEAPON_SERVICE_IDENTITY = SchedulerIdentity(
    NANOWEAPON_SERVICE_BACKEND.account_id,
    NANOWEAPON_SERVICE_BACKEND.server_id,
    NANOWEAPON_SERVICE_RESET,
    service.PRODUCT_ID,
)
NANOWEAPON_OCCURRENCE = "occurrence:nanoweapon:2026-10-29"


class _FixedNanoweaponBoundary:
    def __init__(self, flow_id, outcome):
        self.flow_id = flow_id
        self.outcome = outcome
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        request.validate_identity()
        request.checkpoint()
        return self.outcome


def _nanoweapon_outcome(
    *,
    status="completed",
    production_calls=0,
    craft_calls=0,
    total=None,
    committed=None,
    input_count=8,
    accounting_verified=True,
    flow_id=service.FLOW_ID,
    result_changes=None,
    partial_result=None,
    failure=None,
):
    total = production_calls + craft_calls if total is None else total
    committed = total if committed is None else committed
    start_calls = min(craft_calls, 1)
    claim_calls = craft_calls - start_calls
    precraft_balance = 200 if start_calls else 100
    parts_balance = precraft_balance - 100 if start_calls else precraft_balance
    result = {
        "status": status,
        "native_occurrence_key": NANOWEAPON_OCCURRENCE,
        "occurrence_key": NANOWEAPON_OCCURRENCE,
        "production_transport_calls": production_calls,
        "craft_transport_calls": craft_calls,
        "nanoweapon_dispatch_count": total,
        "attempted_action_count": total,
        "committed_action_count": committed,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": True,
        "terminal_home_state": "HOME_BASE",
        "terminal_home_recognized": True,
        "terminal_home_frame": {
            "frame_path": "evidence/terminal-home.png",
            "frame_sha256": "a" * 64,
        },
        "prior_material_production_reconciled": True,
        "production_state": "active",
        "production_active_count": 1,
        "production_duration_seconds": 21_600,
        "production_timer_seconds_remaining": 21_000,
        "production_occurrence_key": NANOWEAPON_OCCURRENCE,
        "production_target_identity": service.NANO_MATERIAL_PRODUCTION_TARGET,
        "production_state_frame": {
            "frame_path": "evidence/production-state.png",
            "frame_sha256": "b" * 64,
            "observed_utc": "2026-11-06T00:00:00Z",
            "capture_ordinal": 7,
        },
        "production_state_observation_sha256": "b" * 64,
        "production_next_eligible_at": NANOWEAPON_SERVICE_NOW + 21_000,
        "zero_resource_cost_confirmed": True,
        "game_day_id": NANOWEAPON_SERVICE_RESET,
        "craft_duration_seconds": NORMAL_CRAFT_DURATION_SECONDS,
        "craft_start_confirmed": bool(start_calls),
        "craft_start_reset_id": NANOWEAPON_SERVICE_RESET,
        "craft_start_transport_calls": start_calls,
        "craft_claim_transport_calls": claim_calls,
        "precraft_nano_parts_balance": precraft_balance,
        "nano_parts_balance": parts_balance,
        "craft_state": "active" if start_calls else "idle",
        "craft_active_count": 1 if start_calls else 0,
        "active_craft_timer_seconds_remaining": NORMAL_CRAFT_DURATION_SECONDS if start_calls else 0,
        "starts_this_reset": 1,
        "due_reason": "current_reset_start",
        "next_eligible_at": 86_400.0 * (
            int(NANOWEAPON_SERVICE_NOW // 86_400.0) + 1
        ),
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
        session_input_count=input_count,
        runtime_input_count=input_count,
        accounting_verified=accounting_verified,
    )


class NanoweaponServiceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.checkpoints = 0
        self.input_lock = object()

    def checkpoint(self):
        self.checkpoints += 1

    def boundary(self, outcome, *, flow_id=service.FLOW_ID):
        return _FixedNanoweaponBoundary(flow_id, outcome)

    def runner(self, outcome, *, flow_id=service.FLOW_ID):
        return service.NanoweaponRunner(
            native=self.boundary(outcome, flow_id=flow_id),
            adb=BLUESTACKS_ADB,
            serial=BLUESTACKS_SERIAL,
            output_directory=Path("device-free-output"),
            utc_clock=lambda: NANOWEAPON_SERVICE_NOW,
            monotonic_clock=lambda: 7.25,
            settle_seconds=0.5,
        )

    def run_route(
        self,
        runner,
        *,
        identity=NANOWEAPON_SERVICE_IDENTITY,
        previous_reset_id="game-day-2026-10-28",
    ):
        return runner(
            identity,
            previous_reset_id,
            self.checkpoint,
            runtime_input_lock=self.input_lock,
            occurrence_key=NANOWEAPON_OCCURRENCE,
        )

    def test_binding_and_mismatched_flow_fail_closed(self):
        with self.assertRaises(service.NanoweaponRunnerError) as absent:
            service.NanoweaponRunner(
                native=None,
                output_directory=Path("device-free-output"),
                utc_clock=lambda: NANOWEAPON_SERVICE_NOW,
            )(
                NANOWEAPON_SERVICE_IDENTITY,
                None,
                self.checkpoint,
                runtime_input_lock=self.input_lock,
                occurrence_key=NANOWEAPON_OCCURRENCE,
            )
        self.assertEqual(absent.exception.partial_result["status"], "blocked")
        self.assertEqual(absent.exception.partial_result["nanoweapon_dispatch_count"], 0)
        with self.assertRaises(ValueError):
            self.runner(_nanoweapon_outcome(), flow_id="other-flow")

        with self.assertRaises(service.NanoweaponRunnerError) as mismatch:
            self.run_route(self.runner(_nanoweapon_outcome(flow_id="other-flow")))
        self.assertEqual(mismatch.exception.partial_result["status"], "blocked")
        self.assertIn("flow mismatch", mismatch.exception.partial_result["reason"])
        with self.assertRaises(ValueError):
            service.NanoweaponRunner(
                output_directory=Path("device-free-output"),
                observation_interval_seconds=service.DEFAULT_OBSERVATION_INTERVAL_SECONDS + 1,
            )

    def test_request_and_output_normalize_fixed_identity_occurrence_and_claim_inclusive_budget(self):
        outcome = _nanoweapon_outcome(
            production_calls=2,
            craft_calls=2,
            input_count=8,
        )
        boundary = self.boundary(outcome)
        runner = service.NanoweaponRunner(
            native=boundary,
            adb=BLUESTACKS_ADB,
            serial=BLUESTACKS_SERIAL,
            output_directory=Path("device-free-output"),
            utc_clock=lambda: NANOWEAPON_SERVICE_NOW,
            monotonic_clock=lambda: 7.25,
            settle_seconds=0.5,
            observation_interval_seconds=service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
        )
        result = self.run_route(runner)
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
                NANOWEAPON_SERVICE_IDENTITY,
                "game-day-2026-10-28",
                NANOWEAPON_OCCURRENCE,
                str(BLUESTACKS_ADB),
                BLUESTACKS_SERIAL,
                service.MAX_INPUTS,
                4,
                0.5,
                {"observation_interval_seconds": service.DEFAULT_OBSERVATION_INTERVAL_SECONDS},
            ),
        )
        self.assertEqual(request.output_directory, Path("device-free-output"))
        self.assertIs(request.runtime_input_lock, self.input_lock)
        self.assertEqual(request.utc_clock(), NANOWEAPON_SERVICE_NOW)
        self.assertEqual(request.monotonic_clock(), 7.25)
        # Two maintenance actions (claim/start) plus two craft actions (claim/start)
        # consume the complete combined action budget; claims are not free budget-wise.
        self.assertEqual(
            (
                result["production_transport_calls"],
                result["craft_transport_calls"],
                result["nanoweapon_dispatch_count"],
                result["committed_action_count"],
                result["craft_start_transport_calls"],
                result["craft_claim_transport_calls"],
            ),
            (2, 2, 4, 4, 1, 1),
        )
        self.assertEqual(result["attempted_action_count"], 4)
        self.assertEqual(result["occurrence_key"], NANOWEAPON_OCCURRENCE)
        self.assertEqual(result["native_occurrence_key"], NANOWEAPON_OCCURRENCE)
        self.assertEqual(result["task_id"], service.PRODUCT_ID)
        self.assertEqual(result["account_id"], NANOWEAPON_SERVICE_BACKEND.account_id)
        self.assertEqual(result["server_id"], NANOWEAPON_SERVICE_BACKEND.server_id)
        self.assertEqual(result["reset_id"], NANOWEAPON_SERVICE_RESET)
        self.assertEqual(result["game_day_id"], NANOWEAPON_SERVICE_RESET)
        self.assertEqual(result["starts_this_reset"], 1)
        self.assertTrue(result["prior_material_production_reconciled"])
        self.assertEqual(result["production_state"], "active")
        self.assertEqual(result["production_active_count"], 1)
        self.assertEqual(result["production_duration_seconds"], 21_600)
        self.assertEqual(result["production_timer_seconds_remaining"], 21_000)
        self.assertEqual(result["production_next_eligible_at"], NANOWEAPON_SERVICE_NOW + 21_000)
        self.assertEqual(result["next_eligible_at"], NANOWEAPON_SERVICE_NOW + 21_000)
        self.assertTrue(result["zero_resource_cost_confirmed"])
        self.assertTrue(result["craft_start_confirmed"])
        self.assertEqual(result["craft_state"], "active")
        self.assertEqual(result["craft_active_count"], 1)
        self.assertEqual(result["active_craft_timer_seconds_remaining"], NORMAL_CRAFT_DURATION_SECONDS)
        self.assertEqual(
            result["precraft_nano_parts_balance"] - result["nano_parts_balance"],
            100,
        )
        self.assertEqual(result["backend_identity"]["runtime_scope"], NANOWEAPON_SERVICE_BACKEND.runtime_scope)
        self.assertEqual(
            result["backend_identity"]["backend_reset_id"],
            NANOWEAPON_SERVICE_BACKEND.reset_id,
        )
        reset_window = derive_static_utc_reset(
            datetime.fromtimestamp(NANOWEAPON_SERVICE_NOW, timezone.utc),
        )
        self.assertEqual(
            result["backend_identity"]["reset_start_utc"],
            reset_window.reset_start_text,
        )
        self.assertEqual(
            result["backend_identity"]["reset_deadline_utc"],
            reset_window.reset_deadline_text,
        )
        self.assertEqual(result["terminal_home_state"], "HOME_BASE")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["terminal_home_frame"]["frame_sha256"], "a" * 64)
        self.assertIs(result["accounting_verified"], True)
        self.assertEqual(result["completed_at_utc"], NANOWEAPON_SERVICE_NOW)
        self.assertGreaterEqual(self.checkpoints, 2)

    def test_budget_accounting_home_and_reset_identity_mismatches_block(self):
        invalid_outcomes = (
            _nanoweapon_outcome(production_calls=3, input_count=5),
            _nanoweapon_outcome(production_calls=2, craft_calls=2, total=3),
            _nanoweapon_outcome(input_count=service.MAX_INPUTS + 1),
            _nanoweapon_outcome(
                accounting_verified=False,
                partial_result={"nanoweapon_dispatch_count": 1},
            ),
            _nanoweapon_outcome(
                production_calls=1,
                committed=0,
            ),
            _nanoweapon_outcome(
                result_changes={
                    "terminal_home_recognized": False,
                    "terminal_home_frame": {},
                }
            ),
            _nanoweapon_outcome(
                result_changes={"native_occurrence_key": "occurrence:other"}
            ),
            _nanoweapon_outcome(
                result_changes={"occurrence_key": "occurrence:other"}
            ),
            _nanoweapon_outcome(result_changes={"attempted_action_count": 1}),
        )
        for outcome in invalid_outcomes:
            with self.subTest(outcome=outcome):
                with self.assertRaises(service.NanoweaponRunnerError):
                    self.run_route(self.runner(outcome))

        wrong_identity = replace(
            NANOWEAPON_SERVICE_IDENTITY,
            reset_id="game-day-2026-10-28",
        )
        boundary = self.boundary(_nanoweapon_outcome())
        runner = service.NanoweaponRunner(
            native=boundary,
            output_directory=Path("device-free-output"),
            utc_clock=lambda: NANOWEAPON_SERVICE_NOW,
        )
        with self.assertRaises(service.NanoweaponRunnerError):
            self.run_route(runner, identity=wrong_identity)
        self.assertEqual(boundary.requests, [])

    def test_native_occurrence_must_match_the_canonical_request(self):
        valid = self.run_route(self.runner(_nanoweapon_outcome(production_calls=1, craft_calls=1)))
        for key in ("occurrence_key", "native_occurrence_key"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                service.nanoweapon_next_due(
                    dict(valid, **{key: "occurrence:other"}),
                    NANOWEAPON_SERVICE_IDENTITY,
                    NANOWEAPON_SERVICE_NOW,
                )

    def test_current_reset_start_schedules_at_earliest_due_and_rejects_stale_reset_proof(self):
        next_reset = 86_400.0 * (
            int(NANOWEAPON_SERVICE_NOW // 86_400.0) + 1
        )
        result = self.run_route(
            self.runner(
                _nanoweapon_outcome(
                    production_calls=1,
                    craft_calls=1,
                    result_changes={
                        "due_reason": "current_reset_start",
                        "craft_start_reset_id": NANOWEAPON_SERVICE_RESET,
                        "next_eligible_at": next_reset,
                    },
                )
            )
        )
        self.assertEqual(
            service.nanoweapon_next_due(
                result, NANOWEAPON_SERVICE_IDENTITY, NANOWEAPON_SERVICE_NOW,
            ),
            NANOWEAPON_SERVICE_NOW + 21_000,
        )
        self.assertEqual(result["craft_start_reset_id"], NANOWEAPON_SERVICE_RESET)
        self.assertEqual(result["craft_start_transport_calls"], 1)
        self.assertEqual(result["craft_claim_transport_calls"], 0)
        claimed = self.run_route(
            self.runner(
                _nanoweapon_outcome(
                    production_calls=1,
                    craft_calls=1,
                    result_changes={
                        "due_reason": "current_reset_start",
                        "craft_start_confirmed": True,
                        "craft_start_transport_calls": 0,
                        "craft_claim_transport_calls": 1,
                        "precraft_nano_parts_balance": 100,
                        "nano_parts_balance": 0,
                        "craft_state": "idle",
                        "craft_active_count": 0,
                        "active_craft_timer_seconds_remaining": 0,
                        "next_eligible_at": next_reset,
                    },
                )
            )
        )
        self.assertEqual(
            service.nanoweapon_next_due(
                claimed, NANOWEAPON_SERVICE_IDENTITY, NANOWEAPON_SERVICE_NOW,
            ),
            NANOWEAPON_SERVICE_NOW + 21_000,
        )
        self.assertEqual(claimed["craft_claim_transport_calls"], 1)
        invalid_current = (
            {"craft_start_confirmed": False},
            {"game_day_id": "game-day-2026-10-28"},
            {"craft_start_reset_id": "game-day-2026-10-28"},
            {"craft_state": "idle", "craft_active_count": 0, "active_craft_timer_seconds_remaining": 0},
            {"production_state": "unknown"},
            {"production_active_count": 0},
            {"production_duration_seconds": 21_599},
            {"production_duration_seconds": 21_600.0},
            {"craft_duration_seconds": NORMAL_CRAFT_DURATION_SECONDS * 1.0},
            {"production_next_eligible_at": NANOWEAPON_SERVICE_NOW + 20_999},
            {"production_timer_seconds_remaining": 0},
            {"production_timer_seconds_remaining": True},
            {"production_timer_seconds_remaining": 21_601},
            {"production_occurrence_key": "occurrence:other"},
            {"production_target_identity": "other"},
            {"production_state_frame": {}},
            {"production_state_observation_sha256": "c" * 64},
            {"prior_material_production_reconciled": False},
            {"active_craft_timer_seconds_remaining": True},
            {"active_craft_timer_seconds_remaining": NORMAL_CRAFT_DURATION_SECONDS + 1},
            {"starts_this_reset": 0},
        )
        for changes in invalid_current:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.nanoweapon_next_due(
                    dict(result, **changes),
                    NANOWEAPON_SERVICE_IDENTITY,
                    NANOWEAPON_SERVICE_NOW,
                )

    def test_shortage_and_previous_reset_active_timer_use_exact_deadlines(self):
        for balance in (0, 99):
            with self.subTest(balance=balance):
                result = self.run_route(
                    self.runner(
                        _nanoweapon_outcome(
                            status="deferred",
                            production_calls=1,
                            result_changes={
                                "due_reason": "known_material_shortage",
                                "starts_this_reset": 0,
                                "nano_parts_balance": balance,
                                "observation_interval_seconds": service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
                                "next_eligible_at": NANOWEAPON_SERVICE_NOW
                                + service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
                            },
                        )
                    )
                )
                self.assertEqual(
                    service.nanoweapon_next_due(
                        result, NANOWEAPON_SERVICE_IDENTITY, NANOWEAPON_SERVICE_NOW,
                    ),
                    NANOWEAPON_SERVICE_NOW + service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
                )
                self.assertEqual(result["nano_parts_balance"], balance)
                self.assertEqual(result["craft_transport_calls"], 0)

        remaining = 12_345
        prior_reset = "game-day-2026-10-28"
        result = self.run_route(
            self.runner(
                _nanoweapon_outcome(
                    status="deferred",
                    production_calls=1,
                    result_changes={
                        "due_reason": "previous_reset_active_timer",
                        "starts_this_reset": 0,
                        "craft_start_reset_id": prior_reset,
                        "craft_state": "active",
                        "craft_active_count": 1,
                        "active_craft_timer_seconds_remaining": remaining,
                        "craft_start_confirmed": True,
                        "craft_start_transport_calls": 0,
                        "craft_claim_transport_calls": 0,
                        "next_eligible_at": NANOWEAPON_SERVICE_NOW + remaining,
                    },
                )
            )
        )
        self.assertEqual(
            service.nanoweapon_next_due(
                result, NANOWEAPON_SERVICE_IDENTITY, NANOWEAPON_SERVICE_NOW,
            ),
            NANOWEAPON_SERVICE_NOW + remaining,
        )
        self.assertEqual(result["craft_start_reset_id"], prior_reset)
        self.assertEqual(result["craft_transport_calls"], 0)

    def test_unknown_state_has_no_due_and_cadence_evidence_is_exact(self):

        shortage = self.run_route(
            self.runner(
                _nanoweapon_outcome(
                    status="deferred",
                    result_changes={
                        "due_reason": "known_material_shortage",
                        "starts_this_reset": 0,
                        "nano_parts_balance": 99,
                        "observation_interval_seconds": service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
                        "next_eligible_at": NANOWEAPON_SERVICE_NOW
                        + service.DEFAULT_OBSERVATION_INTERVAL_SECONDS,
                    },
                )
            )
        )
        with self.assertRaises(ValueError):
            service.nanoweapon_next_due(
                dict(shortage, due_reason="unknown_state", next_eligible_at=None),
                NANOWEAPON_SERVICE_IDENTITY,
                NANOWEAPON_SERVICE_NOW,
            )
        with self.assertRaises(service.NanoweaponRunnerError):
            self.run_route(
                self.runner(
                    _nanoweapon_outcome(
                        status="deferred",
                        result_changes={"due_reason": "unknown_state"},
                    )
                )
            )
        invalid_shortage = (
            {"nano_parts_balance": 100},
            {"observation_interval_seconds": service.DEFAULT_OBSERVATION_INTERVAL_SECONDS + 1},
            {
                "craft_start_transport_calls": 1,
                "craft_transport_calls": 1,
                "nanoweapon_dispatch_count": 1,
                "committed_action_count": 1,
            },
            {
                "craft_state": "active",
                "craft_active_count": 1,
                "active_craft_timer_seconds_remaining": NORMAL_CRAFT_DURATION_SECONDS,
            },
            {"next_eligible_at": NANOWEAPON_SERVICE_NOW + 1},
        )
        for changes in invalid_shortage:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.nanoweapon_next_due(
                    dict(shortage, **changes),
                    NANOWEAPON_SERVICE_IDENTITY,
                    NANOWEAPON_SERVICE_NOW,
                )

        active = self.run_route(
            self.runner(
                _nanoweapon_outcome(
                    status="deferred",
                    result_changes={
                        "due_reason": "previous_reset_active_timer",
                        "starts_this_reset": 0,
                        "craft_state": "active",
                        "craft_active_count": 1,
                        "craft_start_confirmed": True,
                        "craft_start_transport_calls": 0,
                        "craft_claim_transport_calls": 0,
                        "craft_start_reset_id": "game-day-2026-10-28",
                        "active_craft_timer_seconds_remaining": 12_345,
                        "next_eligible_at": NANOWEAPON_SERVICE_NOW + 12_345,
                    },
                )
            )
        )
        invalid_active = (
            {"craft_start_reset_id": NANOWEAPON_SERVICE_RESET},
            {"craft_start_reset_id": "game-day-2026-10-30"},
            {"active_craft_timer_seconds_remaining": True},
            {"active_craft_timer_seconds_remaining": NORMAL_CRAFT_DURATION_SECONDS + 1},
            {
                "craft_state": "idle",
                "craft_active_count": 0,
                "active_craft_timer_seconds_remaining": 0,
            },
            {
                "craft_start_confirmed": True,
                "craft_start_transport_calls": 1,
                "craft_claim_transport_calls": 0,
                "craft_transport_calls": 1,
                "nanoweapon_dispatch_count": 1,
                "committed_action_count": 1,
            },
        )
        for changes in invalid_active:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.nanoweapon_next_due(
                    dict(active, **changes),
                    NANOWEAPON_SERVICE_IDENTITY,
                    NANOWEAPON_SERVICE_NOW,
                )

        wrong_identity = replace(
            NANOWEAPON_SERVICE_IDENTITY,
            account_id="other-fixed-slot",
        )
        with self.assertRaises(ValueError):
            service.nanoweapon_next_due(
                active, wrong_identity, NANOWEAPON_SERVICE_NOW,
            )

    def test_existing_active_slots_need_no_new_effect_or_start_quote(self):
        result = self.run_route(self.runner(_nanoweapon_outcome(
            status="deferred", production_calls=0, craft_calls=0,
            result_changes={
                "zero_resource_cost_confirmed": False,
                "production_duration_seconds": None,
                "nano_parts_balance": None,
                "precraft_nano_parts_balance": None,
                "craft_start_confirmed": False,
                "craft_start_reset_id": None,
                "starts_this_reset": 0,
                "craft_state": "active",
                "craft_active_count": 1,
                "active_craft_timer_seconds_remaining": 42000,
                "due_reason": "observed_active_timer",
            },
        )))
        self.assertEqual(result["committed_action_count"], 0)
        self.assertEqual(result["next_eligible_at"], NANOWEAPON_SERVICE_NOW + 21000)

    def test_confirmed_claim_then_non_effect_failure_is_not_unknown(self):
        outcome = _nanoweapon_outcome(
            status="blocked", craft_calls=1, committed=1,
            failure="navigation_failed_after_claim",
            result_changes={"craft_claim_transport_calls": 1, "craft_start_transport_calls": 0},
        )
        with self.assertRaises(service.NanoweaponRunnerError) as caught:
            self.run_route(self.runner(outcome))
        partial = caught.exception.partial_result
        self.assertEqual(partial["committed_action_count"], 1)
        self.assertEqual(partial["status"], "blocked")
        self.assertFalse(partial["effect_reconciliation_required"])
        self.assertFalse(partial["identical_retry_denied"])

    def test_partial_unknown_dispatch_denies_identical_retry(self):
        outcome = _nanoweapon_outcome(
            production_calls=1,
            craft_calls=1,
            accounting_verified=False,
            partial_result={
                "production_transport_calls": 1,
                "craft_transport_calls": 1,
                "nanoweapon_dispatch_count": 2,
                "attempted_action_count": 2,
                "committed_action_count": 1,
                "effect_reconciliation_required": True,
            },
            failure="unknown post-craft successor",
        )
        with self.assertRaises(service.NanoweaponRunnerError) as caught:
            self.run_route(self.runner(outcome))
        partial = caught.exception.partial_result
        self.assertEqual(partial["status"], "unresolved")
        self.assertEqual(partial["nanoweapon_dispatch_count"], 2)
        self.assertEqual(partial["attempted_action_count"], 2)
        self.assertEqual(partial["committed_action_count"], 1)
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])

    def test_unknown_attempt_count_stays_unknown_while_confirmed_count_is_preserved(self):
        outcome = _nanoweapon_outcome(
            accounting_verified=False,
            result_changes={
                "production_transport_calls": None,
                "craft_transport_calls": None,
                "nanoweapon_dispatch_count": None,
                "attempted_action_count": None,
                "attempted_action_count_known": False,
                "committed_action_count": 1,
                "effect_reconciliation_required": True,
                "identical_retry_denied": True,
            },
            partial_result={
                "production_transport_calls": None,
                "craft_transport_calls": None,
                "nanoweapon_dispatch_count": None,
                "attempted_action_count": None,
                "committed_action_count": 1,
                "effect_reconciliation_required": True,
            },
            failure="attempt count unknown after native dispatch",
        )
        with self.assertRaises(service.NanoweaponRunnerError) as caught:
            self.run_route(self.runner(outcome))
        partial = caught.exception.partial_result
        self.assertEqual(partial["status"], "unresolved")
        self.assertIsNone(partial["nanoweapon_dispatch_count"])
        self.assertIsNone(partial["attempted_action_count"])
        self.assertEqual(partial["committed_action_count"], 1)
        self.assertTrue(partial["effect_reconciliation_required"])
        self.assertTrue(partial["identical_retry_denied"])

class NanoweaponExecutionHandlerTests(unittest.TestCase):
    def test_handler_binds_exact_registered_product_and_only_installed_execute(self):
        entry = service.canonical_entry(service.FLOW_ID)
        snapshot = entry.registration
        calls = []
        flow_spec = FlowSpec(service.FLOW_ID, default_enabled=False)
        handler = service.NanoweaponExecutionHandler(
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
        self.assertEqual((handler.max_inputs, handler.max_actions), (service.MAX_INPUTS, 4))
        self.assertEqual(handler.plan(facts).outcome, NormalizedOutcome.BLOCKED)
        with self.assertRaises(TypeError):
            service.NanoweaponExecutionHandler(entry, lambda *_: None)
        with self.assertRaises(ValueError):
            service.NanoweaponExecutionHandler(
                snapshot,
                lambda *_: None,
                flow_spec=FlowSpec("unrelated-flow", default_enabled=False),
            )


if __name__ == "__main__":
    unittest.main()
