"""Offline route contract cases and an isolated, transport-forbidden service rig."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Callable
from unittest.mock import patch

from automation_service.registry import (
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, ENHANCEMENT_FLOW_ID, NOVA_FLOW_ID,
    PERSONAL_MIGHT_FLOW_ID, RECRUITMENT_FLOW_ID, SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
    WORLD_FLOW_ID, canonical_entry,
)
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from scripts import navigation_development_boundary as boundary
from tests.support.service_route_fakes import GuardedSupplyRunner
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


def _supply_partial(runner):
    runner.consume = runner.partial = True


ROUTES = {
    SUPPLY_FLOW_ID: RouteSpec(
        SUPPLY_FLOW_ID, lambda stop, root: GuardedSupplyRunner(stop),
        lambda runner: setattr(runner, "consume", True), _supply_partial,
        (3, 1), (1, 0), 4,
    ),
}

# Removed as each route joins the contract during the staged cutover.
PENDING = {
    ULTIMATE_FLOW_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
    BIOENHANCER_FLOW_ID, CAMPAIGN_FLOW_ID, NOVA_FLOW_ID, RECRUITMENT_FLOW_ID,
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
            account_id="account", server_id="server", stop=self.stop,
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
