"""Offline claimed application startup boundary tests."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import pnsctl
from scripts import navigation_development_boundary as boundary
from tests.test_development_launch_game import _frame


class Lock:
    owner = "automation-service"
    invocation_id = "test"
    def assert_held(self, owner, invocation):
        if (owner, invocation) != (self.owner, self.invocation_id):
            raise RuntimeError("lost lock")


class ApplicationStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checkpoints = 0
        self.lock = Lock()
        self.gate = patch.object(boundary, "require_canonical_unresolved_clear")
        self.gate.start(); self.addCleanup(self.gate.stop)
    def checkpoint(self):
        self.checkpoints += 1
    def observe(self, package):
        frame = _frame()
        return {"device_state": "device", "foreground_package": package, "native_width": 800,
                "native_height": 1280, "frame_sha256": "a" * 64}, frame
    def run_start(self, observations, *, ready=True, **patches):
        calls = []
        def adb(*args):
            calls.append(args)
            if args[:4] == ("shell", "am", "start", "-W"):
                if patches.get("transport_error"):
                    raise RuntimeError("transport uncertain")
                return "started"
            package = patches.get("foreground", "com.global.ztmslg")
            return f"mCurrentFocus=Window{{1 u0 {package}/.MainActivity}}"
        plan = patches.get("plan", SimpleNamespace(status="clear", recovery_owner=None))
        with patch.object(pnsctl, "_development_launcher_observation", side_effect=observations), \
                patch.object(pnsctl, "_resolve_installed_game_activity", return_value=pnsctl.PACKAGE + "/.Main"), \
                patch.object(pnsctl, "_run_fixed_bluestacks_adb", side_effect=adb), \
                patch("scripts.startup_recovery.classify_startup_frame", return_value=plan), \
                patch("scripts.startup_normalization.is_clean_home_frame", return_value=ready), \
                patch("cv2.imdecode", return_value=object()):
            result = pnsctl.owner_bound_application_startup(runtime_input_lock=self.lock,
                checkpoint=self.checkpoint, session_directory=self.root / "evidence", flow_id="campaign", require_ready=True)
        return result, calls
    def test_existing_game_is_not_launched_and_current_context_owned_by_route(self):
        result, calls = self.run_start([self.observe(pnsctl.PACKAGE), self.observe(pnsctl.PACKAGE)])
        self.assertEqual(result["system_launch_count"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(result["status"], "already_foreground")
    def test_same_claim_retry_uses_new_directory_and_preserves_prior_evidence(self):
        from automation_service.cli import _application_startup_directory
        first = _application_startup_directory(self.root, "same-run")
        second = _application_startup_directory(self.root, "same-run")
        with patch.object(pnsctl, "_development_launcher_observation",
                          side_effect=[self.observe(pnsctl.PACKAGE)] * 4):
            for directory in (first, second):
                pnsctl.owner_bound_application_startup(runtime_input_lock=self.lock,
                    checkpoint=self.checkpoint, session_directory=directory,
                    flow_id="campaign", require_ready=True)
        self.assertNotEqual(first, second)
        self.assertTrue((first / "before.png").is_file())
        self.assertTrue((second / "before.png").is_file())
        self.assertEqual(json.loads((first / "result.json").read_text())["status"], "already_foreground")
        self.assertEqual(json.loads((second / "result.json").read_text())["status"], "already_foreground")

    def test_known_launcher_starts_once_only_after_immediate_source_and_retains_evidence(self):
        launcher = self.observe("com.uncube.launcher3")
        result, calls = self.run_start([launcher, launcher, self.observe(pnsctl.PACKAGE)])
        self.assertEqual(result["system_launch_count"], 1)
        self.assertEqual(len([c for c in calls if c[:3] == ("shell", "am", "start")]), 1)
        self.assertEqual(result["game_input_count"], 0)
        self.assertTrue(result["route_ready"])
        self.assertTrue((self.root / "evidence" / "immediate-before.png").is_file())
    def test_unknown_foreground_stops_before_launch(self):
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.run_start([self.observe("com.google.android.gms")])
        self.assertEqual(raised.exception.startup_result["system_launch_count"], 0)
    def test_ambiguous_transport_is_recorded_once_and_not_retried(self):
        launcher = self.observe("com.uncube.launcher3")
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.run_start([launcher, launcher], transport_error=True)
        self.assertEqual(raised.exception.startup_result["system_launch_count"], 1)
        retained = json.loads((self.root / "evidence" / "result.json").read_text())
        self.assertEqual(retained["transport_status"], "attempted")
        self.assertEqual(retained["game_input_count"], 0)
    def test_gms_after_launch_is_retained_and_stops_without_interaction(self):
        launcher = self.observe("com.uncube.launcher3")
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.run_start([launcher, launcher, self.observe("com.google.android.gms")],
                           foreground="com.google.android.gms")
        result = raised.exception.startup_result
        self.assertEqual(result["system_launch_count"], 1)
        self.assertEqual(result["game_input_count"], 0)
        self.assertEqual(result["after_observation"]["foreground_package"], "com.google.android.gms")
        self.assertTrue((self.root / "evidence" / "unexpected-foreground.png").is_file())

    def test_launcher_changes_before_dispatch_denies_system_start(self):
        launcher = self.observe("com.uncube.launcher3")
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.run_start([launcher, self.observe("com.google.android.gms")])
        self.assertEqual(raised.exception.startup_result["system_launch_count"], 0)

    def test_splash_does_not_prove_readiness(self):
        launcher = self.observe("com.uncube.launcher3")
        with patch.object(pnsctl.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
                self.run_start([launcher, launcher, self.observe(pnsctl.PACKAGE)], ready=False)
        self.assertEqual(raised.exception.startup_result["system_launch_count"], 1)
        self.assertFalse(raised.exception.startup_result["route_ready"])
    def test_known_owned_overlay_is_an_eligible_fresh_successor(self):
        launcher = self.observe("com.uncube.launcher3")
        plan = SimpleNamespace(status="recovery_required", recovery_owner="shared_home_startup_recovery")
        result, _ = self.run_start([launcher, launcher, self.observe(pnsctl.PACKAGE)], ready=False, plan=plan)
        self.assertEqual(result["readiness"], "known_startup_overlay")

    def test_checkpoint_loss_after_launcher_capture_prevents_launch(self):
        launcher = self.observe("com.uncube.launcher3")
        def stopped():
            self.checkpoints += 1
            if self.checkpoints == 6:
                raise RuntimeError("SERVICE_LEASE_LOST")
        self.checkpoint = stopped
        with self.assertRaises(pnsctl.ApplicationStartupError) as raised:
            self.run_start([launcher, launcher])
        self.assertEqual(raised.exception.startup_result["system_launch_count"], 0)
        self.assertIn("SERVICE_LEASE_LOST", str(raised.exception))

    def test_checkpoint_loss_prevents_any_observation(self):
        with patch.object(pnsctl, "_development_launcher_observation") as observe:
            with self.assertRaisesRegex(RuntimeError, "STOP"):
                pnsctl.owner_bound_application_startup(runtime_input_lock=self.lock,
                    checkpoint=lambda: (_ for _ in ()).throw(RuntimeError("STOP")),
                    session_directory=self.root / "evidence", require_ready=True)
            observe.assert_not_called()


class ClaimedServiceStartupTests(unittest.TestCase):
    def test_callback_runs_under_claim_and_marker_before_fake_route(self):
        from tests import test_service_recruitment as recruitment_tests
        from automation_service.registry import RECRUITMENT_FLOW_ID
        case = recruitment_tests.ServiceRecruitmentTests(methodName="test_native_pass_cooldown_restart_and_later_eligibility")
        case.setUp()
        self.addCleanup(case.doCleanups)
        seen = []
        def startup(flow_id, run_id, owner, checkpoint):
            owner.assert_held(owner.owner, owner.invocation_id)
            checkpoint()
            current = case.state.get_flow(flow_id)
            self.assertEqual(current.blocked_reason, f"EXECUTOR_INTERRUPTED_REQUIRES_INSPECTION:{run_id}")
            self.assertEqual(case.runtimes, [])
            seen.append(run_id)
            return {"status": "already_foreground", "system_launch_count": 0, "game_input_count": 0}
        case.service.application_startup = startup
        reports = []
        case.serve(lambda report: (reports.append(report), case.stop.set()))
        self.assertEqual(len(seen), 1)
        self.assertEqual(reports[0]["status"], "completed")
        self.assertEqual(reports[0]["result"]["system_launch_count"], 0)
        self.assertGreater(reports[0]["result"]["total_input_count"], 0)

    def test_startup_failure_preserves_attempt_and_never_calls_route(self):
        from tests import test_service_recruitment as recruitment_tests
        case = recruitment_tests.ServiceRecruitmentTests(methodName="test_native_pass_cooldown_restart_and_later_eligibility")
        case.setUp()
        self.addCleanup(case.doCleanups)
        def startup(*_args):
            raise pnsctl.ApplicationStartupError("ambiguous start", {"system_launch_count": 1,
                "game_input_count": 0, "status": "unresolved"})
        case.service.application_startup = startup
        reports = []
        case.serve(lambda report: (reports.append(report), case.stop.set()))
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertEqual(reports[0]["result"]["system_launch_count"], 1)
        self.assertEqual(case.runtimes, [])
        row = case.state._db.execute("SELECT consumed_inputs, consumed_actions FROM runs").fetchone()
        self.assertEqual(tuple(row), (0, 0))
