"""Offline route contract cases and an isolated, transport-forbidden service rig."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Callable
from unittest.mock import patch

from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, DAILY_REWARDS_FLOW_ID,
    DAILY_SHOPS_FLOW_ID, ENHANCEMENT_FLOW_ID, FOOD_FARM_BOOST_FLOW_ID,
    HERO_DUEL_FLOW_ID, NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID,
    NOVA_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, RECOMMENDED_RESEARCH_FLOW_ID,
    RECRUITMENT_FLOW_ID, RESOURCE_ITEM_FLOW_ID, RUINS_FLOW_ID, SUPPLY_FLOW_ID,
    HALL_OF_WAR_FLOW_ID, TROOP_TRAINING_FLOW_ID,
)
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerTaskOutcome
from scripts import navigation_development_boundary as boundary
from tests.support.service_route_fakes import (
    GuardedAllianceDonationRunner, GuardedAllianceHelpRunner,
    GuardedAllianceShopRunner, GuardedBioenhancerRunner,
    GuardedCampaignRunner, GuardedDailyRewardsRunner, GuardedDailyShopsRunner,
    GuardedEnhancementRunner, GuardedFoodFarmBoostRunner, GuardedHeroDuelRunner,
    GuardedNanoMaterialProductionRunner, GuardedNanoweaponRunner, GuardedNovaRunner,
    GuardedPersonalMightRunner, GuardedRecruitmentRunner,
    GuardedRecommendedResearchRunner, GuardedResourceItemRunner, GuardedRuinsRunner,
    GuardedHallOfWarRunner, GuardedTroopTrainingRunner,
)
from tests.support.service_stop import VirtualStop


@dataclass(frozen=True)
class RouteSpec:
    flow_id: str
    make_runner: Callable[[VirtualStop, Path], Any]
    work: Callable[[Any], None]
    partial: Callable[[Any], None]
    partial_counts: tuple[int, int]
    generation_counts: tuple[int, int]
    first_inputs: int
    partial_outcome: SchedulerTaskOutcome = SchedulerTaskOutcome.BLOCKED


def _supply_partial(runner):
    runner.consume = runner.partial = True


def _ultimate_partial(runner):
    runner.completed_reset = None
    runner.fail_after_flee = True


def _bioenhancer_partial(runner):
    runner.consume = True
    runner.fault = "partial"



def _ruins_partial(runner):
    runner.partial = True


def _alliance_help_partial(runner):
    runner.partial = True


def _work_by_default(runner):
    """The fake's initial state already exercises a resource-affecting run."""


def _e_route_partial(runner):
    runner.partial = True


ROUTES = {
    SUPPLY_FLOW_ID: RouteSpec(
        SUPPLY_FLOW_ID, lambda stop, root: GuardedSupplyRunner(stop),
        lambda runner: setattr(runner, "consume", True), _supply_partial,
        (3, 1), (1, 0), 4,
    ),
    ULTIMATE_FLOW_ID: RouteSpec(
        ULTIMATE_FLOW_ID, lambda stop, root: GuardedUltimateRunner(stop),
        lambda runner: setattr(runner, "completed_reset", None), _ultimate_partial,
        (4, 1), (1, 1), 4,
    ),
    ENHANCEMENT_FLOW_ID: RouteSpec(
        ENHANCEMENT_FLOW_ID, GuardedEnhancementRunner, _work_by_default,
        lambda runner: setattr(runner, "partial", True), (2, 1), (1, 0), 6,
    ),
    PERSONAL_MIGHT_FLOW_ID: RouteSpec(
        PERSONAL_MIGHT_FLOW_ID, lambda stop, root: GuardedPersonalMightRunner(stop),
        _work_by_default, lambda runner: setattr(runner, "partial", True),
        (4, 1), (1, 0), 6,
    ),
    BIOENHANCER_FLOW_ID: RouteSpec(
        BIOENHANCER_FLOW_ID, GuardedBioenhancerRunner,
        lambda runner: setattr(runner, "consume", True), _bioenhancer_partial,
        (3, 1), (1, 0), 5,
    ),
    CAMPAIGN_FLOW_ID: RouteSpec(
        CAMPAIGN_FLOW_ID, lambda stop, root: GuardedCampaignRunner(stop),
        _work_by_default, lambda runner: setattr(runner, "fault", "partial"),
        (2, 1), (1, 1), 6,
    ),
    NOVA_FLOW_ID: RouteSpec(
        NOVA_FLOW_ID, lambda stop, root: GuardedNovaRunner(stop),
        _work_by_default, lambda runner: setattr(runner, "uncertain", True),
        (4, 1), (1, 0), 4,
    ),
    RECRUITMENT_FLOW_ID: RouteSpec(
        RECRUITMENT_FLOW_ID, lambda stop, root: GuardedRecruitmentRunner(stop),
        _work_by_default, lambda runner: setattr(runner, "uncertain", True),
        (4, 1), (1, 0), 4,
    ),
    DAILY_REWARDS_FLOW_ID: RouteSpec(
        DAILY_REWARDS_FLOW_ID, lambda stop, root: GuardedDailyRewardsRunner(stop, root),
        _work_by_default, lambda runner: setattr(runner, "partial", True),
        (3, 1), (1, 0), 4,
    ),
    RESOURCE_ITEM_FLOW_ID: RouteSpec(
        RESOURCE_ITEM_FLOW_ID, lambda stop, root: GuardedResourceItemRunner(stop),
        _work_by_default, lambda runner: setattr(runner, "partial", True),
        (3, 1), (1, 0), 4,
    ),
    RUINS_FLOW_ID: RouteSpec(
        RUINS_FLOW_ID, GuardedRuinsRunner, _work_by_default, _ruins_partial,
        (4, 1), (1, 0), 8,
    ),
    ALLIANCE_HELP_FLOW_ID: RouteSpec(
        ALLIANCE_HELP_FLOW_ID, GuardedAllianceHelpRunner,
        _work_by_default, _alliance_help_partial, (5, 3), (1, 0), 20,
    ),
    ALLIANCE_DONATION_FLOW_ID: RouteSpec(
        ALLIANCE_DONATION_FLOW_ID,
        lambda stop, root: GuardedAllianceDonationRunner(stop, root),
        _work_by_default,
        lambda runner: setattr(runner, "partial", True),
        (7, 3), (1, 0), 40,
    ),
    ALLIANCE_SHOP_FLOW_ID: RouteSpec(
        ALLIANCE_SHOP_FLOW_ID,
        lambda stop, root: GuardedAllianceShopRunner(stop, root),
        _work_by_default,
        lambda runner: setattr(runner, "partial", True),
        (13, 1), (1, 0), 24,
    ),
    DAILY_SHOPS_FLOW_ID: RouteSpec(
        DAILY_SHOPS_FLOW_ID,
        lambda stop, root: GuardedDailyShopsRunner(stop, root),
        _work_by_default,
        lambda runner: setattr(runner, "partial", True),
        (25, 2), (1, 0), 48,
    ),
    NANO_MATERIAL_PRODUCTION_FLOW_ID: RouteSpec(
        NANO_MATERIAL_PRODUCTION_FLOW_ID,
        lambda stop, root: GuardedNanoMaterialProductionRunner(stop, root),
        _work_by_default, lambda runner: setattr(runner, "partial", True),
        (11, 1), (1, 0), 18,
    ),
    NANOWEAPON_FLOW_ID: RouteSpec(
        NANOWEAPON_FLOW_ID,
        lambda stop, root: GuardedNanoweaponRunner(stop, root),
        _work_by_default, lambda runner: setattr(runner, "partial", True),
        (13, 2), (1, 0), 22,
    ),
    HERO_DUEL_FLOW_ID: RouteSpec(
        HERO_DUEL_FLOW_ID, lambda stop, root: GuardedHeroDuelRunner(stop, root),
        _work_by_default, _e_route_partial, (11, 1), (1, 0), 20,
    ),
    RECOMMENDED_RESEARCH_FLOW_ID: RouteSpec(
        RECOMMENDED_RESEARCH_FLOW_ID,
        lambda stop, root: GuardedRecommendedResearchRunner(stop, root),
        _work_by_default, _e_route_partial, (8, 1), (1, 0), 5,
        partial_outcome=SchedulerTaskOutcome.RECONCILIATION_REQUIRED,
    ),
    FOOD_FARM_BOOST_FLOW_ID: RouteSpec(
        FOOD_FARM_BOOST_FLOW_ID, lambda stop, root: GuardedFoodFarmBoostRunner(stop, root),
        _work_by_default, _e_route_partial, (3, 1), (1, 0), 4,
        partial_outcome=SchedulerTaskOutcome.RECONCILIATION_REQUIRED,
    ),
    HALL_OF_WAR_FLOW_ID: RouteSpec(
        HALL_OF_WAR_FLOW_ID, lambda stop, root: GuardedHallOfWarRunner(stop, root),
        _work_by_default, _e_route_partial, (12, 1), (1, 0), 18,
    ),
    TROOP_TRAINING_FLOW_ID: RouteSpec(
        TROOP_TRAINING_FLOW_ID, lambda stop, root: GuardedTroopTrainingRunner(stop, root),
        _work_by_default, _e_route_partial, (18, 2), (1, 0), 28,
    ),
}

NOT_SERVABLE = {
    WORLD_FLOW_ID: "navigation-only registration; no executor (covered_by tests.test_route_metadata_consistency)",
}
EXCEPTIONS = {
    (CAMPAIGN_FLOW_ID, "reset_guard"): (
        "AP occurrences retain their identity across midnight by design",
        "tests.test_service_campaign_dispatch.ServiceCampaignDispatchTests.test_midnight_during_claimed_observation_retains_ap_occurrence_identity",
    ),
    (CAMPAIGN_FLOW_ID, "restart_before_due"): (
        "AP occurrence eligibility follows a cooldown, not the next reset",
        "tests.test_service_campaign_dispatch.ServiceCampaignDispatchTests.test_new_service_before_due_skips_observation_and_execution_then_due_runs_once",
    ),
    (BIOENHANCER_FLOW_ID, "restart_before_due"): (
        "Research eligibility follows its observed cooldown, not the next reset",
        "tests.test_service_bioenhancer_dispatch.ServiceBioenhancerDispatchTests.test_no_work_persists_deferred_run_then_restart_waits_and_due_runs_once",
    ),
    (NOVA_FLOW_ID, "restart_before_due"): (
        "Praise eligibility follows a cooldown, not the next reset",
        "tests.test_service_nova.ServiceNovaTests.test_cooldown_survives_restart_then_one_due_pulse_and_reset",
    ),
    (RECRUITMENT_FLOW_ID, "restart_before_due"): (
        "Recruitment eligibility follows a cooldown, not the next reset",
        "tests.test_service_recruitment.ServiceRecruitmentTests.test_native_pass_cooldown_restart_and_later_eligibility",
    ),
    (RECOMMENDED_RESEARCH_FLOW_ID, "restart_before_due"): (
        "a confirmed recommendation may settle its timer within the same reset but must not start twice",
        "tests.test_service_route_contract.BatchESemanticContractTests.test_research_start_is_not_replayed_after_same_reset_restart",
    ),
    (DAILY_REWARDS_FLOW_ID, "restart_before_due"): (
        "the 300-second cooldown is an observation interval; a distinct ready batch may run within the same reset",
        "tests.test_service_daily_rewards.DailyRewardsServiceTests.test_cooldown_restart_and_later_distinct_batch_same_reset",
    ),
    (NANO_MATERIAL_PRODUCTION_FLOW_ID, "reset_guard"): (
        "production maintenance follows its persistent six-hour timer across game-day boundaries",
        "tests.test_service_route_contract.BatchDSemanticContractTests.test_production_timer_survives_service_restart_across_reset_and_restarts_once",
    ),
    (NANO_MATERIAL_PRODUCTION_FLOW_ID, "restart_before_due"): (
        "the persistent production timer remains authoritative across service restarts and resets",
        "tests.test_service_route_contract.BatchDSemanticContractTests.test_production_timer_survives_service_restart_across_reset_and_restarts_once",
    ),
    (NANOWEAPON_FLOW_ID, "restart_before_due"): (
        "production and Normal Craft timers drive cooldown pulses, not daily-once eligibility",
        "tests.test_service_route_contract.BatchDSemanticContractTests.test_nanoweapon_same_visit_claims_then_starts_exact_craft_and_resumes_pulse",
    ),
    (TROOP_TRAINING_FLOW_ID, "restart_before_due"): (
        "active queue completion timers can wake a run within the same reset; reconcile active queues without replaying starts",
        "tests.test_service_route_contract.BatchFSemanticContractTests.test_training_active_queue_survives_restart_without_duplicate_start",
    ),
}


def _runner_kwarg(flow_id: str) -> str:
    cli_name = canonical_entry(flow_id).cli_name
    if cli_name is None:
        raise ValueError(f"navigation-only flow has no runner: {flow_id}")
    return cli_name.replace("-", "_") + "_runner"


class RouteRig:
    def __init__(self, testcase, spec: RouteSpec):
        self.stack = ExitStack()
        testcase.addCleanup(self.stack.close)
        self.spec = spec
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "input-lock.sqlite3",
        ))
        for target in ("ADBRunner", "LocalBlueStacksRuntime.connect"):
            self.stack.enter_context(patch(
                f"scripts.bluestacks_native_runtime.{target}",
                side_effect=AssertionError("device access forbidden"),
            ))
        self.stop = VirtualStop(1_800_000_000.0)
        self.account_id, self.server_id = "account", "server"
        if spec.flow_id in {
            ALLIANCE_DONATION_FLOW_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_SHOP_FLOW_ID,
            DAILY_REWARDS_FLOW_ID, DAILY_SHOPS_FLOW_ID, RESOURCE_ITEM_FLOW_ID,
            RUINS_FLOW_ID, NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID,
            HERO_DUEL_FLOW_ID, RECOMMENDED_RESEARCH_FLOW_ID, FOOD_FARM_BOOST_FLOW_ID,
            HALL_OF_WAR_FLOW_ID, TROOP_TRAINING_FLOW_ID,
        }:
            from datetime import datetime, timezone
            backend = derive_resource_runtime_identity(
                resource_fixed_runtime_binding(),
                datetime.fromtimestamp(self.stop.now, timezone.utc),
            )
            self.account_id, self.server_id = backend.account_id, backend.server_id
        self.path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.path))
        self.runner = spec.make_runner(self.stop, self.root)
        self.service = self.make_service(self.state)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(spec.flow_id, True)

    def make_service(self, state):
        return AutomationService(
            mode="supervised", state=state,
            **{_runner_kwarg(self.spec.flow_id): self.runner},
        )

    def once(self, state=None):
        self.stop.stopped = False
        self.stop.on_wait = self.stop.set
        reports = []
        service = self.service if state is None else self.make_service(state)
        service.serve(
            account_id=self.account_id, server_id=self.server_id, stop=self.stop,
            emit=lambda report: (reports.append(report), self.stop.set()),
            clock=lambda: self.stop.now, flow_ids=(self.spec.flow_id,),
        )
        return reports

    def runs(self):
        return [self.state.get_run(row[0]) for row in self.state._db.execute(
            "SELECT run_id FROM runs ORDER BY claimed_at_utc, rowid",
        )]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)
