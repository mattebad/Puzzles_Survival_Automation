from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation_service.state import BotStateManager
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from tests.test_development_launch_game import _focus, _frame


class DevelopmentColdRestartTests(unittest.TestCase):
    def run_restart(self, *, clean_home=True, enabled=False, processes=None,
                    stop_error=False, startup_error=False, flow_enabled=False,
                    lease_owner=None, core_blocked=False, different_state=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            database = root / "state.sqlite3"
            with BotStateManager(database) as state:
                if enabled:
                    state.set_service_enabled(True)
                if flow_enabled:
                    from automation_service.registry import canonical_flow_specs
                    state.initialize_flows(canonical_flow_specs())
                    state.set_flow_enabled(pnsctl.CAMPAIGN_AP_FLOW_ID, True)
            stack.enter_context(patch.object(BotStateManager, "DEFAULT_DB_PATH", database))
            stack.enter_context(patch.dict(os.environ, {"AUTOMATION_SERVICE_STATE_PATH": str(root / "other.sqlite3" if different_state else database)}))
            if lease_owner:
                stack.enter_context(patch.object(BotStateManager, "get_service_lease", return_value=SimpleNamespace(owner_instance_id=lease_owner)))
            if core_blocked:
                stack.enter_context(patch.object(boundary, "require_canonical_unresolved_clear", side_effect=boundary.NavigationBoundaryError("canonical unresolved action")))
            stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"))
            stack.enter_context(patch.object(boundary, "CANONICAL_ACTION_STORE_PATH", root / "actions.sqlite3"))
            stack.enter_context(patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"))
            stack.enter_context(patch("cv2.imdecode", return_value=object()))
            stack.enter_context(patch("scripts.startup_normalization.is_clean_home_frame", return_value=clean_home))
            calls = []
            focus = pnsctl.PACKAGE

            def adb(*args, binary=False):
                nonlocal focus
                calls.append(args)
                if args == ("get-state",):
                    return "device"
                if args == ("exec-out", "screencap", "-p"):
                    return _frame()
                if args == ("shell", "dumpsys", "window"):
                    return _focus(focus)
                if args[:4] == ("shell", "cmd", "package", "resolve-activity"):
                    return pnsctl.PACKAGE + "/.MainActivity\n"
                if args == ("shell", "am", "force-stop", pnsctl.PACKAGE):
                    if stop_error:
                        raise pnsctl.OperatorError("transport outcome unknown")
                    focus = "com.uncube.launcher3"
                    return ""
                if args == ("shell", "ps", "-A"):
                    return processes if processes is not None else "USER PID NAME\nroot 1 init\n"
                raise AssertionError(args)

            def startup(**kwargs):
                kwargs["checkpoint"]()
                self.assertTrue(kwargs["runtime_input_lock"].held)
                if startup_error:
                    raise pnsctl.ApplicationStartupError("manual state", {"system_launch_count": 1})
                return {"status": "launched", "system_launch_count": 1,
                        "route_ready": True, "readiness": "clean_home"}

            stack.enter_context(patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb))
            launch = stack.enter_context(patch.object(pnsctl, "owner_bound_application_startup", side_effect=startup))
            error = None
            result = None
            try:
                result = json.loads(pnsctl.development_session_launch_game(live=True, yes=True, cold_restart=True))
            except pnsctl.OperatorError as exc:
                error = exc
            receipts = list((root / "sessions").glob("*/result.json"))
            retained = json.loads(receipts[0].read_text(encoding="utf-8")) if receipts else None
            # Ownership must be released on both success and every failure.
            with boundary.RuntimeInputLock(owner="verification", invocation_id="after-restart"):
                pass
            return result, error, calls, launch.call_count, retained

    def test_explicit_option_has_no_effect_on_normal_startup_default(self):
        args = pnsctl.parser().parse_args(["development-session", "launch-game", "--live", "--yes"])
        self.assertFalse(args.cold_restart)
        args = pnsctl.parser().parse_args(["development-session", "launch-game", "--live", "--yes", "--cold-restart"])
        self.assertTrue(args.cold_restart)

    def test_authorization_is_required_before_any_runtime_access(self):
        with patch.object(pnsctl, "_run_fixed_bluestacks_adb") as adb:
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_launch_game(live=True, yes=False, cold_restart=True)
            adb.assert_not_called()

    def test_single_stop_process_exit_and_owned_existing_startup(self):
        result, error, calls, launches, retained = self.run_restart()
        self.assertIsNone(error)
        self.assertEqual(result["status"], "cold_restarted")
        self.assertTrue(result["cold_stop_verified"])
        self.assertEqual((result["system_stop_count"], result["system_launch_count"], result["game_input_count"]), (1, 1, 0))
        self.assertEqual(calls.count(("shell", "am", "force-stop", pnsctl.PACKAGE)), 1)
        self.assertEqual(launches, 1)
        self.assertEqual(retained, result)

    def test_enabled_service_denies_all_device_access(self):
        _, error, calls, launches, _ = self.run_restart(enabled=True)
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(launches, 0)

    def test_enabled_flow_denies_all_device_access_even_with_service_off(self):
        _, error, calls, launches, _ = self.run_restart(flow_enabled=True)
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(launches, 0)

    def test_existing_service_owner_denies_all_device_access(self):
        _, error, calls, launches, _ = self.run_restart(lease_owner="existing-operator")
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(launches, 0)

    def test_pending_core_action_denies_all_device_access(self):
        _, error, calls, launches, _ = self.run_restart(core_blocked=True)
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(launches, 0)

    def test_alternate_empty_state_cannot_bypass_canonical_operator_checks(self):
        _, error, calls, launches, _ = self.run_restart(different_state=True)
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(launches, 0)

    def test_non_home_source_is_retained_without_stop_or_start(self):
        _, error, calls, launches, retained = self.run_restart(clean_home=False)
        self.assertIsNotNone(error)
        self.assertEqual(retained["system_stop_count"], 0)
        self.assertIn("before_observation", retained)
        self.assertNotIn(("shell", "am", "force-stop", pnsctl.PACKAGE), calls)
        self.assertEqual(launches, 0)

    def test_remaining_process_prevents_launch_without_identical_stop_retry(self):
        _, error, calls, launches, retained = self.run_restart(processes="USER PID NAME\nu0 45 " + pnsctl.PACKAGE + ":worker\n")
        self.assertIsNotNone(error)
        self.assertFalse(retained["cold_stop_verified"])
        self.assertEqual(calls.count(("shell", "am", "force-stop", pnsctl.PACKAGE)), 1)
        self.assertEqual(launches, 0)

    def test_unreadable_process_observation_prevents_launch(self):
        _, error, _, launches, _ = self.run_restart(processes="")
        self.assertIsNotNone(error)
        self.assertEqual(launches, 0)

    def test_uncertain_stop_is_not_retried_or_followed_by_launch(self):
        _, error, calls, launches, retained = self.run_restart(stop_error=True)
        self.assertIsNotNone(error)
        self.assertEqual(calls.count(("shell", "am", "force-stop", pnsctl.PACKAGE)), 1)
        self.assertEqual(launches, 0)
        self.assertEqual(retained["status"], "unresolved")

    def test_uncertain_startup_preserves_actual_launch_count_and_stops(self):
        _, error, calls, launches, retained = self.run_restart(startup_error=True)
        self.assertIsNotNone(error)
        self.assertTrue(retained["cold_stop_verified"])
        self.assertEqual(retained["system_launch_count"], 1)
        self.assertEqual(launches, 1)
        self.assertEqual(calls.count(("shell", "am", "force-stop", pnsctl.PACKAGE)), 1)


if __name__ == "__main__":
    unittest.main()
