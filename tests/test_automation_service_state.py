"""Focused behavioral coverage for the canonical automation-service authority."""

from pathlib import Path
import tempfile
import unittest

from automation_service.contracts import FlowSpec
from automation_service.state import (
    ActionState,
    BotStateManager,
    RunState,
    TerminalProjectionError,
)


FLOW_ID = "FLOW-TEST"
RESET_ID = "reset-1"


def bootstrap_manager(path: Path, *, owner: str = "owner-a", process_token: str = "process-a") -> tuple[BotStateManager, int]:
    manager = BotStateManager(path, owner_instance_id=owner, process_start_token=process_token, process_id=101)
    manager.initialize_flows(
        [
            FlowSpec(
                FLOW_ID,
                default_enabled=True,
                priority=17,
                cadence="manual",
                max_wait_seconds=90.0,
                max_attempts=4,
            )
        ]
    )
    manager.set_service_enabled(True, now_utc_epoch=100.0)
    manager.set_flow_enabled(FLOW_ID, True, now_utc_epoch=100.0)
    lease = manager.acquire_service_lease(now_utc_epoch=100.0, lease_ttl_seconds=100.0)
    assert lease is not None
    return manager, lease.lease_generation


def claim(manager: BotStateManager, lease_generation: int, *, now: float = 101.0, owner: str = "owner-a", process_token: str = "process-a"):
    return manager.claim_occurrence(
        FLOW_ID,
        RESET_ID,
        now_utc_epoch=now,
        owner_instance_id=owner,
        process_start_token=process_token,
        lease_generation=lease_generation,
        max_inputs=4,
        max_actions=4,
    )


def run_auth(run, *, owner: str = "owner-a", process_token: str = "process-a") -> dict[str, object]:
    return {
        "owner_instance_id": owner,
        "process_start_token": process_token,
        "run_token": run.run_token,
        "lease_generation": run.lease_generation,
    }


class AutomationServiceStateTests(unittest.TestCase):
    def test_fresh_database_and_flow_spec_defaults_are_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = BotStateManager(Path(folder) / "state.sqlite3", owner_instance_id="owner-a")
            try:
                service = manager.get_service()
                self.assertFalse(service.enabled)
                self.assertEqual(service.generation, 0)
                self.assertIsNone(service.emergency_reason)
                self.assertEqual(manager.get_service_lease().lease_generation, 0)
                states = manager.initialize_flows(
                    [FlowSpec(FLOW_ID, default_enabled=True, priority=7, cadence="daily", max_wait_seconds=120.0, max_attempts=2)]
                )
                self.assertFalse(states[0].enabled)
                self.assertEqual(states[0].next_occurrence_key, 0)
            finally:
                manager.close()

    def test_lease_takeover_fences_stale_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            manager, generation = bootstrap_manager(path)
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertTrue(manager.validate_dispatch(run.run_id, **run_auth(run), now_utc_epoch=102.0).valid)

                stale = BotStateManager(path, owner_instance_id="owner-b", process_start_token="process-b", process_id=202)
                try:
                    self.assertIsNone(stale.acquire_service_lease(now_utc_epoch=150.0, lease_ttl_seconds=10.0))
                    takeover = stale.acquire_service_lease(now_utc_epoch=201.0, lease_ttl_seconds=100.0)
                    self.assertIsNotNone(takeover)
                    assert takeover is not None
                    self.assertGreater(takeover.lease_generation, generation)
                    self.assertEqual(
                        manager.validate_dispatch(run.run_id, **run_auth(run), now_utc_epoch=202.0).reason,
                        "SERVICE_LEASE_MISMATCH",
                    )
                    self.assertIsNone(manager.reserve_action(run.run_id, "idempotency-stale", "tap", **run_auth(run), now_utc_epoch=203.0))
                finally:
                    stale.close()
            finally:
                manager.close()

    def test_owner_and_run_tokens_are_required_for_action_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertIsNone(manager.reserve_action(run.run_id, "id-only", "tap", now_utc_epoch=102.0))
                action = manager.reserve_action(run.run_id, "idempotency-1", "tap", **run_auth(run), action_id="action-1", now_utc_epoch=102.0)
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNone(
                    manager.transition_action(action.action_id, ActionState.DISPATCHING, expected_state=ActionState.RESERVED, now_utc_epoch=103.0)
                )
                dispatching = manager.transition_action(
                    action.action_id,
                    ActionState.DISPATCHING,
                    expected_state=ActionState.RESERVED,
                    **run_auth(run),
                    now_utc_epoch=103.0,
                )
                self.assertIsNotNone(dispatching)
            finally:
                manager.close()

    def test_retry_reuses_occurrence_identity_until_success(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                first = claim(manager, generation, now=101.0)
                self.assertIsNotNone(first)
                assert first is not None
                self.assertEqual(first.occurrence_key, f"{FLOW_ID}:{RESET_ID}:0")
                self.assertIsNotNone(manager.transition_run(first.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED, **run_auth(first), now_utc_epoch=102.0))
                failed = manager.project_terminal(
                    first.run_id,
                    RunState.FAILED,
                    expected_state=RunState.RUNNING,
                    retry_not_before_utc=120.0,
                    outcome="FAILED",
                    reason="transient",
                    **run_auth(first),
                    now_utc_epoch=103.0,
                )
                self.assertEqual(failed.occurrence_key, first.occurrence_key)
                self.assertEqual(manager.get_flow(FLOW_ID).next_occurrence_key, 0)
                self.assertIsNone(claim(manager, generation, now=119.0))
                retry = claim(manager, generation, now=120.0)
                self.assertIsNotNone(retry)
                assert retry is not None
                self.assertEqual(retry.run_id, first.run_id)
                self.assertEqual(retry.occurrence_key, first.occurrence_key)
                self.assertIsNotNone(manager.transition_run(retry.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED, **run_auth(retry), now_utc_epoch=121.0))
                completed = manager.project_terminal(
                    retry.run_id,
                    RunState.SUCCEEDED,
                    expected_state=RunState.RUNNING,
                    outcome="SUCCEEDED",
                    **run_auth(retry),
                    now_utc_epoch=122.0,
                )
                self.assertEqual(completed.state, RunState.SUCCEEDED)
                self.assertEqual(manager.get_flow(FLOW_ID).next_occurrence_key, 1)
            finally:
                manager.close()

    def test_reserved_cancel_and_block_refund_budget_but_dispatch_unknown_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                action = manager.reserve_action(run.run_id, "refund-cancel", "tap", input_cost=2, **run_auth(run), now_utc_epoch=102.0)
                self.assertIsNotNone(action)
                assert action is not None
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 2)
                cancelled = manager.transition_action(action.action_id, ActionState.CANCELLED, **run_auth(run), now_utc_epoch=103.0)
                self.assertIsNotNone(cancelled)
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 0)

                blocked = manager.reserve_action(run.run_id, "refund-block", "tap", input_cost=1, **run_auth(run), now_utc_epoch=104.0)
                self.assertIsNotNone(blocked)
                assert blocked is not None
                self.assertIsNotNone(manager.transition_action(blocked.action_id, ActionState.BLOCKED, **run_auth(run), now_utc_epoch=105.0))
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 0)

                unknown = manager.reserve_action(run.run_id, "no-refund-unknown", "tap", input_cost=1, **run_auth(run), now_utc_epoch=106.0)
                self.assertIsNotNone(unknown)
                assert unknown is not None
                self.assertIsNotNone(manager.transition_action(unknown.action_id, ActionState.DISPATCHING, expected_state=ActionState.RESERVED, **run_auth(run), now_utc_epoch=107.0))
                self.assertIsNotNone(manager.transition_action(unknown.action_id, ActionState.UNKNOWN, expected_state=ActionState.DISPATCHING, **run_auth(run), now_utc_epoch=108.0))
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 1)
            finally:
                manager.close()

    def test_terminal_projection_reports_compare_and_set_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertIsNotNone(manager.transition_run(run.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED, **run_auth(run), now_utc_epoch=102.0))
                completed = manager.project_terminal(run.run_id, RunState.SUCCEEDED, expected_state=RunState.RUNNING, **run_auth(run), now_utc_epoch=103.0)
                self.assertEqual(completed.state, RunState.SUCCEEDED)
                with self.assertRaises(TerminalProjectionError) as error:
                    manager.project_terminal(run.run_id, RunState.FAILED, expected_row_version=run.row_version, **run_auth(run), now_utc_epoch=104.0)
                self.assertEqual(error.exception.reason, "TERMINAL_CAS_FAILED")
            finally:
                manager.close()


    def test_emergency_stop_allows_exact_fenced_safe_terminal_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertIsNotNone(
                    manager.transition_run(
                        run.run_id,
                        RunState.RUNNING,
                        expected_state=RunState.CLAIMED,
                        **run_auth(run),
                        now_utc_epoch=102.0,
                    )
                )
                manager.set_service_enabled(False, emergency_reason="operator stop", now_utc_epoch=103.0)
                self.assertIsNone(
                    manager.reserve_action(
                        run.run_id,
                        "fenced-after-stop",
                        "tap",
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                terminal = manager.project_terminal(
                    run.run_id,
                    RunState.BLOCKED,
                    expected_state=RunState.STOP_REQUESTED,
                    reason="EMERGENCY_STOP",
                    **run_auth(run),
                    now_utc_epoch=105.0,
                )
                self.assertEqual(terminal.state, RunState.BLOCKED)
                self.assertTrue(
                    manager.release_service_lease(
                        owner_instance_id="owner-a",
                        process_start_token="process-a",
                        lease_generation=generation,
                    )
                )
                self.assertIsNone(manager.get_service_lease().owner_instance_id)
            finally:
                manager.close()
    def test_pretransport_abort_requires_proof_and_refunds_only_dispatching_action(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                action = manager.reserve_action(
                    run.run_id,
                    "pretransport-abort",
                    "tap",
                    input_cost=2,
                    **run_auth(run),
                    now_utc_epoch=101.0,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    manager.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(run),
                        now_utc_epoch=102.0,
                    )
                )
                manager.set_service_enabled(False, emergency_reason="operator stop", now_utc_epoch=103.0)
                self.assertIsNone(
                    manager.transition_action(
                        action.action_id,
                        ActionState.BLOCKED,
                        expected_state=ActionState.DISPATCHING,
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 2)
                self.assertIsNone(
                    manager.abort_pretransport_action(
                        action.action_id,
                        **run_auth(run),
                        transport_attempted=True,
                        now_utc_epoch=104.0,
                    )
                )
                self.assertIsNone(
                    manager.abort_pretransport_action(
                        action.action_id,
                        owner_instance_id="other-owner",
                        process_start_token="process-a",
                        run_token=run.run_token,
                        lease_generation=run.lease_generation,
                        transport_attempted=False,
                        now_utc_epoch=104.0,
                    )
                )
                aborted = manager.abort_pretransport_action(
                    action.action_id,
                    **run_auth(run),
                    transport_attempted=False,
                    outcome_reason="EMERGENCY_STOP",
                    now_utc_epoch=105.0,
                )
                self.assertIsNotNone(aborted)
                assert aborted is not None
                self.assertEqual(aborted.state, ActionState.BLOCKED)
                self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 0)
                terminal = manager.project_terminal(
                    run.run_id,
                    RunState.BLOCKED,
                    expected_state=RunState.STOP_REQUESTED,
                    reason="EMERGENCY_STOP",
                    **run_auth(run),
                    now_utc_epoch=106.0,
                )
                self.assertEqual(terminal.state, RunState.BLOCKED)
            finally:
                manager.close()


    def test_restart_orphan_recovery_reclaims_reservation_but_blocks_unknown_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            manager, generation = bootstrap_manager(path)
            run = claim(manager, generation)
            self.assertIsNotNone(run)
            assert run is not None
            manager.close()

            restarted = BotStateManager(
                path,
                owner_instance_id="owner-b",
                process_start_token="process-b",
                process_id=202,
            )
            try:
                lease = restarted.acquire_service_lease(now_utc_epoch=250.0, lease_ttl_seconds=100.0)
                self.assertIsNotNone(lease)
                assert lease is not None
                recovered = restarted.recover_orphan(
                    run.run_id,
                    now_utc_epoch=250.0,
                    heartbeat_timeout_seconds=10.0,
                )
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.state, RunState.FAILED)
                reclaimed = restarted.claim_occurrence(
                    FLOW_ID,
                    RESET_ID,
                    now_utc_epoch=251.0,
                    owner_instance_id="owner-b",
                    process_start_token="process-b",
                    lease_generation=lease.lease_generation,
                    max_inputs=4,
                    max_actions=4,
                )
                self.assertIsNotNone(reclaimed)
                assert reclaimed is not None
                action = restarted.reserve_action(
                    reclaimed.run_id,
                    "orphan-dispatch",
                    "tap",
                    **run_auth(reclaimed, owner="owner-b", process_token="process-b"),
                    now_utc_epoch=252.0,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    restarted.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(reclaimed, owner="owner-b", process_token="process-b"),
                        now_utc_epoch=253.0,
                    )
                )
            finally:
                restarted.close()

            observer = BotStateManager(
                path,
                owner_instance_id="owner-c",
                process_start_token="process-c",
                process_id=303,
            )
            try:
                lease = observer.acquire_service_lease(now_utc_epoch=400.0, lease_ttl_seconds=100.0)
                self.assertIsNotNone(lease)
                assert lease is not None
                recovered = observer.recover_orphan(
                    reclaimed.run_id,
                    now_utc_epoch=400.0,
                    heartbeat_timeout_seconds=10.0,
                )
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.state, RunState.BLOCKED)
                self.assertTrue(observer.has_unresolved_actions(reclaimed.run_id))
                self.assertEqual(observer.get_action(action.action_id).state, ActionState.UNKNOWN)
                self.assertIsNone(
                    observer.claim_occurrence(
                        FLOW_ID,
                        RESET_ID,
                        now_utc_epoch=401.0,
                        owner_instance_id="owner-c",
                        process_start_token="process-c",
                        lease_generation=lease.lease_generation,
                        max_inputs=4,
                        max_actions=4,
                    )
                )
            finally:
                observer.close()

    def test_old_reset_completion_does_not_advance_new_reset_ordinal(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                old = claim(manager, generation, now=101.0)
                self.assertIsNotNone(old)
                assert old is not None
                self.assertEqual(old.occurrence_key, f"{FLOW_ID}:{RESET_ID}:0")
                updated = manager.update_reset(FLOW_ID, "reset-2", now_utc_epoch=102.0)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.next_occurrence_key, 0)
                self.assertIsNotNone(
                    manager.transition_run(
                        old.run_id,
                        RunState.RUNNING,
                        expected_state=RunState.CLAIMED,
                        **run_auth(old),
                        now_utc_epoch=103.0,
                    )
                )
                manager.project_terminal(
                    old.run_id,
                    RunState.SUCCEEDED,
                    expected_state=RunState.RUNNING,
                    **run_auth(old),
                    now_utc_epoch=104.0,
                )
                self.assertEqual(manager.get_flow(FLOW_ID).next_occurrence_key, 0)
                new = manager.claim_occurrence(
                    FLOW_ID,
                    "reset-2",
                    now_utc_epoch=105.0,
                    owner_instance_id="owner-a",
                    process_start_token="process-a",
                    lease_generation=generation,
                    max_inputs=4,
                    max_actions=4,
                )
                self.assertIsNotNone(new)
                assert new is not None
                self.assertEqual(new.occurrence_key, f"{FLOW_ID}:reset-2:0")
            finally:
                manager.close()

    def test_unknown_effect_prevents_failed_run_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                action = manager.reserve_action(
                    run.run_id,
                    "unknown-effect",
                    "tap",
                    **run_auth(run),
                    now_utc_epoch=102.0,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    manager.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(run),
                        now_utc_epoch=103.0,
                    )
                )
                self.assertIsNotNone(
                    manager.transition_action(
                        action.action_id,
                        ActionState.UNKNOWN,
                        expected_state=ActionState.DISPATCHING,
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                self.assertIsNotNone(
                    manager.transition_run(
                        run.run_id,
                        RunState.RUNNING,
                        expected_state=RunState.CLAIMED,
                        **run_auth(run),
                        now_utc_epoch=105.0,
                    )
                )
                manager.project_terminal(
                    run.run_id,
                    RunState.FAILED,
                    expected_state=RunState.RUNNING,
                    retry_not_before_utc=106.0,
                    **run_auth(run),
                    now_utc_epoch=105.5,
                )
                self.assertTrue(manager.has_unresolved_actions(run.run_id))
                self.assertFalse(manager.can_retry_run(run.run_id))
                self.assertIsNone(claim(manager, generation, now=200.0))
            finally:
                manager.close()

    def test_binding_fingerprint_rejects_duplicate_key_and_allows_changed_no_effect_hypothesis(self):
        binding = {
            "source_stable_roi_digest": "source-roi",
            "source_binding_digest": "source-binding",
            "target_identity": "tap-target",
            "target_binding_digest": "target-binding",
        }
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                first = manager.reserve_action(
                    run.run_id,
                    "binding-key-1",
                    "tap",
                    hypothesis_digest="hypothesis-a",
                    **binding,
                    **run_auth(run),
                    now_utc_epoch=102.0,
                )
                self.assertIsNotNone(first)
                assert first is not None
                self.assertTrue(first.binding_fingerprint)
                self.assertIsNone(
                    manager.reserve_action(
                        run.run_id,
                        "binding-key-2",
                        "tap",
                        hypothesis_digest="hypothesis-a",
                        **binding,
                        **run_auth(run),
                        now_utc_epoch=103.0,
                    )
                )
            finally:
                manager.close()

        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                first = manager.reserve_action(
                    run.run_id,
                    "no-effect-key-1",
                    "tap",
                    hypothesis_digest="hypothesis-a",
                    **binding,
                    **run_auth(run),
                    now_utc_epoch=102.0,
                )
                self.assertIsNotNone(first)
                assert first is not None
                self.assertIsNotNone(
                    manager.transition_action(
                        first.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(run),
                        now_utc_epoch=103.0,
                    )
                )
                self.assertIsNotNone(
                    manager.transition_action(
                        first.action_id,
                        ActionState.NO_EFFECT,
                        expected_state=ActionState.DISPATCHING,
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                self.assertIsNone(
                    manager.reserve_action(
                        run.run_id,
                        "no-effect-key-2",
                        "tap",
                        retry_of_action_id=first.action_id,
                        hypothesis_digest="hypothesis-a",
                        **binding,
                        **run_auth(run),
                        now_utc_epoch=105.0,
                    )
                )
                retry = manager.reserve_action(
                    run.run_id,
                    "no-effect-key-3",
                    "tap",
                    retry_of_action_id=first.action_id,
                    hypothesis_digest="hypothesis-b",
                    **binding,
                    **run_auth(run),
                    now_utc_epoch=106.0,
                )
                self.assertIsNotNone(retry)
                assert retry is not None
                self.assertEqual(retry.binding_fingerprint, first.binding_fingerprint)
            finally:
                manager.close()

    def test_clock_observation_persists_high_water_and_rejects_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            manager = BotStateManager(path, owner_instance_id="owner-a")
            self.assertTrue(manager.observe_clock(100.0).accepted)
            rollback = manager.observe_clock(90.0)
            self.assertTrue(rollback.clock_rollback)
            self.assertFalse(rollback.accepted)
            self.assertEqual(rollback.high_water_utc, 100.0)
            manager.close()
            restarted = BotStateManager(path, owner_instance_id="owner-b")
            try:
                self.assertEqual(restarted.get_clock().high_water_utc, 100.0)
                self.assertTrue(restarted.observe_clock(100.0).accepted)
            finally:
                restarted.close()
if __name__ == "__main__":
    unittest.main()
