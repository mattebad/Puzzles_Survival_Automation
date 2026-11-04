"""Cross-route service safety invariants; no transport or device access."""
from __future__ import annotations

import importlib
import json
import unittest
from unittest.mock import patch

from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.registry import (
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, CANONICAL_FLOW_REGISTRY, ENHANCEMENT_FLOW_ID,
    NOVA_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, RECRUITMENT_FLOW_ID, REGISTRY_PATH,
    SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
    RegisteredDispatchSnapshot, canonical_entry, canonical_flow_specs,
)
from automation_service.service import ServiceError
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tests.support.service_route_contract import (
    EXCEPTIONS, NOT_SERVABLE, ROUTES, RouteRig, _runner_kwarg,
)


class RouteTableTests(unittest.TestCase):
    def test_every_registered_route_is_in_the_contract_or_explicitly_excluded(self):
        self.assertEqual(
            set(ROUTES) | set(NOT_SERVABLE),
            {entry.flow_id for entry in CANONICAL_FLOW_REGISTRY},
        )
        self.assertTrue(set(ROUTES).isdisjoint(NOT_SERVABLE))
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                self.assertEqual(spec.flow_id, flow_id)

    def test_every_exception_names_a_reason_and_an_existing_test(self):
        for (flow_id, invariant), (reason, covered_by) in EXCEPTIONS.items():
            with self.subTest(route=flow_id, invariant=invariant):
                self.assertTrue(reason.strip())
                module, class_name, method_name = covered_by.rsplit(".", 2)
                test_class = getattr(importlib.import_module(module), class_name)
                self.assertTrue(issubclass(test_class, unittest.TestCase))
                self.assertTrue(method_name.startswith("test_"))
                self.assertTrue(callable(getattr(test_class, method_name)))


class DisabledByDefaultTests(unittest.TestCase):
    def test_route_is_disabled_by_default_and_needs_explicit_cli_selection(self):
        specs = canonical_flow_specs()
        self.assertTrue(all(not spec.default_enabled for spec in specs))
        # The rig's database is explicitly enabled; this second store is untouched.
        with RouteRig(self, ROUTES[SUPPLY_FLOW_ID]) as rig:
            with BotStateManager(rig.root / "fresh.sqlite3") as fresh:
                rows = fresh.initialize_flows(specs)
                self.assertFalse(fresh.get_service_enabled())
                self.assertTrue(all(not row.enabled for row in rows))
        legacy = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.assertTrue(all(
            row["registration_status"] == "NOT_REGISTERED" and not row["scheduler_eligible"]
            for row in legacy["flows"].values()
        ))
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["serve"]).flow)
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "disabled_by_default") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    entry = canonical_entry(flow_id)
                    self.assertFalse(entry.spec.default_enabled)
                    self.assertTrue(entry.build_handler().selection_only)
                    self.assertEqual(
                        RegisteredDispatchSnapshot.from_mapping(entry.registration.to_mapping()),
                        entry.registration,
                    )
                    self.assertEqual(
                        parser.parse_args(["serve", "--flow", entry.cli_name]).flow,
                        [entry.cli_name],
                    )
                    if flow_id in {
                        SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID,
                        PERSONAL_MIGHT_FLOW_ID, BIOENHANCER_FLOW_ID,
                    }:
                        adapter = importlib.import_module(
                            "automation_service." + entry.cli_name.replace("-", "_"),
                        )
                        self.assertEqual(
                            (entry.product_id, entry.product_revision),
                            (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION),
                        )
                        if flow_id == BIOENHANCER_FLOW_ID:
                            self.assertEqual(entry.product_revision, "bioenhancer_research-v1")
                            self.assertFalse(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "cooldown_pulse")
                        else:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(
                                entry.descriptor.recurrence_class,
                                RecurrenceClass.DAILY_ONCE_PER_RESET,
                            )
                            self.assertTrue(entry.spec.observation_only_completion)
                    if (flow_id, "explicit_service_selection") not in EXCEPTIONS:
                        with self.assertRaises(ServiceError):
                            rig.service.serve(
                                account_id="account", server_id="server", stop=rig.stop,
                                emit=lambda _report: None,
                            )
                    self.assertEqual(rig.runner.calls, [])


class RestartBeforeDueTests(unittest.TestCase):
    def test_restart_before_due_skips_runner_and_next_reset_runs_once(self):
        work_counts = {
            SUPPLY_FLOW_ID: (4, 1), ULTIMATE_FLOW_ID: (4, 1),
            ENHANCEMENT_FLOW_ID: (6, 3), PERSONAL_MIGHT_FLOW_ID: (6, 1),
        }
        for flow_id, spec in ROUTES.items():
            if (flow_id, "restart_before_due") in EXCEPTIONS:
                continue
            # Preserve Supply's no-work -> work and Ultimate's already-complete
            # -> Flee transitions, in addition to restarting after real work.
            modes = (False, True) if flow_id in {SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID} else (True,)
            for first_work in modes:
                with self.subTest(route=flow_id, first_work=first_work):
                    with RouteRig(self, spec) as rig:
                        if first_work:
                            spec.work(rig.runner)
                        self.assertEqual(rig.once()[0]["status"], "completed")
                        first, = rig.runs()
                        self.assertEqual(first.state, RunState.SUCCEEDED)
                        first_inputs = 0 if flow_id == ULTIMATE_FLOW_ID and not first_work else spec.first_inputs
                        self.assertEqual(len(rig.runner.inputs), first_inputs)
                        due = rig.state.get_flow(flow_id).next_due_at_utc
                        with BotStateManager(rig.path) as restarted:
                            self.assertEqual(rig.once(state=restarted), [])
                        self.assertEqual(len(rig.runner.calls), 1)
                        self.assertEqual(len(rig.runner.inputs), first_inputs)
                        if flow_id == ULTIMATE_FLOW_ID:
                            self.assertEqual(len(rig.runner.connections), 1)
                        spec.work(rig.runner)
                        rig.stop.now = due
                        self.assertEqual(rig.once()[0]["status"], "completed")
                        first, second = rig.runs()
                        self.assertNotEqual(first.reset_id, second.reset_id)
                        self.assertNotEqual(first.occurrence_key, second.occurrence_key)
                        self.assertEqual(second.state, RunState.SUCCEEDED)
                        self.assertEqual(second.terminal_outcome, "complete_for_reset")
                        self.assertEqual(
                            (second.consumed_inputs, second.consumed_actions), work_counts[flow_id],
                        )
                        self.assertEqual(rig.runner.calls[1][1], first.reset_id)
                        self.assertEqual(rig.state.get_flow(flow_id).next_due_at_utc, due + 86400)
                        self.assertEqual(rig.once(), [])
                        self.assertEqual(len(rig.runner.calls), 2)
                        self.assertEqual(len(rig.runner.inputs), first_inputs + spec.first_inputs)
                        if flow_id == ULTIMATE_FLOW_ID:
                            self.assertEqual(len(rig.runner.connections), 2)
                            self.assertEqual(rig.runner.flee_calls, 2 if first_work else 1)
                        if flow_id == ENHANCEMENT_FLOW_ID:
                            self.assertEqual(rig.runner.use_calls, 6)
                        if flow_id == PERSONAL_MIGHT_FLOW_ID:
                            self.assertEqual(rig.runner.praise_calls, 2)


class BorrowedOwnerTests(unittest.TestCase):
    def test_runtime_owner_is_held_during_the_run_and_released_after(self):
        borrowed = {
            SUPPLY_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, BIOENHANCER_FLOW_ID,
        }
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "borrowed_owner") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    checked = []
                    acquire = boundary.RuntimeInputLock.acquire
                    def check_owner():
                        checked.append(True)
                        run, = rig.runs()
                        self.assertEqual(run.state, RunState.RUNNING)
                        flow = rig.state.get_flow(flow_id)
                        self.assertTrue(flow.blocked)
                        self.assertTrue(flow.blocked_reason.startswith(
                            "EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:",
                        ))
                        # Count only service/session acquisition, not this
                        # intentional failed acquisition by a parallel owner.
                        with patch.object(boundary.RuntimeInputLock, "acquire", acquire):
                            with self.assertRaises(boundary.NavigationBoundaryError):
                                with boundary.RuntimeInputLock(owner="contender", invocation_id="parallel"):
                                    self.fail("a parallel runtime owner acquired the lock")
                    if flow_id == CAMPAIGN_FLOW_ID:
                        rig.runner.check_runtime_owner = check_owner
                    else:
                        rig.runner.on_entry = check_owner
                    with patch.object(
                        boundary.RuntimeInputLock, "acquire", autospec=True, side_effect=acquire,
                    ) as acquired:
                        self.assertEqual(rig.once()[0]["status"], "completed")
                        self.assertEqual(checked, [True])
                        if flow_id in borrowed:
                            self.assertEqual(acquired.call_count, 1)
                    with boundary.RuntimeInputLock(owner="next-owner", invocation_id="after-serve"):
                        pass


class PartialResultTests(unittest.TestCase):
    def test_partial_result_keeps_consumption_blocks_restart_and_is_never_retried(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "partial_result") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.partial(rig.runner)
                    reports = rig.once()
                    self.assertEqual(reports[0]["status"], "blocked", reports)
                    run, = rig.runs()
                    self.assertEqual(run.state, RunState.BLOCKED)
                    self.assertEqual(
                        (run.consumed_inputs, run.consumed_actions), spec.partial_counts,
                    )
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)
                    self.assertIsNone(rig.state.get_flow(flow_id).next_due_at_utc)
                    self.assertEqual(len(rig.runner.inputs), spec.partial_counts[0])
                    inputs = list(rig.runner.inputs)
                    with BotStateManager(rig.path) as restarted:
                        self.assertEqual(rig.once(state=restarted)[0]["status"], "paused")
                    self.assertEqual(len(rig.runner.calls), 1)
                    self.assertEqual(rig.runner.inputs, inputs)
                    if flow_id in {ULTIMATE_FLOW_ID, PERSONAL_MIGHT_FLOW_ID}:
                        self.assertEqual(reports[0]["result"]["committed_action_count"], 0)
                    if flow_id == ULTIMATE_FLOW_ID:
                        self.assertEqual(rig.runner.flee_calls, 1)
                    if flow_id == ENHANCEMENT_FLOW_ID:
                        self.assertEqual(rig.runner.use_calls, 1)
                    if flow_id == PERSONAL_MIGHT_FLOW_ID:
                        self.assertEqual(rig.runner.praise_calls, 1)
                    if flow_id == CAMPAIGN_FLOW_ID:
                        self.assertEqual(reports[0]["result"]["committed_ap_effect_count"], 0)
                        self.assertEqual(len(rig.runner.observations), 1)


class GenerationChangeTests(unittest.TestCase):
    def test_generation_change_after_first_input_stops_further_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "generation_change") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    def toggle(_index):
                        rig.state.set_flow_enabled(flow_id, False)
                        rig.state.set_flow_enabled(flow_id, True)
                    rig.runner.on_input = toggle
                    reports = rig.once()
                    self.assertEqual(reports[0]["status"], "blocked", reports)
                    run, = rig.runs()
                    self.assertEqual((run.consumed_inputs, run.consumed_actions), spec.generation_counts)
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertEqual(rig.runner.effects, 0)
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)
                    if flow_id == ULTIMATE_FLOW_ID:
                        self.assertEqual(rig.runner.flee_calls, 0)


class StopSignalsTests(unittest.TestCase):
    def test_stop_after_first_input_prevents_next_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "stop_after_input") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    rig.runner.on_input = lambda _index: rig.stop.set()
                    self.assertEqual(rig.once()[0]["status"], "blocked")
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)

    def test_flow_disable_after_first_input_prevents_next_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "disable_after_input") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    rig.runner.on_input = lambda _index: rig.state.set_flow_enabled(flow_id, False)
                    self.assertEqual(rig.once()[0]["status"], "blocked")
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)

    def test_clock_rollback_after_first_input_prevents_next_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "clock_rollback") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    def rollback(_index):
                        rig.stop.now -= 10
                    rig.runner.on_input = rollback
                    self.assertEqual(rig.once()[0]["status"], "blocked")
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)

    def test_service_lease_loss_prevents_runner_and_releases_owner(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "service_lease_loss") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    with patch.object(rig.state, "renew_service_lease", return_value=None):
                        reports = rig.once()
                    self.assertEqual(rig.runner.calls, [])
                    self.assertEqual(reports[0]["status"], "blocked")
                    self.assertIn("SERVICE_LEASE_LOST", rig.state.get_flow(flow_id).blocked_reason)
                    with boundary.RuntimeInputLock(owner="after-failure", invocation_id="released"):
                        pass


class ResetGuardTests(unittest.TestCase):
    def test_reset_change_during_execution_blocks_the_route(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "reset_guard") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    midnight = (int(rig.stop.now) // 86400 + 1) * 86400
                    rig.stop.now = midnight - 1
                    calls = []
                    def cross_midnight(identity, previous, checkpoint, **options):
                        calls.append(identity)
                        rig.stop.now = midnight + 1
                        checkpoint()
                        self.fail("reset-scoped execution continued after the day changed")
                    setattr(rig.service, _runner_kwarg(flow_id), cross_midnight)
                    reports = rig.once()
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(len(reports), 1)
                    self.assertEqual(reports[0]["status"], "blocked")
                    self.assertIn("RESET_CHANGED_DURING_", reports[0]["reason"])
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)


class MultiRouteTests(unittest.TestCase):
    def test_selected_routes_share_one_serial_runtime_owner(self):
        with RouteRig(self, ROUTES[NOVA_FLOW_ID]) as rig:
            order = []
            active = False
            nova = rig.runner

            def runner(identity, previous, checkpoint):
                nonlocal active
                self.assertFalse(active)
                active = True
                order.append(identity.task_id)
                checkpoint()
                with self.assertRaises(boundary.NavigationBoundaryError):
                    with boundary.RuntimeInputLock(owner="second", invocation_id="contender"):
                        self.fail("parallel runtime owner acquired")
                if identity.task_id == NOVA_TASK_ID:
                    result = nova(identity, previous, checkpoint)
                else:
                    maintenance = NoahMaintenanceState.for_identity(identity)
                    result = {
                        "status": "completed", "terminal_home_verified": True,
                        "time_basis": "utc", "completed_at_utc": rig.stop.now,
                        "maintenance_state": json.loads(maintenance.to_json()),
                        "total_input_count": 3, "recruitment_dispatch_count": 1,
                        "actions_completed": 1,
                    }
                active = False
                return result

            rig.service.recruitment_runner = runner
            rig.service.nova_runner = runner
            rig.service.set_flow_enabled(RECRUITMENT_FLOW_ID, True)
            reports = []

            def emit(report):
                reports.append(report)
                if len(reports) == 2:
                    rig.stop.set()

            rig.service.serve(account_id="account", server_id="server", stop=rig.stop,
                              emit=emit, clock=lambda: rig.stop.now,
                              flow_ids=(RECRUITMENT_FLOW_ID, NOVA_FLOW_ID))
            self.assertEqual(len(order), 2)
            self.assertEqual({item["flow_id"] for item in reports}, {RECRUITMENT_FLOW_ID, NOVA_FLOW_ID})
            self.assertTrue(all(item["status"] == "completed" for item in reports), reports)

    def test_default_remains_recruitment_and_unknown_selection_is_rejected(self):
        with RouteRig(self, ROUTES[NOVA_FLOW_ID]) as rig:
            for flow_ids in (None, ("UNKNOWN",)):
                with self.subTest(flow_ids=flow_ids), self.assertRaises(ServiceError):
                    rig.service.serve(account_id="account", server_id="server", stop=rig.stop,
                                      emit=lambda _report: None, flow_ids=flow_ids)
            self.assertEqual(rig.runner.inputs, [])
            self.assertEqual(build_parser().parse_args(["serve"]).flow, None)
            args = build_parser().parse_args(["serve", "--flow", "nova", "--flow", "recruitment"])
            self.assertEqual(args.flow, ["nova", "recruitment"])

    def test_selected_nova_and_recruitment_do_not_observe_or_dispatch_campaign(self):
        with RouteRig(self, ROUTES[CAMPAIGN_FLOW_ID]) as rig:
            calls = []

            def nova(identity, previous, checkpoint):
                checkpoint()
                calls.append(identity)
                return {
                    "status": "completed", "terminal_home_verified": True,
                    "time_basis": "utc", "completed_at_utc": rig.stop.now,
                    "account_id": identity.account_id, "server_id": identity.server_id,
                    "reset_id": identity.reset_id, "attempts_before": 2, "attempts_after": 1,
                    "praise_transport_calls": 1, "total_input_count": 1,
                    "journal_status": "confirmed", "cooldown_seconds": 300,
                    "next_eligible_at": rig.stop.now + 300,
                }

            def recruitment(identity, previous, checkpoint):
                checkpoint()
                calls.append(identity)
                return {
                    "status": "completed", "terminal_home_verified": True,
                    "time_basis": "utc", "completed_at_utc": rig.stop.now,
                    "maintenance_state": json.loads(NoahMaintenanceState.for_identity(identity).to_json()),
                    "total_input_count": 1, "recruitment_dispatch_count": 1, "actions_completed": 1,
                }

            rig.service.nova_runner = nova
            rig.service.recruitment_runner = recruitment
            for flow_id in (NOVA_FLOW_ID, RECRUITMENT_FLOW_ID):
                rig.service.set_flow_enabled(flow_id, True)
            reports = []

            def emit(report):
                reports.append(report)
                if len(reports) == 2:
                    rig.stop.set()

            rig.service.serve(
                account_id="account", server_id="server", stop=rig.stop, emit=emit,
                clock=lambda: rig.stop.now, flow_ids=(NOVA_FLOW_ID, RECRUITMENT_FLOW_ID),
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual({report["flow_id"] for report in reports}, {NOVA_FLOW_ID, RECRUITMENT_FLOW_ID})
            self.assertTrue(all(report["status"] == "completed" for report in reports), reports)
            self.assertEqual(rig.runner.observations, [])
            self.assertEqual(rig.runner.calls, [])
            self.assertEqual(rig.runner.inputs, [])
            self.assertEqual({run.flow_id for run in rig.runs()}, {NOVA_FLOW_ID, RECRUITMENT_FLOW_ID})


if __name__ == "__main__":
    unittest.main()
