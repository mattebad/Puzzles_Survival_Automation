from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from safe_action_core import SafetyStore
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts.startup_recovery import (
    StartupRecoveryError,
    classify_startup_frame,
    recover_known_startup_overlay,
)


TARGET = (263, 781, 537, 869)


def popup(*, target=TARGET) -> dict[str, object]:
    return {
        "recognized": True,
        "popup_identity": "VIP_POINTS_GET_PTS",
        "target_identity": "reset-popup-close",
        "target": target,
        "target_center": (400, 825),
    }


class FakeRuntime:
    def __init__(self, root: Path, *, max_inputs: int = 12) -> None:
        self.session = root
        self.session.mkdir()
        self.max_inputs = max_inputs
        self.input_count = 0
        self.ordinal = 0
        self.started = time.monotonic()
        self.keys: set[str] = set()
        self.reconciliations: list[str] = []

    def capture(self, label: str) -> CapturedNativeFrame:
        self.ordinal += 1
        frame = np.full((1280, 800, 3), self.ordinal, np.uint8)
        payload = f"{label}:{self.ordinal}".encode()
        path = self.session / f"{self.ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        return CapturedNativeFrame(
            frame,
            payload,
            hashlib.sha256(payload).hexdigest(),
            self.started + self.ordinal * 0.001,
            path,
        )

    def tap(self, source, *, target_identity, target_roi, action_key, **_kwargs) -> None:
        if action_key in self.keys:
            raise RuntimeError("duplicate action key")
        if self.input_count >= self.max_inputs:
            raise RuntimeError("input limit reached")
        self.keys.add(action_key)
        self.input_count += 1

    def reconcile(self, _action_key, status, _post, _reason) -> None:
        self.reconciliations.append(status)


class StartupRecoveryTests(unittest.TestCase):
    def _recover(self, runtime: FakeRuntime, **kwargs):
        return recover_known_startup_overlay(
            runtime,
            recovery_scope="test-reset",
            action_store_factory=lambda: SafetyStore(
                runtime.session / "test-startup-actions.sqlite3"
            ),
            **kwargs,
        )

    def test_observation_only_seam_assigns_explicit_recovery_ownership(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "assets"
            / "navigation"
            / "800x1280"
            / "reset_popup_source.png"
        ).read_bytes()
        recruitment = classify_startup_frame(
            "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE",
            fixture,
        )
        world = classify_startup_frame("WORLD-MAP-NAVIGATION-FOUNDATION", fixture)
        daily_row = classify_startup_frame(
            "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
            fixture,
        )
        unsupported = classify_startup_frame("NEW-FLOW-WITHOUT-RECOVERY", fixture)

        self.assertEqual(recruitment.status, "recovery_required")
        self.assertEqual(recruitment.recovery_owner, "shared_home_startup_recovery")
        self.assertFalse(recruitment.input_authority)
        self.assertEqual(world.status, "route_owned")
        self.assertEqual(world.recovery_owner, "flow_specific_popup_recovery")
        self.assertEqual(daily_row.status, "blocked")
        self.assertEqual(unsupported.status, "blocked")
        self.assertIsNone(unsupported.recovery_owner)

    def test_non_popup_is_observation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value={"recognized": False},
            ):
                result = self._recover(
                    runtime,
                    task_id="FLOW",
                    recognize_successor=lambda _frame: False,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(result.status, "not_present")
        self.assertEqual(result.input_count, 0)
        self.assertEqual(runtime.input_count, 0)

    def test_exact_popup_closes_once_and_requires_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), {"recognized": False}),
            ):
                result = self._recover(
                    runtime,
                    task_id="FLOW",
                    recognize_successor=lambda _frame: True,
                    sleep=lambda _seconds: None,
                )
            self.assertTrue((runtime.session / "startup-recovery-result.json").is_file())
        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.input_count, 1)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["confirmed"])

    def test_persistent_popup_is_terminal_after_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), popup()),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "failed after dispatch"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: False,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.reconciliations, ["unresolved"])

    def test_target_drift_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            moved = (270, 781, 544, 869)
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(target=moved)),
            ):
                with self.assertRaises(StartupRecoveryError):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 0)

    def test_unknown_successor_is_terminal_after_one_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime")
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                side_effect=(popup(), popup(), popup(), {"recognized": False}),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "failed after dispatch"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: False,
                        sleep=lambda _seconds: None,
                    )
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(
                    StartupRecoveryError,
                    "occurrence_already_recorded",
                ):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)

    def test_exhausted_budget_blocks_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(Path(directory) / "runtime", max_inputs=1)
            runtime.input_count = 1
            with patch(
                "scripts.startup_recovery.recognize_reset_popup",
                return_value=popup(),
            ):
                with self.assertRaisesRegex(StartupRecoveryError, "budget is exhausted"):
                    self._recover(
                        runtime,
                        task_id="FLOW",
                        recognize_successor=lambda _frame: True,
                        sleep=lambda _seconds: None,
                    )
        self.assertEqual(runtime.input_count, 1)


if __name__ == "__main__":
    unittest.main()
