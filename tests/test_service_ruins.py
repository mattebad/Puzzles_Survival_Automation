from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from itertools import count
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import time

import cv2

from scripts import navigation_development_boundary as development
from scripts import ruins_challenge_bluestacks as ruins_native
from scripts.bluestacks_flow_collector import ADBRunner
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime

from automation_service.recruitment import recruitment_reset
from automation_service.native_execution import NativeRouteOutcome
from automation_service.ruins import (
    MAX_ACTIONS,
    MAX_INPUTS,
    PROFILE_ID,
    PRODUCT_ID,
    PRODUCT_REVISION,
    RUINS_FLOW_ID,
    REOBSERVE_SECONDS,
    RuinsCanonicalActionBoundary,
    RuinsNativePartialResultError,
    RuinsRunner,
    ruins_next_due,
)
from safe_action_core import (
    ActionClass,
    ActionIntent,
    Observation,
    PolicyDecision,
    PolicyResult,
    SafetyStore,
    TransportResult,
)
from tasks.ruins_challenge import (
    RUINS_CHALLENGE_DISPATCH_ACTION,
    RUINS_CHALLENGE_RESULT_POSTCONDITION,
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    ruins_daily_action_key,
)
from tasks.runtime_identity import (
    derive_resource_runtime_identity,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class FakeRuntimeInputLock:
    owner = "ruins-service-test"
    invocation_id = "ruins-test-invocation"
    held = True

    def assert_held(self, owner: str, invocation_id: str) -> None:
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("wrong fake input lock identity")


class FakeNative:
    flow_id = RUINS_FLOW_ID
    product_id = PRODUCT_ID
    product_revision = PRODUCT_REVISION
    runtime_profile_id = PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, now: float, *, challenge_status: str, challenge_calls: int, claims=(), status="completed"):
        self.now = now
        self.challenge_status = challenge_status
        self.challenge_calls = challenge_calls
        self.claims = list(claims)
        self.status = status
        self.request = None

    def run(self, request):
        self.request = request
        request.checkpoint()
        request.runtime_input_lock.assert_held(
            request.runtime_input_lock.owner,
            request.runtime_input_lock.invocation_id,
        )
        request.validate_identity()
        identity = request.identity
        backend = request.arguments["runtime_identity"]
        chest_calls = len(self.claims)
        total = self.challenge_calls + chest_calls
        native = {
            "status": self.status,
            "reason": "replayed_fully_reconciled_route",
            "actions_completed": total,
            "ruins_dispatch_count": total,
            "challenge_transport_calls": self.challenge_calls,
            "chest_claim_transport_calls": chest_calls,
            "challenge_participation_confirmed": self.challenge_status == "finished" or (
                self.challenge_calls > 0 and self.challenge_status == "paused"
            ),
            "daily_action_ready": self.challenge_status == "finished" or (
                self.challenge_calls > 0 and self.challenge_status == "paused"
            ),
            "challenge_status": self.challenge_status,
            "challenge_stages": [
                {"identity": "Nova Challenge", "stage_cleared": 6 + ordinal,
                 "stage_maximum": 60,
                 "result": "failure" if self.challenge_status == "finished" and ordinal == self.challenge_calls - 1 else "success"}
                for ordinal in range(self.challenge_calls)
            ] if self.challenge_status != "unresolved" else [],
            "unresolved_action": self.challenge_status == "unresolved",
            "chest_status": "complete",
            "newly_claimed_chests": self.claims,
            "terminal_home_verified": True,
            "terminal_home_frame": {
                "frame_path": "frames/ruins-home.png",
                "frame_sha256": "a" * 64,
                "observed_utc": "2026-07-16T12:00:01Z",
                "capture_ordinal": 7,
            },
            "input_count": 4,
            "session_input_count": 4,
            "runtime_input_count": 4,
            "accounting_verified": True,
            "scheduler_reset_id": identity.reset_id,
            "backend_reset_id": backend.reset_id,
            "runtime_scope": backend.runtime_scope,
            "completed_at_utc": self.now + 1,
            "session_directory": "offline-session",
        }
        return NativeRouteOutcome(
            flow_id=request.flow_id,
            native_result=native,
            partial_result=None,
            failure=None,
            invocation_id=FakeRuntimeInputLock.invocation_id,
            session_directory="offline-session",
            startup_recovery=None,
            input_count=4,
            session_input_count=4,
            runtime_input_count=4,
            accounting_verified=True,
        )


class RuinsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        today = datetime(2026, 11, 8, tzinfo=timezone.utc)
        self.now = today.replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
        binding = resource_fixed_runtime_binding()
        self.identity = SchedulerIdentity(
            binding.account_id,
            binding.server_id,
            recruitment_reset(self.now),
            PRODUCT_ID,
        )
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_fake(self, native: FakeNative, *, utc_clock=None):
        runner = RuinsRunner(
            native,
            output_directory=self.root,
            utc_clock=utc_clock or (lambda: self.now),
            monotonic_clock=lambda: 10.0,
            settle_seconds=0,
        )
        return runner(
            self.identity,
            None,
            lambda: None,
            runtime_input_lock=FakeRuntimeInputLock(),
            occurrence_key="ruins-test-occurrence",
        )

    def test_loss_participation_and_independent_claims_count_every_dispatch(self):
        native = FakeNative(
            self.now,
            challenge_status="finished",
            challenge_calls=1,
            claims=[
                {"identity": "Hero Challenge"},
                {"identity": "Weapon Trial"},
            ],
        )
        result = self.run_fake(native)
        self.assertEqual(
            native.request.arguments["current_day"],
            WEEKDAYS[datetime.fromtimestamp(self.now, timezone.utc).weekday()],
        )
        self.assertEqual(native.request.identity.task_id, PRODUCT_ID)
        self.assertEqual(native.request.max_inputs, 48)
        self.assertEqual(native.request.max_actions, 13)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["challenge_participation_confirmed"])
        self.assertTrue(result["daily_action_ready"])
        self.assertEqual(result["challenge_stages"][-1]["result"], "failure")
        self.assertEqual(result["challenge_transport_calls"], 1)
        self.assertEqual(result["chest_claim_transport_calls"], 2)
        self.assertEqual(result["ruins_dispatch_count"], 3)
        self.assertEqual(result["action_count"], 3)
        self.assertTrue(result["terminal_home_verified"])

    def test_unavailable_challenge_does_not_suppress_ready_chest_or_repeat_due(self):
        native = FakeNative(
            self.now,
            challenge_status="unavailable",
            challenge_calls=0,
            claims=[{"identity": "Tech Challenge"}],
        )
        result = self.run_fake(native)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["challenge_participation_confirmed"])
        self.assertFalse(result["daily_action_ready"])
        self.assertEqual(result["challenge_transport_calls"], 0)
        self.assertEqual(result["chest_claim_transport_calls"], 1)
        self.assertEqual(result["ruins_dispatch_count"], 1)
        self.assertEqual(result["newly_claimed_chests"], [{"identity": "Tech Challenge"}])
        self.assertGreater(result["next_due_at_utc"], result["completed_at_utc"] + REOBSERVE_SECONDS)

    def test_multiple_stages_count_separately_and_budget_pause_is_resumable(self):
        finished = self.run_fake(FakeNative(
            self.now, challenge_status="finished", challenge_calls=3,
            claims=[{"identity": "Hero Challenge"}],
        ))
        self.assertEqual(finished["ruins_dispatch_count"], 4)
        self.assertEqual([stage["result"] for stage in finished["challenge_stages"]],
                         ["success", "success", "failure"])
        self.assertGreater(finished["next_due_at_utc"], finished["completed_at_utc"] + REOBSERVE_SECONDS)
        paused = self.run_fake(FakeNative(
            self.now, challenge_status="paused", challenge_calls=2, status="unresolved",
        ))
        self.assertEqual(paused["next_due_at_utc"], paused["completed_at_utc"] + REOBSERVE_SECONDS)
        self.assertFalse(paused["effect_reconciliation_required"])
        self.assertFalse(paused["identical_retry_denied"])

    def test_unknown_effect_reobserves_and_is_never_reported_as_done(self):
        native = FakeNative(
            self.now,
            challenge_status="unresolved",
            challenge_calls=1,
            status="unresolved",
        )
        result = self.run_fake(native)
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(result["ruins_dispatch_count"], 1)
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["next_due_at_utc"], result["completed_at_utc"] + REOBSERVE_SECONDS)

    def test_clock_progress_preserves_the_original_authorized_reset_window(self):
        clock = count(self.now, 0.25)
        native = FakeNative(self.now, challenge_status="unavailable", challenge_calls=0)
        result = self.run_fake(native, utc_clock=lambda: next(clock))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["terminal_home_verified"])
        self.assertEqual(result["ruins_dispatch_count"], 0)
        self.assertGreater(result["next_due_at_utc"], result["completed_at_utc"])

    def test_clock_progress_cannot_renew_expired_original_authority(self):
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(),
            datetime.fromtimestamp(self.now, timezone.utc),
        )
        assert backend.expires_utc is not None
        expired_at = datetime.fromisoformat(
            backend.expires_utc.replace("Z", "+00:00")
        ).timestamp() + 0.25
        clock = iter((self.now, expired_at))
        native = FakeNative(self.now, challenge_status="unavailable", challenge_calls=0)
        with self.assertRaises(ValueError):
            self.run_fake(native, utc_clock=lambda: next(clock))
        self.assertIsNone(native.request)

    def test_adapter_rejects_scheduler_task_alias_and_wrong_reset(self):
        native = FakeNative(self.now, challenge_status="unavailable", challenge_calls=0)
        runner = RuinsRunner(native, output_directory=self.root, utc_clock=lambda: self.now)
        wrong_task = SchedulerIdentity("test-account", "test-server", self.identity.reset_id, RUINS_FLOW_ID)
        with self.assertRaises(ValueError):
            runner(wrong_task, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(), occurrence_key="wrong-task")
        wrong_reset = SchedulerIdentity("test-account", "test-server", "game-day-1900-01-01", PRODUCT_ID)
        with self.assertRaises(ValueError):
            runner(wrong_reset, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(), occurrence_key="wrong-reset")
        self.assertIsNone(native.request)

    def test_adapter_rejects_unverified_accounting_and_wrong_native_flow(self):
        class BadNative(FakeNative):
            def run(self, request):
                outcome = super().run(request)
                return NativeRouteOutcome(
                    flow_id="wrong-flow",
                    native_result=outcome.native_result,
                    partial_result=None,
                    failure=None,
                    invocation_id=outcome.invocation_id,
                    session_directory=outcome.session_directory,
                    startup_recovery=None,
                    input_count=outcome.input_count,
                    session_input_count=outcome.session_input_count,
                    runtime_input_count=outcome.runtime_input_count,
                    accounting_verified=True,
                )

        bad = BadNative(self.now, challenge_status="unavailable", challenge_calls=0)
        with self.assertRaises(RuinsNativePartialResultError):
            self.run_fake(bad)
        bad_accounting = FakeNative(self.now, challenge_status="unavailable", challenge_calls=0)
        bad_accounting.run = lambda request: NativeRouteOutcome(
            flow_id=request.flow_id,
            native_result={},
            partial_result={},
            failure=None,
            invocation_id="bad",
            session_directory="offline-session",
            startup_recovery=None,
            input_count=MAX_INPUTS + 1,
            session_input_count=MAX_INPUTS + 1,
            runtime_input_count=MAX_INPUTS + 1,
            accounting_verified=True,
        )
        with self.assertRaises(RuinsNativePartialResultError):
            self.run_fake(bad_accounting)

    def test_due_rejects_wrong_identity_or_missing_home(self):
        result = {
            "flow_id": RUINS_FLOW_ID,
            "product_id": PRODUCT_ID,
            "product_revision": PRODUCT_REVISION,
            "task_id": PRODUCT_ID,
            "account_id": self.identity.account_id,
            "server_id": self.identity.server_id,
            "reset_id": self.identity.reset_id,
            "completed_at_utc": self.now + 1,
            "terminal_home_verified": True,
            "accounting_verified": True,
            "status": "completed",
            "challenge_participation_confirmed": True,
            "challenge_status": "finished",
            "chest_status": "complete",
        }
        self.assertGreater(ruins_next_due(result, self.identity, self.now), self.now)
        with self.assertRaises(ValueError):
            ruins_next_due({**result, "terminal_home_verified": False}, self.identity, self.now)
        wrong = SchedulerIdentity("other", self.identity.server_id, self.identity.reset_id, PRODUCT_ID)
        with self.assertRaises(ValueError):
            ruins_next_due(result, wrong, self.now)

    def test_action_keys_and_unknown_safety_row_survive_restart_without_json_authority(self):
        reset_id = self.identity.reset_id
        challenge_key = ruins_daily_action_key(
            flow_id=RUINS_FLOW_ID,
            runtime_scope="bluestacks:test-instance",
            account_id=self.identity.account_id,
            server_id=self.identity.server_id,
            reset_identity=reset_id,
            current_day="Thu",
            category="challenge",
        )
        chest_key = ruins_daily_action_key(
            flow_id=RUINS_FLOW_ID,
            runtime_scope="bluestacks:test-instance",
            account_id=self.identity.account_id,
            server_id=self.identity.server_id,
            reset_identity=reset_id,
            current_day="Thu",
            category="chest:hero-challenge",
        )
        self.assertNotEqual(challenge_key, chest_key)
        database = self.root / "canonical.sqlite3"
        store = SafetyStore(database)
        store.acquire_lease("ruins-service-test", 1000.0, 600.0)
        profile = PROFILE_ID
        postcondition = RUINS_CHALLENGE_RESULT_POSTCONDITION
        observation = Observation(
            frame_sha256="b" * 64,
            capture_completed_monotonic=1.0,
            runtime_profile_id=profile,
            width=800,
            height=1280,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state="RUINS_CHALLENGE_DETAIL",
            overlay_state="none_observed",
            target_identity="ruins-dispatch",
            target_roi=(250, 1120, 550, 1230),
            consequence="ruins_zero_cost_npc_challenge",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition=postcondition,
            evidence_refs=("dispatch-before.png",),
        )
        action_id = "ruins-unknown-action"
        semantic_action = RUINS_CHALLENGE_DISPATCH_ACTION
        intent = ActionIntent(
            action_id=action_id,
            action_key=challenge_key,
            task_id=PRODUCT_ID,
            semantic_action=semantic_action,
            source_state="RUINS_CHALLENGE_DETAIL",
            target_identity="ruins-dispatch",
            target_roi=observation.target_roi,
            source_frame_sha256=observation.frame_sha256,
            source_frame_captured_at=1.0,
            runtime_profile_id=profile,
            game_day_id=reset_id,
            expected_postcondition=postcondition,
            consequence="ruins_zero_cost_npc_challenge",
            cost_type="none",
            cost_amount=0,
            quantity=1,
            evidence_refs=("dispatch-before.png",),
            consequential=True,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        )
        policy = PolicyResult(PolicyDecision.AUTHORIZE, "AUTHORIZED", "", 1000.0, {})
        store.prepare_action(intent, policy, 1000.0)
        store.mark_input_sent(action_id, 1000.1, TransportResult(True, "RUINS_DISPATCHED"))
        store.mark_unresolved(action_id, 1000.2, "result_not_observed")
        stage_keys = []
        for ordinal, outcome in enumerate(("success", "failure")):
            stage_key = ruins_daily_action_key(
                flow_id=RUINS_FLOW_ID, runtime_scope="bluestacks:test-instance",
                account_id=self.identity.account_id, server_id=self.identity.server_id,
                reset_identity=reset_id, current_day="Thu",
                category=f"challenge:nova-challenge:{18 + ordinal}:100",
            )
            stage_keys.append(stage_key)
            stage_intent = replace(intent, action_id=f"stage-{ordinal}", action_key=stage_key)
            store.prepare_action(stage_intent, policy, 1000.0)
            store.mark_input_sent(stage_intent.action_id, 1000.1, TransportResult(True, "RUINS_DISPATCHED"))
            store.audit(PRODUCT_ID, "ruins_stage_result", 1000.2, {
                "account_id": self.identity.account_id,
                "server_id": self.identity.server_id,
                "runtime_scope": "bluestacks:test-instance",
                "reset_id": reset_id,
                "result": outcome,
                "frame_sha256": "c" * 64,
            }, stage_intent.action_id)
            store.mark_confirmed(stage_intent.action_id, 1000.3, {
                "confirmed": True, "frame_sha256": "c" * 64,
            })
        cancelled = replace(intent, action_id="never-sent", action_key="never-sent-stage")
        store.prepare_action(cancelled, policy, 1000.0)
        store.mark_cancelled(cancelled.action_id, 1000.1, "pre_input_revalidation:not_available")
        self.assertEqual(len(set(stage_keys + [challenge_key, chest_key])), 4)
        store.close()

        history = self.root / "ruins-chest-history.json"
        history.write_text(json.dumps({"claims": [{"identity": "Hero Challenge", "status": "confirmed"}]}), encoding="utf-8")
        reopened = SafetyStore(database)
        try:
            context = SimpleNamespace(
                action_store=reopened,
                session=SimpleNamespace(owner="ruins-service-test"),
                runtime=SimpleNamespace(session="offline-session"),
                invocation_id="restarted-invocation",
            )
            boundary = RuinsCanonicalActionBoundary(
                context,
                self.identity,
                SimpleNamespace(runtime_scope="bluestacks:test-instance"),
                lambda: None,
                monotonic_clock=lambda: 2.0,
                utc_clock=lambda: 1001.0,
                settle_seconds=0,
            )
            spec = {
                "action_key": challenge_key,
                "semantic_action": semantic_action,
                "category": "challenge",
                "game_day_id": reset_id,
                "source_state": "RUINS_CHALLENGE_DETAIL",
                "target_identity": "ruins-dispatch",
                "expected_postcondition": postcondition,
                "consequence": "ruins_zero_cost_npc_challenge",
            }
            self.assertEqual(reopened.get_action_by_key(challenge_key)["game_day_id"], reset_id)
            self.assertEqual(reopened.get_action_by_key(challenge_key)["task_id"], PRODUCT_ID)
            self.assertEqual(boundary.status(spec)["status"], "unknown")
            no_dispatch = lambda *_args, **_kwargs: self.fail("UNKNOWN must never retry")
            result = boundary.execute(
                spec=spec,
                proposal_capture=None,
                proposal_observation=observation,
                capture=no_dispatch,
                observe=no_dispatch,
                dispatch=no_dispatch,
                successor=no_dispatch,
                settle_seconds=0,
            )
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["transport_calls"], 0)
            self.assertEqual(boundary.reset_progress(challenge_key), {
                "stages_confirmed": 2, "stages_won": 1, "finished": True, "unresolved": True,
            })
            self.assertEqual(boundary.status({**spec, "action_key": "never-sent-stage"})["status"], "new")
            self.assertEqual(reopened.get_action_by_key(challenge_key)["final_status"], "unresolved")
            self.assertEqual([reopened.get_action_by_key(key)["final_status"] for key in stage_keys],
                             ["confirmed", "confirmed"])
        finally:
            reopened.close()


class RuinsSingleInputOwnerTests(unittest.TestCase):
    """Real session, native journal and SQLite Core; only the ADB device is offline."""

    def _visit(self, *, fail_last_transport=False):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(development, "RUNTIME_INPUT_LOCK_PATH", root / "input.sqlite3"))
        home = cv2.imread(str(Path(__file__).parent / "fixtures/home_base/native-home-20261029.png"))
        self.assertIsNotNone(home)

        class Device(ADBRunner):
            def __init__(self):
                super().__init__("offline-adb", "offline")
                self.physical_inputs = 0

            def run(self, *args, **kwargs):
                raise AssertionError("offline fixture must never execute ADB")

            def capture_png(self):
                frame = home.copy()
                frame[0, 0] = (self.physical_inputs, 17, 23)
                ok, payload = cv2.imencode(".png", frame)
                if not ok:
                    raise AssertionError("fixture PNG encoding failed")
                return payload.tobytes()

            def get_state(self):
                return "device"

            def shell_text(self, *args, **kwargs):
                return "mCurrentFocus=Window{1 u0 com.global.ztmslg/com.unity3d.player.UnityPlayerActivity}"

            def dispatch_tap(self, point):
                self.physical_inputs += 1
                if fail_last_transport and self.physical_inputs == 9:
                    raise RuntimeError("offline transport failure after ninth input")

        device = Device()
        runtime = LocalBlueStacksRuntime(device, root / "runtime", execute=True)
        runtime.max_inputs = MAX_INPUTS
        session = self.enterContext(development.DevelopmentSession(
            owner="ruins-single-owner", invocation_id="offline-mixed-visit",
            session_directory=root / "session", max_inputs=MAX_INPUTS,
        ))
        now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        backend = derive_resource_runtime_identity(resource_fixed_runtime_binding(), now)
        identity = SchedulerIdentity(backend.account_id, backend.server_id, recruitment_reset(now.timestamp()), PRODUCT_ID)
        store = SafetyStore(root / "actions.sqlite3")
        self.addCleanup(store.close)
        store.acquire_lease(session.owner, now.timestamp(), 600.0)
        context = SimpleNamespace(
            session=session, runtime=runtime, action_store=store, invocation_id=session.invocation_id,
        )
        boundary = RuinsCanonicalActionBoundary(
            context, identity, backend, lambda: None,
            monotonic_clock=time.monotonic, utc_clock=lambda: now.timestamp(), settle_seconds=0,
        )
        route = ruins_native.RuinsIntegratedRoute(
            runtime, session=session, reset_identity=identity.reset_id, current_day="Mon",
            account_id=identity.account_id, server_id=identity.server_id,
            runtime_scope=backend.runtime_scope, product_id=PRODUCT_ID, product_revision=PRODUCT_REVISION,
            runtime_identity=backend, action_executor=boundary, post_input_delay=0,
        )
        # Navigation uses the actual route transport wrapper, not a counter shim.
        def navigation(ordinal):
            source = runtime.capture(f"navigation-source-{ordinal}")
            route._ordinary_tap(
                source, target_identity="ruins-attack", target_roi=(250, 900, 550, 1000),
                action_key=f"navigation-{ordinal}",
            )

        for ordinal in range(5):
            navigation(ordinal)
        row = RuinsChallengeRow(
            identity="Hero Challenge", day_label="Mon",
            availability=RuinsAvailability.AVAILABLE,
            progress_current=60, progress_maximum=120, last_successful_level=60,
            challenge_control=RuinsControlState.VISIBLE_ENABLED,
            chest_state=RuinsChestState.UNKNOWN,
            source_frame_sha256=runtime.capture("challenge-row-source").sha256,
            reset_identity=identity.reset_id,
        )
        key = route._challenge_key(row)
        spec = {
            "action_key": key, "semantic_action": RUINS_CHALLENGE_DISPATCH_ACTION,
            "action_kind": RUINS_CHALLENGE_DISPATCH_ACTION, "category": "challenge",
            "subject": "ruins_challenge:hero-challenge", "identity": row.identity,
            "source_state": "RUINS_CHALLENGE_DETAIL", "target_identity": "ruins-dispatch",
            "control_class": "DISPATCH", "consequence": "ruins_zero_cost_npc_challenge",
            "expected_postcondition": RUINS_CHALLENGE_RESULT_POSTCONDITION,
            "semantic_preconditions": route._challenge_preconditions(row, None),
            "game_day_id": identity.reset_id,
        }

        def observe(frame):
            return route._policy_observation(
                frame, source_state=spec["source_state"], target_identity=spec["target_identity"],
                target_roi=(250, 1120, 550, 1230), control_class="DISPATCH",
                consequence=spec["consequence"], postcondition=spec["expected_postcondition"],
            )

        def dispatch(frame, observation):
            route._ordinary_tap(
                frame, target_identity="ruins-dispatch", target_roi=observation.target_roi,
                action_key=key, consequential=True,
            )

        def successor(frame):
            # The offline device changes the PNG only on a physical dispatch.
            if int(frame.frame[0, 0, 0]) == 6:
                spec["result"] = "failure"
                return RUINS_CHALLENGE_RESULT_POSTCONDITION
            return "unknown"

        proposal = runtime.capture("dispatch-proposal")
        result = boundary.execute(
            spec=spec, proposal_capture=proposal, proposal_observation=observe(proposal),
            capture=runtime.capture, observe=observe, dispatch=dispatch, successor=successor, settle_seconds=0,
        )
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["transport_calls"], 1)
        self.assertEqual(store.get_action_by_key(key)["final_status"], "confirmed")
        self.assertEqual(boundary.reset_progress(route._action_key("challenge")), {
            "stages_confirmed": 1, "stages_won": 0, "finished": True, "unresolved": False,
        })
        for ordinal in (6, 7):
            navigation(ordinal)
        if fail_last_transport:
            with self.assertRaisesRegex(RuntimeError, "ninth input"):
                navigation(8)
        else:
            navigation(8)
        self.assertEqual((session.input_count, runtime.input_count, device.physical_inputs), (9, 9, 9))
        self.assertEqual(ruins_native.verify_ruins_route_transports(context), 9)
        rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines()]
        dispatches = [row for row in rows if row["type"] == "dispatch"]
        self.assertEqual(len(dispatches), 9)
        self.assertEqual(sum(row["consequential"] for row in dispatches), 1)
        self.assertEqual(sum(row["action_key"] == key for row in dispatches), 1)
        self.assertEqual(boundary.transport_calls_by_category, {"challenge": 1, "chest": 0})
        # A duplicate confirmed Core key cannot cause a tenth physical input.
        again = boundary.execute(
            spec=spec, proposal_capture=None, proposal_observation=observe(proposal),
            capture=lambda _label: self.fail("confirmed stage must not recapture"),
            observe=observe, dispatch=dispatch, successor=successor, settle_seconds=0,
        )
        self.assertEqual((again["status"], again["transport_calls"], device.physical_inputs), ("confirmed", 0, 9))
        if not fail_last_transport:
            self.assertEqual(len(session.actions), 9)
        return context

    def test_mixed_navigation_and_canonical_dispatch_share_nine_real_inputs(self):
        self._visit()

    def test_failed_navigation_transport_retains_all_nine_owned_inputs(self):
        self._visit(fail_last_transport=True)

    def test_native_journal_crosscheck_rejects_missing_dispatch_without_adoption(self):
        context = self._visit()
        rows = context.runtime.events.read_text(encoding="utf-8").splitlines()
        removed = False
        kept = []
        for line in rows:
            if not removed and json.loads(line)["type"] == "dispatch":
                removed = True
            else:
                kept.append(line)
        context.runtime.events.write_text("\n".join(kept) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "retained dispatch journal") as caught:
            ruins_native.verify_ruins_route_transports(context)
        self.assertEqual((context.session.input_count, context.runtime.input_count), (9, 9))
        self.assertFalse(caught.exception.partial_result["accounting_verified"])
        self.assertFalse(caught.exception.partial_result["journal_verified"])


if __name__ == "__main__":
    unittest.main()
