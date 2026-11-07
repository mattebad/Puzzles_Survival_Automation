"""Daily aggregate batch and milestone service admission contracts."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from automation_service.daily_rewards import (
    FLOW_ID,
    MAX_ACTIONS,
    MAX_INPUTS,
    OBSERVATION_INTERVAL_SECONDS,
    PRODUCT_ID,
    PRODUCT_REVISION,
    DailyRewardsRunner,
    DailyRewardsRunnerError,
    _backend_mapping,
    daily_rewards_next_due,
)
from automation_service.native_execution import NativeRouteOutcome
from automation_service.recruitment import recruitment_reset
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import (
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity


class _HeldLock:
    held = True
    owner = "automation-service"
    invocation_id = "service-invocation"

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("wrong runtime owner assertion")


def _fixture(now: float, directory: Path, *, aggregate: bool, chests=(), no_work=False):
    binding = resource_fixed_runtime_binding()
    instant = datetime.fromtimestamp(now, timezone.utc)
    backend = derive_resource_runtime_identity(binding, instant)
    window = derive_static_utc_reset(instant)
    identity = SchedulerIdentity(
        backend.account_id,
        backend.server_id,
        recruitment_reset(now),
        PRODUCT_ID,
    )
    completed = now + 10
    directory.mkdir(parents=True, exist_ok=True)
    home_bytes = b"offline-test-home-frame"
    (directory / "terminal-home.png").write_bytes(home_bytes)
    home_sha = hashlib.sha256(home_bytes).hexdigest()
    chest_results = []
    for ordinal, state in enumerate(chests, start=1):
        chest_results.append(
            {
                "reset_id": identity.reset_id,
                "target_identity": "activity-milestone-chest",
                "control_class": "MILESTONE_CHEST",
                "ready_state_proven": True,
                "free_only": True,
                "cost_type": "none",
                "successor_milestone_key": f"daily-chest-{ordinal * 30}",
                "milestone_key": f"daily-chest-{ordinal * 30}",
                "status": "confirmed",
                "successor_state": state,
                "source_frame_sha256": f"{ordinal:x}" * 64,
                "successor_frame_sha256": f"{ordinal + 1:x}" * 64,
            }
        )
    action_count = int(aggregate) + len(chest_results)
    result = {
        "status": "completed",
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "task_id": PRODUCT_ID,
        "time_basis": "utc",
        "runtime_profile_id": ACTIVE_RUNTIME_PROFILE_ID,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "started_at_utc": now,
        "completed_at_utc": completed,
        "observation_interval_seconds": OBSERVATION_INTERVAL_SECONDS,
        "next_due_at_utc": completed + OBSERVATION_INTERVAL_SECONDS,
        "occurrence_key": "occ:v1:" + "d" * 64,
        "total_input_count": max(action_count, 1) + 2,
        "total_action_count": action_count,
        "reward_claim_transport_calls": action_count,
        "committed_action_count": action_count,
        "accounting_verified": True,
        "terminal_home_verified": True,
        "effect_reconciliation_required": False,
        "identical_retry_denied": bool(action_count),
        "aggregate_claim": (
            {
                "status": "confirmed",
                "dispatch_count": 1,
                "confirmed": True,
                "reset_id": identity.reset_id,
                "ready_batch_proven": True,
                "free_only": True,
                "control_identity": "daily-quest-claim",
                "ordinary_claim_controls_cleared": True,
                "batch_identity": "batch-v1-" + "b" * 32,
                "source_frame_sha256": "a" * 64,
                "successor_frame_sha256": "c" * 64,
            }
            if aggregate
            else {"status": "none", "dispatch_count": 0, "confirmed": False}
        ),
        "chests_collected": chest_results,
        "milestone_scan": {
            "status": "verified",
            "selected_daily": True,
            "reset_id": identity.reset_id,
            "source_frame_sha256": "e" * 64 if no_work else "f" * 64,
            "ready_chest_count": len(chest_results),
            "ready_chest_keys": [chest["milestone_key"] for chest in chest_results],
            "static_or_locked_chest_keys": [
                f"daily-chest-{value}"
                for value in (30, 60, 90, 120, 150)
                if f"daily-chest-{value}" not in {
                    chest["milestone_key"] for chest in chest_results
                }
            ],
        },
        # Points remain diagnostics and may be unchanged or absent.
        "observed_points": {"before": None, "after": None},
        "unclaimed_ready_chest_count": 0,
        "no_work": no_work,
        "terminal_home_frame": {
            "frame_path": "terminal-home.png",
            "frame_sha256": home_sha,
        },
        "native_session_directory": str(directory),
        "backend_identity": _backend_mapping(
            derive_resource_runtime_identity(binding, datetime.fromtimestamp(completed, timezone.utc))
        ),
    }
    if no_work:
        result["no_work_evidence"] = {
            "selected_daily": True,
            "reset_id": identity.reset_id,
            "source_frame_sha256": "e" * 64,
            "ordinary_claim_controls": 0,
            "ready_chest_count": 0,
            "static_or_locked_chest_keys": [
                "daily-chest-30",
                "daily-chest-60",
                "daily-chest-90",
                "daily-chest-120",
                "daily-chest-150",
            ],
        }
    if aggregate:
        result["aggregate_claim"]["batch_identity"] = "batch-v1-" + "b" * 32
    return identity, result


class _FakeNative:
    flow_id = FLOW_ID
    product_id = PRODUCT_ID
    product_revision = PRODUCT_REVISION
    runtime_profile_id = ACTIVE_RUNTIME_PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(
        self,
        result,
        *,
        failure=None,
        partial_result=None,
        accounting_verified=True,
        input_counts=None,
    ):
        self.result = deepcopy(result)
        self.failure = failure
        self.partial_result = (
            deepcopy(partial_result)
            if partial_result is not None
            else self.result if failure else None
        )
        self.accounting_verified = accounting_verified
        self.input_counts = input_counts
        self.calls = 0
        self.request = None

    def run(self, request):
        counts = self.input_counts or (
            self.result.get("total_input_count", 0),
            self.result.get("total_input_count", 0),
            self.result.get("total_input_count", 0),
        )
        self.calls += 1
        self.request = request
        request.validate_identity()
        return NativeRouteOutcome(
            flow_id=request.flow_id,
            native_result=self.result,
            partial_result=self.partial_result,
            failure=self.failure,
            invocation_id="daily-native-invocation",
            session_directory=self.result["native_session_directory"],
            startup_recovery=None,
            input_count=counts[0],
            session_input_count=counts[1],
            runtime_input_count=counts[2],
            accounting_verified=self.accounting_verified,
        )


class DailyRewardsServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 16, 12, tzinfo=timezone.utc).timestamp()
        self.previous_reset_id = "game-day-2026-08-15"
        self.occurrence_key = "occ:v1:" + "f" * 64

    def _runner(self, directory, native):
        return DailyRewardsRunner(
            native=native,
            output_directory=directory,
            utc_clock=lambda: self.now,
        )

    def test_confirmed_aggregate_and_same_chest_successor_schedule_next_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "native-session"
            identity, result = _fixture(self.now, root, aggregate=True, chests=("opened",))
            # A points-only increase is diagnostic; the chest transition carries success.
            result["observed_points"] = {"before": 0, "after": 100}
            self.assertEqual(
                daily_rewards_next_due(result, identity, self.now),
                result["completed_at_utc"] + OBSERVATION_INTERVAL_SECONDS,
            )

    def test_locked_static_chests_allow_verified_no_work_without_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "native-session"
            identity, result = _fixture(self.now, root, aggregate=False, no_work=True)
            result["observed_points"] = {"before": None, "after": None}
            self.assertEqual(
                daily_rewards_next_due(result, identity, self.now),
                result["next_due_at_utc"],
            )

    def test_ready_chest_points_only_or_locked_successor_is_rejected(self):
        for state in ("ready", "locked", "points_increased"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                identity, result = _fixture(
                    self.now,
                    Path(tmp) / "native-session",
                    aggregate=True,
                    chests=(state,),
                )
                result["observed_points"] = {"before": 0, "after": 100}
                with self.assertRaises(ValueError):
                    daily_rewards_next_due(result, identity, self.now)

    def test_next_due_requires_verified_terminal_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity, result = _fixture(
                self.now,
                Path(tmp) / "native-session",
                aggregate=True,
                chests=("opened",),
            )
            result["terminal_home_verified"] = False
            with self.assertRaises(ValueError):
                daily_rewards_next_due(result, identity, self.now)

    def test_cooldown_restart_and_later_distinct_batch_same_reset(self):
        from automation_service.state import BotStateManager
        from tests.support.service_route_contract import ROUTES, RouteRig

        with RouteRig(self, ROUTES[FLOW_ID]) as rig:
            first = rig.once()
            self.assertEqual(first[0]["status"], "completed", first)
            first_run = rig.runs()[0]
            due = rig.state.get_flow(FLOW_ID).next_due_at_utc
            self.assertEqual(due, rig.stop.now + OBSERVATION_INTERVAL_SECONDS)
            rig.runner.aggregate_ready = False
            with BotStateManager(rig.path) as restarted:
                self.assertEqual(rig.once(restarted), [])
                self.assertEqual(len(rig.runner.calls), 1)
                self.assertEqual(rig.runner.actions, 1)
                rig.stop.now = due
                rig.runner.aggregate_ready = True
                second = rig.once(restarted)
                self.assertEqual(second[0]["status"], "completed", second)
            runs = rig.runs()
            self.assertEqual(len(runs), 2)
            self.assertNotEqual(first_run.occurrence_key, runs[1].occurrence_key)
            self.assertEqual(
                rig.runner.calls[0][0].reset_id,
                rig.runner.calls[1][0].reset_id,
            )
            self.assertEqual(rig.runner.actions, 2)

    def test_complete_scan_requires_five_disjoint_chest_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity, result = _fixture(
                self.now, Path(tmp) / "native-session",
                aggregate=True, chests=("opened",),
            )
            missing = deepcopy(result)
            missing["milestone_scan"]["static_or_locked_chest_keys"].pop()
            with self.assertRaises(ValueError):
                daily_rewards_next_due(missing, identity, self.now)
            overlapping = deepcopy(result)
            overlapping["milestone_scan"]["static_or_locked_chest_keys"].append(
                result["chests_collected"][0]["milestone_key"]
            )
            with self.assertRaises(ValueError):
                daily_rewards_next_due(overlapping, identity, self.now)

    def test_six_confirmed_chests_cannot_complete_one_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity, result = _fixture(
                self.now, Path(tmp) / "native-session",
                aggregate=False, chests=("opened",) * 6,
            )
            with self.assertRaises(ValueError):
                daily_rewards_next_due(result, identity, self.now)

    def test_aggregate_and_chest_transitions_require_distinct_successor_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity, result = _fixture(
                self.now,
                Path(tmp) / "native-session",
                aggregate=True,
                chests=("opened",),
            )
            aggregate = result["aggregate_claim"]
            aggregate["successor_frame_sha256"] = aggregate["source_frame_sha256"]
            with self.assertRaises(ValueError):
                daily_rewards_next_due(result, identity, self.now)

            aggregate["successor_frame_sha256"] = "c" * 64
            chest = result["chests_collected"][0]
            chest["successor_frame_sha256"] = chest["source_frame_sha256"]
            with self.assertRaises(ValueError):
                daily_rewards_next_due(result, identity, self.now)

    def test_static_no_work_evidence_requires_current_daily_and_complete_zero_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity, result = _fixture(
                self.now,
                Path(tmp) / "native-session",
                aggregate=False,
                no_work=True,
            )
            for mutation in (
                {"selected_daily": False},
                {"reset_id": "other-reset"},
                {"ordinary_claim_controls": 1},
                {"ready_chest_count": 1},
                {"static_or_locked_chest_keys": []},
                {"source_frame_sha256": "not-a-digest"},
            ):
                invalid = deepcopy(result)
                invalid["no_work_evidence"].update(mutation)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    daily_rewards_next_due(invalid, identity, self.now)

    def test_partial_unknown_and_failed_native_outcome_cannot_reuse_completed_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "native-session"
            identity, completed = _fixture(self.now, root, aggregate=True, chests=("opened",))
            unknown = deepcopy(completed)
            unknown.update(
                status="unresolved",
                effect_reconciliation_required=True,
                identical_retry_denied=True,
                committed_action_count=1,
                reward_claim_transport_calls=2,
                total_action_count=2,
            )
            native = _FakeNative(unknown)
            runner = self._runner(root.parent, native)
            with self.assertRaises(DailyRewardsRunnerError) as raised:
                runner(
                    identity,
                    self.previous_reset_id,
                    lambda: None,
                    runtime_input_lock=_HeldLock(),
                    occurrence_key=self.occurrence_key,
                )
            self.assertEqual(native.calls, 1)
            self.assertEqual(raised.exception.partial_result["status"], "unresolved")
            self.assertTrue(raised.exception.partial_result["identical_retry_denied"])

            failed_partial = deepcopy(completed)
            failed_partial.update(
                status="unresolved",
                effect_reconciliation_required=True,
                identical_retry_denied=True,
            )
            failed = _FakeNative(
                completed,
                failure="canonical owner teardown failed",
                partial_result=failed_partial,
            )
            with self.assertRaises(DailyRewardsRunnerError) as failed_result:
                self._runner(root.parent, failed)(
                    identity,
                    self.previous_reset_id,
                    lambda: None,
                    runtime_input_lock=_HeldLock(),
                    occurrence_key=self.occurrence_key,
                )
            self.assertEqual(failed_result.exception.partial_result["status"], "unresolved")
            self.assertTrue(failed_result.exception.partial_result["effect_reconciliation_required"])
            self.assertTrue(failed_result.exception.partial_result["identical_retry_denied"])

    def test_later_distinct_occurrence_in_same_reset_is_not_reset_scoped_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_root = Path(tmp) / "first"
            second_root = Path(tmp) / "second"
            identity, first = _fixture(self.now, first_root, aggregate=True, chests=())
            _identity2, second = _fixture(self.now, second_root, aggregate=True, chests=())
            first["chests_collected"] = [{
                "milestone_key": "daily-chest-30",
                "status": "confirmed",
                "reset_id": identity.reset_id,
                "target_identity": "activity-milestone-chest",
                "control_class": "MILESTONE_CHEST",
                "ready_state_proven": True,
                "free_only": True,
                "cost_type": "none",
                "successor_milestone_key": "daily-chest-30",
                "successor_state": "claimed",
                "source_frame_sha256": "1" * 64,
                "successor_frame_sha256": "2" * 64,
            }]
            first["milestone_scan"]["ready_chest_count"] = 1
            first["milestone_scan"]["ready_chest_keys"] = ["daily-chest-30"]
            first["total_action_count"] = first["reward_claim_transport_calls"] = first["committed_action_count"] = 2
            first["total_input_count"] = 4
            first["unclaimed_ready_chest_count"] = 0
            first["milestone_scan"]["static_or_locked_chest_keys"].remove("daily-chest-30")
            second["aggregate_claim"]["batch_identity"] = "batch-v1-" + "c" * 32
            first_native, second_native = _FakeNative(first), _FakeNative(second)
            first_runner = self._runner(Path(tmp), first_native)
            second_runner = self._runner(Path(tmp), second_native)
            first_result = first_runner(
                identity, self.previous_reset_id, lambda: None,
                runtime_input_lock=_HeldLock(), occurrence_key=self.occurrence_key,
            )
            second_result = second_runner(
                identity, self.previous_reset_id, lambda: None,
                runtime_input_lock=_HeldLock(), occurrence_key="occ:v1:" + "a" * 64,
            )
            self.assertEqual(first_result["reset_id"], second_result["reset_id"])
            self.assertEqual(first_native.calls, 1)
            self.assertEqual(second_native.calls, 1)
            self.assertNotEqual(
                first_result["aggregate_claim"]["batch_identity"],
                second_result["aggregate_claim"]["batch_identity"],
            )

    def test_runner_requires_service_lock_and_exact_native_input_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "native-session"
            identity, result = _fixture(
                self.now,
                root,
                aggregate=True,
                chests=("opened",),
            )
            wrong_lock = _HeldLock()
            wrong_lock.owner = "another-route"
            native = _FakeNative(result)
            with self.assertRaises(DailyRewardsRunnerError) as rejected:
                self._runner(root.parent, native)(
                    identity,
                    self.previous_reset_id,
                    lambda: None,
                    runtime_input_lock=wrong_lock,
                    occurrence_key=self.occurrence_key,
                )
            self.assertEqual(native.calls, 0)
            self.assertEqual(rejected.exception.partial_result["status"], "blocked")

            count = result["total_input_count"]
            for native in (
                _FakeNative(result, input_counts=(count, count + 1, count)),
                _FakeNative(result, accounting_verified=False),
            ):
                with self.subTest(native=native), self.assertRaises(
                    DailyRewardsRunnerError
                ) as accounting_failure:
                    self._runner(root.parent, native)(
                        identity,
                        self.previous_reset_id,
                        lambda: None,
                        runtime_input_lock=_HeldLock(),
                        occurrence_key=self.occurrence_key,
                    )
                self.assertEqual(native.calls, 1)
                self.assertFalse(
                    accounting_failure.exception.partial_result["accounting_verified"]
                )
                self.assertNotEqual(
                    accounting_failure.exception.partial_result["status"],
                    "completed",
                )


    def test_native_boundary_binding_identity_is_frozen(self):
        class WrongFlow(_FakeNative):
            flow_id = "OTHER-FLOW"

        with self.assertRaises(ValueError):
            self._runner(Path("sessions"), WrongFlow({}))


if __name__ == "__main__":
    unittest.main()
