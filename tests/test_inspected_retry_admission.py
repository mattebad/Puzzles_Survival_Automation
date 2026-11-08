"""Audited zero-effect inspection rearm of exhausted retry windows.

Every test uses a real temporary SQLite canonical state; the scheduler test also
drives the real pulse coordinator and the canonical CLI entry point.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable, TypeVar
import unittest

from automation_service.cli import main as cli_main
from automation_service.contracts import FlowSpec, NormalizedOutcome, NormalizedResult
from automation_service.state import (
    RENAMED_FLOW_IDS,
    REPOSITORY_ROOT,
    ActionState,
    BotStateManager,
    FlowInspection,
    FlowInspectionDenied,
    FlowState,
    RunRecord,
    RunState,
)
from tests.support.scheduler import FLOW_ID as SCHEDULER_FLOW_ID
from tests.support.scheduler import initialize, make_descriptor, make_facts


FLOW = "INSPECTED-RETRY-FLOW"
OTHER = "INSPECTED-RETRY-OTHER"
RESET = "reset-1"
OWNER = "owner-a"
PROCESS = "process-a"
EVIDENCE = (
    Path(__file__).resolve(),
    REPOSITORY_ROOT / "docs" / "automation-service.md",
    REPOSITORY_ROOT / "automation_service" / "cli.py",
)
NAVIGATION_BLOCK = "RESOURCE_ITEM_REQUIRES_INSPECTION:bag navigation did not settle"
INSPECTION_REASON = "repaired recognition; zero Food Use and zero consequential attempts"

T = TypeVar("T")


def present(value: T | None, what: str) -> T:
    """Fixture invariant: the canonical state returned the expected record."""

    if value is None:
        raise AssertionError(f"{what} unexpectedly missing")
    return value


def flow_of(state: BotStateManager, flow_id: str = FLOW) -> FlowState:
    return present(state.get_flow(flow_id), f"flow {flow_id}")


def json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected a JSON object, got {value!r}")
    return value


@dataclass(frozen=True)
class AttemptSpec:
    target: RunState = RunState.BLOCKED
    reason: str = NAVIGATION_BLOCK
    outcome: str = "blocked"
    inputs: int = 0
    actions: int = 0
    unknown_action: bool = False


BEFORE_INPUT = AttemptSpec()
NAVIGATION_ONLY = AttemptSpec(inputs=2)


def open_state(path: Path) -> BotStateManager:
    state = BotStateManager(path, owner_instance_id=OWNER, process_start_token=PROCESS, process_id=101)
    state.initialize_flows([
        FlowSpec(FLOW, priority=1, cadence="daily_once_per_reset", max_attempts=3),
        FlowSpec(OTHER, priority=2, cadence="daily_once_per_reset", max_attempts=3),
    ])
    return state


def arm(state: BotStateManager, now: float, flow_id: str = FLOW) -> None:
    state.set_service_enabled(True, now_utc_epoch=now)
    state.set_flow_enabled(flow_id, True, now_utc_epoch=now)


def disarm(state: BotStateManager, now: float, flow_id: str = FLOW) -> None:
    state.set_flow_enabled(flow_id, False, now_utc_epoch=now)
    state.set_service_enabled(False, emergency_reason="operator inspection", now_utc_epoch=now)


def attempt(
    state: BotStateManager,
    now: float,
    spec: AttemptSpec = BEFORE_INPUT,
    *,
    flow_id: str = FLOW,
) -> RunRecord | None:
    """Claim, run and terminalize one attempt; ``None`` when the claim is refused."""

    lease = present(
        state.acquire_service_lease(now_utc_epoch=now, lease_ttl_seconds=10.0), "service lease"
    )
    generation = lease.lease_generation
    try:
        run = state.claim_occurrence(
            flow_id, RESET, now_utc_epoch=now, max_inputs=10, max_actions=2,
            owner_instance_id=OWNER, process_start_token=PROCESS, lease_generation=generation,
        )
        if run is None:
            return None
        token = run.run_token
        present(state.transition_run(
            run.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED, now_utc_epoch=now,
            owner_instance_id=OWNER, process_start_token=PROCESS, run_token=token,
            lease_generation=generation,
        ), "running transition")
        if spec.unknown_action:
            action = present(state.reserve_action(
                run.run_id, f"use-{now}", "use-1k-food", now_utc_epoch=now,
                owner_instance_id=OWNER, process_start_token=PROCESS, run_token=token,
                lease_generation=generation,
            ), "reserved action")
            for target, expected in (
                (ActionState.DISPATCHING, ActionState.RESERVED),
                (ActionState.UNKNOWN, ActionState.DISPATCHING),
            ):
                present(state.transition_action(
                    action.action_id, target, expected_state=expected, now_utc_epoch=now,
                    owner_instance_id=OWNER, process_start_token=PROCESS, run_token=token,
                    lease_generation=generation,
                ), f"{target.value} action transition")
        if spec.inputs or spec.actions:
            present(state.record_executor_consumption(
                run.run_id, consumed_inputs=spec.inputs, consumed_actions=spec.actions,
                now_utc_epoch=now, owner_instance_id=OWNER, process_start_token=PROCESS,
                run_token=token, lease_generation=generation,
            ), "executor consumption")
        return state.project_terminal(
            run.run_id, spec.target, expected_state=RunState.RUNNING, reason=spec.reason,
            outcome=spec.outcome, now_utc_epoch=now, owner_instance_id=OWNER,
            process_start_token=PROCESS, run_token=token, lease_generation=generation,
        )
    finally:
        state.release_service_lease(
            owner_instance_id=OWNER, process_start_token=PROCESS, lease_generation=generation
        )


def exhaust(
    state: BotStateManager,
    start: float,
    *,
    flow_id: str = FLOW,
    first: AttemptSpec = BEFORE_INPUT,
    third: AttemptSpec = NAVIGATION_ONLY,
) -> list[RunRecord]:
    """Two before-input failures then one navigation-only failure, as observed."""

    arm(state, start, flow_id)
    runs = [
        present(attempt(state, start, first, flow_id=flow_id), "first attempt"),
        present(attempt(state, start + 100.0, flow_id=flow_id), "second attempt"),
        present(attempt(state, start + 200.0, third, flow_id=flow_id), "third attempt"),
    ]
    disarm(state, start + 250.0, flow_id)
    return runs


def inspect(
    state: BotStateManager,
    now: float,
    *,
    flow_id: str = FLOW,
    evidence: Path = EVIDENCE[0],
    attest: int = 0,
    reason: str = INSPECTION_REASON,
    expected_generation: int | None = None,
    expected_row_version: int | None = None,
    expected_consecutive_failures: int | None = None,
) -> FlowInspection:
    """Rearm one flow with its current CAS facts unless a test overrides one."""

    flow = flow_of(state, flow_id)
    return state.inspect_rearm_flow(
        flow_id,
        expected_generation=flow.generation if expected_generation is None else expected_generation,
        expected_row_version=flow.row_version if expected_row_version is None else expected_row_version,
        expected_consecutive_failures=(
            flow.consecutive_failures
            if expected_consecutive_failures is None
            else expected_consecutive_failures
        ),
        reason=reason,
        evidence_path=evidence,
        attested_untracked_failures=attest,
        now_utc_epoch=now,
    )


def ledger(path: Path) -> list[tuple[object, ...]]:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT * FROM flow_attempts ORDER BY attempt_seq").fetchall()


class InspectedRetryAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / "state.sqlite3"
        self.state = open_state(self.path)
        self.addCleanup(lambda: self.state.close())

    def assert_denied(self, reason: str, call: Callable[[], object]) -> None:
        before = self.state.get_flow(FLOW)
        audits = len(self.state.list_flow_inspections(FLOW))
        with self.assertRaises(FlowInspectionDenied) as raised:
            call()
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(self.state.get_flow(FLOW), before)
        self.assertEqual(len(self.state.list_flow_inspections(FLOW)), audits)

    def test_exhausted_flow_stays_blocked_until_inspected_rearm_and_history_is_retained(self) -> None:
        runs = exhaust(self.state, 1_000.0)
        self.assertEqual(len({run.run_id for run in runs}), 1)  # retried occurrence reuses its row
        flow = flow_of(self.state)
        self.assertTrue(flow.blocked)
        self.assertEqual(flow.blocked_reason, "RETRY_EXHAUSTED")
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 0))

        # The existing unblock path keeps the failure count, so a claim re-blocks.
        arm(self.state, 1_300.0)
        self.assertIsNotNone(self.state.unblock_flow(FLOW))
        self.assertIsNone(attempt(self.state, 1_310.0))
        flow = flow_of(self.state)
        self.assertTrue(flow.blocked)
        self.assertEqual(flow.blocked_reason, "RETRY_EXHAUSTED")
        disarm(self.state, 1_320.0)

        run_before = self.state.get_run(runs[0].run_id)
        ledger_before = ledger(self.path)
        self.assertEqual([row[10] for row in ledger_before], [0, 0, 2])  # consumed_inputs per attempt
        self.assertEqual([row[11] for row in ledger_before], [0, 0, 0])  # consumed_actions per attempt
        flow_before = flow_of(self.state)

        review = self.state.review_flow_inspection(FLOW, now_utc_epoch=1_400.0)
        self.assertTrue(review.eligible, review.reason)
        self.assertEqual(review.window_summary["tracked_failures"], 3)

        inspection = inspect(self.state, 1_400.0)
        flow = flow_of(self.state)
        self.assertFalse(flow.blocked)
        self.assertIsNone(flow.blocked_reason)
        self.assertFalse(flow.enabled)
        self.assertEqual(flow.generation, flow_before.generation)
        self.assertEqual(flow.max_attempts, 3)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 3))
        self.assertEqual(flow.retry_window_failures, 0)
        self.assertEqual((flow.next_occurrence_key, flow.reset_id), (0, RESET))
        self.assertEqual(self.state.get_run(runs[0].run_id), run_before)
        self.assertEqual(ledger(self.path), ledger_before)

        audits = self.state.list_flow_inspections(FLOW)
        self.assertEqual(audits, (inspection,))
        self.assertEqual(inspection.evidence_reference, "tests/test_inspected_retry_admission.py")
        self.assertEqual(inspection.evidence_sha256, hashlib.sha256(EVIDENCE[0].read_bytes()).hexdigest())
        self.assertEqual(inspection.prior_blocked_reason, "RETRY_EXHAUSTED")
        self.assertEqual((inspection.consecutive_failures, inspection.failure_baseline), (3, 3))
        self.assertEqual(inspection.last_attempt_seq, 3)
        self.assertEqual(inspection.attested_untracked_failures, 0)

        with contextlib.closing(sqlite3.connect(self.path)) as db:
            for statement in (
                "UPDATE flow_inspections SET reason = 'edited'",
                "DELETE FROM flow_inspections",
                "UPDATE flow_attempts SET consumed_actions = 0",
                "DELETE FROM flow_attempts",
            ):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.DatabaseError):
                    db.execute(statement)

    def test_new_window_is_finite_survives_restart_and_exhausts_again(self) -> None:
        runs = exhaust(self.state, 1_000.0)
        inspect(self.state, 1_400.0)
        self.state.close()
        self.state = open_state(self.path)
        flow = flow_of(self.state)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 3))

        arm(self.state, 1_500.0)
        retried = [
            present(attempt(self.state, 1_500.0 + 100.0 * index), f"retry {index}") for index in range(3)
        ]
        self.assertTrue(all(run.run_id == runs[0].run_id for run in retried))
        flow = flow_of(self.state)
        self.assertTrue(flow.blocked)
        self.assertEqual(flow.blocked_reason, "RETRY_EXHAUSTED")
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (6, 3))
        self.assertIsNone(attempt(self.state, 2_000.0))
        self.assertEqual(flow.next_occurrence_key, 0)
        disarm(self.state, 2_050.0)

        self.assert_denied("EVIDENCE_ALREADY_USED", lambda: inspect(self.state, 2_100.0))
        second = inspect(self.state, 2_100.0, evidence=EVIDENCE[1])
        self.assertEqual((second.prior_failure_baseline, second.failure_baseline), (3, 6))
        self.assertEqual(len(self.state.list_flow_inspections(FLOW)), 2)
        self.assertEqual(len(ledger(self.path)), 6)

    def test_ordinary_success_resets_failure_bookkeeping_without_extra_progress(self) -> None:
        exhaust(self.state, 1_000.0)
        inspect(self.state, 1_400.0)
        arm(self.state, 1_500.0)
        self.assertIsNotNone(attempt(self.state, 1_500.0))
        flow = flow_of(self.state)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (4, 3))
        succeeded = present(attempt(
            self.state, 1_600.0,
            AttemptSpec(target=RunState.SUCCEEDED, reason="FOOD_USED", outcome="action_performed"),
        ), "successful attempt")
        self.assertEqual(succeeded.state, RunState.SUCCEEDED)
        flow = flow_of(self.state)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (0, 0))
        self.assertEqual(flow.next_occurrence_key, 1)  # the success itself, not the rearm
        self.assertEqual(len(ledger(self.path)), 5)
        self.assertEqual(len(self.state.list_flow_inspections(FLOW)), 1)

    def test_controls_owner_stale_duplicate_and_unexhausted_fail_closed(self) -> None:
        exhaust(self.state, 1_000.0)

        self.state.set_service_enabled(True, now_utc_epoch=1_300.0)
        self.assert_denied("SERVICE_ENABLED", lambda: inspect(self.state, 1_310.0))
        self.state.set_service_enabled(False, emergency_reason="inspection", now_utc_epoch=1_320.0)
        self.state.set_flow_enabled(FLOW, True, now_utc_epoch=1_330.0)
        self.assert_denied("FLOW_ENABLED", lambda: inspect(self.state, 1_340.0))
        self.state.set_flow_enabled(FLOW, False, now_utc_epoch=1_350.0)

        lease = present(
            self.state.acquire_service_lease(now_utc_epoch=1_360.0, lease_ttl_seconds=1_000.0),
            "operator lease",
        )
        self.assert_denied("SERVICE_OWNER_ACTIVE", lambda: inspect(self.state, 1_370.0))
        self.state.release_service_lease(lease_generation=lease.lease_generation)

        flow = flow_of(self.state)
        self.assert_denied(
            "STALE_FLOW_STATE",
            lambda: inspect(self.state, 1_380.0, expected_row_version=flow.row_version - 1),
        )
        self.assert_denied(
            "STALE_FLOW_STATE",
            lambda: inspect(self.state, 1_380.0, expected_generation=flow.generation + 1),
        )
        self.assert_denied(
            "STALE_FLOW_STATE",
            lambda: inspect(self.state, 1_380.0, expected_consecutive_failures=2),
        )

        self.state.observe_clock(5_000.0)
        self.assert_denied("CLOCK_ROLLBACK", lambda: inspect(self.state, 1_390.0))

        stale = flow_of(self.state)
        inspect(self.state, 5_100.0)
        self.assert_denied("STALE_FLOW_STATE", lambda: inspect(
            self.state, 5_200.0,
            expected_generation=stale.generation,
            expected_row_version=stale.row_version,
            expected_consecutive_failures=stale.consecutive_failures,
        ))
        self.assert_denied("FLOW_NOT_BLOCKED", lambda: inspect(self.state, 5_200.0, evidence=EVIDENCE[1]))
        self.assertEqual(len(self.state.list_flow_inspections(FLOW)), 1)

        arm(self.state, 5_300.0, OTHER)
        self.assertIsNotNone(attempt(self.state, 5_300.0, flow_id=OTHER))
        disarm(self.state, 5_350.0, OTHER)
        other = present(
            self.state.block_flow(OTHER, "MANUAL_HOLD", now_utc_epoch=5_360.0), "blocked other flow"
        )
        with self.assertRaises(FlowInspectionDenied) as raised:
            self.state.inspect_rearm_flow(
                OTHER, expected_generation=other.generation, expected_row_version=other.row_version,
                expected_consecutive_failures=1, reason="not exhausted", evidence_path=EVIDENCE[0],
                now_utc_epoch=5_400.0,
            )
        self.assertEqual(raised.exception.reason, "RETRY_NOT_EXHAUSTED")

    def test_in_flight_run_fails_closed(self) -> None:
        exhaust(self.state, 1_000.0)
        arm(self.state, 1_300.0, OTHER)
        lease = present(
            self.state.acquire_service_lease(now_utc_epoch=1_300.0, lease_ttl_seconds=10.0), "service lease"
        )
        self.assertIsNotNone(self.state.claim_occurrence(
            OTHER, RESET, now_utc_epoch=1_300.0, lease_generation=lease.lease_generation,
            owner_instance_id=OWNER, process_start_token=PROCESS,
        ))
        self.state.set_service_enabled(False, emergency_reason="stop", now_utc_epoch=1_310.0)
        self.state.set_flow_enabled(OTHER, False, now_utc_epoch=1_310.0)
        self.assert_denied("ACTIVE_RUN", lambda: inspect(self.state, 1_400.0))

    def test_unknown_consequential_unaccounted_or_uncertain_attempts_are_not_eligible(self) -> None:
        cases = {
            "UNRESOLVED_ACTION": AttemptSpec(unknown_action=True),
            "CONSEQUENTIAL_ATTEMPT": AttemptSpec(inputs=3, actions=1),
            "ACCOUNTING_UNVERIFIED": AttemptSpec(
                inputs=2, reason=NAVIGATION_BLOCK + "; accounting_rejected:native totals are a lower bound",
            ),
            "UNCERTAIN_OUTCOME": AttemptSpec(target=RunState.FAILED, outcome="unresolved"),
        }
        for reason, third in cases.items():
            with self.subTest(reason=reason):
                self.state.close()
                self.path = self.folder / f"{reason}.sqlite3"
                self.state = open_state(self.path)
                exhaust(self.state, 1_000.0, third=third)
                review = self.state.review_flow_inspection(FLOW, now_utc_epoch=1_400.0)
                self.assertFalse(review.eligible)
                self.assertEqual(review.reason, reason)
                self.assert_denied(reason, lambda: inspect(self.state, 1_400.0))

    def test_consequential_attempt_overwritten_by_reclaim_is_still_denied(self) -> None:
        runs = exhaust(self.state, 1_000.0, first=AttemptSpec(inputs=3, actions=1))
        # The reclaim zeroes the reused run row's counters; the ledger retains them.
        run = present(self.state.get_run(runs[0].run_id), "reused run")
        self.assertEqual(run.consumed_actions, 0)
        self.assert_denied("CONSEQUENTIAL_ATTEMPT", lambda: inspect(self.state, 1_400.0))

    def test_unverified_accounting_needs_exact_per_attempt_zero_gameplay_attestation(self) -> None:
        accounting = AttemptSpec(reason=NAVIGATION_BLOCK + "; accounting_rejected:CONSUMPTION_ACCOUNTING_MISSING")
        exhaust(self.state, 1_000.0, third=accounting)
        seqs = [int(row[0]) for row in ledger(self.path)]
        self.assertEqual(len(seqs), 3)
        for attested, reason in (
            ((), "ACCOUNTING_UNVERIFIED"),
            ((seqs[0],), "ACCOUNTING_UNVERIFIED"),
            ((seqs[0], seqs[2]), "ACCOUNTING_ATTESTATION_MISMATCH"),
        ):
            with self.subTest(attested=attested):
                review = self.state.review_flow_inspection(
                    FLOW, attested_zero_gameplay_attempts=attested, now_utc_epoch=1_400.0
                )
                self.assertEqual((review.eligible, review.reason), (False, reason))
        with self.assertRaises(ValueError):
            self.state.review_flow_inspection(
                FLOW, attested_zero_gameplay_attempts=(seqs[2], seqs[2]), now_utc_epoch=1_400.0
            )

        before = flow_of(self.state)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli_main([
                "--state-path", str(self.path), "inspect-rearm", FLOW,
                "--expected-generation", str(before.generation),
                "--expected-row-version", str(before.row_version),
                "--expected-consecutive-failures", str(before.consecutive_failures),
                "--attest-zero-gameplay-attempt", str(seqs[2]),
                "--evidence", str(EVIDENCE[0]), "--reason", INSPECTION_REASON,
                "--now-utc-epoch", "1400",
            ])
        result = json_object(json.loads(output.getvalue().strip().splitlines()[-1]))
        self.assertEqual((code, result["status"]), (0, "rearmed"))
        (audit,) = self.state.list_flow_inspections(FLOW)
        self.assertEqual(audit.window_summary["attested_zero_gameplay_attempts"], [seqs[2]])
        self.assertEqual(audit.attested_untracked_failures, 0)
        flow = flow_of(self.state)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 3))
        self.assertEqual((flow.enabled, flow.blocked), (False, False))

    def test_zero_gameplay_attestation_never_clears_dispatched_or_unknown_effects(self) -> None:
        cases = {
            "UNRESOLVED_ACTION": AttemptSpec(unknown_action=True, reason=NAVIGATION_BLOCK + "; accounting_rejected:x"),
            "CONSEQUENTIAL_ATTEMPT": AttemptSpec(inputs=3, actions=1, reason=NAVIGATION_BLOCK + "; accounting_rejected:x"),
        }
        for reason, third in cases.items():
            with self.subTest(reason=reason):
                self.state.close()
                self.path = self.folder / f"attested-{reason}.sqlite3"
                self.state = open_state(self.path)
                exhaust(self.state, 1_000.0, third=third)
                third_seq = int(ledger(self.path)[-1][0])
                self.assert_denied(reason, lambda: self.state.inspect_rearm_flow(
                    FLOW, expected_generation=flow_of(self.state).generation,
                    expected_row_version=flow_of(self.state).row_version,
                    expected_consecutive_failures=3, reason=INSPECTION_REASON,
                    evidence_path=EVIDENCE[0], attested_zero_gameplay_attempts=(third_seq,),
                    now_utc_epoch=1_400.0,
                ))

    def test_pre_ledger_failures_require_exact_audited_attestation(self) -> None:
        exhaust(self.state, 1_000.0)
        self.state.close()
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            # Reconstruct a database whose failures predate the attempt ledger.
            db.execute("DROP TRIGGER flow_attempts_append_only_delete")
            db.execute("DELETE FROM flow_attempts")
            db.commit()
        self.state = open_state(self.path)

        review = self.state.review_flow_inspection(FLOW, now_utc_epoch=1_400.0)
        self.assertEqual(review.reason, "UNTRACKED_FAILURE_ATTESTATION_MISMATCH")
        self.assertEqual(review.untracked_failures, 3)
        for attest in (0, 2, 4):
            with self.subTest(attest=attest):
                self.assert_denied(
                    "UNTRACKED_FAILURE_ATTESTATION_MISMATCH",
                    lambda: inspect(self.state, 1_400.0, attest=attest),
                )
        first = inspect(self.state, 1_400.0, attest=3)
        self.assertEqual((first.attested_untracked_failures, first.last_attempt_seq), (3, None))

        arm(self.state, 1_500.0)
        for index in range(3):
            self.assertIsNotNone(attempt(self.state, 1_500.0 + 100.0 * index))
        disarm(self.state, 1_850.0)
        self.assertEqual(self.state.review_flow_inspection(FLOW, now_utc_epoch=1_900.0).untracked_failures, 0)
        self.assert_denied(
            "UNTRACKED_FAILURE_ATTESTATION_MISMATCH",
            lambda: inspect(self.state, 1_900.0, evidence=EVIDENCE[1], attest=3),
        )
        second = inspect(self.state, 1_900.0, evidence=EVIDENCE[1])
        self.assertEqual((second.attested_untracked_failures, second.failure_baseline), (0, 6))

    def test_missing_or_unretained_evidence_and_reason_fail_closed(self) -> None:
        exhaust(self.state, 1_000.0)
        outside = self.folder / "outside-repository.json"
        outside.write_text("{}", encoding="utf-8")
        for evidence in (REPOSITORY_ROOT / "missing-inspection-evidence.json", outside):
            with self.subTest(evidence=evidence):
                self.assert_denied("EVIDENCE_NOT_RETAINED", lambda: inspect(self.state, 1_400.0, evidence=evidence))
        with self.assertRaises(ValueError):
            inspect(self.state, 1_400.0, reason=" ")
        self.assertTrue(flow_of(self.state).blocked)

    def test_reset_rollover_never_resets_failures_or_baseline(self) -> None:
        exhaust(self.state, 1_000.0)
        self.state.update_reset(FLOW, "reset-2", now_utc_epoch=1_300.0)
        flow = flow_of(self.state)
        self.assertTrue(flow.blocked)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 0))
        inspect(self.state, 1_400.0)
        self.state.update_reset(FLOW, "reset-3", now_utc_epoch=1_500.0)
        flow = flow_of(self.state)
        self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (3, 3))


class InspectedRetryRenameContinuityTests(unittest.TestCase):
    def test_canonical_rename_keeps_ledger_and_inspection_history_without_fresh_attestation(self) -> None:
        old, new = RENAMED_FLOW_IDS[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state = BotStateManager(path, owner_instance_id=OWNER, process_start_token=PROCESS, process_id=101)
            try:
                state.initialize_flows([FlowSpec(old, cadence="daily_once_per_reset", max_attempts=3)])
                runs = exhaust(state, 1_000.0, flow_id=old)
                first = inspect(state, 1_400.0, flow_id=old)
                arm(state, 1_500.0, old)
                for index in range(3):
                    self.assertIsNotNone(attempt(state, 1_500.0 + 100.0 * index, flow_id=old))
                disarm(state, 1_850.0, old)
            finally:
                state.close()

            # The writable reopen runs the canonical #36 flow-id migration.
            state = BotStateManager(path, owner_instance_id=OWNER, process_start_token=PROCESS, process_id=101)
            try:
                self.assertIsNone(state.get_flow(old))
                flow = flow_of(state, new)
                self.assertTrue(flow.blocked)
                self.assertEqual(flow.blocked_reason, "RETRY_EXHAUSTED")
                self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (6, 3))
                self.assertEqual(present(state.get_run(runs[0].run_id), "migrated run").flow_id, new)

                # Immutable history keeps the id it was written under.
                retained = ledger(path)
                self.assertEqual(len(retained), 6)
                self.assertEqual({row[1] for row in retained}, {old})
                self.assertEqual({row[2] for row in retained}, {runs[0].run_id})
                self.assertEqual(state.list_flow_inspections(new), (first,))
                self.assertEqual(first.flow_id, old)

                # Fully accounted history resolves through run ids: no fresh attestation.
                review = state.review_flow_inspection(new, now_utc_epoch=1_900.0)
                self.assertTrue(review.eligible, review.reason)
                self.assertEqual(review.untracked_failures, 0)
                self.assertEqual(review.window_summary["tracked_failures"], 6)
                before = flow_of(state, new)
                with self.assertRaises(FlowInspectionDenied) as raised:
                    inspect(state, 1_900.0, flow_id=new)
                self.assertEqual(raised.exception.reason, "EVIDENCE_ALREADY_USED")
                self.assertEqual(flow_of(state, new), before)

                second = inspect(state, 1_900.0, flow_id=new, evidence=EVIDENCE[1])
                self.assertEqual((second.flow_id, second.last_attempt_seq), (new, 6))
                self.assertEqual((second.prior_failure_baseline, second.failure_baseline), (3, 6))
                self.assertEqual(state.list_flow_inspections(new), (first, second))
            finally:
                state.close()


class InspectedRetrySchedulerCliTests(unittest.TestCase):
    def cli(
        self, path: Path, *arguments: str, global_flags: tuple[str, ...] = ()
    ) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli_main([
                *global_flags, "--state-path", str(path), "inspect-rearm", SCHEDULER_FLOW_ID, *arguments,
            ])
        return code, json_object(json.loads(output.getvalue().strip().splitlines()[-1]))

    def test_scheduler_window_exhausts_rearms_through_cli_and_exhausts_again(self) -> None:
        descriptor = make_descriptor()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state, coordinator, handler = initialize(path, descriptor)
            try:
                handler.result = NormalizedResult(NormalizedOutcome.BLOCKED, "BAG_NAVIGATION_BLOCKED")
                for now in (100.0, 110.0, 120.0):
                    coordinator.pulse(make_facts(now=now))
                self.assertEqual(handler.plan_calls, 3)
                flow = flow_of(state, SCHEDULER_FLOW_ID)
                self.assertTrue(flow.blocked)
                self.assertEqual(flow.blocked_reason, "RETRY_EXHAUSTED")
                self.assertIsNone(coordinator.select(make_facts(now=130.0)))
                coordinator.pulse(make_facts(now=130.0))
                self.assertEqual(handler.plan_calls, 3)

                state.set_flow_enabled(SCHEDULER_FLOW_ID, False, now_utc_epoch=135.0)
                state.set_service_enabled(False, emergency_reason="inspection", now_utc_epoch=135.0)
                # pnsctl forwards its supervised BlueStacks flags; the state-only command ignores them.
                code, preview = self.cli(
                    path, "--preview", "--now-utc-epoch", "140",
                    global_flags=("--mode", "supervised", "--adapter", "bluestacks"),
                )
                self.assertEqual((code, preview["status"]), (0, "eligible"))
                facts = json_object(preview["flow"])
                self.assertEqual(facts["retry_window_failures"], 3)
                rearm = (
                    "--expected-generation", str(facts["generation"]),
                    "--expected-row-version", str(facts["row_version"]),
                    "--expected-consecutive-failures", str(facts["consecutive_failures"]),
                    "--evidence", str(EVIDENCE[0]),
                    "--reason", "inspected zero-effect navigation failure",
                    "--now-utc-epoch", "141",
                )
                code, rearmed = self.cli(path, *rearm)
                self.assertEqual((code, rearmed["status"]), (0, "rearmed"))
                rearmed_flow = json_object(rearmed["flow"])
                self.assertEqual(rearmed_flow["inspected_failure_baseline"], 3)
                self.assertEqual(rearmed_flow["consecutive_failures"], 3)
                code, replay = self.cli(path, *rearm)
                self.assertEqual((code, replay["reason"]), (2, "STALE_FLOW_STATE"))

                state.set_service_enabled(True, now_utc_epoch=145.0)
                state.set_flow_enabled(SCHEDULER_FLOW_ID, True, now_utc_epoch=145.0)
                self.assertIsNotNone(coordinator.select(make_facts(now=150.0)))
                for now in (150.0, 160.0, 170.0):
                    coordinator.pulse(make_facts(now=now))
                self.assertEqual(handler.plan_calls, 6)
                flow = flow_of(state, SCHEDULER_FLOW_ID)
                self.assertTrue(flow.blocked)
                self.assertEqual((flow.consecutive_failures, flow.inspected_failure_baseline), (6, 3))
                coordinator.pulse(make_facts(now=180.0))
                self.assertEqual(handler.plan_calls, 6)
            finally:
                state.close()


if __name__ == "__main__":
    unittest.main()
