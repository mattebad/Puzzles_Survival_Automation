"""Consumer-visible 10054 boundaries: startup, native runtime, contextual recovery, service.

Only device transport (ADB) and OCR text reads are faked.  Startup, the native
runtime, recognition geometry, the recovery helper, canonical SQLite, the Core
SafetyStore and the claimed service are the production implementations.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import cv2
import numpy as np

from automation_service.registry import RECRUITMENT_FLOW_ID
from automation_service.state import BotStateManager
from safe_action_core import CentralPolicy, SafetyStore, TransportResult
from scripts import bluestacks_popup_recognition as recognition
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts import startup_recovery
from scripts.bluestacks_flow_collector import ADBDevice
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime, box_center
from scripts.bluestacks_popup_recognition import (
    DISCONNECT_BUTTON_EXPECTED,
    DISCONNECT_PANEL_EXPECTED,
    NETWORK_DISCONNECT_TARGET,
)
from scripts.startup_recovery import (
    NetworkDisconnectError,
    recover_contextual_startup_overlay,
    recover_contextual_vip_popup,
    require_network_clear,
)
from tasks.runtime_identity import BLUESTACKS_ADB, BLUESTACKS_PACKAGE, BLUESTACKS_SERIAL, FIXED_RUNTIME_SCOPE
from tests.support import recruitment_service
from tests.support.contextual_startup import SCARLETT, startup_surface
from tests.support.safe_action import TEST_TASK_ID, intent, request
from tests.support.startup_recovery import popup


# Captured before any fixture replaces it: recovery must use the real seam.
REAL_CONNECT = LocalBlueStacksRuntime.__dict__["connect"]
RECOVERY_TASK_ID = "RUNTIME-NETWORK-DISCONNECT-RECOVERY"
LAUNCHER_PACKAGE = "com.uncube.launcher3"
CONFIRM_CENTER = box_center(DISCONNECT_BUTTON_EXPECTED)
VIP_CLOSE_ROI = (263, 781, 537, 869)

BACKGROUND, PANEL_GRAY, LABEL_GRAY, LAUNCHER_GRAY = 18, 44, 245, 40
GOLD_BGR = (60, 123, 180)
HOME_FLAG = 200
# Pixel (1, 1) selects the OCR text the fake reader returns for a dialog frame.
MESSAGES = {
    1: "Disconnected. Reconnect now?[10054]",
    2: "Disconnected. Reconnect now?[10053]",
    3: "Exit the game now?",
    4: "New version detected. Tap Confirm to update.",
}
DIALOG_MARKERS = {"disconnect": 1, "wrong_code": 2, "other_confirm": 3, "update": 4}
NOT_RECOGNIZED_POPUP = {"recognized": False, "blocking_unknown_modal": False, "reason": "not_recognized"}
NOT_RECOGNIZED_SURFACE = {"recognized": False, "commercial_looking": False}


def screen_frame(kind: str) -> np.ndarray:
    """Native frames; every game screen keeps Home visible behind any modal."""
    if kind == "launcher":
        return np.full((1280, 800, 3), LAUNCHER_GRAY, np.uint8)
    frame = np.full((1280, 800, 3), BACKGROUND, np.uint8)
    if kind != "unknown":
        frame[0:3, 6:9] = HOME_FLAG
    marker = DIALOG_MARKERS.get(kind)
    if marker is not None:
        panel = (81, 391, 721, 722) if kind == "update" else DISCONNECT_PANEL_EXPECTED
        button = (277, 619, 523, 697) if kind == "update" else DISCONNECT_BUTTON_EXPECTED
        x0, y0, x1, y1 = panel
        frame[y0:y1, x0:x1] = PANEL_GRAY
        x0, y0, x1, y1 = button
        frame[y0:y1, x0:x1] = GOLD_BGR
        cx, cy = box_center(button)
        frame[cy - 11:cy + 11, cx - 50:cx + 50] = LABEL_GRAY
        frame[0:3, 0:3] = marker
    return frame


@lru_cache(maxsize=None)
def encode(kind: str) -> bytes:
    ok, payload = cv2.imencode(".png", screen_frame(kind))
    if not ok:
        raise AssertionError("offline frame could not be encoded")
    return payload.tobytes()


def sha(kind: str) -> str:
    return hashlib.sha256(encode(kind)).hexdigest()


def read_message(frame: np.ndarray) -> str:
    return recognition.normalized(MESSAGES.get(int(frame[1, 1, 0]), ""))


def read_confirm(frame: np.ndarray, bounds) -> str:
    marker = int(frame[1, 1, 0])
    button = (277, 619, 523, 697) if marker == 4 else DISCONNECT_BUTTON_EXPECTED
    return "confirm" if marker in MESSAGES and tuple(bounds) == button else ""


def clean_home(frame: np.ndarray) -> bool:
    """Home recognizer stand-in: it sees Home even behind a modal."""
    return bool(int(frame[1, 7, 0]) == HOME_FLAG)


class FakeDevice:
    """One emulator: screens change only through taps, launches or a script."""

    def __init__(self, screen: str = "home", *, after_tap: str = "home", after_launch: str = "home"):
        self.screen = screen
        self.after_tap = after_tap
        self.after_launch = after_launch
        self.sequence: list[str] = []
        self.taps: list[tuple[str, tuple[int, int]]] = []
        self.launches: list[tuple[str, ...]] = []
        self.stops: list[tuple[str, ...]] = []
        self.unexpected: list[tuple[str, ...]] = []

    def foreground(self) -> str:
        return LAUNCHER_PACKAGE if self.screen == "launcher" else BLUESTACKS_PACKAGE

    def focus(self) -> str:
        return f"mCurrentFocus=Window{{1 u0 {self.foreground()}/.MainActivity}}\n"

    def capture(self) -> bytes:
        if self.sequence:
            self.screen = self.sequence.pop(0)
        # Coarse Windows monotonic ticks: keep successive captures strictly ordered.
        time.sleep(0.04)
        return encode(self.screen)

    def tap(self, point) -> None:
        self.taps.append((self.screen, tuple(point)))
        self.screen = self.after_tap

    def adb(self, *arguments: str, binary: bool = False):
        if arguments == ("get-state",):
            return "device"
        if arguments == ("exec-out", "screencap", "-p") and binary:
            return self.capture()
        if arguments == ("shell", "dumpsys", "window"):
            return self.focus()
        if arguments[:4] == ("shell", "cmd", "package", "resolve-activity"):
            return f"{BLUESTACKS_PACKAGE}/.MainActivity\n"
        if arguments == ("shell", "am", "force-stop", BLUESTACKS_PACKAGE):
            self.stops.append(arguments)
            self.screen = "launcher"
            return ""
        if arguments == ("shell", "ps", "-A"):
            return "USER PID PPID VSZ RSS WCHAN ADDR S NAME\nroot 1 0 0 0 0 0 S init\n"
        if arguments[:4] == ("shell", "am", "start", "-W"):
            self.launches.append(arguments)
            self.screen = self.after_launch
            return "Status: ok"
        self.unexpected.append(arguments)
        raise AssertionError(f"unexpected device command {arguments!r}")


class FakeRunner:
    """ADBRunner transport surface used by LocalBlueStacksRuntime."""

    def __init__(self, device: FakeDevice, serial: str):
        self.device = device
        self.serial = serial

    def list_devices(self):
        return [ADBDevice(self.serial, "device")]

    def get_state(self) -> str:
        return "device"

    def shell_text(self, *arguments: str) -> str:
        if arguments == ("dumpsys", "window", "windows"):
            return self.device.focus()
        self.device.unexpected.append(arguments)
        raise AssertionError(f"unexpected shell command {arguments!r}")

    def capture_png(self) -> bytes:
        return self.device.capture()

    def dispatch_tap(self, point) -> None:
        self.device.tap(point)

    def dispatch_back(self) -> None:
        self.device.unexpected.append(("back",))
        raise AssertionError("Back is not a network recovery input")


def install_recognizers(stack: ExitStack) -> None:
    stack.enter_context(mock.patch.object(recognition, "_read_disconnect_message", side_effect=read_message))
    stack.enter_context(mock.patch.object(recognition, "_read_disconnect_confirm", side_effect=read_confirm))
    stack.enter_context(mock.patch("scripts.startup_normalization.is_clean_home_frame", side_effect=clean_home))
    stack.enter_context(mock.patch.object(startup_recovery, "recognize_reset_popup", return_value=NOT_RECOGNIZED_POPUP))
    stack.enter_context(mock.patch.object(startup_recovery, "recognize_startup_surface",
                                          return_value=NOT_RECOGNIZED_SURFACE))


def install_device(stack: ExitStack, device: FakeDevice) -> None:
    stack.enter_context(mock.patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=device.adb))

    def runner_factory(executable: str, serial: str) -> FakeRunner:
        if executable != str(BLUESTACKS_ADB):
            raise AssertionError("recovery must use the fixed BlueStacks transport")
        return FakeRunner(device, serial)

    stack.enter_context(mock.patch("scripts.bluestacks_native_runtime.ADBRunner", new=runner_factory))
    install_recognizers(stack)


def seed_unresolved_consequential_action(path: Path) -> dict:
    with closing(SafetyStore(path)) as store:
        store.prepare_action(intent(), CentralPolicy(supervised_tasks={TEST_TASK_ID}).evaluate(request()), time.time())
        store.mark_input_sent("action-1", time.time(), TransportResult(True, "synthetic transport"))
        store.mark_unresolved("action-1", time.time(), "unknown consequential result")
        return dict(store.get_action("action-1"))


def recovery_actions(path: Path) -> list[dict]:
    with closing(SafetyStore(path)) as store:
        return [dict(row) for row in store.list_actions_for_task(RECOVERY_TASK_ID)]


class StartupNetworkCase(unittest.TestCase):
    """Real owner_bound_application_startup on temp canonical state and Core."""

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(mock.patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "input-lock.sqlite3"))
        self.core_path = self.root / "bluestacks-actions.sqlite3"
        stack.enter_context(mock.patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", self.core_path))
        self.state_path = self.root / "bot-state.sqlite3"
        stack.enter_context(mock.patch.object(BotStateManager, "DEFAULT_DB_PATH", self.state_path.resolve()))
        self.state = stack.enter_context(BotStateManager(self.state_path))
        self.device = FakeDevice()
        install_device(stack, self.device)
        self.recover = stack.enter_context(mock.patch.object(
            startup_recovery, "recover_network_disconnect", wraps=startup_recovery.recover_network_disconnect,
        ))
        self.lock = stack.enter_context(boundary.RuntimeInputLock(owner="automation-service",
                                                                  invocation_id="network-boundary"))
        self.attempt = 0
        self.checkpoints = 0

    def checkpoint(self):
        self.checkpoints += 1

    def start(self, *, runtime_input_lock=None, require_ready=True, **options):
        self.attempt += 1
        directory = self.root / f"startup-{self.attempt}"
        result = pnsctl.owner_bound_application_startup(
            runtime_input_lock=runtime_input_lock or self.lock, checkpoint=self.checkpoint,
            session_directory=directory, flow_id=RECRUITMENT_FLOW_ID, require_ready=require_ready, **options,
        )
        return result, directory

    def failed_start(self, **options):
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.start(**options)
        result = raised.exception.startup_result
        directory = self.root / f"startup-{self.attempt}"
        retained = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        for field in ("status", "game_input_count", "system_launch_count", "route_ready"):
            self.assertEqual(retained[field], result[field], field)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNot(result["route_ready"], True)
        return result, directory

    def authorized(self, **options):
        return dict(network_recovery=True, state_manager=self.state, **options)

    def assert_no_input(self):
        self.assertEqual(self.device.taps, [])
        self.assertEqual(self.device.unexpected, [])

    def episode(self):
        return self.state.get_network_recovery(FIXED_RUNTIME_SCOPE)


class DefaultStartupNetworkGuardTests(StartupNetworkCase):
    def test_update_requires_shared_recovery_opt_in_without_confirm_or_stop(self):
        self.device.screen = "update"
        for require_ready in (True, False):
            with self.subTest(require_ready=require_ready):
                result, directory = self.failed_start(require_ready=require_ready)
                self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
                self.assertEqual(result.get("system_stop_count", 0), 0)
                self.assertEqual((directory / "before.png").read_bytes(), encode("update"))
        self.assert_no_input()
        self.assertEqual(self.device.stops, [])
        self.assertEqual(self.device.launches, [])
        self.recover.assert_not_called()
        self.assertIsNone(self.episode())

    def test_foreground_disconnect_is_never_already_foreground_and_retains_before(self):
        self.device.screen = "disconnect"
        for require_ready in (True, False):
            with self.subTest(require_ready=require_ready):
                result, directory = self.failed_start(require_ready=require_ready)
                self.assertNotEqual(result.get("action"), "observe_existing_game")
                self.assertEqual((result["game_input_count"], result["input_count"]), (0, 0))
                self.assertEqual(result["system_launch_count"], 0)
                self.assertFalse(result["dispatch"])
                self.assertEqual(result["before_frame"], "before.png")
                self.assertEqual((directory / "before.png").read_bytes(), encode("disconnect"))
        self.assert_no_input()
        self.assertEqual(self.device.launches, [])
        self.recover.assert_not_called()
        self.assertIsNone(self.episode())

    def test_disconnect_in_after_observation_blocks_existing_foreground(self):
        self.device.sequence = ["home", "disconnect"]
        result, directory = self.failed_start()
        self.assertEqual((directory / "before.png").read_bytes(), encode("home"))
        self.assertEqual(result["after_frame"], "after.png")
        self.assertEqual((directory / "after.png").read_bytes(), encode("disconnect"))
        self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
        self.assert_no_input()
        self.recover.assert_not_called()

    def test_clear_home_still_observes_existing_game_without_launch(self):
        result, directory = self.start()
        self.assertEqual(result["status"], "already_foreground")
        self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
        self.assertTrue((directory / "after.png").is_file())
        self.assertEqual(self.device.launches, [])
        self.recover.assert_not_called()

    def test_wrong_code_or_other_confirm_never_invokes_recovery_even_when_authorized(self):
        for kind in ("wrong_code", "other_confirm"):
            for options in ({}, self.authorized()):
                with self.subTest(kind=kind, authorized=bool(options)):
                    self.device.screen = kind
                    result, directory = self.failed_start(**options)
                    self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
                    self.assertEqual((directory / "before.png").read_bytes(), encode(kind))
        self.assert_no_input()
        self.assertEqual(self.device.launches, [])
        self.recover.assert_not_called()
        self.assertIsNone(self.episode())
        self.assertEqual(recovery_actions(self.core_path), [])

    def test_disconnect_after_launch_is_not_route_ready_and_launch_is_not_retried(self):
        self.device.screen = "launcher"
        self.device.after_launch = "disconnect"
        result, directory = self.failed_start()
        self.assertEqual(result["system_launch_count"], 1)
        self.assertEqual(result["game_input_count"], 0)
        self.assertEqual(len(self.device.launches), 1)
        self.assertEqual((directory / result["after_frame"]).read_bytes(), encode("disconnect"))
        self.assert_no_input()
        self.recover.assert_not_called()


class AuthorizedStartupNetworkRecoveryTests(StartupNetworkCase):
    def test_exact_disconnect_recovers_on_borrowed_owner_with_one_real_confirm(self):
        self.device.screen, self.device.after_tap = "disconnect", "home"
        with mock.patch.object(boundary.RuntimeInputLock, "acquire",
                               side_effect=AssertionError("nested runtime owner")) as nested:
            result, directory = self.start(**self.authorized())
        nested.assert_not_called()
        self.lock.assert_held(self.lock.owner, self.lock.invocation_id)
        self.assertEqual(result["status"], "network_recovered")
        self.assertIs(result["route_ready"], True)
        self.assertEqual(self.device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual((result["game_input_count"], result["input_count"]), (len(self.device.taps), 1))
        self.assertEqual(result["system_launch_count"], 0)
        self.assertEqual(self.device.launches, [])
        self.assertEqual(self.device.unexpected, [])
        self.assertEqual((directory / "before.png").read_bytes(), encode("disconnect"))
        self.assertEqual(json.loads((directory / "result.json").read_text(encoding="utf-8"))["status"],
                         "network_recovered")
        recovery = result["network_recovery"]
        self.assertEqual(recovery["status"], "recovered")
        self.assertEqual((recovery["game_input_count"], recovery["system_launch_count"]), (1, 0))
        self.assertIs(recovery["accounting_verified"], True)
        self.assertEqual(recovery["source_sha256"], sha("disconnect"))
        self.assertEqual(recovery["immediate_before_sha256"], sha("disconnect"))
        self.assertEqual(recovery["terminal_sha256"], sha("home"))
        self.recover.assert_called_once()
        call = self.recover.call_args
        self.assertIs(call.kwargs["state_manager"], self.state)
        self.assertEqual(call.kwargs["scope_key"], FIXED_RUNTIME_SCOPE)
        episode = self.episode()
        self.assertEqual(episode.episode_id, recovery["episode_id"])
        self.assertEqual(episode.status, "RECOVERED")
        self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 0))
        self.assertEqual(episode.confirm_transport_status, "returned")
        actions = recovery_actions(self.core_path)
        self.assertEqual([row["final_status"] for row in actions], ["confirmed"])
        self.assertEqual(actions[0]["target_identity"], NETWORK_DISCONNECT_TARGET)
        with closing(SafetyStore(self.core_path)) as store:
            self.assertFalse(store.lease_valid_for(call.kwargs["owner"], time.time()))
            self.assertFalse(store.has_action_block())

    def test_launcher_acknowledgement_permits_one_launch_then_requires_fresh_home(self):
        self.device.screen, self.device.after_tap, self.device.after_launch = "disconnect", "launcher", "home"
        result, _directory = self.start(**self.authorized())
        self.assertEqual(result["status"], "network_recovered")
        self.assertEqual(self.device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual(len(self.device.launches), 1)
        self.assertEqual((result["game_input_count"], result["system_launch_count"]), (1, 1))
        self.assertEqual(result["network_recovery"]["terminal_sha256"], sha("home"))
        episode = self.episode()
        self.assertEqual(episode.status, "RECOVERED")
        self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 1))
        self.assertEqual(self.device.unexpected, [])

    def test_relaunch_back_into_disconnect_pauses_and_budgets_are_never_renewed(self):
        self.device.screen, self.device.after_tap, self.device.after_launch = "disconnect", "launcher", "disconnect"
        result, _directory = self.failed_start(**self.authorized())
        self.assertEqual((result["game_input_count"], result["system_launch_count"]), (1, 1))
        self.assertNotEqual(self.episode().status, "RECOVERED")
        # The same dialog observed again on a fresh startup gets no new budget.
        second, _directory = self.failed_start(**self.authorized())
        self.assertEqual((second["game_input_count"], second["system_launch_count"]), (0, 0))
        self.assertEqual(self.device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual(len(self.device.launches), 1)
        episode = self.episode()
        self.assertEqual((episode.confirm_attempts, episode.relaunch_attempts), (1, 1))
        self.assertNotEqual(episode.status, "RECOVERED")
        self.assertEqual(self.device.unexpected, [])

    def test_unknown_popup_after_confirm_is_unresolved_and_confirm_is_never_repeated(self):
        self.device.screen, self.device.after_tap = "disconnect", "other_confirm"
        result, _directory = self.failed_start(**self.authorized())
        self.assertEqual(result["game_input_count"], 1)
        self.assertEqual(result["system_launch_count"], 0)
        self.assertNotEqual(result["network_recovery"]["status"], "recovered")
        self.assertEqual([row["final_status"] for row in recovery_actions(self.core_path)], ["unresolved"])
        first_episode = self.episode()
        self.assertEqual(first_episode.status, "MANUAL_REQUIRED")
        # Exact 10054 reappears in a new frame: still no second Confirm.
        self.device.screen = "disconnect"
        second, _directory = self.failed_start(**self.authorized())
        self.assertEqual(second["game_input_count"], 0)
        self.assertEqual(self.device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual(self.device.launches, [])
        self.assertEqual(self.episode().episode_id, first_episode.episode_id)
        self.assertEqual(self.episode().confirm_attempts, 1)
        self.assertEqual(len(recovery_actions(self.core_path)), 1)
        self.assertEqual(self.device.unexpected, [])

    def test_pending_core_action_blocks_recovery_without_input(self):
        retained = seed_unresolved_consequential_action(self.core_path)
        self.device.screen = "disconnect"
        # The Core gate may refuse before any observation; either way nothing is sent.
        with self.assertRaises(pnsctl.OperatorError) as raised:
            self.start(**self.authorized())
        result = getattr(raised.exception, "startup_result", None)
        if result is not None:
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
        self.assertEqual(self.device.launches, [])
        self.assert_no_input()
        self.recover.assert_not_called()
        self.assertIsNone(self.episode())
        with closing(SafetyStore(self.core_path)) as store:
            self.assertEqual(dict(store.get_action("action-1")), retained)
            self.assertTrue(store.has_action_block())

    def test_recovery_requires_actual_owner_and_writable_canonical_state(self):
        other = self.root / "other-state.sqlite3"

        class BorrowedLock:
            owner, invocation_id = self.lock.owner, self.lock.invocation_id
            held = True

            def assert_held(lock, owner, invocation_id):
                self.lock.assert_held(owner, invocation_id)

        with BotStateManager(other) as noncanonical, BotStateManager(self.state_path, read_only=True) as read_only:
            cases = {
                "noncanonical": dict(network_recovery=True, state_manager=noncanonical),
                "read_only": dict(network_recovery=True, state_manager=read_only),
                "missing_state": dict(network_recovery=True, state_manager=None),
                "duck_owner": dict(self.authorized(), runtime_input_lock=BorrowedLock()),
            }
            for name, options in cases.items():
                with self.subTest(case=name):
                    self.device.screen = "disconnect"
                    result, _directory = self.failed_start(**options)
                    self.assertEqual((result["game_input_count"], result["system_launch_count"]), (0, 0))
        self.assert_no_input()
        self.recover.assert_not_called()
        self.assertIsNone(self.episode())
        self.assertEqual(recovery_actions(self.core_path), [])


class LocalRuntimeNetworkBoundaryTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        install_recognizers(stack)
        self.device = FakeDevice()
        self.sessions = 0
        self.runtime = self.new_runtime()

    def new_runtime(self) -> LocalBlueStacksRuntime:
        self.sessions += 1
        return LocalBlueStacksRuntime(FakeRunner(self.device, BLUESTACKS_SERIAL),
                                      self.root / f"native-{self.sessions}", execute=True)

    def dispatch_events(self, runtime: LocalBlueStacksRuntime) -> list[dict]:
        if not runtime.events.exists():
            return []
        lines = runtime.events.read_text(encoding="utf-8").splitlines()
        return [event for event in map(json.loads, lines) if event["type"] == "dispatch"]

    def test_ordinary_inputs_on_exact_or_ambiguous_modal_never_reach_transport(self):
        targets = (
            ("home-quest-button", (40, 1100, 140, 1200)),
            ("reset-popup-close", DISCONNECT_BUTTON_EXPECTED),
            (NETWORK_DISCONNECT_TARGET, DISCONNECT_BUTTON_EXPECTED),
        )
        for kind in ("disconnect", "wrong_code", "other_confirm"):
            self.device.screen = kind
            source = self.runtime.capture(f"{kind}-source")
            for target_identity, roi in targets:
                with self.subTest(kind=kind, target=target_identity):
                    with self.assertRaises(NetworkDisconnectError) as raised:
                        self.runtime.tap(source, target_identity=target_identity, target_roi=roi,
                                         action_key=f"route:{kind}:{target_identity}")
                    self.assertIs(raised.exception.captured, source)
            with self.subTest(kind=kind, target="android-back"):
                with self.assertRaises(NetworkDisconnectError):
                    self.runtime.back(source, action_key=f"route:{kind}:back")
        self.assertEqual(self.device.taps, [])
        self.assertEqual(self.device.unexpected, [])
        self.assertEqual(self.runtime.input_count, 0)
        self.assertEqual(self.runtime.action_keys, set())
        self.assertEqual(self.dispatch_events(self.runtime), [])

    def test_network_class_is_not_exempt_without_the_exact_current_dialog(self):
        for kind in ("wrong_code", "other_confirm", "home", "unknown", "launcher"):
            with self.subTest(kind=kind):
                self.device.screen = kind
                source = self.runtime.capture(f"{kind}-source")
                with self.assertRaises(RuntimeError):
                    self.runtime.tap(source, target_identity=NETWORK_DISCONNECT_TARGET,
                                     target_roi=DISCONNECT_BUTTON_EXPECTED,
                                     action_key=f"network-recovery:forged:{kind}", action_class="network_reconnect")
        self.assertEqual(self.device.taps, [])
        self.assertEqual(self.runtime.input_count, 0)

    def test_forged_network_target_key_or_stale_source_is_rejected_and_budget_is_not_renewed(self):
        self.device.screen = "disconnect"
        source = self.runtime.capture("exact-source")
        exact = dict(target_identity=NETWORK_DISCONNECT_TARGET, target_roi=DISCONNECT_BUTTON_EXPECTED,
                     action_key="network-recovery:episode:confirm", action_class="network_reconnect")
        forgeries = {
            "vip_identity": (source, dict(exact, target_identity="reset-popup-close")),
            "moved_roi": (source, dict(exact, target_roi=VIP_CLOSE_ROI)),
            "route_key": (source, dict(exact, action_key="route:network-confirm")),
            "consequential": (source, dict(exact, consequential=True)),
            "stale_source": (replace(source, captured_monotonic=source.captured_monotonic - 31.0), exact),
        }
        for name, (frame, options) in forgeries.items():
            with self.subTest(forgery=name):
                with self.assertRaises(RuntimeError):
                    self.runtime.tap(frame, **options)
        self.assertEqual(self.device.taps, [])
        self.assertEqual(self.runtime.input_count, 0)
        # Positive control: the exact current dialog admits exactly one Confirm.
        self.runtime.tap(source, **exact)
        self.assertEqual(self.device.taps, [("disconnect", CONFIRM_CENTER)])
        self.device.screen = "disconnect"
        fresh = self.runtime.capture("exact-again")
        with self.assertRaises(RuntimeError):
            self.runtime.tap(source, **dict(exact, action_key="network-recovery:episode:confirm-2"))
        with self.assertRaises(RuntimeError):
            self.runtime.tap(fresh, **exact)
        self.assertEqual(len(self.device.taps), 1)
        self.assertEqual(self.runtime.input_count, 1)

    def test_observation_guard_raises_only_after_capture_is_retained(self):
        self.runtime.observation_guard = require_network_clear
        for kind in ("disconnect", "wrong_code", "other_confirm"):
            with self.subTest(kind=kind):
                self.device.screen = kind
                with self.assertRaises(NetworkDisconnectError) as raised:
                    self.runtime.capture(f"guarded-{kind}")
                captured = raised.exception.captured
                self.assertEqual(captured.path.read_bytes(), encode(kind))
                self.assertEqual(captured.sha256, sha(kind))
                detail = raised.exception.recognition
                if kind == "disconnect":
                    self.assertTrue(detail["recognized"])
                else:
                    self.assertFalse(detail["recognized"])
                    self.assertTrue(detail["blocking_unknown_modal"])
                lines = self.runtime.events.read_text(encoding="utf-8").splitlines()
                retained = [event for event in map(json.loads, lines) if event["type"] == "capture"]
                self.assertEqual(retained[-1]["sha256"], captured.sha256)
                self.assertEqual(Path(retained[-1]["path"]), captured.path)
        self.device.screen = "home"
        self.assertEqual(self.runtime.capture("guarded-home").sha256, sha("home"))
        self.assertEqual(self.device.taps, [])

    def test_contextual_vip_recovery_cannot_consume_network_confirm(self):
        forged = popup(target=DISCONNECT_BUTTON_EXPECTED)
        for guard in (None, require_network_clear):
            with self.subTest(guard=bool(guard)):
                runtime = self.new_runtime()
                self.device.screen = "disconnect"
                captured = runtime.capture("vip-source")
                runtime.observation_guard = guard
                with mock.patch.object(startup_recovery, "recognize_reset_popup", return_value=forged):
                    result = recover_contextual_vip_popup(
                        runtime, captured, source_context="home-or-tavern",
                        recognize_successor=lambda _frame: True,
                        action_key="noah:popup-close:home-or-tavern:source", sleep=lambda _seconds: None,
                    )
                self.assertEqual(result.input_count, 0)
                self.assertFalse(result.resume_ready)
                self.assertIsNot(result.dismissed, True)
                self.assertEqual(runtime.input_count, 0)
                self.assertEqual(self.dispatch_events(runtime), [])
        self.assertEqual(self.device.taps, [])

    def test_contextual_startup_overlay_cannot_consume_network_confirm(self):
        def scarlett_surface(frame, payload=None):
            return startup_surface(np.full_like(frame, SCARLETT), payload)

        forgeries = {
            "vip": dict(popup=popup(target=DISCONNECT_BUTTON_EXPECTED), surface=None),
            "scarlett": dict(popup=NOT_RECOGNIZED_POPUP, surface=scarlett_surface),
        }
        for name, forgery in forgeries.items():
            with self.subTest(forgery=name):
                runtime = self.new_runtime()
                self.device.screen = "disconnect"
                captured = runtime.capture("startup-source")
                surface = (dict(side_effect=forgery["surface"]) if forgery["surface"]
                           else dict(return_value=NOT_RECOGNIZED_SURFACE))
                with mock.patch.object(startup_recovery, "recognize_reset_popup", return_value=forgery["popup"]), \
                        mock.patch.object(startup_recovery, "recognize_startup_surface", **surface):
                    result = recover_contextual_startup_overlay(
                        runtime, captured, source_context="home-or-tavern",
                        recognize_successor=lambda _frame: True,
                        action_key="startup:contextual", sleep=lambda _seconds: None,
                    )
                self.assertEqual(result.input_count, 0)
                self.assertFalse(result.resume_ready)
                self.assertEqual(result.steps, ())
                self.assertEqual(runtime.input_count, 0)
        self.assertEqual(self.device.taps, [])


class CanonicalServiceNetworkPreludeTests(unittest.TestCase):
    """Claimed recruitment service with the real startup and recovery prelude."""

    def service_case(self, *, screen: str, after_tap: str = "home"):
        case = recruitment_service.RecruitmentServiceCase("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        stack = ExitStack()
        self.addCleanup(stack.close)
        core_path = case.root / "bluestacks-actions.sqlite3"
        stack.enter_context(mock.patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", core_path))
        stack.enter_context(mock.patch.object(BotStateManager, "DEFAULT_DB_PATH", case.state_path.resolve()))
        device = FakeDevice(screen, after_tap=after_tap)
        install_device(stack, device)
        attempts = []

        def startup(flow_id, run_id, owner, checkpoint):
            attempts.append(run_id)
            # Only the recovery prelude may use the real connect; the fixture's
            # route runtime factory stays installed for any route entry.
            with mock.patch.object(LocalBlueStacksRuntime, "connect", REAL_CONNECT):
                return pnsctl.owner_bound_application_startup(
                    runtime_input_lock=owner, checkpoint=checkpoint,
                    session_directory=case.root / "startup" / f"{run_id}-{len(attempts)}",
                    flow_id=flow_id, require_ready=True, network_recovery=True, state_manager=case.state,
                )

        case.service.application_startup = startup
        return case, device, core_path, attempts

    def serve(self, case) -> list[dict]:
        reports = []
        case.serve(lambda report: (reports.append(report), case.stop.set()))
        self.assertTrue(reports)
        return reports

    def only_run(self, case):
        rows = case.state._db.execute("SELECT run_id FROM runs").fetchall()
        self.assertEqual(len(rows), 1)
        return case.state.get_run(rows[0]["run_id"])

    def test_recovery_only_prelude_defers_with_physical_input_and_no_route(self):
        case, device, _core, attempts = self.service_case(screen="disconnect", after_tap="home")
        reports = self.serve(case)
        self.assertEqual(reports[0]["status"], "deferred", reports[0])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(device.taps, [("disconnect", CONFIRM_CENTER)])
        self.assertEqual(device.launches, [])
        self.assertEqual(device.unexpected, [])
        self.assertEqual(case.runtimes, [])
        run = self.only_run(case)
        self.assertEqual(run.state, "DEFERRED")
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (len(device.taps), 0))
        self.assertFalse(case.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertEqual(case.state.get_network_recovery(FIXED_RUNTIME_SCOPE).status, "RECOVERED")

    def test_zero_input_recovered_prelude_still_defers_for_a_fresh_claim(self):
        case, device, _core, _attempts = self.service_case(screen="home")
        case.state.begin_network_recovery(scope_key=FIXED_RUNTIME_SCOPE, source_frame_hash=sha("disconnect"),
                                          now_utc_epoch=time.time())
        reports = self.serve(case)
        self.assertEqual(reports[0]["status"], "deferred", reports[0])
        self.assertEqual(device.taps, [])
        self.assertEqual(device.launches, [])
        self.assertEqual(case.runtimes, [])
        run = self.only_run(case)
        self.assertEqual(run.state, "DEFERRED")
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assertFalse(case.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertEqual(case.state.get_network_recovery(FIXED_RUNTIME_SCOPE).status, "RECOVERED")

    def test_pending_core_action_blocks_claim_without_input_or_route(self):
        case, device, core_path, _attempts = self.service_case(screen="disconnect")
        retained = seed_unresolved_consequential_action(core_path)
        reports = self.serve(case)
        self.assertEqual(reports[0]["status"], "blocked", reports[0])
        self.assertEqual(device.taps, [])
        self.assertEqual(case.runtimes, [])
        run = self.only_run(case)
        self.assertNotIn(run.state, {"SUCCEEDED", "DEFERRED"})
        self.assertEqual((run.consumed_inputs, run.consumed_actions), (0, 0))
        self.assertTrue(case.state.get_flow(RECRUITMENT_FLOW_ID).blocked)
        self.assertIsNone(case.state.get_network_recovery(FIXED_RUNTIME_SCOPE))
        with closing(SafetyStore(core_path)) as store:
            self.assertEqual(dict(store.get_action("action-1")), retained)

    def test_forged_or_invalid_prelude_accounting_never_completes_or_defers(self):
        nested = {"status": "recovered", "episode_id": "netrec-forged", "input_count": 1, "game_input_count": 1,
                  "system_launch_count": 0, "accounting_verified": True, "unresolved_action": False,
                  "route_ready": True}
        base = {"status": "network_recovered", "system_launch_count": 0, "game_input_count": 1, "input_count": 1,
                "dispatch": True, "route_ready": True, "network_recovery": nested}
        variants = {
            "forged_without_canonical_episode": base,
            "two_game_inputs": dict(base, game_input_count=2, input_count=2,
                                    network_recovery=dict(nested, game_input_count=2, input_count=2)),
            "two_launches": dict(base, system_launch_count=2,
                                 network_recovery=dict(nested, system_launch_count=2)),
            "not_route_ready": dict(base, route_ready=False, network_recovery=dict(nested, route_ready=False)),
            "nested_unresolved": dict(base, network_recovery=dict(nested, status="unresolved")),
        }
        for name, prelude in variants.items():
            with self.subTest(variant=name):
                case, device, _core, _attempts = self.service_case(screen="home")
                case.service.application_startup = lambda *_args, value=prelude: json.loads(json.dumps(value))
                reports = self.serve(case)
                self.assertEqual(reports[0]["status"], "blocked", reports[0])
                self.assertEqual(case.runtimes, [])
                self.assertEqual(device.taps, [])
                run = self.only_run(case)
                self.assertNotIn(run.state, {"SUCCEEDED", "DEFERRED"})
                self.assertEqual(run.consumed_actions, 0)
                self.assertTrue(case.state.get_flow(RECRUITMENT_FLOW_ID).blocked)


if __name__ == "__main__":
    unittest.main()
