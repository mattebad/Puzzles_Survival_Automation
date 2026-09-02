"""Focused behavioral coverage for the canonical automation-service authority."""

from pathlib import Path
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from automation_service.contracts import FlowSpec
from automation_service.state import (
    ActionState,
    BotStateManager,
    REPOSITORY_ROOT,
    RunState,
    StateBusyError,
    TerminalProjectionError,
    resolve_state_path,
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
def start_running(manager: BotStateManager, run, *, now: float = 102.0):
    started = manager.transition_run(
        run.run_id,
        RunState.RUNNING,
        expected_state=RunState.CLAIMED,
        **run_auth(
            run,
            owner=run.owner_instance_id,
            process_token=run.process_start_token,
        ),
        now_utc_epoch=now,
    )
    assert started is not None
    return started



def run_auth(run, *, owner: str = "owner-a", process_token: str = "process-a") -> dict[str, object]:
    return {
        "owner_instance_id": owner,
        "process_start_token": process_token,
        "run_token": run.run_token,
        "lease_generation": run.lease_generation,
    }


class AutomationServiceStateTests(unittest.TestCase):

    def test_default_and_relative_paths_are_rooted_at_repository(self):
        previous = os.environ.pop("AUTOMATION_SERVICE_STATE_PATH", None)
        try:
            expected = (REPOSITORY_ROOT / ".local-orchestrator" / "bot-state.sqlite3").resolve()
            self.assertEqual(Path(resolve_state_path()), expected)
            self.assertEqual(
                Path(resolve_state_path("relative/state.sqlite3")),
                (REPOSITORY_ROOT / "relative" / "state.sqlite3").resolve(),
            )
            os.environ["AUTOMATION_SERVICE_STATE_PATH"] = "from-environment.sqlite3"
            self.assertEqual(
                Path(resolve_state_path()),
                (REPOSITORY_ROOT / "from-environment.sqlite3").resolve(),
            )
        finally:
            if previous is not None:
                os.environ["AUTOMATION_SERVICE_STATE_PATH"] = previous
            else:
                os.environ.pop("AUTOMATION_SERVICE_STATE_PATH", None)

    def test_managers_from_different_cwds_share_default_service_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            first_cwd = base / "first"
            second_cwd = base / "second"
            first_cwd.mkdir()
            second_cwd.mkdir()
            path = base / "shared.sqlite3"
            previous_cwd = Path.cwd()
            first = second = None
            try:
                with patch.object(BotStateManager, "DEFAULT_DB_PATH", str(path)):
                    os.chdir(first_cwd)
                    first = BotStateManager(
                        owner_instance_id="owner-first",
                        process_start_token="process-first",
                        process_id=1001,
                    )
                    first.initialize_flows(
                        [FlowSpec(FLOW_ID, default_enabled=False, cadence="manual")]
                    )
                    first.set_service_enabled(True, now_utc_epoch=1.0)
                    first.set_flow_enabled(FLOW_ID, True, now_utc_epoch=1.0)
                    lease = first.acquire_service_lease(
                        now_utc_epoch=1.0,
                        lease_ttl_seconds=60.0,
                    )
                    self.assertIsNotNone(lease)
                    os.chdir(second_cwd)
                    second = BotStateManager(
                        owner_instance_id="owner-second",
                        process_start_token="process-second",
                        process_id=1002,
                    )
                    self.assertEqual(first.db_path, second.db_path)
                    self.assertEqual(
                        second.get_service_lease().owner_instance_id,
                        "owner-first",
                    )
                    self.assertIsNone(
                        second.acquire_service_lease(
                            now_utc_epoch=2.0,
                            lease_ttl_seconds=60.0,
                        )
                    )
            finally:
                os.chdir(previous_cwd)
                if second is not None:
                    second.close()
                if first is not None:
                    first.release_service_lease(
                        owner_instance_id="owner-first",
                        process_start_token="process-first",
                        lease_generation=first.get_service_lease().lease_generation,
                    )
                    first.close()
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
                run = manager.transition_run(
                    run.run_id, RunState.RUNNING, expected_state=RunState.CLAIMED,
                    **run_auth(run), now_utc_epoch=101.5,
                )
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
                run = start_running(manager, run)
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
                run = start_running(manager, run)
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
                run = start_running(manager, run)
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


    def test_post_transport_unknown_crosses_generation_fences_without_refund_or_retry(self):
        for fence in ("service", "flow"):
            with self.subTest(fence=fence), tempfile.TemporaryDirectory() as folder:
                manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
                try:
                    run = claim(manager, generation)
                    self.assertIsNotNone(run)
                    assert run is not None
                    run = start_running(manager, run)
                    action = manager.reserve_action(
                        run.run_id,
                        f"post-transport-{fence}",
                        "tap",
                        input_cost=2,
                        **run_auth(run),
                        now_utc_epoch=103.0,
                    )
                    self.assertIsNotNone(action)
                    assert action is not None
                    self.assertIsNotNone(
                        manager.transition_action(
                            action.action_id,
                            ActionState.DISPATCHING,
                            expected_state=ActionState.RESERVED,
                            **run_auth(run),
                            now_utc_epoch=104.0,
                        )
                    )
                    if fence == "service":
                        manager.set_service_enabled(
                            False, emergency_reason="operator stop", now_utc_epoch=105.0
                        )
                    else:
                        manager.set_flow_enabled(FLOW_ID, False, now_utc_epoch=105.0)

                    marked = manager.mark_post_transport_unknown(
                        action.action_id,
                        **run_auth(run),
                        outcome_reason="TRANSPORT_EXCEPTION:TimeoutError",
                        transport_summary="transport raised after dispatch",
                        consequence_summary="reconciliation required",
                        now_utc_epoch=106.0,
                    )
                    self.assertIsNotNone(marked)
                    assert marked is not None
                    self.assertEqual(marked.state, ActionState.UNKNOWN)
                    self.assertEqual(marked.outcome_reason, "TRANSPORT_EXCEPTION:TimeoutError")
                    self.assertEqual(manager.get_run(run.run_id).consumed_inputs, 2)
                    self.assertEqual(manager.get_run(run.run_id).consumed_actions, 1)
                    self.assertIsNone(
                        manager.transition_action(
                            action.action_id,
                            ActionState.SUCCEEDED,
                            expected_state=ActionState.UNKNOWN,
                            **run_auth(run),
                            now_utc_epoch=107.0,
                        )
                    )
                    terminal = manager.project_terminal(
                        run.run_id,
                        RunState.BLOCKED,
                        expected_state=RunState.STOP_REQUESTED,
                        reason="EMERGENCY_STOP",
                        **run_auth(run),
                        now_utc_epoch=108.0,
                    )
                    self.assertEqual(terminal.state, RunState.BLOCKED)
                    self.assertFalse(manager.can_retry_run(run.run_id))
                    if fence == "service":
                        manager.set_service_enabled(True, now_utc_epoch=109.0)
                    else:
                        manager.set_flow_enabled(FLOW_ID, True, now_utc_epoch=109.0)
                    self.assertIsNone(claim(manager, generation, now=110.0))
                    self.assertIsNone(
                        manager.mark_post_transport_unknown(
                            action.action_id,
                            **run_auth(run),
                            now_utc_epoch=109.0,
                        )
                    )
                finally:
                    manager.close()


    def test_post_transport_unknown_requires_exact_tokens_and_current_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                run = start_running(manager, run)
                action = manager.reserve_action(
                    run.run_id,
                    "post-transport-token-fence",
                    "tap",
                    **run_auth(run),
                    now_utc_epoch=103.0,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    manager.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                for kwargs in (
                    {"owner_instance_id": "owner-b"},
                    {"process_start_token": "process-b"},
                    {"run_token": "stale-run-token"},
                    {"lease_generation": generation + 1},
                ):
                    auth = run_auth(run)
                    auth.update(kwargs)
                    self.assertIsNone(
                        manager.mark_post_transport_unknown(
                            action.action_id,
                            **auth,
                            now_utc_epoch=105.0,
                        )
                    )
                    self.assertEqual(manager.get_action(action.action_id).state, ActionState.DISPATCHING)
                marked = manager.mark_post_transport_unknown(
                    action.action_id,
                    **run_auth(run),
                    now_utc_epoch=106.0,
                )
                self.assertIsNotNone(marked)
                assert marked is not None
                self.assertEqual(marked.state, ActionState.UNKNOWN)
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
                    now_utc_epoch=253.0,
                    owner_instance_id="owner-b",
                    process_start_token="process-b",
                    lease_generation=lease.lease_generation,
                    max_inputs=4,
                    max_actions=4,
                )
                self.assertIsNotNone(reclaimed)
                assert reclaimed is not None
                reclaimed = start_running(restarted, reclaimed, now=252.0)
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
                self.assertEqual(recovered.state, RunState.RECOVERING)
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
                resolved = observer.reconcile_unknown_action(
                    reclaimed.run_id,
                    action.action_id,
                    ActionState.BLOCKED,
                    owner_instance_id="owner-c",
                    process_start_token="process-c",
                    run_token=recovered.run_token,
                    lease_generation=lease.lease_generation,
                    now_utc_epoch=402.0,
                )
                self.assertIsNotNone(resolved)
                terminal = observer.terminalize_recovered_run(
                    reclaimed.run_id,
                    owner_instance_id="owner-c",
                    process_start_token="process-c",
                    run_token=recovered.run_token,
                    lease_generation=lease.lease_generation,
                    now_utc_epoch=403.0,
                )
                self.assertIsNotNone(terminal)
                self.assertEqual(terminal.state, RunState.BLOCKED)
                self.assertIsNone(observer.get_service_lease().owner_instance_id)
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

    def test_non_reset_projection_survives_reset_rollover_and_changes_only_with_new_basis(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                first = manager.claim_occurrence(
                    FLOW_ID,
                    "reset-1",
                    occurrence_kind="projection",
                    projection_generation="projection-1",
                    owner_instance_id="owner-a",
                    process_start_token="process-a",
                    lease_generation=generation,
                    max_inputs=4,
                    max_actions=4,
                    now_utc_epoch=101.0,
                )
                self.assertIsNotNone(first)
                assert first is not None
                self.assertEqual(
                    first.occurrence_key,
                    f"{FLOW_ID}:projection:projection-1",
                )
                before_rollover = manager.get_flow(FLOW_ID)
                self.assertEqual(before_rollover.next_occurrence_key, 0)
                self.assertEqual(before_rollover.next_occurrence_basis, "projection-1")
                self.assertEqual(before_rollover.next_occurrence_kind, "projection")

                rolled = manager.update_reset(
                    FLOW_ID, "reset-2", now_utc_epoch=102.0
                )
                self.assertIsNotNone(rolled)
                assert rolled is not None
                self.assertEqual(rolled.reset_id, "reset-2")
                self.assertEqual(rolled.next_occurrence_key, 0)
                self.assertEqual(rolled.next_occurrence_basis, "projection-1")
                self.assertEqual(rolled.next_occurrence_kind, "projection")

                running = start_running(manager, first, now=103.0)
                completed = manager.project_terminal(
                    running.run_id,
                    RunState.SUCCEEDED,
                    expected_state=RunState.RUNNING,
                    **run_auth(running),
                    now_utc_epoch=104.0,
                )
                self.assertEqual(completed.state, RunState.SUCCEEDED)
                after_old_terminal = manager.get_flow(FLOW_ID)
                self.assertEqual(after_old_terminal.next_occurrence_key, 0)
                self.assertEqual(after_old_terminal.next_occurrence_basis, "projection-1")
                self.assertEqual(after_old_terminal.next_occurrence_kind, "projection")

                self.assertIsNone(
                    manager.claim_occurrence(
                        FLOW_ID,
                        "reset-2",
                        occurrence_kind="projection",
                        projection_generation="projection-1",
                        owner_instance_id="owner-a",
                        process_start_token="process-a",
                        lease_generation=generation,
                        max_inputs=4,
                        max_actions=4,
                        now_utc_epoch=105.0,
                    )
                )
                second = manager.claim_occurrence(
                    FLOW_ID,
                    "reset-2",
                    occurrence_kind="projection",
                    projection_generation="projection-2",
                    owner_instance_id="owner-a",
                    process_start_token="process-a",
                    lease_generation=generation,
                    max_inputs=4,
                    max_actions=4,
                    now_utc_epoch=106.0,
                )
                self.assertIsNotNone(second)
                assert second is not None
                self.assertNotEqual(second.occurrence_key, first.occurrence_key)
                self.assertEqual(
                    second.occurrence_key,
                    f"{FLOW_ID}:projection:projection-2",
                )
            finally:
                manager.close()


    def test_daily_occurrence_remains_strictly_reset_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                first = claim(manager, generation, now=101.0)
                self.assertIsNotNone(first)
                assert first is not None
                first = start_running(manager, first, now=102.0)
                manager.project_terminal(
                    first.run_id,
                    RunState.SUCCEEDED,
                    expected_state=RunState.RUNNING,
                    **run_auth(first),
                    now_utc_epoch=103.0,
                )
                self.assertIsNone(
                    manager.claim_occurrence(
                        FLOW_ID,
                        "reset-2",
                        owner_instance_id="owner-a",
                        process_start_token="process-a",
                        lease_generation=generation,
                        max_inputs=4,
                        max_actions=4,
                        now_utc_epoch=104.0,
                    )
                )
            finally:
                manager.close()


    def test_unknown_effect_prevents_failed_run_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                run = start_running(manager, run)
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
                run = start_running(manager, run)
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
                run = start_running(manager, run)
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
    def test_recurrence_identity_kinds_are_deterministic_and_reset_scoped(self):
        daily = BotStateManager.occurrence_key(FLOW_ID, "r1", 0)
        self.assertEqual(daily, f"{FLOW_ID}:r1:0")
        self.assertNotEqual(daily, BotStateManager.occurrence_key(FLOW_ID, "r2", 0))
        timer_a = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 0, occurrence_kind="timer", timer_slot="slot-1"
        )
        timer_b = BotStateManager.occurrence_key(
            FLOW_ID, "r2", 0, occurrence_kind="timer", timer_slot="slot-1"
        )
        self.assertEqual(timer_a, timer_b)
        self.assertNotEqual(
            timer_a,
            BotStateManager.occurrence_key(
                FLOW_ID, "r1", 0, occurrence_kind="timer", timer_slot="slot-2"
            ),
        )
        projection = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 0, occurrence_kind="projection", projection_generation="g1"
        )
        resource = BotStateManager.occurrence_key(
            FLOW_ID, "r2", 0, occurrence_kind="resource", resource_generation="g1"
        )
        self.assertNotEqual(projection, resource)
        bounded_1 = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 0, occurrence_kind="bounded_repeat",
            repeat_sequence="seq-1", repeat_ordinal=0,
        )
        bounded_2 = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 0, occurrence_kind="bounded_repeat",
            repeat_sequence="seq-1", repeat_ordinal=1,
        )
        self.assertNotEqual(bounded_1, bounded_2)
        queue = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 0, occurrence_kind="queue_generation",
            queue_generation="q1",
        )
        march = BotStateManager.occurrence_key(
            FLOW_ID, "r2", 0, occurrence_kind="march_generation",
            march_generation="m1",
        )
        self.assertNotEqual(queue, march)
        manual = BotStateManager.occurrence_key(
            FLOW_ID, "r1", 99, occurrence_kind="manual",
            operator_request_id="operator-42",
        )
        self.assertEqual(
            manual,
            BotStateManager.occurrence_key(
                FLOW_ID, "r2", 0, occurrence_kind="manual",
                operator_request_id="operator-42",
            ),
        )

        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                first = claim(manager, generation)
                self.assertIsNotNone(first)
                assert first is not None
                first = start_running(manager, first)
                first = manager.project_terminal(
                    first.run_id, RunState.SUCCEEDED, expected_state=RunState.RUNNING,
                    **run_auth(first), now_utc_epoch=102.0,
                )
                self.assertEqual(manager.get_flow(FLOW_ID).next_occurrence_key, 1)
                manual_run = manager.claim_occurrence(
                    FLOW_ID, RESET_ID, mode="manual",
                    operator_request_id="operator-42", now_utc_epoch=103.0,
                    owner_instance_id="owner-a", process_start_token="process-a",
                    lease_generation=generation, max_inputs=1, max_actions=1,
                )
                self.assertIsNotNone(manual_run)
                assert manual_run is not None
                self.assertEqual(manager.get_flow(FLOW_ID).next_occurrence_key, 1)
                self.assertEqual(manual_run.occurrence_kind, "manual")
                self.assertEqual(manual_run.occurrence_basis, "operator-42")
            finally:
                manager.close()

    def test_running_is_required_before_reservation_or_dispatch_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, generation = bootstrap_manager(Path(folder) / "state.sqlite3")
            try:
                run = claim(manager, generation)
                self.assertIsNotNone(run)
                assert run is not None
                auth = run_auth(run)
                self.assertIsNone(
                    manager.reserve_action(run.run_id, "claimed", "tap", **auth, now_utc_epoch=102.0)
                )
                self.assertEqual(
                    manager.validate_dispatch(run.run_id, **auth, now_utc_epoch=102.0).reason,
                    "RUN_NOT_RUNNING",
                )
                running = start_running(manager, run)
                action = manager.reserve_action(
                    running.run_id, "running", "tap", **run_auth(running), now_utc_epoch=103.0
                )
                self.assertIsNotNone(action)
            finally:
                manager.close()

    def test_fenced_reconciliation_takeover_resolves_unknown_without_new_input(self):
        for outcome in (ActionState.SUCCEEDED, ActionState.NO_EFFECT, ActionState.BLOCKED):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "state.sqlite3"
                owner_a, generation_a = bootstrap_manager(path)
                run = claim(owner_a, generation_a)
                self.assertIsNotNone(run)
                assert run is not None
                run = start_running(owner_a, run)
                action = owner_a.reserve_action(
                    run.run_id, "orphan", "tap", action_id="orphan-action",
                    **run_auth(run), now_utc_epoch=103.0,
                )
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNotNone(
                    owner_a.transition_action(
                        action.action_id, ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED, **run_auth(run), now_utc_epoch=104.0,
                    )
                )
                self.assertIsNotNone(
                    owner_a.transition_action(
                        action.action_id, ActionState.UNKNOWN,
                        expected_state=ActionState.DISPATCHING, **run_auth(run), now_utc_epoch=105.0,
                    )
                )
                owner_a.close()

                owner_b = BotStateManager(
                    path, owner_instance_id="owner-b", process_start_token="process-b", process_id=202
                )
                try:
                    lease = owner_b.acquire_service_lease(
                        now_utc_epoch=200.0, lease_ttl_seconds=100.0
                    )
                    self.assertIsNotNone(lease)
                    assert lease is not None
                    recovered = owner_b.takeover_orphan(
                        run.run_id, now_utc_epoch=200.0, heartbeat_timeout_seconds=10.0,
                        owner_instance_id="owner-b", process_start_token="process-b",
                        lease_generation=lease.lease_generation,
                    )
                    self.assertIsNotNone(recovered)
                    assert recovered is not None
                    self.assertEqual(recovered.state, RunState.RECOVERING)
                    self.assertEqual(owner_b.get_action(action.action_id).state, ActionState.UNKNOWN)
                    self.assertIsNone(
                        owner_b.reserve_action(
                            run.run_id, "must-not-reserve", "tap",
                            **run_auth(recovered, owner="owner-b", process_token="process-b"),
                            now_utc_epoch=201.0,
                        )
                    )
                    self.assertIsNone(
                        owner_b.reconcile_unknown_action(
                            run.run_id, action.action_id, outcome,
                            owner_instance_id="owner-a", process_start_token="process-a",
                            run_token=run.run_token, lease_generation=run.lease_generation,
                            now_utc_epoch=201.0,
                        )
                    )
                    resolved = owner_b.reconcile_unknown_action(
                        run.run_id, action.action_id, outcome,
                        owner_instance_id="owner-b", process_start_token="process-b",
                        run_token=recovered.run_token, lease_generation=lease.lease_generation,
                        now_utc_epoch=202.0,
                    )
                    self.assertIsNotNone(resolved)
                    terminal = owner_b.terminalize_recovered_run(
                        run.run_id, owner_instance_id="owner-b", process_start_token="process-b",
                        run_token=recovered.run_token, lease_generation=lease.lease_generation,
                        now_utc_epoch=203.0,
                    )
                    self.assertIsNotNone(terminal)
                    self.assertEqual(terminal.state, RunState.BLOCKED)
                    self.assertIsNone(owner_b.get_service_lease().owner_instance_id)
                finally:
                    owner_b.close()

    def test_busy_write_is_bounded_and_typed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            bootstrap, _generation = bootstrap_manager(path)
            bootstrap.close()
            manager = BotStateManager(
                path, owner_instance_id="owner-a", process_start_token="process-a",
                process_id=101, busy_timeout_ms=25,
            )
            holder = sqlite3.connect(path, timeout=0.01, isolation_level=None)
            try:
                holder.execute("BEGIN IMMEDIATE")
                started = time.monotonic()
                with self.assertRaises(StateBusyError) as error:
                    manager.update_retry(
                        FLOW_ID, last_outcome="BUSY", now_utc_epoch=102.0
                    )
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(error.exception.reason, "SQLITE_BUSY")
                self.assertTrue(error.exception.retryable)
            finally:
                holder.rollback()
                holder.close()
                manager.close()

    def test_twenty_managers_yield_one_active_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            seed, _generation = bootstrap_manager(path)
            seed.release_service_lease(
                owner_instance_id="owner-a", process_start_token="process-a",
                lease_generation=seed.get_service_lease().lease_generation,
            )
            seed.close()
            managers = [
                BotStateManager(
                    path, owner_instance_id=f"owner-{i}", process_start_token=f"token-{i}",
                    process_id=1000 + i,
                )
                for i in range(20)
            ]
            barrier = threading.Barrier(20)
            claims = []

            def attempt(manager):
                barrier.wait()
                claims.append(manager.claim_occurrence(FLOW_ID, RESET_ID, now_utc_epoch=101.0))

            threads = [threading.Thread(target=attempt, args=(m,)) for m in managers]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            try:
                self.assertEqual(sum(item is not None for item in claims), 1)
                self.assertEqual(
                    sum(
                        item.state in {RunState.CLAIMED, RunState.RUNNING, RunState.RECOVERING, RunState.STOP_REQUESTED}
                        for item in claims if item is not None
                    ),
                    1,
                )
            finally:
                for manager in managers:
                    manager.close()

    def test_service_lease_competition_rotates_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            first = BotStateManager(path, owner_instance_id="owner-a", process_start_token="token-a", process_id=1)
            second = BotStateManager(path, owner_instance_id="owner-b", process_start_token="token-b", process_id=2)
            try:
                lease_a = first.acquire_service_lease(now_utc_epoch=100.0, lease_ttl_seconds=10.0)
                self.assertIsNotNone(lease_a)
                assert lease_a is not None
                self.assertIsNone(second.acquire_service_lease(now_utc_epoch=105.0, lease_ttl_seconds=10.0))
                lease_b = second.acquire_service_lease(now_utc_epoch=110.0, lease_ttl_seconds=10.0)
                self.assertIsNotNone(lease_b)
                assert lease_b is not None
                self.assertGreater(lease_b.lease_generation, lease_a.lease_generation)
                self.assertIsNone(
                    first.renew_service_lease(
                        owner_instance_id="owner-a", process_start_token="token-a",
                        lease_generation=lease_a.lease_generation, now_utc_epoch=111.0,
                    )
                )
            finally:
                first.close()
                second.close()

if __name__ == "__main__":
    unittest.main()
