"""The #36 Campaign flow-id rename migrates persisted state once, without reopening gates."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from automation_service import state as state_module
from automation_service.contracts import FlowSpec, RecurrenceClass, RecurrenceProjection
from automation_service.registry import CAMPAIGN_FLOW_ID
from automation_service.state import (
    RENAMED_FLOW_IDS,
    BotStateManager,
    FlowIdMigrationConflict,
    RunState,
)
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from safe_action_core import store as store_module
from safe_action_core.policy import CAMPAIGN_AP_FLOW_ID
from safe_action_core.store import RENAMED_TASK_IDS, TaskIdMigrationConflict
from tasks.campaign_victory_recovery import RETAINED_CAMPAIGN_FLOW_ID
from tasks.scheduler_task_result import SchedulerAwareTaskResult, SchedulerIdentity


OLD = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"
NEW = "CAMPAIGN-AP-AUTO-BATTLE"
OTHER = "OTHER-FLOW"
OWNER = {"owner_instance_id": "owner-a", "process_start_token": "process-a"}
BATCH = {"occurrence_kind": "reset_bounded", "ready_batch_id": "batch-a",
         "revision_within_reset": 0, "occurrence_limit": 1}
COOLDOWN_DUE = 10_000.0


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as db:
        return list(db.iterdump())


def _contains(path: Path, text: str) -> bool:
    return any(text in line for line in _dump(path))


def _manager(path: Path) -> BotStateManager:
    return BotStateManager(path, process_id=101, **OWNER)


def _enable(manager: BotStateManager, *flow_ids: str) -> int:
    manager.initialize_flows(FlowSpec(flow_id, cadence="daily_once_per_reset") for flow_id in flow_ids)
    manager.set_service_enabled(True, now_utc_epoch=100.0)
    for flow_id in flow_ids:
        manager.set_flow_enabled(flow_id, True, now_utc_epoch=100.0)
    lease = manager.acquire_service_lease(now_utc_epoch=100.0, lease_ttl_seconds=100_000.0)
    assert lease is not None
    return lease.lease_generation


def _claim(manager: BotStateManager, flow_id: str, generation: int, now: float):
    return manager.claim_occurrence(
        flow_id, "reset-1", now_utc_epoch=now, lease_generation=generation,
        max_inputs=4, max_actions=4, **OWNER, **BATCH,
    )


def _build_state(path: Path) -> str:
    """Persist an enabled old-id flow with a completed reset-bounded run and a cooldown."""

    manager = _manager(path)
    try:
        generation = _enable(manager, OLD, OTHER)
        run = _claim(manager, OLD, generation, 101.0)
        assert run is not None
        token = {"run_token": run.run_token, "lease_generation": run.lease_generation, **OWNER}
        assert manager.transition_run(run.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED,
                                      now_utc_epoch=102.0, **token) is not None
        assert manager.project_terminal(run.run_id, RunState.SUCCEEDED, expected_state=RunState.RUNNING,
                                        now_utc_epoch=103.0, **token).state is RunState.SUCCEEDED
        assert manager.update_schedule(OLD, next_due_at_utc=COOLDOWN_DUE, now_utc_epoch=104.0) is not None
        return run.occurrence_key
    finally:
        manager.close()


def _build_store(path: Path) -> None:
    """Persist old-id scheduler rows: a completed reset, a cooldown, a projection, audit."""

    store = SafetyStore(path)
    try:
        repo = SQLiteSchedulerInvocationRepository(store)
        done = SchedulerIdentity("acct", "srv", "reset-1", OLD)
        claim = repo.claim_occurrence(done, 100.0)
        assert claim is not None
        repo.finalize_claim(claim, SchedulerAwareTaskResult.complete_for_reset(done, "AP_DRAINED"), 101.0)
        cooling = SchedulerIdentity("acct", "srv", "reset-2", OLD)
        claim = repo.claim_occurrence(cooling, 200.0)
        assert claim is not None
        repo.finalize_claim(claim, SchedulerAwareTaskResult.deferred(cooling, "AP_LOW", 500.0), 201.0)
        projection = RecurrenceProjection(RecurrenceClass.QUEUE_GENERATION, observed_at_utc=100.0, generation="g1")
        repo.save_projection(done, f"{done.composite_key}|{OLD}", projection, 100.0)
        store.audit(OLD, "capability_issued", 100.0, {"note": "retained"})
    finally:
        store.close()


class RenameTableTests(unittest.TestCase):
    def test_both_stores_rename_exactly_the_registered_campaign_id(self):
        self.assertEqual(RENAMED_FLOW_IDS, ((OLD, NEW),))
        self.assertEqual(RENAMED_TASK_IDS, RENAMED_FLOW_IDS)
        self.assertEqual(CAMPAIGN_FLOW_ID, NEW)
        self.assertEqual(CAMPAIGN_AP_FLOW_ID, NEW)
        self.assertEqual(RETAINED_CAMPAIGN_FLOW_ID, OLD)


class StateDatabaseMigrationTests(unittest.TestCase):
    def test_old_id_rows_move_to_new_id_and_keep_cooldown_and_reset_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot-state.sqlite3"
            old_key = _build_state(path)
            self.assertTrue(old_key.startswith(f"{OLD}:reset_bounded:"))

            manager = _manager(path)
            try:
                self.assertIsNone(manager.get_flow(OLD))
                flow = manager.get_flow(NEW)
                self.assertTrue(flow.enabled)
                self.assertEqual(flow.reset_id, "reset-1")
                self.assertEqual(flow.next_due_at_utc, COOLDOWN_DUE)
                self.assertEqual(flow.next_occurrence_key, 1)
                self.assertTrue(manager.get_flow(OTHER).enabled)
                # All mutable authority and progress moved to the new id; only the
                # append-only attempt ledger keeps the id its history was written under.
                self.assertEqual(
                    [line for line in _dump(path)
                     if OLD in line and not line.startswith('INSERT INTO "flow_attempts"')],
                    [],
                )
                with closing(sqlite3.connect(path)) as db:
                    rows = db.execute("SELECT flow_id, occurrence_key, state FROM runs").fetchall()
                    history = db.execute(
                        """SELECT flow_attempts.flow_id, flow_attempts.occurrence_key,
                                  flow_attempts.attempt_state, runs.flow_id
                           FROM flow_attempts JOIN runs ON runs.run_id = flow_attempts.run_id"""
                    ).fetchall()
                self.assertEqual(rows, [(NEW, NEW + old_key[len(OLD):], "SUCCEEDED")])
                self.assertEqual(history, [(OLD, old_key, "SUCCEEDED", NEW)])

                generation = manager.get_service_lease().lease_generation
                # Cooldown gate: the next scheduled claim is still not due.
                self.assertIsNone(_claim(manager, NEW, generation, 200.0))
                self.assertIsNone(manager.get_flow(NEW).blocked_reason)
                # Reset gate: with the cooldown lifted, the completed batch stays used up.
                manager.update_schedule(NEW, next_due_at_utc=None, now_utc_epoch=201.0)
                self.assertIsNone(_claim(manager, NEW, generation, 202.0))
                self.assertEqual(manager.get_flow(NEW).blocked_reason, "RESET_BOUNDED_EXHAUSTED")
            finally:
                manager.close()

    def test_without_the_migration_the_new_id_could_claim_the_same_reset_again(self):
        # Sensitivity check: the gates above hold only because the rows moved.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot-state.sqlite3"
            _build_state(path)
            with patch.object(state_module, "RENAMED_FLOW_IDS", ()):
                manager = _manager(path)
                try:
                    generation = _enable(manager, NEW)
                    self.assertIsNotNone(_claim(manager, NEW, generation, 202.0))
                finally:
                    manager.close()

    def test_second_open_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot-state.sqlite3"
            _build_state(path)
            _manager(path).close()
            migrated = _dump(path)
            _manager(path).close()
            self.assertEqual(_dump(path), migrated)

    def test_rows_under_both_ids_fail_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot-state.sqlite3"
            _build_state(path)
            with patch.object(state_module, "RENAMED_FLOW_IDS", ()):
                manager = _manager(path)
                manager.initialize_flows([FlowSpec(NEW)])
                manager.close()
            before = _dump(path)
            with self.assertRaisesRegex(FlowIdMigrationConflict, "rows exist under both ids"):
                _manager(path)
            self.assertEqual(_dump(path), before)


class SafetyStoreMigrationTests(unittest.TestCase):
    def test_old_task_rows_move_to_new_id_and_keep_reset_and_cooldown_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "safety.sqlite3"
            _build_store(path)
            store = SafetyStore(path)
            try:
                self.assertFalse(_contains(path, OLD))
                repo = SQLiteSchedulerInvocationRepository(store)
                done = SchedulerIdentity("acct", "srv", "reset-1", NEW)
                cooling = SchedulerIdentity("acct", "srv", "reset-2", NEW)
                self.assertEqual(repo.get(done).status, "complete_for_reset")
                self.assertEqual(
                    repo.get_occurrence(f"{done.composite_key}|daily_once_per_reset|0").status,
                    "COMPLETED",
                )
                self.assertIsNotNone(repo.get_projection(f"{done.composite_key}|{NEW}"))
                self.assertEqual(
                    [row["task_id"] for row in store.connection.execute("SELECT task_id FROM audit_events")],
                    [NEW],
                )
                # Reset gate: the completed reset is not claimable again.
                self.assertIsNone(repo.claim_occurrence(done, 300.0))
                # Cooldown gate: the deferred reset waits for its deadline, then resumes.
                self.assertIsNone(repo.claim_occurrence(cooling, 400.0))
                self.assertIsNotNone(repo.claim_occurrence(cooling, 600.0))
            finally:
                store.close()

    def test_without_the_migration_the_new_id_could_claim_the_completed_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "safety.sqlite3"
            _build_store(path)
            with patch.object(store_module, "RENAMED_TASK_IDS", ()):
                store = SafetyStore(path)
                try:
                    repo = SQLiteSchedulerInvocationRepository(store)
                    self.assertIsNotNone(
                        repo.claim_occurrence(SchedulerIdentity("acct", "srv", "reset-1", NEW), 300.0)
                    )
                finally:
                    store.close()

    def test_second_open_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "safety.sqlite3"
            _build_store(path)
            SafetyStore(path).close()
            migrated = _dump(path)
            SafetyStore(path).close()
            self.assertEqual(_dump(path), migrated)

    def test_rows_under_both_ids_fail_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "safety.sqlite3"
            _build_store(path)
            with patch.object(store_module, "RENAMED_TASK_IDS", ()):
                store = SafetyStore(path)
                store.audit(NEW, "capability_issued", 300.0, {})
                store.close()
            before = _dump(path)
            with self.assertRaisesRegex(TaskIdMigrationConflict, "rows exist under both ids"):
                SafetyStore(path)
            self.assertEqual(_dump(path), before)


if __name__ == "__main__":
    unittest.main()
