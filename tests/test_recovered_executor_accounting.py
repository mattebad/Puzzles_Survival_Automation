"""Fenced bookkeeping for native executor totals recovered after a lease loss."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from automation_service.contracts import FlowSpec
from automation_service.state import ActionState, BotStateManager, RunState


FLOW_ID = "RECOVERED-NATIVE-EXECUTOR"


def auth(run):
    return {
        "owner_instance_id": run.owner_instance_id,
        "process_start_token": run.process_start_token,
        "run_token": run.run_token,
        "lease_generation": run.lease_generation,
    }


class RecoveredExecutorAccountingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "state.sqlite3"
        self.original = self.manager("original", "original-process", 101)
        self.original.initialize_flows([
            FlowSpec(FLOW_ID, default_enabled=False, cadence="manual"),
            FlowSpec("UNRELATED-FLOW", default_enabled=False, cadence="manual"),
        ])
        self.original.set_service_enabled(True, now_utc_epoch=100.0)
        self.original.set_flow_enabled(FLOW_ID, True, now_utc_epoch=100.0)
        lease = self.original.acquire_service_lease(now_utc_epoch=100.0, lease_ttl_seconds=10.0)
        self.assertIsNotNone(lease)
        run = self.original.claim_occurrence(
            FLOW_ID, "reset-1", now_utc_epoch=101.0,
            owner_instance_id="original", process_start_token="original-process",
            lease_generation=lease.lease_generation, max_inputs=12, max_actions=3,
        )
        self.assertIsNotNone(run)
        self.running = self.original.transition_run(
            run.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED,
            **auth(run), now_utc_epoch=102.0,
        )
        self.assertIsNotNone(self.running)

    def manager(self, owner, token, pid):
        result = BotStateManager(self.path, owner_instance_id=owner,
            process_start_token=token, process_id=pid)
        self.addCleanup(result.close)
        return result

    def recover(self):
        self.original.set_service_enabled(False, now_utc_epoch=106.0)
        self.original.set_flow_enabled(FLOW_ID, False, now_utc_epoch=107.0)
        self.recovery = self.manager("recovery", "recovery-process", 202)
        recovered = self.recovery.takeover_orphan(
            self.running.run_id, now_utc_epoch=200.0,
            heartbeat_timeout_seconds=10.0, lease_ttl_seconds=100.0,
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.state, RunState.RECOVERING)
        return recovered

    def record(self, run, *, consumed_inputs=9, consumed_actions=1, now=201.0, **overrides):
        arguments = dict(auth(run), expected_row_version=run.row_version,
            consumed_inputs=consumed_inputs, consumed_actions=consumed_actions,
            now_utc_epoch=now)
        arguments.update(overrides)
        return self.recovery.record_recovered_executor_consumption(run.run_id, **arguments)

    def unchanged_rows(self):
        return {name: [tuple(row) for row in self.recovery._db.execute(
            f"SELECT * FROM {name} ORDER BY rowid")]
            for name in ("service_control", "service_lease", "flow_state", "actions")}

    def test_takeover_records_totals_without_dispatch_authority_then_terminalizes(self):
        recovered = self.recover()
        untouched = self.unchanged_rows()
        recorded = self.record(recovered)
        self.assertEqual(recorded, replace(recovered, consumed_inputs=9,
            consumed_actions=1, row_version=recovered.row_version + 1))
        self.assertEqual(self.unchanged_rows(), untouched)
        self.assertFalse(self.recovery.get_service_enabled())
        self.assertFalse(self.recovery.get_flow(FLOW_ID).enabled)
        self.assertIsNone(self.recovery.reserve_action(
            recorded.run_id, "not-new-input", "tap", **auth(recorded), now_utc_epoch=202.0))
        terminal = self.recovery.terminalize_recovered_run(
            recorded.run_id, RunState.SUCCEEDED, **auth(recorded),
            reason="independently verified original native result", now_utc_epoch=202.0,
        )
        self.assertEqual(terminal.state, RunState.SUCCEEDED)
        self.assertEqual((terminal.consumed_inputs, terminal.consumed_actions), (9, 1))
        self.assertIsNone(self.recovery.get_service_lease().owner_instance_id)
        self.assertFalse(self.recovery.get_service_enabled())
        self.assertFalse(self.recovery.get_flow(FLOW_ID).enabled)
        self.assertEqual(self.recovery._db.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0)

    def test_current_snapshot_identical_totals_are_idempotent_but_stale_version_is_denied(self):
        recovered = self.recover()
        recorded = self.record(recovered)
        self.assertIsNone(self.record(recovered))
        self.assertEqual(self.record(recorded), recorded)
        self.assertEqual(self.recovery.get_run(recorded.run_id), recorded)

    def test_original_and_mismatched_recovery_fences_cannot_record(self):
        recovered = self.recover()
        invalid = [
            auth(self.running),
            {"owner_instance_id": "foreign"},
            {"process_start_token": "stale-process"},
            {"run_token": self.running.run_token},
            {"lease_generation": self.running.lease_generation},
            {"lease_generation": True},
            {"lease_generation": 0},
            {"owner_instance_id": None},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                self.assertIsNone(self.record(recovered, **overrides))
                self.assertEqual(self.recovery.get_run(recovered.run_id), recovered)

    def test_expired_or_replaced_lease_cannot_record(self):
        recovered = self.recover()
        self.assertIsNone(self.record(recovered, now=300.0))
        foreign = self.manager("foreign", "foreign-process", 303)
        lease = foreign.acquire_service_lease(now_utc_epoch=301.0, lease_ttl_seconds=100.0)
        self.assertIsNotNone(lease)
        self.assertIsNone(self.record(recovered, now=302.0))
        self.assertEqual(self.recovery.get_run(recovered.run_id), recovered)

    def test_normal_accounting_still_denies_recovering_and_recovery_denies_other_states(self):
        self.recovery = self.original
        self.assertIsNone(self.record(self.running, now=103.0))
        self.original.set_service_enabled(False, now_utc_epoch=104.0)
        stopped = self.original.get_run(self.running.run_id)
        self.assertEqual(stopped.state, RunState.STOP_REQUESTED)
        self.assertIsNone(self.record(stopped, now=105.0))
        recovered = self.recover()
        self.assertIsNone(self.recovery.record_executor_consumption(
            recovered.run_id, consumed_inputs=9, consumed_actions=1,
            terminal_accounting=True, **auth(recovered), now_utc_epoch=201.0))
        terminal = self.recovery.terminalize_recovered_run(
            recovered.run_id, RunState.BLOCKED, **auth(recovered), now_utc_epoch=202.0)
        self.assertIsNone(self.record(terminal, now=203.0))

    def test_invalid_or_over_budget_totals_and_counter_refunds_are_denied(self):
        recovered = self.recover()
        for key in ("consumed_inputs", "consumed_actions", "expected_row_version"):
            for value in (-1, True, 1.5, None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.record(recovered, **{key: value})
        for inputs, actions in ((13, 1), (9, 4)):
            with self.subTest(inputs=inputs, actions=actions):
                self.assertIsNone(self.record(recovered, consumed_inputs=inputs, consumed_actions=actions))
        recorded = self.record(recovered)
        for inputs, actions in ((8, 1), (9, 0)):
            with self.subTest(inputs=inputs, actions=actions):
                self.assertIsNone(self.record(recorded, consumed_inputs=inputs, consumed_actions=actions))
                self.assertEqual(self.recovery.get_run(recorded.run_id), recorded)

    def test_any_canonical_action_prevents_mixed_executor_accounting(self):
        action = self.original.reserve_action(
            self.running.run_id, "canonical-action", "tap", **auth(self.running), now_utc_epoch=103.0)
        self.assertIsNotNone(action)
        self.assertIsNotNone(self.original.transition_action(
            action.action_id, ActionState.CANCELLED, expected_state=ActionState.RESERVED,
            **auth(self.running), now_utc_epoch=104.0))
        recovered = self.recover()
        before = self.unchanged_rows()
        self.assertEqual(self.recovery.get_action(action.action_id).state, ActionState.CANCELLED)
        self.assertIsNone(self.record(recovered))
        self.assertEqual(self.recovery.get_run(recovered.run_id), recovered)
        self.assertEqual(self.unchanged_rows(), before)


if __name__ == "__main__":
    unittest.main()
