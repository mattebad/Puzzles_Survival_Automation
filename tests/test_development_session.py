from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    LocalBlueStacksRuntime,
)


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
    def test_ordinary_action_categories_include_complete_gameplay_classes(self):
        self.assertTrue(
            {
                "navigation",
                "combat",
                "claim",
                "reward",
                "in_game_currency",
                "recovery",
            }.issubset(boundary.ORDINARY_DEVELOPMENT_ACTIONS)
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

    def test_pnsctl_flow_session_avoids_queue_and_preserves_checkpoint_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = tuple(root / name for name in ("BACKLOG.md", "queue.json", "handoff.md"))
            for path in checkpoints:
                path.write_text(path.name, encoding="utf-8")
            child = root / "child"
            child.mkdir()
            (child / "events.jsonl").write_text(
                json.dumps({"type": "dispatch"}) + "\n" + json.dumps({"type": "capture"}) + "\n",
                encoding="utf-8",
            )

            def runner(queue, lease, *, live=True):
                self.assertEqual(queue, {"active_flow_id": "FLOW", "development_session": True})
                self.assertEqual(lease["unresolved_action_state"], "not_applicable")
                return json.dumps(
                    {"status": "completed", "session_directory": str(child), "dispatch": live}
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


if __name__ == "__main__":
    unittest.main()
