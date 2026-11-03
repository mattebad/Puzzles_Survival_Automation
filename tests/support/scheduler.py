"""Shared canonical scheduler fixtures for offline tests."""

from __future__ import annotations

from pathlib import Path

from automation_service.contracts import (
    FlowDescriptor,
    FlowSpec,
    NormalizedOutcome,
    NormalizedResult,
    RecurrenceProjection,
    SchedulerFacts,
)
from automation_service.scheduler import UtcPulseCoordinator
from automation_service.state import BotStateManager


FLOW_ID = "CANONICAL-SCHEDULER-FLOW"
PRODUCT = "product-v1"
REVISION = "revision-1"
RESET = "reset-1"


def make_descriptor(
    flow_id: str = FLOW_ID,
    *,
    priority: int = 10,
    scheduler_eligible: bool = True,
    accepted_product: bool | str = PRODUCT,
    product_revision: str | None = REVISION,
    registration_status: str = "REGISTERED",
    cadence: str = "daily_once_per_reset",
    recurrence: RecurrenceProjection | None = None,
) -> FlowDescriptor:
    return FlowDescriptor(
        flow_id=flow_id,
        owner="scheduler-tests",
        family="scheduler-tests",
        variant="canonical",
        cadence=cadence,
        priority=priority,
        scheduler_eligible=scheduler_eligible,
        accepted_product=accepted_product,
        product_revision=product_revision,
        registration_status=registration_status,
        recurrence=recurrence,
    )


def make_facts(now: float = 100.0, **overrides: object) -> SchedulerFacts:
    values: dict[str, object] = {
        "health_ok": True,
        "accepted_product": PRODUCT,
        "product_revision": REVISION,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "owner_available": True,
        "clock_ok": True,
        "reset_agreement": True,
    }
    values.update(overrides)
    reset_id = str(values.pop("reset_id", RESET))
    return SchedulerFacts("account", "server", reset_id, now, **values)


class Handler:
    def __init__(self, descriptor: FlowDescriptor, result: NormalizedResult) -> None:
        self.descriptor = descriptor
        self.result = result
        self.plan_calls = 0

    def describe(self) -> FlowDescriptor:
        return self.descriptor

    def eligibility(self, _facts: SchedulerFacts, _perception=None) -> bool:
        return True

    def revalidate(self, _facts: SchedulerFacts, _perception=None) -> bool:
        return True

    def plan(self, _facts: SchedulerFacts, _perception=None) -> NormalizedResult:
        self.plan_calls += 1
        return self.result

    def reconcile(self, plan, _perception=None):
        return plan


def initialize(
    path: Path,
    descriptor: FlowDescriptor,
    *,
    max_wait_seconds: float | None = None,
    max_attempts: int = 3,
) -> tuple[BotStateManager, UtcPulseCoordinator, Handler]:
    state = BotStateManager(path, owner_instance_id="scheduler-owner")
    state.initialize_flows(
        [
            FlowSpec(
                descriptor.flow_id,
                default_enabled=True,
                priority=descriptor.priority,
                cadence=descriptor.cadence,
                max_wait_seconds=max_wait_seconds,
                max_attempts=max_attempts,
            )
        ]
    )
    state.set_service_enabled(True, now_utc_epoch=0.0)
    state.set_flow_enabled(descriptor.flow_id, True, now_utc_epoch=0.0)
    handler = Handler(
        descriptor,
        NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "DONE", action_count=1),
    )
    coordinator = UtcPulseCoordinator(state, [descriptor], {descriptor.flow_id: handler})
    return state, coordinator, handler
