from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from tasks.alliance_help import (
    CONSEQUENCE, DAILY_REQUEST_LIMIT, INDIVIDUAL_TARGET_IDENTITY,
    POSTCONDITION, SEMANTIC_ACTION, SOURCE_STATE, alliance_help_action_key,
)

from automation_service import registry
from automation_service.alliance_help import (
    AllianceHelpExecutionHandler, AllianceHelpRunner, FLOW_ID, MAX_ACTIONS,
    MAX_INPUTS, alliance_help_next_due, normalize_alliance_help_result,
)
from automation_service.contracts import NormalizedOutcome
from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from automation_service.registry import (
    ALLIANCE_HELP_FLOW_ID, ALLIANCE_HELP_HANDLER_ID, ALLIANCE_HELP_PRODUCT_ID,
    ALLIANCE_HELP_PRODUCT_REVISION, ALLIANCE_HELP_PROFILE_ID,
    RegisteredDispatchSnapshot,
)
from automation_service.recruitment import recruitment_reset


START = 1_800_000_000.0


class FakeRuntimeInputLock:
    owner = "automation-service"
    invocation_id = "alliance-help-service-test"
    held = True

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("Alliance Help runtime lock identity changed")


class FakeNativeBoundary:
    flow_id = ALLIANCE_HELP_FLOW_ID
    product_id = ALLIANCE_HELP_PRODUCT_ID
    product_revision = ALLIANCE_HELP_PRODUCT_REVISION
    runtime_profile_id = ALLIANCE_HELP_PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, native_result, session_directory: Path):
        self.native_result = native_result
        self.session_directory = session_directory
        self.request = None

    def run(self, request: NativeRouteRequest):
        self.request = request
        return NativeRouteOutcome(
            flow_id=FLOW_ID, native_result=self.native_result, partial_result=None,
            failure=None, invocation_id=FakeRuntimeInputLock.invocation_id,
            session_directory=str(self.session_directory), startup_recovery=None,
            input_count=4, session_input_count=4, runtime_input_count=4,
            accounting_verified=True,
        )


class AllianceHelpServiceAdapterTests(unittest.TestCase):
    def _identity(self, now: float = START):
        backend = derive_resource_runtime_identity(resource_fixed_runtime_binding(),
            datetime.fromtimestamp(now, timezone.utc))
        identity = SchedulerIdentity(backend.account_id, backend.server_id,
            recruitment_reset(now), ALLIANCE_HELP_PRODUCT_ID)
        return backend, identity, now

    @staticmethod
    def _write_frame(session: Path, name: str) -> tuple[str, str]:
        path = session / f"{name}.png"
        payload = f"synthetic-labeled-alliance-help-evidence:{name}".encode("ascii")
        path.write_bytes(payload)
        return str(path), hashlib.sha256(payload).hexdigest()

    def _native_result(self, session: Path, backend, *, status="complete_for_reset",
                       count=10, calls=10, partial_no_work=False):
        session.mkdir(parents=True, exist_ok=True)
        source_path, source_sha = self._write_frame(session, "source")
        home_path, home_sha = self._write_frame(session, "terminal-home")
        proof = {
            "runtime_scope": backend.runtime_scope,
            "account_id": backend.account_id,
            "server_id": backend.server_id,
            "reset_id": backend.reset_id,
            "assurance": backend.assurance.value,
            "evidence_refs": list(backend.evidence_refs),
            "observed_utc": backend.observed_utc,
            "expires_utc": backend.expires_utc,
            "runtime_binding_digest": backend.runtime_binding_digest,
            "reset_start_utc": backend.reset_start_utc,
            "reset_deadline_utc": backend.reset_deadline_utc,
        }
        records = []
        actions = []
        dispatches = []
        for ordinal in range(1, count + 1):
            key = alliance_help_action_key(runtime_scope=backend.runtime_scope,
                account_id=backend.account_id, server_id=backend.server_id,
                reset_id=backend.reset_id, ordinal=ordinal)
            records.append({
                "action_id": f"synthetic-action-{ordinal}", "action_key": key,
                "request_ordinal": ordinal, "task_id": FLOW_ID,
                "semantic_action": SEMANTIC_ACTION, "source_state": SOURCE_STATE,
                "target_identity": INDIVIDUAL_TARGET_IDENTITY,
                "game_day_id": backend.reset_id,
                "expected_postcondition": POSTCONDITION, "consequence": CONSEQUENCE,
                "cost_type": "none", "cost_amount": 0, "quantity": 1,
                "consequential": 1, "final_status": "confirmed",
            })
        for ordinal in range(1, calls + 1):
            key = alliance_help_action_key(runtime_scope=backend.runtime_scope,
                account_id=backend.account_id, server_id=backend.server_id,
                reset_id=backend.reset_id, ordinal=ordinal)
            immediate_path, immediate_sha = self._write_frame(session, f"immediate-{ordinal}")
            success_path, success_sha = self._write_frame(session, f"success-{ordinal}")
            stable_path, stable_sha = self._write_frame(session, f"stable-{ordinal}")
            selected_sha = hashlib.sha256(f"selected-request-{ordinal}".encode()).hexdigest()
            before_balance = (ordinal - 1) * 1000
            result_evidence = [
                {"frame_path": success_path, "frame_sha256": success_sha,
                 "selected_request_absent": True, "screen_state": SOURCE_STATE,
                 "source_fresh": True, "overlay_clear": True,
                 "success_message": True, "daily_alliance_coin_balance": ordinal * 1000,
                 "daily_alliance_coin_limit": 50000},
                {"frame_path": stable_path, "frame_sha256": stable_sha,
                 "selected_request_absent": True, "screen_state": SOURCE_STATE,
                 "source_fresh": True, "overlay_clear": True,
                 "success_message": False, "daily_alliance_coin_balance": ordinal * 1000,
                 "daily_alliance_coin_limit": 50000},
            ]
            actions.append({
                "status": "confirmed", "request_ordinal": ordinal, "action_key": key,
                "journal_status": "confirmed", "verified_request_count": 1,
                "help_transport_calls": 1, "effect_reconciliation_required": False,
                "selected_request_sha256": selected_sha,
                "immediate_before_frame": immediate_path,
                "immediate_before_sha256": immediate_sha,
                "proposal_frame": source_path, "proposal_sha256": source_sha,
                "immediate_daily_alliance_coin_balance": before_balance,
                "immediate_daily_alliance_coin_limit": 50000,
                "request_result_frames": [success_path, stable_path],
                "request_result_evidence": result_evidence,
            })
            dispatches.append({"immediate_before_sha256": immediate_sha,
                "target_identity": INDIVIDUAL_TARGET_IDENTITY, "action_key": key})
        no_work_evidence = None
        reason = "ten_confirmed_free_help_requests_reached"
        no_work = False
        if partial_no_work:
            reason = "exact_no_requests_message"
            no_work = True
            no_work_path, no_work_sha = self._write_frame(session, "no-work")
            no_work_evidence = {
                "screen_state": SOURCE_STATE, "source_fresh": True,
                "overlay_clear": True, "exact_no_requests_message": True,
                "free_request_controls": 0, "cost_marker_seen": False,
                "frame_path": no_work_path, "frame_sha256": no_work_sha,
            }
        return {
            "status": status, "reason": reason,
            "flow_id": FLOW_ID, "product_id": ALLIANCE_HELP_PRODUCT_ID,
            "product_revision": ALLIANCE_HELP_PRODUCT_REVISION,
            "task_id": ALLIANCE_HELP_PRODUCT_ID,
            "account_id": backend.account_id, "server_id": backend.server_id,
            "scheduler_reset_id": recruitment_reset(START),
            "reset_id": backend.reset_id, "backend_reset_id": backend.reset_id,
            "occurrence_key": "native-occurrence",
            "backend_identity": proof,
            "source_frame": {"frame_path": source_path, "frame_sha256": source_sha},
            "terminal_home_frame": {"frame_path": home_path, "frame_sha256": home_sha},
            "terminal_home_verified": True,
            "accounting_verified": True,
            "effect_reconciliation_required": False,
            "identical_retry_denied": False,
            "no_work": no_work, "no_work_evidence": no_work_evidence,
            "confirmed_request_count": count,
            "confirmed_request_records": records,
            "committed_action_count": count, "verified_request_count": count,
            "help_transport_calls": calls,
            "help_dispatch_evidence": dispatches,
            "request_actions": actions,
        }

    def _runner(self, directory: Path, native, identity, now):
        return AllianceHelpRunner(native=native, output_directory=directory,
            utc_clock=lambda: now, monotonic_clock=lambda: 50.0, settle_seconds=0.0)

    def _execute(self, runner, identity, *, previous_reset_id="prior-reset", occurrence="occ:alliance-help:1"):
        checks = []
        result = runner(identity, previous_reset_id, lambda: checks.append("checkpoint"),
            runtime_input_lock=FakeRuntimeInputLock(), occurrence_key=occurrence)
        return result, checks

    def test_runner_passes_exact_identity_budget_and_previous_reset_to_native_boundary(self):
        backend, identity, now = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = FakeNativeBoundary(self._native_result(root / "session", backend), root / "session")
            runner = self._runner(root / "output", native, identity, now)
            result, checks = self._execute(runner, identity, previous_reset_id="game-day-2027-01-14")
            request = native.request
        self.assertIsInstance(request, NativeRouteRequest)
        self.assertEqual(request.flow_id, ALLIANCE_HELP_FLOW_ID)
        self.assertEqual(request.product_id, ALLIANCE_HELP_PRODUCT_ID)
        self.assertEqual(request.product_revision, ALLIANCE_HELP_PRODUCT_REVISION)
        self.assertEqual(request.runtime_profile_id, ALLIANCE_HELP_PROFILE_ID)
        self.assertEqual(request.previous_reset_id, "game-day-2027-01-14")
        self.assertEqual(request.occurrence_key, "occ:alliance-help:1")
        self.assertEqual((request.max_inputs, request.max_actions), (MAX_INPUTS, DAILY_REQUEST_LIMIT))
        self.assertEqual(dict(request.arguments), {})
        self.assertIsInstance(result, dict)
        self.assertTrue(result["native_execution_verified"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["remaining_request_target"], 0)
        self.assertGreaterEqual(len(checks), 1)
        request.validate_identity()

    def test_complete_ten_and_restarted_partial_results_normalize_with_remaining_target(self):
        backend, identity, now = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete_native = FakeNativeBoundary(
                self._native_result(root / "complete-session", backend), root / "complete-session")
            complete, _checks = self._execute(self._runner(root / "complete-output", complete_native,
                identity, now), identity)
            self.assertEqual(alliance_help_next_due(complete, identity, now),
                datetime.fromisoformat(backend.reset_deadline_utc.replace("Z", "+00:00")).timestamp())
            normalized = normalize_alliance_help_result(complete, identity, now)
            self.assertEqual(normalized.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
            self.assertEqual(normalized.action_count, 10)
            self.assertEqual(normalized.observed_progress["confirmed_request_count"], 10)
            self.assertEqual(normalized.observed_progress["remaining_request_target"], 0)
            self.assertEqual(normalized.consequence["help_transport_calls"], 10)

            partial_native = FakeNativeBoundary(self._native_result(
                root / "partial-session", backend, status="deferred", count=3, calls=0,
                partial_no_work=True), root / "partial-session")
            partial, _checks = self._execute(self._runner(root / "partial-output", partial_native,
                identity, now), identity, occurrence="occ:alliance-help:2")
            self.assertEqual(alliance_help_next_due(partial, identity, now), now + 300)
            deferred = normalize_alliance_help_result(partial, identity, now)
            self.assertEqual(deferred.outcome, NormalizedOutcome.DEFERRED)
            self.assertEqual(deferred.action_count, 0)
            self.assertEqual(deferred.observed_progress["confirmed_request_count"], 3)
            self.assertEqual(deferred.observed_progress["remaining_request_target"], 7)
            self.assertEqual(deferred.consequence["committed_action_count"], 3)

    def test_transport_without_bound_success_result_and_corrupt_restart_prefix_rejected(self):
        backend, identity, now = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = FakeNativeBoundary(self._native_result(root / "session", backend), root / "session")
            result, _checks = self._execute(self._runner(root / "output", native, identity, now), identity)
            action = result["request_actions"][0]
            action["request_result_evidence"] = [
                {**frame, "success_message": False} for frame in action["request_result_evidence"]]
            with self.assertRaisesRegex(ValueError, "success toast"):
                alliance_help_next_due(result, identity, now)

            result["request_actions"] = result["request_actions"][:-1]
            with self.assertRaisesRegex(ValueError, "transport evidence"):
                alliance_help_next_due(result, identity, now)

    def test_unknown_transport_requires_reconciliation_and_never_returns_due(self):
        _backend, identity, now = self._identity()
        unresolved = normalize_alliance_help_result({
            "status": "reconciliation_required", "help_transport_calls": 1,
            "effect_reconciliation_required": True, "confirmed_request_count": 2,
        }, identity, now)
        self.assertEqual(unresolved.outcome, NormalizedOutcome.RECONCILIATION_REQUIRED)
        self.assertTrue(unresolved.unresolved_action)
        self.assertIsNone(unresolved.next_eligible_at)

    def test_stale_reset_and_unavailable_native_binding_fail_closed(self):
        backend, identity, now = self._identity()
        stale = SchedulerIdentity(identity.account_id, identity.server_id,
            "game-day-2023-11-13", identity.task_id)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = FakeNativeBoundary({}, root / "session")
            stale_runner = self._runner(root / "stale", native, stale, now)
            with self.assertRaisesRegex(ValueError, "scheduler reset identity is not current"):
                self._execute(stale_runner, stale)
            self.assertIsNone(native.request)
            missing = AllianceHelpRunner(output_directory=root / "missing", native=None,
                utc_clock=lambda: now)
            raw, _checks = self._execute(missing, identity)
        self.assertEqual(raw["status"], "blocked")
        self.assertFalse(raw["native_execution_verified"])
        self.assertEqual(raw["remaining_request_target"], DAILY_REQUEST_LIMIT)

    def test_handler_owns_canonical_route_and_fixed_ten_request_budget(self):
        registration = {
            "flow_id": ALLIANCE_HELP_FLOW_ID,
            "product_id": ALLIANCE_HELP_PRODUCT_ID,
            "product_revision": ALLIANCE_HELP_PRODUCT_REVISION,
            "production_handler": ALLIANCE_HELP_HANDLER_ID,
            "profile": ALLIANCE_HELP_PROFILE_ID,
            "mode": registry.ALLIANCE_HELP_PHASE_MODE,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
        }
        snapshot = RegisteredDispatchSnapshot(**registration)
        handler = AllianceHelpExecutionHandler(snapshot, lambda run, _facts: run)
        self.assertFalse(handler.selection_only)
        self.assertEqual((handler.max_inputs, handler.max_actions), (MAX_INPUTS, DAILY_REQUEST_LIMIT))
        self.assertEqual(handler.plan(None).outcome, NormalizedOutcome.BLOCKED)
        self.assertEqual(handler.summarize()["flow_id"], ALLIANCE_HELP_FLOW_ID)


if __name__ == "__main__":
    unittest.main()
