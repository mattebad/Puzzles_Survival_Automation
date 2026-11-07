"""Shared 10054 recovery on the caller's real runtime, canonical state and Core journal."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from automation_service.contracts import FlowSpec
from automation_service.state import (
    BotStateManager, NetworkRecoveryStatus, NetworkRecoveryTransportStatus,
)
from safe_action_core.models import (
    ActionClass, Observation, PolicyDecision, PolicyRequest, PolicyResult, TransportResult,
)
from safe_action_core.policy import CentralPolicy
from safe_action_core.store import SafetyStore
from scripts import bluestacks_popup_recognition as recognition
from scripts import startup_recovery as recovery
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.bluestacks_popup_recognition import DISCONNECT_BUTTON_EXPECTED, NETWORK_DISCONNECT_TARGET
from tests.support.safe_action import PROFILE_ID, TEST_TASK_ID, intent
from tests.test_network_disconnect_recognition import EXACT_MESSAGE, disconnect_frame
from tests.test_network_recovery_state import gameplay_snapshot


TASK_ID = "RUNTIME-NETWORK-DISCONNECT-RECOVERY"
SCOPE = "device:emulator-5554:com.example.game"
OWNER = "network-recovery-test-owner"
AUTHORIZATION = "operator-approved shared 10054 recovery for this controller"
NOW = 1_794_000_000.0
DAY = 86_400.0
SHAPE = (1280, 800, 3)
HOME, OVERLAY, LAUNCHER, MANUAL, UNKNOWN = 211, 41, 61, 141, 181
CONTEXTS = {
    HOME: "HOME_BASE", OVERLAY: "KNOWN_STARTUP_OVERLAY",
    LAUNCHER: "BLUESTACKS_LAUNCHER", MANUAL: "MANUAL_REQUIRED",
}
WRONG_CODE_TAG = 7
EXACT = disconnect_frame()
WRONG_CODE = disconnect_frame()
WRONG_CODE[0:2, 0:2] = WRONG_CODE_TAG
SHIFTED_BUTTON = (284, 676, 528, 754)
SHIFTED = disconnect_frame(buttons=(SHIFTED_BUTTON,))
APPROVED = PolicyResult(PolicyDecision.AUTHORIZE, "AUTHORIZED", "", NOW - 50, {})


class CheckpointStop(RuntimeError):
    pass


def marker(frame):
    return int(frame[200, 200, 0])


def observe(captured):
    return CONTEXTS.get(marker(captured.frame), "UNKNOWN")


def disconnect_message(frame):
    """Bounded OCR stand-in: only the synthetic tag selects the wrong code."""
    return "disconnected. reconnect now?[10053]" if int(frame[0, 0, 0]) == WRONG_CODE_TAG else EXACT_MESSAGE.casefold()


class ReplayDevice:
    """PNG transport whose screen persists until a tap or a lifecycle launch changes it."""

    def __init__(self):
        self.current = HOME
        self.after_tap = None
        self.taps = []
        self.transport_failure = False
        self.captures = 0
        self.hooks = []

    def capture_png(self):
        for hook in list(self.hooks):
            hook()
        self.captures += 1
        spec = self.current
        image = spec.copy() if isinstance(spec, np.ndarray) else np.full(SHAPE, spec, np.uint8)
        image[1279, 0] = self.captures % 250 + 1  # every capture is a distinct PNG
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        return encoded.tobytes()

    def dispatch_tap(self, point):
        self.taps.append(point)
        if self.after_tap is not None:
            self.current = self.after_tap
        if self.transport_failure:
            raise RuntimeError("transport completion uncertain")


class FixtureClock:
    """Finite UTC/monotonic pair; only the injected sleep moves time forward."""

    def __init__(self, limit=20_000):
        self.offset = 0.0
        self.ticks = 0
        self.calls = 0
        self.limit = limit
        self.last_monotonic = -math.inf
        self.sleeps = []

    def _count(self):
        self.calls += 1
        if self.calls > self.limit:
            raise AssertionError("recovery used an unbounded number of clock reads")

    def utc(self):
        self._count()
        self.ticks += 1
        return NOW + self.offset + self.ticks * 0.001

    def monotonic(self):
        self._count()
        value = time.monotonic() + self.offset
        if value < self.last_monotonic:
            raise AssertionError("fixture monotonic clock moved backwards")
        self.last_monotonic = value
        return value

    def sleep(self, seconds):
        if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                or seconds < 0 or len(self.sleeps) >= 50):
            raise AssertionError(f"unbounded or invalid recovery sleep: {seconds!r}")
        self.sleeps.append(seconds)
        self.offset += seconds

    def advance(self, seconds):
        self.offset += seconds


class Relaunch:
    """Existing lifecycle start: one system launch, no game input, own transport fact."""

    def __init__(self, env):
        self.env = env
        self.calls = []
        self.lands_on = HOME

    def __call__(self):
        env = self.env
        self.calls.append({
            "taps": len(env.device.taps),
            "shown": marker(env.device.current) if isinstance(env.device.current, np.ndarray)
            else env.device.current,
            "network_status": [row["final_status"] for row in env.network_rows()],
            "captured_paths": {row["path"] for row in env.events() if row["type"] == "capture"},
        })
        env.device.current = self.lands_on
        return {
            "status": "launched", "system_launch_count": 1, "game_input_count": 0,
            "route_ready": True, "transport_status": "returned",
        }


class Environment:
    def __init__(self, root: Path, stack: ExitStack):
        self.root = root
        self.device = ReplayDevice()
        self.clock = FixtureClock()
        self.relaunch = Relaunch(self)
        self.stop_after_intent = False
        self.state_path = root / "state.sqlite3"
        self.state = BotStateManager(
            self.state_path, owner_instance_id="owner-a", process_start_token="process-a", process_id=101,
        )
        stack.callback(lambda: self.state.close())
        self.store_path = root / "actions.sqlite3"
        self.store = SafetyStore(self.store_path)
        stack.callback(lambda: self.store.close())
        self.runtime = None
        self.runtimes = 0
        self.new_runtime()
        # Partial gameplay progress that recovery must neither consume nor reset.
        self.state.initialize_flows([
            FlowSpec("FLOW-PARTIAL", default_enabled=False, priority=1, cadence="manual",
                     max_wait_seconds=90.0, max_attempts=2),
        ])
        self.state.set_service_enabled(True, now_utc_epoch=NOW - 60)
        self.state.set_flow_enabled("FLOW-PARTIAL", True, now_utc_epoch=NOW - 60)
        self.store.prepare_action(intent("gameplay-confirmed", "day-1:claim:row-1"), APPROVED, NOW - 50)
        self.store.mark_input_sent("gameplay-confirmed", NOW - 49, TransportResult(True, "OK"))
        self.store.mark_confirmed("gameplay-confirmed", NOW - 48, {"confirmed": True})
        # The caller already holds the Core lease; the helper must not acquire one.
        self.store.acquire_lease(OWNER, NOW - 1, 300.0)
        self.gameplay_before = gameplay_snapshot(self.state)
        self.core_gameplay_before = dict(self.store.get_action("gameplay-confirmed"))

    def new_runtime(self):
        self.runtimes += 1
        self.runtime = LocalBlueStacksRuntime(self.device, self.root / f"native-{self.runtimes}", execute=True)
        self.runtime.max_inputs = 8
        self.runtime.checkpoint = self.checkpoint
        return self.runtime

    def restart_process(self):
        self.state.close()
        self.state = BotStateManager(
            self.state_path, owner_instance_id="owner-b", process_start_token="process-b", process_id=202,
        )
        self.store.close()
        self.store = SafetyStore(self.store_path)
        self.store.acquire_lease(OWNER, self.clock.utc(), 300.0)
        self.new_runtime()

    def checkpoint(self):
        if self.stop_after_intent and self.prepared_intent():
            self.stop_after_intent = False
            raise CheckpointStop("operator stop after the Confirm intent was committed")

    def network_rows(self):
        return self.store.list_actions_for_task(TASK_ID)

    def prepared_intent(self):
        return any(row["final_status"] == "prepared" for row in self.network_rows())

    def events(self):
        path = self.runtime.events
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def episode(self):
        return self.state.get_network_recovery(SCOPE)

    def recover(self, *, observe_context=observe, timeout_seconds=30.0, poll_seconds=10.0):
        return recovery.recover_network_disconnect(
            self.runtime, state_manager=self.state, action_store=self.store, owner=OWNER,
            checkpoint=self.checkpoint, observe_context=observe_context, relaunch=self.relaunch,
            scope_key=SCOPE, authorization=AUTHORIZATION,
            timeout_seconds=timeout_seconds, poll_seconds=poll_seconds,
            utc_clock=self.clock.utc, monotonic_clock=self.clock.monotonic, sleep=self.clock.sleep,
        )


class NetworkDisconnectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        forbidden = AssertionError("network recovery must reuse its caller's runtime, owner and stores")
        for target in (
            "scripts.startup_recovery.SafetyStore",
            "scripts.startup_recovery.BotStateManager",
            "safe_action_core.SafetyStore",
            "scripts.bluestacks_native_runtime.ADBRunner",
            "scripts.bluestacks_native_runtime.LocalBlueStacksRuntime.connect",
            "scripts.navigation_development_boundary.DevelopmentSession",
            "scripts.navigation_development_boundary.RuntimeInputLock.acquire",
        ):
            self.stack.enter_context(patch(target, side_effect=forbidden))
        self.stack.enter_context(patch.object(
            recognition, "_read_disconnect_message", side_effect=disconnect_message,
        ))
        self.stack.enter_context(patch.object(
            recognition, "_read_disconnect_confirm", return_value="confirm",
        ))
        self.environments = 0

    def environment(self, source=EXACT, after_tap=None):
        self.environments += 1
        root = self.root / f"env-{self.environments}"
        root.mkdir()
        env = Environment(root, self.stack)
        env.device.current = source
        env.device.after_tap = after_tap
        return env

    def assert_no_input(self, env, result, *, prior_taps=0, rows_before=None):
        self.assertNotEqual(result["status"], "recovered")
        self.assertFalse(result["route_ready"])
        self.assertEqual((result["input_count"], result["game_input_count"], result["system_launch_count"]),
                         (0, 0, 0))
        self.assertEqual(len(env.device.taps), prior_taps)
        self.assertEqual(env.relaunch.calls, [])
        if rows_before is not None:
            self.assertEqual(env.network_rows(), rows_before)  # the Core journal is not touched
        else:
            self.assertFalse(any(row["final_status"] in {"input_sent", "confirmed", "unresolved"}
                                 for row in env.network_rows()))

    def assert_gameplay_untouched(self, env):
        self.assertEqual(gameplay_snapshot(env.state), env.gameplay_before)
        self.assertEqual(dict(env.store.get_action("gameplay-confirmed")), env.core_gameplay_before)

    def assert_tied_successor(self, env, result, dispatch):
        events = env.events()
        captures = {row["path"]: (index, row) for index, row in enumerate(events) if row["type"] == "capture"}
        dispatch_index = next(index for index, row in enumerate(events)
                              if row["type"] == "dispatch" and row["action_key"] == dispatch["action_key"])
        source_index, source = captures[result["source_frame"]]
        immediate_index, immediate = captures[result["immediate_before_frame"]]
        after_index, after = captures[result["after_frame"]]
        self.assertEqual((source["sha256"], immediate["sha256"], after["sha256"]),
                         (result["source_sha256"], result["immediate_before_sha256"], result["after_sha256"]))
        self.assertLess(source_index, immediate_index)
        self.assertLess(immediate_index, dispatch_index)
        self.assertLess(dispatch_index, after_index)
        self.assertLess(source["captured_monotonic"], immediate["captured_monotonic"])
        self.assertLess(immediate["captured_monotonic"], after["captured_monotonic"])
        self.assertEqual(dispatch["source_sha256"], result["immediate_before_sha256"])
        self.assertNotEqual(result["immediate_before_sha256"], result["source_sha256"])

    def test_confirm_then_fresh_connected_context_recovers_with_one_tap_and_no_launch(self):
        for name, successor in (("home", HOME), ("owned startup overlay", OVERLAY)):
            with self.subTest(successor=name):
                env = self.environment(EXACT, after_tap=successor)
                result = env.recover()

                self.assertEqual(result["status"], "recovered")
                self.assertTrue(result["route_ready"])
                self.assertTrue(result["accounting_verified"])
                self.assertFalse(result["unresolved_action"])
                self.assertEqual((result["input_count"], result["game_input_count"], result["system_launch_count"]),
                                 (1, 1, 0))
                self.assertEqual(result["scope_key"], SCOPE)
                self.assertEqual(env.relaunch.calls, [])
                self.assertEqual(env.device.taps, [(400, 711)])

                dispatch, = [row for row in env.events() if row["type"] == "dispatch"]
                self.assertEqual(dispatch["action_class"], "network_reconnect")
                self.assertEqual(dispatch["target_identity"], NETWORK_DISCONNECT_TARGET)
                self.assertEqual(tuple(dispatch["target_roi"]), DISCONNECT_BUTTON_EXPECTED)
                self.assertFalse(dispatch["consequential"])
                self.assert_tied_successor(env, result, dispatch)
                terminal = cv2.imdecode(np.frombuffer(Path(result["terminal_frame"]).read_bytes(), np.uint8),
                                        cv2.IMREAD_COLOR)
                self.assertEqual(marker(terminal), successor)
                reconcile, = [row for row in env.events() if row["type"] == "reconcile"]
                self.assertEqual((reconcile["action_key"], reconcile["status"]), (dispatch["action_key"], "confirmed"))

                row, = env.network_rows()
                self.assertEqual(row["action_key"], dispatch["action_key"])
                self.assertEqual(row["semantic_action"], "RECOVER_NETWORK_DISCONNECT")
                self.assertEqual(row["target_identity"], NETWORK_DISCONNECT_TARGET)
                self.assertEqual(tuple(json.loads(row["target_roi_json"])), DISCONNECT_BUTTON_EXPECTED)
                self.assertEqual((row["final_status"], row["consequential"], row["cost_amount"]), ("confirmed", 0, 0))
                self.assertEqual(
                    [event["lifecycle_to"] for event in env.store.audit_events(row["action_id"])
                     if event["lifecycle_to"]],
                    ["prepared", "input_sent", "confirmed"],
                )

                episode = env.episode()
                self.assertEqual(result["episode_id"], episode.episode_id)
                self.assertIs(episode.status, NetworkRecoveryStatus.RECOVERED)
                self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 0))
                self.assertIs(episode.confirm_transport_status, NetworkRecoveryTransportStatus.RETURNED)
                self.assertIs(episode.relaunch_transport_status, NetworkRecoveryTransportStatus.NOT_ATTEMPTED)
                self.assertEqual(episode.source_frame_hash, result["source_sha256"])
                self.assertTrue(env.store.lease_valid_for(OWNER, env.clock.utc()))
                self.assert_gameplay_untouched(env)

    def test_launcher_after_confirm_allows_one_existing_launch_then_requires_fresh_home(self):
        env = self.environment(EXACT, after_tap=LAUNCHER)
        result = env.recover()

        self.assertEqual(result["status"], "recovered")
        self.assertTrue(result["route_ready"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual((result["input_count"], result["game_input_count"], result["system_launch_count"]),
                         (1, 1, 1))
        self.assertEqual(env.device.taps, [(400, 711)])
        launch, = env.relaunch.calls
        # The launch follows Core's positive popup-closed acknowledgement on the launcher.
        self.assertEqual((launch["taps"], launch["shown"], launch["network_status"]), (1, LAUNCHER, ["confirmed"]))
        self.assertNotIn(result["terminal_frame"], launch["captured_paths"])
        terminal = cv2.imdecode(np.frombuffer(Path(result["terminal_frame"]).read_bytes(), np.uint8),
                                cv2.IMREAD_COLOR)
        self.assertEqual(marker(terminal), HOME)
        episode = env.episode()
        self.assertIs(episode.status, NetworkRecoveryStatus.RECOVERED)
        self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 1))
        self.assertIs(episode.relaunch_transport_status, NetworkRecoveryTransportStatus.RETURNED)
        self.assert_gameplay_untouched(env)

    def test_launcher_or_launch_transport_success_is_never_terminal_success(self):
        for name, lands_on in (("still launcher", LAUNCHER), ("unknown", UNKNOWN), ("popup again", EXACT)):
            with self.subTest(after_launch=name):
                env = self.environment(EXACT, after_tap=LAUNCHER)
                env.relaunch.lands_on = lands_on
                result = env.recover()

                self.assertNotEqual(result["status"], "recovered")
                self.assertFalse(result["route_ready"])
                self.assertEqual((result["input_count"], result["system_launch_count"]), (1, 1))
                self.assertEqual(len(env.relaunch.calls), 1)
                self.assertIsNot(env.episode().status, NetworkRecoveryStatus.RECOVERED)

                env.new_runtime()
                reopened = env.recover()
                self.assertNotEqual(reopened["status"], "recovered")
                self.assertEqual((reopened["input_count"], reopened["system_launch_count"]), (0, 0))
                self.assertEqual(len(env.relaunch.calls), 1)
                self.assertEqual(len(env.device.taps), 1)
                self.assert_gameplay_untouched(env)

    def test_connected_source_needs_no_input_episode_or_launch(self):
        env = self.environment(HOME)
        result = env.recover()
        self.assertEqual(result["status"], "recovered")
        self.assertTrue(result["route_ready"])
        self.assertEqual((result["input_count"], result["system_launch_count"]), (0, 0))
        self.assertIsNone(result["immediate_before_sha256"])
        self.assertEqual(env.device.taps, [])
        self.assertEqual(env.relaunch.calls, [])
        self.assertEqual(env.network_rows(), [])
        self.assertIsNone(env.episode())

    def test_runtime_grants_no_generic_confirm_on_the_dialog(self):
        env = self.environment(EXACT)
        dialog = env.runtime.capture("route-observed-dialog")
        exact = {"target_identity": NETWORK_DISCONNECT_TARGET, "target_roi": DISCONNECT_BUTTON_EXPECTED}
        for name, change in (
            ("ordinary navigation", {"action_class": "navigation", "action_key": "route:confirm"}),
            ("ordinary generic target", {"action_class": "navigation", "action_key": "route:confirm",
                                         "target_identity": "generic-popup-confirm"}),
            ("reconnect class without recovery key", {"action_class": "network_reconnect",
                                                      "action_key": "route:confirm"}),
            ("reconnect class on moved target", {"action_class": "network_reconnect",
                                                 "action_key": "network-recovery:moved",
                                                 "target_roi": SHIFTED_BUTTON}),
            ("consequential reconnect", {"action_class": "network_reconnect",
                                         "action_key": "network-recovery:consequential", "consequential": True}),
        ):
            with self.subTest(dispatch=name), self.assertRaises(RuntimeError):
                env.runtime.tap(dialog, **{**exact, **change})
        with self.assertRaises(recovery.NetworkDisconnectError):
            env.runtime.tap(dialog, **exact, action_key="route:ordinary", action_class="navigation")
        self.assertEqual((env.device.taps, env.runtime.input_count), ([], 0))

    def test_unqualified_sources_send_no_input(self):
        def claims(context):
            return lambda _captured: context

        for name, source, observer in (
            ("wrong code", WRONG_CODE, observe),
            ("wrong code claimed connected", WRONG_CODE, claims("HOME_BASE")),
            ("unrelated unknown", UNKNOWN, observe),
            ("manual screen", MANUAL, observe),
            # An exact dialog is actionable only inside the game foreground (context UNKNOWN).
            ("manual context over exact 10054", EXACT, claims("MANUAL_REQUIRED")),
            ("launcher context over exact 10054", EXACT, claims("BLUESTACKS_LAUNCHER")),
            ("home claimed over exact 10054", EXACT, claims("HOME_BASE")),
        ):
            with self.subTest(source=name):
                env = self.environment(source, after_tap=HOME)
                result = env.recover(observe_context=observer)
                self.assert_no_input(env, result)
                self.assert_gameplay_untouched(env)

    def test_core_freshness_denies_a_decision_older_than_its_frames(self):
        env = self.environment(EXACT, after_tap=HOME)

        def slow_observer(captured):
            env.clock.advance(31.0)
            return observe(captured)

        result = env.recover(observe_context=slow_observer)
        self.assert_no_input(env, result)

    def test_changed_immediate_frame_after_intent_sends_no_input_and_budget_is_not_renewed(self):
        for name, changed in (("moved Confirm", SHIFTED), ("wrong code", WRONG_CODE), ("dialog gone", HOME)):
            with self.subTest(immediate=name):
                env = self.environment(EXACT, after_tap=HOME)

                def swap(env=env, changed=changed):
                    if env.prepared_intent():
                        env.device.current = changed

                env.device.hooks.append(swap)
                result = env.recover()
                self.assert_no_input(env, result)
                row, = env.network_rows()
                self.assertEqual(row["final_status"], "cancelled")

                env.device.hooks.clear()
                env.device.current = EXACT
                cancelled = env.network_rows()
                again = env.recover()
                self.assert_no_input(env, again, rows_before=cancelled)

    def test_lease_loss_after_intent_before_dispatch_sends_no_tap(self):
        env = self.environment(EXACT, after_tap=HOME)

        def lose_lease():
            if env.prepared_intent() and env.store.lease_valid_for(OWNER, env.clock.utc()):
                env.store.release_lease(OWNER, env.clock.utc())

        env.device.hooks.append(lose_lease)
        result = env.recover()
        self.assert_no_input(env, result)
        self.assertIsNot(env.episode().status, NetworkRecoveryStatus.RECOVERED)
        self.assert_gameplay_untouched(env)

    def test_checkpoint_stop_before_dispatch_propagates_and_reopen_cannot_confirm(self):
        env = self.environment(EXACT, after_tap=HOME)
        env.stop_after_intent = True
        with self.assertRaises(CheckpointStop):
            env.recover()
        self.assertEqual(env.device.taps, [])
        self.assertEqual([row["final_status"] for row in env.network_rows()], ["prepared"])

        env.restart_process()
        prepared = env.network_rows()
        reopened = env.recover()
        self.assert_no_input(env, reopened, rows_before=prepared)
        self.assert_gameplay_untouched(env)

    def test_unknown_or_persistent_result_after_sent_input_stays_unresolved_with_one_intent(self):
        for name, after, transport_failure, transport in (
            ("persistent popup", EXACT, False, NetworkRecoveryTransportStatus.RETURNED),
            ("unknown screen", UNKNOWN, False, NetworkRecoveryTransportStatus.RETURNED),
            ("lookalike modal", WRONG_CODE, False, NetworkRecoveryTransportStatus.RETURNED),
            ("uncertain transport", EXACT, True, NetworkRecoveryTransportStatus.UNKNOWN),
        ):
            with self.subTest(after=name):
                env = self.environment(EXACT, after_tap=after)
                env.device.transport_failure = transport_failure
                result = env.recover()

                self.assertEqual(result["status"], "unresolved")
                self.assertTrue(result["unresolved_action"])
                self.assertFalse(result["route_ready"])
                self.assertEqual((result["input_count"], result["system_launch_count"]), (1, 0))
                self.assertEqual(env.device.taps, [(400, 711)])
                self.assertEqual(env.relaunch.calls, [])
                row, = env.network_rows()
                self.assertEqual(row["final_status"], "unresolved")
                episode = env.episode()
                self.assertIsNot(episode.status, NetworkRecoveryStatus.RECOVERED)
                self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 0))
                self.assertIs(episode.confirm_transport_status, transport)
                self.assertEqual([row["status"] for row in env.events() if row["type"] == "reconcile"],
                                 ["unresolved"])
                self.assert_gameplay_untouched(env)

    def test_reopen_new_frame_and_reset_cannot_repeat_confirm_or_launch(self):
        env = self.environment(EXACT, after_tap=EXACT)
        first = env.recover()
        self.assertNotEqual(first["status"], "recovered")
        unresolved, = env.network_rows()
        self.assertEqual(unresolved["final_status"], "unresolved")

        def new_frame():
            env.device.current = SHIFTED

        def restart():
            env.restart_process()
            env.device.current = EXACT

        def reset():
            env.clock.advance(DAY)
            env.new_runtime()

        for name, change in (("new frame", new_frame), ("process reopen", restart), ("daily reset", reset)):
            with self.subTest(reopen=name):
                change()
                rows_before = env.network_rows()
                result = env.recover()
                self.assert_no_input(env, result, prior_taps=1, rows_before=rows_before)
                self.assertEqual([(row["action_id"], row["final_status"]) for row in rows_before],
                                 [(unresolved["action_id"], "unresolved")])
                episode = env.episode()
                self.assertEqual(episode.episode_id, first["episode_id"])
                self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 0))
        self.assert_gameplay_untouched(env)

    def test_prior_unknown_gameplay_action_denies_recovery_and_stays_untouched(self):
        env = self.environment(EXACT, after_tap=HOME)
        env.store.prepare_action(intent("gameplay-unknown", "day-1:claim:row-2"), APPROVED, NOW - 20)
        env.store.mark_input_sent("gameplay-unknown", NOW - 19, TransportResult(True, "OK"))
        env.store.mark_unresolved("gameplay-unknown", NOW - 18, "result_not_observed")
        unknown_before = dict(env.store.get_action("gameplay-unknown"))

        result = env.recover()
        self.assertEqual(result["status"], "blocked")
        self.assert_no_input(env, result)
        self.assertEqual(dict(env.store.get_action("gameplay-unknown")), unknown_before)
        self.assertTrue(env.store.has_action_block())
        self.assert_gameplay_untouched(env)


class NetworkReconnectPolicyTests(unittest.TestCase):
    """Real Core policy: the recovery task grants only the exact zero-cost 10054 Confirm."""

    def setUp(self):
        # Both tasks are enabled so every denial below comes from the network contract.
        self.policy = CentralPolicy(supervised_tasks=frozenset({TASK_ID, TEST_TASK_ID}))
        self.observation = Observation(
            frame_sha256="b" * 64, capture_completed_monotonic=500.0, runtime_profile_id=PROFILE_ID,
            width=800, height=1280, valid_png=True, corrupt=False, black=False,
            source_state="NETWORK_DISCONNECTED_10054", overlay_state="network_disconnect_10054",
            target_identity=NETWORK_DISCONNECT_TARGET, target_roi=DISCONNECT_BUTTON_EXPECTED,
            control_class="POPUP_DISMISS_CONFIRM", consequence="navigate_zero_cost",
            cost_type="none", cost_amount=0, quantity=1,
            expected_postcondition="NETWORK_RECONNECT_ACKNOWLEDGED",
            evidence_refs=("synthetic:network-disconnect",),
            critical_roi_hashes=(("network_disconnect_dialog", "c" * 64), ("network_disconnect_confirm", "d" * 64)),
            target_isolated=True,
        )
        self.request = PolicyRequest(
            action_id="network-recovery:netrec-policy:confirm", action_key="network-recovery:netrec-policy:confirm",
            task_id=TASK_ID, task_mode="supervised_validation", semantic_action="RECOVER_NETWORK_DISCONNECT",
            expected_runtime_profile_id=PROFILE_ID, observation=self.observation, monotonic_now=501.0,
            observation_max_age_seconds=30.0, dispatch_max_age_seconds=30.0,
            lease_owner=OWNER, lease_valid=True, unresolved_action=False, duplicate_action_key=False,
            action_class=ActionClass.NAVIGATION_ONLY, action_kind="RECOVER_NETWORK_DISCONNECT",
            subject=NETWORK_DISCONNECT_TARGET, resource_or_currency="none", maximum_cost=0, free_only=True,
            semantic_preconditions=("NETWORK_DISCONNECTED_10054",),
            semantic_postconditions=("NETWORK_RECONNECT_ACKNOWLEDGED",),
        )

    def test_any_departure_from_the_exact_confirm_loses_network_authority(self):
        self.assertTrue(self.policy.evaluate(self.request).authorized)  # control for the negatives
        dialog, confirm = self.observation.critical_roi_hashes
        request_changes = {
            "ordinary task": {"task_id": TEST_TASK_ID},
            "claim semantic": {"semantic_action": "CLAIM_DAILY_QUEST"},
            "reset popup semantic": {"semantic_action": "DISMISS_RESET_POPUP"},
            "consequential class": {"action_class": ActionClass.ZERO_COST_CONSEQUENTIAL},
        }
        observation_changes = {
            "reset popup source": {"source_state": "RESET_POPUP"},
            "generic overlay": {"overlay_state": "known_reset_popup"},
            "clear overlay": {"overlay_state": "none_observed"},
            "other target": {"target_identity": "reset-popup-close"},
            "close control": {"control_class": "POPUP_DISMISS_X"},
            "claim control": {"control_class": "CLAIM"},
            "game success successor": {"expected_postcondition": "HOME_BASE"},
            "nonzero cost": {"cost_amount": 1},
            "premium cost": {"cost_type": "premium"},
            "second quantity": {"quantity": 2},
            "no dialog ROI": {"critical_roi_hashes": (confirm,)},
            "no Confirm ROI": {"critical_roi_hashes": (dialog,)},
            "no critical ROIs": {"critical_roi_hashes": ()},
            "target outside Confirm band": {"target_roi": (278, 820, 522, 898)},
        }
        cases = [(name, replace(self.request, **change)) for name, change in request_changes.items()]
        cases += [
            (name, replace(self.request, observation=replace(self.observation, **change)))
            for name, change in observation_changes.items()
        ]
        for name, request in cases:
            with self.subTest(change=name):
                self.assertFalse(self.policy.evaluate(request).authorized)

    def test_recovery_task_grants_no_generic_popup_confirm(self):
        generic = replace(
            self.observation, source_state="GENERIC_POPUP", overlay_state="none_observed",
            target_identity="generic-popup-confirm", expected_postcondition="POPUP_CLOSED",
            critical_roi_hashes=(),
        )
        request = replace(
            self.request, semantic_action="DISMISS_POPUP", action_kind="DISMISS_POPUP",
            subject="generic-popup-confirm", observation=generic,
            semantic_preconditions=("GENERIC_POPUP",), semantic_postconditions=("POPUP_CLOSED",),
        )
        self.assertFalse(self.policy.evaluate(request).authorized)



if __name__ == "__main__":
    unittest.main()
