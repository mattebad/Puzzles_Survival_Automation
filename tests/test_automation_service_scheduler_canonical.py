from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from automation_service.contracts import (
    FlowDescriptor,
    FlowSpec,
    NormalizedOutcome,
    NormalizedResult,
    RecurrenceClass,
    RecurrenceProjection,
    SchedulerFacts,
)
from automation_service.scheduler import UtcPulseCoordinator
from automation_service.state import (
    ActionState,
    BotStateManager,
    RunState,
    StateBusyError,
    TerminalProjectionError,
)


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
        NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "DONE"),
    )
    coordinator = UtcPulseCoordinator(state, [descriptor], {descriptor.flow_id: handler})
    return state, coordinator, handler

def mutable_tables(path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Return every canonical state table in a stable, byte-level shape."""

    tables = (
        "service_control",
        "service_lease",
        "clock_state",
        "flow_state",
        "runs",
        "actions",
    )
    with sqlite3.connect(path) as connection:
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ).fetchall()
            )
            for table in tables
        }



class CanonicalSchedulerTests(unittest.TestCase):
    def test_mf1_recurrence_bindings_use_canonical_occurrence_identity(self) -> None:
        cases = (
            (
                "daily",
                make_descriptor(),
                make_facts(),
                "daily_once_per_reset",
                RESET,
                f"{FLOW_ID}:{RESET}:0",
            ),
            (
                "timer",
                make_descriptor(
                    cadence="timer",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.TIMER,
                        next_eligible_at=100.0,
                        observed_at_utc=100.0,
                    ),
                ),
                make_facts(),
                "timer",
                "100.0",
                f"{FLOW_ID}:timer:100.0",
            ),
            (
                "cooldown",
                make_descriptor(
                    cadence="cooldown_pulse",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.COOLDOWN,
                        next_eligible_at=100.0,
                        observed_at_utc=100.0,
                    ),
                ),
                make_facts(),
                "cooldown",
                "100.0",
                f"{FLOW_ID}:cooldown:100.0",
            ),
            (
                "resource",
                make_descriptor(
                    cadence="ap_regeneration",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.AP_REGENERATION,
                        next_eligible_at=100.0,
                        observed_at_utc=100.0,
                        generation="ap-generation-1",
                        observed_balance=12.0,
                    ),
                ),
                make_facts(),
                "ap_regeneration",
                "ap-generation-1",
                f"{FLOW_ID}:ap_regeneration:ap-generation-1",
            ),
            (
                "bounded-repeat",
                make_descriptor(
                    cadence="bounded_repeat",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.BOUNDED_REPEAT,
                        generation="repeat-sequence-1",
                        repeat_ordinal=2,
                        repeat_limit=3,
                    ),
                ),
                make_facts(),
                "bounded_repeat",
                "repeat-sequence-1:2",
                f"{FLOW_ID}:bounded_repeat:repeat-sequence-1:2",
            ),
            (
                "queue",
                make_descriptor(
                    cadence="queue_generation",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.QUEUE_GENERATION,
                        generation="queue-generation-1",
                    ),
                ),
                make_facts(),
                "queue_generation",
                "queue-generation-1",
                f"{FLOW_ID}:queue_generation:queue-generation-1",
            ),
            (
                "march",
                make_descriptor(
                    cadence="march_generation",
                    recurrence=RecurrenceProjection(
                        RecurrenceClass.MARCH_GENERATION,
                        generation="march-generation-1",
                    ),
                ),
                make_facts(),
                "march_generation",
                "march-generation-1",
                f"{FLOW_ID}:march_generation:march-generation-1",
            ),
        )
        for (
            label,
            descriptor,
            current_facts,
            expected_kind,
            expected_basis,
            expected_key,
        ) in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                state, coordinator, _handler = initialize(
                    Path(folder) / "state.sqlite3", descriptor
                )
                try:
                    report = coordinator.pulse(current_facts)
                    self.assertIsNotNone(report.candidate)
                    self.assertIsNotNone(report.result)
                    assert report.candidate is not None
                    assert report.candidate.claim is not None
                    self.assertEqual(report.candidate.occurrence_key, expected_key)
                    self.assertEqual(
                        report.candidate.claim.occurrence_kind, expected_kind
                    )
                    self.assertEqual(
                        report.candidate.claim.occurrence_basis, expected_basis
                    )
                finally:
                    state.close()

    def test_daily_occurrence_is_once_per_reset(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(
                Path(folder) / "state.sqlite3", descriptor
            )
            try:
                first = coordinator.pulse(make_facts(now=100.0))
                second = coordinator.pulse(make_facts(now=101.0))
                self.assertIsNotNone(first.candidate)
                self.assertEqual(second.reason_code, "NO_ELIGIBLE_TASK")
                self.assertIsNone(second.candidate)
                self.assertEqual(handler.plan_calls, 1)
            finally:
                state.close()

    def test_manual_request_is_separate_and_retry_reuses_occurrence_key(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, coordinator, handler = initialize(path, descriptor)
            try:
                first = coordinator.pulse(make_facts(now=100.0))
                self.assertEqual(first.candidate.occurrence_key, f"{FLOW_ID}:{RESET}:0")
                self.assertEqual(state.get_flow(FLOW_ID).next_occurrence_key, 1)

                manual = coordinator.run_manual(
                    FLOW_ID,
                    make_facts(now=101.0),
                    operator_request_id="operator-request-1",
                )
                self.assertEqual(
                    manual.candidate.occurrence_key,
                    f"{FLOW_ID}:manual:operator-request-1",
                )
                self.assertEqual(manual.candidate.claim.mode, "manual")
                self.assertEqual(
                    manual.candidate.claim.occurrence_basis, "operator-request-1"
                )
                self.assertEqual(state.get_flow(FLOW_ID).next_occurrence_key, 1)

                handler.result = NormalizedResult(
                    NormalizedOutcome.RECONCILIATION_REQUIRED, "RETRY_ME"
                )
                failed = coordinator.pulse(
                    make_facts(now=102.0, reset_id="reset-2")
                )
                retry = coordinator.pulse(
                    make_facts(now=104.0, reset_id="reset-2")
                )
                self.assertEqual(
                    retry.candidate.occurrence_key,
                    failed.candidate.occurrence_key,
                )
                self.assertEqual(
                    retry.candidate.claim.run_id,
                    failed.candidate.claim.run_id,
                )
            finally:
                state.close()
    def test_all_public_selection_paths_apply_external_and_static_gates(self) -> None:

        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(Path(folder) / "state.sqlite3", descriptor)
            try:
                for overrides in (
                    {"health_ok": False},
                    {"unresolved_action": True},
                    {"breakers": ("breaker",)},
                    {"owner_available": False},
                    {"clock_ok": False},
                    {"reset_agreement": False},
                    {"accepted_product": "wrong-product"},
                    {"product_revision": "wrong-revision"},
                    {"registration_status": "NOT_REGISTERED"},
                    {"scheduler_eligible": False},
                ):
                    self.assertIsNone(coordinator.select(make_facts(**overrides)))
                    self.assertEqual(handler.plan_calls, 0)
                    self.assertEqual(coordinator.shadow(make_facts(**overrides)).candidate, None)

                state.set_service_enabled(False, now_utc_epoch=101.0)
                self.assertIsNone(coordinator.select(make_facts(now=101.0)))
                state.set_service_enabled(True, now_utc_epoch=102.0)
                state.set_flow_enabled(descriptor.flow_id, False, now_utc_epoch=102.0)
                self.assertIsNone(coordinator.select(make_facts(now=102.0)))
            finally:
                state.close()
    def test_disabled_service_shadow_is_fully_mutation_free(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, coordinator, handler = initialize(path, descriptor)
            try:
                state.set_service_enabled(False, now_utc_epoch=99.0)
                before = mutable_tables(path)
                report = coordinator.shadow(make_facts(now=100.0))
                after = mutable_tables(path)
                self.assertEqual(report.reason_code, "SHADOW_CANDIDATE")
                self.assertIsNotNone(report.candidate)
                self.assertIsNone(report.candidate.claim)
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(after, before)
            finally:
                state.close()

    def test_scheduler_returns_safe_idle_on_state_lock_contention(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(
                Path(folder) / "state.sqlite3", descriptor
            )
            try:
                with patch.object(
                    state,
                    "acquire_service_lease",
                    side_effect=StateBusyError("service lease"),
                ):
                    report = coordinator.pulse(make_facts(now=100.0))
                self.assertEqual(report.reason_code, "SQLITE_BUSY")
                self.assertIsNone(report.candidate)
                self.assertIsNone(report.result)
                self.assertEqual(handler.plan_calls, 0)
            finally:
                state.close()

    def test_only_reset_scoped_descriptors_roll_reset_state(self) -> None:
        timer = make_descriptor(
            cadence="timer",
            recurrence=RecurrenceProjection(
                RecurrenceClass.TIMER,
                next_eligible_at=100.0,
                observed_at_utc=100.0,
            ),
        )
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, _handler = initialize(
                Path(folder) / "state.sqlite3", timer
            )
            try:
                with patch.object(
                    state, "update_reset", wraps=state.update_reset
                ) as update_reset:
                    report = coordinator.pulse(make_facts(now=100.0))
                self.assertIsNotNone(report.candidate)
                self.assertEqual(
                    report.candidate.claim.occurrence_kind, "timer"
                )
            finally:
                state.close()

    def test_retry_preserves_timer_run_key_when_projection_slot_changes(self) -> None:
        descriptor = make_descriptor(
            cadence="timer",
            recurrence=RecurrenceProjection(
                RecurrenceClass.TIMER,
                next_eligible_at=100.0,
                observed_at_utc=100.0,
            ),
        )
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(
                Path(folder) / "state.sqlite3", descriptor
            )
            try:
                handler.result = NormalizedResult(
                    NormalizedOutcome.RECONCILIATION_REQUIRED, "RETRY_TIMER"
                )
                first = coordinator.pulse(make_facts(now=100.0))
                handler.result = NormalizedResult(
                    NormalizedOutcome.COMPLETE_FOR_RESET, "TIMER_RECOVERED"
                )
                changed_slot = RecurrenceProjection(
                    RecurrenceClass.TIMER,
                    next_eligible_at=102.0,
                    observed_at_utc=102.0,
                )
                retry = coordinator.pulse(
                    make_facts(
                        now=102.0,
                        projections={FLOW_ID: changed_slot},
                    )
                )
                self.assertEqual(
                    retry.candidate.occurrence_key,
                    first.candidate.occurrence_key,
                )
                self.assertEqual(
                    retry.candidate.claim.run_id,
                    first.candidate.claim.run_id,
                )
            finally:
                state.close()

    def test_timer_recurrence_requires_matching_fresh_projection_and_due_time(self) -> None:
        recurrence = RecurrenceProjection(
            RecurrenceClass.TIMER,
            next_eligible_at=110.0,
            observed_at_utc=100.0,
        )
        descriptor = make_descriptor(cadence="timer", recurrence=recurrence)
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, _handler = initialize(Path(folder) / "state.sqlite3", descriptor)
            try:
                self.assertIsNone(coordinator.select(make_facts(now=109.0)))
                self.assertIsNotNone(coordinator.select(make_facts(now=110.0)))
                wrong_class = RecurrenceProjection(
                    RecurrenceClass.COOLDOWN,
                    next_eligible_at=110.0,
                    observed_at_utc=100.0,
                )
                self.assertIsNone(
                    coordinator.select(
                        make_facts(now=110.0, projections={FLOW_ID: wrong_class})
                    )
                )
                stale = RecurrenceProjection(
                    RecurrenceClass.TIMER,
                    next_eligible_at=110.0,
                    observed_at_utc=0.0,
                )
                self.assertIsNone(
                    coordinator.select(
                        make_facts(
                            now=110.0,
                            projections={FLOW_ID: stale},
                            projection_freshness_seconds=50.0,
                        )
                    )
                )
            finally:
                state.close()

    def test_failed_terminal_retries_same_occurrence_after_bounded_backoff(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(Path(folder) / "state.sqlite3", descriptor)
            try:
                handler.result = NormalizedResult(
                    NormalizedOutcome.RECONCILIATION_REQUIRED,
                    "UNKNOWN_RESULT",
                )
                first = coordinator.pulse(make_facts(now=100.0))
                self.assertEqual(first.result.outcome.value, "reconciliation_required")
                self.assertEqual(first.candidate.occurrence_key, f"{FLOW_ID}:{RESET}:0")
                flow = state.get_flow(FLOW_ID)
                self.assertEqual(flow.next_occurrence_key, 0)
                self.assertEqual(flow.retry_not_before_utc, 101.0)
                self.assertIsNone(coordinator.select(make_facts(now=100.5)))

                handler.result = NormalizedResult(
                    NormalizedOutcome.COMPLETE_FOR_RESET,
                    "RECOVERED",
                )
                retry = coordinator.pulse(make_facts(now=101.0))
                self.assertEqual(retry.candidate.occurrence_key, first.candidate.occurrence_key)
                self.assertEqual(retry.candidate.claim.run_id, first.candidate.claim.run_id)
                self.assertEqual(retry.result.reason_code, "RECOVERED")
                self.assertEqual(state.get_flow(FLOW_ID).next_occurrence_key, 1)
            finally:
                state.close()

    def test_terminal_projection_race_returns_unknown_result(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, _handler = initialize(Path(folder) / "state.sqlite3", descriptor)
            try:
                with patch.object(
                    state,
                    "project_terminal",
                    side_effect=TerminalProjectionError("TERMINAL_CAS_FAILED"),
                ):
                    report = coordinator.pulse(make_facts())
                self.assertEqual(report.reason_code, "TERMINAL_CAS_FAILED")
                self.assertEqual(report.result.outcome.value, "unknown")
                self.assertTrue(report.result.unresolved_action)
                self.assertEqual(state.get_run(report.candidate.claim.run_id).state, RunState.RUNNING)
            finally:
                state.close()

    def test_restart_reconciles_stale_no_dispatch_orphan_before_selection(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, _coordinator, _handler = initialize(path, descriptor)
            lease = state.acquire_service_lease(now_utc_epoch=100.0)
            self.assertIsNotNone(lease)
            assert lease is not None
            orphan = state.claim_occurrence(
                FLOW_ID,
                RESET,
                now_utc_epoch=100.0,
                owner_instance_id=state.owner_instance_id,
                process_start_token=state.process_start_token,
                lease_generation=lease.lease_generation,
            )
            self.assertIsNotNone(orphan)
            assert orphan is not None
            state.close()

            restarted = BotStateManager(
                path,
                owner_instance_id="scheduler-restarted",
                process_start_token="scheduler-restarted-process",
            )
            try:
                handler = Handler(
                    descriptor,
                    NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "RECOVERED"),
                )
                coordinator = UtcPulseCoordinator(
                    restarted, [descriptor], {FLOW_ID: handler}
                )
                first = coordinator.pulse(make_facts(now=200.0))
                self.assertEqual(first.reason_code, "NO_ELIGIBLE_TASK")
                report = coordinator.pulse(make_facts(now=205.0))
                self.assertEqual(report.candidate.claim.run_id, orphan.run_id)
                self.assertEqual(
                    restarted.get_run(orphan.run_id).state, RunState.SUCCEEDED
                )
                self.assertIsNone(restarted.get_service_lease().owner_instance_id)
            finally:
                restarted.close()

    def test_orphaned_dispatch_is_reconciliation_required_and_not_retried(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, _coordinator, handler = initialize(path, descriptor)
            lease = state.acquire_service_lease(now_utc_epoch=100.0)
            self.assertIsNotNone(lease)
            assert lease is not None
            auth = {
                "owner_instance_id": state.owner_instance_id,
                "process_start_token": state.process_start_token,
                "lease_generation": lease.lease_generation,
            }
            orphan = state.claim_occurrence(
                FLOW_ID, RESET, now_utc_epoch=100.0, **auth
            )
            self.assertIsNotNone(orphan)
            assert orphan is not None
            auth["run_token"] = orphan.run_token
            running = state.transition_run(
                orphan.run_id,
                RunState.RUNNING,
                expected_state=RunState.CLAIMED,
                now_utc_epoch=100.0,
                **auth,
            )
            self.assertIsNotNone(running)
            action = state.reserve_action(
                orphan.run_id,
                "orphan-idempotency",
                "orphan-semantic",
                now_utc_epoch=100.0,
                **auth,
            )
            self.assertIsNotNone(action)
            assert action is not None
            dispatching = state.transition_action(
                action.action_id,
                ActionState.DISPATCHING,
                expected_state=ActionState.RESERVED,
                now_utc_epoch=100.0,
                **auth,
            )
            self.assertIsNotNone(dispatching)
            state.close()

            restarted = BotStateManager(
                path,
                owner_instance_id="scheduler-restarted",
                process_start_token="scheduler-restarted-process",
            )
            try:
                coordinator = UtcPulseCoordinator(
                    restarted, [descriptor], {FLOW_ID: handler}
                )
                report = coordinator.pulse(make_facts(now=200.0))
                self.assertEqual(
                    report.reason_code, "ORPHAN_RECONCILIATION_REQUIRED"
                )
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(
                    restarted.get_run(orphan.run_id).state, RunState.RECOVERING
                )
                self.assertTrue(restarted.has_unresolved_actions(orphan.run_id))
                self.assertEqual(
                    restarted.get_action(action.action_id).state,
                    ActionState.UNKNOWN,
                )
                self.assertIsNone(restarted.get_service_lease().owner_instance_id)
            finally:
                restarted.close()
    def test_unknown_action_effect_blocks_same_occurrence_retry(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, coordinator, handler = initialize(path, descriptor)
            try:
                lease = state.acquire_service_lease(now_utc_epoch=100.0)
                self.assertIsNotNone(lease)
                assert lease is not None
                auth = {
                    "owner_instance_id": state.owner_instance_id,
                    "process_start_token": state.process_start_token,
                    "lease_generation": lease.lease_generation,
                }
                run = state.claim_occurrence(
                    FLOW_ID, RESET, now_utc_epoch=100.0, **auth
                )
                self.assertIsNotNone(run)
                assert run is not None
                auth["run_token"] = run.run_token
                running = state.transition_run(
                    run.run_id,
                    RunState.RUNNING,
                    expected_state=RunState.CLAIMED,
                    now_utc_epoch=100.0,
                    **auth,
                )
                self.assertIsNotNone(running)
                action = state.reserve_action(
                    run.run_id,
                    "unknown-retry-idempotency",
                    "unknown-retry-semantic",
                    now_utc_epoch=100.0,
                    **auth,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    state.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        now_utc_epoch=100.0,
                        **auth,
                    )
                )
                self.assertIsNotNone(
                    state.transition_action(
                        action.action_id,
                        ActionState.UNKNOWN,
                        expected_state=ActionState.DISPATCHING,
                        now_utc_epoch=100.0,
                        **auth,
                    )
                )
                failed = state.project_terminal(
                    run.run_id,
                    RunState.FAILED,
                    expected_state=RunState.RUNNING,
                    now_utc_epoch=100.0,
                    outcome="UNKNOWN",
                    reason="effect unresolved",
                    **auth,
                )
                self.assertEqual(failed.state, RunState.FAILED)
                self.assertTrue(state.has_unresolved_actions(run.run_id))
                state.release_service_lease(**{
                    key: auth[key]
                    for key in (
                        "owner_instance_id",
                        "process_start_token",
                        "lease_generation",
                    )
                })

                report = coordinator.pulse(make_facts(now=200.0))
                self.assertEqual(report.reason_code, "CLAIM_UNAVAILABLE")
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(
                    state.get_run(run.run_id).state, RunState.FAILED
                )
                self.assertTrue(state.has_unresolved_actions(run.run_id))
                self.assertIsNone(state.get_service_lease().owner_instance_id)
            finally:
                state.close()


    def test_clock_high_water_rejects_rollback_even_when_facts_claim_healthy(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(
                Path(folder) / "state.sqlite3", descriptor
            )
            try:
                first = coordinator.pulse(make_facts(now=100.0))
                self.assertEqual(first.result.reason_code, "DONE")
                self.assertEqual(state.get_clock().high_water_utc, 100.0)

                rollback = coordinator.pulse(
                    make_facts(now=90.0, clock_ok=True, clock_rollback=False)
                )
                self.assertEqual(rollback.reason_code, "CLOCK_ROLLBACK")
                self.assertIsNone(rollback.candidate)
                self.assertEqual(handler.plan_calls, 1)
                self.assertEqual(state.get_clock().high_water_utc, 100.0)
                self.assertIsNone(state.get_service_lease().owner_instance_id)
            finally:
                state.close()

    def test_lease_released_after_no_candidate_and_handler_exception(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            state, coordinator, handler = initialize(
                Path(folder) / "state.sqlite3", descriptor
            )
            try:
                state.set_flow_enabled(FLOW_ID, False, now_utc_epoch=0.0)
                no_candidate = coordinator.pulse(make_facts(now=100.0))
                self.assertEqual(no_candidate.reason_code, "NO_ELIGIBLE_TASK")

                state.set_flow_enabled(FLOW_ID, True, now_utc_epoch=100.0)
                with patch.object(handler, "plan", side_effect=RuntimeError("boom")):
                    failed = coordinator.pulse(make_facts(now=101.0))
                self.assertEqual(
                    failed.result.outcome.value, "reconciliation_required"
                )
                self.assertIsNone(state.get_service_lease().owner_instance_id)
            finally:
                state.close()

    def test_starvation_bound_preempts_priority_after_max_wait(self) -> None:
        high = make_descriptor("HIGH", priority=1)
        low = make_descriptor("LOW", priority=99)
        with tempfile.TemporaryDirectory() as folder:
            state = BotStateManager(Path(folder) / "state.sqlite3", owner_instance_id="scheduler-owner")
            state.initialize_flows(
                [
                    FlowSpec("HIGH", default_enabled=True, priority=1),
                    FlowSpec("LOW", default_enabled=True, priority=99, max_wait_seconds=10.0),
                ]
            )
            state.set_service_enabled(True, now_utc_epoch=0.0)
            state.set_flow_enabled("HIGH", True, now_utc_epoch=0.0)
            state.set_flow_enabled("LOW", True, now_utc_epoch=0.0)
            handlers = {
                "HIGH": Handler(high, NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "HIGH")),
                "LOW": Handler(low, NormalizedResult(NormalizedOutcome.COMPLETE_FOR_RESET, "LOW")),
            }
            coordinator = UtcPulseCoordinator(state, [high, low], handlers)
            try:
                candidate = coordinator.select(make_facts(now=11.0))
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate.descriptor.flow_id, "LOW")
            finally:
                state.close()


if __name__ == "__main__":
    unittest.main()
