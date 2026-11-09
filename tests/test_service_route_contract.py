"""Cross-route service safety invariants; no transport or device access."""
from __future__ import annotations

from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import importlib
import io
import json
import unittest
from unittest.mock import patch

from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, CANONICAL_FLOW_REGISTRY,
    DAILY_REWARDS_FLOW_ID, DAILY_SHOPS_FLOW_ID, ENHANCEMENT_FLOW_ID,
    FOOD_FARM_BOOST_FLOW_ID, HALL_OF_WAR_FLOW_ID, HERO_DUEL_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID, NOVA_FLOW_ID,
    PERSONAL_MIGHT_FLOW_ID, RECOMMENDED_RESEARCH_FLOW_ID, RECRUITMENT_FLOW_ID,
    REGISTRY_PATH, RESOURCE_ITEM_FLOW_ID, RUINS_FLOW_ID, SUPPLY_FLOW_ID,
    TROOP_TRAINING_FLOW_ID, ULTIMATE_FLOW_ID, WALI_UPGRADE_FLOW_ID, canonical_entry,
    canonical_flow_specs,
)
from automation_service.alliance_donation import alliance_donation_next_due
from automation_service.alliance_shop import alliance_shop_next_due
from automation_service.daily_shops import daily_shops_next_due
from automation_service.nano_material_production import nano_material_production_next_due
from automation_service.nanoweapon import nanoweapon_next_due
from automation_service.service import ServiceError
from automation_service.state import BotStateManager, RunState
from scripts import navigation_development_boundary as boundary
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tasks.nanoweapon import NANO_PARTS_REQUIRED
from tasks.scheduler_task_result import SchedulerTaskOutcome
from tasks.purchases_disabled import ALLIANCE_WEEKLY_ITEMS, ALLIANCE_WEEKLY_SHOP
from tests.support.service_route_contract import (
    EXCEPTIONS, NOT_SERVABLE, ROUTES, RouteRig, _runner_kwarg,
)
from tests.support.service_route_fakes import (
    GuardedHallOfWarRunner, GuardedNanoMaterialProductionRunner,
    GuardedNanoweaponRunner, GuardedTroopTrainingRunner,
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
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            parser.parse_args(["serve"])
        self.assertEqual(error.exception.code, 2)
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "disabled_by_default") in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    entry = canonical_entry(flow_id)
                    self.assertFalse(entry.spec.default_enabled)
                    self.assertEqual(
                        parser.parse_args(["serve", "--flow", entry.cli_name]).flow,
                        [entry.cli_name],
                    )
                    if flow_id in {
                        SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID,
                        PERSONAL_MIGHT_FLOW_ID, BIOENHANCER_FLOW_ID,
                        DAILY_REWARDS_FLOW_ID, RESOURCE_ITEM_FLOW_ID,
                        ALLIANCE_DONATION_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
                        DAILY_SHOPS_FLOW_ID, NANO_MATERIAL_PRODUCTION_FLOW_ID,
                        NANOWEAPON_FLOW_ID, HERO_DUEL_FLOW_ID,
                        RECOMMENDED_RESEARCH_FLOW_ID, FOOD_FARM_BOOST_FLOW_ID,
                        TROOP_TRAINING_FLOW_ID, HALL_OF_WAR_FLOW_ID, WALI_UPGRADE_FLOW_ID,
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
                        elif flow_id == NANO_MATERIAL_PRODUCTION_FLOW_ID:
                            self.assertFalse(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "timer")
                            self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.TIMER)
                        elif flow_id == NANOWEAPON_FLOW_ID:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "cooldown_pulse")
                            self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.COOLDOWN)
                        elif flow_id == HALL_OF_WAR_FLOW_ID:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "cooldown_pulse")
                            self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.COOLDOWN)
                            self.assertTrue(entry.spec.observation_only_completion)
                        elif flow_id == TROOP_TRAINING_FLOW_ID:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "timer")
                            self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.TIMER)
                            self.assertTrue(entry.spec.observation_only_completion)
                        elif flow_id == DAILY_REWARDS_FLOW_ID or flow_id in {
                            ALLIANCE_DONATION_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
                            DAILY_SHOPS_FLOW_ID, HERO_DUEL_FLOW_ID,
                            RECOMMENDED_RESEARCH_FLOW_ID, FOOD_FARM_BOOST_FLOW_ID,
                            WALI_UPGRADE_FLOW_ID,
                        }:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(entry.descriptor.cadence, "cooldown_pulse")
                            self.assertEqual(entry.descriptor.recurrence_class, RecurrenceClass.COOLDOWN)
                            self.assertTrue(entry.spec.observation_only_completion)
                        else:
                            self.assertTrue(entry.descriptor.reset_scoped)
                            self.assertEqual(
                                entry.descriptor.recurrence_class,
                                RecurrenceClass.DAILY_ONCE_PER_RESET,
                            )
                            self.assertTrue(entry.spec.observation_only_completion)
                    with self.assertRaises(ServiceError):
                        rig.service.serve(
                            account_id="account", server_id="server", stop=rig.stop,
                            emit=lambda _report: rig.stop.set(),
                        )
                    self.assertEqual(rig.runner.calls, [])





class RestartBeforeDueTests(unittest.TestCase):
    def test_restart_before_due_skips_runner_and_next_reset_runs_once(self):
        work_counts = {
            SUPPLY_FLOW_ID: (4, 1), ULTIMATE_FLOW_ID: (4, 1),
            ENHANCEMENT_FLOW_ID: (6, 3), PERSONAL_MIGHT_FLOW_ID: (6, 1),
            RESOURCE_ITEM_FLOW_ID: (4, 1),
            RUINS_FLOW_ID: (8, 2), ALLIANCE_HELP_FLOW_ID: (20, 10),
            ALLIANCE_DONATION_FLOW_ID: (40, 10),
            ALLIANCE_SHOP_FLOW_ID: (24, 1), DAILY_SHOPS_FLOW_ID: (48, 2),
            HERO_DUEL_FLOW_ID: (20, 3), FOOD_FARM_BOOST_FLOW_ID: (4, 2),
            HALL_OF_WAR_FLOW_ID: (18, 2), WALI_UPGRADE_FLOW_ID: (12, 3),
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


class RuinsProgressionTests(unittest.TestCase):
    def test_multiple_stage_results_commit_separately_and_budget_pause_defers(self):
        for paused, outcomes in (
            (False, ("success", "failure")),
            (True, ("success", "success")),
        ):
            with self.subTest(paused=paused), RouteRig(self, ROUTES[RUINS_FLOW_ID]) as rig:
                rig.runner.challenge_results = outcomes
                rig.runner.challenge_paused = paused
                report, = rig.once()
                run, = rig.runs()
                assert run is not None
                result = report["result"]
                self.assertEqual(run.consumed_actions, 3)
                self.assertEqual(len(result["challenge_stages"]), 2)
                self.assertEqual(len(result["newly_claimed_chests"]), 1)
                self.assertFalse(result["effect_reconciliation_required"])
                self.assertEqual(run.state, RunState.DEFERRED if paused else RunState.SUCCEEDED)
                if paused:
                    flow = rig.state.get_flow(RUINS_FLOW_ID)
                    assert flow is not None and flow.next_due_at_utc is not None
                    self.assertFalse(flow.blocked)
                    self.assertLess(
                        flow.next_due_at_utc,
                        (datetime.fromtimestamp(rig.stop.now, timezone.utc)
                         .replace(hour=0, minute=0, second=0, microsecond=0)
                         + timedelta(days=1)).timestamp(),
                    )


class BorrowedOwnerTests(unittest.TestCase):
    def test_runtime_owner_is_held_during_the_run_and_released_after(self):
        borrowed = {
            SUPPLY_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
            BIOENHANCER_FLOW_ID, DAILY_REWARDS_FLOW_ID, RESOURCE_ITEM_FLOW_ID,
            RUINS_FLOW_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_DONATION_FLOW_ID,
            ALLIANCE_SHOP_FLOW_ID, DAILY_SHOPS_FLOW_ID,
            NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID,
            HALL_OF_WAR_FLOW_ID, TROOP_TRAINING_FLOW_ID, WALI_UPGRADE_FLOW_ID,
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
                        reports = rig.once()
                        self.assertEqual(reports[0]["status"], "completed")
                        self.assertEqual(len(rig.runner.inputs), spec.first_inputs)
                        self.assertEqual(checked, [True])
                        if flow_id in {DAILY_REWARDS_FLOW_ID, RESOURCE_ITEM_FLOW_ID}:
                            run, = rig.runs()
                            self.assertEqual(run.consumed_actions, 1)
                        if flow_id in {
                            RUINS_FLOW_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_DONATION_FLOW_ID,
                            ALLIANCE_SHOP_FLOW_ID, DAILY_SHOPS_FLOW_ID,
                            NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID,
                            HALL_OF_WAR_FLOW_ID, TROOP_TRAINING_FLOW_ID, WALI_UPGRADE_FLOW_ID,
                        }:
                            run, = rig.runs()
                            action_budgets = {
                                RUINS_FLOW_ID: 13, ALLIANCE_HELP_FLOW_ID: 10,
                                ALLIANCE_DONATION_FLOW_ID: 10, ALLIANCE_SHOP_FLOW_ID: 1,
                                DAILY_SHOPS_FLOW_ID: 2, NANO_MATERIAL_PRODUCTION_FLOW_ID: 2,
                                NANOWEAPON_FLOW_ID: 4,
                                HALL_OF_WAR_FLOW_ID: 2, TROOP_TRAINING_FLOW_ID: 12,
                                WALI_UPGRADE_FLOW_ID: 6,
                            }
                            self.assertEqual(run.max_actions, action_budgets[flow_id])
                            self.assertLessEqual(run.consumed_actions, action_budgets[flow_id])
                        if flow_id in {
                            DAILY_REWARDS_FLOW_ID, RESOURCE_ITEM_FLOW_ID,
                            RUINS_FLOW_ID, ALLIANCE_HELP_FLOW_ID,
                            ALLIANCE_DONATION_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
                            DAILY_SHOPS_FLOW_ID, NANO_MATERIAL_PRODUCTION_FLOW_ID,
                            NANOWEAPON_FLOW_ID,
                            HALL_OF_WAR_FLOW_ID, TROOP_TRAINING_FLOW_ID, WALI_UPGRADE_FLOW_ID,
                        }:
                            run, = rig.runs()
                            transport_fields = {
                                DAILY_REWARDS_FLOW_ID: "reward_claim_transport_calls",
                                RESOURCE_ITEM_FLOW_ID: "item_use_transport_calls",
                                RUINS_FLOW_ID: "ruins_dispatch_count",
                                ALLIANCE_HELP_FLOW_ID: "help_transport_calls",
                                ALLIANCE_DONATION_FLOW_ID: "donation_transport_calls",
                                ALLIANCE_SHOP_FLOW_ID: "purchase_transport_calls",
                                DAILY_SHOPS_FLOW_ID: "purchase_transport_calls",
                                NANO_MATERIAL_PRODUCTION_FLOW_ID: "production_transport_calls",
                                NANOWEAPON_FLOW_ID: "nanoweapon_dispatch_count",
                                HALL_OF_WAR_FLOW_ID: "hall_of_war_dispatch_count",
                                TROOP_TRAINING_FLOW_ID: "training_dispatch_count",
                                WALI_UPGRADE_FLOW_ID: "total_action_count",
                            }
                            expected_calls = {
                                DAILY_REWARDS_FLOW_ID: 1,
                                RESOURCE_ITEM_FLOW_ID: 1,
                                RUINS_FLOW_ID: 2,
                                ALLIANCE_HELP_FLOW_ID: 10,
                                ALLIANCE_DONATION_FLOW_ID: 10,
                                ALLIANCE_SHOP_FLOW_ID: 1,
                                DAILY_SHOPS_FLOW_ID: 2,
                                NANO_MATERIAL_PRODUCTION_FLOW_ID: 1,
                                NANOWEAPON_FLOW_ID: 2,
                                HALL_OF_WAR_FLOW_ID: 2, TROOP_TRAINING_FLOW_ID: 4,
                                WALI_UPGRADE_FLOW_ID: 3,
                            }
                            result = reports[0]["result"]
                            expected = expected_calls[flow_id]
                            self.assertEqual(result[transport_fields[flow_id]], expected)
                            self.assertEqual(run.consumed_actions, expected)
                            if flow_id == RUINS_FLOW_ID:
                                self.assertEqual(result["actions_completed"], expected)
                            else:
                                self.assertEqual(result["committed_action_count"], expected)
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
                    expected_state = (
                        RunState.FAILED
                        if spec.partial_outcome is SchedulerTaskOutcome.RECONCILIATION_REQUIRED
                        else RunState.BLOCKED
                    )
                    self.assertEqual(run.state, expected_state)
                    self.assertEqual(run.terminal_outcome, spec.partial_outcome.value)
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
                    if flow_id == DAILY_REWARDS_FLOW_ID:
                        self.assertEqual(
                            reports[0]["result"]["reward_claim_transport_calls"], 1,
                        )
                        self.assertEqual(reports[0]["result"]["committed_action_count"], 0)
                    elif flow_id == RESOURCE_ITEM_FLOW_ID:
                        self.assertEqual(
                            reports[0]["result"]["item_use_transport_calls"], 1,
                        )
                        self.assertEqual(reports[0]["result"]["committed_action_count"], 0)
                    elif flow_id == RUINS_FLOW_ID:
                        result = reports[0]["result"]
                        self.assertEqual(result["challenge_transport_calls"], 1)
                        self.assertEqual(result["chest_claim_transport_calls"], 0)
                        self.assertEqual(result["ruins_dispatch_count"], 1)
                    elif flow_id == ALLIANCE_HELP_FLOW_ID:
                        result = reports[0]["result"]
                        self.assertEqual(result["help_transport_calls"], 3)
                        self.assertEqual(result["confirmed_request_count"], 2)
                        self.assertEqual(result["committed_action_count"], 2)
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                    elif flow_id in {
                        ALLIANCE_DONATION_FLOW_ID, ALLIANCE_SHOP_FLOW_ID, DAILY_SHOPS_FLOW_ID,
                    }:
                        result = reports[0]["result"]
                        attempted_field = (
                            "donation_transport_calls"
                            if flow_id == ALLIANCE_DONATION_FLOW_ID
                            else "purchase_transport_calls"
                        )
                        expected_attempts, expected_confirmed = {
                            ALLIANCE_DONATION_FLOW_ID: (3, 2),
                            ALLIANCE_SHOP_FLOW_ID: (1, 0),
                            DAILY_SHOPS_FLOW_ID: (2, 1),
                        }[flow_id]
                        self.assertEqual(result[attempted_field], expected_attempts)
                        self.assertEqual(result["committed_action_count"], expected_confirmed)
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                    elif flow_id == NANO_MATERIAL_PRODUCTION_FLOW_ID:
                        result = reports[0]["result"]
                        self.assertEqual(
                            (result["production_transport_calls"],
                             result["attempted_action_count"],
                             result["committed_action_count"]),
                            (1, 1, 0),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertFalse(result["terminal_home_verified"])
                        self.assertNotIn("next_eligible_at", result)
                        self.assertEqual(
                            set(result["last_action_evidence"]), {"before", "after"},
                        )
                    elif flow_id == NANOWEAPON_FLOW_ID:
                        result = reports[0]["result"]
                        self.assertEqual(
                            (result["production_transport_calls"], result["craft_transport_calls"],
                             result["nanoweapon_dispatch_count"], result["attempted_action_count"],
                             result["committed_action_count"]),
                            (1, 1, 2, 2, 1),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertFalse(result["terminal_home_verified"])
                        self.assertNotIn("next_eligible_at", result)
                        self.assertTrue(result["prior_material_production_reconciled"])
                    elif flow_id == HERO_DUEL_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["entry_transport_calls"], result["duel_dispatch_count"],
                             result["flee_transport_calls"], result["committed_action_count"]),
                            (1, 1, 0, 0),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertIsNone(result["final_free_entries_remaining"])
                    elif flow_id == RECOMMENDED_RESEARCH_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["research_transport_calls"], result["total_action_count"],
                             result["committed_action_count"]),
                            (1, 1, 0),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                    elif flow_id == FOOD_FARM_BOOST_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["collection_transport_calls"], result["collection_count"],
                             result["boost_transport_calls"], result["food_farm_dispatch_count"]),
                            (1, 0, 0, 1),
                        )
                        self.assertFalse(result["collection_effect_accounted"])
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                    elif flow_id == HALL_OF_WAR_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["dispatch_transport_calls"], result["reward_claim_transport_calls"],
                             result["hall_of_war_dispatch_count"], result["committed_action_count"]),
                            (1, 0, 1, 0),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertFalse(result["terminal_home_verified"])
                    elif flow_id == TROOP_TRAINING_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["training_start_transport_calls"], result["training_dispatch_count"],
                             result["committed_action_count"]),
                            (2, 2, 1),
                        )
                        self.assertEqual(result["resource_box_dispatch_count"], 0)
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertFalse(result["terminal_home_verified"])
                    elif flow_id == WALI_UPGRADE_FLOW_ID:
                        result = rig.runner.last_result
                        self.assertEqual(
                            (result["total_action_count"], result["committed_action_count"],
                             result["confirmed_upgrades"], result["evolution_committed_count"]),
                            (2, 1, 1, 0),
                        )
                        self.assertTrue(result["effect_reconciliation_required"])
                        self.assertTrue(result["identical_retry_denied"])
                        self.assertFalse(result["terminal_home_verified"])
                    if flow_id == ULTIMATE_FLOW_ID:
                        self.assertEqual(rig.runner.flee_calls, 1)


class GenerationChangeTests(unittest.TestCase):
    def test_generation_change_after_first_input_stops_further_input(self):
        self._assert_generation_change(service_generation=False)

    def test_service_generation_change_after_first_input_stops_further_input(self):
        self._assert_generation_change(service_generation=True)

    def _assert_generation_change(self, *, service_generation):
        invariant = "service_generation_change" if service_generation else "generation_change"
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, invariant) in EXCEPTIONS:
                    continue
                with RouteRig(self, spec) as rig:
                    spec.work(rig.runner)
                    transitions = []

                    def bump(index):
                        if index != 0:
                            return
                        before = rig.state.get_service() if service_generation else rig.state.get_flow(flow_id)
                        running_before, = rig.runs()
                        if service_generation:
                            rig.state.set_service_enabled(True)
                        else:
                            rig.state.set_flow_enabled(flow_id, True)
                        after = rig.state.get_service() if service_generation else rig.state.get_flow(flow_id)
                        running_after, = rig.runs()
                        validation = rig.state.validate_dispatch(
                            running_after.run_id, now_utc_epoch=rig.stop.now,
                            allow_executor_marker=True,
                        )
                        transitions.append((before, after, running_before.state, running_after.state, validation))

                    rig.runner.on_input = bump
                    reports = rig.once()
                    self.assertEqual(len(transitions), 1)
                    before, after, state_before, state_after, validation = transitions[0]
                    self.assertTrue(before.enabled)
                    self.assertTrue(after.enabled)
                    self.assertEqual(after.generation, before.generation + 1)
                    self.assertEqual(state_before, RunState.RUNNING)
                    self.assertEqual(state_after, RunState.RUNNING)
                    self.assertEqual(reports[0]["status"], "blocked", reports)
                    self.assertEqual(reports[0]["reason"], "GENERATION_MISMATCH")
                    run, = rig.runs()
                    self.assertEqual((run.consumed_inputs, run.consumed_actions), spec.generation_counts)
                    self.assertEqual(len(rig.runner.inputs), 1)
                    self.assertEqual(rig.runner.effects, 0)
                    self.assertTrue(rig.state.get_flow(flow_id).blocked)
                    self.assertFalse(validation.valid)
                    self.assertEqual(
                        validation.reason,
                        "SERVICE_GENERATION_MISMATCH" if service_generation else "FLOW_GENERATION_MISMATCH",
                    )
                    if flow_id == ULTIMATE_FLOW_ID:
                        self.assertEqual(rig.runner.flee_calls, 0)

    def test_disable_then_reenable_after_first_input_stops_further_input(self):
        for flow_id, spec in ROUTES.items():
            with self.subTest(route=flow_id):
                if (flow_id, "disable_then_reenable") in EXCEPTIONS:
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

    def test_omitted_and_unknown_selection_are_rejected(self):
        with RouteRig(self, ROUTES[RECRUITMENT_FLOW_ID]) as rig:
            for flow_ids in (None, (), ("UNKNOWN",)):
                with self.subTest(flow_ids=flow_ids), self.assertRaises(ServiceError):
                    rig.service.serve(account_id="account", server_id="server", stop=rig.stop,
                                      emit=lambda _report: rig.stop.set(), flow_ids=flow_ids)
            self.assertEqual(rig.runner.calls, [])
            self.assertEqual(rig.runner.inputs, [])
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                build_parser().parse_args(["serve"])
            self.assertEqual(error.exception.code, 2)
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


class BatchCSemanticContractTests(unittest.TestCase):
    def test_donation_retains_confirmed_prefix_across_restart_until_attempts_return(self):
        for reason, interval in (("no_attempts", 1800), ("insufficient_resource", 300)):
            with self.subTest(reason=reason), RouteRig(
                self, ROUTES[ALLIANCE_DONATION_FLOW_ID],
            ) as rig:
                runner = rig.runner
                runner.defer_after = 2
                runner.defer_reason = reason
                rig.once()
                result = runner.last_result
                self.assertEqual(
                    (result["donation_transport_calls"], result["committed_action_count"],
                     result["daily_committed_action_count"]),
                    (2, 2, 2),
                )
                self.assertEqual(result["status"], "deferred")
                due = alliance_donation_next_due(
                    result, runner.last_identity, result["started_at_utc"],
                )
                self.assertEqual(due, rig.stop.now + interval)
                with BotStateManager(rig.path) as restarted:
                    self.assertEqual(rig.once(state=restarted), [])
                self.assertEqual(len(runner.calls), 1)
                runner.defer_after = None
                rig.stop.now = due
                rig.once()
                resumed = runner.last_result
                self.assertEqual(
                    (resumed["donation_transport_calls"], resumed["committed_action_count"],
                     resumed["daily_committed_action_count"]),
                    (8, 8, 10),
                )
                self.assertEqual(runner.confirmed_ordinals, list(range(1, 11)))
                self.assertEqual(len(set(runner.confirmed_ordinals)), 10)

    def test_alliance_shop_fallback_mapping_is_one_exact_purchase_with_numeric_guards(self):
        with RouteRig(self, ROUTES[ALLIANCE_SHOP_FLOW_ID]) as rig:
            rig.once()
            runner = rig.runner
            result = runner.last_result
            offer = result["selected_offer"]
            selection = result["selection_evidence"]
            self.assertEqual(
                set(selection),
                {"weekly_inventory", "weekly_offers", "fallback_inventory", "fallback_offer"},
            )
            self.assertEqual(
                (selection["weekly_inventory"]["complete"],
                 selection["weekly_inventory"]["reason"]),
                (True, ""),
            )
            weekly, = selection["weekly_offers"]
            self.assertEqual(
                (weekly["shop_identity"], weekly["item_identity"], weekly["unit_price"],
                 weekly["balance"], weekly["stock"], weekly["available"]),
                (ALLIANCE_WEEKLY_SHOP, ALLIANCE_WEEKLY_ITEMS[0], 1000, 0, 12, True),
            )
            fallback = selection["fallback_offer"]
            self.assertEqual(
                (fallback["shop_identity"], fallback["item_identity"], fallback["rarity"],
                 fallback["unit_price"], fallback["balance"], fallback["stock"],
                 fallback["available"]),
                ("Other", "1★ Gear Enhance Material", 1, 1000, 79999, 10055, True),
            )
            self.assertEqual(
                (selection["fallback_inventory"]["complete"],
                 selection["fallback_inventory"]["reason"]),
                (True, ""),
            )
            self.assertEqual(runner.selection_choice.reason, "AFFORDABLE_EXACT_FALLBACK")
            self.assertEqual(offer["offer_identity"], fallback["offer_identity"])
            self.assertEqual(
                (result["purchase_transport_calls"], result["committed_action_count"]),
                (1, 1),
            )
            self.assertEqual(
                (offer["shop_identity"], offer["item_identity"], offer["rarity"],
                 offer["quantity"], offer["unit_price"], offer["total"],
                 offer["balance_before"]),
                ("Other", "1★ Gear Enhance Material", 1, 1, 1000, 1000, 79999),
            )
            self.assertEqual(
                alliance_shop_next_due(result, runner.last_identity, result["started_at_utc"]),
                (int(rig.stop.now) // 86400 + 1) * 86400,
            )
            for field, value in (("quantity", 2), ("total", 999)):
                with self.subTest(field=field):
                    invalid = dict(result)
                    invalid["selected_offer"] = dict(offer, **{field: value})
                    with self.assertRaises(ValueError):
                        alliance_shop_next_due(
                            invalid, runner.last_identity, result["started_at_utc"],
                        )

    def test_daily_shop_shortage_resumes_other_tab_without_rebuy_and_checks_quantity_total(self):
        with RouteRig(self, ROUTES[DAILY_SHOPS_FLOW_ID]) as rig:
            runner = rig.runner
            runner.rare_earth_unaffordable = True
            rig.once()
            first = runner.last_result
            self.assertEqual(first["status"], "deferred")
            self.assertEqual(first["tab_results"]["ruins"]["status"], "confirmed")
            self.assertEqual(first["tab_results"]["rare_earth"]["status"], "deferred")
            self.assertEqual(
                (first["purchase_transport_calls"], first["committed_action_count"]),
                (1, 1),
            )
            due = daily_shops_next_due(
                first, runner.last_identity, first["started_at_utc"],
            )
            self.assertEqual(due, rig.stop.now + 300)
            for known_status in ("confirmed", "already_confirmed"):
                partial = dict(first)
                partial["tab_results"] = {
                    name: dict(row) for name, row in first["tab_results"].items()
                }
                partial["tab_results"]["ruins"]["status"] = known_status
                partial["tab_results"]["rare_earth"].update(
                    status="blocked", reason="RARE_EARTH_SELECTION_NOT_RECOGNIZED",
                )
                partial["purchase_transport_calls"] = int(known_status == "confirmed")
                partial["committed_action_count"] = int(known_status == "confirmed")
                with self.subTest(known_status=known_status):
                    self.assertEqual(
                        daily_shops_next_due(
                            partial, runner.last_identity, partial["started_at_utc"],
                        ),
                        due,
                    )
                    self.assertFalse(partial["effect_reconciliation_required"])
            runner.rare_earth_unaffordable = False
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(runner.calls), 1)
            rig.stop.now = due
            rig.once()
            resumed = runner.last_result
            self.assertEqual(
                (resumed["tab_results"]["ruins"]["status"],
                 resumed["tab_results"]["rare_earth"]["status"]),
                ("already_confirmed", "confirmed"),
            )
            self.assertEqual(
                (resumed["purchase_transport_calls"], resumed["committed_action_count"]),
                (1, 1),
            )
            self.assertEqual(
                daily_shops_next_due(
                    resumed, runner.last_identity, resumed["started_at_utc"],
                ),
                (int(rig.stop.now) // 86400 + 1) * 86400,
            )
            for field, value in (("quantity", 99), ("total", 1499)):
                with self.subTest(tab="ruins", field=field):
                    invalid = dict(first)
                    invalid["tab_results"] = {
                        name: dict(row) for name, row in first["tab_results"].items()
                    }
                    invalid["tab_results"]["ruins"][field] = value
                    with self.assertRaises(ValueError):
                        daily_shops_next_due(
                            invalid, runner.last_identity, first["started_at_utc"],
                        )
            for field, value in (("quantity", 14), ("total", 206999)):
                with self.subTest(tab="rare_earth", field=field):
                    invalid = dict(resumed)
                    invalid["tab_results"] = {
                        name: dict(row) for name, row in resumed["tab_results"].items()
                    }
                    invalid["tab_results"]["rare_earth"][field] = value
                    with self.assertRaises(ValueError):
                        daily_shops_next_due(
                            invalid, runner.last_identity, resumed["started_at_utc"],
                        )

    def test_c_unknown_dispatches_keep_attempts_distinct_from_confirmed_actions(self):
        cases = (
            (ALLIANCE_DONATION_FLOW_ID, "donation_transport_calls", 3, 2),
            (ALLIANCE_SHOP_FLOW_ID, "purchase_transport_calls", 1, 0),
            (DAILY_SHOPS_FLOW_ID, "purchase_transport_calls", 2, 1),
        )
        for flow_id, calls_field, attempts, committed in cases:
            with self.subTest(flow_id=flow_id), RouteRig(self, ROUTES[flow_id]) as rig:
                spec = ROUTES[flow_id]
                spec.partial(rig.runner)
                report, = rig.once()
                self.assertEqual(report["status"], "blocked", report)
                result = rig.runner.last_result
                self.assertEqual(result[calls_field], attempts)
                self.assertEqual(result["committed_action_count"], committed)
                self.assertTrue(result["effect_reconciliation_required"])
                self.assertTrue(result["identical_retry_denied"])
                with BotStateManager(rig.path) as restarted:
                    self.assertEqual(rig.once(state=restarted)[0]["status"], "paused")
                self.assertEqual(len(rig.runner.calls), 1)
                self.assertEqual(len(rig.runner.inputs), spec.partial_counts[0])


class BatchDSemanticContractTests(unittest.TestCase):
    def assert_action_proof(self, proof):
        self.assertEqual(set(proof), {"before", "after"})
        for frame in proof.values():
            self.assertTrue(frame["frame_path"])
            self.assertEqual(len(frame["frame_sha256"]), 64)
            self.assertTrue(frame["observed_utc"])
        self.assertNotEqual(proof["before"]["frame_sha256"], proof["after"]["frame_sha256"])
        self.assertLess(proof["before"]["capture_ordinal"], proof["after"]["capture_ordinal"])

    def test_production_timer_survives_service_restart_across_reset_and_restarts_once(self):
        with RouteRig(self, ROUTES[NANO_MATERIAL_PRODUCTION_FLOW_ID]) as rig:
            midnight = (int(rig.stop.now) // 86400 + 1) * 86400
            rig.stop.now = midnight - 3600
            started = rig.stop.now
            first_report, = rig.once()
            runner = rig.runner
            first_result = runner.last_result
            first_run, = rig.runs()
            self.assertEqual(first_report["status"], "completed")
            self.assertEqual(
                (first_result["production_transport_calls"],
                 first_result["committed_action_count"],
                 first_result["production_state"],
                 first_result["active_production_count"],
                 first_result["production_duration_seconds"],
                 first_result["zero_resource_cost_confirmed"]),
                (1, 1, "active", 1, 21600, True),
            )
            due = nano_material_production_next_due(
                first_result, runner.last_identity, started,
            )
            self.assertEqual(due, started + 21600)
            self.assertEqual(rig.state.get_flow(NANO_MATERIAL_PRODUCTION_FLOW_ID).next_due_at_utc, due)

            rig.stop.now = midnight + 1800
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(runner.calls), 1)
            rig.stop.now = due
            second_report, = rig.once()
            second_result = runner.last_result
            first_run, second_run = rig.runs()
            self.assertEqual(second_report["status"], "completed")
            self.assertNotEqual(first_run.reset_id, second_run.reset_id)
            self.assertNotEqual(first_run.occurrence_key, second_run.occurrence_key)
            self.assertEqual(runner.transition_order, ["start", "claim", "start"])
            self.assertEqual(
                (second_result["production_transport_calls"],
                 second_result["committed_action_count"]),
                (2, 2),
            )
            self.assertEqual(set(second_result["production_action_evidence"]), {"claim", "start"})
            for proof in second_result["production_action_evidence"].values():
                self.assert_action_proof(proof)
            self.assertEqual(
                nano_material_production_next_due(
                    second_result, runner.last_identity, due,
                ),
                due + 21600,
            )

    def test_production_active_timer_refresh_has_no_transport_work(self):
        with RouteRig(self, ROUTES[NANO_MATERIAL_PRODUCTION_FLOW_ID]) as rig:
            runner = rig.runner
            runner.production_state = "active"
            runner.production_due_at = rig.stop.now + 3600
            started = rig.stop.now
            rig.once()
            result = runner.last_result
            self.assertEqual(
                (result["status"], result["production_transport_calls"],
                 result["committed_action_count"], result["active_production_count"]),
                ("deferred", 0, 0, 1),
            )
            self.assertEqual(result["production_action_evidence"], {})
            self.assertEqual(
                nano_material_production_next_due(result, runner.last_identity, started),
                started + 3600,
            )

    def test_production_unknown_claim_blocks_without_retry_or_due(self):
        with RouteRig(self, ROUTES[NANO_MATERIAL_PRODUCTION_FLOW_ID]) as rig:
            runner = rig.runner
            runner.production_state = "complete"
            runner.partial = True
            runner.partial_action = "claim"
            report, = rig.once()
            result = runner.last_result
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(
                (
                    result["status"], result["production_transport_calls"],
                    result["attempted_action_count"], result["attempted_action_count_known"],
                    result["committed_action_count"],
                ),
                ("unresolved", 1, 1, True, 0),
            )
            self.assertTrue(result["effect_reconciliation_required"])
            self.assertTrue(result["identical_retry_denied"])
            self.assertFalse(result["terminal_home_verified"])
            self.assertNotIn("next_eligible_at", result)
            self.assertEqual(runner.transition_order, ["claim"])
            self.assertEqual(set(result["production_action_evidence"]), {"claim"})
            self.assert_action_proof(result["production_action_evidence"]["claim"])
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted)[0]["status"], "paused")
            self.assertEqual(len(runner.calls), 1)

    def test_nanoweapon_same_visit_claims_then_starts_exact_craft_and_resumes_pulse(self):
        with RouteRig(self, ROUTES[NANOWEAPON_FLOW_ID]) as rig:
            started = rig.stop.now
            runner = rig.runner
            runner.craft_state = "complete"
            runner.craft_due_at = started
            first_report, = rig.once()
            first = runner.last_result
            first_run, = rig.runs()
            self.assertEqual(first_report["status"], "completed")
            self.assertEqual(runner.phase_order[:2], ["production-maintenance", "normal-craft"])
            self.assertEqual(
                runner.action_order, ["production:start", "craft:claim", "craft:start"],
            )
            self.assertEqual(
                (first["production_transport_calls"], first["craft_transport_calls"],
                 first["craft_claim_transport_calls"], first["craft_start_transport_calls"],
                 first["nanoweapon_dispatch_count"], first["attempted_action_count"],
                 first["committed_action_count"]),
                (1, 2, 1, 1, 3, 3, 3),
            )
            self.assertEqual(
                (first["precraft_nano_parts_balance"], first["nano_parts_balance"],
                 first["craft_duration_seconds"], first["craft_start_reset_id"],
                 first["starts_this_reset"], first["craft_start_confirmed"]),
                (200, 100, 43200, first_run.reset_id, 1, True),
            )
            self.assertEqual(first["production_occurrence_key"], first["occurrence_key"])
            self.assertEqual(set(first["production_action_evidence"]), {"start"})
            self.assert_action_proof(first["production_action_evidence"]["start"])
            self.assert_action_proof(first["craft_claim_action_evidence"])
            self.assert_action_proof(first["craft_start_action_evidence"])
            self.assertNotEqual(
                first["craft_claim_action_evidence"], first["craft_start_action_evidence"],
            )
            self.assertTrue(first["craft_claim_confirmed"])
            self.assertEqual(first["craft_claim_occurrence_key"], first["occurrence_key"])
            due = nanoweapon_next_due(first, runner.last_identity, started)
            self.assertEqual(due, started + 21600)

            rig.stop.now = due - 1
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(runner.calls), 1)
            rig.stop.now = due
            rig.once()
            second = runner.last_result
            first_run, second_run = rig.runs()
            self.assertEqual(first_run.reset_id, second_run.reset_id)
            self.assertNotEqual(first_run.occurrence_key, second_run.occurrence_key)
            self.assertEqual(
                (second["production_transport_calls"], second["craft_transport_calls"],
                 second["craft_start_transport_calls"], second["starts_this_reset"],
                 second["nano_parts_balance"]),
                (2, 0, 0, 1, 100),
            )
            self.assertEqual(
                nanoweapon_next_due(second, runner.last_identity, due),
                due + 21600,
            )

    def test_nanoweapon_known_shortage_uses_bounded_observation_due(self):
        for craft_state, balance in (
            ("idle", NANO_PARTS_REQUIRED - 1),
            ("complete", NANO_PARTS_REQUIRED - 1),
            ("complete", None),
        ):
            with self.subTest(craft_state=craft_state, balance=balance), RouteRig(
                self, ROUTES[NANOWEAPON_FLOW_ID],
            ) as rig:
                runner = rig.runner
                runner.craft_state = craft_state
                runner.nano_parts_balance = balance
                runner.materials_affordable = False
                started = rig.stop.now
                rig.once()
                result = runner.last_result
                claims = int(craft_state == "complete")
                self.assertEqual(
                    (result["production_transport_calls"], result["craft_transport_calls"],
                     result["craft_claim_transport_calls"], result["craft_start_transport_calls"],
                     result["committed_action_count"], result["nano_parts_balance"],
                     result["craft_state"]),
                    (1, claims, claims, 0, 1 + claims, balance, "idle"),
                )
                if claims:
                    self.assertTrue(result["craft_claim_confirmed"])
                    self.assert_action_proof(result["craft_claim_action_evidence"])
                else:
                    self.assertNotIn("craft_claim_action_evidence", result)
                self.assertNotIn("craft_start_action_evidence", result)
                self.assertIsNone(result["precraft_nano_parts_balance"])
                self.assertEqual(result["due_reason"], "known_material_shortage")
                self.assertEqual(
                    nanoweapon_next_due(result, runner.last_identity, started),
                    started + 300,
                )

    def test_nanoweapon_previous_reset_craft_timer_prevents_duplicate_start(self):
        with RouteRig(self, ROUTES[NANOWEAPON_FLOW_ID]) as rig:
            runner = rig.runner
            started = rig.stop.now
            current_day = datetime.fromtimestamp(started, timezone.utc).date()
            runner.production_state = "active"
            runner.production_due_at = started + 7200
            runner.craft_state = "active"
            runner.craft_due_at = started + 9000
            runner.craft_start_reset_id = (
                f"game-day-{(current_day - timedelta(days=1)).isoformat()}"
            )
            rig.once()
            result = runner.last_result
            self.assertEqual(
                (result["production_transport_calls"], result["craft_transport_calls"],
                 result["craft_start_transport_calls"], result["starts_this_reset"],
                 result["due_reason"]),
                (0, 0, 0, 0, "previous_reset_active_timer"),
            )
            self.assertEqual(
                nanoweapon_next_due(result, runner.last_identity, started),
                started + 7200,
            )

    def test_nanoweapon_manual_active_craft_observes_timers_without_effects(self):
        with RouteRig(self, ROUTES[NANOWEAPON_FLOW_ID]) as rig:
            runner = rig.runner
            started = rig.stop.now
            runner.production_state = runner.craft_state = "active"
            runner.production_due_at = started + 7200
            runner.craft_due_at = started + 3600
            runner.nano_parts_balance = None
            rig.once()
            result = runner.last_result
            self.assertEqual(
                (result["production_transport_calls"], result["craft_transport_calls"],
                 result["committed_action_count"], result["starts_this_reset"],
                 result["due_reason"], result["craft_start_confirmed"],
                 result["craft_start_reset_id"]),
                (0, 0, 0, 0, "observed_active_timer", False, None),
            )
            self.assertTrue(result["prior_material_production_reconciled"])
            self.assertEqual(result["production_action_evidence"], {})
            self.assertNotIn("craft_start_action_evidence", result)
            self.assertEqual(
                nanoweapon_next_due(result, runner.last_identity, started), started + 3600,
            )

    def test_known_completed_claim_survives_later_unsent_failure(self):
        for flow_id in (NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID):
            with self.subTest(flow_id=flow_id), RouteRig(self, ROUTES[flow_id]) as rig:
                runner = rig.runner
                if flow_id == NANO_MATERIAL_PRODUCTION_FLOW_ID:
                    runner.production_state = "complete"
                    claim_input = runner.CLAIM_INPUT
                else:
                    runner.production_state = "active"
                    runner.production_due_at = rig.stop.now + 7200
                    runner.craft_state = "complete"
                    claim_input = runner.CRAFT_CLAIM_INPUT

                def fail_after_claim(index):
                    if index == claim_input:
                        raise RuntimeError("navigation failed before any subsequent effect input")

                runner.on_input = fail_after_claim
                report, = rig.once()
                result = report["result"]
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["attempted_action_count"], 1)
                self.assertEqual(result["committed_action_count"], 1)
                self.assertFalse(result["effect_reconciliation_required"])
                self.assertFalse(result["identical_retry_denied"])
                self.assertNotIn("next_eligible_at", result)
                if flow_id == NANO_MATERIAL_PRODUCTION_FLOW_ID:
                    self.assertEqual(result["production_state"], "idle")
                    self.assertEqual(set(result["production_action_evidence"]), {"claim"})
                    self.assert_action_proof(result["production_action_evidence"]["claim"])
                else:
                    self.assertEqual(result["craft_claim_transport_calls"], 1)
                    self.assertEqual(result["craft_start_transport_calls"], 0)
                    self.assertTrue(result["craft_claim_confirmed"])
                    self.assert_action_proof(result["craft_claim_action_evidence"])
                    self.assertNotIn("craft_start_action_evidence", result)




class BatchESemanticContractTests(unittest.TestCase):
    def test_hero_duel_proves_defense_and_three_free_loss_cycles(self):
        with RouteRig(self, ROUTES[HERO_DUEL_FLOW_ID]) as rig:
            report, = rig.once()
            result = rig.runner.last_result
            expected_defense = ["ulrik", "mccarty", "meyers", "marlowe", "ephraim"]
            self.assertEqual(report["status"], "completed")
            self.assertEqual(result["expected_defense_hero_ids"], expected_defense)
            self.assertTrue(result["defense_save_confirmed"])
            self.assertEqual(result["defense_selection_transport_calls"], 5)
            self.assertEqual(result["defense_save_transport_calls"], 1)
            self.assertEqual(result["canonical_confirmed_cycle_ordinals"], [1, 2, 3])
            self.assertEqual(
                (result["duel_dispatch_count"], result["entry_transport_calls"],
                 result["flee_transport_calls"], result["flee_confirmed_count"],
                 result["committed_action_count"]),
                (3, 3, 3, 3, 3),
            )
            self.assertEqual(len(result["cycle_proofs"]), 3)
            for ordinal, proof in enumerate(result["cycle_proofs"], 1):
                with self.subTest(cycle=ordinal):
                    self.assertEqual(proof["ordinal"], ordinal)
                    self.assertEqual(proof["event_identity"], result["hero_duel_event_identity"])
                    self.assertEqual(proof["free_after"], proof["free_before"] - 1)
                    self.assertTrue(proof["battle_board_verified"])
                    self.assertTrue(proof["exit_confirmed"])
                    self.assertTrue(proof["flee_confirmed"])
                    self.assertTrue(proof["loss_result_seen"])
                    self.assertTrue(proof["tap_to_continue_confirmed"])
            self.assertEqual(rig.runner.effects, 3)

    def test_hero_duel_exhausted_manual_allowance_defers_without_fabricated_cycles(self):
        with RouteRig(self, ROUTES[HERO_DUEL_FLOW_ID]) as rig:
            rig.runner.duel_mode = "exhausted"
            rig.runner.input_count = 0
            rig.once()
            result = rig.runner.last_result
            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["final_free_entries_remaining"], 0)
            self.assertEqual(result["ui_inferred_prior_uses"], 3)
            self.assertEqual(result["canonical_confirmed_cycle_ordinals"], [])
            self.assertEqual(result["cycle_proofs"], [])
            self.assertEqual((rig.runner.actions, rig.runner.effects), (0, 0))
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(result["identical_retry_denied"])
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(rig.runner.calls), 1)

    def test_research_start_uses_first_idle_affordable_recommendation_only(self):
        with RouteRig(self, ROUTES[RECOMMENDED_RESEARCH_FLOW_ID]) as rig:
            started = rig.stop.now
            report, = rig.once()
            result = rig.runner.last_result
            self.assertEqual(report["status"], "completed")
            self.assertEqual(
                (result["status"], result["first_recommendation_identity"],
                 result["recommendation_position"], result["queue1_state"]),
                ("completed", "troop-load-ii", 1, "idle"),
            )
            self.assertEqual(result["target_identity"], "recommended-research:troop-load-ii:detail-research-button")
            self.assertTrue(result["requirements_scrolled"])
            self.assertTrue(result["prerequisites_met"])
            self.assertFalse(result["queue2_activate_tapped"])
            self.assertFalse(result["research_now_tapped"])
            self.assertEqual(result["research_transport_calls"], 1)
            self.assertEqual(result["committed_action_count"], 1)
            self.assertGreater(result["remaining_seconds"], 0)
            self.assertEqual(result["active_technology"], result["first_recommendation_identity"])
            self.assertTrue(all(
                result["exact_resource_prebalances"][resource] >= cost
                for resource, cost in result["exact_resource_costs"].items()
            ))
            next_due = importlib.import_module(
                "automation_service.recommended_research",
            ).recommended_research_next_due
            self.assertEqual(
                next_due(result, rig.runner.last_identity, started),
                result["completed_at_utc"] + result["remaining_seconds"],
            )
            for changes in (
                {"active_technology": "other-technology"},
                {"remaining_seconds": 0},
                {"target_identity": "recommended-research:other-technology:detail-research-button"},
            ):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    next_due(
                        {**result, **changes}, rig.runner.last_identity, started,
                    )

    def test_research_busy_and_shortage_defer_without_substitute_actions(self):
        for mode in ("deferred_busy", "deferred_shortage"):
            with self.subTest(mode=mode), RouteRig(
                self, ROUTES[RECOMMENDED_RESEARCH_FLOW_ID],
            ) as rig:
                rig.runner.research_mode = mode
                rig.once()
                result = rig.runner.last_result
                self.assertEqual(result["status"], "deferred")
                self.assertEqual(
                    (result["research_transport_calls"], result["committed_action_count"],
                     result["total_action_count"]),
                    (0, 0, 0),
                )
                if mode == "deferred_busy":
                    self.assertEqual(
                        (result["queue1_state"], result["queue1_remaining_seconds"]),
                        ("busy", 731),
                    )
                else:
                    self.assertEqual(result["queue1_state"], "idle")
                    self.assertEqual(result["shortages"], [{"resource": "food", "shortage": 80}])
                    self.assertFalse(result["research_now_tapped"])
                    self.assertFalse(result["queue2_activate_tapped"])
                    self.assertEqual(
                        result["exact_resource_costs"]["food"]
                        - result["exact_resource_balances"]["food"],
                        80,
                    )

    def test_research_start_is_not_replayed_after_same_reset_restart(self):
        with RouteRig(self, ROUTES[RECOMMENDED_RESEARCH_FLOW_ID]) as rig:
            rig.once()
            first, = rig.runs()
            first_due = rig.state.get_flow(RECOMMENDED_RESEARCH_FLOW_ID).next_due_at_utc
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(rig.runner.calls), 1)
            rig.stop.now = first_due
            with BotStateManager(rig.path) as restarted:
                reports = rig.once(state=restarted)
            self.assertEqual(len(reports), 1)
            result = rig.runner.last_result
            second, = rig.runs()[1:]
            self.assertEqual(first.reset_id, second.reset_id)
            self.assertNotEqual(first.occurrence_key, second.occurrence_key)
            self.assertEqual(result["status"], "already_complete")
            self.assertEqual(
                (result["research_transport_calls"], result["committed_action_count"]),
                (0, 0),
            )
            self.assertTrue(result["already_confirmed"])
            self.assertEqual(rig.runner.attempted_actions, 0)

    def test_food_farm_accounts_food_tick_item_boost_and_unknown_retry(self):
        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            report, = rig.once()
            result = rig.runner.last_result
            self.assertEqual(report["status"], "completed")
            self.assertEqual(
                (result["collection_transport_calls"], result["collection_count"],
                 result["collection_effect_accounted"], result["boost_transport_calls"],
                 result["food_farm_dispatch_count"]),
                (1, 1, True, 1, 2),
            )
            self.assertEqual(result["collection_successor"], "hud_tick")
            self.assertGreater(
                int(result["collection_food_after"]), int(result["collection_food_before"]),
            )
            self.assertEqual(result["boost_decision"], "owned_item")
            self.assertEqual(result["boost_duration_seconds"], 86_400)
            self.assertGreater(result["boost_timer_remaining_seconds"], 0)
            self.assertEqual(result["boost_timer_farm_identity"], result["farm_identity"])
            self.assertEqual(result["boost_action"]["status"], "confirmed")
            self.assertEqual((rig.runner.actions, rig.runner.effects), (2, 2))

        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            rig.runner.collection_already_confirmed = True
            rig.once()
            result = rig.runner.last_result
            self.assertEqual(
                (result["collection_transport_calls"], result["collection_count"],
                 result["collection_effect_accounted"], result["boost_transport_calls"],
                 result["food_farm_dispatch_count"]),
                (0, 1, True, 1, 1),
            )
            self.assertIsNone(result["collection_food_before"])
            self.assertIsNone(result["collection_food_after"])

        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            rig.runner.farm_mode = "boost_unresolved"
            rig.once()
            result = rig.runner.last_result
            self.assertEqual(
                (result["collection_transport_calls"], result["collection_count"],
                 result["boost_transport_calls"], result["food_farm_dispatch_count"]),
                (1, 1, 1, 2),
            )
            self.assertTrue(result["collection_effect_accounted"])
            self.assertEqual(result["boost_action"]["status"], "unresolved")
            self.assertTrue(result["effect_reconciliation_required"])
            self.assertTrue(result["identical_retry_denied"])
            self.assertEqual((rig.runner.actions, rig.runner.effects), (2, 1))
            inputs = list(rig.runner.inputs)
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted)[0]["status"], "paused")
            self.assertEqual(len(rig.runner.calls), 1)
            self.assertEqual(rig.runner.inputs, inputs)

    def test_food_farm_settled_first_tap_boosts_without_inventing_collection_credit(self):
        for mode, successor in (("settled_radial", "radial"), ("settled_home", "home")):
            with self.subTest(mode=mode), RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
                rig.runner.farm_mode = mode
                report, = rig.once()
                result = rig.runner.last_result
                self.assertEqual(report["status"], "completed")
                self.assertEqual(result["collection_action"]["status"], "confirmed")
                self.assertEqual(result["collection_action"]["reason"], "FOOD_FARM_FIRST_TAP_SETTLED")
                self.assertEqual(result["collection_successor"], successor)
                self.assertTrue(result["collection_effect_accounted"])
                self.assertEqual(result["collection_count"], 0)
                self.assertEqual(result["boost_action"]["status"], "confirmed")
                self.assertEqual((rig.runner.actions, rig.runner.effects), (2, 1))
                self.assertFalse(rig.runner.collection_credit_by_reset[rig.runner.last_identity.reset_id])
                with BotStateManager(rig.path) as restarted:
                    self.assertEqual(rig.once(state=restarted), [])
                self.assertEqual(len(rig.runner.calls), 1)

    def test_food_farm_diamonds_require_exact_eligible_offer_and_same_daily_boost_key(self):
        from dataclasses import replace
        from tasks.resource_boost_disabled import (
            FoodFarmBoostChoice, FoodFarmBoostObservation, food_farm_boost_decision,
        )

        observation = FoodFarmBoostObservation(
            screen_state="FOOD_FARM_BOOST_PANEL", farm_identity="home.building.farm.02",
            resource_type="FOOD", boost_active=False, active_remaining_seconds=None,
            option_duration_seconds=86_400, option_item_name="Food Farm Output Boost 24h",
            option_item_cost=1, option_item_visible=True, option_item_usable=True,
            inventory_item_name=None, inventory_item_count=None, inventory_observed=False,
            diamond_option_visible=True, diamond_item_name="Food Farm Output Boost 24h",
            diamond_duration_seconds=86_400, diamond_cost=37, diamond_balance=100,
            diamond_offer_actionable=True, source_frame_sha256="a" * 64,
            evidence_refs=("synthetic:food-farm-current-panel",),
        )
        self.assertEqual(food_farm_boost_decision(observation).choice, FoodFarmBoostChoice.OWNED_ITEM)
        self.assertEqual(
            food_farm_boost_decision(replace(observation, option_item_usable=False)).choice,
            FoodFarmBoostChoice.DIAMONDS,
        )
        self.assertEqual(
            food_farm_boost_decision(replace(observation, option_item_usable=None)).choice,
            FoodFarmBoostChoice.BLOCKED,
        )

        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            rig.once()
            owned_boost_key = rig.runner.last_result["boost_action_key"]

        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            rig.runner.farm_mode = "diamond_guard"
            rig.once()
            result = rig.runner.last_result
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["boost_decision"], "diamonds")
            self.assertEqual(result["collection_count"], 1)
            self.assertEqual(result["collection_transport_calls"], 1)
            self.assertEqual(result["boost_transport_calls"], 0)
            self.assertEqual(result["food_farm_dispatch_count"], 1)
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(result["identical_retry_denied"])

        with RouteRig(self, ROUTES[FOOD_FARM_BOOST_FLOW_ID]) as rig:
            rig.runner.farm_mode = "diamonds"
            started = rig.stop.now
            report, = rig.once()
            result = rig.runner.last_result
            self.assertEqual(report["status"], "completed")
            self.assertEqual(result["boost_decision"], "diamonds")
            self.assertEqual(result["boost_transport_calls"], 1)
            self.assertEqual(result["boost_cost"], 37)
            self.assertTrue(result["owned_item_unavailable"])
            self.assertEqual(result["boost_action"]["action_key"], result["boost_action_key"])
            self.assertEqual(result["boost_action_key"], owned_boost_key)
            next_due = importlib.import_module(
                "automation_service.food_farm_boost",
            ).food_farm_boost_next_due
            next_due(result, rig.runner.last_identity, started)
            for changes in (
                {"boost_cost": 0}, {"boost_cost": 49}, {"boost_diamond_balance": 36},
                {"owned_item_unavailable": False},
                {"boost_timer_farm_identity": "home.building.farm.03"},
                {"boost_timer_remaining_seconds": 0},
            ):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    next_due(
                        {**result, **changes}, rig.runner.last_identity, started,
                    )
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(rig.runner.calls), 1)


class BatchFSemanticContractTests(unittest.TestCase):
    def test_hall_dispatch_reward_and_prior_use_are_distinct(self):
        with RouteRig(self, ROUTES[HALL_OF_WAR_FLOW_ID]) as rig:
            report, = rig.once()
            run, = rig.runs()
            result = rig.runner.last_result
            self.assertEqual(report["status"], "completed")
            self.assertEqual(
                (result["status"], result["challenge_status"], result["reward_status"]),
                ("complete_for_reset", "confirmed", "claimed"),
            )
            self.assertEqual(
                (result["challenge_transport_calls"], result["dispatch_transport_calls"],
                 result["reward_claim_transport_calls"], result["talent_switch_transport_calls"],
                 result["hall_of_war_dispatch_count"], result["committed_action_count"]),
                (1, 1, 1, 0, 2, 2),
            )
            self.assertEqual((run.consumed_inputs, run.consumed_actions), (18, 2))
            self.assertTrue(result["accounting_verified"])
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(result["identical_retry_denied"])
            self.assertEqual(result["scheduler_reset_id"], run.reset_id)
            self.assertEqual(result["reset_id"], run.reset_id)
            self.assertEqual(result["occurrence_key"], run.occurrence_key)
            self.assertTrue(result["saved_military_verified"])
            self.assertEqual(
                result["military_preset_verification"]["preset_name"], "Military",
            )
            self.assertFalse(result["military_preset_verification"]["switch_transport_attempted"])
            self.assertEqual(
                (
                    result["troop_set_one"]["hero_count"],
                    result["troop_set_one"]["current_troops"],
                    result["troop_set_one"]["troop_capacity"],
                ),
                (5, 160_200, 160_200),
            )
            self.assertEqual(result["reward_result_frame"]["frame_sha256"], "c" * 64)
            self.assertTrue(result["terminal_home_verified"])
            self.assertEqual(len(result["terminal_home_frame"]["frame_sha256"]), 64)
            self.assertIn("confirm-result", result["verified_navigation"])
            self.assertEqual((rig.runner.actions, rig.runner.effects), (2, 2))

        for mode, expected_status, expected_counts in (
            ("unavailable", "deferred", (0, 0, 0, 0)),
            ("reward_unavailable", "deferred", (1, 0, 1, 1)),
            ("manual_prior_use", "blocked", (0, 0, 0, 0)),
        ):
            with self.subTest(mode=mode), RouteRig(
                self, ROUTES[HALL_OF_WAR_FLOW_ID],
            ) as rig:
                rig.runner.hall_mode = mode
                report, = rig.once()
                run, = rig.runs()
                self.assertEqual(report["status"], expected_status, report)
                self.assertEqual(run.consumed_actions, expected_counts[2])
                if expected_status == "deferred":
                    self.assertEqual(run.state, RunState.DEFERRED)
                    self.assertFalse(rig.state.get_flow(HALL_OF_WAR_FLOW_ID).blocked)
                    due = rig.state.get_flow(HALL_OF_WAR_FLOW_ID).next_due_at_utc
                    self.assertGreater(due, rig.stop.now)
                    inputs = list(rig.runner.inputs)
                    with BotStateManager(rig.path) as restarted:
                        self.assertEqual(rig.once(state=restarted), [])
                    self.assertEqual(rig.runner.inputs, inputs)
                result = rig.runner.last_result
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(
                    (result["dispatch_transport_calls"], result["reward_claim_transport_calls"],
                     result["hall_of_war_dispatch_count"], result["committed_action_count"]),
                    expected_counts,
                )
                self.assertTrue(result["terminal_home_verified"])
                self.assertFalse(result["effect_reconciliation_required"])
                if mode == "manual_prior_use":
                    self.assertEqual(
                        result["challenge_status"], "deferred_unexplained_prior_same_reset_use",
                    )
                    self.assertEqual(len(rig.runner.calls), 1)

        with RouteRig(self, ROUTES[HALL_OF_WAR_FLOW_ID]) as rig:
            rig.runner.hall_mode = "already_reconciled"
            report, = rig.once()
            result = rig.runner.last_result
            run, = rig.runs()
            self.assertEqual(result["status"], "complete_for_reset")
            self.assertEqual(
                (result["challenge_status"], result["reward_status"],
                 result["dispatch_transport_calls"], result["reward_claim_transport_calls"],
                 result["hall_of_war_dispatch_count"], result["committed_action_count"]),
                ("confirmed_prior_canonical_action", "already_claimed", 0, 0, 0, 0),
            )
            self.assertEqual(report["result"]["committed_action_count"], 0)
            self.assertEqual(run.consumed_actions, 0)
            self.assertTrue(result["terminal_home_verified"])
            self.assertFalse(result["effect_reconciliation_required"])
            self.assertFalse(result["identical_retry_denied"])

    def test_training_resource_and_timer_transitions_match_native_actions(self):
        with RouteRig(self, ROUTES[TROOP_TRAINING_FLOW_ID]) as rig:
            report, = rig.once()
            run, = rig.runs()
            result = rig.runner.last_result
            self.assertEqual(report["status"], "completed")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                (result["training_start_transport_calls"], result["claim_dispatch_count"],
                 result["resource_box_dispatch_count"], result["warehouse_dispatch_count"],
                 result["training_dispatch_count"], result["committed_action_count"]),
                (4, 0, 0, 0, 4, 4),
            )
            self.assertEqual((run.consumed_inputs, run.consumed_actions), (28, 4))
            self.assertEqual(result["occurrence_key"], run.occurrence_key)
            self.assertEqual(result["reset_id"], run.reset_id)
            self.assertTrue(result["accounting_verified"])
            self.assertTrue(result["terminal_home_verified"])
            self.assertTrue(result["saved_training_preset_verified"])
            self.assertTrue(result["entry_navigation"]["canonical_home_entry_verified"])
            self.assertTrue(result["entry_navigation"]["terminal_home_verified"])
            self.assertEqual(result["resource_box_approvals"], [])
            self.assertEqual(result["warehouse_approvals"], [])

            expected = {
                "fighter": (8, "current_max", "continuous", True),
                "shooter": (8, "fixed", "once_daily", False),
                "rider": (1, "fixed", "once_daily", False),
                "vehicle": (1, "current_max", "continuous", True),
            }
            self.assertEqual([row["troop_type"] for row in result["training"]],
                             ["fighter", "shooter", "rider", "vehicle"])
            for row in result["training"]:
                with self.subTest(troop_type=row["troop_type"]):
                    tier, quantity_mode, policy, boxes_allowed = expected[row["troop_type"]]
                    self.assertEqual(
                        (row["selected_tier"], row["quantity_mode"], row["training_policy"],
                         result["resolved_config"][row["troop_type"]]["allow_resource_boxes"]),
                        (tier, quantity_mode, policy, boxes_allowed),
                    )
                    self.assertEqual(row["queue_state"], "active")
                    self.assertEqual(row["queue_troop_type"], row["troop_type"])
                    self.assertEqual(row["queue_tier"], tier)
                    self.assertEqual(row["queue_quantity"], row["quantity"])
                    self.assertTrue(row["queue_spatially_associated"])
                    self.assertEqual(row["reset_identity"], run.reset_id)
                    completion = datetime.fromisoformat(
                        row["expected_completion_timestamp"].replace("Z", "+00:00"),
                    ).timestamp()
                    self.assertGreater(completion, rig.stop.now)
                    resolved = result["resolved_config"][row["troop_type"]]
                    self.assertEqual(resolved["per_reset_variant_start_count"], 1)
                    self.assertEqual(
                        resolved["daily_initiation_state"],
                        "initiated" if policy == "once_daily" else "not_started",
                    )
                    if policy == "once_daily":
                        eligible_at = datetime.fromisoformat(
                            row["next_eligible_timestamp"].replace("Z", "+00:00"),
                        ).timestamp()
                        self.assertGreater(eligible_at, rig.stop.now)
                    else:
                        self.assertIsNone(row["next_eligible_timestamp"])
                    if quantity_mode == "current_max":
                        self.assertGreater(row["quantity_maximum"], 0)
                        self.assertEqual(row["quantity"], row["quantity_maximum"])
                        self.assertTrue(row["maximum_equality_proven"])
                        self.assertEqual(
                            result["resolved_config"][row["troop_type"]]["resolved_quantity"],
                            row["quantity_maximum"],
                        )
                    else:
                        self.assertEqual(row["quantity"], 250)
                        self.assertEqual(row["configured_quantity"], 250)
                        self.assertEqual(resolved["resolved_quantity"], 250)
                    before = {
                        resource["name"]: resource
                        for resource in row["resources_before"]
                    }
                    after = {
                        resource["name"]: resource
                        for resource in row["resources_after"]
                    }
                    self.assertEqual(set(before), {"food", "wood", "steel", "gas"})
                    self.assertEqual(set(after), set(before))
                    for name in before:
                        self.assertIsNotNone(before[name]["held"])
                        self.assertIsNotNone(after[name]["held"])
                        self.assertGreaterEqual(before[name]["held"], before[name]["required"])
                        self.assertEqual(before[name]["held"] - after[name]["held"],
                                         before[name]["required"])

        for mode in ("resource_shortage", "box_deferred"):
            with self.subTest(mode=mode), RouteRig(
                self, ROUTES[TROOP_TRAINING_FLOW_ID],
            ) as rig:
                rig.runner.training_mode = mode
                rig.once()
                result = rig.runner.last_result
                self.assertEqual(result["status"], "deferred")
                self.assertEqual(
                    (result["training_start_transport_calls"], result["training_dispatch_count"],
                     result["resource_box_dispatch_count"], result["warehouse_dispatch_count"],
                     result["committed_action_count"]),
                    (0, 0, 0, 0, 0),
                )
                self.assertEqual(result["resource_box_approvals"], [])
                self.assertEqual(result["warehouse_approvals"], [])
                self.assertEqual(result["training"][0]["queue_state"], "empty")
                self.assertEqual(result["training"][0]["status"], "deferred_resource_shortage")
                self.assertFalse(result["effect_reconciliation_required"])
                self.assertFalse(result["identical_retry_denied"])

    def test_training_active_queue_survives_restart_without_duplicate_start(self):
        with RouteRig(self, ROUTES[TROOP_TRAINING_FLOW_ID]) as rig:
            report, = rig.once()
            first, = rig.runs()
            due = rig.state.get_flow(TROOP_TRAINING_FLOW_ID).next_due_at_utc
            first_inputs = list(rig.runner.inputs)
            self.assertEqual(report["status"], "completed")
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(state=restarted), [])
            self.assertEqual(len(rig.runner.calls), 1)
            self.assertEqual(rig.runner.inputs, first_inputs)

            rig.stop.now = due
            rig.runner.input_count = 0
            with BotStateManager(rig.path) as restarted:
                second_report, = rig.once(state=restarted)
            second, = rig.runs()[1:]
            result = rig.runner.last_result
            self.assertEqual(second_report["result"]["status"], "deferred")
            self.assertEqual(first.reset_id, second.reset_id)
            self.assertNotEqual(first.occurrence_key, second.occurrence_key)
            self.assertEqual((second.consumed_inputs, second.consumed_actions), (0, 0))
            self.assertEqual(
                (result["training_start_transport_calls"], result["training_dispatch_count"],
                 result["committed_action_count"]),
                (0, 0, 0),
            )
            self.assertEqual(len(result["training"]), 4)
            self.assertTrue(all(row["queue_state"] == "active" for row in result["training"]))
            self.assertTrue(all(
                datetime.fromisoformat(row["expected_completion_timestamp"].replace("Z", "+00:00"))
                > datetime.fromtimestamp(due, timezone.utc)
                for row in result["training"]
            ))
            self.assertEqual(rig.state.get_flow(TROOP_TRAINING_FLOW_ID).next_due_at_utc, due + 1_800)
            self.assertEqual(len(rig.runner.calls), 2)
            self.assertEqual(rig.runner.inputs, first_inputs)


if __name__ == "__main__":
    unittest.main()
