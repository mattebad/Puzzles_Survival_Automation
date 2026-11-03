from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from safe_action_core import SafetyStore
from scripts.bluestacks_native_runtime import NATIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import BLUESTACKS_PACKAGE


def _frame(tag: bytes = b"frame") -> bytes:
    """Minimal native PNG header sufficient for the controller's bounds check."""

    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (800).to_bytes(4, "big")
        + (1280).to_bytes(4, "big")
        + tag
    )


def _focus(package: str) -> str:
    return f"mCurrentFocus=Window{{1 u0 {package}/.MainActivity}}\n"


class DevelopmentLaunchGameTests(unittest.TestCase):
    def _patch_runtime(self, root: Path):
        return (
            patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
            patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", root / "actions.sqlite3"),
            patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"),
        )

    def test_parser_exposes_explicit_bootstrap_command(self):
        args = pnsctl.parser().parse_args(
            ["development-session", "launch-game", "--live", "--yes"]
        )
        self.assertEqual(args.development_command, "launch-game")
        self.assertTrue(args.live)
        self.assertTrue(args.yes)

    def test_launch_requires_both_live_and_yes_before_acquiring_runtime(self):
        with patch.object(pnsctl, "_run_fixed_bluestacks_adb") as adb:
            with self.assertRaisesRegex(pnsctl.OperatorError, "--live --yes"):
                pnsctl.development_session_launch_game(live=True, yes=False)
            adb.assert_not_called()

    def test_launcher_start_has_one_system_launch_and_no_game_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_runtime(root)
            for item in patches:
                item.start()
            try:
                calls: list[tuple[tuple[object, ...], bool]] = []

                def adb(*args, binary=False):
                    calls.append((args, bool(binary)))
                    if args == ("get-state",):
                        return "device"
                    if args == ("exec-out", "screencap", "-p"):
                        return _frame()
                    if args == ("shell", "dumpsys", "window"):
                        # The first dump is launcher; the poll and after frame
                        # are the game.
                        dumps = [
                            _focus("com.bluestacks.launcher"),
                            _focus(BLUESTACKS_PACKAGE),
                            _focus(BLUESTACKS_PACKAGE),
                        ]
                        index = sum(
                            1
                            for call, _ in calls
                            if call == ("shell", "dumpsys", "window")
                        )
                        return dumps[index - 1]
                    if args == (
                        "shell",
                        "cmd",
                        "package",
                        "resolve-activity",
                        "--brief",
                        "-a",
                        "android.intent.action.MAIN",
                        "-c",
                        "android.intent.category.LAUNCHER",
                        BLUESTACKS_PACKAGE,
                    ):
                        return f"priority=0\n{BLUESTACKS_PACKAGE}/.MainActivity\n"
                    if args[:4] == ("shell", "am", "start", "-W"):
                        return "Starting: Intent {}\n"
                    raise AssertionError(args)

                with patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb):
                    result = json.loads(
                        pnsctl.development_session_launch_game(live=True, yes=True)
                    )
                self.assertEqual(result["status"], "launched")
                self.assertEqual(result["system_launch_count"], 1)
                self.assertEqual(result["game_input_count"], 0)
                icon_intent = json.loads((Path(__file__).parent / "fixtures/startup/bluestacks-icon-launch-intent-20261030.json").read_text(encoding="utf-8"))["intent"]
                launches = [call for call, _ in calls if call[:4] == ("shell", "am", "start", "-W")]
                self.assertEqual(launches, [(
                    "shell", "am", "start", "-W", "-a", icon_intent["action"],
                    "-c", icon_intent["category"], "-f", icon_intent["flags"],
                    "-n", BLUESTACKS_PACKAGE + "/.MainActivity",
                )])
                self.assertEqual(result["launch_intent"]["flags"], icon_intent["flags"])
                self.assertFalse(result["dispatch"])
                self.assertFalse(result["route_ready"])
                self.assertTrue(
                    all(call != ("shell", "am", "force-stop", BLUESTACKS_PACKAGE) for call, _ in calls)
                )
                session = Path(result["session_directory"])
                self.assertTrue((session / "before.png").is_file())
                self.assertTrue((session / "after.png").is_file())
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_existing_foreground_game_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_runtime(root)
            for item in patches:
                item.start()
            try:
                def adb(*args, binary=False):
                    if args == ("get-state",):
                        return "device"
                    if args == ("exec-out", "screencap", "-p"):
                        return _frame()
                    if args == ("shell", "dumpsys", "window"):
                        return _focus(BLUESTACKS_PACKAGE)
                    raise AssertionError(args)

                with patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb) as mocked:
                    result = json.loads(
                        pnsctl.development_session_launch_game(live=True, yes=True)
                    )
                self.assertEqual(result["status"], "already_foreground")
                self.assertEqual(result["system_launch_count"], 0)
                self.assertEqual(result["game_input_count"], 0)
                self.assertFalse(
                    any(call.args[:3] == ("shell", "am", "start") for call in mocked.call_args_list)
                )
            finally:
                for item in reversed(patches):
                    item.stop()


    def test_measured_bluestacks_gamecenter_source_can_start_without_force_stop(self):
        self.assert_launcher_starts_without_force_stop("com.bluestacks.gamecenter")

    def test_measured_uncube_launcher_source_can_start_without_game_input(self):
        self.assert_launcher_starts_without_force_stop("com.uncube.launcher3")

    def assert_launcher_starts_without_force_stop(self, launcher_package):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_runtime(root)
            for item in patches:
                item.start()
            try:
                calls: list[tuple[object, ...]] = []

                def adb(*args, binary=False):
                    calls.append(args)
                    if args == ("get-state",):
                        return "device"
                    if args == ("exec-out", "screencap", "-p"):
                        return _frame()
                    if args == ("shell", "dumpsys", "window"):
                        dumps = [
                            _focus(launcher_package),
                            _focus(BLUESTACKS_PACKAGE),
                            _focus(BLUESTACKS_PACKAGE),
                        ]
                        index = sum(
                            1 for call in calls if call == ("shell", "dumpsys", "window")
                        )
                        return dumps[index - 1]
                    if args[:4] == (
                        "shell",
                        "cmd",
                        "package",
                        "resolve-activity",
                    ):
                        return f"priority=0\n{BLUESTACKS_PACKAGE}/.MainActivity\n"
                    if args[:4] == ("shell", "am", "start", "-W"):
                        return "Starting: Intent {}\n"
                    raise AssertionError(args)

                with patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb):
                    result = json.loads(
                        pnsctl.development_session_launch_game(live=True, yes=True)
                    )
                self.assertEqual(result["status"], "launched")
                self.assertEqual(result["system_launch_count"], 1)
                self.assertEqual(result["game_input_count"], 0)
                self.assertNotIn(("shell", "am", "force-stop", BLUESTACKS_PACKAGE), calls)
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_unknown_foreground_is_blocked_before_resolve_or_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_runtime(root)
            for item in patches:
                item.start()
            try:
                def adb(*args, binary=False):
                    if args == ("get-state",):
                        return "device"
                    if args == ("exec-out", "screencap", "-p"):
                        return _frame()
                    if args == ("shell", "dumpsys", "window"):
                        return _focus("com.bluestacks.fake")
                    raise AssertionError(args)

                with patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb) as mocked:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "positively identified"):
                        pnsctl.development_session_launch_game(live=True, yes=True)
                calls = [call.args for call in mocked.call_args_list]
                self.assertFalse(any("resolve-activity" in call for call in calls))
                self.assertFalse(any("am" in call and "start" in call for call in calls))
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_resolved_activity_must_bind_exactly_to_puzzles_survival(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_runtime(root)
            for item in patches:
                item.start()
            try:
                def adb(*args, binary=False):
                    if args == ("get-state",):
                        return "device"
                    if args == ("exec-out", "screencap", "-p"):
                        return _frame()
                    if args == ("shell", "dumpsys", "window"):
                        return _focus("com.bluestacks.launcher")
                    if args[:4] == (
                        "shell",
                        "cmd",
                        "package",
                        "resolve-activity",
                    ):
                        return "priority=0\ncom.other.game/.MainActivity\n"
                    raise AssertionError(args)

                with patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb) as mocked:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "launcher activity"):
                        pnsctl.development_session_launch_game(live=True, yes=True)
                calls = [call.args for call in mocked.call_args_list]
                self.assertFalse(any("am" in call and "start" in call for call in calls))
            finally:
                for item in reversed(patches):
                    item.stop()

    def test_canonical_action_block_is_checked_before_runtime_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actions = root / "actions.sqlite3"
            store = SafetyStore(actions)
            try:
                store.connection.execute(
                    """
                    INSERT INTO actions(
                        action_id, action_key, task_id, semantic_action, source_state,
                        target_identity, target_roi_json, source_frame_sha256,
                        source_frame_captured_at, runtime_profile_id, game_day_id,
                        expected_postcondition, consequence, cost_type, cost_amount,
                        quantity, consequential, policy_request_json, policy_decision,
                        policy_reason, prepared_at, evidence_refs_json, final_status, updated_at
                    ) VALUES (
                        'block-1', 'block:1', 'synthetic', 'synthetic', 'HOME_BASE',
                        'synthetic', '[1,2,3,4]', ?, 1.0, ?, NULL,
                        'done', 'synthetic', 'none', 0, 1, 1, '{}', 'allow',
                        'seed', 1.0, '[]', 'prepared', 1.0
                    )
                    """,
                    ("b" * 64, NATIVE_RUNTIME_PROFILE_ID),
                )
                store.connection.commit()
            finally:
                store.close()
            patches = (
                patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"),
                patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", actions),
                patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"),
            )
            for item in patches:
                item.start()
            try:
                with patch.object(pnsctl, "_run_fixed_bluestacks_adb") as adb:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "canonical unresolved"):
                        pnsctl.development_session_launch_game(live=True, yes=True)
                    adb.assert_not_called()
            finally:
                for item in reversed(patches):
                    item.stop()


if __name__ == "__main__":
    unittest.main()
