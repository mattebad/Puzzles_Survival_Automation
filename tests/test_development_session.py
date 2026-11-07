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
from automation_service.registry import RUINS_FLOW_ID
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
)
from scripts.startup_recovery import StartupRecoveryPlan
from tasks.runtime_identity import BLUESTACKS_PACKAGE, BLUESTACKS_SERIAL


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

    def test_retired_ruins_flow_is_rejected_before_runtime_acquisition(self):
        with patch.object(
            pnsctl, "_development_runtime_observation",
            side_effect=AssertionError("retired flow must not observe the device"),
        ), patch.object(
            boundary, "DevelopmentSession",
            side_effect=AssertionError("retired flow must not acquire a session"),
        ):
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_run_flow(
                    RUINS_FLOW_ID, live=False, yes=False,
                )

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
                "foreground_package": BLUESTACKS_PACKAGE,
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
                "foreground_package": BLUESTACKS_PACKAGE,
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
                "foreground_package": BLUESTACKS_PACKAGE,
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
        import cv2

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
            # A fresh pixel identity must leave the budget fence, not the
            # duplicate-frame fence, responsible for denying the third input.
            changed_png = cv2.imencode(".png", np.ones((1280, 800, 3), np.uint8))[1].tobytes()
            with patch.object(runner, "capture_png", return_value=changed_png):
                final = runtime.capture("final")
            with self.assertRaisesRegex(RuntimeError, "input limit"):
                runtime.back(final, action_key="back-3")
            self.assertEqual((len(runner.taps), runner.backs), (1, 1))
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
                            "foreground_package": BLUESTACKS_PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(source).hexdigest(),
                        },
                        source,
                    ),
                    (
                        {
                            "device_state": "device",
                            "foreground_package": BLUESTACKS_PACKAGE,
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
                    "action_key": "startup-recovery:scarlett-close",
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

    def test_pnsctl_adapter_exception_retains_shared_recovery_actions(self):
        for count in (1, 2):
            with self.subTest(recovery_inputs=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, post = b"startup-source", b"post-recovery-source"
                def observation(payload):
                    return ({"device_state": "device", "foreground_package": BLUESTACKS_PACKAGE,
                             "native_width": 800, "native_height": 1280,
                             "frame_sha256": hashlib.sha256(payload).hexdigest()}, payload)
                observations = iter((observation(source), observation(post)))
                plan = StartupRecoveryPlan(
                    "recovery_required", "FLOW", "SCARLETT_THREE_DAY_PACK",
                    "shared_startup_surface_recovery", False, "known startup surface",
                )
                actions = [
                    {"status": "recovered", "input_count": 1,
                     "action_key": f"startup-action-{i}", "popup_identity": f"popup-{i}",
                     "before_sha256": "a" * 64, "after_sha256": "b" * 64}
                    for i in range(count)
                ]
                recovery = {"status": "recovered", "input_count": count,
                            "recovery_input_count": count, "actions": actions}
                def runner(_queue, lease, *, live=True):
                    self.assertEqual(lease["route_max_inputs"], 3 - count)
                    raise RuntimeError("adapter rejected input budget")
                with patch.object(pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"), \
                     patch.object(pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()), \
                     patch.object(pnsctl, "BLUESTACKS_FLOW_IDS", ("FLOW",)), \
                     patch.object(pnsctl, "_load_bluestacks_flow_registry", return_value={"FLOW": {"runner": "runner"}}), \
                     patch.dict(pnsctl._BLUESTACKS_FLOW_RUNNERS, {"runner": runner}), \
                     patch.object(pnsctl, "_development_runtime_observation", side_effect=observations), \
                     patch.object(pnsctl, "_run_shared_startup_recovery", return_value=recovery), \
                     patch("scripts.startup_recovery.classify_startup_frame", return_value=plan), \
                     patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "runtime-lock.sqlite3"):
                    with self.assertRaisesRegex(RuntimeError, "adapter rejected input budget"):
                        pnsctl.development_session_run_flow("FLOW", live=True, yes=True, max_inputs=3)
                session = next((root / "sessions").iterdir())
                summary = json.loads((session / "summary.json").read_text(encoding="utf-8"))
                rows = [json.loads(line) for line in (session / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(summary["status"], "failed")
                self.assertEqual(summary["input_count"], count)
                self.assertEqual(summary["action_count"], count)
                self.assertTrue(summary["ownership_released"])
                self.assertIn("adapter rejected input budget", summary["blocker"])
                self.assertEqual([row["action_key"] for row in rows],
                                 [action["action_key"] for action in actions])

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
                            "foreground_package": BLUESTACKS_PACKAGE,
                            "native_width": 800,
                            "native_height": 1280,
                            "frame_sha256": hashlib.sha256(source).hexdigest(),
                        },
                        source,
                    ),
                    (
                        {
                            "device_state": "device",
                            "foreground_package": BLUESTACKS_PACKAGE,
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
                    "action_key": "startup-recovery:scarlett-close",
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
            self.assertFalse(result["result"]["terminal_home_verified"])
            summary = json.loads(
                (Path(result["session_directory"]) / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["input_count"], 1)
            self.assertFalse(result["terminal_home_verified"])
            self.assertFalse(summary["terminal_home_verified"])
            self.assertFalse(summary["control_memory"]["terminal_home_verified"])
            self.assertTrue(summary["ownership_released"])
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
                "foreground_package": BLUESTACKS_PACKAGE,
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
                    "action_key": "startup-recovery:scarlett-close",
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
                        "FLOW", live=True, yes=True, max_inputs=1
                    )
                )

            self.assertEqual(route_calls, [])
            self.assertEqual(result["status"], "evidence_required")
            self.assertEqual(result["recovery_input_count"], 1)
            self.assertEqual(result["route_input_count"], 0)
            self.assertEqual(result["total_input_count"], 1)
            self.assertFalse(result["result"]["terminal_home_verified"])
            summary = json.loads(
                (Path(result["session_directory"]) / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(summary["status"], "evidence_required")
            self.assertEqual(
                summary["blocker"], "evidence_required_unknown_scarlett_successor"
            )
            self.assertFalse(result["terminal_home_verified"])
            self.assertFalse(summary["terminal_home_verified"])
            self.assertTrue(summary["ownership_released"])
            self.assertFalse(
                summary["control_memory"]["terminal_home_verified"]
            )

    def test_pnsctl_flow_session_avoids_queue_and_preserves_checkpoint_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = (
                root / "docs" / "archive" / "backlog-legacy.md",
                root / "queue.json",
                root / "handoff.md",
            )
            checkpoints[0].parent.mkdir(parents=True)
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
                "foreground_package": BLUESTACKS_PACKAGE,
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
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(result["transport_attempted_count"], 1)
            self.assertEqual(result["semantic_completed_count"], 0)
            action = json.loads(
                (Path(result["session_directory"]) / "actions.jsonl").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(action["action_class"], "ordinary_development")
            self.assertEqual(action["before_sha256"], "a" * 64)
            self.assertEqual(action["after_sha256"], "b" * 64)
            self.assertFalse(action["semantic_completed"])

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
                "foreground_package": BLUESTACKS_PACKAGE,
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



class GenericFlowStructureTests(unittest.TestCase):
    def test_reconciliation_terminal_accepts_declared_causal_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "campaign-reconciliation"
            session.mkdir(parents=True)
            (session / "frame.png").write_bytes(b"native-frame")
            (session / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (session / "causal-trace.json").write_text("{}\n", encoding="utf-8")
            result = {
                "schema_version": 1,
                "flow_id": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
                "status": "effect_reconciliation_required",
                "effect_reconciliation_required": True,
                "serial": BLUESTACKS_SERIAL,
                "native_width": pnsctl.BLUESTACKS_NATIVE_WIDTH,
                "native_height": pnsctl.BLUESTACKS_NATIVE_HEIGHT,
                "runtime_owner": "pnsctl-development-session:test",
                "terminal_runtime_state": "safe_blocked_terminal",
                "actions": [],
                "frames": ["frame.png"],
                "required_artifacts": ["events_path", "causal_trace_path"],
                "events_path": "events.jsonl",
                "causal_trace_path": "causal-trace.json",
            }
            result_path = session / "flow-delivery-result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")

            with patch.object(pnsctl, "REPO_ROOT", root):
                verified = pnsctl._verify_flow_structure(session)
                self.assertEqual(
                    verified["artifacts"]["causal_trace_path"],
                    "causal-trace.json",
                )
                result["effect_reconciliation_required"] = False
                result_path.write_text(json.dumps(result), encoding="utf-8")
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "not terminally completed"
                ):
                    pnsctl._verify_flow_structure(session)


if __name__ == "__main__":
    unittest.main()
