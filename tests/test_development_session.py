from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts import flow_delivery_ruins_challenge_bluestacks as ruins_delivery
from automation_service import registry as registration
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
)
from scripts.startup_recovery import StartupRecoveryPlan


def disable_non_target_registrations(payload: dict, target_flow_id: str) -> None:
    disabled = {
        "production_handler": None,
        "profile": None,
        "supported_profiles": [],
        "mode": "disabled",
        "registration_status": "NOT_REGISTERED",
        "scheduler_eligible": False,
        "product_id": None,
        "product_revision": None,
    }
    for flow_id in payload["flows"]:
        if flow_id != target_flow_id:
            payload["flows"][flow_id] = dict(disabled)


def frame(label: str) -> CapturedNativeFrame:
    payload = label.encode()
    return CapturedNativeFrame(
        np.zeros((1280, 800, 3), np.uint8),
        payload,
        hashlib.sha256(payload).hexdigest(),
        time.monotonic(),
        Path(f"{label}.png"),
    )


class FakeRunner:
    def __init__(self) -> None:
        self.taps = []
        self.backs = 0

    def capture_png(self):
        import cv2

        ok, payload = cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))
        assert ok
        return payload.tobytes()

    def dispatch_tap(self, point):
        self.taps.append(point)

    def dispatch_back(self):
        self.backs += 1

    def dispatch_zoom_out(self):
        self.backs += 1


class DevelopmentSessionTests(unittest.TestCase):
    def test_continuous_session_binds_initial_memory_and_effect_unknown_reconciliation(self):
        initial_payload = b"initial-observation"
        initial_hash = hashlib.sha256(initial_payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="continuous-owner",
                    invocation_id="continuous-1",
                    session_directory=root / "session",
                    max_inputs=1,
                ) as session:
                    typed = session.set_initial_observation(
                        {
                            "frame_sha256": initial_hash,
                            "native_width": 800,
                            "native_height": 1280,
                        }
                    )
                    self.assertIsInstance(typed, boundary.DevelopmentInitialObservation)
                    session.remember_control("direction", "forward")
                    with self.assertRaisesRegex(
                        boundary.DevelopmentSessionError, "nested DevelopmentSession"
                    ):
                        with boundary.DevelopmentSession(
                            owner="nested-owner",
                            invocation_id="nested-1",
                            session_directory=root / "nested",
                            max_inputs=1,
                        ):
                            pass
                    result = session.run_action(
                        action_class="owned_item_non_idempotent",
                        label="effect-unknown",
                        capture=lambda label: frame(label),
                        dispatch=lambda _source: None,
                        recognize=lambda _source: "unknown",
                    )
                    self.assertEqual(result.status, "effect_reconciliation_required")
                    self.assertEqual(session.input_count, 1)
            summary = json.loads((root / "session" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["initial_frame_sha256"], initial_hash)
            self.assertEqual(summary["control_memory"]["direction"], "forward")
            self.assertIn("effect reconciliation", summary["next_action"])

    def test_malformed_ruins_continuation_is_rejected_before_runtime_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text("{not-json", encoding="utf-8")
            with patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", (ruins_delivery.FLOW_ID,)), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={ruins_delivery.FLOW_ID: {"runner": ruins_delivery.RUNNER_ID}},
            ), patch.object(pnsctl, "_development_runtime_observation") as observe, patch.object(
                boundary, "DevelopmentSession"
            ) as session:
                with self.assertRaisesRegex(pnsctl.OperatorError, "continuation rejected"):
                    pnsctl.development_session_run_flow(
                        ruins_delivery.FLOW_ID,
                        live=False,
                        yes=False,
                        chests_only=True,
                        chest_continuation=checkpoint,
                    )
            observe.assert_not_called()
            session.assert_not_called()

    def test_valid_ruins_continuation_is_forwarded_with_bound_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text("{}", encoding="utf-8")
            observed_lease = {}

            def runner(queue, lease, *, live=True):
                observed_lease.update(lease)
                return json.dumps({"status": "dry_run", "flow_id": ruins_delivery.FLOW_ID, "dispatch": False})

            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": "0" * 64,
            }
            with patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", (ruins_delivery.FLOW_ID,)), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={ruins_delivery.FLOW_ID: {"runner": ruins_delivery.RUNNER_ID}},
            ), patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {ruins_delivery.RUNNER_ID: runner}), patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, b"png")
            ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"), patch(
                "tasks.ruins_challenge_continuation.load_continuation", return_value={"claims": []}
            ) as load:
                result = pnsctl.development_session_run_flow(
                    ruins_delivery.FLOW_ID,
                    live=False,
                    yes=False,
                    chests_only=True,
                    chest_continuation=checkpoint,
                )
            self.assertEqual(json.loads(result)["chest_continuation"], str(checkpoint))
            self.assertEqual(observed_lease["chest_continuation"], str(checkpoint))
            self.assertTrue(observed_lease["ruins_reset_identity"].startswith("local-"))
            self.assertIn(observed_lease["ruins_current_day"], {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
            load.assert_called_once()
            self.assertEqual(load.call_args.kwargs["expected_reset_identity"], observed_lease["ruins_reset_identity"])
            self.assertEqual(load.call_args.kwargs["expected_current_day"], observed_lease["ruins_current_day"])
            self.assertEqual(load.call_args.kwargs["expected_package_id"], observed_lease["ruins_package_id"])
            self.assertEqual(load.call_args.kwargs["expected_runtime_profile_id"], observed_lease["ruins_runtime_profile_id"])

    def test_ordinary_action_categories_include_complete_gameplay_classes(self):
        capabilities = {
            "navigation",
            "combat",
            "claim",
            "reward",
            "free_action",
            "recruitment",
            "resource_collection",
            "resource_spending",
            "zombie_lair",
            "zombie_attack",
            "challenge_confirmation",
            "healing",
            "training",
            "upgrade",
            "research",
            "maintenance",
            "in_game_currency",
            "recovery",
            "complete_flow",
        }
        self.assertTrue(capabilities.issubset(boundary.ORDINARY_DEVELOPMENT_CAPABILITIES))
        self.assertEqual(
            {boundary.validate_development_action(item) for item in capabilities},
            {boundary.ORDINARY_DEVELOPMENT_ACTION},
        )

    def test_session_acquires_releases_and_runs_multiple_actions_without_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "runtime-lock.sqlite3"
            session_path = root / "session"
            captures = iter((frame("a"), frame("b"), frame("c"), frame("d")))
            dispatched = []
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", lock_path):
                with boundary.DevelopmentSession(
                    owner="test",
                    invocation_id="test-1",
                    session_directory=session_path,
                    max_inputs=4,
                ) as session:
                    for action_class in ("navigation", "combat"):
                        result = session.run_action(
                            action_class=action_class,
                            label=action_class,
                            capture=lambda _label: next(captures),
                            dispatch=lambda source: dispatched.append(source.sha256),
                            recognize=lambda _source: "known",
                        )
                        self.assertEqual(result.status, "completed")
                    self.assertTrue(session._ownership.lock.held)
                self.assertFalse(session._ownership.lock.held)
            summary = json.loads((session_path / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["input_count"], 2)
            self.assertLessEqual(len(summary), 12)
            self.assertFalse(summary["lifecycle_state_created"])
            self.assertTrue(summary["ownership_released"])
            self.assertFalse((session_path / "journal.jsonl").exists())
            self.assertEqual(len(dispatched), 2)
            actions = [
                json.loads(line)
                for line in (session_path / "actions.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [row["action_class"] for row in actions],
                [boundary.ORDINARY_DEVELOPMENT_ACTION] * 2,
            )
            self.assertEqual(
                [row["requested_action"] for row in actions],
                ["navigation", "combat"],
            )

    def test_observe_only_creates_no_action_or_lifecycle_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="observer",
                    invocation_id="observe-1",
                    session_directory=root / "session",
                ) as session:
                    observed = session.observe(lambda _label: frame("observe"), label="observe")
                    self.assertEqual(observed.frame.shape[:2], (1280, 800))
            summary = json.loads((root / "session" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["input_count"], 0)
            self.assertEqual(summary["action_count"], 0)
            self.assertFalse((root / "session" / "actions.jsonl").exists())
            self.assertFalse((root / "session" / "journal.jsonl").exists())

    def test_pnsctl_zero_input_observation_releases_ownership_without_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = b"ordinary-observation"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }
            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                return_value=(observation, png),
            ) as observe, patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                result = json.loads(pnsctl.development_session_observe(max_inputs=0))

            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["input_count"], 0)
            self.assertFalse(result["lifecycle_state_created"])
            self.assertTrue(result["ownership_released"])
            observe.assert_called_once_with()
            session_directory = Path(result["session_directory"])
            summary = json.loads(
                (session_directory / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["input_count"], 0)
            self.assertEqual(summary["action_count"], 0)
            self.assertFalse(summary["lifecycle_state_created"])
            self.assertTrue(summary["ownership_released"])
            self.assertFalse((session_directory / "actions.jsonl").exists())
            self.assertFalse((session_directory / "journal.jsonl").exists())

    def test_pnsctl_negative_observation_rejects_before_session_acquisition(self):
        with patch.object(pnsctl, "_development_runtime_observation") as observe, patch.object(
            boundary, "DevelopmentSession"
        ) as session:
            with self.assertRaisesRegex(
                pnsctl.OperatorError, "ordinary observation requires max_inputs >= 0"
            ):
                pnsctl.development_session_observe(max_inputs=-1)
        observe.assert_not_called()
        session.assert_not_called()

    def test_pnsctl_observation_release_failure_cannot_return_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = b"ordinary-observation"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }
            created = {}

            class UnreleasedSession:
                def __init__(self, **kwargs):
                    self.session_directory = Path(kwargs["session_directory"])
                    lock = type("Lock", (), {"held": True})()
                    self._ownership = type(
                        "Ownership", (), {"lock": lock}
                    )()
                    self.terminal_status = None
                    created["session"] = self

                def __enter__(self):
                    self.session_directory.mkdir(parents=True, exist_ok=True)
                    return self

                def __exit__(self, *_args):
                    return None

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                return_value=(observation, png),
            ), patch.object(boundary, "DevelopmentSession", UnreleasedSession):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "ownership release is unproven"
                ):
                    pnsctl.development_session_observe(max_inputs=0)

            self.assertEqual(created["session"].terminal_status, "evidence_required")
            result = json.loads(
                (created["session"].session_directory / "result.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = json.loads(
                (created["session"].session_directory / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            for artifact in (result, summary):
                self.assertEqual(artifact["status"], "evidence_required")
                self.assertEqual(artifact["input_count"], 0)
                self.assertFalse(artifact["lifecycle_state_created"])
                self.assertFalse(artifact["ownership_released"])
            self.assertIn("ownership release is unproven", result["error"])
            self.assertIn("ownership release is unproven", summary["blocker"])

    def test_pnsctl_observation_checkpoint_mutation_cannot_return_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text("before", encoding="utf-8")
            png = b"ordinary-observation"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }

            def observe_and_mutate():
                checkpoint.write_text("after", encoding="utf-8")
                return observation, png

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", (checkpoint,)
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                side_effect=observe_and_mutate,
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "mutated a persistent checkpoint artifact"
                ):
                    pnsctl.development_session_observe(max_inputs=0)

            session_directories = tuple((root / "sessions").iterdir())
            self.assertEqual(len(session_directories), 1)
            session_directory = session_directories[0]
            result = json.loads(
                (session_directory / "result.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (session_directory / "summary.json").read_text(encoding="utf-8")
            )
            for artifact in (result, summary):
                self.assertEqual(artifact["status"], "evidence_required")
                self.assertEqual(artifact["input_count"], 0)
                self.assertFalse(artifact["lifecycle_state_created"])
                self.assertTrue(artifact["ownership_released"])
            self.assertIn("mutated a persistent checkpoint artifact", result["error"])
            self.assertIn("mutated a persistent checkpoint artifact", summary["blocker"])

    def test_home_zoom_does_not_require_atlas_localization(self):
        captures = iter((frame("zoom-before"), frame("zoom-after")))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="zoom",
                    invocation_id="zoom-1",
                    session_directory=root / "session",
                ) as session:
                    result = session.run_action(
                        action_class="navigation",
                        label="home-zoom-out",
                        capture=lambda _label: next(captures),
                        dispatch=lambda _source: None,
                        recognize=lambda _source: "HOME_BASE",
                    )
            self.assertEqual(result.status, "completed")

    def test_unknown_successor_uses_recovery_without_global_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = iter((frame("before"), frame("unknown"), frame("recovered")))
            states = iter(("unknown", "HOME_BASE"))
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="test",
                    invocation_id="recover-1",
                    session_directory=root / "session",
                ) as session:
                    result = session.run_action(
                        action_class="recovery",
                        label="recover",
                        capture=lambda _label: next(captures),
                        dispatch=lambda _source: None,
                        recognize=lambda _source: next(states),
                        recover=lambda _source: True,
                    )
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.recovery_used)
            summary = json.loads((root / "session" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["input_count"], 2)

    def test_unknown_successor_uses_zero_input_settled_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, immediate, settled = (
                frame("settled-before"),
                frame("settled-immediate"),
                frame("settled-successor"),
            )
            captures = iter((before, immediate, settled))
            labels: list[str] = []

            def capture(label: str) -> CapturedNativeFrame:
                labels.append(label)
                return next(captures)

            def recognize(source: CapturedNativeFrame) -> str:
                return "COMMANDER_INFO" if source is settled else "unknown"

            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="test",
                    invocation_id="settled-1",
                    session_directory=root / "session",
                    max_inputs=1,
                ) as session:
                    result = session.run_action(
                        action_class="navigation",
                        label="delayed-commander-entry",
                        capture=capture,
                        dispatch=lambda _source: None,
                        recognize=recognize,
                        settled_successor=lambda: session.observe(
                            capture, label="delayed-commander-entry-settled"
                        ),
                    )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.state, "COMMANDER_INFO")
            self.assertEqual(result.after_sha256, settled.sha256)
            self.assertEqual(session.input_count, 1)
            self.assertEqual(
                labels,
                [
                    "delayed-commander-entry-immediate-before",
                    "delayed-commander-entry-immediate-post",
                    "delayed-commander-entry-settled",
                ],
            )
            action = json.loads(
                (root / "session" / "actions.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(action["status"], "completed")
            self.assertEqual(action["state"], "COMMANDER_INFO")
            self.assertEqual(action["immediate_post_sha256"], immediate.sha256)
            self.assertEqual(action["settled_successor_sha256"], settled.sha256)
            self.assertEqual(action["after_sha256"], settled.sha256)

    def test_real_money_cash_mall_confirmation_is_rejected_before_dispatch(self):
        dispatched = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with boundary.DevelopmentSession(
                    owner="test",
                    invocation_id="cash-1",
                    session_directory=root / "session",
                ) as session:
                    with self.assertRaisesRegex(boundary.DevelopmentSessionError, "unsupported"):
                        session.run_action(
                            action_class=boundary.REAL_MONEY_CASH_MALL_CONFIRMATION,
                            label="cash",
                            capture=lambda _label: frame("cash"),
                            dispatch=lambda source: dispatched.append(source),
                            recognize=lambda _source: "known",
                        )
            self.assertEqual(dispatched, [])

    def test_runtime_multiple_actions_input_limit_and_cash_confirmation_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = FakeRunner()
            with patch.dict("os.environ", {"PNS_DEVELOPMENT_MAX_INPUTS": "2"}):
                runtime = LocalBlueStacksRuntime(runner, Path(directory) / "runtime", execute=True)
            source = runtime.capture("source")
            runtime.tap(
                source,
                target_identity="ordinary-claim",
                target_roi=(10, 10, 20, 20),
                action_key="claim-1",
                consequential=True,
            )
            post = runtime.capture("post")
            runtime.back(post, action_key="back-2")
            self.assertEqual(runner.backs, 1)
            final = runtime.capture("final")
            with self.assertRaisesRegex(RuntimeError, "input limit"):
                runtime.back(final, action_key="back-3")
        with tempfile.TemporaryDirectory() as directory:
            runner = FakeRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "runtime", execute=True)
            source = runtime.capture("source")
            with self.assertRaisesRegex(RuntimeError, "Cash Mall"):
                runtime.tap(
                    source,
                    target_identity="cash-mall-real-money-confirm",
                    target_roi=(10, 10, 20, 20),
                    action_key="payment",
                )
            self.assertEqual(runner.taps, [])
        with tempfile.TemporaryDirectory() as directory:
            runner = FakeRunner()
            runtime = LocalBlueStacksRuntime(runner, Path(directory) / "runtime", execute=True)
            source = runtime.capture("source")
            with self.assertRaisesRegex(RuntimeError, "Cash Mall"):
                runtime.tap(
                    source,
                    target_identity="Cash Mall buy with USD",
                    target_roi=(10, 10, 20, 20),
                    action_key="submit purchase",
                )
            self.assertEqual(runner.taps, [])

    def test_external_zoom_transport_is_accounted_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = FakeRunner()
            with patch.dict("os.environ", {"PNS_DEVELOPMENT_MAX_INPUTS": "1"}):
                runtime = LocalBlueStacksRuntime(runner, Path(directory) / "runtime", execute=True)
            source = runtime.capture("source")
            called = []
            runtime.dispatch_external_zoom(
                source,
                action_key="zoom-1",
                transport=lambda: called.append(True),
            )
            self.assertEqual(called, [True])
            rows = [json.loads(line) for line in runtime.events.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sum(row.get("type") == "dispatch" for row in rows), 1)
            with self.assertRaisesRegex(RuntimeError, "input limit"):
                runtime.dispatch_external_zoom(
                    runtime.capture("after"),
                    action_key="zoom-2",
                    transport=lambda: None,
                )

    def test_ruins_development_mode_omits_legacy_delivery_bookkeeping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_run(command, **_kwargs):
                self.assertIn("--chests-only", command)
                output = Path(command[command.index("--output-directory") + 1])
                child = output / "child"
                frames = child / "frames"
                frames.mkdir(parents=True)
                (frames / "0001-source.png").write_bytes(b"png")
                (child / "events.jsonl").write_text(
                    json.dumps({"type": "capture", "sha256": "a" * 64}) + "\n",
                    encoding="utf-8",
                )
                stdout = json.dumps(
                    {
                        "status": "blocked",
                        "reason": "recognition_needed",
                        "actions_completed": 0,
                    }
                )
                return CompletedProcess(command, 3, stdout=stdout, stderr="")

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root), patch.object(
                ruins_delivery.subprocess, "run", side_effect=fake_run
            ):
                result = json.loads(
                    ruins_delivery.run_ruins_challenge_home_atlas(
                        {},
                        {"owner": "test", "development_session": True, "chests_only": True},
                        live=True,
                    )
                )
            child = Path(result["session_directory"])
            self.assertEqual(result["status"], "blocked")
            self.assertFalse((child / "ledger.jsonl").exists())
            self.assertFalse((child / "capability-audit.jsonl").exists())
            self.assertFalse((child / "journal.jsonl").exists())
            delivery = json.loads(
                (child / "flow-delivery-result.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(delivery["ledger_path"])
            self.assertIsNone(delivery["capability_audit_path"])
            self.assertIsNone(delivery["journal_path"])

    def test_ruins_chest_evidence_validator_requires_exact_states_and_consistent_claims(self):
        identities = [
            "Hero Challenge", "Weapon Trial", "Tech Challenge", "Gear Challenge",
            "Core Challenge", "Nova Challenge", "Module Challenge", "Glory Challenge",
            "Bioenhancer Challenge", "Ultimate Challenge", "Chip Challenge", "Cube Challenge",
        ]
        coverage = {identity: "already claimed" for identity in identities}
        coverage["Nova Challenge"] = "newly claimed"
        structure = {
            "session_directory": "session",
            "actions": [],
            "result": {
                "flow_id": ruins_delivery.FLOW_ID,
                "terminal_runtime_state": "recognized_home",
                "resource_delta": 25,
                "ruins_result": {
                    "status": "completed",
                    "reason": "verified_safe_exit_to_home",
                    "chests_only": True,
                    "chest_coverage": coverage,
                    "newly_claimed_chests": [{"identity": "Nova Challenge", "ruins_medals": 25}],
                },
            },
        }
        queue = {"flows": [{"flow_id": ruins_delivery.FLOW_ID, "live_attempt_count": 0, "maximum_live_attempts": 14}]}
        verified = ruins_delivery.verify_ruins_challenge_home_atlas(structure, queue, {})
        self.assertEqual(verified["terminal"], "recognized_home")

        malformed = json.loads(json.dumps(structure))
        malformed["result"]["ruins_result"]["chest_coverage"]["Cube Challenge"] = None
        with self.assertRaisesRegex(pnsctl.OperatorError, "complete canonical identity coverage"):
            ruins_delivery.verify_ruins_challenge_home_atlas(malformed, queue, {})

        inconsistent = json.loads(json.dumps(structure))
        inconsistent["result"]["ruins_result"]["newly_claimed_chests"][0]["ruins_medals"] = 24
        with self.assertRaisesRegex(pnsctl.OperatorError, "malformed or inconsistent"):
            ruins_delivery.verify_ruins_challenge_home_atlas(inconsistent, queue, {})

        missing_claim = json.loads(json.dumps(structure))
        missing_claim["result"]["resource_delta"] = 0
        missing_claim["result"]["ruins_result"]["newly_claimed_chests"] = []
        with self.assertRaisesRegex(pnsctl.OperatorError, "malformed or inconsistent"):
            ruins_delivery.verify_ruins_challenge_home_atlas(missing_claim, queue, {})

    def test_pnsctl_shared_startup_recovery_preserves_split_ledger_and_post_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "child"
            child.mkdir()
            route_payload = {
                "type": "dispatch",
                "action_key": "route-action-1",
                "target_identity": "route-target",
                "source_sha256": "a" * 64,
                "execute": True,
            }
            (child / "events.jsonl").write_text(
                json.dumps(route_payload) + "\n", encoding="utf-8"
            )

            source = b"startup-source"
            post = b"post-recovery-home"
            observations = iter(
                [
                    (
                        {
                            "device_state": "device",
                            "foreground_package": pnsctl.PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(source).hexdigest(),
                        },
                        source,
                    ),
                    (
                        {
                            "device_state": "device",
                            "foreground_package": pnsctl.PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(post).hexdigest(),
                        },
                        post,
                    ),
                ]
            )

            plan = StartupRecoveryPlan(
                "recovery_required",
                "FLOW",
                "SCARLETT_THREE_DAY_PACK",
                "shared_startup_surface_recovery",
                False,
                "exact Scarlett startup surface requires shared recovery",
                surface_kind="full_page",
                frame_sha256=hashlib.sha256(source).hexdigest(),
                recognition={"recognized": True},
            )

            def runner(queue, lease, *, live=True):
                self.assertEqual(queue["active_flow_id"], "FLOW")
                self.assertEqual(lease["route_max_inputs"], 2)
                self.assertEqual(lease["startup_recovery_input_count"], 1)
                self.assertEqual(lease["startup_recovery_result"]["input_count"], 1)
                return json.dumps(
                    {
                        "status": "completed",
                        "session_directory": str(child),
                        "dispatch": live,
                    }
                )

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW",)
            ), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={"FLOW": {"runner": "runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner": runner}
            ), patch.object(
                pnsctl, "_development_runtime_observation", side_effect=observations
            ), patch.object(
                pnsctl,
                "_run_shared_startup_recovery",
                return_value={
                    "status": "surface_dismissed_successor_captured",
                    "input_count": 1,
                    "recovery_input_count": 1,
                    "route_input_count": 0,
                    "total_input_count": 1,
                },
            ), patch(
                "scripts.startup_recovery.classify_startup_frame",
                return_value=plan,
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                result = json.loads(
                    pnsctl.development_session_run_flow(
                        "FLOW", live=True, yes=True, max_inputs=3
                    )
                )

        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["route_input_count"], 1)
        self.assertEqual(result["recovery_input_count"], 1)
        self.assertEqual(result["total_input_count"], 2)
        self.assertEqual(result["initial_frame_sha256"], hashlib.sha256(post).hexdigest())

    def test_pnsctl_full_budget_recovery_reports_retained_input_without_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = b"scarlett-source"
            post = b"post-recovery-home"
            observations = iter(
                [
                    (
                        {
                            "device_state": "device",
                            "foreground_package": pnsctl.PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(source).hexdigest(),
                        },
                        source,
                    ),
                    (
                        {
                            "device_state": "device",
                            "foreground_package": pnsctl.PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(post).hexdigest(),
                        },
                        post,
                    ),
                ]
            )
            route_calls: list[object] = []

            def route(_queue, _lease, *, live=True):
                route_calls.append(live)
                raise AssertionError("route dispatch must be denied")

            plan = StartupRecoveryPlan(
                "recovery_required",
                "FLOW",
                "SCARLETT_THREE_DAY_PACK",
                "shared_startup_surface_recovery",
                False,
                "exact Scarlett startup surface requires shared recovery",
                surface_kind="full_page",
                frame_sha256=hashlib.sha256(source).hexdigest(),
                recognition={"recognized": True},
            )
            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW",)
            ), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={"FLOW": {"runner": "runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner": route}
            ), patch.object(
                pnsctl, "_development_runtime_observation", side_effect=observations
            ), patch.object(
                pnsctl,
                "_run_shared_startup_recovery",
                return_value={
                    "status": "surface_dismissed_successor_captured",
                    "reason": "positive_postcondition",
                    "input_count": 1,
                    "recovery_input_count": 1,
                    "route_input_count": 0,
                    "total_input_count": 1,
                },
            ), patch(
                "scripts.startup_recovery.classify_startup_frame",
                return_value=plan,
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                result = json.loads(
                    pnsctl.development_session_run_flow(
                        "FLOW", live=True, yes=True, max_inputs=1
                    )
                )

            self.assertEqual(route_calls, [])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_count"], 1)
            self.assertEqual(result["recovery_input_count"], 1)
            self.assertEqual(result["route_input_count"], 0)
            self.assertEqual(result["total_input_count"], 1)
            self.assertTrue(result["result"]["dispatch"])
            self.assertFalse(result["result"]["route_dispatch"])
            self.assertEqual(
                result["result"]["completion_scope"],
                "startup_recovery_only",
            )
            self.assertTrue(result["result"]["terminal_home_verified"])
            summary = json.loads(
                (Path(result["session_directory"]) / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["input_count"], 1)
            self.assertNotIn("blocker", summary)
            self.assertEqual(
                summary["next_action"],
                "startup recovery completed; route execution was intentionally not run",
            )

    def test_pnsctl_stops_on_unknown_commercial_successor_before_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = b"scarlett-source"
            post = b"commercial-successor"
            observation = lambda payload: {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(payload).hexdigest(),
            }
            observed = iter(((observation(source), source), (observation(post), post)))
            route_calls: list[object] = []

            def route(_queue, _lease, *, live=True):
                route_calls.append(live)
                raise AssertionError("route dispatch must be denied")

            plan = StartupRecoveryPlan(
                "recovery_required",
                "FLOW",
                "SCARLETT_THREE_DAY_PACK",
                "shared_startup_surface_recovery",
                False,
                "exact Scarlett startup surface requires shared recovery",
                surface_kind="full_page",
                frame_sha256=hashlib.sha256(source).hexdigest(),
                recognition={"recognized": True},
            )
            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW",)
            ), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={"FLOW": {"runner": "runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner": route}
            ), patch.object(
                pnsctl, "_development_runtime_observation", side_effect=observed
            ), patch.object(
                pnsctl,
                "_run_shared_startup_recovery",
                return_value={
                    "status": "evidence_required",
                    "reason": "evidence_required_unknown_scarlett_successor",
                    "input_count": 1,
                    "recovery_input_count": 1,
                    "route_input_count": 0,
                    "total_input_count": 1,
                },
            ), patch(
                "scripts.startup_recovery.classify_startup_frame",
                return_value=plan,
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                result = json.loads(
                    pnsctl.development_session_run_flow(
                        "FLOW", live=True, yes=True, max_inputs=3
                    )
                )

            self.assertEqual(route_calls, [])
            self.assertEqual(result["status"], "evidence_required")
            self.assertEqual(result["recovery_input_count"], 1)
            self.assertEqual(result["route_input_count"], 0)
            self.assertEqual(result["total_input_count"], 1)
            summary = json.loads(
                (Path(result["session_directory"]) / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["status"], "evidence_required")
            self.assertEqual(
                summary["blocker"], "evidence_required_unknown_scarlett_successor"
            )

    def test_pnsctl_flow_session_avoids_queue_and_preserves_checkpoint_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = tuple(root / name for name in ("BACKLOG.md", "queue.json", "handoff.md"))
            for path in checkpoints:
                path.write_text(path.name, encoding="utf-8")
            child = root / "child"
            child.mkdir()
            (child / "events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "dispatch",
                        "action_key": "dry-run",
                        "target_identity": "claim",
                        "source_sha256": "0" * 64,
                        "execute": False,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "dispatch",
                        "action_key": "claim-1",
                        "target_identity": "claim",
                        "source_sha256": "a" * 64,
                        "execute": True,
                    }
                )
                + "\n"
                + json.dumps(
                    {"type": "capture", "sha256": "b" * 64, "path": "post.png"}
                )
                + "\n",
                encoding="utf-8",
            )

            def runner(queue, lease, *, live=True):
                self.assertEqual(queue, {"active_flow_id": "FLOW", "development_session": True})
                self.assertEqual(lease["unresolved_action_state"], "not_applicable")
                self.assertEqual(
                    lease["startup_recovery_plan"]["status"],
                    "unclassified",
                )
                self.assertFalse(
                    lease["startup_recovery_plan"]["input_authority"],
                )
                return json.dumps(
                    {
                        "status": "blocked",
                        "reason": "recognition_needed",
                        "session_directory": str(child),
                        "dispatch": live,
                    }
                )

            png = b"png"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }
            with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", checkpoints
            ), patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW",)), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={"FLOW": {"runner": "runner"}},
            ), patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner": runner}), patch.object(
                pnsctl, "_development_runtime_observation", return_value=(observation, png)
            ), patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                result = json.loads(
                    pnsctl.development_session_run_flow(
                        "FLOW", live=True, yes=True, max_inputs=3
                    )
                )
            self.assertEqual(result["input_count"], 1)
            self.assertTrue(result["persistent_checkpoint_artifacts_unchanged"])
            summary = json.loads(
                (Path(result["session_directory"]) / "summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(summary["ownership_released"])
            self.assertEqual(
                summary["control_memory"]["startup_recovery_plan"]["status"],
                "unclassified",
            )
            self.assertIn("repair recognition or recovery", summary["next_action"])
            self.assertIn(str(child), summary["next_action"])
            action = json.loads(
                (Path(result["session_directory"]) / "actions.jsonl").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(action["action_class"], "ordinary_development")
            self.assertEqual(action["before_sha256"], "a" * 64)
            self.assertEqual(action["after_sha256"], "b" * 64)
            self.assertEqual(action["status"], "post_captured")

    def test_nova_live_admission_consumes_registration_before_runtime_and_rejects_repeat(
        self,
    ):
        flow_id = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            checked_in_registry = (
                Path(__file__).resolve().parents[1]
                / "tasks"
                / "flow_delivery_disabled_production_registry.json"
            )
            registry_payload = json.loads(
                checked_in_registry.read_text(encoding="utf-8")
            )
            disable_non_target_registrations(registry_payload, flow_id)
            registry_payload["flows"][flow_id] = {
                "production_handler": registration.NOVA_HANDLER_ID,
                "profile": registration.NOVA_PROFILE_ID,
                "supported_profiles": [registration.NOVA_PROFILE_ID],
                "mode": registration.NOVA_PHASE_MODE,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "product_id": registration.NOVA_PRODUCT_ID,
                "product_revision": registration.NOVA_PRODUCT_REVISION,
            }
            registry_path.write_text(json.dumps(registry_payload), encoding="utf-8")
            runtime_scope = "local-bluestacks-primary-login-slot-v1"
            account_id = "primary-account"
            server_id = "primary-server"
            reset_id = "game-day-2026-08-25"
            identity_evidence = root / "identity-evidence.json"
            identity_evidence.write_text(
                json.dumps(
                    {
                        "account_id": account_id,
                        "server_id": server_id,
                        "reset_id": reset_id,
                        "assurance": "supervised_navigation_binding",
                        "evidence_refs": ["primary-login-screen", "current-reset"],
                    }
                ),
                encoding="utf-8",
            )
            observed_lease = {}

            def runner(queue, lease, *, live=True):
                observed_lease.update(lease)
                self.assertTrue(live)
                self.assertIsInstance(
                    lease["registration_snapshot"],
                    registration.RegisteredDispatchSnapshot,
                )
                return json.dumps(
                    {
                        "status": "blocked",
                        "flow_id": flow_id,
                        "dispatch": False,
                    }
                )

            png = b"nova-admission"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }
            with patch.object(
                registration, "REGISTRY_PATH", registry_path
            ), patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "BLUESTACKS_FLOW_IDS", (flow_id,)
            ), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={flow_id: {"runner": "nova-runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS,
                {"nova-runner": runner},
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                return_value=(observation, png),
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                first = json.loads(
                    pnsctl.development_session_run_flow(
                        flow_id,
                        live=True,
                        yes=True,
                        max_inputs=8,
                        runtime_scope=runtime_scope,
                        account_id=account_id,
                        server_id=server_id,
                        reset_id=reset_id,
                        identity_evidence=identity_evidence,
                    )
                )
                self.assertEqual(first["status"], "blocked")
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "not registered"
                ):
                    pnsctl.development_session_run_flow(
                        flow_id,
                        live=True,
                        yes=True,
                        max_inputs=8,
                        runtime_scope=runtime_scope,
                        account_id=account_id,
                        server_id=server_id,
                        reset_id=reset_id,
                        identity_evidence=identity_evidence,
                    )
            self.assertIn("registration_snapshot", observed_lease)
            self.assertFalse(
                any(
                    entry.registered
                    for entry in registration.load_disabled_registry(registry_path)
                )
            )

    def test_ultimate_session_adopts_adapter_verified_nested_transport_count(self) -> None:
        flow_id = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime-child"
            child.mkdir()
            (child / "events.jsonl").write_text(
                json.dumps({"type": "post_flee_home_route", "flow_id": flow_id})
                + "\n",
                encoding="utf-8",
            )

            def runner(queue, lease, *, live=True):
                self.assertEqual(
                    queue,
                    {"active_flow_id": flow_id, "development_session": True},
                )
                self.assertTrue(lease["development_session"].is_active)
                return json.dumps(
                    {
                        "status": "completed",
                        "flow_id": flow_id,
                        "session_directory": str(child),
                        "dispatch": live,
                        "retained_transport_count": 2,
                        "proof_topology": "composite",
                        "terminal_reconciliation_topology": "continuous",
                        "causal_trace_count": 1,
                    }
                )

            png = b"ultimate-typed-initial"
            observation = {
                "device_state": "device",
                "foreground_package": pnsctl.PACKAGE,
                "native_width": 800,
                "native_height": 1280,
                "frame_sha256": hashlib.sha256(png).hexdigest(),
            }
            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                pnsctl, "BLUESTACKS_FLOW_IDS", (flow_id,)
            ), patch.object(
                pnsctl,
                "_load_bluestacks_flow_registry",
                return_value={flow_id: {"runner": "ultimate-runner"}},
            ), patch.dict(
                pnsctl._BLUESTACKS_FLOW_RUNNERS,
                {"ultimate-runner": runner},
            ), patch.object(
                pnsctl,
                "_development_runtime_observation",
                return_value=(observation, png),
            ), patch.object(
                boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"
            ):
                result = json.loads(
                    pnsctl.development_session_run_flow(
                        flow_id, live=True, yes=True, max_inputs=16
                    )
                )
            self.assertEqual(result["input_count"], 2)
            self.assertEqual(result["proof_topology"], "composite")
            self.assertTrue(result["persistent_checkpoint_artifacts_unchanged"])

    def test_direct_nova_praise_consumes_before_session_and_rejects_repeat(self) -> None:
        flow_id = registration.NOVA_FLOW_ID
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            checked_in = (
                Path(__file__).resolve().parents[1]
                / "tasks"
                / "flow_delivery_disabled_production_registry.json"
            )
            payload = json.loads(checked_in.read_text(encoding="utf-8"))
            disable_non_target_registrations(payload, flow_id)
            payload["flows"][flow_id] = {
                "production_handler": registration.NOVA_HANDLER_ID,
                "profile": registration.NOVA_PROFILE_ID,
                "supported_profiles": [registration.NOVA_PROFILE_ID],
                "mode": registration.NOVA_PHASE_MODE,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "product_id": registration.NOVA_PRODUCT_ID,
                "product_revision": registration.NOVA_PRODUCT_REVISION,
            }
            registry_path.write_text(json.dumps(payload), encoding="utf-8")
            identity_evidence = root / "identity.json"
            identity_evidence.write_text(
                json.dumps(
                    {
                        "account_id": "acct-1",
                        "server_id": "server-1",
                        "reset_id": "game-day-2026-08-25",
                        "assurance": "supervised_navigation_binding",
                        "evidence_refs": ["current-frame"],
                    }
                ),
                encoding="utf-8",
            )
            args = pnsctl.parser().parse_args(
                [
                    "nova-praise-pulse",
                    "--live",
                    "--yes",
                    "--supervised-live-opt-in",
                    "--scenario",
                    "nova_praise_one_free_pulse",
                    "--runtime-scope",
                    "bluestacks-dev-primary",
                    "--account-id",
                    "acct-1",
                    "--server-id",
                    "server-1",
                    "--reset-id",
                    "game-day-2026-08-25",
                    "--identity-evidence",
                    str(identity_evidence),
                ]
            )
            events: list[str] = []

            def registry_consumed() -> None:
                self.assertFalse(
                    any(
                        entry.registered
                        for entry in registration.load_disabled_registry(registry_path)
                    )
                )

            class FakeSession:
                def __init__(self, **_kwargs):
                    events.append("session_init")
                    registry_consumed()

                def __enter__(self):
                    events.append("session_enter")
                    return self

                def __exit__(self, *_args):
                    events.append("session_exit")

            def runner(route_args, _identity):
                events.append("runner")
                self.assertIsInstance(
                    route_args.registration_snapshot,
                    registration.RegisteredDispatchSnapshot,
                )
                self.assertFalse(
                    any(
                        entry.registered
                        for entry in registration.load_disabled_registry(registry_path)
                    )
                )
                return json.dumps(
                    {
                        "status": "blocked",
                        "reason": "recognition_needed",
                        "navigation_input_count": 0,
                        "praise_transport_calls": 0,
                        "session_directory": "",
                    }
                )

            def guard(*_args, **_kwargs):
                events.append("guard")
                self.assertFalse(
                    any(
                        entry.registered
                        for entry in registration.load_disabled_registry(registry_path)
                    )
                )

            args.output_directory = root / "output"
            args.action_database = root / "actions.sqlite3"
            with (
                patch.object(registration, "REGISTRY_PATH", registry_path),
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(pnsctl, "NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT", root / "output"),
                patch.object(pnsctl, "NOVA_SUPERVISED_ACTION_DATABASE", root / "actions.sqlite3"),
                patch.object(boundary, "NavigationDevelopmentSession", FakeSession),
                patch.object(pnsctl, "_create_nova_supervised_invocation_guard", side_effect=guard),
                patch.object(pnsctl, "_finalize_nova_supervised_invocation_guard"),
                patch(
                    "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                    side_effect=runner,
                ),
                patch(
                    "subprocess.run",
                    return_value=CompletedProcess(
                        ["git", "rev-parse", "HEAD"],
                        0,
                        stdout="a" * 40 + "\n",
                    ),
                ),
            ):
                args.output_directory = pnsctl.NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT
                args.action_database = pnsctl.NOVA_SUPERVISED_ACTION_DATABASE
                first = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(first["status"], "blocked")
                self.assertEqual(events, ["guard", "session_init", "session_enter", "runner", "session_exit"])
                with self.assertRaisesRegex(pnsctl.OperatorError, "not registered"):
                    pnsctl.nova_praise_pulse_live(args)
            self.assertFalse(
                any(
                    entry.registered
                    for entry in registration.load_disabled_registry(registry_path)
                )
            )


    def test_direct_nova_praise_persists_dispatch_evidence_in_all_artifacts(self) -> None:
        flow_id = registration.NOVA_FLOW_ID
        from safe_action_core import SafetyStore
        from tasks.nova_praise_pulse import NOVA_TASK_ID

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            checked_in = (
                Path(__file__).resolve().parents[1]
                / "tasks"
                / "flow_delivery_disabled_production_registry.json"
            )
            payload = json.loads(checked_in.read_text(encoding="utf-8"))
            disable_non_target_registrations(payload, flow_id)
            payload["flows"][flow_id] = {
                "production_handler": registration.NOVA_HANDLER_ID,
                "profile": registration.NOVA_PROFILE_ID,
                "supported_profiles": [registration.NOVA_PROFILE_ID],
                "mode": registration.NOVA_PHASE_MODE,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "product_id": registration.NOVA_PRODUCT_ID,
                "product_revision": registration.NOVA_PRODUCT_REVISION,
            }
            registry_path.write_text(json.dumps(payload), encoding="utf-8")
            identity_evidence = root / "identity.json"
            identity_evidence.write_text(
                json.dumps(
                    {
                        "account_id": "acct-1",
                        "server_id": "server-1",
                        "reset_id": "game-day-2026-08-25",
                        "assurance": "supervised_navigation_binding",
                        "evidence_refs": ["current-frame"],
                    }
                ),
                encoding="utf-8",
            )
            output = (
                root
                / ".local-captures"
                / "flow-delivery"
                / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
            )
            session = output / "nova-praise-one-free-pulse-20260825T000000000000Z"
            action_database = root / ".local-orchestrator" / "bluestacks-actions.sqlite3"
            args = pnsctl.parser().parse_args(
                [
                    "nova-praise-pulse",
                    "--live",
                    "--yes",
                    "--supervised-live-opt-in",
                    "--scenario",
                    "nova_praise_one_free_pulse",
                    "--runtime-scope",
                    "bluestacks-dev-primary",
                    "--account-id",
                    "acct-1",
                    "--server-id",
                    "server-1",
                    "--reset-id",
                    "game-day-2026-08-25",
                    "--identity-evidence",
                    str(identity_evidence),
                ]
            )
            observed_snapshot: dict[str, object] = {}

            def runner(route_args, _identity):
                self.assertIsInstance(
                    route_args.registration_snapshot,
                    registration.RegisteredDispatchSnapshot,
                )
                self.assertFalse(
                    any(
                        entry.registered
                        for entry in registration.load_disabled_registry(registry_path)
                    )
                )
                observed_snapshot.update(route_args.registration_snapshot.to_mapping())
                session.mkdir(parents=True)
                (session / "frame.png").write_bytes(b"native-frame")
                (session / "events.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps({"type": "navigation", "action": "open_lab"}),
                            json.dumps(
                                {
                                    "type": "dispatch",
                                    "consequential": True,
                                    "action_key": "nova-praise:key",
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (session / "ledger.jsonl").write_text(
                    json.dumps({"action": "navigation", "authorized": True}) + "\n",
                    encoding="utf-8",
                )
                (session / "journal.jsonl").write_text(
                    json.dumps(
                        {
                            "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                            "action_id": "nova-action",
                            "action_key": "nova-praise:key",
                            "journal_status": "confirmed",
                            "attempts_before": 6,
                            "attempts_after": 5,
                            "cooldown_seconds": 300,
                            "terminal_home_verified": True,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                runner_result = {
                    "schema_version": 1,
                    "flow_id": flow_id,
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "status": "completed",
                    "reason": "confirmed_praise_and_verified_safe_return_home",
                    "session_directory": str(session),
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 300,
                    "action_id": "nova-action",
                    "action_key": "nova-praise:key",
                    "journal_status": "confirmed",
                    "terminal_home_verified": True,
                    "evidence_refs": ["frame.png"],
                    "action_database": str(action_database),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                    "runner_marker": "preserved",
                }
                (session / "result.json").write_text(
                    json.dumps(runner_result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return json.dumps(runner_result)

            action_database.parent.mkdir(parents=True)
            store = SafetyStore(action_database)
            try:
                store.connection.execute(
                    """
                    INSERT INTO actions (
                        action_id, action_key, task_id, semantic_action, source_state,
                        target_identity, target_roi_json, source_frame_sha256,
                        source_frame_captured_at, runtime_profile_id, game_day_id,
                        expected_postcondition, consequence, cost_type, cost_amount,
                        quantity, consequential, policy_request_json, policy_decision,
                        policy_reason, prepared_at, input_attempt_at, transport_result_json,
                        reconciliation_result_json, evidence_refs_json, final_status,
                        final_reason, updated_at
                    ) VALUES (
                        ?, ?, ?, 'praise', 'nova_lab', 'nova', '[]', 'abc', 1.0,
                        'profile', ?, 'decrement', 'praise', 'none', 0, 1, 1, '{}',
                        'allow', 'ok', 1.0, 2.0, '{}', '{}', '[]', 'confirmed', 'ok', 3.0
                    )
                    """,
                    ("nova-action", "nova-praise:key", NOVA_TASK_ID, "game-day-2026-08-25"),
                )
                store.connection.commit()
            finally:
                store.close()

            args.output_directory = output
            args.action_database = action_database
            with (
                patch.object(registration, "REGISTRY_PATH", registry_path),
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(pnsctl, "NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT", output),
                patch.object(pnsctl, "NOVA_SUPERVISED_ACTION_DATABASE", action_database),
                patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"),
                patch.object(pnsctl, "_create_nova_supervised_invocation_guard"),
                patch.object(pnsctl, "_bind_nova_supervised_invocation_guard_session"),
                patch.object(pnsctl, "_finalize_nova_supervised_invocation_guard"),
                patch(
                    "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                    side_effect=runner,
                ),
                patch(
                    "subprocess.run",
                    return_value=CompletedProcess(
                        ["git", "rev-parse", "HEAD"],
                        0,
                        stdout="a" * 40 + "\n",
                    ),
                ),
            ):
                result = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(result["runner_marker"], "preserved")
                self.assertEqual(result["production_registration"], "REGISTERED")
                result_path = session / "result.json"
                delivery_path = session / "flow-delivery-result.json"
                trace_path = session / "causal-trace.json"
                retained = json.loads(result_path.read_text(encoding="utf-8"))
                delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                for artifact in (retained, delivery, trace):
                    self.assertEqual(artifact["registration_snapshot"], observed_snapshot)
                    self.assertEqual(artifact["dispatch_registration"], observed_snapshot)
                    self.assertFalse(artifact["scheduler_enabled"])
                self.assertEqual(retained["runner_marker"], "preserved")
                self.assertEqual(retained["causal_trace"], trace)
                self.assertEqual(delivery["causal_trace"], trace)
                mutated_trace = dict(trace)
                mutated_trace["proof_topology"] = "forged"
                trace_path.write_text(
                    json.dumps(mutated_trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "causal trace objects disagree"
                ):
                    pnsctl.bluestacks_verify_flow(session)
                trace_path.write_text(
                    json.dumps(trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                for field, forged_value in (("read_only", 1), ("input_authority", 0)):
                    typed_trace = dict(trace)
                    typed_trace[field] = forged_value
                    trace_path.write_text(
                        json.dumps(typed_trace, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        pnsctl.OperatorError, "causal trace objects disagree"
                    ):
                        pnsctl.bluestacks_verify_flow(session)
                trace_path.write_text(
                    json.dumps(trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                self.assertEqual(json.loads(pnsctl.bluestacks_verify_flow(session))["status"], "verified")
                trace_path.unlink()
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "causal-trace.json is required"
                ):
                    pnsctl.bluestacks_verify_flow(session)
                trace_path.write_text(
                    json.dumps(trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                forged_trace = dict(trace)
                forged_trace["dispatch_registration"] = {
                    **forged_trace["dispatch_registration"],
                    "product_id": "forged-product",
                }
                trace_path.write_text(
                    json.dumps(forged_trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "forged|disagree"
                ):
                    pnsctl.bluestacks_verify_flow(session)

                trace_path.write_text(
                    json.dumps(trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                forged = dict(delivery)
                forged["dispatch_registration"] = {
                    **forged["dispatch_registration"],
                    "product_id": "forged-product",
                }
                delivery_path.write_text(
                    json.dumps(forged, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "forged|disagree"
                ):
                    pnsctl.bluestacks_verify_flow(session)

            self.assertFalse(
                any(
                    entry.registered
                    for entry in registration.load_disabled_registry(registry_path)
                )
            )
if __name__ == "__main__":
    unittest.main()
