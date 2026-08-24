from __future__ import annotations

import json
import inspect
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
from contextlib import contextmanager
import textwrap
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from scripts import navigation_development_boundary as boundary
from scripts import bluestacks_native_runtime as native_runtime
from scripts import pnsctl
from scripts.flow_delivery_troop_training_bluestacks import (
    FLOW_ID,
    MAX_DISPATCH_BEARING_CANARY_RUNS,
    MAX_INPUTS,
    RECOVERY_ID,
    RUNNER_ID,
    VALIDATOR_ID,
    recover_troop_training_consolidation,
    run_troop_training_consolidation,
    _prior_dispatch_bearing_runs,
    _verify_training_records,
    verify_troop_training_consolidation,
)
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.troop_training_bluestacks import (
    TroopTrainingRouteResult,
    TroopTrainingIntegratedRoute,
    TroopTrainingReturnHomeRoute,
)
from tasks.home_atlas import ZoomIdentity
from tasks.troop_training import (
    FACILITY_BY_TYPE,
    ResourceReading,
    TierObservation,
    TrainingConfig,
    TrainingScreenObservation,
    TroopTrainingConfig,
)


ROOT = Path(__file__).resolve().parents[1]

class TroopTrainingFlowDeliveryTests(unittest.TestCase):
    @contextmanager
    def _live_lease(self, root: Path, *, recovery_only: bool = False):
        digest = "1" * 64
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            session = boundary.DevelopmentSession(
                owner=f"pnsctl-development-session:{FLOW_ID}",
                invocation_id="troop-continuous",
                session_directory=root / "outer",
                max_inputs=MAX_INPUTS,
            )
            session.__enter__()
        (session.session_directory / "source.png").write_bytes(b"troop-initial")
        initial = boundary.DevelopmentInitialObservation(
            {"frame_sha256": digest},
            digest,
            frame_path="source.png",
            invocation_id=session.invocation_id,
        )
        session.set_initial_observation(initial)
        try:
            yield {
                "owner": session.owner,
                "development_session": session,
                "initial_observation": initial,
                "initial_frame_sha256": digest,
                "max_inputs": MAX_INPUTS,
                "troop_training_reset_identity": "reset",
                "troop_training_recovery_only": recovery_only,
            }
        finally:
            session.__exit__(None, None, None)
    def test_main_configures_troop_runtime_frame_age_without_changing_shared_default(self) -> None:
        runtime = SimpleNamespace(session=Path("mock-troop-training-session"), frame_max_age_seconds=30.0)
        result = TroopTrainingRouteResult(
            status="dry-run",
            reason="test",
            actions_completed=0,
            completed_claims=(),
            warehouse_approvals=(),
            resource_box_approvals=(),
            training=(),
            daily_progress={},
            final_home_recognized=False,
            entry_navigation={},
            session=str(runtime.session),
        )
        with patch.object(
            native_runtime.LocalBlueStacksRuntime,
            "connect",
            return_value=runtime,
        ), patch(
            "scripts.troop_training_bluestacks.TroopTrainingIntegratedRoute",
            return_value=SimpleNamespace(run=lambda: result),
        ), patch("scripts.troop_training_bluestacks._retain_route_result"):
            from scripts.troop_training_bluestacks import main

            self.assertEqual(
                main(["--adb", "mock-adb", "--serial", "mock-serial", "--reset-identity", "test"]),
                0,
            )
        self.assertEqual(runtime.frame_max_age_seconds, 45.0)
        self.assertEqual(
            inspect.signature(native_runtime.LocalBlueStacksRuntime.__init__)
            .parameters["frame_max_age_seconds"]
            .default,
            30.0,
        )

    def _invoke_train_with_fresh_observation(self, **fresh_changes):
        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("train-authorization-test")

            def __init__(self):
                self.inputs: list[tuple[str, tuple[int, int, int, int], str, str]] = []
                self.reconciliations: list[tuple[str, str]] = []

            def capture(self, _label):
                raise AssertionError("_train must use _capture_training for immediate-before")

            def tap(
                self,
                captured,
                *,
                target_identity,
                target_roi,
                action_key,
                consequential=False,
                continuation_of=None,
            ):
                del consequential, continuation_of
                self.inputs.append((target_identity, target_roi, action_key, captured.sha256))

            def reconcile(self, action_key, status, _captured, _reason):
                self.reconciliations.append((action_key, status))

        prior_frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        prior_capture = CapturedNativeFrame(
            prior_frame,
            b"prior",
            "a" * 64,
            0.0,
            Path("prior.png"),
        )
        fresh_frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        fresh_frame[100, 100, :] = 1
        fresh_capture = CapturedNativeFrame(
            fresh_frame,
            b"fresh",
            "b" * 64,
            1.0,
            Path("fresh.png"),
        )
        resources = tuple(
            ResourceReading(name, held=1000, required=100)
            for name in ("food", "wood", "steel", "gas")
        )
        tier = TierObservation(8, unlocked=True, selected=True, target_roi=(100, 800, 200, 900))
        before = TrainingScreenObservation(
            recognized=True,
            troop_type="shooter",
            facility_identity=FACILITY_BY_TYPE["shooter"],
            selected_tier=8,
            visible_tiers=(tier,),
            selected_quantity=250,
            resources=resources,
            normal_train_target=(100, 1050, 300, 1150),
            training_duration_seconds=3600,
            frame_sha256=prior_capture.sha256,
        )
        fresh_observation_values = {
            "normal_train_target": (220, 1060, 420, 1160),
            "frame_sha256": fresh_capture.sha256,
            **fresh_changes,
        }
        fresh_observation = replace(before, **fresh_observation_values)
        post_capture = CapturedNativeFrame(
            fresh_frame,
            b"post",
            "c" * 64,
            2.0,
            Path("post.png"),
        )
        after = TrainingScreenObservation(
            recognized=True,
            troop_type="shooter",
            facility_identity=FACILITY_BY_TYPE["shooter"],
            selected_tier=8,
            visible_tiers=(tier,),
            selected_quantity=250,
            resources=resources,
            normal_train_target=(100, 1050, 300, 1150),
            training_duration_seconds=3600,
            queue_active=True,
            queue_label="train t8 shooter x250",
            queue_troop_type="shooter",
            queue_tier=8,
            queue_quantity=250,
            frame_sha256=post_capture.sha256,
            diagnostics={"duration_source": "queue_band", "queue_spatially_associated": True},
        )
        runtime = Runtime()
        disabled = TrainingConfig(enabled=False, training_policy="disabled")
        config = TroopTrainingConfig(
            fighter=disabled,
            shooter=TrainingConfig(
                target_tier=8,
                quantity=250,
                training_policy="continuous",
            ),
            rider=disabled,
            vehicle=disabled,
        )
        route = TroopTrainingIntegratedRoute(
            runtime,
            config=config,
            reset_identity="test-reset",
            post_input_delay=0,
            persistence_path=Path("test-training-band-state.json"),
        )
        with patch.object(
            route,
            "_capture_training",
            side_effect=[(fresh_capture, fresh_observation), (post_capture, after)],
        ), patch(
            "scripts.troop_training_bluestacks.recognize_auto_use_resource_popup",
            return_value=SimpleNamespace(recognized=False),
        ):
            result = route._train(prior_capture, before, "shooter")
        return result, runtime, fresh_observation

    def test_train_authorization_uses_changed_but_semantically_exact_fresh_observation(self) -> None:
        result, runtime, fresh = self._invoke_train_with_fresh_observation()
        self.assertIsNone(result[2])
        self.assertEqual(len(runtime.inputs), 1)
        target_identity, target_roi, action_key, dispatch_hash = runtime.inputs[0]
        self.assertEqual(target_identity, "normal-train:shooter")
        self.assertEqual(target_roi, fresh.normal_train_target)
        self.assertIn(fresh.frame_sha256, action_key)
        self.assertEqual(dispatch_hash, fresh.frame_sha256)
        self.assertEqual(runtime.reconciliations[-1][1], "confirmed")

    def test_train_authorization_rejects_changed_semantics_before_dispatch(self) -> None:
        cases = (
            {"selected_tier": 7},
            {"selected_quantity": 249},
            {"overlay_state": "dialog"},
            {"normal_train_target": None},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                result, runtime, _fresh = self._invoke_train_with_fresh_observation(**changes)
                self.assertIsNotNone(result[2])
                self.assertEqual(runtime.inputs, [])

    def test_train_authorization_requires_fresh_recognized_requested_troop(self) -> None:
        for changes in ({"recognized": False}, {"troop_type": "fighter"}):
            with self.subTest(changes=changes):
                result, runtime, _fresh = self._invoke_train_with_fresh_observation(**changes)
                self.assertIsNotNone(result[2])
                self.assertEqual(runtime.inputs, [])

    def test_live_runner_invokes_checked_in_cli_subprocess_end_to_end(self) -> None:
        """Exercise the real child process boundary without connecting to BlueStacks."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "harness"
            script = harness / "scripts" / "troop_training_bluestacks.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                textwrap.dedent(
                    """
                    import json
                    from pathlib import Path
                    import sys

                    args = sys.argv[1:]
                    output = Path(args[args.index("--output-directory") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "frames").mkdir(exist_ok=True)
                    (output / "frames" / "0001-source.png").write_bytes(b"native")
                    (output / "events.jsonl").write_text(json.dumps({"type": "capture"}) + "\\n", encoding="utf-8")
                    (output / "argv.json").write_text(json.dumps(args), encoding="utf-8")
                    print(json.dumps({"status": "blocked", "session": str(output), "final_home_recognized": False}))
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            import scripts.flow_delivery_troop_training_bluestacks as delivery

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root / "artifacts"), patch.object(
                delivery, "REPO_ROOT", harness
            ):
                with self._live_lease(root, recovery_only=True) as lease:
                    result = json.loads(
                        run_troop_training_consolidation({}, lease, live=True)
                    )
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["recovery_only"])
            child = Path(result["session_directory"])
            retained = json.loads((child / "flow-delivery-result.json").read_text(encoding="utf-8"))
            self.assertEqual(retained["operator_returncode"], 0)
            argv = json.loads((child / "argv.json").read_text(encoding="utf-8"))
            self.assertIn("--return-home-only", argv)
            self.assertIn("--recovery-active-queue", argv)

    def test_preflight_failure_releases_session_without_runner_or_input(self) -> None:
        observed = {"runner": 0}

        def runner(*_args, **_kwargs):
            observed["runner"] += 1
            raise AssertionError("preflight failure must prevent runner invocation")

        observation = {
            "device_state": "device",
            "foreground_package": pnsctl.PACKAGE,
            "native_width": 800,
            "native_height": 1280,
            "frame_sha256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", (FLOW_ID,)), patch.object(
                pnsctl, "_load_bluestacks_flow_registry", return_value={FLOW_ID: {"runner": RUNNER_ID}}
            ), patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {RUNNER_ID: runner}), patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()), patch.object(
                pnsctl,
                "_development_runtime_observation",
                side_effect=pnsctl.OperatorError("preflight foreground mismatch"),
            ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                with self.assertRaisesRegex(pnsctl.OperatorError, "preflight foreground mismatch"):
                    pnsctl.development_session_run_flow(FLOW_ID, live=True, yes=True, max_inputs=4)
            summaries = list((root / "sessions").glob("*/summary.json"))
            self.assertEqual(len(summaries), 1)
            summary = json.loads(summaries[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["input_count"], 0)
            self.assertTrue(summary["ownership_released"])
            self.assertEqual(observed["runner"], 0)

    def test_live_runner_real_child_failure_retains_stderr_and_returncode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "harness"
            script = harness / "scripts" / "troop_training_bluestacks.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "import sys\nprint('child traceback', file=sys.stderr)\nsys.exit(7)\n",
                encoding="utf-8",
            )
            import scripts.flow_delivery_troop_training_bluestacks as delivery

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root / "artifacts"), patch.object(
                delivery, "REPO_ROOT", harness
            ):
                with self._live_lease(root, recovery_only=True) as lease:
                    with self.assertRaisesRegex(pnsctl.OperatorError, r"no JSON result \(returncode 7\)"):
                        run_troop_training_consolidation({}, lease, live=True)
            run_root = root / "outer" / "runtime"
            failure = json.loads((run_root / "operator-failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["operator_returncode"], 7)
            self.assertEqual((run_root / "operator-stderr.log").read_text(encoding="utf-8"), "child traceback\n")

    def test_recovery_exit_dialog_requires_active_queue_and_canonical_atlas(self) -> None:
        """Recovery may cancel safely, but must not claim completion from Home text alone."""

        class Runtime:
            session = Path("retained-recovery")

            def __init__(self) -> None:
                self.inputs: list[tuple[str, str]] = []
                self.frames = [
                    CapturedNativeFrame(np.zeros((1280, 800, 3), dtype=np.uint8), b"source", "s" * 64, 0.0, Path("source.png")),
                    CapturedNativeFrame(np.zeros((1280, 800, 3), dtype=np.uint8), b"final", "f" * 64, 1.0, Path("final.png")),
                ]

            def capture(self, _label: str) -> CapturedNativeFrame:
                return self.frames.pop(0)

            def tap(self, _frame: CapturedNativeFrame, *, target_identity: str, target_roi: object, action_key: str) -> None:
                del target_roi, action_key
                self.inputs.append(("tap", target_identity))

            def back(self, _frame: CapturedNativeFrame, *, action_key: str) -> None:
                self.inputs.append(("back", action_key))

        runtime = Runtime()
        with patch(
            "scripts.troop_training_bluestacks.recognize_exit_dialog",
            return_value=(True, (10, 10, 20, 20)),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_home",
            return_value=SimpleNamespace(recognized=True),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_training",
            return_value=SimpleNamespace(recognized=False),
        ), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer.localize",
            return_value=SimpleNamespace(recognized=False, zoom_identity=None),
        ):
            result = TroopTrainingReturnHomeRoute(runtime, require_active_queue=True).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(runtime.inputs, [])

    def test_recovery_exit_dialog_with_queue_still_requires_canonical_atlas(self) -> None:
        class Runtime:
            session = Path("retained-recovery")

            def __init__(self) -> None:
                self.inputs: list[str] = []
                self.frames = [
                    CapturedNativeFrame(np.zeros((1280, 800, 3), dtype=np.uint8), b"source", "s" * 64, 0.0, Path("source.png")),
                    CapturedNativeFrame(np.zeros((1280, 800, 3), dtype=np.uint8), b"final", "f" * 64, 1.0, Path("final.png")),
                ]

            def capture(self, _label: str) -> CapturedNativeFrame:
                return self.frames.pop(0)

            def tap(self, _frame: CapturedNativeFrame, *, target_identity: str, target_roi: object, action_key: str) -> None:
                del target_roi, action_key
                self.inputs.append(target_identity)

        runtime = Runtime()
        localizer = SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=False, zoom_identity=None))
        queue = SimpleNamespace(
            recognized=True,
            queue_active=True,
            queue_label="train t8 veteran x1000",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=1000,
            training_duration_seconds=45455,
            diagnostics={"duration_source": "queue_band", "queue_spatially_associated": True},
        )
        with patch(
            "scripts.troop_training_bluestacks.recognize_exit_dialog",
            return_value=(True, (10, 10, 20, 20)),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_training",
            return_value=queue,
        ), patch(
            "scripts.troop_training_bluestacks.recognize_home",
            return_value=SimpleNamespace(recognized=True),
        ), patch(
            "scripts.troop_training_bluestacks.load_home_atlas",
            return_value=object(),
        ), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer",
            return_value=localizer,
        ):
            result = TroopTrainingReturnHomeRoute(runtime, require_active_queue=True).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(runtime.inputs, ["exit-dialog-cancel"])

    def test_recovery_from_already_canonical_home_is_zero_input(self) -> None:
        class Runtime:
            session = Path("retained-recovery")

            def __init__(self) -> None:
                self.inputs: list[str] = []

            def capture(self, _label: str) -> CapturedNativeFrame:
                return CapturedNativeFrame(
                    np.zeros((1280, 800, 3), dtype=np.uint8),
                    b"home",
                    "h" * 64,
                    0.0,
                    Path("home.png"),
                )

            def tap(self, *_args, **_kwargs) -> None:
                self.inputs.append("tap")

            def back(self, *_args, **_kwargs) -> None:
                self.inputs.append("back")

        runtime = Runtime()
        home = SimpleNamespace(recognized=True)
        training = SimpleNamespace(recognized=False)
        localizer = SimpleNamespace(
            localize=lambda _frame: SimpleNamespace(
                recognized=True,
                zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
            )
        )
        with patch("scripts.troop_training_bluestacks.recognize_exit_dialog", return_value=(False, None)), patch(
            "scripts.troop_training_bluestacks.recognize_home", return_value=home
        ), patch("scripts.troop_training_bluestacks.recognize_training", return_value=training), patch(
            "scripts.troop_training_bluestacks.load_home_atlas", return_value=object()
        ), patch("scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=localizer):
            result = TroopTrainingReturnHomeRoute(runtime, require_active_queue=True).run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions_completed, 0)
        self.assertTrue(result.final_home_recognized)
        self.assertEqual(runtime.inputs, [])

    def test_retained_canonical_home_frame_has_spatial_hud_and_facility_proof(self) -> None:
        frame_path = ROOT / ".local-captures" / "flow-delivery" / FLOW_ID / "run-20260813T175557906902Z" / "troop-training-20260813T175558441756Z" / "frames" / "0003-return-home-final.png"
        if not frame_path.is_file():
            self.skipTest("retained post-recovery Home frame is unavailable")
        import cv2

        from tasks.troop_training_vision import recognize_home

        observation = recognize_home(cv2.imread(str(frame_path), cv2.IMREAD_COLOR))
        self.assertTrue(observation.recognized)
        self.assertEqual(set(observation.facilities), {"fighter", "shooter", "rider", "vehicle"})
        self.assertGreaterEqual(len(observation.diagnostics["home_hud_values"]), 3)

    def test_retained_recovery_home_proof_accepts_clipped_facility_labels(self) -> None:
        """HUD + canonical Atlas remain sufficient when a camera clips a label."""
        frame_path = ROOT / ".local-captures" / "flow-delivery" / FLOW_ID / "run-20260813T191910848863Z" / "troop-training-20260813T191911410733Z" / "frames" / "0003-return-home-final.png"
        if not frame_path.is_file():
            self.skipTest("retained clipped-label recovery Home frame unavailable")
        import cv2

        from scripts.troop_training_bluestacks import _canonical_home_proof
        from tasks.home_atlas import load_home_atlas
        from tasks.home_atlas_vision import BlueStacksHomeLocalizer
        from tasks.troop_training_vision import recognize_home, recognize_training

        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        atlas_path = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
        home = recognize_home(frame)
        training = recognize_training(frame)
        self.assertFalse(home.recognized)
        self.assertTrue(home.diagnostics["home_hud_signal"])
        self.assertFalse(training.recognized)
        localization = BlueStacksHomeLocalizer(load_home_atlas(atlas_path), atlas_path).localize(frame)
        self.assertTrue(localization.recognized)
        self.assertEqual(localization.zoom_identity.name, "FULLY_ZOOMED_OUT")
        self.assertTrue(_canonical_home_proof(frame, home, atlas_path, training=training))

    def test_checked_in_artifacts_define_unregistered_consolidation(self) -> None:
        queue = json.loads((ROOT / "tasks/flow_delivery_queue.json").read_text(encoding="utf-8"))
        flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
        self.assertEqual(flow["product_policy_status"], "supervised_consequential_validation")
        self.assertEqual(flow["maximum_live_attempts"], 1)
        self.assertIn("tests/test_flow_delivery_troop_training.py", flow["focused_tests"])
        policy = json.loads((ROOT / "tasks/flow_delivery_product_policy.json").read_text(encoding="utf-8"))
        row = next(item for item in policy["policies"] if item["policy_id"] == "troop-training-resource-policy")
        self.assertEqual(row["status"], "explicitly_approved")
        self.assertEqual(row["registration_status"], "NOT_REGISTERED")
        self.assertFalse(row["scheduler_eligibility"])

    def test_canary_authorization_and_input_counters_remain_independent(self) -> None:
        queue = json.loads((ROOT / "tasks/flow_delivery_queue.json").read_text(encoding="utf-8"))
        flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
        self.assertEqual(flow["live_authorization_count"], 1)
        self.assertIsNone(flow["physical_session_count"])
        self.assertEqual(flow["physical_session_count_status"], "unknown_not_derived")
        self.assertIn("not a separately derived", flow["physical_session_count_explanation"])
        self.assertEqual(flow["terminal_transport_input_count"], 10)
        self.assertEqual(flow["consequential_input_count"], 1)
        self.assertEqual(flow["recovery_input_count"], 0)
        self.assertIn("not summed", flow["input_accounting_scope"])
        self.assertFalse(queue["gameplay_scheduler"])

    def test_registry_and_pnsctl_handlers_are_fixed(self) -> None:
        registry = json.loads((ROOT / "tasks/flow_delivery_bluestacks_registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["flows"][FLOW_ID]["runner"], RUNNER_ID)
        self.assertIn(FLOW_ID, pnsctl.BLUESTACKS_FLOW_IDS)
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertIn(VALIDATOR_ID, pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS)
        self.assertIn(RECOVERY_ID, pnsctl._BLUESTACKS_RECOVERY_HANDLERS)

    def test_dry_run_is_bounded_and_does_not_dispatch(self) -> None:
        with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", ROOT / ".local-captures" / "test-flow-delivery"):
            result = json.loads(run_troop_training_consolidation({}, {"owner": "test", "max_inputs": 32}, live=False))
        self.assertEqual(result["flow_id"], FLOW_ID)
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["max_inputs"], 32)
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")


    def test_live_runner_rejects_sessionless_dispatch(self) -> None:
        with self.assertRaisesRegex(
            pnsctl.OperatorError, "active pnsctl-owned DevelopmentSession"
        ):
            run_troop_training_consolidation({}, {}, live=True)
    def test_recovery_is_observe_only(self) -> None:
        with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", ROOT / ".local-captures" / "test-flow-delivery"):
            result = json.loads(recover_troop_training_consolidation({}, {}))
        self.assertEqual(result["flow_id"], FLOW_ID)
        self.assertEqual(result["status"], "observed")
        self.assertFalse(result["dispatch"])

    def test_development_session_binds_reset_identity_and_input_bound_once(self) -> None:
        observed = {}

        def runner(queue, lease, *, live=True):
            del queue, live
            observed.update(lease)
            return json.dumps({"status": "dry_run", "flow_id": FLOW_ID, "dispatch": False, "session_directory": ""})

        observation = {
            "device_state": "device",
            "foreground_package": pnsctl.PACKAGE,
            "native_width": 800,
            "native_height": 1280,
            "frame_sha256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", (FLOW_ID,)), patch.object(
                pnsctl, "_load_bluestacks_flow_registry", return_value={FLOW_ID: {"runner": RUNNER_ID}}
            ), patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {RUNNER_ID: runner}), patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, b"png")
            ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                result = json.loads(
                    pnsctl.development_session_run_flow(FLOW_ID, live=False, yes=False, max_inputs=7)
                )
        self.assertEqual(result["max_inputs"], 7)
        self.assertEqual(observed["max_inputs"], 7)
        self.assertRegex(observed["troop_training_reset_identity"], r"^local-\d{4}-\d{2}-\d{2}-troop-training-consolidation$")

    def test_live_runner_requires_native_events_and_never_fabricates_bookkeeping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                flow_root = root / FLOW_ID

                def fake_run(command, **_kwargs):
                    output = Path(command[command.index("--output-directory") + 1])
                    frames = output / "frames"
                    frames.mkdir(parents=True)
                    (frames / "0001-source.png").write_bytes(b"native")
                    return CompletedProcess(command, 0, stdout=json.dumps({
                        "status": "completed", "session": str(output), "final_home_recognized": True,
                    }), stderr="")

                with patch.object(
                    __import__("scripts.flow_delivery_troop_training_bluestacks", fromlist=["subprocess"]).subprocess,
                    "run", side_effect=fake_run,
                ):
                    with self._live_lease(root) as lease:
                        with self.assertRaisesRegex(pnsctl.OperatorError, "native evidence"):
                            run_troop_training_consolidation({}, lease, live=True)
                self.assertFalse((flow_root / "events.jsonl").exists())
                self.assertFalse((flow_root / "ledger.jsonl").exists())
                self.assertFalse((flow_root / "journal.jsonl").exists())
                self.assertFalse((flow_root / "capability-audit.jsonl").exists())

    def test_live_runner_retains_child_failure_evidence_when_no_json_is_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                import scripts.flow_delivery_troop_training_bluestacks as delivery

                def fake_run(command, **_kwargs):
                    return CompletedProcess(command, 7, stdout="partial child output\n", stderr="child traceback\n")

                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root, recovery_only=True) as lease:
                        with self.assertRaisesRegex(pnsctl.OperatorError, "no JSON result"):
                            run_troop_training_consolidation({}, lease, live=True)
            run_root = root / "outer" / "runtime"
            failure = json.loads((run_root / "operator-failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["operator_returncode"], 7)
            self.assertTrue(failure["recovery_only"])
            self.assertEqual((run_root / "operator-stdout.log").read_text(encoding="utf-8"), "partial child output\n")
            self.assertEqual((run_root / "operator-stderr.log").read_text(encoding="utf-8"), "child traceback\n")

    def test_verifier_rejects_unbound_minimal_result(self) -> None:
        with self.assertRaisesRegex(pnsctl.OperatorError, "session directory"):
            from scripts.flow_delivery_troop_training_bluestacks import verify_troop_training_consolidation

            verify_troop_training_consolidation(
                {"result": {"flow_id": FLOW_ID, "troop_training_result": {"resolved_config": {}, "final_home_recognized": True}}, "session_directory": "fake"},
                {},
                {},
            )

    def test_live_canary_admission_allows_four_total_with_zero_prior_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("--output-directory") + 1])
                (output / "frames").mkdir(parents=True)
                (output / "frames" / "0001-source.png").write_bytes(b"native")
                (output / "events.jsonl").write_text(
                    json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
                )
                return CompletedProcess(
                    command,
                    3,
                    stdout=json.dumps(
                        {
                            "status": "blocked",
                            "session": str(output),
                            "final_home_recognized": False,
                        }
                    ),
                    stderr="",
                )

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                import scripts.flow_delivery_troop_training_bluestacks as delivery

                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            self.assertEqual(result["dispatch_count"], 0)

    def test_recovery_only_remains_permitted_after_one_prior_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / FLOW_ID / "run-prior"
            prior.mkdir(parents=True)
            (prior / "events.jsonl").write_text(
                json.dumps({"type": "dispatch", "action_key": "prior"}) + "\n",
                encoding="utf-8",
            )
            (prior / "flow-delivery-result.json").write_text(
                json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}),
                encoding="utf-8",
            )

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("--output-directory") + 1])
                (output / "frames").mkdir(parents=True)
                (output / "frames" / "0001-source.png").write_bytes(b"native")
                (output / "events.jsonl").write_text(
                    json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
                )
                return CompletedProcess(
                    command,
                    3,
                    stdout=json.dumps(
                        {
                            "status": "blocked",
                            "session": str(output),
                            "final_home_recognized": False,
                        }
                    ),
                    stderr="",
                )

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                import scripts.flow_delivery_troop_training_bluestacks as delivery

                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root, recovery_only=True) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            self.assertEqual(result["dispatch_count"], 0)

    def test_recovery_only_remains_permitted_after_two_prior_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal in range(2):
                prior = root / FLOW_ID / f"run-prior-{ordinal}"
                prior.mkdir(parents=True)
                (prior / "events.jsonl").write_text(
                    json.dumps({"type": "dispatch", "action_key": f"prior-{ordinal}"}) + "\n",
                    encoding="utf-8",
                )
                (prior / "flow-delivery-result.json").write_text(
                    json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}),
                    encoding="utf-8",
                )

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("--output-directory") + 1])
                (output / "frames").mkdir(parents=True)
                (output / "frames" / "0001-source.png").write_bytes(b"native")
                (output / "events.jsonl").write_text(
                    json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
                )
                return CompletedProcess(
                    command,
                    3,
                    stdout=json.dumps(
                        {
                            "status": "blocked",
                            "session": str(output),
                            "final_home_recognized": False,
                        }
                    ),
                    stderr="",
                )

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                import scripts.flow_delivery_troop_training_bluestacks as delivery

                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root, recovery_only=True) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            self.assertEqual(result["dispatch_count"], 0)

    def test_recovery_only_remains_permitted_after_three_prior_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal in range(3):
                prior = root / FLOW_ID / f"run-prior-{ordinal}"
                prior.mkdir(parents=True)
                (prior / "events.jsonl").write_text(
                    json.dumps({"type": "dispatch", "action_key": f"prior-{ordinal}"}) + "\n",
                    encoding="utf-8",
                )
                (prior / "flow-delivery-result.json").write_text(
                    json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}),
                    encoding="utf-8",
                )

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("--output-directory") + 1])
                (output / "frames").mkdir(parents=True)
                (output / "frames" / "0001-source.png").write_bytes(b"native")
                (output / "events.jsonl").write_text(
                    json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
                )
                return CompletedProcess(
                    command,
                    3,
                    stdout=json.dumps(
                        {
                            "status": "blocked",
                            "session": str(output),
                            "final_home_recognized": False,
                        }
                    ),
                    stderr="",
                )

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                import scripts.flow_delivery_troop_training_bluestacks as delivery

                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root, recovery_only=True) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            self.assertEqual(result["dispatch_count"], 0)

    def test_live_canary_admission_rejects_one_prior_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / FLOW_ID / "run-prior"
            prior.mkdir(parents=True)
            (prior / "events.jsonl").write_text(
                json.dumps({"type": "dispatch", "action_key": "prior"}) + "\n",
                encoding="utf-8",
            )
            (prior / "flow-delivery-result.json").write_text(
                json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}),
                encoding="utf-8",
            )
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                with self._live_lease(root) as lease:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "maximum-live-canary"):
                        run_troop_training_consolidation({}, lease, live=True)

    def test_live_canary_admission_uses_full_count_boundary(self) -> None:
        configured_max = MAX_DISPATCH_BEARING_CANARY_RUNS
        self.assertEqual(configured_max, 1)

        def fake_run(command, **_kwargs):
            output = Path(command[command.index("--output-directory") + 1])
            (output / "frames").mkdir(parents=True)
            (output / "frames" / "0001-source.png").write_bytes(b"native")
            (output / "events.jsonl").write_text(
                json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
            )
            return CompletedProcess(
                command,
                3,
                stdout=json.dumps(
                    {
                        "status": "blocked",
                        "session": str(output),
                        "final_home_recognized": False,
                    }
                ),
                stderr="",
            )

        for prior_count in (configured_max - 1, configured_max):
            with self.subTest(prior_count=prior_count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for ordinal in range(prior_count):
                    prior = root / FLOW_ID / f"run-prior-{ordinal}"
                    prior.mkdir(parents=True)
                    (prior / "events.jsonl").write_text(
                        json.dumps({"type": "dispatch", "action_key": f"prior-{ordinal}"}) + "\n",
                        encoding="utf-8",
                    )
                    (prior / "flow-delivery-result.json").write_text(
                        json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}),
                        encoding="utf-8",
                    )
                with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                    import scripts.flow_delivery_troop_training_bluestacks as delivery

                    if prior_count == configured_max:
                        with self._live_lease(root) as lease:
                            with self.assertRaisesRegex(pnsctl.OperatorError, "maximum-live-canary"):
                                run_troop_training_consolidation({}, lease, live=True)
                    else:
                        with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                            with self._live_lease(root) as lease:
                                result = json.loads(
                                    run_troop_training_consolidation({}, lease, live=True)
                                )
                        self.assertEqual(result["dispatch_count"], 0)

    def test_live_canary_admission_rejects_malformed_prior_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / FLOW_ID / "run-malformed"
            root.mkdir(parents=True)
            (root / "flow-delivery-result.json").write_text(
                json.dumps({"flow_id": FLOW_ID, "dispatch_count": "bad"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(pnsctl.OperatorError, "dispatch count is malformed"):
                _prior_dispatch_bearing_runs(root.parent)

    def test_live_canary_admission_rejects_symlink_prior_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / FLOW_ID / "run-symlink"
            root.mkdir(parents=True)
            target = root / "real-result.json"
            target.write_text(json.dumps({"flow_id": FLOW_ID}), encoding="utf-8")
            link = root / "flow-delivery-result.json"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("OS cannot create symlink for this test")
            with self.assertRaisesRegex(pnsctl.OperatorError, "result path is unsafe"):
                _prior_dispatch_bearing_runs(root.parent)

    def test_live_runner_forwards_session_input_bound_to_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured_env = {}
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                def fake_run(command, **kwargs):
                    captured_env.update(kwargs.get("env") or {})
                    output = Path(command[command.index("--output-directory") + 1])
                    frames = output / "frames"
                    frames.mkdir(parents=True)
                    (frames / "0001-source.png").write_bytes(b"native")
                    (output / "events.jsonl").write_text(json.dumps({"type": "capture"}) + "\n", encoding="utf-8")
                    return CompletedProcess(command, 3, stdout=json.dumps({
                        "status": "blocked", "session": str(output), "final_home_recognized": False,
                    }), stderr="")

                import scripts.flow_delivery_troop_training_bluestacks as delivery
                with patch.object(delivery.subprocess, "run", side_effect=fake_run):
                    with self._live_lease(root) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            self.assertEqual(result["max_inputs"], MAX_INPUTS)
            self.assertEqual(captured_env["PNS_DEVELOPMENT_MAX_INPUTS"], str(MAX_INPUTS))

    def test_recovery_runner_uses_only_return_home_command_and_bypasses_canary_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root):
                prior = root / FLOW_ID / "run-prior"
                prior.mkdir(parents=True)
                (prior / "events.jsonl").write_text(
                    json.dumps({"type": "dispatch", "action_key": "prior"}) + "\n", encoding="utf-8"
                )
                (prior / "flow-delivery-result.json").write_text(
                    json.dumps({"flow_id": FLOW_ID, "events_path": "events.jsonl", "dispatch": True}), encoding="utf-8"
                )

                def fake_run(command, **_kwargs):
                    output = Path(command[command.index("--output-directory") + 1])
                    frames = output / "frames"
                    frames.mkdir(parents=True)
                    (frames / "0001-source.png").write_bytes(b"native")
                    (output / "events.jsonl").write_text(
                        json.dumps({"type": "capture"}) + "\n", encoding="utf-8"
                    )
                    return CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps({"status": "completed", "session": str(output), "final_home_recognized": True}),
                        stderr="",
                    )

                import scripts.flow_delivery_troop_training_bluestacks as delivery

                with patch.object(delivery.subprocess, "run", side_effect=fake_run) as process:
                    with self._live_lease(root, recovery_only=True) as lease:
                        result = json.loads(
                            run_troop_training_consolidation({}, lease, live=True)
                        )
            command = process.call_args.args[0]
            self.assertIn("--return-home-only", command)
            self.assertIn("--recovery-active-queue", command)
            self.assertIn("--recovery-training-screen", command)
            self.assertNotIn("--fighter-tier", command)
            self.assertNotIn("--train", command)
            self.assertNotIn("--quantity-editor", command)
            self.assertFalse(any(token.endswith("-quantity") for token in command))
            self.assertFalse(any(token.endswith("-tier") for token in command))
            self.assertTrue(result["recovery_only"])
            self.assertFalse(result["dispatch"])

    def test_released_session_verify_uses_retained_troop_context(self) -> None:
        structure = {"result": {"flow_id": FLOW_ID}, "session_directory": "retained"}
        with patch.object(
            pnsctl,
            "_retained_flow_result",
            return_value=(Path("retained"), {"flow_id": FLOW_ID}),
        ), patch.object(
            pnsctl, "_load_flow_delivery_state", side_effect=pnsctl.OperatorError("released")
        ), patch.object(
            pnsctl, "_retained_troop_training_state", return_value=(
                {"active_flow_id": FLOW_ID},
                {"active_stage": "evidence_review"},
            )
        ), patch.object(
            pnsctl, "_load_bluestacks_flow_registry", return_value={FLOW_ID: {"evidence_validator": VALIDATOR_ID}}
        ), patch.object(
            pnsctl, "_verify_flow_structure", return_value=structure
        ), patch.dict(
            pnsctl._BLUESTACKS_EVIDENCE_VALIDATORS,
            {VALIDATOR_ID: lambda *_args: {"status": "evidence_required", "flow_id": FLOW_ID}},
        ):
            verdict = json.loads(pnsctl.bluestacks_verify_flow(Path("retained")))
        self.assertEqual(verdict["status"], "evidence_required")
        self.assertEqual(verdict["flow_id"], FLOW_ID)

    def test_released_session_recovery_reacquires_bounded_development_session(self) -> None:
        with patch.object(pnsctl, "_load_flow_delivery_state", side_effect=pnsctl.OperatorError("released")), patch.object(
            pnsctl, "_latest_troop_training_recovery_candidate", return_value=Path("retained")
        ), patch.object(
            pnsctl, "development_session_run_flow", return_value=json.dumps({"status": "blocked"})
        ) as run:
            result = json.loads(pnsctl.bluestacks_recover_home())
        self.assertEqual(result["status"], "blocked")
        run.assert_called_once_with(
            FLOW_ID,
            live=True,
            yes=True,
            max_inputs=MAX_INPUTS,
            recovery_only=True,
        )

    def test_unresolved_verifier_requires_and_retains_spatial_queue_proof(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            (session / "frames" / "post.png").write_bytes(b"native-post")
            frame_hash = __import__("hashlib").sha256(b"native-post").hexdigest()
            rows = [
                {
                    "type": "dispatch",
                    "consequential": True,
                    "action_key": "training:fighter:train",
                    "target_identity": "normal-train:fighter",
                },
                {
                    "type": "reconcile",
                    "status": "unresolved",
                    "action_key": "training:fighter:train",
                    "post_path": "frames/post.png",
                },
            ]
            route = {"status": "unresolved"}
            result = {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "blocked",
                "serial": pnsctl.BLUESTACKS_SERIAL,
                "native_width": 800,
                "native_height": 1280,
                "runtime_owner": "test",
                "terminal_runtime_state": "blocked",
                "actions": [],
                "frames": ["frames/post.png"],
                "required_artifacts": ["events_path"],
                "events_path": "events.jsonl",
                "ledger_path": None,
                "journal_path": None,
                "capability_audit_path": None,
                "dispatch": True,
                "dispatch_count": 1,
                "troop_training_result": route,
            }
            (session / "events.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            (session / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
            observation = SimpleNamespace(
                recognized=True,
                queue_active=True,
                queue_label="train t8 veteran x1000",
                queue_troop_type="fighter",
                queue_tier=8,
                queue_quantity=1000,
                training_duration_seconds=100,
                diagnostics={
                    "duration_source": "queue_band",
                    "queue_spatially_associated": True,
                    "queue_band": (90, 1040, 710, 1160),
                },
                frame_sha256=frame_hash,
            )
            with patch("cv2.imread", return_value=object()), patch(
                "tasks.troop_training_vision.recognize_training", return_value=observation
            ):
                verdict = verify_troop_training_consolidation(
                    {"result": result, "session_directory": str(session)}, {}, {}
                )
        self.assertEqual(verdict["status"], "evidence_required")
        self.assertEqual(verdict["queue_quantity"], 1000)
        self.assertEqual(verdict["duration_source"], "queue_band")

    def test_recovery_exit_dialog_without_queue_proof_fails_closed_before_cancel(self) -> None:
        from types import SimpleNamespace

        from scripts.troop_training_bluestacks import TroopTrainingReturnHomeRoute

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("retained-recovery")

            def capture(self, _label):
                return SimpleNamespace(frame=object(), sha256="a" * 64)

            def tap(self, *_args, **_kwargs):
                raise AssertionError("recovery must not cancel an obscuring dialog without queue proof")

        unknown_training = SimpleNamespace(
            recognized=False,
            queue_active=False,
            queue_label=None,
            queue_troop_type=None,
            queue_tier=None,
            queue_quantity=None,
            training_duration_seconds=None,
            diagnostics={},
        )
        with patch("scripts.troop_training_bluestacks.recognize_exit_dialog", return_value=(True, (1, 1, 10, 10))), patch(
            "scripts.troop_training_bluestacks.recognize_training", return_value=unknown_training
        ):
            result = TroopTrainingReturnHomeRoute(
                Runtime(),
                require_active_queue=True,
                radial_troop_type=None,
            ).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.actions_completed, 0)

    def test_queue_empty_training_recovery_uses_back_only_and_never_train_controls(self) -> None:
        """A recognized queue-empty training screen may only take bounded Back recovery."""
        from types import SimpleNamespace

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("retained-recovery")

            def __init__(self) -> None:
                self.frames = [
                    SimpleNamespace(frame=object(), sha256="s" * 64),
                    SimpleNamespace(frame=object(), sha256="f" * 64),
                    SimpleNamespace(frame=object(), sha256="h" * 64),
                ]
                self.inputs: list[tuple[str, object]] = []

            def capture(self, _label):
                return self.frames.pop(0)

            def back(self, _frame, *, action_key):
                self.inputs.append(("back", action_key))

            def tap(self, *_args, **_kwargs):
                self.inputs.append(("tap", _kwargs.get("target_identity")))

        empty_training = SimpleNamespace(
            recognized=True,
            queue_active=False,
            queue_label=None,
            queue_troop_type=None,
            queue_tier=None,
            queue_quantity=None,
            training_duration_seconds=3723,
            overlay_state="none",
            diagnostics={"duration_source": "normal_train_band"},
        )
        home = SimpleNamespace(recognized=False)
        final_home = SimpleNamespace(recognized=True)
        localizer = SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=True, zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT))
        runtime = Runtime()
        with patch("scripts.troop_training_bluestacks.recognize_exit_dialog", return_value=(False, None)), patch(
            "scripts.troop_training_bluestacks.recognize_home", side_effect=[home, final_home]
        ), patch("scripts.troop_training_bluestacks.recognize_training", return_value=empty_training), patch(
            "scripts.troop_training_bluestacks.load_home_atlas", return_value=object()
        ), patch("scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=localizer):
            result = TroopTrainingReturnHomeRoute(
                runtime,
                require_active_queue=True,
                allow_queue_empty_training=True,
                post_input_delay=0,
            ).run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions_completed, 1)
        self.assertEqual([kind for kind, _value in runtime.inputs], ["back"])

    def test_active_queue_recovery_with_radial_hint_uses_back_only_and_canonical_home(self) -> None:
        """A radial hint must not preempt exact active-queue recovery."""

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("active-queue-radial-recovery")

            def __init__(self) -> None:
                self.frames = [
                    SimpleNamespace(frame="source", sha256="s" * 64),
                    SimpleNamespace(frame="fresh", sha256="f" * 64),
                    SimpleNamespace(frame="final", sha256="h" * 64),
                ]
                self.inputs: list[tuple[str, object]] = []

            def capture(self, _label):
                return self.frames.pop(0)

            def back(self, captured, *, action_key):
                self.inputs.append(("back", action_key))

            def tap(self, *_args, **_kwargs):
                raise AssertionError("active-queue recovery must not use a tap")

        active_queue = SimpleNamespace(
            recognized=True,
            queue_active=True,
            queue_label="train t8 veteran x1000",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=1000,
            training_duration_seconds=45455,
            overlay_state="none",
            diagnostics={"duration_source": "queue_band", "queue_spatially_associated": True},
        )
        unknown_training = SimpleNamespace(recognized=False)
        home = SimpleNamespace(recognized=False)
        final_home = SimpleNamespace(recognized=True)
        localizer = SimpleNamespace(
            localize=lambda _frame: SimpleNamespace(
                recognized=True,
                zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
            )
        )
        recognizer_calls: list[tuple[str, str]] = []

        def observe_home(frame, *, reset_identity):
            self.assertEqual(reset_identity, "return-home")
            recognizer_calls.append(("home", frame))
            return {"source": home, "final": final_home}[frame]

        def observe_training(frame):
            recognizer_calls.append(("training", frame))
            return {"source": active_queue, "fresh": active_queue, "final": unknown_training}[frame]

        runtime = Runtime()
        with patch(
            "scripts.troop_training_bluestacks.recognize_exit_dialog",
            return_value=(False, None),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_radial_menu",
            return_value=SimpleNamespace(recognized=False),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_home",
            side_effect=observe_home,
        ), patch(
            "scripts.troop_training_bluestacks.recognize_training",
            side_effect=observe_training,
        ), patch(
            "scripts.troop_training_bluestacks.load_home_atlas",
            return_value=object(),
        ), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer",
            return_value=localizer,
        ):
            result = TroopTrainingReturnHomeRoute(
                runtime,
                require_active_queue=True,
                radial_troop_type="fighter",
                post_input_delay=0,
            ).run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions_completed, 1)
        self.assertTrue(result.final_home_recognized)
        self.assertEqual([kind for kind, _value in runtime.inputs], ["back"])
        self.assertEqual(
            recognizer_calls,
            [("home", "source"), ("training", "source"), ("training", "fresh"), ("home", "final")],
        )

    def test_fresh_recovery_uses_home_fallback_only_after_training_misses(self) -> None:
        class Runtime:
            session = Path("fresh-home-fallback")

            def __init__(self) -> None:
                self.frames = [
                    SimpleNamespace(frame="source", sha256="s" * 64),
                    SimpleNamespace(frame="fresh", sha256="f" * 64),
                ]
                self.inputs: list[str] = []

            def capture(self, _label):
                return self.frames.pop(0)

            def back(self, *_args, **_kwargs):
                self.inputs.append("back")

        active_queue = SimpleNamespace(
            recognized=True,
            queue_active=True,
            queue_label="train t8 veteran x1000",
            queue_troop_type="fighter",
            queue_tier=8,
            queue_quantity=1000,
            training_duration_seconds=45455,
            overlay_state="none",
            diagnostics={"duration_source": "queue_band", "queue_spatially_associated": True},
        )
        unknown_training = SimpleNamespace(recognized=False)
        home = SimpleNamespace(recognized=True)
        recognizer_calls: list[tuple[str, str]] = []

        def observe_home(frame, *, reset_identity):
            self.assertEqual(reset_identity, "return-home")
            recognizer_calls.append(("home", frame))
            return home

        def observe_training(frame):
            recognizer_calls.append(("training", frame))
            return {"source": active_queue, "fresh": unknown_training}[frame]

        localizer = SimpleNamespace(
            localize=lambda _frame: SimpleNamespace(
                recognized=True,
                zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
            )
        )
        with patch(
            "scripts.troop_training_bluestacks.recognize_training_speedup",
            return_value=False,
        ), patch(
            "scripts.troop_training_bluestacks.recognize_exit_dialog",
            return_value=(False, None),
        ), patch(
            "scripts.troop_training_bluestacks.recognize_home",
            side_effect=observe_home,
        ), patch(
            "scripts.troop_training_bluestacks.recognize_training",
            side_effect=observe_training,
        ), patch(
            "scripts.troop_training_bluestacks.load_home_atlas",
            return_value=object(),
        ), patch(
            "scripts.troop_training_bluestacks.BlueStacksHomeLocalizer",
            return_value=localizer,
        ):
            result = TroopTrainingReturnHomeRoute(
                Runtime(),
                require_active_queue=True,
                post_input_delay=0,
            ).run()

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions_completed, 0)
        self.assertEqual(
            recognizer_calls,
            [("home", "source"), ("training", "source"), ("training", "fresh"), ("home", "fresh")],
        )

    def test_queue_empty_training_recovery_without_explicit_allow_blocks_before_input(self) -> None:
        from types import SimpleNamespace

        class Runtime:
            session = Path("retained-recovery")
            in_flight_action = None

            def __init__(self) -> None:
                self.inputs: list[str] = []

            def capture(self, _label):
                return SimpleNamespace(frame=object(), sha256="s" * 64)

            def back(self, *_args, **_kwargs):
                self.inputs.append("back")

        empty_training = SimpleNamespace(
            recognized=True,
            queue_active=False,
            queue_label=None,
            queue_troop_type=None,
            queue_tier=None,
            queue_quantity=None,
            training_duration_seconds=3723,
            overlay_state="none",
            diagnostics={"duration_source": "normal_train_band"},
        )
        with patch("scripts.troop_training_bluestacks.recognize_exit_dialog", return_value=(False, None)), patch(
            "scripts.troop_training_bluestacks.recognize_home", return_value=SimpleNamespace(recognized=False)
        ), patch("scripts.troop_training_bluestacks.recognize_training", return_value=empty_training):
            runtime = Runtime()
            result = TroopTrainingReturnHomeRoute(runtime, require_active_queue=True, post_input_delay=0).run()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.actions_completed, 0)
        self.assertEqual(runtime.inputs, [])

    def test_queue_empty_training_recovery_back_only_proves_canonical_home(self) -> None:
        from scripts.troop_training_bluestacks import TroopTrainingReturnHomeRoute

        class Runtime:
            execute = True
            in_flight_action = None
            session = Path("queue-empty-recovery")

            def __init__(self):
                self.frames = [
                    SimpleNamespace(frame=object(), sha256="a" * 64),
                    SimpleNamespace(frame=object(), sha256="b" * 64),
                    SimpleNamespace(frame=object(), sha256="c" * 64),
                ]
                self.inputs = []

            def capture(self, _label):
                return self.frames.pop(0)

            def back(self, captured, *, action_key):
                self.inputs.append((captured.sha256, action_key))

        empty = SimpleNamespace(
            recognized=True,
            queue_active=False,
            queue_label=None,
            queue_troop_type=None,
            queue_tier=None,
            queue_quantity=None,
            training_duration_seconds=45455,
            overlay_state="none",
            diagnostics={"duration_source": "normal_train_band", "queue_spatially_associated": False},
        )
        home = SimpleNamespace(recognized=True)
        localizer = SimpleNamespace(localize=lambda _frame: SimpleNamespace(recognized=True, zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT))
        runtime = Runtime()
        with patch("scripts.troop_training_bluestacks.recognize_exit_dialog", return_value=(False, None)), patch(
            "scripts.troop_training_bluestacks.recognize_home", side_effect=[home, home, home]
        ), patch("scripts.troop_training_bluestacks.recognize_training", side_effect=[empty, empty, SimpleNamespace(recognized=False)]), patch(
            "scripts.troop_training_bluestacks.load_home_atlas", return_value=object()
        ), patch("scripts.troop_training_bluestacks.BlueStacksHomeLocalizer", return_value=localizer):
            result = TroopTrainingReturnHomeRoute(
                runtime,
                require_active_queue=True,
                allow_queue_empty_training=True,
                radial_troop_type=None,
            ).run()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions_completed, 1)
        self.assertTrue(result.final_home_recognized)
        self.assertEqual(len(runtime.inputs), 1)

    def _normal_train_verifier_fixture(self):
        frame_hash = "a" * 64
        troop_types = ("fighter", "shooter", "rider", "vehicle")
        config = {
            troop_type: {
                "enabled": True,
                "target_tier": 8 if troop_type in {"fighter", "shooter"} else 1,
                "quantity": 250,
                "quantity_mode": "fixed",
                "training_policy": "continuous",
                "allow_resource_boxes": troop_type in {"fighter", "vehicle"},
                "resolved_quantity": 250,
            }
            for troop_type in troop_types
        }
        resources = [{"name": name, "held": 1000, "required": 100} for name in ("food", "wood", "steel", "gas")]
        records = [
            {
                "troop_type": troop_type,
                "facility_identity": f"{troop_type}_camp",
                "selected_tier": config[troop_type]["target_tier"],
                "quantity": 250,
                "quantity_maximum": None,
                "maximum_equality_proven": False,
                "queue_label": f"{troop_type} queue",
                "queue_troop_type": troop_type,
                "queue_tier": config[troop_type]["target_tier"],
                "queue_quantity": 250,
                "displayed_training_duration_seconds": 3600,
                "duration_source": "queue_band",
                "queue_spatially_associated": True,
                "queue_roi": [90, 1040, 710, 1160],
                "resources_before": resources,
                "resources_after": resources,
                "source_frame_hash": frame_hash,
                "immediate_before_frame_hash": frame_hash,
                "immediate_post_frame_hash": frame_hash,
            }
            for troop_type in troop_types
        ]
        records[-1]["terminal_home_frame_hash"] = frame_hash
        route = {
            "resolved_config": config,
            "training": records,
            "entry_navigation": {
                "source_localization": {
                    "recognized": True,
                    "platform": "BlueStacks 5 / Android",
                    "profile_id": "pns-bluestacks-5-p64-800x1280-v1",
                    "zoom_identity": "fully_zoomed_out",
                    "screen_to_atlas": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "frame_sha256": frame_hash,
                },
                "final_binding": {"target_roi": [1, 2, 3, 4]},
                "radial_binding": {"recognized": True},
                "terminal_home_localization": {
                    "recognized": True,
                    "zoom_identity": "fully_zoomed_out",
                    "frame_sha256": frame_hash,
                },
                "terminal_home_frame_hash": frame_hash,
            },
        }
        return route, {frame_hash}, troop_types

    def test_verifier_rejects_completed_records_without_exact_normal_train_dispatches(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in troop_types[1:]
            ],
        ]
        with self.assertRaisesRegex(pnsctl.OperatorError, "normal Train dispatch"):
            _verify_training_records(route, frame_hashes, events)

    def test_verifier_rejects_duplicate_or_misordered_shared_tabs(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"normal-train:{troop_type}", "consequential": True}
                for troop_type in troop_types
            ],
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in ("vehicle", "shooter", "rider", "shooter")
            ],
        ]
        with self.assertRaisesRegex(pnsctl.OperatorError, "shared-tab processing order"):
            _verify_training_records(route, frame_hashes, events)

    def test_verifier_rejects_wrong_zoom_source_home_proof(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        route["entry_navigation"]["source_localization"]["zoom_identity"] = "zoomed_in"
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in troop_types[1:]
            ],
            *[
                {"type": "dispatch", "target_identity": f"normal-train:{troop_type}", "consequential": True}
                for troop_type in troop_types
            ],
        ]
        with self.assertRaisesRegex(pnsctl.OperatorError, "source Home localization"):
            _verify_training_records(route, frame_hashes, events)

    def test_verifier_accepts_continuous_claim_then_new_train_lifecycle(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        train = route["training"][0]
        claim = dict(train)
        claim.update(
            {
                "completion_policy": "completed_batch_claim_reconciled",
                "batch_identity": "fighter:reset:batch",
                "action_key": "fighter-claim-action",
                "daily_initiation_state": "not_started",
                "reset_identity": "reset",
            }
        )
        route["training"] = [claim, train, *route["training"][1:]]
        route["resolved_config"]["fighter"]["training_policy"] = "continuous"
        route["resolved_config"]["fighter"]["daily_initiation_state"] = "not_started"
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in troop_types[1:]
            ],
            {"type": "dispatch", "target_identity": "tab:fighter:claim-completed", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"normal-train:{troop_type}", "consequential": True}
                for troop_type in troop_types
            ],
        ]
        _verify_training_records(route, frame_hashes, events)

    def test_verifier_rejects_terminal_home_evidence_not_bound_to_final_record(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        terminal_hash = "b" * 64
        frame_hashes.add(terminal_hash)
        route["entry_navigation"]["terminal_home_localization"]["frame_sha256"] = terminal_hash
        route["entry_navigation"]["terminal_home_frame_hash"] = terminal_hash
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in troop_types[1:]
            ],
            *[
                {"type": "dispatch", "target_identity": f"normal-train:{troop_type}", "consequential": True}
                for troop_type in troop_types
            ],
        ]
        with self.assertRaisesRegex(pnsctl.OperatorError, "not bound to the final record"):
            _verify_training_records(route, frame_hashes, events)

    def test_verifier_accepts_only_resource_box_reconciled_train_retry(self) -> None:
        route, frame_hashes, troop_types = self._normal_train_verifier_fixture()
        events = [
            {"type": "dispatch", "target_identity": "facility:fighter", "consequential": False},
            *[
                {"type": "dispatch", "target_identity": f"tab:{troop_type}", "consequential": False}
                for troop_type in troop_types[1:]
            ],
            {"type": "dispatch", "target_identity": "normal-train:fighter", "consequential": True, "action_key": "fighter-train-1"},
            {"type": "reconcile", "action_key": "fighter-train-1", "status": "failed_confirmed", "reason": "resource boxes positively applied; queue remained empty and requires a new exact Train transaction"},
            {"type": "dispatch", "target_identity": "normal-train:fighter", "consequential": True, "action_key": "fighter-train-2"},
            {"type": "reconcile", "action_key": "fighter-train-2", "status": "confirmed", "reason": "active queue confirmed"},
            *[
                {"type": "dispatch", "target_identity": f"normal-train:{troop_type}", "consequential": True, "action_key": f"{troop_type}-train"}
                for troop_type in troop_types[1:]
            ],
        ]
        _verify_training_records(route, frame_hashes, events)

    def test_verifier_accepts_completed_once_daily_claim_without_new_transaction_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            frame = session / "frames" / "claim.png"
            frame.parent.mkdir()
            frame.write_bytes(b"native-claim")
            frame_hash = __import__("hashlib").sha256(frame.read_bytes()).hexdigest()
            disabled = {
                "enabled": False,
                "target_tier": None,
                "quantity": None,
                "quantity_mode": "fixed",
                "training_policy": "disabled",
                "allow_resource_boxes": False,
                "resolved_quantity": None,
                "daily_initiation_state": "not_started",
            }
            resolved = {
                "fighter": dict(disabled),
                "vehicle": dict(disabled),
                "rider": dict(disabled),
                "shooter": {
                    "enabled": True,
                    "target_tier": 8,
                    "quantity": 250,
                    "quantity_mode": "fixed",
                    "training_policy": "once_daily",
                    "allow_resource_boxes": False,
                    "resolved_quantity": None,
                    "daily_initiation_state": "initiated",
                },
            }
            claim = {
                "troop_type": "shooter",
                "facility_identity": "shooter_camp",
                "selected_tier": None,
                "quantity": None,
                "quantity_maximum": None,
                "maximum_equality_proven": False,
                "queue_label": None,
                "queue_troop_type": None,
                "queue_tier": None,
                "queue_quantity": None,
                "displayed_training_duration_seconds": None,
                "resources_before": [{"name": name, "held": 1000, "required": 100} for name in ("food", "wood", "steel", "gas")],
                "resources_after": [{"name": name, "held": 1000, "required": 100} for name in ("food", "wood", "steel", "gas")],
                "completion_policy": "completed_batch_claim_reconciled",
                "batch_identity": "shooter:reset:batch",
                "action_key": "shooter-claim-action",
                "daily_initiation_state": "initiated",
                "reset_identity": "reset",
                "source_frame_hash": frame_hash,
                "immediate_before_frame_hash": frame_hash,
                "immediate_post_frame_hash": frame_hash,
                "terminal_home_frame_hash": frame_hash,
                "terminal_home_recognized": True,
            }
            route = {
                "status": "completed",
                "final_home_recognized": True,
                "resolved_config": resolved,
                "training": [claim],
                "entry_navigation": {
                    "source_localization": {
                        "recognized": True,
                        "platform": "BlueStacks 5 / Android",
                        "profile_id": "pns-bluestacks-5-p64-800x1280-v1",
                        "zoom_identity": "fully_zoomed_out",
                        "screen_to_atlas": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "frame_sha256": frame_hash,
                    },
                    "final_binding": {"target_roi": [1, 2, 3, 4]},
                    "radial_binding": {"recognized": True},
                    "terminal_home_localization": {
                        "recognized": True,
                        "zoom_identity": "fully_zoomed_out",
                        "frame_sha256": frame_hash,
                    },
                    "terminal_home_frame_hash": frame_hash,
                },
            }
            result = {
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "status": "completed",
                "serial": pnsctl.BLUESTACKS_SERIAL,
                "native_width": 800,
                "native_height": 1280,
                "runtime_owner": "test",
                "terminal_runtime_state": "recognized_home",
                "actions": [],
                "frames": ["frames/claim.png"],
                "required_artifacts": ["events_path"],
                "events_path": "events.jsonl",
                "ledger_path": None,
                "journal_path": None,
                "capability_audit_path": None,
                "dispatch": False,
                "dispatch_count": 2,
                "max_inputs": 5,
                "troop_training_result": route,
            }
            (session / "events.jsonl").write_text(
                json.dumps({"type": "dispatch", "target_identity": "facility:shooter", "consequential": False})
                + "\n"
                + json.dumps({"type": "dispatch", "target_identity": "tab:shooter:claim-completed", "consequential": False})
                + "\n"
                + json.dumps({"type": "capture", "sha256": frame_hash})
                + "\n",
                encoding="utf-8",
            )
            (session / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
            verdict = verify_troop_training_consolidation(
                {"result": result, "session_directory": str(session), "frames": result["frames"]}, {}, {}
            )
            self.assertEqual(verdict["status"], "verified")


if __name__ == "__main__":
    unittest.main()
